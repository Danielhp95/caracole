"""``caracole fetch``, run through the CLI against a fake Ultimate Guitar.

Each test writes a caracole.toml rooted in tmp_path, with no pause between
requests. UG is served by ``httpx.MockTransport`` through
``caracole.commands._common.transport_for``, so no request reaches the network.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from helpers.ug_pages import make_artist_page_html, make_tab_page_html, version_dict
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.health import get_state, record_block
from caracole.lyrics import Lyrics
from caracole.songs import find_song, get_song, update_song, upsert_song
from caracole.ug.artist import artist_page_url
from caracole.ug.lookup import remember_artist_url
from conftest import subprocess_pythonpath

TAB = "https://tabs.ultimate-guitar.com/tab/"
PERSIANA = f"{TAB}soda-stereo/persiana-americana-chords-101"
SIGNOS = f"{TAB}soda-stereo/signos-chords-201"
SHEET = "[Intro]\r\n[tab][ch]Am[/ch]   [ch]F[/ch]\r\nwalking down the river road tonight[/tab]"


class FakeUG:
    """UG pages by URL; anything else is UG's 404 page. Every request is recorded."""

    def __init__(self, pages=None):
        self.pages = pages if pages is not None else {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        status, body = self.pages.get(str(request.url), (404, "<html><title>Oops!</title></html>"))
        return httpx.Response(status, text=body)


def tab_page(tab_id, song, url):
    tab = version_dict(tab_id, song=song, artist="Soda Stereo", tab_url=url)
    return 200, make_tab_page_html(tab, [], content=SHEET,
                                   artist_url="https://www.ultimate-guitar.com/artist/soda_stereo_2946")


def write_config(tmp_path, *, budget=60):
    path = tmp_path / "caracole.toml"
    path.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n'
        f"[providers.ug]\nbudget = {budget}\ndelay = [0, 0]\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def ug(monkeypatch):
    site = FakeUG()
    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(site.handler))
    return site


def run(tmp_path, *args, budget=60):
    return CliRunner().invoke(build_app(), ["--config", str(write_config(tmp_path, budget=budget)), "fetch", *args])


def connect(tmp_path):
    return db.connect(tmp_path / "state" / "caracole.sqlite")


def accepted(conn, title, song_key, tab_id, *, added_at, dirty=True):
    """An accepted song with one chords tab in the index."""
    song_id, _ = upsert_song(conn, artists=["Soda Stereo"], title=title, album=None, duration_ms=None, isrc=None,
                             source="wanted", source_id=title, added_at=added_at)
    update_song(conn, song_id, match_decision="accept", match_step="exact", match_artist_key="soda-stereo",
                match_song_key=song_key, ug_dirty=dirty)
    conn.execute(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, 'soda-stereo', ?, 'chords', 'last', '2026-10-01T00:00:00Z', ?)",
        (tab_id, song_key, f"soda-stereo/{song_key}-chords-{tab_id}"),
    )
    return song_id


def two_songs(tmp_path, ug):
    conn = connect(tmp_path)
    persiana = accepted(conn, "Persiana Americana", "persiana-americana", 101, added_at="2026-10-02T00:00:00Z")
    signos = accepted(conn, "Signos", "signos", 201, added_at="2026-10-01T00:00:00Z")
    ug.pages[PERSIANA] = tab_page(101, "Persiana Americana", PERSIANA)
    ug.pages[SIGNOS] = tab_page(201, "Signos", SIGNOS)
    return conn, persiana, signos


