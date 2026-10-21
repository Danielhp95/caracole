"""``caracole songbook``: make, list, show, add, remove, move, rename, delete and render songbooks."""

from __future__ import annotations

import fcntl
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import add_song, subprocess_pythonpath
from helpers.songbooks import fake_chordpro_program, keep_sheet, render_sheets
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.config import load_config
from caracole.songbook import FILE_NAME, Songbook, load_songbooks, make_songbook


@pytest.fixture
def setup(tmp_path):
    """A library with three songs, two with sheets; the config file and the database."""
    chordpro = fake_chordpro_program(tmp_path)
    font = tmp_path / "Kai.otf"  # just enough of an OpenType (CFF) font to pass render.py's checks
    font.write_bytes(b"OTTO" + struct.pack(">HHHH", 1, 0, 0, 0) + struct.pack(">4sIII", b"CFF ", 0, 28, 4) + bytes(4))
    toml = tmp_path / "caracole.toml"
    toml.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
        f'cache_dir = "{tmp_path / "cache"}"\nmusic_dir = "{tmp_path / "music"}"\nchordpro_bin = "{chordpro}"\n'
        f'cjk_font = "{font}"\n',
        encoding="utf-8",
    )
    cfg = load_config(toml, env={})
    conn = db.connect(cfg.db_path)
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet(conn, cfg, soda, tab_id=1)
    zh = add_song(conn, "宋冬野", "斑马，斑马")
    keep_sheet(conn, cfg, zh, tab_id=2)
    add_song(conn, "Muse", "Hysteria")
    render_sheets(conn, cfg)
    yield toml, cfg, conn
    conn.close()


def run(setup, *args):
    toml, _, _ = setup
    return CliRunner().invoke(build_app(), ["--config", str(toml), "songbook", *args],
                              env={"CARACOLE_CJK_FONT": None})


def books(setup) -> list[Songbook]:
    return load_songbooks(setup[1].library_dir / FILE_NAME)


def folder(setup, name="Campfire") -> Path:
    return setup[1].library_dir / "_songbooks" / name


# --- make ----------------------------------------------------------------------------------------


@pytest.mark.slow
def test_make_writes_the_songbook_with_the_songs_as_the_library_names_them_and_renders_it(setup):
    result = run(setup, "make", "Campfire", "soda stereo - de musica ligera", "ban ma ban ma", "Muse - Hysteria")
    assert result.exit_code == 0, result.output
    assert books(setup) == [Songbook("Campfire", (
        "Soda Stereo - De Música Ligera", "宋冬野 - 斑马，斑马", "Muse - Hysteria"))]
    assert 'Made the songbook "Campfire": 3 songs' in result.output
    assert 'Took 宋冬野 - 斑马，斑马 for "ban ma ban ma"' in result.output  # found by a search: said so
    assert "Muse - Hysteria has no sheet yet" in result.output
    assert sorted(p.name for p in folder(setup).iterdir()) == ["songbook.cho", "songbook.html", "songbook.pdf"]
    assert (setup[1].library_dir / "index.html").is_file()  # the library pages, rewritten


def test_make_refuses_a_song_the_library_lacks_and_writes_nothing(setup):
    result = run(setup, "make", "Campfire", "Soda Stereo - De Música Ligera", "Soda Stereo - Persiana Americana")
    assert result.exit_code == 1
    assert 'No song "Soda Stereo - Persiana Americana" in the library' in result.output
    assert "caracole add" in result.output
    assert not (setup[1].library_dir / FILE_NAME).exists()


def test_make_refuses_a_name_taken_and_a_name_that_cant_be_a_folder(setup):
    assert run(setup, "make", "Campfire", "Muse - Hysteria").exit_code == 0
    result = run(setup, "make", "campfire", "Muse - Hysteria")
    assert result.exit_code == 1 and "already" in result.output
    result = run(setup, "make", ".hidden", "Muse - Hysteria")
    assert result.exit_code == 1 and "dot" in result.output


@pytest.mark.slow
def test_make_keeps_a_song_named_twice_once_and_says_so(setup):
    result = run(setup, "make", "Gig", "Muse - Hysteria", "Soda Stereo - De Música Ligera", "muse - hysteria")
    assert result.exit_code == 0, result.output
    assert 'Made the songbook "Gig": 2 songs.' in result.output and "Muse - Hysteria is in it already" in result.output
    assert books(setup) == [Songbook("Gig", ("Muse - Hysteria", "Soda Stereo - De Música Ligera"))]


