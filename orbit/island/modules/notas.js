// Notas e listas: moram na assistente (hub.py), então ela lê, escreve e responde sobre elas
// ("qual a lista de compras do mês?", "anota leite na lista de compras"). Cada assunto é uma nota (título + texto).
Orbit.register({
  id: 'notas',
  lists: {},
  current: null,
  notes: [],
  note: null, // id da nota aberta
  async refresh() {
    const [l, n] = await Promise.all([api.get('/orbit/lists'), api.get('/orbit/notes')]);
    if (l) { this.lists = l.lists; this.renderLists(); }
    if (n) { this.notes = n.notes.filter((x) => !x.archived); this.renderNotes(); }
  },
  onEvent(ev) {
    if (ev.type === 'lists') { this.lists = ev.lists; this.renderLists(); }
    if (ev.type === 'notes' && ev.source !== 'ilha') { this.notes = ev.notes.filter((x) => !x.archived); this.renderNotes(); }
    if (ev.type === 'hello' || ev.type === 'online') this.refresh();
  },
  mount(view) {
    view.innerHTML = `
      <div class="row" style="height:100%;align-items:stretch;gap:10px">
        <div class="col" style="flex:0 0 46%;min-width:0">
          <div class="row" id="nt-tabs" style="flex-wrap:wrap;gap:6px"></div>
          <div class="list" id="nt-items" style="flex:1;overflow-y:auto;min-height:0"></div>
          <form class="row" id="nt-form">
            <input class="input" id="nt-new" placeholder="Adicionar item…" spellcheck="false">
            <button class="btn round primary tint" title="Adicionar">${icon('plus', 17)}</button>
          </form>
        </div>
        <div class="col" style="flex:1;min-width:0">
          <div class="row" id="nn-tabs" style="flex-wrap:nowrap;gap:6px;overflow-x:auto;scrollbar-width:none"></div>
          <div class="row" style="gap:6px">
            <input class="input" id="nn-title" placeholder="Título" spellcheck="false" style="font-weight:600">
            <button class="btn round danger" id="nn-del" title="Apagar esta nota">${icon('trash', 15)}</button>
          </div>
          <textarea class="input" id="nt" placeholder="Escreva aqui. %A% lê suas notas quando você pede." spellcheck="false" style="flex:1"></textarea>
        </div>
      </div>`;
    this.$ = (s) => view.querySelector(s);
    this.ta = this.$('#nt');
    for (const i of view.querySelectorAll('input, textarea')) { i.addEventListener('mousedown', () => api.focus(true)); i.addEventListener('blur', () => api.focus(false)); }
    this.titleIn = this.$('#nn-title');
    let t = null;
    const save = () => { clearTimeout(t); t = setTimeout(() => this.saveNote(), 500); };
    this.ta.oninput = save; this.titleIn.oninput = save;
    this.$('#nn-del').onclick = () => {
      const n = this.notes.find((x) => x.id === this.note); if (!n) return;
      if (this.$('#nn-del').dataset.armed !== '1') { // segundo clique confirma (sem caixa de diálogo)
        this.$('#nn-del').dataset.armed = '1'; this.$('#nn-del').title = 'Clique de novo para apagar';
        this.$('#nn-del').classList.add('on'); setTimeout(() => { this.$('#nn-del').dataset.armed = ''; this.$('#nn-del').classList.remove('on'); }, 2500);
        return;
      }
      this.notes = this.notes.filter((x) => x.id !== n.id); this.note = this.notes[0]?.id || null;
      api.post('/orbit/notes/delete', { id: n.id }); this.renderNotes();
    };
    this.$('#nt-form').onsubmit = (e) => {
      e.preventDefault();
      const input = this.$('#nt-new'), v = input.value.trim();
      if (!v) return;
      input.value = '';
      if (this.naming || !this.current) {
        this.naming = false; this.current = v; this.lists[v] = this.lists[v] || [];
        input.placeholder = 'Adicionar item…';
        this.renderLists();
        return;
      }
      api.post('/orbit/lists/add', { list: this.current, items: [v] });
    };
    this.$('#nt-items').addEventListener('click', (e) => {
      const b = e.target.closest('[data-item]');
      // Risca (círculo enche, traço passa pelo texto), recolhe a linha e só então tira da lista.
      if (b && !b.classList.contains('done')) {
        b.style.maxHeight = b.offsetHeight + 'px';
        b.classList.add('done');
        const list = this.current, item = b.dataset.item;
        setTimeout(() => b.classList.add('gone'), 420);
        setTimeout(() => api.post('/orbit/lists/remove', { list, items: [item] }), 720);
      }
    });
    this.refresh();
  },
  show() { this.refresh(); },
  async saveNote() {
    const title = this.titleIn.value.trim(), text = this.ta.value;
    if (!this.note && !title && !text.trim()) return;
    const r = await api.post('/orbit/notes', { id: this.note || '', title: title || 'Sem título', text });
    if (r?.note) {
      const i = this.notes.findIndex((x) => x.id === r.note.id);
      if (i >= 0) this.notes[i] = r.note; else this.notes.unshift(r.note);
      this.note = r.note.id; this.renderTabs();
    }
  },
  renderNotes() {
    if (!this.$) return;
    if (!this.notes.some((n) => n.id === this.note) && !this.drafting) this.note = this.notes[0]?.id || null;
    const n = this.notes.find((x) => x.id === this.note);
    const typing = document.activeElement === this.ta || document.activeElement === this.titleIn;
    if (!typing) { this.titleIn.value = n ? n.title : ''; this.ta.value = n ? n.text : ''; }
    this.renderTabs();
  },
  renderTabs() {
    const tabs = this.$('#nn-tabs');
    tabs.innerHTML = `<button class="tab" data-newnote title="Nova nota">${icon('plus', 15)}</button>`
      + this.notes.map((n) => `<button class="tab ${n.id === this.note ? 'on' : ''}" data-note="${n.id}" title="${esc(n.title)}"><span class="lbl ellipsis" style="display:inline-block;max-width:150px">${esc(n.title || 'Sem título')}</span></button>`).join('');
    tabs.onwheel = (e) => { if (e.deltaY) { tabs.scrollLeft += e.deltaY; e.preventDefault(); } }; // roda do mouse rola as notas
    tabs.querySelectorAll('[data-note]').forEach((b) => { b.onclick = () => { this.drafting = false; this.note = b.dataset.note; this.ta.blur(); this.titleIn.blur(); this.renderNotes(); }; });
    tabs.querySelector('[data-newnote]').onclick = () => {
      this.drafting = true; this.note = null; this.titleIn.value = ''; this.ta.value = '';
      this.renderTabs(); api.focus(true); this.titleIn.focus();
    };
    tabs.querySelector('.on')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  },
  renderLists() {
    if (!this.$) return;
    const names = Object.keys(this.lists);
    if (!names.includes(this.current)) this.current = names[0] || null;
    const tabs = this.$('#nt-tabs');
    tabs.innerHTML = names.map((n) => `<button class="tab ${n === this.current ? 'on' : ''}" data-list="${esc(n)}"><span class="lbl" style="display:inline">${esc(n)}</span><span class="chip">${this.lists[n].length}</span></button>`).join('')
      + `<button class="tab" data-new title="Nova lista">${icon('plus', 15)}</button>`;
    tabs.querySelectorAll('[data-list]').forEach((b) => { b.onclick = () => { this.current = b.dataset.list; this.renderLists(); }; });
    tabs.querySelector('[data-new]').onclick = () => {
      this.naming = true;
      const input = this.$('#nt-new');
      input.placeholder = 'Nome da nova lista (Enter)…';
      api.focus(true); input.focus();
    };
    if (!this.current && !this.naming) this.$('#nt-new').placeholder = 'Nome da primeira lista (Enter)…';
    const items = this.current ? this.lists[this.current] || [] : [];
    this.$('#nt-items').innerHTML = items.map((i) => `
      <div class="item click" data-item="${esc(i)}" title="Clique para riscar (tirar da lista)">
        <span class="chk">${icon('check', 11)}</span>
        <span class="ellipsis strike" style="flex:1">${esc(i)}</span></div>`).join('')
      || `<div class="empty" style="padding:16px 0">${this.current ? 'Lista vazia.' : 'Nenhuma lista. Diga: “anota arroz na lista de compras”.'}</div>`;
  },
});
