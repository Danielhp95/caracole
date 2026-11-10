"""The phone's own pages, for :viewer's viewer.render (``PhoneRender``): render.py's page path with no PDF, as
tests/helpers/phone_render.py runs it, over fixture libraries, so that the phone writes and records what it does for
the same library.

``vectors/viewer/render.jsonl``, each record one of:

- ``constants``: what render.py, songs.py, inbox.py, library.py and keys.py name that the phone's render names too,
  read from the modules (``CONSTANTS``): kv's prefixes and keys, the sheets' names and their outputs', the harmonica
  tabs' names and pages', the lyrics sites that ask a link back, and phone_render's record's suffix.
- ``phone_render``: ``args`` ``[fixture, steps]``, a library (``helpers.corpus.dump_fixture``'s records: its
  database's rows, its kv, the phone's overrides as ``phone_overrides`` rows of overrides.toml, and the files of its
  songs' folders) and what is done to it in turn, each step one of ``{"render": song ids or null}`` (``phone_render``
  of those songs, of every song for null; the phone's ``PhoneRender.render`` of them), ``{"drop": [song id, name]}``
  (``library.drop_file``: the file forgotten and deleted, as a fetch lets a version go) and ``{"delete": path}`` (a
  file of the library deleted from its folder, as on a synced device, its record kept); ``out`` a list, one entry a
  render step: ``{"failed": [display names], "files": [[path, sha256, size], …] (every file of the songs' folders,
  by path), "kv": {key: text} (every record of render.py's and the phone's: render:files:*, render:progressions:*,
  render:*:phone, keys:own_versions), "units": {unit: digest} (each song's, which a changed file, version or override
  moves), "info": {path: text} (each info.json)}``.

The cases (``CASES``) between them reach: a UG sheet and its key; the versions kept beside the sheet (their pages,
one dropped once it leaves), the song's UG versions listed with the one and a ``[pin]``, a Guitar Pro file linked, an
auto sheet beside the human one (no export, its shapes and swaps not the song's); harmonica tabs (their pages, the
harp the sheet's viewer starts on, each page dropped once its tab leaves or its text is gone); an own version kept by
a major letter alone on a sheet now read minor, rewritten once (kv ``keys:own_versions``), and one moved by
``[transpose]``; an auto sheet that takes lyrics that came after it (``with_plain_lyrics``, its version's ``raw``
lyrics "plain"), one made from a YouTube video's audio (the video drawn from the icons, its credit off the viewer);
Chinese sheets in Simplified and in Traditional characters (the phone's script record); LaCuerda's sheet; a sheet that
can't be read (the song failed); a song with no sheet, and one ignored.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from caracole import canonical, db, inbox, keys, library, render, songs
from caracole.autochords import ChordSegment, build_sheet
from caracole.autochords.merge import AUTO_MARKER, youtube_credit
from caracole.config import load_config
from caracole.icons import YOUTUBE
from caracole.lyrics import Lyrics
from caracole.overrides import SONG_TABLES, load_overrides, song_entries
from caracole.songs import get_song, list_songs, update_song
from caracole.ug.page import strip_markup
from caracole.versions import set_coverage, upsert_version

from conftest import add_song, migrated_database
from helpers import phone_render as phone
from helpers.corpus import check, dump_fixture, jsonl, phone_schema
from helpers.ug_pages import version_dict
from helpers.viewer_corpus import VIEWER_VECTORS
from test_viewer_harpfit import LINES, a_tab

MADE_BY = "tests/test_conformance_viewer_render.py"
NOW = "2026-11-05T00:00:00Z"  # every stamp of a fixture, so it is the same on every run
FETCHED = "2026-11-05T00:00:00Z"
UG = "https://tabs.ultimate-guitar.com/tab/"

CONSTANTS = {
    "FILES_KEY": render.FILES_KEY,
    "OWN_VERSIONS_KEY": render.OWN_VERSIONS_KEY,
    "STATUS_KEY": render.STATUS_KEY,
    "PHONE_KV": phone.PHONE_KV,
    "HUMAN_SHEET": songs.HUMAN_SHEET,
    "AUTO_SHEET": songs.AUTO_SHEET,
    "SHEET_OUTPUTS": {name: list(outputs) for name, outputs in songs.SHEET_OUTPUTS.items()},
    "TRADITIONAL_PDFS": dict(songs.TRADITIONAL_PDFS),
    "SHEET_DOC": keys.SHEET_DOC,
    "AUTO_MARKER": AUTO_MARKER,
    "LETTER": render._LETTER.pattern,
    "HARMONICA_KIND": inbox.HARMONICA_KIND,
    "HARMONICA_FILE": inbox.HARMONICA_FILE.pattern,
    "HARMONICA_PAGE": inbox.HARMONICA_PAGE.pattern,
    "LYRICS_PAGES": dict(library.LYRICS_PAGES),
    "YOUTUBE": YOUTUBE,
    "IGNORED": "ignored",
}


# --- a library ---------------------------------------------------------------------------------------------------


class World:
    """A fresh library of its own: its database (copied from a migrated one), its config, its overrides.toml."""

    def __init__(self, root: Path):
        path = root / "state" / "caracole.sqlite"
        path.parent.mkdir(parents=True)
        path.write_bytes(migrated_database())
        self.conn = db.connect(path)
        self.cfg = load_config(None, env={"HOME": str(root / "home"), "STATE_DIRECTORY": str(root / "state"),
                                          "CACHE_DIRECTORY": str(root / "cache")})
        self.cfg.library_dir.mkdir(parents=True, exist_ok=True)

    def overrides(self, text: str) -> None:
        self.cfg.overrides_file.write_text(text, encoding="utf-8")

    def folder(self, song) -> Path:
        return library.song_dir(self.cfg.library_dir, song)

    def close(self) -> None:
        self.conn.close()


def _version(w: World, song, provider: str, tab_id: str, kind: str, *, slot: str = "sheet", raw=None, url: str = "",
             rating: float = 4.5, votes: int = 10, version: int = 1) -> int:
    return upsert_version(w.conn, provider=provider, tab_id=tab_id, song_id=song.id, slot=slot, kind=kind,
                          rating=rating, votes=votes, version=version, label=None, url=url, raw=raw or {}, now=FETCHED)


def _keep(w: World, song, vid: int, name: str, data: str | bytes, rank: int = 1) -> None:
    library.keep_file(w.conn, w.cfg.library_dir, song=song, version_id=vid, name=name,
                      data=data.encode("utf-8") if isinstance(data, str) else data, rank=rank)


def ug_sheet(w: World, song, content: str, *, tab: int, tonality: str | None, capo: int | None = None,
             names: tuple[str, str] = ("sheet.txt", "sheet.json"), rank: int = 1, version: int = 1) -> int:
    """A UG chords sheet kept as the fetch keeps one: its text, and its JSON with the raw content and the page's meta
    (``names``: a version kept beside it, ``version-<tab>.txt`` and ``.json``)."""
    raw = version_dict(tab, song=song.title, artist=song.artist, version=version,
                       **({"tonality_name": tonality} if tonality is not None else {}))
    vid = _version(w, song, "ug", str(tab), "chords", raw=raw, url=raw["tab_url"], version=version)
    doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": {"capo": capo} if capo else {}}
    _keep(w, song, vid, names[0], strip_markup(content), rank)
    _keep(w, song, vid, names[1], json.dumps(doc, ensure_ascii=False, indent=2) + "\n", rank)
    return vid


def ug_listed(w: World, song, tab: int, *, rating: float, votes: int, version: int, coverage: float | None = None):
    """A UG chords version the fetch listed and didn't keep."""
    raw = version_dict(tab, song=song.title, artist=song.artist, version=version, rating=rating, votes=votes)
    vid = _version(w, song, "ug", str(tab), "chords", raw=raw, url=raw["tab_url"], rating=rating, votes=votes,
                   version=version)
    if coverage is not None:
        set_coverage(w.conn, vid, coverage)
    return vid


