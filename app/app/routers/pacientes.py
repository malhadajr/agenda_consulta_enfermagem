"""Endpoints de pacientes. Busca e verificação de CPF usam POST para não expor dados pessoais em URLs/logs."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import LEITURA, OPERACAO, CurrentUser, client_ip, require_roles
from app.services import audit
from app.services import pacientes as svc
from app.services.common import paciente_completo

router = APIRouter(prefix="/api/pacientes", tags=["pacientes"])


class BuscaIn(BaseModel):
    q: str = Field(default="", max_length=100)
    incluir_encerrados: bool = False
    limite: int = Field(default=20, ge=1, le=50)


class CpfIn(BaseModel):
    cpf: str = Field(max_length=20)


class PacienteIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prontuario: Optional[str] = Field(default="", max_length=20)
    nome_completo: str = Field(max_length=200)
    cpf: str = Field(max_length=20)
    data_nascimento: Optional[str] = Field(default="", max_length=10)
    telefone: Optional[str] = Field(default="", max_length=20)
    email: Optional[str] = Field(default="", max_length=160)
    cep: Optional[str] = Field(default="", max_length=10)
    logradouro: Optional[str] = Field(default="", max_length=200)
    numero: Optional[str] = Field(default="", max_length=20)
    complemento: Optional[str] = Field(default="", max_length=120)
    bairro: Optional[str] = Field(default="", max_length=120)
    cidade: Optional[str] = Field(default="", max_length=120)
    uf: Optional[str] = Field(default="", max_length=2)
    tipo_sanguineo: Optional[str] = Field(default="", max_length=3)
    fator_rh: Optional[str] = Field(default="", max_length=10)
    data_abertura_prontuario: Optional[str] = Field(default="", max_length=10)
    ciclo_tratamento: Optional[str] = Field(default="", max_length=160)


class EncerrarIn(BaseModel):
    motivo_encerramento: str = Field(max_length=20)
    data_encerramento: Optional[str] = Field(default="", max_length=10)


class ReativarIn(BaseModel):
    ciclo_tratamento: str = Field(max_length=160)
    data_retorno: Optional[str] = Field(default="", max_length=10)


@router.post("/busca")
def buscar(dados: BuscaIn, _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    res = svc.buscar(db, dados.q, dados.incluir_encerrados, dados.limite)
    return {"ok": True, "total": len(res), "pacientes": res}


@router.post("/verificar-cpf")
def verificar_cpf(dados: CpfIn, _u: CurrentUser = Depends(require_roles(*OPERACAO)), db: Session = Depends(get_db)):
    return svc.verificar_cpf(db, dados.cpf)


@router.get("")
def listar(status: str = Query("", max_length=12), offset: int = Query(0, ge=0), limite: int = Query(50, ge=1, le=200),
           _u: CurrentUser = Depends(require_roles(*LEITURA)), db: Session = Depends(get_db)):
    return {"ok": True, **svc.listar(db, status, limite, offset), "contagens": svc.contagens(db)}


@router.get("/{paciente_id}")
def detalhar(paciente_id: int, request: Request, user: CurrentUser = Depends(require_roles(*LEITURA)),
             db: Session = Depends(get_db)):
    p = svc.obter(db, paciente_id)
    audit.registrar(db, "VISUALIZAR_PACIENTE", usuario=user, entidade="paciente", entidade_id=p.id,
                    ip=client_ip(request), commit=True)
    return {"ok": True, "paciente": paciente_completo(p)}


@router.post("")
def criar(dados: PacienteIn, request: Request, user: CurrentUser = Depends(require_roles(*OPERACAO)),
          db: Session = Depends(get_db)):
    p = svc.criar(db, dados.model_dump())
    audit.registrar(db, "CADASTRO_PACIENTE", usuario=user, entidade="paciente", entidade_id=p.id, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": f"Paciente cadastrado(a) com sucesso (prontuário {p.prontuario}).",
            "paciente": paciente_completo(p)}


@router.put("/{paciente_id}")
def atualizar(paciente_id: int, dados: PacienteIn, request: Request,
              user: CurrentUser = Depends(require_roles(*OPERACAO)), db: Session = Depends(get_db)):
    p = svc.atualizar(db, paciente_id, dados.model_dump())
    audit.registrar(db, "ATUALIZAR_PACIENTE", usuario=user, entidade="paciente", entidade_id=p.id, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Cadastro atualizado com sucesso.", "paciente": paciente_completo(p)}


@router.post("/{paciente_id}/encerrar")
def encerrar(paciente_id: int, dados: EncerrarIn, request: Request,
             user: CurrentUser = Depends(require_roles(*OPERACAO)), db: Session = Depends(get_db)):
    p = svc.encerrar(db, paciente_id, dados.motivo_encerramento, dados.data_encerramento or "")
    audit.registrar(db, "ENCERRAR_TRATAMENTO", usuario=user, entidade="paciente", entidade_id=p.id,
                    detalhe=f"motivo={p.motivo_encerramento}", ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Tratamento alterado para ENCERRADO.", "paciente": paciente_completo(p)}


@router.post("/{paciente_id}/reativar")
def reativar(paciente_id: int, dados: ReativarIn, request: Request,
             user: CurrentUser = Depends(require_roles(*OPERACAO)), db: Session = Depends(get_db)):
    p = svc.reativar(db, paciente_id, dados.ciclo_tratamento, dados.data_retorno or "")
    audit.registrar(db, "REATIVAR_TRATAMENTO", usuario=user, entidade="paciente", entidade_id=p.id, ip=client_ip(request))
    db.commit()
    return {"ok": True, "mensagem": "Tratamento REATIVADO sem duplicar o CPF.", "paciente": paciente_completo(p)}
