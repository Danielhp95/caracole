"""service.py and the CLI's guard: a caracole started on its home defaults, beside caracole's service, warns
before it writes or sends a request, and builds no index unless told ``--home``.

The service is told by its marker, /etc/caracole/service, which nix/module.nix and docs/deploy.md's Ubuntu units
write; here ``CARACOLE_SERVICE_FILE`` names one in tmp_path (conftest.py points it at no file for every other
test), and HOME a home in tmp_path, so nothing depends on the machine the tests run on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from caracole import service
from caracole.cli import build_app
from caracole.commands import _common
from caracole.config import load_config

SERVICE_STATE = "/var/lib/caracole/state"
SERVICE_LIBRARY = "/var/lib/caracole/library"


def marker(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "etc" / "caracole" / "service"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else
                    f'state_dir = "{SERVICE_STATE}"\nlibrary_dir = "{SERVICE_LIBRARY}"\n', encoding="utf-8")
    return path


# --- telling the service -----------------------------------------------------------------------------------------


def test_no_marker_no_service(tmp_path):
    assert service.find({"CARACOLE_SERVICE_FILE": str(tmp_path / "none")}) is None


def test_the_marker_names_the_services_folders(tmp_path):
    found = service.find({"CARACOLE_SERVICE_FILE": str(marker(tmp_path))})
    assert found == service.Service(tmp_path / "etc" / "caracole" / "service", Path(SERVICE_STATE),
                                    Path(SERVICE_LIBRARY))


def test_a_marker_that_wont_read_is_a_service_all_the_same(tmp_path):
    found = service.find({"CARACOLE_SERVICE_FILE": str(marker(tmp_path, "not = [toml"))})
    assert found is not None and found.state_dir is None and found.library_dir is None
    relative = service.find({"CARACOLE_SERVICE_FILE": str(marker(tmp_path, 'state_dir = "state"\n'))})
    assert relative is not None and relative.state_dir is None  # only an absolute path names a folder


def test_the_marker_is_etc_caracole_service_by_default():
    assert service.MARKER == Path("/etc/caracole/service")
    assert service.marker_path({}) == service.MARKER


def home_cfg(tmp_path):
    return load_config(None, env={"HOME": str(tmp_path / "home")})


def test_the_home_defaults_beside_a_service_are_elsewhere(tmp_path):
    env = {"CARACOLE_SERVICE_FILE": str(marker(tmp_path))}
    cfg = home_cfg(tmp_path)
    assert service.elsewhere(cfg, env, explicit=False) == service.find(env)
    assert service.elsewhere(cfg, env, explicit=True) is None  # --config, or CARACOLE_CONFIG: the service's own
    assert service.elsewhere(cfg, {"CARACOLE_SERVICE_FILE": str(tmp_path / "none")}, explicit=False) is None


def test_the_services_own_folders_are_no_elsewhere(tmp_path):
    cfg = home_cfg(tmp_path)
    env = {"CARACOLE_SERVICE_FILE": str(marker(tmp_path, f'state_dir = "{cfg.state_dir}"\n'))}
    assert service.elsewhere(cfg, env, explicit=False) is None


# --- the CLI -----------------------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A caracole on its home defaults (no --config, no CARACOLE_CONFIG) on a machine with a service."""
    for name in ("CARACOLE_CONFIG", "STATE_DIRECTORY", "CACHE_DIRECTORY", "XDG_STATE_HOME", "XDG_CACHE_HOME",
                 "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CARACOLE_SERVICE_FILE", str(marker(tmp_path)))
    monkeypatch.setattr(_common, "transport_for", lambda provider: pytest.fail(f"a client for {provider}"))
    return tmp_path / "home"


def invoke(*args: str):
    return CliRunner().invoke(build_app(), list(args))


BUILDS = [("run",), ("index", "build"), ("index", "refresh"), ("gtptabs",), ("musescore",), ("harptabs", "--index"),
          ("gametabs", "--index"), ("lacuerda", "--index")]


