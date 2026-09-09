---
name: subagent-orchestration
description: >-
  Orchestration protocol for multi-agent teams.
  Defines roles, communication formats, ticket handoffs, and verification between Review and Fix subagents.
---

# Multi-Agent Orchestration Protocol

To reliably eliminate all bugs without regressions, work is organized into iterative waves of specialized subagents.

---

## Agent Roles and Responsibilities

```
                ┌──────────────────────────────────┐
                │        Lead Orchestrator         │
                └─────────────────┬────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼                                               ▼
   [Review Wave]                                   [Fix Wave]
  ├── Backend Reviewer (Python)                   ├── Backend Fixer (Python)
  ├── Bridge Reviewer (Rust/IPC)                  ├── Bridge Fixer (Rust/IPC)
  └── Frontend Reviewer (React)                   └── Frontend Fixer (React)
                                  │
                                  ▼
                         [QA & Verification]
                       └── Test Architect & QA Lead
```

### Review Agents
- **Backend Reviewer**: Audits `jarvis/` for unhandled exceptions, race conditions, missing locks, process leaks, and `sanitized_env()` compliance.
- **Bridge Reviewer**: Audits `jarvis/ui_bridge.py` and `jarvis-ui/src-tauri/src/lib.rs` for channel deadlocks, epoch desync, EOF crashes, and config sync.
- **Frontend Reviewer**: Audits `jarvis-ui/src/` for state desync, memory leaks, unhandled rejections, and reactivity bugs.

### Fix Agents
- **Backend Fixer**: Applies targeted drop-in diffs in Python, following the `tdd-regression` workflow.
- **Bridge Fixer**: Updates Rust and Python IPC handlers, ensuring channel safety and proper JSONL protocol compliance.
- **Frontend Fixer**: Resolves React state/event bugs and adds Vitest tests.

---

## Structured Handoff Schema (Review → Fix)

Every review finding delivered to a fix agent must adhere to this template:

```markdown
### [TICKET-ID] [SEVERITY] Summary of Bug
- **Component**: `backend` | `bridge` | `frontend`
- **File & Lines**: `path/to/file.py:123-145`
- **Root Cause**: Explanation of why the bug occurs.
- **Reproduction**: Minimal code snippet or command triggering the bug.
- **Proposed Solution**: Unified diff (`---`/`+++`) or concrete implementation plan.
- **Test Strategy**: How to verify the fix and prevent regressions.
```

---

## Coordination Invariants

1. **Isolation**: Fix agents work on non-overlapping files or coordinate sequential merges to prevent git conflicts.
2. **Deterministic Completion**: A wave is complete ONLY when:
   - All assigned tickets have passing regression tests.
   - The full verification gate (`verification-before-completion`) passes with 0 failures.
3. **Transparent Reporting**: The Lead Orchestrator aggregates all fixes into a concise user-facing summary and awaits user approval before launching the next wave.
