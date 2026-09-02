#!/usr/bin/env bash
# vamanOS for R36S PS202 — reversible boot-loop recovery
#
# Purpose
#   Bring a PS202 that is stuck boot-looping after a root-side change (most
#   often a boot animation install, a leftover root tool script, or a
#   keylayout modification) back to Android so normal admin can continue.
#
# Design rules (mirrors tools/ps202-installer/AGENTS.md):
#   - The boot animation and the boot helper are documented system changes.
#     This script only reverts *userspace /system* and app-file changes; it
#     never writes the raw boot region, preloader, lk, nvram, or recovery.
#   - Nothing mutates the device without an explicit recovery confirmation
#     token, exactly like the installer.
#   - Every destructive step takes a timestamped pull-back snapshot under
#     ./recovery-snapshots/ before touching the device.
#   - Evidence is logged to ./recovery.log; a failure leaves logs that the
#     project can use, it never "fixes forward" silently.
#
# Usage
#   ./recover-bootloop.sh doctor                 # read-only assessment
#   ./recover-bootloop.sh recover               # guided, asks for confirmation
#   ./recover-bootloop.sh recover --confirm REC-<last8>
#
# What `recover` reverts (in order):
#   1. /system/media/bootanimation.zip    -> .vamanos-previous if present
#   2. leftover root tool scripts in      /storage/sdcard1/ps202/tools/
#   3. mtk-kpd.kl FN remap                restores key 316 -> BTN_MODE when it was changed
#
# It does NOT: dump/factory-reset user data, delete ROMs/saves/states/input
# maps, flash any boot region, or reinstall the whole vamanOS image.

set -uo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 2

ADB="${ADB:-adb}"
SERIAL="${SERIAL:-}"
RUN_DIR="$(pwd)/recovery-run-$(date +%Y%m%d-%H%M%S)"
SNAPDIR="$RUN_DIR/snapshots"
LOG="$RUN_DIR/recovery.log"
mkdir -p "$SNAPDIR"

