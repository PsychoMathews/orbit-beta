// Faísca de raios no laranja do Claude (identidade da aba quando o agente é o Claude).
const SPARK = '<svg viewBox="0 0 24 24" width="30" height="30"><g fill="currentColor">' +
  [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330].map((a, i) => `<rect x="11" y="${i % 2 ? 3.5 : 1.5}" width="2" height="${i % 2 ? 8 : 10}" rx="1" transform="rotate(${a} 12 12)"/>`).join('') + '</g></svg>';
const CLAUDE = '#d97857';
const ts = (v) => (v == null ? null : typeof v === 'number' ? (v < 1e12 ? v * 1000 : v) : Date.parse(v));
const usd = (v) => '$' + (v || 0).toLocaleString('en-US', { minimumFractionDigits: v >= 1000 ? 0 : 2, maximumFractionDigits: v >= 1000 ? 0 : 2 });
const countdown = (ms) => {
  ms = Math.max(0, ms); const d = Math.floor(ms / 864e5), h = Math.floor(ms % 864e5 / 36e5), m = Math.floor(ms % 36e5 / 6e4);
  return d ? `${d}d ${h}h` : h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
};
// Cores por modelo (Opus no laranja do Claude, Sonnet e Haiku em tons próximos).
const modelTint = (m) => /opus|fable/i.test(m) ? CLAUDE : /sonnet/i.test(m) ? '#e8b48a' : /haiku/i.test(m) ? '#8fb3ff' : '#9a9aa2';
const modelName = (m) => m.replace(/^claude-/, '').replace(/-(\d+)-(\d+).*$/, ' $1.$2').replace(/^\w/, (c) => c.toUpperCase());

