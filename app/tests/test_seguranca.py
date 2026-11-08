"""Testes de segurança: autenticação, sessão, CSRF, perfis, bloqueio, cabeçalhos e vazamento de dados."""

from conftest import CPF_A, SENHAS, Sessao, novo_paciente

from app import db as dbmod
from app.models import LogAuditoria, Usuario
from app.security import password_policy_error


ROTAS_PROTEGIDAS = [
    ("get", "/api/metadata"), ("get", "/api/pacientes"), ("post", "/api/pacientes/busca"),
    ("get", "/api/agenda?data=10/03/2027"), ("get", "/api/agenda/mural?data=10/03/2027"),
    ("get", "/api/agenda/mural.pdf?data=10/03/2027"), ("get", "/api/agenda/disponibilidade?data=10/03/2027"),
    ("get", "/api/intercorrencias"), ("get", "/api/relatorios/dashboard"), ("get", "/api/relatorios/mapa-calor?ano=2027"),
    ("get", "/api/usuarios"), ("get", "/api/auditoria"), ("post", "/api/pacientes"), ("post", "/api/agenda"),
    ("get", "/api/protocolos"), ("get", "/api/estatisticas/consolidado"),
]


def test_todas_as_rotas_exigem_login(anon):
    for metodo, url in ROTAS_PROTEGIDAS:
        r = getattr(anon, metodo)(url) if metodo == "get" else anon.post(url, json={})
        assert r.status_code == 401, (url, r.status_code)


def test_saude_publica_e_sem_dados(anon):
    r = anon.get("/api/saude")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_documentacao_automatica_desativada(anon):
    for url in ("/docs", "/redoc", "/openapi.json"):
        assert anon.get(url).status_code == 404


