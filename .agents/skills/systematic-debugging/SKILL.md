---
name: systematic-debugging
description: >-
  Systematic root cause analysis and debugging protocol.
  Use when investigating unexpected behavior, test failures, crashes, or bugs.
  Enforces structured root-cause analysis over speculative code editing.
---

# Systematic Debugging Protocol

Never fix code by guessing or applying random modifications ("shotgun debugging").
Follow this 4-phase protocol to diagnose and eliminate bugs permanently.

---

## Phase 1: Reproduce the Defect

1. **Establish a Deterministic Baseline**:
   - Write a minimal failing test case or an isolated script (e.g. in `tests/` or temporary `scratch/debug_test.py`).
   - Confirm that the test fails consistently with the expected error message or assertion failure.
2. **Identify Boundaries**:
   - Determine what inputs trigger the bug and what inputs succeed.
   - For audio/display components, use mocks for hardware (`vosk`, `silero_vad`, `pyaudio`, `xdotool`) to prevent hanging.

---

## Phase 2: Isolate and Gather Evidence

1. **Trace Execution Path**:
   - Inspect the stack trace, relevant log lines, and arguments passed at each step.
   - Use non-destructive logging (`logger.debug(...)` or print statements in an isolated run) to observe runtime values.
2. **Check Invariants**:
   - Are environment variables missing or improperly sanitized?
   - Is there a type mismatch or unexpected `None`?
   - Is a dictionary key missing or misspelled?
   - Is a thread lock missing or held too long?

---

## Phase 3: Formulate and Test Hypotheses

1. **State the Root Cause Explicitly**:
   - Formulate a clear hypothesis: *"The bug occurs because function X expects format Y, but caller Z provides format W when condition C is met."*
2. **Verify Without Modifying Production Code**:
   - Test your hypothesis against the reproduction script.
   - If the hypothesis is wrong, discard it and form another based on new data. Do not start changing application code until the root cause is proven.

---

## Phase 4: Minimal Targeted Fix & Verification

1. **Apply the Minimal Fix**:
   - Change only what is necessary to address the root cause.
   - Avoid bundling opportunistic refactorings with bug fixes.
2. **Verify Red-to-Green**:
   - Re-run the reproduction test: it must now pass.
3. **Run Regression Suite**:
   - Run the full test suite to guarantee no collateral damage:
     ```bash
     PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q
     cd jarvis-ui && npm test -- --run
     ```
4. **Code Cleanliness**:
   - Remove any temporary print statements, debug logging, or scratch scripts before finalizing.
