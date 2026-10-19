import sys
import types

from typer.testing import CliRunner

from tabarr import cli


def test_version_option():
    result = CliRunner().invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "tabarr 0.1.0" in result.output


def test_command_modules_are_discovered(monkeypatch):
    import typer

    fake = types.ModuleType("tabarr.commands.zz_fake")

    def register(app: typer.Typer) -> None:
        @app.command("zz-hello")
        def hello() -> None:
            typer.echo("hello from plugin")

    fake.register = register
    monkeypatch.setitem(sys.modules, "tabarr.commands.zz_fake", fake)
    app = cli.build_app(extra_modules=["tabarr.commands.zz_fake"])
    result = CliRunner().invoke(app, ["zz-hello"])
    assert result.exit_code == 0, result.output
    assert "hello from plugin" in result.output


def test_config_option_is_stored_on_context(tmp_path):
    import typer

    seen = {}
    fake = types.ModuleType("tabarr.commands.zz_ctx")

    def register(app: typer.Typer) -> None:
        @app.command("zz-where")
        def where(ctx: typer.Context) -> None:
            seen["path"] = ctx.obj.config_path

    fake.register = register
    sys.modules["tabarr.commands.zz_ctx"] = fake
    try:
        app = cli.build_app(extra_modules=["tabarr.commands.zz_ctx"])
        cfg = tmp_path / "tabarr.toml"
        result = CliRunner().invoke(app, ["--config", str(cfg), "zz-where"])
    finally:
        del sys.modules["tabarr.commands.zz_ctx"]
    assert result.exit_code == 0, result.output
    assert seen["path"] == cfg
