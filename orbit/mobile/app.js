// Orbit no celular: conversa com a assistente, avisos (push) e o que a ilha mostra no PC.
const icon = window.ORBIT_ICON;
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const hhmm = (t) => new Date(t).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
const bytes = (n) => { const u = ['B', 'KB', 'MB', 'GB']; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return `${n.toFixed(n >= 100 || !i ? 0 : 1)} ${u[i]}`; };
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
const standalone = navigator.standalone || matchMedia('(display-mode: standalone)').matches;

let me = { assistente: { nome: 'Orbit' } };
const nome = () => me.assistente?.nome || 'Orbit';

async function api(path, opts = {}) {
  const init = { credentials: 'same-origin', ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.json !== undefined) { init.method = init.method || 'POST'; init.body = JSON.stringify(opts.json); init.headers['Content-Type'] = 'application/json'; }
  const r = await fetch('/api' + path, init);
  if (r.status === 401) { showPair(); throw new Error('não pareado'); }
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
const post = (path, json = {}) => api(path, { json });

function toast(text, ms = 2600) {
  const t = $('#toast'); t.textContent = text; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms);
}

// ---------- Abas ----------
const MAIN = ['sexta', 'agenda', 'lembretes', 'midia', 'mais'];
const V = {};
let current = null;

function view(def) { V[def.id] = def; }

function go(id) {
  if (!V[id]) id = 'sexta';
  const prev = V[current];
  if (prev && prev.el && prev !== V[id]) {
    const old = prev.el; old.classList.remove('on'); old.classList.add('leaving'); prev.hide?.();
    setTimeout(() => old.classList.remove('leaving'), 260);
  }
  const v = V[id];
  if (!v.el) { v.el = document.createElement('section'); v.el.className = 'view'; v.el.dataset.id = id; $('#views').append(v.el); v.mount(v.el); }
  v.el.classList.add('on'); current = id;
  $('#title').textContent = id === 'sexta' ? nome() : v.title;
  const tab = MAIN.includes(id) ? id : 'mais';
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.id === tab));
  history.replaceState(null, '', '#' + id);
  rise(v.el);
  Promise.resolve(v.show?.()).then(() => rise(v.el));
}

// Entrada em cascata (como os cartões da referência) e números que contam até o valor.
const RISE = '.card, .item, .tile, .sec, .msg';
function rise(el, only) {
  const items = only ? [only] : [...el.querySelectorAll(RISE)].filter((x) => !x.parentElement.closest('.card, .item'));
  items.forEach((x, i) => { x.classList.remove('rise'); void x.offsetWidth; x.style.setProperty('--i', Math.min(i, 12)); x.classList.add('rise'); });
  el.querySelectorAll('[data-count]').forEach(countUp);
}
function countUp(n) {
  const to = parseFloat(n.dataset.count), t0 = performance.now(), dur = 700;
  delete n.dataset.count;
  const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); n.textContent = Math.round(to * e); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}

function buildTabs() {
  $('#tabs').innerHTML = MAIN.map((id) => `<button data-id="${id}">${icon(V[id].icon, 24)}<span>${id === 'sexta' ? esc(nome()) : V[id].title}</span></button>`).join('');
  $('#tabs').onclick = (e) => { const b = e.target.closest('button'); if (b) go(b.dataset.id); };
}

const back = () => `<button class="back" data-back>${icon('left', 18)} Mais</button>`;
function wireBack(el) { el.querySelector('[data-back]')?.addEventListener('click', () => go('mais')); }

