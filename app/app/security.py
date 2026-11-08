"""
Segurança: hash de senhas (Argon2id), política de senha, sessões no servidor,
proteção CSRF, controle de acesso por perfil e limitação de tentativas de login.
"""

import hashlib
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Deque, Dict, Iterable, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Sessao, Usuario

COOKIE_NAME = "na_sessao"
CSRF_HEADER = "X-CSRF-Token"

_hasher = PasswordHasher()  # Argon2id com parâmetros recomendados pela biblioteca

# Hash "fantasma" para equalizar o tempo de resposta quando o usuário não existe
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


# =============================================================================
# SENHAS
# =============================================================================

def hash_password(senha: str) -> str:
    return _hasher.hash(senha)


def verify_password(senha_hash: Optional[str], senha: str) -> bool:
    if not senha_hash or senha_hash == "!":
        try:
            _hasher.verify(_DUMMY_HASH, senha)
        except Exception:
            pass
        return False
    try:
        return _hasher.verify(senha_hash, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_policy_error(senha: str, usuario: str = "", nome: str = "", cpf: str = "") -> Optional[str]:
    """Retorna a mensagem de erro se a senha não atender à política; None se estiver ok."""
    if not senha or len(senha) < 10:
        return "A senha deve ter no mínimo 10 caracteres."
    if len(senha) > 128:
        return "A senha deve ter no máximo 128 caracteres."
    if not re.search(r"[A-Za-z]", senha) or not re.search(r"\d", senha):
        return "A senha deve conter letras e números."
    baixa = senha.lower()
    if usuario and usuario.lower() in baixa:
        return "A senha não pode conter o nome de usuário."
    digitos = re.sub(r"\D", "", senha)
    if cpf and len(cpf) == 11 and cpf in digitos:
        return "A senha não pode conter o CPF."
    for parte in (nome or "").lower().split():
        if len(parte) >= 4 and parte in baixa:
            return "A senha não pode conter partes do seu nome."
    if baixa in {"admin12345", "senha12345", "1234567890a", "inca123456", "abc1234567"}:
        return "Senha muito comum. Escolha outra."
    return None


def generate_temp_password() -> str:
    """Senha temporária forte (o usuário é obrigado a trocar no primeiro acesso)."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    while True:
        s = "".join(secrets.choice(alfabeto) for _ in range(14))
        if re.search(r"\d", s) and re.search(r"[A-Za-z]", s):
            return s


# =============================================================================
# SESSÕES
# =============================================================================

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, usuario: Usuario, ip: str, user_agent: str) -> tuple:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    agora = datetime.now()
    db.add(
        Sessao(
            token_hash=_hash_token(token),
            csrf_token=csrf,
            usuario_id=usuario.id,
            criado_em=agora,
            ultimo_acesso=agora,
            ip=(ip or "")[:64],
            user_agent=(user_agent or "")[:200],
        )
    )
    # Limpeza oportunista de sessões expiradas
    limite = agora - timedelta(hours=settings.sessao_maxima_horas)
    db.execute(delete(Sessao).where(Sessao.criado_em < limite))
    return token, csrf


def destroy_session(db: Session, token: Optional[str]) -> None:
    if token:
        db.execute(delete(Sessao).where(Sessao.token_hash == _hash_token(token)))


def destroy_user_sessions(db: Session, usuario_id: int, exceto_token: Optional[str] = None) -> None:
    stmt = delete(Sessao).where(Sessao.usuario_id == usuario_id)
    if exceto_token:
        stmt = stmt.where(Sessao.token_hash != _hash_token(exceto_token))
    db.execute(stmt)


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        max_age=settings.sessao_maxima_horas * 3600,
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")


def client_ip(request: Request) -> str:
    # O Uvicorn já resolve X-Forwarded-For (vindo do Nginx) em request.client
    return request.client.host if request.client else ""


class CurrentUser:
    def __init__(self, usuario: Usuario, sessao: Sessao):
        self.usuario = usuario
        self.sessao = sessao

    @property
    def id(self) -> int:
        return self.usuario.id

    @property
    def perfil(self) -> str:
        return self.usuario.perfil


def _load_session(request: Request, db: Session) -> Optional[CurrentUser]:
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 200:
        return None
    sessao = db.execute(select(Sessao).where(Sessao.token_hash == _hash_token(token))).scalar_one_or_none()
    if not sessao:
        return None
    agora = datetime.now()
    expirada = (
        agora - sessao.ultimo_acesso > timedelta(minutes=settings.sessao_inatividade_min)
        or agora - sessao.criado_em > timedelta(hours=settings.sessao_maxima_horas)
    )
    usuario = db.get(Usuario, sessao.usuario_id)
    if expirada or not usuario or not usuario.ativo:
        db.delete(sessao)
        db.commit()
        return None
    # Atualiza o último acesso no máximo a cada 30 s (evita escrita a cada requisição).
    # Atualizações automáticas do Painel ao vivo (X-Auto-Refresh) NÃO renovam a sessão:
    # uma tela esquecida aberta continua expirando por inatividade.
    automatica = request.headers.get("X-Auto-Refresh") == "1"
    if not automatica and (agora - sessao.ultimo_acesso).total_seconds() > 30:
        sessao.ultimo_acesso = agora
        db.commit()
    return CurrentUser(usuario, sessao)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    user = _load_session(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Sessão expirada ou inexistente. Faça login novamente.")
    # Proteção CSRF para qualquer método que altera dados
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        enviado = request.headers.get(CSRF_HEADER, "")
        if not enviado or not secrets.compare_digest(enviado, user.sessao.csrf_token):
            raise HTTPException(status_code=403, detail="Falha de verificação de segurança (CSRF). Recarregue a página.")
    # Usuário com senha temporária só pode trocar a senha
    if user.usuario.trocar_senha and not request.url.path.startswith("/api/auth/"):
        raise HTTPException(status_code=403, detail="Troque sua senha temporária para continuar.")
    return user


def require_roles(*perfis: str):
    permitidos = set(perfis)

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.perfil not in permitidos:
            raise HTTPException(status_code=403, detail="Acesso negado para o seu perfil.")
        return user

    return _dep


# Atalhos de permissão
LEITURA = ("ADMIN", "ENFERMEIRO", "GESTOR")
OPERACAO = ("ADMIN", "ENFERMEIRO")
GESTAO = ("ADMIN", "GESTOR")
SO_ADMIN = ("ADMIN",)


def permissoes_do_perfil(perfil: str) -> Dict[str, bool]:
    admin = perfil == "ADMIN"
    enf = perfil == "ENFERMEIRO"
    gestor = perfil == "GESTOR"
    return {
        "agenda_ver": True,
        "agenda_editar": admin or enf,
        "mural": True,
        "pacientes_ver": True,
        "pacientes_editar": admin or enf,
        "intercorrencias_ver": True,
        "intercorrencias_editar": admin or enf,
        "estatisticas_ver": True,
        "estatisticas_editar": admin or enf,
        "mapa_calor": True,
        "dashboards": True,
        "protocolos_editar": admin,
        "usuarios": admin,
        "log_auditoria": admin,
    }


# =============================================================================
# LIMITADOR DE TENTATIVAS POR IP (complementa o bloqueio por conta)
# =============================================================================

class RateLimiter:
    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Registra uma tentativa; retorna False se o limite foi excedido."""
        agora = time.monotonic()
        with self._lock:
            fila = self._hits[key]
            while fila and agora - fila[0] > self.window:
                fila.popleft()
            if len(fila) >= self.max_hits:
                return False
            fila.append(agora)
            if len(self._hits) > 10000:  # evita crescimento ilimitado de memória
                self._hits.clear()
            return True

    def reset(self, keys: Iterable[str] = ()) -> None:
        with self._lock:
            if not keys:
                self._hits.clear()
            for k in keys:
                self._hits.pop(k, None)


login_ip_limiter = RateLimiter(max_hits=20, window_seconds=300)
