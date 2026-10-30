"""``caracole run`` through the CLI: the report on stdout, the log on stderr, the exit codes.

Each test writes a caracole.toml rooted in tmp_path, with no pause between
requests. Every site is a fake behind ``httpx.MockTransport``, handed to the
clients through ``caracole.commands._common.transport_for``, so no request can
reach the network.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from helpers.lacuerda_site import listing_page
from typer.testing import CliRunner

import caracole.pipeline as pipeline
from caracole.cli import build_app
from caracole.commands import _common

# Environment load_config, the log or the report would read; none of it may leak into a test.
OUTSIDE_SETTINGS = (
    "CARACOLE_CONFIG",
    "JOURNAL_STREAM", "NO_COLOR",
)
NTFY = "https://ntfy.example/caracole-test"
SONG = "epic - I'm not sorry for loving you"
LISTING = re.compile(r"/tabs/([a-z_]+)/index(\d+)\.html")


class Sites:
    """LRCLIB answers every request with ``lrclib`` (503: overloaded, with Retry-After: 1, as live, so caracole asks
    each once more after a second); LaCuerda has three
    pages of artists for each initial, as its listings of every artist are paged; UG must not be
    asked at all, and Megalobiz, AZLyrics, gtptabs.com, harptabs.com, gametabs.net and MuseScore are turned off; ntfy takes every
    post."""

    def __init__(self, lrclib: int = 503):
        self.lrclib = lrclib
        self.requests: list[str] = []  # LRCLIB's
        self.lacuerda: list[str] = []
        self.posts: list[httpx.Request] = []

    def transport(self, provider: str) -> httpx.BaseTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if provider == "ntfy":
                self.posts.append(request)
                return httpx.Response(200, json={"id": "x"})
            listing = LISTING.fullmatch(request.url.path)
            if provider == "lacuerda" and listing:
                self.lacuerda.append(str(request.url))
                letter, start = listing.group(1), int(listing.group(2))
                artists = [(f"{letter}_{start}", f"Artista {letter} {start}", 1)]
                return httpx.Response(200, text=listing_page(artists, pages=3, page=start // 100))
            if provider != "lrclib":
                raise AssertionError(f"unexpected {provider} request: {request.url}")
            self.requests.append(str(request.url))
            return httpx.Response(self.lrclib, headers={"Retry-After": "1"}, json={"name": "ServerOverloaded"})

        return httpx.MockTransport(handler)


@pytest.fixture
def sites(monkeypatch):
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    s = Sites()
    monkeypatch.setattr(_common, "transport_for", s.transport)
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return s


@pytest.fixture
def clock(monkeypatch):
    """The run's clock: it starts at 100 s, and every later reading is 3.2 s on."""
    readings = iter([100.0])
    monkeypatch.setattr(pipeline, "clock", lambda: next(readings, 103.2))


def write_config(tmp_path: Path, *, ntfy: bool = False) -> Path:
    lines = [
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
    ]
    for provider in ("ug", "lrclib", "lacuerda"):
        lines += [f"[providers.{provider}]", "delay = [0, 0]"]
    for provider in ("megalobiz", "azlyrics", "gtptabs", "harptabs", "gametabs", "musescore"):  # sites these tests leave out
        lines += [f"[providers.{provider}]", "enabled = false"]
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def wanted(tmp_path: Path, *lines: str) -> None:
    lib = tmp_path / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "wanted.txt").write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def run(tmp_path: Path, *args: str, ntfy: bool = False):
    path = write_config(tmp_path, ntfy=ntfy)
    return CliRunner().invoke(build_app(), ["--config", str(path), *args, "run"])


# --- the user's night: one song, no index yet, LRCLIB overloaded ------------------------------


def the_users_night(tmp_path: Path) -> str:
    return (
        "First, build the index once: caracole index build (about 10 minutes).\n"
        "Until then, no song is matched or looked for on Ultimate Guitar.\n"
        "\n"
        "Songs: 1 in wanted.txt, 1 new.\n"
        "LaCuerda: 30 pages of artists read.\n"
        "\n"
        f"1 thing on your to-do page needs you: {tmp_path / 'lib' / '_todo.md'}\n"
        "LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.\n"
        "Requests: Ultimate Guitar 0 of 60, LRCLIB 2 of 200, "
        "LaCuerda 30 of 30 (used up: the rest waits for the next run).\n"
        "Took 3 s.\n"
    )


def test_one_song_no_index_and_lrclib_down_reads_as_a_short_report(tmp_path, sites, clock):
    wanted(tmp_path, SONG)
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    assert result.stdout == the_users_night(tmp_path)
    assert result.stderr == ""  # nothing went wrong that the report doesn't say
    # /api/get, then once more after its Retry-After; never /api/search, as a busy LRCLIB is no miss.
    assert [url.split("?")[0] for url in sites.requests] == ["https://lrclib.net/api/get"] * 2
    # LaCuerda's listings of every artist, three pages an initial, as far as its budget goes: the next
    # night goes on from the eleventh initial.
    assert sites.lacuerda[:4] == [f"https://acordes.lacuerda.net/tabs/{p}" for p in (
        "_num/index0.html", "_num/index100.html", "_num/index200.html", "a/index0.html")]
    assert len(sites.lacuerda) == 30


