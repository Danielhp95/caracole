"""``caracole audio``: a song's auto sheet from an audio file you give it, run through the CLI.

Each test writes a caracole.toml rooted in tmp_path, with a chordpro that writes a PDF and model files (unread);
auto-chords' models are fakes, LRCLIB, Megalobiz and AZLyrics fakes behind ``_common.transport_for`` (any other client
fails the test), and the audio files helpers/audio_files.py's: nothing reaches the network, and no model runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import add_song, subprocess_pythonpath
from helpers.audio_files import audio, write
from test_youtube_sheet import keep_human_sheet, record
from typer.testing import CliRunner

import caracole.youtube_fetch as yf
from caracole import audio_store
from caracole.cli import build_app
from caracole.commands import _common
from caracole.config import load_config
from caracole.get import read_progress_line
from caracole.normalize import identity_key
from caracole.songs import find_song

FAKE_CHORDPRO = """\
#!{python}
import sys

out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
with open(out, "w", encoding="utf-8") as f:
    f.write("%PDF-1.4 fake")
"""
# Settings a shell could leak in (the auto-chords shells set the model files): none may reach a test.
OUTSIDE_SETTINGS = ("CARACOLE_CONFIG", "CARACOLE_BTC_WEIGHTS", "CARACOLE_BEAT_CHECKPOINT", "CARACOLE_WHISPER_MODEL",
                    "CARACOLE_DEMUCS_MODEL", "CARACOLE_TORCH_CUDA", "CARACOLE_YTDLP_BIN")


@pytest.fixture
def lrclib(monkeypatch):
    """LRCLIB with the song's timed lyrics (200 s), Megalobiz and AZLyrics with none; its requests kept."""
    from test_youtube_sheet import Lrclib

    from helpers.azlyrics_site import FakeAzLyrics
    from helpers.megalobiz_site import FakeMegalobiz

    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    site, megalobiz, azlyrics = Lrclib(record(200.0)), FakeMegalobiz(), FakeAzLyrics({})

    def transport(provider):
        handlers = {"lrclib": site.handler, "megalobiz": megalobiz.handler, "azlyrics": azlyrics.handler}
        if provider not in handlers:
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(handlers[provider])

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(_common, "sleep", lambda s: None)
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))
    return site


@pytest.fixture
def models(monkeypatch) -> list[str]:
    """auto-chords' models the command builds, BTC and beat_this, fakes noting the file each heard."""
    import caracole.autochords.run as ac_run
    from caracole.autochords import ChordSegment

    heard: list[str] = []

    class BTC:
        def __init__(self, weights, *, device="cpu"):
            pass

        def recognize(self, path):
            heard.append(Path(path).name)
            return [ChordSegment(0.0, 5.0, "D"), ChordSegment(5.0, 10.0, "A")]

    monkeypatch.setattr(ac_run, "BTCRecognizer", BTC)
    monkeypatch.setattr(ac_run, "detect_beats", lambda path, checkpoint, device="cpu": (
        [0.5 * i for i in range(21)], [2.0 * i for i in range(6)]))
    return heard


