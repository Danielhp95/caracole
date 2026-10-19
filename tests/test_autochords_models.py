"""Auto-chords models: BTC chord recognition and beat_this beat tracking.

Tests marked ``autochords`` need torch, librosa and beat_this, and the model
files: set TABARR_BTC_WEIGHTS and TABARR_BEAT_CHECKPOINT, or put the files under
TABARR_MODELS_DIR. Run them in the auto-chords environment. The other tests here
cover the pure helpers and run anywhere.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tabarr.autochords import ChordSegment
from tabarr.autochords.beats import detect_beats
from tabarr.autochords.btc import (
    BTCRecognizer,
    common_name,
    frames_to_segments,
    spell_for_key,
    vocabulary,
)

from conftest import subprocess_pythonpath

# Where this project's development session keeps downloaded weights; anywhere
# else, set the environment variables above.
_DEV_MODELS = Path(
    "/tmp/tabarr-dev/models"
)
MODELS_DIR = Path(os.environ.get("TABARR_MODELS_DIR", _DEV_MODELS))


def _imports(*names: str) -> bool:
    try:
        for name in names:
            importlib.import_module(name)
    except (ImportError, OSError):  # missing, or a native library that fails to load
        return False
    return True


def _model_file(env_var: str, name: str) -> Path | None:
    value = os.environ.get(env_var)
    if value:
        return Path(value) if Path(value).is_file() else None
    return next(MODELS_DIR.rglob(name), None) if MODELS_DIR.is_dir() else None


HAVE_LIBS = _imports("numpy", "soundfile", "torch", "librosa", "beat_this")
BTC_WEIGHTS = _model_file("TABARR_BTC_WEIGHTS", "btc_model_large_voca.pt")
BTC_MAJMIN_WEIGHTS = _model_file("TABARR_BTC_MAJMIN_WEIGHTS", "btc_model.pt")
BEAT_CHECKPOINT = _model_file("TABARR_BEAT_CHECKPOINT", "final0.ckpt")

needs_libs = pytest.mark.skipif(not HAVE_LIBS, reason="needs torch, librosa and beat_this")
needs_btc = pytest.mark.skipif(BTC_WEIGHTS is None, reason="no BTC weights")
needs_beat_this = pytest.mark.skipif(BEAT_CHECKPOINT is None, reason="no beat_this checkpoint")

SR = 22050


def _triads(path: Path) -> Path:
    """C major for 0–5 s, then G major for 5–10 s, as tones with four harmonics."""
    import numpy as np
    import soundfile as sf

    def tone(midi: int, seconds: float):
        t = np.arange(int(seconds * SR)) / SR
        f = 440.0 * 2 ** ((midi - 69) / 12)
        return sum(0.5**k * np.sin(2 * np.pi * f * (k + 1) * t) for k in range(4))

    def triad(root: int, seconds: float):
        return sum(tone(root + step, seconds) for step in (0, 4, 7))

    y = np.concatenate([triad(60, 5.0), triad(55, 5.0)])  # C4 E4 G4, then G3 B3 D4
    sf.write(path, 0.3 * y / np.abs(y).max(), SR)
    return path


def _drums(path: Path, *, bpm: float = 120.0, seconds: float = 12.0) -> Path:
    """Kick on beats 1 and 3, snare on 2 and 4, hi-hat on the off-beats."""
    import numpy as np
    import soundfile as sf

    rng = np.random.default_rng(0)
    y = np.zeros(int(seconds * SR))
    half = 30.0 / bpm
    n = int(0.15 * SR)
    t = np.arange(n) / SR
    for k in range(int(seconds / half)):
        if k % 2:
            hit = 0.15 * rng.standard_normal(n) * np.exp(-t * 80)
        elif k % 4 == 0:
            sweep = 120 * np.exp(-t * 20) + 40
            hit = np.sin(2 * np.pi * np.cumsum(sweep) / SR) * np.exp(-t * 15)
        else:
            hit = 0.6 * rng.standard_normal(n) * np.exp(-t * 25)
        start = round(k * half * SR)
        y[start : start + n] += hit[: len(y) - start]
    sf.write(path, 0.5 * y / np.abs(y).max(), SR)
    return path


def _label_at(segs: list[ChordSegment], t: float) -> str | None:
    return next((s.label for s in segs if s.start <= t < s.end), None)


def test_large_vocabulary_indices_name_harte_labels():
    names = vocabulary(170)
    assert (names[0], names[1], names[9], names[14], names[15], names[167]) == (
        "C:min",
        "C",
        "C:7",
        "C#:min",
        "C#",
        "B:sus4",
    )
    assert (names[168], names[169]) == ("X", "N")
    assert vocabulary(25)[:2] == ["C", "C:min"] and vocabulary(25)[24] == "N"


def test_harte_labels_become_common_names():
    cases = {
        "C": "C",
        "C:maj": "C",
        "A:min": "Am",
        "A:min7": "Am7",
        "G:7": "G7",
        "F#:min": "F#m",
        "D:maj7": "Dmaj7",
        "E:minmaj7": "EmMaj7",
        "B:hdim7": "Bm7b5",
        "C:dim": "Cdim",
        "C:dim7": "Cdim7",
        "C:aug": "Caug",
        "C:maj6": "C6",
        "A:min6": "Am6",
        "D:sus2": "Dsus2",
        "D:sus4": "Dsus4",
        "N": "N",
        "X": "N",
    }
    assert {label: common_name(label) for label in cases} == cases


def test_black_key_roots_are_spelled_for_the_song_key():
    def song(*labels: str) -> list[ChordSegment]:
        return [ChordSegment(2.0 * k, 2.0 * (k + 1), label) for k, label in enumerate(labels)]

    # F major: A# is written Bb.
    assert [s.label for s in spell_for_key(song("F", "A#", "C", "D:min"))] == [
        "F",
        "Bb",
        "C",
        "D:min",
    ]
    # E major keeps its sharps.
    assert [s.label for s in spell_for_key(song("E", "B", "C#:min", "A"))] == [
        "E",
        "B",
        "C#:min",
        "A",
    ]
    # Ab major: G#, C# and D# become Ab, Db and Eb.
    assert [s.label for s in spell_for_key(song("G#", "C#", "D#:7", "F:min"))] == [
        "Ab",
        "Db",
        "Eb:7",
        "F:min",
    ]
    # C major with a borrowed bVII: Bb, not A#.
    assert [s.label for s in spell_for_key(song("C", "A#", "F", "C"))] == ["C", "Bb", "F", "C"]
    # Still C major (the B chord rules out the flat keys), with a borrowed bVI.
    c_major = song("C", "C", "C", "C", "G", "G", "F", "F", "B:dim", "G#")
    assert [s.label for s in spell_for_key(c_major)][-2:] == ["B:dim", "Ab"]


def test_frames_become_segments():
    names = vocabulary(25)
    # C, C, Am, Am, Am, N at 0.5 s per frame.
    segs = frames_to_segments([0, 0, 19, 19, 19, 24], 0.5, names)
    assert segs == [
        ChordSegment(0.0, 1.0, "C"),
        ChordSegment(1.0, 2.5, "A:min"),
        ChordSegment(2.5, 3.0, "N"),
    ]


def test_missing_btc_weights_raise_before_any_model_code(tmp_path):
    with pytest.raises(FileNotFoundError):
        BTCRecognizer(tmp_path / "nope.pt")


def test_missing_beat_checkpoint_never_downloads(tmp_path):
    # beat_this would fetch an unknown checkpoint name from the network.
    with pytest.raises(FileNotFoundError):
        detect_beats(tmp_path / "song.wav", tmp_path / "final0.ckpt")


@pytest.mark.autochords
@needs_libs
def test_a_checkpoint_that_is_not_btc_is_refused(tmp_path):
    import torch

    for k, model in enumerate(({"weight": torch.zeros(2, 2)}, [torch.zeros(2)])):
        bogus = tmp_path / f"bogus{k}.pt"
        torch.save({"model": model, "mean": 0.0, "std": 1.0}, bogus)
        with pytest.raises(ValueError, match="BTC"):
            BTCRecognizer(bogus)


@pytest.mark.autochords
@needs_libs
def test_a_sliver_after_the_last_full_chunk_is_skipped_quietly():
    import warnings

    import numpy as np

    from tabarr.autochords.btc import cqt_features

    rng = np.random.default_rng(0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        # 10 s plus one sample: the one-sample tail is shorter than a frame and is dropped.
        assert cqt_features(rng.standard_normal(220_501).astype(np.float32)).shape == (108, 144)
        # A tail of a few frames is analysed, as upstream does.
        assert cqt_features(rng.standard_normal(225_500).astype(np.float32)).shape == (111, 144)


@pytest.mark.autochords
@needs_libs
def test_features_work_without_a_writable_home(tmp_path):
    # A hardened unit has no home, and the package directory is read-only, so
    # numba (inside librosa) has nowhere to put its cache unless we give it one.
    import sys

    src = Path(__file__).resolve().parents[1] / "src"
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o555)
    code = (
        "import numpy\n"
        "from tabarr.autochords.btc import cqt_features\n"
        "print(cqt_features(numpy.zeros(4096, 'float32')).shape)"
    )
    env = {"HOME": str(locked / "home"), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            cwd=tmp_path,
            check=False,
        )
    finally:
        locked.chmod(0o755)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "(3, 144)"


@pytest.mark.autochords
@needs_libs
@needs_btc
def test_btc_recognizes_synthetic_triads(tmp_path):
    segs = BTCRecognizer(BTC_WEIGHTS).recognize(_triads(tmp_path / "triads.wav"))
    assert [_label_at(segs, t) for t in (1.0, 2.5, 4.0)] == ["C", "C", "C"]
    assert [_label_at(segs, t) for t in (6.0, 7.5, 9.0)] == ["G", "G", "G"]
    assert segs[-1].end == pytest.approx(10.0, abs=0.1)


@pytest.mark.autochords
@needs_libs
@pytest.mark.skipif(BTC_MAJMIN_WEIGHTS is None, reason="no major/minor BTC weights")
def test_the_major_minor_model_loads_too(tmp_path):
    segs = BTCRecognizer(BTC_MAJMIN_WEIGHTS).recognize(_triads(tmp_path / "triads.wav"))
    assert [_label_at(segs, t) for t in (2.5, 7.5)] == ["C", "G"]


@pytest.mark.autochords
@needs_libs
@needs_btc
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg to encode AAC")
def test_btc_reads_aac_from_the_itunes_store(tmp_path):
    # libsndfile cannot decode .m4a, so the recognizer falls back to torchaudio.
    wav = _triads(tmp_path / "triads.wav")
    m4a = tmp_path / "triads.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "192k", str(m4a)],
        check=True,
    )
    segs = BTCRecognizer(BTC_WEIGHTS).recognize(m4a)
    assert [_label_at(segs, t) for t in (2.5, 7.5)] == ["C", "G"]


@pytest.mark.autochords
@needs_libs
@needs_beat_this
def test_beat_this_finds_half_second_beats_at_120_bpm(tmp_path):
    import numpy as np

    beats, downbeats = detect_beats(_drums(tmp_path / "drums.wav"), BEAT_CHECKPOINT)
    assert len(beats) >= 20
    assert float(np.median(np.diff(beats))) == pytest.approx(0.5, abs=0.02)
    assert beats[0] < 0.6 and beats[-1] > 11.0
    assert set(downbeats) <= set(beats)