// ---------- Conversa ----------
view({
  id: 'sexta', title: 'Conversa', icon: 'spark',
  log: store.get('orbit.chat', []),
  mount(el) {
    el.innerHTML = `<div id="chat"></div>
      <div id="composer">
        <input class="input" id="say" placeholder="Fale com %nome%…" enterkeyhint="send" autocomplete="off">
        <button class="btn round" id="send">${icon('send', 20)}</button>
        <button class="btn round tint" id="mic">${icon('mic', 22)}</button>
      </div>`;
    $('#say').placeholder = `Escreva para ${nome()}…`;
    $('#say').onkeydown = (e) => { if (e.key === 'Enter') this.send(); };
    $('#send').onclick = () => this.send();
    $('#mic').onclick = () => this.mic();
    this.render();
  },
  show() { this.scroll(); },
  add(m) {
    this.log = [...this.log, m].slice(-80); store.set('orbit.chat', this.log.filter((x) => !x.wait)); this.render();
    const last = $('#chat')?.lastElementChild; if (last) rise(last.parentElement, last);
  },
  render() {
    const chat = $('#chat'); if (!chat) return;
    chat.innerHTML = this.log.length ? this.log.map((m, i) => `<div class="msg ${m.who}${m.wait ? ' wait' : ''}">${esc(m.text)}${
      (m.pending || []).map((p) => `<div class="faint" style="margin-top:8px">${esc(p.summary)}</div><div class="acts">
        <button class="btn primary" data-ok="${p.id}" data-i="${i}">Confirmar</button><button class="btn" data-no="${p.id}" data-i="${i}">Cancelar</button></div>`).join('')}</div>`).join('')
      : `<div class="empty">Fale ou escreva para ${esc(nome())}.<br>Ela responde aqui, com a mesma memória do PC.</div>`;
    chat.onclick = async (e) => {
      const b = e.target.closest('[data-ok],[data-no]'); if (!b) return;
      const ok = !!b.dataset.ok, id = b.dataset.ok || b.dataset.no;
      const r = await post('/confirm', { id, ok }).catch(() => ({ msg: 'Falhou.' }));
      const m = this.log[+b.dataset.i]; m.pending = []; this.add({ who: 'ai', text: r.msg || (ok ? 'Feito.' : 'Cancelado.') });
    };
    this.scroll();
  },
  scroll() { const el = V.sexta.el; if (el) requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; }); },
  async send() {
    const inp = $('#say'), text = inp.value.trim(); if (!text) return;
    inp.value = ''; inp.blur();
    this.add({ who: 'me', text });
    await this.ask(() => post('/ask', { text }));
  },
  async ask(fn) {
    this.add({ who: 'ai', text: 'Pensando…', wait: true }); island.set('thinking');
    let r;
    try { r = await fn(); } catch (e) { r = { ok: false, erro: 'Não consegui falar com o PC. Ele está ligado?' }; }
    this.log = this.log.filter((m) => !m.wait); island.set('idle');
    if (r.heard) this.add({ who: 'me', text: r.heard });
    this.add({ who: 'ai', text: r.ok ? r.reply || '(sem resposta)' : r.erro || 'Deu erro.', pending: r.pending });
    if (r.audio) island.speak('data:audio/mpeg;base64,' + r.audio);
  },
  // Toque para gravar, toque de novo para enviar.
  async mic() {
    const btn = $('#mic');
    island.unlock(); // o iPhone só libera áudio depois de um toque
    if (this.rec) { this.rec.stop(); return; }
    if (!window.MediaRecorder) return toast('Este navegador não grava áudio.');
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return toast('Sem acesso ao microfone.'); }
    const type = ['audio/mp4', 'audio/webm'].find((t) => MediaRecorder.isTypeSupported(t)) || '';
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined), parts = [];
    rec.ondataavailable = (e) => e.data.size && parts.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop()); btn.classList.remove('rec'); this.rec = null; island.listen(null);
      const blob = new Blob(parts, { type: rec.mimeType || type });
      if (blob.size < 2000) return toast('Áudio muito curto.');
      this.ask(() => api('/voice', { method: 'POST', body: blob, headers: { 'Content-Type': blob.type || 'application/octet-stream' } }));
    };
    rec.start(); this.rec = rec; btn.classList.add('rec'); island.listen(stream);
  },
});
// ---------- Pílula (a ilha dentro do app): orbe, estado e a onda de som da voz ----------
const island = {
  st: 'idle', ac: null, an: null, pc: false,
  ctx() {
    if (!this.ac) { const AC = window.AudioContext || window.webkitAudioContext; this.ac = new AC(); this.an = this.ac.createAnalyser(); this.an.fftSize = 64; }
    return this.ac;
  },
  unlock() {
    const ac = this.ctx(); if (ac.state === 'suspended') ac.resume();
    if (!this.player) {
      this.player = new Audio(); this.player.playsInline = true;
      const src = ac.createMediaElementSource(this.player); src.connect(this.an); src.connect(ac.destination);
    }
  },
  set(st, text) {
    this.st = st;
    const lab = { listening: 'Ouvindo', thinking: 'Pensando', speaking: 'Falando' };
    $('#pill').className = st === 'idle' ? '' : 'open ' + st;
    $('#pill-text').textContent = st === 'idle' ? nome() : text || lab[st] || '';
    $('#orb').className = 'ring ' + st;
    if (st !== 'idle') this.loop();
  },
  listen(stream) {
    if (this.mic) { this.mic.disconnect(); this.mic = null; }
    if (!stream) { if (this.st === 'listening') this.set('idle'); return; }
    this.ctx(); this.mic = this.ac.createMediaStreamSource(stream); this.mic.connect(this.an); this.set('listening');
  },
  speak(url) {
    this.unlock(); this.player.src = url; this.player.play().catch(() => {});
    this.set('speaking'); this.player.onended = () => this.set('idle');
  },
  // Barras finas a cada quadro: nível real do microfone ou da voz dela; pensando, uma onda calma.
  loop() {
    if (this.running) return; this.running = true;
    const cv = $('#wave'), g = cv.getContext('2d'), N = 16, data = new Uint8Array(32);
    const draw = (t) => {
      if (this.st === 'idle') { this.running = false; g.clearRect(0, 0, cv.width, cv.height); return; }
      const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
      if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
      g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
      const real = this.st !== 'thinking' && !this.pc && this.an;
      if (real) this.an.getByteFrequencyData(data);
      const cs = getComputedStyle(document.documentElement), grad = g.createLinearGradient(0, 0, W, 0);
      grad.addColorStop(0, cs.getPropertyValue('--accent').trim()); grad.addColorStop(1, cs.getPropertyValue('--accent2').trim());
      g.fillStyle = grad;
      for (let i = 0; i < N; i++) {
        const v = real ? data[2 + i] / 255 : 0.3 + 0.22 * Math.sin(t / 240 + i * 0.7) * Math.sin(t / 900 + i);
        const h = Math.max(3, Math.min(H, v * H * 1.2)), x = (i + 0.5) * (W / N) - 1.25;
        g.beginPath(); g.roundRect(x, (H - h) / 2, 2.5, h, 1.25); g.fill();
      }
      requestAnimationFrame(draw);
    };
    requestAnimationFrame(draw);
  },
};

