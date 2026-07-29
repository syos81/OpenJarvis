#!/usr/bin/env bash
#
# Re-seal the bundled Contacts sidecar with the entitlements it actually needs
# — namely none — and then re-seal the enclosing .app.
#
# Why this exists
# ---------------
# `tauri build` signs every Mach-O inside the bundle with the *application's*
# Entitlements.plist. For the main binary that is correct; for the sidecar it
# is not. The sidecar would otherwise inherit `allow-jit`,
# `allow-unsigned-executable-memory` and `disable-library-validation` — three
# relaxations of the Hardened Runtime that a small, single-purpose read-only
# process has no use for. Entitlements are a grant, and an unused grant is
# still a grant.
#
# The sidecar needs no entitlement for Contacts access: the app is not
# sandboxed (Entitlements.plist sets app-sandbox=false), so TCC governs the
# access, not an entitlement.
#
# Order matters: nested code is sealed into the outer signature, so re-signing
# the sidecar invalidates the .app. The app is therefore re-signed afterwards,
# with its own entitlements unchanged.
#
# This script performs no Contacts operation and starts no process. It only
# re-signs and verifies.
#
# Usage:
#   APPLE_SIGNING_IDENTITY="<identity>" ./reseal-contacts-sidecar.sh <path-to-.app>

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-}"
IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
ENTITLEMENTS="$HERE/../Entitlements.plist"
SIDECAR_IDENTIFIER="de.kluender.jarvis.contacts-bridge"

if [ -z "$APP" ] || [ ! -d "$APP" ]; then
    echo "Usage: APPLE_SIGNING_IDENTITY=<id> $0 <path-to-.app>" >&2
    exit 2
fi
if [ -z "$IDENTITY" ]; then
    echo "APPLE_SIGNING_IDENTITY is not set — refusing to ad-hoc sign." >&2
    echo "An ad-hoc signature is bound to the code hash and does not survive" >&2
    echo "a rebuild, so the granted Contacts permission would be lost." >&2
    exit 3
fi

SIDECAR="$APP/Contents/MacOS/jarvis-contacts"
if [ ! -f "$SIDECAR" ]; then
    echo "No bundled sidecar at $SIDECAR" >&2
    exit 4
fi

echo "== 1/4 Re-sign sidecar without entitlements =="
codesign --force --sign "$IDENTITY" \
    --identifier "$SIDECAR_IDENTIFIER" \
    --options runtime --timestamp=none \
    "$SIDECAR"

echo "== 2/4 Re-sign the enclosing app =="
codesign --force --sign "$IDENTITY" \
    --options runtime --timestamp=none \
    --entitlements "$ENTITLEMENTS" \
    "$APP"

echo "== 3/4 Verify =="
codesign --verify --strict --verbose=2 "$SIDECAR"
codesign --verify --strict --deep --verbose=2 "$APP"

echo "== 4/4 Evidence =="
echo "-- Sidecar entitlements (expected: none) --"
codesign -d --entitlements - "$SIDECAR" 2>&1 | tail -n +2
echo "-- Sidecar designated requirement --"
codesign -d -r- "$SIDECAR" 2>&1 | grep designated
echo "RESEAL OK"
