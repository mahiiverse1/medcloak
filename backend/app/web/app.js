const noteInput = document.querySelector("#clinical-note");
const deploymentBadge = document.querySelector("#deployment-badge");
const runtimeDescription = document.querySelector("#runtime-description");
const syntheticNotice = document.querySelector("#synthetic-notice");
const characterCount = document.querySelector("#character-count");
const demoSelect = document.querySelector("#demo-select");
const runButton = document.querySelector("#run-button");
const documentUpload = document.querySelector("#document-upload");
const privacyProfile = document.querySelector("#privacy-profile");
const redactedNote = document.querySelector("#redacted-note");
const resultStatus = document.querySelector("#result-status");
const resultSummary = document.querySelector("#result-summary");
const downloadActions = document.querySelector("#download-actions");
const manualRedactionActions = document.querySelector("#manual-redaction-actions");
const manualCategorySelect = document.querySelector("#manual-category-select");
const manualProtectButton = document.querySelector("#manual-protect-button");
const undoManualProtectButton = document.querySelector("#undo-manual-protect-button");
const entityList = document.querySelector("#entity-list");
const entityTotal = document.querySelector("#entity-total");
const auditExportButton = document.querySelector("#audit-export-button");
const reviewList = document.querySelector("#review-list");
const reviewState = document.querySelector("#review-state");
const reviewSignoff = document.querySelector("#review-signoff");
const signoffState = document.querySelector("#signoff-state");
const reviewChecks = [...document.querySelectorAll("input[data-review-check]")];
const evaluationButton = document.querySelector("#evaluation-button");
const evaluationResults = document.querySelector("#evaluation-results");

let demoNotes = [];
let activeRedaction = null;
let restoredEntityIndexes = new Set();
let activeAudit = null;
let activeReview = null;
let manualProtections = [];
let deploymentMode = "local";
const REDACTION_CATEGORIES = ["NAME", "DATE", "PHONE", "EMAIL", "MRN", "PATIENT_ID", "ADDRESS", "POSTAL_CODE", "LOCATION", "ORGANIZATION", "OTHER"];

function updateCharacterCount() {
  characterCount.textContent = `${noteInput.value.length.toLocaleString()} / 20,000 characters`;
}

function setStatus(text, state = "") {
  resultStatus.textContent = text;
  resultStatus.className = `status-pill ${state}`.trim();
}

function syncManualProtectionControls() {
  undoManualProtectButton.disabled = manualProtections.length === 0;
}

function startReviewSignoff() {
  reviewSignoff.hidden = false;
  for (const checkbox of reviewChecks) checkbox.checked = false;
  signoffState.textContent = "Review pending";
  signoffState.className = "status-pill";
}

function updateReviewSignoff() {
  const complete = reviewChecks.every((checkbox) => checkbox.checked);
  signoffState.textContent = complete ? "Review documented" : "Review pending";
  signoffState.className = `status-pill ${complete ? "" : "processing"}`.trim();
}

function clearResults() {
  redactedNote.textContent = "Your protected clinical note will appear here.";
  redactedNote.classList.add("empty-state");
  resultSummary.hidden = true;
  downloadActions.hidden = true;
  manualRedactionActions.hidden = true;
  entityList.innerHTML = '<p class="muted-copy">Run a privacy check to view category counts and detector evidence.</p>';
  entityTotal.textContent = "0";
  auditExportButton.hidden = true;
  reviewList.innerHTML = '<p class="muted-copy">The local reviewer runs after first-pass redaction.</p>';
  reviewState.textContent = "—";
  reviewState.className = "metric subdued";
  activeRedaction = null;
  restoredEntityIndexes = new Set();
  activeAudit = null;
  activeReview = null;
  manualProtections = [];
  syncManualProtectionControls();
  reviewSignoff.hidden = true;
}

function renderEntities(entities, allowRestore = false) {
  entityTotal.textContent = entities.length;
  if (!entities.length) {
    entityList.innerHTML = '<p class="muted-copy">No configured identifiers were detected in this note.</p>';
    return;
  }
  entityList.innerHTML = entities.map((entity, index) => `
    <div class="entity-row">
      <div>
        <p class="entity-name">${escapeHtml(entity.replacement)}</p>
        <p class="entity-meta">${escapeHtml(entity.detector)} · ${(entity.heuristic_score * 100).toFixed(0)} heuristic score</p>
      </div>
      <div class="entity-actions">
        <span class="category">${escapeHtml(entity.category)}</span>
        ${allowRestore ? `<label class="restore-control"><input type="checkbox" data-entity-index="${index}" ${restoredEntityIndexes.has(index) ? "checked" : ""} /> Restore</label>` : ""}
      </div>
    </div>`).join("");
}

