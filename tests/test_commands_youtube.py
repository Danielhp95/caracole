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
    "CARACOLE_CONFIG",
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


def write_config(tmp_path: Path, fake: FakeYtDlp, *, enabled=True, budget=None, models=True, ntfy=False,
                 chordpro: Path | None = None) -> Path:
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
        *([f'chordpro_bin = "{chordpro}"'] if chordpro else []),
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
    (("--url", "https://youtu.be/XFkzRNyygfk"), "--url, --none and --sheet need --song"),
    (("--sheet",), "--url, --none and --sheet need --song"),
    (("--song", "Radiohead - Creep", "--sheet", "--none"), "either --sheet or --none"),
    (("--song", "Radiohead - Creep", "--progress"), "--progress goes with --sheet"),
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
    assert [p.headers.get("title") for p in ntfy.posts] == ["caracole: YouTube blocked"]
    assert (kv_get_json(conn, f"youtube:{song.id}") or {}).get("missing_at") is None
    again = invoke(write_config(tmp_path, fake, ntfy=True))
    assert again.exit_code == 0 and "cooling down" in again.output and len(fake.argvs()) == 1


@pytest.mark.parametrize("blocked", [False, True])
def test_the_pages_after_a_lookup_went_first_read_overrides_toml_again(tmp_path, ntfy, fake, conn, monkeypatch,
                                                                       blocked):
    # Between two yt-dlp runs the command let `caracole get --tab` go first, which pinned a tab: the pages it
    # writes at its end, after a block too, go by overrides.toml as the lookup left it.
    import caracole.commands.youtube as cmd
    from caracole.http import ProviderBlocked

    to_buy(conn)
    config = write_config(tmp_path, fake)
    overrides = tmp_path / "lib" / "overrides.toml"

    def youtube_pass(conn, runner, cfg, now, **kwargs):  # a lookup had the lock in a pause, and pinned a tab
        overrides.parent.mkdir(parents=True, exist_ok=True)
        overrides.write_text('[pin]\n"Radiohead - Creep" = ["https://tabs.ultimate-guitar.com/tab/2"]\n',
                             encoding="utf-8")
        monkeypatch.setattr(_common, "_handoffs", _common.handoffs() + 1)
        if blocked:
            raise ProviderBlocked("youtube", "ytsearch:Radiohead Creep", None, "bot check")
        return yf.YouTubeStats()

    monkeypatch.setattr(yf, "youtube_pass", youtube_pass)
    seen = []
    monkeypatch.setattr(cmd, "write_pages", lambda conn, cfg, o, now: seen.append([*o.pin.values()]))
    result = invoke(config)
    assert result.exit_code == 0, result.output
    assert seen == [[(2,)]]


@pytest.mark.slow
def test_runs_that_all_failed_leave_youtubes_strikes(tmp_path, ntfy, fake, conn):
    # Two blocks in a row, the second's cooldown over: yt-dlp runs that all failed are no good run, as a
    # nightly run of nothing but errors isn't, so the next block still cools YouTube down for 98 hours.
    from datetime import timedelta

    record_block(conn, "youtube", _common.utcnow() - timedelta(days=10), "youtube: bot check")
    record_block(conn, "youtube", _common.utcnow() - timedelta(days=7), "youtube: bot check")
    to_buy(conn)
    fake.search("Radiohead Creep", stderr="ERROR: [youtube] Unable to extract initial data", exit=1)
    result = invoke(write_config(tmp_path, fake))
    assert result.exit_code == 0, result.output
    assert len(fake.argvs()) == 1
    state = get_state(conn, "youtube")
    assert (state.strikes, state.last_ok) == (2, None)


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


# --- --sheet: a song's auto sheet now (youtube_sheet.py) -------------------------------------------------

VIKINGOS = "lzN7Thn3FV4"
FAKE_CHORDPRO = """\
#!{python}
import sys

out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
with open(out, "w", encoding="utf-8") as f:
    f.write("%PDF-1.4 fake")
"""


