# Stage 1: base — unit tests
FROM debian:bookworm-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev portaudio19-dev \
    libnotify-bin wtype xdotool espeak-ng git build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN python3 -m venv venv && venv/bin/pip install --upgrade pip setuptools && \
    venv/bin/pip install -e ".[dev]"

# Stage 2: integration — добавляет i3 + Xvfb
FROM base AS integration
RUN apt-get update && apt-get install -y --no-install-recommends \
    i3-wm xvfb x11-utils xdotool scrot xterm dbus dbus-x11 libnotify-bin \
    && rm -rf /var/lib/apt/lists/*
COPY docker/i3/config /etc/i3/config
COPY docker/i3/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
