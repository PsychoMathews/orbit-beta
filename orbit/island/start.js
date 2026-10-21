// Liga tudo: configuração, módulos, eventos da assistente e o mouse (abrir ao passar, clique-através fora da ilha).
const started = new Set();

function startModules() {
  for (const id of Orbit.order()) {
    if (started.has(id)) continue;
    started.add(id);
    try { Orbit.modules[id].start?.(); } catch (e) { console.error(id, e); }
  }
}

function applyConfig(cfg) {
  Orbit.cfg = cfg;
  // Cores da assistente viram variáveis CSS (botões, ponto do aviso, orbe da aba).
  const c = cfg.island, solid = c.orbMode === 'solid', rs = document.documentElement.style;
  rs.setProperty('--orb1', c.orbC1);
  rs.setProperty('--orb-grad', solid ? c.orbC1 : `linear-gradient(135deg, ${c.orbC1}, ${c.orbC2} 55%, ${c.orbC3})`);
  rs.setProperty('--orb-ring', solid ? c.orbC1 : `conic-gradient(${c.orbC1}, ${c.orbC2}, ${c.orbC3}, ${c.orbC1})`);
  document.documentElement.classList.toggle('lite', !!c.lite);
  document.documentElement.classList.toggle('cpanel', !!c.compactPanel);
  startModules();
  buildTabs();
  renderCompact();
}

// ---------- Eventos da assistente ----------

let pendingReply = null;

api.onEvent((ev) => {
  const f = Orbit.friday;
  switch (ev.type) {
    case 'hello': if (ev.assistente) window.ORBIT_SET_ASSIST(ev.assistente); f.online = true; f.state = ev.state; f.muted = ev.muted; break;
    case 'online': f.online = true; break;
    case 'offline': f.online = false; f.state = 'idle'; break;
    case 'state':
      f.state = ev.state; if (!waveRunning) drawWave();
      if (ev.state === 'idle' && pendingReply) { const t = pendingReply; pendingReply = null; setTimeout(() => banner('%nome%', t), 250); }
      break;
    case 'beat': Orbit.modules.midia?.onEvent(ev); return; // 15x/s: só mexe nas barrinhas, sem redesenhar a ilha
    case 'level': waveTarget = Math.min(1, Math.sqrt(ev.value) * 1.3); return; // raiz: voz baixa também mexe
    case 'gamemode':
      if (Orbit.game.on !== ev.on) banner(ev.on ? '🎮 Modo jogo' : '🎮 Modo jogo desligado', ev.on ? 'Não escuto nem falo pelo PC. Só passam lembretes, reuniões e timers.' : 'Tudo de volta ao normal.', '', 3500);
      Orbit.game = ev;
      break;
    case 'mute':
      f.muted = ev.muted;
      banner(ev.muted ? 'Mudo' : 'Som ligado', ev.muted ? 'Atalho e voz no PC desligados. Telegram e Alexa seguem normais.' : 'Pode falar comigo de novo.', ev.muted ? 'bad' : '', 2600);
      break;
    case 'reply':
      // Enquanto ela pensa/fala, a pílula mostra a onda; o texto aparece quando ela termina.
      if (Orbit.mode === 'expanded' && Orbit.tab === 'sexta') break;
      if (f.state !== 'idle') pendingReply = ev.text; else banner('%nome%', ev.text);
      break;
    case 'notify':
      if (ev.kind === 'timer') { chime('alarm'); setTimeout(() => chime('alarm'), 1400); banner('⏱️ Timer', ev.text, 'warn', 12000); break; }
      chime(); banner(ev.kind === 'claude' || ev.kind === 'claude_done' ? 'Claude' : 'Aviso', ev.text, ev.kind === 'error' || ev.kind === 'mute' ? 'bad' : 'warn'); break;
    case 'show': chime(); banner(ev.title || '%nome%', ev.text); break;
    case 'confirm': askConfirm(ev); break;
    case 'confirm_done': confirmDone(ev); break;
  }
  for (const id of Object.keys(Orbit.modules)) {
    if (!Orbit.enabled(id)) continue;
    const m = Orbit.modules[id];
    try { m.onEvent?.(ev); if (['hello', 'online', 'offline', 'state', 'mute', 'heard', 'reply', 'notify', 'show'].includes(ev.type)) m.onFriday?.(ev); } catch (e) { console.error(e); }
  }
  if (ev.type === 'online' && Orbit.mode === 'expanded' && Orbit.tab) {
    const m = Orbit.modules[Orbit.tab];
    m && m.show && m.show();
  }
  renderCompact();
});

// ---------- Confirmar ações pela ilha (o mesmo pedido do botão do Telegram; vale o primeiro clique) ----------

