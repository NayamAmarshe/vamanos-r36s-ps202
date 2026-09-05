import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vamanos_installer as inst

ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "tools" / "ps202-installer"
MANIFEST = inst.load_json(INSTALLER / "manifest.json")
PROFILE = inst.load_json(INSTALLER / "device-profile.json")


class HomeTests(unittest.TestCase):
    def test_uses_kitkat_home_intent(self):
        commands = []

        class FakeAdb:
            def shell(self, command, timeout=300, check=True):
                commands.append(command)
                return inst.CommandResult(
                    0,
                    "Starting: Intent { cat=[android.intent.category.HOME] }\n"
                    "Activity: com.ps202.nayamamarshe.emulationstation/.PS202HomeActivity\n",
                    "",
                )

        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.adb = FakeAdb()
        installer.set_home()
        self.assertEqual([inst.HOME_INTENT], commands)
        self.assertNotIn("set-home-activity", commands[0])


class ManifestProfileTests(unittest.TestCase):
    def test_emulationstation_artifact_is_the_suspend_fix_build(self):
        apk = (
            INSTALLER / MANIFEST["artifacts"]["emulationstation"]["source"]
        ).resolve()
        if not apk.is_file():
            self.skipTest("packaged EmulationStation APK not present")
        self.assertEqual(
            MANIFEST["artifacts"]["emulationstation"]["sha256"], inst.sha256_file(apk)
        )
        with zipfile.ZipFile(apk) as archive:
            dex = archive.read("classes.dex")
        self.assertIn(b"pauseForSuspend", dex)
        self.assertIn(b"resumeAfterSuspend", dex)
        self.assertIn(b"splash wallpaper repaired", dex)

    def test_retroarch_is_the_pinned_api19_build(self):
        artifact = MANIFEST["artifacts"]["retroarch"]
        self.assertNotIn("source", artifact)
        self.assertEqual("downloads/retroarch-ra32-1.20.0.apk", artifact["download"])
        self.assertEqual(
            "https://buildbot.libretro.com/stable/1.20.0/android/RetroArch_ra32.apk",
            artifact["url"],
        )
        self.assertEqual("com.retroarch.ra32", artifact["package"])
        self.assertEqual("1.20.0_GIT", artifact["version_name"])
        self.assertEqual(11, artifact["version_code"])
        self.assertEqual(
            "cbcf1cf1aac3e9afe447051cae12ee069039dbc22132d92af856cab26cae45df",
            artifact["sha256"],
        )

    def test_profile_is_ps202_00001(self):
        self.assertEqual("PS202_00001", PROFILE["id"])
        self.assertEqual("armeabi-v7a", PROFILE["identity"]["abi"])

    def test_retroarch_baseline_binds_ps202_volume_keys(self):
        baseline = (INSTALLER / "payload/retroarch-baseline.cfg").read_text(
            encoding="utf-8"
        )
        self.assertIn('input_volume_up = "volumeup"', baseline)
        self.assertIn('input_volume_down = "volumedown"', baseline)
        self.assertIn('audio_driver = "opensl"', baseline)

        helper = (INSTALLER / "payload/ps202-boot.sh").read_text(encoding="utf-8")
        self.assertIn('input_volume_up = "volumeup"', helper)
        self.assertIn('input_volume_down = "volumedown"', helper)
        self.assertIn('audio_driver = "opensl"', helper)
        self.assertIn("audio_driver\\ =\\ *)", helper)

    def test_retroarch_autoconfig_binds_verified_mtk_kpd_profile(self):
        profile_path = INSTALLER / MANIFEST["payload"]["retroarch_autoconfig"]
        profile = inst.parse_cfg(profile_path.read_text(encoding="utf-8"))
        self.assertEqual('"android"', profile["input_driver"])
        self.assertEqual('"mtk-kpd"', profile["input_device"])
        for key, value in {
            "input_up_btn": '"19"',
            "input_down_btn": '"20"',
            "input_left_btn": '"21"',
            "input_right_btn": '"22"',
            "input_select_btn": '"109"',
            "input_start_btn": '"108"',
            "input_l_x_plus_axis": '"+0"',
            "input_l_y_plus_axis": '"+1"',
            "input_r_x_plus_axis": '"+2"',
            "input_r_y_plus_axis": '"+3"',
        }.items():
            self.assertEqual(value, profile[key], key)

    def test_boot_region_offsets_are_exact(self):
        boot = PROFILE["regions"]["boot"]
        self.assertEqual(0x01D80000, boot["offset"])  # 30932992 bytes = 60416 sectors
        self.assertEqual(6 * 1024 * 1024, boot["length"])

    def test_splash_is_android_bootanimation_not_raw_logo_region(self):
        self.assertNotIn("logo", PROFILE["regions"])
        self.assertNotIn("logo_custom", MANIFEST["artifacts"])
        self.assertEqual(
            "/system/media/bootanimation.zip", PROFILE["android_boot_splash"]["path"]
        )
        source = (INSTALLER / "vamanos_installer.py").read_text(encoding="utf-8")
        self.assertNotIn('write_region("logo"', source)
        self.assertNotIn("logo_custom", source)

    def test_android_bootanimation_uses_the_pinned_video_conversion(self):
        artifact = MANIFEST["artifacts"]["android_bootanimation"]
        animation = (INSTALLER / artifact["source"]).resolve()
        if not animation.is_file():
            self.skipTest("Android bootanimation artifact not present")
        self.assertEqual(artifact["sha256"], inst.sha256_file(animation))
        with zipfile.ZipFile(animation) as archive:
            names = archive.namelist()
            self.assertEqual("desc.txt", names[0])
            self.assertEqual("part1/final.jpg", names[-1])
            self.assertEqual(126, len(names))
            self.assertEqual(
                b"640 480 15\np 1 0 part0\np 0 0 part1\n", archive.read("desc.txt")
            )
            self.assertEqual(
                artifact["reveal_frame_count"],
                len([name for name in names if name.startswith("part0/")]),
            )
            self.assertEqual(
                zipfile.ZIP_STORED, archive.getinfo("desc.txt").compress_type
            )
            for name in names[1:]:
                self.assertEqual(
                    zipfile.ZIP_STORED, archive.getinfo(name).compress_type
                )

        self.assertEqual("vamanos_boot.mp4", artifact["source_video_name"])

    def test_v2_cody_theme_is_pinned_and_importable(self):
        artifact = MANIFEST["artifacts"]["cody_theme"]
        theme = (INSTALLER / artifact["source"]).resolve()
        if not theme.is_file():
            self.skipTest("V2 CODY theme archive not present")
        self.assertEqual(artifact["sha256"], inst.sha256_file(theme))
        with zipfile.ZipFile(theme) as archive:
            names = archive.namelist()
            self.assertIn("theme.xml", names)
            self.assertFalse(
                any(name.startswith("es-theme-CODY-DARKTECK-main/") for name in names)
            )
            self.assertIn(
                b"<formatVersion>7</formatVersion>", archive.read("theme.xml")
            )

    def test_frontend_music_is_present_and_checksum_pinned(self):
        artifact = MANIFEST["artifacts"]["frontend_music"]
        root = (INSTALLER / artifact["source"]).resolve()
        self.assertTrue(root.is_dir())
        self.assertEqual(
            set(artifact["files"]), {path.name for path in root.glob("*.ogg")}
        )
        for name, expected in artifact["files"].items():
            self.assertEqual(expected, inst.sha256_file(root / name))

    def test_boot_patch_is_live_and_preserves_the_kernel(self):
        stock = (ROOT / "ps202-project/backups/boot-images/boot-stock.img").resolve()
        if not stock.is_file():
            self.skipTest("reference boot image not present")
        find_binary = INSTALLER / "release-inputs/bin/find"
        init_script = INSTALLER / "payload/ps202-init.sh"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "boot-live-patched.img"
            inst.patch_boot_image_file(
                stock, output, find_binary, init_script, PROFILE
            )
            original = stock.read_bytes().ljust(PROFILE["regions"]["boot"]["length"], b"\0")
            patched = output.read_bytes()
            layout = inst._boot_layout(original, PROFILE["regions"]["boot"]["length"])
            self.assertEqual(
                original[layout["page"] : layout["ramdisk_offset"]],
                patched[layout["page"] : layout["ramdisk_offset"]],
            )
            entries = inst._parse_newc(inst._boot_layout(
                patched, PROFILE["regions"]["boot"]["length"]
            )["cpio"])
            files = {name: body for name, _mode, body in entries}
            self.assertIn("sbin/find", files)
            self.assertIn("sbin/ps202-init.sh", files)
            self.assertEqual(
                files["sbin/adbd"],
                inst.patch_adbd_bytes(
                    files["sbin/adbd"], PROFILE["boot_patch"]["adbd"]
                ),
            )

    def test_boot_patch_rejects_an_unknown_adbd(self):
        with self.assertRaises(inst.InstallerError):
            inst.patch_adbd_bytes(b"not a reviewed adbd", PROFILE["boot_patch"]["adbd"])

    def test_known_boot_image_pairs_are_release_artifacts(self):
        self.assertNotIn("boot_stock", MANIFEST["artifacts"])
        self.assertNotIn("boot_patched", MANIFEST["artifacts"])
        self.assertNotIn("patched_adbd", MANIFEST["artifacts"])
        self.assertEqual(
            ["V10", "V11/V12"],
            [variant["name"] for variant in MANIFEST["boot_image_variants"]],
        )
        for variant in MANIFEST["boot_image_variants"]:
            self.assertIn(variant["stock"], MANIFEST["artifacts"])
            self.assertIn(variant["patched"], MANIFEST["artifacts"])
        self.assertIn("backup_path", PROFILE["regions"]["boot"])
        self.assertIn("sites", PROFILE["boot_patch"]["adbd"])

    def test_known_boot_pairs_are_valid_and_preserve_the_kernel(self):
        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.manifest = MANIFEST
        installer.profile = PROFILE
        installer.bundle_root = None
        installer.bundle_hashes = None
        installer.run_dir = Path(tempfile.mkdtemp())
        installer.msg = lambda *args, **kwargs: None
        installer.log = lambda *args, **kwargs: None

        installer.validate_known_boot_images()
        for variant in MANIFEST["boot_image_variants"]:
            stock = installer.art(variant["stock"])
            patched = installer.art(variant["patched"])
            original = inst.sha256_file(stock)
            selected, digest, _name = installer.select_known_boot_patch(stock, original)
            self.assertEqual(inst.sha256_file(patched), digest)
            self.assertEqual(patched.read_bytes(), selected.read_bytes())

    def test_unknown_boot_image_uses_live_patch_fallback(self):
        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.manifest = MANIFEST
        installer.profile = PROFILE
        installer.bundle_root = None
        installer.bundle_hashes = None
        installer.run_dir = Path(tempfile.mkdtemp())
        installer.msg = lambda *args, **kwargs: None
        installer.log = lambda *args, **kwargs: None

        stock = installer.art("boot_v11_v12_stock")
        altered = installer.run_dir / "unknown-boot.img"
        data = bytearray(stock.read_bytes())
        data[-1] ^= 1  # Keep the image valid, but make its full hash unknown.
        altered.write_bytes(data)
        self.assertIsNone(
            installer.select_known_boot_patch(altered, inst.sha256_file(altered))
        )
        output = installer.run_dir / "live-fallback.img"
        installer.build_live_patched_boot(altered, output)
        self.assertEqual("PATCHED", installer.classify_boot_image(output))

    def test_manifest_sources_are_self_contained(self):
        for name, artifact in MANIFEST["artifacts"].items():
            source = artifact.get("source")
            if not source:
                continue
            source_path = Path(source)
            self.assertFalse(source_path.is_absolute(), name)
            self.assertNotIn("..", source_path.parts, name)
            self.assertTrue((INSTALLER / source_path).exists(), name)

    def test_temproot_helpers_are_pinned_and_available(self):
        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.manifest = MANIFEST
        installer.bundle_root = None
        expected = {
            "temproot_cowtest": "da2884341bd32ad78f510f2db21d9b2aedae2b2707f997b9dd57127e487f76fa",
            "temproot_blockdump": "0f17354c875aa6a38db1a4a6f7475712810e234a72e6f1450e799585c457aff0",
        }
        for key, digest in expected.items():
            path = installer.art(key)
            self.assertTrue(path.is_file(), path)
            self.assertEqual(digest, inst.sha256_file(path))

    def test_boot_helper_preserves_stock_controller_keylayout(self):
        helper = (INSTALLER / "payload/ps202-boot.sh").read_text(encoding="utf-8")
        self.assertIn("preserve the stock mtk-kpd keylayout", helper)
        self.assertNotIn('grep -v "key 316"', helper)
        self.assertNotIn("key 316   F1", helper)
        self.assertNotIn("com.ps202.shell", helper)
        self.assertNotIn("vamanos-tmp", helper)
        self.assertNotIn('cp -f "$SOURCE"', helper)

    def test_performance_profile_is_guarded_and_reversible(self):
        profile = (INSTALLER / "payload/ps202-performance.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("restore", profile)
        self.assertIn("/proc/sys/vm/swappiness", profile)
        self.assertIn("/sys/block/mmcblk1/queue/read_ahead_kb", profile)
        self.assertNotIn("scaling_governor", profile)
        self.assertNotIn("scaling_setspeed", profile)
        self.assertNotIn("/system/usr/keylayout/mtk-kpd.kl", profile)

    def test_shell_is_not_an_installer_artifact_and_emulator_is_protected(self):
        self.assertNotIn("shell", MANIFEST["artifacts"])
        self.assertIn(
            "com.ps202.emulationstation", PROFILE["debloat"]["remove"]
        )
        self.assertNotIn(
            "com.ps202.emulationstation", PROFILE["debloat"]["protected"]
        )
        self.assertIn("com.ps202.shell", PROFILE["debloat"]["remove"])
        self.assertIn("com.xugame.gameconsoleMenu", PROFILE["debloat"]["remove"])
        self.assertNotIn("com.xugame.gameconsole", PROFILE["debloat"]["remove"])
        self.assertIn("com.xugame.gameconsole", PROFILE["debloat"]["protected"])

    def test_seven_cores_referenced_by_launchers_are_in_manifest(self):
        # The complete device launcher map needs every packaged core.
        cores = MANIFEST["cores"]
        for name in (
            "fceumm",
            "snes9x",
            "gambatte",
            "gpsp",
            "pcsx_rearmed",
            "picodrive",
            "mgba",
        ):
            self.assertIn(name, cores)
        self.assertEqual("tgbdual_libretro_android.so", cores["gambatte"])

    def test_every_supported_system_has_a_pinned_launcher_and_core(self):
        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.manifest = MANIFEST
        installer.bundle_root = None
        installer.bundle_hashes = None
        installer.log = lambda *args, **kwargs: None
        cores = installer.core_files()
        installer.validate_launcher_config(
            INSTALLER / "payload/android_launchers.xml", cores
        )
        self.assertEqual(22, len(MANIFEST["supported_systems"]))
        self.assertEqual(15, len(cores))

    def test_rom_layout_matches_frontend_paths(self):
        layout = set(MANIFEST["sd_layout"])
        self.assertIn("roms/CPS1", layout)
        self.assertIn("roms/COLECOVISION", layout)
        self.assertIn(
            "Android/data/com.ps202.nayamamarshe.emulationstation/files/themes",
            layout,
        )
        self.assertNotIn("ps202/roms/nes", layout)

    def test_api19_core_source_precedes_newer_buildbot_inputs(self):
        sources = MANIFEST["core_sources"]
        self.assertEqual("release-inputs/cores-api19", sources[0])
        launcher = (INSTALLER / "payload/android_launchers.xml").read_text(
            encoding="utf-8"
        )
        self.assertIn('core="tgbdual_libretro_android.so"', launcher)
        self.assertIn('core="gpsp_libretro_android.so"', launcher)

    def test_debloat_protected_contains_critical_packages(self):
        protected = set(PROFILE["debloat"]["protected"])
        for pkg in (
            "com.android.systemui",
            "com.android.phone",
            "com.android.bluetooth",
            "com.ps202.nayamamarshe.emulationstation",
            "com.retroarch.ra32",
            "org.ppsspp.ppsspp",
        ):
            self.assertIn(pkg, protected)


class MergeCfgTests(unittest.TestCase):
    def test_preserves_manual_input_bindings(self):
        existing = 'input_player1_a = "5"\nvideo_driver = "gl"\n'
        overlay = (
            'input_player1_a = "99"\nvideo_driver = "gles"\naudio_latency = "96"\n'
        )
        merged = inst.merge_cfg(existing, overlay)
        self.assertIn('input_player1_a = "5"', merged)  # user remap kept
        self.assertIn('video_driver = "gles"', merged)  # non-personal key merged
        self.assertIn('audio_latency = "96"', merged)  # new key appended

    def test_adds_new_keys_and_leaves_unknown_lines(self):
        existing = 'content_show_history = "true"\n'
        overlay = (
            'content_show_history = "false"\nnotification_show_autoconfig = "false"\n'
        )
        merged = inst.merge_cfg(existing, overlay)
        self.assertIn('content_show_history = "false"', merged)
        self.assertIn('notification_show_autoconfig = "false"', merged)

    def test_replaces_an_old_audio_driver_without_touching_input(self):
        existing = 'audio_driver = "rsound"\ninput_player1_a = "5"\n'
        overlay = 'audio_driver = "opensl"\ninput_player1_a = "99"\n'
        merged = inst.merge_cfg(existing, overlay)
        self.assertIn('audio_driver = "opensl"', merged)
        self.assertIn('input_player1_a = "5"', merged)

    def test_seeds_ps202_pad_when_stock_dpad_is_unbound(self):
        existing = (
            'input_player1_a_btn = "96"\n'
            'input_player1_b_btn = "97"\n'
            'input_player1_up_btn = "nul"\n'
            'input_player1_down_btn = "nul"\n'
            'input_player1_left_btn = "nul"\n'
            'input_player1_right_btn = "nul"\n'
        )
        merged = inst.apply_ps202_input_defaults(existing, existing)
        self.assertIn('input_player1_up_btn = "19"', merged)
        self.assertIn('input_player1_right_btn = "22"', merged)
        self.assertIn('input_quit_gamepad_combo = "4"', merged)

    def test_ps202_pad_defaults_never_replace_existing_dpad_map(self):
        existing = (
            'input_player1_up_btn = "7"\n'
            'input_player1_down_btn = "8"\n'
            'input_player1_left_btn = "9"\n'
            'input_player1_right_btn = "10"\n'
        )
        merged = inst.apply_ps202_input_defaults(existing, existing)
        self.assertEqual(existing, merged)


class AdbClientTests(unittest.TestCase):
    def test_keeps_serial_and_install_flags(self):
        calls = []

        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                calls.append(list(args))
                return inst.CommandResult(0, "Success\n", "")

        client = inst.AdbClient("adb", "SERIAL", RecordingRunner())
        client.install_apk(Path("/tmp/a.apk"))
        self.assertEqual("adb", calls[0][0])
        self.assertIn("-s", calls[0])
        self.assertIn("SERIAL", calls[0])
        self.assertIn("install", calls[0])
        self.assertIn("/tmp/a.apk", calls[0])

    def test_can_install_large_apk_directly_to_sd(self):
        calls = []

        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                calls.append(list(args))
                if "shell" in args and "pm install" in args[-1]:
                    return inst.CommandResult(0, "Success\n", "")
                return inst.CommandResult(0, "", "")

        client = inst.AdbClient("adb", "SERIAL", RecordingRunner())
        client.install_apk(Path("/tmp/retroarch.apk"), to_sd=True)
        self.assertIn("push", calls[0])
        self.assertIn("-s", calls[1][-1])
        self.assertIn("pm install", calls[1][-1])
        self.assertIn("rm -f", calls[2][-1])

    def test_recovers_completed_push_when_old_adbd_returns_eof(self):
        calls = []

        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                calls.append(list(args))
                if "push" in args:
                    return inst.CommandResult(1, "", "failed to read copy response: EOF")
                return inst.CommandResult(0, "12\n", "")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "core.so"
            source.write_bytes(b"0123456789ab")
            client = inst.AdbClient("adb", "SERIAL", RecordingRunner())
            client.push(source, "/storage/sdcard1/retroarch/cores/core.so")

        self.assertEqual(2, len(calls))
        self.assertIn("wc -c", calls[1][-1])

    def test_retries_incomplete_push_after_eof(self):
        calls = []
        sizes = iter((3, 12))

        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                calls.append(list(args))
                if "push" in args:
                    return inst.CommandResult(1, "", "failed to read copy response: EOF")
                return inst.CommandResult(0, f"{next(sizes)}\n", "")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "core.so"
            source.write_bytes(b"0123456789ab")
            client = inst.AdbClient("adb", "SERIAL", RecordingRunner())
            client.push(source, "/storage/sdcard1/retroarch/cores/core.so")

        self.assertEqual(4, len(calls))
        self.assertEqual(2, sum("push" in call for call in calls))

    def test_reads_serial_for_confirmation_when_available(self):
        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                self.args = list(args)
                return inst.CommandResult(0, "0123456789ABCDEF\n", "")

        runner = RecordingRunner()
        client = inst.AdbClient("adb", runner=runner)
        self.assertEqual("0123456789ABCDEF", client.get_serialno())
        self.assertIn("get-serialno", runner.args)

    def test_parses_old_android_df_available_column(self):
        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                return inst.CommandResult(
                    0,
                    "Filesystem 1K-blocks Used Available Use% Mounted on\n"
                    "/dev/block 100000 70000 30000 70% /data\n",
                    "",
                )

        client = inst.AdbClient("adb", runner=RecordingRunner())
        self.assertEqual(30000 * 1024, client.free_bytes("/data"))

    def test_parses_ps202_human_readable_df_free_column(self):
        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                return inst.CommandResult(
                    0,
                    "Filesystem               Size     Used     Free   Blksize\n"
                    "/data                    1.4G     1.4G    83.8M   4096\n",
                    "",
                )

        client = inst.AdbClient("adb", runner=RecordingRunner())
        self.assertEqual(int(83.8 * 1024 * 1024), client.free_bytes("/data"))


class BundleTests(unittest.TestCase):
    def test_discovers_an_extracted_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "manifest.json",
                "device-profile.json",
                "vamanos_installer.py",
                "payload/apks/emulationstation.apk",
                "bundle-sha256.json",
            ):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x")
            self.assertEqual(root.resolve(), inst.discover_bundle_root(root))


