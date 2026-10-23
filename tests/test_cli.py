import sys
import types

import pytest
from typer.testing import CliRunner

from caracole import cli, logs


def test_version_option():
    result = CliRunner().invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "caracole 0.1.0" in result.output


def test_command_modules_are_discovered(monkeypatch):
    import typer

    fake = types.ModuleType("caracole.commands.zz_fake")

    def register(app: typer.Typer) -> None:
        @app.command("zz-hello")
        def hello() -> None:
            typer.echo("hello from plugin")

    fake.register = register
    monkeypatch.setitem(sys.modules, "caracole.commands.zz_fake", fake)
    app = cli.build_app(extra_modules=["caracole.commands.zz_fake"])
    result = CliRunner().invoke(app, ["zz-hello"])
    assert result.exit_code == 0, result.output
    assert "hello from plugin" in result.output


def test_config_option_is_stored_on_context(tmp_path):
    import typer

    seen = {}
    fake = types.ModuleType("caracole.commands.zz_ctx")

    def register(app: typer.Typer) -> None:
        @app.command("zz-where")
        def where(ctx: typer.Context) -> None:
            seen["path"] = ctx.obj.config_path

    fake.register = register
    sys.modules["caracole.commands.zz_ctx"] = fake
    try:
        app = cli.build_app(extra_modules=["caracole.commands.zz_ctx"])
        cfg = tmp_path / "caracole.toml"
        result = CliRunner().invoke(app, ["--config", str(cfg), "zz-where"])
    finally:
        del sys.modules["caracole.commands.zz_ctx"]
    assert result.exit_code == 0, result.output
    assert seen["path"] == cfg


# --- the log, set up once for every command by the root callback ------------------------------

def command(name: str, body) -> list[str]:
    """A command module named ``caracole.commands.zz_<name>`` whose command runs ``body(ctx)``."""
    import typer

    module = types.ModuleType(f"caracole.commands.zz_{name}")

    def register(app: typer.Typer) -> None:
        @app.command(f"zz-{name}")
        def run(ctx: typer.Context) -> None:
            body(ctx)

    module.register = register
    sys.modules[module.__name__] = module
    return [module.__name__]


def chatter(ctx) -> None:
    """What a command and the libraries it uses may log, at each level."""
    import logging

    import typer

    for name in ("caracole.zz", "httpx", "httpcore.connection", "librosa.core"):
        logging.getLogger(name).debug("%s debug", name)
        logging.getLogger(name).info("%s info", name)
        logging.getLogger(name).warning("%s warning", name)
    typer.echo("the report")


def invoke(*args: str, body=chatter):
    modules = command("chatter", body)
    try:
        app = cli.build_app(extra_modules=modules)
        return CliRunner().invoke(app, [*args, "zz-chatter"])
    finally:
        del sys.modules[modules[0]]


def test_every_command_logs_problems_only_by_default_on_stderr_alone():
    result = invoke()
    assert result.exit_code == 0, result.output
    assert result.stdout == "the report\n"  # the log never reaches stdout
    assert result.stderr.splitlines() == [
        "warning: caracole.zz warning", "warning: httpx warning", "warning: httpcore.connection warning",
        "warning: librosa.core warning",
    ]


def test_verbose_adds_caracoles_own_information_and_very_verbose_everything():
    verbose = invoke("-v").stderr.splitlines()
    assert "caracole.zz info" in verbose
    assert not [line for line in verbose if "debug" in line or line in ("httpx info", "librosa.core info")]
    very = invoke("-vv").stderr.splitlines()
    assert "debug: caracole.zz: caracole.zz debug" in very
    assert "httpx: httpx info" in very and "debug: httpcore.connection: httpcore.connection debug" in very


def test_quiet_keeps_the_problems_and_tells_the_command():
    seen = {}

    def body(ctx):
        seen["verbosity"] = ctx.obj.verbosity
        chatter(ctx)

    result = invoke("-q", body=body)
    assert seen["verbosity"] == logs.QUIET
    assert "warning: caracole.zz warning" in result.stderr.splitlines() and "info" not in result.stderr
    assert invoke("--quiet", body=body).exit_code == 0 and invoke("--verbose", "--verbose").exit_code == 0


def test_the_logging_a_command_found_is_back_once_it_ends():
    import logging

    root = logging.getLogger()
    before = (list(root.handlers), root.level, logging.getLogger("httpx").level)
    invoke("-vv")
    assert (list(root.handlers), root.level, logging.getLogger("httpx").level) == before


def test_a_bug_exits_1_with_one_line_that_says_so_then_its_traceback(monkeypatch, capsys):
    def body(ctx):
        raise KeyError("boom")

    modules = command("boom", body)
    try:
        monkeypatch.setattr(cli, "app", cli.build_app(extra_modules=modules))
        monkeypatch.setattr(sys, "argv", ["caracole", "zz-boom"])
        with pytest.raises(SystemExit) as exit_:
            cli.main()
    finally:
        del sys.modules[modules[0]]
    assert exit_.value.code == 1
    out, err = capsys.readouterr()
    first, second, *rest = err.splitlines()
    assert out == ""
    assert first == ("error: caracole stopped on an unexpected error: KeyError: 'boom'. That's a bug in caracole; "
                     "its traceback follows.")
    assert second == "Traceback (most recent call last):" and rest[-1] == "KeyError: 'boom'"


def test_every_help_keeps_its_square_brackets():
    # Rich reads "[version]" as markup and drops it: `caracole render --help` said "as overrides.toml
    # says (, else )". A table name in a help is written "\\[version]", as Rich escapes it.
    import click
    import typer.main
    from rich.markup import render

    def helps(command: click.Command, name: str):
        yield name, command.help or ""
        for param in command.params:
            yield f"{name} {param.opts[0] if param.opts else param.name}", getattr(param, "help", None) or ""
        for sub, child in getattr(command, "commands", {}).items():
            yield from helps(child, f"{name} {sub}")

    lost = [where for where, text in helps(typer.main.get_command(cli.build_app()), "caracole")
            if render(text).plain != text.replace("\\[", "[")]
    assert lost == []
