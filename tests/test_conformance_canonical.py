"""The canonical corpus, for the phone: tests/conformance/vectors/canonical/, what caracole.canonical and
db.kv_set_json answer, which core.json.Canonical and core.json.PyJson must answer to the byte.

- ``dumps.jsonl``: ``canonical.dumps(value)``, C(v), each record's ``args[0]`` the value (a float as its repr, which
  Kotlin reads as its literal).
- ``digest.jsonl``: ``canonical.digest(value)``, D(v).
- ``stored_hash.jsonl``: ``canonical.stored_hash(text)``, H(text), each record with two keys more: ``reads``, whether
  ``json.loads`` reads the text (Kotlin's ``Canonical.parse`` must, else throw ``CanonicalError``), and
  ``canonical``, C of what it reads, or null where there is none (not JSON, or not canonicalizable: then
  ``Canonical.write`` of what it reads throws). Its texts: the spec's vectors, caracole's own stored records
  (UG's version records as ``versions.raw`` holds them, LRCLIB's answers as ``songs.lyrics_json`` does, and the
  fixtures' own texts), numbers, the reading's edges, whitespace.
- ``stored_hash_utf16.jsonl``: H of texts that hold a raw lone surrogate, which no corpus string may: each record's
  text is its ``utf16`` code units (``args`` empty), with ``reads`` as above.
- ``pydumps.jsonl``: ``json.dumps(value, ensure_ascii=False, **kw)``, db.kv_set_json's text with no ``kw`` beyond
  ``ensure_ascii``: kv-shaped values. A corpus line sorts its keys, and insertion order is what's tested, so each
  record's value is its ``value`` key, the value's JSON text in its insertion order (``json.dumps(value, indent=1)``,
  ASCII), which Kotlin reads with ``Canonical.parse``; ``args`` is empty.
- ``float_text.jsonl``: ``json.dumps(x)`` of a float, its repr (or ``NaN``, ``Infinity``, ``-Infinity``), which
  Kotlin's ``PyJson.floatText`` must write from the Double the record's ``args[0]`` reads as: every power of two (a
  double whose lower neighbour is nearer than its upper), ties between two shortest digit strings, the doubles whose
  ``Double.toString`` digits are no shortest ones (2e+23, 5e-324), and seeded random ones.
"""

import json
import math
import random
import struct
from pathlib import Path

from helpers.corpus import VECTORS, check, jsonl
from test_canonical import ROWS, needs_the_spec, nested

from caracole import canonical
from caracole.lyrics import Lyrics
from caracole.ug.page import parse_tab_page

MADE_BY = "tests/test_conformance_canonical.py"
FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-11-03T12:00:00Z"
DIGESTS = ["0" * 64, "d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772", None]


def write(name: str, records) -> None:
    check(VECTORS / "canonical" / f"{name}.jsonl", jsonl(records, corpus=f"canonical/{name}", made_by=MADE_BY))


# --- values ---------------------------------------------------------------------------------------------------

CONTROLS = "".join(chr(i) for i in range(0x20))
SONG = {
    "names": {"artist": "宋冬野", "artists": ["宋冬野"], "title": "斑马, 斑马", "album": None, "duration_ms": 253100,
              "variant": None},
    "status": "found", "review": False, "match": ["auto", "song dongye", "ban ma ban ma"],
    "lyrics": ["found", "9217d0ebcdddf167491b9693b8e59f4db62531e6fa658eca50bbd5a10a26c1a5"],
    "versions": [{"provider": "ug", "tab": "101", "slot": "sheet", "kind": "chords", "label": None, "pick": 1,
                  "gone": False, "url": "https://tabs.ultimate-guitar.com/tab/101", "raw": None},
                 {"provider": "ug", "tab": "99", "slot": "versions", "kind": "chords", "label": "acoustic",
                  "pick": None, "gone": True, "url": None, "raw": DIGESTS[1]}],
    "files": {"sheet.txt": DIGESTS[0], "guitar-1.gp5": DIGESTS[1]},
    "overrides": {"version": "key=Gm&mode=dorian&capo=0", "pin": 101, "ignore": False},
}