def test_fetch_reports_each_song_and_the_totals(tmp_path, ug):
    conn, persiana, signos = two_songs(tmp_path, ug)

    result = run(tmp_path)

    assert result.exit_code == 0, result.output
    assert "Soda Stereo - Persiana Americana: sheet 101 (1 request)" in result.output
    assert "Soda Stereo - Signos: sheet 201 (1 request)" in result.output
    assert "2 songs done, 0 failed, 2 UG requests." in result.output
    assert ug.requests == [PERSIANA, SIGNOS]  # newest first
    assert get_song(conn, persiana).status == "found" and get_song(conn, signos).ug_dirty is False
    assert (tmp_path / "lib" / "Soda Stereo" / "Signos" / "sheet.txt").is_file()
    events = conn.execute("SELECT url, decision FROM events ORDER BY id").fetchall()
    assert [tuple(e) for e in events] == [(PERSIANA, "ok"), (SIGNOS, "ok")]


def test_nothing_to_fetch(tmp_path, ug):
    conn = connect(tmp_path)
    accepted(conn, "Signos", "signos", 201, added_at="2026-10-01T00:00:00Z", dirty=False)

    result = run(tmp_path)

    assert result.exit_code == 0, result.output
    assert "Nothing to fetch." in result.output and ug.requests == []


def test_a_block_cools_ug_down_and_exits_0(tmp_path, ug):
    conn, persiana, _ = two_songs(tmp_path, ug)
    ug.pages[PERSIANA] = (403, "<html><body>Forbidden</body></html>")

    result = run(tmp_path)

    assert result.exit_code == 0, result.output
    assert "Ultimate Guitar blocked caracole" in result.output
    assert re.search(r"No more UG requests until \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", result.output)
    assert "Nothing was marked not found." in result.output
    state = get_state(conn, "ug")
    assert state.strikes == 1 and state.cooldown_until is not None
    assert ug.requests == [PERSIANA]
    assert get_song(conn, persiana).ug_dirty is True


def test_a_cooling_provider_is_left_alone(tmp_path, ug):
    from caracole.commands._common import utcnow

    conn, _, _ = two_songs(tmp_path, ug)
    record_block(conn, "ug", utcnow(), "HTTP 403")

    result = run(tmp_path)

    assert result.exit_code == 0, result.output
    assert "Ultimate Guitar is cooling down after a block until" in result.output
    assert ug.requests == []


def test_a_spent_budget_says_so_and_exits_0(tmp_path, ug):
    conn, persiana, signos = two_songs(tmp_path, ug)

    result = run(tmp_path, budget=1)

    assert result.exit_code == 0, result.output
    assert "1 song done, 0 failed, 1 UG request." in result.output
    assert "The UG budget of 1 request is spent; the rest waits for the next run." in result.output
    assert get_song(conn, persiana).status == "found"  # newest first
    assert get_song(conn, signos).ug_dirty is True


def test_a_page_ug_cannot_serve_fails_that_song_only(tmp_path, ug):
    conn, persiana, signos = two_songs(tmp_path, ug)
    ug.pages[PERSIANA] = (200, "<html><body>maintenance</body></html>")  # no js-store

    result = run(tmp_path)

    assert result.exit_code == 0, result.output
    assert "1 song done, 1 failed, 2 UG requests." in result.output
    assert get_song(conn, persiana).ug_dirty is True and get_song(conn, signos).status == "found"


def kept_sheet_coverage(conn, song_id):
    return conn.execute(
        "SELECT v.coverage FROM files f JOIN versions v ON v.id = f.version_id WHERE f.song_id = ? AND f.name = ?",
        (song_id, "sheet.txt"),
    ).fetchone()[0]


def test_fetch_first_scores_sheets_kept_before_their_lyrics(tmp_path, ug):
    # As the nightly run does, without a request: a partial sheet then shows on the to-do page.
    conn, persiana, _ = two_songs(tmp_path, ug)
    assert run(tmp_path).exit_code == 0  # both sheets kept while LRCLIB had no lyrics for them
    assert kept_sheet_coverage(conn, persiana) is None
    record = {"id": 1, "plainLyrics": "walking down the river road tonight\ncounting every lantern on the shore",
              "syncedLyrics": None, "instrumental": False, "duration": 213.0}
    update_song(conn, persiana, lyrics_status="found", lyrics_json=Lyrics.from_record(record).to_json())
    ug.requests.clear()

    result = run(tmp_path)

    assert result.exit_code == 0, result.output
    assert "Scored 1 kept sheet against lyrics that came later." in result.output and ug.requests == []
    assert kept_sheet_coverage(conn, persiana) == 0.5


