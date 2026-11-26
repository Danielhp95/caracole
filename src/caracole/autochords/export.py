"""BTC and beat_this as ONNX graphs, for chords and beats worked out on the phone.

The phone runs the computer's two models on ONNX Runtime. This module writes their graphs, and
tests/test_autochords_export.py holds each one to PyTorch's answers. ``CONTRACT`` is what a graph takes and gives:
a change to either is a new contract.

- ``export_btc`` writes ``btc-graph.onnx`` (opset 17), BTC (btc_model.py) over raw log-CQT frames, ``features:
  float32[N, 108, 144]``, giving ``logits: float32[N, 108, 170]``. The graph normalizes the frames itself by the
  checkpoint's mean and standard deviation, in float32 as btc.py does, and its metadata says both: a window's frames
  past the audio's end are padded with that mean (never 0), which normalizes to btc.py's zeros. Its layer norms' unbiased standard deviation is written
  out (the sum of squares over n − 1), and nothing is folded, so the graph holds no weight of its own: every tensor
  of the checkpoint's state dict is an external initializer at its offset in the authors' own
  ``btc_model_large_voca.pt``, which is copied beside it unchanged. BTC's weights are never re-hosted.
- ``export_beats`` writes beat_this's final0 checkpoint over its log-mel frames, ``spect: float32[1, T, 128]``,
  giving the ``beat`` and ``downbeat`` logits, ``float32[1, T]``. With ``fp16``, its weights are stored as float16
  and cast to float32 as the graph loads, so it computes in float32. Its attentions over time run one slice at a
  time (``_attention_by_slices``), the same answers to the bit in a fraction of the memory.
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
import pickletools
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
    into. ValueError when the graph's initializers aren't the checkpoint's tensors, byte for byte.

    The graph's metadata (``metadata_props``) holds ``mean`` and ``std``, the float32 values it normalizes with, and
    ``weights_sha256``, the authors' file's. A window's frames past the audio's end are padded with that mean, never
    0, or the last window's chords come out wrong. Nothing but that SHA-256 says which ``.pt`` the graph's offsets
    are into: a caller checks the file beside it against it before running the graph."""
    import numpy as np
    import torch
    from onnx import TensorProto

    from caracole.autochords.btc import N_BINS, TIMESTEP, _load_checkpoint

    weights, out = Path(weights), Path(out)
    if not weights.is_file():
        raise FileNotFoundError(f"BTC weights not found: {weights}")
    offsets = pt_offsets(weights)
    checkpoint = _load_checkpoint(weights)
    state = {k: v for k, v in checkpoint["model"].items() if not k.startswith("output_layer.lstm.")}
    # As btc.py normalizes: float32 frames, less the mean, over the standard deviation, both as float32.
    mean, std = np.float32(float(checkpoint["mean"])), np.float32(float(checkpoint["std"]))
    model = _btc_for_export(state, mean, std)
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
    # Each float32 as the shortest decimal that reads back as it.
    for key, value in (("mean", str(mean)), ("std", str(std)), ("weights_sha256", hashlib.sha256(authors).hexdigest())):
        entry = graph.metadata_props.add()
        entry.key, entry.value = key, value
    out.mkdir(parents=True, exist_ok=True)
    copy = out / BTC_WEIGHTS_NAME
    if not (copy.exists() and copy.samefile(weights)):
        shutil.copyfile(weights, copy)
    path = _write(graph, out / BTC_GRAPH)
    return _exported((path, copy), len(graph.graph.initializer))


def export_beats(checkpoint: Path, out: Path, *, fp16: bool, sliced: bool = True) -> Exported:
    """beat_this's final0 checkpoint as ``beat_this-final0.onnx`` in ``out``, or with ``fp16`` as
    ``beat_this-final0-fp16.onnx``, its weights stored as float16; its attentions one slice at a time
    (``_attention_by_slices``), unless not ``sliced`` (the tests' whole attention, to hold it to)."""
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
    if sliced:
        _attention_by_slices(graph)
    if fp16:
        _store_as_float16(graph)
    out.mkdir(parents=True, exist_ok=True)
    path = _write(graph, out / (BEATS_FP16_GRAPH if fp16 else BEATS_GRAPH))
    return _exported((path,), len(graph.graph.initializer))


def _btc_for_export(state: dict, mean, std):
    """BTC with the checkpoint's tensors, which normalizes raw log-CQT frames itself by ``mean`` and ``std`` (numpy
    float32s) and writes its layer norms' unbiased standard deviation out."""
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
            self.register_buffer("mean", torch.tensor(mean), persistent=False)
            self.register_buffer("std", torch.tensor(std), persistent=False)

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


