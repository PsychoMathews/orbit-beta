// DaVinci Resolve: projeto e timeline abertos, fila de render com progresso. Render rodando aparece na pílula.
Orbit.register({
  id: 'davinci',
  data: null,
  async refresh() {
    const r = await api.get('/orbit/resolve');
    this.failed = !r;
    if (r) this.data = r;
    this.render(); renderCompact();
  },
  start() {
    // Mais rápido enquanto renderiza; devagar quando não.
    const loop = async () => { await this.refresh(); setTimeout(loop, this.data?.rendering || (Orbit.mode === 'expanded' && Orbit.tab === 'davinci') ? 3000 : 15000); };
    loop();
  },
  active() { return (this.data?.jobs || []).find((j) => /render/i.test(j.status) && !/conclu|complete|fail|cancel/i.test(j.status)); },
  live() {
    if (!this.data?.rendering) return null;
    const j = this.active();
    const pct = j ? j.progress : 0;
    return { priority: 2, width: 330, left: `<span style="color:#ff6b6b">${icon('film', 16)}</span>`,
      mid: `<span class="t">Render ${j ? esc(j.name) : ''}</span>`, right: `<b style="color:var(--fg)">${pct}%</b>` };
  },
  mount(view) { this.view = view; this.render(); },
  show() { this.loading = true; this.render(); this.refresh().finally(() => { this.loading = false; this.render(); }); },
  render() {
    if (!this.view) return;
    const d = this.data;
    // O script do DaVinci leva alguns segundos: esqueleto do layout em vez de tela vazia.
    if (!d) { this.view.innerHTML = this.failed ? failNote('o DaVinci') : `<div class="card hero row" style="margin-bottom:8px"><span class="mark"><i class="spin" style="width:20px;height:20px"></i></span>
      <div style="flex:1"><div class="title">Conversando com o DaVinci…</div><div class="faint">o Resolve demora alguns segundos para responder</div></div></div>
      <div class="list"><div class="skel" style="height:48px"></div><div class="skel" style="height:48px;opacity:.6"></div></div>`; return; }
    if (!d.running) { this.view.innerHTML = '<div class="empty">DaVinci Resolve fechado (ou sem projeto aberto).</div>'; return; }
    const jobs = d.jobs.map((j) => {
      const done = /conclu|complete/i.test(j.status), bad = /fail|falh|cancel/i.test(j.status);
      return `<div class="item"><div style="flex:1;min-width:0">
        <div class="row"><span class="ellipsis" style="flex:1">${esc(j.name)}</span>
        <span class="chip" style="color:${done ? 'var(--ok)' : bad ? 'var(--bad)' : 'var(--warn)'}">${esc(j.status)}</span></div>
        <div class="bar" style="margin-top:6px"><i style="width:${j.progress || 0}%;background:${done ? 'var(--ok)' : bad ? 'var(--bad)' : 'var(--warn)'}"></i></div>
      </div><b style="min-width:42px;text-align:right">${j.progress || 0}%</b></div>`;
    }).join('');
    this.view.innerHTML = `
      <div class="card hero row" style="margin-bottom:8px">
        <span class="mark">${icon('film', 22)}</span>
        <div style="flex:1;min-width:0"><div class="title ellipsis">${esc(d.project)}${this.loading ? ' <i class="spin" title="Atualizando"></i>' : ''}</div>
        <div class="faint ellipsis">${d.timeline ? 'Timeline: ' + esc(d.timeline) : 'Sem timeline aberta'}</div></div>
        <span class="chip" style="color:${d.rendering ? 'var(--warn)' : d.playing ? 'var(--ok)' : 'var(--dim)'}">${d.rendering ? 'Renderizando' : d.playing ? '▶ Tocando' : d.busy ? 'Ocupado' : 'Parado'}</span>
      </div>
      <div class="list">${jobs || '<div class="empty" style="padding:16px 0">Fila de render vazia.</div>'}</div>`;
  },
});
