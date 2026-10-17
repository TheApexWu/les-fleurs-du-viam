/* Taste lens: scores a bouquet with plain floristry rules and sketches it. No model, no network.
   window.Taste.evaluate(stems) -> {overall, axes, mood, critique, suggestion}; window.Taste.sketch(stems) -> svg string.
   stems: [{variety, color, label, swatch, quantity, available}] */
(() => {
  'use strict';
  // Hue on the colour wheel (null = neutral white). Meanings are common flower-language readings.
  const STEM = {
    'rose:red': { hue: 352, meaning: 'love', height: 0.8 },
    'rose:pink': { hue: 330, meaning: 'gratitude', height: 0.8 },
    'rose:yellow': { hue: 50, meaning: 'friendship', height: 0.8 },
    'carnation:white': { hue: null, meaning: 'remembrance', height: 0.65 },
    'carnation:red-white': { hue: 355, meaning: 'devotion', height: 0.65 },
    'lily:orange': { hue: 28, meaning: 'confidence', height: 1.0 },
    'lily:yellow': { hue: 55, meaning: 'cheer', height: 1.0 },
  };
  const key = (s) => `${s.variety}:${s.color}`;
  const gap = (a, b) => { const d = Math.abs(a - b) % 360; return Math.min(d, 360 - d); };

  function harmony(hues, hasNeutral) {
    if (!hues.length) return [70, 'All white: calm, but it needs one colour to hold the eye.'];
    const spread = Math.max(0, ...hues.flatMap((a) => hues.map((b) => gap(a, b))));
    if (spread <= 35) return [hues.length > 1 ? 88 : 82, hues.length > 1 ? 'Close colours, so it reads as one mood.' : 'One colour family, simple and clear.'];
    if (spread >= 150) return [84 + (hasNeutral ? 6 : 0), 'Opposite colours give contrast' + (hasNeutral ? ', and white keeps it from shouting.' : '.')];
    return [hasNeutral ? 74 : 62, hasNeutral ? 'The colours compete a little; white helps bridge them.' : 'These colours sit at an awkward distance and compete.'];
  }

  function evaluate(stems) {
    const picked = stems.filter((s) => s.quantity > 0);
    const n = picked.reduce((t, s) => t + s.quantity, 0);
    if (!n) return null;
    const info = picked.map((s) => ({ ...s, ...(STEM[key(s)] || { hue: null, meaning: 'mystery', height: 0.8 }) }));
    const hues = [...new Set(info.filter((s) => s.hue !== null).map((s) => s.hue))];
    const hasNeutral = info.some((s) => s.hue === null || s.color === 'red-white');
    const [harm, harmNote] = harmony(hues, hasNeutral);
    const rhythm = n === 1 ? 62 : n % 2 ? (n <= 9 ? 95 : 78) : 70;
    const rhythmNote = n === 1 ? 'A single stem is a statement.' : n % 2 ? `${n} stems: odd numbers look natural.` : `${n} stems: an even count can look staged.`;
    const heights = new Set(info.map((s) => s.height));
    const prop = n >= 3 ? (heights.size > 1 ? 92 : 78) : n === 2 ? 70 : 60;
    const propNote = n >= 3 ? (heights.size > 1 ? 'Tall, middle and low lines: the classic three-level shape.' : 'Same-height stems; a taller lily would add a line.') : 'Too few stems for a tall-middle-low shape.';
    const top = Math.max(...picked.map((s) => s.quantity)) / n;
    const focus = n === 1 ? 80 : top >= 0.4 && top <= 0.7 ? 95 : top > 0.7 ? 80 : 66;
    const focusNote = top > 0.7 && n > 1 ? 'One colour dominates; a second voice would help.' : top < 0.4 ? 'No clear lead colour, so it reads busy.' : 'A clear lead colour with support.';
    const axes = [['Harmony', harm, harmNote], ['Rhythm', rhythm, rhythmNote], ['Proportion', prop, propNote], ['Focus', focus, focusNote]];
    const overall = Math.round(harm * 0.35 + rhythm * 0.2 + prop * 0.25 + focus * 0.2);
    const counts = {};
    info.forEach((s) => { counts[s.meaning] = (counts[s.meaning] || 0) + s.quantity; });
    const mood = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([m]) => m);
    const weakest = axes.reduce((w, a) => (a[1] < w[1] ? a : w));
    return { overall, axes, mood, critique: weakest[2], suggestion: suggest(weakest[0], stems, n, hues) };
  }

  function suggest(axis, stems, n, hues) {
    const free = (k) => stems.find((s) => key(s) === k && (s.available ?? 99) > s.quantity);
    const pick = (keys) => keys.map(free).find(Boolean);
    let s = null;
    if (axis === 'Rhythm' && n % 2 === 0) s = pick(['carnation:white', 'lily:yellow', 'rose:yellow', 'rose:pink']);
    if (axis === 'Proportion') s = pick(['lily:orange', 'lily:yellow']);
    if (axis === 'Harmony') s = pick(['carnation:white', 'carnation:red-white']);
    if (axis === 'Focus') s = pick(hues.length ? ['carnation:white', 'lily:yellow'] : ['rose:red', 'lily:orange']);
    return s ? { key: key(s), label: s.label, text: `Add one ${s.label.toLowerCase()}.` } : null;
  }

  // Sketch: stems fanned from a vase, the tallest in the middle-back, like a simple florist layout.
  function sketch(stems) {
    const list = [];
    stems.forEach((s) => { for (let i = 0; i < s.quantity; i++) list.push({ ...s, ...(STEM[key(s)] || { height: 0.8 }) }); });
    list.sort((a, b) => b.height - a.height);
    const n = list.length;
    const parts = list.map((s, i) => {
      const spread = n > 1 ? (i / (n - 1) - 0.5) : 0;
      const ang = (i === 0 ? -6 : spread * 46 + (i % 2 ? 6 : -6)) * Math.PI / 180;
      const len = 120 * s.height * (i === 0 ? 1 : 0.88 - 0.04 * (i % 3));
      const x0 = 110 + spread * 14, y0 = 196, x1 = x0 + Math.sin(ang) * len, y1 = y0 - Math.cos(ang) * len;
      const col = s.swatch || '#999';
      const head = s.variety === 'lily'
        ? Array.from({ length: 6 }, (_, k) => `<ellipse cx="${x1}" cy="${y1 - 6}" rx="3.2" ry="9" fill="${col}" transform="rotate(${k * 60} ${x1} ${y1})"/>`).join('')
        : s.variety === 'carnation'
          ? `<circle cx="${x1}" cy="${y1}" r="9" fill="${col}" stroke="${s.color === 'red-white' ? '#c23a4b' : '#c9c3b2'}" stroke-width="2" stroke-dasharray="2 2"/>`
          : `<circle cx="${x1}" cy="${y1}" r="9.5" fill="${col}"/><path d="M${x1 - 5} ${y1}q5 -6 10 0q-5 5 -10 0" stroke="#00000030" fill="none"/>`;
      return `<path d="M${x0} ${y0}L${x1} ${y1 + 8}" stroke="#5f7e5c" stroke-width="2" stroke-linecap="round"/>${head}`;
    }).join('');
    const vase = '<path d="M88 160h44l-5 70h-34z" fill="#e8ece6" fill-opacity=".75" stroke="#9fb0a2"/><ellipse cx="110" cy="160" rx="22" ry="4" fill="none" stroke="#9fb0a2"/>';
    return `<svg viewBox="0 0 220 240" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${parts}${vase}</svg>`;
  }

  window.Taste = { evaluate, sketch };
})();
