"""The Whisper transcriber's rules that need no model: which device, and whose fault an error is."""

import logging
import os
import sys
import types
import warnings

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
    def __init__(self, result=None, error=None, warns=()):
        self.dims = types.SimpleNamespace(n_mels=128)
        self.device = "cpu"
        self.heads = None
        self.calls = []
        self._result, self._error, self._warns = result, error, warns

    def set_alignment_heads(self, heads):
        self.heads = heads

    def transcribe(self, audio, **kw):
        self.calls.append((audio, kw))
        for message in self._warns:
            warnings.warn(message, stacklevel=1)
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


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_a_load_failure_is_the_models_on_either_device(monkeypatch, tmp_path, device):
    # A corrupt model file fails to load on the GPU as on the CPU: it is no fault of the GPU's.
    _fake_torch(monkeypatch, available=device == "cuda", allocates=True)
    _fake_whisper(monkeypatch, load_error=RuntimeError("PytorchStreamReader failed reading zip archive"))
    with pytest.raises(transcribe.SetupFailed, match=r"^Whisper's model won't load: RuntimeError: PytorchStreamReader "
                                                     r"failed reading zip archive$"):
        _make(monkeypatch, tmp_path, device)


@pytest.mark.parametrize("device", ["cpu", "cuda"])
@pytest.mark.parametrize("error", [RuntimeError("CUDA error: x"), "OutOfMemoryError"])
def test_a_cuda_error_at_load_is_the_gpus_on_either_device(monkeypatch, tmp_path, device, error):
    torch = _fake_torch(monkeypatch, available=device == "cuda", allocates=True)
    error = torch.cuda.OutOfMemoryError("CUDA out of memory") if error == "OutOfMemoryError" else error
    _fake_whisper(monkeypatch, load_error=error)
    with pytest.raises(transcribe.SetupFailed, match=rf"^the GPU failed: {type(error).__name__}: CUDA "):
        _make(monkeypatch, tmp_path, device)


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


def test_a_stem_whisper_cant_load_is_the_separators_never_the_songs(monkeypatch, tmp_path):
    # Whisper reads the stem first, for the language: a stem it can't load (or one gone from the cache) is no proof
    # the song's audio is bad, so it is the setup's, said as the separator's, and the song stays offered.
    _fake_torch(monkeypatch, available=False, allocates=True)
    model = _Model({"segments": []})
    _fake_whisper(monkeypatch, model)
    stem = tmp_path / "vocals.wav"

    def load_audio(path):
        if path == str(stem):
            raise RuntimeError("Failed to load audio: Error opening input files: No such file or directory")
        return [0.0] * 16000 * 40

    sys.modules["whisper"].load_audio = load_audio
    with pytest.raises(transcribe.SetupFailed, match=r"^the separator can't run here \(its vocals can't be read: "
                                                     r"RuntimeError: Failed to load audio: Error opening input files: "
                                                     r"No such file or directory\)$"):
        _make(monkeypatch, tmp_path).hear(tmp_path / "mix", stem, 0.0)
    assert model.calls == []  # the mix never heard


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


class _Bar:
    """openai-whisper's transcribe(): its progress bar over the mix's mel frames (10 ms each), moved a window at a
    time, as whisper/transcribe.py moves its ``tqdm.tqdm``, read through the module's own ``tqdm`` name."""

    def __init__(self, frames, windows):
        self.frames, self.windows = frames, windows

    def transcribe(self, audio, **kw):
        bars = sys.modules["whisper.transcribe"].tqdm
        with bars.tqdm(total=self.frames, unit="frames", disable=kw.get("verbose") is not False) as pbar:
            for n in self.windows:
                pbar.update(n)
        return {"segments": []}


def test_whispers_progress_through_the_mix_is_told_as_it_hears(monkeypatch, tmp_path):
    # Whisper hears a song window by window, minutes on a CPU: its own progress bar (whisper.transcribe's tqdm, which
    # it shows only with verbose=False) is read as it moves, in seconds of the mix heard, and given back as it was.
    _fake_torch(monkeypatch, available=False, allocates=True)
    model = _Model()
    model.transcribe = _Bar(22500, [3000, 3000, 16500]).transcribe  # 3 min 45 s, two windows, then the rest
    _fake_whisper(monkeypatch, model)
    drawn = []

    class Own:
        def __init__(self, **kw):
            drawn.append(kw)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def update(self, n):
            pass

    real = types.SimpleNamespace(tqdm=Own)
    monkeypatch.setitem(sys.modules, "whisper.transcribe", types.SimpleNamespace(tqdm=real))
    heard = []
    t = _make(monkeypatch, tmp_path)
    t.hear(tmp_path / "mix", tmp_path / "stem", 0.0, on_progress=lambda done, total: heard.append((done, total)))
    assert heard == [(30.0, 225.0), (60.0, 225.0), (225.0, 225.0)]
    assert drawn == [] and sys.modules["whisper.transcribe"].tqdm is real  # never drawn, and put back
    t.hear(tmp_path / "mix", tmp_path / "stem", 0.0)  # with none asked, Whisper's own bar, hidden as ever
    assert drawn == [{"total": 22500, "unit": "frames", "disable": True}]


