// Modo beta (programa instalado): o Orbit liga o bot sozinho, com o Python embutido, e na primeira abertura
// mostra o guia de configuração. Os dados de quem usa ficam em %APPDATA%\Orbit Beta\dados (nada vem de quem criou o projeto).
// Na pasta de desenvolvimento (sem instalar) nada disto roda: o bot é ligado pelo Agendador de Tarefas.
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn, execFile } = require('child_process');
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');

const ON = app.isPackaged || !!process.env.ORBIT_BETA;
const PORT = 8790; // diferente do 8788 da versão de desenvolvimento, para as duas poderem rodar no mesmo PC

function dataDir() { return path.join(app.getPath('userData'), 'dados'); }
function core() { return app.isPackaged ? path.join(process.resourcesPath, 'core') : path.join(__dirname, '..'); }
function pyDir() { return app.isPackaged ? path.join(process.resourcesPath, 'python') : path.join(__dirname, '..', '.venv', 'Scripts'); }
function configured() { return fs.existsSync(path.join(dataDir(), 'assistente.json')) && fs.existsSync(path.join(dataDir(), '.env')); }

function env() {
  const py = pyDir();
  return { ...process.env, ORBIT_DATA_DIR: dataDir(), ORBIT_PORT: String(PORT), PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1',
    PATH: [py, path.join(py, 'Scripts'), process.env.PATH].join(path.delimiter) }; // ffmpeg.exe mora junto do Python
}

// ---------- Bot ----------

let bot = null, stopping = false, crashes = [];
function startBot() {
  if (bot) return;
  fs.mkdirSync(path.join(dataDir(), 'memoria'), { recursive: true });
  const log = fs.openSync(path.join(dataDir(), 'memoria', 'bot.log'), 'a');
  bot = spawn(path.join(pyDir(), 'pythonw.exe'), ['-m', 'friday.bot'], { cwd: core(), env: env(), stdio: ['ignore', log, log], windowsHide: true });
  bot.on('exit', (code) => {
    bot = null;
    if (stopping) return;
    // Caiu: liga de novo, mas desiste se cair 5 vezes em 2 minutos (o log mostra o motivo).
    crashes = crashes.filter((t) => Date.now() - t < 120000).concat(Date.now());
    if (crashes.length < 5) setTimeout(startBot, 3000);
    else dialog.showErrorBox('Orbit', `O assistente parou de funcionar (código ${code}).\nDetalhes em:\n${path.join(dataDir(), 'memoria', 'bot.log')}`);
  });
}
// Mata o bot e os filhos dele (reconhecimento de voz e medidor de som rodam em processos à parte).
function killTree(p) { try { execFile('taskkill', ['/PID', String(p.pid), '/T', '/F'], { windowsHide: true }); } catch {} }
function stopBot() { stopping = true; if (bot) killTree(bot); }
function restartBot() {
  crashes = [];
  if (!bot) { stopping = false; return startBot(); }
  bot.once('exit', () => { stopping = false; startBot(); });
  stopping = true; killTree(bot);
}

// ---------- Guia de primeira abertura ----------

let win = null, onDone = null;
function openSetup(done) {
  onDone = done || onDone;
  if (win && !win.isDestroyed()) { win.show(); win.focus(); return; }
  win = new BrowserWindow({ width: 720, height: 760, minWidth: 600, minHeight: 600, title: 'Orbit — Primeira configuração',
    backgroundColor: '#0d0d0f', autoHideMenuBar: true, show: false,
    webPreferences: { preload: path.join(__dirname, 'setup', 'preload.js') } });
  win.loadFile(path.join(__dirname, 'setup', 'index.html'));
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => { win = null; if (!configured()) app.quit(); }); // fechou sem terminar: sai
}

function request(mod, opts, body) {
  return new Promise((resolve) => {
    const req = mod.request({ timeout: 20000, ...opts }, (res) => {
      let d = ''; res.setEncoding('utf8'); res.on('data', (c) => (d += c));
      res.on('end', () => { let j = null; try { j = JSON.parse(d); } catch {} resolve({ status: res.statusCode, json: j }); });
    });
    req.on('error', (e) => resolve({ status: 0, error: e.message }));
    req.on('timeout', () => req.destroy(new Error('sem resposta')));
    if (body) req.write(body);
    req.end();
  });
}

