"""Audio as the models read it: mono float32 samples at a given rate, from any file caracole keeps.

libsndfile, which librosa reads with, decodes WAV, FLAC, Ogg and MP3. Anything else is decoded by torchaudio (FFmpeg,
through torchcodec), then mixed down and resampled the way librosa does it: the AAC in an .m4a above all, which is how
caracole keeps every song's audio from YouTube (youtube.py) and how the iTunes Store sells it; and an MP3 whose first
frame names no length where libsndfile decodes it only in part (``load_mono``). BTC's chords (btc.py ``load_audio``) and
the transcription's loudness (separate.py ``frame_db``) both read through ``load_mono``; beat_this reads with its own
loader, FFmpeg's first (beats.py).

NumPy, librosa and torchaudio are imported inside the functions, so this module imports in any environment.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

DISAGREES_S = 0.5  # how far libsndfile's decode of an MP3 may be from its frames' length before FFmpeg reads it


def load_mono(path: Path | str, rate: int) -> np.ndarray:
    """Mono float32 samples at ``rate`` Hz, as ``librosa.load(sr=rate, mono=True)`` gives them, from a file of any
    format libsndfile or FFmpeg decodes. A missing file raises FileNotFoundError; one neither can decode, the
    decoder's own error.

    An MP3 whose first frame names no length is decoded by libsndfile only as far as it guesses (its size over the
    first frame's bitrate), with no error: where that decode is more than ``DISAGREES_S`` off the length its
    frames say (mpeg_frames.py), it is read again through FFmpeg, which decodes every frame, as beat_this reads it,
    with a warning naming the file; should FFmpeg fail, libsndfile's part is kept, with a warning saying how much of
    the file it is. Every other file is read as libsndfile reads it."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"audio file not found: {path}")
    librosa = load_librosa()
    try:
        y, _ = librosa.load(path, sr=rate, mono=True)
    except RuntimeError:  # soundfile's LibsndfileError: a format libsndfile cannot read
        return _ffmpeg(path, rate)
    from caracole.mpeg_frames import counted_length

    counted = counted_length(path)
    if counted is None or abs(len(y) / rate - counted) <= DISAGREES_S:
        return y
    log.warning("%s: libsndfile decoded %.1f s of the %.1f s its MP3 frames hold; read again through FFmpeg.",
                path, len(y) / rate, counted)
    try:
        return _ffmpeg(path, rate)
    except Exception as e:  # noqa: BLE001 - no worse than libsndfile's read, which is kept, and said
        log.warning("%s: FFmpeg couldn't read it again (%s): only the %.1f s libsndfile decoded of its %.1f s are "
                    "heard.", path, e, len(y) / rate, counted)
        return y


def _ffmpeg(path: Path, rate: int) -> np.ndarray:
    """The file decoded by torchaudio (FFmpeg, through torchcodec), mixed down and resampled as librosa does it."""
    import numpy as np
    import torchaudio

    waveform, sr = torchaudio.load(str(path))
    mono = waveform.mean(dim=0).numpy().astype(np.float32)
    return load_librosa().resample(mono, orig_sr=sr, target_sr=rate, res_type="soxr_hq")


def load_librosa():
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