def auto_sheet(w: World, song, *, synced: str | None, raw: dict[str, Any] | None = None, source: str | None = None):
    """An auto-chords sheet kept as the autochords step keeps one."""
    text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G"), ChordSegment(8.0, 12.0, "Am")],
                       title=song.title, artist=song.artist, synced=synced, source=source, beats=BEATS)
    vid = _version(w, song, "auto", f"auto-{song.id}", "auto", raw=raw or {}, rating=0, votes=0)
    _keep(w, song, vid, songs.AUTO_SHEET, text)
    return vid


def harmonica_tab(w: World, song, number: int, text: str, *, key: str | None, harp: str | None = None):
    """A harmonica tab kept as harptabs_fetch.py keeps one, its page's chips ``key`` and ``harp``."""
    vid = _version(w, song, "harptabs", str(588 + number), inbox.HARMONICA_KIND, slot="guitar",
                   url=f"https://www.harptabs.com/tab/{588 + number}/synthetic-song", rating=3.3, votes=224000,
                   raw={"title": song.title, "artist": song.artist, "key": key, "harp": harp,
                        "difficulty": "Beginner", "views": 224000, "rating": 3.3})
    _keep(w, song, vid, f"harmonica-{number}.txt", text, number)


def store_lyrics(w: World, song, plain: str, *, provider: str = "lrclib", url: str | None = None) -> None:
    lyrics = Lyrics(plain=plain, synced=None, instrumental=False, duration=None, lrclib_id=None, raw={},
                    provider=provider, url=url)
    update_song(w.conn, song.id, lyrics_status="found", lyrics_json=lyrics.to_json())


