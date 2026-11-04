"""Python's JSON, HTML entities, numbers, capitalize and URLs, for the phone's site parsers: what core.py answers in
their place (core/py/PyHtml, PyNumbers, PyUrl, PyUnicode.capitalize; core/json/PyJson's loads and dumps with an
indent), record for record (docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, lane py-sites).

caracole's site modules read every page with Python's own functions: ``html.unescape`` (azlyrics.py, ug/page.py),
``json.loads`` (UG's js-store, LRCLIB's and Megalobiz's answers, harptabs.com's and gametabs.net's JSON), ``float()``
and ``int()`` (harptabs.py, ug/page.py's numbers), ``str.capitalize`` (lacuerda_index.py, progressions.py) and
``urllib.parse``'s ``urljoin``, ``urlencode`` and ``urlunsplit`` (ug/fetch.py, ug/artist.py, icons.py, the routes),
and write what they keep with ``json.dumps(..., ensure_ascii=False, indent=2)`` (ug/fetch.py, lacuerda_fetch.py,
library.py). The phone answers as they do, to the byte.

Runtime data, tests/conformance/data/caracole/unicode/ (caracole/unicode/ on the phone's classpath):

- ``title.txt``: ``cp title`` lines, the full title case ``str.capitalize`` gives a code point first in a string,
  ``+``-joined, ``=`` where it is the code point itself; only where it is not ``str.upper``'s (case.txt's): the
  digraphs (ǆ to ǅ), the ligatures and ß (``Ss``), the Greek letters with ypogegrammeni and the Georgian letters,
  whose title case is themselves. The first line names its unicodedata version, as every table there does.

Vectors, tests/conformance/vectors/py/ (lane py-format adds its own ``format*.jsonl`` beside them):

- ``sites_unescape.jsonl``: ``html.unescape`` over batches of strings (``args[0]``, ``out`` the answers in order):
  every name of ``html.entities.html5`` with its ``;`` and without, followed by a letter, as a prefix of a longer
  name (the longest-prefix rule), curated edge cases and seeded random strings; then
  ``html.unescape.numeric`` records, ``args`` a reference's format and the first and last number it is given, ``out``
  the runs ``[first, last, text]`` where its answer is not ``chr(n)`` (the windows-1252 table, the invalid code
  points, the surrogates and beyond U+10FFFF): every other number in range answers ``chr(n)``. A record whose
  ``err`` is set raised (``ValueError``: more digits than ``int()`` reads).
- ``sites_json.jsonl``: ``json.loads`` of a text (``args[0]``) or of a fixture's bytes (``json.loads(bytes)``, the
  way http.py's ``Response.json`` reads an answer), ``out`` what ``json.dumps`` writes of the value: ``dumps``
  (its defaults but ``ensure_ascii=False``), ``indent`` (``ensure_ascii=False, indent=2``) and ``ascii``
  (``ensure_ascii=True, indent=1, sort_keys=True``); a text holding a lone surrogate is given as ``<key>_utf16``, its
  UTF-16 code units, since a corpus line holds none, and one longer than ``LONG`` as ``<key>_sha256``, the SHA-256
  of its UTF-8 (``surrogatepass``). ``err``, ``"<type>: <message>"``, for a text Python refuses: the message is
  ``JSONDecodeError``'s, positions in code points (a UTF-16 or UTF-32 decoding error by its type alone). The
  fixtures' JSON (UG's js-store, harptabs.com's ld+json, gametabs.net's attributes, LRCLIB's and Megalobiz's
  answers) gives ``indent`` and ``ascii`` (as its digest) alone. ``json.loads.numbers`` records batch number
  literals, ``out`` each one's ``json.dumps``. ``json.loads(bytes)``'s ``args[0]`` is a fixture reference or
  ``{"hex": …}``.
- ``sites_numbers.jsonl``: ``float`` and ``int`` over batches of strings, ``out`` each answer: a float as the 16
  lowercase hex digits of its IEEE bits, an int as its decimal, ``null`` where Python raises ValueError.
- ``sites_capitalize.jsonl``: ``str.capitalize`` of every code point alone (``out`` the ``[cp, text]`` of those it
  changes: every other one is itself), of every code point after an ``a`` (``out`` what follows the ``A``, where it
  isn't the code point), and of batches of strings.
- ``sites_url.jsonl``: ``urllib.parse.urljoin`` (``args`` a base and a batch of references), ``urlunsplit``
  (``args`` a batch of five-part tuples) and ``urlencode`` (``args`` a batch of pair lists, ``kw.doseq``; with
  ``doseq`` a value may be a list). An answer is a string, or ``{"err": "ValueError: <message>"}``.
"""

from __future__ import annotations

import decimal
import functools
import hashlib
import html
import html.entities
import itertools
import json
import math
import random
import struct
import sys
import unicodedata
import urllib.parse

import pytest

from helpers.corpus import DATA, FIXTURES, VECTORS, check, fixture_ref, jsonl

MADE_BY = "tests/test_conformance_py.py"
OUT = VECTORS / "py"
MAX = 0x110000
SEED = 20261104
BATCH = 400


def _batches(items: list, size: int = BATCH) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _unique(items) -> list:
    return list(dict.fromkeys(items))


