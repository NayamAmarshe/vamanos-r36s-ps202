#!/usr/bin/env python3
"""vamanOS for R36S PS202 — cross-platform installer.

Transforms a factory PS202 handheld into the vamanOS appliance by replaying
the exact verified-state of the reference device: patched-root boot, Android
boot animation, /system/xbin/su, boot helper, EmulationStation, RetroArch,
PPSSPP, the tuned RetroArch config, launcher map, cores, and the safe debloat
list.

Design rules (from docs/PS202-OPERATIONS.md):
  - Only the boot region (0x1D80000, 6 MiB) is written in raw flash, and only
    for the reviewed root-ADB boot patch. It is read back and SHA-256 verified
    before reboot. The splash is installed in Android at
    /system/media/bootanimation.zip, never in a raw flash region.
  - Preloader / lk / nvram / secro / protect_* / whole flash are never touched.
  - Factory units boot unrooted: use the dirtycow temp-root path first to
    write the patched boot once, then reboot to root ADB.
  - User data (ROMs, saves, states, input maps) is never cleared or erased.
  - protected packages are never disabled/removed; no 'pm clear' is used.
  - Only the Python standard library is used; a single engine drives the
    bash/PowerShell/CMD launchers.

Usage (run from this directory):
  python3 vamanos_installer.py doctor                 # read-only health check
  python3 vamanos_installer.py splash                 # Android bootanimation only
  python3 vamanos_installer.py install --boot-mode temproot  # factory unit (dirtycow)
  python3 vamanos_installer.py install                # already-rooted unit
  python3 vamanos_installer.py assemble               # build dist zip
  python3 vamanos_installer.py verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

INSTALLER_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = INSTALLER_DIR.parents[1]
DEFAULT_MANIFEST = INSTALLER_DIR / "manifest.json"
DEFAULT_PROFILE = INSTALLER_DIR / "device-profile.json"
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")
CONFIRM_RE = re.compile(r"^[a-zA-Z0-9]{4,40}$")

# The ES Java bridge auto-derives CONFIGFILE/SDCARD/EXTERNAL/DATADIR/APK for
# RetroArch (see EmulationStationActivity.buildIntent), so we only rely on the
# launcher XML for ROM + LIBRETRO + the PSP shortcut.
RADIR_SD = "/storage/sdcard1/retroarch/cores"
RADIR_PRIVATE = "/data/data/com.retroarch.ra32/cores"
PPSSPP_PACKAGE = "org.ppsspp.ppsspp"


class InstallerError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise InstallerError(f"cannot read JSON {path}: {exc}")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)


def resolve_path(value: str, base: Path = INSTALLER_DIR) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def align_up(value: int, page: int) -> int:
    return (value + page - 1) // page * page


def parse_cfg(text: str) -> Dict[str, str]:
    """Parse a simple RetroArch-style 'key = "value"' config. No interpolation."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


PERSONAL_KEYS = {
    "input_player1_", "input_player2_", "input_libretro_device_", "input_enable_hotkey",
}

# Stock RetroArch 1.20 creates these keys as unbound on PS202 even though the
# mtk-kpd Android device is present. They are defaults for an entirely
# unconfigured PS202 only; an existing user's non-empty D-pad map wins.
PS202_INPUT_DEFAULTS = {
    "input_player1_analog_dpad_mode": '"1"',
    "input_player1_up_btn": '"19"',
    "input_player1_down_btn": '"20"',
    "input_player1_left_btn": '"21"',
    "input_player1_right_btn": '"22"',
    "input_enable_hotkey_btn": '"110"',
    "input_menu_toggle_btn": '"110"',
    "input_quit_gamepad_combo": '"4"',
}


def is_personal_input_key(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in PERSONAL_KEYS)


def merge_cfg(existing: str, overlay: str, preserve_personal: bool = True) -> str:
    """Merge overlay into existing, preserving user input bindings."""
    current = parse_cfg(existing)
    incoming = parse_cfg(overlay)
    lines = [line for line in existing.splitlines() if line.strip()]
    present_keys = set()
    for key in current:
        present_keys.add(key)
    for key, value in incoming.items():
        if preserve_personal and is_personal_input_key(key):
            continue
        if key in present_keys:
            for i, line in enumerate(lines):
                if line.strip() and line.strip().split("=", 1)[0].strip() == key:
                    lines[i] = f"{key} = {value}"
                    break
        else:
            lines.append(f"{key} = {value}")
            present_keys.add(key)
    return "\n".join(lines).rstrip() + "\n"


def apply_ps202_input_defaults(existing: str, merged: str) -> str:
    """Seed the stock PS202 pad only when all four D-pad buttons are unset."""
    current = parse_cfg(existing)
    dpad_keys = (
        "input_player1_up_btn", "input_player1_down_btn",
        "input_player1_left_btn", "input_player1_right_btn",
    )
    unset = {None, '"nul"', '""', ""}
    if not all(current.get(key) in unset for key in dpad_keys):
        return merged
    overlay = "\n".join(f"{key} = {value}" for key, value in PS202_INPUT_DEFAULTS.items())
    return merge_cfg(merged, overlay, preserve_personal=False)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


# --------------------------------------------------------------------------- #
# Host execution
# --------------------------------------------------------------------------- #

class HostRunner:
    def __init__(self, cwd: Optional[Path] = None, dry_run: bool = False):
        self.cwd = cwd
        self.dry_run = dry_run

    def run(self, args: Sequence[str], timeout: int = 300, check: bool = True,
            binary: bool = False) -> CommandResult:
        if self.dry_run:
            print("  [dry-run] " + " ".join(args))
            return CommandResult(0, "", "")
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout, cwd=str(self.cwd) if self.cwd else None,
        )
        stdout = proc.stdout if binary else proc.stdout.decode("utf-8", "replace")
        stderr = proc.stderr.decode("utf-8", "replace")
        if check and proc.returncode != 0:
            raise InstallerError(f"command failed (rc={proc.returncode}): {' '.join(args)}\n{stderr}")
        return CommandResult(proc.returncode, stdout, stderr)


# --------------------------------------------------------------------------- #
# ADB
# --------------------------------------------------------------------------- #

class AdbClient:
    def __init__(self, adb: str = "adb", serial: Optional[str] = None,
                 runner: Optional[HostRunner] = None):
        self.adb = adb
        self.serial = serial
        self.runner = runner or HostRunner()

    def base(self) -> List[str]:
        return [self.adb, "-s", self.serial] if self.serial else [self.adb]

    def run(self, args: Sequence[str], timeout: int = 300, check: bool = True) -> CommandResult:
        return self.runner.run(self.base() + list(args), timeout=timeout, check=check)

    def shell(self, command: str, timeout: int = 300, check: bool = True) -> CommandResult:
        # 'shell' keeps multi-command remote pipelines intact.
        return self.runner.run(self.base() + ["shell", command], timeout=timeout, check=check)

    def shell_text(self, command: str, timeout: int = 120, check: bool = True) -> str:
        return self.shell(command, timeout=timeout, check=check).stdout.strip()

    def push(self, local: Path, remote: str, timeout: int = 600) -> None:
        self.run(["push", str(local), remote], timeout=timeout)

    def pull(self, remote: str, local: Path, timeout: int = 600, check: bool = True) -> bool:
        result = self.runner.run(self.base() + ["pull", remote, str(local)], timeout=timeout, check=check)
        return result.returncode == 0

    def install_apk(self, apk: Path, timeout: int = 1200) -> None:
        self.run(["install", "-r", "-d", str(apk)], timeout=timeout)

    def wait_for_device(self, timeout: int = 240) -> None:
        self.run(["wait-for-device"], timeout=timeout)

    def get_serialno(self) -> str:
        """Return the connected device serial, or empty if it is unavailable."""
        result = self.run(["get-serialno"], timeout=30, check=False)
        serial = result.stdout.strip()
        return serial if serial and serial != "unknown" else ""

    def reboot(self) -> None:
        self.run(["reboot"], timeout=120)

    def is_root(self) -> bool:
        out = self.shell_text("id", check=False)
        return out.startswith("uid=0")

    def getprop(self, key: str) -> str:
        return self.shell_text(f"getprop {key}", check=False)

    def package_path(self, package: str) -> Optional[str]:
        out = self.shell_text(f"pm path {package}", check=False)
        if out.startswith("package:"):
            return out.split("package:", 1)[1].strip()
        return None


