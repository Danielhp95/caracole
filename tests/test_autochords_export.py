"""export.py: BTC and beat_this as ONNX graphs, held to PyTorch's answers.

The tests marked ``autochords`` need torch, librosa, beat_this, onnx, ONNX Runtime and mir_eval, and the model files
(found as tests/test_autochords_models.py finds them): run them in `nix develop .#autochords`. The others run anywhere.
"""

from __future__ import annotations

import functools
import hashlib
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from caracole.autochords.export import BEATS_FP16_GRAPH, BEATS_GRAPH, BTC_GRAPH, BTC_WEIGHTS_NAME, pt_offsets

from conftest import subprocess_pythonpath
from helpers import legacy_pt
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
    mean = np.float32(session.get_modelmeta().custom_metadata_map["mean"])  # as the phone reads it
    assert mean == np.float32(recognizer.mean)

    def windows(raw: np.ndarray) -> np.ndarray:
        """Raw log-CQT frames in model windows, the last one filled out with the graph's mean: what btc.py's zeros
        are once normalized."""
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
def test_btc_graph_says_what_it_normalizes_with_and_whose_weights_it_reads(btc_export):
    import numpy as np
    import onnx

    from caracole.autochords.btc import _load_checkpoint

    out, _ = btc_export
    graph = onnx.load(str(out / BTC_GRAPH), load_external_data=False)
    checkpoint = _load_checkpoint(BTC_WEIGHTS)
    mean, std = np.float32(float(checkpoint["mean"])), np.float32(float(checkpoint["std"]))
    said = {entry.key: entry.value for entry in graph.metadata_props}
    assert said == {"mean": str(mean), "std": str(std), "weights_sha256": _sha256(BTC_WEIGHTS)}
    # Each reads back as the very float32 the graph normalizes with.
    assert (np.float32(said["mean"]), np.float32(said["std"])) == (mean, std)
    constants = [
        onnx.numpy_helper.to_array(node.attribute[0].t) for node in graph.graph.node if node.op_type == "Constant"
    ]
    assert any(c.dtype == np.float32 and c.shape == () and c == mean for c in constants)
    assert any(c.dtype == np.float32 and c.shape == () and c == std for c in constants)


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


# --- pt_offsets, on files written here ---------------------------------------------------------------------


def _write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "checkpoint.pt"
    path.write_bytes(data)
    return path


def test_pt_offsets_finds_each_tensors_bytes(tmp_path):
    good = legacy_pt.checkpoint()
    offsets = pt_offsets(_write(tmp_path, good.data))
    assert offsets == good.offsets
    assert [length for _, length in offsets.values()] == [24, 16, 8]
    assert offsets["c"][0] == offsets["a.weight"][0] + 16  # four elements into the storage it shares
    for name, (offset, length) in offsets.items():
        assert struct.unpack(f"<{length // 4}f", good.data[offset : offset + length]) == good.elements[name]


@pytest.mark.parametrize(
    "broken, why",
    [
        (dict(magic=1), "magic number"),
        (dict(protocol=1000), "magic number"),
        (dict(little_endian=False), "little-endian"),
        (dict(keys=["0"]), "storages aren't the ones its tensors name"),
        (dict(keys=["0", "1", "2"]), "storages aren't the ones its tensors name"),
        (dict(keys=["0", "0", "1"]), "storages aren't the ones its tensors name"),
        (dict(counts={"0": 5}), "isn't the size its tensors say"),
        (dict(after=b"\0"), "don't end where the file does"),
        (dict(tensors={"a": legacy_pt.Tensor("0", (2, 3), stride=(1, 2))}, storages={"0": 6}), "isn't contiguous"),
        (dict(tensors={"a": legacy_pt.Tensor("1", (4,), offset=2)}, storages={"1": 4}), "past its storage's end"),
        (dict(claimed={"1": 2**62}), "past the file's end"),
    ],
    ids=["magic", "protocol", "big-endian", "a key missing", "a key more", "a key twice", "a count", "a byte more",
         "strided", "outside its storage", "a storage of 2**62"],
)
def test_pt_offsets_refuses_a_checkpoint_that_isnt_as_its_format_says(tmp_path, broken, why):
    with pytest.raises(ValueError, match=f"legacy format: .*{why}"):
        pt_offsets(_write(tmp_path, legacy_pt.checkpoint(**broken).data))


