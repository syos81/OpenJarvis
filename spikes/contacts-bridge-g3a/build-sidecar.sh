#!/usr/bin/env bash
# build-sidecar.sh — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.
# Baut den Kontakte-Sidecar inkl. eingebetteter Info.plist-Sektion (G4).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src"
BUILD="$HERE/build"
# Beide macOS-Architekturen sind gleichwertige Produktionsziele: die Host-
# Architektur wird erkannt, TARGET bleibt zum Cross-Bauen überschreibbar.
# TAURI_TRIPLE ist der von Tauri erwartete externalBin-Suffix derselben Arch.
MIN_MACOS="${MIN_MACOS:-12.3}"
case "$(uname -m)" in
  arm64)  HOST_ARCH="arm64"  ;;
  x86_64) HOST_ARCH="x86_64" ;;
  *) echo "Nicht unterstützte Host-Architektur: $(uname -m)" >&2; exit 1 ;;
esac
TARGET="${TARGET:-${HOST_ARCH}-apple-macos${MIN_MACOS}}"
# externalBin-Suffix aus dem TATSÄCHLICHEN Ziel ableiten, nicht aus dem Host —
# sonst meldet ein Cross-Build den falschen Namen.
case "$TARGET" in
  arm64-*|aarch64-*) TAURI_TRIPLE="${TAURI_TRIPLE:-aarch64-apple-darwin}" ;;
  x86_64-*)          TAURI_TRIPLE="${TAURI_TRIPLE:-x86_64-apple-darwin}"  ;;
  *) echo "Unbekanntes TARGET-Präfix: $TARGET" >&2; exit 1 ;;
esac
SDK="$(xcrun --show-sdk-path)"
NAME="jarvis-contacts"
BIN="$BUILD/$NAME"

mkdir -p "$BUILD"

# ── G4/2: Info.plist des Sidecars (Diskriminator-Text "(SIDECAR)") ────────────
PLIST="$BUILD/sidecar-Info.plist"
cat > "$PLIST" <<'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>de.jarvis.contacts-spike.sidecar</string>
  <key>CFBundleName</key>
  <string>Jarvis Contacts Spike Sidecar</string>
  <key>CFBundleShortVersionString</key>
  <string>0.0.1</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>NSContactsUsageDescription</key>
  <string>Spike-Test: Zugriff auf Kontakte (SIDECAR)</string>
</dict>
</plist>
PLIST_EOF

echo "== 1/3 ObjC-Shim kompilieren ($TARGET) =="
clang -c -fobjc-arc -fmodules -target "$TARGET" -isysroot "$SDK" \
  "$SRC/JCChangeHistoryShim.m" -o "$BUILD/JCChangeHistoryShim.o"

echo "== 2/3 Swift kompilieren und linken (mit __TEXT,__info_plist) =="
swiftc -target "$TARGET" -sdk "$SDK" \
  -import-objc-header "$SRC/JCChangeHistoryShim.h" \
  "$SRC/sidecar.swift" "$BUILD/JCChangeHistoryShim.o" \
  -framework Contacts -framework Foundation \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PLIST" \
  -o "$BIN"

echo "== 3/3 Nachweise (G4: Sektion muss tatsächlich vorhanden sein) =="
echo "-- Architektur (muss $TARGET entsprechen) --"
lipo -info "$BIN"
echo "-- Tauri-externalBin-Name für diese Architektur --"
echo "   $NAME-$TAURI_TRIPLE"
echo "-- LC_BUILD_VERSION --"
otool -l "$BIN" | grep -A3 LC_BUILD_VERSION | grep -E "minos|sdk"
echo "-- Eingebettete Info.plist (otool -P) --"
if otool -P "$BIN" | grep -q "NSContactsUsageDescription"; then
  otool -P "$BIN" | grep -A1 "NSContactsUsageDescription"
  echo "G4-NACHWEIS: Sidecar traegt eigenen Usage-String = JA"
else
  echo "G4-NACHWEIS: Sidecar traegt eigenen Usage-String = NEIN"
fi
echo "-- Signaturstatus --"
codesign -dvvv "$BIN" 2>&1 | grep -E "Identifier|Signature|flags" || echo "(unsigniert)"
echo "BUILD OK: $BIN"
