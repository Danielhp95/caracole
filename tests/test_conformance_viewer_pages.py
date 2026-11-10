"""viewer/page.py for the phone: a sheet's page, byte for byte, for :viewer's ``viewer.pages.SheetPage``.

The logic is Kotlin's; what page.py states as data is written here from the module itself, and what it answers is
recorded, so a change to the page regenerates what the phone reads and compares. Every page here is built after the
print rules (viewer.css's light palette on paper and its ``@page`` margins, tests/test_viewer_print.py), so the pages'
bytes are the stylesheet's as it is.

The data, ``tests/conformance/data/caracole/viewer/page.json`` (caracole/viewer/page.json on the phone's classpath,
``ViewerData.table("page")``; ``viewer_corpus.data_json``), page.py's HTML and its constants under their own names,
never retyped: ``LIBRARY_PAGE``, ``CREDIT_URL``, ``_NOTICE``, ``_CREDIT``, ``_VERSIONS``, ``_VERSION_LIST``,
``_HARMONY_ROW``, ``_GUITAR_ROW`` (``_with_guitar`` puts it after the Harmony row, once), ``_EXPORT_ROW``,
``_EXPORT_ASK``, ``_CONTROLS``, ``_SHEET_CONTROLS`` (the sheet's: the export row and its question), ``_NOTHING`` (the
header of a page whose policy can't be read); ``credit_notice``, chords-db's notice as the footer prints it
(``_credit_notice()``); and ``patterns``: ``_META_POLICY`` (a bytes pattern, written as its ASCII text: the phone runs it
over the page's bytes read as Latin-1, one character a byte) and ``_HEADER_TEXT``, as Python writes them. The page's
icon is page_icon.py's ``LINK``, caracole/page/icon.json's ``link`` (M2's), which a test here holds to it.

The vectors (``helpers.corpus.jsonl``); a key is ``[tonic, mode]``, a sheet's section ``{"label", "chorus", "lines"}``
and a line one of ``{"lyrics": [[head, text], …]}`` (a head an int, a chord's index into the sheet's chords, a string,
a mark, or null), ``{"chords": [int or string, …]}``, ``{"text": …}``, ``{"tab": [line, …]}``, ``{"blank": true}``:

``vectors/viewer/pages_parts.jsonl``, the page's frame, function by function, with no sheet read:

- ``artist_line(artist, names)``, ``pdf_line(files)`` (``files`` as ``[[name, label, twin or null], …]``),
  ``zh_attr(text, names)``: their HTML; ``names_table(chinese, texts)``: the table, or null;
- ``_words(texts)`` (a batch): each text cut as the page cuts it (``_lyric_texts``);
- ``_facts(key, [[origin, capo], …])``: the key line's HTML for each (``key`` null for a sheet with none);
- ``_footer(links)``, ``_page(title, body, styles, scripts, names)``: their HTML;
- ``viewer_csp(page)``: ``page`` as ``{"base64": …}``, the header;
- ``shown_html(chords, pre, sections)`` (this module's): ``_preamble_html(pre, chords)`` (null for no ``pre``) and
  ``_section_html(section, chords)`` of each section, as ``page._sheet_html`` joins them: the sheet as
  ``page._shown`` shows it, for ``SHOWN_PER_TAG`` sheets of each tag of ``viewer_corpus.sheets()`` (``SHOWN_FIXTURES``
  fixtures', none of ``SHOWN_SKIPPED``'s) and every edge sheet.

``vectors/viewer/pages-1.jsonl`` to ``pages-<PAGE_FILES>.jsonl``, the pages in that many runs, in order (each file a
test of its own, a few seconds each): ``build_viewer(cho, **kw)`` for every sheet of ``viewer_corpus.sheets()`` (its
``key`` and ``key_source``, and options drawn by ``SEED``: ``transpose``, ``start``, ``pdf`` and ``pdf_traditional``,
``export``, ``versions``, ``guitar``, ``harmonica`` with or without a ``harp``, ``video``), then ``EXTRA`` pages (every
option at once, names to escape, a title that would end a script, an empty sheet). ``kw`` holds what isn't
build_viewer's default; ``sheet`` names the corpus sheet. A page is 200–650 KB, so a record holds its digests (the
corpus plan's page records): ``out`` is ``{"sha256", "size"}`` of the page's UTF-8, ``body`` (the first ``PART`` hex
digits of the SHA-256 of the markup between ``<body>\\n`` and the ``song`` block: ``_body``'s), ``data`` (each member of
the ``song`` block in its order as ``name=digest``, space-separated, the digest the first ``DIGEST`` hex digits of the
SHA-256 of ``json.dumps(value, ensure_ascii=False, separators=(",", ":"))``, so a mismatch names the member at fault),
``names`` (the ``song-names`` block's JSON text's, as ``body``'s, or null), and ``written_script`` and ``is_chinese``
of the sheet.

``vectors/viewer/page_whole.json``: ``WHOLE``, one small page kept whole (a sheet with no chords, with a PDF, Guitar
Pro files, versions, a video and a start): ``pages``, each ``{"fn", "args", "kw", "pieces"}``, the page as its pieces in
order, each a text or ``{"asset": name}`` where it inlines viewer/'s file ``name`` whole (ViewerAssets.text): the page
is their concatenation, byte for byte, without a copy of the 316 kB of scripts and styles every page inlines.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_pages.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import base64
import copy
import functools
import hashlib
import json
import random
import re
from typing import Any

import pytest

from caracole import page_icon
from caracole.viewer import page
from caracole.viewer.sheet import Blank, ChordRow, Lyrics, Section, Tab, Text, parse_sheet
from caracole.viewer.theory import Key
from helpers import viewer_corpus
from helpers.corpus import DATA, check, json_document, jsonl

MADE_BY = "tests/test_conformance_viewer_pages.py"
HELPER = "test_conformance_viewer_pages."
P = "caracole.viewer.page."
SEED = viewer_corpus.SEED + 700
DIGEST = 8  # hex digits of a data member's digest: enough to name the member at fault, an eighth of a SHA-256's
PART = 16  # those of the body's and the names' digests: the page's own SHA-256 is whole
PAGE_FILES = 6  # pages-1.jsonl to pages-6.jsonl: each generator test a few seconds
SHOWN_PER_TAG = 1
SHOWN_FIXTURES = 2
WORDS_BATCH = 100
WORDS_EVERY = (12, 4)  # of the sheets' texts, one in this many ASCII ones, one in this many others
SHOWN_SKIPPED = ("qualities", "catalogue")  # tags whose sheets show nothing the others don't
# The constants of page.py the phone reads, in this order.
CONSTANTS = ("LIBRARY_PAGE", "CREDIT_URL", "_NOTICE", "_CREDIT", "_VERSIONS", "_VERSION_LIST", "_HARMONY_ROW",
             "_GUITAR_ROW", "_EXPORT_ROW", "_EXPORT_ASK", "_CONTROLS", "_SHEET_CONTROLS", "_NOTHING")
# build_viewer's keywords and their defaults: a record's kw holds the others alone.
DEFAULTS: dict[str, Any] = {"key": None, "key_source": None, "transpose": 0, "start": None, "pdf": None,
                            "export": True, "versions": None, "guitar": (), "harmonica": (), "pdf_traditional": None,
                            "video": None}
STARTS = ("t=2", "t=-1&mode=dorian", "t=0&mode=aeolian&capo=3", "capo=2&alt=0.1-1", "t=5&at=3.2&inst=ukulele")
GUITARS = (["guitar-1.gp5"], ["guitar-1.gp5", "guitar-2.gpx"], ["guitar-3.gp"],
           ["guitar-1.ptb", "guitar-2.gp4", "guitar-10.gp5"])
HARPS = (0, 7, 2, 10, 19, -5)
CHANNELS = ("Placeholder Records", "Canal Inventado", "合成频道", "")
EDGE_ARTISTS = ("", "AC/DC", "Guns N' Roses", "Simon & Garfunkel", "宋冬野", "a b/c?d#e%f&g=h+i", "Ünïcødé Ñame",
                "<script>alert(1)</script>", '"Quoted" Band', "~._-", "李宗盛 (Jonathan Lee)", "  spaced  ", "💿 Emoji",
                "Ⅳ Roman", "東京事変")
EDGE_WORDS = ("", " ", "  ", "a", "a b", "a  b ", " a", "\ta\tb", "我们一起", "我 们", "a我b", "我a b们", "ｆｕｌｌ ｗｉｄｔｈ",
              "カタカナ テスト", "한국어 노래", "a\u3000b", "\u3000", "x\u00a0y", "😀 smile", "a😀b", "ﾊﾝｶｸ", "—dash—",
              "rock'n'roll", "end. ", "(oh) yeah!", "斑马，斑马", "「引用」です", "x\u200by")


def constants() -> dict[str, Any]:
    out: dict[str, Any] = {name: getattr(page, name) for name in CONSTANTS}
    out["credit_notice"] = page._credit_notice()
    assert page._META_POLICY.flags == 0 and page._HEADER_TEXT.flags & ~re.UNICODE == 0
    out["patterns"] = {"_META_POLICY": page._META_POLICY.pattern.decode("ascii"),
                       "_HEADER_TEXT": page._HEADER_TEXT.pattern}
    return out


def page_json() -> str:
    return viewer_corpus.data_json(constants())


def test_page_json_is_page_pys_html_and_constants():
    check(viewer_corpus.VIEWER_DATA / "page.json", page_json())


def test_the_data_reads_back_as_page_py_holds_it():
    data = json.loads(page_json())
    for name in CONSTANTS:
        assert data[name] == getattr(page, name), name
    # _with_guitar's one replacement, on either set of controls; the sheet's are the shared ones and the export's
    for controls in ("_CONTROLS", "_SHEET_CONTROLS"):
        assert data[controls].count(data["_HARMONY_ROW"]) == 1
        assert (data[controls].replace(data["_HARMONY_ROW"], data["_HARMONY_ROW"] + data["_GUITAR_ROW"], 1)
                == page._with_guitar(getattr(page, controls), True))
    assert data["_EXPORT_ROW"] in data["_SHEET_CONTROLS"] and data["_SHEET_CONTROLS"].endswith(data["_EXPORT_ASK"])
    assert re.compile(data["patterns"]["_META_POLICY"].encode("ascii")).pattern == page._META_POLICY.pattern
    # The icon is M2's data: caracole/page/icon.json's link is page_icon.LINK, as the page inlines it.
    icon = json.loads((DATA / "page" / "icon.json").read_text(encoding="utf-8"))
    assert icon["link"] == page_icon.LINK == page.PAGE_ICON


# --- the frame's parts --------------------------------------------------------------------------------------------


def line_json(line) -> dict[str, Any]:
    if isinstance(line, Lyrics):
        return {"lyrics": [[head, text] for head, text in line.parts]}
    if isinstance(line, ChordRow):
        return {"chords": list(line.items)}
    if isinstance(line, Text):
        return {"text": line.text}
    if isinstance(line, Tab):
        return {"tab": list(line.lines)}
    assert isinstance(line, Blank)
    return {"blank": True}


def section_json(section: Section) -> dict[str, Any]:
    return {"label": section.label, "chorus": section.chorus, "lines": [line_json(line) for line in section.lines]}


def key_json(key: Key | None) -> list[Any] | None:
    return None if key is None else [key.tonic, key.mode]


def shown_html(chords: list[str], pre: Section | None, sections: list[Section]) -> dict[str, Any]:
    return {"pre": page._preamble_html(pre, chords) if pre else None,
            "sections": [page._section_html(s, chords) for s in sections]}


def _shown_sheets() -> list[viewer_corpus.CorpusSheet]:
    """SHOWN_PER_TAG sheets of each tag but SHOWN_SKIPPED, SHOWN_FIXTURES fixtures' and every edge sheet, in the
    corpus's order."""
    sheets = viewer_corpus.sheets()
    picked: dict[str, None] = {}
    tags: dict[str, int] = {}
    for sheet in sheets:
        for tag in sheet.tags:
            if tag in SHOWN_SKIPPED:
                continue
            if tags.get(tag, 0) < (SHOWN_FIXTURES if tag == "fixture" else SHOWN_PER_TAG) or tag == "edge":
                tags[tag] = tags.get(tag, 0) + 1
                picked[sheet.name] = None
    return [s for s in sheets if s.name in picked]


