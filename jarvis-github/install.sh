#!/bin/bash
# JARVIS Universal Installer
# Supports: Linux (Arch, Debian-based, Fedora), macOS
# Usage: bash install.sh [--venv]

set -e

echo "==================================="
echo "  JARVIS Universal Voice Assistant"
echo "==================================="
echo ""

USE_VENV=false
if [[ "$1" == "--venv" ]]; then
    USE_VENV=true
fi

# Определяем ОС
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    echo "❌ Неподдерживаемая ОС: $OSTYPE"
    exit 1
fi

echo "🖥️  Платформа: $OS"

# Определяем дистрибутив Linux
DISTRO="unknown"
if [[ "$OS" == "linux" ]]; then
    if command -v pacman &> /dev/null; then
        DISTRO="arch"
    elif command -v apt &> /dev/null; then
        DISTRO="debian"
    elif command -v dnf &> /dev/null; then
        DISTRO="fedora"
    fi
fi

install_arch() {
    echo "📦 Установка зависимостей (Arch/Manjaro/CachyOS)..."
    sudo pacman -S --needed python python-pip portaudio python-pyaudio wtype xdotool --noconfirm || true
    # piper-tts в AUR (yay/paru), устанавливается опционально
    if command -v yay &> /dev/null; then
        yay -S --needed piper-tts --noconfirm 2>/dev/null || true
    elif command -v paru &> /dev/null; then
        paru -S --needed piper-tts --noconfirm 2>/dev/null || true
    else
        echo "⚠️  Установи piper-tts из AUR: yay -S piper-tts"
    fi
}

install_debian() {
    echo "📦 Установка зависимостей (Debian/Ubuntu)..."
    sudo apt update
    sudo apt install -y python3 python3-pip portaudio19-dev python3-pyaudio \
        libnotify-bin xdotool wtype espeak-ng || true
}

install_fedora() {
    echo "📦 Установка зависимостей (Fedora)..."
    sudo dnf install -y python3 python3-pip portaudio-devel python3-pyaudio \
        libnotify xdotool wtype espeak-ng || true
}

install_macos() {
    echo "📦 Установка зависимостей (macOS)..."
    if ! command -v brew &> /dev/null; then
        echo "❌ Homebrew не найден. Установите: https://brew.sh"
        exit 1
    fi
    brew install python portaudio
}

# ── Системные зависимости ──
if [[ "$OS" == "linux" ]]; then
    case "$DISTRO" in
        arch)   install_arch ;;
        debian) install_debian ;;
        fedora) install_fedora ;;
        *)      echo "⚠️  Неизвестный дистрибутив, пропускаем системные пакеты" ;;
    esac
elif [[ "$OS" == "macos" ]]; then
    install_macos
fi

# ── Python окружение ──
if $USE_VENV; then
    echo ""
    echo "🐍 Создание виртуального окружения..."
    python3 -m venv venv
    source venv/bin/activate
    PIP_CMD="venv/bin/pip"
else
    PIP_CMD="pip3"
fi

echo ""
echo "🐍 Установка Python пакетов..."
$PIP_CMD install --upgrade pip
$PIP_CMD install pyyaml vosk pyaudio numpy torch faster-whisper silero-vad --index-url https://download.pytorch.org/whl/cpu
$PIP_CMD install anthropic requests gtts
$PIP_CMD install audioop-lts  # Python 3.14 compat

# ── Директории ──
echo ""
echo "📁 Создание директорий..."
mkdir -p models logs data

# ── Модели ──
echo ""
echo "📥 Скачивание моделей (интерактивно)..."
python3 setup.py download-models 2>/dev/null || echo "⚠️  setup.py не найден, модели скачайте вручную"

echo ""
echo "✅ Установка завершена!"
echo ""
if $USE_VENV; then
    echo "Для запуска:"
    echo "  source venv/bin/activate"
    echo "  python3 -m jarvis run"
    echo ""
    echo "Или установите пакет:"
    echo "  source venv/bin/activate && pip install -e . && jarvis run"
else
    echo "Для запуска:"
    echo "  python3 -m jarvis run"
fi
echo ""
echo "Для настройки отредактируйте config.yaml"
