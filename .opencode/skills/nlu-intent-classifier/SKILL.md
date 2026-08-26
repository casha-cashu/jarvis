---
name: nlu-intent-classifier
description: "Use when editing nlu.py, IntentRouter, intent classification, slot extraction, or command pattern matching. Covers TF-IDF + LogisticRegression pipeline and NLU cache."
---

# NLU Intent Classifier Skill

## Architecture

Natural Language Understanding in `jarvis/modules/nlu.py`:

```
raw text → IntentRouter.parse() → IntentResult
    ├── raw: "открой telegram"
    ├── intent: "open_app"
    ├── intent_confidence: 0.89 (float)
    └── slots: { "app": "telegram" }
```

## Pipeline

1. **TF-IDF vectorizer** — converts Russian utterance to sparse feature vectors
2. **LogisticRegression classifier** — multiclass intent classification
   (trained at startup from `data/commands.json` + `data/apps.json`)
3. **Regex slot extractor** — extracts named entities:
   - `app` — application name from `apps.json`
   - `search` — search query after command prefix
   - `workspace` — workspace number
   - `volume_amount` — numeric volume level

## Key Files

- `jarvis/modules/nlu.py` — IntentRouter, IntentClassifier, slot extractors
- `data/commands.json` — training data for intent classification
- `data/apps.json` — application list for `open_app` intent

## NLU Cache

Cache via `JARVIS_NLU_CACHE` env var (default: `~/.cache/jarvis/classifier.joblib`):

```
Trained model (TF-IDF + LogisticRegression) → joblib.dump → cache file
On startup: if cache exists → joblib.load (skip training)
           if cache stale/missing → train from scratch → save
```

Set `JARVIS_NLU_CACHE=0` to force re-training on every startup.

## Integration in CommandExecutor

NLU runs at step 1.5 in `Commands.execute()`:

```
1. Check built-in commands (wake/mute/unmute)
1.5. NLU intent classification (if confidence > threshold)
2. Pattern-based command match (fallback)
3. LLM fallback
```

`CommandManager` auto-initializes NLU via `_init_nlu()`.
NLU result is attached as `ctx.nlu_result` dict.

## Editing Checklist

- `scikit-learn` must be installed (shared venv has it)
- When adding new commands/apps, update `data/commands.json` and`data/apps.json`
- Test with `python -m pytest tests/test_nlu_integration.py -v` (10 tests)
- Slot regex patterns are compiled once at init, not per-call
- `parse()` returns `{raw, intent, intent_confidence, slots}` — never mutate this shape