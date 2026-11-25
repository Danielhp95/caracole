"""export.py: BTC and beat_this as ONNX graphs, held to PyTorch's answers.

The tests marked ``autochords`` need torch, librosa, beat_this, onnx, ONNX Runtime and mir_eval, and the model files
(found as tests/test_autochords_models.py finds them): run them in `nix develop .#autochords`. The others run anywhere.
"""

from __future__ import annotations

import functools
import hashlib
import os
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

from caracole.autochords.export import BEATS_FP16_GRAPH, BEATS_GRAPH, BTC_GRAPH, BTC_WEIGHTS_NAME, pt_offsets

from conftest import subprocess_pythonpath
from test_autochords_models import BEAT_CHECKPOINT, BTC_WEIGHTS, _drums, _imports, _installed

LIBS = ("numpy", "soundfile", "torch", "librosa", "beat_this", "onnx", "onnxruntime", "mir_eval")
HAVE_LIBS = _installed(*LIBS)


@functools.cache
def libs_load() -> bool:
    return HAVE_LIBS and _imports(*LIBS)


@pytest.fixture(scope="module")
def _models():
    if not HAVE_LIBS or BTC_WEIGHTS is None or BEAT_CHECKPOINT is None:
        pytest.skip("needs torch, librosa, beat_this, onnx, onnxruntime, mir_eval and both model files")
    if not libs_load():
        pytest.skip("torch, beat_this, onnx or onnxruntime won't load")


@pytest.fixture(scope="module")
def btc_export(_models, tmp_path_factory):
    from caracole.autochords.export import export_btc

    out = tmp_path_factory.mktemp("btc")
    return out, export_btc(BTC_WEIGHTS, out)


@pytest.fixture(scope="module")
def beats_exports(_models, tmp_path_factory):
    from caracole.autochords.export import export_beats

    out = tmp_path_factory.mktemp("beats")
    return out, {fp16: export_beats(BEAT_CHECKPOINT, out, fp16=fp16) for fp16 in (False, True)}


def _session(path: Path):
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- BTC ---------------------------------------------------------------------------------------


@pytest.mark.autochords
def test_btc_onnx_gives_torchs_logits(btc_export, tmp_path):
    import numpy as np
    import torch

    from caracole.autochords.btc import N_BINS, TIMESTEP, BTCRecognizer, cqt_features, load_audio
    from caracole.autochords.run import _write_tone

    out, exported = btc_export
    assert exported.files == (out / BTC_GRAPH, out / BTC_WEIGHTS_NAME)
    session = _session(out / BTC_GRAPH)
    (given,), (gives,) = session.get_inputs(), session.get_outputs()
    assert (given.name, given.type, given.shape) == ("features", "tensor(float)", ["N", TIMESTEP, N_BINS])
    assert (gives.name, gives.type, gives.shape) == ("logits", "tensor(float)", ["N", TIMESTEP, 170])

    recognizer = BTCRecognizer(BTC_WEIGHTS)
    mean = np.float32(recognizer.mean)

    def windows(raw: np.ndarray) -> np.ndarray:
        """Raw log-CQT frames in model windows, the last one filled out with the checkpoint's mean: what btc.py's
        zeros are once normalized."""
        return np.pad(raw, ((0, -len(raw) % TIMESTEP), (0, 0)), constant_values=mean).reshape(-1, TIMESTEP, N_BINS)

    def torchs(raw: np.ndarray) -> np.ndarray:
        """BTCRecognizer's logits, normalized and padded as btc.py does it."""
        normalized = (raw - recognizer.mean) / recognizer.std
        padded = np.pad(normalized, ((0, -len(raw) % TIMESTEP), (0, 0)))
        with torch.inference_mode():
            return recognizer.model(torch.tensor(padded).view(-1, TIMESTEP, N_BINS)).numpy()

    seeded = (np.random.default_rng(7).standard_normal((4 * TIMESTEP, N_BINS)) * recognizer.std + mean)
    tone = cqt_features(load_audio(_write_tone(tmp_path / "test-tone.wav")))
    for raw in (seeded.astype(np.float32), tone):
        assert raw.dtype == np.float32
        (logits,) = session.run(None, {"features": windows(raw)})
        expected = torchs(raw)
        assert logits.shape == expected.shape
        assert np.abs(logits - expected).max() <= 1e-4
        assert (logits.argmax(-1) == expected.argmax(-1)).all()


