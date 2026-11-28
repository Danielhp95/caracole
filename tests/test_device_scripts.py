"""android/scripts/device-test.sh and android/scripts/stop-all.sh, each run from a copy in a checkout of its own
against stand-ins for ``adb``, ``emulator``, ``nix`` (and, for stop-all.sh, ``ps``): what each leaves running, the
owner's rule of 2026-11-27 ("Ensure that emulators are properly killed when using them for testing or development.
same thing for gradle biuld and adb servers."). No test reaches a device, an emulator or Gradle."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "android" / "scripts"
PHONE = "192.0.2.10:41873"  # a documentation address (RFC 5737), never a real phone's

if not SCRIPTS.exists():  # the package build's tree: pyproject.toml, README.md, LICENSE, src/ and tests/ alone
    pytest.skip("android/ is not in this tree", allow_module_level=True)

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not shutil.which("bash") or not shutil.which("flock")
                                                   or not shutil.which("setsid"), reason="needs bash and util-linux")]

# Every stand-in logs its call to calls.jsonl beside it and keeps its state there too: `server` while adb's server
# runs, `emulators/<port>` (its pid) while an emulator does, `emulators/<port>.kill` once `emu kill` asked it to end.
COMMON = r'''
import json, os, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
state = here / "emulators"
state.mkdir(exist_ok=True)
def held_locks():
    out = []
    for fd in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue
        if target.endswith(".lock"):
            out.append(target)
    return out
def log(tool, argv):
    with open(here / "calls.jsonl", "a") as f:
        f.write(json.dumps({"tool": tool, "argv": argv, "locks": held_locks()}) + "\n")
def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie is no emulator
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except OSError:
        return False
def emulators():
    out = {}
    for f in state.iterdir():
        if f.name.isdigit() and alive(int(f.read_text() or 0)):
            out[f.name] = int(f.read_text())
    return out
'''

# adb: `devices` starts its server when none runs (saying so, as adb does), then lists FAKE_ADB_DEVICES and the
# emulators alive; `kill-server` ends it; `-s emulator-N emu kill` asks that emulator to end.
ADB = COMMON + r'''
argv = sys.argv[1:]
log("adb", argv)
hang = os.environ.get("FAKE_ADB_HANG", "").split(",")
if argv == ["devices"] and "devices" in hang and (not os.environ.get("FAKE_ADB_HANG_AFTER_RUN")
                                                  or (here / "instrumenting").exists()):
    time.sleep(600)
if argv == ["devices"]:
    if not (here / "server").exists():
        (here / "server").write_text("up")
        print("* daemon not running; starting now at tcp:5037", file=sys.stderr)
        print("* daemon started successfully", file=sys.stderr)
    print("List of devices attached")
    for line in os.environ.get("FAKE_ADB_DEVICES", "").splitlines():
        if line.strip():
            print("\t".join(line.split()))
    for port in sorted(emulators()):
        print(f"emulator-{port}\tdevice")
    print()
    sys.exit(0)
if argv == ["kill-server"]:
    (here / "server").unlink(missing_ok=True)
    sys.exit(0)
serial, rest = (argv[1], argv[2:]) if argv[:1] == ["-s"] else ("", argv)
if rest == ["emu", "kill"] and "emu" in hang:
    time.sleep(600)
if rest[:3] == ["shell", "rm", "-rf"] and "rm" in hang and (here / "instrumenting").exists():
    time.sleep(600)  # the cleanup's, after the run
if rest == ["emu", "kill"]:
    (state / (serial.removeprefix("emulator-") + ".kill")).write_text("")
    print("OK: killing emulator, bye bye")
    sys.exit(0)
if rest[:1] in (["install"], ["push"]):
    print("Success")
    sys.exit(0)
if rest[:3] == ["shell", "getprop", "sys.boot_completed"]:
    print("1\r")
    sys.exit(0)
if rest[:3] == ["shell", "am", "instrument"]:
    how = os.environ.get("FAKE_INSTRUMENT", "ok")
    (here / "instrumenting").write_text("")
    if how == "crash":  # the emulator dies mid-run
        port = serial.removeprefix("emulator-")
        (state / (port + ".kill")).write_text("")
        while port in emulators():
            time.sleep(0.05)
    if how == "hang":
        time.sleep(60)
    print("FAILURES!!!\r" if how == "fail" else "OK (1 test)\r")
    sys.exit(0)
if rest[:1] == ["shell"]:
    sys.exit(0)
sys.exit(f"fake adb: no answer for {argv}")
'''

# emulator: up as `-port N` says until `emu kill` asks it to end (never, with FAKE_EMULATOR_DEAF: then only a signal
# ends it).
EMULATOR = COMMON + r'''
argv = sys.argv[1:]
log("emulator", argv)
port = argv[argv.index("-port") + 1]
(state / port).write_text(str(os.getpid()))
(state / (port + ".kill")).unlink(missing_ok=True)
while os.environ.get("FAKE_EMULATOR_DEAF") or not (state / (port + ".kill")).exists():
    time.sleep(0.05)
(state / port).unlink(missing_ok=True)
'''

# nix: `develop … -c gradle …` logged (the build, --status: FAKE_GRADLE_STATUS, or --stop); any other `-c` command run
# as it is.
NIX = COMMON + r'''
argv = sys.argv[1:]
log("nix", argv)
rest = argv[argv.index("-c") + 1:]
if rest[:1] == ["gradle"]:
    if "--status" in rest:
        print(os.environ.get("FAKE_GRADLE_STATUS", ""))
        sys.exit(int(os.environ.get("FAKE_GRADLE_STATUS_RC", "0")))
    sys.exit(0)
os.execvp(rest[0], rest)
'''

# ps, for stop-all.sh (`ps -u UID -o pid=,comm=,args=`): each emulator alive as its qemu, FAKE_GRADLE_DAEMONS' pids as
# Gradle daemons, and FAKE_PS_EXTRA's lines as they are.
PS = COMMON + r'''
argv = sys.argv[1:]
log("ps", argv)
for port, pid in sorted(emulators().items()):
    print(f"{pid} qemu-system-x86 /nix/store/x-emulator/qemu-system-x86_64 -avd caracole -port {port} -read-only")
for pid in os.environ.get("FAKE_GRADLE_DAEMONS", "").split():
    print(f"{pid} java /nix/store/x-jdk/bin/java -Xmx3g -cp gradle.jar org.gradle.launcher.daemon.bootstrap.GradleDaemon"
          " 8.14.4")
for line in os.environ.get("FAKE_PS_EXTRA", "").splitlines():
    print(line)
'''

# python, for device-test.sh's start_computer (`nix develop -c python -m tests.helpers.e2e_library serve DIR PORT
# ...`): its argv kept in computers/<port>.json with its pid, then a listener on 127.0.0.1:PORT until killed.
COMPUTER = r'''
import json, os, socket, sys
from pathlib import Path
here = Path(__file__).resolve().parent
argv = sys.argv[1:]
port = int(argv[argv.index("serve") + 2])
(here / "computers").mkdir(exist_ok=True)
(here / "computers" / f"{port}.json").write_text(json.dumps({"pid": os.getpid(), "argv": argv}))
s = socket.create_server(("127.0.0.1", port))
while True:
    c, _ = s.accept()
    c.close()
'''

STATUS = """   PID STATUS   INFO
{lines}

