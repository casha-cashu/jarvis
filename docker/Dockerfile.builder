# syntax=docker/dockerfile:1
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=/usr/local/cargo/bin:/usr/local/bin:$PATH

# System dependencies for Tauri, PyInstaller, WebKitGTK and audio
RUN apt-get update -o Acquire::Retries=5 && \
    apt-get install -y --no-install-recommends -o Acquire::Retries=5 \
        build-essential \
        curl \
        wget \
        git \
        pkg-config \
        libwebkit2gtk-4.1-dev \
        libgtk-3-dev \
        libayatana-appindicator3-dev \
        librsvg2-dev \
        patchelf \
        rpm \
        fuse \
        libfuse2 \
        libssl-dev \
        libsoup-3.0-dev \
        libjavascriptcoregtk-4.1-dev \
        portaudio19-dev \
        libasound2-dev \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        file \
        ca-certificates \
        zstd \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Rust stable
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal \
    && chmod -R a+w /usr/local/cargo /usr/local/rustup

WORKDIR /app
