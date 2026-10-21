"""``caracole render`` through the CLI: what it leaves beside the PDFs.

How it renders, skips and fails is tested in test_render_all.py; here chordpro is a
fake that writes a stand-in PDF, so no real PDF is made.
"""

from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner

from caracole.cli import build_app

from conftest import add_song

FAKE_CHORDPRO = """\
#!{python}
import sys

out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
with open(out, "w", encoding="utf-8") as f:
    f.write("%PDF-1.4 fake")
"""
STALE = "as an earlier run left it\n"


@pytest.fixture
def chordpro(tmp_path):
    path = tmp_path / "bin" / "chordpro"
    path.parent.mkdir()
    path.write_text(FAKE_CHORDPRO.format(python=sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def render(cfg, chordpro, *args):
    toml = cfg.state_dir.parent / "caracole.toml"
    toml.write_text(
        f'library_dir = "{cfg.library_dir}"\nstate_dir = "{cfg.state_dir}"\n'
        f'cache_dir = "{cfg.cache_dir}"\nchordpro_bin = "{chordpro}"\n',
        encoding="utf-8",
    )
    return CliRunner().invoke(
        build_app(), ["--config", str(toml), "render", *args], env={"CARACOLE_CJK_FONT": None}
    )


def test_render_rewrites_the_pages(conn, cfg, chordpro):
    # The to-do page tells when the PDFs were last made, and index.html links them.
    add_song(conn, "Soda Stereo", "De Música Ligera")
    cfg.library_dir.mkdir(parents=True)
    for name in ("_todo.md", "index.html"):
        (cfg.library_dir / name).write_text(STALE, encoding="utf-8")
    result = render(cfg, chordpro)
    assert result.exit_code == 0, result.output
    todo = (cfg.library_dir / "_todo.md").read_text(encoding="utf-8")
    assert "## PDFs" in todo and "0 rendered, 0 failed" in todo
    assert (cfg.library_dir / "index.html").read_text(encoding="utf-8") != STALE


def song_in_em(conn, cfg):
    """A - T, with a UG sheet in Em kept."""
    from helpers.ug_pages import version_dict
    from caracole.library import keep_file, song_dir, write_atomic
    from caracole.versions import upsert_version
    import json

    song = add_song(conn, "A", "T")
    raw = version_dict(1, song="T", artist="A", tonality_name="Em")
    vid = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw,
                         now="2026-10-18T03:00:00Z")
    content = "[Verse]\n[tab][ch]Em[/ch]   [ch]G[/ch]\nuna prueba[/tab]\n"
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"x", rank=1)
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json",
                 json.dumps({"version": raw, "content": content, "meta": []}).encode("utf-8"))
    return song


def test_render_version_exports_one_song(conn, cfg, chordpro):
    from caracole.library import song_dir

    song = song_in_em(conn, cfg)
    result = render(cfg, chordpro, "--song", "A - T", "--version", "t=2&mode=dorian")
    assert result.exit_code == 0, result.output
    folder = song_dir(cfg.library_dir, song)
    exports = sorted(p.name for p in folder.glob("sheet (*).pdf"))
    assert len(exports) == 1 and "Dorian" in exports[0]
    assert exports[0] in result.output


def test_render_version_needs_a_song(cfg, chordpro):
    result = render(cfg, chordpro, "--version", "t=2")
    assert result.exit_code == 2


def test_render_mine_makes_the_version_the_songs_own_and_renders_the_song(conn, cfg, chordpro):
    import json
    import re

    from caracole.library import song_dir
    from caracole.overrides import load_overrides

    song = song_in_em(conn, cfg)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text("# mine\n", encoding="utf-8")
    result = render(cfg, chordpro, "--song", "A - T", "--version", "#t=2&mode=dorian&at=0.1&fs=20", "--mine")
    assert result.exit_code == 0, result.output
    assert "Your version of A - T: F# Dorian, capo 0" in result.output
    # the key it plays in, its mode and its capo, never a t: a sheet in another key in its place plays there too;
    # the shape chosen, for the chord it was chosen for
    assert load_overrides(cfg.overrides_file).version == {song.key: "key=F#m&mode=dorian&capo=0&at=F#m.x-4-4-6-7-5"}
    assert cfg.overrides_file.read_text(encoding="utf-8").startswith("# mine\n")
    folder = song_dir(cfg.library_dir, song)
    assert (folder / "sheet.pdf").is_file() and not list(folder.glob("sheet (*).pdf"))  # its own PDF, no export
    viewer = (folder / "sheet.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', viewer, re.S).group(1))
    assert data["start"] == "t=2&mode=dorian&capo=0&at=0.1"

    # The sheet as the song plays it without one: no [version] left.
    result = render(cfg, chordpro, "--song", "A - T", "--version", "t=0", "--mine")
    assert result.exit_code == 0, result.output
    assert load_overrides(cfg.overrides_file).version == {}


def song_without_a_key(conn, cfg):
    """A - T, with a UG sheet of no chord caracole can read kept: no key."""
    from helpers.ug_pages import version_dict
    from caracole.library import keep_file, song_dir, write_atomic
    from caracole.versions import upsert_version
    import json

    song = add_song(conn, "A", "T")
    raw = version_dict(1, song="T", artist="A", tonality_name="")
    vid = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw,
                         now="2026-10-18T03:00:00Z")
    content = "[Verse]\n[tab][ch]N.C.[/ch]   [ch]Hm[/ch]\nuna prueba[/tab]\n"
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"x", rank=1)
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json",
                 json.dumps({"version": raw, "content": content, "meta": []}).encode("utf-8"))
    return song


