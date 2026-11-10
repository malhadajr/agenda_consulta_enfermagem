"""Mapa de calor de ocupação, dashboards, análise de tempo real x estimado e estatísticas diárias."""

import calendar
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import (
    Agendamento,
    EstatisticaAgendamento,
    EstatisticaAuditoria,
    Intercorrencia,
    Paciente,
)
from app.services.agenda import _intervalo, mapa_protocolos
from app.services.common import intercorrencia_dict
from app.services.validators import fmt_date, minutes_to_hhmm, normalize_box_id, time_to_minutes

NOMES_MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
               "Setembro", "Outubro", "Novembro", "Dezembro"]


def _qt_periodo(db: Session, ano: int, mes: Optional[int] = None) -> List[Agendamento]:
    stmt = (
        select(Agendamento).options(joinedload(Agendamento.paciente))
        .where(Agendamento.modalidade == "QT", extract("year", Agendamento.data) == ano)
    )
    if mes:
        stmt = stmt.where(extract("month", Agendamento.data) == mes)
    return list(db.execute(stmt).scalars())


# =============================================================================
# MAPA DE CALOR
# =============================================================================

def mapa_calor(db: Session, ano: int, mes: Optional[int], qtd_poltronas: int, horas_funcionamento: int) -> Dict[str, Any]:
    prot_map = mapa_protocolos(db)
    capacidade_dia = float(qtd_poltronas * horas_funcionamento)
    horas_por_data: Dict[date, float] = {}
    atend_por_data: Dict[date, int] = {}
    horas_por_prot: Dict[str, float] = {}
    horas_por_box: Dict[str, float] = {f"Box {i}": 0.0 for i in range(1, qtd_poltronas + 1)}
    registros = []

    for a in _qt_periodo(db, ano, mes):
        if (a.compareceu or "").upper() == "N":
            continue
        t_est = a.tempo_estimado or prot_map.get((a.protocolo or "").upper(), "01:00")
        est_min = time_to_minutes(t_est) or 60
        s, e, sh, eh = _intervalo(a, prot_map)
        real_min = max(0, e - s) if s is not None and e is not None else est_min
        h = real_min / 60.0
        horas_por_data[a.data] = horas_por_data.get(a.data, 0.0) + h
        atend_por_data[a.data] = atend_por_data.get(a.data, 0) + 1
        if a.protocolo:
            horas_por_prot[a.protocolo] = horas_por_prot.get(a.protocolo, 0.0) + h
        b = normalize_box_id(a.box)
        if b.startswith("BOX "):
            chave = f"Box {b[4:]}"
            horas_por_box[chave] = horas_por_box.get(chave, 0.0) + h
        if a.hora_inicio and a.hora_termino:
            diff = real_min - est_min
            registros.append({
                "data": fmt_date(a.data), "box": a.box, "protocolo": a.protocolo,
                "tempo_estimado_hhmm": minutes_to_hhmm(est_min), "hora_entrada": sh, "hora_saida": eh,
                "tempo_ocupacao_real_hhmm": minutes_to_hhmm(real_min), "diferenca_minutos": diff,
            })

    cal = calendar.Calendar(firstweekday=6)
    meses = []
    for m in ([mes] if mes else range(1, 13)):
        dias_uteis, total_mes, semanas = 0, 0.0, []
        for semana in cal.monthdatescalendar(ano, m):
            cel = []
            for d in semana:
                if d.month != m:
                    cel.append({"vazio": True})
                    continue
                fds = d.weekday() >= 5
                if not fds:
                    dias_uteis += 1
                h_dia = round(horas_por_data.get(d, 0.0), 2)
                total_mes += h_dia
                ociosas = 0.0 if fds else max(0.0, round(capacidade_dia - h_dia, 2))
                if fds:
                    classe, status = "fim-de-semana", "Fim de semana"
                elif h_dia < capacidade_dia - 0.01:
                    classe, status = "ocioso", f"Cadeiras ociosas ({ociosas}h livres)"
                elif abs(h_dia - capacidade_dia) <= 0.01:
                    classe, status = "meta", "100% da capacidade"
                else:
                    classe, status = "sobrecarga", f"Acima da capacidade (+{round(h_dia - capacidade_dia, 2)}h)"
                cel.append({
                    "vazio": False, "dia": d.day, "data_br": fmt_date(d), "horas_ocupadas": h_dia,
                    "horas_ociosas": ociosas, "atendimentos": atend_por_data.get(d, 0),
                    "taxa_ocupacao_pct": round(h_dia / capacidade_dia * 100, 1) if capacidade_dia else 0.0,
                    "classe_cor": classe, "status_dia": status,
                })
            semanas.append(cel)
        cap_mes = round(dias_uteis * capacidade_dia, 2)
        total_mes = round(total_mes, 2)
        meses.append({
            "mes": m, "nome_mes": NOMES_MESES[m], "ano": ano, "dias_uteis": dias_uteis,
            "capacidade_mes_horas": cap_mes, "total_ocupacao_mes_horas": total_mes,
            "saldo_horas": round(total_mes - cap_mes, 2),
            "horas_ociosas_mes": max(0.0, round(cap_mes - total_mes, 2)),
            "taxa_ocupacao_pct": round(total_mes / cap_mes * 100, 1) if cap_mes else 0.0,
            "semanas": semanas,
        })

    return {
        "ok": True, "ano": ano, "mes_filtrado": mes,
        "parametros": {"qtd_poltronas": qtd_poltronas, "horas_funcionamento_dia": horas_funcionamento,
                       "capacidade_diaria_horas": capacidade_dia},
        "meses": meses,
        "top_protocolos": sorted(
            [{"protocolo": k, "horas_ocupadas": round(v, 2)} for k, v in horas_por_prot.items()],
            key=lambda x: -x["horas_ocupadas"],
        )[:10],
        "ocupacao_por_box": [{"box": k, "horas_ocupadas": round(v, 2)} for k, v in horas_por_box.items()],
        "registros_tempo_real_vs_estimado": registros[-100:][::-1],
    }


