"""Audio as the models read it: mono float32 samples at a given rate, from any file caracole keeps.

libsndfile, which librosa reads with, decodes WAV, FLAC, Ogg and MP3. Anything else is decoded by torchaudio (FFmpeg,
through torchcodec), then mixed down and resampled the way librosa does it: the AAC in an .m4a above all, which is how
caracole keeps every song's audio from YouTube (youtube.py) and how the iTunes Store sells it. BTC's chords
(btc.py ``load_audio``) and the transcription's loudness (separate.py ``frame_db``) both read through ``load_mono``.

NumPy, librosa and torchaudio are imported inside the functions, so this module imports in any environment.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def load_mono(path: Path | str, rate: int) -> np.ndarray:
    """Mono float32 samples at ``rate`` Hz, as ``librosa.load(sr=rate, mono=True)`` gives them, from a file of any
    format libsndfile or FFmpeg decodes. A missing file raises FileNotFoundError; one neither can decode, the
    decoder's own error."""
    import numpy as np

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"audio file not found: {path}")
    librosa = load_librosa()
    try:
        y, _ = librosa.load(path, sr=rate, mono=True)
        return y
    except RuntimeError:  # soundfile's LibsndfileError: a format libsndfile cannot read
        import torchaudio

        waveform, sr = torchaudio.load(str(path))
        mono = waveform.mean(dim=0).numpy().astype(np.float32)
        return librosa.resample(mono, orig_sr=sr, target_sr=rate, res_type="soxr_hq")


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
