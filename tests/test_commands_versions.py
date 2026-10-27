"""``caracole versions``, run through the CLI: list a song's Ultimate Guitar chords versions, keep one
beside the sheet, choose one, clear the choice.

The sites are test_get.py's ``Sites`` behind ``caracole.commands._common.transport_for``; chordpro
is test_commands_get.py's fake script.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from helpers.ug_pages import make_tab_page_html, version_dict
from test_commands_get import FAKE_CHORDPRO, OUTSIDE_SETTINGS, get
from test_get import LINES, NOW, TAB, Sites, creep_tab, sheet
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.library import keep_file
from caracole.overrides import load_overrides
from caracole.sheet_versions import kept_by_you, unkeepable
from caracole.songs import find_song
from caracole.ug.index import mark_built, upsert_rows
from caracole.versions import upsert_version
from conftest import add_song, subprocess_pythonpath

CREEP = "Radiohead - Creep"


def write_config(tmp_path: Path, ug: str = "") -> Path:
    chordpro = tmp_path / "bin" / "chordpro"
    if not chordpro.exists():
        chordpro.parent.mkdir(exist_ok=True)
        chordpro.write_text(FAKE_CHORDPRO.format(python=sys.executable), encoding="utf-8")
        chordpro.chmod(0o755)
    providers = "".join(f"[providers.{p}]\ndelay = [0, 0]\nlookup_delay = [0, 0]\n{ug if p == 'ug' else ''}"
                        for p in ("ug", "lrclib", "lacuerda", "gtptabs", "musescore"))
    path = tmp_path / "caracole.toml"
    path.write_text(f'data_dir = "{tmp_path}"\nchordpro_bin = "{chordpro}"\n{providers}', encoding="utf-8")
    return path


@pytest.fixture
def config(tmp_path) -> Path:
    return write_config(tmp_path)


@pytest.fixture
def sites(monkeypatch) -> Sites:
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", lambda provider: httpx.MockTransport(s.handler))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return s


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "state" / "caracole.sqlite")
    yield c
    c.close()


def versions(config, *args):
    return CliRunner().invoke(build_app(), ["--config", str(config), "versions", *args])


def url(tab_id: int) -> str:
    return f"{TAB}radiohead/creep-chords-{tab_id}"


def serve_four(sites, conn, more: int = 0) -> None:
    """Creep's four chords versions: 101 the best rated, a verse alone; 102, 103 and 104 the song. ``more`` adds
    that many after them (105, 106, ...), the song too, each rated below the one before."""
    tabs = [creep_tab(101, rating=4.9, votes=100), creep_tab(102, rating=4.6), creep_tab(103, rating=4.2),
            creep_tab(104, rating=3.5, votes=20)]
    tabs += [creep_tab(105 + n, rating=round(3.4 - n / 10, 1), votes=20) for n in range(more)]
    texts = {101: LINES[:2]} | {t["id"]: LINES for t in tabs[1:]}
    for tab in tabs:
        others = [t for t in tabs if t is not tab]
        sites.pages[tab["tab_url"]] = (200, make_tab_page_html(tab, others, content=sheet(f"sheet {tab['id']}",
                                                                                            texts[tab["id"]])))
    upsert_rows(conn, [(t["id"], "radiohead", "creep", "chords", t["tab_url"].removeprefix(TAB)) for t in tabs],
                "1", NOW)
    mark_built(conn, NOW)
    sites.lyrics[("Radiohead", "Creep")] = "\n".join(LINES)


def folder(tmp_path) -> Path:
    return tmp_path / "library" / "Radiohead" / "Creep"


def version_files(tmp_path) -> list[str]:
    return sorted(p.name for p in folder(tmp_path).glob("version-*.txt"))


def looked_up(config, sites, conn, tmp_path, more: int = 0):
    serve_four(sites, conn, more)
    result = get(config, CREEP)
    assert result.exit_code == 0, result.output
    assert "sheet 102" in (folder(tmp_path) / "sheet.txt").read_text()
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt"]
    sites.requests.clear()
    return result


# --- the list -------------------------------------------------------------------------------------


def wonderwall(conn, tmp_path):
    song = add_song(conn, "Oasis", "Wonderwall")

    def chords(tab, rating, votes, number, raw=None):
        return upsert_version(conn, provider="ug", tab_id=tab, song_id=song.id, slot="sheet", kind="chords",
                              rating=rating, votes=votes, version=number, label=None,
                              url=f"{TAB}oasis/wonderwall-chords-{tab}", raw=raw or {}, now="2026-10-20T00:00:00Z")

    one = chords("1064463", 4.86, 408, 3, {"version_description": "the version that oasis play\non Wembley 2008"})
    other = chords("39144", 4.85, 12629, 1)
    chords("555", 4.5, 30, 2)
    lib = tmp_path / "library"
    keep_file(conn, lib, song=song, version_id=one, name="sheet.txt", data=b"one", rank=1)
    keep_file(conn, lib, song=song, version_id=other, name="version-39144.txt", data=b"other", rank=2)
    return song


def test_versions_lists_every_version_in_rank_order(config, conn, tmp_path):
    wonderwall(conn, tmp_path)

    result = versions(config, "Oasis - Wonderwall")

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == ("Oasis - Wonderwall: 3 chords versions on Ultimate Guitar; "
                        "the title opens tab 1064463, caracole's pick.")
    assert lines[1:4] == [
        "  Ver 3 of 3 · 4.86★ (408) · tab 1064463 · kept · the one · the version that oasis play on Wembley 2008",
        "  Ver 1 of 3 · 4.85★ (12,629) · tab 39144 · kept",
        "  Ver 2 of 3 · 4.50★ (30) · tab 555",
    ]
    assert '--keep TAB' in lines[4] and '--choose TAB' in lines[4]
    assert len(lines) == 5  # no pin: nothing to clear


def test_versions_of_a_ukulele_sheet_list_its_ukulele_chords_versions(config, conn, tmp_path):
    # A song with no chords on UG took its sheet from UG's Ukulele Chords (ug/fetch.py).
    song = add_song(conn, "Vance Joy", "Riptide")
    uke = upsert_version(conn, provider="ug", tab_id="1391193", song_id=song.id, slot="sheet", kind="ukulele",
                         rating=4.89, votes=12745, version=1, label=None,
                         url=f"{TAB}vance-joy/riptide-ukulele-1391193", raw={}, now="2026-10-20T00:00:00Z")
    upsert_version(conn, provider="ug", tab_id="1419102", song_id=song.id, slot="sheet", kind="ukulele", rating=4.5,
                   votes=40, version=2, label=None, url=f"{TAB}vance-joy/riptide-ukulele-1419102", raw={},
                   now="2026-10-20T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=song, version_id=uke, name="sheet.txt", data=b"uke", rank=1)

    result = versions(config, "Vance Joy - Riptide")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == ("Vance Joy - Riptide: 2 Ukulele Chords versions on Ultimate Guitar; "
                                             "the title opens tab 1391193, caracole's pick.")


def test_versions_names_another_sites_sheet_as_the_one(config, conn, tmp_path):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    theirs = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/de_musica_ligera", song_id=song.id,
                            slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                            url="https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml", raw={},
                            now="2026-10-20T00:00:00Z")
    upsert_version(conn, provider="ug", tab_id="85053", song_id=song.id, slot="sheet", kind="chords", rating=4.5,
                   votes=7, version=2, label=None, url=f"{TAB}85053", raw={}, now="2026-10-20T00:00:00Z")
    keep_file(conn, tmp_path / "library", song=song, version_id=theirs, name="sheet.txt", data=b"lc", rank=1)

    result = versions(config, "Soda Stereo - De Música Ligera")

    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0].endswith("; the sheet is LaCuerda's.")
    assert "the one" not in result.output


def test_versions_of_a_song_with_none_says_so(config, conn):
    add_song(conn, "Oasis", "Wonderwall")
    result = versions(config, "Oasis", "Wonderwall")
    assert result.exit_code == 0, result.output
    assert "no Ultimate Guitar chords versions yet" in result.output


def test_versions_of_a_song_not_in_the_library_exits_1(config, conn):
    result = versions(config, "Oasis - Wonderwall")
    assert result.exit_code == 1 and "No song" in result.output


@pytest.mark.parametrize("args", [["Oasis - Wonderwall", "--keep", "1", "--clear"], ["Wonderwall"],
                                  ["Oasis - Wonderwall", "--keep", "not a tab"],
                                  ["Oasis - Wonderwall", "--keep-more", "--keep", "1"],
                                  ["Oasis - Wonderwall", "--keep-more", "--clear"]])
def test_versions_usage_errors_exit_2(config, conn, args):
    assert versions(config, *args).exit_code == 2


# --- --keep ------------------------------------------------------------------------------------------


@pytest.mark.slow
def test_keep_fetches_one_tab_page_and_keeps_it_beside_the_sheet(config, sites, conn, tmp_path, monkeypatch):
    looked_up(config, sites, conn, tmp_path)
    from caracole import versions_cmd

    locks = []
    real = versions_cmd.exclusive

    def exclusive(cfg, what, **kw):
        locks.append((what, kw.get("interactive")))
        return real(cfg, what, **kw)

    monkeypatch.setattr(versions_cmd, "exclusive", exclusive)

    result = versions(config, CREEP, "--keep", "104")

    assert result.exit_code == 0, result.output
    assert locks == [(f"versions {CREEP} --keep", True)]  # caracole's lock, as a lookup takes it
    assert sites.ug() == [url(104)]  # its page alone
    assert f"Kept tab 104 beside the sheet of {CREEP}" in result.output
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt", "version-104.txt"]
    assert "sheet 104" in (folder(tmp_path) / "version-104.txt").read_text()
    song = find_song(conn, "radiohead/creep")
    assert kept_by_you(conn, song.id) == ("104",)

    # The nightly fetch keeps it, whatever the ranking, from the cache.
    sites.requests.clear()
    fetched = CliRunner().invoke(build_app(), ["--config", str(config), "fetch", "--song", CREEP])
    assert fetched.exit_code == 0, fetched.output
    assert sites.ug() == []
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt", "version-104.txt"]

    listed = versions(config, CREEP).output
    assert "tab 104 · kept" in listed


@pytest.mark.slow
def test_keep_with_the_lookup_budget_spent_keeps_nothing_and_exits_0(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)
    write_config(tmp_path, "lookup_per_hour = 3\n")  # the lookup spent those three

    result = versions(config, CREEP, "--keep", "104")

    assert result.exit_code == 0, result.output
    assert "nothing kept" in result.output
    assert sites.ug() == []
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt"]
    assert kept_by_you(conn, find_song(conn, "radiohead/creep").id) == ()


@pytest.mark.slow
def test_keep_of_a_version_kept_already_sends_nothing(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)
    result = versions(config, CREEP, "--keep", url(103))
    assert result.exit_code == 0, result.output
    assert "kept beside the sheet" in result.output and sites.requests == []
    assert kept_by_you(conn, find_song(conn, "radiohead/creep").id) == ("103",)


@pytest.mark.slow
def test_keep_of_a_tab_that_is_no_version_of_the_song_exits_1(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)
    result = versions(config, CREEP, "--keep", "999")
    assert result.exit_code == 1 and "isn't one of the Ultimate Guitar chords versions" in result.output
    assert sites.requests == []


@pytest.mark.slow
def test_keep_progress_writes_lookup_lines(config, sites, conn, tmp_path):
    from caracole.get import read_progress_line

    looked_up(config, sites, conn, tmp_path)
    result = versions(config, CREEP, "--keep", "104", "--progress")
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    assert events[0] == {"stage": "song", "state": "running", "detail": ""}
    assert any(e.get("stage") == "version" and e["state"] == "done" for e in events)
    assert events[-1]["done"]["ok"] is True and events[-1]["done"]["requests"] == {"ug": 1}



@pytest.mark.slow
def test_keep_blocked_counts_the_request_it_sent_in_its_progress(config, sites, conn, tmp_path):
    from caracole.get import read_progress_line

    looked_up(config, sites, conn, tmp_path)
    sites.pages[url(104)] = (403, "Forbidden")

    result = versions(config, CREEP, "--keep", "104", "--progress")

    assert result.exit_code == 0, result.output
    assert sites.ug() == [url(104)]
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    assert any(e.get("stage") == "version" and e["state"] == "skipped" and "nothing kept" in e["detail"]
               for e in events)
    assert events[-1]["done"]["requests"] == {"ug": 1}
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt"]


def textless(sites, tab_id: int) -> None:
    """Version ``tab_id``'s page answers with no sheet caracole can keep: UG's page there is a Guitar Pro file's
    now, which parses, with no text. (A chords page with no text won't parse: an error, which waits.)"""
    pro = version_dict(tab_id, type="Pro", song="Creep", artist="Radiohead", tab_url=url(tab_id))
    sites.pages[url(tab_id)] = (200, make_tab_page_html(pro, [], content=None))


@pytest.mark.slow
def test_keep_notes_a_version_it_cant_keep(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)
    textless(sites, 104)

    result = versions(config, CREEP, "--keep", "104")

    assert result.exit_code == 0, result.output
    assert "has no sheet caracole can keep" in result.output
    assert unkeepable(conn, find_song(conn, "radiohead/creep").id) == ("104",)
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt"]


# --- --keep-more -------------------------------------------------------------------------------------


@pytest.mark.slow
def test_keep_more_keeps_the_next_versions_in_rank_order_within_the_lookups_budget(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path, more=9)  # 104 to 113 not kept, in that order
    write_config(tmp_path, "lookup_requests = 3\n")

    result = versions(config, CREEP, "--keep-more")

    assert result.exit_code == 0, result.output
    assert sites.ug() == [url(104), url(105), url(106)]
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt", "version-104.txt", "version-105.txt",
                                       "version-106.txt"]
    assert (folder(tmp_path) / "version-105.html").is_file()  # each kept one's viewer page made
    assert kept_by_you(conn, find_song(conn, "radiohead/creep").id) == ("104", "105", "106")
    assert f"Kept 3 versions of {CREEP}; 7 more not kept: ask again." in result.output

    # The nightly fetch keeps them, whatever the ranking, from the cache.
    sites.requests.clear()
    fetched = CliRunner().invoke(build_app(), ["--config", str(config), "fetch", "--song", CREEP])
    assert fetched.exit_code == 0, fetched.output
    assert "version-106.txt" in version_files(tmp_path)


