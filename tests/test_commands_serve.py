"""``caracole serve``: its options, its access token, and what it imports on every start."""

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from caracole.cli import build_app
from caracole.web.security import session_value

from conftest import subprocess_pythonpath

TOKEN = "a-long-random-access-token"


def config(tmp_path: Path) -> Path:
    path = tmp_path / "caracole.toml"
    path.write_text(f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
                    f'cache_dir = "{tmp_path / "cache"}"\nmusic_dir = "{tmp_path / "music"}"\n', encoding="utf-8")
    return path


@pytest.fixture
def started(monkeypatch):
    """What `caracole serve` would serve, without listening."""
    seen = {}

    def serve(app, address, port, *, announce):
        seen.update(app=app, address=address, port=port)
        announce("listening")

    monkeypatch.setattr("caracole.web.server.serve", serve)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    return seen


def invoke(tmp_path, *args):
    return CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), "serve", *args])


def test_by_default_it_listens_on_this_machine_alone(tmp_path, started):
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert (started["address"], started["port"]) == ("127.0.0.1", 8737)
    app = started["app"]
    assert {"localhost", "127.0.0.1", "::1"} <= app.allowed
    assert app._session is None
    assert "listening" in result.output and "anyone" not in result.output


def test_the_page_it_serves_keeps_its_own_timers(tmp_path, started):
    # Only the tests that drive the page on real time shorten its timers (test_web_page.py's QUICK).
    result = invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert started["app"].timers is None


def test_options_set_the_address_port_names_and_token(tmp_path, started):
    token = tmp_path / "token"
    token.write_text(TOKEN + "\n", encoding="utf-8")
    result = invoke(tmp_path, "--address", "100.64.0.7", "--port", "9000", "--allow-host", "nuc.example.ts.net",
                    "--allow-host", "music.lan", "--token-file", str(token))
    assert result.exit_code == 0, result.output
    assert (started["address"], started["port"]) == ("100.64.0.7", 9000)
    app = started["app"]
    assert {"100.64.0.7", "nuc.example.ts.net", "music.lan"} <= app.allowed
    assert app._session == session_value(TOKEN)
    assert TOKEN not in result.output


def test_the_token_comes_from_systemds_credentials_by_default(tmp_path, started, monkeypatch):
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "web_token").write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(creds))
    assert invoke(tmp_path).exit_code == 0
    assert started["app"]._session == session_value(TOKEN)


def test_a_short_or_missing_token_is_refused(tmp_path, started):
    short = tmp_path / "short"
    short.write_text("hunter2", encoding="utf-8")
    result = invoke(tmp_path, "--token-file", str(short))
    assert result.exit_code == 2 and "16 characters" in result.output and not started
    result = invoke(tmp_path, "--token-file", str(tmp_path / "missing"))
    assert result.exit_code == 2 and "can't read" in result.output and not started


def test_a_host_name_that_isnt_one_exits_2(tmp_path, started):
    result = invoke(tmp_path, "--allow-host", "my nuc")
    assert result.exit_code == 2 and "--allow-host: 'my nuc' isn't a host name" in result.output
    assert not started


def test_listening_beyond_this_machine_without_a_token_warns(tmp_path, started):
    result = invoke(tmp_path, "--address", "0.0.0.0")
    assert result.exit_code == 0
    assert "warning: Listening on 0.0.0.0: anyone who can reach" in result.output


def test_an_address_it_cant_listen_on_exits_1(tmp_path, monkeypatch):
    def serve(app, address, port, *, announce):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr("caracole.web.server.serve", serve)
    result = invoke(tmp_path, "--port", "8737")
    assert result.exit_code == 1 and "can't listen on 127.0.0.1:8737: Address already in use" in result.output


@pytest.mark.slow
def test_registering_the_command_imports_no_server_code():
    code = "import sys; import caracole.cli; print(sorted(m for m in sys.modules if m.startswith('caracole.web')))"
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.strip() == "[]"
