"""``caracole peer export`` and ``caracole peer import``, through the CLI: a library written to a ``.caracole`` file
and another library synced with it, as if the caracole that wrote it were there (peer_file.py, peer_import.py); and
``caracole peer sync --parts``, with the answers an import remembered, against another library's caracole serve (a
WebApp, in this process), as tests/test_commands_peer.py runs it."""

from __future__ import annotations

import itertools
import json
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from caracole import db, index_transfer, peer_file, peer_import, site_index
from caracole.commands.peer import CONFLICT_LEFT, LEFT, PEER_IMPORT_STAGES
from caracole import peer_sync as sync
from caracole.config import load_config
from caracole.get import read_progress_line
from caracole.library import song_dir
from caracole.overrides import add_version, load_overrides, override_key
from caracole.songbook import load_songbooks, make_songbook, songbooks_file
from caracole.songs import find_song, removed_song
from caracole.wanted import find_wanted
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from test_commands_peer import CREEP, InProcess, Side, run
from test_web_app import ALLOWED, HOST, Recorder, post

def write_config(root: Path, name: str) -> Path:
    path = root / "caracole.toml"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(f'name = "{name}"\nlibrary_dir = "{root / "lib"}"\nmusic_dir = "{root / "music"}"\n'
                    f'state_dir = "{root / "state"}"\ncache_dir = "{root / "cache"}"\n', encoding="utf-8")
    return path


class Lib:
    """A library of its own, called ``name`` (caracole.toml's), with its caracole serve: test_commands_peer's
    ``Side``, named."""

    def __init__(self, root: Path, name: str, runner=None):
        self.root = root
        self.cfg = load_config(write_config(root, name), env={"HOME": str(root / "home")})
        self.conn = db.connect(self.cfg.db_path)
        if isinstance(runner, InProcess):
            runner.side = self
        self.app = WebApp(self.cfg, JobQueue(runner or Recorder(), limit=3), allowed=ALLOWED, csrf="tok")

    song = Side.song
    units = Side.units

    def id(self) -> str:
        return sync.own_id(self.conn)

    def songs(self) -> set[str]:
        return {key for (key,) in self.conn.execute("SELECT key FROM songs")}


@pytest.fixture
def libraries(tmp_path, monkeypatch):
    """Desk and Studio, each with its caracole serve; ``serving[0]`` is the one ``caracole peer`` asks over HTTP
    (Desk), which runs what it queued as it is asked how a job goes; the songs taken are rendered by a recorder; and
    each ``caracole peer`` command's clock a second after the last one's."""
    desk, studio = Lib(tmp_path / "desk", "Desk", InProcess()), Lib(tmp_path / "studio", "Studio", InProcess())
    serving = [desk]

    def handler(request: httpx.Request) -> httpx.Response:
        there = serving[0]
        if request.url.path.startswith("/api/jobs/"):
            there.app.queue.run_pending()
        answer = WebApp.finish(there.app.handle(Request(request.method, request.url.raw_path.decode(),
                                                        dict(request.headers), request.content)))
        return httpx.Response(answer.status, headers=answer.headers, content=answer.body)

    rendered = []
    ticks, start = itertools.count(), datetime.now(UTC).replace(microsecond=0)
    # each command's clock a second on from the last's, so that a file exported after an import is newer than it
    monkeypatch.setattr("caracole.commands.peer.utcnow", lambda: start + timedelta(seconds=next(ticks)))
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: rendered.append(
        set(kw.get("song_ids") or ())))
    yield desk, studio, rendered
    desk.conn.close()
    studio.conn.close()


@pytest.fixture
def in_utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def exported(lib: Lib, path: Path, *args: str) -> Path:
    result = run(lib, "peer", "export", *args, str(path))
    assert result.exit_code == 0, result.output
    return path


def events(output: str) -> list[dict]:
    return [e for e in map(read_progress_line, output.splitlines()) if e is not None]


def desk_with_a_songbook(desk: Lib) -> None:
    desk.song("Radiohead", "Creep")
    desk.song("Oasis", "Wonderwall", sheet=b"[Em]Today", version=None)
    make_songbook(songbooks_file(desk.cfg.library_dir), "Campfire", [CREEP])


# --- peer export ----------------------------------------------------------------------------------------------------


def test_an_export_says_what_it_wrote_and_writes_over_nothing(libraries, tmp_path):
    desk, _, _ = libraries
    desk_with_a_songbook(desk)
    result = run(desk, "peer", "export", str(tmp_path / "d.caracole"))
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Exported Desk: 2 songs, 1 songbook, ") and str(tmp_path / "d.caracole") in \
        result.output
    assert "No pages in it" in result.output  # no library page written yet
    manifest = json.loads(zipfile.ZipFile(tmp_path / "d.caracole").read("caracole.json"))
    assert manifest["parts"] == ["library", "songbooks"] and manifest["id"] == desk.id()
    again = run(desk, "peer", "export", str(tmp_path / "d.caracole"))
    assert again.exit_code == 2 and "already exists" in again.output
    assert run(desk, "peer", "export", "--parts", "library,lyrics", str(tmp_path / "e.caracole")).exit_code == 2
    assert not (tmp_path / "e.caracole").exists()


def test_an_export_into_a_folder_is_named_for_the_library_and_the_day(libraries, tmp_path):
    desk, _, _ = libraries
    desk.song()
    folder = tmp_path / "out"
    folder.mkdir()
    assert run(desk, "peer", "export", str(folder)).exit_code == 0
    [made] = list(folder.iterdir())
    assert made.name == peer_file.file_name("Desk", datetime.now().astimezone())


def test_an_export_takes_no_lock_and_waits_for_none(libraries, tmp_path):
    from caracole.commands._common import exclusive

    desk, _, _ = libraries
    desk.song()
    with exclusive(desk.cfg, "the nightly run"):
        result = run(desk, "peer", "export", str(tmp_path / "d.caracole"))
    assert result.exit_code == 0, result.output


