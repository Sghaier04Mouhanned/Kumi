# Kumi: University Timetable Optimizer

Kumi generates a personalized weekly timetable from a photo of your
university's timetable board. Upload one or more photos, pick your
required courses, set hard constraints and soft preferences, and get
back the best valid schedule — computed by a deterministic backtracking
search, not an LLM. Currently tuned for Tunis Business School (TBS),
built to generalize to other schools later.

## How it works

```
Photo(s) of timetable  --[Gemini]-->  raw structured class data
        |
        v
Normalize + merge sessions split across adjacent grid time-slots
        |
        v
Optional AI cleanup (Groq, grounded on TBS's real course catalog):
auto-corrects confident duplicate/misread course & instructor labels,
flags uncertain ones as suggestions, everything undoable
        |
        v
Review & correct extracted data in the browser (extraction isn't perfect)
        |
        v
Select required courses + hard constraints + soft preferences
        |
        v
Backtracking search (hard constraints) + weighted scoring (soft preferences)
        |
        v
Best timetable(s), rendered as a weekly calendar
```

Nothing is persisted server-side — extracted data and preferences live
only in the browser for that session. There's no database. The one
exception is a local disk cache keyed by each photo's content hash, so
the same photo is never re-sent to Gemini twice (see below).

## Project layout

```
backend/
  main.py         # FastAPI app: /api/extract, /api/reconcile, /api/generate, serves frontend/
  extraction.py   # Orchestrates: vision.py -> normalize -> merge -> dedupe -> reconcile -> validate -> cache
  vision.py       # Photo -> raw structured data (Gemini)
  reconcile.py    # AI cleanup of duplicate/misread course & instructor labels (Groq)
  solver.py       # Backtracking search + weighted soft-preference scoring
  models.py       # Pydantic request/response schemas
  config.py       # Settings (API keys, CORS, models)
data/
  tbs_catalog.json # TBS's real course catalog, used to ground reconciliation
frontend/
  index.html, main.js, style.css   # Static UI, no build step
normalize.py      # Field normalization (day names, time format, course codes)
.extraction_cache/ # Gitignored. One JSON file per photo (by SHA-256 of its
                    # bytes) so re-uploading the same file never re-bills Gemini.
                    # Safe to delete anytime to force a fresh extraction.
```

## Data quality & AI cleanup

Photo extraction is inherently noisy (OCR/vision misreads, split table
cells, inconsistent group labels), so several layers handle that
before a student ever picks a course:

- **Contiguous-slot merging** — a course drawn across several adjacent
  grid columns (e.g. a 3-hour lecture split into three 1-hour cells)
  is collapsed back into one session.
- **Duration validation** — every non-Tutorial course is expected to
  total 3 hours a week (TBS's standard); anything that doesn't shows
  up as a warning in the review step, since it usually means a slot
  was missed rather than misread.
- **AI reconciliation (optional, needs `GROQ_API_KEY`)** — groups
  course/instructor label variants that are almost certainly the same
  real entity read differently (e.g. a dropped digit in a course code,
  an abbreviated vs. full instructor name), and grounds course-code
  correction against `data/tbs_catalog.json` so it can catch a bad
  code even with nothing to compare it against. High-confidence
  corrections apply automatically and are undoable (look for the
  undo icon on a corrected cell in the review table); low-confidence
  ones surface as a suggestion you apply manually. If Groq is
  rate-limited or unreachable, extraction still succeeds — cleanup is
  just skipped with a visible notice and a "Retry AI Cleanup" button
  (`POST /api/reconcile`, re-runs cleanup on already-extracted data
  without calling the vision API again).
- **Manual review** — the review table before course selection lets a
  student fix anything the automated layers didn't catch.

## Run locally

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your Gemini key in `.env` at the project root (free tier, no
   billing setup — get one at [aistudio.google.com](https://aistudio.google.com) → API keys):
   ```
   GEMINI_API_KEY=your_key_here
   ```
   Also set `GROQ_API_KEY` (free tier at [console.groq.com](https://console.groq.com)) to enable the
   optional AI reconciliation pass described above — extraction still
   works without it, just without duplicate-label cleanup.

3. Start the server from the project root (module mode so `backend/`
   can import the root-level `normalize.py`):
   ```bash
   python -m uvicorn backend.main:app --reload
   ```
   If port 8000 is already taken by something else on your machine,
   add `--port 8001` (or any free port).

4. Open http://localhost:8000 — the backend serves the frontend directly.

## Deploying

Any Python host works (single service, no database). `render.yaml` is
included for [Render](https://render.com)'s free tier:

1. Push this repo to GitHub, connect it on Render, it picks up
   `render.yaml` automatically.
2. Set the `GEMINI_API_KEY` and `GROQ_API_KEY` environment variables in
   the Render dashboard (kept out of `render.yaml` on purpose — never
   commit them).

Fly.io or Railway work the same way: `pip install -r requirements.txt`
as the build step, `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
as the start command.

## Notes on the scheduling algorithm

- **Hard constraints** (no overlaps, required courses present, blocked
  sections/days/times) are enforced by filtering — a timetable that
  violates one is never a candidate.
- **Soft preferences** (preferred instructor/section, preferred free
  days, avoid early/late, minimize gaps, compactness) are a weighted
  sum over valid candidates only. See `WEIGHTS` in `backend/solver.py`.
- The search orders courses most-constrained-first and is capped at
  50,000 nodes, which is generous for a normal course load; it isn't a
  general-purpose ILP solver by design — see the design discussion in
  this repo's PR history for why that tradeoff was made.
- When no valid timetable exists, the solver runs a pairwise
  compatibility check across selected courses to report *which* two
  courses conflict, rather than just failing.
