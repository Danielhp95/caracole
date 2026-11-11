"""tests/helpers/fake_sites.py: the fake sites server the phone's lookups end to end are sent to (lane lookups-e2e).

It answers a scenario's pages as the sites would, by the URL Kotlin's RoutedTransport carries (``GET /fetch?url=…``),
counts and logs every request, answers 404 for a URL it has no rule for (logged unknown) and for one robots.txt
closes (logged closed), never takes the owner's port, and serves the scenario's index and document. caracole itself,
its clients routed there (``fake_sites.routed``), looks the scenario's songs up against it as it would against the
sites: so the pages the phone is given are pages caracole reads.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import subprocess_pythonpath
from helpers.fake_sites import (
    LOOKUPS,
    OWNERS_PORT,
    VOTES_PER_READ,
    FakeSites,
    build_index,
    by_provider,
    harptabs_rows,
    index_rows,
    log,
    routed,
    wait_until_up,
)

from caracole import db

REPO = Path(__file__).resolve().parents[1]
ROLES = {s.role: s for s in LOOKUPS}


@pytest.fixture
def sites():
    with FakeSites("lookups") as fake:
        yield fake


def fetch(sites: FakeSites, url: str, user_agent: str = "caracole-test") -> tuple[int, bytes]:
    """``url`` asked of the fake sites as RoutedTransport asks it, straight (no proxy)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    routed_url = f"{sites.url}/fetch?url={urllib.parse.quote_plus(url)}"
    request = urllib.request.Request(routed_url, headers={"User-Agent": user_agent})
    try:
        with opener.open(request, timeout=30) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def read(sites: FakeSites, path: str) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(sites.url + path, timeout=30) as answer:
        return answer.read()


def test_a_tab_page_is_ug_s_markup_with_its_other_versions_and_every_request_is_logged(sites):
    from caracole.ug.page import parse_tab_page

    song = ROLES["get_it"]
    status, body = fetch(sites, song.tab_url(song.tabs[0]), "caracole/0.1 (+test)")
    assert status == 200
    page = parse_tab_page(body.decode("utf-8"))
    assert page.tab.tab_id == song.tabs[0] and page.tab.song_name == "The Minstrel Boy"
    assert sorted(v.tab_id for v in page.versions) == sorted(song.tabs[1:])  # its others, as UG lists them
    assert "[ch]Am[/ch]" in page.content
    assert page.artist_url == song.artist.page

    status, _ = fetch(sites, "https://tabs.ultimate-guitar.com/tab/nobody/nothing-chords-1")
    assert status == 404
    asked = log(sites.url)
    assert [(r["n"], r["provider"], r["status"], r["known"], r["closed"]) for r in asked] == [
        (1, "ug", 200, True, False), (2, "ug", 404, False, False)]
    assert asked[0]["user_agent"] == "caracole/0.1 (+test)"
    assert [r["n"] for r in log(sites.url, since=1)] == [2]


def test_a_url_robots_txt_closes_is_never_answered_and_is_logged_closed(sites):
    status, _ = fetch(sites, "https://tabs.ultimate-guitar.com/tab/print?id=7000001")
    assert status == 404
    (entry,) = sites.requests
    assert entry["closed"] and not entry["known"]


def test_the_blocked_songs_page_is_a_403(sites):
    song = ROLES["blocked"]
    assert fetch(sites, song.tab_url(song.tabs[0]))[0] == 403


def test_the_closed_songs_page_redirects_to_its_print_view_which_robots_txt_closes(sites):
    from caracole.http import robots_disallows

    song = ROLES["closed"]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    url = f"{sites.url}/fetch?url={urllib.parse.quote_plus(song.tab_url(song.tabs[0]))}"
    with pytest.raises(urllib.error.HTTPError) as answer:
        opener.open(url, timeout=30)
    assert answer.value.code == 301
    assert answer.value.headers["Location"] == song.print_url(song.tabs[0])
    assert robots_disallows(song.print_url(song.tabs[0])) is not None
    assert [r["known"] for r in sites.requests] == [True]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_the_get_it_songs_votes_grow_with_every_read_of_a_page(sites):
    from caracole.ug.page import parse_tab_page

    song = ROLES["get_it"]
    first, second = (parse_tab_page(fetch(sites, song.tab_url(song.tabs[0]))[1].decode()) for _ in range(2))
    assert second.tab.votes == first.tab.votes + VOTES_PER_READ
    other = ROLES["fetch_now"]
    once, again = (parse_tab_page(fetch(sites, other.tab_url(other.tabs[0]))[1].decode()) for _ in range(2))
    assert once.tab.votes == again.tab.votes


def test_the_artist_page_lists_the_bare_tab_no_sitemap_has(sites):
    from caracole.ug.artist import parse_artist_page

    song = ROLES["artist_page"]
    status, body = fetch(sites, song.artist.page + "?filter=chords")
    assert status == 200
    listed = parse_artist_page(body.decode("utf-8"))
    tabs = {t.tab_id: t for t in listed.tabs}
    assert song.bare in tabs and tabs[song.bare].url == f"https://tabs.ultimate-guitar.com/tab/{song.bare}"
    assert song.bare not in {tab for _, _, tab in index_rows()}


