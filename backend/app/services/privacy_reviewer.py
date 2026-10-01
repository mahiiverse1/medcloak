"""Local GenAI reviewer for possible PHI missed by first-pass redaction.

The reviewer is intentionally advisory: it receives only redacted text, returns
structured flags, and never silently changes the user's note. Ollama keeps the
model local so raw clinical text is not sent to a hosted LLM provider.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from app.schemas import PrivacyReviewFinding, PrivacyReviewResponse


class ReviewerUnavailableError(RuntimeError):
    """Raised when the optional local Ollama service is not running."""


class ReviewerOutputError(RuntimeError):
    """Raised when a model response cannot be safely used as a review result."""


POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "phi_review_policy.json"
PLACEHOLDER_PATTERN = re.compile(r"^\[[A-Z_]+\]$")
QUOTED_PLACEHOLDER_PATTERN = re.compile(r"^[\s\"'`\u201c\u201d\u2018\u2019]*\[[A-Z_]+\][\s\"'`\u201c\u201d\u2018\u2019]*$")
MEANINGFUL_TEXT_PATTERN = re.compile(r"[A-Za-z0-9]")


def load_policy() -> dict[str, Any]:
    """Load the small, local policy grounding document used in every review."""

    with POLICY_PATH.open(encoding="utf-8") as policy_file:
        return json.load(policy_file)


class OllamaPrivacyReviewer:
    """Thin dependency-free client for Ollama's local chat API."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 90,
    ) -> None:
        self.model = model or os.getenv("MEDCLOAK_OLLAMA_MODEL", "qwen2.5:3b")
        self.base_url = base_url or os.getenv("MEDCLOAK_OLLAMA_URL", "http://127.0.0.1:11434")
        self.timeout_seconds = timeout_seconds
        self.policy = load_policy()

    def _system_prompt(self) -> str:
        policy_json = json.dumps(self.policy, ensure_ascii=True)
        return (
            "You are MedCloak's local privacy-review assistant. You audit a clinical note only after "
            "a deterministic redaction pass. Do not diagnose, summarize, or give medical advice. "
            "Flag only explicit text that may still identify a person. Do not flag clinical facts, "
            "medications, conditions, generic hospitals, or placeholders like [NAME]. "
            "Before returning an empty list, check specifically for unredacted staff names (including title-plus-initial "
            "forms such as Dr. A. Shah) and named residences, buildings, facilities, villages, or employers. "
            "A distinctive named residence is a review candidate; the generic word "
            "'residence' by itself is not. "
            "Quote the shortest exact entity only, never a complete sentence or surrounding clinical context. "
            "Assign categories from the text itself: a person's written name is NAME, and PHONE may be used only "
            "when the quoted text contains a telephone number. Do not infer a category from nearby wording. "
            "Every finding must quote an exact substring from the supplied redacted note. "
            "If no likely identifier remains, return an empty findings list. "
            "Your output must be valid JSON with exactly this shape: "
            '{"findings":[{"category":"NAME|DATE|PHONE|EMAIL|MRN|PATIENT_ID|ADDRESS|POSTAL_CODE|LOCATION|ORGANIZATION|OTHER",'
            '"text":"exact remaining substring","reason":"brief privacy rationale","risk_level":"low|medium|high"}]}. '
            f"Use this local review policy: {policy_json}"
        )

    def _request_payload(self, redacted_text: str) -> bytes:
        return json.dumps(
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0, "seed": 42},
                "messages": [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": f"Redacted note to audit:\n---\n{redacted_text}\n---"},
                ],
            }
        ).encode("utf-8")

    def _parse_findings(self, model_content: str, redacted_text: str) -> list[PrivacyReviewFinding]:
        """Validate model output and reject unsafe or unverifiable suggestions."""

        try:
            raw_findings = json.loads(model_content).get("findings", [])
            findings = [PrivacyReviewFinding.model_validate(finding) for finding in raw_findings]
        except (json.JSONDecodeError, ValidationError, AttributeError, TypeError) as error:
            raise ReviewerOutputError("The local model returned invalid review JSON.") from error

        verified: list[PrivacyReviewFinding] = []
        for finding in findings:
            candidate = finding.text.strip()
            if (
                PLACEHOLDER_PATTERN.fullmatch(candidate)
                or QUOTED_PLACEHOLDER_PATTERN.fullmatch(candidate)
                or not MEANINGFUL_TEXT_PATTERN.search(candidate)
            ):
                continue
            if candidate not in redacted_text:
                continue
            verified_finding = finding.model_copy(update={"text": candidate})
            if verified_finding not in verified:
                verified.append(verified_finding)
        return verified

    def review(self, redacted_text: str) -> PrivacyReviewResponse:
        """Ask Ollama for review flags; no original, unredacted note is sent."""

        request = Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=self._request_payload(redacted_text),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, OSError) as error:
            raise ReviewerUnavailableError(
                "Local GenAI review is unavailable. Start Ollama and download the configured model."
            ) from error

        try:
            model_content = raw_response["message"]["content"]
        except (KeyError, TypeError) as error:
            raise ReviewerOutputError("The local model response did not contain a chat message.") from error

        findings = self._parse_findings(model_content, redacted_text)
        return PrivacyReviewResponse(
            reviewer_model=self.model,
            findings=findings,
            safety_notice=(
                "Local GenAI review is advisory only. It can miss identifiers or raise false positives; "
                "a qualified human must review flagged and unflagged output before any real-world use."
            ),
        )