# beat_this's attentions over a chunk's frames, as the exporter names them, and the axis of their scores that a
# slice is taken along: its frontend's over time attend once a frequency band (scores [bands, heads, T, T]: the
# bands, 32, 16 and 8), its transformer blocks' once a chunk (scores [1, 16, T, T]: the heads).
_ATTENDS_OVER_TIME = (("/partial/attnT/attend/", 0), ("/transformer_blocks/", 1))


def _attention_by_slices(graph: onnx.ModelProto) -> int:
    """Each of beat_this's attentions over time, its scores' MatMul, their Softmax and the MatMul by the values, as one
    Scan over the axis ``_ATTENDS_OVER_TIME`` gives it: the same three ops over each slice in turn, the outputs put
    together where they were. Each slice's answers are the whole's to the bit (each is its own matrix product and
    its own rows' softmax either way), and a 1500-frame chunk's scores and softmax are no longer two [32, 1, 1500,
    1500] float32s at once, 576 MB, but one slice's at a time (36 MB at most): the phone's peak memory (the
    chords-on-the-phone design's B0 memory gate, 1 GB) is that pair's. The count of attentions rewritten."""
    from onnx import TensorProto, helper

    nodes = list(graph.graph.node)
    producer = {o: n for n in nodes for o in n.output}
    readers: dict[str, list] = collections.defaultdict(list)
    for n in nodes:
        for i in n.input:
            readers[i].append(n)
    rewritten: dict[str, object] = {}
    dropped: set[str] = set()
    for softmax in (n for n in nodes if n.op_type == "Softmax"):
        axis = next((a for name, a in _ATTENDS_OVER_TIME if name in softmax.name), None)
        scores = producer.get(softmax.input[0])
        after = readers[softmax.output[0]]
        if axis is None or scores is None or scores.op_type != "MatMul" or len(after) != 1:
            continue
        by_values = after[0]
        if by_values.op_type != "MatMul" or by_values.input[0] != softmax.output[0]:
            continue
        last = next((a.i for a in softmax.attribute if a.name == "axis"), -1)
        if last not in (-1, 3):
            raise ValueError(f"{softmax.name}: a softmax over axis {last}, not its scores' last")
        body = helper.make_graph(
            [helper.make_node("MatMul", ["q", "k"], ["scores"]),
             helper.make_node("Softmax", ["scores"], ["weights"], axis=-1),
             helper.make_node("MatMul", ["weights", "v"], ["out"])],
            f"{softmax.name}/by_slices",
            [helper.make_tensor_value_info(name, TensorProto.FLOAT, None) for name in ("q", "k", "v")],
            [helper.make_tensor_value_info("out", TensorProto.FLOAT, None)],
        )
        rewritten[by_values.name] = helper.make_node(
            "Scan", [scores.input[0], scores.input[1], by_values.input[1]], [by_values.output[0]],
            name=f"{softmax.name}/by_slices", num_scan_inputs=3, body=body, scan_input_axes=[axis] * 3,
            scan_output_axes=[axis])
        dropped |= {scores.name, softmax.name}
    kept = [rewritten.get(n.name, n) for n in nodes if n.name not in dropped]
    del graph.graph.node[:]
    graph.graph.node.extend(kept)
    return len(rewritten)


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
#
# The file may come from the network, so the unpickler trusts nothing in it. It is the standard library's
# pure-Python one, whose opcodes it guards one by one:
# - no opcode of a later protocol than 2, the legacy format's (no frames, sets, byte arrays or buffers);
# - nothing but the six globals of `_ALLOWED`, each a stand-in that runs and imports nothing;
# - BUILD, which would set state on any object, only where torch's legacy format sets it: a numpy dtype's, and a
#   state dict's `_metadata` (its modules' versions, never read); so nothing else handed out (a record checked as it
#   was made, a class, a function) is changed after it;
# - no dictionary key but a text or a number: hashing a tuple nested deep enough overflows CPython's C stack;
# - no length read past the file's end, so a length a file claims is never allocated before it is there.
# Then every record is checked again where it is used.

_LEGACY_MAGIC = 0x1950A86A20F9469CFC6C
_LEGACY_PROTOCOL = 1001
_PICKLE_PROTOCOL = 2
_FLOAT32_BYTES = 4


class _FloatStorage:
    """``torch.FloatStorage``, as a checkpoint's storages name their type."""


@dataclass(frozen=True, slots=True)
class _Storage:
    key: str
    numel: int