@pytest.mark.slow
def test_keep_more_takes_the_lock_as_a_lookup_does(config, sites, conn, tmp_path, monkeypatch):
    looked_up(config, sites, conn, tmp_path)
    from caracole import versions_cmd

    locks = []
    real = versions_cmd.exclusive

    def exclusive(cfg, what, **kw):
        locks.append((what, kw.get("interactive")))
        return real(cfg, what, **kw)

    monkeypatch.setattr(versions_cmd, "exclusive", exclusive)

    result = versions(config, CREEP, "--keep-more")

    assert result.exit_code == 0, result.output
    assert locks == [(f"versions {CREEP} --keep-more", True)]
    assert f"Kept 1 version of {CREEP}; none is left to keep." in result.output


@pytest.mark.slow
def test_keep_more_passes_over_the_sheet_gone_and_blocked_versions(config, sites, conn, tmp_path):
    from caracole.versions import mark_gone

    looked_up(config, sites, conn, tmp_path)
    song = find_song(conn, "radiohead/creep")
    vids = {}
    for tab in (105, 106):  # rated above 104
        vids[tab] = upsert_version(conn, provider="ug", tab_id=str(tab), song_id=song.id, slot="sheet",
                                   kind="chords", rating=4.95, votes=900, version=tab - 100, label=None, url=url(tab),
                                   raw={}, now="2026-10-20T00:00:00Z")
    mark_gone(conn, vids[105])
    (tmp_path / "library" / "overrides.toml").write_text("[block]\ntab_ids = [106]\n", encoding="utf-8")

    result = versions(config, CREEP, "--keep-more")

    assert result.exit_code == 0, result.output
    assert sites.ug() == [url(104)]  # never the sheet's (102), the gone one's or the blocked one's
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt", "version-104.txt"]


