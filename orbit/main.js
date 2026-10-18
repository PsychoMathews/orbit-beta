// Orbit: a ilha da assistente no topo da tela. Processo principal: janelas, bandeja, configurações e coleta de dados.
const { app, BrowserWindow, ipcMain, screen, Tray, Menu, nativeImage, clipboard, shell, nativeTheme, globalShortcut, dialog } = require('electron');
const http = require('http');
const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const { MODULES, DEFAULTS, names, assist } = require('./shared/catalog');

// Programa instalado (ou ORBIT_BETA=1): pasta e porta próprias, e o Orbit liga o bot sozinho (beta.js).
const beta = require('./beta');
if (beta.ON) app.setPath('userData', path.join(app.getPath('appData'), 'Orbit Beta'));
// Versão de desenvolvimento (rodando da pasta do projeto): pasta própria e fixa, separada da beta, mesmo com o nome "Orbit Beta" no package.json.
else app.setPath('userData', path.join(app.getPath('appData'), 'orbit'));
const PORT = Number(process.env.ORBIT_PORT || (beta.ON ? beta.PORT : 8788));
// A janela é maior que a ilha; o que sobra é transparente e deixa o clique passar.
const WIN_W = 900, WIN_H = 480;

if (!app.requestSingleInstanceLock()) { app.quit(); return; }
// Depuração: ORBIT_DEBUG=1 abre a ilha para inspeção em 127.0.0.1:9229 (DevTools).
if (process.env.ORBIT_DEBUG) app.commandLine.appendSwitch('remote-debugging-port', '9229');
// Sem isso, em algumas placas NVIDIA a área transparente vira um bloco preto.
app.disableHardwareAcceleration();

let island, settingsWin, tray;

// ---------- Configuração ----------

const CONFIG_FILE = path.join(app.getPath('userData'), 'config.json');
const NOTES_FILE = path.join(app.getPath('userData'), 'notas.txt');

function merge(base, extra) {
  const out = { ...base };
  for (const [k, v] of Object.entries(extra || {})) {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && base[k] ? merge(base[k], v) : v;
  }
  return out;
}

function loadConfig() {
  let saved = {};
  try { saved = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8')); } catch {}
  const cfg = merge(DEFAULTS, saved);
  // Módulos novos entram na ordem do catálogo.
  MODULES.forEach((m, i) => {
    if (cfg.modules.order.includes(m.id)) return;
    const prev = i ? cfg.modules.order.indexOf(MODULES[i - 1].id) : -1;
    cfg.modules.order.splice(prev + 1, 0, m.id); // módulo novo entra logo depois do vizinho do catálogo
  });
  cfg.modules.order = cfg.modules.order.filter((id) => MODULES.some((m) => m.id === id));
  return cfg;
}

let config = loadConfig();

function saveConfig(next) {
  config = merge(config, next);
  fs.mkdirSync(path.dirname(CONFIG_FILE), { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
  for (const w of [island, settingsWin]) if (w && !w.isDestroyed()) w.webContents.send('config', config);
  place();
  applyTheme();
}

// Tema do Orbit: claro, escuro ou seguindo o Windows.
function effectiveTheme() {
  const t = config.island.theme;
  return t === 'sistema' ? (nativeTheme.shouldUseDarkColors ? 'escuro' : 'claro') : (t || 'escuro');
}
function applyTheme() {
  const t = effectiveTheme();
  for (const w of [island, settingsWin]) if (w && !w.isDestroyed()) w.webContents.send('theme', t);
  if (settingsWin && !settingsWin.isDestroyed()) {
    const bg = t === 'claro' ? '#f4f4f6' : '#0d0d0f';
    settingsWin.setBackgroundColor(bg);
    try { settingsWin.setTitleBarOverlay({ color: bg, symbolColor: t === 'claro' ? '#333' : '#d8d8d8' }); } catch {}
  }
}
nativeTheme.on('updated', applyTheme);

// ---------- Janelas ----------

function place() {
  if (!island || island.isDestroyed()) return;
  const d = screen.getPrimaryDisplay();
  island.setBounds({ x: Math.round(d.bounds.x + (d.bounds.width - WIN_W) / 2), y: d.bounds.y, width: WIN_W, height: WIN_H });
}

function createIsland() {
  island = new BrowserWindow({
    width: WIN_W, height: WIN_H, frame: false, transparent: true, resizable: false, movable: false,
    minimizable: false, maximizable: false, fullscreenable: false, focusable: false, skipTaskbar: true,
    alwaysOnTop: true, hasShadow: false, show: false, backgroundColor: '#00000000', thickFrame: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), backgroundThrottling: false, autoplayPolicy: 'no-user-gesture-required' },
  });
  island.setAlwaysOnTop(true, 'screen-saver');
  island.setIgnoreMouseEvents(true, { forward: true });
  place();
  island.loadFile(path.join('island', 'index.html'));
  // Soltar um arquivo na ilha nunca pode trocar a página dela pela do arquivo.
  island.webContents.on('will-navigate', (e) => e.preventDefault());
  island.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  island.once('ready-to-show', () => island.showInactive());
  screen.on('display-metrics-changed', place);
  screen.on('display-added', place);
  screen.on('display-removed', place);
  // Volta para o topo se outra janela "sempre visível" passar na frente.
  setInterval(() => { if (island && !island.isDestroyed()) island.moveTop(); }, 5000);
}

function openSettings(page) {
  if (settingsWin && !settingsWin.isDestroyed()) {
    settingsWin.show(); settingsWin.focus();
    if (page) settingsWin.webContents.send('goto', page);
    return;
  }
  settingsWin = new BrowserWindow({
    width: 900, height: 640, minWidth: 760, minHeight: 520, title: 'Orbit — Configurações',
    backgroundColor: '#0d0d0f', autoHideMenuBar: true, show: false, icon: trayImage(64),
    titleBarStyle: 'hidden', titleBarOverlay: { color: '#0d0d0f', symbolColor: '#d8d8d8', height: 40 },
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
  });
  settingsWin.loadFile(path.join('settings', 'index.html'), { hash: page || '' });
  settingsWin.once('ready-to-show', () => { settingsWin.show(); applyTheme(); });
}

// Ícone desenhado em código: um anel com um ponto, sem arquivo de imagem.
function trayImage(size = 32) {
  const buf = Buffer.alloc(size * size * 4);
  const c = (size - 1) / 2, rOut = size * 0.46, rIn = size * 0.34, rDot = size * 0.14;
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const d = Math.hypot(x - c, y - c);
    const ring = Math.max(0, Math.min(1, rOut - d + 0.5)) * Math.max(0, Math.min(1, d - rIn + 0.5));
    const dot = Math.max(0, Math.min(1, rDot - d + 0.5));
    const a = Math.max(ring, dot);
    const i = (y * size + x) * 4;
    buf[i] = 255; buf[i + 1] = dot > ring ? 209 : 255; buf[i + 2] = dot > ring ? 79 : 255; buf[i + 3] = Math.round(a * 255);
  }
  return nativeImage.createFromBitmap(buf, { width: size, height: size });
}

