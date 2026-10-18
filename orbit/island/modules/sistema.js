// Sistema: CPU, GPU (nvidia-smi), memória, temperatura e disco, com histórico. Só mede com a aba aberta.
Orbit.register({
  id: 'sistema',
  hist: { cpu: [], gpu: [], mem: [], rx: [], tx: [] },
  mount(view) {
    const card = (id, name, color) => `
      <div class="card hero" style="--tint:${color}"><div class="row"><span class="faint" style="flex:1">${name}</span><b id="sy-${id}">–</b></div>
      <div class="faint ellipsis" id="sy-${id}-sub" style="margin-top:2px">&nbsp;</div>
      <canvas class="spark" id="sy-${id}-c" data-color="${color}"></canvas></div>`;
    view.innerHTML = `
      <div class="grid3">${card('cpu', 'CPU', '#4fd1ff')}${card('gpu', 'GPU', '#4ade80')}${card('mem', 'Memória', '#b18cff')}</div>
      <div class="grid2" style="margin-top:8px">
        <div class="card"><div class="row"><span class="faint" style="flex:1">Disco C:</span><b id="sy-disk">–</b></div>
          <div class="bar" style="margin-top:10px"><i id="sy-disk-bar" style="width:0"></i></div></div>
        <div class="card"><div class="row"><span class="faint" style="flex:1">Temperatura GPU</span><b id="sy-temp">–</b></div>
          <div class="faint" id="sy-up" style="margin-top:8px"></div></div>
      </div>
      <div class="card hero" style="--tint:#38bdf8;margin-top:8px">
        <div class="row"><span class="faint" style="flex:1">Rede <span id="sy-ip"></span></span>
          <span class="faint">↓ <b id="sy-rx" style="color:var(--fg)">–</b> &nbsp; ↑ <b id="sy-tx" style="color:var(--fg)">–</b></span></div>
        <canvas class="spark" id="sy-net-c" data-color="#38bdf8"></canvas>
        <div class="row" style="margin-top:8px;gap:14px">
          <button class="btn primary tint" style="height:30px" id="sy-speed">Testar velocidade</button>
          <span class="faint">Ping <b id="sp-ping" style="color:var(--fg)">–</b></span>
          <span class="faint">Download <b id="sp-down" style="color:var(--fg)">–</b></span>
          <span class="faint">Upload <b id="sp-up" style="color:var(--fg)">–</b></span>
          <span class="faint" id="sp-when" style="flex:1;text-align:right;font-size:11px"></span>
        </div>
      </div>`;
    const mbps = (v) => (v == null ? '–' : (v >= 100 ? v.toFixed(0) : v.toFixed(1)) + ' Mb/s');
    const showSpeed = (p) => {
      this.$('#sp-ping').textContent = p.ping != null ? p.ping + ' ms' : '–';
      this.$('#sp-down').textContent = mbps(p.down); this.$('#sp-up').textContent = mbps(p.up);
      const b = this.$('#sy-speed');
      b.disabled = p.phase !== 'done';
      b.innerHTML = p.phase === 'done' ? 'Testar de novo' : `<i class="spin"></i> ${p.phase === 'up' ? 'Enviando…' : 'Baixando…'}`;
      if (p.phase === 'done') { this.$('#sp-when').textContent = 'speed.cloudflare.com · ' + hhmm(p.t) + (p.link && /^100 Mbps/.test(p.link.LinkSpeed) && p.down > 80 ? ' · limitado pelo cabo (100 Mbps)' : ''); try { localStorage.setItem('orbit.speed', JSON.stringify(p)); } catch {} }
    };
    api.onSpeed(showSpeed);
    try { const last = JSON.parse(localStorage.getItem('orbit.speed') || 'null'); if (last) setTimeout(() => showSpeed(last)); } catch {}
    view.querySelector('#sy-speed').onclick = () => { showSpeed({ phase: 'down' }); api.speedTest(); };
    this.$ = (s) => view.querySelector(s);
  },
  show() { this.poll(); this.timer = setInterval(() => this.poll(), 1500); },
  hide() { clearInterval(this.timer); },
  async poll() {
    const s = await api.system();
    if (!s || !this.$) return;
    const push = (k, v) => { this.hist[k].push(v); if (this.hist[k].length > 60) this.hist[k].shift(); };
    const memPct = Math.round(100 * s.memUsed / s.memTotal);
    push('cpu', s.cpu); push('mem', memPct); push('gpu', s.gpu ? s.gpu.util : 0);
    if (s.net) {
      const rate = (v) => bytes(v || 0) + '/s';
      this.$('#sy-rx').textContent = rate(s.net.rx); this.$('#sy-tx').textContent = rate(s.net.tx);
      const L = s.net.link;
      this.$('#sy-ip').innerHTML = (s.net.ip ? '· IP local ' + s.net.ip : '') + (L?.LinkSpeed ? ` · cabo a <b style="color:${/^100 Mbps|^10 Mbps/.test(L.LinkSpeed) ? 'var(--warn)' : 'var(--fg)'}" title="${/^100 Mbps/.test(L.LinkSpeed) ? 'A placa está conectada a 100 Mbps: a internet não passa disso. Um cabo Cat5e ou Cat6 (e porta gigabit no roteador) libera 1 Gbps.' : 'Velocidade da conexão da placa de rede'}">${esc(L.LinkSpeed)}</b>` : '');
      this.hist.rx.push(s.net.rx || 0); if (this.hist.rx.length > 60) this.hist.rx.shift();
      const max = Math.max(1, ...this.hist.rx);
      const c = this.$('#sy-net-c'); sparkline(c, this.hist.rx.map((v) => (100 * v) / max), c.dataset.color);
    }
    this.$('#sy-cpu').textContent = s.cpu + '%';
    this.$('#sy-cpu-sub').textContent = `${s.cpuName.replace(/\(R\)|\(TM\)|CPU|Processor/g, '').replace(/\s+/g, ' ')}`;
    this.$('#sy-mem').textContent = memPct + '%';
    this.$('#sy-mem-sub').textContent = `${bytes(s.memUsed)} de ${bytes(s.memTotal)}`;
    if (s.gpu) {
      this.$('#sy-gpu').textContent = s.gpu.util + '%';
      this.$('#sy-gpu-sub').textContent = `${s.gpu.name.replace('NVIDIA GeForce ', '')} · VRAM ${(s.gpu.memUsed / 1024).toFixed(1)}/${(s.gpu.memTotal / 1024).toFixed(0)} GB`;
      const t = s.gpu.temp;
      this.$('#sy-temp').textContent = t + ' °C';
      this.$('#sy-temp').style.color = t >= 83 ? 'var(--bad)' : t >= 72 ? 'var(--warn)' : '';
    }
    if (s.disk) {
      const used = 1 - s.disk.free / s.disk.total;
      this.$('#sy-disk').textContent = `${bytes(s.disk.free)} livres`;
      this.$('#sy-disk-bar').style.width = (used * 100).toFixed(1) + '%';
      this.$('#sy-disk-bar').style.background = used > 0.9 ? 'var(--bad)' : '';
    }
    const h = Math.floor(s.uptime / 3600);
    this.$('#sy-up').textContent = `Ligado há ${h >= 24 ? Math.floor(h / 24) + ' d ' : ''}${h % 24} h`;
    for (const k of ['cpu', 'gpu', 'mem']) { const c = this.$(`#sy-${k}-c`); sparkline(c, this.hist[k], c.dataset.color); }
  },
});