// Uso de IA no estilo da página de agentes do Vorssaint: cartões em grade, valor em API em destaque,
// barras de limite com o risco do "ritmo" (onde o uso estaria se fosse distribuído igual pela janela).
Orbit.register({
  id: 'ia',
  quota: null,
  tasks: [],
  period: 'week', // today | week | month
  start() {
    try { this.period = localStorage.getItem('orbit.ia.period') || 'week'; } catch {}
    api.get('/orbit/claude').then((q) => { if (q) { this.quota = q; this.tasks = q.tasks || []; } renderCompact(); });
  },
  onEvent(ev) {
    if (ev.type === 'claude_work') { this.tasks = ev.tasks || []; if (this.visible) this.render(); return; }
    if (ev.type === 'claude') { this.quota = { ...this.quota, ...ev }; renderCompact(); if (this.visible) this.render(); }
  },
  live() {
    const q = this.quota;
    if (this.tasks.length) {
      const t = this.tasks[0], s = Math.round(Date.now() / 1000 - t.start);
      if (s >= 20) return { priority: 0.4, width: 320, left: `<span class="mark" style="color:${CLAUDE};display:flex;animation:spin 3s linear infinite">${SPARK.replace(/30/g, '18')}</span>`,
        mid: `<span class="t">Claude trabalhando · ${esc(t.project)}${this.tasks.length > 1 ? ' +' + (this.tasks.length - 1) : ''}</span>`, right: mmss(s) };
    }
    if (!q || !q.limited) return null;
    return { priority: 0.5, width: 300, left: `<span style="color:${CLAUDE};display:flex">${SPARK.replace(/30/g, '18')}</span>`,
      mid: '<span class="t">Cota do Claude esgotada</span>', right: 'volta ' + hhmm(q.reset) };
  },
  mount(view) {
    this.view = view;
    view.innerHTML = '<div class="empty">Somando tokens…</div>';
    view.addEventListener('click', (e) => {
      const p = e.target.closest('[data-period]');
      if (p) { this.period = p.dataset.period; try { localStorage.setItem('orbit.ia.period', this.period); } catch {} this.render(); }
    });
  },
  show() { this.visible = true; this.poll(); this.timer = setInterval(() => this.poll(), 30000); this.clock = setInterval(() => this.render(), 15000); },
  hide() { this.visible = false; clearInterval(this.timer); clearInterval(this.clock); },
  async poll() {
    const [r, q] = await Promise.all([api.aiUsage(), api.get('/orbit/claude?history=1')]);
    if (q) { this.history = q.history; delete q.history; this.quota = q; this.tasks = q.tasks || this.tasks; }
    this.usage = r;
    this.failed = !r;
    this.render();
  },

  // Soma os dias do período escolhido.
  sum() {
    const days = this.usage?.claude?.days || {}, n = { today: 1, week: 7, month: 30 }[this.period];
    const out = { input: 0, cached: 0, output: 0, cost: 0, messages: 0, models: {}, projects: {}, series: [] };
    for (let i = n - 1; i >= 0; i--) {
      const key = new Date(Date.now() - i * 864e5).toLocaleDateString('sv-SE'), d = days[key];
      out.series.push({ key, cost: d?.cost || 0, tokens: d ? d.input + d.output + d.cached : 0 });
      if (!d) continue;
      for (const k of ['input', 'cached', 'output', 'cost', 'messages']) out[k] += d[k];
      for (const g of ['models', 'projects']) for (const [name, v] of Object.entries(d[g])) {
        const o = (out[g][name] ||= { tokens: 0, cost: 0 }); o.tokens += v.tokens; o.cost += v.cost;
      }
    }
    out.tokens = out.input + out.output + out.cached;
    return out;
  },

  card(title, ico, body, accessory = '') {
    return `<div class="card acard"><div class="ahead">${ico}<span>${title}</span><span style="flex:1"></span>${accessory}</div>${body}</div>`;
  },
  meter(frac, tint, pace) {
    return `<div class="ameter"><i style="width:${Math.max(frac > 0 ? 2 : 0, Math.min(100, frac * 100))}%;background:${tint}"></i>${pace > 0.02 && pace < 0.98 ? `<b style="left:${pace * 100}%" title="Ritmo: até aqui seria o uso distribuído igual pela janela"></b>` : ''}</div>`;
  },

  limitsCard() {
    const q = this.quota, L = q?.live, now = Date.now();
    const row = (label, w, hours) => {
      if (!w) return `<div class="arow"><div class="row"><span class="alabel">${label}</span><span style="flex:1"></span><span class="faint">sem dado</span></div>${this.meter(0, CLAUDE)}</div>`;
      const used = Math.min(100, w.used_pct || 0) / 100, reset = ts(w.resets_at);
      const tint = used >= 0.95 ? 'var(--bad)' : used >= 0.8 ? '#ff9f43' : CLAUDE;
      const pace = reset ? 1 - (reset - now) / (hours * 36e5) : null;
      return `<div class="arow" title="${reset ? 'Renova ' + new Date(reset).toLocaleString('pt-BR', { weekday: 'long', hour: '2-digit', minute: '2-digit' }) : 'Janela parada: começa no próximo uso'}">
        <div class="row" style="gap:6px"><span class="alabel">${label}</span>
          <span class="faint" style="font-size:11.5px">${reset ? '↻ ' + countdown(reset - now) : 'parada'}</span><span style="flex:1"></span>
          <span class="apct" style="${used >= 0.8 ? 'color:' + tint : ''}">${Math.round(used * 100)}%</span></div>
        ${this.meter(used, tint, pace)}</div>`;
    };
    const upd = ts(L?.updated);
    const age = upd ? Math.round((now - upd) / 6e4) : null;
    return this.card('Limites', `<span class="amark">${SPARK.replace(/30/g, '15')}</span>`,
      row('Sessão (5 h)', L?.five_hour, 5) + row('Semana', L?.seven_day, 168) +
      (q?.limited ? `<div class="faint" style="color:var(--bad);margin-top:2px">Esgotada · volta às ${hhmm(q.reset)}</div>` : ''),
      age != null ? `<span class="faint" style="font-size:11px">${age < 2 ? 'agora' : 'há ' + age + ' min'}</span>` : '');
  },

  spendCard(u) {
    const models = Object.entries(u.models).filter(([, v]) => v.cost > 0).sort((a, b) => b[1].cost - a[1].cost);
    const tot = models.reduce((n, [, v]) => n + v.cost, 0);
    const split = tot ? models.map(([m, v]) => `<i style="flex:${v.cost / tot};background:${modelTint(m)}" title="${esc(modelName(m))} ${usd(v.cost)}"></i>`).join('') : '<i style="flex:1;background:#ffffff22"></i>';
    const cacheRate = u.input + u.cached ? u.cached / (u.input + u.cached) : 0;
    return this.card('Gasto', `<span style="color:${CLAUDE}">${icon('gauge', 14)}</span>`, `
      <div class="row" style="align-items:baseline;gap:6px;margin-top:2px"><span class="abig">${usd(u.cost)}</span><span class="faint">valor em API</span></div>
      <div class="asplit">${split}</div>
      <div class="faint" style="font-size:12px;margin-top:6px">${compact(u.tokens)} tokens${cacheRate ? ` · ${Math.round(cacheRate * 100)}% do cache` : ''} · ${u.messages} respostas</div>`,
      '<span class="faint" style="font-size:11px" title="Quanto custaria pagando a API; o plano não cobra isso">estimado</span>');
  },

  liveCard() {
    const ol = this.usage?.ollama;
    const tasks = this.tasks.length ? this.tasks.map((t) => `<div class="row" style="gap:8px;margin-top:6px">
        <span class="apulse"></span><span class="ellipsis" style="flex:1"><b>${esc(t.project)}</b></span><span class="faint">${mmss(Date.now() / 1000 - t.start)}</span></div>`).join('')
      : '<div class="faint" style="margin-top:6px">Nenhuma tarefa rodando.</div>';
    const models = (ol || []).map((m) => `<div class="row" style="margin-top:4px;font-size:12px"><span class="ellipsis" style="flex:1">${esc(m.name)}</span><span class="faint">${bytes(m.size_vram || 0)}</span></div>`).join('');
    return this.card('Agora', `<span style="color:${CLAUDE}">${icon('spark', 14)}</span>`, tasks +
      `<div class="row" style="margin-top:10px"><span class="faint" style="flex:1">Ollama (%nome%)</span><span class="chip" style="color:${ol ? 'var(--ok)' : 'var(--bad)'}">${ol ? 'ligado' : 'desligado'}</span></div>${models}`,
      this.tasks.length ? '<span class="faint" style="font-size:11px">aviso ao terminar</span>' : '');
  },

  trendCard(u) {
    const s = u.series, max = Math.max(0.01, ...s.map((d) => d.cost));
    const many = s.length > 7;
    const bars = s.map((d, i) => {
      const lbl = s.length === 1 ? 'hoje' : many ? (i === 0 || i === s.length - 1 || i === Math.floor(s.length / 2) ? d.key.slice(8) + '/' + d.key.slice(5, 7) : '')
        : new Date(d.key + 'T12:00').toLocaleDateString('pt-BR', { weekday: 'narrow' });
      return `<div class="abar" title="${new Date(d.key + 'T12:00').toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' })}: ${usd(d.cost)} · ${compact(d.tokens)} tokens">
        <i style="height:${Math.max(3, 52 * d.cost / max)}px;background:${i === s.length - 1 ? CLAUDE : '#3a3a42'}"></i><span>${lbl}</span></div>`;
    }).join('');
    return this.card('Tendência', `<span style="color:${CLAUDE}">${icon('up', 14)}</span>`, `<div class="atrend">${bars}</div>`,
      `<span class="faint" style="font-size:11px">pico ${usd(max)}/dia</span>`);
  },

  shareCard(title, ico, entries, name, tint) {
    const list = Object.entries(entries).sort((a, b) => b[1].cost - a[1].cost || b[1].tokens - a[1].tokens).slice(0, 4);
    const top = Math.max(0.0001, ...list.map(([, v]) => v.cost || v.tokens / 1e6));
    const rows = list.map(([k, v]) => `<div class="arow" style="margin-top:6px">
      <div class="row" style="gap:6px"><span class="ellipsis" style="flex:1;font-size:12.5px">${esc(name(k))}</span><span class="faint" style="font-size:11.5px">${compact(v.tokens)}</span><b style="font-size:12.5px;min-width:54px;text-align:right">${usd(v.cost)}</b></div>
      ${this.meter((v.cost || v.tokens / 1e6) / top, tint(k))}</div>`).join('') || '<div class="faint" style="margin-top:6px">Nada no período.</div>';
    return this.card(title, `<span style="color:${CLAUDE}">${icon(ico, 14)}</span>`, rows);
  },

  render() {
    if (!this.view || !this.visible) return;
    if (this.failed && !this.usage) { this.view.innerHTML = failNote('o uso de IA'); return; }
    if (!this.usage) return;
    const u = this.sum();
    const periods = [['today', 'Hoje'], ['week', '7 dias'], ['month', '30 dias']]
      .map(([k, l]) => `<button class="ptab${this.period === k ? ' on' : ''}" data-period="${k}">${l}</button>`).join('');
    const top = this.view.scrollTop;
    this.view.innerHTML = `
      <div class="row" style="gap:6px;margin-bottom:8px"><span class="amark" style="width:20px">${SPARK.replace(/30/g, '18')}</span><b style="font-size:14px">Claude</b>
        <span style="flex:1"></span>${periods}</div>
      <div class="agrid">
        ${this.limitsCard()}${this.spendCard(u)}
        ${this.liveCard()}${this.trendCard(u)}
        ${this.shareCard('Modelos', 'cpu', u.models, modelName, modelTint)}
        ${this.shareCard('Projetos', 'folder', u.projects, (p) => p, () => CLAUDE)}
      </div>`;
    this.view.scrollTop = top;
  },
});
