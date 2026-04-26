# Workpaper Generation Flow Plan

## 1. What to Build / Architecture Changes (Very Minimal)
We will leverage the existing workpaper generation hook from the backend (`analysis.py`), but:
- Improve the structure of the workpaper text itself.
- Hide the workpaper from the user initially.
- Show a big "Generate Workpaper Draft" CTA button once the analysis results are complete.
- When clicked, expand the "Evaluation Workpaper" section, clearly marking it as a draft that must be reviewed.
- Hook up "Copy" and "Export TXT" functionality in the UI properly (fixing any broken on-click references from index.html).

## 2. Files Changed:
- `copilot/analysis.py`: Refactor `workpaper_text` block at the end of `analyze_evidence` to output the specific fields requested (Control Objective, Audit Procedure, Evidence Reviewed, Testing Performed, Results, Exceptions, Conclusions, Notes, plus Traceability) and append the disclaimer.
- `copilot/static/index.html`: 
  - Add a `<div id="ar-workpaper-cta-container">` with a "Generate Draft Workpaper" button.
  - Update `ar-workpaper-container` to include a "Copy" button.
  - Fix `onclick="exportTxt()"` -> `exportWorkpaperTXT()`.
  - Add inline UI disclaimers near the textarea: "Draft generated for auditor review. Please confirm accuracy before finalizing."
- `copilot/static/app.js`: 
  - In `renderAnalysisResults`, unhide `ar-workpaper-cta-container` INSTEAD of `ar-workpaper-container`.
  - Add the click handler function `generateWorkpaperDraft()` to unhide the container.
  - Implement a `copyWorkpaper()` function.

## 3. How Draft is Generated
The backend (`analysis.py`) creates a detailed markdown-style text representation directly. It will be sent via JSON payload as `workpaper_text`. The CTA button basically just opens up the UI to view the pre-generated text in an editable text box. 

## 4. Editing/Export Limitations
- It is editable within the browser textarea. If they type and then use "Copy" or "Export TXT", they will get their edits.
- BUT if the user re-runs analysis, their manual edits will be overwritten unless saved via an extra endpoint (which exists: `PUT /api/test_runs/{id}/workpaper`).
- Simple "Copy to Clipboard" and "Export TXT" will be the primary output tools. Export PDF already exists (will fix the UI if broken).

## 5. URL to test
http://127.0.0.1:8000
