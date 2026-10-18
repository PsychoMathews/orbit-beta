// Cor da marca de quem está tocando (Spotify verde; navegador quase sempre é YouTube, vermelho).
const brand = (app = '') => {
  const a = app.toLowerCase();
  const v = (t, btn, fg) => `--tint:${t};--tint-fill:${t};--btn:${btn};--btn-fg:${fg}`;
  if (a.includes('spotify')) return v('#1ed760', '#fff', '#000');
  if (/youtube|chrome|edge|opera|firefox|brave/.test(a)) return v('#ff3040', '#fff', '#000');
  if (a.includes('vlc')) return v('#ff8800', '#fff', '#000');
  return v('#1ed760', '#fff', '#000');
};
// Música e vídeo: tudo que toca no Windows (Spotify, YouTube no navegador...), um cartão com controles por player.
Orbit.register({
  id: 'midia',
  now: { title: null, playing: false, sessions: [] },
  at: 0, // quando chegou a última leitura (para andar a barra entre uma leitura e outra)
  async refresh() {
    const r = await api.get('/orbit/media');
    if (r) this.set(r);
  },
  set(r) {
    // Logo depois de um clique a leitura ainda pode vir com o estado antigo; arrastando, a barra é sua.
    if (Date.now() < this.holdUntil || this.dragging) return;
    const was = this.now.sessions.some((s) => s.playing);
    const prevTitle = (this.now.sessions.find((x) => /spotify/i.test(x.app || '')) || {}).title;
    // A posição que o Windows informa chega atrasada e "volta" a cada leitura. Se a leitura nova está perto
    // do que a barra já estimava (até 3 s), a barra segue a própria conta; só pula em salto de verdade (seek, troca).
    const prev = Object.fromEntries(this.now.sessions.map((s) => [s.id, { title: s.title, p: this.pos(s) }]));
    for (const s of r.sessions || []) {
      const o = prev[s.id];
      if (o && o.title === s.title && s.playing && Math.abs((s.position || 0) - o.p) < 3) s.position = o.p;
    }
    this.now = { sessions: [], ...r }; this.at = Date.now();
    const sp = this.now.sessions.find((x) => /spotify/i.test(x.app || ''));
    if (this.queueOn && sp && sp.title !== prevTitle) this.loadQueue(); // trocou de música: a fila andou
    this.render(); renderCompact();
    // Começou a tocar: já pede a batida, sem esperar o próximo ciclo de 2 s.
    const n = this.now.sessions.find((s) => s.playing && s.title);
    if (!was && n && Orbit.mode === 'compact' && !Orbit.game.on) api.post('/orbit/beat', { app: n.app || '' });
  },
  holdUntil: 0,
  start() {
    this.refresh();
    // Painel aberto nesta aba: atualiza a cada 1 s; fechado: a cada 3 s (só para a pílula); modo jogo (ilha escondida): 15 s.
    const open = () => Orbit.mode === 'expanded' && Orbit.tab === 'midia';
    const loop = () => { this.refresh(); setTimeout(loop, open() ? 1000 : Orbit.game.on ? 15000 : Orbit.cfg.island.lite ? 6000 : 3000); };
    setTimeout(loop, 1000);
    // Batida real: enquanto a pílula mostra a música, pede ao bot o nível de som do player (renova a cada 2 s;
    // ele para sozinho sem renovação). Com a ilha aberta, escondida ou em modo jogo, não pede nada.
    setInterval(() => {
      const n = this.now.sessions.find((s) => s.playing && s.title);
      if (n && Orbit.cfg.island.liveMusic && !Orbit.cfg.island.lite && Orbit.mode === 'compact' && !Orbit.game.on && Orbit.friday.state === 'idle') api.post('/orbit/beat', { app: n.app || '' });
    }, 2000);
    setInterval(() => { if (open() && this.now.sessions.some((s) => s.playing)) this.renderProgress(); }, 250);
    // Com a aba aberta e o Spotify tocando, a posição exata vem da conta conectada (a cada 2,5 s).
    setInterval(() => {
      const sp = this.now.sessions.find((s) => /spotify/i.test(s.app || '') && s.playing);
      if (open() && sp) this.syncSpotify();
    }, 2500);
  },
  // Depois de um comando: confere o estado real em 0,5 s e 1,5 s (o player leva um instante para reagir).
  recheck() {
    setTimeout(() => this.syncSpotify(), 1200); // depois de pular/pausar, relê a posição do Spotify
    this.holdUntil = Date.now() + 450;
    setTimeout(() => this.refresh(), 500);
    setTimeout(() => this.refresh(), 1500);
  },
  // Pulos muito seguidos travavam o YouTube (cada um recarrega o vídeo): no máximo um a cada 0,4 s por player,
  // sempre com a posição mais recente.
  seekState: {},
  seek(id, position) {
    const ss = this.now.sessions.find((x) => x.id === id);
    if (ss && /spotify/i.test(ss.app || '')) {
      // A conta do Spotify demora um instante para saber do pulo: a letra e a barra já vão para o ponto certo
      // e leituras antigas que chegarem nos próximos 4 s são ignoradas.
      this.spClock = { pos: position, at: performance.now(), playing: ss.playing, name: ss.title };
      this.spHold = performance.now() + 4000;
      this.lyrLine = null;
    }
    const st = this.seekState[id] || (this.seekState[id] = { last: 0, timer: null, pos: 0 });
    st.pos = position;
    if (st.timer) return;
    const send = () => {
      st.timer = null; st.last = Date.now();
      api.post('/orbit/media/seek_to', { id, position: st.pos });
      this.recheck();
    };
    const wait = 400 - (Date.now() - st.last);
    if (wait <= 0) send(); else st.timer = setTimeout(send, wait);
  },
  seekAt(bar, clientX) {
    const id = bar.closest('[data-sid]').dataset.sid;
    const s = this.now.sessions.find((x) => x.id === id);
    if (!s || !s.duration || !(s.can || {}).seek) return null;
    const rect = bar.getBoundingClientRect();
    return { id, s, position: Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) * s.duration };
  },
  pos(s) {
    const c = this.spClock;
    if (/spotify/i.test(s.app || '') && c && c.name === s.title && performance.now() - c.at < 8000) {
      const p = c.pos + (c.playing && s.playing ? (performance.now() - c.at) / 1000 : 0);
      return s.duration ? Math.min(p, s.duration) : p;
    }
    const p = (s.position || 0) + (s.playing ? (Date.now() - this.at) / 1000 : 0);
    return s.duration ? Math.min(p, s.duration) : p;
  },
  onEvent(ev) {
    if (ev.type !== 'beat') return;
    const bars = document.querySelectorAll('#c-right .eq i');
    if (!bars.length) return;
    // Cada barra reage um pouco diferente (e com queda suave) para não subirem todas juntas.
    this.eqv = this.eqv || [0, 0, 0, 0];
    // Ganho automático: compara com o pico recente, então música baixa também mexe a barra inteira.
    this.pk = Math.max(ev.value, (this.pk || 0.2) * 0.985, 0.08);
    const v = Math.min(1, Math.pow(ev.value / this.pk, 0.8) * 1.1), mul = [0.8, 1, 0.92, 0.7];
    bars.forEach((b, i) => {
      const target = v * mul[i] * (0.8 + Math.random() * 0.4);
      this.eqv[i] = target > this.eqv[i] ? this.eqv[i] * 0.25 + target * 0.75 : this.eqv[i] * 0.78 + target * 0.22;
      b.parentNode.classList.add('real');
      b.style.height = (2 + this.eqv[i] * 13).toFixed(1) + 'px';
    });
  },
  live() {
    const n = this.now.sessions.find((s) => s.playing && s.title);
    if (!Orbit.cfg.island.liveMusic || !n) return null;
    const art = n.art ? `<img class="art" src="${n.art}">` : `<span class="art" style="display:grid;place-items:center">${icon('music', 13)}</span>`;
    return { priority: 1, width: 330, left: art, mid: `<span class="t">${esc(n.title)}${n.artist ? ' · ' + esc(n.artist) : ''}</span>`,
      right: '<span class="eq"><i></i><i></i><i></i><i></i></span>' };
  },
  mount(view) {
    this.view = view;
    // Barra de tempo: clicar ou arrastar; a barra acompanha o mouse e o player pula quando você solta.
    view.addEventListener('pointerdown', (e) => {
      const bar = e.target.closest('[data-seek]');
      if (!bar) return;
      const hit = this.seekAt(bar, e.clientX);
      if (!hit) return;
      e.preventDefault();
      bar.setPointerCapture(e.pointerId);
      this.dragging = hit;
      const move = (ev) => {
        const h = this.seekAt(bar, ev.clientX);
        if (!h) return;
        this.dragging = h;
        h.s.position = h.position; this.at = Date.now();
        if (this.spClock && /spotify/i.test(h.s.app || '')) this.spClock = { ...this.spClock, pos: h.position, at: performance.now() };
        this.renderProgress();
      };
      const up = () => {
        bar.removeEventListener('pointermove', move);
        const h = this.dragging;
        this.dragging = null;
        if (h) this.seek(h.id, h.position);
      };
      bar.addEventListener('pointermove', move);
      bar.addEventListener('pointerup', up, { once: true });
      bar.addEventListener('pointercancel', up, { once: true });
      move(e);
    });
    view.addEventListener('click', (e) => {
      if (e.target.closest('[data-lyrretry]')) { delete this.lyr[this.lkey(this.cur)]; this.lastKey = null; this.render(); return; }
      if (e.target.closest('[data-q]')) { this.queueOn = !this.queueOn; this.lyricsOn = false; this.lastKey = null; this.render(); if (this.queueOn) this.loadQueue(); return; }
      const sk = e.target.closest('[data-skip]');
      if (sk) {
        const t = this.q?.queue?.[+sk.dataset.skip];
        if (!t || this.qBusy) return;
        this.qBusy = true;
        // Mostra na hora: a escolhida vira a música atual e o que vinha antes some da fila (o Spotify confirma depois).
        const i = +sk.dataset.skip, cur = this.now.sessions.find((x) => /spotify/i.test(x.app || ''));
        if (cur) { Object.assign(cur, { title: t.name, artist: t.artist, art: t.art || cur.art, duration: t.duration, position: 0, playing: true }); this.at = Date.now(); }
        this.spClock = { pos: 0, at: performance.now(), playing: true, name: t.name }; this.spHold = performance.now() + 4000;
        this.q = { ...this.q, queue: this.q.queue.slice(i + 1) };
        this.holdUntil = Date.now() + 2500; this.lastKey = null; this.render(); renderCompact();
        api.post('/orbit/spotify/play', { uri: t.uri, context: this.q.context || '' }).then((r) => {
          this.qBusy = false;
          if (r?.msg && r.msg !== 'Tocando.') Orbit.banner('Spotify', r.msg, 'warn', 3000);
          this.recheck(); setTimeout(() => this.loadQueue(), 600);
        });
        return;
      }
      if (e.target.closest('[data-qconnect]')) { api.openSettings('permissoes'); return; }
      if (e.target.closest('[data-lyr]')) { this.queueOn = false; this.lyricsOn = !this.lyricsOn; this.lastKey = null; this.render(); return; }
      const p = e.target.closest('[data-pick]');
      if (p) { this.sel = p.dataset.pick; this.render(); return; }
      const b = e.target.closest('[data-a]');
      if (!b || b.disabled) return;
      const id = b.closest('[data-sid]')?.dataset.sid;
      const action = b.dataset.a;
      // Mostra o resultado na hora; a confirmação do player vem logo depois.
      const s = this.now.sessions.find((x) => x.id === id);
      if (s && action === 'play_pause') { s.position = this.pos(s); this.at = Date.now(); s.playing = !s.playing; this.render(); renderCompact(); }
      if (s && action.startsWith('seek_')) {
        // -10/+10 viram "pular para" uma posição exata: cliques seguidos se juntam num pulo só.
        const position = Math.max(0, Math.min(s.duration || Infinity, this.pos(s) + (action === 'seek_forward' ? 10 : -10)));
        s.position = position; this.at = Date.now(); this.renderProgress();
        this.seek(id, position);
        return;
      }
      api.post('/orbit/media/' + action, action.startsWith('volume') ? {} : { id });
      this.recheck();
    });
    this.render();
  },
  show() { this.refresh(); },
  card(s, big) {
    const can = s.can || {};
    const btn = (a, label, on, why, extra = '') =>
      `<button class="btn round ${a === 'play_pause' ? 'primary tint' : ''}" data-a="${a}" ${on ? '' : 'disabled'} title="${on ? label : why}"
        style="${on ? '' : 'opacity:.35;'}${extra}">${a.startsWith('seek') ? (a === 'seek_back' ? '-10' : '+10') : icon({ previous: 'prev', next: 'next', play_pause: s.playing ? 'pause' : 'play' }[a], a === 'play_pause' ? 18 : 16)}</button>`;
    const size = big ? 128 : 76;
    return `<div class="card hero row" data-sid="${esc(s.id)}" style="${brand(s.app)};gap:14px;align-items:stretch;padding:12px">
      <div style="width:${size}px;height:${size}px;border-radius:${big ? 18 : 12}px;flex:none;background:var(--card2) ${s.art ? `url('${s.art}') center/cover` : ''};display:grid;place-items:center;color:var(--faint)">${s.art ? '' : icon('music', big ? 34 : 22)}</div>
      <div class="col" style="flex:1;min-width:0;justify-content:center;gap:3px">
        <div class="faint"><span class="tint-text" style="font-weight:600">${esc(s.app || '')}</span>${s.title && !s.playing ? ' · pausado' : ''}</div>
        <div class="title" style="font-size:${big ? 16 : 14}px;display:-webkit-box;-webkit-line-clamp:${big ? 2 : 1};-webkit-box-orient:vertical;overflow:hidden">${esc(s.title || 'Nada tocando')}</div>
        <div class="muted-text ellipsis">${esc([s.artist, s.album].filter(Boolean).join(' — '))}</div>
        ${s.duration ? `<div data-prog style="margin-top:4px"><div data-seek title="${can.seek ? 'Clique para pular para este ponto' : ''}"
          style="padding:6px 0;margin:-6px 0;${can.seek ? 'cursor:pointer' : ''}"><div class="bar"><i style="width:0"></i></div></div>
          <div class="row faint" style="margin-top:3px;font-variant-numeric:tabular-nums;font-size:11px"><span data-pos>0:00</span><span style="flex:1"></span><span>${mmss(s.duration)}</span></div></div>` : ''}
        <div class="row" style="margin-top:6px;gap:6px">
          ${btn('previous', 'Anterior', can.previous !== false, 'Este player não deixa voltar')}
          ${btn('seek_back', 'Voltar 10 s', !!can.seek, 'Este player não deixa voltar segundos', 'font-size:11px;font-weight:700')}
          ${btn('play_pause', 'Tocar/pausar', true, '')}
          ${btn('seek_forward', 'Avançar 10 s', !!can.seek, 'Este player não deixa avançar segundos', 'font-size:11px;font-weight:700')}
          ${btn('next', 'Próxima', can.next !== false, 'Este player não deixa pular (no YouTube, só em playlist)')}
          <span style="flex:1"></span>
          ${/spotify/i.test(s.app || '') ? `<button class="btn" style="height:30px;padding:0 12px;${this.queueOn ? 'background:color-mix(in srgb,var(--tint) 25%,var(--card2))' : ''}" data-q title="Próximas músicas (Spotify)">Fila</button>` : ''}
          ${this.hasLyrics(s) ? `<button class="btn" style="height:30px;padding:0 12px;${this.lyricsOn ? 'background:color-mix(in srgb,var(--tint) 25%,var(--card2))' : ''}" data-lyr title="Letra (busca online no lrclib.net)">Letra</button>` : ''}
        </div>
      </div></div>`;
  },
  render() {
    if (!this.view || this.dragging) return; // não redesenha no meio de um arraste
    const list = this.now.sessions || [];
    // Só redesenha quando muda algo além do tempo (a barra anda sozinha em renderProgress).
    const key = this.sel + this.lyricsOn + this.queueOn + JSON.stringify(this.q || null) + JSON.stringify(list.map((s) => [s.id, s.title, s.artist, s.playing, s.art && s.art.length, s.can, s.duration]));
    if (key === this.lastKey && this.view.childElementCount) { this.renderProgress(); return; }
    this.lyrLine = null;
    this.lastKey = key;
    if (!list.length || !list[0].title) {
      this.view.innerHTML = `<div class="empty">Nada tocando.<br><span class="faint">Toque algo no Spotify, YouTube ou outro player.</span></div>`;
      return;
    }
    // Um cartão grande por vez; com vários players, abas no topo (com a cor da marca) trocam entre eles.
    // Sem escolha sua, mostra o que está tocando.
    if (!list.some((s) => s.id === this.sel)) this.sel = null;
    const cur = list.find((s) => s.id === this.sel) || list.find((s) => s.playing) || list[0];
    const tabs = list.length > 1 ? `<div class="row ptabs" style="gap:6px;margin-bottom:8px">${list.slice(0, 5).map((s) => `
      <button class="ptab ${s.id === cur.id ? 'on' : ''}" data-pick="${esc(s.id)}" style="${brand(s.app)}">
        <i style="background:var(--tint)"></i>${esc(s.app || 'Player')}${s.playing ? ' <span class="eq mini"><i></i><i></i><i></i></span>' : ''}</button>`).join('')}</div>` : '';
    this.cur = cur;
    if (this.lyricsOn) this.loadLyrics(cur);
    const qScroll = this.view.querySelector('.qbox')?.scrollTop || 0; // redesenhar não pode jogar a fila para o topo
    if (this.lyricsOn && !this.hasLyrics(cur)) this.lyricsOn = false;
    const side = this.lyricsOn || (this.queueOn && /spotify/i.test(cur.app || ''));
    this.view.innerHTML = tabs + `<div class="list pslide">${this.card(cur, !side)}</div>
      ${this.queueOn && /spotify/i.test(cur.app || '') ? `<div class="card lyr qbox" style="${brand(cur.app)}">${this.queueHtml()}</div>` : ''}
      ${this.lyricsOn ? `<div class="card lyr" style="${brand(cur.app)}">${this.lyricsHtml(cur)}</div>` : ''}
      <div class="row" style="justify-content:flex-end;gap:6px;margin-top:8px">
        <span class="faint" style="margin-right:4px">Volume geral</span>
        <button class="btn round" data-a="volume_down" title="Volume -">${icon('volDown', 16)}</button>
        <button class="btn round" data-a="volume_up" title="Volume +">${icon('volUp', 16)}</button>
      </div>`;
    const qb = this.view.querySelector('.qbox'); if (qb) qb.scrollTop = qScroll;
    this.renderProgress();
  },
  // Letra só em player de música (Spotify, Apple Music, VLC...); vídeo no navegador não tem.
  hasLyrics(s) { return !/youtube|chrome|edge|opera|firefox|brave|navegador/i.test(s.app || ''); },
  // ---- fila do Spotify (pela conta conectada nas Configurações) ----
  async loadQueue() {
    const r = await api.get('/orbit/spotify?queue=1');
    this.q = r || { error: '%A% está fora do ar.' };
    this.render();
  },
  queueHtml() {
    const q = this.q;
    if (!q) return '<div class="faint" style="text-align:center;padding:18px 0"><span class="spin"></span> Lendo a fila…</div>';
    if (!q.connected) return `<div class="faint" style="text-align:center;padding:14px 0">Conecte sua conta do Spotify para ver a fila.<br><button class="btn" style="height:28px;margin-top:8px" data-qconnect>Conectar Spotify</button></div>`;
    if (q.error) return `<div class="faint" style="text-align:center;padding:18px 0">${esc(q.error)}</div>`;
    if (!q.queue?.length) return '<div class="faint" style="text-align:center;padding:18px 0">A fila está vazia.</div>';
    return q.queue.map((t, i) => `<div class="row qrow" data-skip="${i}" title="Pular para esta">
      ${t.art ? `<img class="art" src="${esc(t.art)}">` : `<span class="art"></span>`}
      <span class="ellipsis" style="flex:1"><b>${esc(t.name)}</b> <span class="faint">${esc(t.artist)}</span></span>
      <span class="faint">${t.duration ? mmss(t.duration) : ''}</span></div>`).join('');
  },
  // ---- letra ----
  lyr: {},
  lkey(s) { return (s.artist || '') + '|' + (s.title || ''); },
  async loadLyrics(s) {
    const k = this.lkey(s);
    if (this.lyr[k]) return;
    this.lyr[k] = { loading: true };
    const r = await api.lyrics(s.artist || '', s.title || '', s.duration || 0);
    const lines = (r?.synced || '').split('\n').map((l) => /^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$/.exec(l)).filter(Boolean)
      .map((m) => ({ t: +m[1] * 60 + +m[2], text: m[3] }));
    this.lyr[k] = { lines, plain: r?.plain || '', busy: !r || r.busy };
    this.lastKey = null; this.render();
  },
  lyricsHtml(s) {
    const L = this.lyr[this.lkey(s)];
    if (!L || L.loading) return '<div class="faint" style="text-align:center;padding:18px 0"><span class="spin"></span> Buscando a letra…</div>';
    if (L.lines.length) return '<div class="lyr-in" data-lyrin>' + L.lines.map((l, i) => `<div data-l="${i}">${esc(l.text) || '♪'}</div>`).join('') + '</div>';
    if (L.plain) return '<div class="lyr-in plain">' + esc(L.plain).replace(/\n/g, '<br>') + '</div>';
    if (L.busy) return '<div class="faint" style="text-align:center;padding:18px 0">O site das letras não respondeu. <button class="btn" style="height:26px;margin-left:6px" data-lyrretry>Tentar de novo</button></div>';
    return '<div class="faint" style="text-align:center;padding:18px 0">Não achei a letra desta música.</div>';
  },
  // Tempo da letra: no Spotify conectado, a posição exata da conta (a do Windows atrasa e dá saltos);
  // entre uma leitura e outra o relógio do PC anda sozinho. Nos outros players, a posição do Windows.
  spClock: null,
  async syncSpotify() {
    if (this.spOff && Date.now() < this.spOff) return; // Spotify não conectado: não fica perguntando
    const r = await api.get('/orbit/spotify?now=1');
    if (r && !r.connected) { this.spOff = Date.now() + 60000; return; }
    if (r?.now && r.now.name && this.spHold && performance.now() < this.spHold && this.spClock) {
      const c = this.spClock, guess = c.pos + (c.playing ? (performance.now() - c.at) / 1000 : 0);
      if (Math.abs(r.now.progress - guess) > 2) return; // leitura de antes do pulo
    }
    if (r?.now && r.now.name) this.spClock = { pos: r.now.progress, at: performance.now(), playing: r.now.playing, name: r.now.name };
  },
  lyricsTime(s) {
    const c = this.spClock;
    if (/spotify/i.test(s.app || '') && c && c.name === s.title) return c.pos + (c.playing ? (performance.now() - c.at) / 1000 : 0);
    return this.pos(s);
  },
  // Um quadro por vez (requestAnimationFrame) só enquanto a letra está aberta; a lista desliza com transform,
  // sem rolar a caixa nem redesenhar a aba, então não disputa com o resto da ilha.
  lyricsLoop() {
    if (this.lyrRaf) return;
    const tick = () => {
      const open = this.lyricsOn && Orbit.mode === 'expanded' && Orbit.tab === 'midia';
      if (!open) { this.lyrRaf = null; return; }
      this.lyrRaf = requestAnimationFrame(tick);
      this.renderLyrics();
    };
    this.syncSpotify();
    this.lyrRaf = requestAnimationFrame(tick);
  },
  renderLyrics() {
    const s = this.cur, box = this.view?.querySelector('[data-lyrin]');
    const L = s && this.lyr[this.lkey(s)];
    if (!box || !L?.lines?.length) return;
    const p = this.lyricsTime(s) + 0.25;
    let i = -1;
    for (let j = 0; j < L.lines.length && L.lines[j].t <= p; j++) i = j;
    if (i === this.lyrLine && box === this.lyrEl) return;
    this.lyrLine = i; this.lyrEl = box;
    box.querySelector('.on')?.classList.remove('on');
    const el = box.children[Math.max(0, i)];
    if (i >= 0) el.classList.add('on');
    const h = box.parentElement.clientHeight;
    box.style.transform = `translateY(${Math.round(h / 2 - el.offsetTop - el.offsetHeight / 2)}px)`;
  },
  renderProgress() {
    if (!this.view) return;
    if (this.lyricsOn) this.lyricsLoop();
    for (const s of this.now.sessions || []) {
      const el = this.view.querySelector(`[data-sid="${CSS.escape(s.id)}"] [data-prog]`);
      if (!el || !s.duration) continue;
      const p = this.pos(s);
      el.querySelector('i').style.width = (100 * p / s.duration).toFixed(2) + '%';
      el.querySelector('[data-pos]').textContent = mmss(p);
    }
  },
});
