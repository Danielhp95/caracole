"""``caracole ug --directory``, run through the CLI, and what a search finds after it: the live 宋冬野 case end to end.

UG is ``FakeDirectory`` (helpers/ug_bands.py: its letter listings, and helpers/ug_pages.py's ``FakeUG`` for 宋冬野's
page), handed to the client through ``caracole.commands._common.transport_for``, so no request reaches the network.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import get_state
from caracole.search import find_index
from caracole.ug.bands import LETTERS, listing_url
from helpers.ug_bands import FakeDirectory, fillers, listed
from helpers.ug_pages import SONG_DONGYE, SONG_DONGYE_CHORDS_URL, SONG_DONGYE_ID, SONG_DONGYE_URL


@pytest.fixture
def site(monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    s = FakeDirectory({"s": [listed(SONG_DONGYE_ID, SONG_DONGYE, tabs=42, bare=True),
                             *fillers("s", 60, start=50_000)]})

    def transport(provider: str) -> httpx.BaseTransport:
        if provider != "ug":
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(s.handler)

    monkeypatch.setattr(_common, "transport_for", transport)
    return s


def run(tmp_path: Path, *args: str, extra: str = ""):
    (tmp_path / "caracole.toml").write_text("\n".join([
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
        "[ug_directory]",
        "concurrency = 3",
        extra,
    ]) + "\n", encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(tmp_path / "caracole.toml"), "ug", *args])


def database(tmp_path: Path):
    return closing(db.connect(tmp_path / "state" / "caracole.sqlite"))


def test_the_live_song_dongye_case_end_to_end(tmp_path, site):
    # The listings alone first: 宋冬野 is an artist a search names, their page not read yet.
    result = run(tmp_path, "--directory", "--budget", str(len(LETTERS) + 1))
    assert result.exit_code == 0, result.output
    assert "UG's listings: 28 pages read" in result.output
    assert "The budget of 28 requests is spent" in result.output
    with database(tmp_path) as conn:
        from caracole.search import directory_artists

        [artist] = directory_artists(conn, "宋冬野")
        assert (artist.artist, artist.url, artist.tabs) == (SONG_DONGYE, SONG_DONGYE_URL, 42)
        assert not find_index(conn, "斑马斑马").songs  # the directory names no song
        sent = "SELECT COUNT(*) FROM events WHERE provider = 'ug' AND decision != 'budget'"
        assert conn.execute(sent).fetchone()[0] == 28
        assert db.kv_get(conn, "http:last_request:ug") is not None
    # Then the second pass reads their page, and a search by title finds their song.
    result = run(tmp_path, "--directory")
    assert result.exit_code == 0, result.output
    assert "Bare artists' pages: 1 page read." in result.output
    assert "The directory: 87 of about 87 artists, 27 of 27 listings read whole; 1 of 1 bare artists' pages read." \
        in result.output
    assert site.asked(SONG_DONGYE_CHORDS_URL) == 1
    with database(tmp_path) as conn:
        hits = find_index(conn, "斑马斑马").songs
        assert hits and hits[0].title == "斑马斑马" and hits[0].page == SONG_DONGYE_URL
        assert directory_artists(conn, "宋冬野") == []  # read: their songs show as any read artist's do
        assert [a.artist for a in find_index(conn, "宋冬野").artists] == ["宋冬野"]


def test_its_settings_are_caracole_tomls_and_the_budget_its_own(tmp_path, site):
    result = run(tmp_path, "--directory", extra="budget = 5")
    assert result.exit_code == 0, result.output
    assert "The budget of 5 requests is spent" in result.output
    assert len(site.requests) == 5


def test_a_block_stops_the_pass_and_cools_ug_for_everything(tmp_path, site):
    site.status[listing_url("c")] = 403
    result = run(tmp_path, "--directory")
    assert result.exit_code == 0, result.output
    assert "Ultimate Guitar blocked caracole" in result.output
    with database(tmp_path) as conn:
        assert get_state(conn, "ug").strikes == 1
    assert run(tmp_path, "--directory").output.startswith("Ultimate Guitar is cooling down")


def test_link_and_directory_are_one_or_the_other(tmp_path, site):
    assert run(tmp_path).exit_code == 2
    assert run(tmp_path, "--directory", "--link", "https://tabs.ultimate-guitar.com/tab/1").exit_code == 2
    assert run(tmp_path, "--link", "https://tabs.ultimate-guitar.com/tab/1", "--budget", "3").exit_code == 2
    assert not site.requests