@pytest.mark.parametrize(
    "end, why",
    [(-1, "past the file's end"), (-20, "past the file's end"), (300, ""), (30, "")],
    ids=["in its last storage", "in a storage's count", "in its pickles", "in its header"],
)
def test_pt_offsets_refuses_a_file_cut_short(tmp_path, end, why):
    with pytest.raises(ValueError, match=f"legacy format: .*({why})"):
        pt_offsets(_write(tmp_path, legacy_pt.checkpoint().data[:end]))


def test_pt_offsets_refuses_a_file_in_another_format(tmp_path):
    zipped = tmp_path / "zipped.pt"
    zipped.write_bytes(b"PK\x03\x04" + bytes(60))  # torch's default format since 1.6 is a zip
    with pytest.raises(ValueError, match="legacy format"):
        pt_offsets(zipped)


@pytest.mark.parametrize(
    "module, name", [("os", "system"), ("builtins", "eval"), ("torch", "HalfStorage")], ids=["os", "eval", "half"]
)
def test_pt_offsets_refuses_a_class_its_format_doesnt_need(tmp_path, module, name):
    # The phone will read a file fetched from the network: nothing in it but what BTC's checkpoint holds is unpickled.
    ran = tmp_path / "ran"
    evil = legacy_pt.HEADER + f"c{module}\n{name}\n(S'touch {ran}'\ntR.".encode()
    with pytest.raises(ValueError, match=f"{module}.{name}"):
        pt_offsets(_write(tmp_path, evil))
    assert not ran.exists()


def _stand_ins() -> list:
    """What pt_offsets' unpickler hands a file, and what each holds, to see that a file refused changed none."""
    from caracole.autochords import export

    return [(obj, dict(vars(obj)), getattr(obj, "__defaults__", None)) for obj in export._ALLOWED.values()]


SETTING = legacy_pt.text("offset") + legacy_pt.integer(-5)
BUILDS = {
    # A tensor's record changed after it was checked: its offset 20 bytes before its storage's data.
    "after a tensor": dict(tensor_build=b"}" + SETTING + b"sb"),
    "after a tensor, by slots": dict(tensor_build=b"(N}" + SETTING + b"stb"),
    "on a storage": dict(storage_build=b"}" + legacy_pt.text("key") + legacy_pt.text("1") + b"sb"),
    # A state dict takes its `_metadata` alone.
    "on a state dict": dict(tensor_build=legacy_pt.glob("collections", "OrderedDict") + b")R}" + SETTING + b"sb0"),
}


@pytest.mark.parametrize("build", BUILDS.values(), ids=BUILDS.keys())
def test_pt_offsets_refuses_state_set_on_a_record(tmp_path, build):
    before = _stand_ins()
    with pytest.raises(ValueError, match="legacy format: .*BUILD"):
        pt_offsets(_write(tmp_path, legacy_pt.checkpoint(**build).data))
    assert _stand_ins() == before


@pytest.mark.parametrize("state", [b"}" + SETTING + b"s", b"(N}" + SETTING + b"st"], ids=["dict", "slots"])
def test_pt_offsets_refuses_state_set_on_a_class_or_function_it_hands_out(tmp_path, state):
    # A refused file changes nothing the next file is read with.
    from caracole.autochords import export

    before = _stand_ins()
    for module, name in export._ALLOWED:
        evil = legacy_pt.HEADER + b"\x80\x02" + legacy_pt.glob(module, name) + state + b"b."
        with pytest.raises(ValueError, match="legacy format: .*BUILD"):
            pt_offsets(_write(tmp_path, evil))
    assert _stand_ins() == before
    good = legacy_pt.checkpoint()
    assert pt_offsets(_write(tmp_path, good.data)) == good.offsets