@dataclass(frozen=True, slots=True)
class _Tensor:
    storage: _Storage
    offset: int
    size: tuple[int, ...]
    stride: tuple[int, ...]


def _rebuild_tensor(storage, offset, size, stride, requires_grad, hooks, *metadata) -> _Tensor:
    """``torch._utils._rebuild_tensor_v2``, recording where the tensor is in its storage."""
    if not _a_tensor(storage, offset, size, stride):
        raise ValueError("a tensor that isn't a float32 tensor's record")
    return _Tensor(storage, offset, size, stride)


def _a_tensor(storage, offset, size, stride) -> bool:
    return (type(storage) is _Storage and type(size) is tuple and type(stride) is tuple and len(size) == len(stride)
            and _ints(offset, *size, *stride))


class _StateDict(collections.OrderedDict):
    """A state dict, or another ordered dict a checkpoint holds."""


def _ordered_dict() -> _StateDict:
    """``collections.OrderedDict``, empty, as a state dict starts: its items come by SETITEMS, each key checked."""
    return _StateDict()


class _NumpyScalar:
    """``numpy.core.multiarray.scalar``: the checkpoint's standard deviation, kept as it was pickled, never read."""

    __slots__ = ("dtype", "data")

    def __init__(self, dtype, data):
        self.dtype, self.data = dtype, data


class _NumpyDType:
    """``numpy.dtype``, the scalar's, which BUILD sets the state of."""

    __slots__ = ("args", "state")

    def __init__(self, *args):
        self.args = args


def _latin1(text, encoding):
    """``_codecs.encode``, which protocol 2 pickles bytes with, for latin-1 alone."""
    if type(text) is not str or type(encoding) is not str or encoding not in ("latin1", "latin-1"):
        raise ValueError("an encoding other than latin-1")
    return text.encode("latin-1")


_ALLOWED = {
    ("collections", "OrderedDict"): _ordered_dict,
    ("torch._utils", "_rebuild_tensor_v2"): _rebuild_tensor,
    ("torch", "FloatStorage"): _FloatStorage,
    ("numpy.core.multiarray", "scalar"): _NumpyScalar,
    ("numpy", "dtype"): _NumpyDType,
    ("_codecs", "encode"): _latin1,
}


def _later_protocol(name: str):
    def refuse(unpickler):
        raise ValueError(f"opcode {name}, of a later pickle protocol than a legacy checkpoint's")

    return refuse


def _key(key) -> None:
    if type(key) not in (str, int):
        raise ValueError(f"a dictionary key that is a {type(key).__name__}, neither a text nor a number")


def _into(target) -> dict:
    if not isinstance(target, dict):
        raise ValueError(f"items set on a {type(target).__name__}")
    return target


class _Strict(pickle._Unpickler):
    """The pure-Python unpickler, guarded opcode by opcode to build only what a legacy checkpoint of float32 tensors
    holds (the notes above)."""

    dispatch = dict(pickle._Unpickler.dispatch)
    for _op in pickletools.opcodes:
        if _op.proto > _PICKLE_PROTOCOL:
            dispatch[_op.code.encode("latin-1")[0]] = _later_protocol(_op.name)
    del _op

    def __init__(self, file, storages: dict[str, _Storage]):
        super().__init__(file, encoding="latin1")
        self.storages = storages

    def load_proto(self):
        if self.read(1)[0] > _PICKLE_PROTOCOL:
            raise ValueError("a pickle of a later protocol than a legacy checkpoint's")

    dispatch[pickle.PROTO[0]] = load_proto

    def load_build(self):
        state = self.stack.pop()
        target = self.stack[-1]
        if type(target) is _NumpyDType:
            target.state = state
        elif not (type(target) is _StateDict and type(state) is dict and list(state) == ["_metadata"]):
            raise ValueError(f"state set by BUILD on a {type(target).__name__}, which a legacy checkpoint never sets")

    dispatch[pickle.BUILD[0]] = load_build

    def load_dict(self):
        items = self.pop_mark()
        for key in items[::2]:
            _key(key)
        self.append({items[i]: items[i + 1] for i in range(0, len(items), 2)})

    dispatch[pickle.DICT[0]] = load_dict

    def load_setitem(self):
        value, key = self.stack.pop(), self.stack.pop()
        _key(key)
        _into(self.stack[-1])[key] = value

    dispatch[pickle.SETITEM[0]] = load_setitem

    def load_setitems(self):
        items = self.pop_mark()
        target = _into(self.stack[-1])
        for i in range(0, len(items), 2):
            _key(items[i])
            target[items[i]] = items[i + 1]

    dispatch[pickle.SETITEMS[0]] = load_setitems

    def find_class(self, module, name):
        try:
            return _ALLOWED[(module, name)]
        except KeyError:
            raise ValueError(f"a class a checkpoint of float32 tensors doesn't hold: {module}.{name}"[:200]) from None

    def persistent_load(self, pid):
        if not (type(pid) is tuple and len(pid) == 6 and pid[0] == "storage" and pid[1] is _FloatStorage
                and type(pid[2]) is str and type(pid[3]) is str and _ints(pid[4]) and pid[5] is None):
            raise ValueError(f"a persistent id ({type(pid).__name__}) that isn't a float32 storage's")
        storage = self.storages.setdefault(pid[2], _Storage(pid[2], pid[4]))
        if storage.numel != pid[4]:
            raise ValueError(f"storage {pid[2]} of two sizes"[:200])
        return storage


