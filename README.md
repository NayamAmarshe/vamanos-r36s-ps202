# vamanOS

Made by **Nayam Amarshe**.

![vamanOS boot screen](assets/vamanos_boot.webp)

<video autoplay loop muted playsinline>
  <source src="video.mp4" type="video/mp4">
</video>

vamanOS is a simple firmware update for the R36S PS202 devices. These are
unofficial R36S clones with Android 4.4, Wi-Fi, and Bluetooth. Their factory
software is limited, so vamanOS gives them a clean game menu, better game
launching, RetroArch, PPSSPP, a CODY theme, performance settings, and the
original handheld menu music.

This installer is for the **R36S PS202**, also called **PS202** or **TICHIPS**.
If this looks like your device, you’re good to go:

- Model: `PS202`
- Build: `PS202_00001`
- Android: `4.4.2`
- Processor: MediaTek `MT6572`
- Screen: landscape `640 × 480`
- Wireless: Wi-Fi and Bluetooth

The installer checks the device before it starts. Do not use it on another
handheld.

## Before you start

1. Copy your games, saves, and save states somewhere safe.
2. Install **Python 3** from [python.org](https://www.python.org/downloads/).
3. Follow [ADB and USB debugging setup](ADB-SETUP.md).
4. Download the vamanOS ZIP from GitHub Releases and unzip it.
5. Connect the handheld with a USB data cable.
6. Keep the computer online so the installer can download the tested
   RetroArch version.

## Install

Open a terminal or command window inside the unzipped vamanOS folder.

### macOS or Linux

```bash
./install.sh doctor
./install.sh install
./install.sh verify
```

### Windows PowerShell

```powershell
.\install.ps1 doctor
.\install.ps1 install
.\install.ps1 verify
```

### Windows Command Prompt

```bat
install.cmd doctor
install.cmd install
install.cmd verify
```

The installer will show a code beginning with `INSTALL-`. Type that exact code
and press Enter. This is the final yes before installation begins.

Keep the cable connected until the installer says it is finished. The
handheld reboots at the end to start vamanOS correctly.

## Put games on the SD card

Put games in the matching folder on the SD card:

| System                             | Folder                                                               |
| ---------------------------------- | -------------------------------------------------------------------- |
| NES                                | `roms/nes`                                                           |
| SNES                               | `roms/snes`                                                          |
| Genesis / Mega Drive               | `roms/genesis` or `roms/megadrive`                                   |
| Game Boy / Color / Advance         | `roms/gb`, `roms/gbc`, or `roms/gba`                                 |
| PlayStation                        | `roms/psx`                                                           |
| PSP                                | `roms/psp`                                                           |
| Arcade / CPS1 / CPS2 / CPS3 / MAME | `roms/arcade`, `roms/CPS1`, `roms/CPS2`, `roms/CPS3`, or `roms/mame` |
| Master System / Game Gear          | `roms/SMS` or `roms/gamegear`                                        |
| Atari 2600 / Lynx                  | `roms/atari2600` or `roms/atarilynx`                                 |
| Neo Geo Pocket                     | `roms/ngpc`                                                          |
| PC Engine                          | `roms/pcengine`                                                      |
| ColecoVision                       | `roms/COLECOVISION`                                                  |
| WonderSwan                         | `roms/wonder`                                                        |

The full path is `/storage/sdcard1/roms/...`. BIOS files go in
`/storage/sdcard1/ps202/bios`.

## What vamanOS keeps

The installer keeps your ROMs, saves, screenshots, controller map, and
RetroArch settings. It keeps the factory emulator because it is useful for
the handheld’s layout. It keeps an existing PPSSPP app and only installs the
included PPSSPP when PPSSPP is missing.

Old launchers and unused apps are backed up to
`/storage/sdcard1/ps202/backups/apps` before they are removed. PS202 Shell is
not installed. They are removed at the end, after the new game menu is ready,
so the handheld is never left without a HOME app.

RetroArch 1.20.0 is downloaded from its pinned official build during setup.

## If something goes wrong

Run the read-only check again:

```bash
./install.sh doctor
```

If the handheld still boots into Android but you want the original boot image
back:

macOS or Linux:

```bash
./install.sh restore-boot
```

Windows PowerShell:

```powershell
.\install.ps1 restore-boot
```

Windows Command Prompt:

```bat
install.cmd restore-boot
```

This asks for a separate `RESTORE-...` confirmation code. Stock boot removes
root ADB, as expected.

If the handheld is stuck during startup, run this on macOS or Linux:

```bash
./recover-bootloop.sh doctor
```

Do not unplug the handheld while an installer or restore command is running.

For connection problems, see [ADB and USB debugging setup](ADB-SETUP.md).

See [CREDITS.md](CREDITS.md) for included software and music information.
