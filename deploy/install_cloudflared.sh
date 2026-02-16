#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/install_cloudflared.sh"
  exit 1
fi

TMP_BIN="/tmp/cloudflared"
TARGET_BIN="/usr/local/bin/cloudflared"
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
  x86_64|amd64) CF_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
  *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

curl -fL -o "${TMP_BIN}" "${CF_URL}"
chmod +x "${TMP_BIN}"
install -m 0755 "${TMP_BIN}" "${TARGET_BIN}"
rm -f "${TMP_BIN}"

"${TARGET_BIN}" --version
