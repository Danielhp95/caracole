"""Shared fixtures: a fresh database, a config rooted in tmp_path, and fake HTTP. And how the
suite runs: tmp_path in memory, and the whole suite on several cores (pytest-xdist)."""

from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest

# tmp_path goes to a tmpfs unless --basetemp or PYTEST_DEBUG_TEMPROOT says otherwise. caracole
# fsyncs every file it keeps and sqlite every commit: a few milliseconds each on a disk, nothing
# in memory, and the suite runs nearly three times faster. pyproject.toml keeps only the folders
# of tests that failed.
MEMORY = Path("/dev/shm")
# What MEMORY must have free. Docker and podman give a container's /dev/shm 64 MB, and the
# Chromium of each test process wants its share of it too.
MEMORY_FREE = 1 << 30
# Workers for -n auto. Each imports and collects the whole suite before its first test, and past
# a dozen they cost more than they save: on 24 cores, the suite takes 6.5 s on 12, 8 s on 24.
MAX_WORKERS = 12


@pytest.hookimpl(tryfirst=True)  # before pytest-xdist's own, which reads -n and --dist
def pytest_cmdline_main(config):
    """With pytest-xdist: the whole suite (pytest given no paths) runs on -n auto workers unless
    -n says otherwise, and tests go to the workers by work stealing (--dist worksteal), so no
    worker is left with all of a file's browser tests. Given paths, pytest runs them in this
    process, which starts sooner; and so it does with --pdb, --trace or -s, which want this
    terminal, and with -m autochords, the model tests."""
    option = config.option
    if not config.pluginmanager.hasplugin("xdist") or hasattr(config, "workerinput"):
        return
    whole_suite = config.args_source == pytest.Config.ArgsSource.TESTPATHS
    at_the_terminal = option.usepdb or option.trace or option.capture == "no"
    # The model tests load torch, librosa and beat_this: a gigabyte or more in every worker.
    models = option.markexpr.strip() == "autochords"
    if (option.numprocesses is None and not option.tx and whole_suite and not option.collectonly
            and not at_the_terminal and not models):
        option.numprocesses = "auto"
    if option.dist == "no" and (option.numprocesses or option.tx):
        option.dist = "worksteal"


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config):
    if os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return None  # pytest-xdist's own hook reads it
    return min(len(os.sched_getaffinity(0)), MAX_WORKERS)


def pytest_configure(config):
    if config.option.basetemp or os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return
    if memory_will_do():
        # Read when the first tmp_path is made; pytest-xdist's workers make theirs in this one's.
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(MEMORY)


def memory_will_do() -> bool:
    """Whether tmp_path can go to MEMORY: a folder this user can write, mounted so that the
    programs a test writes there run (a fake chordpro), with MEMORY_FREE to spare. Docker and
    podman mount /dev/shm noexec, and so do hardened hosts: tmp_path then stays on disk."""
    try:
        mounted = os.statvfs(MEMORY)
    except OSError:
        return False
    return (MEMORY.is_dir() and os.access(MEMORY, os.W_OK | os.X_OK)
            and not mounted.f_flag & os.ST_NOEXEC
            and mounted.f_bavail * mounted.f_frsize >= MEMORY_FREE)


def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("chordpro") or item.get_closest_marker("autochords"):
            item.add_marker(pytest.mark.slow)


def pytest_collection_finish(session):
    # What collection made (every module, test and fixture) lives until the session ends: frozen,
    # the garbage collector stops walking it on each pass, and the quick loop ends half a second
    # sooner.
    gc.freeze()


# --- fixtures ----------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _chromium_profiles(tmp_path_factory):
    """This process's browser keeps its profile in the run's basetemp, and quits when the session
    ends."""
    from helpers import browser

    browser.profiles = tmp_path_factory.mktemp("chromium")
    yield
    browser.close()


@pytest.fixture
def _chromium(_chromium_profiles):
    """What a test marked @in_chromium gets (helpers/browser.py): the profiles' folder, and the
    right to open pages, which a test without the mark is refused
    (``browser.require_in_chromium``)."""
    from helpers import browser

    browser.marked = True
    yield
    browser.marked = False


@pytest.fixture(autouse=True)
def _no_real_yt_dlp(monkeypatch, tmp_path_factory):
    """No test runs a real yt-dlp. In `nix develop .#autochords` torch imports, the model paths
    are set and yt-dlp is on PATH, so a command reading the real environment would find the
    YouTube route on (youtube_fetch.route_problem); with ``CARACOLE_YTDLP_BIN`` naming no
    program, it finds yt-dlp missing instead. A test that wants the route sets ``ytdlp_bin``
    to a ``FakeYtDlp`` (helpers/fake_ytdlp.py), which wins over the variable."""
    monkeypatch.setenv("CARACOLE_YTDLP_BIN", str(tmp_path_factory.getbasetemp() / "no-real-yt-dlp-in-tests"))


_migrated: dict[tuple, bytes] = {}


def migrated_database() -> bytes:
    """A new database's bytes, made once per process by db.connect for the migrations it has now
    (a test may have patched them)."""
    from caracole import db

    key = (db.SCHEMA_VERSION, tuple(sorted(db._MIGRATIONS.items())))
    if key not in _migrated:
        import tempfile

        with tempfile.TemporaryDirectory(dir=os.environ.get("PYTEST_DEBUG_TEMPROOT")) as tmp:
            path = Path(tmp) / "caracole.sqlite"
            db.connect(path).close()  # the last connection to close folds the WAL into the file
            _migrated[key] = path.read_bytes()
    return _migrated[key]


@pytest.fixture
def conn(tmp_path: Path):
    """A connection to tmp_path/state/caracole.sqlite: a copy of a database db.connect made, so
    the migrations run once per process rather than once per test."""
    from caracole import db

    path = tmp_path / "state" / "caracole.sqlite"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)  # sqlite's own mode
        with open(fd, "wb") as f:
            f.write(migrated_database())
    c = db.connect(path)
    yield c
    c.close()


@pytest.fixture
def cfg(tmp_path: Path):
    from caracole.config import load_config

    return load_config(
        None,
        env={
            "HOME": str(tmp_path / "home"),
            "STATE_DIRECTORY": str(tmp_path / "state"),
            "CACHE_DIRECTORY": str(tmp_path / "cache"),
        },
    )


def add_song(conn, artist="Soda Stereo", title="De Música Ligera", *, added_at="2026-10-01T00:00:00Z",
             duration_ms=213000, album=None, source="wanted", source_id=None, artists=None):
    """Insert a song through the repository and return it."""
    from caracole.songs import get_song, upsert_song

    song_id, _ = upsert_song(
        conn,
        artists=artists or [artist],
        title=title,
        album=album,
        duration_ms=duration_ms,
        isrc=None,
        source=source,
        source_id=source_id or f"{artist}/{title}",
        added_at=added_at,
    )
    return get_song(conn, song_id)


def subprocess_pythonpath(src) -> str:
    """PYTHONPATH for a child Python: ``src`` first, then the inherited path (inside a
    Nix build the dependencies arrive on PYTHONPATH)."""
    return os.pathsep.join(p for p in (str(src), os.environ.get("PYTHONPATH")) if p)