const TESTS = {
  async claude({ key, model }) {
    const body = JSON.stringify({ model, max_tokens: 20, messages: [{ role: 'user', content: 'Responda só: funcionou' }] });
    const r = await request(https, { host: 'api.anthropic.com', path: '/v1/messages', method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) } }, body);
    if (r.status === 200) return { ok: true, msg: 'Funcionou: o Claude respondeu.' };
    if (r.status === 401) return { ok: false, msg: 'Chave recusada. Confira se copiou a chave inteira (começa com sk-ant-).' };
    if (r.status === 400 && /credit/i.test(JSON.stringify(r.json))) return { ok: false, msg: 'A chave funciona, mas a conta está sem crédito. Adicione crédito em Billing.' };
    if (r.status === 404) return { ok: false, msg: 'Esse modelo não está disponível para a sua conta. Escolha outro.' };
    return { ok: false, msg: r.error ? `Sem conexão com a Anthropic (${r.error}).` : `A Anthropic respondeu ${r.status}: ${r.json?.error?.message || ''}` };
  },
  async ollama() {
    const r = await request(http, { host: '127.0.0.1', port: 11434, path: '/api/tags', method: 'GET', timeout: 4000 });
    if (r.status !== 200) return { ok: false, msg: 'Ollama não encontrado neste PC (opcional).', models: [] };
    const models = (r.json?.models || []).map((m) => m.name);
    return { ok: models.length > 0, msg: models.length ? `Ollama ligado com ${models.length} modelo(s).` : 'Ollama ligado, mas sem modelos. Rode: ollama pull qwen3:8b', models };
  },
  async elevenlabs({ key }) {
    const r = await request(https, { host: 'api.elevenlabs.io', path: '/v1/voices', method: 'GET', headers: { 'xi-api-key': key } });
    if (r.status === 200) return { ok: true, msg: 'Funcionou.', voices: (r.json?.voices || []).map((v) => ({ id: v.voice_id, name: v.name })) };
    return { ok: false, msg: r.status === 401 ? 'Chave da ElevenLabs recusada.' : `Não consegui falar com a ElevenLabs (${r.status || r.error}).` };
  },
  async voz({ voice }) { // fala uma frase com a voz escolhida, pelo próprio Python do pacote
    return new Promise((resolve) => {
      execFile(path.join(pyDir(), 'python.exe'), ['-m', 'friday.voz_teste', voice, 'Oi! Esta é a minha voz.'],
        { cwd: core(), env: env(), timeout: 60000, windowsHide: true }, (err, out, errOut) => {
          resolve(err ? { ok: false, msg: 'Não consegui tocar a voz: ' + String(errOut || err.message).trim().split('\n').pop() } : { ok: true, msg: 'Tocou nas caixas de som.' });
        });
    });
  },
};