// ---------- Agenda ----------
const dayLabel = (d) => {
  const t = new Date(); t.setHours(0, 0, 0, 0); const x = new Date(d); x.setHours(0, 0, 0, 0);
  const n = Math.round((x - t) / 864e5);
  return n === 0 ? 'Hoje' : n === 1 ? 'Amanhã' : x.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: '2-digit' });
};
view({
  id: 'agenda', title: 'Agenda', icon: 'calendar',
  mount(el) { el.innerHTML = '<div data-body><div class="empty">Carregando…</div></div>'; },
  async show() {
    const body = $('[data-body]', this.el);
    try {
      const d = await api('/agenda');
      if (!d.connected) { body.innerHTML = '<div class="empty">Agenda Google não conectada no PC.</div>'; return; }
      if (!d.events.length) { body.innerHTML = '<div class="empty">Nada na agenda hoje e amanhã.</div>'; return; }
      let html = '', last = '';
      for (const e of d.events) {
        const allDay = !String(e.start).includes('T'), lab = dayLabel(allDay ? e.start + 'T12:00' : e.start);
        if (lab !== last) { html += `<div class="sec">${esc(lab)}</div>`; last = lab; }
        html += `<div class="item"><span class="when">${allDay ? 'dia' : hhmm(e.start)}</span><div class="grow"><div class="ellipsis" style="${e.done ? 'text-decoration:line-through;opacity:.5' : ''}">${esc(e.title)}</div>
          ${e.where ? `<div class="faint ellipsis">${esc(e.where)}</div>` : ''}</div>
          ${e.link ? `<a class="btn" href="${esc(e.link)}" target="_blank" rel="noopener">Entrar</a>` : ''}</div>`;
      }
      body.innerHTML = html;
    } catch { body.innerHTML = '<div class="empty">Não consegui buscar a agenda.</div>'; }
  },
});

