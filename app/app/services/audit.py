"""Registro da trilha de auditoria (sem dados pessoais: apenas IDs internos)."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import LogAuditoria

logger = logging.getLogger("nova_agenda.auditoria")


def registrar(
    db: Session,
    acao: str,
    usuario=None,
    entidade: Optional[str] = None,
    entidade_id=None,
    resultado: str = "OK",
    detalhe: Optional[str] = None,
    ip: Optional[str] = None,
    usuario_login: Optional[str] = None,
    commit: bool = False,
) -> None:
    """
    Grava um evento de auditoria. `usuario` pode ser um Usuario ou CurrentUser.
    NÃO passe CPF, nome, telefone ou endereço em `detalhe`.
    """
    u = getattr(usuario, "usuario", usuario)
    db.add(
        LogAuditoria(
            momento=datetime.now(),
            usuario_id=getattr(u, "id", None),
            usuario_login=(usuario_login or getattr(u, "usuario", None) or "")[:60] or None,
            acao=acao[:60],
            entidade=(entidade or "")[:40] or None,
            entidade_id=str(entidade_id)[:40] if entidade_id is not None else None,
            resultado=resultado[:20],
            detalhe=(detalhe or "")[:300] or None,
            ip=(ip or "")[:64] or None,
        )
    )
    if commit:
        db.commit()
    logger.info("acao=%s entidade=%s id=%s resultado=%s", acao, entidade, entidade_id, resultado)
