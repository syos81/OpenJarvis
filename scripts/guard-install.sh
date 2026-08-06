#!/bin/bash
# Owner activation of the external PreToolUse guard.
#
# This script is prepared by Claude Code and executed by Lukas. It refuses to
# run unless it is root, so the guarded session can never activate, update or
# relocate the guard on its own.
#
#   sudo /bin/bash scripts/guard-install.sh \
#     --commit <full-oid> --expect-hash <sha256> [--target <dir>] [--dry-run]
#
# What it does, in order, aborting on the first problem:
#
#   1. verify root, session user, target and the committed source state,
#   2. build the package from the *commit object*, never from the worktree,
#   3. compare the built hash with the expected hash,
#   4. back up the currently active version for owner rollback,
#   5. install atomically, set owner and modes,
#   6. create the protected runtime area with its ACLs,
#   7. create or validate the protected hook registration,
#   8. re-verify hash, owner, modes and the ACL behaviour,
#   9. append to the protected activation log.
#
# On any failure after step 5 the previous version is restored.

set -euo pipefail

export LC_ALL=C
export LANG=C
export TZ=UTC
export PYTHONDONTWRITEBYTECODE=1

readonly DEFAULT_TARGET="/usr/local/jarvis-guard"
# /usr/bin/python3 is only a stub. On this platform it resolves into a
# developer tools bundle that can belong to the ordinary user, which would
# put a session writable interpreter into the trust chain. The Command Line
# Tools framework binary is root owned along its whole ancestor chain.
readonly GUARD_PYTHON="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9"
readonly GIT_BIN="/usr/bin/git"
readonly POLICY_DIR="/Library/Application Support/ClaudeCode"
readonly POLICY_FILE="${POLICY_DIR}/managed-settings.json"

COMMIT=""
EXPECT_HASH=""
TARGET="${DEFAULT_TARGET}"
DRY_RUN="no"
SESSION_USER="${SUDO_USER:-}"

die() {
  printf 'guard-install: %s\n' "$1" >&2
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --commit) COMMIT="${2:-}"; shift 2 ;;
    --expect-hash) EXPECT_HASH="${2:-}"; shift 2 ;;
    --target) TARGET="${2:-}"; shift 2 ;;
    --session-user) SESSION_USER="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN="yes"; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

# --dry-run builds and reports only; it installs nothing and therefore needs
# no privileges. Every path that touches the protected installation does.
if [ "${DRY_RUN}" != "yes" ]; then
  [ "$(id -u)" = "0" ] || die "must run as root (use sudo); the guarded session cannot activate the guard"
fi
[ -n "${COMMIT}" ] || die "--commit is required"
[ -n "${EXPECT_HASH}" ] || die "--expect-hash is required"
[ -n "${SESSION_USER}" ] || die "--session-user is required when SUDO_USER is unset"
case "${COMMIT}" in
  *[!0-9a-f]* | "") die "--commit must be a full lowercase object id" ;;
esac
[ "${#COMMIT}" = "40" ] || die "--commit must be a full 40 character object id"
case "${EXPECT_HASH}" in
  *[!0-9a-f]* | "") die "--expect-hash must be a lowercase sha256" ;;
esac
[ "${#EXPECT_HASH}" = "64" ] || die "--expect-hash must be a 64 character sha256"
[ -x "${GUARD_PYTHON}" ] || die "system interpreter not available: ${GUARD_PYTHON}"
[ -x "${GIT_BIN}" ] || die "system git not available: ${GIT_BIN}"
id -u "${SESSION_USER}" >/dev/null 2>&1 || die "unknown session user: ${SESSION_USER}"

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
readonly SCRIPT_DIR
WORKTREE="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly WORKTREE

# Running as root against a repository owned by the session user trips git's
# ownership check. The path is derived from this script's own location, so
# trusting it here is not a widening of the boundary.
GIT_COMMON="$("${GIT_BIN}" -C "${WORKTREE}" rev-parse --git-common-dir 2>/dev/null || echo "")"
readonly GIT_COMMON
git_repo() {
  "${GIT_BIN}" -c "safe.directory=${WORKTREE}" \
    -c "safe.directory=${GIT_COMMON}" \
    -c "safe.directory=*" \
    -C "${WORKTREE}" "$@"
}

git_repo cat-file -e "${COMMIT}^{commit}" 2>/dev/null \
  || die "commit not present in this repository: ${COMMIT}"

STAGE="$(mktemp -d -t jarvis-guard-stage)"
readonly STAGE
cleanup() {
  if [ -d "${STAGE}" ]; then
    /bin/rm -rf -- "${STAGE}"
  fi
  return 0
}
trap cleanup EXIT

# 2. build from the commit object, never from the working tree
SOURCE="${STAGE}/source"
mkdir -p "${SOURCE}"
git_repo archive --format=tar "${COMMIT}" tools/guard tools/guardpkg \
  | tar -x -C "${SOURCE}" -f -
