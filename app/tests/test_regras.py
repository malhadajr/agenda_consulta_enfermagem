"""Testes das regras de negócio herdadas da versão em planilha."""

from conftest import CPF_A, CPF_B, CPF_C, novo_paciente

from app.services.validators import calculate_end_time, intervals_overlap, validate_cpf


def _ag(s, paciente_id, **kw):
    corpo = {"modalidade": "QT", "data": "10/03/2027", "hora": "08:00", "box": "Box 1", "paciente_id": paciente_id,
             "protocolo": "CDDP+DOXO"}
    corpo.update(kw)
    return s.post("/api/agenda", json=corpo)


def test_cpfs_de_teste_validos():
    for c in (CPF_A, CPF_B, CPF_C):
        assert validate_cpf(c)[0]
    assert not validate_cpf("111.111.111-11")[0]
    assert not validate_cpf("529.982.247-24")[0]


def test_calculos_de_horario():
    assert calculate_end_time("08:00", "04:00") == "12:00"
    assert intervals_overlap(480, 720, 600, 660)
    assert not intervals_overlap(480, 720, 720, 780)


def test_cpf_unico_e_reativacao(enf):
    p = novo_paciente(enf)
    r = enf.post("/api/pacientes", json={"nome_completo": "Outra Pessoa", "cpf": CPF_A})
    assert r.status_code == 409 and r.json()["erro"] == "Paciente já cadastrado com tratamento em andamento"
    assert enf.post(f"/api/pacientes/{p['id']}/encerrar", json={"motivo_encerramento": "CURA"}).status_code == 200
    r = enf.post("/api/pacientes", json={"nome_completo": "Outra Pessoa", "cpf": CPF_A})
    assert r.status_code == 409 and r.json()["code"] == "CPF_EXISTENTE_ENCERRADO"
    r = enf.post(f"/api/pacientes/{p['id']}/reativar", json={"ciclo_tratamento": "Retorno 1º ciclo"})
    assert r.status_code == 200 and r.json()["paciente"]["status"] == "INICIADO"
    assert r.json()["paciente"]["data_retorno"]


def test_prontuario_automatico_7_digitos(enf):
    p = novo_paciente(enf)
    assert len(p["prontuario"]) == 7 and p["prontuario"].isdigit()
    p2 = novo_paciente(enf, nome="Segunda Pessoa", cpf=CPF_B)
    assert int(p2["prontuario"]) == int(p["prontuario"]) + 1


def test_verificar_cpf(enf):
    novo_paciente(enf)
    r = enf.post("/api/pacientes/verificar-cpf", json={"cpf": CPF_A}).json()
    assert r["existe"] and r["acao_sugerida"] == "BLOQUEAR"
    r = enf.post("/api/pacientes/verificar-cpf", json={"cpf": CPF_B}).json()
    assert r["existe"] is False


def test_busca_tolerante(enf):
    novo_paciente(enf, nome="Conceição Araújo Teste")
    r = enf.post("/api/pacientes/busca", json={"q": "conceicao arau"}).json()
    assert r["total"] == 1
    r = enf.post("/api/pacientes/busca", json={"q": "Concesao"}).json()
    assert r["total"] == 1


def test_encerrado_nao_pode_ser_agendado(enf):
    p = novo_paciente(enf)
    enf.post(f"/api/pacientes/{p['id']}/encerrar", json={"motivo_encerramento": "DESISTÊNCIA"})
    assert _ag(enf, p["id"]).status_code == 400
    r = enf.post("/api/pacientes/busca", json={"q": "ficticio"}).json()
    assert r["total"] == 0
    r = enf.post("/api/pacientes/busca", json={"q": "ficticio", "incluir_encerrados": True}).json()
    assert r["total"] == 1


def test_bloqueio_de_box_pela_duracao_do_protocolo(enf):
    a = novo_paciente(enf)
    b = novo_paciente(enf, nome="Segunda Pessoa", cpf=CPF_B)
    assert _ag(enf, a["id"]).status_code == 200  # CDDP+DOXO = 04:00 -> 08:00 às 12:00
    r = _ag(enf, b["id"], hora="10:00")
    assert r.status_code == 409 and r.json()["code"] == "CONFLITO_HORARIO_BOX"
    assert _ag(enf, b["id"], hora="12:00").status_code == 200  # começa quando o anterior termina
    assert _ag(enf, b["id"], hora="08:00", box="Box 2").status_code == 200  # outro Box está livre
    r = _ag(enf, b["id"], hora="13:00", box="Box 3")  # paciente B já ocupa 12:00–16:00 no Box 1
    assert r.status_code == 409 and r.json()["code"] == "CONFLITO_HORARIO_PACIENTE"