def test_an_export_with_the_library_page_written_holds_its_pages(libraries, tmp_path):
    from caracole.commands._common import write_pages
    from caracole.overrides import Overrides

    desk, _, _ = libraries
    desk.song()
    write_pages(desk.conn, desk.cfg, Overrides(), datetime(2026, 11, 3, tzinfo=UTC))
    result = run(desk, "peer", "export", str(tmp_path / "d.caracole"))
    assert result.exit_code == 0 and "No pages" not in result.output, result.output
    with peer_file.FileSource(peer_file.read_file(tmp_path / "d.caracole"), None, tmp_path) as src:
        assert [e["path"] for e in src.pages()["files"]][0] == "index.html"


# --- peer import ----------------------------------------------------------------------------------------------------


def test_an_export_imported_into_another_library_brings_its_songs_files_and_songbooks(libraries, tmp_path):
    desk, studio, rendered = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")
    out = run(studio, "peer", "import", "--yes", str(f))
    assert out.exit_code == 0, out.output
    assert "From Desk's file: Took 3 changes; 2 songs rendered again." in out.output
    assert studio.units() == desk.units()
    creep = find_song(studio.conn, "radiohead/creep")
    assert (song_dir(studio.cfg.library_dir, creep) / "sheet.txt").read_bytes() == b"[Am]Creep"
    assert find_wanted(studio.cfg.wanted_file, "Oasis", "Wonderwall") is not None
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    assert [b.texts for b in load_songbooks(songbooks_file(studio.cfg.library_dir))] == [(CREEP,)]
    assert len(rendered) == 1 and len(rendered[0]) == 2
    base = sync.base_of(studio.conn, desk.id())
    made = peer_file.read_file(f).made
    assert {when for _, when in base.values()} == {made} and set(base) == set(desk.units())
    assert list((studio.cfg.state_dir / "backups").iterdir())  # backed up first
    assert sync.base_of(desk.conn, studio.id()) is None  # a file takes nothing back, and changes nothing there


def test_a_second_import_of_the_same_file_is_refused_as_no_newer(libraries, tmp_path, in_utc):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")
    assert run(studio, "peer", "import", "--yes", str(f)).exit_code == 0
    before = db.kv_get(studio.conn, sync.BASE_KEY + desk.id())
    again = run(studio, "peer", "import", "--yes", str(f))
    day = datetime.now(UTC).strftime("%d/%m/%y")
    assert again.exit_code == 2 and f"Nothing in this file is newer than your sync with Desk on {day}." in again.output
    assert db.kv_get(studio.conn, sync.BASE_KEY + desk.id()) == before


def test_after_the_songbooks_alone_the_rest_of_the_same_file_is_still_taken(libraries, tmp_path, in_utc):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)  # Creep (in songbook Campfire) and Wonderwall
    f = exported(desk, tmp_path / "d.caracole")
    out = run(studio, "peer", "import", "--yes", "--parts", "songbooks", str(f))
    assert out.exit_code == 0, out.output
    assert studio.songs() == {"radiohead/creep"}  # the songbook's song came along, Wonderwall was not asked for
    again = run(studio, "peer", "import", "--yes", "--parts", "library", str(f))
    assert again.exit_code == 0, again.output
    assert "oasis/wonderwall" in studio.songs()
    third = run(studio, "peer", "import", "--yes", str(f))  # and now nothing in it is left to take
    assert third.exit_code == 2 and "Nothing in this file is newer than your sync with Desk" in third.output


def test_a_unit_an_import_left_is_taken_from_the_same_file_next_time(libraries, tmp_path, in_utc, monkeypatch):
    from caracole import overrides

    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")
    real = overrides.put_song_entries

    def failing(path, display, entries):  # overrides.toml can't be written for Wonderwall, this once
        if "Wonderwall" in display:
            raise overrides.OverridesError("overrides.toml is busy")
        return real(path, display, entries)

    monkeypatch.setattr(overrides, "put_song_entries", failing)
    out = run(studio, "peer", "import", "--yes", str(f))
    assert out.exit_code == 1 and f"{LEFT}: Oasis - Wonderwall: " in out.output
    monkeypatch.setattr(overrides, "put_song_entries", real)
    again = run(studio, "peer", "import", "--yes", str(f))
    assert again.exit_code == 0, again.output
    assert "oasis/wonderwall" in studio.songs()


def test_a_files_indexes_with_no_kv_table_are_not_merged_and_said_so(libraries, tmp_path):
    import sqlite3

    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "i.caracole", "--parts", "library,songbooks,indexes")
    odd = tmp_path / "odd.sqlite"
    with zipfile.ZipFile(f) as z:
        odd.write_bytes(z.read(peer_file.INDEXES))
    made = sqlite3.connect(odd)
    made.execute("DROP TABLE kv")
    made.commit()
    made.close()
    g = tmp_path / "j.caracole"
    with zipfile.ZipFile(f) as z, zipfile.ZipFile(g, "w") as out:
        for info in z.infolist():
            out.writestr(info, odd.read_bytes() if info.filename == peer_file.INDEXES else z.read(info))
    result = run(studio, "peer", "import", "--yes", "--progress", str(g))
    assert result.exit_code == 1 and not isinstance(result.exception, sqlite3.Error), result.output
    index = [e for e in events(result.output) if e.get("stage") == "index"]
    assert index[-1]["state"] == "failed" and "kv has the columns (none)" in index[-1]["detail"]
    assert '"event":"report"' in result.output
    assert "radiohead/creep" in studio.songs()


def test_a_librarys_own_export_is_refused_and_changes_nothing(libraries, tmp_path):
    desk, _, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")
    before = desk.units()
    out = run(desk, "peer", "import", "--yes", "--progress", str(f))
    assert out.exit_code == 2 and "this library's own export" in out.output
    assert [(e["stage"], e["state"]) for e in events(out.output)] == [("check", "running"), ("check", "failed")]
    assert desk.units() == before and db.kv_get(desk.conn, sync.BASE_KEY + desk.id()) is None
    assert not (desk.cfg.state_dir / "backups").exists()


