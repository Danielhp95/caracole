"""One caracole at a time: every command that sends requests or writes takes caracole's lock.

Another caracole (the nightly run, say) holds the lock here the way it would: an open file of
its own on state/caracole.lock, flocked. A command started meanwhile must wait, say which
caracole it waits for, and do nothing until the lock is free; a read-only command doesn't wait
at all. A command that waited also sees what the other one did: after a block, the provider
is cooling down, and the command sends nothing. The last test runs ``caracole run`` in a
process of its own. Every site is a fake behind ``httpx.MockTransport``.
"""

from __future__ import annotations

import fcntl
import gzip
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from helpers.locks import waiting_for
from helpers.ug_pages import make_tab_page_html, version_dict
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.health import record_block
from caracole.lyrics import Lyrics
from caracole.songs import update_song
from caracole.ug.index import mark_built

from conftest import add_song, subprocess_pythonpath

WAITING = "Another caracole is running (pid 4242: run); waiting for it to finish."
PERSIANA = "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-101"
LRCLIB_HIT = Path(__file__).parent / "fixtures" / "lrclib" / "get_hit.json"
SPANISH_LYRICS = "Cruzo la plaza con el café frío\ny cuento las luces del tren de las seis\n"
# Environment load_config would read; none of it may leak into a test.
OUTSIDE_SETTINGS = (
    "CREDENTIALS_DIRECTORY", "CARACOLE_CONFIG", "CARACOLE_NTFY_TOKEN", "CARACOLE_SPOTIFY_CLIENT_SECRET",
)


class Sites:
    """Every provider's site: answers by host and path (the query left out), else a 404."""

    def __init__(self):
        self.routes: dict[str, tuple[int, str]] = {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        status, body = self.routes.get(f"{request.url.host}{request.url.path}", (404, "not here"))
        return httpx.Response(status, text=body)

    def transport(self, provider: str) -> httpx.BaseTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def sites(monkeypatch) -> Sites:
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    return s


@pytest.fixture
def config(tmp_path) -> Path:
    folders = (("library_dir", "lib"), ("music_dir", "music"), ("state_dir", "state"),
               ("cache_dir", "cache"))
    lines = [f'{key} = "{tmp_path / name}"' for key, name in folders]
    for provider in ("ug", "lrclib", "lacuerda", "gtptabs", "musescore"):
        lines += [f"[providers.{provider}]", "delay = [0, 0]"]
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path  # beside conftest's conn: tmp_path/state/caracole.sqlite is the database


@contextmanager
def another_caracole(tmp_path: Path):
    """Another caracole holding the lock, as the nightly run would: its own open file, flocked."""
    lock = tmp_path / "state" / "caracole.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.write(fd, b"4242 run\n")
    try:
        yield
    finally:
        os.close(fd)


class Started:
    """A command run through the CLI in a thread of its own, so the test can hold the lock."""

    def __init__(self, config: Path, args: list[str]):
        self.result = None
        self.lock = config.parent / "state" / "caracole.lock"  # the config's state_dir
        self.thread = threading.Thread(target=self._run, args=(config, args), daemon=True)
        self.thread.start()

    def _run(self, config: Path, args: list[str]) -> None:
        self.result = CliRunner().invoke(build_app(), ["--config", str(config), *args])

    def still_waiting(self) -> bool:
        return waiting_for(self.lock, self.thread.is_alive)

    def finished(self):
        self.thread.join(15)
        assert not self.thread.is_alive(), "the command never finished"
        return self.result


# --- what each command needs, and what it leaves once it ran -----------------------------------


def index_row(conn, tab_id: int, artist_key: str, song_key: str) -> None:
    conn.execute(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, 'chords', '1', '2026-10-01T00:00:00Z', ?)",
        (tab_id, artist_key, song_key, f"{artist_key}/{song_key}-chords-{tab_id}"),
    )


def built_index(conn) -> None:
    index_row(conn, 2002, "radiohead", "creep")
    index_row(conn, 5001, "stone-temple-pilots", "creep")
    mark_built(conn, _common.utcnow())


def a_song_to_fetch(tmp_path, sites, conn) -> None:
    song = add_song(conn, "Soda Stereo", "Persiana Americana")
    update_song(conn, song.id, match_decision="accept", match_step="exact",
                match_artist_key="soda-stereo", match_song_key="persiana-americana")
    index_row(conn, 101, "soda-stereo", "persiana-americana")
    tab = version_dict(101, song="Persiana Americana", artist="Soda Stereo", tab_url=PERSIANA)
    content = "[tab][ch]Am[/ch]   [ch]F[/ch]\r\nwalking down the river road tonight[/tab]"
    sites.routes["tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-101"] = (
        200, make_tab_page_html(tab, [], content=content))


