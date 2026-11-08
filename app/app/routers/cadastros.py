"""Catálogos (protocolos, intercorrências), usuários/permissões, metadados da tela e consulta de endereço."""

import re
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import PERFIS, Protocolo, TipoIntercorrencia, Usuario
from app.security import (
    LEITURA,
    OPERACAO,
    SO_ADMIN,
    CurrentUser,
    client_ip,
    destroy_user_sessions,
    generate_temp_password,
    hash_password,
    require_roles,
)
from app.services import audit, endereco
from app.services import pacientes as pac_svc
from app.services.agenda import lista_boxes
from app.services.common import RegraNegocio, usuario_dict
from app.services.validators import (
    GRADE_HORARIOS_PADRAO,
    clean_text,
    normalize_cpf,
    validate_and_format_phone,
    validate_and_format_time_hhmm,
    validate_cpf,
)

router = APIRouter(prefix="/api", tags=["cadastros"])

USUARIO_RE = re.compile(r"^[a-z0-9._-]{3,60}$")


# =============================================================================
# METADADOS PARA A TELA
# =============================================================================

@router.get("/metadata")
def metadata(_u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    protocolos = db.execute(select(Protocolo).where(Protocolo.ativo.is_(True)).order_by(Protocolo.nome)).scalars()
    tipos = db.execute(select(TipoIntercorrencia).where(TipoIntercorrencia.ativo.is_(True)).order_by(TipoIntercorrencia.nome)).scalars()
    enfermeiros = db.execute(
        select(Usuario).where(Usuario.ativo.is_(True), Usuario.perfil.in_(("ENFERMEIRO", "ADMIN"))).order_by(Usuario.nome)
    ).scalars()
    return {
        "ok": True,
        "instituicao": settings.nome_instituicao,
        "qtd_poltronas": settings.qtd_poltronas,
        "horas_funcionamento_dia": settings.horas_funcionamento_dia,
        "contagens": pac_svc.contagens(db),
        "protocolos": [{"protocolo": p.nome, "tempo_estimado": p.tempo_estimado} for p in protocolos],
        "intercorrencias": [t.nome for t in tipos],
        "enfermeiros": [{"id": u.id, "nome": u.nome, "coren": u.coren or ""} for u in enfermeiros],
        "listas": {
            "boxes": lista_boxes(),
            "horarios_padrao": GRADE_HORARIOS_PADRAO,
            "motivos_encerramento": ["DESISTÊNCIA", "CURA", "MORTE"],
            "tipos_sanguineos": list(pac_svc.TIPOS_SANGUINEOS),
            "fatores_rh": list(pac_svc.FATORES_RH),
            "ufs": list(pac_svc.UFS),
            "perfis": list(PERFIS),
        },
    }


# =============================================================================
# ENDEREÇO (CEP)
# =============================================================================

@router.get("/endereco/cep")
def cep(cep: str = Query(..., max_length=10), _u: CurrentUser = Depends(require_roles(*OPERACAO))):
    return endereco.buscar_cep(cep)


@router.get("/endereco/logradouro")
def logradouro(uf: str = Query("", max_length=2), cidade: str = Query("", max_length=80),
               logradouro: str = Query(..., max_length=80), _u: CurrentUser = Depends(require_roles(*OPERACAO))):
    return endereco.buscar_logradouro(uf, cidade, logradouro)


# =============================================================================
# PROTOCOLOS
# =============================================================================

class ProtocoloIn(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    tempo_estimado: str = Field(max_length=5)
    ativo: bool = True


@router.get("/protocolos")
def listar_protocolos(_u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    itens = db.execute(select(Protocolo).order_by(Protocolo.nome)).scalars()
    return {"ok": True, "protocolos": [{"id": p.id, "nome": p.nome, "tempo_estimado": p.tempo_estimado, "ativo": p.ativo} for p in itens]}


def _validar_protocolo(db: Session, dados: ProtocoloIn, pid: Optional[int] = None) -> tuple:
    nome = clean_text(dados.nome, 160)
    ok, tempo = validate_and_format_time_hhmm(dados.tempo_estimado)
    if not ok or not tempo:
        raise RegraNegocio("Tempo estimado inválido. Use HH:MM (ex.: 02:30).")
    dup = db.execute(select(Protocolo).where(func.upper(Protocolo.nome) == nome.upper())).scalar_one_or_none()
    if dup and dup.id != pid:
        raise RegraNegocio("Já existe um protocolo com este nome.", "DUPLICADO", 409)
    return nome, tempo


@router.post("/protocolos")
def criar_protocolo(dados: ProtocoloIn, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
                    db: Session = Depends(get_db)):
    nome, tempo = _validar_protocolo(db, dados)
    p = Protocolo(nome=nome, tempo_estimado=tempo, ativo=dados.ativo)
    db.add(p)
    db.flush()
    audit.registrar(db, "CRIAR_PROTOCOLO", usuario=user, entidade="protocolo", entidade_id=p.id, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Protocolo cadastrado."}


@router.put("/protocolos/{pid}")
def alterar_protocolo(pid: int, dados: ProtocoloIn, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
                      db: Session = Depends(get_db)):
    p = db.get(Protocolo, pid)
    if not p:
        raise RegraNegocio("Protocolo não encontrado.", "NAO_ENCONTRADO", 404)
    nome, tempo = _validar_protocolo(db, dados, pid)
    if nome != p.nome:
        raise RegraNegocio("Para manter o histórico, o nome do protocolo não pode ser alterado. Desative-o e cadastre um novo.")
    p.tempo_estimado, p.ativo = tempo, dados.ativo
    audit.registrar(db, "ALTERAR_PROTOCOLO", usuario=user, entidade="protocolo", entidade_id=p.id, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Protocolo atualizado."}


# =============================================================================
# TIPOS DE INTERCORRÊNCIA
# =============================================================================

class TipoIn(BaseModel):
    nome: str = Field(min_length=3, max_length=200)
    ativo: bool = True


@router.get("/tipos-intercorrencia")
def listar_tipos(_u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    itens = db.execute(select(TipoIntercorrencia).order_by(TipoIntercorrencia.nome)).scalars()
    return {"ok": True, "tipos": [{"id": t.id, "nome": t.nome, "ativo": t.ativo} for t in itens]}


@router.post("/tipos-intercorrencia")
def criar_tipo(dados: TipoIn, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
               db: Session = Depends(get_db)):
    nome = clean_text(dados.nome, 200)
    if db.execute(select(TipoIntercorrencia).where(func.upper(TipoIntercorrencia.nome) == nome.upper())).scalar_one_or_none():
        raise RegraNegocio("Este tipo de intercorrência já existe.", "DUPLICADO", 409)
    t = TipoIntercorrencia(nome=nome, ativo=dados.ativo)
    db.add(t)
    db.flush()
    audit.registrar(db, "CRIAR_TIPO_INTERCORRENCIA", usuario=user, entidade="tipo_intercorrencia", entidade_id=t.id,
                    ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Tipo de intercorrência cadastrado."}


@router.put("/tipos-intercorrencia/{tid}")
def alterar_tipo(tid: int, dados: TipoIn, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
                 db: Session = Depends(get_db)):
    t = db.get(TipoIntercorrencia, tid)
    if not t:
        raise RegraNegocio("Tipo não encontrado.", "NAO_ENCONTRADO", 404)
    t.ativo = dados.ativo
    audit.registrar(db, "ALTERAR_TIPO_INTERCORRENCIA", usuario=user, entidade="tipo_intercorrencia", entidade_id=t.id,
                    ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Tipo de intercorrência atualizado."}


# =============================================================================
# USUÁRIOS E PERMISSÕES
# =============================================================================

class UsuarioIn(BaseModel):
    usuario: str = Field(min_length=3, max_length=60)
    nome: str = Field(min_length=3, max_length=160)
    perfil: str = Field(max_length=20)
    matricula: Optional[str] = Field(default="", max_length=30)
    cpf: Optional[str] = Field(default="", max_length=14)
    coren: Optional[str] = Field(default="", max_length=30)
    telefone: Optional[str] = Field(default="", max_length=20)
    email: Optional[str] = Field(default="", max_length=160)
    ativo: bool = True


def _validar_usuario(db: Session, dados: UsuarioIn, uid: Optional[int] = None) -> dict:
    login = dados.usuario.strip().lower()
    if not USUARIO_RE.match(login):
        raise RegraNegocio("Usuário deve ter 3 a 60 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado.")
    if dados.perfil not in PERFIS:
        raise RegraNegocio("Perfil inválido.")
    dup = db.execute(select(Usuario).where(func.lower(Usuario.usuario) == login)).scalar_one_or_none()
    if dup and dup.id != uid:
        raise RegraNegocio("Este nome de usuário já está em uso.", "DUPLICADO", 409)
    cpf = ""
    if dados.cpf:
        ok, msg = validate_cpf(dados.cpf)
        if not ok:
            raise RegraNegocio(msg)
        cpf = normalize_cpf(dados.cpf)
        dup = db.execute(select(Usuario).where(Usuario.cpf == cpf)).scalar_one_or_none()
        if dup and dup.id != uid:
            raise RegraNegocio("Este CPF já pertence a outro usuário.", "DUPLICADO", 409)
    ok, tel = validate_and_format_phone(dados.telefone)
    if not ok:
        raise RegraNegocio(tel)
    return {
        "usuario": login, "nome": clean_text(dados.nome, 160), "perfil": dados.perfil,
        "matricula": clean_text(dados.matricula, 30) or None, "cpf": cpf or None,
        "coren": clean_text(dados.coren, 30) or None, "telefone": tel or None,
        "email": clean_text(dados.email, 160) or None, "ativo": dados.ativo,
    }


def _admins_ativos(db: Session) -> int:
    return db.execute(select(func.count(Usuario.id)).where(Usuario.perfil == "ADMIN", Usuario.ativo.is_(True))).scalar() or 0


@router.get("/usuarios")
def listar_usuarios(_u: CurrentUser = Depends(require_roles(*SO_ADMIN)), db: Session = Depends(get_db)):
    itens = db.execute(select(Usuario).order_by(Usuario.nome)).scalars()
    return {"ok": True, "usuarios": [usuario_dict(u) for u in itens]}


@router.post("/usuarios")
def criar_usuario(dados: UsuarioIn, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
                  db: Session = Depends(get_db)):
    campos = _validar_usuario(db, dados)
    senha = generate_temp_password()
    u = Usuario(**campos, senha_hash=hash_password(senha), trocar_senha=True)
    db.add(u)
    db.flush()
    audit.registrar(db, "CRIAR_USUARIO", usuario=user, entidade="usuario", entidade_id=u.id,
                    detalhe=f"perfil={u.perfil}", ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Usuário criado. Entregue a senha temporária pessoalmente; ela será trocada no 1º acesso.",
            "senha_temporaria": senha, "usuario": usuario_dict(u)}


@router.put("/usuarios/{uid}")
def alterar_usuario(uid: int, dados: UsuarioIn, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
                    db: Session = Depends(get_db)):
    u = db.get(Usuario, uid)
    if not u:
        raise RegraNegocio("Usuário não encontrado.", "NAO_ENCONTRADO", 404)
    campos = _validar_usuario(db, dados, uid)
    perde_admin = u.perfil == "ADMIN" and u.ativo and (campos["perfil"] != "ADMIN" or not campos["ativo"])
    if perde_admin and _admins_ativos(db) <= 1:
        raise RegraNegocio("Não é possível remover o último administrador ativo.")
    for k, v in campos.items():
        setattr(u, k, v)
    if not u.ativo:
        destroy_user_sessions(db, u.id)
    audit.registrar(db, "ALTERAR_USUARIO", usuario=user, entidade="usuario", entidade_id=u.id,
                    detalhe=f"perfil={u.perfil} ativo={u.ativo}", ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Usuário atualizado.", "usuario": usuario_dict(u)}


@router.post("/usuarios/{uid}/redefinir-senha")
def redefinir_senha(uid: int, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
                    db: Session = Depends(get_db)):
    u = db.get(Usuario, uid)
    if not u:
        raise RegraNegocio("Usuário não encontrado.", "NAO_ENCONTRADO", 404)
    senha = generate_temp_password()
    u.senha_hash = hash_password(senha)
    u.trocar_senha = True
    u.tentativas_falhas = 0
    u.bloqueado_ate = None
    destroy_user_sessions(db, u.id)
    audit.registrar(db, "REDEFINIR_SENHA", usuario=user, entidade="usuario", entidade_id=u.id, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Senha redefinida e conta desbloqueada. O usuário deverá trocá-la no próximo acesso.",
            "senha_temporaria": senha}