function renderReviewedText() {
  if (!activeRedaction) return;
  let reviewedText = activeRedaction.sourceText;
  for (let index = activeRedaction.entities.length - 1; index >= 0; index -= 1) {
    const entity = activeRedaction.entities[index];
    const replacement = restoredEntityIndexes.has(index) ? entity.text : entity.replacement;
    reviewedText = `${reviewedText.slice(0, entity.start)}${replacement}${reviewedText.slice(entity.end)}`;
  }
  for (const protection of manualProtections) {
    reviewedText = replaceOccurrence(reviewedText, protection.text, protection.occurrence, protection.replacement);
  }
  redactedNote.textContent = reviewedText;
  const protectedCount = activeRedaction.entities.length - restoredEntityIndexes.size;
  const manualNote = manualProtections.length
    ? ` ${manualProtections.length} human-confirmed item${manualProtections.length === 1 ? "" : "s"} protected.`
    : "";
  resultSummary.textContent = activeRedaction.priorProtectedCount !== undefined
    ? `${activeRedaction.priorProtectedCount} identifiers protected from the uploaded document.${manualNote || " Human review remains required."}`
    : restoredEntityIndexes.size
    ? `${protectedCount} identifiers remain protected. ${restoredEntityIndexes.size} item${restoredEntityIndexes.size === 1 ? "" : "s"} restored after human review.${manualNote}`
    : `${protectedCount} identifier${protectedCount === 1 ? "" : "s"} replaced. Human review remains required.${manualNote}`;
  renderEntities(activeRedaction.entities, true);
  if (activeReview) renderReview(activeReview);
  syncManualProtectionControls();
  startReviewSignoff();
  setStatus(restoredEntityIndexes.size ? "Human review edits" : "Review complete");
}

function replaceOccurrence(text, target, occurrence, replacement) {
  let start = -1;
  let searchFrom = 0;
  for (let index = 0; index <= occurrence; index += 1) {
    start = text.indexOf(target, searchFrom);
    if (start === -1) return text;
    searchFrom = start + target.length;
  }
  return `${text.slice(0, start)}${replacement}${text.slice(start + target.length)}`;
}

function occurrenceAtOffset(text, target, offset) {
  let occurrence = 0;
  let start = text.indexOf(target);
  while (start !== -1) {
    if (start >= offset) return occurrence;
    occurrence += 1;
    start = text.indexOf(target, start + target.length);
  }
  return 0;
}

function addManualProtection(text, category, occurrence = 0) {
  const candidate = text.trim();
  if (!candidate || !REDACTION_CATEGORIES.includes(category)) return false;
  if (!/[A-Za-z0-9]/.test(candidate) || /^\[[A-Z_]+\]$/.test(candidate)) return false;
  if (!redactedNote.textContent.includes(candidate)) return false;
  manualProtections.push({ text: candidate, category, occurrence, replacement: `[${category}]` });
  renderReviewedText();
  return true;
}