@pytest.mark.parametrize("words", BUILDS, ids=lambda w: " ".join(w))
def test_an_index_is_never_built_into_the_home_database_beside_a_service_unasked(home, words):
    result = invoke(*words)

    assert result.exit_code == 2, result.output
    said = " ".join(result.stderr.split())
    command = " ".join(words)
    assert f"`sudo caracole-admin {command}`" in said
    assert f"`caracole --home {command}`" in said
    assert str(home / ".local" / "state" / "caracole") in said and SERVICE_STATE in said
    assert not (home / ".local" / "state" / "caracole").exists()  # no database, no lock: nothing written


def test_home_says_build_it_here_all_the_same(home):
    result = invoke("--home", "index", "refresh")

    assert result.exit_code == 1  # past the guard: the home index is empty
    assert "The index is empty" in result.stderr
    assert "service" not in result.stderr
    assert (home / ".local" / "state" / "caracole" / "caracole.sqlite").exists()


def test_a_config_named_is_the_services_and_says_nothing(home, tmp_path):
    config = tmp_path / "caracole.toml"
    config.write_text(f'data_dir = "{tmp_path / "data"}"\n', encoding="utf-8")

    result = invoke("--config", str(config), "index", "refresh")

    assert result.exit_code == 1 and "The index is empty" in result.stderr
    assert "service" not in result.stderr


def test_caracole_config_in_the_environment_is_named_too(home, tmp_path, monkeypatch):
    config = tmp_path / "caracole.toml"
    config.write_text(f'data_dir = "{tmp_path / "data"}"\n', encoding="utf-8")
    monkeypatch.setenv("CARACOLE_CONFIG", str(config))  # as caracole-admin and the Ubuntu units set it

    result = invoke("index", "refresh")

    assert "service" not in result.stderr and "The index is empty" in result.stderr


def test_a_command_that_writes_warns_once_and_goes_on(home):
    result = invoke("sync")

    assert result.exit_code == 0, result.output
    [line] = [line for line in result.stderr.splitlines() if "service" in line]
    said = " ".join(line.split())
    assert "home" in said and str(home / "Tabs") in said and SERVICE_LIBRARY in said
    assert "`sudo caracole-admin sync`" in said


def test_add_warns_before_it_writes_its_line(home):
    result = invoke("add", "Soda Stereo - De Música Ligera")

    assert result.exit_code == 0, result.output
    assert result.stderr.count("sudo caracole-admin add") == 1
    assert (home / "Tabs" / "wanted.txt").exists()


def test_with_home_a_command_that_writes_says_nothing(home):
    result = invoke("--home", "sync")
    assert result.exit_code == 0 and "service" not in result.stderr


@pytest.mark.parametrize("words", [("index", "stats"), ("search", "creep"), ("songbook", "list"), ("backup", "--list")],
                         ids=lambda w: " ".join(w))
def test_a_command_that_only_reads_says_nothing(home, words):
    result = invoke(*words)
    assert "service" not in result.stderr, result.stderr


def test_without_a_service_the_home_defaults_say_nothing(home, monkeypatch, tmp_path):
    monkeypatch.setenv("CARACOLE_SERVICE_FILE", str(tmp_path / "none"))
    result = invoke("index", "refresh")
    assert result.exit_code == 1 and "The index is empty" in result.stderr and "service" not in result.stderr


def test_serve_on_the_home_defaults_runs_its_commands_with_home():
    from caracole.web.jobs import CaracoleRunner

    assert CaracoleRunner(None, home=True)._argv[-1] == "--home"
    assert "--home" not in CaracoleRunner(Path("/etc/caracole/caracole.toml"))._argv


def test_a_command_that_only_reads_leaves_no_warning_owed_to_the_next(home):
    invoke("index", "stats")
    assert _common._unwarned is None  # the next command of this process, or a caller of exclusive, owes none
