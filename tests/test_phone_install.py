"""android/scripts/phone-install.sh, run from a copy in a checkout of its own against a fake ``adb`` and a fake
``nix``: which device it picks, the build it asks for, the install for user 0 alone, and never the release's
package. No test reaches a device or runs Gradle."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "android" / "scripts" / "phone-install.sh"

DEBUG = "io.github.danielhp95.caracole.debug"
RELEASE = "io.github.danielhp95.caracole"
PHONE = "192.168.12.219:41873"
OTHER = "R5CT10ABCDE"

if not SCRIPT.exists():  # the package build's tree: pyproject.toml, README.md, LICENSE, src/ and tests/ alone
    pytest.skip("android/ is not in this tree", allow_module_level=True)

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")]

# The fake adb: `devices` lists FAKE_ADB_DEVICES ("serial state" a line), after an adb server's start-up lines when
# FAKE_ADB_NOISE is set; `install` says Success unless FAKE_ADB_INSTALL names its Failure; `shell dumpsys package P`
# names P's versionName; every call logged to calls.jsonl.
ADB = r'''
import json, os, sys
from pathlib import Path
here = Path(__file__).resolve().parent
argv = sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps({"tool": "adb", "argv": argv}) + "\n")
if argv == ["devices"]:
    if os.environ.get("FAKE_ADB_NOISE"):
        print("* daemon not running; starting now at tcp:5037")
        print("* daemon started successfully")
    print("List of devices attached")
    for line in os.environ.get("FAKE_ADB_DEVICES", "").splitlines():
        if line.strip():
            serial, state = line.split()
            print(f"{serial}\t{state}")
    print()
    sys.exit(0)
rest = argv[2:] if argv[:1] == ["-s"] else argv
if rest[:1] == ["install"]:
    if os.environ.get("FAKE_ADB_INSTALL"):
        print("Performing Streamed Install\r")
        print(f"adb: failed to install app-debug.apk: Failure [{os.environ['FAKE_ADB_INSTALL']}]\r")
        sys.exit(1)
    print("Performing Streamed Install\r\nSuccess\r")
    sys.exit(0)
if rest[:3] == ["shell", "dumpsys", "package"]:
    print(f"Packages:\r\n  Package [{rest[3]}] (1a2b3c):\r\n    versionCode=3 minSdk=26 targetSdk=36\r\n"
          f"    versionName=0.3.0-debug\r")
    sys.exit(0)
if rest[:3] == ["shell", "am", "start"]:
    print("Starting: Intent { cmp=... }")
    sys.exit(0)
sys.exit(f"fake adb: no answer for {argv}")
'''

# The fake nix: logs its arguments and leaves the APK the build would, and AGP's output-metadata.json naming
# FAKE_APP_ID (the debug build's package unless a test says otherwise).
NIX = r'''
import json, os, sys
from pathlib import Path
here = Path(__file__).resolve().parent
argv = sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps({"tool": "nix", "argv": argv}) + "\n")
android = Path(argv[argv.index("-p") + 1])
out = android / "app" / "build" / "outputs" / "apk" / "debug"
out.mkdir(parents=True, exist_ok=True)
(out / "app-debug.apk").write_bytes(b"PK an apk")
(out / "output-metadata.json").write_text(json.dumps({
    "version": 3, "applicationId": os.environ.get("FAKE_APP_ID", "io.github.danielhp95.caracole.debug"),
    "variantName": "debug", "elements": [{"type": "SINGLE", "versionCode": 3, "versionName": "0.3.0-debug",
                                           "outputFile": "app-debug.apk"}]}, indent=2))
'''


class Rig:
    def __init__(self, tmp_path: Path):
        self.checkout = tmp_path / "checkout"
        scripts = self.checkout / "android" / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(SCRIPT, scripts / "phone-install.sh")
        self.android = self.checkout / "android"
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for name, body in (("adb", ADB), ("nix", NIX)):
            tool = self.bin / name
            tool.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
            tool.chmod(0o755)

    def run(self, *args: str, devices: str = "", **env: str) -> subprocess.CompletedProcess:
        full = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "FAKE_ADB_DEVICES": devices,
                **env}
        full.pop("ADB", None)
        return subprocess.run(["bash", str(self.android / "scripts" / "phone-install.sh"), *args], env=full,
                              capture_output=True, text=True, timeout=60)

    def calls(self, tool: str | None = None) -> list[list[str]]:
        log = self.bin / "calls.jsonl"
        lines = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [c["argv"] for c in lines if tool is None or c["tool"] == tool]

    @property
    def apk(self) -> str:
        return str(self.android / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk")


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_the_one_phone_gets_this_checkouts_debug_build_for_user_0_alone(rig):
    done = rig.run(devices=f"emulator-5554 device\n{PHONE} device")
    assert done.returncode == 0, done.stderr
    assert rig.calls("nix") == [["develop", str(rig.android), "-c", "gradle", "-p", str(rig.android),
                                 ":app:assembleDebug", "--max-workers=2"]]
    assert ["-s", PHONE, "install", "-r", "--user", "0", rig.apk] in rig.calls("adb")
    assert f"Installed {DEBUG} 0.3.0-debug on {PHONE}." in done.stdout
    assert not any("am" in c for c in rig.calls("adb")), "no --launch: nothing started"


def test_launch_starts_the_debug_app_for_user_0(rig):
    done = rig.run("--launch", devices=f"{PHONE} device")
    assert done.returncode == 0, done.stderr
    assert rig.calls("adb")[-1] == ["-s", PHONE, "shell", "am", "start", "--user", "0", "-n",
                                    f"{DEBUG}/io.github.danielhp95.caracole.MainActivity"]


def test_a_serial_named_picks_that_device_among_several(rig):
    done = rig.run("-s", OTHER, devices=f"{PHONE} device\n{OTHER} device")
    assert done.returncode == 0, done.stderr
    assert ["-s", OTHER, "install", "-r", "--user", "0", rig.apk] in rig.calls("adb")
    assert not any(PHONE in c for c in rig.calls("adb"))


def test_a_serial_named_may_be_an_emulator(rig):
    done = rig.run("-s", "emulator-5556", devices="emulator-5556 device")
    assert done.returncode == 0, done.stderr
    assert ["-s", "emulator-5556", "install", "-r", "--user", "0", rig.apk] in rig.calls("adb")


@pytest.mark.parametrize("devices, says", [
    (f"{PHONE} device\n{OTHER} device", "more than one phone"),
    ("emulator-5554 device", "no phone is connected"),
    ("", "no phone is connected"),
    (f"{PHONE} unauthorized", "no phone is connected"),
])
def test_no_single_phone_is_an_error_that_lists_the_devices_before_any_build(rig, devices, says):
    done = rig.run(devices=devices)
    assert done.returncode == 3
    assert says in done.stderr
    for line in devices.splitlines():
        assert line in done.stderr
    if not devices:
        assert "(none" in done.stderr
    assert rig.calls("nix") == []
    assert not any("install" in c for c in rig.calls("adb"))


def test_a_serial_not_connected_or_not_ready_is_an_error(rig):
    gone = rig.run("-s", OTHER, devices=f"{PHONE} device")
    assert gone.returncode == 3
    assert f"{OTHER} isn't connected" in gone.stderr and PHONE in gone.stderr
    waiting = rig.run("-s", PHONE, devices=f"{PHONE} unauthorized")
    assert waiting.returncode == 3
    assert "unauthorized" in waiting.stderr and "accept the prompt on the phone" in waiting.stderr
    assert rig.calls("nix") == []


def test_an_apk_of_the_release_package_is_never_installed(rig):
    done = rig.run(devices=f"{PHONE} device", FAKE_APP_ID=RELEASE)
    assert done.returncode == 4
    assert f"not {DEBUG}: nothing installed" in done.stderr
    assert not any("install" in c for c in rig.calls("adb"))


def test_no_call_names_the_release_package(rig):
    assert rig.run("--launch", devices=f"{PHONE} device").returncode == 0
    for call in rig.calls("adb"):
        for word in call:
            assert word != RELEASE and not word.startswith(RELEASE + "/"), call


@pytest.mark.parametrize("failure", [
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE: Existing package io.github.danielhp95.caracole.debug signatures do not match "
    "newer version; ignoring!",
    "INSTALL_FAILED_INSUFFICIENT_STORAGE",
])
def test_an_install_that_fails_says_what_adb_said_and_what_often_causes_it(rig, failure):
    done = rig.run(devices=f"{PHONE} device", FAKE_ADB_INSTALL=failure)
    assert done.returncode == 1
    assert f"  adb: failed to install app-debug.apk: Failure [{failure}]\n" in done.stderr, "adb's own words, whole"
    assert "\r" not in done.stderr
    assert "Often a debug build signed with another machine's key" in done.stderr
    assert f"adb -s {PHONE} uninstall --user 0 {DEBUG}" in done.stderr
    assert not any("dumpsys" in c for c in rig.calls("adb"))


def test_an_adb_server_starting_says_so_before_the_list_and_none_of_it_is_a_device(rig):
    done = rig.run(devices=f"emulator-5554 device\n{PHONE} device", FAKE_ADB_NOISE="1")
    assert done.returncode == 0, done.stderr
    assert ["-s", PHONE, "install", "-r", "--user", "0", rig.apk] in rig.calls("adb")
    several = rig.run(devices=f"{PHONE} device\n{OTHER} device", FAKE_ADB_NOISE="1")
    assert several.returncode == 3
    listed = several.stderr.split("adb lists:\n", 1)[1]
    assert listed.splitlines() == [f"  {PHONE} device", f"  {OTHER} device"]
    alone = rig.run(devices="", FAKE_ADB_NOISE="1")
    assert alone.returncode == 3 and "(none" in alone.stderr and "daemon" not in alone.stderr


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="needs shellcheck")
def test_shellcheck_finds_nothing():
    done = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout


def test_an_unknown_argument_prints_the_usage(rig):
    done = rig.run("--release", devices=f"{PHONE} device")
    assert done.returncode == 2
    assert "phone-install.sh [-s SERIAL] [--launch]" in done.stdout
    assert rig.calls() == []