def _surrogates(s: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def _units(s: str) -> list[int]:
    """``s``'s UTF-16 code units: an astral code point two, a lone surrogate one."""
    out = []
    for c in s:
        cp = ord(c)
        if cp >= 0x10000:
            cp -= 0x10000
            out += [0xD800 | (cp >> 10), 0xDC00 | (cp & 0x3FF)]
        else:
            out.append(cp)
    return out


def _err(e: BaseException) -> str:
    return f"{type(e).__name__}: {e}"


# --- title.txt -----------------------------------------------------------------------------------------------


def _seq(s: str) -> str:
    return "+".join(f"{ord(c):04X}" for c in s)


@functools.cache
def _titles() -> list[tuple[int, str]]:
    """Each code point whose full title case (``capitalize`` of it alone) is not its full upper case."""
    out = []
    for cp in itertools.chain(range(0xD800), range(0xE000, MAX)):
        c = chr(cp)
        title = c.capitalize()
        if title != c.upper():
            out.append((cp, title))
    return out


def title_txt() -> str:
    head = (f"# caracole/unicode/title.txt: cp title, '+' joins, '=' itself, where str.upper differs; unicodedata "
            f"{unicodedata.unidata_version}, Python {sys.version.split()[0]}, made by {MADE_BY}\n")
    return head + "".join(f"{cp:04X} {'=' if t == chr(cp) else _seq(t)}\n" for cp, t in _titles())


def test_title_txt_is_pythons():
    check(DATA / "unicode" / "title.txt", title_txt())


def test_capitalize_is_the_title_of_the_first_then_the_rest_lowered_in_context():
    """What PyUnicode.capitalize computes: title.txt's (else upper's) first, then what lower() makes of the rest, Σ
    read in the whole string's context (its Final_Sigma rule)."""
    titles = dict(_titles())
    for s in CAPITALIZE_CURATED + _random_strings(500, POOLS):
        if not s:
            continue
        first = titles.get(ord(s[0]), s[0].upper())
        assert s.capitalize() == first + s.lower()[len(s[0].lower()):], repr(s)


def test_decimal_digits_come_in_runs_of_ten_from_zero():
    """PyNumbers reads a Unicode decimal digit's value from its place in its run of isdecimal() code points, as
    Unicode guarantees and Python's own answers show."""
    start = None
    for cp in itertools.chain(range(0xD800), range(0xE000, MAX)):
        if chr(cp).isdecimal():
            if start is None or not chr(cp - 1).isdecimal():
                start = cp
            assert unicodedata.decimal(chr(cp)) == (cp - start) % 10, hex(cp)


# --- html.unescape ------------------------------------------------------------------------------------------


UNESCAPE_CURATED = [
    "", "plain", "&", "&&", "&&amp;", "&amp", "&amp;", "&AMP;", "&AMP", "&ampx", "&ampamp;", "&amp;amp;",
    "&#", "&#;", "&#x", "&#x;", "&#X;", "&#xg;", "&#65", "&#65;", "&#065;", "&#x41", "&#x41;", "&#X41;", "&#x041;",
    "&#xA9;", "&#xa9;", "&#169", "&#0;", "&#00;", "&#x0;", "&#1;", "&#8;", "&#9;", "&#10;", "&#11;", "&#12;",
    "&#13;", "&#14;", "&#31;", "&#32;", "&#127;", "&#128;", "&#x80;", "&#129;", "&#141;", "&#143;", "&#144;",
    "&#157;", "&#159;", "&#160;", "&#xD7FF;", "&#xD800;", "&#xDBFF;", "&#xDC00;", "&#xDFFF;", "&#xE000;",
    "&#xFDCF;", "&#xFDD0;", "&#xFDEF;", "&#xFDF0;", "&#xFFFD;", "&#xFFFE;", "&#xFFFF;", "&#x10000;", "&#x1FFFE;",
    "&#x1FFFF;", "&#x10FFFD;", "&#x10FFFE;", "&#x10FFFF;", "&#x110000;", "&#1114111;", "&#1114112;",
    "&#99999999999999999999;", "&#xFFFFFFFFFFFFFFFFFFFF;", "&#x" + "0" * 40 + "41;", "&#" + "0" * 40 + "65;",
    "&#" + "1" * 4300 + ";", "&#" + "1" * 4301 + ";", "&#" + "0" * 4301 + "65;", "&#x" + "f" * 5000 + ";", "&#65x", "&#65 x", "&#x41g", "&#x41;;", "&#65;65",
    "&notit;", "&notin;", "&notin", "&noti", "&not", "&nothing", "&not;", "&no", "&n", "&;", "& amp;", "&\tamp;",
    "&\namp;", "&\x0camp;", "&<amp;", "&#amp;", "&amp<", "&lt&gt", "&lt;&gt;", "&lt\n", "&lt\t", "&lt ", "&lt<",
    "&Eacute", "&Eacuteacute", "&eacute;", "&Eacute;", "&EACUTE;", "&copy", "&copy;", "&copyright", "&COPY",
    "&COPY;", "&nbsp", "&nbsp;", "&nbsp;nbsp", "&NotEqualTilde;", "&NotEqualTilde", "&nsubE;", "&b.alpha;",
    "&CounterClockwiseContourIntegral;", "&CounterClockwiseContourIntegral",
    "&CounterClockwiseContourIntegralX;", "&" + "a" * 31 + ";", "&" + "a" * 32 + ";", "&" + "a" * 33 + ";",
    "&" + "a" * 40, "&amp" + "a" * 40 + ";", "&é;", "&é", "&amp;é", "&ampé", "&😀;", "&😀amp;", "&amp😀",
    "&" + "😀" * 31 + ";", "&" + "😀" * 32 + ";", "&" + "😀" * 33 + ";", "&" + "é" * 32 + "x", "&lt😀",
    "x &amp; y", "a&b&c", "&&&&", "&#38;amp;", "&amp;#38;", "Tom &amp; Jerry&#39;s &quot;cat&quot;",
    "&apos;", "&apos", "&quot", "&QUOT", "&gt", "&GT;", "&LT", "&reg", "&REG", "&uuml", "&yuml;", "&szlig",
    "&frac12;", "&frac12", "&frac1", "&sup2", "&sup2;", "&acE;", "&ThickSpace;", "&fjlig;", "&bne;", "&bne",
    "&lt;script&gt;", "&lt;br/&gt;", "\x00&amp;\x00", "&\x00amp;", "&amp;\ud7ff", "&a\u3000mp;",
]

UNESCAPE_POOL = ["&", "&", "&", "#", "#", ";", ";", "x", "X", "0", "1", "9", "65", "a", "f", "F", "amp", "lt",
                 "not", "in", "it", "copy", "nbsp", "Eacute", "eacute", "acute", " ", "\t", "\n", "\x0c", "<", "é",
                 "😀", "\u3000", "z", "zz", "AMP", "12", "x41", "128", "#x"]


def _unescape_inputs() -> list[str]:
    names = list(html.entities.html5)
    out = []
    for name in names:
        bare = name.rstrip(";")
        out += ["&" + name + "x", "&" + bare + "Zq", "&" + bare + ";"]
        if len(bare) > 3:
            out.append("&" + bare[:-1] + "Q")
    rng = random.Random(SEED)
    for _ in range(1000):
        out.append("".join(rng.choice(UNESCAPE_POOL) for _ in range(rng.randrange(1, 12))))
    return _unique(UNESCAPE_CURATED + out)


def _numeric_runs(form: str, first: int, last: int) -> list[list]:
    """The runs of numbers from ``first`` to ``last`` whose reference ``form % n`` unescapes to one text that isn't
    ``chr(n)``."""
    runs: list[list] = []
    unescape = html.unescape
    for n in range(first, last + 1):
        got = unescape(form % n)
        if n < MAX and got == chr(n):
            continue
        if runs and runs[-1][1] == n - 1 and runs[-1][2] == got:
            runs[-1][1] = n
        else:
            runs.append([n, n, got])
    return runs


NUMERIC_FORMS = [("&#x%X;", 0, MAX + 16), ("&#%d", 0, MAX + 16), ("&#X%x", 0, 0x2000), ("&#%07d;", 0, 0x2000)]


def unescape_records() -> list[dict]:
    records = []
    for batch in _batches(_unescape_inputs()):
        ok, raised = [], []
        for s in batch:
            try:
                html.unescape(s)
                ok.append(s)
            except ValueError:
                raised.append(s)
        records.append({"fn": "html.unescape", "args": [ok], "out": [html.unescape(s) for s in ok]})
        for s in raised:
            try:
                html.unescape(s)
            except ValueError as e:
                records.append({"fn": "html.unescape", "args": [[s]], "err": _err(e)})
    for form, first, last in NUMERIC_FORMS:
        records.append({"fn": "html.unescape.numeric", "args": [form, first, last],
                        "out": _numeric_runs(form, first, last)})
    return records


@pytest.mark.slow  # about 1.5 s: every numeric reference to U+10FFFF and past it, in two forms
def test_sites_unescape_jsonl():
    check(OUT / "sites_unescape.jsonl", jsonl(unescape_records(), corpus="py/sites_unescape", made_by=MADE_BY))


def test_the_unescape_curated_cases_cover_each_rule():
    assert html.unescape("&notit;") == "¬it;"  # the longest prefix of a name without its ';'
    assert html.unescape("&#128;") == "€" and html.unescape("&#xD800;") == "\ufffd" and html.unescape("&#1;") == ""
    with pytest.raises(ValueError):
        html.unescape("&#" + "1" * 4301 + ";")  # int()'s limit: html.unescape raises


# --- json.loads and json.dumps ------------------------------------------------------------------------------


LONG = 1500  # an answer longer than this is kept as its digest


def _dumps_out(v, *, whole: bool = True) -> dict:
    texts = {"indent": json.dumps(v, ensure_ascii=False, indent=2)}
    if whole:
        texts["dumps"] = json.dumps(v, ensure_ascii=False)
    texts["ascii"] = json.dumps(v, ensure_ascii=True, indent=1, sort_keys=True)
    out = {}
    for key, text in texts.items():
        if len(text) > LONG or (key == "ascii" and not whole):
            out[key + "_sha256"] = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
        elif _surrogates(text):
            out[key + "_utf16"] = _units(text)
        else:
            out[key] = text
    return out


def _loads_record(text: str, note: str | None = None) -> dict:
    record: dict = {"fn": "json.loads", "args": [text]}
    try:
        record["out"] = _dumps_out(json.loads(text))
    except (ValueError, RecursionError) as e:
        record["err"] = _err(e)
    if note:
        record["note"] = note
    return record


def _fixture_json() -> list[tuple[str, str]]:
    """The JSON texts caracole's site parsers read from the fixtures' pages, as each reads it: (where, text)."""
    from selectolax.lexbor import LexborHTMLParser

    found = []
    for path in sorted(FIXTURES.rglob("*.html")):
        rel = path.relative_to(FIXTURES).as_posix()
        tree = LexborHTMLParser(path.read_bytes().decode("utf-8", errors="replace"))
        for node in tree.css("div.js-store"):
            found.append((f"{rel} div.js-store data-content", node.attributes.get("data-content") or ""))
        for node in tree.css('script[type="application/ld+json"]'):
            found.append((f"{rel} ld+json", node.text(deep=True) or ""))
        for attr in ("data-tab", "data-prepopulated-instruments"):
            for node in tree.css(f"[{attr}]"):
                found.append((f"{rel} {attr}", node.attributes.get(attr) or ""))
    return found


LOADS_CURATED = [
    "", " ", "\t\n\r ", "[", "]", "{", "}", "[1,]", "[1,\n]", "[1 , ]", '{"a":1,}', '{"a":1 , }', '{"a" 1}',
    "{1:2}", '{"a":}', '{"a":1', '{"a"', '{"', "{,}", "[,]", "[1,,2]", '{"a":1,,}', "[1 2]", '{"a":1 "b":2}',
    "1 2", "01", "-01", "00", "-", "-a", "- 1", "1.", "1.e5", "1e", "1e+", "1E-", ".5", "+1", "1_0", "0x10",
    "tru", "nul", "fals", "True", "TRUE", "tRue", "null", "true", "false", " null ", "[null,true,false]",
    "NaN", "-NaN", "nan", "Infinity", "-Infinity", "+Infinity", "infinity", "Infinit", "-Inf", "[NaN, Infinity]",
    '"abc', '"abc\\', '"\\', '"\\u', '"\\u1', '"\\u12', '"\\u123', '"\\u1234', '"\\u1234"', '"\\u12G4"',
    '"\\uDEFG"', '"a\x01b"', '"a\nb"', '"a\tb"', '"\x1f"', '"\x7f"', '"\x00"', '"a\\qb"', '"\\x41"', '"\\U0041"',
    '"\\/"', '"\\b\\f\\n\\r\\t\\"\\\\"', '"\\u0000"', '"\\u001f"', '"\\u007f"', '"\\u00e9"', '"\\u00E9"',
    '"\\ud83d\\ude00"', '"\\uD83D\\uDE00"', '"\\ud800"', '"\\udc00"', '"\\udfff"', '"\\ud800\\ud800"',
    '"\\udc00\\ud800"', '"\\ud800\\u0041"', '"\\ud800x"', '"\\ud800\\"', '"\\ud800\\x"', '"\\ud800\\u"',
    '"\\ud800\\udc0"', '"\\ud800\\udc0G"', '"\\ud800\\udc00', '"\\ud800\\udc00x"', '"\\ud800\\udbff"',
    '["\\ud800", "\\udfff"]', '{"\\ud800": 1}', '"😀"', '"😀\\u00e9😀"', '["😀", 1, ' + '"x"]', '[😀]',
    '"😀', '{"😀": 1, "a": [1,', "\ufeff1", "\ufeff", " \ufeff1", "\u00a01", "1\u00a0", "\u30001", "1\u2028",
    "[1]x", '"x"y', "{}x", "[] ", " {} ", "[[]]", "[{}]", '{"a":{"b":{"c":[]}}}', "[" * 10, "[" * 10 + "]" * 10,
    "[" * 40 + "]" * 40, '{"a":' * 20 + "1" + "}" * 20, '{"a":1,"a":2,"b":3}', '{"b":1,"a":2,"b":3,"a":4}',
    '{"a":1,"a":{"x":1},"a":[]}', '{"":1,"":2}', '{"k":1}\n', '{\n  "k": [\n    1,\n    2\n  ]\n}',
    "1e400", "-1e400", "1e-400", "-1e-400", "-0", "-0.0", "0.0", "0e0", "-0e-0", "1E2", "1e+2", "1.50", "100",
    "1" * 4300, "1" * 4301, "-" + "1" * 4300, "-" + "1" * 4301, "0." + "1" * 5000, "1e" + "9" * 30,
    "1e-" + "9" * 30, "123456789012345678901234567890", "-123456789012345678901234567890", "9007199254740993",
    "2.2250738585072011e-308", "2.2250738585072014e-308", "4.9e-324", "2.4703282292062327e-324",
    "2.4703282292062328e-324", "1.7976931348623157e308", "1.7976931348623158e308", "1.7976931348623159e308",
    "0.1", "0.30000000000000004", "1e16", "1e15", "123.456e-7", "5e-324", "1e-323",
    '[1, 2.5, "x", null, true, false, {"k": "v"}]', '  [ 1 ,\t2 ,\n3 ]  ', '{"a" : 1 , "b"\t:\n2}',
    '{"a":1}{"b":2}', "[1]\n\n", "\n\n[1,\n2,\n3,\n]", "\r\n{\r\n\"a\":\r\n}", "\n\n  x", "😀😀\n😀 [1, 2,]",
    '"😀\\q"', '😀', '"\U00010000\U0001f600" 1', "[\n\"\U0001f600\", 1 2]",
]

TRUNCATED = [
    '{"a": ["\\u00e9\\ud83d\\ude00", 1.5e3, -0, true, null], "b\\n": {}}',
    '[NaN, -Infinity, Infinity, false, "\\ud800\\udc00", 0.25E-2]',
    '\n {"😀" :\t[1 ,2 ], "\\"\\\\\\/\\b\\f\\n\\r\\t": "x"}',
]

JSON_STRINGS = ["", "a", "é", "😀", "宋冬野", "\x00", "\x1f", "\x7f", "\u2028", '"', "\\", "/", "\b\f\n\r\t",
                "\ud7ff", "\ue000", "\ufffd", "\uffff", "\U0010ffff", "Ünïcödé ✓", "a b", " ", "<&>"]


def _random_value(rng: random.Random, depth: int = 0):
    kind = rng.randrange(10 if depth < 4 else 7)
    if kind == 0:
        return rng.choice([None, True, False])
    if kind == 1:
        return rng.choice([0, -1, 1, 7, -7, 2 ** 53 + 1, -(2 ** 63), 10 ** 30, rng.randrange(-10 ** 6, 10 ** 6)])
    if kind == 2:
        return rng.choice([0.0, -0.0, 0.5, 1e-7, 1e16, 2.5e-10, rng.uniform(-1e6, 1e6), rng.random() * 10 **
                           rng.randrange(-320, 308), math.inf, -math.inf, math.nan])
    if kind in (3, 4, 5, 6):
        return "".join(rng.choice(JSON_STRINGS) for _ in range(rng.randrange(0, 5)))
    if kind in (7, 8):
        return [_random_value(rng, depth + 1) for _ in range(rng.randrange(0, 5))]
    keys = [rng.choice(JSON_STRINGS + ["k", "key", "a", "b", "id"]) for _ in range(rng.randrange(0, 6))]
    return {k: _random_value(rng, depth + 1) for k in keys}


def _random_text(rng: random.Random, value) -> str:
    text = json.dumps(value, ensure_ascii=rng.random() < 0.4, indent=rng.choice([None, None, 0, 1, 2, "\t"]),
                      separators=rng.choice([None, (",", ":"), (" , ", " : ")]), sort_keys=rng.random() < 0.3)
    if rng.random() < 0.3:
        text = rng.choice([" ", "\n", "\t", "\r\n"]) + text + rng.choice(["", " ", "\n"])
    return text


def _mutated(rng: random.Random, text: str) -> str:
    """``text`` with one character deleted, doubled or replaced: mostly no JSON, at positions the errors name."""
    if not text:
        return "x"
    i = rng.randrange(len(text))
    how = rng.randrange(3)
    if how == 0:
        return text[:i] + text[i + 1:]
    if how == 1:
        return text[:i] + text[i] + text[i:]
    return text[:i] + rng.choice('[]{}",:\\ \nx01-.eEtfnNI\x01😀') + text[i + 1:]


FLOAT_LITERALS = [
    "0.1", "0.2", "0.3", "1.1", "2.675", "1e23", "8.41e21", "5e-324", "4.9406564584124654e-324", "1e-324",
    "2.4703282292062327e-324", "2.4703282292062328e-324", "2.2250738585072009e-308", "2.2250738585072014e-308",
    "1.7976931348623157e308", "1.7976931348623158e308", "1.7976931348623159e308", "1e308", "1e309", "1e-308",
    "9007199254740992.0", "9007199254740993.0", "9007199254740993.0000000001", "9007199254740995.0",
    "123456789012345678901234567890.0", "0.000001", "0.0000001", "1e-7", "1e16", "1e15", "1.5", "-1.5", "-0.0",
    "0.0", "0e5", "0e-5", "-0e0", "1E+2", "1e+02", "1e-02", "100e-2", "0.01e2", "3.14159265358979323846264338",
    "2.718281828459045235360287", "1.0000000000000002", "1.0000000000000001", "0.9999999999999999",
    "0.99999999999999994", "0.99999999999999995", "4.35", "94.745", "66.66666666666667",
    "1.00000000000000011102230246251565404236316680908203125", "1.00000000000000011102230246251565404236316680908203126",
    "1.00000000000000011102230246251565404236316680908203124", "7.2057594037927933e16", "1" + "0" * 400 + ".0",
    "0." + "0" * 400 + "1", "0." + "0" * 300 + "1", "1e-1000", "1e1000", "123e-310", "1.23e-320",
]


def _halfway_literals(rng: random.Random, n: int) -> list[str]:
    """Decimal texts at the exact midpoint of two neighbouring doubles, and a hair either side: the cases a
    correctly rounding reader must break to the even one."""
    ctx = decimal.Context(prec=2000)
    out = []
    for _ in range(n):
        x = abs(struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64) & 0x7FEFFFFFFFFFFFFF))[0])
        if x == 0.0 or not math.isfinite(x):
            continue
        up = math.nextafter(x, math.inf)
        mid = ctx.divide(ctx.add(decimal.Decimal(x), decimal.Decimal(up)), 2)
        text = format(mid, "e")
        out.append(text)
        ulp = ctx.subtract(decimal.Decimal(up), decimal.Decimal(x))
        out.append(format(ctx.add(mid, ctx.divide(ulp, 10 ** 12)), ".40e"))
        out.append(format(ctx.subtract(mid, ctx.divide(ulp, 10 ** 12)), ".40e"))
    return out