// ---------- Lembretes ----------
view({
  id: 'lembretes', title: 'Lembretes', icon: 'bell',
  mount(el) {
    el.innerHTML = `<div class="card" style="display:flex;flex-direction:column;gap:10px;margin-bottom:6px">
        <input class="input" id="rm-text" placeholder="Lembrar de…">
        <div class="row"><input class="input" id="rm-when" type="datetime-local"><button class="btn primary" id="rm-add">Criar</button></div>
        <div class="row" style="flex-wrap:wrap">${[[15, '15 min'], [60, '1 h'], [180, '3 h']].map(([m, l]) => `<button class="chip" data-in="${m}">em ${l}</button>`).join('')}<button class="chip" data-tomorrow>amanhã 9h</button></div>
      </div><div data-body></div>`;
    const setWhen = (d) => { const p = (n) => String(n).padStart(2, '0'); $('#rm-when').value = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
    el.querySelectorAll('[data-in]').forEach((b) => b.onclick = () => setWhen(new Date(Date.now() + b.dataset.in * 6e4)));
    $('[data-tomorrow]', el).onclick = () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); setWhen(d); };
    $('#rm-add').onclick = async () => {
      const text = $('#rm-text').value.trim(), when = $('#rm-when').value;
      if (!text || !when) return toast('Escreva o lembrete e escolha quando.');
      const r = await post('/reminders/add', { text, when }).catch(() => null);
      toast(r?.msg || 'Não consegui criar.'); $('#rm-text').value = ''; this.show();
    };
  },
  async show() {
    const body = $('[data-body]', this.el);
    try {
      const { reminders } = await api('/reminders');
      body.innerHTML = reminders.length ? '<div class="sec">Pendentes</div><div class="list">' + reminders.map((r, i) => `<div class="item">
        <span class="well">${icon('bell', 18)}</span><div class="grow"><div>${esc(r.text)}</div><div class="faint">${esc(dayLabel(r.when))} · ${hhmm(r.when)}</div></div>
        <button class="btn round" data-x="${i}">${icon('x', 16)}</button></div>`).join('') + '</div>' : '<div class="empty">Nenhum lembrete pendente.</div>';
      body.onclick = async (e) => {
        const b = e.target.closest('[data-x]'); if (!b) return;
        const r = await post('/reminders/cancel', { text: reminders[+b.dataset.x].text }).catch(() => null);
        toast(r?.msg || 'Não consegui cancelar.'); this.show();
      };
    } catch { body.innerHTML = '<div class="empty">Não consegui buscar os lembretes.</div>'; }
  },
});

// ---------- Música (o que toca no PC) ----------
view({
  id: 'midia', title: 'Música', icon: 'music',
  mount(el) { el.innerHTML = '<div data-body><div class="empty">Carregando…</div></div>'; },
  show() { this.load(); clearInterval(this.t); this.t = setInterval(() => this.load(), 3000); },
  hide() { clearInterval(this.t); },
  async load() {
    const body = $('[data-body]', this.el);
    let m; try { m = await api('/media'); } catch { body.innerHTML = '<div class="empty">Sem conexão com o PC.</div>'; return; }
    this.m = m;
    if (!m.title) { body.innerHTML = '<div class="empty">Nada tocando no PC.</div>'; return; }
    const pct = m.duration ? Math.min(100, (m.position / m.duration) * 100) : 0;
    body.innerHTML = `<div class="card"><div class="row" style="margin-bottom:14px"><span class="label" style="flex:1">Tocando no PC</span>${m.playing ? '<span class="live">AO VIVO</span>' : '<span class="label">Pausado</span>'}</div>
      ${m.art ? `<img class="art" src="${m.art}" alt="">` : ''}
      <div style="margin-top:16px"><div style="font-size:19px;font-weight:600">${esc(m.title)}</div><div class="dim">${esc(m.artist || m.app)}</div></div>
      <div class="bar" style="margin-top:16px"><i style="width:${pct}%"></i></div>
      <div class="controls">
        <button class="btn round" data-a="previous">${icon('prev', 22)}</button>
        <button class="btn round big primary" data-a="play_pause">${icon(m.playing ? 'pause' : 'play', 28)}</button>
        <button class="btn round" data-a="next">${icon('next', 22)}</button></div></div>`;
    body.onclick = async (e) => {
      const b = e.target.closest('[data-a]'); if (!b) return;
      await post('/media/' + b.dataset.a, { id: this.m.id }).catch(() => {}); setTimeout(() => this.load(), 400);
    };
  },
});

