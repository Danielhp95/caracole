"""Songs as the library holds them, for index.html's tests: their files in their folders and their records, as the
fetch, the inbox and the render steps leave them, with no request and no chordpro::

    from helpers.library_songs import hotel_california, with_versions

``hotel_california(conn, cfg)``: Eagles - Hotel California, found, in B minor (from the tab), which holds one of
everything a song's line shows: its chord sheet from Ultimate Guitar (viewer, PDF, text and ChordPro), two Guitar Pro
files (gtptabs.com's, then one filed from your inbox) and a text tab, a harmonica tab of harptabs.com's, its lyrics
(plain and timed, LRCLIB's) and a MusicXML score filed from your inbox. Its files' bytes are stand-ins.

``with_versions(conn, cfg, song)``: what a song's card counts and lists besides, for one whose sheet is Ultimate
Guitar's (``hotel_california``'s): twelve more of UG's chords versions (13 in all, ``TABS`` in rank order), the next
two kept beside the sheet (``version-<tab>.txt`` and ``.json``, the first with its viewer page), two LaCuerda sheets
caracole met (``LACUERDA``, best first), an auto sheet beside the human one, and a PDF export in another key.
"""

from __future__ import annotations

import json

from caracole.library import keep_file, song_dir
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song

HOTEL = "[ch]Bm[/ch] [ch]F#[/ch]\nOn a dark desert highway\n"
SHEET_TAB = "46190"  # hotel_california's sheet
TABS = (SHEET_TAB, *(str(46191 + n) for n in range(12)))  # with_versions': UG's chords versions in rank order
LACUERDA = ("https://acordes.lacuerda.net/eagles/hotel_california.shtml",
            "https://acordes.lacuerda.net/eagles/hotel_california-2.shtml")
EXPORT = "sheet (G Dorian, capo 0).pdf"


def _version(conn, song, provider, tab_id, slot, kind, *, raw=None, url=""):
    return upsert_version(conn, provider=provider, tab_id=str(tab_id), song_id=song.id, slot=slot, kind=kind,
                          rating=4.86 if provider == "ug" else 0, votes=408 if provider == "ug" else 0, version=3,
                          label=None, url=url, raw=raw or {}, now="2026-10-19T00:00:00Z")


def hotel_california(conn, cfg):
    """Eagles - Hotel California, holding a file of every kind a line shows (the module's docstring)."""
    song = add_song(conn, "Eagles", "Hotel California", added_at="2026-10-19T00:00:00Z")
    ug = _version(conn, song, "ug", SHEET_TAB, "sheet", "chords", raw={"tonality_name": "Bm"},
                  url=f"https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-{SHEET_TAB}")
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


def with_versions(conn, cfg, song):
    """The versions a card counts and lists, for ``song``, a ``hotel_california`` (the module's docstring)."""
    from caracole.db import kv_set_json
    from caracole.render import EXPORT_KV
    from caracole.sheet_versions import version_names
    from caracole.versions import set_coverage

    sheet = conn.execute("SELECT id FROM versions WHERE song_id = ? AND tab_id = ?", (song.id, SHEET_TAB)).fetchone()[0]
    set_coverage(conn, sheet, 1.0)
    for n, tab in enumerate(TABS[1:], start=1):
        vid = upsert_version(conn, provider="ug", tab_id=tab, song_id=song.id, slot="sheet", kind="chords",
                             rating=round(4.8 - n / 20, 2), votes=900 - 50 * n, version=n + 3, label=None,
                             url=f"https://tabs.ultimate-guitar.com/tab/eagles/hotel-california-chords-{tab}", raw={},
                             now="2026-10-19T00:00:00Z")
        if n <= 2:  # the next two, kept beside the sheet
            set_coverage(conn, vid, 0.8 if n == 1 else 0.5)
            text, doc, viewer = version_names(tab)
            keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=text, data=tab.encode(), rank=n + 1)
            keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=doc, data=b"{}", rank=n + 1)
            if n == 1:
                (song_dir(cfg.library_dir, song) / viewer).write_bytes(b"x")
    for url, coverage in zip(LACUERDA, (0.9, 0.6), strict=True):
        vid = upsert_version(conn, provider="lacuerda", tab_id=url.split("/", 3)[3].removesuffix(".shtml"),
                             song_id=song.id, slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                             url=url, raw={}, now="2026-10-19T00:00:00Z")
        set_coverage(conn, vid, coverage)
    folder = song_dir(cfg.library_dir, song)
    for name in ("sheet (auto).html", "sheet (auto).pdf", "sheet (auto).txt", "sheet (auto).cho", EXPORT):
        (folder / name).write_bytes(b"x")
    kv_set_json(conn, f"{EXPORT_KV}{song.id}", {"G Dorian, capo 0": {"pdf": EXPORT, "query": "t=-4&mode=dorian"}})
