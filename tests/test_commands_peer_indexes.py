"""The site indexes between two computers' caracoles: what ``caracole peer sync`` asks the other side for and gives it
of them (peer_sync.py ``Peer.index``, peer_import.py ``Uploader``), against the other library's caracole serve (a
WebApp in this process), as tests/test_commands_peer.py asks it."""

from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime

import httpx
import pytest

from caracole import index_transfer, peer_import, site_index
from caracole import peer_sync as sync
from caracole.web.app import Request, WebApp

from test_commands_peer import HOST, InProcess, Side

THERE = f"http://{HOST}"
READ = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)


@pytest.fixture
def sides(tmp_path, monkeypatch):
    """This library (here) and another's (there), whose caracole serve answers at THERE: each request it is sent
    recorded, by its method and path."""
    here, there = Side(tmp_path / "here"), Side(tmp_path / "there", InProcess())
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((request.method, request.url.path))
        answer = WebApp.finish(there.app.handle(Request(request.method, request.url.raw_path.decode(),
                                                        dict(request.headers), request.content)))
        body = answer.body if answer.stream is None else answer.stream.read()
        if answer.stream is not None:
            answer.stream.close()
        return httpx.Response(answer.status, headers=answer.headers, content=body)

    transport = httpx.MockTransport(handler)
    yield here, there, asked, transport
    here.conn.close()
    there.conn.close()


def gtptabs_rows(side, locs, at=READ):
    from caracole import gtptabs_fetch

    site = gtptabs_fetch.SITE
    site_index._store(side.conn, site, "sitemap-tabs-1.xml", [site.row(loc) for loc in locs],
                      {"etag": '"1"', "last_modified": None}, at)


def rows_of(path, table):
    file = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return file.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        file.close()


# --- the other side's indexes, taken ------------------------------------------------------------------------------


def test_the_others_indexes_of_the_sites_asked_are_streamed_into_a_file_of_their_own(sides, tmp_path):
    _, there, asked, transport = sides
    gtptabs_rows(there, ["https://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/tabs/2/blur/beetlebum.html"])
    to = tmp_path / "theirs.sqlite"
    with sync.Peer(THERE, transport=transport) as peer:
        peer.index(to, ["gtptabs"])
    assert asked == [("GET", "/api/peer/index")]
    assert stat.S_IMODE(to.stat().st_mode) == 0o600
    assert index_transfer._meta(to)["sites"] == '["gtptabs"]' and rows_of(to, "gtptabs_index") == 2


def test_a_refused_ask_for_the_indexes_is_said_and_leaves_no_file(sides, tmp_path):
    _, _, _, transport = sides
    to = tmp_path / "theirs.sqlite"
    with sync.Peer(THERE, transport=transport) as peer, pytest.raises(sync.PeerError, match="answered 400: no site"):
        peer.index(to, ["nosuch"])
    assert not to.exists()

    def older(request):  # a caracole serve older than the route
        return httpx.Response(404, json={"error": "Not found"})

    with sync.Peer(THERE, transport=httpx.MockTransport(older)) as peer, pytest.raises(sync.PeerError):
        peer.index(to, [])
    assert not to.exists()


# --- this side's indexes, given ----------------------------------------------------------------------------------


def test_an_upload_sends_a_file_to_the_others_import_in_parts_as_its_page_does(sides, tmp_path, monkeypatch):
    _, there, asked, transport = sides
    monkeypatch.setattr(peer_import, "PART_MAX", 1000)  # the parts there say they may be: 1000 bytes
    data = bytes(range(256)) * 10
    path = tmp_path / "caracole-index.sqlite"
    path.write_bytes(data)
    with peer_import.Uploader(THERE, transport=transport) as uploader:
        import_id = uploader.upload(path)
    assert asked == [("GET", "/api/peer/state"), ("POST", "/sync/import/open"),
                     *[("POST", "/sync/import/part")] * 3]
    assert peer_import.whole(there.cfg.state_dir, import_id).read_bytes() == data
    folder = there.cfg.state_dir / "peer" / f"import-{import_id}"
    assert peer_import.opened_name(folder) == "caracole-index.sqlite"


def test_an_upload_the_other_side_refuses_is_said(sides, tmp_path):
    _, there, _, transport = sides
    path = tmp_path / "caracole-index.sqlite"
    path.write_bytes(b"x" * 10)
    peer_import.open_import(there.cfg.state_dir, size=4, name="another.caracole")  # one is open there already
    with peer_import.Uploader(THERE, transport=transport) as uploader:
        with pytest.raises(sync.PeerError, match="answered 409: " + peer_import.BUSY.split(":")[0]):
            uploader.upload(path)
