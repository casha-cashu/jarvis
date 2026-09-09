---
name: improve-codebase-architecture
description: >-
  Architectural analysis and refactoring skill. Finds structural bottlenecks,
  tight couplings, and architectural drift, proposing clean, minimal designs.
---

# Codebase Architecture Improvement

Use this skill when auditing, reviewing, or refactoring codebase architecture to keep the system simple, maintainable, and robust.

---

## Core Principles

1. **Thin Orchestrators, Focused Modules**:
   - Keep entry points and orchestrators (`Jarvis`, `main`) thin (~300-400 lines maximum).
   - Real business logic belongs in dedicated modular subsystems (`config_loader`, `audio_pipeline`, `response_pipeline`, `modules/`, `adapters/`).
2. **Interface Inversion & Platform Adapters**:
   - Hide OS/environment differences behind clean abstract interfaces (`BaseAdapter`).
   - Adapters must encapsulate platform commands without leaking OS-specific quirks to upper layers.
3. **Strict Isolation & Security Boundaries**:
   - Subprocesses must NEVER use `shell=True`.
   - Always sanitize environments (`sanitized_env()`) to prevent environment leaks.
   - Separate GUI/IPC boundaries cleanly via structured JSONL protocols.
4. **Simplicity Over Premature Abstraction**:
   - Do not create multi-tier abstractions for simple operations.
   - Delete dead code, unused shims, and redundant configuration paths.
