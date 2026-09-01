# Kumi: University Timetable Optimizer

Kumi generates a personalized weekly timetable from a photo of your
university's timetable board. Upload one or more photos, pick your
required courses, set hard constraints and soft preferences, and get
back the best valid schedule — computed by a deterministic backtracking
search, not an LLM.

## How it works

```
Photo(s) of timetable  --[Gemini]-->  structured class data
        |
        v
Review & correct extracted data (extraction isn't perfect)
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
only in the browser for that session. There's no database.

## Project layout

```
backend/
  main.py         # FastAPI app: /api/extract, /api/generate, serves frontend/
  extraction.py   # Orchestrates: vision.py -> normalize -> merge -> dedupe -> reconcile -> validate
  vision.py        # Photo -> raw structured data (Gemini)
  reconcile.py     # AI cleanup of duplicate/misread course & instructor labels (Groq)
  solver.py       # Backtracking search + weighted soft-preference scoring
  models.py       # Pydantic request/response schemas
  config.py       # Settings (API keys, CORS, models)
data/
  tbs_catalog.json # TBS's real course catalog, used to ground reconciliation
frontend/
  index.html, main.js, style.css   # Static UI, no build step
normalize.py      # Field normalization (day names, time format, course codes)
```

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
   optional AI reconciliation pass — extraction still works without it,
   just without duplicate-label cleanup.

3. Start the server from the project root (module mode so `backend/`
   can import the root-level `image_to_json/` and `normalize.py`):
   ```bash
   python -m uvicorn backend.main:app --reload
   ```

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
