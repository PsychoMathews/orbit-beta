// Configurações do Orbit: recursos (liga/desliga e ordem), comportamento da ilha e da assistente.
const icon = window.ORBIT_ICON;
const { MODULES } = window.ORBIT_CATALOG;
let cfg;

const PRESETS = {
  tudo: MODULES.map((m) => m.id),
  edicao: ['sexta', 'midia', 'som', 'davinci', 'windows', 'sistema', 'timer', 'agenda', 'ia', 'arquivos'],
  minimo: ['sexta', 'midia', 'som', 'timer'],
};

document.querySelectorAll('[data-ico]').forEach((s) => { s.outerHTML = icon(s.dataset.ico, 18); });

function go(page) {
  if (!document.getElementById(page)) return;
  document.querySelectorAll('nav button').forEach((b) => b.classList.toggle('on', b.dataset.page === page));
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('on', p.id === page));
}
document.querySelectorAll('nav button').forEach((b) => { b.onclick = () => go(b.dataset.page); });
window.orbit.onGoto(go);
window.orbit.onTheme((t) => { document.documentElement.dataset.theme = t; });
if (location.hash) go(location.hash.slice(1));

function save(next) { window.orbit.configSet(next); }

function renderFeatures() {
  const box = document.getElementById('features');
  box.innerHTML = '';
  cfg.modules.order.forEach((id, i) => {
    const m = MODULES.find((x) => x.id === id);
    const on = !!cfg.modules.enabled[id];
    const row = document.createElement('div');
    row.className = 'feature' + (on ? '' : ' off');
    row.innerHTML = `
      <div class="move"><button data-d="-1" title="Subir">${icon('up', 16)}</button><button data-d="1" title="Descer">${icon('down', 16)}</button></div>
      <div class="fi">${icon(m.icon, 20)}</div>
      <div class="txt"><b>${m.name}</b><span>${m.desc}</span></div>
      <label class="switch"><input type="checkbox" ${on ? 'checked' : ''}><i></i></label>`;
    row.dataset.id = id;
    row.querySelector('input').onchange = (e) => save({ modules: { enabled: { [id]: e.target.checked } } });
    row.querySelectorAll('[data-d]').forEach((b) => {
      b.onclick = () => {
        const order = [...cfg.modules.order], j = i + +b.dataset.d;
        if (j < 0 || j >= order.length) return;
        [order[i], order[j]] = [order[j], order[i]];
        save({ modules: { order } });
      };
    });
    row.addEventListener('pointerdown', (e) => startDrag(e, row, box));
    box.appendChild(row);
  });
}

