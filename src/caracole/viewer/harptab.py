"""A harmonica tab as harptabs.com's tabbers write it (``harmonica-N.txt``, harptabs_fetch.py: the page's ``<pre>``
as it is), read for its page (harptab_page.py): its notation, its sections, its rows of holes, each paired with the
line of words sung under it, the syllable each hole is blown on, and the words around them. On top of harp.py.

**The notation is data** (``Notation``): its symbols (``Symbol``: a mark as tabs write it, what it means and where:
before the hole, after it, around it, between two holes), the breath of a hole written with no mark (``bare``), and
whether its letters read in either case (``fold``). Each compiles into its tokenizer (``scan``). The presets
(``PRESETS``), the commonest first:

- ``signs``, harptabs.com's own key: ``4`` or ``+4`` blow, ``-4`` (``−4``, ``–4``) draw; a bend after the hole,
  ``'`` ``''`` ``'''`` or ``b`` ``bb`` ``bbb`` (``-3'``, ``-3bb``), ``"`` or ``”`` two (``-3"``, as ``-3''``: Barrett's
  key prints a whole-step bend so), before it (``b-3``) or between its sign and it (``-b3``); an overblow or an
  overdraw ``o`` (``6o``, ``-7o``); a chromatic's slide pressed in, ``<`` or ``*``;
- ``brackets``, the Spanish tabs' "aspirar": a hole alone blown, ``(5)`` drawn, every unsigned hole in brackets a
  draw, a bend after the brackets the hole's (``(3)b``); ``-`` joins two;
- ``letters``: ``4B`` or ``4b`` blow, ``4D`` or ``4d`` draw, a bend ``*`` or ``'`` before the letter (``3*d``), ``-``
  joining two (``3*d-3d``), ``7,8B`` holes 7 and 8 blown; a hole with no letter is unread;
- ``signs after`` (``6+ 6-``, Wikibooks' two signs) and ``barrett`` (a hole alone drawn, ``4+`` blown).

What every notation shares: holes together, ``(4 5 6)`` or ``(456)`` a chord, ``{-4 -5}`` a head shake, ``[-2 -5]`` a
tongue split; holds (``----``, ``....``, ``___``, ``(hold)``), bars, ``~``, repeat marks (``x2``, ``(x2)``, ``2x``,
``(2x)``) and a leading label (``Intro:``, ``FILL 1 :``). A time signature or a clock time (``Time: 3/4``, ``1:45``)
is prose, never holes.

**What the whole tab says** changes each candidate alike: where it writes a dot before a hole (``. 4``, ``.5``, a
German hymn series' "the dots extend the note"), a single dot lengthens the hole before it (``DOTS``); where the
page's chip (``parse``'s ``harp``) calls the harp diatonic, ``*`` after a hole may be a bend (``-3*``, ``-3**``):
one more candidate, ``signs`` with it (``STAR_BENDS``), before ``signs`` (the chip makes it the commoner reading
there), and a slide is a note no Richter harp plays; Chromatic, the tab is a chromatic's.

**Which notation** (``read``). The tab is scanned under each candidate and the best kept by Q = P × T, as CleverCSV
picks a CSV's dialect: P, the share of the lines of holes' characters the notation explains (the lines any candidate
reads as holes, the tabber's words in them aside, so each is judged on the same text); T, the share of the holes it reads a Richter harp plays
(``harp.hole_note``; a slide is playable unless the page's chip says Diatonic). A tie goes to the commoner. The
margin is the winner's score over the best candidate that reads the tab differently; a notation less common than
such a rival must beat it by ``MARGIN``, and the winner's Q must reach ``TAB_Q``, else the tab is its text as written.

**A legend** (``legend``): two or more adjacent lines ``SYM = meaning`` (or ``:``, ``-``, columns), each meaning a
word of ``_LEXICON``'s ("(w) = Wah effect", "b= blow", "(x) = aspirar"). It is evidence, never an order: it makes one
more candidate, the preset that agrees with most of it changed as it says, and each candidate's score is multiplied
by ``1 + LEGEND_WEIGHT × agreement``. Its lines are a ``Legend`` on the page.

**A reading pinned** (``pinned``): overrides.toml's ``[harmonica]`` names how a tab is read, a preset, "legend"
(the tab's own), or a table, a preset and what its symbols mean (``check_spec``); ``parse(notation=)`` reads it so,
whatever the others score, and draws it whatever its Q (``source`` "pinned"). ``readings`` is every way caracole
weighs, best first, for caracole serve's page of them; ``spec_of`` the pin of each. ``Reading.standard``: harptabs.com's
own key, guessed, the tab using nothing else, whose page says no more than that key's legend.

**The lines.** A line is a row of holes when at least ``HOLE_SHARE`` of its characters read as holes, holes together
or holds (``scan``), or of them, the tabber's words in it aside (``Scan.is_row``: "6 -6 7 BOM BOM (percussions)",
"(3)tue (2)te", holes and their words after them), where it writes three tokens holding holes one after another, or
holes in each, and no more words than holes. Those words, an aside in brackets (its numbers no holes) and a syllable
written against its hole, are kept in their place as text (a group of kind "words"). A row reads with confidence its
own P × T (its words aside), and one under ``ROW_TRUST``, or a line that holds
three holes but reads under ``HOLE_SHARE``, is a row shown as written (``Row.trusted``). Nothing read is lost: what a
row's notation can't read is kept in its place (a group of kind "unread": ``$``, ``(DV)``). The line under a row is
its words when it is a line of text that is no section's name, no address and no line of holes too few to be a row
(``Scan.holey``: "do 3, slip to 6"). A line of text alone between blank lines after the first row is the tabber's
prose; so is a block that holds an address or starts as an instruction does ("Repeat…", "Listen…"); a longer block is
words sung to the same tune (a later verse). Before the first row, every line is the tabber's notes. A short line that
names a section ("Verse", "chorus-", "[Bridge]") starts one; right above or below a row, one that starts so but goes
on in words ("End of the road") is sung. A tab that writes each row's words above it (``_above``: the lines of words
above its rows fit them, syllables to holes, clearly better than those below) pairs each row with the line above it
(``Row.above``), its first line no note.

**Holes over syllables** (``align``). Each syllable start of a row's words (a word's first letter, and each letter
after a hyphen or a comma inside one) takes the hole written nearest it, within ``REACH`` columns of where the hole is
written or its number, one a start, the nearest pairs first; a hole placed before one written before it loses its
place. The holes left over inside a word with no hyphen there cut it where the pieces read best as syllables
(``_cuts``: "to|mor|row"), as ChordPro puts a chord inside a word; any hole still left joins the place before it (a
melisma: "air--"), or, before every place, the next word. What a row couldn't read goes with the hole it is written
against. A row's ``placement`` counts how each found its place.

**Readable or not** (``Tab.readable``). A tab with no row drawn, whose reading isn't confident, or for a chromatic
harmonica (its page says Chromatic, or it presses a slide) is shown as its tabber wrote it: its page says so.
"""

from __future__ import annotations

import functools
import itertools
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from caracole.viewer import harp

TAB_STOP = 8  # a tab character's columns, as harptabs.com's <pre> shows it
HOLE_SHARE = 0.75  # the share of a row's characters that read as holes, holes together or holds
MISSED_SHARE = 0.4  # a line holding three holes read this far holds holes caracole couldn't read: as written
REACH = 3  # the columns from a syllable's start a hole may be written at and still be blown on it
MAX_CUTS = 20000  # the most ways ``_cuts`` weighs for one word: past it, fewer cuts (a long word, many holes in it)
TAB_Q = 0.5  # the least Q a tab is drawn at
MARGIN = 0.05  # how far a notation must beat a commoner one that reads the tab differently
ROW_TRUST = 0.5  # the least confidence (its own P × T) a row is drawn at
LEGEND_WEIGHT = 0.2  # how much a tab's legend weighs: a candidate's score × (1 + this × its agreement)
ABOVE_LEAD = 2.0  # how far the words above a tab's rows must fit them better than those below, at least (``_above``)
ABOVE_SHARE = 1 / 6  # … and at least this share of its rows

# --- the notation ---------------------------------------------------------------------------------------------

BREATHS = ("blow", "draw")
EFFECTS = ("hold", "wah", "vibrato", "shake", "trill", "glissando", "staccato")  # what a symbol may add to a hole
MEANINGS = BREATHS + ("bend", "over", "slide", "join", "together", "mark") + EFFECTS
PLACES = ("before", "after", "around", "between")


