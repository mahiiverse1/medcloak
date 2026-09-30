"""In-memory text extraction for MedCloak's synthetic document demo."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".txt", ".docx", ".pdf"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class DocumentExtractionError(ValueError):
    pass


def extract_text(filename: str, contents: bytes) -> str:
    """Extract selectable text without writing the upload to disk."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentExtractionError("Use a .txt, .docx, or .pdf file.")
    if not contents:
        raise DocumentExtractionError("The uploaded file is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise DocumentExtractionError("Files must be 5 MB or smaller.")
    try:
        if suffix == ".txt":
            text = contents.decode("utf-8")
        elif suffix == ".docx":
            text = "\n".join(paragraph.text for paragraph in Document(BytesIO(contents)).paragraphs)
        else:
            reader = PdfReader(BytesIO(contents))
            if reader.is_encrypted:
                raise DocumentExtractionError("Password-protected PDFs are not supported.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except DocumentExtractionError:
        raise
    except Exception as error:
        raise DocumentExtractionError("This document could not be read as text.") from error
    if not text.strip():
        raise DocumentExtractionError("No selectable text was found in this document.")
    return text.strip()