def test_whispers_progress_hook_is_its_versions_own():
    # The hook reads whisper.transcribe's module-level tqdm, which its transcribe() draws its bar with, over the mel
    # frames of 10 ms: a Whisper that draws it otherwise fails here, never in a job.
    import inspect

    pytest.importorskip("whisper")
    module = sys.modules["whisper.transcribe"]
    from whisper.audio import HOP_LENGTH, SAMPLE_RATE
    from whisper.model import Whisper

    assert Whisper.transcribe.__globals__ is vars(module)
    assert "with tqdm.tqdm(\n        total=content_frames" in inspect.getsource(module)
    assert "pbar.update(" in inspect.getsource(module)
    assert HOP_LENGTH / SAMPLE_RATE == transcribe.WHISPER_FRAME_S


@pytest.mark.parametrize(("error", "audio"), [
    (RuntimeError("Failed to load audio: song.m4a: Invalid data found when processing input"), True),
    (RuntimeError("expected scalar type Half but found Float"), False),
    (IndexError("list index out of range"), False),
    (ValueError("Failed to load audio: not whisper's own"), False),
])
def test_only_whisper_failing_to_load_the_audio_is_the_audios(error, audio):
    assert transcribe.is_audio_error(error) is audio


@pytest.mark.slow
def test_whispers_own_error_for_a_file_it_cant_load_is_the_audios(tmp_path):
    whisper_audio = pytest.importorskip("whisper.audio")  # runs its ffmpeg on a file that is no audio
    bad = tmp_path / "song.m4a"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(Exception) as caught:
        whisper_audio.load_audio(str(bad))
    assert transcribe.is_audio_error(caught.value)


def _no_library_path(monkeypatch):
    """LIBRARY_PATH unset for the test, and as it was after it (setenv records it, delenv clears it)."""
    monkeypatch.setenv("LIBRARY_PATH", "")
    monkeypatch.delenv("LIBRARY_PATH")


def test_triton_links_the_drivers_libcuda_where_nixos_has_one(monkeypatch, tmp_path):
    # nixpkgs' Triton gives its launcher's linker no libcuda folder: gcc finds it by LIBRARY_PATH.
    driver = tmp_path / "opengl-driver" / "lib"
    driver.mkdir(parents=True)
    (driver / "libcuda.so.1").write_bytes(b"")
    monkeypatch.setattr(transcribe, "DRIVER_LIBS", driver)
    _no_library_path(monkeypatch)
    _fake_torch(monkeypatch, available=False, allocates=True)
    _fake_whisper(monkeypatch, _Model())
    _make(monkeypatch, tmp_path)
    assert os.environ["LIBRARY_PATH"] == str(driver)


def test_triton_is_left_alone_without_the_drivers_libcuda_or_with_a_library_path(monkeypatch, tmp_path):
    monkeypatch.setattr(transcribe, "DRIVER_LIBS", tmp_path / "none")
    _no_library_path(monkeypatch)
    _fake_torch(monkeypatch, available=False, allocates=True)
    _fake_whisper(monkeypatch, _Model())
    _make(monkeypatch, tmp_path)
    assert "LIBRARY_PATH" not in os.environ
    driver = tmp_path / "lib"
    driver.mkdir()
    (driver / "libcuda.so.1").write_bytes(b"")
    monkeypatch.setattr(transcribe, "DRIVER_LIBS", driver)
    monkeypatch.setenv("LIBRARY_PATH", "/elsewhere")
    _make(monkeypatch, tmp_path)
    assert os.environ["LIBRARY_PATH"] == "/elsewhere"


# openai-whisper's own, from whisper/timing.py: each 30 s window, where Triton can't build its kernels.
TRITON = ("Failed to launch Triton kernels, likely due to missing CUDA toolkit; falling back to a slower median "
          "kernel implementation...",
          "Failed to launch Triton kernels, likely due to missing CUDA toolkit; falling back to a slower DTW "
          "implementation...")


def test_whispers_triton_fallback_is_said_once_at_info_and_its_warnings_are_kept_back(monkeypatch, tmp_path, caplog):
    # caracole-web's unit has no C compiler: Triton can't build its word-timing kernels, and Whisper would warn twice
    # a window into the request's Output. Its other warnings pass as they are.
    _fake_torch(monkeypatch, available=True, allocates=True)
    _fake_whisper(monkeypatch, _Model({"segments": []}, warns=[*TRITON * 6, "something else"]))
    t = _make(monkeypatch, tmp_path, "cuda")
    with caplog.at_level(logging.INFO, logger="caracole.autochords.transcribe"):
        with warnings.catch_warnings(record=True) as shown:
            warnings.simplefilter("always")
            t.hear(tmp_path / "mix", tmp_path / "stem", 0.0)
            t.hear(tmp_path / "mix", tmp_path / "stem", 0.0)
    assert [str(w.message) for w in shown] == ["something else", "something else"]
    said = [r for r in caplog.records if "Triton" in r.getMessage()]
    assert len(said) == 1 and said[0].levelno == logging.INFO
    assert "slower" in said[0].getMessage()


def test_whispers_warnings_are_said_when_it_fails_too(monkeypatch, tmp_path):
    _fake_torch(monkeypatch, available=True, allocates=True)
    _fake_whisper(monkeypatch, _Model(error=ValueError("odd"), warns=[TRITON[0], "something else"]))
    t = _make(monkeypatch, tmp_path, "cuda")
    with warnings.catch_warnings(record=True) as shown:
        warnings.simplefilter("always")
        with pytest.raises(ValueError, match="odd"):
            t.hear(tmp_path / "mix", tmp_path / "stem", 0.0)
    assert [str(w.message) for w in shown] == ["something else"]
