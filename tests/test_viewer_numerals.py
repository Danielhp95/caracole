"""The sheet viewer's chord names as Roman numerals (viewer/harmony_tables.py, page.py's data; viewer.js, viewer.css).

"Chord names" in the settings, a segmented control: Chords · + Numerals · Numerals (``nm`` in the address: absent,
``both``, ``numerals``). page.py hands the page harmony.py's answers as tables per mode; the script only looks
them up. The numerals sit after the chord names, or in their place, coloured by family (home, away, pull) unless
the colours are off, a chord from outside the key underlined; a tap (touch) or the mouse over one shows its line,
which names the key it is read in, and opens the chord's card, which names its numeral too. The browser tests open
a viewer in a Chromium of their own (helpers/viewer_pages.py).
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

import pytest

from caracole.viewer import build_viewer, harmony
from caracole.viewer.harmony_tables import SHIFTS, fill, page_name, pitch_class, shifted
from caracole.viewer.theory import MODES, Key, map_chord, parse_chord, spelling

from helpers.browser import in_chromium
from helpers.targets import small_targets
from helpers.viewer_pages import tap_at, viewer as open_viewer, written

IN_C = ("{title: In C}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n"
        "[C]Made up [G]words to [Am]sing a[F]long\n[C]made up [G]words to [Am]sing a[F]long\n\n"
        "{comment: Bridge}\n[D]Five [G]six [D]seven [C]eight\n[Bb]Borrowed [F]from the [C]minor\n")
IN_A_MINOR = ("{title: In A minor}\n{artist: Synthetic}\n{key: Am}\n{comment: Verse}\n"
              "[Am]Down the [G]stairs we [F]go and [E7]on\n[Am]down the [G]stairs we [F]go and [E7]on\n")
# Amazing Grace's chords, made up: D7 is V7, going home; G7 is V7/IV, going to C, with an F from outside the key.
IN_G = ("{title: In G}\n{artist: Synthetic}\n{key: G}\n{comment: Verse}\n"
        "[G]Made up [G7]words to [C]sing a[G]long\n[G]made up [Em]words to [D7]sing a[G]long\n")
NO_KEY = "{title: Riffs}\n{artist: Synthetic}\n{comment: Verse}\n[N.C.]Made up [Xq]words\n"
LONG = "{title: Long}\n{artist: Synthetic}\n{key: G}\n" + "".join(
    f"{{comment: Verse {n}}}\n[G]Synthetic line [D]number {n} [Em]made up to [C]scroll by\n[G/B]and [Am]on it [F]goes\n\n"
    for n in range(40))
PHONE = {"width": 390, "height": 844, "mobile": True}
DESKTOP = {"width": 1280, "height": 800, "mobile": False}


def data_of(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S)
    assert found, "no song data"
    return json.loads(found.group(1))


def text_on(text, key: Key, s: int) -> str:
    """A text of the tables (harmony_tables' docstring) on the transposition ``s``, as viewer.js reads it."""
    if isinstance(text, str):
        return text
    if isinstance(text, dict):
        return text["by"][s]
    return fill(text, spelling(Key((key.tonic + s) % 12, key.mode)), s)


def chords_of(cho: str) -> list:
    from caracole.viewer.sheet import parse_sheet

    return [parse_chord(name, strict=False) for name in parse_sheet(cho).chords]


# --- the tables -------------------------------------------------------------------------------------


def test_c_majors_chords_are_numbered_against_c():
    data = data_of(build_viewer(IN_C))
    assert [n[0] for n in data["numerals"]["ionian"][:6]] == ["I", "V", "vi", "IV", "V/V", "♭VII"]
    assert data["families"]["ionian"][:4] == ["home", "pull", "home", "away"]
    assert data["families"]["ionian"][5] is None and data["relations"]["ionian"][5] == "borrowed"
    assert data["numerals"]["ionian"][4] == ["V/V", "", "V", "", "", None, "V"]  # the parts of Numeral


def test_a_minors_chords_are_numbered_against_a_minors_major_scale():
    data = data_of(build_viewer(IN_A_MINOR))
    assert data["key"]["mode"] == "aeolian"
    assert [n[0] for n in data["numerals"]["aeolian"]] == ["i", "♭VII", "♭VI", "V7"]


def test_every_mode_has_its_own_table_of_the_chords_mapped_there():
    data = data_of(build_viewer(IN_C))
    chords = chords_of(IN_C)
    for mode in MODES:
        key = Key(0, mode)
        mapped = [map_chord(c, Key(0, "ionian"), mode) for c in chords]
        assert [n[0] for n in data["numerals"][mode][:3]] == [harmony.numeral(c, key).text for c in mapped[:3]], mode


def test_a_chord_read_two_ways_on_the_sheet_has_a_reading_for_each_place():
    # D goes to G (V/V), then to C (C Lydian's II): the second place has a reading of its own.
    data = data_of(build_viewer(IN_C))
    numerals = data["numerals"]["ionian"]
    places = data["places"]["ionian"]
    assert numerals[4][0] == "V/V"
    assert len(places) == 1
    (place, reading), = places.items()
    assert int(place) == 10  # the 11th chord on the page: [C][G][Am][F] [C][G][Am][F] [D][G] [D]
    assert numerals[reading][0] == "II"
    assert "Lydian" in text_on(data["explains"]["ionian"][reading], Key(0, "ionian"), 0)


@pytest.mark.parametrize("mode", ["ionian", "aeolian", "dorian"])
def test_each_line_names_the_key_shown_on_every_transposition(mode):
    data = data_of(build_viewer(IN_C))
    for i in range(len(chords_of(IN_C))):
        for s in SHIFTS:
            shown = Key(s % 12, mode)
            words = f"{spelling(shown)[s % 12]} {harmony._mode_word(mode)}"
            line = text_on(data["explains"][mode][i], Key(0, mode), s)
            assert line.startswith(data["numerals"][mode][i][0] + ": ") and words in line, (s, line)


def test_the_lines_are_harmonys_on_every_transposition():
    data = data_of(build_viewer(IN_A_MINOR))
    chords = chords_of(IN_A_MINOR)
    key = Key(9, "aeolian")
    goes = [chords[1], chords[2], chords[3], chords[0]]  # Am G F E7, round again
    for i, chord in enumerate(chords):
        for s in SHIFTS:
            assert text_on(data["explains"]["aeolian"][i], key, s) == harmony.explain(
                shifted(chord, s), Key((9 + s) % 12, "aeolian"), shifted(goes[i], s))


def test_the_data_carries_no_glossary():
    # A numeral's line and its chord's card say what it does; no page explains the notation as a whole any more
    # (the PDF's legend is pdf_text.py's, from harmony.glossary).
    assert "glossary" not in data_of(build_viewer(IN_A_MINOR)) and "numerals" in data_of(build_viewer(IN_A_MINOR))


def test_each_chord_and_each_alternative_has_its_notes_and_its_scale_for_a_solo():
    data = data_of(build_viewer(IN_C))
    assert data["tones"]["C"] == "C E G|R 3 5|0 4 7"
    assert data["tones"]["D"] == "D F# A|R 3 5|2 6 9"  # C, two semitones up
    assert data["tones"]["Bb"] == "Bb D F|R 3 5|10 2 5"
    word = data["scaleWords"][data["solo"]["ionian"][2]]
    assert word == "minor" and data["scales"]["A minor"] == "A minor|A B C D E F G"  # Am in C: A Aeolian
    assert data["scales"]["B minor"] == "B minor|B C# D E F# G A"
    alt = data["alts"]["ionian"][0][0]  # C's first alternative, and its own
    names = spelling(Key(0, "ionian"))
    name = names[alt[0]] + alt[1] + ("" if alt[2] is None else "/" + names[alt[2]])
    assert name in data["tones"] and len(data["altSolo"]["ionian"][0]) == len(data["alts"]["ionian"][0])
    assert data["altNumerals"]["ionian"][0][0][0] in "hapbslo"


def test_tones_carry_each_notes_pitch_class():
    # A third field, for the numeral's tooltip: each note's pitch class, so that the page draws the chord on a circle
    # and a keyboard by looking them up. The card's notes read the first two fields, as before.
    data = data_of(build_viewer(IN_G))
    assert data["tones"]["D7"] == "D F# A C|R 3 5 ♭7|2 6 9 0"
    assert data["tones"]["G7"] == "G B D F|R 3 5 ♭7|7 11 2 5"
    for chord in {c for c in chords_of(IN_G) if c is not None}:
        for s in SHIFTS:
            shown = Key((7 + s) % 12, "ionian")
            notes, steps, pcs = data["tones"][page_name(chord, spelling(shown), s)].split("|")
            found = harmony.chord_tones(shifted(chord, s), shown)
            assert notes.split(" ") == [n for n, _ in found] and steps.split(" ") == [t for _, t in found]
            assert [int(pc) for pc in pcs.split(" ")] == [pitch_class(n) for n, _ in found], (chord, s)
            assert {int(pc) for pc in pcs.split(" ")} == shifted(chord, s).pitch_classes, (chord, s)
    for named in data["tones"].values():  # every chord the page can name, its alternatives too
        notes, _, pcs = named.split("|")
        assert [int(pc) for pc in pcs.split(" ")] == [pitch_class(n) for n in notes.split(" ")], named


def test_a_song_with_no_key_has_no_numerals_but_its_chords_notes():
    data = data_of(build_viewer(NO_KEY))
    assert data["key"] is None
    assert "numerals" not in data and "tones" in data


def test_a_long_songs_tables_grow_with_its_chords_not_its_lines():
    short = data_of(build_viewer(LONG.split("{comment: Verse 2}")[0]))
    long = data_of(build_viewer(LONG))
    for name in ("numerals", "explains", "families", "relations", "altNumerals", "tones", "scales"):
        assert len(json.dumps(long[name])) == len(json.dumps(short[name])), name
    assert len(json.dumps(long["places"])) <= len(json.dumps(short["places"])) + 200



# --- in a browser ------------------------------------------------------------------------------------

# Each chord of the sheet as the page shows it: its text, its numeral and the numeral's classes, its label.
SHEET = """(() => [...document.querySelectorAll('#sheet .c')].map((c) => {
  const nm = c.querySelector('.nm');
  return {text: c.textContent, nm: nm ? nm.textContent : null, cls: nm ? nm.className : '',
          label: c.getAttribute('aria-label')};
}))()"""
TIP = """(() => { const tip = document.getElementById('tip');
  return tip.hidden ? null : {line: tip.querySelector('#tip-line').textContent, key: tip.querySelector('#tip-key').textContent,
    card: !document.getElementById('card').hidden}; })()"""
C_NAMES = ["C", "G", "Am", "F", "C", "G", "Am", "F", "D", "G", "D", "C", "Bb", "F", "C"]
C_NUMERALS = ["I", "V", "vi", "IV", "I", "V", "vi", "IV", "V/V", "V", "II", "I", "♭VII", "IV", "I"]
AM_NAMES = ["Am", "G", "F", "E7"] * 2
AM_NUMERALS = ["i", "♭VII", "♭VI", "V7"] * 2


def luminance(colour: str) -> float:
    def channel(v: float) -> float:
        v = v / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (float(v) for v in re.findall(r"[\d.]+", colour)[:3])
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def middle(b, selector: str, n: int = 0) -> list[float]:
    """The middle of the ``n``-th element ``selector`` finds, scrolled into the middle of the screen."""
    found = b.js(f"""(() => {{ const el = document.querySelectorAll({json.dumps(selector)})[{n}];
      if (!el) return null; el.scrollIntoView({{block: 'center'}}); const r = el.getBoundingClientRect();
      return [r.left + r.width / 2, r.top + r.height / 2]; }})()""")
    assert found, selector
    return found


def hover(b, x: float, y: float) -> None:
    b.send("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)


@in_chromium
@pytest.mark.parametrize(("cho", "names", "numerals"), [(IN_C, C_NAMES, C_NUMERALS), (IN_A_MINOR, AM_NAMES, AM_NUMERALS)],
                         ids=["C major", "A minor"])
@pytest.mark.parametrize("display", ["", "both", "numerals"])
def test_every_display_names_the_chords_as_asked(tmp_path, cho, names, numerals, display):
    url = written(tmp_path, cho) + (f"#nm={display}" if display else "")
    with open_viewer(tmp_path, url, **PHONE) as b:
        shown = b.js(SHEET)
        # Each chord stays over its syllable: its column starts where its words do.
        columns = b.js("""[...document.querySelectorAll('#sheet .s')].map((s) =>
          Math.abs(s.firstElementChild.getBoundingClientRect().left - s.lastElementChild.getBoundingClientRect().left))""")
        wide = b.js("document.documentElement.scrollWidth")
    if not display:
        assert [c["text"] for c in shown] == names and all(c["nm"] is None for c in shown)
    elif display == "both":
        assert [c["text"] for c in shown] == [n + m for n, m in zip(names, numerals, strict=True)]
        assert [c["nm"] for c in shown] == numerals
        assert [c["label"] for c in shown] == [f"{n}, {m}" for n, m in zip(names, numerals, strict=True)]
    else:
        assert [c["text"] for c in shown] == numerals == [c["nm"] for c in shown]
    assert max(columns) <= 1 and wide <= 390


@in_chromium
def test_the_setting_shows_the_numerals_keeps_them_in_the_address_and_colours_them_by_family(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_C), **PHONE) as b:
        b.click("#more")
        chips = b.js("[...document.querySelectorAll('#names > button')].map((c) => [c.getAttribute('aria-label'), "
                     "c.getAttribute('aria-pressed')])")
        b.js("[...document.querySelectorAll('#names > button')][1].click()")
        both = b.js(SHEET)
        address = b.js("location.hash")
        b.js("location.reload()")
        assert b.wait("document.documentElement.dataset.ready === '1' && document.querySelector('#sheet .nm') !== null")
        again = b.js(SHEET)
        b.click("#more")
        b.click("#roles")
        plain = b.js("[document.documentElement.dataset.roles, document.getElementById('roles').getAttribute('aria-pressed')]")
    assert chips == [["Chords", "true"], ["Chords + numerals", "false"], ["Numerals only", "false"]]
    assert "nm=both" in address and [c["nm"] for c in again] == C_NUMERALS
    classes = {c["nm"]: c["cls"] for c in both}
    assert "r-h" in classes["I"] and "r-p" in classes["V"] and "r-a" in classes["IV"] and "r-h" in classes["vi"]
    assert "out" in classes["♭VII"] and "out" in classes["V/V"] and "out" not in classes["I"]
    assert plain == ["off", "false"]


@in_chromium
def test_a_mode_relabels_the_numerals_and_a_transposition_leaves_them(tmp_path):
    html = build_viewer(IN_C)
    dorian = [n[0] for n in data_of(html)["numerals"]["dorian"]]
    with open_viewer(tmp_path, written(tmp_path, IN_C) + "#nm=both", **PHONE) as b:
        b.click("#t-up")
        b.click("#t-up")
        moved = b.js(SHEET)
        b.click("#more")
        b.js("[...document.querySelectorAll('#modes .chip')].find((c) => c.textContent.startsWith('Dorian')).click()")
        modal = b.js(SHEET)
    assert [c["nm"] for c in moved] == C_NUMERALS  # a I is a I in every key
    assert [c["text"][:len(n)] for c, n in zip(moved, ["D", "A", "Bm", "G"])] == ["D", "A", "Bm", "G"]
    assert [c["nm"] for c in modal[:4]] == dorian[:4] != C_NUMERALS[:4]


@in_chromium
def test_the_mouse_over_a_numeral_shows_its_line_in_the_key_shown(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_C) + "#nm=both", **DESKTOP) as b:
        hover(b, *middle(b, "#sheet .nm", 2))  # Am's vi
        assert b.wait("!document.getElementById('tip').hidden")
        first = b.js(TIP)
        hover(b, 5, 5)
        gone = b.wait("document.getElementById('tip').hidden", timeout=3)
        b.click("#t-up")
        b.click("#t-up")
        hover(b, *middle(b, "#sheet .nm", 8))  # D's V/V, now E
        assert b.wait("!document.getElementById('tip').hidden")
        moved = b.js(TIP)
    assert first == {"line": "vi: the 6th chord of C major, minor (lower case)",
                     "key": "In the key of C (from the sheet).", "card": False}
    assert gone
    assert moved["line"] == "V/V: the V of V in D major, major (upper case); leads to A"
    assert moved["key"] == "In the key of D (from the sheet)."


