// Ovozlar: Web Audio API orqali sintez qilingan (fayl kerak emas). Umumiy balandlik va o'chirish bor.
window.Sfx = (function () {
  let ctx = null, master = null, musicOn = false, musicTimer = null;
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} },
  };
  let muted = store.get('sfx_muted', false);
  let volume = store.get('sfx_volume', 0.7);

  function ac() {
    if (!ctx) {
      try {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        master = ctx.createGain(); master.gain.value = muted ? 0 : volume; master.connect(ctx.destination);
      } catch (e) {}
    }
    if (ctx && ctx.state === 'suspended') ctx.resume();
    return ctx;
  }
  function tone(freq, dur, type, vol, when, slideTo) {
    const c = ac(); if (!c || muted) return;
    const t = c.currentTime + (when || 0);
    const o = c.createOscillator(), g = c.createGain();
    o.type = type || 'sine'; o.frequency.setValueAtTime(freq, t);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
    g.gain.setValueAtTime(vol || 0.15, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g); g.connect(master); o.start(t); o.stop(t + dur + 0.03);
  }
  function noise(dur, vol, when, hp) {
    const c = ac(); if (!c || muted) return;
    const t = c.currentTime + (when || 0);
    const buf = c.createBuffer(1, Math.max(1, c.sampleRate * dur), c.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / d.length);
    const s = c.createBufferSource(); s.buffer = buf;
    const f = c.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = hp || 800;
    const g = c.createGain(); g.gain.value = vol || .2;
    s.connect(f); f.connect(g); g.connect(master); s.start(t);
  }
  const S = {
    click() { tone(520, .06, 'triangle', .12); },
    select() { tone(700, .08, 'triangle', .16); tone(990, .1, 'triangle', .14, .06); },
    correct() { tone(523, .12, 'triangle', .22); tone(659, .12, 'triangle', .22, .1); tone(784, .28, 'triangle', .24, .2); },
    wrong() { tone(220, .25, 'sawtooth', .13); tone(160, .4, 'sawtooth', .13, .2); },
    streak() { [523, 659, 784, 1047, 1319].forEach((f, i) => tone(f, .14, 'square', .1, i * .08)); noise(.4, .08, .3, 3000); },
    gift() { tone(300, .08, 'square', .1); tone(450, .08, 'square', .1, .08); tone(900, .35, 'triangle', .2, .18); tone(1350, .35, 'sine', .15, .22); },
    freeze() { tone(1500, .6, 'sine', .15, 0, 300); tone(900, .5, 'triangle', .1, .1, 200); noise(.5, .1, 0, 4000); },
    unfreeze() { noise(.35, .18, 0, 2500); tone(1200, .2, 'triangle', .1, .05, 2400); },
    coin() { tone(988, .08, 'square', .1); tone(1319, .25, 'square', .1, .08); },
    steal() { for (let i = 0; i < 6; i++) tone(900 + i * 140, .08, 'square', .09, i * .06); },
    tick() { tone(880, .05, 'square', .07); },
    alarm() { tone(988, .1, 'square', .1); tone(740, .1, 'square', .1, .14); },
    beep() { tone(660, .18, 'sine', .25); },
    go() { tone(990, .5, 'triangle', .3); tone(1320, .5, 'sine', .2, .05); },
    drum() { for (let i = 0; i < 22; i++) { noise(.08, .12 + i * .008, i * .075, 200); tone(110, .08, 'sine', .25, i * .075); } },
    crown() { tone(784, .15, 'triangle', .25); tone(1047, .15, 'triangle', .25, .12); tone(1568, .5, 'triangle', .28, .24); },
    alert() { tone(880, .15, 'sine', .3); tone(1175, .2, 'sine', .3, .18); tone(880, .15, 'sine', .3, .4); tone(1175, .25, 'sine', .3, .58); },
    join() { tone(660, .08, 'sine', .15); tone(880, .12, 'sine', .15, .08); },
    powerup() { S.streak(); },
    win() { [523, 659, 784, 1047, 784, 1047, 1319, 1568].forEach((f, i) => tone(f, .24, 'triangle', .24, i * .16)); },
  };
  const melody = [262, 330, 392, 330, 294, 370, 440, 370, 262, 330, 392, 523, 440, 392, 330, 294];
  function musicLoop() {
    if (!musicOn) return;
    melody.forEach((f, i) => tone(f, .3, 'sine', .028, i * .32));
    musicTimer = setTimeout(musicLoop, melody.length * 320);
  }
  return {
    play(n) { try { S[n] && S[n](); } catch (e) {} },
    unlock() { ac(); },
    music(on) { musicOn = on; clearTimeout(musicTimer); if (on) { ac(); musicLoop(); } },
    isMusic() { return musicOn; },
    get muted() { return muted; },
    get volume() { return volume; },
    setMuted(v) { muted = !!v; store.set('sfx_muted', muted); if (master) master.gain.value = muted ? 0 : volume; if (muted) this.music(false); },
    toggleMute() { this.setMuted(!muted); return muted; },
    setVolume(v) { volume = Math.min(1, Math.max(0, v)); store.set('sfx_volume', volume); if (master && !muted) master.gain.value = volume; },
    pref(k, d) { return store.get(k, d); },
    setPref(k, v) { store.set(k, v); },
  };
})();