function renderReview(review) {
  activeReview = review;
  reviewState.textContent = review.findings.length;
  reviewState.className = "metric";
  if (!review.findings.length) {
    reviewList.innerHTML = '<p class="muted-copy">No additional explicit identifiers were flagged by the local GenAI reviewer.</p>';
    return;
  }
  reviewList.innerHTML = review.findings.map((finding, index) => {
    const protection = manualProtections.find((item) => item.text === finding.text);
    const isProtected = Boolean(protection);
    const selectedCategory = protection?.category || finding.category;
    const categoryOptions = REDACTION_CATEGORIES.map((category) => (
      `<option value="${category}" ${category === selectedCategory ? "selected" : ""}>${category}</option>`
    )).join("");
    return `
    <div class="finding">
      <div>
        <p class="entity-name">“${escapeHtml(finding.text)}”</p>
        <p class="finding-reason">${escapeHtml(finding.reason)}</p>
      </div>
      <div>
        <span class="risk">${escapeHtml(finding.risk_level)}</span>
        <label class="finding-category-label">Protect as
          <select class="finding-category-select" data-finding-category="${index}" ${isProtected ? "disabled" : ""}>${categoryOptions}</select>
        </label>
        <button class="finding-action" type="button" data-finding-index="${index}" ${isProtected ? "disabled" : ""}>${isProtected ? "Protected" : "Protect"}</button>
      </div>
    </div>`;
  }).join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

async function loadDemoNotes() {
  try {
    const response = await fetch("/api/v1/demo-notes");
    demoNotes = await response.json();
    for (const note of demoNotes) {
      const option = document.createElement("option");
      option.value = note.id;
      option.textContent = note.title;
      demoSelect.append(option);
    }
  } catch {
    demoSelect.disabled = true;
  }
}

async function loadDeploymentStatus() {
  try {
    const response = await fetch("/health");
    if (!response.ok) return;
    const health = await response.json();
    deploymentMode = health.deployment_mode || "local";
    if (deploymentMode === "hosted_demo") {
      deploymentBadge.textContent = "Hosted synthetic demo";
      runtimeDescription.textContent = "A hosted synthetic-data demonstration of transparent redaction, local NLP, and human-review controls.";
      syntheticNotice.innerHTML = "<strong>Hosted synthetic-demo environment.</strong> Do not enter real patient data. Text is processed in memory by this demo server and is not persisted by the application.";
      reviewList.innerHTML = '<p class="muted-copy">Local Ollama GenAI review is available in the local MedCloak build. This hosted demo keeps rule-based, local NLP, and human review enabled.</p>';
    } else {
      deploymentBadge.textContent = "Local privacy mode";
      runtimeDescription.textContent = "A hybrid privacy pipeline that redacts direct identifiers, then asks a local GenAI reviewer to flag possible misses.";
      syntheticNotice.innerHTML = "<strong>Local synthetic-demo environment.</strong> Do not enter real patient data. Text is processed in memory on this device and requires human review.";
    }
  } catch {
    // Keep the local-mode default when the optional health check is unavailable.
  }
}

async function runPrivacyCheck() {
  const text = noteInput.value.trim();
  if (!text) {
    setStatus("Add a note first", "error");
    noteInput.focus();
    return;
  }

  runButton.disabled = true;
  runButton.textContent = "Protecting note…";
  setStatus("First-pass redaction", "processing");
  reviewList.innerHTML = deploymentMode === "hosted_demo"
    ? '<p class="muted-copy">Hosted demo mode keeps local Ollama GenAI review disabled.</p>'
    : '<p class="muted-copy">Waiting for local GenAI review…</p>';

  try {
    const redactionResponse = await fetch("/api/v1/deidentify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, privacy_profile: privacyProfile.value })
    });
    if (!redactionResponse.ok) throw new Error("The redaction service could not process this note.");
    const redaction = await redactionResponse.json();

    activeRedaction = { sourceText: text, entities: redaction.entities };
    restoredEntityIndexes = new Set();
    manualProtections = [];
    syncManualProtectionControls();
    activeAudit = { entities: redaction.entities, source: "pasted synthetic note" };
    activeReview = null;
    auditExportButton.hidden = false;
    redactedNote.textContent = redaction.redacted_text;
    redactedNote.classList.remove("empty-state");
    resultSummary.textContent = `${redaction.entities.length} identifier${redaction.entities.length === 1 ? "" : "s"} replaced. Use Restore only for confirmed false positives.`;
    resultSummary.hidden = false;
    downloadActions.hidden = false;
    manualRedactionActions.hidden = false;
    startReviewSignoff();
    renderEntities(redaction.entities, true);

    if (deploymentMode === "hosted_demo") {
      reviewState.textContent = "local";
      reviewState.className = "metric subdued";
      reviewList.innerHTML = '<p class="muted-copy">Local Ollama GenAI review is available only in the local MedCloak build. Continue with the detected identifiers and human-review controls in this hosted synthetic demo.</p>';
      setStatus("Redaction complete");
      return;
    }

    setStatus("Local GenAI review", "processing");
    const reviewResponse = await fetch("/api/v1/privacy-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ redacted_text: redaction.redacted_text })
    });

    if (reviewResponse.ok) {
      renderReview(await reviewResponse.json());
      setStatus("Review complete");
    } else {
      const error = await reviewResponse.json();
      reviewState.textContent = "!";
      reviewState.className = "metric subdued";
      reviewList.innerHTML = `<p class="muted-copy">Local GenAI review was unavailable: ${escapeHtml(error.detail || "unknown error")}</p>`;
      setStatus("Redaction complete");
    }
  } catch (error) {
    setStatus("Processing failed", "error");
    reviewList.innerHTML = `<p class="muted-copy">${escapeHtml(error.message)}</p>`;
  } finally {
    runButton.disabled = false;
    runButton.innerHTML = 'Run privacy check <span aria-hidden="true">→</span>';
  }
}

