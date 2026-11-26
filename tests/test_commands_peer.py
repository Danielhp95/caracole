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
from caracole.web import peer_routes  # noqa: F401  (its limits read before a test sets peer_push's smaller)
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

    # There can't take a push now (two wait there already, two other caracoles'): the give fails, after the take.
    for sender in ("0123456789abcdef", "fedcba9876543210"):
        peer_push.new_push(there.cfg.state_dir, sender=sender, files=[], need=[], own=sync.own_id(there.conn))
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


def test_a_take_of_a_push_whose_render_fails_keeps_what_it_took_agreed_with_its_sender(two, monkeypatch):
    # The push's take there dies as it renders (a bug, caracole serve stopped): its agree never runs, and the
    # pusher's own may not either (its next ask of the take finds no server), so the take keeps what it took itself.
    here, there, _, _ = two
    here.song("Muse", "Hysteria", version=None)
    unit = "song/muse/hysteria"

    def render_all(conn, cfg, overrides, **kw):
        if cfg.state_dir == there.cfg.state_dir:
            raise RuntimeError("killed while rendering")

    monkeypatch.setattr("caracole.render.render_all", render_all)
    run(here, "peer", "sync", HOST, "--push", "--yes")
    (job,) = there.app.queue.snapshot()
    assert job.state == "failed" and there.units()[unit] == here.units()[unit]  # taken before its render died
    base = sync.base_of(there.conn, sync.own_id(here.conn)) or {}
    assert base.get(unit, (None,))[0] == here.units()[unit].digest


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


def limited(there, *, limits=None, refuse=None, posted=None):
    """There's caracole serve as server.py serves it: a body past its route's limit (or ``limits``' for its path)
    refused 413 before it is read; ``refuse(path, n)``, the n-th POST to a path from 1, a status to answer instead
    (None: answered); each POST's path and length kept in ``posted``."""
    counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path, target = request.url.path, request.url.raw_path.decode()
        if path.startswith("/api/jobs/"):
            there.app.queue.run_pending()
        if request.method == "POST":
            counts[path] = counts.get(path, 0) + 1
            if posted is not None:
                posted.append((path, len(request.content)))
            limit = (limits or {}).get(path, there.app.body_limit("POST", target))
            if len(request.content) > limit:
                return httpx.Response(413, content=b"That is too long to send here.\n")
            status = refuse(path, counts[path]) if refuse is not None else None
            if status is not None:
                return httpx.Response(status, json={"error": "Not now."})
        answer = WebApp.finish(there.app.handle(Request(request.method, target, dict(request.headers),
                                                        request.content)))
        return httpx.Response(answer.status, headers=answer.headers, content=answer.body)

    return httpx.MockTransport(handler)


def test_a_push_that_fails_halfway_lets_go_of_its_slot_there_at_once(two, monkeypatch):
    """A push that stops after POST /peer/push/new (here its file refused, 503) is dropped there as it fails, so two
    failed syncs never leave the other side refusing every push for an hour, the phone's included; and the sync says
    why it failed."""
    from caracole import peer_push

    here, there, asked, _ = two
    transport = limited(there, refuse=lambda path, n: 503 if path == peer_push.FILE_PATH else None)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    here.song("Radiohead", "Creep", sheet=b"%PDF a scanned score")
    for _ in range(2):
        result = run(here, "peer", "sync", HOST, "--push", "--yes")
        assert result.exit_code == 1 and "answered 503" in result.output, result.output
    assert not (there.cfg.state_dir / "peer").exists() or not [
        p for p in (there.cfg.state_dir / "peer").iterdir() if p.name.startswith(peer_push.PREFIX)]
    # another caracole's push (the phone's) is taken now
    opened = peer_push.new_push(there.cfg.state_dir, sender="fedcba9876543210", files=[], need=[],
                                own=sync.own_id(there.conn))
    assert opened.push


VERSE = "Line of a verse that goes on for a while, as songs' lines do\n"


