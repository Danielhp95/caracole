"""overrides.toml on the phone: what overrides.py reads and writes, for the Kotlin lane overrides-model (core.library's
``Overrides``, ``OverrideWriters``, ``OverrideUrls`` and the picks) to agree with.

The phone holds overrides.toml as table ``phone_overrides`` (phone.sql), a row an entry: ``{tbl, key, written,
value}``, a song's table and its identity key (or ``alias`` and ``artist_url`` with the artist's key, ``block`` with
the tab id), ``written`` the name overrides.toml writes the entry under, ``value`` the canonical JSON of the value as
``overrides.song_entries`` gives it (the alias's slugs, the artist's page, ``true`` for an ``[ignore]``d song or a
blocked tab). A file and its rows go both ways here:

- ``rows_of(path)``: an overrides.toml's rows, as the phone holds the entries it reads (one a song a table: the one
  that counts, under the name it is written under), sorted by table and key in code-point order (SQLite's);
- ``toml_of(rows)``: rows as an overrides.toml, each entry under its ``written`` name, in the rows' order, which
  ``load_overrides`` then reads as the phone's ``Overrides.read`` must read the rows.

**Vectors** (``vectors/library/``), a header, then a record a line:

- ``overrides_read.jsonl``: ``{fn: "caracole.overrides.load_overrides", case, rows, checks, out | err, message}``:
  ``out`` every field of ``Overrides`` as ``load_overrides`` reads ``toml_of(rows)`` (a set sorted in code-point
  order, a pair an array, a pick its fields), or the ``OverridesError`` it raises and its words (without the file's
  path). Each case's rows come from an overrides.toml written as a user or caracole writes one, and reading them
  gives what reading that file gives (asserted), but its ``tables``, which holds a table only while an entry is in
  it. ``checks``: each call the reader made to the viewer's checks, in order, ``{fn: "key_version" | "check_spec",
  arg, error}`` (``error`` the ValueError's words, or null), which the phone takes as parameters (its :core has no
  viewer); ``{fn: "caracole.overrides.artist_url_entry", rows, args: [keys], out: [key, address] | null}``.
- ``overrides_writes.jsonl``: ``{fn: "caracole.overrides.add_<table>" | "...remove_pin", case, rows, kw, checks,
  out: {returned, rows} | err, message}``: each writer run over ``toml_of(rows)`` with ``kw`` (Python's names; a set
  of tabs a sorted list), ``out.rows`` the file's ``rows_of`` after, whole, and ``returned`` what the writer returned
  (``remove_pin``'s bool; null for the rest); a refusal's class and words, the file left as it was (asserted).
  Every song's entries after are put back by ``put_song_entries`` (an alias's by ``put_alias``) into an empty file,
  which reads them back as given (asserted): what the phone writes, the computer takes as it is at a sync.
- ``override_urls.jsonl``: ``{fn, args: [text], out | err, message}``: overrides.py's address readers
  (``override_key``, ``tab_id_from_url``, ``pin_url``, ``artist_page_address``, ``_artist_url_value``,
  ``pasted_tab_id``, the three pick parsers with each pick's ``url`` (and ``path``), ``azlyrics_page_from_url``),
  youtube_urls.py's ``video_id_from_url`` and ug/sitemap.py's ``classify_tab_url`` (its row's fields, or why it has
  none), over every text of tests/test_overrides.py, tests/test_get.py and tests/test_sitemap.py that looks like an
  address or a song's name (harvested with ast, ``TAB + "…"`` joined), and some of this file's; and
  ``caracole.overrides.LaCuerdaPick.holds`` over a pick and a tab id.

The answers are the same on every run (``test_the_vectors_are_the_same_on_another_run``). Regenerate with
``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
import tomlkit

from helpers.corpus import VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_overrides.py"
LIBRARY = VECTORS / "library"
READ = LIBRARY / "overrides_read.jsonl"
WRITES = LIBRARY / "overrides_writes.jsonl"
URLS = LIBRARY / "override_urls.jsonl"
TESTS = Path(__file__).resolve().parent
HARVESTED = ("test_overrides.py", "test_get.py", "test_sitemap.py")


def canonical(value: Any) -> str:
    from caracole import canonical

    return canonical.dumps(value)


# --- an overrides.toml and the phone's rows of it ---------------------------------------------------------------


def written_names(path: Path) -> dict[str, dict[str, str]]:
    """The name each entry that counts is written under, by table and the key overrides.py reads it by (the last of
    a song written two ways, as the reader keeps the last)."""
    from caracole.normalize import slug_key
    from caracole.overrides import override_key

    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    names: dict[str, dict[str, str]] = {}
    for table, entries in data.items():
        if not isinstance(entries, dict):
            continue
        if table == "ignore":
            songs = entries.get("songs", [])
            for song in [songs] if isinstance(songs, str) else songs:
                names.setdefault(table, {}).setdefault(override_key(song), song)
        elif table in ("alias", "artist_url"):
            for name in entries:
                names.setdefault(table, {})[slug_key(name)] = name
        elif table != "block":
            for name in entries:
                names.setdefault(table, {})[override_key(name)] = name
    return names


def rows_of(path: Path) -> list[dict[str, str]]:
    """The phone's rows of the overrides.toml at ``path``, sorted by table and key (code points, as SQLite's
    BINARY collation sorts UTF-8)."""
    from caracole.overrides import SONG_TABLES, load_overrides, song_entries

    o = load_overrides(path)
    written = written_names(path)
    keys = sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore))
    rows = []
    for key in keys:
        entries = song_entries(o, key)
        for table in (*SONG_TABLES, "ignore"):
            if table in entries:
                rows.append({"tbl": table, "key": key, "written": written[table][key],
                             "value": canonical(entries[table])})
    for artist, slugs in o.alias.items():
        rows.append({"tbl": "alias", "key": artist, "written": written["alias"][artist],
                     "value": canonical(list(slugs))})
    for artist, page in o.artist_url.items():
        rows.append({"tbl": "artist_url", "key": artist, "written": o.artist_url_names.get(artist, artist),
                     "value": canonical(page)})
    for tab in sorted(o.block):
        rows.append({"tbl": "block", "key": str(tab), "written": str(tab), "value": canonical(True)})
    return sorted(rows, key=lambda r: (r["tbl"], r["key"]))


def _inline(value: Any) -> Any:
    if isinstance(value, dict):
        made = tomlkit.inline_table()
        for k, v in value.items():
            made[k] = _inline(v)
        return made
    return value


def toml_of(rows: list[dict[str, str]]) -> str:
    """Rows as overrides.toml: each entry under its ``written`` name, in the rows' order; ``[ignore] songs`` and
    ``[block] tab_ids`` a list of them."""
    doc = tomlkit.document()
    for row in rows:
        table, value = row["tbl"], json.loads(row["value"])
        if table not in doc:
            doc[table] = tomlkit.table()
        if table == "ignore":
            doc[table].setdefault("songs", tomlkit.array()).append(row["written"])
        elif table == "block":
            doc[table].setdefault("tab_ids", tomlkit.array()).append(int(row["key"]))
        else:
            doc[table][row["written"]] = _inline(value)
    return tomlkit.dumps(doc)


def fields(o) -> dict[str, Any]:
    """Every field of an ``Overrides`` as the corpus writes it: a set sorted (code points), a pair an array, a pick
    its fields."""
    return {
        "alias": {k: list(v) for k, v in o.alias.items()},
        "match": {k: list(v) for k, v in o.match.items()},
        "artist_url": dict(o.artist_url),
        "pin": {k: list(v) for k, v in o.pin.items()},
        "transpose": dict(o.transpose),
        "ignore": sorted(o.ignore),
        "block": sorted(o.block),
        "pin_urls": {k: list(v) for k, v in o.pin_urls.items()},
        "reject": {k: [list(p) for p in sorted(v)] for k, v in o.reject.items()},
        "artist_url_names": dict(o.artist_url_names),
        "youtube": dict(o.youtube),
        "lacuerda": {k: dataclasses.asdict(v) for k, v in o.lacuerda.items()},
        "harptabs": {k: dataclasses.asdict(v) for k, v in o.harptabs.items()},
        "gametabs": {k: dataclasses.asdict(v) for k, v in o.gametabs.items()},
        "azlyrics": dict(o.azlyrics),
        "version": dict(o.version),
        "harmonica": {k: {tab: (dict(s) if isinstance(s, dict) else s) for tab, s in v.items()}
                      for k, v in o.harmonica.items()},
        "tables": sorted(o.tables),
    }


@contextmanager
def checks_recorded() -> Iterator[list[dict[str, Any]]]:
    """Each call overrides.py makes to the viewer's checks (version.key_version, harptab.check_spec), in order, with
    the ValueError's words each raised (or null)."""
    import caracole.viewer.harptab as harptab
    import caracole.viewer.version as version

    calls: list[dict[str, Any]] = []
    real_key_version, real_check_spec = version.key_version, harptab.check_spec

    def recorded(name: str, real: Callable[[Any], Any]) -> Callable[[Any], Any]:
        def call(arg: Any) -> Any:
            entry = {"fn": name, "arg": arg if isinstance(arg, str) else dict(arg) if isinstance(arg, dict) else arg,
                     "error": None}
            calls.append(entry)
            try:
                return real(arg)
            except ValueError as e:
                entry["error"] = str(e)
                raise
        return call

    version.key_version = recorded("key_version", real_key_version)
    harptab.check_spec = recorded("check_spec", real_check_spec)
    try:
        yield calls
    finally:
        version.key_version, harptab.check_spec = real_key_version, real_check_spec


