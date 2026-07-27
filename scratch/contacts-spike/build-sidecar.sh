#!/usr/bin/env bash
# build-sidecar.sh — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.
# Baut den Kontakte-Sidecar inkl. eingebetteter Info.plist-Sektion (G4).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src"
BUILD="$HERE/build"
TARGET="${TARGET:-arm64-apple-macos12.3}"
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
