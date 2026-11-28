"""tests/helpers/autochords_reference.py's names for the references it writes, which go to a phone's shared storage.

Its models' half needs the auto-chords environment (test_conformance_autochords_models.py); its names need nothing.
"""

from __future__ import annotations

import pytest

from helpers.autochords_reference import (
    MODELS_VECTORS, Reference, argmax_runs, lengths_disagree, main, reference_name,
)


@pytest.mark.parametrize(("audio", "want"), [
    ("Nobody - River Road.flac", "Nobody - River Road.json"),
    # The phone's shared storage refuses a colon (adb push: "remote couldn't create file"), and these with it.
    ("2026-06-01_20:12:10 to 20:19:30.wav", "2026-06-01_20-12-10 to 20-19-30.json"),
    ('a<b>c"d|e?f*g\\h.mp3', "a-b-c-d-e-f-g-h.json"),
    ("tab\there.ogg", "tab-here.json"),
])
def test_a_references_name_is_its_audios_stem_with_what_shared_storage_refuses_made_a_hyphen(audio, want):
    assert reference_name(audio) == want


@pytest.mark.parametrize("names", [("a:b.wav", "a-b.wav"), ("x.flac", "x.mp3")])
def test_two_audio_files_of_one_references_name_are_refused_before_any_is_read(names, tmp_path, capsys):
    given, out = tmp_path / "in", tmp_path / "out"
    given.mkdir()
    for name in names:
        (given / name).write_bytes(b"not audio: nothing is read")
    assert main([str(given), str(out)]) == 2
    assert not out.exists()
    said = capsys.readouterr().err
    assert all(name in said for name in names) and reference_name(names[0]) in said


def _ref(decoded_s: float, mel_s: float, duration: float | None) -> Reference:
    return Reference(decoded=[0.0] * round(decoded_s * 22050), features=None, logits=None, segments=[],
                     mel=[[0.0]] * round(mel_s * 50), beat_logits=(None, None), beats=[], downbeats=[],
                     duration=duration)


@pytest.mark.parametrize(("lengths", "said"), [
    ((240.0, 240.02, 240.0), None),
    ((240.0, 240.02, None), None),
    ((240.0, 240.02, 130.0), "its duration, 130.000 s"),  # mutagen's guess of a headerless MP3, as it was
    ((70.0, 240.0, 240.0), "its decoded samples, 70.000 s"),  # libsndfile's decode cut short
    ((240.0, 70.0, 240.0), "its mel's frames, 70.000 s"),
])
def test_a_reference_whose_lengths_disagree_says_which(lengths, said):
    found = lengths_disagree(_ref(*lengths))
    assert found is None if said is None else said in found


def test_two_lengths_that_disagree_with_no_duration_name_neither_as_the_odd_one_out():
    said = lengths_disagree(_ref(70.0, 240.02, None))
    assert said == ("its decoded samples, 70.000 s, and its mel's frames, 240.020 s, disagree (more than 0.1 s); "
                    "it has no duration to tell which is right")


def test_a_reference_whose_lengths_disagree_is_never_written(tmp_path, monkeypatch, capsys):
    import helpers.autochords_reference as module

    given, out = tmp_path / "in", tmp_path / "out"
    given.mkdir()
    for name in ("good.mp3", "bad.mp3"):
        (given / name).write_bytes(b"read by the reference below")
    monkeypatch.setattr(module, "reference", lambda path, **kw: _ref(10.0, 10.02, 10.0 if path.stem == "good" else 5.6))
    monkeypatch.setattr(module, "encoded", lambda ref: {"segments": [], "beats": []})
    assert main([str(given), str(out)]) == 1
    assert sorted(p.name for p in out.iterdir()) == ["good.json"]
    said = capsys.readouterr().err
    assert "bad.mp3" in said and "not written" in said and "5.600 s" in said


def _heard(decoded_s: float, duration: float | None, logits) -> Reference:
    return Reference(decoded=[0.0] * round(decoded_s * 22050), features=None, logits=logits,
                     segments=[[0.0, 0.278, "C"]], mel=[[0.0]] * round(decoded_s * 50), beat_logits=(None, None),
                     beats=[0.5, 1.0], downbeats=[0.5], duration=duration)


def test_argmax_runs_are_each_frames_first_highest_class_as_runs():
    logits = [[0.0, 2.0, 2.0], [0.0, 3.0, 1.0], [5.0, 5.0, 0.0], [1.0, 0.0, 0.0]]
    assert argmax_runs(logits) == [[1, 2], [0, 2]]


def test_the_folders_hearings_are_the_corpus_records_with_the_committed_gates(tmp_path, monkeypatch, capsys):
    import hashlib
    import json

    import helpers.autochords_reference as module

    given, out = tmp_path / "in", tmp_path / "out"
    given.mkdir()
    (given / "a: song.mp3").write_bytes(b"read by the reference below")
    (given / "notes.txt").write_bytes(b"no audio: left alone")
    seen = []

    def fake(path, **kw):
        seen.append((path.name, kw))
        return _heard(2.0, 2.0, [[0.0, 1.0]] * 3 + [[1.0, 0.0]])

    monkeypatch.setattr(module, "reference", fake)
    assert main(["--hearings", str(given), str(out)]) == 0
    assert seen == [("a: song.mp3", {"threads": 1})]
    assert sorted(p.name for p in out.iterdir()) == ["a- song.hearing.json", "meta.json"]
    record = json.loads((out / "a- song.hearing.json").read_text(encoding="utf-8"))
    assert record == {
        "kind": "hearing", "duration": 2.0,
        "file": {"name": "a: song.mp3", "sha256": hashlib.sha256(b"read by the reference below").hexdigest()},
        "btc": {"samples": 44100, "frames": 4, "argmax": [[1, 3], [0, 1]], "segments": [[0.0, 0.278, "C"]]},
        "beats": {"frames": 100, "beats": [0.5, 1.0], "downbeats": [0.5]},
    }
    # The corpus's own hearing records have the same keys, all the way down.
    committed = [json.loads(line) for line in MODELS_VECTORS.read_text(encoding="utf-8").splitlines()[1:]]
    corpus = next(r for r in committed if r.get("kind") == "hearing")
    assert record.keys() == corpus.keys() and record["file"]["name"] == "a: song.mp3"
    assert all(record[k].keys() == corpus[k].keys() for k in ("btc", "beats"))
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["gates"] == committed[0]["gates"]
    assert meta["gates"]["end_to_end"]["wcsr_majmin_min"] == 0.99


def test_a_hearing_whose_lengths_disagree_is_never_written_and_two_of_one_name_are_refused(tmp_path, monkeypatch,
                                                                                           capsys):
    import helpers.autochords_reference as module

    given, out = tmp_path / "in", tmp_path / "out"
    given.mkdir()
    for name in ("good.mp3", "bad.m4a"):
        (given / name).write_bytes(b"read by the reference below")
    monkeypatch.setattr(module, "reference",
                        lambda path, **kw: _heard(10.0, 10.0 if path.stem == "good" else 5.6, [[1.0]]))
    assert main(["--hearings", str(given), str(out)]) == 1
    assert sorted(p.name for p in out.iterdir()) == ["good.hearing.json", "meta.json"]
    assert "bad.m4a: not written" in capsys.readouterr().err
    (given / "good.flac").write_bytes(b"its name is good.mp3's")
    assert main(["--hearings", str(given), str(tmp_path / "again")]) == 2
    assert not (tmp_path / "again").exists()
