// =====================================================================
// NOVA AGENDA 2027 — aplicação (uma página, abas por #hash)
// =====================================================================
import {
  $, $$, api, abrirModal, autocompletarPaciente, baixar, brParaIso, confirmar, configurarApi, debounce,
  enviando, erroToast, estado, fecharModal, fmtNum, html, isoHoje, isoParaBr, lerForm, mascaraCep,
  mascaraCpf, mascaraTelefone, mesAtual, preencherForm, qs, raw, setHTML, somarDias, toast,
} from "./core.js?v=2.1.1";

const MOD_LABEL = { QT: "Quimioterapia", CONSULTA_ENF: "Consulta de Enfermagem", TELECONSULTA: "Teleconsulta" };
const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
const pode = (p) => !!estado.user?.permissoes?.[p];

// =====================================================================
// SESSÃO
// =====================================================================
configurarApi({
  sessaoPerdida: () => mostrarLogin("Sua sessão expirou. Entre novamente."),
  trocaObrigatoria: () => abrirTrocaSenha(true),
});

function mostrarLogin(msg = "") {
  estado.user = null;
  estado.csrf = "";
  fecharModal();
  $("#app").hidden = true;
  $("#tela-login").hidden = false;
  $("#login-erro").textContent = msg;
  $("#form-login [name=senha]").value = "";
  $("#form-login [name=usuario]").focus();
}

$("#form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.currentTarget;
  const dados = lerForm(f);
  $("#login-erro").textContent = "";
  if (!dados.usuario || !dados.senha) { $("#login-erro").textContent = "Informe usuário e senha."; return; }
  await enviando(f.querySelector("button"), async () => {
    try {
      const r = await api("POST", "/api/auth/login", dados);
      f.reset();
      iniciarSessao(r);
    } catch (e) { $("#login-erro").textContent = e.message; }
  });
});

function iniciarSessao(r) {
  estado.csrf = r.csrf;
  estado.user = r.user;
  $("#tela-login").hidden = true;
  $("#app").hidden = false;
  $("#user-nome").textContent = r.user.nome;
  $("#user-perfil").textContent = r.user.perfil;
  $$("[data-perm]").forEach((el) => { el.hidden = !pode(el.dataset.perm); });
  if (r.user.trocar_senha) { abrirTrocaSenha(true); return; }
  carregarMetadata().then(() => irPara(location.hash.slice(1) || "painel"));
}

async function logout() {
  try { await api("POST", "/api/auth/logout"); } catch { /* ignora */ }
  mostrarLogin("Você saiu do sistema.");
}

function abrirTrocaSenha(obrigatoria = false) {
  const body = abrirModal(obrigatoria ? "Defina sua nova senha" : "Trocar senha", html`
    ${obrigatoria ? html`<p class="aviso">Por segurança, troque a senha temporária antes de continuar.</p>` : ""}
    <form class="form" id="form-senha" novalidate>
      <label>Senha atual <input type="password" name="senha_atual" autocomplete="current-password" required maxlength="128"></label>
      <label>Nova senha <input type="password" name="nova_senha" autocomplete="new-password" required maxlength="128"></label>
      <label>Repita a nova senha <input type="password" name="confirma" autocomplete="new-password" required maxlength="128"></label>
      <p class="muted small">Mínimo de 10 caracteres, com letras e números. Não use seu nome, usuário ou CPF.</p>
      <p class="form-erro" id="senha-erro"></p>
      <div class="form-acoes">
        ${obrigatoria ? html`<button type="button" class="btn btn-ghost" data-action="logout">Sair</button>` : ""}
        <button class="btn btn-primary" type="submit">Salvar nova senha</button>
      </div>
    </form>`);
  if (obrigatoria) $("#modal [data-action=fechar-modal]").hidden = true;
  body.querySelector("#form-senha").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const d = lerForm(ev.currentTarget);
    if (d.nova_senha !== d.confirma) { $("#senha-erro").textContent = "As senhas não conferem."; return; }
    try {
      await api("POST", "/api/auth/trocar-senha", { senha_atual: d.senha_atual, nova_senha: d.nova_senha });
      $("#modal [data-action=fechar-modal]").hidden = false;
      fecharModal();
      toast("Senha alterada com sucesso.", "ok");
      const me = await api("GET", "/api/auth/me");
      iniciarSessao(me);
    } catch (e) { $("#senha-erro").textContent = e.message; }
  });
}

// =====================================================================
// NAVEGAÇÃO
// =====================================================================
const ABAS = {
  painel: () => Painel.carregar(),
  agenda: () => Agenda.carregar(), mural: () => Mural.carregar(), pacientes: () => Pacientes.carregar(),
  intercorrencias: () => Intercorrencias.carregar(), estatisticas: () => Estatisticas.carregar(),
  mapa: () => Mapa.carregar(), dashboards: () => Dashboards.carregar(), protocolos: () => Protocolos.carregar(),
  usuarios: () => Usuarios.carregar(), auditoria: () => Auditoria.carregar(),
};
const PERM_ABA = { mapa: "mapa_calor", dashboards: "dashboards", usuarios: "usuarios", auditoria: "log_auditoria" };

function irPara(aba) {
  if (!ABAS[aba] || (PERM_ABA[aba] && !pode(PERM_ABA[aba]))) aba = "agenda";
  if (aba !== "painel") Painel.parar();
  $$(".aba").forEach((s) => s.classList.toggle("ativa", s.id === `aba-${aba}`));
  $$("[data-tab]").forEach((a) => a.classList.toggle("ativo", a.dataset.tab === aba));
  $("#titulo-aba").textContent = $(`#aba-${aba}`).dataset.titulo;
  document.title = `${$(`#aba-${aba}`).dataset.titulo} — Nova Agenda 2027`;
  document.body.classList.remove("menu-aberto");
  if (location.hash.slice(1) !== aba) history.replaceState(null, "", `#${aba}`);
  ABAS[aba]().catch?.(erroToast);
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => estado.user && irPara(location.hash.slice(1)));

// Ações globais por delegação (não há onclick inline — exigência da CSP)
const ACOES = {
  "abrir-menu": () => document.body.classList.add("menu-aberto"),
  "fechar-menu": () => document.body.classList.remove("menu-aberto"),
  "fechar-modal": () => fecharModal(),
  logout: () => logout(),
  "trocar-senha": () => abrirTrocaSenha(false),
};
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-action]");
  if (!el) return;
  const fn = ACOES[el.dataset.action];
  if (fn) { ev.preventDefault(); fn(el, ev); }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("#modal").hidden && !$("#modal [data-action=fechar-modal]").hidden) fecharModal();
});

// =====================================================================
// METADADOS (listas para os formulários)
// =====================================================================
async function carregarMetadata() {
  estado.meta = await api("GET", "/api/metadata");
  const c = estado.meta.contagens;
  $("#cnt-ativos").textContent = c.ativos;
  $("#cnt-encerrados").textContent = c.encerrados;
  preencherSelects(document);
}

function opcoes(tipo) {
  const m = estado.meta;
  switch (tipo) {
    case "protocolos": return html`<option value="">Selecione…</option>${m.protocolos.map((p) => html`<option value="${p.protocolo}">${p.protocolo} (${p.tempo_estimado})</option>`)}`;
    case "protocolos-opcional": return html`<option value="">—</option>${m.protocolos.map((p) => html`<option value="${p.protocolo}">${p.protocolo}</option>`)}`;
    case "intercorrencias": return html`<option value="">Selecione…</option>${m.intercorrencias.map((t) => html`<option>${t}</option>`)}`;
    case "enfermeiros": return html`<option value="">—</option>${m.enfermeiros.map((e) => html`<option value="${e.id}">${e.nome}${e.coren ? ` (COREN ${e.coren})` : ""}</option>`)}`;
    case "boxes": return html`${m.listas.boxes.map((b) => html`<option>${b}</option>`)}`;
    case "ufs": return html`<option value="">UF</option>${m.listas.ufs.map((u) => html`<option>${u}</option>`)}`;
    case "tipos-sanguineos": return html`<option value="">—</option>${m.listas.tipos_sanguineos.map((u) => html`<option>${u}</option>`)}`;
    case "fatores-rh": return html`<option value="">—</option>${m.listas.fatores_rh.map((u) => html`<option>${u}</option>`)}`;
    case "motivos": return html`${m.listas.motivos_encerramento.map((u) => html`<option>${u}</option>`)}`;
    case "perfis": return html`${m.listas.perfis.map((u) => html`<option>${u}</option>`)}`;
    default: return html``;
  }
}
function preencherSelects(root) {
  $$("select[data-fill]", root).forEach((s) => { const v = s.value; setHTML(s, opcoes(s.dataset.fill)); if (v) s.value = v; });
}

