# Prompt Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make prompt enrichment happen in a lower confirmation workbench instead of overwriting the main textarea immediately.

**Architecture:** Keep `/prompt/enrich` as the single API endpoint, but return a structured result with either `action: "candidate"` or `action: "question"`. The browser stores the original text and candidate locally, renders clarification/candidate content below the main editor, and only copies the candidate into the main textarea when the user clicks "采用结果".

**Tech Stack:** Python standard library HTTP server, MiniMax OpenAI-compatible chat completions API, inline HTML/CSS/JavaScript, pytest.

---

### Task 1: Backend Contract Tests

**Files:**
- Modify: `tests/test_prompt_enrichment.py`

- [ ] Add a test proving JSON model output is normalized into `action`, `candidate`, `question`, and `text`.
- [ ] Add a test proving `mode="auto"` resolves to a concrete mode while preserving label/model/provider fields.
- [ ] Run `C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_prompt_enrichment.py -q` and confirm the new tests fail before implementation.

### Task 2: Frontend Contract Tests

**Files:**
- Modify: `tests/test_prompt_enrichment.py`

- [ ] Add a page test asserting the lower workbench controls exist: `promptWorkbench`, `promptQuestion`, `promptAnswer`, `promptCandidate`, `acceptPromptResult`, and `sendPromptAnswer`.
- [ ] Add a page test asserting the prompt mode select includes `value="auto"` and the enrichment success path calls `renderPromptWorkbench(...)` instead of assigning `textEl.value = data.result.text`.
- [ ] Run the same pytest command and confirm these tests fail before implementation.

### Task 3: Backend Implementation

**Files:**
- Modify: `src/gui_app.py`

- [ ] Add `resolve_prompt_mode(mode_id, library, text)` with a conservative heuristic for `auto`.
- [ ] Change `build_prompt_enrichment_messages(original, mode, answer="")` to request strict JSON and at most one clarification question.
- [ ] Add JSON extraction/normalization helpers that fall back to plain text as a candidate for compatibility.
- [ ] Update `enrich_prompt(..., answer="")` and `/prompt/enrich` to pass optional `answer`.
- [ ] Run `C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_prompt_enrichment.py -q` and confirm backend tests pass.

### Task 4: Frontend Implementation

**Files:**
- Modify: `src/gui_app.py`

- [ ] Add `auto` as the default prompt mode in the select.
- [ ] Add a lower prompt workbench area with question textarea, candidate preview, continue, clear, and accept buttons.
- [ ] Update JavaScript so enrichment renders the workbench and does not mutate the main textarea until `acceptPromptResult` is clicked.
- [ ] Run `C:\Users\0\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_prompt_enrichment.py -q` and confirm frontend tests pass.

### Task 5: Version, Docs, Build

**Files:**
- Modify: `src/gui_app.py`
- Modify: `VERSION`
- Modify: `README.md`
- Generated: `dist/DoubaoLanInputBridge_zh2en.exe`
- Generated: `local_update_source/update.json`

- [ ] Bump version to `0.5.4`.
- [ ] Document the new prompt workbench behavior in README.
- [ ] Run the full test/build script.
- [ ] Publish the local update source for the new build.
- [ ] Commit the finished change.