def test_login_errado_mensagem_generica(anon):
    r1 = anon.post("/api/auth/login", json={"usuario": "enf.teste", "senha": "errada123456"})
    r2 = anon.post("/api/auth/login", json={"usuario": "nao.existe", "senha": "errada123456"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["erro"] == r2.json()["erro"]  # não revela se o usuário existe


def test_senhas_antigas_padrao_nao_funcionam(anon):
    assert anon.post("/api/auth/login", json={"usuario": "admin", "senha": "admin"}).status_code == 401


def test_bloqueio_apos_tentativas(anon):
    for _ in range(5):
        anon.post("/api/auth/login", json={"usuario": "enf.teste", "senha": "errada123456"})
    r = anon.post("/api/auth/login", json={"usuario": "enf.teste", "senha": SENHAS["enf.teste"]})
    assert r.status_code == 423  # mesmo com a senha certa a conta fica bloqueada


def test_cookie_de_sessao_seguro(anon):
    r = anon.post("/api/auth/login", json={"usuario": "enf.teste", "senha": SENHAS["enf.teste"]})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "token" not in r.json()  # o token não é entregue ao JavaScript


def test_senha_guardada_com_hash(enf):
    with dbmod.SessionLocal() as db:
        u = db.query(Usuario).filter_by(usuario="enf.teste").one()
        assert u.senha_hash.startswith("$argon2id$")
        assert SENHAS["enf.teste"] not in u.senha_hash


def test_csrf_obrigatorio(enf):
    r = enf.c.post("/api/pacientes", json={"nome_completo": "Teste Csrf", "cpf": CPF_A})
    assert r.status_code == 403
    r = enf.c.post("/api/pacientes", json={"nome_completo": "Teste Csrf", "cpf": CPF_A}, headers={"X-CSRF-Token": "falso"})
    assert r.status_code == 403


def test_logout_invalida_sessao(enf):
    assert enf.post("/api/auth/logout").status_code == 200
    assert enf.get("/api/metadata").status_code == 401


def test_cookie_forjado_rejeitado(anon):
    anon.cookies.set("na_sessao", "a" * 43, domain="testserver")
    assert anon.get("/api/metadata").status_code == 401


def test_permissoes_enfermeiro(enf):
    assert enf.get("/api/relatorios/dashboard").status_code == 200  # liberado para a enfermagem
    assert enf.get("/api/relatorios/mapa-calor?ano=2027").status_code == 200
    assert enf.user["permissoes"]["dashboards"] and enf.user["permissoes"]["mapa_calor"]
    assert enf.get("/api/usuarios").status_code == 403
    assert enf.get("/api/auditoria").status_code == 403
    assert enf.post("/api/protocolos", json={"nome": "X", "tempo_estimado": "01:00"}).status_code == 403


def test_permissoes_gestor_somente_leitura(gestor):
    assert gestor.get("/api/relatorios/dashboard").status_code == 200
    assert gestor.get("/api/relatorios/mapa-calor?ano=2027").status_code == 200
    assert gestor.post("/api/pacientes", json={"nome_completo": "Teste Gestor", "cpf": CPF_A}).status_code == 403
    assert gestor.post("/api/agenda", json={"data": "10/03/2027", "hora": "08:00", "paciente_id": 1}).status_code == 403
    assert gestor.get("/api/usuarios").status_code == 403


def test_troca_de_senha_obrigatoria(admin, anon):
    r = admin.post("/api/usuarios", json={"usuario": "nova.enf", "nome": "Nova Enfermeira Teste", "perfil": "ENFERMEIRO"})
    temp = r.json()["senha_temporaria"]
    s = anon
    r = s.post("/api/auth/login", json={"usuario": "nova.enf", "senha": temp})
    assert r.status_code == 200 and r.json()["user"]["trocar_senha"] is True
    csrf = r.json()["csrf"]
    assert s.get("/api/metadata").status_code == 403  # bloqueado até trocar
    r = s.post("/api/auth/trocar-senha", json={"senha_atual": temp, "nova_senha": "curta"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400
    r = s.post("/api/auth/trocar-senha", json={"senha_atual": temp, "nova_senha": "CavaloAzul2027x"},
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert s.get("/api/metadata").status_code == 200


def test_politica_de_senha():
    assert password_policy_error("admin") is not None
    assert password_policy_error("somenteletrasaqui") is not None
    assert password_policy_error("Maria2027forte", nome="Maria Souza") is not None
    assert password_policy_error("x52998224725y", cpf="52998224725") is not None
    assert password_policy_error("CavaloAzul2027") is None


def test_nao_remove_ultimo_admin(admin):
    uid = admin.user["id"]
    r = admin.put(f"/api/usuarios/{uid}", json={"usuario": "admin.teste", "nome": "Admin", "perfil": "ENFERMEIRO"})
    assert r.status_code == 400


def test_cabecalhos_de_seguranca(anon):
    r = anon.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    api = anon.get("/api/saude")
    assert api.headers["cache-control"] == "no-store"


def test_erro_interno_nao_vaza_detalhes(admin):
    r = admin.get("/api/agenda/disponibilidade?data=99/99/9999")
    assert r.status_code == 400
    assert "Traceback" not in r.text and "sqlalchemy" not in r.text.lower()


def test_busca_paciente_minimiza_dados(enf):
    novo_paciente(enf, telefone="21987654321")
    r = enf.post("/api/pacientes/busca", json={"q": "ficticio"})
    p = r.json()["pacientes"][0]
    assert "telefone" not in p and "cpf" not in p
    assert p["cpf_mascarado"].startswith("***")


def test_log_de_auditoria_sem_dados_pessoais(enf, admin):
    novo_paciente(enf)
    with dbmod.SessionLocal() as db:
        textos = " ".join(f"{e.acao} {e.detalhe or ''} {e.entidade_id or ''}" for e in db.query(LogAuditoria).all())
    assert "CADASTRO_PACIENTE" in textos
    assert "52998224725" not in textos and "Ficticio" not in textos
    r = admin.get("/api/auditoria")
    assert r.status_code == 200 and r.json()["total"] > 0


def test_visualizacao_de_paciente_e_auditada(enf, admin):
    p = novo_paciente(enf)
    enf.get(f"/api/pacientes/{p['id']}")
    acoes = [e["acao"] for e in admin.get("/api/auditoria").json()["eventos"]]
    assert "VISUALIZAR_PACIENTE" in acoes


def test_pdf_escapa_marcacao(enf):
    p = novo_paciente(enf, nome="Paciente <b>Negrito</b> & Cia")
    enf.post("/api/agenda", json={"modalidade": "QT", "data": "10/03/2027", "hora": "08:00", "box": "Box 1",
                                  "paciente_id": p["id"], "protocolo": "ACTD"})
    r = enf.get("/api/agenda/mural.pdf?data=10/03/2027")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r = enf.get("/api/agenda/mural.png?data=10/03/2027")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"


def test_sessao_expira_por_inatividade(enf):
    from datetime import datetime, timedelta

    from app.models import Sessao as SessaoModel

    with dbmod.SessionLocal() as db:
        for s in db.query(SessaoModel).all():
            s.ultimo_acesso = datetime.now() - timedelta(hours=2)
        db.commit()
    assert enf.get("/api/metadata").status_code == 401


def test_usuario_desativado_perde_acesso(admin):
    novo = Sessao("enf.teste")
    with dbmod.SessionLocal() as db:
        uid = db.query(Usuario).filter_by(usuario="enf.teste").one().id
    r = admin.put(f"/api/usuarios/{uid}", json={"usuario": "enf.teste", "nome": "Enf", "perfil": "ENFERMEIRO", "ativo": False})
    assert r.status_code == 200
    assert novo.get("/api/metadata").status_code == 401


def test_atualizacao_automatica_nao_renova_sessao(enf, anon):
    from datetime import datetime, timedelta

    from app.models import Sessao as SessaoModel

    antigo = datetime.now() - timedelta(minutes=10)
    with dbmod.SessionLocal() as db:
        for s in db.query(SessaoModel).all():
            s.ultimo_acesso = antigo
        db.commit()
    assert enf.get("/api/painel/agora", headers={"X-Auto-Refresh": "1"}).status_code == 200
    with dbmod.SessionLocal() as db:
        assert all(s.ultimo_acesso == antigo for s in db.query(SessaoModel).all())
    assert anon.get("/api/painel/agora").status_code == 401