def test_lrclib_down_for_many_songs_is_one_line(tmp_path, sites, clock):
    # Three songs fail, then caracole stops asking LRCLIB: the two songs it never asked about wait too.
    wanted(tmp_path, *(f"epic - Song {n}" for n in range(5)))
    result = run(tmp_path)
    assert result.exit_code == 0, result.output
    problems = [line for line in result.stdout.splitlines() if line.startswith("LRCLIB")]
    assert problems == ["LRCLIB didn't answer (HTTP 503) and caracole stopped asking it, so the lyrics of 5 songs "
                        "will be tried again on the next run."]
    assert len(sites.requests) == 6  # /api/get, and once more after its Retry-After, for each of the three


def test_quiet_keeps_what_needs_you_and_what_went_wrong(tmp_path, sites, clock):
    wanted(tmp_path, SONG)
    result = run(tmp_path, "-q")
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "First, build the index once: caracole index build (about 10 minutes).\n"
        "Until then, no song is matched or looked for on Ultimate Guitar.\n"
        "\n"
        "LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.\n"
    )
    assert result.stderr == ""


def test_verbose_adds_a_line_per_request_and_per_step_on_stderr_only(tmp_path, sites, clock):
    wanted(tmp_path, SONG)
    result = run(tmp_path, "-v")
    assert result.exit_code == 0, result.output
    assert result.stdout == the_users_night(tmp_path)
    log = result.stderr.splitlines()
    requests = [line for line in log if line.startswith("LRCLIB GET ")]
    assert len(requests) == 2
    assert requests[0].startswith("LRCLIB GET https://lrclib.net/api/get?")
    assert "→ 503 Service Unavailable in " in requests[0] and requests[0].endswith(" s (1 of 200 requests)")
    assert requests[1].startswith("LRCLIB GET https://lrclib.net/api/get?")  # once more, after its Retry-After
    assert [line for line in log if "Retry-After: 1; asking once more in " in line]
    assert "lyrics: 0 found, 0 missing, 0 instrumental, 1 error" in log
    assert not [line for line in log if "httpx" in line or "HTTP Request" in line]  # the library stays quiet


def test_very_verbose_lets_the_libraries_speak_with_their_names(tmp_path, sites, clock):
    wanted(tmp_path, SONG)
    log = run(tmp_path, "-vv").stderr.splitlines()
    assert [line for line in log if line.startswith("httpx: HTTP Request: GET https://lrclib.net/api/get?")]
    assert [line for line in log if line.startswith("caracole.http: LRCLIB GET ")]


def test_ntfy_gets_the_summarys_own_words(tmp_path, sites, clock):
    wanted(tmp_path, SONG)
    result = run(tmp_path, ntfy=True)
    assert result.exit_code == 0, result.output
    [post] = sites.posts
    assert str(post.url) == NTFY and post.headers["title"] == "caracole run"
    assert post.content.decode() == result.stdout


def test_a_bug_exits_1_and_leaves_its_traceback_in_the_log_behind_one_line(tmp_path, sites, clock, monkeypatch):
    def broken(ctx):
        raise KeyError("boom")

    steps = pipeline.default_steps
    monkeypatch.setattr(pipeline, "default_steps",
                        lambda: [pipeline.Step("match", broken), *(s for s in steps() if s.name == "todo")])
    result = run(tmp_path)
    assert result.exit_code == 1
    assert ("The match step failed: KeyError: 'boom'. That's a bug in caracole: its traceback is in the log, and "
            "the run exits 1.") in result.stdout.splitlines()
    first, second, *rest, page = result.stderr.splitlines()
    assert first == "error: The match step failed: KeyError: 'boom'. That's a bug in caracole; its traceback follows."
    assert second == "Traceback (most recent call last):" and rest[-1] == "KeyError: 'boom'"
    # Then the pages, written all the same: of a library with no songs, a warning (page_log.py).
    assert page.startswith("warning: library page written to ") and " with no songs: " in page


@pytest.mark.slow
def test_under_systemd_every_line_carries_its_journal_priority(tmp_path):
    # As caracole.service runs it: stdout and stderr both the journal's stream, which JOURNAL_STREAM names.
    # A real process, as the journal is told apart by the file stdout and stderr are. Its library is empty,
    # so it asks no site; the proxy is a dead end all the same.
    import os
    import subprocess
    import sys

    from conftest import subprocess_pythonpath

    config = write_config(tmp_path)
    src = Path(__file__).resolve().parents[1] / "src"
    journal = tmp_path / "journal"
    with open(journal, "w+", encoding="utf-8") as f:
        st = os.fstat(f.fileno())
        env = {
            "HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src),
            "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
            "JOURNAL_STREAM": f"{st.st_dev}:{st.st_ino}",
        }
        done = subprocess.run([sys.executable, "-m", "caracole", "--config", str(config), "run"], env=env,
                              cwd=tmp_path, stdout=f, stderr=f, timeout=120)
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert done.returncode == 0, lines
    # The library page it wrote, of a library with no songs: a warning, with what tells why (page_log.py).
    [page] = [line for line in lines if "library page" in line]
    assert page.startswith("<4>library page written to ") and " with no songs: " in page
    lines.remove(page)
    assert lines[:2] == ["<4>First, build the index once: caracole index build (about 10 minutes).",
                         "<4>Until then, no song is matched or looked for on Ultimate Guitar."]
    assert all(line[:3] in ("<3>", "<4>", "<6>", "<7>") for line in lines), lines  # and no blank line
    assert "<6>Requests: Ultimate Guitar 0 of 60, LRCLIB 0 of 200, LaCuerda 0 of 30." in lines
    assert not [line for line in lines if "\x1b[" in line]