const vazio = (msg) => html`<div class="vazio">${msg}</div>`;
function barras(itens, rotulo, valor, sufixo = "") {
  if (!itens.length) return vazio("Sem dados no período.");
  const max = Math.max(...itens.map(valor), 1);
  return html`<div class="barras">${itens.map((i) => html`
    <div class="barra" title="${rotulo(i)}: ${fmtNum(valor(i))}${sufixo}">
      <span class="barra-rotulo">${rotulo(i)}</span>
      <span class="barra-trilho"><span class="barra-valor" data-pct="${(valor(i) / max) * 100}"></span></span>
      <span class="barra-num">${fmtNum(valor(i))}${sufixo}</span>
    </div>`)}</div>`;
}
const tagCompareceu = (c) => (c === "S" ? html`<span class="tag tag-ok">✓ Compareceu</span>`
  : c === "N" ? html`<span class="tag tag-erro">✗ Falta</span>` : html`<span class="tag">Agendado</span>`);

// =====================================================================
// PAINEL AO VIVO (atualiza sozinho a cada 30 s enquanto a aba estiver aberta e visível)
// =====================================================================
const Painel = {
  timer: null,
  inicializado: false,
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    Object.assign(ACOES, {
      "painel-atualizar": () => this.carregar(),
      "painel-tela-cheia": () => this.telaCheia(),
    });
    document.addEventListener("visibilitychange", () => {
      if (location.hash !== "#painel") return;
      if (document.hidden) this.parar(); else this.carregar();
    });
    document.addEventListener("fullscreenchange", () => {
      if (!document.fullscreenElement) document.body.classList.remove("modo-tv");
    });
  },
  parar() {
    clearTimeout(this.timer);
    this.timer = null;
    $(".pulso")?.classList.add("parado");
  },
  telaCheia() {
    if (document.fullscreenElement) { document.exitFullscreen(); return; }
    document.body.classList.add("modo-tv");
    document.documentElement.requestFullscreen?.().catch(() => {});
  },
  async carregar(automatico = false) {
    this.init();
    clearTimeout(this.timer);
    let d;
    try {
      d = await api("GET", "/api/painel/agora", undefined, automatico ? { "X-Auto-Refresh": "1" } : {});
    } catch (e) {
      $(".pulso")?.classList.add("parado");
      if (e.status !== 401) this.timer = setTimeout(() => this.carregar(true), 30000);
      return;
    }
    if (location.hash === "#painel" && !document.hidden) this.timer = setTimeout(() => this.carregar(true), 30000);
    $(".pulso")?.classList.remove("parado");
    $("#painel-dia").textContent = `${d.dia_semana}, ${d.data}`;
    $("#painel-hora").textContent = d.atualizado_em;
    const k = d.kpis;
    setHTML("painel-kpis", html`
      <div class="kpi destaque"><small>Poltronas em uso agora</small><strong>${k.poltronas_ocupadas_agora} / ${k.poltronas_total}</strong><span>ocupação do dia ${fmtNum(k.ocupacao_dia_pct)}%</span></div>
      <div class="kpi"><small>Agendados hoje</small><strong>${k.agendados}</strong><span>${fmtNum(k.horas_ocupadas)}h de ${k.capacidade_horas}h de poltrona</span></div>
      <div class="kpi"><small>Em atendimento</small><strong>${k.em_atendimento}</strong><span>${k.concluidos} concluído(s)</span></div>
      <div class="kpi"><small>Presentes</small><strong>${k.presentes}</strong><span>${k.taxa_presenca_pct === null ? "—" : `${fmtNum(k.taxa_presenca_pct)}% de presença`}</span></div>
      <div class="kpi"><small>Aguardando chegada</small><strong>${k.aguardando}</strong><span>${k.faltas} falta(s)</span></div>
      <div class="kpi ${k.atrasados ? "alerta" : ""}"><small>Atrasados</small><strong>${k.atrasados}</strong><span>${k.intercorrencias_hoje} intercorrência(s) hoje</span></div>`);
    const rotulo = { livre: "Livre", ocupada: "Em infusão", aguardando: "Aguardando" };
    setHTML("painel-poltronas", html`${d.poltronas.map((p) => html`
      <div class="poltrona pl-${p.status}" title="${p.box}: ${rotulo[p.status]}${p.paciente ? ` — ${p.paciente}` : ""}">
        <b>${p.box}</b><span class="estado">${rotulo[p.status]}</span>
        ${p.paciente ? html`<span class="pac">${p.paciente}</span><span>até ${p.fim}</span>` : ""}
        ${p.status === "ocupada" ? html`<span class="progresso"><span data-pct="${p.progresso_pct}"></span></span>` : ""}
      </div>`)}`);
    const max = Math.max(d.kpis.poltronas_total, 1);
    setHTML("painel-horas", html`${d.ocupacao_por_hora.map((h) => html`
      <div class="coluna ${h.agora ? "agora" : ""}" title="${h.hora}: ${h.poltronas} de ${max} poltronas">
        <span class="coluna-num">${h.poltronas}</span>
        <span class="coluna-barra"><span data-pcth="${(h.poltronas / max) * 100}"></span></span>
        <span>${h.agora ? "agora" : h.hora.slice(0, 2) + "h"}</span>
      </div>`)}`);
    const mini = (i, detalhe, alerta = false) => html`<div class="mini ${alerta ? "alerta" : ""}">
      <span class="t">${i.hora}</span><b>${i.paciente}</b><span class="d">${i.local} • ${i.protocolo || i.modalidade}${detalhe ? ` • ${detalhe}` : ""}</span></div>`;
    setHTML("painel-atendimento", d.em_atendimento.length
      ? html`${d.em_atendimento.map((i) => mini(i, `termina ${i.fim} (${i.restante_min} min)`))}` : vazio("Ninguém em atendimento agora."));
    setHTML("painel-proximos", d.proximos.length
      ? html`${d.proximos.map((i) => mini(i, i.em_min > 0 ? `em ${i.em_min} min` : "agora"))}` : vazio("Sem próximos atendimentos hoje."));
    setHTML("painel-atrasados", d.atrasados.length
      ? html`${d.atrasados.map((i) => mini(i, `${i.atraso_min} min de atraso`, true))}` : vazio("Nenhum atraso. 👍"));
  },
};

