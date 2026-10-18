// Timers: moram na assistente (hub.py). Criados aqui, por voz, Telegram ou Alexa, tocam no PC, no Telegram e na ilha.
Orbit.register({
  id: 'timer',
  timers: [],
  syncedAt: 0,
  async refresh() {
    const r = await api.get('/orbit/timers');
    if (r) this.set(r.timers);
  },
  set(list) { this.timers = list; this.syncedAt = Date.now(); this.render(); renderCompact(); },
  start() { this.refresh(); setInterval(() => { if (this.timers.length) { this.render(); } }, 1000); },
  onEvent(ev) {
    if (ev.type === 'timers') this.set(ev.timers);
    if (ev.type === 'hello' || ev.type === 'online') this.refresh();
  },
  left(t) { return t.paused != null ? t.paused : t.left - (Date.now() - this.syncedAt) / 1000; },
  async add(minutes, label) {
    const r = await api.post('/orbit/timers/start', { minutes, label });
    if (!r) Orbit.banner('Timer', '%A% está fora do ar; o timer precisa dela para tocar em todo lugar.', 'bad', 5000);
  },
  live() {
    if (!Orbit.cfg.island.liveTimer) return null;
    const t = this.timers.filter((x) => x.paused == null).sort((a, b) => a.left - b.left)[0];
    if (!t) return null;
    // Timer longe de acabar fica atrás da música; nos últimos 5 minutos ele toma a pílula.
    const soon = this.left(t) <= 300;
    return { priority: soon ? 2.5 : 0.8, width: 300, left: `<span style="color:var(--warn)">${icon('timer', 16)}</span>`,
      mid: `<span class="t">${esc(t.label)}</span>`, right: `<b style="color:var(--fg)">${mmss(this.left(t))}</b>` };
  },
  mount(view) {
    view.innerHTML = `
      <div class="col">
        <div class="row" style="flex-wrap:wrap;gap:6px">
          ${[1, 5, 10, 15, 30, 60].map((m) => `<button class="btn" data-m="${m}">${m < 60 ? m + ' min' : '1 h'}</button>`).join('')}
          <button class="btn" data-m="25" data-l="Pomodoro" style="color:var(--bad)">🍅 Pomodoro</button>
        </div>
        <form class="row" id="tm-form">
          <input class="input" id="tm-min" placeholder="Minutos" style="flex:0 0 110px" inputmode="decimal">
          <input class="input" id="tm-label" placeholder="Nome (opcional)">
          <button class="btn round primary tint" title="Iniciar">${icon('plus', 17)}</button>
        </form>
        <div class="list" id="tm-list"></div>
        <div class="faint" style="text-align:center">Toca aqui e nas caixas de som. Também dá pra pedir: “%nome%, timer de 10 minutos”.</div>
      </div>`;
    this.$ = (s) => view.querySelector(s);
    view.querySelectorAll('[data-m]').forEach((b) => { b.onclick = () => this.add(+b.dataset.m, b.dataset.l || b.textContent.trim()); });
    for (const i of view.querySelectorAll('input')) { i.addEventListener('mousedown', () => api.focus(true)); i.addEventListener('blur', () => api.focus(false)); }
    this.$('#tm-form').onsubmit = (e) => {
      e.preventDefault();
      const m = parseFloat(this.$('#tm-min').value.replace(',', '.'));
      if (!(m > 0)) return;
      this.add(m, this.$('#tm-label').value.trim() || `${m} min`);
      this.$('#tm-min').value = ''; this.$('#tm-label').value = '';
    };
    this.$('#tm-list').addEventListener('click', (e) => {
      const b = e.target.closest('[data-act]');
      if (!b) return;
      const id = b.closest('[data-id]').dataset.id;
      api.post('/orbit/timers/' + b.dataset.act, { id });
    });
    this.render();
  },
  render() {
    if (!this.$) return;
    this.$('#tm-list').innerHTML = this.timers.map((t) => {
      const left = this.left(t), pct = 100 * (1 - left / t.total);
      return `<div class="item hero" data-id="${t.id}">
        <div style="flex:1;min-width:0"><div class="row"><span class="ellipsis" style="flex:1">${esc(t.label)}</span>
        <b style="font-variant-numeric:tabular-nums;font-size:16px">${mmss(left)}</b></div>
        <div class="bar" style="margin-top:6px"><i style="width:${pct}%;background:var(--warn)"></i></div></div>
        <button class="btn round" data-act="pause" title="${t.paused != null ? 'Continuar' : 'Pausar'}">${icon(t.paused != null ? 'play' : 'pause', 14)}</button>
        <button class="btn round" data-act="cancel" title="Cancelar">${icon('x', 15)}</button></div>`;
    }).join('') || '<div class="empty" style="padding:14px 0">Nenhum timer rodando.</div>';
  },
});