@in_chromium
def test_a_finger_on_a_numeral_shows_its_line_and_on_the_name_the_card(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_C) + "#nm=both", **PHONE) as b:
        x, y = middle(b, "#sheet .nm", 12)  # Bb's ♭VII
        tap_at(b, x, y)
        assert b.wait("!document.getElementById('tip').hidden")
        tipped = b.js(TIP)
        b.press("Escape")
        escaped = b.js(TIP)
        tap_at(b, x, y)
        assert b.wait("!document.getElementById('tip').hidden")
        tap_at(b, 200, 60)  # elsewhere
        elsewhere = b.js(TIP)
        name = b.js("""(() => { const c = document.querySelectorAll('#sheet .c')[12]; const r = document.createRange();
          r.selectNodeContents(c.firstChild); const box = r.getBoundingClientRect();
          return [box.left + box.width / 2, box.top + box.height / 2]; })()""")
        tap_at(b, *name)
        assert b.wait("!document.getElementById('card').hidden")
        card = b.js("[document.getElementById('card-name').textContent, document.getElementById('tip').hidden]")
    assert tipped["line"] == "♭VII: built on the lowered 7th degree of C major, major (upper case); borrowed from C minor"
    assert not tipped["card"] and escaped is None and elsewhere is None
    assert card == ["Bb · ♭VII", True]


