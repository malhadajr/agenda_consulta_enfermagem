"""
NOVA AGENDA 2027 — Enfermagem Oncológica
Servidor web para Intranet: agendamento com bloqueio de Box, mural diário, pacientes,
intercorrências, estatísticas, mapa de calor, dashboards e administração de usuários.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.bootstrap import init_db
from app.routers import agenda, auth, cadastros, pacientes, registros, relatorios
from app.services.common import RegraNegocio

BASE_DIR = Path(__file__).resolve().parent
VERSAO = "2.2.0"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("nova_agenda")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info("Nova Agenda 2027 v%s iniciada.", VERSAO)
    yield


app = FastAPI(
    title="Nova Agenda 2027",
    version=VERSAO,
    lifespan=lifespan,
    docs_url=None,       # documentação automática desativada em produção
    redoc_url=None,
    openapi_url=None,
)

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.url.path.startswith("/api/"):
        # Dados de saúde não devem ficar em cache de navegador/proxy
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(RegraNegocio)
async def _regra(_req: Request, exc: RegraNegocio):
    return JSONResponse(status_code=exc.status, content={"ok": False, "code": exc.code, "erro": exc.mensagem, **exc.extra})


@app.exception_handler(StarletteHTTPException)
async def _http(_req: Request, exc: StarletteHTTPException):
    msg = exc.detail if isinstance(exc.detail, str) else "Requisição inválida."
    if exc.status_code == 404 and msg == "Not Found":
        msg = "Recurso não encontrado."
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "erro": msg})


@app.exception_handler(RequestValidationError)
async def _validacao(_req: Request, exc: RequestValidationError):
    campos = sorted({".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()})
    return JSONResponse(status_code=422, content={"ok": False, "erro": "Dados inválidos no formulário.", "campos": campos})


@app.exception_handler(Exception)
async def _erro_interno(_req: Request, exc: Exception):
    # Nunca expõe detalhes internos ao navegador; o erro completo fica apenas no log do servidor
    log.exception("Erro interno não tratado: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"ok": False, "erro": "Erro interno. Tente novamente ou acione o suporte."})


for r in (auth, pacientes, agenda, registros, cadastros, relatorios):
    app.include_router(r.router)


@app.get("/api/saude", include_in_schema=False)
def saude():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE_DIR / "templates" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(BASE_DIR / "static" / "img" / "icone-192.png", media_type="image/png")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(BASE_DIR / "static" / "manifest.webmanifest", media_type="application/manifest+json")
