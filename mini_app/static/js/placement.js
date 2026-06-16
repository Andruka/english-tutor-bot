/**
 * English Tutor Mini App — Placement Test View
 * Ported from the original index.html into the SPA module system.
 */

(function () {
  const { getPlacementQuestions, submitPlacement, navigate } = window.TutorApp;

  // ── State ──────────────────────────────────────────
  let state = {
    questions: [],
    sessionId: null,
    currentIndex: 0,
    answers: {},
    result: null,
  };

  // ── Helpers ─────────────────────────────────────────
  function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ── Render ──────────────────────────────────────────
  function render() {
    const app = document.getElementById('app');
    app.innerHTML = `
      <div id="placementLoading" class="loading">
        <div class="spinner"></div>
        <div>Loading questions...</div>
      </div>

      <div id="placementQuestionView" class="hidden">
        <div class="header">
          <h2>Placement Test</h2>
          <span class="progress" id="progressText">0/0</span>
        </div>
        <div class="progress-bar"><div class="progress-fill" id="progressFill" style="width:0%"></div></div>
        <div class="question-card">
          <div class="question-level" id="questionLevel"></div>
          <div class="question-prompt" id="questionPrompt"></div>
          <div id="feedback" class="hidden"></div>
          <div class="choices" id="choices"></div>
        </div>
        <div class="nav" id="nav">
          <button class="btn secondary hidden" id="prevBtn">← Back</button>
          <button class="btn primary" id="nextBtn" disabled>Next →</button>
        </div>
      </div>

      <div id="placementResultView" class="hidden">
        <div class="result-card">
          <h2>Test Complete! 🎉</h2>
          <div class="result-level" id="resultLevel"></div>
          <div class="result-score" id="resultScore"></div>
          <div class="result-breakdown" id="resultBreakdown"></div>
          <button class="btn primary" id="saveResultBtn" style="margin-top:24px">Save & Close</button>
          <button class="btn btn-secondary mt-8" onclick="window.TutorApp.navigate('exercises')">Start Exercises</button>
        </div>
      </div>

      <div id="placementError" class="error hidden">
        <p id="errorMessage"></p>
        <button class="btn primary" onclick="window.TutorApp.navigate('placement')">Retry</button>
      </div>
    `;

    // Wire up event listeners
    document.getElementById('prevBtn').addEventListener('click', prevQuestion);
    document.getElementById('nextBtn').addEventListener('click', nextQuestion);
    document.getElementById('saveResultBtn').addEventListener('click', sendResult);

    loadQuestions();
  }

  // ── Load questions ──────────────────────────────────
  async function loadQuestions() {
    try {
      const data = await getPlacementQuestions();
      state.sessionId = data.session_id;
      state.questions = data.questions;
      state.answers = {};
      state.currentIndex = 0;
      document.getElementById('placementLoading').classList.add('hidden');
      document.getElementById('placementQuestionView').classList.remove('hidden');
      renderQuestion();
    } catch (err) {
      document.getElementById('placementLoading').classList.add('hidden');
      showError(err.message);
    }
  }

  function showError(msg) {
    document.getElementById('errorMessage').textContent = msg;
    document.getElementById('placementError').classList.remove('hidden');
  }

  // ── Render question ─────────────────────────────────
  function renderQuestion() {
    const q = state.questions[state.currentIndex];
    if (!q) return;

    const total = state.questions.length;
    const idx = state.currentIndex;

    document.getElementById('progressText').textContent = `${idx + 1}/${total}`;
    document.getElementById('progressFill').style.width = `${((idx + 1) / total) * 100}%`;
    document.getElementById('questionLevel').textContent = `Level ${q.level.toUpperCase()} · ${capitalize(q.type.replace('_', ' '))}`;
    document.getElementById('questionPrompt').innerHTML = q.prompt;

    const choicesEl = document.getElementById('choices');
    choicesEl.innerHTML = '';
    const savedAnswer = state.answers[q.question_id];

    const choices = shuffle([...q.choices]);
    if (!q._shuffled) q._shuffled = choices;

    q._shuffled.forEach((choice) => {
      const btn = document.createElement('button');
      btn.className = 'choice-btn' + (savedAnswer === choice ? ' selected' : '');
      btn.textContent = choice;
      btn.onclick = () => selectChoice(q.question_id, choice);
      choicesEl.appendChild(btn);
    });

    document.getElementById('feedback').classList.add('hidden');
    updateNav();
  }

  function selectChoice(questionId, choice) {
    state.answers[questionId] = choice;
    document.querySelectorAll('.choice-btn').forEach((btn) => {
      btn.classList.toggle('selected', btn.textContent === choice);
    });
    document.getElementById('nextBtn').disabled = false;
  }

  function updateNav() {
    const total = state.questions.length;
    const idx = state.currentIndex;
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const q = state.questions[idx];

    prevBtn.classList.toggle('hidden', idx === 0);
    const answered = !!state.answers[q?.question_id];
    nextBtn.textContent = idx === total - 1 ? 'Submit ✓' : 'Next →';
    nextBtn.disabled = !answered;
  }

  function nextQuestion() {
    const total = state.questions.length;
    const idx = state.currentIndex;
    const q = state.questions[idx];

    if (!state.answers[q.question_id]) return;

    if (idx === total - 1) {
      submitTest();
      return;
    }

    state.currentIndex++;
    renderQuestion();
  }

  function prevQuestion() {
    if (state.currentIndex > 0) {
      state.currentIndex--;
      renderQuestion();
    }
  }

  // ── Submit ──────────────────────────────────────────
  async function submitTest() {
    const nextBtn = document.getElementById('nextBtn');
    nextBtn.disabled = true;
    nextBtn.textContent = 'Saving...';

    try {
      const result = await submitPlacement(state.sessionId, state.answers);
      state.result = result;
      showResult();
    } catch (err) {
      nextBtn.disabled = false;
      nextBtn.textContent = 'Retry';
      showError(err.message);
    }
  }

  function showResult() {
    const r = state.result;
    document.getElementById('placementQuestionView').classList.add('hidden');
    document.getElementById('placementResultView').classList.remove('hidden');
    document.getElementById('resultLevel').textContent = r.estimated_level;
    document.getElementById('resultScore').textContent = `${r.correct_answers}/${r.total_questions} correct (${r.score}%)`;

    const breakdownEl = document.getElementById('resultBreakdown');
    breakdownEl.innerHTML = '';
    const levels = Object.entries(r.level_breakdown || {});
    if (levels.length) {
      const h3 = document.createElement('h3');
      h3.textContent = 'Level Breakdown';
      breakdownEl.appendChild(h3);
      levels.forEach(([level, data]) => {
        const row = document.createElement('div');
        row.className = 'level-row';
        row.innerHTML = `<span>${level}</span>
          <div class="bar-wrap"><div class="bar" style="width:${data.score}%"></div></div>
          <span>${data.correct}/${data.total}</span>`;
        breakdownEl.appendChild(row);
      });
    }
  }

  function sendResult() {
    const tg = window.Telegram?.WebApp;
    if (!tg) {
      alert(`Level: ${state.result.estimated_level}\nScore: ${state.result.score}%`);
      return;
    }
    tg.sendData(JSON.stringify({
      session_id: state.sessionId,
      level: state.result.estimated_level,
      score: state.result.score,
    }));
    tg.close();
  }

  // ── Register route ─────────────────────────────────
  window.TutorApp.registerRoute('placement', render);
})();