// =====================
// Constants
// =====================
const DAY_ORDER = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
const CORE_DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI'];
let rowIdCounter = 0;

// Inline SVG icons -- no emoji/dingbat glyphs anywhere in the UI.
const ICON_FILE = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="14" rx="1"/><circle cx="9" cy="10" r="2"/><path d="M21 15l-5-4-9 7"/></svg>';
const ICON_CLOSE = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>';
const ICON_UNDO = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 10h9a5 5 0 0 1 0 10H8"/><path d="M4 10l4-4M4 10l4 4"/></svg>';
const ICON_INFO = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><circle cx="12" cy="16.2" r="0.4" fill="currentColor"/></svg>';

// =====================
// State
// =====================
let uploadedFiles = [];      // [{file, groupLabel}]
let reviewRows = [];         // [{id, course_name, course_code, course_type, instructor_name, day, time_start, time_end, group_number}]
let selectedCourses = new Set();
let preferredSections = new Set();   // "CODE|GROUP"
let blockedSections = new Set();     // "CODE|GROUP"
let preferredInstructors = new Set();
let blockedDays = new Set();
let freeDays = new Set();
let lastResults = [];
let activeResultIndex = 0;
let currentSuggestions = [];  // AI reconciliation suggestions not yet applied

// =====================
// Step 1: Upload
// =====================
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');

uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', (e) => addFiles(e.target.files));

function addFiles(fileList) {
  for (const f of fileList) {
    if (f.type.startsWith('image/')) uploadedFiles.push({ file: f, groupLabel: '' });
  }
  renderFileList();
}

function removeFile(index) {
  uploadedFiles.splice(index, 1);
  renderFileList();
}

function updateFileLabel(index, value) {
  uploadedFiles[index].groupLabel = value;
}

function renderFileList() {
  const el = document.getElementById('file-list');
  el.innerHTML = uploadedFiles.map((entry, i) => `
    <div class="file-chip">
      <span style="display:flex;align-items:center;gap:8px">${ICON_FILE} ${esc(entry.file.name)}</span>
      <input class="group-label-input" placeholder="Group (e.g. G1)" value="${esc(entry.groupLabel)}"
             oninput="updateFileLabel(${i}, this.value)"/>
      <button onclick="removeFile(${i})" aria-label="Remove">${ICON_CLOSE}</button>
    </div>
  `).join('');
  document.getElementById('extract-btn').disabled = uploadedFiles.length === 0;
}

async function extractPhotos() {
  if (!uploadedFiles.length) return;
  const btn = document.getElementById('extract-btn');
  const loading = document.getElementById('extract-loading');
  hideError('upload-error');
  btn.disabled = true;
  loading.classList.add('show');

  const formData = new FormData();
  uploadedFiles.forEach((entry) => formData.append('files', entry.file));
  formData.append('group_labels', JSON.stringify(uploadedFiles.map((entry) => entry.groupLabel)));

  try {
    const res = await fetch('/api/extract', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(Array.isArray(data.detail) ? data.detail.join('; ') : (data.detail || 'Extraction failed.'));
    }

    reviewRows = data.classes.map((c) => ({ id: rowIdCounter++, ...c }));

    const warnBox = document.getElementById('extract-warnings');
    if (data.warnings && data.warnings.length) {
      warnBox.classList.add('show');
      warnBox.innerHTML = `<span class="alert-icon">${ICON_INFO}</span><span style="flex:1">` +
        data.warnings.map((w) => `${esc(w.filename)}: ${esc(w.message)}`).join('<br>') + '</span>';
    } else {
      warnBox.classList.remove('show');
    }

    renderReconcileNote(data.reconcile_note);

    currentSuggestions = data.suggestions || [];
    renderSuggestions();
    renderReviewTable();
    document.getElementById('review-section').style.display = 'block';
    setStep(2);
  } catch (err) {
    showError('upload-error', err.message);
  } finally {
    btn.disabled = false;
    loading.classList.remove('show');
  }
}

