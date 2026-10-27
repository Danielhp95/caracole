"""A Guitar Pro file downloaded from the page caracole serve serves, in a real Chromium: saved under its song's name
("Joaquín Sabina - 19 Días y 500 Noches (2).ptb"), as web/app.py's header and the link's ``download`` say it,
whatever it is called in the song's folder."""

from __future__ import annotations

import threading
import time

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.guitar import keep_guitar

from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS

SONG = ("Joaquín Sabina", "19 Días y 500 Noches")


@pytest.fixture
def served(cfg, conn):
    """The library page on a socket, with a song that has a Guitar Pro file and a Power Tab one."""
    song = add_song(conn, *SONG)
    keep_guitar(conn, cfg, song, b"FICHIER GUITAR PRO v5.00", name="guitar-1.gp5", tab="1")
    keep_guitar(conn, cfg, song, b"ptab", name="guitar-2.ptb", tab="2")
    conn.commit()
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


def saved(folder, timeout=15.0):
    """The names of the files Chromium finished saving into ``folder``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done = sorted(p.name for p in folder.iterdir() if not p.name.endswith(".crdownload"))
        if done:
            return done
        time.sleep(0.05)
    return []


@pytest.mark.parametrize(("label", "name"), [
    ("Guitar Pro 1", "Joaquín Sabina - 19 Días y 500 Noches.gp5"),
    ("Power Tab 2", "Joaquín Sabina - 19 Días y 500 Noches (2).ptb"),
])
def test_a_guitar_pro_file_saves_under_its_songs_name(served, tmp_path, label, name):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    try:
        page._send("Browser.setDownloadBehavior", behavior="allow", downloadPath=str(downloads))
        page.open(served)
        assert page.wait("!!document.querySelector('.line-more')", 15)
        page.click(".line-more")
        page.click(".tile-guitar button.vchip")  # its files, in the card's drawer: each one's Download
        link = (f"[...document.querySelectorAll('.drawer a[download]')]"
                f".find((a) => a.getAttribute('aria-label').startsWith('Download ' + {label!r}))")
        assert page.wait(f"!!{link}")
        assert page.js(f"{link}.getAttribute('download')") == name
        page.js(f"{link}.click()")
        assert saved(downloads) == [name]
    finally:
        page.close()