// ---------- Som (volume do PC) ----------
view({
  id: 'som', title: 'Som', icon: 'volUp',
  mount(el) { el.innerHTML = back() + '<div data-body><div class="empty">Carregando…</div></div>'; wireBack(el); },
  async show() {
    const body = $('[data-body]', this.el);
    let d; try { d = await api('/audio'); } catch { body.innerHTML = '<div class="empty">Sem conexão com o PC.</div>'; return; }
    const row = (id, name, vol, muted) => `<div class="card" style="margin-bottom:10px;padding:14px 16px"><div class="row" style="gap:14px">
      <button class="well" data-mute="${id}" style="${muted ? 'color:var(--bad)' : ''}">${icon(muted ? 'volDown' : 'volUp', 18)}</button>
      <div style="flex:1;min-width:0"><div class="ellipsis" style="font-weight:600">${esc(name)}</div><div class="label" style="font-size:9.5px">${muted ? 'Mudo' : 'Volume'}</div></div>
      <span style="font-size:24px;font-weight:500;letter-spacing:-.5px" data-num="${id}">${vol}</span></div>
      <input type="range" min="0" max="100" value="${vol}" data-vol="${id}" style="--v:${vol}%;margin-top:6px"></div>`;
    body.innerHTML = `<div class="sec">${esc(d.device || 'Saída')}</div>` + row('master', 'Volume geral', d.master, d.masterMuted)
      + '<div class="sec">Programas</div>' + d.apps.map((a) => row(a.id, a.name, a.volume, a.muted)).join('');
    let t;
    body.oninput = (e) => {
      const r = e.target.closest('[data-vol]'); if (!r) return;
      r.style.setProperty('--v', r.value + '%'); const n = body.querySelector(`[data-num="${r.dataset.vol}"]`); if (n) n.textContent = r.value;
      clearTimeout(t); t = setTimeout(() => post('/audio', { app: r.dataset.vol, volume: +r.value }).catch(() => {}), 150); };
    body.onclick = async (e) => {
      const b = e.target.closest('[data-mute]'); if (!b) return;
      const id = b.dataset.mute, cur = id === 'master' ? d.masterMuted : d.apps.find((a) => a.id === id)?.muted;
      await post('/audio', { app: id, mute: !cur }).catch(() => {}); this.show();
    };
  },
});

// ---------- Timer ----------
view({
  id: 'timer', title: 'Timer', icon: 'timer',
  timers: [],
  mount(el) {
    el.innerHTML = back() + `<div class="grid" style="margin-bottom:10px">${[5, 10, 15, 25, 45, 60].map((m) => `<button class="tile" data-m="${m}">${m} min</button>`).join('')}</div>
      <div class="row"><input class="input" id="tm-min" type="number" inputmode="decimal" placeholder="Minutos"><input class="input" id="tm-label" placeholder="Nome (opcional)"><button class="btn primary" id="tm-go">Iniciar</button></div>
      <div data-body style="margin-top:14px"></div>`;
    wireBack(el);
    const start = async (m, label) => { const r = await post('/timers/start', { minutes: m, label: label || 'Timer' }).catch(() => null); if (r) { this.timers = r.timers; this.render(); toast(r.msg); } };
    el.querySelectorAll('[data-m]').forEach((b) => b.onclick = () => start(+b.dataset.m));
    $('#tm-go').onclick = () => { const m = parseFloat($('#tm-min').value); if (m > 0) start(m, $('#tm-label').value.trim()); };
  },
  async show() { try { this.timers = (await api('/timers')).timers; } catch {} this.render(); clearInterval(this.t); this.t = setInterval(() => this.render(), 1000); },
  hide() { clearInterval(this.t); },
  render() {
    const body = this.el && $('[data-body]', this.el); if (!body) return;
    const left = (t) => Math.max(0, Math.round(t.paused != null ? t.paused : t.end - Date.now() / 1000));
    const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    body.innerHTML = this.timers.length ? this.timers.map((t) => `<div class="card" style="margin-bottom:10px"><div class="row">
      <div style="flex:1"><div class="label" style="margin-bottom:10px">${esc(t.label)}${t.paused != null ? ' · pausado' : ''}</div><div class="big-num">${fmt(left(t))}</div></div>
      <button class="btn round" data-p="${t.id}">${icon(t.paused != null ? 'play' : 'pause', 18)}</button>
      <button class="btn round danger" data-c="${t.id}">${icon('x', 18)}</button></div></div>`).join('') : '<div class="empty">Nenhum timer rodando.</div>';
    body.onclick = async (e) => {
      const b = e.target.closest('[data-p],[data-c]'); if (!b) return;
      const r = await post(b.dataset.p ? '/timers/pause' : '/timers/cancel', { id: b.dataset.p || b.dataset.c }).catch(() => null);
      if (r) { this.timers = r.timers; this.render(); }
    };
  },
});

