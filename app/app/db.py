"""Conexão com o banco de dados (PostgreSQL em produção; SQLite apenas nos testes)."""

import threading
import zlib
from datetime import date
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Lock local usado somente quando o banco é SQLite (testes / desenvolvimento)
_local_lock = threading.RLock()


def configure_engine(url: str) -> None:
    """Permite que os testes troquem o banco em tempo de execução."""
    global engine
    engine = _make_engine(url)
    SessionLocal.configure(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def lock_agenda_dia(db: Session, dia: date) -> None:
    """
    Serializa gravações de agendamento para um mesmo dia, evitando que dois
    enfermeiros reservem o mesmo Box/horário ao mesmo tempo.
    PostgreSQL: advisory lock transacional (liberado no commit/rollback).
    """
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        key = zlib.crc32(f"agenda:{dia.isoformat()}".encode())
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def lock_global(db: Session, nome: str) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        key = zlib.crc32(f"global:{nome}".encode())
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