// =====================================================================
// AGENDA DO DIA
// =====================================================================
const Agenda = {
  inicializado: false,
  dados: null,
  itens: [],

  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    $("#agenda-data").value = isoHoje();
    $("#agenda-data").addEventListener("change", () => this.carregar());
    $("#agenda-filtro-mod").addEventListener("change", () => this.renderLista());
    Object.assign(ACOES, {
      "dia-anterior": () => { $("#agenda-data").value = somarDias($("#agenda-data").value || isoHoje(), -1); this.carregar(); },
      "dia-seguinte": () => { $("#agenda-data").value = somarDias($("#agenda-data").value || isoHoje(), 1); this.carregar(); },
      hoje: () => { $("#agenda-data").value = isoHoje(); this.carregar(); },
      "novo-agendamento": () => FormAgendamento.abrir({ data: $("#agenda-data").value }),
      "slot-livre": (el) => pode("agenda_editar") && FormAgendamento.abrir({
        data: $("#agenda-data").value, modalidade: el.dataset.mod, box: el.dataset.box, hora: el.dataset.hora }),
      "abrir-ag": (el) => FormAgendamento.editar(Number(el.dataset.id)),
      "ag-presenca": (el) => this.presenca(Number(el.dataset.id), el.dataset.valor),
      "ag-excluir": (el) => this.excluir(Number(el.dataset.id)),
    });
  },

  async carregar() {
    this.init();
    const data = $("#agenda-data").value || isoHoje();
    const [disp, lista] = await Promise.all([
      api("GET", `/api/agenda/disponibilidade?${qs({ data })}`),
      api("GET", `/api/agenda?${qs({ data })}`),
    ]);
    this.dados = disp;
    this.itens = lista.agendamentos;
    $("#agenda-dia-semana").textContent = disp.dia_semana;
    const r = disp.resumo_dia;
    setHTML("agenda-resumo", html`
      <div class="kpi destaque"><small>Atendimentos no dia</small><strong>${this.itens.length}</strong><span>${disp.dia_semana}</span></div>
      <div class="kpi"><small>Horas de poltrona ocupadas</small><strong>${fmtNum(r.horas_ocupadas_dia)}h</strong><span>de ${r.capacidade_horas_dia}h</span></div>
      <div class="kpi"><small>Horas ociosas</small><strong>${fmtNum(r.horas_ociosas_dia)}h</strong><span>${r.cadeiras_100_ociosas} poltrona(s) sem uso</span></div>
      <div class="kpi"><small>Consultas / Teleconsultas</small><strong>${r.consultas_enf_dia} / ${r.teleconsultas_dia}</strong><span>1 h cada</span></div>`);
    this.renderGrade();
    this.renderLista();
  },

  renderGrade() {
    const d = this.dados;
    const faixas = d.faixas;
    const linhas = d.matriz_poltronas.map((linha) => {
      const mod = linha.tipo_linha === "BOX_QT" ? "QT" : linha.tipo_linha;
      let anterior = null;
      const celulas = faixas.map((faixa) => {
        const c = linha.faixas.find((f) => f.faixa === faixa);
        if (!c) return html`<td></td>`;
        if (!c.ocupado) {
          anterior = null;
          return html`<td><button type="button" class="slot slot-livre" data-action="slot-livre" data-mod="${mod}"
            data-box="${mod === "QT" ? linha.box : ""}" data-hora="${faixa}" title="${linha.box} ${faixa}: livre"
            ${pode("agenda_editar") ? "" : raw("disabled")}>${faixa}</button></td>`;
        }
        const continua = anterior === c.agendamento_id;
        anterior = c.agendamento_id;
        const classe = mod === "QT" ? "slot-ocupado" : "slot-consulta";
        return html`<td><button type="button" class="slot ${classe} ${continua ? "cont" : ""}" data-action="abrir-ag"
          data-id="${c.agendamento_id}" title="${c.paciente} • ${c.protocolo} • ${c.janela}">
          ${continua ? "↳" : html`<b>${c.paciente}</b>${c.janela}`}</button></td>`;
      });
      const sep = linha.tipo_linha === "CONSULTA_ENF" ? "sep" : "";
      return html`<tr class="${sep}"><th class="linha" scope="row">${linha.box}<small>${fmtNum(linha.horas_ocupadas)}h ocupadas</small></th>${celulas}</tr>`;
    });
    setHTML("grade", html`<thead><tr><th class="linha">Poltrona</th>${faixas.map((f) => html`<th>${f}</th>`)}</tr></thead><tbody>${linhas}</tbody>`);
  },

  renderLista() {
    const filtro = $("#agenda-filtro-mod").value;
    const itens = this.itens.filter((a) => !filtro || a.modalidade === filtro)
      .sort((a, b) => (a.hora > b.hora ? 1 : -1));
    const editar = pode("agenda_editar");
    setHTML("agenda-lista", itens.length ? html`${itens.map((a) => html`
      <div class="item">
        <div class="item-hora">${a.janela}<small>${a.box}</small></div>
        <div class="item-corpo">
          <b>${a.nome_paciente}</b>
          <span>${a.modalidade_label}${a.protocolo ? ` • ${a.protocolo}` : ""}${a.enfermeira ? ` • ${a.enfermeira}` : ""}</span>
          <div>${tagCompareceu(a.compareceu)}</div>
        </div>
        <div class="item-acoes">
          ${editar ? html`
            <button type="button" class="btn btn-sm btn-ghost" data-action="ag-presenca" data-id="${a.id}" data-valor="S" title="Marcar presença">✓ Veio</button>
            <button type="button" class="btn btn-sm btn-ghost" data-action="ag-presenca" data-id="${a.id}" data-valor="N" title="Marcar falta">✗ Faltou</button>` : ""}
          <button type="button" class="btn btn-sm btn-ghost" data-action="abrir-ag" data-id="${a.id}">${editar ? "Editar" : "Ver"}</button>
          ${editar ? html`<button type="button" class="btn btn-sm btn-ghost" data-action="ag-excluir" data-id="${a.id}" aria-label="Excluir">🗑️</button>` : ""}
        </div>
      </div>`)}` : vazio("Nenhum atendimento agendado para este dia."));
  },

  async presenca(id, valor) {
    try {
      const { agendamento: a } = await api("GET", `/api/agenda/${id}`);
      const novo = a.compareceu === valor ? "" : valor;
      await api("PUT", `/api/agenda/${id}`, { ...payloadDe(a), compareceu: novo });
      toast(novo === "S" ? "Presença registrada." : novo === "N" ? "Falta registrada — o horário foi liberado." : "Situação reaberta.", "ok");
      this.carregar();
    } catch (e) { erroToast(e); }
  },

  async excluir(id) {
    const a = this.itens.find((x) => x.id === id);
    if (!(await confirmar("Excluir agendamento", `Excluir o agendamento de ${a?.nome_paciente || ""} às ${a?.hora || ""}? Esta ação é registrada no log.`, "Excluir", true))) return;
    try { await api("DELETE", `/api/agenda/${id}`); toast("Agendamento excluído.", "ok"); this.carregar(); } catch (e) { erroToast(e); }
  },
};

function payloadDe(a) {
  return {
    modalidade: a.modalidade, data: a.data, hora: a.hora, box: a.modalidade === "QT" ? a.box : "", paciente_id: a.paciente_id,
    protocolo: a.protocolo, tempo_estimado: a.tempo_estimado, compareceu: a.compareceu, hora_inicio: a.hora_inicio,
    hora_termino: a.hora_termino, enfermeiro_id: a.enfermeiro_id, observacao: a.observacao,
  };
}

// ---------------- Formulário de agendamento (modal) ----------------
const FormAgendamento = {
  async editar(id) {
    try {
      const { agendamento } = await api("GET", `/api/agenda/${id}`);
      this.abrir(agendamento, id);
    } catch (e) { erroToast(e); }
  },

  abrir(inicial = {}, id = null) {
    const editar = pode("agenda_editar");
    const titulo = id ? (editar ? "Alterar agendamento" : "Agendamento") : "Novo agendamento";
    const body = abrirModal(titulo, html`
      <form class="form" id="form-ag" novalidate>
        <div class="form-grid">
          <label>Modalidade
            <select name="modalidade">
              <option value="QT">Quimioterapia (Box)</option>
              <option value="CONSULTA_ENF">Consulta de Enfermagem</option>
              <option value="TELECONSULTA">Teleconsulta</option>
            </select></label>
          <label>Data <input type="date" name="data" required></label>
          <label class="span-2">Paciente
            <div class="autocomplete">
              <input type="search" placeholder="Nome, prontuário ou CPF" autocomplete="off" maxlength="100">
              <input type="hidden" name="paciente_id">
              <div class="ac-lista" hidden></div>
            </div></label>
          <label data-qt>Box / Poltrona <select name="box" data-fill="boxes"></select></label>
          <label data-qt>Protocolo <select name="protocolo" data-fill="protocolos"></select></label>
          <label data-qt>Tempo estimado <input type="time" name="tempo_estimado"></label>
          <label>Horário agendado <select name="hora" required></select></label>
          <label>Enfermeira(o) responsável <select name="enfermeiro_id" data-fill="enfermeiros"></select></label>
          <label>Compareceu?
            <select name="compareceu"><option value="">Em aberto</option><option value="S">Sim</option><option value="N">Não (falta)</option></select></label>
          <label>Hora início real <input type="time" name="hora_inicio"></label>
          <label>Hora término real <input type="time" name="hora_termino"></label>
          <label class="span-2">Observação <textarea name="observacao" rows="2" maxlength="1000"></textarea></label>
        </div>
        <p class="aviso" id="ag-previsao" hidden></p>
        <fieldset>
          <legend><label class="inline check"><input type="checkbox" id="ag-tem-inter"> Registrar intercorrência neste atendimento</label></legend>
          <div class="form-grid" id="ag-inter" hidden>
            <label>Intercorrência <select name="intercorrencia" data-fill="intercorrencias"></select></label>
            <label>Medida tomada <input name="medida_tomada" maxlength="1000"></label>
          </div>
        </fieldset>
        <p class="form-erro" id="ag-erro" role="alert"></p>
        <div class="form-acoes">
          <button type="button" class="btn btn-ghost" data-action="fechar-modal">Cancelar</button>
          ${editar ? html`<button class="btn btn-primary" type="submit">${id ? "Salvar alterações" : "Agendar"}</button>` : ""}
        </div>
      </form>`);
    const f = body.querySelector("#form-ag");
    preencherSelects(f);
    const ac = autocompletarPaciente(f.querySelector(".autocomplete"));
    const dados = { modalidade: "QT", box: "Box 1", ...inicial, data: brParaIso(inicial.data) || isoHoje() };
    preencherForm(f, { ...dados, hora: "" });
    if (inicial.paciente_id) ac.selecionar({ id: inicial.paciente_id, nome_completo: inicial.nome_paciente });
    if (!editar) $$("input, select, textarea", f).forEach((el) => { el.disabled = true; });

    const atualizarModalidade = () => {
      const qt = f.modalidade.value === "QT";
      $$("[data-qt]", f).forEach((el) => { el.hidden = !qt; });
    };
    const protocoloTempo = () => {
      const p = estado.meta.protocolos.find((x) => x.protocolo === f.protocolo.value);
      if (p) f.tempo_estimado.value = p.tempo_estimado;
    };
    const atualizarHorarios = async (manter) => {
      try {
        const d = await api("GET", `/api/agenda/disponibilidade?${qs({
          data: f.data.value, modalidade: f.modalidade.value, box: f.box.value, protocolo: f.protocolo.value,
          tempo_estimado: f.tempo_estimado.value, ignorar_id: id })}`);
        const atual = manter || f.hora.value;
        const lista = d.horarios.slice();
        if (atual && !lista.some((h) => h.hora === atual)) lista.push({ hora: atual, disponivel: true, fim_previsto: "" });
        setHTML(f.hora, html`<option value="">Selecione…</option>${lista.map((h) => html`
          <option value="${h.hora}" ${h.disponivel ? "" : raw("disabled")}>${h.hora}${h.disponivel ? ` → ${h.fim_previsto}` : ` — ${h.motivo_bloqueio}`}</option>`)}`);
        if (atual) f.hora.value = atual;
        if (!editar) f.hora.disabled = true;
        const prev = $("#ag-previsao");
        prev.hidden = false;
        prev.textContent = `${d.dia_semana} • duração considerada ${d.duracao_considerada_hhmm}. Horários fechados aparecem desabilitados.`;
      } catch (e) { $("#ag-erro").textContent = e.message; }
    };

    atualizarModalidade();
    if (!inicial.tempo_estimado) protocoloTempo();
    atualizarHorarios(dados.hora);
    f.modalidade.addEventListener("change", () => { atualizarModalidade(); atualizarHorarios(); });
    f.protocolo.addEventListener("change", () => { protocoloTempo(); atualizarHorarios(); });
    ["data", "box", "tempo_estimado"].forEach((n) => f[n].addEventListener("change", () => atualizarHorarios()));
    $("#ag-tem-inter").addEventListener("change", (ev) => { $("#ag-inter").hidden = !ev.target.checked; });

    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = lerForm(f);
      $("#ag-erro").textContent = "";
      if (!d.paciente_id) { $("#ag-erro").textContent = "Selecione o paciente na lista de busca."; return; }
      if (!d.hora) { $("#ag-erro").textContent = "Selecione um horário livre."; return; }
      const corpo = {
        ...d, paciente_id: Number(d.paciente_id), enfermeiro_id: d.enfermeiro_id ? Number(d.enfermeiro_id) : null,
        data: isoParaBr(d.data),
      };
      if (!$("#ag-tem-inter").checked) { corpo.intercorrencia = ""; corpo.medida_tomada = ""; }
      await enviando(f.querySelector("[type=submit]"), async () => {
        try {
          const r = await api(id ? "PUT" : "POST", id ? `/api/agenda/${id}` : "/api/agenda", corpo);
          fecharModal();
          toast(r.mensagem, "ok");
          $("#agenda-data").value = d.data;
          if (location.hash === "#agenda") Agenda.carregar(); else irPara("agenda");
        } catch (e) { $("#ag-erro").textContent = e.message; }
      });
    });
  },
};