// =====================
// Step 2: Review / edit extracted data
// =====================
function renderReviewTable() {
  const tbody = document.getElementById('review-tbody');
  tbody.innerHTML = reviewRows.map((row) => `
    <tr data-id="${row.id}">
      <td class="${row.original_course_name ? 'ai-corrected' : ''}">
        <input value="${esc(row.course_name)}" oninput="updateRow(${row.id},'course_name',this.value)"/>
      </td>
      <td class="${row.original_course_code ? 'ai-corrected' : ''}">
        <input value="${esc(row.course_code)}" oninput="updateRow(${row.id},'course_code',this.value)"/>
        ${row.original_course_code ? `<button class="undo-btn" title="AI-corrected from '${esc(row.original_course_code)}' — click to undo" onclick="undoCorrection(${row.id},'course')">${ICON_UNDO}</button>` : ''}
      </td>
      <td><input value="${esc(row.course_type || '')}" oninput="updateRow(${row.id},'course_type',this.value)"/></td>
      <td class="${row.original_instructor_name ? 'ai-corrected' : ''}">
        <input value="${esc(row.instructor_name || '')}" oninput="updateRow(${row.id},'instructor_name',this.value)"/>
        ${row.original_instructor_name ? `<button class="undo-btn" title="AI-corrected from '${esc(row.original_instructor_name)}' — click to undo" onclick="undoCorrection(${row.id},'instructor')">${ICON_UNDO}</button>` : ''}
      </td>
      <td>
        <select onchange="updateRow(${row.id},'day',this.value)">
          ${DAY_ORDER.map((d) => `<option value="${d}" ${row.day === d ? 'selected' : ''}>${d}</option>`).join('')}
        </select>
      </td>
      <td><input type="time" value="${esc(row.time_start)}" oninput="updateRow(${row.id},'time_start',this.value)"/></td>
      <td><input type="time" value="${esc(row.time_end)}" oninput="updateRow(${row.id},'time_end',this.value)"/></td>
      <td><input value="${esc(row.group_number)}" oninput="updateRow(${row.id},'group_number',this.value)"/></td>
      <td><button class="row-delete" onclick="deleteRow(${row.id})">${ICON_CLOSE}</button></td>
    </tr>
  `).join('');
}

function updateRow(id, field, value) {
  const row = reviewRows.find((r) => r.id === id);
  if (row) row[field] = value;
}

function deleteRow(id) {
  reviewRows = reviewRows.filter((r) => r.id !== id);
  renderReviewTable();
}

function undoCorrection(id, field) {
  const row = reviewRows.find((r) => r.id === id);
  if (!row) return;
  if (field === 'course') {
    if (row.original_course_code) row.course_code = row.original_course_code;
    if (row.original_course_name) row.course_name = row.original_course_name;
    row.original_course_code = null;
    row.original_course_name = null;
  } else if (field === 'instructor') {
    if (row.original_instructor_name) row.instructor_name = row.original_instructor_name;
    row.original_instructor_name = null;
  }
  renderReviewTable();
}

// =====================
// Reconciliation skipped notice + manual retry
// =====================
function renderReconcileNote(note) {
  const box = document.getElementById('reconcile-note');
  if (note) {
    box.classList.add('show');
    document.getElementById('reconcile-note-icon').innerHTML = ICON_INFO;
    document.getElementById('reconcile-note-text').textContent = note;
  } else {
    box.classList.remove('show');
  }
}

