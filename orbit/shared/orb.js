// Orbe da assistente: uma linha principal brilhante (quase branca no miolo) e fios finos que se soltam dela
// numa região que gira devagar, ondulando como energia; tudo com brilho suave. Usado pela ilha do PC (core.js)
// e pelo app do celular (fundo), para os dois serem o mesmo orbe.
(function (root) {
  const TAU = Math.PI * 2;
  // Saliência suave em volta do ângulo `at` (onde os fios se soltam da linha principal).
  const bump = (a, at, w) => { const d = Math.atan2(Math.sin(a - at), Math.cos(a - at)); return Math.exp(-(d / w) * (d / w)); };

  /**
   * g: contexto 2D. o: { cx, cy, R, t (segundos), energy (0.6 parado .. 2 falando alto), colors: [c1, c2, c3],
   *   blur: pixels de tela por unidade do desenho (o brilho do canvas não acompanha a escala), alpha: 0..1 }
   */
  function draw(g, o) {
    const { cx, cy, R, t, colors } = o, e = o.energy ?? 1, k = o.blur ?? 1, A = o.alpha ?? 1;
    const grad = g.createConicGradient(t * 0.25, cx, cy);
    [colors[0], colors[1], colors[2], colors[0]].forEach((c, i) => grad.addColorStop(i / 3, c));
    const b1 = t * 0.35, b2 = 2.1 - t * 0.22;
    const env = (a) => bump(a, b1, 1.0) + 0.6 * bump(a, b2, 0.75);
    const ring = (dev, n = 140) => {
      g.beginPath();
      for (let i = 0; i <= n; i++) {
        const a = i / n * TAU, r = R + dev(a);
        i ? g.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r) : g.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
      }
    };
    g.save();
    g.globalCompositeOperation = 'lighter';
    g.strokeStyle = grad; g.shadowColor = colors[1]; g.lineCap = 'round';

    // Fios: saem da linha principal onde a saliência passa e ondulam; no resto do anel ficam colados nela.
    for (let s = 0; s < 6; s++) {
      const ph = s * 1.3, sp = 0.6 + s * 0.17, amp = R * (0.06 + s * 0.028) * (0.55 + 0.5 * e); // visíveis mesmo parado
      ring((a) => env(a) * amp * (Math.sin(a * 2 + t * sp + ph) * 0.65 + Math.sin(a * 3 - t * sp * 0.7 + ph * 2) * 0.35)
        + Math.sin(a * 9 + t * 2.6 + s) * R * 0.004 * e);
      g.globalAlpha = A * (0.55 - s * 0.05); g.lineWidth = R * 0.022; g.shadowBlur = R * 0.12 * k; g.stroke();
    }
    // Linha principal: quase redonda, com um leve tremor de energia.
    const main = (a) => env(a) * R * 0.018 * e * Math.sin(a * 3 + t * 1.4) + Math.sin(a * 7 - t * 2) * R * 0.004 * e;
    ring(main);
    g.globalAlpha = A * 0.35; g.lineWidth = R * 0.16; g.shadowBlur = R * 0.6 * k; g.stroke();   // halo
    g.globalAlpha = A * 0.95; g.lineWidth = R * 0.07; g.shadowBlur = R * 0.25 * k; g.stroke();  // cor
    g.strokeStyle = '#fff'; g.globalAlpha = A * 0.55; g.lineWidth = R * 0.03; g.shadowBlur = 0; g.stroke(); // miolo branco
    g.restore();
  }

  root.ORBIT_ORB = { draw };
})(this);