def _names_tables() -> list[tuple[bool, list[str]]]:
    """names_table's inputs: each Chinese or kana sheet's title, artist and page title, and edges."""
    out: list[tuple[bool, list[str]]] = []
    for sheet in viewer_corpus.sheets():
        if {"chinese", "kana", "fixture"} & set(sheet.tags) or "斑马" in sheet.title:
            title = sheet.title or "Untitled"
            out.append((True, [title, sheet.artist, f"{title} · {sheet.artist}" if sheet.artist else title]))
    out += [(False, ["斑马", "宋冬野", "斑马 · 宋冬野"]), (True, ["Latin", "Only", "Latin · Only"]),
            (True, ["愛情故事", "", "愛情故事"]), (True, ["說話", "聽見", "說話 · 聽見"]), (True, ["发", "髮", "發"]),
            (True, []), (True, ["著", "着", "著 · 着"])]
    return out


def _lyric_texts() -> list[str]:
    """_words' inputs: EDGE_WORDS, then the sheets' texts (a line's parts, a line of text), one in WORDS_EVERY of
    each kind."""
    found: dict[str, None] = {}
    for sheet in viewer_corpus.sheets():
        for section in parse_sheet(sheet.cho).sections:
            for line in section.lines:
                if isinstance(line, Lyrics):
                    found.update(dict.fromkeys(text for _, text in line.parts))
                elif isinstance(line, Text):
                    found[line.text] = None
    texts = [t for n, t in enumerate(found) if n % WORDS_EVERY[not t.isascii()] == 0]
    return list(dict.fromkeys([*EDGE_WORDS, *texts]))


