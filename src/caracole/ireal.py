"""iReal Pro's forum: chord charts of jazz standards, kept as a song's sheet when the sheet sites have none.

forums.irealpro.com is the forum of iReal Pro, the app that plays a song's chord chart: its users post charts there,
one song a thread or a playlist of many, as links the app opens (``irealb://…``). It is where jazz standards are
charted, which Ultimate Guitar and LaCuerda chart badly or not at all, and its "Jazz 1460 Standards" thread holds a
playlist of 1,460 of them, curated by the forum's moderators. caracole indexes its sitemaps' threads, reads the jazz
forum's playlist threads (ireal_index.py), matches your songs to its charts by title and composer (or the Jazz 1460's
by title alone), and keeps the best one as the song's sheet (ireal_fetch.py). What the site answered on 18 November 2026, asked with caracole's own user agent
(``config.DEFAULT_USER_AGENT``): robots.txt, the sitemap index and its six children, the jazz forum's first page and
three thread pages, all 200, from Apache on Ubuntu (XenForo 2.3), no bot protection seen:

- **robots.txt** gives its ``User-agent: *`` group no Crawl-delay and closes ``/search/``, ``/login/``,
  ``/register/``, ``/members/``, ``/whats-new/``, ``/misc/``, ``/find-new/`` and ``/account/`` (``http.ROBOTS_DISALLOW``);
  it names the sitemap index, ``SITEMAP_URL``.
- **The sitemaps**: an index of six children, ``/sitemap-1.xml`` to ``/sitemap-6.xml`` (``sitemap_child``), 50,000
  URLs each at most, about 26 MB together, each closed by its end tag. The first lists the home page, the forums,
  the tags and every thread, ``/threads/<slug>.<id>/`` (13,071), then members, whom the others list too. A song's
  thread is named for its title and its composer ("groove-merchant-thad-jones.9518"), a playlist's for itself
  ("jazz-1460-standards.12753"): a slug can't be split into the two by itself, so a title meets the threads whose
  slug begins with its words (``begins_with``), and the page says the rest.
- **A thread page** (``parse_thread_page``) is server-rendered: its title in its ``<h1>``, its forum in its
  breadcrumbs, and each post an ``<article>`` whose body holds its charts as links, ``irealb://`` (or the older
  ``irealbook://``, unscrambled), in the page itself, to anyone: no login, no script. One link holds one tune or a
  playlist of many, ``===`` between them, the playlist's name last. A link quoted in a reply is the post's it quotes,
  never the reply's.
- **A tune** (``Tune``) is ``title=composer=(style2)=style=key=(transpose)=music[=comp style=tempo=repeats]``
  (``irealbook://``: ``title=composer=style=key=n=music``). Its music, after the magic ``1r34LbKcu7``, is scrambled in
  blocks of 50 characters as the open-source readers document (pyRealParser, ireal-reader: ``unscramble``), then
  ``XyQ`` stands for three spaces, ``LZ`` for " |" and ``Kcl`` for "| x". What it reads (``chart``): bar lines
  ``| [ ] { } Z``, sections ``*A``, the time ``T44``, endings ``N1``, ``x`` the bar before again, ``r`` the two bars
  before, an empty bar the last chord before it held on, ``n`` no chord, ``Q`` coda, ``S`` segno, ``<…>`` a comment,
  chords such as ``C^7 D-7 G7b9 Bb/Ab`` and the app's own ``C*-^*`` (``chord_name``), and what only the app's layout
  reads (``Y``, ``s``, ``l``, ``p``, ``U``, ``f``, ``,``, an alternative chord in parentheses), which a sheet leaves out.
  A tune none of whose music reads as a chord, or with more than ``UNREAD_MOST`` characters that read as nothing (a
  link cut short inside a block leaves it scrambled), is ``IRealParseError``: the decoder raises nothing else, on any
  input. The composer is written last name first, "Jones Thad" (``composer_name``).
- **The jazz forum's page** (``parse_forum_page``, ``/forums/jazz.6/``) lists its threads, its playlists first,
  sticky: the Jazz 1460 Standards, its New 50 and individual songs, gypsy jazz, Dixieland, fusion, contemporary jazz.
- **Its terms** (``/help/terms/``) say nothing of bots, scraping or reading; posters keep their copyright. No
  ``/ai.txt``, no ``/llms.txt``. The app is paid; the forum's charts are free to anyone, and caracole draws its own
  chord grid, none of the app's paid parts (its backing tracks, its playback).

A page without the expected markup is ``IRealParseError``: a provider error, never a miss.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, NamedTuple

from selectolax.lexbor import LexborHTMLParser, LexborNode

from caracole.http import ProviderError
from caracole.normalize import clean_title, fold, slug_key, ug_slug_key

PROVIDER = "ireal"
HOST = "forums.irealpro.com"
BASE_URL = f"https://{HOST}"
SITEMAP_URL = f"{BASE_URL}/sitemap.php"
MAGIC = "1r34LbKcu7"  # what an irealb:// tune's music starts with
JAZZ_1460 = "threads/jazz-1460-standards.12753/"  # the moderators' playlist of 1,460 standards
PLAYLIST_FORUMS = ("forums/jazz.6/",)  # the forums whose sticky threads are playlists caracole reads
BARS_A_LINE = 4  # a sheet's line of a chart: four bars, as the app lays them out
UNREAD_MOST = 3  # characters of a tune's music that read as nothing it may hold: past them, it is garbled

_THREAD = re.compile(r"threads/([a-z0-9_-]{1,250})\.([1-9][0-9]{0,9})/")
_PAGE = re.compile(rf"https://{re.escape(HOST)}/({_THREAD.pattern})")
# A thread's page as its address or its canonical link names it: its first, a later one, or a post's address.
_ANY_PAGE = re.compile(rf"https://{re.escape(HOST)}/({_THREAD.pattern})(?:page-[1-9][0-9]{{0,5}}|post-[1-9][0-9]{{0,11}})?")
_FORUM = re.compile(r"forums/[a-z0-9_-]{1,200}\.[1-9][0-9]{0,9}/")
_CHILD = re.compile(rf"https://{re.escape(HOST)}/(sitemap-[1-9][0-9]{{0,2}})\.xml")
_SCHEMES = ("irealb", "irealbook")
_TRAILING_ARTICLE = re.compile(r"^(.*\S)\s*,\s*(the|a|an)\s*$", re.IGNORECASE)
_ARTICLES = ("the-", "a-", "an-")
_POST_ID = re.compile(r"post-([1-9][0-9]{0,11})")


class IRealParseError(ProviderError):
    """A page of iReal Pro's forum without the expected markup: a provider error, never a miss."""

    def __init__(self, message: str, *, url: str | None = None):
        super().__init__(PROVIDER, url=url, message=message)


