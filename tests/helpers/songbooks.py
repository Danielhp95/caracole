"""Songs with sheets, the way the fetch and render steps leave them, for the songbook tests; and a
stand-in for the chordpro program that takes many files at once, as a songbook's run does.

The lyrics are synthetic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from caracole.library import keep_file, song_dir, write_atomic
from caracole.overrides import Overrides
from caracole.render import render_all
from caracole.ug.page import strip_markup
from caracole.versions import upsert_version
from helpers.ug_pages import version_dict

FETCHED = "2026-10-18T03:00:00Z"

SHEET = (
    "[Verse 1]\n"
    "[tab][ch]Am[/ch]          [ch]F[/ch]\n"
    "Una canción de prueba[/tab]\n"
    "[tab][ch]C[/ch]              [ch]G[/ch]\n"
    "solo para el analizador[/tab]\n"
)
ZH_SHEET = (
    "[Verse]\n"
    "[tab][ch]C[/ch]       [ch]G[/ch]\n"
    "这是一个合成的例子[/tab]\n"
)


def keep_sheet(conn, cfg, song, content: str = SHEET, *, tab_id: int = 85053, tonality: str = "Am") -> None:
    """Keep a UG sheet as the fetch step does: sheet.txt, and sheet.json beside it with the markup."""
    raw = version_dict(tab_id, song=song.title, artist=song.artist, tonality_name=tonality)
    vid = upsert_version(
        conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet", kind="chords",
        rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED,
    )
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": []}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json", json.dumps(doc, ensure_ascii=False).encode("utf-8"))


def output_of(cmd) -> Path:
    return Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("--output=")))


class FakeChordPro:
    """Stands in for subprocess.run: records each command, and writes its output by name, as chordpro
    does: a PDF holding the options and every input file in order, or a ChordPro file of the inputs
    joined by {new_song} (chordpro's own ChordPro backend), each as caracole wrote it.

    ``fail`` holds words that make a run fail when an input holds one.
    """

    def __init__(self, fail: tuple[str, ...] = ()):
        self.calls: list[list[str]] = []
        self.files: dict[Path, str] = {}  # each file of a run's folder, as it was when chordpro ran
        self.fail = fail

    def inputs(self, cmd) -> list[Path]:
        return [Path(a) for a in cmd[1:] if not a.startswith("-")]

    def text(self, path: Path) -> str:
        """A file of a run's folder, as it was when chordpro ran: the folder goes once it is done."""
        return self.files[path]

    def __call__(self, cmd, **kwargs):
        cmd = list(cmd)
        self.calls.append(cmd)
        out = output_of(cmd)
        for path in out.parent.iterdir():
            self.files[path] = path.read_text(encoding="utf-8", errors="replace")
        texts = [p.read_text(encoding="utf-8") for p in self.inputs(cmd)]
        if any(word in text for text in texts for word in self.fail):
            out.write_bytes(b"%PDF-1.4 half")
            return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="Unhandled fonts detected -- aborted\n")
        if out.suffix == ".cho":
            out.write_text("{new_song}\n".join(texts), encoding="utf-8")
        else:
            out.write_bytes(b"%PDF-1.4 fake\n" + "\n".join([*cmd[1:], *texts]).encode("utf-8"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


FAKE_PROGRAM = """\
#!{python}
import sys

out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--output="))
songs = [a for a in sys.argv[1:] if not a.startswith("-")]
texts = [open(s, encoding="utf-8").read() for s in songs]
with open(out, "w", encoding="utf-8") as f:
    if out.endswith(".cho"):
        f.write("{{new_song}}\\n".join(texts))
    else:
        f.write("%PDF-1.4 fake " + " ".join(sys.argv[1:]) + "\\n" + "\\n".join(texts))
"""


def fake_chordpro_program(folder: Path) -> Path:
    """A stand-in for the chordpro program, run as one: it writes its output by name, a PDF naming its
    options and holding its inputs, or a ChordPro file of its inputs joined by {new_song}."""
    path = folder / "bin" / "chordpro"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_PROGRAM.format(python=sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def render_sheets(conn, cfg, overrides: Overrides | None = None) -> None:
    """Render every kept sheet's .cho, PDF and viewer, as the render step does before the songbooks."""
    render_all(conn, cfg, overrides or Overrides(), runner=FakeChordPro())
