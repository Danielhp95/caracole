"""The live case of 2026-10-19, end to end and offline: 宋冬野 - 斑马斑马 through the nightly run.

The user found the song on UG at /tab/4180894, which caracole never found: UG's sitemaps list
every tab of the artist by a bare id, the artist page is /artist/634073 (no name), and UG names
the artist "Song Dongye (宋冬野)" and the song "斑马 斑马 Banma Banma Zebra Zebra". The fakes
(helpers.ug_pages) keep the JSON fields and values read live; LRCLIB answers with made-up lines
in Traditional characters, as its records of the song are.

Each night is ``caracole run``'s steps, with UG's own budget and pauses, minus the index refresh
(it would ask for sitemaps: the index here is complete, without the artist, as UG's is) and the
render; LaCuerda's listings of every artist were read the night before, so LaCuerda is asked
nothing. Nothing here reaches the network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from helpers.ug_pages import (
    BANMA_TRADITIONAL_LINES,
    BANMA_UG,
    DONG_XIAOJIE_LINES,
    SONG_DONGYE_URL,
    FakeUG,
)

from caracole import lacuerda_index
from caracole.db import kv_set
from caracole.http import PoliteClient, robots_disallows
from caracole.library import song_dir
from caracole.notify import Notifier
from caracole.pipeline import Services, default_steps, run_pipeline
from caracole.songs import find_song
from caracole.ug.artist import artist_page_url
from caracole.ug.index import mark_built
from caracole.ug.lookup import learned_artist_url
from caracole.versions import get_version, song_versions

NIGHT = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
TAB = "https://tabs.ultimate-guitar.com/tab/"
FOUND = f"{TAB}4180894"  # the page the user found on UG
CHORDS = artist_page_url(SONG_DONGYE_URL, kind="chords")  # read live: …/artist/634073?filter=chords
TABS = artist_page_url(SONG_DONGYE_URL, kind="tabs")
STEPS = ("sync", "match", "lyrics", "fetch", "lacuerda", "todo")
BANMA = "宋冬野/斑马斑马"
DONG = "宋冬野/董小姐"


class FakeLRCLIB:
    """LRCLIB with plain lyrics only for 宋冬野's two songs, made up, in Traditional characters."""

    LYRICS = {"斑马斑马": BANMA_TRADITIONAL_LINES, "董小姐": DONG_XIAOJIE_LINES}

    def handler(self, request: httpx.Request) -> httpx.Response:
        track = request.url.params.get("track_name")
        if request.url.path == "/api/get" and track in self.LYRICS:
            return httpx.Response(200, json={
                "id": 29499942, "name": track, "trackName": track, "artistName": "宋冬野", "albumName": "安和桥北",
                "duration": 253.0, "instrumental": False, "plainLyrics": "\n".join(self.LYRICS[track]),
                "syncedLyrics": None,
            })
        return httpx.Response(200, json=[]) if request.url.path == "/api/search" else httpx.Response(404)


def no_request(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected request: {request.url}")


@pytest.fixture
def library(cfg, conn):
    """A complete UG index without the artist, LaCuerda's listings read, and wanted.txt with the user's line."""
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, 'chords', 'last', '2026-10-01T00:00:00Z', ?)",
        [(1, "radiohead", "creep", "radiohead/creep-chords-1"), (2, "oasis", "wonderwall", "oasis/wonderwall-chords-2")],
    )
    mark_built(conn, NIGHT - timedelta(days=1))
    kv_set(conn, lacuerda_index.COMPLETE_KEY, "2026-10-18T03:30:00Z")  # read a night before, so not due
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    cfg.wanted_file.write_text("# the songs I'm learning\n宋冬野 - 斑马斑马\n", encoding="utf-8")
    return cfg


def night(cfg, conn, ug, *, at=NIGHT):
    """One nightly run; returns the pauses UG's client took before its requests."""
    pauses: list[float] = []
    clients = {
        "ug": PoliteClient("ug", cfg.provider("ug"), cfg.cache_dir, user_agent="caracole-test",
                           transport=httpx.MockTransport(ug.handler), sleep=pauses.append, clock=lambda: 0.0,
                           wall_clock=lambda: at),
        "lrclib": PoliteClient("lrclib", cfg.provider("lrclib"), cfg.cache_dir, user_agent="caracole-test",
                               transport=httpx.MockTransport(FakeLRCLIB().handler), sleep=lambda s: None,
                               wall_clock=lambda: at),
        "lacuerda": PoliteClient("lacuerda", cfg.provider("lacuerda"), cfg.cache_dir, user_agent="caracole-test",
                                 transport=httpx.MockTransport(no_request), sleep=lambda s: None),
    }
    services = Services(clients=clients, notifier=Notifier(None))
    try:
        report = run_pipeline(cfg, conn=conn, services=services, steps=[s for s in default_steps() if s.name in STEPS],
                              now=at)
    finally:
        services.close()
    assert report.ok, report.errors
    return pauses


