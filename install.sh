#!/bin/bash
# JARVIS Universal Installer
# Supports: Linux (Arch, Debian-based, Fedora), macOS
# Usage: bash install.sh

set -e

echo "==================================="
echo "  JARVIS Universal Voice Assistant"
echo "==================================="
echo ""

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
    sudo apt install -y python3 python3-pip python3-venv python3-dev \
        portaudio19-dev python3-pyaudio \
        libnotify-bin xdotool wtype espeak-ng mpv || true
}

install_fedora() {
    echo "📦 Установка зависимостей (Fedora)..."
    sudo dnf install -y python3 python3-pip gcc python3-devel portaudio-devel \
        libnotify xdotool wtype espeak-ng mpv || true
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
# PEP 668 (Debian 12+/Fedora/Arch): ставить в системный python нельзя,
# поэтому venv создаётся всегда. Флаг --venv сохранён для совместимости.
if [[ "$1" == "--venv" ]]; then
    echo "ℹ️  Флаг --venv больше не нужен: venv создаётся всегда."
fi
if [[ ! -d venv ]]; then
    echo ""
    echo "🐍 Создание виртуального окружения..."
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

echo ""
echo "🐍 Установка Python пакетов..."
pip install --upgrade pip
# CPU-сборка torch (без этого PyPI тянет CUDA-зависимости ~2.5GB);
# остальные зависимости ставятся из pyproject.toml одной командой ниже.
if [[ "$OS" == "linux" ]]; then
    pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
# Сам пакет + все зависимости (pydantic, scikit-learn, rapidfuzz, openai, ...)
# — в venv/bin появляется бинарь `jarvis`
pip install -e .

# ── Директории ──
echo ""
echo "📁 Создание директорий..."
mkdir -p models logs data

# ── Конфиг ──
if [[ ! -f config.yaml && -f config.example.yaml ]]; then
    cp config.example.yaml config.yaml
    echo "⚙️  Создан config.yaml из config.example.yaml — заполни ключи LLM."
fi

# ── Модели ──
echo ""
echo "📥 Модели ставятся интерактивно: source venv/bin/activate && jarvis setup"
echo "   (скачает Vosk модель и Piper-голос)"

echo ""
echo "✅ Установка завершена!"
echo ""
echo "Для запуска:"
echo "  source venv/bin/activate"
echo "  jarvis run"
echo ""
echo "Для настройки отредактируйте config.yaml"
