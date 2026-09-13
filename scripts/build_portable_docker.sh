#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== 1. Building / Verifying Ubuntu 22.04 Builder Image ==="
docker build -t jarvis-builder:ubuntu22 -f "${REPO_ROOT}/docker/Dockerfile.builder" "${REPO_ROOT}"

echo "=== 2. Compiling sidecar, frontend & Tauri bundles in Ubuntu 22.04 container ==="
mkdir -p "${HOME}/.cargo/registry" "${HOME}/.npm" "${REPO_ROOT}/dist/arch"

docker run --rm \
  -v "${REPO_ROOT}:/app" \
  -v "${HOME}/.cargo/registry:/usr/local/cargo/registry" \
  -v "${HOME}/.npm:/root/.npm" \
  -v "${HOME}/.cache/pip:/root/.cache/pip" \
  -e CARGO_TARGET_DIR=/app/jarvis-ui/src-tauri/target-ubuntu \
  -e APPIMAGE_EXTRACT_AND_RUN=1 \
  -e HOST_UID="$(id -u)" \
  -e HOST_GID="$(id -g)" \
  -w /app \
  jarvis-builder:ubuntu22 bash -c '
    set -euo pipefail
    echo "--- Building PyInstaller Sidecar (Python 3.10 + CPU torch) ---"
    python3 -m venv /tmp/venv
    /tmp/venv/bin/pip install --upgrade pip
    /tmp/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
    /tmp/venv/bin/pip install -e .
    /tmp/venv/bin/pip install pyinstaller
    /tmp/venv/bin/pyinstaller jarvis-bridge.spec --workpath /tmp/pyi-build --distpath /tmp/pyi-dist --noconfirm
    mkdir -p jarvis-ui/src-tauri/binaries
    cp /tmp/pyi-dist/jarvis-bridge jarvis-ui/src-tauri/binaries/jarvis-bridge-x86_64-unknown-linux-gnu
    chmod +x jarvis-ui/src-tauri/binaries/jarvis-bridge-x86_64-unknown-linux-gnu
    echo "Sidecar ready:"
    ls -lh jarvis-ui/src-tauri/binaries/jarvis-bridge-x86_64-unknown-linux-gnu

    echo "--- Building Frontend ---"
    cd /app/jarvis-ui
    npm ci
    npm run build

    echo "--- Building Tauri Bundles (deb, appimage) ---"
    npx tauri build --bundles deb,appimage
    DEB_PATH=$(find src-tauri -path "*/bundle/deb/*.deb" | head -1)
    APPIMAGE_PATH=$(find src-tauri -path "*/bundle/appimage/*.AppImage" | head -1)
    echo "Found deb: ${DEB_PATH}"
    echo "Found AppImage: ${APPIMAGE_PATH}"

    chown -R "${HOST_UID}:${HOST_GID}" /app/jarvis-ui/src-tauri/binaries /app/jarvis-ui/src-tauri/target-ubuntu /app/dist 2>/dev/null || true
'

echo "=== 3. Repacking Arch Package from Portable Deb via Arch Container ==="
DEB_FILE=$(find "${REPO_ROOT}/jarvis-ui/src-tauri/target-ubuntu" -name "JARVIS_*.deb" 2>/dev/null | head -1)
if [[ -z "${DEB_FILE}" || ! -f "${DEB_FILE}" ]]; then
  echo "❌ Ошибка: свежий .deb пакет не найден в target-ubuntu! Сборка остановлена." >&2
  exit 1
fi
mkdir -p "${REPO_ROOT}/dist/arch"
cp -v "${DEB_FILE}" "${REPO_ROOT}/dist/arch/"
docker run --rm -v "${REPO_ROOT}:/work" -w /work/dist/arch archlinux:latest bash -c "
  pacman -Syu --noconfirm --needed base-devel binutils zstd libarchive sudo >/dev/null 2>&1
  useradd -m -s /bin/bash builduser 2>/dev/null || true
  echo 'builduser ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/builduser
  chown -R builduser:builduser /work/dist/arch
  su - builduser -c 'cd /work/dist/arch && makepkg -f --nodeps'
"

echo "=== 4. Checking GLIBC Requirements ==="
JARVIS_BIN=$(find "${REPO_ROOT}/jarvis-ui/src-tauri" -name "jarvis" -type f -perm /111 2>/dev/null | grep release | head -1)
echo -n "jarvis binary (${JARVIS_BIN}) max GLIBC: "
strings "${JARVIS_BIN}" | grep GLIBC_2. | sort -V | tail -1
echo -n "jarvis-bridge sidecar max GLIBC: "
strings "${REPO_ROOT}/jarvis-ui/src-tauri/binaries/jarvis-bridge-x86_64-unknown-linux-gnu" | grep GLIBC_2. | sort -V | tail -1

echo "=== 5. Deploying to /tmp/jarvis_packages and Ventoy ==="
mkdir -p /tmp/jarvis_packages
APPIMAGE_FILE=$(find "${REPO_ROOT}/jarvis-ui/src-tauri" -name "JARVIS_*.AppImage" | head -1)
cp -v "${DEB_FILE}" /tmp/jarvis_packages/
cp -v "${APPIMAGE_FILE}" /tmp/jarvis_packages/JARVIS-x86_64.AppImage
cp -v "${REPO_ROOT}/dist/arch"/jarvis-*-x86_64.pkg.tar.zst /tmp/jarvis_packages/ || true

if [ -d "/run/media/misha/Ventoy" ]; then
  echo "Mirroring to Ventoy..."
  cp -v /tmp/jarvis_packages/* /run/media/misha/Ventoy/ 2>/dev/null || true
fi

echo "=== Portable build complete! ==="