@pytest.mark.autochords
def test_every_external_initializer_is_the_authors_bytes_at_its_offset(btc_export):
    import onnx
    from onnx import TensorProto

    from caracole.autochords.btc import _load_checkpoint

    out, exported = btc_export
    graph = onnx.load(str(out / BTC_GRAPH), load_external_data=False)
    state = {k: v for k, v in _load_checkpoint(BTC_WEIGHTS)["model"].items() if not k.startswith("output_layer.lstm.")}
    assert sorted(i.name for i in graph.graph.initializer) == sorted(state)
    assert exported.initializers == len(state) == 213

    authors = BTC_WEIGHTS.read_bytes()
    offsets = pt_offsets(BTC_WEIGHTS)
    for initializer in graph.graph.initializer:
        assert initializer.data_location == TensorProto.EXTERNAL and not initializer.raw_data
        where = {entry.key: entry.value for entry in initializer.external_data}
        offset, length = int(where["offset"]), int(where["length"])
        assert where == {"location": BTC_WEIGHTS_NAME, "offset": str(offset), "length": str(length)}
        assert offsets[initializer.name] == (offset, length)
        tensor = state[initializer.name]
        assert list(initializer.dims) == list(tensor.shape) and initializer.data_type == TensorProto.FLOAT
        assert authors[offset : offset + length] == tensor.numpy().astype("<f4").tobytes()

    # The weights beside the graph are the authors' file, unchanged.
    assert exported.sha256[BTC_WEIGHTS_NAME] == _sha256(out / BTC_WEIGHTS_NAME) == _sha256(BTC_WEIGHTS)
    assert exported.sha256[BTC_GRAPH] == _sha256(out / BTC_GRAPH)


def _legacy_header() -> bytes:
    """The first three pickles of a checkpoint in torch's legacy format."""
    info = {"protocol_version": 1001, "little_endian": True, "type_sizes": {"short": 2, "int": 4, "long": 4}}
    return b"".join(pickle.dumps(value, protocol=2) for value in (0x1950A86A20F9469CFC6C, 1001, info))


@pytest.mark.parametrize(
    "module, name", [("os", "system"), ("builtins", "eval"), ("torch", "HalfStorage")], ids=["os", "eval", "half"]
)
def test_pt_offsets_refuses_a_class_its_format_doesnt_need(tmp_path, module, name):
    # The phone will read a file fetched from the network: nothing in it but what BTC's checkpoint holds is unpickled.
    ran = tmp_path / "ran"
    path = tmp_path / "evil.pt"
    path.write_bytes(_legacy_header() + f"c{module}\n{name}\n(S'touch {ran}'\ntR.".encode())
    with pytest.raises(ValueError, match=f"{module}.{name}"):
        pt_offsets(path)
    assert not ran.exists()


def test_pt_offsets_refuses_a_file_in_another_format(tmp_path):
    zipped = tmp_path / "zipped.pt"
    zipped.write_bytes(b"PK\x03\x04" + bytes(60))  # torch's default format since 1.6 is a zip
    with pytest.raises(ValueError, match="legacy format"):
        pt_offsets(zipped)


# --- beat_this ---------------------------------------------------------------------------------


