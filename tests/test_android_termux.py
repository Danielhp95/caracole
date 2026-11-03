"""android/termux/setup.sh, caracole installed in Termux on a phone: its versions are docs/deploy.md's, and its steps
run in order, each stopping at its first failure, here against a fake Termux (a folder for $PREFIX and $HOME)."""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "android" / "termux" / "setup.sh"

# The package's own build runs the suite on a source tree of pyproject.toml, README.md, LICENSE, src/ and tests/.
if not (SCRIPT.is_file() and (ROOT / "docs" / "deploy.md").is_file()):
    pytest.skip("android/ and docs/ are not in this tree", allow_module_level=True)

DEPLOY = (ROOT / "docs" / "deploy.md").read_text(encoding="utf-8")


def block(name: str) -> str:
    """A variable the script sets to a quoted block of lines."""
    return re.search(rf"^{name}='(.*?)'$", SCRIPT.read_text(encoding="utf-8"), re.S | re.M).group(1)


def test_it_pins_the_versions_deploy_md_pins():
    constraints = DEPLOY[DEPLOY.index("# The Nix package's versions"):DEPLOY.index("# Auto-chords' (section 12).")]
    pinned = [line for line in constraints.splitlines() if "==" in line]
    assert block("CONSTRAINTS").splitlines() == pinned
    for name in ("CHORDPRO_SHA256", "FONTS_SHA256", "PDF_FONTS_SHA256"):
        for line in block(name).splitlines():
            assert line in DEPLOY, line  # each file's SHA-256 is deploy.md's


def test_it_is_a_posix_shell_script():
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)


@pytest.fixture
def termux(tmp_path):
    """A fake Termux: $PREFIX with its sh, $HOME, and a caracole already in ~/.caracole/venv."""
    prefix, home = tmp_path / "usr", tmp_path / "home"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "sh").symlink_to("/bin/sh")
    (prefix / "tmp").mkdir()
    venv = home / ".caracole" / "venv" / "bin"
    venv.mkdir(parents=True)
    fake = venv / "caracole"
    fake.write_text('#!/bin/sh\necho "caracole 0.1.0 $CARACOLE_PDF_FONTS $PERL5LIB"\n', encoding="utf-8")
    fake.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PREFIX": str(prefix), "TMPDIR": str(prefix / "tmp")}
    return prefix, home, env


@pytest.mark.slow
def test_the_wrapper_and_the_service_are_written_where_termux_reads_them(termux):
    prefix, home, env = termux
    for step in ("wrapper", "service"):
        done = subprocess.run(["sh", str(SCRIPT), "--step", step], env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr
    wrapper = home / ".caracole" / "bin" / "caracole"
    said = subprocess.run([str(wrapper), "--version"], env=env, capture_output=True, text=True, check=True).stdout
    assert said == f"caracole 0.1.0 {home}/.caracole/pdf-fonts {home}/.caracole/perl/lib/perl5\n"
    run = (prefix / "var" / "service" / "caracole" / "run").read_text(encoding="utf-8")
    assert run.startswith(f"#!{prefix}/bin/sh\n") and f"cat {home}/.caracole/address" in run
    assert 'serve --address "$address"' in run
    assert os.access(home / ".termux" / "boot" / "start-caracole", os.X_OK)
    assert "PATH=$HOME/.caracole/bin:$PATH" in (home / ".profile").read_text(encoding="utf-8")
    assert "wrapper: ok" in (home / "caracole-setup.log").read_text(encoding="utf-8")


@pytest.mark.slow
def test_a_step_that_fails_stops_there_and_says_what_to_send(termux):
    prefix, home, env = termux
    (home / ".caracole" / "venv" / "bin" / "caracole").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    done = subprocess.run(["sh", str(SCRIPT), "--step", "wrapper"], env=env, capture_output=True, text=True)
    assert done.returncode == 1
    assert "The step wrapper failed" in done.stderr and "caracole-setup.log" in done.stderr
    assert "wrapper: ok" not in (home / "caracole-setup.log").read_text(encoding="utf-8")
    bad = subprocess.run(["sh", str(SCRIPT), "--step", "nonsense"], env=env, capture_output=True, text=True)
    assert bad.returncode == 2 and "No step nonsense" in bad.stderr