def test_a_file_of_a_caracole_whose_song_keys_changed_is_refused_and_takes_nothing(libraries, tmp_path,
                                                                                     monkeypatch):
    from caracole import normalize, songs

    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    assert run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "d.caracole"))).exit_code == 0
    # Desk is upgraded: its normalizer keys Creep otherwise (a KEY_VERSION bump), it re-keys its songs, and exports.
    with monkeypatch.context() as upgraded:
        old = songs.identity_key
        upgraded.setattr(songs, "identity_key", lambda a, t: old(a, t) + "-v3" if t == "Creep" else old(a, t))
        upgraded.setattr(normalize, "KEY_VERSION", normalize.KEY_VERSION + 1)
        songs.rekey_songs(desk.conn)
        f = exported(desk, tmp_path / "e.caracole")
    before, base, backups = studio.units(), db.kv_get(studio.conn, sync.BASE_KEY + desk.id()), sorted(
        (studio.cfg.state_dir / "backups").iterdir())
    out = run(studio, "peer", "import", "--yes", "--progress", str(f))
    assert out.exit_code == 2 and peer_file.OTHER_KEYS in out.output, out.output
    assert [(e["stage"], e["state"]) for e in events(out.output)] == [("check", "running"), ("check", "failed")]
    assert find_song(studio.conn, "radiohead/creep") is not None and removed_song(studio.conn, "radiohead/creep") is None
    assert studio.units() == before and db.kv_get(studio.conn, sync.BASE_KEY + desk.id()) == base
    assert sorted((studio.cfg.state_dir / "backups").iterdir()) == backups


def test_something_that_isnt_a_file_caracole_exported_is_refused(libraries, tmp_path):
    _, studio, _ = libraries
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    out = run(studio, "peer", "import", "--yes", str(tmp_path / "notes.txt"))
    assert out.exit_code == 2 and "isn't a file caracole exported" in out.output
    gone = run(studio, "peer", "import", "--yes", str(tmp_path / "nothing.caracole"))
    assert gone.exit_code == 2 and "No file at" in gone.output


def test_a_file_cut_short_is_refused_whole_before_anything_is_taken(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")
    data = bytearray(f.read_bytes())
    at = data.find(b"[Em]Today")
    data[at] ^= 0xFF  # a CRC error in a kept file
    (tmp_path / "bad.caracole").write_bytes(bytes(data))
    out = run(studio, "peer", "import", "--yes", str(tmp_path / "bad.caracole"))
    assert out.exit_code == 2 and "can't be read whole" in out.output
    assert studio.songs() == set() and not (studio.cfg.state_dir / "backups").exists()


def test_a_songbooks_only_file_removes_no_song_it_doesnt_hold(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    # Studio synced Desk's whole library before, then Desk removed Wonderwall: a file of the songbooks alone
    # says nothing of it, so Studio keeps it.
    assert run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "all.caracole"))).exit_code == 0
    from caracole.removal import plan_removal, remove_song

    remove_song(desk.conn, desk.cfg, plan_removal(desk.conn, desk.cfg, find_song(desk.conn, "oasis/wonderwall")))
    make_songbook(songbooks_file(desk.cfg.library_dir), "Practice", [CREEP])
    before = studio.songs()
    base_before = sync.base_of(studio.conn, desk.id())
    f = exported(desk, tmp_path / "s.caracole", "--parts", "songbooks")
    out = run(studio, "peer", "import", "--yes", str(f))
    assert out.exit_code == 0, out.output
    assert studio.songs() >= before and "oasis/wonderwall" in studio.songs()
    assert sorted(b.name for b in load_songbooks(songbooks_file(studio.cfg.library_dir))) == ["Campfire", "Practice"]
    base = sync.base_of(studio.conn, desk.id())
    for unit in ("song/oasis/wonderwall", "removed/oasis/wonderwall"):  # the file said nothing of either
        assert base.get(unit) == base_before.get(unit)
    assert base["songbook/practice"][0] == desk.units()["songbook/practice"].digest
    # a file of the whole library then says the song was removed there since: removed here too
    out = run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "later.caracole")))
    assert out.exit_code == 0, out.output
    assert find_song(studio.conn, "oasis/wonderwall") is None
    assert removed_song(studio.conn, "oasis/wonderwall") is not None


def test_a_song_the_files_library_removed_since_the_last_sync_is_removed_here(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    assert run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "a.caracole"))).exit_code == 0
    from caracole.removal import plan_removal, remove_song

    remove_song(desk.conn, desk.cfg, plan_removal(desk.conn, desk.cfg, find_song(desk.conn, "oasis/wonderwall")))
    out = run(studio, "peer", "import", "--yes", "--progress", str(exported(desk, tmp_path / "b.caracole")))
    assert out.exit_code == 0, out.output
    assert sorted((e["id"], e["outcome"]) for e in events(out.output) if e.get("event") == "unit") == [
        ("removed/oasis/wonderwall", "taken"), ("song/oasis/wonderwall", "taken")]
    assert find_song(studio.conn, "oasis/wonderwall") is None
    assert find_wanted(studio.cfg.wanted_file, "Oasis", "Wonderwall") is None


def test_a_conflict_kept_here_is_remembered_and_not_asked_again_at_the_next_import(libraries, tmp_path):
    desk, studio, _ = libraries
    desk.song(version="key=Am&capo=0")
    studio.song(version="key=Gm&capo=0")
    unit = "song/radiohead/creep"
    first = exported(desk, tmp_path / "1.caracole")
    out = run(studio, "peer", "import", "--yes", f"--choose=here:{unit}", str(first))
    assert out.exit_code == 0, out.output
    made = peer_file.read_file(first).made
    assert sync.kept_of(studio.conn, desk.id()) == {unit: (studio.units()[unit].digest, desk.units()[unit].digest,
                                                           made)}
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    second = exported(desk, tmp_path / "2.caracole")
    out = run(studio, "peer", "import", "--yes", "--progress", str(second))
    assert out.exit_code == 0, out.output
    assert [e for e in events(out.output) if e.get("event") == "unit"] == []
    assert "Nothing to take. 1 kept as they are here" in out.output
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    # a change on the file's side after the answer, which still lacks the version kept, is a conflict again: left
    # unasked, the version kept here as it was, until the owner takes the file's
    add_version(desk.cfg.overrides_file, CREEP, "key=Em&capo=0")
    third = exported(desk, tmp_path / "3.caracole")
    out = run(studio, "peer", "import", "--yes", str(third))
    assert out.exit_code == 0, out.output
    assert f"{LEFT}: Radiohead - Creep: {CONFLICT_LEFT}" in out.output
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    out = run(studio, "peer", "import", "--yes", f"--choose=there:{unit}", str(third))
    assert out.exit_code == 0, out.output
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Em&capo=0"}
    assert sync.kept_of(studio.conn, desk.id()) == {}


