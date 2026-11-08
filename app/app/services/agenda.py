"""
Agendamentos nas 3 modalidades (Quimioterapia/Box, Consulta de Enfermagem e Teleconsulta)
com bloqueio de conflito por Box + duração do protocolo e bloqueio de agendamento cruzado do paciente.
"""

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import _local_lock, lock_agenda_dia
from app.models import Agendamento, Intercorrencia, Paciente, Protocolo, Usuario
from app.services.common import (
    MODALIDADE_LABEL,
    MODALIDADE_LOCAL,
    RegraNegocio,
    agendamento_dict,
)
from app.services.validators import (
    GRADE_HORARIOS_PADRAO,
    calculate_end_time,
    clean_text,
    compute_appointment_interval_minutes,
    dia_semana,
    fmt_date,
    intervals_overlap,
    minutes_to_hhmm,
    normalize_box_id,
    parse_date_br,
    time_to_minutes,
    validate_and_format_time_hhmm,
)

FAIXAS_CONSULTA = [f"{h:02d}:00" for h in range(8, 18)]  # 08:00 às 17:00, 1 h cada
DURACAO_CONSULTA = "01:00"
CONSULTA_INICIO_MIN = 8 * 60
CONSULTA_FIM_MIN = 17 * 60
BOXES_EXTRAS = ["Pesquisa Clínica", "Internado"]


def lista_boxes() -> List[str]:
    return [f"Box {i}" for i in range(1, settings.qtd_poltronas + 1)] + BOXES_EXTRAS


def mapa_protocolos(db: Session) -> Dict[str, str]:
    return {p.nome.upper(): p.tempo_estimado for p in db.execute(select(Protocolo)).scalars()}


def _intervalo(a: Agendamento, prot_map: Dict[str, str]) -> Tuple[Optional[int], Optional[int], str, str]:
    if a.modalidade == "QT":
        t_est = a.tempo_estimado or prot_map.get((a.protocolo or "").upper(), "01:00")
        return compute_appointment_interval_minutes(
            hora=a.hora, tempo_estimado=t_est, hora_inicio=a.hora_inicio or "", hora_termino=a.hora_termino or ""
        )
    return compute_appointment_interval_minutes(
        hora=a.hora, tempo_estimado=DURACAO_CONSULTA, hora_inicio=a.hora_inicio or "",
        hora_termino=a.hora_termino or "", default_duration_min=60,
    )


def agendamentos_do_dia(db: Session, dia: date, modalidade: Optional[str] = None) -> List[Agendamento]:
    stmt = select(Agendamento).options(joinedload(Agendamento.paciente)).where(Agendamento.data == dia)
    if modalidade:
        stmt = stmt.where(Agendamento.modalidade == modalidade)
    return list(db.execute(stmt.order_by(Agendamento.hora, Agendamento.id)).scalars())


def _ocupacao(a: Agendamento, prot_map: Dict[str, str]) -> Optional[Dict[str, Any]]:
    s, e, sh, eh = _intervalo(a, prot_map)
    if s is None or e is None:
        return None
    return {
        "id": a.id,
        "box": a.box or MODALIDADE_LOCAL.get(a.modalidade, ""),
        "inicio_min": s,
        "fim_min": e,
        "inicio_hhmm": sh,
        "fim_hhmm": eh,
        "nome_paciente": a.paciente.nome_completo if a.paciente else "",
        "protocolo": a.protocolo or MODALIDADE_LABEL.get(a.modalidade, ""),
        "compareceu": a.compareceu or "",
    }