// =====================================================================
// MURAL
// =====================================================================
const Mural = {
  inicializado: false,
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    $("#mural-data").value = isoHoje();
    $("#mural-data").addEventListener("change", () => this.carregar());
    $("#mural-mod").addEventListener("change", () => this.carregar());
    const p = () => qs({ data: isoParaBr($("#mural-data").value), modalidade: $("#mural-mod").value });
    Object.assign(ACOES, {
      "mural-imprimir": () => window.print(),
      "mural-pdf": () => baixar(`/api/agenda/mural.pdf?${p()}`, `mural_${$("#mural-data").value}.pdf`).catch(erroToast),
      "mural-png": () => baixar(`/api/agenda/mural.png?${p()}`, `mural_${$("#mural-data").value}.png`).catch(erroToast),
    });
  },
  async carregar() {
    this.init();
    const m = await api("GET", `/api/agenda/mural?${qs({ data: isoParaBr($("#mural-data").value), modalidade: $("#mural-mod").value })}`);
    setHTML("mural-folha", html`
      <div class="mural-cab">
        <h3>${estado.meta.instituicao}</h3>
        <p>MURAL DIÁRIO DE ATENDIMENTOS • ${m.data} (${m.dia_semana})</p>
        <span class="muted small">Total ${m.total_geral} • Quimioterapia ${m.total_quimioterapia} • Consultas ${m.total_consulta_enf} • Teleconsultas ${m.total_teleconsulta}</span>
      </div>
      <div class="tabela-wrap"><table class="tabela">
        <thead><tr><th>Hora</th><th>Paciente</th><th>Protocolo</th><th>Enfermeiro(a)</th><th>Box / Atendimento</th><th>Situação</th></tr></thead>
        <tbody>${m.itens.length ? m.itens.map((i) => html`<tr>
          <td><b>${i.hora}</b></td><td><b>${i.paciente}</b></td><td>${i.protocolo}</td><td>${i.enfermeiro}</td>
          <td><b>${i.local_atendimento}</b></td><td>${tagCompareceu(i.compareceu)}</td></tr>`)
          : html`<tr><td colspan="6" class="vazio">Nenhum atendimento agendado para esta data.</td></tr>`}</tbody>
      </table></div>`);
  },
};

