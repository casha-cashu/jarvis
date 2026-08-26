---
name: bash-agent-safety
description: "Use when editing bash_agent.py, tool execution, approval gates, or LLM-driven automation. Covers 3-layer safety model and tool output sanitization."
---

# Bash Agent Safety Skill

## Architecture

LLM-driven automation in `jarvis/modules/bash_agent.py`:

```
LLM requests tool → BashAgent.execute_tool()
    ├── Layer 1: Hardline blocklist (rm -rf /, mkfs, dd of=/dev/, fork bombs)
    ├── Layer 2: Dangerous-pattern detector (~20 patterns)
    ├── Layer 3: Approval gate (auto / strict / yolo)
    └── Execute: sanitized_env() + subprocess.run(timeout=...)
```

## Tools

| Tool | Description | Restrictions |
|---|---|---|
| `bash` | Execute shell command | Layers 1-3 + timeout |
| `read` | Read file content | None |
| `write` | Write to file | Blocks /etc, /usr, /boot, /sys, /proc, /dev |

## Approval Modes

Configured via `agent_approval_mode` in `config.yaml`:

| Mode | Behavior |
|---|---|
| `auto` | Execute dangerous commands after user confirmation |
| `strict` | Require confirmation for ALL commands (recommended) |
| `yolo` | Execute without asking (dangerous: only for trusted envs) |

## Blocklist (Layer 1 — hard rejection)

Patterns that result in immediate rejection with no path to approval:
- `rm -rf /`, `rm -rf /*`, `rm -rf ~`
- `mkfs.*`, `mkfs.ext4`, `mkfs.btrfs`
- `dd of=/dev/*`, `dd if=* of=/dev/*`
- Fork bombs: `:(){:|:&};:`, recursive functions
- `chmod 777 /`, `> /dev/sda`
- `shutdown`, `reboot`, `halt`

## Dangerous Patterns (Layer 2 — requires approval)

~20 patterns that trigger a warning but can proceed with confirmation:
- `curl <url> | sh`, `curl | bash`, `wget -O- | sh`
- `git push -f`, `git push --force`
- `iptables -F`, `iptables -X`
- `kill -9 -1`, `killall`
- `chmod 777`, `chown -R /`
- `> /etc/`, `>> /etc/` (any redirect to /etc)
- `:(){ :|:& };:`

## Tool Output Sanitization

Outputs from `bash` / `read` tools pass through:
- `truncate_tool_output()` — limits to configurable max_lines/max_bytes
- `redact_secrets()` — strips API keys, tokens, passwords from output
  before feeding back to LLM

## Hard Rules

- **All commands pass through `sanitized_env()`** — no API keys leak
- **All commands pass through `subprocess.run(timeout=...)`** — configurable
  via `commands.execution_timeout` (default: 30s)
- **No `shell=True`** anywhere in jarvis
- Security module is `jarvis/modules/bash_agent.py`