def test_falta_libera_vaga(enf):
    a = novo_paciente(enf)
    b = novo_paciente(enf, nome="Segunda Pessoa", cpf=CPF_B)
    r = _ag(enf, a["id"])
    ag_id = r.json()["agendamento"]["id"]
    corpo = {"modalidade": "QT", "data": "10/03/2027", "hora": "08:00", "box": "Box 1", "paciente_id": a["id"],
             "protocolo": "CDDP+DOXO", "compareceu": "N"}
    assert enf.put(f"/api/agenda/{ag_id}", json=corpo).status_code == 200
    assert _ag(enf, b["id"], hora="09:00").status_code == 200


def test_agendamento_cruzado_do_paciente(enf):
    a = novo_paciente(enf)
    assert _ag(enf, a["id"]).status_code == 200
    r = enf.post("/api/agenda", json={"modalidade": "CONSULTA_ENF", "data": "10/03/2027", "hora": "09:00",
                                      "paciente_id": a["id"]})
    assert r.status_code == 409 and r.json()["code"] == "CONFLITO_HORARIO_PACIENTE"


def test_consulta_uma_por_hora_e_expediente(enf):
    a = novo_paciente(enf)
    b = novo_paciente(enf, nome="Segunda Pessoa", cpf=CPF_B)
    base = {"modalidade": "TELECONSULTA", "data": "10/03/2027", "hora": "09:00"}
    assert enf.post("/api/agenda", json={**base, "paciente_id": a["id"]}).status_code == 200
    r = enf.post("/api/agenda", json={**base, "paciente_id": b["id"], "hora": "09:30"})
    assert r.status_code == 409 and r.json()["code"] == "CONFLITO_HORARIO_CONSULTA"
    assert enf.post("/api/agenda", json={**base, "paciente_id": b["id"], "hora": "18:00"}).status_code == 400
    # Consulta de Enfermagem é uma linha independente da Teleconsulta
    assert enf.post("/api/agenda", json={**base, "modalidade": "CONSULTA_ENF", "paciente_id": b["id"]}).status_code == 200


def test_protocolo_e_box_precisam_existir(enf):
    a = novo_paciente(enf)
    assert _ag(enf, a["id"], protocolo="INEXISTENTE").status_code == 400
    assert _ag(enf, a["id"], box="Box 99").status_code == 400


def test_grade_e_mural(enf):
    a = novo_paciente(enf)
    _ag(enf, a["id"])
    d = enf.get("/api/agenda/disponibilidade?data=10/03/2027&box=Box 1&protocolo=CDDP%2BDOXO").json()
    assert len(d["matriz_poltronas"]) == 14  # 12 boxes + consulta + teleconsulta
    livres = {h["hora"]: h["disponivel"] for h in d["horarios"]}
    assert livres["08:00"] is False and livres["12:00"] is True
    m = enf.get("/api/agenda/mural?data=10/03/2027").json()
    assert m["total_quimioterapia"] == 1 and m["itens"][0]["hora"] == "08:00 – 12:00"


def test_intercorrencia_junto_ao_agendamento(enf, admin):
    a = novo_paciente(enf)
    r = _ag(enf, a["id"], intercorrencia="Hipersensibilidade Leve a Moderada", medida_tomada="Suspensa a infusão")
    assert r.status_code == 200
    lista = enf.get("/api/intercorrencias").json()["intercorrencias"]
    assert len(lista) == 1 and lista[0]["protocolo"] == "CDDP+DOXO"


def test_intercorrencia_avulsa_exige_catalogo(enf):
    a = novo_paciente(enf)
    r = enf.post("/api/intercorrencias", json={"data": "10/03/2027", "paciente_id": a["id"], "intercorrencia": "Inventada"})
    assert r.status_code == 400
    r = enf.post("/api/intercorrencias", json={"data": "10/03/2027", "paciente_id": a["id"],
                                               "intercorrencia": "Derramamento Acidental (Spill)"})
    assert r.status_code == 200


def test_estatisticas_diarias(enf, gestor):
    r = enf.put("/api/estatisticas/auditoria", json={"data": "10/03/2027", "valores": {"total_auditados": 10, "validados": 8,
                                                                                     "dose_nao_conforme": 2}})
    assert r.status_code == 200
    r = enf.put("/api/estatisticas/auditoria", json={"data": "10/03/2027", "valores": {"total_auditados": 12, "validados": 9}})
    assert "atualizada" in r.json()["mensagem"]
    assert enf.put("/api/estatisticas/auditoria", json={"data": "11/03/2027", "valores": {"validados": 5}}).status_code == 400
    assert enf.put("/api/estatisticas/agendamento", json={"data": "10/03/2027", "valores": {"primeira_vez": 3}}).status_code == 200
    c = gestor.get("/api/estatisticas/consolidado?ano=2027").json()
    assert c["total_auditados"] == 12 and c["estatistica_agendamento"]["primeira_vez"] == 3
    assert gestor.put("/api/estatisticas/agendamento", json={"data": "10/03/2027", "valores": {}}).status_code == 403


