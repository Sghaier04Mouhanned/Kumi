"""Optional post-extraction cleanup pass: asks an open-source model (via
Groq's free tier) to spot course codes/names or instructor names that are
almost certainly OCR noise on the same real entity (e.g. "MIS20" vs
"MIS200"), and propose one canonical value for each.

This is deliberately kept out of the scheduling path -- the solver never
sees or trusts an LLM. It only cleans up duplicate labels before the
student picks courses. High-confidence groupings are applied directly
(with the original value preserved per row so the review table can offer
an undo); low-confidence ones are returned as suggestions the student
applies manually.
"""

import asyncio
import difflib
import json
from pathlib import Path

import httpx

from backend.config import settings
from backend.models import ClassSession, ReconcileSuggestion

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "tbs_catalog.json"

# Groq's free tier rate-limits under normal testing load (confirmed: hit
# repeatedly during this project's own dev/test cycles). A 429 is usually
# transient, so retry with backoff before giving up and skipping cleanup.
MAX_RATE_LIMIT_RETRIES = 2
RATE_LIMIT_BACKOFF_SECONDS = 5.0

CLOSEST_MATCH_COUNT = 2
CLOSEST_MATCH_MIN_SIMILARITY = 0.55  # below this, not worth showing the model as a hint


def _load_catalog() -> dict[str, str]:
    """code -> name, or {} if the catalog file isn't present (feature degrades gracefully)."""
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return {c["code"]: c["name"] for c in data.get("courses", [])}
    except Exception:  # noqa: BLE001
        return {}


_CATALOG = _load_catalog()


def _closest_catalog_codes(code: str) -> list[dict]:
    if code in _CATALOG or not _CATALOG:
        return []
    scored = sorted(
        ((difflib.SequenceMatcher(None, code, c).ratio(), c) for c in _CATALOG),
        reverse=True,
    )
    return [
        {"code": c, "name": _CATALOG[c], "similarity": round(ratio, 2)}
        for ratio, c in scored[:CLOSEST_MATCH_COUNT]
        if ratio >= CLOSEST_MATCH_MIN_SIMILARITY
    ]

