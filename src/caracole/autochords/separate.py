"""The vocal stem, separated by demucs-rs, and its loudness frame by frame.

demucs-rs is a Rust program, run as a subprocess; it separates the full mix only so that
``words.sung_spans`` can tell where someone sings (the transcript is Whisper's, from the mix).
"""

import os
import subprocess
from pathlib import Path
from typing import Protocol

from caracole.autochords.words import FRAME_S


class SeparatorFailed(Exception):
    """demucs-rs exited nonzero or wrote no vocal stem; the message carries its last stderr line."""


class Separator(Protocol):
    def vocals(self, audio: Path, workdir: Path) -> Path: ...


class DemucsSeparator:
    """demucs-rs on a file. It reads its model only from ``$XDG_CACHE_HOME/demucs-rs/htdemucs.safetensors`` (and
    downloads it otherwise), so each run gets a private XDG_CACHE_HOME holding a symlink to the pinned model.

    burn's autotune cache (measured, demucs-rs 0.3.4) goes to ``$XDG_CONFIG_HOME/autotune/0.9.0/<device>/``: the
    GPU (wgpu) build writes it there, and a warm cache cut a 4 s clip from 70 s to 25 s; the cpu (ndarray) build
    writes none, so for it the setting is harmless. It is kept at ``cache_dir/demucs-rs`` between runs. Nothing
    lands in HOME or the working directory. The driver's own shader caches (``mesa_shader_cache``, ``nvidia``)
    go to XDG_CACHE_HOME and are lost with the work directory."""

    def __init__(self, binary: str, model: Path, cache_dir: Path):
        self.binary = binary
        self.model = model
        self.cache_dir = cache_dir

    def vocals(self, audio: Path, workdir: Path) -> Path:
        cache = workdir / "cache"
        (cache / "demucs-rs").mkdir(parents=True, exist_ok=True)
        link = cache / "demucs-rs" / "htdemucs.safetensors"
        link.unlink(missing_ok=True)
        link.symlink_to(self.model.resolve())
        config = self.cache_dir / "demucs-rs"
        config.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "XDG_CACHE_HOME": str(cache), "XDG_CONFIG_HOME": str(config)}
        stems = workdir / "stems"
        cmd = [self.binary, "-m", "htdemucs", "-s", "vocals", "-o", str(stems), str(audio)]
        try:
            done = subprocess.run(cmd, env=env, capture_output=True, text=True)
        except OSError as e:
            raise SeparatorFailed(f"demucs-rs won't run: {e}") from e
        if done.returncode != 0:
            lines = [ln for ln in done.stderr.splitlines() if ln.strip()]
            raise SeparatorFailed(lines[-1].strip() if lines else f"demucs-rs exited {done.returncode}")
        out = stems / "vocals.wav"
        if not out.is_file():
            raise SeparatorFailed(f"demucs-rs wrote no vocals.wav under {stems}")
        return out


def frame_db(path: Path, *, frame_s: float = FRAME_S, rate: int = 16000) -> list[float]:
    """The RMS loudness of each ``frame_s`` frame of the audio at ``path``, in dB, one value per frame."""
    import librosa

    samples, _ = librosa.load(path, sr=rate, mono=True)
    hop = max(1, round(frame_s * rate))
    rms = librosa.feature.rms(y=samples, frame_length=2 * hop, hop_length=hop)[0]
    return [float(v) for v in librosa.amplitude_to_db(rms, ref=1.0, amin=1e-5, top_db=None)]
