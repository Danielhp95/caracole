"""What the computer's models make of an audio file, step by step: the reference the phone's port is held to.

- ``reference(path, *, btc=None, beats=None, threads=1) -> Reference``: the computer's own path, each step kept:
  - ``decoded``: the mono float32 samples at 22,050 Hz BTC reads (btc.py ``load_audio``);
  - ``features``: BTC's raw log-CQT, float32 ``[frames, 144]`` (btc.py ``cqt_features``), before its normalization;
  - ``logits``: BTC's, float32 ``[frames, 170]``, of the normalized features in windows of 108 frames, the last one
    padded with normalized zeros (the raw features' mean), as ``BTCRecognizer.recognize`` runs it;
  - ``segments``: the chords ``recognize`` gives, ``[start, end, name]``, spelled for the key, in common names;
  - ``mel``: beat_this's log-mel, float32 ``[T, 128]``, of the audio as beat_this loads it (its ``load_audio``, then
    ``signal2spect``);
  - ``beat_logits``: beat_this's beat and downbeat logits, float32 ``[T]`` each, in its 1500-frame chunks
    (``spect2frames``), and ``beats``, ``downbeats``, its minimal postprocessor's, in seconds;
  - ``duration``: the file's length as run.py reads it (music.py ``read_audio``, mutagen's), None where it has none.
  The models are the environment's (``CARACOLE_BTC_WEIGHTS``, ``CARACOLE_BEAT_CHECKPOINT``) unless named, and run on
  ``threads`` of torch's (1, so that a second run gives the same bits).
- ``logits_of(mel, beats=None, threads=1)``: beat_this's logits of a log-mel given, as ``spect2frames`` gives them,
  and ``peaks_of(beat, downbeat)``, its minimal postprocessor's beats and downbeats.
- ``python -m tests.helpers.autochords_reference IN OUT``: the reference of every audio file in the folder ``IN`` (or
  of the one file ``IN``), each as ``OUT/<name>.json`` (the arrays base64 of little-endian float32, as the corpus
  writes them, ``encoded``), for songs that are never committed: the owner's own, kept outside the repository.

torch, librosa, numpy and beat_this are imported inside the functions: only the auto-chords environment has them.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUDIO = (".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a", ".aac", ".aiff", ".aif")


@dataclass(frozen=True)
class Reference:
    decoded: Any
    features: Any
    logits: Any
    segments: list[list]
    mel: Any
    beat_logits: tuple[Any, Any]
    beats: list[float]
    downbeats: list[float]
    duration: float | None


def _model_path(given: Path | str | None, env_var: str) -> Path:
    path = given or os.environ.get(env_var)
    if not path:
        raise FileNotFoundError(f"no model file: name one, or set {env_var}")
    return Path(path)


@contextlib.contextmanager
def torch_threads(n: int):
    """torch on ``n`` threads inside the block, as many as before after it."""
    import torch

    before = torch.get_num_threads()
    torch.set_num_threads(n)
    try:
        yield
    finally:
        torch.set_num_threads(before)


def btc_logits(recognizer, features):
    """BTC's logits of raw log-CQT frames, ``[frames, 170]`` float32, as ``BTCRecognizer.recognize`` computes its
    predictions: normalized by the checkpoint's mean and std, padded to whole windows with zeros, cut back."""
    import numpy as np
    import torch

    from caracole.autochords.btc import N_BINS, TIMESTEP

    normalized = (features - recognizer.mean) / recognizer.std
    frames = len(normalized)
    padded = np.pad(normalized, ((0, -frames % TIMESTEP), (0, 0)))
    x = torch.tensor(padded, dtype=torch.float32, device=recognizer.device).view(-1, TIMESTEP, N_BINS)
    with torch.inference_mode():
        out = recognizer.model(x).reshape(-1, len(recognizer.names))[:frames]
    return out.cpu().numpy().astype(np.float32)