def _random_floats(rng: random.Random, n: int) -> list[str]:
    out = []
    for _ in range(n):
        kind = rng.randrange(4)
        if kind == 0:
            x = struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0]
            if math.isfinite(x):
                out.append(repr(x))
        elif kind == 1:
            out.append(repr(rng.uniform(-1e3, 1e3)))
        elif kind == 2:
            digits = "".join(rng.choice("0123456789") for _ in range(rng.randrange(1, 30))).lstrip("0") or "0"
            out.append(f"{digits}.{rng.randrange(10 ** rng.randrange(1, 20))}e{rng.randrange(-340, 320)}")
        else:
            out.append(f"{rng.randrange(1, 10 ** 17)}e{rng.randrange(-340, 320)}")
    return out


def json_records() -> list[dict]:
    records = []
    for where, text in _fixture_json():
        record = {"fn": "json.loads", "args": [text], "note": where}
        try:
            record["out"] = _dumps_out(json.loads(text), whole=False)
        except ValueError as e:
            record["err"] = _err(e)
        records.append(record)
    for path in sorted(FIXTURES.rglob("*.json")):
        body = path.read_bytes()
        record: dict = {"fn": "json.loads(bytes)", "args": [fixture_ref(path)]}
        try:
            record["out"] = _dumps_out(json.loads(body), whole=False)
        except ValueError as e:
            record["err"] = _err(e)
        records.append(record)
    records += [_loads_record(text) for text in _unique(LOADS_CURATED)]
    # Every prefix of a few texts: where each error is met as a text is cut short.
    for whole in TRUNCATED:
        records += [_loads_record(whole[:k], "prefix") for k in range(len(whole))]
    rng = random.Random(SEED)
    texts = 0
    while texts < 300:
        text = _random_text(rng, _random_value(rng))
        if len(text) > 400:
            continue
        texts += 1
        records.append(_loads_record(text, "random"))
        for _ in range(2):
            records.append(_loads_record(_mutated(rng, text), "mutated"))
    numbers = _unique(FLOAT_LITERALS + _halfway_literals(rng, 60) + _random_floats(rng, 400)
                      + [str(rng.randrange(-10 ** k, 10 ** k)) for k in range(1, 60)])
    for batch in _batches(numbers):
        records.append({"fn": "json.loads.numbers", "args": [batch],
                        "out": [json.dumps(json.loads(t)) for t in batch]})
    for raw in BYTES_CASES:
        record = {"fn": "json.loads(bytes)", "args": [{"hex": raw.hex()}]}
        try:
            record["out"] = _dumps_out(json.loads(raw))
        except ValueError as e:
            # UTF-16's and UTF-32's decoding errors by their type alone; UTF-8's and the JSON's with their message
            record["err"] = type(e).__name__ if isinstance(e, UnicodeDecodeError) and _wide(raw) else _err(e)
        records.append(record)
    return records


