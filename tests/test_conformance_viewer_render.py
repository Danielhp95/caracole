"""The phone's own pages, for :viewer's viewer.render (``PhoneRender``): render.py's page path with no PDF, as
tests/helpers/phone_render.py runs it, over fixture libraries, so that the phone writes and records what it does for
the same library.

``vectors/viewer/render.jsonl``, each record one of:

- ``constants``: what render.py, songs.py, inbox.py, library.py and keys.py name that the phone's render names too,
  read from the modules (``CONSTANTS``): kv's prefixes and keys, the sheets' names and their outputs', the harmonica
  tabs' names and pages', the lyrics sites that ask a link back, phone_render's record's suffix, and what a viewer's
  ``kinds`` reads (render.py ``_kinds_data``: the kinds in the card's order, the files' names, the scores' formats,
  the inbox's source).
- ``lyrics_key``: ``args`` ``[text]``, ``out`` ``autochords.sheet_lyrics.lyrics_key(text)``, the key of the words an
  auto sheet was made over, which both sides write into its version's raw (so into the song's unit): the texts of
  ``LYRICS_KEY_TEXTS``, each what could read otherwise in Kotlin (Python's whitespace at a line's ends and inside it,
  line endings, characters that aren't whitespace, blank runs, past the BMP, NFC and NFD).
- ``phone_render``: ``args`` ``[fixture, steps]``, a library (``helpers.corpus.dump_fixture``'s records: its
  database's rows, its kv, the phone's overrides as ``phone_overrides`` rows of overrides.toml, and the files of its
  songs' folders) and what is done to it in turn, each step one of ``{"render": song ids or null}`` (``phone_render``
  of those songs, of every song for null; the phone's ``PhoneRender.render`` of them), ``{"drop": [song id, name]}``
  (``library.drop_file``: the file forgotten and deleted, as a fetch lets a version go) and ``{"delete": path}`` (a
  file of the library deleted from its folder, as on a synced device, its record kept); ``out`` a list, one entry a
  render step: ``{"failed": [display names], "files": [[path, sha256, size], …] (every file of the songs' folders,
  by path), "kv": {key: text} (every record of render.py's and the phone's: render:files:*, render:progressions:*,
  render:*:phone, keys:own_versions), "units": {unit: digest} (each song's, which a changed file, version or override
  moves), "info": {path: text} (each info.json)}``; and for the cases of ``RAW_CASES`` ``"raws": {"<song id>/<tab
  id>": 16 hex}``, each auto version's raw text as SQLite holds it, by its SHA-256 (the units' canonical digests are
  blind to a raw's member order, which tells whether plain lyrics went on a heard sheet before its re-lay or after).

The cases (``CASES``) between them reach: a UG sheet and its key, and its timed lyrics, too few lines to light its page;
the versions kept beside the sheet (their pages, one dropped once it leaves), the song's UG versions listed with the one
and a ``[pin]``, a Guitar Pro file linked, the song's timed lyrics lighting the sheet's page, its auto sheet's and a
kept version's (viewer/sung.py: their data's ``sung``), an auto sheet beside the human one (no export, the song's
``[version]`` there without its shapes and swaps), then retired (its .cho and page gone, and the PDF names of it,
whatever is there); harmonica tabs (their pages, the harp the sheet's viewer starts on, each page dropped once its tab
leaves or its text is gone); an own version kept by a major letter alone on a sheet now read minor, rewritten once (kv
``keys:own_versions``), and one moved by ``[transpose]``; an auto sheet that takes lyrics that came after it
(``with_plain_lyrics``, its version's ``raw`` lyrics "plain"), one beside a human sheet that takes none, one made from a
YouTube video's audio (the video drawn from the icons, its credit off the viewer); auto sheets that keep what was heard,
laid out again over the words that came since before any page is made (``relay_onto_sheets``), one up to date left; Chinese sheets in Simplified and in
Traditional characters (the phone's script record); LaCuerda's sheet; a sheet that can't be read (the song failed); a
song with no sheet, and one ignored; a library that holds the computer's PDFs and their records (never linked, read or
deleted: info.json's ``render`` null), whose human sheet then leaves (its .cho and page gone, the PDFs left); a ukulele
sheet and every other kind a song keeps (Guitar Pro and Power Tab files, a text tab, a game music tab, a score in three
formats), which its page's ``kinds`` names in the card's order, one let go.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
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
from caracole.autochords.sheet_lyrics import lyrics_key
from caracole.chordpro import to_chordpro
from caracole.config import load_config
from caracole.icons import INBOX, YOUTUBE
from caracole.lyrics import Lyrics
from caracole.overrides import SONG_TABLES, load_overrides, song_entries
from caracole.songs import get_song, list_songs, update_song
from caracole.ug.page import strip_markup
from caracole.versions import set_coverage, upsert_version
from caracole.viewer import page
from caracole.viewer.sheet import parse_sheet

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
    "KINDS": list(render._KINDS),
    "KIND_GUITAR": render._KIND_GUITAR.pattern,
    "KIND_SCORE": render._KIND_SCORE.pattern,
    "GAMETAB_FILE": inbox.GAMETAB_FILE.pattern,
    "TAB": render._TAB,
    "SCORE_FORMATS": [list(item) for item in render._SCORE_FORMATS.items()],  # in order: the card lists them so
    "INBOX": INBOX,
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
             names: tuple[str, str] = ("sheet.txt", "sheet.json"), rank: int = 1, version: int = 1,
             kind: str = "chords") -> int:
    """A UG chords sheet kept as the fetch keeps one: its text, and its JSON with the raw content and the page's meta
    (``names``: a version kept beside it, ``version-<tab>.txt`` and ``.json``); ``kind`` "ukulele" for one of UG's
    Ukulele Chords."""
    raw = version_dict(tab, song=song.title, artist=song.artist, version=version,
                       **({"tonality_name": tonality} if tonality is not None else {}))
    vid = _version(w, song, "ug", str(tab), kind, raw=raw, url=raw["tab_url"], version=version)
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


def sung_lrc(markup: str) -> str:
    """Timed lyrics of a UG sheet's sung lines (the lines its page draws with words: ``page._drawn_lines`` of its
    .cho), 4 s apart from 00:00.00, as LRCLIB's would time them."""
    lines = [line for line in page._drawn_lines(parse_sheet(to_chordpro(markup, title="", artist=""))) if line]
    return "".join(f"[00:{4 * n:02d}.00]{line}\n" for n, line in enumerate(lines))