class UpdateTests(unittest.TestCase):
    def test_update_parser_defaults_to_main_and_auto_boot_mode(self):
        args = inst._build_arg_parser().parse_args(["update"])
        self.assertEqual("update", args.func)
        self.assertEqual(inst.UPDATE_REF, args.ref)
        self.assertEqual("auto", args.boot_mode)
        self.assertFalse(args.legacy_temproot)

    def test_update_api_url_quotes_ref_and_nested_path(self):
        self.assertEqual(
            "https://api.github.com/repos/NayamAmarshe/vamanos-r36s-ps202/"
            "contents/payload/bin?ref=release%2F2026",
            inst._update_api_url("payload/bin", "release/2026"),
        )

    def test_updated_install_command_forwards_global_and_install_options(self):
        args = inst._build_arg_parser().parse_args(
            [
                "--adb",
                "/opt/android/adb",
                "--serial",
                "PS202-1234",
                "--dry-run",
                "--quiet",
                "update",
                "--boot-mode",
                "skip",
                "--confirm",
                "INSTALL-1234",
            ]
        )
        command = inst._updated_install_command(
            args, Path("/tmp/latest/vamanos_installer.py"), Path("/tmp/bundle")
        )
        self.assertEqual(
            [
                sys.executable,
                "/tmp/latest/vamanos_installer.py",
                "--bundle",
                "/tmp/bundle",
                "--adb",
                "/opt/android/adb",
                "--serial",
                "PS202-1234",
                "--dry-run",
                "--quiet",
                "install",
                "--boot-mode",
                "skip",
                "--confirm",
                "INSTALL-1234",
            ],
            command,
        )

    def test_update_reuses_current_bundle_and_cleans_temporary_source(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            for relative in (
                "manifest.json",
                "device-profile.json",
                "vamanos_installer.py",
                "payload/apks/emulationstation.apk",
                "bundle-sha256.json",
            ):
                target = bundle / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x")

            args = inst._build_arg_parser().parse_args(
                ["--bundle", str(bundle), "update"]
            )
            temporary_source = {}

            def write_update(_files, root):
                temporary_source["root"] = root.parent
                (root / "vamanos_installer.py").write_text(
                    "print('latest')\n", encoding="utf-8"
                )
                (root / "manifest.json").write_text(
                    '{"manifest_version": "latest"}\n', encoding="utf-8"
                )
                (root / "device-profile.json").write_text(
                    '{"id": "PS202_00001"}\n', encoding="utf-8"
                )

            child_result = type("ChildResult", (), {"returncode": 7})()
            with patch.object(inst, "_collect_update_files", return_value={}), patch.object(
                inst, "_download_update_files", side_effect=write_update
            ), patch.object(inst.subprocess, "run", return_value=child_result) as run:
                self.assertEqual(7, inst.update_and_install(args))

            command = run.call_args[0][0]
            self.assertIn("--bundle", command)
            self.assertEqual(str(bundle.resolve()), command[command.index("--bundle") + 1])
            self.assertEqual("install", command[-1])
            self.assertFalse(temporary_source["root"].exists())


class DownloadTests(unittest.TestCase):
    def test_downloads_retroarch_to_cache_and_checks_hash(self):
        data = b"known-good-retroarch-apk"

        class FakeResponse:
            def __init__(self):
                self.remaining = data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size):
                chunk, self.remaining = self.remaining[:size], self.remaining[size:]
                return chunk

        with tempfile.TemporaryDirectory() as directory:
            installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            installer.manifest = {
                "artifacts": {
                    "retroarch": {
                        "download": "downloads/retroarch.apk",
                        "url": "https://example.invalid/retroarch.apk",
                        "sha256": inst.hashlib.sha256(data).hexdigest(),
                    }
                }
            }
            installer.bundle_root = Path(directory)
            installer.msg = lambda *args, **kwargs: None
            with patch.object(inst, "urlopen", return_value=FakeResponse()) as open_url:
                result = installer.art("retroarch")
                self.assertEqual(data, result.read_bytes())

        open_url.assert_called_once()
        self.assertEqual(
            "https://example.invalid/retroarch.apk", open_url.call_args.args[0].full_url
        )