def long_songs(side, n):
    """``n`` songs of ``side`` with long lyrics (some 9 KB of push document each), their unit ids in order."""
    plain = VERSE * 40
    synced = "".join(f"[{k // 60:02d}:{k % 60:02d}.00] {VERSE}" for k in range(40))
    record = {"id": 1, "trackName": "T", "artistName": "A", "duration": 240.0, "instrumental": False,
              "plainLyrics": plain, "syncedLyrics": synced}
    units = []
    for k in range(n):
        song = side.song("Band", f"Song {k}", version=None, sheet=f"[Am]Song {k}".encode())
        update_song(side.conn, song.id, lyrics_json=Lyrics.from_record(record).to_json())
        units.append(f"song/{song.key}")
    return units


def test_a_give_past_what_one_push_carries_goes_in_several_each_within_the_other_sides_limits(two, monkeypatch):
    """A give whose one push document would pass the other side's limit (a first sync of a whole library: 1,500
    songs pass 16 MiB) goes in as many pushes as its limits ask, each followed to its take's end before the next:
    every song taken there, never the 413 that gave nothing at every sync."""
    from caracole import peer_push

    here, there, asked, _ = two
    monkeypatch.setattr(peer_push, "DOCUMENT_MAX", 40_000)  # a few songs a push, so 12 make several
    posted = []
    transport = limited(there, limits={peer_push.PUSH_PATH: 40_000}, posted=posted)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    units = long_songs(here, 12)
    result = run(here, "peer", "sync", HOST, "--push", "--yes", "--progress")
    assert result.exit_code == 0, result.output[-600:]
    documents = [size for path, size in posted if path == peer_push.PUSH_PATH]
    assert len(documents) >= 3 and max(documents) <= 40_000, documents
    assert [path for path, _ in posted if path.startswith("/peer/push")].count(peer_push.NEW_PATH) == len(documents)
    assert there.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 12
    assert '"stage":"give","state":"done","detail":"gave 12"' in result.output
    from caracole.get import read_progress_line

    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    assert sorted(e["id"] for e in events if e.get("outcome") == "given") == sorted(units)
    assert run(here, "peer", "diff", HOST).output.count("only in our book") == 0  # the two agree on each
    assert not [p for p in (there.cfg.state_dir / "peer").iterdir() if p.name.startswith(peer_push.PREFIX)]


def test_a_give_that_stops_at_its_second_push_keeps_the_first_taken_and_says_how_far_it_got(two, monkeypatch):
    """Push 2 of 3 refused: push 1's songs are taken there and agreed (the next sync gives only the rest), push 2 is
    dropped there, push 3 never sent, and the error says how far the give got."""
    from caracole import peer_push

    here, there, asked, _ = two
    monkeypatch.setattr(peer_push, "DOCUMENT_MAX", 40_000)
    posted = []
    transport = limited(there, limits={peer_push.PUSH_PATH: 40_000}, posted=posted,
                        refuse=lambda path, n: 503 if path == peer_push.PUSH_PATH and n == 2 else None)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    long_songs(here, 12)
    result = run(here, "peer", "sync", HOST, "--push", "--yes", "--progress")
    assert result.exit_code == 1, result.output[-600:]
    first = there.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    pushes = [p for p, _ in posted if p == peer_push.PUSH_PATH]
    assert 0 < first < 12 and len(pushes) == 2  # push 1 taken, push 2 refused, none after it
    assert f"Couldn't give them 12: {first} given in the first push of " in result.output
    assert "; then push 2 of " in result.output and "answered 503" in result.output
    assert sum('"outcome":"given"' in line for line in result.output.splitlines()) == first
    assert '"stage":"give","state":"failed"' in result.output
    assert not [p for p in (there.cfg.state_dir / "peer").iterdir() if p.name.startswith(peer_push.PREFIX)]

    posted.clear()
    transport = limited(there, limits={peer_push.PUSH_PATH: 40_000}, posted=posted)
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 0, result.output[-600:]
    assert f"Here takes 0, there takes {12 - first}." in result.output  # push 1's were agreed as its take ended
    assert there.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 12