// ---------- Uso de IA (cota do Claude) ----------
view({
  id: 'ia', title: 'Uso de IA', icon: 'gauge',
  mount(el) { el.innerHTML = back() + '<div data-body><div class="empty">Carregando…</div></div>'; wireBack(el); },
  async show() {
    const body = $('[data-body]', this.el);
    let d; try { d = await api('/claude'); } catch { body.innerHTML = '<div class="empty">Sem conexão com o PC.</div>'; return; }
    const live = d.live || {};
    const box = (lab, w) => w ? `<div class="card" style="margin-bottom:12px"><div class="row"><span class="label" style="flex:1">${lab}</span><span class="live">AO VIVO</span></div>
      <div style="margin:16px 0 18px"><span class="big-num" data-count="${Math.round(w.used_pct)}">0</span><span class="unit">% USADO</span></div>
      <div class="bar"><i style="width:${Math.min(100, w.used_pct)}%"></i></div>
      <div class="faint" style="margin-top:10px">Renova ${dayLabel(w.resets_at * 1000).toLowerCase()} às ${hhmm(w.resets_at * 1000)}</div></div>` : '';
    body.innerHTML = (box('Janela de 5 horas', live.five_hour) + box('Semana', live.seven_day)) || '<div class="empty">Sem dados da cota ainda.</div>';
    if (d.tasks?.length) body.innerHTML += '<div class="sec">Claude trabalhando</div><div class="list">' + d.tasks.map((t) => `<div class="item"><span class="grow">${esc(t.project)}</span><span class="faint">desde ${hhmm(t.start * 1000)}</span></div>`).join('') + '</div>';
  },
});

// ---------- Arquivos ----------
view({
  id: 'arquivos', title: 'Arquivos', icon: 'folder',
  mount(el) {
    el.innerHTML = back() + `<label class="card row" style="justify-content:center;gap:10px;padding:18px;font-weight:600">${icon('up', 20)} Mandar do iPhone para o PC
      <input type="file" multiple hidden id="up"></label><div id="up-prog" class="faint" style="margin:8px 4px"></div><div data-body></div>`;
    wireBack(el);
    $('#up').onchange = (e) => this.upload([...e.target.files]);
  },
  upload(files) {
    if (!files.length) return;
    const fd = new FormData(); files.forEach((f) => fd.append('file', f, f.name));
    const xhr = new XMLHttpRequest(), prog = $('#up-prog');
    xhr.open('POST', '/api/upload'); xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) prog.textContent = `Enviando… ${Math.round((e.loaded / e.total) * 100)}%`; };
    xhr.onload = () => { prog.textContent = xhr.status === 200 ? 'Enviado para Downloads\\Do celular.' : 'Falhou o envio.'; $('#up').value = ''; this.show(); };
    xhr.onerror = () => { prog.textContent = 'Falhou o envio.'; };
    xhr.send(fd);
  },
  async show() {
    const body = $('[data-body]', this.el);
    let d; try { d = await api('/files'); } catch { body.innerHTML = '<div class="empty">Sem conexão com o PC.</div>'; return; }
    body.innerHTML = '<div class="sec">Downloads do PC</div>' + (d.files.length ? '<div class="list">' + d.files.map((f) => `<a class="item" style="color:inherit;text-decoration:none"
      href="/api/file?name=${encodeURIComponent(f.name)}&where=${f.where}" download="${esc(f.name)}"><div class="grow"><div class="ellipsis">${esc(f.name)}</div>
      <div class="faint">${bytes(f.size)} · ${dayLabel(f.t * 1000)} ${hhmm(f.t * 1000)}${f.where === 'celular' ? ' · do celular' : ''}</div></div>${icon('download', 18)}</a>`).join('') + '</div>' : '<div class="empty">Pasta vazia.</div>');
  },
});

