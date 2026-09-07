"""Persisted shared timetable catalogs -- one per university, each the
dataset that university's students load by default instead of uploading
their own photos. Plain JSON files on disk, not a database: each one is a
small, infrequently-written document (published once per semester by
whoever curates it for that school), not a fit for the concurrency or
query needs a real database exists for.

Gitignored -- these are real extracted timetable data tied to a specific
university and semester, not source code, and they go stale the moment a
new semester starts. No catalogs published yet is a normal state, not an
error.
"""

import json
import re
from pathlib import Path

from backend.models import ClassSession, SharedCatalog, UniversitySummary

CATALOG_DIR = Path(__file__).resolve().parent.parent / "data" / "catalogs"


def slugify_university(name: str) -> str:
    """Turns a free-typed university name into a stable id, e.g.
    "Tunis Business School" -> "tunis-business-school"."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "university"


def _path(university_id: str) -> Path:
    return CATALOG_DIR / f"{university_id}.json"


def load_catalog(university_id: str) -> SharedCatalog:
    path = _path(university_id)
    if not path.exists():
        return SharedCatalog(university_id=university_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SharedCatalog(**data)
    except Exception:  # noqa: BLE001 - a corrupt file should degrade to "no catalog", not 500
        return SharedCatalog(university_id=university_id)


def save_catalog(
    university_id: str,
    university_name: str,
    classes: list[ClassSession],
    semester_label: str | None,
    updated_at: str,
) -> SharedCatalog:
    catalog = SharedCatalog(
        university_id=university_id,
        university_name=university_name,
        classes=classes,
        updated_at=updated_at,
        semester_label=semester_label,
    )
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    _path(university_id).write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
    return catalog


def list_universities() -> list[UniversitySummary]:
    """Every university with a published (non-empty) catalog -- lets the
    frontend offer a pick list instead of every student having to type
    their university's name from scratch."""
    if not CATALOG_DIR.exists():
        return []
    summaries = []
    for path in sorted(CATALOG_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            catalog = SharedCatalog(**data)
        except Exception:  # noqa: BLE001 - skip a corrupt file rather than failing the whole list
            continue
        if not catalog.classes or not catalog.university_id:
            continue
        summaries.append(UniversitySummary(
            university_id=catalog.university_id,
            university_name=catalog.university_name or catalog.university_id,
            updated_at=catalog.updated_at,
            semester_label=catalog.semester_label,
            group_count=len({c.group_number for c in catalog.classes}),
        ))
    return summaries
