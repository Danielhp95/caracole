"""The separator: demucs-rs run as a program (a fake one here, written to ``tmp_path``), and the frame energies."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from caracole.autochords.separate import DemucsSeparator, SeparatorFailed

FAKE = '''#!{python}
import json, os, sys
from pathlib import Path

here = Path(__file__).resolve().parent
argv = sys.argv[1:]
(here / "call.json").write_text(json.dumps({{
    "argv": argv,
    "cache": os.environ.get("XDG_CACHE_HOME"),
    "config": os.environ.get("XDG_CONFIG_HOME"),
    "model": str((Path(os.environ["XDG_CACHE_HOME"]) / "demucs-rs" / "htdemucs.safetensors").resolve()),
}}))
mode = {mode!r}
if mode == "fail":
    print("loading model", file=sys.stderr)
    print("thread 'main' panicked: No possible adapter", file=sys.stderr)
    sys.exit(101)
if mode == "write":
    out = Path(argv[argv.index("-o") + 1]) / "vocals.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"RIFF")
'''


def _fake(tmp_path: Path, mode: str) -> Path:
    script = tmp_path / "bin" / "demucs"
    script.parent.mkdir(exist_ok=True)
    script.write_text(FAKE.format(python=sys.executable, mode=mode), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _separator(tmp_path: Path, mode: str) -> tuple[DemucsSeparator, Path]:
    model = tmp_path / "htdemucs.safetensors"
    model.write_bytes(b"weights")
    return DemucsSeparator(str(_fake(tmp_path, mode)), model, tmp_path / "cache"), model


def test_demucs_runs_on_the_audio_with_its_model_linked_and_its_autotune_cache_kept(tmp_path):
    separator, model = _separator(tmp_path, "write")
    workdir = tmp_path / "work"
    workdir.mkdir()
    audio = tmp_path / "song.m4a"
    audio.write_bytes(b"x")

    stem = separator.vocals(audio, workdir)

    call = json.loads((tmp_path / "bin" / "call.json").read_text())
    assert call["argv"] == ["-m", "htdemucs", "-s", "vocals", "-o", str(workdir / "stems"), str(audio)]
    assert call["cache"] == str(workdir / "cache")
    assert Path(call["model"]) == model.resolve()
    assert call["config"] == str(tmp_path / "cache" / "demucs-rs")
    assert stem == workdir / "stems" / "vocals.wav"
    assert stem.is_file()


def test_a_demucs_that_fails_raises_separator_failed_with_its_last_line(tmp_path):
    separator, _ = _separator(tmp_path, "fail")
    with pytest.raises(SeparatorFailed, match="No possible adapter"):
        separator.vocals(tmp_path / "song.m4a", tmp_path)


def test_a_demucs_that_writes_no_stem_raises_separator_failed(tmp_path):
    separator, _ = _separator(tmp_path, "nothing")
    with pytest.raises(SeparatorFailed, match="vocals.wav"):
        separator.vocals(tmp_path / "song.m4a", tmp_path)