# =============================================================================
# TEMPO REAL x ESTIMADO
# =============================================================================

def analise_tempo(db: Session, ano: int, mes: Optional[int] = None) -> Dict[str, Any]:
    prot_map = mapa_protocolos(db)
    inter = db.execute(select(Intercorrencia.paciente_id, Intercorrencia.data, Intercorrencia.tipo)).all()
    inter_lookup: Dict[tuple, List[str]] = {}
    for pid, d, t in inter:
        inter_lookup.setdefault((pid, d), []).append(t)

    por_prot: Dict[str, List[Dict[str, Any]]] = {}
    por_enf: Dict[str, List[Dict[str, Any]]] = {}
    total = 0
    for a in _qt_periodo(db, ano, mes):
        ini, fim = time_to_minutes(a.hora_inicio), time_to_minutes(a.hora_termino)
        if ini is None or fim is None or fim <= ini:
            continue
        real = fim - ini
        est = time_to_minutes(a.tempo_estimado or prot_map.get((a.protocolo or "").upper(), "")) or 60
        desvio_pct = round((real - est) / est * 100.0, 1)
        classe = "MUITO_RAPIDO" if desvio_pct < -10 else ("MUITO_DEVAGAR" if desvio_pct > 10 else "NO_TEMPO")
        item = {"est": est, "real": real, "classe": classe, "inter": (a.paciente_id, a.data) in inter_lookup}
        por_prot.setdefault((a.protocolo or "NÃO INFORMADO").upper(), []).append(item)
        por_enf.setdefault(a.enfermeiro_nome or "Não especificado", []).append(item)
        total += 1

    def _resumo(itens):
        n = len(itens)
        est = sum(i["est"] for i in itens) / n
        real = sum(i["real"] for i in itens) / n
        dm = real - est
        dp = dm / est * 100 if est else 0.0
        c = {k: sum(1 for i in itens if i["classe"] == k) for k in ("MUITO_RAPIDO", "NO_TEMPO", "MUITO_DEVAGAR")}
        return n, est, real, dm, dp, c, sum(1 for i in itens if i["inter"])

    protocolos = []
    for nome, itens in por_prot.items():
        n, est, real, dm, dp, c, ni = _resumo(itens)
        p_rap, p_dev = c["MUITO_RAPIDO"] / n * 100, c["MUITO_DEVAGAR"] / n * 100
        if p_rap >= 40 and dp <= -10:
            rotulo, badge = "MUITO RÁPIDO", "rapido"
        elif p_dev >= 40 and dp >= 10:
            rotulo, badge = "MUITO DEVAGAR", "devagar"
        else:
            rotulo, badge = "NO TEMPO (±10%)", "notempo"
        protocolos.append({
            "protocolo": nome, "total_atendimentos": n,
            "tempo_estimado_medio_hhmm": minutes_to_hhmm(int(est)), "tempo_real_medio_hhmm": minutes_to_hhmm(int(real)),
            "desvio_medio_min": round(dm, 1), "desvio_medio_pct": round(dp, 1),
            "muito_rapido_count": c["MUITO_RAPIDO"], "no_tempo_count": c["NO_TEMPO"],
            "muito_devagar_count": c["MUITO_DEVAGAR"], "intercorrencias_count": ni,
            "status_geral": rotulo, "status_badge": badge,
        })
    protocolos.sort(key=lambda x: abs(x["desvio_medio_pct"]), reverse=True)

    enfermeiros = []
    for nome, itens in por_enf.items():
        n, est, real, dm, dp, c, ni = _resumo(itens)
        if c["MUITO_RAPIDO"] > c["MUITO_DEVAGAR"] and dp < -5:
            tend, badge = "Acelerando", "rapido"
        elif c["MUITO_DEVAGAR"] > c["MUITO_RAPIDO"] and dp > 5:
            tend, badge = "Atrasando", "devagar"
        else:
            tend, badge = "No ritmo planejado", "notempo"
        enfermeiros.append({
            "enfermeiro": nome, "total_atendimentos": n, "tempo_estimado_medio_min": round(est, 1),
            "tempo_real_medio_min": round(real, 1), "desvio_medio_min": round(dm, 1), "desvio_medio_pct": round(dp, 1),
            "muito_rapido_count": c["MUITO_RAPIDO"], "no_tempo_count": c["NO_TEMPO"],
            "muito_devagar_count": c["MUITO_DEVAGAR"], "intercorrencias_presentes": ni,
            "tendencia": tend, "badge": badge,
        })
    enfermeiros.sort(key=lambda x: x["desvio_medio_pct"])
    return {"total_infusoes_analisadas": total, "resumo_protocolos": protocolos, "resumo_enfermeiros": enfermeiros}


