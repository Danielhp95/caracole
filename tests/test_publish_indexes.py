"""nix/publish-indexes.sh, run against a fake ``gh`` (helpers/fake_gh.py) and the real
``caracole index publish --kept``: no test reaches GitHub."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import subprocess_pythonpath
from helpers.fake_gh import FakeGh

from caracole import db

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "nix" / "publish-indexes.sh"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs bash and jq"),
]

SCHEMA = db.SCHEMA_VERSION
NEW = f"indexes-s{SCHEMA}-20261124T0312Z.sqlite.gz"


def name(day: int, schema: int = SCHEMA) -> str:
    return f"indexes-s{schema}-202611{day:02d}T0312Z.sqlite.gz"


class Rig:
    def __init__(self, tmp_path: Path, data: bytes | None = None):
        self.tmp = tmp_path
        self.gh = FakeGh(tmp_path / "bin")
        caracole = tmp_path / "bin" / "caracole"
        caracole.write_text(f"#!{sys.executable}\nfrom caracole.cli import main\nmain()\n", encoding="utf-8")
        caracole.chmod(0o755)
        self.dir = tmp_path / "out"
        self.dir.mkdir()
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.data = gzip.compress(b"a small catalogue", mtime=0) if data is None else data
        (self.dir / NEW).write_bytes(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()
        (self.dir / "published.json").write_text(json.dumps({
            "file": NEW, "schema": SCHEMA, "made": "2026-11-24T03:12:00Z", "bytes": len(self.data),
            "raw_bytes": 17, "sha256": self.sha, "sites": {}}), encoding="utf-8")

    def env(self, **env: str) -> dict[str, str]:
        full = {**os.environ, "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
                "PYTHONPATH": subprocess_pythonpath(ROOT / "src"), "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home), "XDG_STATE_HOME": str(self.home), "XDG_CACHE_HOME": str(self.home),
                "XDG_DATA_HOME": str(self.home), "CARACOLE_SERVICE_FILE": str(self.tmp / "no-service"),
                "REPO": "o/r", "TAG": "indexes", **env}
        full.pop("GH_TOKEN", None) if "GH_TOKEN" not in env else None
        return full

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SCRIPT), *args, str(self.dir)], env=self.env(**env), capture_output=True,
                              text=True, timeout=120)

    def start(self, **env: str) -> subprocess.Popen:
        """The script started, its stdout a pipe to read as it goes (bytes)."""
        return subprocess.Popen(["bash", str(SCRIPT), str(self.dir)], env=self.env(**env), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_a_first_publish_makes_the_release_a_prerelease_says_each_step_and_uploads(rig):
    done = rig.run()
    assert done.returncode == 0, done.stderr
    rig.gh.load()
    # A prerelease is never the repository's Latest (/releases/latest), as a release with no other full one
    # would be whatever --latest=false asked; the phone reads the tag.
    assert "--prerelease" in rig.gh.state["release"]["args"] and rig.gh.state["release"]["prerelease"]
    assert rig.gh.names() == [NEW]
    assert done.stdout.splitlines() == [
        "publish-indexes: reading the release indexes of o/r...",
        "publish-indexes: creating the release indexes, a prerelease, so that it is never the repository's Latest...",
        f"publish-indexes: uploading {NEW} ({len(rig.data)} bytes) to o/r, release indexes...",
        "publish-indexes: checking the upload against published.json...",
        "publish-indexes: applying the Keep rule to 1 asset...",
        f"publish-indexes: published {NEW}",
    ]


def test_a_release_that_isnt_a_prerelease_is_made_one(rig):
    rig.gh.release(prerelease=False)
    done = rig.run()
    assert done.returncode == 0, done.stderr
    rig.gh.load()
    assert rig.gh.state["release"]["prerelease"]
    assert "publish-indexes: marking the release indexes a prerelease, so that it is never the repository's " \
           "Latest..." in done.stdout.splitlines()
    assert [c["argv"][:3] for c in rig.gh.calls() if c["argv"][:2] == ["release", "edit"]] == [
        ["release", "edit", "indexes"]]
    again = rig.run()
    assert again.returncode == 0 and "marking" not in again.stdout
    assert len([c for c in rig.gh.calls() if c["argv"][:2] == ["release", "edit"]]) == 1


def test_a_release_that_cant_be_made_a_prerelease_fails_before_anything_is_uploaded(rig):
    rig.gh.release(prerelease=False)
    done = rig.run(FAKE_GH_FAIL="edit:1")
    assert done.returncode == 1
    assert "step 1: the release indexes can't be made a prerelease" in done.stderr
    assert rig.gh.names() == []


def test_a_half_upload_left_behind_is_deleted_first(rig):
    rig.gh.asset(name(10), state="starter").asset(name(11))
    done = rig.run()
    assert done.returncode == 0, done.stderr
    assert name(10) not in rig.gh.names()
    assert NEW in rig.gh.names()


def test_an_existing_name_is_refused(rig):
    rig.gh.asset(NEW, b"another file").asset(name(11))
    done = rig.run()
    assert done.returncode == 1
    assert "different file" in done.stderr
    assert rig.gh.names() == sorted([NEW, name(11)])


def test_the_same_file_again_is_already_published(rig):
    rig.gh.asset(NEW, rig.data)
    done = rig.run()
    assert done.returncode == 0
    assert "already published" in done.stdout
    assert not [c for c in rig.gh.calls() if c["argv"][:2] == ["release", "upload"]]
    assert rig.gh.names() == [NEW]


def test_a_digest_that_differs_is_deleted_and_fails(rig):
    rig.gh.release()
    rig.gh.state["corrupt_upload"] = True
    rig.gh.save()
    done = rig.run()
    assert done.returncode == 1
    assert "digest" in done.stderr
    assert rig.gh.names() == []


def test_pruning_deletes_only_what_the_keep_rule_names(rig):
    old = [name(d) for d in (1, 2, 3)]
    for n in old:
        rig.gh.asset(n)
    rig.gh.asset("indexes.json", b"{}").asset("notes.txt")
    done = rig.run()
    assert done.returncode == 0, done.stderr
    # the schema's two newest stay (the new file and the 3rd), the others go; names that aren't files stay
    assert rig.gh.names() == sorted([NEW, name(3), "indexes.json", "notes.txt"])


def test_a_failed_upload_leaves_last_weeks_file_listed(rig):
    rig.gh.asset(name(17))
    done = rig.run(FAKE_GH_FAIL="upload:1")
    assert done.returncode == 1
    assert "can't be uploaded" in done.stderr
    assert rig.gh.names() == [name(17)]


def test_an_asset_of_its_name_listed_with_no_digest_is_deleted_and_uploaded_again(rig):
    """A digest-less asset of the file's name can't be checked: never taken for another file (which would fail every
    run after), it is deleted and the file uploaded again."""
    for there in (rig.data, b"half of it"):
        rig.gh.state = {**rig.gh.state, "assets": []}
        rig.gh.save()
        rig.gh.asset(NEW, there, no_digest=True)
        done = rig.run()
        assert done.returncode == 0, done.stderr
        assert f"publish-indexes: GitHub lists {NEW} with no digest, so it can't be checked: deleting it to upload " \
               "it again..." in done.stdout.splitlines()
        rig.gh.load()
        (asset,) = rig.gh.state["assets"]
        assert asset["name"] == NEW and asset["digest"] == "sha256:" + rig.sha
        assert rig.gh.content(NEW) == rig.data


def test_no_digest_on_the_read_back_keeps_the_upload_and_fails(rig):
    rig.gh.release()
    rig.gh.state["no_digest"] = True
    rig.gh.save()
    done = rig.run()
    assert done.returncode == 1
    assert "no digest" in done.stderr
    assert rig.gh.names() == [NEW]


def test_an_uploader_of_an_older_schema_never_prunes_what_the_newer_schema_keeps(rig):
    """The release holds a newer schema's files than this caracole's (another caracole published them): the newer
    schema is the one publishing, so its two newest stay, as its own caracole's upload would keep them."""
    newer = [name(d, SCHEMA + 1) for d in (1, 2, 3)]
    for n in newer:
        rig.gh.asset(n)
    done = rig.run()
    assert done.returncode == 0, done.stderr
    names = rig.gh.names()
    assert newer[1] in names and newer[2] in names
    assert newer[0] not in names and f"publish-indexes: pruned {newer[0]}" in done.stdout.splitlines()


