from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.extraction import extract_from_uploads
from backend.models import ExtractResponse, GenerateRequest, GenerateResponse
from backend.solver import generate_timetables

app = FastAPI(title="SchedAI")

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
async def extract(files: list[UploadFile] = File(...)) -> ExtractResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    classes, warnings = await extract_from_uploads(files)

    if not classes and warnings:
        raise HTTPException(status_code=422, detail=[w.message for w in warnings])

    return ExtractResponse(classes=classes, warnings=warnings)


@app.post("/api/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    if not request.selected_courses:
        raise HTTPException(status_code=400, detail="No courses selected.")
    return generate_timetables(request)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
