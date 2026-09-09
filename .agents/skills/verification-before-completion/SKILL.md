---
name: verification-before-completion
description: >-
  Strict quality gate requiring empirical verification and automated proof before marking any task as complete.
  Use before declaring a task finished, submitting code reviews, or delivering bug fixes.
---

# Verification Before Completion Quality Gate

Never assume code works without running verification commands.
Never declare a task complete, fixed, or ready based purely on reading code or applying an edit.
You must execute the full automated test and verification suite and review the actual exit codes and output.

---

## The 5-Stage Verification Gate

Before completing any task, execute each gate sequentially:

### Gate 1: Python Backend Test Suite
```bash
PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q
```
- **Requirement**: 100% tests passing. Zero errors, zero unexpected warnings.
- **Rule**: NEVER run bare `pytest tests/` without markers — hardware tests will hang waiting for physical audio/display servers.

### Gate 2: Python Code Style & Types
```bash
./venv/bin/ruff check jarvis/ tests/
```
- **Requirement**: Zero lint errors.
- If formatting was modified:
  ```bash
  ./venv/bin/ruff format --check jarvis/ tests/
  ```

### Gate 3: Frontend Contract & Component Tests
```bash
cd jarvis-ui && npm test -- --run
```
- **Requirement**: All Vitest test suites (contracts, backend, providers, mocks) must pass green.

### Gate 4: Frontend Linter & Build
```bash
cd jarvis-ui && npm run lint
```
- **Requirement**: Zero Oxlint errors.
- If TypeScript types were changed:
  ```bash
  cd jarvis-ui && npm run build
  ```

### Gate 5: Rust Bridge & Tauri IPC
```bash
cargo check --manifest-path jarvis-ui/src-tauri/Cargo.toml
```
- **Requirement**: Successful compilation check without errors.

---

## Pass/Fail Criteria

| Criterion | Requirement | Failure Action |
|---|---|---|
| Test suite status | 100% passed | Revert or fix root cause immediately |
| Regressions | 0 existing tests broken | Investigate unexpected side effects |
| Linter warnings | 0 errors | Resolve lint issues before reporting |
| Process cleanup | No orphan processes | Ensure all child processes are killed/waited |

---

## Completion Report Template

Every task completion or handoff message must conclude with:
```markdown
### Verification Summary
- [x] Python Unit Tests: `<N> passed in <S>s`
- [x] Python Linter: `Ruff clean (0 errors)`
- [x] Frontend Vitest: `<N> passed in <S>s`
- [x] Frontend Linter: `Oxlint clean (0 errors)`
- [x] Rust Bridge: `Cargo check clean`
```