// ---------- Notas ----------
view({
  id: 'notas', title: 'Notas', icon: 'note',
  mount(el) {
    el.innerHTML = back() + '<textarea class="input" id="nt" placeholder="Bloco de notas (o mesmo da ilha)…"></textarea><div class="faint" id="nt-st" style="margin:6px 4px"></div>';
    wireBack(el);
    let t; $('#nt').oninput = () => { $('#nt-st').textContent = 'Salvando…'; clearTimeout(t); t = setTimeout(async () => { await post('/notes', { text: $('#nt').value }).catch(() => {}); $('#nt-st').textContent = 'Salvo'; }, 700); };
  },
  async show() { try { if (document.activeElement !== $('#nt')) $('#nt').value = (await api('/notes')).text; } catch {} },
});

// ---------- Avisos ----------
const KIND = { reminder: 'bell', timer: 'timer', meeting: 'calendar', email: 'inbox', render: 'film', claude_done: 'spark', brief: 'spark' };
view({
  id: 'avisos', title: 'Avisos', icon: 'inbox',
  mount(el) { el.innerHTML = back() + '<div data-body><div class="empty">Carregando…</div></div>'; wireBack(el); },
  async show() {
    const body = $('[data-body]', this.el);
    let d; try { d = await api('/feed'); } catch { body.innerHTML = '<div class="empty">Sem conexão com o PC.</div>'; return; }
    store.set('orbit.seen', Date.now() / 1000); badge();
    body.innerHTML = d.feed.length ? '<div class="list">' + d.feed.map((a) => `<div class="item" style="align-items:flex-start">
      <span class="well">${icon(KIND[a.kind] || 'spark', 18)}</span>
      <div class="grow"><div style="white-space:pre-wrap">${esc(a.text)}</div><div class="faint">${esc(dayLabel(a.t * 1000))} · ${hhmm(a.t * 1000)}</div></div></div>`).join('') + '</div>'
      : `<div class="empty">Nada por aqui ainda. Os avisos ${me.assistente?.artigo === 'o' ? 'do' : 'da'} ${esc(nome())} aparecem aqui.</div>`;
  },
});

// ---------- Ajustes (notificações e instalação) ----------
const b64 = (s) => { const p = '='.repeat((4 - (s.length % 4)) % 4), r = atob((s + p).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(r, (c) => c.charCodeAt(0)); };
view({
  id: 'ajustes', title: 'Ajustes', icon: 'gear',
  mount(el) { el.innerHTML = back() + '<div data-body></div>'; wireBack(el); },
  async show() {
    const body = $('[data-body]', this.el);
    const perm = window.Notification ? Notification.permission : 'indisponível';
    body.innerHTML = (!standalone ? `<div class="card" style="margin-bottom:12px"><b>Instale o app</b><div class="dim" style="margin-top:6px">No Safari, toque em Compartilhar ${icon('up', 14).replace('class="ico"', 'class="ico" style="display:inline;vertical-align:-2px"')} e depois em <b>Adicionar à Tela de Início</b>. O iPhone só entrega notificações para o app instalado.</div></div>` : '')
      + `<div class="sec">Notificações</div><div class="card" style="display:flex;flex-direction:column;gap:12px">
        <div class="row"><span style="flex:1">Avisos no iPhone</span><span class="chip">${perm === 'granted' && me.push ? 'ligados' : perm === 'denied' ? 'bloqueados nos Ajustes' : 'desligados'}</span></div>
        <div class="row"><button class="btn primary" id="push-on" ${!standalone ? 'disabled' : ''}>Ativar avisos</button><button class="btn" id="push-test">Testar</button></div>
        <div class="row"><div style="flex:1"><div>Avisar mesmo com o PC em uso</div><div class="faint">Desligado: só manda pro celular quando você está longe do PC.</div></div>
          <button class="switch ${me.always_push ? 'on' : ''}" id="always"></button></div></div>`;
    $('#push-on').onclick = () => enablePush();
    $('#push-test').onclick = async () => { const r = await post('/push/test').catch(() => null); toast(r?.ok ? 'Mandei um aviso de teste.' : 'Nenhum aparelho com avisos ligados.'); };
    $('#always').onclick = async () => { me.always_push = !me.always_push; await post('/prefs', { always_push: me.always_push }).catch(() => {}); this.show(); };
  },
});

async function enablePush() {
  try {
    if (!('serviceWorker' in navigator) || !window.PushManager) return toast('Abra pelo app instalado na tela inicial.');
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') return toast('Permissão negada. Libere em Ajustes > Notificações > Orbit.');
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api('/push/key');
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) });
    await post('/push/subscribe', sub.toJSON());
    me.push = true; toast('Avisos ligados.'); V.ajustes.show();
  } catch (e) { toast('Não consegui ligar os avisos: ' + e.message, 4000); }
}