def test_make_needs_songs(setup):
    result = run(setup, "make", "Campfire")
    assert result.exit_code == 2


# --- reading them ---------------------------------------------------------------------------------


@pytest.mark.slow
def test_list_and_show_say_what_each_songbook_holds(setup):
    _, cfg, _ = setup
    assert "No songbooks yet" in run(setup, "list").output
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire",
                  ["Soda Stereo - De Música Ligera", "Muse - Hysteria", "Gone Band - Removed Song"])
    listed = run(setup, "list")
    assert listed.exit_code == 0
    assert "Campfire: 3 songs, 2 without a sheet · not made yet" in listed.output
    run(setup, "render")
    assert "songbook.pdf, songbook.html, songbook.cho" in run(setup, "list").output
    shown = run(setup, "show", "CAMPFIRE")
    assert shown.exit_code == 0, shown.output
    lines = shown.output.splitlines()
    assert "  1. Soda Stereo - De Música Ligera" in lines
    assert "  2. Muse - Hysteria (missing: no sheet yet)" in lines
    assert "  3. Gone Band - Removed Song (missing: not in the library)" in lines
    assert str(folder(setup) / "songbook.html") in shown.output
    assert run(setup, "show", "Picnic").exit_code == 1


def test_reading_never_waits_for_another_caracole(setup):
    _, cfg, _ = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Muse - Hysteria"])
    lock = cfg.state_dir / "caracole.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another caracole holds it
        assert run(setup, "list").exit_code == 0
        assert run(setup, "show", "Campfire").exit_code == 0
    finally:
        os.close(fd)


def test_a_broken_songbooks_file_exits_2_naming_it(setup):
    _, cfg, _ = setup
    (cfg.library_dir / FILE_NAME).write_text("[Campfire\n", encoding="utf-8")
    for args in (("list",), ("make", "Picnic", "Muse - Hysteria"), ("render",)):
        result = run(setup, *args)
        assert result.exit_code == 2, args
        assert FILE_NAME in result.output


# --- changing them --------------------------------------------------------------------------------


@pytest.mark.slow
def test_add_remove_move_rename_and_delete(setup):
    assert run(setup, "make", "Campfire", "Muse - Hysteria").exit_code == 0
    added = run(setup, "add", "campfire", "soda stereo - de música ligera", "Muse - Hysteria")
    assert added.exit_code == 0, added.output
    assert "Added Soda Stereo - De Música Ligera" in added.output and "Muse - Hysteria is in it already" in added.output
    assert run(setup, "add", "Campfire", "Nobody - Nothing").exit_code == 1

    moved = run(setup, "move", "Campfire", "De Musica Ligera", "1")
    assert moved.exit_code == 0, moved.output
    assert books(setup)[0].songs == ("Soda Stereo - De Música Ligera", "Muse - Hysteria")
    assert "Moved Soda Stereo - De Música Ligera to 1" in moved.output
    assert run(setup, "move", "Campfire", "Muse - Hysteria", "0").exit_code == 2

    removed = run(setup, "remove", "Campfire", "Muse - Hysteria")
    assert removed.exit_code == 0 and "Removed Muse - Hysteria" in removed.output
    assert books(setup)[0].songs == ("Soda Stereo - De Música Ligera",)
    assert run(setup, "remove", "Campfire", "Muse - Hysteria").exit_code == 1  # not in it any more

    renamed = run(setup, "rename", "Campfire", "Beach nights")
    assert renamed.exit_code == 0, renamed.output
    assert [b.name for b in books(setup)] == ["Beach nights"]
    assert folder(setup, "Beach nights").is_dir() and not folder(setup).exists()

    deleted = run(setup, "delete", "beach nights")
    assert deleted.exit_code == 0 and 'Deleted the songbook "Beach nights"' in deleted.output
    assert books(setup) == [] and not folder(setup, "Beach nights").exists()
    assert run(setup, "delete", "Beach nights").exit_code == 1


def test_a_song_removed_from_the_library_can_be_taken_out_by_its_name(setup):
    _, cfg, _ = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Gone Band - Removed Song", "Muse - Hysteria"])
    result = run(setup, "remove", "Campfire", "gone band - removed song")
    assert result.exit_code == 0, result.output
    assert books(setup)[0].songs == ("Muse - Hysteria",)


