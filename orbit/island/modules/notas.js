// Notas e listas: moram na assistente (hub.py), então ela lê, escreve e responde sobre elas
// ("qual a lista de compras do mês?", "anota leite na lista de compras").
Orbit.register({
  id: 'notas',
  lists: {},
  current: null,
  async refresh() {
    const [l, n] = await Promise.all([api.get('/orbit/lists'), api.get('/orbit/notes')]);
    if (l) { this.lists = l.lists; this.renderLists(); }
    if (n && this.ta && document.activeElement !== this.ta) this.ta.value = n.text;
  },
  onEvent(ev) {
    if (ev.type === 'lists') { this.lists = ev.lists; this.renderLists(); }
    if (ev.type === 'notes' && ev.source !== 'ilha' && this.ta) this.ta.value = ev.text;
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
        <textarea class="input" id="nt" placeholder="Bloco de notas. %A% lê isto quando você pede." spellcheck="false" style="flex:1"></textarea>
      </div>`;
    this.$ = (s) => view.querySelector(s);
    this.ta = this.$('#nt');
    for (const i of view.querySelectorAll('input, textarea')) { i.addEventListener('mousedown', () => api.focus(true)); i.addEventListener('blur', () => api.focus(false)); }
    let t = null;
    this.ta.oninput = () => { clearTimeout(t); t = setTimeout(() => api.post('/orbit/notes', { text: this.ta.value }), 500); };
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
