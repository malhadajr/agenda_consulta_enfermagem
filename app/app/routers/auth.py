"""Login, sessão, logout e troca de senha."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Usuario
from app.security import (
    COOKIE_NAME,
    CurrentUser,
    clear_session_cookie,
    client_ip,
    create_session,
    destroy_session,
    destroy_user_sessions,
    get_current_user,
    hash_password,
    login_ip_limiter,
    password_policy_error,
    permissoes_do_perfil,
    set_session_cookie,
    verify_password,
)
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

ERRO_LOGIN = "Usuário ou senha inválidos."


class LoginIn(BaseModel):
    usuario: str = Field(min_length=1, max_length=60)
    senha: str = Field(min_length=1, max_length=128)


class TrocaSenhaIn(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=128)
    nova_senha: str = Field(min_length=1, max_length=128)


def _perfil_publico(u: Usuario, csrf: str) -> dict:
    return {
        "ok": True,
        "csrf": csrf,
        "user": {
            "id": u.id,
            "usuario": u.usuario,
            "nome": u.nome,
            "perfil": u.perfil,
            "trocar_senha": u.trocar_senha,
            "permissoes": permissoes_do_perfil(u.perfil),
        },
        "sessao_inatividade_min": settings.sessao_inatividade_min,
    }


@router.post("/login")
def login(dados: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not login_ip_limiter.hit(ip):
        audit.registrar(db, "LOGIN_LIMITE_IP", resultado="BLOQUEADO", ip=ip, usuario_login=dados.usuario[:60], commit=True)
        return JSONResponse(status_code=429, content={"ok": False, "erro": "Muitas tentativas. Aguarde alguns minutos."})

    login_norm = dados.usuario.strip().lower()
    u = db.execute(select(Usuario).where(func.lower(Usuario.usuario) == login_norm)).scalar_one_or_none()
    agora = datetime.now()

    if u and u.bloqueado_ate and u.bloqueado_ate > agora:
        verify_password(None, dados.senha)  # tempo de resposta constante
        audit.registrar(db, "LOGIN_CONTA_BLOQUEADA", usuario=u, resultado="BLOQUEADO", ip=ip, commit=True)
        return JSONResponse(status_code=423, content={
            "ok": False, "erro": "Conta temporariamente bloqueada por tentativas erradas. Tente mais tarde ou procure o administrador."})

    # A verificação Argon2 sempre roda (mesmo se o usuário não existir) para não revelar logins válidos pelo tempo
    senha_ok = verify_password(u.senha_hash if u and u.ativo else None, dados.senha)
    if not u or not u.ativo or not senha_ok:
        if u and u.ativo:
            u.tentativas_falhas = (u.tentativas_falhas or 0) + 1
            if u.tentativas_falhas >= settings.login_max_tentativas:
                u.bloqueado_ate = agora + timedelta(minutes=settings.login_bloqueio_min)
                u.tentativas_falhas = 0
                audit.registrar(db, "CONTA_BLOQUEADA", usuario=u, resultado="BLOQUEADO", ip=ip)
        audit.registrar(db, "LOGIN_FALHA", usuario=u, usuario_login=None if u else dados.usuario[:60],
                        resultado="FALHA", ip=ip, commit=True)
        return JSONResponse(status_code=401, content={"ok": False, "erro": ERRO_LOGIN})

    u.tentativas_falhas = 0
    u.bloqueado_ate = None
    u.ultimo_login = agora
    token, csrf = create_session(db, u, ip, request.headers.get("user-agent", ""))
    audit.registrar(db, "LOGIN", usuario=u, ip=ip)
    db.commit()
    payload = _perfil_publico(u, csrf)
    resp = JSONResponse(content=payload)
    set_session_cookie(resp, token)
    return resp


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return _perfil_publico(user.usuario, user.sessao.csrf_token)


@router.post("/logout")
def logout(request: Request, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    audit.registrar(db, "LOGOUT", usuario=user, ip=client_ip(request))
    destroy_session(db, request.cookies.get(COOKIE_NAME))
    db.commit()
    resp = JSONResponse(content={"ok": True})
    clear_session_cookie(resp)
    return resp


@router.post("/trocar-senha")
def trocar_senha(dados: TrocaSenhaIn, request: Request, user: CurrentUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    u = db.get(Usuario, user.id)
    if not verify_password(u.senha_hash, dados.senha_atual):
        audit.registrar(db, "TROCA_SENHA", usuario=u, resultado="FALHA", ip=client_ip(request), commit=True)
        return JSONResponse(status_code=400, content={"ok": False, "erro": "A senha atual está incorreta."})
    if dados.nova_senha == dados.senha_atual:
        return JSONResponse(status_code=400, content={"ok": False, "erro": "A nova senha deve ser diferente da atual."})
    erro = password_policy_error(dados.nova_senha, u.usuario, u.nome, u.cpf or "")
    if erro:
        return JSONResponse(status_code=400, content={"ok": False, "erro": erro})
    u.senha_hash = hash_password(dados.nova_senha)
    u.trocar_senha = False
    destroy_user_sessions(db, u.id, exceto_token=request.cookies.get(COOKIE_NAME))
    audit.registrar(db, "TROCA_SENHA", usuario=u, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Senha alterada com sucesso."}
