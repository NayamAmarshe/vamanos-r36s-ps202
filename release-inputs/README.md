# vamanOS for R36S PS202 — release inputs

Made by Nayam Amarshe.

This directory is part of the public installer. It holds checksum-pinned
runtime inputs used to assemble a release ZIP. The project owner has confirmed
that these files may be published with vamanOS. Keep the matching license and
copyright information with the release. The installer keeps an existing PS202
PPSSPP and uses this bundled copy only as a fallback when PPSSPP is missing.

## Contents

- `apks/emulationstation.apk` — the packaged Batocera V2 EmulationStation
  frontend used by vamanOS.
- RetroArch is downloaded during installation from the pinned official
  buildbot URL in `../manifest.json`. It is the tested `com.retroarch.ra32`
  RetroArch `1.20.0_GIT` APK for Android 4.4.2/API 19 (version code 11).
- `bin/su` — the live `/system/xbin/su` fetched from the reference device
  (SHA-256 `48bdf38d…`). Used for step 3 of the install.
- `bin/find` — the PS202 ARMv7 `find` binary installed at
  `/system/xbin/find`.
- `boot/v10_stock.img` + `boot/v10_patched.img` — the matching V10 boot pair.
- `boot/v11_v12_stock.img` + `boot/v11_v12_patched.img` — the matching V11/V12
  pair. V11 and V12 have the same boot image, so they share one pair.
  The installer compares the full boot-region checksum before using a pair. If
  a supported PS202 has a different boot image, it captures that image, saves
  it for rollback, and patches only its ramdisk instead.
- The V10 pair was prepared from the supplied V10 backup and padded to the
  PS202 boot partition size. It still needs a real V10 handheld boot test
  before a public release is advertised as V10-tested.
- A universal boot image and a loose pre-patched `adbd` are not used. The
  installer never sends a known pair to a device unless its exact image hash
  and kernel match.
- `apks/ppsspp.apk` — a fallback `org.ppsspp.ppsspp` APK (from the reference
  vendor partition, SHA-256 `7966aa71…`). It is installed only when the
  handheld does not already have PPSSPP. Its `manifest.json` source is this
  release-input path.
- `cores-api19/` — the ARMv7/API-19-compatible cores used for the main
  consoles. These are preferred whenever the same core exists in both folders.
  TGB Dual supplies both GB and GBC, while gpSP supplies GBA.
- `cores/` — the additional checked cores used for arcade, Atari, Master
  System, Game Gear, Neo Geo Pocket, PC Engine, ColecoVision, and WonderSwan.
  The installer copies every launcher core into RetroArch's private runtime
  directory, then checks its checksum.
- `themes/EPIC-CODY.zip` — the pinned V2 format-7 CODY theme archive staged by
  the installer at `/storage/sdcard1/ps202/themes/EPIC-CODY.zip`.
- `music/` — the 12 menu music tracks used by the frontend, copied to
  `/storage/sdcard1/music` when a track is missing.
- `touchbridge/cowtest`, `touchbridge/runas-blockdump`, and
  `touchbridge/run-as-original` — optional inputs for the temp-root
  bootstrap on a virgin, non-root factory unit. Pinned default copies now ship
  in `../payload/bin/`; these files can override them only when their hashes
  match the manifest.

Per-file SHA-256 is already pinned in `../manifest.json`; the installer
verifies every artifact before use and aborts on a mismatch.

## Obtaining the inputs

- **live `su`**: `adb pull /system/xbin/su` from a root-ADB reference device.
- **cores**: extract the API-19 set from the preserved factory APK, or pull
  the already verified files from a root-ADB reference device. The additional
  files in `cores/` must also be tested on the PS202 before their hashes are
  changed.
- **touchbridge**: the exact default binaries are available from the nested
  `tools/touchbridge` Git checkout and are copied into `../payload/bin/` for
  distribution. If rebuilding or replacing them, use only the matching
  ARMv7/API-19 artifacts and verify the manifest hashes.

Do not put ROMs, saves, states, credentials, device backups, or diagnostic
captures in this directory.
