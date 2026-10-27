"""Songs as the library holds them, for index.html's tests: their files in their folders and their records, as the
fetch, the inbox and the render steps leave them, with no request and no chordpro::

    from helpers.library_songs import hotel_california

``hotel_california(conn, cfg)``: Eagles - Hotel California, found, in B minor (from the tab), which holds one of
everything a song's line shows: its chord sheet from Ultimate Guitar (viewer, PDF, text and ChordPro), two Guitar Pro
files (gtptabs.com's, then one filed from your inbox) and a text tab, a harmonica tab of harptabs.com's, its lyrics
(plain and timed, LRCLIB's) and a MusicXML score filed from your inbox. Its files' bytes are stand-ins.
"""

from __future__ import annotations

import json

from caracole.library import keep_file, song_dir
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song

HOTEL = "[ch]Bm[/ch] [ch]F#[/ch]\nOn a dark desert highway\n"


def _version(conn, song, provider, tab_id, slot, kind, *, raw=None, url=""):
    return upsert_version(conn, provider=provider, tab_id=str(tab_id), song_id=song.id, slot=slot, kind=kind,
                          rating=4.86 if provider == "ug" else 0, votes=408 if provider == "ug" else 0, version=3,
                          label=None, url=url, raw=raw or {}, now="2026-10-19T00:00:00Z")


def hotel_california(conn, cfg):
    """Eagles - Hotel California, holding a file of every kind a line shows (the module's docstring)."""
    song = add_song(conn, "Eagles", "Hotel California", added_at="2026-10-19T00:00:00Z")
    ug = _version(conn, song, "ug", 46190, "sheet", "chords", raw={"tonality_name": "Bm"},
                  url="https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-46190")
    keep_file(conn, cfg.library_dir, song=song, version_id=ug, name="sheet.json",
              data=json.dumps({"content": HOTEL}).encode(), rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=ug, name="sheet.txt", data=HOTEL.encode(), rank=1)
    gtp = _version(conn, song, "gtptabs", 1201, "guitar", "guitar-pro",
                   url="https://gtptabs.com/tabs/e/eagles/hotel-california-1201.html")
    keep_file(conn, cfg.library_dir, song=song, version_id=gtp, name="guitar-1.gp5", data=b"FICHIER GUITAR PRO v5",
              rank=1)
    inbox = _version(conn, song, "inbox", "guitar-pro", "guitar", "guitar-pro")
    keep_file(conn, cfg.library_dir, song=song, version_id=inbox, name="guitar-2.gp5",
              data=b"FICHIER GUITAR PRO v5.10", rank=1)
    harp = _version(conn, song, "harptabs", 3141, "guitar", "harmonica",
                    url="https://www.harptabs.com/song.php?ID=3141")
    keep_file(conn, cfg.library_dir, song=song, version_id=harp, name="harmonica-1.txt", data=b"4 -4 5 -5\n", rank=1)
    score = _version(conn, song, "inbox", "score", "guitar", "score")
    keep_file(conn, cfg.library_dir, song=song, version_id=score, name="score-1.mxl", data=b"PK\x03\x04", rank=1)
    folder = song_dir(cfg.library_dir, song)
    for name in ("sheet.html", "sheet.pdf", "sheet.cho", "tab.txt", "lyrics.txt", "lyrics.lrc"):
        (folder / name).write_bytes(b"x")
    update_song(conn, song.id, status="found", lyrics_status="found")
    return song
