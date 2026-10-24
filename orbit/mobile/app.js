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
const TABS_DEFAULT = { main: ['sexta', 'agenda', 'lembretes', 'midia', 'timer'], more: ['avisos', 'ia', 'arquivos', 'notas'] };
function tabOrder() {
  const t = store.get('orbit.tabs', TABS_DEFAULT), all = [...TABS_DEFAULT.main, ...TABS_DEFAULT.more];
  const main = (t.main || []).filter((x) => all.includes(x)).slice(0, 5), more = all.filter((x) => !main.includes(x));
  const savedMore = (t.more || []).filter((x) => more.includes(x));
  return { main: main.length ? main : TABS_DEFAULT.main, more: [...savedMore, ...more.filter((x) => !savedMore.includes(x))] };
}
let MAIN = [...tabOrder().main, 'mais'];
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
  for (const x of Object.values(V)) x.el?.classList.toggle('in-main', MAIN.includes(x.id)); // aba da barra não mostra "‹ Mais"
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.id === tab));
  history.replaceState(null, '', '#' + id);
  rise(v.el);
  Promise.resolve(v.show?.()).then(() => rise(v.el));
}

// Entrada em cascata (como os cartões da referência) e números que contam até o valor.
const RISE = '.card, .item, .tile, .sec, .msg';
function rise(el, only) {
  const items = only ? [only] : [...el.querySelectorAll(RISE)].filter((x) => !x.parentElement.closest('.card, .item'));
  items.forEach((x, i) => {
    x.classList.remove('rise'); void x.offsetWidth; x.style.setProperty('--i', Math.min(i, 12)); x.classList.add('rise');
    x.addEventListener('animationend', () => x.classList.remove('rise'), { once: true }); // solta o transform (ex.: deslizar a nota)
  });
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
    document.body.dataset.st = st; // a aura do fundo muda junto
    if (st === 'idle') document.documentElement.style.setProperty('--lv', 0);
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
      // Nível da voz para a aura do fundo (suavizado para a luz não piscar).
      const avg = real ? data.slice(2, 2 + N).reduce((a, b) => a + b, 0) / N / 255 : 0.15;
      this.lv = (this.lv || 0) * 0.85 + avg * 0.15;
      document.documentElement.style.setProperty('--lv', Math.min(1, this.lv * 1.6).toFixed(3));
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
  // Um cartão só: o que lembrar, quando (atalhos ou "Escolher", que abre o seletor do iPhone) e o botão.
  mount(el) {
    const p2 = (n) => String(n).padStart(2, '0');
    const at = (h, m = 0, plusDays = 0) => { const d = new Date(); d.setDate(d.getDate() + plusDays); d.setHours(h, m, 0, 0); return d; };
    const later = (min) => new Date(Date.now() + min * 6e4);
    const tonight = at(19); const evening = Date.now() < tonight - 30 * 6e4;
    const quick = [['Em 15 min', () => later(15)], ['Em 1 hora', () => later(60)],
      evening ? ['Hoje 19h', () => at(19)] : ['Em 3 horas', () => later(180)], ['Amanhã 9h', () => at(9, 0, 1)]];
    el.innerHTML = `<div class="card" style="display:flex;flex-direction:column;gap:14px">
        <input class="input" id="rm-text" placeholder="Lembrar de…" enterkeyhint="done" style="width:100%;flex:none">
        <div><div class="label" style="margin:0 4px 8px">Quando</div>
          <div class="row" style="flex-wrap:wrap;gap:8px" id="rm-quick">
            ${quick.map(([l], i) => `<button class="chip pick" data-q="${i}">${l}</button>`).join('')}
            <label class="chip pick" id="rm-other" style="position:relative">Escolher…
              <input type="datetime-local" id="rm-when" style="position:absolute;inset:0;opacity:0;width:100%;height:100%"></label>
          </div></div>
        <button class="btn tint" id="rm-add" style="width:100%" disabled>Escolha quando</button>
      </div><div data-body></div>`;
    let when = null;
    const label = (d) => `${dayLabel(d)} às ${hhmm(d)}`;
    const pick = (d, btn) => {
      when = d;
      el.querySelectorAll('.pick').forEach((b) => b.classList.toggle('on', b === btn));
      const ok = !!$('#rm-text').value.trim();
      $('#rm-add').disabled = !ok; $('#rm-add').textContent = ok ? `Lembrar ${label(d).toLowerCase()}` : label(d);
    };
    el.querySelectorAll('[data-q]').forEach((b) => b.onclick = () => pick(quick[+b.dataset.q][1](), b));
    $('#rm-when').onchange = (e) => { if (e.target.value) pick(new Date(e.target.value), $('#rm-other')); };
    $('#rm-text').oninput = () => { if (when) pick(when, el.querySelector('.pick.on')); };
    $('#rm-add').onclick = async () => {
      const text = $('#rm-text').value.trim(); if (!text || !when) return;
      const iso = `${when.getFullYear()}-${p2(when.getMonth() + 1)}-${p2(when.getDate())}T${p2(when.getHours())}:${p2(when.getMinutes())}`;
      const r = await post('/reminders/add', { text, when: iso }).catch(() => null);
      toast(r?.msg || 'Não consegui criar.');
      $('#rm-text').value = ''; when = null; el.querySelectorAll('.pick').forEach((b) => b.classList.remove('on'));
      $('#rm-add').disabled = true; $('#rm-add').textContent = 'Escolha quando'; this.show();
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
      ${m.yt ? `<img class="art" src="${m.yt.thumb}" onerror="this.onerror=null;this.src='${m.yt.thumb_hq}'" alt="">` : m.art ? `<img class="art" src="${m.art}" alt="">` : ''}
      <div style="margin-top:16px"><div style="font-size:19px;font-weight:600">${esc(m.title)}</div><div class="dim">${esc(m.artist || m.app)}</div></div>
      <div class="bar" style="margin-top:16px"><i style="width:${pct}%"></i></div>
      <div class="controls">
        <button class="btn round" data-a="previous">${icon('prev', 22)}</button>
        <button class="btn round big primary" data-a="play_pause">${icon(m.playing ? 'pause' : 'play', 28)}</button>
        <button class="btn round" data-a="next">${icon('next', 22)}</button></div>
      ${m.yt ? `<a class="btn" style="width:100%;margin-top:14px" data-handoff href="https://youtu.be/${m.yt.id}?t=${Math.floor(m.position || 0)}">${icon('up', 18)} Abrir no celular</a>` : ''}</div>`;
    body.onclick = async (e) => {
      if (e.target.closest('[data-handoff]') && this.m.playing) { post('/media/play_pause', { id: this.m.id }).catch(() => {}); return; }
      const b = e.target.closest('[data-a]'); if (!b) return;
      await post('/media/' + b.dataset.a, { id: this.m.id }).catch(() => {}); setTimeout(() => this.load(), 400);
    };
  },
});

// ---------- Timer: Pomodoro, seletor de tempo (como o Relógio do iPhone) e timers em anel ----------
const ROW = 44; // altura de cada número na roda
function wheel(max, start = 0) {
  return `<div class="wheel" data-max="${max}"><div class="wheel-in">${Array.from({ length: max + 1 }, (_, n) => `<div>${String(n).padStart(2, '0')}</div>`).join('')}</div></div>`;
}
view({
  id: 'timer', title: 'Timer', icon: 'timer',
  timers: [], pomo: null,
  mount(el) {
    el.innerHTML = back() + `
      <div class="card pomo" style="margin-bottom:12px"><div id="pm-main"></div>
        <div class="row" id="pm-dots" style="gap:6px;margin-top:14px"></div></div>
      <div data-body></div>
      <div class="card" style="margin-bottom:12px">
        <div class="label" style="margin-bottom:6px">Timer personalizado</div>
        <div class="wheels">${wheel(23)}<span class="wl">h</span>${wheel(59)}<span class="wl">min</span>${wheel(59)}<span class="wl">s</span><div class="wheel-band"></div></div>
        <div class="row" style="flex-wrap:wrap;gap:8px;margin:12px 0">${[1, 5, 10, 15, 30, 60].map((m) => `<button class="chip pick" data-m="${m}">${m < 60 ? m + ' min' : '1 h'}</button>`).join('')}</div>
        <input class="input" id="tm-label" placeholder="Nome (opcional), ex.: Café" style="width:100%;margin-bottom:12px">
        <button class="btn primary" id="tm-go" style="width:100%">Iniciar</button>
      </div>`;
    wireBack(el);
    this.wheels = [...el.querySelectorAll('.wheel')];
    this.set(0, 10, 0);
    el.querySelectorAll('[data-m]').forEach((b) => b.onclick = () => { const m = +b.dataset.m; this.set(Math.floor(m / 60), m % 60, 0); });
    const start = async (min, label) => {
      const r = await post('/timers/start', { minutes: min, label }).catch(() => null); if (!r) return toast('Não consegui iniciar.');
      this.apply(r);
      const novo = label === 'Pomodoro' ? $('#pm-main') : $('[data-body]', this.el).lastElementChild;
      if (novo) { rise(this.el, novo.closest('.card') || novo); novo.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
    };
    $('#tm-go', el).onclick = () => {
      const [h, m, s2] = this.wheels.map((w) => Math.round(w.scrollTop / ROW)), min = h * 60 + m + s2 / 60;
      if (min <= 0) return toast('Escolha um tempo.');
      start(min, $('#tm-label').value.trim() || 'Timer'); $('#tm-label').value = '';
    };
    this.start = start;
    $('#pm-main', el).onclick = (e) => {
      if (e.target.closest('#pm-go')) start(this.pomo?.focus || 25, 'Pomodoro');
      else this.control(e);
    };
  },
  async control(e) {
    const b = e.target.closest('[data-p],[data-c]'); if (!b) return;
    const r = await post(b.dataset.p ? '/timers/pause' : '/timers/cancel', { id: b.dataset.p || b.dataset.c }).catch(() => null);
    if (r) this.apply(r);
  },
  set(h, m, s2) { [h, m, s2].forEach((v, i) => this.wheels[i].scrollTo({ top: v * ROW, behavior: this.el.offsetParent ? 'smooth' : 'auto' })); },
  apply(r) { this.timers = r.timers; this.pomo = r.pomodoro || this.pomo; this.render(); },
  async show() {
    try { this.apply(await api('/timers')); } catch {}
    requestAnimationFrame(() => { if (!this.wheels[1].scrollTop) this.set(0, 10, 0); });
    clearInterval(this.t); this.t = setInterval(() => this.render(), 1000);
  },
  hide() { clearInterval(this.t); },
  render() {
    const body = this.el && $('[data-body]', this.el); if (!body) return;
    const p = this.pomo, running = this.timers.find((t) => /^(pomodoro|pausa)$/i.test(t.label));
    if (p) {
      const inSet = p.done % p.every;
      $('#pm-dots').innerHTML = Array.from({ length: p.every }, (_, k) => `<span class="pdot ${k < inSet ? 'on' : ''}"></span>`).join('')
        + `<span class="faint" style="margin-left:6px">${p.done ? `${p.done} hoje` : 'nenhum hoje'}</span>`;
    }
    const left = (t) => Math.max(0, Math.round(t.paused != null ? t.paused : t.end - Date.now() / 1000));
    const fmt = (s2) => { const h = Math.floor(s2 / 3600), m = Math.floor(s2 % 3600 / 60), x = s2 % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };
    const R = 34, C = 2 * Math.PI * R;
    const ring = (t, size = 84) => { const frac = t.total ? left(t) / t.total : 0; return `<svg width="${size}" height="${size}" viewBox="0 0 84 84" style="flex:none;transform:rotate(-90deg)">
      <circle cx="42" cy="42" r="${R}" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="6"/>
      <circle cx="42" cy="42" r="${R}" fill="none" stroke="var(--accent)" stroke-width="6" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - frac)}" style="transition:stroke-dashoffset 1s linear;filter:drop-shadow(0 0 6px var(--accent))"/></svg>`; };
    const buttons = (t) => `<div style="display:flex;flex-direction:column;gap:8px"><button class="btn round" data-p="${t.id}">${icon(t.paused != null ? 'play' : 'pause', 18)}</button>
      <button class="btn round danger" data-c="${t.id}">${icon('x', 18)}</button></div>`;
    const pm = $('#pm-main');
    if (pm) pm.innerHTML = running
      ? `<div class="row" style="gap:16px"><div style="position:relative;display:grid;place-items:center">${ring(running)}<span class="tomato" style="position:absolute;font-size:26px">🍅</span></div>
          <div style="flex:1;min-width:0"><div class="label" style="margin-bottom:6px">${/pausa/i.test(running.label) ? 'Pausa' : 'Foco'}${running.paused != null ? ' · pausado' : ''}</div>
          <div class="big-num" style="font-size:40px">${fmt(left(running))}</div></div>${buttons(running)}</div>`
      : `<div class="row" style="gap:14px"><span class="tomato">🍅</span>
          <div style="flex:1"><div style="font-weight:600;font-size:17px">Pomodoro</div><div class="faint">${p ? `${p.focus} min de foco · ${p.break} de pausa` : ''}</div></div>
          <button class="btn tint" id="pm-go">Focar</button></div>`;
    const items = this.timers.filter((t) => t !== running && !/^(pomodoro|pausa)$/i.test(t.label)).map((t) => {
      return `<div class="card" style="margin-bottom:12px;padding:16px"><div class="row" style="gap:16px">${ring(t)}
        <div style="flex:1;min-width:0"><div class="label" style="margin-bottom:6px">${esc(t.label)}${t.paused != null ? ' · pausado' : ''}</div>
          <div class="big-num" style="font-size:40px">${fmt(left(t))}</div></div>${buttons(t)}</div></div>`;
    });
    body.innerHTML = items.join('');
    body.onclick = (e) => this.control(e);
  },
});