// =====================================================================
// PACIENTES
// =====================================================================
const Pacientes = {
  inicializado: false,
  offset: 0,
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    const atualizar = debounce(() => { this.offset = 0; this.carregar(); }, 300);
    $("#pac-busca").addEventListener("input", atualizar);
    $("#pac-incluir-enc").addEventListener("change", atualizar);
    Object.assign(ACOES, {
      "novo-paciente": () => this.formulario(),
      "pac-abrir": (el) => this.detalhe(Number(el.dataset.id)),
      "pac-pagina": (el) => { this.offset = Number(el.dataset.offset); this.carregar(); },
    });
  },
  async carregar() {
    this.init();
    const q = $("#pac-busca").value.trim();
    let itens, total = 0;
    if (q.length >= 2) {
      const r = await api("POST", "/api/pacientes/busca", { q, incluir_encerrados: $("#pac-incluir-enc").checked, limite: 50 });
      itens = r.pacientes;
      setHTML("pac-paginacao", "");
    } else {
      const status = $("#pac-incluir-enc").checked ? "" : "INICIADO";
      const r = await api("GET", `/api/pacientes?${qs({ status, offset: this.offset, limite: 30 })}`);
      itens = r.pacientes; total = r.total;
      $("#cnt-ativos").textContent = r.contagens.ativos;
      $("#cnt-encerrados").textContent = r.contagens.encerrados;
      const pag = [];
      if (this.offset > 0) pag.push(html`<button type="button" class="btn btn-sm btn-ghost" data-action="pac-pagina" data-offset="${Math.max(0, this.offset - 30)}">‹ Anteriores</button>`);
      pag.push(html`<span class="muted small">${this.offset + 1}–${Math.min(this.offset + 30, total)} de ${total}</span>`);
      if (this.offset + 30 < total) pag.push(html`<button type="button" class="btn btn-sm btn-ghost" data-action="pac-pagina" data-offset="${this.offset + 30}">Próximos ›</button>`);
      setHTML("pac-paginacao", total ? html`${pag}` : "");
    }
    setHTML("pac-lista", itens.length ? html`${itens.map((p) => html`
      <div class="item">
        <div class="item-hora">${p.prontuario || "—"}<small>prontuário</small></div>
        <div class="item-corpo"><b>${p.nome_completo}</b>
          <span>${p.cpf_mascarado || "sem CPF"}${p.ciclo_tratamento ? ` • ${p.ciclo_tratamento}` : ""}</span>
          <div><span class="tag ${p.status === "ENCERRADO" ? "tag-erro" : "tag-ok"}">${p.status}</span>
            ${p.cadastro_incompleto ? html`<span class="tag tag-aviso">Cadastro incompleto</span>` : ""}</div>
        </div>
        <div class="item-acoes"><button type="button" class="btn btn-sm btn-ghost" data-action="pac-abrir" data-id="${p.id}">Abrir</button></div>
      </div>`)}` : vazio(q ? "Nenhum paciente encontrado." : "Nenhum paciente cadastrado."));
  },

  async detalhe(id) {
    try {
      const { paciente: p } = await api("GET", `/api/pacientes/${id}`);
      const editar = pode("pacientes_editar");
      const linha = (r, v) => (v ? html`<tr><th>${r}</th><td>${v}</td></tr>` : "");
      const body = abrirModal(p.nome_completo, html`
        <p><span class="tag ${p.status === "ENCERRADO" ? "tag-erro" : "tag-ok"}">${p.status}</span>
          ${p.cadastro_incompleto ? html`<span class="tag tag-aviso">Cadastro incompleto — informe o CPF</span>` : ""}</p>
        <div class="tabela-wrap"><table class="tabela"><tbody>
          ${linha("Prontuário", p.prontuario)}${linha("CPF", p.cpf)}${linha("Nascimento", p.data_nascimento)}
          ${linha("Telefone", p.telefone)}${linha("E-mail", p.email)}${linha("Endereço", p.endereco)}
          ${linha("Tipo sanguíneo", [p.tipo_sanguineo, p.fator_rh].filter(Boolean).join(" "))}
          ${linha("Abertura do prontuário", p.data_abertura_prontuario)}${linha("Ciclo de tratamento", p.ciclo_tratamento)}
          ${linha("Motivo do encerramento", p.motivo_encerramento)}${linha("Data do encerramento", p.data_encerramento)}
          ${linha("Data do retorno", p.data_retorno)}
        </tbody></table></div>
        ${editar ? html`<div class="form-acoes">
          <button type="button" class="btn btn-ghost" data-p="editar">Editar cadastro</button>
          ${p.status === "ENCERRADO"
            ? html`<button type="button" class="btn btn-ok" data-p="reativar">Reativar tratamento</button>`
            : html`<button type="button" class="btn btn-danger" data-p="encerrar">Encerrar tratamento</button>`}
        </div>` : ""}`);
      body.addEventListener("click", (ev) => {
        const b = ev.target.closest("[data-p]");
        if (!b) return;
        if (b.dataset.p === "editar") this.formulario(p);
        if (b.dataset.p === "encerrar") this.encerrar(p);
        if (b.dataset.p === "reativar") this.reativar(p);
      });
    } catch (e) { erroToast(e); }
  },

  formulario(p = null) {
    const body = abrirModal(p ? "Editar paciente" : "Novo paciente", html`
      <form class="form" id="form-pac" novalidate>
        <div class="form-grid">
          <label class="span-2">Nome completo * <input name="nome_completo" required maxlength="200" autocomplete="off"></label>
          <label>CPF * <input name="cpf" inputmode="numeric" required maxlength="14" autocomplete="off"></label>
          <label>Prontuário (7 dígitos) <input name="prontuario" inputmode="numeric" maxlength="7" placeholder="automático" autocomplete="off"></label>
          <label>Data de nascimento <input type="date" name="data_nascimento"></label>
          <label>Telefone <input name="telefone" inputmode="tel" maxlength="15" autocomplete="off"></label>
          <label>E-mail <input type="email" name="email" maxlength="160" autocomplete="off"></label>
          <label>Abertura do prontuário <input type="date" name="data_abertura_prontuario"></label>
          <label>Tipo sanguíneo <select name="tipo_sanguineo" data-fill="tipos-sanguineos"></select></label>
          <label>Fator RH <select name="fator_rh" data-fill="fatores-rh"></select></label>
          <label class="span-2">Ciclo de tratamento <input name="ciclo_tratamento" maxlength="160"></label>
        </div>
        <div id="pac-cpf-aviso"></div>
        <fieldset><legend>Endereço</legend>
          <div class="form-grid">
            <label>CEP <input name="cep" inputmode="numeric" maxlength="9" autocomplete="off"></label>
            <label class="span-2">Logradouro <input name="logradouro" maxlength="200"></label>
            <label>Número <input name="numero" maxlength="20"></label>
            <label>Complemento <input name="complemento" maxlength="120"></label>
            <label>Bairro <input name="bairro" maxlength="120"></label>
            <label>Cidade <input name="cidade" maxlength="120"></label>
            <label>UF <select name="uf" data-fill="ufs"></select></label>
          </div>
          <p class="muted small" id="cep-status">Digite o CEP para preencher automaticamente (ViaCEP). Todos os campos podem ser editados.</p>
        </fieldset>
        <p class="form-erro" id="pac-erro" role="alert"></p>
        <div class="form-acoes">
          <button type="button" class="btn btn-ghost" data-action="fechar-modal">Cancelar</button>
          <button class="btn btn-primary" type="submit">${p ? "Salvar" : "Cadastrar"}</button>
        </div>
      </form>`);
    const f = body.querySelector("#form-pac");
    preencherSelects(f);
    mascaraCpf(f.cpf); mascaraTelefone(f.telefone); mascaraCep(f.cep);
    if (p) {
      preencherForm(f, { ...p, data_nascimento: brParaIso(p.data_nascimento), data_abertura_prontuario: brParaIso(p.data_abertura_prontuario) });
      if (!p.logradouro && p.endereco) $("#cep-status").textContent = `Endereço importado: ${p.endereco}`;
    } else {
      f.data_abertura_prontuario.value = isoHoje();
      f.cpf.addEventListener("blur", async () => {
        const d = f.cpf.value.replace(/\D/g, "");
        if (d.length !== 11) return;
        try {
          const r = await api("POST", "/api/pacientes/verificar-cpf", { cpf: f.cpf.value });
          if (!r.cpf_valido) setHTML("pac-cpf-aviso", html`<p class="aviso erro">${r.erro}</p>`);
          else if (!r.existe) setHTML("pac-cpf-aviso", html`<p class="aviso ok">✓ ${r.mensagem}</p>`);
          else setHTML("pac-cpf-aviso", html`<div class="aviso erro">${r.mensagem}: <b>${r.paciente.nome_completo}</b> (prontuário ${r.paciente.prontuario})
            <div class="form-acoes"><button type="button" class="btn btn-sm btn-ghost" data-abrir="${r.paciente.id}">Abrir cadastro existente</button></div></div>`);
        } catch (e) { erroToast(e); }
      });
      $("#pac-cpf-aviso").addEventListener("click", (ev) => {
        const b = ev.target.closest("[data-abrir]");
        if (b) this.detalhe(Number(b.dataset.abrir));
      });
    }
    f.cep.addEventListener("input", async () => {
      const d = f.cep.value.replace(/\D/g, "");
      if (d.length !== 8) return;
      $("#cep-status").textContent = "Consultando CEP…";
      try {
        const r = await api("GET", `/api/endereco/cep?${qs({ cep: d })}`);
        ["logradouro", "bairro", "cidade", "uf"].forEach((k) => { if (r[k]) f[k].value = r[k]; });
        $("#cep-status").textContent = `Endereço encontrado (${r.provedor}). Complete o número.`;
        f.numero.focus();
      } catch (e) { $("#cep-status").textContent = e.message; }
    });
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = lerForm(f);
      d.data_nascimento = isoParaBr(d.data_nascimento);
      d.data_abertura_prontuario = isoParaBr(d.data_abertura_prontuario);
      await enviando(f.querySelector("[type=submit]"), async () => {
        try {
          const r = await api(p ? "PUT" : "POST", p ? `/api/pacientes/${p.id}` : "/api/pacientes", d);
          fecharModal();
          toast(r.mensagem, "ok");
          carregarMetadata();
          this.carregar();
        } catch (e) {
          $("#pac-erro").textContent = e.message;
          if (e.dados?.paciente) setHTML("pac-cpf-aviso", html`<p class="aviso erro">Cadastro existente: <b>${e.dados.paciente.nome_completo}</b> (prontuário ${e.dados.paciente.prontuario}, ${e.dados.paciente.status})</p>`);
        }
      });
    });
  },

  encerrar(p) {
    const body = abrirModal(`Encerrar tratamento — ${p.nome_completo}`, html`
      <form class="form" id="form-enc" novalidate>
        <label>Motivo <select name="motivo_encerramento" data-fill="motivos"></select></label>
        <label>Data do encerramento <input type="date" name="data_encerramento"></label>
        <p class="form-erro" id="enc-erro"></p>
        <div class="form-acoes"><button type="button" class="btn btn-ghost" data-action="fechar-modal">Cancelar</button>
          <button class="btn btn-danger" type="submit">Encerrar tratamento</button></div>
      </form>`);
    const f = body.querySelector("form");
    preencherSelects(f);
    f.data_encerramento.value = isoHoje();
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = lerForm(f);
      try {
        await api("POST", `/api/pacientes/${p.id}/encerrar`, { ...d, data_encerramento: isoParaBr(d.data_encerramento) });
        fecharModal(); toast("Tratamento encerrado.", "ok"); carregarMetadata(); this.carregar();
      } catch (e) { $("#enc-erro").textContent = e.message; }
    });
  },

  reativar(p) {
    const body = abrirModal(`Reativar tratamento — ${p.nome_completo}`, html`
      <form class="form" novalidate>
        <p class="muted">O mesmo cadastro é reaproveitado (sem duplicar o CPF).</p>
        <label>Ciclo / protocolo de retorno * <input name="ciclo_tratamento" required maxlength="160" placeholder="Ex.: Retorno 1º ciclo"></label>
        <label>Data do retorno <input type="date" name="data_retorno"></label>
        <p class="form-erro" id="rea-erro"></p>
        <div class="form-acoes"><button type="button" class="btn btn-ghost" data-action="fechar-modal">Cancelar</button>
          <button class="btn btn-ok" type="submit">Reativar</button></div>
      </form>`);
    const f = body.querySelector("form");
    f.data_retorno.value = isoHoje();
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = lerForm(f);
      try {
        await api("POST", `/api/pacientes/${p.id}/reativar`, { ...d, data_retorno: isoParaBr(d.data_retorno) });
        fecharModal(); toast("Tratamento reativado.", "ok"); carregarMetadata(); this.carregar();
      } catch (e) { $("#rea-erro").textContent = e.message; }
    });
  },
};

