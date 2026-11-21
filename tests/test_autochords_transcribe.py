"""The Whisper transcriber's rules that need no model: which device, and whose fault an error is."""

import sys
import types

import pytest

from caracole.autochords import transcribe


def _fake_torch(monkeypatch, *, available: bool, allocates: bool):
    class OutOfMemoryError(RuntimeError):
        pass

    def zeros(n, device=None):
        if not allocates:
            raise RuntimeError("CUDA error: all CUDA-capable devices are busy or unavailable")
        return object()

    torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: available, OutOfMemoryError=OutOfMemoryError),
        zeros=zeros,
        float16="float16",
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    return torch


@pytest.mark.parametrize(
    ("available", "allocates", "want"),
    [(False, True, "cpu"), (True, False, "cpu"), (True, True, "cuda")],
)
def test_auto_is_cuda_when_torch_allocates_on_it_else_cpu(monkeypatch, available, allocates, want):
    _fake_torch(monkeypatch, available=available, allocates=allocates)
    assert transcribe.resolve_device("auto") == want


def test_cpu_and_cuda_are_taken_as_given(monkeypatch):
    _fake_torch(monkeypatch, available=False, allocates=False)
    assert transcribe.resolve_device("cpu") == "cpu"
    assert transcribe.resolve_device("cuda") == "cuda"


def test_out_of_memory_and_cuda_errors_are_the_setups(monkeypatch):
    torch = _fake_torch(monkeypatch, available=True, allocates=True)
    assert transcribe.is_setup_error(RuntimeError("CUDA error: out of memory"))
    assert transcribe.is_setup_error(RuntimeError("cuDNN error: CUDNN_STATUS_NOT_INITIALIZED"))
    assert transcribe.is_setup_error(RuntimeError("a device-side assert triggered"))
    assert transcribe.is_setup_error(torch.cuda.OutOfMemoryError("x"))
    assert not transcribe.is_setup_error(RuntimeError("Error opening x.m4a"))
    assert not transcribe.is_setup_error(ValueError("CUDA"))


def test_the_alignment_heads_are_large_v3s():
    whisper = pytest.importorskip("whisper")
    assert transcribe.ALIGNMENT_HEADS == whisper._ALIGNMENT_HEADS["large-v3"]


class _Mel:
    def to(self, *_a, **_k):
        return self


class _Model:
    def __init__(self, result=None, error=None):
        self.dims = types.SimpleNamespace(n_mels=128)
        self.device = "cpu"
        self.heads = None
        self.calls = []
        self._result, self._error = result, error

    def set_alignment_heads(self, heads):
        self.heads = heads

    def transcribe(self, audio, **kw):
        self.calls.append((audio, kw))
        if self._error:
            raise self._error
        return self._result


def _fake_whisper(monkeypatch, model=None, load_error=None):
    def load_model(path, device=None):
        if load_error:
            raise load_error
        return model

    whisper = types.SimpleNamespace(
        load_model=load_model,
        load_audio=lambda p: [0.0] * 16000 * 40,
        pad_or_trim=lambda a: a,
        log_mel_spectrogram=lambda clip, n: _Mel(),
        detect_language=lambda m, mel: (None, {"en": 0.1, "es": 0.9}),
    )
    monkeypatch.setitem(sys.modules, "whisper", whisper)


def _make(monkeypatch, tmp_path, device="cpu"):
    monkeypatch.setenv("TRITON_CACHE_DIR", str(tmp_path))
    return transcribe.WhisperTranscriber(tmp_path / "m.pt", device=device, cache_dir=tmp_path)


def test_a_cuda_load_failure_is_the_gpus(monkeypatch, tmp_path):
    _fake_torch(monkeypatch, available=True, allocates=True)
    _fake_whisper(monkeypatch, load_error=ValueError("bad file"))
    with pytest.raises(transcribe.SetupFailed, match=r"^the GPU failed: ValueError: bad file$"):
        _make(monkeypatch, tmp_path, "cuda")


def test_a_cpu_load_failure_is_the_models(monkeypatch, tmp_path):
    _fake_torch(monkeypatch, available=False, allocates=True)
    _fake_whisper(monkeypatch, load_error=ValueError("bad file"))
    with pytest.raises(transcribe.SetupFailed, match=r"^Whisper's model won't load: ValueError: bad file$"):
        _make(monkeypatch, tmp_path)


def test_a_cpu_load_failure_by_cuda_error_is_the_gpus(monkeypatch, tmp_path):
    _fake_torch(monkeypatch, available=False, allocates=True)
    _fake_whisper(monkeypatch, load_error=RuntimeError("CUDA error: x"))
    with pytest.raises(transcribe.SetupFailed, match=r"^the GPU failed: RuntimeError: CUDA error: x$"):
        _make(monkeypatch, tmp_path)


def test_the_alignment_heads_are_set_after_loading(monkeypatch, tmp_path):
    _fake_torch(monkeypatch, available=False, allocates=True)
    model = _Model()
    _fake_whisper(monkeypatch, model)
    _make(monkeypatch, tmp_path)
    assert model.heads == transcribe.ALIGNMENT_HEADS


def test_a_cuda_error_while_hearing_is_the_gpus(monkeypatch, tmp_path):
    _fake_torch(monkeypatch, available=True, allocates=True)
    _fake_whisper(monkeypatch, _Model(error=RuntimeError("CUDA error: out of memory")))
    with pytest.raises(transcribe.SetupFailed, match=r"^the GPU failed: RuntimeError: CUDA error: out of memory$"):
        _make(monkeypatch, tmp_path, "cuda").hear(tmp_path / "a", tmp_path / "b", 0.0)


@pytest.mark.parametrize("error", [RuntimeError("Failed to load audio: x"), ValueError("odd")])
def test_an_audio_error_while_hearing_is_not_the_setups(monkeypatch, tmp_path, error):
    _fake_torch(monkeypatch, available=False, allocates=True)
    _fake_whisper(monkeypatch, _Model(error=error))
    with pytest.raises(type(error)) as raised:
        _make(monkeypatch, tmp_path).hear(tmp_path / "a", tmp_path / "b", 0.0)
    assert raised.value is error


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_hearing_builds_words_and_calls_whisper_as_pinned(monkeypatch, tmp_path, device):
    from caracole.autochords.words import Word

    _fake_torch(monkeypatch, available=True, allocates=True)
    result = {
        "segments": [
            {"words": [
                {"start": 0.0, "end": 0.5, "word": " "},
                {"start": 0.5, "end": 1.0, "word": " Hola"},
                {"start": 1.0, "end": 1.5, "word": "mundo"},
            ]},
            {"words": [
                {"start": 2.0, "end": 2.2, "word": "\n"},
                {"start": 2.2, "end": 2.6, "word": " otra"},
                {"start": 2.6, "end": 3.0, "word": "vez"},
            ]},
        ]
    }
    model = _Model(result)
    _fake_whisper(monkeypatch, model)
    heard = _make(monkeypatch, tmp_path, device).hear(tmp_path / "mix", tmp_path / "stem", 5.0)
    assert heard.language == "es"
    assert heard.words == [
        Word(0.5, 1.0, "Hola", True, True),
        Word(1.0, 1.5, "mundo", False, False),
        Word(2.2, 2.6, "otra", True, True),
        Word(2.6, 3.0, "vez", False, False),
    ]
    (audio, kw), = model.calls
    assert audio == str(tmp_path / "mix")
    assert kw == dict(
        language="es", word_timestamps=True, condition_on_previous_text=False, beam_size=5, best_of=5,
        fp16=device == "cuda",
    )