def _linha_matriz(rotulo: str, tipo: str, ocs: List[Dict[str, Any]], faixas: List[str], capacidade_h: float) -> Dict[str, Any]:
    horas = sum(max(0.0, (o["fim_min"] - o["inicio_min"]) / 60.0) for o in ocs)
    celulas = []
    for h in faixas:
        hs = time_to_minutes(h)
        oc = next((o for o in ocs if intervals_overlap(hs, hs + 60, o["inicio_min"], o["fim_min"])), None)
        celulas.append({
            "faixa": h,
            "ocupado": oc is not None,
            "agendamento_id": oc["id"] if oc else None,
            "paciente": oc["nome_paciente"] if oc else "",
            "protocolo": oc["protocolo"] if oc else "",
            "janela": f"{oc['inicio_hhmm']}–{oc['fim_hhmm']}" if oc else "Livre",
        })
    return {
        "box": rotulo,
        "tipo_linha": tipo,
        "horas_ocupadas": round(horas, 2),
        "horas_ociosas": round(max(0.0, capacidade_h - horas), 2),
        "taxa_ocupacao_pct": round(min(100.0, horas / capacidade_h * 100.0), 1) if capacidade_h else 0.0,
        "faixas": celulas,
    }


def disponibilidade(
    db: Session, data_str: str, box: str = "", protocolo: str = "", tempo_estimado: str = "",
    modalidade: str = "QT", ignorar_id: Optional[int] = None,
) -> Dict[str, Any]:
    dia = parse_date_br(data_str)
    if not dia:
        raise RegraNegocio("Informe uma data válida (DD/MM/AAAA).")
    modalidade = modalidade if modalidade in MODALIDADE_LABEL else "QT"
    prot_map = mapa_protocolos(db)
    dur_min = time_to_minutes(clean_text(tempo_estimado, 5) or prot_map.get(clean_text(protocolo, 160).upper(), ""))
    if not dur_min or dur_min <= 0:
        dur_min = 60

    por_box: Dict[str, List[Dict[str, Any]]] = {}
    consultas: Dict[str, List[Dict[str, Any]]] = {"CONSULTA_ENF": [], "TELECONSULTA": []}
    for a in agendamentos_do_dia(db, dia):
        if a.id == ignorar_id or (a.compareceu or "").upper() == "N":
            continue
        oc = _ocupacao(a, prot_map)
        if not oc:
            continue
        if a.modalidade == "QT":
            por_box.setdefault(normalize_box_id(a.box), []).append(oc)
        else:
            consultas[a.modalidade].append(oc)

    faixas = [f"{h:02d}:00" for h in range(8, 8 + settings.horas_funcionamento_dia)]
    h_func = float(settings.horas_funcionamento_dia)
    matriz = [
        _linha_matriz(f"Box {i}", "BOX_QT", por_box.get(f"BOX {i}", []), faixas, h_func)
        for i in range(1, settings.qtd_poltronas + 1)
    ]
    matriz.append(_linha_matriz("(Consulta Enf)", "CONSULTA_ENF", consultas["CONSULTA_ENF"], FAIXAS_CONSULTA, 10.0))
    matriz.append(_linha_matriz("(Teleconsulta)", "TELECONSULTA", consultas["TELECONSULTA"], FAIXAS_CONSULTA, 10.0))

    if modalidade == "QT":
        alvo = por_box.get(normalize_box_id(box), []) if box else []
        slots = GRADE_HORARIOS_PADRAO
    else:
        alvo = consultas[modalidade]
        slots = FAIXAS_CONSULTA
        dur_min = 60

    horarios = []
    for slot in slots:
        s = time_to_minutes(slot)
        conflito = next((o for o in alvo if intervals_overlap(s, s + dur_min, o["inicio_min"], o["fim_min"])), None)
        horarios.append({
            "hora": slot,
            "fim_previsto": minutes_to_hhmm(s + dur_min),
            "disponivel": conflito is None,
            "motivo_bloqueio": (
                f"Ocupado das {conflito['inicio_hhmm']} às {conflito['fim_hhmm']} ({conflito['nome_paciente']})"
                if conflito else ""
            ),
        })

    boxes = matriz[: settings.qtd_poltronas]
    return {
        "ok": True,
        "data": fmt_date(dia),
        "dia_semana": dia_semana(dia),
        "modalidade": modalidade,
        "box_selecionado": box,
        "duracao_considerada_hhmm": minutes_to_hhmm(dur_min),
        "horarios": horarios,
        "matriz_poltronas": matriz,
        "faixas": faixas,
        "resumo_dia": {
            "poltronas_instaladas": settings.qtd_poltronas,
            "capacidade_horas_dia": settings.qtd_poltronas * settings.horas_funcionamento_dia,
            "horas_ocupadas_dia": round(sum(m["horas_ocupadas"] for m in boxes), 2),
            "horas_ociosas_dia": round(sum(m["horas_ociosas"] for m in boxes), 2),
            "cadeiras_100_ociosas": sum(1 for m in boxes if m["horas_ocupadas"] == 0),
            "consultas_enf_dia": len(consultas["CONSULTA_ENF"]),
            "teleconsultas_dia": len(consultas["TELECONSULTA"]),
        },
    }