# --- the cases ---------------------------------------------------------------------------------------------------

SODA = (  # a UG chords sheet in G (synthetic words)
    "[Verse]\r\n"
    "[tab][ch]G[/ch]           [ch]D[/ch]\r\n"
    "Palabras de prueba[/tab]\r\n"
    "[tab][ch]Em[/ch]          [ch]C[/ch]\r\n"
    "solo para el visor[/tab]\r\n"
    "\r\n[Chorus]\r\n"
    "[tab][ch]C[/ch]      [ch]G[/ch]      [ch]D[/ch]\r\n"
    "y un coro de prueba[/tab]\r\n"
)
HOTEL = (  # Hotel California as UG writes it: its key "A", capo 2, its chords A minor's (synthetic words)
    "[Intro]\n[ch]Am[/ch]  [ch]E7[/ch]  [ch]G[/ch]  [ch]D[/ch]  [ch]F[/ch]  [ch]C[/ch]  [ch]Dm[/ch]  [ch]E[/ch]\n\n"
    "[Verse]\n[tab][ch]Am[/ch]             [ch]E7[/ch]\nmade up words to sing[/tab]\n"
    "[tab][ch]G[/ch]                 [ch]D[/ch]\nonly for the test[/tab]\n"
    "[tab][ch]F[/ch]                 [ch]C[/ch]\nand more of them[/tab]\n"
    "[tab][ch]Dm[/ch]                [ch]E7[/ch]\nand back again[/tab]\n"
)
HOTEL_OTHER = (  # another tabber's, in B minor with no capo
    "[Verse]\n[tab][ch]Bm[/ch]             [ch]F#[/ch]\nmade up words to sing[/tab]\n"
    "[tab][ch]A[/ch]                 [ch]E[/ch]\nonly for the test[/tab]\n"
)
HOTEL_THIRD = (  # a third, which the fetch lets go
    "[Verse]\n[tab][ch]Am[/ch]   [ch]E[/ch]\nmade up words to sing[/tab]\n"
)
GM = (
    "[Verse 1]\r\n"
    "[tab][ch]Gm[/ch]             [ch]Eb[/ch]\r\n"
    "Una canción de prueba[/tab]\r\n"
    "[tab][ch]Bb[/ch]                 [ch]F[/ch]\r\n"
    "solo para el analizador[/tab]\r\n"
)
SIMPLIFIED = (  # Chinese words in Simplified characters (synthetic)
    "[Verse]\n[tab][ch]C[/ch]        [ch]G[/ch]\n我们一起唱歌月亮[/tab]\n"
    "[tab][ch]Am[/ch]       [ch]F[/ch]\n遥远的地方爱情故事[/tab]\n"
)
TRADITIONAL = (  # and in Traditional ones
    "[Verse]\n[tab][ch]D[/ch]        [ch]A[/ch]\n愛情說話聽見開門[/tab]\n"
    "[tab][ch]Bm[/ch]       [ch]G[/ch]\n風吹過來發著光[/tab]\n"
)
LACUERDA = "[ch]Am[/ch]        [ch]G[/ch]\nletra de prueba aquí\n[ch]F[/ch]       [ch]E[/ch]\ny otra línea más\n"
TAB_LINES = "".join(f"[tab][ch]D[/ch]\r\n{line}[/tab]\r\n" for line in LINES)  # a D under each of the tab's lines
VIDEO = {"id": "dQw4w9WgXcQ", "title": "Synthetic  Song (Official Audio)", "channel": "Placeholder  Band - Topic",
         "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
SYNCED = "[00:00.00]made up words to sing\n[00:04.00]only for the test\n"
BEATS = [float(n) for n in range(13)]


def case_ug_sheet(w: World) -> list[dict]:
    song = add_song(w.conn, "Soda Stereo", "De Música Ligera - Remasterizado 2007")
    ug_sheet(w, song, SODA, tab=85053, tonality="G", capo=2)
    return [{"render": None}]


def case_versions(w: World) -> list[dict]:
    song = add_song(w.conn, "Eagles", "Hotel California")
    ug_sheet(w, song, HOTEL, tab=46190, tonality="A", capo=2, version=3)
    ug_sheet(w, song, HOTEL_OTHER, tab=46191, tonality="Bm", names=("version-46191.txt", "version-46191.json"),
             rank=2, version=4)
    ug_sheet(w, song, HOTEL_THIRD, tab=46192, tonality=None, names=("version-46192.txt", "version-46192.json"),
             rank=3, version=5)
    for n, tab in enumerate((46193, 46194, 46195)):
        ug_listed(w, song, tab, rating=4.8 - n / 10, votes=900 - 100 * n, version=6 + n,
                  coverage=0.4 if n == 0 else None)
    set_coverage(w.conn, w.conn.execute("SELECT id FROM versions WHERE tab_id = '46190'").fetchone()[0], 1.0)
    gtp = _version(w, song, "gtptabs", "1201", "guitar-pro", slot="guitar",
                   url="https://gtptabs.com/tabs/e/eagles/hotel-california-1201.html")
    _keep(w, song, gtp, "guitar-1.gp5", b"FICHIER GUITAR PRO v5.00 synthetic")
    auto_sheet(w, song, synced=SYNCED)
    w.overrides('[pin]\n"Eagles - Hotel California" = ['
                f'"{UG}eagles/hotel-california-chords-46190"]\n')
    return [{"render": None}, {"drop": [song.id, "version-46192.txt"]}, {"drop": [song.id, "version-46192.json"]},
            {"render": [song.id]}]


def case_harmonica(w: World) -> list[dict]:
    song = add_song(w.conn, "Placeholder Band", "Synthetic Song")
    ug_sheet(w, song, TAB_LINES, tab=91001, tonality="Bm")
    harmonica_tab(w, song, 1, a_tab(), key="C")
    harmonica_tab(w, song, 2, a_tab(3), key=None, harp="Diatonic")
    alone = add_song(w.conn, "Placeholder Band", "Tab Alone", added_at="2026-10-02T00:00:00Z")
    harmonica_tab(w, alone, 3, a_tab(2), key="G")
    folder = w.folder(song).relative_to(w.cfg.library_dir).as_posix()
    return [{"render": None}, {"delete": f"{folder}/harmonica-1.txt"}, {"drop": [song.id, "harmonica-2.txt"]},
            {"render": None}]


def case_own_versions(w: World) -> list[dict]:
    hotel = add_song(w.conn, "Eagles", "Hotel California")
    ug_sheet(w, hotel, HOTEL, tab=46190, tonality="A", capo=2)
    soda = add_song(w.conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-02T00:00:00Z")
    ug_sheet(w, soda, GM, tab=85054, tonality="Gm")
    moved = add_song(w.conn, "Placeholder Band", "Moved Song", added_at="2026-10-03T00:00:00Z")
    ug_sheet(w, moved, SODA, tab=85055, tonality="G")
    w.overrides("# my versions\n[version]\n"
                '"Eagles - Hotel California" = "key=B&capo=2"  # two up\n'
                '"Soda Stereo - De Música Ligera" = "key=A"  # A major, on a G minor sheet\n'
                '\n[transpose]\n"Placeholder Band - Moved Song" = -2\n')
    return [{"render": None}, {"render": None}]


def case_auto_sheets(w: World) -> list[dict]:
    later = add_song(w.conn, "Placeholder Band", "Lyrics Came Later")
    auto_sheet(w, later, synced=None, raw={"lyrics": "none", "key": "C"}, source="Audio from a purchase (synthetic)")
    store_lyrics(w, later, "made up words to sing\nonly for the test\n\nand a second verse", provider="megalobiz",
                 url="https://megalobiz.com/lrc/maker/synthetic.51234567")
    video = add_song(w.conn, "Placeholder Band", "From A Video", added_at="2026-10-02T00:00:00Z")
    auto_sheet(w, video, synced=SYNCED, raw={"youtube": VIDEO},
               source=youtube_credit(VIDEO["title"], VIDEO["channel"], VIDEO["id"]))
    return [{"render": None}]


def case_chinese(w: World) -> list[dict]:
    simplified = add_song(w.conn, "李健", "月亮代表")
    ug_sheet(w, simplified, SIMPLIFIED, tab=77001, tonality="C")
    traditional = add_song(w.conn, "周杰倫", "愛情", added_at="2026-10-02T00:00:00Z")
    ug_sheet(w, traditional, TRADITIONAL, tab=77002, tonality=None)
    return [{"render": None}]


def case_other_sheets(w: World) -> list[dict]:
    lc = add_song(w.conn, "Estopa", "Tu Calorro")
    url = "https://acordes.lacuerda.net/estopa/tu_calorro.shtml"
    vid = _version(w, lc, "lacuerda", "estopa/tu_calorro", "acordes", url=url, rating=0, votes=0)
    doc = {"provider": "lacuerda", "url": url, "content": LACUERDA, "version": 1}
    _keep(w, lc, vid, "sheet.json", json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    _keep(w, lc, vid, "sheet.txt", strip_markup(LACUERDA))
    ug_listed(w, lc, 51001, rating=4.6, votes=120, version=1)
    ug_listed(w, lc, 51002, rating=4.1, votes=30, version=2)
    broken = add_song(w.conn, "Placeholder Band", "Unreadable Sheet", added_at="2026-10-02T00:00:00Z")
    raw = version_dict(61001, song=broken.title, artist=broken.artist, tonality_name="E")
    bad = _version(w, broken, "ug", "61001", "chords", raw=raw, url=raw["tab_url"])
    _keep(w, broken, bad, "sheet.json", "{not json")
    _keep(w, broken, bad, "sheet.txt", "made up words")
    add_song(w.conn, "Placeholder Band", "Nothing Kept", added_at="2026-10-03T00:00:00Z")
    ignored = add_song(w.conn, "Placeholder Band", "Ignored Song", added_at="2026-10-04T00:00:00Z")
    ug_sheet(w, ignored, SODA, tab=61002, tonality="G")
    w.overrides('[ignore]\nsongs = ["Placeholder Band - Ignored Song"]\n')
    return [{"render": None}]


CASES = {
    "ug_sheet": case_ug_sheet,
    "versions": case_versions,
    "harmonica": case_harmonica,
    "own_versions": case_own_versions,
    "auto_sheets": case_auto_sheets,
    "chinese": case_chinese,
    "other_sheets": case_other_sheets,
}


# --- the records -------------------------------------------------------------------------------------------------


def phone_rows(w: World) -> list[tuple[str, str, str, str]]:
    """overrides.toml as the phone holds it, ``phone_overrides`` rows (phone.sql): each song's entries by its identity
    key, written as its display name."""
    o = load_overrides(w.cfg.overrides_file)
    named = {s.key: s.display for s in list_songs(w.conn)}
    rows = []
    for key in sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore)):
        entries = song_entries(o, key)
        for table in (*SONG_TABLES, "ignore"):
            if table in entries:
                rows.append((table, key, named.get(key, key), canonical.dumps(entries[table])))
    return rows


def _settle(w: World) -> None:
    """Every stamp a fixture holds made ``NOW``, and the phone's overrides overrides.toml's."""
    w.conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (NOW, NOW))
    w.conn.execute("UPDATE files SET created_at = ?", (NOW,))
    w.conn.execute("DELETE FROM kv WHERE key GLOB 'wanted:first_seen:*'")
    if "phone_overrides" not in {r[0] for r in w.conn.execute("SELECT name FROM sqlite_master")}:
        phone_schema(w.conn)
    w.conn.execute("DELETE FROM phone_overrides")
    w.conn.executemany("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)", phone_rows(w))


