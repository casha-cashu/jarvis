---
description: Синхронизировать jarvis-claude → jarvis-github без релиза (только rsync + commit)
agent: build
---
Синхронизируй jarvis-claude в jarvis-github без релиза:

```bash
rsync -av --delete \
  --exclude='.git' --exclude='venv' --exclude='.env' \
  --exclude='SESSION.md' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.pytest_cache' --exclude='.ruff_cache' --exclude='*.joblib' \
  /home/misha/Projects/jarvis-py/jarvis-claude/ \
  /home/misha/Projects/jarvis-py/jarvis-github/
```

Затем проверь `.gitignore` (убедись что CLAUDE.md и classifier_*.joblib в нём),
и сделай commit + push без тега:

```bash
cd /home/misha/Projects/jarvis-py/jarvis-github/
git add -A
git commit -m "sync: jarvis-claude → jarvis-github"
git -c credential.helper='!f() { echo "username=casha-cashu"; echo "password=$GITHUB_TOKEN"; }; f' push origin main
```

Не создавай тег и не делай GitHub Release.