import json
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pypdf import PdfReader

import app.main as main
from app.main import app
from app.services.document_text import DocumentExtractionError, extract_text
from app.services.privacy_reviewer import OllamaPrivacyReviewer, ReviewerOutputError
from app.services.redactor import RedactionEngine


def test_redactor_detects_common_identifiers() -> None:
    note = (
        "Patient: Riya Sharma. DOB: 14/08/1983. MRN: MH-10492. "
        "Call +91 98765 43210 or email riya@example.com."
    )
    redacted, entities = RedactionEngine().redact(note)

    assert "Riya Sharma" not in redacted
    assert "14/08/1983" not in redacted
    assert "MH-10492" not in redacted
    assert "+91 98765 43210" not in redacted
    assert "riya@example.com" not in redacted
    assert {entity.category for entity in entities} >= {"NAME", "DATE", "MRN", "PHONE", "EMAIL"}


def test_redactor_propagates_a_labelled_patient_name_to_later_mentions() -> None:
    note = "Patient name: Kavya Iyer\nDOB: 18/02/1988\n\nKavya Iyer reports improved sleep."
    redacted, entities = RedactionEngine().redact(note)

    assert "Kavya Iyer" not in redacted
    assert redacted == "Patient name: [NAME]\nDOB: [DATE]\n\n[NAME] reports improved sleep."


def test_redactor_detects_patient_name_in_follow_up_context() -> None:
    note = "Follow-up note for Kavya Iyer. She reports improved sleep."

    redacted, entities = RedactionEngine(nlp_enabled=False).redact(note)

    assert redacted == "Follow-up note for [NAME]. She reports improved sleep."
    assert any(entity.category == "NAME" and entity.text == "Kavya Iyer" for entity in entities)
    assert sum(entity.category == "NAME" for entity in entities) == 1


def test_redactor_handles_common_free_text_clinical_contexts() -> None:
    note = (
        "Aron Rodgers visited the hospital on 5th May 2026. Aron complained of sleep apnea. "
        "Contact him on +917389000543, and he lives on 24th Street, Golden City, Oklahoma."
    )

    redacted, _ = RedactionEngine(nlp_enabled=False).redact(note)

    assert redacted == (
        "[NAME] visited the hospital on [DATE]. [NAME] complained of sleep apnea. "
        "Contact him on [PHONE], and he lives on [ADDRESS]."
    )


def test_redactor_detects_demographic_name_and_street_suffix_address() -> None:
    note = "Kayla McCarthy, aged 24, lives at New Wales Street. Kayla reports nausea."

    redacted, _ = RedactionEngine(nlp_enabled=False).redact(note)

    assert redacted == "[NAME], aged 24, lives at [ADDRESS]. [NAME] reports nausea."


def test_redactor_detects_clinician_name_with_initial() -> None:
    note = "Dr. A. Shah prescribed iron supplements."

    redacted, entities = RedactionEngine(nlp_enabled=False).redact(note)

    assert redacted == "Dr. [NAME] prescribed iron supplements."
    assert any(entity.text == "A. Shah" and entity.detector == "regex.honorific_name" for entity in entities)


def test_redactor_detects_distinctive_named_residence_in_context() -> None:
    note = "The emergency contact will meet her near Willow Co-op Housing Society after the appointment."

    redacted, entities = RedactionEngine(nlp_enabled=False).redact(note)

    assert redacted == "The emergency contact will meet her near [LOCATION] after the appointment."
    assert any(entity.text == "Willow Co-op Housing Society" and entity.detector == "regex.named_residence_context" for entity in entities)


def test_core_profile_leaves_contextual_locations_visible() -> None:
    note = "Meet her near Willow Co-op Housing Society."

    redacted, entities = RedactionEngine(nlp_enabled=False).redact(note, privacy_profile="core")

    assert redacted == note
    assert entities == []


def test_local_nlp_detects_healthcare_organization_and_location() -> None:
    note = 'Aron Rodgers works at "Evermore Healthcare Hospital" in Golden City, Oklahoma.'

    redacted, entities = RedactionEngine().redact(note)

    assert "Evermore Healthcare Hospital" not in redacted
    assert any(entity.category == "ORGANIZATION" for entity in entities)
    assert any(entity.category == "LOCATION" for entity in entities)


def test_medication_brand_in_administration_list_is_not_redacted_as_a_name() -> None:
    note = "Dr. Martinez administered Rabonia-120D, Palmishine and Nurokind tablets."

    redacted, entities = RedactionEngine().redact(note)

    assert "Palmishine" in redacted
    assert not any(entity.text == "Palmishine" and entity.category == "NAME" for entity in entities)


def test_redactor_propagates_a_labelled_patient_given_name_to_later_mentions() -> None:
    note = "Patient: Riya Sharma\n\nRiya reports improved sleep."
    redacted, entities = RedactionEngine().redact(note)

    assert "Riya" not in redacted
    assert redacted == "Patient: [NAME]\n\n[NAME] reports improved sleep."
    assert any(entity.detector == "rule.patient_given_name_propagation" for entity in entities)


def test_api_returns_audit_report() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/deidentify", json={"text": "Patient: Riya Sharma. MRN: 123456."})

    assert response.status_code == 200
    body = response.json()
    assert body["redacted_text"] == "Patient: [NAME]. [MRN]."
    assert body["category_counts"] == {"NAME": 1, "MRN": 1}
    assert body["review_required"] is True


