"""caracole/get.py: one song looked up now, its sheet readable before anything else is asked.

Every site is a fake behind ``httpx.MockTransport``, reached through
``caracole.commands._common.transport_for``: Ultimate Guitar's tab pages,
LRCLIB's ``/api/get``, LaCuerda's artist and version pages. chordpro is a fake
runner that writes a dummy PDF.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from helpers.ug_pages import make_tab_page_html, version_dict

from caracole import db
from caracole.commands import _common
from caracole.config import load_config
from caracole.health import get_state, record_block
from caracole.overrides import load_overrides
from caracole.songs import find_song, get_song, list_songs
from caracole.ug.index import mark_built, upsert_rows

TAB = "https://tabs.ultimate-guitar.com/tab/"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
LINES = [
    "walking down the river road tonight", "counting every lantern on the shore",
    "the wind is singing softly in the pines", "and nobody remembers what we were",
    "hold the silver morning in your hands", "every window glowing like a promise",
    "we kept the summer folded in a letter", "until the rain forgot to say goodbye",
]
LACUERDA = Path(__file__).parent / "fixtures" / "lacuerda"


def sheet(tag: str, lines) -> str:
    rows = ["[Intro]", tag, ""]
    for line in lines:
        rows += ["[tab][ch]Am[/ch]       [ch]F[/ch]       [ch]C[/ch]", f"{line}[/tab]"]
    return "\r\n".join(rows)


class Sites:
    """Every site caracole asks, by URL; LRCLIB by artist and title. Every request is recorded."""

    def __init__(self):
        self.pages: dict[str, tuple[int, str]] = {}
        self.lyrics: dict[tuple[str, str], str] = {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if request.url.host == "lrclib.net":
            key = (request.url.params.get("artist_name"), request.url.params.get("track_name"))
            if request.url.path == "/api/get" and key in self.lyrics:
                record = {"id": 7, "trackName": key[1], "artistName": key[0], "albumName": "", "duration": 200.0,
                          "instrumental": False, "plainLyrics": self.lyrics[key], "syncedLyrics": None}
                return httpx.Response(200, json=record)
            if request.url.path == "/api/search":
                return httpx.Response(200, json=[])
            return httpx.Response(404, json={"name": "TrackNotFound"})
        status, body = self.pages.get(url, (404, "<html><title>Oops! We couldn't find that page.</title></html>"))
        return httpx.Response(status, text=body)

    def ug(self) -> list[str]:
        return [u for u in self.requests if "ultimate-guitar.com" in u]

    def lrclib(self) -> list[str]:
        return [u for u in self.requests if "lrclib.net" in u]


@pytest.fixture
def sites(monkeypatch) -> Sites:
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", lambda provider: httpx.MockTransport(s.handler))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return s


def write_cfg(tmp_path: Path, extra: str = ""):
    providers = "".join(f"[providers.{p}]\ndelay = [0, 0]\nlookup_delay = [0, 0]\n{extra if p == 'ug' else ''}"
                        for p in ("ug", "lrclib", "lacuerda", "gtptabs", "musescore"))
    path = tmp_path / "caracole.toml"
    path.write_text(f'data_dir = "{tmp_path}"\n{providers}', encoding="utf-8")
    return load_config(path, env={"HOME": str(tmp_path / "home")})


@pytest.fixture
def cfg(tmp_path):
    return write_cfg(tmp_path)


def creep_tab(tab_id: int, *, rating: float, votes: int = 50, artist="Radiohead", song="Creep", kind="chords"):
    slug = f"{artist.lower().replace(' ', '-')}/{song.lower().replace(' ', '-')}"
    return version_dict(tab_id, song=song, artist=artist, rating=rating, votes=votes,
                        type={"chords": "Chords", "tabs": "Tabs"}[kind], tab_url=f"{TAB}{slug}-{kind}-{tab_id}")


def serve_creep(sites: Sites, conn) -> None:
    """Radiohead's Creep in the index and on UG: 101, the best rated, charts a verse; 102 and 103 the song."""
    tabs = [creep_tab(101, rating=4.9, votes=100), creep_tab(102, rating=4.6), creep_tab(103, rating=4.2)]
    texts = {101: LINES[:2], 102: LINES, 103: LINES}
    for tab in tabs:
        others = [t for t in tabs if t is not tab]
        sites.pages[tab["tab_url"]] = (200, make_tab_page_html(tab, others, content=sheet(f"sheet {tab['id']}",
                                                                                            texts[tab["id"]])))
    upsert_rows(conn, [(t["id"], "radiohead", "creep", "chords", t["tab_url"].removeprefix(TAB)) for t in tabs],
                "1", NOW)
    mark_built(conn, NOW)
    sites.lyrics[("Radiohead", "Creep")] = "\n".join(LINES)


class Progress:
    """What a lookup reports, with the UG requests sent when the sheet became readable."""

    def __init__(self, sites: Sites | None = None):
        self.sites = sites
        self.events: list[tuple] = []
        self.said: list[tuple[str, str, str]] = []  # every stage event with its detail
        self.readable_after: int | None = None

    def stage(self, name, state, detail=""):
        self.events.append(("stage", name, state))
        self.said.append((name, state, detail))

    def readable(self, files, seconds):
        self.events.append(("readable", dict(files)))
        if self.sites is not None and self.readable_after is None:
            self.readable_after = len(self.sites.ug())

    def states(self) -> dict[str, str]:
        out = {}
        for event in self.events:
            if event[0] == "stage":
                out[event[1]] = event[2]
        return out


class FakeRunner:
    """chordpro: writes a dummy PDF where it is told to, or fails on a sheet that holds ``fail``."""

    def __init__(self, fail: str | None = None):
        self.calls = 0
        self.fail = fail

    def __call__(self, cmd, **kwargs):
        self.calls += 1
        if self.fail is not None and self.fail in Path(cmd[-1]).read_text(encoding="utf-8"):
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="chordpro: aborted\n")
        out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output="))
        Path(out).write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def look_up(cfg, *, sites=None, runner=None, **request):
    from caracole.get import LookupRequest, look_up as run

    progress = Progress(sites)
    result = run(cfg, LookupRequest(**request), progress, runner=runner or FakeRunner(), now=NOW)
    return result, progress


