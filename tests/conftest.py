"""Shared fixtures: a fresh database, a config rooted in tmp_path, and fake HTTP."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _no_real_yt_dlp(monkeypatch, tmp_path_factory):
    """No test runs a real yt-dlp. In `nix develop .#autochords` torch imports, the model paths
    are set and yt-dlp is on PATH, so a command reading the real environment would find the
    YouTube route on (youtube_fetch.route_problem); with ``CARACOLE_YTDLP_BIN`` naming no
    program, it finds yt-dlp missing instead. A test that wants the route sets ``ytdlp_bin``
    to a ``FakeYtDlp`` (helpers/fake_ytdlp.py), which wins over the variable."""
    monkeypatch.setenv("CARACOLE_YTDLP_BIN", str(tmp_path_factory.getbasetemp() / "no-real-yt-dlp-in-tests"))


@pytest.fixture(autouse=True)
def _forget_the_logs_secrets():
    """The log keeps the secrets a command's config read for the life of the process; a test's
    ("secret", say) must not hide words from the next test's output."""
    yield
    from caracole import logs

    logs.forget_secrets()


@pytest.fixture
def conn(tmp_path: Path):
    from caracole import db

    c = db.connect(tmp_path / "state" / "caracole.sqlite")
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
    import os

    return os.pathsep.join(p for p in (str(src), os.environ.get("PYTHONPATH")) if p)