def a_song_waiting_for_lyrics(tmp_path, sites, conn) -> None:
    add_song(conn, "Soda Stereo", "De Música Ligera")
    sites.routes["lrclib.net/api/get"] = (200, LRCLIB_HIT.read_text(encoding="utf-8"))


def a_spanish_song(tmp_path, sites, conn) -> None:
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    lyrics = Lyrics(plain=SPANISH_LYRICS, synced=None, instrumental=False, duration=None,
                    lrclib_id=None)
    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics.to_json())


def a_song_without_a_guitar_pro_file(tmp_path, sites, conn) -> None:
    add_song(conn, "Blur", "Beetlebum")
    sites.routes["gtptabs.com/sitemapGoogle.xml"] = (
        200, '<?xml version="1.0" encoding="UTF-8"?><sitemapindex><sitemap>'
             "<loc>http://gtptabs.com/sitemapGoogle1.xml</loc></sitemap></sitemapindex>")


def a_song_for_musescore(tmp_path, sites, conn) -> None:
    add_song(conn, "Oasis", "Wonderwall")
    sites.routes["musescore.com/sitemaps/song-index.xml"] = (
        200, '<?xml version="1.0" encoding="UTF-8"?><sitemapindex><sitemap>'
             "<loc>https://musescore.com/sitemaps/song-index/sitemap_songs1.xml</loc></sitemap></sitemapindex>")


def sitemap_files(tmp_path, sites, conn) -> None:
    folder = tmp_path / "sitemaps"
    folder.mkdir()
    urlset = ('<?xml version="1.0" encoding="UTF-8"?><urlset><url><loc>'
              "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-2002"
              "</loc></url></urlset>")
    (folder / "sitemap1.xml.gz").write_bytes(gzip.compress(urlset.encode()))
    (folder / "sitemap_last.xml").write_text(urlset, encoding="utf-8")


def an_index_to_refresh(tmp_path, sites, conn) -> None:
    built_index(conn)
    sites.routes["www.ultimate-guitar.com/sitemap.xml"] = (
        200, '<?xml version="1.0" encoding="UTF-8"?><sitemapindex></sitemapindex>')


def a_wanted_line(tmp_path, sites, conn) -> None:
    (tmp_path / "lib").mkdir(exist_ok=True)
    (tmp_path / "lib" / "wanted.txt").write_text("Radiohead - Creep\n", encoding="utf-8")


def a_song_to_match(tmp_path, sites, conn) -> None:
    built_index(conn)
    add_song(conn, "Radiohead", "Creep")


def nothing(tmp_path, sites, conn) -> None:
    pass


def requested(tmp_path, sites, conn) -> bool:
    return bool(sites.requests)


def has_songs(tmp_path, sites, conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] > 0


def matched(tmp_path, sites, conn) -> bool:
    decided = "SELECT COUNT(*) FROM songs WHERE match_decision IS NOT NULL"
    return conn.execute(decided).fetchone()[0] > 0


