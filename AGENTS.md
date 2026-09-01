# vamanOS installer instructions for AI agents

This file tells an AI agent how to help a user install vamanOS. It does not
mean “install now.” Install only when the user clearly asks for it.

## Install steps

1. Make sure the user has copied their games, saves, and save states somewhere
   safe.
2. Make sure the handheld is connected with a USB data cable and USB debugging
   is on. If ADB is not ready, show the user `ADB-SETUP.md`.
3. Run the read-only check:

   ```sh
   ./install.sh doctor
   ```

4. Continue only if the check identifies an R36S PS202 with build
   `PS202_00001`.
5. Run the normal installer. Let it choose the correct root method:

   ```sh
   ./install.sh install
   ```

6. When the installer shows its plan and an `INSTALL-...` code, show the code
   to the user and ask for a final yes. After the user agrees, enter that exact
   code. Never invent a code or skip this confirmation.
7. Keep the USB cable connected until the installer finishes.
8. Check the result:

   ```sh
   ./install.sh verify
   ```

On Windows, use `install.ps1` in PowerShell or `install.cmd` in Command Prompt
for the same steps.

## Important rules

- Do not install on another handheld or an unknown PS202 build.
- Do not run random flashing tools or write a full device image.
- Do not use `pm clear`, uninstall/reinstall to fix a settings problem, or
  reset the controller map.
- Do not delete the user's ROMs, saves, states, screenshots, or input maps.
- Keep the vendor emulator installed.
- If the installer stops, read the error and report it. Do not blindly retry.
- If the handheld is stuck during startup, run `./recover-bootloop.sh doctor`
  first. It is read-only.

## Installer files

- `vamanos_installer.py` is the installer engine.
- `manifest.json` lists the files and checksums.
- `device-profile.json` describes the supported PS202.
- `payload/` contains the installer files that are safe to ship.
- `tests/` contains host tests.
- `release-inputs/` contains private files used to build a release ZIP. Do not
  publish its contents.

If changing the installer, manifest, profile, or payload, run:

```sh
python3 -m unittest discover -s tests -v
```
