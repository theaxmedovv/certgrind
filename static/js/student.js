// O'quvchi ilovasi (Alpine). Barcha mantiq serverda; bu yerda faqat ko'rsatish va animatsiya.
// Python kodini qator-qator ranglaydi (highlight.js bo'lsa); kutubxona yuklanmasa oddiy matn.
function highlightCode(code) {
  if (!code) return [];
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return code.replace(/\s+$/, '').split('\n').map((ln) => {
    if (!ln) return '&nbsp;';
    try { if (window.hljs) return window.hljs.highlight(ln, { language: 'python', ignoreIllegals: true }).value; } catch (_) {}
    return esc(ln);
  });
}

function student() {
  const LS_QUEUE = 'queue';
  const SHAPES = ['▲', '◆', '●', '■', '★', '⬢'];
  return {
    SHAPES,
    token: localStorage.getItem('pt'),
    ws: null, connected: false, everConnected: false, fatal: '', banner: '', _bannerT: null,
    st: null, screen: 'loading',
    q: null, pending: null, selected: null,
    result: null, pointsShown: 0,
    intervalLeft: 0, intervalTotal: 3, _intervalTimer: null, _intervalStart: 0, intervalDue: false,
    shownTop: [], prevTop: [],
    codes: [],
    picker: null, reel: { person: null, number: null, locked: false, numLocked: false, label: '' }, _reelId: null, pickerMsg: '', giftOpened: false,
    powerMsg: '', _flashT: null,
    notice: null, _noticeT: null, scoreFlash: false,
    remaining: 0, _remBase: 0, _remAt: 0, _running: false, _lastTick: -1, _syncAsked: false,
    frozenLeft: 0, _frozenUntil: 0, iceShown: false, iceBreaking: false, freezeBy: '',
    cd: null, cdText: '',
    lockedOnce: false,
    factIdx: 0,
    music: Sfx.pref('music', true),
    muted: Sfx.muted,
    finStage: 'none', podiumStep: 0, podiumDone: false, celebrated: false,
    reviewFilter: 'all', codeLines: [], roundBanner: 0, _lastRound: 0, _roundT: null,
    guardOn: false, _reconnectDelay: 1000,

    init() {
      if (!this.token) { location.href = '/'; return; }
      window.__guard = this;
      this.connect();
      setInterval(() => this.tick(), 250);
      setInterval(() => this.send({ t: 'ping' }), 20000);
      setInterval(() => (this.factIdx = (this.factIdx + 1) % FACTS.length), 6000);
      window.addEventListener('online', () => { if (!this.connected) this.connect(); });
      window.addEventListener('keydown', (e) => this.onKey(e));
      // brauzer ovozni faqat birinchi bosishdan keyin ruxsat beradi
      const unlock = () => { Sfx.unlock(); if (this.music && !this.muted) Sfx.music(true); window.removeEventListener('pointerdown', unlock); };
      window.addEventListener('pointerdown', unlock);
    },

    // ---------- ulanish
    connect() {
      if (this.ws && this.ws.readyState <= 1) return;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${location.host}/ws/student/?t=${encodeURIComponent(this.token)}`);
      this.ws = ws;
      ws.onopen = () => {
        const wasLost = this.everConnected && !this.connected;
        this.connected = true; this.everConnected = true; this._reconnectDelay = 1000;
        if (wasLost) { this.banner = 'back'; clearTimeout(this._bannerT); this._bannerT = setTimeout(() => (this.banner = ''), 2200); }
        this.flushQueue();
        this.send({ t: 'sync' });
      };
      ws.onclose = (e) => {
        this.connected = false;
        if (e.code === 4403) {
          this.fatal = "Bu qurilmadan yoki brauzerdan kirib bo'lmaydi. Sessiya faqat birinchi kirgan brauzerda ishlaydi.";
          if (!this.everConnected) localStorage.removeItem('pt');
          return;
        }
        if (e.code === 4409) { this.fatal = "Sen boshqa oynada ochding. Bu oyna yopildi."; return; }
        if (this.everConnected) this.banner = 'lost';
        setTimeout(() => this.connect(), this._reconnectDelay);
        this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, 8000);
      };
      ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
    },
    send(msg) {
      if (this.ws && this.ws.readyState === 1) { this.ws.send(JSON.stringify(msg)); return true; }
      return false;
    },
    queue() { try { return JSON.parse(localStorage.getItem(LS_QUEUE) || '[]'); } catch (_) { return []; } },
    saveQueue(q) { try { localStorage.setItem(LS_QUEUE, JSON.stringify(q)); } catch (_) {} },
    enqueue(m) { const q = this.queue(); q.push(m); this.saveQueue(q); },
    dequeue(uuid) { this.saveQueue(this.queue().filter((m) => m.uuid !== uuid)); },
    flushQueue() {
      this.queue().forEach((m) => this.send(m));
      const v = localStorage.getItem('viol');
      if (v && this.send({ t: 'violation', type: v })) localStorage.removeItem('viol');
    },

    // ---------- xabarlar
    onMessage(m) {
      switch (m.t) {
        case 'state': this.applyState(m); break;
        case 'question': this.showQuestion(m); break;
        case 'answer_result': this.onResult(m); break;
        case 'powerup_result': this.onPowerupResult(m); break;
        case 'notice': this.onNotice(m); break;
        case 'error': this.onError(m); break;
        case 'pong': this.onPong(m); break;
      }
    },
    onPong(m) {
      // server bilan vaqtni qayta tekislash; holat o'zgargan bo'lsa to'liq sinxronlash
      if (!this.st) return;
      if (m.status !== this.st.room.status) { this.send({ t: 'sync' }); return; }
      if (this._running) { this._remBase = m.remaining; this._remAt = performance.now(); }
    },
    applyState(s) {
      this.st = s;
      this._remBase = s.room.remaining; this._remAt = performance.now();
      this._running = s.room.status === 'running' || (s.room.status === 'finished' && s.room.remaining > 0 && s.phase === 'question');
      this.remaining = s.room.remaining;
      if (s.codes) this.codes = s.codes;
      this._frozenUntil = s.frozen_left > 0 ? performance.now() + s.frozen_left * 1000 : 0;
      this.frozenLeft = s.frozen_left;
      if (s.frozen_left > 0) this.iceShown = true;
      if (this.screen === 'countdown') return;
      if (this.screen === 'interval' && s.phase === 'question') return;
      switch (s.phase) {
        case 'pending': this.setScreen('pending'); break;
        case 'lobby': this.setScreen('lobby'); break;
        case 'ready': this.setScreen('ready'); break;
        case 'paused': this.setScreen('paused'); break;
        case 'locked': this.lockedOnce = true; this.setScreen('locked'); break;
        case 'frozen': this.setScreen('frozen'); break;
        case 'kicked': this.setScreen('kicked'); break;
        case 'rejected': this.setScreen('rejected'); break;
        case 'finished': this.setScreen('finished'); this.onFinished(); break;
        case 'question':
          if (!this.isFullscreen()) { this.setScreen('needfs'); }
          else if (this.screen !== 'question' || !this.q) { this.setScreen('question'); this.send({ t: 'next' }); }
          break;
      }
    },
    setScreen(name) {
      if (name !== 'question' && name !== 'interval') this.q = null;
      this.screen = name;
      this.guardOn = name === 'question' || name === 'interval';
    },
    onError(m) {
      if (m.uuid) {
        this.dequeue(m.uuid);
        if (this.pending && this.pending.uuid === m.uuid) { this.pending = null; this.selected = null; }
      }
      if (['frozen', 'locked', 'paused'].includes(m.code)) return;
      if (this.picker) { this.pickerMsg = m.message; this._reelId = null; this.picker = { stage: 'gift', kind: null }; this.giftOpened = true; return; }
      this.flash(m.message);
    },
    flash(text) {
      this.powerMsg = text;
      clearTimeout(this._flashT);
      this._flashT = setTimeout(() => (this.powerMsg = ''), 3500);
    },
    onKey(e) {
      if (this.screen !== 'question' || !this.q || this.pending) return;
      const n = parseInt(e.key, 10);
      if (n >= 1 && n <= this.q.options.length) { e.preventDefault(); this.choose(this.q.options[n - 1]); }
    },

    // ---------- fullscreen va start
    isFullscreen() { return !!(document.fullscreenElement || document.webkitFullscreenElement); },
    async enterFullscreen() {
      const el = document.documentElement;
      try {
        if (el.requestFullscreen) await el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
        else { this.flash("Brauzering to'liq ekranni qo'llamaydi (iPhone'da ishlamaydi). Kompyuter, planshet yoki Android'dan foydalan."); return false; }
      } catch (e) { this.flash("To'liq ekranga o'tib bo'lmadi, qayta urinib ko'r"); return false; }
      return true;
    },
    async startTest() {
      Sfx.unlock();
      if (!(await this.enterFullscreen())) return;
      this.setScreen('countdown');
      const steps = [['3', 'beep'], ['2', 'beep'], ['1', 'beep'], ['BOSHLADIK!', 'go']];
      for (const [txt, snd] of steps) {
        this.cdText = txt; this.cd = txt + Math.random();
        Sfx.play(snd);
        await new Promise((r) => setTimeout(r, txt === 'BOSHLADIK!' ? 700 : 900));
      }
      this.cd = null;
      this.screen = 'loading';
      this.send({ t: 'begin' });
    },
    async resumeAfterLock() {
      Sfx.unlock();
      if (!(await this.enterFullscreen())) return;
      this.lockedOnce = false;
      this.setScreen('question');
      this.send({ t: 'next' });
    },

    // ---------- qoidabuzarlik
    violate(type) {
      if (!this.guardOn) return;
      this.guardOn = false;
      this.q = null;
      this.screen = 'locked'; this.lockedOnce = true;
      clearTimeout(this._intervalTimer);
      if (!this.send({ t: 'violation', type })) { try { localStorage.setItem('viol', type); } catch (_) {} }
      setTimeout(() => this.send({ t: 'sync' }), 800);
    },

    // ---------- savol va javob
    showQuestion(m) {
      if (this.screen === 'interval') return;
      this.q = m; this.selected = null; this.pending = null;
      this.codeLines = highlightCode(m.code);
      if (m.round > 1 && m.round > this._lastRound && this._lastRound > 0) this.showRoundBanner(m.round);
      this._lastRound = m.round || 1;
      this.setScreen('question');
    },
    showRoundBanner(n) {
      this.roundBanner = n; Sfx.play('go');
      clearTimeout(this._roundT);
      this._roundT = setTimeout(() => (this.roundBanner = 0), 2200);
    },
    uuid() {
      if (crypto.randomUUID) return crypto.randomUUID();
      return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, (c) => (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16));
    },
    choose(opt) {
      if (this.pending || !this.q || this.screen !== 'question') return;
      const msg = { t: 'answer', position: this.q.position, option_id: opt.id, uuid: this.uuid() };
      this.selected = opt.id; this.pending = msg;
      Sfx.play('select');
      this.enqueue(msg);
      this.send(msg);
    },
    onResult(m) {
      this.dequeue(m.uuid);
      const mine = this.pending && this.pending.uuid === m.uuid;
      if (this.st) { this.st.me.score = m.score; this.st.me.streak = m.streak; }
      this.codes = m.codes;
      if (!mine && this.screen !== 'interval') { this.send({ t: 'sync' }); return; }
      this.pending = null;
      this.result = m;
      this.q = null;
      this.setScreen('interval');
      this.intervalTotal = m.interval; this.intervalLeft = m.interval; this.intervalDue = false;
      // ball sanab ko'tariladi
      this.pointsShown = 0;
      setTimeout(() => (this.pointsShown = m.points), 350);
      // reyting: avval eski tartib, keyin yangisiga silliq siljish
      this.shownTop = this.prevTop.length ? this.prevTop : m.top5;
      setTimeout(() => (this.shownTop = m.top5), 600);
      this.prevTop = m.top5;
      Sfx.play(m.correct ? 'correct' : 'wrong');
      if (m.correct) FX.light();
      if (m.new_code) setTimeout(() => { Sfx.play('streak'); FX.confetti(false); }, 700);
      clearTimeout(this._intervalTimer);
      this._intervalStart = performance.now();
      this._intervalTimer = setTimeout(() => this.intervalEnd(), m.interval * 1000);
    },
    intervalEnd() {
      if (this.picker) { this.intervalDue = true; return; }
      this.intervalDue = false;
      if (this.result && this.result.finished) { this.send({ t: 'sync' }); return; }
      this.screen = 'question'; this.q = null; this.result = null;
      this.send({ t: 'next' });
    },
    get meInTop() { return this.result && this.shownTop.some((p) => this.st && p.id === this.st.me.id); },
    get streakShown() { return this.result ? (this.result.new_code ? this.result.streak_target : this.result.streak) : 0; },
    get encourage() {
      const t = ['Hechqisi yo\'q, keyingisi seniki! 💪', 'Xato — o\'rganish yo\'li! Davom et 🚀', 'Yaxshi urinish! Keyingisini uzamiz 🌟', 'Tinchlan, hali hammasi oldinda! 😉'];
      return t[(this.result ? this.result.position : 0) % t.length];
    },

    // ---------- super-kuchlar
    get flags() { return this.result ? this.result.powerups : (this.st ? this.st.powerups : { steal: false, freeze: false }); },
    openGift() {
      if (!this.codes.length) return;
      this.picker = { stage: 'gift', kind: null }; this.giftOpened = false; this.pickerMsg = '';
      Sfx.play('gift');
      setTimeout(() => (this.giftOpened = true), 700);
    },
    chooseCard(kind) {
      if (!this.codes.length || this.picker.stage === 'wait') return;
      // nishonni SERVER tanlaydi; biz faqat turini yuboramiz va natijani animatsiya qilamiz
      this.picker = { stage: 'wait', kind }; this.pickerMsg = '';
      this.reel = { person: null, number: null, locked: false, numLocked: false, label: '' };
      Sfx.play('select');
      this.send({ t: 'powerup', code: this.codes[0], kind });
    },
    closePicker() {
      this._reelId = null;
      this.picker = null;
      if (this.intervalDue) this.intervalEnd();
    },
    onPowerupResult(m) {
      this.codes = m.codes;
      if (this.result) { this.result.codes = m.codes; this.result.score = m.score; }
      if (this.st) this.st.me.score = m.score;
      this.runReel(m);
    },
    // "Baraban": avatarlar tez aylanadi, sekinlashib nishonda to'xtaydi, so'ng raqam aylanib to'xtaydi
    async runReel(m) {
      const id = (this._reelId = Math.random());
      const alive = () => this._reelId === id && this.picker;
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const reduced = typeof REDUCED !== 'undefined' && REDUCED;
      this.picker = { stage: 'reel', kind: m.kind };
      this.reel = { person: null, number: null, locked: false, numLocked: false, label: m.kind === 'steal' ? 'ball' : 'soniya' };
      const people = m.reel && m.reel.length ? m.reel : [m.target];
      if (!reduced) {
        let delay = 55;
        for (let i = 0; i < 24 && alive(); i++) {
          this.reel.person = people[i % people.length];
          Sfx.play('tick');
          await sleep(delay); delay *= 1.13;
        }
      }
      if (!alive()) return;
      this.reel.person = m.target; this.reel.locked = true; Sfx.play('select');
      await sleep(reduced ? 200 : 650);
      const final = m.kind === 'steal' ? m.amount : m.seconds;
      if (!reduced) {
        const [lo, hi] = m.range || [1, 20];
        const top = m.kind === 'steal' ? Math.max(final * 2, 60) : hi;
        const low = m.kind === 'steal' ? 1 : lo;
        let delay = 50;
        for (let i = 0; i < 16 && alive(); i++) {
          this.reel.number = low + Math.floor(Math.random() * (top - low + 1));
          Sfx.play('tick');
          await sleep(delay); delay *= 1.15;
        }
      }
      if (!alive()) return;
      this.reel.number = final; this.reel.numLocked = true;
      const from = document.getElementById('reel-target');
      if (m.kind === 'steal') { Sfx.play('steal'); FX.coins(12); this.flash(`💰 ${m.target.name} dan ${m.amount} ball oldingiz!`); }
      else { Sfx.play('freeze'); this.flash(`❄️ ${m.target.name} ${m.seconds} soniyaga muzlatildi!`); }
      await sleep(reduced ? 600 : 1500);
      if (this._reelId === id) this.closePicker();
    },
    onNotice(m) {
      this.notice = m;
      clearTimeout(this._noticeT);
      this._noticeT = setTimeout(() => (this.notice = null), 4500);
      if (m.kind === 'steal') {
        Sfx.play('steal'); FX.coins(14);
        this.scoreFlash = false; this.$nextTick(() => (this.scoreFlash = true));
        setTimeout(() => (this.scoreFlash = false), 1200);
      }
      if (m.kind === 'freeze') { Sfx.play('freeze'); this.iceShown = true; }
    },

    // ---------- taymer
    get timerState() { return this.remaining <= 10 ? 'danger' : (this.remaining <= 60 ? 'warn' : 'ok'); },
    tick() {
      if (!this.st) return;
      this.remaining = this._running ? Math.max(0, this._remBase - (performance.now() - this._remAt) / 1000) : this._remBase;
      if (this._running && this.remaining <= 10 && this.remaining > 0) {
        const s = Math.ceil(this.remaining);
        if (s !== this._lastTick) { this._lastTick = s; Sfx.play(s <= 3 ? 'alarm' : 'tick'); }
      }
      if (this._running && this.remaining <= 0 && !this._syncAsked) {
        this._syncAsked = true; this.send({ t: 'sync' });
        setTimeout(() => (this._syncAsked = false), 2000);
      }
      if (this._frozenUntil) {
        this.frozenLeft = Math.max(0, (this._frozenUntil - performance.now()) / 1000);
        if (this.frozenLeft <= 0) { this._frozenUntil = 0; this.send({ t: 'sync' }); }
      }
      if (this.iceShown && this.frozenLeft <= 0 && !this.iceBreaking) {
        this.iceBreaking = true; Sfx.play('unfreeze');
        setTimeout(() => { this.iceShown = false; this.iceBreaking = false; }, 700);
      }
      if (this.screen === 'interval' && this._intervalStart) {
        this.intervalLeft = Math.max(0, this.intervalTotal - (performance.now() - this._intervalStart) / 1000);
      }
    },
    fmt(s) { s = Math.floor(s); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); },

    // ---------- yakun: sarlavha -> baraban -> podium -> natija kartasi
    async onFinished() {
      this.guardOn = false;
      if (document.fullscreenElement) { try { document.exitFullscreen(); } catch (_) {} }
      const s = this.st;
      if (s.room_finished && s.podium && s.podium.length && !this.podiumDone) {
        this.podiumDone = true;
        await this.runPodium();
      } else if (this.finStage === 'none') {
        this.finStage = 'title';
        Sfx.play('win');
        setTimeout(() => { if (this.finStage === 'title') this.finStage = 'card'; }, 1800);
      }
    },
    async runPodium() {
      const wait = (ms) => new Promise((r) => setTimeout(r, ms));
      this.finStage = 'title'; this.podiumStep = 0;
      Sfx.play('drum');
      await wait(window.REDUCED ? 300 : 2000);
      this.finStage = 'podium';
      for (let step = 1; step <= 3; step++) {
        this.podiumStep = step;
        Sfx.play(step === 3 ? 'crown' : 'coin');
        if (step === 3) { Sfx.play('win'); FX.confetti(true); }
        await wait(window.REDUCED ? 200 : 1400);
      }
      await wait(window.REDUCED ? 200 : 2200);
      this.finStage = 'card';
    },
    podiumPerson(rank) { return (this.st.podium || []).find((p) => p.rank === rank); },
    get ringDash() { const p = this.st && this.st.result ? this.st.result.percent : 0; return `${(p / 100) * 251.3} 251.3`; },
    get badges() {
      const r = this.st && this.st.result; if (!r) return [];
      const b = [];
      if (r.rank && r.rank <= 3 && this.st.room_finished) b.push({ i: ['🥇', '🥈', '🥉'][r.rank - 1], t: r.rank + '-o\'rin' });
      if (r.total && r.correct === r.total) b.push({ i: '💯', t: 'Mukammal' });
      if (r.codes) b.push({ i: '🎁', t: 'Maxfiy kod ×' + r.codes });
      if (r.percent >= 70) b.push({ i: '🔥', t: 'Bilimdon' });
      if (!b.length) b.push({ i: '🌱', t: 'Birinchi qadam' });
      return b;
    },
    get reviewItems() {
      const all = (this.st && this.st.review) || [];
      return this.reviewFilter === 'wrong' ? all.filter((r) => !r.is_correct) : all;
    },
    saveCard() {
      const r = this.st.result, me = this.st.me;
      const c = document.createElement('canvas'); c.width = 800; c.height = 1000;
      const g = c.getContext('2d');
      const grad = g.createLinearGradient(0, 0, 800, 1000);
      grad.addColorStop(0, '#2a0a6b'); grad.addColorStop(1, '#6c3bff');
      g.fillStyle = grad; g.fillRect(0, 0, 800, 1000);
      g.fillStyle = '#ffc83d'; g.font = '800 54px Baloo 2, Nunito, sans-serif'; g.textAlign = 'center';
      g.fillText('🧠 Bilimdon', 400, 100);
      const draw = (img) => {
        if (img) { g.save(); g.beginPath(); g.arc(400, 260, 110, 0, 7); g.clip(); g.drawImage(img, 290, 150, 220, 220); g.restore(); }
        g.fillStyle = '#fff'; g.font = '800 56px Baloo 2, Nunito, sans-serif';
        g.fillText(me.name, 400, 440);
        g.font = '700 30px Nunito, sans-serif'; g.fillStyle = '#d9ccff';
        g.fillText(me.school_class + ' · ' + this.st.room.name, 400, 485);
        const box = (x, label, val) => {
          g.fillStyle = 'rgba(255,255,255,.14)'; g.beginPath(); g.roundRect(x, 560, 220, 170, 28); g.fill();
          g.fillStyle = '#d9ccff'; g.font = '700 26px Nunito, sans-serif'; g.fillText(label, x + 110, 605);
          g.fillStyle = '#ffc83d'; g.font = '800 78px Baloo 2, Nunito, sans-serif'; g.fillText(String(val), x + 110, 695);
        };
        box(60, "O'rin", r.rank || '—'); box(290, 'Ball', r.score); box(520, 'Baho', r.grade);
        g.fillStyle = '#fff'; g.font = '800 40px Baloo 2, Nunito, sans-serif';
        g.fillText(`To'g'ri javoblar: ${r.correct}/${r.total} (${r.percent}%)`, 400, 830);
        g.font = '700 28px Nunito, sans-serif'; g.fillStyle = '#d9ccff';
        g.fillText(this.badges.map((b) => b.i + ' ' + b.t).join('   '), 400, 900);
        c.toBlob((blob) => {
          const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
          a.download = 'natija.png'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        });
      };
      const img = new Image();
      img.onload = () => draw(img); img.onerror = () => draw(null);
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(Avatar.svg(me.avatar, ''));
    },
    toggleMusic() { this.music = !this.music; Sfx.setPref('music', this.music); if (this.muted) this.toggleMute(); Sfx.unlock(); Sfx.music(this.music); },
    toggleMute() { this.muted = Sfx.toggleMute(); if (!this.muted && this.music) Sfx.music(true); },
    leave() { localStorage.removeItem('pt'); localStorage.removeItem('queue'); location.href = '/'; },
  };
}