def killed_rendering(conn, cfg, overrides, **kw):
    """``render_all`` raising, as a render's bug does, or as caracole serve's stop kills its child mid-render."""
    raise RuntimeError("killed while rendering")


def test_an_import_killed_after_its_take_keeps_what_it_took_agreed_and_its_file_still_offers_the_rest(
        libraries, tmp_path, monkeypatch):
    desk, studio, _ = libraries
    desk.song(version="key=Am&capo=0")  # Creep, chorded otherwise on each side: kept here as chosen
    studio.song(version="key=Gm&capo=0")
    desk.song("Oasis", "Wonderwall", sheet=b"[Em]Today", version=None)  # in the file alone: taken
    creep, wonderwall = "song/radiohead/creep", "song/oasis/wonderwall"
    f = exported(desk, tmp_path / "d.caracole")
    made = peer_file.read_file(f).made
    monkeypatch.setattr("caracole.render.render_all", killed_rendering)
    out = run(studio, "peer", "import", "--yes", f"--choose=here:{creep}", str(f))
    assert out.exit_code == 1 and isinstance(out.exception, RuntimeError)
    # What it took is agreed at the file's made; the answer "keep mine", remembered at the agree, died with it.
    assert sync.base_of(studio.conn, desk.id()) == {wonderwall: (desk.units()[wonderwall].digest, made)}
    assert sync.kept_of(studio.conn, desk.id()) == {}

    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: None)
    again = run(studio, "peer", "import", "--yes", "--progress", f"--choose=here:{creep}", str(f))
    assert again.exit_code == 0, again.output  # still offered: its Creep is a conflict again, never no newer
    assert [e for e in events(again.output) if e.get("event") == "unit"] == []  # Wonderwall isn't taken again
    assert sync.kept_of(studio.conn, desk.id()) == {creep: (studio.units()[creep].digest, desk.units()[creep].digest,
                                                            made)}


def test_a_file_an_import_killed_after_its_take_took_whole_is_no_newer_the_next_time(libraries, tmp_path, in_utc,
                                                                                      monkeypatch):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")
    monkeypatch.setattr("caracole.render.render_all", killed_rendering)
    out = run(studio, "peer", "import", "--yes", str(f))
    assert out.exit_code == 1 and studio.units() == desk.units()
    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: None)
    again = run(studio, "peer", "import", "--yes", str(f))
    day = datetime.now(UTC).strftime("%d/%m/%y")
    assert again.exit_code == 2 and f"Nothing in this file is newer than your sync with Desk on {day}." in again.output


def test_a_conflict_neither_chosen_nor_preferred_is_left_and_named(libraries, tmp_path):
    desk, studio, _ = libraries
    desk.song(version="key=Am&capo=0")
    studio.song(version="key=Gm&capo=0")
    out = run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "d.caracole")))
    assert out.exit_code == 0, out.output
    assert f"{LEFT}: Radiohead - Creep: {CONFLICT_LEFT}" in out.output
    assert sync.kept_of(studio.conn, desk.id()) == {}
    out = run(studio, "peer", "import", "--yes", "--prefer", "there", str(exported(desk, tmp_path / "e.caracole")))
    assert out.exit_code == 0, out.output
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Am&capo=0"}


def test_with_progress_an_import_says_its_stages_its_units_and_a_report(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    out = run(studio, "peer", "import", "--yes", "--progress", str(exported(desk, tmp_path / "d.caracole")))
    assert out.exit_code == 0, out.output
    lines = events(out.output)
    assert [line["stage"] for line in lines if line.get("state") == "running"] == ["check", "take", "render", "agree"]
    assert [(line["stage"], line["state"]) for line in lines if "stage" in line][-1] == ("index", "skipped")
    assert sorted(line["id"] for line in lines if line.get("event") == "unit") == [
        "song/oasis/wonderwall", "song/radiohead/creep", "songbook/campfire"]
    [report] = [line["report"] for line in lines if line.get("event") == "report"]
    assert report["with"] == {"name": "Desk", "kind": "file", "address": None} and report["indexes"] == []
    assert report["parts"] == ["library", "songbooks"] and sync_stamp(report["at"])
    assert [name for name, _ in PEER_IMPORT_STAGES] == ["check", "take", "render", "agree", "index"]


def test_an_imports_render_stage_says_how_many_of_the_songs_taken_it_has_reached(libraries, tmp_path, monkeypatch):
    # As a take's: "1 of 2 songs" while the first renders, which the Sync sheet and the request's line show.
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)

    def render_all(conn, cfg, overrides, *, song_ids=(), on_song=None, **kw):
        assert on_song is not None
        for n, _song_id in enumerate(sorted(song_ids), 1):
            on_song(n, len(song_ids), None)

    monkeypatch.setattr("caracole.render.render_all", render_all)
    out = run(studio, "peer", "import", "--yes", "--progress", str(exported(desk, tmp_path / "d.caracole")))
    assert out.exit_code == 0, out.output
    assert [(e["state"], e["detail"]) for e in events(out.output) if e.get("stage") == "render"] == [
        ("running", ""), ("running", "1 of 2 songs"), ("running", "2 of 2 songs"), ("done", "")]


def sync_stamp(text: str) -> bool:
    from caracole import stamps

    return stamps.parse(text) is not None and text.endswith("Z")


