// Prepara o pacote da beta (chamado por "npm run dist" na pasta orbit).
//   node tools/preparar_beta.js             -> copia o código do bot para build/core e confere o Python portátil
//   node tools/preparar_beta.js --verificar -> confere o programa gerado (nada pessoal pode ter ido junto)
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const BUILD = path.join(ROOT, 'build');
const PY = path.join(BUILD, 'python');

function fail(msg) { console.error('\n✗ ' + msg + '\n'); process.exit(1); }

if (process.argv.includes('--verificar')) {
  const app = path.join(BUILD, 'dist', 'win-unpacked', 'resources');
  if (!fs.existsSync(app)) fail('Não achei build/dist/win-unpacked: o electron-builder rodou?');
  try {
    execFileSync(path.join(PY, 'python.exe'), ['-I', path.join(ROOT, 'tools', 'verificar_vazamento.py'), app], { stdio: 'inherit' });
  } catch { fail('A verificação achou algo pessoal no pacote. NÃO distribua este instalador.'); }
  console.log('\n✓ Pacote conferido: nada pessoal encontrado.');
  process.exit(0);
}

// 1) Python portátil com as dependências (montado uma vez; ver PLANO-BETA.md, Fase 4).
if (!fs.existsSync(path.join(PY, 'pythonw.exe'))) fail('Falta build/python (Python portátil). Veja PLANO-BETA.md, Fase 4.');
for (const mod of ['telegram', 'faster_whisper', 'edge_tts', 'keyboard', 'pycaw', 'aiohttp']) {
  if (!fs.existsSync(path.join(PY, 'Lib', 'site-packages', mod))) fail(`O Python portátil está sem o pacote ${mod}. Rode o pip de novo.`);
}

// 2) ffmpeg (a voz precisa): vem do pacote imageio-ffmpeg, copiado com o nome que o bot procura.
const ff = path.join(PY, 'ffmpeg.exe');
if (!fs.existsSync(ff)) {
  const dir = path.join(PY, 'Lib', 'site-packages', 'imageio_ffmpeg', 'binaries');
  const exe = fs.existsSync(dir) && fs.readdirSync(dir).find((f) => /^ffmpeg.*\.exe$/i.test(f));
  if (!exe) fail('Não achei o ffmpeg do imageio-ffmpeg no Python portátil.');
  fs.copyFileSync(path.join(dir, exe), ff);
}
// A cópia original do imageio-ffmpeg não é usada: sai do pacote (84 MB a menos).
fs.rmSync(path.join(PY, 'Lib', 'site-packages', 'imageio_ffmpeg', 'binaries'), { recursive: true, force: true });

// 3) Código do bot: só os .py da pasta friday (nada de memoria/, .env, credenciais ou caches).
const core = path.join(BUILD, 'core', 'friday');
fs.rmSync(path.join(BUILD, 'core'), { recursive: true, force: true });
fs.mkdirSync(core, { recursive: true });
for (const f of fs.readdirSync(path.join(ROOT, 'friday'))) {
  if (f.endsWith('.py')) fs.copyFileSync(path.join(ROOT, 'friday', f), path.join(core, f));
}
fs.copyFileSync(path.join(ROOT, 'requirements.txt'), path.join(BUILD, 'core', 'requirements.txt'));
console.log('✓ build/core e build/python prontos.');
