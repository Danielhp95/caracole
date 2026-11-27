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

- ``vectors/autochords/frontend.jsonl``: a ``meta`` record (the libraries, the threads, torch's kernels, the
  encoding, and the ``gates`` the phone's front ends are held to, ``FRONTEND_GATES``, the design's B1 feature gate),
  then a record a clip: its WAV (a fixture reference), its samples' count and the SHA-256 of the float32
  samples BTC reads; its length by mutagen (run.py's); BTC's raw log-CQT (``cqt``, float32 ``[frames, 144]``, btc.py
  ``cqt_features``) and beat_this's log-mel (``mel``, stored as float16 ``[T, 128]``), each with its frames' L2 norms
  (``math.fsum`` of the stored values' squares, its square root); then an ``excerpt`` record for each of
  ``CQT_EXCERPTS``, the log-CQT of that many of long.wav's samples from its second chunk on, as if they were the
  whole audio (btc.py's last chunk, the lowest octaves' STFTs padded past their few samples).
- ``vectors/autochords/models.jsonl``: a ``meta`` record, frontend.jsonl's with its own ``gates``, those the phone's
  runtime is held to (``GATES``, the design's §4.2), and, a clip at a time, how far float16's mel moves beat_this's
  logits from the full-precision mel's (``mel_float16_logits_max_abs``), then a record a clip, of PyTorch's answers
  on one thread, each checked to be what ``BTCRecognizer.recognize`` and ``detect_beats`` give for the clip:
  - ``btc``: the logits (float32 ``[frames, 170]``) of that very ``cqt``, its windows of 108 frames, the last one
    padded with the checkpoint's mean (models.json's ``btc.mean``); each frame's ``argmax`` and ``second`` class and
    their ``margin``; the chords ``recognize`` names (``segments``, ``[start, end, name]``);
  - ``beats``: beat_this's ``beat`` and ``downbeat`` logits (float32 ``[T]``) of frontend.jsonl's ``mel`` as it is
    stored (float16, read as float32), in its 1500-frame chunks, and its minimal postprocessor's ``beats`` and
    ``downbeats``, which are the computer's for the clip's audio too;
  - ``known``: the chords, beats and downbeats as synth_music.py played them;
  then a ``hearing`` record for each of ``HEARING_FILES`` (encode.sh's: long.wav's first 20 s, 44.1 kHz stereo MP3
  and 48 kHz stereo M4A), the computer's whole hearing of that file (``reference``), no array: ``btc``'s ``samples``
  (librosa's 22,050 Hz length, ``ceil(n · ratio)``), ``frames``, its ``argmax`` as runs (``[class, frames]``) and
  ``segments``; ``beats``' ``frames`` (the mel's, of beat_this's own soxr length), ``beats`` and ``downbeats``; its
  ``duration``, read_audio's.
- ``vectors/autochords/soxr.jsonl``: a ``meta`` record (python-soxr's and libsoxr's versions, its engine, the
  tolerance the phone's libsoxr is held to), then a record a conversion: python-soxr's ``resample`` at HQ (libsoxr
  0.1.3, linear phase, nixpkgs' own build, which python-soxr links) of seeded noise (its samples in the record) or of
  an excerpt of a clip (a fixture reference, its first sample and its count, read as soundfile reads it as float32),
  from 22,050 to 11,025 Hz (the CQT's halvings), 44,100 and 48,000 to 22,050 Hz; one of 120,000 samples, past
  python-soxr's chunk of 96,000 inputs. Needs only numpy, soundfile and soxr, and no CPU's kernels: never skipped
  for them.
- ``vectors/autochords/decode.jsonl``: a ``meta`` record (the libraries; ``DECODE_GATES``, the design's B1 decode
  gate), then a record for each of the decode gate's files (``DECODE_FILES``, tests/fixtures/autochords/encode.sh's):
  its format as audio_store.py ``sniff`` names it, its rate and channels, which reader the computer took
  (``libsndfile``, or ``ffmpeg`` for an M4A and for an MP3 libsndfile reads only in part), its decode as
  autochords/audio.py ``load_mono`` gives it at the file's own rate (its frames, the SHA-256 of its float32 samples,
  and, of a lossy file, those samples as 16-bit, ``pcm16``; of a lossless one, the SHA-256 of soundfile's float32
  channels interleaved, ``interleaved_sha256``, which the phone's must equal, and soundfile's ``subtype``, a FLAC
  deeper than 16 bits its ``pcm16`` too), and its length by music.py ``read_audio`` (its frames counted for an MP3
  that names none). Needs no model and no CPU's kernels.
- ``vectors/autochords/peaks.jsonl``, ``chunks.jsonl`` and ``scores.jsonl``, of no model file (its own section, below):
  beat_this's minimal postprocessor over seeded and hand-made logits; ``split_piece`` and ``aggregate_prediction`` of
  every piece of 0 to 4,000 frames, a table deflated; mir_eval's WCSR (``mir_eval_wcsr``) and beat F-measure
  (``mir_eval_beat_f``) over seeded and hand-made edges; and ``data/caracole/autochords/scores.json``, mir_eval's
  tables (``scores_json``).
- ``data/caracole/autochords/btc-graph.onnx``: export.py's BTC graph, the APK's.
- ``data/caracole/autochords/frontend.json``: what the phone's front ends apply (``frontend_json``): librosa's CQT as it
  ran over a chunk, step by step, its sparse bases and lengths, and beat_this's mel window, norm and filterbank.
- ``data/caracole/autochords/models.json``: the pins: the contract; each file's name, bytes and SHA-256 (BTC's
  authors' file with its git blob id, repository, commit and path, from nix/autochords.nix's pin); BTC's mean and std
  (the graph's metadata), its window, bins and classes (its output's); beat_this's chunk, border, frame rate and
  bins (its code's defaults); and each model's name for an auto sheet's ``raw["models"]``.

Two runs on this machine write the same bytes: torch runs on one thread, as its sums' order moves the last bits
with the threads, and the meta names its kernels (``cpu_capability``). On a CPU of other kernels the byte check is
skipped, saying why; there, as for the phone's ONNX Runtime, the check that counts is the gates':
``test_onnx_runtime_meets_the_gates_on_the_stored_inputs``.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
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


# The design's §4.2 gates for the phone's runtime against these records, which models.jsonl's meta carries and
# test_onnx_runtime_meets_the_gates_on_the_stored_inputs reads back: BTC's argmax equal on every frame but where its
# stored top-two margin is under ``margin_under``, its logits within ``logits_max_abs``; beat_this's fp32 logits
# within theirs; the fp16-stored file's beats and downbeats at F ≥ ``f_measure_min`` (mir_eval's, ``window`` either
# side, the first ``trim`` seconds left out), with no bound on its logits (None). ``end_to_end``, the design's B1 gate
# for the phone's whole hearing of each clip's audio (android/ml's PipelineTest): its chords' WCSR against the chords
# these records' argmax names (Harte labels spelled for the key, mir_eval's rules) at ``wcsr_majmin_min`` and
# ``wcsr_tetrads_min``, its beats' and downbeats' F as the fp16 gate's.
GATES = {
    "btc": {"argmax": "equal", "margin_under": 1e-3, "logits_max_abs": 1e-4},
    "beats_fp32": {"logits_max_abs": 1e-3},
    "beats_fp16": {"logits_max_abs": None, "f_measure_min": 0.99, "window": 0.07, "trim": 5.0},
    "end_to_end": {"wcsr_majmin_min": 0.99, "wcsr_tetrads_min": 0.98, "f_measure_min": 0.99, "window": 0.07,
                   "trim": 5.0},
}


# The design's B1 feature gate for the phone's front ends against frontend.jsonl's ``cqt`` and ``mel``, which its meta
# carries and AutochordsReplays reads back: the same frames, and each frame's cosine with the stored one at a median of
# ``cosine_median_min`` and a least of ``cosine_min``, over the frames that aren't silent. A frame is silent when every
# stored value lies within ``silent_within`` of its feature's floor (``floors``, which _records adds: the log-CQT's
# log(btc.LOG_FLOOR) as float32 makes it, the log-mel's log1p(0)); there the phone's frame must be silent too. Beside
# it a tripwire of ours, not the design's: no value of a frame that isn't silent further than ``max_abs`` from the
# stored one (a √2 slip over one octave of 24 bins moves 1 - cosine by about 1e-4 alone; the port's are 4.5e-4 and
# 3.8e-3 at most, 2026-11-26).
FRONTEND_GATES = {"frames": "equal", "cosine_median_min": 0.9999, "cosine_min": 0.999, "silent_within": 1e-3,
                  "max_abs": 1e-2}
# The end-to-end gate's files (tests/fixtures/autochords/encode.sh), heard whole by the phone against the computer.
HEARING_FILES = ("hearing.mp3", "hearing.m4a")
# frontend.jsonl's excerpts: long.wav's samples from its second chunk on, this many, each btc.py's whole audio.
CQT_EXCERPTS = (2048, 2049, 4095)


def cpu_capability() -> str:
    """The kernels torch dispatches to on this CPU ("AVX512", "AVX2", "DEFAULT"…): its last bits are theirs."""
    import torch

    return torch.backends.cpu.get_cpu_capability()


def _meta() -> dict:
    import beat_this
    import librosa
    import numpy
    import soundfile
    import torch
    import torchaudio

    return {"kind": "meta", "threads": THREADS, "cpu_capability": cpu_capability(),
            "arrays": "base64 of little-endian values, row-major",
            "libraries": {"beat_this": getattr(beat_this, "__version__", "1.1.0"), "librosa": librosa.__version__,
                          "numpy": numpy.__version__, "soundfile": soundfile.__version__,
                          "torch": torch.__version__, "torchaudio": torchaudio.__version__}}


def beat_this_settings() -> dict[str, int]:
    """beat_this's own chunk border, frame rate and mel bins, read from its code."""
    import inspect

    from beat_this.inference import split_piece
    from beat_this.model.postprocessor import Postprocessor
    from beat_this.preprocessing import LogMelSpect

    def default(f, name):
        return inspect.signature(f).parameters[name].default

    return {"border": default(split_piece, "border_size"), "fps": default(Postprocessor, "fps"),
            "bins": default(LogMelSpect, "n_mels")}


def _norms(a) -> list[float]:
    return [math.sqrt(math.fsum(v * v for v in row)) for row in a.astype("float64").tolist()]


def _f32(x) -> float:
    import numpy as np

    return float(np.float32(x))


def _records() -> tuple[list[dict], list[dict]]:
    """frontend.jsonl's and models.jsonl's records."""
    import numpy as np

    from caracole.autochords.beats import detect_beats
    from caracole.autochords.btc import CHUNK_SECONDS, LOG_FLOOR, SAMPLE_RATE, TIMESTEP, BTCRecognizer, cqt_features
    from caracole.autochords.btc import load_audio as btc_load
    from helpers.autochords_reference import array, logits_of, peaks_of, reference, torch_threads
    from helpers.corpus import fixture_ref

    meta = _meta()
    float16_moves: dict[str, float] = {}
    floors = {"cqt": float(np.log(np.float32(LOG_FLOOR))), "mel": 0.0}
    frontend = [{**meta, "gates": {**FRONTEND_GATES, "floors": floors}}]
    models = [{**meta, "gates": GATES, "mel_float16_logits_max_abs": float16_moves}]
    recognizer = BTCRecognizer(BTC_WEIGHTS)
    for clip in synth_music.CLIPS:
        wav = CLIPS / f"{clip.name}.wav"
        ref = reference(wav, btc=BTC_WEIGHTS, beats=BEAT_CHECKPOINT, threads=THREADS)
        # The reference is what caracole autochords makes of the clip: its classes, on the same files, exactly.
        with torch_threads(THREADS):
            chords = [[s.start, s.end, s.label] for s in recognizer.recognize(wav)]
            computer_beats = detect_beats(wav, BEAT_CHECKPOINT)
        assert ref.segments == chords, f"{clip.name}: the reference's chords aren't BTCRecognizer.recognize's"
        assert (ref.beats, ref.downbeats) == computer_beats, f"{clip.name}: the reference's beats aren't detect_beats'"
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
        float16_moves[clip.name] = _f32(max(np.abs(beat - ref.beat_logits[0]).max(),
                                            np.abs(downbeat - ref.beat_logits[1]).max()))
        first = ref.logits.argmax(axis=-1)
        rows = np.arange(len(ref.logits))
        others = ref.logits.copy()
        others[rows, first] = -np.inf
        second = others.argmax(axis=-1)
        margin = ref.logits[rows, first] - ref.logits[rows, second]
        chords, known_beats, known_downbeats = synth_music.known(clip.spec)
        models.append({
            "kind": "clip", "clip": clip.name,
            "btc": {"frames": len(ref.logits), "windows": -(-len(ref.logits) // TIMESTEP), "logits": array(ref.logits),
                    "argmax": first.tolist(), "second": second.tolist(), "margin": [_f32(m) for m in margin],
                    "segments": ref.segments},
            "beats": {"frames": len(beat), "beat": array(beat), "downbeat": array(downbeat), "beats": beats,
                      "downbeats": downbeats},
            "known": {"chords": chords, "beats": known_beats, "downbeats": known_downbeats},
        })
    # btc.py's last chunk when it is all there is of it: long.wav's samples from its second chunk on, a hop's, a
    # sample more and a sample under two hops' (the lowest octaves' STFTs then pad past their few samples).
    long = btc_load(CLIPS / "long.wav")
    start = int(SAMPLE_RATE * CHUNK_SECONDS)
    for count in CQT_EXCERPTS:
        features = cqt_features(long[start:start + count]).astype(np.float32)
        frontend.append({"kind": "excerpt", "wav": fixture_ref(CLIPS / "long.wav"), "offset": start, "count": count,
                         "cqt": array(features), "cqt_norms": _norms(features)})
    for name in HEARING_FILES:
        path = CLIPS / name
        ref = reference(path, btc=BTC_WEIGHTS, beats=BEAT_CHECKPOINT, threads=THREADS)
        runs: list[list[int]] = []
        for k in ref.logits.argmax(axis=-1).tolist():
            if runs and runs[-1][0] == k:
                runs[-1][1] += 1
            else:
                runs.append([k, 1])
        models.append({
            "kind": "hearing", "file": fixture_ref(path), "duration": ref.duration,
            "btc": {"samples": len(ref.decoded), "frames": len(ref.logits), "argmax": runs, "segments": ref.segments},
            "beats": {"frames": len(ref.mel), "beats": ref.beats, "downbeats": ref.downbeats},
        })
    return frontend, models


@functools.cache
def _texts() -> tuple[str, str]:
    frontend, models = _records()
    return (jsonl(frontend, corpus="autochords/frontend", made_by=MADE_BY),
            jsonl(models, corpus="autochords/models", made_by=MADE_BY))


def _committed_meta() -> dict | None:
    path = AREA / "models.jsonl"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8").splitlines()[1])


@pytest.mark.autochords
def test_frontend_and_models_vectors(_models):
    """The records, byte for byte, on a CPU of the committed meta's capability. On another, torch's kernels move the
    last bits, so a byte mismatch is expected there and this check is skipped (not failed: nothing is wrong, and
    regenerating there would only churn the corpus); test_onnx_runtime_meets_the_gates_on_the_stored_inputs, the
    comparison within the gates, is the one that counts."""
    committed = _committed_meta()
    here = cpu_capability()
    if os.environ.get("CARACOLE_CORPUS") != "write" and committed and committed.get("cpu_capability") != here:
        pytest.skip(f"the records were made on a {committed.get('cpu_capability')} CPU's kernels, this one's are "
                    f"{here}: a byte mismatch is expected here; the within-gates comparison is the check that counts")
    frontend, models = _fresh_texts()
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

    graph = onnx.load(out / BTC_GRAPH, load_external_data=False)
    meta = {p.key: p.value for p in graph.metadata_props}
    classes = graph.graph.output[0].type.tensor_type.shape.dim[-1].dim_value
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
            "window": TIMESTEP, "bins": N_BINS, "classes": classes, "model": btc_name,
        },
        "beats": {
            "checkpoint": {"name": "final0.ckpt", "bytes": Path(BEAT_CHECKPOINT).stat().st_size, "sha256": checkpoint},
            "fp32": {**_file(out / BEATS_GRAPH), "asset": BEATS_GRAPH, "model": f"beat_this final0@{checkpoint[:16]}"},
            "fp16": {**_file(out / BEATS_FP16_GRAPH), "asset": BEATS_FP16_GRAPH,
                     "model": f"beat_this final0@{checkpoint[:16]} fp16"},
            "chunk": BEATS_CHUNK, **beat_this_settings(),
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


@pytest.mark.autochords
def test_models_json_and_btc_graph(exports):
    from caracole.autochords.export import BTC_GRAPH

    check(MODELS_DATA / BTC_GRAPH, (exports / BTC_GRAPH).read_bytes())
    check(MODELS_DATA / "models.json", models_json(exports))


def _sparse(rows) -> dict:
    """A sparse matrix of rows, CSR, as frontend.json writes it: its shape, each row's start in ``indices`` (``indptr``)
    and each stored value's column, and the values, float32 ``[nnz]``, or for a complex one ``[nnz, 2]``, (re, im)."""
    import numpy as np

    from helpers.autochords_reference import array

    rows = rows.tocsr()
    rows.sort_indices()
    data = rows.data
    values = (array(np.stack([data.real, data.imag], axis=-1).astype(np.float32)) if np.iscomplexobj(data)
              else array(data.astype(np.float32)))
    return {"shape": list(rows.shape), "indptr": rows.indptr.tolist(), "indices": rows.indices.tolist(),
            "values": values}


def frontend_json() -> str:
    """data/caracole/autochords/frontend.json: what the phone's front ends apply, each number Python's own object.

    ``cqt``: btc.py's settings (``rate``, ``hop``, ``bins``, ``chunk`` in samples, ``min_tail``: the least audio and
    the least tail it keeps, its ``HOP_LENGTH``; the log's ``floor``), and librosa 1.0's ``cqt`` of one chunk at those
    settings, as it ran (``_cqt``, watched): its ``steps`` in order (``samples``: how many each was given, for a whole
    chunk), each either a ``resample`` (librosa's ``audio.resample``: its rates, ``res_type``, ``fix`` and
    ``scale``; the early downsample, then a halving between octaves) or an ``octave`` (its ``__cqt_response``: the
    STFT's ``n_fft``, ``hop``, ``window`` and ``pad_mode``, and the sparse FFT basis it applied, ``basis``, complex64,
    each octave's rescaling in it), then the ``lengths`` its ``scale`` divides each bin by the root of (float64, the
    last ``wavelet_lengths`` it asked for, at ``lengths_rate``). The octaves fill the bins from the top, as
    ``__trim_stack`` does, every one its frames cut to the fewest.
    ``mel``: beat_this's ``LogMelSpect`` (torchaudio's ``MelSpectrogram``): its rate, ``n_fft``, ``hop``, its
    periodic Hann ``window`` (float32), centred with ``pad_mode`` padding, its spectrum's ``norm`` (torch.stft's
    ``normalized``, frame_length**-0.5), power 1, the slaney ``filterbank`` (float32, ``[mels, n_fft // 2 + 1]``, its
    zeros left out) and ``log1p(log_multiplier * x)``."""
    import inspect

    import librosa
    import librosa.core.constantq as constantq
    import numpy as np
    import torchaudio
    from beat_this.preprocessing import LogMelSpect
    from scipy.sparse import csr_array

    from caracole.autochords import btc
    from helpers.autochords_reference import array

    steps: list[dict] = []
    lengths: list[tuple[float, object]] = []
    response = getattr(constantq, "__cqt_response")
    resample = constantq.audio.resample
    wavelet_lengths = constantq.filters.wavelet_lengths
    resample_defaults = inspect.signature(resample).parameters
    response_defaults = inspect.signature(response).parameters

    def watched_response(y, n_fft, hop_length, fft_basis, mode, **kw):
        assert set(kw) <= {"dtype"}, kw
        steps.append({"octave": {"samples": len(y), "n_fft": n_fft, "hop": hop_length,
                                 "window": response_defaults["window"].default, "pad_mode": mode,
                                 "basis": _sparse(fft_basis)}})
        return response(y, n_fft, hop_length, fft_basis, mode, **kw)

    def watched_resample(y, *, orig_sr, target_sr, res_type=resample_defaults["res_type"].default,
                         fix=resample_defaults["fix"].default, scale=resample_defaults["scale"].default, **kw):
        assert not kw, kw
        steps.append({"resample": {"samples": len(y), "from": orig_sr, "to": target_sr, "res_type": res_type,
                                   "fix": fix, "scale": scale}})
        return resample(y, orig_sr=orig_sr, target_sr=target_sr, res_type=res_type, fix=fix, scale=scale)

    def watched_lengths(**kw):
        out = wavelet_lengths(**kw)
        lengths.append((kw["sr"], out[0]))
        return out

    chunk = int(btc.SAMPLE_RATE * btc.CHUNK_SECONDS)
    setattr(constantq, "__cqt_response", watched_response)
    constantq.audio.resample, constantq.filters.wavelet_lengths = watched_resample, watched_lengths
    try:
        out = btc._cqt(np.zeros(chunk, np.float32))
    finally:
        setattr(constantq, "__cqt_response", response)
        constantq.audio.resample, constantq.filters.wavelet_lengths = resample, wavelet_lengths
    assert out.shape[0] == btc.N_BINS
    lengths_rate, last_lengths = lengths[-1]

    spect = LogMelSpect()
    mel = spect.spect_class
    stft = mel.spectrogram
    assert (stft.normalized, stft.center, stft.power, stft.onesided, stft.pad) == ("frame_length", True, 1.0, True, 0)
    assert stft.win_length == stft.n_fft

    doc = {
        "libraries": {"librosa": librosa.__version__, "torchaudio": torchaudio.__version__, "numpy": np.__version__},
        "cqt": {
            "rate": btc.SAMPLE_RATE, "hop": btc.HOP_LENGTH, "bins": btc.N_BINS, "chunk": chunk,
            "min_tail": btc.HOP_LENGTH, "floor": btc.LOG_FLOOR,
            "steps": steps,
            "lengths_rate": float(lengths_rate),
            "lengths": array(np.asarray(last_lengths, np.float64), "float64"),
        },
        "mel": {
            "rate": mel.sample_rate, "n_fft": stft.n_fft, "hop": stft.hop_length, "pad_mode": stft.pad_mode,
            "window": array(stft.window.numpy()), "norm": stft.n_fft ** -0.5,
            "filterbank": _sparse(csr_array(mel.mel_scale.fb.numpy().T)),
            "log_multiplier": spect.log_multiplier,
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


_FRONTEND_JSON = """
import pathlib, sys
sys.path[:0] = ["tests"]
import test_conformance_autochords_models as m
pathlib.Path(sys.argv[1], "frontend.json").write_text(m.frontend_json(), encoding="utf-8")
"""


@pytest.mark.autochords
def test_frontend_json(_models):
    """frontend.json, made in a fresh process as the records are; its bytes held on a CPU of the committed records'
    kernels, as theirs are (test_frontend_and_models_vectors says why)."""
    committed = _committed_meta()
    elsewhere = committed and committed.get("cpu_capability") != cpu_capability()
    if os.environ.get("CARACOLE_CORPUS") != "write" and elsewhere:
        pytest.skip("the records were made on another CPU's kernels: test_frontend_and_models_vectors says why")
    (text,) = _child_texts(_FRONTEND_JSON, ("frontend.json",))
    check(MODELS_DATA / "frontend.json", text)


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
    """beat_this's chunking and aggregation (its own functions, its own chunk and border) around the ONNX graph."""
    import numpy as np
    import torch
    from beat_this.inference import split_predict_aggregate

    from caracole.autochords.export import BEATS_CHUNK

    def model(chunk):
        beat, downbeat = session.run(["beat", "downbeat"], {"spect": chunk.numpy().astype(np.float32)})
        return {"beat": torch.from_numpy(beat), "downbeat": torch.from_numpy(downbeat)}

    border = beat_this_settings()["border"]
    out = split_predict_aggregate(torch.from_numpy(mel), BEATS_CHUNK, border, "keep_first", model)
    return out["beat"].numpy(), out["downbeat"].numpy()


@pytest.mark.autochords
def test_onnx_runtime_meets_the_gates_on_the_stored_inputs(exports):
    """The design's B0 gates, read from models.jsonl's meta (``gates``) as the phone's replay reads them, over the
    committed records' inputs, on this machine's ONNX Runtime."""
    import mir_eval
    import numpy as np

    from caracole.autochords.btc import TIMESTEP
    from caracole.autochords.export import BEATS_FP16_GRAPH, BEATS_GRAPH, BTC_GRAPH
    from helpers.autochords_reference import peaks_of

    gates = _committed_meta()["gates"]
    frontend = {r["clip"]: r for r in _committed("frontend.jsonl")}
    models = _committed("models.jsonl")
    btc = _ort(exports / BTC_GRAPH)
    mean = np.float32(btc.get_modelmeta().custom_metadata_map["mean"])
    fp32, fp16 = _ort(exports / BEATS_GRAPH), _ort(exports / BEATS_FP16_GRAPH)
    for record in models:
        clip = record["clip"]
        cqt = _unarray(frontend[clip]["cqt"])
        frames, bins = cqt.shape
        want = _unarray(record["btc"]["logits"])
        padded = np.concatenate([cqt, np.full((-frames % TIMESTEP, bins), mean, np.float32)])
        logits = btc.run(["logits"], {"features": padded.reshape(-1, TIMESTEP, bins)})[0]
        logits = logits.reshape(-1, want.shape[1])[:frames]
        differ = np.flatnonzero(logits.argmax(axis=-1) != np.array(record["btc"]["argmax"]))
        margins = np.array(record["btc"]["margin"])
        assert (margins[differ] < gates["btc"]["margin_under"]).all(), (clip, differ.tolist())
        assert np.abs(logits - want).max() <= gates["btc"]["logits_max_abs"], clip

        mel = _unarray(frontend[clip]["mel"]).astype(np.float32)
        beat, downbeat = _ort_beats(fp32, mel)
        for got, name in ((beat, "beat"), (downbeat, "downbeat")):
            assert np.abs(got - _unarray(record["beats"][name])).max() <= gates["beats_fp32"]["logits_max_abs"], clip

        half = gates["beats_fp16"]
        assert half["logits_max_abs"] is None
        beats, downbeats = peaks_of(*_ort_beats(fp16, mel))
        for name, got in (("beats", beats), ("downbeats", downbeats)):
            ref = mir_eval.beat.trim_beats(np.array(record["beats"][name]), min_beat_time=half["trim"])
            est = mir_eval.beat.trim_beats(np.array(got), min_beat_time=half["trim"])
            if len(ref):
                assert mir_eval.beat.f_measure(ref, est, half["window"]) >= half["f_measure_min"], (clip, name)


# soxr.jsonl's conversions (from, to), its noise's lengths (each its own seed) and its clips' excerpts: every clip's
# SOXR_EXCERPT samples from its SOXR_OFFSET-th (where silence.wav's music begins), and long.wav's first SOXR_LONG at
# the conversions of SOXR_LONG_AT, past python-soxr's 96,000 and 104,489 inputs a call (its ``div_len``).
SOXR_CONVERSIONS = ((22050, 11025), (44100, 22050), (48000, 22050))
SOXR_NOISE = (0, 1, 2, 7, 100, 1001, 9600)
SOXR_OFFSET, SOXR_EXCERPT = 27562, 8192
SOXR_LONG, SOXR_LONG_AT = 120000, ((22050, 11025), (48000, 22050))
SOXR_TOLERANCE = 1e-6


def soxr_records() -> list[dict]:
    """soxr.jsonl's records."""
    import numpy as np
    import soundfile
    import soxr

    from helpers.autochords_reference import array
    from helpers.corpus import fixture_ref

    engine = soxr.ResampleStream(44100, 22050, 1, dtype="float32", quality="HQ")._csoxr.engine()
    records: list[dict] = [{
        "kind": "meta", "quality": "HQ", "engine": engine, "tolerance": SOXR_TOLERANCE,
        "arrays": "base64 of little-endian values, row-major",
        "libraries": {"soxr": soxr.__version__, "libsoxr": soxr.__libsoxr_version__, "numpy": np.__version__,
                      "soundfile": soundfile.__version__},
    }]

    def record(source: dict, x, conversions) -> None:
        for rate_in, rate_out in conversions:
            y = soxr.resample(x, rate_in, rate_out, quality="HQ")
            assert y.dtype == np.float32
            records.append({"kind": "resample", **source, "from": rate_in, "to": rate_out, "length": len(y),
                            "y": array(y)})

    for n in SOXR_NOISE:
        x = np.random.default_rng(n).uniform(-1.0, 1.0, n).astype(np.float32)
        record({"noise": {"seed": n, "x": array(x)}}, x, SOXR_CONVERSIONS)
    for clip in synth_music.CLIPS:
        wav = CLIPS / f"{clip.name}.wav"
        samples, _ = soundfile.read(wav, dtype="float32")
        x = np.ascontiguousarray(samples[SOXR_OFFSET:SOXR_OFFSET + SOXR_EXCERPT])
        record({"clip": {"wav": fixture_ref(wav), "offset": SOXR_OFFSET, "count": len(x)}}, x, SOXR_CONVERSIONS)
        if clip.name == "long":
            x = np.ascontiguousarray(samples[:SOXR_LONG])
            record({"clip": {"wav": fixture_ref(wav), "offset": 0, "count": len(x)}}, x, SOXR_LONG_AT)
    return records


_SOXR_TEXT = """
import pathlib, sys
sys.path[:0] = ["tests"]
import test_conformance_autochords_models as m
from helpers.corpus import jsonl
text = jsonl(m.soxr_records(), corpus="autochords/soxr", made_by=m.MADE_BY)
pathlib.Path(sys.argv[1], "soxr.jsonl").write_text(text, encoding="utf-8")
"""


@pytest.mark.autochords
def test_soxr_vectors():
    """python-soxr's answers, made in a fresh process as the models' records are."""
    if not _installed("numpy", "soundfile", "soxr"):
        pytest.skip("needs numpy, soundfile and soxr: nix develop .#autochords")
    (text,) = _child_texts(_SOXR_TEXT, ("soxr.jsonl",))
    check(AREA / "soxr.jsonl", text)


# The decode gate's files (tests/fixtures/autochords/encode.sh), each the format audio_store.py ``sniff`` names it.
DECODE_FILES = (("decode.mp3", "MP3"), ("decode-lame.mp3", "MP3"), ("decode-headerless.mp3", "MP3"),
                ("decode.m4a", "M4A"), ("decode-11k.m4a", "M4A"), ("decode.ogg", "Ogg"), ("decode-opus.ogg", "Ogg"),
                ("decode.flac", "FLAC"), ("decode-24.flac", "FLAC"), ("decode.wav", "WAV"), ("decode.aiff", "AIFF"))
# The design's B1 decode gate: no sample offset (by cross-correlation within ``offset_search`` samples either way,
# over ``offset_window`` samples), an SNR of ``snr_db_min`` or more against the computer's decode at the file's rate,
# and of ``snr_second_db_min`` over each whole second of it. The length the phone states held to music.py
# read_audio's, the computer's rule for each container (an MP4's mdhd, an MP3's Xing frames less a LAME tag's delay
# and padding, an MP3 that names none its frames counted, the rest their samples over the rate), within
# ``length_within_samples`` samples at the file's rate; its decoded samples' count the computer's within
# ``decoded_within_samples``. The lossless forms are held closer: sample for sample (``exact``), but a lossless file
# deeper than 16 bits, whose 16-bit decode the platform may give (a FLAC's ``pcm16`` kept for it too).
DECODE_GATES = {"offset": 0, "offset_search": 2048, "offset_window": 22050, "snr_db_min": 60.0,
                "snr_second_db_min": 60.0, "length_within_samples": 2, "decoded_within_samples": 0}
_LOSSLESS = ("FLAC", "WAV", "AIFF")


def _sha256(a) -> str:
    import numpy as np

    return hashlib.sha256(np.ascontiguousarray(a, dtype="<f4").tobytes()).hexdigest()


def _deltas(pcm) -> dict:
    """16-bit samples as decode.jsonl keeps them, a quarter smaller than an ``array``'s: each sample less the one
    before (the first less 0), wrapped to int16, deflated (zlib), in base64; a cumulative sum in int16 gives them back."""
    import zlib

    import numpy as np

    deltas = np.diff(pcm.astype(np.int32), prepend=0).astype("<i2")
    assert np.array_equal(np.cumsum(deltas, dtype=np.int16), pcm)
    return {"dtype": "int16", "shape": [len(pcm)], "coding": "deltas, zlib",
            "base64": base64.b64encode(zlib.compress(deltas.tobytes(), 9)).decode("ascii")}


def decode_records() -> list[dict]:
    """decode.jsonl's records: each file decoded as the computer decodes it, autochords/audio.py ``load_mono`` at the
    file's own rate (so with no resampling), and its length as run.py reads it (music.py ``read_audio``)."""
    import librosa
    import mutagen
    import numpy as np
    import soundfile
    import torchaudio

    from caracole import audio_store
    from caracole.autochords import audio
    from caracole.music import read_audio
    from helpers.corpus import fixture_ref

    records: list[dict] = [{
        "kind": "meta", "gates": DECODE_GATES,
        "samples": "pcm16: round(y * 32768), clipped to int16, of load_mono's float32 y, each less the one before, "
                   "deflated (zlib); *_sha256: SHA-256 of little-endian float32 samples",
        "libraries": {"numpy": np.__version__, "soundfile": soundfile.__version__,
                      "libsndfile": soundfile.__libsndfile_version__, "librosa": librosa.__version__,
                      "torchaudio": torchaudio.__version__, "mutagen": mutagen.version_string},
    }]
    for name, form in DECODE_FILES:
        path = CLIPS / name
        assert audio_store.sniff(path.read_bytes()[:64]) == form, name
        try:
            info = soundfile.info(path)
            rate, channels = info.samplerate, info.channels
        except RuntimeError:  # no format libsndfile reads: FFmpeg's, as load_mono reads it
            waveform, rate = torchaudio.load(str(path))
            channels = waveform.shape[0]
        read = []
        ffmpeg = audio._ffmpeg
        audio._ffmpeg = lambda *a, **kw: read.append("ffmpeg") or ffmpeg(*a, **kw)
        try:
            y = audio.load_mono(path, rate)
        finally:
            audio._ffmpeg = ffmpeg
        assert y.dtype == np.float32
        record = {"kind": "file", "file": fixture_ref(path), "format": form, "rate": rate, "channels": channels,
                  "reader": read[-1] if read else "libsndfile", "frames": len(y),
                  "duration": read_audio(path).duration_s, "mono_sha256": _sha256(y)}
        # Clipped to int16's range: the headerless MP3's burst of noise decodes past full scale in FFmpeg's floats,
        # and a 16-bit decoder clips it there too.
        pcm16 = _deltas(np.clip(np.round(y * 32768.0), -32768, 32767).astype(np.int16))
        if form in _LOSSLESS:
            samples, _ = soundfile.read(path, dtype="float32", always_2d=True)
            record["exact"] = True
            record["interleaved_sha256"] = _sha256(samples)
            record["subtype"] = soundfile.info(path).subtype
            if form == "FLAC" and record["subtype"] not in ("PCM_16", "PCM_U8", "PCM_S8"):
                record["pcm16"] = pcm16  # a codec's: the platform may give it as 16-bit
        else:
            record["exact"] = False
            record["pcm16"] = pcm16
        records.append(record)
    return records


_DECODE_TEXT = """
import pathlib, sys
sys.path[:0] = ["tests"]
import test_conformance_autochords_models as m
from helpers.corpus import jsonl
text = jsonl(m.decode_records(), corpus="autochords/decode", made_by=m.MADE_BY)
pathlib.Path(sys.argv[1], "decode.jsonl").write_text(text, encoding="utf-8")
"""


@pytest.mark.autochords
def test_decode_vectors():
    """The computer's decode of each of the decode gate's files, made in a fresh process as the models' records are."""
    if not _installed("numpy", "soundfile", "librosa", "torchaudio", "mutagen"):
        pytest.skip("needs numpy, soundfile, librosa, torchaudio and mutagen: nix develop .#autochords")
    (text,) = _child_texts(_DECODE_TEXT, ("decode.jsonl",))
    check(AREA / "decode.jsonl", text)


# --- around the models: beat_this's peaks and chunks, and the gates' scores (mir_eval) ---------------------------
# Pure functions of their inputs: no model file and no CPU's kernels, so never skipped for them, and made in this
# process (no beat_this model runs here).

AROUND_LIBS = ("numpy", "torch", "beat_this", "mir_eval")
# peaks.jsonl's seeded logits: quantized ones (an int8 q a frame, the logit q/8, exact in float32, so ties and
# plateaus are common) of each length, and continuous ones (float32).
PEAK_LENGTHS = (1, 2, 3, 4, 6, 7, 8, 13, 50, 333, 1500)
PEAK_CONTINUOUS = (64, 700)
# chunks.jsonl: every piece of 0 to CHUNK_FRAMES frames, its table in blocks of CHUNK_BLOCK lengths.
CHUNK_FRAMES, CHUNK_BLOCK = 4000, 500
# aggregate_prediction's input in chunks.jsonl: chunk i's frame j is i·CHUNK_TAG + j, so each frame of the piece says
# which chunk's which frame it kept (exact in float32 for these lengths).
CHUNK_TAG = 2048


def _peaks_of(beat, downbeat) -> tuple[list[float], list[float]]:
    import torch
    from beat_this.model.postprocessor import Postprocessor

    b, d = Postprocessor(type="minimal")(torch.from_numpy(beat), torch.from_numpy(downbeat))
    return [float(t) for t in b], [float(t) for t in d]


def _hand_logits() -> list[tuple[str, list[float], list[float]]]:
    """Logits made by hand for the postprocessor's edges: [what, beat, downbeat]."""
    lo = -2.0

    def at(n: int, peaks: dict[int, float]) -> list[float]:
        return [peaks.get(t, lo) for t in range(n)]

    inf = float("inf")
    return [
        ("none above 0", [-1.0, -0.5, -3.0], [-1.0, -1.0, -1.0]),
        ("exactly 0 is no peak", [0.0, 0.0, 0.0, 0.0], [0.0, -1.0, 0.0, -1.0]),
        ("-1000 and a huge logit", [-1000.0, 1e30, -1000.0], [-1000.0, -1000.0, 1e30]),
        ("+inf", [1.0, inf, 1.0, -1.0], [inf, -1.0, -1.0, inf]),
        ("peaks at the edges", at(20, {0: 1.0, 19: 2.0}), at(20, {0: 1.0, 19: 1.0})),
        ("twin peaks: their mean", at(30, {10: 1.5, 11: 1.5}), at(30, {10: 1.5, 11: 1.5})),
        ("plateaus of 3, 4 and 5", at(60, {**{t: 1.0 for t in range(5, 8)}, **{t: 2.0 for t in range(20, 24)},
                                         **{t: 3.0 for t in range(40, 45)}}), at(60, {})),
        ("equal peaks 4 apart", at(20, {5: 1.0, 9: 1.0}), at(20, {9: 1.0})),
        ("a smaller peak within 3 frames", at(20, {5: 1.0, 8: 0.5, 12: 0.5}), at(20, {})),
        ("a downbeat halfway between two beats", at(30, {0: 1.0, 2: 1.0, 10: 1.0, 20: 1.0}), at(30, {1: 1.0, 15: 1.0})),
        ("downbeats and no beat", at(20, {}), at(20, {3: 1.0, 12: 1.0})),
        ("two downbeats moved to one beat", at(40, {10: 1.0, 30: 1.0}), at(40, {8: 1.0, 13: 1.0, 31: 1.0})),
        ("a twin downbeat", at(40, {10: 1.0, 11: 1.0, 30: 1.0}), at(40, {10: 1.0, 11: 1.0})),
    ]


def _peak_settings() -> dict:
    """The minimal postprocessor's window and threshold, read from beat_this's code: max_pool1d's kernel, stride and
    padding, the logit a peak must pass, and deduplicate_peaks' width."""
    import inspect

    from beat_this.model import postprocessor

    source = inspect.getsource(postprocessor.Postprocessor.postp_minimal)
    pool = re.search(r"F\.max_pool1d\(pred_logits, (\d+), (\d+), (\d+)\)", source)
    above = re.search(r"pred_peaks = pred_peaks > (\d+)", source)
    width = re.search(r"deduplicate_peaks\(beat_frame, width=(\d+)\)",
                      inspect.getsource(postprocessor.Postprocessor._postp_minimal_item))
    assert pool and above and width, "beat_this's minimal postprocessor isn't written as it was"
    kernel, stride, padding = (int(g) for g in pool.groups())
    return {"pool": {"kernel": kernel, "stride": stride, "padding": padding}, "above": int(above.group(1)),
            "width": int(width.group(1))}


def peaks_records() -> list[dict]:
    """peaks.jsonl's records: beat_this's minimal postprocessor (``Postprocessor(type="minimal")``, as File2Beats runs
    it with dbn=False) over logits of no model."""
    import numpy as np
    import torch

    from helpers.autochords_reference import array

    records: list[dict] = [{
        "kind": "meta", "postprocessor": "minimal", "fps": beat_this_settings()["fps"], **_peak_settings(),
        "logits": "int8: base64 of a q a frame, the logit q * scale in float32; float32: base64 of little-endian values",
        "libraries": {"numpy": np.__version__, "torch": torch.__version__},
    }]

    def record(what: str, beat, downbeat, coded: tuple[dict, dict]) -> None:
        beats, downbeats = _peaks_of(beat, downbeat)
        records.append({"kind": "peaks", "what": what, "beat": coded[0], "downbeat": coded[1], "beats": beats,
                        "downbeats": downbeats})

    for n in PEAK_LENGTHS:
        rng = np.random.default_rng(n)
        qb = rng.integers(-24, 25, n).astype(np.int8)
        qd = rng.integers(-40, 17, n).astype(np.int8)
        beat, downbeat = (q.astype(np.float32) * np.float32(0.125) for q in (qb, qd))
        record(f"quantized, seed {n}", beat, downbeat,
               ({**array(qb, "int8"), "scale": 0.125}, {**array(qd, "int8"), "scale": 0.125}))
    for n in PEAK_CONTINUOUS:
        rng = np.random.default_rng(1000 + n)
        beat = rng.normal(-1.0, 2.0, n).astype(np.float32)
        downbeat = rng.normal(-2.0, 2.0, n).astype(np.float32)
        record(f"continuous, seed {1000 + n}", beat, downbeat, (array(beat), array(downbeat)))
    for what, b, d in _hand_logits():
        beat, downbeat = np.array(b, np.float32), np.array(d, np.float32)
        record(what, beat, downbeat, (array(beat), array(downbeat)))
    return records


def _chunk_answer(n: int, size: int, border: int) -> list[int]:
    """One length's row of chunks.jsonl's table: [n, k, k starts, k lengths, m, m runs of 4]."""
    import torch
    from beat_this.inference import aggregate_prediction, split_piece

    chunks, starts = split_piece(torch.zeros(n, 1), size, border_size=border, avoid_short_end=True)
    lengths = [len(c) for c in chunks]
    preds = [torch.arange(i * CHUNK_TAG, i * CHUNK_TAG + length, dtype=torch.float32)
             for i, length in enumerate(lengths)]
    beat, downbeat = aggregate_prediction([{"beat": p, "downbeat": p} for p in preds], starts, n, size, border,
                                          "keep_first", "cpu")
    assert torch.equal(beat, downbeat)
    runs: list[list[int]] = []
    for f, v in enumerate(int(x) for x in beat.tolist()):
        chunk, at = (-1, -1) if v == -1000 else divmod(v, CHUNK_TAG)
        last = runs[-1] if runs else None
        if last and last[1] == f and last[2] == chunk and (chunk < 0 or last[3] + (f - last[0]) == at):
            last[1] = f + 1
        else:
            runs.append([f, f + 1, chunk, at])
    starts = [int(s) for s in starts]
    return [n, len(starts), *starts, *lengths, len(runs), *(x for r in runs for x in r)]


def chunks_records() -> list[dict]:
    """chunks.jsonl's records: beat_this's ``split_piece`` (``avoid_short_end``) and ``aggregate_prediction``
    (``keep_first``), as ``split_predict_aggregate`` runs them for Spect2Frames, over every piece of 0 to
    ``CHUNK_FRAMES`` frames."""
    import zlib

    import numpy as np
    import torch

    from caracole.autochords.export import BEATS_CHUNK

    border = beat_this_settings()["border"]
    records: list[dict] = [{
        "kind": "meta", "chunk": BEATS_CHUNK, "border": border, "avoid_short_end": True, "overlap_mode": "keep_first",
        "tag": CHUNK_TAG,
        "table": "int32 little-endian, deflated (zlib), in base64; a length's row: n, k, the k chunks' starts, their "
                 "lengths, m, then m runs (from, until, chunk, frame): frames [from, until) of the piece keep that "
                 "chunk's predictions from that frame on (chunk -1: none kept, -1000). aggregate_prediction was given "
                 "chunk i's frame j as i * tag + j",
        "libraries": {"numpy": np.__version__, "torch": torch.__version__},
    }]
    for first in range(0, CHUNK_FRAMES + 1, CHUNK_BLOCK):
        last = min(first + CHUNK_BLOCK, CHUNK_FRAMES + 1)
        table = [x for n in range(first, last) for x in _chunk_answer(n, BEATS_CHUNK, border)]
        data = np.asarray(table, dtype="<i4").tobytes()
        records.append({"kind": "lengths", "from": first, "until": last, "count": len(table),
                        "table": base64.b64encode(zlib.compress(data, 9)).decode("ascii")})
    return records


# scores.jsonl's reference calls, mir_eval's own steps of ``mir_eval.chord.evaluate`` and ``mir_eval.beat.evaluate``
# for the two scores the gates read: WCSR by a comparison rule, and beat F at a window (and after trim_beats, as
# beat.evaluate trims, its 5 s: a record has both, Scores.beatF being f_measure alone).
def mir_eval_wcsr(ref: list, est: list, rule: str) -> float:
    import numpy as np
    from mir_eval import chord, util

    ref_intervals = np.array([[s, e] for s, e, _ in ref], dtype=float)
    est_intervals = np.array([[s, e] for s, e, _ in est], dtype=float).reshape(-1, 2)
    est_intervals, est_labels = util.adjust_intervals(est_intervals, [lab for *_, lab in est], ref_intervals.min(),
                                                      ref_intervals.max(), chord.NO_CHORD, chord.NO_CHORD)
    intervals, ref_labels, est_labels = util.merge_labeled_intervals(ref_intervals, [lab for *_, lab in ref],
                                                                     est_intervals, est_labels)
    durations = util.intervals_to_durations(intervals)
    return float(chord.weighted_accuracy(getattr(chord, rule)(ref_labels, est_labels), durations))


def mir_eval_beat_f(ref: list[float], est: list[float], window: float, trim: float | None = None) -> float:
    import numpy as np
    from mir_eval import beat

    ref_beats, est_beats = np.array(ref, dtype=float), np.array(est, dtype=float)
    if trim is not None:
        ref_beats, est_beats = beat.trim_beats(ref_beats, trim), beat.trim_beats(est_beats, trim)
    return float(beat.f_measure(ref_beats, est_beats, window))


WCSR_RULES = ("majmin", "tetrads")
BEAT_TRIM = 5.0


def numpy_sum(values: list[float]) -> float:
    """numpy's float64 ``np.sum`` of a contiguous array, as Scores ports it: 0.0 plus numpy's pairwise sum (blocks of
    under 8 summed in turn, up to 128 by eight running sums, longer ones halved at a multiple of 8)."""

    def pairwise(i: int, n: int) -> float:
        if n < 8:
            r = -0.0
            for k in range(n):
                r += values[i + k]
            return r
        if n <= 128:
            r = [values[i + j] for j in range(8)]
            k = 8
            while k < n - n % 8:
                for j in range(8):
                    r[j] += values[i + k + j]
                k += 8
            s = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
            while k < n:
                s += values[i + k]
                k += 1
            return s
        half = n // 2
        half -= half % 8
        return pairwise(i, half) + pairwise(i + half, n - half)

    return 0.0 + pairwise(0, len(values))


def _song(rng, n: int, names: list[str], start: float = 0.0) -> list[list]:
    t, out = start, []
    for _ in range(n):
        d = round(float(rng.choice([0.093, 0.185, 0.5, 1.0, 1.852, 2.5, 4.0])), 3)
        out.append([t, round(t + d, 3), str(rng.choice(names))])
        t = round(t + d, 3)
    return out


def _estimate(rng, ref: list[list], names: list[str]) -> list[list]:
    """ref heard otherwise: boundaries moved by up to two frames, a label in eight another."""
    out = []
    for s, e, lab in ref:
        out.append([s, e, str(rng.choice(names)) if rng.random() < 0.125 else lab])
    for k in range(1, len(out)):
        moved = round(out[k][0] + float(rng.integers(-2, 3)) * 0.093, 3)
        if out[k - 1][0] < moved < out[k][1]:
            out[k - 1][1] = out[k][0] = moved
    return out


def _wcsr_cases() -> list[tuple[str, list, list]]:
    import numpy as np

    from caracole.autochords import btc

    names = btc.vocabulary(170)
    flats = [btc._FLATS.get(lab.partition(":")[0], "") + lab[2:] for lab in names if lab[1:2] == "#"]
    cases: list[tuple[str, list, list]] = []
    for seed, n in ((1, 4), (2, 30), (3, 30), (4, 200)):
        rng = np.random.default_rng(seed)
        ref = _song(rng, n, names)
        cases.append((f"seed {seed}, {n} chords", ref, _estimate(rng, ref, names + flats)))
    rng = np.random.default_rng(5)
    ref = _song(rng, 12, ["C", "A:min", "F", "G", "N", "E:min7", "D:7"])
    end = ref[-1][1]
    cases += [
        ("the same", ref, [list(s) for s in ref]),
        ("an estimate that ends early", ref, [s for s in ref if s[1] <= end / 2]),
        ("an estimate that starts late", ref, [s for s in ref if s[0] >= end / 3]),
        ("an estimate longer either side", ref, [[0.0, 0.5, "G"]] + [[s + 0.5, e + 0.5, lab] for s, e, lab in ref]
         + [[end + 0.5, end + 9.0, "C"]]),
        ("an estimate wholly after the reference", ref, [[end + 1.0, end + 3.0, "C"]]),
        ("an empty estimate", ref, []),
        ("sharps against flats", [[0.0, 2.0, "A#"], [2.0, 4.0, "D#:min7"], [4.0, 5.0, "C#:maj7"]],
         [[0.0, 2.0, "Bb"], [2.0, 4.0, "Eb:min7"], [4.0, 5.0, "Db:7"]]),
        ("no chord on both sides", [[0.0, 1.0, "N"], [1.0, 3.0, "C"], [3.0, 4.0, "N"]],
         [[0.0, 1.5, "N"], [1.5, 4.0, "C"]]),
        ("X and chords outside major and minor", [[0.0, 1.0, "X"], [1.0, 2.0, "C:dim"], [2.0, 3.0, "C:sus4"],
                                                  [3.0, 4.0, "C:aug"], [4.0, 5.0, "C:hdim7"], [5.0, 6.0, "C:7"],
                                                  [6.0, 7.0, "C:maj6"], [7.0, 8.0, "C:min7"]],
         [[0.0, 1.0, "X"], [1.0, 2.0, "C:dim"], [2.0, 3.0, "C"], [3.0, 4.0, "C"], [4.0, 5.0, "C:min"],
          [5.0, 6.0, "C"], [6.0, 7.0, "C:maj7"], [7.0, 8.0, "C:minmaj7"]]),
        ("nothing comparable", [[0.0, 1.0, "X"], [1.0, 2.0, "C:sus2"]], [[0.0, 2.0, "C"]]),
        ("an estimate of X", [[0.0, 1.0, "C"], [1.0, 2.0, "N"]], [[0.0, 2.0, "X"]]),
        ("zero-length intervals", [[0.0, 1.0, "C"], [1.0, 1.0, "G"], [1.0, 2.0, "A:min"], [2.0, 2.0, "F"]],
         [[0.0, 0.0, "D"], [0.0, 1.0, "C"], [1.0, 1.0, "E"], [1.0, 2.0, "A:min"]]),
        ("a reference of no length", [[3.0, 3.0, "C"]], [[0.0, 5.0, "C"]]),
        ("not a chord label", [[0.0, 1.0, "C"]], [[0.0, 1.0, "Cm"]]),
    ]
    return cases


def _beat_cases() -> list[tuple[str, list[float], list[float], float]]:
    import numpy as np

    cases: list[tuple[str, list[float], list[float], float]] = []
    for seed in (1, 2, 3):
        rng = np.random.default_rng(seed)
        ref = [round(0.3 + 0.5 * k, 2) for k in range(60)]
        est = sorted(round(t + float(rng.normal(0.0, 0.04)), 2) for t in ref if rng.random() > 0.1)
        est += [round(float(t), 2) for t in rng.uniform(0.0, 30.0, 4)]
        cases.append((f"seed {seed}", ref, sorted(est), 0.07))
    beats = [6.0, 6.5, 7.0, 7.5]
    cases += [
        ("both empty", [], [], 0.07),
        ("no reference beat", [], beats, 0.07),
        ("no estimated beat", beats, [], 0.07),
        ("before 5 s alone", [1.0, 2.0, 3.0], [1.0, 2.0, 3.05], 0.07),
        ("across 5 s", [4.0, 4.98, 5.0, 5.5], [4.0, 4.99, 5.01, 5.5], 0.07),
        ("at the window's edges", [6.0, 7.0, 8.0, 9.0, 10.0], [6.07, 6.93, 8.07000001, 9.0699999, 10.07], 0.07),
        ("duplicates", [6.0, 6.0, 7.0], [6.0, 7.0, 7.0, 7.0], 0.07),
        ("each estimate within reach of two beats", [6.0, 6.1, 6.2], [6.05, 6.15, 6.25], 0.07),
        ("the same", beats, beats, 0.07),
        ("a window of 0", beats, [6.0, 6.5000001, 7.0], 0.0),
        ("a window of half a second", beats, [5.6, 6.9], 0.5),
    ]
    return cases


def _beat_defaults() -> dict:
    """mir_eval's own defaults, which Scores' are held to: f_measure's window and trim_beats' least time."""
    import inspect

    from mir_eval import beat

    return {"window": inspect.signature(beat.f_measure).parameters["f_measure_threshold"].default,
            "min_beat_time": inspect.signature(beat.trim_beats).parameters["min_beat_time"].default}


def scores_records() -> list[dict]:
    """scores.jsonl's records: ``mir_eval_wcsr`` (each rule of ``WCSR_RULES``; where mir_eval.chord.evaluate takes
    the case, its score the same) and ``mir_eval_beat_f`` (untrimmed, and trimmed at ``BEAT_TRIM``), each answer or
    the name of what it raised; and ``numpy_sum`` held to np.sum on seeded arrays of every length to 300."""
    import warnings

    import mir_eval
    import numpy as np

    rng = np.random.default_rng(42)
    for n in [*range(300), 1000, 5000]:
        a = rng.uniform(0.0, 1.0, n) ** 3 * 10.0 ** rng.uniform(-5.0, 5.0, n)
        assert numpy_sum(a.tolist()) == float(np.sum(a)), n
    records: list[dict] = [{
        "kind": "meta", "rules": list(WCSR_RULES), "trim": BEAT_TRIM, **_beat_defaults(),
        "wcsr": "mir_eval.util.adjust_intervals of the estimate to the reference's span with N, "
                "merge_labeled_intervals, intervals_to_durations, then chord.weighted_accuracy of chord.<rule>",
        "beat": "beat.f_measure(ref, est, window); f_trimmed: of beat.trim_beats of each, at trim",
        "libraries": {"mir_eval": mir_eval.__version__, "numpy": np.__version__},
    }]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for what, ref, est in _wcsr_cases():
            record: dict = {"kind": "wcsr", "what": what, "ref": ref, "est": est}
            for rule in WCSR_RULES:
                try:
                    score = mir_eval_wcsr(ref, est, rule)
                except Exception as e:  # noqa: BLE001 - its name is the answer
                    record[rule] = {"raises": type(e).__name__}
                    continue
                record[rule] = score
                try:
                    evaluated = mir_eval.chord.evaluate(
                        np.array([r[:2] for r in ref], float), [r[2] for r in ref],
                        np.array([r[:2] for r in est], float).reshape(-1, 2), [r[2] for r in est])
                except Exception:  # noqa: BLE001 - evaluate's segmentation scores refuse some of the edges
                    continue
                assert evaluated[rule] == score, (what, rule)
            records.append(record)
        for what, ref, est, window in _beat_cases():
            records.append({"kind": "beat", "what": what, "ref": ref, "est": est, "window": window,
                            "f": mir_eval_beat_f(ref, est, window),
                            "f_trimmed": mir_eval_beat_f(ref, est, window, BEAT_TRIM)})
        for what, ref, est in (("unsorted", [6.0, 5.5], [6.0]), ("past mir_eval's MAX_TIME", [6.0], [30000.5])):
            try:
                mir_eval_beat_f(ref, est, 0.07)
            except ValueError as e:
                records.append({"kind": "beat", "what": what, "ref": ref, "est": est, "window": 0.07,
                                "raises": type(e).__name__})
            else:
                raise AssertionError(what)
    return records


def scores_json() -> str:
    """scores.json: the tables Scores reads, mir_eval's own: its pitch classes, its qualities' bitmaps, its no-chord
    and unknown labels, its beats' MAX_TIME."""
    import mir_eval

    doc = {"mir_eval": mir_eval.__version__, "no_chord": mir_eval.chord.NO_CHORD, "x_chord": mir_eval.chord.X_CHORD,
           "pitch_classes": dict(mir_eval.chord.PITCH_CLASSES),
           "qualities": {q: list(bits) for q, bits in mir_eval.chord.QUALITIES.items()},
           "max_time": float(mir_eval.beat.MAX_TIME)}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def _around() -> None:
    if not _installed(*AROUND_LIBS) or not _imports(*AROUND_LIBS):
        pytest.skip("needs numpy, torch, beat_this and mir_eval: nix develop .#autochords")


@pytest.mark.autochords
def test_peaks_vectors():
    _around()
    check(AREA / "peaks.jsonl", jsonl(peaks_records(), corpus="autochords/peaks", made_by=MADE_BY))


@pytest.mark.autochords
def test_chunks_vectors():
    _around()
    check(AREA / "chunks.jsonl", jsonl(chunks_records(), corpus="autochords/chunks", made_by=MADE_BY))


@pytest.mark.autochords
def test_scores_vectors_and_json():
    _around()
    check(AREA / "scores.jsonl", jsonl(scores_records(), corpus="autochords/scores", made_by=MADE_BY))
    check(MODELS_DATA / "scores.json", scores_json())


_TEXTS = """
import pathlib, sys
sys.path[:0] = ["tests"]
import test_conformance_autochords_models as m
out = pathlib.Path(sys.argv[1])
for name, text in zip(("frontend.jsonl", "models.jsonl"), m._texts()):
    (out / name).write_text(text, encoding="utf-8")
"""


def _fresh_texts(**env: str) -> tuple[str, ...]:
    """frontend.jsonl's and models.jsonl's texts as a fresh process writes them, under [env] besides this one's.

    Never this process's. The fresh process is a canonicalisation: the records are beat_this at 1 thread in a
    process that ran nothing before them, whatever the tests' order and their workers'. beat_this's logits move in
    their last bits (up to 1.2e-5; its beats, BTC and the frontend never) once the same process has run beat_this
    over real audio first, as test_autochords_run's real-model tests do, and the same sequence gives the same bits.
    The cause isn't found, only narrowed (2026-11-26, the failing order reproduced in one process): a first run of
    real audio through beats.py's cached ``_tracker`` moves them, at 1 thread as at 24, and ``_tracker.cache_clear()``
    after it, before the records, puts them back; but a separate File2Beats run of real audio first moves them too,
    kept alive or let go. (1500 frames of zeros at 8 threads through the cached tracker, then the cache cleared, moved
    nothing, as real audio does once the cache is cleared: so it shows nothing of zeros.) So it is no cached object
    nor thread count alone, and a cache_clear in the reference would close one way in of several."""
    return _child_texts(_TEXTS, ("frontend.jsonl", "models.jsonl"), **env)


def _child_texts(script: str, names: tuple[str, ...], **env: str) -> tuple[str, ...]:
    """The files [names] that [script], run in a fresh process with a temporary folder as its argument, writes."""
    with tempfile.TemporaryDirectory() as tmp:
        done = subprocess.run([sys.executable, "-c", script, tmp], cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": subprocess_pythonpath(ROOT / "src"), **env})
        assert done.returncode == 0, f"the records' child failed:\n{done.stderr}"
        return tuple((Path(tmp) / name).read_text(encoding="utf-8") for name in names)


@pytest.mark.autochords
def test_two_processes_of_other_hash_seeds_write_the_same_records(_models):
    if _committed_meta() and _committed_meta().get("cpu_capability") != cpu_capability():
        pytest.skip("the records were made on another CPU's kernels: test_frontend_and_models_vectors says why")
    want = [(AREA / name).read_text(encoding="utf-8") for name in ("frontend.jsonl", "models.jsonl")]
    frontend_json = (MODELS_DATA / "frontend.json").read_text(encoding="utf-8")
    for seed in ("0", "4242"):
        got = _fresh_texts(PYTHONHASHSEED=seed)
        assert [hashlib.sha256(t.encode()).digest() for t in got] == \
            [hashlib.sha256(t.encode()).digest() for t in want], f"PYTHONHASHSEED={seed}"
        (data,) = _child_texts(_FRONTEND_JSON, ("frontend.json",), PYTHONHASHSEED=seed)
        assert data == frontend_json, f"frontend.json, PYTHONHASHSEED={seed}"