const q = (v) => String(v ?? '').replace(/[\r\n]/g, ' ').trim();
function writeSetup(d) {
  const dir = dataDir();
  fs.mkdirSync(path.join(dir, 'memoria'), { recursive: true });
  const assistente = { nome: q(d.nome) || 'Orbit', artigo: d.artigo === 'o' ? 'o' : 'a', usuario: q(d.usuario), tratamento: q(d.tratamento),
    sobre_usuario: q(d.sobre_linha), personalidade: d.personalidade || 'direta', personalidade_texto: String(d.personalidade_texto || '').trim(),
    apelidos: [], correcoes: {} };
  fs.writeFileSync(path.join(dir, 'assistente.json'), JSON.stringify(assistente, null, 2));
  const lines = [
    '# Gerado pelo guia de primeira configuração do Orbit. Pode editar; reinicie o Orbit depois.',
    `ANTHROPIC_API_KEY=${q(d.claudeKey)}`, `CLOUD_MODEL=${q(d.claudeModel) || 'claude-sonnet-5-5'}`, 'CLOUD_EFFORT=low', 'CLOUD_CHANNELS=pc',
    `OLLAMA_MODEL=${q(d.ollamaModel) || 'qwen3:8b'}`,
    `VOICE_ENGINE=${d.elevenKey ? 'elevenlabs' : 'local'}`, `ELEVENLABS_API_KEY=${q(d.elevenKey)}`, `ELEVENLABS_VOICE_ID=${q(d.elevenVoice)}`,
    `EDGE_VOICE=${q(d.edgeVoice) || 'pt-BR-FranciscaNeural'}`, 'STT_ENGINE=local', 'WHISPER_MODEL=small', 'WHISPER_DEVICE=cpu',
    `HOTKEY=${q(d.hotkey) || 'ctrl+alt+space'}`, `HOME_CITY=${q(d.cidade) || 'São Paulo'}`, 'PC_SPEAK=1',
    'MORNING_TIME=', // resumo da manhã desligado até a pessoa pedir
  ];
  fs.writeFileSync(path.join(dir, '.env'), lines.join('\n') + '\n');
  if (d.sobre) { // "Sobre mim" do guia vira o começo do SOBRE_MIM.md
    const f = path.join(dir, 'memoria', 'SOBRE_MIM.md');
    if (!fs.existsSync(f)) fs.writeFileSync(f, `# Sobre mim\n\n## Quem sou\n- Nome: ${q(d.usuario)}\n\n${String(d.sobre).trim()}\n\n## Aprendido\n`);
  }
}

function load() { // para refazer o guia com os dados já preenchidos (sem mostrar chaves inteiras)
  const out = {};
  try { Object.assign(out, JSON.parse(fs.readFileSync(path.join(dataDir(), 'assistente.json'), 'utf8'))); } catch {}
  try {
    for (const l of fs.readFileSync(path.join(dataDir(), '.env'), 'utf8').split('\n')) {
      const m = l.match(/^([A-Z_]+)=(.*)$/); if (m) out['env_' + m[1]] = m[2];
    }
  } catch {}
  return out;
}

function setupIpc() {
  ipcMain.handle('setup-test', (_e, kind, args) => (TESTS[kind] ? TESTS[kind](args || {}) : { ok: false, msg: '?' }));
  ipcMain.handle('setup-load', () => load());
  ipcMain.on('setup-open', (_e, url) => { if (/^https:\/\//.test(url)) require('electron').shell.openExternal(url); });
  ipcMain.handle('setup-save', (_e, d) => {
    try { writeSetup(d); } catch (e) { return { ok: false, msg: 'Não consegui salvar: ' + e.message }; }
    const done = onDone; onDone = null;
    if (win && !win.isDestroyed()) win.destroy();
    restartBot();
    if (done) done();
    return { ok: true };
  });
  ipcMain.handle('setup-google', async () => { // importa o credentials.json da pessoa e abre o login do Google
    const r = await dialog.showOpenDialog(win, { title: 'Escolha o arquivo baixado do Google Cloud (credentials.json)', properties: ['openFile'], filters: [{ name: 'JSON', extensions: ['json'] }] });
    if (r.canceled || !r.filePaths[0]) return { ok: false, msg: 'Nenhum arquivo escolhido.' };
    try {
      const j = JSON.parse(fs.readFileSync(r.filePaths[0], 'utf8'));
      if (!j.installed) return { ok: false, msg: 'Esse arquivo não é de "App para computador". Crie o ID do cliente OAuth com esse tipo.' };
    } catch { return { ok: false, msg: 'Não consegui ler esse arquivo.' }; }
    fs.mkdirSync(dataDir(), { recursive: true });
    fs.copyFileSync(r.filePaths[0], path.join(dataDir(), 'credentials.json'));
    return new Promise((resolve) => {
      execFile(path.join(pyDir(), 'python.exe'), ['-m', 'friday.google_auth'], { cwd: core(), env: env(), timeout: 300000, windowsHide: true },
        (err, out, errOut) => resolve(err ? { ok: false, msg: 'O login não terminou: ' + String(errOut || err.message).trim().split('\n').pop() } : { ok: true, msg: 'Google conectado.' }));
    });
  });
}

module.exports = { ON, PORT, dataDir, configured, startBot, stopBot, restartBot, openSetup, setupIpc };
