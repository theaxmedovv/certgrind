// Effektlar: konfetti, tangalar, uchuvchi "snaryad"
window.FX = {
  confetti(strong) {
    if (typeof confetti !== 'function' || window.REDUCED) return;
    const colors = ['#6C3BFF', '#FFC83D', '#22C55E', '#FF4D6D', '#38BDF8'];
    const end = Date.now() + (strong ? 4500 : 1200);
    (function frame() {
      confetti({ particleCount: strong ? 7 : 3, angle: 60, spread: 70, origin: { x: 0, y: .8 }, colors });
      confetti({ particleCount: strong ? 7 : 3, angle: 120, spread: 70, origin: { x: 1, y: .8 }, colors });
      if (Date.now() < end) requestAnimationFrame(frame);
    })();
  },
  light() { this.confetti(false); },
  coins(n) {
    if (window.REDUCED) return;
    for (let i = 0; i < (n || 14); i++) {
      const el = document.createElement('div');
      el.className = 'coin';
      el.textContent = '🪙';
      el.style.left = (10 + Math.random() * 80) + 'vw';
      el.style.top = (50 + Math.random() * 40) + 'vh';
      el.style.setProperty('--dx', (Math.random() * 200 - 100) + 'px');
      el.style.animationDelay = (Math.random() * .5) + 's';
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 2200);
    }
  },
  // from -> to elementlari orasida emoji uchirish (tanga / muz parchasi)
  fly(emoji, fromEl, toEl) {
    if (window.REDUCED || !fromEl || !toEl || !window.gsap) return;
    const a = fromEl.getBoundingClientRect(), b = toEl.getBoundingClientRect();
    const el = document.createElement('div');
    el.textContent = emoji;
    el.style.cssText = `position:fixed;z-index:130;font-size:2.4rem;pointer-events:none;left:${a.left + a.width / 2}px;top:${a.top + a.height / 2}px`;
    document.body.appendChild(el);
    gsap.to(el, { x: b.left - a.left, y: b.top - a.top, rotation: 540, scale: 1.4, duration: .7, ease: 'power2.in', onComplete: () => el.remove() });
  },
};