@pytest.fixture
def conn(cfg):
    c = db.connect(cfg.db_path)
    yield c
    c.close()


def folder(cfg, artist, title) -> Path:
    return cfg.library_dir / artist / title


# --- the sheet first --------------------------------------------------------------------------------


def test_the_sheet_is_readable_after_one_ug_request_and_the_rest_fills_in_after(cfg, conn, sites):
    serve_creep(sites, conn)

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    # One page lists every version and its rating: the best rated is kept at once, readable.
    assert progress.readable_after == 1
    first = next(e for e in progress.events if e[0] == "readable")
    assert first[1]["sheet"] == "Radiohead/Creep/sheet.txt"
    order = [e[1] for e in progress.events if e[0] == "stage" and e[2] == "running"]
    assert order == ["song", "match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs", "pages", "songbooks"]
    assert progress.events.index(first) < progress.events.index(("stage", "lyrics", "running"))
    # Then the lyrics, and with them the sheets are scored: 102 charts the whole song.
    assert "sheet 102" in (folder(cfg, "Radiohead", "Creep") / "sheet.txt").read_text(encoding="utf-8")
    assert (folder(cfg, "Radiohead", "Creep") / "lyrics.txt").is_file()
    assert (folder(cfg, "Radiohead", "Creep") / "sheet.pdf").is_file()
    song = find_song(conn, "radiohead/creep")
    assert (song.status, song.ug_dirty, song.lyrics_status) == ("found", False, "found")
    assert len(sites.ug()) == 3 and len(sites.lrclib()) == 1
    assert result.ok and result.sheet == folder(cfg, "Radiohead", "Creep") / "sheet.txt"
    assert result.seconds_to_sheet is not None and result.seconds_to_sheet < 5
    # The song is in wanted.txt, as `caracole add` writes it, and in the library.
    assert "Radiohead - Creep" in cfg.wanted_file.read_text(encoding="utf-8")
    assert (cfg.library_dir / "index.html").is_file()


def test_a_better_sheet_found_later_is_said_to_be_readable_again(cfg, conn, sites):
    serve_creep(sites, conn)
    _, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")
    readable = [e for e in progress.events if e[0] == "readable"]
    assert len(readable) >= 2 and readable[-1][1].get("pdf") == "Radiohead/Creep/sheet.pdf"


def test_the_requests_of_a_lookup_count_in_its_hourly_budget(cfg, conn, sites):
    serve_creep(sites, conn)
    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")
    runs = {r[0] for r in conn.execute("SELECT DISTINCT run FROM events")}
    assert runs and all(run.startswith("lookup:") for run in runs)


def test_a_lookup_sends_a_few_requests_at_most_and_leaves_the_rest_for_the_night(tmp_path, sites):
    cfg = write_cfg(tmp_path, "lookup_requests = 2\n")
    c = db.connect(cfg.db_path)
    serve_creep(sites, c)

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert len(sites.ug()) == 2
    assert progress.readable_after == 1 and progress.states()["ug"] == "skipped"
    assert "nightly run" in result.details["ug"]
    song = find_song(c, "radiohead/creep")
    assert song.ug_dirty is True and song.match_decision == "accept"  # the night goes on from here
    c.close()


