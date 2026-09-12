#!/system/bin/sh
# PS202 boot hook (runs with full caps via ps202init service)
LOG=/data/local/tmp/ps202-boot.log
echo "=== ps202-boot $(date) ===" >> "$LOG"

# wait for SD (max 60s)
i=0
while [ ! -d /storage/sdcard1/retroarch ] && [ $i -lt 30 ]; do
  sleep 2
  i=$((i+1))
done
echo "sdcard ready after ${i}x2s" >> "$LOG"

# --- init.d-style performance profile (guarded + reversible) -------------
# Stock PS202 has no usable /system/etc/init.d hook. Keep the profile as a
# separate source-controlled script so its writes can be audited and restored.
if [ -f /data/local/ps202-performance.sh ]; then
  echo "applying /data/local/ps202-performance.sh" >> "$LOG"
  sh /data/local/ps202-performance.sh apply >> "$LOG" 2>&1
  echo "performance profile rc=$?" >> "$LOG"
fi

# --- RetroArch setup (idempotent; never delete installed/user files) ---
# Both PS202 SD mounts are noexec. The installer keeps a user-facing source
# copy on SD and puts the runtime core copy in RetroArch's app-private cores
# directory using the ADB sync service. This boot hook deliberately does not
# try to copy/chown/chmod that 0700 app-owned directory: a root shell on this
# Android 4.4 build still lacks DAC override, while the ADB sync service can
# write the file there during installation. It also never deletes core files.
CFG=/storage/sdcard0/Android/data/com.retroarch.ra32/files/retroarch.cfg
if [ -d /storage/sdcard1/retroarch/cores ]; then
  mkdir -p /storage/sdcard0/Android/data/com.retroarch.ra32/files/saves \
    /storage/sdcard0/Android/data/com.retroarch.ra32/files/states
  if [ -f "$CFG" ]; then
    echo "retroarch.cfg exists — preserving (user remaps survive)" >> "$LOG"
  else
  mkdir -p /storage/sdcard0/Android/data/com.retroarch.ra32/files
  {
    echo 'libretro_directory = "/data/data/com.retroarch.ra32/cores/"'
    echo 'rgui_browser_directory = "/storage/sdcard1/roms/"'
    echo 'menu_driver = "ozone"'
    echo 'ozone_menu_color_theme = "10"'
    echo 'video_threaded = "true"'
    echo 'audio_driver = "opensl"'
    echo 'input_driver = "android"'
    echo 'input_volume_up = "volumeup"'
    echo 'input_volume_down = "volumedown"'
    echo 'input_autoconfigure_dir = "/storage/sdcard1/retroarch/autoconfig/"'
    echo 'content_show_history = "false"'
    echo 'video_vsync = "true"'
    echo 'savefile_directory = "/storage/sdcard0/Android/data/com.retroarch.ra32/files/saves"'
    echo 'savefiles_in_content_dir = "false"'
    echo 'sort_savefiles_enable = "false"'
    echo 'sort_savefiles_by_content_enable = "false"'
    echo 'savestate_directory = "/storage/sdcard0/Android/data/com.retroarch.ra32/files/states"'
    echo 'savestates_in_content_dir = "false"'
    echo 'sort_savestates_enable = "false"'
    echo 'sort_savestates_by_content_enable = "false"'
    echo 'screenshot_directory = "/storage/sdcard1/ps202/screenshots"'
    echo 'audio_latency = "96"'
    echo 'pcsx_rearmed_dynarec = "enabled"'
    echo 'pcsx_rearmed_neon = "enabled"'
    echo 'pcsx_rearmed_frameskip = "0"'
    echo 'pcsx_rearmed_internal_resolution = "1x"'
    echo 'pcsx_rearmed_region = "auto"'
    echo 'video_swap_interval = "1"'
  } > "$CFG"
  chmod 664 "$CFG"
  fi
  # Normalize the audio and save-path settings on upgrades. Android 4.4's
  # toolbox has no sed, awk, or printf, so use only portable shell
  # read/case/echo operations. This rewrites only these known vamanOS keys;
  # input bindings and all other user settings remain intact.
  needs_cfg_migration=0
  for kv in \
    'audio_driver = "opensl"' \
    'savefiles_in_content_dir = "false"' \
    'sort_savefiles_enable = "false"' \
    'sort_savefiles_by_content_enable = "false"' \
    'savestates_in_content_dir = "false"' \
    'sort_savestates_enable = "false"' \
    'sort_savestates_by_content_enable = "false"'; do
    k=${kv%% = *}
    expected=${kv#* = }
    if ! grep -q "^$k = $expected$" "$CFG" 2>/dev/null; then
      needs_cfg_migration=1
      break
    fi
  done
  if [ -f "$CFG" ] && [ "$needs_cfg_migration" = 1 ]; then
    CFG_TMP="${CFG}.vamanos.tmp"
    if : > "$CFG_TMP"; then
      copy_ok=1
      while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
          audio_driver\ =\ *) line='audio_driver = "opensl"' ;;
          savefiles_in_content_dir\ =\ *) line='savefiles_in_content_dir = "false"' ;;
          sort_savefiles_enable\ =\ *) line='sort_savefiles_enable = "false"' ;;
          sort_savefiles_by_content_enable\ =\ *) line='sort_savefiles_by_content_enable = "false"' ;;
          savestates_in_content_dir\ =\ *) line='savestates_in_content_dir = "false"' ;;
          sort_savestates_enable\ =\ *) line='sort_savestates_enable = "false"' ;;
          sort_savestates_by_content_enable\ =\ *) line='sort_savestates_by_content_enable = "false"' ;;
        esac
        if ! echo "$line" >> "$CFG_TMP"; then
          copy_ok=0
          break
        fi
      done < "$CFG"
      if [ "$copy_ok" = 1 ]; then
        for kv in \
          'audio_driver = "opensl"' \
          'savefiles_in_content_dir = "false"' \
          'sort_savefiles_enable = "false"' \
          'sort_savefiles_by_content_enable = "false"' \
          'savestates_in_content_dir = "false"' \
          'sort_savestates_enable = "false"' \
          'sort_savestates_by_content_enable = "false"'; do
          k=${kv%% = *}
          if ! grep -q "^$k = " "$CFG_TMP" 2>/dev/null; then
            if ! echo "$kv" >> "$CFG_TMP"; then
              copy_ok=0
              break
            fi
          fi
        done
      fi
      if [ "$copy_ok" = 1 ] && cp -f "$CFG_TMP" "$CFG"; then
        rm -f "$CFG_TMP"
        echo "retroarch config normalized (audio + save paths)" >> "$LOG"
      else
        echo "WARNING: could not normalize RetroArch config" >> "$LOG"
        rm -f "$CFG_TMP"
      fi
    else
      echo "WARNING: could not create RetroArch config temp file" >> "$LOG"
    fi
  fi
  mkdir -p /data/local/ra-snapshot
  echo "sdcard0 retroarch.cfg preserved + migrated" >> "$LOG"
  echo "retroarch cores: SD source preserved; private runtime copy is installer-managed" >> "$LOG"
