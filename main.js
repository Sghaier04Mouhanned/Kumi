// =====================
// Constants
// =====================
const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI'];
const TIME_SLOTS = [
  '8:30 - 10:00',
  '10:00 - 11:30',
  '11:30 - 1:00',
  '1:30 - 3:00',
  '3:00 - 4:30',
];

// =====================
// State
// =====================
let timetableData = null;
let allClasses = [];
let selectedGroups      = new Set();
let selectedInstructors = new Set();
let avoidDays           = new Set();
let selectedTypes       = new Set();

// =====================
// File Upload Handling
// =====================
const uploadZone = document.getElementById('upload-zone');
const fileInput  = document.getElementById('file-input');

uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('dragover');
});
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  if (file) readFile(file);
});
fileInput.addEventListener('change', (e) => {
  if (e.target.files[0]) readFile(e.target.files[0]);
});

function readFile(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    document.getElementById('json-paste').value = e.target.result;
    const el = document.getElementById('upload-success');
    el.textContent = `✓ Loaded: ${file.name} (${(file.size / 1024).toFixed(1)}KB)`;
    el.style.display = 'block';
  };
  reader.readAsText(file);
}

// =====================
// Load & Parse Data
// =====================
function loadData() {
  const raw = document.getElementById('json-paste').value.trim();
  if (!raw) { alert('Please paste or upload your JSON data first.'); return; }

  try {
    timetableData = JSON.parse(raw);
  } catch (e) {
    alert('Invalid JSON: ' + e.message);
    return;
  }

  // Support both { all_classes: [] } and { by_group: { G1: [] } } structures
  allClasses = [];
  if (timetableData.all_classes) allClasses = [...timetableData.all_classes];
  if (timetableData.by_group) {
    Object.values(timetableData.by_group).forEach((arr) => {
      if (Array.isArray(arr)) allClasses.push(...arr);
    });
  }

  // Deduplicate by course+group+day+time
  const seen = new Set();
  allClasses = allClasses.filter((c) => {
    const key = `${c.course_code}-${c.group_number}-${c.day}-${c.time}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  if (!allClasses.length) { alert('No classes found in the JSON.'); return; }

  // Extract unique filter values
  const groups      = [...new Set(allClasses.map((c) => c.group_number).filter(Boolean))].sort();
  const instructors = [...new Set(allClasses.map((c) => c.instructor_name).filter((v) => v && v !== 'Unknown' && v !== 'null'))].sort();
  const days        = [...new Set(allClasses.map((c) => c.day).filter(Boolean))].sort();
  const types       = [...new Set(allClasses.map((c) => normalizeType(c.course_type)).filter(Boolean))].sort();

  buildChips('chips-groups',      groups,      selectedGroups,      false);
  buildChips('chips-instructors', instructors, selectedInstructors, false);
  buildChips('chips-days',        days,        avoidDays,           true);
  buildChips('chips-types',       types,       selectedTypes,       false);

  document.getElementById('prefs-section').style.display    = 'block';
  document.getElementById('generate-section').style.display = 'block';

  document.getElementById('step1').classList.remove('active');
  document.getElementById('step1').classList.add('done');
  document.getElementById('step2').classList.add('active');

  updatePromptPreview();
}

// =====================
// Chip Builder
// =====================
function buildChips(containerId, values, selectedSet, isAvoid) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  values.forEach((v) => {
    const chip = document.createElement('div');
    chip.className = 'chip' + (isAvoid ? ' avoid' : '');
    chip.textContent = v;
    chip.onclick = () => {
      if (selectedSet.has(v)) { selectedSet.delete(v); chip.classList.remove('selected'); }
      else                    { selectedSet.add(v);    chip.classList.add('selected');    }
      updatePromptPreview();
    };
    container.appendChild(chip);
  });
}

// =====================
// Prompt Preview
// =====================
function updatePromptPreview() {
  const groups = selectedGroups.size      ? [...selectedGroups].join(', ')      : 'Any group';
  const instr  = selectedInstructors.size ? [...selectedInstructors].join(', ') : 'No preference';
  const avoid  = avoidDays.size           ? [...avoidDays].join(', ')           : 'None';
  const types  = selectedTypes.size       ? [...selectedTypes].join(', ')       : 'All types';
  const extra  = document.getElementById('extra-prompt').value;

  // Show live filtered count so user can see token estimate before hitting generate
  const preview = preFilterClasses(allClasses, {
    preferred_groups: selectedGroups.size ? [...selectedGroups] : null,
    avoid_days:       avoidDays.size      ? [...avoidDays]      : null,
    course_types:     selectedTypes.size  ? [...selectedTypes]  : null,
  });

  document.getElementById('prompt-preview').innerHTML = `
    <strong>Prompt to Groq (Llama 3 — Handbook Mode):</strong><br><br>
    Sending <strong style="color:var(--accent3)">${preview.length}</strong> classes
    (pre-filtered from ${allClasses.length} total) with these constraints:<br><br>
    • <strong>Groups:</strong> ${groups}<br>
    • <strong>Instructors:</strong> ${instr}<br>
    • <strong>Avoid days:</strong> ${avoid}<br>
    • <strong>Course types:</strong> ${types}<br>
    ${extra ? `• <strong>Extra:</strong> ${extra}` : ''}
    <br><br>
    <em style="color:var(--accent2)">📋 Handbook rules active:</em>
    <em style="color:var(--muted)"> no conflicts · all components required · no duplicates · valid weekly structure</em>
  `;
}

document.getElementById('extra-prompt').addEventListener('input', updatePromptPreview);

// =====================
// Pre-Filter
// Cuts payload size BEFORE the API call to stay under free-tier token limits.
// Always select at least one group — that alone cuts the data by ~80–90%.
// =====================
function preFilterClasses(classes, prefs) {
  let filtered = [...classes];

  // 1. Keep only selected groups (biggest reduction)
  if (prefs.preferred_groups && prefs.preferred_groups.length) {
    filtered = filtered.filter((c) => prefs.preferred_groups.includes(c.group_number));
  }

  // 2. Drop avoided days
  if (prefs.avoid_days && prefs.avoid_days.length) {
    filtered = filtered.filter((c) => !prefs.avoid_days.includes(c.day));
  }

  // 3. Keep only selected course types
  if (prefs.course_types && prefs.course_types.length) {
    filtered = filtered.filter((c) => {
      const t = normalizeType(c.course_type);
      return prefs.course_types.includes(t);
    });
  }

  // 4. Strip redundant fields to save tokens
  filtered = filtered.map(({ time_start, time_end, ...rest }) => rest);

  console.log(`Pre-filter: ${classes.length} → ${filtered.length} classes sent to API`);
  return filtered;
}

// =====================
// Generate via Groq API
// =====================
async function generate() {
  const apiKey = document.getElementById('api-key').value.trim();
  if (!apiKey)            { showError('Please enter your Groq API key.'); return; }
  if (!allClasses.length) { showError('Please load your data first.'); return; }

  const btn     = document.getElementById('gen-btn');
  const loading = document.getElementById('loading');
  btn.disabled  = true;
  loading.classList.add('show');
  hideError();

  document.getElementById('step2').classList.remove('active');
  document.getElementById('step2').classList.add('done');
  document.getElementById('step3').classList.add('active');

  const prefs = {
    preferred_groups:      selectedGroups.size      ? [...selectedGroups]      : null,
    preferred_instructors: selectedInstructors.size ? [...selectedInstructors] : null,
    avoid_days:            avoidDays.size           ? [...avoidDays]           : null,
    course_types:          selectedTypes.size       ? [...selectedTypes]       : null,
    extra:                 document.getElementById('extra-prompt').value || null,
  };

  // Pre-filter BEFORE sending — stays within the 12k token free-tier limit
  const filteredClasses = preFilterClasses(allClasses, prefs);

  if (!filteredClasses.length) {
    showError('No classes match your current filters. Try selecting different groups or removing some filters.');
    btn.disabled = false;
    loading.classList.remove('show');
    document.getElementById('step3').classList.remove('active');
    document.getElementById('step2').classList.remove('done');
    document.getElementById('step2').classList.add('active');
    return;
  }

  // ─────────────────────────────────────────────
  // SYSTEM PROMPT — University Handbook Rules
  // ─────────────────────────────────────────────
  const systemPrompt = `You are a constraint-aware university timetable optimizer that strictly follows the university academic handbook.

HANDBOOK RULES (HARD CONSTRAINTS — never violate these):
1. NO TIME CONFLICTS: A student cannot attend two classes at the same time slot.
2. REQUIRED COURSE COMPONENTS: If a course has Lecture + Tutorial + Lab components, ALL must appear in the schedule.
3. SECTION COMPATIBILITY: Only use tutorial/lab sections that are compatible with the selected lecture section.
4. GROUP RESTRICTIONS: Only include sessions that belong to the student's selected group(s).
5. NO DUPLICATE CLASSES: The same course component cannot appear twice.
6. COMPLETE ACADEMIC LOAD: All required courses for the semester must be included.
7. VALID WEEKLY STRUCTURE: Courses must be distributed across valid university time blocks.

STUDENT PREFERENCES (SOFT CONSTRAINTS — apply only if they don't conflict with handbook rules):
- Preferred professors
- Preferred days
- Avoid early morning / late classes
- Prefer compact schedules
- Avoid specific instructors
If a preference conflicts with a handbook rule, the handbook rule ALWAYS takes priority.

REASONING PROCESS — before selecting sessions you must internally:
1. Identify all unique courses in the provided data
2. For each course, identify all available components (Lecture / Tutorial / Lab)
3. Filter out any sections that violate handbook rules
4. Check for time conflicts between selected sessions
5. Evaluate remaining options against student preferences
6. Select the best valid combination

OUTPUT FORMAT — return a single JSON object with exactly these two keys:
{
  "schedule": [ array of selected class objects ],
  "summary": {
    "total_courses": number,
    "total_sessions": number,
    "days_used": [ list of days ],
    "instructors": [ list of instructor names ],
    "notes": "brief explanation of decisions made and any trade-offs"
  }
}

Each object in "schedule" must have exactly these fields:
course_name, course_code, course_type, instructor_name, class_number, day, time, group_number

STRICT RULES:
- Return ONLY the JSON object above. No markdown, no backticks, no explanation outside the JSON.
- NEVER invent classes, instructors, or time slots not present in the input data.
- NEVER produce overlapping sessions.
- ONLY use sections present in the provided data.`;

  // ─────────────────────────────────────────────
  // USER PROMPT — Data + Student Preferences
  // ─────────────────────────────────────────────
  const userPrompt = `Here are the available class sessions for this student (${filteredClasses.length} sessions, pre-filtered by group/day/type):
${JSON.stringify(filteredClasses)}

Student preferences:
- Preferred groups: ${prefs.preferred_groups ? prefs.preferred_groups.join(', ') : 'Any'}
- Preferred instructors: ${prefs.preferred_instructors ? prefs.preferred_instructors.join(', ') : 'No preference'}
- Days to avoid: ${prefs.avoid_days ? prefs.avoid_days.join(', ') : 'None'}
- Course types to include: ${prefs.course_types ? prefs.course_types.join(', ') : 'All'}
- Extra instructions: ${prefs.extra || 'None'}

Apply the handbook rules strictly, then maximize the student preferences. Return ONLY the JSON object.`;

  try {
    document.getElementById('loading-text').textContent = 'Sending to Groq...';

    const response = await fetch('https://api.groq.com/openai/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: 'llama-3.3-70b-versatile',
        max_tokens: 4000,
        temperature: 0.1, // Low temp = deterministic, rule-following output
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user',   content: userPrompt   },
        ],
      }),
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.error?.message || `HTTP ${response.status}`);
    }

    document.getElementById('loading-text').textContent = 'Parsing response...';
    const data = await response.json();
    let text = data.choices[0].message.content.trim();

    // Strip markdown fences if the model added them anyway
    text = text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();

    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      // Fallback: extract JSON object or array from mixed text
      const objMatch = text.match(/\{[\s\S]*\}/);
      const arrMatch = text.match(/\[[\s\S]*\]/);
      if (objMatch)      parsed = JSON.parse(objMatch[0]);
      else if (arrMatch) parsed = { schedule: JSON.parse(arrMatch[0]), summary: null };
      else throw new Error('Could not parse JSON from response. Raw: ' + text.substring(0, 300));
    }

    // Support both { schedule, summary } and plain array responses
    const classes = Array.isArray(parsed) ? parsed : parsed.schedule;
    const summary = Array.isArray(parsed) ? null   : parsed.summary;

    renderResult(classes, summary);
    document.getElementById('step3').classList.add('done');

  } catch (err) {
    showError('Error: ' + err.message);
    document.getElementById('step3').classList.remove('active');
    document.getElementById('step2').classList.remove('done');
    document.getElementById('step2').classList.add('active');
  } finally {
    btn.disabled = false;
    loading.classList.remove('show');
  }
}

// =====================
// Render Timetable + Summary
// =====================
function renderResult(classes, summary) {
  const section = document.getElementById('result-section');
  section.classList.add('show');
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const uniqueDays    = new Set(classes.map((c) => c.day));
  const uniqueCourses = new Set(classes.map((c) => c.course_code));
  const typeCount     = classes.reduce((acc, c) => {
    const t = normalizeType(c.course_type) || 'Other';
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});

  // Use model-provided summary values if available, else compute from data
  const totalCourses  = summary?.total_courses  ?? uniqueCourses.size;
  const totalSessions = summary?.total_sessions ?? classes.length;
  const daysUsed      = summary?.days_used      ?? [...uniqueDays];
  const notes         = summary?.notes          ?? null;

  document.getElementById('summary-grid').innerHTML = `
    <div class="summary-card">
      <div class="summary-num">${totalSessions}</div>
      <div class="summary-label">Sessions</div>
    </div>
    <div class="summary-card">
      <div class="summary-num">${totalCourses}</div>
      <div class="summary-label">Courses</div>
    </div>
    <div class="summary-card">
      <div class="summary-num">${daysUsed.length}</div>
      <div class="summary-label">Days/Week</div>
    </div>
    <div class="summary-card">
      <div class="summary-num">${Object.keys(typeCount).join('/')}</div>
      <div class="summary-label">Types</div>
    </div>
  `;

  // Render model's reasoning notes below the summary cards
  const existingNotes = document.getElementById('model-notes');
  if (existingNotes) existingNotes.remove();

  if (notes) {
    const notesEl = document.createElement('div');
    notesEl.id = 'model-notes';
    notesEl.style.cssText = `
      background: rgba(124,106,255,0.07);
      border: 1px solid rgba(124,106,255,0.25);
      border-radius: 4px; padding: 14px; margin-bottom: 20px;
      font-size: 0.78rem; color: var(--muted); line-height: 1.7;
    `;
    notesEl.innerHTML = `<strong style="color:var(--accent)">📋 Model Notes:</strong><br>${notes}`;
    document.getElementById('summary-grid').insertAdjacentElement('afterend', notesEl);
  }

  // Build grid map: "DAY|TIME" → [classes]
  const grid = {};
  classes.forEach((c) => {
    const key = `${c.day}|${normalizeTime(c.time)}`;
    if (!grid[key]) grid[key] = [];
    grid[key].push(c);
  });

  let html = '<thead><tr><th>TIME</th>';
  DAYS.forEach((d) => (html += `<th>${d}</th>`));
  html += '</tr></thead><tbody>';

  TIME_SLOTS.forEach((slot) => {
    html += `<tr><td class="time-cell">${slot}</td>`;
    DAYS.forEach((day) => {
      const entries = findEntries(grid, day, slot);
      if (entries.length) {
        html += `<td>`;
        entries.forEach((c) => {
          const typeClass = (normalizeType(c.course_type) || 'other').toLowerCase();
          html += `
            <div class="class-card ${typeClass}">
              <div class="class-name">${c.course_name}</div>
              <div class="class-info">${c.instructor_name || '—'}</div>
              <div>
                <span class="class-badge">${c.group_number}</span>
                <span class="class-badge">${c.class_number || ''}</span>
              </div>
            </div>`;
        });
        html += `</td>`;
      } else {
        html += `<td></td>`;
      }
    });
    html += '</tr>';
  });

  html += '</tbody>';
  document.getElementById('timetable').innerHTML = html;
  document.getElementById('raw-json').textContent = JSON.stringify({ schedule: classes, summary }, null, 2);
}

// =====================
// Utility Functions
// =====================

/** Normalize course type string → 'Lecture' | 'Tutorial' | 'Lab' | null */
function normalizeType(t) {
  if (!t || t === 'null') return null;
  const lower = t.toLowerCase();
  if (lower.includes('lec') || t === '(L)') return 'Lecture';
  if (lower.includes('tut') || t === '(T)') return 'Tutorial';
  if (lower.includes('lab'))                 return 'Lab';
  return t;
}

/** Normalize whitespace in time strings for consistent key comparison */
function normalizeTime(t) {
  if (!t) return t;
  return t.replace(/\s+/g, ' ').trim();
}

/** Find grid entries for a day + slot, with fuzzy whitespace-insensitive time matching */
function findEntries(grid, day, slot) {
  const key = `${day}|${slot}`;
  if (grid[key]) return grid[key];
  const results = [];
  Object.keys(grid).forEach((k) => {
    const [d, t] = k.split('|');
    if (d === day && timesMatch(t, slot)) results.push(...grid[k]);
  });
  return results;
}

/** Compare two time strings ignoring all whitespace */
function timesMatch(a, b) {
  const norm = (s) => s.replace(/\s/g, '').toLowerCase();
  return norm(a) === norm(b);
}

function showError(msg) {
  const box = document.getElementById('error-box');
  box.textContent = msg;
  box.classList.add('show');
}

function hideError() {
  document.getElementById('error-box').classList.remove('show');
}

function toggleJson() {
  document.getElementById('raw-json').classList.toggle('show');
}
