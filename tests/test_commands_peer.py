"""``caracole peer``, run through the CLI against another library's caracole serve (a WebApp, in this process): the
comparison, a pull of the other's units, and a two-way sync: there asked to pull, or given its units by a push
(``--push``), which its caracole serve takes as a job of its queue, run in this process through the CLI too."""

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
    assert "ours goes there Radiohead - Creep (only in our book)" in out
    assert "theirs comes here Estopa - Tu Calorro (only in theirs)" in out
    assert "CONFLICT Oasis - Wonderwall (in both books, different, never shared)" in out
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
    assert result.exit_code == 1 and "No answer at http://192.168.1.20:8737" in result.output


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
    assert stored["format"] == 3 and stored["units"][f"song/{song.key}"][0] == here.units()[f"song/{song.key}"].digest
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
    assert found == {f"song/{theirs.key}": ("theirs", "gone there since the last share"),
                     f"removed/{theirs.key}": ("theirs", "new there since the last share")}
    result = run(here, "peer", "sync", HOST, "--yes")
    assert result.exit_code == 0, result.output
    assert find_song(here.conn, theirs.key) is None and removed_song(here.conn, theirs.key) is not None
    assert find_wanted(here.cfg.wanted_file, "Radiohead", "Creep") is None


def by_keys(transport: httpx.MockTransport, version: int) -> httpx.MockTransport:
    """``transport``'s caracole serve answering as a caracole whose songs are keyed by ``version``
    (``normalize.KEY_VERSION``), whatever this side's are: the two in this process, its every answer, and every
    command it runs as it answers, made under its own."""
    from caracole import normalize

    def handler(request: httpx.Request) -> httpx.Response:
        here_keys, normalize.KEY_VERSION = normalize.KEY_VERSION, version
        try:
            return transport.handler(request)
        finally:
            normalize.KEY_VERSION = here_keys

    return httpx.MockTransport(handler)


def answering_by_keys(monkeypatch, version: int) -> None:
    """There's caracole serve, as ``caracole peer`` asks it, answering as a caracole of the song keys of ``version``."""
    from caracole.commands import peer

    there = by_keys(peer.transport_for_peer(), version)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: there)


def test_a_caracole_whose_song_keys_changed_never_syncs_with_one_of_the_old_keys_and_neither_loses_the_song(
        two, monkeypatch):
    from caracole import normalize, songs

    here, there, asked, _ = two
    creep = there.song()
    assert run(here, "peer", "sync", HOST, "--push", "--yes").exit_code == 0  # the two agree on Creep
    # Here is upgraded: its normalizer keys Creep otherwise (a KEY_VERSION bump), and it re-keys its songs. There
    # still runs the caracole before, which keys it as it did: to it, here's song/<old key> is gone.
    old = songs.identity_key
    monkeypatch.setattr(songs, "identity_key", lambda a, t: old(a, t) + "-v3" if t == "Creep" else old(a, t))
    songs.rekey_songs(here.conn)
    monkeypatch.setattr(songs, "identity_key", old)
    assert find_song(here.conn, creep.key + "-v3") is not None
    monkeypatch.setattr(normalize, "KEY_VERSION", normalize.KEY_VERSION + 1)
    answering_by_keys(monkeypatch, normalize.KEY_VERSION - 1)
    mine, theirs = here.units(), there.units()
    asked.clear()

    for args in (["diff"], ["sync", "--push", "--yes", "--prefer=here"], ["pull", f"--unit=song/{creep.key}"]):
        result = run(here, "peer", args[0], HOST, *args[1:])
        assert result.exit_code == 1 and sync.OTHER_KEYS in result.output, (args, result.output)
    assert {path for _, path in asked} == {"/api/peer/state"}  # refused as the state is read: nothing asked after
    assert find_song(there.conn, creep.key) is not None and removed_song(there.conn, creep.key) is None
    assert here.units() == mine and there.units() == theirs and there.app.queue.snapshot() == []


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
    digest = here.units()[f"song/{mine.key}"].digest  # as compared: this side's, and none there
    assert [list(s.args) for s in job.steps] == [["peer", "pull", f"--unit={digest}:-:song/{mine.key}", "--",
                                                  "http://192.168.1.10:8737"]]


