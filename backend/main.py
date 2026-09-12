import hmac
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import catalog_store
from backend.config import settings
from backend.extraction import extract_from_uploads, reconcile_and_validate
from backend.models import (
    ExtractResponse,
    GenerateRequest,
    GenerateResponse,
    PublishCatalogRequest,
    ReconcileRequest,
    SharedCatalog,
    UniversitySummary,
)
from backend.solver import generate_timetables

app = FastAPI(title="Kumi")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Confirmed on real testing: the frontend has no build step or versioned
# filenames, so a browser that already loaded index.html/main.js/style.css
# once can keep serving that stale copy from its own cache after a fix
# ships, even on a normal reload -- a shipped bug fix can look like it never
# landed. Force revalidation on every request for anything that isn't the
# API so a change is always picked up on the next reload.
@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract", response_model=ExtractResponse)
async def extract(
    files: list[UploadFile] = File(...),
    group_labels: str = Form("[]"),
) -> ExtractResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    try:
        labels = json.loads(group_labels)
        if not isinstance(labels, list):
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="group_labels must be a JSON array of strings.")

    classes, warnings, suggestions, reconcile_note = await extract_from_uploads(files, labels)

    if not classes and warnings:
        raise HTTPException(status_code=422, detail=[w.message for w in warnings])

    return ExtractResponse(classes=classes, warnings=warnings, suggestions=suggestions, reconcile_note=reconcile_note)


@app.post("/api/reconcile", response_model=ExtractResponse)
async def reconcile_endpoint(request: ReconcileRequest) -> ExtractResponse:
    """Re-runs AI cleanup + validation on already-extracted data, without
    touching the vision API. Lets the client retry after a rate limit
    (Groq's free tier) without spending another photo-extraction call."""
    if not request.classes:
        raise HTTPException(status_code=400, detail="No classes to reconcile.")

    classes, warnings, suggestions, reconcile_note = await reconcile_and_validate(request.classes)
    return ExtractResponse(classes=classes, warnings=warnings, suggestions=suggestions, reconcile_note=reconcile_note)


@app.get("/api/universities", response_model=list[UniversitySummary])
def list_universities() -> list[UniversitySummary]:
    """Every university with a published catalog, so a student can pick
    theirs from a list instead of typing it blind. A university that isn't
    listed just hasn't had anyone publish for it yet -- not an error."""
    return catalog_store.list_universities()


@app.get("/api/catalog", response_model=SharedCatalog)
def get_catalog(university_id: str) -> SharedCatalog:
    """The shared timetable that university's students load by default.
    Empty classes means no semester has been published yet for this
    university -- the frontend falls back to the upload flow in that case,
    not an error state."""
    return catalog_store.load_catalog(university_id)


@app.post("/api/catalog", response_model=SharedCatalog)
def publish_catalog(request: PublishCatalogRequest) -> SharedCatalog:
    if not settings.admin_token:
        raise HTTPException(status_code=403, detail="Publishing is disabled (no admin token configured).")
    if not hmac.compare_digest(request.token, settings.admin_token):
        raise HTTPException(status_code=403, detail="Invalid admin token.")
    if not request.classes:
        raise HTTPException(status_code=400, detail="No classes to publish.")
    if not request.university_name.strip():
        raise HTTPException(status_code=400, detail="University name is required.")

    university_id = request.university_id or catalog_store.slugify_university(request.university_name)
    updated_at = datetime.now(timezone.utc).isoformat()
    return catalog_store.save_catalog(
        university_id, request.university_name, request.classes, request.semester_label, updated_at
    )


@app.delete("/api/catalog/{university_id}")
def delete_catalog(university_id: str, token: str) -> dict[str, str]:
    """Removes a published catalog -- for clearing out a test or mistaken
    publish. Same admin-token gate as publishing; there's no undo."""
    if not settings.admin_token:
        raise HTTPException(status_code=403, detail="Deleting is disabled (no admin token configured).")
    if not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(status_code=403, detail="Invalid admin token.")
    if not catalog_store.delete_catalog(university_id):
        raise HTTPException(status_code=404, detail=f"No catalog published for '{university_id}'.")
    return {"status": "deleted", "university_id": university_id}


# Matches the frontend's own cap (kept here too since a request can bypass
# the UI entirely) -- a realistic max course load, not an arbitrary number.
MAX_SELECTED_COURSES = 7


@app.post("/api/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    if not request.selected_courses:
        raise HTTPException(status_code=400, detail="No courses selected.")
    if len(request.selected_courses) > MAX_SELECTED_COURSES:
        raise HTTPException(status_code=400, detail=f"You can select at most {MAX_SELECTED_COURSES} courses.")
    return generate_timetables(request)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
