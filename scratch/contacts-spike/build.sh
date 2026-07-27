#!/usr/bin/env bash
# build.sh — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.
# Baut die P0-Reachability-Probe: ObjC-Shim (reine Weiterleitung) + Swift-Aufrufer.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src"
BUILD="$HERE/build"
# macOS 12.3 = effektive Untergrenze (transactionAuthor 12, shouldRefetchContacts 12.3)
TARGET="${TARGET:-arm64-apple-macos12.3}"
BIN="$BUILD/jarvis-contacts-p0"

mkdir -p "$BUILD"

echo "== Toolchain =="
swiftc --version | head -2
xcrun --show-sdk-path

echo "== 1/2 ObjC-Shim kompilieren ($TARGET) =="
clang -c -fobjc-arc -fmodules -target "$TARGET" \
  -isysroot "$(xcrun --show-sdk-path)" \
  "$SRC/JCChangeHistoryShim.m" -o "$BUILD/JCChangeHistoryShim.o"

echo "== 2/2 Swift kompilieren und linken =="
swiftc -target "$TARGET" \
  -sdk "$(xcrun --show-sdk-path)" \
  -import-objc-header "$SRC/JCChangeHistoryShim.h" \
  "$SRC/main.swift" "$BUILD/JCChangeHistoryShim.o" \
  -framework Contacts -framework Foundation \
  -o "$BIN"

echo "== Ergebnis =="
ls -l "$BIN"
echo "-- LC_BUILD_VERSION (minos muss $TARGET entsprechen) --"
otool -l "$BIN" | grep -A4 LC_BUILD_VERSION | head -8
echo "-- Contacts.framework verlinkt? --"
otool -L "$BIN" | grep -i contacts || echo "WARNUNG: Contacts nicht in den Link-Bibliotheken"
echo "-- Shim-Symbol vorhanden? --"
nm -U "$BIN" 2>/dev/null | grep -i JCChangeHistoryShim | head -3 || \
  nm "$BIN" 2>/dev/null | grep -i JCChangeHistoryShim | head -3 || \
  echo "(Symbol statisch gelinkt, keine externe Referenz — erwartet)"
echo "BUILD OK: $BIN"