@pytest.fixture
def config(tmp_path) -> Path:
    chordpro = tmp_path / "bin" / "chordpro"
    chordpro.parent.mkdir(parents=True)
    chordpro.write_text(FAKE_CHORDPRO.format(python=sys.executable), encoding="utf-8")
    chordpro.chmod(0o755)
    models = tmp_path / "models"
    models.mkdir()
    for name in ("btc.pt", "final0.ckpt"):
        (models / name).write_bytes(b"model")
    folders = (("library_dir", "lib"), ("music_dir", "music"), ("state_dir", "state"), ("cache_dir", "cache"))
    lines = [f'{key} = "{tmp_path / name}"' for key, name in folders]
    lines += [f'chordpro_bin = "{chordpro}"', f'ytdlp_bin = "{tmp_path / "no-yt-dlp"}"', "[autochords]",
              f'btc_weights = "{models / "btc.pt"}"', f'beat_checkpoint = "{models / "final0.ckpt"}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def invoke(config: Path, *args: str):
    return CliRunner().invoke(build_app(), ["--config", str(config), "audio", *args])


def kept_files(tmp_path) -> list[str]:
    """The files in caracole's audio folder, a moved upload's marker (``.upload-<id>.kept``) aside."""
    folder = tmp_path / "state" / "audio"
    return sorted(p.name for p in folder.iterdir() if not p.name.endswith(".kept")) if folder.exists() else []


# --- the whole way ---------------------------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("name,tags,song,named", [
    ("track.wav", {"artist": "Nick Cani", "title": "Vikingos veganos", "album": "Pruebas"}, None,
     "Nick Cani - Vikingos veganos | Pruebas | 3:20"),
    ("03 - Nick Cani - Vikingos veganos.wav", {}, None, "Nick Cani - Vikingos veganos | 3:20"),
    ("track.wav", {"artist": "Someone Else", "title": "Another Song", "album": "Pruebas"},
     "Nick Cani - Vikingos veganos", "Nick Cani - Vikingos veganos | Pruebas | 3:20"),
], ids=["its tags", "its name", "--song wins"])
def test_a_file_gives_a_new_song_its_sheet(tmp_path, config, conn, lrclib, models, name, tags, song, named):
    given = write(tmp_path / "mine" / name, "WAV", 200.0, **tags)
    result = invoke(config, str(given), *(("--song", song) if song else ()))
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    if song is None:
        assert f"Read “{name}” as Nick Cani - Vikingos veganos." in lines
    assert "Song: added to wanted.txt, line 16." in lines
    assert "Audio: kept as its audio: WAV, 3:20." in lines
    assert "Lyrics: found, timed." in lines and "Chords: chords over the lyrics." in lines
    assert lines[-1].startswith("Done in ") and lines[-1].endswith(" s: 1 LRCLIB request."), lines
    assert named in (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    sheet = tmp_path / "lib" / "Nick Cani" / "Vikingos veganos" / "sheet (auto).txt"
    assert sheet.is_file() and (sheet.parent / "sheet (auto).html").is_file()
    song_row = find_song(conn, identity_key("Nick Cani", "Vikingos veganos"))
    kept = audio_store.uploaded(load_config(config, env={}), song_row)
    # BTC heard its test tone, then the copy kept in caracole's own folder; the file given stays where it was.
    assert kept is not None and models == ["test-tone.wav", kept.name] and given.exists()
    assert find_song(conn, identity_key("Someone Else", "Another Song")) is None


@pytest.mark.slow
def test_an_upload_by_its_id_with_progress(tmp_path, config, conn, lrclib, models):
    cfg = load_config(config, env={})
    up = audio_store.stage(cfg, audio("MP3", 200.0), "vikingos.mp3", named=())
    result = invoke(config, "--upload", up.id, "--song", "Nick Cani - Vikingos veganos", "--progress")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    events = [e for e in map(read_progress_line, lines) if e is not None]
    assert {"stage": "audio", "state": "done", "detail": "kept as its audio: MP3, 3:20"} in events
    assert events[-1]["done"]["ok"] is True and events[-1]["done"]["refused"] is None
    song = find_song(conn, identity_key("Nick Cani", "Vikingos veganos"))
    assert kept_files(tmp_path) == [Path(song.audio_path).name]  # moved: the staged file and its record gone


@pytest.mark.slow
def test_a_sites_wait_exits_0(tmp_path, config, conn, lrclib, models, monkeypatch):
    monkeypatch.setattr(lrclib, "handler", lambda request: httpx.Response(503, text="Service Unavailable"))
    given = write(tmp_path / "mine" / "track.wav", "WAV", 200.0)
    result = invoke(config, str(given), "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 0, result.output
    assert "Lyrics: failed: no lyrics yet (LRCLIB unavailable); tried again tonight." in result.output.splitlines()


# --- exit 1 ------------------------------------------------------------------------------------------------------


def test_a_song_with_a_human_sheet_is_refused_and_exits_1(tmp_path, config, conn, lrclib, models):
    cfg = load_config(config, env={})
    keep_human_sheet(conn, cfg, add_song(conn, "Nick Cani", "Vikingos veganos"))
    given = write(tmp_path / "mine" / "track.wav", "WAV", 200.0)
    result = invoke(config, str(given), "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 1, result.output
    assert result.output.splitlines()[-1] == "No sheet made: Nick Cani - Vikingos veganos already has a sheet."
    assert kept_files(tmp_path) == [] and models == [] and lrclib.requests == []
    assert "Nick Cani" not in ((tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
                               if (tmp_path / "lib" / "wanted.txt").exists() else "")


@pytest.mark.slow
def test_audio_auto_chords_cant_read_exits_1(tmp_path, config, conn, lrclib, models, monkeypatch):
    import caracole.autochords.run as ac_run

    class Deaf:
        def __init__(self, weights, *, device="cpu"):
            pass

        def recognize(self, path):
            if Path(path).name == "test-tone.wav":
                return []
            raise RuntimeError("Error opening the file: Format not recognised.")

    monkeypatch.setattr(ac_run, "BTCRecognizer", Deaf)
    given = write(tmp_path / "mine" / "track.wav", "WAV", 200.0)
    result = invoke(config, str(given), "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 1, result.output
    assert result.output.splitlines()[-1] == "No sheet made: auto-chords can't read the audio."


@pytest.mark.parametrize("data,said", [
    (b"not really audio, whatever its name says" * 10,
     "Not an audio file caracole reads (MP3, M4A, FLAC, WAV, Ogg or AIFF)."),
    (audio("FLAC", audio_store.MAX_SECONDS + 1), "That file is longer than 30 minutes."),
], ids=["not audio", "too long"])
def test_a_file_caracole_doesnt_read_is_said_before_anything_and_exits_1(tmp_path, config, lrclib, models, data,
                                                                        said):
    given = tmp_path / "mine" / "track.mp3"
    given.parent.mkdir()
    given.write_bytes(data)
    result = invoke(config, str(given), "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 1, result.output
    assert said in result.output
    assert not (tmp_path / "lib" / "wanted.txt").exists() and kept_files(tmp_path) == []
    assert not (tmp_path / "state" / "caracole.lock").exists()  # it asked for nothing, the lock included


def test_an_upload_gone_is_said_before_anything_and_exits_1(tmp_path, config, lrclib, models):
    result = invoke(config, "--upload", "0123456789abcdef", "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 1, result.output
    assert audio_store.GONE in result.output
    assert not (tmp_path / "state" / "caracole.lock").exists()


def test_without_auto_chords_it_says_so_before_anything_and_exits_1(tmp_path, config, lrclib, models, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    given = write(tmp_path / "mine" / "track.wav", "WAV", 2.0)
    result = invoke(config, str(given), "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 1, result.output
    assert ("caracole makes no sheet from an audio file here: built without auto-chords (missing: torch): nothing "
            "to make of the audio; use the flake's packages.autochords") in result.output
    assert not (tmp_path / "lib" / "wanted.txt").exists() and kept_files(tmp_path) == []
    assert not (tmp_path / "state" / "caracole.lock").exists()


# --- exit 2 ----------------------------------------------------------------------------------------------------


def test_a_file_that_names_no_artist_asks_for_one_and_exits_2(tmp_path, config, lrclib, models):
    given = write(tmp_path / "mine" / "07 Vikingos veganos.wav", "WAV", 2.0)
    result = invoke(config, str(given))
    assert result.exit_code == 2, result.output
    assert '--song "ARTIST - Vikingos veganos"' in result.output
    assert not (tmp_path / "lib" / "wanted.txt").exists() and kept_files(tmp_path) == []


@pytest.mark.parametrize("args", [
    (),  # neither a file nor an upload
    ("FILE", "--upload", "0123456789abcdef"),  # both
    ("FILE", "--song", "Nick Cani"),  # no title
    ("missing.wav",),  # no such file
], ids=["neither", "both", "no title", "no such file"])
def test_a_usage_error_exits_2(tmp_path, config, lrclib, models, args):
    given = write(tmp_path / "mine" / "track.wav", "WAV", 2.0)
    result = invoke(config, *(str(given) if a == "FILE" else str(tmp_path / a) if a.endswith(".wav") else a
                              for a in args))
    assert result.exit_code == 2, result.output
    assert kept_files(tmp_path) == [] and models == []


# --- the lock, and what it imports -------------------------------------------------------------------------------


class _Took(Exception):
    """Raised where the command first takes caracole's lock, once the test has seen how."""


def test_it_takes_the_lock_as_asked_for_now(tmp_path, config, lrclib, models, monkeypatch):
    # caracole serve queues it for the owner: a lookup queued after it must not wait behind the whole nightly run
    # it waits for, so it announces itself as a lookup does (interactive), outside the lookups' lane.
    took: list[tuple[str, bool, bool]] = []

    def acquire(cfg, what, *, fatal=True, interactive=False, lane=False, on_wait=None):
        took.append((what, interactive, lane))
        raise _Took

    monkeypatch.setattr(_common, "_acquire", acquire)
    given = write(tmp_path / "mine" / "track.wav", "WAV", 2.0)
    result = invoke(config, str(given), "--song", "Nick Cani - Vikingos veganos", "--progress")
    assert isinstance(result.exception, _Took), result.output
    assert took == [("audio Nick Cani - Vikingos veganos", True, False)]


@pytest.mark.slow
def test_registering_the_command_imports_no_tag_reader_or_model(tmp_path):
    # Every command module is imported on every start, and the default package has no torch.
    code = (
        "import sys\n"
        "from caracole.cli import build_app\n"
        "build_app()\n"
        "print([m for m in ('mutagen', 'rapidfuzz', 'whisper', 'torch', 'librosa', 'caracole.audio_sheet',"
        " 'caracole.audio_store', 'caracole.music') if m in sys.modules])\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
                         check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "[]"


@pytest.mark.slow
def test_the_same_upload_again_once_it_is_the_songs_audio_goes_on_with_it(tmp_path, config, conn, lrclib, models):
    # Try again of a job past its Audio stage: the upload's id is gone, the song's audio is the file it became.
    cfg = load_config(config, env={})
    up = audio_store.stage(cfg, audio("MP3", 200.0), "vikingos.mp3", named=())
    args = ("--upload", up.id, "--song", "Nick Cani - Vikingos veganos")
    assert invoke(config, *args).exit_code == 0
    result = invoke(config, *args)
    assert result.exit_code == 0, result.output
    assert "Audio: has this file's audio already." in result.output.splitlines()
    song = find_song(conn, identity_key("Nick Cani", "Vikingos veganos"))
    assert kept_files(tmp_path) == [Path(song.audio_path).name]


@pytest.mark.slow
def test_an_mp3_whose_first_frame_names_no_length_is_kept_as_long_as_its_frames(tmp_path, config, conn, lrclib,
                                                                                 models):
    # tests/fixtures/audio/short-guess.mp3: 10.1 s of frames, which mutagen and libsndfile guess at 1.7 s.
    given = tmp_path / "mine" / "take.mp3"
    given.parent.mkdir()
    given.write_bytes((Path(__file__).parent / "fixtures" / "audio" / "short-guess.mp3").read_bytes())

    result = invoke(config, str(given), "--song", "Nick Cani - Vikingos veganos")

    assert result.exit_code == 0, result.output
    assert "Audio: kept as its audio: MP3, 0:10." in result.output.splitlines()
    assert "Nick Cani - Vikingos veganos | 0:10" in (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    assert ("get", {"artist_name": "Nick Cani", "track_name": "Vikingos veganos", "duration": "10"}) in lrclib.requests
