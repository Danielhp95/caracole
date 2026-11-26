"""tests/helpers/autochords_reference.py's names for the references it writes, which go to a phone's shared storage.

Its models' half needs the auto-chords environment (test_conformance_autochords_models.py); its names need nothing.
"""

from __future__ import annotations

import pytest

from helpers.autochords_reference import main, reference_name


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
