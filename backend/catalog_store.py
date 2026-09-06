"""Persisted shared timetable catalog -- the dataset every student loads
by default instead of uploading their own photos. Plain JSON file on
disk, not a database: this is one small, infrequently-written document
(published once per semester by whoever curates it), not a fit for the
concurrency or query needs a real database exists for.

Gitignored -- it's real extracted timetable data tied to a specific
semester, not source code, and it'll be wrong the moment a new semester
starts. Empty/missing is a normal state (no semester published yet),
not an error.
"""

import json
from pathlib import Path

from backend.models import ClassSession, SharedCatalog

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "shared_timetable.json"


def load_catalog() -> SharedCatalog:
    if not CATALOG_PATH.exists():
        return SharedCatalog()
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return SharedCatalog(**data)
    except Exception:  # noqa: BLE001 - a corrupt file should degrade to "no catalog", not 500
        return SharedCatalog()


def save_catalog(classes: list[ClassSession], semester_label: str | None, updated_at: str) -> SharedCatalog:
    catalog = SharedCatalog(classes=classes, updated_at=updated_at, semester_label=semester_label)
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
    return catalog