def _wide(raw: bytes) -> bool:
    """Whether json.loads reads ``raw`` as UTF-16 or UTF-32, whose decoding errors are told by type alone."""
    return json.detect_encoding(raw) not in ("utf-8", "utf-8-sig")


BYTES_CASES = [
    b"", b"1", b"[1]", b'"\xc3\xa9"', b"\xef\xbb\xbf[1]", b"\xef\xbb\xbf", b"\xef\xbb", b'"\xff"', b'"\xc3"',
    b'"\xe2\x82"', b'"\xe2\x82x"', b'"\xed\xa0\x80"', b'"\xed\xb0\x80"', b'"\xed\xa0\xbd\xed\xb8\x80"', b'"\xed\xa0"',
    b'"\xf0\x9f\x98\x80"', b'"\xf4\x90\x80\x80"', b'"\xc0\xaf"', b'"\xe0\x80\xaf"', b'"\xf8\x88\x80\x80\x80"',
    b'["a", "\x80"]', b'{"k": "\xc3\xa9\xc3"}', b"\xc3\xa91", b"[1]\xff",
    "[1, \"é\"]".encode("utf-16"), "[1, \"é\"]".encode("utf-16-le"), "[1, \"é\"]".encode("utf-16-be"),
    "[1, \"😀\"]".encode("utf-32"), "[1, \"😀\"]".encode("utf-32-le"), "[1, \"😀\"]".encode("utf-32-be"),
    "1".encode("utf-16-le"), "1".encode("utf-16-be"), b"\x00\x00\x00", b"1\x00",
]