// =====================================================================
// INTERCORRÊNCIAS
// =====================================================================
const Intercorrencias = {
  inicializado: false,
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    const f = $("#form-intercorrencia");
    f.data.value = isoHoje();
    $("#inter-mes").value = mesAtual();
    $("#inter-mes").addEventListener("change", () => this.carregar());
    this.ac = autocompletarPaciente(f.querySelector(".autocomplete"), { incluirEncerrados: () => true });
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = lerForm(f);
      if (!d.paciente_id) { toast("Selecione o paciente na lista.", "erro"); return; }
      await enviando(f.querySelector("[type=submit]"), async () => {
        try {
          await api("POST", "/api/intercorrencias", { ...d, paciente_id: Number(d.paciente_id), data: isoParaBr(d.data) });
          toast("Intercorrência registrada.", "ok");
          f.reset(); f.data.value = isoHoje(); this.ac.limpar(); this.carregar();
        } catch (e) { erroToast(e); }
      });
    });
  },
  async carregar() {
    this.init();
    const [ano, mes] = ($("#inter-mes").value || mesAtual()).split("-").map(Number);
    const r = await api("GET", `/api/intercorrencias?${qs({ ano, mes })}`);
    setHTML("inter-lista", r.intercorrencias.length ? html`<table class="tabela"><thead><tr>
      <th>Data</th><th>Paciente</th><th>Intercorrência</th><th>Protocolo</th><th>Enfermeiro(a)</th><th>Medida tomada</th></tr></thead>
      <tbody>${r.intercorrencias.map((i) => html`<tr><td>${i.data}</td><td>${i.paciente}</td><td><b>${i.intercorrencia}</b></td>
        <td>${i.protocolo}</td><td>${i.enfermeiro}</td><td>${i.medida_tomada}</td></tr>`)}</tbody></table>`
      : vazio("Nenhuma intercorrência registrada no mês."));
  },
};

// =====================================================================
// ESTATÍSTICAS DIÁRIAS
// =====================================================================
const Estatisticas = {
  _iniciando: null,
  tipo: "auditoria",
  campos: null,
  init() {
    if (!this._iniciando) this._iniciando = this._init();
    return this._iniciando;
  },
  async _init() {
    this.campos = await api("GET", "/api/estatisticas/campos");
    const f = $("#form-estatistica");
    f.data.value = isoHoje();
    $("#est-mes").value = mesAtual();
    $("#est-mes").addEventListener("change", () => this.carregar());
    f.data.addEventListener("change", () => this.preencherDoDia());
    $$(".subtab[data-est]").forEach((b) => b.addEventListener("click", () => {
      this.tipo = b.dataset.est;
      $$(".subtab[data-est]").forEach((x) => x.classList.toggle("ativo", x === b));
      this.montarCampos();
      this.carregar();
    }));
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const valores = {};
      $$("#est-campos input", f).forEach((i) => { valores[i.name] = Number(i.value || 0); });
      await enviando(f.querySelector("[type=submit]"), async () => {
        try {
          const r = await api("PUT", `/api/estatisticas/${this.tipo}`, { data: isoParaBr(f.data.value), valores });
          toast(r.mensagem, "ok"); this.carregar();
        } catch (e) { erroToast(e); }
      });
    });
    this.montarCampos();
  },
  montarCampos() {
    const campos = this.campos[this.tipo];
    $("#est-titulo").textContent = this.tipo === "auditoria" ? "Auditoria Clínica Prévia — lançamento do dia" : "Estatística de Agendamento — lançamento do dia";
    setHTML("est-campos", html`${Object.entries(campos).map(([k, rot]) => html`
      <label>${rot}<input type="number" name="${k}" min="0" max="100000" inputmode="numeric" value="0"></label>`)}`);
    if (!pode("estatisticas_editar")) $$("#est-campos input").forEach((i) => { i.disabled = true; });
  },
  registros: [],
  preencherDoDia() {
    const br = isoParaBr($("#form-estatistica").data.value);
    const r = this.registros.find((x) => x.data === br);
    $$("#est-campos input").forEach((i) => { i.value = r ? r[i.name] : 0; });
  },
  async carregar() {
    await this.init();
    const [ano, mes] = ($("#est-mes").value || mesAtual()).split("-").map(Number);
    const r = await api("GET", `/api/estatisticas/${this.tipo}?${qs({ ano, mes })}`);
    this.registros = r.registros;
    this.preencherDoDia();
    const campos = Object.entries(r.campos);
    setHTML("est-lista", r.registros.length ? html`<table class="tabela"><thead><tr><th>Data</th>
      ${campos.map(([, rot]) => html`<th title="${rot}">${rot.length > 28 ? `${rot.slice(0, 26)}…` : rot}</th>`)}</tr></thead>
      <tbody>${r.registros.map((x) => html`<tr><td><b>${x.data}</b></td>${campos.map(([k]) => html`<td class="num">${x[k]}</td>`)}</tr>`)}</tbody>
      <tfoot><tr><th>Total</th>${campos.map(([k]) => html`<th class="num">${r.registros.reduce((s, x) => s + x[k], 0)}</th>`)}</tr></tfoot></table>`
      : vazio("Sem lançamentos neste mês."));
  },
};

// =====================================================================
// MAPA DE CALOR
// =====================================================================
const Mapa = {
  inicializado: false,
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    $("#mapa-ano").value = new Date().getFullYear();
    setHTML("mapa-mes", html`<option value="">Ano inteiro</option>${MESES.map((m, i) => html`<option value="${i + 1}">${m}</option>`)}`);
    $("#mapa-mes").value = String(new Date().getMonth() + 1);
    $("#mapa-poltronas").value = estado.meta.qtd_poltronas;
    $("#mapa-horas").value = estado.meta.horas_funcionamento_dia;
    ACOES["mapa-atualizar"] = () => this.carregar();
  },
  async carregar() {
    this.init();
    const r = await api("GET", `/api/relatorios/mapa-calor?${qs({ ano: $("#mapa-ano").value, mes: $("#mapa-mes").value,
      qtd_poltronas: $("#mapa-poltronas").value, horas_funcionamento: $("#mapa-horas").value })}`);
    const dias = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
    setHTML("mapa-meses", html`${r.meses.map((m) => html`
      <div class="mes">
        <h4>${m.nome_mes} ${m.ano}</h4>
        <div class="mes-resumo">Ocupação <b>${fmtNum(m.taxa_ocupacao_pct)}%</b> • ${fmtNum(m.total_ocupacao_mes_horas)}h de ${fmtNum(m.capacidade_mes_horas)}h • ociosas ${fmtNum(m.horas_ociosas_mes)}h • ${m.dias_uteis} dias úteis</div>
        <table class="cal"><thead><tr>${dias.map((d) => html`<th>${d}</th>`)}</tr></thead>
        <tbody>${m.semanas.map((s) => html`<tr>${s.map((c) => (c.vazio ? html`<td></td>`
          : html`<td class="${c.classe_cor}" title="${c.data_br}: ${c.status_dia} • ${fmtNum(c.horas_ocupadas)}h ocupadas • ${c.atendimentos} atendimento(s) • ${fmtNum(c.taxa_ocupacao_pct)}%">
              <b>${c.dia}</b>${c.horas_ocupadas ? html`<i>${fmtNum(c.horas_ocupadas, 0)}h</i>` : ""}</td>`))}</tr>`)}</tbody></table>
      </div>`)}`);
    setHTML("mapa-boxes", barras(r.ocupacao_por_box, (b) => b.box, (b) => b.horas_ocupadas, "h"));
    setHTML("mapa-protocolos", barras(r.top_protocolos, (p) => p.protocolo, (p) => p.horas_ocupadas, "h"));
    setHTML("mapa-desvios", r.registros_tempo_real_vs_estimado.length ? html`<table class="tabela"><thead><tr>
      <th>Data</th><th>Box</th><th>Protocolo</th><th>Estimado</th><th>Entrada</th><th>Saída</th><th>Real</th><th>Diferença</th></tr></thead>
      <tbody>${r.registros_tempo_real_vs_estimado.map((x) => html`<tr><td>${x.data}</td><td>${x.box}</td><td>${x.protocolo}</td>
        <td>${x.tempo_estimado_hhmm}</td><td>${x.hora_entrada}</td><td>${x.hora_saida}</td><td>${x.tempo_ocupacao_real_hhmm}</td>
        <td class="num">${x.diferenca_minutos > 0 ? "+" : ""}${x.diferenca_minutos} min</td></tr>`)}</tbody></table>`
      : vazio("Nenhuma infusão com hora de início e término registradas no período."));
  },
};

