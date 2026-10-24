// Núcleo da ilha: registro de módulos, estados (compacta, aviso, expandida), eventos da assistente.
const icon = window.ORBIT_ICON;
const api = window.orbit;

const Orbit = {
  modules: {},
  cfg: null,
  catalog: window.ORBIT_CATALOG.MODULES,
  friday: { state: 'idle', muted: false, online: false, level: 0 },
  game: { on: false },
  listeners: {},
  mode: 'compact', // compact | banner | expanded
  tab: null,
  pinned: false,

  register(def) { this.modules[def.id] = def; },
  on(type, fn) { (this.listeners[type] ||= []).push(fn); },
  emit(ev) { for (const fn of this.listeners[ev.type] || []) { try { fn(ev); } catch (e) { console.error(e); } } },
  enabled(id) { return !!(this.cfg && this.cfg.modules.enabled[id] && this.modules[id]); },
  order() { return this.cfg.modules.order.filter((id) => this.enabled(id)); },
};

// ---------- Utilidades ----------

function esc(s) { return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
function hhmm(d) { return new Date(d).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }); }
function dayLabel(d) {
  const x = new Date(d), today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((new Date(x).setHours(0, 0, 0, 0) - today) / 86400e3);
  return diff === 0 ? 'Hoje' : diff === 1 ? 'Amanhã' : x.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' });
}
function bytes(n) { const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; while (n >= 1024 && i < 4) { n /= 1024; i++; } return `${n.toFixed(n >= 100 || i === 0 ? 0 : 1)} ${u[i]}`; }
function compact(n) { return n >= 1e9 ? (n / 1e9).toFixed(1) + ' bi' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' mi' : n >= 1e3 ? (n / 1e3).toFixed(1) + ' mil' : String(n); }
function mmss(s) { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(r).padStart(2, '0'); }

// Linha de gráfico simples num canvas (histórico de 0..100).
function sparkline(canvas, values, color) {
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w) return;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext('2d'); g.scale(dpr, dpr);
  const step = w / Math.max(1, values.length - 1);
  const y = (v) => h - 2 - (Math.min(100, v) / 100) * (h - 4);
  g.beginPath(); values.forEach((v, i) => (i ? g.lineTo(i * step, y(v)) : g.moveTo(0, y(v))));
  g.strokeStyle = color; g.lineWidth = 1.6; g.lineJoin = 'round'; g.stroke();
  g.lineTo((values.length - 1) * step, h); g.lineTo(0, h); g.closePath();
  const grad = g.createLinearGradient(0, 0, 0, h); grad.addColorStop(0, color + '55'); grad.addColorStop(1, color + '00');
  g.fillStyle = grad; g.fill();
}

// Som curto gerado (sem arquivos).
function chime(kind = 'soft') {
  if (Orbit.cfg && !Orbit.cfg.island.sounds) return;
  try {
    const ctx = new AudioContext(), now = ctx.currentTime;
    const notes = kind === 'alarm' ? [880, 660, 880, 660, 880] : [740, 988];
    notes.forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0, now + i * 0.16); g.gain.linearRampToValueAtTime(0.18, now + i * 0.16 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, now + i * 0.16 + 0.3);
      o.connect(g).connect(ctx.destination); o.start(now + i * 0.16); o.stop(now + i * 0.16 + 0.32);
    });
    setTimeout(() => ctx.close(), 2000);
  } catch {}
}

// ---------- Tamanho e modos ----------

const $island = document.getElementById('island');
const $banner = document.getElementById('banner');
const $tabs = document.getElementById('tabs');
const $views = document.getElementById('views');
const $left = document.getElementById('c-left');
const $mid = document.getElementById('c-mid');
const $right = document.getElementById('c-right');

let bannerTimer = null, bannerUntil = 0, hovering = false;

// Largura que as abas pedem (a aba aberta mostra o nome): o painel cresce para nenhuma ficar espremida.
function tabsWidth() {
  const tabs = [...$tabs.children].filter((x) => !x.classList.contains('spacer'));
  return tabs.reduce((sum, t) => sum + t.offsetWidth, 0) + 2 * tabs.length + 4 + 24 + 24;
}