@pytest.fixture
def sheet_sites(monkeypatch, ntfy, tmp_path):
    """LRCLIB (with no lyrics for anything) beside ntfy, auto-chords' models as fakes, a fake chordpro, and ten
    seconds of audio for the fake yt-dlp to give."""
    import wave

    import caracole.autochords.run as ac_run
    from caracole.autochords import ChordSegment

    asked = []

    def lrclib(request):
        asked.append(request)
        if request.url.path.endswith("/get"):
            return httpx.Response(404, json={"name": "TrackNotFound"})
        return httpx.Response(200, json=[])

    def megalobiz(request):  # asked after LRCLIB, for the timed lyrics it lacks: none either
        return httpx.Response(200, json={"query": {}, "count": 0, "results": []})

    def azlyrics(request):  # and AZLyrics, which has no such artist
        return httpx.Response(404, text="")

    def transport(provider):
        if provider == "lrclib":
            return httpx.MockTransport(lrclib)
        if provider == "megalobiz":
            return httpx.MockTransport(megalobiz)
        if provider == "azlyrics":
            return httpx.MockTransport(azlyrics)
        if provider == "ntfy":
            return httpx.MockTransport(ntfy.handler)
        pytest.fail(f"a client for {provider} was made")

    class Recognizer:
        def __init__(self, weights, *, device="cpu"):
            pass

        def recognize(self, path):
            return [ChordSegment(0.0, 5.0, "D"), ChordSegment(5.0, 10.0, "A")]

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(ac_run, "BTCRecognizer", Recognizer)
    monkeypatch.setattr(ac_run, "detect_beats",
                        lambda path, checkpoint, device="cpu": ([0.5 * i for i in range(21)], [2.0 * i for i in range(6)]))
    chordpro = tmp_path / "bin" / "chordpro"
    chordpro.parent.mkdir(parents=True, exist_ok=True)
    chordpro.write_text(FAKE_CHORDPRO.format(python=sys.executable), encoding="utf-8")
    chordpro.chmod(0o755)
    audio = tmp_path / "audio" / "vikingos.wav"
    audio.parent.mkdir()
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000 * 10)
    return chordpro, audio, asked


@pytest.mark.slow
def test_sheet_makes_the_songs_auto_sheet_now_and_says_each_stage(tmp_path, fake, conn, sheet_sites):
    from caracole.get import read_progress_line

    chordpro, audio, asked = sheet_sites
    fake.video(VIKINGOS, "Vikingos veganos", "HyperFanes", 10, ext="wav", copy=str(audio))
    config = write_config(tmp_path, fake, chordpro=chordpro)
    result = invoke(config, "--song", "Nick Cani - Vikingos veganos", "--url",
                    f"https://www.youtube.com/watch?v={VIKINGOS}&pp=ygUQdmlraW5nb3MgdmVnYW5vcw%3D%3D",
                    "--sheet", "--progress")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert f"Audio: downloaded Vikingos veganos (HyperFanes), https://www.youtube.com/watch?v={VIKINGOS}." in lines
    assert "Lyrics: LRCLIB has none; nor has Megalobiz; nor has AZLyrics." in lines
    assert "Chords: chords only, no lyrics." in lines
    sheet = tmp_path / "lib" / "Nick Cani" / "Vikingos veganos" / "sheet (auto).txt"
    assert any(line.startswith(f"Sheet: {sheet}, readable after") for line in lines)
    assert (sheet.parent / "sheet (auto).html").is_file()
    events = [e for e in map(read_progress_line, lines) if e is not None]
    assert {"stage": "chords", "state": "done", "detail": "chords only, no lyrics"} in events
    assert events[-1]["done"]["ok"] is True
    assert "Done in" in result.output and "1 yt-dlp run" in result.output and len(asked) == 2


