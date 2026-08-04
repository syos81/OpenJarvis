#!/usr/bin/env bash
# build-app.sh — SPIKE „Kalender-Fundament" (2026-08-04). Temporär, nicht produktiv.
#
# Packt die read-only Probe in ein signiertes App-Bündel. Der Umweg ist der
# eigentliche Versuch: TCC schreibt einen Zugriff dem **verantwortlichen**
# Prozess zu. Aus der Shell gestartet wäre das das Terminal — eine breite,
# dauerhafte Berechtigung, die über Jarvis nichts aussagt. Aus einem eigenen
# signierten Bündel gestartet ist es das Bündel: eng, benannt, widerrufbar,
# und genau die Kette, die das spätere Modul benutzen wird.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/build"
BIN="$BUILD/jarvis-calendar-probe"
APP="$BUILD/JarvisCalendarProbe.app"
IDENTITY="${IDENTITY:-Personal Jarvis Contacts Spike}"

test -x "$BIN" || { echo "Erst ./build.sh ausführen" >&2; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/JarvisCalendarProbe"

cat > "$APP/Contents/Info.plist" <<'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>JarvisCalendarProbe</string>
  <key>CFBundleIdentifier</key>
  <string>de.jarvis.calendar-spike.probe-app</string>
  <key>CFBundleName</key>
  <string>Jarvis Calendar Probe</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.0.1</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.3</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSCalendarsUsageDescription</key>
  <string>Spike-Test: nur lesender Zugriff auf Kalender und Termine (PROBE-APP)</string>
</dict>
</plist>
PLIST_EOF

echo "== Signieren mit Identität '$IDENTITY' und Hardened Runtime =="
codesign --force --options runtime --timestamp=none \
  --entitlements "$HERE/Probe.entitlements" \
  --sign "$IDENTITY" "$APP"

echo "== Nachweise =="
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -3
echo "-- Designated Requirement (muss zertifikatsgebunden sein) --"
codesign -d -r- "$APP" 2>&1 | grep -E "designated|certificate|cdhash" || true
echo "-- Usage-String im Bündel --"
/usr/libexec/PlistBuddy -c "Print :NSCalendarsUsageDescription" "$APP/Contents/Info.plist"
echo "-- Architektur --"
lipo -info "$APP/Contents/MacOS/JarvisCalendarProbe"
