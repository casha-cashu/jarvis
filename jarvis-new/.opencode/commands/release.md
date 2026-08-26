---
description: Синхронизировать jarvis-new → jarvis-github и выпустить релиз
agent: build
---
Sync working copy to GitHub and release: copy jarvis-new to jarvis-github (without venv, .env, SESSION.md), update version in pyproject.toml, git add/commit/push/tag in jarvis-github, then create GitHub release