def big(tmp_path) -> Rig:
    """A rig whose file is 400 KB, so that a slow fake gh's quarters are 100 KB."""
    return Rig(tmp_path, data=random.Random(0).randbytes(400 * 1024))


def ticks(done: subprocess.CompletedProcess) -> list[str]:
    return [line for line in done.stdout.splitlines() if line.startswith("publish-indexes: uploading \u00b7")]


def test_a_slow_upload_says_every_tick_how_far_gh_has_read_the_file_and_its_size(tmp_path):
    rig = big(tmp_path)
    done = rig.run(FAKE_GH_SLOW="1.5", TICK="1")
    assert done.returncode == 0, done.stderr
    said = ticks(done)
    assert said, done.stdout
    read = [re.fullmatch(r"publish-indexes: uploading \u00b7 (\d+) of 400 KB \u00b7 (\d+) s so far, "
                         r"about (\d+) s left", line) for line in said]
    assert any(read), said  # gh's file read a quarter at a time: its position, read from /proc
    assert {int(m.group(1)) for m in read if m} <= {100, 200, 300}
    assert all(m or re.fullmatch(r"publish-indexes: uploading \u00b7 all 400 KB read \u00b7 \d+ s so far, "
                                 r"waiting for GitHub", line) for m, line in zip(read, said))
    lines = done.stdout.splitlines()
    assert lines.index(f"publish-indexes: uploading {NEW} (400 KB) to o/r, release indexes...") < \
        lines.index(said[0]) < lines.index("publish-indexes: checking the upload against published.json...")
    assert rig.gh.content(NEW) == rig.data