def _without_path(e: Exception, path: Path) -> str:
    text = str(e)
    return text[len(f"{path}: "):] if text.startswith(f"{path}: ") else text


# --- the read records -------------------------------------------------------------------------------------------

EVERY_TABLE = '''
[alias]
"Soda Stereo" = "Soda-Stereo"
"Los Prisioneros" = ["los-prisioneros", "The-Prisoners"]

[match]
"Soda Stereo - De Música Ligera" = "Soda-Stereo/De-Musica-Ligera"
"宋冬野 - 斑马，斑马" = "song-dongye/banma-banma"

[artist_url]
"Song Dongye (宋冬野)" = "https://www.ultimate-guitar.com/artist/634073?filter=chords"
"Joaquín Sabina" = "tabs.ultimate-guitar.com/tab/joaquin-sabina/19-dias-y-500-noches-chords-1234?ref=x"

[pin]
"Soda Stereo - Persiana Americana" = [
  "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460?app=1",
  " 85053 ",
  "www.ultimate-guitar.com/tab/4180894/#comments",
]
"Radiohead - Creep" = "http://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"

[transpose]
"Radiohead - Creep" = -2
"Soda Stereo - Persiana Americana" = 11

[ignore]
songs = ["Nobody - Nothing", "宋冬野 - 斑马，斑马 (Live)"]

[block]
tab_ids = [99, 101, 4242]

[reject]
"Radiohead - Creep" = ["Radiohead/Creep-Acoustic", "radiohead/high-and-dry"]

[youtube]
"Radiohead - Creep" = "https://youtu.be/XFkzRNyygfk"
"Soda Stereo - De Música Ligera" = "None"

[lacuerda]
"Estopa - Como Camarón" = "acordes.lacuerda.net/estopa/como_camaron-2.shtml?ref=1"
"Soda Stereo - De Música Ligera" = "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera/"
"Soda Stereo - Persiana Americana" = "https://lacuerda.net/soda_stereo/persiana_americana.shtml"

[harptabs]
"Billy Joel - Piano Man" = "www.harptabs.com/tab/23862/piano-man-c-harmonica?ref=1"

[gametabs]
"Yuzo Koshiro - Fillmore" = "https://www.gametabs.net/tabs/actraiser/fillmore/"

[azlyrics]
"Misc Musicals - Hadestown Wait For Me" = "azlyrics.com/lyrics/hadestown/waitforme.html?x=1"

[version]
"Soda Stereo - De Música Ligera" = "#t=2&mode=dorian&capo=0&at=3.1"
"Radiohead - Creep" = "key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6"

[harmonica]
"Cowboy Bebop - Spokey Dokey" = {"harmonica-1.txt" = "letters", "harmonica-2.txt" = {as = "signs", "*" = "bend"}}
'''

