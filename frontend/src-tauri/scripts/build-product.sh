#!/usr/bin/env bash
#
# Der kanonische Produktbuild für macOS — der einzige Weg zu einem
# auslieferbaren Jarvis-Paket.
#
# Warum es ihn gibt
# -----------------
# `tauri build` allein hinterlässt ein Paket, das fertig *aussieht* und den
# Vertrag bricht. Zwei Ursachen, beide gemessen am Integrationsstand
# ff240978 auf arm64:
#
#   1. `signingIdentity` steht in `tauri.conf.json` auf `-`. Jedes Mach-O im
#      Bundle wird adhoc signiert und erbt die Entitlements der Anwendung.
#      Der Schreibhelfer trug so neun Rechte statt einem und den generierten
#      Identifier `contacts-write-helper-5555…` statt seines eigenen.
#
#   2. Das DMG entsteht **vor** jeder Nachbehandlung. Selbst wer
#      `reseal-contacts-sidecar.sh` kennt und ausführt, repariert damit nur
#      die `.app` im Targetordner — das ausgelieferte Image behält den
#      vertragswidrigen Helfer. Nachgewiesen: der Helfer im fertigen
#      `Jarvis_1.0.1_aarch64.dmg` war adhoc, neun Entitlements, falscher
#      Identifier.
#
# Dieses Skript ersetzt keine vorhandene Logik und legt keine zweite
# Paketierung daneben. Es ordnet die vorhandenen Schritte — Sidecarbau,
# Helferbau, `tauri build`, `reseal-contacts-sidecar.sh` — in die einzige
# Reihenfolge, in der das Ergebnis stimmt, und stellt einen Torwächter
# dahinter. Das DMG entsteht erst aus der gesiegelten App.
#
# Fail-closed heisst hier wörtlich: Ohne bestandenen Vertragsnachweis
# entsteht kein DMG, und der Exitcode ist ungleich null.
#
# Aufruf:
#   APPLE_SIGNING_IDENTITY="de.kluender.jarvis" ./build-product.sh [<triple>]
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC_TAURI="$(cd "$HERE/.." && pwd)"
FRONTEND="$(cd "$SRC_TAURI/.." && pwd)"
REPO="$(cd "$FRONTEND/.." && pwd)"

IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
if [ -z "$IDENTITY" ]; then
    cat >&2 <<'EOF'
APPLE_SIGNING_IDENTITY ist nicht gesetzt — der Build wird abgebrochen.

Ohne Identität entstünde genau der Zustand, den dieses Skript verhindert:
eine Adhoc-Signatur, die an den Codehash gebunden ist, keinen Neubau
überlebt und die einmal erteilte TCC-Berechtigung mitnimmt.
EOF
    exit 2
fi

if [ "${1:-}" != "" ]; then
    TRIPLE="$1"
else
    case "$(uname -m)" in
        arm64|aarch64) TRIPLE="aarch64-apple-darwin" ;;
        x86_64)        TRIPLE="x86_64-apple-darwin"  ;;
        *) echo "Nicht unterstützte Hostarchitektur: $(uname -m)" >&2; exit 2 ;;
    esac
fi

# Das Blatt wird aus dem Schlüsselbund aufgelöst, nicht im Skript genannt:
# Der Vertrag lautet „dasselbe Zertifikat wie die Identität", nicht „dieser
# eine Fingerabdruck".
LEAF="$(security find-identity -v -p codesigning \
        | grep -F "\"$IDENTITY\"" | head -1 | awk '{print $2}')"
if [ -z "$LEAF" ]; then
    echo "Keine Codesigning-Identität '$IDENTITY' im Schlüsselbund." >&2
    exit 2
fi

# Der Updater ist eine eigene Releasefrage und nicht die des Helfervertrags.
# `createUpdaterArtifacts` steht in `tauri.conf.json` auf true; ohne
# `TAURI_SIGNING_PRIVATE_KEY` endet `tauri build` deshalb ungleich null —
# **nachdem** es das Bundle bereits erzeugt hat. Diesen Exitcode einfach zu
# schlucken wäre genau die Sorte stiller Fehlschlag, die dieses Skript
# verhindern soll. Stattdessen wird die Updater-Erzeugung für diesen Lauf
# ausdrücklich abgeschaltet und der Lauf als das benannt, was er dann ist.
TAURI_ARGS=()
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
    TAURI_ARGS=(--config '{"bundle":{"createUpdaterArtifacts":false}}')
    UPDATER="ohne Updater-Artefakte (TAURI_SIGNING_PRIVATE_KEY nicht gesetzt)"
else
    UPDATER="mit Updater-Artefakten"
fi

TARGET_DIR="$SRC_TAURI/target/$TRIPLE/release"
APP="$TARGET_DIR/bundle/macos/Jarvis.app"
HELPER_TARGET="$TARGET_DIR/contacts-write-helper"
HELPER_SLOT="$SRC_TAURI/binaries/contacts-write-helper-$TRIPLE"
HELPER_PACKED="$APP/Contents/MacOS/contacts-write-helper"

