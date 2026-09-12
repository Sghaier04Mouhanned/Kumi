"""Turns uploaded timetable photos into structured ClassSession rows.

Each photo is parsed + extracted independently via Gemini (backend/vision.py),
then normalized and merged into one deduplicated list. Nothing is written to
disk or persisted beyond the extraction cache -- results only ever live in
the response for that request.
"""

import asyncio
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from fastapi import UploadFile

from backend import vision
from backend.config import settings
from backend.models import ClassSession, ExtractWarning, ReconcileSuggestion
from backend.reconcile import reconcile
from normalize import merge_contiguous_sessions, normalize_schedule

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"}
# Confirmed on a real 12-photo upload against the live deploy: even 3
# concurrent Gemini calls was enough to trip the free tier's rate limit
# repeatedly -- several photos exhausted their whole retry budget and
# dropped out entirely, and the ones that did succeed took 60-90+ seconds
# fighting through 429s. Serializing every call to Gemini is slower
# end-to-end, but each individual call is far less likely to get
# rate-limited in the first place.
MAX_CONCURRENT_EXTRACTIONS = 1
PHOTO_PACING_SECONDS = 3.0

# Keyed by the exact bytes of the uploaded photo -- the same image is never
# sent to the vision API twice. Repeated dev/test runs with the same file
# were burning through quota for no reason.
CACHE_DIR = Path(__file__).resolve().parent.parent / ".extraction_cache"


def _cache_path(content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    return CACHE_DIR / f"{digest}.json"

# Department standard: every course is a 3-hour weekly block except
# Tutorials, which run shorter. Used only as a review-step hint --
# never blocks generation, since it's a heuristic, not a hard rule.
EXPECTED_COURSE_MINUTES = 180


def _minutes(time_str: str) -> int:
    hours, mins = time_str.split(":")
    return int(hours) * 60 + int(mins)


# Confirmed on real data: gemini-3.5-flash-lite leaves course_type blank
# more often than the full model did, and a blank type used to make this
# check treat the session as a lecture by default -- so a genuine tutorial
# with no type label got counted toward the "should total 3h" expectation
# alongside its course's real lecture, producing a false "session may be
# missing or misread" warning on data that was actually fine. Falling back
# to duration when the type is blank (TBS tutorials run ~1.5h, lectures
# run a full 3h) fixes that without ever touching the course_type shown to
# the student -- this only affects this heuristic's own bookkeeping.
PROBABLE_TUTORIAL_MAX_MINUTES = 105


def _is_tutorial(item: ClassSession) -> bool:
    if item.course_type:
        t = item.course_type.strip().lower()
        return "tut" in t or t in ("(t)", "t")
    return _minutes(item.time_end) - _minutes(item.time_start) <= PROBABLE_TUTORIAL_MAX_MINUTES


def _validate_durations(classes: list[ClassSession]) -> list[ExtractWarning]:
    groups: dict[tuple[str, str], list[ClassSession]] = defaultdict(list)
    for item in classes:
        if _is_tutorial(item):
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


async def _extract_one(file: UploadFile, group_override: str) -> tuple[str, list[dict]]:
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValueError(f"file exceeds {settings.max_upload_size_mb}MB limit")

    cache_path = _cache_path(content)
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        extracted_group = cached.get("group_number")
        schedule = cached.get("schedule") or []
        print(f"[extraction cache] hit for {file.filename} ({cache_path.name}) -- vision API not called")
    else:
        extracted_group, schedule = await vision.extract_photo(content, file.content_type or "image/jpeg")

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"group_number": extracted_group, "schedule": schedule}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[extraction cache] miss for {file.filename} -- called vision API, cached as {cache_path.name}")

    # Vision extraction of the group/section label is unreliable between runs
    # (confirmed with the previous provider: same photo, different results),
    # so a group label the uploader typed in for this photo wins when given.
    group_number = group_override.strip() or extracted_group or "UNKNOWN"
    return group_number, schedule


async def extract_from_uploads(
    files: list[UploadFile], group_labels: list[str] | None = None
) -> tuple[list[ClassSession], list[ExtractWarning], list[ReconcileSuggestion], str | None]:
    labels = group_labels or [""] * len(files)

    # See MAX_CONCURRENT_EXTRACTIONS above for why this is 1, not a larger
    # number that would let a multi-photo upload run faster.
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)

    async def run(file: UploadFile, label: str):
        async with semaphore:
            try:
                result = await _extract_one(file, label)
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a per-file warning
                result = exc
            # Confirmed against Google AI Studio's own usage dashboard: the
            # error rate spikes line up exactly with bursts of activity and
            # recover within minutes right after -- a short rate-limit
            # window, not a hard daily quota. Serializing calls stops
            # concurrent bursts, but a fast, successful call was still
            # immediately followed by the next one with zero gap. This
            # keeps a multi-photo upload paced even when every call
            # succeeds on the first try and would otherwise have no reason
            # to pause at all.
            await asyncio.sleep(PHOTO_PACING_SECONDS)
            return result

    raw_results = await asyncio.gather(*(run(f, label) for f, label in zip(files, labels)))

    all_items: list[dict] = []
    warnings: list[ExtractWarning] = []

    for file, result in zip(files, raw_results):
        if isinstance(result, Exception):
            # Some exceptions (a plain timeout, for one) stringify to an
            # empty string -- fall back to the exception's type name so the
            # warning is never just blank and undiagnosable.
            message = str(result) or type(result).__name__
            warnings.append(ExtractWarning(filename=file.filename or "unknown", message=message))
            continue

        group_number, schedule = result
        try:
            normalized, skipped_rows = normalize_schedule(schedule, group_number)
            for skipped_item, reason in skipped_rows:
                label = skipped_item.get("course_code") or skipped_item.get("course_name") or "a row"
                warnings.append(ExtractWarning(
                    filename=file.filename or "unknown",
                    message=f"Couldn't read the time for {label} ({reason}) -- add it manually in the review table.",
                ))
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

    deduped, reconcile_warnings, suggestions, reconcile_note = await reconcile_and_validate(deduped)
    warnings.extend(reconcile_warnings)

    return deduped, warnings, suggestions, reconcile_note


async def reconcile_and_validate(
    classes: list[ClassSession],
) -> tuple[list[ClassSession], list[ExtractWarning], list[ReconcileSuggestion], str | None]:
    """Shared tail of the pipeline: AI cleanup + dedupe + duration check.

    Split out so /api/reconcile can re-run just this part (e.g. after a
    Groq rate limit) without re-calling the vision API on the photos again.
    """
    classes, suggestions, reconcile_note = await reconcile(classes)
    # Reconciliation can make two previously-distinct rows fully identical
    # (e.g. two spellings of the same instructor on the same session) --
    # dedupe again now that labels are canonicalized.
    classes = _dedupe(classes)
    warnings = _validate_durations(classes)
    return classes, warnings, suggestions, reconcile_note
