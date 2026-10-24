// Prints: os últimos da pasta Capturas de Tela, prontos para arrastar (Claude, chat, pasta) ou copiar como imagem.
Orbit.register({
  id: 'prints',
  shots: [],
  async start() { try { this.shots = (await api.shots()) || []; } catch (e) { console.error(e); } },
  onEvent(ev) {
    if (ev.type !== 'shots') return;
    this.shots = ev.shots;
    this.render();
    if (ev.fresh) this.announce(ev.fresh);
  },
  // Print novo: aviso curto com a miniatura, que já dá para arrastar dali mesmo.
  announce(f) {
    Orbit.banner('Print salvo', 'Arraste a miniatura ou copie a imagem.', '', 6000);
    const box = document.getElementById('b-actions');
    if (Orbit.confirming) return;
    box.innerHTML = `<img class="shot-mini" src="${f.thumb}" draggable="true" title="Arraste para soltar em outro lugar">
      <button class="btn" data-s="copy">Copiar</button><button class="btn" data-s="tab">Ver prints</button>`;
    box.querySelector('img').ondragstart = (e) => { e.preventDefault(); api.fileDrag(f.path); };
    box.onclick = (e) => {
      const b = e.target.closest('[data-s]'); if (!b) return; e.stopPropagation();
      if (b.dataset.s === 'copy') { api.shotCopy(f.path); Orbit.banner('Copiado', 'Cole com Ctrl+V.', '', 1800); }
      else Orbit.open('prints');
    };
  },
  mount(view) {
    this.view = view;
    view.innerHTML = `<div class="row" style="margin-bottom:8px">
      <span class="faint" style="flex:1">Arraste um print para soltar no Claude, num chat ou numa pasta. Clique para abrir.</span>
      <button class="btn" style="height:28px" data-folder>Abrir pasta</button></div><div class="shots" data-body></div>`;
    this.body = view.querySelector('[data-body]');
    view.querySelector('[data-folder]').onclick = () => api.shotFolder();
    this.render();
  },
  show() { api.shots().then((s) => { if (s) { this.shots = s; this.render(); } }); },
  render() {
    if (!this.body) return;
    if (!this.shots.length) {
      this.body.innerHTML = '<div class="empty" style="grid-column:1/-1">Nenhum print ainda. Tire um com Win+Shift+S ou PrtScn.</div>';
      return;
    }
    this.body.innerHTML = this.shots.map((f, i) => `<div class="shot" draggable="true" data-i="${i}" title="${esc(f.name)}">
      <img src="${f.thumb}" alt="">
      <span class="shot-bar"><span class="faint">${hhmm(f.t)}</span><span style="flex:1"></span>
        <button class="btn round" data-copy title="Copiar imagem">${icon('copy', 13)}</button>
        <button class="btn round" data-show title="Mostrar na pasta">${icon('folder', 13)}</button></span></div>`).join('');
    this.body.querySelectorAll('.shot').forEach((el) => {
      const f = this.shots[+el.dataset.i];
      el.onclick = (e) => {
        if (e.target.closest('[data-copy]')) { api.shotCopy(f.path); Orbit.banner('Copiado', 'Cole com Ctrl+V.', '', 1800); return; }
        if (e.target.closest('[data-show]')) { api.fileShow(f.path); return; }
        api.fileOpen(f.path);
      };
      el.ondragstart = (e) => { e.preventDefault(); api.fileDrag(f.path); };
    });
  },
});