function menuTemplate() {
  return [
    { label: `Falar com ${names('%a%')}`, click: () => bridgePost('/orbit/trigger') },
    { label: muted ? 'Tirar do mudo' : 'Mudo', click: () => bridgePost('/orbit/mute') },
    { label: status.game ? '🎮 Desligar modo jogo' : '🎮 Modo jogo', click: () => bridgePost('/orbit/gamemode', { on: !status.game }) },
    { type: 'separator' },
    { label: 'Configurações', click: () => openSettings() },
    ...(beta.ON ? [{ label: 'Refazer configuração', click: () => beta.openSetup() }] : []),
    { label: 'Recarregar a ilha', click: () => island && island.reload() },
    { type: 'separator' },
    { label: 'Sair do Orbit', click: () => app.quit() },
  ];
}

function createTray() {
  tray = new Tray(trayImage(32));
  tray.setToolTip(`Orbit — ${assist.nome}`);
  tray.on('click', () => openSettings());
  tray.on('right-click', () => tray.popUpContextMenu(Menu.buildFromTemplate(menuTemplate())));
}

// ---------- Ponte com o bot ----------

let muted = false;
// Último estado conhecido, para a ilha pedir quando (re)carrega.
const status = { online: false, state: 'idle', muted: false, game: false };

function toIsland(ev) { if (island && !island.isDestroyed()) island.webContents.send('orbit-event', ev); }

function connect() {
  const req = http.get({ host: '127.0.0.1', port: PORT, path: '/orbit/events', headers: { 'X-Orbit': '1' } }, (res) => {
    if (res.statusCode !== 200) { res.resume(); return retry(); }
    status.online = true;
    toIsland({ type: 'online' });
    let buf = '';
    res.setEncoding('utf8');
    res.on('data', (chunk) => {
      buf += chunk;
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        for (const line of block.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === 'hello' || ev.type === 'mute') muted = status.muted = ev.muted;
            if (ev.type === 'hello' && ev.assistente) { // nome escolhido por quem usa (assistente.json no bot)
              Object.assign(assist, ev.assistente); status.assistente = ev.assistente;
              if (tray) tray.setToolTip(`Orbit — ${assist.nome}`);
            }
            if (ev.type === 'theme') saveConfig({ island: { theme: ev.mode } }); // a IA trocou o tema do Orbit
            if (ev.type === 'gamemode') status.game = ev.on;
            // Modo servidor: ilha leve enquanto ele estiver ligado; ao desligar, volta como você tinha deixado.
            if (ev.type === 'server') {
              if (ev.on && !config.island.serverLite) saveConfig({ island: { serverLite: { was: !!config.island.lite }, lite: true } });
              else if (!ev.on && config.island.serverLite) saveConfig({ island: { lite: !!config.island.serverLite.was, serverLite: null } });
            }
            if (ev.type === 'hello' || ev.type === 'state') status.state = ev.state;
            toIsland(ev);
          } catch {}
        }
      }
    });
    res.on('end', retry);
    res.on('error', retry);
  });
  req.on('error', retry);
  req.setTimeout(40000, () => req.destroy()); // o servidor manda ping a cada 15 s
}
let retrying = false;
function retry() {
  if (retrying) return;
  retrying = true;
  status.online = false; status.state = 'idle';
  toIsland({ type: 'offline' });
  setTimeout(() => { retrying = false; connect(); }, 3000);
}

