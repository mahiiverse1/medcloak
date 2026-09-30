"""FastAPI entry point for the MedCloak Phase 1 API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.schemas import (
    DeidentifyRequest,
    DeidentifyResponse,
    DemoNote,
    HealthResponse,
    PrivacyReviewRequest,
    PrivacyReviewResponse,
    PrivacyProfile,
    category_counts,
)
from app.services.privacy_reviewer import (
    OllamaPrivacyReviewer,
    ReviewerOutputError,
    ReviewerUnavailableError,
)
from app.services.redactor import RedactionEngine
from app.services.document_text import DocumentExtractionError, extract_text
from app.services.protected_document import build_protected_document
from app.evaluation.report import build_evaluation_report


app = FastAPI(
    title="MedCloak API",
    version="0.1.0",
    description="Synthetic-data-only clinical text de-identification prototype.",
)
engine = RedactionEngine()
reviewer = OllamaPrivacyReviewer()
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_notes.json"
WEB_PATH = Path(__file__).resolve().parent / "web"

app.mount("/assets", StaticFiles(directory=WEB_PATH), name="assets")


def load_demo_notes() -> list[DemoNote]:
    with DATA_PATH.open(encoding="utf-8") as file:
        return [DemoNote.model_validate(note) for note in json.load(file)]


@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    """Serve the local MedCloak demonstration interface."""

    return FileResponse(WEB_PATH / "index.html")


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    return HealthResponse(status="ok", service="medcloak-api", version=app.version)


@app.get("/api/v1/demo-notes", response_model=list[DemoNote], tags=["demo"])
def demo_notes() -> list[DemoNote]:
    """Return synthetic notes only; no patient information is included."""

    return load_demo_notes()


@app.get("/api/v1/evaluation", tags=["evaluation"])
def evaluation_report() -> dict[str, object]:
    """Return a reproducible benchmark based solely on MedCloak synthetic notes."""
    return build_evaluation_report()


@app.post("/api/v1/deidentify", response_model=DeidentifyResponse, tags=["de-identification"])
def deidentify(payload: DeidentifyRequest) -> DeidentifyResponse:
    """Redact common PHI patterns in memory and return an audit trail."""

    try:
        redacted_text, entities = engine.redact(payload.text, privacy_profile=payload.privacy_profile)
    except Exception as error:  # defensive API boundary; submitted text is never logged
        raise HTTPException(status_code=500, detail="Unable to process the submitted note.") from error

    return DeidentifyResponse(
        redacted_text=redacted_text,
        entities=entities,
        category_counts=category_counts(entities),
        review_required=True,
        privacy_notice=(
            "Prototype only. Results require human review and are not a HIPAA or DPDP compliance determination. "
            "Submitted text is processed in memory and is not persisted by this API."
        ),
    )


@app.post("/api/v1/deidentify-document", response_model=DeidentifyResponse, tags=["de-identification"])
async def deidentify_document(
    file: UploadFile = File(...),
    privacy_profile: PrivacyProfile = Form("strict"),
) -> DeidentifyResponse:
    """Extract and redact a synthetic TXT, DOCX, or PDF upload in memory."""
    try:
        text = extract_text(file.filename or "", await file.read())
        redacted_text, entities = engine.redact(text, privacy_profile=privacy_profile)
    except DocumentExtractionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to process the uploaded document.") from error
    finally:
        await file.close()
    return DeidentifyResponse(
        redacted_text=redacted_text,
        entities=entities,
        category_counts=category_counts(entities),
        review_required=True,
        privacy_notice="Prototype only. Uploaded files are read in memory and are not persisted by this API. Use synthetic documents only.",
    )


@app.post("/api/v1/download-protected/{output_format}", tags=["de-identification"])
def download_protected_document(output_format: str, payload: DeidentifyRequest) -> Response:
    """Return an in-memory TXT, DOCX, or PDF built from protected text only."""
    try:
        contents, media_type, filename = build_protected_document(payload.text, output_format)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return Response(
        content=contents,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/v1/privacy-review", response_model=PrivacyReviewResponse, tags=["genai review"])
def privacy_review(payload: PrivacyReviewRequest) -> PrivacyReviewResponse:
    """Use a local LLM to flag possible PHI left after deterministic redaction."""

    try:
        return reviewer.review(payload.redacted_text)
    except ReviewerUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ReviewerOutputError as error:
        raise HTTPException(status_code=502, detail="Local GenAI review returned unusable output.") from error