def test_sites_json_jsonl():
    check(OUT / "sites_json.jsonl", jsonl(json_records(), corpus="py/sites_json", made_by=MADE_BY))


def test_the_json_edge_cases_hold_what_the_phone_must_follow():
    assert list(json.loads('{"b":1,"a":2,"b":3}').items()) == [("b", 3), ("a", 2)]  # first place, last value
    assert json.loads('"\\ud800"') == "\ud800"  # a lone surrogate, kept
    with pytest.raises(ValueError, match="4300"):
        json.loads("1" * 4301)


# --- float() and int() --------------------------------------------------------------------------------------


def _float_answer(s: str) -> str | None:
    try:
        return f"{struct.unpack('<Q', struct.pack('<d', float(s)))[0]:016x}"
    except ValueError:
        return None


def _int_answer(s: str) -> str | None:
    try:
        return str(int(s))
    except ValueError:
        return None


NUMBER_CURATED = [
    "", " ", "0", "1", "-1", "+1", "--1", "+-1", "-+1", "- 1", "1 ", " 1", "\t1\n", "\x0b1\x0c", "\r1\r",
    "\x1c1", "1\x1c", "\x1f1", "\x851", "1\x85", "\xa01.5\xa0", "\u30001\u3000", "\u20281", "\u180e1", "\u200b1",
    "\ufeff1", "1\x00", "\x001", "1\x002", "00", "007", "-0", "+0", "0_0", "1_000", "1__000", "_1", "1_", "1_.5",
    "1._5", "1.5_", "1_000.0_1", "1e1_0", "1_e10", "1e_10", " 1_0 ", "_ 1", "1 _", "1_000_000", "١٢٣", "١٢_٣",
    "١.٥", "١e٥", "１２３", "－１", "𝟎𝟏", "𝟘𝟙𝟚", "௧௨", "١ ", " ١", "1.", ".1", ".", "-.", "-.1", "+.1", "1.e5",
    ".e5", "e5", "1e", "1e+", "1e-", "1e+5", "1e-5", "1E5", "1e05", "1e+05", "1e5.5", "1.5e", "1.5e+", "0x10",
    "0o7", "0b1", "1d", "1f", "1L", "1j", "inf", "-inf", "+inf", "INF", "Inf", "iNf", "infinity", "Infinity",
    "INFINITY", "-Infinity", "infinit", "infinityy", "in", "i", "nan", "NaN", "NAN", "-nan", "+nan", "nan(1)",
    "nanx", "na", "in_f", "n_an", "1e400", "-1e400", "1e-400", "1e" + "9" * 30, "1e-" + "9" * 30,
    "1" * 4300, "1" * 4301, "0" * 4301 + "1", "-" + "1" * 4300, "1_" * 2150 + "1", "0." + "1" * 5000,
    "9007199254740993", "123456789012345678901234567890", "2.2250738585072011e-308", "4.9e-324", "2e-324",
    "2.4703282292062328e-324", "1.7976931348623159e308", "1,000", "1 000", "1'000", "١,٠", "½", "²", "Ⅻ",
    "一", "①", "\u00b2", "\U0001d7ce.5", "\U000104a0", "\U0001e950", "\U0001fbf0", "\U00016b50",
    "1\U0001f600", "\x7f1", "1\x7f",
]

