// =====================================================================
// Núcleo da interface: escape de HTML (anti-XSS), cliente da API com CSRF,
// avisos (toasts), modal, autocompletar de pacientes e utilidades de data.
// =====================================================================

// ---------- HTML seguro: tudo que é interpolado é escapado ----------
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(s);

function render(v) {
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(render).join("");
  if (v === false || v === null || v === undefined) return "";
  return esc(v);
}

export function html(strings, ...vals) {
  let out = strings[0];
  vals.forEach((v, i) => { out += render(v) + strings[i + 1]; });
  return new Raw(out);
}

export function setHTML(el, conteudo) {
  if (typeof el === "string") el = document.getElementById(el);
  if (!el) return;
  el.innerHTML = conteudo instanceof Raw ? conteudo.s : esc(conteudo);
  aplicarLarguras(el);
}

// Barras dos gráficos: largura aplicada via CSSOM (compatível com a CSP, sem style="" inline)
export function aplicarLarguras(root) {
  root.querySelectorAll("[data-pct]").forEach((el) => {
    const p = Math.max(0, Math.min(100, Number(el.dataset.pct) || 0));
    el.style.width = `${p}%`;
  });
  root.querySelectorAll("[data-pcth]").forEach((el) => {
    const p = Math.max(0, Math.min(100, Number(el.dataset.pcth) || 0));
    el.style.height = `${p}%`;
  });
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ---------- API ----------
export const estado = { csrf: "", user: null, meta: null };

export class ApiErro extends Error {
  constructor(msg, status, dados) { super(msg); this.status = status; this.dados = dados || {}; }
}

let aoPerderSessao = () => {};
let aoExigirTroca = () => {};
export function configurarApi({ sessaoPerdida, trocaObrigatoria }) {
  aoPerderSessao = sessaoPerdida;
  aoExigirTroca = trocaObrigatoria;
}

export async function api(metodo, url, corpo, cabecalhos = {}) {
  const opts = { method: metodo, credentials: "same-origin", headers: { Accept: "application/json", ...cabecalhos } };
  if (metodo !== "GET") {
    opts.headers["X-CSRF-Token"] = estado.csrf;
    if (corpo !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(corpo);
    }
  }
  let resp;
  try {
    resp = await fetch(url, opts);
  } catch {
    throw new ApiErro("Sem conexão com o servidor. Verifique a rede da unidade.", 0);
  }
  let dados = {};
  try { dados = await resp.json(); } catch { /* resposta sem JSON */ }
  if (resp.status === 401 && !url.startsWith("/api/auth/login")) {
    aoPerderSessao();
    throw new ApiErro(dados.erro || "Sessão expirada.", 401, dados);
  }
  if (resp.status === 403 && /Troque sua senha/.test(dados.erro || "")) {
    aoExigirTroca(true);
    throw new ApiErro(dados.erro, 403, dados);
  }
  if (!resp.ok || dados.ok === false) {
    throw new ApiErro(dados.erro || `Erro ${resp.status}`, resp.status, dados);
  }
  return dados;
}

export const qs = (obj) =>
  new URLSearchParams(Object.entries(obj).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();

// Download de arquivo (PDF/PNG) mantendo o cookie de sessão
export async function baixar(url, nome) {
  const resp = await fetch(url, { credentials: "same-origin" });
  if (resp.status === 401) { aoPerderSessao(); return; }
  if (!resp.ok) throw new ApiErro("Não foi possível gerar o arquivo.", resp.status);
  const blob = await resp.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = nome;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
}

// ---------- Avisos ----------
export function toast(msg, tipo = "") {
  const t = document.createElement("div");
  t.className = `toast ${tipo}`;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), tipo === "erro" ? 7000 : 4000);
}
export const erroToast = (e) => toast(e?.message || "Erro inesperado.", "erro");

// ---------- Modal ----------
let ultimoFoco = null;
export function abrirModal(titulo, conteudo) {
  ultimoFoco = document.activeElement;
  $("#modal-titulo").textContent = titulo;
  setHTML("modal-body", conteudo);
  $("#modal").hidden = false;
  document.body.classList.add("modal-aberto");
  setTimeout(() => { $("#modal-body input:not([type=hidden]), #modal-body select, #modal-body button")?.focus(); }, 30);
  return $("#modal-body");
}
export function fecharModal() {
  $("#modal").hidden = true;
  setHTML("modal-body", "");
  document.body.classList.remove("modal-aberto");
  ultimoFoco?.focus?.();
}
export function confirmar(titulo, mensagem, rotulo = "Confirmar", perigo = false) {
  return new Promise((resolve) => {
    const body = abrirModal(titulo, html`
      <p>${mensagem}</p>
      <div class="form-acoes">
        <button type="button" class="btn btn-ghost" data-r="0">Cancelar</button>
        <button type="button" class="btn ${perigo ? "btn-danger" : "btn-primary"}" data-r="1">${rotulo}</button>
      </div>`);
    body.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-r]");
      if (!b) return;
      fecharModal();
      resolve(b.dataset.r === "1");
    });
  });
}