class AppInstallTests(unittest.TestCase):
    def _installer(self, directory, ppsspp_present):
        installed = []

        class FakeAdb:
            def package_path(self, package):
                if package == inst.PPSSPP_PACKAGE and ppsspp_present:
                    return "/data/app/org.ppsspp.ppsspp-1.apk"
                return None

            def package_is_on_sd(self, package):
                return False

            def install_apk(self, apk, timeout=1200, to_sd=False):
                installed.append((Path(apk).name, to_sd))

        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.adb = FakeAdb()
        installer.msg = lambda *args, **kwargs: None
        installer.art = lambda key: Path(directory) / f"{key}.apk"
        installer.installed_package_matches = lambda key: False
        for key in ("emulationstation", "retroarch", "ppsspp"):
            (Path(directory) / f"{key}.apk").write_bytes(b"apk")
        return installer, installed

    def test_keeps_existing_ppsspp(self):
        with tempfile.TemporaryDirectory() as directory:
            installer, installed = self._installer(directory, ppsspp_present=True)
            installer.install_apks()
        self.assertEqual(
            [("emulationstation.apk", False), ("retroarch.apk", True)], installed
        )

    def test_installs_bundled_ppsspp_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            installer, installed = self._installer(directory, ppsspp_present=False)
            installer.install_apks()
        self.assertEqual(
            [
                ("emulationstation.apk", False),
                ("retroarch.apk", True),
                ("ppsspp.apk", False),
            ],
            installed,
        )

    def test_skips_exact_existing_es_and_retroarch(self):
        with tempfile.TemporaryDirectory() as directory:
            installer, installed = self._installer(directory, ppsspp_present=True)
            installer.installed_package_matches = lambda key: (
                key in {"emulationstation", "retroarch"}
            )
            installer.adb.package_is_on_sd = lambda package: True
            installer.install_apks()
        self.assertEqual([], installed)


