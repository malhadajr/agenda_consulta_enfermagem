"""Dashboards, mapa de calor, análise de tempo e consulta ao log de auditoria."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import LogAuditoria
from app.security import LEITURA, SO_ADMIN, CurrentUser, require_roles
from app.services import painel as painel_svc
from app.services import relatorios as svc
from app.services.validators import parse_date_br

router = APIRouter(prefix="/api", tags=["relatorios"])


@router.get("/painel/agora")
def painel_agora(_u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    """Painel ao vivo (todos os perfis). Atualizado automaticamente pela tela a cada 30 s."""
    return painel_svc.painel(db)


@router.get("/relatorios/dashboard")
def dashboard(ano: Optional[int] = Query(None, ge=2020, le=2100), mes: Optional[int] = Query(None, ge=1, le=12),
              _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    return svc.dashboard(db, ano, mes)


@router.get("/relatorios/mapa-calor")
def mapa_calor(ano: int = Query(..., ge=2020, le=2100), mes: Optional[int] = Query(None, ge=1, le=12),
               qtd_poltronas: int = Query(settings.qtd_poltronas, ge=1, le=50),
               horas_funcionamento: int = Query(settings.horas_funcionamento_dia, ge=1, le=24),
               _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    return svc.mapa_calor(db, ano, mes, qtd_poltronas, horas_funcionamento)


@router.get("/auditoria")
def log_auditoria(
    usuario: str = Query("", max_length=60), acao: str = Query("", max_length=60),
    data_ini: str = Query("", max_length=10), data_fim: str = Query("", max_length=10),
    offset: int = Query(0, ge=0), limite: int = Query(100, ge=1, le=500),
    _u: CurrentUser = Depends(require_roles(*SO_ADMIN)), db: Session = Depends(get_db),
):
    stmt = select(LogAuditoria)
    cnt = select(func.count(LogAuditoria.id))
    filtros = []
    if usuario:
        filtros.append(func.lower(LogAuditoria.usuario_login).like(f"%{usuario.lower()}%"))
    if acao:
        filtros.append(LogAuditoria.acao.like(f"%{acao.upper()}%"))
    di, df = parse_date_br(data_ini), parse_date_br(data_fim)
    if di:
        filtros.append(LogAuditoria.momento >= datetime.combine(di, datetime.min.time()))
    if df:
        filtros.append(LogAuditoria.momento < datetime.combine(df + timedelta(days=1), datetime.min.time()))
    for f in filtros:
        stmt, cnt = stmt.where(f), cnt.where(f)
    total = db.execute(cnt).scalar() or 0
    itens = db.execute(stmt.order_by(LogAuditoria.id.desc()).offset(offset).limit(limite)).scalars()
    return {
        "ok": True, "total": total,
        "eventos": [
            {"id": e.id, "momento": e.momento.strftime("%d/%m/%Y %H:%M:%S"), "usuario": e.usuario_login or "-",
             "acao": e.acao, "entidade": e.entidade or "", "entidade_id": e.entidade_id or "",
             "resultado": e.resultado, "detalhe": e.detalhe or "", "ip": e.ip or ""}
            for e in itens
        ],
    }