# =============================================================================
# ESTATÍSTICAS DIÁRIAS (AUDITORIA CLÍNICA PRÉVIA E AGENDAMENTO)
# =============================================================================

CAMPOS_AUDITORIA = {
    "total_auditados": "Nº total de prontuários AUDITADOS no dia",
    "validados": "Nº de prontuários VALIDADOS no dia",
    "exame_incompativel": "Exame laboratorial incompatível com a liberação do tratamento",
    "dose_nao_conforme": "Necessidade de reavaliação de dose (dose não conforme)",
    "incompatibilidade_evolucao_prescricao": "Incompatibilidade entre evolução médica e prescrição/receita (encaminhados à supervisão)",
    "sem_evolucao_ou_prescricao": "Sem evolução médica e/ou prescrição de quimioterapia",
    "sem_dados_antropometricos": "Sem dados antropométricos atualizados / divergência",
    "receita_ausente_ou_errada": "Receita médica ausente/errada/incompleta/incompreensível",
    "encaminhamentos_multiprofissional": "Encaminhamentos para a Equipe Multiprofissional",
}

CAMPOS_AGENDAMENTO = {
    "validados_infusao": "Nº total de prontuários VALIDADOS no dia da infusão",
    "primeira_vez": "Nº de agendamentos de 1ª VEZ",
    "retorno_controle": "Nº de agendamentos de RETORNO após período de controle",
    "reagendamentos": "Nº de REAGENDAMENTOS",
    "avaliacao_supervisao": "Pacientes com necessidade de avaliação clínica pela SUPERVISÃO",
    "avaliacao_enfermeiro": "Pacientes com necessidade de avaliação clínica pelo ENFERMEIRO",
    "sem_receita_medica": "Pacientes sem RECEITA MÉDICA ou com receita errada/incompleta",
    "sem_exames_laboratoriais": "Pacientes sem SOLICITAÇÃO DE EXAMES LABORATORIAIS ou pedido errado",
    "sem_exames_imagem": "Pacientes sem PEDIDO DE EXAMES DE IMAGEM ou pedido errado",
    "encaminhamentos_multiprofissional": "Encaminhamentos para a Equipe Multiprofissional",
}


