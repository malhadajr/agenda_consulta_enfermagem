"""Endpoints de agendamento, grade de disponibilidade e mural diário (tela, PDF e PNG)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Agendamento
from app.security import LEITURA, OPERACAO, CurrentUser, client_ip, require_roles
from app.services import agenda as svc
from app.services import audit
from app.services.common import RegraNegocio, agendamento_dict
from app.services.exportacao import mural_pdf, mural_png
from app.services.validators import parse_date_br

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


class AgendamentoIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    modalidade: str = Field(default="QT", max_length=15)
    data: str = Field(max_length=10)
    hora: str = Field(max_length=5)
    box: Optional[str] = Field(default="", max_length=40)
    paciente_id: int
    protocolo: Optional[str] = Field(default="", max_length=160)
    tempo_estimado: Optional[str] = Field(default="", max_length=5)
    compareceu: Optional[str] = Field(default="", max_length=1)
    hora_inicio: Optional[str] = Field(default="", max_length=5)
    hora_termino: Optional[str] = Field(default="", max_length=5)
    enfermeiro_id: Optional[int] = None
    observacao: Optional[str] = Field(default="", max_length=1000)
    intercorrencia: Optional[str] = Field(default="", max_length=200)
    medida_tomada: Optional[str] = Field(default="", max_length=1000)


def _obter(db: Session, ag_id: int) -> Agendamento:
    a = db.get(Agendamento, ag_id)
    if not a:
        raise RegraNegocio("Agendamento não encontrado.", "NAO_ENCONTRADO", 404)
    return a


@router.get("/disponibilidade")
def disponibilidade(
    data: str = Query(..., max_length=10), box: str = Query("", max_length=40),
    protocolo: str = Query("", max_length=160), tempo_estimado: str = Query("", max_length=5),
    modalidade: str = Query("QT", max_length=15), ignorar_id: Optional[int] = Query(None),
    _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db),
):
    return svc.disponibilidade(db, data, box, protocolo, tempo_estimado, modalidade, ignorar_id)


@router.get("")
def listar(data: str = Query(..., max_length=10), modalidade: str = Query("", max_length=15),
           _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    itens = svc.listar(db, data, modalidade)
    return {"ok": True, "total": len(itens), "agendamentos": itens}


@router.get("/mural")
def mural(data: str = Query(..., max_length=10), modalidade: str = Query("TODOS", max_length=15),
          _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    return svc.mural(db, data, modalidade)


def _nome_arquivo(data: str, ext: str) -> str:
    d = parse_date_br(data)
    return f"mural_{d.isoformat() if d else 'dia'}.{ext}"


@router.get("/mural.pdf")
def mural_em_pdf(request: Request, data: str = Query(..., max_length=10), modalidade: str = Query("TODOS", max_length=15),
                 user: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    dados = svc.mural(db, data, modalidade)
    audit.registrar(db, "EXPORTAR_MURAL_PDF", usuario=user, detalhe=dados["data"], ip=client_ip(request), commit=True)
    return Response(mural_pdf(dados), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_nome_arquivo(data, "pdf")}"'})


@router.get("/mural.png")
def mural_em_png(request: Request, data: str = Query(..., max_length=10), modalidade: str = Query("TODOS", max_length=15),
                 user: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    dados = svc.mural(db, data, modalidade)
    audit.registrar(db, "EXPORTAR_MURAL_PNG", usuario=user, detalhe=dados["data"], ip=client_ip(request), commit=True)
    return Response(mural_png(dados), media_type="image/png",
                    headers={"Content-Disposition": f'attachment; filename="{_nome_arquivo(data, "png")}"'})


@router.get("/{ag_id}")
def detalhar(ag_id: int, _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    a = _obter(db, ag_id)
    d = agendamento_dict(a)
    d["termino_previsto"] = svc.termino_previsto(db, a)
    return {"ok": True, "agendamento": d}


@router.post("")
def criar(dados: AgendamentoIn, request: Request, user: CurrentUser = Depends(require_roles(*OPERACAO)),
          db: Session = Depends(get_db)):
    a = svc.salvar(db, dados.model_dump(), user.id)
    audit.registrar(db, f"AGENDAMENTO_{a.modalidade}", usuario=user, entidade="agendamento", entidade_id=a.id,
                    detalhe=f"{a.data.isoformat()} {a.hora} {a.box or ''}".strip(), ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": f"Agendamento gravado para {dados.data} às {a.hora} (término previsto {svc.termino_previsto(db, a)}).",
            "agendamento": agendamento_dict(a)}


@router.put("/{ag_id}")
def atualizar(ag_id: int, dados: AgendamentoIn, request: Request, user: CurrentUser = Depends(require_roles(*OPERACAO)),
              db: Session = Depends(get_db)):
    a = svc.salvar(db, dados.model_dump(), user.id, existente=_obter(db, ag_id))
    audit.registrar(db, "ALTERAR_AGENDAMENTO", usuario=user, entidade="agendamento", entidade_id=a.id, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Agendamento atualizado.", "agendamento": agendamento_dict(a)}


@router.delete("/{ag_id}")
def excluir(ag_id: int, request: Request, user: CurrentUser = Depends(require_roles(*OPERACAO)),
            db: Session = Depends(get_db)):
    a = _obter(db, ag_id)
    detalhe = f"{a.modalidade} {a.data.isoformat()} {a.hora}"
    db.delete(a)
    audit.registrar(db, "EXCLUIR_AGENDAMENTO", usuario=user, entidade="agendamento", entidade_id=ag_id,
                    detalhe=detalhe, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Agendamento excluído."}
