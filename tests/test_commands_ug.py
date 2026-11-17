"""``caracole ug --link``, run through the CLI: a UG page pasted into the library page's search box, read now.

Ultimate Guitar is ``FakeUG`` (helpers/ug_pages.py: 宋冬野's pages as UG answered them on 2026-10-19), handed to the
client through ``caracole.commands._common.transport_for``, so no request can reach the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from helpers.ug_pages import (
    BANMA_UG,
    SONG_DONGYE_CHORDS_URL,
    SONG_DONGYE_TABS_URL,
    SONG_DONGYE_URL,
    FakeUG,
    make_tab_page_html,
    song_dongye_tab,
    version_dict,
)
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.get import read_progress_line
from caracole.health import is_cooling
from caracole.http import robots_disallows

TAB = "https://tabs.ultimate-guitar.com/tab/"
FOUND = f"{TAB}4180894"  # the page the owner found on UG
READ = "Read: 斑马 斑马 Banma Banma Zebra Zebra by Song Dongye (宋冬野), chords; their page lists 8 tabs."


class Sites:
    def __init__(self):
        self.ug = FakeUG()

    def transport(self, provider: str) -> httpx.BaseTransport:
        if provider != "ug":
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(self.ug.handler)


@pytest.fixture
def sites(monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    return s


def run(tmp_path: Path, *args: str, lookup_requests: int = 6):
    (tmp_path / "caracole.toml").write_text("\n".join([
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
        "[providers.ug]",
        "lookup_delay = [0, 0]",
        f"lookup_requests = {lookup_requests}",
    ]) + "\n", encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(tmp_path / "caracole.toml"), "ug", *args])


def database(tmp_path: Path):
    return db.connect(tmp_path / "state" / "caracole.sqlite")


def served(result) -> str:
    """What caracole serve's request line says of a read that printed this (web/status.py reads its last word)."""
    from caracole.web.jobs import UG_LINK, Job, Step
    from caracole.web.status import job_line

    step = Step("Reading the page on Ultimate Guitar", ("ug", "--link=x"), state="done",
                output=result.output.splitlines())
    return job_line(Job(1, "Read", UG_LINK + "x", [step], state="done"), None).text


def polite(requests: list[str]) -> bool:
    """Every request open in robots.txt: no search.php, no download or print page."""
    return all(robots_disallows(u) is None and "search.php" not in u for u in requests)


def test_a_tab_link_reads_its_page_then_its_artists_lists_at_the_lookup_pace(tmp_path, sites):
    result = run(tmp_path, "--link", FOUND)

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == READ
    assert served(result) == "Read: 斑马 斑马 Banma Banma Zebra Zebra by Song Dongye."
    assert sites.ug.requests == [FOUND, SONG_DONGYE_CHORDS_URL, SONG_DONGYE_TABS_URL] and polite(sites.ug.requests)
    conn = database(tmp_path)
    try:
        assert {r[0].split(":", 1)[0] for r in conn.execute("SELECT run FROM events WHERE provider = 'ug'")} == {"lookup"}
        # The artist page learned as the fetch learns it, under UG's names for the artist, and its lists kept.
        assert conn.execute("SELECT value FROM kv WHERE key = 'ug:artist_url:宋冬野'").fetchone()[0] == SONG_DONGYE_URL
        assert conn.execute("SELECT COUNT(*) FROM ug_artist_tabs WHERE page = ?", (SONG_DONGYE_URL,)).fetchone()[0] == 8
        assert conn.execute("SELECT title FROM ug_artist_tabs WHERE tab_id = 4180894").fetchone()[0] == BANMA_UG
    finally:
        conn.close()
    again = run(tmp_path, "--link", f"{FOUND}?ref=share")  # known now: nothing asked
    assert again.stdout.splitlines()[-1] == READ and len(sites.ug.requests) == 3


def test_its_progress_is_a_json_line_a_stage(tmp_path, sites):
    result = run(tmp_path, "--link", FOUND, "--progress")

    assert result.exit_code == 0, result.output
    events = [e for line in result.stdout.splitlines() if (e := read_progress_line(line))]
    assert [(e["stage"], e["state"]) for e in events] == [
        ("tab", "running"), ("tab", "running"), ("tab", "done"), ("artist", "running"), ("artist", "done")]
    assert events[2]["detail"] == "斑马 斑马 Banma Banma Zebra Zebra by Song Dongye (宋冬野), chords"
    assert events[-1]["detail"] == READ and result.stdout.splitlines()[-1] == READ


def test_an_artist_link_reads_their_lists_alone(tmp_path, sites):
    result = run(tmp_path, "--link", f"{SONG_DONGYE_URL}?filter=chords", "--progress")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == "Read: UG's page of Song Dongye (宋冬野) lists 8 tabs."
    assert sites.ug.requests == [SONG_DONGYE_CHORDS_URL, SONG_DONGYE_TABS_URL]
    events = [e for line in result.stdout.splitlines() if (e := read_progress_line(line))]
    assert {e["stage"] for e in events} == {"artist"}


