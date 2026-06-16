/**
 * English Tutor Mini App — Exercises View
 * Supports gap_fill, choice, and translation exercise types.
 */

(function () {
  const { getExercise, checkExercise, navigate } = window.TutorApp;

  const EXERCISE_TYPES = [
    { id: 'gap_fill', label: 'Fill the Gap', icon: '✏️', desc: 'Type the missing word' },
    { id: 'choice', label: 'Multiple Choice', icon: '🎯', desc: 'Pick the best option' },
    { id: 'translation', label: 'Translation', icon: '🌍', desc: 'Translate the sentence' },
  ];

  const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1'];
  const TOPICS = [
    'daily_routine', 'work', 'travel', 'food', 'health',
    'education', 'shopping', 'family', 'entertainment', 'technology',
  ];

  let currentExercise = null;
  let currentType = 'gap_fill';
  let currentLevel = 'A1';
  let currentTopic = 'daily_routine';

  // ── Render ──────────────────────────────────────────
  function render(params) {
    // If a type is specified in params, go straight to exercise
    if (params && EXERCISE_TYPES.some(t => t.id === params)) {
      currentType = params;
      renderExerciseView();
      return;
    }
    renderMenu();
  }

  // ── Menu: pick type, level, topic ───────────────────
  function renderMenu() {
    const app = document.getElementById('app');
    app.innerHTML = `
      <div class="container">
        <div class="nav-bar">
          <button class="nav-btn" onclick="window.TutorApp.navigate('placement')">Placement</button>
          <button class="nav-btn" onclick="window.TutorApp.navigate('texts')">Texts</button>
          <button class="nav-btn active">Exercises</button>
        </div>

        <h1>Exercises</h1>
        <p>Choose an exercise type and settings to practice.</p>

        <div class="card">
          <h3>Exercise Type</h3>
          ${EXERCISE_TYPES.map(t => `
            <button class="choice-btn" data-type="${t.id}" onclick="window.TutorApp.navigate('exercises/${t.id}')">
              <strong>${t.icon} ${t.label}</strong><br>
              <small style="color:var(--hint)">${t.desc}</small>
            </button>
          `).join('')}
        </div>

        <div class="card">
          <div class="picker-group">
            <label class="picker-label">Level</label>
            <select class="picker" id="levelPicker">
              ${LEVELS.map(l => `<option value="${l}" ${l === currentLevel ? 'selected' : ''}>${l}</option>`).join('')}
            </select>
          </div>
          <div class="picker-group">
            <label class="picker-label">Topic</label>
            <select class="picker" id="topicPicker">
              ${TOPICS.map(t => `<option value="${t}" ${t === currentTopic ? 'selected' : ''}>${capitalize(t.replace('_', ' '))}</option>`).join('')}
            </select>
          </div>
        </div>

        <p class="text-center" style="color:var(--hint);font-size:13px">
          Pick a type above to start. Level & topic are saved for next time.
        </p>
      </div>
    `;

    document.getElementById('levelPicker').addEventListener('change', (e) => {
      currentLevel = e.target.value;
    });
    document.getElementById('topicPicker').addEventListener('change', (e) => {
      currentTopic = e.target.value;
    });
  }

  // ── Exercise view ───────────────────────────────────
  function renderExerciseView() {
    const app = document.getElementById('app');
    app.innerHTML = `
      <div class="container">
        <div class="nav-bar">
          <button class="nav-btn" onclick="window.TutorApp.navigate('placement')">Placement</button>
          <button class="nav-btn" onclick="window.TutorApp.navigate('texts')">Texts</button>
          <button class="nav-btn active" onclick="window.TutorApp.navigate('exercises')">Exercises</button>
        </div>

        <div id="exerciseHeader">
          <button class="btn btn-secondary" onclick="window.TutorApp.navigate('exercises')">← Back to Menu</button>
          <h2 class="mt-16" id="exerciseTitle">${getTypeLabel(currentType)}</h2>
          <p id="exerciseMeta">${currentLevel} · ${capitalize(currentTopic.replace('_', ' '))}</p>
        </div>

        <div id="exerciseLoading" class="loading">
          <div class="spinner"></div>
          <div>Generating exercise...</div>
        </div>

        <div id="exerciseContent" class="hidden"></div>
        <div id="exerciseFeedback" class="hidden"></div>

        <div id="exerciseActions" class="hidden mt-16">
          <button class="btn btn-primary" id="nextExerciseBtn">Next Exercise →</button>
        </div>
      </div>
    `;

    document.getElementById('nextExerciseBtn').addEventListener('click', () => {
      renderExerciseView();
    });

    loadExercise();
  }

  async function loadExercise() {
    try {
      const exercise = await getExercise(currentType, currentLevel, currentTopic);
      currentExercise = exercise;
      document.getElementById('exerciseLoading').classList.add('hidden');
      document.getElementById('exerciseContent').classList.remove('hidden');
      renderExercise(exercise);
    } catch (err) {
      document.getElementById('exerciseLoading').classList.add('hidden');
      document.getElementById('exerciseContent').classList.remove('hidden');
      document.getElementById('exerciseContent').innerHTML = `
        <div class="error">
          <p>${err.message}</p>
          <button class="btn btn-primary mt-16" onclick="window.TutorApp.navigate('exercises/${currentType}')">Retry</button>
        </div>
      `;
    }
  }

  function renderExercise(exercise) {
    const content = document.getElementById('exerciseContent');
    const feedback = document.getElementById('exerciseFeedback');
    const actions = document.getElementById('exerciseActions');

    feedback.classList.add('hidden');
    actions.classList.add('hidden');

    switch (exercise.type) {
      case 'gap_fill':
        renderGapFill(exercise, content);
        break;
      case 'choice':
        renderChoice(exercise, content);
        break;
      case 'translation':
        renderTranslation(exercise, content);
        break;
      default:
        content.innerHTML = `<p>Unknown exercise type: ${exercise.type}</p>`;
    }
  }

  // ── Gap Fill ────────────────────────────────────────
  function renderGapFill(exercise, container) {
    const prompt = exercise.prompt || '';
    const payload = exercise.payload || {};
    const sentence = payload.sentence || prompt;

    container.innerHTML = `
      <div class="prompt">${sentence}</div>
      <div class="picker-group">
        <label class="picker-label">Your answer</label>
        <input class="input" id="gapFillInput" type="text" placeholder="Type the missing word..." autocomplete="off">
      </div>
      <button class="btn btn-primary" id="checkGapFillBtn">Check ✓</button>
    `;

    document.getElementById('gapFillInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') checkGapFill();
    });
    document.getElementById('checkGapFillBtn').addEventListener('click', checkGapFill);
    document.getElementById('gapFillInput').focus();
  }

  async function checkGapFill() {
    const input = document.getElementById('gapFillInput');
    const answer = input.value.trim();
    if (!answer) return;

    const btn = document.getElementById('checkGapFillBtn');
    btn.disabled = true;
    btn.textContent = 'Checking...';

    try {
      const result = await checkExercise(currentExercise.exercise_id, answer);
      showFeedback(result);
    } catch (err) {
      showFeedback({ correct: false, expected: 'Error', explanation: err.message });
    } finally {
      btn.disabled = false;
      btn.textContent = 'Check ✓';
    }
  }

  // ── Choice ──────────────────────────────────────────
  function renderChoice(exercise, container) {
    const payload = exercise.payload || {};
    const choices = payload.choices || [];
    const sentence = payload.sentence || exercise.prompt || '';

    container.innerHTML = `
      <div class="prompt">${sentence}</div>
      <div id="choiceButtons">
        ${choices.map((c, i) => `
          <button class="choice-btn" data-index="${i}" data-value="${escapeHtml(c)}">
            ${c}
          </button>
        `).join('')}
      </div>
    `;

    document.querySelectorAll('#choiceButtons .choice-btn').forEach(btn => {
      btn.addEventListener('click', () => selectChoice(btn));
    });
  }

  function selectChoice(btn) {
    // Disable all buttons
    document.querySelectorAll('#choiceButtons .choice-btn').forEach(b => {
      b.disabled = true;
    });

    const answer = btn.dataset.value;
    checkChoice(answer);
  }

  async function checkChoice(answer) {
    try {
      const result = await checkExercise(currentExercise.exercise_id, answer);
      // Highlight correct/incorrect
      document.querySelectorAll('#choiceButtons .choice-btn').forEach(btn => {
        if (btn.dataset.value === result.expected) {
          btn.classList.add('correct');
        }
        if (btn.dataset.value === answer && !result.correct) {
          btn.classList.add('incorrect');
        }
      });
      showFeedback(result);
    } catch (err) {
      showFeedback({ correct: false, expected: 'Error', explanation: err.message });
    }
  }

  // ── Translation ─────────────────────────────────────
  function renderTranslation(exercise, container) {
    const prompt = exercise.prompt || '';
    const payload = exercise.payload || {};
    const sourceText = payload.source_text || payload.sentence || prompt;

    container.innerHTML = `
      <div class="prompt">${escapeHtml(sourceText)}</div>
      ${payload.hints ? `
        <p style="color:var(--hint);font-size:14px;margin-bottom:8px">
          💡 Hint: ${escapeHtml(payload.hints)}
        </p>
      ` : ''}
      <div class="picker-group">
        <label class="picker-label">Your translation</label>
        <input class="input" id="translationInput" type="text" placeholder="Type your translation..." autocomplete="off">
      </div>
      <button class="btn btn-primary" id="checkTranslationBtn">Check ✓</button>
    `;

    document.getElementById('translationInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') checkTranslation();
    });
    document.getElementById('checkTranslationBtn').addEventListener('click', checkTranslation);
    document.getElementById('translationInput').focus();
  }

  async function checkTranslation() {
    const input = document.getElementById('translationInput');
    const answer = input.value.trim();
    if (!answer) return;

    const btn = document.getElementById('checkTranslationBtn');
    btn.disabled = true;
    btn.textContent = 'Checking...';

    try {
      const result = await checkExercise(currentExercise.exercise_id, answer);
      showFeedback(result);
    } catch (err) {
      showFeedback({ correct: false, expected: 'Error', explanation: err.message });
    } finally {
      btn.disabled = false;
      btn.textContent = 'Check ✓';
    }
  }

  // ── Feedback ────────────────────────────────────────
  function showFeedback(result) {
    const feedback = document.getElementById('exerciseFeedback');
    const actions = document.getElementById('exerciseActions');

    feedback.classList.remove('hidden');
    feedback.className = 'feedback ' + (result.correct ? 'correct' : 'incorrect');
    feedback.innerHTML = `
      <h4>${result.correct ? '✅ Correct!' : '❌ Not quite'}</h4>
      ${!result.correct ? `<p><strong>Expected:</strong> ${escapeHtml(result.expected)}</p>` : ''}
      ${result.explanation ? `<div class="explanation">${escapeHtml(result.explanation)}</div>` : ''}
    `;

    actions.classList.remove('hidden');
  }

  // ── Helpers ─────────────────────────────────────────
  function getTypeLabel(type) {
    const t = EXERCISE_TYPES.find(x => x.id === type);
    return t ? `${t.icon} ${t.label}` : type;
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  // ── Register route ─────────────────────────────────
  window.TutorApp.registerRoute('exercises', render);
})();