def lookups_spent(conn, provider: str, n: int) -> None:
    """``n`` requests of earlier lookups this hour, as their clients logged them."""
    from datetime import timedelta

    at = (datetime.now(UTC) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.executemany("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, ?, ?, ?)",
                         [("lookup:2026-10-19T11:40:00Z", at, provider, f"{TAB}x-{i}", 200, "ok") for i in range(n)])


def test_half_of_the_hours_lookup_requests_are_kept_for_sheets(cfg, conn, sites):
    # An evening of songs looked up on the spot: what the nightly run would do anyway mustn't eat the sheets.
    serve_creep(sites, conn)
    lookups_spent(conn, "ug", 40)  # of 60 an hour

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert progress.readable_after == 1 and len(sites.ug()) == 1  # the sheet, and nothing more
    assert progress.states()["ug"] == "skipped"
    assert "kept for sheets" in result.details["ug"] and "nightly run" in result.details["ug"]
    assert find_song(conn, "radiohead/creep").ug_dirty is True  # the night goes on from here
    # Later that hour, another song still gets its sheet.
    serve_wonderwall(sites, conn)
    later, progress = look_up(cfg, sites=sites, artist="Oasis", title="Wonderwall")
    assert progress.readable_after is not None and later.sheet is not None


def test_what_follows_the_sheet_spends_only_what_leaves_half_of_the_hour_for_sheets(cfg, conn, sites):
    serve_creep(sites, conn)
    lookups_spent(conn, "ug", 28)  # 2 more, and half of the hour is spent

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert len(sites.ug()) == 2 and progress.readable_after == 1  # the sheet, then one for the rest
    assert progress.states()["ug"] == "skipped" and "kept for sheets" in result.details["ug"]


def serve_wonderwall(sites: Sites, conn) -> None:
    tab = creep_tab(201, rating=4.8, artist="Oasis", song="Wonderwall")
    sites.pages[tab["tab_url"]] = (200, make_tab_page_html(tab, [], content=sheet("sheet 201", LINES)))
    upsert_rows(conn, [(201, "oasis", "wonderwall", "chords", tab["tab_url"].removeprefix(TAB))], "1", NOW)


def test_a_lookup_waits_only_the_short_gap_between_two_requests(tmp_path, sites, monkeypatch):
    path = tmp_path / "caracole.toml"
    path.write_text(f'data_dir = "{tmp_path}"\n', encoding="utf-8")  # the default paces
    cfg = load_config(path, env={"HOME": str(tmp_path / "home")})
    slept: list[float] = []
    monkeypatch.setattr(_common, "sleep", slept.append)
    c = db.connect(cfg.db_path)
    serve_creep(sites, c)
    c.close()

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert slept and max(slept) <= 1.5  # never the bulk 10-20 s
    assert sum(slept) <= 1.5 * len(sites.requests)


# --- its own PDF -------------------------------------------------------------------------------------

ZH_SHEET = "[Verse]\n[tab][ch]C[/ch]       [ch]G[/ch]\n这是一个合成的例子[/tab]\n"


def test_a_lookup_renders_its_own_song_alone(cfg, conn, sites, monkeypatch):
    from caracole import render
    from helpers.rendered import rendered_song

    rendered_song(conn, cfg)  # Soda Stereo - De Música Ligera, kept and rendered
    serve_creep(sites, conn)
    real, built = render.build_viewer, []

    def build_viewer(cho, **kwargs):
        built.append(cho)
        return real(cho, **kwargs)

    monkeypatch.setattr(render, "build_viewer", build_viewer)

    result, _ = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert result.details["pdf"] == "made"
    assert built and all("{title: Creep}" in cho for cho in built)  # the pdf stage's and the pages'


def test_another_songs_failed_pdf_is_not_the_lookups(cfg, conn, sites):
    from caracole.db import kv_get_json
    from caracole.overrides import Overrides
    from caracole.render import render_all

    serve_creep(sites, conn)
    serve_wonderwall(sites, conn)
    runner = FakeRunner(fail="Wonderwall")  # chordpro fails on Wonderwall's sheet, every time
    look_up(cfg, sites=sites, runner=runner, artist="Oasis", title="Wonderwall")
    render_all(conn, cfg, Overrides(), runner=runner, now=datetime(2026, 10, 19, 3, 30, tzinfo=UTC))  # the night's
    nightly = kv_get_json(conn, "render:status")
    assert nightly["failed"] == ["Oasis - Wonderwall"]

    result, progress = look_up(cfg, sites=sites, runner=runner, artist="Radiohead", title="Creep")

    assert progress.states()["pdf"] == "done" and result.details["pdf"] == "made"
    assert kv_get_json(conn, "render:status") == nightly  # the to-do page still tells of the night's render


def test_a_chinese_song_elsewhere_waiting_for_a_font_is_not_the_lookups(cfg, conn, sites):
    from caracole.db import kv_get_json
    from helpers.rendered import rendered_song

    assert cfg.cjk_font is None
    rendered_song(conn, cfg, "宋冬野", "斑马斑马", content=ZH_SHEET)  # no PDF until a CJK font is set
    before = kv_get_json(conn, "render:status")
    assert "宋冬野 - 斑马斑马" in before["font_error"]
    serve_creep(sites, conn)

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert progress.states()["pdf"] == "done" and result.details["pdf"] == "made"
    assert kv_get_json(conn, "render:status") == before


# --- your pick -----------------------------------------------------------------------------------------


def two_creeps(sites, conn):
    """Creep by Radiohead and by Stone Temple Pilots: for "Creep" alone the matcher would ask you."""
    serve_creep(sites, conn)
    stp = creep_tab(501, rating=4.0, artist="Stone Temple Pilots")
    sites.pages[stp["tab_url"]] = (200, make_tab_page_html(stp, [], content=sheet("sheet 501", LINES)))
    upsert_rows(conn, [(501, "stone-temple-pilots", "creep", "chords", stp["tab_url"].removeprefix(TAB))], "1", NOW)


def test_the_ug_song_you_pick_is_recorded_and_fetched_without_review(cfg, conn, sites):
    two_creeps(sites, conn)

    result, _ = look_up(cfg, sites=sites, artist="Stone Temple Pilots", title="Creep",
                        ug="stone-temple-pilots/creep")

    assert load_overrides(cfg.overrides_file).match == {"stone-temple-pilots/creep": ("stone-temple-pilots", "creep")}
    song = find_song(conn, "stone-temple-pilots/creep")
    assert (song.match_decision, song.match_step) == ("accept", "override")
    assert "sheet 501" in (folder(cfg, "Stone Temple Pilots", "Creep") / "sheet.txt").read_text(encoding="utf-8")


def test_the_tab_you_pick_is_pinned_and_kept(cfg, conn, sites):
    serve_creep(sites, conn)

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep", ug="radiohead/creep", tab=f"{TAB}radiohead/creep-chords-103")

    overrides = load_overrides(cfg.overrides_file)
    assert overrides.pin == {"radiohead/creep": (103,)}
    assert find_song(conn, "radiohead/creep").match_decision == "pinned"
    assert "sheet 103" in (folder(cfg, "Radiohead", "Creep") / "sheet.txt").read_text(encoding="utf-8")
    assert sites.ug()[0] == f"{TAB}radiohead/creep-chords-103"


def test_a_picked_version_replaces_only_the_pins_of_its_kind(cfg, conn, sites):
    # You pinned a chords sheet, then pick a text tab: the sheet you chose stays yours.
    from caracole.overrides import add_pin

    serve_creep(sites, conn)
    upsert_rows(conn, [(401, "radiohead", "creep", "tabs", "radiohead/creep-tabs-401")], "1", NOW)
    add_pin(cfg.overrides_file, "Radiohead - Creep", [f"{TAB}radiohead/creep-chords-102"])

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep", tab=f"{TAB}radiohead/creep-tabs-401")
    assert sorted(load_overrides(cfg.overrides_file).pin["radiohead/creep"]) == [102, 401]

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep", tab=f"{TAB}radiohead/creep-chords-103")
    assert sorted(load_overrides(cfg.overrides_file).pin["radiohead/creep"]) == [103, 401]  # chords for chords


def test_a_picked_version_replaces_a_pin_of_a_guitar_pro_page(cfg, conn, sites):
    # A [pin] of a Guitar Pro version on Ultimate Guitar, from when caracole still picked them there: it pins
    # nothing now, so a version you pick takes its place.
    from caracole.overrides import add_pin

    serve_creep(sites, conn)
    upsert_rows(conn, [(301, "radiohead", "creep", "guitar-pro", "radiohead/creep-guitar-pro-301")], "1", NOW)
    add_pin(cfg.overrides_file, "Radiohead - Creep", [f"{TAB}radiohead/creep-guitar-pro-301"])

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep", tab=f"{TAB}radiohead/creep-chords-103")
    assert load_overrides(cfg.overrides_file).pin["radiohead/creep"] == (103,)
    assert f"{TAB}radiohead/creep-guitar-pro-301" not in sites.ug()


def test_a_guitar_pro_page_asked_for_as_the_tab_is_refused_and_nothing_is_written(cfg, conn, sites):
    # caracole picks no Guitar Pro or Power Tab version on Ultimate Guitar: one asked for (an old link, say) would
    # pin nothing, so the lookup says so before it adds or records anything.
    serve_creep(sites, conn)
    upsert_rows(conn, [(301, "radiohead", "creep", "guitar-pro", "radiohead/creep-guitar-pro-301"),
                       (302, "radiohead", "creep", "power", "radiohead/creep-power-302")], "1", NOW)
    for tab in (f"{TAB}radiohead/creep-guitar-pro-301", "302"):
        result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep", tab=tab)

        assert progress.states()["song"] == "failed" and sites.requests == []
        assert "Guitar Pro" in result.details["song"] and "_inbox" in result.details["song"]
    assert not cfg.wanted_file.exists() and not cfg.overrides_file.exists()


def test_a_song_the_matcher_isnt_sure_of_says_so_and_still_gets_its_lyrics(cfg, conn, sites):
    two_creeps(sites, conn)
    sites.lyrics[("Somebody", "Creep")] = "\n".join(LINES)

    result, progress = look_up(cfg, sites=sites, artist="Somebody", title="Creep")

    assert find_song(conn, "somebody/creep").match_decision == "review"
    assert progress.states()["sheet"] == "skipped" and "pick" in result.details["sheet"]
    assert sites.ug() == [] and progress.states()["lyrics"] == "done"


def test_a_lookup_waiting_for_the_lock_says_where_it_is_let_in(cfg, conn, sites):
    # Shown on the lookup page while it waits: behind auto-chords it is let in between two songs, not in a pause.
    import fcntl
    import os
    import threading

    from caracole.get import LookupRequest
    from caracole.get import look_up as run

    serve_creep(sites, conn)
    details: list[str] = []
    waiting = threading.Event()

    class Heard(Progress):
        def stage(self, name, state, detail=""):
            super().stage(name, state, detail)
            if name == "song" and state == "running" and detail:
                details.append(detail)
                waiting.set()

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(cfg.state_dir / _common.LOCK_NAME, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.write(fd, b"4242 autochords\n")
    done: list = []
    thread = threading.Thread(target=lambda: done.append(
        run(cfg, LookupRequest(artist="Radiohead", title="Creep"), Heard(sites), runner=FakeRunner(), now=NOW)))
    thread.start()
    try:
        assert waiting.wait(10)
    finally:
        os.close(fd)
        thread.join(30)
    assert done and done[0].sheet is not None
    [said] = details
    assert "pid 4242: autochords" in said
    assert "at its next pause" in said and "between two songs" in said


# --- errors are never misses ---------------------------------------------------------------------------


def test_a_block_cools_ug_down_and_the_lookup_goes_on(cfg, conn, sites):
    serve_creep(sites, conn)
    sites.pages[f"{TAB}radiohead/creep-chords-101"] = (403, "Forbidden")

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert get_state(conn, "ug").cooldown_until is not None
    assert progress.states()["sheet"] == "skipped" and progress.states()["lyrics"] == "done"
    assert progress.states()["ug"] == "skipped"
    song = find_song(conn, "radiohead/creep")
    assert (song.match_decision, song.ug_dirty) == ("accept", True)
    assert result.ok  # a block is no bug


def test_a_site_cooling_down_is_left_alone(cfg, conn, sites):
    serve_creep(sites, conn)
    record_block(conn, "ug", datetime.now(UTC), "403")

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert sites.ug() == [] and progress.states()["sheet"] == "skipped"
    assert "cooling down" in result.details["sheet"]


def test_a_server_error_leaves_the_song_for_the_night(cfg, conn, sites):
    serve_creep(sites, conn)
    sites.pages[f"{TAB}radiohead/creep-chords-101"] = (500, "oops")

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert progress.states()["sheet"] == "failed" and result.ok
    assert find_song(conn, "radiohead/creep").match_decision == "accept"
    # As in a nightly step, the error ends UG's part: the lookup asks it nothing more.
    assert sites.ug() == [f"{TAB}radiohead/creep-chords-101"] and progress.states()["ug"] == "skipped"


def test_a_lookup_ug_answered_nothing_but_errors_keeps_its_strikes(cfg, conn, sites):
    # Two blocks in a row, the second's cooldown over: the next block cools UG down for 98 hours. A lookup
    # UG answers with nothing but errors is no good run, as a nightly run of nothing but errors isn't.
    from datetime import timedelta

    record_block(conn, "ug", NOW - timedelta(days=10), "403")
    record_block(conn, "ug", NOW - timedelta(days=7), "403")
    serve_creep(sites, conn)
    sites.pages[f"{TAB}radiohead/creep-chords-101"] = (500, "oops")

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    state = get_state(conn, "ug")
    assert (state.strikes, state.last_ok) == (2, None)
    assert get_state(conn, "lrclib").last_ok == NOW  # LRCLIB answered the lookup: a good run of its own


PINKPOP = ("Creep, live at the Pinkpop festival in Landgraaf, the Netherlands, on the fifth of June nineteen ninety six, "
           "in the encore, take")


def test_a_sheet_that_would_go_where_another_songs_is_says_so_and_waits(cfg, conn, sites):
    # Two takes whose titles agree for longer than a folder's name keeps: one folder, where the first keeps its sheet.
    from conftest import add_song

    from caracole.library import keep_file, song_dir
    from caracole.normalize import clean_title, slug_key
    from caracole.versions import upsert_version

    one = add_song(conn, "Radiohead", f"{PINKPOP} one")
    vid = upsert_version(conn, provider="ug", tab_id="1", song_id=one.id, slot="sheet", kind="chords", rating=5,
                         votes=1, version=1, label=None, url=f"{TAB}1", raw={}, now="2026-10-01T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=one, version_id=vid, name="sheet.txt", data=b"take one", rank=1)
    song = slug_key(clean_title(f"{PINKPOP} two"))
    tab = version_dict(301, song=f"{PINKPOP} two", artist="Radiohead", tab_url=f"{TAB}radiohead/{song}-chords-301")
    sites.pages[tab["tab_url"]] = (200, make_tab_page_html(tab, [], content=sheet("take two", LINES)))
    upsert_rows(conn, [(301, "radiohead", song, "chords", tab["tab_url"].removeprefix(TAB))], "1", NOW)
    mark_built(conn, NOW)

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title=f"{PINKPOP} two")

    two = next(s for s in list_songs(conn) if s.title.endswith("take two"))
    assert song_dir(cfg.library_dir, two) == song_dir(cfg.library_dir, one) and two.id != one.id
    assert result.ok and progress.states()["sheet"] == "failed"  # no bug: it waits, as after a site's error
    assert "sheet.txt isn't kept: its folder is" in result.details["sheet"]
    assert (song_dir(cfg.library_dir, one) / "sheet.txt").read_bytes() == b"take one"


# --- the other sites -------------------------------------------------------------------------------------


def test_a_spanish_song_ug_has_no_sheet_for_gets_lacuerdas_at_once(cfg, conn, sites):
    sites.pages["https://acordes.lacuerda.net/soda_stereo/"] = (200, (LACUERDA / "artist.html").read_text("utf-8"))
    sites.pages["https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-3.shtml"] = (
        200, (LACUERDA / "version.html").read_text("utf-8"))
    upsert_rows(conn, [(7, "oasis", "wonderwall", "chords", "oasis/wonderwall-chords-7")], "1", NOW)
    mark_built(conn, NOW)

    result, progress = look_up(cfg, sites=sites, artist="Soda Stereo", title="De Música Ligera")

    readable = next(e for e in progress.events if e[0] == "readable")
    assert progress.events.index(readable) < progress.events.index(("stage", "lyrics", "running"))
    assert (folder(cfg, "Soda Stereo", "De Música Ligera") / "sheet.txt").is_file()
    assert progress.states()["lacuerda"] in ("done", "skipped")


LC = "https://acordes.lacuerda.net/"
CAMARON_2 = LC + "estopa/como_camaron-2.shtml"


def serve_como_camaron(sites: Sites, conn) -> None:
    """Estopa's Como Camarón: on Ultimate Guitar, whose sheets chart the whole song, and LaCuerda's version 2."""
    tabs = [creep_tab(201, rating=4.9, artist="Estopa", song="Como Camaron"),
            creep_tab(202, rating=4.5, artist="Estopa", song="Como Camaron")]
    for tab in tabs:
        others = [t for t in tabs if t is not tab]
        sites.pages[tab["tab_url"]] = (200, make_tab_page_html(tab, others, content=sheet(f"sheet {tab['id']}", LINES)))
    upsert_rows(conn, [(t["id"], "estopa", "como-camaron", "chords", t["tab_url"].removeprefix(TAB)) for t in tabs],
                "1", NOW)
    mark_built(conn, NOW)
    sites.lyrics[("Estopa", "Como Camarón")] = "\n".join(LINES)
    sites.pages[CAMARON_2] = (200, (LACUERDA / "version.html").read_text("utf-8"))


def test_the_lacuerda_sheet_you_pick_is_the_sheet_first_and_stays(cfg, conn, sites):
    from caracole.overrides import LaCuerdaPick

    serve_como_camaron(sites, conn)

    result, progress = look_up(cfg, sites=sites, artist="Estopa", title="Como Camarón", lacuerda=CAMARON_2)

    # The version you picked, before Ultimate Guitar is asked anything: its page alone.
    readable = next(e for e in progress.events if e[0] == "readable")
    assert sites.requests[0] == CAMARON_2 and progress.events.index(readable) < progress.events.index(
        ("stage", "lyrics", "running"))
    here = folder(cfg, "Estopa", "Como Camarón")
    assert (here / "sheet.txt").read_text(encoding="utf-8").startswith("Intro:")
    assert load_overrides(cfg.overrides_file).lacuerda == {"estopa/como-camaron": LaCuerdaPick("estopa", "como_camaron", 2)}
    assert "[lacuerda]" in result.details["song"] and "LaCuerda" in result.details["sheet"]
    # Ultimate Guitar's sheets, which chart the lyrics better, replace nothing: the pick stays.
    assert progress.states()["ug"] == "done" and len(sites.ug()) >= 1
    assert (here / "sheet.txt").read_text(encoding="utf-8").startswith("Intro:")
    assert progress.states()["lacuerda"] == "skipped"  # asked already, for the sheet
    assert find_song(conn, "estopa/como-camaron").status == "found" and result.ok


def test_a_lacuerda_pick_lacuerda_cant_answer_now_leaves_the_sheet_to_ultimate_guitar(cfg, conn, sites):
    serve_como_camaron(sites, conn)
    record_block(conn, "lacuerda", datetime.now(UTC), "HTTP 403")

    result, progress = look_up(cfg, sites=sites, artist="Estopa", title="Como Camarón", lacuerda=CAMARON_2)

    assert CAMARON_2 not in sites.requests
    assert "sheet 20" in (folder(cfg, "Estopa", "Como Camarón") / "sheet.txt").read_text(encoding="utf-8")
    song = find_song(conn, "estopa/como-camaron")
    assert song.lacuerda_checked_at is None  # an error is never a miss: the nightly run asks for the pick
    assert "estopa/como-camaron" in load_overrides(cfg.overrides_file).lacuerda and result.ok
    assert result.details["sheet"].startswith("LaCuerda is cooling down after a block")  # said where it's looked for


def test_a_lacuerda_pick_that_fails_says_so_where_the_sheet_ultimate_guitar_gave_is_said(cfg, conn, sites):
    serve_como_camaron(sites, conn)
    sites.pages[CAMARON_2] = (500, "<html>down</html>")

    result, progress = look_up(cfg, sites=sites, artist="Estopa", title="Como Camarón", lacuerda=CAMARON_2)

    assert CAMARON_2 in sites.requests
    sheet_said = result.details["sheet"]
    assert sheet_said.startswith("LaCuerda failed (") and sheet_said.endswith("tab 201 from Ultimate Guitar")
    assert progress.states()["lacuerda"] == "failed" and "LaCuerda failed (" in result.details["lacuerda"]
    assert find_song(conn, "estopa/como-camaron").lacuerda_checked_at is None and result.ok  # no miss


def test_a_gtptabs_error_says_what_the_site_did_as_the_lyrics_stage_does(cfg, conn, sites):
    serve_creep(sites, conn)
    radiohead = "tabs/18/radiohead.html"
    conn.execute("INSERT INTO gtptabs_index VALUES (?, ?, 'radiohead', '', '', 'sitemapGoogle1.xml')",
                 (radiohead, radiohead))
    sites.pages[f"https://gtptabs.com/{radiohead}"] = (502, "<html>Bad gateway</html>")

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert f"https://gtptabs.com/{radiohead}" in sites.requests
    assert progress.states()["gtptabs"] == "failed"
    assert result.details["gtptabs"].startswith("gtptabs.com failed (gtptabs: 502")
    assert "502" in get_state(conn, "gtptabs").last_error and result.ok  # an error, as at night: never a miss
    assert get_song(conn, find_song(conn, "radiohead/creep").id).status == "found"


def test_the_sheet_stage_says_which_site_it_asks_once_lacuerda_is_one(cfg, conn, sites):
    # caracole serve's line follows it (status.py): LaCuerda, for the pick, then Ultimate Guitar, which LaCuerda's
    # failure leaves the sheet to. A sheet Ultimate Guitar alone is asked for says nothing more.
    from caracole.get import SHEET_FROM

    serve_como_camaron(sites, conn)
    sites.pages[CAMARON_2] = (500, "<html>down</html>")

    result, progress = look_up(cfg, sites=sites, artist="Estopa", title="Como Camarón", lacuerda=CAMARON_2)

    running = [detail for name, state, detail in progress.said if name == "sheet" and state == "running"]
    assert running == ["", SHEET_FROM["lacuerda"], SHEET_FROM["ug"]] and result.ok
    serve_creep(sites, conn)
    _, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")
    assert [detail for name, state, detail in progress.said if name == "sheet" and state == "running"] == [""]


def test_a_tab_you_pinned_on_ultimate_guitar_is_said_to_be_kept_over_a_lacuerda_pick(cfg, conn, sites):
    serve_como_camaron(sites, conn)
    look_up(cfg, sites=sites, artist="Estopa", title="Como Camarón", tab=f"{TAB}estopa/como-camaron-chords-202")
    sites.requests.clear()

    result, progress = look_up(cfg, sites=sites, artist="Estopa", title="Como Camarón", lacuerda=CAMARON_2)

    assert CAMARON_2 not in sites.requests  # the pin wins: LaCuerda is asked nothing
    assert "sheet 202" in (folder(cfg, "Estopa", "Como Camarón") / "sheet.txt").read_text(encoding="utf-8")
    said = "the Ultimate Guitar tab you pinned is kept over your LaCuerda pick"
    assert result.details["sheet"].startswith(said) and said in result.details["lacuerda"]
    assert "this month" not in result.details["lacuerda"]


def test_a_new_pick_is_asked_for_at_once_however_lately_lacuerda_answered_for_the_song(cfg, conn, sites):
    from caracole.songs import update_song

    from conftest import add_song

    serve_como_camaron(sites, conn)
    song = add_song(conn, "Estopa", "Como Camarón")
    update_song(conn, song.id, lacuerda_checked_at="2026-10-19T03:00:00Z")  # a miss last night

    look_up(cfg, sites=sites, artist="Estopa", title="Como Camarón", lacuerda=CAMARON_2)

    assert CAMARON_2 in sites.requests
    assert (folder(cfg, "Estopa", "Como Camarón") / "sheet.txt").read_text(encoding="utf-8").startswith("Intro:")


def test_an_existing_song_is_looked_up_without_a_new_line_in_wanted_txt(cfg, conn, sites):
    from conftest import add_song

    serve_creep(sites, conn)
    add_song(conn, "Radiohead", "Creep", source="spotify", source_id="spotify:track:1")

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert not cfg.wanted_file.exists()
    assert [s.display for s in list_songs(conn)] == ["Radiohead - Creep"]
    assert get_song(conn, find_song(conn, "radiohead/creep").id).status == "found"


def test_a_song_ignored_in_overrides_toml_is_not_looked_up(cfg, conn, sites):
    serve_creep(sites, conn)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text('[ignore]\nsongs = ["Radiohead - Creep"]\n', encoding="utf-8")

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert sites.requests == [] and progress.states()["song"] == "failed"
    assert "ignore" in result.details["song"]


def test_the_lookup_is_noted_for_a_nightly_run_it_went_before(cfg, conn, sites):
    from caracole.db import kv_get_json

    serve_creep(sites, conn)
    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")
    assert kv_get_json(conn, "lookup:songs") == [find_song(conn, "radiohead/creep").id]


def test_progress_lines_are_json_a_server_can_read():
    from caracole.get import PROGRESS_PREFIX, progress_line, read_progress_line

    line = progress_line({"stage": "sheet", "state": "done", "detail": "tab 101"})
    assert line.startswith(PROGRESS_PREFIX)
    assert read_progress_line(line) == {"stage": "sheet", "state": "done", "detail": "tab 101"}
    assert read_progress_line("Sheet: Radiohead/Creep/sheet.txt") is None
    assert read_progress_line(PROGRESS_PREFIX + "{not json") is None
    assert json.loads(line[len(PROGRESS_PREFIX):]) == {"stage": "sheet", "state": "done", "detail": "tab 101"}


def test_a_song_you_removed_is_asked_for_again_by_a_lookup(cfg, conn, sites):
    # caracole remove left its tombstone; `caracole get` writes its wanted.txt line, which always asks again.
    from caracole.removal import plan_removal, remove_song

    serve_creep(sites, conn)
    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")
    remove_song(conn, cfg, plan_removal(conn, cfg, find_song(conn, "radiohead/creep")))
    assert find_song(conn, "radiohead/creep") is None and "Creep" not in cfg.wanted_file.read_text(encoding="utf-8")

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert progress.states()["song"] == "done" and result.sheet is not None
    assert find_song(conn, "radiohead/creep") is not None
    assert "Radiohead - Creep" in cfg.wanted_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("how", ["cooldown", "block", "error"])
def test_a_clean_song_whose_lookup_ug_cut_short_is_owed_a_fetch_by_the_nightly_run(cfg, conn, sites, how):
    # A card's Fetch now on a song fetched before (clean: nothing new to fetch at night). A cooldown, a block
    # or an error leaves it to the nightly run, as `caracole fetch --song` does: marked to fetch, so the
    # card's "Not fetched yet" waits for something.
    from caracole.songs import update_song

    from conftest import add_song

    serve_creep(sites, conn)
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_step="exact", match_artist_key="radiohead",
                match_song_key="creep", ug_dirty=False, ug_checked_at="2026-10-01T00:00:00Z")
    if how == "cooldown":
        record_block(conn, "ug", datetime.now(UTC), "HTTP 403")
    for url in [u for u in sites.pages if "ultimate-guitar.com" in u]:
        sites.pages[url] = (403, "Forbidden") if how == "block" else (500, "Oops") if how == "error" else sites.pages[url]

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert progress.states()["sheet"] in ("skipped", "failed")
    assert get_song(conn, creep.id).ug_dirty is True


# --- a song a search found on an artist page ------------------------------------------------------


def serve_song_dongye(sites: Sites, conn, cfg) -> None:
    """宋冬野 on UG, listed only by bare ids: their artist page (pasted under [artist_url]), its chords and tabs
    lists, and the sheets of 斑马斑马 and 董小姐; LRCLIB's lyrics of both. The index has another artist."""
    from helpers.ug_pages import (BANMA_TRADITIONAL_LINES, BANMA_UG, DONG_XIAOJIE_LINES, SONG_DONGYE_URL,
                                  song_dongye_chords, song_dongye_page_html, song_dongye_sheet, song_dongye_tab)

    from caracole.ug.artist import artist_page_url

    sites.pages[artist_page_url(SONG_DONGYE_URL, kind="chords")] = (200, song_dongye_page_html(song_dongye_chords(
        t4180894=(4.8, 120), t4689017=(4.6, 40), t3016223=(4.7, 90), t3204647=(4.1, 9))))
    sites.pages[artist_page_url(SONG_DONGYE_URL, kind="tabs")] = (200, song_dongye_page_html(
        [song_dongye_tab(5000001, "安和桥 Anhe Bridge", type="Tabs")]))
    for tab_id, title, lines in ((4180894, BANMA_UG, BANMA_TRADITIONAL_LINES), (4689017, BANMA_UG, BANMA_TRADITIONAL_LINES),
                                 (3016223, "董小姐", DONG_XIAOJIE_LINES), (3204647, "董小姐", DONG_XIAOJIE_LINES)):
        sites.pages[f"{TAB}{tab_id}"] = (200, make_tab_page_html(song_dongye_tab(tab_id, title), [],
                                                                 content=song_dongye_sheet(lines),
                                                                 artist_url=SONG_DONGYE_URL))
    sites.lyrics[("宋冬野", "斑马斑马")] = "\n".join(BANMA_TRADITIONAL_LINES)
    sites.lyrics[("宋冬野", "董小姐")] = "\n".join(DONG_XIAOJIE_LINES)
    upsert_rows(conn, [(1, "radiohead", "creep", "chords", "radiohead/creep-chords-1")], "1", NOW)
    mark_built(conn, NOW)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[artist_url]\n"宋冬野" = "{SONG_DONGYE_URL}"\n', encoding="utf-8")


def test_a_song_a_search_found_on_an_artist_page_is_looked_up_there_from_the_learned_address(cfg, conn, sites):
    from caracole.search import find_index

    serve_song_dongye(sites, conn, cfg)
    look_up(cfg, sites=sites, artist="宋冬野", title="斑马斑马")
    cfg.overrides_file.write_text("", encoding="utf-8")  # the page is known now only as caracole learned it

    hit = find_index(conn, "董小姐").songs[0]
    assert (hit.artist, hit.title, hit.url) == ("宋冬野", "董小姐", f"{TAB}3016223")
    before = len(sites.ug())
    result, progress = look_up(cfg, sites=sites, artist=hit.artist, title=hit.title)

    song = find_song(conn, "宋冬野/董小姐")
    assert (song.status, song.match_step) == ("found", "artist_page") and result.sheet is not None
    # The artist page's lists come from the cache, and no tab page is read to learn where the page is.
    assert sites.ug()[before:] and set(sites.ug()[before:]) <= {f"{TAB}3016223", f"{TAB}3204647"}


def test_a_lookup_fills_the_artist_pages_tabs_from_the_cache_once_with_no_request(cfg, conn, sites):
    # A database from before those tabs were kept: the cache holds the lists, and any lookup reads them.
    from caracole.db import kv_delete
    from caracole.search import find_index
    from caracole.ug.artist_tabs import BACKFILL_KEY

    serve_song_dongye(sites, conn, cfg)
    look_up(cfg, sites=sites, artist="宋冬野", title="斑马斑马")
    conn.execute("DELETE FROM ug_artist_tabs")
    kv_delete(conn, BACKFILL_KEY)
    record_block(conn, "ug", NOW, "HTTP 429")  # even while Ultimate Guitar cools down
    before = len(sites.ug())

    look_up(cfg, sites=sites, artist="Nobody", title="Nothing")

    assert sites.ug()[before:] == []
    assert find_index(conn, "董小姐").songs[0].url == f"{TAB}3016223"


# --- the songbooks the song is in -------------------------------------------------------------------


def _books(cfg, **books):
    from caracole.songbook import make_songbook, songbooks_file

    for name, songs in books.items():
        make_songbook(songbooks_file(cfg.library_dir), name, songs)


def test_a_song_fetched_now_remakes_the_songbooks_it_is_in_and_no_other(cfg, conn, sites):
    from conftest import add_song

    serve_creep(sites, conn)
    add_song(conn, "Soda Stereo", "De Música Ligera")
    _books(cfg, Campfire=["Radiohead - Creep"], Other=["Soda Stereo - De Música Ligera"])

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert result.ok
    assert (cfg.library_dir / "_songbooks" / "Campfire" / "songbook.html").is_file()
    assert not (cfg.library_dir / "_songbooks" / "Other").exists()
    assert ("songbooks", "running", "Campfire") in progress.said  # caracole serve's "Remaking songbook Campfire…"
    assert ("songbooks", "done", "Campfire made again") in progress.said


def test_the_library_page_is_written_after_the_songbooks_a_lookup_made_again(cfg, conn, sites):
    import re

    serve_creep(sites, conn)
    _books(cfg, Campfire=["Radiohead - Creep"])

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    # index.html shows the songbook as it is now: made, with its files to open, not "not made yet".
    page = (cfg.library_dir / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="songs">(.*?)</script>', page, re.S).group(1))
    book = next(b for b in data["songbooks"]["books"] if b["name"] == "Campfire")
    assert "songbook.html" in {f["name"] for f in book["files"]}, book
    assert book["changed"] is not None and book["missing"] == 0, book


def test_a_lookup_told_to_leave_the_songbooks_remakes_none(cfg, conn, sites):
    serve_creep(sites, conn)
    _books(cfg, Campfire=["Radiohead - Creep"])

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep", songbooks=False)

    assert result.ok
    assert not (cfg.library_dir / "_songbooks").exists()
    assert not [s for s in progress.said if s[0] == "songbooks" and s[1] == "running" and s[2]]  # no names: none made
    assert any(s[0] == "songbooks" and s[1] == "skipped" for s in progress.said)


def test_a_song_in_no_songbook_remakes_none(cfg, conn, sites):
    serve_creep(sites, conn)
    _books(cfg, Other=["Soda Stereo - De Música Ligera"])

    _, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert ("songbooks", "skipped", "no songbook lists it") in progress.said
    assert not (cfg.library_dir / "_songbooks").exists()


def test_a_broken_songbooks_file_is_said_and_stops_nothing(cfg, conn, sites):
    serve_creep(sites, conn)
    path = cfg.library_dir / "songbooks.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[[songbook\nbroken", encoding="utf-8")

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert result.ok and result.refused is None
    assert (folder(cfg, "Radiohead", "Creep") / "sheet.pdf").is_file()
    state, detail = next((s, d) for n, s, d in progress.said if n == "songbooks" and s != "running")
    assert state == "skipped" and "songbooks.toml can't be read" in detail


def test_a_songbook_that_cant_be_made_is_said_and_the_lookups_sheet_stands(cfg, conn, sites):
    serve_creep(sites, conn)
    _books(cfg, Campfire=["Radiohead - Creep"])

    from helpers.songbooks import FakeChordPro

    # chordpro fails in the songbook's folder alone (its input holds Creep's sheet); the song's own PDF is made
    songbook_fails, other = FakeChordPro(fail=("Creep",)), FakeRunner()
    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep",
                               runner=lambda cmd, **kw: (songbook_fails if "/songbook-" in " ".join(cmd) else other)(
                                   cmd, **kw))

    state, detail = next((s, d) for n, s, d in progress.said if n == "songbooks" and s != "running")
    assert state == "failed" and "Campfire" in detail
    assert result.ok and progress.states()["pdf"] == "done"  # the song's own sheet and PDF are the lookup's
    assert (folder(cfg, "Radiohead", "Creep") / "sheet.pdf").is_file()


