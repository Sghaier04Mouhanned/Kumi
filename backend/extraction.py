"""Turns uploaded timetable photos into structured ClassSession rows.

Each photo is parsed + extracted independently via LandingAI ADE (reusing
the same schema as image_to_json/), then normalized and merged into one
deduplicated list. Nothing is written to disk or persisted -- results only
ever live in the response for that request.
"""

import asyncio
from collections import defaultdict

from fastapi import UploadFile
from landingai_ade import AsyncLandingAIADE

from backend.config import settings
from backend.models import ClassSession, ExtractWarning, ReconcileSuggestion
from backend.reconcile import reconcile
from image_to_json.schema import schema_json
from normalize import merge_contiguous_sessions, normalize_schedule

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"}

# Department standard: every course is a 3-hour weekly block except
# Tutorials, which run shorter. Used only as a review-step hint --
# never blocks generation, since it's a heuristic, not a hard rule.
EXPECTED_COURSE_MINUTES = 180


def _is_tutorial(course_type: str | None) -> bool:
    if not course_type:
        return False
    t = course_type.strip().lower()
    return "tut" in t or t in ("(t)", "t")


def _minutes(time_str: str) -> int:
    hours, mins = time_str.split(":")
    return int(hours) * 60 + int(mins)


def _validate_durations(classes: list[ClassSession]) -> list[ExtractWarning]:
    groups: dict[tuple[str, str], list[ClassSession]] = defaultdict(list)
    for item in classes:
        if _is_tutorial(item.course_type):
            continue
        groups[(item.course_code, item.group_number)].append(item)

    warnings = []
    for (code, group), items in groups.items():
        total = sum(_minutes(i.time_end) - _minutes(i.time_start) for i in items)
        if total != EXPECTED_COURSE_MINUTES:
            hours, mins = divmod(total, 60)
            warnings.append(ExtractWarning(
                filename="(validation)",
                message=f"{code} ({group}) totals {hours}h{mins:02d}m of non-tutorial sessions, expected 3h "
                        "-- a session may be missing or misread. Check the review table.",
            ))
    return warnings


def _dedupe(classes: list[ClassSession]) -> list[ClassSession]:
    seen: set[tuple[str, str, str, str, str, str]] = set()
    result = []
    for item in classes:
        key = (
            item.course_code, item.group_number, item.day,
            item.time_start, item.time_end, item.instructor_name or "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


async def _extract_one(client: AsyncLandingAIADE, file: UploadFile, group_override: str) -> tuple[str, list[dict]]:
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValueError(f"file exceeds {settings.max_upload_size_mb}MB limit")

    parse_result = await client.parse(
        document=(file.filename or "upload.jpg", content, file.content_type or "image/jpeg"),
        model=settings.parse_model,
    )
    extraction_result = await client.extract(
        schema=schema_json,
        markdown=parse_result.markdown,
        model=settings.extract_model,
    )

    data = extraction_result.extraction or {}
    extracted_group = (data.get("group_info") or {}).get("group_number")
    # LandingAI's group_info extraction is unreliable between runs (confirmed:
    # the same photo returned "G1" once and nothing the next time), so a
    # group label the uploader typed in for this photo wins when given.
    group_number = group_override.strip() or extracted_group or "UNKNOWN"
    schedule = data.get("schedule") or []
    return group_number, schedule


async def extract_from_uploads(
    files: list[UploadFile], group_labels: list[str] | None = None
) -> tuple[list[ClassSession], list[ExtractWarning], list[ReconcileSuggestion], str | None]:
    client = AsyncLandingAIADE(apikey=settings.vision_agent_api_key or None)
    labels = group_labels or [""] * len(files)

    async def run(file: UploadFile, label: str):
        try:
            return await _extract_one(client, file, label)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a per-file warning
            return exc

    raw_results = await asyncio.gather(*(run(f, label) for f, label in zip(files, labels)))

    all_items: list[dict] = []
    warnings: list[ExtractWarning] = []

    for file, result in zip(files, raw_results):
        if isinstance(result, Exception):
            warnings.append(ExtractWarning(filename=file.filename or "unknown", message=str(result)))
            continue

        group_number, schedule = result
        try:
            normalized = normalize_schedule(schedule, group_number)
            # Merge per-photo first: a course split across adjacent grid
            # time-slots only ever happens within one photo's table.
            all_items.extend(merge_contiguous_sessions(normalized))
        except Exception as exc:  # noqa: BLE001
            warnings.append(ExtractWarning(filename=file.filename or "unknown", message=f"normalization failed: {exc}"))

    seen: set[tuple[str, str, str, str, str, str]] = set()
    deduped: list[ClassSession] = []
    for item in all_items:
        key = (
            item.get("course_code", ""),
            item.get("group_number", ""),
            item.get("day", ""),
            item.get("time_start", ""),
            item.get("time_end", ""),
            item.get("instructor_name", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        try:
            deduped.append(ClassSession(**item))
        except Exception as exc:  # noqa: BLE001 - malformed row from a bad extraction
            warnings.append(ExtractWarning(filename="(extraction)", message=f"dropped malformed row: {exc}"))

    deduped, suggestions, reconcile_note = await reconcile(deduped)
    # Reconciliation can make two previously-distinct rows fully identical
    # (e.g. two spellings of the same instructor on the same session) --
    # dedupe again now that labels are canonicalized.
    deduped = _dedupe(deduped)
    warnings.extend(_validate_durations(deduped))

    return deduped, warnings, suggestions, reconcile_note