# --------------------------------------------------------------------------- #
# Boot image construction (only used for host-side unit tests / assembly)
# --------------------------------------------------------------------------- #

def build_patched_boot(stock: Path, output: Path, patched_adbd: Path,
                       find_binary: Path, init_script: Path, profile: dict) -> str:
    """Reproduce the verified boot-adbd-root-v2.img from stock boot + patches.

    This mirrors the manual process used to create the reference image. It is
    used for reproducibility testing; the installer normally ships the
    pre-built boot image and just verifies its hash.
    """
    import gzip as _gz
    import struct

    data = stock.read_bytes()
    page = struct.unpack_from("<I", data, 36)[0]
    kernel_size = struct.unpack_from("<I", data, 8)[0]
    ramdisk_size = struct.unpack_from("<I", data, 16)[0]

    kernel_offset = page
    ramdisk_offset = align_up(kernel_offset + kernel_size, page)

    # The ramdisk region is MTK-wrapped: 4-byte magic + 4-byte size +4-byte tag
    # then the gzip cpio. Repack using the wrapper to stay byte-compatible.
    wrapped = data[ramdisk_offset + 12: ramdisk_offset + ramdisk_size]

    def _gzip_roundtrip(raw: bytes) -> bytes:
        return _gz.compress(raw)

    # Decompress the existing ramdisk payload, modify the cpio, recompress.
    cpio_data = _gz.decompress(wrapped)
    entries = _parse_newc(cpio_data)
    new_entries = []
    for name, mode, body in entries:
        if name == "sbin/adbd":
            body = patched_adbd.read_bytes()
            mode = body_mtime_placeholder = None
            new_entries.append((name, 0o100750, body))
        elif name == "sbin/find":
            new_entries.append((name, 0o100750, find_binary.read_bytes()))
        elif name == "sbin/ps202-init.sh":
            new_entries.append((name, 0o100750, init_script.read_bytes()))
        else:
            new_entries.append((name, mode, body))

    new_cpio = _build_newc(new_entries)
    new_wrapped = _gz.compress(new_cpio)
    new_wrapped = wrapped[:12] + new_wrapped

    # Reassemble the boot image: header + kernel + padded + new ramdisk.
    header = bytearray(data[:page])
    ramdisk_region = bytearray(b"\x00" * len(new_wrapped))
    ramdisk_region[: len(new_wrapped)] = new_wrapped
    out = bytearray(data[: ramdisk_offset])
    out += ramdisk_region
    # keep trailing padding (region length) intact
    out += data[ramdisk_offset + len(new_wrapped):]
    output.write_bytes(bytes(out))
    return sha256_file(output)


def _parse_newc(cpio: bytes) -> List[tuple]:
    entries = []
    offset = 0
    while offset + 110 <= len(cpio):
        magic = cpio[offset: offset + 6]
        if magic not in (b"070701", b"070702"):
            break
        # newc header is 110 bytes (but 4-byte padded); fields are hex ascii
        def field(start: int, end: int) -> int:
            return int(cpio[offset + start: offset + end].decode(), 16)
        size = field(54, 62)
        name_len = field(94, 98)
        name = cpio[offset + 110: offset + 110 + name_len - 1].decode()
        mode = field(14, 22)
        body = cpio[offset + 110 + align_up_maybe(name_len, 4): offset + 110 + align_up_maybe(name_len, 4) + size]
        entries.append((name, mode, body))
        offset += align_up_maybe(110 + align_up_maybe(name_len, 4) + size, 4)
    return entries


def align_up_maybe(value: int, page: int) -> int:
    return (value + page - 1) // page * page


def _build_newc(entries: List[tuple]) -> bytes:
    out = bytearray()
    inode = 0x101
    trailer = b"TRAILER!!!"
    def hdr(name_len: int, mode: int, size: int, ino: int) -> bytes:
        fields = [
            "070701",  # magic
            f"{ino:08x}", 0x00000000, f"{mode:08x}", 0x00000000,
            f"{size:08x}", f"{inode * 0x10000 & 0xffffffff:08x}", 0x00000000,
            0x00000001, name_len, 0x00000000,
        ]
        return "".join(fields).encode()
    for name, mode, body in entries:
        nlen = len(name.encode()) + 1
        out += hdr(nlen, mode, len(body), inode)
        out += name.encode() + b"\x00"
        out += body
        out += b"\x00" * ((4 - (len(out) % 4)) % 4)
        inode += 1
    nlen = len(trailer) + 1
    out += hdr(nlen, 0, 0, inode)
    out += trailer + b"\x00"
    return bytes(out)


# --------------------------------------------------------------------------- #
# Manifest / profile
# --------------------------------------------------------------------------- #

