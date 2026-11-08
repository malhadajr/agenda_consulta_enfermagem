"""Regras de negócio de pacientes: CPF único, cadastro, encerramento e retorno (recidiva)."""

import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import _local_lock, lock_global
from app.models import MOTIVOS_ENCERRAMENTO, Paciente
from app.services.common import RegraNegocio, paciente_completo, paciente_resumo
from app.services.validators import (
    clean_text,
    fuzzy_match_patients,
    normalize_cpf,
    normalize_search_text,
    parse_date_br,
    validate_and_format_date_br,
    validate_and_format_phone,
    validate_cpf,
)

TIPOS_SANGUINEOS = ("A", "B", "AB", "O")
FATORES_RH = ("Positivo", "Negativo")
UFS = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
)
PRONTUARIO_INICIAL = 5261001
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")


def buscar(db: Session, q: str, incluir_encerrados: bool = False, limite: int = 20) -> List[Dict[str, Any]]:
    """Busca tolerante a acentos e erros de digitação por nome, prontuário ou CPF."""
    q = clean_text(q, 100)
    stmt = select(Paciente.id, Paciente.nome_completo, Paciente.cpf, Paciente.prontuario, Paciente.status)
    if not incluir_encerrados:
        stmt = stmt.where(Paciente.status != "ENCERRADO")
    digitos = re.sub(r"\D", "", q)
    if digitos and len(digitos) >= 3 and not normalize_search_text(re.sub(r"\d", "", q)):
        stmt = stmt.where(or_(Paciente.cpf.like(f"{digitos}%"), Paciente.prontuario.like(f"{digitos}%")))
    linhas = db.execute(stmt.order_by(Paciente.nome_completo).limit(50000)).all()
    # fuzzy_match_patients compara o campo "id" com os dígitos digitados: usamos o prontuário
    base = [
        {"id": r.prontuario or "", "nome_completo": r.nome_completo, "cpf": r.cpf or "", "status": r.status, "_pid": r.id}
        for r in linhas
    ]
    achados = fuzzy_match_patients(q, base, include_encerrados=incluir_encerrados, limit=limite)
    if not achados:
        return []
    ids = [a["_pid"] for a in achados]
    mapa = {p.id: p for p in db.execute(select(Paciente).where(Paciente.id.in_(ids))).scalars()}
    return [paciente_resumo(mapa[i]) for i in ids if i in mapa]


def obter(db: Session, paciente_id: int) -> Paciente:
    p = db.get(Paciente, paciente_id)
    if not p:
        raise RegraNegocio("Paciente não encontrado.", "NAO_ENCONTRADO", 404)
    return p


def por_cpf(db: Session, cpf_digits: str) -> Optional[Paciente]:
    return db.execute(select(Paciente).where(Paciente.cpf == cpf_digits)).scalar_one_or_none()


def verificar_cpf(db: Session, cpf: str) -> Dict[str, Any]:
    ok, msg = validate_cpf(cpf)
    if not ok:
        return {"ok": False, "cpf_valido": False, "erro": msg}
    p = por_cpf(db, normalize_cpf(cpf))
    if not p:
        return {"ok": True, "cpf_valido": True, "existe": False, "cpf_formatado": msg,
                "mensagem": "CPF válido e disponível para novo cadastro."}
    if p.status == "ENCERRADO":
        return {"ok": True, "cpf_valido": True, "existe": True, "status": "ENCERRADO", "acao_sugerida": "REATIVAR",
                "mensagem": "Paciente já cadastrado com tratamento ENCERRADO. Você pode reativar o tratamento sem duplicar o CPF.",
                "paciente": paciente_resumo(p)}
    return {"ok": True, "cpf_valido": True, "existe": True, "status": "INICIADO", "acao_sugerida": "BLOQUEAR",
            "mensagem": "Paciente já cadastrado com tratamento em andamento", "paciente": paciente_resumo(p)}


