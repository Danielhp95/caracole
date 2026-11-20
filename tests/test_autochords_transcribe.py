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