def paste(cfg, toml):
    cfg.overrides_file.write_text(toml, encoding="utf-8")


def todo_page(cfg):
    return (cfg.library_dir / "_todo.md").read_text(encoding="utf-8")


def kept_sheet(cfg, conn, key):
    """The UG tab id of a song's kept sheet.json, its text, and its version's lyric coverage."""
    song = find_song(conn, key)
    folder = song_dir(cfg.library_dir, song)
    doc = json.loads((folder / "sheet.json").read_text(encoding="utf-8"))
    (row,) = [r for r in song_versions(conn, song.id) if int(r.tab_id) == doc["version"]["id"]]
    return doc["version"]["id"], (folder / "sheet.txt").read_text(encoding="utf-8"), get_version(conn, row.id).coverage


def polite(requests, pauses):
    """Every UG request open in robots.txt (no search.php, no download or print page), one at a time,
    2.5 to 5 seconds after the one before."""
    assert all(robots_disallows(u) is None and "search.php" not in u for u in requests), requests
    assert len(pauses) == max(len(requests) - 1, 0) and all(2.5 <= p <= 5 for p in pauses), pauses
    return True


def test_the_artist_page_pasted_as_the_browser_shows_it_finds_banma(library, conn):
    cfg, ug = library, FakeUG()

    night(cfg, conn, ug)

    # (d) Before: the index can't see the artist, and UG is asked for nothing.
    song = find_song(conn, BANMA)
    assert (song.match_decision, song.status, song.lyrics_status) == ("not_found", "wanted", "found")
    assert ug.requests == []
    section = todo_page(cfg).split("## Artists to find on Ultimate Guitar", 1)[1].split("\n## ", 1)[0]
    assert "- **宋冬野** (1 song)" in section
    assert "open the artist's page, or any of their tab pages, and copy its address" in section
    assert '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/…"' in section
    assert "<name>" not in section and "`https://www.ultimate-guitar.com/artist/634073`" in section

    # (a) The artist page, pasted as the browser showed it.
    paste(cfg, '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/634073?filter=chords"\n')
    pauses = night(cfg, conn, ug, at=NIGHT + timedelta(days=1))

    song = find_song(conn, BANMA)
    assert (song.status, song.match_decision, song.match_step) == ("found", "accept", "artist_page")
    tab_id, text, coverage = kept_sheet(cfg, conn, BANMA)
    assert tab_id in (4180894, 4689017) and coverage == 1.0
    assert BANMA_TRADITIONAL_LINES[0] in text and "[ch]" not in text
    assert ug.requests == [CHORDS, TABS, f"{TAB}4180894", f"{TAB}4689017"] and polite(ug.requests, pauses)
    assert "## Artists to find" not in todo_page(cfg)  # (d) After


def test_a_tab_page_of_the_artist_pasted_under_artist_url_finds_banma(library, conn):
    cfg, ug = library, FakeUG()
    paste(cfg, f'[artist_url]\n"宋冬野" = "{FOUND}"\n')

    pauses = night(cfg, conn, ug)

    song = find_song(conn, BANMA)
    assert (song.status, song.match_step) == ("found", "artist_page")
    tab_id, _, coverage = kept_sheet(cfg, conn, BANMA)
    assert tab_id in (4180894, 4689017) and coverage == 1.0
    # One request for the tab page, through the night's polite client; the sheet slot reads it from the cache.
    assert ug.requests == [FOUND, CHORDS, TABS, f"{TAB}4689017"] and polite(ug.requests, pauses)
    assert learned_artist_url(conn, "宋冬野") == SONG_DONGYE_URL
    assert "## Artists to find" not in todo_page(cfg)

    night(cfg, conn, ug, at=NIGHT + timedelta(days=1))

    assert len(ug.requests) == 4  # remembered: nothing is asked again