SYSTEM_PROMPT = """You clean up course and instructor data extracted via OCR from a \
university timetable photo. OCR sometimes misreads letters or digits, so the same real \
course or professor can appear under two or more different-looking spellings -- not just \
small typos. Examples: "MIS20" and "MIS200" are both "Management Information Systems"; \
"R. Esghaier" and "R. Esghair" are the same person; "BCOR200" and "BOOK200" can be the same \
course misread (C/R confused with O/K), especially when other evidence supports it.

Each course entry lists its sessions (day, time, group). A single student group cannot \
physically attend two different courses at the same day and time, so if two course-code \
variants share a session with the exact same day, time, and group, treat that as strong \
extra evidence they are the same real course read two different ways. But the reverse is \
NOT evidence against merging: two variants having no matching day/time/group is completely \
expected both when they are two different groups/sections of the same course (which \
naturally meet at different times) and when they are genuinely different courses -- it \
tells you nothing either way, so fall back to code and name similarity as your primary \
signal in that case, same as if session data were not there at all.

Find such duplicates and propose one canonical value for each group. For the canonical \
value, prefer one of the input variants exactly as given rather than inventing a new \
spelling -- only deviate from the given variants if the other entries in this list, or the \
closest_catalog_matches hints described below, give you clear evidence of the correct form. \
Only group entries you are confident refer to the exact same real-world course or person -- \
never group genuinely different courses (e.g. CS220 and CS221 are different courses) or different \
people who happen to share a surname. If you are not fully sure, mark confidence as "low" \
rather than omitting the group -- a human will review low-confidence groups before anything \
is merged.

Some course entries also carry a closest_catalog_matches list: the most similar course codes \
from this university's official course catalog, each with a similarity score (0-1) and that \
catalog course's name. Use this carefully -- the catalog is one specific edition and may be \
missing courses added since, so an entry's absence from the catalog is only weak evidence by \
itself, not proof the code is wrong.

Crucially, this school's course codes are Department-Prefix + Level-Digit + Unique-Digit (e.g. \
CS220: level 2, unique id 20). The department deliberately mints new, related courses by \
changing only that trailing numeric part -- CS220 and CS221 are meant to look almost identical \
as codes precisely because the numbering system works that way, not because one is a typo of \
the other. So a close match that differs only in the numeric suffix is weak evidence of an OCR \
error and should rarely reach high confidence on code-similarity alone -- prefer "low" unless \
you have real corroborating evidence (matching session day/time/group with a same-named entry \
elsewhere, or the course name is obviously wrong/nonsensical for that code). A close match that \
differs in the DEPARTMENT LETTERS instead (e.g. BOOK200 vs BCOR200) is a much stronger signal, \
since those letters aren't part of any incrementing scheme and OCR letter confusion is common -- \
that case can reach high confidence on its own, even for a single unpaired entry.

For the canonical value, prefer one of the input variants exactly as given rather than \
inventing a new spelling -- only deviate if the other entries in this list, or a catalog hint \
above the bar just described, give you clear evidence of the correct form. Note that course \
NAMES can legitimately differ from the catalog (this catalog edition may predate a course \
rename), so use catalog hints to fix the CODE only; never suggest overwriting a course's name \
with the catalog's name for this reason alone.

Find such duplicates and propose one canonical value for each group. Only group entries you \
are confident refer to the exact same real-world course or person -- never group genuinely \
different courses or different people who happen to share a surname. If you are not fully \
sure, mark confidence as "low" rather than omitting the group -- a human will review \
low-confidence groups before anything is merged. Report catalog-based code fixes as a separate \
"catalog_corrections" list, not as a course_group (course_group is for clustering multiple \
extracted entries together; a catalog_correction can apply to a single entry with no duplicate \
elsewhere in the data). Do not report a catalog_correction for an entry whose code already \
exactly matches the catalog. Respond with a JSON object only, no other text."""


def _build_user_prompt(course_entries: list[dict], instructor_entries: list[dict]) -> str:
    return f"""Courses (id, code, name, sessions=[day,time,group], closest_catalog_matches=[{{code,name,similarity}}]):
{json.dumps(course_entries)}

Instructors (id, name):
{json.dumps(instructor_entries)}

Return JSON exactly in this shape:
{{
  "course_groups": [{{"member_ids": [0, 2], "canonical_code": "...", "canonical_name": "...", "confidence": "high", "reason": "..."}}],
  "instructor_groups": [{{"member_ids": [0, 2], "canonical_name": "...", "confidence": "high", "reason": "..."}}],
  "catalog_corrections": [{{"id": 3, "corrected_code": "...", "confidence": "high", "reason": "..."}}]
}}

Only include a course_group/instructor_group when you found 2 or more ids that are the same \
real course/person. Only include a catalog_correction when an entry's code doesn't already \
match the catalog but clearly should. Omit anything with no finding. confidence must be \
"high" or "low"."""


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