@in_chromium
def test_with_numerals_only_a_tap_shows_the_line_and_the_way_to_the_shapes(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_A_MINOR) + "#nm=numerals", **PHONE) as b:
        tap_at(b, *middle(b, "#sheet .c", 3))  # E7's V7
        assert b.wait("!document.getElementById('tip').hidden")
        tipped = b.js(TIP)
        button = b.js("[document.getElementById('tip-card').textContent, document.getElementById('tip-card').getAttribute('aria-label')]")
        targets = b.js(small_targets(".foot *"))
        b.click("#tip-card")
        assert b.wait("!document.getElementById('card').hidden")
        card = b.js("document.getElementById('card-name').textContent")
    assert tipped["line"] == "V7: the 5th chord of A minor, major (upper case) with a 7th (7)"
    assert tipped["key"] == "In the key of Am (from the sheet)."
    assert button == ["Shapes", "E7: shapes"] and targets == [] and card == "E7 · V7"


@in_chromium
def test_a_numeral_is_as_easy_to_tap_as_its_chord(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_C) + "#nm=both", **PHONE) as b:
        x, y = middle(b, "#sheet .nm", 1)
        reach = b.js(f"""[[0, -9], [0, 9], [6, 0], [-1, 0]].map(([dx, dy]) => {{
          const hit = document.elementFromPoint({x} + dx, {y} + dy); return Boolean(hit && hit.closest('.nm')); }})""")
    assert all(reach)


