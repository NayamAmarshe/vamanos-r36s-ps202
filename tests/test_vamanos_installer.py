import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import vamanos_installer as inst


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "tools" / "ps202-installer"
MANIFEST = inst.load_json(INSTALLER / "manifest.json")
PROFILE = inst.load_json(INSTALLER / "device-profile.json")


class ManifestProfileTests(unittest.TestCase):
    def test_emulationstation_artifact_is_the_suspend_fix_build(self):
        apk = (ROOT / "ps202-batocera-es/build/ps202-emulationstation.apk").resolve()
        if not apk.is_file():
            self.skipTest("current EmulationStation APK not present")
        self.assertEqual(MANIFEST["artifacts"]["emulationstation"]["sha256"],
                         inst.sha256_file(apk))
        with zipfile.ZipFile(apk) as archive:
            dex = archive.read("classes.dex")
        self.assertIn(b"pauseForSuspend", dex)
        self.assertIn(b"resumeAfterSuspend", dex)
        self.assertIn(b"splash wallpaper repaired", dex)

    def test_profile_is_ps202_00001(self):
        self.assertEqual("PS202_00001", PROFILE["id"])
        self.assertEqual("armeabi-v7a", PROFILE["identity"]["abi"])

    def test_boot_region_offsets_are_exact(self):
        boot = PROFILE["regions"]["boot"]
        self.assertEqual(0x01D80000, boot["offset"])   # 30932992 bytes = 60416 sectors
        self.assertEqual(6 * 1024 * 1024, boot["length"])

    def test_splash_is_android_bootanimation_not_raw_logo_region(self):
        self.assertNotIn("logo", PROFILE["regions"])
        self.assertNotIn("logo_custom", MANIFEST["artifacts"])
        self.assertEqual("/system/media/bootanimation.zip",
                         PROFILE["android_boot_splash"]["path"])
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
            self.assertEqual(b"640 480 15\np 1 0 part0\np 0 0 part1\n",
                             archive.read("desc.txt"))
            self.assertEqual(artifact["reveal_frame_count"],
                             len([name for name in names if name.startswith("part0/")]))
            self.assertEqual(zipfile.ZIP_STORED, archive.getinfo("desc.txt").compress_type)
            for name in names[1:]:
                self.assertEqual(zipfile.ZIP_STORED, archive.getinfo(name).compress_type)

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
            self.assertFalse(any(name.startswith("es-theme-CODY-DARKTECK-main/") for name in names))
            self.assertIn(b"<formatVersion>7</formatVersion>", archive.read("theme.xml"))

    def test_boot_patched_hash_matches_reference_image(self):
        img = (ROOT / "ps202-project/firmware/boot-adbd-root-v2.img").resolve()
        if not img.is_file():
            self.skipTest("reference boot image not present")
        expected = PROFILE["regions"]["boot"]["patched_sha256"]
        self.assertEqual(expected, inst.sha256_file(img))

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
        profile = (INSTALLER / "payload/ps202-performance.sh").read_text(encoding="utf-8")
        self.assertIn("restore", profile)
        self.assertIn("/proc/sys/vm/swappiness", profile)
        self.assertIn("/sys/block/mmcblk1/queue/read_ahead_kb", profile)
        self.assertNotIn("scaling_governor", profile)
        self.assertNotIn("scaling_setspeed", profile)
        self.assertNotIn("/system/usr/keylayout/mtk-kpd.kl", profile)

    def test_shell_is_not_an_installer_artifact_and_emulator_is_protected(self):
        self.assertNotIn("shell", MANIFEST["artifacts"])
        self.assertIn("com.ps202.shell", PROFILE["debloat"]["remove"])
        self.assertIn("com.xugame.gameconsoleMenu", PROFILE["debloat"]["remove"])
        self.assertNotIn("com.xugame.gameconsole", PROFILE["debloat"]["remove"])
        self.assertIn("com.xugame.gameconsole", PROFILE["debloat"]["protected"])

    def test_seven_cores_referenced_by_launchers_are_in_manifest(self):
        # The device launcher map needs exactly these seven cores.
        cores = MANIFEST["cores"]
        for name in ("fceumm", "snes9x", "gambatte", "gpsp", "pcsx_rearmed", "picodrive", "mgba"):
            self.assertIn(name, cores)
        self.assertEqual("tgbdual_libretro_android.so", cores["gambatte"])

    def test_api19_core_source_precedes_newer_buildbot_inputs(self):
        sources = MANIFEST["core_sources"]
        self.assertEqual("release-inputs/cores-api19", sources[0])
        launcher = (INSTALLER / "payload/android_launchers.xml").read_text(encoding="utf-8")
        self.assertIn('value="tgbdual_libretro_android.so"', launcher)
        self.assertIn('value="gpsp_libretro_android.so"', launcher)

    def test_debloat_protected_contains_critical_packages(self):
        protected = set(PROFILE["debloat"]["protected"])
        for pkg in ("com.android.systemui", "com.android.phone", "com.android.bluetooth",
                    "com.ps202.emulationstation", "com.retroarch.ra32", "org.ppsspp.ppsspp"):
            self.assertIn(pkg, protected)


