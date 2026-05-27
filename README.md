# JARVIS — Universal Voice Assistant

Голосовой ИИ-ассистент с поддержкой Linux и macOS. Распознаёт речь (Vosk / Whisper), выполняет системные команды, отвечает через LLM (локально или через API), синтезирует речь (Piper TTS).

## Features

- 🎤 **Распознавание речи** — Vosk (быстрый, офлайн) или faster-whisper (точный)
- 🔊 **Синтез речи** — Piper TTS (русский голос Дмитрия), gTTS fallback
- 🤖 **LLM интеграция** — Ollama (локально), OpenAI-совместимые API, Anthropic Claude
- 🖥️ **Управление системой** — воркспейсы, окна, скриншоты, звук, блокировка
- 🔌 **Кроссплатформенность** — автоопределение DE/WM (Hyprland, KDE, GNOME, i3, Sway, macOS)
- 💬 **Multi-turn диалоги** — 10с таймаут на follow-up, mute/unmute голосом
- ⏰ **Напоминания** — «напомни через 10 минут», «таймер на 5 минут»
- 📝 **Диктовка** — голосовой ввод текста через wtype/xdotool
- 🎯 **Wake word** — «джарвис» + альтернативы

## Поддерживаемые платформы

| OS | DE/WM | Статус |
|---|---|---|
| Linux (Arch) | Hyprland | ✅ |
| Linux (Arch/Debian/Fedora) | KDE Plasma | ✅ |
| Linux (Arch/Debian/Fedora) | GNOME | ✅ |
| Linux (Arch/Debian/Fedora) | i3 | ✅ |
| Linux (Arch/Debian/Fedora) | Sway | ✅ |
| macOS | macOS | ✅ |

## Быстрый старт

```bash
# Клонирование
git clone https://github.com/yourusername/jarvis-universal.git
cd jarvis-universal

# Установка (автоопределит Arch/Debian/Fedora/macOS)
bash install.sh

# Или через pip (после установки системных зависимостей)
pip install -e .
jarvis run
```

Скажите «джарвис» и дайте команду.

## Установка вручную

### Системные зависимости

**Arch Linux:**
```bash
sudo pacman -S python python-pip portaudio python-pyaudio piper-tts wtype xdotool
```

**Debian/Ubuntu:**
```bash
sudo apt install python3 python3-pip portaudio19-dev python3-pyaudio libnotify-bin xdotool wtype
```

**Fedora:**
```bash
sudo dnf install python3 python3-pip portaudio-devel python3-pyaudio libnotify xdotool wtype
```

**macOS:**
```bash
brew install python portaudio
```

### Python зависимости

```bash
pip install -e .           # Установит все зависимости из pyproject.toml
# Или вручную:
pip install pyyaml vosk pyaudio numpy faster-whisper anthropic requests gtts audioop-lts
```

### Модели

- **Vosk**: `python3 -c "from jarvis.setup import download_vosk; download_vosk()"`
- **faster-whisper**: скачивается автоматически при первом запуске
- **Piper TTS**: скачайте бинарник с [GitHub](https://github.com/rhasspy/piper/releases) и модель голоса

## Конфигурация

Отредактируйте `config.yaml`:

- **Микрофон**: укажите `device_name` вашего USB-микрофона
- **STT**: выберите `vosk` (быстрый) или `whisper` (точный)
- **LLM**: укажите провайдер (`ollama`, `kiro`, `openrouter`, `anthropic`)
- **TTS**: настройте пути к Piper бинарнику и модели

## Использование

```bash
# Полный список команд
jarvis --help

# Запуск с интерактивным выбором провайдера
jarvis run

# Запуск с конкретным провайдером
jarvis run -p ollama

# Запуск с пресетом
jarvis run --preset prod

# Режим без wake word
jarvis run --mode continuous

# Режим диктовки
jarvis dictation

# Управление пресетами
jarvis presets

# Тест модулей
jarvis test

# Systemd автозапуск (только Linux)
jarvis service install
```

## Примеры команд

| Голосовая команда | Действие |
|---|---|
| «первый воркспейс» / «воркспейс 3» | Переключение рабочего стола |
| «следующий воркспейс» | Следующий рабочий стол |
| «закрой окно» | Закрыть активное окно |
| «полный экран» | Развернуть на весь экран |
| «скриншот экрана» | Скриншот всего экрана |
| «громче» / «тише» | Регулировка громкости |
| «заблокируй экран» | Блокировка |
| «открой браузер» / «открой телеграм» | Запуск приложений |
| «какое время» / «какая дата» | Текущее время/дата |
| «диктовка» | Режим голосового ввода |
| «напомни через 10 минут» | Установка напоминания |

Всё, что не распознано как команда — отправляется в LLM.

## Архитектура

```
jarvis-universal/
├── config.yaml                 # Конфигурация
├── data/
│   ├── commands.json           # Команды (приложения + информация)
│   └── apps.json               # Приложения с алиасами
├── jarvis/
│   ├── cli.py                  # CLI entry point
│   ├── __init__.py             # Jarvis class (основной цикл)
│   ├── adapters/               # Платформенные адаптеры
│   │   ├── base.py             #   Базовый класс
│   │   ├── hyprland.py         #   Hyprland WM
│   │   ├── kde.py              #   KDE Plasma
│   │   ├── gnome.py            #   GNOME Shell
│   │   ├── i3.py               #   i3 WM
│   │   ├── sway.py             #   Sway WM
│   │   └── macos.py            #   macOS
│   └── modules/
│       ├── stt.py              # Vosk STT
│       ├── stt_whisper.py      # faster-whisper STT
│       ├── tts.py              # Piper TTS + gTTS
│       ├── llm.py              # LLM клиенты
│       ├── commands.py         # Обработка команд (pipeline)
│       ├── vad.py              # Silero VAD
│       ├── dictation.py        # Режим диктовки
│       ├── reminder.py         # Напоминания
│       └── platform_adapter.py # Автоопределение платформы
├── install.sh                  # Установщик (Arch/Debian/Fedora/macOS)
├── pyproject.toml              # Python пакет
├── LICENSE                     # MIT
└── README.md
```

## Как это работает

1. **Автоопределение платформы** — при запуске определяется ОС, дистрибутив и DE/WM
2. **Загрузка адаптера** — выбирается соответствующий адаптер (Hyprland, KDE, GNOME, etc.)
3. **Генерация команд** — команды генерируются динамически под текущую платформу
4. **Распознавание речи** — Vosk/Whisper слушает wake word и команды
5. **Pipeline обработки**: exact → fuzzy → pattern (открой {app}) → standalone app → voice cmd → LLM
6. **Озвучка** — Piper TTS озвучивает ответ
7. **Multi-turn** — после ответа 10с ожидание follow-up (прерывается wake word)

## Лицензия

MIT. Делайте что хотите.

## Благодарности

- [Vosk](https://alphacephei.com/vosk/) — Speech recognition
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Speech recognition
- [Piper](https://github.com/rhasspy/piper) — Text-to-speech
- [Silero VAD](https://github.com/snakers4/silero-vad) — Voice Activity Detection
- [Ollama](https://ollama.ai/) — Local LLM
