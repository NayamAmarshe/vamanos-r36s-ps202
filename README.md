# vamanOS

Made by **Nayam Amarshe**.

![vamanOS boot screen](assets/vamanos_boot.webp)

vamanOS is a simple game system for the R36S PS202. It gives the handheld a
clean game menu, opens games with RetroArch or PPSSPP, and keeps your games,
saves, and controller settings in place.

## Which device is this for?

This installer is for the **R36S PS202**, also called **PS202** or **TICHIPS**.

The supported device shows:

- Model: `PS202`
- Build: `PS202_00001`
- Android: `4.4.2`
- Screen: landscape `640 × 480`

The installer checks the device before it starts. It is not for other R36S
models or other handhelds.

This guide is for beginners. It shows how to install vamanOS on an **R36S
PS202** handheld.

## Before you start

1. Make a copy of your games, saves, and save states.
2. Read [ADB and USB debugging setup](ADB-SETUP.md).
3. Download the vamanOS ZIP from the project's GitHub Releases page.
4. Unzip it into a folder.
5. Connect the handheld with a USB data cable. Keep it connected during the
   install.

The installer is only for the R36S PS202. Do not use it on another handheld.

## Install vamanOS

Open a terminal or command window inside the unzipped vamanOS folder.

### macOS or Linux

Run:

```bash
./install.sh doctor
./install.sh install --boot-mode temproot
./install.sh verify
```

### Windows PowerShell

Run:

```powershell
.\install.ps1 doctor
.\install.ps1 install --boot-mode temproot
.\install.ps1 verify
```

### Windows Command Prompt

Run:

```bat
install.cmd doctor
install.cmd install --boot-mode temproot
install.cmd verify
```

The installer will show a code that starts with `INSTALL-`.

Type that exact code and press Enter. This is the final “yes” before the
install starts. If you type anything else, the installer stops.

The install can take a few minutes. Do not unplug the handheld until it says
the install is finished.

## What you get

vamanOS adds:

- A game menu
- RetroArch and the PS202's PPSSPP app
- Game cores and the CODY theme
- Root ADB and the small tools vamanOS needs
- Faster startup and game loading

The installer keeps the PPSSPP app already on the handheld. It installs the
bundled PPSSPP only when PPSSPP is missing.

Your games, saves, screenshots, and controller settings are kept.

## If the installer stops

Read the message on the screen first. Then run:

```bash
./install.sh doctor
```

On Windows, use `install.ps1 doctor` or `install.cmd doctor` instead.

If the handheld is stuck on its startup screen, run:

```bash
./recover-bootloop.sh doctor
```

Do not unplug the handheld while the installer is working.

## Need help?

See [ADB and USB debugging setup](ADB-SETUP.md) if the computer cannot see the
handheld.
