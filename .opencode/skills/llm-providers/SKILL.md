---
name: llm-providers
description: "Use when editing llm.py, LLM client implementations, chat_with_tools, or adding new LLM providers. Covers Ollama, OpenAI, Anthropic, OpenRouter clients."
---

# LLM Providers Skill

## Architecture

Four LLM providers in `jarvis/modules/llm.py`:

```
LLMManager (router by config.yaml::llm.provider)
    ├── ollama     → OllamaClient (local, tool-calling)
    ├── openai     → OpenAIClient (native SDK, tool-calling)
    ├── anthropic  → AnthropicClient (native SDK, tool-calling)
    └── openrouter → OpenRouterClient (chat only, no tools)
```

## Key Files

- `jarvis/modules/llm.py` — all client implementations + `LLMManager` factory
- `jarvis/modules/prompt_builder.py` — dynamic prompt composition, TTS
  sanitization, secret redaction
- `tests/test_llm.py` — 36 tests including 9 `chat_with_tools` mocked tests
- `tests/test_ollama_integration.py` — 5 real Ollama integration tests
  (marker: `ollama`, model: `qwen2.5:3b`)

## Provider Configuration

Each provider has its own config block in `config.yaml`:

```yaml
llm:
  provider: ollama  # default
  ollama: { model: "qwen2.5:3b", host: "http://localhost:11434" }
  openai: { model: "gpt-4o-mini", api_key: "${OPENAI_API_KEY}" }
  anthropic: { model: "claude-sonnet-4-20250514", api_key: "${ANTHROPIC_API_KEY}" }
  openrouter: { model: "anthropic/claude-sonnet-4-20250514", api_key: "${OPENROUTER_API_KEY}" }
```

API keys flow as kwargs into LLM clients via `config.yaml` → `provider_config`
→ `LLMManager`. They must NEVER be written to `os.environ`.

## chat_with_tools() Protocol

Three providers support tool-calling:

1. **Ollama**: raw HTTP POST to `/api/chat` with tool definitions JSON
2. **OpenAI**: native `client.chat.completions.create(tools=...)`
3. **Anthropic**: native `client.messages.create(tools=...)` with schema
   conversion (Anthropic format ↔ OpenAI format)

`OpenRouterClient` only has `chat()` — no `chat_with_tools()`.

Response shape from all `chat_with_tools()`:

```python
{
    "text": "I'll run that command",  # LLM text before tool call
    "tool_calls": [
        {"id": "call_1", "function": {"name": "bash", "arguments": '{"command":"ls"}'}}
    ],
    "finish_reason": "tool_calls" | "stop"
}
```

## History Persistence

All LLM clients share one history file at
`~/.local/share/jarvis/history.json`
(path override: `JARVIS_HISTORY_FILE`). History clamps to `llm.max_history`.
`clear_history()` writes empty list atomically (temp + atomic rename).

## Editing Checklist

1. Never add new `pip install` without checking `requirements.txt`/`pyproject.toml`
2. API keys must flow as constructor kwargs, NOT from `os.environ` directly
3. All `chat_with_tools()` responses must return the same shape
4. Run `python -m pytest tests/test_llm.py -v` after changes (36 tests)
5. If adding tool-calling to OpenRouter: note it doesn't support native tools