class CoreInstallTests(unittest.TestCase):
    def test_cores_are_kept_on_sd_and_pushed_into_private_runtime_dir(self):
        pushes = []

        class FakeAdb:
            def push(self, local, remote, timeout=600):
                pushes.append((Path(local), remote))

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fceumm_libretro_android.so"
            source.write_bytes(b"core")
            installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            installer.adb = FakeAdb()
            installer.run_dir = Path(directory) / "run"
            installer.dry_run = False
            installer.log = lambda message: None
            installer.install_cores({"nes": source})

        self.assertEqual(
            [
                (source, "/storage/sdcard1/retroarch/cores/fceumm_libretro_android.so"),
                (
                    source,
                    "/data/data/com.retroarch.ra32/cores/fceumm_libretro_android.so",
                ),
            ],
            pushes,
        )


class FrontendMusicTests(unittest.TestCase):
    def test_installs_missing_tracks_and_keeps_existing_tracks(self):
        pushes = []
        commands = []
        states = iter(("missing", "installed"))

        class FakeAdb:
            def shell_text(self, command, timeout=120, check=True):
                commands.append(command)
                if command.startswith("if test -f"):
                    return next(states)
                return "done"

            def push(self, local, remote, timeout=600):
                pushes.append((Path(local), remote))

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "menu.ogg"
            source.write_bytes(b"music")
            installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            installer.manifest = {
                "artifacts": {
                    "frontend_music": {
                        "device_path": "/storage/sdcard1/music",
                        "files": {"menu.ogg": inst.sha256_file(source)},
                    }
                }
            }
            installer.frontend_music_files = lambda: {"menu.ogg": source}
            installer.adb = FakeAdb()
            installer.dry_run = False
            installer.msg = lambda *args, **kwargs: None
            installer.install_frontend_music()

        self.assertEqual([(source, "/storage/sdcard1/music/menu.ogg")], pushes)
        self.assertIn("/storage/sdcard1/music/menu.ogg", commands[1])

    def test_keeps_existing_track_without_temp_copy_cleanup(self):
        pushes = []

        class FakeAdb:
            def shell_text(self, command, timeout=120, check=True):
                if command.startswith("if test -f"):
                    return "existing"
                return "done"

            def push(self, local, remote, timeout=600):
                pushes.append((Path(local), remote))

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "menu.ogg"
            source.write_bytes(b"music")
            installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            installer.manifest = {
                "artifacts": {
                    "frontend_music": {
                        "device_path": "/storage/sdcard1/music",
                        "files": {"menu.ogg": inst.sha256_file(source)},
                    }
                }
            }
            installer.frontend_music_files = lambda: {"menu.ogg": source}
            installer.adb = FakeAdb()
            installer.dry_run = False
            installer.msg = lambda *args, **kwargs: None
            installer.install_frontend_music()

        self.assertEqual([], pushes)


