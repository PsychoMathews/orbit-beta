// Cartão do topo na cor da aba: o próximo item e quanto falta.
window.nextHero = function(ic, label, title, when) {
  const ms = when - Date.now(), m = Math.round(ms / 6e4);
  const rel = ms <= 0 ? 'agora' : m < 60 ? `em ${m} min` : m < 1440 ? `em ${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}` : dayLabel(when) + ' ' + hhmm(when);
  return `<div class="card hero row" style="gap:14px;margin-bottom:8px;padding:12px 16px"><span class="mark">${icon(ic, 26)}</span>
    <div style="flex:1;min-width:0"><div class="faint">${label}</div><div class="big" style="font-size:22px">${rel}</div>
    <div class="ellipsis muted-text">${esc(title)}</div></div></div>`;
};
// Lembretes pendentes criados pela assistente.
Orbit.register({
  id: 'lembretes',
  mount(view) { this.view = view; view.innerHTML = '<div class="empty">Carregando…</div>'; },
  async show() {
    const r = await api.get('/orbit/reminders');
    if (!r) { this.view.innerHTML = failNote('os lembretes'); return; }
    const items = r.reminders || [];
    const nx = items[0];
    this.view.innerHTML = (nx ? nextHero('bell', 'Próximo lembrete', nx.text, new Date(nx.when).getTime()) : '') + `
      <div class="list">${items.map((x) => `
        <div class="item"><span class="when" style="min-width:96px">${dayLabel(x.when)} ${hhmm(x.when)}</span>
        <span style="flex:1">${esc(x.text)}</span></div>`).join('') || '<div class="empty">Nenhum lembrete pendente.</div>'}
      </div>
      <div class="faint" style="text-align:center;margin-top:12px">Para criar: “%nome%, me lembra de … às …”</div>`;
  },
});