@dataclass(frozen=True)
class Symbol:
    """A mark of a notation: its ``text`` as tabs write it, what it ``means`` (``MEANINGS``: a breath, a bend of
    ``count`` semitones, an overblow, a chromatic's slide, notes run together, holes played at once, a mark that
    plays nothing, an effect) and where it is written (``at``, ``PLACES``: before the hole, after it, around it, as
    ``()``, or between two holes)."""

    text: str
    means: str
    at: str
    count: int = 1


@dataclass(frozen=True)
class Notation:
    """How a tab writes its holes: its ``name``, its ``symbols``, the breath of a hole written with no breath mark
    (``bare``: "blow", "draw", or None where a hole needs one) and whether its letters read in either case
    (``fold``)."""

    name: str
    symbols: tuple[Symbol, ...]
    bare: str | None = "blow"
    fold: bool = False

    def changed(self, symbols: tuple[Symbol, ...] = (), *, name: str | None = None, bare: str | None = "",
                fold: bool | None = None) -> Notation:
        """This notation with ``symbols`` in place of its own written the same way and in the same place (the
        others added), as a legend or the owner changes it."""
        keys = {(self._key(s.text), s.at) for s in symbols}
        kept = tuple(s for s in self.symbols if (self._key(s.text), s.at) not in keys)
        return Notation(name or self.name, kept + tuple(symbols), self.bare if bare == "" else bare,
                        self.fold if fold is None else fold)

    def _key(self, text: str) -> str:
        return text.casefold() if self.fold else text

    def meaning(self, text: str, at: str) -> Symbol | None:
        """The symbol it reads ``text`` written ``at`` as, or None."""
        key = self._key(text)
        return next((s for s in self.symbols if s.at == at and self._key(s.text) == key), None)


def _symbols(at: str, means: str, *texts: str, count: int = 1) -> tuple[Symbol, ...]:
    return tuple(Symbol(t, means, at, count) for t in texts)


_TWO_BENDS = _symbols("after", "bend", '"', "”", count=2)  # a whole step: Barrett's "3”"
SIGNS = Notation("signs", (
    *_symbols("before", "draw", "-", "−", "–"), *_symbols("before", "blow", "+"),
    *_symbols("before", "bend", "b"), *_symbols("before", "slide", "<"),
    *_symbols("after", "bend", "'", "’", "`", "b"), *_TWO_BENDS, *_symbols("after", "over", "o"),
    *_symbols("after", "slide", "<", "*"),
))
BRACKETS = Notation("brackets", (
    *_symbols("before", "blow", "+"), *_symbols("around", "draw", "()"),
    *_symbols("after", "bend", "'", "’", "b"), *_TWO_BENDS, *_symbols("between", "join", "-"),
))
LETTERS = Notation("letters", (
    *_symbols("after", "blow", "b"), *_symbols("after", "draw", "d"), *_symbols("after", "bend", "*", "'", "’"),
    *_TWO_BENDS, *_symbols("between", "join", "-"), *_symbols("between", "together", ","),
), bare=None, fold=True)
SIGNS_AFTER = Notation("signs after", (
    *_symbols("after", "blow", "+"), *_symbols("after", "draw", "-", "−", "–"),
    *_symbols("after", "bend", "'", "’"), *_TWO_BENDS,
))
BARRETT = Notation("barrett", (
    *_symbols("after", "blow", "+"), *_symbols("after", "bend", "'", "’"), *_TWO_BENDS,
), bare="draw")
PRESETS = (SIGNS, BRACKETS, LETTERS, SIGNS_AFTER, BARRETT)  # the commonest first: a tie goes to the first
PRESET = {n.name: n for n in PRESETS}
DOTS = Symbol(".", "hold", "after")  # each candidate's, in a tab that writes a dot before a hole
STAR_BENDS = SIGNS.changed((Symbol("*", "bend", "after"),))  # a candidate where the page's chip says Diatonic

_NUM = r"(?:10|[1-9])"
_KINDS = {"(": "chord", "{": "shake", "[": "split"}
# What every notation shares: marks that play nothing (bars, repeats, ~) and holds, the group before them held.
_DECOR = re.compile(r"-{2,}|_+|\.{2,}|~+|\|+|\^|\*|,|;|/|\\|:|\(x\s?\d+\)|x\s?\d+\b|\(\d+x\)|\b\d+x\b|\(hold\)|hold\b|>|=",
                    re.I)
_HOLD = re.compile(r"-{2,}|\.{2,}|_+|\(hold\)|hold", re.I)
# A time signature, a clock time, a date (Time: 3/4, 1:45, 30/03/2018): prose, never holes.
_TIME = re.compile(r"(?<![\w/:.+−–-])\d{1,2}(?:[/:]\d{1,4})+(?![\w/:])")
# The tabber's words in brackets, "(percussions)", "(nur Vers 1 + 2 !)": prose, never holes, its numbers too.
_ASIDE = re.compile(r"\((?P<body>[^()]*)\)")
_DOT_BEFORE = re.compile(r"(?<![.\w])\.[ \t]*[-+−–]?(?:10|[1-9])(?!\d)")  # . 4  .5  .-6: a dot before a hole
_CHIPS = {"Diatonic": re.compile(r"(?i)\bdiatonic\b"), "Chromatic": re.compile(r"(?i)\bchromatic\b")}
_SIGNS = "+-−–"
_LEAD_LABEL = re.compile(r"^\s*(?P<label>\(?[A-Za-z][A-Za-z ]{0,14}(?:\d{1,2})?\)?)\s*[:;]+\s*")
_LABEL_WORD = (r"(?:verse|chorus|bridge|intro|outro|solo|riff|refrain|instrumental|fill|coro|estribillo|interlude|"
               r"pre-?chorus|break|ending|end|repeat|harp|harmonica|part|melody|theme|next verse|last verse|verso|"
               r"estrofa)\b")
_LABEL_WORDS = re.compile(r"(?i)^\W*" + _LABEL_WORD)
# What a section's name holds besides its words: a number, a repeat mark, punctuation ("Verse 2", "Chorus (x2)").
_LABEL_REST = re.compile(r"(?i)" + _LABEL_WORD + r"|\b(?:x\s?\d+|\d+x|\d+)\b|[^\w]")
_CHORUS = re.compile(r"(?i)chorus|coro|estribillo|refr[aeá]i?n")
_URL = re.compile(r"https?://|www\.", re.I)
# A line that tells the player something rather than being sung: its block is the tabber's prose.
_INSTRUCTION = re.compile(
    r"(?i)^\W*(?:listen|repeat|play|tabbed|tab by|for the|enjoy|note|thanks|thank you|same|then|watch|check|"
    r"words and music|written by|by\b|next verses|rest of)")
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
    """What one place of a row plays: a hole (``kind`` "note"), or holes together ("chord", "shake", "split"), or
    what its notation couldn't read, kept as written ("unread", no holes), or the tabber's words in it ("words", no
    holes: "BOM BOM", "(Chorus)", "tue" against its hole); the column its text starts at (tabs
    expanded), the column of its first hole's number, its text as written, whether it is held (``----`` after it),
    its other ``effects`` ("wah"), and whether it runs into the next group (``join``: ``3*d-3d``)."""

    holes: tuple[Hole, ...]
    kind: str
    col: int
    digit: int
    text: str
    hold: bool = False
    effects: tuple[str, ...] = ()
    join: bool = False

    @property
    def end(self) -> int:
        return self.col + len(self.text)

    def label(self) -> str:
        if not self.holes and self.kind in ("unread", "words"):
            return self.text
        inner = " ".join(h.label() for h in self.holes)
        return {"note": inner, "chord": f"({inner})", "shake": f"{{{inner}}}", "split": f"[{inner}]"}[self.kind]


@dataclass(frozen=True)
class Scan:
    """A line as holes: its groups (what it couldn't read among them, kind "unread"), the share of its characters
    (spaces aside) they, the holds and its notation's marks explain, what is left unread as before (``unknown``, a
    word's leftovers), the label it leads with ("Intro"), and the symbols it read, as written (``used``: each
    ``(text, means, at, count)``, a hole alone ``("", bare, "bare", 1)``)."""

    groups: tuple[Group, ...]
    coverage: float
    unknown: tuple[str, ...]
    label: str | None = None
    used: Counter = field(default_factory=Counter, compare=False)
    free: int = 0  # its words standing free: tokens of three letters or more and no digit ("slip", "BOM")
    prose: float = 0.0  # the share of its characters that are the tabber's words, kept as text (kind "words")
    run: int = 0  # the most tokens holding holes it writes one after another, a bar or a hold between them no break
    tokens: int = 0  # its tokens, bars and holds aside

    @property
    def explained(self) -> float:
        """The share of its characters, its words aside, its notation explains."""
        rest = 1 - self.prose
        return min(1.0, self.coverage / rest) if rest > 0 else 0.0

    @property
    def holes(self) -> tuple[Group, ...]:
        """Its groups that play: every one but the unread."""
        return tuple(g for g in self.groups if g.holes)

    @property
    def is_row(self) -> bool:
        """Whether it is a row of holes: ``HOLE_SHARE`` of it read; or of it, its words aside ("6 -6 7 BOM BOM",
        "(2)te (3)tue"), where it writes three tokens holding holes one after another at least (or holes in every
        token: "(4)tue (45)tu") and no more words than holes."""
        return bool(self.holes) and (self.coverage >= HOLE_SHARE or (
            self.explained >= HOLE_SHARE and self.run >= min(3, self.tokens) and len(self.holes) >= self.free))

    @property
    def missed(self) -> bool:
        """Whether it holds holes its notation couldn't read enough of to make it a row."""
        return not self.is_row and len(self.holes) >= 3 and self.coverage >= MISSED_SHARE

    @property
    def holey(self) -> bool:
        """Whether it is a line of holes too few or too mixed to be a row ("do 3, slip to 6"): never a row's words.
        Two holes at least, and twice as many as its words standing free."""
        return len(self.holes) >= 2 and len(self.holes) >= 2 * self.free