def test_a_song_with_a_kept_file_too_big_to_push_is_left_with_why_and_the_rest_given(two, monkeypatch):
    """A song whose kept file passes what a push carries (64 MiB: a scanned score dropped into _inbox/) is left out of
    the give in the export's words for it, never sent to be refused; the other songs are given."""
    from caracole import peer_file, peer_push

    here, there, asked, _ = two
    posted = []
    transport = limited(there, posted=posted)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    creep = here.song("Radiohead", "Creep", sheet=b"%PDF" + b"\0" * peer_push.FILE_MAX)  # 64 MiB and 4 bytes
    wonderwall = here.song("Oasis", "Wonderwall", sheet=b"[Em]Today", version=None)
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 0, result.output
    assert f"Left song/{creep.key}: {peer_file.TOO_BIG}" in result.output
    assert "Gave 1 change to" in result.output
    assert find_song(there.conn, wonderwall.key) is not None and find_song(there.conn, creep.key) is None
    assert max(size for _, size in posted) < peer_push.FILE_MAX  # the file was never sent
    assert sync.base_of(here.conn, sync.own_id(there.conn)).get(f"song/{creep.key}") is None  # nor agreed


def waiting_first(there, *, then=None, posted=None, limits=None):
    """``limited`` there, whose push's take is still queued at the first poll of each job (so the give pauses
    between two polls), ``then()`` run as that first poll comes, before it is answered."""
    polled: set[str] = set()
    inner = limited(there, limits=limits, posted=posted)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/jobs/") and path not in polled:
            polled.add(path)
            if then is not None:
                then()
            answer = WebApp.finish(there.app.handle(Request(request.method, request.url.raw_path.decode(),
                                                            dict(request.headers), request.content)))
            return httpx.Response(answer.status, headers=answer.headers, content=answer.body)
        return inner.handle_request(request)

    return httpx.MockTransport(handler)


@pytest.mark.slow
def test_a_lookup_waiting_for_the_lock_gets_it_while_the_give_waits_between_two_pushes(two, monkeypatch, tmp_path):
    """The wait for a push's take there (minutes, for hundreds of songs) is a hand-over point: a lookup in the lane
    waiting for caracole's lock meanwhile takes it then, and the give goes on once it is done."""
    import time

    from helpers.lanes import TURNS, config_file, records, start, wait_for

    from caracole import peer_push
    from caracole.commands import _common

    here, there, asked, _ = two
    monkeypatch.setattr(peer_push, "DOCUMENT_MAX", 40_000)
    (tmp_path / "lookup").mkdir()
    log, go = tmp_path / "lanes.log", tmp_path / "go-lookup"
    lookup = start(TURNS, config_file(here.cfg, tmp_path / "lookup"), log, "lookup", 1, go=go)
    times: list[tuple[str, float]] = []

    def lookup_waits():  # as push 1's take is first asked about: a lookup now waits in the lane
        if go.exists():
            return
        wait_for(log, "ready", "lookup")
        go.touch()
        deadline = time.monotonic() + 20
        while not _common.lane_tickets(here.cfg) and time.monotonic() < deadline:
            time.sleep(0.01)

    class Timed(list):
        def append(self, item):
            times.append((item[0], time.time()))
            super().append(item)

    transport = waiting_first(there, then=lookup_waits, posted=Timed(), limits={peer_push.PUSH_PATH: 40_000})
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    units = long_songs(here, 12)
    try:
        result = run(here, "peer", "sync", HOST, "--push", "--yes")
        assert lookup.wait(30) == 0
    finally:
        lookup.kill()
    assert result.exit_code == 0, result.output[-600:]
    assert there.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == len(units)
    turn = next(r.t for r in records(log) if r.word == "turn")
    pushed = [t for p, t in times if p == peer_push.PUSH_PATH]
    opened = [t for p, t in times if p == peer_push.NEW_PATH]
    assert len(pushed) >= 2 and pushed[0] < turn < opened[1], (pushed, opened, turn)  # between push 1 and push 2