def test_a_pull_as_compared_leaves_a_unit_changed_on_either_side_since(two):
    here, there, _, _ = two
    theirs = there.song()
    unit = f"song/{theirs.key}"
    digest = there.units()[unit].digest
    result = run(here, "peer", "pull", HOST, f"--unit={'0' * 64}:-:{unit}")  # changed there since compared
    assert result.exit_code == 1 and f"Left {unit}: changed there since compared" in result.output
    here.song(sheet=b"[C]Creep, mine")  # changed here since compared: none here then
    result = run(here, "peer", "pull", HOST, f"--unit={digest}:-:{unit}")
    assert result.exit_code == 1 and f"Left {unit}: changed here since compared" in result.output
    assert here.units()[unit].digest != digest  # the change made here since kept
    mine = here.units()[unit].digest
    result = run(here, "peer", "pull", HOST, f"--unit={digest}:{mine}:{unit}")
    assert result.exit_code == 0, result.output
    assert here.units()[unit].digest == digest
    assert run(here, "peer", "pull", HOST, "--unit=x:-:song/a").exit_code == 2


def test_without_its_address_a_sync_says_what_to_run_there(two):
    here, there, asked, _ = two
    mine = here.song()
    result = run(here, "peer", "sync", HOST, "--yes")
    assert result.exit_code == 0, result.output
    assert f"caracole peer pull ADDRESS-OF-THIS-ONE --unit=song/{mine.key}" in " ".join(lines_of(result.output))
    assert ("POST", "/peer/pull") not in asked


# --- a sync by push, with your choices and the comparison they were made on --------------------------------------


def two_conflicts(here, there):
    """Two libraries that never synced: Creep and Wonderwall on both, chorded differently (two conflicts), Creep's
    sheet too; Muse's Hysteria here alone, Estopa's Tu Calorro there alone."""
    here.song("Radiohead", "Creep", version="key=Am&capo=0", sheet=b"[Am]Creep, as played here")
    there.song("Radiohead", "Creep", version="key=Gm&capo=0")
    here.song("Oasis", "Wonderwall", version="key=Em&capo=2")
    there.song("Oasis", "Wonderwall", version="key=Em&capo=0")
    here.song("Muse", "Hysteria", version=None)
    there.song("Estopa", "Tu Calorro", version=None)
    return {find_song(here.conn, k).display: f"song/{k}" for (k,) in here.conn.execute("SELECT key FROM songs")} | {
        find_song(there.conn, k).display: f"song/{k}" for (k,) in there.conn.execute("SELECT key FROM songs")}