Only Daemons for the current Gradle version are displayed. See https://docs.gradle.org/8.14.4/userguide/gradle_daemon.html#sec:status
"""


class Rig:
    def __init__(self, tmp_path: Path, *, ps: bool = False):
        self.tmp = tmp_path
        self.android = tmp_path / "checkout" / "android"
        (self.android / "scripts").mkdir(parents=True)
        for name in ("device-test.sh", "stop-all.sh"):
            if (SCRIPTS / name).exists():
                shutil.copy2(SCRIPTS / name, self.android / "scripts" / name)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        tools = [("adb", ADB), ("emulator", EMULATOR), ("nix", NIX)] + ([("ps", PS)] if ps else [])
        for name, body in tools:
            tool = self.bin / name
            tool.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
            tool.chmod(0o755)
        (self.bin / "emulators").mkdir()
        self.lock = tmp_path / "locks" / "caracole-emulator.lock"
        self.extra: list[subprocess.Popen] = []

    def env(self, **env: str) -> dict:
        full = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "DISPLAY": ":99",
                "CARACOLE_EMULATOR_LOCK": str(self.lock), "CARACOLE_EMULATORS": "1",
                "CARACOLE_DEVICE_LOGS": str(self.tmp / "logs"), "CARACOLE_EMULATOR_STOP_WAIT": "3", **env}
        for name in ("ADB", "CARACOLE_KEEP_EMULATOR"):
            if name not in env:
                full.pop(name, None)
        return full

    def command(self, script: str, *args: str) -> list[str]:
        return ["bash", str(self.android / "scripts" / script), *args]

    def run(self, script: str, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(self.command(script, *args), env=self.env(**env), capture_output=True, text=True,
                              timeout=90)

    def server_up(self, up: bool = True) -> None:
        if up:
            (self.bin / "server").write_text("up")

    @property
    def server(self) -> bool:
        return (self.bin / "server").exists()

    def emulator_up(self, port: int = 5554, **env: str) -> subprocess.Popen:
        """An emulator someone else started: up before the script runs."""
        proc = subprocess.Popen([str(self.bin / "emulator"), "-avd", "caracole", "-port", str(port)],
                                env=self.env(**env), start_new_session=True)
        self.extra.append(proc)
        until(lambda: str(port) in self.emulators())
        return proc

    def emulators(self) -> dict[str, int]:
        out = {}
        for f in (self.bin / "emulators").iterdir():
            if f.name.isdigit() and f.read_text() and alive(int(f.read_text())):
                out[f.name] = int(f.read_text())
        return out

    def records(self) -> list[dict]:
        log = self.bin / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def calls(self, tool: str | None = None) -> list[list[str]]:
        return [c["argv"] for c in self.records() if tool is None or c["tool"] == tool]

    def adb_held_no_lock(self) -> bool:
        return all(c["locks"] == [] for c in self.records() if c["tool"] == "adb")

    def close(self) -> None:
        for proc in self.extra:
            proc.kill()
            proc.wait()
        for pid in self.emulators().values():
            os.kill(pid, signal.SIGKILL)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except OSError:
        return False


def until(check, timeout: float = 20) -> None:
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.05)


@pytest.fixture
def rig(tmp_path):
    made = Rig(tmp_path)
    yield made
    made.close()


@pytest.fixture
def stop_rig(tmp_path):
    made = Rig(tmp_path, ps=True)
    yield made
    made.close()


@pytest.fixture
def computer_rig(tmp_path):
    """The rig with a stand-in `python` for the computers device-test.sh starts; each one killed at the end."""
    made = Rig(tmp_path)
    tool = made.bin / "python"
    tool.write_text(f"#!{sys.executable}\n{COMPUTER}", encoding="utf-8")
    tool.chmod(0o755)
    yield made
    folder = made.bin / "computers"
    for record in folder.glob("*.json") if folder.exists() else []:
        try:
            os.kill(json.loads(record.read_text())["pid"], signal.SIGKILL)
        except (OSError, ValueError, KeyError):
            pass
    made.close()


# device-test.sh


def test_an_emulator_it_started_is_stopped_as_it_ends(rig):
    rig.server_up()
    done = rig.run("device-test.sh", "--area", "keys")
    assert done.returncode == 0, done.stderr
    assert ["-s", "emulator-5554", "emu", "kill"] in rig.calls("adb")
    assert rig.emulators() == {}, "its process is gone"
    assert "device-test.sh: stopped emulator-5554, which it started" in done.stderr


def test_an_emulator_that_was_up_already_is_left_up(rig):
    rig.server_up()
    rig.emulator_up()
    done = rig.run("device-test.sh", "--area", "keys")
    assert done.returncode == 0, done.stderr
    assert ["-s", "emulator-5554", "emu", "kill"] not in rig.calls("adb")
    assert "5554" in rig.emulators()
    assert "device-test.sh: emulator-5554 was up already: left up" in done.stderr
    assert rig.calls("emulator") == [["-avd", "caracole", "-port", "5554"]], "only the test's own"


@pytest.mark.parametrize("keep", [["--keep-emulator"], []])
def test_keep_emulator_leaves_up_the_one_it_started(rig, keep):
    rig.server_up()
    env = {} if keep else {"CARACOLE_KEEP_EMULATOR": "1"}
    done = rig.run("device-test.sh", *keep, "--area", "keys", **env)
    assert done.returncode == 0, done.stderr
    assert ["-s", "emulator-5554", "emu", "kill"] not in rig.calls("adb")
    assert "5554" in rig.emulators()
    assert "device-test.sh: emulator-5554 kept up (--keep-emulator)" in done.stderr


def test_a_failing_test_still_stops_the_emulator(rig):
    rig.server_up()
    done = rig.run("device-test.sh", "--area", "keys", FAKE_INSTRUMENT="fail")
    assert done.returncode == 1
    assert "FAIL CorpusOnDeviceTest" in done.stdout
    assert rig.emulators() == {}
    assert "stopped emulator-5554" in done.stderr


def test_a_computer_it_starts_listens_on_the_hosts_loopback_alone(computer_rig, tmp_path):
    """caracole serve has no sign-in: a test's computer is never on the LAN (android/README.md); the emulator reaches
    the host's loopback at 10.0.2.2."""
    computer_rig.server_up()
    done = computer_rig.run("device-test.sh", f"NoSitesTest={tmp_path / 'computer'}")
    assert done.returncode == 0, done.stderr
    records = [json.loads(f.read_text()) for f in (computer_rig.bin / "computers").glob("*.json")]
    assert len(records) == 1, done.stderr
    argv = records[0]["argv"]
    assert argv[:3] == ["-m", "tests.helpers.e2e_library", "serve"]
    assert "--address" in argv and argv[argv.index("--address") + 1] == "127.0.0.1", f"started as {argv}"