// Clicar, segurar e arrastar um recurso para cima ou para baixo (as setas continuam valendo).
function startDrag(e, row, box) {
  if (e.button !== 0 || e.target.closest('button, label, input')) return;
  const startY = e.clientY;
  let dragging = false;
  const move = (ev) => {
    if (!dragging) {
      if (Math.abs(ev.clientY - startY) < 6) return; // só um clique, não arraste
      dragging = true;
      row.classList.add('dragging');
      row.setPointerCapture(ev.pointerId);
    }
    // Troca de lugar com o vizinho cujo meio o ponteiro passou.
    const others = [...box.children].filter((r) => r !== row);
    const after = others.find((r) => ev.clientY < r.getBoundingClientRect().top + r.offsetHeight / 2);
    if (after) { if (row.nextSibling !== after) box.insertBefore(row, after); }
    else if (box.lastChild !== row) box.appendChild(row);
  };
  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    if (!dragging) return;
    row.classList.remove('dragging');
    const order = [...box.children].map((r) => r.dataset.id);
    if (order.join() !== cfg.modules.order.join()) save({ modules: { order } });
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

document.querySelectorAll('[data-preset]').forEach((b) => {
  b.onclick = () => {
    const on = PRESETS[b.dataset.preset];
    save({ modules: { enabled: Object.fromEntries(MODULES.map((m) => [m.id, on.includes(m.id)])) } });
  };
});

function toggle(section, key, title, desc) {
  return { section, key, title, desc, kind: 'toggle' };
}
function range(section, key, title, desc, min, max, step, fmt) {
  return { section, key, title, desc, kind: 'range', min, max, step, fmt };
}

function choice(section, key, title, desc, options) {
  return { section, key, title, desc, kind: 'choice', options };
}

const ISLAND = [
  { section: 'island', kind: 'colors', title: 'Cores %da%', desc: 'Anel e ondas da pílula. Gradiente usa as 3 cores; sólida, só a primeira.' },
  choice('island', 'theme', 'Tema do Orbit', 'Ilha e Configurações.', [['escuro', 'Escuro'], ['claro', 'Claro'], ['sistema', 'Igual ao Windows']]),
  toggle('island', 'expandOnHover', 'Abrir ao passar o mouse', 'Desligado: abre só com clique.'),
  range('island', 'hoverDelay', 'Atraso para abrir', 'Quanto tempo o mouse fica em cima antes de abrir.', 0, 800, 20, (v) => v + ' ms'),
  range('island', 'collapseDelay', 'Atraso para fechar', 'Depois que o mouse sai.', 100, 2000, 50, (v) => v + ' ms'),
  range('island', 'idleOpacity', 'Opacidade parada', 'Quão visível a pílula fica quando nada está acontecendo.', 0.15, 1, 0.05, (v) => Math.round(v * 100) + '%'),
  range('island', 'panelWidth', 'Largura do painel', 'Tamanho da ilha aberta.', 520, 860, 10, (v) => v + ' px'),
  range('island', 'offsetY', 'Distância do topo', '', 0, 40, 1, (v) => v + ' px'),
  toggle('island', 'liveMusic', 'Música na pílula', 'Mostra a música tocando com a capa.'),
  toggle('island', 'liveTimer', 'Timer na pílula', 'Mostra a contagem do timer mais próximo.'),
  toggle('island', 'sounds', 'Sons', 'Toque curto em avisos e alarme no fim do timer.'),
  toggle('island', 'lite', 'Modo leve', 'Para PCs mais fracos: sem animações, sem batida da música e atualizações mais espaçadas. Tudo continua funcionando.'),
  toggle('island', 'compactPanel', 'Painel compacto', 'Ilha aberta mais baixa e abas só com ícone.'),
];
const ASSIST_OPTS = [
  toggle('friday', 'speakTyped', 'Responder em voz o que eu digitar', 'Perguntas digitadas na ilha também são respondidas pelas caixas de som.'),
];

function renderOpts(boxId, opts) {
  const box = document.getElementById(boxId);
  box.innerHTML = '';
  for (const o of opts) {
    const v = cfg[o.section][o.key];
    const row = document.createElement('div');
    row.className = 'opt';
    if (o.kind === 'colors') {
      const c = cfg.island, presets = { 'Padrão': ['#2f7bff', '#9b5cff', '#ff6fb5'], Ciano: ['#00e5ff', '#2f7bff', '#7cf7ff'], Brasa: ['#ff6a00', '#ff2d55', '#ff9a3c'], Verde: ['#2bff9a', '#00b3ff', '#c6ff6b'] };
      const on = (m) => (c.orbMode === m ? 'background:var(--accent);color:#000' : '');
      row.innerHTML = `<div><b>${o.title}</b><span>${o.desc}</span></div><div style="display:flex;flex-direction:column;gap:8px;align-items:flex-end">
        <div class="presets" style="margin:0"><button data-m="grad" style="${on('grad')}">Gradiente</button><button data-m="solid" style="${on('solid')}">Sólida</button></div>
        <div style="display:flex;gap:6px;align-items:center">${Object.entries(presets).map(([n, p]) => `<button data-p="${p}" title="${n}" style="width:22px;height:22px;border-radius:50%;border:2px solid #fff3;background:linear-gradient(135deg,${p})"></button>`).join('')}
        ${['orbC1', 'orbC2', 'orbC3'].map((k) => `<input type="color" data-k="${k}" value="${c[k]}" style="width:28px;height:24px;border:0;background:none;padding:0">`).join('')}</div></div>`;
      row.querySelectorAll('[data-m]').forEach((b) => { b.onclick = () => save({ island: { orbMode: b.dataset.m } }); });
      row.querySelectorAll('[data-p]').forEach((b) => { const [a, d, e] = b.dataset.p.split(','); b.onclick = () => save({ island: { orbC1: a, orbC2: d, orbC3: e } }); });
      row.querySelectorAll('[data-k]').forEach((i) => { let t = null; i.oninput = () => { clearTimeout(t); t = setTimeout(() => save({ island: { [i.dataset.k]: i.value } }), 80); }; });
    } else if (o.kind === 'choice') {
      row.innerHTML = `<div><b>${o.title}</b><span>${o.desc}</span></div><div class="presets" style="margin:0">${o.options.map(([v, l]) =>
        `<button data-v="${v}" style="${v === cfg[o.section][o.key] ? 'background:var(--accent);color:#000' : ''}">${l}</button>`).join('')}</div>`;
      row.querySelectorAll('[data-v]').forEach((b) => { b.onclick = () => save({ [o.section]: { [o.key]: b.dataset.v } }); });
    } else if (o.kind === 'toggle') {
      row.innerHTML = `<div><b>${o.title}</b><span>${o.desc}</span></div><label class="switch"><input type="checkbox" ${v ? 'checked' : ''}><i></i></label>`;
      row.querySelector('input').onchange = (e) => save({ [o.section]: { [o.key]: e.target.checked } });
    } else {
      row.innerHTML = `<div><b>${o.title}</b><span>${o.desc}</span></div><input type="range" min="${o.min}" max="${o.max}" step="${o.step}" value="${v}"><output>${o.fmt(v)}</output>`;
      const input = row.querySelector('input'), out = row.querySelector('output');
      // Aplica enquanto arrasta (com um pequeno intervalo), para ver a ilha mudando na hora.
      let t = null;
      input.oninput = () => {
        out.textContent = o.fmt(+input.value);
        clearTimeout(t);
        t = setTimeout(() => save({ [o.section]: { [o.key]: +input.value } }), 120);
      };
    }
    box.appendChild(row);
  }
}

function render() {
  const c = cfg.island, rs = document.documentElement.style;
  rs.setProperty('--orb1', c.orbC1);
  rs.setProperty('--accent', c.orbC1); // chaves, abas e destaques na cor da assistente
  rs.setProperty('--orb-ring', c.orbMode === 'solid' ? c.orbC1 : `conic-gradient(${c.orbC1}, ${c.orbC2}, ${c.orbC3}, ${c.orbC1})`);
  renderFeatures(); renderOpts('island-opts', ISLAND); renderOpts('friday-opts', ASSIST_OPTS); renderPerms(); }

document.getElementById('reset').onclick = () => window.orbit.configReset();
window.orbit.onConfig((c) => { cfg = c; if (!document.activeElement || !['range', 'color'].includes(document.activeElement.type)) render(); });
window.orbit.configGet().then(({ config }) => { cfg = config; render(); });
window.orbit.status().then((st) => { if (st && st.assistente) window.ORBIT_SET_ASSIST(st.assistente); });

// ---------- Permissões ----------
// Cada acesso: para que serve e quais recursos (abas) usam. "Sem uso" = todos os recursos dele estão desligados.
const PERMS = [
  { name: 'Microfone', icon: 'mic', what: 'Ouvir você quando aperta Ctrl+Alt+F ou o botão da ilha. Só grava depois do bipe; o áudio vira texto no seu PC (Whisper local).', uses: ['sexta'], always: true },
  { name: 'Caixas de som', icon: 'volUp', what: 'A voz %da%, os alarmes dos timers e os sons da ilha.', uses: ['sexta', 'timer'], always: true },
  { name: 'Mixer de som do Windows', icon: 'headset', what: 'Volume e saída de cada programa, nível da música para a batida da pílula e o mudo dos microfones.', uses: ['som', 'midia'] },
  { name: 'Mídia do Windows', icon: 'music', what: 'Saber o que toca (título, capa, tempo) e controlar o player.', uses: ['midia'] },
  { name: 'Google Agenda e Gmail', icon: 'calendar', what: 'Ler a agenda e os e-mails; criar evento ou responder e-mail só com a sua confirmação.', uses: ['agenda'], key: 'google', always: true },
  { name: 'Área de transferência', icon: 'clip', what: 'Guardar o histórico do que você copia (fica só neste PC).', uses: ['clipboard'] },
  { name: 'Pasta Downloads', icon: 'folder', what: 'Mostrar downloads em andamento e recentes; a faxina só manda para a Lixeira o que você escolher.', uses: ['arquivos', 'windows'] },
  { name: 'Registros do Claude Code', icon: 'gauge', what: 'Somar tokens, ver quando o Claude está trabalhando e ler a cota da sua conta (sem gastar cota).', uses: ['ia'], key: 'claude' },
  { name: 'DaVinci Resolve', icon: 'film', what: 'Ler projeto, timeline e fila de render pelo script oficial do Resolve.', uses: ['davinci'] },
  { name: 'Energia e sistema', icon: 'cpu', what: 'CPU, GPU, memória e disco; manter acordado, plano de energia e desligar agendado.', uses: ['sistema', 'windows'] },
  { name: 'Internet', icon: 'link', what: 'Letra da música (lrclib.net, só quando você abre), teste de velocidade (Cloudflare, só quando você clica), clima, pesquisa e notícias.', uses: ['midia', 'sistema', 'sexta'] },
  { name: 'Telegram e Alexa', icon: 'send', what: 'Falar com %a% fora do PC e receber avisos e botões de confirmação.', uses: ['sexta'], always: true },
];

async function renderAccounts() {
  const box = document.getElementById('accounts');
  const s = await window.orbit.get('/orbit/spotify').catch(() => null);
  if (!s) { box.innerHTML = '<div class="opt"><div><b>Spotify</b><span>%A% está fora do ar.</span></div></div>'; return; }
  const setup = !s.client_id ? `<div class="opt" style="flex-direction:column;align-items:stretch;gap:8px">
      <div><b>Primeira vez: criar o app do Spotify (2 min)</b><span>1. Entre em developer.spotify.com/dashboard e clique em “Create app”.<br>
      2. Em “Redirect URIs” coloque exatamente: <code style="user-select:all">${s.redirect}</code><br>
      3. Marque “Web API”, salve, e copie o <b>Client ID</b> aqui embaixo. Quem for usar a sua instalação precisa estar em “User Management” do app (até 25 pessoas).</span></div>
      <div style="display:flex;gap:8px"><input id="sp-cid" placeholder="Client ID" style="flex:1;height:34px;border-radius:10px;border:0;padding:0 12px;background:var(--card2);color:inherit;font:inherit">
      <button class="btn" id="sp-save">Salvar</button><button class="btn" id="sp-dash">Abrir o painel</button></div></div>` : '';
  box.innerHTML = setup + `<div class="opt"><div class="fi" style="margin-right:12px;color:#1ed760">${icon('music', 18)}</div>
    <div style="flex:1"><b>Spotify</b><span>${s.connected ? 'Conectado' + (s.user ? ' como ' + s.user : '') + '. A aba Música mostra a fila e %a% põe músicas na fila por voz.' : 'Conecte para ver a fila na aba Música e pedir “coloca tal música na fila”. O login é no site do Spotify; a senha nunca passa pelo Orbit.'}</span></div>
    ${s.connected ? '<span class="pill ok">Conectado</span><button class="btn" id="sp-off" style="margin-left:8px">Desconectar</button>' : `<button class="btn" id="sp-on" ${s.client_id ? '' : 'disabled'}>Conectar</button>`}</div>`;
  const $ = (id) => document.getElementById(id);
  if ($('sp-dash')) $('sp-dash').onclick = () => window.orbit.openUrl('https://developer.spotify.com/dashboard');
  if ($('sp-save')) $('sp-save').onclick = async () => { const v = $('sp-cid').value.trim(); if (v) { await window.orbit.post('/orbit/spotify/client', { client_id: v }); renderAccounts(); } };
  if ($('sp-on')) $('sp-on').onclick = async () => { const r = await window.orbit.post('/orbit/spotify/connect'); if (r && r.url) window.orbit.openUrl(r.url); else alert(r && r.msg || 'Não deu.'); };
  if ($('sp-off')) $('sp-off').onclick = async () => { await window.orbit.post('/orbit/spotify/disconnect'); renderAccounts(); };
}
window.orbit.onEvent && window.orbit.onEvent((ev) => { if (ev.type === 'spotify') renderAccounts(); });

async function renderPerms() {
  renderAccounts();
  const box = document.getElementById('perms');
  const st = await window.orbit.permissions().catch(() => null);
  const name = (id) => (MODULES.find((m) => m.id === id) || {}).name || id;
  box.innerHTML = PERMS.map((p) => {
    const used = p.uses.filter((id) => cfg.modules.enabled[id]);
    let state = used.length || p.always ? '<span class="pill ok">Em uso</span>' : '<span class="pill warn" title="Nenhum recurso que usa isto está ligado">Sem uso</span>';
    if (p.key === 'google' && st) state = st.agenda?.connected ? '<span class="pill ok">Conectado</span>' : '<span class="pill">Não conectado</span>';
    if (p.key === 'claude' && st?.claude?.live) state = '<span class="pill ok">Lendo a cota</span>';
    return `<div class="opt"><div class="fi" style="margin-right:12px">${icon(p.icon, 18)}</div>
      <div style="flex:1"><b>${p.name}</b><span>${p.what}</span><span class="uses">Usado por: ${p.uses.map((id) => `<i class="${cfg.modules.enabled[id] ? '' : 'offu'}">${name(id)}</i>`).join('')}</span></div>${state}</div>`;
  }).join('');
}

document.getElementById('export').onclick = async (e) => {
  const f = await window.orbit.configExport();
  if (f) { e.target.textContent = 'Exportado ✓'; setTimeout(() => { e.target.textContent = 'Exportar'; }, 2500); }
};
document.getElementById('import').onclick = async (e) => {
  const r = await window.orbit.configImport();
  if (!r) return;
  e.target.textContent = r.ok ? 'Importado ✓' : 'Erro';
  if (r.error) alert(r.error);
  setTimeout(() => { e.target.textContent = 'Importar'; }, 2500);
};
