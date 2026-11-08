"""
Comandos de administração (executados dentro do contêiner):

  python -m app.cli criar-admin --usuario admin.ti --nome "Nome Completo"
  python -m app.cli importar-planilha /importacao/planilha.xlsx [--simular]

A importação lê o arquivo .xlsx exportado do Google Sheets antigo ("Nova Agenda 2027")
e grava no banco. O relatório final mostra apenas contagens e números de linha — nunca dados pessoais.
"""

import argparse
import re
import sys
import unicodedata
from datetime import date, datetime, time
from typing import Any, Dict, Optional

from sqlalchemy import func, select

from app import db as dbmod
from app.bootstrap import init_db
from app.models import (
    Agendamento,
    EstatisticaAgendamento,
    EstatisticaAuditoria,
    Intercorrencia,
    Paciente,
    Protocolo,
    TipoIntercorrencia,
    Usuario,
)
from app.security import generate_temp_password, hash_password
from app.services import audit
from app.services.validators import (
    normalize_box_id,
    normalize_cpf,
    normalize_search_text,
    parse_date_br,
    validate_and_format_phone,
    validate_and_format_time_hhmm,
    validate_cpf,
)

# Posições (1-based) das colunas na planilha antiga
PAC = {"ID": 1, "NOME": 2, "CPF": 3, "NASC": 4, "TEL": 5, "EMAIL": 6, "END": 7, "TIPO": 8, "RH": 9, "ABERT": 10,
       "STATUS": 11, "MOTIVO": 12, "DT_ENC": 13, "DT_RET": 14, "CICLO": 15}
QT = {"DATA": 1, "BOX": 2, "HORA": 3, "NOME": 4, "PROT": 5, "TEMPO": 6, "COMP": 7, "INI": 8, "FIM": 9, "ENF": 10, "OBS": 11}
CONS = {"DATA": 1, "HORA": 2, "NOME": 3, "INI": 4, "FIM": 5, "ENF": 6, "COMP": 7, "OBS": 8}
ENF = {"MATRICULA": 1, "CPF": 2, "NOME": 3, "TEL": 5, "EMAIL": 6, "COREN": 8, "PERFIL": 10}
INTER = {"DATA": 3, "PACIENTE": 4, "TIPO": 5, "ENF": 6, "PROT": 7, "MEDIDA": 8, "OBS": 9}
EST_AUD = ["total_auditados", "validados", "exame_incompativel", "dose_nao_conforme",
           "incompatibilidade_evolucao_prescricao", "sem_evolucao_ou_prescricao", "sem_dados_antropometricos",
           "receita_ausente_ou_errada", "encaminhamentos_multiprofissional"]
EST_AGD = ["validados_infusao", "primeira_vez", "retorno_controle", "reagendamentos", "avaliacao_supervisao",
           "avaliacao_enfermeiro", "sem_receita_medica", "sem_exames_laboratoriais", "sem_exames_imagem",
           "encaminhamentos_multiprofissional"]


def _norm_aba(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if not unicodedata.combining(c)).lower())


def _cel(row, pos: int) -> Any:
    return row[pos - 1] if len(row) >= pos else None


def _txt(v: Any, n: int = 200) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()[:n]


