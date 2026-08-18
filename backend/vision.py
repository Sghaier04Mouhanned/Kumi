"""Turns one timetable photo into raw (group_number, schedule) data via
Gemini's free tier. Plain REST over httpx, same lightweight pattern as
reconcile.py -- no SDK dependency.

This replaces the LandingAI ADE integration, which kept running out of
its (small, paid) quota during normal development/testing. Gemini's free
tier is generous enough for a low-traffic student project.
"""

import base64
import json

import httpx

from backend.config import settings

GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_INSTRUCTION = """You extract structured class schedule data from a photo of a \
university timetable board or grid. Read every visible session carefully: course name, \
course code, course type (Lecture/Tutorial/Lab, if shown -- often abbreviated like "(L)" or \
"(T)"), instructor name, room/class number, day of week, and time range. Preserve the day and \
time text exactly as printed on the photo, including its format (do not reformat or guess at \
24-hour time). If a group/section number (e.g. "G1", "G13") is visible, usually in a header or \
label on the photo, put it in group_info.group_number; otherwise leave it empty. Do not invent \
or guess at sessions that are not actually visible in the photo."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "group_info": {
            "type": "OBJECT",
            "properties": {
                "group_number": {"type": "STRING"},
                "level": {"type": "STRING"},
                "academic_year": {"type": "STRING"},
                "semester": {"type": "STRING"},
            },
        },
        "schedule": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "course_name": {"type": "STRING"},
                    "course_code": {"type": "STRING"},
                    "course_type": {"type": "STRING"},
                    "instructor_name": {"type": "STRING"},
                    "class_number": {"type": "STRING"},
                    "day": {"type": "STRING"},
                    "time": {"type": "STRING"},
                },
                "required": ["course_name", "course_code", "day", "time"],
            },
        },
    },
    "required": ["schedule"],
}


async def extract_photo(content: bytes, mime_type: str) -> tuple[str | None, list[dict]]:
    """Returns (group_number_or_None, schedule_rows) -- raises on failure, same
    contract the caller previously got from the LandingAI parse+extract pair."""
    url = GEMINI_URL_TEMPLATE.format(model=settings.gemini_model)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
                "contents": [{
                    "parts": [
                        {"text": "Extract this timetable photo into the required JSON shape."},
                        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(content).decode("ascii")}},
                    ],
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "response_mime_type": "application/json",
                    "response_schema": RESPONSE_SCHEMA,
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)

    group_number = (parsed.get("group_info") or {}).get("group_number") or None
    schedule = parsed.get("schedule") or []
    return group_number, schedule