@dataclass
class Row:
    """A line of holes, with the words sung under it (``lyric``, None for a line played alone), cut into ``parts``:
    each place's groups and the words sung from there to the next place, as a ChordPro line is; the first part's
    groups may be none (the words before the first hole). ``text`` is the line as written (tabs expanded), ``line``
    its place in the tab; ``confidence``, its own P × T; a row not ``trusted`` is shown as written, its words too."""

    groups: list[Group]
    lyric: str | None
    label: str | None = None
    unknown: list[str] = field(default_factory=list)
    parts: list[tuple[list[Group], str]] = field(default_factory=list)
    placement: Counter = field(default_factory=Counter)  # "snap", "split", "held", "gap": how each found its place
    text: str = ""
    line: int = -1
    confidence: float = 1.0
    trusted: bool = True
    above: bool = False  # its words written above it (a tab that writes them so, ``_above``)


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


@dataclass(frozen=True)
class Legend:
    """A tab's own legend: its lines as written, where they are (``at``, their places in the tab), and what they say
    (``symbols``; ``at`` "bare" for a hole written alone, "" where the tab writes it)."""

    lines: tuple[str, ...]
    symbols: tuple[Symbol, ...]
    at: tuple[int, ...] = ()


Item = Row | Words | Prose | Gap | Legend


@dataclass
class Section:
    label: str | None
    items: list[Item] = field(default_factory=list)

    @property
    def chorus(self) -> bool:
        return bool(self.label and _CHORUS.search(self.label))


@dataclass(frozen=True)
class Reading:
    """How a tab was read: its ``notation``, where that came from (``source``: "guessed", "legend", "pinned"), the
    share of its lines of holes the notation explains (``explained``, P) and of the holes it reads a Richter harp
    plays (``playable``, T), its ``score`` (Q, weighed by the tab's legend), the ``margin`` over the best notation
    that reads it differently (``runner``), whether it is ``confident`` enough to draw, and the symbols the tab used,
    as written (``used``: ``Scan.used``'s, over its rows)."""

    notation: Notation
    source: str
    explained: float
    playable: float
    score: float
    margin: float
    runner: str | None
    confident: bool
    used: tuple[tuple[tuple[str, str, str, int], int], ...] = ()

    @property
    def q(self) -> float:
        return self.explained * self.playable

    @property
    def standard(self) -> bool:
        """Whether caracole guessed harptabs.com's own key, and the tab used nothing else: the page then says no
        more than that key's legend (the owner's choice)."""
        return self.source == "guessed" and self.notation.name == SIGNS.name and all(
            (means == SIGNS.bare) if at == "bare" else (
                (text, means, at) == (DOTS.text, DOTS.means, DOTS.at)
                or (own := SIGNS.meaning(text, at)) is not None and (own.means, own.count) == (means, count))
            for (text, means, at, count), _ in self.used)

    def said(self) -> str:
        """The symbols the tab was read by, as it writes them: "b blow · d draw · * bend · (w) wah"."""
        return " · ".join(f"{text} {word}" for text, word in self.symbols())

    def symbols(self) -> list[tuple[str, str]]:
        """The symbols the tab was read by, each as it writes it most, and what it means in words: ``("b",
        "blow")``, ``("' or b", "bend")``, ``("4", "blow")`` for a hole written alone, ``("(4)", "draw")`` for one in
        brackets."""
        return said(Counter(dict(self.used)))


@dataclass
class Tab:
    """A tab read: the tabber's notes before its first row, its sections, how it was read (``reading``), the harp's
    key its words name ("A", or None), the lines that hold holes but are shown as written (``missed``), whether it is
    a chromatic's, its ``legend`` (its blocks', together) and the page's harp chip (``harp``: "Diatonic",
    "Chromatic", or None)."""

    notes: list[str]
    sections: list[Section]
    reading: Reading
    key: str | None
    missed: list[str]
    chromatic: bool
    legend: Legend | None = None
    harp: str | None = None

    @property
    def convention(self) -> str:
        """The notation's name: "signs", "brackets", "letters"…"""
        return self.reading.notation.name

    def rows(self) -> list[Row]:
        return [item for s in self.sections for item in s.items if isinstance(item, Row)]

    @property
    def readable(self) -> bool:
        """Whether its page draws its holes, else its text as written (the module's docstring)."""
        return self.reading.confident and any(r.trusted for r in self.rows()) and not self.chromatic


# --- a notation compiled ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Tokens:
    """A notation compiled: where a hole may start (its before-symbols, then its number), one symbol of each place,
    an effect written apart, a join, holes together (``7,8B``)."""

    start: re.Pattern
    before: re.Pattern | None
    after: re.Pattern | None
    apart: re.Pattern | None
    join: re.Pattern | None
    together: re.Pattern | None


def _alt(texts, *, alone: bool = False) -> str:
    """One of ``texts``, the longest first; ``alone``: a text that starts or ends with a letter touches no other."""
    def one(t: str) -> str:
        if not alone:
            return re.escape(t)
        return ((r"(?<![^\W\d_])" if t[:1].isalpha() else "") + re.escape(t)
                + (r"(?![^\W\d_])" if t[-1:].isalpha() else ""))
    return "|".join(one(t) for t in sorted(set(texts), key=lambda t: (-len(t), t)))


@functools.lru_cache(maxsize=64)
def _tokens(notation: Notation) -> _Tokens:
    flags = re.I if notation.fold else 0

    def texts(at: str, *means: str) -> list[str]:
        return [s.text for s in notation.symbols if s.at == at and (not means or s.means in means)]

    def one(found: list[str]) -> re.Pattern | None:
        return re.compile(_alt(found), flags) if found else None

    before, after = texts("before"), texts("after")
    pre = f"(?:{_alt(before)}){{0,4}}" if before else ""
    together = texts("between", "together")
    return _Tokens(
        start=re.compile(f"(?P<pre>{pre})(?P<num>{_NUM})", flags),
        before=one(before),
        after=one(after),
        apart=(re.compile(r"(?<![^\W\d_])(?:" + _alt(texts("after", *EFFECTS, "mark"), alone=True) + ")", flags)
               if texts("after", *EFFECTS, "mark") else None),
        join=one([s.text for s in notation.symbols if s.at == "between" and s.means != "together"]),
        together=re.compile(rf"(?P<body>{_NUM}(?:(?:{_alt(together)}){_NUM})+)", flags) if together else None,
    )


@dataclass
class _Read:
    """A hole as a notation reads it: where it is, its number, and what its marks say (``breath`` None where they say
    none: the caller's brackets or the notation's bare breath decide)."""

    start: int
    end: int
    num: int
    digit: int = 0
    breath: str | None = None
    bend: int = 0
    over: bool = False
    slide: bool = False
    effects: list[str] = field(default_factory=list)
    used: list[tuple[str, Symbol]] = field(default_factory=list)


def _marks(found: list[tuple[int, int, str, Symbol]], read: _Read) -> bool:
    """Add one mark to ``read``; False when it can't take it (a second breath, a second slide, a fourth bend)."""
    _, _, text, sym = found[-1]
    if sym.means in BREATHS:
        if read.breath is not None:
            return False
        read.breath = sym.means
    elif sym.means == "bend":
        if read.bend + sym.count > 3:
            return False
        read.bend += sym.count
    elif sym.means == "over":
        if read.over:
            return False
        read.over = True
    elif sym.means == "slide":
        if read.slide:
            return False
        read.slide = True
    elif sym.means in EFFECTS:
        read.effects.append(sym.means)
    read.used.append((text, sym))
    return True


