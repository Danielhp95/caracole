"""The vocal stem, separated by demucs-rs, and its loudness frame by frame.

demucs-rs is a Rust program, run as a subprocess; it separates the full mix only so that
``words.sung_spans`` can tell where someone sings (the transcript is Whisper's, from the mix). It says nothing of how
far it is, so the caller is told how long it has run as it goes (``on_tick``). The loudness of the mix and of the
stem is ``frame_db``'s, read through audio.py.
"""

import logging
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from caracole.autochords.words import FRAME_S

log = logging.getLogger(__name__)

# The cpu build runs about 4.8x the song's length, so a long song takes most of an hour; a run past this is hung
# (a wgpu or driver stall), not slow.
TIMEOUT_S = 4 * 3600.0
TICK_S = 5.0  # how often a run that goes on tells its caller how long it has run (``on_tick``)
# How long demucs-rs takes for a second of the song, measured: the cpu build about 4.8 s, the GPU (wgpu) build about
# 0.3 s once its shaders are compiled (half of a 149 s song's 83-87 s transcription; a cold first run adds a minute).
CPU_PACE, GPU_PACE = 4.8, 0.3
# demucs-rs 0.3.4 names no adapter or backend (nor does cubecl's CUBECL_DEBUG_LOG make it): what it says that bears
# on its device is its GPU shaders ("Pre-compiling GPU shaders", the wgpu build) and a driver's own words after it
# ("NVVM compilation failed: 3", NVIDIA's compiler), logged at INFO so the journal shows where it ran.
_DEVICE_WORDS = re.compile(r"\b(GPU|NVVM|NVIDIA|adapter|backend|Vulkan|lavapipe|llvmpipe|wgpu|device)\b", re.I)


def _why(stderr: str, code: int) -> str:
    """The panic's own words: the line after the first ``panicked at`` (a Rust panic ends with a backtrace hint and
    the main thread's generic unwrap, not its cause), else the last line that isn't a ``note:``."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    for i, ln in enumerate(lines[:-1]):
        if "panicked at" in ln:
            return lines[i + 1][:300]
    lines = [ln for ln in lines if not ln.startswith("note:")]
    return lines[-1][:300] if lines else f"demucs-rs exited {code}"


def _of_its_device(stderr: str) -> str:
    """demucs-rs's own lines that bear on the device it ran on, for the log."""
    said = [ln.strip() for ln in stderr.splitlines() if _DEVICE_WORDS.search(ln)]
    return f"of its device it said: {' | '.join(said)}" if said else "it named no device"


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


class SeparatorFailed(Exception):
    """demucs-rs failed (exited nonzero, died by a signal before Done!) or wrote no vocal stem; the message carries its last stderr line."""


class Separator(Protocol):
    def vocals(self, audio: Path, workdir: Path, *, on_tick: Callable[[float], None] | None = None) -> Path: ...


class DemucsSeparator:
    """demucs-rs on a file. It reads its model only from ``$XDG_CACHE_HOME/demucs-rs/htdemucs.safetensors`` (and
    downloads it otherwise), so each run gets a private XDG_CACHE_HOME holding a symlink to the pinned model.

    burn's autotune cache (measured, demucs-rs 0.3.4) goes to ``$XDG_CONFIG_HOME/autotune/0.9.0/<device>/``: the
    GPU (wgpu) build writes it there, and a warm cache cut a 4 s clip from 70 s to 25 s; the cpu (ndarray) build
    writes none, so for it the setting is harmless. It is kept at ``cache_dir/demucs-rs`` between runs. Nothing
    lands in HOME or the working directory. The driver's own shader caches (``mesa_shader_cache``, ``nvidia``)
    go to XDG_CACHE_HOME and are lost with the work directory.

    The wgpu build, run from Python with its output captured (6 of 6 runs; from a plain shell it exits 0), finishes
    the separation and then dies by SIGSEGV in the driver's exit path; at times it says more after ``Done!``
    (``NVVM compilation failed: 3``) or glibc aborts it (``double free or corruption (out)``, SIGABRT), as measured
    on real songs. A death by a signal once ``Done!`` was said, with vocals.wav written, is therefore taken as a
    success and logged; a positive exit, a signal before ``Done!`` and a missing stem still fail."""

    def __init__(self, binary: str, model: Path, cache_dir: Path, timeout: float = TIMEOUT_S, tick: float = TICK_S):
        self.binary = binary
        self.model = model
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.tick = tick

    def vocals(self, audio: Path, workdir: Path, *, on_tick: Callable[[float], None] | None = None) -> Path:
        """The vocal stem of ``audio``, separated under ``workdir``; ``on_tick`` is told how long demucs-rs has run,
        in seconds, every ``tick`` while it runs."""
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
            done = self._run(cmd, env, on_tick)
        except subprocess.TimeoutExpired as e:
            raise SeparatorFailed(f"demucs-rs took longer than {self.timeout:g} s and was stopped") from e
        except OSError as e:
            raise SeparatorFailed(f"demucs-rs won't run: {e}") from e
        out = stems / "vocals.wav"
        if done.returncode != 0:
            said = [ln.strip() for ln in done.stderr.splitlines() if ln.strip()]
            if not (done.returncode < 0 and "Done!" in said and out.is_file()):
                raise SeparatorFailed(_why(done.stderr, done.returncode))
            log.warning("demucs-rs died by %s on its way out, after writing the vocals; taking them",
                        _signal_name(-done.returncode))
        if not out.is_file():
            raise SeparatorFailed(f"demucs-rs wrote no vocals.wav under {stems}")
        log.info("demucs-rs separated the vocals; %s", _of_its_device(done.stderr))
        return out

    def _run(self, cmd: list[str], env: dict[str, str],
             on_tick: Callable[[float], None] | None) -> subprocess.CompletedProcess[str]:
        """demucs-rs run to its end as ``subprocess.run`` runs it (its output captured as text, stopped past
        ``timeout``, killed on anything raised meanwhile, a Ctrl-C too), ``on_tick`` told every ``tick`` how long it
        has run."""
        started = time.monotonic()
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                errors="replace")
        try:
            while True:
                left = self.timeout - (time.monotonic() - started)
                try:
                    out, err = proc.communicate(timeout=max(0.0, min(self.tick, left) if on_tick else left))
                    break
                except subprocess.TimeoutExpired:
                    ran = time.monotonic() - started
                    if ran >= self.timeout:
                        raise
                    if on_tick is not None:
                        on_tick(ran)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def frame_db(path: Path, *, frame_s: float = FRAME_S, rate: int = 16000) -> list[float]:
    """The RMS loudness of each ``frame_s`` frame of the audio at ``path``, in dB, one value per frame. The file is
    read as BTC reads its own (audio.py ``load_mono``: libsndfile, else FFmpeg for the AAC of YouTube's .m4a and an
    MP3 libsndfile decodes only in part)."""
    from caracole.autochords.audio import load_librosa, load_mono

    samples = load_mono(path, rate)
    librosa = load_librosa()
    hop = max(1, round(frame_s * rate))
    rms = librosa.feature.rms(y=samples, frame_length=2 * hop, hop_length=hop)[0]
    return [float(v) for v in librosa.amplitude_to_db(rms, ref=1.0, amin=1e-5, top_db=None)]