def test_song_option_fetches_that_song_even_when_nothing_changed(tmp_path, ug):
    conn, persiana, signos = two_songs(tmp_path, ug)
    update_song(conn, signos, ug_dirty=False)

    result = run(tmp_path, "--song", "Soda Stereo - Signos")

    assert result.exit_code == 0, result.output
    assert ug.requests == [SIGNOS]
    assert "Soda Stereo - Signos: sheet 201 (1 request)" in result.output
    assert get_song(conn, persiana).ug_dirty is True


@pytest.mark.parametrize("decision,message", [
    ("review", "needs review first: run `caracole review`"),
    (None, "isn't matched yet: run `caracole match`"),
])
def test_song_option_explains_what_is_missing(tmp_path, ug, decision, message):
    conn = connect(tmp_path)
    song_id = accepted(conn, "Signos", "signos", 201, added_at="2026-10-01T00:00:00Z")
    update_song(conn, song_id, match_decision=decision)

    result = run(tmp_path, "--song", "Soda Stereo - Signos")

    assert result.exit_code == 1 and message in result.output
    assert ug.requests == []


def test_song_option_for_an_artist_ug_lists_only_by_bare_ids(tmp_path, ug):
    conn = connect(tmp_path)
    song_id, _ = upsert_song(conn, artists=["Joaquín Sabina"], title="19 Días y 500 Noches", album=None,
                             duration_ms=None, isrc=None, source="wanted", source_id="x",
                             added_at="2026-10-01T00:00:00Z")
    update_song(conn, song_id, match_decision="not_found")

    result = run(tmp_path, "--song", "Joaquín Sabina - 19 Días y 500 Noches")

    assert result.exit_code == 1 and "[artist_url]" in result.output
    assert ug.requests == []


SODA_ARTIST = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"


def title_only_review(conn):
    """Soda Stereo - De Música Ligera: all its tabs are bare ids, so the index offers only a cover."""
    song_id, _ = upsert_song(conn, artists=["Soda Stereo"], title="De Música Ligera", album=None, duration_ms=None,
                             isrc=None, source="wanted", source_id="dml", added_at="2026-10-01T00:00:00Z")
    update_song(conn, song_id, match_decision="review", review=True, match_candidates=[
        {"artist_key": "os-paralamas-do-sucesso", "song_key": "de-musica-ligeira", "score": 97.0,
         "step": "title_only"}])
    return song_id


def test_song_option_looks_a_title_only_review_up_on_the_artist_page(tmp_path, ug):
    # The nightly fetch takes such a review to the artist's UG page; so does --song.
    conn = connect(tmp_path)
    song_id = title_only_review(conn)
    remember_artist_url(conn, "soda-stereo", SODA_ARTIST)
    tab = version_dict(85042, song="De Música Ligera", artist="Soda Stereo")
    ug.pages[artist_page_url(SODA_ARTIST, kind="chords")] = (200, make_artist_page_html(2946, "Soda Stereo", [tab]))
    ug.pages[f"{TAB}85042"] = (200, make_tab_page_html(tab, [], content=SHEET, artist_url=SODA_ARTIST))

    result = run(tmp_path, "--song", "Soda Stereo - De Música Ligera")

    assert result.exit_code == 0, result.output
    assert "Soda Stereo - De Música Ligera: sheet 85042" in result.output
    assert get_song(conn, song_id).match_step == "artist_page"


def test_song_option_for_a_title_only_review_of_an_artist_ug_lists_only_by_bare_ids(tmp_path, ug):
    conn = connect(tmp_path)
    title_only_review(conn)

    result = run(tmp_path, "--song", "Soda Stereo - De Música Ligera")

    assert result.exit_code == 1 and "[artist_url]" in result.output
    assert ug.requests == []


def test_song_option_for_an_unknown_song(tmp_path, ug):
    connect(tmp_path)

    result = run(tmp_path, "--song", "Soda Stereo - Zoom")

    assert result.exit_code == 1 and 'No song "Soda Stereo - Zoom" in the library' in result.output
    assert find_song(connect(tmp_path), "soda-stereo/zoom") is None


# --- the pages --------------------------------------------------------------------------------

STALE = "as an earlier run left it\n"
PAGES = ("_todo.md", "index.html")


def stale_pages(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        (lib / name).write_text(STALE, encoding="utf-8")


def pages(tmp_path):
    return [(tmp_path / "lib" / name).read_text(encoding="utf-8") for name in PAGES]


@pytest.mark.parametrize("args", [(), ("--song", "Soda Stereo - Signos")], ids=["fetch", "--song"])
def test_fetch_rewrites_the_pages(tmp_path, ug, args):
    two_songs(tmp_path, ug)
    stale_pages(tmp_path)

    result = run(tmp_path, *args)

    assert result.exit_code == 0, result.output
    todo, index = pages(tmp_path)
    found = 1 if args else 2
    assert f"2 songs: {found} found, {2 - found} wanted" in todo
    assert "Signos" in index and index != STALE


def test_a_block_rewrites_the_pages_with_the_cooldown(tmp_path, ug):
    two_songs(tmp_path, ug)
    ug.pages[PERSIANA] = (403, "<html><body>Forbidden</body></html>")
    stale_pages(tmp_path)

    result = run(tmp_path)

    assert result.exit_code == 0, result.output
    todo, index = pages(tmp_path)
    assert STALE not in (todo, index)
    assert "| ug | cooling down until " in todo


def test_a_cooldown_leaves_the_pages_alone(tmp_path, ug):
    from caracole.commands._common import utcnow

    conn, _, _ = two_songs(tmp_path, ug)
    record_block(conn, "ug", utcnow(), "HTTP 403")
    stale_pages(tmp_path)

    result = run(tmp_path)

    assert "cooling down" in result.output, result.output
    assert pages(tmp_path) == [STALE, STALE]


def test_nothing_to_fetch_leaves_the_pages_alone(tmp_path, ug):
    conn = connect(tmp_path)
    accepted(conn, "Signos", "signos", 201, added_at="2026-10-01T00:00:00Z", dirty=False)
    stale_pages(tmp_path)

    result = run(tmp_path)

    assert "Nothing to fetch." in result.output, result.output
    assert pages(tmp_path) == [STALE, STALE]


def test_sheets_scored_with_nothing_to_fetch_rewrite_the_pages(tmp_path, ug):
    # The partial sheet the score found shows on the to-do page at once.
    conn, persiana, signos = two_songs(tmp_path, ug)
    assert run(tmp_path).exit_code == 0  # both sheets kept while LRCLIB had no lyrics for them
    record = {"id": 1, "plainLyrics": "walking down the river road tonight\ncounting every lantern",
              "syncedLyrics": None, "instrumental": False, "duration": 213.0}
    lyrics = Lyrics.from_record(record).to_json()
    update_song(conn, persiana, lyrics_status="found", lyrics_json=lyrics)
    stale_pages(tmp_path)

    result = run(tmp_path)

    assert "Scored 1 kept sheet" in result.output, result.output
    assert "Nothing to fetch." in result.output
    todo, _ = pages(tmp_path)
    assert "**Soda Stereo - Persiana Americana**: 50% of the lyrics" in todo


def test_registering_the_command_imports_no_fetch_code(tmp_path):
    # Every command module is imported on every start; the fetch code waits for the command.
    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, typer\n"
        "from caracole.commands import fetch\n"
        "fetch.register(typer.Typer())\n"
        "print([m for m in ('caracole.ug.fetch', 'rapidfuzz', 'selectolax') if m in sys.modules])\n"
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"
