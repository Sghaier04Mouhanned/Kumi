// =====================
// Constants
// =====================
const DAY_ORDER = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
const CORE_DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI'];
let rowIdCounter = 0;

// TBS's course coding system (handbook section 2.2): the first digit of a
// course's number is its academic level -- 1=Freshman, 2=Sophomore,
// 3=Junior, 4=Senior (e.g. BCOR210 -> level digit "2" -> Sophomore).
const LEVELS = ['Freshman', 'Sophomore', 'Junior', 'Senior'];
const LEVEL_BY_DIGIT = { '1': 'Freshman', '2': 'Sophomore', '3': 'Junior', '4': 'Senior' };
const MAX_SELECTED_COURSES = 7;

function levelFromCode(code) {
  const match = (code || '').match(/(\d+)$/);
  return match ? (LEVEL_BY_DIGIT[match[1][0]] || null) : null;
}

// Inline SVG icons -- no emoji/dingbat glyphs anywhere in the UI.
const ICON_FILE = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="14" rx="1"/><circle cx="9" cy="10" r="2"/><path d="M21 15l-5-4-9 7"/></svg>';
const ICON_CLOSE = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>';
const ICON_UNDO = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 10h9a5 5 0 0 1 0 10H8"/><path d="M4 10l4-4M4 10l4 4"/></svg>';
const ICON_INFO = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><circle cx="12" cy="16.2" r="0.4" fill="currentColor"/></svg>';

// =====================
// State
// =====================
let currentUniversity = null; // {id, name} -- picked in Step 0, gates everything after it
let uploadedFiles = [];      // [{file, groupLabel}]
let reviewRows = [];         // [{id, course_name, course_code, course_type, instructor_name, day, time_start, time_end, group_number}]
let selectedCourses = new Set();
let preferredGroups = new Set();     // bare group numbers, e.g. "G1" -- a student's
let blockedGroups = new Set();       // group is the same set of peers across every course
let preferredInstructors = new Set();
let blockedInstructors = new Set();  // hard-blocks that instructor's whole group (lecture + tutorial)
let blockedDays = new Set();
let freeDays = new Set();
let lastResults = [];
let activeResultIndex = 0;
let currentSuggestions = [];  // AI reconciliation suggestions not yet applied
let selectedLevel = null;     // null = show courses from every level

// =====================
// Styled confirm dialog -- replaces window.confirm() so "are you sure"
// prompts match the rest of the UI instead of the browser's own dialog
// chrome. Usage: `if (await showConfirm('...')) { ... }`.
// =====================
const confirmOverlay = document.getElementById('confirm-overlay');
const confirmMessageEl = document.getElementById('confirm-message');
let _confirmResolve = null;

function showConfirm(message) {
  return new Promise((resolve) => {
    _confirmResolve = resolve;
    confirmMessageEl.textContent = message;
    document.getElementById('confirm-cancel-btn').style.display = '';
    confirmOverlay.classList.add('show');
  });
}

// Same modal, but for a plain notice with nothing to actually confirm (e.g.
// "publish succeeded") -- a Cancel button next to that reads as if there's
// a decision to make, so this hides it and leaves just OK.
function showAlert(message) {
  return new Promise((resolve) => {
    _confirmResolve = resolve;
    confirmMessageEl.textContent = message;
    document.getElementById('confirm-cancel-btn').style.display = 'none';
    confirmOverlay.classList.add('show');
  });
}

function _resolveConfirm(result) {
  confirmOverlay.classList.remove('show');
  if (_confirmResolve) {
    const resolve = _confirmResolve;
    _confirmResolve = null;
    resolve(result);
  }
}

