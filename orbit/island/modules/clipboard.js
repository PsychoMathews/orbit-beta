// Histórico da área de transferência (texto). Clique num item para copiar de novo.
Orbit.register({
  id: 'clipboard',
  clips: [],
  async start() { this.clips = await api.clips(); },
  onEvent(ev) { if (ev.type === 'clipboard') { this.clips = ev.clips; this.render(); } },
  mount(view) {
    view.innerHTML = `
      <div class="row" style="margin-bottom:8px">
        <input class="input" id="cb-q" placeholder="Buscar no que você copiou…" spellcheck="false">
        <button class="btn round danger" id="cb-clear" title="Limpar histórico">${icon('trash', 16)}</button>
      </div>
      <div class="list" id="cb-list"></div>`;
    this.$ = (s) => view.querySelector(s);
    const q = this.$('#cb-q');
    q.addEventListener('mousedown', () => api.focus(true));
    q.addEventListener('blur', () => api.focus(false));
    q.oninput = () => this.render();
    this.$('#cb-clear').onclick = () => api.clearClips();
    this.render();
  },
  render() {
    if (!this.$) return;
    const q = this.$('#cb-q').value.toLowerCase();
    const items = this.clips.filter((c) => !q || c.text.toLowerCase().includes(q));
    const list = this.$('#cb-list');
    list.innerHTML = items.map((c, i) => `
      <div class="item click" data-i="${i}" title="Clique para copiar">
        <span class="ellipsis" style="flex:1">${esc(c.text.replace(/\s+/g, ' ').slice(0, 200))}</span>
        <span class="faint">${hhmm(c.t)}</span><span class="muted-text">${icon('copy', 14)}</span>
      </div>`).join('') || '<div class="empty">Nada copiado ainda.</div>';
    list.querySelectorAll('[data-i]').forEach((it) => {
      it.onclick = () => { api.copy(items[+it.dataset.i].text); Orbit.banner('Copiado', items[+it.dataset.i].text.slice(0, 140), '', 1800); };
    });
  },
});