# --- URLs and the index --------------------------------------------------------------------------------------------


def page_url(path: str) -> str:
    """The address of a page, from its path as the index keeps it (``threads/groove-merchant-thad-jones.9518/``)."""
    return f"{BASE_URL}/{path}"


def sitemap_child(url: str) -> str | None:
    """The name of a child sitemap the index lists (``sitemap-1``); None for any other URL."""
    m = _CHILD.fullmatch(url)
    return m.group(1) if m else None


class IndexRow(NamedTuple):
    """One thread of the sitemaps, as ``ireal_index`` keeps it: its path, its id, its slug, and its slug's key
    (``slug_key_of``), which a title's key begins."""

    path: str
    thread: int
    slug: str
    key: str


def slug_key_of(slug: str) -> str:
    """A thread slug's key: as Ultimate Guitar's slugs are keyed (``ug_slug_key``), an underscore a hyphen, less a
    leading article, as ``title_key`` reads a title."""
    return _less_article(ug_slug_key(slug.replace("_", "-")))


def parse_page_url(url: str) -> IndexRow | None:
    """The index row of a thread's page; None for any other URL (a forum, a tag, a member, a thread's next page),
    or a slug without a key."""
    m = _PAGE.fullmatch(url)
    if m is None:
        return None
    path, slug, thread = m.groups()
    key = slug_key_of(slug)
    return IndexRow(path, int(thread), slug, key) if key else None


