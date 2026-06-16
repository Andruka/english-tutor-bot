/**
 * English Tutor Mini App — Router & API Client
 * Hash-based SPA router with Telegram WebApp integration.
 */

// ── Telegram WebApp ──────────────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.expand();
  tg.ready();
}

function getInitData() {
  return tg?.initData || '';
}

// ── API Client ───────────────────────────────────────────────
const API_BASE = '';

async function apiFetch(path, options = {}) {
  const headers = {
    'X-Telegram-Init-Data': getInitData(),
    ...options.headers,
  };
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail || res.statusText;
    throw new Error(detail);
  }
  return res.json();
}

// Placement
function getPlacementQuestions() {
  return apiFetch('/api/placement/questions');
}
function submitPlacement(sessionId, answers) {
  return apiFetch('/api/placement/submit', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, answers }),
  });
}

// Exercises
function getExercise(type, level, topic) {
  const params = new URLSearchParams({ exercise_type: type, level, topic });
  return apiFetch(`/api/exercises?${params}`);
}
function checkExercise(exerciseId, answer) {
  return apiFetch('/api/exercises/check', {
    method: 'POST',
    body: JSON.stringify({ exercise_id: exerciseId, answer }),
  });
}

// Texts
function getTextCatalog()     { return apiFetch('/api/texts/catalog'); }
function listTexts(level, cat) {
  const params = new URLSearchParams();
  if (level) params.set('level', level);
  if (cat) params.set('category', cat);
  return apiFetch(`/api/texts?${params}`);
}
function getText(id)           { return apiFetch(`/api/texts/${id}`); }
function startReading(id)      { return apiFetch(`/api/texts/${id}/start`, { method: 'POST' }); }
function completeReading(id)   { return apiFetch(`/api/texts/${id}/complete`, { method: 'POST' }); }
function getTextProgress()     { return apiFetch('/api/texts/progress'); }

// ── Router ───────────────────────────────────────────────────
const routes = {};

function registerRoute(hash, handler) {
  routes[hash] = handler;
}

function navigate(hash) {
  window.location.hash = hash;
}

function getCurrentRoute() {
  const hash = window.location.hash.slice(1) || 'placement';
  // Support nested routes like exercises/gap_fill
  for (const [pattern, handler] of Object.entries(routes)) {
    if (hash === pattern || hash.startsWith(pattern + '/')) {
      const rest = hash.slice(pattern.length + 1);
      return { handler, params: rest };
    }
  }
  // Fallback to exact match
  const handler = routes[hash];
  if (handler) return { handler, params: '' };
  // Default to placement
  return { handler: routes['placement'], params: '' };
}

function router() {
  const { handler, params } = getCurrentRoute();
  if (handler) handler(params);
}

// ── Init ─────────────────────────────────────────────────────
window.addEventListener('hashchange', router);
window.addEventListener('DOMContentLoaded', () => {
  if (!window.location.hash) {
    window.location.hash = 'placement';
  }
  router();
});

// ── Exports (global for inline scripts) ──────────────────────
window.TutorApp = {
  tg,
  getInitData,
  apiFetch,
  getPlacementQuestions,
  submitPlacement,
  getExercise,
  checkExercise,
  getTextCatalog,
  listTexts,
  getText,
  startReading,
  completeReading,
  getTextProgress,
  navigate,
  registerRoute,
  router,
};