def test_render_mine_on_a_sheet_with_no_key_keeps_the_move_with_its_t(conn, cfg, chordpro):
    # No key to keep: the version is a move from the sheet, its t written even at 0, so the song's [transpose]
    # never takes its place when it is read back
    import json
    import re

    from caracole.library import song_dir
    from caracole.overrides import load_overrides

    song = song_without_a_key(conn, cfg)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text('[transpose]\n"A - T" = 3\n', encoding="utf-8")
    result = render(cfg, chordpro, "--song", "A - T", "--version", "t=0&capo=1", "--mine")
    assert result.exit_code == 0, result.output
    assert "Your version of A - T: As written, capo 1" in result.output
    assert load_overrides(cfg.overrides_file).version == {song.key: "t=0&capo=1"}
    viewer = (song_dir(cfg.library_dir, song) / "sheet.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', viewer, re.S).group(1))
    assert data["start"] == "t=0&capo=1"
    result = render(cfg, chordpro, "--song", "A - T", "--version", "t=0", "--mine")
    assert result.exit_code == 0, result.output
    assert load_overrides(cfg.overrides_file).version == {song.key: "t=0"}
    # the song's [transpose] is where it plays without one: no [version] left
    result = render(cfg, chordpro, "--song", "A - T", "--version", "t=3", "--mine")
    assert result.exit_code == 0, result.output
    assert load_overrides(cfg.overrides_file).version == {}


def keep_ug_sheet(conn, cfg, song, content: str, tab_id: int = 1, tonality: str = ""):
    """Keep a UG sheet of ``content`` as the song's, in place of any before it."""
    from helpers.ug_pages import version_dict
    from caracole.library import keep_file, song_dir, write_atomic
    from caracole.versions import upsert_version
    import json

    raw = version_dict(tab_id, song=song.title, artist=song.artist, tonality_name=tonality)
    vid = upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw,
                         now="2026-10-18T03:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=content.encode(), rank=1)
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json",
                 json.dumps({"version": raw, "content": content, "meta": []}).encode("utf-8"))


def test_render_mine_keeps_the_key_without_a_mode_so_a_sheet_read_in_the_relative_key_plays_its_chords(
        conn, cfg, chordpro):
    # Two tabs of one song, naming no key: the first reads as C major, the one in its place as A minor. Two up,
    # chosen on the first, is D major there; on the second it is what t=2 played, B minor: Bm G D A Bm
    import json
    import re

    from caracole.library import song_dir
    from caracole.overrides import load_overrides
    from caracole.viewer.page import viewer_key
    from caracole.viewer.sheet import parse_sheet
    from caracole.viewer.version import apply_version, version_from_query

    song = add_song(conn, "A", "T")
    keep_ug_sheet(conn, cfg, song, "[Verse]\n[tab][ch]C[/ch] [ch]G[/ch] [ch]Am[/ch] [ch]F[/ch] [ch]C[/ch]\n"
                                   "una prueba[/tab]\n")
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    result = render(cfg, chordpro, "--song", "A - T", "--version", "t=2", "--mine")
    assert result.exit_code == 0, result.output
    assert "Your version of A - T: D Major, capo 0" in result.output
    assert load_overrides(cfg.overrides_file).version == {song.key: "key=D&capo=0"}  # no mode chosen: none kept
    keep_ug_sheet(conn, cfg, song, "[Verse]\n[tab][ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch] [ch]Am[/ch]\n"
                                   "otra prueba[/tab]\n", tab_id=2)
    result = render(cfg, chordpro, "--song", "A - T")
    assert result.exit_code == 0, result.output
    folder = song_dir(cfg.library_dir, song)
    viewer = (folder / "sheet.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', viewer, re.S).group(1))
    assert data["start"] == "t=2&capo=0"
    cho = (folder / "sheet.cho").read_text(encoding="utf-8")
    assert re.findall(r"\[([^\]]+)\]", cho) == ["Am", "F", "C", "G", "Am"]  # the sheet in its place
    played = apply_version(cho, version_from_query(data["start"]), key=viewer_key(cho), capo_sheet=parse_sheet(cho).capo)
    assert re.findall(r"\[([^\]]+)\]", played) == ["Bm", "G", "D", "A", "Bm"]


def test_render_mine_needs_a_version(conn, cfg, chordpro):
    song_in_em(conn, cfg)
    result = render(cfg, chordpro, "--song", "A - T", "--mine")
    assert result.exit_code == 2 and "--mine needs --version" in result.output