READ_CASES: dict[str, str] = {
    "every table, as a user and caracole write them": EVERY_TABLE,
    "nothing": "",
    "a table with no entry left in it is no table on the phone": '[match]\n# "A - B" = "a/b"\n\n[pin]\n',
    "a song written two ways: the last entry counts, rejections of both": '''
[match]
"radiohead - creep" = "radiohead/creep"
"Radiohead - Creep" = "radiohead/creep-acoustic"

[pin]
"RADIOHEAD - CREEP" = "4169"
"Radiohead - Creep" = ["85053", "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"]

[reject]
"radiohead - creep" = "radiohead/high-and-dry"
"Radiohead - Creep" = ["radiohead/karma-police", "Radiohead/High-And-Dry"]

[harmonica]
"cowboy bebop - spokey dokey" = {"harmonica-1.txt" = "letters"}
"Cowboy Bebop - Spokey Dokey" = {"harmonica-2.txt" = "barrett"}

[alias]
"soda stereo" = "soda-stereo"
"Soda Stereo" = ["soda", "stereo"]
''',
    "names beyond the BMP, and rejections the UTF-16 order sorts otherwise": '''
[reject]
"𝄞 Band - 𝄞 Song" = ["/x", "\U00020000/y", "abc/z", "ábc/w"]

[match]
"𝄞 Band - 𝄞 Song" = "\U00020000/"

[ignore]
songs = "\U00020000 - "
''',
}

# Rows the phone could hold that overrides.py refuses (each written by hand, as a broken sync could leave one).
BAD_ROWS: dict[str, list[tuple[str, str, str, Any]]] = {
    "semitones past 11": [("transpose", "radiohead/creep", "Radiohead - Creep", 12)],
    "semitones as text": [("transpose", "radiohead/creep", "Radiohead - Creep", "2")],
    "semitones as a truth": [("transpose", "radiohead/creep", "Radiohead - Creep", True)],
    "semitones with a fraction": [("transpose", "radiohead/creep", "Radiohead - Creep", 2.5)],
    "a match with no slash": [("match", "radiohead/creep", "Radiohead - Creep", "radiohead")],
    "a match with two": [("match", "radiohead/creep", "Radiohead - Creep", "a/b/c")],
    "a match whose artist has no key": [("match", "radiohead/creep", "Radiohead - Creep", "---/creep")],
    "a match of punctuation, kept as it is": [("match", "radiohead/creep", "Radiohead - Creep", "!!!/&")],
    "a match as a number": [("match", "radiohead/creep", "Radiohead - Creep", 5)],
    "a pin that is no tab page": [("pin", "radiohead/creep", "Radiohead - Creep", ["https://example.com/tab/1"])],
    "a pin as a number": [("pin", "radiohead/creep", "Radiohead - Creep", 5)],
    "a pin list with a number": [("pin", "radiohead/creep", "Radiohead - Creep", ["85053", 4])],
    "a rejection with no slash": [("reject", "radiohead/creep", "Radiohead - Creep", ["radiohead"])],
    "a video that is a channel": [("youtube", "radiohead/creep", "Radiohead - Creep",
                                   "https://www.youtube.com/@radiohead")],
    "a video as a number": [("youtube", "radiohead/creep", "Radiohead - Creep", 7)],
    "a LaCuerda pick as a number": [("lacuerda", "estopa/como-camaron", "Estopa - Como Camarón", 5)],
    "a LaCuerda pick of its listing": [("lacuerda", "estopa/como-camaron", "Estopa - Como Camarón",
                                        "https://acordes.lacuerda.net/tabs/e/index0.html")],
    "a harptabs.com pick of tab 0": [("harptabs", "billy-joel/piano-man", "Billy Joel - Piano Man",
                                      "https://www.harptabs.com/tab/0/x")],
    "a gametabs.net pick of a game": [("gametabs", "yuzo-koshiro/fillmore", "Yuzo Koshiro - Fillmore",
                                       "https://gametabs.net/tabs/actraiser")],
    "an AZLyrics page of an artist": [("azlyrics", "radiohead/creep", "Radiohead - Creep",
                                       "https://www.azlyrics.com/r/radiohead.html")],
    "an AZLyrics page as a list": [("azlyrics", "radiohead/creep", "Radiohead - Creep", ["x"])],
    "a version as a number": [("version", "radiohead/creep", "Radiohead - Creep", 3)],
    "a version as a truth": [("version", "radiohead/creep", "Radiohead - Creep", True)],
    "a version that escapes no UTF-8": [("version", "radiohead/creep", "Radiohead - Creep", "t=%ff")],
    "a version with a control character": [("version", "radiohead/creep", "Radiohead - Creep", "t=2\u0000")],
    "a version with one escaped": [("version", "radiohead/creep", "Radiohead - Creep", "t=2&x=%01")],
    "a version too long": [("version", "radiohead/creep", "Radiohead - Creep", "t=2&" + "x" * 1997)],
    "a version of 2000 characters beyond the BMP": [("version", "radiohead/creep", "Radiohead - Creep",
                                                     "t=2&a=" + "\U0001d11e" * 1994)],
    "a version whose key is none": [("version", "radiohead/creep", "Radiohead - Creep", "key=H")],
    "a version with a key and a t": [("version", "radiohead/creep", "Radiohead - Creep", "t=2&key=G")],
    "harmonica as a name": [("harmonica", "a/b", "A - B", "letters")],
    "harmonica of a tab with no number": [("harmonica", "a/b", "A - B", {"harmonica.txt": "letters"})],
    "harmonica read in no notation": [("harmonica", "a/b", "A - B", {"harmonica-1.txt": "staff"})],
    "harmonica with a symbol that means nothing": [("harmonica", "a/b", "A - B",
                                                    {"harmonica-1.txt": {"*": "squeak"}})],
    "an alias as a number": [("alias", "soda-stereo", "Soda Stereo", 5)],
    "an artist's page with no number": [("artist_url", "joaquin-sabina", "Joaquín Sabina",
                                         "https://www.ultimate-guitar.com/artist/joaquin_sabina")],
    "an artist's page as a bare number": [("artist_url", "joaquin-sabina", "Joaquín Sabina", "1234")],
    "two broken tables: the first in the reader's order": [
        ("version", "radiohead/creep", "Radiohead - Creep", 3),
        ("match", "radiohead/creep", "Radiohead - Creep", "radiohead"),
    ],
    "a version beside a good one, read in the rows' order": [
        ("version", "a/b", "A - B", "key=G"),
        ("version", "radiohead/creep", "Radiohead - Creep", "key=Gmin"),
    ],
}