def _fixture(w: World) -> list[dict]:
    """The library's records, the files of its songs' folders alone (overrides.toml is the phone's database's)."""
    return [r for r in dump_fixture(w.conn, w.cfg.library_dir) if "file" not in r or "/" in r["file"]]


RECORDED = re.compile(r"render:(files:\d+|progressions:\d+|\d+:phone)|keys:own_versions")


def _out(w: World, made: phone.PhoneRendered) -> dict[str, Any]:
    lib = w.cfg.library_dir
    files = []
    for path in sorted(p for p in lib.rglob("*") if p.is_file() and not p.is_symlink() and p.parent != lib):
        data = path.read_bytes()
        files.append([path.relative_to(lib).as_posix(), hashlib.sha256(data).hexdigest(), len(data)])
    kv = {k: v for k, v in w.conn.execute("SELECT key, value FROM kv ORDER BY key") if RECORDED.fullmatch(k)}
    units = {phone.unit_id(s): phone.unit_digest(w.conn, w.cfg, s) for s in list_songs(w.conn)}
    info = {path: (lib / path).read_text(encoding="utf-8") for path, _, _ in files if path.endswith("/info.json")}
    return {"failed": made.failed, "files": files, "kv": kv, "units": units, "info": info}


def _assert_phone_writes(out: dict[str, Any]) -> None:
    """What the phone never writes: a PDF, a PDF's record, the to-do page's record."""
    assert not [p for p, _, _ in out["files"] if p.endswith(".pdf")], out["files"]
    for path, text in out["info"].items():
        assert json.loads(text)["render"] is None, path