def test_a_unit_a_lookup_changed_while_the_give_waited_is_left_changed_here_never_pushed_stale(two, monkeypatch):
    """After a wait in which the lock went to a lookup, the pushes still to send are checked again: a song the lookup
    changed meanwhile is left (changed here since the comparison), for the next sync, and the rest go on."""
    from caracole import peer_push
    from caracole.commands import _common

    here, there, asked, _ = two
    monkeypatch.setattr(peer_push, "DOCUMENT_MAX", 40_000)
    units = long_songs(here, 12)
    changed = units[9]  # "Band - Song 9", the last by its label: in the last push
    last = find_song(here.conn, changed.partition("/")[2])
    handed = []

    def hand_over(cfg, conn=None):  # a lookup took the lock in the wait, and changed Song 9
        if handed:
            return False
        assert conn is not None and not conn.in_transaction
        handed.append(True)
        add_version(here.cfg.overrides_file, "Band - Song 9", "key=Em&capo=2")  # its chords, as a pin is
        monkeypatch.setattr(_common, "_handoffs", _common._handoffs + 1)
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    transport = waiting_first(there, limits={peer_push.PUSH_PATH: 40_000})
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 0, result.output[-600:]
    assert handed
    assert f"Left {changed}: {sync.CHANGED_HERE}" in result.output
    assert find_song(there.conn, last.key) is None
    assert there.conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 11
    assert "Here takes 0, there takes 1." in run(here, "peer", "sync", HOST, "--push", "--yes").output


def refusing_jobs(there, refuse, *, limits=None, posted=None):
    """``limited`` there, but for ``GET /api/jobs/<id>`` of the ``refuse(n)``-th job asked about (from 1), answered
    503 as a server that went away."""
    seen: list[str] = []
    inner = limited(there, limits=limits, posted=posted)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/api/jobs/"):
            if path not in seen:
                seen.append(path)
            if refuse(seen.index(path) + 1):
                return httpx.Response(503, json={"error": "Restarting."})
        return inner.handle_request(request)

    return httpx.MockTransport(handler)


def test_a_wait_for_the_last_push_that_fails_says_how_far_the_give_got(two, monkeypatch):
    from caracole import peer_push

    here, there, asked, _ = two
    monkeypatch.setattr(peer_push, "DOCUMENT_MAX", 80_000)  # 12 songs in two pushes
    posted = []
    transport = refusing_jobs(there, lambda n: n == 2, limits={peer_push.PUSH_PATH: 80_000}, posted=posted)
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    long_songs(here, 12)
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 1, result.output[-600:]
    assert [p for p, _ in posted].count(peer_push.PUSH_PATH) == 2, result.output[-400:]  # the last sent
    given = result.output.count("  Gave song/")
    said = " ".join(result.output.split())
    assert 0 < given < 12 and f"Couldn't give them 12: {given} given in the first push of 2; then push 2 of 2: " \
        "http://localhost:8737 answered 503: Restarting. The pushes taken there stay taken; the next sync gives " \
        "the rest." in said, said[-600:]


def test_the_units_a_give_left_before_its_first_push_are_said_when_that_push_is_never_seen_taken(two, monkeypatch):
    from caracole import peer_file, peer_push

    here, there, asked, _ = two
    monkeypatch.setattr(peer_push, "DOCUMENT_MAX", 40_000)
    transport = refusing_jobs(there, lambda n: n == 1, limits={peer_push.PUSH_PATH: 40_000})
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: transport)
    long_songs(here, 12)
    creep = here.song("Radiohead", "Creep", sheet=b"%PDF" + b"\0" * peer_push.FILE_MAX)  # 64 MiB and 4 bytes
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 1 and "answered 503" in result.output, result.output[-600:]
    assert f"Left song/{creep.key}: {peer_file.TOO_BIG}" in result.output


def test_a_song_kept_here_against_a_removal_there_answers_its_removal_too(two):
    """Creep changed here and removed there, the owner keeping here's: the song is given, its removal there part of
    that answer (neither taken nor left), and the give clears the tombstone there, so the two then agree."""
    from caracole.get import read_progress_line
    from caracole.removal import plan_removal, remove_song

    here, there, _, _ = two
    creep = there.song()
    assert run(here, "peer", "sync", HOST, "--push", "--yes").exit_code == 0  # synced: Creep on both
    add_version(here.cfg.overrides_file, "Radiohead - Creep", "key=Em&capo=0")  # changed here
    remove_song(there.conn, there.cfg, plan_removal(there.conn, there.cfg, find_song(there.conn, creep.key)))
    result = run(here, "peer", "sync", HOST, "--push", "--yes", "--progress", f"--choose=here:song/{creep.key}")
    assert result.exit_code == 0, result.output
    units = [(e["id"], e["outcome"], e.get("why", "")) for e in map(read_progress_line, result.output.splitlines())
             if e is not None and e.get("event") == "unit"]
    assert units == [(f"song/{creep.key}", "given", "")], units
    assert find_song(here.conn, creep.key) is not None and removed_song(here.conn, creep.key) is None
    assert find_song(there.conn, creep.key) is not None and removed_song(there.conn, creep.key) is None
    assert json.loads(run(here, "peer", "diff", HOST, "--json").output)["differences"] == []


