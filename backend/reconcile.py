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

import json

import httpx

from backend.config import settings
from backend.models import ClassSession, ReconcileSuggestion

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You clean up course and instructor data extracted via OCR from a \
university timetable photo. OCR sometimes misreads a digit or letter, so the same real \
course or professor can appear under two or more slightly different spellings (e.g. \
"MIS20" and "MIS200" both being "Management Information Systems", or "R. Esghaier" and \
"R. Esghair" being the same person).

Find such duplicates and propose one canonical value for each group. Only group entries \
you are confident refer to the exact same real-world course or person -- never group \
genuinely different courses (e.g. CS220 and CS221 are different courses) or different \
people who happen to share a surname. If you are not fully sure, mark confidence as "low" \
rather than omitting the group -- a human will review low-confidence groups before anything \
is merged. Respond with a JSON object only, no other text."""


def _build_user_prompt(course_entries: list[dict], instructor_entries: list[dict]) -> str:
    return f"""Courses (id, code, name):
{json.dumps(course_entries)}

Instructors (id, name):
{json.dumps(instructor_entries)}

Return JSON exactly in this shape:
{{
  "course_groups": [{{"member_ids": [0, 2], "canonical_code": "...", "canonical_name": "...", "confidence": "high", "reason": "..."}}],
  "instructor_groups": [{{"member_ids": [0, 2], "canonical_name": "...", "confidence": "high", "reason": "..."}}]
}}

Only include a group when you found 2 or more ids that are the same real course/person. \
Omit anything with no duplicate. confidence must be "high" or "low"."""


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
    if len(course_list) < 2 and len(instructor_list) < 2:
        return classes, [], None

    course_entries = [{"id": i, "code": c, "name": n} for i, (c, n) in enumerate(course_list)]
    instructor_entries = [{"id": i, "name": n} for i, n in enumerate(instructor_list)]

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
                json={
                    "model": settings.groq_model,
                    "temperature": 0.1,
                    "max_tokens": 2000,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": _build_user_prompt(course_entries, instructor_entries)},
                    ],
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_response(content)
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
