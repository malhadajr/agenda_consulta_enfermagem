"""Modelo de dados (tabelas) da Nova Agenda 2027."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

PERFIS = ("ADMIN", "ENFERMEIRO", "GESTOR")
MODALIDADES = ("QT", "CONSULTA_ENF", "TELECONSULTA")
STATUS_PACIENTE = ("INICIADO", "ENCERRADO")
MOTIVOS_ENCERRAMENTO = ("DESISTÊNCIA", "CURA", "MORTE")


class Usuario(Base):
    """Usuários do sistema (equipe de enfermagem, gestores e administradores)."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(160))
    perfil: Mapped[str] = mapped_column(String(20), default="ENFERMEIRO")
    matricula: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    cpf: Mapped[Optional[str]] = mapped_column(String(14), nullable=True, unique=True)
    coren: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    telefone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    senha_hash: Mapped[str] = mapped_column(String(255), default="!")  # "!" = sem senha definida
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    trocar_senha: Mapped[bool] = mapped_column(Boolean, default=True)
    tentativas_falhas: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_ate: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ultimo_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Sessao(Base):
    """Sessões ativas. Apenas o hash SHA-256 do token é guardado."""

    __tablename__ = "sessoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime)
    ultimo_acesso: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    usuario: Mapped[Usuario] = relationship()


class Paciente(Base):
    __tablename__ = "pacientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prontuario: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True)
    nome_completo: Mapped[str] = mapped_column(String(200), index=True)
    nome_busca: Mapped[str] = mapped_column(String(200), index=True, default="")
    cpf: Mapped[Optional[str]] = mapped_column(String(11), unique=True, nullable=True)  # só dígitos
    data_nascimento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    telefone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    cep: Mapped[Optional[str]] = mapped_column(String(9), nullable=True)
    logradouro: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    numero: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    complemento: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    bairro: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    cidade: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    uf: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    endereco_legado: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tipo_sanguineo: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    fator_rh: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    data_abertura_prontuario: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="INICIADO", index=True)
    motivo_encerramento: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    data_encerramento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    data_retorno: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ciclo_tratamento: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Protocolo(Base):
    __tablename__ = "protocolos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), unique=True)
    tempo_estimado: Mapped[str] = mapped_column(String(5), default="01:00")  # HH:MM
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class TipoIntercorrencia(Base):
    __tablename__ = "tipos_intercorrencia"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(200), unique=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Agendamento(Base):
    __tablename__ = "agendamentos"
    __table_args__ = (Index("ix_agendamento_data_modalidade", "data", "modalidade"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    modalidade: Mapped[str] = mapped_column(String(15), default="QT")
    data: Mapped[date] = mapped_column(Date, index=True)
    hora: Mapped[str] = mapped_column(String(5))
    box: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id", ondelete="RESTRICT"), index=True)
    protocolo: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    tempo_estimado: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    compareceu: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # S / N / vazio
    hora_inicio: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    hora_termino: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    enfermeiro_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    enfermeiro_nome: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    observacao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    paciente: Mapped[Paciente] = relationship()


class Intercorrencia(Base):
    __tablename__ = "intercorrencias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[date] = mapped_column(Date, index=True)
    paciente_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pacientes.id", ondelete="RESTRICT"), nullable=True)
    paciente_nome: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(200))
    enfermeiro_nome: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    protocolo: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    medida_tomada: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    observacao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agendamento_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agendamentos.id", ondelete="SET NULL"), nullable=True)
    criado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EstatisticaAuditoria(Base):
    """Estatística diária da Auditoria Clínica Prévia (antes preenchida à mão na planilha)."""

    __tablename__ = "estatistica_auditoria"
    __table_args__ = (UniqueConstraint("data", name="uq_estat_auditoria_data"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[date] = mapped_column(Date)
    total_auditados: Mapped[int] = mapped_column(Integer, default=0)
    validados: Mapped[int] = mapped_column(Integer, default=0)
    exame_incompativel: Mapped[int] = mapped_column(Integer, default=0)
    dose_nao_conforme: Mapped[int] = mapped_column(Integer, default=0)
    incompatibilidade_evolucao_prescricao: Mapped[int] = mapped_column(Integer, default=0)
    sem_evolucao_ou_prescricao: Mapped[int] = mapped_column(Integer, default=0)
    sem_dados_antropometricos: Mapped[int] = mapped_column(Integer, default=0)
    receita_ausente_ou_errada: Mapped[int] = mapped_column(Integer, default=0)
    encaminhamentos_multiprofissional: Mapped[int] = mapped_column(Integer, default=0)
    registrado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class EstatisticaAgendamento(Base):
    """Estatística diária de agendamento (antes preenchida à mão na planilha)."""

    __tablename__ = "estatistica_agendamento"
    __table_args__ = (UniqueConstraint("data", name="uq_estat_agendamento_data"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[date] = mapped_column(Date)
    validados_infusao: Mapped[int] = mapped_column(Integer, default=0)
    primeira_vez: Mapped[int] = mapped_column(Integer, default=0)
    retorno_controle: Mapped[int] = mapped_column(Integer, default=0)
    reagendamentos: Mapped[int] = mapped_column(Integer, default=0)
    avaliacao_supervisao: Mapped[int] = mapped_column(Integer, default=0)
    avaliacao_enfermeiro: Mapped[int] = mapped_column(Integer, default=0)
    sem_receita_medica: Mapped[int] = mapped_column(Integer, default=0)
    sem_exames_laboratoriais: Mapped[int] = mapped_column(Integer, default=0)
    sem_exames_imagem: Mapped[int] = mapped_column(Integer, default=0)
    encaminhamentos_multiprofissional: Mapped[int] = mapped_column(Integer, default=0)
    registrado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class LogAuditoria(Base):
    """Trilha de auditoria (LGPD): quem fez o quê, quando e de onde. Nunca guarda CPF, nome ou telefone."""

    __tablename__ = "log_auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    momento: Mapped[datetime] = mapped_column(DateTime, index=True)
    usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    usuario_login: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    acao: Mapped[str] = mapped_column(String(60), index=True)
    entidade: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    entidade_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    resultado: Mapped[str] = mapped_column(String(20), default="OK")
    detalhe: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