@in_chromium
@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("display", ["both", "numerals"])
def test_the_numerals_colours_read_in_light_and_dark(tmp_path, scheme, display):
    colours = """(() => ({page: getComputedStyle(document.body).backgroundColor,
      numerals: [...document.querySelectorAll('#sheet .nm')].map((n) => [n.textContent, getComputedStyle(n).color])}))()"""
    with open_viewer(tmp_path, written(tmp_path, IN_C) + f"#nm={display}", **PHONE) as b:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        assert b.wait(f"matchMedia('(prefers-color-scheme: {scheme})').matches")
        coloured = b.js(colours)
        b.js("document.getElementById('roles').click()")
        plain = b.js(colours)
    assert (luminance(coloured["page"]) > 0.8) == (scheme == "light")
    for seen in (coloured, plain):
        worst = min(contrast(c, seen["page"]) for _, c in seen["numerals"])
        assert worst >= 4.5, (scheme, seen)
    assert len({c for _, c in coloured["numerals"]}) >= 3  # home, away and pull apart
    assert len({c for _, c in plain["numerals"]}) == 1


@in_chromium
def test_no_sideways_scroll_on_a_phone_with_numerals_beside_a_long_songs_chords(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG) + "#nm=both", **PHONE) as b:
        seen = b.js("[document.documentElement.scrollWidth, document.querySelectorAll('#sheet .nm').length]")
    assert seen[0] <= 390 and seen[1] > 200


