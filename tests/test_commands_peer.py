"""``caracole peer``, run through the CLI against another library's caracole serve (a WebApp, in this process): the
comparison, a pull of the other's units, and a two-way sync."""

import json
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from typer.testing import CliRunner

from caracole import db
from caracole import peer_sync as sync
from caracole.cli import build_app
from caracole.config import load_config
from caracole.library import keep_file, song_dir
from caracole.lyrics import Lyrics
from caracole.overrides import Overrides, add_version, load_overrides, override_key
from caracole.songbook import load_songbooks, make_songbook, songbooks_file
from caracole.songs import find_song, removed_song, update_song
from caracole.versions import upsert_version
from caracole.wanted import append_wanted, find_wanted
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from test_web_app import ALLOWED, HOST, Recorder

NOW = "2026-10-31T00:00:00Z"
CREEP = "Radiohead - Creep"


def write_config(root: Path) -> Path:
    path = root / "caracole.toml"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(f'library_dir = "{root / "lib"}"\nmusic_dir = "{root / "music"}"\n'
                    f'state_dir = "{root / "state"}"\ncache_dir = "{root / "cache"}"\n', encoding="utf-8")
    return path


class InProcess:
    """A side's caracole serve's runner, in this process: each command queued run through the CLI, on its config,
    as caracole serve's child would run it."""

    def __init__(self):
        self.side = None
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        result = run(self.side, *args)
        for line in result.output.splitlines():
            emit(line)
        return result.exit_code


class Side:
    """A library of its own: its config, its database, and its caracole serve, whose queue records the commands
    it is asked to run (``runner``: or runs them)."""

    def __init__(self, root: Path, runner=None):
        self.root = root
        self.cfg = load_config(write_config(root), env={"HOME": str(root / "home")})
        self.conn = db.connect(self.cfg.db_path)
        if isinstance(runner, InProcess):
            runner.side = self
        self.app = WebApp(self.cfg, JobQueue(runner or Recorder(), limit=3), allowed=ALLOWED, csrf="tok")

    def song(self, artist="Radiohead", title="Creep", *, sheet=b"[Am]Creep", version="key=Gm&capo=0"):
        """A song of wanted.txt with a sheet kept, its own version, and lyrics."""
        append_wanted(self.cfg.wanted_file, artist, title)
        # as its line says it (no duration), so that reading wanted.txt again changes nothing of it
        song = add_song(self.conn, artist, title, source_id=f"{artist} - {title}", duration_ms=None)
        vid = upsert_version(self.conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                             rating=4.5, votes=10, version=1, label=None, url="https://u/101", raw={"x": 1}, now=NOW)
        keep_file(self.conn, self.cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=sheet, rank=1)
        lyrics = Lyrics(plain="I'm a creep", synced=None, instrumental=False, duration=None, lrclib_id=1)
        update_song(self.conn, song.id, status="found", lyrics_status="found", lyrics_json=lyrics.to_json())
        if version:
            add_version(self.cfg.overrides_file, f"{artist} - {title}", version)
        return find_song(self.conn, song.key)

    def units(self):
        overrides = load_overrides(self.cfg.overrides_file) if self.cfg.overrides_file.exists() else Overrides()
        return sync.library_state(self.conn, overrides, load_songbooks(songbooks_file(self.cfg.library_dir)))


@pytest.fixture
def two(tmp_path, monkeypatch):
    """This library (here) and the phone's (there), whose caracole serve answers at http://localhost:8737 and runs
    what it queued as it is asked how a job goes; the songs taken are rendered by a recorder, not chordpro."""
    here, there = Side(tmp_path / "here"), Side(tmp_path / "there", InProcess())
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.method, request.url.path))
        if request.url.path.startswith("/api/jobs/"):
            there.app.queue.run_pending()
        answer = there.app.handle(Request(request.method, request.url.raw_path.decode(), dict(request.headers),
                                          request.content))
        answer = WebApp.finish(answer)
        return httpx.Response(answer.status, headers=answer.headers, content=answer.body)

    rendered = []
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr("caracole.render.render_all", lambda conn, cfg, overrides, **kw: rendered.append(
        set(kw.get("song_ids") or ())))
    yield here, there, asked, rendered
    here.conn.close()
    there.conn.close()


def run(side, *args):
    return CliRunner().invoke(build_app(), ["--config", str(side.root / "caracole.toml"), *args])


def lines_of(output):
    return [" ".join(line.split()) for line in output.splitlines()]


