// Gera o ícone do app (icon.png 512 e icon.ico 16–256): o mesmo anel de energia vazado da pílula (drawOrb em island/core.js).
// Rodar com: npm run icon (dentro de orbit/) ou npm --prefix orbit run icon (da raiz)
const { app, BrowserWindow } = require('electron');
const fs = require('fs'), path = require('path');
const SIZES = [16, 24, 32, 48, 64, 128, 256, 512];

// Roda dentro da página: desenha o anel em cada tamanho e devolve PNGs em base64.
function render(sizes) {
  const cs = [[0x2f, 0x7b, 0xff], [0x9b, 0x5c, 0xff], [0xff, 0x6f, 0xb5]]; // cores padrão da Orbit
  const mix = (a, b, k) => a.map((v, i) => Math.round(v + (b[i] - v) * k));
  const C = (k) => (k < 0.5 ? mix(cs[0], cs[1], k * 2) : mix(cs[1], cs[2], (k - 0.5) * 2));
  return sizes.map((S) => {
    const cv = document.createElement('canvas'); cv.width = cv.height = S;
    const g = cv.getContext('2d'); g.scale(S / 64, S / 64);
    const c = 32, small = S < 48;
    // fundo: disco escuro, para o anel aparecer em barra de tarefas clara ou escura
    g.fillStyle = '#0d0d0f'; g.beginPath(); g.arc(c, c, 31.5, 0, 7); g.fill();
    const R = 21, cg = g.createConicGradient(-0.6, c, c);
    [0, 0.33, 0.66, 1].forEach((s, i) => cg.addColorStop(s, `rgb(${C([0, 0.5, 1, 0][i])})`));
    const hg = g.createRadialGradient(c, c, R * 0.7, c, c, R * 1.5);
    hg.addColorStop(0, 'rgba(0,0,0,0)'); hg.addColorStop(0.35, `rgba(${C(0.4)},0.32)`); hg.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = hg; g.fillRect(0, 0, 64, 64);
    g.globalCompositeOperation = 'lighter'; g.strokeStyle = cg;
    if (small) { // em 16–32 px os fios viram borrão: só o anel, mais grosso
      g.globalAlpha = 0.3; g.lineWidth = 11; g.beginPath(); g.arc(c, c, R, 0, 7); g.stroke();
      g.globalAlpha = 1; g.lineWidth = 6; g.stroke();
    } else {
      const t = 2.2, energy = 0.75;
      for (let s = 0; s < 9; s++) {
        const ph = s * 0.7, sp = 0.5 + s * 0.13; g.beginPath();
        for (let i = 0; i <= 128; i++) {
          const a = i / 128 * Math.PI * 2;
          const off = (Math.sin(a * 2 + t * sp + ph) * 1.6 + Math.sin(a * 3 - t * sp * 0.8 + ph * 2) * 1.1 + Math.sin(a * 5 + t * 1.3 + s)) * energy;
          const r = R + off * (s % 3 === 0 ? 0.4 : 1);
          const x = c + Math.cos(a) * r, y = c + Math.sin(a) * r; i ? g.lineTo(x, y) : g.moveTo(x, y);
        }
        g.globalAlpha = s === 0 ? 0.85 : 0.18; g.lineWidth = s === 0 ? 2 : 1.1; g.stroke();
      }
      g.globalAlpha = 0.14; g.lineWidth = 7; g.beginPath(); g.arc(c, c, R, 0, 7); g.stroke();
      g.globalAlpha = 0.3; g.lineWidth = 3; g.stroke();
    }
    return cv.toDataURL('image/png').split(',')[1];
  });
}

// ICO com PNGs embutidos (aceito pelo Windows desde o Vista).
function ico(pngs) {
  const head = Buffer.alloc(6 + 16 * pngs.length); head.writeUInt16LE(1, 2); head.writeUInt16LE(pngs.length, 4);
  let off = head.length;
  pngs.forEach(({ size, buf }, i) => {
    const e = 6 + 16 * i; head[e] = size >= 256 ? 0 : size; head[e + 1] = size >= 256 ? 0 : size;
    head.writeUInt16LE(1, e + 4); head.writeUInt16LE(32, e + 6); head.writeUInt32LE(buf.length, e + 8); head.writeUInt32LE(off, e + 12);
    off += buf.length;
  });
  return Buffer.concat([head, ...pngs.map((p) => p.buf)]);
}

app.whenReady().then(async () => {
  const w = new BrowserWindow({ show: false });
  await w.loadURL('data:text/html,<body></body>');
  const out = await w.webContents.executeJavaScript(`(${render})(${JSON.stringify(SIZES)})`);
  const pngs = SIZES.map((size, i) => ({ size, buf: Buffer.from(out[i], 'base64') }));
  fs.writeFileSync(path.join(__dirname, 'icon.png'), pngs.find((p) => p.size === 512).buf);
  fs.writeFileSync(path.join(__dirname, 'icon.ico'), ico(pngs.filter((p) => p.size <= 256)));
  console.log('icon.png + icon.ico', SIZES.join(','));
  app.quit();
});
