"""Real AAC audio in an .m4a, as yt-dlp writes YouTube's audio for caracole (youtube.py's ``m4a``), made at test time.

``aac_m4a(path, stretches)`` writes stereo AAC at 44.1 kHz with torchcodec's encoder (FFmpeg's own AAC encoder, from
the FFmpeg torchaudio decodes with), from ``(seconds, amplitude)`` stretches of a 220 Hz tone, amplitude 0 for
silence; ``samples(stretches)`` is that signal, mono, for a stem of the same song. Both need numpy, and ``aac_m4a``
torch and torchcodec: call them from a test marked ``autochords``, which skips without them (``needs_aac``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RATE = 44100
TONE_HZ = 220.0

needs_aac = pytest.mark.skipif(
    not all(importlib.util.find_spec(name) for name in ("numpy", "torch", "torchcodec", "librosa", "torchaudio")),
    reason="needs numpy, torch, torchcodec, torchaudio and librosa",
)


def samples(stretches: list[tuple[float, float]]):
    """The signal, mono float32 at ``RATE``: each stretch a tone of its amplitude, phase running on."""
    import numpy as np

    total = sum(round(seconds * RATE) for seconds, _ in stretches)
    t = np.arange(total) / RATE
    level = np.concatenate([np.full(round(seconds * RATE), amplitude) for seconds, amplitude in stretches])
    return (level * np.sin(2 * np.pi * TONE_HZ * t)).astype(np.float32)


def aac_m4a(path: Path, stretches: list[tuple[float, float]]) -> Path:
    """The stretches as AAC at 128 kb/s in an .m4a at ``path``, both channels alike."""
    import torch
    from torchcodec.encoders import AudioEncoder

    mono = torch.from_numpy(samples(stretches))
    path.parent.mkdir(parents=True, exist_ok=True)
    AudioEncoder(mono.repeat(2, 1), sample_rate=RATE).to_file(str(path), bit_rate=128_000)  # YouTube's format 140
    return path
