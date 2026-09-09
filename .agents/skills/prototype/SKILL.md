---
name: prototype
description: >-
  Rapid prototyping and spike development skill. Quickly constructs minimal working
  demonstrations to validate hypotheses, API integrations, and UX ideas before production code.
---

# Rapid Prototyping Workflow

Use this skill when exploring new features, third-party libraries, audio/hardware APIs, or novel UI concepts where uncertainty exists.

---

## 4-Step Prototyping Loop

```
1. Define Hypothesis ──► 2. Build Minimal Spike ──► 3. Validate Empirically ──► 4. Extract or Discard
```

### 1. Define the Core Hypothesis
- State exactly what needs to be verified (e.g. "Can we stream tokens from Ollama Cloud via HTTP chunked encoding?").
- Establish clear success and failure criteria.

### 2. Build Minimal Spike (Isolated)
- Keep spike code isolated from production packages:
  - Backend spike scripts belong in `scratch/` or `tools/`.
  - Frontend spike components belong in test mock harnesses.
- Use direct, unadorned code without boilerplate error-handling or complex configs.

### 3. Validate Empirically
- Run the spike with real input or live test data.
- Measure latency, memory, or behavior under edge cases.

### 4. Extract or Discard
- If successful: translate the proven design into production code following TDD and architectural guidelines.
- If failed: discard the spike cleanly without leaving dead code in the main tree.
