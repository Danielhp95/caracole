"""BTC and beat_this as ONNX graphs, for chords and beats worked out on the phone.

The phone runs the computer's two models on ONNX Runtime. This module writes their graphs, and
tests/test_autochords_export.py holds each one to PyTorch's answers. ``CONTRACT`` is what a graph takes and gives:
a change to either is a new contract.

- ``export_btc`` writes ``btc-graph.onnx`` (opset 17), BTC (btc_model.py) over raw log-CQT frames, ``features:
  float32[N, 108, 144]``, giving ``logits: float32[N, 108, 170]``. The graph normalizes the frames itself by the
  checkpoint's mean and standard deviation, in float32 as btc.py does: a window's frames past the audio's end are
  the checkpoint's mean, which normalize to btc.py's zeros. Its layer norms' unbiased standard deviation is written
  out (the sum of squares over n − 1), and nothing is folded, so the graph holds no weight of its own: every tensor
  of the checkpoint's state dict is an external initializer at its offset in the authors' own
  ``btc_model_large_voca.pt``, which is copied beside it unchanged. BTC's weights are never re-hosted.
- ``export_beats`` writes beat_this's final0 checkpoint over its log-mel frames, ``spect: float32[1, T, 128]``,
  giving the ``beat`` and ``downbeat`` logits, ``float32[1, T]``. With ``fp16``, its weights are stored as float16
  and cast to float32 as the graph loads, so it computes in float32.
- ``pt_offsets`` finds where each tensor of a checkpoint in torch's legacy format lies in the file, which is a
  pickle and then each storage's raw bytes. It reads the pickle with a strict unpickler of the standard library,
  which builds nothing but the few classes that format needs and imports no torch: the phone will fetch such a file.

torch, onnx and beat_this are imported inside the functions, as only the auto-chords environment has them.
"""

from __future__ import annotations

import collections
import hashlib
import io
import os
import pickle
import shutil
import struct
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import onnx

CONTRACT = 1
OPSET = 17
BTC_GRAPH = "btc-graph.onnx"
BTC_WEIGHTS_NAME = "btc_model_large_voca.pt"  # the authors' file, as the graph names it
BEATS_GRAPH = "beat_this-final0.onnx"
BEATS_FP16_GRAPH = "beat_this-final0-fp16.onnx"
BEATS_CHUNK = 1500  # beat_this's frames a chunk (inference.py's Spect2Frames): the frames the graph is traced on


@dataclass(frozen=True)
class Exported:
    """What an export wrote: its files, each one's SHA-256 by its name, and how many initializers its graph has."""

    files: tuple[Path, ...]
    sha256: dict[str, str]
    initializers: int


def export_btc(weights: Path, out: Path) -> Exported:
    """``btc-graph.onnx`` in ``out``, beside a copy of ``weights`` (``btc_model_large_voca.pt``) its tensors point
    into. ValueError when the graph's initializers aren't the checkpoint's tensors, byte for byte."""
    import torch
    from onnx import TensorProto

    from caracole.autochords.btc import N_BINS, TIMESTEP, _load_checkpoint

    weights, out = Path(weights), Path(out)
    if not weights.is_file():
        raise FileNotFoundError(f"BTC weights not found: {weights}")
    offsets = pt_offsets(weights)
    checkpoint = _load_checkpoint(weights)
    state = {k: v for k, v in checkpoint["model"].items() if not k.startswith("output_layer.lstm.")}
    model = _btc_for_export(state, float(checkpoint["mean"]), float(checkpoint["std"]))
    graph = _traced(
        model,
        torch.zeros(1, TIMESTEP, N_BINS),
        inputs=["features"],
        outputs=["logits"],
        dynamic={"features": {0: "N"}, "logits": {0: "N"}},
        folding=False,
    )
    authors = weights.read_bytes()
    for initializer in graph.graph.initializer:
        name = initializer.name
        if name not in state:
            raise ValueError(f"BTC's graph has an initializer that isn't the checkpoint's: {name}")
        offset, length = offsets[name]
        if (initializer.data_type != TensorProto.FLOAT or list(initializer.dims) != list(state[name].shape)
                or initializer.raw_data != authors[offset : offset + length]):
            raise ValueError(f"BTC's graph holds {name} otherwise than its authors' file does")
        initializer.ClearField("raw_data")
        initializer.data_location = TensorProto.EXTERNAL
        for key, value in (("location", BTC_WEIGHTS_NAME), ("offset", str(offset)), ("length", str(length))):
            entry = initializer.external_data.add()
            entry.key, entry.value = key, value
    if len(graph.graph.initializer) != len(state):
        raise ValueError("BTC's graph doesn't take every tensor of the checkpoint")
    out.mkdir(parents=True, exist_ok=True)
    copy = out / BTC_WEIGHTS_NAME
    if not (copy.exists() and copy.samefile(weights)):
        shutil.copyfile(weights, copy)
    path = _write(graph, out / BTC_GRAPH)
    return _exported((path, copy), len(graph.graph.initializer))


