// =====================================================================
// Gráficos em 3 dimensões (Canvas 2D, sem bibliotecas externas — compatível com a CSP).
//   grafico3d(el, { tipo: "barras", colunas, series, ... })  → colunas 3D (1 ou várias séries)
//   grafico3d(el, { tipo: "pizza", fatias, ... })            → rosca 3D
// Arraste (ou use as setas do teclado) para girar. Passe o mouse para ver o valor.
// Todo gráfico leva junto uma legenda e uma tabela com os mesmos dados.
// =====================================================================

// Paleta categórica conferida para daltonismo (ordem fixa: a cor acompanha a série, não a posição)
export const PALETA = ["#7b2fb5", "#eb6834", "#1baf7a", "#eda100", "#e0457b", "#2a78d6", "#008300", "#e34948"];
const TINTA = "#2D1B36";
const TINTA_2 = "#5B4668";
const LINHA = "#DCCDE6";
const PISO = "#F6EEF9";
const PAREDE = "#FBF7FD";
const FONTE = '"Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif';

const GRAUS = Math.PI / 180;
const limitar = (v, a, b) => Math.max(a, Math.min(b, v));
const suave = (t) => 1 - (1 - t) ** 3;
const fmt = (n, casas = 1) => Number(n || 0).toLocaleString("pt-BR", { maximumFractionDigits: casas });
const semMovimento = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function misturar(hex, alvo, t) {
  const a = rgb(hex);
  const b = alvo === "branco" ? [255, 255, 255] : [20, 6, 34];
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
}
function claro(hex) {
  const [r, g, b] = rgb(hex);
  return 0.299 * r + 0.587 * g + 0.114 * b > 150;
}
function escalaBonita(max, inteiro) {
  if (max <= 0) return { topo: 1, passo: 1 };
  const bruto = max / 4;
  const pot = 10 ** Math.floor(Math.log10(bruto));
  const passo = [1, 2, 5, 10].map((m) => m * pot).find((p) => p >= bruto) || 10 * pot;
  const p = inteiro ? Math.max(1, passo) : passo;
  return { topo: Math.ceil(max / p) * p, passo: p };
}
function dentro(poli, x, y) {
  let ok = false;
  for (let i = 0, j = poli.length - 1; i < poli.length; j = i++) {
    const [xi, yi] = poli[i];
    const [xj, yj] = poli[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) ok = !ok;
  }
  return ok;
}
function no(tag, classe, texto) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

// ---------------------------------------------------------------------
// Base: tamanho/nitidez do canvas, animação de entrada, arrastar, teclado e dica
// ---------------------------------------------------------------------
class Base {
  constructor(el, cfg) {
    this.el = el;
    this.cfg = cfg;
    this.sufixo = cfg.sufixo || "";
    this.casas = cfg.casas ?? 1;
    this.t = 0;
    this.alvos = [];
    this.foco = null;
    this.quadro = 0;
    this.iniciou = false;

    this.palco = no("div", "g3d-palco");
    this.canvas = no("canvas", "g3d-canvas");
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute("role", "img");
    this.canvas.setAttribute("aria-label", `${cfg.titulo || "Gráfico"} — gráfico em 3D. Use as setas do teclado para girar. Os valores estão na tabela logo abaixo.`);
    this.dica = no("div", "g3d-dica");
    this.dica.hidden = true;
    this.palco.append(this.canvas, this.dica);
    el.append(this.palco);
    this.ctx = this.canvas.getContext("2d");

    this._eventos();
    this.observador = new ResizeObserver(() => this._medir());
    this.observador.observe(this.palco);
  }

  destruir() {
    this.observador.disconnect();
    cancelAnimationFrame(this.quadro);
  }

