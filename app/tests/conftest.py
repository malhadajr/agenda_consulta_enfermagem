import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="nova_agenda_test_")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP) / 'teste.db'}"
os.environ["CEP_ONLINE"] = "0"
os.environ["COOKIE_SECURE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app.bootstrap import init_db  # noqa: E402
from app.db import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Usuario  # noqa: E402
from app.security import hash_password, login_ip_limiter  # noqa: E402

SENHAS = {"admin.teste": "AdminForte2027x", "enf.teste": "EnfermeiraBoa77", "gestor.teste": "GestorSeguro99"}
PERFIS = {"admin.teste": "ADMIN", "enf.teste": "ENFERMEIRO", "gestor.teste": "GESTOR"}

# CPFs válidos gerados apenas para teste (não pertencem a ninguém real conhecido)
CPF_A = "529.982.247-25"
CPF_B = "111.444.777-35"
CPF_C = "390.533.447-05"


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(dbmod.engine)
    init_db()
    login_ip_limiter.reset()
    with dbmod.SessionLocal() as db:
        for login, senha in SENHAS.items():
            db.add(Usuario(usuario=login, nome=f"Usuária {login.split('.')[0].title()} Teste", perfil=PERFIS[login],
                           senha_hash=hash_password(senha), trocar_senha=False, ativo=True))
        db.commit()
    yield


def _cliente():
    return TestClient(app, base_url="https://testserver")


class Sessao:
    def __init__(self, login: str):
        self.c = _cliente()
        r = self.c.post("/api/auth/login", json={"usuario": login, "senha": SENHAS[login]})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf"]
        self.user = r.json()["user"]

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def _h(self):
        return {"X-CSRF-Token": self.csrf}

    def post(self, url, json=None):
        return self.c.post(url, json=json, headers=self._h())

    def put(self, url, json=None):
        return self.c.put(url, json=json, headers=self._h())

    def delete(self, url):
        return self.c.delete(url, headers=self._h())


@pytest.fixture
def anon():
    return _cliente()


@pytest.fixture
def admin():
    return Sessao("admin.teste")


@pytest.fixture
def enf():
    return Sessao("enf.teste")


@pytest.fixture
def gestor():
    return Sessao("gestor.teste")


def novo_paciente(s: Sessao, nome="Paciente Ficticio Um", cpf=CPF_A, **extra):
    r = s.post("/api/pacientes", json={"nome_completo": nome, "cpf": cpf, **extra})
    assert r.status_code == 200, r.text
    return r.json()["paciente"]