def test_a_removal_left_beside_its_songs_conflict_is_left_again_never_taken_at_the_next_sync(two):
    here, there, _, _ = two
    creep = there.song()
    assert run(here, "peer", "sync", HOST, "--push", "--yes").exit_code == 0
    add_version(here.cfg.overrides_file, "Radiohead - Creep", "key=Em&capo=0")
    from caracole.removal import plan_removal, remove_song

    remove_song(there.conn, there.cfg, plan_removal(there.conn, there.cfg, find_song(there.conn, creep.key)))
    for _ in range(2):  # the song's conflict left each time, unsettled
        result = run(here, "peer", "sync", HOST, "--push", "--yes")
        assert result.exit_code == 0, result.output
        assert f"Left removed/{creep.key}: {sync.SONG_HERE}" in result.output
        assert f"Took removed/{creep.key}" not in result.output
    found = {d["id"]: d["proposal"] for d in json.loads(run(here, "peer", "diff", HOST, "--json").output)["differences"]}
    assert found == {f"song/{creep.key}": "conflict", f"removed/{creep.key}": "theirs"}
    assert f"removed/{creep.key}" not in (sync.base_of(here.conn, sync.own_id(there.conn)) or {})  # nothing agreed


def test_a_song_the_take_respells_is_given_as_the_take_left_it(two):
    """here's "eagles - Desperado", there's "Eagles - Hotel California": the take respells Desperado as there writes
    the artist, a change of the sync's own, and the give then pushes it as it is now."""
    here, there, _, _ = two
    desperado = here.song("eagles", "Desperado", version=None)
    there.song("Eagles", "Hotel California", version=None)
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 0, result.output
    assert find_song(here.conn, desperado.key).artist == "Eagles"
    assert sync.CHANGED_HERE not in result.output
    assert find_song(there.conn, desperado.key) is not None
    assert json.loads(run(here, "peer", "diff", HOST, "--json").output)["differences"] == []


def test_a_song_the_take_respells_and_a_lookup_then_changes_is_left_changed_here(two, monkeypatch):
    """The respelling the take wrote is the sync's own; a change after it, a lookup's, still leaves the song."""
    from caracole.commands import peer as peer_cmd

    here, there, _, _ = two
    desperado = here.song("eagles", "Desperado", version=None)
    there.song("Eagles", "Hotel California", version=None)
    push = peer_cmd._push

    def after_a_lookup(cfg, *args, **kw):  # the lock let go of between the take and the give: a lookup pins a key
        add_version(here.cfg.overrides_file, "Eagles - Desperado", "key=Em&capo=2")
        return push(cfg, *args, **kw)

    monkeypatch.setattr(peer_cmd, "_push", after_a_lookup)
    result = run(here, "peer", "sync", HOST, "--push", "--yes")
    assert result.exit_code == 0, result.output
    assert f"Left song/{desperado.key}: {sync.CHANGED_HERE}" in result.output
    assert find_song(there.conn, desperado.key) is None


def test_a_song_the_take_respells_is_asked_there_at_its_digest_as_the_take_left_it(two):
    here, there, _, _ = two
    desperado = here.song("eagles", "Desperado", version=None)
    there.song("Eagles", "Hotel California", version=None)
    result = run(here, "peer", "sync", HOST, "--yes", "--here", "192.168.1.10:8737")
    assert result.exit_code == 0, result.output
    unit = f"song/{desperado.key}"
    job = there.app.queue.snapshot()[0]
    assert [list(s.args) for s in job.steps] == [["peer", "pull", f"--unit={here.units()[unit].digest}:-:{unit}",
                                                  "--", "http://192.168.1.10:8737"]]