def _resolver_enfermeiro(db: Session, enfermeiro_id) -> Tuple[Optional[int], Optional[str]]:
    if not enfermeiro_id:
        return None, None
    try:
        u = db.get(Usuario, int(enfermeiro_id))
    except (TypeError, ValueError):
        u = None
    if not u or not u.ativo or u.perfil not in ("ENFERMEIRO", "ADMIN"):
        raise RegraNegocio("Enfermeira(o) responsável inválida(o).")
    return u.id, u.nome


def salvar(db: Session, payload: Dict[str, Any], usuario_id: int, existente: Optional[Agendamento] = None) -> Agendamento:
    """Cria (existente=None) ou altera um agendamento aplicando TODAS as regras de conflito."""
    modalidade = clean_text(payload.get("modalidade") or (existente.modalidade if existente else "QT"), 15).upper()
    if modalidade == "AGENDA_QT":
        modalidade = "QT"
    if modalidade not in MODALIDADE_LABEL:
        raise RegraNegocio("Tipo de agenda inválido.")

    dia = parse_date_br(payload.get("data"))
    if not dia:
        raise RegraNegocio("Informe uma data válida no formato DD/MM/AAAA.")

    ok, hora = validate_and_format_time_hhmm(payload.get("hora"))
    if not ok or not hora:
        raise RegraNegocio("Informe o horário agendado no formato HH:MM.")
    ok, hora_ini = validate_and_format_time_hhmm(payload.get("hora_inicio"))
    if not ok:
        raise RegraNegocio(hora_ini)
    ok, hora_fim = validate_and_format_time_hhmm(payload.get("hora_termino"))
    if not ok:
        raise RegraNegocio(hora_fim)
    if hora_ini and hora_fim and time_to_minutes(hora_fim) <= time_to_minutes(hora_ini):
        raise RegraNegocio("A hora de término deve ser posterior à hora de início.")

    compareceu = clean_text(payload.get("compareceu"), 1).upper()
    if compareceu and compareceu not in ("S", "N"):
        raise RegraNegocio("O campo COMPARECEU deve ser 'S', 'N' ou ficar em branco.")

    try:
        paciente_id = int(payload.get("paciente_id") or 0)
    except (TypeError, ValueError):
        paciente_id = 0
    paciente = db.get(Paciente, paciente_id) if paciente_id else None
    if not paciente:
        raise RegraNegocio("Selecione um(a) paciente válido(a) na lista de busca.")
    mudou_paciente = not existente or existente.paciente_id != paciente.id
    if paciente.status == "ENCERRADO" and mudou_paciente:
        raise RegraNegocio(
            f"O tratamento de '{paciente.nome_completo}' consta como ENCERRADO. Reative o tratamento na aba Pacientes antes de agendar."
        )

    enf_id, enf_nome = _resolver_enfermeiro(db, payload.get("enfermeiro_id"))

    box: Optional[str] = None
    protocolo: Optional[str] = None
    tempo_est: Optional[str] = None
    if modalidade == "QT":
        box = clean_text(payload.get("box"), 40)
        if not box:
            raise RegraNegocio("Informe o Box/Poltrona para agendamento de Quimioterapia.")
        validos = {normalize_box_id(b): b for b in lista_boxes()}
        if normalize_box_id(box) not in validos:
            raise RegraNegocio("Box inválido.")
        box = validos[normalize_box_id(box)]
        protocolo_in = clean_text(payload.get("protocolo"), 160)
        if not protocolo_in:
            raise RegraNegocio("Selecione o Protocolo terapêutico.")
        prot = db.execute(select(Protocolo).where(Protocolo.nome == protocolo_in)).scalar_one_or_none()
        if not prot:
            raise RegraNegocio("Protocolo não cadastrado. Peça ao administrador para incluí-lo na aba Protocolos.")
        protocolo = prot.nome
        ok, tempo_est = validate_and_format_time_hhmm(payload.get("tempo_estimado") or prot.tempo_estimado)
        if not ok:
            raise RegraNegocio("Tempo estimado inválido (HH:MM).")
    else:
        s_min = time_to_minutes(hora_ini or hora)
        if s_min < CONSULTA_INICIO_MIN or s_min > CONSULTA_FIM_MIN:
            raise RegraNegocio(
                f"Horário ({hora}) fora do expediente de consultas: 08:00 às 17:00 (cada consulta tem 1 hora)."
            )

    observacao = clean_text(payload.get("observacao"), 1000)

    with _local_lock:
        lock_agenda_dia(db, dia)
        prot_map = mapa_protocolos(db)
        novo = SimpleNamespace(
            modalidade=modalidade, data=dia, hora=hora, box=box, paciente_id=paciente.id, protocolo=protocolo,
            tempo_estimado=tempo_est, compareceu=compareceu or None, hora_inicio=hora_ini or None,
            hora_termino=hora_fim or None,
        )
        s_novo, e_novo, sh_novo, eh_novo = _intervalo(novo, prot_map)

        if compareceu != "N":
            for a in agendamentos_do_dia(db, dia):
                if existente and a.id == existente.id:
                    continue
                if (a.compareceu or "").upper() == "N":
                    continue
                s, e, sh, eh = _intervalo(a, prot_map)
                if s is None or not intervals_overlap(s_novo, e_novo, s, e):
                    continue
                # 1. Mesmo paciente em qualquer modalidade no mesmo horário
                if a.paciente_id == paciente.id:
                    raise RegraNegocio(
                        f"Agendamento cruzado bloqueado: '{paciente.nome_completo}' já possui "
                        f"{MODALIDADE_LABEL[a.modalidade]} das {sh} às {eh} em {fmt_date(dia)}.",
                        "CONFLITO_HORARIO_PACIENTE", 409,
                    )
                # 2. Mesmo Box (quimioterapia) considerando a duração do protocolo
                if modalidade == "QT" and a.modalidade == "QT" and normalize_box_id(a.box) == normalize_box_id(box):
                    raise RegraNegocio(
                        f"Horário indisponível no {box} em {fmt_date(dia)}: o intervalo pretendido ({sh_novo} às {eh_novo}, "
                        f"protocolo {protocolo}) conflita com o agendamento de '{a.paciente.nome_completo}' "
                        f"({a.protocolo}) que ocupa o {a.box} das {sh} às {eh}.",
                        "CONFLITO_HORARIO_BOX", 409,
                    )
                # 3. Mesma linha de consulta (1 atendimento por hora)
                if modalidade != "QT" and a.modalidade == modalidade:
                    raise RegraNegocio(
                        f"Horário ocupado em '{MODALIDADE_LABEL[modalidade]}' em {fmt_date(dia)}: "
                        f"já existe atendimento das {sh} às {eh}. Cada consulta tem 1 hora (08:00 às 17:00).",
                        "CONFLITO_HORARIO_CONSULTA", 409,
                    )

        if existente:
            ag = existente
            for campo in ("modalidade", "data", "hora", "box", "paciente_id", "protocolo", "tempo_estimado",
                          "compareceu", "hora_inicio", "hora_termino"):
                setattr(ag, campo, getattr(novo, campo))
            ag.paciente = paciente
        else:
            ag = Agendamento(
                modalidade=modalidade, data=dia, hora=hora, box=box, paciente_id=paciente.id, protocolo=protocolo,
                tempo_estimado=tempo_est, compareceu=compareceu or None, hora_inicio=hora_ini or None,
                hora_termino=hora_fim or None, criado_por_id=usuario_id,
            )
            db.add(ag)
        ag.enfermeiro_id = enf_id
        ag.enfermeiro_nome = enf_nome
        ag.observacao = observacao or None
        db.flush()

        tipo_inter = clean_text(payload.get("intercorrencia"), 200)
        if tipo_inter:
            db.add(Intercorrencia(
                data=dia, paciente_id=paciente.id, paciente_nome=paciente.nome_completo, tipo=tipo_inter,
                enfermeiro_nome=enf_nome, protocolo=protocolo or MODALIDADE_LABEL[modalidade],
                medida_tomada=clean_text(payload.get("medida_tomada"), 1000) or None,
                observacao="Registrado junto ao agendamento", agendamento_id=ag.id, criado_por_id=usuario_id,
            ))
            db.flush()
        return ag