@pytest.fixture
def gig(setup):
    """The songbook Gig: Karma Police, Wonderwall, then Karma Police Live, a song removed from the library
    since, whose title holds Karma Police's: a search would take one for the other."""
    _, cfg, conn = setup
    police = add_song(conn, "Radiohead", "Karma Police")
    keep_sheet(conn, cfg, police, tab_id=3)
    add_song(conn, "Oasis", "Wonderwall")
    live = add_song(conn, "Radiohead", "Karma Police Live")
    render_sheets(conn, cfg)
    make_songbook(cfg.library_dir / FILE_NAME, "Gig",
                  ["Radiohead - Karma Police", "Oasis - Wonderwall", "Radiohead - Karma Police Live"])
    conn.execute("DELETE FROM songs WHERE id = ?", (live.id,))


@pytest.mark.slow
def test_a_song_gone_from_the_library_is_shown_missing_and_moved_or_taken_out_alone(setup, gig):
    lines = run(setup, "show", "Gig").output.splitlines()
    assert lines[1:4] == ["  1. Radiohead - Karma Police", "  2. Oasis - Wonderwall (missing: no sheet yet)",
                          "  3. Radiohead - Karma Police Live (missing: not in the library)"]
    assert "Gig: 3 songs, 2 without a sheet" in run(setup, "list").output

    moved = run(setup, "move", "--", "Gig", "Radiohead - Karma Police Live", "1")  # as the page's ↑ queues it
    assert moved.exit_code == 0, moved.output
    assert "Moved Radiohead - Karma Police Live to 1" in moved.output
    assert books(setup)[0].songs == ("Radiohead - Karma Police Live", "Radiohead - Karma Police",
                                     "Oasis - Wonderwall")

    removed = run(setup, "remove", "--", "Gig", "Radiohead - Karma Police Live")  # as the page's × queues it
    assert removed.exit_code == 0, removed.output
    assert removed.output.splitlines()[0] == "Removed Radiohead - Karma Police Live"
    assert "Removed Radiohead - Karma Police\n" not in removed.output
    assert books(setup)[0].songs == ("Radiohead - Karma Police", "Oasis - Wonderwall")


@pytest.mark.slow
def test_a_song_caracole_remove_takes_out_of_the_library_is_missing_from_its_songbook(setup):
    # caracole remove deletes the song's record and its files, never a songbook's entry: the songbook goes
    # on, listing the song as missing until you take it out, and every file of it is made again.
    toml, cfg, conn = setup
    made = run(setup, "make", "Campfire", "Soda Stereo - De Música Ligera", "宋冬野 - 斑马，斑马")
    assert made.exit_code == 0, made.output
    gone = CliRunner().invoke(build_app(), ["--config", str(toml), "remove", "--yes",
                                            "Soda Stereo - De Música Ligera"], env={"CARACOLE_CJK_FONT": None})
    assert gone.exit_code == 0, gone.output
    assert conn.execute("SELECT count(*) FROM songs WHERE title = 'De Música Ligera'").fetchone()[0] == 0
    assert books(setup) == [Songbook("Campfire", ("Soda Stereo - De Música Ligera", "宋冬野 - 斑马，斑马"))]

    shown = run(setup, "show", "Campfire").output.splitlines()
    assert shown[1:3] == ["  1. Soda Stereo - De Música Ligera (missing: not in the library)", "  2. 宋冬野 - 斑马，斑马"]
    index = (cfg.library_dir / "index.html").read_text(encoding="utf-8")  # caracole remove rewrote it
    assert re.search(r'<li class="missing">.*?De Música Ligera.*?missing: not in the library', index)

    rendered = run(setup, "render", "Campfire")
    assert rendered.exit_code == 0, rendered.output
    assert "1 rendered, 0 up to date, 0 failed" in rendered.output
    pdf = (folder(setup) / "songbook.pdf").read_text(encoding="utf-8")  # the stand-in's: its inputs
    assert "{title: De Música Ligera}\n{artist: Soda Stereo · missing: not in the library}" in pdf
    cho = (folder(setup) / "songbook.cho").read_text(encoding="utf-8")
    assert "De Música Ligera" not in cho and "斑马" in cho  # an app gets the songs it can play
    page =(folder(setup) / "songbook.html").read_text(encoding="utf-8")
    assert re.search(r'<li class="missing">.*?De Música Ligera.*?Missing: not in the library', page, re.S)

    out = run(setup, "remove", "Campfire", "Soda Stereo - De Música Ligera")  # taken out by its name
    assert out.exit_code == 0, out.output
    assert books(setup)[0].songs == ("宋冬野 - 斑马，斑马",)


