"""
Módulo de validações, normalizações, máscaras, controle de conflito de horários por Box
e busca tolerante a erros (fuzzy search).
Regras críticas:
- CPF: normalização apenas dígitos, validação oficial dos 2 dígitos verificadores, formatação 000.000.000-00.
- Datas: validação e formatação DD/MM/AAAA + cálculo do dia da semana em português.
- Horários e Conflito de Box: cálculo automático de término a partir de hora inicial + tempo estimado
  e verificação de sobreposição de intervalos [início, término) no mesmo Box e Data.
- Busca de pacientes: sem acento, case-insensitive, tolerante a erros de digitação, ocultando ENCERRADOS por padrão.
"""

import re
import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from datetime import date
from typing import Dict, List, Optional, Tuple


DIAS_SEMANA_PT = [
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
]

# Grade padrão de horários do ambulatório (de 30 em 30 min, das 07:00 às 18:30)
GRADE_HORARIOS_PADRAO = [
    f"{h:02d}:{m:02d}"
    for h in range(7, 19)
    for m in (0, 30)
]


def normalize_cpf(cpf: Optional[str]) -> str:
    """Remove tudo que não for dígito do CPF."""
    if not cpf:
        return ""
    return re.sub(r"\D", "", str(cpf))


def format_cpf(cpf: Optional[str]) -> str:
    """Formata um CPF de 11 dígitos no padrão 000.000.000-00."""
    digits = normalize_cpf(cpf)
    if len(digits) != 11:
        return digits
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def validate_cpf(cpf: Optional[str]) -> Tuple[bool, str]:
    """
    Valida um CPF segundo a regra oficial dos dígitos verificadores.
    Retorna (valido: bool, mensagem_ou_cpf_formatado: str).
    """
    digits = normalize_cpf(cpf)
    if not digits:
        return False, "O CPF é obrigatório."
    if len(digits) != 11:
        return False, "O CPF deve conter exatamente 11 dígitos numéricos."
    if digits == digits[0] * 11:
        return False, "CPF inválido (sequência de dígitos repetidos)."

    soma1 = sum(int(digits[i]) * (10 - i) for i in range(9))
    resto1 = (soma1 * 10) % 11
    dv1 = 0 if resto1 == 10 else resto1
    if int(digits[9]) != dv1:
        return False, "CPF inválido (dígito verificador incorreto)."

    soma2 = sum(int(digits[i]) * (11 - i) for i in range(10))
    resto2 = (soma2 * 10) % 11
    dv2 = 0 if resto2 == 10 else resto2
    if int(digits[10]) != dv2:
        return False, "CPF inválido (dígito verificador incorreto)."

    return True, format_cpf(digits)


def normalize_phone(phone: Optional[str]) -> str:
    """Extrai apenas dígitos do telefone."""
    if not phone:
        return ""
    return re.sub(r"\D", "", str(phone))


def validate_and_format_phone(phone: Optional[str]) -> Tuple[bool, str]:
    """
    Valida e formata telefone brasileiro (10 ou 11 dígitos com DDD).
    Permite vazio se não informado, mas valida se preenchido.
    """
    digits = normalize_phone(phone)
    if not digits:
        return True, ""
    if len(digits) == 10:
        return True, f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    if len(digits) == 11:
        return True, f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    return False, "Telefone inválido. Informe DDD + número (10 ou 11 dígitos)."


def validate_and_format_date_br(date_str: Optional[str]) -> Tuple[bool, str, str]:
    """
    Aceita data em DD/MM/AAAA ou AAAA-MM-DD.
    Retorna (valido, data_dd_mm_aaaa, dia_da_semana_pt).
    """
    if not date_str or not str(date_str).strip():
        return True, "", ""
    raw = str(date_str).strip()
    dt = None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return False, "Data inválida. Use o formato brasileiro DD/MM/AAAA.", ""
    if dt.year < 1900 or dt.year > 2100:
        return False, "Ano da data fora do intervalo permitido (1900–2100).", ""
    return True, dt.strftime("%d/%m/%Y"), DIAS_SEMANA_PT[dt.weekday()]


def validate_and_format_time_hhmm(time_str: Optional[str]) -> Tuple[bool, str]:
    """Valida e normaliza horário no formato HH:MM (aceita também 0800 -> 08:00)."""
    if not time_str or not str(time_str).strip():
        return True, ""
    raw = str(time_str).strip().lower().replace("h", ":")
    if raw.endswith(":"):
        raw = raw[:-1] + ":00"
    if re.fullmatch(r"\d{4}", raw):
        raw = f"{raw[:2]}:{raw[2:]}"
    elif re.fullmatch(r"\d{3}", raw):
        raw = f"0{raw[0]}:{raw[1:]}"
    parts = raw.split(":")
    if len(parts) < 2:
        return False, "Horário inválido. Use o formato HH:MM (ex.: 08:00)."
    try:
        h = int(parts[0])
        m = int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return False, "Horário fora do intervalo 00:00 a 23:59."
        return True, f"{h:02d}:{m:02d}"
    except ValueError:
        return False, "Horário inválido. Use o formato HH:MM."


