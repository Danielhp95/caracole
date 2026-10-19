"""A song caracole has rendered, so its sheet viewer is the page caracole wrote and recorded.

The sheet is kept the way the fetch step keeps one (a UG chords sheet: sheet.txt,
and sheet.json beside it), or the way the autochords step does, and then
``render_all`` runs with ``fake_chordpro`` in chordpro's place::

    from helpers.rendered import rendered_song

    song = rendered_song(conn, cfg)  # Soda Stereo/De Música Ligera/sheet.html, in G
    auto = rendered_song(conn, cfg, "Placeholder Band", "Synthetic Song", auto=True)  # sheet (auto).html
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from caracole.autochords import ChordSegment, build_sheet
from caracole.library import keep_file, song_dir, write_atomic
from caracole.overrides import Overrides
from caracole.render import render_all
from caracole.songs import Song
from caracole.ug.page import strip_markup
from caracole.versions import upsert_version

from conftest import add_song
from helpers.ug_pages import version_dict

FETCHED = "2026-10-18T03:00:00Z"

# A UG chords sheet in G, as wiki_tab.content holds it (synthetic lyrics).
SHEET = (
    "[Verse]\r\n"
    "[tab][ch]G[/ch]           [ch]D[/ch]\r\n"
    "Palabras de prueba[/tab]\r\n"
    "[tab][ch]Em[/ch]          [ch]C[/ch]\r\n"
    "solo para el visor[/tab]\r\n"
)


def fake_chordpro(cmd, **kwargs) -> subprocess.CompletedProcess:
    """Stands in for chordpro: writes a small PDF at its ``--output=``."""
    out = Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("--output=")))
    out.write_bytes(b"%PDF-1.4 fake\n")
    return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")


def rendered_song(conn, cfg, artist: str = "Soda Stereo", title: str = "De Música Ligera", *,
                  content: str = SHEET, auto: bool = False) -> Song:
    """Add a song, keep a sheet for it (``auto``: an auto-chords sheet), and render the library."""
    song = add_song(conn, artist, title)
    if auto:
        text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")], title=title,
                           artist=artist, synced="[00:00.00]made up words\n[00:04.00]for the test\n")
        vid = upsert_version(conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet",
                             kind="auto", rating=0, votes=0, version=1, label=None, url="", raw={}, now=FETCHED)
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt",
                  data=text.encode("utf-8"), rank=1)
    else:
        raw = version_dict(85053 + song.id, song=title, artist=artist, tonality_name="G")
        vid = upsert_version(conn, provider="ug", tab_id=str(raw["id"]), song_id=song.id, slot="sheet",
                             kind="chords", rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"],
                             raw=raw, now=FETCHED)
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
                  data=strip_markup(content).encode("utf-8"), rank=1)
        doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": []}
        write_atomic(song_dir(cfg.library_dir, song) / "sheet.json", json.dumps(doc, ensure_ascii=False).encode())
    stats = render_all(conn, cfg, Overrides(), runner=fake_chordpro)
    assert stats.failed == 0, stats
    return song
