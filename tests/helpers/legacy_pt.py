"""Checkpoints in torch's legacy format, written with the standard library alone, for export.py's ``pt_offsets``.

BTC's own ``btc_model_large_voca.pt`` is one: five pickles (torch's magic number, its protocol, sys_info, the
checkpoint, the storage keys), then each storage as its element count (a little-endian int64) and its float32
elements. ``checkpoint`` writes one from a few tensors as torch 1.0 wrote BTC's: protocol 2, each tensor rebuilt by
``torch._utils._rebuild_tensor_v2`` from a persistent id of its storage, the state dict's ``_metadata`` and the
numpy scalar of the standard deviation's dtype set by BUILD, the scalar's bytes by ``_codecs.encode``. ``Checkpoint.offsets`` says where each tensor's bytes are and
``.elements`` what they hold. Each keyword argument makes one thing wrong, so a test names what it breaks; ``text``,
``integer``, ``glob`` and ``HEADER`` write pickle opcodes by hand, for what a well-formed file never holds.
"""

from __future__ import annotations

import pickle
import struct
from collections.abc import Iterable
from dataclasses import dataclass

MAGIC = 0x1950A86A20F9469CFC6C
PROTOCOL = 1001


def _header(magic: int = MAGIC, protocol: int = PROTOCOL, little_endian: bool = True) -> bytes:
    info = {"protocol_version": protocol, "little_endian": little_endian, "type_sizes": {"short": 2, "int": 4, "long": 4}}
    return b"".join(pickle.dumps(value, protocol=2) for value in (magic, protocol, info))


HEADER = _header()  # the three pickles before the checkpoint's


def text(s: str) -> bytes:
    """BINUNICODE."""
    data = s.encode("utf-8", "surrogatepass")
    return b"X" + struct.pack("<I", len(data)) + data


def integer(n: int) -> bytes:
    """BININT, or LONG1 for one past 32 bits."""
    if -(2**31) <= n < 2**31:
        return b"J" + struct.pack("<i", n)
    data = n.to_bytes((n.bit_length() + 8) // 8, "little", signed=True)
    return b"\x8a" + bytes([len(data)]) + data


def glob(module: str, name: str) -> bytes:
    """GLOBAL."""
    return b"c" + f"{module}\n{name}\n".encode()


def _tuple(items: Iterable[bytes]) -> bytes:
    return b"(" + b"".join(items) + b"t"


@dataclass(frozen=True)
class Tensor:
    storage: str  # its storage's key
    size: tuple[int, ...]
    offset: int = 0  # in elements
    stride: tuple[int, ...] | None = None  # None: contiguous, in C order

    @property
    def numel(self) -> int:
        n = 1
        for d in self.size:
            n *= d
        return n

    def strides(self) -> tuple[int, ...]:
        if self.stride is not None:
            return self.stride
        out, step = [], 1
        for d in reversed(self.size):
            out.append(step)
            step *= d
        return tuple(reversed(out))


@dataclass(frozen=True)
class Checkpoint:
    data: bytes
    offsets: dict[str, tuple[int, int]]  # each tensor's (offset, length) in the file, as pt_offsets gives them
    elements: dict[str, tuple[float, ...]]  # what each contiguous tensor holds


# Two storages, one of them shared by two tensors (as the cuDNN LSTM's are in BTC's file).
TENSORS = {"a.weight": Tensor("0", (2, 3)), "b.bias": Tensor("1", (4,)), "c": Tensor("0", (2,), offset=4)}
STORAGES = {"0": 6, "1": 4}  # each storage's key and how many elements it holds


def _numpy_std(value: float) -> bytes:
    """``numpy.core.multiarray.scalar(numpy.dtype("f8"), <its 8 bytes>)``, as numpy pickles a float64."""
    dtype = glob("numpy", "dtype") + _tuple([text("f8"), b"\x89", b"\x88"]) + b"R"
    state = _tuple([integer(3), text("<"), b"N", b"N", b"N", integer(-1), integer(-1), integer(0)])
    data = glob("_codecs", "encode") + _tuple([text(struct.pack("<d", value).decode("latin-1")), text("latin1")])
    return glob("numpy.core.multiarray", "scalar") + b"(" + dtype + state + b"b" + data + b"R" + b"t" + b"R"


def _tensor(t: Tensor, numel: int, tensor_build: bytes, storage_build: bytes) -> bytes:
    pid = _tuple([text("storage"), glob("torch", "FloatStorage"), text(t.storage), text("cpu"), integer(numel),
                  b"N"]) + b"Q" + storage_build
    args = [pid, integer(t.offset), _tuple(integer(n) for n in t.size), _tuple(integer(n) for n in t.strides()),
            b"\x89", glob("collections", "OrderedDict") + b")R"]
    return glob("torch._utils", "_rebuild_tensor_v2") + _tuple(args) + b"R" + tensor_build


def checkpoint(
    tensors: dict[str, Tensor] = TENSORS,
    storages: dict[str, int] = STORAGES,
    *,
    magic: int = MAGIC,
    protocol: int = PROTOCOL,
    little_endian: bool = True,
    keys: list[str] | None = None,
    counts: dict[str, int] | None = None,
    claimed: dict[str, int] | None = None,
    after: bytes = b"",
    tensor_build: bytes = b"",
    storage_build: bytes = b"",
) -> Checkpoint:
    """A legacy checkpoint of ``tensors`` over ``storages`` (each key's element count).

    ``keys``: the storage keys it lists, sorted ``storages`` by default; ``counts``: element counts its storages
    claim otherwise than their persistent ids do; ``claimed``: element counts both claim, past what the storages
    hold; ``after``: bytes after its last storage; ``tensor_build`` and ``storage_build``: opcodes right after each
    tensor's REDUCE and each storage's persistent id."""
    keys = sorted(storages) if keys is None else keys
    claimed = claimed or {}
    counts = {**claimed, **(counts or {})}
    model = glob("collections", "OrderedDict") + b")R" + b"("
    for name, t in tensors.items():
        numel = claimed.get(t.storage, storages.get(t.storage, 0))
        model += text(name) + _tensor(t, numel, tensor_build, storage_build)
    # torch's note of its modules' versions, set on the state dict by BUILD as an ordered dict's state.
    versions = glob("collections", "OrderedDict") + b")R(" + text("") + b"}" + text("version") + integer(1) + b"su"
    model += b"u" + b"}" + text("_metadata") + versions + b"s" + b"b"
    body = (b"\x80\x02}(" + text("model") + model + text("mean") + b"G" + struct.pack(">d", -2.25)
            + text("std") + _numpy_std(1.75) + b"u.")
    data = _header(magic, protocol, little_endian) + body + pickle.dumps(keys, protocol=2)
    begins, values = {}, {}
    for place, key in enumerate(keys):
        numel = storages.get(key, 0)
        values[key] = [100.0 * (place + 1) + i for i in range(numel)]  # each storage's elements its own
        begins[key] = len(data) + 8
        data += struct.pack("<q", counts.get(key, numel)) + struct.pack(f"<{numel}f", *values[key])
    offsets, elements = {}, {}
    for name, t in tensors.items():
        if t.storage in begins:
            offsets[name] = (begins[t.storage] + 4 * t.offset, 4 * t.numel)
            elements[name] = tuple(values[t.storage][t.offset : t.offset + t.numel])
    return Checkpoint(data + after, offsets, elements)