async def reconcile(classes: list[ClassSession]) -> tuple[list[ClassSession], list[ReconcileSuggestion], str | None]:
    if not settings.groq_api_key:
        return classes, [], "AI cleanup skipped: GROQ_API_KEY not configured."

    course_keys: dict[tuple[str, str], list[int]] = {}
    instructor_keys: dict[str, list[int]] = {}
    for idx, item in enumerate(classes):
        course_keys.setdefault((item.course_code, item.course_name), []).append(idx)
        if item.instructor_name:
            instructor_keys.setdefault(item.instructor_name, []).append(idx)

    course_list = list(course_keys.keys())
    instructor_list = list(instructor_keys.keys())

    course_entries = []
    any_catalog_hint = False
    for i, (c, n) in enumerate(course_list):
        hints = _closest_catalog_codes(c)
        any_catalog_hint = any_catalog_hint or bool(hints)
        entry = {
            "id": i,
            "code": c,
            "name": n,
            "sessions": [
                [classes[idx].day, classes[idx].time_start, classes[idx].group_number]
                for idx in course_keys[(c, n)]
            ],
        }
        if hints:
            entry["closest_catalog_matches"] = hints
        course_entries.append(entry)

    instructor_entries = [{"id": i, "name": n} for i, n in enumerate(instructor_list)]

    # Nothing to compare against another entry, and no catalog hint on any solo
    # entry either -- calling the model would find nothing.
    if len(course_list) < 2 and len(instructor_list) < 2 and not any_catalog_hint:
        return classes, [], None

    payload = {
        "model": settings.groq_model,
        "temperature": 0.1,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(course_entries, instructor_entries)},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
                resp = await client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                    wait = float(resp.headers.get("retry-after", RATE_LIMIT_BACKOFF_SECONDS))
                    await asyncio.sleep(min(wait, 15.0))
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = _parse_json_response(content)
                break
    except Exception as exc:  # noqa: BLE001 - never let cleanup break extraction
        return classes, [], f"AI cleanup skipped: {exc}"

    suggestions: list[ReconcileSuggestion] = []

    for group in parsed.get("course_groups", []):
        member_ids = group.get("member_ids", [])
        if len(member_ids) < 2:
            continue
        variants = [course_list[i] for i in member_ids if 0 <= i < len(course_list)]
        if len(variants) < 2:
            continue
        to_code, to_name = group.get("canonical_code", ""), group.get("canonical_name", "")
        if not to_code or not to_name:
            continue

        if group.get("confidence") == "high":
            for code, name in variants:
                for idx in course_keys[(code, name)]:
                    item = classes[idx]
                    if item.course_code != to_code or item.course_name != to_name:
                        item.original_course_code = item.original_course_code or item.course_code
                        item.original_course_name = item.original_course_name or item.course_name
                        item.course_code = to_code
                        item.course_name = to_name
        else:
            suggestions.append(ReconcileSuggestion(
                field="course",
                variants=[f"{c} ({n})" for c, n in variants],
                canonical=f"{to_code} ({to_name})",
                reason=group.get("reason", ""),
            ))

    for correction in parsed.get("catalog_corrections", []):
        entry_id = correction.get("id")
        corrected_code = correction.get("corrected_code", "")
        if entry_id is None or not corrected_code or not (0 <= entry_id < len(course_list)):
            continue
        code, name = course_list[entry_id]
        if code == corrected_code:
            continue

        if correction.get("confidence") == "high":
            for idx in course_keys[(code, name)]:
                item = classes[idx]
                if item.course_code != corrected_code:
                    item.original_course_code = item.original_course_code or item.course_code
                    item.course_code = corrected_code
        else:
            suggestions.append(ReconcileSuggestion(
                field="course_code",
                variants=[code],
                canonical=corrected_code,
                reason=correction.get("reason", ""),
            ))

    for group in parsed.get("instructor_groups", []):
        member_ids = group.get("member_ids", [])
        if len(member_ids) < 2:
            continue
        variants = [instructor_list[i] for i in member_ids if 0 <= i < len(instructor_list)]
        if len(variants) < 2:
            continue
        to_name = group.get("canonical_name", "")
        if not to_name:
            continue

        if group.get("confidence") == "high":
            for name in variants:
                for idx in instructor_keys[name]:
                    item = classes[idx]
                    if item.instructor_name != to_name:
                        item.original_instructor_name = item.original_instructor_name or item.instructor_name
                        item.instructor_name = to_name
        else:
            suggestions.append(ReconcileSuggestion(
                field="instructor", variants=list(variants), canonical=to_name, reason=group.get("reason", ""),
            ))

    return classes, suggestions, None