def _read_hole(text: str, m: re.Match, notation: Notation, tokens: _Tokens, limit: int) -> _Read | None:
    """The hole ``m`` (``tokens.start``) found: its before-symbols read from the number back, its after-symbols up to
    ``limit``, the longest that leaves no letter touching it; None for a number in a word ("2nd", "x2")."""
    pieces = []
    pos = m.start("pre")
    while pos < m.end("pre"):
        s = tokens.before.match(text, pos)
        pieces.append((s.start(), s.end(), s.group(), notation.meaning(s.group(), "before")))
        pos = s.end()
    read = _Read(m.start("num"), m.end("num"), int(m.group("num")), m.start("num"))
    taken: list[tuple[int, int, str, Symbol]] = []
    for piece in reversed(pieces):
        if not _marks(taken + [piece], read):
            break
        taken.append(piece)
    if taken:
        read.start = taken[-1][0]
    if read.start > 0 and text[read.start - 1].isalpha():
        return None
    before = (read.breath, read.bend, read.over, read.slide, list(read.effects), list(read.used))
    options = [(read.end, before)]
    pos = read.end
    while tokens.after is not None and pos < limit:
        s = tokens.after.match(text, pos, limit)
        sym = s and notation.meaning(s.group(), "after")
        if sym and sym.means in BREATHS and s.group() in _SIGNS and (
                (s.end() < len(text) and (text[s.end()] in _SIGNS or text[s.end()].isalnum()))
                or (read.start > 0 and text[read.start - 1].isdigit())):
            break  # 6+ 6-, never 6-7 (a sign before the 7), 6-- (a hold) nor 456- (holes glued, the sign whose?)
        if not s or not _marks([(s.start(), s.end(), s.group(), sym)], read):
            break
        pos = s.end()
        options.append((pos, (read.breath, read.bend, read.over, read.slide, list(read.effects), list(read.used))))
    for end, state in reversed(options):
        if end >= len(text) or not text[end].isalpha():
            read.end = end
            read.breath, read.bend, read.over, read.slide, read.effects, read.used = state
            return read
    return None


_BRACKET = re.compile(r"(?P<open>[(\[{])(?P<body>[^()\[\]{}]*?)(?P<close>[)\]}])")
_SEPARATOR = re.compile(r"[\s,]*")
_CLOSE = {"(": "()", "[": "[]", "{": "{}"}


def expand(line: str) -> str:
    """A line as the page lays it out: tabs to their stops, a no-break space a space."""
    return line.expandtabs(TAB_STOP).replace("\u00a0", " ")


def scan(line: str, *, notation: Notation = SIGNS) -> Scan:
    """The holes ``line`` holds as ``notation`` reads them, where, how much of it they explain, and what it couldn't
    read, kept in place."""
    text = expand(line)
    tokens = _tokens(notation)
    label = None
    lead = _LEAD_LABEL.match(text)
    if (lead and tokens.start.search(text[lead.end():]) and not lead.group("label").strip().isdigit()
            and not any(m.start() < lead.end() for m in _TIME.finditer(text))):  # "SOLO 4:24": a time, no label
        label = lead.group("label").strip("() ")
        text = " " * lead.end() + text[lead.end():]
    covered = [False] * len(text)
    used: Counter = Counter()
    groups: list[Group] = []
    prose = [False] * len(text)  # a time or the tabber's words in brackets: never holes, kept as words
    for m in _TIME.finditer(text):
        prose[m.start():m.end()] = [True] * (m.end() - m.start())
    for m in _ASIDE.finditer(text):
        if (any(_is_word(w, alone=True) for w in m.group("body").split()) and not _DECOR.fullmatch(m.group(0))
                and not (tokens.apart and tokens.apart.fullmatch(m.group(0)))):  # never "(hold)", nor a "(wah)"
            prose[m.start():m.end()] = [True] * (m.end() - m.start())

    def taken(a: int, b: int) -> bool:
        return any(covered[a:b]) or any(prose[a:b])

    def mark(a: int, b: int) -> None:
        covered[a:b] = [True] * (b - a)

    def note(read: _Read, bare: str | None = None) -> None:
        for written, sym in read.used:
            used[(written, sym.means, sym.at, sym.count)] += 1
        if bare is not None:  # its breath the notation's for a hole written alone
            used[("", bare, "bare", 1)] += 1

    # Holes in brackets: a chord, a shake, a split, or a hole alone, its breath the brackets' where they give one.
    for m in _BRACKET.finditer(text):
        if taken(m.start(), m.end()):
            continue
        reads, pos, end = [], m.start("body"), m.end("body")
        pos = _SEPARATOR.match(text, pos, end).end()
        while pos < end:
            found = tokens.start.match(text, pos, end)
            read = found and _read_hole(text, found, notation, tokens, end)
            if not read or read.start != pos:
                break
            reads.append(read)
            pos = _SEPARATOR.match(text, read.end, end).end()
        if not reads or pos < end:
            continue
        stop = m.end()
        outer = _Read(m.start(), m.end(), 0)
        while tokens.after is not None and len(reads) == 1:  # (3)b: a mark after the brackets is their hole's
            s = tokens.after.match(text, stop)
            if not s or not _marks([(s.start(), s.end(), s.group(), notation.meaning(s.group(), "after"))], outer):
                break
            stop = s.end()
        if stop < len(text) and text[stop].isalpha():
            stop = m.end()
            outer = _Read(m.start(), m.end(), 0)
        around = notation.meaning(_CLOSE[m.group("open")], "around")
        given = around.means if around is not None and around.means in BREATHS else None
        breaths = [r.breath or outer.breath or given or notation.bare for r in reads]
        if None in breaths:
            continue
        kind = "note" if len(reads) == 1 and m.group("open") == "(" else _KINDS[m.group("open")]
        holes = tuple(Hole(r.num, b, min(r.bend + outer.bend, 3), r.over or outer.over, r.slide or outer.slide)
                      for r, b in zip(reads, breaths))
        for r, b in zip(reads, breaths):
            note(r, b if not (r.breath or outer.breath or given) else None)
        note(outer)
        if given and any(r.breath is None and outer.breath is None for r in reads):
            used[(_CLOSE[m.group("open")], given, "around", 1)] += 1
        effects = tuple(outer.effects + [e for r in reads for e in r.effects])
        if kind == "note" and given is None and reads[0].breath is None and outer.breath is None:
            # A hole alone in brackets that its notation gives no meaning to (harptabs.com's "(5)"): the hole is
            # read, the brackets are not.
            r = reads[0]
            groups.append(Group((Hole(r.num, breaths[0], r.bend, r.over, r.slide),), "note", r.start, r.digit,
                                text[r.start:r.end], "hold" in r.effects, _others(tuple(r.effects))))
            mark(r.start, r.end)
            continue
        groups.append(Group(holes, kind, m.start(), reads[0].digit, text[m.start():stop], "hold" in effects,
                            _others(effects)))
        mark(m.start(), stop)
    # Holes together, one mark for all: 7,8B.
    if tokens.together is not None:
        for m in tokens.together.finditer(text):
            if taken(m.start(), m.end()) or (m.start() and text[m.start() - 1].isalnum()):
                continue
            last = tokens.start.match(text, m.end() - len(re.search(_NUM + "$", m.group("body")).group(0)))
            read = last and _read_hole(text, last, notation, tokens, len(text))
            breath = read and (read.breath or notation.bare)
            if not read or not breath:
                continue
            nums = [int(n) for n in re.findall(_NUM, m.group("body"))]
            note(read, breath if read.breath is None else None)
            sep = re.search(r"\D+", m.group("body")).group(0)
            sym = notation.meaning(sep, "between")
            used[(sep, sym.means, "between", 1)] += len(nums) - 1
            groups.append(Group(tuple(Hole(n, breath, read.bend, read.over, read.slide) for n in nums), "chord",
                                m.start(), m.start(), text[m.start():read.end], "hold" in read.effects,
                                _others(tuple(read.effects))))
            mark(m.start(), read.end)
    # Single holes.
    pos = 0
    while (found := tokens.start.search(text, pos)) is not None:
        if taken(found.start(), found.end()):
            pos = found.start() + 1 if covered[found.start()] or prose[found.start()] else found.end()
            continue
        read = _read_hole(text, found, notation, tokens, _free_until(covered, prose, found.end()))
        if read is None:
            pos = found.end()
            continue
        breath = read.breath or notation.bare
        pos = read.end
        if breath is None:  # a hole with no breath where the notation needs one: unread, kept as written
            continue
        note(read, breath if read.breath is None else None)
        effects = tuple(read.effects)
        groups.append(Group((Hole(read.num, breath, read.bend, read.over, read.slide),), "note", read.start,
                            read.digit, text[read.start:read.end], "hold" in effects, _others(effects)))
        mark(read.start, read.end)
    groups.sort(key=lambda g: g.col)
    # Effects written apart (a legend's "(w)" after a space), and the marks every notation shares: each effect and
    # hold is the group's before it.
    if tokens.apart is not None:
        for m in tokens.apart.finditer(text):
            if taken(m.start(), m.end()):
                continue
            sym = notation.meaning(m.group(0), "after")
            mark(m.start(), m.end())
            used[(m.group(0), sym.means, "after", sym.count)] += 1
            if sym.means in EFFECTS:
                _effect_before(groups, m.start(), sym.means)
    joins = []  # notes run together, written between two with nothing apart: 3*d-3d (never a hold's ----)
    if tokens.join is not None:
        for m in tokens.join.finditer(text):
            a, b = m.start(), m.end()
            if taken(a, b) or a == 0 or b >= len(text) or text[a - 1].isspace() or text[b].isspace() \
                    or text[a - 1] == m.group(0)[0] or text[b] == m.group(0)[-1]:
                continue
            sym = notation.meaning(m.group(0), "between")
            mark(a, b)
            used[(m.group(0), sym.means, "between", 1)] += 1
            joins.append((a, sym.means))
    for m in _DECOR.finditer(text):
        if taken(m.start(), m.end()):
            continue
        mark(m.start(), m.end())
        if _HOLD.fullmatch(m.group(0)):
            _effect_before(groups, m.start(), "hold")
    # What it couldn't read, in place: the tabber's words ("BOM", "(Chorus)", "tue" against its hole, an aside in
    # brackets) as words, together where only spaces part them; anything else unread.
    for m in _WORD.finditer(text):
        a = m.start()
        for i in range(m.start(), m.end() + 1):
            if i == m.end() or covered[i]:
                if i > a:
                    alone = a == m.start() and i == m.end()
                    words = any(prose[a:i]) or _is_word(text[a:i], alone=alone)
                    groups.append(Group((), "words" if words else "unread", a, a, text[a:i]))
                a = i + 1
    groups.sort(key=lambda g: g.col)
    for n in range(len(groups) - 1, 0, -1):
        one, two = groups[n - 1], groups[n]
        if one.kind == two.kind == "words" and not text[one.end:two.col].strip():
            groups[n - 1:n + 1] = [Group((), "words", one.col, one.col, text[one.col:two.end])]
    for at, means in joins:
        before = [n for n, g in enumerate(groups) if g.col < at]
        if before:
            n = before[-1]
            groups[n] = replace(groups[n], join=True)
            if means in EFFECTS and groups[n].holes:  # x-x: a glissando from the one to the other
                _effect_before(groups, at, means)
    unknown = []
    for m in _WORD.finditer(text):
        rest = "".join(ch for i, ch in enumerate(m.group(0), m.start()) if not covered[i])
        if rest:  # nothing dropped as if read: a " left over is a bend no hole took
            unknown.append(rest)
    letters = sum(not ch.isspace() for ch in text)
    good = sum(1 for i, ch in enumerate(text) if covered[i] and not ch.isspace())
    free = sum(1 for w in _WORD.findall(text) if not re.search(r"\d", w) and sum(c.isalpha() for c in w) >= 3)
    said = sum(not ch.isspace() for g in groups if g.kind == "words" for ch in g.text)
    return Scan(tuple(groups), good / letters if letters else 0.0, tuple(unknown), label, used, free,
                said / letters if letters else 0.0, *_run(text, groups, covered))


