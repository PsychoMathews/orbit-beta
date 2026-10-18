// Som: volume geral e por programa (mixer do Windows), pela ponte do bot (audio.py).
Orbit.register({
  id: 'som',
  data: null,
  out: null,
  start() { this.loadOut(); },
  async loadOut() { const o = await api.get('/orbit/audio/outputs'); if (o) { this.out = o; this.render(); renderCompact(); } },
  onEvent(ev) { if (ev.type === 'mic' && this.out) { this.out.micMuted = ev.muted; this.render(); renderCompact(); } },
  // Microfone mudo fica avisado na pílula (para não falar numa chamada achando que está ligado, ou o contrário).
  live() {
    if (!this.out?.micMuted) return null;
    return { priority: 0.3, width: 230, left: `<span style="color:var(--bad)">${icon('micOff', 16)}</span>`, mid: '<span class="t">Microfone mudo</span>', right: '' };
  },
  short(n) { return String(n || '').replace(/\s*\(.*\)\s*$/, '') || n; },
  async setOut(body) {
    const r = await api.post('/orbit/audio/output', body);
    if (r?.msg) Orbit.banner('Som', r.msg, '', 2500);
    await this.loadOut(); this.refresh();
  },
  async refresh() {
    const r = await api.get('/orbit/audio');
    if (r) { this.data = r; this.failed = false; this.render(); }
    else if (!this.data) { this.failed = true; this.render(); }
  },
  mount(view) {
    this.view = view;
    // Cada canal guarda só o último valor arrastado; um envio por vez, sempre o mais recente.
    // (Antes um temporizador único fazia mexer no canal B cancelar o envio do A, que ficava no valor antigo.)
    view.addEventListener('input', (e) => {
      const r = e.target.closest('input[type=range]');
      if (!r) return;
      r.parentElement.querySelector('output').textContent = r.value + '%';
      this.pending.set(r.dataset.app, { app: r.dataset.app, volume: +r.value });
      this.flush();
    });
    view.addEventListener('change', (e) => {
      const sel = e.target.closest('select[data-route]');
      if (sel) this.setOut({ app: sel.dataset.route, device: sel.value });
    });
    view.addEventListener('click', (e) => {
      const o = e.target.closest('[data-out]');
      if (o) { this.setOut({ device: o.dataset.out }); return; }
      if (e.target.closest('[data-mic]')) { this.setOut({ mic: !this.out?.micMuted }); return; }
      const b = e.target.closest('[data-mute]');
      if (!b) return;
      this.pending.set(b.dataset.mute + ':mute', { app: b.dataset.mute, mute: b.dataset.muted !== '1' });
      this.flush(true);
    });
    this.render();
  },
  pending: new Map(),
  async flush(rerender) {
    if (this.busy) { if (rerender) this.again = true; return; } // o envio em andamento pega o que entrou na fila
    this.busy = true;
    try {
      while (this.pending.size) {
        const [key, body] = this.pending.entries().next().value;
        this.pending.delete(key);
        const r = await api.post('/orbit/audio', body);
        if (r) this.data = r;
      }
    } finally {
      this.busy = false;
    }
    if (rerender || this.again) { this.again = false; this.render(); }
  },
  show() { this.refresh(); this.loadOut(); this.timer = setInterval(() => { if (!this.busy && !this.view.querySelector('input:active')) this.refresh(); }, 3000); },
  hide() { clearInterval(this.timer); },
  row(id, name, vol, muted, sub) {
    return `<div class="item" style="gap:12px;padding:8px 12px">
      <button class="btn round" style="width:32px;height:32px;${muted ? 'background:var(--bad);color:#fff' : ''}" data-mute="${esc(id)}" data-muted="${muted ? 1 : 0}" title="${muted ? 'Tirar do mudo' : 'Mudo'}">${icon(muted ? 'micOff' : 'volUp', 15)}</button>
      <div style="width:150px;min-width:0"><div class="ellipsis">${esc(name)}</div>${sub ? `<div class="faint ellipsis">${esc(sub)}</div>` : ''}</div>
      <input type="range" min="0" max="100" value="${vol}" data-app="${esc(id)}" style="flex:1;accent-color:var(--tint)">
      <output class="faint" style="width:38px;text-align:right">${vol}%</output>
      ${id !== 'master' && id !== 'sistema' && this.out?.outputs?.length > 1 ? `<select class="osel" data-route="${esc(id)}" title="Saída deste programa">
        <option value="">Padrão</option>${this.out.outputs.map((o) => `<option value="${esc(o.id)}" ${this.out.apps?.[id] === o.id ? 'selected' : ''}>${esc(this.short(o.name))}</option>`).join('')}</select>` : ''}</div>`;
  },
  render() {
    if (!this.view) return;
    const d = this.data;
    if (!d) { this.view.innerHTML = this.failed ? failNote('o mixer') : '<div class="empty">Carregando o mixer…</div>'; return; }
    const o = this.out;
    const outs = o?.outputs?.length ? `<div class="row" style="gap:6px;flex-wrap:wrap;margin-bottom:8px">
      <span class="faint" style="margin-right:2px">Saída</span>
      ${o.outputs.map((x) => `<button class="ptab${x.id === o.default ? ' on' : ''}" data-out="${esc(x.id)}" title="${esc(x.name)}">${icon(/fone|headset|head|earphone/i.test(x.name) ? 'headset' : 'volUp', 13)} ${esc(this.short(x.name))}</button>`).join('')}
      <span style="flex:1"></span>
      ${o.mic ? `<button class="ptab${o.micMuted ? ' on' : ''}" data-mic title="${esc(o.mic)} · Ctrl+Alt+M" style="${o.micMuted ? 'color:var(--bad)' : ''}">${icon(o.micMuted ? 'micOff' : 'mic', 13)} ${o.micMuted ? 'Mic mudo' : 'Mic ligado'}</button>` : ''}
    </div>` : '';
    this.view.innerHTML = outs + `<div class="list">
      ${this.row('master', 'Volume geral', d.master, d.masterMuted, d.device)}
      <div class="faint" style="margin:6px 4px 0">Programas com som</div>
      ${d.apps.map((a) => this.row(a.id, a.name, a.volume, a.muted, a.active ? 'tocando agora' : '')).join('') || '<div class="empty">Nenhum programa com áudio aberto.</div>'}
    </div>
    <div class="faint" style="text-align:center;margin-top:10px">Também por voz: “%nome%, Spotify a 30%”, “joga o Discord no fone”, “muta o microfone”.</div>`;
  },
});