@pytest.mark.slow
def test_keep_more_stops_at_a_block_and_keeps_what_it_kept(config, sites, conn, tmp_path):
    from caracole.health import get_state

    looked_up(config, sites, conn, tmp_path, more=3)
    sites.pages[url(105)] = (403, "Forbidden")

    result = versions(config, CREEP, "--keep-more")

    assert result.exit_code == 0, result.output
    assert sites.ug() == [url(104), url(105)]  # nothing more once blocked
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt", "version-104.txt"]
    assert (folder(tmp_path) / "version-104.html").is_file()  # what it kept is rendered
    assert get_state(conn, "ug").cooldown_until is not None  # recorded as a block, cooling UG down
    assert "Ultimate Guitar blocked caracole" in result.output
    assert f"Kept 1 version of {CREEP}; 3 more not kept." in result.output  # not "ask again": UG cools down

    sites.requests.clear()
    cooling = versions(config, CREEP, "--keep-more")
    assert cooling.exit_code == 0 and "cooling down" in cooling.output and sites.requests == []


@pytest.mark.slow
def test_keep_more_stops_at_a_page_that_wont_parse_and_counts_it_still(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path, more=2)
    chords_page = creep_tab(105, rating=3.4, votes=20)
    sites.pages[url(105)] = (200, make_tab_page_html(chords_page, [], content=None))  # a chords page, no text

    result = versions(config, CREEP, "--keep-more")

    assert result.exit_code == 0, result.output
    assert sites.ug() == [url(104), url(105)]
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt", "version-104.txt"]
    assert (folder(tmp_path) / "version-104.html").is_file()
    assert "Ultimate Guitar failed" in result.output
    assert f"Kept 1 version of {CREEP}; 2 more not kept: ask again." in result.output  # 105 waits, as any page
    assert unkeepable(conn, find_song(conn, "radiohead/creep").id) == ()


