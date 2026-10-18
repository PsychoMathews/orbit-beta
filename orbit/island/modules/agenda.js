// Agenda: próximos eventos do Google Agenda (pela ponte do bot). Mostra na pílula quando falta pouco.
Orbit.register({
  id: 'agenda',
  data: null,
  async refresh() {
    const r = await api.get('/orbit/agenda');
    this.failed = !r;
    if (r) this.data = r;
    this.render(); renderCompact();
  },
  start() { this.refresh(); setInterval(() => this.refresh(), 120000); },
  next() {
    const now = Date.now();
    return (this.data?.events || []).find((e) => e.start.length > 10 && new Date(e.end) > now);
  },
  live() {
    const e = this.next();
    if (!e) return null;
    const mins = Math.round((new Date(e.start) - Date.now()) / 60000);
    if (mins > 15) return null;
    const label = mins > 0 ? `em ${mins} min` : 'agora';
    return { priority: mins <= 5 ? 3 : 2, width: 330, left: `<span style="color:var(--warn)">${icon('calendar', 16)}</span>`,
      mid: `<span class="t">${esc(e.title)}</span>`, right: label };
  },
  mount(view) {
    this.view = view;
    view.innerHTML = `<div class="row" style="gap:6px;margin-bottom:8px">
      <button class="ptab on" data-av="next">Próximos</button><button class="ptab" data-av="month">Mês</button></div><div data-body></div>`;
    this.body = view.querySelector('[data-body]');
    view.addEventListener('click', (e) => { const b = e.target.closest('[data-done]'); if (b) { e.stopPropagation(); this.toggleDone(b.dataset.done); } }, true);
    view.querySelectorAll('[data-av]').forEach((b) => b.onclick = () => {
      this.mode = b.dataset.av;
      view.querySelectorAll('[data-av]').forEach((x) => x.classList.toggle('on', x === b));
      this.mode === 'month' ? this.loadMonth() : this.render();
    });
    this.render();
  },
  mode: 'next', month: null, sel: null, months: {},
  // Evento de dia inteiro (que não seja feriado) vira tarefa: dá para marcar como feito.
  isTask(e) { return !e.holiday && e.start.length <= 10 && e.id; },
  chk(e) { return this.isTask(e) ? `<button class="chk${e.done ? ' on' : ''}" data-done="${esc(e.id)}" title="${e.done ? 'Desmarcar' : 'Marcar como feito'}">${icon('check', 11)}</button>` : ''; },
  async toggleDone(id) {
    const all = [...(this.data?.events || []), ...Object.values(this.months).flat()].filter((e) => e.id === id);
    if (!all.length) return;
    const done = !all[0].done;
    all.forEach((e) => { e.done = done; });
    this.mode === 'month' ? this.renderMonth() : this.render();
    await api.post('/orbit/agenda/done', { id, done, title: all[0].title });
  },
  show() { this.refresh(); if (this.mode === 'month') this.loadMonth(); },
  mkey(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'); },
  async loadMonth(shift = 0) {
    const base = this.month || new Date(new Date().setDate(1));
    this.month = new Date(base.getFullYear(), base.getMonth() + shift, 1);
    if (!this.sel || shift) this.sel = shift ? null : new Date().toDateString();
    const k = this.mkey(this.month);
    if (!this.months[k]) this.body.innerHTML = '<div class="skel" style="height:300px"></div>';
    this.renderMonth();
    const r = await api.get('/orbit/agenda?month=' + k);
    if (r) { this.months[k] = r.events || []; this.connected = r.connected; }
    this.renderMonth();
  },
  dayOf(e) { return new Date(e.start.length <= 10 ? e.start + 'T12:00' : e.start).toDateString(); },
  renderMonth() {
    if (this.mode !== 'month' || !this.month) return;
    const ev = this.months[this.mkey(this.month)];
    if (!ev) return;
    if (this.connected === false) { this.body.innerHTML = '<div class="empty">Google não conectado.</div>'; return; }
    const y = this.month.getFullYear(), m = this.month.getMonth(), first = (new Date(y, m, 1).getDay() + 6) % 7; // semana começa na segunda
    const days = new Date(y, m + 1, 0).getDate(), today = new Date().toDateString();
    const byDay = {};
    ev.forEach((e) => (byDay[this.dayOf(e)] ||= []).push(e));
    const hol = (list) => (list || []).find((e) => e.holiday === 'feriado');
    let cells = '';
    for (let i = 0; i < first; i++) cells += '<span></span>';
    for (let d = 1; d <= days; d++) {
      const ds = new Date(y, m, d).toDateString(), list = byDay[ds] || [], h = hol(list);
      const n = list.filter((e) => !e.holiday && !e.done).length;
      cells += `<button class="cday${ds === today ? ' today' : ''}${ds === this.sel ? ' sel' : ''}${h ? ' holi' : ''}" data-day="${ds}" title="${esc(h ? h.title : '')}">${d}
        <span class="dots">${h ? '<i class="h"></i>' : ''}${'<i></i>'.repeat(Math.min(h ? 2 : 3, n))}</span></button>`;
    }
    const selEv = this.sel ? byDay[this.sel] || [] : ev.filter((e) => (e.holiday ? e.holiday === 'feriado' : true) && new Date(e.end) >= new Date());
    const title = this.sel ? dayLabel(this.sel) + ' · ' + new Date(this.sel).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long' }) : 'Resto do mês';
    this.body.innerHTML = `<div class="row" style="align-items:flex-start;gap:12px">
      <div class="card" style="width:286px;flex:none;padding:10px 12px">
        <div class="row" style="margin-bottom:6px"><button class="btn round" style="width:28px;height:28px" data-mv="-1">${icon('left', 14)}</button>
          <b style="flex:1;text-align:center;text-transform:capitalize">${this.month.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })}</b>
          <button class="btn round" style="width:28px;height:28px" data-mv="1">${icon('right', 14)}</button></div>
        <div class="cal">${['S', 'T', 'Q', 'Q', 'S', 'S', 'D'].map((l) => `<span class="faint">${l}</span>`).join('')}${cells}</div>
      </div>
      <div style="flex:1;min-width:0"><div class="faint" style="margin:2px 4px 6px;text-transform:capitalize">${title}</div>
        <div class="list">${selEv.slice(0, 30).map((e) => {
          const allDay = e.start.length <= 10;
          if (e.holiday) return `<div class="item holi-item"><span class="when">${this.sel ? '' : new Date(this.dayOf(e)).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' '}${e.holiday === 'feriado' ? 'Feriado' : 'Data'}</span>
            <span class="ellipsis" style="flex:1">${esc(e.title)}</span></div>`;
          return `<div class="item${e.page ? ' click' : ''}${e.done ? ' done' : ''}" data-page="${esc(e.page || '')}">${this.chk(e)}<span class="when">${this.sel ? '' : new Date(this.dayOf(e)).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' '}${allDay ? 'Dia todo' : hhmm(e.start)}</span>
            <span class="ellipsis strike" style="flex:1">${esc(e.title)}${e.where ? `<span class="faint"> · ${esc(e.where)}</span>` : ''}</span></div>`;
        }).join('') || '<div class="empty" style="padding:20px 0">Nada marcado.</div>'}</div></div></div>`;
    this.body.querySelectorAll('[data-day]').forEach((b) => b.onclick = () => { this.sel = this.sel === b.dataset.day ? null : b.dataset.day; this.renderMonth(); });
    this.body.querySelectorAll('[data-mv]').forEach((b) => b.onclick = () => this.loadMonth(+b.dataset.mv));
    this.body.querySelectorAll('[data-page]').forEach((it) => { if (it.dataset.page) it.onclick = () => api.openUrl(it.dataset.page); });
  },
  render() {
    if (!this.view || this.mode !== 'next') return;
    const view = this.body;
    const d = this.data;
    if (!d) { view.innerHTML = this.failed ? failNote('a agenda') : '<div class="empty">Carregando a agenda…</div>'; return; }
    if (!d.connected) { view.innerHTML = '<div class="empty">Google não conectado. Peça para %a% conectar a agenda.</div>'; return; }
    if (!d.events.length) { view.innerHTML = '<div class="empty">Nada na agenda hoje nem amanhã. 🎉</div>'; return; }
    let lastDay = '';
    const nx = d.events.find((e) => e.start.length > 10 && new Date(e.end) > Date.now());
    view.innerHTML = (nx ? nextHero('calendar', new Date(nx.start) <= Date.now() ? 'Acontecendo agora' : 'Próximo compromisso', nx.title, new Date(nx.start).getTime()) : '') + '<div class="list">' + d.events.map((e) => {
      const allDay = e.start.length <= 10;
      const day = dayLabel(allDay ? e.start + 'T12:00' : e.start);
      const head = day !== lastDay ? `<div class="faint" style="margin:${lastDay ? 8 : 0}px 4px 2px">${day}</div>` : '';
      lastDay = day;
      const now = Date.now(), live = !allDay && new Date(e.start) <= now && new Date(e.end) > now;
      return head + `<div class="item ${e.link ? 'click' : ''} ${live ? 'hero' : ''}${e.done ? ' done' : ''}" data-link="${esc(e.link)}">${this.chk(e)}
        <span class="when">${allDay ? 'Dia todo' : hhmm(e.start) + '–' + hhmm(e.end)}</span>
        <span class="ellipsis strike" style="flex:1">${esc(e.title)}</span>
        ${live ? '<span class="chip" style="color:var(--ok)">agora</span>' : ''}
        ${e.link ? `<span class="muted-text">${icon('link', 15)}</span>` : ''}
      </div>`;
    }).join('') + '</div>';
    view.querySelectorAll('[data-link]').forEach((it) => { if (it.dataset.link) it.onclick = () => api.openUrl(it.dataset.link); });
  },
});