def test_an_upload_whose_file_gh_hasnt_opened_says_the_time_so_far_and_the_size(tmp_path):
    rig = big(tmp_path)
    done = rig.run(FAKE_GH_WAIT="2.5", TICK="1")
    assert done.returncode == 0, done.stderr
    said = ticks(done)
    assert said and all(re.fullmatch(r"publish-indexes: uploading \u00b7 \d+ s so far \(400 KB\)", line)
                        for line in said), said


def test_a_failed_slow_upload_still_fails_with_its_step(tmp_path):
    rig = big(tmp_path)
    rig.gh.asset(name(17))
    done = rig.run(FAKE_GH_FAIL="upload:1", TICK="1")
    assert done.returncode == 1 and "step 4" in done.stderr and "can't be uploaded" in done.stderr
    assert rig.gh.names() == [name(17)]


def until_a_tick(proc: subprocess.Popen, within: float = 30) -> list[str]:
    """The script's lines up to its first tick of the upload's progress."""
    lines, rest, end = [], b"", time.monotonic() + within
    while time.monotonic() < end:
        if select.select([proc.stdout], [], [], 0.2)[0]:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            *whole, rest = (rest + chunk).split(b"\n")
            lines += [line.decode() for line in whole]
            if any(line.startswith("publish-indexes: uploading \u00b7") for line in lines):
                return lines
    raise AssertionError(f"no tick within {within} s: {lines}")


def running(*marks: str, but: int | None = None) -> list[int]:
    """The processes whose command line holds every one of ``marks``, but ``but``, and no zombie."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == but:
            continue
        try:
            line = (entry / "cmdline").read_bytes()
            state = (entry / "stat").read_text().rsplit(") ", 1)[1].split()[0]
        except (OSError, IndexError):
            continue
        if all(m.encode() in line for m in marks) and state != "Z":
            found.append(int(entry.name))
    return found


def none_within(seconds: float, find) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not find():
            return True
        time.sleep(0.1)
    return not find()


def ended(rig: Rig, proc: subprocess.Popen) -> None:
    """Whatever of the run is left (the script, its ticker, gh) ended, and its pipe closed."""
    for pid in [proc.pid, *running(str(rig.dir))]:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(timeout=10)
    proc.stdout.close()


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="needs /proc")
def test_the_ticker_stops_once_the_script_is_gone(tmp_path):
    """Killed mid-upload, the script can't end its ticker: the ticker sees it gone at its next tick and ends, though
    gh still uploads."""
    rig = big(tmp_path)
    proc = rig.start(FAKE_GH_SLOW="3", TICK="1")
    try:
        until_a_tick(proc)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
        assert running(str(rig.tmp / "bin" / "gh"))  # gh still at it
        assert none_within(5, lambda: running(str(SCRIPT), str(rig.dir))), "the ticker still runs"
    finally:
        ended(rig, proc)


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="needs /proc")
def test_the_ticker_stops_once_gh_is_gone_though_the_script_cant_end_it(tmp_path):
    """gh gone (here killed while the script is stopped, so a zombie no one reaps): the ticker ends at its next tick."""
    rig = big(tmp_path)
    proc = rig.start(FAKE_GH_SLOW="3", TICK="1")
    try:
        until_a_tick(proc)
        (gh,) = running(str(rig.tmp / "bin" / "gh"))
        os.kill(proc.pid, signal.SIGSTOP)
        os.kill(gh, signal.SIGKILL)
        assert none_within(5, lambda: running(str(SCRIPT), str(rig.dir), but=proc.pid)), "the ticker still runs"
    finally:
        ended(rig, proc)


def test_pruning_runs_on_the_services_machine(rig):
    """The owner's user runs it beside the service: the marker names another state_dir, and --kept still answers."""
    marker = rig.tmp / "service"
    marker.write_text(f'state_dir = "{rig.tmp / "svc-state"}"\nlibrary_dir = "{rig.tmp / "svc-lib"}"\n')
    for n in (name(1), name(2), name(3)):
        rig.gh.asset(n)
    done = rig.run(CARACOLE_SERVICE_FILE=str(marker))
    assert done.returncode == 0, done.stderr
    assert rig.gh.names() == sorted([NEW, name(3)])
