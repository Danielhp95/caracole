"""The conformance corpus's auto-chords models half: what the computer's models make of the committed clips, for the
phone's port of the front ends and its ONNX Runtime to be held to (the design: .claude/handoff/synchunt-2026-11-25/
android-autochords-design.md, §4).

The clips, tests/fixtures/autochords/*.wav and their README, are synth_music.py's (``CLIPS``), checked here in any
shell. The rest needs torch, librosa, beat_this, onnx, onnxruntime and mir_eval, and the model files
(``CARACOLE_BTC_WEIGHTS``, ``CARACOLE_BEAT_CHECKPOINT``, as tests/test_autochords_models.py finds them): marked
``autochords``, it runs in ``.#autochords`` alone, and is regenerated there with ``CARACOLE_CORPUS=write nix develop
.#autochords -c pytest -q -n 0 -m autochords tests/test_conformance_autochords_models.py``.
The ONNX graphs are exported here by export.py from those very files, into a temporary folder: an export is the
same bytes every time (test_autochords_export.py), so they are ``.#chord-models``' files, whose SHA-256s
models.json names.

What it writes (every array a corpus ``array``: ``{"dtype", "shape", "base64"}``, base64 of its little-endian bytes,
row-major; every number in a record a float32's value or an int, written as JSON writes a Python float):

- ``vectors/autochords/frontend.jsonl``: a ``meta`` record (the libraries, the threads, the encoding), then a record a
  clip: its WAV (a fixture reference), its samples' count and the SHA-256 of the float32 samples BTC reads; its
  length by mutagen (run.py's); BTC's raw log-CQT (``cqt``, float32 ``[frames, 144]``, btc.py ``cqt_features``) and
  beat_this's log-mel (``mel``, stored as float16 ``[T, 128]``), each with its frames' L2 norms (``math.fsum`` of the
  stored values' squares, its square root).
- ``vectors/autochords/models.jsonl``: a ``meta`` record, then a record a clip, of PyTorch's answers on one thread:
  - ``btc``: the logits (float32 ``[frames, 170]``) of that very ``cqt``, its windows of 108 frames, the last one
    padded with the checkpoint's mean (models.json's ``btc.mean``); each frame's ``argmax`` and ``second`` class and
    their ``margin``; the chords ``recognize`` names (``segments``, ``[start, end, name]``);
  - ``beats``: beat_this's ``beat`` and ``downbeat`` logits (float32 ``[T]``) of frontend.jsonl's ``mel`` as it is
    stored (float16, read as float32), in its 1500-frame chunks, and its minimal postprocessor's ``beats`` and
    ``downbeats``, which are the computer's for the clip's audio too;
  - ``known``: the chords, beats and downbeats as synth_music.py played them.
- ``data/caracole/autochords/btc-graph.onnx``: export.py's BTC graph, the APK's.
- ``data/caracole/autochords/models.json``: the pins: the contract; each file's name, bytes and SHA-256 (BTC's
  authors' file with its git blob id, repository, commit and path, from nix/autochords.nix's pin); BTC's mean and std
  (the graph's metadata), its window, bins and classes; beat_this's chunk, border and frame rate; and each model's
  name for an auto sheet's ``raw["models"]``.

Two runs on this machine write the same bytes: torch runs on one thread, as its sums' order moves the last bits
with the threads. Another machine's torch, or the phone's ONNX Runtime, is held to these numbers by the design's
gates, not bit for bit: ``test_onnx_runtime_meets_the_gates_on_the_stored_inputs`` measures this machine's.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import subprocess_pythonpath
from helpers import synth_music
from helpers.corpus import DATA, FIXTURES, VECTORS, check, jsonl
from test_autochords_models import BEAT_CHECKPOINT, BTC_WEIGHTS, _imports, _installed

MADE_BY = "tests/test_conformance_autochords_models.py"
CLIPS = FIXTURES / "autochords"
AREA = VECTORS / "autochords"
MODELS_DATA = DATA / "autochords"
ROOT = Path(__file__).resolve().parents[1]
THREADS = 1
LIBS = ("numpy", "soundfile", "torch", "torchaudio", "librosa", "beat_this", "onnx", "onnxruntime", "mir_eval",
        "mutagen")
HAVE_LIBS = _installed(*LIBS)


# --- the clips, in any shell -----------------------------------------------------------------------------------


def test_the_committed_clips_are_what_synth_music_renders():
    for clip in synth_music.CLIPS:
        check(CLIPS / f"{clip.name}.wav", synth_music.render(clip.spec, clip.seed))


def test_the_clips_readme_names_each_clips_spec():
    check(CLIPS / "README.md", synth_music.readme())
    text = (CLIPS / "README.md").read_text(encoding="utf-8")
    for clip in synth_music.CLIPS:
        assert synth_music.described(clip) in text


def test_a_clips_known_chords_cover_it_and_its_beats_lie_inside_them():
    for clip in synth_music.CLIPS:
        chords, beats, downbeats = synth_music.known(clip.spec)
        assert chords[0][0] == 0.0 and chords[-1][1] == round(clip.spec.seconds, 3)
        assert all(a[1] == b[0] for a, b in zip(chords, chords[1:]))
        assert set(downbeats) <= set(beats) and beats == sorted(beats)
        assert all(any(s <= t < e and name != "N" for s, e, name in chords) for t in beats)


# --- the models, in .#autochords -------------------------------------------------------------------------------


@functools.cache
def _libs_load() -> bool:
    return HAVE_LIBS and _imports(*LIBS)


@pytest.fixture(scope="module")
def _models():
    if not HAVE_LIBS or BTC_WEIGHTS is None or BEAT_CHECKPOINT is None:
        pytest.skip("needs torch, librosa, beat_this, onnx, onnxruntime, mir_eval and both model files "
                    "(CARACOLE_BTC_WEIGHTS, CARACOLE_BEAT_CHECKPOINT): nix develop .#autochords")
    if not _libs_load():
        pytest.skip("torch, beat_this, onnx or onnxruntime won't load")


@pytest.fixture(scope="module")
def exports(_models, tmp_path_factory):
    """export.py's three graphs (and BTC's authors' file beside its graph) in a temporary folder."""
    from caracole.autochords.export import export_beats, export_btc

    out = tmp_path_factory.mktemp("chord-models")
    export_btc(BTC_WEIGHTS, out)
    export_beats(BEAT_CHECKPOINT, out, fp16=False)
    export_beats(BEAT_CHECKPOINT, out, fp16=True)
    return out