def time_to_minutes(hhmm: Optional[str]) -> Optional[int]:
    """Converte HH:MM para minutos desde 00:00."""
    ok, norm = validate_and_format_time_hhmm(hhmm)
    if not ok or not norm:
        return None
    h, m = map(int, norm.split(":"))
    return h * 60 + m


def minutes_to_hhmm(total_minutes: int) -> str:
    """Converte minutos desde 00:00 para HH:MM (limitado a 23:59)."""
    total_minutes = max(0, min(total_minutes, 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def calculate_end_time(start_hhmm: Optional[str], duration_hhmm: Optional[str]) -> str:
    """
    Calcula HORA TÉRMINO somando HORA (ou HORA INÍCIO) + TEMPO ESTIMADO (HH:MM).
    Retorna string HH:MM ou vazio se não for possível calcular.
    """
    s_min = time_to_minutes(start_hhmm)
    d_min = time_to_minutes(duration_hhmm)
    if s_min is None or d_min is None:
        return ""
    # Se o protocolo tiver duração 00:00 (ex.: suspensão/registro rápido), considera ocupação mínima de 30 min para bloqueio se desejado, mas retorna horário exato
    return minutes_to_hhmm(s_min + d_min)


def normalize_box_id(box_str: Optional[str]) -> str:
    """
    Normaliza a identificação do Box para comparação consistente.
    Ex.: 'Box 1', 'BOX 01', '1' -> 'BOX 1'.
    """
    if not box_str:
        return ""
    raw = str(box_str).strip().upper()
    m = re.fullmatch(r"(?:BOX\s*)?0*(\d+)", raw)
    if m:
        return f"BOX {m.group(1)}"
    return re.sub(r"\s+", " ", raw)


def intervals_overlap(start1_min: int, end1_min: int, start2_min: int, end2_min: int) -> bool:
    """
    Verifica se dois intervalos de tempo [start1, end1) e [start2, end2) se sobrepõem.
    Exemplo:
    - Existente: 08:00 (480) às 12:00 (720) [duração 4h]
    - Novo às 08:00, 09:00, 10:00, 11:30 -> Bloqueado (sobrepõe!)
    - Novo às 12:00 (720) -> Liberado (começa exatamente quando o anterior termina).
    """
    # Garante duração mínima de 15 min caso início == fim (protocolo 00:00)
    e1 = max(end1_min, start1_min + 15)
    e2 = max(end2_min, start2_min + 15)
    return start1_min < e2 and e1 > start2_min


def compute_appointment_interval_minutes(
    hora: str,
    tempo_estimado: str = "",
    hora_inicio: str = "",
    hora_termino: str = "",
    default_duration_min: int = 60,
) -> Tuple[Optional[int], Optional[int], str, str]:
    """
    Determina o intervalo [inicio_min, fim_min) de um agendamento.
    Prioriza hora_inicio (se preenchida) ou hora agendada como início,
    e hora_termino (se preenchida) ou (início + tempo_estimado) como fim.
    """
    start_str = hora_inicio.strip() if (hora_inicio and hora_inicio.strip()) else (hora or "").strip()
    s_min = time_to_minutes(start_str)
    if s_min is None:
        return None, None, "", ""

    e_min = time_to_minutes(hora_termino) if (hora_termino and hora_termino.strip()) else None
    if e_min is None or e_min <= s_min:
        d_min = time_to_minutes(tempo_estimado)
        if d_min is not None and d_min > 0:
            e_min = s_min + d_min
        else:
            e_min = s_min + default_duration_min

    return s_min, e_min, minutes_to_hhmm(s_min), minutes_to_hhmm(e_min)


def format_address_column(
    logradouro: str = "",
    numero: str = "",
    complemento: str = "",
    bairro: str = "",
    cidade: str = "",
    uf: str = "",
    cep: str = "",
) -> str:
    """
    Monta o endereço padronizado para gravação na coluna G da aba Pacientes,
    preservando todos os componentes preenchidos na tela.
    """
    logradouro = (logradouro or "").strip()
    numero = (numero or "").strip()
    complemento = (complemento or "").strip()
    bairro = (bairro or "").strip()
    cidade = (cidade or "").strip()
    uf = (uf or "").strip().upper()
    cep_digits = re.sub(r"\D", "", cep or "")
    cep_fmt = f"{cep_digits[:5]}-{cep_digits[5:]}" if len(cep_digits) == 8 else (cep or "").strip()

    parts = []
    if logradouro:
        rua_num = f"{logradouro}, {numero}" if numero else logradouro
        if complemento:
            rua_num += f" ({complemento})"
        parts.append(rua_num)
    elif numero:
        parts.append(f"Nº {numero}")

    if bairro:
        parts.append(bairro)

    if cidade and uf:
        parts.append(f"{cidade}/{uf}")
    elif cidade or uf:
        parts.append(cidade or uf)

    if cep_fmt:
        parts.append(f"CEP: {cep_fmt}")

    return " - ".join(parts)


def normalize_search_text(text: Optional[str]) -> str:
    """
    Remove acentos, converte para minúsculas, remove pontuação final e espaços extras.
    """
    if not text:
        return ""
    s = str(text).strip().lower()
    s = "".join(
        ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)
    )
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fuzzy_match_patients(
    query: str,
    patients: List[Dict],
    include_encerrados: bool = False,
    limit: int = 15,
) -> List[Dict]:
    """
    Busca pacientes de forma tolerante a acentos, maiúsculas/minúsculas e erros de digitação.
    Por padrão (Requisito 4.2), pacientes com STATUS == 'ENCERRADO' NÃO aparecem,
    exceto quando include_encerrados=True.
    """
    filtered = []
    for p in patients:
        status_upper = str(p.get("status") or "").strip().upper()
        if not include_encerrados and status_upper == "ENCERRADO":
            continue
        filtered.append(p)

    q_norm = normalize_search_text(query)
    q_digits = re.sub(r"\D", "", query or "")

    if not q_norm and not q_digits:
        return filtered[:limit]

    q_tokens = q_norm.split()
    scored = []

    for p in filtered:
        nome = str(p.get("nome_completo") or "")
        nome_norm = normalize_search_text(nome)
        cpf_digits = normalize_cpf(p.get("cpf"))
        id_str = str(p.get("id") or "").strip()

        score = 0.0

        if q_digits:
            if id_str.startswith(q_digits) or cpf_digits.startswith(q_digits):
                score = max(score, 0.98)
            elif q_digits in id_str or q_digits in cpf_digits:
                score = max(score, 0.88)

        if q_norm:
            if nome_norm == q_norm:
                score = max(score, 1.0)
            elif nome_norm.startswith(q_norm):
                score = max(score, 0.95)
            elif q_norm in nome_norm:
                score = max(score, 0.86)
            else:
                nome_tokens = nome_norm.split()
                if q_tokens and nome_tokens:
                    token_scores = []
                    for qt in q_tokens:
                        best_t = 0.0
                        for nt in nome_tokens:
                            if nt.startswith(qt):
                                best_t = max(best_t, 0.92)
                            elif qt in nt:
                                best_t = max(best_t, 0.82)
                            else:
                                ratio = SequenceMatcher(None, qt, nt).ratio()
                                if ratio >= 0.72:
                                    best_t = max(best_t, ratio * 0.85)
                        token_scores.append(best_t)
                    avg_token_score = sum(token_scores) / len(token_scores)
                    if all(ts >= 0.60 for ts in token_scores):
                        score = max(score, avg_token_score)
                    else:
                        full_ratio = SequenceMatcher(None, q_norm, nome_norm[: len(q_norm) + 8]).ratio()
                        if full_ratio >= 0.72:
                            score = max(score, full_ratio * 0.80)

        if score >= 0.58:
            scored.append((score, nome_norm, p))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


# =============================================================================
# CONVERSÕES DE DATA PARA O BANCO DE DADOS
# =============================================================================

def parse_date_br(date_str) -> "Optional[date]":
    """Converte DD/MM/AAAA (ou AAAA-MM-DD) em datetime.date. Retorna None se vazio/inválido."""
    from datetime import date as _date

    if isinstance(date_str, _date):
        return date_str
    ok, fmt, _ = validate_and_format_date_br(date_str)
    if not ok or not fmt:
        return None
    return datetime.strptime(fmt, "%d/%m/%Y").date()


def fmt_date(d) -> str:
    """datetime.date -> DD/MM/AAAA (vazio se None)."""
    return d.strftime("%d/%m/%Y") if d else ""


def dia_semana(d) -> str:
    return DIAS_SEMANA_PT[d.weekday()] if d else ""


def clean_text(value, max_len: int = 500) -> str:
    """Remove caracteres de controle e limita o tamanho de textos livres."""
    if value is None:
        return ""
    s = str(value)
    s = "".join(ch for ch in s if ch == "\n" or ch == "\t" or (ord(ch) >= 32 and ord(ch) != 127))
    return s.strip()[:max_len]