echo "== Produktbuild =="
echo "   Triple:    $TRIPLE"
echo "   Identität: $IDENTITY"
echo "   Blatt:     ${LEAF:0:8}…"
echo "   Updater:   $UPDATER"

# ── 1. Frontend ─────────────────────────────────────────────────────────────
# Muss vor dem Helferbau laufen, nicht erst als `beforeBuildCommand` von
# `tauri build`: `generate_context!` prüft `frontendDist` bereits beim
# Kompilieren, und der Helfer wird aus demselben Crate gebaut. In einem
# frischen Worktree scheitert Schritt 3 sonst mit „this path doesn't exist".
echo
echo "== 1/8 Frontend bauen =="
( cd "$FRONTEND" && npm run build:tauri )

# ── 2. Sidecars ─────────────────────────────────────────────────────────────
echo
echo "== 2/8 Sidecars bauen und signieren =="
CONTACTS_SIDECAR_IDENTITY="$IDENTITY" "$HERE/build-contacts-sidecar.sh" "$TRIPLE"
CALENDAR_SIDECAR_IDENTITY="$IDENTITY" "$HERE/build-calendar-sidecar.sh" "$TRIPLE"

# ── 3. Schreibhelfer ────────────────────────────────────────────────────────
# `build.rs` verlangt jeden externalBin-Slot als existierende Datei, bevor es
# überhaupt kompiliert. Beim allerersten Build gibt es den Helfer aber noch
# nicht — die Henne-Ei-Lage wird mit einem Platzhalter aufgelöst, der sofort
# durch das echte Artefakt ersetzt wird.
echo
echo "== 3/8 Schreibhelfer bauen =="
if [ ! -f "$HELPER_SLOT" ]; then
    printf '#!/bin/sh\nexit 1\n' > "$HELPER_SLOT"
    chmod 755 "$HELPER_SLOT"
    echo "   Platzhalter für den ersten Durchlauf gesetzt."
fi
( cd "$SRC_TAURI" && cargo build --release --target "$TRIPLE" \
    --bin contacts-write-helper )
cp "$HELPER_TARGET" "$HELPER_SLOT"
chmod 755 "$HELPER_SLOT"

# ── 4. App und Installer bauen ──────────────────────────────────────────────
# Beide Bundles in **einem** Lauf, obwohl das DMG aus diesem Lauf verworfen
# wird. Der Grund ist gemessen, nicht theoretisch:
#
#   * `tauri bundle --bundles dmg` als zweiter Schritt erzeugt die `.app`
#     vollständig neu, signiert dabei jedes Mach-O wieder mit den
#     Entitlements der Anwendung — und **löscht die App danach**
#     („Cleaning …/bundle/macos/Jarvis.app"). Ein Reseal davor ist damit
#     wirkungslos, und der Torwächter hat genau das gefangen: 5 von 33
#     Nachweisen im DMG gebrochen, Helfer und beide Sidecars zurück auf neun
#     Rechten.
#   * Nur mit `--bundles app` entsteht `bundle_dmg.sh` gar nicht erst.
#
# Also: tauri baut beides, das DMG aus diesem Lauf ist Zwischenprodukt, und
# Schritt 8 erzeugt es aus der gesiegelten App neu — mit demselben Skript,
# das tauri selbst dafür verwendet.
echo
echo "== 4/8 App und Installer bündeln =="
( cd "$FRONTEND" && npx tauri build --target "$TRIPLE" --bundles app,dmg \
    "${TAURI_ARGS[@]}" )

# ── 5. Artefaktidentität ────────────────────────────────────────────────────
# `tauri build` baut den Bin selbst neu (Feature `custom-protocol`). Weicht
# das Ergebnis vom Slotinhalt ab, wurde etwas anderes gepackt als gemessen —
# dann wird der Slot nachgezogen und erneut gebündelt, bis alle drei Stellen
# dieselbe signaturinvariante Identität tragen.
uuid_of() { /usr/bin/dwarfdump --uuid "$1" | awk '{print $2}'; }

echo
echo "== 5/8 Artefaktidentität angleichen =="
for runde in 1 2 3; do
    U_TARGET="$(uuid_of "$HELPER_TARGET")"
    U_SLOT="$(uuid_of "$HELPER_SLOT")"
    U_PACKED="$(uuid_of "$HELPER_PACKED")"
    echo "   Runde $runde: target=$U_TARGET slot=$U_SLOT gepackt=$U_PACKED"
    if [ "$U_TARGET" = "$U_SLOT" ] && [ "$U_SLOT" = "$U_PACKED" ]; then
        echo "   Kette geschlossen."
        break
    fi
    if [ "$runde" = "3" ]; then
        echo "Artefaktidentität konvergiert nicht — Build abgebrochen." >&2
        exit 4
    fi
    cp "$HELPER_TARGET" "$HELPER_SLOT"
    chmod 755 "$HELPER_SLOT"
    ( cd "$FRONTEND" && npx tauri build --target "$TRIPLE" --bundles app,dmg \
    "${TAURI_ARGS[@]}" )
