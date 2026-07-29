#!/usr/bin/env bash
#
# Build the productive Contacts bridge sidecar and place it in the Tauri
# binaries/ directory under the externalBin target-triple naming convention.
#
# Usage:
#   ./build-contacts-sidecar.sh                      # auto-detect host target
#   ./build-contacts-sidecar.sh aarch64-apple-darwin
#   ./build-contacts-sidecar.sh x86_64-apple-darwin
#
# The sidecar sources live in native/contacts-bridge/ (ADR-0016). This script
# only wraps the existing build there and renames the result — it never
# downloads anything, never compiles at app runtime, and never reads spikes/.
#
# Signing is OPTIONAL and OFF by default. Without CONTACTS_SIDECAR_IDENTITY the
# script does not touch the keychain at all. Signing identities are never
# hardcoded here (Plan §15, ADR-0018).
#
# The delivery format (one universal artifact vs. two architecture-specific
# packages) is NOT decided here — DEC-D17 stays open. This script builds one
# target per invocation; both are equally valid inputs to either format.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BINARIES_DIR="$HERE/../binaries"
NATIVE_DIR="$HERE/../../../native/contacts-bridge"

if [ ! -x "$NATIVE_DIR/build.sh" ]; then
    echo "Sidecar sources not found: $NATIVE_DIR/build.sh" >&2
    exit 1
fi

# Determine target triple (Tauri externalBin convention).
if [ "${1:-}" != "" ]; then
    TARGET_TRIPLE="$1"
else
    case "$(uname -m)" in
        arm64|aarch64) TARGET_TRIPLE="aarch64-apple-darwin" ;;
        x86_64)        TARGET_TRIPLE="x86_64-apple-darwin"  ;;
        *) echo "Unsupported host architecture: $(uname -m)" >&2; exit 1 ;;
    esac
fi

# Map the Tauri triple to the compiler target. macOS 12.3 is the binding
# minimum on both architectures (ADR-0018 §2).
MIN_MACOS="12.3"
case "$TARGET_TRIPLE" in
    aarch64-apple-darwin) BUILD_TARGET="arm64-apple-macos${MIN_MACOS}"  ;;
    x86_64-apple-darwin)  BUILD_TARGET="x86_64-apple-macos${MIN_MACOS}" ;;
    *)
        echo "Unknown target triple: $TARGET_TRIPLE" >&2
        echo "Supported: aarch64-apple-darwin, x86_64-apple-darwin" >&2
        exit 2
        ;;
esac

echo "Target triple: $TARGET_TRIPLE  (compiler target: $BUILD_TARGET)"

BUILD_DIR="$NATIVE_DIR/build-${TARGET_TRIPLE}"
BUILD_DIR="$BUILD_DIR" TARGET="$BUILD_TARGET" MIN_MACOS="$MIN_MACOS" \
    "$NATIVE_DIR/build.sh"

SRC_BIN="$BUILD_DIR/jarvis-contacts"
OUT_FILE="$BINARIES_DIR/jarvis-contacts-${TARGET_TRIPLE}"

mkdir -p "$BINARIES_DIR"
cp "$SRC_BIN" "$OUT_FILE"
chmod 755 "$OUT_FILE"

# Optional local signing. Without the variable the keychain is never touched.
if [ -n "${CONTACTS_SIDECAR_IDENTITY:-}" ]; then
    echo "Signing with identity from CONTACTS_SIDECAR_IDENTITY"
    codesign --force --sign "$CONTACTS_SIDECAR_IDENTITY" \
        --identifier "de.kluender.jarvis.contacts-bridge" \
        --options runtime --timestamp=none "$OUT_FILE"
    codesign --verify --strict "$OUT_FILE"
else
    echo "Not signed (set CONTACTS_SIDECAR_IDENTITY to sign locally)."
fi

echo "-- Architecture --"
lipo -info "$OUT_FILE"
echo "-- Minimum system version (must be $MIN_MACOS) --"
otool -l "$OUT_FILE" | grep -A3 LC_BUILD_VERSION | grep -E "minos" | head -1
echo "OK: $OUT_FILE"