def _validar_campos(payload: Dict[str, Any]) -> Dict[str, Any]:
    nome = clean_text(payload.get("nome_completo"), 200)
    if len(nome) < 3:
        raise RegraNegocio("Informe o nome completo da(o) paciente.")

    prontuario = clean_text(payload.get("prontuario"), 20)
    if prontuario and (not prontuario.isdigit() or len(prontuario) != 7):
        raise RegraNegocio("O prontuário deve ter exatamente 7 dígitos numéricos.")

    ok_cpf, cpf_msg = validate_cpf(payload.get("cpf"))
    if not ok_cpf:
        raise RegraNegocio(cpf_msg)

    ok_n, nasc, _ = validate_and_format_date_br(payload.get("data_nascimento"))
    if not ok_n:
        raise RegraNegocio(f"Data de nascimento: {nasc}")
    nasc_d = parse_date_br(nasc) if nasc else None
    if nasc_d and nasc_d > date.today():
        raise RegraNegocio("A data de nascimento não pode estar no futuro.")

    ok_a, abert, _ = validate_and_format_date_br(payload.get("data_abertura_prontuario") or date.today().strftime("%d/%m/%Y"))
    if not ok_a:
        raise RegraNegocio(f"Data de abertura do prontuário: {abert}")

    ok_t, tel = validate_and_format_phone(payload.get("telefone"))
    if not ok_t:
        raise RegraNegocio(tel)

    email = clean_text(payload.get("email"), 160)
    if email and not EMAIL_RE.match(email):
        raise RegraNegocio("E-mail inválido.")

    tipo = clean_text(payload.get("tipo_sanguineo"), 3).upper()
    if tipo and tipo not in TIPOS_SANGUINEOS:
        raise RegraNegocio(f"Tipo sanguíneo inválido. Escolha entre: {', '.join(TIPOS_SANGUINEOS)}.")
    fator = clean_text(payload.get("fator_rh"), 10).capitalize()
    if fator and fator not in FATORES_RH:
        raise RegraNegocio("Fator RH inválido. Escolha entre: Positivo, Negativo.")

    uf = clean_text(payload.get("uf"), 2).upper()
    if uf and uf not in UFS:
        raise RegraNegocio("UF inválida.")
    cep = re.sub(r"\D", "", payload.get("cep") or "")
    if cep and len(cep) != 8:
        raise RegraNegocio("CEP deve ter 8 dígitos.")

    return {
        "nome_completo": nome,
        "nome_busca": normalize_search_text(nome),
        "prontuario": prontuario or None,
        "cpf": normalize_cpf(cpf_msg),
        "data_nascimento": nasc_d,
        "telefone": tel or None,
        "email": email or None,
        "cep": f"{cep[:5]}-{cep[5:]}" if cep else None,
        "logradouro": clean_text(payload.get("logradouro"), 200) or None,
        "numero": clean_text(payload.get("numero"), 20) or None,
        "complemento": clean_text(payload.get("complemento"), 120) or None,
        "bairro": clean_text(payload.get("bairro"), 120) or None,
        "cidade": clean_text(payload.get("cidade"), 120) or None,
        "uf": uf or None,
        "tipo_sanguineo": tipo or None,
        "fator_rh": fator or None,
        "data_abertura_prontuario": parse_date_br(abert),
        "ciclo_tratamento": clean_text(payload.get("ciclo_tratamento"), 160) or None,
    }


def _proximo_prontuario(db: Session) -> str:
    atual = db.execute(
        select(func.max(Paciente.prontuario)).where(func.length(Paciente.prontuario) == 7)
    ).scalar()
    try:
        return str(max(int(atual) + 1, PRONTUARIO_INICIAL)) if atual else str(PRONTUARIO_INICIAL)
    except ValueError:
        return str(PRONTUARIO_INICIAL)


def criar(db: Session, payload: Dict[str, Any]) -> Paciente:
    with _local_lock:
        lock_global(db, "pacientes")
        dados = _validar_campos(payload)
        existente = por_cpf(db, dados["cpf"])
        if existente:
            if existente.status == "ENCERRADO":
                raise RegraNegocio(
                    "CPF já cadastrado com STATUS = ENCERRADO. Use a opção 'Reativar tratamento'.",
                    "CPF_EXISTENTE_ENCERRADO", 409, {"paciente": paciente_resumo(existente)},
                )
            raise RegraNegocio(
                "Paciente já cadastrado com tratamento em andamento",
                "CPF_DUPLICADO_ATIVO", 409, {"paciente": paciente_resumo(existente)},
            )
        if dados["prontuario"]:
            dup = db.execute(select(Paciente).where(Paciente.prontuario == dados["prontuario"])).scalar_one_or_none()
            if dup:
                raise RegraNegocio("Já existe paciente com este número de prontuário.", "PRONTUARIO_DUPLICADO", 409)
        else:
            dados["prontuario"] = _proximo_prontuario(db)
        p = Paciente(**dados, status="INICIADO")
        db.add(p)
        db.flush()
        return p


