"""``caracole get``, run through the CLI against fake sites: one song, now, sheet first.

The sites are test_get.py's ``Sites`` behind ``caracole.commands._common.transport_for``;
chordpro is a fake script that writes a dummy PDF.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from test_get import TAB, Sites, serve_creep
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.get import PROGRESS_PREFIX, read_progress_line
from caracole.songs import find_song
from conftest import subprocess_pythonpath

FAKE_CHORDPRO = """\
#!{python}
import sys
out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
open(out, "w").write("%PDF-1.4 fake")
"""
OUTSIDE_SETTINGS = ("CARACOLE_CONFIG",)


@pytest.fixture
def sites(monkeypatch) -> Sites:
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", lambda provider: httpx.MockTransport(s.handler))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return s


@pytest.fixture
def config(tmp_path) -> Path:
    chordpro = tmp_path / "bin" / "chordpro"
    chordpro.parent.mkdir()
    chordpro.write_text(FAKE_CHORDPRO.format(python=sys.executable), encoding="utf-8")
    chordpro.chmod(0o755)
    providers = "".join(f"[providers.{p}]\ndelay = [0, 0]\nlookup_delay = [0, 0]\n"
                        for p in ("ug", "lrclib", "lacuerda", "gtptabs", "musescore"))
    path = tmp_path / "caracole.toml"
    path.write_text(f'data_dir = "{tmp_path}"\nchordpro_bin = "{chordpro}"\n{providers}', encoding="utf-8")
    return path


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "state" / "caracole.sqlite")
    yield c
    c.close()


def get(config, *args):
    return CliRunner().invoke(build_app(), ["--config", str(config), "get", *args])


@pytest.mark.slow
def test_get_says_where_the_sheet_is_as_soon_as_it_is_kept(config, sites, conn, tmp_path):
    serve_creep(sites, conn)

    result = get(config, "Radiohead - Creep")

    assert result.exit_code == 0, result.output
    sheet = tmp_path / "library" / "Radiohead" / "Creep" / "sheet.txt"
    lines = result.output.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("Sheet: "))
    assert str(sheet) in lines[at] and "from Ultimate Guitar" in lines[at] and "readable after" in lines[at]
    assert any(line.startswith("Lyrics: found") for line in lines[at:])  # after the sheet
    assert lines[-1].startswith("Done in ") and "4 requests" in lines[-1]
    assert find_song(conn, "radiohead/creep").status == "found"


@pytest.mark.slow
def test_get_takes_the_artist_and_the_title_as_two_words_too(config, sites, conn):
    serve_creep(sites, conn)
    assert get(config, "Radiohead", "Creep").exit_code == 0
    assert find_song(conn, "radiohead/creep").status == "found"


@pytest.mark.slow
def test_get_print_shows_the_sheet_itself(config, sites, conn):
    serve_creep(sites, conn)
    result = get(config, "--print", "Radiohead - Creep")
    assert result.exit_code == 0, result.output
    assert "sheet 101" in result.output  # the first sheet, the moment it is kept
    assert "walking down the river road tonight" in result.output


@pytest.mark.slow
def test_get_progress_writes_a_json_line_per_stage_for_caracole_serve(config, sites, conn):
    serve_creep(sites, conn)
    result = get(config, "--progress", "Radiohead - Creep")
    assert result.exit_code == 0, result.output
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    assert events[0] == {"stage": "song", "state": "running", "detail": ""}
    assert {"stage": "sheet", "state": "done", "detail": "tab 101 from Ultimate Guitar"} in events
    readable = next(e for e in events if "files" in e)
    assert readable["files"]["sheet"] == "Radiohead/Creep/sheet.txt" and readable["seconds"] >= 0
    song = next(e for e in events if "song" in e)
    assert song["song"] == {"id": find_song(conn, "radiohead/creep").id, "display": "Radiohead - Creep"}
    assert all(line.startswith(PROGRESS_PREFIX) or not line.startswith("{") for line in result.output.splitlines())
    json.loads(result.output.splitlines()[0][len(PROGRESS_PREFIX):])


@pytest.mark.slow
def test_get_no_songbooks_leaves_the_songbooks_alone(config, sites, conn, tmp_path):
    from caracole.songbook import make_songbook, songbooks_file

    serve_creep(sites, conn)
    make_songbook(songbooks_file(tmp_path / "library"), "Campfire", ["Radiohead - Creep"])
    result = get(config, "--progress", "--no-songbooks", "Radiohead - Creep")
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "library" / "_songbooks").exists()
    plain = get(config, "--progress", "Radiohead - Creep")
    assert plain.exit_code == 0, plain.output
    assert (tmp_path / "library" / "_songbooks" / "Campfire" / "songbook.html").is_file()


@pytest.mark.slow
def test_get_records_the_ug_song_and_the_tab_you_pick(config, sites, conn, tmp_path):
    serve_creep(sites, conn)
    result = get(config, "--ug", "radiohead/creep", "--tab", f"{TAB}radiohead/creep-chords-103", "Radiohead - Creep")
    assert result.exit_code == 0, result.output
    overrides = (tmp_path / "library" / "overrides.toml").read_text(encoding="utf-8")
    assert '"Radiohead - Creep" = "radiohead/creep"' in overrides
    assert f'"Radiohead - Creep" = ["{TAB}radiohead/creep-chords-103"]' in overrides


@pytest.mark.slow
def test_get_records_the_lacuerda_song_you_pick(config, sites, conn, tmp_path):
    from test_get import CAMARON_2, serve_como_camaron

    serve_como_camaron(sites, conn)
    result = get(config, "--lacuerda", "acordes.lacuerda.net/estopa/como_camaron-2.shtml", "Estopa - Como Camarón")
    assert result.exit_code == 0, result.output
    overrides = (tmp_path / "library" / "overrides.toml").read_text(encoding="utf-8")
    assert f'[lacuerda]\n"Estopa - Como Camarón" = "{CAMARON_2}"' in overrides
    assert sites.requests[0] == CAMARON_2 and "Sheet: sheet kept from LaCuerda" in result.output


@pytest.mark.parametrize("args,said", [
    (["Radiohead"], 'a song as "Artist - Title"'),
    (["a", "b", "c"], 'a song as "Artist - Title"'),
    (["--tab", "https://example.com/x", "Radiohead - Creep"], "--tab"),
    (["--ug", "radiohead", "Radiohead - Creep"], "--ug"),
    (["--lacuerda", "https://acordes.lacuerda.net/estopa/", "Estopa - Como Camarón"], "--lacuerda"),
    (["--lacuerda", f"{TAB}radiohead/creep-chords-103", "Radiohead - Creep"], "--lacuerda"),
    (["--harptabs", "https://www.harptabs.com/artist/9/radiohead", "Radiohead - Creep"], "--harptabs"),
    (["--gametabs", "https://gametabs.net/tabs/actraiser", "Yuzo Koshiro - Fillmore"], "--gametabs"),
    (["--duration", "soon", "Radiohead - Creep"], "--duration"),
])
def test_get_refuses_what_isnt_a_song_with_status_2(config, sites, args, said):
    result = get(config, *args)
    assert result.exit_code == 2 and said in result.output
    assert sites.requests == []


def test_get_with_a_title_alone_offers_its_ug_songs_and_looks_nothing_up(config, sites, conn):
    from datetime import UTC, datetime

    from caracole.ug.index import mark_built, upsert_rows

    when = datetime(2026, 10, 20, tzinfo=UTC)
    upsert_rows(conn, [(6125, "oasis", "wonderwall", "chords", "oasis/wonderwall-chords-6125"),
                       (2426561, "ryan-adams", "wonderwall", "chords", "ryan-adams/wonderwall-chords-2426561")],
                "1", when)
    mark_built(conn, when)
    result = get(config, "Wonderwall")
    assert result.exit_code == 2, result.output
    assert '     caracole get --ug oasis/wonderwall "Oasis - Wonderwall"\n' in result.output
    assert '     caracole get --ug ryan-adams/wonderwall "Ryan Adams - Wonderwall"\n' in result.output
    assert 'a song as "Artist - Title"' in result.output and '"Wonderwall" is one name' in result.output
    assert sites.requests == [] and find_song(conn, "oasis/wonderwall") is None
    from conftest import add_song

    add_song(conn, "misc", "Wonderwall")  # a placeholder artist: nothing can be found by it
    mine = get(config, "Wonderwall").output
    assert "misc - Wonderwall · wanted" in mine and 'caracole get "misc - Wonderwall"' not in mine



@pytest.mark.slow
def test_get_with_one_text_reads_its_names_as_the_pages_do(config, sites, conn):
    # song_names.py: an en dash as wanted.txt reads one; a text that doesn't say who its artist is looks nothing up.
    serve_creep(sites, conn)
    result = get(config, "Radiohead – Creep")
    assert result.exit_code == 0, result.output
    assert "Read “Radiohead – Creep” as Radiohead - Creep." in result.output
    assert find_song(conn, "radiohead/creep") is not None
    asked = len(sites.requests)
    unread = get(config, "silvana estrada que problema")
    assert unread.exit_code == 2 and '"silvana estrada que problema" is one name' in unread.output
    assert len(sites.requests) == asked


def test_get_with_one_name_gives_no_line_to_run_for_a_weak_hit(config, sites, conn):
    from datetime import UTC, datetime

    from caracole.ug.index import mark_built, upsert_rows

    when = datetime(2026, 10, 20, tzinfo=UTC)
    upsert_rows(conn, [(9001, "anju-panta", "banma-phulyo-fullai-ful", "chords",
                        "anju-panta/banma-phulyo-fullai-ful-chords-9001")], "1", when)
    mark_built(conn, when)
    result = get(config, "斑马")
    assert result.exit_code == 2, result.output
    assert "Anju Panta - Banma Phulyo Fullai Ful" in result.output  # listed, as caracole search numbers it
    assert "caracole get --ug" not in result.output  # but no line to run: it may well be another song
    assert "Run one of the lines above" not in result.output and "Name its artist too" in result.output


def test_get_of_a_song_ignored_in_overrides_toml_exits_1(config, sites, conn, tmp_path):
    (tmp_path / "library").mkdir(exist_ok=True)
    (tmp_path / "library" / "overrides.toml").write_text('[ignore]\nsongs = ["Radiohead - Creep"]\n',
                                                         encoding="utf-8")
    result = get(config, "Radiohead - Creep")
    assert result.exit_code == 1 and "ignored in overrides.toml" in result.output
    assert sites.requests == []


def test_a_block_exits_0(config, sites, conn):
    serve_creep(sites, conn)
    sites.pages[f"{TAB}radiohead/creep-chords-101"] = (403, "Forbidden")
    result = get(config, "Radiohead - Creep")
    assert result.exit_code == 0, result.output
    assert "blocked caracole" in result.output and "Nothing was marked not found" in result.output


@pytest.mark.slow
def test_registering_the_command_imports_no_lookup_code(tmp_path):
    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, typer\n"
        "from caracole.commands import get\n"
        "get.register(typer.Typer())\n"
        "print([m for m in ('caracole.get', 'caracole.ug', 'rapidfuzz', 'caracole.match') if m in sys.modules])\n"
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"