  _medir() {
    const w = this.palco.clientWidth;
    const h = this.palco.clientHeight;
    if (!w || !h) return; // aba escondida: desenha quando aparecer
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = w;
    this.h = h;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!this.iniciou) {
      this.iniciou = true;
      this._animar();
    } else this.desenhar();
  }

  _animar() {
    if (this.cfg.animar === false || semMovimento()) { this.t = 1; this.desenhar(); return; }
    const inicio = performance.now();
    const passo = (agora) => {
      this.t = limitar((agora - inicio) / 800, 0, 1);
      this.desenhar();
      if (this.t < 1) this.quadro = requestAnimationFrame(passo);
    };
    this.quadro = requestAnimationFrame(passo);
  }

  _eventos() {
    const c = this.canvas;
    let arrasto = null;
    const pos = (ev) => { const r = c.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
    c.addEventListener("pointerdown", (ev) => {
      arrasto = { x: ev.clientX, y: ev.clientY };
      c.setPointerCapture?.(ev.pointerId);
      c.classList.add("girando");
    });
    c.addEventListener("pointermove", (ev) => {
      if (arrasto) {
        this.girar(ev.clientX - arrasto.x, ev.clientY - arrasto.y);
        arrasto = { x: ev.clientX, y: ev.clientY };
        this._mostrarDica(null);
        this.desenhar();
        return;
      }
      const [x, y] = pos(ev);
      const alvo = this.achar(x, y);
      if (alvo?.chave !== this.foco) {
        this.foco = alvo?.chave ?? null;
        this.desenhar();
      }
      this._mostrarDica(alvo, x, y);
    });
    const soltar = () => { arrasto = null; c.classList.remove("girando"); };
    c.addEventListener("pointerup", soltar);
    c.addEventListener("pointercancel", soltar);
    c.addEventListener("pointerleave", () => {
      if (arrasto) return;
      this.foco = null;
      this._mostrarDica(null);
      this.desenhar();
    });
    c.addEventListener("dblclick", () => { this.reiniciarVista(); this.desenhar(); });
    c.addEventListener("keydown", (ev) => {
      const passos = { ArrowLeft: [-12, 0], ArrowRight: [12, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] }[ev.key];
      if (ev.key === "Home") { this.reiniciarVista(); this.desenhar(); ev.preventDefault(); return; }
      if (!passos) return;
      ev.preventDefault();
      this.girar(...passos);
      this.desenhar();
    });
  }

  _mostrarDica(alvo, x = 0, y = 0) {
    if (!alvo) { this.dica.hidden = true; return; }
    this.dica.replaceChildren(no("b", "", alvo.titulo), no("span", "", alvo.texto));
    this.dica.hidden = false;
    const larg = this.dica.offsetWidth;
    this.dica.style.left = `${limitar(x + 14, 4, this.w - larg - 4)}px`;
    this.dica.style.top = `${Math.max(4, y - this.dica.offsetHeight - 10)}px`;
  }

  achar(x, y) {
    for (let i = this.alvos.length - 1; i >= 0; i--) {
      if (this.alvos[i].polis.some((p) => dentro(p, x, y))) return this.alvos[i];
    }
    return null;
  }
}

// ---------------------------------------------------------------------
// Colunas 3D (uma série = uma fileira; várias séries = fileiras em profundidade)
// ---------------------------------------------------------------------
class Barras3D extends Base {
  constructor(el, cfg) {
    super(el, cfg);
    this.reiniciarVista();
    const todos = cfg.series.flatMap((s) => s.valores);
    this.escala = escalaBonita(Math.max(0, ...todos), this.casas === 0);
    this._medir();
  }

  reiniciarVista() {
    this.giro = (this.cfg.giro ?? -26) * GRAUS;
    this.inclinacao = (this.cfg.inclinacao ?? 22) * GRAUS;
  }

  girar(dx, dy) {
    this.giro = limitar(this.giro + dx * 0.45 * GRAUS, -68 * GRAUS, 68 * GRAUS);
    this.inclinacao = limitar(this.inclinacao + dy * 0.3 * GRAUS, 8 * GRAUS, 58 * GRAUS);
  }