fi

# --- PPSSPP conservative tuning (first-run defaults; preserve user settings) ---
mkdir -p /storage/sdcard1/PSP/SAVEDATA /storage/sdcard1/PSP/PPSSPP/STATE
if [ ! -f /storage/sdcard1/PSP/ppsspp.ini ]; then
  {
    echo '[Graphics]'
    echo 'RenderResolution = 1'
    echo 'BufferedRendering = True'
    echo 'HardwareTransform = True'
    echo 'SoftwareSkinning = False'
    echo 'LazyTextureCaching = True'
    echo 'Frameskip = 0'
    echo 'SplineBezierQuality = 0'
    echo 'VSyncInterval = 1'
  } > /storage/sdcard1/PSP/ppsspp.ini 2>> "$LOG"
  echo "ppsspp defaults written" >> "$LOG"
else
  echo "ppsspp.ini exists — preserving user settings" >> "$LOG"
fi
if [ -d /data/data/org.ppsspp.ppsspp ]; then
  mkdir -p /data/data/org.ppsspp.ppsspp/files/PSP/SAVEDATA /data/data/org.ppsspp.ppsspp/files/PSP/PPSSPP/STATE
  if [ ! -f /data/data/org.ppsspp.ppsspp/files/PSP/ppsspp.ini ] \
      && [ -f /storage/sdcard1/PSP/ppsspp.ini ]; then
    cp -f /storage/sdcard1/PSP/ppsspp.ini /data/data/org.ppsspp.ppsspp/files/PSP/ppsspp.ini 2>> "$LOG"
    echo "ppsspp private defaults copied" >> "$LOG"
  else
    echo "ppsspp private settings preserved" >> "$LOG"
  fi