[ -d "${SOURCE}/tools/guard" ] || die "commit does not contain tools/guard"
[ -f "${SOURCE}/tools/guardpkg/bootstrap.py" ] || die "commit does not contain the bootstrap"

BUILD_REPORT="$("${GUARD_PYTHON}" -I -B "${SOURCE}/tools/guardpkg/build.py" \
  --source "${SOURCE}" --out "${STAGE}/build")"
BUILT_HASH="$(printf '%s' "${BUILD_REPORT}" \
  | "${GUARD_PYTHON}" -I -B -c 'import json,sys;print(json.load(sys.stdin)["package_sha256"])')"
readonly BUILT_HASH

printf 'guard-install: built package hash %s\n' "${BUILT_HASH}"
[ "${BUILT_HASH}" = "${EXPECT_HASH}" ] \
  || die "package hash mismatch: built ${BUILT_HASH}, expected ${EXPECT_HASH}"

GUARD_VERSION="$("${GUARD_PYTHON}" -I -B -c \
  'import sys;sys.path.insert(0,sys.argv[1]);import guard;print(guard.GUARD_VERSION)' \
  "${STAGE}/build/active")"
CONFIG_SCHEMA="$("${GUARD_PYTHON}" -I -B -c \
  'import sys;sys.path.insert(0,sys.argv[1]);import guard;print(guard.CONFIG_SCHEMA)' \
  "${STAGE}/build/active")"
readonly GUARD_VERSION CONFIG_SCHEMA

ACTIVATED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
readonly ACTIVATED_AT

if [ "${DRY_RUN}" = "yes" ]; then
  printf 'guard-install: dry run only — nothing installed\n'
  printf 'guard-install: version %s, schema %s, target %s\n' \
    "${GUARD_VERSION}" "${CONFIG_SCHEMA}" "${TARGET}"
  exit 0
fi

# 4. back up the currently active version
mkdir -p "${TARGET}"
if [ -d "${TARGET}/active" ]; then
  /bin/rm -rf -- "${TARGET}/previous"  # gate-allow: owner rollback slot
  mkdir -p "${TARGET}/previous"
  cp -R "${TARGET}/active" "${TARGET}/previous/active"
  if [ -f "${TARGET}/active.json" ]; then
    cp "${TARGET}/active.json" "${TARGET}/previous/active.json"
  fi
  printf 'guard-install: previous version kept in %s/previous\n' "${TARGET}"
fi

rollback() {
  if [ -d "${TARGET}/previous/active" ]; then
    /bin/rm -rf -- "${TARGET}/active"  # gate-allow: rollback
    cp -R "${TARGET}/previous/active" "${TARGET}/active"
    if [ -f "${TARGET}/previous/active.json" ]; then
      cp "${TARGET}/previous/active.json" "${TARGET}/active.json"
    fi
    printf 'guard-install: rolled back to the previous version\n' >&2
  fi
}

# 5. install atomically
/bin/rm -rf -- "${TARGET}/active.new"  # gate-allow: staging slot
cp -R "${STAGE}/build/active" "${TARGET}/active.new"
cp "${SOURCE}/tools/guardpkg/bootstrap.py" "${TARGET}/bootstrap.py"
sed -e "s#@@GUARD_ROOT@@#${TARGET}#g" -e "s#@@GUARD_PYTHON@@#${GUARD_PYTHON}#g" \
  "${SOURCE}/tools/guardpkg/bootstrap.sh" > "${TARGET}/bootstrap.sh"

if [ -d "${TARGET}/active" ]; then
  /bin/rm -rf -- "${TARGET}/active.old"  # gate-allow: swap slot
  mv "${TARGET}/active" "${TARGET}/active.old"
fi
mv "${TARGET}/active.new" "${TARGET}/active"
/bin/rm -rf -- "${TARGET}/active.old"  # gate-allow: swap slot

cat > "${TARGET}/active.json" <<POLICY_EOF
{
  "activated_at": "${ACTIVATED_AT}",
  "config_schema": "${CONFIG_SCHEMA}",
  "guard_version": "${GUARD_VERSION}",
  "install_target": "${TARGET}",
  "interpreter": "${GUARD_PYTHON}",
  "package_sha256": "${BUILT_HASH}",
  "schema_version": "guard-active-1",
  "source_commit": "${COMMIT}"
}
POLICY_EOF

chown -R root:wheel "${TARGET}"
chmod 0755 "${TARGET}"
chmod 0755 "${TARGET}/bootstrap.sh"
chmod 0644 "${TARGET}/bootstrap.py"
chmod 0444 "${TARGET}/active.json"
chmod -R a-w "${TARGET}/active"
find "${TARGET}/active" -type d -exec chmod 0755 {} +
find "${TARGET}/active" -type f -exec chmod 0444 {} +

