"""viewer/harpfit.py and viewer/harptab_page.py for the phone: the harp a harmonica tab's page starts on, and the
page, byte for byte, for :viewer's ``viewer.harpfit.HarpFit`` and ``viewer.pages.HarmonicaPage``; and render.py's
``_tab_harps``, the harp each tab gives its sheet's viewers (page.py ``harpTabs``).

The logic is Kotlin's; what the two modules state as data is written here from the modules themselves, and what they
answer is recorded, so a change to either regenerates what the phone reads and compares. Every page here is built
with viewer/'s stylesheets as they are, so a change to viewer.css or harptab.css (their print rules among them)
regenerates the pages' records.

**The data**, ``tests/conformance/data/caracole/viewer/harmonica_page.json`` (caracole/viewer/harmonica_page.json on
the phone's classpath, ``ViewerData.table("harmonica_page")``; ``viewer_corpus.data_json``): ``harpfit``, that
module's ``MIN_NOTES``, ``LINE_MATCH``, ``WHY`` and ``_PITCH``; and ``harptab_page``, that module's ``BPM``,
``SITE``, ``_SAID``, ``_BRACKETS`` (each ``[open, close]``), ``_JOIN``, ``_SOURCE``, ``_PLAY_ICON``, ``_NO_SHEET``,
``_NO_KEY``, ``_BAR``, ``_BAR_RAW`` and ``_PILL``, never retyped.

**The vectors** (``helpers.corpus.jsonl``). A text is ``{"fixture": path}`` (a file of tests/fixtures/, read as
UTF-8) or ``{"named": name}``, a text of ``harpfit_texts.jsonl``; a tab is ``[text, harp]``, the page's chip
(``parse(text, harp=harp)``); a digest is the first ``DIGEST`` hex digits of the SHA-256 of ``json.dumps(value,
ensure_ascii=False, separators=(",", ":"))``, or of an HTML text's UTF-8 (``PART`` digits). Floats are Python's
repr, compared to the bit.

``vectors/viewer/harpfit_texts.jsonl``: ``text(name)`` → the text, each once: the chord sheets the other records
read (``record:<tab>``, a sheet charting a tab's own sung rows, its words now and then hyphenated, bracketed or in
another case, with seeded chords, a capo, a key or none; ``other:<n>``, words no tab sings; ``keyless``, ``bare``,
``chinese``) and the tabs that are no fixture (``sung:<n>``, rows of holes over words, each hole a tone of the chord
the sheet ``sung-sheet:<n>`` plays there on a seeded harp, now and then not; the ``<pre>`` of tests/fixtures/
harptabs/'s three tab pages, ``page:<name>``; ``arrows``, a notation no preset reads; ``thin``, too little to read;
``chromatic``, read under either chip; ``tiny``, the page kept whole).

``vectors/viewer/harpfit.jsonl``:

- ``pitch(names)``: each name's pitch class, or null; ``words(texts)``: each text's words.
- ``_sheet_lines(sheet)``: each sung line's ``[[word, its chord's pitch classes sorted, or null], …]``, whole where
  its JSON is at most ``WHOLE_LINES`` characters, else ``{"digest", "lines"}``.
- ``fit_of(tab, sheet, cases)``, a record a tab with its own sheet, else one of other words or none:
  ``record_fit(parse(tab), cho)`` as ``[[harp, share, notes], …]`` (``sheet`` null:
  no record fit, and ``choose`` with no sheet), and for each case ``[key, key_source, page_key]`` the choice
  ``choose`` makes, ``[harp, why, fitted, named, page, tonic, tabs_harp]`` (``fitted``: its ``fits`` are
  ``record_fit``'s, else none).
- ``_tab_harps(tabs, sheet, key, key_source)``: render.py's, each tab ``[name, text, harp, page_key, pin]``, the
  answer ``{name: harp}``.

``vectors/viewer/harmonica_pages.jsonl``:

- ``_a(names)``; ``_harp_lines(choices)``, each choice ``[harp, why, fits, named, page, tonic]``; ``_footer(cases)``,
  each ``[tab_file, url, placed, change]``; ``_read_as(tab, pin, facts)``, the tab read as the page reads it with
  that pin, for each facts given (its first two whole, the others by their ``PART`` digits); their HTML.
- ``_overlay_data(choice, sheet, key, key_source)``: ``{"guitar", "harp"}``, each member of each as ``name=digest``,
  space-separated (``-`` for null).
- ``build_harmonica_viewer(text, **kw)`` (``kw`` its keywords but the defaults; ``cho`` a text): ``out`` is the page's
  ``{"sha256", "size"}`` of its UTF-8, ``head``, ``article``, ``foot`` and ``bar`` (the digests of the header, the
  tab, the footer and what follows it up to the data block), ``data`` (each member of the ``harp-data`` block in its
  order as ``name=digest``, space-separated), ``overlay`` (its ``overlay``'s ``guitar`` and ``harp`` the same way)
  and ``names`` (the ``song-names`` block's digest, or null).

``vectors/viewer/harmonica_pages_whole.jsonl``: ``WHOLE``, one small page kept whole: ``pieces``, its texts and
``{"asset": name}`` where it inlines viewer/'s file ``name`` whole (ViewerAssets.text), whose concatenation is the
page.

Regenerate: ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_viewer_harmonica.py``, then
``nix develop ./android -c gradle -p android :viewer:test``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import random
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from caracole import harptabs, render
from caracole.viewer import harp, harpfit, harptab_page, page
from caracole.viewer.harptab import parse
from helpers import viewer_corpus
from helpers.corpus import FIXTURES, check, fixture_bytes, fixture_ref, jsonl

MADE_BY = "tests/test_conformance_viewer_harmonica.py"
HELPER = "test_conformance_viewer_harmonica."
F = "caracole.viewer.harpfit."
P = "caracole.viewer.harptab_page."
SEED = viewer_corpus.SEED + 900
DIGEST = 8
PART = 16
WHOLE_LINES = 300
RECORD_ROWS = 8  # a record sheet's lines: a tab's first sung rows
WORDS_EVERY = 6  # of the tabs' sung texts, one in this many
TAB_DIRS = ("tabs", "legends", "spellings", "layout")
TAB_PAGES = ("tab_25_piano-man.html", "tab_29910_knockin-on-heavens-door.html", "tab_89_la-bamba.html")
SUNG = 6  # the generated tabs sung over a sheet of their own

# Keys the record sheets are charted in, each with chords its sheet plays (one now and then no chord at all).
KEYS = (("G", ("G", "C", "D", "Em", "Am", "D7", "Bm")), ("Am", ("Am", "Dm", "E7", "G", "C", "F", "E")),
        ("D", ("D", "G", "A", "Bm", "Em", "A7", "F#m")), ("E", ("E", "A", "B7", "C#m", "F#m", "E7")),
        ("Bb", ("Bb", "Eb", "F", "Gm", "Cm", "F7")), ("F#m", ("F#m", "Bm", "C#7", "D", "A", "E")),
        ("C", ("C", "F", "G", "Am", "Dm", "G7", "Em")), ("Em", ("Em", "Am", "B7", "C", "G", "D")))
ODD_CHORDS = ("N.C.", "x2", "Cfoo", "G/B", "D/F#", "Am7", "Cmaj7", "Bm7b5", "Asus4", "E7#9")
# choose's other inputs: the song's key as keys.py found it, and harptabs.com's key chip.
CASES = ((None, None, None), (None, None, "Bb"), ("A minor", "tab", None), ("Bm", "chords", "C"),
         ("E", "audio", None), ("Am", "tab", "G#"), ("C", None, "F#"), ("G", "ug", "A"), ("Dm", "chords", "H"),
         ("nonsense", "tab", "Eb"), (None, None, " D "))
PITCH_NAMES = ("C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B", " G ",
               "\tA\n", "E♭", "F♯", "B♭", "A♯", "", " ", "H", "Cb", "B#", "E#", "Fb", "c", "bb", "Am", "C major",
               "Bb ", "♭", "#", "C♯♯", "Ｃ", "D ", "　E")
WORD_EDGES = ("On a dark des-ert high-way, (background)", "I'm sure you’ve", "rock'n'roll", "don't 'quote' me",
              "a--b -c- d-", "(all (nested) of it) after", "(unclosed tail", "x_y _z_ 1st 2nd", "Über ÉLAN naïve",
              "我们一起 唱歌", "カタカナ・テスト", "  spaced\tout\nlines  ", "", "—dash—", "it’s o’clock", "'", "a'",
              "'a", "a''b", "x-'y", "9-5", "ﬁne ﬂow", "İstanbul", "ΣΊΣΥΦΟΣ", "áb", "١٢٣ ٤٥", "ß-ẞ",
              "end. (x2)", "(x2)", "HEY!-HO!", "co-op's", "a-b-c-d", "word‑nb", "x​y")
PINS: tuple[Any, ...] = (None, "signs", "brackets", "letters", "signs after", "barrett", "legend", "nope",
                          {"as": "letters"}, {"*": "bend"}, {"as": "signs", "(w)": "wah"}, {"x": "draw"})
TITLES = (("Synthetic Song", "Placeholder Band"), ("", ""), ("Rock & Roll <Live> \"Take 2\"", "AC/DC & Friends"),
          ("</script><!-- x", "<!--</script>-->"), ("Canción inventada", "Grupo Ficticio"), ("Alone", ""),
          ("💿 Emoji ♪", "Ünïcødé Ñame"))
TAB_FILES = ("harmonica-1.txt", "harmonica-2.txt", "harmonica-12.txt", "harmonica 3 (x).txt", "口琴-1.txt",
             "a&b\"c'd.txt", "harmonica-1.txt?x=1#y")
URLS = (None, "https://www.harptabs.com/tab/588/hotel-california", "https://www.harptabs.com/", "javascript:alert(1)",
        "https://example.com/tab", "http://www.harptabs.com/tab/1", "https://www.harptabs.com/tab/1?a=1&b=<2>", 3)
BACKS = (None, "sheet.html", "sheet (auto).html", "a b&c?d.html", "版本.html", "")
FACTS: tuple[dict[str, Any], ...] = (
    {}, {"difficulty": "Beginner", "views": 224000, "rating": 3.3}, {"views": 1_100_000, "rating": None},
    {"views": 400}, {"views": "lots", "rating": True}, {"difficulty": "  Expert ", "views": 23000},
    {"views": 999}, {"views": 1000}, {"views": 1499}, {"views": 1500}, {"views": 2500}, {"views": 999_499},
    {"views": 999_500}, {"views": 1_250_000}, {"views": 1_050_000}, {"views": 10**12}, {"views": 0}, {"views": -5},
    {"views": True}, {"views": 1234.0}, {"rating": 5}, {"rating": 4.25}, {"rating": 4.35}, {"rating": 0.05},
    {"rating": 0.04}, {"rating": 0}, {"rating": -1.5}, {"rating": "4.5"}, {"rating": 10**20},
    {"difficulty": "", "views": 7}, {"difficulty": 3}, {"difficulty": "<b>Hard</b> & \"x\""},
    {"title": "hotel california", "artist": "The Eagles", "key": None, "difficulty": "Intermediate",
     "views": 12345, "rating": 2.95})


def constants() -> dict[str, Any]:
    return {
        "harpfit": {"MIN_NOTES": harpfit.MIN_NOTES, "LINE_MATCH": harpfit.LINE_MATCH, "WHY": list(harpfit.WHY),
                    "_PITCH": harpfit._PITCH},
        "harptab_page": {
            "BPM": harptab_page.BPM, "SITE": harptab_page.SITE, "_SAID": harptab_page._SAID,
            "_BRACKETS": {k: list(v) for k, v in harptab_page._BRACKETS.items()}, "_JOIN": harptab_page._JOIN,
            "_SOURCE": harptab_page._SOURCE, "_PLAY_ICON": harptab_page._PLAY_ICON,
            "_NO_SHEET": harptab_page._NO_SHEET, "_NO_KEY": harptab_page._NO_KEY, "_BAR": harptab_page._BAR,
            "_BAR_RAW": harptab_page._BAR_RAW, "_PILL": harptab_page._PILL},
    }


def test_harmonica_page_json_is_the_modules_constants():
    check(viewer_corpus.VIEWER_DATA / "harmonica_page.json", viewer_corpus.data_json(constants()))


def test_the_data_reads_back_as_the_modules_hold_it():
    data = json.loads(viewer_corpus.data_json(constants()))
    assert tuple(data["harpfit"]["WHY"]) == harpfit.WHY and data["harpfit"]["_PITCH"] == harpfit._PITCH
    assert tuple(data["harptab_page"]["_SAID"]) == harpfit.WHY
    assert {k: tuple(v) for k, v in data["harptab_page"]["_BRACKETS"].items()} == harptab_page._BRACKETS
    assert data["harptab_page"]["_BAR"].count(harptab_page._PLAY_ICON) == 1


# --- the inputs ---------------------------------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, separators=(",", ":")))[:DIGEST]


def _fixture_tabs() -> list[tuple[str, dict[str, str]]]:
    out = []
    for folder in TAB_DIRS:
        for path in sorted((FIXTURES / "harptabs" / folder).glob("*.txt")):
            out.append((f"{folder}/{path.stem}", fixture_ref(path)))
    return out


def _sung_line(rng: random.Random, words: list[str], chords: list[str], on: int) -> tuple[str, str, str]:
    """A row of holes over ``words`` (a hole over each word's start, seeded) and its sheet's line: each word under a
    chord of ``chords`` in turn, the hole a tone of it on the ``on`` harp, now and then not; signs' marks."""
    lyric = " ".join(words)
    starts = [i for i, ch in enumerate(lyric) if ch != " " and (i == 0 or lyric[i - 1] == " ")]
    holes: list[tuple[int, str]] = []
    cells: list[str] = []
    sheet = []
    for n, (at, word) in enumerate(zip(starts, words)):
        chord = chords[(n // 2) % len(chords)]
        tones = sorted(harpfit.parse_chord(chord, strict=False).pitch_classes)
        playing = [(h, b, bend) for h in range(1, 11) for b in ("blow", "draw") for bend in (0, 1)
                   if (note := harp.hole_note(0, h, b, bend)) is not None
                   and ((note + on) % 12 in tones) != (rng.random() < 0.15)]
        hole, breath, bend = rng.choice(playing)
        cells.append(("-" if breath == "draw" else "") + str(hole) + "'" * bend)
        holes.append((at, cells[-1]))
        sheet.append((f"[{chord}]" if n % 2 == 0 else "") + word)
    line = [" "] * (len(lyric) + 6)
    end = 0
    for at, cell in holes:
        at = max(at, end)
        line[at:at + len(cell)] = cell
        end = at + len(cell) + 1
    return "".join(line).rstrip(), lyric, " ".join(sheet)


@functools.cache
def _generated() -> tuple[tuple[str, str], ...]:
    """The tabs and sheets that are no fixture, by name, in order (the module's docstring)."""
    rng = random.Random(SEED)
    out: list[tuple[str, str]] = []
    vocabulary = [w for w in viewer_corpus._LATIN_WORDS if w.isascii()]
    for n in range(SUNG):
        key, chords = KEYS[n % len(KEYS)]
        on = rng.randrange(12)
        rows, lines = [], []
        for _ in range(rng.randint(3, 6)):
            words = [rng.choice(vocabulary) for _ in range(rng.randint(4, 8))]
            holes, lyric, sheet_line = _sung_line(rng, words, list(chords), on)
            rows += [holes, lyric, ""]
            lines.append(sheet_line)
        before = rng.choice(("", "Tabbed by a placeholder\n\n", f"I use a {harp.HARP_KEYS[rng.randrange(12)]} harp\n\n"))
        capo = rng.choice((0, 0, 2))
        out.append((f"sung:{n}", before + "\n".join(rows)))
        out.append((f"sung-sheet:{n}", "{title: Sung %d}\n{artist: Placeholder Band}\n{key: %s}\n" % (n, key)
                    + (f"{{capo: {capo}}}\n" if capo else "") + "{comment: Verse}\n" + "\n".join(lines) + "\n"))
    for name in TAB_PAGES:
        found = harptabs.parse_tab_page((FIXTURES / "harptabs" / name).read_text(encoding="utf-8"))
        out.append((f"page:{name}", found.body))
    out.append(("arrows", "ARMONICA C\n↑3 ↓3 ↑4 ↓4 ↑5\n↓5 ↑6 ↓6 ↑6\n"))
    out.append(("tiny", "Verse\n4  -4  5  -5  6  6\nSing it la la la now\n\n6 -6 7 -7\nand so on now\n"))
    out.append(("thin", "(3)tue (3)te (3)te\n"))
    out.append(("chromatic", "4 -4 5 -5 6\nla la la la la\n\n6 -6 7 -7 8\nla la la la la\n"))
    for n in range(3):
        words = [" ".join(rng.choice(vocabulary) for _ in range(rng.randint(3, 7))) for _ in range(rng.randint(2, 5))]
        key, chords = KEYS[(n + 3) % len(KEYS)]
        out.append((f"other:{n}", "{title: Other}\n{artist: Placeholder Band}\n" + f"{{key: {key}}}\n"
                    + "".join(f"[{rng.choice(chords)}]{line} [{rng.choice(chords)}]and on\n" for line in words)))
    out.append(("keyless", "{title: Keyless}\n{artist: Placeholder Band}\n[N.C.]words with no key [x2]at all\n"))
    out.append(("bare", "{title: Bare}\n{artist: Placeholder Band}\n{key: C}\nwords with no chords at all\n"))
    out.append(("chinese", "{title: 斑马}\n{artist: 宋冬野}\n{key: G}\n[G]我们一起 [C]唱歌\n[D]你的愛 [G]過去\n"))
    return tuple(out)


@functools.cache
def _record_sheets() -> tuple[tuple[str, str], ...]:
    """A sheet charting each fixture tab's own sung rows (none for a tab with none), the module's docstring."""
    rng = random.Random(SEED + 1)
    out: list[tuple[str, str]] = []
    for name, ref in _fixture_tabs():
        tab = parse(fixture_bytes(ref).decode("utf-8"))
        sung = [r.lyric for r in tab.rows() if r.lyric is not None and r.lyric.strip()][:RECORD_ROWS]
        if not sung:
            continue
        key, chords = KEYS[rng.randrange(len(KEYS))]
        lines = []
        for lyric in sung:
            words = lyric.split()
            for i, w in enumerate(words):
                roll = rng.random()
                if roll < 0.08 and len(w) > 4:
                    words[i] = w[:2] + "-" + w[2:]
                elif roll < 0.12:
                    words[i] = w.upper()
                elif roll < 0.15:
                    words[i] = "(oh) " + w
            placed = []
            for i, w in enumerate(words):
                if i == 0 or rng.random() < 0.3:
                    chord = rng.choice(ODD_CHORDS) if rng.random() < 0.05 else rng.choice(chords)
                    placed.append(f"[{chord}]{w}")
                else:
                    placed.append(w)
            lines.append(" ".join(placed))
        head = "{title: %s}\n{artist: Placeholder Band}\n" % name.rpartition("/")[2]
        if rng.random() < 0.8:
            head += f"{{key: {key}}}\n"
        if rng.random() < 0.25:
            head += f"{{capo: {rng.choice((1, 2, 3, 5))}}}\n"
        out.append((f"record:{name}", head + "{comment: Verse}\n" + "\n".join(lines) + "\n"))
    return tuple(out)


@functools.cache
def texts() -> dict[str, str]:
    return dict(_generated() + _record_sheets())


def text_of(ref: dict[str, str]) -> str:
    return fixture_bytes(ref).decode("utf-8") if "fixture" in ref else texts()[ref["named"]]


def named(name: str) -> dict[str, str]:
    assert name in texts(), name
    return {"named": name}


def _page_facts() -> dict[str, tuple[str | None, str | None, dict[str, Any]]]:
    """Each tab page's chips: its key, its harp, its version's raw."""
    out = {}
    for name in TAB_PAGES:
        found = harptabs.parse_tab_page((FIXTURES / "harptabs" / name).read_text(encoding="utf-8"),
                                        f"https://www.harptabs.com/tab/{name}")
        out[f"page:{name}"] = (found.key, found.harp, found.raw())
    return out


def tabs() -> list[tuple[str, dict[str, str], str | None]]:
    """Every tab the records read: (name, text, the page's chip)."""
    out: list[tuple[str, dict[str, str], str | None]] = [(name, ref, None) for name, ref in _fixture_tabs()]
    chips = _page_facts()
    for name, _ in _generated():
        if name.startswith("sung:") or name in ("arrows", "thin", "tiny"):
            out.append((name, named(name), None))
        elif name.startswith("page:"):
            out.append((name, named(name), chips[name][1]))
        elif name == "chromatic":
            out += [(name, named(name), "Chromatic"), (name, named(name), "Diatonic")]
    return out


def texts_records() -> list[dict[str, Any]]:
    return [{"fn": HELPER + "text", "args": [name], "out": text} for name, text in texts().items()]


def test_the_texts_are_the_generators():
    check(viewer_corpus.VIEWER_VECTORS / "harpfit_texts.jsonl",
          jsonl(texts_records(), corpus="viewer/harpfit_texts", made_by=MADE_BY))


# --- harpfit --------------------------------------------------------------------------------------------------


def _lines_json(cho: str) -> Any:
    lines = [[[w, None if chord is None else sorted(chord)] for w, chord in line] for line in harpfit._sheet_lines(cho)]
    if len(json.dumps(lines, ensure_ascii=False, separators=(",", ":"))) <= WHOLE_LINES:
        return lines
    return {"digest": short(lines), "lines": len(lines)}


def _fits(fits) -> list[list[Any]]:
    return [[f.harp, f.share, f.notes] for f in fits]


def _choice(chosen: harpfit.Choice, fitted: list[list[Any]]) -> list[Any]:
    assert not chosen.fits or _fits(chosen.fits) == fitted
    return [chosen.harp, chosen.why, bool(chosen.fits), chosen.named, chosen.page, chosen.tonic, chosen.tabs_harp]


def _sheet_for(name: str) -> str | None:
    if name.startswith("sung:"):
        return "sung-sheet:" + name.partition(":")[2]
    if f"record:{name}" in texts():
        return f"record:{name}"
    return None


def _words_texts() -> list[str]:
    found: dict[str, None] = {}
    for name, ref, chip in tabs():
        for row in parse(text_of(ref), harp=chip).rows():
            found.update(dict.fromkeys(text for _, text in row.parts))
    return list(dict.fromkeys([*WORD_EDGES, *(t for n, t in enumerate(found) if n % WORDS_EVERY == 0)]))


def harpfit_records() -> list[dict[str, Any]]:
    rng = random.Random(SEED + 2)
    records: list[dict[str, Any]] = [
        {"fn": F + "pitch", "args": [list(PITCH_NAMES) + [None]], "out": [harpfit.pitch(n) for n in PITCH_NAMES]
         + [harpfit.pitch(None)]}]
    batch = _words_texts()
    for start in range(0, len(batch), 80):
        part = batch[start:start + 80]
        records.append({"fn": F + "words", "args": [part], "out": [harpfit.words(t) for t in part]})
    for name in texts():
        if name.startswith(("record:", "sung-sheet:", "other:")) or name in ("keyless", "bare", "chinese"):
            records.append({"fn": F + "_sheet_lines", "args": [named(name)], "out": _lines_json(texts()[name])})
    others = [n for n in texts() if n.startswith("other:")] + ["keyless", "bare", "chinese"]
    for name, ref, chip in tabs():
        tab = parse(text_of(ref), harp=chip)
        # its own sheet, else one that sings other words or none
        sheet = _sheet_for(name) or rng.choice((None, rng.choice(others)))
        cho = texts()[sheet] if sheet else None
        fitted = _fits(harpfit.record_fit(tab, cho)) if cho else []
        page_key = _page_facts().get(name, (None,))[0]
        cases = rng.sample(CASES, 3) + ([(None, None, page_key)] if page_key else [])
        choices = [_choice(harpfit.choose(tab, cho=cho, key=k, key_source=s, page_key=p), fitted)
                   for k, s, p in cases]
        records.append({"fn": HELPER + "fit_of", "args": [[ref, chip], sheet and named(sheet), [list(c) for c in cases]],
                        "out": {"record_fit": fitted, "choices": choices}})
    records += tab_harps_records(rng)
    return records


def _tab_harps(given: list[list[Any]], cho: str, key: str | None, key_source: str | None, folder: Path) -> Any:
    """render._tab_harps over ``given`` tabs, each written into ``folder`` as a kept file would be."""
    harmonica: dict[str, Any] = {}
    files: dict[str, Any] = {}
    listed = []
    for name, ref, chip, page_key, pin in given:
        if ref is not None:
            (folder / name).write_text(text_of(ref), encoding="utf-8")
            files[name] = SimpleNamespace(path=name)
        if pin is not None:
            harmonica[name] = pin
        listed.append(SimpleNamespace(name=name, harp=chip, key=page_key))
    song = SimpleNamespace(key="placeholder band/song", display="Placeholder Band - Song")
    return render._tab_harps(SimpleNamespace(library_dir=folder), SimpleNamespace(harmonica={song.key: harmonica}),
                             song, listed, files, cho, (key, key_source))


def tab_harps_records(rng: random.Random) -> list[dict[str, Any]]:
    import tempfile

    every = tabs()
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for n in range(8):
            picked = rng.sample(every, 3)
            given: list[list[Any]] = []
            for k, (name, ref, chip) in enumerate(picked):
                given.append([f"harmonica-{k + 1}.txt", ref if k or n % 4 else None, chip,
                              rng.choice((None, "C", "Bb", "A")), rng.choice(PINS)])
            sheet = _sheet_for(picked[0][0]) or rng.choice(("other:0", "chinese", "keyless"))
            key, source, _ = rng.choice(CASES)
            folder = Path(tmp) / str(n)
            folder.mkdir()
            out.append({"fn": "caracole.render._tab_harps", "args": [given, named(sheet), key, source],
                        "out": _tab_harps(given, texts()[sheet], key, source, folder)})
    return out


def test_harpfit_is_harpfit_pys():
    check(viewer_corpus.VIEWER_VECTORS / "harpfit.jsonl",
          jsonl(harpfit_records(), corpus="viewer/harpfit", made_by=MADE_BY))


def test_the_fits_cover_every_choice():
    whys = {c[1] for r in harpfit_records() if r["fn"] == HELPER + "fit_of" for c in r["out"]["choices"]}
    assert whys == set(harpfit.WHY)
    harps = [r["out"] for r in harpfit_records() if r["fn"] == "caracole.render._tab_harps"]
    assert any(harps) and not all(harps)


# --- the page -------------------------------------------------------------------------------------------------


def _choices() -> list[list[Any]]:
    fits = [[2, 1.0, 24], [5, 0.3333333333333333, 24], [9, 0.25, 24]]
    return [[0, "usual", [], None, None, None], [9, "tab", [], 9, 4, None], [10, "page", [], None, 10, 7],
            [7, "song", [], None, None, 7], [2, "record", fits, None, 0, 11], [2, "record", fits, 2, 0, 11],
            [2, "record", fits, 9, None, None], [2, "record", fits[:1], 4, None, 2], [4, "record", fits, 4, 1, 5],
            [1, "tab", [], 1, None, 0], [3, "usual", [], None, None, 6], [8, "record", [[8, 0.625, 40],
                                                                                    [3, 0.005, 40]], None, None, 3]]


def _a_choice(row: list[Any]) -> harpfit.Choice:
    harp_, why, fits, named_, page_, tonic = row
    return harpfit.Choice(harp_, why, tuple(harpfit.Fit(*f) for f in fits), named_, page_, tonic)


def parts_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [{"fn": P + "_a", "args": [list(harp.HARP_KEYS)],
                                      "out": [harptab_page._a(n) for n in harp.HARP_KEYS]}]
    choices = _choices()
    records.append({"fn": P + "_harp_lines", "args": [choices],
                    "out": [harptab_page._harp_lines(_a_choice(c)) for c in choices]})
    footers = [[f, u, n % 2 == 0, n % 3 == 0] for n, (f, u) in enumerate(zip(TAB_FILES + TAB_FILES[:1], URLS))]
    records.append({"fn": P + "_footer", "args": [footers],
                    "out": [harptab_page._footer(f, u, placed=p, change=c) for f, u, p, c in footers]})
    every = [dict(f) for f in FACTS]
    for n, (ref, chip, pin) in enumerate(((fixture_ref("harptabs/tabs/588_hotel-california.txt"), None, None),
                           (fixture_ref("harptabs/tabs/124_heart-of-gold.txt"), None, None),
                           (fixture_ref("harptabs/tabs/588_hotel-california.txt"), None, "signs"),
                           (fixture_ref("harptabs/legends/693_spokey-dokey.txt"), None, None),
                           (fixture_ref("harptabs/tabs/1882_juke.txt"), "Diatonic", {"as": "letters"}))):
        tab = parse(text_of(ref), harp=chip, notation=harptab_page._pinned(pin, text_of(ref)))
        facts = every if n == 0 else every[:3]
        said = [harptab_page._read_as(tab, f) for f in facts]
        records.append({"fn": P + "_read_as", "args": [[ref, chip], pin, facts],
                        "out": [html if k < 2 else _sha(html)[:PART] for k, html in enumerate(said)]})
    rng = random.Random(SEED + 4)
    sheets = [n for n in texts() if n.startswith(("record:", "sung-sheet:", "other:"))]
    for n, sheet in enumerate([None, "keyless", "bare", "chinese"] + rng.sample(sheets, 10)):
        choice = choices[n % len(choices)]
        key, source, _ = rng.choice(CASES)
        found = harptab_page._overlay_data(_a_choice(choice), sheet and texts()[sheet], key, source)
        records.append({"fn": P + "_overlay_data", "args": [choice, sheet and named(sheet), key, source],
                        "out": {k: _members(v) for k, v in found.items()}})
    return records


def _cut(html: str, start: str, end: str, at: int = 0) -> tuple[str, int]:
    a = html.index(start, at)
    b = html.index(end, a) + len(end)
    return html[a:b], b


def _members(value: dict[str, Any] | None) -> str:
    return "-" if value is None else " ".join(f"{k}={short(v)}" for k, v in value.items())


_DATA = '<script type="application/json" id="harp-data">'
_NAMES = '<script type="application/json" id="song-names">'


def page_out(html: str) -> dict[str, Any]:
    """A page's record (the module's docstring)."""
    body = html.index("<body>\n")
    head, at = _cut(html, '<header class="head">', "</header>\n", body)
    article, at = _cut(html, '<article class="sheet', "</article>\n", at)
    foot, at = _cut(html, '<footer class="foot">', "</footer>\n", at)
    block = html.index(_DATA, at)
    data = json.loads(html[block + len(_DATA):html.index("</script>", block)])
    names = None
    if _NAMES in html:
        n = html.index(_NAMES) + len(_NAMES)
        names = _sha(html[n:html.index("</script>", n)])[:PART]
    return {"sha256": _sha(html), "size": len(html.encode("utf-8")), "head": _sha(head)[:PART],
            "article": _sha(article)[:PART], "foot": _sha(foot)[:PART], "bar": _sha(html[at:block])[:PART],
            "data": _members(data), "overlay": _members(data["overlay"]), "names": names}


DEFAULTS: dict[str, Any] = {"artist": "", "url": None, "page_key": None, "harp": None, "pin": None, "facts": None,
                            "cho": None, "key": None, "key_source": None, "back": None}


@functools.cache
def _pages() -> tuple[tuple[dict[str, str], dict[str, Any]], ...]:
    """Every page's (text, kw), kw's ``cho`` a text's name: each tab once with seeded options, then the edges."""
    rng = random.Random(SEED + 3)
    others = [n for n in texts() if n.startswith("other:")] + ["keyless", "bare"]
    chips = _page_facts()
    out = []
    for name, ref, chip in tabs():
        title, artist = rng.choice(TITLES)
        kw: dict[str, Any] = {"title": title, "artist": artist, "tab_file": rng.choice(TAB_FILES)}
        if name in chips:
            key, chip_, raw = chips[name]
            kw |= {"url": f"https://www.harptabs.com/tab/{name}", "page_key": key, "harp": chip_, "facts": raw}
        else:
            kw |= {"url": rng.choice(URLS[:6]), "page_key": rng.choice((None, None, "C", "Bb", "E", "F#")),
                   "harp": chip, "facts": rng.choice(FACTS[:6]) or None}
        kw["pin"] = rng.choice(PINS) if rng.random() < 0.3 else None
        sheet = _sheet_for(name) if rng.random() < 0.7 else rng.choice(others + [None])
        if sheet is not None:
            kw["cho"] = sheet
            kw["key"], kw["key_source"], _ = rng.choice(CASES)
        kw["back"] = rng.choice(BACKS)
        out.append((ref, kw))
    out.append((named("sung:0"), {"title": "斑马", "artist": "宋冬野", "tab_file": "harmonica-1.txt",
                                  "cho": "chinese", "back": "sheet.html"}))
    out.append((named("sung:1"), {"title": "愛情故事", "artist": "", "tab_file": "harmonica-1.txt", "cho": "chinese"}))
    out.append((named("thin"), {"title": "Thin", "tab_file": "harmonica-1.txt", "cho": "sung-sheet:0",
                                "page_key": "E"}))
    out.append((named("arrows"), {"title": "Arrows", "tab_file": "harmonica-1.txt", "page_key": "C",
                                  "facts": FACTS[1]}))
    return tuple((ref, {k: v for k, v in kw.items() if v != DEFAULTS.get(k, object())}) for ref, kw in out)


def _call(ref: dict[str, str], kw: dict[str, Any]) -> str:
    """build_harmonica_viewer as the record holds it: an object's members sorted (helpers.corpus), so the page's
    ``facts`` reads them in that order on both sides, and ``cho`` the text it names."""
    given = json.loads(json.dumps(kw, sort_keys=True))
    if "cho" in given:
        given["cho"] = texts()[given["cho"]]
    return harptab_page.build_harmonica_viewer(text_of(ref), **given)


def page_records() -> list[dict[str, Any]]:
    out = parts_records()
    for ref, kw in _pages():
        given = dict(kw)
        if "cho" in given:
            given["cho"] = named(given["cho"])
        out.append({"fn": P + "build_harmonica_viewer", "args": [ref], "kw": given, "out": page_out(_call(ref, kw))})
    return out


def test_every_page_is_harptab_page_pys():
    check(viewer_corpus.VIEWER_VECTORS / "harmonica_pages.jsonl",
          jsonl(page_records(), corpus="viewer/harmonica_pages", made_by=MADE_BY))


def test_the_pages_cover_every_option():
    pages = _pages()
    used = {k for _, kw in pages for k in kw}
    assert used >= set(DEFAULTS) | {"title", "tab_file"}, set(DEFAULTS) - used
    built = [(_call(ref, kw), kw) for ref, kw in pages]
    assert any('<pre class="tab">' in html for html, _ in built)  # a tab shown as written
    assert any('<pre class="tab asw">' in html for html, _ in built)  # a row shown as written
    assert any(_NAMES in html for html, _ in built)
    assert any('id="reading-src"' in html for html, _ in built) and any('id="reading-foot"' in html for html, _ in built)
    assert any('class="why"' in html for html, _ in built)
    assert any('<details class="pre">' in html for html, _ in built) and any('<div class="pre">' in html
                                                                            for html, _ in built)
    for kind in ("tab-legend", "l words", "note", "gap", "sec chorus", "jn", "tw", "fx", "hold", '"u"'):
        assert any(kind in html for html, _ in built), kind
    whys = set()
    for ref, kw in pages:
        chip = kw.get("harp")
        tab = parse(text_of(ref), harp=chip, notation=harptab_page._pinned(kw.get("pin"), text_of(ref)))
        cho = texts()[kw["cho"]] if "cho" in kw else None
        whys.add(harpfit.choose(tab, cho=cho, key=kw.get("key"), key_source=kw.get("key_source"),
                                page_key=kw.get("page_key")).why)
    assert whys == set(harpfit.WHY)


# --- a page kept whole ----------------------------------------------------------------------------------------

WHOLE = (named("tiny"), {"title": "Whole Page", "artist": "The Placeholders", "tab_file": "harmonica-1.txt",
                         "page_key": "C"})


def pieces(html: str) -> list[Any]:
    """``html`` as its texts and the viewer/ files it inlines whole (``{"asset": name}``), in order."""
    style, _ = page._assets()
    own_style, script = harptab_page._own_assets()
    assets = [("viewer.css", style), ("harptab.css", own_style), ("strum.js", page._sound()),
              ("overlay.js", page._overlay()), ("harptab.js", script)]
    out: list[Any] = []
    at = 0
    for name, text in assets:
        found = html.index(text, at)
        out += [html[at:found], {"asset": name}]
        at = found + len(text)
    out.append(html[at:])
    assert "".join(p if isinstance(p, str) else dict(assets)[p["asset"]] for p in out) == html
    return out


def whole_records() -> list[dict[str, Any]]:
    ref, kw = WHOLE
    return [{"fn": P + "build_harmonica_viewer", "args": [ref], "kw": kw, "pieces": pieces(_call(ref, kw))}]


def test_a_small_page_is_kept_whole():
    check(viewer_corpus.VIEWER_VECTORS / "harmonica_pages_whole.jsonl",
          jsonl(whole_records(), corpus="viewer/harmonica_pages_whole", made_by=MADE_BY))


def test_the_records_name_only_texts_they_hold():
    for record in harpfit_records() + page_records():
        for found in re.findall(r'\{"named":"([^"]*)"\}', json.dumps(record, ensure_ascii=False,
                                                                       separators=(",", ":"))):
            assert found in texts()