@pytest.mark.slow
def test_a_song_the_songbook_lacks_is_still_found_by_a_search_of_the_library(setup, gig):
    moved = run(setup, "move", "Gig", "oasis wonderwal", "1")  # no entry of Gig is it: the library's search
    assert moved.exit_code == 0, moved.output
    assert books(setup)[0].songs[0] == "Oasis - Wonderwall"
    removed = run(setup, "remove", "Gig", "oasis wonderwal")
    assert removed.exit_code == 0 and "Removed Oasis - Wonderwall" in removed.output
    assert books(setup)[0].songs == ("Radiohead - Karma Police", "Radiohead - Karma Police Live")


@pytest.mark.slow
def test_a_change_whose_files_cant_be_made_exits_1_and_stays_made(setup):
    (folder(setup, "Trip") / "songbook.pdf").mkdir(parents=True)  # a synced device put a folder in its place
    made = run(setup, "make", "Trip", "Soda Stereo - De Música Ligera")
    assert made.exit_code == 1 and isinstance(made.exception, SystemExit), made.output
    assert "Some of its files couldn't be made" in made.output
    assert books(setup) == [Songbook("Trip", ("Soda Stereo - De Música Ligera",))]  # songbooks.toml is changed
    assert (folder(setup, "Trip") / "songbook.html").is_file()
    for args in (("add", "Trip", "Muse - Hysteria"), ("move", "Trip", "Muse - Hysteria", "1"),
                 ("remove", "Trip", "Muse - Hysteria")):
        assert run(setup, *args).exit_code == 1, args
    assert books(setup)[0].songs == ("Soda Stereo - De Música Ligera",)
    (folder(setup, "Trip") / "songbook.pdf").rmdir()
    assert run(setup, "add", "Trip", "Muse - Hysteria").exit_code == 0


@pytest.mark.slow
def test_render_renders_one_or_every_songbook(setup):
    _, cfg, _ = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Soda Stereo - De Música Ligera"])
    make_songbook(cfg.library_dir / FILE_NAME, "Picnic", ["宋冬野 - 斑马，斑马"])
    one = run(setup, "render", "picnic")
    assert one.exit_code == 0, one.output
    assert folder(setup, "Picnic").is_dir() and not folder(setup).exists()
    every = run(setup, "render")
    assert every.exit_code == 0 and "1 rendered, 1 up to date, 0 failed" in every.output
    assert "0 rendered, 2 up to date" in run(setup, "render").output
    assert "2 rendered" in run(setup, "render", "--force").output
    assert run(setup, "render", "Weddings").exit_code == 1


@pytest.mark.slow
def test_every_change_holds_caracoles_lock(setup, monkeypatch):
    from caracole import songbook

    _, cfg, _ = setup
    held = []
    real = songbook.render_songbooks

    def spy(*args, **kwargs):
        path = cfg.state_dir / "caracole.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(False)
        except BlockingIOError:
            held.append(True)
        finally:
            os.close(fd)
        return real(*args, **kwargs)

    monkeypatch.setattr(songbook, "render_songbooks", spy)
    for args in (("make", "Campfire", "Muse - Hysteria"), ("add", "Campfire", "Soda Stereo - De Música Ligera"),
                 ("move", "Campfire", "Muse - Hysteria", "2"), ("remove", "Campfire", "Muse - Hysteria"),
                 ("rename", "Campfire", "Picnic"), ("render",), ("delete", "Picnic")):
        assert run(setup, *args).exit_code == 0, args
    assert held == [True] * 7


CHANGES = [("make", "Picnic", "Muse - Hysteria"), ("add", "Campfire", "Soda Stereo - De Música Ligera"),
           ("move", "Campfire", "Muse - Hysteria", "1"), ("remove", "Campfire", "Muse - Hysteria"),
           ("rename", "Campfire", "Picnic"), ("delete", "Campfire"), ("render", "Campfire"), ("render",)]