def test_api_core_profile_excludes_contextual_location() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/deidentify",
        json={
            "text": "Meet her near Willow Co-op Housing Society.",
            "privacy_profile": "core",
        },
    )

    assert response.status_code == 200
    assert response.json()["redacted_text"] == "Meet her near Willow Co-op Housing Society."
    assert response.json()["entities"] == []


def test_demo_notes_are_synthetic_and_available() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/demo-notes")

    assert response.status_code == 200
    assert len(response.json()) >= 2


def test_web_app_is_served_from_the_root_route() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Protect the patient" in response.text


def test_health_check_reports_local_genai_mode() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["deployment_mode"] == "local"
    assert response.json()["genai_review_available"] is True


def test_hosted_demo_mode_does_not_attempt_local_ollama(monkeypatch) -> None:
    monkeypatch.setattr(main, "deployment_mode", "hosted_demo")
    client = TestClient(app)
    response = client.post("/api/v1/privacy-review", json={"redacted_text": "[NAME] attended follow-up."})

    assert response.status_code == 503
    assert "local MedCloak build" in response.json()["detail"]


def test_genai_reviewer_discards_hallucinated_or_placeholder_spans() -> None:
    reviewer = OllamaPrivacyReviewer()
    redacted_note = "[NAME] attended City Hospital. Follow-up is in two weeks."
    model_output = '''{
      "findings": [
        {"category": "NAME", "text": "[NAME]", "reason": "placeholder", "risk_level": "high"},
        {"category": "LOCATION", "text": "City Hospital", "reason": "specific facility", "risk_level": "medium"},
        {"category": "NAME", "text": "Riya Sharma", "reason": "not in note", "risk_level": "high"}
      ]
    }'''

    findings = reviewer._parse_findings(model_output, redacted_note)

    assert len(findings) == 1
    assert findings[0].text == "City Hospital"


def test_genai_reviewer_discards_quotes_and_quoted_placeholders() -> None:
    reviewer = OllamaPrivacyReviewer()
    redacted_note = "[NAME] attended City Hospital."
    model_output = json.dumps(
        {
            "findings": [
                {"category": "OTHER", "text": "\"", "reason": "Punctuation", "risk_level": "low"},
                {"category": "NAME", "text": "\"[NAME]\"", "reason": "Placeholder", "risk_level": "low"},
                {"category": "ORGANIZATION", "text": "City Hospital", "reason": "Verify", "risk_level": "medium"},
            ]
        }
    )

    findings = reviewer._parse_findings(model_output, redacted_note)

    assert len(findings) == 1
    assert findings[0].text == "City Hospital"


def test_genai_reviewer_rejects_invalid_json() -> None:
    reviewer = OllamaPrivacyReviewer()

    try:
        reviewer._parse_findings("not json", "Safe text")
    except ReviewerOutputError:
        pass
    else:
        raise AssertionError("Invalid GenAI output must not reach the API response.")


def test_document_endpoint_processes_synthetic_text_file() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/deidentify-document",
        files={"file": ("synthetic-note.txt", b"Patient: Riya Sharma. Call +91 98765 43210.", "text/plain")},
    )

    assert response.status_code == 200
    assert "Riya Sharma" not in response.json()["redacted_text"]


def test_document_endpoint_applies_the_selected_privacy_profile() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/deidentify-document",
        data={"privacy_profile": "core"},
        files={
            "file": (
                "synthetic-note.txt",
                b"Meet her near Willow Co-op Housing Society.",
                "text/plain",
            )
        },
    )

    assert response.status_code == 200
    assert "Willow Co-op Housing Society" in response.json()["redacted_text"]


def test_document_endpoint_rejects_unsupported_files() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/deidentify-document",
        files={"file": ("synthetic-note.csv", b"name,value", "text/csv")},
    )

    assert response.status_code == 400
    assert "txt, .docx, or .pdf" in response.json()["detail"]


def test_document_text_rejects_extracted_text_above_the_note_limit() -> None:
    try:
        extract_text("synthetic-note.txt", b"a" * 20_001)
    except DocumentExtractionError as error:
        assert "20,000 characters" in str(error)
    else:
        raise AssertionError("Extracted text above the note limit must be rejected.")


def test_protected_download_endpoints_return_expected_file_types() -> None:
    client = TestClient(app)
    for output_format, media_type, signature in (
        ("txt", "text/plain", b"[NAME]"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK"),
        ("pdf", "application/pdf", b"%PDF"),
    ):
        response = client.post(f"/api/v1/download-protected/{output_format}", json={"redacted_text": "[NAME] follow-up note."})
        assert response.status_code == 200
        assert media_type in response.headers["content-type"]
        assert response.content.startswith(signature)


def test_protected_documents_include_clear_review_context() -> None:
    client = TestClient(app)
    docx_response = client.post("/api/v1/download-protected/docx", json={"redacted_text": "[NAME] follow-up note."})
    pdf_response = client.post("/api/v1/download-protected/pdf", json={"redacted_text": "[NAME] follow-up note."})

    with ZipFile(BytesIO(docx_response.content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    pdf_text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_response.content)).pages)

    assert "MedCloak Protected Clinical Note" in document_xml
    assert "Human review is required" in document_xml
    assert "MedCloak Protected Clinical Note" in pdf_text
    assert "Human review is required" in pdf_text


def test_protected_download_requires_explicitly_redacted_text_field() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/download-protected/txt", json={"text": "Raw source text"})

    assert response.status_code == 422