class MergeCfgTests(unittest.TestCase):
    def test_preserves_manual_input_bindings(self):
        existing = 'input_player1_a = "5"\nvideo_driver = "gl"\n'
        overlay = 'input_player1_a = "99"\nvideo_driver = "gles"\naudio_latency = "96"\n'
        merged = inst.merge_cfg(existing, overlay)
        self.assertIn('input_player1_a = "5"', merged)   # user remap kept
        self.assertIn('video_driver = "gles"', merged)   # non-personal key merged
        self.assertIn('audio_latency = "96"', merged)    # new key appended

    def test_adds_new_keys_and_leaves_unknown_lines(self):
        existing = 'content_show_history = "true"\n'
        overlay = 'content_show_history = "false"\nnotification_show_autoconfig = "false"\n'
        merged = inst.merge_cfg(existing, overlay)
        self.assertIn('content_show_history = "false"', merged)
        self.assertIn('notification_show_autoconfig = "false"', merged)

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

    def test_reads_serial_for_confirmation_when_available(self):
        class RecordingRunner(inst.HostRunner):
            def run(self, args, timeout=120, check=True, binary=False):
                self.args = list(args)
                return inst.CommandResult(0, "0123456789ABCDEF\n", "")

        runner = RecordingRunner()
        client = inst.AdbClient("adb", runner=runner)
        self.assertEqual("0123456789ABCDEF", client.get_serialno())
        self.assertIn("get-serialno", runner.args)


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
                (source, "/data/data/com.retroarch.ra32/cores/fceumm_libretro_android.so"),
            ],
            pushes,
        )


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
        source = (INSTALLER / MANIFEST["artifacts"]["android_bootanimation"]["source"]).resolve()
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
            installer.verify_android_bootanimation = lambda: MANIFEST["artifacts"]["android_bootanimation"]["sha256"]
            installer.msg = lambda *args, **kwargs: None
            installer.install_android_bootanimation()

        self.assertEqual(1, len(pushed))
        self.assertEqual("/data/local/tmp/vamanos-bootanimation.zip", pushed[0][1])
        self.assertEqual(1, len(shell_commands))
        self.assertIn("/system/media/bootanimation.zip", shell_commands[0])
        self.assertIn("/system/media/bootanimation.zip.vamanos-previous", shell_commands[0])
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

        self.assertTrue(any("cp -p /data/app/com.ps202.shell-1.apk" in command
                            for command in commands))
        self.assertTrue(any("cp -R -p /data/data/com.ps202.shell" in command
                            for command in commands))
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
        installer.core_files = lambda: {"fceumm": Path("/tmp/fceumm.so")}
        installer.payload_file = lambda key: payloads.append(key) or Path("/tmp/" + key)

        installer.validate_install_artifacts("temproot")

        self.assertEqual(
            {"android_bootanimation", "su", "find", "emulationstation",
             "retroarch", "ppsspp", "cody_theme", "boot_patched",
             "temproot_cowtest", "temproot_blockdump"},
            set(resolved),
        )
        self.assertEqual({"boot_helper", "performance_profile", "launcher_config", "retroarch_baseline"}, set(payloads))

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
        args = inst._build_arg_parser().parse_args(["install", "--boot-mode", "temproot"])
        self.assertEqual("temproot", args.boot_mode)


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
        """The boot image we ship must carry the patched adbd, find, and the
        ps202-init.sh boot script in its ramdisk."""
        img = (ROOT / "ps202-project/firmware/boot-adbd-root-v2.img").resolve()
        if not img.is_file():
            self.skipTest("reference patched boot image not present")
        import gzip as _g
        data = img.read_bytes()
        page = int.from_bytes(data[36:40], "little")
        kernel_size = int.from_bytes(data[8:12], "little")
        ramdisk_size = int.from_bytes(data[16:20], "little")
        roff = page + ((kernel_size + page - 1) // page) * page
        region = data[roff: roff + ramdisk_size]
        gz_idx = region.find(b"\x1f\x8b\x08")
        self.assertGreaterEqual(gz_idx, 0, "gzip ramdisk not found in boot image")
        cpio = _g.decompress(region[gz_idx:])
        for needle in (b"sbin/adbd", b"sbin/find", b"sbin/ps202-init.sh"):
            self.assertIn(needle, cpio, f"ramdisk missing {needle.decode()}")

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
