"""``caracole remove``, run through the CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import add_song, subprocess_pythonpath
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.library import keep_file, song_dir
from caracole.songs import get_song, list_removed, list_songs
from caracole.versions import upsert_version


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "caracole.toml"
    path.write_text(f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
                    f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    return path


def run(tmp_path, *args, input=None):
    return CliRunner().invoke(build_app(), ["--config", str(write_config(tmp_path)), *args], input=input)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "state" / "caracole.sqlite")
    yield c
    c.close()


def a_found_song(tmp_path, conn, artist="Radiohead", title="Creep"):
    """A song from wanted.txt with a sheet caracole kept, and a file of yours beside it."""
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    wanted = lib / "wanted.txt"
    with wanted.open("a", encoding="utf-8") as f:
        f.write(f"{artist} - {title}\n")
    song = add_song(conn, artist, title, source="wanted", source_id=f"{artist.lower()}/{title.lower()}")
    vid = upsert_version(conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url="https://u/101", raw={},
                         now="2026-10-01T00:00:00Z")
    keep_file(conn, lib, song=song, version_id=vid, name="sheet.txt", data=b"[Am]Creep", rank=1)
    (song_dir(lib, song) / "notes.md").write_text("capo 2", encoding="utf-8")
    return get_song(conn, song.id)


def test_remove_says_what_goes_and_what_stays_asks_then_removes(tmp_path, conn):
    song = a_found_song(tmp_path, conn)
    add_song(conn, "Oasis", "Wonderwall")
    result = run(tmp_path, "remove", "Radiohead - Creep", input="y\n")
    assert result.exit_code == 0, result.output
    out = result.output
    asked = out.index("Remove it?")
    assert out.startswith("Remove Radiohead - Creep from caracole?")
    assert "its line in wanted.txt (line 1)" in out[:asked]
    assert "2 files caracole wrote in Radiohead/Creep/: info.json, sheet.txt" not in out  # no info.json yet
    assert "1 file caracole wrote in Radiohead/Creep/: sheet.txt" in out[:asked]
    assert "Radiohead/Creep/notes.md: caracole didn't write it" in out[:asked]
    assert "until you ask for it again" in out[:asked]
    assert "Removed Radiohead - Creep: deleted 1 file, took 1 line out of wanted.txt." in out[asked:]
    assert "It left:\n  - Radiohead/Creep/notes.md: caracole didn't write it" in out[asked:]
    assert [s.title for s in list_songs(conn)] == ["Wonderwall"]
    assert [r.display for r in list_removed(conn)] == ["Radiohead - Creep"]
    folder = song_dir(tmp_path / "lib", song)
    assert sorted(p.name for p in folder.iterdir()) == ["notes.md"]
    assert (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8") == ""
    # The pages no longer list it.
    page = (tmp_path / "lib" / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'id="songs">(.*?)</script>', page, re.S).group(1))
    assert [s["title"] for s in data["songs"]] == ["Wonderwall"]
    assert "Creep" not in (tmp_path / "lib" / "_todo.md").read_text(encoding="utf-8")


def test_saying_no_removes_nothing(tmp_path, conn):
    a_found_song(tmp_path, conn)
    result = run(tmp_path, "remove", "Radiohead - Creep", input="n\n")
    assert result.exit_code == 0 and "Nothing was removed." in result.output
    assert [s.title for s in list_songs(conn)] == ["Creep"] and list_removed(conn) == []
    assert (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8") == "Radiohead - Creep\n"


def test_yes_skips_the_question(tmp_path, conn):
    a_found_song(tmp_path, conn)
    result = run(tmp_path, "remove", "--yes", "Radiohead - Creep")
    assert result.exit_code == 0, result.output
    assert "Remove it?" not in result.output and "Removed Radiohead - Creep" in result.output
    assert list_songs(conn) == []


def test_without_an_answer_nothing_is_removed(tmp_path, conn):
    # As from a script, or the web page's queue, without --yes.
    a_found_song(tmp_path, conn)
    result = run(tmp_path, "remove", "Radiohead - Creep", input="")
    assert result.exit_code == 1 and [s.title for s in list_songs(conn)] == ["Creep"]


def test_a_song_the_library_doesnt_have_is_an_error(tmp_path, conn):
    result = run(tmp_path, "remove", "--yes", "Radiohead - Creep")
    assert result.exit_code == 1 and 'No song "Radiohead - Creep" in the library' in result.output
    result = run(tmp_path, "remove", "--yes", "Creep")
    assert result.exit_code == 2 and '"ARTIST - TITLE"' in result.output
    assert run(tmp_path, "remove").exit_code == 2  # a song, or --list


def test_a_song_removed_already_says_how_to_bring_it_back(tmp_path, conn):
    a_found_song(tmp_path, conn)
    assert run(tmp_path, "remove", "--yes", "Radiohead - Creep").exit_code == 0
    result = run(tmp_path, "remove", "--yes", "radiohead - CREEP")
    assert result.exit_code == 0, result.output
    assert "Radiohead - Creep was removed on 20" in result.output and "caracole add" in result.output


def test_an_artist_with_a_dash_in_the_name_is_found(tmp_path, conn):
    # A song an older caracole kept (Spotify brought some) may have " - " in its artist's name, and the web page's
    # Remove names a song by its display: every split is tried, removed already too.
    add_song(conn, "Sergio Mendes - Brasil '66", "Mas Que Nada")
    result = run(tmp_path, "remove", "--yes", "Sergio Mendes - Brasil '66 - Mas Que Nada")
    assert result.exit_code == 0, result.output
    assert list_songs(conn) == []
    result = run(tmp_path, "remove", "--yes", "Sergio Mendes - Brasil '66 - Mas Que Nada")
    assert result.exit_code == 0 and "Sergio Mendes - Brasil '66 - Mas Que Nada was removed on 20" in result.output


def test_list_shows_the_removed_songs_newest_first(tmp_path, conn):
    assert run(tmp_path, "remove", "--list").output == "No removed songs.\n"
    a_found_song(tmp_path, conn)
    a_found_song(tmp_path, conn, "Oasis", "Wonderwall")
    assert run(tmp_path, "remove", "--yes", "Radiohead - Creep").exit_code == 0
    assert run(tmp_path, "remove", "--yes", "Oasis - Wonderwall").exit_code == 0
    conn.execute("UPDATE removed SET removed_at = '2026-10-01T08:00:00Z' WHERE key = 'radiohead/creep'")
    result = run(tmp_path, "remove", "--list")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[1:] == [
        "  Oasis - Wonderwall" + lines[1].removeprefix("  Oasis - Wonderwall"),
        "  Radiohead - Creep  removed 2026-10-01 08:00 UTC",
    ]
    assert lines[0] == "2 removed songs; `caracole add` brings one back:"


def test_caracole_add_brings_a_removed_song_back_and_says_so(tmp_path, conn):
    a_found_song(tmp_path, conn)
    assert run(tmp_path, "remove", "--yes", "Radiohead - Creep").exit_code == 0
    result = run(tmp_path, "add", "Radiohead", "Creep")
    assert result.exit_code == 0, result.output
    assert "back from its removal on 20" in result.output
    assert [s.title for s in list_songs(conn)] == ["Creep"] and list_removed(conn) == []


@pytest.mark.slow
def test_registering_the_command_imports_no_removal_code(tmp_path):
    # Every command module is imported on every start, so the removal waits for the command.
    src = Path(__file__).resolve().parents[1] / "src"
    code = ("import sys, typer\nfrom caracole.commands import remove\nremove.register(typer.Typer())\n"
            "print([m for m in ('caracole.removal', 'caracole.wanted', 'caracole.todo') if m in sys.modules])\n")
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