def indexed(tmp_path, sites, conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM ug_index").fetchone()[0] > 0


def todo_written(tmp_path, sites, conn) -> bool:
    return (tmp_path / "lib" / "_todo.md").exists()


def rendered(tmp_path, sites, conn) -> bool:
    return db.kv_get(conn, "render:status") is not None


def added_to_wanted_txt(tmp_path, sites, conn) -> bool:
    wanted = tmp_path / "lib" / "wanted.txt"
    return wanted.exists() and "Stone Temple Pilots - Creep" in wanted.read_text(encoding="utf-8")


Step = Callable[[Path, Sites, object], object]


@dataclass(frozen=True)
class Case:
    args: tuple[str, ...]
    setup: Step
    done: Step  # what the command leaves once it ran; false while it waits


WRITERS = [
    Case(("run",), nothing, todo_written),
    Case(("index", "build", "--from", "{tmp}/sitemaps"), sitemap_files, indexed),
    Case(("index", "refresh"), an_index_to_refresh, requested),
    Case(("fetch",), a_song_to_fetch, requested),
    Case(("fetch", "--song", "Soda Stereo - Persiana Americana"), a_song_to_fetch, requested),
    Case(("lyrics",), a_song_waiting_for_lyrics, requested),
    Case(("lacuerda",), a_spanish_song, requested),
    Case(("gtptabs",), a_song_without_a_guitar_pro_file, requested),
    Case(("musescore",), a_song_for_musescore, requested),
    Case(("render",), nothing, rendered),
    Case(("sync",), a_wanted_line, has_songs),
    Case(("add", "Radiohead", "Creep"), nothing, has_songs),
    Case(("match",), a_song_to_match, matched),
    Case(("search", "stone temple pilots creep", "--add", "1"), a_song_to_match,
         added_to_wanted_txt),
]


def argv(case: Case, tmp_path: Path) -> list[str]:
    return [arg.format(tmp=tmp_path) for arg in case.args]


@pytest.mark.parametrize("case", WRITERS, ids=lambda c: " ".join(c.args))
def test_a_command_that_writes_waits_for_another_caracole(tmp_path, config, sites, conn, case):
    case.setup(tmp_path, sites, conn)
    with another_caracole(tmp_path):
        started = Started(config, argv(case, tmp_path))
        assert started.still_waiting()
        assert not case.done(tmp_path, sites, conn)  # nothing sent, nothing written yet
    result = started.finished()
    assert WAITING in result.output, result.output
    assert case.done(tmp_path, sites, conn), result.output


READERS = [("search", "creep"), ("match", "--dry-run"), ("index", "stats")]


@pytest.mark.parametrize("args", READERS, ids=" ".join)
def test_a_command_that_only_reads_doesnt_wait(tmp_path, config, sites, conn, args):
    a_song_to_match(tmp_path, sites, conn)
    with another_caracole(tmp_path):
        started = Started(config, list(args))
        started.thread.join(10)
        waited = started.thread.is_alive()
    result = started.finished()
    assert not waited, result.output
    assert result.exit_code == 0, result.output
    assert WAITING not in result.output


# The commands that ask a provider, with what they need and the provider they ask.
ASKERS = [
    pytest.param(("fetch",), a_song_to_fetch, "ug", id="fetch"),
    pytest.param(("lyrics",), a_song_waiting_for_lyrics, "lrclib", id="lyrics"),
    pytest.param(("lacuerda",), a_spanish_song, "lacuerda", id="lacuerda"),
    pytest.param(("gtptabs",), a_song_without_a_guitar_pro_file, "gtptabs", id="gtptabs"),
    pytest.param(("musescore",), a_song_for_musescore, "musescore", id="musescore"),
    pytest.param(("index", "refresh"), an_index_to_refresh, "ug", id="index refresh"),
]


@pytest.mark.parametrize("args,setup,provider", ASKERS)
def test_a_command_that_waited_for_a_caracole_that_got_blocked_asks_nothing(
    tmp_path, config, sites, conn, args, setup, provider
):
    # The run it waited for met a 403: the provider is cooling down when the lock comes free.
    setup(tmp_path, sites, conn)
    with another_caracole(tmp_path):
        started = Started(config, list(args))
        assert started.still_waiting()
        record_block(conn, provider, _common.utcnow(), f"{provider}: 403: HTTP 403")
    result = started.finished()
    assert result.exit_code == 0, result.output
    assert sites.requests == [], result.output
    assert "cooling down" in result.output


def lock_is_free(tmp_path: Path) -> bool:
    fd = os.open(tmp_path / "state" / "caracole.lock", os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


def test_review_never_holds_the_lock_while_it_waits_for_you(tmp_path, config, conn, monkeypatch):
    # You may take your time: the nightly run must not wait for an answer.
    import typer

    song = add_song(conn, "宋冬野", "斑马斑马")
    candidate = {"artist_key": "song-dongye", "song_key": "ban-ma-ban-ma", "score": 80.0,
                 "step": "fuzzy_title"}
    update_song(conn, song.id, review=True, match_candidates=[candidate])
    free_at_each_prompt = []

    def answer(prompt, **kwargs):
        free_at_each_prompt.append(lock_is_free(tmp_path))
        return "s"

    monkeypatch.setattr(typer, "prompt", answer)
    result = CliRunner().invoke(build_app(), ["--config", str(config), "review"])
    assert result.exit_code == 0, result.output
    assert free_at_each_prompt and all(free_at_each_prompt)


def test_the_nightly_run_waits_for_another_caracole_process(tmp_path, config):
    # Two processes: this one holds the lock, as a `caracole-admin index build` would, and
    # `caracole run` starts in a process of its own. Its library is empty, so it asks no site;
    # the proxy is a dead end all the same.
    src = Path(__file__).resolve().parents[1] / "src"
    env = {
        "HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": subprocess_pythonpath(src),
        "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
    }
    todo = tmp_path / "lib" / "_todo.md"
    with another_caracole(tmp_path):
        run = subprocess.Popen(
            [sys.executable, "-m", "caracole", "--config", str(config), "run"], env=env,
            cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            lock = tmp_path / "state" / "caracole.lock"
            assert waiting_for(lock, lambda: run.poll() is None, timeout=3)  # it waits for the lock
            assert not todo.exists()
        except BaseException:
            run.kill()
            raise
    out, err = run.communicate(timeout=60)
    assert run.returncode == 0, err[-3000:]
    assert WAITING in err
    assert todo.is_file() and f"to-do page needs you: {todo}" in out  # the summary names it