// Rotas que podem demorar mais (varredura do disco, pergunta para a IA).
const SLOW = { '/orbit/cleanup': 70000, '/orbit/windows/clean': 120000 };

function bridge(method, p, body) {
  return new Promise((resolve) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const req = http.request({
      host: '127.0.0.1', port: PORT, path: p, method, timeout: SLOW[p] || 15000,
      headers: { 'X-Orbit': '1', ...(data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {}) },
    }, (res) => {
      let out = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { out += c; });
      res.on('end', () => {
        if (!status.online && res.statusCode < 500) { status.online = true; toIsland({ type: 'online' }); }
        try { resolve(JSON.parse(out)); } catch { resolve(null); }
      });
    });
    req.on('error', (e) => {
      // Ponte fora do ar: a ilha precisa saber, mesmo que a conexão de eventos antiga pareça viva.
      if (e.code === 'ECONNREFUSED' && status.online) { status.online = false; toIsland({ type: 'offline' }); }
      resolve(null);
    });
    req.on('timeout', () => { req.destroy(); resolve(null); });
    if (data) req.write(data);
    req.end();
  });
}
const bridgePost = (p, body) => bridge('POST', p, body);

// ---------- Sistema ----------

let lastCpu = os.cpus();
const CPU_NAME = lastCpu[0].model.trim(), CORES = lastCpu.length;
function cpuPercent() {
  const now = os.cpus();
  let idle = 0, total = 0;
  now.forEach((c, i) => {
    const a = c.times, b = lastCpu[i] ? lastCpu[i].times : { user: 0, nice: 0, sys: 0, idle: 0, irq: 0 };
    const t = (a.user - b.user) + (a.nice - b.nice) + (a.sys - b.sys) + (a.irq - b.irq) + (a.idle - b.idle);
    total += t; idle += a.idle - b.idle;
  });
  lastCpu = now;
  return total ? Math.round(100 * (1 - idle / total)) : 0;
}

function gpuStats() {
  return new Promise((resolve) => {
    execFile('nvidia-smi', ['--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu',
      '--format=csv,noheader,nounits'], { timeout: 3000, windowsHide: true }, (err, out) => {
      if (err) return resolve(null);
      const [name, util, used, total, temp] = out.trim().split('\n')[0].split(',').map((s) => s.trim());
      resolve({ name, util: +util, memUsed: +used, memTotal: +total, temp: +temp });
    });
  });
}

// Rede: bytes recebidos/enviados do Windows (netstat -e), vira velocidade entre duas leituras.
let lastNet = null;
function netStats() {
  return new Promise((resolve) => {
    execFile('netstat', ['-e'], { timeout: 3000, windowsHide: true }, (err, out) => {
      const m = !err && /^\S+\s+(\d+)\s+(\d+)\s*$/m.exec(out); // linha "Bytes  recebido  enviado"
      const ips = Object.entries(os.networkInterfaces()).flatMap(([name, list]) => (list || [])
        .filter((a) => a.family === 'IPv4' && !a.internal && !/vEthernet|VirtualBox|VMware|Tailscale|Loopback/i.test(name))
        .map((a) => ({ name, ip: a.address })));
      if (!m) return resolve({ ip: ips[0]?.ip || '', iface: ips[0]?.name || '' });
      const now = { rx: +m[1], tx: +m[2], t: Date.now() };
      let rx = 0, tx = 0;
      if (lastNet && now.rx >= lastNet.rx && now.tx >= lastNet.tx) {
        const dt = (now.t - lastNet.t) / 1000;
        rx = (now.rx - lastNet.rx) / dt; tx = (now.tx - lastNet.tx) / dt;
      }
      lastNet = now;
      resolve({ rx, tx, ip: ips[0]?.ip || '', iface: ips[0]?.name || '' });
    });
  });
}

