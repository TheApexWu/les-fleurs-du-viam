/* A deliberately small client: the server owns vision, planning, and all motion. */
(() => {
  'use strict';

  const demo = new URLSearchParams(window.location.search).get('demo') === '1';
  const teaching = new URLSearchParams(window.location.search).get('teach') === '1';
  const MAX_ORDER_SIZE = 12;
  const $ = (id) => document.getElementById(id);
  // Colours sampled from the stems on the workbench; one entry per variety and colour we stock.
  const palette = {
    'rose:red': { label: 'Red rose', swatch: '#8f2531', background: '#f2e5e3', light: '#d9858d' },
    'rose:pink': { label: 'Pink rose', swatch: '#c47fa0', background: '#f3e8ec', light: '#ecc2d3' },
    'rose:yellow': { label: 'Yellow rose', swatch: '#e7c752', background: '#f5f0db', light: '#f7e6a4' },
    'carnation:white': { label: 'White carnation', swatch: '#f2eee4', background: '#eef0e8', light: '#c9c3b2' },
    'carnation:red-white': { label: 'Red & white carnation', swatch: '#f4ebe6', background: '#f2e8e6', light: '#c23a4b' },
    'lily:orange': { label: 'Orange lily', swatch: '#e57a26', background: '#f5ebe0', light: '#f6b77f' },
    'lily:yellow': { label: 'Yellow lily', swatch: '#e2d45a', background: '#f3f2df', light: '#c2b544' },
  };
  const VARIETIES = [['rose', 'Roses'], ['carnation', 'Carnations'], ['lily', 'Lilies']];
  const keyOf = (item) => item.key || `${item.variety || 'rose'}:${item.color}`;
  const stock = () => Object.entries(palette).map(([key, theme]) => {
    const [variety, color] = key.split(':');
    return { variety, color, label: theme.label, available: null };
  });
  const state = {
    colors: stock(),
    quantities: {}, inventory: null, plan: null, order: null, busy: false, scanning: false,
    connected: false, pollFailures: 0, demoTimer: null,
  };

  function textElement(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function styleFor(item) {
    return palette[keyOf(item)] || { label: `${item.color} ${item.variety || 'rose'}`, swatch: '#927e90', background: '#eee9e8', light: '#d9c6d3' };
  }

  // Only controlled palette values enter SVG markup; resource labels use textContent.
  const STEM = '<path d="M53 109C54 88 53 66 56 41" stroke="#638164" stroke-width="2" stroke-linecap="round"/><path d="M54 86C39 89 29 80 28 71C42 70 51 76 54 86Z" fill="#7c9472"/><path d="M54 74C65 76 76 70 79 60C66 57 57 65 54 74Z" fill="#6f8d67"/>';

  function flowerArt(item) {
    const theme = styleFor(item);
    const variety = item.variety || 'rose';
    if (variety === 'carnation') {
      const frill = Array.from({ length: 14 }, (_, i) => {
        const a = (i / 14) * Math.PI * 2;
        return `${(56 + Math.cos(a) * 25).toFixed(1)},${(30 + Math.sin(a) * 22).toFixed(1)} ${(56 + Math.cos(a + 0.22) * 18).toFixed(1)},${(30 + Math.sin(a + 0.22) * 16).toFixed(1)}`;
      }).join(' ');
      const stripes = item.color === 'red-white' ? Array.from({ length: 10 }, (_, i) => {
        const a = (i / 10) * Math.PI * 2;
        return `<path d="M${(56 + Math.cos(a) * 9).toFixed(1)} ${(30 + Math.sin(a) * 8).toFixed(1)}L${(56 + Math.cos(a) * 24).toFixed(1)} ${(30 + Math.sin(a) * 21).toFixed(1)}" stroke="${theme.light}" stroke-width="1.6" stroke-linecap="round"/>`;
      }).join('') : '';
      return `<svg viewBox="0 0 110 120" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${STEM}<path d="M50 52L56 40L62 52Z" fill="#7c9472"/><polygon points="${frill}" fill="${theme.swatch}" stroke="${theme.light}" stroke-opacity=".55" stroke-width="1" stroke-linejoin="round"/>${stripes}<circle cx="56" cy="30" r="5" fill="${theme.light}" fill-opacity=".35"/></svg>`;
    }
    if (variety === 'lily') {
      const petals = Array.from({ length: 6 }, (_, i) => `<path d="M56 32C51 22 52 8 56 0C60 8 61 22 56 32Z" fill="${theme.swatch}" stroke="${theme.light}" stroke-width="1" transform="rotate(${i * 60 + 30} 56 32)"/>`).join('');
      return `<svg viewBox="0 0 110 120" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${STEM}${petals}<path d="M56 32L49 20M56 32L63 21M56 32L56 18" stroke="#a6612f" stroke-width="1.1" stroke-linecap="round"/><circle cx="49" cy="20" r="1.8" fill="#8a4a25"/><circle cx="63" cy="21" r="1.8" fill="#8a4a25"/><circle cx="56" cy="18" r="1.8" fill="#8a4a25"/></svg>`;
    }
    return roseArt(theme);
  }

  function roseArt(theme) {
    return `<svg viewBox="0 0 110 120" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${STEM}<path d="M55 47C37 45 24 29 31 18C35 9 45 11 48 17C47 0 64-1 70 11C78 8 86 16 81 25C91 38 73 53 61 53Z" fill="${theme.swatch}" stroke="#0000000b"/><path d="M36 18C31 31 47 45 60 46C49 38 45 28 51 20C58 11 68 15 68 23C62 29 58 32 53 34M49 44C62 49 77 40 77 31M48 16C49 23 49 31 53 34C61 35 72 27 68 23M53 34C53 40 56 43 60 46" stroke="${theme.light}" stroke-opacity=".8" stroke-width="1.1" stroke-linecap="round"/></svg>`;
  }

  function total() {
    return Object.values(state.quantities).reduce((sum, quantity) => sum + quantity, 0);
  }

  function isDemo() {
    return demo || state.inventory?.mode === 'demo';
  }

  function activeOrder() {
    return state.order && ['pending', 'queued', 'running', 'planning', 'picking', 'placing', 'stopping'].includes(state.order.status);
  }

  function announce(message) {
    $('announcer').textContent = message;
  }

  function notice(message, info = false) {
    const node = $('global-notice');
    node.textContent = message || '';
    node.className = info ? 'notice info' : 'notice';
    node.hidden = !message;
  }

  function setConnection(mode, label) {
    $('connection-pill').className = `connection-pill ${mode}`;
    $('connection-label').textContent = label;
  }

  function payload() {
    return {
      items: state.colors.filter((item) => state.quantities[keyOf(item)] > 0).map((item) => ({ variety: item.variety, color: item.color, quantity: state.quantities[keyOf(item)] })),
      rules: { selection: $('selection-rule').value },
    };
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch(path, {
        ...options,
        headers: { 'Accept': 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
        signal: controller.signal,
      });
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) throw new Error(`The server did not return JSON (${response.status}). Start the bouquet server and open its address.`);
      const data = await response.json();
      if (!response.ok) {
        const detail = typeof data.error === 'string' ? data.error : (data.message || `Request failed (${response.status})`);
        const blockers = Array.isArray(data.blockers) ? data.blockers.map(blockerText) : [];
        throw new Error([detail, ...blockers].join(' '));
      }
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('The request timed out. Check the robot connection before trying again.');
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function renderFlowers() {
    const grid = $('flower-grid');
    const focus = document.activeElement?.dataset?.control;
    grid.replaceChildren();
    for (const [variety, heading] of VARIETIES) {
      const group = state.colors.filter((item) => (item.variety || 'rose') === variety);
      if (!group.length) continue;
      grid.append(textElement('h3', heading, 'variety-heading'));
    for (const item of group) {
      const quantity = state.quantities[keyOf(item)] || 0;
      const theme = styleFor(item);
      const label = item.label || theme.label;
      const card = textElement('article', '', `flower-card${quantity ? ' selected' : ''}`);
      card.style.setProperty('--flower-bg', theme.background);
      const picture = textElement('div', '', 'flower-picture');
      picture.innerHTML = flowerArt(item);
      picture.append(textElement('span', '✓', 'card-picked'));
      const body = textElement('div', '', 'flower-card-body');
      body.append(textElement('h3', label));
      body.append(textElement('p', Number.isInteger(item.detected_count)
        ? `${item.detected_count} ${state.inventory?.staged_demo ? 'at marked slot' : 'detected'} · ${item.available || 0} ready to pick`
        : Number.isInteger(item.available) ? `${item.available} available in view` : 'Inventory not scanned', 'available-label'));
      const controls = textElement('div', '', 'quantity-control');
      for (const [delta, symbol, action] of [[-1, '−', 'Remove'], [1, '+', 'Add']]) {
        if (delta === 1) {
          const count = textElement('output', String(quantity));
          count.setAttribute('aria-label', `${label} quantity`);
          controls.append(count);
        }
        const button = textElement('button', symbol);
        button.type = 'button';
        button.setAttribute('aria-label', `${action} one ${label.toLowerCase().replace(/roses$/, 'rose').replace(/carnations$/, 'carnation').replace(/lilies$/, 'lily')}`);
        button.dataset.control = `${keyOf(item)}:${delta}`;
        button.disabled = !!activeOrder() || state.busy || (delta < 0 ? quantity === 0 : total() >= (state.inventory?.commissioning ? 1 : MAX_ORDER_SIZE));
        button.addEventListener('click', () => {
          state.quantities[keyOf(item)] = Math.max(0, quantity + delta);
          invalidatePlan();
          render();
          announce(`${state.quantities[keyOf(item)]} × ${label.toLowerCase()} selected. ${total()} stems total.`);
        });
        controls.append(button);
      }
      body.append(controls);
      card.append(picture, body);
      grid.append(card);
    }
    }
    if (focus) Array.from(grid.querySelectorAll('button')).find((button) => button.dataset.control === focus && !button.disabled)?.focus({ preventScroll: true });
  }

  function invalidatePlan() {
    state.plan = null;
    $('plan-result').hidden = true;
  }

  function renderSummary() {
    const count = total();
    $('stem-total').textContent = count;
    $('stem-unit').textContent = count === 1 ? 'stem' : 'stems';
    const list = $('summary-items');
    list.replaceChildren();
    for (const item of state.colors.filter((item) => state.quantities[keyOf(item)] > 0)) {
      const row = textElement('div', '', 'summary-row');
      const dot = textElement('span', '', 'color-dot');
      dot.style.setProperty('--swatch', styleFor(item).swatch);
      row.append(dot, textElement('span', item.label || styleFor(item).label), textElement('span', `× ${state.quantities[keyOf(item)]}`, 'summary-quantity'));
      list.append(row);
    }
    if (!count) list.append(textElement('p', 'Something lovely starts with one stem.', 'empty-summary'));
    const running = !!activeOrder();
    $('clear-selection').disabled = running || state.busy || !count;
    $('selection-rule').disabled = running || state.busy;
    $('plan-button').disabled = !count || state.busy || state.scanning || running || (!demo && !state.connected);
    $('build-button').disabled = !count || state.busy || state.scanning || running || !state.plan?.ready;
    $('build-button').firstChild.textContent = isDemo() ? 'Preview arrangement ' : (running ? 'Arranging your bouquet ' : 'Build my bouquet ');
    $('scan-button').disabled = state.scanning || state.busy || running;
    $('scan-button').classList.toggle('loading', state.scanning);
    $('scan-button').setAttribute('aria-busy', String(state.scanning));
    $('build-caption').textContent = isDemo() ? 'Preview only. The robot will not move.' : (running ? 'The arm is working. Keep the workbench clear.' : state.plan?.ready ? 'Ready to arrange. The arm will move when you build.' : 'Choose your stems, then check the bouquet.');
  }

  function renderInventory() {
    const list = $('inventory-list');
    list.replaceChildren();
    for (const item of state.colors) {
      const row = textElement('div', '', 'inventory-row');
      const dot = textElement('span', '', 'color-dot');
      dot.style.setProperty('--swatch', styleFor(item).swatch);
      row.append(dot, textElement('span', item.label || styleFor(item).label));
      row.append(textElement('span', Number.isInteger(item.detected_count) ? `${item.detected_count} detected`
        : Number.isInteger(item.available) ? `${item.available} stem${item.available === 1 ? '' : 's'}` : '—', 'inventory-count'));
      list.append(row);
    }
    const mode = isDemo() ? 'demo' : (state.connected && state.inventory?.mode === 'live' ? 'live' : 'offline');
    $('inventory-dot').className = `status-dot ${mode}`;
    $('inventory-status-text').textContent = isDemo() ? 'Sample inventory · preview only' : state.scanning ? 'Looking at the workbench…' : state.inventory?.staged_demo ? 'Staged flowers · fresh tape checks' : mode === 'live' ? 'Live vision connected' : 'Live inventory unavailable';
    const blockers = state.inventory?.blockers || [];
    const detectionCount = state.inventory?.raw_detection_count;
    const needsCalibration = !isDemo() && state.inventory && (!state.inventory.ready || blockers.length > 0);
    $('calibration-notice').hidden = !needsCalibration;
    $('calibration-title').textContent = 'Inventory needs attention';
    $('calibration-blockers').replaceChildren(...blockers.map((blocker) => textElement('li', blockerText(blocker))));
    if (needsCalibration && !blockers.length) $('calibration-blockers').append(textElement('li', 'Camera-to-table calibration and the grasp reference must be verified before an order can start.'));
    $('detection-evidence').hidden = !Number.isInteger(detectionCount);
    $('detection-evidence').textContent = Number.isInteger(detectionCount) ? state.inventory?.staged_demo
      ? `${detectionCount} tape marks · flower labels assigned by staging.`
      : `${detectionCount} raw stem detection${detectionCount === 1 ? '' : 's'} · pick locations still need verification.` : '';
    const detectedAt = state.inventory?.detected_at;
    const date = detectedAt ? new Date(typeof detectedAt === 'number' ? (detectedAt < 1e12 ? detectedAt * 1000 : detectedAt) : detectedAt) : null;
    $('inventory-time').textContent = date && !Number.isNaN(date.getTime()) ? `Last scan ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · checked again before building` : 'Inventory is checked again before an order starts.';
    const cameraUrl = state.inventory?.camera_url;
    if (typeof cameraUrl === 'string' && /^(\/[^/]|https?:\/\/)/.test(cameraUrl)) {
      const stamp = detectedAt ? encodeURIComponent(String(detectedAt)) : '';
      const source = `${cameraUrl}${stamp ? `${cameraUrl.includes('?') ? '&' : '?'}scan=${stamp}` : ''}`;
      if ($('camera-preview').getAttribute('src') !== source) $('camera-preview').src = source;
      $('camera-view').hidden = false;
      $('camera-preview').style.cursor = teaching && state.inventory?.staged_demo ? 'crosshair' : '';
    } else $('camera-view').hidden = true;
    renderCandidates();
    renderCameraOverlay();
  }

  function renderCandidates() {
    const candidates = Array.isArray(state.inventory?.candidates) ? state.inventory.candidates : [];
    const list = $('candidate-list');
    list.replaceChildren();
    list.hidden = candidates.length === 0;
    if (!candidates.length) return;
    list.append(textElement('p', 'DETECTION PREVIEW', 'candidate-eyebrow'));
    candidates.slice(0, 6).forEach((candidate, index) => {
      const card = textElement('div', '', 'candidate-card');
      const heading = textElement('div', '', 'candidate-heading');
      const color = candidate.color && candidate.color !== 'unknown'
        ? `${candidate.color} ${candidate.variety || 'rose'}` : 'flower unknown';
      heading.append(textElement('strong', `${index + 1}. ${color}`));
      const score = candidate.label_source === 'operator_staged_slot' ? 'taught slot · '
        : Number.isFinite(candidate.confidence) ? `${Math.round(candidate.confidence * 100)}% · ` : '';
      const graspPreview = Array.isArray(candidate.grasp_pixel) && candidate.grasp_pixel.length === 2
        && ['pickup_approach', 'pretend_grasp', 'lift'].every((name) => candidate.pickup_poses?.[name]);
      heading.append(textElement('span', `${score}${candidate.pickable ? 'ready to pick' : graspPreview ? 'grasp preview · motion blocked' : 'vision needs attention'}`));
      card.append(heading);
      if (Array.isArray(candidate.grasp_pixel) && candidate.grasp_pixel.length >= 2) card.append(textElement('p', `Grasp pixel: ${candidate.grasp_pixel.slice(0, 2).map((value) => Math.round(value)).join(', ')}`));
      if (Array.isArray(candidate.world_grasp) && candidate.world_grasp.length >= 3) card.append(textElement('p', `Table grasp: ${candidate.world_grasp.slice(0, 3).map((value) => Number(value).toFixed(1)).join(', ')} mm`));
      const reasons = (Array.isArray(candidate.blockers) ? candidate.blockers : []).map(blockerText);
      if (reasons.length) card.append(textElement('p', reasons.join(' · '), 'candidate-blocker'));
      list.append(card);
    });
    if (candidates.length > 6) list.append(textElement('p', `${candidates.length - 6} more detections in the current scan.`, 'muted'));
  }

  function renderCameraOverlay() {
    const overlay = $('camera-overlay');
    overlay.replaceChildren();
    const size = state.inventory?.image_size;
    const width = Array.isArray(size) ? Number(size[0]) : $('camera-preview').naturalWidth;
    const height = Array.isArray(size) ? Number(size[1]) : $('camera-preview').naturalHeight;
    if (!(width > 0 && height > 0)) return;
    overlay.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const svg = (tag, attributes) => {
      const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
      return node;
    };
    // Legacy YOLO head boxes are display evidence, never robot grasp locations.
    for (const flower of state.inventory?.flower_detections || []) {
      const box = flower.bbox;
      if (!Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite)) continue;
      const color = '#edc6ff';
      overlay.append(svg('rect', { x: box[0], y: box[1], width: box[2] - box[0], height: box[3] - box[1],
        fill: 'none', stroke: color, 'stroke-width': Math.max(2, width / 400), 'stroke-dasharray': '6 5' }));
      const label = svg('text', { x: box[0], y: Math.max(20, box[1] - 8), fill: color,
        'font-size': Math.max(16, width / 55), 'font-family': 'sans-serif', 'paint-order': 'stroke',
        stroke: '#183e33', 'stroke-width': 3 });
      label.textContent = `${flower.colour || 'unknown'} ${flower.variety || 'flower'} · head only`;
      overlay.append(label);
    }
    const workspace = state.inventory?.image_workspace_polygon;
    if (Array.isArray(workspace) && workspace.length === 4) {
      overlay.append(svg('polygon', { points: workspace.map((point) => point.join(',')).join(' '),
        fill: 'none', stroke: '#b9ed92', 'stroke-width': Math.max(2, width / 400), 'stroke-dasharray': '12 8' }));
    }
    for (const band of state.inventory?.grasp_bands || []) {
      const box = band.bbox;
      if (!Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite)) continue;
      overlay.append(svg('rect', { x: box[0], y: box[1], width: box[2] - box[0], height: box[3] - box[1],
        fill: 'none', stroke: '#67d9ef', 'stroke-width': Math.max(2, width / 400), 'stroke-dasharray': '8 4' }));
    }
    const candidates = Array.isArray(state.inventory?.candidates) ? state.inventory.candidates : [];
    candidates.forEach((candidate, index) => {
      const box = candidate.bbox;
      if (!Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite)) return;
      const color = candidate.pickable ? '#b9ed92' : '#ffc579';
      const stroke = Math.max(2, width / 300);
      overlay.append(svg('rect', { x: box[0], y: box[1], width: Math.max(0, box[2] - box[0]), height: Math.max(0, box[3] - box[1]), fill: 'none', stroke: color, 'stroke-width': stroke }));
      const label = svg('text', { x: box[0] + stroke * 2, y: Math.max(20, box[1] - stroke * 2), fill: color, 'font-size': Math.max(20, width / 38), 'font-family': 'sans-serif', 'font-weight': 700, 'paint-order': 'stroke', stroke: '#183e33', 'stroke-width': stroke });
      label.textContent = String(index + 1);
      overlay.append(label);
      const pixel = candidate.grasp_pixel;
      if (Array.isArray(pixel) && pixel.length >= 2 && pixel.slice(0, 2).every(Number.isFinite)) overlay.append(svg('circle', { cx: pixel[0], cy: pixel[1], r: Math.max(4, width / 120), fill: color, stroke: '#183e33', 'stroke-width': stroke / 2 }));
    });
  }

  function renderTaste() {
    if (!window.Taste) return;
    const stems = state.colors.map((item) => ({ ...item, quantity: state.quantities[keyOf(item)] || 0, swatch: styleFor(item).swatch }));
    const read = window.Taste.evaluate(stems);
    $('taste-panel').hidden = !read;
    if (!read) return;
    $('taste-sketch').innerHTML = window.Taste.sketch(stems.filter((s) => s.quantity > 0));
    $('taste-score').textContent = String(read.overall);
    $('taste-mood').textContent = read.mood.length ? `Reads as ${read.mood.join(' and ')}.` : '';
    $('taste-axes').replaceChildren(...read.axes.map(([name, score]) => {
      const row = textElement('div', '', 'taste-axis');
      const bar = textElement('span', '', 'taste-bar');
      bar.style.setProperty('--w', `${score}%`);
      row.append(textElement('span', name), bar, textElement('span', String(score), 'taste-num'));
      return row;
    }));
    $('taste-critique').textContent = read.critique;
    const apply = $('taste-apply');
    apply.hidden = !read.suggestion || !!activeOrder() || total() >= MAX_ORDER_SIZE;
    if (read.suggestion) {
      apply.textContent = `Try it: ${read.suggestion.text}`;
      apply.onclick = () => { state.quantities[read.suggestion.key] = (state.quantities[read.suggestion.key] || 0) + 1; invalidatePlan(); render(); announce(read.suggestion.text); };
    }
  }

  function render() {
    renderFlowers();
    renderSummary();
    renderTaste();
    renderInventory();
  }

  function applyInventory(snapshot) {
    if (!snapshot || !Array.isArray(snapshot.colors)) throw new Error('The inventory response is missing its colors list.');
    state.inventory = snapshot;
    // An empty snapshot must not preserve quantities or imply old detections are current.
    const colors = snapshot.colors.length ? snapshot.colors : stock();
    state.colors = colors.map((item) => ({
      key: keyOf(item),
      variety: String(item.variety || 'rose'),
      color: String(item.color),
      label: String(item.label || styleFor(item).label),
      available: Number.isInteger(item.available) && item.available >= 0 ? item.available : null,
      detected_count: Number.isInteger(item.detected_count) ? item.detected_count : null,
      confidence: item.confidence,
    }));
    state.quantities = Object.fromEntries(state.colors.map((item) => [keyOf(item), state.quantities[keyOf(item)] || 0]));
    state.connected = demo || ['live', 'demo'].includes(snapshot.mode);
    invalidatePlan();
    $('demo-banner').hidden = !isDemo();
    setConnection(isDemo() ? 'demo' : state.connected ? 'live' : 'offline', isDemo() ? 'Preview mode' : state.connected ? 'Vision connected' : 'Robot offline');
    if (snapshot.staged_demo && state.connected) setConnection('live', snapshot.execution_enabled ? 'Staged demo · arm enabled' : 'Staged demo · read-only');
    notice('');
    if (snapshot.staged_demo) notice('Staged physical demo: reset each flower on its labeled pickup mark before Build. Flower labels come from staging; camera checks confirm the marks.', true);
    if (snapshot.commissioning) notice('Supervised one-flower limit. Verified calibration, measured workspace and camera alignment are required before motion.', true);
    render();
  }

  function blockerText(blocker) {
    return typeof blocker === 'string' ? blocker : String(blocker?.message || blocker?.reason || JSON.stringify(blocker));
  }

  function inventoryFailed(error) {
    state.connected = false;
    state.inventory = null;
    state.colors = state.colors.map((item) => ({ ...item, available: null }));
    invalidatePlan();
    setConnection('offline', 'Robot offline');
    notice(`Could not read the live inventory: ${error.message}`);
    render();
  }

  async function scan() {
    if (state.scanning || activeOrder()) return;
    state.scanning = true;
    renderSummary();
    renderInventory();
    try {
      if (demo) applyInventory(demoInventory());
      else applyInventory(await api('/api/scan', { method: 'POST' }));
      announce('Workbench inventory updated.');
    } catch (error) { inventoryFailed(error); }
    finally { state.scanning = false; render(); }
  }

  function showPlan(plan) {
    const node = $('plan-result');
    node.replaceChildren();
    node.hidden = false;
    node.className = plan.ready ? 'plan-result' : 'plan-result error';
    if (plan.ready) {
      node.append(textElement('span', `${plan.requested_total || total()} stems checked. Your bouquet is ready to arrange.`));
    } else {
      node.append(textElement('span', 'A little attention before we can build:'));
      const list = document.createElement('ul');
      for (const blocker of plan.blockers || ['The planner did not approve this bouquet.']) list.append(textElement('li', blockerText(blocker)));
      node.append(list);
    }
  }

  async function checkPlan() {
    if (state.busy || !total() || activeOrder()) return;
    state.busy = true;
    render();
    try {
      const result = demo ? demoPlan() : await api('/api/plan', { method: 'POST', body: JSON.stringify(payload()) });
      if (typeof result.ready !== 'boolean') throw new Error('The planner response is missing its readiness result.');
      state.plan = result;
      showPlan(result);
      announce(result.ready ? 'Your bouquet is ready to arrange.' : 'Your bouquet needs attention. See the planner message.');
    } catch (error) {
      state.plan = null;
      showPlan({ ready: false, blockers: [error.message] });
    } finally { state.busy = false; render(); }
  }

  function renderOrder(order) {
    state.order = order;
    const idle = !order || order.status === 'idle';
    $('progress-panel').hidden = idle;
    if (idle) { renderSummary(); return; }
    const requested = Number(order.requested_total) || total();
    const completed = Math.max(0, Number(order.completed) || 0);
    const percent = requested ? Math.min(100, Math.round(completed / requested * 100)) : 0;
    $('progress-count').textContent = `${completed} / ${requested} stems`;
    $('progress-track').setAttribute('aria-valuenow', String(percent));
    $('progress-fill').style.width = `${percent}%`;
    const messages = {
      pending: 'Checking the workbench and preparing your first stem.', queued: 'Your bouquet is queued.',
      planning: 'Finding a path to the next stem.', running: 'Picking and placing one stem at a time.',
      picking: 'Gently picking the next stem.', placing: 'Placing a stem into the vase.',
      completed: 'Your bouquet is ready. A little beauty, arranged.', complete: 'Your bouquet is ready. A little beauty, arranged.',
      failed: 'The arrangement stopped. Check the error before continuing.', error: 'The arrangement stopped. Check the error before continuing.',
      stopped: 'The arm was stopped. Inspect its position before starting another order.', stopping: 'Sending the stop command to the arm.',
      cancelled: 'The arrangement was cancelled.',
    };
    $('progress-title').textContent = ['complete', 'completed'].includes(order.status) ? 'A little beauty, arranged.' : order.status === 'stopped' ? 'A moment to pause.' : 'One stem at a time.';
    const failureStage = order.failure_stage ? `Stage: ${order.failure_stage.replaceAll('_', ' ')}. ` : '';
    $('progress-message').textContent = order.error ? `${messages[order.status] || 'Order needs attention'} ${failureStage}${blockerText(order.error)}` : (messages[order.status] || `Order status: ${order.status}`);
    $('progress-verification').hidden = typeof order.verification !== 'string' || !order.verification;
    $('progress-verification').textContent = typeof order.verification === 'string' ? order.verification : '';
    const steps = $('order-steps');
    steps.replaceChildren();
    for (const step of (Array.isArray(order.steps) ? order.steps : []).slice(-6)) {
      const message = typeof step === 'string' ? step : step.message || step.label || [step.color, step.variety, step.stage || step.status].filter(Boolean).join(' · ');
      if (message) steps.append(textElement('li', String(message)));
    }
    renderFlowers();
    renderSummary();
  }

  async function buildBouquet() {
    if (state.busy || activeOrder() || !state.plan?.ready) return;
    state.busy = true;
    render();
    try {
      if (demo) startDemoOrder();
      else {
        const order = await api('/api/orders', { method: 'POST', body: JSON.stringify(payload()) });
        if (!order.id || !order.status) throw new Error('The server did not confirm an order. Check the arm state before trying again.');
        renderOrder(order);
      }
      announce(isDemo() ? 'Arrangement preview started. No robot commands are sent.' : 'The bouquet order has started.');
      $('progress-panel').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
    } catch (error) {
      notice(`Could not start the bouquet: ${error.message}`);
      invalidatePlan();
    } finally { state.busy = false; render(); }
  }

  async function stopArm() {
    const button = $('stop-button');
    button.disabled = true;
    try {
      if (demo) {
        window.clearInterval(state.demoTimer);
        if (activeOrder()) renderOrder({ ...state.order, status: 'stopped' });
        notice('The arrangement preview has stopped. No robot command was sent.', true);
      } else {
        const result = await api('/api/stop', { method: 'POST' });
        if (state.order && activeOrder()) renderOrder({ ...state.order, ...result });
        notice(isDemo() ? 'Stop request acknowledged by the demo server. No hardware command was sent.' : 'Stop request acknowledged by the server. Inspect the arm before continuing.', true);
      }
      invalidatePlan();
      announce('Stop request acknowledged.');
    } catch (error) { notice(`Stop could not be confirmed: ${error.message} Use the physical stop button if the arm is moving.`); }
    finally { button.disabled = false; render(); }
  }

  async function pollOrder() {
    if (demo || state.busy) return;
    try {
      const order = await api('/api/orders/current');
      state.pollFailures = 0;
      if (order && order.status) {
        const wasActive = !!activeOrder();
        renderOrder(order);
        if (wasActive && !activeOrder()) {
          invalidatePlan();
          announce(order.status === 'completed' || order.status === 'complete' ? 'Your bouquet is ready.' : `Order ${order.status}.`);
          try { applyInventory(await api('/api/inventory')); } catch (error) { inventoryFailed(error); }
        }
      }
    } catch (error) {
      state.pollFailures += 1;
      if (activeOrder()) notice(`Order updates are unavailable: ${error.message} The arm may still be moving; use the stop control if needed.`);
    }
  }

  function demoInventory() {
    // What is actually on the workbench today.
    const inView = { 'rose:yellow': 2, 'rose:red': 1, 'rose:pink': 1, 'carnation:white': 2, 'carnation:red-white': 2, 'lily:orange': 1, 'lily:yellow': 1 };
    return { mode: 'demo', ready: true, detected_at: new Date().toISOString(), blockers: [],
      colors: stock().map((item) => ({ ...item, available: inView[keyOf(item)] ?? 0 })) };
  }

  function demoPlan() {
    const blockers = state.colors.filter((item) => (state.quantities[keyOf(item)] || 0) > item.available).map((item) => `Only ${item.available} × ${item.label.toLowerCase()} in view.`);
    return { ready: total() > 0 && !blockers.length, blockers, requested_total: total(), assignments: payload().items };
  }

  function startDemoOrder() {
    const order = { id: 'preview', status: 'running', requested_total: total(), completed: 0, steps: ['Preview only: checking the bouquet.'] };
    renderOrder(order);
    state.demoTimer = window.setInterval(() => {
      const completed = state.order.completed + 1;
      renderOrder({ ...state.order, completed, status: completed >= order.requested_total ? 'completed' : 'running', steps: [...state.order.steps, `Preview: placed stem ${completed} in the vase.`] });
      if (completed >= order.requested_total) { window.clearInterval(state.demoTimer); invalidatePlan(); renderSummary(); }
    }, 1600);
  }

  $('scan-button').addEventListener('click', scan);
  $('plan-button').addEventListener('click', checkPlan);
  $('build-button').addEventListener('click', buildBouquet);
  $('stop-button').addEventListener('click', stopArm);
  $('clear-selection').addEventListener('click', () => { state.quantities = {}; invalidatePlan(); render(); announce('Bouquet selection cleared.'); });
  $('selection-rule').addEventListener('change', () => { invalidatePlan(); renderSummary(); });
  $('camera-preview').addEventListener('load', renderCameraOverlay);
  $('camera-preview').addEventListener('error', () => { $('camera-view').hidden = true; });
  $('camera-preview').addEventListener('click', (event) => {
    if (!teaching || !state.inventory?.staged_demo || activeOrder()) return;
    const image = $('camera-preview');
    const rect = image.getBoundingClientRect();
    if (!(image.naturalWidth > 0 && rect.width > 0 && rect.height > 0)) return;
    const u = Math.min(image.naturalWidth - 1, Math.max(0, Math.round((event.clientX - rect.left) * image.naturalWidth / rect.width)));
    const v = Math.min(image.naturalHeight - 1, Math.max(0, Math.round((event.clientY - rect.top) * image.naturalHeight / rect.height)));
    notice(`Teaching pixel: ${u} ${v}. Use these values with the marker capture command. This click only reads the image.`, true);
    announce(`Teaching pixel ${u}, ${v}.`);
  });

  async function init() {
    render();
    if (demo) {
      $('demo-banner').hidden = false;
      applyInventory(demoInventory());
      state.quantities = { 'rose:red': 1, 'carnation:white': 2, 'lily:orange': 1 };
      render();
      return;
    }
    try { applyInventory(await api('/api/inventory')); }
    catch (error) { inventoryFailed(error); }
    await pollOrder();
    // Schedule after each request settles to avoid overlapping requests on a slow robot.
    const poll = async () => { await pollOrder(); window.setTimeout(poll, 2000); };
    window.setTimeout(poll, 2000);
  }
  init();
})();
