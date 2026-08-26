---
description: Запустить линтер и проверку типов (ruff + ruff-format + mypy)
agent: build
---
Запусти полную проверку кода в jarvis-claude:

```bash
cd /home/misha/Projects/jarvis-py/jarvis-claude && source ../jarvis-new/venv/bin/activate && pip install pre-commit ruff mypy 2>/dev/null; pre-commit run --all-files
```

Если ruff/mypy/pre-commit не установлены — установи их сначала.

После получения ошибок:
1. Исправь ошибки ruff (форматирование)
2. Исправь ошибки mypy (типы)
3. Повтори проверку
4. Если после 3 попыток остались ошибки — остановись и сообщи