def _csp_inputs() -> list[bytes]:
    heads = []
    for cho in ("{title: A}\n", viewer_corpus.EDGE_SHEETS[6]):
        built = page.build_viewer(cho).encode("utf-8")
        heads.append(built[:built.index(b"<title")])
    meta = b'<meta http-equiv="Content-Security-Policy" content="%s">'
    return heads + [
        meta % b"default-src &#39;none&#39;; script-src &amp; &lt;x&gt;",
        meta % b"default-src 'none'\xff",
        meta % b"default-src 'none';\nscript-src 'self'",
        meta % "default-src 'none'; é".encode("utf-8"),
        b"<html><head><title>No policy</title></head></html>",
        meta % b"first-src 'none'" + meta % b"second-src 'none'",
        meta % b"",
        meta % b"default-src 'none'&#x0a;img-src data:",
        b'<META HTTP-EQUIV="Content-Security-Policy" CONTENT="default-src \'none\'">',
        meta % b"default-src &amp 'none' &copy",
        meta % b"default-src 'none'; style-src 'sha256-abc='" + b"\n<p>after</p>",
        b'<meta http-equiv="Content-Security-Policy" content="a"b">',
        meta % b"\t default-src 'none'",
        meta % b"~ !\"",
    ]


def parts_records() -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    records: list[dict[str, Any]] = []
    tables = [(chinese, texts, page.names_table(chinese, texts)) for chinese, texts in _names_tables()]
    for chinese, texts, names in tables:
        records.append({"fn": P + "names_table", "args": [chinese, texts], "out": names})
    named = [names for _, _, names in tables if names] + [None]
    artists = list(dict.fromkeys([s.artist for s in viewer_corpus.sheets()] + list(EDGE_ARTISTS)))
    for artist in artists:
        names = rng.choice(named)
        records.append({"fn": P + "artist_line", "args": [artist, names], "out": page.artist_line(artist, names)})
    for _, texts, names in tables:
        if names is not None:
            for text in dict.fromkeys([*texts, "斑马", "Latin", ""]):
                records.append({"fn": P + "zh_attr", "args": [text, names], "out": page.zh_attr(text, names)})
    records.append({"fn": P + "zh_attr", "args": ["斑马", None], "out": page.zh_attr("斑马", None)})
    for files in ([], [("sheet.pdf", "PDF", None)], [("sheet.pdf", "PDF", "sheet (Traditional).pdf")],
                  [("sheet (auto).pdf", "PDF", "sheet (auto, Traditional).pdf"), ("a b&c\"d'.pdf", "A & B", None)],
                  [("songbook.pdf", "Songbook PDF", None), ("songbook (Traditional).pdf", "繁體 PDF", None)],
                  [("ünï/cødé #1?.pdf", "<b>PDF</b>", "x%20y.pdf")]):
        records.append({"fn": P + "pdf_line", "args": [[list(f) for f in files]], "out": page.pdf_line(files)})
    texts = _lyric_texts()
    for start in range(0, len(texts), WORDS_BATCH):
        batch = texts[start:start + WORDS_BATCH]
        records.append({"fn": P + "_words", "args": [batch], "out": [page._words(t) for t in batch]})
    origins = (None, "from the tab", "estimated from the chords", "from the sheet", "from <b>x & y</b>")
    for key in [None, *viewer_corpus.keys()]:
        cases = [[rng.choice(origins), capo] for capo in (0, rng.choice((1, 2, 3, 5)), rng.choice((7, 9, 11, 12)))]
        records.append({"fn": P + "_facts", "args": [key_json(key), cases],
                        "out": [page._facts(key, origin, capo) for origin, capo in cases]})
    for links in ("", page.pdf_line([("sheet.pdf", "PDF", "sheet (Traditional).pdf")])):
        records.append({"fn": P + "_footer", "args": [links], "out": page._footer(links)})
    frames = [("Song · Artist", "<p>x</p>\n", ("a{}",), ("1", "2"), None),
              ("A <b> & \"c\"", "", ("a{}", "b{color:red}"), (), None),
              ("斑马 · 宋冬野", "<div>\n</div>\n", ("é{}",), ("console.log('ü')",),
               page.names_table(True, ["斑马", "宋冬野", "斑马 · 宋冬野"])),
              ("Untitled", "body", (), ("",), {"simplified": {}, "traditional": {"Untitled": "x"}})]
    for title, body, styles, scripts, names in frames:
        records.append({"fn": P + "_page", "args": [title, body, list(styles), list(scripts), names],
                        "out": page._page(title, body, styles=styles, scripts=scripts, names=names)})
    for raw in _csp_inputs():
        records.append({"fn": P + "viewer_csp", "args": [{"base64": base64.b64encode(raw).decode("ascii")}],
                        "out": page.viewer_csp(raw)})
    for sheet in _shown_sheets():
        parsed = parse_sheet(sheet.cho)
        pre, sections = page._shown(parsed)
        records.append({"fn": HELPER + "shown_html", "sheet": sheet.name,
                        "args": [parsed.chords, section_json(pre) if pre else None,
                                 [section_json(s) for s in sections]],
                        "out": shown_html(parsed.chords, pre, sections)})
    return records