def _filtro_periodo(stmt, coluna, ano: Optional[int], mes: Optional[int]):
    if ano:
        stmt = stmt.where(extract("year", coluna) == ano)
    if mes:
        stmt = stmt.where(extract("month", coluna) == mes)
    return stmt


def estatisticas_consolidadas(db: Session, ano: Optional[int] = None, mes: Optional[int] = None) -> Dict[str, Any]:
    aud = {k: 0 for k in CAMPOS_AUDITORIA}
    for r in db.execute(_filtro_periodo(select(EstatisticaAuditoria), EstatisticaAuditoria.data, ano, mes)).scalars():
        for k in aud:
            aud[k] += getattr(r, k) or 0
    agd = {k: 0 for k in CAMPOS_AGENDAMENTO}
    for r in db.execute(_filtro_periodo(select(EstatisticaAgendamento), EstatisticaAgendamento.data, ano, mes)).scalars():
        for k in agd:
            agd[k] += getattr(r, k) or 0

    pend = {CAMPOS_AUDITORIA[k]: aud[k] for k in (
        "exame_incompativel", "dose_nao_conforme", "incompatibilidade_evolucao_prescricao",
        "sem_evolucao_ou_prescricao", "sem_dados_antropometricos", "receita_ausente_ou_errada",
        "encaminhamentos_multiprofissional")}
    pend["Sem solicitação de exames laboratoriais"] = agd["sem_exames_laboratoriais"]
    pend["Sem pedido de exames de imagem"] = agd["sem_exames_imagem"]
    pend["Necessidade de avaliação clínica pela Supervisão"] = agd["avaliacao_supervisao"]
    pend["Necessidade de avaliação clínica pelo Enfermeiro"] = agd["avaliacao_enfermeiro"]
    ranking = [{"motivo": k, "quantidade": v} for k, v in sorted(pend.items(), key=lambda x: -x[1]) if v > 0]
    taxa = round(aud["validados"] / aud["total_auditados"] * 100, 1) if aud["total_auditados"] else 0.0
    return {
        "total_auditados": aud["total_auditados"], "total_validados": aud["validados"],
        "total_pendencias": sum(r["quantidade"] for r in ranking), "taxa_validacao_pct": taxa,
        "ranking_pendencias": ranking, "auditoria": aud, "estatistica_agendamento": agd,
    }


# =============================================================================
# DASHBOARD EXECUTIVO
# =============================================================================

