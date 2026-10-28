"""A harmonica tab as harptabs.com's tabbers write it (``harmonica-N.txt``, harptabs_fetch.py: the page's ``<pre>``
as it is), read for its page (harptab_page.py): its sections, its rows of holes, each paired with the line of words
sung under it, the syllable each hole is blown on, and the words around them. The standard library alone.

**The notation** (harptabs.com's own key, and what its tabs write besides):

- a hole: ``4`` or ``+4`` blow, ``-4`` (``−4``, ``–4``) draw; ``4B`` blow and ``4D`` draw (a suffix, upper case);
  a bend after it, ``'`` ``''`` ``'''`` or ``b`` ``bb`` ``bbb`` (``-3'``, ``-3bb``), ``"`` or ``”`` two (``-3"``,
  as ``-3''``), before it (``b-3``) or between its sign and it (``-b3``), after its brackets (``(3)b``); an
  overblow or an overdraw ``o`` (``6o``, ``-7o``); a chromatic's slide pressed in, ``<`` or ``*``. In a tab that
  writes no ``-`` anywhere and puts single holes in brackets, ``(5)`` is a draw (the Spanish tabs' "aspirar");
  anywhere else ``(-4)`` and ``(4)`` are the hole;
- holes together: ``(4 5 6)`` or ``(456)`` a chord, ``{-4 -5}`` a head shake, ``[-2 -5]`` a tongue split, ``7,8B``
  holes 7 and 8 blown;
- what a line of holes holds besides: holds (``----``, ``....``, ``___``, ``(hold)``), bars, ``~``, repeat marks
  (``x2``, ``(x2)``, ``2x``, ``(2x)``), a leading label (``Intro:``, ``FILL 1 :``). A time signature or a clock time
  (``Time: 3/4``, ``1:45``) is prose, never holes.

What no spelling reads is the line's ``unknown``, never dropped as if read.

**The lines.** A line is a row of holes when at least ``HOLE_SHARE`` of its characters read as holes, holes together
or holds (``scan``). The line under a row is its words when it is a line of text that is no section's name and no
address. A line of text alone between blank lines after the first row is the tabber's prose; so is a block that
holds an address or starts as an instruction does ("Repeat…", "Listen…"); a longer block is words sung to the same
tune (a later verse). Before the first row, every line is the tabber's notes. A short line that names a section
("Verse", "chorus-", "[Bridge]") starts one.

**Holes over syllables** (``align``). Each syllable start of a row's words (a word's first letter, and each letter
after a hyphen or a comma inside one) takes the hole written nearest it, within ``REACH`` columns of where the hole is
written or its number, one a start, the nearest pairs first; a hole placed before one written before it loses its
place. The holes left over inside a word with no hyphen there cut it where the pieces read best as syllables
(``_cuts``: "to|mor|row"), as ChordPro puts a chord inside a word; any hole still left joins the place before it (a
melisma: "air--"), or, before every place, the next word. A row's ``placement`` counts how each found its place.

**Readable or not** (``Tab.readable``). A tab with no row of holes, with more lines that hold holes but don't read as
a row than rows (a private notation: "(3)tue (3)te"), or for a chromatic harmonica (a slide, or a hole past 10) is
shown as its tabber wrote it: its page says so.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from dataclasses import dataclass, field

TAB_STOP = 8  # a tab character's columns, as harptabs.com's <pre> shows it
HOLE_SHARE = 0.75  # the share of a row's characters that read as holes, holes together or holds
REACH = 3  # the columns from a syllable's start a hole may be written at and still be blown on it
MAX_CUTS = 20000  # the most ways ``_cuts`` weighs for one word: past it, fewer cuts (a long word, many holes in it)

# --- the notation ---------------------------------------------------------------------------------------------
# Each spelling is a named piece.

_DRAW_SIGNS = "-−–"
# A bend after a hole, a semitone each: ' ’ ` or b (a b, not a word's start). " and ” are two (``_TWO_BENDS``), as ''
# is: Barrett's key prints a whole-step bend so, and 124 of the 128 a study of 146 tabs found sit on draws 2 and 3,
# the holes that bend a whole step.
_BEND = r"""(?:'|’|`|"|”|b(?!b*[ac-z]))"""
_TWO_BENDS = '"”'
_HOLE = re.compile(r"""
    (?P<pb>b{1,3}(?=[-+−–]?\d))?          # a bend written before the hole: b-3
    (?P<btn><)?                          # a chromatic's slide, before
    (?P<sign>[-+−–])?
    (?P<sb>b{1,3}(?=\d))?                # a bend between the sign and the hole: -b3 (Whole Lotta Love's)
    (?P<num>10|[1-9])
    (?P<bd>[BD](?![A-Za-z]))?            # 4B blow, 5D draw
    (?P<bend>BEND{1,3})?                 # -3' -3'' -3b -3bbb -3" (a b, not a word's start)
    (?P<ob>o(?![a-z]))?                  # 6o: an overblow, an overdraw on 7 to 10
    (?P<btn2>[<*](?!\S*[a-z]))?          # 4< 4*: the slide
""".replace("BEND", _BEND), re.X)
_INNER = r"(?:b{1,3})?<?[-+−–]?(?:b{1,3})?(?:10|[1-9])[BD]?(?:'|’|`|\"|”|b){0,3}o?[<*]?"
_GROUP = re.compile(r"(?P<open>[(\[{])\s*(?P<body>" + _INNER + r"(?:[\s,]*" + _INNER + r")*)\s*(?P<close>[)\]}])")
_BENT = re.compile(_BEND + "{1,3}")  # (3)b (3)' (3)": a bend after a lone hole in brackets, the hole's
_COMMA_CHORD = re.compile(r"(?P<body>(?:10|[1-9])(?:,(?:10|[1-9]))+)(?P<bd>[BD])")
_DECOR = re.compile(r"-{2,}|_+|\.{2,}|~+|\|+|\^|\*|,|;|/|\\|:|\(x\s?\d+\)|x\s?\d+\b|\(\d+x\)|\b\d+x\b|\(hold\)|hold\b|>|=",
                    re.I)
_HOLD = re.compile(r"-{2,}|\.{2,}|_+|\(hold\)|hold", re.I)
# A time signature, a clock time, a date (Time: 3/4, 1:45, 30/03/2018): prose, never holes.
_TIME = re.compile(r"(?<![\w/:.+−–-])\d{1,2}(?:[/:]\d{1,4})+(?![\w/:])")
_LEAD_LABEL = re.compile(r"^\s*(?P<label>\(?[A-Za-z][A-Za-z ]{0,14}(?:\d{1,2})?\)?)\s*[:;]+\s*")
_LABEL_WORDS = re.compile(
    r"(?i)^\W*(?:verse|chorus|bridge|intro|outro|solo|riff|refrain|instrumental|fill|coro|estribillo|interlude|"
    r"pre-?chorus|break|ending|end|repeat|harp|harmonica|part|melody|theme|next verse|last verse|verso|estrofa)\b")
_CHORUS = re.compile(r"(?i)chorus|coro|estribillo|refr[aeá]i?n")
_URL = re.compile(r"https?://|www\.", re.I)
# A line that tells the player something rather than being sung: its block is the tabber's prose.
_INSTRUCTION = re.compile(
    r"(?i)^\W*(?:listen|repeat|play|tabbed|tab by|for the|enjoy|note|thanks|thank you|same|then|watch|check|"
    r"words and music|written by|by\b|next verses|rest of)")
_SIGNED = re.compile(r"(?<![\w-])[-−–](?:10|[1-9])(?!\d)")
_SUFFIXED = re.compile(r"(?<!\w)(?:10|[1-9])[BD](?![A-Za-z])")
_BRACKETED = re.compile(r"\((?:10|[1-9])\)")
_WORD = re.compile(r"\S+")

# The harp's key a tab's words name: "I use an A harp", "harp in Bb", "ARMONICA EN C".
_KEY_PATTERNS = (
    re.compile(r"\b([A-G](?:b|#|♭|♯)?)\s*[- ]?(?:harp|harmonica|harmonika)\b"),
    re.compile(r"(?i:harp|harmonica|armonica|armónica)\s*(?i:en|in|de|key(?: of)?|:)?\s*([A-G](?:b|#|♭|♯)?)(?![\w#♯♭])"),
)


@dataclass(frozen=True)
class Hole:
    """One hole played: its number (1 to 10), its breath ("blow" or "draw"), the semitones it is bent down, whether
    it is overblown (or overdrawn), whether a chromatic's slide is pressed."""

    hole: int
    breath: str
    bend: int = 0
    over: bool = False
    button: bool = False

    def label(self) -> str:
        """As the page writes it: "4", "−4", "−3′′", "6°"."""
        return (("−" if self.breath == "draw" else "") + str(self.hole) + "′" * self.bend
                + ("°" if self.over else "") + ("<" if self.button else ""))


@dataclass(frozen=True)
class Group:
    """What one place of a row plays: a hole (``kind`` "note"), or holes together ("chord", "shake", "split"); the
    column its text starts at (tabs expanded), the column of its first hole's number, its text as written, and
    whether it is held (``----`` after it)."""

    holes: tuple[Hole, ...]
    kind: str
    col: int
    digit: int
    text: str
    hold: bool = False

    def label(self) -> str:
        inner = " ".join(h.label() for h in self.holes)
        return {"note": inner, "chord": f"({inner})", "shake": f"{{{inner}}}", "split": f"[{inner}]"}[self.kind]


@dataclass(frozen=True)
class Scan:
    """A line as holes: its groups, the share of its characters (spaces aside) they and the holds explain, what is
    left unread, and the label it leads with ("Intro")."""

    groups: tuple[Group, ...]
    coverage: float
    unknown: tuple[str, ...]
    label: str | None = None

    @property
    def is_row(self) -> bool:
        return bool(self.groups) and self.coverage >= HOLE_SHARE


@dataclass
class Row:
    """A line of holes, with the words sung under it (``lyric``, None for a line played alone), cut into ``parts``:
    each place's groups and the words sung from there to the next place, as a ChordPro line is; the first part's
    groups may be none (the words before the first hole)."""

    groups: list[Group]
    lyric: str | None
    label: str | None = None
    unknown: list[str] = field(default_factory=list)
    parts: list[tuple[list[Group], str]] = field(default_factory=list)
    placement: Counter = field(default_factory=Counter)  # "snap", "split", "held", "gap": how each found its place


@dataclass(frozen=True)
class Words:
    """Lines of words with no holes over them: a later verse, sung to the same tune."""

    lines: tuple[str, ...]


@dataclass(frozen=True)
class Prose:
    """A line of the tabber's: a note, an address, "next verses the same"."""

    text: str


@dataclass(frozen=True)
class Gap:
    """A blank line between two parts of a section."""


Item = Row | Words | Prose | Gap


@dataclass
class Section:
    label: str | None
    items: list[Item] = field(default_factory=list)

    @property
    def chorus(self) -> bool:
        return bool(self.label and _CHORUS.search(self.label))


@dataclass
class Tab:
    """A tab read: the tabber's notes before its first row, its sections, how it writes a draw ("signs": -4,
    "suffix": 4D, "parens": (4)), the harp's key its words name ("A", or None), the lines that hold holes but read as
    no row (``missed``), and whether it is a chromatic's."""

    notes: list[str]
    sections: list[Section]
    convention: str
    key: str | None
    missed: list[str]
    chromatic: bool

    def rows(self) -> list[Row]:
        return [item for s in self.sections for item in s.items if isinstance(item, Row)]

    @property
    def readable(self) -> bool:
        """Whether its page draws its holes, else its text as written (the module's docstring)."""
        rows = self.rows()
        return bool(rows) and len(self.missed) <= len(rows) and not self.chromatic


# --- a line ---------------------------------------------------------------------------------------------------


def _bends(marks: str | None) -> int:
    """The semitones bend marks bend: a semitone each, two for a " or a ”."""
    return sum(2 if ch in _TWO_BENDS else 1 for ch in marks or "")


def _hole(m: re.Match, *, parens_draw: bool = False) -> Hole:
    sign, suffix = m.group("sign"), m.group("bd")
    breath = "draw" if (sign and sign in _DRAW_SIGNS) or suffix == "D" or parens_draw else "blow"
    bend = _bends(m.group("bend")) + len(m.group("pb") or "") + len(m.group("sb") or "")
    return Hole(int(m.group("num")), breath, min(bend, 3), bool(m.group("ob")), bool(m.group("btn") or m.group("btn2")))


def expand(line: str) -> str:
    """A line as the page lays it out: tabs to their stops, a no-break space a space."""
    return line.expandtabs(TAB_STOP).replace(" ", " ")


def scan(line: str, *, parens_draw: bool = False) -> Scan:
    """The holes ``line`` holds, where, and how much of it they explain (``parens_draw``: the tab writes a draw as
    ``(5)``). What no spelling reads is ``unknown``."""
    text = expand(line)
    prose = [False] * len(text)  # a time, never holes (_TIME): unread
    for m in _TIME.finditer(text):
        prose[m.start():m.end()] = [True] * (m.end() - m.start())
    label = None
    lead = _LEAD_LABEL.match(text)
    if (lead and _HOLE.search(text[lead.end():]) and not lead.group("label").strip().isdigit()
            and not any(prose[:lead.end()])):  # "SOLO 4:24": a time, no label "SOLO 4"
        label = lead.group("label").strip("() ")
        text = " " * lead.end() + text[lead.end():]
    groups: list[Group] = []
    covered = [False] * len(text)

    def taken(a: int, b: int) -> bool:
        return any(covered[a:b]) or any(prose[a:b])

    def mark(a: int, b: int) -> None:
        covered[a:b] = [True] * (b - a)

    for m in _GROUP.finditer(text):
        inner = list(_HOLE.finditer(m.group("body")))
        if not inner or taken(m.start(), m.end()):
            continue
        kind = {"(": "chord", "{": "shake", "[": "split"}[m.group("open")]
        digit = m.start("body") + inner[0].start("num")
        end = m.end()
        if len(inner) == 1 and kind == "chord":  # (5): a draw where the tab writes no sign; (-4): the hole
            hole = _hole(inner[0], parens_draw=parens_draw and not inner[0].group("sign"))
            if bent := _BENT.match(text, end):  # (3)b (3)': a bend after the brackets, the hole's
                hole = Hole(hole.hole, hole.breath, min(hole.bend + _bends(bent.group(0)), 3), hole.over, hole.button)
                end = bent.end()
            groups.append(Group((hole,), "note", m.start(), digit, text[m.start():end]))
        else:
            groups.append(Group(tuple(_hole(i) for i in inner), kind, m.start(), digit, m.group(0)))
        mark(m.start(), end)
    for m in _COMMA_CHORD.finditer(text):
        if taken(m.start(), m.end()):
            continue
        breath = "draw" if m.group("bd") == "D" else "blow"
        holes = tuple(Hole(int(n), breath) for n in m.group("body").split(","))
        groups.append(Group(holes, "chord", m.start(), m.start(), m.group(0)))
        mark(m.start(), m.end())
    for m in _HOLE.finditer(text):
        if taken(m.start(), m.end()):
            continue
        before = text[m.start() - 1] if m.start() else " "
        after = text[m.end()] if m.end() < len(text) else " "
        if before.isalpha() or after.isalpha():  # a digit in a word ("2nd", "4th") is no hole
            continue
        groups.append(Group((_hole(m),), "note", m.start(), m.start("num"), m.group(0)))
        mark(m.start(), m.end())
    for m in _DECOR.finditer(text):
        if taken(m.start(), m.end()):
            continue
        mark(m.start(), m.end())
        if _HOLD.fullmatch(m.group(0)):  # held: the group before it
            before = [n for n, g in enumerate(groups) if g.col < m.start()]
            if before:
                n = max(before, key=lambda k: groups[k].col)
                g = groups[n]
                groups[n] = Group(g.holes, g.kind, g.col, g.digit, g.text, True)
    unknown = []
    for m in _WORD.finditer(text):
        rest = "".join(ch for i, ch in enumerate(m.group(0), m.start()) if not covered[i])
        if rest:  # nothing dropped as if read: a " left over is a bend no hole took
            unknown.append(rest)
    groups.sort(key=lambda g: g.col)
    letters = sum(not ch.isspace() for ch in text)
    good = sum(1 for i, ch in enumerate(text) if covered[i] and not ch.isspace())
    return Scan(tuple(groups), good / letters if letters else 0.0, tuple(unknown), label)


# --- the tab --------------------------------------------------------------------------------------------------


def parse(body: str) -> Tab:
    """The tab ``body`` (a ``harmonica-N.txt``) read: the module's docstring says how."""
    lines = [expand(line).rstrip() for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # How it writes a draw: a tab that writes no "-" draw and puts single holes in brackets reads (N) as one.
    signed = sum(len(_SIGNED.findall(line)) for line in lines)
    suffixed = sum(len(_SUFFIXED.findall(line)) for line in lines)
    bracketed = sum(len(_BRACKETED.findall(line)) for line in lines)
    parens_draw = signed == 0 and bracketed > 0
    convention = "parens" if parens_draw else "suffix" if suffixed > signed else "signs"
    scans = [scan(line, parens_draw=parens_draw) for line in lines]
    kinds = ["blank" if not line.strip() else "holes" if s.is_row else "text" for line, s in zip(lines, scans)]
    missed = [line.strip() for line, s, kind in zip(lines, scans, kinds)
              if kind == "text" and len(s.groups) >= 3 and s.coverage >= 0.4]

    notes: list[str] = []
    sections = [Section(None)]
    seen_row = False
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        if not seen_row:
            notes.extend(line.strip() for line in block)
        elif _is_prose(block):
            sections[-1].items.extend(Prose(line.strip()) for line in block)
        else:
            sections[-1].items.append(Words(tuple(line.rstrip() for line in block)))
        block.clear()

    i = 0
    while i < len(lines):
        kind, line = kinds[i], lines[i]
        if kind == "blank":
            flush()
            if seen_row and sections[-1].items and not isinstance(sections[-1].items[-1], Gap):
                sections[-1].items.append(Gap())
            i += 1
            continue
        if kind == "holes":
            flush()
            found = scans[i]
            lyric = None
            if i + 1 < len(lines) and kinds[i + 1] == "text" and not _is_label(lines[i + 1]) \
                    and not _URL.search(lines[i + 1]):
                lyric = lines[i + 1]
            label = found.label
            if label and _is_label(label + ":"):
                sections.append(Section(label))
                label = None
            row = Row(list(found.groups), lyric, label, list(found.unknown))
            align(row)
            sections[-1].items.append(row)
            seen_row = True
            i += 2 if lyric is not None else 1
            continue
        if _is_label(line) and (seen_row or _LABEL_WORDS.search(line)):
            flush()
            sections.append(Section(_label_text(line)))
        else:
            block.append(line if seen_row else line.strip())
        i += 1
    flush()
    for s in sections:
        while s.items and isinstance(s.items[-1], Gap):
            s.items.pop()
        while s.items and isinstance(s.items[0], Gap):
            s.items.pop(0)
    sections = [s for s in sections if s.items or s.label]
    prose = notes + [item.text for s in sections for item in s.items if isinstance(item, Prose)]
    rows = [item for s in sections for item in s.items if isinstance(item, Row)]
    chromatic = any(h.button or h.hole > 10 for r in rows for g in r.groups for h in g.holes)
    return Tab(notes, sections, convention, named_key(prose), missed, chromatic)


def _is_prose(block: list[str]) -> bool:
    """Whether a block of text between blank lines after the first row is the tabber's (a note, an address, an
    instruction), not words sung to the same tune."""
    return len(block) == 1 or any(_URL.search(line) for line in block) or bool(_INSTRUCTION.search(block[0]))


def named_key(lines: list[str]) -> str | None:
    """The harp's key the tabber's words name ("I use an A harp", "ARMONICA EN C"): the first they name, as harp.py
    names a harp's key ("Bb"), or None."""
    for line in lines:
        for pattern in _KEY_PATTERNS:
            if m := pattern.search(line):
                return m.group(1).replace("♭", "b").replace("♯", "#")
    return None


def _is_label(line: str) -> bool:
    words = line.split()
    stripped = line.strip()
    if not words or len(stripped) > 32 or _URL.search(stripped):
        return False
    if re.fullmatch(r"\[[^\]]+\]|\([^)]+\)", stripped) and len(words) <= 4:
        return True
    if _LABEL_WORDS.search(stripped) and len(words) <= 4:
        return True
    return len(words) <= 3 and stripped[-1] in ":-" and not stripped.endswith("--")


def _label_text(line: str) -> str:
    return line.strip().strip("[]()").rstrip(":-;. ").strip() or line.strip()


# --- holes over syllables -------------------------------------------------------------------------------------


def syllable_starts(lyric: str) -> list[int]:
    """The columns a syllable of ``lyric`` starts at: each word's first, and each letter after a hyphen or a
    comma inside one ("des-ert", "hea-vy,and")."""
    starts = []
    for w in _WORD.finditer(lyric):
        starts.append(w.start())
        for h in re.finditer(r"(?:-+|[,.;!?])(?=[^\W\d_])", w.group(0)):
            if h.start() > 0:
                starts.append(w.start() + h.end())
    return sorted(set(starts))


def align(row: Row, reach: int = REACH) -> None:
    """Place each group of ``row`` on a column of its words, cutting them into ``row.parts`` (the module's
    docstring); a row played alone is one part."""
    if row.lyric is None:
        row.parts = [(list(row.groups), "")] if row.groups else []
        return
    lyric = row.lyric.rstrip()
    starts = syllable_starts(lyric)
    words = [(w.start(), w.end()) for w in _WORD.finditer(lyric)]
    pairs = sorted(  # the nearest first; of two as near, the one written at or after the start
        (min(abs(s - g.col), abs(s - g.digit)), g.digit < s, s, n)
        for n, g in enumerate(row.groups) for s in starts if min(abs(s - g.col), abs(s - g.digit)) <= reach)
    at_of: dict[int, int] = {}
    taken: set[int] = set()
    for _, _, s, n in pairs:
        if n not in at_of and s not in taken:
            at_of[n] = s
            taken.add(s)
    for n in sorted(at_of):  # in their order: one placed before a group written before it loses its place
        if any(m < n and m in at_of and at_of[m] > at_of[n] for m in at_of):
            taken.discard(at_of.pop(n))
    placement = Counter(snap=len(at_of))
    for a, b in words:
        inside = [n for n, g in enumerate(row.groups) if n not in at_of and a < g.digit < b and lyric[g.digit].isalpha()]
        if not inside:
            continue
        fixed = sorted({a, b} | {t for t in taken if a < t < b})
        for n, cut in zip(inside, _cuts(lyric, (a, b), [row.groups[n].digit for n in inside], fixed)):
            if cut is not None:
                at_of[n] = cut
                taken.add(cut)
                placement["split"] += 1
    for n, g in enumerate(row.groups):
        if n in at_of:
            continue
        before = [at_of[m] for m in range(n) if m in at_of]
        if before:
            at_of[n] = before[-1]
            placement["held"] += 1
        else:
            later = [a for a, _ in words if a >= g.digit] or [words[0][0] if words else 0]
            at_of[n] = later[0]
            placement["gap"] += 1
    places: dict[int, list[Group]] = {}
    for n, g in enumerate(row.groups):
        places.setdefault(at_of[n], []).append(g)
    cuts = sorted(places)
    parts: list[tuple[list[Group], str]] = []
    if cuts and cuts[0] > 0 and lyric[:cuts[0]].strip():
        parts.append(([], lyric[:cuts[0]]))
    for n, at in enumerate(cuts):
        end = cuts[n + 1] if n + 1 < len(cuts) else len(lyric)
        parts.append((places[at], lyric[at:end]))
    row.parts = parts
    row.placement = placement


_VOWELS = frozenset("aeiouyáéíóúàèìòùäëïöüAEIOUYÁÉÍÓÚÀÈÌÒÙÄËÏÖÜ")
_DIGRAPHS = frozenset({"gh", "th", "ch", "sh", "ph", "ng", "ck", "wh", "qu"})


def _rank(lyric: str, k: int) -> float:
    """How well a word cut before ``k`` reads as a syllable break: between two consonants (not a digraph), 0
    ("tomor|row"); after a vowel, before a consonant and a vowel, 0.8 ("be|lieve"); else 1.6."""
    l1, r1, r2 = lyric[k - 1], lyric[k], lyric[k + 1:k + 2]
    if l1 not in _VOWELS and r1 not in _VOWELS and (l1 + r1).lower() not in _DIGRAPHS:
        return 0.0
    if l1 in _VOWELS and r1 not in _VOWELS and r2 and r2 in _VOWELS:
        return 0.8
    return 1.6


def _cuts(lyric: str, word: tuple[int, int], anchors: list[int], fixed: list[int]) -> list[int | None]:
    """Where to cut a word with no hyphen for the holes written at ``anchors`` inside it, in their order: the cuts
    that leave each piece a vowel, each near its hole (written at its syllable's start or a column after it) and
    where a syllable breaks best (``_rank``), the cheapest set; ``fixed``, the word's ends and the places already in
    it. Fewer cuts when not every hole can have one (the rest are held), and fewer when there are more ways than
    ``MAX_CUTS`` to weigh."""
    a, b = word
    spots = [k for k in range(a + 1, b) if k not in fixed and lyric[k - 1].isalpha() and lyric[k].isalpha()]
    for count in range(min(len(anchors), len(spots)), 0, -1):
        if math.comb(len(anchors), count) * math.comb(len(spots), count) > MAX_CUTS:
            continue
        best = None
        for chosen in itertools.combinations(range(len(anchors)), count):
            for cut in itertools.combinations(spots, count):
                bounds = sorted(set(fixed) | set(cut))
                if not all(_VOWELS.intersection(lyric[x:y]) for x, y in zip(bounds, bounds[1:])):
                    continue
                cost = sum(0.6 * abs(anchors[i] - (k + 1)) + _rank(lyric, k) for i, k in zip(chosen, cut))
                if best is None or cost < best[0]:
                    best = (cost, chosen, cut)
        if best is not None:
            out: list[int | None] = [None] * len(anchors)
            for i, k in zip(best[1], best[2]):
                out[i] = k
            return out
    return [None] * len(anchors)