NUMBER_POOL = ["0", "1", "5", "9", "00", "12", ".", ".", "e", "E", "+", "-", "_", "_", " ", "\t", "inf", "nan",
               "infinity", "x", "١", "٥", "１", "𝟗", "\u3000", "\xa0", "\x85", "\x1c", "\u2028"]


def _decimal_runs() -> list[int]:
    """The first code point of each run of ten decimal digits."""
    return [cp for cp in itertools.chain(range(0xD800), range(0xE000, MAX))
            if chr(cp).isdecimal() and unicodedata.decimal(chr(cp)) == 0]


def _number_inputs() -> list[str]:
    out = list(NUMBER_CURATED)
    for zero in _decimal_runs():
        digits = "".join(chr(zero + k) for k in range(10))
        out += [digits, "-" + digits[1:4] + "." + digits[5:], digits[1] + "_" + digits[2] + "e" + digits[3],
                " " + digits[7] + " "]
    spaces = [chr(cp) for cp in itertools.chain(range(0xD800), range(0xE000, MAX)) if chr(cp).isspace()]
    out += [w + "1.5" + w for w in spaces] + ["\x1c", "\x1d", "\x1e", "\x1f", "\x85"]
    out += [chr(cp) + "1" for cp in range(0x80)]
    rng = random.Random(SEED)
    for _ in range(1500):
        out.append("".join(rng.choice(NUMBER_POOL) for _ in range(rng.randrange(1, 9))))
    return _unique(out)


def number_records() -> list[dict]:
    inputs = _number_inputs()
    rng = random.Random(SEED + 1)
    floats = _unique(inputs + _halfway_literals(rng, 150) + _random_floats(rng, 600))
    records = []
    for batch in _batches(floats):
        records.append({"fn": "float", "args": [batch], "out": [_float_answer(s) for s in batch]})
    for batch in _batches(inputs):
        records.append({"fn": "int", "args": [batch], "out": [_int_answer(s) for s in batch]})
    assert not any(_surrogates(s) for s in floats)
    return records


def test_sites_numbers_jsonl():
    check(OUT / "sites_numbers.jsonl", jsonl(number_records(), corpus="py/sites_numbers", made_by=MADE_BY))


# --- str.capitalize -----------------------------------------------------------------------------------------