# ---------------------------- helpers -------------------------------------- #
log()  { printf '%s  %s\n' "$(date +%T)" "$*" | tee -a "$LOG"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

adb()  {
  if [ -n "$SERIAL" ]; then "$ADB" -s "$SERIAL" "$@"; else "$ADB" "$@"; fi
}
adb_device_state() { adb get-state 2>/dev/null; }

get_serial() {
  # prefer explicit SERIAL; else take the first non-unauthorized/offline device
  if [ -n "$SERIAL" ]; then echo "$SERIAL"; return; fi
  local line
  adb devices 2>/dev/null | tail -n +2 | awk '$2=="device"{print $1; exit}'
}

confirm_or_exit() {
  # $1 expected token; $2 optional pre-supplied token (may be empty -> interactive)
  local expected="$1" given="${2:-}"
  if [ -n "$given" ]; then
    [ "$given" == "$expected" ] && return 0
    die "confirmation token mismatch (expected $expected)"
  fi
  printf 'Type %s to confirm (or Ctrl-C to abort): ' "$expected" >&2
  read -r ans
  [ "$ans" == "$expected" ] || die "aborted (token mismatch)"
}

# ---------------------------- shell abstractions --------------------------- #
txt()     { adb shell "$1" 2>/dev/null | tr -d '\r'; }     # trimmed text

# ---------------------------- doctor --------------------------------------- #
doctor() {
  log "=== doctor: read-only assessment ==="
  local state; state="$(adb_device_state)"
  log "adb state: ${state:-unreachable}"

  if [ "$state" != "device" ]; then
    log "Device is NOT in 'device' adb state (showing '${state}')."
    log "  - If it shows 'unauthorized': unlock the phone or tap the RSA"
    log "    allow prompt on the device, or run 'adb kill-server' then retry."
    log "  - If no device: hold Vol+ while booting to enter recovery adb."
    log "  Boot-loop recovery can be attempted from Android adb or from recovery adb."
    return 0
  fi

  txt "id" | grep -q '^uid=0' && local_root=yes || local_root=no
  log "root adb (uid=0): $local_root"
  if [ "$local_root" = no ]; then
    log "  WARNING: not root. 'recover' needs root to rewrite /system."
    log "  adb root may be enough (shell) but /system writes typically need root."
  fi

  # boot animation
  local d
  d="$(txt 'ls -l /system/media/bootanimation.zip')"
  log "bootanimation.zip:"; log "$d"
  local prev; prev="$(txt 'ls -l /system/media/bootanimation.zip.vamanos-previous')"
  log "previous backup:"; [ -n "$prev" ] && log "$prev" || log "  (none)"
  local desc; desc="$(txt 'unzip -p /system/media/bootanimation.zip desc.txt')"
  log "desc.txt: ${desc:-unreadable}"

  # leftover tool scripts / power mailbox
  log "tool scripts under /storage/sdcard1/ps202/tools: (if any)"
  txt 'ls -la /storage/sdcard1/ps202/tools 2>/dev/null' | log_stdin
  log "ES power mailbox present:         $(txt 'test -f /data/data/com.ps202.emulationstation/files/ps202-power.request && echo yes || echo no')"

  # keylayout
  log "mtk-kpd.kl key 316 line (should end in BTN_MODE on stock):"
  txt "grep 'key 316' /system/usr/keylayout/mtk-kpd.kl 2>/dev/null" | log_stdin
  log "=== doctor: done ==="
}

log_stdin() { while IFS= read -r l; do log "    $l"; done; }

# ---------------------------- recover -------------------------------------- #
snap_file() {
  # snapshot a remote file into $SNAPDIR/<local name> for audit
  local remote="$1" localname="$2"
  adb pull "$remote" "$SNAPDIR/$localname" >/dev/null 2>&1 \
    && log "  snapshot saved: $SNAPDIR/$localname" \
    || log "  (no snapshot for $remote — clean/pull-only)"
}

recover() {
  log "=== recover ==="
  local state; state="$(adb_device_state)"
  [ "$state" == "device" ] || die "device not in 'device' adb state (got '${state}'). Boot-loop recovery needs Android- or recovery-adb first."
  txt "id" | grep -q '^uid=0' || die "recover requires root adb (uid=0). Run doctor first and resolve root access."

  local serial; serial="$(get_serial)"
  [ -n "$serial" ] || die "could not resolve device serial"
  local token="REC-${serial: -8}"

  # optional --confirm TOKEN   (or --confirm=TOKEN) before the case below
  local given="" rest=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --confirm=*) given="${1#*=}"; shift;;
      --confirm)   given="${2:-}"; shift 2;;
      *) rest+=("$1"); shift;;
    esac
  done

  confirm_or_exit "$token" "$given"
  log "confirmation OK ($token)"

  # --- 1. Revert boot animation -------------------------------------------------
  log "[1/4] Reverting boot animation"
  snap_file "/system/media/bootanimation.zip" "bootanimation.on-device.zip"
  if [ "$(txt 'test -f /system/media/bootanimation.zip.vamanos-previous && echo yes')" == "yes" ]; then
    adb shell "mount -o rw,remount /system 2>/dev/null; cp /system/media/bootanimation.zip /system/media/bootanimation.zip.dead-recovery 2>/dev/null; mv -f /system/media/bootanimation.zip.vamanos-previous /system/media/bootanimation.zip; chmod 0644 /system/media/bootanimation.zip; chown 0:0 /system/media/bootanimation.zip; sync" && \
      log "  restored previous Android boot animation (from .vamanos-previous)."
  else
    log "  no .vamanos-previous found. NOT removing the current file (a valid"
    log "  config is better than a missing one); confirm separately if you want"
    log "  the stock animation re-seeded."
  fi

  # --- 2. Dispose of leftover root tool scripts -------------------------------
  log "[2/4] Moving leftover root tool scripts to a recovery folder"
  if [ "$(txt 'test -d /storage/sdcard1/ps202/tools && echo yes')" == "yes" ]; then
    adb shell "mkdir -p /storage/sdcard1/ps202/tools/.recovered-$(date +%s); mv -f /storage/sdcard1/ps202/tools/*.sh /storage/sdcard1/ps202/tools/*.sh.txt /storage/sdcard1/ps202/tools/.recovered-$(date +%s)/ 2>/dev/null" \
      && log "  moved leftover .sh scripts into /storage/sdcard1/ps202/tools/.recovered-* (preserved, not deleted)."
  fi
  # --- 3. Restore mtk-kpd.kl FN remap --------------------------------------------
  log "[3/4] Restoring mtk-kpd.kl (FN -> BTN_MODE) if the helper changed it"
  snap_file "/system/usr/keylayout/mtk-kpd.kl" "mtk-kpd.kl.on-device"
  if [ "$(txt "grep -c 'key 316.*F1' /system/usr/keylayout/mtk-kpd.kl 2>/dev/null")" -gt 0 ]; then
    # Use grep/grep-append/cp (NOT sed -i): Android 4.4 toolbox sed lacks -i.
    adb shell "mount -o rw,remount /system 2>/dev/null; \
      grep -v 'key 316' /system/usr/keylayout/mtk-kpd.kl > /data/local/kl.recover; \
      echo 'key 316   BTN_MODE' >> /data/local/kl.recover; \
      cp /data/local/kl.recover /system/usr/keylayout/mtk-kpd.kl; \
      rm /data/local/kl.recover; chmod 0644 /system/usr/keylayout/mtk-kpd.kl; sync" \
      && log "  reverted key 316 to BTN_MODE in mtk-kpd.kl."
  else
    log "  key 316 not set to F1; leaving keylayout unchanged."
  fi

  # --- 4. Report ----------------------------------------------------------------
  log "[4/4] Recovery complete. Snapshot + log in $RUN_DIR"
  log "  The next cold boot should reach Android. If it still loops, the cause"
  log "  is outside these userspace files (e.g. a boot-region/init change):"
  log "  inspect ${RUN_DIR}/recovery.log and the .on-device snapshots. If Android"
  log "  can still boot with root ADB, use ./install.sh restore-boot for the"
  log "  reviewed stock image."
}

# ---------------------------- main ------------------------------------------ #
case "${1:-doctor}" in
  doctor) shift; doctor ;;
  recover|--recover) shift; recover "$@" ;;
  *) die "usage: $0 {doctor|recover [--confirm REC-<last8>]}" ;;
esac