document.getElementById('confirm-ok-btn').onclick = () => _resolveConfirm(true);
document.getElementById('confirm-cancel-btn').onclick = () => _resolveConfirm(false);
confirmOverlay.onclick = (e) => {
  if (e.target === confirmOverlay) _resolveConfirm(false); // backdrop click = cancel
};
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && confirmOverlay.classList.contains('show')) _resolveConfirm(false);
});

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

    // Append rather than replace -- if a shared catalog is already loaded,
    // newly uploaded photos (e.g. a missing group) add to it instead of
    // discarding it.
    reviewRows = reviewRows.concat(data.classes.map((c) => ({ id: rowIdCounter++, ...c })));

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
// Step 0: University -- each university has its own shared catalog, so this
// decides whose catalog (if any) to check before anything else runs.
// =====================
const UNIVERSITY_STORAGE_KEY = 'kumi.university';
let knownUniversities = []; // last fetched /api/universities list, reused by the fuzzy-match check below

async function initUniversityStep() {
  try {
    const res = await fetch('/api/universities');
    if (res.ok) knownUniversities = await res.json();
  } catch (err) {
    console.error('Could not load university list:', err);
  }

  const saved = readSavedUniversity();
  if (saved) {
    // Returning visit -- skip the picker, but only trust a saved id that a
    // published catalog actually recognizes; otherwise fall through to the
    // list so a stale/guessed id from a first-time upload doesn't stick.
    const known = knownUniversities.find((u) => u.university_id === saved.id);
    selectUniversity(saved.id, known ? known.university_name : saved.name, { skipSave: true });
    return;
  }

  renderUniversityList(knownUniversities);
}