CAPITALIZE_CURATED = [
    "", "a", "A", "ab", "AB", "aB", "hello world", "HELLO WORLD", "ǆungla", "ǅungla", "Ǆungla", "ǈ", "ǉx", "ßx",
    "ß", "ﬁx", "ﬃ", "ŉ", "ǰ", "ΐ", "ᾳ", "ᾼ", "ᾀx", "և", "ﬓ", "ﬗ", "ΑΣ", "ΑΣ ΑΣ", "ΣΑ", "Σ", "aΣ", "ΑΣ.", "ΑΣΑ",
    "ΑΣ'Α", "Α'Σ'", "1Σ", "ΣΣ", "ΣΑΣ", "ὈΔΥΣΣΕΎΣ", "ΑΣ\u0345", "İstanbul", "ISTANBUL", "ıI", "İİ", "აბგ", "ᲐᲑᲒ",
    "Ꭰꭰ", "ꭰꭰ", "\U00010428\U00010400", "\U00010400\U00010428", "\U0001e922\U0001e900", "ʼn", "123abc", " a",
    "_a", "宋冬野", "a宋", "ÉCOLE", "école", "major", "minor", "dorian", "mixolydian", "phrygian", "LOCRIAN",
    "lydian", "aeolian", "ionian", "harmonic minor", "el_cuarteto", "los-prisioneros", "soda", "Ⅻ", "ⅻ", "ⓐⓑ",
    "Ⓐⓑ", "\u0345", "\u0345a", "\u1fbe", "ǲ", "ǳ", "ẞ", "ẞX", "ᾩ", "ῼ", "ﬀ", "ﬆ",
]

POOLS = {
    "latin": "abcdefxyzABCDEFXYZéÉàÀñÑçÇßẞǆǅǄǉǈǇǌǋǊĳĲŉǰ",
    "greek": "αβγδΣσςΑΒΓΔΩωΐΰᾳᾼᾀᾈῳῼ\u0345\u0301'.",
    "cyrillic": "абвгдАБВГДёЁ",
    "other": "აბგᲐᲑᲒꭰᏸᎠ\U00010428\U00010400\U0001e922\U0001e900ⓐⒶⅻⅫ宋冬 _-1'\u00ad\u200d",
}


def _random_strings(n: int, pools: dict[str, str]) -> list[str]:
    rng = random.Random(SEED)
    groups = list(pools.values())
    out = []
    for _ in range(n):
        favourite = rng.choice(groups)
        out.append("".join(rng.choice(favourite if rng.random() < 0.7 else rng.choice(groups))
                           for _ in range(rng.randrange(1, 9))))
    return out


def capitalize_records() -> list[dict]:
    cps = list(itertools.chain(range(0xD800), range(0xE000, MAX)))
    alone = [[cp, chr(cp).capitalize()] for cp in cps if chr(cp).capitalize() != chr(cp)]
    after = [[cp, ("a" + chr(cp)).capitalize()[1:]] for cp in cps if ("a" + chr(cp)).capitalize()[1:] != chr(cp)]
    assert all(("a" + chr(cp)).capitalize()[0] == "A" for cp in cps[::97])
    records = [{"fn": "str.capitalize", "args": ["each code point alone"], "out": alone},
               {"fn": "str.capitalize", "args": ["each code point after an a"], "out": after}]
    strings = _unique(CAPITALIZE_CURATED + _random_strings(2500, POOLS))
    records += [{"fn": "str.capitalize", "args": [batch], "out": [s.capitalize() for s in batch]}
                for batch in _batches(strings)]
    return records


def test_sites_capitalize_jsonl():
    check(OUT / "sites_capitalize.jsonl", jsonl(capitalize_records(), corpus="py/sites_capitalize",
                                                made_by=MADE_BY))


# --- urljoin, urlunsplit and urlencode ----------------------------------------------------------------------


RFC3986_BASE = "http://a/b/c/d;p?q"
RFC3986_REFS = [
    "g:h", "g", "./g", "g/", "/g", "//g", "?y", "g?y", "#s", "g#s", "g?y#s", ";x", "g;x", "g;x?y#s", "", ".", "./",
    "..", "../", "../g", "../..", "../../", "../../g", "../../../g", "../../../../g", "/./g", "/../g", "g.", ".g",
    "g..", "..g", "./../g", "./g/.", "g/./h", "g/../h", "g;x=1/./y", "g;x=1/../y", "g?y/./x", "g?y/../x", "g#s/./x",
    "g#s/../x", "http:g", "http:", "http:?q", "http:#f", "https:g", "//", "///", "////g", "//g/", "/", "//[::1]/x",
    "//[::1", "//]x", "http://[v1.x]/", "http://[1.2.3.4]/", "HTTP://A/B", "http://a/b/c/d;p?q", "?", "#", "?#",
    "\x00g", " g", "g ", "\tg\n", "a\r\nb", "../" * 6 + "g", "g/../../..", "g/..", "g/.", "...", ".../g", "/..",
    "/.", "//a/../b", "mailto:x@y", "javascript:void(0)", "data:text/plain,x", "foo:bar", "file:///x", "ftp:x",
    "1:x", "a+b-c.d:x", "-a:x", "a_b:x", "é:x", "C:\\x", "//é/x", "//x\u2100y/", "%2e%2e/g", "%2E/g",
    "//[foo]/x", "//[v1]/x", "//[vz.x]/", "//u@[::1]:80/x", "//[::1]x/", "//a[::1]/",
]

BASES = [
    RFC3986_BASE, "http://a/b/c/d", "http://a/b/c/", "http://a", "http://a/", "http://a?q", "http://a#f",
    "https://www.ultimate-guitar.com/", "https://www.ultimate-guitar.com/artist/soda_stereo_2946",
    "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-79209",
    "https://acordes.lacuerda.net/soda_stereo/", "https://harptabs.com/song.php?ID=25",
    "https://www.gametabs.net/hollow-knight/resting-grounds", "file:///home/x/y", "file:/x/y", "mailto:a@b",
    "foo:bar/baz", "foo://h/a/b", "svn+ssh://h/a/b", "ws://h/a", "/relative/base", "relative/base", "", "//h/x",
    "http:///x", "http://h//a//b/", "http://h/a/./b/../c", "http://u:p@h:80/a?x#y", "HTTP://H/A", "http://[::1]/a",
]