def test_a_songbook_waiting_for_a_font_is_skipped_and_the_lookup_goes_on(cfg, conn, sites):
    from helpers.rendered import rendered_song

    assert cfg.cjk_font is None
    serve_creep(sites, conn)
    rendered_song(conn, cfg, "宋冬野", "斑马斑马", content=ZH_SHEET)
    _books(cfg, Campfire=["Radiohead - Creep", "宋冬野 - 斑马斑马"])

    result, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    state, detail = next((s, d) for n, s, d in progress.said if n == "songbooks" and s != "running")
    assert state == "skipped" and "songbook PDF of Campfire" in detail
    assert result.ok


def test_a_second_identical_lookup_finds_the_songbook_up_to_date(cfg, conn, sites):
    serve_creep(sites, conn)
    _books(cfg, Campfire=["Radiohead - Creep"])
    look_up(cfg, sites=sites, artist="Radiohead", title="Creep")
    html = cfg.library_dir / "_songbooks" / "Campfire" / "songbook.html"
    before = (html.read_bytes(), html.stat().st_mtime_ns)

    _, progress = look_up(cfg, sites=sites, artist="Radiohead", title="Creep")

    assert ("songbooks", "done", "Campfire up to date") in progress.said
    assert (html.read_bytes(), html.stat().st_mtime_ns) == before