# Of BAD_ROWS, those read as they are: at the edge of what a reader takes.
READ_AS_GIVEN = {"a version of 2000 characters beyond the BMP", "a match of punctuation, kept as it is"}

ARTIST_URL_ENTRIES = [
    ("by its own key", ["song-dongye"]),
    ("by a form of the name as written", ["宋冬野"]),
    ("by a key with no hyphens", ["songdongye"]),
    ("by none of these", ["radiohead", ""]),
    ("an empty key passed over", ["", "joaquin-sabina"]),
]


def read_records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.overrides import OverridesError, artist_url_entry, load_overrides

    records: list[dict[str, Any]] = []
    for n, (case, text) in enumerate(READ_CASES.items()):
        original = tmp / f"read-{n}.toml"
        original.write_text(text, encoding="utf-8")
        rows = rows_of(original)
        rebuilt = tmp / f"read-{n}-rows.toml"
        rebuilt.write_text(toml_of(rows), encoding="utf-8")
        with checks_recorded() as checks:
            read = load_overrides(rebuilt)
        mine = load_overrides(original)
        # The rows lose nothing of what the file says: the same reading, but a table with no entry in it.
        assert dataclasses.replace(mine, tables=read.tables) == read, case
        assert read.tables <= mine.tables
        records.append({"fn": "caracole.overrides.load_overrides", "case": case, "rows": rows, "checks": checks,
                        "out": fields(read)})
        if case.startswith("every table"):
            for keys_case, keys in ARTIST_URL_ENTRIES:
                found = artist_url_entry(read, keys)
                records.append({"fn": "caracole.overrides.artist_url_entry", "case": keys_case, "rows": rows,
                                "args": [keys], "out": list(found) if found else None})
    for n, (case, bad) in enumerate(BAD_ROWS.items()):
        rows = [{"tbl": t, "key": k, "written": w, "value": canonical(v)} for t, k, w, v in bad]
        path = tmp / f"bad-{n}.toml"
        path.write_text(toml_of(rows), encoding="utf-8")
        record = {"fn": "caracole.overrides.load_overrides", "case": case, "rows": rows}
        with checks_recorded() as checks:
            try:
                record["out"] = fields(load_overrides(path))
            except OverridesError as e:
                record.update(err="OverridesError", message=_without_path(e, path))
        assert ("err" in record) != (case in READ_AS_GIVEN), case
        records.append(record | {"checks": checks})
    return records


# --- the write records ------------------------------------------------------------------------------------------

BASE = '''
[alias]
"Soda Stereo" = "soda-stereo"

[match]
"radiohead - creep" = "radiohead/creep"

[artist_url]
"宋冬野" = "https://www.ultimate-guitar.com/artist/634073"

[pin]
"Soda Stereo - De Música Ligera" = [
  "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053",
  "https://tabs.ultimate-guitar.com/tab/4180894",
]

[reject]
"radiohead - creep" = ["radiohead/creep-acoustic"]

[lacuerda]
"estopa - como camarón" = "https://acordes.lacuerda.net/estopa/como_camaron"

[harptabs]
"billy joel - piano man" = "https://www.harptabs.com/tab/25/piano-man"

[gametabs]
"yuzo koshiro - fillmore" = "https://gametabs.net/tabs/actraiser/fillmore"

[version]
"radiohead - creep" = "t=1"

[harmonica]
"cowboy bebop - spokey dokey" = {"harmonica-1.txt" = "letters", "harmonica-2.txt" = "signs"}

[ignore]
songs = ["nobody - nothing"]

[block]
tab_ids = [99]
'''