CARACOLE_REFS = [
    "/artist/soda_stereo_2946", "/artist/2946", "artist/x_1", "https://www.ultimate-guitar.com/artist/x",
    "https://tabs.ultimate-guitar.com/tab/x/y-chords-1", "//www.ultimate-guitar.com/artist/x", "/favicon.ico",
    "favicon.png", "../img/icon.png", "./icon.svg", "/static/i.png?v=3", "https://cdn.example.org/i.ico", "?page=2",
    "?filter=chords&page=2", "#top", "data:image/png;base64,AAAA", "//cdn.x/i.png", "/a b/é?ç=1#ü",
]


def _join(base: str, url: str):
    try:
        return urllib.parse.urljoin(base, url)
    except ValueError as e:
        return {"err": _err(e)}


def _unsplit(parts: list[str]):
    try:
        return urllib.parse.urlunsplit(parts)
    except ValueError as e:
        return {"err": _err(e)}


SPLIT_URLS = RFC3986_REFS + BASES + CARACOLE_REFS + [
    "http://h/p?", "http://h/p#", "http://h/p?#", "http:?x", "http:#x", "//h", "//h?x", "mailto:", "a:", ":",
    ":x", "x:", "//", "///x", "http:///x", "http:////x", "foo:////x", "foo:x//y", "file:x", "file://", "x//y",
]


def _unsplit_parts() -> list[list[str]]:
    parts = []
    for url in SPLIT_URLS:
        try:
            parts.append(list(urllib.parse.urlsplit(url)))
        except ValueError:
            continue
    parts += [list(p) for p in itertools.product(["", "http", "mailto", "file", "foo", "svn+ssh"],
                                                 ["", "h", "u@h:1"], ["", "p", "/p", "//p", "a:b", "p//q"],
                                                 ["", "q"], ["", "f"])]
    return _unique([tuple(p) for p in parts])


ENCODE_STRINGS = ["", "a", "a b", "a+b", "a&b", "a=b", "~", "-_.", "/", "?#", "%", "%20", "é", "😀", "宋冬野",
                  "\x00", "\x7f", "\n", " ", "  ", "chords", "filter", "page", "2", "a b+c&d=e/f?g#h%i~j",
                  "!*'();:@&=+$,/?#[]", "\u2028", "\U0010ffff", "ÿ", "\ufeff"]


def _encode_cases() -> list[tuple[list, bool]]:
    rng = random.Random(SEED)
    cases: list[tuple[list, bool]] = [([], False), ([("a", "")], False), ([("", "")], False),
                                      ([("filter", "chords"), ("page", "2")], False), ([("page", "2")], False),
                                      ([("file", "Artist/Title/guitar-1.gp5")], False), ([("q", "Soda Stereo")], False),
                                      ([("k", ["a", "b"])], True), ([("k", [])], True), ([("k", "ab")], True),
                                      ([("k", ["é", "a b", "+"]), ("j", "x")], True), ([("a", "1"), ("a", "2")], True)]
    for _ in range(300):
        pairs = [(rng.choice(ENCODE_STRINGS) + rng.choice(ENCODE_STRINGS),
                  rng.choice(ENCODE_STRINGS) + rng.choice(ENCODE_STRINGS)) for _ in range(rng.randrange(1, 5))]
        cases.append((pairs, False))
    for _ in range(100):
        pairs = [(rng.choice(ENCODE_STRINGS),
                  [rng.choice(ENCODE_STRINGS) for _ in range(rng.randrange(0, 4))] if rng.random() < 0.6
                  else rng.choice(ENCODE_STRINGS)) for _ in range(rng.randrange(1, 4))]
        cases.append((pairs, True))
    return cases


def url_records() -> list[dict]:
    records = []
    refs = _unique(RFC3986_REFS + CARACOLE_REFS)
    for base in BASES:
        records.append({"fn": "urllib.parse.urljoin", "args": [base, refs], "out": [_join(base, r) for r in refs]})
    rng = random.Random(SEED)
    segments = ["", ".", "..", "a", "b", "g", "é", "%2e", "...", ";x", "a?b", "a#b", "?q", "#f", "//h"]
    pairs = []
    for _ in range(600):
        base = rng.choice(["http://h", "https://h:1", "foo://h", "file://", "", "rel", "/abs", "mailto:x"]) + \
            "/".join(rng.choice(segments) for _ in range(rng.randrange(0, 5)))
        ref = rng.choice(["", "/", "//", "http:", "https://o", "foo:"]) + \
            "/".join(rng.choice(segments) for _ in range(rng.randrange(0, 5)))
        pairs.append((base, ref))
    for base, group in itertools.groupby(sorted(pairs), key=lambda p: p[0]):
        urls = _unique(r for _, r in group)
        records.append({"fn": "urllib.parse.urljoin", "args": [base, urls], "out": [_join(base, u) for u in urls]})
    parts = [list(p) for p in _unsplit_parts()]
    for batch in _batches(parts):
        records.append({"fn": "urllib.parse.urlunsplit", "args": [batch], "out": [_unsplit(p) for p in batch]})
    for doseq in (False, True):
        cases = [pairs for pairs, d in _encode_cases() if d == doseq]
        records.append({"fn": "urllib.parse.urlencode", "args": [[[list(p) for p in c] for c in cases]],
                        "kw": {"doseq": doseq}, "out": [urllib.parse.urlencode(c, doseq=doseq) for c in cases]})
    return records


def test_sites_url_jsonl():
    check(OUT / "sites_url.jsonl", jsonl(url_records(), corpus="py/sites_url", made_by=MADE_BY))


def test_caracoles_own_url_calls_are_among_the_records():
    """ug/fetch.py's urljoin(WWW + "/", …) and ug/artist.py's urlunsplit of its query are what the vectors hold."""
    assert "https://www.ultimate-guitar.com/" in BASES and "/artist/soda_stereo_2946" in CARACOLE_REFS
    from caracole.ug.artist import artist_page_url

    url = artist_page_url("https://www.ultimate-guitar.com/artist/soda_stereo_2946/", kind="chords", page=2)
    parts = urllib.parse.urlsplit(url)
    assert urllib.parse.urlunsplit(parts) == url
    assert ([("filter", "chords"), ("page", "2")], False) in _encode_cases()
