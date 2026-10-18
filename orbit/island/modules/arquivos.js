// Arquivos: downloads (em andamento e recentes) e a Prateleira (arraste arquivos, textos ou links para a ilha e solte depois).
function ext(name) { const m = /\.([a-z0-9]{1,5})$/i.exec(name || ''); return m ? m[1].toUpperCase() : ''; }
function ago(t) {
  const m = Math.round((Date.now() - t) / 6e4);
  return m < 1 ? 'agora' : m < 60 ? `há ${m} min` : m < 1440 ? `há ${Math.round(m / 60)} h` : new Date(t).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}

Orbit.register({
  id: 'arquivos',
  dl: { active: [], recent: [] },
  shelf: [],
  tab: 'dl',
  async start() {
    this.dropZone(); // primeiro: se algo abaixo falhar, soltar arquivo na ilha não pode virar "abrir o arquivo"
    try { this.dl = (await api.downloads()) || this.dl; } catch (e) { console.error(e); }
    try { this.shelf = (await api.shelf()) || []; } catch (e) { console.error(e); }
    this.render();
  },
  onEvent(ev) {
    if (ev.type === 'downloads') { this.dl = ev; this.render(); }
    if (ev.type === 'shelf') { this.shelf = ev.shelf; this.render(); }
    if (ev.type === 'download_done') {
      this.dl.recent = [ev.file, ...this.dl.recent.filter((r) => r.path !== ev.file.path)];
      chime();
      Orbit.banner('Download concluído', ev.file.name + ' · ' + bytes(ev.file.size), '', 6000);
      const box = document.getElementById('b-actions');
      if (!Orbit.confirming) {
        box.innerHTML = `<button class="btn" data-f="open">Abrir</button><button class="btn" data-f="show">Mostrar na pasta</button>`;
        box.onclick = (e) => { const b = e.target.closest('[data-f]'); if (!b) return; e.stopPropagation(); b.dataset.f === 'open' ? api.fileOpen(ev.file.path) : api.fileShow(ev.file.path); };
      }
      this.render();
    }
  },
  live() {
    const a = this.dl.active;
    if (!a.length) return null;
    const f = a[0];
    return { priority: 1.5, width: 360, left: `<span style="color:#5ee0a0">${icon('download', 16)}</span>`,
      mid: `<span class="t">${esc(f.name)}${a.length > 1 ? ' +' + (a.length - 1) : ''}</span>`,
      right: f.speed > 0 ? bytes(f.speed) + '/s' : bytes(f.size) };
  },
  // Soltar coisas na ilha: abre na aba Arquivos > Prateleira.
  dropZone() {
    const isFiles = (e) => [...(e.dataTransfer?.types || [])].some((t) => t === 'Files' || t === 'text/uri-list' || t === 'text/plain');
    // Sempre cancela o padrão do navegador (abrir a imagem/arquivo na janela da ilha).
    window.addEventListener('dragover', (e) => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; }, true);
    window.addEventListener('drop', (e) => e.preventDefault(), true);
    document.addEventListener('dragenter', (e) => {
      if (!isFiles(e) || !Orbit.enabled('arquivos')) return;
      e.preventDefault();
      this.tab = 'shelf';
      if (Orbit.mode !== 'expanded' || Orbit.tab !== 'arquivos') Orbit.open('arquivos');
      this.view?.classList.add('dropping');
      this.render();
    });
    document.addEventListener('dragleave', (e) => { if (!e.relatedTarget) this.view?.classList.remove('dropping'); });
    document.addEventListener('drop', (e) => {
      e.preventDefault();
      if (!Orbit.enabled('arquivos')) return;
      this.view?.classList.remove('dropping');
      const items = [...e.dataTransfer.files].map((f) => ({ path: api.pathOf(f), name: f.name, size: f.size }));
      if (!items.length) {
        const url = e.dataTransfer.getData('text/uri-list'), text = e.dataTransfer.getData('text/plain');
        if (url || text) items.push(url ? { link: url.split('\n')[0], name: url.split('\n')[0] } : { text, name: text.slice(0, 80) });
      }
      if (items.length) api.shelfAdd(items);
    });
  },
  mount(view) {
    this.view = view;
    view.innerHTML = `<div class="row" style="gap:6px;margin-bottom:8px">
      <button class="ptab" data-at="dl">${icon('download', 13)} Downloads</button>
      <button class="ptab" data-at="shelf">${icon('folder', 13)} Prateleira</button>
      <span style="flex:1"></span><button class="btn" style="height:28px" data-dlfolder>Abrir pasta</button></div><div data-body></div>`;
    this.body = view.querySelector('[data-body]');
    view.querySelectorAll('[data-at]').forEach((b) => b.onclick = () => { this.tab = b.dataset.at; this.render(); });
    view.querySelector('[data-dlfolder]').onclick = () => api.fileShow('');
    this.render();
  },
  show() { api.downloads().then((d) => { if (d) { this.dl = d; this.render(); } }); },
  fileRow(f, i, kind) {
    const isFile = !!f.path, label = f.name || f.text || f.link;
    return `<div class="item click file" draggable="${isFile}" data-i="${i}" data-k="${kind}" title="${isFile ? 'Clique para abrir; arraste para soltar em outro lugar' : 'Clique para copiar'}">
      <span class="fext">${isFile ? esc(ext(f.name) || '•') : f.link ? icon('link', 14) : 'T'}</span>
      <span class="ellipsis" style="flex:1">${esc(label)}</span>
      <span class="faint">${f.size ? bytes(f.size) + ' · ' : ''}${f.t ? ago(f.t) : ''}</span>
      ${isFile ? `<button class="btn round" style="width:28px;height:28px" data-show title="Mostrar na pasta">${icon('folder', 14)}</button>` : ''}
      ${kind === 'shelf' ? `<button class="btn round" style="width:28px;height:28px" data-del title="Tirar da prateleira">${icon('x', 14)}</button>` : ''}
    </div>`;
  },
  render() {
    if (!this.body) return;
    this.view.querySelectorAll('[data-at]').forEach((b) => b.classList.toggle('on', b.dataset.at === this.tab));
    let html = '';
    if (this.tab === 'dl') {
      html += this.dl.active.map((a) => `<div class="card hero" style="margin-bottom:8px"><div class="row">
        <span class="spin" style="color:var(--tint)"></span><span class="ellipsis" style="flex:1"><b>${esc(a.name)}</b></span>
        <span class="faint">${bytes(a.size)}${a.speed > 0 ? ' · ' + bytes(a.speed) + '/s' : ''}</span></div></div>`).join('');
      html += '<div class="list">' + (this.dl.recent.map((f, i) => this.fileRow(f, i, 'dl')).join('') || '<div class="empty">Pasta Downloads vazia.</div>') + '</div>';
    } else {
      html += `<div class="drop">${icon('folder', 18)} Arraste arquivos, textos ou links para a ilha para guardar aqui</div>`;
      html += '<div class="list">' + this.shelf.map((f, i) => this.fileRow(f, i, 'shelf')).join('') + '</div>';
      if (this.shelf.length) html += '<div style="text-align:right;margin-top:8px"><button class="btn danger" style="height:28px" data-clear>Limpar prateleira</button></div>';
    }
    this.body.innerHTML = html;
    const pick = (el) => { const i = +el.dataset.i; return el.dataset.k === 'shelf' ? this.shelf[i] : this.dl.recent[i]; };
    this.body.querySelectorAll('.file').forEach((el) => {
      const f = pick(el);
      el.onclick = (e) => {
        if (e.target.closest('[data-del]')) { api.shelfRemove(+el.dataset.i); return; }
        if (e.target.closest('[data-show]')) { api.fileShow(f.path); return; }
        if (f.path) api.fileOpen(f.path);
        else if (f.link && /^https:\/\//.test(f.link)) api.openUrl(f.link);
        else { api.copy(f.text || f.link); Orbit.banner('Copiado', (f.text || f.link).slice(0, 120), '', 2000); }
      };
      el.ondragstart = (e) => { if (!f.path) return; e.preventDefault(); api.fileDrag(f.path); };
    });
    this.body.querySelector('[data-clear]')?.addEventListener('click', () => api.shelfRemove('all'));
  },
});