WRITE_CASES: list[tuple[str, str, dict[str, Any]]] = [
    # add_match
    ("add_match", "a new song's, its reference keyed", {"display": "Blur - Song 2", "ug_ref": "Blur/Song-2"}),
    ("add_match", "the song written another way: its entry is the one given now",
     {"display": "Radiohead - Creep", "ug_ref": "Radiohead/Creep-Acoustic"}),
    ("add_match", "the same again, as written", {"display": "radiohead - creep", "ug_ref": "radiohead/creep"}),
    ("add_match", "the same again, written another way", {"display": "RADIOHEAD - CREEP", "ug_ref": "radiohead/creep"}),
    ("add_match", "a Chinese song", {"display": "宋冬野 - 斑马，斑马", "ug_ref": "song-dongye/banma-banma"}),
    ("add_match", "no song named", {"display": "Creep", "ug_ref": "radiohead/creep"}),
    ("add_match", "a song with no title", {"display": "Radiohead -  ", "ug_ref": "radiohead/creep"}),
    ("add_match", "no slash", {"display": "Blur - Song 2", "ug_ref": "blur"}),
    ("add_match", "two slashes", {"display": "Blur - Song 2", "ug_ref": "a/b/c"}),
    ("add_match", "an artist with no key", {"display": "Blur - Song 2", "ug_ref": "-/song-2"}),
    # add_pin
    ("add_pin", "a new song's, each address as a pin writes it",
     {"display": "Blur - Song 2", "urls": ["tabs.ultimate-guitar.com/tab/blur/song-2-chords-1234?ref=x#c", " 85053 ",
                                           "http://www.ultimate-guitar.com/tab/4180894/", "٣"]}),
    ("add_pin", "the song written another way: its pins replaced",
     {"display": "soda stereo - de música ligera", "urls": ["4180894"]}),
    ("add_pin", "no address", {"display": "Blur - Song 2", "urls": []}),
    ("add_pin", "an address that is no UG tab page", {"display": "Blur - Song 2",
                                                     "urls": ["85053", "https://example.com/tab/1"]}),
    ("add_pin", "UG's print page", {"display": "Blur - Song 2",
                                   "urls": ["https://tabs.ultimate-guitar.com/tab/print?id=85053"]}),
    ("add_pin", "a digit int() can't read", {"display": "Blur - Song 2", "urls": ["²"]}),
    ("add_pin", "no song named", {"display": "Song 2", "urls": ["85053"]}),
    # remove_pin
    ("remove_pin", "every pin", {"display": "Soda Stereo - De Música Ligera", "tabs": None}),
    ("remove_pin", "one of two, the song written another way",
     {"display": "SODA STEREO - DE MÚSICA LIGERA", "tabs": [85053]}),
    ("remove_pin", "both of two", {"display": "Soda Stereo - De Música Ligera", "tabs": [85053, 4180894]}),
    ("remove_pin", "a tab it hasn't pinned", {"display": "Soda Stereo - De Música Ligera", "tabs": [1]}),
    ("remove_pin", "no tab", {"display": "Soda Stereo - De Música Ligera", "tabs": []}),
    ("remove_pin", "a song with no pin", {"display": "Radiohead - Creep", "tabs": None}),
    ("remove_pin", "no song named", {"display": "Creep", "tabs": None}),
    # add_lacuerda, add_harptabs, add_gametabs
    ("add_lacuerda", "a new song's version", {"display": "Soda Stereo - De Música Ligera",
                                             "url": "lacuerda.net/soda_stereo/de_musica_ligera-3.shtml?x=1"}),
    ("add_lacuerda", "the song's first version, written another way: its name kept",
     {"display": "Estopa - Como Camarón", "url": "https://acordes.lacuerda.net/estopa/como_camaron.shtml"}),
    ("add_lacuerda", "the same song again", {"display": "Estopa - Como Camarón",
                                            "url": "https://acordes.lacuerda.net/estopa/como_camaron/"}),
    ("add_lacuerda", "LaCuerda's listing", {"display": "Estopa - Como Camarón",
                                           "url": "https://acordes.lacuerda.net/tabs/e/index0.html"}),
    ("add_lacuerda", "version 0", {"display": "Estopa - Como Camarón",
                                  "url": "https://acordes.lacuerda.net/estopa/como_camaron-0.shtml"}),
    ("add_lacuerda", "no song named", {"display": "Como Camarón",
                                      "url": "https://acordes.lacuerda.net/estopa/como_camaron"}),
    ("add_harptabs", "a new song's", {"display": "Radiohead - Creep",
                                     "url": "harptabs.com/tab/700/creep?ref=1"}),
    ("add_harptabs", "another tab, written another way: its name kept",
     {"display": "Billy Joel - Piano Man", "url": "https://www.harptabs.com/tab/23862/piano-man-c-harmonica/"}),
    ("add_harptabs", "the same tab again", {"display": "Billy Joel - Piano Man",
                                           "url": "https://www.harptabs.com/tab/25/piano-man"}),
    ("add_harptabs", "a page that is no tab's", {"display": "Billy Joel - Piano Man",
                                                "url": "https://www.harptabs.com/artist/1178/billy-joel"}),
    ("add_gametabs", "a new song's", {"display": "Hollow Knight - Resting Grounds",
                                     "url": "gametabs.net/tabs/hollow-knight/resting-grounds-2?ref=1"}),
    ("add_gametabs", "another tab, written another way: its name kept",
     {"display": "Yuzo Koshiro - Fillmore", "url": "https://www.gametabs.net/tabs/actraiser/fillmore-2/"}),
    ("add_gametabs", "the same tab again", {"display": "Yuzo Koshiro - Fillmore",
                                           "url": "https://gametabs.net/tabs/actraiser/fillmore"}),
    ("add_gametabs", "a game's page", {"display": "Yuzo Koshiro - Fillmore", "url": "https://gametabs.net/tabs/actraiser"}),
    # add_reject
    ("add_reject", "a new song's, each keyed once, in code-point order",
     {"display": "𝄞 Band - 𝄞 Song", "ug_refs": ["\U00020000/y", "/x", "Abc/Z", "abc/z", "ábc/w"]}),
    ("add_reject", "the song written another way: its list grows, its name kept",
     {"display": "Radiohead - Creep", "ug_refs": ["radiohead/karma-police", "Radiohead/Creep-Acoustic"]}),
    ("add_reject", "every one rejected already", {"display": "Radiohead - Creep",
                                                  "ug_refs": ["radiohead/creep-acoustic"]}),
    ("add_reject", "none", {"display": "Radiohead - Creep", "ug_refs": []}),
    ("add_reject", "one with no slash", {"display": "Radiohead - Creep", "ug_refs": ["radiohead/x", "creep"]}),
    ("add_reject", "none, for no song named", {"display": "Creep", "ug_refs": []}),
    # add_alias
    ("add_alias", "a new artist's", {"source_artist": "Los Prisioneros", "ug_artist": "Los-Prisioneros"}),
    ("add_alias", "another, written another way: the list grows, its name kept",
     {"source_artist": "SODA STEREO", "ug_artist": "Soda"}),
    ("add_alias", "one there already, by its key", {"source_artist": "Soda Stereo", "ug_artist": "Soda-Stereo"}),
    ("add_alias", "one whose key is empty", {"source_artist": "Blur", "ug_artist": "---"}),
    # add_ignore
    ("add_ignore", "a new song", {"display": "Blur - Song 2"}),
    ("add_ignore", "a song ignored already, written another way", {"display": "Nobody - Nothing"}),
    ("add_ignore", "no song named", {"display": "Song 2"}),
    # add_version
    ("add_version", "a new song's, its # dropped", {"display": "Blur - Song 2", "query": "  #t=2&mode=dorian  "}),
    # Two marks: add_version drops one and writes "#t=2", which the file then reads as "t=2" (song_entries' value).
    ("add_version", "two marks: the text the file then reads", {"display": "Blur - Song 2", "query": "##t=2"}),
    ("add_version", "a mark, then a space", {"display": "Blur - Song 2", "query": "# t=2"}),
    ("add_version", "a ? then a #", {"display": "Blur - Song 2", "query": "?#t=2"}),
    ("add_version", "the same again, two marks before it", {"display": "Radiohead - Creep", "query": "##t=1"}),
    ("add_version", "the song written another way: its name kept", {"display": "Radiohead - Creep", "query": "?t=3"}),
    ("add_version", "the same again", {"display": "Radiohead - Creep", "query": "t=1"}),
    ("add_version", "kept by its key", {"display": "Blur - Song 2",
                                        "query": "key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6"}),
    ("add_version", "a key that is none", {"display": "Blur - Song 2", "query": "key=H"}),
    ("add_version", "a capo past 11", {"display": "Blur - Song 2", "query": "key=G&capo=12"}),
    ("add_version", "taken out", {"display": "RADIOHEAD - CREEP", "query": None}),
    ("add_version", "none to take out", {"display": "Blur - Song 2", "query": None}),
    ("add_version", "a control character", {"display": "Blur - Song 2", "query": "t=1\x00&mode=dorian"}),
    ("add_version", "one escaped", {"display": "Blur - Song 2", "query": "t=1&x=%7f"}),
    ("add_version", "too long", {"display": "Blur - Song 2", "query": "t=1&" + "y" * 1997}),
    ("add_version", "2000 characters, at most", {"display": "Blur - Song 2", "query": "t=1&" + "y" * 1996}),
    ("add_version", "no song named", {"display": "Song 2", "query": "t=1"}),
    # add_harmonica
    ("add_harmonica", "a new song's tab", {"display": "Blues Traveler - Run-Around", "tab": "harmonica-1.txt",
                                          "reading": "brackets"}),
    ("add_harmonica", "a table of what its symbols mean", {"display": "Blues Traveler - Run-Around",
                                                         "tab": "harmonica-3.txt",
                                                         "reading": {"as": "signs", "*": "bend"}}),
    ("add_harmonica", "another tab of the song written another way: its name kept",
     {"display": "Cowboy Bebop - Spokey Dokey", "tab": "harmonica-3.txt", "reading": "legend"}),
    ("add_harmonica", "a tab read otherwise", {"display": "Cowboy Bebop - Spokey Dokey", "tab": "harmonica-1.txt",
                                              "reading": "barrett"}),
    ("add_harmonica", "the same again", {"display": "Cowboy Bebop - Spokey Dokey", "tab": "harmonica-1.txt",
                                        "reading": "letters"}),
    ("add_harmonica", "a tab taken out", {"display": "Cowboy Bebop - Spokey Dokey", "tab": "harmonica-2.txt",
                                         "reading": None}),
    ("add_harmonica", "a tab it hasn't", {"display": "Cowboy Bebop - Spokey Dokey", "tab": "harmonica-9.txt",
                                         "reading": None}),
    ("add_harmonica", "a song with no entry", {"display": "Blur - Song 2", "tab": "harmonica-1.txt",
                                              "reading": None}),
    ("add_harmonica", "a tab with no number", {"display": "Blur - Song 2", "tab": "harmonica.txt",
                                              "reading": "letters"}),
    ("add_harmonica", "a tab with no number, taken out", {"display": "Blur - Song 2", "tab": "harmonica.txt",
                                                         "reading": None}),
    ("add_harmonica", "a tab whose name ends as one's does", {"display": "Blur - Song 2",
                                                              "tab": "my harmonica-1.txt", "reading": "letters"}),
    ("add_harmonica", "no notation", {"display": "Blur - Song 2", "tab": "harmonica-1.txt", "reading": "staff"}),
    ("add_harmonica", "a symbol that means nothing", {"display": "Blur - Song 2", "tab": "harmonica-1.txt",
                                                    "reading": {"*": "squeak"}}),
    ("add_harmonica", "no song named", {"display": "Blur", "tab": "harmonica-1.txt", "reading": "letters"}),
]