def store_lyrics(w: World, song, plain: str, *, provider: str = "lrclib", url: str | None = None,
                 synced: str | None = None) -> None:
    lyrics = Lyrics(plain=plain, synced=synced, instrumental=False, duration=None, lrclib_id=None, raw={},
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
    "[tab][ch]G[/ch]                 [ch]D[/ch]\nand more of them[/tab]\n"
    "[tab][ch]Em[/ch]                [ch]F#[/ch]\nand back again[/tab]\n"
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
    # its timed lyrics: three sung lines, too few to light (viewer/sung.py MIN_LINES), so its page has no sung
    store_lyrics(w, song, strip_markup(SODA), synced=sung_lrc(SODA))
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
    # its timed lyrics, four sung lines, which light the sheet's page, its auto sheet's and version 46191's alike
    store_lyrics(w, song, strip_markup(HOTEL), synced=sung_lrc(HOTEL))
    auto_sheet(w, song, synced=sung_lrc(HOTEL))
    w.overrides('[pin]\n"Eagles - Hotel California" = ['
                f'"{UG}eagles/hotel-california-chords-46190"]\n'
                '\n[version]\n"Eagles - Hotel California" = "key=Am&capo=2&alt=E7.E&at=Am.x-0-2-2-1-0"\n')
    return [{"render": None}, {"drop": [song.id, "version-46192.txt"]}, {"drop": [song.id, "version-46192.json"]},
            {"render": [song.id]}, {"drop": [song.id, songs.AUTO_SHEET]}, {"render": [song.id]}]


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
    both = add_song(w.conn, "Placeholder Band", "Both Sheets", added_at="2026-10-03T00:00:00Z")
    ug_sheet(w, both, SODA, tab=93002, tonality="G")
    auto_sheet(w, both, synced=None, raw={"lyrics": "none"}, source="Audio from a purchase (synthetic)")
    store_lyrics(w, both, "words that came later\nbeside a human sheet")
    # an auto sheet made over a transcript: it lights its lines by the transcript, which is no lyrics of the song's
    heard = add_song(w.conn, "Placeholder Band", "Heard Not Read", added_at="2026-10-04T00:00:00Z")
    transcript = "".join(f"[00:{4 * n + 2:02d}.00]{line}\n" for n, line in enumerate(
        ["made up words to sing", "only for the test", "and a second verse", "heard on the audio", "and no more"]))
    auto_sheet(w, heard, synced=transcript, source="Audio from a purchase (synthetic)",
               raw={"lyrics": "synced", "lyrics_source": "transcript", "transcript": transcript,
                    "transcript_made_at": "2026-11-20T01:00:00Z"})
    return [{"render": None}]


def case_relaid(w: World) -> list[dict]:
    """Auto sheets that keep what was heard, laid out again over the words that came since, before any page is made
    (render_all's ``relay_onto_sheets`` after ``lyrics_onto_sheets``): one the phone made over none, timed lyrics
    come; one another caracole made from a video's audio, plain lyrics come; one up to date, left as it is."""
    from caracole.autochords.sheet import Heard, Maker, make_sheet, raw_of
    from caracole.youtube import Video

    heard = Heard([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G"), ChordSegment(8.0, 12.0, "Am")],
                  BEATS, BEATS[::4], 12.0)
    phone = Maker("phone", "f0f0f0f0f0f0f0f0", {"chords": "btc_large_voca@0123456789abcdef"},
                  "onnxruntime 1.27.1", "song.mp3", "00112233aabbccdd")
    for title, video, words in (("Relaid On Timed Words", None, None),
                                ("Relaid From A Video", VIDEO, None),
                                ("Up To Date", None, SYNCED)):
        song = add_song(w.conn, "Placeholder Band", title, added_at=f"2026-10-0{len(list_songs(w.conn)) + 1}T00:00:00Z")
        if words is not None:
            update_song(w.conn, song.id, lyrics_status="found", lyrics_json=Lyrics(
                plain="made up words to sing\nonly for the test", synced=words, instrumental=False, duration=12.0,
                lrclib_id=None, raw={}).to_json())
        song = get_song(w.conn, song.id)
        clip = Video.from_json(video) if video else None
        made = make_sheet(song, heard, source=youtube_credit(clip.title, clip.channel, clip.id) if clip else None)
        vid = _version(w, song, "auto", str(song.id), "auto", raw=raw_of(song, made, video=clip, maker=phone),
                       rating=0, votes=0)
        _keep(w, song, vid, songs.AUTO_SHEET, made.text)
    later = list_songs(w.conn)
    update_song(w.conn, later[-1].id, lyrics_status="found", lyrics_json=Lyrics(
        plain="made up words to sing\nonly for the test", synced=SYNCED, instrumental=False, duration=12.0,
        lrclib_id=None, raw={}).to_json())
    store_lyrics(w, later[-2], "made up words to sing\nonly for the test\n\nand a second verse")
    return [{"render": None}, {"render": None}]


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


def case_computers_pdfs(w: World) -> list[dict]:
    song = add_song(w.conn, "Placeholder Band", "Sheets Leave")
    ug_sheet(w, song, SODA, tab=93001, tonality="G")
    folder = w.folder(song)
    (folder / "sheet.pdf").write_bytes(b"%PDF-1.4 the computer's (synthetic)\n")
    (folder / songs.TRADITIONAL_PDFS[songs.HUMAN_SHEET]).write_bytes(b"%PDF-1.4 the computer's, Traditional\n")
    record = {"source_sha": "0" * 64, "transpose": 0, "font": None, "fonts": None, "style": "s", "pdf": "sheet.pdf",
              "pdf_text": 1, "printed_sha": "0" * 64, "pdf_sha256": "0" * 64, "pdf_size": 36}
    db.kv_set_json(w.conn, f"render:{song.id}", record)
    db.kv_set_json(w.conn, f"render:{song.id}:trad", {**record, "pdf": songs.TRADITIONAL_PDFS[songs.HUMAN_SHEET]})
    return [{"render": None}, {"drop": [song.id, "sheet.txt"]}, {"drop": [song.id, "sheet.json"]}, {"render": None}]


def case_kinds(w: World) -> list[dict]:
    """A ukulele sheet and every other kind a song keeps, which its page names (render.py ``_kinds_data``), in the
    card's order, never by name (guitar-10 after guitar-2, score-1.mid after score-1.mscz); then its text tab let
    go."""
    song = add_song(w.conn, "Placeholder Band", "Every Kind")
    ug_sheet(w, song, SODA, tab=94001, tonality="G", kind="ukulele")
    for name, data, provider, kind, tab_id in (
            ("guitar-1.gp5", b"FICHIER GUITAR PRO v5.00 synthetic", "gtptabs", "guitar-pro", "1202"),
            ("guitar-2.ptb", b"ptab synthetic", "inbox", "power", "power"),
            ("guitar-10.gp4", b"FICHIER GUITAR PRO v4.06 synthetic", "inbox", "guitar-pro", "guitar-pro"),
            ("tab.txt", "e|--0--| synthetic\n", "ug", "tabs", "94002"),
            ("gametab-1.txt", "e|--3--| synthetic\n", "gametabs", "gametab", "synthetic-game/main-theme"),
            ("score-1.pdf", b"%PDF-1.4 a synthetic score\n", "inbox", "score", "score"),
            ("score-1.mscz", b"PK synthetic score", "inbox", "score", "score"),
            ("score-1.mid", b"MThd synthetic score", "inbox", "score", "score")):
        _keep(w, song, _version(w, song, provider, tab_id, kind, slot="guitar"), name, data)
    return [{"render": None}, {"drop": [song.id, "tab.txt"]}, {"render": [song.id]}]


CASES = {
    "ug_sheet": case_ug_sheet,
    "versions": case_versions,
    "harmonica": case_harmonica,
    "own_versions": case_own_versions,
    "auto_sheets": case_auto_sheets,
    "relaid": case_relaid,
    "chinese": case_chinese,
    "other_sheets": case_other_sheets,
    "computers_pdfs": case_computers_pdfs,
    "kinds": case_kinds,
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


# The cases whose outs also hold each auto version's raw as SQLite holds it (its text's SHA-256, 16 hex): the units'
# digests are of canonical JSON, blind to the order of a raw's members, which tells whether the plain lyrics were put
# on a heard sheet before or after it was laid out again.
RAW_CASES = ("relaid",)


def _raws(w: World) -> dict[str, str]:
    rows = w.conn.execute("SELECT song_id, tab_id, raw FROM versions WHERE provider = 'auto' ORDER BY song_id, tab_id")
    return {f"{song_id}/{tab_id}": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] for song_id, tab_id, raw in rows}


def _out(w: World, made: phone.PhoneRendered, case: str = "") -> dict[str, Any]:
    lib = w.cfg.library_dir
    files = []
    for path in sorted(p for p in lib.rglob("*") if p.is_file() and not p.is_symlink() and p.parent != lib):
        data = path.read_bytes()
        files.append([path.relative_to(lib).as_posix(), hashlib.sha256(data).hexdigest(), len(data)])
    kv = {k: v for k, v in w.conn.execute("SELECT key, value FROM kv ORDER BY key") if RECORDED.fullmatch(k)}
    units = {phone.unit_id(s): phone.unit_digest(w.conn, w.cfg, s) for s in list_songs(w.conn)}
    info = {path: (lib / path).read_text(encoding="utf-8") for path, _, _ in files if path.endswith("/info.json")}
    out = {"failed": made.failed, "files": files, "kv": kv, "units": units, "info": info}
    if case in RAW_CASES:
        out["raws"] = _raws(w)
    return out


def _assert_phone_writes(out: dict[str, Any], fixture: list[dict]) -> None:
    """What the phone never writes: a PDF (those the fixture held stay as they were), a PDF's record in info.json."""
    held = {r["file"]: base64.b64decode(r["base64"]) for r in fixture if r.get("file", "").endswith(".pdf")}
    pdfs = {p: sha for p, sha, _ in out["files"] if p.endswith(".pdf")}
    assert pdfs == {p: hashlib.sha256(data).hexdigest() for p, data in held.items() if p in pdfs}, out["files"]
    assert set(pdfs) <= set(held), out["files"]
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
                out = _out(w, phone.phone_render(w.conn, w.cfg, song_ids=step["render"]), name)
                _assert_phone_writes(out, fixture)
                outs.append(out)
            elif "drop" in step:
                song_id, file = step["drop"]
                library.drop_file(w.conn, w.cfg.library_dir, song=get_song(w.conn, song_id), name=file)
            else:
                (w.cfg.library_dir / step["delete"]).unlink()
        return {"fn": "phone_render", "case": name, "args": [fixture, steps], "out": outs}
    finally:
        w.close()


# Each written as escapes, so that no editor folds them. Python's str.strip() takes U+00A0, U+3000, a form feed,
# U+0085, U+2028 and U+2029 off a line's ends; inside a line they stay (the text is split on LF alone, after CRLF and
# CR are read as LF); U+FEFF and U+200B are no whitespace to it.
LYRICS_KEY_TEXTS = [
    "Walking down the river road\nSinging to the morning light",
    "\u00a0Walking down\u00a0the river\u00a0\n\u3000Singing\u3000to the light\u3000",
    "Walking\fdown\nthe\u2028river\nroad\u2029home\nand\u0085back",
    "\fWalking down\f\n\u2028the river\u2028\n\u2029road\u2029\n\u0085home\u0085",
    "Walking down\r\nthe river\rroad\nhome\r\n\r\nagain\r",
    "\ufeffWalking down\nthe\u200briver road\u200b",
    "\n\n\nWalking down\n\n\n\nthe river\n \n\t\n\nroad\n\n\n",
    "   \n\t\nWalking down\n    \nthe river",
    "",
    " \t\n\u00a0\n\u3000\r\n",
    "\u7b2c\u4e00\u884c\u6b4c\u8bcd\u5728\u8fd9\u91cc\n\n\u7b2c\u4e8c\u884c\u6b4c\u8bcd\u3000\u5728\u8fd9\u91cc",
    "Walking down \U0001f3b8 the river\n\U00020000 road",
    "Caf\u00e9 du r\u00e9veil",
    "Cafe\u0301 du re\u0301veil",
]


def render_records(root: Path) -> list[dict[str, Any]]:
    return ([{"fn": "constants", "out": CONSTANTS}]
            + [{"fn": "lyrics_key", "args": [text], "out": lyrics_key(text)} for text in LYRICS_KEY_TEXTS]
            + [run_case(root, name) for name in CASES])


def test_render_vectors_are_render_pys_page_path_with_no_pdf(tmp_path):
    check(VIEWER_VECTORS / "render.jsonl", jsonl(render_records(tmp_path), corpus="viewer/render", made_by=MADE_BY))


# --- the cases reach what they are for ---------------------------------------------------------------------------


def test_the_words_keys_pin_what_python_strips_and_what_it_keeps():
    key = dict(zip(LYRICS_KEY_TEXTS, map(lyrics_key, LYRICS_KEY_TEXTS), strict=True))
    plain = lyrics_key("Walking down the river road\nSinging to the morning light")
    assert lyrics_key("Walking down\u00a0the river\nSinging\u3000to the light") == key[LYRICS_KEY_TEXTS[1]]
    assert lyrics_key("\fWalking down\f") == lyrics_key("Walking down")  # a form feed is whitespace at the ends
    assert lyrics_key("Walking down\nthe river\nroad\nhome\n\nagain") == key[LYRICS_KEY_TEXTS[4]]
    assert key[LYRICS_KEY_TEXTS[5]] != lyrics_key("Walking down\nthe river road")  # BOM and ZWSP are kept
    assert key[LYRICS_KEY_TEXTS[6]] == lyrics_key("Walking down\n\nthe river\n\nroad")
    assert key[""] == key[LYRICS_KEY_TEXTS[9]] == hashlib.sha256(b"").hexdigest()[:16]
    assert key[LYRICS_KEY_TEXTS[12]] != key[LYRICS_KEY_TEXTS[13]]  # NFC and NFD: other bytes, other words
    assert len(set(key.values())) == len(key) - 1 and plain == key[LYRICS_KEY_TEXTS[0]]
    # Inside a line, the "line breaks" Python's splitlines knows are no breaks here
    assert key[LYRICS_KEY_TEXTS[2]] != lyrics_key("Walking\ndown\nthe\nriver\nroad\nhome\nand\nback")



@pytest.fixture(scope="module")
def records(tmp_path_factory) -> dict[str, dict[str, Any]]:
    return {r["case"]: r for r in render_records(tmp_path_factory.mktemp("render")) if r["fn"] == "phone_render"}


def _names(out: dict[str, Any]) -> set[str]:
    return {path.rsplit("/", 1)[1] for path, _, _ in out["files"]}


def test_a_version_page_and_a_tab_page_go_once_they_leave(records):
    first, last, _ = records["versions"]["out"]
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


def test_an_auto_sheet_retires_and_a_human_sheet_leaves_as_on_the_phone(records):
    *_, retired = records["versions"]["out"]
    assert not {"sheet (auto).cho", "sheet (auto).html"} & _names(retired) and "sheet.html" in _names(retired)
    first, gone = records["computers_pdfs"]["out"]
    pdfs = {"sheet.pdf", "sheet (Traditional).pdf"}
    assert pdfs | {"sheet.cho", "sheet.html"} <= _names(first)
    assert pdfs <= _names(gone) and not {"sheet.cho", "sheet.html"} & _names(gone)
    for out in (first, gone):
        assert all(json.loads(t)["render"] is None for t in out["info"].values())


def test_an_auto_sheet_beside_a_human_one_takes_no_lyrics(records):
    fixture, _ = records["auto_sheets"]["args"]
    (out,) = records["auto_sheets"]["out"]
    before = {r["file"]: base64.b64decode(r["base64"]) for r in fixture if "file" in r}
    after = {p: sha for p, sha, _ in out["files"]}
    auto = next(p for p in before if p.endswith("Both Sheets/sheet (auto).txt"))
    assert after[auto] == hashlib.sha256(before[auto]).hexdigest()
    raws = [json.loads(r["row"]["raw"]) for r in fixture if r.get("table") == "versions"]
    assert raws.count({"lyrics": "none"}) == 1  # its version's lyrics stay "none"


def test_the_kinds_case_names_a_ukulele_sheet_and_every_kind_but_the_one_let_go(tmp_path):
    run_case(tmp_path, "kinds")
    page = next(tmp_path.rglob("Every Kind/sheet.html")).read_text("utf-8")
    kinds = json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', page, re.S)[1])["kinds"]
    assert (kinds["sheet"], kinds["page"]) == ("ukulele", "sheet.html")
    assert [(g["kind"], [i["name"] for i in g["items"]]) for g in kinds["groups"]] == [
        ("guitar", ["guitar-1.gp5", "guitar-2.ptb", "guitar-10.gp4"]), ("gametab", ["gametab-1.txt"]),
        ("score", ["score-1.mscz", "score-1.pdf", "score-1.mid"])]


def _song_data(page_path: Path) -> dict[str, Any]:
    return json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>',
                                page_path.read_text("utf-8"), re.S)[1])


def test_timed_lyrics_light_the_sheets_its_auto_sheets_and_a_versions_page_and_too_few_light_none(tmp_path):
    for name, lit, unlit in (("versions", ("sheet.html", "sheet (auto).html", "version-46191.html"),
                              ("version-46192.html",)),
                             ("ug_sheet", (), ("sheet.html",))):
        w = World(tmp_path / name)
        try:
            CASES[name](w)
            _settle(w)
            phone.phone_render(w.conn, w.cfg, song_ids=None)
            folder = w.folder(list_songs(w.conn)[0])
            for page_name in lit:
                assert len(_song_data(folder / page_name)["sung"]) >= 4, (name, page_name)
            for page_name in unlit:
                assert "sung" not in _song_data(folder / page_name), (name, page_name)
        finally:
            w.close()


def test_the_vectors_are_within_reason():
    path = VIEWER_VECTORS / "render.jsonl"
    if path.is_file() and not os.environ.get("CARACOLE_CORPUS"):
        assert path.stat().st_size < 400_000
