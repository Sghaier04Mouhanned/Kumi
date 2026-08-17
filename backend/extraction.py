"""Turns uploaded timetable photos into structured ClassSession rows.

Each photo is parsed + extracted independently via LandingAI ADE (reusing
the same schema as image_to_json/), then normalized and merged into one
deduplicated list. Nothing is written to disk or persisted -- results only
ever live in the response for that request.
"""

import asyncio

from fastapi import UploadFile
from landingai_ade import AsyncLandingAIADE

from backend.config import settings
from backend.models import ClassSession, ExtractWarning
from image_to_json.schema import schema_json
from normalize import normalize_schedule

IMAGE_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"}


async def _extract_one(client: AsyncLandingAIADE, file: UploadFile) -> tuple[str, list[dict]]:
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
    group_number = (data.get("group_info") or {}).get("group_number") or "UNKNOWN"
    schedule = data.get("schedule") or []
    return group_number, schedule


async def extract_from_uploads(files: list[UploadFile]) -> tuple[list[ClassSession], list[ExtractWarning]]:
    client = AsyncLandingAIADE(apikey=settings.vision_agent_api_key or None)

    async def run(file: UploadFile):
        try:
            return await _extract_one(client, file)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a per-file warning
            return exc

    raw_results = await asyncio.gather(*(run(f) for f in files))

    all_items: list[dict] = []
    warnings: list[ExtractWarning] = []

    for file, result in zip(files, raw_results):
        if isinstance(result, Exception):
            warnings.append(ExtractWarning(filename=file.filename or "unknown", message=str(result)))
            continue

        group_number, schedule = result
        try:
            all_items.extend(normalize_schedule(schedule, group_number))
        except Exception as exc:  # noqa: BLE001
            warnings.append(ExtractWarning(filename=file.filename or "unknown", message=f"normalization failed: {exc}"))

    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[ClassSession] = []
    for item in all_items:
        key = (item.get("course_code", ""), item.get("group_number", ""), item.get("day", ""), item.get("time", ""))
        if key in seen:
            continue
        seen.add(key)
        try:
            deduped.append(ClassSession(**item))
        except Exception as exc:  # noqa: BLE001 - malformed row from a bad extraction
            warnings.append(ExtractWarning(filename="(extraction)", message=f"dropped malformed row: {exc}"))

    return deduped, warnings