def test_a_pin_of_the_tab_page_finds_banma_and_teaches_the_artist_page_for_the_artists_other_songs(library, conn):
    cfg, ug = library, FakeUG()
    with cfg.wanted_file.open("a", encoding="utf-8") as f:
        f.write("宋冬野 - 董小姐\n")
    paste(cfg, f'[pin]\n"宋冬野 - 斑马斑马" = ["{FOUND}"]\n')

    pauses = night(cfg, conn, ug)

    banma = find_song(conn, BANMA)
    assert (banma.status, banma.match_decision) == ("found", "pinned")
    assert kept_sheet(cfg, conn, BANMA)[0] == 4180894 and ug.requests == [FOUND] and polite(ug.requests, pauses)
    assert learned_artist_url(conn, "宋冬野") == SONG_DONGYE_URL  # filed under the song's artist too
    assert find_song(conn, DONG).match_decision == "not_found"
    assert "## Artists to find" not in todo_page(cfg)  # the artist's page is known now
    ug.requests.clear()

    pauses = night(cfg, conn, ug, at=NIGHT + timedelta(days=1))

    dong = find_song(conn, DONG)
    assert (dong.status, dong.match_step) == ("found", "artist_page")
    tab_id, text, coverage = kept_sheet(cfg, conn, DONG)
    assert tab_id in (3016223, 3204647) and coverage == 1.0 and DONG_XIAOJIE_LINES[0] in text
    assert ug.requests == [CHORDS, TABS, f"{TAB}3016223", f"{TAB}3204647"] and polite(ug.requests, pauses)
    assert {int(r.tab_id) for r in song_versions(conn, dong.id)} == {3016223, 3204647}  # 斑马斑马's are not its own
    assert find_song(conn, BANMA).status == "found"


def test_the_live_artist_page_lists_banma_under_the_names_ug_gave_it(library, conn):
    # The fake keeps what UG showed: names in two scripts, bare tab URLs, the bare artist page.
    from caracole.ug.artist import parse_artist_page
    from caracole.ug.page import parse_tab_page

    ug = FakeUG()
    page = parse_artist_page(ug.pages[CHORDS], url=CHORDS)
    assert (page.artist_id, page.name, page.pages) == (634073, "Song Dongye (宋冬野)", 1)
    assert set(page.filters) == {"chords", "tabs"}
    assert [(t.tab_id, t.song_name) for t in page.tabs][:3] == [
        (6613886, "与我交谈 Speak With Me"), (4180894, BANMA_UG), (4689017, BANMA_UG)]
    assert all(t.url == f"{TAB}{t.tab_id}" for t in page.tabs)
    tab = parse_tab_page(ug.pages[FOUND], url=FOUND)
    assert (tab.tab.song_name, tab.tab.artist_name, tab.tab.type, tab.tab.version, tab.tab.access) == (
        BANMA_UG, "Song Dongye (宋冬野)", "Chords", 1, "public")
    assert tab.tab.raw["artist_id"] == 634073 and tab.artist_url == SONG_DONGYE_URL
    assert [(v.tab_id, v.type, v.version) for v in tab.versions] == [(4689017, "Chords", 2)]
    assert tab.content is not None and tab.content.startswith("[tab][ch]C[/ch] [ch]D[/ch] [ch]Bm[/ch] [ch]Em[/ch]\n")


