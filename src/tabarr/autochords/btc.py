"""Chord recognition with BTC, the Bi-directional Transformer for Chord recognition.

``BTCRecognizer`` loads the published weights, either ``btc_model_large_voca.pt``
(170 classes: 14 qualities on 12 roots, plus unknown and no chord) or
``btc_model.pt`` (25 classes: major and minor), and turns an audio file into
timed chords. The features are upstream's (``audio_file_to_features`` in
``utils/mir_eval_modules.py``): mono audio at 22,050 Hz, a librosa CQT of 144
bins at 24 per octave from C1 with a hop of 2048 samples, computed 10 s at a
time, then ``log(|CQT| + 1e-6)``, normalized with the mean and standard
deviation stored in the checkpoint, and fed to the model 108 frames (10 s) at a
time. The CQT options BTC was trained with, librosa 0.6's defaults, are passed
explicitly, because later librosa versions changed some of them.

The label helpers are pure Python. NumPy, librosa and torch are imported only to
load audio or build a recognizer, so this module imports in any environment.
"""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from tabarr.autochords.merge import NO_CHORD, ChordSegment

if TYPE_CHECKING:
    import numpy as np

SAMPLE_RATE = 22050
CHUNK_SECONDS = 10.0  # upstream's inst_len: the CQT is computed 10 s at a time
N_BINS = 144
BINS_PER_OCTAVE = 24
HOP_LENGTH = 2048
TIMESTEP = 108  # frames per model window: one 10 s chunk
FRAME_SECONDS = CHUNK_SECONDS / TIMESTEP

ROOTS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_QUALITIES = (
    "min", "maj", "dim", "aug", "min6", "maj6", "min7", "minmaj7", "maj7", "7", "dim7", "hdim7",
    "sus2", "sus4",
)  # fmt: skip
_COMMON = {
    "maj": "", "min": "m", "dim": "dim", "aug": "aug", "min6": "m6", "maj6": "6", "min7": "m7",
    "minmaj7": "mMaj7", "maj7": "maj7", "7": "7", "dim7": "dim7", "hdim7": "m7b5",
    "sus2": "sus2", "sus4": "sus4",
}  # fmt: skip

_FLATS = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}
_MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
_FLAT_KEYS = {1, 3, 5, 8, 10}  # Db, Eb, F, Ab and Bb major, and their relative minors
# In C major (or A minor) a black-key chord is usually borrowed: bIII, bVI or bVII.
_C_MAJOR_SPELLING = {"D#": "Eb", "G#": "Ab", "A#": "Bb"}


def vocabulary(num_chords: int) -> list[str]:
    """Harte labels of a BTC model's classes, by index: 170 (large vocabulary) or 25."""
    if num_chords == 25:
        return [f"{root}{suffix}" for root in ROOTS for suffix in ("", ":min")] + [NO_CHORD]
    if num_chords == 170:
        names = [root if q == "maj" else f"{root}:{q}" for root in ROOTS for q in _QUALITIES]
        return names + ["X", NO_CHORD]
    raise ValueError(f"no BTC vocabulary has {num_chords} classes")


def common_name(label: str) -> str:
    """A guitarist's name for a Harte label: "A:min7" → "Am7", "G:7" → "G7", "C:maj" → "C".

    "N" (no chord) and "X" (unknown chord) both become "N".
    """
    if label in (NO_CHORD, "X"):
        return NO_CHORD
    root, _, quality = label.split("/")[0].partition(":")
    quality = quality or "maj"
    return root + _COMMON.get(quality, quality)


def spell_for_key(segments: Sequence[ChordSegment]) -> list[ChordSegment]:
    """Rename black-key roots the way the song's key writes them: Bb in F major, A# in F# major.

    The key is the major scale (equally, its relative minor) whose notes carry the
    most chord time.
    """
    weights = [0.0] * 12
    for s in segments:
        root = s.label.partition(":")[0]
        if root in ROOTS:
            weights[ROOTS.index(root)] += s.end - s.start
    if not any(weights):
        return list(segments)

    def fit(tonic: int) -> float:
        return sum(weights[(tonic + step) % 12] for step in _MAJOR_SCALE)

    tonic = max(range(12), key=fit)
    names = _FLATS if tonic in _FLAT_KEYS else _C_MAJOR_SPELLING if tonic == 0 else {}
    out = []
    for s in segments:
        root, sep, rest = s.label.partition(":")
        out.append(replace(s, label=names.get(root, root) + sep + rest) if root in names else s)
    return out


def frames_to_segments(
    predictions: Sequence[int], frame_seconds: float, names: Sequence[str]
) -> list[ChordSegment]:
    """Runs of equal frame predictions, as timed segments named from ``names``."""
    segs = []
    start = 0
    for i in range(1, len(predictions) + 1):
        if i == len(predictions) or predictions[i] != predictions[start]:
            segs.append(
                ChordSegment(
                    round(start * frame_seconds, 3),
                    round(i * frame_seconds, 3),
                    names[predictions[start]],
                )
            )
            start = i
    return segs


def load_audio(path: Path | str) -> np.ndarray:
    """Mono float32 samples at 22,050 Hz, like upstream's ``librosa.load(sr=22050, mono=True)``.

    libsndfile reads WAV, FLAC, Ogg and MP3. Anything else, such as the AAC in an
    iTunes Store .m4a, is decoded by torchaudio (FFmpeg, through torchcodec), then
    mixed down and resampled the way librosa does it.
    """
    import numpy as np

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"audio file not found: {path}")
    librosa = _librosa()
    try:
        y, _ = librosa.load(path, sr=SAMPLE_RATE, mono=True)
        return y
    except RuntimeError:  # soundfile's LibsndfileError: a format libsndfile cannot read
        import torchaudio

        waveform, sr = torchaudio.load(str(path))
        mono = waveform.mean(dim=0).numpy().astype(np.float32)
        return librosa.resample(mono, orig_sr=sr, target_sr=SAMPLE_RATE, res_type="soxr_hq")