# 6. protected runtime area
mkdir -p "${TARGET}/var/exceptions/pending" "${TARGET}/var/exceptions/spent"
touch "${TARGET}/var/guard.log"
chown -R root:wheel "${TARGET}/var"
chmod 0755 "${TARGET}/var" "${TARGET}/var/exceptions"
chmod 0755 "${TARGET}/var/exceptions/pending"
chmod 01733 "${TARGET}/var/exceptions/spent"
chmod 0644 "${TARGET}/var/guard.log"

chmod -N "${TARGET}/var/exceptions/spent" 2>/dev/null || true
chmod -N "${TARGET}/var/guard.log" 2>/dev/null || true
chmod +a "user:${SESSION_USER} deny delete_child,delete,writesecurity,chown" \
  "${TARGET}/var/exceptions/spent"
chmod +a "user:${SESSION_USER} allow add_file,search,readattr" \
  "${TARGET}/var/exceptions/spent"
chmod +a "user:${SESSION_USER} deny write,delete,writeattr,writeextattr,writesecurity,chown" \
  "${TARGET}/var/guard.log"
chmod +a "user:${SESSION_USER} allow append,read,readattr" "${TARGET}/var/guard.log"

# 7. protected hook registration
mkdir -p "${POLICY_DIR}"
chown root:wheel "${POLICY_DIR}"
chmod 0755 "${POLICY_DIR}"
if [ -f "${POLICY_FILE}" ]; then
  if ! grep -q -F "${TARGET}/bootstrap.sh" "${POLICY_FILE}"; then
    rollback
    die "existing managed settings do not register ${TARGET}/bootstrap.sh — refusing to overwrite. Add the PreToolUse hook manually and re-run."
  fi
  printf 'guard-install: existing hook registration validated\n'
else
  cat > "${POLICY_FILE}" <<HOOK_EOF
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "${TARGET}/bootstrap.sh",
            "timeout": 20
          }
        ]
      }
    ]
  }
}
HOOK_EOF
  printf 'guard-install: hook registration created\n'
fi
chown root:wheel "${POLICY_FILE}"
chmod 0644 "${POLICY_FILE}"

# 8. re-verify
VERIFY_HASH="$("${GUARD_PYTHON}" -I -B -c \
  'import sys;sys.path.insert(0,sys.argv[1]);import bootstrap;print(bootstrap.package_digest(sys.argv[2]))' \
  "${TARGET}" "${TARGET}/active")"
[ "${VERIFY_HASH}" = "${EXPECT_HASH}" ] || { rollback; die "post install hash mismatch"; }

[ "$(stat -f '%u' "${TARGET}/active.json")" = "0" ] || { rollback; die "active.json not root owned"; }
[ "$(stat -f '%u' "${TARGET}/bootstrap.sh")" = "0" ] || { rollback; die "bootstrap.sh not root owned"; }
[ "$(stat -f '%u' "${POLICY_FILE}")" = "0" ] || { rollback; die "hook registration not root owned"; }

# ACL behaviour, checked as the guarded session user
sudo -u "${SESSION_USER}" /bin/bash -c \
  'printf "" >> "$1"' _ "${TARGET}/var/guard.log" \
  || { rollback; die "session user cannot append to the protected log"; }
if sudo -u "${SESSION_USER}" /bin/bash -c \
  ': > "$1"' _ "${TARGET}/var/guard.log" 2>/dev/null; then
  rollback
  die "session user can truncate the protected log — ACL not effective"
fi
sudo -u "${SESSION_USER}" /bin/bash -c \
  'touch "$1/acl-probe"' _ "${TARGET}/var/exceptions/spent" \
  || { rollback; die "session user cannot claim an exception marker"; }
if sudo -u "${SESSION_USER}" /bin/bash -c \
  'unlink "$1/acl-probe"' _ "${TARGET}/var/exceptions/spent" 2>/dev/null; then
  rollback
  die "session user can remove an exception marker — ACL not effective"
fi
/bin/rm -f -- "${TARGET}/var/exceptions/spent/acl-probe"
if sudo -u "${SESSION_USER}" /bin/bash -c \
  'printf "x" > "$1/probe"' _ "${TARGET}" 2>/dev/null; then
  /bin/rm -f -- "${TARGET}/probe"
  rollback
  die "session user can write into the installation root"
fi

# 9. protected activation log
ACTIVATION_LOG="${TARGET}/var/activation.log"
touch "${ACTIVATION_LOG}"
chown root:wheel "${ACTIVATION_LOG}"
chmod 0600 "${ACTIVATION_LOG}"
printf '%s guard_version=%s source_commit=%s package_sha256=%s target=%s\n' \
  "${ACTIVATED_AT}" "${GUARD_VERSION}" "${COMMIT}" "${BUILT_HASH}" "${TARGET}" \
  >> "${ACTIVATION_LOG}"

printf 'guard-install: activated guard %s from %s\n' "${GUARD_VERSION}" "${COMMIT}"
printf 'guard-install: package_sha256 %s\n' "${BUILT_HASH}"
printf 'guard-install: hook registration %s\n' "${POLICY_FILE}"
printf 'guard-install: restart Claude Code so the policy hook is picked up\n'
exit 0