def test_lrclib_has_the_get_it_songs_timed_lyrics_and_none_else(sites):
    song, other = ROLES["get_it"], ROLES["fetch_now"]
    query = urllib.parse.urlencode({"artist_name": song.artist.name, "track_name": song.title})
    status, body = fetch(sites, f"https://lrclib.net/api/get?{query}")
    assert status == 200 and json.loads(body)["syncedLyrics"].startswith("[00:10.00] Made-up words")
    query = urllib.parse.urlencode({"artist_name": other.artist.name, "track_name": other.title})
    assert fetch(sites, f"https://lrclib.net/api/get?{query}")[0] == 404
    status, body = fetch(sites, f"https://lrclib.net/api/search?{query}")
    assert (status, json.loads(body)) == (200, [])
    assert all(r["known"] for r in sites.requests)


def test_a_gtptabs_artist_page_lists_none_of_the_scenarios_songs(sites):
    from caracole.gtptabs import parse_artist_page

    url = "https://gtptabs.com/tabs/20/traditional.html"
    status, body = fetch(sites, url)
    assert status == 200 and parse_artist_page(body.decode("utf-8"), url) == []
    assert [r["known"] for r in sites.requests] == [True]


def test_the_chinese_songs_charts_sing_chinese_words(sites):
    from caracole.ug.page import parse_tab_page
    from caracole.viewer.page import written_script

    song = ROLES["chinese"]
    pages = [parse_tab_page(fetch(sites, song.tab_url(tab))[1].decode("utf-8")) for tab in song.tabs]
    assert [p.tab.tab_id for p in pages] == list(song.tabs)
    assert all("这是为测试编的歌词" in p.content and written_script(p.content) for p in pages)


def test_harptabs_has_the_harmonica_songs_tab_by_its_artist(sites):
    from caracole.harptabs import parse_tab_page
    from helpers.e2e_library import harmonica_tab

    song = ROLES["harmonica"]
    url = f"https://www.harptabs.com/{song.harp_path}"
    status, body = fetch(sites, url)
    assert status == 200
    tab = parse_tab_page(body.decode("utf-8"), url)
    assert tab.artist == "henry clay work" and tab.title == "marching through georgia"
    assert tab.body.strip() == harmonica_tab(song.title).strip() and tab.key == "C"
    assert fetch(sites, "https://www.harptabs.com/tab/6102/another-tab")[0] == 404
    assert [r["known"] for r in sites.requests] == [True, False]


def test_it_never_takes_the_owners_port():
    with pytest.raises(ValueError, match="owner"):
        FakeSites("lookups", OWNERS_PORT)


def test_its_index_is_an_index_export_of_the_scenarios_songs_and_its_document_names_their_rows(sites, tmp_path):
    index = tmp_path / "index.sqlite"
    index.write_bytes(read(sites, "/index.sqlite"))
    with sqlite3.connect(index) as conn:
        assert conn.execute("SELECT COUNT(*) FROM caracole_export").fetchone()[0] >= 1
        rows = {t: path for t, path in conn.execute("SELECT tab_id, path FROM ug_index")}
    assert rows == {tab: f"{a}/{s}-chords-{tab}" for a, s, tab in index_rows()}  # each at its sitemap's path
    with sqlite3.connect(index) as conn:  # harptabs.com's rows of the harmonica tab, and of its artist's page
        harp = set(conn.execute("SELECT path, kind, page_id, key FROM harptabs_index"))
    assert harp == set(harptabs_rows()) and {kind for _, kind, _, _ in harp} == {"artist", "tab"}
    document = json.loads(read(sites, "/scenario.json"))
    assert set(document["songs"]) == set(ROLES)
    found = document["songs"]["get_it"]["search"]
    assert found["ug"] == "thomas-moore/minstrel-boy" and found["query"] == "minstrel boy"
    assert document["limits"]["ug"]["lookup_requests"] == 6
    assert document["songs"]["artist_page"]["tabs"] == ["https://tabs.ultimate-guitar.com/tab/7000021"]


# --- caracole itself, against the fake sites --------------------------------------------------------------------


