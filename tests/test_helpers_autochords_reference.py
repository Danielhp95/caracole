"""tests/helpers/autochords_reference.py's names for the references it writes, which go to a phone's shared storage.

Its models' half needs the auto-chords environment (test_conformance_autochords_models.py); its names need nothing.
"""

from __future__ import annotations

import pytest

from helpers.autochords_reference import Reference, lengths_disagree, main, reference_name


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