@in_chromium
def test_a_song_with_no_key_offers_chords_alone_and_says_why(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, NO_KEY) + "#nm=both", **PHONE) as b:
        b.click("#more")
        seen = b.js("""({chips: [...document.querySelectorAll('#names > button:not(:disabled)')].map((c) => c.textContent),
          hint: document.getElementById('names-hint').textContent, numerals: document.querySelectorAll('#sheet .nm').length})""")
    assert seen == {"chips": ["Chords"], "hint": "caracole can't tell this song's key, so it can't number its chords.",
                    "numerals": 0}


@in_chromium
def test_a_chord_caracole_cant_read_stays_as_written_among_numerals(tmp_path):
    cho = IN_C + "{comment: Break}\n[N.C.]a break [C]then home\n"
    with open_viewer(tmp_path, written(tmp_path, cho) + "#nm=numerals", **PHONE) as b:
        shown = b.js(SHEET)
    assert [c["text"] for c in shown[-2:]] == ["N.C.", "I"] and shown[-2]["nm"] is None


@in_chromium
def test_a_songbook_song_shows_its_numerals_and_its_harmony(tmp_path):
    from caracole.viewer.book import BookSong, build_songbook

    songs = [BookSong("In C", "Synthetic", cho=IN_C, id="aaaa"), BookSong("In A minor", "Synthetic", cho=IN_A_MINOR, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-2", **PHONE) as b:
        b.click("#more")
        b.js("[...document.querySelectorAll('#names > button')][1].click()")
        shown = b.js(SHEET)
        b.click("#harmony-open")
        assert b.wait("!document.getElementById('harmony').hidden")
        progs = b.js("[...document.querySelectorAll('#harmony .prog')].map((p) => [p.querySelector('.prog-nums').textContent, "
                     "p.querySelector('.prog-songs').getAttribute('href')])")
    assert [c["nm"] for c in shown] == AM_NUMERALS
    assert progs == [["i–♭VII–♭VI–V7×2", "../../index.html#prog=V%20i%20%E2%99%ADVII%20%E2%99%ADVI"]]


# --- the tooltip: the chord's notes ----------------------------------------------------------------------

# What the tooltip shows: its head (the chord, its numeral and the numeral's classes, its role), its line and key,
# the view shown, the circle's dots ([pitch class, classes, name, centre]) and the shape joining them (the pitch
# class of each corner, in order), the notes listed ([name, interval, classes]), the line under the picture, and
# whether Hear it shows; None while it is hidden.
SEEN = """(() => { const tip = document.getElementById('tip'); if (tip.hidden) return null;
  const q = (s) => tip.querySelector(s), shows = (el) => Boolean(el) && el.getClientRects().length > 0;
  const nm = q('#tip-nm .nm'), shape = q('#tip-clock polygon');
  const pc = (x, y) => (Math.round(Math.atan2(x - 75, 75 - y) / (Math.PI / 6)) + 12) % 12;
  return {chord: q('#tip-chord').textContent, nm: nm ? nm.textContent : null, nmClass: nm ? nm.className : '',
    role: q('#tip-role').textContent, line: q('#tip-line').textContent, key: q('#tip-key').textContent,
    view: tip.dataset.view, picture: shows(q('#tip-pic')),
    dots: [...tip.querySelectorAll('#tip-clock circle.tc-dot')].map((d) => [Number(d.dataset.pc),
      d.getAttribute('class').split(' ').slice(1).sort(), tip.querySelector(`#tip-clock text[data-pc="${d.dataset.pc}"]`).textContent,
      [Number(d.getAttribute('cx')), Number(d.getAttribute('cy'))]]),
    dashed: [...tip.querySelectorAll('#tip-clock circle.tc-dot')].filter((d) => getComputedStyle(d).strokeDasharray !== 'none')
      .map((d) => Number(d.dataset.pc)),
    shape: shape ? shape.getAttribute('points').trim().split(/\\s+/).map((p) => pc(...p.split(',').map(Number))) : null,
    notes: [...tip.querySelectorAll('#tip-notes li')].filter(shows).map((li) => [li.children[0].textContent,
      li.children[1].textContent, li.className]),
    off: shows(q('#tip-off')) ? q('#tip-off').textContent : null,
    hear: shows(q('#tip-hear')), shapes: [q('#tip-card').textContent, q('#tip-card').getAttribute('aria-label')]};
})()"""
G_MAJOR = {7, 9, 11, 0, 2, 4, 6}


def tip_on(b, n: int) -> dict:
    """The mouse over the ``n``-th numeral of the sheet, from afar: its tooltip, once it shows."""
    hover(b, 5, 5)
    assert b.wait("document.getElementById('tip').hidden", timeout=3)
    hover(b, *middle(b, "#sheet .nm", n))
    assert b.wait("!document.getElementById('tip').hidden")
    return b.js(SEEN)


def lit(seen: dict, mark: str = "on") -> list[int]:
    return sorted(pc for pc, classes, _, _ in seen["dots"] if mark in classes)


@in_chromium
def test_the_tip_heads_with_chord_numeral_and_role(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_G) + "#nm=both", **DESKTOP) as b:
        d7, g7, c, em = (tip_on(b, n) for n in (6, 1, 2, 5))
    assert [d7["chord"], d7["nm"], d7["role"]] == ["D7", "V7", "pull"]
    assert "r-p" in d7["nmClass"] and "out" not in d7["nmClass"]
    assert [g7["chord"], g7["nm"], g7["role"]] == ["G7", "V7/IV", "outside the key"] and "out" in g7["nmClass"]
    assert [c["chord"], c["role"], em["chord"], em["role"]] == ["C", "away", "Em", "home"]
    assert d7["line"] == "V7: the 5th chord of G major, major (upper case) with a 7th (7)"
    assert d7["key"] == "In the key of G (from the sheet)."


@in_chromium
def test_the_circle_rings_the_key_and_joins_the_chords_notes(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_G) + "#nm=both", **DESKTOP) as b:
        d7 = tip_on(b, 6)
        b.click("#t-up")
        b.click("#t-up")
        e7 = tip_on(b, 6)  # two semitones up, in A
    assert d7["picture"]
    assert lit(d7) == [0, 2, 6, 9] and lit(d7, "root") == [2] and lit(d7, "in") == sorted(G_MAJOR) and lit(d7, "off") == []
    assert d7["shape"] == [0, 2, 6, 9]  # joined round the circle, in pitch order
    assert d7["notes"] == [["D", "root", "root"], ["F#", "3", ""], ["A", "5", ""], ["C", "♭7", ""]]
    names = spelling(Key(7, "ionian"))
    assert [name for _, _, name, _ in d7["dots"]] == ["C", names[1], "D", names[3], "E", names[5], "F#", "G", names[8],
                                                     "A", names[10], "B"]
    top = min(d7["dots"], key=lambda d: d[3][1])
    assert top[0] == 0 and top[3][0] == 75  # C at the top, the notes round it as a clock's hours
    assert d7["off"] is None and d7["dashed"] == []
    assert e7["chord"] == "E7" and lit(e7) == [2, 4, 8, 11] and lit(e7, "root") == [4]
    assert lit(e7, "in") == sorted({(pc + 2) % 12 for pc in G_MAJOR}) and e7["shape"] == [2, 4, 8, 11]
    assert [n for n, _, _ in e7["notes"]] == ["E", "G#", "B", "D"]


