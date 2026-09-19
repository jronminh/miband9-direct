#!/data/data/com.termux/files/usr/bin/bash
# Build the vendored adbwire. Output: tools/adbwire/out/adbwire
# Requires clang + openssl (`pkg install clang openssl`).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$HERE/out"
mkdir -p "$OUT_DIR"

command -v clang >/dev/null 2>&1 || { echo "clang not found: pkg install clang" >&2; exit 1; }

clang -O2 -Wall -Wextra -o "$OUT_DIR/adbwire" \
    "$HERE/adbwire.c" "$HERE/spake2.c" \
    "$HERE/ed25519/fe.c" "$HERE/ed25519/ge.c" "$HERE/ed25519/sc.c" \
    -lssl -lcrypto

echo "built $OUT_DIR/adbwire"