class _Bounded:
    """A file's reads for the unpickler, none past the file's end: a length a pickle claims is refused before it is
    read, never allocated."""

    def __init__(self, f, size: int):
        self.f, self.size = f, size

    def read(self, n: int) -> bytes:
        if not 0 <= n <= self.size - self.f.tell():
            raise ValueError(f"a read of {n} bytes past the file's end")
        return self.f.read(n)

    def readline(self) -> bytes:
        return self.f.readline(self.size - self.f.tell())


def _ints(*values) -> bool:
    return all(type(v) is int and v >= 0 for v in values)


def pt_offsets(path: Path) -> dict[str, tuple[int, int]]:
    """Each tensor of a legacy checkpoint's ``model`` state dict, by its name: where its bytes begin in the file,
    and how many there are (little-endian float32, contiguous). ValueError for any other file."""
    path = Path(path)
    with open(path, "rb") as f:
        try:
            return _offsets(f, os.fstat(f.fileno()).st_size)
        except (pickle.UnpicklingError, EOFError, struct.error, TypeError, AttributeError, IndexError, KeyError,
                ValueError, OverflowError, RecursionError) as e:
            why = str(e)[:300] or type(e).__name__
            raise ValueError(f"{path} is not a checkpoint in torch's legacy format: {why}") from e


def _offsets(f, size: int) -> dict[str, tuple[int, int]]:
    storages: dict[str, _Storage] = {}
    reads = _Bounded(f, size)
    magic, protocol, info = (_Strict(reads, storages).load() for _ in range(3))
    if type(magic) is not int or magic != _LEGACY_MAGIC or type(protocol) is not int or protocol != _LEGACY_PROTOCOL:
        raise ValueError("no legacy magic number")
    if type(info) is not dict or info.get("little_endian") is not True:
        raise ValueError("not little-endian")
    checkpoint = _Strict(reads, storages).load()
    keys = _Strict(reads, storages).load()
    model = checkpoint.get("model") if type(checkpoint) is dict else None
    if not isinstance(model, dict) or not all(type(k) is str and type(t) is _Tensor for k, t in model.items()):
        raise ValueError("no state dict of tensors under 'model'")
    if (type(keys) is not list or not all(type(k) is str for k in keys) or len(set(keys)) != len(keys)
            or set(keys) != set(storages)):
        raise ValueError("its storages aren't the ones its tensors name")
    # Each storage: its element count as a little-endian int64, then its elements, in the order of the keys.
    begins, at = {}, f.tell()
    for key in keys:
        if at + 8 > size:
            raise ValueError(f"storage {key} begins past the file's end"[:200])
        f.seek(at)
        (count,) = struct.unpack("<q", f.read(8))
        if count != storages[key].numel:
            raise ValueError(f"storage {key} isn't the size its tensors say"[:200])
        begins[key] = at + 8
        at += 8 + count * _FLOAT32_BYTES
        if at > size:
            raise ValueError(f"storage {key} runs past the file's end"[:200])
    if at != size:
        raise ValueError("its storages don't end where the file does")
    offsets = {}
    for name, t in model.items():
        # Checked again where it is used, whatever was checked as it was made.
        if not (_a_tensor(t.storage, t.offset, t.size, t.stride) and storages.get(t.storage.key) is t.storage):
            raise ValueError(f"{name} isn't a float32 tensor's record"[:200])
        numel = 1
        for n in t.size:
            numel *= n
        if not _contiguous(t.size, t.stride):
            raise ValueError(f"{name} isn't contiguous"[:200])
        if t.offset + numel > t.storage.numel:
            raise ValueError(f"{name} runs past its storage's end"[:200])
        offsets[name] = (begins[t.storage.key] + t.offset * _FLOAT32_BYTES, numel * _FLOAT32_BYTES)
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
