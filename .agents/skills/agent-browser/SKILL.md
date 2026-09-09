---
name: agent-browser
description: >-
  Browser automation and web interaction skill. Enables autonomous browsing,
  clicking, filling forms, reading DOM/rendered content, and validating web interfaces.
---

# Agent Browser Workflow

Use this skill when interacting with web applications, performing end-to-end browser testing, capturing UI screenshots, or extracting content from dynamic web pages.

---

## Capabilities

1. **Navigation & Inspection**:
   - Open target URLs and inspect the rendered DOM/accessibility tree.
   - Wait for elements, loaders, and state changes to settle.
2. **User Interaction**:
   - Click buttons, links, tabs, and interactive controls by unique selector or text.
   - Type input into text fields, search boxes, and textareas.
   - Trigger keyboard events (Enter, Escape, Tab, Arrows).
3. **Verification & Artifacts**:
   - Capture full-page or element-specific screenshots to verify visual state.
   - Read console logs and network responses to verify API calls.

---

## Guidelines

- Prefer resilient selectors (data-testid, role, unique descriptive IDs) over brittle CSS hierarchies.
- Always verify page state before clicking or typing (ensure inputs are focused and visible).
- Clean up any temporary browser instances or sessions upon task completion.