class Chordpro:
    """chordpro: a dummy PDF where it is told to write one."""

    def __call__(self, cmd, **kwargs):
        out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output="))
        Path(out).write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_caracole_looks_the_scenarios_songs_up_against_it_within_a_lookups_limits(sites, cfg, monkeypatch, tmp_path):
    from caracole.commands import _common
    from caracole.config import DEFAULT_PROVIDERS
    from caracole.get import LookupRequest, look_up
    from caracole.health import get_state
    from caracole.songs import list_songs

    monkeypatch.setattr(_common, "transport_for", lambda provider: routed(sites.url))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    conn = db.connect(cfg.db_path)
    try:
        build_index(conn, tmp_path / "sitemaps")
    finally:
        conn.close()
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

    def files(song) -> set[str]:
        folder = cfg.library_dir / song.artist.name / song.title
        return {p.name for p in folder.iterdir()} if folder.is_dir() else set()

    each = {}
    for role in ("get_it", "fetch_now", "artist_page", "closed", "blocked"):
        song = ROLES[role]
        before = len(sites.requests)
        result = look_up(cfg, LookupRequest(song.artist.name, song.title), runner=Chordpro(), now=now)
        each[role] = sites.requests[before:]
        assert result.song_id is not None, role
    for role, asked in each.items():
        for provider, n in by_provider(asked).items():
            assert n <= DEFAULT_PROVIDERS[provider].lookup_requests, (role, provider, asked)
    every = sites.requests
    assert not any(r["closed"] for r in every)
    assert [r for r in every if not r["known"]] == []  # every URL caracole asks is one the scenario answers
    assert {r["user_agent"] for r in every} == {cfg.user_agent}
    closed = ROLES["closed"]
    # its page asked (by the sheet's stage, then the ug stage: a 301 is never cached), its redirect never followed
    assert {r["status"] for r in each["closed"] if r["url"] == closed.tab_url(closed.tabs[0])} == {301}
    assert not any(r["url"] == closed.print_url(closed.tabs[0]) for r in every)

    assert {"sheet.txt", "sheet.json", "lyrics.lrc"} <= files(ROLES["get_it"])
    assert "sheet.txt" in files(ROLES["fetch_now"])
    assert "sheet.txt" in files(ROLES["artist_page"])  # from the bare tab its artist's page lists
    assert any(r["url"].startswith(ROLES["artist_page"].artist.page) for r in each["artist_page"])
    assert "sheet.txt" not in files(ROLES["blocked"]) and "sheet.txt" not in files(closed)
    assert (cfg.library_dir / "Thomas Moore" / "The Minstrel Boy" / "lyrics.lrc").read_text().startswith("[00:10.00]")
    conn = db.connect(cfg.db_path)
    try:
        assert get_state(conn, "ug").cooldown_until is not None  # the 403 cooled Ultimate Guitar down
        assert len(list_songs(conn)) == 5
        status = dict(conn.execute("SELECT title, lyrics_status FROM songs"))
        assert (status["The Minstrel Boy"], status["Oft in the Stilly Night"]) == ("found", "missing")
        # Errors are never misses: the block leaves its song matched and waiting for the next run; a redirect to a
        # page robots.txt closes is Ultimate Guitar's answer (RobotsClosed), its song matched and checked.
        decided = {role: tuple(conn.execute("SELECT match_decision, ug_dirty FROM songs WHERE title = ?",
                                            (ROLES[role].title,)).fetchone()) for role in ("closed", "blocked")}
        assert decided == {"closed": ("accept", 0), "blocked": ("accept", 1)}, decided
    finally:
        conn.close()


def test_caracole_keeps_the_chinese_songs_other_version_beside_it_and_the_harmonica_tab(sites, cfg, monkeypatch,
                                                                                     tmp_path):
    from caracole.commands import _common
    from caracole.get import LookupRequest, look_up
    from caracole.render import FILES_KEY

    monkeypatch.setattr(_common, "transport_for", lambda provider: routed(sites.url))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    conn = db.connect(cfg.db_path)
    try:
        build_index(conn, tmp_path / "sitemaps")
    finally:
        conn.close()
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    written = {}
    for role in ("chinese", "harmonica"):
        song = ROLES[role]
        result = look_up(cfg, LookupRequest(song.artist.name, song.title), runner=Chordpro(), now=now)
        conn = db.connect(cfg.db_path)
        try:
            written[role] = set(db.kv_get_json(conn, f"{FILES_KEY}{result.song_id}") or {})
        finally:
            conn.close()
    chinese = ROLES["chinese"]
    assert {f"version-{tab}.txt" for tab in chinese.tabs[1:]} <= {
        p.name for p in (cfg.library_dir / chinese.artist.name / chinese.title).iterdir()}
    assert written == {"chinese": {"sheet.cho", "sheet.html", *(f"version-{t}.html" for t in chinese.tabs[1:])},
                       "harmonica": {"sheet.cho", "sheet.html", "harmonica-1.html"}}
    every = sites.requests
    assert [r for r in every if not r["known"] or r["closed"]] == []
    assert [r["status"] for r in every if r["provider"] == "harptabs"] == [200]


@pytest.mark.slow
def test_serve_answers_on_its_port_until_stopped(tmp_path):
    from helpers.e2e_library import free_port

    port = free_port()
    log_file = tmp_path / "serve.log"
    env = dict(os.environ, PYTHONPATH=subprocess_pythonpath(REPO / "src"))
    with log_file.open("wb") as out:
        server = subprocess.Popen([sys.executable, "-m", "tests.helpers.fake_sites", "serve", "lookups", str(port),
                                   "--address", "127.0.0.1"], cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        url = f"http://127.0.0.1:{port}"
        wait_until_up(url, timeout=120)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "/scenario.json", timeout=30) as answer:
            assert json.load(answer)["scenario"] == "lookups"
        assert log(url) == []
    finally:
        server.terminate()
        server.wait(30)
    assert f"on 127.0.0.1:{port}" in log_file.read_text()
