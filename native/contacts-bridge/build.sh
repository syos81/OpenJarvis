#!/usr/bin/env bash
# build.sh — produktive Kontakte-Bridge (ADR-0016, ADR-0018).
#
# Baut den Sidecar für EINE Zielarchitektur. Beide macOS-Architekturen sind
# gleichwertige Produktionsziele (DEC-042); die Host-Architektur wird erkannt,
# TARGET bleibt zum Cross-Bauen überschreibbar.
#
# Die Abnahme erfolgt ausschließlich NATIV auf echter Hardware je Architektur —
# ein Cross-Build ist ein Bauartefakt, kein Nachweis (ADR-0018 §5).
# Das Auslieferungsformat (DEC-D17) wird hier NICHT entschieden.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src"
BUILD="${BUILD_DIR:-$HERE/build}"

# macOS 12.3 = verbindliche Untergrenze (AV-29, ADR-0018):
# CNSaveRequest.transactionAuthor ab 12, shouldRefetchContacts ab 12.3.
MIN_MACOS="${MIN_MACOS:-12.3}"
case "$(uname -m)" in
  arm64)  HOST_ARCH="arm64"  ;;
  x86_64) HOST_ARCH="x86_64" ;;
  *) echo "Nicht unterstuetzte Host-Architektur: $(uname -m)" >&2; exit 1 ;;
esac
TARGET="${TARGET:-${HOST_ARCH}-apple-macos${MIN_MACOS}}"

# externalBin-Suffix aus dem TATSAECHLICHEN Ziel ableiten, nicht aus dem Host.
case "$TARGET" in
  arm64-*|aarch64-*) TAURI_TRIPLE="aarch64-apple-darwin" ;;
  x86_64-*)          TAURI_TRIPLE="x86_64-apple-darwin"  ;;
  *) echo "Unbekanntes TARGET-Praefix: $TARGET" >&2; exit 1 ;;
esac

SDK="$(xcrun --show-sdk-path)"
NAME="jarvis-contacts"
BIN="$BUILD/$NAME"
mkdir -p "$BUILD"

# Eingebettete Info.plist: eigener produktiver Usage-String und Identifier.
PLIST="$BUILD/Info.plist"
cat > "$PLIST" <<'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>de.kluender.jarvis.contacts-bridge</string>
  <key>CFBundleName</key>
  <string>Jarvis Contacts Bridge</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <!-- Der Text erscheint dem Nutzer woertlich im Systemdialog. Lesen ist
       der Normalfall; ein Anlegen geschieht ausschliesslich nach einer
       ausdruecklichen Einzelfreigabe (ADR-0025, Phase M2). Ein Versprechen
       von "verwalten" waere weiterhin falsch. -->
  <key>NSContactsUsageDescription</key>
  <string>Personal Jarvis liest deine Kontakte, um sie lokal auf diesem Mac zu durchsuchen und zu ordnen. Neue Kontakte werden nur nach deiner ausdruecklichen Freigabe angelegt; bestehende Kontakte werden nicht veraendert und keine Daten uebertragen.</string>
</dict>
PLIST_EOF
echo '</plist>' >> "$PLIST"

echo "== 1/4 Objective-C-Shims kompilieren ($TARGET) =="
clang -c -fobjc-arc -fmodules -target "$TARGET" -isysroot "$SDK" \
  "$SRC/JCChangeHistoryShim.m" -o "$BUILD/JCChangeHistoryShim.o"
clang -c -fobjc-arc -fmodules -target "$TARGET" -isysroot "$SDK" \
  "$SRC/JCContactsSaveShim.m" -o "$BUILD/JCContactsSaveShim.o"

echo "== 2/4 Shim-Harness bauen und ausfuehren (kontaktfrei) =="
# Der Harness prueft die @try/@catch-Grenze ausschliesslich mit Fakes —
# kein CNContactStore, kein Kontaktzugriff. Er laeuft bei JEDEM Build:
# ein gebrochener Shim kann damit gar nicht erst gepackt werden. Beim
# Cross-Bauen ist das Testbinary nicht ausfuehrbar; dann wird es nur gebaut.
clang -fobjc-arc -fmodules -target "$TARGET" -isysroot "$SDK" \
  "$SRC/JCContactsSaveShimTests.m" "$BUILD/JCContactsSaveShim.o" \
  -framework Foundation -framework Contacts \
  -o "$BUILD/$NAME-shim-tests"
if [ "$(uname -m)" = "${TARGET%%-*}" ]; then
  "$BUILD/$NAME-shim-tests"
else
  echo "   (Cross-Build: Harness gebaut, Ausfuehrung uebersprungen)"
fi

echo "== 3/4 Swift kompilieren und linken =="
swiftc -target "$TARGET" -sdk "$SDK" \
  -import-objc-header "$SRC/JCBridgingHeader.h" \
  "$SRC/sidecar.swift" \
  "$BUILD/JCChangeHistoryShim.o" "$BUILD/JCContactsSaveShim.o" \
  -framework Contacts -framework Foundation \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PLIST" \
  -o "$BIN"

echo "== 4/4 Nachweise =="
echo "-- Architektur --";  lipo -info "$BIN"
echo "-- Mindestversion (muss minos $MIN_MACOS sein) --"
otool -l "$BIN" | grep -A3 LC_BUILD_VERSION | grep -E "minos|sdk"
echo "-- Eingebettete Info.plist --"
otool -P "$BIN" | grep -A1 -E "CFBundleIdentifier|NSContactsUsageDescription" | grep string
echo "-- Tauri-externalBin-Name --"
echo "   $NAME-$TAURI_TRIPLE"
echo "BUILD OK: $BIN"
