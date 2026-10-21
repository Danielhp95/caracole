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


def test_render_version_exports_one_song(conn, cfg, chordpro):
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
    result = render(cfg, chordpro, "--song", "A - T", "--version", "t=2&mode=dorian")
    assert result.exit_code == 0, result.output
    folder = song_dir(cfg.library_dir, song)
    exports = sorted(p.name for p in folder.glob("sheet (*).pdf"))
    assert len(exports) == 1 and "Dorian" in exports[0]
    assert exports[0] in result.output


def test_render_version_needs_a_song(cfg, chordpro):
    result = render(cfg, chordpro, "--version", "t=2")
    assert result.exit_code == 2
