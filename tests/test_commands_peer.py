"""``caracole peer diff``, run through the CLI against another library's caracole serve (a WebApp, in this process)."""

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
from caracole.db import kv_set_json
from caracole.overrides import add_version
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from test_web_app import ALLOWED, HOST, Recorder


def write_config(root: Path) -> Path:
    path = root / "caracole.toml"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(f'library_dir = "{root / "lib"}"\nmusic_dir = "{root / "music"}"\n'
                    f'state_dir = "{root / "state"}"\ncache_dir = "{root / "cache"}"\n', encoding="utf-8")
    return path


def side(root: Path):
    """A library of its own, its config and an open database."""
    cfg = load_config(write_config(root), env={"HOME": str(root / "home")})
    return cfg, db.connect(cfg.db_path)


@pytest.fixture
def two(tmp_path, monkeypatch):
    """This library (here) and the phone's (there), whose caracole serve answers at http://localhost:8737."""
    here_cfg, here = side(tmp_path / "here")
    there_cfg, there = side(tmp_path / "there")
    app = WebApp(there_cfg, JobQueue(Recorder(), limit=3), allowed=ALLOWED, csrf="tok")
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        answer = app.handle(Request(request.method, request.url.raw_path.decode(), dict(request.headers)))
        return httpx.Response(answer.status, headers=answer.headers, content=answer.body)

    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: httpx.MockTransport(handler))
    yield tmp_path / "here", here, there_cfg, there, asked
    here.close()
    there.close()


def run(root, *args):
    return CliRunner().invoke(build_app(), ["--config", str(root / "caracole.toml"), *args])


def test_diff_lists_the_songs_each_side_has_alone_and_changes_nothing(two):
    root, here, there_cfg, there, asked = two
    add_song(here, "Radiohead", "Creep")
    add_song(here, "Oasis", "Wonderwall")
    add_song(there, "Oasis", "Wonderwall")
    add_song(there, "Estopa", "Tu Calorro")
    add_version(there_cfg.overrides_file, "Oasis - Wonderwall", "key=Em&capo=2")  # chords changed on the phone

    result = run(root, "peer", "diff", HOST)
    assert result.exit_code == 0, result.output
    assert asked == ["/api/peer/state"]
    out = result.output
    assert "The two never synced" in out
    assert "3 differences, 1 conflict:" in out
    lines = [" ".join(line.split()) for line in out.splitlines()]
    assert "keep here's Radiohead - Creep (only here)" in lines
    assert "take there's Estopa - Tu Calorro (only there)" in lines
    assert "CONFLICT Oasis - Wonderwall (on both sides, different, and never synced)" in lines
    assert sync.own_id(here) is None and sync.own_id(there) is None  # nothing written on either side


def test_once_synced_the_change_made_on_one_side_alone_is_taken_from_it(two):
    root, here, there_cfg, there, asked = two
    add_song(here, "Oasis", "Wonderwall")
    add_song(there, "Oasis", "Wonderwall")
    peer = sync.make_id(there)
    from caracole.overrides import Overrides
    as_synced = {u.id: u.digest for u in sync.library_state(here, Overrides(), []).values()}
    kv_set_json(here, sync.BASE_KEY + peer, as_synced)
    add_version(there_cfg.overrides_file, "Oasis - Wonderwall", "key=Em&capo=2")
    add_song(here, "Radiohead", "Creep")

    result = run(root, "peer", "diff", f"http://{HOST}/", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["synced_before"] is True and data["peer"]["server"] == peer
    assert {d["label"]: (d["proposal"], d["why"]) for d in data["differences"]} == {
        "Oasis - Wonderwall": ("theirs", "changed there since the last sync"),
        "Radiohead - Creep": ("mine", "new here since the last sync"),
    }


def test_the_same_caracole_twice_is_said_and_nothing_compared(two):
    root, here, there_cfg, there, asked = two
    sync.make_id(there)
    db.kv_set(here, sync.ID_KEY, sync.own_id(there))  # a copy of the database
    result = run(root, "peer", "diff", HOST)
    assert result.exit_code == 1 and "is this one" in result.output


def test_nothing_answering_is_said_plainly(two, monkeypatch):
    root = two[0]

    def refused(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr("caracole.commands.peer.transport_for_peer", lambda: httpx.MockTransport(refused))
    result = run(root, "peer", "diff", "192.168.1.20:8737")
    assert result.exit_code == 1 and "Nothing answered at http://192.168.1.20:8737" in result.output


def test_identical_libraries_differ_in_nothing(two):
    root = two[0]
    result = run(root, "peer", "diff", HOST)
    assert result.exit_code == 0 and "Nothing differs." in result.output