def dashboard(db: Session, ano: Optional[int] = None, mes: Optional[int] = None) -> Dict[str, Any]:
    hoje = date.today()
    ano = ano or hoje.year
    mes = mes or hoje.month

    total_pac = db.execute(select(func.count(Paciente.id))).scalar() or 0
    enc = db.execute(select(func.count(Paciente.id)).where(Paciente.status == "ENCERRADO")).scalar() or 0

    ags = list(db.execute(
        select(Agendamento).options(joinedload(Agendamento.paciente)).where(extract("year", Agendamento.data) == ano)
    ).scalars())
    ag_mes = [a for a in ags if a.data.month == mes]
    por_mod = {m: sum(1 for a in ag_mes if a.modalidade == m) for m in ("QT", "CONSULTA_ENF", "TELECONSULTA")}
    pres = sum(1 for a in ag_mes if a.compareceu == "S")
    falt = sum(1 for a in ag_mes if a.compareceu == "N")
    aval = pres + falt

    # Série do ano (alimenta o gráfico 3D "Atendimentos por mês" da aba Visão geral).
    # Sempre devolve os 12 meses, mesmo os zerados, para o eixo do gráfico não mudar de tamanho.
    serie_mensal = []
    for m in range(1, 13):
        do_mes = [a for a in ags if a.data.month == m]
        serie_mensal.append({
            "mes": m, "mes_nome": NOMES_MESES[m], "total": len(do_mes),
            "quimioterapia": sum(1 for a in do_mes if a.modalidade == "QT"),
            "consulta_enf": sum(1 for a in do_mes if a.modalidade == "CONSULTA_ENF"),
            "teleconsulta": sum(1 for a in do_mes if a.modalidade == "TELECONSULTA"),
            "presencas": sum(1 for a in do_mes if a.compareceu == "S"),
            "faltas": sum(1 for a in do_mes if a.compareceu == "N"),
        })

    # Ranking de faltas (ano inteiro) — busca ativa
    faltas: Dict[int, Dict[str, Any]] = {}
    for a in ags:
        f = faltas.setdefault(a.paciente_id, {"p": a.paciente, "faltas": 0, "total": 0})
        f["total"] += 1
        if a.compareceu == "N":
            f["faltas"] += 1
    ranking_faltas = sorted(
        [
            {"paciente_id": pid, "prontuario": v["p"].prontuario or "-", "nome_completo": v["p"].nome_completo,
             "total_faltas": v["faltas"], "total_agendamentos": v["total"],
             "taxa_falta_pct": round(v["faltas"] / v["total"] * 100, 1), "telefone": v["p"].telefone or "-",
             "status": v["p"].status}
            for pid, v in faltas.items() if v["faltas"] > 0
        ],
        key=lambda x: (x["total_faltas"], x["taxa_falta_pct"]), reverse=True,
    )[:10]

    prot_map = mapa_protocolos(db)
    qt_mes = [a for a in ag_mes if a.modalidade == "QT"]
    cont: Dict[str, int] = {}
    for a in qt_mes:
        if a.protocolo:
            cont[a.protocolo] = cont.get(a.protocolo, 0) + 1
    tot_qt = max(1, len(qt_mes))
    top_prot = []
    for nome, n in sorted(cont.items(), key=lambda x: -x[1])[:10]:
        dur = prot_map.get(nome.upper(), "01:00")
        top_prot.append({"protocolo": nome, "total_agendado": n, "percentual": round(n / tot_qt * 100, 1),
                         "tempo_estimado_hhmm": dur,
                         "horas_totais_estimadas": round(n * (time_to_minutes(dur) or 60) / 60, 1)})

    inter_q = _filtro_periodo(select(Intercorrencia), Intercorrencia.data, ano, mes)
    inters = list(db.execute(inter_q.order_by(Intercorrencia.data.desc(), Intercorrencia.id.desc())).scalars())

    def _conta(chave):
        c: Dict[str, int] = {}
        for i in inters:
            v = chave(i)
            if v:
                c[v] = c.get(v, 0) + 1
        return sorted(c.items(), key=lambda x: -x[1])

    tempo = analise_tempo(db, ano, mes)
    return {
        "ok": True,
        "periodo": {"ano": ano, "mes": mes, "mes_nome": NOMES_MESES[mes]},
        "kpis": {
            "total_pacientes": total_pac, "pacientes_iniciados": total_pac - enc, "pacientes_encerrados": enc,
            "agendamentos_mes": len(ag_mes), "agendamentos_ano": len(ags),
            "total_quimioterapia": por_mod["QT"], "total_consulta_enf": por_mod["CONSULTA_ENF"],
            "total_teleconsulta": por_mod["TELECONSULTA"], "total_compareceram": pres, "total_faltas": falt,
            "taxa_presenca_pct": round(pres / aval * 100, 1) if aval else 0.0,
            "taxa_falta_pct": round(falt / aval * 100, 1) if aval else 0.0,
            "total_intercorrencias": len(inters),
        },
        "serie_mensal": serie_mensal,
        "top_protocolos": top_prot,
        "top_pacientes_faltas": ranking_faltas,
        "pendencias_auditoria": estatisticas_consolidadas(db, ano, mes),
        "tempo_real_protocolos": tempo["resumo_protocolos"],
        "desempenho_enfermeiros": tempo["resumo_enfermeiros"],
        "total_infusoes_analisadas": tempo["total_infusoes_analisadas"],
        "intercorrencias": {
            "total": len(inters),
            "principais_tipos": [{"tipo": k, "quantidade": v} for k, v in _conta(lambda i: i.tipo)],
            "por_protocolo": [{"protocolo": k, "quantidade": v} for k, v in _conta(lambda i: (i.protocolo or "").upper())],
            "por_enfermeiro": [{"enfermeiro": k, "quantidade": v} for k, v in _conta(lambda i: i.enfermeiro_nome)],
            "ocorrencias_recentes": [intercorrencia_dict(i) for i in inters[:10]],
        },
    }