VALUES = [
    None, True, False, 0, -1, 7, "", "a", [], {}, [[]], {"": ""},
    CONTROLS, {c: i for i, c in enumerate(CONTROLS)}, [c for c in CONTROLS],
    "\x7f", "\u2028\u2029", "/", '"\\', "é", "宋冬野 - 斑马斑马", "Ｆｕｌｌ ｗｉｄｔｈ", "\ufeff", "\ufffd", "\U0001F3B8",
    "\U0001D11E", "\U0010FFFF", "a\U0001F600b\uff61c",
    {"\uff61": 1, "\U0001F600": 2, "\ue000": 3, "\ufffd": 4, "\U00010000": 5, "z": 6, "é": 7, "宋": 8, "": 9,
     "\U0001F3B8": 10, "\uffff": 11, "\ud7ff": 12},
    {"z": {"b": [1, {"y": 1, "x": 2}], "a": None}},
    {"b": {"d": {"f": [{"h": [], "g": {}}], "e": None}, "c": "x"}, "a": [True, False]},
    nested(30), nested(512),
    2 ** 64, -(2 ** 63) - 1, 10 ** 40, -(10 ** 40), int("7" * 4300), -int("7" * 4300),
    238.0, 4.5, 0.1, -0.0, 1e-07, 2.5e-10, 1e16, 1e22, 1e300, 5e-324, 1.7976931348623157e308, 123456789.125,
    -4.54038, 253.1004, [213.0, {"duration": 184.0, "rating": 4.8925}],
    float("nan"), float("inf"), float("-inf"), [float("nan"), 1, float("-inf")],
    SONG, {"artist": "Eagles", "title": "Hotel California"},
    {"name": "Campfire", "songs": [["Radiohead - Creep", {}], ["A - B", {"key": "G", "capo": 2}],
                                   ["宋冬野 - 斑马斑马", {"key": "Am", "mode": "dorian", "instrument": "ukulele"}]]},
    ["radiohead", "radiohead-official"], {"name": "Song Dongye (宋冬野)", "page": "https://u/artist/song-dongye_1"},
    [["song/a", "mine", DIGESTS[0], None], ["song/b", "conflict", DIGESTS[0], DIGESTS[1]]],
]


def test_dumps_vectors():
    write("dumps", [{"fn": "caracole.canonical.dumps", "args": [v], "kw": {}, "out": canonical.dumps(v)}
                    for v in VALUES])


def test_digest_vectors():
    write("digest", [{"fn": "caracole.canonical.digest", "args": [v], "kw": {}, "out": canonical.digest(v)}
                     for v in VALUES])


# --- stored texts ---------------------------------------------------------------------------------------------

def stored_records() -> list[str]:
    """What caracole stores: UG's version records (versions.raw), LRCLIB's answers (songs.lyrics_json)."""
    texts = []
    for name in ("tab_chords.html", "tab_ukulele.html", "tab_pro.html"):
        page = parse_tab_page((FIXTURES / "ug" / name).read_text("utf-8"))
        for version in (page.tab, *page.versions):
            texts.append(json.dumps(dict(version.raw), ensure_ascii=False))
    for name in ("get_hit.json", "get_instrumental.json"):
        text = (FIXTURES / "lrclib" / name).read_text("utf-8")
        texts += [text, Lyrics.from_record(json.loads(text)).to_json()]
    banma = (FIXTURES / "lrclib" / "search_banma.json").read_text("utf-8")
    texts += [banma] + [Lyrics.from_record(r).to_json() for r in json.loads(banma)]
    return texts


RECORD = '{"id": 85053, "rating": 4.54038, "votes": 7, "song_name": "De M\\u00fasica Ligera", "tags": [], "x": null}'
LONE = ['"\\ud800"', '"\\udfff"', '"\\udfb8\\ud83c"', '"\\ud83c\\u0041"', '"\\ud83cx"', '{"\\ud800": 1}',
        '["ok", {"k": "\\udc00"}]']