def thread_of(path: str) -> int | None:
    """A thread page's id, from its path; None for another path."""
    m = _THREAD.fullmatch(path)
    return int(m.group(2)) if m else None


def _less_article(key: str) -> str:
    for article in _ARTICLES:
        if key.startswith(article) and len(key) > len(article):
            return key[len(article):]
    return key


def title_key(title: str) -> str:
    """The key a song's title meets a chart's title and a thread's slug with: its version suffixes go first
    (``clean_title``), and an article, whether iReal Pro writes it last ("Girl From Ipanema, The") or a title first
    ("A Night in Tunisia")."""
    cleaned = clean_title(title)
    m = _TRAILING_ARTICLE.match(cleaned)
    if m:
        cleaned = f"{m.group(2)} {m.group(1)}"
    return _less_article(slug_key(cleaned))


def begins_with(key: str, title: str) -> bool:
    """Whether a slug's key begins with a title's key, whole words alone: "misty-erroll-garner" with "misty", never
    "mistyc-dreams"."""
    return bool(key and title) and (key == title or key.startswith(title + "-"))


# --- a tune and its chart ------------------------------------------------------------------------------------------


def _obfuscate(block: str) -> str:
    out = list(block)
    for i in (*range(5), *range(10, 24)):
        out[49 - i], out[i] = block[i], block[49 - i]
    return "".join(out)


def unscramble(music: str) -> str:
    """An ``irealb://`` tune's music, less its magic, unscrambled: each block of 50 characters swapped end for end in
    two runs, but the last, and one with fewer than two characters after it. The scramble is its own inverse."""
    out = []
    while len(music) > 50:
        block, music = music[:50], music[50:]
        out.append(block if len(music) < 2 else _obfuscate(block))
    out.append(music)
    return "".join(out)


def decoded(music: str, scheme: str = "irealb") -> str:
    """A tune's music as it reads: unscrambled when it is scrambled, the app's three abbreviations written out."""
    if scheme == "irealb" and music.startswith(MAGIC):
        music = unscramble(music[len(MAGIC):])
    return music.replace("XyQ", "   ").replace("LZ", " |").replace("Kcl", "| x")


# What a chord's quality is made of, after its root: a sign first (minor-major, major, minor, half-diminished,
# diminished, augmented), then numbers, alterations, "alt", "add" and "sus" in any order.
_QUALITY = r"(?:-\^|\^|-|h|o|\+)?(?:[0-9]+|alt|add[0-9]*|sus[0-9]*|[b#][0-9]+|\^[0-9]*)*"
_CHORD = re.compile(rf"([A-GW][b#]?)({_QUALITY})(?:\*({_QUALITY})\*)?(?:/([A-G][b#]?))?")  # "C*-^*": the app's own
_SIGNS = (("-^", "mmaj"), ("^", "maj"), ("-", "m"), ("h", "m7b5"), ("o", "dim"), ("+", "aug"))


def chord_name(token: str) -> str:
    """A chord as iReal Pro writes it, named as sheets name it: "C^7" Cmaj7, "D-7" Dm7, "Bh7" Bm7b5, "Eo7" Edim7,
    "C+" Caug, "C-^7" Cmmaj7, and a quality of the app's own between asterisks as any ("C*-^*" Cmmaj); its root, its
    bass and the rest as written."""
    m = _CHORD.fullmatch(token)
    if m is None:
        return token
    root, quality, own, bass = m.groups()
    return root + _quality(quality + (own or "")) + (f"/{bass}" if bass else "")


def _quality(quality: str) -> str:
    if quality in ("^", "-^"):
        return {"^": "maj7", "-^": "mmaj7"}[quality]
    if quality in ("h", "h7"):
        return "m7b5"
    for sign, name in _SIGNS:
        if quality.startswith(sign):
            rest = quality[len(sign):].replace("^", "maj")
            if sign == "h":
                return f"m{rest}b5"
            return name + rest
    return quality.replace("^", "maj")