@pytest.mark.slow
@pytest.mark.parametrize("args", CHANGES, ids=" ".join)
def test_a_change_waits_for_the_nightly_run_as_a_lookup_does_never_for_its_whole_run(setup, args):
    # A songbook asked for now is made now: like `caracole get`, the change announces that it waits (its
    # ticket in caracole.lock.waiting/), so that a nightly run holding the lock hands it over at its next
    # pause, or between two songs, instead of making it wait for the whole run. It still never writes beside
    # the run: until the lock is its own, nothing is written.
    import threading
    import time

    from caracole.commands import _common

    _, cfg, _ = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Muse - Hysteria", "宋冬野 - 斑马，斑马"])
    before = (cfg.library_dir / FILE_NAME).read_bytes()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(cfg.state_dir / "caracole.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)  # the nightly run holds it
    os.write(fd, b"4242 run\n")
    done: list = []
    thread = threading.Thread(target=lambda: done.append(run(setup, *args)), daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not _common.lookups_waiting(cfg) and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert _common.lookups_waiting(cfg), done and done[0].output  # what the nightly run looks for in its pauses
        assert not done and (cfg.library_dir / FILE_NAME).read_bytes() == before  # waiting, not writing beside it
    finally:
        os.close(fd)
    thread.join(15)
    assert done and done[0].exit_code == 0, done and done[0].output
    assert "it lets a lookup go first at its next pause" in done[0].output
    assert not _common.lookups_waiting(cfg)  # it took the lock: its ticket went


HOLDER = r"""
import sys, time
from pathlib import Path
import httpx
from caracole.commands import _common
from caracole.config import load_config
from caracole import db

cfg = load_config(Path(sys.argv[1]), env={})
out = open(sys.argv[2], "w", buffering=1)
_common.transport_for = lambda provider: httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
conn = db.connect(cfg.db_path)
with _common.exclusive(cfg, "run"):
    client = _common.make_client(cfg, conn, "ug", "2026-10-19T03:30:00Z")
    client.get("https://tabs.ultimate-guitar.com/tab/1")
    out.write(f"first {time.time()}\n")
    client.get("https://tabs.ultimate-guitar.com/tab/2")  # after a 4 s pause, handed over meanwhile
    out.write(f"second {time.time()} {client.handoffs}\n")
    client.close()
"""


@pytest.mark.slow
def test_a_songbook_made_during_the_nightly_run_is_made_in_its_next_pause(setup, tmp_path):
    import time

    toml, cfg, _ = setup
    with toml.open("a", encoding="utf-8") as f:
        f.write("[providers.ug]\ndelay = [4, 4]\n")  # the run's pause between two requests to UG
    log = tmp_path / "holder.log"
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(Path(__file__).parents[1] / "src")}
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(toml), str(log)], env=env)
    try:
        deadline = time.time() + 20
        while "first" not in (log.read_text() if log.exists() else "") and time.time() < deadline:
            time.sleep(0.05)
        asked = time.time()
        made = run(setup, "make", "Campfire", "Muse - Hysteria", "Soda Stereo - De Música Ligera")
        finished = time.time()
        assert holder.wait(30) == 0
    finally:
        holder.kill()
    assert made.exit_code == 0, made.output
    assert finished - asked < 3.5  # in the pause the run was in, not after it, let alone after the whole run
    assert (folder(setup) / "songbook.html").is_file()
    _, sent, handoffs = log.read_text().splitlines()[1].split()
    assert float(sent) >= finished + 3.5 and int(handoffs) == 1  # the run waited a whole pause again after it


@pytest.mark.slow
def test_registering_the_command_imports_neither_the_songbooks_nor_the_renderer():
    code = ("import sys; import caracole.cli; "
            "print(sorted(m for m in sys.modules if m in ('caracole.songbook', 'caracole.render', 'caracole.viewer')))")
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.strip() == "[]"


# --- caracole render and the nightly run ---------------------------------------------------------


@pytest.mark.slow
def test_caracole_render_makes_the_songbooks_after_the_sheets(setup):
    toml, cfg, _ = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Soda Stereo - De Música Ligera"])
    result = CliRunner().invoke(build_app(), ["--config", str(toml), "render"], env={"CARACOLE_CJK_FONT": None})
    assert result.exit_code == 0, result.output
    assert "Songbooks: 1 rendered, 0 up to date, 0 failed" in result.output
    assert (folder(setup) / "songbook.pdf").is_file()
    again = CliRunner().invoke(build_app(), ["--config", str(toml), "render"], env={"CARACOLE_CJK_FONT": None})
    assert "Songbooks: 0 rendered, 1 up to date, 0 failed" in again.output


