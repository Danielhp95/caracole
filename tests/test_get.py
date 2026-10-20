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


def test_a_song_the_matcher_isnt_sure_of_says_so_and_still_gets_its_lyrics(cfg, conn, sites):
    two_creeps(sites, conn)
    sites.lyrics[("Somebody", "Creep")] = "\n".join(LINES)

    result, progress = look_up(cfg, sites=sites, artist="Somebody", title="Creep")

    assert find_song(conn, "somebody/creep").match_decision == "review"
    assert progress.states()["sheet"] == "skipped" and "pick" in result.details["sheet"]
    assert sites.ug() == [] and progress.states()["lyrics"] == "done"


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
