# MedCloak

MedCloak is a local-first clinical text de-identification research prototype. It detects and replaces potential identifiers in synthetic clinical notes, explains each detection through an audit trail, and uses a local GenAI reviewer to flag possible misses.

> **Research prototype only.** MedCloak is developed and evaluated using synthetic data. It is not a HIPAA or DPDP compliance determination and must not be used with real patient data without appropriate institutional, legal, security, and human-review controls.

## What it does

- Redacts names, dates, phone numbers, email addresses, patient identifiers, MRNs, addresses, postal codes, locations, and conservative organization references.
- Combines transparent clinical-context rules with local spaCy named-entity recognition.
- Runs an optional local Ollama GenAI reviewer only after first-pass redaction; reviewer findings are advisory and never alter a note automatically.
- Accepts synthetic TXT, DOCX, and selectable-text PDF uploads in memory, with no persistence.
- Generates downloadable protected TXT, DOCX, and PDF copies from the redacted text.
- Shows a reproducible, controlled synthetic-template benchmark that compares rules-only performance with hybrid local-NLP name recall.

## Architecture

```text
Synthetic text or document upload
            |
            v
In-memory text extraction (TXT / DOCX / PDF)
            |
            v
Hybrid detector: clinical rules + local spaCy NLP
            |
            +--> transparent audit trail and protected text
            |
            +--> optional local Ollama reviewer (advisory only)
            |
            +--> protected TXT / DOCX / PDF download
```

No submitted note or upload is written to a database or log file by the application.

## Deterministic redaction API

This first phase exposes a FastAPI endpoint that detects common identifiers using transparent rules and replaces them with category labels such as `[NAME]` and `[MRN]`.

### Run locally

1. Open a terminal in `medcloak/backend`.
2. Create a virtual environment: `python -m venv .venv`
3. Activate it in PowerShell: `.\.venv\Scripts\Activate.ps1`
4. Install dependencies: `python -m pip install -r requirements.txt`
5. Start the API: `uvicorn app.main:app --reload`
6. Open `http://127.0.0.1:8000/docs` to use the interactive API.

### Try it

Send a `POST` request to `/api/v1/deidentify`:

```json
{
  "text": "Patient: Riya Sharma. DOB: 14/08/1983. MRN: MH-10492. Call +91 98765 43210."
}
```

The API never writes submitted text to a database or log file. Do not use real patient data in this prototype.

### Run tests

From `medcloak/backend` run: `pytest`

## Local application

From `medcloak/backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Open `http://127.0.0.1:8001` in your browser.

## Implemented workflow

1. Deterministic redaction with transparent rules and local spaCy NLP
2. Advisory local GenAI privacy review through Ollama
3. Browser interface, audit evidence, human-review controls, and protected exports
4. Reproducible synthetic evaluation and a deployment-safe hosted-demo configuration

## Local GenAI review

Phase 2 uses [Ollama](https://ollama.com/) to run the optional privacy-review model on your own machine. After installing Ollama, run:

```powershell
ollama pull qwen2.5:3b
```

Then call `POST /api/v1/privacy-review` with the **already redacted** text from the de-identification endpoint. The model returns only advisory findings; it never changes a note automatically.

## Hosted demo mode

`render.yaml` prepares a free hosted demo using the rule-based and local-NLP layers. In this mode, the app deliberately disables the Ollama GenAI reviewer instead of sending clinical text to a cloud model or presenting a misleading error. The full GenAI review remains available when MedCloak is run locally with Ollama.

Use only synthetic or properly authorized data in the hosted demo.

## Synthetic evaluation

MedCloak includes a reproducible, labelled corpus of entirely synthetic notes.
It measures the transparent rules-only baseline with exact-span precision,
recall, and F1 before future NLP improvements are added.

The current hybrid detector also uses spaCy's local `en_core_web_sm` model to
propose person entities that the labelled regex rules do not recognise. It is
an additional signal, not a compliance guarantee, and its performance will be
reported separately from the rules-only baseline.

After installing Python requirements for the first time, download the free
local spaCy model once:

```powershell
python -m spacy download en_core_web_sm
```

From `medcloak/backend`, run:

```powershell
.\.venv\Scripts\python.exe scripts\run_baseline_evaluation.py
```

The JSON report is saved to `backend/data/evaluation/baseline_report.json`.
The deliberately mixed-difficulty data includes unlabelled patient-name cases
so the baseline's limitations are visible in the results.

Run `scripts/run_hybrid_evaluation.py` in the same way to save the local NLP
comparison as `backend/data/evaluation/hybrid_report.json`.

## Scope and limitations

- The reported exact-span scores measure controlled synthetic templates, not clinical generalization or deployment readiness.
- General-purpose NLP can produce false positives or miss identifiers. MedCloak therefore exposes detector evidence and requires human review.
- Detector scores are heuristic priorities, not calibrated probabilities of correctness.
- Medication-administration contexts are protected from automatic person-name redaction to reduce false positives such as brand names.
- Phone-number and postal-code rules are primarily India-oriented; they are not a country-independent PHI detector.
- Password-protected and image-only PDFs are intentionally not processed.