# --- the comparison ----------------------------------------------------------------------------------------------


def test_diff_lists_the_songs_each_side_has_alone_and_changes_nothing(two):
    here, there, asked, _ = two
    add_song(here.conn, "Radiohead", "Creep")
    add_song(here.conn, "Oasis", "Wonderwall")
    add_song(there.conn, "Oasis", "Wonderwall")
    add_song(there.conn, "Estopa", "Tu Calorro")
    add_version(there.cfg.overrides_file, "Oasis - Wonderwall", "key=Em&capo=2")  # chords changed on the phone

    result = run(here, "peer", "diff", HOST)
    assert result.exit_code == 0, result.output
    assert asked == [("GET", "/api/peer/state")]
    out = lines_of(result.output)
    assert "The two never synced: a unit on one side alone is that side's, and one both hold, differently, a " \
           "conflict." in out
    assert "3 differences, 1 conflict:" in out
    assert "keep here's Radiohead - Creep (only here)" in out
    assert "take there's Estopa - Tu Calorro (only there)" in out
    assert "CONFLICT Oasis - Wonderwall (on both sides, different, and never synced)" in out
    assert sync.base_of(here.conn, sync.own_id(there.conn)) is None  # nothing written


def test_the_same_caracole_twice_is_said_and_nothing_compared(two):
    here, there, _, _ = two
    db.kv_set(here.conn, sync.ID_KEY, sync.own_id(there.conn))  # a copy of the database
    result = run(here, "peer", "diff", HOST)
    assert result.exit_code == 1 and "is this one" in result.output and "caracole peer new-id" in result.output
    assert run(here, "peer", "new-id").exit_code == 0
    assert run(here, "peer", "diff", HOST).exit_code == 0


def test_nothing_answering_is_said_plainly(two, monkeypatch):
    here = two[0]

    def refused(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: httpx.MockTransport(refused))
    result = run(here, "peer", "diff", "192.168.1.20:8737")
    assert result.exit_code == 1 and "Nothing answered at http://192.168.1.20:8737" in result.output


# --- taking units ------------------------------------------------------------------------------------------------