ESCAPES = ['"\\ud83c\\udfb8"', '"\\uD83C\\uDFB8"', '"\\u00E9\\u00e9"', '"\\/\\b\\f\\n\\r\\t\\"\\\\"', '"\\u0000"',
           '"\\u001F\\u007F\\u2028"', '"a\\tb"', '{"\\u00e9": 1, "\\u00c9": 2, "e\\u0301": 3}']
NOT_JSON = [
    "", " ", "hello", "'a'", '"abc', '"a\\x"', '"\\u12"', '"\\U0041"', '"\\u12G4"', '"a\tb"', '"a\nb"', '"\x1f"',
    "tru", "nul", "True", "None", "nan", "infinity", "-NaN", "+Infinity", "-", "-a", "1e", "1e+", "1.5e", "1.e5",
    "-01", "00", "0x10", "1_000", "١", "１", "[", "]", "[1,]", '{"a":1,}', "[1 2]", '{"a" 1}', '{"a":1 "b":2}',
    "{1:2}", "{'a':1}", "{a:1}", "[1]]", "{}{}", "1 2", "/* */1", "1 // x", "[\u00a01]", "\u20281", "\x0c1",
    "\x0b1", "\x851",
]
NUMBERS = [
    "0", "-0", "1", "-1", "238", "238.0", "-238.000", "4.50", "1E2", "1e-7", "1E-07", "-0.0", "-0e-3", "0e0",
    "0.0e+0", "1e+300", "5e-324", "1.7976931348623157e+308", "2.5e-10", "100e-2", "12.340e1", "-12.340e1",
    "1.5E-3", "0.000", "10.0001000", "1e30", "0.12345678901234567890123456789012345",
    "3.14159265358979323846264338327950288419716939937510", "-98765432109876543210.123456789012345678901",
    "1e1000", "1e-1000", "1E+1000", "0.001e+0001000", "123.456e-1000", "1e1001", "1e-1001", "1000e-1001",
    "1e+00001001", "1e999999999", "-1e999999999", "1e" + "9" * 50, "7" * 4300, "-" + "7" * 4300, "7" * 4301,
    "-" + "7" * 4301, "1" * 5000, "7" * 5000 + ".50", "0." + "0" * 5000 + "1", "[1, 2.0, -3e1, 4E-1]",
    "NaN", "Infinity", "-Infinity", "[NaN, Infinity, -Infinity, 0]", '{"t": [238.0, 1e-7]}',
]
SHAPES = [
    "true", "false", "null", "[]", "{}", "[[]]", '{"":{}}', '""', '{"a":1,"a":2}', '{"a":{"x":1},"b":0,"a":[3]}',
    '{"b":1,"a":2,"b":3}', '[{"k":1,"k":null}]', nested(512), nested(513), '{"a":' * 512 + "1" + "}" * 512,
    '{"a":' * 513 + "1" + "}" * 513, "[" * 512 + "{}" + "]" * 512,
]


def whitespace_variants() -> list[str]:
    record = json.loads(RECORD)
    texts = [RECORD, json.dumps(record, separators=(",", ":")), json.dumps(record, indent=1),
             json.dumps(record, indent="\t"), json.dumps(record, indent=2).replace("\n", "\r\n"),
             " \t\r\n" + RECORD + "\n\n", json.dumps(record, ensure_ascii=False), json.dumps(dict(reversed(
                 list(record.items()))))]
    texts += [RECORD + space for space in ("\u00a0", "\x0b", "\x0c", "\u2028", "\u3000", "\ufeff", "\x85")]
    texts += ["\ufeff" + RECORD, "\ufeff{}"]
    return texts