  desenhar() {
    const { ctx, cfg } = this;
    if (!this.w) return;
    const nc = cfg.colunas.length;
    const nr = cfg.series.length;
    const W = nc;
    const D = nr === 1 ? 1.5 : nr * 1.05;
    const H = limitar(W * 0.5, 3, 6.5);
    const raio = Math.hypot(W, D, H) / 2;
    const dist = raio * 3.2;
    const cg = Math.cos(this.giro), sg = Math.sin(this.giro);
    const ci = Math.cos(this.inclinacao), si = Math.sin(this.inclinacao);

    // ponto do mundo → [x, y, profundidade] ainda sem escala de tela
    const bruto = (x, y, z) => {
      const x1 = x * cg + z * sg;
      const z1 = -x * sg + z * cg;
      const y2 = (y - H / 2) * ci + z1 * si;
      const z2 = -(y - H / 2) * si + z1 * ci;
      const k = dist / (dist + z2);
      return [x1 * k, -y2 * k, z2];
    };
    // enquadra a caixa inteira no canvas, com margem para os rótulos
    const cantos = [];
    for (const x of [-W / 2, W / 2]) for (const y of [0, H]) for (const z of [-D / 2, D / 2]) cantos.push(bruto(x, y, z));
    const xs = cantos.map((p) => p[0]), ys = cantos.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const fonte = this.w < 520 ? 10 : 12;
    const margem = { esq: 46, dir: 46, topo: 26, base: nc > 1 ? 78 : 30 };
    const esc = Math.min((this.w - margem.esq - margem.dir) / (maxX - minX), (this.h - margem.topo - margem.base) / (maxY - minY));
    const ox = margem.esq + (this.w - margem.esq - margem.dir - (maxX - minX) * esc) / 2 - minX * esc;
    const oy = margem.topo + (this.h - margem.topo - margem.base - (maxY - minY) * esc) / 2 - minY * esc;
    const P = (x, y, z) => { const p = bruto(x, y, z); return [ox + p[0] * esc, oy + p[1] * esc, p[2]]; };

    const poli = (pts, preench, traco, larg = 1) => {
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
      ctx.closePath();
      if (preench) { ctx.fillStyle = preench; ctx.fill(); }
      if (traco) { ctx.strokeStyle = traco; ctx.lineWidth = larg; ctx.stroke(); }
    };
    const linha = (a, b, cor, larg = 1) => {
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
      ctx.strokeStyle = cor; ctx.lineWidth = larg; ctx.stroke();
    };

    ctx.clearRect(0, 0, this.w, this.h);
    ctx.lineJoin = "round";

    // --- piso e paredes do fundo ---
    const ladoFundo = this.giro > 0 ? -1 : 1; // parede lateral que fica atrás
    poli([P(-W / 2, 0, -D / 2), P(W / 2, 0, -D / 2), P(W / 2, 0, D / 2), P(-W / 2, 0, D / 2)], PISO, LINHA);
    poli([P(-W / 2, 0, D / 2), P(W / 2, 0, D / 2), P(W / 2, H, D / 2), P(-W / 2, H, D / 2)], PAREDE, LINHA);
    const xl = (ladoFundo * W) / 2;
    poli([P(xl, 0, -D / 2), P(xl, 0, D / 2), P(xl, H, D / 2), P(xl, H, -D / 2)], PAREDE, LINHA);
    for (let i = 1; i < nc; i++) linha(P(-W / 2 + i, 0, -D / 2), P(-W / 2 + i, 0, D / 2), LINHA, 0.6);

    // --- linhas de grade e números do eixo ---
    ctx.font = `600 ${fonte}px ${FONTE}`;
    ctx.fillStyle = TINTA_2;
    ctx.textBaseline = "middle";
    const { topo, passo } = this.escala;
    for (let v = 0; v <= topo + 1e-9; v += passo) {
      const y = (v / topo) * H;
      if (v > 0) {
        linha(P(-W / 2, y, D / 2), P(W / 2, y, D / 2), LINHA, 0.8);
        linha(P(xl, y, D / 2), P(xl, y, -D / 2), LINHA, 0.8);
      }
      const p = P(xl, y, -D / 2);
      ctx.textAlign = ladoFundo < 0 ? "right" : "left";
      ctx.fillText(fmt(v, this.casas), p[0] + ladoFundo * 7, p[1]);
    }

    // --- colunas (das mais distantes para as mais próximas) ---
    const larguraX = 0.62;
    const larguraZ = nr === 1 ? 0.8 : 0.62;
    const passoZ = D / nr;
    const barras = [];
    cfg.series.forEach((serie, j) => {
      serie.valores.forEach((valor, i) => {
        const x = -W / 2 + i + 0.5;
        const z = D / 2 - (j + 0.5) * passoZ; // primeira série fica ao fundo
        const atraso = nc > 1 ? (i / (nc - 1)) * 0.35 : 0;
        const cresc = suave(limitar((this.t - atraso) / 0.65, 0, 1));
        const alt = Math.max(0, (valor / topo) * H * cresc);
        barras.push({ i, j, x, z, alt, valor, serie, prof: bruto(x, alt / 2, z)[2] });
      });
    });
    barras.sort((a, b) => b.prof - a.prof);

    this.alvos = [];
    const topos = [];
    for (const b of barras) {
      const cor = cfg.cores?.[b.j]?.[b.i] || b.serie.cor || PALETA[b.j % PALETA.length];
      const chave = `${b.j}:${b.i}`;
      const aceso = this.foco === chave;
      const x0 = b.x - larguraX / 2, x1 = b.x + larguraX / 2;
      const z0 = b.z - larguraZ / 2, z1 = b.z + larguraZ / 2;
      const h = b.alt;
      const titulo = nr > 1 ? `${cfg.colunas[b.i]} • ${b.serie.nome}` : cfg.colunas[b.i];
      const texto = cfg.dica ? cfg.dica(b.valor, b.i, b.j) : `${fmt(b.valor, this.casas)}${this.sufixo}`;
      if (h < 0.004) {
        // valor zero: só uma marca no piso
        const base = [P(x0, 0, z0), P(x1, 0, z0), P(x1, 0, z1), P(x0, 0, z1)];
        poli(base, misturar(cor, "branco", 0.78), misturar(cor, "branco", 0.5), 0.8);
        this.alvos.push({ chave, polis: [base], titulo, texto });
        continue;
      }
      const faces = [
        { pts: [P(x0, 0, z0), P(x1, 0, z0), P(x1, h, z0), P(x0, h, z0)], tom: ["preto", 0.04] },
        { pts: [P(x0, 0, z1), P(x1, 0, z1), P(x1, h, z1), P(x0, h, z1)], tom: ["preto", 0.04] },
        { pts: [P(x0, 0, z0), P(x0, 0, z1), P(x0, h, z1), P(x0, h, z0)], tom: ["preto", 0.24] },
        { pts: [P(x1, 0, z0), P(x1, 0, z1), P(x1, h, z1), P(x1, h, z0)], tom: ["preto", 0.24] },
        { pts: [P(x0, h, z0), P(x1, h, z0), P(x1, h, z1), P(x0, h, z1)], tom: ["branco", 0.3] },
      ];
      faces.forEach((f) => { f.prof = f.pts.reduce((s, p) => s + p[2], 0) / 4; });
      faces.sort((a, c) => c.prof - a.prof);
      for (const f of faces) {
        const base = aceso ? misturar(cor, "branco", 0.22) : cor;
        const tinta = f.tom[0] === "branco"
          ? misturar(cor, "branco", aceso ? 0.48 : f.tom[1])
          : (aceso ? base : misturar(cor, "preto", f.tom[1]));
        poli(f.pts, tinta, misturar(cor, "preto", 0.35), 0.7);
      }
      this.alvos.push({ chave, polis: faces.map((f) => f.pts.map((p) => [p[0], p[1]])), titulo, texto });
      topos.push({ b, p: P(b.x, h, b.z) });
    }

    // --- rótulos ---
    ctx.fillStyle = TINTA;
    if (nr === 1 && nc <= 12 && this.t > 0.6) {
      ctx.globalAlpha = limitar((this.t - 0.6) / 0.4, 0, 1);
      ctx.font = `700 ${fonte}px ${FONTE}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      for (const { b, p } of topos) ctx.fillText(`${fmt(b.valor, this.casas)}${this.sufixo}`, p[0], p[1] - 6);
      ctx.globalAlpha = 1;
    }
    if (nc > 1 || cfg.colunas[0]) {
      ctx.font = `600 ${fonte}px ${FONTE}`;
      ctx.fillStyle = TINTA_2;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      const maxLetras = this.w < 520 ? 11 : 17;
      const pular = Math.ceil(nc / (this.w < 520 ? 10 : 22));
      cfg.colunas.forEach((rotulo, i) => {
        if (i % pular) return;
        const p = P(-W / 2 + i + 0.5, 0, -D / 2 - 0.18);
        const txt = String(rotulo).length > maxLetras ? `${String(rotulo).slice(0, maxLetras - 1)}…` : String(rotulo);
        ctx.save();
        ctx.translate(p[0], p[1] + 6);
        ctx.rotate(-34 * GRAUS);
        ctx.fillText(txt, 0, 0);
        ctx.restore();
      });
    }
    if (nr > 1 && cfg.rotulosSeries !== false) {
      const xf = (-ladoFundo * W) / 2; // lado que fica à frente
      ctx.font = `700 ${fonte}px ${FONTE}`;
      ctx.fillStyle = TINTA;
      ctx.textBaseline = "middle";
      ctx.textAlign = ladoFundo < 0 ? "left" : "right";
      cfg.series.forEach((s, j) => {
        const p = P(xf, 0, D / 2 - (j + 0.5) * passoZ);
        ctx.fillText(s.curto || s.nome, p[0] - ladoFundo * 9, p[1]);
      });
    }
  }
}

// ---------------------------------------------------------------------
// Rosca 3D
// ---------------------------------------------------------------------
class Pizza3D extends Base {
  constructor(el, cfg) {
    super(el, cfg);
    this.fatias = cfg.fatias.filter((f) => f.valor > 0);
    this.total = this.fatias.reduce((s, f) => s + f.valor, 0);
    this.reiniciarVista();
    this._medir();
  }

  reiniciarVista() { this.rot = -90 * GRAUS; this.achat = 0.56; }

  girar(dx, dy) {
    this.rot += dx * 0.6 * GRAUS;
    this.achat = limitar(this.achat + dy * 0.003, 0.35, 0.8);
  }

  _geo() {
    const esp = Math.min(this.w, this.h) * 0.085;
    const rx = Math.max(20, Math.min(this.w / 2 - 14, (this.h - esp - 30) / (2 * this.achat)));
    return { cx: this.w / 2, cy: (this.h - esp) / 2 + 4, rx, ry: rx * this.achat, esp, furo: 0.5 };
  }

  achar(x, y) {
    if (!this.arcos) return null;
    const { cx, cy, rx, ry, esp, furo } = this._geo();
    const dx = (x - cx) / rx;
    let ang = null;
    const r = Math.hypot(dx, (y - cy) / ry);
    if (r <= 1 && r >= furo) ang = Math.atan2((y - cy) / ry, dx);
    else if (Math.abs(dx) <= 1 && y > cy) {
      const borda = cy + Math.sqrt(1 - dx * dx) * ry;
      if (y >= borda && y <= borda + esp) ang = Math.acos(dx);
    }
    if (ang === null) return null;
    const volta = 2 * Math.PI;
    const rel = (((ang - this.rot) % volta) + volta) % volta;
    return this.arcos.find((a) => rel >= a.de && rel < a.ate)?.alvo || null;
  }

  desenhar() {
    const { ctx } = this;
    if (!this.w) return;
    ctx.clearRect(0, 0, this.w, this.h);
    if (!this.total) return;
    const { cx, cy, rx, ry, esp, furo } = this._geo();
    const abre = suave(this.t);
    const volta = 2 * Math.PI;
    const norm = (a) => ((a % volta) + volta) % volta;

    let acum = 0;
    this.arcos = [];
    const fatias = this.fatias.map((f, i) => {
      const de = acum;
      acum += (f.valor / this.total) * volta;
      const cor = f.cor || PALETA[i % PALETA.length];
      const pct = (f.valor / this.total) * 100;
      const alvo = { chave: `f${i}`, titulo: f.nome, texto: `${fmt(f.valor, this.casas)}${this.sufixo} • ${fmt(pct)}%` };
      this.arcos.push({ de, ate: acum, alvo });
      return { ...f, cor, pct, a0: this.rot + de * abre, a1: this.rot + acum * abre, chave: alvo.chave };
    });

    // trechos de um arco [a0, a1] que caem dentro da janela [de, ate] (em 0..2π)
    const recortes = (a0, a1, de, ate) => {
      const partes = [];
      const ini = norm(a0);
      const fim = ini + (a1 - a0);
      for (const desloc of [0, volta]) {
        const s = Math.max(ini, de + desloc), e = Math.min(fim, ate + desloc);
        if (e > s + 1e-4) partes.push([s, e]);
      }
      return partes;
    };
    const parede = (raioX, raioY, s, e, cor, sobe = 0) => {
      ctx.beginPath();
      ctx.ellipse(cx, cy - sobe, raioX, raioY, 0, s, e);
      ctx.ellipse(cx, cy + esp, raioX, raioY, 0, e, s, true);
      ctx.closePath();
      ctx.fillStyle = cor;
      ctx.fill();
    };
    const tampa = (f, sobe) => {
      ctx.beginPath();
      ctx.ellipse(cx, cy - sobe, rx, ry, 0, f.a0, f.a1);
      ctx.ellipse(cx, cy - sobe, rx * furo, ry * furo, 0, f.a1, f.a0, true);
      ctx.closePath();
      ctx.fillStyle = sobe ? misturar(f.cor, "branco", 0.2) : f.cor;
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
    };

    // 1) parede interna (lado de trás do furo)  2) parede externa (frente)  3) tampas
    for (const f of fatias) {
      for (const [s, e] of recortes(f.a0, f.a1, Math.PI, volta)) parede(rx * furo, ry * furo, s, e, misturar(f.cor, "preto", 0.42));
    }
    for (const f of fatias) {
      for (const [s, e] of recortes(f.a0, f.a1, 0, Math.PI)) parede(rx, ry, s, e, misturar(f.cor, "preto", 0.26));
    }
    const normais = fatias.filter((f) => f.chave !== this.foco);
    const acesa = fatias.find((f) => f.chave === this.foco);
    normais.forEach((f) => tampa(f, 0));
    if (acesa) {
      const sobe = 9;
      for (const [s, e] of recortes(acesa.a0, acesa.a1, 0, Math.PI)) parede(rx, ry, s, e, misturar(acesa.cor, "preto", 0.18), sobe);
      for (const a of [acesa.a0, acesa.a1]) { // cortes laterais da fatia levantada
        const x0 = cx + Math.cos(a) * rx * furo, y0 = cy + Math.sin(a) * ry * furo;
        const x1 = cx + Math.cos(a) * rx, y1 = cy + Math.sin(a) * ry;
        ctx.beginPath();
        ctx.moveTo(x0, y0 - sobe); ctx.lineTo(x1, y1 - sobe); ctx.lineTo(x1, y1); ctx.lineTo(x0, y0);
        ctx.closePath();
        ctx.fillStyle = misturar(acesa.cor, "preto", 0.32);
        ctx.fill();
      }
      tampa(acesa, sobe);
    }

    // percentuais sobre as fatias maiores e total no centro
    if (this.t > 0.7) {
      ctx.globalAlpha = limitar((this.t - 0.7) / 0.3, 0, 1);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = `700 ${rx < 110 ? 11 : 13}px ${FONTE}`;
      for (const f of fatias) {
        if (f.a1 - f.a0 < 0.34) continue;
        const meio = (f.a0 + f.a1) / 2;
        const rr = (1 + furo) / 2;
        ctx.fillStyle = claro(f.cor) ? TINTA : "#fff";
        ctx.fillText(`${fmt(f.pct, 0)}%`, cx + Math.cos(meio) * rx * rr, cy + Math.sin(meio) * ry * rr - (f.chave === this.foco ? 9 : 0));
      }
      if (rx * furo > 34) {
        ctx.fillStyle = TINTA;
        ctx.font = `800 ${Math.round(limitar(rx * 0.17, 14, 26))}px ${FONTE}`;
        ctx.fillText(fmt(this.total, this.casas), cx, cy - 4);
        ctx.fillStyle = TINTA_2;
        ctx.font = `600 11px ${FONTE}`;
        ctx.fillText(this.cfg.rotuloTotal || "total", cx, cy + 13);
      }
      ctx.globalAlpha = 1;
    }
  }
}

// ---------------------------------------------------------------------
// Montagem: gráfico + legenda + tabela de dados
// ---------------------------------------------------------------------
const instancias = new WeakMap();

function legenda(itens) {
  const ul = no("ul", "g3d-legenda");
  for (const it of itens) {
    const li = no("li");
    const cor = no("i", "g3d-cor");
    cor.style.background = it.cor;
    li.append(cor, no("span", "", it.nome));
    if (it.valor !== undefined) li.append(no("b", "", it.valor));
    ul.append(li);
  }
  return ul;
}

function tabela(cabecalho, linhas) {
  const det = no("details", "g3d-dados");
  det.append(no("summary", "", "Ver dados em tabela"));
  const wrap = no("div", "tabela-wrap");
  const t = no("table", "tabela");
  const tr = no("tr");
  cabecalho.forEach((c) => tr.append(no("th", "", c)));
  const thead = no("thead");
  thead.append(tr);
  const tbody = no("tbody");
  for (const l of linhas) {
    const r = no("tr");
    l.forEach((c, i) => r.append(no("td", i ? "num" : "", c)));
    tbody.append(r);
  }
  t.append(thead, tbody);
  wrap.append(t);
  det.append(wrap);
  return det;
}

export function grafico3d(el, cfg) {
  if (typeof el === "string") el = document.getElementById(el);
  if (!el) return null;
  instancias.get(el)?.destruir();
  instancias.delete(el);
  el.replaceChildren();
  el.classList.add("g3d");
  el.classList.toggle("g3d-alto", !!cfg.alto);
  const casas = cfg.casas ?? 1;
  const suf = cfg.sufixo || "";

  let inst;
  if (cfg.tipo === "pizza") {
    const fatias = (cfg.fatias || []).filter((f) => f.valor > 0);
    const total = fatias.reduce((s, f) => s + f.valor, 0);
    if (!total) { el.append(no("div", "vazio", cfg.vazio || "Sem dados no período.")); return null; }
    el.classList.add("g3d-pizza");
    inst = new Pizza3D(el, cfg);
    el.append(
      legenda(fatias.map((f, i) => ({ cor: f.cor || PALETA[i % PALETA.length], nome: f.nome, valor: `${fmt(f.valor, casas)}${suf} (${fmt((f.valor / total) * 100)}%)` }))),
      tabela([cfg.rotuloCategoria || "Categoria", cfg.rotuloValor || "Quantidade", "%"],
        fatias.map((f) => [f.nome, `${fmt(f.valor, casas)}${suf}`, `${fmt((f.valor / total) * 100)}%`])),
    );
  } else {
    const series = cfg.series || [];
    const temDado = series.some((s) => s.valores.some((v) => v > 0));
    if (!cfg.colunas?.length || !temDado) { el.append(no("div", "vazio", cfg.vazio || "Sem dados no período.")); return null; }
    el.classList.remove("g3d-pizza");
    inst = new Barras3D(el, cfg);
    if (cfg.legenda) el.append(legenda(cfg.legenda));
    else if (series.length > 1) el.append(legenda(series.map((s, j) => ({ cor: s.cor || PALETA[j % PALETA.length], nome: s.nome }))));
    el.append(tabela(
      [cfg.rotuloCategoria || "Categoria", ...series.map((s) => s.nome)],
      cfg.colunas.map((c, i) => [c, ...series.map((s) => `${fmt(s.valores[i], casas)}${suf}`)]),
    ));
  }
  el.append(no("p", "g3d-ajuda", "Arraste o gráfico para girar • toque duplo volta à posição inicial"));
  instancias.set(el, inst);
  return inst;
}