// =====================================================================
// DASHBOARDS
// =====================================================================
const Dashboards = {
  inicializado: false,
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    $("#dash-mes").value = mesAtual();
    ACOES["dash-atualizar"] = () => this.carregar();
    $("#dash-mes").addEventListener("change", () => this.carregar());
  },
  async carregar() {
    this.init();
    const [ano, mes] = ($("#dash-mes").value || mesAtual()).split("-").map(Number);
    const d = await api("GET", `/api/relatorios/dashboard?${qs({ ano, mes })}`);
    const k = d.kpis;
    setHTML("dash-kpis", html`
      <div class="kpi destaque"><small>Agendamentos em ${d.periodo.mes_nome}</small><strong>${k.agendamentos_mes}</strong><span>${k.agendamentos_ano} no ano</span></div>
      <div class="kpi"><small>Pacientes em tratamento</small><strong>${k.pacientes_iniciados}</strong><span>${k.pacientes_encerrados} encerrados</span></div>
      <div class="kpi"><small>Quimioterapia</small><strong>${k.total_quimioterapia}</strong><span>no mês</span></div>
      <div class="kpi"><small>Consultas / Teleconsultas</small><strong>${k.total_consulta_enf} / ${k.total_teleconsulta}</strong><span>no mês</span></div>
      <div class="kpi"><small>Presença</small><strong>${fmtNum(k.taxa_presenca_pct)}%</strong><span>${k.total_compareceram} presenças</span></div>
      <div class="kpi"><small>Faltas</small><strong>${fmtNum(k.taxa_falta_pct)}%</strong><span>${k.total_faltas} faltas</span></div>
      <div class="kpi"><small>Intercorrências</small><strong>${k.total_intercorrencias}</strong><span>no mês</span></div>
      <div class="kpi"><small>Validação de prontuários</small><strong>${fmtNum(d.pendencias_auditoria.taxa_validacao_pct)}%</strong><span>${d.pendencias_auditoria.total_auditados} auditados</span></div>`);
    setHTML("dash-protocolos", barras(d.top_protocolos, (p) => p.protocolo, (p) => p.total_agendado));
    setHTML("dash-pendencias", barras(d.pendencias_auditoria.ranking_pendencias, (p) => p.motivo, (p) => p.quantidade));
    setHTML("dash-faltas", d.top_pacientes_faltas.length ? html`<table class="tabela"><thead><tr><th>Prontuário</th><th>Paciente</th>
      <th>Faltas</th><th>Agendados</th><th>% faltas</th><th>Telefone</th><th>Status</th></tr></thead>
      <tbody>${d.top_pacientes_faltas.map((p) => html`<tr><td>${p.prontuario}</td><td><b>${p.nome_completo}</b></td><td class="num">${p.total_faltas}</td>
        <td class="num">${p.total_agendamentos}</td><td class="num">${fmtNum(p.taxa_falta_pct)}%</td><td>${p.telefone}</td><td>${p.status}</td></tr>`)}</tbody></table>`
      : vazio("Nenhuma falta registrada no ano."));
    const tagTempo = (b, t) => html`<span class="tag tag-${b}">${t}</span>`;
    setHTML("dash-tempo", d.tempo_real_protocolos.length ? html`<table class="tabela"><thead><tr><th>Protocolo</th><th>Infusões</th>
      <th>Estimado</th><th>Real médio</th><th>Desvio</th><th>⚡</th><th>⏱️</th><th>🐢</th><th>Intercorr.</th><th>Situação</th></tr></thead>
      <tbody>${d.tempo_real_protocolos.map((p) => html`<tr><td><b>${p.protocolo}</b></td><td class="num">${p.total_atendimentos}</td>
        <td>${p.tempo_estimado_medio_hhmm}</td><td>${p.tempo_real_medio_hhmm}</td><td class="num">${p.desvio_medio_pct > 0 ? "+" : ""}${fmtNum(p.desvio_medio_pct)}%</td>
        <td class="num">${p.muito_rapido_count}</td><td class="num">${p.no_tempo_count}</td><td class="num">${p.muito_devagar_count}</td>
        <td class="num">${p.intercorrencias_count}</td><td>${tagTempo(p.status_badge, p.status_geral)}</td></tr>`)}</tbody></table>`
      : vazio("Registre a hora de início e de término das infusões para ver esta análise."));
    setHTML("dash-equipe", d.desempenho_enfermeiros.length ? html`<table class="tabela"><thead><tr><th>Enfermeiro(a)</th><th>Infusões</th>
      <th>Estimado médio</th><th>Real médio</th><th>Desvio</th><th>Intercorrências</th><th>Tendência</th></tr></thead>
      <tbody>${d.desempenho_enfermeiros.map((e) => html`<tr><td><b>${e.enfermeiro}</b></td><td class="num">${e.total_atendimentos}</td>
        <td class="num">${fmtNum(e.tempo_estimado_medio_min, 0)} min</td><td class="num">${fmtNum(e.tempo_real_medio_min, 0)} min</td>
        <td class="num">${e.desvio_medio_pct > 0 ? "+" : ""}${fmtNum(e.desvio_medio_pct)}%</td><td class="num">${e.intercorrencias_presentes}</td>
        <td>${tagTempo(e.badge, e.tendencia)}</td></tr>`)}</tbody></table>` : vazio("Sem infusões finalizadas no período."));
    setHTML("dash-inter-tipos", barras(d.intercorrencias.principais_tipos, (i) => i.tipo, (i) => i.quantidade));
    setHTML("dash-inter-prot", barras(d.intercorrencias.por_protocolo, (i) => i.protocolo, (i) => i.quantidade));
  },
};

// =====================================================================
// PROTOCOLOS E CATÁLOGOS
// =====================================================================
const Protocolos = {
  inicializado: false,
  lista: [],
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    $("#prot-filtro").addEventListener("input", () => this.render());
    $("#form-protocolo").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = ev.currentTarget;
      try { await api("POST", "/api/protocolos", lerForm(f)); toast("Protocolo cadastrado.", "ok"); f.reset(); this.carregar(); carregarMetadata(); }
      catch (e) { erroToast(e); }
    });
    $("#form-tipo-inter").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = ev.currentTarget;
      try { await api("POST", "/api/tipos-intercorrencia", lerForm(f)); toast("Tipo cadastrado.", "ok"); f.reset(); this.carregar(); carregarMetadata(); }
      catch (e) { erroToast(e); }
    });
    Object.assign(ACOES, {
      "prot-editar": (el) => this.editar(this.lista.find((p) => p.id === Number(el.dataset.id))),
      "tipo-alternar": async (el) => {
        try {
          await api("PUT", `/api/tipos-intercorrencia/${el.dataset.id}`, { nome: el.dataset.nome, ativo: el.dataset.ativo !== "true" });
          this.carregar(); carregarMetadata();
        } catch (e) { erroToast(e); }
      },
    });
  },
  async carregar() {
    this.init();
    const [p, t] = await Promise.all([api("GET", "/api/protocolos"), api("GET", "/api/tipos-intercorrencia")]);
    this.lista = p.protocolos;
    this.render();
    const adm = pode("protocolos_editar");
    setHTML("tipos-lista", html`<table class="tabela"><thead><tr><th>Tipo</th><th>Situação</th>${adm ? html`<th></th>` : ""}</tr></thead>
      <tbody>${t.tipos.map((x) => html`<tr><td>${x.nome}</td><td>${x.ativo ? html`<span class="tag tag-ok">Ativo</span>` : html`<span class="tag">Inativo</span>`}</td>
        ${adm ? html`<td><button type="button" class="btn btn-sm btn-ghost" data-action="tipo-alternar" data-id="${x.id}" data-nome="${x.nome}" data-ativo="${x.ativo}">${x.ativo ? "Desativar" : "Ativar"}</button></td>` : ""}</tr>`)}</tbody></table>`);
  },
  render() {
    const f = $("#prot-filtro").value.trim().toLowerCase();
    const adm = pode("protocolos_editar");
    const itens = this.lista.filter((p) => !f || p.nome.toLowerCase().includes(f));
    setHTML("prot-lista", html`<table class="tabela"><thead><tr><th>Protocolo</th><th>Tempo de poltrona</th><th>Situação</th>${adm ? html`<th></th>` : ""}</tr></thead>
      <tbody>${itens.map((p) => html`<tr><td><b>${p.nome}</b></td><td>${p.tempo_estimado}</td>
        <td>${p.ativo ? html`<span class="tag tag-ok">Ativo</span>` : html`<span class="tag">Inativo</span>`}</td>
        ${adm ? html`<td><button type="button" class="btn btn-sm btn-ghost" data-action="prot-editar" data-id="${p.id}">Editar</button></td>` : ""}</tr>`)}</tbody></table>`);
  },
  editar(p) {
    const body = abrirModal(`Protocolo ${p.nome}`, html`<form class="form" novalidate>
      <label>Tempo estimado de poltrona <input type="time" name="tempo_estimado" required></label>
      <label class="inline check"><input type="checkbox" name="ativo"> Ativo (aparece nos agendamentos)</label>
      <p class="muted small">O nome não pode ser alterado para preservar o histórico. Para renomear, desative e cadastre outro.</p>
      <div class="form-acoes"><button type="button" class="btn btn-ghost" data-action="fechar-modal">Cancelar</button>
        <button class="btn btn-primary" type="submit">Salvar</button></div></form>`);
    const f = body.querySelector("form");
    f.tempo_estimado.value = p.tempo_estimado;
    f.ativo.checked = p.ativo;
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        await api("PUT", `/api/protocolos/${p.id}`, { nome: p.nome, tempo_estimado: f.tempo_estimado.value, ativo: f.ativo.checked });
        fecharModal(); toast("Protocolo atualizado.", "ok"); this.carregar(); carregarMetadata();
      } catch (e) { erroToast(e); }
    });
  },
};

