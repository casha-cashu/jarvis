---
name: prompt-builder
description: "Use when editing prompt_builder.py, system prompts, LLM system messages, or tool-calling prompt engineering. Covers dynamic prompt composition and TTS sanitization."
---

# Prompt Builder Skill

## Architecture

Dynamic system prompt composition in `jarvis/modules/prompt_builder.py`:

```
compose_system_prompt()
    ├── Config: system_prompt_base   (Russian, platform-aware)
    ├── Config: system_prompt_tools  (tool calling instructions)
    └── Dynamic: agent_query_prefix() (conditionally prepended)

sanitize_for_tts() → post-process LLM response for TTS
    ├── Strip markdown (**bold**, *italic*, `code`)
    ├── Strip emojis
    ├── Normalize whitespace
    └── (preserves punctuation for natural prosody)

redact_secrets()       → strip API keys/tokens from tool output
truncate_tool_output() → limit tool output before feeding to LLM
```

## Config Keys (config.yaml)

```yaml
system_prompt_base: |
  Ты — JARVIS, голосовой ассистент на Linux. Работаешь через речь.
  Отвечай кратко, естественно, без разметки и эмодзи.
  Не упоминай, что ты ИИ — говори так, будто ты программа.
  Не используй слово "безопасность" и не читай лекций по безопасности.

system_prompt_tools: |
  Тебе доступны инструменты:
  - bash: выполнить команду в терминале
  - read: прочитать содержимое файла
  - write: записать в файл
  Правила: ...
```

## TTS Sanitization

Called on LLM response text before feeding to TTS engine:
- Removes: markdown formatting, emojis, code blocks
- Preserves: sentence structure, punctuation
- Returns: clean spoken Russian text

## Wiring

- `ResponsePipeline.start()` calls `compose_system_prompt()`
- `ResponsePipeline.process_query()` calls `sanitize_for_tts()` before TTS
- Bash-agent tool execution calls `redact_secrets()` + `truncate_tool_output()`