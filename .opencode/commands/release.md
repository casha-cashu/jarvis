---
description: Синхронизировать jarvis-claude → jarvis-github и выпустить релиз
agent: build
---
Выполни релиз JARVIS согласно flow описанному в AGENTS.md:

1. **rsync** из jarvis-claude/ в jarvis-github/:
   ```bash
   rsync -av --delete \
     --exclude='.git' --exclude='venv' --exclude='.env' \
     --exclude='SESSION.md' --exclude='__pycache__' --exclude='*.pyc' \
     --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='*.joblib' \
     /home/misha/Projects/jarvis-py/jarvis-claude/ \
     /home/misha/Projects/jarvis-py/jarvis-github/
   ```

2. **Проверь .gitignore**: после rsync пересоздай `.gitignore` с `CLAUDE.md` и `classifier_*.joblib` если они просочились.

3. **Bump version** в `jarvis-github/pyproject.toml`

4. **Commit + push + tag**:
   ```bash
   cd /home/misha/Projects/jarvis-py/jarvis-github/
   git add -A
   git commit -m "vX.Y.Z: <описание изменений>"
   git -c credential.helper='!f() { echo "username=casha-cashu"; echo "password=$GITHUB_TOKEN"; }; f' push origin main --tags
   ```

5. **Создай GitHub Release**:
   ```bash
   curl -sS -X POST -H "Authorization: token $GITHUB_TOKEN" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/casha-cashu/jarvis/releases \
     -d '{"tag_name":"vX.Y.Z","name":"vX.Y.Z","body":"<release notes>","draft":false,"prerelease":false}'
   ```

6. **Вернись и обнови workspace docs**: если есть изменения в архитектуре — обнови `AGENTS.md`, `CLAUDE.md`, и knowledge-base.