class AndroidBootSplashTests(unittest.TestCase):
    def test_splash_only_command_never_enters_boot_region_flow(self):
        calls = []
        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.serial = "SERIAL"
        installer.known = True
        installer.dry_run = False
        installer.adb = type("RootAdb", (), {"is_root": lambda self: True})()
        installer.print_identity = lambda: None
        installer.msg = lambda *args, **kwargs: None
        installer.install_android_bootanimation = lambda: calls.append("splash")
        installer.verify_android_bootanimation = lambda: "verified"
        installer.install_splash(confirmed="INSTALL-SERIAL")
        self.assertEqual(["splash"], calls)

    def test_install_replaces_android_file_without_raw_flash_write(self):
        source = (
            INSTALLER / MANIFEST["artifacts"]["android_bootanimation"]["source"]
        ).resolve()
        pushed = []
        shell_commands = []

        class FakeAdb:
            def __init__(self):
                self.pull_count = 0

            def pull(self, remote, local, check=False):
                self.pull_count += 1
                if self.pull_count == 1:
                    return False
                Path(local).write_bytes(source.read_bytes())
                return True

            def push(self, local, remote, timeout=600):
                pushed.append((local, remote))

            def shell(self, command, timeout=300, check=True):
                shell_commands.append(command)
                return inst.CommandResult(0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            installer.manifest = MANIFEST
            installer.profile = PROFILE
            installer.run_dir = Path(directory)
            installer.dry_run = False
            installer.adb = FakeAdb()
            installer.art = lambda key: source
            installer.verify_android_bootanimation = lambda: MANIFEST["artifacts"][
                "android_bootanimation"
            ]["sha256"]
            installer.msg = lambda *args, **kwargs: None
            installer.install_android_bootanimation()

        self.assertEqual(1, len(pushed))
        self.assertEqual("/data/local/tmp/vamanos-bootanimation.zip", pushed[0][1])
        self.assertEqual(1, len(shell_commands))
        self.assertIn("/system/media/bootanimation.zip", shell_commands[0])
        self.assertIn(
            "/system/media/bootanimation.zip.vamanos-previous", shell_commands[0]
        )
        self.assertNotIn("/dev/block/mmcblk0", shell_commands[0])


class DebloatBackupTests(unittest.TestCase):
    def test_backup_is_required_before_removal(self):
        commands = []
        pulled = []

        class FakeAdb:
            def package_path(self, package):
                return "/data/app/{}-1.apk".format(package)

            def shell_text(self, command, timeout=120, check=True):
                commands.append(command)
                if command.startswith("test -f") and "&& echo yes" in command:
                    return "yes"
                return "done"

            def pull(self, remote, local, check=False, timeout=600):
                pulled.append((remote, local))
                Path(local).write_bytes(b"apk")
                return True

        with tempfile.TemporaryDirectory() as directory:
            installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            installer.dry_run = False
            installer.run_dir = Path(directory)
            installer.profile = {
                "debloat": {
                    "backup_path": "/storage/sdcard1/ps202/backups/apps",
                    "remove": ["com.ps202.shell"],
                    "protected": [],
                }
            }
            installer.adb = FakeAdb()
            installer.msg = lambda *args, **kwargs: None
            installer.log = lambda *args, **kwargs: None
            installer.backup_packages_before_removal()

        self.assertTrue(
            any(
                "cp -p /data/app/com.ps202.shell-1.apk" in command
                for command in commands
            )
        )
        self.assertTrue(
            any(
                "cp -R -p /data/data/com.ps202.shell" in command for command in commands
            )
        )
        self.assertEqual([("/data/app/com.ps202.shell-1.apk", pulled[0][1])], pulled)


class ConfirmationTests(unittest.TestCase):
    def test_exact_token_required(self):
        def make():
            inst_ = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            inst_.serial = "0123456789ABCDEF"
            return inst_

        token = inst.Confirmation.token("INSTALL", "0123456789ABCDEF")
        self.assertEqual("INSTALL-89ABCDEF", token)
        with self.assertRaises(inst.InstallerError):
            inst.Confirmation.request("0123456789ABCDEF", "INSTALL-WRONG")
        # correct token returns normally (no exception)

    def test_rounded_sector_alignment(self):
        # Boot 0x1D80000 / 512 = 60416 (whole sectors)
        self.assertEqual(0, (PROFILE["regions"]["boot"]["offset"] % 512))


class FactoryTemprootTests(unittest.TestCase):
    def test_install_artifact_preflight_resolves_temproot_inputs(self):
        resolved = []
        payloads = []
        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.art = lambda key: resolved.append(key) or Path("/tmp/" + key)
        installer.frontend_music_files = lambda: {"menu.ogg": Path("/tmp/menu.ogg")}
        installer.core_files = lambda: {"fceumm": Path("/tmp/fceumm.so")}
        installer.payload_file = lambda key: payloads.append(key) or Path("/tmp/" + key)
        installer.validate_launcher_config = lambda *args: None
        installer.validate_known_boot_images = lambda: None

        installer.validate_install_artifacts("temproot")

        self.assertEqual(
            {
                "android_bootanimation",
                "su",
                "find",
                "emulationstation",
                "retroarch",
                "ppsspp",
                "cody_theme",
                "temproot_cowtest",
                "temproot_blockdump",
            },
            set(resolved),
        )
        self.assertEqual(
            {
                "boot_helper",
                "performance_profile",
                "launcher_config",
                "retroarch_baseline",
                "retroarch_autoconfig",
            },
            set(payloads),
        )

    def test_existing_ppsspp_can_skip_bundled_apk_preflight(self):
        resolved = []
        installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        installer.art = lambda key: resolved.append(key) or Path("/tmp/" + key)
        installer.frontend_music_files = lambda: {"menu.ogg": Path("/tmp/menu.ogg")}
        installer.core_files = lambda: {"fceumm": Path("/tmp/fceumm.so")}
        installer.payload_file = lambda key: Path("/tmp/" + key)
        installer.validate_launcher_config = lambda *args: None

        installer.validate_install_artifacts("skip", require_ppsspp=False)

        self.assertNotIn("ppsspp", resolved)

    def test_preflight_does_not_read_boot_before_temproot(self):
        class FactoryAdb:
            def is_root(self):
                return False

            def shell_text(self, command, timeout=120, check=True):
                if command.startswith("ls -d /storage/sdcard1"):
                    return "/storage/sdcard1"
                return ""

        with tempfile.TemporaryDirectory() as directory:
            installer = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
            installer.dry_run = False
            installer.known = True
            installer.run_dir = Path(directory)
            installer.adb = FactoryAdb()
            installer.identify = lambda: None

            def fail_if_called(*args, **kwargs):
                raise AssertionError("factory preflight must defer boot read")

            installer.read_current_region = fail_if_called
            report = installer.preflight(boot_mode="temproot")

        self.assertFalse(report["root_adb"])
        self.assertTrue(report["boot_read_deferred"])
        self.assertNotIn("boot_sha256", report)

    def test_legacy_temproot_alias_maps_to_boot_mode(self):
        args = inst._build_arg_parser().parse_args(["install", "--temproot"])
        self.assertTrue(args.legacy_temproot)
        args = inst._build_arg_parser().parse_args(
            ["install", "--boot-mode", "temproot"]
        )
        self.assertEqual("temproot", args.boot_mode)

    def test_restore_boot_command_has_its_own_confirmation(self):
        args = inst._build_arg_parser().parse_args(
            ["restore-boot", "--confirm", "RESTORE-1234"]
        )
        self.assertEqual("restore_boot", args.func)
        self.assertEqual("RESTORE-1234", args.confirm)
        self.assertEqual(
            "RESTORE-89ABCDEF", inst.Confirmation.token("RESTORE", "0123456789ABCDEF")
        )


class CpuReportTests(unittest.TestCase):
    def test_fmt_mhz(self):
        self.assertEqual("1300 MHz", inst.VamanOSInstaller._fmt_mhz("1300000"))
        self.assertEqual("598 MHz", inst.VamanOSInstaller._fmt_mhz("598000"))
        self.assertEqual("n/a", inst.VamanOSInstaller._fmt_mhz("n/a"))

    def test_report_cpu_never_writes(self):
        """The CPU report is read-only: no governor/frequency write is issued."""
        calls = []

        class RecordingAdb:
            def shell_text(self, command, timeout=120, check=True):
                calls.append(command)
                if "scaling_governor" in command:
                    return "hotplug"
                if "scaling_cur_freq" in command:
                    return "1300000"
                if "cpuinfo_max_freq" in command:
                    return "1300000"
                if "cpuinfo_min_freq" in command:
                    return "598000"
                return ""

        instance = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        instance.adb = RecordingAdb()
        instance.log = lambda *a, **k: None
        instance.msg = lambda *a, **k: None
        instance.report_cpu()
        # Only `cat` reads are issued, never `echo ... >` that writes a value
        # into the sysfs node. (`2>/dev/null` stderr redirects are harmless.)
        self.assertTrue(calls)
        for command in calls:
            self.assertTrue(command.startswith("cat "))
            self.assertNotRegex(command, r"^\s*echo\b")


class AucBinariesTests(unittest.TestCase):
    def test_patched_boot_contains_adbd_and_init_script(self):
        """Every bundled patched pair carries the required ramdisk files."""
        for variant in MANIFEST["boot_image_variants"]:
            img = (
                INSTALLER / MANIFEST["artifacts"][variant["patched"]]["source"]
            ).resolve()
            entries = inst._parse_newc(
                inst._boot_layout(
                    img.read_bytes(), PROFILE["regions"]["boot"]["length"]
                )["cpio"]
            )
            files = {name for name, _mode, _body in entries}
            self.assertTrue(
                {"sbin/adbd", "sbin/find", "sbin/ps202-init.sh"} <= files,
                variant["name"],
            )

    def test_install_aux_binaries_skips_su_and_deploys_find(self):
        """install_aux_binaries() must deploy find (not su) to /system/xbin."""
        pushed = []

        inst_ = inst.VamanOSInstaller.__new__(inst.VamanOSInstaller)
        inst_.dry_run = False
        inst_.manifest = MANIFEST
        inst_.adb = type("FakeAdb", (), {})()
        inst_.adb.push = lambda local, remote, timeout=600: pushed.append(remote)
        inst_.adb.shell_text = lambda *a, **k: "done"
        inst_.art = lambda key: ROOT / "tools/ps202-installer" / "manifest.json"
        inst_.msg = lambda *a, **k: None
        inst_.install_aux_binaries()
        # `su` must NOT be pushed here (it has a dedicated install_su); `find`
        # must be pushed to /data/local/tmp/vamanos-find.
        self.assertNotIn("/data/local/tmp/vamanos-su", pushed)
        self.assertIn("/data/local/tmp/vamanos-find", pushed)


if __name__ == "__main__":
    unittest.main()
