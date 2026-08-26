---
description: Запустить unit-тесты JARVIS (без интеграционных/slow)
agent: build
---
Запусти unit-тесты JARVIS из jarvis-claude:

```bash
cd /home/misha/Projects/jarvis-py/jarvis-claude && source ../jarvis-new/venv/bin/activate && python -m pytest tests/ -m "not slow and not integration" -q --ignore=tests/integration
```

Если есть падения — запусти 3 попытки self-healing цикла: прочитай ошибку, исправь код, перезапусти тесты. После 3 неудачных попыток остановись и сообщи пользователю.