def test_sheet_refuses_a_song_with_a_human_sheet_and_exits_1(tmp_path, fake, conn, sheet_sites):
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    chordpro, audio, _ = sheet_sites
    song = add_song(conn, "Nick Cani", "Vikingos veganos")
    v = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords", rating=5,
                       votes=9, version=1, label=None, url="u", raw={}, now="x")
    keep_file(conn, tmp_path / "lib", song=song, version_id=v, name="sheet.txt", data=b"[C]x", rank=1)
    result = invoke(write_config(tmp_path, fake, chordpro=chordpro), "--song", "Nick Cani - Vikingos veganos",
                    "--url", f"https://youtu.be/{VIKINGOS}", "--sheet")
    assert result.exit_code == 1
    assert "No sheet made: Nick Cani - Vikingos veganos already has a sheet." in result.output
    assert fake.argvs() == []


def test_sheet_without_auto_chords_asks_nothing_and_exits_1(tmp_path, fake, conn, sheet_sites, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    result = invoke(write_config(tmp_path, fake), "--song", "Nick Cani - Vikingos veganos", "--url",
                    f"https://youtu.be/{VIKINGOS}", "--sheet")
    assert result.exit_code == 1
    assert "caracole makes no sheet from YouTube here: this caracole was built without auto-chords" in result.output
    assert fake.argvs() == [] and not (tmp_path / "lib" / "wanted.txt").exists()


# --- --search: a video suggested for a search (youtube_search.py) ------------------------------------------

THUMB = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
         b"\xff\xc0\x00\x0b\x08\x01\x68\x01\xe0\x01\x01\x11\x00\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\x34\xff\xd9")
SEARCHED = "Nick Cani - Vikingos veganos"


@pytest.fixture
def image_host(monkeypatch, ntfy):
    """i.ytimg.com (provider ``ytimg``) beside ntfy: ``answer`` is what a thumbnail's request gets; every request
    kept, and every pause caracole takes (``slept``), which a thumbnail never waits for."""
    host = type("ImageHost", (), {})()
    host.asked = []
    host.slept = []
    host.answer = httpx.Response(200, content=THUMB, headers={"content-type": "image/jpeg"})

    def handler(request):
        host.asked.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return host.answer

    def transport(provider):
        if provider == "ytimg":
            return httpx.MockTransport(handler)
        if provider == "ntfy":
            return httpx.MockTransport(ntfy.handler)
        pytest.fail(f"a client for {provider} was made")

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(_common, "sleep", host.slept.append)
    return host


def vikingos_found(fake):
    fake.search(SEARCHED, entry(VIKINGOS, "Somos vikingos veganos - Hyperfanes", "kintanedu", 222),
                entry(OTHER, "Not this one", "someone", 200))


@pytest.mark.slow
def test_search_keeps_youtubes_first_video_and_its_thumbnail_for_the_page(tmp_path, fake, conn, image_host):
    from caracole.youtube_search import query_key

    vikingos_found(fake)
    config = write_config(tmp_path, fake)
    result = invoke(config, "--search", SEARCHED)
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == (f"Searched: YouTube's first video for “{SEARCHED}” is Somos vikingos "
                                              f"veganos - Hyperfanes (kintanedu), https://www.youtube.com/watch?v={VIKINGOS}.")
    # One yt-dlp run: the first result's metadata alone, the query after "--", nothing retried, nothing downloaded.
    [argv] = fake.argvs()
    assert argv[-2:] == ["--", f"ytsearch1:{SEARCHED}"]
    assert {"--flat-playlist", "--dump-single-json", "--ignore-config", "--no-cookies"} <= set(argv)
    assert argv[argv.index("--retries") + 1] == "0" and "-x" not in argv
    assert image_host.asked == [f"https://i.ytimg.com/vi/{VIKINGOS}/hqdefault.jpg"]
    assert (tmp_path / "cache" / "youtube-thumbs" / f"{VIKINGOS}.jpg").read_bytes() == THUMB
    said = kv_get_json(conn, f"youtube-search:{query_key(SEARCHED)}")
    assert said["video"]["id"] == VIKINGOS and said["thumb"] is True
    # Asked again within 30 days, nothing is asked: the page shows it from the record.
    again = invoke(config, "--search", "vikingos veganos - nick cani")
    assert again.exit_code == 0 and again.output.startswith("Searched: YouTube's first video for")
    assert len(fake.argvs()) == 1 and len(image_host.asked) == 1


