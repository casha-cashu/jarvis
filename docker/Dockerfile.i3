# syntax=docker/dockerfile:1
# Stage 1: base — unit tests
FROM debian:bookworm-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev portaudio19-dev \
    libnotify-bin wtype xdotool espeak-ng git build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Слои: манифесты -> deps (кэшируются) -> исходники. Любой чих репо
# больше не перекачивает torch.
COPY pyproject.toml requirements.txt ./
RUN python3 -m venv venv && \
    venv/bin/pip install --upgrade pip setuptools wheel && \
    venv/bin/pip install --retries 5 --timeout 120 torch --index-url https://download.pytorch.org/whl/cpu && \
    venv/bin/pip install --retries 5 --timeout 120 -r requirements.txt pytest pytest-cov pytest-mock pytest-timeout
COPY . .
RUN venv/bin/pip install -e ".[dev]" --no-deps

# Stage 2: integration — добавляет i3 + Xvfb
FROM base AS integration
RUN apt-get update && apt-get install -y --no-install-recommends \
    i3-wm xvfb x11-utils xdotool scrot xterm dbus dbus-x11 libnotify-bin \
    procps pulseaudio pulseaudio-utils dunst x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*
COPY docker/i3/config /etc/i3/config
COPY docker/i3/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