def test_the_frames_parts_are_page_pys():
    check(viewer_corpus.VIEWER_VECTORS / "pages_parts.jsonl",
          jsonl(parts_records(), corpus="viewer/pages_parts", made_by=MADE_BY))


# --- whole pages --------------------------------------------------------------------------------------------------


def _versions(rng: random.Random, tab: str) -> dict[str, Any]:
    total = rng.randint(1, 14)
    entries = []
    for n in range(min(total, rng.randint(1, 2))):
        entries.append({"tab": str(1000 + n) if n else tab, "number": n + 1, "rating": rng.choice((4.86, 5, 3.5, None)),
                        "votes": rng.choice((408, 12, 0)), "label": rng.choice(("", "Ver 2", "acoustic", "Versión")),
                        "note": rng.choice((None, "the one", "kept by you")), "rank": n + 1, "kept": n < 2,
                        "chosen": n == 0, "gone": n == 3, "page": f"version-{1000 + n}.html" if n else None,
                        "url": f"https://tabs.ultimate-guitar.com/tab/x/y-chords-{1000 + n}", "this": n == 0})
    return {"total": total, "list": entries, "sheet": rng.choice(("ug", "lacuerda", "auto", None)),
            "pinned": rng.random() < 0.3}


def _video(rng: random.Random) -> dict[str, Any]:
    mark: dict[str, Any] = {"name": "YouTube", "letters": "YT"}
    if rng.random() < 0.5:
        mark["src"] = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    return {"title": rng.choice(("Placeholder Song (Official Video)", "Canción <inventada> & más", "合成歌曲")),
            "href": rng.choice(("https://www.youtube.com/watch?v=abcdefghijk", "https://youtu.be/abcdefghijk",
                                "https://example.com/video")),
            "channel": rng.choice(CHANNELS), "mark": mark}