@pytest.mark.slow
def test_search_with_progress_says_its_stages(tmp_path, fake, conn, image_host):
    from caracole.get import read_progress_line

    vikingos_found(fake)
    result = invoke(write_config(tmp_path, fake), "--search", SEARCHED, "--progress")
    assert result.exit_code == 0, result.output
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    assert [(e["stage"], e["state"]) for e in events] == [("video", "running"), ("video", "done"),
                                                         ("thumbnail", "running"), ("thumbnail", "done")]


@pytest.mark.slow
def test_a_thumbnail_that_isnt_a_jpeg_is_none_and_the_video_is_suggested_all_the_same(tmp_path, fake, conn,
                                                                                     image_host):
    vikingos_found(fake)
    image_host.answer = httpx.Response(200, content=b"<html>not an image</html>", headers={"content-type": "text/html"})
    result = invoke(write_config(tmp_path, fake), "--search", SEARCHED)
    assert result.exit_code == 0 and result.output.startswith("Searched:")
    assert not (tmp_path / "cache" / "youtube-thumbs" / f"{VIKINGOS}.jpg").exists()


@pytest.mark.slow
def test_a_block_cools_youtube_down_alerts_once_and_keeps_nothing(tmp_path, fake, conn, image_host, ntfy):
    fake.search(SEARCHED, stderr="ERROR: [youtube] Sign in to confirm you’re not a bot.", exit=1)
    result = invoke(write_config(tmp_path, fake, ntfy=True), "--search", SEARCHED)
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1].startswith("Not searched: YouTube blocked caracole")
    assert is_cooling(conn, "youtube", _common.utcnow())
    assert [p.headers.get("title") for p in ntfy.posts] == ["caracole: YouTube blocked"]
    assert image_host.asked == [] and kv_get_json(conn, "youtube-search:cani-nick-veganos-vikingos") is None
    again = invoke(write_config(tmp_path, fake, ntfy=True), "--search", SEARCHED)
    assert "paused after a block" in again.output and len(fake.argvs()) == 1  # nothing retried


@pytest.mark.slow
def test_an_error_is_no_miss_and_isnt_sent_again_within_the_hour(tmp_path, fake, conn, image_host):
    fake.search(SEARCHED, stderr="ERROR: [youtube] Unable to download API page: HTTP Error 500", exit=1)
    config = write_config(tmp_path, fake)
    result = invoke(config, "--search", SEARCHED)
    assert result.exit_code == 0 and result.output.startswith("Not searched: yt-dlp failed")
    assert kv_get_json(conn, "youtube-search:cani-nick-veganos-vikingos") is None
    again = invoke(config, "--search", SEARCHED)
    assert "failed less than an hour ago" in again.output and len(fake.argvs()) == 1


@pytest.mark.slow
def test_a_search_that_finds_nothing_is_kept_as_none(tmp_path, fake, conn, image_host):
    fake.search(SEARCHED)  # no entry
    result = invoke(write_config(tmp_path, fake), "--search", SEARCHED)
    assert result.exit_code == 0 and result.output.splitlines()[-1] == (
        f"Nothing found: YouTube has no video for “{SEARCHED}”.")
    assert kv_get_json(conn, "youtube-search:cani-nick-veganos-vikingos")["video"] is None
    assert image_host.asked == []


