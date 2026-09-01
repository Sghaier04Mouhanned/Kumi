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
)
from backend.solver import generate_timetables

app = FastAPI(title="Kumi")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/catalog", response_model=SharedCatalog)
def get_catalog() -> SharedCatalog:
    """The shared timetable everyone loads by default. Empty classes means
    no semester has been published yet -- the frontend falls back to the
    upload flow in that case, not an error state."""
    return catalog_store.load_catalog()


@app.post("/api/catalog", response_model=SharedCatalog)
def publish_catalog(request: PublishCatalogRequest) -> SharedCatalog:
    if not settings.admin_token:
        raise HTTPException(status_code=403, detail="Publishing is disabled (no admin token configured).")
    if not hmac.compare_digest(request.token, settings.admin_token):
        raise HTTPException(status_code=403, detail="Invalid admin token.")
    if not request.classes:
        raise HTTPException(status_code=400, detail="No classes to publish.")

    updated_at = datetime.now(timezone.utc).isoformat()
    return catalog_store.save_catalog(request.classes, request.semester_label, updated_at)


@app.post("/api/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    if not request.selected_courses:
        raise HTTPException(status_code=400, detail="No courses selected.")
    return generate_timetables(request)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
