// Histórico de avisos e respostas da assistente (lembretes, reuniões, e-mails, renders, timers).
Orbit.register({
  id: 'avisos',
  items: [],
  start() { try { this.items = JSON.parse(localStorage.getItem('orbit.avisos') || '[]'); } catch {} },
  addItem(title, text) {
    this.items.unshift({ title, text, t: Date.now() });
    this.items = this.items.slice(0, 50);
    try { localStorage.setItem('orbit.avisos', JSON.stringify(this.items)); } catch {}
    this.render();
  },
  onFriday(ev) {
    if (ev.type === 'notify' && ev.kind !== 'mute') this.addItem('Aviso', ev.text);
    if (ev.type === 'reply') this.addItem('Resposta', ev.text);
    if (ev.type === 'show') this.addItem(ev.title || '%nome%', ev.text);
  },
  mount(view) { this.view = view; this.render(); },
  render() {
    if (!this.view) return;
    this.view.innerHTML = `<div class="list">${this.items.map((x) => `
      <div class="item" style="align-items:flex-start"><span class="when">${dayLabel(x.t) === 'Hoje' ? hhmm(x.t) : dayLabel(x.t)}</span>
      <div style="flex:1;min-width:0"><div class="faint">${esc(x.title)}</div><div style="white-space:pre-wrap;user-select:text">${esc(x.text)}</div></div></div>`).join('')
      || '<div class="empty">Sem avisos por enquanto.</div>'}</div>`;
  },
});