const confirmQueue = [];
function askConfirm(c) {
  if (!confirmQueue.some((x) => x.id === c.id)) confirmQueue.push(c);
  if (confirmQueue[0].id === c.id) showConfirm();
}
function showConfirm() {
  const c = confirmQueue[0];
  if (!c) { Orbit.confirming = false; return; }
  Orbit.confirming = true;
  chime();
  banner('Confirmar?', c.summary, 'warn', 120000);
  setTimeout(() => { if (confirmQueue[0] === c) Orbit.confirming = false; }, 120000); // o aviso some; o Telegram continua valendo
  const btns = `<button class="btn primary" data-c="1">Confirmar</button><button class="btn" data-c="0">Cancelar</button>
    ${confirmQueue.length > 1 ? `<span class="faint">+${confirmQueue.length - 1} na fila</span>` : ''}`;
  // Aparece no aviso (ilha fechada) e no topo do painel (ilha aberta): os dois valem.
  const box = document.getElementById('b-actions'), bar = document.getElementById('cbar');
  box.innerHTML = btns;
  bar.innerHTML = `<span class="b-dot" style="background:var(--warn)"></span><span class="ellipsis" style="flex:1">${esc(c.summary)}</span>${btns}`;
  bar.onclick = box.onclick = async (e) => {
    const b = e.target.closest('[data-c]');
    e.stopPropagation();
    if (!b || b.disabled) return;
    [box, bar].forEach((el) => el.querySelectorAll('button').forEach((x) => { x.disabled = true; }));
    b.innerHTML = '<i class="spin"></i>';
    const r = await api.post('/orbit/confirm', { id: c.id, ok: b.dataset.c === '1' });
    finishConfirm(c.id, r ? r.msg : '%A% está fora do ar.', !r);
  };
}
function confirmDone(ev) { if (confirmQueue.some((x) => x.id === ev.id)) finishConfirm(ev.id, ev.result, !ev.ok && ev.result !== 'Cancelado.'); }
function finishConfirm(id, msg, bad) {
  const i = confirmQueue.findIndex((x) => x.id === id);
  if (i < 0) return;
  const was = i === 0;
  confirmQueue.splice(i, 1);
  if (!was) return;
  document.getElementById('b-actions').innerHTML = '';
  document.getElementById('cbar').innerHTML = '';
  Orbit.confirming = false;
  banner(bad ? 'Não deu certo' : 'Feito', msg || 'Feito.', bad ? 'bad' : '', 3500);
  if (confirmQueue.length) setTimeout(showConfirm, 3600);
}
// Pedidos que já estavam esperando quando a ilha abriu.
api.get('/orbit/pending').then((r) => (r && r.pending || []).forEach(askConfirm));

// ---------- Mouse ----------

let hoverTimer = null, leaveTimer = null, gameTimer = null;

function setHover(on) {
  if (on === hovering) return;
  hovering = on;
  clearTimeout(hoverTimer); clearTimeout(leaveTimer); clearTimeout(gameTimer);
  // Modo jogo: o clique só é capturado depois de ~0,9 s parado em cima, para não roubar cliques do jogo.
  if (on && Orbit.game.on) gameTimer = setTimeout(() => { if (hovering) { api.interactive(true); layout(); } }, 900);
  else api.interactive(on);
  const c = Orbit.cfg.island;
  if (on) {
    if (c.expandOnHover && !Orbit.game.on) hoverTimer = setTimeout(() => setMode('expanded'), c.hoverDelay);
  } else {
    leaveTimer = setTimeout(collapseIfIdle, c.collapseDelay);
  }
  layout();
}

function collapseIfIdle() {
  if (hovering || Orbit.pinned) return;
  const typing = document.activeElement && /INPUT|TEXTAREA/.test(document.activeElement.tagName) && document.activeElement.value;
  if (typing) return;
  setMode(Date.now() < bannerUntil ? 'banner' : 'compact');
}

// Com setIgnoreMouseEvents(forward) o movimento chega mesmo quando o clique atravessa a janela.
document.addEventListener('mousemove', (e) => setHover(!!e.target.closest('#island')));
document.addEventListener('mouseleave', () => setHover(false));
api.onCursorOut(() => setHover(false)); // o processo principal viu o cursor sair (plano B do mouseleave)
window.addEventListener('blur', () => setTimeout(collapseIfIdle, 50));

document.getElementById('compact').addEventListener('click', () => {
  if (Orbit.game.on) { api.post('/orbit/gamemode', { on: false }); return; }
  setMode(Orbit.mode === 'expanded' ? 'compact' : 'expanded');
});
document.getElementById('banner').addEventListener('click', () => { bannerUntil = 0; setMode('expanded'); showTab(Orbit.enabled('avisos') ? 'avisos' : Orbit.order()[0]); });
$island.addEventListener('contextmenu', (e) => { e.preventDefault(); api.menu(); });
function escape() { setPinned(false); document.activeElement?.blur(); setMode(Date.now() < bannerUntil ? 'banner' : 'compact'); }
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') escape(); });
api.onEscape(escape);

// ---------- Início ----------

api.onConfig(applyConfig);
let previewTimer = null;
api.onPreview((kind) => {
  clearTimeout(previewTimer);
  if (kind === 'idle') {
    // Opacidade "parada": mostra a pílula como fica sem nada acontecendo, por alguns segundos.
    Orbit.previewIdle = true;
    setMode('compact'); renderCompact();
    previewTimer = setTimeout(() => { Orbit.previewIdle = false; renderCompact(); }, 3000);
    return;
  }
  setMode('expanded');
  previewTimer = setTimeout(collapseIfIdle, 2500);
});
api.onTheme((t) => { document.documentElement.dataset.theme = t; });
api.get('/orbit/gamemode').then((g) => { if (g) { Orbit.game = g; renderCompact(); } });
api.configGet().then(async ({ config }) => {
  applyConfig(config);
  const st = await api.status();
  if (st.assistente) window.ORBIT_SET_ASSIST(st.assistente);
  Object.assign(Orbit.friday, st);
  for (const id of Object.keys(Orbit.modules)) if (Orbit.enabled(id)) Orbit.modules[id].onFriday?.({ type: 'hello' });
  renderCompact();
  drawWave();
  setInterval(renderCompact, 1000); // relógio e contagens
});
