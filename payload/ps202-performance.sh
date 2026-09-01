#!/system/bin/sh
# vamanOS PS202 init.d-style performance profile.
#
# Android 4.4 on this unit has no usable /system/etc/init.d hook, so the
# source-controlled boot helper calls this script from the rooted ps202init
# service. Every write is guarded, idempotent, logged, and reversible.
#
# Deliberately not touched here:
#   - CPU governor/frequency: the MTK cpufreq driver rejects userspace writes.
#   - I/O scheduler: the benefit is workload-dependent and unmeasured here.
#   - zram size, dirty ratios, and user files: changing them is riskier than
#     the small, measurable adjustments below.

LOG=/data/local/tmp/ps202-performance.log

log() {
  echo "$(date) $1" >> "$LOG"
}

save_node() {
  NODE=$1
  BACKUP=$2
  if [ -f "$NODE" ] && [ ! -f "$BACKUP" ]; then
    cat "$NODE" > "$BACKUP" 2>> "$LOG"
    log "saved $NODE -> $BACKUP"
  fi
}

tune_node() {
  NODE=$1
  TARGET=$2
  BACKUP=$3
  LABEL=$4
  if [ ! -f "$NODE" ]; then
    log "$LABEL: unavailable ($NODE)"
    return
  fi
  save_node "$NODE" "$BACKUP"
  OLD=$(cat "$NODE" 2>/dev/null)
  if echo "$TARGET" > "$NODE" 2>> "$LOG"; then
    NOW=$(cat "$NODE" 2>/dev/null)
    log "$LABEL: old=$OLD target=$TARGET now=$NOW"
  else
    log "$LABEL: write rejected (old=$OLD target=$TARGET)"
  fi
}

restore_node() {
  NODE=$1
  BACKUP=$2
  LABEL=$3
  if [ ! -f "$BACKUP" ]; then
    log "$LABEL: no saved value ($BACKUP)"
    return
  fi
  if [ ! -f "$NODE" ]; then
    log "$LABEL: unavailable ($NODE)"
    return
  fi
  VALUE=$(cat "$BACKUP" 2>/dev/null)
  if echo "$VALUE" > "$NODE" 2>> "$LOG"; then
    log "$LABEL: restored=$VALUE"
  else
    log "$LABEL: restore rejected (value=$VALUE)"
  fi
}

apply_profile() {
  # 100 is the stock value observed on this 481 MiB device. A moderate 60
  # lets the kernel prefer RAM while retaining zram as an emergency buffer.
  tune_node /proc/sys/vm/swappiness 60 \
    /data/local/ps202-performance.previous.swappiness swappiness

  # 128 KiB was observed on both storage devices. 256 KiB helps sequential
  # ROM/artwork reads without the latency and cache pressure of old 2-8 MiB
  # init.d recipes. mmcblk1 is the removable ROM/SD volume.
  tune_node /sys/block/mmcblk0/queue/read_ahead_kb 256 \
    /data/local/ps202-performance.previous.mmcblk0-read-ahead mmcblk0-read-ahead
  tune_node /sys/block/mmcblk1/queue/read_ahead_kb 256 \
    /data/local/ps202-performance.previous.mmcblk1-read-ahead mmcblk1-read-ahead

  log "profile apply complete (CPU governor/frequency unchanged)"
}

restore_profile() {
  restore_node /proc/sys/vm/swappiness \
    /data/local/ps202-performance.previous.swappiness swappiness
  restore_node /sys/block/mmcblk0/queue/read_ahead_kb \
    /data/local/ps202-performance.previous.mmcblk0-read-ahead mmcblk0-read-ahead
  restore_node /sys/block/mmcblk1/queue/read_ahead_kb \
    /data/local/ps202-performance.previous.mmcblk1-read-ahead mmcblk1-read-ahead
  log "profile restore complete"
}

mkdir -p /data/local/tmp
case "$1" in
  restore)
    restore_profile
    ;;
  apply|"")
    apply_profile
    ;;
  *)
    echo "usage: ps202-performance.sh [apply|restore]"
    exit 2
    ;;
esac
exit 0