def _is_word(text: str, *, alone: bool) -> bool:
    """Whether what a line couldn't read is the tabber's word: letters and no digit, a vowel among them, two at
    least where it stands ``alone`` (one against a hole: "(45)u"); never "SB", "z" or "X"."""
    letters = [c for c in _fold_accents(text).casefold() if c.isalpha()]
    return (not re.search(r"\d", text) and len(letters) >= (2 if alone else 1)
            and any(c in "aeiouyøæåœ" for c in letters))


def _run(text: str, groups: list[Group], covered: list[bool]) -> tuple[int, int]:
    """The most tokens holding holes a line writes one after another, and its tokens, a bar or a hold neither."""
    holed = [False] * len(text)
    for g in groups:
        if g.holes:
            holed[g.col:g.end] = [True] * (g.end - g.col)
    best = run = count = 0
    for m in _WORD.finditer(text):
        if any(holed[m.start():m.end()]):
            run += 1
            count += 1
            best = max(best, run)
        elif not all(covered[m.start():m.end()]):
            run = 0
            count += 1
    return best, count


def _free_until(covered: list[bool], prose: list[bool], start: int) -> int:
    """Where the first character from ``start`` read already, or prose, is (a hole's marks stop there)."""
    for i in range(start, len(covered)):
        if covered[i] or prose[i]:
            return i
    return len(covered)


def _others(effects: tuple[str, ...]) -> tuple[str, ...]:
    """The effects a group shows as labels: every one but a hold, which the page draws as its own."""
    out = []
    for e in effects:
        if e != "hold" and e not in out:
            out.append(e)
    return tuple(out)


def _effect_before(groups: list[Group], at: int, effect: str) -> None:
    """Give ``effect`` to the group of holes written last before column ``at``."""
    before = [n for n, g in enumerate(groups) if g.col < at and g.holes]
    if not before:
        return
    n = max(before, key=lambda k: groups[k].col)
    g = groups[n]
    if effect == "hold":
        groups[n] = replace(g, hold=True)
    elif effect not in g.effects:
        groups[n] = replace(g, effects=g.effects + (effect,))


# --- a tab's legend -------------------------------------------------------------------------------------------

# The words a legend's meanings are read by, accents folded, in no case: each meaning's, the earliest in a line wins.
_LEXICON = tuple((means, re.compile(rf"(?i)(?<![^\W\d_])(?:{words})(?![^\W\d_])")) for means, words in (
    ("blow", r"blow|blown|blowing|exhale\w*|soplar|sopla|soplo|soplad[oa]s?|blasen|geblasen|souffl\w*"),
    ("draw", r"draw|drawn|drawing|inhale\w*|suck|aspirar|aspira|aspirad[oa]s?|inspirar|ziehen|gezogen"),
    ("bend", r"bend|bends|bent|bending"),
    ("over", r"overblow\w*|overdraw\w*|over-blow\w*|over-draw\w*"),
    ("slide", r"slide|button"),
    ("hold", r"hold|held|extend\w*|sustain\w*|larg[oa]"),
    ("wah", r"wah?"),
    ("vibrato", r"vibrato|tremolo"),
    ("shake", r"shake|headshake|warble"),
    ("trill", r"trill|trino"),
    ("together", r"chord|together"),
    ("join", r"ligad[oa]|slur|legato"),
    ("glissando", r"glissando|glisando|gliss"),
    ("staccato", r"staccato"),
    ("mark", r"bar|rest|repeat|whole note|half note|quarter note|eighth note|sixteenth note|note length"),
))
_LEGEND_LINE = re.compile(
    r"^\s*(?P<sym>\([^()\s]{1,8}\)\S{0,3}|[^\s=:]{1,8}?)\s*(?P<sep>=>|->|=|:|\s[-–—]\s|\s{2,})\s*(?P<meaning>\S.*?)\s*$")
_PLACEHOLDER = re.compile(r"(?i)n[uú]mero|##?#?|(?<![a-z])x(?![a-z])|(?<![a-z])N(?![a-z])|10|[1-9]")
_TWO = re.compile(r"(?i)whole|double|two|dos\b|2")
_THREE = re.compile(r"(?i)1[.,]5|and a half|three|tres\b|3")


def _fold_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _meaning(text: str) -> str | None:
    """What a legend's meaning says, by ``_LEXICON``: the meaning its earliest word names, or None."""
    text = _fold_accents(text)
    found = [(m.start(), means) for means, pattern in _LEXICON if (m := pattern.search(text))]
    return min(found)[1] if found else None


def _entry(sym: str, meaning: str) -> Symbol | None:
    """One line of a legend as a symbol: ``(x)`` brackets, ``x`` a hole alone ("bare"), ``-x`` before it, ``x+``
    after it, ``x-x`` between two; a symbol with no placeholder ``at`` "", where the tab writes it."""
    means = _meaning(meaning)
    if means is None or _URL.search(sym) or _URL.search(meaning):
        return None
    count = 1
    if means == "bend":
        count = 3 if _THREE.search(meaning) else 2 if _TWO.search(meaning) else 1
    return _template(sym, means, count)


