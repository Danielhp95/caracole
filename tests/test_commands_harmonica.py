"""``caracole harmonica``, run through the CLI: how each of a song's harmonica tabs is read and the readings caracole
weighs; a reading pinned in overrides.toml's ``[harmonica]`` (a notation, the tab's own legend, or a notation with a
symbol changed), or the pin taken out, then the song's pages rendered again. It writes the library, so it takes
caracole's lock, and waits for it as a lookup does: it is asked for now."""

from __future__ import annotations

import fcntl
import os
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.config import load_config
from caracole.library import song_dir
from caracole.overrides import load_overrides

from conftest import add_song
from test_commands_versions import write_config
from test_render_harmonica import data_of, keep_tab
from test_viewer_harptab_notation import SPOKEY

SONG = "Placeholder Band - Synthetic Song"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)


@pytest.fixture
def setup(tmp_path):
    """A config, its cfg, and a song with one harmonica tab (no sheet: nothing for chordpro to make)."""
    config = write_config(tmp_path)
    cfg = load_config(config, env={})
    conn = db.connect(cfg.db_path)
    try:
        song = add_song(conn, "Placeholder Band", "Synthetic Song")
        keep_tab(conn, cfg, song, SPOKEY)
    finally:
        conn.close()
    return config, cfg, song


def harmonica(config: Path, *args: str):
    return CliRunner().invoke(build_app(), ["--config", str(config), "harmonica", *args])


def reading(cfg, song) -> dict:
    return data_of(song_dir(cfg.library_dir, song) / "harmonica-1.html", "harp-data")["reading"]


def test_it_says_how_each_tab_is_read_and_the_readings_it_weighs(setup):
    config, cfg, song = setup
    result = harmonica(config, SONG)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == ("harmonica-1.txt: read as b blow · d draw · * bend · - joins · (h) hold · (w) wah, from the "
                        "tab's own legend (Q 0.96)")
    assert lines[1] == "  legend       Q 0.96  b blow · d draw · * bend · - joins · (h) hold · (w) wah"
    assert lines[2].startswith("  letters      Q 0.86  b blow · d draw")
    assert any(line.startswith("  signs        Q ") for line in lines)
    assert not (cfg.library_dir / "overrides.toml").exists()  # it only reads


def test_as_pins_a_reading_and_renders_the_songs_pages_again(setup):
    config, cfg, song = setup
    result = harmonica(config, SONG, "--as", "signs")  # its one tab: no --tab needed
    assert result.exit_code == 0, result.output
    assert "harmonica-1.txt of Placeholder Band - Synthetic Song is read as signs, as you set it" in result.output
    assert load_overrides(cfg.overrides_file).harmonica == {song.key: {"harmonica-1.txt": "signs"}}
    assert reading(cfg, song)["source"] == "pinned" and reading(cfg, song)["name"] == "signs"
    # a notation with a symbol changed, a table in overrides.toml
    result = harmonica(config, SONG, "--tab", "harmonica-1.txt", "--as", "signs", "--symbol", "*=bend",
                       "--symbol", "(w)=wah")
    assert result.exit_code == 0, result.output
    assert load_overrides(cfg.overrides_file).harmonica[song.key] == {
        "harmonica-1.txt": {"as": "signs", "*": "bend", "(w)": "wah"}}
    # and back to caracole's guess
    result = harmonica(config, SONG, "--clear")
    assert result.exit_code == 0, result.output
    assert "caracole guesses how harmonica-1.txt is read again" in result.output
    assert load_overrides(cfg.overrides_file).harmonica == {} and reading(cfg, song)["source"] == "legend"
    again = harmonica(config, SONG, "--clear")
    assert again.exit_code == 0 and "No [harmonica] entry pins how harmonica-1.txt is read" in again.output


@pytest.mark.parametrize(("args", "said"), [
    (("--tab", "harmonica-9.txt", "--as", "signs"), "has no harmonica tab harmonica-9.txt"),
    (("--as", "staff"), "signs, brackets, letters, signs after, barrett or legend"),
    (("--as", "signs", "--symbol", "*"), "SYMBOL=MEANING"),
    (("--as", "signs", "--symbol", "*=squeak"), "what a symbol means"),
    (("--symbol", "*=bend"), "--symbol needs --as"),
    (("--as", "signs", "--clear"), "one of --as and --clear"),
])
def test_what_it_cant_do_is_a_usage_error_and_nothing_is_written(setup, args, said):
    config, cfg, _ = setup
    result = harmonica(config, SONG, *args)
    assert result.exit_code == 2, result.output
    assert said in result.output and not (cfg.library_dir / "overrides.toml").exists()


def test_a_pin_by_its_legend_needs_a_legend(setup, tmp_path):
    config, cfg, song = setup
    conn = db.connect(cfg.db_path)
    try:
        keep_tab(conn, cfg, song, "4 5 6 -6\nla la la la\n", number=2)
    finally:
        conn.close()
    many = harmonica(config, SONG, "--as", "signs")  # two tabs: which?
    assert many.exit_code == 2 and "--tab: harmonica-1.txt or harmonica-2.txt" in many.output
    result = harmonica(config, SONG, "--tab", "harmonica-2.txt", "--as", "legend")
    assert result.exit_code == 2 and "harmonica-2.txt has no legend of its own" in result.output
    assert harmonica(config, SONG, "--tab", "harmonica-1.txt", "--as", "legend").exit_code == 0


def test_a_change_waits_for_the_nightly_run_as_a_lookup_does(setup):
    # Asked for now (caracole serve's page queues it): its ticket says it waits, so that a nightly run holding the
    # lock hands it over at its next pause; until the lock is its own, nothing is written.
    from caracole.commands import _common

    config, cfg, _ = setup
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(cfg.state_dir / "caracole.lock", os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)  # the nightly run holds it
    os.write(fd, b"4242 run\n")
    done: list = []
    thread = threading.Thread(target=lambda: done.append(harmonica(config, SONG, "--as", "signs")), daemon=True)
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not _common.lookups_waiting(cfg) and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert _common.lookups_waiting(cfg), done and done[0].output
        assert not done and not (cfg.library_dir / "overrides.toml").exists()
    finally:
        os.close(fd)
    thread.join(15)
    assert done and done[0].exit_code == 0, done and done[0].output
    assert "it lets a lookup go first at its next pause" in done[0].output
    assert not _common.lookups_waiting(cfg)