// Teste de velocidade pelos servidores da Cloudflare (o mesmo do speed.cloudflare.com).
function timed(method, url, body) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    let n = 0;
    const req = https.request(url, { method, timeout: 20000, headers: body ? { 'Content-Type': 'application/octet-stream', 'Content-Length': body.length } : {} }, (res) => {
      res.on('data', (c) => { n += c.length; });
      res.on('end', () => resolve({ ms: Date.now() - t0, bytes: n }));
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    if (body) req.write(body);
    req.end();
  });
}
let speedRunning = false;
// Vários downloads/uploads ao mesmo tempo por alguns segundos (um só não enche uma conexão rápida),
// com o resultado parcial mandado para a ilha a cada 250 ms.
function flood(kind, seconds, streams, onBytes) {
  return new Promise((resolve) => {
    const base = 'https://speed.cloudflare.com/', end = Date.now() + seconds * 1000, reqs = new Set();
    let open = 0;
    const one = () => {
      if (Date.now() > end) { if (!open) resolve(); return; }
      open++;
      const done = () => { reqs.delete(req); open--; one(); };
      const opts = { method: kind === 'down' ? 'GET' : 'POST', timeout: 15000, headers: kind === 'up' ? { 'Content-Type': 'application/octet-stream', 'Content-Length': 8e6 } : {} };
      const req = https.request(base + (kind === 'down' ? '__down?bytes=50000000' : '__up'), opts, (res) => {
        res.on('data', (c) => { if (kind === 'down') onBytes(c.length); if (Date.now() > end) req.destroy(); });
        res.on('end', done); res.on('error', done);
      });
      reqs.add(req);
      req.on('error', done); req.on('timeout', () => req.destroy());
      req.on('close', () => { if (reqs.has(req)) done(); });
      if (kind === 'up') {
        const chunk = Buffer.alloc(256 * 1024);
        let sent = 0;
        const pump = () => {
          while (sent < 8e6) {
            if (Date.now() > end) { req.destroy(); return; }
            sent += chunk.length; onBytes(chunk.length);
            if (!req.write(chunk)) { req.once('drain', pump); return; }
          }
          req.end();
        };
        pump();
      } else req.end();
    };
    for (let i = 0; i < streams; i++) one();
    setTimeout(() => { for (const r of reqs) r.destroy(); resolve(); }, seconds * 1000 + 3000);
  });
}
async function measure(kind, ping, send, extra) {
  let bytes = 0, t0 = 0, best = 0;
  const tick = setInterval(() => {
    if (!t0) return;
    const mbps = (bytes * 8) / ((Date.now() - t0) / 1000) / 1e6;
    best = mbps;
    send({ phase: kind, ping, ...extra, [kind]: mbps });
  }, 250);
  // Primeiro meio segundo é aquecimento (a conexão ainda está acelerando): não entra na conta.
  setTimeout(() => { bytes = 0; t0 = Date.now(); }, 700);
  await flood(kind, 7, 6, (n) => { bytes += n; });
  clearInterval(tick);
  return t0 ? (bytes * 8) / ((Date.now() - t0) / 1000) / 1e6 : best;
}
async function speedTest(send) {
  if (speedRunning) return null;
  speedRunning = true;
  try {
    const pings = [];
    for (let i = 0; i < 6; i++) { const r = await timed('GET', 'https://speed.cloudflare.com/__down?bytes=0'); if (r) pings.push(r.ms); }
    const ping = pings.length ? Math.min(...pings) : null;
    send({ phase: 'down', ping });
    const down = await measure('down', ping, send, {});
    send({ phase: 'up', ping, down });
    const up = await measure('up', ping, send, { down });
    const result = { phase: 'done', ping, down, up, link: linkSpeed(), t: Date.now() };
    send(result);
    return result;
  } finally { speedRunning = false; }
}

// Velocidade em que a placa de rede está conectada (ex.: 100 Mbps num cabo Cat5 limita a internet).
let linkCache = null;
function linkSpeed() { return linkCache; }
function readLink() {
  execFile('powershell', ['-NoProfile', '-Command', "Get-NetAdapter | ? Status -eq 'Up' | ? InterfaceDescription -notmatch 'Tailscale|Virtual|VPN|Hyper-V' | Select -First 1 Name,LinkSpeed,MediaType | ConvertTo-Json"],
    { timeout: 8000, windowsHide: true }, (err, out) => { try { linkCache = JSON.parse(out); } catch {} });
}

async function systemStats() {
  let disk = null;
  try {
    const s = fs.statfsSync('C:\\');
    disk = { free: s.bavail * s.bsize, total: s.blocks * s.bsize };
  } catch {}
  return {
    cpu: cpuPercent(), cpuName: CPU_NAME, cores: CORES,
    memUsed: os.totalmem() - os.freemem(), memTotal: os.totalmem(),
    gpu: await gpuStats(), disk, uptime: os.uptime(), net: { ...(await netStats()), link: linkCache },
  };
}

// ---------- Uso de IA (Claude Code e Ollama) ----------

const CLAUDE_DIR = path.join(os.homedir(), '.claude', 'projects');
const tokenFiles = new Map(); // arquivo -> {offset, rest, entries: Map(id -> {day, model, tokens})}

