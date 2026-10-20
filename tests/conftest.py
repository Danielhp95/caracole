"""Shared fixtures: a fresh database, a config rooted in tmp_path, and fake HTTP. And how the
suite runs: tmp_path in memory."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# tmp_path goes to a tmpfs unless --basetemp or PYTEST_DEBUG_TEMPROOT says otherwise. caracole
# fsyncs every file it keeps and sqlite every commit: a few milliseconds each on a disk, nothing
# in memory, and the suite runs nearly three times faster. pyproject.toml keeps only the folders
# of tests that failed.
MEMORY = Path("/dev/shm")


def pytest_configure(config):
    if config.option.basetemp or os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return
    if MEMORY.is_dir() and os.access(MEMORY, os.W_OK | os.X_OK):
        # Read when the first tmp_path is made; pytest-xdist's workers make theirs in this one's.
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(MEMORY)


# --- fixtures ----------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _forget_the_logs_secrets():
    """The log keeps the secrets a command's config read for the life of the process; a test's
    ("secret", say) must not hide words from the next test's output."""
    yield
    from caracole import logs

    logs.forget_secrets()


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
