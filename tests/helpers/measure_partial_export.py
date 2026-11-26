"""Rows and bytes of a partial export (index_transfer.export(have=)) against a whole one, on a computer of realistic
shape, built with no request: UG's index of 30 sitemaps of 45,000 tabs (1.35 M rows), a directory of 250,000 artists
and 40,000 artist-page tabs; a phone that merged last week's whole export; then one night on the computer (UG's three
newest sitemaps read again with 50 tabs more each, a thirtieth of the directory seen again, 4,000 artist-page tabs
read), and both exports of it for that phone.

    nix develop -c python tests/helpers/measure_partial_export.py DIR

DIR is emptied and filled (about 600 MB, a couple of minutes). On 2026-11-26 it printed:

    whole: 1,640,150 rows {'ug_index': 1350150, 'ug_artist_tabs': 40000, 'ug_directory': 250000}, 183,590,912 bytes (175.1 MiB)
    partial: 157,058 rows {'ug_index': 135150, 'ug_artist_tabs': 4600, 'ug_directory': 17308}, 17,960,960 bytes (17.1 MiB)

(the directory's 17,308 hold about 8,300 rows stamped exactly at last week's export, which the hour's margin sends
again).
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from caracole import db, index_transfer as t, stamps
from caracole.ug import index as ug

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for p in out.iterdir():
    if p.is_file():
        p.unlink()
WEEK = datetime(2026, 11, 18, 12, tzinfo=UTC)
NIGHT = WEEK + timedelta(days=7)
TONIGHT = NIGHT + timedelta(hours=8)
SITEMAPS, PER, ARTISTS, TABS = 30, 45_000, 250_000, 40_000

def sitemap(conn, n, rows, at, start):
    conn.executemany("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                     "(?, ?, ?, 'chords', ?, ?, ?) ON CONFLICT (tab_id) DO NOTHING",
                     [(start + i, f"artist-{(start + i) % 20011}", f"song-{start + i}", str(n), stamps.stamp(at),
                       f"artist-{(start + i) % 20011}/song-{start + i}-chords-{start + i}") for i in range(rows)])
    rec = db.kv_get_json(conn, ug.SITEMAPS_KEY, default={}) or {}
    rec[str(n)] = {"etag": f'"{n}-{at:%d}"', "last_modified": None, "indexed_at": stamps.stamp(at), "rows": rows,
                   "tabs": {"urls": rows, "indexed": rows, "bare": 0, "other": {}, "closed": 0, "unrecognized": 0}}
    db.kv_set_json(conn, ug.SITEMAPS_KEY, rec)

home = db.connect(out / "home.sqlite")
t0 = time.time()
with db.savepoint(home, "build"):
    for n in range(1, SITEMAPS + 1):
        sitemap(home, n, PER, WEEK - timedelta(days=1), n * 1_000_000)
    home.executemany("INSERT INTO ug_directory (artist_id, name, slug, letter, place, tabs, updated_at, artist_key, forms, seen_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?)",
                     [(i, f"Artist {i}", f"artist-{i}", "abcdefghijklmnopqrstuvwxyz"[i % 26], i, i % 300, f"artist {i}",
                       f"artist {i}", stamps.stamp(WEEK - timedelta(days=i % 30))) for i in range(ARTISTS)])
    home.executemany("INSERT INTO ug_artist_tabs (page, tab_id, type, artist, title, url, artist_key, song_key, "
                     "artist_forms, title_forms, forms, read_at) VALUES (?, ?, 'chords', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     [(f"https://www.ultimate-guitar.com/artist/{i // 40}", i, f"Artist {i // 40}", f"Song {i}",
                       f"https://tabs.ultimate-guitar.com/tab/{i}", f"artist {i // 40}", f"song {i}", f"artist {i // 40}",
                       f"song {i}", f"artist {i // 40} song {i}", stamps.stamp(WEEK - timedelta(days=i % 60)))
                      for i in range(TABS)])
    db.kv_set(home, ug.REFRESHED_KEY, stamps.stamp(WEEK - timedelta(days=1)))
print(f"built in {time.time() - t0:.0f} s", flush=True)
phone = db.connect(out / "phone.sqlite")
t.export(home, out / "week.sqlite", ["ug"], now=WEEK)
t.merge(phone, out / "week.sqlite", ["ug"], state_dir=out / "state", now=WEEK, arrivals=False)
since = stamps.stamp(WEEK)
# One night: UG's three newest sitemaps read again (50 tabs more each), a thirtieth of the directory seen again, a
# hundred artist pages' tabs read.
with db.savepoint(home, "night"):
    for n in (SITEMAPS - 2, SITEMAPS - 1, SITEMAPS):
        sitemap(home, n, PER + 50, NIGHT, n * 1_000_000)
    home.execute("UPDATE ug_directory SET seen_at = ? WHERE letter = 'q'", (stamps.stamp(NIGHT),))
    home.execute("UPDATE ug_artist_tabs SET read_at = ? WHERE tab_id < 4000", (stamps.stamp(NIGHT),))
    db.kv_set(home, ug.REFRESHED_KEY, stamps.stamp(NIGHT))
records = t._records(phone, "main", ug.SITEMAPS_KEY)
have = {"ug": t.Have({k: {f: v for f, v in r.items() if f != "checked_at"} for k, r in records.items()}, since)}
whole = t.export(home, out / "whole.sqlite", ["ug"], now=TONIGHT)
part = t.export(home, out / "part.sqlite", ["ug"], now=TONIGHT, have=have)
for name, e in (("whole", whole), ("partial", part)):
    print(f"{name}: {sum(e.rows.values()):,} rows {e.rows}, {e.size:,} bytes ({e.size / 2**20:.1f} MiB)")
