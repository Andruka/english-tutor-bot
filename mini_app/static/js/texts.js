/**
 * English Tutor Mini App — Reading Library View
 * Routes: texts, texts/level/A1, texts/cat/daily_life, texts/read/1, texts/progress
 */
(function () {
  const {
    getTextCatalog, listTexts, getText, startReading,
    completeReading, getTextProgress, navigate,
  } = window.TutorApp;

  // ── Labels ──────────────────────────────────────────
  const LEVEL_LABELS = { A1: 'Beginner', A2: 'Elementary', B1: 'Intermediate', B2: 'Upper Int.', C1: 'Advanced', C2: 'Proficient' };
  const STATUS_LABELS = { started: '📖 Reading', completed: '✅ Read' };

  // ── Cached catalog ──────────────────────────────────
  let catalogCache = null;

  async function getCatalog() {
    if (catalogCache) return catalogCache;
    catalogCache = await getTextCatalog();
    return catalogCache;
  }

  // ── Router handler ──────────────────────────────────
  async function render(params) {
    showLoading();
    try {
      if (!params) { await renderCatalog(); return; }
      const parts = params.split('/');
      if (parts[0] === 'level') { await renderList('level', parts[1]); return; }
      if (parts[0] === 'cat')   { await renderList('category', parts[1]); return; }
      if (parts[0] === 'read')  { await renderReader(parseInt(parts[1], 10)); return; }
      if (parts[0] === 'progress') { await renderProgress(); return; }
      await renderCatalog();
    } catch (e) {
      showError(e.message);
    }
  }

  // ── Catalog: levels + categories ────────────────────
  async function renderCatalog() {
    const cat = await getCatalog();
    const app = document.getElementById('app');
    app.innerHTML = `
      <div class="container">
        <div class="nav-bar">
          <button class="nav-btn" onclick="window.TutorApp.navigate('placement')">Placement</button>
          <button class="nav-btn active">Texts</button>
          <button class="nav-btn" onclick="window.TutorApp.navigate('exercises')">Exercises</button>
        </div>

        <h1>Reading Library</h1>
        <p>Read texts at your level and learn new words.</p>

        <h2>By Level</h2>
        <div class="texts-grid">
          ${(cat.levels || []).map(l => `
            <div class="card texts-grid-card" onclick="window.TutorApp.navigate('texts/level/${l.level}')">
              <strong>${LEVEL_LABELS[l.level] || l.level}</strong>
              <div style="font-size:12px;color:var(--tg-theme-hint-color,#888);margin-top:4px">${l.count} texts</div>
            </div>
          `).join('')}
        </div>

        <h2>By Category</h2>
        <div class="texts-grid">
          ${(cat.categories || []).map(c => `
            <div class="card texts-grid-card" onclick="window.TutorApp.navigate('texts/cat/${c.category}')">
              <strong>${c.label || c.category}</strong>
              <div style="font-size:12px;color:var(--tg-theme-hint-color,#888);margin-top:4px">${c.count} texts</div>
            </div>
          `).join('')}
        </div>

        <div style="margin-top:12px">
          <button class="btn btn-outline" onclick="window.TutorApp.navigate('texts/progress')">📊 My Progress</button>
        </div>
      </div>
    `;
  }

  // ── List texts by level or category ─────────────────
  async function renderList(filterBy, filterVal) {
    const data = await listTexts(
      filterBy === 'level' ? filterVal : '',
      filterBy === 'category' ? filterVal : ''
    );
    const texts = data.texts || [];
    const cat = await getCatalog();
    const label = filterBy === 'level'
      ? (LEVEL_LABELS[filterVal] || filterVal)
      : ((cat.categories || []).find(c => c.category === filterVal)?.label || filterVal);

    const app = document.getElementById('app');
    app.innerHTML = `
      <div class="container">
        <button class="btn btn-secondary" onclick="window.TutorApp.navigate('texts')" style="margin-bottom:12px">← Back to Library</button>
        <h1>${label}</h1>
        <p>${texts.length} text${texts.length !== 1 ? 's' : ''} found</p>
        ${texts.length === 0 ? '<div class="card"><p>No texts found for this filter.</p></div>' : `
          <div class="texts-text-list">
            ${texts.map(t => {
              const statusIcon = t.status === 'completed' ? '✅' : t.status === 'started' ? '📖' : '';
              const progressPct = t.paragraph_count > 0 ? Math.round((t.words_learned / Math.max(t.paragraph_count, 1)) * 100) : 0;
              return `
                <div class="card texts-text-card" onclick="window.TutorApp.navigate('texts/read/${t.id}')">
                  <div class="texts-text-card-header">
                    ${statusIcon ? `<span class="texts-status-icon">${statusIcon}</span>` : ''}
                    <strong style="flex:1">${escHtml(t.title)}</strong>
                  </div>
                  <div class="texts-text-card-meta">
                    <span class="badge badge-level">${t.level}</span>
                    <span class="badge badge-cat">${escHtml(t.category_label || t.category)}</span>
                    <span>${t.word_count} words</span>
                    ${t.status === 'started' ? `<span>📖 ${progressPct}%</span>` : ''}
                  </div>
                  ${t.status === 'started' ? `
                    <div class="texts-progress-bar"><div class="texts-progress-fill" style="width:${progressPct}%"></div></div>
                  ` : ''}
                  ${t.status === 'completed' ? `
                    <div class="texts-progress-bar"><div class="texts-progress-fill full"></div></div>
                  ` : ''}
                </div>
              `;
            }).join('')}
          </div>
        `}
      </div>
    `;
  }

  // ── Text reader ─────────────────────────────────────
  async function renderReader(textId) {
    const { text, progress, paragraphs, bookmark } = await getText(textId);
    const isStarted = progress && progress.status === 'started';
    const isCompleted = progress && progress.status === 'completed';

    const app = document.getElementById('app');
    app.innerHTML = `
      <div class="container">
        <button class="btn btn-secondary" onclick="window.TutorApp.navigate('texts')" style="margin-bottom:12px">← Back to Library</button>

        <div class="card texts-reader-header">
          <h1>${escHtml(text.title)}</h1>
          <div class="texts-reader-meta">
            <span class="badge badge-level">${text.level}</span>
            <span class="badge badge-cat">${escHtml(text.category_label || text.category)}</span>
            <span>${text.word_count} words</span>
            ${text.author ? `<span>✍️ ${escHtml(text.author)}</span>` : ''}
          </div>
          ${isCompleted ? '<div style="margin-top:8px;color:var(--accent);font-weight:600">✅ Completed</div>' : ''}
          ${isStarted ? '<div style="margin-top:8px;color:var(--tg-theme-link-color,#2481cc);font-weight:600">📖 Reading in progress</div>' : ''}
        </div>

        <div class="card texts-reader-content">
          ${paragraphs.map((p, i) => `
            <div class="texts-paragraph" id="para-${i}">
              ${escHtml(p)}
              ${bookmark && bookmark.paragraph_index === i ? '<span class="bookmark-marker">🔖</span>' : ''}
            </div>
          `).join('')}
        </div>

        <div class="texts-reader-actions">
          ${!isStarted && !isCompleted ? `
            <button class="btn btn-primary" id="btn-start-reading">📖 Start Reading</button>
          ` : ''}
          ${isStarted && !isCompleted ? `
            <button class="btn btn-success" id="btn-complete-reading">✅ Mark as Read</button>
          ` : ''}
          ${isCompleted ? `
            <button class="btn btn-outline" id="btn-restart-reading">🔄 Read Again</button>
          ` : ''}
        </div>

        ${isCompleted || isStarted ? `
          <div style="margin-top:8px">
            <button class="btn btn-secondary" onclick="window.TutorApp.navigate('texts/progress')">📊 My Progress</button>
          </div>
        ` : ''}
      </div>
    `;

    // Bind buttons
    const startBtn = document.getElementById('btn-start-reading');
    const completeBtn = document.getElementById('btn-complete-reading');
    const restartBtn = document.getElementById('btn-restart-reading');

    if (startBtn) {
      startBtn.addEventListener('click', async () => {
        await startReading(textId);
        renderReader(textId);
      });
    }
    if (completeBtn) {
      completeBtn.addEventListener('click', async () => {
        await completeReading(textId);
        renderReader(textId);
      });
    }
    if (restartBtn) {
      restartBtn.addEventListener('click', async () => {
        await startReading(textId);
        renderReader(textId);
      });
    }
  }

  // ── Progress stats ──────────────────────────────────
  async function renderProgress() {
    const stats = await getTextProgress();
    const app = document.getElementById('app');
    app.innerHTML = `
      <div class="container">
        <button class="btn btn-secondary" onclick="window.TutorApp.navigate('texts')" style="margin-bottom:12px">← Back to Library</button>
        <h1>📊 My Progress</h1>

        <div class="texts-stats-grid">
          <div class="card texts-stat-card">
            <div class="texts-stat-num">${stats.started || 0}</div>
            <div class="texts-stat-label">Started</div>
          </div>
          <div class="card texts-stat-card">
            <div class="texts-stat-num">${stats.completed || 0}</div>
            <div class="texts-stat-label">Completed</div>
          </div>
          <div class="card texts-stat-card">
            <div class="texts-stat-num">${stats.total_texts || 0}</div>
            <div class="texts-stat-label">Total Texts</div>
          </div>
          <div class="card texts-stat-card">
            <div class="texts-stat-num">${Math.round((stats.completion_rate || 0) * 100)}%</div>
            <div class="texts-stat-label">Completion</div>
          </div>
        </div>

        <div class="card" style="margin-bottom:16px">
          <h3>Words Learned</h3>
          <div class="texts-stat-num" style="font-size:40px;margin:8px 0">${stats.words_learned || 0}</div>
        </div>

        <h2>🔖 Bookmarks</h2>
        ${!stats.bookmarks || stats.bookmarks.length === 0
          ? '<div class="card"><p>No bookmarks yet.</p></div>'
          : `<div class="texts-bookmark-list">
              ${stats.bookmarks.map(bm => `
                <div class="card texts-bookmark-card" onclick="window.TutorApp.navigate('texts/read/${bm.text_id}')">
                  <strong>${escHtml(bm.text_title)}</strong>
                  <div style="font-size:12px;color:var(--tg-theme-hint-color,#888);margin-top:4px">
                    Paragraph ${bm.paragraph_index + 1} ${bm.note ? '— ' + escHtml(bm.note) : ''}
                  </div>
                </div>
              `).join('')}
            </div>`
        }
      </div>
    `;
  }

  // ── Helpers ─────────────────────────────────────────
  function showLoading() {
    document.getElementById('app').innerHTML = `
      <div class="loading">
        <div class="spinner"></div>
        <div>Loading...</div>
      </div>
    `;
  }

  function showError(msg) {
    document.getElementById('app').innerHTML = `
      <div class="container">
        <div class="card" style="text-align:center;padding:40px 20px">
          <div style="font-size:48px;margin-bottom:16px">⚠️</div>
          <h2>Something went wrong</h2>
          <p>${escHtml(msg)}</p>
          <button class="btn btn-primary" onclick="window.TutorApp.navigate('texts')">Try Again</button>
        </div>
      </div>
    `;
  }

  function escHtml(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }

  // ── Register route ──────────────────────────────────
  window.TutorApp.registerRoute('texts', render);
})();
