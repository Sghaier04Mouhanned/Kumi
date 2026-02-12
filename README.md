# SchedAI: Automated Class Schedule Extraction

SchedAI is a Python project that extracts structured class schedule information from timetable documents (images/PDFs) using OCR + LLMs. The pipeline converts raw schedules into validated JSON (Pydantic-ready), making it easy to analyze, display, and feed into a downstream schedule builder.

## What this repo currently does

- Extracts schedule information from multiple files in a folder.
- Supports PDF and image input (currently wired for images in `time tables/`).
- Uses **OCR / DPT models** to read text from documents.
- Leverages **LandingAI ADE** extraction to produce structured JSON.
- Validates output using **Pydantic**-compatible JSON schema.
- Handles multiple schedules, instructors, and class types.

---

## Project layout

```
.
├── image_to_json/
│   ├── process_images.py   # Main extraction pipeline
│   └── schema.py           # JSON schema for timetable extraction
├── time tables/            # Input images (you provide)
└── output/                 # Extraction results (auto-created)
```

---

## Setup

1. **Install dependencies** (you may already have them):
   ```bash
   pip install -r requirements.txt
   ```

2. **Set env vars** for LandingAI ADE (example):
   ```bash
   export VISION_AGENT_API_KEY="YOUR_KEY"
   ```
   Or create a `.env` file at the project root.

---

## Run extraction

```bash
python -m image_to_json.process_images
```

- Input images are read from `time tables/`.
- Output JSON is written to `output/`.

Each image produces a file like `output/<image_name>.json`.

---

## What to do **after** you have Pydantic JSON files

Your goal is to combine many group/level timetables (G1, G2, … + levels like Fresh/Sophomore/etc.) and return a **personalized schedule** based on:
- chosen courses,
- preferred professors,
- preferred groups,
- and hard constraints (time conflicts, missing sessions, etc.).

Here’s a practical next-step roadmap:

### 1) Normalize & index the JSON
Create a unified dataset from all extracted JSON files.

- **Normalize fields** (e.g., standardize day names, time format, course codes).
- **Build indexes**:
  - `courses -> available sections`
  - `instructors -> available slots`
  - `group -> schedule items`

This makes it fast to look up options when building a schedule.

### 2) Define constraints and preferences
Split your rules into **hard constraints** (must always hold) and **soft preferences** (nice-to-have).

**Hard constraints** examples:
- No overlapping time slots.
- All required courses must be present.
- If a course has both lecture + lab, both must be scheduled.

**Preferences** examples:
- Prefer Professor X.
- Prefer Group G2.
- Prefer mornings/afternoons.

### 3) Run a schedule builder (constraint solver)
Use either a custom backtracking search or a constraint solver library.

**Simple strategy (start small):**
1. For each required course, list all available sections.
2. Try all combinations (backtracking) while pruning conflicts.
3. Score each valid schedule based on preferences.
4. Pick the highest-scoring schedule.

**If you want an engine:**
- Python: `python-constraint`, `ortools`, or `pulp`

### 4) If no schedule is possible, explain why + give alternatives
When a conflict happens, you should return:

- **Which constraint failed** (e.g., “Course A conflicts with Course B on Tuesday 10:00”).
- **Closest alternatives**, such as:
  - different professor,
  - different group,
  - different day/time slot,
  - or dropping a low-priority course.

This can be done by tracking the conflict set during search.

---