def _meta() -> dict:
    import beat_this
    import librosa
    import numpy
    import soundfile
    import torch
    import torchaudio

    return {"kind": "meta", "threads": THREADS, "arrays": "base64 of little-endian values, row-major",
            "libraries": {"beat_this": getattr(beat_this, "__version__", "1.1.0"), "librosa": librosa.__version__,
                          "numpy": numpy.__version__, "soundfile": soundfile.__version__,
                          "torch": torch.__version__, "torchaudio": torchaudio.__version__}}


def _norms(a) -> list[float]:
    return [math.sqrt(math.fsum(v * v for v in row)) for row in a.astype("float64").tolist()]


def _f32(x) -> float:
    import numpy as np

    return float(np.float32(x))


def _records() -> tuple[list[dict], list[dict]]:
    """frontend.jsonl's and models.jsonl's records."""
    import numpy as np

    from helpers.autochords_reference import array, logits_of, peaks_of, reference
    from helpers.corpus import fixture_ref

    meta = _meta()
    frontend, models = [meta], [meta]
    for clip in synth_music.CLIPS:
        wav = CLIPS / f"{clip.name}.wav"
        ref = reference(wav, btc=BTC_WEIGHTS, beats=BEAT_CHECKPOINT, threads=THREADS)
        mel = ref.mel.astype(np.float16)
        stored = mel.astype(np.float32)
        frontend.append({
            "kind": "clip", "clip": clip.name, "wav": fixture_ref(wav), "rate": synth_music.RATE,
            "samples": len(ref.decoded),
            "decoded_sha256": hashlib.sha256(ref.decoded.astype("<f4").tobytes()).hexdigest(),
            "duration": ref.duration, "cqt": array(ref.features), "cqt_norms": _norms(ref.features),
            "mel": array(mel, "float16"), "mel_norms": _norms(stored),
        })
        beat, downbeat = logits_of(stored, BEAT_CHECKPOINT, THREADS)
        beats, downbeats = peaks_of(beat, downbeat)
        assert (beats, downbeats) == (ref.beats, ref.downbeats), f"{clip.name}: float16's mel moves a beat"
        first = ref.logits.argmax(axis=-1)
        rows = np.arange(len(ref.logits))
        others = ref.logits.copy()
        others[rows, first] = -np.inf
        second = others.argmax(axis=-1)
        margin = ref.logits[rows, first] - ref.logits[rows, second]
        chords, known_beats, known_downbeats = synth_music.known(clip.spec)
        models.append({
            "kind": "clip", "clip": clip.name,
            "btc": {"frames": len(ref.logits), "windows": -(-len(ref.logits) // 108), "logits": array(ref.logits),
                    "argmax": first.tolist(), "second": second.tolist(), "margin": [_f32(m) for m in margin],
                    "segments": ref.segments},
            "beats": {"frames": len(beat), "beat": array(beat), "downbeat": array(downbeat), "beats": beats,
                      "downbeats": downbeats},
            "known": {"chords": chords, "beats": known_beats, "downbeats": known_downbeats},
        })
    return frontend, models


@functools.cache
def _texts() -> tuple[str, str]:
    frontend, models = _records()
    return (jsonl(frontend, corpus="autochords/frontend", made_by=MADE_BY),
            jsonl(models, corpus="autochords/models", made_by=MADE_BY))


@pytest.mark.autochords
def test_frontend_and_models_vectors(_models):
    frontend, models = _texts()
    check(AREA / "frontend.jsonl", frontend)
    check(AREA / "models.jsonl", models)


def _btc_pin() -> dict[str, str]:
    """BTC's authors' file as nix/autochords.nix pins it: its repository, commit and path."""
    text = (ROOT / "nix" / "autochords.nix").read_text(encoding="utf-8")
    m = re.search(r"raw\.githubusercontent\.com/([^/]+/[^/]+)/([0-9a-f]{40})/(\S+?btc_model_large_voca\.pt)", text)
    assert m, "nix/autochords.nix pins no btc_model_large_voca.pt"
    return {"repository": m[1], "commit": m[2], "path": m[3]}


def _file(path: Path) -> dict:
    data = path.read_bytes()
    return {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def models_json(out: Path) -> str:
    import onnx

    from caracole.autochords.btc import N_BINS, TIMESTEP
    from caracole.autochords.export import (
        BEATS_CHUNK, BEATS_FP16_GRAPH, BEATS_GRAPH, BTC_GRAPH, BTC_WEIGHTS_NAME, CONTRACT,
    )

    meta = {p.key: p.value for p in onnx.load(out / BTC_GRAPH, load_external_data=False).metadata_props}
    weights = (out / BTC_WEIGHTS_NAME).read_bytes()
    checkpoint = hashlib.sha256(Path(BEAT_CHECKPOINT).read_bytes()).hexdigest()
    btc_name = f"btc_large_voca@{hashlib.sha256(weights).hexdigest()[:16]}"
    assert meta["weights_sha256"] == hashlib.sha256(weights).hexdigest()
    doc = {
        "contract": CONTRACT,
        "release": "models",
        "btc": {
            "graph": _file(out / BTC_GRAPH),
            "weights": {**_file(out / BTC_WEIGHTS_NAME), **_btc_pin(),
                        "git_blob": hashlib.sha1(b"blob %d\0" % len(weights) + weights).hexdigest()},
            "mean": float(meta["mean"]), "std": float(meta["std"]), "pad": "mean",
            "window": TIMESTEP, "bins": N_BINS, "classes": 170, "model": btc_name,
        },
        "beats": {
            "checkpoint": {"name": "final0.ckpt", "bytes": Path(BEAT_CHECKPOINT).stat().st_size, "sha256": checkpoint},
            "fp32": {**_file(out / BEATS_GRAPH), "asset": BEATS_GRAPH, "model": f"beat_this final0@{checkpoint[:16]}"},
            "fp16": {**_file(out / BEATS_FP16_GRAPH), "asset": BEATS_FP16_GRAPH,
                     "model": f"beat_this final0@{checkpoint[:16]} fp16"},
            "chunk": BEATS_CHUNK, "border": 6, "fps": 50, "bins": 128,
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


@pytest.mark.autochords
def test_models_json_and_btc_graph(exports):
    from caracole.autochords.export import BTC_GRAPH

    check(MODELS_DATA / BTC_GRAPH, (exports / BTC_GRAPH).read_bytes())
    check(MODELS_DATA / "models.json", models_json(exports))


def _unarray(a):
    import base64

    import numpy as np

    dtype = np.dtype(a["dtype"]).newbyteorder("<")
    return np.frombuffer(base64.b64decode(a["base64"]), dtype=dtype).reshape(a["shape"])


def _committed(name: str) -> list[dict]:
    lines = (AREA / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[1:] if json.loads(line)["kind"] == "clip"]


def _ort(path: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def _ort_beats(session, mel):
    """beat_this's chunking and aggregation (its own functions) around the ONNX graph."""
    import numpy as np
    import torch
    from beat_this.inference import split_predict_aggregate

    def model(chunk):
        beat, downbeat = session.run(["beat", "downbeat"], {"spect": chunk.numpy().astype(np.float32)})
        return {"beat": torch.from_numpy(beat), "downbeat": torch.from_numpy(downbeat)}

    out = split_predict_aggregate(torch.from_numpy(mel), 1500, 6, "keep_first", model)
    return out["beat"].numpy(), out["downbeat"].numpy()


@pytest.mark.autochords
def test_onnx_runtime_meets_the_gates_on_the_stored_inputs(exports):
    """The design's B0 gates, on this machine, over the committed records' inputs: BTC's argmax equal on every frame
    (each frame's top two are further apart than 1e-3 here), its logits within 1e-4; beat_this's fp32 logits within
    1e-3; its fp16-stored file's beats and downbeats at F 1.0 (±70 ms, mir_eval's 5 s trim)."""
    import mir_eval
    import numpy as np

    from caracole.autochords.export import BEATS_FP16_GRAPH, BEATS_GRAPH, BTC_GRAPH

    frontend = {r["clip"]: r for r in _committed("frontend.jsonl")}
    models = _committed("models.jsonl")
    btc = _ort(exports / BTC_GRAPH)
    mean = np.float32(btc.get_modelmeta().custom_metadata_map["mean"])
    fp32, fp16 = _ort(exports / BEATS_GRAPH), _ort(exports / BEATS_FP16_GRAPH)
    for record in models:
        clip = record["clip"]
        cqt = _unarray(frontend[clip]["cqt"])
        frames = len(cqt)
        padded = np.concatenate([cqt, np.full((-frames % 108, cqt.shape[1]), mean, np.float32)])
        logits = btc.run(["logits"], {"features": padded.reshape(-1, 108, cqt.shape[1])})[0].reshape(-1, 170)[:frames]
        want = _unarray(record["btc"]["logits"])
        assert min(record["btc"]["margin"]) > 1e-3, clip
        assert logits.argmax(axis=-1).tolist() == record["btc"]["argmax"], clip
        assert np.abs(logits - want).max() <= 1e-4, clip

        mel = _unarray(frontend[clip]["mel"]).astype(np.float32)
        beat, downbeat = _ort_beats(fp32, mel)
        assert np.abs(beat - _unarray(record["beats"]["beat"])).max() <= 1e-3, clip
        assert np.abs(downbeat - _unarray(record["beats"]["downbeat"])).max() <= 1e-3, clip

        from helpers.autochords_reference import peaks_of

        beats, downbeats = peaks_of(*_ort_beats(fp16, mel))
        for name, got in (("beats", beats), ("downbeats", downbeats)):
            ref = mir_eval.beat.trim_beats(np.array(record["beats"][name]))
            est = mir_eval.beat.trim_beats(np.array(got))
            if len(ref):
                assert mir_eval.beat.f_measure(ref, est, 0.07) == 1.0, (clip, name)


_DIGESTS = """
import hashlib, sys
sys.path[:0] = ["tests"]
import test_conformance_autochords_models as m
for text in m._texts():
    print(hashlib.sha256(text.encode()).hexdigest())
"""


@pytest.mark.autochords
def test_two_processes_of_other_hash_seeds_write_the_same_records(_models):
    want = [hashlib.sha256(text.encode()).hexdigest() for text in _texts()]
    for seed in ("0", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": subprocess_pythonpath(ROOT / "src")}
        done = subprocess.run([sys.executable, "-c", _DIGESTS], cwd=ROOT, env=env, capture_output=True, text=True,
                              check=True)
        assert done.stdout.split() == want, f"PYTHONHASHSEED={seed}"
