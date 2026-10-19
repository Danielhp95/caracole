"""Beats and downbeats with beat_this (CPJKU, ISMIR 2024; nixpkgs beat-this 1.1.0).

beat_this fetches a checkpoint from JKU's servers when it is given a checkpoint
name, or a path that does not exist. The auto-chords unit runs without network
access, so ``detect_beats`` takes the path of the packaged ``final0.ckpt`` and
refuses to start without it.
"""

from __future__ import annotations

import functools
from pathlib import Path


def detect_beats(
    audio_path: Path | str, checkpoint: Path | str, *, device: str = "cpu"
) -> tuple[list[float], list[float]]:
    """Beat and downbeat times of an audio file, in seconds. Every downbeat is also a beat."""
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file():
        raise FileNotFoundError(f"beat_this checkpoint not found: {checkpoint}")
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"audio file not found: {audio_path}")
    beats, downbeats = _tracker(str(checkpoint), device)(str(audio_path))
    return [float(b) for b in beats], [float(d) for d in downbeats]


@functools.lru_cache(maxsize=2)
def _tracker(checkpoint: str, device: str):
    from beat_this.inference import File2Beats

    # dbn=False: the DBN postprocessor needs madmom, which nixpkgs does not ship.
    return File2Beats(checkpoint_path=checkpoint, device=device, dbn=False)
