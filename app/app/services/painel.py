"""
Painel ao vivo: retrato simplificado do setor AGORA (poltronas em uso, quem está chegando,
atrasos, presença e ocupação por hora). Pensado para celular e para TV/monitor no setor.
Nomes aparecem abreviados (ex.: "Ana F. S.") para reduzir exposição de dados em telas públicas.
"""

from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Intercorrencia
from app.services.agenda import _intervalo, agendamentos_do_dia, mapa_protocolos
from app.services.common import MODALIDADE_LABEL, MODALIDADE_LOCAL
from app.services.validators import dia_semana, fmt_date, normalize_box_id

TOLERANCIA_ATRASO_MIN = 15


def nome_curto(nome: str) -> str:
    partes = [p for p in (nome or "").split() if p.lower() not in ("da", "de", "do", "das", "dos", "e")]
    if not partes:
        return ""
    return partes[0] + ("" if len(partes) == 1 else " " + " ".join(f"{p[0].upper()}." for p in partes[1:]))


def painel(db: Session, agora: Optional[datetime] = None) -> Dict[str, Any]:
    agora = agora or datetime.now()
    hoje: date = agora.date()
    agora_min = agora.hour * 60 + agora.minute
    prot_map = mapa_protocolos(db)
    ags = agendamentos_do_dia(db, hoje)

    poltronas: Dict[str, Dict[str, Any]] = {
        f"BOX {i}": {"box": f"Box {i}", "status": "livre"} for i in range(1, settings.qtd_poltronas + 1)
    }
    em_atendimento, proximos, atrasados = [], [], []
    presentes = faltas = aguardando = concluidos = 0
    horas_ocupadas = 0.0
    ocupacao_hora = {h: 0 for h in range(8, 8 + settings.horas_funcionamento_dia)}

    for a in ags:
        s, e, sh, eh = _intervalo(a, prot_map)
        if s is None:
            continue
        cmp_ = (a.compareceu or "").upper()
        nome = nome_curto(a.paciente.nome_completo if a.paciente else "")
        local = a.box or MODALIDADE_LOCAL.get(a.modalidade, "")
        item = {"id": a.id, "paciente": nome, "hora": sh, "fim": eh, "local": local,
                "modalidade": MODALIDADE_LABEL[a.modalidade], "protocolo": a.protocolo or ""}

        if cmp_ == "S":
            presentes += 1
        elif cmp_ == "N":
            faltas += 1
            continue  # falta libera a vaga: não conta como ocupação
        else:
            aguardando += 1

        if a.modalidade == "QT":
            horas_ocupadas += max(0, e - s) / 60
            for h in ocupacao_hora:
                if s < (h + 1) * 60 and e > h * 60:
                    ocupacao_hora[h] += 1

        # Só conta como encerrado se o paciente chegou; quem não chegou e não foi marcado segue como atrasado
        terminou = bool(a.hora_termino) or (e <= agora_min and (cmp_ == "S" or bool(a.hora_inicio)))
        em_curso = s <= agora_min < e and not a.hora_termino
        if terminou and cmp_ == "S":
            concluidos += 1

        if em_curso and (cmp_ == "S" or a.hora_inicio):
            pct = round((agora_min - s) / max(1, e - s) * 100)
            em_atendimento.append({**item, "progresso_pct": pct, "restante_min": e - agora_min})
            chave = normalize_box_id(a.box)
            if a.modalidade == "QT" and chave in poltronas:
                poltronas[chave].update({"status": "ocupada", "paciente": nome, "fim": eh, "progresso_pct": pct,
                                         "protocolo": a.protocolo or ""})
        elif not cmp_ and not a.hora_inicio and agora_min > s + TOLERANCIA_ATRASO_MIN and not terminou:
            atrasados.append({**item, "atraso_min": agora_min - s})
            chave = normalize_box_id(a.box)
            if a.modalidade == "QT" and chave in poltronas and s <= agora_min < e and poltronas[chave]["status"] == "livre":
                poltronas[chave].update({"status": "aguardando", "paciente": nome, "fim": eh})
        elif s >= agora_min - TOLERANCIA_ATRASO_MIN and not cmp_ and not a.hora_inicio:
            proximos.append({**item, "em_min": s - agora_min})
            chave = normalize_box_id(a.box)
            if a.modalidade == "QT" and chave in poltronas and s <= agora_min and poltronas[chave]["status"] == "livre":
                poltronas[chave].update({"status": "aguardando", "paciente": nome, "fim": eh})

    proximos.sort(key=lambda x: x["hora"])
    capacidade = settings.qtd_poltronas * settings.horas_funcionamento_dia
    ocupadas_agora = sum(1 for p in poltronas.values() if p["status"] == "ocupada")
    inter_hoje = db.execute(select(func.count(Intercorrencia.id)).where(Intercorrencia.data == hoje)).scalar() or 0
    avaliados = presentes + faltas

    return {
        "ok": True,
        "data": fmt_date(hoje),
        "dia_semana": dia_semana(hoje),
        "agora": agora.strftime("%H:%M"),
        "atualizado_em": agora.strftime("%H:%M:%S"),
        "kpis": {
            "agendados": len(ags),
            "presentes": presentes,
            "faltas": faltas,
            "aguardando": aguardando,
            "em_atendimento": len(em_atendimento),
            "concluidos": concluidos,
            "atrasados": len(atrasados),
            "poltronas_ocupadas_agora": ocupadas_agora,
            "poltronas_total": settings.qtd_poltronas,
            "ocupacao_dia_pct": round(horas_ocupadas / capacidade * 100, 1) if capacidade else 0.0,
            "horas_ocupadas": round(horas_ocupadas, 1),
            "capacidade_horas": capacidade,
            "taxa_presenca_pct": round(presentes / avaliados * 100, 1) if avaliados else None,
            "intercorrencias_hoje": inter_hoje,
        },
        "poltronas": list(poltronas.values()),
        "em_atendimento": sorted(em_atendimento, key=lambda x: x["restante_min"]),
        "proximos": proximos[:8],
        "atrasados": sorted(atrasados, key=lambda x: -x["atraso_min"]),
        "ocupacao_por_hora": [
            {"hora": f"{h:02d}:00", "poltronas": n, "agora": h * 60 <= agora_min < (h + 1) * 60}
            for h, n in ocupacao_hora.items()
        ],
    }
