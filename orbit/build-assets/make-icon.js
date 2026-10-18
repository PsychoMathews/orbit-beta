// Gera o ícone do instalador (256x256): o mesmo anel com ponto da bandeja, sem arquivo de imagem de terceiros.
const fs = require('fs'), zlib = require('zlib'), path = require('path');
const S = 256, c = (S - 1) / 2, rOut = S * 0.46, rIn = S * 0.34, rDot = S * 0.14;
const raw = Buffer.alloc((S * 4 + 1) * S);
for (let y = 0; y < S; y++) {
  raw[y * (S * 4 + 1)] = 0;
  for (let x = 0; x < S; x++) {
    const d = Math.hypot(x - c, y - c), cl = (v) => Math.max(0, Math.min(1, v));
    const ring = cl(rOut - d + 0.5) * cl(d - rIn + 0.5), dot = cl(rDot - d + 0.5), bg = cl(S * 0.5 - d + 0.5);
    const i = y * (S * 4 + 1) + 1 + x * 4, t = x / S;
    if (ring > 0 || dot > 0) { raw[i] = 47 + 160 * t; raw[i + 1] = 123 - 30 * t; raw[i + 2] = 255; raw[i + 3] = 255 * Math.max(ring, dot); }
    else { raw[i] = 13; raw[i + 1] = 13; raw[i + 2] = 15; raw[i + 3] = 255 * bg; }
  }
}
const crc = (b) => { let c = ~0; for (const x of b) { c ^= x; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1)); } return ~c >>> 0; };
const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const k = Buffer.alloc(4); k.writeUInt32BE(crc(td)); return Buffer.concat([l, td, k]); };
const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(S, 0); ihdr.writeUInt32BE(S, 4); ihdr[8] = 8; ihdr[9] = 6;
const png = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
fs.writeFileSync(path.join(__dirname, 'icon.png'), png);
console.log('icon.png', png.length);
