#!/usr/bin/env bash
# build.sh — SPIKE „Kalender-Fundament" (2026-08-04). Temporär, nicht produktiv.
# Baut die read-only EventKit-Probe mit eingebetteter Info.plist-Sektion.
#
# Der Usage-String muss im Binary stecken, nicht daneben liegen: TCC liest ihn
# aus __TEXT,__info_plist des verantwortlichen Codes. Fehlt er, gibt es keinen
# Dialog — nur ein stilles `denied`.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src"
BUILD="$HERE/build"
MIN_MACOS="${MIN_MACOS:-12.3}"
case "$(uname -m)" in
  arm64)  HOST_ARCH="arm64"  ;;
  x86_64) HOST_ARCH="x86_64" ;;
  *) echo "Nicht unterstützte Host-Architektur: $(uname -m)" >&2; exit 1 ;;
esac
TARGET="${TARGET:-${HOST_ARCH}-apple-macos${MIN_MACOS}}"
SDK="$(xcrun --show-sdk-path)"
NAME="jarvis-calendar-probe"
BIN="$BUILD/$NAME"

mkdir -p "$BUILD"

PLIST="$BUILD/probe-Info.plist"
cat > "$PLIST" <<'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>de.jarvis.calendar-spike.probe</string>
  <key>CFBundleName</key>
  <string>Jarvis Calendar Spike Probe</string>
  <key>CFBundleShortVersionString</key>
  <string>0.0.1</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>NSCalendarsUsageDescription</key>
  <string>Spike-Test: nur lesender Zugriff auf Kalender und Termine (PROBE)</string>
</dict>
</plist>
PLIST_EOF

echo "== Toolchain =="
swiftc --version | head -2
echo "SDK: $SDK"

echo "== Kompilieren und linken ($TARGET) =="
swiftc -target "$TARGET" -sdk "$SDK" \
  "$SRC/main.swift" \
  -framework EventKit -framework Foundation -framework CryptoKit \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PLIST" \
  -o "$BIN"

echo "== Nachweise =="
lipo -info "$BIN"
otool -l "$BIN" | grep -A3 LC_BUILD_VERSION | grep -E "minos|sdk"
if otool -P "$BIN" | grep -q "NSCalendarsUsageDescription"; then
  echo "Usage-String eingebettet = JA"
else
  echo "Usage-String eingebettet = NEIN"
fi
echo "-- Es darf keine Schreib-API im Binary auftauchen --"
if nm -u "$BIN" 2>/dev/null | grep -Eq "saveEvent|removeEvent|EKEventStore.*commit"; then
  echo "SCHREIB-API GEFUNDEN — Spike-Grenze verletzt" >&2
  exit 1
fi
echo "keine Schreib-API referenziert = JA"
codesign -dvvv "$BIN" 2>&1 | grep -E "Identifier|Signature|flags" || echo "(unsigniert)"