def _harmonica(rng: random.Random) -> list[dict[str, Any]]:
    tabs = []
    for n in range(1, rng.randint(1, 3) + 1):
        tab: dict[str, Any] = {"name": f"harmonica-{n}.txt", "href": f"harmonica-{n}.txt",
                               "page": f"harmonica-{n}.html"}
        if rng.random() < 0.5:
            tab["key"] = rng.choice(("C", "G", "A minor", "Bb"))
        if rng.random() < 0.7:
            tab["harp"] = rng.choice(HARPS)
        tabs.append(tab)
    return tabs


def _options(rng: random.Random, sheet: viewer_corpus.CorpusSheet) -> dict[str, Any]:
    kw: dict[str, Any] = {"key": sheet.key, "key_source": sheet.key_source}
    kw["transpose"] = rng.choice((0, 0, 0, 0, 2, -3, 5, 11, -12))
    if rng.random() < 0.25:
        kw["start"] = rng.choice(STARTS)
    if rng.random() < 0.7:
        kw["pdf"] = "sheet (auto).pdf" if sheet.auto else "sheet.pdf"
        if "chinese" in sheet.tags and rng.random() < 0.7:
            kw["pdf_traditional"] = "sheet (auto, Traditional).pdf" if sheet.auto else "sheet (Traditional).pdf"
    kw["export"] = rng.random() < 0.8
    if rng.random() < 0.3:
        kw["versions"] = _versions(rng, str(rng.randint(100, 9999)))
    if rng.random() < 0.25:
        kw["guitar"] = rng.choice(GUITARS)
    if rng.random() < 0.25:
        kw["harmonica"] = _harmonica(rng)
    if (sheet.auto and rng.random() < 0.7) or rng.random() < 0.05:
        kw["video"] = _video(rng)
    return {k: v for k, v in kw.items() if v != DEFAULTS[k] and not (v in ((), []) and DEFAULTS[k] == ())}