@in_chromium
def test_an_outside_note_is_marked_and_named(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_G) + "#nm=both", **DESKTOP) as b:
        g7 = tip_on(b, 1)  # V7/IV, going to C
    assert lit(g7) == [2, 5, 7, 11] and lit(g7, "root") == [7] and lit(g7, "off") == [5] and g7["dashed"] == [5]
    assert g7["notes"] == [["G", "root", "root"], ["B", "3", ""], ["D", "5", ""], ["F", "♭7 · off key", "off"]]
    assert g7["off"] == "F isn't in G major (it has F#)."


@in_chromium
def test_hear_it_strums_the_chord_and_hides_when_sound_is_off(tmp_path):
    url = written(tmp_path, IN_G) + "#nm=both"
    with open_viewer(tmp_path, url, **PHONE) as b:
        name = b.js("""(() => { const c = document.querySelectorAll('#sheet .c')[6]; c.scrollIntoView({block: 'center'});
          const r = document.createRange(); r.selectNodeContents(c.firstChild); const box = r.getBoundingClientRect();
          return [box.left + box.width / 2, box.top + box.height / 2]; })()""")
        tap_at(b, *name)  # the chord's name: its card, and its shape strummed
        assert b.wait("document.documentElement.dataset.heard !== undefined")
        card = b.js("document.documentElement.dataset.heard")
        b.press("Escape")
        b.js("delete document.documentElement.dataset.heard")
        tap_at(b, *middle(b, "#sheet .nm", 6))
        assert b.wait("!document.getElementById('tip').hidden")
        assert b.js(SEEN)["hear"]
        tap_at(b, *b.js("""(() => { const r = document.getElementById('tip-hear').getBoundingClientRect();
          return [r.left + r.width / 2, r.top + r.height / 2]; })()"""))
        assert b.wait("document.documentElement.dataset.heard !== undefined")
        heard = b.js("[document.documentElement.dataset.heard, document.getElementById('tip').hidden]")
    assert heard == [card, False]  # the shape its card shows, and the tooltip stays
    with open_viewer(tmp_path, url + "&vol=0", **PHONE) as b:
        tap_at(b, *middle(b, "#sheet .nm", 6))
        assert b.wait("!document.getElementById('tip').hidden")
        silent = b.js(SEEN)
    assert not silent["hear"] and silent["shapes"][0] == "Shapes"