def test_a_page_gone_is_not_found_and_asked_for_no_more(tmp_path, sites):
    result = run(tmp_path, "--link", f"{TAB}999")
    assert result.exit_code == 0 and result.stdout == f"Not found: UG answers 404 for {TAB}999.\n"
    assert served(result) == f"Not found: UG answers 404 for {TAB}999."
    again = run(tmp_path, "--link", f"{TAB}999")
    assert again.stdout == result.stdout and sites.ug.requests == [f"{TAB}999"]
    gone = run(tmp_path, "--link", f"{SONG_DONGYE_URL[:-6]}1")  # an artist page: its lists, then the page itself
    assert gone.stdout.splitlines()[-1] == f"Not found: UG answers 404 for {SONG_DONGYE_URL[:-6]}1."


def test_a_tab_of_a_type_caracole_keeps_nothing_of_is_said_and_its_artist_page_never_read(tmp_path, sites):
    slugged = run(tmp_path, "--link", f"{TAB}metallica/one-guitar-pro-225441")
    assert slugged.exit_code == 0 and sites.ug.requests == []  # its slug says it: nothing asked
    assert slugged.stdout == (f"Not read: {TAB}metallica/one-guitar-pro-225441: it is a Guitar Pro file: caracole "
                              "keeps UG's chords, tabs and ukulele chords alone.\n")
    pro = version_dict(7001, type="Pro", song="One", artist="Metallica", artist_url=f"{SONG_DONGYE_URL}")
    sites.ug.pages[f"{TAB}7001"] = make_tab_page_html(pro, [], meta={"fileExtension": ".gp5"})
    bare = run(tmp_path, "--link", f"{TAB}7001")
    assert bare.stdout == ("Read: One by Metallica is a Guitar Pro file: caracole keeps UG's chords, tabs and ukulele "
                           "chords alone.\n")
    assert sites.ug.requests == [f"{TAB}7001"]


def test_a_tab_that_links_to_no_artist_page_is_read_alone(tmp_path, sites):
    tab = song_dongye_tab(7002, "新歌 New Song")
    del tab["artist_url"]
    sites.ug.pages[f"{TAB}7002"] = make_tab_page_html(tab, [], content="[ch]C[/ch]")
    result = run(tmp_path, "--link", f"{TAB}7002")
    assert result.stdout == "Read: 新歌 New Song by Song Dongye (宋冬野), chords; it links to no artist page.\n"
    assert sites.ug.requests == [f"{TAB}7002"]


def test_a_block_cools_ug_down_and_the_next_read_waits(tmp_path, sites):
    sites.ug.status[FOUND] = 403
    result = run(tmp_path, "--link", FOUND)
    assert result.exit_code == 0 and result.stdout.startswith("Not read: UG turned us back (")
    assert served(result) == "Not read: UG turned us back."
    conn = database(tmp_path)
    try:
        from caracole.commands._common import utcnow

        assert is_cooling(conn, "ug", utcnow())
    finally:
        conn.close()
    again = run(tmp_path, "--link", FOUND)
    assert again.stdout.startswith("Not read: waiting out UG until ") and sites.ug.requests == [FOUND]


def test_an_error_is_remembered_an_hour_and_read_again_by_hand(tmp_path, sites):
    sites.ug.status[FOUND] = 500
    result = run(tmp_path, "--link", FOUND)
    assert result.exit_code == 0 and result.stdout.startswith("Not read: UG failed (")
    conn = database(tmp_path)
    try:
        failed = json.loads(conn.execute("SELECT value FROM kv WHERE key = 'ug:link-failed'").fetchone()[0])
        assert list(failed) == [FOUND]
    finally:
        conn.close()
    del sites.ug.status[FOUND]
    again = run(tmp_path, "--link", FOUND)  # by hand (Try again): read, and its failure forgotten
    assert again.stdout.splitlines()[-1] == READ
    conn = database(tmp_path)
    try:
        assert json.loads(conn.execute("SELECT value FROM kv WHERE key = 'ug:link-failed'").fetchone()[0]) == {}
    finally:
        conn.close()


def test_a_budget_spent_after_the_tab_page_leaves_its_artists_page_for_later(tmp_path, sites):
    result = run(tmp_path, "--link", FOUND, lookup_requests=1)
    assert result.exit_code == 0, result.output
    assert result.stdout == ("Read: 斑马 斑马 Banma Banma Zebra Zebra by Song Dongye (宋冬野), chords; their page waits "
                             "for the next lookup (its asks of UG are spent).\n")
    assert sites.ug.requests == [FOUND]


def test_the_hours_lookups_spent_asks_nothing(tmp_path, sites):
    result = run(tmp_path, "--link", FOUND, lookup_requests=0)
    assert result.exit_code == 0
    assert result.stdout == "Not read: no more asks of UG this hour (60 spent). Ask again later.\n"
    assert sites.ug.requests == []


def test_a_text_that_is_no_ug_link_exits_2_and_asks_nothing(tmp_path, sites):
    result = run(tmp_path, "--link", "https://www.ultimate-guitar.com/explore")
    assert result.exit_code == 2 and sites.ug.requests == []
