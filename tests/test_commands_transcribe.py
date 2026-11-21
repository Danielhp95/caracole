"""``caracole transcribe``: a song's lyrics transcribed from its YouTube audio, then its auto sheet made again.

Every model the command would build is a fake (demucs-rs, Whisper, BTC, beat_this, librosa's loudness), chordpro a
script that writes a PDF, and every site a client the test refuses to make: nothing reaches the network, and no
model runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import subprocess_pythonpath
from test_transcribe_job import MIX, STEM, WORDS, offered
from test_youtube_sheet import wav
from typer.testing import CliRunner

import caracole.autochords.run as ac_run
import caracole.youtube_fetch as yf
from caracole.autochords import ChordSegment, separate
from caracole.autochords import transcribe as tx
from caracole.cli import build_app
from caracole.commands import _common
from caracole.config import load_config
from caracole.db import kv_get
from caracole.get import read_progress_line
from caracole.songs import update_song

FAKE_CHORDPRO = """\
#!{python}
import sys

out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
with open(out, "w", encoding="utf-8") as f:
    f.write("%PDF-1.4 fake")
"""
# Settings a shell could leak in (the auto-chords shells set the model files): none may reach a test.
OUTSIDE_SETTINGS = ("CARACOLE_CONFIG", "CARACOLE_BTC_WEIGHTS", "CARACOLE_BEAT_CHECKPOINT", "CARACOLE_WHISPER_MODEL",
                    "CARACOLE_DEMUCS_MODEL", "CARACOLE_TORCH_CUDA")


@pytest.fixture
def config(tmp_path, monkeypatch) -> Path:
    """caracole.toml beside conftest's database, with a chordpro that writes a PDF and model files (unread)."""
    for name in OUTSIDE_SETTINGS:
        monkeypatch.delenv(name, raising=False)

    def transport(provider):
        pytest.fail(f"a client for {provider} was made")

    monkeypatch.setattr(_common, "transport_for", transport)
    chordpro = tmp_path / "bin" / "chordpro"
    chordpro.parent.mkdir(parents=True)
    chordpro.write_text(FAKE_CHORDPRO.format(python=sys.executable), encoding="utf-8")
    chordpro.chmod(0o755)
    models = tmp_path / "models"
    models.mkdir()
    for name in ("btc.pt", "final0.ckpt", "large-v3.pt", "htdemucs.safetensors"):
        (models / name).write_bytes(b"model")
    folders = (("library_dir", "lib"), ("music_dir", "music"), ("state_dir", "state"), ("cache_dir", "cache"))
    lines = [f'{key} = "{tmp_path / name}"' for key, name in folders]
    lines += [f'chordpro_bin = "{chordpro}"', "[autochords]", f'btc_weights = "{models / "btc.pt"}"',
              f'beat_checkpoint = "{models / "final0.ckpt"}"', f'whisper_model = "{models / "large-v3.pt"}"',
              f'separator_model = "{models / "htdemucs.safetensors"}"']
    path = tmp_path / "caracole.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def models(monkeypatch) -> list[str]:
    """The models the command builds, each a fake noting what it heard: demucs-rs, Whisper, BTC and beat_this."""
    heard: list[str] = []

    class Demucs:
        def __init__(self, binary, model, cache_dir, timeout=0.0):
            pass

        def vocals(self, audio, workdir):
            heard.append(f"demucs {Path(audio).name}")
            return wav(Path(workdir) / "stems" / "vocals.wav", 1.0)

    class Whisper:
        def __init__(self, model_path, *, device, cache_dir):
            self.device = device

        def hear(self, mix, stem, first_sung_s):
            heard.append(f"whisper {Path(mix).name}")
            return tx.Heard("es", list(WORDS))

    class BTC:
        def __init__(self, weights, *, device="cpu"):
            pass

        def recognize(self, path):
            heard.append(f"btc {Path(path).name}")
            return [ChordSegment(0.0, 30.0, "D"), ChordSegment(30.0, 60.0, "A")]

    monkeypatch.setattr(separate, "DemucsSeparator", Demucs)
    monkeypatch.setattr(separate, "frame_db",
                        lambda path, **kw: list(STEM if Path(path).name == "vocals.wav" else MIX))
    monkeypatch.setattr(tx, "WhisperTranscriber", Whisper)
    monkeypatch.setattr(tx, "resolve_device", lambda setting: "cpu")
    monkeypatch.setattr(ac_run, "BTCRecognizer", BTC)
    monkeypatch.setattr(ac_run, "detect_beats", lambda path, checkpoint, device="cpu": (
        [0.5 * i for i in range(121)], [2.0 * i for i in range(31)]))
    return heard