def _data(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return parse_date_br(_txt(v, 20)) if v not in (None, "") else None


def _hora(v: Any) -> str:
    if isinstance(v, (time, datetime)):
        return f"{v.hour:02d}:{v.minute:02d}"
    ok, h = validate_and_format_time_hhmm(_txt(v, 10))
    return h if ok else ""


def _int(v: Any) -> int:
    try:
        return max(0, int(float(v or 0)))
    except (TypeError, ValueError):
        return 0


# =============================================================================
# CRIAR ADMINISTRADOR
# =============================================================================

def criar_admin(usuario: str, nome: str) -> int:
    init_db()
    usuario = usuario.strip().lower()
    if not re.match(r"^[a-z0-9._-]{3,60}$", usuario):
        print("Usuário inválido: use 3 a 60 caracteres (letras minúsculas, números, ponto, hífen, sublinhado).")
        return 2
    with dbmod.SessionLocal() as db:
        if db.execute(select(Usuario).where(func.lower(Usuario.usuario) == usuario)).scalar_one_or_none():
            print("Já existe um usuário com este nome. Para redefinir a senha use a tela Usuários e Permissões.")
            return 1
        senha = generate_temp_password()
        u = Usuario(usuario=usuario, nome=nome.strip()[:160] or usuario, perfil="ADMIN",
                    senha_hash=hash_password(senha), trocar_senha=True, ativo=True)
        db.add(u)
        db.flush()
        audit.registrar(db, "CRIAR_ADMIN_CLI", usuario_login="cli", entidade="usuario", entidade_id=u.id)
        db.commit()
    print("=" * 64)
    print(f"Administrador criado: {usuario}")
    print(f"Senha temporária:     {senha}")
    print("Ela será trocada obrigatoriamente no primeiro acesso.")
    print("=" * 64)
    return 0


# =============================================================================
# IMPORTAR PLANILHA ANTIGA
# =============================================================================

def importar_planilha(caminho: str, simular: bool) -> int:
    import openpyxl

    init_db()
    wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    abas = {_norm_aba(ws.title): ws for ws in wb.worksheets}

    def aba(*nomes):
        for n in nomes:
            if _norm_aba(n) in abas:
                return abas[_norm_aba(n)]
        return None

    rel: Dict[str, Any] = {}
    avisos = []
    with dbmod.SessionLocal() as db:
        # ---------- Protocolos
        ws = aba("Protocolos")
        n = 0
        if ws:
            existentes = {p.nome.upper() for p in db.execute(select(Protocolo)).scalars()}
            for row in ws.iter_rows(min_row=2, values_only=True):
                nome = _txt(_cel(row, 1), 160)
                if nome and nome.upper() not in existentes:
                    db.add(Protocolo(nome=nome, tempo_estimado=_hora(_cel(row, 2)) or "01:00"))
                    existentes.add(nome.upper())
                    n += 1
        rel["protocolos_novos"] = n

        # ---------- Catálogo de intercorrências (coluna A)
        ws_int = aba("INTERCORRÊNCIAS", "INTERCORRENCIAS")
        n = 0
        tipos = {t.nome.upper() for t in db.execute(select(TipoIntercorrencia)).scalars()}
        if ws_int:
            for row in ws_int.iter_rows(min_row=1, values_only=True):
                nome = _txt(_cel(row, 1), 200)
                if nome and nome.upper() not in tipos and nome.lower() not in ("catalogo", "catálogo", "tipo"):
                    db.add(TipoIntercorrencia(nome=nome))
                    tipos.add(nome.upper())
                    n += 1
        rel["tipos_intercorrencia_novos"] = n

        # ---------- Enfermeiros -> usuários SEM senha (o admin redefine a senha de cada um)
        ws = aba("Enfermeiros")
        n = 0
        usuarios_por_nome: Dict[str, int] = {
            normalize_search_text(u.nome): u.id for u in db.execute(select(Usuario)).scalars()
        }
        if ws:
            logins = {u.usuario for u in db.execute(select(Usuario)).scalars()}
            cpfs = {u.cpf for u in db.execute(select(Usuario)).scalars() if u.cpf}
            for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                nome = _txt(_cel(row, ENF["NOME"]), 160)
                if not nome or normalize_search_text(nome) in usuarios_por_nome:
                    continue
                partes = normalize_search_text(nome).split()
                base = ".".join([partes[0], partes[-1]]) if len(partes) > 1 else partes[0]
                login, k = base[:55], 2
                while login in logins:
                    login, k = f"{base[:52]}{k}", k + 1
                logins.add(login)
                cpf = normalize_cpf(_txt(_cel(row, ENF["CPF"]), 20))
                cpf = cpf if validate_cpf(cpf)[0] and cpf not in cpfs else None
                if cpf:
                    cpfs.add(cpf)
                ok, tel = validate_and_format_phone(_txt(_cel(row, ENF["TEL"]), 20))
                perfil = "ADMIN" if _txt(_cel(row, ENF["PERFIL"])).upper() == "ADMIN" else "ENFERMEIRO"
                u = Usuario(usuario=login, nome=nome, perfil=perfil, matricula=_txt(_cel(row, ENF["MATRICULA"]), 30) or None,
                            cpf=cpf, coren=_txt(_cel(row, ENF["COREN"]), 30) or None, telefone=tel if ok and tel else None,
                            email=_txt(_cel(row, ENF["EMAIL"]), 160) or None, senha_hash="!", trocar_senha=True, ativo=True)
                db.add(u)
                db.flush()
                usuarios_por_nome[normalize_search_text(nome)] = u.id
                n += 1
        rel["usuarios_importados_sem_senha"] = n

        # ---------- Pacientes
        ws = aba("Pacientes")
        n = n_incomp = 0
        por_nome: Dict[str, int] = {p.nome_busca: p.id for p in db.execute(select(Paciente)).scalars()}
        cpfs_pac = {p.cpf for p in db.execute(select(Paciente)).scalars() if p.cpf}
        pronts = {p.prontuario for p in db.execute(select(Paciente)).scalars() if p.prontuario}
        if ws:
            for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                nome = _txt(_cel(row, PAC["NOME"]), 200)
                if not nome:
                    continue
                cpf = normalize_cpf(_txt(_cel(row, PAC["CPF"]), 20))
                if cpf and cpf in cpfs_pac:
                    avisos.append(f"Pacientes linha {i}: CPF repetido — linha ignorada.")
                    continue
                if cpf and not validate_cpf(cpf)[0]:
                    avisos.append(f"Pacientes linha {i}: CPF inválido — importado sem CPF (cadastro incompleto).")
                    cpf = ""
                pront = _txt(_cel(row, PAC["ID"]), 20)
                if not (pront.isdigit() and len(pront) == 7) or pront in pronts:
                    pront = ""
                status = _txt(_cel(row, PAC["STATUS"])).upper()
                motivo = _txt(_cel(row, PAC["MOTIVO"])).upper().replace("DEISTÊNCIA", "DESISTÊNCIA").replace("DESISTENCIA", "DESISTÊNCIA")
                tipo = _txt(_cel(row, PAC["TIPO"]), 3).upper()
                rh = _txt(_cel(row, PAC["RH"]), 10).capitalize()
                ok, tel = validate_and_format_phone(_txt(_cel(row, PAC["TEL"]), 20))
                p = Paciente(
                    prontuario=pront or None, nome_completo=nome, nome_busca=normalize_search_text(nome), cpf=cpf or None,
                    data_nascimento=_data(_cel(row, PAC["NASC"])), telefone=tel if ok and tel else None,
                    email=_txt(_cel(row, PAC["EMAIL"]), 160) or None, endereco_legado=_txt(_cel(row, PAC["END"]), 500) or None,
                    tipo_sanguineo=tipo if tipo in ("A", "B", "AB", "O") else None,
                    fator_rh=rh if rh in ("Positivo", "Negativo") else None,
                    data_abertura_prontuario=_data(_cel(row, PAC["ABERT"])),
                    status="ENCERRADO" if status == "ENCERRADO" else "INICIADO",
                    motivo_encerramento=motivo if motivo in ("DESISTÊNCIA", "CURA", "MORTE") else None,
                    data_encerramento=_data(_cel(row, PAC["DT_ENC"])), data_retorno=_data(_cel(row, PAC["DT_RET"])),
                    ciclo_tratamento=_txt(_cel(row, PAC["CICLO"]), 160) or None,
                )
                db.add(p)
                db.flush()
                if cpf:
                    cpfs_pac.add(cpf)
                else:
                    n_incomp += 1
                if pront:
                    pronts.add(pront)
                por_nome.setdefault(p.nome_busca, p.id)
                n += 1
        rel["pacientes_importados"] = n
        rel["pacientes_sem_cpf"] = n_incomp

        def paciente_por_nome(nome: str, linha_ref: str) -> Optional[int]:
            chave = normalize_search_text(nome)
            if not chave:
                return None
            if chave not in por_nome:
                p = Paciente(nome_completo=nome[:200], nome_busca=chave, status="INICIADO")
                db.add(p)
                db.flush()
                por_nome[chave] = p.id
                rel["pacientes_criados_pela_agenda"] = rel.get("pacientes_criados_pela_agenda", 0) + 1
                avisos.append(f"{linha_ref}: paciente não estava na aba Pacientes — criado como cadastro incompleto.")
            return por_nome[chave]

        # ---------- Agendas
        for chave_aba, nomes, cols, mod in (
            ("agenda_qt", ("AGENDA 2027",), QT, "QT"),
            ("consulta_enf", ("CONSULTA DE ENFERMAGEM",), CONS, "CONSULTA_ENF"),
            ("teleconsulta", ("TELECONSULTA",), CONS, "TELECONSULTA"),
        ):
            ws = aba(*nomes)
            n = 0
            if ws:
                for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                    nome = _txt(_cel(row, cols["NOME"]), 200)
                    d = _data(_cel(row, cols["DATA"]))
                    hora = _hora(_cel(row, cols["HORA"]))
                    if not nome and not d:
                        continue
                    if not (nome and d and hora):
                        avisos.append(f"{nomes[0]} linha {i}: sem data, hora ou paciente — ignorada.")
                        continue
                    comp = _txt(_cel(row, cols["COMP"]), 1).upper()
                    enf_nome = _txt(_cel(row, cols["ENF"]), 160)
                    a = Agendamento(
                        modalidade=mod, data=d, hora=hora, paciente_id=paciente_por_nome(nome, f"{nomes[0]} linha {i}"),
                        compareceu=comp if comp in ("S", "N") else None,
                        hora_inicio=_hora(_cel(row, cols["INI"])) or None, hora_termino=_hora(_cel(row, cols["FIM"])) or None,
                        enfermeiro_nome=enf_nome or None,
                        enfermeiro_id=usuarios_por_nome.get(normalize_search_text(enf_nome)) if enf_nome else None,
                        observacao=_txt(_cel(row, cols["OBS"]), 1000) or None,
                    )
                    if mod == "QT":
                        box = _txt(_cel(row, cols["BOX"]), 40)
                        nb = normalize_box_id(box)
                        a.box = f"Box {nb[4:]}" if nb.startswith("BOX ") else (box or None)
                        a.protocolo = _txt(_cel(row, cols["PROT"]), 160) or None
                        a.tempo_estimado = _hora(_cel(row, cols["TEMPO"])) or None
                    db.add(a)
                    n += 1
            rel[f"agendamentos_{chave_aba}"] = n

        # ---------- Registros de intercorrências (colunas C:I)
        n = 0
        if ws_int:
            for i, row in enumerate(ws_int.iter_rows(min_row=2, values_only=True), start=2):
                d = _data(_cel(row, INTER["DATA"]))
                nome = _txt(_cel(row, INTER["PACIENTE"]), 200)
                tipo = _txt(_cel(row, INTER["TIPO"]), 200)
                if not (d and nome and tipo):
                    continue
                db.add(Intercorrencia(
                    data=d, paciente_id=paciente_por_nome(nome, f"INTERCORRÊNCIAS linha {i}"), paciente_nome=nome, tipo=tipo,
                    enfermeiro_nome=_txt(_cel(row, INTER["ENF"]), 160) or None, protocolo=_txt(_cel(row, INTER["PROT"]), 160) or None,
                    medida_tomada=_txt(_cel(row, INTER["MEDIDA"]), 1000) or None, observacao=_txt(_cel(row, INTER["OBS"]), 1000) or None,
                ))
                n += 1
        rel["intercorrencias"] = n

        # ---------- Estatísticas
        for chave, nomes, modelo, campos in (
            ("estat_auditoria", ("Estatística Auditoria Clinica P", "Estatística Auditoria Clinica Prévia"), EstatisticaAuditoria, EST_AUD),
            ("estat_agendamento", ("Estatísca agendamento", "Estatística agendamento"), EstatisticaAgendamento, EST_AGD),
        ):
            ws = aba(*nomes)
            n = 0
            if ws:
                datas = {r.data for r in db.execute(select(modelo)).scalars()}
                for row in ws.iter_rows(min_row=2, values_only=True):
                    d = _data(_cel(row, 1))
                    if not d or d in datas:
                        continue
                    db.add(modelo(data=d, **{c: _int(_cel(row, k + 2)) for k, c in enumerate(campos)}))
                    datas.add(d)
                    n += 1
            rel[chave] = n

        audit.registrar(db, "IMPORTAR_PLANILHA", usuario_login="cli", resultado="SIMULADO" if simular else "OK",
                        detalhe=", ".join(f"{k}={v}" for k, v in rel.items())[:300])
        if simular:
            db.rollback()
        else:
            db.commit()

    print("=" * 64)
    print("SIMULAÇÃO — nada foi gravado" if simular else "IMPORTAÇÃO CONCLUÍDA")
    for k, v in rel.items():
        print(f"  {k:36s} {v}")
    if avisos:
        print(f"\nAvisos ({len(avisos)}):")
        for a in avisos[:200]:
            print("  - " + a)
        if len(avisos) > 200:
            print(f"  ... e mais {len(avisos) - 200} avisos")
    print("\nUsuários importados da aba Enfermeiros NÃO têm senha: use 'Redefinir senha' na tela Usuários.")
    print("=" * 64)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli", description="Administração da Nova Agenda 2027")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("criar-admin", help="Cria um administrador com senha temporária")
    a.add_argument("--usuario", required=True)
    a.add_argument("--nome", required=True)
    b = sub.add_parser("importar-planilha", help="Importa o .xlsx exportado do Google Sheets antigo")
    b.add_argument("arquivo")
    b.add_argument("--simular", action="store_true", help="Mostra o resultado sem gravar nada")
    args = ap.parse_args(argv)
    if args.cmd == "criar-admin":
        return criar_admin(args.usuario, args.nome)
    return importar_planilha(args.arquivo, args.simular)


if __name__ == "__main__":
    sys.exit(main())