function layout() {
  const c = Orbit.cfg.island;
  $island.style.top = c.offsetY + 'px';
  $island.classList.toggle('muted', Orbit.friday.muted);
  $island.className = $island.className.replace(/\b(compact|banner|expanded)\b/g, '').trim() + ' ' + Orbit.mode;
  let w, h, r;
  if (Orbit.mode === 'expanded') { w = Math.min(window.innerWidth - 16, Math.max(c.panelWidth, tabsWidth())); h = c.compactPanel ? 330 : 390; r = 30; }
  else if (Orbit.mode === 'banner') {
    w = 480; r = 26;
    $banner.style.width = w + 'px';
    h = Math.min(190, $banner.scrollHeight + 2);
  } else {
    const live = liveActivity();
    w = live ? (live.width || 330) : 200; h = 34; r = 22;
    if (live && live.id === 'sexta') { h = 46; r = 23; } // cresce um pouco para a onda caber
  }
  $island.style.width = w + 'px'; $island.style.height = h + 'px'; $island.style.borderRadius = r + 'px';
  // O processo principal precisa saber onde a pílula está para aceitar arquivos arrastados (Prateleira).
  const rk = w + 'x' + h + '@' + c.offsetY;
  if (rk !== layout.rk) { layout.rk = rk; api.islandRect({ x: Math.round((window.innerWidth - w) / 2), y: c.offsetY, w, h }); }
  const idle = Orbit.mode === 'compact' && !liveActivity() && Orbit.friday.state === 'idle' && !Orbit.friday.muted && !hovering;
  $island.style.opacity = idle || Orbit.previewIdle ? c.idleOpacity : 1;
  // Modo jogo: a ilha some; só aparece passando o mouse (para sair) ou num aviso liberado.
  if (Orbit.game.on && Orbit.mode === 'compact') $island.style.opacity = hovering ? 0.6 : 0;
}

function setMode(mode) {
  if (Orbit.mode === mode) return;
  const prev = Orbit.mode;
  Orbit.mode = mode;
  api.expanded(mode === 'expanded');
  if (mode === 'expanded') { showTab(Orbit.tab || Orbit.order()[0]); }
  else if (prev === 'expanded') { hideViews(); api.focus(false); }
  layout();
}

function banner(title, text, kind = '', ms) {
  document.getElementById('b-title').textContent = title;
  document.getElementById('b-text').textContent = text;
  if (!Orbit.confirming) document.getElementById('b-actions').innerHTML = '';
  $banner.className = kind;
  const dur = ms || Math.min(15000, 4500 + String(text).length * 45);
  bannerUntil = Date.now() + dur;
  if (Orbit.mode !== 'expanded') setMode('banner');
  layout();
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => { if (Orbit.mode === 'banner' && !hovering) setMode('compact'); }, dur);
}

// ---------- Atividade ao vivo na pílula compacta ----------

// Orbe (anel de energia) e onda 3D de pontos; cores vêm das Configurações.
const orbCv = document.createElement('canvas');
orbCv.className = 'orb';
const wave = document.createElement('canvas');
wave.className = 'wave';
let waveLevel = 0, waveTarget = 0, waveT = 0, waveLast = 0;

function liveActivity() {
  const f = Orbit.friday;
  if (f.state !== 'idle') return { id: 'sexta', width: 310 };
  let best = null;
  for (const id of Orbit.order()) {
    const m = Orbit.modules[id];
    const live = m.live && m.live();
    if (live && (!best || (live.priority || 0) > (best.priority || 0))) best = { ...live, id };
  }
  return best;
}

function renderCompact() {
  const f = Orbit.friday;
  const orbClass = !f.online ? 'offline' : f.muted && f.state === 'idle' ? 'muted' : f.state;
  const live = f.state === 'idle' ? liveActivity() : null;
  let left = '<span data-orb></span>', mid = '', right = hhmm(Date.now());
  if (Orbit.game.on) { left = '<span>🎮</span>'; mid = '<span class="t">Modo jogo · clique para sair</span>'; right = ''; }
  else if (f.state !== 'idle') { mid = '<span data-wave></span>'; right = ''; }
  else if (live) { left = live.left ?? left; mid = live.mid || ''; right = live.right ?? ''; }
  else if (f.muted) mid = '<span class="t" style="color:var(--bad);font-weight:600">Mudo</span>';
  else if (!f.online) mid = '<span class="t">%nome% fora do ar</span>';
  const key = left + '|' + mid + '|' + right;
  if (key !== renderCompact.key) {
    renderCompact.key = key;
    $left.innerHTML = left; $mid.innerHTML = mid; $right.innerHTML = right;
    $left.querySelector('[data-orb]')?.replaceWith(orbCv);
    $mid.querySelector('[data-wave]')?.replaceWith(wave);
  }
  orbCv.dataset.st = orbClass;
  if (!waveRunning) drawOrb();
  layout();
}

