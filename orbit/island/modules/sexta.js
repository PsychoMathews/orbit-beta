// Assistente: falar (mesmo fluxo do Ctrl+Alt+F), digitar perguntas, mudo e a última conversa.
Orbit.register({
  id: 'sexta',
  mount(view) {
    view.innerHTML = `
      <div class="col" style="height:100%">
        <div class="row">
          <div class="card hero row" style="flex:1;padding:10px 14px;gap:12px">
            <span class="ring idle" id="sx-orb" style="width:30px;height:30px"></span>
            <div style="min-width:0">
              <div class="title tint-text" id="sx-state">Pronta</div>
              <div class="faint" id="sx-sub">Clique no microfone ou aperte Ctrl+Alt+F</div>
            </div>
          </div>
          <button class="btn round primary tint" id="sx-talk" title="Falar">${icon('mic', 18)}</button>
          <button class="btn round" id="sx-mute" title="Mudo">${icon('micOff', 18)}</button>
        </div>
        <div class="card" style="flex:1;min-height:0;overflow-y:auto" id="sx-log">
          <div class="empty" style="padding:18px 0">Pergunte qualquer coisa: agenda, e-mails, o PC, um timer…</div>
        </div>
        <form class="row" id="sx-form">
          <input class="input" id="sx-input" placeholder="Pergunte %à%…" autocomplete="off" spellcheck="false">
          <button class="btn round primary tint" title="Enviar">${icon('send', 17)}</button>
        </form>
      </div>`;
    this.$ = (s) => view.querySelector(s);
    this.$('#sx-talk').onclick = () => api.post('/orbit/trigger');
    this.$('#sx-mute').onclick = () => api.post('/orbit/mute');
    const input = this.$('#sx-input');
    input.addEventListener('mousedown', () => api.focus(true));
    input.addEventListener('blur', () => api.focus(false));
    this.$('#sx-form').onsubmit = (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      this.add('you', text);
      api.post('/orbit/ask', { text, speak: Orbit.cfg.friday.speakTyped });
    };
    this.log = [];
    this.render();
  },
  add(who, text) {
    this.log.push({ who, text, t: Date.now() });
    this.log = this.log.slice(-12);
    if (!this.$) return;
    const box = this.$('#sx-log');
    box.innerHTML = this.log.map((m) => `
      <div style="margin:2px 0 10px">
        <div class="faint">${m.who === 'you' ? 'Você' : '%nome%'} · ${hhmm(m.t)}</div>
        <div style="${m.who === 'you' ? 'color:var(--dim)' : ''};white-space:pre-wrap;user-select:text">${esc(m.text)}</div>
      </div>`).join('');
    box.scrollTop = box.scrollHeight;
  },
  // Aba escondida não tem altura: rolar lá não vale. Ao abrir a aba, desce até a última mensagem.
  show() { requestAnimationFrame(() => { const b = this.$ && this.$('#sx-log'); if (b) b.scrollTop = b.scrollHeight; }); },
  render() {
    if (!this.$) return;
    const f = Orbit.friday;
    const orbClass = !f.online ? 'offline' : f.muted && f.state === 'idle' ? 'muted' : f.state;
    this.$('#sx-orb').className = 'ring ' + orbClass;
    const titles = { idle: f.muted ? 'No mudo' : 'Pronta', listening: 'Ouvindo…', thinking: 'Pensando…', speaking: 'Falando' };
    this.$('#sx-state').textContent = f.online ? titles[f.state] : 'Fora do ar';
    this.$('#sx-sub').textContent = !f.online ? 'O bot não está rodando; o vigia reinicia em até 5 min'
      : f.muted ? 'Atalho e voz no PC desligados. Telegram e Alexa seguem normais.' : 'Clique no microfone ou aperte Ctrl+Alt+F';
    this.$('#sx-mute').classList.toggle('on', f.muted);
    this.$('#sx-talk').disabled = f.muted || Orbit.game.on;
    if (Orbit.game.on) { this.$('#sx-state').textContent = 'Modo jogo'; this.$('#sx-sub').textContent = 'Não escuto nem falo pelo PC até o modo jogo desligar.'; }
  },
  onFriday(ev) {
    if (ev.type === 'heard') this.add('you', ev.text);
    if (ev.type === 'reply') this.add('ai', ev.text);
    this.render();
  },
});
