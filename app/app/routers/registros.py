"""Intercorrências clínicas e estatísticas diárias (Auditoria Clínica Prévia e Agendamento)."""

from typing import Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EstatisticaAgendamento, EstatisticaAuditoria, Intercorrencia, Paciente, TipoIntercorrencia
from app.security import LEITURA, OPERACAO, SO_ADMIN, CurrentUser, client_ip, require_roles
from app.services import audit
from app.services.common import RegraNegocio, intercorrencia_dict
from app.services.relatorios import CAMPOS_AGENDAMENTO, CAMPOS_AUDITORIA, estatisticas_consolidadas
from app.services.validators import clean_text, fmt_date, parse_date_br

router = APIRouter(prefix="/api", tags=["registros"])


# =============================================================================
# INTERCORRÊNCIAS
# =============================================================================

class IntercorrenciaIn(BaseModel):
    data: str = Field(max_length=10)
    paciente_id: int
    intercorrencia: str = Field(max_length=200)
    protocolo: Optional[str] = Field(default="", max_length=160)
    medida_tomada: Optional[str] = Field(default="", max_length=1000)
    observacao: Optional[str] = Field(default="", max_length=1000)


@router.get("/intercorrencias")
def listar_intercorrencias(ano: Optional[int] = Query(None, ge=2020, le=2100), mes: Optional[int] = Query(None, ge=1, le=12),
                           limite: int = Query(200, ge=1, le=1000),
                           _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    stmt = select(Intercorrencia)
    if ano:
        stmt = stmt.where(extract("year", Intercorrencia.data) == ano)
    if mes:
        stmt = stmt.where(extract("month", Intercorrencia.data) == mes)
    itens = db.execute(stmt.order_by(Intercorrencia.data.desc(), Intercorrencia.id.desc()).limit(limite)).scalars()
    return {"ok": True, "intercorrencias": [intercorrencia_dict(i) for i in itens]}


@router.post("/intercorrencias")
def criar_intercorrencia(dados: IntercorrenciaIn, request: Request, user: CurrentUser = Depends(require_roles(*OPERACAO)),
                         db: Session = Depends(get_db)):
    d = parse_date_br(dados.data)
    if not d:
        raise RegraNegocio("Informe uma data válida no formato DD/MM/AAAA.")
    p = db.get(Paciente, dados.paciente_id)
    if not p:
        raise RegraNegocio("Selecione um(a) paciente válido(a).")
    tipo = clean_text(dados.intercorrencia, 200)
    if not db.execute(select(TipoIntercorrencia).where(TipoIntercorrencia.nome == tipo)).scalar_one_or_none():
        raise RegraNegocio("Selecione uma intercorrência do catálogo oficial.")
    i = Intercorrencia(
        data=d, paciente_id=p.id, paciente_nome=p.nome_completo, tipo=tipo, enfermeiro_nome=user.usuario.nome,
        protocolo=clean_text(dados.protocolo, 160) or None, medida_tomada=clean_text(dados.medida_tomada, 1000) or None,
        observacao=clean_text(dados.observacao, 1000) or None, criado_por_id=user.id,
    )
    db.add(i)
    db.flush()
    audit.registrar(db, "REGISTRO_INTERCORRENCIA", usuario=user, entidade="intercorrencia", entidade_id=i.id,
                    ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Intercorrência registrada com sucesso.", "intercorrencia": intercorrencia_dict(i)}


# =============================================================================
# ESTATÍSTICAS DIÁRIAS
# =============================================================================

TABELAS = {
    "auditoria": (EstatisticaAuditoria, CAMPOS_AUDITORIA),
    "agendamento": (EstatisticaAgendamento, CAMPOS_AGENDAMENTO),
}


class EstatisticaIn(BaseModel):
    data: str = Field(max_length=10)
    valores: Dict[str, int]


def _tabela(tipo: str):
    if tipo not in TABELAS:
        raise RegraNegocio("Tipo de estatística inválido.", "NAO_ENCONTRADO", 404)
    return TABELAS[tipo]


@router.get("/estatisticas/campos")
def campos(_u: CurrentUser = Depends(require_roles(*LEITURA))):
    return {"ok": True, "auditoria": CAMPOS_AUDITORIA, "agendamento": CAMPOS_AGENDAMENTO}


@router.get("/estatisticas/consolidado")
def consolidado(ano: Optional[int] = Query(None, ge=2020, le=2100), mes: Optional[int] = Query(None, ge=1, le=12),
                _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    return {"ok": True, **estatisticas_consolidadas(db, ano, mes)}


@router.get("/estatisticas/{tipo}")
def listar_estatisticas(tipo: str, ano: int = Query(..., ge=2020, le=2100), mes: Optional[int] = Query(None, ge=1, le=12),
                        _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    modelo, campos_ = _tabela(tipo)
    stmt = select(modelo).where(extract("year", modelo.data) == ano)
    if mes:
        stmt = stmt.where(extract("month", modelo.data) == mes)
    linhas = []
    for r in db.execute(stmt.order_by(modelo.data.desc())).scalars():
        linhas.append({"id": r.id, "data": fmt_date(r.data), **{k: getattr(r, k) for k in campos_}})
    return {"ok": True, "campos": campos_, "registros": linhas}


@router.put("/estatisticas/{tipo}")
def gravar_estatistica(tipo: str, dados: EstatisticaIn, request: Request,
                       user: CurrentUser = Depends(require_roles(*OPERACAO)), db: Session = Depends(get_db)):
    modelo, campos_ = _tabela(tipo)
    d = parse_date_br(dados.data)
    if not d:
        raise RegraNegocio("Informe uma data válida.")
    for k, v in dados.valores.items():
        if k not in campos_:
            raise RegraNegocio("Campo de estatística desconhecido.")
        if v < 0 or v > 100000:
            raise RegraNegocio("Os valores devem ser números inteiros entre 0 e 100000.")
    if tipo == "auditoria" and dados.valores.get("validados", 0) > dados.valores.get("total_auditados", 0):
        raise RegraNegocio("O número de validados não pode ser maior que o total auditado.")
    reg = db.execute(select(modelo).where(modelo.data == d)).scalar_one_or_none()
    novo = reg is None
    if novo:
        reg = modelo(data=d)
        db.add(reg)
    for k in campos_:
        setattr(reg, k, int(dados.valores.get(k, 0)))
    reg.registrado_por_id = user.id
    db.flush()
    audit.registrar(db, f"ESTATISTICA_{tipo.upper()}", usuario=user, entidade=f"estat_{tipo}", entidade_id=reg.id,
                    detalhe=("novo " if novo else "alterado ") + d.isoformat(), ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": f"Estatística de {fmt_date(d)} {'registrada' if novo else 'atualizada'}."}


@router.delete("/estatisticas/{tipo}/{reg_id}")
def excluir_estatistica(tipo: str, reg_id: int, request: Request, user: CurrentUser = Depends(require_roles(*SO_ADMIN)),
                        db: Session = Depends(get_db)):
    modelo, _ = _tabela(tipo)
    reg = db.get(modelo, reg_id)
    if not reg:
        raise RegraNegocio("Registro não encontrado.", "NAO_ENCONTRADO", 404)
    db.delete(reg)
    audit.registrar(db, f"EXCLUIR_ESTATISTICA_{tipo.upper()}", usuario=user, entidade=f"estat_{tipo}", entidade_id=reg_id,
                    ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Registro excluído."}