@pytest.mark.slow
def test_keep_more_with_nothing_left_sends_nothing(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)
    assert versions(config, CREEP, "--keep", "104").exit_code == 0
    sites.requests.clear()

    result = versions(config, CREEP, "--keep-more", "--progress")

    assert result.exit_code == 0, result.output
    assert f"Nothing more to keep of {CREEP}" in result.output
    assert sites.requests == []


@pytest.mark.slow
def test_keep_more_notes_the_versions_it_cant_keep(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path, more=1)
    textless(sites, 104)

    result = versions(config, CREEP, "--keep-more")

    assert result.exit_code == 0, result.output
    assert sites.ug() == [url(104), url(105)]  # past the one it can't keep, to the next
    assert "Tab 104 of Radiohead - Creep: its page has no sheet caracole can keep." in result.output
    assert unkeepable(conn, find_song(conn, "radiohead/creep").id) == ("104",)
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt", "version-105.txt"]

    sites.requests.clear()
    again = versions(config, CREEP, "--keep-more")
    assert again.exit_code == 0 and f"Nothing more to keep of {CREEP}" in again.output
    assert sites.requests == []  # never that page again


@pytest.mark.slow
def test_keep_more_progress_counts_in_the_version_stage(config, sites, conn, tmp_path):
    from caracole.get import read_progress_line

    looked_up(config, sites, conn, tmp_path, more=9)
    write_config(tmp_path, "lookup_requests = 3\n")

    result = versions(config, CREEP, "--keep-more", "--progress")

    assert result.exit_code == 0, result.output
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    ended = [(e["stage"], e["state"], e["detail"]) for e in events if "stage" in e and e["state"] != "running"]
    assert ended[0] == ("song", "done", "in the library")
    assert ended[1] == ("version", "done", "kept 3 of 10")
    assert [name for name, _, _ in ended[2:]] == ["pdf", "pages"]
    assert events[-1]["done"]["ok"] is True and events[-1]["done"]["requests"] == {"ug": 3}

