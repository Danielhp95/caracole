"""harmonica-N.html: a harmonica tab caracole kept from harptabs.com (``harmonica-N.txt``, harptabs_fetch.py) as a
page in the sheet viewer's look, written beside it at render time (render.py) and recorded as the viewers are.

It is sheet.html's kind of page (page.py ``_page``): one self-contained file that loads nothing, its policy allowing
its three scripts (strum.js, overlay.js, then harptab.js) and its two stylesheets (viewer.css, then harptab.css) by
their hashes, and served in a sandbox (``page.viewer_csp``). The tab is read by harptab.py: each hole over the syllable it is blown
on, as a chord sits over its syllable on sheet.html (page.py's ``.s`` and ``.w`` columns: a line wraps between its
words, never parting a hole from its syllable), a blow in the accent colour, a draw in blue with its "−", a bend's
″ in purple, holes together in their brackets; rows played alone, words sung to the same tune and the tabber's notes
as they come. What a row's notation couldn't read is shown in its place as written, muted ("$", "(DV)"); an effect
is a small label on its hole ("wah"), notes run together a ‿ between them, the tab's own legend a block of its own,
and a row read with low confidence (``Row.trusted``) its text as written. The header says how the tab was read: the
symbols it used, as it writes them, and whether its own legend said so or caracole guessed, how surely (harptab.py's
``Reading``). A tab harptab.py can't read (``Tab.readable``) is its text as written, in the page's style, and its
page says so; never an error.

The header names the harp the page starts on and why (harpfit.py ``choose``: with the record, as the tab says,
harptabs.com's key, for the song's key, or the usual C harp), and the position it plays the song in when the song's
sheet has a key. The bar at the foot is the viewer's (Aa, ▶ scrolling by itself with its pill), with the harp a
semitone down or up in place of the transposition (the holes stay: the sound and the notes' names change) and ♪,
Notes, each hole's note on that harp in its place. The song's title and its artist's name follow the sheet viewer's
Chinese characters where its chord sheet is Chinese (page.py ``names_table``: a ``song-names`` block), read from
the browser's storage or ``trad=1`` in the address, with no row of the page's own. A tap on a hole sounds it (strum.js's reed voice); ▶ at a line's
end plays it hole by hole, a hole a beat, lighting each (``caracoleSound.play``). ‹ Chord sheet goes back to the
song's viewer (‹ Library for a song with none), and the tab's text is a tap away at the foot.

From 1200 px, the sheet viewer's overlay (overlay.js) is on the left, Harmonica first and shown: the harps round the
circle of fifths for the song as its chord sheet sounds, the one chosen the page's own harp both ways (a harp tapped
there is the one the page plays; −/+ move the circle's choice), the key on it and each chord's holes; and Guitar, the
sheet's key and chords on the guitar's neck, as the sheet is written. A song with no sheet has no Guitar tab, and
with no key to place a harp in, its Harmonica tab shows the page's harp's notes alone. Its Hide, the bar's button and
``necks=0`` are the viewer's, the choice one for every page.

The script (harptab.js) computes no music theory: the page's data, a JSON block (``harp-data``, each ``<`` escaped),
holds every answer, made here:

- ``harpKeys``: the 12 harps' names, by pitch class (harp.py ``HARP_KEYS``); ``start``, the one the page starts on;
  ``why``: what the header says of a harp, by pitch class ("with the record", "as the tab says", "harptabs.com's
  key", "for the song's key"); ``positions``: the position each harp plays the song in ("4th position, aeolian"),
  or null for a song with no key;
- ``holes``: each harp's every note (harp.py ``hole_tables``: ``blow[i]``, ``draw[i]``, its note then its bends;
  ``over[i]``, its overblow's breath and note), and ``names``, each harp's names of the 12 pitch classes
  (``theory.spelling`` of its major key);
- ``groups``: each group of holes on the page, by its ``data-i``: ``[kind, [[hole, "b" or "d", bend, over], ...]]``,
  and where it has more, a third entry: ``{"fx": ["wah"], "join": 1}``, its effects (which the script draws again on
  it) and whether it runs into the next; ``rows``: each drawn row's groups, by its ▶'s ``data-row``; ``bpm``, a hole a
  beat when a line plays. A tab shown as written has no ``groups`` and no ``rows``. What a row couldn't read is the
  page's text alone, never in the data;
- ``reading``: how the tab was read (harptab.py ``Reading``): the notation's ``name``, its ``source`` ("legend",
  "guessed", "pinned"), its ``q`` and ``margin``, and ``said``, its symbols in words;
- ``overlay``: what the overlay draws (``_overlay``), as overlay.js's ``rail`` takes it: ``guitar``, the Guitar tab
  (the sheet's chords as written, each with its positions, ``instruments.chord_shapes``, and the key's neck), or null
  for a song with no sheet; ``harp``, the Harmonica tab: with the sheet's key, the key as it sounds (``key``,
  ``tonic``, ``names``), harp.py's tables for its mode (``ring``, ``holes``, ``scales``, ``outside``, ``choices``), each
  chord as it sounds with its entries and its notes, and ``tabs``, the page's harp when the record or the tab's words
  chose it; with none, ``key`` null, the line that says so and ``holes``, each harp's notes for the page's harp's.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from html import escape
from typing import Any
from urllib.parse import quote

from caracole.inline import json_block
from caracole.viewer import harmony, harp, harpfit
from caracole.viewer.harmony_tables import page_name
from caracole.viewer.harptab import Gap, Group, Hole, Legend, Prose, Row, Section, Tab, Words, parse
from caracole.viewer.instruments import GUITAR, chord_shapes
from caracole.viewer.page import (
    HERE,
    LIBRARY_PAGE,
    _assets,
    _overlay,
    _page,
    _sound,
    _words,
    artist_line,
    is_chinese,
    names_table,
    shapes_of,
    viewer_key,
    zh_attr,
)
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import Chord, Key, key_name, parse_chord, sounding, spelling

BPM = 132  # a line played: a hole a beat
SITE = "https://www.harptabs.com/"
# What the header and the bar say of the harp the page starts on, by why it was chosen (harpfit.WHY).
_SAID = {"record": "with the record", "tab": "as the tab says", "page": "harptabs.com's key",
         "song": "for the song's key", "usual": ""}
_BRACKETS = {"note": ("", ""), "chord": ("(", ")"), "shake": ("{", "}"), "split": ("[", "]")}
_JOIN = '<span class="jn" aria-hidden="true">‿</span>'  # notes run together: 3*d-3d
_SOURCE = {"legend": "from the tab's own legend", "pinned": "as you set it"}
_PLAY_ICON = ('<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.4v11.2c0 .6.7 1 1.2.6l8.8-5.6a.7.7 0 0 0 '
              '0-1.2L5.7 1.8c-.5-.4-1.2 0-1.2.6z"/></svg>')


@lru_cache(maxsize=1)
def _own_assets() -> tuple[str, str]:
    return (HERE / "harptab.css").read_text(encoding="utf-8"), (HERE / "harptab.js").read_text(encoding="utf-8")


def build_harmonica_viewer(
    text: str,
    *,
    title: str,
    artist: str = "",
    tab_file: str,
    url: str | None = None,
    page_key: str | None = None,
    facts: Mapping[str, Any] | None = None,
    cho: str | None = None,
    key: str | None = None,
    key_source: str | None = None,
    back: str | None = None,
) -> str:
    """The page of the harmonica tab ``text`` (a ``harmonica-N.txt``'s body) of the song ``title`` by ``artist``.

    ``tab_file`` names the text beside the page, which its foot links; ``url`` is the tab's page on harptabs.com,
    ``page_key`` the key it names, ``facts`` what else it says (``difficulty``, ``views``, ``rating``: the version's
    ``raw``, harptabs.HarpTab.raw). ``cho`` is the song's chord sheet (its human one, else its auto one, as render.py
    writes it), with ``key`` and ``key_source``, its key as keys.py found it: the harp that plays with the record, and
    the song's key for the positions. ``back`` names the song's sheet viewer beside the page ("sheet.html"), which
    ‹ Chord sheet opens; with none, ‹ Library."""
    tab = parse(text)
    choice = harpfit.choose(tab, cho=cho, key=key, key_source=key_source, page_key=page_key)
    data = _data(tab, choice)
    data["overlay"] = _overlay_data(choice, cho, key, key_source)
    page_title = f"{title or 'Untitled'} · harmonica tab"
    # The song's names in the characters its viewer shows its Chinese in, for a song whose sheet is Chinese
    names = names_table(cho is not None and is_chinese(cho), [title or "Untitled", artist, page_title])
    head = _header(title, artist, tab, choice, facts or {}, back, names)
    article = _tab_html(tab, data) if tab.readable else _raw_html(text)
    style, _ = _assets()
    own_style, script = _own_assets()
    body = (
        '<aside class="necks" id="necks" hidden aria-label="Chord necks"></aside>\n'
        + '<div class="page">\n'
        + head
        + article
        + _footer(tab_file, url, placed=tab.readable and any(r.trusted and r.lyric for r in tab.rows()))
        + "</div>\n"
        + (_BAR if tab.readable else _BAR_RAW)
        + _PILL
        + json_block("harp-data", data)
        + (json_block("song-names", names) if names else "")
    )
    return _page(page_title, body, styles=(style, own_style), scripts=(_sound(), _overlay(), script), names=names)


# --- the data ----------------------------------------------------------------------------------------------------


def _data(tab: Tab, choice: harpfit.Choice) -> dict[str, Any]:
    why: dict[str, str] = {}
    for pc, reason in ((choice.harp, choice.why), (choice.named, "tab"), (choice.page, "page")):
        if pc is not None and _SAID[reason] and str(pc) not in why:
            why[str(pc)] = _SAID[reason]
    data: dict[str, Any] = {
        "harpKeys": list(harp.HARP_KEYS),
        "start": choice.harp,
        "why": why,
        "positions": None if choice.tonic is None else [harp.position_text(choice.tonic, h) for h in range(12)],
        "names": [spelling(Key(h, "ionian")) for h in range(12)],
        "holes": harp.hole_tables(),
        "bpm": BPM,
        "reading": {"name": tab.reading.notation.name, "source": tab.reading.source, "q": round(tab.reading.q, 2),
                    "margin": round(tab.reading.margin, 2), "said": tab.reading.said()},
    }
    if tab.readable:
        data["groups"] = []
        data["rows"] = []
    return data


# --- the overlay: Harmonica and Guitar --------------------------------------------------------------------------

_NO_SHEET = "With no chord sheet, caracole doesn't know the song's key, so it can't tell which harp plays it."
_NO_KEY = "With no key in its chord sheet, caracole can't tell which harp plays the song."


def _overlay_data(choice: harpfit.Choice, cho: str | None, key: str | None, key_source: str | None) -> dict[str, Any]:
    """What the page's overlay draws (the module's docstring): the song's chord sheet ``cho`` as written, in its key
    (``key``, ``key_source``: keys.py's, as its viewer reads them), with the harp ``choice`` the page starts on."""
    holes = [harp.holes(offset) for offset in range(12)]
    sheet = parse_sheet(cho) if cho else None
    shapes = viewer_key(cho, key, key_source) if cho else None
    if sheet is None or shapes is None:
        return {"guitar": _guitar_data(sheet, None) if sheet else None,
                "harp": {"key": None, "none": _NO_KEY if sheet else _NO_SHEET, "holes": holes}}
    sounds = sounding(shapes, sheet.capo or 0)
    names = spelling(sounds)
    capo = (sounds.tonic - shapes.tonic) % 12
    found = harp.tables(shapes, {shapes.mode: [parse_chord(name, strict=False) for name in sheet.chords]})
    chords = []
    for i, name, chord in _once(sheet):
        form, notes = found["harpChords"][shapes.mode][i], found["harpNotes"][shapes.mode][i]
        sound = name if capo == 0 else page_name(chord, names, capo)
        chords.append({"name": sound, "shape": "" if sound == name else name, "root": names[(chord.root + capo) % 12],
                       "entries": found["harpForms"][form], "notes": notes})
    return {"guitar": _guitar_data(sheet, shapes), "harp": {
        "key": key_name(sounds), "tonic": sounds.tonic, "names": names, "ring": found["harpRing"], "holes": holes,
        "scales": found["harpScales"][shapes.mode], "outside": found["harpOutside"][shapes.mode],
        "choices": found["harps"][shapes.mode], "chords": chords,
        "tabs": [] if choice.tabs_harp is None else [(choice.tabs_harp - sounds.tonic) % 12]}}


def _once(sheet) -> list[tuple[int, str, Chord]]:
    """The sheet's chords as its viewer's rail lists them: each it can read, once a name, in the order they come."""
    out, seen = [], set()
    for i, name in enumerate(sheet.chords):
        chord = parse_chord(name, strict=False)
        if chord is None or name in seen:
            continue
        seen.add(name)
        out.append((i, name, chord))
    return out


def _guitar_data(sheet, shapes: Key | None) -> dict[str, Any]:
    """The Guitar tab: each chord of the sheet as written with its positions on the guitar (the sheet's own first:
    ``mine``), and the key's neck (none for a sheet with no key)."""
    given = shapes_of(sheet)
    chords = []
    for _, name, chord in _once(sheet):
        bass = "" if chord.bass is None else chord.bass
        chords.append({"name": name, "list": chord_shapes(GUITAR, chord, 0, given),
                       "mine": given.get(f"{chord.root},{chord.suffix},{bass}", {}).get("mine", 0)})
    neck = None
    if shapes is not None:
        box = [(pc - shapes.tonic) % 12 for pc in harmony.pentatonic(shapes)]
        neck = {"name": key_name(shapes), "tonic": shapes.tonic, "tonicName": spelling(shapes)[shapes.tonic],
                "scale": [(pc - shapes.tonic) % 12 for pc in harmony.key_scale(shapes)], "pentatonic": box,
                "pentaName": "major pentatonic" if 4 in box else "minor pentatonic", "tuning": list(GUITAR.tuning)}
    return {"name": GUITAR.name, "strings": len(GUITAR.tuning), "chords": chords, "key": neck}


# --- the header --------------------------------------------------------------------------------------------------


def _a(name: str) -> str:
    """"a D harp", "an A harp", "an F harp", "an Eb harp"."""
    return ("an " if name[0] in "AEF" else "a ") + name + " harp"


def _header(title: str, artist: str, tab: Tab, choice: harpfit.Choice, facts: Mapping[str, Any],
            back: str | None, names: dict[str, dict[str, str]] | None = None) -> str:
    link = (f'<a class="back" href="{escape(quote(back))}" data-sheet>‹ Chord sheet</a>\n' if back
            else f'<a class="back" href="{LIBRARY_PAGE}">‹ Library</a>\n')
    return (
        '<header class="head">\n'
        + link
        + f"<h1{zh_attr(title or 'Untitled', names)}>{escape(title or 'Untitled')}</h1>\n"
        + artist_line(artist, names)
        + (_harp_lines(choice) if tab.readable else
           '<p class="facts" id="facts">Harmonica tab, as its tabber wrote it: caracole can\'t read its notation.</p>\n')
        + (_read_as(tab, facts) if tab.readable else "")
        + "</header>\n"
    )


def _harp_lines(choice: harpfit.Choice) -> str:
    """The header's harp: which, why, the position it plays the song in; with the record, how well it fits."""
    name = harp.HARP_KEYS[choice.harp]
    where = f" ({escape(harp.position_text(choice.tonic, choice.harp))})" if choice.tonic is not None else ""
    said = {"record": f"<b>{name} harp</b> with the record{where}",
            "tab": f"<b>{name} harp</b>, as the tab says{where}",
            "page": f"<b>{name} harp</b>, as harptabs.com's key says{where}",
            "song": f"<b>{name} harp</b> for the song's key{where}",
            "usual": f"<b>{name} harp</b>, as tabs are written when they name none{where}"}[choice.why]
    bits = ["Harmonica tab", said]
    if choice.why == "record" and choice.named is not None and choice.named != choice.harp:
        bits.append(f"the tab says {harp.HARP_KEYS[choice.named]} harp")
    html = f'<p class="facts" id="facts">{" · ".join(bits)}</p>\n'
    if choice.why == "record" and len(choice.fits) > 1:
        best, runner = choice.fits[0], choice.fits[1]
        html += (f'<p class="why">{best.share:.0%} of the sung notes fall on the sheet\'s chords on '
                 f"{_a(harp.HARP_KEYS[best.harp])}, {runner.share:.0%} on {_a(harp.HARP_KEYS[runner.harp])}</p>\n")
    return html


def _read_as(tab: Tab, facts: Mapping[str, Any]) -> str:
    """How the tab was read (its symbols as it writes them, and whether its own legend said so or caracole guessed,
    how surely), and what harptabs.com says of the tab: its difficulty, its views, its rating."""
    said = []
    if isinstance(facts.get("difficulty"), str) and facts["difficulty"].strip():
        said.append(escape(facts["difficulty"].strip()))
    views = facts.get("views")
    if isinstance(views, int) and not isinstance(views, bool) and views > 0:
        said.append(f"{views} views" if views < 1000 else f"{views / 1000:.0f}k views" if views < 999_500
                    else f"{views / 1e6:.1f}M views")
    rating = facts.get("rating")
    if isinstance(rating, (int, float)) and not isinstance(rating, bool) and rating > 0:
        said.append(f"{rating:.1f}★")
    reading = tab.reading
    symbols = " · ".join(f'<code class="sy">{escape(text)}</code> {escape(word)}' for text, word in reading.symbols())
    source = _SOURCE.get(reading.source, f"guessed ({reading.q:.2f})")
    return (f'<p class="legend" aria-label="How the tab was read">Read as: {symbols}, {escape(source)}'
            + (" · " + " · ".join(said) if said else "") + "</p>\n")



# --- the tab -----------------------------------------------------------------------------------------------------


def _tab_html(tab: Tab, data: dict[str, Any]) -> str:
    return ('<article class="sheet harp-tab" id="sheet">\n'
            + _notes_html(tab.notes)
            + "".join(_section_html(n, s, data) for n, s in enumerate(tab.sections))
            + "</article>\n")


def _raw_html(text: str) -> str:
    return f'<article class="sheet harp-tab raw" id="sheet">\n<pre class="tab">{escape(text.rstrip())}</pre>\n</article>\n'


def _notes_html(notes: list[str]) -> str:
    """The tabber's notes before the first row, as sheet.html shows a tab's: folded after two lines."""
    lines = [n for n in notes if n.strip()]
    if not lines:
        return ""
    body = "\n".join(f'<p class="l">{escape(n)}</p>' for n in lines)
    if len(lines) <= 2:
        return f'<div class="pre">\n{body}\n</div>\n'
    peek = "<br>".join(escape(n) for n in lines[:2])
    return (f'<details class="pre">\n<summary><span class="peek">{peek}</span><span class="named">Notes</span>'
            '<span class="more">More</span><span class="less">Less</span></summary>\n'
            f'<div class="pre-body">\n{body}\n</div>\n</details>\n')


def _section_html(n: int, section: Section, data: dict[str, Any]) -> str:
    out = [f'<section class="sec{" chorus" if section.chorus else ""}" id="sec-{n}">']
    if section.label:
        out.append(f'<h2 class="lbl">{escape(section.label)}</h2>')
    for item in section.items:
        if isinstance(item, Row):
            out.append(_row_html(item, data) if item.trusted else _written_html(item))
        elif isinstance(item, Legend):
            out.append('<div class="tab-legend"><p class="lgh">The tab\'s legend</p>'
                       + "".join(f'<p class="l">{escape(line.strip())}</p>' for line in item.lines) + "</div>")
        elif isinstance(item, Words):
            out += [f'<p class="l words">{escape(line.strip())}</p>' for line in item.lines if line.strip()]
        elif isinstance(item, Prose):
            out.append(f'<p class="note">{escape(item.text.strip())}</p>')
        elif isinstance(item, Gap):
            out.append('<div class="gap"></div>')
    out.append("</section>\n")
    return "\n".join(out)


def _written_html(row: Row) -> str:
    """A row read with low confidence: its line as written, and its words under it, in the tab's own columns."""
    lines = [row.text.rstrip()] + ([row.lyric.rstrip()] if row.lyric is not None else [])
    return f'<pre class="tab asw">{escape(chr(10).join(lines))}</pre>'


def _row_html(row: Row, data: dict[str, Any]) -> str:
    first = len(data["groups"])
    if row.lyric is None:
        lead = f'<i class="m">{escape(row.label)}</i> ' if row.label else ""
        cells = _cells(row.groups, data, " ")
        line = f'<p class="l holes">{lead}{cells}'
    else:
        out = []
        for groups, text in row.parts:
            words = _words(text)
            if groups:
                top = '<span class="hg">' + _cells(groups, data, "") + "</span>"
                lead = escape(words.pop(0)) if words else ""
                out.append(f'<span class="s">{top}<span class="y">{lead}</span></span>')
            out += [f'<span class="w">{escape(w)}</span>' for w in words]
        line = f'<p class="l hl">{"".join(out)}'
    data["rows"].append(list(range(first, len(data["groups"]))))
    return (f'{line}<button type="button" class="rp" data-row="{len(data["rows"]) - 1}" '
            f'aria-label="Play this line" aria-pressed="false">{_PLAY_ICON}</button></p>')


def _cells(groups: list[Group], data: dict[str, Any], space: str) -> str:
    """A row's groups in their order, ``space`` between two, none between two run together; in a row played alone,
    each a cell with its hold and its tie, which a line never parts."""
    out = ""
    for n, group in enumerate(groups):
        if n and not groups[n - 1].join:
            out += space
        cell = _group_html(group, data) + (_JOIN if group.join and n + 1 < len(groups) else "")
        out += f'<span class="cell">{cell}</span>' if space else cell
    return out


def _group_html(group: Group, data: dict[str, Any]) -> str:
    """A group of holes as the page shows it before its script runs, which draws it again as the harp and Notes
    ask; ``data-i``, its place in the data's ``groups``. What the notation couldn't read is its text, as written."""
    if group.kind == "unread":
        return f'<span class="u">{escape(group.text)}</span>'
    i = len(data["groups"])
    more: dict[str, Any] = {}
    if group.effects:
        more["fx"] = list(group.effects)
    if group.join:
        more["join"] = 1
    data["groups"].append([group.kind, [[h.hole, h.breath[0], h.bend, int(h.over)] for h in group.holes]]
                          + ([more] if more else []))
    a, b = _BRACKETS[group.kind]
    inner = " ".join(_hole_html(h) for h in group.holes)
    effects = "".join(f'<small class="fx">{escape(e)}</small>' for e in group.effects)
    held = '<span class="hold" aria-hidden="true">…</span>' if group.hold else ""
    return (f'<b class="h" data-i="{i}" tabindex="0" role="button" aria-label="{escape(_said(group))}">'
            f"{a}{inner}{b}{effects}</b>{held}")


def _hole_html(hole: Hole) -> str:
    sign = '<span class="sg">−</span>' if hole.breath == "draw" else ""
    bend = f'<span class="bd">{"′" * hole.bend}</span>' if hole.bend else ""
    over = '<span class="bd">°</span>' if hole.over else ""
    return f'<span class="{hole.breath[0]}">{sign}{hole.hole}{bend}{over}</span>'


def _said(group: Group) -> str:
    """A group in words, for a screen reader: "draw 3 bent 1", "blow 4 and blow 5", "draw 1, wah"."""
    return (" and ".join(f"{h.breath} {h.hole}" + (f" bent {h.bend}" if h.bend else "")
                         + (" overblown" if h.over else "") for h in group.holes)
            + "".join(f", {e}" for e in group.effects))


# --- the foot and the bar ----------------------------------------------------------------------------------------


def _footer(tab_file: str, url: str | None, *, placed: bool) -> str:
    """The foot: the tab's text beside the page, where it came from (its page on harptabs.com, else the site), and a
    word on keeping the page private."""
    site = url if isinstance(url, str) and url.startswith(SITE) else SITE
    return (
        '<footer class="foot">\n'
        f'<p><a class="pdf" href="{escape(quote(tab_file))}">The tab as text</a></p>\n'
        f'<p>Tab from <a href="{escape(site)}">harptabs.com</a>, as its tabber wrote it'
        + ("; caracole placed each hole over its syllable.</p>\n" if placed else ".</p>\n")
        + "<p>Keep this page private: the lyrics and the tab are other people's work.</p>\n"
        "</footer>\n"
    )


# The bar, hidden until the script runs, in the order a keyboard reaches it: the overlay shown or hidden (from 1200 px,
# as the viewer's: page.py's _CONTROLS); the harp a semitone down or up, its name
# and why it was chosen between them; the neck, the overlay's sheet opened or closed (below 1200 px, as the viewer's);
# ♪, each hole's note on it in its place (pressed while it shows); Aa, the text size in a box beside it; ▶, scrolling
# by itself. A tab shown as written has the overlay's buttons, Aa and ▶ alone.
_BAR = """<div class="bar" id="bar" hidden role="region" aria-label="Controls">
<div class="bar-in">
<button type="button" class="tool necks-toggle" id="necks-toggle" hidden aria-label="Chord necks" aria-pressed="true" aria-controls="necks"><svg viewBox="0 0 16 16" aria-hidden="true"><path fill-rule="evenodd" d="M3 2h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm0 1.5a.5.5 0 0 0-.5.5v8a.5.5 0 0 0 .5.5h10a.5.5 0 0 0 .5-.5V4a.5.5 0 0 0-.5-.5zM3.5 4.5h3v7h-3z"/></svg></button>
<span class="keys" id="harps" role="group" aria-label="Harp">
<button type="button" class="step" id="h-down" aria-label="The harp a semitone down">−</button>
<output class="now" id="harp-now" for="h-down h-up"><span class="k" id="harp-name"></span><span class="d" id="harp-why"></span></output>
<button type="button" class="step" id="h-up" aria-label="The harp a semitone up">+</button>
</span>
<button type="button" class="tool necks-open" id="necks-open" hidden aria-label="Necks and harps" aria-haspopup="dialog" aria-controls="necks" aria-expanded="false"><svg viewBox="0 0 16 16" aria-hidden="true"><path fill-rule="evenodd" d="M2.75 4.25h10.5a1.5 1.5 0 0 1 1.5 1.5v4.5a1.5 1.5 0 0 1-1.5 1.5H2.75a1.5 1.5 0 0 1-1.5-1.5v-4.5a1.5 1.5 0 0 1 1.5-1.5zM2.5 5.5v5h11v-5zm2.25 0h1v5h-1zM8 5.5h1v5H8zm3.25 0h1v5h-1zM6.875 7a1 1 0 1 0 0 2a1 1 0 1 0 0-2z"/></svg></button>
<button type="button" class="tool notes" id="notes" aria-pressed="false" aria-label="Note names">♪</button>
<span class="size-box" id="size-box">
<button type="button" class="tool" id="size" aria-label="Text size" aria-expanded="false" aria-controls="sizes">Aa</button>
<span class="sizes" id="sizes" role="group" aria-label="Text size" hidden>
<button type="button" id="smaller" aria-label="Smaller text" aria-disabled="false">A−</button>
<output id="fs-now">18 px</output>
<button type="button" id="bigger" aria-label="Bigger text" aria-disabled="false">A+</button>
</span>
</span>
<button type="button" class="tool play" id="scroll" aria-label="Scroll by itself">""" + _PLAY_ICON + """</button>
</div>
</div>
"""
_BAR_RAW = (_BAR.replace(_BAR[_BAR.index('<span class="keys"'):_BAR.index('<button type="button" class="tool necks-open"')],
                         "", 1)
            .replace(_BAR[_BAR.index('<button type="button" class="tool notes"'):_BAR.index('<span class="size-box"')], "", 1))

# Scrolling by itself, as the viewer's (page.py's _CONTROLS): the pill that steers it, above the bar's place.
_PILL = """<div class="pill" id="pill" role="group" aria-label="Scrolling by itself" hidden>
<button type="button" class="go" id="go" aria-label="Pause"><svg class="ring" viewBox="0 0 44 44" aria-hidden="true"><circle class="track" cx="22" cy="22" r="19"/><circle class="arc" cx="22" cy="22" r="19" pathLength="100"/></svg><svg class="i-pause" viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="2" width="3.6" height="12" rx="1"/><rect x="9.4" y="2" width="3.6" height="12" rx="1"/></svg><svg class="i-play" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.4v11.2c0 .6.7 1 1.2.6l8.8-5.6a.7.7 0 0 0 0-1.2L5.7 1.8c-.5-.4-1.2 0-1.2.6z"/></svg><span class="tick" id="tick"></span></button>
<button type="button" class="step" id="pill-slower" data-speed="-1" aria-label="Slower">−</button>
<output id="pill-speed">6</output>
<button type="button" class="step" id="pill-faster" data-speed="1" aria-label="Faster">+</button>
<button type="button" class="end" id="pill-end" aria-label="Stop scrolling">×</button>
</div>
<p class="vh" id="scroll-status" role="status"></p>
<noscript><p class="noscript">Turn on JavaScript to hear the holes and change the harp.</p></noscript>
"""