def composer_name(composer: str) -> str:
    """A composer as people write them: iReal Pro writes one name of two words last name first ("Jones Thad"), and
    anything else as it is ("Herbie Hancock - Stevie Wonder", "Fain-Webster")."""
    words = composer.split()
    if len(words) == 2 and " - " not in composer and "," not in composer:
        return f"{words[1]} {words[0]}"
    return " ".join(words)


def composer_words(composer: str) -> frozenset[str]:
    """The words of a composer's name, as keys word them: whichever order they come in, a song's artist is one of
    them when each of its words is here."""
    return frozenset(w for w in re.split(r"[^0-9a-z]+", fold(composer)) if w and w != "and")


def _note(text: str) -> str:
    """A comment as a note: its position digits ("*74") and its spaces gone."""
    return " ".join(re.sub(r"^\*[0-9]{2}", "", text).split())


def _time(digits: str) -> str:
    return "12/8" if digits == "12" else f"{digits[0]}/{digits[1]}"


_SECTIONS = {"i": "Intro", "v": "Verse"}
_TIME = re.compile(r"T([0-9]{2})")  # a time signature: two digits, never one at the music's end
_LAYOUT = frozenset(",lspYUf")  # what the app's layout alone reads: a sheet leaves it out


@dataclass
class _Bar:
    left: str = "|"  # the bar line before it, as a sheet writes it ("|", "||", "|:")
    right: str = "|"  # and after it ("|", "||", ":|")
    chords: list[str] | None = None
    label: str | None = None  # a section, an ending, the coda: where a line of its own begins
    notes: list[str] | None = None

    def add(self, name: str) -> None:
        self.chords = [*(self.chords or []), name]

    def note(self, text: str) -> None:
        if text:
            self.notes = [*(self.notes or []), text]