fi
echo "ppsspp setup complete" >> "$LOG"

# --- microSD ps202 layout (idempotent; never delete user files) ---
if [ -d /storage/sdcard1 ]; then
  for d in \
    ps202/bios roms/COLECOVISION roms/CPS1 roms/CPS2 roms/CPS3 roms/SMS \
    roms/arcade roms/atari2600 roms/atarilynx roms/gamegear roms/gb \
    roms/gba roms/gbc roms/genesis roms/megadrive roms/mame roms/ngpc \
    roms/nes roms/pcengine roms/psp roms/psx roms/snes roms/wonder \
    ps202/saves ps202/states ps202/screenshots ps202/themes \
    Android/data/com.ps202.nayamamarshe.emulationstation/files/themes \
    ps202/media/images ps202/media/videos ps202/configs ps202/logs \
    ps202/cache ps202/cache/roms; do
    mkdir -p "/storage/sdcard1/$d"
  done
  # The app writes the diagnostic log and ZIP extraction cache here. Keep
  # the rest of the appliance tree under its existing private permissions.
  chmod 777 /storage/sdcard1/ps202/logs \
    /storage/sdcard1/ps202/cache /storage/sdcard1/ps202/cache/roms 2>> "$LOG"
  echo "ps202 layout ensured" >> "$LOG"
else
  echo "SDCARD MISSING at boot" >> "$LOG"
fi

# --- /data usage report (internal storage is tight) ---
{
  echo '=== /data usage ==='
  du -sm /data/app /data/dalvik-cache 2>/dev/null
  ls -S /data/dalvik-cache 2>/dev/null | head -3
} > /data/local/data-usage.txt 2>&1
# --- ES power mailbox (fixed actions only) ---
(
  ESPRIV=/data/data/com.ps202.nayamamarshe.emulationstation/files
  ESCMD=$ESPRIV/ps202-power.request
  while true; do
    if [ -f "$ESCMD" ]; then
      C=$(cat "$ESCMD" 2>/dev/null)
      rm -f "$ESCMD"
      echo "es power request: $C" >> "$LOG"
      case "$C" in
        reboot) reboot ;;
        poweroff) reboot -p ;;
        *) echo "rejected es power request" >> "$LOG" ;;
      esac
    fi
    sleep 2
  done
) &

# --- preserve the stock mtk-kpd keylayout -------------------------------
# FN/MODE remains Android's stock BTN_MODE (scancode 316); vamanOS does not
# assign it to ES navigation or rewrite the controller keylayout.
# Never rewrite /system/usr/keylayout/mtk-kpd.kl here: Android loads the
# stock D-pad/ABXY mappings from that file, and a failed filtered copy can
# leave it empty and break every physical control.
echo "=== ps202-boot done (ES power mailbox only) ===" >> "$LOG"
# Keep the init service alive so the fixed power mailbox watcher survives.
while true; do sleep 60; done
exit 0