@in_chromium
def test_shapes_opens_the_chords_card(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, IN_G) + "#nm=both", **DESKTOP) as b:
        g7 = tip_on(b, 1)
        b.click("#tip-card")
        assert b.wait("!document.getElementById('card').hidden")
        card = b.js("[document.getElementById('card-name').textContent, document.getElementById('tip').hidden]")
    assert g7["shapes"] == ["Shapes", "G7: shapes"] and card == ["G7 · V7/IV", True]


# Where the tooltip and the numeral it is for are on the screen, the bar's top, and the screen's width.
WHERE = """(() => { const r = (el) => el.getBoundingClientRect(), tip = r(document.getElementById('tip'));
  const nm = r(document.querySelectorAll('#sheet .nm')[%d]);
  return {tip: [tip.left, tip.top, tip.right, tip.bottom], nm: [nm.top, nm.bottom], bar: r(document.getElementById('bar')).top,
    width: document.documentElement.clientWidth, sideways: document.documentElement.scrollWidth > innerWidth}; })()"""


@in_chromium
def test_the_tip_fits_390px_and_flips_above_near_the_bottom(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, LONG) + "#nm=both", **PHONE) as b:
        tap_at(b, *middle(b, "#sheet .nm", 40))
        assert b.wait("!document.getElementById('tip').hidden")
        middle_of = b.js(WHERE % 40)
        small = [t for t in b.js(small_targets("")) if "tip" in t["what"]]
        b.press("Escape")
        low = b.js("""(() => { const nm = document.querySelectorAll('#sheet .nm')[60];
          scrollBy(0, nm.getBoundingClientRect().top - (document.getElementById('bar').getBoundingClientRect().top - 60));
          const r = nm.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()""")
        tap_at(b, *low)
        assert b.wait("!document.getElementById('tip').hidden")
        near_the_foot = b.js(WHERE % 60)
    left, top, right, bottom = middle_of["tip"]
    assert left >= 8 and right <= middle_of["width"] - 8 and not middle_of["sideways"]
    assert top >= middle_of["nm"][1] and bottom <= middle_of["bar"]  # under its numeral, above the bar
    assert small == []
    left, top, right, bottom = near_the_foot["tip"]
    assert bottom <= near_the_foot["nm"][0] and top >= 0  # above its numeral: there's no room under it


