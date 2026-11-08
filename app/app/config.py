"""Configuração central da aplicação (lida exclusivamente de variáveis de ambiente)."""

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "sim", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _database_url() -> str:
    """
    Em produção (Docker) a URL é montada a partir de DB_HOST/DB_NAME/DB_USER e da senha
    lida de um arquivo de segredo (DB_PASSWORD_FILE) — a senha nunca fica em variável de ambiente.
    """
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    host = os.getenv("DB_HOST")
    if host:
        from urllib.parse import quote_plus

        senha = ""
        arq = os.getenv("DB_PASSWORD_FILE")
        if arq and os.path.isfile(arq):
            with open(arq, encoding="utf-8") as f:
                senha = f.read().strip()
        usuario = os.getenv("DB_USER", "nova_agenda")
        nome = os.getenv("DB_NAME", "nova_agenda")
        porta = os.getenv("DB_PORT", "5432")
        return f"postgresql+psycopg://{quote_plus(usuario)}:{quote_plus(senha)}@{host}:{porta}/{nome}"
    return "sqlite:///./nova_agenda_dev.db"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)
    # Em produção o cookie de sessão só trafega por HTTPS
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", True))
    # Minutos de inatividade até a sessão expirar
    sessao_inatividade_min: int = field(default_factory=lambda: _int("SESSAO_INATIVIDADE_MIN", 30))
    # Duração máxima absoluta de uma sessão (horas)
    sessao_maxima_horas: int = field(default_factory=lambda: _int("SESSAO_MAXIMA_HORAS", 12))
    # Bloqueio de conta após N tentativas erradas
    login_max_tentativas: int = field(default_factory=lambda: _int("LOGIN_MAX_TENTATIVAS", 5))
    login_bloqueio_min: int = field(default_factory=lambda: _int("LOGIN_BLOQUEIO_MIN", 15))
    # Consulta de CEP na internet (ViaCEP / BrasilAPI)
    cep_online: bool = field(default_factory=lambda: _bool("CEP_ONLINE", True))
    qtd_poltronas: int = field(default_factory=lambda: _int("QTD_POLTRONAS", 12))
    horas_funcionamento_dia: int = field(default_factory=lambda: _int("HORAS_FUNCIONAMENTO_DIA", 10))
    nome_instituicao: str = field(
        default_factory=lambda: os.getenv(
            "NOME_INSTITUICAO", "INSTITUTO NACIONAL DE CÂNCER — INCA / HOSPITAL DE CÂNCER II (HC II)"
        )
    )


settings = Settings()