def compared_now(here):
    result = run(here, "peer", "diff", HOST, "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["compared"]


def test_a_sync_by_push_with_choices_takes_and_gives_and_the_two_end_with_no_differences(two):
    here, there, asked, _ = two
    unit = two_conflicts(here, there)
    result = run(here, "peer", "sync", HOST, "--push", "--yes", f"--compared={compared_now(here)}",
                 f"--choose=here:{unit['Radiohead - Creep']}", f"--choose=there:{unit['Oasis - Wonderwall']}")
    assert result.exit_code == 0, result.output
    assert "Here takes 2, there takes 2." in result.output and "Gave 2 changes to http://localhost:8737." in result.output

    assert ("POST", "/peer/pull") not in asked  # given by a push: there needn't reach here
    assert [p for m, p in asked if m == "POST"] == ["/peer/push/new", "/peer/push/file", "/peer/push"]
    (job,) = there.app.queue.snapshot()
    assert job.state == "done" and job.display == f"Changes from {here.cfg.library_name}"
    assert sorted(job.units) == sorted([(unit["Radiohead - Creep"], "taken", ""), (unit["Muse - Hysteria"], "taken", "")])
    assert not (there.cfg.state_dir / "peer").exists() or list((there.cfg.state_dir / "peer").iterdir()) == []

    assert here.units() == there.units()
    creep = find_song(there.conn, unit["Radiohead - Creep"].partition("/")[2])
    assert (song_dir(there.cfg.library_dir, creep) / "sheet.txt").read_bytes() == b"[Am]Creep, as played here"
    assert load_overrides(here.cfg.overrides_file).version == {
        override_key(CREEP): "key=Am&capo=0", override_key("Oasis - Wonderwall"): "key=Em&capo=0"}
    assert load_overrides(there.cfg.overrides_file).version == load_overrides(here.cfg.overrides_file).version
    assert "Nothing differs." in run(here, "peer", "diff", HOST).output
    there_id = sync.own_id(there.conn)
    stored = db.kv_get_json(here.conn, "sync:peer:" + there_id)
    assert stored == {"address": "http://localhost:8737", "name": there.cfg.library_name,
                      "synced_at": stored["synced_at"]}
    assert stored["synced_at"] == sync.base_of(here.conn, there_id)[unit["Muse - Hysteria"]][1]
    assert sync.base_of(there.conn, sync.own_id(here.conn))[unit["Muse - Hysteria"]][0] == \
        here.units()[unit["Muse - Hysteria"]].digest  # there agreed as it took the push


def test_a_stale_comparison_is_refused_before_any_change(two):
    here, there, asked, _ = two
    unit = two_conflicts(here, there)
    compared = compared_now(here)
    there.song("Muse", "Uprising", version=None)  # there moved on since
    before = here.units()
    asked.clear()
    result = run(here, "peer", "sync", HOST, "--push", "--yes", f"--compared={compared}",
                 f"--choose=here:{unit['Radiohead - Creep']}", "--progress")
    assert result.exit_code == 1 and "changed since that comparison" in result.output
    assert asked == [("GET", "/api/peer/state")] and here.units() == before
    assert there.app.queue.snapshot() == [] and not (here.cfg.state_dir / "backups").exists()
    assert db.kv_get(here.conn, "sync:peer:" + sync.own_id(there.conn)) is None
    assert '"stage":"compare","state":"failed"' in result.output


def test_a_syncs_progress_is_its_stages_and_a_line_a_unit(two, monkeypatch):
    from caracole.get import read_progress_line

    here, there, _, _ = two
    unit = two_conflicts(here, there)

    def render_all(conn, cfg, overrides, *, song_ids=(), on_song=None, **kw):  # its turns, as render.py's
        for n, _song_id in enumerate(sorted(song_ids), 1):
            on_song(n, len(song_ids), None)

    monkeypatch.setattr("caracole.render.render_all", render_all)
    result = run(here, "peer", "sync", HOST, "--push", "--progress", f"--choose=skip:{unit['Radiohead - Creep']}",
                 f"--choose=there:{unit['Oasis - Wonderwall']}")
    assert result.exit_code == 0, result.output
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    stages = [(e["stage"], e["state"]) for e in events if "stage" in e]
    assert [s for n, s in enumerate(stages) if n == 0 or s != stages[n - 1]] == [
        ("compare", "running"), ("compare", "done"), ("take", "running"), ("take", "done"), ("give", "running"),
        ("give", "done"), ("agree", "running"), ("agree", "done"), ("index", "skipped")]
    # The take renders the songs it took, which of them it is at its running detail, as an import's render stage
    # says it (the Sync sheet shows it).
    assert [e["detail"] for e in events if e.get("stage") == "take" and e["state"] == "running"] == [
        "2 changes", "1 of 2 songs", "2 of 2 songs"]
    assert sorted((e["id"], e["outcome"], e["why"]) for e in events if e.get("event") == "unit") == sorted([
        (unit["Radiohead - Creep"], "left", "skipped, as you chose"), (unit["Oasis - Wonderwall"], "taken", ""),
        (unit["Estopa - Tu Calorro"], "taken", ""), (unit["Muse - Hysteria"], "given", "")])
    found = json.loads(run(here, "peer", "diff", HOST, "--json").output)["differences"]
    assert [(d["id"], d["proposal"]) for d in found] == [(unit["Radiohead - Creep"], "conflict")]


def test_a_conflict_neither_chosen_nor_preferred_is_left_and_named(two):
    here, there, _, _ = two
    unit = two_conflicts(here, there)
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 0, result.output
    assert f"Left {unit['Radiohead - Creep']}: both books changed it: choose one" in result.output
    assert f"Left {unit['Oasis - Wonderwall']}: both books changed it: choose one" in result.output
    found = json.loads(run(here, "peer", "diff", HOST, "--json").output)["differences"]
    assert sorted(d["id"] for d in found) == sorted([unit["Radiohead - Creep"], unit["Oasis - Wonderwall"]])


def served_by(side) -> httpx.MockTransport:
    """``side``'s caracole serve, as ``two``'s handler serves there's: for the other side to ask this one."""
    def handler(request: httpx.Request) -> httpx.Response:
        answer = WebApp.finish(side.app.handle(Request(request.method, request.url.raw_path.decode(),
                                                       dict(request.headers), request.content)))
        return httpx.Response(answer.status, headers=answer.headers, content=answer.body)

    return httpx.MockTransport(handler)


def differences(side) -> dict:
    result = run(side, "peer", "diff", HOST, "--json")
    assert result.exit_code == 0, result.output
    return {d["id"]: (d["proposal"], d["why"]) for d in json.loads(result.output)["differences"]}


def test_what_a_sync_took_stays_agreed_when_its_give_fails_so_a_later_change_there_alone_is_theirs(two, monkeypatch):
    from caracole import peer_push

    here, there, _, _ = two
    creep = here.song(version="key=Am&capo=0")
    there.song(version="key=Am&capo=0")
    assert run(here, "peer", "sync", HOST, "--push", "--yes").exit_code == 0  # synced once: Creep alike, agreed
    unit, hysteria = f"song/{creep.key}", "song/muse/hysteria"
    add_version(there.cfg.overrides_file, CREEP, "key=Gm&capo=0")  # there changes Creep's chords
    here.song("Muse", "Hysteria", version=None)  # here gets a song of its own to give

    # There can't take a push now (two wait there already, another caracole's): the give fails, after the take.
    for _ in range(2):
        peer_push.new_push(there.cfg.state_dir, sender="0123456789abcdef", files=[], need=[],
                           own=sync.own_id(there.conn))
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 1 and "Two pushes wait here already" in result.output, result.output
    assert here.units()[unit] == there.units()[unit]  # Creep taken all the same: the two hold it alike
    base = sync.base_of(here.conn, sync.own_id(there.conn))
    assert base[unit][0] == there.units()[unit].digest  # what was taken is agreed, at its digest
    assert hysteria not in base  # what wasn't given isn't

    # There changes Creep again: only there changed it since the two last held it alike.
    add_version(there.cfg.overrides_file, CREEP, "key=Fm&capo=0")
    assert differences(here) == {unit: ("theirs", "changed there since the last share"),
                                 hysteria: ("mine", "new here since the last share")}
    # And there, asking here, reads it so too, by the agreement here's state carries.
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: served_by(here))
    assert differences(there) == {unit: ("mine", "changed here since the last share"),
                                  hysteria: ("theirs", "new there since the last share")}


def test_choices_that_cant_be_read_or_name_no_difference_are_refused_before_anything(two):
    here, there, asked, _ = two
    unit = two_conflicts(here, there)
    for args in (["--choose=maybe:" + unit["Radiohead - Creep"]], ["--choose=here"], ["--choose=here:nonsense"],
                 ["--choose=here:" + unit["Radiohead - Creep"], "--choose=there:" + unit["Radiohead - Creep"]],
                 ["--push", "--here", "192.168.1.10:8737"]):
        result = run(here, "peer", "sync", HOST, "--yes", *args)
        assert result.exit_code == 2, (args, result.output)
    assert asked == []
    result = run(here, "peer", "sync", HOST, "--yes", "--choose=here:song/nobody/nothing")
    assert result.exit_code == 2 and "don't hold differently" in result.output
    assert there.app.queue.snapshot() == [] and not (here.cfg.state_dir / "backups").exists()