@in_chromium
def test_a_chord_chosen_instead_or_one_the_tables_cant_name_still_opens_its_tip(tmp_path):
    html = build_viewer(IN_G)
    data = data_of(html)
    alt = data["alts"]["ionian"][4][0]  # D7's first alternative
    names = spelling(Key(7, "ionian"))
    alt_name = names[alt[0]] + alt[1] + ("" if alt[2] is None else "/" + names[alt[2]])
    swap = f"alt=ionian.4.{alt[0]}.{quote(alt[1], safe='')}.{'' if alt[2] is None else alt[2]}"
    with open_viewer(tmp_path, written(tmp_path, IN_G) + "#nm=both&" + swap, **DESKTOP) as b:
        chosen = tip_on(b, 6)
    assert chosen["chord"] == alt_name and chosen["line"] == f"{chosen['nm']}: the chord you chose in place of D7."
    assert chosen["picture"] and [n for n, _, _ in chosen["notes"]] == data["tones"][alt_name].split("|")[0].split(" ")
    unnamed = tmp_path / "Unnamed" / "Title" / "sheet.html"
    unnamed.parent.mkdir(parents=True)
    tones = json.dumps({"D7": data["tones"]["D7"]}, ensure_ascii=False, separators=(",", ":"))[1:-1]
    assert tones in html
    unnamed.write_text(html.replace(tones, '"D7?":"?"'), encoding="utf-8")
    with open_viewer(tmp_path, unnamed.as_uri() + "#nm=both", **DESKTOP) as b:
        bare = tip_on(b, 6)
    assert [bare["chord"], bare["nm"], bare["role"]] == ["D7", "V7", "pull"]
    assert not bare["picture"] and bare["notes"] == [] and bare["off"] is None