# --- --choose and --clear --------------------------------------------------------------------------------


@pytest.mark.slow
def test_choose_pins_a_version_and_clear_goes_back_to_caracoles_pick(config, sites, conn, tmp_path):
    # Review Focus 2: a pin outside the top three, then the pin cleared.
    looked_up(config, sites, conn, tmp_path)
    overrides = tmp_path / "library" / "overrides.toml"
    overrides.write_text("# my decisions\n[block]  # never these\ntab_ids = [7]\n", encoding="utf-8")

    chose = versions(config, CREEP, "--choose", "104")

    assert chose.exit_code == 0, chose.output
    assert load_overrides(overrides).pin["radiohead/creep"] == (104,)
    assert load_overrides(overrides).pin_urls["radiohead/creep"] == (url(104),)
    assert "sheet 104" in (folder(tmp_path) / "sheet.txt").read_text()
    assert version_files(tmp_path) == ["version-101.txt", "version-102.txt", "version-103.txt"]
    assert "tab 104 · kept · the one" in versions(config, CREEP).output
    assert "--clear" in versions(config, CREEP).output

    cleared = versions(config, CREEP, "--clear")

    assert cleared.exit_code == 0, cleared.output
    assert "Took tab 104 out of [pin]" in cleared.output
    text = overrides.read_text(encoding="utf-8")
    assert "# my decisions" in text and "# never these" in text and "104" not in text
    assert load_overrides(overrides).pin == {}
    assert "sheet 102" in (folder(tmp_path) / "sheet.txt").read_text()
    assert version_files(tmp_path) == ["version-101.txt", "version-103.txt"]
    assert not list(folder(tmp_path).glob("version-104*"))