@pytest.mark.autochords
def test_beats_onnx_gives_torchs_logits(beats_exports, tmp_path):
    import mir_eval
    import numpy as np
    import soundfile as sf
    import torch
    from beat_this.inference import load_model
    from beat_this.model.postprocessor import Postprocessor
    from beat_this.preprocessing import LogMelSpect

    out, exported = beats_exports
    assert (exported[False].files, exported[True].files) == ((out / BEATS_GRAPH,), (out / BEATS_FP16_GRAPH,))
    fp32, fp16 = _session(out / BEATS_GRAPH), _session(out / BEATS_FP16_GRAPH)
    for session in (fp32, fp16):
        assert [(i.name, i.type, i.shape) for i in session.get_inputs()] == [("spect", "tensor(float)", [1, "T", 128])]
        assert [(o.name, o.shape) for o in session.get_outputs()] == [("beat", [1, "T"]), ("downbeat", [1, "T"])]
    model = load_model(str(BEAT_CHECKPOINT), "cpu")

    def torchs(spect: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        with torch.inference_mode():
            out = model(torch.tensor(spect))
        return out["beat"].numpy(), out["downbeat"].numpy()

    def furthest(session, spect: np.ndarray) -> float:
        got, expected = session.run(None, {"spect": spect}), torchs(spect)
        return max(float(np.abs(g - e).max()) for g, e in zip(got, expected, strict=True))

    rng = np.random.default_rng(7)
    for frames in (1500, 437):  # a whole chunk, and a piece shorter than one
        spect = (rng.standard_normal((1, frames, 128)) * 1.5 + 2.0).astype(np.float32)
        assert furthest(fp32, spect) <= 1e-4
        assert furthest(fp16, spect) <= 1e-2

    samples, rate = sf.read(_drums(tmp_path / "drums.wav", seconds=24.0), dtype="float32")
    assert rate == 22050
    music = LogMelSpect()(torch.tensor(samples)).numpy()[None]
    assert furthest(fp32, music) <= 1e-4
    # On music the float16 weights move logits of ±13 by up to about 0.3, so there it is held by the beats they give.
    peaks = Postprocessor()
    reference = peaks(*(torch.tensor(x[0]) for x in torchs(music)))
    estimated = peaks(*(torch.tensor(x[0]) for x in fp16.run(None, {"spect": music})))
    for expected, got in zip(reference, estimated, strict=True):  # beats, then downbeats
        # mir_eval's rules, as its evaluate() keeps them: the first 5 s left out, a hit within 70 ms.
        expected, got = (mir_eval.beat.trim_beats(np.asarray(times)) for times in (expected, got))
        assert len(expected) >= 8
        assert mir_eval.beat.f_measure(expected, got) >= 0.99


# --- both --------------------------------------------------------------------------------------


@pytest.mark.autochords
def test_an_export_is_the_same_bytes_twice(btc_export, beats_exports, tmp_path):
    from caracole.autochords.export import export_beats, export_btc

    first = {**btc_export[1].sha256, **beats_exports[1][False].sha256, **beats_exports[1][True].sha256}
    again = {
        **export_btc(BTC_WEIGHTS, tmp_path).sha256,
        **export_beats(BEAT_CHECKPOINT, tmp_path, fp16=False).sha256,
        **export_beats(BEAT_CHECKPOINT, tmp_path, fp16=True).sha256,
    }
    assert again == first
    assert sorted(first) == sorted([BTC_GRAPH, BTC_WEIGHTS_NAME, BEATS_GRAPH, BEATS_FP16_GRAPH])
    assert {name: _sha256(tmp_path / name) for name in again} == again


@pytest.mark.slow
def test_registering_the_commands_imports_no_onnx(tmp_path):
    # Every command module is imported on every start, and only the auto-chords environment has torch and onnx.
    code = (
        "import sys\n"
        "from caracole.cli import build_app\n"
        "build_app()\n"
        "print([m for m in ('onnx', 'onnxruntime', 'torch', 'beat_this', 'caracole.autochords.export')"
        " if m in sys.modules])\n"
    )
    src = Path(__file__).resolve().parents[1] / "src"
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": subprocess_pythonpath(src)}
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "[]"
