// Ko'chirishga qarshi himoya (mijoz tomoni). Asosiy tekshiruvlar serverda.
(function () {
  const report = (type) => { if (window.__guard) window.__guard.violate(type); };
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); return false; };

  ['contextmenu', 'copy', 'cut', 'paste', 'selectstart', 'dragstart', 'beforeprint'].forEach((ev) =>
    document.addEventListener(ev, (e) => {
      if (e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
      stop(e);
    }, true));

  document.addEventListener('keydown', (e) => {
    const k = (e.key || '').toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    if (e.key === 'F12') { stop(e); report('devtools'); return; }
    if (ctrl && e.shiftKey && ['i', 'j', 'c', 'k'].includes(k)) { stop(e); report('devtools'); return; }
    if (ctrl && ['c', 'x', 'v', 'p', 's', 'u', 'a'].includes(k)) { stop(e); return; }
  }, true);

  document.addEventListener('keyup', (e) => {
    if (e.key === 'PrintScreen' || e.code === 'PrintScreen') {
      try { navigator.clipboard.writeText(''); } catch (_) {}
      report('printscreen');
    }
  }, true);

  // DevTools (ulangan oyna) o'lchamlar farqi bo'yicha aniqlash
  setInterval(() => {
    const dw = window.outerWidth - window.innerWidth, dh = window.outerHeight - window.innerHeight;
    if (dw > 200 || dh > 200) report('devtools');
  }, 1500);

  document.addEventListener('visibilitychange', () => { if (document.hidden) report('tab_switch'); });
  window.addEventListener('blur', () => report('tab_switch'));
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) report('fullscreen_exit'); });
  document.addEventListener('webkitfullscreenchange', () => { if (!document.webkitFullscreenElement) report('fullscreen_exit'); });
})();