// ---- cores ----
const hex = (h) => [1, 3, 5].map((i) => parseInt(String(h).substr(i, 2), 16) || 0);
const mix = (a, b, k) => a.map((v, i) => v + (b[i] - v) * k);
function orbColor(k) {
  const c = Orbit.cfg.island, cs = [c.orbC1, c.orbC2, c.orbC3].map(hex);
  if (c.orbMode === 'solid') return cs[0];
  return k < 0.5 ? mix(cs[0], cs[1], k * 2) : mix(cs[1], cs[2], (k - 0.5) * 2);
}

// Anel de energia: linha principal brilhante e fios ondulando (desenho em shared/orb.js).
function drawOrb() {
  if (!Orbit.cfg) return;
  const st = orbCv.dataset.st || 'idle', dead = st === 'offline', mute = st === 'muted';
  const dpr = window.devicePixelRatio || 1, W = 26;
  if (orbCv.width !== W * dpr) { orbCv.width = orbCv.height = W * dpr; }
  const g = orbCv.getContext('2d'); g.setTransform(dpr * W / 64, 0, 0, dpr * W / 64, 0, 0); g.clearRect(0, 0, 64, 64);
  const C = (k) => { const cc = orbColor(k); if (!mute && !dead) return cc; const m = (cc[0] + cc[1] + cc[2]) / 3; return [m * 0.9, m * 0.9, m]; };
  // Mesmo orbe do app do celular (shared/orb.js): linha principal brilhante e fios que se soltam dela.
  const t = waveT, lv = waveLevel, A = dead ? 0.35 : 1;
  ORBIT_ORB.draw(g, { cx: 32, cy: 32, R: 19 * (1 + lv * 0.1), t, alpha: A, blur: dpr * W / 64,
    energy: 0.8 + lv * 1.6 + (st === 'thinking' ? 0.5 : 0), colors: [0, 0.5, 1].map((k) => `rgb(${C(k)})`) });
  if (mute) { g.strokeStyle = '#ff5a5a'; g.lineWidth = 4; g.beginPath(); g.moveTo(18, 46); g.lineTo(46, 18); g.stroke(); }
}

// Superfície 3D de pontos: linhas em profundidade, projetadas em perspectiva.
function drawSurface() {
  const dpr = window.devicePixelRatio || 1, W = 190, H = 42;
  if (wave.width !== W * dpr) { wave.width = W * dpr; wave.height = H * dpr; }
  const g = wave.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  g.globalCompositeOperation = 'lighter';
  const t = waveT, amp = Orbit.friday.state === 'thinking' ? 0.8 : 0.3 + waveLevel * 2.6;
  for (let r = 0; r < 14; r++) {
    const z = r / 13, p = 1 / (1 + z * 1.6);
    for (let i = 0; i < 64; i++) {
      const u = i / 63, fade = Math.sin(u * Math.PI) ** 1.2;
      const h = (Math.sin(u * 7 + t * 1.7 + z * 2.4) * 0.6 + Math.sin(u * 3.3 - t * 1.1 + z * 4) * 0.5 + Math.sin(u * 13 + t * 2.6 - z * 3) * 0.18) * amp * fade;
      const x = W / 2 + (u - 0.5) * W * (0.62 + 0.38 * p);
      const y = H * 0.5 + (z - 0.5) * H * 0.28 * p - Math.tanh(h) * H * 0.32 * p; // tanh: nunca passa da borda
      const a = Math.min(1, (0.25 + 0.75 * p) * (0.35 + 0.65 * fade) * (0.55 + Math.max(0, h) * 0.6));
      g.fillStyle = `rgba(${orbColor(Math.min(1, u * 0.7 + z * 0.5))},${a})`;
      const s = 0.5 + p * 0.7; g.fillRect(x, y, s, s);
    }
  }
  g.globalCompositeOperation = 'source-over';
}