def test_dashboard_e_mapa_de_calor(enf, gestor):
    a = novo_paciente(enf)
    _ag(enf, a["id"], data="10/03/2027", hora_inicio="08:00", hora_termino="13:00", compareceu="S")
    d = gestor.get("/api/relatorios/dashboard?ano=2027&mes=3").json()
    assert d["kpis"]["total_quimioterapia"] == 1 and d["kpis"]["taxa_presenca_pct"] == 100.0
    assert d["tempo_real_protocolos"][0]["status_geral"] == "MUITO DEVAGAR"
    serie = d["serie_mensal"]
    assert len(serie) == 12 and serie[2]["mes_nome"] == "Março"
    assert serie[2]["quimioterapia"] == 1 and serie[2]["presencas"] == 1 and sum(m["total"] for m in serie) == 1
    m = gestor.get("/api/relatorios/mapa-calor?ano=2027&mes=3").json()
    dia = [c for s in m["meses"][0]["semanas"] for c in s if not c["vazio"] and c["dia"] == 10][0]
    assert dia["horas_ocupadas"] == 5.0 and dia["classe_cor"] == "ocioso"


def test_admin_gerencia_protocolos_e_usuarios(admin):
    assert admin.post("/api/protocolos", json={"nome": "NOVO PROTOCOLO", "tempo_estimado": "2:30"}).status_code == 200
    assert admin.post("/api/protocolos", json={"nome": "novo protocolo", "tempo_estimado": "01:00"}).status_code == 409
    assert admin.post("/api/usuarios", json={"usuario": "maria silva", "nome": "Maria Silva", "perfil": "GESTOR"}).status_code == 400
    r = admin.post("/api/usuarios", json={"usuario": "Maria.Silva", "nome": "Maria Silva", "perfil": "GESTOR"})
    assert r.status_code == 200 and r.json()["usuario"]["usuario"] == "maria.silva"  # normalizado para minúsculas
    assert len(r.json()["senha_temporaria"]) >= 12
    assert admin.post("/api/usuarios", json={"usuario": "maria.silva", "nome": "Outra", "perfil": "GESTOR"}).status_code == 409
    uid = r.json()["usuario"]["id"]
    assert admin.post(f"/api/usuarios/{uid}/redefinir-senha").status_code == 200


def test_excluir_agendamento(enf):
    a = novo_paciente(enf)
    ag_id = _ag(enf, a["id"]).json()["agendamento"]["id"]
    assert enf.delete(f"/api/agenda/{ag_id}").status_code == 200
    assert enf.get(f"/api/agenda/{ag_id}").status_code == 404


def test_painel_ao_vivo(enf, gestor):
    from datetime import datetime

    from app import db as dbmod
    from app.services.painel import nome_curto, painel

    a = novo_paciente(enf, nome="Maria da Silva Teste")
    b = novo_paciente(enf, nome="Segunda Pessoa", cpf=CPF_B)
    c = novo_paciente(enf, nome="Terceira Pessoa", cpf=CPF_C)
    _ag(enf, a["id"], data="10/03/2027", hora="08:00", compareceu="S")              # Box 1, 08–12, presente
    _ag(enf, b["id"], data="10/03/2027", hora="08:30", box="Box 2", protocolo="ACTD")  # sem chegada -> atrasado
    _ag(enf, c["id"], data="10/03/2027", hora="11:00", box="Box 3", protocolo="ACTD")  # próximo
    with dbmod.SessionLocal() as db:
        p = painel(db, datetime(2027, 3, 10, 9, 30))
    k = p["kpis"]
    assert k["agendados"] == 3 and k["em_atendimento"] == 1 and k["atrasados"] == 1 and k["presentes"] == 1
    assert k["poltronas_ocupadas_agora"] == 1
    status = {x["box"]: x["status"] for x in p["poltronas"]}
    assert status["Box 1"] == "ocupada" and status["Box 3"] == "livre"
    with dbmod.SessionLocal() as db:
        p2 = painel(db, datetime(2027, 3, 10, 9, 0))  # 30 min após o horário de B, ainda dentro da janela
    assert {x["box"]: x["status"] for x in p2["poltronas"]}["Box 2"] == "aguardando"
    assert p["proximos"][0]["hora"] == "11:00"
    assert p["em_atendimento"][0]["paciente"] == "Maria S. T."  # nome abreviado em telas públicas
    assert nome_curto("Ana") == "Ana"
    assert gestor.get("/api/painel/agora").status_code == 200
    assert enf.get("/api/painel/agora").status_code == 200
