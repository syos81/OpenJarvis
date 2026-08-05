#!/usr/bin/env bash
#
# Re-seal each bundled sidecar with exactly the entitlements it needs — one
# apiece — and then re-seal the enclosing .app.
#
# Since 2026-08-05 this covers two sidecars: Contacts and Calendar. The script
# keeps its name so the existing packaging evidence keeps pointing at one file;
# what changed is that a second single-purpose binary needs the same treatment,
# not the rule behind it.
#
# Why this exists
# ---------------
# `tauri build` signs every Mach-O inside the bundle with the *application's*
# Entitlements.plist. For the main binary that is correct; for the sidecar it
# is not. The sidecar would otherwise inherit `allow-jit`,
# `allow-unsigned-executable-memory`, `disable-library-validation` and both
# network rights — relaxations and grants that a small, single-purpose
# read-only process has no use for. An unused grant is still a grant.
#
# Each sidecar carries exactly one entitlement — address book for Contacts
# (ContactsSidecar.entitlements), calendars for Calendar
# (CalendarSidecar.entitlements). The entitlement is the signed statement that
# this binary means to touch that data; the actual decision stays with TCC,
# and TCC judges the responsible process — the app — not the child.
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
CONTACTS_ENTITLEMENTS="$HERE/../ContactsSidecar.entitlements"
CONTACTS_IDENTIFIER="de.kluender.jarvis.contacts-bridge"
CALENDAR_ENTITLEMENTS="$HERE/../CalendarSidecar.entitlements"
CALENDAR_IDENTIFIER="de.kluender.jarvis.calendar-bridge"

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

CONTACTS_SIDECAR="$APP/Contents/MacOS/jarvis-contacts"
CALENDAR_SIDECAR="$APP/Contents/MacOS/jarvis-calendar"

if [ ! -f "$CONTACTS_SIDECAR" ]; then
    echo "No bundled sidecar at $CONTACTS_SIDECAR" >&2
    exit 4
fi
if [ ! -f "$CALENDAR_SIDECAR" ]; then
    echo "No bundled sidecar at $CALENDAR_SIDECAR" >&2
    exit 4
fi

for ent in "$CONTACTS_ENTITLEMENTS" "$CALENDAR_ENTITLEMENTS"; do
    if [ ! -f "$ent" ]; then
        echo "Missing $ent — refusing to fall back to the app's entitlements," >&2
        echo "which is exactly what this script exists to prevent." >&2
        exit 5
    fi
done

echo "== 1/4 Re-sign each sidecar with its own minimal entitlements =="
codesign --force --sign "$IDENTITY" \
    --identifier "$CONTACTS_IDENTIFIER" \
    --options runtime --timestamp=none \
    --entitlements "$CONTACTS_ENTITLEMENTS" \
    "$CONTACTS_SIDECAR"
codesign --force --sign "$IDENTITY" \
    --identifier "$CALENDAR_IDENTIFIER" \
    --options runtime --timestamp=none \
    --entitlements "$CALENDAR_ENTITLEMENTS" \
    "$CALENDAR_SIDECAR"

echo "== 2/4 Re-sign the enclosing app =="
codesign --force --sign "$IDENTITY" \
    --options runtime --timestamp=none \
    --entitlements "$ENTITLEMENTS" \
    "$APP"

echo "== 3/4 Verify =="
codesign --verify --strict --verbose=2 "$CONTACTS_SIDECAR"
codesign --verify --strict --verbose=2 "$CALENDAR_SIDECAR"
codesign --verify --strict --deep --verbose=2 "$APP"

echo "== 4/4 Evidence =="
echo "-- Contacts sidecar entitlements (expected: address book only) --"
codesign -d --entitlements :- "$CONTACTS_SIDECAR" 2>&1 | tail -n +2
echo "-- Contacts sidecar designated requirement --"
codesign -d -r- "$CONTACTS_SIDECAR" 2>&1 | grep designated
echo "-- Calendar sidecar entitlements (expected: calendars only) --"
codesign -d --entitlements :- "$CALENDAR_SIDECAR" 2>&1 | tail -n +2
echo "-- Calendar sidecar designated requirement --"
codesign -d -r- "$CALENDAR_SIDECAR" 2>&1 | grep designated
echo "RESEAL OK"