async function processUploadedDocument() {
  const [file] = documentUpload.files;
  if (!file) return;
  runButton.disabled = true;
  setStatus("Extracting document", "processing");
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("privacy_profile", privacyProfile.value);
    const response = await fetch("/api/v1/deidentify-document", { method: "POST", body: formData });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "The document could not be processed.");
    noteInput.value = result.redacted_text;
    activeRedaction = { sourceText: result.redacted_text, entities: [], priorProtectedCount: result.entities.length };
    restoredEntityIndexes = new Set();
    manualProtections = [];
    syncManualProtectionControls();
    activeAudit = { entities: result.entities, source: "uploaded synthetic document" };
    activeReview = null;
    auditExportButton.hidden = false;
    updateCharacterCount();
    redactedNote.textContent = result.redacted_text;
    redactedNote.classList.remove("empty-state");
    resultSummary.textContent = `${result.entities.length} identifier${result.entities.length === 1 ? "" : "s"} replaced from ${file.name}.`;
    resultSummary.hidden = false;
    downloadActions.hidden = false;
    manualRedactionActions.hidden = false;
    startReviewSignoff();
    renderEntities(result.entities);
    reviewList.innerHTML = '<p class="muted-copy">Run the privacy check again to request the optional local GenAI review.</p>';
    setStatus("Document protected");
  } catch (error) {
    setStatus("Upload failed", "error");
    reviewList.innerHTML = `<p class="muted-copy">${escapeHtml(error.message)}</p>`;
  } finally {
    runButton.disabled = false;
    documentUpload.value = "";
  }
}

