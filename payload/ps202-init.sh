#!/system/bin/sh
LOG=/data/local/tmp/ps202-init.log
echo "=== ps202-init $(date) ===" >> "$LOG"
mount -o rw,remount /system >> "$LOG" 2>&1
echo "remount rc=$?" >> "$LOG"
if [ -f /sbin/find ] && [ ! -f /system/xbin/find ]; then
  cp /sbin/find /system/xbin/find && chmod 0755 /system/xbin/find
  echo "find installed rc=$?" >> "$LOG"
fi
if [ -f /data/local/ps202-boot.sh ]; then
  echo "executing /data/local/ps202-boot.sh" >> "$LOG"
  sh /data/local/ps202-boot.sh >> "$LOG" 2>&1
  echo "ps202-boot.sh rc=$?" >> "$LOG"
fi
echo "=== ps202-init done ===" >> "$LOG"
exit 0