class _Reader:
    """A tune's music read into bars (``Tune.bars``)."""

    def __init__(self, music: str):
        self.bars: list[_Bar] = []
        self.time: str | None = None  # the first time signature
        self.now: str | None = None  # the one in force
        self.cur = _Bar()
        self.content = False  # the bar being read holds something (a chord, a repeat, no chord)
        self.repeat = 0  # 1: the bar before again ("x"); 2: the two bars before ("r")
        self.blank = False  # a space read since the last bar line
        self.last = "|"  # the last bar line read
        self.skip_empty = False  # the empty bar after an "r" is that repeat's second
        self.chord: str | None = None  # the last chord named, for a bass alone ("W/C")
        self.chords = 0  # the chords read (no "N.C.")
        self.unread = 0  # the characters that read as nothing: no mark, chord or layout
        self._read(music)
        self._close("")

    def _read(self, s: str) -> None:
        pos = 0
        while pos < len(s):
            c = s[pos]
            nxt = s[pos + 1] if pos + 1 < len(s) else ""
            if c == "<":
                end = s.find(">", pos)
                end = len(s) if end < 0 else end
                self.cur.note(_note(s[pos + 1:end]))
                pos = end + 1
                continue
            if c == "(":  # an alternative chord, drawn small over the bar: a sheet leaves it out
                end = s.find(")", pos)
                pos = len(s) if end < 0 else end + 1
                continue
            if c == "*" and nxt.isalpha():
                self.cur.label = _SECTIONS.get(nxt.lower(), nxt)
                pos += 2
                continue
            if c == "T" and (t := _TIME.match(s, pos)) is not None:
                time = _time(t.group(1))
                if self.time is None:
                    self.time = time
                elif time != self.now:
                    self.cur.note(time)
                self.now = time
                pos += 3
                continue
            if c == "N" and nxt in "0123456789" and nxt:
                self.cur.label = f"Ending {nxt}" if nxt != "0" else self.cur.label
                pos += 2
                continue
            if c in "|[]{}Z":
                self._bar_line(c)
                pos += 1
                continue
            m = _CHORD.match(s, pos)
            if m is not None and m.end() > pos:
                self._chord(m)
                pos = m.end()
                continue
            if c == "x":
                self.repeat, self.content = 1, True
            elif c == "r":
                self.repeat, self.content = 2, True
            elif c == "n":
                self.cur.add("N.C.")
                self.content = True
            elif c == "Q":
                if self.content:
                    self.cur.note("To Coda")
                elif self.cur.left in ("||", "|:") or not self.bars:
                    self.cur.label = "Coda"
                else:
                    self.cur.note("Coda")
            elif c == "S":
                self.cur.note("Segno")
            elif c == " ":
                self.blank = True
            elif c not in _LAYOUT:
                self.unread += 1
            pos += 1

    def _chord(self, m: re.Match[str]) -> None:
        root, _, _, bass = m.groups()
        if root == "W":  # a bass alone, under the chord before it
            if self.chord is None or not bass:
                self.unread += 1
                return
            name = self.chord.partition("/")[0] + f"/{bass}"
        else:
            name = chord_name(m.group(0).replace("**", ""))
        self.chord = name
        self.chords += 1
        self.cur.add(name)
        self.content = True

    def _bar_line(self, c: str) -> None:
        # The bar after two bars repeated ("r") is that repeat's second: empty, it is no bar of its own.
        second, self.skip_empty = self.skip_empty, False
        if self._empty(c) and not second:
            self.cur.chords = [(self.bars[-1].chords or ["N.C."])[-1]]  # the last chord before it, held on
            self.content = True
        if c in "]}Z":
            self._close({"]": "||", "}": ":|", "Z": "||"}[c])
            self.cur.left = "|"
        elif c in "[{":
            self._close("|")
            self.cur.left = {"[": "||", "{": "|:"}[c]
        else:
            self._close("|")
        self.last = c
        self.blank = False

    def _empty(self, c: str) -> bool:
        """Whether the bar line ``c`` ends an empty bar: space alone since a bar line that opens one (``|``, ``[``,
        ``{``), up to one that ends one (``|``, ``]``, ``}``, ``Z``), after a bar with a chord; never the space between
        a bar line that closes a section and one that opens the next ("Z [")."""
        return (not self.content and self.blank and self.last in "|[{" and c in "|]}Z" and bool(self.bars)
                and bool(self.bars[-1].chords))

    def _close(self, right: str) -> None:
        """The bar being read ends at a bar line written ``right``: kept when it holds something, its repeats the bars
        before it again; a bar with nothing in it keeps what it says (a section, a note) for the next."""
        bar = self.cur
        if not self.content:
            return
        bar.right = right or "|"
        if self.repeat == 1 and self.bars:
            bar.chords = list(self.bars[-1].chords or []) + list(bar.chords or [])
        if self.repeat == 2 and len(self.bars) >= 2:
            first, second = self.bars[-2], self.bars[-1]
            self.bars.append(_Bar(bar.left, "|", list(first.chords or []), bar.label, bar.notes))
            bar = _Bar("|", bar.right, list(second.chords or []))
            self.skip_empty = True
        self.bars.append(bar)
        self.cur, self.content, self.repeat = _Bar(), False, 0


def _separator(right: str, left: str) -> str:
    """The bar line between two bars of a line: one bar's end and the next one's start, written once."""
    if right == "|":
        return left
    if left == "|":
        return right
    return right + left.lstrip("|")


def _bars_text(bars: list[_Bar]) -> str:
    parts = [bars[0].left]
    for n, bar in enumerate(bars):
        parts.append(" ".join(c if c == "N.C." else f"[ch]{c}[/ch]" for c in bar.chords or []))
        parts.append(_separator(bar.right, bars[n + 1].left) if n + 1 < len(bars) else bar.right)
    return " ".join(p for p in parts if p)