// ---------- Mais ----------
const MORE = ['avisos', 'som', 'timer', 'ia', 'arquivos', 'notas', 'ajustes'];
view({
  id: 'mais', title: 'Mais', icon: 'plus',
  mount(el) {
    el.innerHTML = `<div class="grid">${MORE.map((id) => `<button class="tile" data-go="${id}">${icon(V[id].icon, 26)}<span>${V[id].title}</span><span class="chip" data-badge="${id}" hidden></span></button>`).join('')}</div>`;
    el.onclick = (e) => { const b = e.target.closest('[data-go]'); if (b) go(b.dataset.go); };
    badge();
  },
});

// Avisos novos desde a última visita: bolinha na aba Mais.
async function badge() {
  try {
    const { feed } = await api('/feed'), seen = store.get('orbit.seen', 0), n = feed.filter((a) => a.t > seen).length;
    const chip = document.querySelector('[data-badge="avisos"]'); if (chip) { chip.hidden = !n; chip.textContent = n; }
  } catch {}
}

// ---------- Ao vivo (mesmos eventos da ilha) ----------
function applyColors(c) {
  if (!c) return;
  const r = document.documentElement.style, solid = c.mode === 'solid';
  r.setProperty('--accent', c.c1); r.setProperty('--accent2', solid ? c.c1 : c.c2); r.setProperty('--accent3', solid ? c.c1 : c.c3);
}
function live() {
  const es = new EventSource('/api/events');
  es.onopen = () => { $('#net').hidden = true; };
  es.onerror = () => { $('#net').hidden = false; };
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch { return; }
    if (ev.type === 'notify' && !['mute', 'error'].includes(ev.kind)) { toast(ev.text, 5000); badge(); if (current === 'avisos') V.avisos.show(); }
    if (ev.type === 'timers' && V.timer.el) { V.timer.timers = ev.timers; V.timer.render(); }
    // A assistente ouvindo/pensando/falando no PC aparece na pílula do celular (sem som).
    if (ev.type === 'state' && (island.st === 'idle' || island.pc)) {
      island.pc = ev.state !== 'idle';
      island.set(ev.state, { listening: 'Ouvindo no PC', thinking: 'Pensando no PC', speaking: 'Falando no PC' }[ev.state]);
    }
  };
}

// ---------- Pareamento ----------
function showPair() {
  if (showPair.on) return; showPair.on = true;
  $('#tabs').hidden = true; $('#title').textContent = 'Orbit';
  $('#views').innerHTML = `<section class="view on"><div class="pair">
    <span class="ring" style="width:64px;height:64px;margin:0 auto"></span>
    <h2 style="margin:6px 0 0">Conectar ao seu PC</h2>
    <div class="dim">${standalone ? 'Peça o código para a assistente ("parear o celular") ou veja no log do PC, e digite aqui.' : 'Primeiro instale: no Safari, Compartilhar → Adicionar à Tela de Início. Depois abra pelo ícone e digite o código.'}</div>
    <input class="input" id="code" maxlength="6" autocomplete="one-time-code" autocapitalize="characters" placeholder="CÓDIGO">
    <button class="btn primary" id="pair-go" style="height:50px">Conectar</button></div></section>`;
  $('#pair-go').onclick = async () => {
    const r = await fetch('/api/pair', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: $('#code').value, name: 'iPhone' }) }).then((x) => x.json()).catch(() => ({}));
    if (r.ok) location.replace('/'); else toast(r.erro || 'Não conectou.');
  };
}

// ---------- Início ----------
(async () => {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  navigator.serviceWorker?.addEventListener('message', (e) => { if (e.data?.goto) go(e.data.goto); });
  try { me = await api('/me'); } catch (e) { if (!showPair.on) { $('#views').innerHTML = '<div class="empty" style="padding-top:30vh">Não consegui falar com o PC.<br>Ele está ligado e no Tailscale?</div>'; } return; }
  document.title = 'Orbit';
  applyColors(me.cores);
  island.set('idle');
  buildTabs();
  go(location.hash.slice(1) || 'sexta');
  live();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { V[current]?.show?.(); badge(); } });
})();