// =====================================================================
// USUÁRIOS E PERMISSÕES
// =====================================================================
const Usuarios = {
  inicializado: false,
  lista: [],
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    Object.assign(ACOES, {
      "novo-usuario": () => this.formulario(),
      "usr-editar": (el) => this.formulario(this.lista.find((u) => u.id === Number(el.dataset.id))),
      "usr-senha": (el) => this.redefinir(this.lista.find((u) => u.id === Number(el.dataset.id))),
    });
  },
  async carregar() {
    this.init();
    const r = await api("GET", "/api/usuarios");
    this.lista = r.usuarios;
    setHTML("usr-lista", html`<table class="tabela"><thead><tr><th>Nome</th><th>Usuário</th><th>Perfil</th><th>COREN</th>
      <th>Situação</th><th>Último acesso</th><th></th></tr></thead>
      <tbody>${r.usuarios.map((u) => html`<tr><td><b>${u.nome}</b></td><td>${u.usuario}</td><td><span class="tag">${u.perfil}</span></td><td>${u.coren}</td>
        <td>${u.ativo ? html`<span class="tag tag-ok">Ativo</span>` : html`<span class="tag tag-erro">Inativo</span>`}
          ${u.bloqueado ? html`<span class="tag tag-aviso">Bloqueado</span>` : ""}${u.trocar_senha ? html`<span class="tag tag-aviso">Senha temporária</span>` : ""}</td>
        <td>${u.ultimo_login || "—"}</td>
        <td><div class="grupo-btn"><button type="button" class="btn btn-sm btn-ghost" data-action="usr-editar" data-id="${u.id}">Editar</button>
          <button type="button" class="btn btn-sm btn-ghost" data-action="usr-senha" data-id="${u.id}">Redefinir senha</button></div></td></tr>`)}</tbody></table>`);
  },
  mostrarSenha(nome, senha) {
    abrirModal("Senha temporária", html`
      <p>Entregue esta senha <b>pessoalmente</b> a ${nome}. Ela só aparece agora e deverá ser trocada no primeiro acesso.</p>
      <div class="senha-temp">${senha}</div>
      <div class="form-acoes"><button type="button" class="btn btn-primary" data-action="fechar-modal">Entendi</button></div>`);
  },
  formulario(u = null) {
    const body = abrirModal(u ? `Editar ${u.nome}` : "Novo usuário", html`
      <form class="form" novalidate>
        <div class="form-grid">
          <label class="span-2">Nome completo * <input name="nome" required maxlength="160"></label>
          <label>Usuário (login) * <input name="usuario" required maxlength="60" autocapitalize="none" spellcheck="false" placeholder="ex.: maria.silva"></label>
          <label>Perfil * <select name="perfil" data-fill="perfis"></select></label>
          <label>Matrícula <input name="matricula" maxlength="30"></label>
          <label>COREN <input name="coren" maxlength="30"></label>
          <label>CPF <input name="cpf" inputmode="numeric" maxlength="14"></label>
          <label>Telefone <input name="telefone" inputmode="tel" maxlength="15"></label>
          <label class="span-2">E-mail <input type="email" name="email" maxlength="160"></label>
        </div>
        <label class="inline check"><input type="checkbox" name="ativo" checked> Usuário ativo</label>
        <p class="form-erro" id="usr-erro"></p>
        <div class="form-acoes"><button type="button" class="btn btn-ghost" data-action="fechar-modal">Cancelar</button>
          <button class="btn btn-primary" type="submit">${u ? "Salvar" : "Criar usuário"}</button></div>
      </form>`);
    const f = body.querySelector("form");
    preencherSelects(f);
    mascaraCpf(f.cpf); mascaraTelefone(f.telefone);
    if (u) { preencherForm(f, u); f.ativo.checked = u.ativo; } else f.perfil.value = "ENFERMEIRO";
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const d = { ...lerForm(f), ativo: f.ativo.checked };
      try {
        const r = await api(u ? "PUT" : "POST", u ? `/api/usuarios/${u.id}` : "/api/usuarios", d);
        await this.carregar(); carregarMetadata();
        if (r.senha_temporaria) this.mostrarSenha(d.nome, r.senha_temporaria);
        else { fecharModal(); toast(r.mensagem, "ok"); }
      } catch (e) { $("#usr-erro").textContent = e.message; }
    });
  },
  async redefinir(u) {
    if (!(await confirmar("Redefinir senha", `Gerar nova senha temporária para ${u.nome}? As sessões abertas dessa pessoa serão encerradas e a conta desbloqueada.`, "Redefinir"))) return;
    try {
      const r = await api("POST", `/api/usuarios/${u.id}/redefinir-senha`);
      this.mostrarSenha(u.nome, r.senha_temporaria);
      this.carregar();
    } catch (e) { erroToast(e); }
  },
};

// =====================================================================
// LOG DE AUDITORIA
// =====================================================================
const Auditoria = {
  inicializado: false,
  offset: 0,
  init() {
    if (this.inicializado) return;
    this.inicializado = true;
    $("#form-aud-filtro").addEventListener("submit", (ev) => { ev.preventDefault(); this.offset = 0; this.carregar(); });
    ACOES["aud-pagina"] = (el) => { this.offset = Number(el.dataset.offset); this.carregar(); };
  },
  async carregar() {
    this.init();
    const f = lerForm($("#form-aud-filtro"));
    const r = await api("GET", `/api/auditoria?${qs({ ...f, data_ini: isoParaBr(f.data_ini), data_fim: isoParaBr(f.data_fim), offset: this.offset, limite: 100 })}`);
    setHTML("aud-lista", r.eventos.length ? html`<table class="tabela"><thead><tr><th>Quando</th><th>Usuário</th><th>Ação</th>
      <th>Registro</th><th>Resultado</th><th>Detalhe</th><th>IP</th></tr></thead>
      <tbody>${r.eventos.map((e) => html`<tr><td>${e.momento}</td><td>${e.usuario}</td><td><b>${e.acao}</b></td>
        <td>${e.entidade}${e.entidade_id ? ` #${e.entidade_id}` : ""}</td>
        <td><span class="tag ${e.resultado === "OK" ? "tag-ok" : "tag-erro"}">${e.resultado}</span></td><td>${e.detalhe}</td><td>${e.ip}</td></tr>`)}</tbody></table>`
      : vazio("Nenhum evento encontrado."));
    const pag = [];
    if (this.offset > 0) pag.push(html`<button type="button" class="btn btn-sm btn-ghost" data-action="aud-pagina" data-offset="${Math.max(0, this.offset - 100)}">‹ Mais recentes</button>`);
    pag.push(html`<span class="muted small">${r.total} evento(s)</span>`);
    if (this.offset + 100 < r.total) pag.push(html`<button type="button" class="btn btn-sm btn-ghost" data-action="aud-pagina" data-offset="${this.offset + 100}">Mais antigos ›</button>`);
    setHTML("aud-paginacao", html`${pag}`);
  },
};

// =====================================================================
// INÍCIO
// =====================================================================
(async function iniciar() {
  try {
    const me = await api("GET", "/api/auth/me");
    iniciarSessao(me);
  } catch {
    mostrarLogin("");
  }
})();