@pytest.mark.slow
def test_a_songbook_file_that_cant_be_written_fails_caracole_render_without_a_traceback(setup):
    toml, cfg, _ = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Trip", ["Soda Stereo - De Música Ligera"])
    make_songbook(cfg.library_dir / FILE_NAME, "Weekend", ["Soda Stereo - De Música Ligera"])
    (folder(setup, "Trip") / "songbook.pdf").mkdir(parents=True)  # a synced device put a folder in its place
    result = CliRunner().invoke(build_app(), ["--config", str(toml), "render"], env={"CARACOLE_CJK_FONT": None})
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit), result.output
    assert "Traceback" not in result.output
    assert "songbook Trip: no songbook.pdf: [Errno 21] Is a directory" in result.output  # the warning
    assert "Songbooks: 1 rendered, 0 up to date, 1 failed" in result.output
    assert (folder(setup, "Weekend") / "songbook.pdf").is_file()
    assert (cfg.library_dir / "index.html").is_file()  # the pages, written all the same


def test_caracole_render_says_nothing_of_songbooks_without_any(setup):
    toml, _, _ = setup
    result = CliRunner().invoke(build_app(), ["--config", str(toml), "render"], env={"CARACOLE_CJK_FONT": None})
    assert result.exit_code == 0 and "Songbooks" not in result.output


@pytest.mark.slow
def test_a_broken_songbooks_file_costs_caracole_render_no_pdf(setup):
    toml, cfg, _ = setup
    (cfg.library_dir / FILE_NAME).write_text("[Campfire\n", encoding="utf-8")
    result = CliRunner().invoke(build_app(), ["--config", str(toml), "render", "--force"],
                                env={"CARACOLE_CJK_FONT": None})
    assert result.exit_code == 1
    assert "2 rendered" in result.output and "Songbooks: songbooks.toml can't be read" in result.output


@pytest.mark.slow
def test_the_nightly_render_step_makes_the_songbooks(setup):
    from caracole.notify import Notifier
    from caracole.pipeline import Services, default_steps, run_pipeline

    _, cfg, conn = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Soda Stereo - De Música Ligera", "Muse - Hysteria"])
    steps = [s for s in default_steps() if s.name == "render"]
    services = Services(clients={}, spotify=None, notifier=Notifier(None, None))
    report = run_pipeline(cfg, conn=conn, services=services, steps=steps)
    assert report.ok, report.errors
    result = report.results["render"]
    assert "1 songbook made" in result.done
    assert "songbooks: 1 rendered" in result.status
    assert (folder(setup) / "songbook.pdf").is_file()


@pytest.mark.slow
def test_a_songbook_file_that_cant_be_written_costs_the_nightly_render_step_nothing_else(setup):
    from caracole.notify import Notifier
    from caracole.pipeline import Services, default_steps, run_pipeline

    _, cfg, conn = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Trip", ["Soda Stereo - De Música Ligera"])
    (folder(setup, "Trip") / "songbook.pdf").mkdir(parents=True)
    steps = [s for s in default_steps() if s.name == "render"]
    services = Services(clients={}, spotify=None, notifier=Notifier(None, None))
    report = run_pipeline(cfg, conn=conn, services=services, steps=steps)
    assert report.ok, report.errors  # no crash: the sheets' counts are kept
    problems = " ".join(p.text for p in report.results["render"].problems)
    assert "couldn't be made in full (Trip)" in problems


def test_the_nightly_render_step_reports_a_broken_songbooks_file(setup):
    from caracole.notify import Notifier
    from caracole.pipeline import Services, default_steps, run_pipeline

    _, cfg, conn = setup
    (cfg.library_dir / FILE_NAME).write_text("[Campfire\n", encoding="utf-8")
    steps = [s for s in default_steps() if s.name == "render"]
    services = Services(clients={}, spotify=None, notifier=Notifier(None, None))
    report = run_pipeline(cfg, conn=conn, services=services, steps=steps)
    assert report.ok, report.errors  # the PDFs were made all the same
    problems = " ".join(p.text for p in report.results["render"].problems)
    assert "songbooks.toml" in problems and "line 1" in problems