// ---------- Formulários ----------
export function lerForm(form) {
  const dados = {};
  new FormData(form).forEach((v, k) => { dados[k] = typeof v === "string" ? v.trim() : v; });
  return dados;
}
export function preencherForm(form, dados) {
  Object.entries(dados || {}).forEach(([k, v]) => {
    const el = form.elements.namedItem(k);
    if (el && "value" in el) el.value = v ?? "";
  });
}
export async function enviando(botao, fn) {
  if (!botao) return fn();
  botao.disabled = true;
  try { return await fn(); } finally { botao.disabled = false; }
}

// ---------- Datas ----------
const pad = (n) => String(n).padStart(2, "0");
export const isoHoje = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
export const mesAtual = () => isoHoje().slice(0, 7);
export const isoParaBr = (iso) => (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split("-").reverse().join("/") : iso || "");
export const brParaIso = (br) => (br && /^\d{2}\/\d{2}\/\d{4}$/.test(br) ? br.split("/").reverse().join("-") : br || "");
export function somarDias(iso, n) {
  const [a, m, d] = iso.split("-").map(Number);
  const dt = new Date(a, m - 1, d + n);
  return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`;
}
export const fmtNum = (n, casas = 1) => Number(n || 0).toLocaleString("pt-BR", { maximumFractionDigits: casas });

// ---------- Máscaras ----------
export function mascaraCpf(input) {
  input.addEventListener("input", () => {
    const d = input.value.replace(/\D/g, "").slice(0, 11);
    input.value = d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
  });
}
export function mascaraTelefone(input) {
  input.addEventListener("input", () => {
    const d = input.value.replace(/\D/g, "").slice(0, 11);
    input.value = d.length > 10
      ? d.replace(/(\d{2})(\d{5})(\d{0,4})/, "($1) $2-$3")
      : d.replace(/(\d{2})(\d{4})(\d{0,4})/, "($1) $2-$3").replace(/[-\s(]+$/, "");
  });
}
export function mascaraCep(input) {
  input.addEventListener("input", () => {
    const d = input.value.replace(/\D/g, "").slice(0, 8);
    input.value = d.length > 5 ? `${d.slice(0, 5)}-${d.slice(5)}` : d;
  });
}

export function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---------- Autocompletar de pacientes ----------
// Estrutura: <div class="autocomplete"><input type=search><input type=hidden name=paciente_id><div class=ac-lista></div></div>
export function autocompletarPaciente(wrap, { incluirEncerrados = () => false, aoSelecionar } = {}) {
  const campo = wrap.querySelector("input[type=search]");
  const oculto = wrap.querySelector("input[type=hidden]");
  const lista = wrap.querySelector(".ac-lista");
  let itens = [];

  const buscar = debounce(async () => {
    const q = campo.value.trim();
    oculto.value = "";
    if (q.length < 2) { lista.hidden = true; return; }
    try {
      const r = await api("POST", "/api/pacientes/busca", { q, incluir_encerrados: incluirEncerrados(), limite: 12 });
      itens = r.pacientes;
      setHTML(lista, itens.length
        ? html`${itens.map((p, i) => html`<button type="button" class="ac-item" data-i="${i}">
            <b>${p.nome_completo}</b>
            <small>Prontuário ${p.prontuario || "—"} • ${p.cpf_mascarado || "sem CPF"} • ${p.status}${p.cadastro_incompleto ? " • cadastro incompleto" : ""}</small>
          </button>`)}`
        : html`<div class="ac-item">Nenhum paciente encontrado. Cadastre na aba Pacientes.</div>`);
      lista.hidden = false;
    } catch (e) { erroToast(e); }
  }, 280);

  campo.addEventListener("input", buscar);
  campo.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { lista.querySelector(".ac-item")?.focus(); ev.preventDefault(); }
    if (ev.key === "Escape") lista.hidden = true;
  });
  lista.addEventListener("keydown", (ev) => {
    const atual = document.activeElement;
    if (ev.key === "ArrowDown") { atual.nextElementSibling?.focus(); ev.preventDefault(); }
    if (ev.key === "ArrowUp") { (atual.previousElementSibling || campo).focus(); ev.preventDefault(); }
    if (ev.key === "Escape") { lista.hidden = true; campo.focus(); }
  });
  lista.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-i]");
    if (!b) return;
    const p = itens[Number(b.dataset.i)];
    selecionar(p);
  });
  document.addEventListener("click", (ev) => { if (!wrap.contains(ev.target)) lista.hidden = true; });

  function selecionar(p) {
    if (!p) { oculto.value = ""; campo.value = ""; return; }
    oculto.value = p.id;
    campo.value = p.nome_completo;
    lista.hidden = true;
    aoSelecionar?.(p);
  }
  return { selecionar, limpar: () => selecionar(null) };
}