def stored_texts() -> list[str | None]:
    texts = [r[1] for r in ROWS] + ["1e1000"]
    texts += stored_records() + whitespace_variants() + NUMBERS + SHAPES + LONE + ESCAPES + NOT_JSON + [None]
    seen, out = set(), []
    for text in texts:
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def stored(text: str | None) -> dict:
    try:
        value = canonical.read(text) if text is not None else None
        reads = text is not None
    except ValueError:
        value, reads = None, False
    try:
        c = canonical.dumps(value) if reads else None
    except canonical.NotCanonical:
        c = None
    return {"reads": reads, "canonical": c, "out": canonical.stored_hash(text)}


@needs_the_spec  # its texts begin with the spec's rows
def test_stored_hash_vectors():
    write("stored_hash", [{"fn": "caracole.canonical.stored_hash", "args": [text], "kw": {}, **stored(text)}
                          for text in stored_texts()])


def utf16(text: str) -> list[int]:
    units = []
    for c in text:
        n = ord(c)
        units += [0xD800 + ((n - 0x10000) >> 10), 0xDC00 + ((n - 0x10000) & 0x3FF)] if n > 0xFFFF else [n]
    return units


# Raw lone surrogates: a high one escaped and a low one raw beside it (or the other way round) read as two lone
# surrogates in Python, never as the pair their UTF-16 units look like in Kotlin.
RAW_SURROGATES = ['"a\ud800b"', '"\udfff"', "\ud800", "x\udc00", '{"k": "\udfff"}', '{"\ud83c": 1}',
                  '"\ud83c\\udfb8"', '"\\ud83c\udfb8"', '"\\ud83c\udfb8\\ud83c\\udfb8"', '"\udfb8\ud83c"',
                  '"\U0001F3B8"', '["\ud800", 1e1001]', '"\ud800']


def test_stored_hash_utf16_vectors():
    records = [{"fn": "caracole.canonical.stored_hash", "args": [], "kw": {}, "utf16": utf16(text), **stored(text)}
               for text in RAW_SURROGATES]
    assert [r["canonical"] for r in records if r["canonical"] is not None] == ['"\U0001F3B8"']
    write("stored_hash_utf16", records)


# --- kv text --------------------------------------------------------------------------------------------------

BASE = {"song/宋冬野|斑马斑马": (DIGESTS[0], NOW), "song/radiohead|creep": (DIGESTS[1], NOW),
        "song/\U0001F3B8|x": (None, NOW), "song/\uff61|y": (DIGESTS[0], "2026-10-31T00:00:00Z"),
        "removed/eagles|hotel california": (DIGESTS[1], NOW), "block/4242": (None, NOW)}
