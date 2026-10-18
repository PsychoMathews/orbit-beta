// Clique registrado: só desabilita o botão até a resposta (sem animação; o Windows responde rápido).
function busy(btn) { btn.disabled = true; }
const atLeast = (p) => p;
// Windows: energia (manter acordado, quando dormir, plano, desligar depois do render), faxina de espaço e alertas.
// Tudo roda no bot (winsys.py), então a assistente faz o mesmo por voz/Telegram.
Orbit.register({
  id: 'windows',
  st: null,
  scanData: null,
  picked: new Set(['temp', 'browsers']),
  async refresh() {
    const [r, g] = await Promise.all([api.get('/orbit/windows'), api.get('/orbit/gamemode')]);
    if (g) Orbit.game = g;
    this.failed = !r;
    if (r) this.st = r;
    this.render(); renderCompact();
  },
  start() { this.refresh(); setInterval(() => this.refresh(), 60000); },
  onEvent(ev) {
    if (ev.type === 'windows' && this.st) { Object.assign(this.st, ev); this.render(); renderCompact(); }
    if (ev.type === 'gamemode') this.render();
    if (ev.type === 'hello' || ev.type === 'online') this.refresh();
  },
  live() {
    const s = this.st;
    if (!s) return null;
    const sd = s.shutdown;
    if (sd.action) {
      const verb = sd.action === 'shutdown' ? 'Desliga' : 'Reinicia';
      return { priority: 3, width: 320, left: `<span style="color:var(--bad)">${icon('bolt', 16)}</span>`,
        mid: `<span class="t">${verb} ${sd.after_render ? 'quando o render acabar' : 'às ' + hhmm(sd.at * 1000)}</span>`, right: '' };
    }
    if (s.awake.mode !== 'off') {
      const until = s.awake.mode === 'minutes' ? 'até ' + hhmm(s.awake.until * 1000) : s.awake.mode === 'until_render' ? 'até o render' : '';
      return { priority: 0.3, width: 280, left: '<span>☕</span>', mid: `<span class="t">Acordado ${until}</span>`, right: '' };
    }
    return null;
  },
  async act(action, body) {
    const r = await atLeast(api.post('/orbit/windows/' + action, body || {}));
    if (!r) { Orbit.banner('Windows', '%A% está fora do ar.', 'bad', 3000); return; }
    this.st = r; this.render(); renderCompact();
    if (r.msg) Orbit.banner('Windows', r.msg, '', 3500);
    return r;
  },
  // Botões perigosos pedem um segundo clique.
  confirmClick(btn, label, fn) {
    if (btn.dataset.armed) { delete btn.dataset.armed; fn(); return; }
    btn.dataset.armed = '1';
    const old = btn.innerHTML;
    btn.innerHTML = label; btn.classList.add('on');
    setTimeout(() => { if (btn.dataset.armed) { delete btn.dataset.armed; btn.innerHTML = old; btn.classList.remove('on'); } }, 4000);
  },
  mount(view) {
    this.view = view;
    view.addEventListener('click', (e) => {
      const b = e.target.closest('[data-do]');
      if (!b) return;
      const d = b.dataset, num = (v) => (v === undefined ? undefined : +v);
      // Ações que esperam o Windows: o botão mostra que está trabalhando até a resposta chegar.
      if (['game', 'gallow', 'gspeak', 'wtheme', 'cancel', 'alert'].includes(d.do)) busy(b);
      switch (d.do) {
        case 'game': api.post('/orbit/gamemode', { on: !Orbit.game.on }); break;
        case 'gallow': {
          const allow = new Set(Orbit.game.allow || []);
          allow.has(d.k) ? allow.delete(d.k) : allow.add(d.k);
          atLeast(api.post('/orbit/gamemode', { allow: [...allow] })).then((g) => { if (g) { Orbit.game = g; this.render(); } });
          break;
        }
        case 'gspeak': atLeast(api.post('/orbit/gamemode', { speak: !Orbit.game.speak })).then((g) => { if (g) { Orbit.game = g; this.render(); } }); break;
        case 'wtheme': atLeast(api.post('/orbit/theme', { mode: d.mode, target: 'windows' })).then((r) => { if (r) { this.winTheme = r.windows; this.render(); Orbit.banner('Tema', r.msg, '', 2500); } }); break;
        case 'awake': this.draft.awake = { mode: d.mode, minutes: num(d.min) || 0 }; this.render(); break;
        case 'screen': this.draft.keepScreen = !this.val('keepScreen'); this.render(); break;
        case 'sleep': this.draft.sleep = +d.v; this.render(); break;
        case 'screenoff': this.draft.screen = +d.v; this.render(); break;
        case 'plan': this.draft.plan = d.name; this.render(); break;
        case 'apply': this.apply(b); break;
        case 'discard': this.draft = {}; this.render(); break;
        case 'shutdown': this.confirmClick(b, 'Confirmar?', () => { busy(b); this.act('shutdown', { action: d.act, minutes: num(d.min), after_render: d.render === '1' }); }); break;
        case 'cancel': this.act('cancel'); break;
        case 'server': busy(b); this.act('server', { on: !this.st.server?.on }); break;
        case 'alert': this.act('alerts', { [d.k]: !this.st.alerts[d.k] }); break;
        case 'scan': this.scan(); break;
        case 'files': this.toggleFiles(d.k); break;
        case 'fkeep': { const set = this.unchecked[d.k] ||= new Set(); set.has(d.p) ? set.delete(d.p) : set.add(d.p); this.renderClean(); break; }
        case 'fshow': api.fileShow(d.p); break;
        case 'fdir': api.fileShow(''); break;
        case 'pick': this.picked.has(d.k) ? this.picked.delete(d.k) : this.picked.add(d.k); this.renderClean(); break;
        case 'clean': this.confirmClick(b, 'Apagar de vez? Clique de novo', async () => { busy(b); await this.act('clean', { targets: [...this.picked], only: this.only() }); this.scan(); }); break;
        case 'acevery': this.act('autoclean', { every: d.v }); break;
        case 'acpick': { const t = new Set(this.st.autoclean.targets); t.has(d.k) ? t.delete(d.k) : t.add(d.k); this.act('autoclean', { targets: [...t] }); break; }
        case 'acdays': this.act('autoclean', { downloads_days: +d.v }); break;
        case 'recycle': this.confirmClick(b, 'Esvaziar de vez?', async () => { busy(b); await this.act('recycle'); this.scan(); }); break;
      }
    });
    this.render();
  },
  show() { this.refresh(); api.get('/orbit/theme').then((r) => { if (r) { this.winTheme = r.windows; this.render(); } }); if (!this.scanData) this.scan(); },
  // Itens que vão para a Lixeira (instaladores, downloads antigos): dá para ver um por um e desmarcar.
  files: {}, unchecked: {}, open: null,
  async toggleFiles(k) {
    this.open = this.open === k ? null : k;
    if (this.open && !this.files[k]) { this.files[k] = 'loading'; this.renderClean(); const r = await api.get('/orbit/cleanup?files=' + k); this.files[k] = r ? r.files : []; }
    this.renderClean();
  },
  only() {
    const out = {};
    for (const k of ['installers', 'old_downloads']) {
      if (!this.picked.has(k) || !Array.isArray(this.files[k])) continue;
      out[k] = this.files[k].filter((f) => !(this.unchecked[k] || new Set()).has(f.path)).map((f) => f.path);
    }
    return out;
  },
  fileList(k) {
    const f = this.files[k];
    if (f === 'loading') return '<div class="faint" style="padding:6px 12px"><span class="spin"></span> Listando…</div>';
    if (!f.length) return '<div class="faint" style="padding:6px 12px">Nada aqui.</div>';
    const un = this.unchecked[k] || new Set();
    return `<div class="flist">${f.slice(0, 150).map((x) => `<div class="row fl">
        <button class="fchk${un.has(x.path) ? '' : ' on'}" data-do="fkeep" data-k="${k}" data-p="${esc(x.path)}" title="${un.has(x.path) ? 'Fica (não vai para a Lixeira)' : 'Vai para a Lixeira'}"></button>
        <span class="ellipsis" style="flex:1">${x.dir ? '📁 ' : ''}${esc(x.name)}</span>
        <span class="faint">${new Date(x.mtime * 1000).toLocaleDateString('pt-BR')}</span><b style="width:70px;text-align:right">${bytes(x.size)}</b>
        <button class="btn round" style="width:24px;height:24px" data-do="fshow" data-p="${esc(x.path)}" title="Mostrar no Explorer">${icon('folder', 12)}</button></div>`).join('')}</div>
      <div class="row" style="gap:8px;margin:4px 0 2px"><span class="faint" style="flex:1">Desmarque o que você quer manter. Tudo vai para a Lixeira (dá para recuperar).</span>
        <button class="btn" style="height:26px" data-do="fdir">Abrir Downloads no Explorer</button></div>`;
  },
  async scan() {
    this.scanning = true; this.renderClean();
    const r = await api.get('/orbit/cleanup');
    this.scanning = false;
    if (r) this.scanData = r;
    else Orbit.banner('Faxina', 'A varredura não respondeu. Tente de novo.', 'bad', 3500);
    this.renderClean();
  },
  // on: true = ativo no Windows; 'pending' = escolhido, esperando "Aplicar".
  chip(label, attrs, on) {
    const style = on === 'pending' ? 'box-shadow:inset 0 0 0 1.5px var(--tint);color:var(--tint)' : on ? 'background:var(--fg);color:#000' : '';
    return `<button class="btn" style="height:28px;padding:0 11px;font-size:12px;${style}" ${attrs}>${label}</button>`;
  },
  draft: {},
  // Valor atual de uma opção de energia: o rascunho, se houver; senão o que está no Windows.
  val(k) {
    const s = this.st, a = s.awake;
    const cur = { awake: { mode: a.mode, minutes: 0 }, keepScreen: a.screen, sleep: s.sleep, screen: s.screen,
      plan: (s.plans || []).find((p) => p.active)?.name };
    return k in this.draft ? this.draft[k] : cur[k];
  },
  // Estado do chip: escolhido no rascunho = 'pending'; ativo no Windows sem rascunho = true.
  sel(k, match) {
    if (k in this.draft) return match(this.draft[k]) ? 'pending' : false;
    return match(this.val(k));
  },
  async apply(btn) {
    const d = this.draft, body = {};
    if ('awake' in d || 'keepScreen' in d) {
      const aw = this.val('awake');
      body.awake = { mode: aw.mode, minutes: aw.minutes, screen: this.val('keepScreen') };
      if (aw.mode === 'minutes' && !aw.minutes && this.st.awake.until) body.awake.minutes = (this.st.awake.until * 1000 - Date.now()) / 60000;
      if (aw.mode === 'off' && 'keepScreen' in d && !('awake' in d)) body.awake.mode = 'forever'; // "tela também" liga o modo acordado
    }
    if ('sleep' in d) body.sleep = d.sleep;
    if ('screen' in d) body.screen = d.screen;
    if ('plan' in d) body.plan = d.plan;
    busy(btn);
    const r = await this.act('apply', body);
    if (r) this.draft = {};
    this.render();
  },
  render() {
    if (!this.view) return;
    const s = this.st;
    if (!s) { this.view.innerHTML = this.failed ? failNote('os ajustes do Windows') : '<div class="empty">Carregando…</div>'; return; }
    const a = s.awake, sd = s.shutdown, c = this.chip.bind(this);
    const awakeTxt = a.mode === 'off' ? 'Desligado: o PC dorme normalmente'
      : a.mode === 'minutes' ? `Ligado até ${hhmm(a.until * 1000)}` : a.mode === 'until_render' ? 'Ligado até o render do DaVinci acabar' : 'Ligado até você desligar';
    const opts = (vals, key, kind) => vals.map(([v, l]) => c(l, `data-do="${kind}" data-v="${v}"`, this.sel(key, (x) => x === v))).join('');
    const sdTxt = sd.action ? `${sd.action === 'shutdown' ? 'Desligar' : 'Reiniciar'} ${sd.after_render ? 'quando o render acabar' : 'às ' + hhmm(sd.at * 1000)}` : '';
    const energy = `
      <div class="card hero col" style="gap:10px">
        <div class="row"><span class="mark">${icon('bolt', 17)}</span><b style="flex:1">Energia</b><span class="faint">na tomada</span></div>
        <div><div class="row"><span class="muted-text" style="flex:1">☕ Manter acordado</span><span class="faint">${awakeTxt}</span></div>
          <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">
            ${c('Desligado', 'data-do="awake" data-mode="off"', this.sel('awake', (v) => v.mode === 'off'))}
            ${c('1 h', 'data-do="awake" data-mode="minutes" data-min="60"', this.sel('awake', (v) => v.mode === 'minutes' && v.minutes === 60))}
            ${c('2 h', 'data-do="awake" data-mode="minutes" data-min="120"', this.sel('awake', (v) => v.mode === 'minutes' && v.minutes === 120))}
            ${c('Até o render acabar', 'data-do="awake" data-mode="until_render"', this.sel('awake', (v) => v.mode === 'until_render'))}
            ${c('Sempre', 'data-do="awake" data-mode="forever"', this.sel('awake', (v) => v.mode === 'forever'))}
            ${c((this.val('keepScreen') ? '✓ ' : '') + 'Tela também', 'data-do="screen"', this.sel('keepScreen', (v) => !!v))}
          </div></div>
        <div class="grid2">
          <div><div class="muted-text">PC dorme após</div><div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">${opts([[0, 'Nunca'], [10, '10 min'], [30, '30 min'], [60, '1 h']], 'sleep', 'sleep')}</div></div>
          <div><div class="muted-text">Tela apaga após</div><div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">${opts([[0, 'Nunca'], [5, '5 min'], [10, '10 min'], [30, '30 min']], 'screen', 'screenoff')}</div></div>
        </div>
        <div><div class="muted-text">Plano de energia</div><div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">
          ${(s.plans || []).map((p) => c(esc(p.name), `data-do="plan" data-name="${esc(p.name)}"`, this.sel('plan', (v) => v === p.name))).join('')}</div></div>
        ${Object.keys(this.draft).length ? `<div class="row" style="justify-content:flex-end;gap:8px">
          <span class="faint" style="flex:1">Escolhas em azul ainda não foram aplicadas.</span>
          <button class="btn" data-do="discard" style="height:30px">Descartar</button>
          <button class="btn primary tint" data-do="apply" style="height:30px">Aplicar</button></div>` : ''}
        <div><div class="row"><span class="muted-text" style="flex:1">⏻ Desligar o PC</span>${sd.action ? `<b style="color:var(--bad)">${sdTxt}</b>` : ''}</div>
          <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">
            ${sd.action ? `<button class="btn danger" data-do="cancel" style="height:28px">Cancelar desligamento</button>` : `
              ${c('Em 30 min', 'data-do="shutdown" data-act="shutdown" data-min="30"', false)}${c('Em 1 h', 'data-do="shutdown" data-act="shutdown" data-min="60"', false)}
              ${c('Quando o render acabar', 'data-do="shutdown" data-act="shutdown" data-render="1"', false)}
              ${c('Reiniciar em 5 min', 'data-do="shutdown" data-act="restart" data-min="5"', false)}`}
          </div></div>
      </div>`;
    const names = { cpu: 'CPU no máximo (5 min)', ram: 'Memória acima de 92%', disk: 'Disco com menos de 20 GB', gpu: 'GPU acima de 85 °C' };
    const alerts = `
      <div class="card" style="margin-top:8px">
        <div class="row"><span style="color:var(--bad)">${icon('bell', 17)}</span><b style="flex:1">Alertas</b><span class="faint">na ilha e no Telegram</span></div>
        <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:8px">${Object.entries(names).map(([k, l]) => c((s.alerts[k] ? '✓ ' : '') + l, `data-do="alert" data-k="${k}"`, s.alerts[k])).join('')}</div>
      </div>`;
    const g = Orbit.game, kinds = g.kinds || {};
    const game = `
      <div class="card" style="margin-bottom:8px">
        <div class="row"><span>🎮</span><b style="flex:1">Modo jogo</b>
          <button class="btn ${g.on ? 'on' : 'primary tint'}" data-do="game" style="height:30px">${g.on ? 'Desligar' : 'Ligar'}</button></div>
        <div class="faint" style="margin-top:6px">Não escuta nem fala pelo PC, silencia as notificações do Windows e esconde a ilha. O resto fica guardado num resumo para depois. Passam só:</div>
        <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:8px">
          ${Object.entries(kinds).map(([k, l]) => c(((g.allow || []).includes(k) ? '✓ ' : '') + esc(l), `data-do="gallow" data-k="${k}"`, (g.allow || []).includes(k))).join('')}
          ${c((g.speak ? '✓ ' : '') + 'Falar esses avisos', 'data-do="gspeak"', g.speak)}
        </div>
      </div>`;
    const wt = this.winTheme;
    const theme = `
      <div class="card" style="margin-top:8px">
        <div class="row"><span>🌗</span><b style="flex:1">Tema do Windows</b>
          ${c('Escuro', 'data-do="wtheme" data-mode="escuro"', wt === 'escuro')}${c('Claro', 'data-do="wtheme" data-mode="claro"', wt === 'claro')}</div>
        <div class="faint" style="margin-top:6px">O tema da ilha fica em Configurações → Ilha.</div>
      </div>`;
    const sv = s.server || {};
    const server = `
      <div class="card ${sv.on ? 'hero' : ''}" style="margin-bottom:8px">
        <div class="row"><span>🖥️</span><b style="flex:1">Modo servidor</b>
          ${sv.on && sv.since ? `<span class="faint" style="margin-right:8px">desde ${new Date(sv.since * 1000).toLocaleString('pt-BR', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}</span>` : ''}
          <button class="btn ${sv.on ? 'on' : 'primary tint'}" data-do="server" style="height:30px">${sv.on ? 'Desligar' : 'Ligar'}</button></div>
        <div class="faint" style="margin-top:6px">${sv.on
          ? 'Ligado: o PC não dorme, a tela apaga em 1 min, plano Economia de energia, IA local fora da placa de vídeo e ilha no modo leve. Desligar volta tudo como estava.'
          : 'Para deixar o PC ligado dias seguidos gastando o mínimo e falar com a assistente de longe (Telegram, iPhone, Alexa). Deixe o Tailscale ligado.'}</div>
      </div>`;
    this.view.innerHTML = server + game + energy + '<div id="wn-clean"></div>' + theme + alerts;
    this.renderClean();
  },
  renderClean() {
    const box = this.view && this.view.querySelector('#wn-clean');
    if (!box) return;
    const d = this.scanData;
    let body;
    if (this.scanning && !d) body = '<div class="faint row" style="padding:8px 0;gap:8px">Varrendo o PC… isso leva alguns segundos</div>';
    else if (!d) body = '';
    else {
      const t = d.targets;
      const rows = ['temp', 'davinci', 'browsers', 'installers', 'old_downloads', 'wintemp'].filter((k) => t[k]).map((k) => `
        <div class="item click" data-do="pick" data-k="${k}" style="padding:7px 10px">
          <span style="width:16px;height:16px;border-radius:5px;flex:none;${this.picked.has(k) ? 'background:var(--tint)' : 'box-shadow:inset 0 0 0 1.5px var(--faint)'}"></span>
          <div style="flex:1;min-width:0"><div class="ellipsis">${esc(t[k].name)}</div><div class="faint ellipsis">${esc(t[k].desc)}</div></div>
          ${['installers', 'old_downloads'].includes(k) && t[k].size ? `<button class="btn" style="height:26px" data-do="files" data-k="${k}">${this.open === k ? 'Esconder' : 'Ver'}</button>` : ''}
          <b>${bytes(t[k].size)}</b></div>${this.open === k ? this.fileList(k) : ''}`).join('');
      const total = [...this.picked].reduce((n, k) => {
        const f = this.files[k];
        if (Array.isArray(f) && this.unchecked[k]?.size) return n + f.filter((x) => !this.unchecked[k].has(x.path)).reduce((a, x) => a + x.size, 0);
        return n + (t[k] ? t[k].size : 0);
      }, 0);
      const disks = d.disks.map((x) => {
        const used = 1 - x.free / x.total;
        return `<div style="flex:1"><div class="row"><span class="faint" style="flex:1">Disco ${esc(x.drive)}</span><span class="faint">${bytes(x.free)} livres</span></div>
          <div class="bar" style="margin-top:4px"><i style="width:${(used * 100).toFixed(1)}%;${used > 0.9 ? 'background:var(--bad)' : ''}"></i></div></div>`;
      }).join('');
      body = `<div class="row" style="gap:12px;margin:8px 0">${disks}</div><div class="list">${rows}</div>
        <div class="row" style="margin-top:8px;gap:8px">
          <button class="btn primary tint" data-do="clean" ${total ? '' : 'disabled'}>${icon('broom', 15)} Limpar ${bytes(total)}</button>
          <span style="flex:1"></span>
          <span class="faint">Lixeira: ${bytes(t.recycle.size)}</span>
          <button class="btn danger" data-do="recycle" style="height:30px" ${t.recycle.size ? '' : 'disabled'}>Esvaziar</button>
        </div>`;
    }
    const ac = this.st?.autoclean, c = this.chip.bind(this);
    const tn = { temp: 'Temporários', browsers: 'Cache dos navegadores', installers: 'Instaladores velhos', davinci: 'Cache do DaVinci', wintemp: 'Temp do Windows' };
    const auto = ac ? `<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--line)">
      <div class="row"><span class="muted-text" style="flex:1">Faxina automática</span>
        <span class="faint">${ac.every !== 'off' && ac.last ? 'última ' + new Date(ac.last * 1000).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) : ''}</span></div>
      <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">
        ${[['off', 'Desligada'], ['daily', 'Todo dia'], ['weekly', 'Toda semana']].map(([v, l]) => c(l, `data-do="acevery" data-v="${v}"`, ac.every === v)).join('')}</div>
      ${ac.every !== 'off' ? `<div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">
        ${Object.entries(tn).map(([k, l]) => c((ac.targets.includes(k) ? '✓ ' : '') + l, `data-do="acpick" data-k="${k}"`, ac.targets.includes(k))).join('')}</div>` : ''}
      <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:8px"><span class="faint" style="margin-right:4px">Downloads antigos para a Lixeira</span>
        ${[[0, 'Nunca'], [30, '30 dias'], [60, '60 dias'], [90, '90 dias']].map(([v, l]) => c(l, `data-do="acdays" data-v="${v}"`, (ac.downloads_days || 0) === v)).join('')}</div>
    </div>` : '';
    body += auto;
    box.innerHTML = `
      <div class="card" style="margin-top:8px">
        <div class="row"><span style="color:var(--tint)">${icon('broom', 17)}</span><b style="flex:1">Faxina</b>
          <button class="btn" data-do="scan" style="height:28px;font-size:12px">${this.scanning ? 'Varrendo…' : d ? 'Varrer de novo' : 'Varrer o PC'}</button></div>
        ${body}
      </div>`;
  },
});