class VamanOSInstaller:
    def __init__(self, manifest_path: Path = DEFAULT_MANIFEST,
                 profile_path: Path = DEFAULT_PROFILE,
                 adb: str = "adb", serial: Optional[str] = None,
                 dry_run: bool = False, quiet: bool = False,
                 bundle_root: Optional[Path] = None):
        self.quiet = quiet
        self.manifest = load_json(manifest_path)
        self.profile = load_json(profile_path)
        if self.profile.get("id") != "PS202_00001":
            raise InstallerError("device-profile.json is not the PS202_00001 profile")
        self.runner = HostRunner(dry_run=dry_run)
        self.adb = AdbClient(adb, serial, self.runner)
        discovered_serial = serial or self.adb.get_serialno()
        self.serial = discovered_serial or "default"
        if not serial and discovered_serial:
            # Pin all subsequent calls to the discovered device and make the
            # confirmation token match the serial shown by `adb devices`.
            self.adb.serial = discovered_serial
        self.identity: Optional[dict] = None
        self.known = False
        self.run_dir = INSTALLER_DIR / "runs" / (
            time.strftime("%Y%m%d-%H%M%S") + "-" + self.serial)
        self.dry_run = dry_run
        self.preserved_system_digests: Dict[str, str] = {}
        # If set, artifacts resolve from an extracted `assemble` bundle instead
        # of the workspace source tree. `bundle_root/payload/bundle-sha256.json`
        # (or the workspace bundle layout) is used to locate files.
        self.bundle_root = bundle_root

    def msg(self, text: str) -> None:
        if not self.quiet:
            print(text)

    def log(self, text: str) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "installer.log").open("a", encoding="utf-8") as stream:
            stream.write(text.rstrip() + "\n")

    # -- device identity --------------------------------------------------- #
    def identify(self) -> dict:
        identity = {
            "model": self.adb.getprop("ro.product.model"),
            "build_id": self.adb.getprop("ro.build.display.id"),
            "android_release": self.adb.getprop("ro.build.version.release"),
            "abi": self.adb.getprop("ro.product.cpu.abi"),
        }
        self.identity = identity
        expected = self.profile["identity"]
        self.known = all(identity[k] == expected[k] for k in ("model", "build_id", "android_release", "abi"))
        return identity

    def print_identity(self) -> None:
        ident = self.identify()
        state = "MATCH (PS202_00001)" if self.known else "UNKNOWN device"
        self.msg(f"Device: {ident['model']} / {ident['build_id']} / "
                 f"Android {ident['android_release']} / {ident['abi']}  [{state}]")

    # -- artifact resolution ----------------------------------------------- #
    def _bundle_artifact(self, key: str) -> Optional[Path]:
        """Locate an artifact inside an extracted `assemble` bundle."""
        if not self.bundle_root:
            return None
        mapping = {
            "emulationstation": "payload/apks/emulationstation.apk",
            "ppsspp": "payload/apks/ppsspp.apk",
            "su": "payload/bin/su",
            "patched_adbd": "payload/bin/adbd",
            "find": "payload/bin/find",
            "temproot_cowtest": "payload/bin/cowtest",
            "temproot_blockdump": "payload/bin/runas-blockdump",
            "boot_stock": "payload/boot/boot_stock.img",
            "boot_patched": "payload/boot/boot_patched.img",
            "android_bootanimation": "payload/boot/android_bootanimation.zip",
            "cody_theme": "payload/themes/EPIC-CODY.zip",
            "frontend_music": "payload/music",
        }
        rel = mapping.get(key)
        if not rel:
            return None
        candidate = self.bundle_root / rel
        return candidate if candidate.is_file() or candidate.is_dir() else None

    def _download_artifact(self, key: str, spec: dict, target: Path) -> None:
        """Download a pinned artifact into a local cache and verify it later."""
        url = spec.get("url")
        if not url:
            raise InstallerError(f"artifact {key} is missing: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".part", dir=str(target.parent))
        temporary = Path(temporary_name)
        try:
            self.msg(f"  downloading {key} from the official source")
            request = Request(url, headers={"User-Agent": "vamanOS-installer/1.0"})
            with urlopen(request, timeout=300) as response, os.fdopen(fd, "wb") as stream:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    stream.write(chunk)
            temporary.replace(target)
        except (OSError, URLError) as exc:
            try:
                os.close(fd)
            except OSError:
                pass
            raise InstallerError(f"could not download {key} from {url}: {exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def art(self, key: str) -> Path:
        """Resolve an artifact and verify its pinned SHA-256.

        Precedence: an extracted bundle (--bundle) first, then the workspace
        source/cache path, then a pinned download URL, then the manifest's
        fallback list.
        """
        spec = self.manifest["artifacts"][key]
        bundled = self._bundle_artifact(key)
        if bundled is not None:
            source = bundled
        else:
            source_value = spec.get("source") or spec.get("download")
            if not source_value:
                raise InstallerError(f"artifact {key} has no source or download path")
            base = self.bundle_root or INSTALLER_DIR
            source = resolve_path(source_value, base)
        if not source.is_file():
            if bundled is None:
                if spec.get("url"):
                    self._download_artifact(key, spec, source)
                else:
                    for fallback in spec.get("fallback", []):
                        candidate = resolve_path(fallback, INSTALLER_DIR) if not Path(fallback).is_absolute() else Path(fallback)
                        if candidate.is_file():
                            source = candidate
                            break
                    else:
                        raise InstallerError(f"artifact {key} missing: {source}")
            else:
                raise InstallerError(f"bundle artifact {key} missing: {source}")
        expected = spec.get("sha256")
        if expected:
            actual = sha256_file(source)
            if actual != expected:
                raise InstallerError(f"SHA-256 mismatch for {key}: {source}\n  expected {expected}\n  actual   {actual}")
        return source

    def frontend_music_files(self) -> Dict[str, Path]:
        """Resolve and verify the checksum-pinned frontend music directory."""
        spec = self.manifest["artifacts"]["frontend_music"]
        bundled = self._bundle_artifact("frontend_music")
        if bundled is not None:
            root = bundled
        else:
            root = resolve_path(spec["source"], INSTALLER_DIR)
        if not root.is_dir():
            raise InstallerError(f"frontend music directory missing: {root}")

        files = spec.get("files", {})
        if not isinstance(files, dict) or not files:
            raise InstallerError("frontend music manifest has no files")
        resolved: Dict[str, Path] = {}
        for name, expected in files.items():
            relative = Path(name)
            if relative.is_absolute() or relative.name != name:
                raise InstallerError(f"unsafe frontend music filename: {name}")
            source = root / relative
            if not source.is_file():
                raise InstallerError(f"frontend music file missing: {source}")
            actual = sha256_file(source)
            if actual != expected:
                raise InstallerError(
                    f"SHA-256 mismatch for frontend music {name}:\n"
                    f"  expected {expected}\n  actual   {actual}")
            resolved[name] = source
        return resolved

    def payload_file(self, key: str) -> Path:
        """Resolve a non-hashed payload file from a workspace or bundle."""
        try:
            relative = self.manifest["payload"][key]
        except KeyError as exc:
            raise InstallerError(f"payload entry is missing: {key}") from exc
        if self.bundle_root:
            bundled = self.bundle_root / relative
            if bundled.is_file():
                return bundled
        source = resolve_path(relative, INSTALLER_DIR)
        if not source.is_file():
            raise InstallerError(f"payload file {key} missing: {source}")
        return source

    def core_files(self) -> Dict[str, Path]:
        """Resolve the core .so files named in the manifest's cores map.

        When running from a bundle, looks in `<bundle>/payload/cores/` first,
        then the workspace core_sources.
        """
        core_names = self.manifest.get("cores", {})
        sources = []
        if self.bundle_root:
            sources.append(self.bundle_root / "payload" / "cores")
        sources += [resolve_path(s, INSTALLER_DIR) for s in self.manifest.get("core_sources", [])]
        found: Dict[str, Path] = {}
        for short, filename in core_names.items():
            candidates = [d / filename for d in sources]
            path = next((c for c in candidates if c.is_file()), None)
            if path is None:
                raise InstallerError(f"core missing: {filename} (checked {[str(s) for s in sources]})")
            found[short] = path
        return found

    def validate_install_artifacts(self, boot_mode: str,
                                   require_ppsspp: bool = True) -> None:
        """Resolve every file needed by install before requesting confirmation.

        This is deliberately host-only. The install plan must fail before any
        boot write or Android system-file change if a pinned APK, core, payload,
        or temp-root input is unavailable.
        """
        required = [
            "android_bootanimation", "su", "find", "emulationstation",
            "retroarch", "cody_theme",
        ]
        if require_ppsspp:
            required.append("ppsspp")
        if boot_mode in ("force", "temproot"):
            required.append("boot_patched")
        if boot_mode == "temproot":
            required.extend(("temproot_cowtest", "temproot_blockdump"))
        for key in required:
            self.art(key)
        self.frontend_music_files()
        self.core_files()
        for key in ("boot_helper", "performance_profile", "launcher_config", "retroarch_baseline"):
            self.payload_file(key)

    # -- preflight --------------------------------------------------------- #
    def preflight(self, boot_mode: str = "auto") -> dict:
        self.identify()
        root = self.adb.is_root()
        sd = self.adb.shell_text("ls -d /storage/sdcard1 2>/dev/null", check=False) == "/storage/sdcard1"
        report = {"known": self.known, "root_adb": root, "sd_mounted": sd}
        if not sd:
            if self.dry_run:
                report["sd_mounted"] = None
                self.log("preflight (dry-run): SD mount not checked")
            else:
                raise InstallerError("external SD (/storage/sdcard1) is not mounted. Insert the ROM/SD card and retry.")
        if report["known"] and not self.dry_run:
            if root:
                boot = self.read_current_region("boot", INSTALLER_DIR / "runs" / "_preflight-boot.bin")
                self.region_check = boot
                report["boot_sha256"] = boot
            else:
                # A factory shell cannot read mmcblk0. The temporary-root
                # bootstrap must run before boot-state inspection is possible.
                report["boot_read_deferred"] = True
                self.log("preflight: boot read deferred until temproot bootstrap")
        self.log("preflight: " + json.dumps(report, sort_keys=True))
        return report

    # -- region I/O (root only) --------------------------------------------- #
    def _region(self, name: str) -> dict:
        return self.profile["regions"][name]

    def read_current_region(self, name: str, output: Path) -> str:
        region = self._region(name)
        sec = region["offset"] // 512
        count = region["length"] // 512
        remote = f"/data/local/vamanos-{name}-read.bin"
        self.adb.shell_text(f"dd if=/dev/block/mmcblk0 of={remote} bs=512 skip={sec} count={count} 2>/dev/null; echo done")
        output.parent.mkdir(parents=True, exist_ok=True)
        if not self.adb.pull(remote, output, check=False):
            raise InstallerError(f"could not read {name} region from device")
        return sha256_file(output)

    def write_region(self, name: str, source: Path) -> None:
        region = self._region(name)
        sec = region["offset"] // 512
        count = region["length"] // 512
        remote = f"/data/local/vamanos-{name}-write.img"
        self.adb.push(source, remote)
        actual = sha256_file(source)
        # Only reviewed images (stock or the profile's target image) may be
        # written into a firmware region.
        allowed = {region["stock_sha256"], self._target_hash(name)}
        if actual not in allowed:
            raise InstallerError(f"refusing to write {name}: image hash {actual} is not a reviewed image")
        self.adb.shell_text(f"dd if={remote} of=/dev/block/mmcblk0 bs=512 seek={sec} count={count} 2>/dev/null; sync; echo done")

    def _target_hash(self, name: str) -> str:
        region = self._region(name)
        if name == "boot":
            return region["patched_sha256"]
        return region["custom_sha256"]

    def verify_readback(self, name: str) -> str:
        out = self.run_dir / f"{name}-readback.bin"
        digest = self.read_current_region(name, out)
        expected = self._target_hash(name)
        if digest != expected:
            raise InstallerError(f"{name} readback SHA-256 {digest} != expected {expected}")
        return digest

    def read_readback_via_runas(self, name: str, output: Path) -> str:
        """Read a firmware region through the temp-root run-as primitive.

        Mirrors tools/flash-boot-v1.sh: after the dirtycow write the shell is
        still the unprivileged `shell` user; the block region is read back via
        `/system/bin/run-as OFFSET LEN hex`. We decode the hex on the host and
        SHA-256 it. No host dependency beyond Python.
        """
        region = self._region(name)
        out = self.adb.shell_text(
            f"/system/bin/run-as {region['offset']} {region['length']} hex")
        hex_digits = "".join(ch for ch in out if ch in "0123456789abcdefABCDEF")
        if len(hex_digits) != region["length"] * 2:
            raise InstallerError(
                f"{name} readback via run-as returned unexpected length "
                f"got {len(hex_digits)} hex chars, want {region['length'] * 2}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(bytes.fromhex(hex_digits))
        return sha256_file(output)

    # -- temp-root bootstrap (factory units) -------------------------------- #
    def _temproot_inputs(self) -> tuple:
        """Return the pinned Dirty COW helper paths."""
        return self.art("temproot_cowtest"), self.art("temproot_blockdump")

    def bootstrap_temproot(self, boot_patched: Path) -> None:
        """Use dirtycow to gain a one-shot root and write the patched boot."""
        if self.dry_run:
            self.msg("[dry-run] would run dirtycow temp-root bootstrap")
            return
        cowtest, blockdump = self._temproot_inputs()
        # step 1: push helpers + image
        self.adb.push(cowtest, "/data/local/tmp/cowtest")
        self.adb.push(blockdump, "/data/local/tmp/runas-blockdump")
        self.adb.push(boot_patched, "/data/local/tmp/boot-patch.img")
        self.adb.shell_text("chmod 755 /data/local/tmp/cowtest /data/local/tmp/runas-blockdump")

        # step 2: dirtycow run-as
        self.adb.shell_text("cp /system/bin/run-as /data/local/tmp/run-as-original")
        self.adb.shell_text("/data/local/tmp/cowtest /data/local/tmp/runas-blockdump /system/bin/run-as --no-pad")

        # step 3: write boot region via patched run-as
        region = self._region("boot")
        hex_offset = hex(region["offset"])
        hex_len = hex(region["length"])
        self.adb.shell_text(f"/system/bin/run-as {hex_offset} {hex_len} writefile /data/local/tmp/boot-patch.img")
        self.adb.shell_text("sync")

        # step 4: read back and verify (through run-as, as in flash-boot-v1.sh)
        digest = self.read_readback_via_runas("boot", self.run_dir / "boot-bootstrap-readback.bin")
        if digest != region["patched_sha256"]:
            raise InstallerError(
                f"boot readback after temp-root write mismatches patch: {digest}\n"
                "Device is NOT rooted yet. Re-run after restoring run-as, do not reboot.")
        # step 5: restore run-as
        self.adb.shell_text("/data/local/tmp/cowtest /data/local/tmp/run-as-original /system/bin/run-as --no-pad")
        self.msg("Boot patch verified. Rebooting to activate root ADB...")
        self.adb.reboot()
        self.adb.wait_for_device(timeout=300)
        if not self.adb.is_root():
            raise InstallerError("root ADB is not active after boot patch reboot")

    # -- post-root setup --------------------------------------------------- #
    def install_su(self, su: Path) -> None:
        if self.dry_run:
            self.msg("[dry-run] install /system/xbin/su")
            return
        if not self.adb.is_root():
            raise InstallerError("install_su requires root ADB")
        # back up any existing su first (never overwrite a working one blindly)
        self.adb.shell_text("test -f /system/xbin/su && cp -f /system/xbin/su /system/xbin/su.vamanos-previous 2>/dev/null; echo done")
        self.adb.push(su, "/data/local/tmp/vamanos-su")
        # chown clears setuid/setgid on Android; set ownership first and the
        # 6755 mode last so su remains usable by non-root callers.
        self.adb.shell_text("mount -o rw,remount /system 2>/dev/null; cp -f /data/local/tmp/vamanos-su /system/xbin/su; chown 0:0 /system/xbin/su; chmod 6755 /system/xbin/su; sync")
        mode = self.adb.shell_text("ls -l /system/xbin/su 2>/dev/null", check=False)
        if not mode.startswith("-rwsr-sr-x"):
            raise InstallerError(f"/system/xbin/su has unexpected mode/owner: {mode}")

    def install_system_binary(self, key: str) -> None:
        """Install an aux binary (find, etc.) to its /system path.

        Mirrors what the reference device has in /system/xbin. This makes the
        installer self-sufficient rather than relying only on the first-boot
        ps202-init.sh copy from the ramdisk.
        """
        spec = self.manifest["artifacts"][key]
        on_device = spec.get("on_device")
        if not on_device:
            return
        if self.dry_run:
            self.msg(f"[dry-run] install {on_device}")
            return
        src = self.art(key)
        remote = f"/data/local/tmp/vamanos-{key}"
        self.adb.push(src, remote)
        mode = str(spec.get("mode", "0755"))
        owner = spec.get("owner", "0:0")
        self.adb.shell_text(
            f"mount -o rw,remount /system 2>/dev/null; "
            f"cp -f {remote} {on_device}; chmod {mode} {on_device}; chown {owner} {on_device}; sync; echo done")

    def install_aux_binaries(self) -> None:
        """Install find (and any other manifest 'on_device' binaries except su,
        which is handled separately by install_su)."""
        for key, spec in self.manifest.get("artifacts", {}).items():
            if key == "su":
                continue  # handled by install_su (mode 6755 / setuid)
            if isinstance(spec, dict) and spec.get("on_device"):
                self.install_system_binary(key)


    def deploy_boot_helper(self, helper: Path, performance_profile: Optional[Path] = None) -> None:
        self.adb.push(helper, "/data/local/ps202-boot.sh")
        command = (
            "chmod 0755 /data/local/ps202-boot.sh; "
            "chown 0:0 /data/local/ps202-boot.sh"
        )
        if performance_profile is not None:
            self.adb.push(performance_profile, "/data/local/ps202-performance.sh")
            command += (
                "; chmod 0755 /data/local/ps202-performance.sh; "
                "chown 0:0 /data/local/ps202-performance.sh"
            )
        self.adb.shell_text(command)

    def install_android_bootanimation(self) -> None:
        """Install the Android userspace boot splash, preserving its old file."""
        spec = self.manifest["artifacts"]["android_bootanimation"]
        splash = self.profile["android_boot_splash"]
        source = self.art("android_bootanimation")
        if self.dry_run:
            self.msg(f"[dry-run] install Android boot splash {splash['path']}")
            return

        current = self.run_dir / "android-bootanimation-current.zip"
        if self.adb.pull(splash["path"], current, check=False) and current.is_file():
            if sha256_file(current) == spec["sha256"]:
                self.msg("  Android boot splash already matches the vamanOS animation")
                return

        remote = "/data/local/tmp/vamanos-bootanimation.zip"
        self.adb.push(source, remote)
        self.adb.shell(
            f"mount -o rw,remount /system 2>/dev/null; "
            f"cp -f {splash['path']} {splash['backup_path']} 2>/dev/null || true; "
            f"cp -f {remote} {splash['path']} && "
            f"chmod {splash['mode']} {splash['path']} && "
            f"chown {splash['owner']} {splash['path']} && sync")
        self.verify_android_bootanimation()

    def verify_android_bootanimation(self) -> str:
        """Pull and hash the installed Android boot animation."""
        if self.dry_run:
            return ""
        splash = self.profile["android_boot_splash"]
        output = self.run_dir / "android-bootanimation-readback.zip"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if not self.adb.pull(splash["path"], output, check=False) or not output.is_file():
            raise InstallerError(f"Android boot splash is missing at {splash['path']}")
        digest = sha256_file(output)
        expected = self.manifest["artifacts"]["android_bootanimation"]["sha256"]
        if digest != expected:
            raise InstallerError(f"Android boot splash SHA-256 {digest} != expected {expected}")
        return digest

    def ensure_sd_layout(self) -> None:
        for path in self.manifest.get("sd_layout", []):
            self.adb.shell_text(f"mkdir -p /storage/sdcard1/{path}")

    def install_cores(self, cores: Dict[str, Path]) -> None:
        """Install a readable SD source and an executable runtime copy.

        The PS202 SD/FUSE mounts are noexec, so RetroArch cannot load a
        libretro shared object directly from them.  The ADB sync service can
        write into RetroArch's 0700 app-private cores directory even though a
        root shell on this old Android build cannot; use that service instead
        of a shell cp/chown/chmod sequence.  The SD copy remains user-visible
        and is never removed.
        """
        for short, src in cores.items():
            self.adb.push(src, f"{RADIR_SD}/{src.name}")
            self.adb.push(src, f"{RADIR_PRIVATE}/{src.name}")
            self.log(f"core {short}: SD source + private runtime {src.name}")

    def verify_private_cores(self, cores: Dict[str, Path]) -> None:
        """Read back every runtime core and compare it with its pinned source."""
        if self.dry_run:
            return
        output_dir = self.run_dir / "retroarch-private-cores"
        output_dir.mkdir(parents=True, exist_ok=True)
        for short, src in cores.items():
            output = output_dir / src.name
            if not self.adb.pull(f"{RADIR_PRIVATE}/{src.name}", output, check=False):
                raise InstallerError(f"RetroArch private core is missing: {RADIR_PRIVATE}/{src.name}")
            actual = sha256_file(output)
            expected = sha256_file(src)
            if actual != expected:
                raise InstallerError(
                    f"RetroArch private core {short} hash {actual} != source {expected}")
            self.log(f"core {short}: private sha256={actual}")

    def install_cody_theme(self) -> None:
        """Stage the V2 EPIC-CODY archive for the Android bootstrap importer."""
        spec = self.manifest["artifacts"]["cody_theme"]
        target = spec["device_path"]
        source = self.art("cody_theme")
        if self.dry_run:
            self.msg(f"[dry-run] install V2 CODY theme {target}")
            return

        current = self.run_dir / "cody-theme-current.zip"
        if self.adb.pull(target, current, check=False) and current.is_file():
            if sha256_file(current) == spec["sha256"]:
                self.msg("  V2 CODY theme archive already matches")
                return

        remote = "/data/local/tmp/vamanos-EPIC-CODY.zip"
        backup = target + ".previous"
        self.adb.push(source, remote)
        self.adb.shell(
            f"mkdir -p /storage/sdcard1/ps202/themes; "
            f"if test -f '{target}'; then cp -f '{target}' '{backup}'; fi; "
            f"cp -f '{remote}' '{target}' && sync")
        self.verify_cody_theme(require_active=False)
        self.msg(f"  staged V2 CODY theme at {target}")

    def verify_cody_theme(self, require_active: bool = False) -> bool:
        """Verify the staged archive and, optionally, V2's activated theme root."""
        spec = self.manifest["artifacts"]["cody_theme"]
        target = spec["device_path"]
        output = self.run_dir / "cody-theme-readback.zip"
        if not self.adb.pull(target, output, check=False) or not output.is_file():
            raise InstallerError(f"V2 CODY theme archive is missing at {target}")
        digest = sha256_file(output)
        if digest != spec["sha256"]:
            raise InstallerError(
                f"V2 CODY theme SHA-256 {digest} != expected {spec['sha256']}")

        active = self.adb.shell_text(
            "test -f /storage/sdcard1/themes/EPIC-CODY/theme.xml && echo yes",
            check=False).endswith("yes")
        if require_active and not active:
            raise InstallerError("V2 CODY theme archive is staged but EPIC-CODY did not activate")
        return active

    def install_frontend_music(self) -> None:
        """Install missing Batocera frontend music without removing user tracks."""
        spec = self.manifest["artifacts"]["frontend_music"]
        files = self.frontend_music_files()
        target_root = spec["device_path"]
        if self.dry_run:
            self.msg(f"[dry-run] install frontend music in {target_root}")
            return

        target_root_q = shlex.quote(target_root)
        self.adb.shell_text(f"mkdir -p {target_root_q}")
        installed = 0
        kept = 0
        for index, (name, source) in enumerate(files.items()):
            remote = f"/data/local/tmp/vamanos-music-{index}.ogg"
            target = f"{target_root}/{name}"
            target_q = shlex.quote(target)
            remote_q = shlex.quote(remote)
            self.adb.push(source, remote)
            state = self.adb.shell_text(
                f"if test -f {target_q}; then echo existing; "
                f"elif cp -f {remote_q} {target_q}; then echo installed; "
                f"else echo failed; fi; rm -f {remote_q}; sync",
                check=False,
            )
            if state.endswith("installed"):
                installed += 1
            elif state.endswith("existing"):
                kept += 1
            else:
                raise InstallerError(f"could not install frontend music: {target}")
        self.msg(f"  frontend music: {installed} copied, {kept} existing files kept")

    def verify_frontend_music(self) -> None:
        """Confirm every bundled frontend track exists on the SD card."""
        spec = self.manifest["artifacts"]["frontend_music"]
        for name in spec.get("files", {}):
            target = shlex.quote(f"{spec['device_path']}/{name}")
            if not self.adb.shell_text(f"test -f {target} && echo yes", check=False).endswith("yes"):
                raise InstallerError(f"frontend music is missing: {spec['device_path']}/{name}")

    def install_retroarch_config(self, baseline: Path) -> None:
        """Merge the baseline cfg into the running shared config, preserving user bindings."""
        cfg_path = "/storage/sdcard0/Android/data/com.retroarch.ra32/files/retroarch.cfg"
        local = self.run_dir / "retroarch.cfg"
        overlay = baseline.read_text(encoding="utf-8")
        if self.adb.pull(cfg_path, local, check=False) and local.is_file():
            existing = local.read_text(encoding="utf-8", errors="replace")
            merged = merge_cfg(existing, overlay, preserve_personal=True)
            merged = apply_ps202_input_defaults(existing, merged)
            tmp = self.run_dir / "retroarch.merged.cfg"
            tmp.write_text(merged, encoding="utf-8")
            self.adb.push(tmp, "/data/local/tmp/vamanos-retroarch.cfg")
            self.adb.shell_text(f"cp -f /data/local/tmp/vamanos-retroarch.cfg '{cfg_path}'; chmod 664 '{cfg_path}'; echo done")
        else:
            # no existing config -> write baseline directly
            self.adb.push(baseline, "/data/local/tmp/vamanos-retroarch-baseline.cfg")
            self.adb.shell_text(f"cp -f /data/local/tmp/vamanos-retroarch-baseline.cfg \"{cfg_path}\"; echo done")

    def deploy_launchers(self, launchers: Path) -> None:
        self.adb.push(launchers, "/storage/sdcard1/ps202/configs/android_launchers.xml")

    def snapshot_preserved_system_files(self, phase: str) -> Dict[str, str]:
        """Read preserved system files and optionally compare with the install baseline."""
        digests: Dict[str, str] = {}
        for remote in self.profile.get("preserve_system_files", []):
            name = remote.strip("/").replace("/", "_")
            local = self.run_dir / f"{name}.{phase}"
            if not self.adb.pull(remote, local, check=False) or not local.is_file():
                raise InstallerError(f"preserved system file is unreadable: {remote}")
            if local.stat().st_size == 0:
                raise InstallerError(f"preserved system file is empty: {remote}")
            digests[remote] = sha256_file(local)
            self.log(f"preserved {remote} {phase} sha256={digests[remote]}")
        return digests

    def verify_preserved_system_files(self) -> None:
        """Ensure vamanOS did not alter the stock controller keylayout or other protected files."""
        after = self.snapshot_preserved_system_files("after")
        for remote, before_digest in self.preserved_system_digests.items():
            if after.get(remote) != before_digest:
                raise InstallerError(f"preserved system file changed during install: {remote}")

    def backup_packages_before_removal(self) -> None:
        """Back up removable packages before pm uninstall, refusing unsafe removal."""
        config = self.profile["debloat"]
        backup_root = config.get("backup_path", "/storage/sdcard1/ps202/backups/apps")
        if self.dry_run:
            self.msg(f"[dry-run] back up removable packages to {backup_root}")
            return

        root_q = shlex.quote(backup_root)
        self.adb.shell_text(f"mkdir -p {root_q}", check=False)
        host_root = self.run_dir / "removed-app-backup"
        records = []
        for package in config["remove"]:
            if package in set(config.get("protected", [])):
                raise InstallerError(f"debloat configuration protects a removable package: {package}")

            apk_path = self.adb.package_path(package)
            if not apk_path:
                self.log(f"backup skipped absent package {package}")
                continue

            package_dir = f"{backup_root}/{package}"
            package_dir_q = shlex.quote(package_dir)
            marker = f"{package_dir}/.complete"
            marker_q = shlex.quote(marker)
            apk_backup = f"{package_dir}/app.apk"
            data_backup = f"{package_dir}/data"
            info = f"{package_dir}/backup-info.txt"
            data_path = f"/data/data/{package}"
            command = (
                f"mkdir -p {package_dir_q}; "
                f"if test -f {marker_q}; then echo existing; else "
                f"if test -n {shlex.quote(apk_path)}; then "
                f"cp -p {shlex.quote(apk_path)} {shlex.quote(apk_backup)} || exit 1; fi; "
                f"if test -d {shlex.quote(data_path)}; then "
                f"if cp -R -p {shlex.quote(data_path)} {shlex.quote(data_backup)}; "
                f"then DATA_STATUS=backed_up; else DATA_STATUS=retained_by_pm_uninstall_k; fi; "
                f"else DATA_STATUS=absent; fi; "
                f"echo package={package} > {shlex.quote(info)} && "
                f"echo apk={apk_path} >> {shlex.quote(info)} && "
                f"echo data=$DATA_STATUS >> {shlex.quote(info)} && "
                f"touch {marker_q}; fi"
            )
            self.adb.shell_text(command, check=False)
            if not self.adb.shell_text(f"test -f {marker_q} && echo yes", check=False).endswith("yes"):
                raise InstallerError(
                    f"backup failed for {package}; refusing to remove it. "
                    f"Check {backup_root} and retry.")

            host_dir = host_root / package
            host_dir.mkdir(parents=True, exist_ok=True)
            host_apk = host_dir / "app.apk"
            host_apk_ok = self.adb.pull(apk_path, host_apk, check=False)
            records.append({
                "package": package,
                "apk_source": apk_path,
                "device_backup": f"{backup_root}/{package}",
                "host_apk": str(host_apk) if host_apk_ok else None,
                "data_restore_policy": "pm uninstall -k retains app data on Android 4.4.2",
            })
            self.msg(f"  backed up {package} before removal")

        write_json(self.run_dir / "removed-app-backup.json", {
            "device_path": backup_root,
            "host_path": str(host_root),
            "packages": records,
        })

    def apply_packages(self) -> None:
        disable = self.profile["debloat"]["disable"]
        remove = self.profile["debloat"]["remove"]
        protected = set(self.profile["debloat"]["protected"])
        for pkg in disable:
            if pkg in protected:
                continue
            self.adb.shell_text(f"pm disable {pkg} 2>/dev/null >/dev/null; echo done")
        self.backup_packages_before_removal()
        for pkg in remove:
            if pkg in protected:
                continue
            self.adb.shell_text(f"pm uninstall -k {pkg} 2>/dev/null >/dev/null; echo done")

    def set_home(self) -> None:
        # ES is the sole CATEGORY_HOME provider; make it the default.
        self.adb.shell_text("cmd package set-home-activity com.ps202.emulationstation/.PS202HomeActivity 2>/dev/null; echo done")

    def install_apks(self) -> None:
        for key in ("emulationstation", "retroarch"):
            apk = self.art(key)
            self.msg(f"  installing {key} ({apk.stat().st_size // (1024*1024)} MiB)")
            self.adb.install_apk(apk)
        if self.adb.package_path(PPSSPP_PACKAGE):
            self.msg("  keeping existing ppsspp")
            return
        apk = self.art("ppsspp")
        self.msg(f"  installing ppsspp ({apk.stat().st_size // (1024*1024)} MiB)")
        self.adb.install_apk(apk)

    def verify(self, require_root: bool = True) -> None:
        if self.dry_run:
            return  # nothing is installed under --dry-run; nothing to verify
        if require_root and not self.adb.is_root():
            raise InstallerError("post-install ADB is not root")
        for package in ("com.ps202.emulationstation", "com.retroarch.ra32", "org.ppsspp.ppsspp"):
            if not self.adb.package_path(package):
                raise InstallerError(f"installed package is missing: {package}")
        if self.adb.package_path("com.ps202.shell"):
            raise InstallerError("PS202 Shell is still installed; the installer must remove it")
        if require_root:
            su_out = self.adb.shell_text("su -c id", check=False)
            if "uid=0" not in su_out:
                raise InstallerError("su -c id did not return root")
            self.verify_android_bootanimation()
            if "0" != self.adb.shell_text("test -f /data/local/ps202-boot.sh; echo $?", check=False)[-1:]:
                raise InstallerError("PS202 boot helper is missing")
            if "0" != self.adb.shell_text("test -f /data/local/ps202-performance.sh; echo $?", check=False)[-1:]:
                raise InstallerError("PS202 performance profile is missing")
            # su + find must be present in /system/xbin (adbd lives in the boot
            # ramdisk and is proven by root-ADB being active above).
            for bin_path, key in (("/system/xbin/su", "su"), ("/system/xbin/find", "find")):
                present = self.adb.shell_text(f"test -f {bin_path} && echo yes", check=False).endswith("yes")
                if not present:
                    raise InstallerError(f"{key} binary is missing at {bin_path}")
            self.verify_private_cores(self.core_files())
            self.verify_preserved_system_files()
            self.verify_frontend_music()
        self.ensure_sd_layout()
        self.adb.shell("am start -n com.ps202.emulationstation/.PS202HomeActivity", check=False)
        time.sleep(3)
        self.verify_cody_theme(require_active=True)
        act = self.adb.shell_text("dumpsys activity activities", timeout=30, check=False)
        if "com.ps202.emulationstation" not in act:
            raise InstallerError("EmulationStation is not present in the activity dump after launch")
        self.msg("Verification passed: root ADB (adbd), su + find, boot helper, packages, preserved controller map, V2 CODY theme, ES home.")

    # -- top level ---------------------------------------------------------- #
    def report_cpu(self) -> None:
        """Report the live CPU governor/frequency (read-only).

        On this MT6572 the cpufreq control nodes are owned by the `radio`
        uid and the kernel rejects writes from any userspace process (even
        root / su), so the governor cannot be forced to `userspace` to "pin"
        a frequency at runtime. The device already reaches cpuinfo_max_freq
        under the hotplug governor. We therefore only *report* the true state
        rather than attempt a write that would fail.
        """
        base = "/sys/devices/system/cpu/cpu0/cpufreq"
        gov = self.adb.shell_text(f"cat {base}/scaling_governor 2>/dev/null", check=False)
        cur = self.adb.shell_text(f"cat {base}/scaling_cur_freq 2>/dev/null", check=False)
        mx = self.adb.shell_text(f"cat {base}/cpuinfo_max_freq 2>/dev/null", check=False)
        mn = self.adb.shell_text(f"cat {base}/cpuinfo_min_freq 2>/dev/null", check=False)
        gov = gov.strip() if gov else "n/a"
        cur = cur.strip() if cur else "n/a"
        mx = mx.strip() if mx else "n/a"
        mn = mn.strip() if mn else "n/a"
        self.log(f"cpu: governor={gov} cur={cur} min={mn} max={mx}")
        self.msg(f"CPU freq:     governor {gov}, now {self._fmt_mhz(cur)}, "
                 f"range {self._fmt_mhz(mn)}–{self._fmt_mhz(mx)}")
        if mx.isdigit() and cur.isdigit() and int(cur) >= int(mx):
            self.msg(f"             already at the {self._fmt_mhz(mx)} hardware maximum; "
                     "runtime overclock/pinning is blocked by the MTK cpufreq driver")
        else:
            self.msg("             (governor/frequency read from the MT6572 cpufreq sysfs)")

    @staticmethod
    def _fmt_mhz(value: str) -> str:
        if value and value.lstrip("-").isdigit():
            return f"{int(value) // 1000} MHz"
        return value

    def doctor(self) -> None:
        self.print_identity()
        root = self.adb.is_root()
        self.msg(f"Root ADB:     {'yes' if root else 'no'}")
        self.msg(f"SD (/storage/sdcard1): {'mounted' if self.adb.shell_text('ls -d /storage/sdcard1 2>/dev/null', check=False) else 'not mounted'}")
        self.msg(f"su on device: {'present' if self.adb.shell_text('test -x /system/xbin/su && echo yes', check=False).endswith('yes') else 'absent'}")
        try:
            self._temproot_inputs()
            self.msg("Temp-root helpers: ready")
        except InstallerError as exc:
            self.msg(f"Temp-root helpers: unavailable ({exc})")
        self.report_cpu()
        if self.known:
            if root:
                boot = self.read_current_region("boot", self.run_dir / "doctor-boot.bin")
                state = "STOCK" if boot == self.profile["regions"]["boot"]["stock_sha256"] else (
                    "PATCHED (root)" if boot == self.profile["regions"]["boot"]["patched_sha256"] else "UNKNOWN")
                self.msg(f"Boot region:  {state} ({boot[:16]}…)")
            else:
                self.msg("Boot region:  unavailable without root ADB; install --boot-mode temproot will inspect it after bootstrap")
            splash = self.run_dir / "doctor-bootanimation.zip"
            if self.adb.pull(self.profile["android_boot_splash"]["path"], splash, check=False):
                digest = sha256_file(splash)
                expected = self.manifest["artifacts"]["android_bootanimation"]["sha256"]
                splash_state = "CUSTOM vamanOS" if digest == expected else "OTHER"
                self.msg(f"Android boot splash: {splash_state} ({digest[:16]}…)")
            else:
                self.msg("Android boot splash: unavailable")

    def install(self, boot_mode: str = "auto",
                confirmed: Optional[str] = None) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.print_identity()
        pre = self.preflight(boot_mode=boot_mode)
        root = pre["root_adb"]
        ppsspp_present = None if self.dry_run else bool(self.adb.package_path(PPSSPP_PACKAGE))

        if self.known:
            if boot_mode == "auto":
                boot_state = pre.get("boot_sha256")
                if boot_state == self.profile["regions"]["boot"]["patched_sha256"]:
                    boot_mode = "skip"  # already rooted/patch installed
                elif boot_state == self.profile["regions"]["boot"]["stock_sha256"]:
                    boot_mode = "force" if root else "temproot"
                elif boot_state is None and not root:
                    # On a factory unit, the boot region is intentionally not
                    # readable until Dirty COW has provided temporary root.
                    boot_mode = "temproot"
                else:
                    raise InstallerError(f"unknown boot state: {boot_state}")
            if boot_mode in ("force", "temproot") and not root and boot_mode != "temproot":
                raise InstallerError("boot patching requires root ADB (use --boot-mode temproot on a factory unit)")

            if boot_mode == "temproot":
                # Resolve and hash-check the helpers before asking for the
                # destructive confirmation token. This guarantees that a
                # missing payload cannot leave the user at a dead prompt.
                self._temproot_inputs()

            if boot_mode == "skip" and not root and not self.dry_run:
                raise InstallerError("--boot-mode skip requires root ADB")

        # Resolve all files used by the install before asking for the
        # destructive confirmation token. This prevents a late missing-APK or
        # missing-core failure after boot/system files have already changed.
        self.validate_install_artifacts(boot_mode, require_ppsspp=ppsspp_present is not True)

        # Plan
        self.msg("\n=== vamanOS install plan ===")
        plans = [
            "1. Patch boot to root ADB (region 0x1D80000, 6 MiB)" if boot_mode in ("force", "temproot") else "1. Boot already patched (skip)",
            "2. Install Android boot splash (/system/media/bootanimation.zip; no raw logo-region write)",
            "3. Install /system/xbin/su + /system/xbin/find (root)",
            "4. Deploy PS202 boot helper + performance profile (/data/local/)",
            ("5. Install ES + RetroArch; keep the existing PPSSPP app"
             if ppsspp_present is True else
             "5. Install ES + RetroArch; install bundled PPSSPP only if missing"),
            "6. Install RetroArch cores + menu music + V2 CODY theme + tune shared config (preserves input bindings)",
            "7. Back up removable apps, deploy launcher map + PS202 SD layout",
            "8. Remove old apps/game launcher + set ES as HOME",
        ]
        for p in plans:
            self.msg(f"  {p}")
        self.msg("  Only the reviewed root boot region may be written; no logo region, preloader/lk/nvram, or user ROMs/saves/states/input maps are touched.")
        token = Confirmation.request(self.serial, confirmed)

        # Firmware phase
        if self.known:
            if boot_mode == "temproot":
                self.msg("[1/8] Boot patching via dirtycow temp-root...")
                self.bootstrap_temproot(self.art("boot_patched"))
                root = True
            elif boot_mode == "force":
                self.msg("[1/8] Boot patching (root ADB)...")
                self.write_region("boot", self.art("boot_patched"))
                self.verify_readback("boot")
                self.adb.reboot()
                self.adb.wait_for_device(timeout=300)
                if not self.adb.is_root():
                    raise InstallerError("root ADB not active after boot reboot")
                root = True
            if self.known:
                self.msg("[2/8] Installing Android boot splash...")
                self.install_android_bootanimation()

        if not root and not self.dry_run:
            raise InstallerError("non-root ADB cannot complete the vamanOS setup")

        if root and not self.dry_run:
            self.preserved_system_digests = self.snapshot_preserved_system_files("before")

        # Software phase
        self.msg("[3/8] Installing su + system binaries (find)...")
        self.install_su(self.art("su"))
        self.install_aux_binaries()
        self.msg("[4/8] Deploying boot helper + performance profile...")
        self.deploy_boot_helper(self.payload_file("boot_helper"),
                                self.payload_file("performance_profile"))
        self.msg("[5/8] Installing apps (this can take a few minutes)...")
        self.install_apks()
        self.msg("[6/8] Installing cores + config...")
        self.ensure_sd_layout()
        self.install_cores(self.core_files())
        self.install_frontend_music()
        self.install_cody_theme()
        self.install_retroarch_config(self.payload_file("retroarch_baseline"))
        self.msg("[7/8] Deploying launch map + layout...")
        self.deploy_launchers(self.payload_file("launcher_config"))
        self.msg("[8/8] Backing up/removing old apps + HOME...")
        self.apply_packages()
        self.set_home()

        self.msg("\nVerifying install...")
        self.verify(require_root=True)
        write_json(self.run_dir / "result.json", {"status": "installed", "boot_mode": boot_mode,
                                                  "log": str(self.run_dir / "installer.log")})
        self.msg(f"\nDone. Details in {self.run_dir}")

    def install_splash(self, confirmed: Optional[str] = None) -> None:
        """Install only the Android boot animation; never inspect or write boot flash."""
        self.print_identity()
        if not self.known and not self.dry_run:
            raise InstallerError("Android boot splash is only supported on PS202_00001")
        if not self.dry_run and not self.adb.is_root():
            raise InstallerError("splash-only install requires root ADB; no boot image changes were made")

        self.msg("\n=== vamanOS Android boot splash plan ===")
        self.msg("  Replace /system/media/bootanimation.zip with the video animation")
        self.msg("  Preserve the existing file as /system/media/bootanimation.zip.vamanos-previous")
        self.msg("  Do not read or write any raw flash region")
        Confirmation.request(self.serial, confirmed)
        self.msg("Installing Android boot splash...")
        self.install_android_bootanimation()
        if not self.dry_run:
            self.msg(f"Android boot splash verified: {self.verify_android_bootanimation()}")

    def log_path(self) -> Path:
        return self.run_dir / "installer.log"

    def assemble(self, output: Optional[Path] = None) -> Path:
        """Assemble a self-contained dist zip from all bundled artifacts."""
        if output is None:
            output = INSTALLER_DIR / "dist" / "vamanOS-PS202-bundle.zip"
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="vamanos-bundle-"))
        bundle = tmp / "payload"
        try:
            # Keep the engine, manifest, profile, launchers, and README beside
            # the payload so an extracted release can run by itself.
            for name in ("vamanos_installer.py", "manifest.json", "device-profile.json",
                         "README.md", "ADB-SETUP.md", "install.sh", "install.ps1",
                         "install.cmd", "recover-bootloop.sh", "AGENTS.md"):
                shutil.copy2(INSTALLER_DIR / name, tmp / name)
            (tmp / "assets").mkdir()
            shutil.copy2(INSTALLER_DIR / "assets" / "vamanos_boot.webp",
                         tmp / "assets" / "vamanos_boot.webp")
            (bundle / "apks").mkdir(parents=True)
            (bundle / "cores").mkdir(parents=True)
            (bundle / "boot").mkdir(parents=True)
            (bundle / "bin").mkdir(parents=True)
            (bundle / "music").mkdir(parents=True)
            (bundle / "themes").mkdir(parents=True)
            # APKs
            for key in ("emulationstation", "ppsspp"):
                src = self.art(key)
                shutil.copy2(src, bundle / "apks" / f"{key}.apk")
            # cores
            for short, core in self.core_files().items():
                shutil.copy2(core, bundle / "cores" / core.name)
            # boot region images + Android userspace boot splash
            for key, filename in (("boot_stock", "boot_stock.img"),
                                  ("boot_patched", "boot_patched.img"),
                                  ("android_bootanimation", "android_bootanimation.zip")):
                shutil.copy2(self.art(key), bundle / "boot" / filename)
            for key in ("patched_adbd", "find", "su", "temproot_cowtest", "temproot_blockdump"):
                source = self.art(key)
                shutil.copy2(source, bundle / "bin" / source.name)
            for name, source in self.frontend_music_files().items():
                shutil.copy2(source, bundle / "music" / name)
            shutil.copy2(self.art("cody_theme"), bundle / "themes" / "EPIC-CODY.zip")
            # payload configs
            for name in ("ps202-init.sh", "retroarch-baseline.cfg", "android_launchers.xml"):
                shutil.copy2(self.payload_file({"ps202-init.sh": "init_script",
                                                "retroarch-baseline.cfg": "retroarch_baseline",
                                                "android_launchers.xml": "launcher_config"}[name]), bundle / name)
            shutil.copy2(self.payload_file("boot_helper"), bundle / "ps202-boot.sh")
            shutil.copy2(self.payload_file("performance_profile"), bundle / "ps202-performance.sh")

            # write a bundle manifest with hashes
            manifest_out = {}
            for base, _dirs, files in os.walk(bundle):
                for f in files:
                    p = Path(base) / f
                    rel = str(p.relative_to(tmp))
                    manifest_out[rel] = sha256_file(p)
            write_json(tmp / "bundle-sha256.json", manifest_out)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(tmp):
                    for f in files:
                        p = Path(root) / f
                        zf.write(p, p.relative_to(tmp).as_posix())
            self.msg(f"Assembled {output} ({output.stat().st_size // (1024*1024)} MiB)")
            return output
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Confirmation:
    @staticmethod
    def token(action: str, serial: str) -> str:
        tail = serial[-8:] if "-" in serial or serial.isalnum() else "PS202"
        return f"{action}-{tail}"

    @staticmethod
    def request(serial: str, supplied: Optional[str]) -> None:
        token = Confirmation.token("INSTALL", serial)
        if supplied:
            if supplied == token:
                return
            raise InstallerError(f"confirmation did not match: expected {token}")
        print(f"\nType {token} to install vamanOS, or anything else to abort.")
        try:
            choice = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            raise InstallerError("confirmation aborted")
        if choice != token:
            raise InstallerError("confirmation did not match; no changes were made")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vamanos",
                                     description="vamanOS for R36S PS202 installer")
    parser.add_argument("--adb", default="adb", help="path to adb binary")
    parser.add_argument("--serial", help="ADB serial when more than one device")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running them")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--bundle", type=Path, default=None,
                        help="run from an extracted `assemble` bundle directory instead of the workspace")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="read-only device health check")
    p_doc.set_defaults(func="doctor")

    p_splash = sub.add_parser("splash", help="install only the Android boot animation")
    p_splash.add_argument("--confirm", help="non-interactive confirmation token")
    p_splash.set_defaults(func="splash")

    p_inst = sub.add_parser("install", help="install vamanOS")
    boot_group = p_inst.add_mutually_exclusive_group()
    boot_group.add_argument("--boot-mode", choices=["auto", "force", "temproot", "skip"],
                             default="auto",
                             help="auto: skip if already rooted, temproot on stock factory. force: rewrite patched boot. "
                                  "temproot: use dirtycow bootstrap on a factory unit. skip: assume already rooted.")
    boot_group.add_argument("--temproot", dest="legacy_temproot", action="store_true",
                            help="legacy alias for --boot-mode temproot")
    p_inst.add_argument("--confirm", help="non-interactive confirmation token")
    p_inst.set_defaults(func="install")

    p_ver = sub.add_parser("verify", help="verify a finished install")
    p_ver.set_defaults(func="verify")

    p_as = sub.add_parser("assemble", help="build a self-contained distribution zip")
    p_as.add_argument("--output")
    p_as.set_defaults(func="assemble")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        installer = VamanOSInstaller(adb=args.adb, serial=args.serial,
                                     dry_run=args.dry_run, quiet=args.quiet,
                                     bundle_root=args.bundle)
        if args.func == "doctor":
            installer.doctor()
        elif args.func == "splash":
            installer.install_splash(confirmed=args.confirm)
        elif args.func == "install":
            boot_mode = "temproot" if args.legacy_temproot else args.boot_mode
            installer.install(boot_mode=boot_mode, confirmed=args.confirm)
        elif args.func == "verify":
            installer.verify(require_root=True)
        elif args.func == "assemble":
            installer.assemble(output=Path(args.output) if args.output else None)
        return 0
    except InstallerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
