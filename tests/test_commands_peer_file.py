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
from caracole.commands.peer import PEER_IMPORT_STAGES
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
from test_web_app import ALLOWED, HOST, Recorder

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
    # a change on the file's side after the answer is the file's again
    add_version(desk.cfg.overrides_file, CREEP, "key=Em&capo=0")
    out = run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "3.caracole")))
    assert out.exit_code == 0, out.output
    assert load_overrides(studio.cfg.overrides_file).version == {override_key(CREEP): "key=Em&capo=0"}
    assert sync.kept_of(studio.conn, desk.id()) == {}


def test_a_conflict_neither_chosen_nor_preferred_is_left_and_named(libraries, tmp_path):
    desk, studio, _ = libraries
    desk.song(version="key=Am&capo=0")
    studio.song(version="key=Gm&capo=0")
    out = run(studio, "peer", "import", "--yes", str(exported(desk, tmp_path / "d.caracole")))
    assert out.exit_code == 0, out.output
    assert "Left song/radiohead/creep: a conflict: choose a side for it" in out.output
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
                                  "after": 2, "read": "2026-11-02T08:00:00Z"}]
    assert not list((studio.cfg.cache_dir / "peer").iterdir())  # the indexes' copy gone
    # --parts without the indexes leaves them
    other = Lib(tmp_path / "other", "Other")
    out = run(other, "peer", "import", "--yes", "--progress", "--parts", "library", str(f))
    assert ("index", "skipped") in [(e["stage"], e["state"]) for e in events(out.output) if "stage" in e]
    assert other.conn.execute("SELECT COUNT(*) FROM gtptabs_index").fetchone()[0] == 0
    other.conn.close()


def test_an_index_file_is_merged_and_records_no_agreement(libraries, tmp_path):
    desk, studio, _ = libraries
    gtptabs_index(desk, datetime(2026, 11, 2, 8, 0, tzinfo=UTC), ["https://gtptabs.com/tabs/3/oasis.html"])
    index_transfer.export(desk.conn, tmp_path / "i.sqlite", now=datetime(2026, 11, 3, tzinfo=UTC))
    out = run(studio, "peer", "import", "--yes", "--progress", str(tmp_path / "i.sqlite"))
    assert out.exit_code == 0, out.output
    assert [r[0] for r in studio.conn.execute("SELECT path FROM gtptabs_index")] == ["tabs/3/oasis.html"]
    assert [(e["stage"], e["state"]) for e in events(out.output) if "stage" in e] == [
        ("check", "running"), ("check", "done"), ("take", "skipped"), ("render", "skipped"), ("agree", "skipped"),
        ("index", "running"), ("index", "done")]
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
    assert out.exit_code == 1 and "Left song/oasis/wonderwall" in "\n".join(
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