def run_case(root: Path, name: str) -> dict[str, Any]:
    w = World(root / name)
    try:
        steps = CASES[name](w)
        _settle(w)
        fixture = _fixture(w)
        outs = []
        for step in steps:
            if "render" in step:
                out = _out(w, phone.phone_render(w.conn, w.cfg, song_ids=step["render"]))
                _assert_phone_writes(out)
                outs.append(out)
            elif "drop" in step:
                song_id, file = step["drop"]
                library.drop_file(w.conn, w.cfg.library_dir, song=get_song(w.conn, song_id), name=file)
            else:
                (w.cfg.library_dir / step["delete"]).unlink()
        return {"fn": "phone_render", "case": name, "args": [fixture, steps], "out": outs}
    finally:
        w.close()


def render_records(root: Path) -> list[dict[str, Any]]:
    return [{"fn": "constants", "out": CONSTANTS}] + [run_case(root, name) for name in CASES]


def test_render_vectors_are_render_pys_page_path_with_no_pdf(tmp_path):
    check(VIEWER_VECTORS / "render.jsonl", jsonl(render_records(tmp_path), corpus="viewer/render", made_by=MADE_BY))


# --- the cases reach what they are for ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def records(tmp_path_factory) -> dict[str, dict[str, Any]]:
    return {r["case"]: r for r in render_records(tmp_path_factory.mktemp("render"))[1:]}