function dayKey(d) { return d.toLocaleDateString('sv-SE'); }

// Valor estimado em API (US$ por milhão de tokens: entrada, saída). Cache: escrita 1,25x e leitura 0,1x da entrada.
const PRICES = [[/haiku/, 1, 5], [/sonnet/, 3, 15], [/opus|fable/, 5, 25]];
function cost(model, u) {
  const p = PRICES.find(([re]) => re.test(model)) || PRICES[1];
  return ((u.input_tokens || 0) * p[1] + (u.cache_creation_input_tokens || 0) * p[1] * 1.25
    + (u.cache_read_input_tokens || 0) * p[1] * 0.1 + (u.output_tokens || 0) * p[2]) / 1e6;
}

// Lê só o que foi acrescentado desde a última vez (os registros chegam a dezenas de MB) e sem travar a janela.
async function readAppended(full, st) {
  let known = tokenFiles.get(full);
  if (!known || st.size < known.offset) { known = { offset: 0, rest: '', entries: new Map() }; tokenFiles.set(full, known); }
  if (st.size === known.offset) return;
  const fh = await fs.promises.open(full, 'r');
  try {
    const len = st.size - known.offset;
    const buf = Buffer.alloc(len);
    await fh.read(buf, 0, len, known.offset);
    known.offset = st.size;
    const lines = (known.rest + buf.toString('utf8')).split('\n');
    known.rest = lines.pop(); // linha ainda incompleta
    for (const line of lines) {
      if (!line.includes('"usage"')) continue;
      try {
        const j = JSON.parse(line);
        const m = j.message;
        if (!m || !m.usage || !m.id) continue;
        const u = m.usage;
        known.entries.set(m.id, {
          day: dayKey(new Date(j.timestamp || st.mtimeMs)), model: m.model || '?',
          input: (u.input_tokens || 0) + (u.cache_creation_input_tokens || 0),
          cached: u.cache_read_input_tokens || 0, output: u.output_tokens || 0,
          cost: cost(m.model || '', u), project: j.cwd ? path.basename(j.cwd) : '?',
        });
      } catch {}
    }
  } finally { await fh.close(); }
}

let scanning = null;
function scanTokens() { return scanning || (scanning = scanTokensNow().finally(() => { scanning = null; })); }

async function scanTokensNow() {
  const since = Date.now() - 31 * 86400e3;
  let dirs = [];
  try { dirs = await fs.promises.readdir(CLAUDE_DIR); } catch { return null; }
  for (const d of dirs) {
    let files = [];
    try { files = (await fs.promises.readdir(path.join(CLAUDE_DIR, d))).filter((f) => f.endsWith('.jsonl')); } catch { continue; }
    for (const f of files) {
      const full = path.join(CLAUDE_DIR, d, f);
      let st;
      try { st = await fs.promises.stat(full); } catch { continue; }
      if (st.mtimeMs < since) continue;
      try { await readAppended(full, st); } catch {}
    }
  }
  // Por dia (últimos 31): tokens, valor em API, cache, modelos e projetos. A aba soma pelo período escolhido.
  const days = {};
  for (const { entries } of tokenFiles.values()) for (const e of entries.values()) {
    const d = (days[e.day] ||= { input: 0, cached: 0, output: 0, cost: 0, messages: 0, models: {}, projects: {} });
    d.input += e.input; d.cached += e.cached; d.output += e.output; d.cost += e.cost || 0; d.messages++;
    const t = e.input + e.output + e.cached;
    const m = (d.models[e.model] ||= { tokens: 0, cost: 0 }); m.tokens += t; m.cost += e.cost || 0;
    const p = (d.projects[e.project] ||= { tokens: 0, cost: 0 }); p.tokens += t; p.cost += e.cost || 0;
  }
  return { days };
}