def cqt_features(y: np.ndarray) -> np.ndarray:
    """Upstream's log-CQT of mono 22,050 Hz audio, shaped [frames, 144].

    Unlike upstream, audio of 10 s or less works, and a tail shorter than one hop
    after the last full chunk is skipped instead of failing the CQT.
    """
    import numpy as np

    if len(y) < HOP_LENGTH:
        raise ValueError("audio is too short to recognize chords in")
    chunk = int(SAMPLE_RATE * CHUNK_SECONDS)
    parts = []
    start = 0
    while len(y) > start + chunk:
        parts.append(_cqt(y[start : start + chunk]))
        start += chunk
    if len(y) - start >= HOP_LENGTH or not parts:
        parts.append(_cqt(y[start:]))
    return np.log(np.abs(np.concatenate(parts, axis=1)) + 1e-6).T


def _librosa():
    """librosa, imported after making sure numba has somewhere to write its cache.

    librosa compiles some functions with numba's on-disk cache, which numba keeps
    next to the package or under the home directory. A hardened service has
    neither writable, and numba then fails at import. Unless NUMBA_CACHE_DIR is
    set, the cache goes to the service's cache directory, or to the temp dir.
    """
    if "NUMBA_CACHE_DIR" not in os.environ:
        base = os.environ.get("CACHE_DIRECTORY", "").split(":")[0] or tempfile.gettempdir()
        os.environ["NUMBA_CACHE_DIR"] = os.path.join(base, "numba")
        if "numba" in sys.modules:
            sys.modules["numba"].core.config.reload_config()
    import librosa

    return librosa


def _cqt(y: np.ndarray) -> np.ndarray:
    librosa = _librosa()
    with warnings.catch_warnings():
        # librosa warns when the last, short chunk is shorter than its lowest filters.
        warnings.simplefilter("ignore", UserWarning)
        return librosa.cqt(
            y,
            sr=SAMPLE_RATE,
            hop_length=HOP_LENGTH,
            n_bins=N_BINS,
            bins_per_octave=BINS_PER_OCTAVE,
            tuning=0.0,
            filter_scale=1,
            norm=1,
            sparsity=0.01,
            window="hann",
            scale=True,
            pad_mode="reflect",
        )


class BTCRecognizer:
    """Timed chords from audio, with the published BTC weights.

    ``weights`` is ``btc_model_large_voca.pt`` (preferred) or ``btc_model.pt``.
    A missing file raises FileNotFoundError; a file that is not a BTC checkpoint
    raises ValueError.
    """

    def __init__(self, weights: Path | str, *, device: str = "cpu"):
        weights = Path(weights)
        if not weights.is_file():
            raise FileNotFoundError(f"BTC weights not found: {weights}")
        import torch

        from tabarr.autochords.btc_model import BTCModel

        checkpoint = _load_checkpoint(weights)
        try:
            # The output layer's LSTM is never used at inference; the vendored model drops it.
            state = {
                k: v
                for k, v in checkpoint["model"].items()
                if not k.startswith("output_layer.lstm.")
            }
            num_chords = int(state["output_layer.output_projection.weight"].shape[0])
            self.names = vocabulary(num_chords)
            model = BTCModel(num_chords=num_chords)
            model.load_state_dict(state, strict=True)
            self.mean = float(checkpoint["mean"])
            self.std = float(checkpoint["std"])
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as e:
            raise ValueError(f"{weights} is not a BTC checkpoint: {e}") from e
        self.device = torch.device(device)
        self.model = model.to(self.device).eval()

    def recognize(self, audio_path: Path | str) -> list[ChordSegment]:
        """The chords of an audio file, in common names, with "N" where none is played."""
        import numpy as np
        import torch

        features = (cqt_features(load_audio(audio_path)) - self.mean) / self.std
        frames = len(features)
        padded = np.pad(features, ((0, -frames % TIMESTEP), (0, 0)))
        x = torch.tensor(padded, dtype=torch.float32, device=self.device).view(-1, TIMESTEP, N_BINS)
        with torch.inference_mode():
            predictions = self.model(x).argmax(dim=-1).reshape(-1)[:frames].tolist()
        segs = spell_for_key(frames_to_segments(predictions, FRAME_SECONDS, self.names))
        out: list[ChordSegment] = []
        for s in segs:
            label = common_name(s.label)
            if out and out[-1].label == label:
                out[-1] = replace(out[-1], end=s.end)
            else:
                out.append(replace(s, label=label))
        return out


def _load_checkpoint(path: Path) -> dict:
    """The checkpoint dict, unpickled with torch's weights-only loader.

    Upstream saved the normalization constants as NumPy scalars, so the loader is
    allowed exactly those globals, and nothing else that could run code.
    """
    import numpy as np
    import torch

    core = getattr(np, "_core", None) or np.core
    allowed = [
        (core.multiarray.scalar, "numpy.core.multiarray.scalar"),
        np.dtype,
        np.dtypes.Float64DType,
    ]
    try:
        with torch.serialization.safe_globals(allowed):
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as e:
        raise ValueError(f"{path} is not a BTC checkpoint: {e}") from e
    if not isinstance(checkpoint, dict) or not {"model", "mean", "std"} <= checkpoint.keys():
        raise ValueError(f"{path} is not a BTC checkpoint: expected model, mean and std")
    return checkpoint