def _template(sym: str, means: str, count: int = 1) -> Symbol | None:
    """A symbol written with a placeholder for its hole, as a legend or a pin writes it (``_entry``), and what it
    means: placed where the placeholder says, or ``at`` "" with none; None where nothing can go."""
    found = list(_PLACEHOLDER.finditer(sym))
    if not found:
        if len(sym) > 1 and len(set(sym)) == 1 and means == "bend":  # "**": the bend "*" written twice
            return Symbol(sym[0], means, "", max(1, count // len(sym)))
        return Symbol(sym, means, "", count)
    if len(found) == 1:
        a, b = found[0].span()
        pre, post = sym[:a], sym[b:]
        if pre in _CLOSE and post.startswith(_CLOSE[pre][1]):
            post = post[1:]
            if not post:
                return Symbol(_CLOSE[pre], means, "around", count) if means in BREATHS else None
            return Symbol(post, means, "after", count)
        if not pre and not post:
            return Symbol("", means, "bare") if means in BREATHS else Symbol(sym, means, "", count)
        if pre and (not post or means in BREATHS):  # -4 = draw; -4' = bend is the ' after
            return Symbol(pre, means, "before", count)
        return Symbol(post, means, "after", count)
    between = sym[found[0].end():found[1].start()].strip("()[]{}")
    return (Symbol(between, means, "between")
            if len(found) == 2 and between and means in ("join", "together", *EFFECTS) and means != "hold" else None)


def legend(lines: list[str]) -> list[Legend]:
    """The tab's legends: each block of two or more adjacent lines that read ``SYM = meaning`` (or ``:``, ``-``,
    columns), two of them at least with a meaning ``_LEXICON`` reads; never "Key: D" or an address."""
    blocks: list[list[tuple[int, Symbol | None]]] = []
    run: list[tuple[int, Symbol | None]] = []
    for n, line in enumerate(lines + [""]):
        m = _LEGEND_LINE.match(line) if line.strip() and not _URL.search(line) else None
        if m and "=" not in m.group("sep") and m.group("sym").isalpha() and len(m.group("sym")) > 2:
            m = None  # "Chorus: hold on", "Hey  hold  me": a word, not a symbol, before a colon or spaces
        if m:
            run.append((n, _entry(m.group("sym"), m.group("meaning"))))
            continue
        if sum(s is not None for _, s in run) >= 2:
            while run and run[-1][1] is None:
                run.pop()
            while run and run[0][1] is None:
                run.pop(0)
            blocks.append(run)
        run = []
    return [Legend(tuple(lines[n].rstrip() for n, _ in block),
                   tuple(dict.fromkeys(s for _, s in block if s is not None)), tuple(n for n, _ in block))
            for block in blocks]


def _where(sym: Symbol, lines: list[str]) -> Symbol | None:
    """A legend's symbol placed where the tab's lines of holes write it (an effect after its hole; a mark before a
    hole when it is written right before one more often than after one), or None when they never write it."""
    if sym.at == "bare":
        return sym
    if sym.at == "around":
        return sym if any(re.search(rf"\({_NUM}\)", line) for line in lines) else None
    flags = re.I if any(c.isalpha() for c in sym.text) else 0
    pattern = re.compile(re.escape(sym.text), flags)
    hits = [(line, m.start(), m.end()) for line in lines for m in pattern.finditer(line)]
    if not hits:
        return None
    if sym.at:
        return sym
    if sym.means in EFFECTS or sym.means == "mark":
        return replace(sym, at="after")
    before = sum(1 for line, _, b in hits if re.match(rf"[-+−–]?{_NUM}", line[b:b + 3]))
    after = sum(1 for line, a, _ in hits if re.search(r"\d\S{0,2}$", line[max(0, a - 3):a]))
    return replace(sym, at="before" if before > after else "after")


def _agrees(notation: Notation, sym: Symbol) -> bool:
    """Whether ``notation`` reads the legend's ``sym`` as the legend says."""
    if sym.at == "bare":
        return notation.bare == sym.means
    own = notation.meaning(sym.text, sym.at) or (notation.meaning(sym.text.swapcase(), sym.at)
                                                 if notation.fold else None)
    if sym.means == "mark":
        return (own is not None and own.means == "mark") or (own is None and bool(_DECOR.fullmatch(sym.text)))
    return own is not None and own.means == sym.means and (sym.means != "bend" or own.count == sym.count)


def _with_legend(found: tuple[Symbol, ...], lines: list[str]) -> tuple[Notation, tuple[Symbol, ...]] | None:
    """The preset that agrees with most of a legend's symbols the tab uses (``found``, placed), changed as it says:
    a letter it writes in one case and the tab in the other read in both."""
    if not found:
        return None
    base = max(PRESETS, key=lambda n: (sum(_agrees(n, s) for s in found), -PRESETS.index(n)))
    changes: list[Symbol] = []
    bare = ""
    text = "\n".join(lines)
    for sym in found:
        if sym.at == "bare":
            bare = sym.means
            continue
        changes.append(sym)
        if not base.fold and sym.text != sym.text.swapcase() and sym.text.swapcase() in text:
            changes.append(replace(sym, text=sym.text.swapcase()))
    return base.changed(tuple(changes), bare=bare), found


def _agreement(notation: Notation, found: tuple[Symbol, ...]) -> float:
    return sum(_agrees(notation, s) for s in found) / len(found) if found else 0.0


# --- which notation --------------------------------------------------------------------------------------------


def _playable(hole: Hole, harp_chip: str | None) -> bool:
    if hole.button:
        return harp_chip != "Diatonic"
    return harp.hole_note(0, hole.hole, hole.breath, hole.bend, hole.over) is not None


def _signature(scans: list[Scan]) -> tuple:
    return tuple(tuple((g.kind, g.holes) for g in s.holes) for s in scans)


def read(lines: list[str], *, harp_chip: str | None = None, notation: Notation | None = None,
         legends: list[Legend] | None = None) -> tuple[Reading, list[Scan]]:
    """How the tab's ``lines`` (tabs expanded, its legends' lines left out) are best read, and each line as that
    notation reads it: the module's docstring. ``notation`` given is read as it is ("pinned")."""
    if notation is not None:
        candidates, found = [(notation, "pinned")], ()
    else:
        candidates, found = _candidates(lines, harp_chip, legends or [])
    weighed = _weighed(lines, candidates, harp_chip, found)
    k = max(weighed.results, key=lambda r: (r[0], -r[1]))[1]
    return weighed.reading(k), weighed.scanned[k]


def _candidates(lines: list[str], harp_chip: str | None,
                legends: list[Legend]) -> tuple[list[tuple[Notation, str]], tuple[Symbol, ...]]:
    """The notations a tab is read under, the commonest first, each with its source, and its legends' symbols placed
    (``found``, what each candidate's agreement is counted against): the legend's own candidate, the presets
    (``STAR_BENDS`` before ``signs`` where the chip says Diatonic), each with ``DOTS`` where a dot comes before a
    hole."""
    holey = [line for line in lines if re.search(r"\d", line)]
    placed = tuple(dict.fromkeys(s for legend_ in legends for sym in legend_.symbols
                                 if (s := _where(sym, holey)) is not None))
    candidates: list[tuple[Notation, str]] = []
    found: tuple[Symbol, ...] = ()
    made = _with_legend(placed, holey)
    if made is not None:
        found = made[1]
        candidates.append((made[0], "legend"))
    for preset in PRESETS:  # where the chip says Diatonic, "*" a bend before a slide: the commoner there
        if preset is SIGNS and harp_chip == "Diatonic":
            candidates.append((STAR_BENDS, "guessed"))
        candidates.append((preset, "guessed"))
    if _dotted(lines):  # "the dots extend the note"
        candidates = [(n.changed((DOTS,)), source) for n, source in candidates]
    return candidates, found


def _dotted(lines: list[str]) -> bool:
    return any(_DOT_BEFORE.search(line) for line in lines)


@dataclass
class _Weighed:
    """Each candidate's scans of the tab's lines, the lines scored, and its result: ``(score, k, explained,
    playable, signature)``, ``k`` its place among the candidates."""

    candidates: list[tuple[Notation, str]]
    scanned: list[list[Scan]]
    scored: list[int]
    results: list[tuple[float, int, float, float, tuple]]

    def reading(self, k: int) -> Reading:
        """The candidate ``k``'s reading: its margin over the best that reads the tab differently, and whether a
        commoner one that does is within ``MARGIN`` of it."""
        score, _, explained, playable, signature = self.results[k]
        rivals = [r for r in self.results if r[4] != signature]
        runner = max(rivals, key=lambda r: (r[0], -r[1])) if rivals else None
        thin = any(r[1] < k and score - r[0] < MARGIN for r in rivals)
        used: Counter = Counter()
        for i in self.scored:
            used.update(self.scanned[k][i].used)
        n, source = self.candidates[k]
        return Reading(n, source, explained, playable, score, score - runner[0] if runner else score,
                       self.candidates[runner[1]][0].name if runner else None,
                       source == "pinned" or (explained * playable >= TAB_Q and not thin),  # a pin is yours
                       tuple(sorted(used.items())))


def _weighed(lines: list[str], candidates: list[tuple[Notation, str]], harp_chip: str | None,
             found: tuple[Symbol, ...]) -> _Weighed:
    """Each candidate scored on the tab's lines: Q = P × T, weighed by the legend's ``found`` symbols."""
    scanned = [[scan(line, notation=n) if line.strip() else Scan((), 0.0, ()) for line in lines]
               for n, _ in candidates]
    scored = [i for i in range(len(lines)) if any(s[i].is_row or s[i].missed for s in scanned)]
    sizes = {i: sum(not ch.isspace() for ch in lines[i]) for i in scored}
    # the tabber's words in a line of holes aside, the most any candidate finds (a notation that can't read "(3)"
    # can't tell "tue" after it), the same for every candidate, so each is judged on the same text
    said = {i: max(s[i].prose for s in scanned) * sizes[i] for i in scored}
    results = []
    for k, (n, source) in enumerate(candidates):
        chars = sum(sizes[i] - said[i] for i in scored)
        explained = min(1.0, sum(scanned[k][i].coverage * sizes[i] for i in scored) / chars) if chars else 0.0
        holes = [h for i in scored for g in scanned[k][i].holes for h in g.holes]
        playable = sum(_playable(h, harp_chip) for h in holes) / len(holes) if holes else 0.0
        weight = 1 + LEGEND_WEIGHT * _agreement(n, found) if found else 1.0
        results.append((explained * playable * weight, k, explained, playable,
                        _signature([scanned[k][i] for i in scored])))
    return _Weighed(candidates, scanned, scored, results)


# --- a reading pinned: overrides.toml's [harmonica] -----------------------------------------------------------

PIN_NAMES = (*(p.name for p in PRESETS), "legend")  # what a pin may name: a preset, or the tab's own legend
# What a pin's table says a symbol means, in words: MEANINGS, a bend of two or three semitones, an overblow.
_PIN_WORDS = {**{m: (m, 1) for m in MEANINGS}, "double bend": ("bend", 2), "triple bend": ("bend", 3),
              "overblow": ("over", 1), "joins": ("join", 1)}


def _names(names, last: str = "or") -> str:
    *rest, end = names
    return f"{', '.join(rest)} {last} {end}" if rest else end


def _pin_symbol(key: Any, word: Any) -> Symbol:
    """A pin's table entry as a symbol: ``key`` the symbol, a "4" (or an "x") standing for its hole where it says
    where it is written ("(4)", "4", "b4", "4-4"), else where the tab writes it; ``word`` what it means
    (``_PIN_WORDS``). Raises ValueError, saying what it takes."""
    if not isinstance(key, str) or not key.strip() or key != key.strip() or len(key) > 12:
        raise ValueError(f"expected a symbol, as the tab writes it, got {key!r}")
    if not isinstance(word, str) or word not in _PIN_WORDS:
        raise ValueError(f"{key!r}: expected what a symbol means ({_names(list(_PIN_WORDS))}), got {word!r}")
    means, count = _PIN_WORDS[word]
    sym = _template(key, means, count)
    if sym is None:
        raise ValueError(f"{key!r}: a hole alone, or in brackets, can only be a blow or a draw")
    return sym


def check_spec(spec: Any) -> None:
    """Whether ``spec`` can be a pin: a notation's name (``PIN_NAMES``), or a table, ``as`` a preset (signs by
    default) and each other entry a symbol and what it means (``_pin_symbol``). Raises ValueError, saying what it
    takes."""
    if isinstance(spec, str):
        if spec not in PIN_NAMES:
            raise ValueError(f"expected {_names(PIN_NAMES)}, got {spec!r}")
        return
    if not isinstance(spec, Mapping):
        raise ValueError(f"expected a notation's name or a table of what its symbols mean, got {spec!r}")
    base = spec.get("as", SIGNS.name)
    if base not in PRESET:
        raise ValueError(f"as: expected {_names(list(PRESET))}, got {base!r}")
    for key, word in spec.items():
        if key != "as":
            _pin_symbol(key, word)


def pinned(spec: Any, body: str) -> Notation | None:
    """The notation the pin ``spec`` names for the tab ``body`` (``check_spec``'s): a preset; the tab's own
    legend's (None for a tab with none); or a preset changed as the table says, each symbol placed as a legend's is,
    in either case where it is a letter the tab writes in the other. With ``DOTS`` where a dot comes before a hole, as
    every candidate has them. Raises ValueError for a spec ``check_spec`` refuses."""
    check_spec(spec)
    _, lines, legends, in_legend = _prepared(body, None)
    lines = ["" if n in in_legend else line for n, line in enumerate(lines)]
    holey = [line for line in lines if re.search(r"\d", line)]
    if spec == "legend":
        placed = tuple(dict.fromkeys(s for legend_ in legends for sym in legend_.symbols
                                     if (s := _where(sym, holey)) is not None))
        made = _with_legend(placed, holey)
        notation = made[0] if made is not None else None
    elif isinstance(spec, str):
        notation = PRESET[spec]
    else:
        placed = tuple(s for key, word in spec.items() if key != "as"
                       if (s := _where(_pin_symbol(key, word), holey)) is not None)
        base = PRESET[spec.get("as", SIGNS.name)]
        bare = next((s.means for s in placed if s.at == "bare"), "")
        text = "\n".join(holey)
        changes = [s for s in placed if s.at != "bare"]
        changes += [replace(s, text=s.text.swapcase()) for s in changes
                    if not base.fold and s.text != s.text.swapcase() and s.text.swapcase() in text]
        notation = base.changed(tuple(changes), bare=bare)
    if notation is not None and _dotted(lines):
        notation = notation.changed((DOTS,))
    return notation


def readings(body: str, *, harp: str | None = None) -> list[Reading]:
    """Every reading caracole weighs for the tab ``body`` (``harp``, the page's chip), best first: one a way of
    reading it (two candidates that read every hole alike and say so alike are one, the better, else the
    commoner); the first is ``parse``'s."""
    chip, lines, legends, in_legend = _prepared(body, harp)
    lines = ["" if n in in_legend else line for n, line in enumerate(lines)]
    candidates, found = _candidates(lines, chip, legends)
    weighed = _weighed(lines, candidates, chip, found)
    out: dict[tuple, Reading] = {}
    for _, k, *_rest in sorted(weighed.results, key=lambda r: (-r[0], r[1])):
        reading = weighed.reading(k)
        out.setdefault((weighed.results[k][4], reading.said()), reading)
    return list(out.values())


def spec_of(reading: Reading) -> str | dict[str, str]:
    """The pin that reads a tab as ``reading`` does: "legend" for its legend's, a preset's name, or a table of the
    preset and what changes it (a symbol after a hole written alone, another with a 4 for its hole)."""
    if reading.source == "legend":
        return "legend"
    notation = reading.notation
    base = PRESET[notation.name]
    changed = [s for s in notation.symbols if s != DOTS and s not in base.symbols]
    if not changed and notation.bare == base.bare:
        return notation.name
    spec = {"as": notation.name}
    if notation.bare != base.bare and notation.bare is not None:
        spec["4"] = notation.bare
    for s in changed:
        key = {"before": f"{s.text}4", "around": f"{s.text[:1]}4{s.text[1:]}", "between": f"4{s.text}4"}.get(
            s.at, s.text)
        spec[key] = s.means if s.means != "bend" or s.count == 1 else ("double bend", "triple bend")[s.count - 2]
    return spec


_SAY = {"over": "overblow", "join": "joins"}
_ORDER = ("bare", "before", "around", "after", "between")


def said(used: Counter) -> list[tuple[str, str]]:
    """The symbols ``used`` (``Scan.used``'s), each as the tab writes it most, and what it means in words:
    ``[("4", "blow"), ("-", "draw"), ("' or b", "bend"), ("(w)", "wah")]``."""
    entries: dict[tuple[str, str, int], Counter] = {}
    for (text, means, at, count), times in used.items():
        if means != "mark":
            entries.setdefault((means, at, count), Counter())[text] += times
    rank = {m: n for n, m in enumerate(MEANINGS)}

    def order(key: tuple[str, str, int]) -> tuple:
        means, at, count = key
        return (0, _ORDER.index(at), rank[means]) if means in BREATHS else (1, rank[means], count)

    out = []
    for key in sorted(entries, key=order):
        means, at, count = key
        spelled: dict[str, Counter] = {}
        for text, times in entries[key].items():
            spelled.setdefault(text.casefold(), Counter())[text] += times
        shown = [max(spelled[t].items(), key=lambda kv: (kv[1], kv[0] == kv[0].lower()))[0]
                 for t in sorted(spelled, key=lambda t: (-spelled[t].total(), t))]
        word = (("bend", "double bend", "triple bend")[min(count, 3) - 1] if means == "bend"
                else _SAY.get(means, means))
        text = "4" if at == "bare" else "(4)" if shown == ["()"] else " or ".join(shown)
        out.append((text, word))
    return out


# --- the tab --------------------------------------------------------------------------------------------------


def _row_confidence(found: Scan, harp_chip: str | None) -> float:
    """A row's own P × T: the share of it its notation explains, times the share of its holes a harp plays."""
    holes = [h for g in found.holes for h in g.holes]
    return found.explained * (sum(_playable(h, harp_chip) for h in holes) / len(holes) if holes else 0.0)


def _prepared(body: str, harp: str | None) -> tuple[str | None, list[str], list[Legend], set[int]]:
    """A tab's text as it is read: the page's chip as caracole reads it ("Diatonic", "Chromatic", or None), its
    lines (tabs expanded), its legends, and their lines' places."""
    chip = next((name for name, pattern in _CHIPS.items() if harp and pattern.search(harp)), None)
    lines = [expand(line).rstrip() for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    legends = legend(lines)
    return chip, lines, legends, {n for block in legends for n in block.at}


def parse(body: str, *, harp: str | None = None, notation: Notation | None = None) -> Tab:
    """The tab ``body`` (a ``harmonica-N.txt``) read: the module's docstring says how. ``harp`` is the page's chip
    ("Diatonic", "Chromatic"), ``notation`` one to read it by, whatever the others score ("pinned")."""
    chip, lines, legends, in_legend = _prepared(body, harp)
    reading, scans = read(["" if n in in_legend else line for n, line in enumerate(lines)], harp_chip=chip,
                          notation=notation, legends=legends)
    kinds = ["legend" if n in in_legend else "blank" if not line.strip() else "holes" if s.is_row
             else "missed" if s.missed else "text" for n, (line, s) in enumerate(zip(lines, scans))]

    above = _above(lines, kinds, scans)
    notes: list[str] = []
    sections = [Section(None)]
    seen_row = False
    block: list[str] = []
    last_text = -1  # the line block's last is

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
        if kind == "legend":
            flush()
            here = next(b for b in legends if i in b.at)
            sections[-1].items.append(here)
            i = here.at[-1] + 1
            continue
        if kind == "holes" or (kind == "missed" and seen_row):  # before the first row, a line of the notes
            found = scans[i]
            lyric = None
            if above:  # the line just above it, unless it is a section's name, a row's or the tabber's notes' end
                if last_text == i - 1 and block and _sung(lines[i - 1], scans[i - 1]):
                    block.pop()
                    lyric = lines[i - 1]
            elif i + 1 < len(lines) and kinds[i + 1] == "text" and _sung(lines[i + 1], scans[i + 1]):
                lyric = lines[i + 1]
            flush()
            label = found.label
            if label and _is_label(label + ":"):
                sections.append(Section(label))
                label = None
            confidence = _row_confidence(found, chip)
            row = Row(list(found.groups), lyric, label, list(found.unknown), text=line, line=i, confidence=confidence,
                      trusted=kind == "holes" and confidence >= ROW_TRUST, above=above and lyric is not None)
            align(row)
            sections[-1].items.append(row)
            seen_row = True
            i += 2 if lyric is not None and not above else 1
            continue
        beside = any(0 <= j < len(kinds) and kinds[j] in ("holes", "missed") for j in (i - 1, i + 1))
        if _is_label(line, beside_row=beside) and (seen_row or _LABEL_WORDS.search(line)):
            flush()
            sections.append(Section(_label_text(line)))
        else:
            block.append(line if seen_row else line.strip())
            last_text = i
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
    missed = [lines[n].strip() for n, kind in enumerate(kinds)
              if kind == "missed" or (kind == "holes" and not any(r.line == n and r.trusted for r in rows))]
    chromatic = chip == "Chromatic" or any(h.button for r in rows if r.trusted for g in r.groups for h in g.holes)
    together = Legend(tuple(line for b in legends for line in b.lines), tuple(s for b in legends for s in b.symbols),
                      tuple(n for b in legends for n in b.at)) if legends else None
    return Tab(notes, sections, reading, named_key(prose), missed, chromatic, together, chip)


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


_VOWEL_RUN = re.compile(r"[aeiouyøæåœ]+")


def _syllables(line: str) -> int:
    """A line's syllables, near enough: its runs of vowels, accents folded ("Øl, øl og mere øl.": 6)."""
    return len(_VOWEL_RUN.findall(_fold_accents(line).casefold()))


def _above(lines: list[str], kinds: list[str], scans: list[Scan]) -> bool:
    """Whether a tab writes each row's words above it, not under it: the lines of words above its rows fit them,
    syllables to holes, better than those below, by ``ABOVE_LEAD`` and ``ABOVE_SHARE`` of its rows at least. A line
    of words is one most of whose tokens hold two letters or more (not 8834's note lengths, "h q q"), no section's
    name, no address and no line of holes."""
    def fit(j: int, holes: int) -> float:
        if not (0 <= j < len(lines) and kinds[j] == "text" and _sung(lines[j], scans[j])):
            return 0.0
        tokens = lines[j].split()
        if 2 * sum(sum(c.isalpha() for c in t) >= 2 for t in tokens) < len(tokens):
            return 0.0
        found = _syllables(lines[j])
        return 1 - abs(found - holes) / max(found, holes) if max(found, holes) else 0.0

    rows = [n for n, kind in enumerate(kinds) if kind == "holes"]
    up = sum(fit(n - 1, len(scans[n].holes)) for n in rows)
    down = sum(fit(n + 1, len(scans[n].holes)) for n in rows)
    return up - down >= max(ABOVE_LEAD, ABOVE_SHARE * len(rows))


def _sung(line: str, found: Scan) -> bool:
    """Whether a line of text by a row may be its words: no section's name, no address, no line of holes."""
    return not _is_label(line, beside_row=True) and not _URL.search(line) and not found.holey


def _is_label(line: str, *, beside_row: bool = False) -> bool:
    """Whether a line names a section: "[Bridge]", "Chorus", "Verse 2", "fade:". Right above or below a row
    (``beside_row``), a line that starts as one but goes on in words ("End of the road", "Break my heart") is sung."""
    words = line.split()
    stripped = line.strip()
    if not words or len(stripped) > 32 or _URL.search(stripped):
        return False
    if re.fullmatch(r"\[[^\]]+\]|\([^)]+\)", stripped) and len(words) <= 4:
        return True
    if _LABEL_WORDS.search(stripped) and len(words) <= 4 and (
            not beside_row or ":" in stripped or not _LABEL_REST.sub("", stripped).strip()):
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
    docstring); a row played alone is one part, and a row shown as written none."""
    if not row.trusted:
        row.parts = []
        return
    if row.lyric is None:
        row.parts = [(list(row.groups), "")] if row.groups else []
        return
    lyric = row.lyric.rstrip()
    starts = syllable_starts(lyric)
    words = [(w.start(), w.end()) for w in _WORD.finditer(lyric)]
    groups = [g for g in row.groups if g.holes]  # what it couldn't read goes with them, after
    pairs = sorted(  # the nearest first; of two as near, the one written at or after the start
        (min(abs(s - g.col), abs(s - g.digit)), g.digit < s, s, n)
        for n, g in enumerate(groups) for s in starts if min(abs(s - g.col), abs(s - g.digit)) <= reach)
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
        inside = [n for n, g in enumerate(groups) if n not in at_of and a < g.digit < b and lyric[g.digit].isalpha()]
        if not inside:
            continue
        fixed = sorted({a, b} | {t for t in taken if a < t < b})
        for n, cut in zip(inside, _cuts(lyric, (a, b), [groups[n].digit for n in inside], fixed)):
            if cut is not None:
                at_of[n] = cut
                taken.add(cut)
                placement["split"] += 1
    for n, g in enumerate(groups):
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
    place = {id(g): at_of[n] for n, g in enumerate(groups)}
    for g in row.groups:  # what it couldn't read: with the hole it touches after it, else the one before it
        if not g.holes:
            after = next((h for h in groups if h.col == g.end), None)
            before = [h for h in groups if h.col < g.col]
            place[id(g)] = place[id(after or (before[-1] if before else groups[0]))]
    places: dict[int, list[Group]] = {}
    for g in row.groups:
        places.setdefault(place[id(g)], []).append(g)
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