// ---------- Uso de IA: a mesma aba da ilha (faísca e laranja do Claude), em vidro ----------
const SPARK = (sz) => `<svg viewBox="0 0 24 24" width="${sz}" height="${sz}"><g fill="currentColor">` +
  [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((a, i) => `<rect x="11" y="${i % 2 ? 3.5 : 1.5}" width="2" height="${i % 2 ? 8 : 10}" rx="1" transform="rotate(${a} 12 12)"/>`).join('') + '</g></svg>';
const CLAUDE = '#d97857';
const usd = (v) => '$' + (v || 0).toLocaleString('en-US', { minimumFractionDigits: v >= 1000 ? 0 : 2, maximumFractionDigits: v >= 1000 ? 0 : 2 });
const compact = (n) => n >= 1e9 ? (n / 1e9).toFixed(1) + ' bi' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' mi' : n >= 1e3 ? Math.round(n / 1e3) + ' mil' : String(n || 0);
const countdown = (ms) => { ms = Math.max(0, ms); const d = Math.floor(ms / 864e5), h = Math.floor(ms % 864e5 / 36e5), m = Math.floor(ms % 36e5 / 6e4); return d ? `${d}d ${h}h` : h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`; };
const modelTint = (m) => /opus|fable/i.test(m) ? CLAUDE : /sonnet/i.test(m) ? '#e8b48a' : /haiku/i.test(m) ? '#8fb3ff' : '#9a9aa2';
const modelName = (m) => m.replace(/^claude-/, '').replace(/-(\d+)-(\d+).*$/, ' $1.$2').replace(/^\w/, (c) => c.toUpperCase());
const mmss = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(s % 60).padStart(2, '0')}s`; };
view({
  id: 'ia', title: 'Uso de IA', icon: 'gauge',
  period: store.get('orbit.ia.period', 'week'),
  mount(el) {
    el.innerHTML = back() + `<div class="row" style="margin:0 4px 14px;gap:10px"><span style="color:${CLAUDE};display:flex">${SPARK(26)}</span>
      <b style="font-size:20px;flex:1">Claude</b><div class="row" id="ia-per" style="gap:6px"></div></div><div data-body><div class="empty">Somando tokens…</div></div>`;
    wireBack(el);
    $('#ia-per').onclick = (e) => { const b = e.target.closest('[data-p]'); if (!b) return; this.period = b.dataset.p; store.set('orbit.ia.period', this.period); this.render(); rise(this.el); };
  },
  async show() {
    try { [this.q, this.u] = await Promise.all([api('/claude'), api('/ai-usage')]); } catch { $('[data-body]', this.el).innerHTML = '<div class="empty">Sem conexão com o PC.</div>'; return; }
    this.render();
  },
  sum() {
    const days = this.u?.claude?.days || {}, n = { today: 1, week: 7, month: 30 }[this.period];
    const out = { input: 0, cached: 0, output: 0, cost: 0, messages: 0, models: {}, projects: {}, series: [] };
    for (let i = n - 1; i >= 0; i--) {
      const key = new Date(Date.now() - i * 864e5).toLocaleDateString('sv-SE'), d = days[key];
      out.series.push({ key, cost: d?.cost || 0 });
      if (!d) continue;
      for (const k of ['input', 'cached', 'output', 'cost', 'messages']) out[k] += d[k];
      for (const g of ['models', 'projects']) for (const [name, v] of Object.entries(d[g])) { const o = (out[g][name] ||= { tokens: 0, cost: 0 }); o.tokens += v.tokens; o.cost += v.cost; }
    }
    out.tokens = out.input + out.output + out.cached;
    return out;
  },
  card(title, ico, body, extra = '') {
    return `<div class="card" style="margin-bottom:12px"><div class="row" style="gap:8px;margin-bottom:12px"><span style="color:${CLAUDE};display:flex">${ico}</span><span class="label" style="flex:1">${title}</span>${extra}</div>${body}</div>`;
  },
  meter(frac, tint, pace) {
    return `<div class="bar" style="position:relative;overflow:visible;height:6px"><i style="width:${Math.max(frac > 0 ? 2 : 0, Math.min(100, frac * 100))}%;background:${tint};box-shadow:0 0 10px ${tint}"></i>${
      pace > 0.02 && pace < 0.98 ? `<b style="position:absolute;top:-4px;left:${pace * 100}%;width:2px;height:14px;border-radius:1px;background:#fff;opacity:.7"></b>` : ''}</div>`;
  },
  render() {
    const body = $('[data-body]', this.el); if (!body || !this.u) return;
    $('#ia-per').innerHTML = [['today', 'Hoje'], ['week', '7 dias'], ['month', '30 dias']].map(([k, l]) => `<button class="chip pick${this.period === k ? ' on' : ''}" data-p="${k}" style="padding:6px 10px">${l}</button>`).join('');
    const u = this.sum(), L = this.q?.live || {}, now = Date.now();
    const lim = (label, w, hours) => {
      if (!w) return `<div style="margin-bottom:14px"><div class="row"><span style="flex:1">${label}</span><span class="faint">sem dado</span></div></div>`;
      const used = Math.min(100, w.used_pct || 0) / 100, reset = w.resets_at * 1000, tint = used >= 0.95 ? 'var(--bad)' : used >= 0.8 ? '#ff9f43' : CLAUDE;
      return `<div style="margin-bottom:16px"><div class="row" style="margin-bottom:8px;align-items:baseline"><span style="flex:1;font-weight:600">${label}</span>
        <span class="faint" style="margin-right:10px">↻ ${countdown(reset - now)}</span><span style="font-size:22px;font-weight:500;${used >= 0.8 ? 'color:' + tint : ''}" data-count="${Math.round(used * 100)}">0</span><span class="unit" style="margin-left:2px">%</span></div>
        ${this.meter(used, tint, 1 - (reset - now) / (hours * 36e5))}</div>`;
    };
    const models = Object.entries(u.models).filter(([, v]) => v.cost > 0).sort((a, b) => b[1].cost - a[1].cost), tot = models.reduce((n, [, v]) => n + v.cost, 0);
    const split = `<div style="display:flex;gap:3px;height:6px;border-radius:3px;overflow:hidden;margin:14px 0 10px">${tot ? models.map(([m, v]) => `<i style="flex:${v.cost / tot};background:${modelTint(m)}"></i>`).join('') : '<i style="flex:1;background:#ffffff22"></i>'}</div>`;
    const cacheRate = u.input + u.cached ? u.cached / (u.input + u.cached) : 0;
    const tasks = this.q?.tasks || [], ol = this.u.ollama;
    const max = Math.max(0.01, ...u.series.map((d) => d.cost)), many = u.series.length > 7;
    const bars = `<div style="display:flex;align-items:flex-end;gap:${many ? 2 : 8}px;height:76px">${u.series.map((d, i) => {
      const lbl = u.series.length === 1 ? 'hoje' : many ? (i === 0 || i === u.series.length - 1 ? d.key.slice(8) + '/' + d.key.slice(5, 7) : '') : new Date(d.key + 'T12:00').toLocaleDateString('pt-BR', { weekday: 'narrow' });
      return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px"><i style="display:block;width:100%;max-width:26px;border-radius:5px;height:${Math.max(3, 54 * d.cost / max)}px;background:${i === u.series.length - 1 ? CLAUDE : 'rgba(255,255,255,.14)'}"></i><span class="faint" style="font-size:10px">${lbl}</span></div>`;
    }).join('')}</div>`;
    const share = (entries, name, tint) => Object.entries(entries).sort((a, b) => b[1].cost - a[1].cost).slice(0, 4).map(([k, v], _, arr) => `<div style="margin-bottom:12px">
      <div class="row" style="margin-bottom:6px;gap:8px"><span class="ellipsis" style="flex:1">${esc(name(k))}</span><span class="faint">${compact(v.tokens)}</span><b style="min-width:62px;text-align:right">${usd(v.cost)}</b></div>
      ${this.meter(v.cost / Math.max(0.0001, arr[0][1].cost), tint(k))}</div>`).join('') || '<div class="faint">Nada no período.</div>';
    body.innerHTML =
      this.card('Limites', SPARK(16), lim('Sessão (5 h)', L.five_hour, 5) + lim('Semana', L.seven_day, 168), '<span class="live" style="color:' + CLAUDE + '">AO VIVO</span>')
      + this.card('Gasto', icon('gauge', 16), `<div><span class="big-num">${usd(u.cost)}</span></div><div class="label" style="margin-top:6px">valor em API · estimado</div>${split}
        <div class="faint">${compact(u.tokens)} tokens${cacheRate ? ` · ${Math.round(cacheRate * 100)}% do cache` : ''} · ${u.messages} respostas</div>`)
      + this.card('Agora', icon('spark', 16), (tasks.length ? tasks.map((t) => `<div class="row" style="gap:10px;margin-bottom:8px"><span style="color:${CLAUDE};display:flex;animation:spin 3s linear infinite">${SPARK(14)}</span><b class="ellipsis" style="flex:1">${esc(t.project)}</b><span class="faint">${mmss(Date.now() / 1000 - t.start)}</span></div>`).join('') : '<div class="faint" style="margin-bottom:8px">Nenhuma tarefa rodando.</div>')
        + `<div class="row"><span class="dim" style="flex:1">Ollama (${esc(nome())})</span><span class="chip" style="color:${ol && ol.length ? 'var(--ok)' : 'var(--faint)'}">${ol && ol.length ? 'carregado' : ol ? 'parado' : 'desligado'}</span></div>`)
      + this.card('Tendência', icon('up', 16), bars, `<span class="faint">pico ${usd(max)}/dia</span>`)
      + this.card('Modelos', icon('cpu', 16), share(u.models, modelName, modelTint))
      + this.card('Projetos', icon('folder', 16), share(u.projects, (p) => p, () => CLAUDE));
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

// ---------- Notas (uma por assunto): deslizar para arquivar/excluir, links clicáveis ----------
const URL_RE = /https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]]/g;
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };
// Texto da nota com os links virando pílulas tocáveis (domínio + ícone), o resto como texto normal.
function linkify(text) {
  let out = '', last = 0;
  for (const m of String(text || '').matchAll(URL_RE)) {
    out += esc(text.slice(last, m.index)) + `<a class="link-pill" href="${esc(m[0])}" target="_blank" rel="noopener">${icon('link', 14)}<span>${esc(host(m[0]))}</span></a>`;
    last = m.index + m[0].length;
  }
  return out + esc(String(text || '').slice(last));
}
view({
  id: 'notas', title: 'Notas', icon: 'note',
  notes: [], open: null, showArchived: false,
  mount(el) { el.innerHTML = '<div data-body></div>'; },
  async show() { try { this.notes = (await api('/notes')).notes; } catch {} if (this.open == null) this.list(); },
  list() {
    this.open = null;
    const body = $('[data-body]', this.el), active = this.notes.filter((n) => !n.archived), archived = this.notes.filter((n) => n.archived);
    const row = (n) => `<div class="swipe" data-id="${n.id}">
        <div class="swipe-acts"><button class="sw-arch" data-arch="${n.id}">${icon('inbox', 18)}<span>${n.archived ? 'Voltar' : 'Arquivar'}</span></button>
          <button class="sw-del" data-del="${n.id}">${icon('trash', 18)}<span>Excluir</span></button></div>
        <div class="item swipe-front"><span class="well">${icon('note', 18)}</span><div class="grow"><div class="ellipsis" style="font-weight:600">${esc(n.title || 'Sem título')}</div>
          <div class="faint ellipsis">${esc((n.text || '').replace(/\s+/g, ' ').slice(0, 90)) || 'Vazia'}</div></div>
          ${/https?:\/\//.test(n.text || '') ? `<span class="faint" style="display:flex">${icon('link', 15)}</span>` : ''}</div></div>`;
    body.innerHTML = back() + `<button class="btn primary" data-new style="width:100%;margin-bottom:12px">${icon('plus', 18)} Nova nota</button>`
      + (active.length ? '<div class="list">' + active.map(row).join('') + '</div>' : '<div class="empty">Nenhuma nota.</div>')
      + (archived.length ? `<button class="sec" data-toggle style="display:flex;gap:6px;align-items:center">${icon(this.showArchived ? 'down' : 'right', 14)} Arquivadas (${archived.length})</button>`
        + (this.showArchived ? '<div class="list">' + archived.map(row).join('') + '</div>' : '') : '')
      + '<div class="faint" style="text-align:center;margin-top:14px">Deslize uma nota para o lado para arquivar ou excluir.</div>';
    wireBack(body);
    $('[data-new]', body).onclick = () => this.edit({ id: '', title: '', text: '' }, true);
    $('[data-toggle]', body)?.addEventListener('click', () => { this.showArchived = !this.showArchived; this.list(); });
    body.querySelectorAll('.swipe').forEach((sw) => this.swipe(sw));
    rise(this.el);
  },
  // Deslizar para a esquerda revela Arquivar e Excluir (como no app Notas); toque abre a nota.
  swipe(sw) {
    const front = $('.swipe-front', sw), OPEN = -164;
    let x0 = null, y0 = 0, dx = 0, base = 0, moved = false;
    const set = (v, anim) => { front.style.transition = anim ? 'transform .3s var(--settle)' : 'none'; front.style.transform = `translateX(${v}px)`; sw.classList.toggle('moving', v < 0); };
    sw.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; base = sw.classList.contains('open') ? OPEN : 0; moved = false; }, { passive: true });
    sw.addEventListener('touchmove', (e) => {
      if (x0 == null) return;
      dx = e.touches[0].clientX - x0;
      if (!moved && Math.abs(e.touches[0].clientY - y0) > Math.abs(dx)) { x0 = null; return; } // rolagem vertical
      moved = true; set(Math.min(0, Math.max(OPEN - 40, base + dx)));
    }, { passive: true });
    sw.addEventListener('touchend', () => {
      if (x0 == null) return; x0 = null;
      if (!moved) return;
      const open = base + dx < OPEN / 2;
      this.el.querySelectorAll('.swipe.open').forEach((o) => { if (o !== sw) { o.classList.remove('open'); $('.swipe-front', o).style.transform = ''; } });
      sw.classList.toggle('open', open); set(open ? OPEN : 0, true);
    });
    front.addEventListener('click', () => {
      if (moved) return;
      if (sw.classList.contains('open')) { sw.classList.remove('open'); set(0, true); return; }
      this.edit(this.notes.find((n) => n.id === sw.dataset.id));
    });
    $('[data-arch]', sw).onclick = async () => {
      const n = this.notes.find((x) => x.id === sw.dataset.id);
      await post('/notes/archive', { id: n.id, archived: !n.archived, source: 'celular' }).catch(() => {});
      toast(n.archived ? 'Nota de volta.' : 'Nota arquivada.'); await this.show(); this.list();
    };
    $('[data-del]', sw).onclick = async () => {
      const n = this.notes.find((x) => x.id === sw.dataset.id);
      sw.style.transition = 'opacity .25s, max-height .3s'; sw.style.maxHeight = sw.offsetHeight + 'px';
      requestAnimationFrame(() => { sw.style.opacity = 0; sw.style.maxHeight = '0px'; });
      await post('/notes/delete', { id: n.id, source: 'celular' }).catch(() => {});
      undoToast('Nota excluída.', async () => { await post('/notes', { title: n.title, text: n.text, source: 'celular' }); await this.show(); this.list(); });
      setTimeout(async () => { await this.show(); this.list(); }, 320);
    };
  },
  // Abre em leitura (links em pílulas); tocar no texto ou em Editar entra na edição. Nota nova já abre editando.
  edit(n, editing = false) {
    this.open = n.id;
    const body = $('[data-body]', this.el);
    const head = `<div class="row" style="margin-bottom:10px"><button class="back" data-list style="margin:0;flex:1">${icon('left', 18)} Notas</button><span class="faint" id="nt-st"></span></div>`;
    if (!editing) {
      body.innerHTML = head + `<div class="card note-read"><h2 style="margin:0 0 12px;font-size:22px;font-weight:600">${esc(n.title || 'Sem título')}</h2>
        <div class="note-text">${linkify(n.text) || '<span class="faint">Vazia. Toque para escrever.</span>'}</div></div>
        <button class="btn" data-editbtn style="width:100%;margin-top:12px">${icon('note', 17)} Editar</button>`;
      $('[data-list]', body).onclick = () => this.list();
      const go = (e) => { if (!e.target.closest('a')) this.edit(n, true); };
      $('.note-read', body).onclick = go; $('[data-editbtn]', body).onclick = go;
      rise(this.el); return;
    }
    body.innerHTML = head + `<input class="input" id="nt-title" placeholder="Título" value="${esc(n.title)}" style="width:100%;font-weight:600;margin-bottom:10px">
      <textarea class="input" id="nt" placeholder="Escreva aqui…">${esc(n.text)}</textarea>`;
    let t;
    const save = () => {
      $('#nt-st').textContent = 'Salvando…'; clearTimeout(t);
      t = setTimeout(async () => {
        const r = await post('/notes', { id: this.open || '', title: $('#nt-title').value.trim() || 'Sem título', text: $('#nt').value, source: 'celular' }).catch(() => null);
        if (r?.note) { this.open = r.note.id; Object.assign(n, r.note); $('#nt-st').textContent = 'Salvo'; } else $('#nt-st').textContent = 'Não salvou';
      }, 600);
    };
    $('#nt-title').oninput = save; $('#nt').oninput = save;
    $('[data-list]', body).onclick = async () => { clearTimeout(t); await this.show(); this.list(); };
    (n.id ? $('#nt') : $('#nt-title')).focus();
  },
});
// Aviso com "Desfazer" (excluir nota).
function undoToast(text, undo) {
  const tEl = $('#toast'); tEl.innerHTML = `<div class="row"><span style="flex:1">${esc(text)}</span><button class="btn" style="height:34px" id="undo">Desfazer</button></div>`;
  tEl.hidden = false; clearTimeout(toast.t);
  $('#undo').onclick = () => { tEl.hidden = true; undo(); };
  toast.t = setTimeout(() => { tEl.hidden = true; }, 5000);
}

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
const PRESETS = { 'Padrão': ['#2f7bff', '#9b5cff', '#ff6fb5'], Ciano: ['#00e5ff', '#2f7bff', '#7cf7ff'], Brasa: ['#ff6a00', '#ff2d55', '#ff9a3c'], Verde: ['#2bff9a', '#00b3ff', '#c6ff6b'] };
view({
  id: 'ajustes', title: 'Ajustes', icon: 'gear',
  mount(el) { el.innerHTML = back() + '<div data-body></div>'; wireBack(el); },
  async show() {
    try { me = await api('/me'); } catch {}
    const body = $('[data-body]', this.el), c = me.cores || {}, perm = window.Notification ? Notification.permission : 'indisponível';
    let mic = 'pedido no primeiro uso';
    try { const q = await navigator.permissions?.query({ name: 'microphone' }); if (q) mic = { granted: 'liberado', denied: 'bloqueado', prompt: 'pedido no primeiro uso' }[q.state] || mic; } catch {}
    const order = tabOrder();
    const tabRow = (id, where, i, n) => `<div class="item" style="padding:10px 12px;gap:10px"><span class="well" style="width:36px;height:36px">${icon(V[id].icon, 17)}</span>
      <span class="grow" style="font-weight:600">${id === 'sexta' ? esc(nome()) : V[id].title}</span>
      <button class="btn round" style="width:36px;height:36px" data-up="${where}:${i}" ${i === 0 ? 'disabled' : ''}>${icon('up', 16)}</button>
      <button class="btn round" style="width:36px;height:36px" data-dn="${where}:${i}" ${i === n - 1 ? 'disabled' : ''}>${icon('down', 16)}</button>
      <button class="chip pick" data-mv="${where}:${i}">${where === 'main' ? 'Mais' : 'Barra'}</button></div>`;
    const perms = [
      ['bell', 'Notificações', perm === 'granted' ? 'liberadas' : perm === 'denied' ? 'bloqueadas' : 'desligadas', 'Avisos da assistente quando você está longe do PC: lembretes, timers, reuniões, e-mails importantes.'],
      ['mic', 'Microfone', mic, 'Só enquanto você segura a conversa por voz. O áudio vai para o seu PC, vira texto lá e é apagado.'],
      ['calendar', 'Conta Google', me.google ? 'conectada' : 'desconectada', 'Agenda (ver e criar eventos) e Gmail (ler e, com sua confirmação, enviar). O acesso fica no seu PC.'],
      ['folder', 'Arquivos', 'só o que você escolhe', 'O app só envia o arquivo que você escolher e só mostra a pasta Downloads do PC.'],
      ['spark', 'Seu PC', 'pareado', 'Este iPhone conversa com a assistente, vê o que toca no PC, seus timers, notas e lembretes, pela rede privada do Tailscale.'],
    ];
    body.innerHTML = (!standalone ? `<div class="card" style="margin-bottom:12px"><b>Instale o app</b><div class="dim" style="margin-top:6px">No Safari, toque em Compartilhar e depois em <b>Adicionar à Tela de Início</b>. O iPhone só entrega notificações para o app instalado.</div></div>` : '')
      + `<div class="sec">Cores ${me.assistente?.artigo === 'o' ? 'do' : 'da'} ${esc(nome())}</div><div class="card">
          <div class="row" style="gap:14px;margin-bottom:14px"><span class="ring" style="width:44px;height:44px;animation-duration:6s"></span>
            <div class="row" style="flex:1;justify-content:flex-end;gap:6px"><button class="chip pick ${c.mode !== 'solid' ? 'on' : ''}" data-mode="grad">Gradiente</button><button class="chip pick ${c.mode === 'solid' ? 'on' : ''}" data-mode="solid">Sólida</button></div></div>
          <div class="label" style="margin-bottom:10px">Prontas</div>
          <div class="row" style="gap:12px;margin-bottom:16px">${Object.entries(PRESETS).map(([n, p]) => `<button class="preset ${[c.c1, c.c2, c.c3].join() === p.join() ? 'on' : ''}" data-pre="${n}"><i style="background:linear-gradient(135deg,${p})"></i><span>${n}</span></button>`).join('')}</div>
          <div class="label" style="margin-bottom:10px">Personalizada</div>
          <div class="row" style="gap:10px">${['c1', 'c2', 'c3'].map((k, i) => `<label class="swatch" ${c.mode === 'solid' && i ? 'hidden' : ''}><input type="color" data-c="${k}" value="${c[k] || '#ffffff'}"><span style="background:${c[k]}"></span></label>`).join('')}
            <span class="faint" style="flex:1">${c.mode === 'solid' ? 'Uma cor só.' : 'Três cores do gradiente.'} Muda aqui e na ilha do PC.</span></div>
        </div>`
      + `<div class="sec">Abas</div><div class="label" style="margin:0 6px 8px">Na barra de baixo (até 5)</div><div class="list">${order.main.map((id, i) => tabRow(id, 'main', i, order.main.length)).join('')}</div>
        <div class="label" style="margin:16px 6px 8px">No Mais</div><div class="list">${order.more.map((id, i) => tabRow(id, 'more', i, order.more.length)).join('')}</div>`
      + `<div class="sec">Notificações</div><div class="card" style="display:flex;flex-direction:column;gap:12px">
        <div class="row"><span style="flex:1">Avisos no iPhone</span><span class="chip">${perm === 'granted' && me.push ? 'ligados' : perm === 'denied' ? 'bloqueados nos Ajustes' : 'desligados'}</span></div>
        <div class="row"><button class="btn primary" id="push-on" ${!standalone ? 'disabled' : ''}>Ativar avisos</button><button class="btn" id="push-test">Testar</button></div>
        <div class="row"><div style="flex:1"><div>Avisar mesmo com o PC em uso</div><div class="faint">Desligado: só manda pro celular quando você está longe do PC.</div></div>
          <button class="switch ${me.always_push ? 'on' : ''}" id="always"></button></div></div>`
      + `<div class="sec">Permissões</div><div class="list">${perms.map(([ic, t, st, d]) => `<div class="item" style="align-items:flex-start"><span class="well">${icon(ic, 18)}</span>
          <div class="grow"><div class="row"><b style="flex:1">${t}</b><span class="chip">${st}</span></div><div class="faint" style="margin-top:4px;white-space:normal">${d}</div></div></div>`).join('')}</div>
        <div class="row" style="margin-top:12px;gap:8px"><a class="btn" style="flex:1" href="https://psychomathews.github.io/orbit/privacidade.html" target="_blank" rel="noopener">Privacidade</a>
          <button class="btn danger" style="flex:1" id="unpair">Desconectar este iPhone</button></div>`;

    // cores
    const setColors = async (mode, cs) => {
      const r = await post('/colors', { mode, c1: cs[0], c2: cs[1], c3: cs[2] }).catch(() => null);
      if (r?.cores) { me.cores = r.cores; applyColors(r.cores); this.show(); } else toast('Não consegui salvar as cores.');
    };
    body.querySelectorAll('[data-mode]').forEach((b) => b.onclick = () => setColors(b.dataset.mode, [c.c1, c.c2, c.c3]));
    body.querySelectorAll('[data-pre]').forEach((b) => b.onclick = () => setColors(c.mode || 'grad', PRESETS[b.dataset.pre]));
    body.querySelectorAll('[data-c]').forEach((inp) => inp.onchange = () => { const cs = [c.c1, c.c2, c.c3]; cs[+inp.dataset.c[1] - 1] = inp.value; setColors(c.mode || 'grad', cs); });
    // abas
    const save = (o) => { store.set('orbit.tabs', o); const t = tabOrder(); MAIN = [...t.main, 'mais']; MORE = [...t.more, 'ajustes']; buildTabs(); go('ajustes'); this.show(); };
    body.onclick = (e) => {
      const b = e.target.closest('[data-up],[data-dn],[data-mv]'); if (!b) return;
      const [where, i] = (b.dataset.up || b.dataset.dn || b.dataset.mv).split(':'), o = tabOrder(), list = o[where], k = +i;
      if (b.dataset.up) [list[k - 1], list[k]] = [list[k], list[k - 1]];
      else if (b.dataset.dn) [list[k + 1], list[k]] = [list[k], list[k + 1]];
      else {
        const other = where === 'main' ? 'more' : 'main';
        if (where === 'main' && o.main.length === 1) return toast('A barra precisa de pelo menos uma aba.');
        if (other === 'main' && o.main.length >= 5) return toast('A barra já tem 5 abas. Mande uma para o Mais antes.');
        o[other].push(list.splice(k, 1)[0]);
      }
      save(o);
    };
    // notificações e aparelho
    $('#push-on').onclick = () => enablePush();
    $('#push-test').onclick = async () => { const r = await post('/push/test').catch(() => null); toast(r?.ok ? 'Mandei um aviso de teste.' : 'Nenhum aparelho com avisos ligados.'); };
    $('#always').onclick = async () => { me.always_push = !me.always_push; await post('/prefs', { always_push: me.always_push }).catch(() => {}); this.show(); };
    $('#unpair').onclick = async (e) => {
      const btn = e.currentTarget;
      if (!btn.dataset.armed) { btn.dataset.armed = '1'; btn.textContent = 'Toque de novo para desconectar'; setTimeout(() => { delete btn.dataset.armed; btn.textContent = 'Desconectar este iPhone'; }, 3000); return; }
      await post('/unpair').catch(() => {}); location.replace('/');
    };
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
let MORE = [...tabOrder().more, 'ajustes'];
view({
  id: 'mais', title: 'Mais', icon: 'plus',
  mount(el) { el.onclick = (e) => { const b = e.target.closest('[data-go]'); if (b) go(b.dataset.go); }; },
  show() {
    this.el.innerHTML = `<div class="grid">${MORE.map((id) => `<button class="tile" data-go="${id}">${icon(V[id].icon, 26)}<span>${V[id].title}</span><span class="chip" data-badge="${id}" hidden></span></button>`).join('')}</div>`;
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
// O orbe da Friday atrás do app: fios de luz ondulando em volta de um círculo, somando brilho (como na ilha do PC).
const orbBg = {
  t: 0, last: 0,
  start() { requestAnimationFrame((t) => this.frame(t)); },
  frame(now) {
    requestAnimationFrame((t) => this.frame(t));
    const active = island.st !== 'idle';
    if (!active && now - this.last < 40) return; // parado: ~25 quadros/s bastam (economiza bateria)
    const dt = Math.min(0.1, (now - (this.last || now)) / 1000); this.last = now;
    const lv = active ? +(getComputedStyle(document.documentElement).getPropertyValue('--lv') || 0) : 0;
    this.t += dt * (active ? 1.6 + lv * 3 : 0.9); // parado também ondula, só mais calmo
    // Nítido (o mesmo desenho da ilha do PC, em shared/orb.js), na resolução da tela.
    const cv = $('#orb-bg'), S = Math.min(900, Math.round(cv.clientWidth * (devicePixelRatio || 1))) || 512;
    if (cv.width !== S) { cv.width = cv.height = S; }
    const g = cv.getContext('2d'), cs = getComputedStyle(document.documentElement);
    g.clearRect(0, 0, S, S);
    const energy = Math.min(2, 0.8 + lv * 1.4 + (island.st === 'thinking' ? 0.4 : 0)) * (1 + 0.15 * Math.sin(this.t * 2.3) * Math.sin(this.t * 0.7));
    ORBIT_ORB.draw(g, { cx: S / 2, cy: S / 2, R: S * 0.3, t: this.t, energy, blur: 1,
      colors: ['--accent', '--accent2', '--accent3'].map((v) => cs.getPropertyValue(v).trim()) });
  },
};

function applyColors(c) {
  if (!c) return;
  const r = document.documentElement.style, solid = c.mode === 'solid';
  r.setProperty('--accent', c.c1); r.setProperty('--accent2', solid ? c.c1 : c.c2); r.setProperty('--accent3', solid ? c.c1 : c.c3);
}
// O Safari desiste do canal para sempre quando o PC responde com erro (ex.: a assistente reiniciando).
// Aqui ele é refeito sozinho; "sem conexão" só aparece se o PC continuar fora depois de alguns segundos.
let es = null, retry = 0, netTimer = null;
function live() {
  if (es) es.close();
  es = new EventSource('/api/events');
  es.onopen = () => { retry = 0; clearTimeout(netTimer); $('#net').hidden = true; };
  es.onerror = () => {
    clearTimeout(netTimer); netTimer = setTimeout(() => { $('#net').hidden = false; }, 6000);
    if (es.readyState === EventSource.CLOSED) setTimeout(live, Math.min(30000, 1000 * 2 ** retry++));
  };
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch { return; }
    if (ev.type === 'notify' && !['mute', 'error'].includes(ev.kind)) { toast(ev.text, 5000); badge(); if (current === 'avisos') V.avisos.show(); }
    if (ev.type === 'orbit_config' && ev.config?.island) { const i = ev.config.island; me.cores = { mode: i.orbMode, c1: i.orbC1, c2: i.orbC2, c3: i.orbC3 }; applyColors(me.cores); }
    if (ev.type === 'timers' && V.timer.el) { V.timer.timers = ev.timers; V.timer.render(); if (current === 'timer') api('/timers').then((r) => V.timer.apply(r)).catch(() => {}); }
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
  orbBg.start();
  buildTabs();
  go(location.hash.slice(1) || 'sexta');
  live();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (!es || es.readyState !== EventSource.OPEN) { retry = 0; live(); } // voltou ao app: reconecta na hora
    V[current]?.show?.(); badge();
  });
})();
