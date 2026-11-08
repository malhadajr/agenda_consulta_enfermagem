"""Criação das tabelas e carga inicial dos catálogos (protocolos e tipos de intercorrência)."""

import csv
import logging
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import db as dbmod
from app.db import Base
from app.models import Protocolo, TipoIntercorrencia
from app.services.validators import validate_and_format_time_hhmm

SEED_DIR = Path(__file__).resolve().parent / "seed"
log = logging.getLogger("nova_agenda")
_LOCK_INIT = 727_2027


def _carga_inicial(db: Session) -> None:
    if not db.execute(select(func.count(Protocolo.id))).scalar():
        with open(SEED_DIR / "protocolos.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                nome = (row.get("protocolo") or "").strip()
                ok, tempo = validate_and_format_time_hhmm(row.get("tempo_estimado"))
                if nome:
                    db.add(Protocolo(nome=nome[:160], tempo_estimado=tempo if ok and tempo else "01:00"))
        log.info("Catálogo de protocolos carregado.")
    if not db.execute(select(func.count(TipoIntercorrencia.id))).scalar():
        for linha in (SEED_DIR / "intercorrencias.txt").read_text(encoding="utf-8").splitlines():
            if linha.strip():
                db.add(TipoIntercorrencia(nome=linha.strip()[:200]))
        log.info("Catálogo de intercorrências carregado.")


def init_db() -> None:
    """Idempotente. No PostgreSQL usa um lock para que vários processos não criem as tabelas ao mesmo tempo."""
    import app.models  # noqa: F401  (registra as tabelas)

    with dbmod.engine.connect() as conn:
        pg = conn.dialect.name == "postgresql"
        if pg:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_INIT})
        try:
            Base.metadata.create_all(conn)
            conn.commit()
            with Session(bind=conn) as db:
                _carga_inicial(db)
                db.commit()
        finally:
            if pg:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_INIT})
                conn.commit()