def test_an_interrupt_still_stops_the_emulator(rig):
    rig.server_up()
    proc = subprocess.Popen(rig.command("device-test.sh", "--area", "keys"), env=rig.env(FAKE_INSTRUMENT="hang"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        until(lambda: (rig.bin / "instrumenting").exists(), timeout=60)
        os.killpg(proc.pid, signal.SIGINT)  # Ctrl-C: the script and its foreground command
        _, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    assert proc.returncode != 0
    assert rig.emulators() == {}
    assert "stopped emulator-5554" in err


def test_an_emulator_deaf_to_emu_kill_is_killed_after_the_wait(rig):
    rig.server_up()
    done = rig.run("device-test.sh", "--area", "keys", FAKE_EMULATOR_DEAF="1")
    assert done.returncode == 0, done.stderr
    assert rig.emulators() == {}
    assert "device-test.sh: emulator-5554 didn't stop within 3 s of emu kill: killed it" in done.stderr


def test_the_stop_happens_while_it_still_holds_the_emulators_lock(rig):
    """The next caller can't take a dying emulator: the lock is free only once the emulator is gone."""
    rig.server_up()
    proc = subprocess.Popen(rig.command("device-test.sh", "--area", "keys"), env=rig.env(FAKE_EMULATOR_DEAF="1"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        until(lambda: (rig.bin / "emulators" / "5554.kill").exists(), timeout=60)
        assert "5554" in rig.emulators(), "emu kill asked, the emulator still up"
        with open(rig.lock, "w") as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc.communicate(timeout=60)
        assert rig.emulators() == {}
        with open(rig.lock, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_an_adb_server_it_started_is_stopped_when_no_device_is_left(rig):
    done = rig.run("device-test.sh", "--area", "keys")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] in rig.calls("adb")
    assert not rig.server
    assert "device-test.sh: stopped the adb server it started (no device left)" in done.stderr


def test_an_adb_server_that_was_running_is_left(rig):
    rig.server_up()
    done = rig.run("device-test.sh", "--area", "keys")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] not in rig.calls("adb")
    assert rig.server


def test_an_adb_server_it_started_is_left_while_a_phone_is_listed(rig):
    done = rig.run("device-test.sh", "--area", "keys", FAKE_ADB_DEVICES=f"{PHONE} device")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] not in rig.calls("adb")
    assert not any(PHONE in word for call in rig.calls("adb") for word in call), "the phone is never asked"
    assert "device-test.sh: left the adb server it started: a device is still listed" in done.stderr


def test_an_adb_server_it_started_is_left_while_another_caller_holds_an_emulator(rig):
    lock = rig.lock.parent / "caracole-emulator-5556.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done = rig.run("device-test.sh", "--area", "keys", CARACOLE_EMULATORS="2")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] not in rig.calls("adb")
    assert "left the adb server it started: another caller holds emulator-5556" in done.stderr


def test_no_adb_it_runs_holds_the_emulators_lock(rig):
    """An adb server it starts (adb forks it) would otherwise hold that emulator's flock until it dies."""
    done = rig.run("device-test.sh", "--area", "keys")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] in rig.calls("adb"), "it started the server"
    assert rig.adb_held_no_lock()


def test_an_emulator_that_died_mid_run_is_sent_nothing_and_killed_by_no_one(rig):
    rig.server_up()
    done = rig.run("device-test.sh", "--area", "keys", FAKE_INSTRUMENT="crash")
    assert ["-s", "emulator-5554", "emu", "kill"] not in rig.calls("adb"), "whatever answers there now isn't ours"
    assert "device-test.sh: emulator-5554, which it started, had stopped already: nothing to stop" in done.stderr
    assert "killed" not in done.stderr


def test_a_second_interrupt_during_the_stop_never_cuts_it_short(rig):
    rig.server_up()
    proc = subprocess.Popen(rig.command("device-test.sh", "--area", "keys"),
                            env=rig.env(FAKE_INSTRUMENT="hang", FAKE_EMULATOR_DEAF="1"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        until(lambda: (rig.bin / "instrumenting").exists(), timeout=60)
        os.killpg(proc.pid, signal.SIGINT)
        until(lambda: (rig.bin / "emulators" / "5554.kill").exists(), timeout=30)  # the stop has begun
        os.killpg(proc.pid, signal.SIGINT)
        os.killpg(proc.pid, signal.SIGTERM)
        _, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    assert rig.emulators() == {}, "stopped all the same"
    assert "emulator-5554 didn't stop within 3 s of emu kill: killed it" in err


def test_sigterm_still_stops_the_emulator(rig):
    rig.server_up()
    proc = subprocess.Popen(rig.command("device-test.sh", "--area", "keys"), env=rig.env(FAKE_INSTRUMENT="hang"),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        until(lambda: (rig.bin / "instrumenting").exists(), timeout=60)
        os.killpg(proc.pid, signal.SIGTERM)
        _, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    assert proc.returncode == 143
    assert rig.emulators() == {}
    assert "stopped emulator-5554" in err


@pytest.mark.parametrize("state", ["offline", "unauthorized"])
@pytest.mark.parametrize("serial", [PHONE, "emulator-5560"])
def test_an_adb_server_it_started_is_left_while_a_device_in_any_state_is_listed(rig, state, serial):
    done = rig.run("device-test.sh", "--area", "keys", FAKE_ADB_DEVICES=f"{serial} {state}")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] not in rig.calls("adb")
    assert rig.server
    assert "left the adb server it started: a device is still listed" in done.stderr


def test_an_adb_that_hangs_in_the_stop_is_cut_off_and_the_emulator_killed_all_the_same(rig):
    """A hung console (emu kill) and a wedged server (devices) never hold the stop, which ignores TERM, forever."""
    started = time.monotonic()
    done = rig.run("device-test.sh", "--area", "keys", FAKE_ADB_HANG="emu,devices", FAKE_ADB_HANG_AFTER_RUN="1",
                   CARACOLE_ADB_TIMEOUT="2")
    assert done.returncode == 0, done.stderr
    assert time.monotonic() - started < 60
    assert rig.emulators() == {}, "its session killed"
    assert "device-test.sh: emulator-5554 didn't stop within 3 s of emu kill, which got no answer: killed it" \
        in done.stderr
    assert "device-test.sh: left the adb server it started: adb devices got no answer" in done.stderr
    assert ["kill-server"] not in rig.calls("adb")
    with open(rig.lock, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released


# device-test.sh: the chords lane's --data, --models, --ml and --tcpdump


DATA = "/data/local/tmp/caracole-data"
MODELS = "/data/local/tmp/caracole-models"


def lane_env(rig, tmp_path, **env):
    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    (models / "btc-graph.onnx").write_bytes(b"onnx")
    (models / "beats.onnx").write_bytes(b"onnx")
    return {"CARACOLE_CHORD_MODELS": str(models), **env}


def data_folder(tmp_path):
    data = tmp_path / "songs"
    data.mkdir(exist_ok=True)
    (data / "a.m4a").write_bytes(b"audio")
    (data / "meta.json").write_text("{}")
    return data


def index_of(calls, call):
    return max(i for i, c in enumerate(calls) if c == call)


def assert_data_removed_before_the_emulator_stopped(rig):
    calls = rig.calls("adb")
    rm = ["-s", "emulator-5554", "shell", "rm", "-rf", DATA]
    clear = ["-s", "emulator-5554", "shell", "pm", "clear", "io.github.danielhp95.caracole.ml.test"]
    kill = ["-s", "emulator-5554", "emu", "kill"]
    assert index_of(calls, rm) < index_of(calls, kill), "the private data goes while the emulator is still up"
    assert index_of(calls, clear) < index_of(calls, kill)
    assert rig.emulators() == {}


@pytest.mark.parametrize("how, code", [("ok", 0), ("fail", 1)])
def test_data_is_removed_before_the_emulator_it_started_is_stopped(rig, tmp_path, how, code):
    rig.server_up()
    done = rig.run("device-test.sh", "--data", str(data_folder(tmp_path)),
                   **lane_env(rig, tmp_path, FAKE_INSTRUMENT=how))
    assert done.returncode == code, done.stderr
    assert ["-s", "emulator-5554", "push", str(tmp_path / "songs" / "a.m4a"), f"{DATA}/a.m4a"] in rig.calls("adb")
    assert_data_removed_before_the_emulator_stopped(rig)
    assert "stopped emulator-5554, which it started" in done.stderr


def test_an_interrupt_removes_the_data_before_the_emulator_is_stopped(rig, tmp_path):
    rig.server_up()
    proc = subprocess.Popen(rig.command("device-test.sh", "--data", str(data_folder(tmp_path))),
                            env=rig.env(**lane_env(rig, tmp_path, FAKE_INSTRUMENT="hang")),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        until(lambda: (rig.bin / "instrumenting").exists(), timeout=60)
        os.killpg(proc.pid, signal.SIGINT)
        _, err = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    assert proc.returncode != 0
    assert_data_removed_before_the_emulator_stopped(rig)
    assert "stopped emulator-5554" in err


def test_a_hung_adb_in_the_data_cleanup_never_keeps_the_emulator_up(rig, tmp_path):
    rig.server_up()
    done = rig.run("device-test.sh", "--data", str(data_folder(tmp_path)),
                   **lane_env(rig, tmp_path, FAKE_ADB_HANG="rm", CARACOLE_ADB_TIMEOUT="2"))
    assert done.returncode == 0, done.stderr
    assert rig.emulators() == {}
    assert "stopped emulator-5554, which it started" in done.stderr


@pytest.mark.parametrize("flags", [["--models", "--area", "keys"], ["--ml"]])
def test_the_model_cache_is_left_on_the_emulator(rig, tmp_path, flags):
    rig.server_up()
    done = rig.run("device-test.sh", *flags, **lane_env(rig, tmp_path))
    assert done.returncode == 0, done.stderr
    assert ["-s", "emulator-5554", "push", str(tmp_path / "models" / "btc-graph.onnx"),
            f"{MODELS}/btc-graph.onnx"] in rig.calls("adb")
    assert not any("rm" in c and any(MODELS in w for w in c) for c in rig.calls("adb")), "a cache for the next run"
    assert not any(c[-1:] == [DATA] for c in rig.calls("adb")), "no --data, nothing of it"
    assert rig.emulators() == {}


def test_tcpdump_parses_and_a_run_that_stops_on_it_still_stops_the_emulator(rig, tmp_path):
    rig.server_up()
    done = rig.run("device-test.sh", "--tcpdump", str(tmp_path / "out.pcap"), "--area", "keys")
    assert done.returncode == 3
    assert "--tcpdump needs a rooted emulator" in done.stderr
    assert rig.emulators() == {}
    assert "stopped emulator-5554, which it started" in done.stderr


def test_an_unknown_option_prints_the_usage_with_every_flag(rig):
    done = rig.run("device-test.sh", "--nope")
    assert done.returncode == 2
    for flag in ("--ml", "--models", "--data DIR", "--youtube", "--tcpdump FILE", "--keep-emulator", "--sites"):
        assert flag in done.stdout
    assert rig.calls("nix") == []


# device-test.sh: the YouTube lane's --youtube


YOUTUBE_CLASSES = ["YtDlpVersionTest", "QjsTest", "YtDlpServiceTest", "KillTest", "GateServiceTest",
                   "AcrossProcessesTest"]


def test_youtube_runs_its_classes_and_the_apps_and_stops_the_emulator(rig):
    rig.server_up()
    clip = rig.android / "youtube" / "src" / "androidTest" / "assets" / "youtube" / "clip.m4a"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"m4a")
    done = rig.run("device-test.sh", "--youtube")
    assert done.returncode == 0, done.stderr
    calls = rig.calls("adb")
    ns = "io.github.danielhp95.caracole"
    apk = str(rig.android / "youtube" / "build" / "outputs" / "apk" / "androidTest" / "debug"
              / "youtube-debug-androidTest.apk")
    assert ["-s", "emulator-5554", "install", "-r", "-t", apk] in calls
    for name in YOUTUBE_CLASSES:
        assert ["-s", "emulator-5554", "shell", "am", "instrument", "-w", "-e", "class", f"{ns}.youtube.{name}",
                f"{ns}.youtube.test/{ns}.youtube.YoutubeTestRunner"] in calls, name
    for name in ("YouTubeBenchTest", "YtDlpEngineTest"):
        assert any(c[:9] == ["-s", "emulator-5554", "shell", "am", "instrument", "-w", "-e", "class", f"{ns}.{name}"]
                   and "clip" in c for c in calls), name
    assert any(":youtube:assembleDebugAndroidTest" in c for c in rig.calls("nix"))
    for name in YOUTUBE_CLASSES + ["YouTubeBenchTest", "YtDlpEngineTest"]:
        assert f"PASS {name}" in done.stdout
    assert rig.emulators() == {}
    assert "stopped emulator-5554, which it started" in done.stderr


# stop-all.sh


def test_stop_all_with_nothing_running_says_so_and_exits_0(stop_rig):
    done = stop_rig.run("stop-all.sh")
    assert done.returncode == 0, done.stderr
    assert "stop-all.sh: no emulator of the pool is running" in done.stdout
    assert "stop-all.sh: no Gradle daemon is running" in done.stdout
    assert "stop-all.sh: no adb server was running" in done.stdout
    assert not stop_rig.server, "the server its own look started is stopped again"
    assert stop_rig.calls("nix") == []
    assert all(c[:1] == ["-u"] and c[1] == str(os.getuid()) for c in stop_rig.calls("ps")), "this user's alone"


def test_stop_all_stops_every_free_pool_emulator_and_the_adb_server(stop_rig):
    stop_rig.server_up()
    stop_rig.emulator_up(5554)
    stop_rig.emulator_up(5556)
    done = stop_rig.run("stop-all.sh", CARACOLE_EMULATORS="3")
    assert done.returncode == 0, done.stderr
    assert stop_rig.emulators() == {}
    assert "stop-all.sh: stopped emulator-5554" in done.stdout
    assert "stop-all.sh: stopped emulator-5556" in done.stdout
    assert ["kill-server"] in stop_rig.calls("adb")
    assert "stop-all.sh: stopped the adb server (no device listed)" in done.stdout
    assert stop_rig.adb_held_no_lock(), "no adb it runs holds a pool lock"
    again = stop_rig.run("stop-all.sh", CARACOLE_EMULATORS="3")
    assert again.returncode == 0 and "no emulator of the pool is running" in again.stdout, "idempotent"


def test_stop_all_without_gradle_leaves_the_daemons_and_says_they_idle_out(stop_rig):
    stop_rig.server_up()
    done = stop_rig.run("stop-all.sh", FAKE_GRADLE_DAEMONS="4242 4343")
    assert done.returncode == 0, done.stderr
    assert stop_rig.calls("nix") == [], "no gradle --status, no gradle --stop"
    assert "stop-all.sh: left 2 Gradle daemon(s): each stops by itself after two idle minutes (--gradle stops them " \
        "now)" in done.stdout


def test_stop_all_with_gradle_stops_them_when_every_one_is_idle(stop_rig):
    stop_rig.server_up()
    status = STATUS.format(lines="  4242 IDLE     8.14.4\n  4343 IDLE     8.14.4")
    done = stop_rig.run("stop-all.sh", "--gradle", FAKE_GRADLE_DAEMONS="4242 4343", FAKE_GRADLE_STATUS=status)
    assert done.returncode == 0, done.stderr
    assert stop_rig.calls("nix") == [
        ["develop", str(stop_rig.android), "-c", "gradle", "-p", str(stop_rig.android), "--status"],
        ["develop", str(stop_rig.android), "-c", "gradle", "-p", str(stop_rig.android), "--stop"]]
    assert "stop-all.sh: stopped 2 idle Gradle daemon(s) (gradle --stop)" in done.stdout


@pytest.mark.parametrize("lines, rc", [
    ("  4242 IDLE     8.14.4\n  4343 BUSY     8.14.4", "0"),   # a build running in another checkout
    ("  4242 IDLE     8.14.4", "0"),                           # one it can't read the state of
])
def test_stop_all_with_gradle_refuses_while_a_daemon_is_busy_or_unknown(stop_rig, lines, rc):
    stop_rig.server_up()
    done = stop_rig.run("stop-all.sh", "--gradle", FAKE_GRADLE_DAEMONS="4242 4343",
                        FAKE_GRADLE_STATUS=STATUS.format(lines=lines) if lines else "", FAKE_GRADLE_STATUS_RC=rc)
    assert done.returncode == 0, done.stderr
    assert not any("--stop" in c for c in stop_rig.calls("nix"))
    assert "stop-all.sh: left 2 Gradle daemon(s):" in done.stdout and "busy" in done.stdout


@pytest.mark.parametrize("lines", ["", "  4242 IDLE     8.14.4\n  4343 IDLE     8.14.4"])
def test_stop_all_with_gradle_refuses_when_gradle_status_fails(stop_rig, lines):
    stop_rig.server_up()
    done = stop_rig.run("stop-all.sh", "--gradle", FAKE_GRADLE_DAEMONS="4242 4343",
                        FAKE_GRADLE_STATUS=STATUS.format(lines=lines), FAKE_GRADLE_STATUS_RC="1")
    assert done.returncode == 0, done.stderr
    assert not any("--stop" in c for c in stop_rig.calls("nix"))
    assert "stop-all.sh: left 2 Gradle daemon(s): gradle --status failed, so none is known idle" in done.stdout


def test_stop_all_cuts_off_an_adb_that_hangs_and_kills_the_emulator_all_the_same(stop_rig):
    stop_rig.server_up()
    stop_rig.emulator_up(5554)
    started = time.monotonic()
    done = stop_rig.run("stop-all.sh", FAKE_ADB_HANG="emu,devices", CARACOLE_ADB_TIMEOUT="2")
    assert done.returncode == 0, done.stderr
    assert time.monotonic() - started < 60
    assert stop_rig.emulators() == {}
    assert "stop-all.sh: emulator-5554 didn't stop within 3 s of emu kill, which got no answer: killed it" \
        in done.stdout
    assert "stop-all.sh: left the adb server: adb devices got no answer" in done.stdout
    assert ["kill-server"] not in stop_rig.calls("adb")


def test_stop_all_matches_the_processes_themselves_never_a_command_line_quoting_them(stop_rig):
    stop_rig.server_up()
    decoys = "\n".join([
        "777 bash bash -c pgrep -f qemu-system.*-port 5554 qemu-system-x86_64 -port 5554",
        "778 vim vim org.gradle.launcher.daemon.bootstrap.GradleDaemon",
    ])
    done = stop_rig.run("stop-all.sh", FAKE_PS_EXTRA=decoys)
    assert done.returncode == 0, done.stderr
    assert "no emulator of the pool is running" in done.stdout
    assert "no Gradle daemon is running" in done.stdout
    assert ["-s", "emulator-5554", "emu", "kill"] not in stop_rig.calls("adb")


def test_stop_all_leaves_an_emulator_whose_lock_another_caller_holds(stop_rig):
    stop_rig.server_up()
    stop_rig.emulator_up(5554)
    stop_rig.lock.parent.mkdir(parents=True, exist_ok=True)
    with open(stop_rig.lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done = stop_rig.run("stop-all.sh")
    assert done.returncode == 0, done.stderr
    assert "5554" in stop_rig.emulators()
    assert ["-s", "emulator-5554", "emu", "kill"] not in stop_rig.calls("adb")
    assert "stop-all.sh: left emulator-5554: another caller holds its lock" in done.stdout
    assert ["kill-server"] not in stop_rig.calls("adb"), "a device is listed"


def test_stop_all_leaves_the_adb_server_while_a_caller_holds_a_pool_lock_with_nothing_listed_yet(stop_rig):
    """An emulator early in its boot isn't listed yet: its caller holds the lock."""
    stop_rig.server_up()
    stop_rig.lock.parent.mkdir(parents=True, exist_ok=True)
    with open(stop_rig.lock.parent / "caracole-emulator-5556.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done = stop_rig.run("stop-all.sh", CARACOLE_EMULATORS="3")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] not in stop_rig.calls("adb")
    assert stop_rig.server
    assert "stop-all.sh: left the adb server: another caller holds emulator-5556" in done.stdout


@pytest.mark.parametrize("state", ["device", "offline", "unauthorized"])
def test_stop_all_never_stops_the_adb_server_while_a_phone_in_any_state_is_listed(stop_rig, state):
    stop_rig.server_up()
    done = stop_rig.run("stop-all.sh", FAKE_ADB_DEVICES=f"{PHONE} {state}")
    assert done.returncode == 0, done.stderr
    assert ["kill-server"] not in stop_rig.calls("adb")
    assert stop_rig.server
    assert f"stop-all.sh: left the adb server: {PHONE} is listed" in done.stdout
    assert not any(PHONE in word for call in stop_rig.calls("adb") for word in call)


def test_stop_all_kills_an_emulator_deaf_to_emu_kill_after_the_wait(stop_rig):
    stop_rig.server_up()
    stop_rig.emulator_up(5554, FAKE_EMULATOR_DEAF="1")
    done = stop_rig.run("stop-all.sh")
    assert done.returncode == 0, done.stderr
    assert stop_rig.emulators() == {}
    assert "stop-all.sh: emulator-5554 didn't stop within 3 s of emu kill: killed it" in done.stdout


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="needs shellcheck")
@pytest.mark.parametrize("name", ["device-test.sh", "stop-all.sh"])
def test_shellcheck_finds_no_warning(name):
    done = subprocess.run(["shellcheck", "-S", "warning", str(SCRIPTS / name)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout
