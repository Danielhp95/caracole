"""``caracole lyrics`` and ``caracole lacuerda``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with no pause between
requests. LRCLIB, LaCuerda and ntfy are fakes behind ``httpx.MockTransport``,
handed to the clients through ``caracole.commands._common.transport_for``, so no
request can reach the network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import add_song, subprocess_pythonpath
from helpers.lacuerda_site import listing_page
from helpers.azlyrics_site import FakeAzLyrics
from helpers.megalobiz_site import FakeMegalobiz, record
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import get_state, is_cooling, record_block
from caracole.library import kept_files
from caracole.lyrics import Lyrics
from caracole.songs import get_song, update_song

LRCLIB_FIXTURES = Path(__file__).parent / "fixtures" / "lrclib"
LACUERDA_FIXTURES = Path(__file__).parent / "fixtures" / "lacuerda"
SODA = "https://acordes.lacuerda.net/soda_stereo/"
DML_3 = "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-3.shtml"
NTFY = "https://ntfy.example/caracole-test"

# Every line is in the LaCuerda version fixture's sheet (all invented).
SHEET_LYRICS = """\
Cruzo la plaza con el café frío
y cuento las luces del tren de las seis
nadie me espera en el andén vacío
guardo tu nombre y no sé qué hacer
"""

# Environment load_config would read; none of it may leak into a test.
OUTSIDE_SETTINGS = (
    "CARACOLE_CONFIG",
)


class FakeLrclib:
    """``/api/get`` answers its records (by artist and track) and its documented 404 otherwise (its 503 is
    ServerOverloaded, busy: an error, never a miss); ``/api/search`` lists nothing. ``status`` answers every
    request with that status."""

    def __init__(self, records=(), status: int | None = None):
        self.records = list(records)
        self.status = status
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.path)
        if self.status is not None:
            return httpx.Response(self.status, text="nope")
        params = dict(request.url.params)
        if request.url.path == "/api/get":
            wanted = (params["artist_name"], params["track_name"])
            for r in self.records:
                if (r["artistName"], r["trackName"]) == wanted:
                    return httpx.Response(200, json=r)
            return httpx.Response(404, json={"name": "TrackNotFound"})
        if request.url.path == "/api/search":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.url}")


class FakeLaCuerda:
    """Pages by URL; an unknown artist gets LaCuerda's HTTP 200 "aqui llega" body, and a listing of
    artists it doesn't have its 404 page."""

    def __init__(self, pages=None, status: int | None = None):
        self.pages = dict(pages or {})
        self.status = status
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if self.status is not None:
            return httpx.Response(self.status, text="nope")
        if url in self.pages:
            return httpx.Response(200, text=self.pages[url])
        slug = request.url.path.strip("/")
        if request.url.path.endswith("/") and "/" not in slug:
            return httpx.Response(200, text=f"aqui llega:../tabs/{slug[0]}/{slug}/index.html")
        if request.url.path.startswith("/tabs/"):
            return httpx.Response(404, text=(LACUERDA_FIXTURES / "not_found.html").read_text(encoding="utf-8"))
        raise AssertionError(f"unexpected request: {url}")


class FakeNtfy:
    def __init__(self):
        self.posts: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})


class Sites:
    def __init__(self):
        self.lrclib = FakeLrclib()
        self.megalobiz = FakeMegalobiz()
        self.azlyrics = FakeAzLyrics({})  # with no page: it has no artist
        self.lacuerda = FakeLaCuerda()
        self.ntfy = FakeNtfy()

    def transport(self, provider: str) -> httpx.BaseTransport:
        fakes = {"lrclib": self.lrclib, "megalobiz": self.megalobiz, "azlyrics": self.azlyrics, "lacuerda": self.lacuerda,
                 "ntfy": self.ntfy}
        if provider not in fakes:
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(fakes[provider].handler)


@pytest.fixture
def sites(monkeypatch):
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    return s


def write_config(tmp_path: Path, *, budgets=None, ntfy=False, off=()) -> Path:
    budgets = budgets or {}
    lines = [
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
    ]
    for provider in ("lrclib", "megalobiz", "azlyrics", "lacuerda"):
        lines += [f"[providers.{provider}]", "delay = [0, 0]"]
        if provider in budgets:
            lines.append(f"budget = {budgets[provider]}")
        if provider in off:
            lines.append("enabled = false")
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(tmp_path, *args, **config):
    path = write_config(tmp_path, **config)
    return CliRunner().invoke(build_app(), ["--config", str(path), *args])


def open_db(tmp_path):
    return db.connect(tmp_path / "state" / "caracole.sqlite")


def hit_record() -> dict:
    return json.loads((LRCLIB_FIXTURES / "get_hit.json").read_text(encoding="utf-8"))


def seed(tmp_path, *songs: tuple[str, str]) -> list[int]:
    conn = open_db(tmp_path)
    try:
        return [
            add_song(conn, artist, title, added_at=f"2026-10-{i + 1:02}T00:00:00Z").id
            for i, (artist, title) in enumerate(songs)
        ]
    finally:
        conn.close()


def song(tmp_path, song_id):
    conn = open_db(tmp_path)
    try:
        return get_song(conn, song_id)
    finally:
        conn.close()


# --- caracole lyrics ---------------------------------------------------------------------


def test_lyrics_looks_up_pending_songs_and_reports_the_counts(tmp_path, sites):
    sites.lrclib.records.append(hit_record())
    found, missing = seed(
        tmp_path, ("Soda Stereo", "De Música Ligera"), ("Soda Stereo", "Canción Inexistente")
    )
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "Lyrics: 1 found, 1 missing, 0 instrumental, 0 errors" in result.stdout
    assert song(tmp_path, found).lyrics_status == "found"
    assert song(tmp_path, missing).lyrics_status == "missing"
    assert (tmp_path / "lib" / "Soda Stereo" / "De Música Ligera" / "lyrics.txt").is_file()
    conn = open_db(tmp_path)
    try:  # every request is in the event log, as in the nightly run
        logged = conn.execute("SELECT COUNT(*) FROM events WHERE provider = 'lrclib'").fetchone()[0]
    finally:
        conn.close()
    assert logged == len(sites.lrclib.requests) == 3
    # Then Megalobiz, for the song LRCLIB missed: it has none either, so the song is missing.
    assert "Megalobiz: 0 found, 0 timed, 1 missing, 0 errors" in result.stdout
    assert sites.megalobiz.endpoints() == ["search"]


def test_lyrics_with_nothing_to_look_up(tmp_path, sites):
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "No song is waiting for lyrics." in result.stdout
    assert sites.lrclib.requests == [] and sites.megalobiz.requests == []


def test_lyrics_asks_megalobiz_for_a_song_lrclib_missed(tmp_path, sites):
    sites.megalobiz.records.append(record())
    (song_id,) = seed(tmp_path, ("Eagles", "Hotel California"))
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "Lyrics: 0 found, 1 missing, 0 instrumental, 0 errors" in result.stdout
    assert "Megalobiz: 1 found, 0 timed, 0 missing, 0 errors" in result.stdout
    stored = song(tmp_path, song_id)
    assert stored.lyrics_status == "found" and json.loads(stored.lyrics_json)["provider"] == "megalobiz"
    conn = open_db(tmp_path)
    try:
        logged = conn.execute("SELECT COUNT(*) FROM events WHERE provider = 'megalobiz'").fetchone()[0]
    finally:
        conn.close()
    assert logged == len(sites.megalobiz.requests) == 2


def test_lyrics_with_megalobiz_turned_off_asks_it_nothing(tmp_path, sites):
    sites.megalobiz.records.append(record())
    (song_id,) = seed(tmp_path, ("Eagles", "Hotel California"))
    result = run(tmp_path, "lyrics", off=("megalobiz",))
    assert result.exit_code == 0, result.output
    assert "Megalobiz" not in result.stdout and sites.megalobiz.requests == []
    assert song(tmp_path, song_id).lyrics_status == "missing"


def test_a_megalobiz_block_cools_it_down_and_leaves_lrclibs_answer(tmp_path, sites):
    sites.megalobiz.failing["search"] = 429
    (song_id,) = seed(tmp_path, ("Eagles", "Hotel California"))
    result = run(tmp_path, "lyrics", ntfy=True)
    assert result.exit_code == 0, result.output
    assert "Megalobiz blocked caracole" in result.stdout
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "megalobiz", _common.utcnow())
    finally:
        conn.close()
    assert song(tmp_path, song_id).lyrics_status == "missing"
    assert len(sites.ntfy.posts) == 1


def test_lyrics_errors_leave_songs_pending_and_say_so(tmp_path, sites):
    sites.lrclib.status = 500
    (song_id,) = seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "0 found, 0 missing, 0 instrumental, 1 error" in result.stdout
    assert "pending" in result.stdout
    assert song(tmp_path, song_id).lyrics_status == "pending"


def test_lyrics_spent_budget_is_no_failure(tmp_path, sites):
    sites.lrclib.records.append(hit_record())
    older, newer = seed(
        tmp_path, ("Soda Stereo", "Persiana Americana"), ("Soda Stereo", "De Música Ligera")
    )
    result = run(tmp_path, "lyrics", budgets={"lrclib": 1})
    assert result.exit_code == 0, result.output
    assert "Lyrics: 1 found, 0 missing, 0 instrumental, 0 errors" in result.stdout
    assert "budget of 1 request" in result.stdout and "next run" in result.stdout
    assert song(tmp_path, newer).lyrics_status == "found"
    assert song(tmp_path, older).lyrics_status == "pending"


def test_lyrics_block_starts_a_cooldown_and_sends_one_alert(tmp_path, sites):
    # A block is expected behaviour, as for `caracole fetch` and `caracole index`: exit 0.
    sites.lrclib.status = 429
    (song_id,) = seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    result = run(tmp_path, "lyrics", ntfy=True)
    assert result.exit_code == 0, result.output
    assert "LRCLIB blocked caracole" in result.stdout
    assert "Nothing was marked missing" in result.stdout
    assert song(tmp_path, song_id).lyrics_status == "pending"
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "lrclib", datetime.now(UTC))
        assert get_state(conn, "lrclib").strikes == 1
    finally:
        conn.close()
    (alert,) = sites.ntfy.posts
    assert alert.headers["Title"] == "caracole: LRCLIB blocked"
    assert alert.headers["Priority"] == "high"


def test_lyrics_asks_nothing_while_lrclib_cools_down(tmp_path, sites):
    seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    conn = open_db(tmp_path)
    try:
        record_block(conn, "lrclib", datetime.now(UTC), "lrclib: 429: HTTP 429")
    finally:
        conn.close()
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "LRCLIB is cooling down" in result.stdout
    assert sites.lrclib.requests == []


def test_a_pass_that_went_well_clears_old_strikes(tmp_path, sites):
    # As after a nightly run: the cooldown is over and LRCLIB answered.
    sites.lrclib.records.append(hit_record())
    seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    conn = open_db(tmp_path)
    try:
        record_block(conn, "lrclib", datetime.now(UTC) - timedelta(days=2), "lrclib: 429: HTTP 429")
    finally:
        conn.close()
    assert run(tmp_path, "lyrics").exit_code == 0
    conn = open_db(tmp_path)
    try:
        assert get_state(conn, "lrclib").strikes == 0
    finally:
        conn.close()


@pytest.mark.parametrize("command,provider", [("lyrics", "lrclib"), ("lacuerda", "lacuerda")])
def test_a_pass_the_site_answered_with_nothing_but_errors_leaves_the_strikes(tmp_path, sites, command, provider):
    # As a nightly run of nothing but errors: no sign that the site answers again.
    getattr(sites, provider).status = 500
    spanish_song(tmp_path)
    conn = open_db(tmp_path)
    try:
        update_song(conn, 1, lyrics_status="pending")
        record_block(conn, provider, datetime.now(UTC) - timedelta(days=2), f"{provider}: 429: HTTP 429")
    finally:
        conn.close()
    assert run(tmp_path, command).exit_code == 0
    assert getattr(sites, provider).requests
    conn = open_db(tmp_path)
    try:
        assert (get_state(conn, provider).strikes, get_state(conn, provider).last_ok) == (1, None)
    finally:
        conn.close()


def test_a_pass_that_asked_nothing_leaves_the_strikes(tmp_path, sites):
    # Nothing was waiting, so nothing shows LRCLIB answers again.
    conn = open_db(tmp_path)
    try:
        record_block(conn, "lrclib", datetime.now(UTC) - timedelta(days=2), "lrclib: 429: HTTP 429")
    finally:
        conn.close()
    assert run(tmp_path, "lyrics").exit_code == 0
    conn = open_db(tmp_path)
    try:
        assert get_state(conn, "lrclib").strikes == 1
    finally:
        conn.close()


# --- caracole lacuerda -------------------------------------------------------------------


def spanish_song(tmp_path, title="De Música Ligera") -> int:
    (song_id,) = seed(tmp_path, ("Soda Stereo", title))
    lyrics = Lyrics(
        plain=SHEET_LYRICS, synced=None, instrumental=False, duration=None, lrclib_id=None
    )
    conn = open_db(tmp_path)
    try:
        update_song(conn, song_id, lyrics_status="found", lyrics_json=lyrics.to_json())
    finally:
        conn.close()
    return song_id


def soda_pages() -> dict[str, str]:
    return {
        SODA: (LACUERDA_FIXTURES / "artist.html").read_text(encoding="utf-8"),
        DML_3: (LACUERDA_FIXTURES / "version.html").read_text(encoding="utf-8"),
    }


def test_lacuerda_keeps_a_sheet_and_reports_the_counts(tmp_path, sites):
    sites.lacuerda.pages.update(soda_pages())
    kept = spanish_song(tmp_path)
    spanish_song(tmp_path, "Canción Inexistente")
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "LaCuerda: 2 tried, 1 sheet kept, 1 missing, 0 errors" in result.stdout
    assert song(tmp_path, kept).status == "found"
    assert (tmp_path / "lib" / "Soda Stereo" / "De Música Ligera" / "sheet.txt").is_file()


def ug_sheet_kept_before_its_lyrics(tmp_path, song_id: int, markup: str) -> int:
    """A UG sheet kept while the song's lyrics were pending: sheet.txt and sheet.json, unscored."""
    from caracole.library import keep_file
    from caracole.songs import refresh_status
    from caracole.versions import upsert_version

    url = "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-101"
    conn = open_db(tmp_path)
    try:
        vid = upsert_version(conn, provider="ug", tab_id="101", song_id=song_id, slot="sheet",
                             kind="chords", rating=4.5, votes=20, version=1, label=None, url=url,
                             raw={"id": 101}, now="2026-10-01T00:00:00Z")
        files = {"sheet.json": json.dumps({"content": markup, "url": url}), "sheet.txt": markup}
        for name, text in files.items():
            keep_file(conn, tmp_path / "lib", song=get_song(conn, song_id), version_id=vid,
                      name=name, data=text.encode(), rank=1)
        refresh_status(conn, song_id, ignored=False)
    finally:
        conn.close()
    return vid


def test_lacuerda_first_scores_a_sheet_kept_before_its_lyrics(tmp_path, sites):
    # The kept UG sheet covers 1 of the 7 lyric lines, LaCuerda's 4: a partial sheet that
    # covers more replaces the kept one, but only once the kept one is scored, as the run does.
    from caracole.versions import get_version

    sites.lacuerda.pages.update(soda_pages())
    (song_id,) = seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    vid = ug_sheet_kept_before_its_lyrics(tmp_path, song_id, "Cruzo la plaza con el café frío\n")
    more = ("las golondrinas vuelven en invierno\nmi abuela tejía bufandas de colores\n"
            "un perro ladra lejos del molino\n")
    lyrics = Lyrics(plain=SHEET_LYRICS + more, synced=None, instrumental=False, duration=None,
                    lrclib_id=None)
    conn = open_db(tmp_path)
    try:
        update_song(conn, song_id, lyrics_status="found", lyrics_json=lyrics.to_json())
    finally:
        conn.close()

    result = run(tmp_path, "lacuerda")

    assert result.exit_code == 0, result.output
    assert "LaCuerda: 1 tried, 1 sheet kept, 0 missing, 0 errors" in result.stdout
    conn = open_db(tmp_path)
    try:
        assert round(get_version(conn, vid).coverage, 3) == round(1 / 7, 3)
    finally:
        conn.close()
    sheet = tmp_path / "lib" / "Soda Stereo" / "De Música Ligera" / "sheet.txt"
    assert "Baila la lluvia" in sheet.read_text(encoding="utf-8")  # LaCuerda's


def test_lacuerda_follows_overrides(tmp_path, sites):
    # Ignored in overrides.toml, though no match has run since.
    sites.lacuerda.pages.update(soda_pages())
    spanish_song(tmp_path)
    overrides = tmp_path / "lib" / "overrides.toml"
    overrides.parent.mkdir(parents=True, exist_ok=True)
    overrides.write_text('[ignore]\nsongs = ["Soda Stereo - De Música Ligera"]\n', encoding="utf-8")
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "No song to try on LaCuerda." in result.stdout
    assert sites.lacuerda.requests == []


def test_lacuerda_reads_overrides_again_after_a_lookup_it_let_go_first(tmp_path, sites, monkeypatch):
    # In the pause before Soda Stereo's page, the command let `caracole get --tab` go first, which pinned the
    # partial UG sheet De Música Ligera keeps: LaCuerda's complete sheet doesn't take its place.
    sites.lacuerda.pages.update(soda_pages())
    song_id = spanish_song(tmp_path)
    vid = ug_sheet_kept_before_its_lyrics(tmp_path, song_id, "Cruzo la plaza con el café frío\n")
    overrides = tmp_path / "lib" / "overrides.toml"
    answer = sites.lacuerda.handler

    def lookup_first(request):
        if str(request.url) == SODA and not overrides.exists():
            overrides.write_text('[pin]\n"Soda Stereo - De Música Ligera" = '
                                 '["https://tabs.ultimate-guitar.com/tab/101"]\n', encoding="utf-8")
            monkeypatch.setattr(_common, "_handoffs", _common.handoffs() + 1)
        return answer(request)

    monkeypatch.setattr(sites.lacuerda, "handler", lookup_first)
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert sites.lacuerda.requests == [SODA, DML_3]
    conn = open_db(tmp_path)
    try:
        assert {f.name: f.version_id for f in kept_files(conn, song_id)} == {"sheet.json": vid, "sheet.txt": vid}
    finally:
        conn.close()


def test_lacuerda_says_which_song_waits_for_a_folder_another_songs_name_makes(tmp_path, sites, monkeypatch):
    import caracole.lacuerda_fetch as lf
    from caracole.library import SharedFolder

    two, one = seed(tmp_path, ("Rodrigo", "Concierto, part two"), ("Rodrigo", "Concierto, part one"))
    shared = SharedFolder(song(tmp_path, two), song(tmp_path, one), "sheet.json")
    monkeypatch.setattr(lf, "lacuerda_sheets", lambda *a, **k: lf.LaCuerdaStats(tried=1, shared=[shared]))
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert ("LaCuerda: 1 tried, 0 sheets kept, 0 missing, 0 errors\nRodrigo - Concierto, part two's sheet.json isn't "
            "kept: its folder is Rodrigo - Concierto, part one's too") in result.stdout


def test_lacuerda_with_nothing_to_try(tmp_path, sites):
    seed(tmp_path, ("Radiohead", "Creep"))
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "No song to try on LaCuerda." in result.stdout
    assert sites.lacuerda.requests == []


def test_lacuerda_errors_are_counted_and_tried_again(tmp_path, sites):
    sites.lacuerda.status = 500
    song_id = spanish_song(tmp_path)
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "LaCuerda: 1 tried, 0 sheets kept, 0 missing, 1 error" in result.stdout
    assert "tried again next run" in result.stdout
    assert song(tmp_path, song_id).lacuerda_checked_at is None


def test_lacuerda_block_starts_a_cooldown(tmp_path, sites):
    sites.lacuerda.status = 403
    song_id = spanish_song(tmp_path)
    result = run(tmp_path, "lacuerda", ntfy=True)
    assert result.exit_code == 0, result.output
    assert "LaCuerda blocked caracole" in result.stdout
    assert "Nothing was marked missing" in result.stdout
    assert song(tmp_path, song_id).lacuerda_checked_at is None
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "lacuerda", datetime.now(UTC))
    finally:
        conn.close()
    (alert,) = sites.ntfy.posts
    assert alert.headers["Title"] == "caracole: LaCuerda blocked"


def test_lacuerda_asks_nothing_while_lacuerda_cools_down(tmp_path, sites):
    song_id = spanish_song(tmp_path)
    conn = open_db(tmp_path)
    try:
        record_block(conn, "lacuerda", datetime.now(UTC), "lacuerda: 403: HTTP 403")
    finally:
        conn.close()
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert "LaCuerda is cooling down" in result.stdout
    assert sites.lacuerda.requests == []
    assert song(tmp_path, song_id).lacuerda_checked_at is None


def test_lacuerda_spent_budget_is_no_failure(tmp_path, sites):
    sites.lacuerda.pages.update(soda_pages())
    song_id = spanish_song(tmp_path)
    result = run(tmp_path, "lacuerda", budgets={"lacuerda": 1})
    assert result.exit_code == 0, result.output
    assert "budget of 1 request" in result.stdout and "next run" in result.stdout
    assert song(tmp_path, song_id).lacuerda_checked_at is None


# --- caracole lacuerda --index ------------------------------------------------------------

LISTING = "https://acordes.lacuerda.net/tabs/{}/index{}.html"


def listings(sites) -> None:
    """E's listing on two pages, and S's on one; every other initial has none."""
    pages = {("e", 0): [("ebenezer", "Ebenezer", 268), ("enanitos", "Enanitos Verdes", 151)],
             ("e", 100): [("estopa", "Estopa", 159)], ("s", 0): [("soda_stereo", "Soda Stereo", 89)]}
    for (letter, start), artists in pages.items():
        count = 2 if letter == "e" else 1
        sites.lacuerda.pages[LISTING.format(letter, start)] = listing_page(artists, pages=count, page=start // 100)


def test_lacuerda_index_reads_every_listing_and_says_what_the_index_holds(tmp_path, sites):
    listings(sites)
    soda = (LACUERDA_FIXTURES / "artist.html").read_text(encoding="utf-8")
    sites.lacuerda.pages[SODA] = soda
    spanish_song(tmp_path)  # a song LaCuerda would be asked about: --index leaves it be
    result = run(tmp_path, "lacuerda", "--index")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["Index: 3 pages of artists read.",
                                          "LaCuerda: 4 artists and 0 songs in the index."]
    assert len(sites.lacuerda.requests) == 29 and SODA not in sites.lacuerda.requests
    result = run(tmp_path, "lacuerda", "--index")
    assert result.stdout == "LaCuerda's artist index is up to date: 4 artists and 0 songs.\n"
    assert len(sites.lacuerda.requests) == 29


def test_lacuerda_index_with_a_spent_budget_leaves_the_rest_for_the_next_run(tmp_path, sites):
    listings(sites)
    result = run(tmp_path, "lacuerda", "--index", budgets={"lacuerda": 6})
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "Index: 1 page of artists read.",
        "LaCuerda: 2 artists and 0 songs in the index.",
        "LaCuerda's budget of 6 requests per run is spent; the next run reads the rest of its listings.",
    ]


def test_lacuerda_index_errors_are_counted_and_asked_again(tmp_path, sites):
    sites.lacuerda.status = 500
    result = run(tmp_path, "lacuerda", "--index")
    assert result.exit_code == 0, result.output
    assert "LaCuerda: 0 artists and 0 songs in the index, 1 error; the next run asks again." in result.stdout


def test_lacuerda_index_block_starts_a_cooldown(tmp_path, sites):
    sites.lacuerda.status = 403
    result = run(tmp_path, "lacuerda", "--index", ntfy=True)
    assert result.exit_code == 0, result.output
    assert "LaCuerda blocked caracole" in result.stdout
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "lacuerda", datetime.now(UTC))
    finally:
        conn.close()
    (alert,) = sites.ntfy.posts
    assert alert.headers["Title"] == "caracole: LaCuerda blocked"


def test_lacuerda_index_asks_nothing_while_lacuerda_cools_down(tmp_path, sites):
    conn = open_db(tmp_path)
    try:
        record_block(conn, "lacuerda", datetime.now(UTC), "lacuerda: 403: HTTP 403")
    finally:
        conn.close()
    result = run(tmp_path, "lacuerda", "--index")
    assert "LaCuerda is cooling down" in result.stdout
    assert sites.lacuerda.requests == []


def test_lacuerda_without_index_reads_no_listing(tmp_path, sites):
    listings(sites)
    sites.lacuerda.pages.update(soda_pages())
    spanish_song(tmp_path)
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    assert sites.lacuerda.requests == [SODA, DML_3]


# --- caracole lacuerda --artist -----------------------------------------------------------


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)  # the lookup pace's second, between two runs


def served(result) -> str:
    """What caracole serve's request line says of a read that printed this (web/status.py reads its last word)."""
    from caracole.web.jobs import LACUERDA_ARTIST, Job, Step
    from caracole.web.status import job_line

    step = Step("Reading LaCuerda's page", ("lacuerda", "--artist=x"), state="done", output=result.output.splitlines())
    return job_line(Job(1, "Read", LACUERDA_ARTIST + "x", [step], state="done"), None).text


def test_lacuerda_artist_reads_one_page_into_the_index_at_the_lookup_pace(tmp_path, sites, quick):
    from caracole.lacuerda_index import artist_songs

    sites.lacuerda.pages[SODA] = (LACUERDA_FIXTURES / "artist.html").read_text(encoding="utf-8")
    result = run(tmp_path, "lacuerda", "--artist", "soda_stereo")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Read: LaCuerda's page of Soda Stereo lists 14 songs, in the index now.\n"
    assert served(result) == "Read: LaCuerda's page of Soda Stereo lists 14 songs, in the index now."
    assert sites.lacuerda.requests == [SODA]
    conn = open_db(tmp_path)
    try:
        assert len(artist_songs(conn, "soda_stereo")) == 14
        # A lookup's request: it counts in the hour's lookup requests, and its pace is a lookup's.
        assert [r[0] for r in conn.execute("SELECT run FROM events WHERE provider = 'lacuerda'")][0].startswith("lookup:")
    finally:
        conn.close()
    again = run(tmp_path, "lacuerda", "--artist", "Soda Stereo")  # by their name too; from the cache
    assert again.stdout == "Read: LaCuerda's page of Soda Stereo lists 14 songs, in the index now.\n"
    assert sites.lacuerda.requests == [SODA]


def test_lacuerda_artist_lacuerda_has_no_page_for_says_so(tmp_path, sites, quick):
    result = run(tmp_path, "lacuerda", "--artist", "Nadie Conocido")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Not found: LaCuerda has no artist page for Nadie Conocido.\n"
    assert served(result) == "Not found: LaCuerda has no artist page for Nadie Conocido."


def test_lacuerda_artist_block_cooldown_error_and_spent_lookup_budget_exit_0(tmp_path, sites, quick):
    sites.lacuerda.status = 500
    result = run(tmp_path, "lacuerda", "--artist", "soda_stereo")
    assert result.exit_code == 0 and "LaCuerda failed" in result.stdout and "try again" in result.stdout
    assert served(result) == "Not read: LaCuerda failed."
    sites.lacuerda.status = 403
    result = run(tmp_path, "lacuerda", "--artist", "soda_stereo")
    assert result.exit_code == 0 and "LaCuerda blocked caracole" in result.stdout
    assert served(result) == "Not read: LaCuerda blocked caracole."
    asked = len(sites.lacuerda.requests)
    result = run(tmp_path, "lacuerda", "--artist", "soda_stereo")
    assert "LaCuerda is cooling down" in result.stdout and len(sites.lacuerda.requests) == asked
    assert served(result).startswith("Not read: LaCuerda is cooling down after a block until ")
    conn = open_db(tmp_path)
    try:
        conn.execute("DELETE FROM kv WHERE key = 'provider:lacuerda'")  # the cooldown over
        conn.executemany("INSERT INTO events (run, at, provider, url, decision) VALUES (?, ?, 'lacuerda', 'x', 'ok')",
                         [("lookup:x", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))] * 60)
        conn.commit()
    finally:
        conn.close()
    sites.lacuerda.status = None
    result = run(tmp_path, "lacuerda", "--artist", "soda_stereo")
    assert result.exit_code == 0 and "this hour's 60 lookup requests to LaCuerda are spent" in result.stdout
    assert served(result) == "Not read: this hour's 60 lookup requests to LaCuerda are spent."
    assert len(sites.lacuerda.requests) == asked


def test_lacuerda_artist_and_index_together_is_a_usage_error(tmp_path, sites):
    result = run(tmp_path, "lacuerda", "--index", "--artist", "estopa")
    assert result.exit_code == 2 and sites.lacuerda.requests == []
    for other in (("--index",), ("--artist", "estopa")):
        result = run(tmp_path, "lacuerda", "--search", "corazon de tiza", *other)
        assert result.exit_code == 2 and sites.lacuerda.requests == []


# --- caracole lacuerda --search ----------------------------------------------------------------

SEARCH_URL = "https://acordes.lacuerda.net/busca.php?exp=corazon+tiza&canc=1&ord=0&ini=0"


def tiza_answer() -> str:
    from helpers.lacuerda_site import search_page

    return search_page(("imaginarios", "Los Imaginarios", [("corazon_de_tiza", "Corazón de Tiza", "RT-12")]),
                       ("marea_baja", "Marea Baja", [("corazon_de_tiza", "Corazón de Tiza", "T-1")]))


def searched(result) -> str:
    """What caracole serve's request line says of a search that printed this (web/status.py reads its last word)."""
    from caracole.web.jobs import LACUERDA_SEARCH, Job, Step
    from caracole.web.status import job_line

    step = Step("Searching LaCuerda", ("lacuerda", "--search=x"), state="done", output=result.output.splitlines())
    return job_line(Job(1, "Search", LACUERDA_SEARCH + "x", [step], state="done"), None).text


def lookup_events(tmp_path, run_name: str, n: int) -> None:
    """``n`` requests to LaCuerda in the last hour, under a run named ``run_name``."""
    conn = open_db(tmp_path)
    try:
        conn.executemany("INSERT INTO events (run, at, provider, url, decision) VALUES (?, ?, 'lacuerda', 'x', 'ok')",
                         [(run_name, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))] * n)
        conn.commit()
    finally:
        conn.close()


def test_lacuerda_search_asks_once_and_puts_what_it_answers_in_the_index(tmp_path, sites, quick):
    from caracole import lacuerda_index as li

    sites.lacuerda.pages[SEARCH_URL] = tiza_answer()
    result = run(tmp_path, "lacuerda", "--search", "Corazón de tiza")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Searched: LaCuerda has 2 songs for “Corazón de tiza”, in the index now.\n"
    assert searched(result) == "Searched: LaCuerda has 2 songs for “Corazón de tiza”, in the index now."
    assert sites.lacuerda.requests == [SEARCH_URL]  # one request, of the songs: "de" is no word to LaCuerda
    conn = open_db(tmp_path)
    try:
        assert [(h.artist, h.title) for h in li.find(conn, "corazon de tiza").songs] == [
            ("Los Imaginarios", "Corazón de Tiza"), ("Marea Baja", "Corazón de Tiza")]
        # A lookup's request, in the hour's lookups and in their share of them that searches take.
        [run_name] = [r[0] for r in conn.execute("SELECT run FROM events WHERE provider = 'lacuerda'")]
        assert run_name.startswith("lookup:lacuerda-search:")
        said = db.kv_get_json(conn, "lacuerda:search:corazon-tiza")
        assert (said["songs"], said["artists"]) == (2, 0) and said["at"]
    finally:
        conn.close()
    # Asked within 30 days: no request, under any spelling LaCuerda reads the same.
    again = run(tmp_path, "lacuerda", "--search", "corazon tiza")
    assert again.exit_code == 0 and again.stdout.startswith("Searched: LaCuerda was asked for “corazon tiza” on ")
    assert again.stdout.endswith(": 2 songs, in the index.\n")
    assert sites.lacuerda.requests == [SEARCH_URL]


def nothing_found() -> str:
    """LaCuerda's answer of no song: "0 resultados", and no table of them."""
    from helpers.lacuerda_site import fixture

    html = fixture("search.html").replace(". 3 resultados.", ". 0 resultados.")
    start, end = html.index("<table id=s_main"), html.index("</script>", html.index("var NMAX")) + len("</script>")
    return html[:start] + html[end:]


def test_lacuerda_search_asks_again_after_30_days(tmp_path, sites, quick):
    import gzip  # noqa: F401 (the cache's bodies are gzipped; only their meta is aged here)
    import hashlib

    sites.lacuerda.pages[SEARCH_URL] = nothing_found()  # a month ago, LaCuerda had nothing
    assert run(tmp_path, "lacuerda", "--search", "corazon de tiza").stdout.startswith("Nothing found: ")
    month = (datetime.now(UTC) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = open_db(tmp_path)
    try:
        db.kv_set_json(conn, "lacuerda:search:corazon-tiza", {"at": month, "songs": 0, "artists": 0, "stated": 0})
        conn.commit()
    finally:
        conn.close()
    key = hashlib.sha256(SEARCH_URL.encode()).hexdigest()
    meta = tmp_path / "cache" / "http" / "lacuerda" / key[:2] / f"{key}.json"
    meta.write_text(json.dumps({**json.loads(meta.read_text()), "fetched_at": month}))
    sites.lacuerda.pages[SEARCH_URL] = tiza_answer()
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza")
    assert result.stdout.startswith("Searched: LaCuerda has 2 songs") and sites.lacuerda.requests == [SEARCH_URL] * 2
    # Its songs in the index now, strong: a month on, the index answers it, and LaCuerda isn't asked again.
    conn = open_db(tmp_path)
    try:
        db.kv_set_json(conn, "lacuerda:search:corazon-tiza", {"at": month, "songs": 2, "artists": 0, "stated": 2})
        conn.commit()
    finally:
        conn.close()
    assert run(tmp_path, "lacuerda", "--search", "corazon de tiza").stdout.startswith("Found already: ")
    assert sites.lacuerda.requests == [SEARCH_URL] * 2


def test_lacuerda_search_that_finds_nothing_says_so_and_a_query_it_cant_read_asks_nothing(tmp_path, sites, quick):
    sites.lacuerda.pages[SEARCH_URL] = nothing_found()
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza")
    assert result.exit_code == 0 and result.stdout == "Nothing found: LaCuerda has no song for “corazon de tiza”.\n"
    assert searched(result) == "Nothing found: LaCuerda has no song for “corazon de tiza”."
    # Its answer counts: asked again, within 30 days, it asks nothing.
    assert run(tmp_path, "lacuerda", "--search", "corazon de tiza").stdout.startswith("Searched: LaCuerda was asked")
    result = run(tmp_path, "lacuerda", "--search", "el sol y tu")
    assert result.exit_code == 0 and result.stdout == (
        "Not searched: LaCuerda's search reads only words of 4 letters or more, and “el sol y tu” has none.\n")
    assert sites.lacuerda.requests == [SEARCH_URL]


def test_lacuerda_search_keeps_to_its_share_of_the_hours_lookups_unless_asked_by_hand(tmp_path, sites, quick):
    sites.lacuerda.pages[SEARCH_URL] = tiza_answer()
    lookup_events(tmp_path, "lookup:lacuerda-search:x", 20)
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza", "--auto")
    assert result.exit_code == 0 and sites.lacuerda.requests == []
    assert result.stdout.startswith("Not searched: this hour's 20 searches of LaCuerda the page sends by itself "
                                    "are spent")
    assert searched(result) == "Not searched: this hour's 20 searches of LaCuerda the page sends by itself are spent."
    # Asked by hand (the page's button, or a terminal), within the hour's lookups.
    assert run(tmp_path, "lacuerda", "--search", "corazon de tiza").stdout.startswith("Searched: LaCuerda has 2")
    assert sites.lacuerda.requests == [SEARCH_URL]
    sites.lacuerda.pages[SEARCH_URL.replace("tiza", "papel")] = tiza_answer()
    lookup_events(tmp_path, "lookup:x", 39)  # with the 21 searches, the hour's 60 lookup requests
    result = run(tmp_path, "lacuerda", "--search", "corazon de papel")
    assert result.exit_code == 0 and sites.lacuerda.requests == [SEARCH_URL]
    assert searched(result) == "Not searched: this hour's 60 lookup requests to LaCuerda are spent."


def test_lacuerda_search_block_cooldown_and_error_exit_0_and_mark_nothing_asked(tmp_path, sites, quick):
    sites.lacuerda.status = 500
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza")
    assert result.exit_code == 0 and "LaCuerda failed" in result.stdout
    assert searched(result) == "Not searched: LaCuerda failed."
    sites.lacuerda.status = 403
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza")
    assert result.exit_code == 0 and searched(result) == "Not searched: LaCuerda blocked caracole."
    asked = len(sites.lacuerda.requests)
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza")
    assert searched(result).startswith("Not searched: LaCuerda is cooling down after a block until ")
    assert len(sites.lacuerda.requests) == asked
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "lacuerda", datetime.now(UTC))
        assert db.kv_get(conn, "lacuerda:search:corazon-tiza") is None  # an error is never an answer
    finally:
        conn.close()


def test_lacuerda_search_asks_once_more_for_a_cached_answer_cut_short(tmp_path, sites, quick):
    from helpers.lacuerda_site import fixture

    sites.lacuerda.pages[SEARCH_URL] = fixture("search_cut.html")
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza")
    assert result.exit_code == 0 and "LaCuerda failed" in result.stdout and "cut short" in result.stdout
    sites.lacuerda.pages[SEARCH_URL] = tiza_answer()  # the cache holds the page cut short
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza")
    assert result.stdout.startswith("Searched: LaCuerda has 2 songs") and sites.lacuerda.requests == [SEARCH_URL] * 2


def test_lacuerda_search_progress_says_how_it_goes_for_the_job_page(tmp_path, sites, quick):
    from caracole.get import read_progress_line

    sites.lacuerda.pages[SEARCH_URL] = tiza_answer()
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza", "--progress")
    events = [e for e in map(read_progress_line, result.stdout.splitlines()) if e is not None]
    assert [(e["stage"], e["state"]) for e in events] == [("search", "running"), ("search", "done")]
    assert events[-1]["detail"] == "Searched: LaCuerda has 2 songs for “corazon de tiza”, in the index now."
    assert result.stdout.splitlines()[-1] == events[-1]["detail"]


def test_lacuerda_search_that_failed_isnt_sent_by_the_page_again_within_the_hour_but_by_hand_it_is(tmp_path, sites,
                                                                                                  quick):
    sites.lacuerda.status = 500
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza", "--auto")
    assert result.exit_code == 0 and searched(result) == "Not searched: LaCuerda failed."
    assert sites.lacuerda.requests == [SEARCH_URL]
    # LaCuerda answers again, but the page's own search of that query waits an hour: an answer caracole can't read
    # isn't asked for again on every page that shows the query. Its words in any order are the same query.
    sites.lacuerda.status = None
    sites.lacuerda.pages[SEARCH_URL] = tiza_answer()
    result = run(tmp_path, "lacuerda", "--search", "tiza corazon", "--auto")
    assert result.exit_code == 0 and sites.lacuerda.requests == [SEARCH_URL]
    assert searched(result) == "Not searched: LaCuerda's search for “tiza corazon” failed less than an hour ago."
    assert "so the page won't send it by itself before " in result.stdout and "HTTP 500" in result.stdout
    assert result.stdout.rstrip().endswith("its Ask LaCuerda button, Try again or a terminal asks now.")
    # By hand (its button, Try again, a terminal) it asks, and an answer clears the failure.
    assert run(tmp_path, "lacuerda", "--search", "corazon de tiza").stdout.startswith("Searched: LaCuerda has 2")
    assert sites.lacuerda.requests == [SEARCH_URL] * 2
    conn = open_db(tmp_path)
    try:
        assert db.kv_get_json(conn, "lacuerda:search-failed") == {}
    finally:
        conn.close()


def test_lacuerda_search_after_three_failures_in_an_hour_the_page_sends_none_by_itself(tmp_path, sites, quick):
    sites.lacuerda.status = 500
    for q in ("corazon de papel", "corazon de cristal", "corazon de piedra"):
        assert searched(run(tmp_path, "lacuerda", "--search", q, "--auto")) == "Not searched: LaCuerda failed."
    assert len(sites.lacuerda.requests) == 3
    sites.lacuerda.status = None
    sites.lacuerda.pages[SEARCH_URL] = tiza_answer()
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza", "--auto")
    assert searched(result) == "Not searched: 3 searches of LaCuerda failed in the last hour."
    assert "so the page sends none by itself before " in result.stdout and len(sites.lacuerda.requests) == 3
    # An hour after the first of them, two failed in the last hour: the page's own searches go again.
    conn = open_db(tmp_path)
    try:
        failed = db.kv_get_json(conn, "lacuerda:search-failed")
        assert sorted(failed) == ["corazon-cristal", "corazon-papel", "corazon-piedra"]
        failed["corazon-papel"]["at"] = (datetime.now(UTC) - timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.kv_set_json(conn, "lacuerda:search-failed", failed)
        conn.commit()
    finally:
        conn.close()
    result = run(tmp_path, "lacuerda", "--search", "corazon de tiza", "--auto")
    assert result.stdout.startswith("Searched: LaCuerda has 2") and sites.lacuerda.requests[-1] == SEARCH_URL


def test_lacuerda_search_that_the_index_or_your_library_answers_sends_no_request(tmp_path, sites, quick):
    # Soda Stereo's page is in the HTTP cache, not in the index: the search puts it there first, from the cache,
    # and then has its answer with no request.
    sites.lacuerda.pages[SODA] = (LACUERDA_FIXTURES / "artist.html").read_text(encoding="utf-8")
    assert run(tmp_path, "lacuerda", "--artist", "soda_stereo").exit_code == 0
    conn = open_db(tmp_path)
    try:
        conn.execute("DELETE FROM lacuerda_index WHERE title != ''")
        conn.commit()
    finally:
        conn.close()
    result = run(tmp_path, "lacuerda", "--search", "persiana americana", "--auto")
    assert result.exit_code == 0 and sites.lacuerda.requests == [SODA]
    assert result.stdout == ("Found already: caracole has “persiana americana” already, in your library or its copy "
                             "of LaCuerda's index; no request sent.\n")
    assert searched(result) == ("Found already: caracole has “persiana americana” already, in your library or its "
                                "copy of LaCuerda's index.")
    # A song of yours the query names: you are looking through your songs, and LaCuerda isn't asked.
    seed(tmp_path, ("Oasis", "Wonderwall"))
    result = run(tmp_path, "lacuerda", "--search", "oasis wonderwall")
    assert result.stdout.startswith("Found already: ") and sites.lacuerda.requests == [SODA]


# --- the pages -----------------------------------------------------------------------------

STALE = "as an earlier run left it\n"
PAGES = ("_todo.md", "index.html")


def stale_pages(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        (lib / name).write_text(STALE, encoding="utf-8")


def pages(tmp_path):
    return [(tmp_path / "lib" / name).read_text(encoding="utf-8") for name in PAGES]


def test_lyrics_rewrites_the_pages(tmp_path, sites):
    sites.lrclib.records.append(hit_record())
    seed(tmp_path, ("Soda Stereo", "De Música Ligera"))
    stale_pages(tmp_path)
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    todo, index = pages(tmp_path)
    assert "1 song: 0 found, 1 wanted" in todo
    assert "lyrics.txt" in index  # the lyrics it just found


def test_lacuerda_rewrites_the_pages(tmp_path, sites):
    sites.lacuerda.pages.update(soda_pages())
    spanish_song(tmp_path)
    stale_pages(tmp_path)
    result = run(tmp_path, "lacuerda")
    assert result.exit_code == 0, result.output
    todo, index = pages(tmp_path)
    assert "1 song: 1 found, 0 wanted" in todo  # the sheet it just kept
    assert "sheet.txt" in index


@pytest.mark.parametrize("command,provider", [("lyrics", "lrclib"), ("lacuerda", "lacuerda")])
def test_a_block_rewrites_the_pages_with_the_cooldown(tmp_path, sites, command, provider):
    getattr(sites, provider).status = 429
    spanish_song(tmp_path)
    conn = open_db(tmp_path)
    try:
        update_song(conn, 1, lyrics_status="pending")
    finally:
        conn.close()
    stale_pages(tmp_path)
    result = run(tmp_path, command)
    assert result.exit_code == 0, result.output
    todo, _ = pages(tmp_path)
    assert f"| {provider} | cooling down until " in todo


@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("command,provider", [("lyrics", "lrclib"), ("lacuerda", "lacuerda")])
def test_the_pages_after_a_lookup_went_first_read_overrides_toml_again(tmp_path, sites, monkeypatch, command,
                                                                       provider, blocked):
    # In the pause before its first request, the command let `caracole get --tab` go first, which pinned a tab:
    # the pages it writes at its end, after a block too, go by overrides.toml as the lookup left it.
    import caracole.commands.lyrics as cmd

    sites.lacuerda.pages.update(soda_pages())
    spanish_song(tmp_path)
    conn = open_db(tmp_path)
    try:
        update_song(conn, 1, lyrics_status="pending")
    finally:
        conn.close()
    overrides = tmp_path / "lib" / "overrides.toml"
    site = getattr(sites, provider)
    answer = site.handler

    def lookup_first(request):
        if not overrides.exists():
            overrides.parent.mkdir(parents=True, exist_ok=True)
            overrides.write_text('[pin]\n"Radiohead - Creep" = ["https://tabs.ultimate-guitar.com/tab/2"]\n',
                                 encoding="utf-8")
            monkeypatch.setattr(_common, "_handoffs", _common.handoffs() + 1)
        return httpx.Response(429, text="nope") if blocked else answer(request)

    monkeypatch.setattr(site, "handler", lookup_first)
    seen = []
    monkeypatch.setattr(cmd, "write_pages", lambda conn, cfg, o, now: seen.append([*o.pin.values()]))
    result = run(tmp_path, command)
    assert result.exit_code == 0, result.output
    # `caracole lyrics` writes them after each site's pass: after Megalobiz's too, for the song LRCLIB missed.
    assert seen and all(pins == [(2,)] for pins in seen)


@pytest.mark.parametrize("command,provider", [("lyrics", "lrclib"), ("lacuerda", "lacuerda")])
def test_a_cooldown_leaves_the_pages_alone(tmp_path, sites, command, provider):
    spanish_song(tmp_path)
    conn = open_db(tmp_path)
    try:
        update_song(conn, 1, lyrics_status="pending")
        record_block(conn, provider, datetime.now(UTC), f"{provider}: 403: HTTP 403")
    finally:
        conn.close()
    stale_pages(tmp_path)
    result = run(tmp_path, command)
    assert "cooling down" in result.stdout, result.output
    assert pages(tmp_path) == [STALE, STALE]


@pytest.mark.parametrize("command", ["lyrics", "lacuerda"])
def test_nothing_to_do_leaves_the_pages_alone(tmp_path, sites, command):
    stale_pages(tmp_path)
    result = run(tmp_path, command)
    assert result.exit_code == 0, result.output
    assert "No song" in result.stdout
    assert pages(tmp_path) == [STALE, STALE]


# --- start-up ------------------------------------------------------------------------------


@pytest.mark.slow
def test_registering_the_commands_imports_neither_pass(tmp_path):
    # Every command module is imported on every start; the passes wait for their command.
    src = Path(__file__).resolve().parents[1] / "src"
    passes = ("caracole.lyrics", "caracole.lacuerda", "caracole.lacuerda_fetch", "caracole.lacuerda_index",
              "caracole.lacuerda_search", "caracole.gtptabs", "caracole.gtptabs_fetch", "caracole.musescore",
              "caracole.musescore_fetch", "caracole.megalobiz", "caracole.megalobiz_fetch", "caracole.azlyrics",
              "caracole.azlyrics_fetch")
    code = (
        "import sys, typer\n"
        "from caracole.commands import lyrics\n"
        "lyrics.register(typer.Typer())\n"
        f"print([m for m in {passes!r} if m in sys.modules])\n"
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"
    # The help's share of the hour's lookups, written there so that registering imports no pass, is the pass's.
    from caracole import lacuerda_search
    from caracole.commands.lyrics import LACUERDA_SEARCHES_PER_HOUR

    assert LACUERDA_SEARCHES_PER_HOUR == lacuerda_search.SEARCHES_PER_HOUR


def test_lyrics_asks_azlyrics_for_a_song_the_others_missed(tmp_path, sites):
    from helpers.azlyrics_site import ARTIST, POMME, SONG

    sites.azlyrics.pages.update(POMME)
    (song_id,) = seed(tmp_path, ("pomme", "mononoke"))
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "AZLyrics: 1 found, 0 missing, 0 errors" in result.stdout
    assert sites.azlyrics.requests == [ARTIST, SONG]
    stored = song(tmp_path, song_id)
    assert stored.lyrics_status == "found" and json.loads(stored.lyrics_json)["provider"] == "azlyrics"


def test_lyrics_asks_the_page_overrides_toml_names(tmp_path, sites):
    from helpers.azlyrics_site import POMME, SONG

    sites.azlyrics.pages.update(POMME)
    (song_id,) = seed(tmp_path, ("Misc Musicals", "Mononoke"))
    (tmp_path / "lib").mkdir(exist_ok=True)
    (tmp_path / "lib" / "overrides.toml").write_text(
        '[azlyrics]\n"Misc Musicals - Mononoke" = "azlyrics.com/lyrics/pomme/mononoke.html"\n', encoding="utf-8")
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert sites.azlyrics.requests == [SONG]
    assert song(tmp_path, song_id).lyrics_status == "found"


def test_lyrics_with_azlyrics_turned_off_asks_it_nothing(tmp_path, sites):
    seed(tmp_path, ("pomme", "mononoke"))
    result = run(tmp_path, "lyrics", off=("azlyrics",))
    assert result.exit_code == 0, result.output
    assert "AZLyrics" not in result.stdout and sites.azlyrics.requests == []


def test_an_azlyrics_block_cools_it_down_and_leaves_the_song_as_it_was(tmp_path, sites):
    from helpers.azlyrics_site import ARTIST

    sites.azlyrics.failing[ARTIST] = "block"
    (song_id,) = seed(tmp_path, ("pomme", "mononoke"))
    result = run(tmp_path, "lyrics", ntfy=True)
    assert result.exit_code == 0, result.output
    assert "AZLyrics blocked caracole" in result.stdout
    conn = open_db(tmp_path)
    try:
        assert is_cooling(conn, "azlyrics", _common.utcnow())
    finally:
        conn.close()
    assert song(tmp_path, song_id).lyrics_status == "missing"


def test_lyrics_found_go_on_the_auto_sheet_and_its_page_at_once(tmp_path, sites, monkeypatch):
    from helpers.azlyrics_site import POMME

    from helpers.rendered import fake_chordpro

    from caracole import render
    from caracole.autochords import ChordSegment, build_sheet
    from caracole.autochords.run import _keep
    from caracole.config import load_config
    from caracole.library import song_dir
    from caracole.overrides import Overrides

    sites.azlyrics.pages.update(POMME)
    (song_id,) = seed(tmp_path, ("pomme", "mononoke"))
    render_all = render.render_all
    monkeypatch.setattr(render, "render_all", lambda *a, **kw: render_all(*a, runner=fake_chordpro, **kw))
    cfg = load_config(write_config(tmp_path), env={"HOME": str(tmp_path)})
    conn = open_db(tmp_path)
    try:
        stored = get_song(conn, song_id)
        _keep(conn, cfg, stored, build_sheet([ChordSegment(0.0, 4.0, "C")], title="mononoke", artist="pomme"), "none",
              None, "2026-10-30T13:42:00Z")
        render.render_all(conn, cfg, Overrides())
    finally:
        conn.close()
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "Auto sheets: 1 given lyrics, 1 rendered" in result.stdout
    page = song_dir(cfg.library_dir, stored) / "sheet (auto).html"
    assert "Des mots inventés" in page.read_text(encoding="utf-8")


def test_lyrics_with_no_auto_sheet_to_give_them_to_says_nothing_of_one(tmp_path, sites):
    seed(tmp_path, ("pomme", "mononoke"))
    result = run(tmp_path, "lyrics")
    assert result.exit_code == 0, result.output
    assert "Auto sheets" not in result.stdout
