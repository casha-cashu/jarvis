---
name: tdd-regression
description: >-
  Test-Driven Development (TDD) and regression prevention workflow for bug fixing.
  Use when fixing reported bugs, edge cases, contract breakages, or adding new features.
---

# TDD Bugfix & Regression Prevention Workflow

Every bug fix MUST follow the Red-Green-Refactor cycle.
Never touch production code to fix a defect until a test case has been created that demonstrates the defect.

---

## The 5-Step TDD Loop

```
1. Write Failing Test (RED)
       │
       ▼
2. Verify Failure Reason
       │
       ▼
3. Implement Minimal Fix (GREEN)
       │
       ▼
4. Verify Passing Test
       │
       ▼
5. Full Regression & Refactor
```

### Step 1: Write the Failing Test (Red)
- Place the test in the appropriate test module in `tests/` (backend) or `jarvis-ui/src/api/` (frontend).
- **Hermetic Mocking**:
  - Always mock external devices and network services:
    ```python
    @pytest.fixture
    def mock_deps(monkeypatch, tmp_path):
        monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("JARVIS_HISTORY_FILE", str(tmp_path / "history.json"))
        monkeypatch.setenv("JARVIS_NLU_CACHE", str(tmp_path / "nlu_cache.joblib"))
    ```
  - For audio/speech tests, stub hardware imports so the test executes in milliseconds without requiring ALSA/microphone.

### Step 2: Verify the Failure Reason
- Run only your new test:
  ```bash
  ./venv/bin/python -m pytest tests/test_my_fix.py -k "test_specific_bug" -v
  ```
- Confirm:
  - The test exits with code 1 (failure).
  - The failure output matches the reported bug (not an unrelated ImportError or syntax error).

### Step 3: Implement Minimal Fix (Green)
- Edit the target file in `jarvis/` or `jarvis-ui/src/`.
- Change only the lines necessary to satisfy the contract.
- Preserve backward compatibility and existing interfaces.

### Step 4: Verify the Pass
- Re-run the specific test:
  ```bash
  ./venv/bin/python -m pytest tests/test_my_fix.py -k "test_specific_bug" -v
  ```
- Confirm: The test now passes cleanly.

### Step 5: Full Regression Run
- Run the entire fast test suite:
  ```bash
  PYTHONPATH=. ./venv/bin/python -m pytest -m "not slow and not integration" -q
  cd jarvis-ui && npm test -- --run
  ```
- Verify that 0 existing tests broke.
