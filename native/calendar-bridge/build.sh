#!/usr/bin/env bash
# build.sh — produktive Kalender-Bridge (Modul 2; ADR-0016-Analogie, ADR-0018).
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

# macOS 12.3 = verbindliche Untergrenze (AV-29, ADR-0018). Der Kalender braucht
# selbst nichts oberhalb von 12.0, bleibt aber auf derselben Untergrenze wie
# die Kontakte — eine zweite Mindestversion im selben Produkt waere eine
# zusaetzliche Matrixachse ohne Gegenwert.
MIN_MACOS="${MIN_MACOS:-12.3}"
case "$(uname -m)" in
  arm64)  HOST_ARCH="arm64"  ;;
  x86_64) HOST_ARCH="x86_64" ;;
  *) echo "Nicht unterstuetzte Host-Architektur: $(uname -m)" >&2; exit 1 ;;
esac
TARGET="${TARGET:-${HOST_ARCH}-apple-macos${MIN_MACOS}}"

case "$TARGET" in
  arm64-*|aarch64-*) TAURI_TRIPLE="aarch64-apple-darwin" ;;
  x86_64-*)          TAURI_TRIPLE="x86_64-apple-darwin"  ;;
  *) echo "Unbekanntes TARGET-Praefix: $TARGET" >&2; exit 1 ;;
esac

SDK="$(xcrun --show-sdk-path)"
NAME="jarvis-calendar"
BIN="$BUILD/$NAME"
mkdir -p "$BUILD"

# Eingebettete Info.plist. BEIDE Usage-Description-Schluessel (Baseline B-13):
# `NSCalendarsUsageDescription` gilt bis macOS 13, `…FullAccess…` ab macOS 14.
# Fehlt der passende, beendet macOS den Prozess beim ersten Zugriff — belegt
# beim Kontakte-Sidecar mit dem Reminders-Schluessel.
PLIST="$BUILD/Info.plist"
cat > "$PLIST" <<'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>de.kluender.jarvis.calendar-bridge</string>
  <key>CFBundleName</key>
  <string>Jarvis Calendar Bridge</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <!-- Der Text erscheint dem Nutzer woertlich im Systemdialog. v1 liest
       ausschliesslich; ein Versprechen von "verwalten" waere falsch. macOS
       kennt fuer das Lesen von Terminen nur die Stufe "Vollzugriff" — das
       steht hier ehrlich, statt es zu verschweigen. -->
  <key>NSCalendarsUsageDescription</key>
  <string>Personal Jarvis liest deinen Kalender, um Termine lokal auf diesem Mac anzuzeigen und zu durchsuchen. Es werden keine Termine angelegt, geaendert oder geloescht und keine Daten uebertragen.</string>
  <key>NSCalendarsFullAccessUsageDescription</key>
  <string>Personal Jarvis liest deinen Kalender, um Termine lokal auf diesem Mac anzuzeigen und zu durchsuchen. macOS bietet fuer das Lesen nur die Stufe „Vollzugriff“ an; Jarvis legt trotzdem keine Termine an, aendert und loescht keine und uebertraegt keine Daten.</string>
</dict>
PLIST_EOF
echo '</plist>' >> "$PLIST"

echo "== 1/3 Swift kompilieren und linken ($TARGET) =="
swiftc -target "$TARGET" -sdk "$SDK" \
  "$SRC/sidecar.swift" \
  -framework EventKit -framework Foundation \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PLIST" \
  -o "$BIN"

echo "== 2/3 Schreibfreiheit am gebauten Binary pruefen =="
# Die Quelle enthaelt keinen Schreibaufruf (Test prueft das). Diese zweite,
# unabhaengige Pruefung sieht das ERGEBNIS an: taucht ein EventKit-Schreib-
# selektor in den Symbolen auf, wird nicht ausgeliefert. Ein Versprechen, das
# nur im Quelltext steht, ist keines.
VERBOTEN="saveEvent removeEvent commit saveCalendar removeCalendar"
GEFUNDEN=""
for sel in $VERBOTEN; do
  if nm -u "$BIN" 2>/dev/null | grep -qi "$sel" \
     || strings "$BIN" | grep -qx "${sel}:withSpan:error:"; then
    GEFUNDEN="$GEFUNDEN $sel"
  fi
done
if [ -n "$GEFUNDEN" ]; then
  echo "ABBRUCH: Schreibselektor im Binary gefunden:$GEFUNDEN" >&2
  exit 3
fi
echo "   keine EventKit-Schreibselektoren im Binary"

echo "== 3/3 Nachweise =="
echo "-- Architektur --";  lipo -info "$BIN"
echo "-- Mindestversion (muss minos $MIN_MACOS sein) --"
otool -l "$BIN" | grep -A3 LC_BUILD_VERSION | grep -E "minos|sdk"
echo "-- Eingebettete Info.plist --"
otool -P "$BIN" | grep -A1 -E "CFBundleIdentifier|NSCalendarsUsageDescription|NSCalendarsFullAccessUsageDescription" | grep string
echo "-- Tauri-externalBin-Name --"
echo "   $NAME-$TAURI_TRIPLE"
echo "BUILD OK: $BIN"
