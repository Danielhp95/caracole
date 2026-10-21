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
        self.readable_after: int | None = None

    def stage(self, name, state, detail=""):
        self.events.append(("stage", name, state))

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
    """chordpro: writes a dummy PDF where it is told to."""

    def __init__(self):
        self.calls = 0

    def __call__(self, cmd, **kwargs):
        self.calls += 1
        out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output="))
        Path(out).write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def look_up(cfg, *, sites=None, **request):
    from caracole.get import LookupRequest, look_up as run

    progress = Progress(sites)
    result = run(cfg, LookupRequest(**request), progress, runner=FakeRunner(), now=NOW)
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
    assert order == ["song", "match", "sheet", "pdf", "lyrics", "ug", "lacuerda", "gtptabs", "pages"]
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
    # You pinned a chords sheet, then pick a Guitar Pro version: the sheet you chose stays yours.
    from caracole.overrides import add_pin

    serve_creep(sites, conn)
    upsert_rows(conn, [(301, "radiohead", "creep", "guitar-pro", "radiohead/creep-guitar-pro-301")], "1", NOW)
    add_pin(cfg.overrides_file, "Radiohead - Creep", [f"{TAB}radiohead/creep-chords-102"])

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep", tab=f"{TAB}radiohead/creep-guitar-pro-301")
    assert sorted(load_overrides(cfg.overrides_file).pin["radiohead/creep"]) == [102, 301]

    look_up(cfg, sites=sites, artist="Radiohead", title="Creep", tab=f"{TAB}radiohead/creep-chords-103")
    assert sorted(load_overrides(cfg.overrides_file).pin["radiohead/creep"]) == [103, 301]  # chords for chords


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
