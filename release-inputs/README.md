# vamanOS for R36S PS202 — private release inputs

Made by Nayam Amarshe.

This directory is intentionally ignored by Git. It holds legally obtained,
checksum-pinned runtime inputs that the installer re-distributes but which
must be assembled per user (they are third-party / device-owned binaries).

## Contents

- `bin/su` — the live `/system/xbin/su` fetched from the reference device
  (SHA-256 `48bdf38d…`). Used for step 3 of the install.
- `apks/ppsspp.apk` — the stock `org.ppsspp.ppsspp` APK (from the reference
  vendor partition, SHA-256 `7966aa71…`). Its `manifest.json` source is this
  release-input path.
- `cores-api19/` — the ARMv7/API-19-compatible cores staged for the
  RetroArch launch map. These are extracted from the pinned factory
  `GameCenter_Launcher.apk` backup; the newer buildbot cores in `cores/` are
  not usable on this Android 4.4.2 device because they import libc symbols
  introduced after API 19. TGB Dual supplies both GB and GBC, while gpSP
  supplies GBA.
- `cores/` — optional newer/reference cores. Keep them available for
  comparison, but do not put them ahead of `cores-api19/` in the manifest.
- `themes/EPIC-CODY.zip` — the pinned V2 format-7 CODY theme archive staged by
  the installer at `/storage/sdcard1/ps202/themes/EPIC-CODY.zip`.
- `touchbridge/cowtest`, `touchbridge/runas-blockdump`, and
  `touchbridge/run-as-original` — optional private inputs for the temp-root
  bootstrap on a virgin, non-root factory unit. Pinned default copies now ship
  in `../payload/bin/`; these files can override them only when their hashes
  match the manifest.

Per-file SHA-256 is already pinned in `../manifest.json`; the installer
verifies every artifact before use and aborts on a mismatch.

## Obtaining the inputs

- **live `su`**: `adb pull /system/xbin/su` from a root-ADB reference device.
- **cores**: extract the API-19 set from the preserved factory APK, or pull
  the already verified files from a root-ADB reference device. Do not use the
  current buildbot files in `tools/cores-x` for PS202 runtime deployment;
  several import symbols that they require are absent from Android 4.4.2.
- **touchbridge**: the exact default binaries are available from the nested
  `tools/touchbridge` Git checkout and are copied into `../payload/bin/` for
  distribution. If rebuilding or replacing them, use only the matching
  ARMv7/API-19 artifacts and verify the manifest hashes.

Do not put ROMs, saves, states, credentials, device backups, or diagnostic
captures in this directory.