# The cases that start from rows of their own, not BASE's.
EMPTY_CASES = {("add_harmonica", "a song with no entry")}

TWO_PINS = ("remove_pin", "both of two")


def _write_call(fn: str, path: Path, kw: dict[str, Any]) -> Any:
    import caracole.overrides as ov

    if fn == "remove_pin":
        return ov.remove_pin(path, kw["display"], None if kw["tabs"] is None else set(kw["tabs"]))
    if fn == "add_reject":
        return ov.add_reject(path, kw["display"], kw["ug_refs"])
    return getattr(ov, fn)(path, **kw)


def _reads_back(rows: list[dict[str, str]], tmp: Path) -> None:
    """Each song's entries of ``rows``, put by ``put_song_entries`` into an empty overrides.toml (an alias by
    ``put_alias``), read back as given: the computer takes what the phone wrote as it is."""
    from caracole.overrides import SONG_TABLES, load_overrides, put_alias, put_song_entries, song_entries

    songs: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in rows:
        if row["tbl"] in (*SONG_TABLES, "ignore"):
            written, entries = songs.setdefault(row["key"], (row["written"], {}))
            entries[row["tbl"]] = json.loads(row["value"])
    for key, (written, entries) in songs.items():
        path = tmp / "put.toml"
        path.write_text("", encoding="utf-8")
        put_song_entries(path, written, entries)
        assert song_entries(load_overrides(path), key) == entries, (key, entries)
    for row in rows:
        if row["tbl"] == "alias":
            path = tmp / "put.toml"
            path.write_text("", encoding="utf-8")
            put_alias(path, row["written"], json.loads(row["value"]))
            assert list(load_overrides(path).alias[row["key"]]) == json.loads(row["value"])