def invoke(config: Path, *args: str):
    return CliRunner().invoke(build_app(), ["--config", str(config), "transcribe", *args])


@pytest.mark.slow
def test_transcribe_says_each_stage_and_exits_0(tmp_path, config, conn, models, monkeypatch):
    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: None)  # as with Whisper, its models and demucs-rs
    song = offered(conn, load_config(config, env={}))
    result = invoke(config, "--song", "Nick Cani - Vikingos veganos", "--progress")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    for said in ("Song: in the book.", "Vocals: sung from 24.8 s, 1 stretch.",
                 "Words: 6 words in 2 lines (es), 1 dropped.", "Chords: chords over the transcribed lyrics.",
                 "PDF: made.", "Pages: _todo.md and index.html rewritten."):
        assert said in lines, result.output
    sheet = tmp_path / "lib" / "Nick Cani" / "Vikingos veganos" / "sheet (auto).txt"
    assert any(line.startswith(f"Sheet: {sheet}, readable after") for line in lines)
    events = [e for e in map(read_progress_line, lines) if e is not None]
    assert {"stage": "words", "state": "done", "detail": "6 words in 2 lines (es), 1 dropped"} in events
    assert {"song": {"id": song.id, "display": "Nick Cani - Vikingos veganos"}} in events
    assert events[-1]["done"]["ok"] is True and events[-1]["done"]["refused"] is None
    assert any(line.startswith("Done in ") for line in lines)
    # Whisper and BTC heard a test tone before the song's audio; demucs-rs, the song alone.
    audio = Path(song.audio_path).name
    assert models == [f"demucs {audio}", "whisper test-tone.wav", f"whisper {audio}", "btc test-tone.wav",
                      f"btc {audio}"]
    assert kv_get(conn, f"transcript:{song.id}") is not None


def test_transcribe_refuses_a_song_not_offered_and_exits_1(tmp_path, config, conn, models, monkeypatch):
    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: None)
    song = offered(conn, load_config(config, env={}))
    update_song(conn, song.id, lyrics_status="found")
    result = invoke(config, "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 1, result.output
    assert ("No transcript made: Nick Cani - Vikingos veganos isn't offered a transcription: its lyrics are "
            "found.") in result.output
    assert models == []


def test_transcribe_where_it_cant_run_says_why_and_exits_1(tmp_path, config, conn, models, monkeypatch):
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    song = offered(conn, load_config(config, env={}))
    result = invoke(config, "--song", "Nick Cani - Vikingos veganos")
    assert result.exit_code == 1
    assert ("caracole transcribes nothing here: built without auto-chords (missing: torch): nothing to make of the "
            "audio") in result.output
    assert models == [] and kv_get(conn, f"transcript:{song.id}") is None
    assert not (tmp_path / "state" / "caracole.lock").exists()  # it asked for nothing, the lock included


@pytest.mark.parametrize("args", [("--song", "Nick Cani"), ()], ids=["no title", "no song"])
def test_a_song_that_isnt_artist_and_title_is_a_usage_error(tmp_path, config, models, args):
    result = invoke(config, *args)
    assert result.exit_code == 2, result.output
    assert models == []


@pytest.mark.slow
def test_registering_the_command_imports_no_model(tmp_path):
    # Every command module is imported on every start, and the default package has neither Whisper nor torch.
    code = (
        "import sys\n"
        "from caracole.cli import build_app\n"
        "build_app()\n"
        "print([m for m in ('whisper', 'torch', 'librosa', 'caracole.transcribe_job', 'caracole.autochords.transcribe')"
        " if m in sys.modules])\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True,
                         check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "[]"