@dataclass(frozen=True)
class Tune:
    """A tune of a chart link: its title, composer (last name first), style and key ("Bb", "G-" for G minor) as the
    app writes them, its music as the link gave it (scrambled, for ``irealb``), the link's scheme, its tempo (0: the
    app's own), and the name of the playlist it came in ("" for a link of one tune)."""

    title: str
    composer: str
    style: str
    key: str
    music: str
    scheme: str = "irealb"
    tempo: int = 0
    playlist: str = ""

    @property
    def tonality(self) -> str:
        """Its key as a sheet names it: "Bb", "Gm"."""
        return self.key[:-1] + "m" if self.key.endswith("-") else self.key

    @property
    def time(self) -> str:
        """Its first time signature ("4/4", "3/4"), 4/4 when the music names none; ``IRealParseError`` for music that
        won't read (``chart``)."""
        return self._read().time or "4/4"

    def _read(self) -> _Reader:
        """Its music read; ``IRealParseError`` when none of it reads as a chord, or more than ``UNREAD_MOST`` characters
        read as nothing (a link cut short inside a block leaves its end scrambled), and the one error it raises."""
        try:
            reader = _Reader(decoded(self.music, self.scheme))
        except (IndexError, KeyError, ValueError) as e:  # no input should, but the web's is anyone's to write
            raise IRealParseError(f"the chart of “{self.title}” won't read: {e}") from e
        if not reader.chords:
            raise IRealParseError(f"no chord in the chart of “{self.title}”")
        if reader.unread > UNREAD_MOST:
            raise IRealParseError(f"the chart of “{self.title}” is garbled: {reader.unread} characters read as no "
                                  f"chord or mark")
        return reader

    def chart(self) -> str:
        """The chart as a sheet in Ultimate Guitar's markup, as render.py and the viewer read a sheet (chordpro.py): a
        line of who wrote it, in what style and time; then its bars, ``BARS_A_LINE`` a line, the chords of each in
        ``[ch]…[/ch]`` between bar lines, which a sheet's page draws as cells (viewer/sheet.py ``bars``), a double bar or a
        repeat's start beginning a line too; a section, an ending or the coda a ``[label]`` over the line it begins; and a line of what its marks say (a comment, "To
        Coda", another time) under the line they are in, after a blank one. ``IRealParseError`` for a tune whose music
        won't read as a chart (``_read``)."""
        reader = self._read()
        head = " · ".join(p for p in (composer_name(self.composer), self.style, reader.time or "4/4") if p)
        out = [head, ""]
        lines: list[list[_Bar]] = []
        for bar in reader.bars:
            if not lines or bar.label or bar.left != "|" or len(lines[-1]) >= BARS_A_LINE:
                lines.append([])
            lines[-1].append(bar)
        for line in lines:
            if line[0].label:
                out.append(f"[{line[0].label}]")
            out.append(_bars_text(line))
            notes = [n for bar in line for n in bar.notes or []]
            if notes:
                out += ["", " · ".join(dict.fromkeys(notes))]
        return "\n".join(out) + "\n"

    def raw(self) -> dict[str, Any]:
        """What a kept chart's version records of it (sheet.json keeps the music too)."""
        return {"title": self.title, "composer": self.composer, "style": self.style, "key": self.key,
                "tonality_name": self.tonality, "playlist": self.playlist, "tempo": self.tempo}


def parse_link(href: str) -> tuple[Tune, ...]:
    """The tunes of a chart link, in its order, each with its playlist's name; none for a link that holds no tune, or
    no chart link."""
    scheme, sep, body = href.partition("://")
    if not sep or scheme.lower() not in _SCHEMES:
        return ()
    scheme = scheme.lower()
    parts = urllib.parse.unquote(body, errors="replace").split("===")
    playlist = parts.pop() if len(parts) > 1 and parts[-1].count("=") < 5 else ""
    tunes = []
    for part in parts:
        fields = part.split("=")
        if scheme == "irealb" and len(fields) >= 7:
            title, composer, _, style, key, _, music, *rest = fields
            tempo = rest[1] if len(rest) > 1 else ""
        elif scheme == "irealbook" and len(fields) >= 6:
            title, composer, style, key, _, music, *_ = fields
            tempo = ""
        else:
            continue
        title = " ".join(title.split())
        if not title or not music:
            continue
        tunes.append(Tune(title, " ".join(composer.split()), " ".join(style.split()), key.strip(), music, scheme,
                          int(tempo) if tempo.isdigit() and tempo.isascii() and len(tempo) < 5 else 0,
                          " ".join(playlist.split())))
    return tuple(tunes)


