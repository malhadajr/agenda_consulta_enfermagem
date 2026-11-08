"""Utilidades comuns: exceção de regra de negócio e serialização dos registros."""

from typing import Any, Dict, Optional

from app.models import Agendamento, Intercorrencia, Paciente, Usuario
from app.services.validators import dia_semana, fmt_date, format_address_column, format_cpf

MODALIDADE_LABEL = {
    "QT": "Quimioterapia",
    "CONSULTA_ENF": "Consulta de Enfermagem",
    "TELECONSULTA": "Teleconsulta",
}
MODALIDADE_LOCAL = {"CONSULTA_ENF": "(Consulta Enf)", "TELECONSULTA": "(Teleconsulta)"}


class RegraNegocio(Exception):
    """Violação de regra de negócio. Vira HTTP 400/409 com mensagem amigável."""

    def __init__(self, mensagem: str, code: str = "REGRA", status: int = 400, extra: Optional[Dict[str, Any]] = None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.code = code
        self.status = status
        self.extra = extra or {}


def endereco_paciente(p: Paciente) -> str:
    montado = format_address_column(
        logradouro=p.logradouro or "",
        numero=p.numero or "",
        complemento=p.complemento or "",
        bairro=p.bairro or "",
        cidade=p.cidade or "",
        uf=p.uf or "",
        cep=p.cep or "",
    )
    return montado or (p.endereco_legado or "")


def paciente_resumo(p: Paciente) -> Dict[str, Any]:
    """Dados mínimos para listas e autocompletar (minimização LGPD)."""
    cpf = p.cpf or ""
    return {
        "id": p.id,
        "prontuario": p.prontuario or "",
        "nome_completo": p.nome_completo,
        "cpf_mascarado": f"***.{cpf[3:6]}.{cpf[6:9]}-**" if len(cpf) == 11 else "",
        "status": p.status,
        "ciclo_tratamento": p.ciclo_tratamento or "",
        "cadastro_incompleto": not bool(p.cpf),
    }


def paciente_completo(p: Paciente) -> Dict[str, Any]:
    d = paciente_resumo(p)
    d.update(
        {
            "cpf": format_cpf(p.cpf) if p.cpf else "",
            "data_nascimento": fmt_date(p.data_nascimento),
            "telefone": p.telefone or "",
            "email": p.email or "",
            "cep": p.cep or "",
            "logradouro": p.logradouro or "",
            "numero": p.numero or "",
            "complemento": p.complemento or "",
            "bairro": p.bairro or "",
            "cidade": p.cidade or "",
            "uf": p.uf or "",
            "endereco": endereco_paciente(p),
            "tipo_sanguineo": p.tipo_sanguineo or "",
            "fator_rh": p.fator_rh or "",
            "data_abertura_prontuario": fmt_date(p.data_abertura_prontuario),
            "motivo_encerramento": p.motivo_encerramento or "",
            "data_encerramento": fmt_date(p.data_encerramento),
            "data_retorno": fmt_date(p.data_retorno),
        }
    )
    return d


def agendamento_dict(a: Agendamento) -> Dict[str, Any]:
    return {
        "id": a.id,
        "modalidade": a.modalidade,
        "modalidade_label": MODALIDADE_LABEL.get(a.modalidade, a.modalidade),
        "data": fmt_date(a.data),
        "dia_semana": dia_semana(a.data),
        "hora": a.hora,
        "box": a.box or MODALIDADE_LOCAL.get(a.modalidade, ""),
        "paciente_id": a.paciente_id,
        "nome_paciente": a.paciente.nome_completo if a.paciente else "",
        "prontuario": (a.paciente.prontuario or "") if a.paciente else "",
        "protocolo": a.protocolo or "",
        "tempo_estimado": a.tempo_estimado or "",
        "compareceu": a.compareceu or "",
        "hora_inicio": a.hora_inicio or "",
        "hora_termino": a.hora_termino or "",
        "enfermeiro_id": a.enfermeiro_id,
        "enfermeira": a.enfermeiro_nome or "",
        "observacao": a.observacao or "",
    }


def intercorrencia_dict(i: Intercorrencia) -> Dict[str, Any]:
    return {
        "id": i.id,
        "data": fmt_date(i.data),
        "paciente_id": i.paciente_id,
        "paciente": i.paciente_nome,
        "intercorrencia": i.tipo,
        "enfermeiro": i.enfermeiro_nome or "",
        "protocolo": i.protocolo or "",
        "medida_tomada": i.medida_tomada or "",
        "observacao": i.observacao or "",
        "agendamento_id": i.agendamento_id,
    }


def usuario_dict(u: Usuario) -> Dict[str, Any]:
    return {
        "id": u.id,
        "usuario": u.usuario,
        "nome": u.nome,
        "perfil": u.perfil,
        "matricula": u.matricula or "",
        "cpf": format_cpf(u.cpf) if u.cpf else "",
        "coren": u.coren or "",
        "telefone": u.telefone or "",
        "email": u.email or "",
        "ativo": u.ativo,
        "trocar_senha": u.trocar_senha,
        "bloqueado": bool(u.bloqueado_ate),
        "ultimo_login": u.ultimo_login.strftime("%d/%m/%Y %H:%M") if u.ultimo_login else "",
    }