def test_the_owners_link_pasted_is_read_found_by_a_search_and_fetched_with_its_version(tmp_path, monkeypatch):
    # 2026-11-17: the owner searched for 斑马斑马, found nothing, and pasted the page UG has it at into the library
    # page's box. The page asks /api/ug/link (no request: never read), posts /ug/link, whose job is caracole ug --link:
    # the tab's page and its artist's lists, through the lookup's polite client. Then the link is found, a search finds
    # the song, and Fetch this version (POST /lookup with the tab) keeps that very version as the song's pick.
    from urllib.parse import urlencode

    from helpers.scenario import _empty_pass
    from typer.testing import CliRunner

    from caracole import db
    from caracole.cli import build_app
    from caracole.commands import _common
    from caracole.config import load_config
    from caracole.overrides import load_overrides
    from caracole.web.app import Request, WebApp
    from caracole.web.jobs import JobQueue

    config = tmp_path / "caracole.toml"
    providers = "".join(f"[providers.{p}]\ndelay = [0, 0]\nlookup_delay = [0, 0]\n"
                        for p in ("ug", "lrclib", "megalobiz", "azlyrics", "lacuerda", "gtptabs", "musescore",
                                  "harptabs", "gametabs"))
    config.write_text(f'data_dir = "{tmp_path / "data"}"\n{providers}', encoding="utf-8")
    cfg = load_config(config, env={"HOME": str(tmp_path / "home")})
    cfg.state_dir.mkdir(parents=True)
    cfg.library_dir.mkdir(parents=True)
    with db.connect(cfg.db_path) as conn:  # a complete index without the artist, as UG's sitemaps are
        conn.executemany(
            "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
            "VALUES (?, ?, ?, 'chords', 'last', '2026-10-01T00:00:00Z', ?)",
            [(1, "radiohead", "creep", "radiohead/creep-chords-1"), (2, "oasis", "wonderwall", "oasis/wonderwall-chords-2")])
        mark_built(conn, NIGHT)
    ug, lrclib, elsewhere = FakeUG(), FakeLRCLIB(), []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith("ultimate-guitar.com"):
            return ug.handler(request)
        if request.url.host == "lrclib.net":
            return lrclib.handler(request)
        elsewhere.append(str(request.url))
        return httpx.Response(404, text="not here")

    monkeypatch.setattr(_common, "transport_for", lambda provider: httpx.MockTransport(handler))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    for target, kind in (("caracole.render.render_all", "render"), ("caracole.todo.write_pages", "pages"),
                         ("caracole.songbook.render_songbooks", "songbooks")):
        monkeypatch.setattr(target, _empty_pass(kind))  # a caracole with no ChordPro: no PDF, no page
    app = WebApp(cfg, JobQueue(lambda args, emit: 0, limit=5), allowed=frozenset({"localhost"}), csrf="tok")
    host = {"host": "localhost:8737", "sec-fetch-site": "same-origin", "accept": "application/json"}

    def get(path: str) -> dict:
        response = app.handle(Request("GET", path, host))
        assert response.status == 200, response.body
        return json.loads(response.body)

    def post(path: str, fields: dict) -> dict:
        sent = host | {"content-type": "application/x-www-form-urlencoded", "origin": "http://localhost:8737"}
        response = app.handle(Request("POST", path, sent, urlencode({"csrf": "tok", **fields}).encode("utf-8")))
        assert response.status == 202, response.body
        return json.loads(response.body)

    def run(job_id: int):
        """The queued job's command, as caracole serve's queue runs it."""
        [step] = app.queue.job(job_id).steps
        result = CliRunner().invoke(build_app(), ["--config", str(config), *step.args])
        assert result.exit_code == 0, result.output
        return result

    link = "/api/ug/link?" + urlencode({"url": FOUND})
    assert get(link)["state"] == "auto" and ug.requests == []
    read = run(post("/ug/link", {"url": FOUND})["job"])
    assert read.stdout.splitlines()[-1] == (
        "Read: 斑马 斑马 Banma Banma Zebra Zebra by Song Dongye (宋冬野), chords; their page lists 8 tabs.")
    assert ug.requests == [FOUND, CHORDS, TABS]
    assert all(robots_disallows(u) is None and "search.php" not in u for u in ug.requests)

    found = get(link)
    assert found["state"] == "found" and found["guess"] == {"artist": "宋冬野", "title": "斑马斑马"}
    assert [(h["artist"], h["title"]) for h in found["hits"]] == [("宋冬野", "斑马斑马")]
    searched = get("/api/search?" + urlencode({"q": "斑马斑马"}))
    assert ("宋冬野", "斑马斑马") in [(h["artist"], h["title"]) for h in searched["index"]]

    lookup = post("/lookup", {"artist": "宋冬野", "title": "斑马斑马", "tab": FOUND})  # Fetch this version
    assert f"--tab={FOUND}" in app.queue.job(lookup["job"]).steps[0].args
    run(lookup["job"])
    with db.connect(cfg.db_path) as conn:
        song = find_song(conn, BANMA)
        assert kept_sheet(cfg, conn, BANMA)[0] == 4180894 and song.match_decision == "pinned"
    assert load_overrides(cfg.overrides_file).pin[BANMA] == (4180894,)  # the card's Sheet versions can change it
    mine = get(link)["song"]
    assert (mine["display"], mine["has_sheet"], mine["this_tab"]) == ("宋冬野 - 斑马斑马", True, True)
    assert not any("ultimate-guitar" in u for u in elsewhere)