def write_records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.overrides import OverridesError

    base = tmp / "base.toml"
    base.write_text(BASE, encoding="utf-8")
    base_rows = rows_of(base)
    records = []
    for n, (fn, case, kw) in enumerate(WRITE_CASES):
        rows = [] if (fn, case) in EMPTY_CASES else base_rows
        path = tmp / f"write-{n}.toml"
        path.write_text(toml_of(rows), encoding="utf-8")
        before = path.read_bytes()
        record: dict[str, Any] = {"fn": f"caracole.overrides.{fn}", "case": case, "rows": rows, "kw": kw}
        refused: Exception | None = None
        with checks_recorded() as checks:  # the writer's own calls alone
            try:
                returned = _write_call(fn, path, kw)
            except (OverridesError, ValueError) as e:
                refused = e
        if refused is not None:
            assert path.read_bytes() == before, case  # a refusal writes nothing
            record.update(err=type(refused).__name__, message=_without_path(refused, path))
        else:
            after = rows_of(path)
            _reads_back(after, tmp)
            record["out"] = {"returned": returned, "rows": after}
        record["checks"] = checks
        records.append(record)
    return records


# --- the address records ----------------------------------------------------------------------------------------

_LOOKS = re.compile(r"ultimate-guitar|lacuerda|harptabs|gametabs|azlyrics|youtube|youtu\.be|/tab/|/artist/|/tabs/")

EXTRA_TEXTS = [
    "85053", " 85053 ", "٣٤", "²", "　 42 ", "0", "007", "", " ", "-5", "+5", "1_000",
    "HTTPS://TABS.ULTIMATE-GUITAR.COM/tab/85053", "https://TABS.Ultimate-Guitar.com/TAB/85053",
    "https://tabs.ultimate-guitar.com/tab/٣٤", "https://tabs.ultimate-guitar.com/tab/a/b-chords-٣",
    "https://[::1]/tab/1", "https://[tabs.ultimate-guitar.com/tab/1", "https://tabs.ultimate-guitar.com/tab/1\t2",
    "\n https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053/\n",
    "https://de.ultimate-guitar.com/tab/85053", "https://xyz.ultimate-guitar.com/tab/85053",
    "https://tabs.ultimate-guitar.com/tab/a/b/c-chords-1", "https://tabs.ultimate-guitar.com/tab/a-1",
    "https://tabs.ultimate-guitar.com/tab/a/-1", "https://tabs.ultimate-guitar.com/tab/a/b-ukulele-chords-5",
    "https://tabs.ultimate-guitar.com/tab/a/b-ukulele-5", "https://tabs.ultimate-guitar.com/tab/a/b-guitar-pro-5",
    "https://tabs.ultimate-guitar.com/tab/a/guitar-pro-5", "https://tabs.ultimate-guitar.com/tab/a/b-bass-tabs-5",
    "https://tabs.ultimate-guitar.com/tab/%C3%A9/b-chords-5", "https://tabs.ultimate-guitar.com/tab/a/b-chords-5?x=1",
    "https://tabs.ultimate-guitar.com/tab/6571181", "http://tabs.ultimate-guitar.com/tab/6571181/",
    "httpſ://tabs.ultimate-guitar.com/tab/1", "Kite.ultimate-guitar.com/tab/1",
    "https://www.ultimate-guitar.com/artist/٣", "https://www.ultimate-guitar.com/artist/a_b_12?x#y",
    "https://www.ultimate-guitar.com/artist/_12", "https://www.ultimate-guitar.com/artist/a/12",
    "https://WWW.ULTIMATE-GUITAR.COM/artist/12",
    "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-1.shtml",
    "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-10.shtml",
    "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml/",
    "https://acordes.lacuerda.net/soda_stereo/de_musica_ligera-2",
    "https://www.lacuerda.net/a_1/b_2", "https://LACUERDA.NET/a/b", "https://x.lacuerda.net/a/b",
    "https://www.harptabs.com/tab/123456789/a", "https://www.harptabs.com/tab/1234567890/a",
    "https://www.harptabs.com/tab/25/piano-man//", "https://WWW.HARPTABS.COM/tab/25/piano-man",
    "https://gametabs.net/tabs/a_b/c-d_e", "https://gametabs.net/tabs/a/b/",
    "https://www.azlyrics.com/lyrics/a/b.html/", "https://www.azlyrics.com/lyrics/a-1/b-2.html?x=1#y",
    "https://m.youtube.com/watch?v=XFkzRNyygfk", "https://music.youtube.com/watch?v=XFkzRNyygfk&v=ABCDEFGHIJK",
    "https://www.youtube.com/watch?v=XFkz%52yygfk", "https://www.youtube.com/watch?v=", "youtube.com/watch?v=XFkzRNyygfk",
    "https://www.youtube.com/shorts/XFkzRNyygfk/", "https://www.youtube.com/embed/XFkzRNyygfk",
    "https://www.youtube.com/live/XFkzRNyygfk", "https://www.youtube.com/v/XFkzRNyygfk",
    "https://youtu.be/XFkzRNyygfk/", "https://youtu.be/XFkzRNyygf", "https://YOUTU.BE/XFkzRNyygfk",
    "https://youtu.be//XFkzRNyygfk//", "ftp://youtu.be/XFkzRNyygfk",
    "Soda Stereo - De Música Ligera", "宋冬野 - 斑马，斑马", "A - B - C", " - B", "A - ", "A-B", "A  -  B",
    "\U0001d11e Band - \U0001d11e Song", "Radiohead - Creep", "Radiohead - Creep　",
]

URL_FNS = (
    "caracole.overrides.override_key", "caracole.overrides.tab_id_from_url", "caracole.overrides.pin_url",
    "caracole.overrides.artist_page_address", "caracole.overrides._artist_url_value",
    "caracole.overrides.pasted_tab_id", "caracole.overrides.lacuerda_pick_from_url",
    "caracole.overrides.harptabs_pick_from_url", "caracole.overrides.gametabs_pick_from_url",
    "caracole.overrides.azlyrics_page_from_url", "caracole.youtube_urls.video_id_from_url",
    "caracole.ug.sitemap.classify_tab_url",
)