def termino_previsto(db: Session, a: Agendamento) -> str:
    _, _, _, eh = _intervalo(a, mapa_protocolos(db))
    return eh


def listar(db: Session, data_str: str, modalidade: str = "") -> List[Dict[str, Any]]:
    dia = parse_date_br(data_str)
    if not dia:
        raise RegraNegocio("Data inválida.")
    mod = modalidade if modalidade in MODALIDADE_LABEL else None
    prot_map = mapa_protocolos(db)
    itens = []
    for a in agendamentos_do_dia(db, dia, mod):
        d = agendamento_dict(a)
        _, _, sh, eh = _intervalo(a, prot_map)
        d["janela"] = f"{sh}–{eh}" if sh and eh else a.hora
        itens.append(d)
    return itens


def mural(db: Session, data_str: str, modalidade: str = "TODOS") -> Dict[str, Any]:
    dia = parse_date_br(data_str)
    if not dia:
        raise RegraNegocio("Data inválida. Informe uma data no formato DD/MM/AAAA.")
    mod = (modalidade or "TODOS").upper()
    alias = {"AGENDA_QT": "QT", "QT": "QT", "CONSULTA_ENF": "CONSULTA_ENF", "TELECONSULTA": "TELECONSULTA"}
    filtro = alias.get(mod)
    prot_map = mapa_protocolos(db)
    itens = []
    for a in agendamentos_do_dia(db, dia, filtro):
        s, _, sh, eh = _intervalo(a, prot_map)
        cmp_ = (a.compareceu or "").upper()
        itens.append({
            "id": a.id,
            "modalidade": a.modalidade,
            "tipo_label": MODALIDADE_LABEL[a.modalidade],
            "data": fmt_date(dia),
            "hora": f"{sh} – {eh}" if sh and eh and sh != eh else a.hora,
            "inicio_min": s if s is not None else 9999,
            "paciente": a.paciente.nome_completo if a.paciente else "Não informado",
            "protocolo": a.protocolo or f"{MODALIDADE_LABEL[a.modalidade]} (1h)",
            "enfermeiro": a.enfermeiro_nome or "Não informado",
            "local_atendimento": a.box or MODALIDADE_LOCAL.get(a.modalidade, "Box não definido"),
            "compareceu": cmp_,
            "situacao": "Compareceu" if cmp_ == "S" else ("Falta / Cancelado" if cmp_ == "N" else "Agendado"),
        })
    itens.sort(key=lambda x: (x["inicio_min"], x["local_atendimento"], x["paciente"]))
    enfermeiros = sorted({i["enfermeiro"] for i in itens if i["enfermeiro"] != "Não informado"})
    return {
        "ok": True,
        "data": fmt_date(dia),
        "dia_semana": dia_semana(dia),
        "modalidade_filtro": mod,
        "total_geral": len(itens),
        "total_quimioterapia": sum(1 for i in itens if i["modalidade"] == "QT"),
        "total_consulta_enf": sum(1 for i in itens if i["modalidade"] == "CONSULTA_ENF"),
        "total_teleconsulta": sum(1 for i in itens if i["modalidade"] == "TELECONSULTA"),
        "total_presencas": sum(1 for i in itens if i["compareceu"] == "S"),
        "total_faltas": sum(1 for i in itens if i["compareceu"] == "N"),
        "enfermeiros_escalados": enfermeiros,
        "itens": itens,
    }


__all__ = ["disponibilidade", "salvar", "listar", "mural", "lista_boxes", "calculate_end_time", "termino_previsto"]