def test_search_where_no_sheet_can_be_made_asks_nothing(tmp_path, fake, conn, image_host, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    result = invoke(write_config(tmp_path, fake), "--search", SEARCHED)
    assert result.exit_code == 0 and result.output.startswith("Not searched: no sheet from YouTube here")
    assert fake.argvs() == []


@pytest.mark.parametrize("args", [("--search", "x", "--song", "Radiohead - Creep"), ("--search", "x", "--sheet")])
def test_search_goes_alone(tmp_path, fake, conn, image_host, args):
    result = invoke(write_config(tmp_path, fake), *args)
    assert result.exit_code == 2 and "--video go alone" in result.output



@pytest.mark.slow
def test_the_thumbnail_comes_right_after_the_search_with_no_pause(tmp_path, fake, conn, image_host):
    # YouTube's pause between two yt-dlp runs is 15–30 s; the thumbnail is YouTube's image host's, a provider of its
    # own with none: neither that pause nor YouTube's last request (the search, just now) delays it.
    vikingos_found(fake)
    config = write_config(tmp_path, fake)
    config.write_text(config.read_text().replace("delay = [0, 0]", "delay = [15, 30]"), encoding="utf-8")
    result = invoke(config, "--search", SEARCHED)
    assert result.exit_code == 0, result.output
    assert image_host.asked == [f"https://i.ytimg.com/vi/{VIKINGOS}/hqdefault.jpg"]
    assert image_host.slept == []  # not a slice of a pause, before the search or after it
    ran = conn.execute("SELECT provider, url FROM events ORDER BY id").fetchall()
    assert [p for p, _ in ran] == ["youtube", "ytimg"]  # the search's run, then the thumbnail, each its own provider


@pytest.mark.slow
def test_a_thumbnail_block_cools_down_youtubes_images_alone(tmp_path, fake, conn, image_host, ntfy):
    vikingos_found(fake)
    image_host.answer = httpx.Response(429, text="Too Many Requests")
    config = write_config(tmp_path, fake, ntfy=True)
    result = invoke(config, "--search", SEARCHED)
    assert result.exit_code == 0 and result.output.splitlines()[-1].startswith("Searched:")  # the video, all the same
    assert is_cooling(conn, "ytimg", _common.utcnow()) and not is_cooling(conn, "youtube", _common.utcnow())
    assert [p.headers.get("title") for p in ntfy.posts] == ["caracole: YouTube's images blocked"]
    assert not (tmp_path / "cache" / "youtube-thumbs" / f"{VIKINGOS}.jpg").exists()
    # While it cools down, the next suggestion comes without a thumbnail, and the image host is asked nothing.
    fake.search("Nick Cani - Vegan Vikings", entry(OTHER, "Vegan Vikings", "Nick Cani", 223))
    again = invoke(config, "--search", "Nick Cani - Vegan Vikings")
    assert again.exit_code == 0 and again.output.splitlines()[-1].startswith("Searched:")
    assert len(image_host.asked) == 1 and len(fake.argvs()) == 2


def test_youtubes_images_turned_off_give_rows_without_thumbnails(tmp_path, fake, conn, image_host):
    vikingos_found(fake)
    config = write_config(tmp_path, fake)
    config.write_text(config.read_text() + "[providers.ytimg]\nenabled = false\n", encoding="utf-8")
    result = invoke(config, "--search", SEARCHED)
    assert result.exit_code == 0 and result.output.splitlines()[-1].startswith("Searched:")
    assert image_host.asked == []


# --- --video: a pasted video's metadata (youtube_search.read_video) ------------------------------------------

PASTED_LINK = "https://www.youtube.com/watch?v=lzN7Thn3FV4&pp=ygUQdmlraW5nb3MgdmVnYW5vcw%3D%3D"


def vikingos_video(fake, **spec):
    fake.video(VIKINGOS, "Somos vikingos veganos - Hyperfanes", "kintanedu", 222, **spec)


@pytest.mark.slow
def test_video_reads_a_pasted_videos_metadata_and_thumbnail_with_no_download(tmp_path, fake, conn, image_host):
    from caracole.get import read_progress_line

    vikingos_video(fake)
    config = write_config(tmp_path, fake)
    config.write_text(config.read_text().replace("delay = [0, 0]", "delay = [15, 30]"), encoding="utf-8")
    result = invoke(config, "--video", PASTED_LINK, "--progress")
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == (f"Searched: YouTube's video {VIKINGOS} is Somos vikingos veganos - "
                                              "Hyperfanes (kintanedu).")
    [argv] = fake.argvs()
    assert argv[-2:] == ["--", f"https://www.youtube.com/watch?v={VIKINGOS}"]  # its plain address: no tracking
    assert {"--skip-download", "--flat-playlist", "--dump-single-json", "--no-cookies"} <= set(argv)
    assert argv[argv.index("--retries") + 1] == "0" and "-x" not in argv and "-o" not in argv
    assert not (tmp_path / "cache" / "youtube").exists()  # nothing downloaded
    assert image_host.asked == [f"https://i.ytimg.com/vi/{VIKINGOS}/hqdefault.jpg"] and image_host.slept == []
    said = kv_get_json(conn, f"youtube-search:video:{VIKINGOS}")
    assert said["video"]["title"] == "Somos vikingos veganos - Hyperfanes" and said["thumb"] is True
    events = [e for e in map(read_progress_line, result.output.splitlines()) if e is not None]
    assert [(e["stage"], e["state"]) for e in events] == [("video", "running"), ("video", "done"),
                                                         ("thumbnail", "running"), ("thumbnail", "done")]
    for asked_again in (f"https://youtu.be/{VIKINGOS}?si=abc", VIKINGOS):  # a link, or the id, as a job passes it
        again = invoke(config, "--video", asked_again)
        assert again.exit_code == 0 and again.output.startswith("Searched: YouTube's video")
    assert len(fake.argvs()) == 1 and len(image_host.asked) == 1  # known this month: nothing asked


@pytest.mark.slow
def test_a_video_youtube_wont_give_is_kept_as_none(tmp_path, fake, conn, image_host):
    vikingos_video(fake, stderr=f"ERROR: [youtube] {VIKINGOS}: Private video. Sign in if you've been granted access",
                   exit=1)
    result = invoke(write_config(tmp_path, fake), "--video", VIKINGOS)  # the id alone, as the page's job passes it
    assert result.exit_code == 0 and result.output.splitlines()[-1].startswith("Nothing found: YouTube won't give")
    said = kv_get_json(conn, f"youtube-search:video:{VIKINGOS}")
    assert said["video"] is None and "Private video" in said["unavailable"] and image_host.asked == []


@pytest.mark.slow
def test_a_block_reading_a_video_cools_youtube_down_and_alerts_once(tmp_path, fake, conn, image_host, ntfy):
    vikingos_video(fake, stderr="ERROR: [youtube] Sign in to confirm you’re not a bot.", exit=1)
    result = invoke(write_config(tmp_path, fake, ntfy=True), "--video", PASTED_LINK)
    assert result.exit_code == 0 and "YouTube blocked caracole" in result.output
    assert is_cooling(conn, "youtube", _common.utcnow())
    assert [p.headers.get("title") for p in ntfy.posts] == ["caracole: YouTube blocked"]
    assert kv_get_json(conn, f"youtube-search:video:{VIKINGOS}") is None


@pytest.mark.parametrize("link", ["https://vimeo.com/1", "nick cani", "https://www.youtube.com/@nickcani"])
def test_video_takes_a_youtube_videos_link_alone(tmp_path, fake, conn, image_host, link):
    result = invoke(write_config(tmp_path, fake), "--video", link)
    assert result.exit_code == 2 and "not a YouTube video" in result.output
    assert fake.argvs() == []