def export_beats(checkpoint: Path, out: Path, *, fp16: bool) -> Exported:
    """beat_this's final0 checkpoint as ``beat_this-final0.onnx`` in ``out``, or with ``fp16`` as
    ``beat_this-final0-fp16.onnx``, its weights stored as float16."""
    import torch
    from beat_this.inference import load_model

    checkpoint, out = Path(checkpoint), Path(out)
    if not checkpoint.is_file():  # beat_this would fetch a checkpoint it can't find from JKU's servers
        raise FileNotFoundError(f"beat_this checkpoint not found: {checkpoint}")

    class Logits(torch.nn.Module):
        """beat_this's model, its two outputs a tuple rather than a dict."""

        def __init__(self, model: torch.nn.Module):
            super().__init__()
            self.model = model

        def forward(self, spect: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            heads = self.model(spect)
            return heads["beat"], heads["downbeat"]

    graph = _traced(
        Logits(load_model(str(checkpoint), "cpu")).eval(),
        torch.zeros(1, BEATS_CHUNK, 128),
        inputs=["spect"],
        outputs=["beat", "downbeat"],
        dynamic={"spect": {1: "T"}, "beat": {1: "T"}, "downbeat": {1: "T"}},
        folding=True,
    )
    for output in graph.graph.output:  # one piece at a time, as the input says: the exporter can't tell
        output.type.tensor_type.shape.dim[0].dim_value = 1
    if fp16:
        _store_as_float16(graph)
    out.mkdir(parents=True, exist_ok=True)
    path = _write(graph, out / (BEATS_FP16_GRAPH if fp16 else BEATS_GRAPH))
    return _exported((path,), len(graph.graph.initializer))


def _btc_for_export(state: dict, mean: float, std: float):
    """BTC with the checkpoint's tensors, which normalizes raw log-CQT frames itself and writes its layer norms'
    unbiased standard deviation out."""
    import numpy as np
    import torch

    from caracole.autochords.btc_model import BTCModel, LayerNorm

    class UnbiasedLayerNorm(LayerNorm):
        """btc_model.py's layer norm, ``x.std`` as the sum of squares over n − 1, which ONNX has no op for."""

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            mean = x.mean(-1, keepdim=True)
            centred = x - mean
            std = torch.sqrt((centred * centred).sum(-1, keepdim=True) / (self.gamma.numel() - 1))
            return self.gamma * centred / (std + self.eps) + self.beta

    class Normalizing(BTCModel):
        def __init__(self):
            super().__init__(num_chords=int(state["output_layer.output_projection.weight"].shape[0]))
            # As btc.py computes it: float32 frames, less the mean, over the standard deviation, both as float32.
            self.register_buffer("mean", torch.tensor(np.float32(mean)), persistent=False)
            self.register_buffer("std", torch.tensor(np.float32(std)), persistent=False)

        def forward(self, features: torch.Tensor) -> torch.Tensor:
            return super().forward((features - self.mean) / self.std)

    model = Normalizing()
    model.load_state_dict(state, strict=True)
    for module in model.modules():
        if type(module) is LayerNorm:
            module.__class__ = UnbiasedLayerNorm
    return model.eval()


def _traced(model, example, *, inputs: list[str], outputs: list[str], dynamic: dict, folding: bool) -> onnx.ModelProto:
    """``model`` as an ONNX graph, by torch's TorchScript exporter (the one beat_this's community exports use)."""
    import onnx
    import torch

    buffer = io.BytesIO()
    with warnings.catch_warnings():
        # The exporter's deprecation, and what the tracer and constant folding say of shapes and slices they keep.
        warnings.simplefilter("ignore")
        torch.onnx.export(
            model,
            (example,),
            buffer,
            dynamo=False,
            opset_version=OPSET,
            do_constant_folding=folding,
            input_names=inputs,
            output_names=outputs,
            dynamic_axes=dynamic,
        )
    return onnx.load_from_string(buffer.getvalue())


def _store_as_float16(graph: onnx.ModelProto) -> None:
    """Every float32 initializer stored as float16, a Cast back to float32 in front of the nodes that read it."""
    import numpy as np
    from onnx import TensorProto, helper, numpy_helper

    stored, casts = [], []
    for initializer in graph.graph.initializer:
        if initializer.data_type != TensorProto.FLOAT:
            stored.append(initializer)
            continue
        half = numpy_helper.to_array(initializer).astype(np.float16)
        if not np.isfinite(half).all():
            raise ValueError(f"{initializer.name} doesn't fit in float16")
        stored.append(numpy_helper.from_array(half, f"{initializer.name}.fp16"))
        casts.append(
            helper.make_node("Cast", [f"{initializer.name}.fp16"], [initializer.name], name=f"{initializer.name}.cast",
                             to=TensorProto.FLOAT)
        )
    nodes = [*casts, *graph.graph.node]
    del graph.graph.initializer[:], graph.graph.node[:]
    graph.graph.initializer.extend(stored)
    graph.graph.node.extend(nodes)


def _write(graph: onnx.ModelProto, path: Path) -> Path:
    import onnx

    path.write_bytes(graph.SerializeToString(deterministic=True))
    onnx.checker.check_model(str(path))  # by its path, so that its external data is checked to be beside it
    return path


def _exported(files: tuple[Path, ...], initializers: int) -> Exported:
    return Exported(files, {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}, initializers)


# --- where a legacy checkpoint's tensors are -------------------------------------------------------------------

_LEGACY_MAGIC = 0x1950A86A20F9469CFC6C
_LEGACY_PROTOCOL = 1001
_FLOAT32_BYTES = 4


class _FloatStorage:
    """``torch.FloatStorage``, as a checkpoint's storages name their type."""


@dataclass
class _Storage:
    key: str
    numel: int


@dataclass(frozen=True)
class _Tensor:
    storage: _Storage
    offset: int
    size: tuple[int, ...]
    stride: tuple[int, ...]


def _rebuild_tensor(storage, offset, size, stride, requires_grad, hooks, *metadata) -> _Tensor:
    """``torch._utils._rebuild_tensor_v2``, recording where the tensor is in its storage."""
    if not isinstance(storage, _Storage) or not _ints(offset, *size, *stride) or len(size) != len(stride):
        raise ValueError("a tensor that isn't a float32 tensor's record")
    return _Tensor(storage, offset, tuple(size), tuple(stride))


class _NumpyScalar:
    """``numpy.core.multiarray.scalar``: the checkpoint's standard deviation, kept as it was pickled, never read."""

    def __init__(self, dtype, data):
        self.dtype, self.data = dtype, data


class _NumpyDType:
    """``numpy.dtype``, the scalar's."""

    def __init__(self, *args):
        self.args = args

    def __setstate__(self, state):
        self.state = state


def _latin1(text, encoding):
    """``_codecs.encode``, which protocol 2 pickles bytes with, for latin-1 alone."""
    if not isinstance(text, str) or encoding not in ("latin1", "latin-1"):
        raise ValueError("an encoding other than latin-1")
    return text.encode("latin-1")


_ALLOWED = {
    ("collections", "OrderedDict"): collections.OrderedDict,
    ("torch._utils", "_rebuild_tensor_v2"): _rebuild_tensor,
    ("torch", "FloatStorage"): _FloatStorage,
    ("numpy.core.multiarray", "scalar"): _NumpyScalar,
    ("numpy", "dtype"): _NumpyDType,
    ("_codecs", "encode"): _latin1,
}


class _Strict(pickle.Unpickler):
    """An unpickler that builds only what a legacy checkpoint of float32 tensors holds."""

    def __init__(self, file, storages: dict[str, _Storage]):
        super().__init__(file, encoding="latin1")
        self.storages = storages

    def find_class(self, module, name):
        try:
            return _ALLOWED[(module, name)]
        except KeyError:
            raise ValueError(f"a class a checkpoint of float32 tensors doesn't hold: {module}.{name}") from None

    def persistent_load(self, pid):
        if not (isinstance(pid, tuple) and len(pid) == 6 and pid[0] == "storage" and pid[1] is _FloatStorage
                and isinstance(pid[2], str) and isinstance(pid[3], str) and _ints(pid[4]) and pid[5] is None):
            raise ValueError(f"a storage that isn't a float32 one: {pid!r}"[:200])
        storage = self.storages.setdefault(pid[2], _Storage(pid[2], pid[4]))
        if storage.numel != pid[4]:
            raise ValueError(f"storage {pid[2]} of two sizes")
        return storage


def _ints(*values) -> bool:
    return all(type(v) is int and v >= 0 for v in values)


def pt_offsets(path: Path) -> dict[str, tuple[int, int]]:
    """Each tensor of a legacy checkpoint's ``model`` state dict, by its name: where its bytes begin in the file,
    and how many there are (little-endian float32, contiguous). ValueError for any other file."""
    path = Path(path)
    with open(path, "rb") as f:
        try:
            return _offsets(f, os.fstat(f.fileno()).st_size)
        except (pickle.UnpicklingError, EOFError, struct.error, TypeError, AttributeError, IndexError,
                ValueError) as e:
            raise ValueError(f"{path} is not a checkpoint in torch's legacy format: {e}") from e


def _offsets(f, size: int) -> dict[str, tuple[int, int]]:
    storages: dict[str, _Storage] = {}
    magic, protocol, info = (_Strict(f, storages).load() for _ in range(3))
    if magic != _LEGACY_MAGIC or protocol != _LEGACY_PROTOCOL:
        raise ValueError("no legacy magic number")
    if not isinstance(info, dict) or info.get("little_endian") is not True:
        raise ValueError("not little-endian")
    checkpoint = _Strict(f, storages).load()
    keys = _Strict(f, storages).load()
    model = checkpoint.get("model") if isinstance(checkpoint, dict) else None
    if not isinstance(model, dict) or not all(isinstance(k, str) and isinstance(t, _Tensor) for k, t in model.items()):
        raise ValueError("no state dict of tensors under 'model'")
    if not isinstance(keys, list) or sorted(keys) != sorted(storages) or len(set(keys)) != len(keys):
        raise ValueError("its storages aren't the ones its tensors name")
    # Each storage: its element count as a little-endian int64, then its elements, in the order of the keys.
    begins, at = {}, f.tell()
    for key in keys:
        f.seek(at)
        (count,) = struct.unpack("<q", f.read(8))
        if count != storages[key].numel:
            raise ValueError(f"storage {key} isn't the size its tensors say")
        begins[key] = at + 8
        at += 8 + count * _FLOAT32_BYTES
    if at != size:
        raise ValueError("its storages don't end where the file does")
    offsets = {}
    for name, tensor in model.items():
        numel = 1
        for n in tensor.size:
            numel *= n
        if not _contiguous(tensor.size, tensor.stride) or tensor.offset + numel > tensor.storage.numel:
            raise ValueError(f"{name} isn't contiguous inside its storage")
        offsets[name] = (begins[tensor.storage.key] + tensor.offset * _FLOAT32_BYTES, numel * _FLOAT32_BYTES)
    return offsets


def _contiguous(size: tuple[int, ...], stride: tuple[int, ...]) -> bool:
    """Whether a tensor's elements lie in its storage in C order, with no gaps (a dimension of one may stride by
    anything, as torch's own check has it)."""
    expected = 1
    for n, step in zip(reversed(size), reversed(stride), strict=True):
        if n != 1 and step != expected:
            return False
        expected *= n
    return True
