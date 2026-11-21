"""Whisper large-v3 hears a song: its words, timed, in the language sung.

Whisper hears the full mix (it does worse on a separated stem); the vocal stem only serves to detect the
language, on the first 30 s of singing. torch and whisper load inside functions: ``caracole --help`` never
pays for them.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from caracole.autochords.words import Word

# openai-whisper's _ALIGNMENT_HEADS["large-v3"], copied: ``load_model(<path>)`` leaves the alignment heads
# unset (only ``load_model("large-v3")`` sets them), and word timestamps need them.
ALIGNMENT_HEADS = b"ABzY8gWO1E0{>%R7(9S+Kn!D~%ngiGaR?*L!iJG9p-nab0JQ=-{D1-g00"

SAMPLE_RATE = 16000  # whisper.audio.SAMPLE_RATE
DETECT_S = 30.0  # the stretch of singing the language is heard on


@dataclass(frozen=True)
class Heard:
    language: str
    words: list[Word]


class Transcriber(Protocol):
    def hear(self, mix: Path, stem: Path, first_sung_s: float) -> Heard: ...


class SetupFailed(Exception):
    """The setup's failure (a GPU that is missing, busy or out of memory; a model that won't load), never
    the audio's: the song stays offered."""


def resolve_device(setting: str) -> str:
    """``cpu`` and ``cuda`` as given; ``auto`` is ``cuda`` when torch can allocate on it, else ``cpu``."""
    if setting != "auto":
        return setting
    import torch

    try:
        if torch.cuda.is_available():
            torch.zeros(1, device="cuda")
            return "cuda"
    except Exception:  # noqa: BLE001 - a GPU that is busy, out of memory or half-working is no GPU here
        pass
    return "cpu"


def is_setup_error(e: BaseException) -> bool:
    """Out of GPU memory, or a CUDA, cuDNN or device-side failure: the setup's, not the audio's."""
    import torch

    if isinstance(e, torch.cuda.OutOfMemoryError):
        return True
    return isinstance(e, RuntimeError) and any(s in str(e) for s in ("CUDA", "cuDNN", "device-side"))


AUDIO_ERROR = "Failed to load audio: "  # how openai-whisper's load_audio says ffmpeg couldn't read a file


def is_audio_error(e: BaseException) -> bool:
    """Whisper couldn't read the audio: openai-whisper's ``load_audio`` raises ``RuntimeError("Failed to load audio:
    <ffmpeg's stderr>")``. Anything else it raises is no fault of the audio's."""
    return isinstance(e, RuntimeError) and str(e).startswith(AUDIO_ERROR)


class WhisperTranscriber:
    def __init__(self, model_path: Path, *, device: str, cache_dir: Path):
        # Triton compiles into a cache, and fails without a writable one (the service's HOME is read-only).
        os.environ.setdefault("TRITON_CACHE_DIR", str(cache_dir / "triton"))
        import whisper

        self.device = device
        try:
            self.model = whisper.load_model(str(model_path), device=device)
        except Exception as e:  # noqa: BLE001 - classified below
            if device == "cuda" or is_setup_error(e):
                raise SetupFailed(f"the GPU failed: {type(e).__name__}: {e}") from e
            raise SetupFailed(f"Whisper's model won't load: {type(e).__name__}: {e}") from e
        self.model.set_alignment_heads(ALIGNMENT_HEADS)

    def hear(self, mix: Path, stem: Path, first_sung_s: float) -> Heard:
        try:
            language = self._language(stem, first_sung_s)
            result = self.model.transcribe(
                str(mix),
                language=language,
                word_timestamps=True,
                condition_on_previous_text=False,
                beam_size=5,
                best_of=5,
                fp16=self.device == "cuda",
            )
        except Exception as e:  # noqa: BLE001 - only the setup's errors are told apart
            if is_setup_error(e):
                raise SetupFailed(f"the GPU failed: {type(e).__name__}: {e}") from e
            raise
        words = []
        for segment in result["segments"]:
            first = True
            for w in segment.get("words", []):
                text = w["word"].strip()
                if not text:
                    continue
                words.append(Word(w["start"], w["end"], text, w["word"][:1].isspace(), first))
                first = False
        return Heard(language, words)

    def _language(self, stem: Path, first_sung_s: float) -> str:
        import torch
        import whisper

        audio = whisper.load_audio(str(stem))
        start = round(max(first_sung_s, 0.0) * SAMPLE_RATE)
        clip = whisper.pad_or_trim(audio[start : start + round(DETECT_S * SAMPLE_RATE)])
        mel = whisper.log_mel_spectrogram(clip, self.model.dims.n_mels).to(self.model.device)
        if self.device == "cuda":
            mel = mel.to(torch.float16)
        _, probs = whisper.detect_language(self.model, mel)
        return max(probs, key=probs.get)