def test_a_stale_comparison_is_refused_before_any_change(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")
    out = run(studio, "peer", "import", "--yes", "--compared", "0" * 64, str(f))
    assert out.exit_code == 1 and "changed since that comparison" in out.output
    assert studio.songs() == set()
    unknown = run(studio, "peer", "import", "--yes", "--choose=here:song/no/such", str(f))
    assert unknown.exit_code == 2 and "don't hold differently" in unknown.output


def gtptabs_index(lib: Lib, at: datetime, locs: list[str]) -> None:
    from caracole import gtptabs_fetch

    site = gtptabs_fetch.SITE
    site_index._store(lib.conn, site, "sitemap-tabs-1.xml", [site.row(loc) for loc in locs],
                      {"etag": '"1"', "last_modified": None}, at)


def test_an_import_with_indexes_merges_them_and_reports_each_site(libraries, tmp_path):
    desk, studio, _ = libraries
    desk.song()
    at = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
    gtptabs_index(desk, at, ["https://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/tabs/2/blur/beetlebum.html"])
    f = exported(desk, tmp_path / "i.caracole", "--parts", "library,songbooks,indexes")
    out = run(studio, "peer", "import", "--yes", "--progress", str(f))
    assert out.exit_code == 0, out.output
    assert {r[0] for r in studio.conn.execute("SELECT path FROM gtptabs_index")} == {
        "tabs/2/blur.html", "tabs/2/blur/beetlebum.html"}
    [report] = [line["report"] for line in events(out.output) if line.get("event") == "report"]
    assert report["parts"] == ["library", "songbooks", "indexes"]
    assert report["indexes"] == [{"site": "gtptabs", "title": "gtptabs.com", "direction": "taken", "before": 0,
                                  "after": 2, "new": 2, "checked": 2, "read": "2026-11-02T08:00:00Z"}]
    said = [e["detail"] for e in events(out.output) if e.get("stage") == "index" and e["state"] == "running"]
    assert said[:4] == ["", "Copying the file's indexes out", "Comparing with this database's indexes",
                        "Backing up the database first"]
    assert "gtptabs.com · 1 sitemap" in said
    assert not list((studio.cfg.cache_dir / "peer").iterdir())  # the indexes' copy gone
    # --parts without the indexes leaves them
    other = Lib(tmp_path / "other", "Other")
    out = run(other, "peer", "import", "--yes", "--progress", "--parts", "library", str(f))
    assert ("index", "skipped") in [(e["stage"], e["state"]) for e in events(out.output) if "stage" in e]
    assert other.conn.execute("SELECT COUNT(*) FROM gtptabs_index").fetchone()[0] == 0
    other.conn.close()


def test_an_import_over_a_site_this_side_holds_says_what_is_newer_in_the_file(libraries, tmp_path):
    desk, studio, _ = libraries
    desk.song()
    gtptabs_index(desk, datetime(2026, 11, 2, 8, 0, tzinfo=UTC), ["https://gtptabs.com/tabs/2/blur.html",
                                                                  "https://gtptabs.com/tabs/2/blur/beetlebum.html"])
    gtptabs_index(studio, datetime(2026, 10, 2, 8, 0, tzinfo=UTC), ["https://gtptabs.com/tabs/2/blur.html"])
    f = exported(desk, tmp_path / "i.caracole", "--parts", "library,songbooks,indexes")
    out = run(studio, "peer", "import", "--yes", "--progress", str(f))
    assert out.exit_code == 0, out.output
    said = [e["detail"] for e in events(out.output) if e.get("stage") == "index" and e["state"] == "running"]
    assert "gtptabs.com · 1 sitemap newer in the file" in said and "gtptabs.com · 1 sitemap" not in said
    [report] = [line["report"] for line in events(out.output) if line.get("event") == "report"]
    assert [(e["before"], e["after"], e["new"], e["checked"]) for e in report["indexes"]] == [(1, 2, 1, 2)]


def test_indexes_that_cant_be_merged_say_so_and_the_import_exits_1(libraries, tmp_path, monkeypatch):
    desk, studio, _ = libraries
    desk.song()
    gtptabs_index(desk, datetime(2026, 11, 2, 8, 0, tzinfo=UTC), ["https://gtptabs.com/tabs/3/oasis.html"])
    f = exported(desk, tmp_path / "i.caracole", "--parts", "library,songbooks,indexes")

    def refused(*args, **kw):
        raise index_transfer.TransferError("The disk is full")  # a refusal's words begin with a capital, as most do

    monkeypatch.setattr(index_transfer, "merge", refused)
    out = run(studio, "peer", "import", "--yes", "--progress", str(f))
    # Appended mid-sentence, its first letter lower.
    assert out.exit_code == 1 and "The file's indexes weren't merged: the disk is full" in out.output
    assert ("index", "failed") in [(e["stage"], e["state"]) for e in events(out.output) if "stage" in e]
    [report] = [e["report"] for e in events(out.output) if e.get("event") == "report"]
    assert report["indexes"] == [] and studio.units() == desk.units()  # its units taken all the same


def test_the_indexes_alone_asked_of_a_whole_file_agree_on_nothing_so_its_library_comes_later(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    gtptabs_index(desk, datetime(2026, 11, 2, 8, 0, tzinfo=UTC), ["https://gtptabs.com/tabs/3/oasis.html"])
    f = exported(desk, tmp_path / "i.caracole", "--parts", "library,songbooks,indexes")
    out = run(studio, "peer", "import", "--yes", "--progress", "--parts", "indexes", str(f))
    assert out.exit_code == 0, out.output
    assert ("agree", "skipped") in [(e["stage"], e["state"]) for e in events(out.output) if "stage" in e]
    assert studio.songs() == set() and sync.base_of(studio.conn, desk.id()) is None
    assert studio.conn.execute("SELECT COUNT(*) FROM gtptabs_index").fetchone()[0] == 1
    out = run(studio, "peer", "import", "--yes", "--parts", "library,songbooks", str(f))
    assert out.exit_code == 0, out.output
    assert studio.units() == desk.units()


def test_an_import_that_cant_back_up_first_takes_nothing_and_still_reports(libraries, tmp_path, monkeypatch):
    from caracole import backup

    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    f = exported(desk, tmp_path / "d.caracole")

    def full(*args, **kw):
        raise backup.BackupError("no room")

    monkeypatch.setattr(backup, "make", full)
    out = run(studio, "peer", "import", "--yes", "--progress", str(f))
    assert out.exit_code == 1 and "Nothing taken: couldn't back up the database first: no room" in out.output
    [report] = [e["report"] for e in events(out.output) if e.get("event") == "report"]
    assert report["with"]["name"] == "Desk" and report["indexes"] == []
    assert studio.songs() == set() and sync.base_of(studio.conn, desk.id()) is None


def test_an_index_file_is_merged_and_records_no_agreement(libraries, tmp_path):
    desk, studio, _ = libraries
    gtptabs_index(desk, datetime(2026, 11, 2, 8, 0, tzinfo=UTC), ["https://gtptabs.com/tabs/3/oasis.html"])
    index_transfer.export(desk.conn, tmp_path / "i.sqlite", now=datetime(2026, 11, 3, tzinfo=UTC))
    out = run(studio, "peer", "import", "--yes", "--progress", str(tmp_path / "i.sqlite"))
    assert out.exit_code == 0, out.output
    assert [r[0] for r in studio.conn.execute("SELECT path FROM gtptabs_index")] == ["tabs/3/oasis.html"]
    assert [(e["stage"], e["state"]) for e in events(out.output) if "stage" in e and e["stage"] != "index"] == [
        ("check", "running"), ("check", "done"), ("take", "skipped"), ("render", "skipped"), ("agree", "skipped")]
    # The merge says how far it has got as the index stage's running detail, which the Sync sheet shows.
    assert [(e["state"], e["detail"]) for e in events(out.output) if e.get("stage") == "index"] == [
        ("running", ""), ("running", "Comparing with this database's indexes"),
        ("running", "Backing up the database first"), ("running", "Ultimate Guitar"), ("running", "LaCuerda"),
        ("running", "gtptabs.com"), ("running", "gtptabs.com · 1 sitemap"), ("running", "MuseScore"),
        ("running", "harptabs.com"), ("running", "gametabs.net"), ("done", "1 index merged")]
    [report] = [e["report"] for e in events(out.output) if e.get("event") == "report"]
    assert report["with"] == {"name": "i.sqlite", "kind": "file", "address": None}
    assert report["parts"] == ["indexes"] and [i["site"] for i in report["indexes"]] == ["gtptabs"]
    assert not [k for (k,) in studio.conn.execute("SELECT key FROM kv WHERE key LIKE 'sync:base:%'")]
    assert (tmp_path / "i.sqlite").exists()  # a file given is the owner's: never deleted


def stage(lib: Lib, data: bytes, name: str = "d.caracole") -> Path:
    state = lib.cfg.state_dir
    import_id = peer_import.open_import(state, size=len(data), name=name)
    at = 0
    while at < len(data):
        at = peer_import.add_part(state, import_id, at, data[at:at + 1000])
    return state / "peer" / f"import-{import_id}"


def test_a_staged_folder_is_taken_then_deleted(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    folder = stage(studio, exported(desk, tmp_path / "d.caracole").read_bytes())
    out = run(studio, "peer", "import", "--yes", "--progress", str(folder))
    assert out.exit_code == 0, out.output
    assert studio.units() == desk.units() and not folder.exists()
    [report] = [e["report"] for e in events(out.output) if e.get("event") == "report"]
    assert report["with"]["name"] == "Desk"


def test_a_staged_index_export_goes_by_the_name_it_was_sent_under_and_is_deleted(libraries, tmp_path):
    desk, studio, _ = libraries
    gtptabs_index(desk, datetime(2026, 11, 2, 8, 0, tzinfo=UTC), ["https://gtptabs.com/tabs/3/oasis.html"])
    index_transfer.export(desk.conn, tmp_path / "i.sqlite", now=datetime(2026, 11, 3, tzinfo=UTC))
    folder = stage(studio, (tmp_path / "i.sqlite").read_bytes(), "phone-indexes.sqlite")
    out = run(studio, "peer", "import", "--yes", "--progress", str(folder))
    assert out.exit_code == 0, out.output
    [report] = [e["report"] for e in events(out.output) if e.get("event") == "report"]
    assert report["with"]["name"] == "phone-indexes.sqlite" and not folder.exists()


def compared_in_the_tab(lib: Lib, folder: Path) -> str:
    """The hash the Sync tab's comparison of the file staged in ``folder`` names (POST /sync/import/compare's)."""
    from caracole.commands.peer import _library

    file = peer_file.read_file(folder / peer_import.FILE)
    overrides, books = _library(lib.cfg)
    with peer_file.FileSource(file, lib.conn, lib.cfg.library_dir) as source:
        return sync.compared_hash(peer_file.compare_file(lib.conn, overrides, books, file, source).found)


def staged_long_ago(folder: Path) -> None:
    """The staged import in ``folder`` last touched more than ``peer_import.EXPIRES`` ago: its last part came in
    long before its import ran (a long job ahead of it in the queue, the owner choosing sides)."""
    import os

    then = time.time() - peer_import.EXPIRES - 600
    for path in (folder / peer_import.FILE, folder / peer_import.OPENED, folder):
        os.utime(path, (then, then))


def test_a_stale_import_keeps_its_staged_file_to_compare_again_and_takes_it_then(libraries, tmp_path):
    from caracole.commands.peer import STALE

    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    folder = stage(studio, exported(desk, tmp_path / "d.caracole").read_bytes())
    shown = compared_in_the_tab(studio, folder)
    studio.song("Muse", "Hysteria", version=None)  # the library moves on before the job runs (a lookup, the night)
    staged_long_ago(folder)  # and the job ran over an hour after the last part came
    out = run(studio, "peer", "import", "--yes", "--progress", f"--compared={shown}", str(folder))
    assert out.exit_code == 1 and STALE in out.output, out.output
    assert folder.exists() and studio.songs() == {"muse/hysteria"}  # kept, nothing taken
    assert peer_import.sweep(studio.cfg.state_dir) == []  # its hour runs from the import's end
    out = run(studio, "peer", "import", "--yes", "--progress", f"--compared={compared_in_the_tab(studio, folder)}",
              str(folder))
    assert out.exit_code == 0, out.output
    assert "oasis/wonderwall" in studio.songs() and not folder.exists()


def test_a_kept_folder_that_cant_be_touched_leaves_the_imports_own_ending(libraries, tmp_path, monkeypatch):
    # peer_import.kept runs in a finally: a touch refused (another owner, a read-only mount) never stands for how
    # the import ended.
    from caracole.commands.peer import STALE

    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    folder = stage(studio, exported(desk, tmp_path / "d.caracole").read_bytes())
    shown = compared_in_the_tab(studio, folder)
    studio.song("Muse", "Hysteria", version=None)

    def refused(*args, **kw):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(peer_import.os, "utime", refused)
    out = run(studio, "peer", "import", "--yes", "--progress", f"--compared={shown}", str(folder))
    assert out.exit_code == 1 and STALE in out.output, out.output
    assert isinstance(out.exception, SystemExit) and folder.exists(), out.exception  # no traceback over it
    out = run(studio, "peer", "import", "--yes", "--progress", f"--compared={compared_in_the_tab(studio, folder)}",
              str(folder))
    assert out.exit_code == 0 and not isinstance(out.exception, OSError), (out.output, out.exception)
    assert not folder.exists()


def test_an_import_a_new_comparison_can_settle_keeps_its_staged_file_and_lets_go_of_it(libraries, tmp_path):
    desk, studio, _ = libraries
    f = a_file_that_removed_a_song_changed_here(desk, studio, tmp_path)
    folder = stage(studio, f.read_bytes())
    out = run(studio, "peer", "import", "--yes", "--progress", "--choose=here:song/oasis/nothing", str(folder))
    assert out.exit_code == 2 and "no longer a difference" in out.output and folder.exists()
    out = run(studio, "peer", "import", "--yes", "--progress", str(folder))  # its conflict left with no side
    assert out.exit_code == 1 and folder.exists(), out.output
    # The import over, its hold is gone: another file opened lets it go, as an hour does.
    assert peer_import.let_go(studio.cfg.state_dir, set()) == [folder.name[len(peer_import.PREFIX):]]


def test_a_file_an_import_refuses_or_takes_whole_is_deleted(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    data = exported(desk, tmp_path / "d.caracole").read_bytes()
    folder = stage(studio, data)
    assert run(studio, "peer", "import", "--yes", str(folder)).exit_code == 0 and not folder.exists()
    again = stage(studio, data)  # the same file: nothing newer in it
    staged_long_ago(again)
    out = run(studio, "peer", "import", "--yes", str(again))
    assert out.exit_code == 2 and "Nothing in this file is newer" in out.output and not again.exists()
    own = stage(studio, exported(studio, tmp_path / "own.caracole").read_bytes())
    out = run(studio, "peer", "import", "--yes", str(own))
    assert out.exit_code == 2 and peer_file.OWN_EXPORT in out.output and not own.exists()
    garbage = stage(studio, b"not a file at all")
    assert run(studio, "peer", "import", "--yes", str(garbage)).exit_code == 2 and not garbage.exists()


def test_a_staged_file_not_whole_yet_is_refused_and_left_for_the_rest_to_come(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    data = exported(desk, tmp_path / "d.caracole").read_bytes()
    state = studio.cfg.state_dir
    import_id = peer_import.open_import(state, size=len(data), name="d.caracole")
    peer_import.add_part(state, import_id, 0, data[:len(data) // 2])
    folder = state / "peer" / f"import-{import_id}"
    out = run(studio, "peer", "import", "--yes", "--progress", str(folder))
    assert out.exit_code == 2 and peer_import.NOT_WHOLE in out.output
    assert folder.exists() and studio.songs() == set()
    peer_import.add_part(state, import_id, len(data) // 2, data[len(data) // 2:])
    out = run(studio, "peer", "import", "--yes", str(folder))
    assert out.exit_code == 0, out.output
    assert studio.units() == desk.units() and not folder.exists()


def test_a_folder_that_isnt_an_import_here_is_refused_and_left(libraries, tmp_path):
    _, studio, _ = libraries
    elsewhere = tmp_path / "import-0123456789abcdef"
    elsewhere.mkdir()
    out = run(studio, "peer", "import", "--yes", str(elsewhere))
    assert out.exit_code == 2 and elsewhere.exists()


def test_a_song_left_out_of_the_file_is_left_here_saying_why(libraries, tmp_path):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    (song_dir(desk.cfg.library_dir, find_song(desk.conn, "oasis/wonderwall")) / "sheet.txt").write_bytes(b"edited")
    f = tmp_path / "d.caracole"
    result = run(desk, "peer", "export", str(f))
    assert result.exit_code == 0 and "Left out song/oasis/wonderwall" in result.output
    out = run(studio, "peer", "import", "--yes", str(f))
    assert out.exit_code == 1 and f"{LEFT}: Oasis - Wonderwall: " in "\n".join(
        " ".join(line.split()) for line in out.output.splitlines())
    assert "radiohead/creep" in studio.songs() and "oasis/wonderwall" not in studio.songs()



# --- peer sync --parts, and the answers an import remembered ---------------------------------------------------------


def test_a_sync_of_songbooks_alone_takes_the_songbook_and_its_song_and_nothing_else(libraries):
    desk, studio, _ = libraries
    desk_with_a_songbook(desk)
    out = run(studio, "peer", "sync", HOST, "--yes", "--parts", "songbooks")
    assert out.exit_code == 0, out.output
    assert studio.songs() == {"radiohead/creep"}
    assert [b.name for b in load_songbooks(songbooks_file(studio.cfg.library_dir))] == ["Campfire"]
    assert "Oasis - Wonderwall" not in out.output  # outside the parts: neither taken nor said
    assert run(studio, "peer", "sync", HOST, "--yes", "--parts", "lyrics").exit_code == 2
    assert run(studio, "peer", "sync", HOST, "--yes", "--parts", "library,songbooks,indexes").exit_code == 0
    assert studio.songs() == {"radiohead/creep", "oasis/wonderwall"}


def test_a_unit_kept_here_at_an_import_is_given_at_the_next_network_sync(libraries, tmp_path):
    desk, studio, _ = libraries
    desk.song(version="key=Am&capo=0")
    studio.song(version="key=Gm&capo=0")
    unit = "song/radiohead/creep"
    out = run(studio, "peer", "import", "--yes", f"--choose=here:{unit}", str(exported(desk, tmp_path / "d.caracole")))
    assert out.exit_code == 0, out.output
    assert unit in sync.kept_of(studio.conn, desk.id())
    diff = json.loads(run(studio, "peer", "diff", HOST, "--json").output)
    assert [(d["id"], d["proposal"], d["why"]) for d in diff["differences"]] == [(unit, "mine", sync.KEPT_HERE)]
    out = run(studio, "peer", "sync", HOST, "--push", "--yes")
    assert out.exit_code == 0, out.output
    assert load_overrides(desk.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    assert desk.units() == studio.units() and sync.kept_of(studio.conn, desk.id()) == {}


def test_a_sync_from_the_tab_after_an_import_kept_a_unit_gives_it_there(libraries, tmp_path, monkeypatch):
    """caracole serve's Sync tab compares with the answers an import remembered, as ``peer sync`` does
    (web/sync_routes.py): a unit kept here is here's to give, and its Sync, ``peer sync --compared`` with its hash,
    is the comparison it showed, never refused as stale for them."""
    from caracole.commands import peer as peer_cmd
    from caracole.web import sync_routes

    desk, studio, _ = libraries
    desk.song(version="key=Am&capo=0")
    studio.song(version="key=Gm&capo=0")
    unit = "song/radiohead/creep"
    out = run(studio, "peer", "import", "--yes", f"--choose=here:{unit}", str(exported(desk, tmp_path / "d.caracole")))
    assert out.exit_code == 0, out.output
    monkeypatch.setattr(sync_routes, "transport", peer_cmd.transport_for_peer)
    compared = json.loads(post(studio.app, "/sync/compare", {"address": HOST}, accept="application/json").body)
    assert [(d["id"], d["proposal"], d["why"]) for d in compared["differences"]] == [(unit, "mine", sync.KEPT_HERE)]
    answer = post(studio.app, "/sync/apply", {"comparison": compared["comparison"], "prefer": "", "choices": ""},
                  accept="application/json")
    assert answer.status == 200, answer.body
    studio.app.queue.run_pending()
    (job,) = studio.app.queue.snapshot()
    assert job.state == "done", [s.output for s in job.steps]
    # the unit the tab showed as kept here, given there: here's as it was
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    assert studio.units() == desk.units() and sync.kept_of(studio.conn, desk.id()) == {}
    # a hash that names neither comparison is refused all the same
    stale = run(studio, "peer", "sync", HOST, "--push", "--yes", "--compared", "0" * 64)
    assert stale.exit_code == 1 and "changed since that comparison" in stale.output


def a_file_that_removed_a_song_changed_here(desk: Lib, studio: Lib, tmp_path: Path) -> Path:
    """Studio took Wonderwall from Desk's file, then changed it; Desk removed it since: its next file."""
    from caracole.removal import plan_removal, remove_song

    desk_with_a_songbook(desk)
    assert run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "a.caracole"))).exit_code == 0
    add_version(studio.cfg.overrides_file, "Oasis - Wonderwall", "key=Em&capo=2")  # changed here
    remove_song(desk.conn, desk.cfg, plan_removal(desk.conn, desk.cfg, find_song(desk.conn, "oasis/wonderwall")))
    return exported(desk, tmp_path / "b.caracole")


def test_a_song_kept_here_against_the_files_removal_answers_its_removal_too(libraries, tmp_path, in_utc):
    """"Keep mine" for a song the file removed is the removal's answer too: nothing taken nor left, the import done,
    both answers remembered, so the same file is then refused as no newer."""
    desk, studio, _ = libraries
    f = a_file_that_removed_a_song_changed_here(desk, studio, tmp_path)
    song, removal = "song/oasis/wonderwall", "removed/oasis/wonderwall"
    out = run(studio, "peer", "import", "--yes", "--progress", f"--choose=here:{song}", str(f))
    assert out.exit_code == 0, out.output
    assert [e for e in events(out.output) if e.get("event") == "unit"] == []
    assert find_song(studio.conn, "oasis/wonderwall") is not None and removed_song(studio.conn, "oasis/wonderwall") is None
    made = peer_file.read_file(f).made
    removed_there = peer_file.read_file(f).state.units[removal].digest
    assert sync.kept_of(studio.conn, desk.id()) == {song: (studio.units()[song].digest, None, made),
                                                    removal: (None, removed_there, made)}
    again = run(studio, "peer", "import", "--yes", str(f))
    day = datetime.now(UTC).strftime("%d/%m/%y")
    assert again.exit_code == 2 and f"Nothing in this file is newer than your sync with Desk on {day}." in again.output
    assert find_song(studio.conn, "oasis/wonderwall") is not None


def test_a_song_taken_as_the_file_removed_it_takes_its_removal_too(libraries, tmp_path):
    desk, studio, _ = libraries
    f = a_file_that_removed_a_song_changed_here(desk, studio, tmp_path)
    out = run(studio, "peer", "import", "--yes", "--progress", "--choose=there:song/oasis/wonderwall", str(f))
    assert out.exit_code == 0, out.output
    assert sorted((e["id"], e["outcome"]) for e in events(out.output) if e.get("event") == "unit") == [
        ("removed/oasis/wonderwall", "taken"), ("song/oasis/wonderwall", "taken")]
    assert find_song(studio.conn, "oasis/wonderwall") is None
    assert removed_song(studio.conn, "oasis/wonderwall") is not None


def test_a_removal_beside_its_songs_conflict_left_unsettled_is_left_saying_so(libraries, tmp_path):
    desk, studio, _ = libraries
    f = a_file_that_removed_a_song_changed_here(desk, studio, tmp_path)
    out = run(studio, "peer", "import", "--yes", "--progress", str(f))
    assert out.exit_code == 1, out.output  # units left
    units = sorted((e["id"], e["outcome"], e["why"]) for e in events(out.output) if e.get("event") == "unit")
    assert ("removed/oasis/wonderwall", "left", sync.SONG_HERE) in units, units
    assert find_song(studio.conn, "oasis/wonderwall") is not None
    assert "removed/oasis/wonderwall" not in sync.kept_of(studio.conn, desk.id())  # nothing kept for the removal