async function retryReconcile() {
  const btn = document.getElementById('retry-reconcile-btn');
  btn.disabled = true;
  btn.textContent = 'Retrying…';
  try {
    const res = await fetch('/api/reconcile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ classes: reviewRows.map(normalizeSession) }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Retry failed.');

    reviewRows = data.classes.map((c) => ({ id: rowIdCounter++, ...c }));
    renderReconcileNote(data.reconcile_note);
    currentSuggestions = data.suggestions || [];
    renderSuggestions();
    renderReviewTable();
  } catch (err) {
    alert('Retry failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Retry AI Cleanup';
  }
}

// =====================
// AI reconciliation suggestions (low-confidence groupings, not auto-applied)
// =====================
function renderSuggestions() {
  const box = document.getElementById('extract-suggestions');
  if (!currentSuggestions.length) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  box.innerHTML = currentSuggestions.map((s, i) => `
    <div class="suggestion-item">
      <span style="display:flex;align-items:flex-start;gap:8px">${ICON_INFO} <span>${s.variants.map(esc).join(' / ')} → <strong>${esc(s.canonical)}</strong>${s.reason ? ` <em>(${esc(s.reason)})</em>` : ''}</span></span>
      <button class="btn-secondary" onclick="applySuggestion(${i})">Apply</button>
    </div>
  `).join('');
}

function applySuggestion(index) {
  const s = currentSuggestions[index];
  if (!s) return;

  reviewRows.forEach((row) => {
    if (s.field === 'course') {
      const label = `${row.course_code} (${row.course_name})`;
      if (!s.variants.includes(label)) return;
      const match = s.canonical.match(/^(.*) \((.*)\)$/);
      row.original_course_code = row.original_course_code || row.course_code;
      row.original_course_name = row.original_course_name || row.course_name;
      row.course_code = match ? match[1] : s.canonical;
      row.course_name = match ? match[2] : row.course_name;
    } else if (s.field === 'instructor') {
      if (!s.variants.includes(row.instructor_name)) return;
      row.original_instructor_name = row.original_instructor_name || row.instructor_name;
      row.instructor_name = s.canonical;
    } else if (s.field === 'course_code') {
      if (!s.variants.includes(row.course_code)) return;
      row.original_course_code = row.original_course_code || row.course_code;
      row.course_code = s.canonical;
    }
  });

  currentSuggestions.splice(index, 1);
  renderSuggestions();
  renderReviewTable();
}

function addReviewRow() {
  reviewRows.push({
    id: rowIdCounter++,
    course_name: '', course_code: '', course_type: '', instructor_name: '',
    day: 'MON', time_start: '08:00', time_end: '09:30', group_number: 'G1',
  });
  renderReviewTable();
}

function confirmReview() {
  const bad = reviewRows.filter((r) => !r.course_code || !r.day || !r.time_start || !r.time_end || !r.group_number);
  if (bad.length) {
    alert(`${bad.length} row(s) are missing required fields (code, day, start, end, group). Fill them in or remove those rows.`);
    return;
  }
  buildCoursePicker();
  document.getElementById('prefs-section').style.display = 'block';
  setStep(3);
}

// =====================
// Step 3: Courses & preferences
// =====================
function normalizeSession(row) {
  return { ...row, time: `${row.time_start} - ${row.time_end}` };
}

function buildCoursePicker() {
  const courses = new Map(); // code -> name
  reviewRows.forEach((r) => { if (!courses.has(r.course_code)) courses.set(r.course_code, r.course_name || r.course_code); });

  const container = document.getElementById('chips-courses');
  container.innerHTML = '';
  [...courses.entries()].sort().forEach(([code, name]) => {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.textContent = `${code} — ${name}`;
    chip.onclick = () => {
      if (selectedCourses.has(code)) { selectedCourses.delete(code); chip.classList.remove('selected'); }
      else { selectedCourses.add(code); chip.classList.add('selected'); }
      buildPreferenceChips();
    };
    container.appendChild(chip);
  });

  buildPreferenceChips();
}

function buildPreferenceChips() {
  const relevant = reviewRows.filter((r) => selectedCourses.has(r.course_code));

  const sectionKeys = [...new Set(relevant.map((r) => `${r.course_code}|${r.group_number}`))].sort();
  const instructors = [...new Set(relevant.map((r) => r.instructor_name).filter(Boolean))].sort();

  buildToggleChips('chips-preferred-sections', sectionKeys, preferredSections, false, formatSectionLabel, blockedSections);
  buildToggleChips('chips-blocked-sections', sectionKeys, blockedSections, true, formatSectionLabel, preferredSections);
  buildToggleChips('chips-preferred-instructors', instructors, preferredInstructors, false);
  buildToggleChips('chips-blocked-days', CORE_DAYS, blockedDays, true, null, freeDays);
  buildToggleChips('chips-free-days', CORE_DAYS, freeDays, false, null, blockedDays);
}

function formatSectionLabel(key) {
  const [code, group] = key.split('|');
  return `${code} · ${group}`;
}

function buildToggleChips(containerId, values, selectedSet, isAvoid, labelFn, mutuallyExclusiveWith) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  values.forEach((v) => {
    const chip = document.createElement('div');
    chip.className = 'chip' + (isAvoid ? ' avoid' : '') + (selectedSet.has(v) ? ' selected' : '');
    chip.textContent = labelFn ? labelFn(v) : v;
    chip.onclick = () => {
      if (selectedSet.has(v)) {
        selectedSet.delete(v);
      } else {
        selectedSet.add(v);
        if (mutuallyExclusiveWith) mutuallyExclusiveWith.delete(v);
      }
      buildPreferenceChips();
    };
    container.appendChild(chip);
  });
}

// =====================
// Step 4: Generate
// =====================
async function generate() {
  if (!selectedCourses.size) { showError('gen-error', 'Select at least one course first.'); return; }

  const btn = document.getElementById('gen-btn');
  const loading = document.getElementById('gen-loading');
  hideError('gen-error');
  btn.disabled = true;
  loading.classList.add('show');

  const payload = {
    classes: reviewRows.map(normalizeSession),
    selected_courses: [...selectedCourses],
    hard_constraints: {
      blocked_sections: [...blockedSections].map((k) => { const [c, g] = k.split('|'); return { course_code: c, group_number: g }; }),
      blocked_days: [...blockedDays],
      blocked_time_ranges: [],
    },
    preferences: {
      preferred_instructors: [...preferredInstructors],
      preferred_groups: [...preferredSections].map((k) => { const [c, g] = k.split('|'); return { course_code: c, group_number: g }; }),
      preferred_days: [],
      free_days: [...freeDays],
      avoid_early: document.getElementById('pref-avoid-early').checked,
      avoid_late: document.getElementById('pref-avoid-late').checked,
      minimize_gaps: document.getElementById('pref-minimize-gaps').checked,
      compact: document.getElementById('pref-compact').checked,
    },
    top_n: 3,
  };

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not generate a timetable.');

    if (data.status === 'unsatisfiable') {
      const msg = data.conflicts.map((c) => `• ${c.course_code ? c.course_code + ': ' : ''}${c.reason}`).join('<br>');
      showError('gen-error', 'No valid timetable found:<br>' + msg, true);
      return;
    }

    lastResults = data.results;
    activeResultIndex = 0;
    renderResult();
    document.getElementById('result-section').classList.add('show');
    setStep(4);
    document.getElementById('result-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    showError('gen-error', err.message);
  } finally {
    btn.disabled = false;
    loading.classList.remove('show');
  }
}