def _names(out: dict[str, Any]) -> set[str]:
    return {path.rsplit("/", 1)[1] for path, _, _ in out["files"]}


def test_a_version_page_and_a_tab_page_go_once_they_leave(records):
    first, last = records["versions"]["out"]
    assert {"version-46191.html", "version-46192.html", "sheet.html", "sheet (auto).html"} <= _names(first)
    assert "version-46192.html" not in _names(last) and "version-46191.html" in _names(last)
    first, last = records["harmonica"]["out"]
    assert {"harmonica-1.html", "harmonica-2.html", "harmonica-3.html"} <= _names(first)
    assert not {"harmonica-1.html", "harmonica-2.html"} & _names(last) and "harmonica-3.html" in _names(last)


def test_every_page_is_recorded_with_the_unit_it_was_made_of(records):
    for name, record in records.items():
        for out in record["out"]:
            for key, text in out["kv"].items():
                if key.startswith("render:files:"):
                    unit = out["units"]
                    assert all(set(e) == {"sha256", "size", "unit"} for e in json.loads(text).values()), (name, key)
                    assert {e["unit"] for e in json.loads(text).values()} <= set(unit.values()), (name, key)


def test_the_own_version_is_rewritten_once_and_lyrics_go_on_an_auto_sheet(records):
    first, again = records["own_versions"]["out"]
    rewritten = json.loads(first["kv"]["keys:own_versions"])["rewritten"]
    assert list(rewritten.values()) == [["key=B&capo=2", "key=Bm&capo=2"]]
    assert again["kv"]["keys:own_versions"] == first["kv"]["keys:own_versions"] and again["units"] == first["units"]
    fixture, _ = records["auto_sheets"]["args"]
    raws = [json.loads(r["row"]["raw"]) for r in fixture if r.get("table") == "versions"]
    assert {"lyrics": "none", "key": "C"} in raws
    (out,) = records["auto_sheets"]["out"]
    info = next(json.loads(t) for p, t in out["info"].items() if "Lyrics Came Later" in p)
    assert info["lyrics_from"] == {"source": "megalobiz", "href": "https://megalobiz.com/lrc/maker/synthetic.51234567"}


def test_the_phone_records_each_songs_script_and_skips_what_it_must(records):
    (out,) = records["chinese"]["out"]
    scripts = sorted(json.loads(v).get("script") for k, v in out["kv"].items() if k.endswith(":phone"))
    assert scripts == ["simplified", "traditional"]
    (out,) = records["other_sheets"]["out"]
    assert out["failed"] == ["Placeholder Band - Unreadable Sheet"]
    assert not [p for p, _, _ in out["files"] if "Ignored Song" in p and not p.endswith((".txt", ".json"))]
    assert [p for p, _, _ in out["files"] if p.endswith("Nothing Kept/info.json")]


def test_the_vectors_are_within_reason():
    path = VIEWER_VECTORS / "render.jsonl"
    if path.is_file() and not os.environ.get("CARACOLE_CORPUS"):
        assert path.stat().st_size < 400_000
