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
    # A real wgpu build with no Vulkan adapter: the cause, a hint, then the main thread's generic unwrap panic.
    sys.stderr.write("Loading model...\\n\\n"
        "thread 'demucs-main' (1) panicked at cubecl-wgpu-0.9.0/src/runtime.rs:395:14:\\n"
        "No possible adapter available for backend. Falling back to first available.: NotFound\\n"
        "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\\n\\n"
        "thread 'main' (2) panicked at demucs-cli/src/main.rs:82:10:\\n"
        "called `Result::unwrap()` on an `Err` value: Any {{ .. }}\\n")
    sys.exit(101)
if mode == "hang":
    import time
    time.sleep(30)
if mode in ("write", "crash_after_done", "abort_after_done", "crash_before_done", "done_exit_1"):
    out = Path(argv[argv.index("-o") + 1]) / "vocals.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"RIFF")
if mode in ("crash_after_done", "abort_after_done", "done_exit_1"):
    sys.stderr.write("Separating...\\n  Wrote " + str(out) + "\\nDone!\\n")
    sys.stderr.flush()
if mode == "abort_after_done":
    # As measured (Task 14): the driver's exit path says more after Done!, then glibc aborts.
    sys.stderr.write("NVVM compilation failed: 3\\ndouble free or corruption (out)\\n")
    sys.stderr.flush()
    import signal
    os.kill(os.getpid(), signal.SIGABRT)
if mode == "crash_before_done":
    sys.stderr.write("Separating...\\n")
    sys.stderr.flush()
if mode in ("crash_after_done", "crash_before_done"):
    import signal
    os.kill(os.getpid(), signal.SIGSEGV)
if mode == "done_exit_1":
    sys.exit(1)
'''


def _fake(tmp_path: Path, mode: str) -> Path:
    script = tmp_path / "bin" / "demucs"
    script.parent.mkdir(exist_ok=True)
    script.write_text(FAKE.format(python=sys.executable, mode=mode), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _separator(tmp_path: Path, mode: str, **kw) -> tuple[DemucsSeparator, Path]:
    model = tmp_path / "htdemucs.safetensors"
    model.write_bytes(b"weights")
    return DemucsSeparator(str(_fake(tmp_path, mode)), model, tmp_path / "cache", **kw), model


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


def test_a_demucs_that_hangs_is_stopped_and_raises_separator_failed(tmp_path):
    separator, _ = _separator(tmp_path, "hang", timeout=0.5)
    with pytest.raises(SeparatorFailed, match="longer than 0.5 s"):
        separator.vocals(tmp_path / "song.m4a", tmp_path)


def test_a_demucs_that_crashes_on_its_way_out_after_writing_the_vocals_has_separated_them(tmp_path, caplog):
    separator, _ = _separator(tmp_path, "crash_after_done")
    with caplog.at_level("WARNING"):
        stem = separator.vocals(tmp_path / "song.m4a", tmp_path)
    assert stem == tmp_path / "stems" / "vocals.wav" and stem.is_file()
    assert "SIGSEGV" in caplog.text


def test_a_demucs_that_aborts_with_more_said_after_done_has_separated_them_too(tmp_path, caplog):
    separator, _ = _separator(tmp_path, "abort_after_done")
    with caplog.at_level("WARNING"):
        stem = separator.vocals(tmp_path / "song.m4a", tmp_path)
    assert stem == tmp_path / "stems" / "vocals.wav" and stem.is_file()
    assert "SIGABRT" in caplog.text


def test_a_demucs_that_dies_by_a_signal_before_done_fails(tmp_path):
    separator, _ = _separator(tmp_path, "crash_before_done")
    with pytest.raises(SeparatorFailed, match="Separating"):
        separator.vocals(tmp_path / "song.m4a", tmp_path)


def test_a_demucs_that_says_done_but_exits_1_fails(tmp_path):
    separator, _ = _separator(tmp_path, "done_exit_1")
    with pytest.raises(SeparatorFailed):
        separator.vocals(tmp_path / "song.m4a", tmp_path)
