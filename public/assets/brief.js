/* Progressive enhancement only. All source reading works without JavaScript. */
(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const all = (selector) => [...document.querySelectorAll(selector)];
  const KEY = 'vigie.resident.v1';
  const fold = (text) => String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const rows = all('.story');
  // Per-row refs and parsed facets are cached once: render() runs on every
  // interaction over 300+ rows and up to 1200 saved marks, so it must stay
  // linear with hash lookups — never a nested scan.
  const cards = rows.map(row => {
    const d = row.dataset;
    const h3 = row.querySelector('h3');
    return {
      row,
      id: d.id,
      geo: d.geo,
      areas: new Set(String(d.areas || '').split(' ')),
      topics: new Set(String(d.topics || '').split(' ')),
      search: String(d.search || ''),
      newLabel: row.querySelector('.new-label'),
      saveBtn: row.querySelector('[data-save]'),
      title: h3 ? h3.textContent.trim() : '',
    };
  });
  const idSet = new Set(cards.map(c => c.id));
  let view = 'brief', topic = 'all', limit = 6, timer, searchTimer;
  let state = { saved: [], seen: null, visited: null };
  let savedSet = new Set(), seenSet = null, newCount = 0;
  const syncSets = () => {
    savedSet = new Set(state.saved);
    seenSet = state.seen === null ? null : new Set(state.seen);
    newCount = seenSet === null ? 0 : cards.reduce((n, c) => n + (seenSet.has(c.id) ? 0 : 1), 0);
  };
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null');
    const validIds = (ids) => Array.isArray(ids) ? [...new Set(ids.filter(x => typeof x === 'string' && /^[a-f0-9]{20}$/.test(x)))].slice(0, 1200) : [];
    if (raw && typeof raw === 'object') state = { saved: validIds(raw.saved), seen: Array.isArray(raw.seen) ? validIds(raw.seen) : null, visited: typeof raw.visited === 'string' && Number.isFinite(Date.parse(raw.visited)) ? raw.visited : null };
  } catch { /* Reading remains usable when browser storage is unavailable. */ }
  syncSets();
  const toastEl = $('#toast');
  const toast = (text) => { toastEl.textContent = text; clearTimeout(timer); timer = setTimeout(() => { toastEl.textContent = ''; }, 5000); };
  const persist = () => {
    try { localStorage.setItem(KEY, JSON.stringify(state)); return true; }
    catch { toast('Stockage indisponible : vos repères resteront seulement pendant cette visite.'); return false; }
  };
  const dateText = (value) => new Intl.DateTimeFormat('fr-CA', { timeZone:'America/Toronto', day:'numeric', month:'short', hour:'2-digit', minute:'2-digit' }).format(new Date(value));
  all('time[datetime]').forEach(el => { if (Number.isFinite(Date.parse(el.dateTime))) { el.textContent = dateText(el.dateTime); el.title = 'Heure de Québec · ' + el.dateTime; } });
  const freshnessEl = $('#freshness-label');
  const freshness = () => {
    const label = freshnessEl;
    const date = Date.parse(label.dataset.fetched);
    const age = Date.now() - date;
    const stale = !Number.isFinite(date) || age > 6 * 3600 * 1000 || age < -300000;
    label.classList.toggle('warning', stale || label.dataset.partial === 'true');
    label.textContent = !Number(label.dataset.total) ? 'État des sources inconnu' : !Number(label.dataset.ok) ? 'Collecte indisponible' : stale ? 'Collecte à actualiser' : label.dataset.partial === 'true' ? 'Collecte partielle' : 'Dernière collecte';
  };
  freshness();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) freshness(); });
  setInterval(freshness, 60000);
  const isNew = card => seenSet !== null && !seenSet.has(card.id);
  const searchEl = $('#search'), scopeEl = $('#scope'), areaEl = $('#area');
  const resultCountEl = $('#result-count'), noResultsEl = $('#no-results'), showMoreEl = $('#show-more');
  const endNoteEl = $('#end-note'), savedCountEl = $('#saved-count'), newCountEl = $('#new-count'), visitStatusEl = $('#visit-status');
  const viewBtns = all('[data-view]'), topicBtns = all('[data-topic]');
  function render() {
    const terms = fold(searchEl.value.trim()).split(/\s+/).filter(Boolean);
    const scope = scopeEl.value, area = areaEl.value;
    const matches = cards.filter(card => {
      const scopeMatch = scope === 'all' || card.geo === 'quebec-city' || (scope === 'province' && card.geo === 'quebec');
      return scopeMatch && (area === 'all' || card.areas.has(area))
        && (topic === 'all' || card.topics.has(topic))
        && terms.every(t => card.search.includes(t))
        && (view !== 'saved' || savedSet.has(card.id)) && (view !== 'new' || isNew(card));
    });
    const visible = new Set(matches.slice(0, limit));
    cards.forEach(card => {
      card.row.hidden = !visible.has(card);
      card.newLabel.hidden = !isNew(card);
      const saved = savedSet.has(card.id);
      card.saveBtn.setAttribute('aria-pressed', String(saved));
      card.saveBtn.textContent = saved ? 'Gardé ✓' : 'Garder ＋';
      card.saveBtn.setAttribute('aria-label', (saved ? 'Retirer : ' : 'Garder : ') + card.title);
    });
    viewBtns.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
    topicBtns.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.topic === topic)));
    resultCountEl.textContent = `${Math.min(limit, matches.length)} sur ${matches.length} articles dans cette vue`;
    noResultsEl.hidden = matches.length > 0;
    showMoreEl.hidden = matches.length <= limit;
    endNoteEl.textContent = matches.length > limit ? 'Un premier point. La suite, si vous en avez besoin.' : matches.length ? 'Vous avez fait le tour de cette sélection.' : 'Élargissez votre regard.';
    savedCountEl.textContent = state.saved.length ? `(${state.saved.length})` : '';
    newCountEl.textContent = state.seen !== null ? `(${newCount})` : '';
    const missingSaved = state.saved.reduce((n, id) => n + (idSet.has(id) ? 0 : 1), 0);
    visitStatusEl.textContent = view === 'saved' && missingSaved
      ? `${missingSaved} article(s) gardé(s) ne figurent plus dans cette collecte. Les repères sont conservés.`
      : state.visited ? `${newCount} article(s) apparu(s) dans les flux depuis votre repère du ${dateText(state.visited)}. Ce n’est pas un suivi des modifications.`
      : 'Mémorisez votre point de lecture pour voir les nouveaux articles à votre prochaine visite.';
    if (view === 'new' && state.seen === null) visitStatusEl.textContent = 'Créez d’abord un repère avec « Mémoriser ce point de lecture ».';
  }
  function reset() { topic = 'all'; view = 'brief'; limit = 6; searchEl.value = ''; scopeEl.value = 'local'; areaEl.value = 'all'; render(); }
  viewBtns.forEach(b => b.addEventListener('click', () => { view = b.dataset.view; limit = 6; if (view === 'saved' || view === 'new') { scopeEl.value = 'all'; areaEl.value = 'all'; searchEl.value = ''; topic = 'all'; } else { scopeEl.value = 'local'; } render(); }));
  topicBtns.forEach(b => b.addEventListener('click', () => { topic = b.dataset.topic; limit = 6; render(); }));
  // Debounced: filtering every row per keystroke wastes battery on phones;
  // 150 ms still feels instant and the final render is always correct.
  searchEl.addEventListener('input', () => { limit = 6; clearTimeout(searchTimer); searchTimer = setTimeout(render, 150); });
  [scopeEl, areaEl].forEach(el => el.addEventListener('change', () => { limit = 6; render(); }));
  ['#reset-filters', '#empty-reset'].forEach(s => $(s).addEventListener('click', reset));
  showMoreEl.addEventListener('click', () => { limit += 6; render(); });
  all('[data-save]').forEach(b => b.addEventListener('click', () => {
    const id = b.dataset.save;
    if (savedSet.has(id)) state.saved = state.saved.filter(x => x !== id);
    else { if (state.saved.length >= 1200) { toast('La limite de 1 200 repères est atteinte. Retirez-en pour en garder de nouveaux.'); return; } state.saved.push(id); }
    syncSets(); persist(); render();
  }));
  $('#remember').addEventListener('click', () => {
    state.seen = cards.map(c => c.id).slice(0, 1200); state.visited = new Date().toISOString();
    syncSets();
    const stored = persist(); render(); if (stored) toast('Point de lecture mémorisé sur cet appareil.');
  });
  $('#clear-local').addEventListener('click', () => {
    let cleared = true;
    try { [KEY, 'vigie_facets_v1', 'vigie_visit_v1'].forEach(k => localStorage.removeItem(k)); } catch { cleared = false; }
    state = { saved: [], seen: null, visited: null }; syncSets(); reset();
    $('#privacy-status').textContent = cleared ? 'Vos repères Vigie ont été effacés de cet appareil.' : 'L’accès au stockage est bloqué. Les repères de cette visite ont été effacés.';
  });
  // Hash links to disclosures must open the disclosure, including direct URLs.
  const revealHash = () => { if (location.hash === '#couverture') $('#couverture').open = true; };
  window.addEventListener('hashchange', revealHash); revealHash();
  // Attach handlers first, then reveal controls; a failure leaves readable HTML.
  document.documentElement.classList.add('js'); render();
})();