def harvested() -> list[str]:
    """The texts of the tests that read addresses and songs' names: each string constant of one line that looks like
    an address or names a song ("Artist - Title"), ``TAB + "…"`` and ``WWW + "…"`` joined; in a sorted order."""
    found: set[str] = set()
    for name in HARVESTED:
        tree = ast.parse((TESTS / name).read_text(encoding="utf-8"))
        constants = {node.targets[0].id: node.value.value for node in tree.body
                     if isinstance(node, ast.Assign) and len(node.targets) == 1
                     and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)
                     and isinstance(node.value.value, str)}
        for node in ast.walk(tree):
            text = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and isinstance(node.left, ast.Name)
                  and node.left.id in constants and isinstance(node.right, ast.Constant)
                  and isinstance(node.right.value, str)):
                text = constants[node.left.id] + node.right.value
            if text is None or "\n" in text or len(text) > 200:
                continue
            if _LOOKS.search(text) or (" - " in text and len(text) < 80 and "=" not in text):
                found.add(text)
            if name == "test_sitemap.py" and re.fullmatch(r"[^\s/:]*/[^\s:]+", text):
                found.add(constants["TAB"] + text)
    return sorted(found)


def _pick(pick: Any) -> dict[str, Any]:
    out = dataclasses.asdict(pick) | {"url": pick.url}
    if hasattr(pick, "path"):
        out["path"] = pick.path
    return out


def _url_answer(fn: str, text: str) -> Any:
    import caracole.overrides as ov
    from caracole.ug.sitemap import classify_tab_url
    from caracole.youtube_urls import video_id_from_url

    name = fn.rsplit(".", 1)[1]
    if name == "video_id_from_url":
        return video_id_from_url(text)
    if name == "classify_tab_url":
        row = classify_tab_url(text)
        return row if isinstance(row, str) else row._asdict()
    answer = getattr(ov, name)(text)
    return _pick(answer) if dataclasses.is_dataclass(answer) else answer


def url_records() -> list[dict[str, Any]]:
    from caracole.overrides import LaCuerdaPick, OverridesError

    texts = list(dict.fromkeys([*harvested(), *EXTRA_TEXTS]))
    records = []
    for fn in URL_FNS:
        for text in texts:
            record: dict[str, Any] = {"fn": fn, "args": [text]}
            try:
                record["out"] = _url_answer(fn, text)
            except (OverridesError, ValueError) as e:
                record.update(err=type(e).__name__, message=str(e))
            records.append(record)
    picks = [LaCuerdaPick("estopa", "como_camaron"), LaCuerdaPick("estopa", "como_camaron", 2),
             LaCuerdaPick("estopa", "como_camaron", 1)]
    tabs = ["estopa/como_camaron-1", "estopa/como_camaron-2", "estopa/como_camaron", "estopa/como_camaron-",
            "estopa/como-camaron-2", "estopa/como_camaron-2-3", "estopa/como_camaron_x-2", "other/como_camaron-2",
            "estopa/como_camaron-02", "estopa", ""]
    for pick in picks:
        for tab in tabs:
            records.append({"fn": "caracole.overrides.LaCuerdaPick.holds", "args": [dataclasses.asdict(pick), tab],
                            "out": pick.holds(tab)})
    return records


# --- the files ----------------------------------------------------------------------------------------------------


def every_file(tmp: Path) -> dict[Path, str]:
    return {
        READ: jsonl(read_records(tmp), corpus="library/overrides_read", made_by=MADE_BY),
        WRITES: jsonl(write_records(tmp), corpus="library/overrides_writes", made_by=MADE_BY),
        URLS: jsonl(url_records(), corpus="library/override_urls", made_by=MADE_BY),
    }


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return every_file(tmp_path_factory.mktemp("overrides"))


@pytest.mark.parametrize("name", ["overrides_read", "overrides_writes", "override_urls"])
def test_the_vector_is_what_overrides_py_does(made, name):
    path = LIBRARY / f"{name}.jsonl"
    check(path, made[path])


def test_every_writer_and_reader_is_in_the_vectors(made):
    writes = [json.loads(line) for line in made[WRITES].splitlines()[1:]]
    names = {r["fn"].rsplit(".", 1)[1] for r in writes}
    assert names == {"add_match", "add_pin", "remove_pin", "add_lacuerda", "add_harptabs", "add_gametabs",
                     "add_reject", "add_alias", "add_ignore", "add_version", "add_harmonica"}
    for name in names:  # each writer writes, refuses or leaves the rows as they were
        mine = [r for r in writes if r["fn"].endswith(name)]
        assert any("out" in r and r["out"]["rows"] != r["rows"] for r in mine), name
    assert {r.get("err") for r in writes} >= {"OverridesError", "ValueError"}
    assert any(c["error"] for r in writes for c in r["checks"]) and any(
        not c["error"] for r in writes for c in r["checks"])
    reads = [json.loads(line) for line in made[READ].splitlines()[1:]]
    every = next(r for r in reads if r["case"].startswith("every table"))
    assert all(every["out"][f] for f in every["out"]), "every field of the first case holds something"
    urls = [json.loads(line) for line in made[URLS].splitlines()[1:]]
    assert {r["fn"] for r in urls} == {*URL_FNS, "caracole.overrides.LaCuerdaPick.holds"}
    for fn in URL_FNS:
        answers = [r for r in urls if r["fn"] == fn]
        assert any("err" not in r and r["out"] is not None for r in answers), fn


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert every_file(tmp_path) == made


def test_a_file_and_its_rows_read_alike(tmp_path):
    """rows_of and toml_of go both ways: a file's rows made a file again give the same rows."""
    path = tmp_path / "a.toml"
    path.write_text(EVERY_TABLE, encoding="utf-8")
    rows = rows_of(path)
    again = tmp_path / "b.toml"
    again.write_text(toml_of(rows), encoding="utf-8")
    assert rows_of(again) == rows