def atualizar(db: Session, paciente_id: int, payload: Dict[str, Any]) -> Paciente:
    with _local_lock:
        lock_global(db, "pacientes")
        p = obter(db, paciente_id)
        dados = _validar_campos(payload)
        outro = por_cpf(db, dados["cpf"])
        if outro and outro.id != p.id:
            raise RegraNegocio("Este CPF já pertence a outro paciente.", "CPF_DUPLICADO", 409)
        if dados["prontuario"]:
            dup = db.execute(select(Paciente).where(Paciente.prontuario == dados["prontuario"])).scalar_one_or_none()
            if dup and dup.id != p.id:
                raise RegraNegocio("Este prontuário já pertence a outro paciente.", "PRONTUARIO_DUPLICADO", 409)
        else:
            dados["prontuario"] = p.prontuario or _proximo_prontuario(db)
        for k, v in dados.items():
            setattr(p, k, v)
        db.flush()
        return p


def encerrar(db: Session, paciente_id: int, motivo: str, data_str: str = "") -> Paciente:
    p = obter(db, paciente_id)
    motivo = clean_text(motivo, 20).upper()
    if motivo in ("DESISTENCIA", "DEISTÊNCIA"):
        motivo = "DESISTÊNCIA"
    if motivo not in MOTIVOS_ENCERRAMENTO:
        raise RegraNegocio(f"Motivo de encerramento inválido. Escolha entre: {', '.join(MOTIVOS_ENCERRAMENTO)}.")
    if p.status == "ENCERRADO":
        raise RegraNegocio("O tratamento deste paciente já está ENCERRADO.")
    d = parse_date_br(data_str) if data_str else date.today()
    if not d:
        raise RegraNegocio("Data de encerramento inválida. Use DD/MM/AAAA.")
    p.status = "ENCERRADO"
    p.motivo_encerramento = motivo
    p.data_encerramento = d
    db.flush()
    return p


def reativar(db: Session, paciente_id: int, ciclo: str, data_str: str = "") -> Paciente:
    p = obter(db, paciente_id)
    if p.status != "ENCERRADO":
        raise RegraNegocio("Paciente já cadastrado com tratamento em andamento", "JA_ATIVO", 409)
    ciclo = clean_text(ciclo, 160)
    if not ciclo:
        raise RegraNegocio("Informe o ciclo/protocolo de retorno do tratamento (ex.: Retorno 1º Ciclo).")
    d = parse_date_br(data_str) if data_str else date.today()
    if not d:
        raise RegraNegocio("Data de retorno inválida. Use DD/MM/AAAA.")
    p.status = "INICIADO"
    p.data_retorno = d
    p.ciclo_tratamento = ciclo
    db.flush()
    return p


def listar(db: Session, status: str = "", limite: int = 50, offset: int = 0) -> Dict[str, Any]:
    stmt = select(Paciente)
    cnt = select(func.count(Paciente.id))
    if status in ("INICIADO", "ENCERRADO"):
        stmt = stmt.where(Paciente.status == status)
        cnt = cnt.where(Paciente.status == status)
    total = db.execute(cnt).scalar() or 0
    itens = db.execute(stmt.order_by(Paciente.atualizado_em.desc(), Paciente.id.desc()).offset(offset).limit(limite)).scalars().all()
    return {"total": total, "pacientes": [paciente_resumo(p) for p in itens]}


def contagens(db: Session) -> Dict[str, int]:
    total = db.execute(select(func.count(Paciente.id))).scalar() or 0
    enc = db.execute(select(func.count(Paciente.id)).where(Paciente.status == "ENCERRADO")).scalar() or 0
    return {"total": total, "ativos": total - enc, "encerrados": enc}


__all__ = [
    "buscar", "obter", "verificar_cpf", "criar", "atualizar", "encerrar", "reativar", "listar",
    "contagens", "paciente_completo", "TIPOS_SANGUINEOS", "FATORES_RH", "UFS",
]