def btc_segments(recognizer, logits) -> list[list]:
    """The chords ``recognize`` names for those logits: runs of each frame's argmax, spelled for the key, joined."""
    from caracole.autochords.btc import FRAME_SECONDS, common_name, frames_to_segments, spell_for_key

    predictions = logits.argmax(axis=-1).tolist()
    out: list[list] = []
    for s in spell_for_key(frames_to_segments(predictions, FRAME_SECONDS, recognizer.names)):
        label = common_name(s.label)
        if out and out[-1][2] == label:
            out[-1][1] = s.end
        else:
            out.append([s.start, s.end, label])
    return out


def _tracker(beats: Path | str | None):
    from caracole.autochords.beats import _tracker

    return _tracker(str(_model_path(beats, "CARACOLE_BEAT_CHECKPOINT")), "cpu")


def logits_of(mel, beats: Path | str | None = None, threads: int = 1):
    """beat_this's beat and downbeat logits, float32 ``[T]`` each, of a log-mel ``[T, 128]``."""
    import numpy as np
    import torch

    with torch_threads(threads):
        beat, downbeat = _tracker(beats).spect2frames(torch.from_numpy(np.ascontiguousarray(mel, dtype=np.float32)))
    return beat.numpy().astype(np.float32), downbeat.numpy().astype(np.float32)


def peaks_of(beat, downbeat) -> tuple[list[float], list[float]]:
    """beat_this's minimal postprocessor over those logits: the beats and downbeats, in seconds."""
    import torch
    from beat_this.model.postprocessor import Postprocessor

    b, d = Postprocessor(type="minimal")(torch.from_numpy(beat), torch.from_numpy(downbeat))
    return [float(t) for t in b], [float(t) for t in d]


def reference(path: Path | str, *, btc: Path | str | None = None, beats: Path | str | None = None,
              threads: int = 1) -> Reference:
    """The computer's models' every step over the audio at ``path``."""
    import numpy as np
    import torch
    from beat_this.preprocessing import load_audio as beat_this_load

    from caracole.autochords.btc import BTCRecognizer, cqt_features, load_audio
    from caracole.music import read_audio

    path = Path(path)
    decoded = load_audio(path)
    features = cqt_features(decoded).astype(np.float32)
    recognizer = BTCRecognizer(_model_path(btc, "CARACOLE_BTC_WEIGHTS"))
    with torch_threads(threads):
        logits = btc_logits(recognizer, features)
        signal, rate = beat_this_load(str(path))
        with torch.inference_mode():
            mel = _tracker(beats).signal2spect(signal, rate).numpy().astype(np.float32)
    beat, downbeat = logits_of(mel, beats, threads)
    found, down = peaks_of(beat, downbeat)
    return Reference(decoded=decoded, features=features, logits=logits, segments=btc_segments(recognizer, logits),
                     mel=mel, beat_logits=(beat, downbeat), beats=found, downbeats=down,
                     duration=read_audio(path).duration_s)


def array(a, dtype: str = "float32") -> dict:
    """An array as the corpus writes one: its dtype, its shape, and base64 of its little-endian bytes, row-major."""
    import numpy as np

    data = np.ascontiguousarray(a, dtype=np.dtype(dtype).newbyteorder("<"))
    return {"dtype": dtype, "shape": list(data.shape), "base64": base64.b64encode(data.tobytes()).decode("ascii")}


def encoded(ref: Reference) -> dict:
    """A reference as JSON's values: every array by ``array``, the rest as it is."""
    return {
        "decoded": array(ref.decoded), "features": array(ref.features), "logits": array(ref.logits),
        "segments": ref.segments, "mel": array(ref.mel),
        "beat_logits": {"beat": array(ref.beat_logits[0]), "downbeat": array(ref.beat_logits[1])},
        "beats": ref.beats, "downbeats": ref.downbeats, "duration": ref.duration,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m tests.helpers.autochords_reference IN OUT", file=sys.stderr)
        return 2
    given, out = Path(argv[0]), Path(argv[1])
    files = [given] if given.is_file() else sorted(p for p in given.iterdir() if p.suffix.lower() in AUDIO)
    if not files:
        print(f"no audio file in {given}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        doc = {"file": f.name, **encoded(reference(f, threads=os.cpu_count() or 1))}
        (out / f"{f.stem}.json").write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{f.name}: {len(doc['segments'])} chords, {len(doc['beats'])} beats", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