@pytest.mark.slow
def test_clear_without_a_pin_changes_nothing(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)
    result = versions(config, CREEP, "--clear")
    assert result.exit_code == 0, result.output
    assert "caracole's pick is the sheet already" in result.output and sites.requests == []


@pytest.mark.slow
def test_clear_leaves_a_tab_pin(config, sites, conn, tmp_path):
    looked_up(config, sites, conn, tmp_path)
    upsert_rows(conn, [(401, "radiohead", "creep", "tabs", "radiohead/creep-tabs-401")], "1", NOW)
    overrides = tmp_path / "library" / "overrides.toml"
    overrides.write_text(f'[pin]\n"Radiohead - Creep" = ["{url(104)}", "{TAB}radiohead/creep-tabs-401"]\n',
                         encoding="utf-8")

    result = versions(config, CREEP, "--clear")

    assert result.exit_code == 0, result.output
    assert load_overrides(overrides).pin["radiohead/creep"] == (401,)


@pytest.mark.slow
def test_a_second_lookup_rewrites_no_version_file(config, sites, conn, tmp_path):
    # Its first, quick pass scores one sheet alone: the versions kept wait for the pass after it.
    looked_up(config, sites, conn, tmp_path)
    before = {p.name: p.stat().st_ino for p in folder(tmp_path).glob("version-*")}

    assert get(config, CREEP).exit_code == 0

    assert {p.name: p.stat().st_ino for p in folder(tmp_path).glob("version-*")} == before


@pytest.mark.slow
def test_get_says_which_versions_it_kept_beside_the_sheet(config, sites, conn, tmp_path):
    result = looked_up(config, sites, conn, tmp_path)
    ug = next(line for line in result.output.splitlines() if line.startswith("Ultimate Guitar: "))
    assert ug.startswith("Ultimate Guitar: sheet 102") and ug.endswith("kept beside it: tab 103, tab 101.")


def test_choose_of_a_gone_version_exits_1(config, conn, tmp_path):
    from caracole.versions import mark_gone

    song = wonderwall(conn, tmp_path)
    [row] = conn.execute("SELECT id FROM versions WHERE song_id = ? AND tab_id = '555'", (song.id,)).fetchall()
    mark_gone(conn, row[0])
    result = versions(config, "Oasis - Wonderwall", "--choose", "555")
    assert result.exit_code == 1 and "no longer has tab 555" in result.output


def test_registering_the_command_imports_no_http_client_nor_the_fetch(tmp_path):
    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, typer\n"
        "from caracole.commands import versions\n"
        "versions.register(typer.Typer())\n"
        "print([m for m in ('httpx', 'caracole.http', 'caracole.ug.fetch', 'caracole.versions_cmd',"
        " 'caracole.sheet_versions', 'rapidfuzz') if m in sys.modules])\n"
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"