TOO_MUCH = {
    # A length claimed past the file's end is refused before anything that long is made.
    "a string of 2 GB": legacy_pt.HEADER + b"\x80\x02X" + struct.pack("<I", 2**31 - 1) + b"x" * 16,
    "bytes of 2**62": legacy_pt.HEADER + b"\x80\x03\x8e" + struct.pack("<Q", 2**62) + b"x" * 16,
    # Nested 200,000 deep: named by its type, never written out.
    "a deep persistent id": legacy_pt.HEADER + b"\x80\x02)" + b"\x85" * 200_000 + b"Q.",
    # Hashing a tuple nested that deep overflows CPython's C stack: no key but a text or a number.
    "a deep key": legacy_pt.HEADER + b"\x80\x02})" + b"\x85" * 200_000 + b"K\x01s.",
}


@pytest.mark.parametrize("data", TOO_MUCH.values(), ids=TOO_MUCH.keys())
def test_pt_offsets_refuses_what_would_exhaust_it_with_a_value_error(tmp_path, data):
    with pytest.raises(ValueError, match="legacy format"):
        pt_offsets(_write(tmp_path, data))


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


_PEAK = """
import sys
import numpy as np, onnxruntime as ort
options = ort.SessionOptions()
options.intra_op_num_threads = 4
options.enable_mem_pattern = False  # the app's settings (android/ml's OrtModels)
options.enable_cpu_mem_arena = False
session = ort.InferenceSession(sys.argv[1], options, providers=["CPUExecutionProvider"])
session.run(None, {"spect": np.random.default_rng(3).standard_normal((1, 1500, 128)).astype(np.float32)})
print(next(int(line.split()[1]) for line in open("/proc/self/status") if line.startswith("VmHWM:")) // 1024)
"""


def _peak_mb(path: Path) -> int:
    """A fresh process's peak RSS, in MB, as it runs a whole 1500-frame chunk through the graph at ``path``: its own
    memory's high-water mark (VmHWM), never ``ru_maxrss``, which a child keeps from the process it was forked from."""
    done = subprocess.run([sys.executable, "-c", _PEAK, str(path)], capture_output=True, text=True, check=True)
    return int(done.stdout.split()[-1])


@pytest.mark.autochords
def test_beat_this_attends_one_slice_at_a_time_and_answers_to_the_bit_as_the_whole_attention_does(
        beats_exports, tmp_path):
    import numpy as np
    import onnx
    from caracole.autochords.export import export_beats

    out, _ = beats_exports
    whole = tmp_path / "whole"
    for fp16, name in ((False, BEATS_GRAPH), (True, BEATS_FP16_GRAPH)):
        export_beats(BEAT_CHECKPOINT, whole, fp16=fp16, sliced=False)
        graph = onnx.load(str(out / name))
        scans = [n for n in graph.graph.node if n.op_type == "Scan"]
        # The frontend's three attentions over time (a slice a frequency band) and the six transformer blocks'
        # (a slice a head): every softmax over a [T, T] of scores.
        assert len(scans) == 9, name
        attending = {n.name for n in graph.graph.node if n.op_type == "Softmax"}
        assert not any("attnT" in n or "transformer_blocks" in n for n in attending), name
        sliced, entire = _session(out / name), _session(whole / name)
        rng = np.random.default_rng(11)
        for frames in (1500, 437, 6):
            spect = (rng.standard_normal((1, frames, 128)) * 1.5 + 2.0).astype(np.float32)
            for got, want in zip(sliced.run(None, {"spect": spect}), entire.run(None, {"spect": spect}), strict=True):
                assert np.array_equal(got, want), (name, frames)
        # A whole chunk's scores and their softmax, two [32, 1, 1500, 1500] float32s at once: 576 MB of the peak.
        assert _peak_mb(out / name) <= _peak_mb(whole / name) - 300, name


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