noteInput.addEventListener("input", updateCharacterCount);
demoSelect.addEventListener("change", () => {
  const note = demoNotes.find((item) => item.id === demoSelect.value);
  if (!note) return;
  noteInput.value = note.text;
  updateCharacterCount();
  clearResults();
  setStatus("Demo loaded");
});
runButton.addEventListener("click", runPrivacyCheck);
documentUpload.addEventListener("change", processUploadedDocument);
reviewChecks.forEach((checkbox) => checkbox.addEventListener("change", updateReviewSignoff));
entityList.addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-entity-index]");
  if (!checkbox || !activeRedaction) return;
  const index = Number(checkbox.dataset.entityIndex);
  if (checkbox.checked) restoredEntityIndexes.add(index);
  else restoredEntityIndexes.delete(index);
  renderReviewedText();
});
reviewList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-finding-index]");
  if (!button || !activeRedaction || !activeReview) return;
  const finding = activeReview.findings[Number(button.dataset.findingIndex)];
  if (!finding || !finding.text.trim()) return;
  const categorySelect = reviewList.querySelector(`select[data-finding-category="${button.dataset.findingIndex}"]`);
  const category = categorySelect?.value;
  if (!REDACTION_CATEGORIES.includes(category)) return;
  if (!redactedNote.textContent.includes(finding.text)) {
    setStatus("Suggestion not in note", "error");
    return;
  }
  addManualProtection(finding.text, category);
});
manualProtectButton.addEventListener("click", () => {
  const selection = window.getSelection();
  const selectedText = selection?.toString() || "";
  const selectionIsInOutput = selection
    && redactedNote.contains(selection.anchorNode)
    && redactedNote.contains(selection.focusNode);
  if (!activeRedaction || !selectionIsInOutput || !selectedText.trim()) {
    setStatus("Select text in output", "error");
    return;
  }
  const range = selection.getRangeAt(0);
  const prefix = range.cloneRange();
  prefix.selectNodeContents(redactedNote);
  prefix.setEnd(range.startContainer, range.startOffset);
  const occurrence = occurrenceAtOffset(redactedNote.textContent, selectedText.trim(), prefix.toString().length);
  if (!addManualProtection(selectedText, manualCategorySelect.value, occurrence)) {
    setStatus("Selection not protected", "error");
    return;
  }
  selection.removeAllRanges();
});
undoManualProtectButton.addEventListener("click", () => {
  if (!manualProtections.length || !activeRedaction) return;
  manualProtections.pop();
  renderReviewedText();
});
downloadActions.addEventListener("click", async (event) => {
  const outputFormat = event.target.dataset.format;
  if (!outputFormat || !redactedNote.textContent) return;
  try {
    const response = await fetch(`/api/v1/download-protected/${outputFormat}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ redacted_text: redactedNote.textContent })
    });
    if (!response.ok) throw new Error("Download could not be created.");
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `medcloak-protected-note.${outputFormat}`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    setStatus("Download failed", "error");
  }
});
auditExportButton.addEventListener("click", () => {
  if (!activeAudit) return;
  const entities = activeAudit.entities;
  const categoryCounts = entities.reduce((counts, entity) => {
    counts[entity.category] = (counts[entity.category] || 0) + 1;
    return counts;
  }, {});
  const reviewFindings = (activeReview?.findings || []).map((finding) => ({
    category: finding.category,
    risk_level: finding.risk_level
  }));
  const auditReport = {
    report_type: "MedCloak de-identification audit",
    generated_at: new Date().toISOString(),
    source: activeAudit.source,
    redaction_summary: {
      detected_identifiers: entities.length,
      protected_identifiers: entities.length - restoredEntityIndexes.size,
      restored_after_human_review: restoredEntityIndexes.size,
      genai_suggestions_confirmed_and_protected: manualProtections.length,
      category_counts: categoryCounts
    },
    detector_evidence: entities.map((entity, index) => ({
      category: entity.category,
      replacement: entity.replacement,
      detector: entity.detector,
      heuristic_score: entity.heuristic_score,
      action: restoredEntityIndexes.has(index) ? "restored_after_human_review" : "protected"
    })),
    local_genai_review: {
      status: activeReview ? "completed" : "not_available_or_not_run",
      finding_count: reviewFindings.length,
      findings: reviewFindings,
      confirmed_protection_categories: manualProtections.map((protection) => protection.category)
    },
    human_review_record: {
      status: reviewChecks.every((checkbox) => checkbox.checked) ? "documented" : "pending",
      checks: Object.fromEntries(reviewChecks.map((checkbox) => [checkbox.dataset.reviewCheck, checkbox.checked]))
    },
    privacy_note: "This export intentionally excludes the original note, original identifier values, and GenAI finding text. It is a synthetic-demo audit record, not a compliance determination."
  };
  const blob = new Blob([JSON.stringify(auditReport, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "medcloak-deidentification-audit.json";
  link.click();
  URL.revokeObjectURL(link.href);
});
evaluationButton.addEventListener("click", async () => {
  evaluationButton.disabled = true;
  evaluationButton.textContent = "Running benchmark…";
  evaluationResults.innerHTML = '<p class="muted-copy">Evaluating 120 synthetic notes locally…</p>';
  try {
    const response = await fetch("/api/v1/evaluation");
    if (!response.ok) throw new Error("Benchmark unavailable");
    const report = await response.json();
    const overall = report.rules_only_overall;
    const names = report.name_recall;
    evaluationResults.innerHTML = `
      <div class="benchmark-grid">
        <div class="benchmark-card"><p class="benchmark-label">Rules-only overall F1</p><p class="benchmark-value">${(overall.f1 * 100).toFixed(1)}%</p></div>
        <div class="benchmark-card"><p class="benchmark-label">Rules-only name recall</p><p class="benchmark-value">${(names.rules_only * 100).toFixed(1)}%</p></div>
        <div class="benchmark-card"><p class="benchmark-label">Hybrid local NLP name recall</p><p class="benchmark-value">${(names.hybrid_local_nlp * 100).toFixed(1)}%</p></div>
      </div>
      <p class="benchmark-note">${escapeHtml(report.dataset)} · ${escapeHtml(report.method_note)}</p>`;
  } catch {
    evaluationResults.innerHTML = '<p class="muted-copy">The benchmark could not be run. Try again after restarting the local server.</p>';
  } finally {
    evaluationButton.disabled = false;
    evaluationButton.textContent = "View benchmark";
  }
});

clearResults();
updateCharacterCount();
loadDemoNotes();
loadDeploymentStatus();
