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
  - ``known``: the chords, beats and downbeats as synth_music.py played them.
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
  channels interleaved, ``interleaved_sha256``, which the phone's must equal), and its length by music.py
  ``read_audio`` (its frames counted for an MP3 that names none). Needs no model and no CPU's kernels.
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
# side, the first ``trim`` seconds left out), with no bound on its logits (None).
GATES = {
    "btc": {"argmax": "equal", "margin_under": 1e-3, "logits_max_abs": 1e-4},
    "beats_fp32": {"logits_max_abs": 1e-3},
    "beats_fp16": {"logits_max_abs": None, "f_measure_min": 0.99, "window": 0.07, "trim": 5.0},
}


# The design's B1 feature gate for the phone's front ends against frontend.jsonl's ``cqt`` and ``mel``, which its meta
# carries and AutochordsReplays reads back: the same frames, and each frame's cosine with the stored one at a median of
# ``cosine_median_min`` and a least of ``cosine_min``, over the frames that aren't silent. A frame is silent when every
# stored value lies within ``silent_within`` of its feature's floor (``floors``, which _records adds: the log-CQT's
# log(btc.LOG_FLOOR) as float32 makes it, the log-mel's log1p(0)); there the phone's frame must be silent too.
FRONTEND_GATES = {"frames": "equal", "cosine_median_min": 0.9999, "cosine_min": 0.999, "silent_within": 1e-3}
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
DECODE_FILES = (("decode.mp3", "MP3"), ("decode-headerless.mp3", "MP3"), ("decode.m4a", "M4A"),
                ("decode.ogg", "Ogg"), ("decode-opus.ogg", "Ogg"), ("decode.flac", "FLAC"), ("decode.wav", "WAV"),
                ("decode.aiff", "AIFF"))
# The design's B1 decode gate: no sample offset (by cross-correlation within ``offset_search`` samples either way),
# an SNR of ``snr_db_min`` or more against the computer's decode at the file's rate, and the length the phone states
# within ``length_within`` s of music.py read_audio's (its frames counted for an MP3 that names no length). Its
# decoded samples' count is held within ``decoded_within`` s of the computer's apart: read_audio's length is the
# container's, a LAME MP3's or an M4A's with the encoder's delay and padding that the decoders trim (0.06 s and 0.05 s
# here), so the computer's own decode is no nearer to it than that. The lossless forms are held closer: sample for
# sample (``exact``).
DECODE_GATES = {"offset": 0, "offset_search": 2048, "snr_db_min": 60.0, "length_within": 0.05, "decoded_within": 0.05}
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
        if form in _LOSSLESS:
            samples, _ = soundfile.read(path, dtype="float32", always_2d=True)
            record["exact"] = True
            record["interleaved_sha256"] = _sha256(samples)
        else:
            record["exact"] = False
            record["pcm16"] = _deltas(np.clip(np.round(y * 32768.0), -32768, 32767).astype(np.int16))
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