function readSavedUniversity() {
  try {
    const raw = localStorage.getItem(UNIVERSITY_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null; // private browsing / blocked storage -- just re-ask each visit
  }
}

function renderUniversityList(universities) {
  const container = document.getElementById('university-list');
  container.innerHTML = '';
  universities.forEach((u) => {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.textContent = `${u.university_name} — ${u.group_count} group${u.group_count === 1 ? '' : 's'}`;
    chip.onclick = () => selectUniversity(u.university_id, u.university_name);
    container.appendChild(chip);
  });
}

// Character-bigram Dice coefficient -- catches typos, spacing, and
// punctuation differences (e.g. "Tunis Buisness School" vs "Tunis Business
// School"). Same spirit as the Python side's difflib.SequenceMatcher.ratio()
// used for catalog-code/instructor-name matching, just implemented here
// since this needs to run against the university list in the browser.
function _bigrams(str) {
  const s = str.toLowerCase().replace(/\s+/g, ' ').trim();
  const grams = [];
  for (let i = 0; i < s.length - 1; i++) grams.push(s.slice(i, i + 2));
  return grams;
}

function _diceCoefficient(a, b) {
  const bigramsA = _bigrams(a);
  const bigramsB = _bigrams(b);
  if (!bigramsA.length || !bigramsB.length) return a.toLowerCase() === b.toLowerCase() ? 1 : 0;
  const counts = new Map();
  bigramsA.forEach((g) => counts.set(g, (counts.get(g) || 0) + 1));
  let matches = 0;
  bigramsB.forEach((g) => {
    const c = counts.get(g) || 0;
    if (c > 0) { matches++; counts.set(g, c - 1); }
  });
  return (2 * matches) / (bigramsA.length + bigramsB.length);
}

// Separate check for the case Dice similarity can't catch on its own: an
// initialism like "TBS" for "Tunis Business School" is nowhere near it
// character-for-character, but is an exact, unambiguous match on first
// letters.
function _isAcronymMatch(typed, fullName) {
  const cleanTyped = typed.replace(/[^a-zA-Z]/g, '').toUpperCase();
  if (cleanTyped.length < 2) return false; // too short to mean anything -- avoid false positives
  const acronym = fullName.split(/\s+/).filter(Boolean).map((w) => w[0]).join('').toUpperCase();
  return cleanTyped === acronym;
}

const UNIVERSITY_FUZZY_MATCH_THRESHOLD = 0.6;

function findUniversityMatch(typedName) {
  let best = null;
  let bestScore = 0;
  knownUniversities.forEach((u) => {
    const score = _diceCoefficient(typedName, u.university_name);
    const acronym = _isAcronymMatch(typedName, u.university_name);
    if (!acronym && score < UNIVERSITY_FUZZY_MATCH_THRESHOLD) return;
    const effectiveScore = acronym ? Math.max(score, 0.99) : score;
    if (effectiveScore > bestScore) {
      bestScore = effectiveScore;
      best = u;
    }
  });
  return best;
}

async function chooseUniversity() {
  const input = document.getElementById('university-input');
  const name = input.value.trim();
  if (!name) return;

  // Typos, spacing/punctuation variants, and initialisms (e.g. "TBS" for
  // "Tunis Business School") should land on the same existing catalog
  // instead of silently starting a separate, empty one -- but a match is
  // only ever a suggestion the student confirms, never applied silently,
  // since guessing wrong here means showing them the wrong school's data.
  const match = findUniversityMatch(name);
  if (match && match.university_name.toLowerCase() !== name.toLowerCase()) {
    const useExisting = await showConfirm(
      `Did you mean "${match.university_name}"? Click OK to use their already-published timetable, ` +
      `or Cancel to set up "${name}" as a separate, new university.`
    );
    if (useExisting) {
      selectUniversity(match.university_id, match.university_name);
      return;
    }
  }

  // This id is only a client-side guess used to check for an existing
  // catalog -- if this university ends up publishing one, the server
  // settles on the real id (same slugify rule) at that point.
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'university';
  selectUniversity(id, name);
}

function selectUniversity(id, name, opts) {
  currentUniversity = { id, name };
  if (!opts || !opts.skipSave) {
    try {
      localStorage.setItem(UNIVERSITY_STORAGE_KEY, JSON.stringify(currentUniversity));
    } catch (err) {
      // Not fatal -- just won't be remembered next visit.
    }
  }
  document.getElementById('university-section').style.display = 'none';
  document.getElementById('steps-bar').style.display = 'flex';
  document.getElementById('upload-section').style.display = 'block';
  document.getElementById('university-indicator-name').textContent = name;
  document.getElementById('university-indicator').style.display = 'block';
  loadSharedCatalog();
}

function switchUniversity() {
  try { localStorage.removeItem(UNIVERSITY_STORAGE_KEY); } catch (err) { /* ignore */ }
  location.reload();
}

// =====================
// Shared catalog -- lets a university's students skip uploading entirely
// once someone has published one for their school
// =====================
async function loadSharedCatalog() {
  try {
    const res = await fetch(`/api/catalog?university_id=${encodeURIComponent(currentUniversity.id)}`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.classes || !data.classes.length) return; // nothing published yet for this university -- normal upload flow

    reviewRows = data.classes.map((c) => ({ id: rowIdCounter++, ...c }));

    const groups = new Set(reviewRows.map((r) => r.group_number));
    const updated = data.updated_at ? new Date(data.updated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : 'an unknown date';
    const banner = document.getElementById('catalog-banner');
    banner.classList.add('show');
    document.getElementById('catalog-banner-icon').innerHTML = ICON_INFO;
    document.getElementById('catalog-banner-text').textContent =
      `Using ${currentUniversity.name}'s ${data.semester_label || 'published'} timetable (${groups.size} group${groups.size === 1 ? '' : 's'}) — last updated ${updated}.`;

    document.getElementById('upload-section').style.display = 'none';
    buildCoursePicker();
    document.getElementById('prefs-section').style.display = 'block';
    setStep(3);
  } catch (err) {
    // Catalog fetch failing should never block the normal upload flow.
    console.error('Could not load shared catalog:', err);
  }
}

function showUploadForMissingGroup() {
  document.getElementById('catalog-banner').classList.remove('show');
  document.getElementById('upload-section').style.display = 'block';
  document.getElementById('upload-section').scrollIntoView({ behavior: 'smooth' });
  setStep(1);
}

function openPublishModal() {
  if (!reviewRows.length) { alert('Nothing to publish yet.'); return; }
  document.getElementById('publish-university-name').textContent = currentUniversity.name;
  document.getElementById('publish-token-input').value = '';
  document.getElementById('publish-label-input').value = '';
  hideError('publish-error');
  document.getElementById('publish-overlay').classList.add('show');
}

function closePublishModal() {
  document.getElementById('publish-overlay').classList.remove('show');
}

async function submitPublish() {
  const token = document.getElementById('publish-token-input').value;
  if (!token) { showError('publish-error', 'Admin token is required.'); return; }
  const semester_label = document.getElementById('publish-label-input').value.trim() || null;

  const btn = document.getElementById('publish-confirm-btn');
  btn.disabled = true;
  hideError('publish-error');
  try {
    const res = await fetch('/api/catalog', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        university_id: currentUniversity.id,
        university_name: currentUniversity.name,
        classes: reviewRows.map(normalizeSession),
        semester_label,
        token,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Publish failed.');
    closePublishModal();
    await showAlert(
      `Published as ${currentUniversity.name}'s shared catalog (${data.classes.length} sessions). ` +
      'Other students at this university loading the app now will see this instead of the upload flow.'
    );
  } catch (err) {
    showError('publish-error', err.message);
  } finally {
    btn.disabled = false;
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
      <td><input value="${esc(row.class_number || '')}" oninput="updateRow(${row.id},'class_number',this.value)"/></td>
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
    day: 'MON', time_start: '08:00', time_end: '09:30', group_number: 'G1', class_number: '',
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

  // Level filter -- single-select, "All" (null) shows everything. A course
  // whose code doesn't match TBS's level-digit convention (a non-TBS photo,
  // or an unrecognized code) always shows, regardless of the filter.
  const levelContainer = document.getElementById('chips-level');
  levelContainer.innerHTML = '';
  [null, ...LEVELS].forEach((level) => {
    const chip = document.createElement('div');
    chip.className = 'chip' + (selectedLevel === level ? ' selected' : '');
    chip.textContent = level || 'All Levels';
    chip.onclick = () => { selectedLevel = level; buildCoursePicker(); };
    levelContainer.appendChild(chip);
  });

  const container = document.getElementById('chips-courses');
  container.innerHTML = '';
  [...courses.entries()].sort().forEach(([code, name]) => {
    const level = levelFromCode(code);
    const isSelected = selectedCourses.has(code);
    // Always show an already-selected course so filtering never hides a pick.
    if (!isSelected && selectedLevel && level && level !== selectedLevel) return;

    const chip = document.createElement('div');
    chip.className = 'chip' + (isSelected ? ' selected' : '');
    chip.textContent = `${code} — ${name}`;
    chip.onclick = () => {
      if (selectedCourses.has(code)) {
        selectedCourses.delete(code);
      } else {
        if (selectedCourses.size >= MAX_SELECTED_COURSES) {
          showCourseLimitNote(`You can select at most ${MAX_SELECTED_COURSES} courses -- remove one before adding another.`);
          return;
        }
        selectedCourses.add(code);
      }
      hideCourseLimitNote();
      buildCoursePicker(); // rebuilds the chip list AND preference chips
    };
    container.appendChild(chip);
  });

  buildPreferenceChips();
}

function showCourseLimitNote(message) {
  const box = document.getElementById('course-limit-note');
  document.getElementById('course-limit-icon').innerHTML = ICON_INFO;
  document.getElementById('course-limit-text').textContent = message;
  box.classList.add('show');
}

function hideCourseLimitNote() {
  document.getElementById('course-limit-note').classList.remove('show');
}

// "G1" in a Freshman course and "G1" in a Sophomore course are different
// physical groups of students that just happen to share a label -- group
// numbers are only unique within a level. So the group a student picks has
// to be scoped by level too, not just by its bare number.
function groupLevelKey(row) {
  return `${levelFromCode(row.course_code) || 'Unknown'}|${row.group_number}`;
}

function formatGroupLevelLabel(key) {
  const [level, group] = key.split('|');
  return `${group} · ${level}`;
}

function buildPreferenceChips() {
  const relevant = reviewRows.filter((r) => selectedCourses.has(r.course_code));

  // A student's group is the same set of peers across all their courses
  // within a level, so blocking/preferring "G3 · Freshman" applies
  // everywhere that group shows up -- not chosen per course.
  const groups = [...new Set(relevant.map(groupLevelKey))].sort();
  const instructors = [...new Set(relevant.map((r) => r.instructor_name).filter(Boolean))].sort();

  buildToggleChips('chips-preferred-sections', groups, preferredGroups, false, formatGroupLevelLabel, blockedGroups);
  buildToggleChips('chips-blocked-sections', groups, blockedGroups, true, formatGroupLevelLabel, preferredGroups);
  buildToggleChips('chips-preferred-instructors', instructors, preferredInstructors, false, null, blockedInstructors);
  buildToggleChips('chips-blocked-instructors', instructors, blockedInstructors, true, null, preferredInstructors);
  buildToggleChips('chips-blocked-days', CORE_DAYS, blockedDays, true, null, freeDays);
  buildToggleChips('chips-free-days', CORE_DAYS, freeDays, false, null, blockedDays);
}

// Expands a set of selected "LEVEL|GROUP" keys into every {course_code,
// group_number} pair the backend needs, scoped to the currently-selected
// courses (a group selection only matters for courses the student is
// actually taking, and only within the same level the group was picked in).
function expandGroupToSections(groupSet) {
  const seen = new Set();
  const result = [];
  reviewRows.forEach((r) => {
    if (!selectedCourses.has(r.course_code) || !groupSet.has(groupLevelKey(r))) return;
    const key = `${r.course_code}|${r.group_number}`;
    if (seen.has(key)) return;
    seen.add(key);
    result.push({ course_code: r.course_code, group_number: r.group_number });
  });
  return result;
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
      blocked_sections: expandGroupToSections(blockedGroups),
      blocked_instructors: [...blockedInstructors],
      blocked_days: [...blockedDays],
      blocked_time_ranges: [],
    },
    preferences: {
      preferred_instructors: [...preferredInstructors],
      preferred_groups: expandGroupToSections(preferredGroups),
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

// A fixed 08:00-18:00 covers a typical school day; stretched further only
// if a real session falls outside it, so an outlier evening class never
// gets clipped off instead of just making every week's grid taller.
const CAL_DEFAULT_START_MIN = 8 * 60;
const CAL_DEFAULT_END_MIN = 18 * 60;
const CAL_PX_PER_MIN = 1.4;
const CAL_MIN_CARD_HEIGHT = 32; // a floor so a very short class stays readable, not a sliver
// Real class blocks here run in 90-minute units (a 1.5h tutorial, a 3h
// lecture as two of them back to back), so gridlines every 90 minutes land
// on actual start/end times far more often than plain hourly lines did.
const CAL_TICK_MIN = 90;

function _timeToMinutes(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

function _classTypeLabel(courseType) {
  const rawType = (courseType || '').toLowerCase().replace(/[()]/g, '').trim();
  return rawType === 'l' || rawType.includes('lec') ? 'Lecture'
    : rawType === 't' || rawType.includes('tut') ? 'Tutorial'
    : rawType.includes('lab') ? 'Lab'
    : rawType;
}

function renderCalendar(sessions) {
  const timetableEl = document.getElementById('timetable');
  if (!sessions.length) { timetableEl.innerHTML = ''; return; }

  const days = CORE_DAYS.filter((d) => true).concat(
    ['SAT', 'SUN'].filter((d) => sessions.some((s) => s.day === d))
  );

  let gridStart = CAL_DEFAULT_START_MIN;
  let gridEnd = CAL_DEFAULT_END_MIN;
  sessions.forEach((s) => {
    gridStart = Math.min(gridStart, Math.floor(_timeToMinutes(s.time_start) / CAL_TICK_MIN) * CAL_TICK_MIN);
    gridEnd = Math.max(gridEnd, Math.ceil(_timeToMinutes(s.time_end) / CAL_TICK_MIN) * CAL_TICK_MIN);
  });

  const tickHeight = CAL_TICK_MIN * CAL_PX_PER_MIN;
  const totalHeight = (gridEnd - gridStart) * CAL_PX_PER_MIN;

  let hourMarks = '';
  for (let m = gridStart; m <= gridEnd; m += CAL_TICK_MIN) {
    const h = Math.floor(m / 60);
    const mm = m % 60;
    hourMarks += `<div class="cal-hour-mark" style="top:${(m - gridStart) * CAL_PX_PER_MIN}px">${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}</div>`;
  }

  let dayColumns = '';
  days.forEach((day) => {
    let events = '';
    sessions.filter((s) => s.day === day).forEach((c) => {
      const startMin = _timeToMinutes(c.time_start);
      const endMin = _timeToMinutes(c.time_end);
      const top = (startMin - gridStart) * CAL_PX_PER_MIN;
      const height = Math.max((endMin - startMin) * CAL_PX_PER_MIN, CAL_MIN_CARD_HEIGHT);
      const typeLabel = _classTypeLabel(c.course_type);
      events += `
        <div class="class-card" style="top:${top}px;height:${height}px">
          <div class="class-name">${esc(c.course_name || c.course_code)}</div>
          ${typeLabel ? `<div class="class-type">${esc(typeLabel)}</div>` : ''}
          <div class="class-info">${esc(c.instructor_name || '—')}</div>
          <div class="class-info">${c.time_start}–${c.time_end}</div>
          <div style="display:flex;gap:4px;flex-wrap:wrap">
            <span class="class-badge">${esc(c.group_number)}</span>
            ${c.class_number ? `<span class="class-badge">${esc(c.class_number)}</span>` : ''}
          </div>
        </div>`;
    });
    dayColumns += `<div class="cal-day-col">${events}</div>`;
  });

  let dayHeaders = '';
  days.forEach((d) => { dayHeaders += `<div class="cal-day-header">${d}</div>`; });

  timetableEl.innerHTML = `
    <div class="cal-header-row">
      <div class="cal-gutter-header"></div>
      ${dayHeaders}
    </div>
    <div class="cal-body" style="height:${totalHeight}px;--tick-h:${tickHeight}px">
      <div class="cal-gutter">${hourMarks}</div>
      ${dayColumns}
    </div>`;
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

// =====================
// Calendar export (.ics) -- classes repeat weekly, but the extracted data
// only ever has a day-of-week + time, never real calendar dates. Asking for
// the semester's start/end once lets every session become a correctly
// dated, weekly-recurring calendar event a phone's calendar app understands
// natively, instead of a one-off event on the wrong date.
// =====================
const ICS_BYDAY = { MON: 'MO', TUE: 'TU', WED: 'WE', THU: 'TH', FRI: 'FR', SAT: 'SA', SUN: 'SU' };
const DAY_OFFSET = { MON: 0, TUE: 1, WED: 2, THU: 3, FRI: 4, SAT: 5, SUN: 6 };

function _pad2(n) {
  return String(n).padStart(2, '0');
}

function _toDateInputValue(date) {
  return `${date.getFullYear()}-${_pad2(date.getMonth() + 1)}-${_pad2(date.getDate())}`;
}

function _defaultSemesterStart() {
  const d = new Date();
  const daysUntilMonday = (1 - d.getDay() + 7) % 7; // 0 if today already is Monday
  d.setDate(d.getDate() + daysUntilMonday);
  return d;
}

function openCalendarExport() {
  const startInput = document.getElementById('semester-start-input');
  const endInput = document.getElementById('semester-end-input');
  if (!startInput.value) {
    const start = _defaultSemesterStart();
    const end = new Date(start);
    end.setDate(end.getDate() + 15 * 7); // a common semester length -- just a starting point to adjust
    startInput.value = _toDateInputValue(start);
    endInput.value = _toDateInputValue(end);
  }
  document.getElementById('calendar-export-overlay').classList.add('show');
}

function closeCalendarExport() {
  document.getElementById('calendar-export-overlay').classList.remove('show');
}

function _icsDateTime(date, timeStr) {
  const [h, m] = timeStr.split(':').map(Number);
  return `${date.getFullYear()}${_pad2(date.getMonth() + 1)}${_pad2(date.getDate())}T${_pad2(h)}${_pad2(m)}00`;
}

function _icsDateOnly(date) {
  return `${date.getFullYear()}${_pad2(date.getMonth() + 1)}${_pad2(date.getDate())}`;
}

function _icsUtcNow() {
  const d = new Date();
  return `${d.getUTCFullYear()}${_pad2(d.getUTCMonth() + 1)}${_pad2(d.getUTCDate())}T` +
    `${_pad2(d.getUTCHours())}${_pad2(d.getUTCMinutes())}${_pad2(d.getUTCSeconds())}Z`;
}

function _icsEscape(text) {
  return String(text || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
}

function buildIcs(sessions, semesterStart, semesterEnd) {
  const until = new Date(semesterEnd);
  until.setDate(until.getDate() + 1); // include events ON the end date, not just before it
  const untilStr = `${_icsDateOnly(until)}T235959`;
  const dtstamp = _icsUtcNow();

  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Kumi//Timetable//EN', 'CALSCALE:GREGORIAN'];

  sessions.forEach((s, i) => {
    const offset = DAY_OFFSET[s.day];
    if (offset === undefined) return; // an unrecognized day shouldn't break the rest of the export

    const firstDate = new Date(semesterStart);
    firstDate.setDate(firstDate.getDate() + offset);

    const summary = s.course_type ? `${s.course_name || s.course_code} — ${s.course_type}` : (s.course_name || s.course_code);
    const descriptionParts = [];
    if (s.instructor_name) descriptionParts.push(`Instructor: ${s.instructor_name}`);
    if (s.group_number) descriptionParts.push(`Group: ${s.group_number}`);

    lines.push('BEGIN:VEVENT');
    lines.push(`UID:kumi-${i}-${s.course_code}-${s.group_number}-${s.day}-${s.time_start}@kumi.app`.replace(/\s+/g, ''));
    lines.push(`DTSTAMP:${dtstamp}`);
    lines.push(`DTSTART:${_icsDateTime(firstDate, s.time_start)}`);
    lines.push(`DTEND:${_icsDateTime(firstDate, s.time_end)}`);
    lines.push(`RRULE:FREQ=WEEKLY;BYDAY=${ICS_BYDAY[s.day]};UNTIL=${untilStr}`);
    lines.push(`SUMMARY:${_icsEscape(summary)}`);
    if (s.class_number) lines.push(`LOCATION:${_icsEscape(s.class_number)}`);
    if (descriptionParts.length) lines.push(`DESCRIPTION:${_icsEscape(descriptionParts.join('\n'))}`);
    lines.push('END:VEVENT');
  });

  lines.push('END:VCALENDAR');
  return lines.join('\r\n');
}

function downloadCalendarFile() {
  const startVal = document.getElementById('semester-start-input').value;
  const endVal = document.getElementById('semester-end-input').value;
  if (!startVal || !endVal) { alert('Pick both a start and end date.'); return; }

  const start = new Date(`${startVal}T00:00:00`);
  const end = new Date(`${endVal}T00:00:00`);
  if (end < start) { alert('The end date is before the start date.'); return; }

  const sessions = lastResults[activeResultIndex].sessions;
  const ics = buildIcs(sessions, start, end);
  const blob = new Blob([ics], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'kumi-timetable.ics';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  closeCalendarExport();
}

function esc(str) {
  const div = document.createElement('div');
  div.textContent = str == null ? '' : String(str);
  return div.innerHTML;
}

// =====================
// Start over
// =====================
async function startOver() {
  // A full reload is the simplest way to guarantee every piece of session
  // state (uploaded files, extracted/edited rows, selections, results) is
  // truly gone -- and it re-checks the shared catalog cleanly too, rather
  // than trying to hand-reset a dozen variables and risk missing one. The
  // chosen university is deliberately kept (it's identity, not session
  // state) via UNIVERSITY_STORAGE_KEY -- use "Switch university" for that.
  if (await showConfirm('Clear everything from this session (uploads, extracted data, selections) and start over?')) {
    location.reload();
  }
}

// =====================
// Init
// =====================
initUniversityStep();
