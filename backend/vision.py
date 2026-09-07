"""Turns one timetable photo into raw (group_number, schedule) data via
Gemini's free tier. Plain REST over httpx, same lightweight pattern as
reconcile.py -- no SDK dependency.

This replaces the LandingAI ADE integration, which kept running out of
its (small, paid) quota during normal development/testing. Gemini's free
tier is generous enough for a low-traffic student project.
"""

import asyncio
import base64
import json
import random

import httpx

from backend.config import settings

GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Confirmed on a real 10-photo batch: firing every upload concurrently blew
# through Gemini's free-tier rate limit and overloaded it (5 of 10 photos
# failed with 429/503), and there was no retry at all -- one rate-limit hit
# just silently lost that photo's data. Exponential backoff with jitter so
# several photos retrying at once don't all collide on the same instant.
MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 3.0
RETRYABLE_STATUS_CODES = {429, 503}

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
    payload = {
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
    }

    # The key goes in a header, not a "?key=..." query param -- confirmed on
    # a real deploy: httpx's own exception message on a failed request
    # includes the full request URL, and that message was flowing straight
    # into the API's error response. A query-param key would leak into that
    # response (and into any request logging) the moment a call ever fails.
    headers = {"x-goog-api-key": settings.gemini_api_key}

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(MAX_RETRIES + 1):
            # Confirmed on a real deploy under heavy load: Gemini can be slow
            # enough to trip the 60s client timeout before ever returning a
            # response at all, not just return a 429/503. That's a network
            # exception, not an HTTP status, so it was skipping the retry
            # logic entirely -- and its own message stringifies to nothing
            # useful (an empty string for a plain timeout), producing a
            # blank, undiagnosable warning. Treat it exactly like a
            # retryable status instead of letting it escape uncaught.
            try:
                resp = await client.post(url, headers=headers, json=payload)
            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    wait = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 1.5)
                    await asyncio.sleep(min(wait, 30.0))
                    continue
                raise RuntimeError(f"Gemini request timed out after {MAX_RETRIES + 1} attempts")

            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after else BASE_BACKOFF_SECONDS * (2 ** attempt)
                wait += random.uniform(0, 1.5)  # jitter so concurrent photos don't retry in lockstep
                await asyncio.sleep(min(wait, 30.0))
                continue
            if resp.is_error:
                # Sanitized on purpose -- never let httpx's own exception
                # message (which includes the full request URL) reach the
                # client, as a second line of defense beyond moving the key
                # out of the URL above.
                raise RuntimeError(f"Gemini request failed with status {resp.status_code}")
            data = resp.json()
            break

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)

    group_number = (parsed.get("group_info") or {}).get("group_number") or None
    schedule = parsed.get("schedule") or []
    return group_number, schedule
