/* Progressive enhancement only. All source reading works without JavaScript. */
(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const all = (selector) => [...document.querySelectorAll(selector)];
  const KEY = 'vigie.resident.v1';
  const fold = (text) => String(text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const rows = all('.story');
  let view = 'brief', topic = 'all', limit = 6, timer;
  let state = { saved: [], seen: null, visited: null };
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null');
    const validIds = (ids) => Array.isArray(ids) ? [...new Set(ids.filter(x => typeof x === 'string' && /^[a-f0-9]{20}$/.test(x)))].slice(0, 1200) : [];
    if (raw && typeof raw === 'object') state = { saved: validIds(raw.saved), seen: Array.isArray(raw.seen) ? validIds(raw.seen) : null, visited: typeof raw.visited === 'string' && Number.isFinite(Date.parse(raw.visited)) ? raw.visited : null };
  } catch { /* Reading remains usable when browser storage is unavailable. */ }
  const toast = (text) => { $('#toast').textContent = text; clearTimeout(timer); timer = setTimeout(() => { $('#toast').textContent = ''; }, 5000); };
  const persist = () => {
    try { localStorage.setItem(KEY, JSON.stringify(state)); return true; }
    catch { toast('Stockage indisponible : vos repères resteront seulement pendant cette visite.'); return false; }
  };
  const dateText = (value) => new Intl.DateTimeFormat('fr-CA', { timeZone:'America/Toronto', day:'numeric', month:'short', hour:'2-digit', minute:'2-digit' }).format(new Date(value));
  all('time[datetime]').forEach(el => { if (Number.isFinite(Date.parse(el.dateTime))) { el.textContent = dateText(el.dateTime); el.title = 'Heure de Québec · ' + el.dateTime; } });
  const freshness = () => {
    const label = $('#freshness-label');
    const date = Date.parse(label.dataset.fetched);
    const age = Date.now() - date;
    const stale = !Number.isFinite(date) || age > 6 * 3600 * 1000 || age < -300000;
    label.classList.toggle('warning', stale || label.dataset.partial === 'true');
    label.textContent = !Number(label.dataset.total) ? 'État des sources inconnu' : !Number(label.dataset.ok) ? 'Collecte indisponible' : stale ? 'Collecte à actualiser' : label.dataset.partial === 'true' ? 'Collecte partielle' : 'Dernière collecte';
  };
  freshness();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) freshness(); });
  setInterval(freshness, 60000);
  const isNew = row => state.seen !== null && !state.seen.includes(row.dataset.id);
  function render() {
    const terms = fold($('#search').value.trim()).split(/\s+/).filter(Boolean);
    const scope = $('#scope').value, area = $('#area').value;
    const matches = rows.filter(row => {
      const d = row.dataset;
      const scopeMatch = scope === 'all' || d.geo === 'quebec-city' || (scope === 'province' && d.geo === 'quebec');
      return scopeMatch && (area === 'all' || d.areas.split(' ').includes(area))
        && (topic === 'all' || d.topics.split(' ').includes(topic))
        && terms.every(t => d.search.includes(t))
        && (view !== 'saved' || state.saved.includes(d.id)) && (view !== 'new' || isNew(row));
    });
    const visible = new Set(matches.slice(0, limit));
    rows.forEach(row => {
      row.hidden = !visible.has(row);
      row.querySelector('.new-label').hidden = !isNew(row);
      const saved = state.saved.includes(row.dataset.id), button = row.querySelector('[data-save]');
      button.setAttribute('aria-pressed', String(saved));
      button.textContent = saved ? 'Gardé ✓' : 'Garder ＋';
      button.setAttribute('aria-label', (saved ? 'Retirer : ' : 'Garder : ') + row.querySelector('h3').textContent.trim());
    });
    all('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
    all('[data-topic]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.topic === topic)));
    $('#result-count').textContent = `${Math.min(limit, matches.length)} sur ${matches.length} articles dans cette vue`;
    $('#no-results').hidden = matches.length > 0;
    $('#show-more').hidden = matches.length <= limit;
    $('#end-note').textContent = matches.length > limit ? 'Un premier point. La suite, si vous en avez besoin.' : matches.length ? 'Vous avez fait le tour de cette sélection.' : 'Élargissez votre regard.';
    $('#saved-count').textContent = state.saved.length ? `(${state.saved.length})` : '';
    const newCount = rows.filter(isNew).length;
    $('#new-count').textContent = state.seen !== null ? `(${newCount})` : '';
    const missingSaved = state.saved.filter(id => !rows.some(r => r.dataset.id === id)).length;
    $('#visit-status').textContent = view === 'saved' && missingSaved
      ? `${missingSaved} article(s) gardé(s) ne figurent plus dans cette collecte. Les repères sont conservés.`
      : state.visited ? `${newCount} article(s) apparu(s) dans les flux depuis votre repère du ${dateText(state.visited)}. Ce n’est pas un suivi des modifications.`
      : 'Mémorisez votre point de lecture pour voir les nouveaux articles à votre prochaine visite.';
    if (view === 'new' && state.seen === null) $('#visit-status').textContent = 'Créez d’abord un repère avec « Mémoriser ce point de lecture ».';
  }
  function reset() { topic = 'all'; view = 'brief'; limit = 6; $('#search').value = ''; $('#scope').value = 'local'; $('#area').value = 'all'; render(); }
  all('[data-view]').forEach(b => b.addEventListener('click', () => { view = b.dataset.view; limit = 6; if (view === 'saved' || view === 'new') { $('#scope').value = 'all'; $('#area').value = 'all'; $('#search').value = ''; topic = 'all'; } else { $('#scope').value = 'local'; } render(); }));
  all('[data-topic]').forEach(b => b.addEventListener('click', () => { topic = b.dataset.topic; limit = 6; render(); }));
  $('#search').addEventListener('input', () => { limit = 6; render(); });
  ['#scope', '#area'].forEach(s => $(s).addEventListener('change', () => { limit = 6; render(); }));
  ['#reset-filters', '#empty-reset'].forEach(s => $(s).addEventListener('click', reset));
  $('#show-more').addEventListener('click', () => { limit += 6; render(); });
  all('[data-save]').forEach(b => b.addEventListener('click', () => {
    const id = b.dataset.save;
    if (state.saved.includes(id)) state.saved = state.saved.filter(x => x !== id);
    else { if (state.saved.length >= 1200) { toast('La limite de 1 200 repères est atteinte. Retirez-en pour en garder de nouveaux.'); return; } state.saved.push(id); }
    persist(); render();
  }));
  $('#remember').addEventListener('click', () => {
    state.seen = rows.map(r => r.dataset.id).slice(0, 1200); state.visited = new Date().toISOString();
    const stored = persist(); render(); if (stored) toast('Point de lecture mémorisé sur cet appareil.');
  });
  $('#clear-local').addEventListener('click', () => {
    let cleared = true;
    try { [KEY, 'vigie_facets_v1', 'vigie_visit_v1'].forEach(k => localStorage.removeItem(k)); } catch { cleared = false; }
    state = { saved: [], seen: null, visited: null }; reset();
    $('#privacy-status').textContent = cleared ? 'Vos repères Vigie ont été effacés de cet appareil.' : 'L’accès au stockage est bloqué. Les repères de cette visite ont été effacés.';
  });
  // Hash links to disclosures must open the disclosure, including direct URLs.
  const revealHash = () => { if (location.hash === '#couverture') $('#couverture').open = true; };
  window.addEventListener('hashchange', revealHash); revealHash();
  // Attach handlers first, then reveal controls; a failure leaves readable HTML.
  document.documentElement.classList.add('js'); render();
})();