KV_VALUES = [
    {"strikes": 2, "cooldown_until": "2026-11-05T02:00:00Z", "last_ok": None, "last_error": "403 from ug",
     "last_error_at": NOW},
    {"run_id": NOW, "started": NOW, "finished": "2026-11-03T12:31:07Z", "steps": {"sync": "ok", "lyrics": "ok"},
     "blocked": [], "errors": ["gtptabs: timeout"], "requests": {"ug": 12, "lrclib": 140},
     "budgets": {"ug": 60}, "seconds": 1867.25},
    {"tabs.xml.gz": {"etag": '"5f-abc"', "rows": 51234, "read_at": NOW}, "artists.xml": {"etag": None, "rows": 0}},
    ["101", "202", "99"], {"sheet.html": {"sha256": DIGESTS[0], "size": 1}, "sheet (Traditional).pdf": {"size": 9}},
    {k: list(v) for k, v in sorted(BASE.items())},
    {"format": 2, "units": {k: list(v) for k, v in sorted(BASE.items())}},
    {"at": NOW, "query": "Soda Stereo – De Música Ligera", "video": {"id": "dQw4w9WgXcQ", "title": "“Live” 🎸",
                                                                      "duration": 213.0, "thumb": True}},
    {"until": NOW, "strikes": 1, "error": "no data.tab_view\n<html>"},
    {"zeta": 1, "alpha": {"y": [], "b": {}, "a": [{"z": None, "a": False}]}, "mu": "宋"},
    {"pages": 4, "tabs": 120}, 3, "text", None, [], {}, [{}], {"": []},
    {"floats": [0.1, 4.5, 213.0, -0.0, 1e-07, 1e16, 1.7976931348623157e308, 5e-324, 2.5e-10]},
    {"ints": [0, -1, 2 ** 70, -(10 ** 30)]}, [float("nan"), float("inf"), float("-inf")],
    {"escapes": CONTROLS + '\x7f"\\/\u2028\u2029\U0001F600'}, {CONTROLS: 1, "\U0001F600": 2, "\uff61": 3},
]
KWS = [{"ensure_ascii": False}, {"ensure_ascii": False, "sort_keys": True},
       {"ensure_ascii": False, "separators": (",", ":")},
       {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")}]


def test_pydumps_vectors():
    records = [{"fn": "json.dumps", "args": [], "kw": kw, "value": json.dumps(v, indent=1),
                "out": json.dumps(v, **kw)} for kw in KWS for v in KV_VALUES]
    write("pydumps", records)


def test_kv_set_json_writes_json_dumps_text(conn):
    from caracole.db import kv_get, kv_set_json

    for i, value in enumerate(KV_VALUES):
        kv_set_json(conn, f"t:{i}", value)
        assert kv_get(conn, f"t:{i}") == json.dumps(value, ensure_ascii=False)


def test_a_value_reads_back_from_its_text_in_its_insertion_order():
    for value in KV_VALUES:
        text = json.dumps(value, indent=1)
        assert json.dumps(json.loads(text), ensure_ascii=False) == json.dumps(value, ensure_ascii=False)


# --- a float's text -------------------------------------------------------------------------------------------

def bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def floats() -> list[float]:
    rng = random.Random(20261103)
    xs = [0.0, -0.0, float("nan"), float("inf"), float("-inf"), 5e-324, -5e-324, 1e-323, 2.2250738585072014e-308,
          math.nextafter(2.2250738585072014e-308, 0), 1.7976931348623157e308, -1.7976931348623157e308, 1.0, -1.0, 0.1,
          0.2, 0.1 + 0.2, 0.3, 1 / 3, 2 / 3, 4.35, 238.0, 4.5, 213.0, 184.0, 4.8925, 4.54038, 253.1004, 1867.25,
          123456789.125, 12345678.9, 2.5e-10, 1e-07, 1e-05, 9.999999999999999e-05, 0.0001, 0.00012345, 1e7, 1e15,
          1e16, 1.5e16, 9999999999999998.0, 1e22, 1e23, 2e23, 8.41e21, 2.82879384806159e17, 1e300, 1e-300,
          float(2 ** 53), float(2 ** 53 + 2), float(2 ** 63), float(2 ** 64), 2.0 ** 1023]
    xs += [2.0 ** k for k in range(-1074, 1024)]
    xs += [math.nextafter(2.0 ** k, direction) for k in rng.sample(range(-1073, 1023), 150) for direction in (0, math.inf)]
    # 2^50 to 2^51 steps by a quarter: k.25 and k.75 lie halfway between two 17-digit strings that both read as them.
    xs += [float(2 ** 50 + k) + quarter for k in rng.sample(range(2 ** 50), 30) for quarter in (0.25, 0.75)]
    xs += [struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0] for _ in range(1000)]
    xs += [round(rng.uniform(-1e4, 1e4), rng.randrange(0, 7)) for _ in range(300)]
    xs += [float(f"{rng.randrange(1, 10 ** rng.randrange(1, 18))}e{rng.randrange(-40, 40)}") for _ in range(300)]
    seen, out = set(), []
    for x in xs:
        if bits(x) not in seen:
            seen.add(bits(x))
            out.append(x)
    return out


def test_float_text_vectors():
    records = [{"fn": "json.dumps", "args": [x], "kw": {}, "out": json.dumps(x)} for x in floats()]
    assert all(r["out"] == repr(r["args"][0]) for r in records if math.isfinite(r["args"][0]))
    write("float_text", records)