function ollamaPs() {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port: 11434, path: '/api/ps', timeout: 2000 }, (res) => {
      let out = '';
      res.on('data', (c) => { out += c; });
      res.on('end', () => { try { resolve(JSON.parse(out).models || []); } catch { resolve(null); } });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

// ---------- Área de transferência ----------

const CLIP_FILE = path.join(app.getPath('userData'), 'clipboard.json');
let clips = [];
try { clips = JSON.parse(fs.readFileSync(CLIP_FILE, 'utf8')); } catch {}
let lastClip = clipboard.readText();
let clipSaveTimer = null;
function watchClipboard() {
  setInterval(() => {
    if (!config.modules.enabled.clipboard) return;
    const text = clipboard.readText();
    if (!text || text === lastClip) return;
    lastClip = text;
    if (text.length > 20000) return;
    clips = [{ text, t: Date.now() }, ...clips.filter((c) => c.text !== text)].slice(0, config.clipboard.max);
    toIsland({ type: 'clipboard', clips });
    clearTimeout(clipSaveTimer);
    clipSaveTimer = setTimeout(() => fs.writeFile(CLIP_FILE, JSON.stringify(clips), () => {}), 1000);
  }, 800);
}

// ---------- Downloads e prateleira de arquivos ----------

const DL_DIR = app.getPath('downloads');
const PARTIAL = /\.(crdownload|part|partial|download|tmp)$/i;
const dlSeen = new Map(); // arquivo parcial -> {size, t, speed}
let dlRecent = [];

function dlList() {
  let names = [];
  try { names = fs.readdirSync(DL_DIR); } catch { return { active: [], recent: [] }; }
  const now = Date.now(), active = [], done = [];
  for (const n of names) {
    let st;
    try { st = fs.statSync(path.join(DL_DIR, n)); } catch { continue; }
    if (!st.isFile()) continue;
    if (PARTIAL.test(n)) {
      if (now - st.mtimeMs > 120e3) continue; // parcial abandonado
      const prev = dlSeen.get(n), dt = prev ? (now - prev.t) / 1000 : 0;
      const speed = prev && dt > 0 ? Math.max(0, (st.size - prev.size) / dt) : 0;
      dlSeen.set(n, { size: st.size, t: now, speed: prev ? prev.speed * 0.6 + speed * 0.4 : 0 });
      active.push({ name: n.replace(PARTIAL, '').replace(/^Não confirmado \d+\.?/, 'Baixando…'), size: st.size, speed: dlSeen.get(n).speed });
    } else done.push({ name: n, path: path.join(DL_DIR, n), size: st.size, t: st.birthtimeMs || st.mtimeMs });
  }
  for (const k of dlSeen.keys()) if (!names.includes(k)) dlSeen.delete(k);
  done.sort((a, b) => b.t - a.t);
  return { active, recent: done.slice(0, 12) };
}

let dlActive = false, dlKnown = null;
function watchDownloads() {
  const tick = () => {
    if (!config.modules.enabled.arquivos) return;
    const d = dlList();
    const names = new Set(d.recent.map((r) => r.path));
    if (dlKnown) {
      // Arquivo novo e recente (até 2 min) na pasta: download que acabou de terminar.
      for (const r of d.recent) if (!dlKnown.has(r.path) && Date.now() - r.t < 120e3) toIsland({ type: 'download_done', file: r });
    }
    dlKnown = names;
    dlRecent = d.recent;
    if (d.active.length || dlActive) toIsland({ type: 'downloads', ...d });
    dlActive = d.active.length > 0;
  };
  tick();
  setInterval(tick, 1000);
}

const SHELF_FILE = path.join(app.getPath('userData'), 'prateleira.json');
let shelf = [];
try { shelf = JSON.parse(fs.readFileSync(SHELF_FILE, 'utf8')); } catch {}
function saveShelf() { fs.writeFile(SHELF_FILE, JSON.stringify(shelf), () => {}); toIsland({ type: 'shelf', shelf }); }

// Ícone do arraste: o ícone do próprio arquivo no Windows.
async function dragIcon(file) {
  try { return await app.getFileIcon(file, { size: 'normal' }); } catch { return trayImage(32); }
}

// Arrastar um arquivo para a pílula: a janela ignora o mouse, então o processo principal liga o mouse
// quando o cursor está em cima da pílula (senão o "soltar" atravessaria a ilha).
let islandRect = null;
function watchCursor() {
  let inside = false;
  setInterval(() => {
    if (!island || island.isDestroyed() || !islandRect) return;
    const p = screen.getCursorScreenPoint(), b = island.getBounds();
    const x = p.x - b.x, y = p.y - b.y, r = islandRect;
    const now = x >= r.x - 6 && x <= r.x + r.w + 6 && y >= r.y - 6 && y <= r.y + r.h + 6;
    if (now && !inside) island.setIgnoreMouseEvents(false);
    inside = now;
  }, 120);
}

// ---------- Letra da música (lrclib.net, só quando você abre a letra) ----------

const lyricsCache = new Map();
function getJson(url, timeout = 8000) {
  return new Promise((resolve) => {
    const req = https.get(url, { headers: { 'User-Agent': 'Orbit 1.0' }, timeout }, (res) => {
      let out = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { out += c; });
      res.on('end', () => { try { resolve(res.statusCode === 200 ? JSON.parse(out) : res.statusCode === 404 ? { notFound: true } : { busy: true }); } catch { resolve({ busy: true }); } });
    });
    req.on('error', () => resolve({ busy: true }));
    req.on('timeout', () => { req.destroy(); resolve({ busy: true }); });
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// O lrclib às vezes responde "ocupado" (503): tenta de novo algumas vezes antes de desistir.
async function getJsonRetry(url) {
  for (let i = 0; i < 4; i++) { const r = await getJson(url); if (!r || !r.busy) return r; await sleep(700 * (i + 1)); }
  return { busy: true };
}
// Título do YouTube vem como "Artista - Música (Clipe Oficial)": separa e limpa.
function cleanTrack(artist, title) {
  let t = String(title || '').replace(/\s*[([](official|clipe|video|vídeo|lyric|letra|audio|áudio|hd|4k|ao vivo|live)[^)\]]*[)\]]/gi, '').trim();
  let a = String(artist || '').replace(/\s*-\s*Topic$/i, '').replace(/VEVO$/i, '').trim();
  const m = /^(.+?)\s+[-–—]\s+(.+)$/.exec(t);
  if (m && (!a || /youtube|chrome|edge|opera/i.test(a) || t.toLowerCase().startsWith(a.toLowerCase()))) { a = m[1]; t = m[2]; }
  return { a, t: t.replace(/\s*(ft\.|feat\.).*$/i, '').trim() };
}
async function lyrics(artist, title, duration) {
  const { a, t } = cleanTrack(artist, title);
  const key = (a + '|' + t).toLowerCase();
  if (lyricsCache.has(key)) return lyricsCache.get(key);
  const q = (o) => Object.entries(o).filter(([, v]) => v).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');
  let busy = false;
  let r = a ? await getJsonRetry('https://lrclib.net/api/get?' + q({ artist_name: a, track_name: t, duration: duration ? Math.round(duration) : '' })) : null;
  if (r && r.busy) { busy = true; r = null; }
  if (r && r.notFound) r = null;
  if (!r) {
    const list = await getJsonRetry('https://lrclib.net/api/search?' + q({ q: (a + ' ' + t).trim() }));
    if (list && list.busy) busy = true;
    r = Array.isArray(list) ? list.find((x) => x.syncedLyrics) || list.find((x) => x.plainLyrics) || null : null;
  }
  const out = r ? { synced: r.syncedLyrics || '', plain: r.plainLyrics || '' } : busy ? { busy: true } : { none: true };
  if (!out.busy) lyricsCache.set(key, out); // falha de rede não fica guardada: na próxima vez tenta de novo
  return out;
}

// ---------- IPC ----------

ipcMain.on('interactive', (_e, on) => island && island.setIgnoreMouseEvents(!on, { forward: true }));
ipcMain.on('focus', (_e, on) => {
  if (!island) return;
  island.setFocusable(!!on);
  if (on) island.focus(); else island.blur();
});
// A ilha não pega o foco (para não atrapalhar o que você está usando), então o Esc só chega
// por um atalho global, ligado apenas enquanto ela está aberta.
ipcMain.on('expanded', (_e, open) => {
  if (open && !globalShortcut.isRegistered('Escape')) {
    globalShortcut.register('Escape', () => island && island.webContents.send('escape'));
  } else if (!open && globalShortcut.isRegistered('Escape')) {
    globalShortcut.unregister('Escape');
  }
});
app.on('will-quit', () => globalShortcut.unregisterAll());
// Mutar todos os microfones de qualquer lugar (como no Vorssaint).
function micShortcut() {
  try { globalShortcut.register('Control+Alt+M', () => bridgePost('/orbit/audio/output', { mic: null })); } catch {}
}
ipcMain.on('menu', () => Menu.buildFromTemplate(menuTemplate()).popup({ window: island }));
ipcMain.on('open-settings', (_e, page) => openSettings(page));
ipcMain.on('open-url', (_e, url) => { if (/^https:\/\//.test(url)) shell.openExternal(url); });
ipcMain.handle('bridge', (_e, method, p, body) => (p.startsWith('/orbit/') ? bridge(method, p, body) : null));
ipcMain.handle('status', () => status);
ipcMain.handle('theme', () => effectiveTheme());
ipcMain.handle('system', () => systemStats());
ipcMain.handle('speedtest', (e) => speedTest((p) => { if (!e.sender.isDestroyed()) e.sender.send('speed', p); }));
ipcMain.handle('ai-usage', async () => ({ claude: await scanTokens(), ollama: await ollamaPs() }));
ipcMain.handle('clips', () => clips);
ipcMain.on('island-rect', (_e, r) => { islandRect = r; });
ipcMain.handle('downloads', () => dlList());
ipcMain.handle('lyrics', (_e, a, t, d) => lyrics(a, t, d));
ipcMain.handle('shelf', () => shelf);
ipcMain.on('shelf-add', (_e, items) => {
  for (const it of items || []) {
    if (it.path && !fs.existsSync(it.path)) continue;
    if (shelf.some((s) => (it.path && s.path === it.path) || (it.text && s.text === it.text))) continue;
    shelf.unshift({ ...it, t: Date.now() });
  }
  shelf = shelf.slice(0, 40);
  saveShelf();
});
ipcMain.on('shelf-remove', (_e, i) => { if (i === 'all') shelf = []; else shelf.splice(i, 1); saveShelf(); });
ipcMain.on('file-open', (_e, f) => { if (f && fs.existsSync(f)) shell.openPath(f); });
ipcMain.on('file-show', (_e, f) => { if (f && fs.existsSync(f)) shell.showItemInFolder(f); else shell.openPath(DL_DIR); });
const dragIconCache = new Map();
ipcMain.on('file-drag', (e, f) => {
  const files = (Array.isArray(f) ? f : [f]).filter((x) => x && fs.existsSync(x));
  // O arraste precisa começar na hora (esperar o ícone do arquivo fazia o Windows ignorar o arraste).
  if (files.length) e.sender.startDrag({ file: files[0], files, icon: dragIconCache.get(path.extname(files[0]).toLowerCase()) || trayImage(32) });
  for (const x of files) { const k = path.extname(x).toLowerCase(); if (!dragIconCache.has(k)) dragIcon(x).then((i) => { if (!i.isEmpty()) dragIconCache.set(k, i); }); }
});
ipcMain.on('copy', (_e, text) => { lastClip = text; clipboard.writeText(text); });
ipcMain.on('clips-clear', () => { clips = []; fs.writeFile(CLIP_FILE, '[]', () => {}); toIsland({ type: 'clipboard', clips }); });
ipcMain.handle('notes-get', () => { try { return fs.readFileSync(NOTES_FILE, 'utf8'); } catch { return ''; } });
ipcMain.on('notes-set', (_e, text) => fs.writeFile(NOTES_FILE, String(text), () => {}));
ipcMain.handle('config-get', () => ({ config, modules: MODULES }));
ipcMain.on('config-set', (_e, next) => {
  saveConfig(next);
  // Mexeu em tamanho/posição da ilha nas Configurações: ela abre um instante para você ver o resultado.
  if (next.island && island) {
    if ('idleOpacity' in next.island) island.webContents.send('preview', 'idle');
    else if (['panelWidth', 'offsetY', 'theme'].some((k) => k in next.island)) island.webContents.send('preview', 'open');
  }
});
// Exportar/importar: só as opções do Orbit (nada de conversas, notas ou contas), para levar a outro PC ou passar a um amigo.
ipcMain.handle('config-export', async () => {
  const r = await dialog.showSaveDialog(settingsWin, { title: 'Exportar configurações do Orbit', defaultPath: 'orbit-configuracoes.json', filters: [{ name: 'JSON', extensions: ['json'] }] });
  if (r.canceled || !r.filePath) return null;
  fs.writeFileSync(r.filePath, JSON.stringify({ orbit: 1, exported: new Date().toISOString(), config }, null, 2));
  return r.filePath;
});
ipcMain.handle('config-import', async () => {
  const r = await dialog.showOpenDialog(settingsWin, { title: 'Importar configurações do Orbit', properties: ['openFile'], filters: [{ name: 'JSON', extensions: ['json'] }] });
  if (r.canceled || !r.filePaths[0]) return null;
  try {
    const j = JSON.parse(fs.readFileSync(r.filePaths[0], 'utf8'));
    const c = j.config || j;
    if (!c.modules || !c.island) return { error: 'Esse arquivo não é uma configuração do Orbit.' };
    // Só as chaves conhecidas entram (um arquivo estranho não injeta nada).
    const pick = (src, base) => Object.fromEntries(Object.keys(base).filter((k) => k in (src || {})).map((k) => [k, src[k]]));
    saveConfig({ island: pick(c.island, DEFAULTS.island), friday: pick(c.friday, DEFAULTS.friday), clipboard: pick(c.clipboard, DEFAULTS.clipboard),
      modules: { enabled: pick(c.modules.enabled, DEFAULTS.modules.enabled), order: (c.modules.order || []).filter((id) => MODULES.some((m) => m.id === id)) } });
    return { ok: true };
  } catch { return { error: 'Não consegui ler esse arquivo.' }; }
});
ipcMain.handle('permissions', async () => ({
  agenda: await bridge('GET', '/orbit/agenda'), claude: await bridge('GET', '/orbit/claude'), online: status.online,
}));
ipcMain.on('config-reset', () => { config = loadConfig(); saveConfig(JSON.parse(JSON.stringify(DEFAULTS))); });

function startAll() {
  createIsland();
  createTray();
  connect();
  watchClipboard();
  watchDownloads();
  watchCursor();
  micShortcut();
  readLink(); setInterval(readLink, 60000);
}

app.whenReady().then(() => {
  app.setAppUserModelId(beta.ON ? 'Orbit.Beta' : 'Orbit.App');
  if (!beta.ON) return startAll();
  if (app.isPackaged) app.setLoginItemSettings({ openAtLogin: true }); // instalado: abre junto com o Windows
  beta.setupIpc();
  if (beta.configured()) { beta.startBot(); startAll(); } else beta.openSetup(startAll); // primeira vez: guia antes da ilha
});
app.on('before-quit', () => { if (beta.ON) beta.stopBot(); });
app.on('second-instance', () => openSettings());
app.on('window-all-closed', (e) => e.preventDefault());