# --- a thread page -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Post:
    """A post of a thread: its id and the tunes its charts hold, in their order (none quoted from another post)."""

    post: int
    tunes: tuple[Tune, ...] = ()


@dataclass(frozen=True)
class ThreadPage:
    """A thread's first page: its path, its id, its title, its forum's path ("" when the page names none) and its
    posts."""

    path: str
    thread: int
    title: str
    forum: str
    posts: tuple[Post, ...]

    def charts(self):
        """Each post's tunes, as (post, place, tune), the place the tune's in the post's (from 1)."""
        for post in self.posts:
            for place, tune in enumerate(post.tunes, 1):
                yield post, place, tune


def _text(node: LexborNode | None) -> str:
    return " ".join((node.text(deep=True) or "").split()) if node is not None else ""


def _quoted(node: LexborNode, top: LexborNode) -> bool:
    parent = node.parent
    while parent is not None and parent is not top:
        if parent.tag == "blockquote":
            return True
        parent = parent.parent
    return False


def _path_of(tree: LexborHTMLParser, url: str | None) -> str:
    """The path of a thread's first page, from a page of it (its first, a later one)."""
    canonical = tree.css_first('link[rel="canonical"]')
    for address in ((canonical.attributes.get("href") or "") if canonical is not None else "", url or ""):
        m = _ANY_PAGE.fullmatch(address.split("#", 1)[0])
        if m:
            return m.group(1)
    return ""


def parse_thread_page(html: str | bytes, url: str | None = None) -> ThreadPage:
    """A thread page's title, forum and posts, each with the tunes of its charts; ``IRealParseError`` for a page
    without a title, a thread's address or a post (a page cut short, an error page). A later page of a thread reads
    as its first does, its path the first's, its posts its own."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    title = _text(tree.css_first("h1.p-title-value"))
    path = _path_of(tree, url)
    articles = tree.css("article.message--post")
    if not title or not path or not articles:
        raise IRealParseError("no thread (h1.p-title-value, its address, article.message--post) on the page", url=url)
    forum = next((m.group(0) for a in tree.css(".p-breadcrumbs a")
                  if (m := _FORUM.search(a.attributes.get("href") or ""))), "")
    posts = []
    for article in articles:
        found = _POST_ID.fullmatch(article.attributes.get("data-content") or "")
        if found is None:
            continue
        body = article.css_first(".message-body")
        links = [a.attributes.get("href") or "" for a in (body.css("a[href]") if body is not None else ())
                 if not _quoted(a, body)]
        posts.append(Post(int(found.group(1)), tuple(t for href in links for t in parse_link(href))))
    thread = thread_of(path)
    assert thread is not None
    return ThreadPage(path, thread, title, forum, tuple(posts))


# --- a forum's page ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ForumPage:
    """A forum's page: the threads it lists, in its order (``threads``), its sticky ones first (``sticky``)."""

    sticky: tuple[str, ...]
    threads: tuple[str, ...]


def _thread_link(item: LexborNode) -> str | None:
    a = item.css_first(".structItem-title a[data-tp-primary]") or item.css_first(".structItem-title a")
    m = _THREAD.search(a.attributes.get("href") or "") if a is not None else None
    return m.group(0) if m else None


def parse_forum_page(html: str | bytes, url: str | None = None) -> ForumPage:
    """A forum page's threads, its sticky ones apart; ``IRealParseError`` for a page that lists none."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    tree = LexborHTMLParser(html)
    threads = tuple(dict.fromkeys(p for item in tree.css(".structItem--thread") if (p := _thread_link(item))))
    if not threads:
        raise IRealParseError("no threads (.structItem--thread) on the page", url=url)
    sticky = tuple(dict.fromkeys(p for item in tree.css(".structItemContainer-group--sticky .structItem--thread")
                                 if (p := _thread_link(item))))
    return ForumPage(sticky, threads)