// =====================
// Result rendering
// =====================
function renderResult() {
  const result = lastResults[activeResultIndex];
  const sessions = result.sessions;

  const tabs = document.getElementById('alt-tabs');
  tabs.innerHTML = lastResults.map((r, i) => `
    <button class="alt-tab ${i === activeResultIndex ? 'active' : ''}" onclick="selectResult(${i})">
      Option ${i + 1} <span class="alt-score">${r.score}</span>
    </button>
  `).join('');

  document.getElementById('summary-grid').innerHTML = `
    <div class="summary-card"><div class="summary-num">${result.total_sessions}</div><div class="summary-label">Sessions</div></div>
    <div class="summary-card"><div class="summary-num">${result.total_courses}</div><div class="summary-label">Courses</div></div>
    <div class="summary-card"><div class="summary-num">${result.days_used.length}</div><div class="summary-label">Days/Week</div></div>
    <div class="summary-card"><div class="summary-num">${result.score}</div><div class="summary-label">Score</div></div>
  `;

  const breakdown = Object.entries(result.score_breakdown)
    .map(([k, v]) => `<span class="score-item ${v >= 0 ? 'pos' : 'neg'}">${k.replace(/_/g, ' ')}: ${v >= 0 ? '+' : ''}${v}</span>`)
    .join('');
  document.getElementById('score-breakdown').innerHTML = breakdown;

  renderCalendar(sessions);
  document.getElementById('raw-json').textContent = JSON.stringify(result, null, 2);
}

function selectResult(i) {
  activeResultIndex = i;
  renderResult();
}

function renderCalendar(sessions) {
  const days = CORE_DAYS.filter((d) => true).concat(
    ['SAT', 'SUN'].filter((d) => sessions.some((s) => s.day === d))
  );

  const grid = {};
  sessions.forEach((s) => {
    const key = `${s.day}|${s.time_start}`;
    if (!grid[key]) grid[key] = [];
    grid[key].push(s);
  });

  const slots = [...new Set(sessions.map((s) => s.time_start))].sort();

  let html = '<thead><tr><th>TIME</th>';
  days.forEach((d) => (html += `<th>${d}</th>`));
  html += '</tr></thead><tbody>';

  slots.forEach((slot) => {
    html += `<tr><td class="time-cell">${slot}</td>`;
    days.forEach((day) => {
      const entries = grid[`${day}|${slot}`] || [];
      if (entries.length) {
        html += '<td>';
        entries.forEach((c) => {
          const rawType = (c.course_type || '').toLowerCase().replace(/[()]/g, '').trim();
          const typeLabel = rawType === 'l' || rawType.includes('lec') ? 'Lecture'
            : rawType === 't' || rawType.includes('tut') ? 'Tutorial'
            : rawType.includes('lab') ? 'Lab'
            : rawType;
          html += `
            <div class="class-card">
              <div class="class-name">${esc(c.course_name || c.course_code)}</div>
              ${typeLabel ? `<div class="class-type">${esc(typeLabel)}</div>` : ''}
              <div class="class-info">${esc(c.instructor_name || '—')}</div>
              <div class="class-info">${c.time_start}–${c.time_end}</div>
              <div><span class="class-badge">${esc(c.group_number)}</span></div>
            </div>`;
        });
        html += '</td>';
      } else {
        html += '<td></td>';
      }
    });
    html += '</tr>';
  });

  html += '</tbody>';
  document.getElementById('timetable').innerHTML = html;
}

// =====================
// Utilities
// =====================
function setStep(n) {
  for (let i = 1; i <= 4; i++) {
    const el = document.getElementById(`step${i}`);
    el.classList.toggle('active', i === n);
    el.classList.toggle('done', i < n);
  }
}

function showError(id, msg, isHtml) {
  const box = document.getElementById(id);
  box.innerHTML = `<span class="alert-icon">${ICON_INFO}</span><span style="flex:1">${isHtml ? msg : esc(msg)}</span>`;
  box.classList.add('show');
}

function hideError(id) {
  document.getElementById(id).classList.remove('show');
}

function toggleJson() {
  document.getElementById('raw-json').classList.toggle('show');
}

function esc(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}
