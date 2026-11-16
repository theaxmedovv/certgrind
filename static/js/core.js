// Umumiy yordamchilar: mavzu (tungi rejim), avatarlar, count-up, Lottie, ikonkalar
(function () {
  const REDUCED = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.REDUCED = REDUCED;

  // ---------- tungi rejim (o'qituvchi paneli)
  window.Theme = {
    isDark() { return document.documentElement.classList.contains('dark'); },
    toggle() {
      const d = !this.isDark();
      document.documentElement.classList.toggle('dark', d);
      try { localStorage.setItem('theme', d ? 'dark' : 'light'); } catch (_) {}
      document.dispatchEvent(new CustomEvent('themechange'));
    },
  };

  // ---------- avatarlar: 24 ta original multfilm SVG (12 qahramon × 2 rang)
  const eyes = (y = 34, dx = 8, r = 5.2) =>
    `<circle cx="${32 - dx}" cy="${y}" r="${r}" fill="#fff"/><circle cx="${32 + dx}" cy="${y}" r="${r}" fill="#fff"/>` +
    `<circle cx="${32 - dx + 1}" cy="${y + .5}" r="${r * .5}" fill="#231942"/><circle cx="${32 + dx + 1}" cy="${y + .5}" r="${r * .5}" fill="#231942"/>` +
    `<circle cx="${32 - dx + 2.3}" cy="${y - 1}" r="1" fill="#fff"/><circle cx="${32 + dx + 2.3}" cy="${y - 1}" r="1" fill="#fff"/>`;
  const smile = (y = 45) => `<path d="M26 ${y} Q32 ${y + 6} 38 ${y}" fill="none" stroke="#231942" stroke-width="2.4" stroke-linecap="round"/>`;
  const cheeks = `<circle cx="19" cy="42" r="3.2" fill="#ff8fab" opacity=".55"/><circle cx="45" cy="42" r="3.2" fill="#ff8fab" opacity=".55"/>`;
  const head = (c, rx = 20, ry = 18) => `<ellipse cx="32" cy="37" rx="${rx}" ry="${ry}" fill="${c}"/>`;

  const TYPES = [
    // 0 mushuk
    (c, d) => `<path d="M13 28 L16 6 L30 19Z M51 28 L48 6 L34 19Z" fill="${c}"/><path d="M17 22 L18 12 L25 19Z M47 22 L46 12 L39 19Z" fill="${d}"/>${head(c)}${eyes()}<path d="M30 40 L34 40 L32 43Z" fill="#ff6b8b"/>${smile(44)}<g stroke="#231942" stroke-width="1.2" opacity=".6"><path d="M10 40 L20 41 M10 46 L20 44 M54 40 L44 41 M54 46 L44 44"/></g>${cheeks}`,
    // 1 ayiq
    (c, d) => `<circle cx="15" cy="17" r="8" fill="${c}"/><circle cx="49" cy="17" r="8" fill="${c}"/><circle cx="15" cy="17" r="4" fill="${d}"/><circle cx="49" cy="17" r="4" fill="${d}"/>${head(c, 21, 19)}<ellipse cx="32" cy="44" rx="10" ry="7.5" fill="${d}"/>${eyes(33)}<ellipse cx="32" cy="41.5" rx="3.4" ry="2.4" fill="#231942"/>${smile(46)}`,
    // 2 quyon
    (c, d) => `<ellipse cx="22" cy="12" rx="6" ry="14" fill="${c}"/><ellipse cx="42" cy="12" rx="6" ry="14" fill="${c}"/><ellipse cx="22" cy="12" rx="2.8" ry="10" fill="${d}"/><ellipse cx="42" cy="12" rx="2.8" ry="10" fill="${d}"/>${head(c)}${eyes(36)}<path d="M30 42 L34 42 L32 44.5Z" fill="#ff6b8b"/>${smile(46)}${cheeks}<rect x="29.5" y="47" width="2.5" height="4" rx="1" fill="#fff"/><rect x="32.5" y="47" width="2.5" height="4" rx="1" fill="#fff"/>`,
    // 3 tulki
    (c, d) => `<path d="M12 30 L15 5 L31 20Z M52 30 L49 5 L33 20Z" fill="${c}"/><path d="M16 22 L17 11 L25 19Z M48 22 L47 11 L39 19Z" fill="#3a2540"/>${head(c)}<path d="M12 40 Q32 62 52 40 Q40 34 32 44 Q24 34 12 40Z" fill="${d}"/>${eyes(34, 8, 4.6)}<ellipse cx="32" cy="43" rx="3" ry="2.2" fill="#231942"/>${smile(46)}`,
    // 4 panda
    (c, d) => `<circle cx="14" cy="16" r="8" fill="#2a2140"/><circle cx="50" cy="16" r="8" fill="#2a2140"/>${head('#fff', 21, 19)}<ellipse cx="23" cy="34" rx="6.5" ry="8" fill="#2a2140" transform="rotate(-18 23 34)"/><ellipse cx="41" cy="34" rx="6.5" ry="8" fill="#2a2140" transform="rotate(18 41 34)"/><circle cx="24" cy="34" r="2.8" fill="#fff"/><circle cx="40" cy="34" r="2.8" fill="#fff"/><circle cx="24.6" cy="34.4" r="1.4" fill="#231942"/><circle cx="40.6" cy="34.4" r="1.4" fill="#231942"/><ellipse cx="32" cy="43" rx="3.2" ry="2.2" fill="#2a2140"/>${smile(46)}<circle cx="32" cy="9" r="0" fill="${c}"/>`,
    // 5 baqa
    (c, d) => `<circle cx="20" cy="19" r="9" fill="${c}"/><circle cx="44" cy="19" r="9" fill="${c}"/><circle cx="20" cy="19" r="5.5" fill="#fff"/><circle cx="44" cy="19" r="5.5" fill="#fff"/><circle cx="21" cy="19.5" r="2.8" fill="#231942"/><circle cx="45" cy="19.5" r="2.8" fill="#231942"/>${head(c, 22, 17)}<path d="M20 42 Q32 54 44 42" fill="none" stroke="#231942" stroke-width="2.6" stroke-linecap="round"/><circle cx="27" cy="36" r="1.2" fill="${d}"/><circle cx="37" cy="36" r="1.2" fill="${d}"/><circle cx="17" cy="43" r="3.4" fill="#ff8fab" opacity=".6"/><circle cx="47" cy="43" r="3.4" fill="#ff8fab" opacity=".6"/>`,
    // 6 robot
    (c, d) => `<line x1="32" y1="4" x2="32" y2="14" stroke="${d}" stroke-width="3"/><circle cx="32" cy="5" r="4" fill="#ff4d6d"/><rect x="10" y="14" width="44" height="40" rx="12" fill="${c}"/><rect x="6" y="28" width="5" height="12" rx="2.5" fill="${d}"/><rect x="53" y="28" width="5" height="12" rx="2.5" fill="${d}"/><rect x="16" y="23" width="32" height="17" rx="8" fill="#1d1640"/><circle cx="25" cy="31.5" r="4.6" fill="#4ff0ff"/><circle cx="39" cy="31.5" r="4.6" fill="#4ff0ff"/><rect x="22" y="45" width="20" height="5" rx="2.5" fill="#1d1640"/><path d="M27 45 V50 M32 45 V50 M37 45 V50" stroke="${c}" stroke-width="1.4"/>`,
    // 7 kosmonavt
    (c, d) => `<circle cx="32" cy="34" r="25" fill="#f4f1ff"/><circle cx="32" cy="34" r="25" fill="none" stroke="${c}" stroke-width="4"/><rect x="12" y="22" width="40" height="26" rx="13" fill="#231a52"/><path d="M18 30 Q22 25 28 26" stroke="#8fa8ff" stroke-width="2.4" fill="none" stroke-linecap="round" opacity=".8"/><circle cx="26" cy="37" r="3" fill="#fff"/><circle cx="38" cy="37" r="3" fill="#fff"/><circle cx="26.6" cy="37.4" r="1.4" fill="#231942"/><circle cx="38.6" cy="37.4" r="1.4" fill="#231942"/><path d="M28 43 Q32 46 36 43" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round"/><rect x="29" y="6" width="6" height="7" rx="3" fill="${d}"/>`,
    // 8 boyqush
    (c, d) => `<path d="M12 24 L14 8 L26 17Z M52 24 L50 8 L38 17Z" fill="${c}"/>${head(c, 22, 20)}<circle cx="23" cy="33" r="9" fill="#fff6dc"/><circle cx="41" cy="33" r="9" fill="#fff6dc"/><circle cx="23" cy="33" r="5.4" fill="#231942"/><circle cx="41" cy="33" r="5.4" fill="#231942"/><circle cx="24.6" cy="31.4" r="1.9" fill="#fff"/><circle cx="42.6" cy="31.4" r="1.9" fill="#fff"/><path d="M29 41 L35 41 L32 47Z" fill="#ffb12e"/><path d="M20 49 Q24 52 28 49 M36 49 Q40 52 44 49" stroke="${d}" stroke-width="2" fill="none" stroke-linecap="round"/>`,
    // 9 pingvin
    (c, d) => `${head('#2a2457', 22, 20)}<ellipse cx="32" cy="42" rx="14" ry="13" fill="#fff"/><circle cx="24" cy="33" r="4.6" fill="#fff"/><circle cx="40" cy="33" r="4.6" fill="#fff"/><circle cx="24.8" cy="33.4" r="2.3" fill="#231942"/><circle cx="40.8" cy="33.4" r="2.3" fill="#231942"/><path d="M27 39 L37 39 L32 46Z" fill="${c}"/><path d="M15 38 Q9 48 14 52" stroke="#2a2457" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M49 38 Q55 48 50 52" stroke="#2a2457" stroke-width="5" fill="none" stroke-linecap="round"/><circle cx="16" cy="44" r="0" fill="${d}"/>`,
    // 10 dino
    (c, d) => `<path d="M20 20 L24 8 L28 19Z M30 18 L34 5 L38 18Z M40 19 L44 8 L48 21Z" fill="${d}"/>${head(c, 21, 19)}<circle cx="22" cy="35" r="5.2" fill="#fff"/><circle cx="42" cy="35" r="5.2" fill="#fff"/><circle cx="23" cy="35.5" r="2.6" fill="#231942"/><circle cx="43" cy="35.5" r="2.6" fill="#231942"/><circle cx="28" cy="42" r="1.4" fill="${d}"/><circle cx="36" cy="42" r="1.4" fill="${d}"/><path d="M22 47 Q32 55 42 47" stroke="#231942" stroke-width="2.4" fill="none" stroke-linecap="round"/><path d="M26 49.5 L28 52 L30 50 M34 50 L36 52 L38 49.5" stroke="#fff" stroke-width="1.6" fill="none" stroke-linejoin="round"/>`,
    // 11 o'zga sayyoralik
    (c, d) => `<line x1="22" y1="12" x2="17" y2="3" stroke="${d}" stroke-width="2.4"/><line x1="42" y1="12" x2="47" y2="3" stroke="${d}" stroke-width="2.4"/><circle cx="17" cy="3.5" r="3" fill="#ffc83d"/><circle cx="47" cy="3.5" r="3" fill="#ffc83d"/><path d="M32 8 C52 8 56 36 44 50 Q32 58 20 50 C8 36 12 8 32 8Z" fill="${c}"/><ellipse cx="22" cy="31" rx="7" ry="9.5" fill="#1d1640" transform="rotate(-22 22 31)"/><ellipse cx="42" cy="31" rx="7" ry="9.5" fill="#1d1640" transform="rotate(22 42 31)"/><circle cx="24" cy="28" r="2.2" fill="#fff"/><circle cx="44" cy="28" r="2.2" fill="#fff"/><path d="M28 46 Q32 49 36 46" stroke="#1d1640" stroke-width="2.2" fill="none" stroke-linecap="round"/>`,
  ];
  const COLORS = [
    [['#ffa94d', '#ffd8a8'], ['#9ca3b8', '#e5e7f0']],     // mushuk
    [['#b9783f', '#e9c9a0'], ['#8a6bd6', '#d6c9f5']],     // ayiq
    [['#ffffff', '#ffb3c7'], ['#cdbdff', '#ffb3c7']],     // quyon
    [['#ff8a3d', '#fff1e0'], ['#f0605d', '#ffe3e0']],     // tulki
    [['#fff', '#fff'], ['#fff', '#fff']],                  // panda
    [['#56d364', '#2d9c46'], ['#4cc9f0', '#2488b0']],     // baqa
    [['#9bb3ff', '#5a72d6'], ['#ffc83d', '#c99200']],     // robot
    [['#6c3bff', '#4a22c4'], ['#ff4d6d', '#c42c4a']],     // kosmonavt
    [['#a8794a', '#6e4a2a'], ['#7a8fb3', '#4a5d80']],     // boyqush
    [['#ff9f1c', '#e07b00'], ['#ff5d8f', '#d03466']],     // pingvin
    [['#7ddb6b', '#3fa535'], ['#ffb347', '#d9822b']],     // dino
    [['#8be28b', '#41b341'], ['#c58bff', '#8d4bd6']],     // alien
  ];
  const BGS = ['#ffe9a8', '#c8f1ff', '#ffd1e0', '#d7ffd9', '#e6dcff', '#ffd9b8'];

  window.Avatar = {
    keys: Array.from({ length: 24 }, (_, i) => 'a' + String(i + 1).padStart(2, '0')),
    svg(key, cls) {
      const m = /^a(\d\d)$/.exec(key || '');
      if (!m) return `<span class="${cls || ''}" style="font-size:1.6em">${key || '🙂'}</span>`;
      const i = parseInt(m[1], 10) - 1;
      const t = i % 12, v = Math.floor(i / 12);
      const [c, d] = COLORS[t][v];
      return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" class="${cls || 'w-full h-full'}" aria-hidden="true"><circle cx="32" cy="32" r="31" fill="${BGS[i % BGS.length]}"/>${TYPES[t](c, d)}</svg>`;
    },
  };

  // ---------- Alpine direktivalari
  document.addEventListener('alpine:init', () => {
    // x-avatar="expr": avatar SVG'ni element ichiga qo'yadi
    Alpine.directive('avatar', (el, { expression }, { effect, evaluateLater }) => {
      const get = evaluateLater(expression);
      effect(() => get((v) => { el.innerHTML = Avatar.svg(v); }));
    });
    // x-countup="son": raqam o'zgarganda sanab o'sadi/kamayadi
    Alpine.directive('countup', (el, { expression }, { effect, evaluateLater }) => {
      const get = evaluateLater(expression);
      const state = { v: 0 };
      effect(() => get((to) => {
        to = Number(to) || 0;
        if (REDUCED || !window.gsap) { state.v = to; el.textContent = Math.round(to); return; }
        gsap.to(state, { v: to, duration: .9, ease: 'power2.out', onUpdate: () => (el.textContent = Math.round(state.v)) });
      }));
    });
  });

  // ---------- Lottie (ixtiyoriy): /static/lottie/<nom>.json bo'lsa o'ynaydi, bo'lmasa CSS effekt ishlaydi
  window.Lottie = {
    async play(el, name) {
      if (!window.lottie || !el || REDUCED) return false;
      try {
        const r = await fetch(`/static/lottie/${name}.json`, { method: 'HEAD' });
        if (!r.ok) return false;
        lottie.loadAnimation({ container: el, path: `/static/lottie/${name}.json`, loop: false, autoplay: true });
        return true;
      } catch (_) { return false; }
    },
  };

  window.FACTS = [
    'Bilasanmi? Tez javob ko\'proq ball beradi ⚡',
    'Ketma-ket 3 ta to\'g\'ri javob — maxfiy kod beradi 🎁',
    'Maxfiy kod bilan raqibingni muzlatishing yoki ball o\'g\'irlashing mumkin ❄️💰',
    'Testda boshqa oynaga o\'tma — darhol chetlatilasan 🔒',
    'Klaviaturada 1, 2, 3, 4 tugmalari bilan ham javob berish mumkin ⌨️',
    'Xato qilsang — ham hechqisi yo\'q, keyingi savol seniki! 💪',
    'Oxirgi 10 soniyada taymer qizarib pulsatsiya qiladi ⏱️',
  ];

  // ---------- Lucide ikonkalari
  function icons() { if (window.lucide) lucide.createIcons(); }
  document.addEventListener('DOMContentLoaded', () => {
    icons();
    let t;
    new MutationObserver(() => { clearTimeout(t); t = setTimeout(icons, 60); }).observe(document.body, { childList: true, subtree: true });
  });
})();