done

# ── 6. Siegeln ──────────────────────────────────────────────────────────────
echo
echo "== 6/8 Bundle siegeln =="
APPLE_SIGNING_IDENTITY="$IDENTITY" "$HERE/reseal-contacts-sidecar.sh" "$APP"

# ── 7. Torwächter ───────────────────────────────────────────────────────────
# Einzelnachweise statt Sammelaussage. `codesign --deep` bliebe hier grün,
# obwohl Identifier, Rechte und Blatt falsch wären.
echo
echo "== 7/8 Vertrag prüfen =="
( cd "$REPO" && uv run python -m tools.packaging.bundle_contract "$APP" \
    --entitlements-dir "$SRC_TAURI" \
    --expect-leaf "$LEAF" --expect-triple "$TRIPLE" )

# ── 8. Installer aus der gesiegelten App ────────────────────────────────────
# `bundle_dmg.sh` ist tauris eigenes, von tauri in diesen Ordner geschriebenes
# Skript mit dokumentierter Schnittstelle
# (`bundle_dmg.sh [options] <output.dmg> <source_folder>`). Es hier direkt auf
# die gesiegelte App anzusetzen ist Wiederverwendung derselben Paketierung,
# keine zweite daneben — der einzige Unterschied ist die Quelle: das Bundle,
# das den Vertrag erfüllt, statt eines frisch neu signierten.
DMG_DIR="$TARGET_DIR/bundle/dmg"
DMG_SCRIPT="$DMG_DIR/bundle_dmg.sh"
# Der Name kommt aus Schritt 4 — so heisst das Produkt, unabhängig von der
# hier nicht noch einmal zu erratenden Versions- und Architekturschreibweise.
DMG="$(ls "$DMG_DIR"/*.dmg 2>/dev/null | head -1 || true)"
if [ ! -x "$DMG_SCRIPT" ] || [ -z "$DMG" ]; then
    echo "tauris bundle_dmg.sh oder das Ausgangs-DMG fehlt in $DMG_DIR." >&2
    exit 5
fi

echo
echo "== 8/8 DMG aus dem gesiegelten Bundle neu erzeugen =="
STAGE="$(mktemp -d)"
# `ditto` statt `cp`: Es überträgt erweiterte Attribute und die eingebettete
# Signatur unverändert. Ein `cp -R` würde die Siegelung beschädigen.
ditto "$APP" "$STAGE/Jarvis.app"
rm -f "$DMG"
( cd "$DMG_DIR" && "$DMG_SCRIPT" \
    --volname "Jarvis" \
    --icon "Jarvis.app" 180 170 \
    --app-drop-link 480 170 \
    --window-size 660 400 \
    --hide-extension "Jarvis.app" \
    "$DMG" "$STAGE" )
rm -rf "$STAGE"

# Das Image selbst wird mit derselben Identität gesiegelt, wie tauri es tut.
codesign --force --sign "$IDENTITY" --timestamp=none "$DMG"

# Der Installer wird selbst geprüft, nicht als Folge der App unterstellt: Er
# ist das, was ausgeliefert wird.
echo
echo "== Vertrag im DMG prüfen =="
MOUNT="$(mktemp -d)"
trap 'hdiutil detach "$MOUNT" >/dev/null 2>&1 || true; rmdir "$MOUNT" 2>/dev/null || true' EXIT
hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT" "$DMG" >/dev/null
( cd "$REPO" && uv run python -m tools.packaging.bundle_contract \
    "$MOUNT/Jarvis.app" --entitlements-dir "$SRC_TAURI" \
    --expect-leaf "$LEAF" --expect-triple "$TRIPLE" )
hdiutil detach "$MOUNT" >/dev/null
rmdir "$MOUNT" 2>/dev/null || true
trap - EXIT

echo
echo "== Artefaktidentität =="
echo "   LC_UUID $(uuid_of "$HELPER_TARGET")"
printf '     %10s B  %s\n' "$(stat -f %z "$HELPER_TARGET")" "target/$TRIPLE/release/contacts-write-helper"
printf '     %10s B  %s\n' "$(stat -f %z "$HELPER_SLOT")" "binaries/contacts-write-helper-$TRIPLE"
printf '     %10s B  %s\n' "$(stat -f %z "$HELPER_PACKED")" "Jarvis.app/Contents/MacOS/contacts-write-helper"
echo "   (Der Grössenunterschied ist die eingebettete Signatur; SHA-256 taugt"
echo "    deshalb hier nicht, LC_UUID schon.)"

echo
echo "PRODUKTBUILD OK"
echo "  App: $APP"
echo "  DMG: $DMG"