def test_a_pull_brings_the_song_its_line_versions_files_lyrics_and_chords_then_the_two_agree(two):
    here, there, asked, rendered = two
    theirs = there.song()
    result = run(here, "peer", "pull", HOST, f"--unit=song/{theirs.key}")
    assert result.exit_code == 0, result.output
    assert "Took 1 change; 1 song rendered again." in result.output

    song = find_song(here.conn, theirs.key)
    assert song is not None and find_wanted(here.cfg.wanted_file, "Radiohead", "Creep") is not None
    folder = song_dir(here.cfg.library_dir, song)
    assert (folder / "sheet.txt").read_bytes() == b"[Am]Creep"
    assert (folder / "lyrics.txt").read_text(encoding="utf-8") == "I'm a creep\n"
    assert load_overrides(here.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    assert [tuple(r) for r in here.conn.execute("SELECT provider, tab_id, kind FROM versions")] == [
        ("ug", "101", "chords")]
    assert rendered == [{song.id}]
    assert here.units() == there.units()
    assert ("GET", "/api/peer/file") in asked
    base = sync.base_of(here.conn, sync.own_id(there.conn))
    assert base[f"song/{song.key}"][0] == here.units()[f"song/{song.key}"].digest
    assert "Nothing differs." in run(here, "peer", "diff", HOST).output
    assert list(here.cfg.state_dir.joinpath("backups").iterdir())  # the database backed up first


def test_a_pull_of_a_song_spelled_otherwise_here_takes_the_peers_names_and_the_two_then_agree(two):
    here, there, _, _ = two
    mine = here.song("radiohead", "creep", version=None)
    theirs = there.song("Radiohead", "Creep", version=None)
    assert mine.key == theirs.key and here.units() != there.units()
    result = run(here, "peer", "pull", HOST, f"--unit=song/{theirs.key}")
    assert result.exit_code == 0, result.output
    song = find_song(here.conn, theirs.key)
    assert (song.artist, song.title) == ("Radiohead", "Creep")
    assert here.units() == there.units()
    assert [line.split(" | ")[0] for line in here.cfg.wanted_file.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")] == [CREEP]  # its line, as the peer writes the song
    stored = json.loads(db.kv_get(here.conn, sync.BASE_KEY + sync.own_id(there.conn)))
    assert stored["format"] == 2 and stored["units"][f"song/{song.key}"][0] == here.units()[f"song/{song.key}"].digest
    assert "Nothing differs." in run(here, "peer", "diff", HOST).output


def test_a_file_that_changed_there_since_it_was_kept_leaves_the_song_as_it_was(two):
    here, there, _, _ = two
    theirs = there.song()
    (song_dir(there.cfg.library_dir, theirs) / "sheet.txt").write_bytes(b"edited on a synced device")
    result = run(here, "peer", "pull", HOST, f"--unit=song/{theirs.key}")
    assert result.exit_code == 1 and f"Left song/{theirs.key}:" in result.output
    assert find_song(here.conn, theirs.key) is None


def test_a_sync_takes_what_changed_there_and_leaves_a_conflict_unless_a_side_is_preferred(two):
    here, there, _, _ = two
    mine, theirs = here.song(version="key=Am&capo=0"), there.song(version="key=Gm&capo=0")
    add_song(there.conn, "Estopa", "Tu Calorro")
    append_wanted(there.cfg.wanted_file, "Estopa", "Tu Calorro")

    result = run(here, "peer", "sync", HOST, "--yes")
    assert result.exit_code == 0, result.output
    assert "Here takes 1, there takes 0, 1 left as they are." in result.output
    estopa = next(k for (k,) in there.conn.execute("SELECT key FROM songs WHERE title = 'Tu Calorro'"))
    assert find_song(here.conn, estopa) is not None
    assert load_overrides(here.cfg.overrides_file).version == {override_key(CREEP): "key=Am&capo=0"}

    result = run(here, "peer", "sync", HOST, "--yes", "--prefer", "there")
    assert result.exit_code == 0, result.output
    assert load_overrides(here.cfg.overrides_file).version == {override_key(CREEP): "key=Gm&capo=0"}
    assert mine.key == theirs.key and here.units() == there.units()


def test_once_synced_a_song_removed_there_is_removed_here(two):
    here, there, _, _ = two
    theirs = there.song()
    assert run(here, "peer", "pull", HOST, f"--unit=song/{theirs.key}").exit_code == 0
    from caracole.removal import plan_removal, remove_song

    remove_song(there.conn, there.cfg, plan_removal(there.conn, there.cfg, find_song(there.conn, theirs.key)))
    result = run(here, "peer", "diff", HOST, "--json")
    found = {d["id"]: (d["proposal"], d["why"]) for d in json.loads(result.output)["differences"]}
    assert found == {f"song/{theirs.key}": ("theirs", "gone there since the last sync"),
                     f"removed/{theirs.key}": ("theirs", "new there since the last sync")}
    result = run(here, "peer", "sync", HOST, "--yes")
    assert result.exit_code == 0, result.output
    assert find_song(here.conn, theirs.key) is None and removed_song(here.conn, theirs.key) is not None
    assert find_wanted(here.cfg.wanted_file, "Radiohead", "Creep") is None


def test_a_songbook_comes_with_its_songs_in_order(two):
    here, there, _, _ = two
    make_songbook(songbooks_file(there.cfg.library_dir), "Campfire", [CREEP, "Oasis - Wonderwall"])
    result = run(here, "peer", "pull", HOST, "--unit=songbook/campfire")
    assert result.exit_code == 0, result.output
    assert [b.texts for b in load_songbooks(songbooks_file(here.cfg.library_dir))] == [(CREEP, "Oasis - Wonderwall")]


def test_with_its_address_a_sync_asks_there_to_take_what_goes_there(two):
    here, there, asked, _ = two
    mine = here.song()
    result = run(here, "peer", "sync", HOST, "--yes", "--here", "192.168.1.10:8737")
    assert result.exit_code == 0, result.output
    assert "Asked http://localhost:8737 to take 1 from http://192.168.1.10:8737" in result.output
    assert ("POST", "/peer/pull") in asked
    job = there.app.queue.snapshot()[0]
    assert [list(s.args) for s in job.steps] == [["peer", "pull", f"--unit=song/{mine.key}", "--",
                                                  "http://192.168.1.10:8737"]]


def test_without_its_address_a_sync_says_what_to_run_there(two):
    here, there, asked, _ = two
    mine = here.song()
    result = run(here, "peer", "sync", HOST, "--yes")
    assert result.exit_code == 0, result.output
    assert f"caracole peer pull ADDRESS-OF-THIS-ONE --unit=song/{mine.key}" in " ".join(lines_of(result.output))
    assert ("POST", "/peer/pull") not in asked
