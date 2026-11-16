// O'qituvchi paneli / proyektor ekrani uchun Alpine komponenti
function teacherRoom(roomId, kind) {
  const WS_PATH = kind === 'projector' ? 'projector' : 'teacher';
  return {
    snap: {
      room: { status: 'waiting', remaining: 0, total_questions: 0, results_visible: false, code: '', name: '' },
      participants: [], violations: [], late: [], powerups: [], podium: [],
    },
    loaded: false, connected: false, ws: null,
    toasts: [], remaining: 0, _base: 0, _at: 0, _asked: false,
    addMinutes: 5, lateExtra: {}, soundOn: !Sfx.muted, celebrated: false,
    search: '', statusFilter: 'all', panelOpen: true, tab: 'violations',
    ticker: [], _seenPowerups: 0,

    init() {
      this.connect();
      setInterval(() => this.tick(), 250);
      setInterval(() => this.send({ t: 'snapshot' }), 8000);
    },
    connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      this.ws = new WebSocket(`${proto}://${location.host}/ws/${WS_PATH}/${roomId}/`);
      this.ws.onopen = () => { this.connected = true; };
      this.ws.onclose = () => { this.connected = false; setTimeout(() => this.connect(), 2000); };
      this.ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
    },
    send(msg) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(msg)); },

    onMessage(m) {
      if (m.t === 'error') { this.toast({ text: m.message, kind: 'error' }, 5000); return; }
      if (m.t !== 'snapshot') return;
      const prev = this.snap, first = !this.loaded;
      this.loaded = true; this.snap = m;
      this._base = m.room.remaining; this._at = performance.now();
      if (m.alert && m.alert.text) {
        this.toast(m.alert, 0);
        if (this.soundOn) Sfx.play('alert');
      }
      // hal qilingan so'rovlarning toast'larini olib tashlash
      const pendV = new Set(m.violations.filter(v => v.decision === 'pending').map(v => v.id));
      const pendL = new Set(m.late.map(l => l.pid));
      this.toasts = this.toasts.filter(t => (t.kind === 'violation' ? pendV.has(t.id) : (t.kind === 'late' ? pendL.has(t.pid) : true)));
      if (!first && m.participants.length > prev.participants.length && this.soundOn) Sfx.play('join');
      // super-kuch hodisalari lentasi (proyektor uchun)
      if (m.powerups.length > this._seenPowerups) {
        m.powerups.slice(0, m.powerups.length - this._seenPowerups).reverse().forEach(l => {
          if (!first) this.ticker.unshift({ id: Math.random(), text: `${l.type === 'steal' ? '💰' : '❄️'} ${l.attacker} → ${l.victim}` + (l.type === 'steal' ? ` (−${l.amount})` : `, ${l.seconds} s`) });
        });
        this.ticker = this.ticker.slice(0, 5);
        setTimeout(() => { this.ticker = this.ticker.slice(0, -1); }, 12000);
        if (!first && this.soundOn) Sfx.play('coin');
      }
      this._seenPowerups = m.powerups.length;
      if (m.room.status === 'finished' && !this.celebrated) {
        this.celebrated = true;
        if (!first) { if (this.soundOn) Sfx.play('win'); }
        FX.confetti(true);
      }
    },
    toast(t, ttl) {
      const item = { ...t, uid: Date.now() + Math.random() };
      this.toasts.push(item);
      if (ttl) setTimeout(() => { this.toasts = this.toasts.filter(x => x.uid !== item.uid); }, ttl);
    },
    dismiss(t) { this.toasts = this.toasts.filter(x => x.uid !== t.uid); },

    tick() {
      const r = this.snap.room;
      if (r.status === 'running') {
        this.remaining = Math.max(0, this._base - (performance.now() - this._at) / 1000);
        if (this.remaining <= 0 && !this._asked) { this._asked = true; setTimeout(() => { this.send({ t: 'snapshot' }); this._asked = false; }, 1500); }
      } else this.remaining = r.remaining;
    },
    fmt(s) {
      s = Math.floor(s);
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
      return (h ? h + ':' : '') + String(m).padStart(h ? 2 : 1, '0') + ':' + String(x).padStart(2, '0');
    },
    get status() { return this.snap.room.status; },
    get pending() { return this.snap.violations.filter(v => v.decision === 'pending'); },
    get waitingList() { return this.snap.participants.filter(p => !['pending', 'kicked'].includes(p.status)); },
    get counts() {
      const c = { total: 0, active: 0, finished: 0, answered: 0, possible: 0 };
      this.snap.participants.forEach(p => {
        if (['pending', 'kicked'].includes(p.status)) return;
        c.total++;
        if (p.status === 'active') c.active++;
        if (p.status === 'finished') c.finished++;
        c.answered += p.answered; c.possible += this.snap.room.total_questions;
      });
      return c;
    },
    get progressPct() { const d = this.snap.room.duration || 0; return d ? Math.min(100, Math.max(0, Math.round((d - this.remaining) * 100 / d))) : 0; },
    cardState(p) {
      if (p.status === 'kicked') return 'kicked';
      if (p.locked) return 'locked';
      if (p.frozen) return 'frozen';
      return p.status;
    },
    get filtered() {
      const q = this.search.trim().toLowerCase();
      return this.snap.participants.filter(p => {
        if (p.status === 'pending') return false;
        if (q && !(p.name.toLowerCase().includes(q) || p.school_class.toLowerCase().includes(q))) return false;
        const s = this.cardState(p);
        return this.statusFilter === 'all' || s === this.statusFilter || (this.statusFilter === 'kicked' && s === 'locked');
      });
    },
    statusLabel(s) {
      return { waiting: 'Kutmoqda', active: 'Faol', finished: 'Tugatdi', kicked: 'Chetlatilgan', locked: 'Qulflangan', frozen: 'Muzlatilgan', pending: 'Ruxsat kutmoqda' }[s] || s;
    },
    cardClass(p) {
      return {
        active: 'border-ok bg-ok/5', frozen: 'border-ice bg-ice/15', locked: 'border-bad bg-bad/10 alert-red',
        kicked: 'border-bad bg-bad/10 opacity-70', waiting: 'border-sun bg-sun/10', finished: 'border-line bg-line/40',
      }[this.cardState(p)] || 'border-line';
    },

    start() { this.send({ t: 'start' }); },
    pause() { this.send({ t: 'pause' }); },
    resume() { this.send({ t: 'resume' }); },
    finish() { if (confirm('Test hamma uchun darhol yakunlansinmi?')) this.send({ t: 'finish' }); },
    addTime(min) { this.send({ t: 'add_time', minutes: min }); },
    kick(p) { if (confirm(`${p.name} xonadan chiqarilsinmi?`)) this.send({ t: 'kick', pid: p.id }); },
    decideViolation(id, d) { this.send({ t: 'violation', id, decision: d }); },
    decideLate(pid, allow) { this.send({ t: 'late', pid, allow, extra: (parseInt(this.lateExtra[pid]) || 0) * 60 }); },
    extraTime(p) {
      const m = parseInt(prompt(`${p.name} uchun necha daqiqa qo'shimcha vaqt?`, '2'));
      if (m > 0) this.send({ t: 'extra_time', pid: p.id, seconds: m * 60 });
    },
    setResultsVisible(v) { this.send({ t: 'results_visible', value: v }); },
    toggleSound() { this.soundOn = !this.soundOn; Sfx.setMuted(!this.soundOn); Sfx.unlock(); },
  };
}