// Só anima enquanto ela ouve, pensa ou fala; parada, desenha uma vez e para.
let waveRunning = false;
function drawWave(now) {
  const s = Orbit.friday.state;
  if (s === 'idle' || !Orbit.cfg) { waveRunning = false; waveLast = 0; waveLevel = 0; drawOrb(); return; }
  if (Orbit.cfg.island.lite) { waveRunning = false; waveLevel = 0.3; drawOrb(); drawSurface(); return; } // modo leve: um quadro só
  if (!waveRunning) { waveRunning = true; requestAnimationFrame(drawWave); return; }
  requestAnimationFrame(drawWave);
  const dt = Math.min(0.05, (now - (waveLast || now)) / 1000); waveLast = now; waveT += dt;
  waveLevel += (waveTarget - waveLevel) * (1 - Math.exp(-dt * 12)); waveTarget *= Math.exp(-dt * 3);
  drawOrb(); drawSurface();
}

// ---------- Abas e módulos ----------

const mounted = {};

function buildTabs() {
  $tabs.innerHTML = '';
  for (const id of Orbit.order()) {
    const meta = Orbit.catalog.find((m) => m.id === id);
    const b = el(`<button class="tab" data-id="${id}" title="${esc(meta.name)}">${icon(meta.icon, 17)}<span class="lbl">${esc(meta.name)}</span></button>`);
    b.onclick = () => showTab(id);
    $tabs.appendChild(b);
  }
  $tabs.appendChild(el('<span class="spacer"></span>'));
  const pin = el(`<button class="tab" id="pin-btn" title="Fixar aberta">${icon('pin', 16)}</button>`);
  pin.onclick = () => setPinned(!Orbit.pinned);
  const gear = el(`<button class="tab" title="Configurações">${icon('gear', 16)}</button>`);
  gear.onclick = () => api.openSettings();
  $tabs.append(pin, gear);
  setPinned(Orbit.pinned);
  if (Orbit.mode === 'expanded') showTab(Orbit.order().includes(Orbit.tab) ? Orbit.tab : Orbit.order()[0]);
}

// O ícone do alfinete sempre mostra o estado real (o Esc também solta).
function setPinned(on) {
  Orbit.pinned = on;
  const b = document.getElementById('pin-btn');
  if (b) b.classList.toggle('pinned', on);
}

function showTab(id) {
  if (!id) return;
  for (const [mid, m] of Object.entries(mounted)) if (mid !== id && m.visible) { m.visible = false; m.view.classList.remove('on'); Orbit.modules[mid].hide?.(); }
  Orbit.tab = id;
  for (const b of $tabs.querySelectorAll('.tab[data-id]')) b.classList.toggle('on', b.dataset.id === id);
  if (!mounted[id]) {
    const view = el(`<div class="view" data-id="${id}"></div>`);
    $views.appendChild(view);
    mounted[id] = { view, visible: false };
    Orbit.modules[id].mount(view);
  }
  const m = mounted[id];
  if (!m.visible) { m.visible = true; m.view.classList.add('on'); Orbit.modules[id].show?.(); }
  layout(); // o nome da aba aberta muda a largura que as abas precisam
}

function hideViews() {
  for (const [id, m] of Object.entries(mounted)) if (m.visible) { m.visible = false; m.view.classList.remove('on'); Orbit.modules[id].hide?.(); }
}

// Mensagem padrão quando uma aba não consegue os dados (em vez de "Carregando…" para sempre).
function failNote(what) {
  return `<div class="empty">${!Orbit.friday.online ? '%A% está fora do ar; reconectando…' : `Não consegui carregar ${what}.`}
    <div style="margin-top:10px"><button class="btn" data-retry>Tentar de novo</button></div></div>`;
}
$views.addEventListener('click', (e) => {
  if (!e.target.closest('[data-retry]')) return;
  const m = Orbit.modules[Orbit.tab];
  m && m.show && m.show();
});

// Módulos chamam isto para pedir a ilha aberta numa aba (ex.: timer acabou).
Orbit.open = (id) => { Orbit.tab = id; setMode('expanded'); showTab(id); };
Orbit.banner = banner;
