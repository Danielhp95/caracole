"""``caracole youtube``, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, its yt-dlp ``FakeYtDlp``
(helpers/fake_ytdlp.py) and its model files there too, and takes auto-chords' packages
to be there (``youtube_fetch.autochords_missing``); ntfy is a fake behind
``_common.transport_for``. No request can reach the network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from conftest import add_song, subprocess_pythonpath
from helpers.fake_ytdlp import FakeYtDlp, entry
from typer.testing import CliRunner

import caracole.youtube_fetch as yf
from caracole import db
from caracole.cli import build_app
from caracole.commands import _common
from caracole.db import kv_get_json
from caracole.health import get_state, is_cooling, record_block
from caracole.overrides import load_overrides
from caracole.songs import find_song, get_song, update_song

NTFY = "https://ntfy.example/caracole-test"
TOPIC = "XFkzRNyygfk"
OTHER = "oNOFfl3Hx3s"
OUTSIDE_SETTINGS = (
    "CREDENTIALS_DIRECTORY", "CARACOLE_CONFIG", "CARACOLE_NTFY_TOKEN", "CARACOLE_SPOTIFY_CLIENT_SECRET",
    "CARACOLE_YTDLP_BIN", "CARACOLE_BTC_WEIGHTS", "CARACOLE_BEAT_CHECKPOINT",
)


class FakeNtfy:
    def __init__(self):
        self.posts: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})


@pytest.fixture
def ntfy(monkeypatch):
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    fake = FakeNtfy()

    def transport(provider: str) -> httpx.BaseTransport:
        if provider != "ntfy":
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(fake.handler)

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(_common, "sleep", lambda s: None)
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    return fake


@pytest.fixture
def fake(tmp_path):
    return FakeYtDlp(tmp_path / "bin")


def write_config(tmp_path: Path, fake: FakeYtDlp, *, enabled=True, budget=None, models=True, ntfy=False) -> Path:
    model_dir = tmp_path / "models"
    model_dir.mkdir(exist_ok=True)
    for name in ("btc.pt", "beat.ckpt"):
        (model_dir / name).write_bytes(b"m")
    lines = [
        f'library_dir = "{tmp_path / "lib"}"',
        f'music_dir = "{tmp_path / "music"}"',
        f'state_dir = "{tmp_path / "state"}"',
        f'cache_dir = "{tmp_path / "cache"}"',
        f'ytdlp_bin = "{fake.bin}"',
        "[providers.youtube]",
        "delay = [0, 0]",
        f"enabled = {'true' if enabled else 'false'}",
    ]
    if budget is not None:
        lines.append(f"budget = {budget}")
    if models:
        lines += ["[autochords]", f'btc_weights = "{model_dir / "btc.pt"}"', f'beat_checkpoint = "{model_dir / "beat.ckpt"}"']
    if ntfy:
        lines += ["[ntfy]", f'url = "{NTFY}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def invoke(config: Path, *args: str):
    return CliRunner().invoke(build_app(), ["--config", str(config), "youtube", *args])


def to_buy(conn, artist="Radiohead", title="Creep", **kw):
    song = add_song(conn, artist, title, duration_ms=239000, **kw)
    update_song(conn, song.id, match_decision="not_found")
    return get_song(conn, song.id)


def creep(fake):
    fake.search("Radiohead Creep", entry(TOPIC, "Creep", "Radiohead - Topic", 238))
    fake.video(TOPIC, "Creep", "Radiohead - Topic", 238, data="topic")


@pytest.mark.slow
def test_youtube_downloads_the_due_songs_and_says_what_comes_next(tmp_path, ntfy, fake, conn):
    song = to_buy(conn)
    creep(fake)
    result = invoke(write_config(tmp_path, fake))
    assert result.exit_code == 0, result.output
    assert (f"Radiohead - Creep: downloaded Creep (Radiohead - Topic), https://www.youtube.com/watch?v={TOPIC}"
            in result.output)
    assert "YouTube: 1 downloaded, 0 not there, 0 unavailable, 0 errors (2 yt-dlp runs of 6)." in result.output
    assert "caracole autochords" in result.output
    assert get_song(conn, song.id).audio_path.endswith(f"{song.id}-{TOPIC}.m4a")
    assert get_state(conn, "youtube").last_ok is not None
    assert "## No human sheet found yet (1)" in (tmp_path / "lib" / "_todo.md").read_text(encoding="utf-8")
    assert (tmp_path / "lib" / "index.html").exists()
    runs = conn.execute("SELECT decision FROM events WHERE provider = 'youtube'").fetchall()
    assert [r[0] for r in runs] == ["ok", "ok"]


def test_with_nothing_due_it_asks_nothing(tmp_path, ntfy, fake, conn):
    result = invoke(write_config(tmp_path, fake))
    assert result.exit_code == 0 and "No song is waiting for audio from YouTube." in result.output
    assert fake.argvs() == []


def test_turned_off_it_says_so_and_asks_nothing(tmp_path, ntfy, fake, conn):
    to_buy(conn)
    result = invoke(write_config(tmp_path, fake, enabled=False))
    assert result.exit_code == 0
    assert "YouTube is off ([providers.youtube] enabled = false); nothing was asked." in result.output
    assert fake.argvs() == []


def test_without_auto_chords_it_downloads_nothing_and_fails(tmp_path, ntfy, fake, conn, monkeypatch):
    to_buy(conn)
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch", "beat_this"])
    result = invoke(write_config(tmp_path, fake))
    assert result.exit_code == 1
    assert "this caracole was built without auto-chords (missing: torch, beat_this)" in result.output
    assert "packages.autochords" in result.output
    assert fake.argvs() == []
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    result = invoke(write_config(tmp_path, fake, models=False))
    assert result.exit_code == 1 and "auto-chords has no BTC weights configured" in result.output


@pytest.mark.slow
def test_one_song_by_hand(tmp_path, ntfy, fake, conn):
    song = to_buy(conn)
    other = to_buy(conn, "Radiohead", "Airbag")
    creep(fake)
    result = invoke(write_config(tmp_path, fake), "--song", "radiohead - creep")
    assert result.exit_code == 0, result.output
    assert get_song(conn, song.id).audio_path and get_song(conn, other.id).audio_path is None
    assert len(fake.argvs()) == 2
    again = invoke(write_config(tmp_path, fake), "--song", "Radiohead - Creep")
    assert again.exit_code == 0 and len(fake.argvs()) == 2
    assert f"Radiohead - Creep already has the audio of https://www.youtube.com/watch?v={TOPIC}" in again.output


@pytest.mark.slow
def test_a_song_whose_audio_is_gone_from_the_cache_gets_it_again(tmp_path, ntfy, fake, conn):
    import shutil

    song = to_buy(conn)
    creep(fake)
    config = write_config(tmp_path, fake)
    assert invoke(config).exit_code == 0
    for args in (("--song", "Radiohead - Creep"), ()):
        shutil.rmtree(tmp_path / "cache" / "youtube")
        result = invoke(config, *args)
        assert result.exit_code == 0, result.output
        assert "Radiohead - Creep: downloaded Creep (Radiohead - Topic)" in result.output
        assert Path(get_song(conn, song.id).audio_path).read_text() == "topic"
    assert [a[-1] for a in fake.argvs()].count(f"https://www.youtube.com/watch?v={TOPIC}") == 3


@pytest.mark.parametrize("display,said", [
    ("Nobody - Nothing", 'No song "Nobody - Nothing" in the library'),
    ("Creep", 'expected "Artist - Title"'),
])
def test_a_song_that_isnt_there_is_said_so(tmp_path, ntfy, fake, conn, display, said):
    result = invoke(write_config(tmp_path, fake), "--song", display)
    assert result.exit_code != 0 and said in result.output


def test_a_song_with_a_human_sheet_or_ignored_gets_nothing_from_youtube(tmp_path, ntfy, fake, conn):
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    song = to_buy(conn)
    v = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords", rating=5,
                       votes=9, version=1, label=None, url="u", raw={}, now="x")
    keep_file(conn, tmp_path / "lib", song=song, version_id=v, name="sheet.txt", data=b"[C]x", rank=1)
    result = invoke(write_config(tmp_path, fake), "--song", "Radiohead - Creep")
    assert result.exit_code == 1 and "has a human sheet" in result.output
    ignored = to_buy(conn, "Radiohead", "Airbag")
    update_song(conn, ignored.id, status="ignored")
    result = invoke(write_config(tmp_path, fake), "--song", "Radiohead - Airbag")
    assert result.exit_code == 1 and "is ignored" in result.output
    assert fake.argvs() == []


def test_a_song_whose_purchase_is_linked_gets_nothing_from_youtube(tmp_path, ntfy, fake, conn):
    song = to_buy(conn)
    creep(fake)
    bought = tmp_path / "music" / "Radiohead - Creep.flac"
    bought.parent.mkdir(parents=True)
    bought.write_bytes(b"bought")
    update_song(conn, song.id, audio_path=str(bought), audio_mtime=bought.stat().st_mtime)
    result = invoke(write_config(tmp_path, fake), "--song", "Radiohead - Creep")
    assert result.exit_code == 1
    assert '"Radiohead - Creep" has its audio already (Radiohead - Creep.flac' in result.output
    assert fake.argvs() == [] and get_song(conn, song.id).audio_path == str(bought)


@pytest.mark.slow
def test_a_pasted_url_is_written_to_overrides_and_downloaded(tmp_path, ntfy, fake, conn):
    song = to_buy(conn)
    fake.video(OTHER, "Radiohead - Creep (Live)", "someone", 300, data="live")
    config = write_config(tmp_path, fake)
    result = invoke(config, "--song", "Radiohead - Creep", "--url", f"https://youtu.be/{OTHER}?t=4")
    assert result.exit_code == 0, result.output
    assert load_overrides(tmp_path / "lib" / "overrides.toml").youtube == {song.key: OTHER}
    assert f'"Radiohead - Creep" = "https://www.youtube.com/watch?v={OTHER}"' in (
        tmp_path / "lib" / "overrides.toml").read_text(encoding="utf-8")
    assert [a[-1] for a in fake.argvs()] == [f"https://www.youtube.com/watch?v={OTHER}"]
    assert Path(get_song(conn, song.id).audio_path).read_text() == "live"


@pytest.mark.slow
def test_none_turns_youtube_down_for_the_song_and_lets_go_of_its_audio(tmp_path, ntfy, fake, conn):
    song = to_buy(conn)
    creep(fake)
    config = write_config(tmp_path, fake)
    invoke(config, "--song", "Radiohead - Creep")
    audio = Path(get_song(conn, song.id).audio_path)
    calls = len(fake.argvs())
    result = invoke(config, "--song", "Radiohead - Creep", "--none")
    assert result.exit_code == 0, result.output
    assert "caracole won't take Radiohead - Creep's audio from YouTube" in result.output
    assert load_overrides(tmp_path / "lib" / "overrides.toml").youtube == {song.key: None}
    assert get_song(conn, song.id).audio_path is None and not audio.exists()
    assert len(fake.argvs()) == calls


@pytest.mark.slow
def test_audio_let_go_with_nothing_due_rewrites_the_pages(tmp_path, ntfy, fake, conn):
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    song = to_buy(conn)
    creep(fake)
    config = write_config(tmp_path, fake)
    assert invoke(config).exit_code == 0
    v = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords", rating=5,
                       votes=9, version=1, label=None, url="u", raw={}, now="x")
    keep_file(conn, tmp_path / "lib", song=get_song(conn, song.id), version_id=v, name="sheet.txt", data=b"[C]x",
              rank=1)  # a human sheet turned up: the audio from YouTube isn't needed any more
    update_song(conn, song.id, status="found", match_decision="accept")
    page = tmp_path / "lib" / "_todo.md"
    page.unlink()
    result = invoke(config)
    assert result.exit_code == 0 and "No song is waiting for audio from YouTube." in result.output
    assert get_song(conn, song.id).audio_path is None
    assert page.is_file()  # the pages say so
    page.unlink()
    assert invoke(config).exit_code == 0 and not page.exists()  # nothing changed: nothing written


@pytest.mark.parametrize("off", ["turned off", "no models"])
def test_none_is_written_ahead_of_time_with_youtube_off(tmp_path, ntfy, fake, conn, off):
    song = to_buy(conn)
    config = write_config(tmp_path, fake, enabled=off != "turned off", models=off != "no models")
    result = invoke(config, "--song", "Radiohead - Creep", "--none")
    assert result.exit_code == 0, result.output
    assert "caracole won't take Radiohead - Creep's audio from YouTube" in result.output
    assert load_overrides(tmp_path / "lib" / "overrides.toml").youtube == {song.key: None}
    assert (tmp_path / "lib" / "_todo.md").is_file() and fake.argvs() == []


def test_none_is_written_for_a_song_not_in_the_library_yet(tmp_path, ntfy, fake, conn):
    result = invoke(write_config(tmp_path, fake), "--song", "Radiohead - Airbag", "--none")
    assert result.exit_code == 0, result.output
    assert 'once "Radiohead - Airbag" is in the library' in result.output
    assert load_overrides(tmp_path / "lib" / "overrides.toml").youtube == {"radiohead/airbag": None}


@pytest.mark.parametrize("args,said", [
    (("--url", "https://youtu.be/XFkzRNyygfk"), "--url and --none need --song"),
    (("--song", "Radiohead - Creep", "--url", "https://vimeo.com/1"), "YouTube video's address"),
    (("--song", "Radiohead - Creep", "--url", "https://youtu.be/XFkzRNyygfk", "--none"), "either --url or --none"),
])
def test_bad_options_are_usage_errors(tmp_path, ntfy, fake, conn, args, said):
    to_buy(conn)
    result = invoke(write_config(tmp_path, fake), *args)
    assert result.exit_code == 2 and said in result.output
    assert fake.argvs() == []


@pytest.mark.slow
def test_a_block_cools_youtube_down_alerts_once_and_exits_0(tmp_path, ntfy, fake, conn):
    song = to_buy(conn)
    fake.search("Radiohead Creep", stderr="ERROR: [youtube] Sign in to confirm you’re not a bot.", exit=1)
    result = invoke(write_config(tmp_path, fake, ntfy=True))
    assert result.exit_code == 0, result.output
    assert "YouTube blocked caracole" in result.output and "Nothing was marked missing." in result.output
    assert is_cooling(conn, "youtube", _common.utcnow())
    assert [p.headers.get("title") for p in ntfy.posts] == ["caracole: youtube blocked"]
    assert (kv_get_json(conn, f"youtube:{song.id}") or {}).get("missing_at") is None
    again = invoke(write_config(tmp_path, fake, ntfy=True))
    assert again.exit_code == 0 and "cooling down" in again.output and len(fake.argvs()) == 1


@pytest.mark.slow
def test_a_download_that_fails_the_same_way_every_time_gives_way_to_another_pick(tmp_path, ntfy, fake, conn):
    to_buy(conn)
    creep(fake)
    fake.video(TOPIC, stderr="ERROR: [youtube] XFkzRNyygfk: Requested format is not available", exit=1)
    config = write_config(tmp_path, fake)
    first = invoke(config)
    assert first.exit_code == 0, first.output
    assert ("Radiohead - Creep: failed ([youtube] XFkzRNyygfk: Requested format is not available); tried again on "
            "the next run") in first.output
    for _ in range(yf.GIVE_UP_AFTER - 2):
        invoke(config)
    last = invoke(config)
    assert last.exit_code == 0, last.output
    assert (f"(https://www.youtube.com/watch?v={TOPIC} failed {yf.GIVE_UP_AFTER} times: the next run picks another)"
            in last.output)
    assert "tried again on the next run" not in last.output


@pytest.mark.slow
def test_a_spent_budget_says_so(tmp_path, ntfy, fake, conn):
    to_buy(conn)
    creep(fake)
    result = invoke(write_config(tmp_path, fake, budget=1))
    assert result.exit_code == 0
    assert "YouTube's budget of 1 yt-dlp run is spent; the songs left wait for the next run." in result.output


def test_it_waits_for_another_caracole(tmp_path, ntfy, fake, conn):
    from test_commands_lock import WAITING, Started, another_caracole

    to_buy(conn)
    creep(fake)
    config = write_config(tmp_path, fake)
    with another_caracole(tmp_path):
        started = Started(config, ["youtube"])
        assert started.still_waiting()
        assert fake.argvs() == []
        record_block(conn, "youtube", _common.utcnow(), "youtube: bot check")  # what the run it waited for met
    result = started.finished()
    assert WAITING in result.output and "cooling down" in result.output and fake.argvs() == []


def test_the_help_names_the_youtube_table(tmp_path, ntfy, fake):
    # Rich takes "[youtube]" for markup unless it is escaped, and the help would say "under  in".
    result = CliRunner().invoke(build_app(), ["youtube", "--help"])
    assert result.exit_code == 0
    text = " ".join(" ".join(line.strip(" │").split()) for line in result.output.splitlines())  # unwrapped
    assert "written under [youtube] in overrides.toml" in text
    assert '("none" under [youtube])' in text


@pytest.mark.slow
def test_registering_the_command_imports_neither_the_pass_nor_yt_dlp(tmp_path):
    src = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys, typer\n"
        "from caracole.commands import youtube\n"
        "youtube.register(typer.Typer())\n"
        "print([m for m in ('caracole.youtube_fetch', 'caracole.todo') if m in sys.modules])\n"
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
                         check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "[]"


@pytest.mark.slow
def test_the_song_is_found_by_any_spelling(tmp_path, ntfy, fake, conn):
    song = to_buy(conn, "宋冬野", "斑马，斑马")
    assert find_song(conn, song.key) is not None
    fake.search("宋冬野 斑马，斑马", entry(TOPIC, "斑马，斑马", "宋冬野 - Topic", 239))
    fake.video(TOPIC, "斑马，斑马", "宋冬野 - Topic", 239)
    result = invoke(write_config(tmp_path, fake), "--song", "宋冬野 - 斑马斑马")
    assert result.exit_code == 0, result.output
    assert db.kv_get(conn, f"youtube:{song.id}") is not None
