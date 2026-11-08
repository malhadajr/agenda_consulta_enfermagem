"""Geração do Mural diário em PDF (ReportLab) e PNG (Matplotlib)."""

import io
from datetime import datetime
from typing import Any, Dict
from xml.sax.saxutils import escape

from app.config import settings


def _e(texto: Any) -> str:
    """Escapa texto para o mini-HTML do ReportLab (evita injeção de marcação)."""
    return escape(str(texto or ""))


def mural_pdf(dados: Dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=25, rightMargin=25, topMargin=20,
                            bottomMargin=20, title="Mural diário de atendimentos", author="Nova Agenda 2027")
    roxo, lilas = colors.HexColor("#4A148C"), colors.HexColor("#7B1FA2")
    titulo = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=roxo, alignment=1)
    sub = ParagraphStyle("s", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=lilas, alignment=1)
    meta = ParagraphStyle("m", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#424242"), alignment=1)
    th = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.white, alignment=1)
    td = ParagraphStyle("td", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#37474F"), alignment=1)
    td_b = ParagraphStyle("tdb", parent=td, fontName="Helvetica-Bold", textColor=roxo)
    td_p = ParagraphStyle("tdp", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.HexColor("#212121"))

    story = [
        Paragraph(_e(settings.nome_instituicao), titulo),
        Paragraph(_e(f"MURAL DIÁRIO DE ATENDIMENTOS • {dados.get('data', '')} ({dados.get('dia_semana', '')})"), sub),
        Paragraph(
            f"<b>Total:</b> {int(dados.get('total_geral', 0))} &nbsp;|&nbsp; "
            f"<b>Quimioterapia:</b> {int(dados.get('total_quimioterapia', 0))} &nbsp;|&nbsp; "
            f"<b>Consultas:</b> {int(dados.get('total_consulta_enf', 0))} &nbsp;|&nbsp; "
            f"<b>Teleconsultas:</b> {int(dados.get('total_teleconsulta', 0))}",
            meta,
        ),
        Spacer(1, 8),
    ]
    cab = ["DATA", "HORA", "PACIENTE", "PROTOCOLO", "ENFERMEIRO(A)", "BOX / ATENDIMENTO", "SITUAÇÃO"]
    linhas = [[Paragraph(c, th) for c in cab]]
    itens = dados.get("itens", [])
    if not itens:
        linhas.append([Paragraph("-", td), Paragraph("-", td), Paragraph("Nenhum atendimento agendado para esta data.", td),
                       Paragraph("-", td), Paragraph("-", td), Paragraph("-", td), Paragraph("-", td)])
    for it in itens:
        cor = "#2E7D32" if it["compareceu"] == "S" else ("#C62828" if it["compareceu"] == "N" else "#6A1B9A")
        sit = ParagraphStyle("sit", parent=td, fontName="Helvetica-Bold", textColor=colors.HexColor(cor))
        linhas.append([
            Paragraph(_e(it["data"]), td), Paragraph(_e(it["hora"]), td_b), Paragraph(_e(it["paciente"]), td_p),
            Paragraph(_e(it["protocolo"]), td), Paragraph(_e(it["enfermeiro"]), td),
            Paragraph(_e(it["local_atendimento"]), td_b), Paragraph(_e(it["situacao"]), sit),
        ])
    tabela = Table(linhas, colWidths=[65, 85, 205, 120, 140, 110, 67], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), roxo),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1C4E9")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F4FA")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [tabela, Spacer(1, 10), Paragraph(
        _e(f"Gerado pelo sistema Nova Agenda 2027 em {datetime.now().strftime('%d/%m/%Y às %H:%M')} • "
           "Documento com dados pessoais de saúde — uso interno (LGPD)."),
        ParagraphStyle("f", fontName="Helvetica", fontSize=7.5, textColor=colors.HexColor("#757575"), alignment=1),
    )]
    doc.build(story)
    return buf.getvalue()


def mural_png(dados: Dict[str, Any]) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def _t(s: Any, n: int = 60) -> str:
        s = str(s or "").replace("$", r"\$")  # evita interpretação como fórmula matemática
        return s if len(s) <= n else s[: n - 3] + "..."

    itens = dados.get("itens", [])
    fig, ax = plt.subplots(figsize=(14, max(7.0, 2.2 + max(len(itens), 1) * 0.42)), dpi=160)
    ax.axis("off")
    plt.suptitle(_t(settings.nome_instituicao, 120), fontsize=13, fontweight="bold", color="#4A148C", y=0.97)
    plt.title(
        _t(f"MURAL DIÁRIO DE ATENDIMENTOS • {dados.get('data', '')} ({dados.get('dia_semana', '')})", 120)
        + f"\nTotal: {int(dados.get('total_geral', 0))}  |  Quimioterapia: {int(dados.get('total_quimioterapia', 0))}"
        f"  |  Consultas: {int(dados.get('total_consulta_enf', 0))}  |  Teleconsultas: {int(dados.get('total_teleconsulta', 0))}",
        fontsize=9.5, color="#6A1B9A", pad=12, linespacing=1.4,
    )
    cab = ["DATA", "HORA", "PACIENTE", "PROTOCOLO", "ENFERMEIRO(A)", "BOX / ATENDIMENTO", "SITUAÇÃO"]
    linhas = [[_t(i["data"]), _t(i["hora"]), _t(i["paciente"], 34), _t(i["protocolo"], 28), _t(i["enfermeiro"], 28),
               _t(i["local_atendimento"]), _t(i["situacao"])] for i in itens] or [
        ["-", "-", "Nenhum agendamento para esta data", "-", "-", "-", "-"]]
    tab = ax.table(cellText=linhas, colLabels=cab, colWidths=[0.10, 0.12, 0.28, 0.16, 0.18, 0.16, 0.11],
                   cellLoc="center", loc="center")
    tab.auto_set_font_size(False)
    tab.set_fontsize(8.5)
    tab.scale(1, 1.8)
    for c in range(len(cab)):
        cel = tab[(0, c)]
        cel.set_facecolor("#4A148C")
        cel.get_text().set_color("white")
        cel.get_text().set_weight("bold")
    for r in range(1, len(linhas) + 1):
        for c in range(len(cab)):
            tab[(r, c)].set_facecolor("#FFFFFF" if r % 2 else "#F7F2FA")
    out = io.BytesIO()
    plt.savefig(out, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out.getvalue()
