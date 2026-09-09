---
name: diagnosing-bugs
description: >-
  Systematic root cause analysis and bug diagnosis skill. Investigates unexpected behavior,
  test failures, and crashes by isolating cause from symptom before writing code.
---

# Diagnosing Bugs (Root Cause Analysis)

Use this skill whenever investigating unexpected behavior, crashes, broken UI contracts, or test failures.

---

## The 4 Principles of Diagnosis

1. **Never Guess or Speculate**:
   - Formulate a testable hypothesis based on logs, stack traces, and deterministic reproduction.
   - Do not make random edits hoping something fixes the bug.

2. **Isolate Symptom from Cause**:
   - The line that throws an exception is often not the cause; look upstream at data invariants, corrupted state, or unhandled nulls.

3. **Minimal Reproduction**:
   - Strip away non-essential variables until you have the smallest possible command or test case that reproduces the bug reliably.

4. **Verify the Fix Against the Hypothesis**:
   - Confirm that the proposed change directly addresses the identified root cause, not merely masks the symptom.