EXTRA_SHEETS = (
    ("escapes", "{title: Rock & Roll <Live> \"Take 2\" 'b'}\n{artist: AC/DC & Friends #1 ~ é}\n{key: E}\n"
                "{comment: Verse <1> & \"2\"}\n[E]Words & <things> [A]\"quoted\" 'single'\n[*x2] [B7]\n"),
    ("script", "{title: </script><!-- x}\n{artist: <!--</script>-->}\n{comment: Verse}\n[C]</script> [G]<!--\n"),
    ("empty", ""),
    ("no-artist", "{title: Alone}\n{comment: Verse}\nWords with no chords at all\n"),
    ("untitled", "{artist: Somebody}\n[Am]La [Dm]la\n"),
)


def _extra(rng: random.Random) -> list[tuple[str, str, dict[str, Any]]]:
    """Every option at once on a Chinese, a kana and an auto sheet, and EXTRA_SHEETS."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    for tag in ("chinese", "kana", "auto", "legend", "capo"):
        sheet = next(s for s in viewer_corpus.sheets() if tag in s.tags)
        kw = {"key": sheet.key, "key_source": sheet.key_source, "transpose": 3, "start": STARTS[2],
              "pdf": "sheet.pdf", "pdf_traditional": "sheet (Traditional).pdf", "export": True,
              "versions": _versions(rng, "777"), "guitar": GUITARS[3], "harmonica": _harmonica(rng),
              "video": _video(rng)}
        kw["harmonica"].append({"name": "harmonica-9.txt", "href": "harmonica-9.txt", "page": "harmonica-9.html",
                                "harp": 4})
        out.append((sheet.name, sheet.cho, {k: v for k, v in kw.items() if v is not None}))
    for name, cho in EXTRA_SHEETS:
        out.append((f"extra:{name}", cho, {"pdf": "sheet.pdf", "guitar": GUITARS[1], "export": name != "empty"}))
        out.append((f"extra:{name}", cho, {"key": "C", "key_source": "tab", "video": _video(rng)}))
    return out


def _call(cho: str, kw: dict[str, Any]) -> str:
    """build_viewer of ``cho`` given ``kw`` as the record holds it: a corpus writes an object's members sorted
    (helpers.corpus), and the phone builds the page from what it reads, so the page's ``versions``, ``video`` and
    ``harmonicaTabs`` keep the members in that order on both sides."""
    return page.build_viewer(cho, **json.loads(json.dumps(kw, sort_keys=True)))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_SONG = '<script type="application/json" id="song">'
_NAMES = '<script type="application/json" id="song-names">'


def page_out(html: str, cho: str) -> dict[str, Any]:
    """A page's record: its digests, its body's, each data member's and its names' (the module's docstring)."""
    start = html.index("<body>\n") + len("<body>\n")
    song = html.index(_SONG, start)
    payload = html[song + len(_SONG):html.index("</script>", song)]
    data = json.loads(payload)
    names = None
    if _NAMES in html:
        at = html.index(_NAMES) + len(_NAMES)
        names = _sha(html[at:html.index("</script>", at)])
    members = " ".join(f"{name}={_sha(json.dumps(value, ensure_ascii=False, separators=(',', ':')))[:DIGEST]}"
                       for name, value in data.items())
    return {"sha256": _sha(html), "size": len(html.encode("utf-8")), "body": _sha(html[start:song])[:PART],
            "data": members, "names": names and names[:PART], "written_script": page.written_script(cho),
            "is_chinese": page.is_chinese(cho)}


@functools.cache
def _pages() -> tuple[tuple[str, str, dict[str, Any]], ...]:
    """Every page's (sheet's name, cho, kw), in order: the corpus's sheets', then the extra ones."""
    rng = random.Random(SEED + 1)
    pages = [(sheet.name, sheet.cho, _options(rng, sheet)) for sheet in viewer_corpus.sheets()]
    return tuple(pages + _extra(rng))


def page_records(part: int) -> list[dict[str, Any]]:
    """The records of ``pages-<part>.jsonl``: the ``part``-th of PAGE_FILES runs of the pages, in order."""
    pages = _pages()
    size = -(-len(pages) // PAGE_FILES)
    return [{"fn": P + "build_viewer", "sheet": name, "args": [cho], "kw": copy.deepcopy(kw),
             "out": page_out(_call(cho, kw), cho)}
            for name, cho, kw in pages[(part - 1) * size:part * size]]


@pytest.mark.parametrize("part", range(1, PAGE_FILES + 1))
def test_every_page_is_page_pys(part):
    check(viewer_corpus.VIEWER_VECTORS / f"pages-{part}.jsonl",
          jsonl(page_records(part), corpus=f"viewer/pages-{part}", made_by=MADE_BY))


def test_the_pages_cover_every_option():
    pages = _pages()
    assert -(-len(pages) // PAGE_FILES) * (PAGE_FILES - 1) < len(pages)  # no file is left empty
    used = {k for _, _, kw in pages for k in kw}
    assert used == set(DEFAULTS), set(DEFAULTS) - used
    scripts = {page.written_script(cho) for _, cho, _ in pages}
    assert {None, "simplified", "traditional"} <= scripts
    named = [page.names_table(page.is_chinese(cho), [parse_sheet(cho).title, parse_sheet(cho).artist])
             for _, cho, _ in pages]
    assert any(named)
    tags = {t for s in viewer_corpus.sheets() for t in s.tags}
    assert {"chinese", "kana", "auto", "preamble", "legend", "tab", "define", "capo"} <= tags
    harped = [(cho, kw) for _, cho, kw in pages
              if any(isinstance(t.get("harp"), int) for t in kw.get("harmonica", ()))]
    assert any(page.viewer_key(cho, kw.get("key"), kw.get("key_source")) is not None for cho, kw in harped)


# --- a page kept whole --------------------------------------------------------------------------------------------

WHOLE = (
    "{title: Whole Page}\n{artist: The Placeholders}\nA note before the song\n\n{comment: Verse}\nWords alone, "
    "no chords\n\n{comment: Chorus}\nMore words\n",
    {"pdf": "sheet.pdf", "guitar": ["guitar-1.gp5"], "start": "t=2",
     "versions": {"total": 1, "list": [{"tab": "1", "number": 1, "rating": 4.5, "votes": 3, "label": "",
                                        "note": None, "rank": 1, "kept": True, "chosen": True, "gone": False,
                                        "page": None, "url": "https://tabs.ultimate-guitar.com/tab/x/y-chords-1",
                                        "this": True}], "sheet": "ug", "pinned": False},
     "video": {"title": "Whole Page (Official Video)", "href": "https://www.youtube.com/watch?v=abcdefghijk",
               "channel": "Placeholder Records", "mark": {"name": "YouTube", "letters": "YT"}}},
)


def pieces(html: str) -> list[Any]:
    """``html`` as its texts and the viewer/ files it inlines whole (``{"asset": name}``), in order."""
    style, script = page._assets()
    assets = [("viewer.css", style), ("strum.js", page._sound()), ("overlay.js", page._overlay()),
              ("instruments.js", page._instruments()), ("winds.js", page._winds()), ("viewer.js", script)]
    out: list[Any] = []
    at = 0
    for name, text in assets:
        found = html.index(text, at)
        out += [html[at:found], {"asset": name}]
        at = found + len(text)
    out.append(html[at:])
    joined = "".join(p if isinstance(p, str) else dict(assets)[p["asset"]] for p in out)
    assert joined == html
    return out


def whole_json() -> str:
    cho, kw = WHOLE
    return json_document({"pages": [{"fn": P + "build_viewer", "args": [cho], "kw": kw,
                                     "pieces": pieces(_call(cho, kw))}]},
                         corpus="viewer/page_whole", made_by=MADE_BY)


def test_a_small_page_is_kept_whole():
    check(viewer_corpus.VIEWER_VECTORS / "page_whole.json", whole_json())
