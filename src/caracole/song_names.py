"""The artist and the title a text names: the one parser every path that turns free text into a song's name uses.

Those paths, each reading names here and nowhere else (no page splits a text itself):

- the request forms the library page and the lookup page fill in from a query (``/api/search``'s ``names``, read with
  the YouTube video suggested for the query), which Make the sheet fills in too;
- the guess a pasted YouTube link's panel shows (web/youtube_routes.py ``pasted_video``: the video's title, read with
  its channel);
- ``/request`` and ``/lookup`` given one text, ``q``, in place of an artist and a title (web/library_routes.py
  ``named_form``);
- ``caracole add TEXT`` and ``caracole get TEXT`` (commands/_common.py ``read_song_text``). Two arguments, ``caracole
  add ARTIST TITLE``, are the names themselves, never read.

**The text, cleaned** (``clean``): its spaces folded; a bracket made only of a video's words ("(Official Video)",
"[Videoclip Oficial]", "(Letra)", "(Visualizer)", "【MV】", a year beside them too) goes, then a last part of such words
after a mark ("… | Official Video"), then such words loose at its end, two or more ("… Official Video", "… Con Letra")
or one of a format's ("HD", "4K", "MV"), and quotes around it. The song's own words stay: "(feat. …)", "(En Vivo)", a
title that ends with one such word ("Radio Video"). Its case, accents and marks are kept as written.

**The rules, in order** (the first that reads the cleaned text names the song):

1. **Two parts.** "A - B" (an en or em dash, "|", "~" or "//" too, with a space on each side, at the first such mark)
   with a word on each side is the artist A and the title B, whoever they are, as wanted.txt reads a line ("Silvana
   Estrada – Que problema"; "Muse - Hysteria - Live" is "Hysteria - Live" by Muse); turned round when B is a known
   artist and A isn't, as in a fan's upload ("Somos vikingos veganos - Hyperfanes", once Hyperfanes is known).
2. **A known artist first, or after " by ".** The longest run of the first words that is a known artist's whole name
   is the artist, the rest the title ("silvana estrada que problema"; never a name that ends with a word names leave
   out, ``identity_key``: "Joaquín Sabina y nos dieron las diez"); or the words after the last " by " are, those before
   it the title ("Que problema by Silvana Estrada"). Where both read the text, the artist of more words ("Ben E King
   Stand by Me" is Ben E King's even where an index knows an artist "Me"); of as many, " by "'s. Neither reads a text
   that is a song's title whole, yours, Ultimate Guitar's or LaCuerda's ("Love Me Tender" is no song "Me Tender" by
   Love, "Stand by Me" none by Me).
3. **A video's channel.** The title of a video (``channel``) that neither reads is its channel's song: the channel,
   its label words gone (``clean_channel``: "Radiohead - Topic", "EstopaVEVO", "Queen Official"), is the artist ("Creep"
   from "Radiohead - Topic").
4. **The suggested video's song.** A query that neither reads, whose suggested video (``video``) is that song, names
   the video's artist: the video's own title read by these rules, with its channel, gives a title of the query's very
   words ("creep", and Radiohead's "Creep"; "que problema", and Silvana Estrada's "Qué Problema"). A video of another
   song names no one ("vikingos veganos", and a fan's "Somos vikingos veganos - Hyperfanes").

Else nothing: the text doesn't say who its artist is, and a page fills it in as the title (or as the artist's name,
when the search's answer has an artist lead), for the owner to edit: never cut at its first space ("Silvana" and
"Estrada").

**A known artist**, by their whole name (accents, case, spaces and scripts aside, ``normalize.name_forms``), never a
placeholder ("misc", "Various Artists"), is written as the first of these knows them, else as typed:

- an artist of your library, as it writes them ("bjork" is your Björk). One of two words or more, however few their
  songs; one of **one word** only when that is credible (``_Known._credible``): a song of theirs has a sheet from a
  site (``sheet.txt``, never auto-chords'), the library has two songs or more of theirs, or an index below knows them
  too, by a song or more. So one mistaken line in wanted.txt ("Silvana - Estrada") makes no artist "Silvana" for the
  queries after it;
- the channel of the video the text is the title of, or of the video suggested for the query, as the channel writes
  it ("Silvana Estrada", for "silvana estrada que problema");
- an artist of an index, read locally, never a site: Ultimate Guitar's and the artist pages caracole read,
  LaCuerda's listings, gtptabs.com's and harptabs.com's. One of two words or more with a song there; one of one word
  with ``ONE_WORD_ARTIST`` songs or more on one of them (Ultimate Guitar's "Que", of one song, makes "Que problema" no
  song by Que).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING

from caracole.normalize import compact, identity_key, name_forms, name_words, placeholder_artist, slug_key

if TYPE_CHECKING:
    from caracole.songs import Song

ONE_WORD_ARTIST = 5  # a one-word name is an index's artist with this many songs there, or a credible one of yours
_MARK = re.compile(r"\s+(?:-|–|—|\||~|//)\s+")  # the first splits "Artist - Title"
_BY = re.compile(r"\s+by\s+", re.IGNORECASE)  # "Title by Artist"

# A video's words, no song's: a bracket of them alone goes, and so do they at the title's end.
_NOISE = frozenset({
    "official", "oficial", "officiel", "ufficiale", "music", "musical", "video", "vídeo", "videoclip", "clip",
    "audio", "lyric", "lyrics", "letra", "letras", "con", "with", "hd", "hq", "4k", "1080p", "720p", "mv", "m/v",
    "visualizer", "visualiser", "remastered", "remaster", "remasterizado", "remasterizada", "version", "versión",
})
_STRONG = _NOISE - {"music", "musical", "con", "with", "version", "versión", "clip"}  # one of them makes words noise
_FORMAT = frozenset({"hd", "hq", "4k", "1080p", "720p", "mv", "m/v"})  # noise alone, even loose at a title's end
_YEAR = re.compile(r"(?:19|20)\d\d")
_BRACKETS = re.compile(r"\s*[(\[【「]([^()\[\]【】「」]*)[)\]】」]")
_QUOTES = "\"'“”‘’«»「」『』"
_TOPIC = re.compile(r"^(.*\S)\s+-\s+topic$", re.IGNORECASE)
_LABEL = re.compile(r"\s*(?:vevo|official|oficial|officiel)(?:\s+channel)?$", re.IGNORECASE)


# --- the text, cleaned -----------------------------------------------------------------------------------------------


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return [w for w in re.split(r"[\s,.:!¡¿?\-–—]+", folded) if w]


def _noise(text: str) -> bool:
    """Whether words are a video's alone: one strong word at least, a year beside them too."""
    words = _words(text)
    return bool(words) and any(w in _STRONG for w in words) and all(w in _NOISE or _YEAR.fullmatch(w) for w in words)


def _noise_word(word: str) -> bool:
    words = _words(word)
    return bool(words) and all(w in _NOISE or _YEAR.fullmatch(w) for w in words)


def _unquoted(text: str) -> str:
    while len(text) > 1 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return text


def clean(text: str) -> str:
    """``text`` without what a video's title adds to a song's name (module docstring), its spaces folded."""
    text = " ".join(_BRACKETS.sub(lambda m: "" if _noise(m.group(1)) else m.group(0), " ".join(text.split())).split())
    while (marks := list(_MARK.finditer(text))) and _noise(text[marks[-1].end():]):
        text = text[:marks[-1].start()]  # "… | Official Video"
    words = text.split()
    cut = len(words)
    while cut > 1 and _noise_word(words[cut - 1]):
        cut -= 1
    loose = words[cut:]
    if len(loose) > 1 and _noise(" ".join(loose)) or len(loose) == 1 and _words(loose[0]) and \
            all(w in _FORMAT for w in _words(loose[0])):
        text = " ".join(words[:cut])
    text = _unquoted(text)
    return "" if _noise(text) else text


def clean_channel(channel: str) -> str:
    """A channel's name as an artist's: no " - Topic", no VEVO, Official or Oficial at its end."""
    name = " ".join(channel.split())
    topic = _TOPIC.match(name)
    if topic:
        return topic.group(1).strip()
    bare = _LABEL.sub("", name).strip()
    return bare or name


# --- the rules -------------------------------------------------------------------------------------------------------


def read_names(conn: sqlite3.Connection | None, text: str, *, songs: Sequence[Song] | None = None,
               channel: str | None = None, video: tuple[str, str] | None = None) -> tuple[str, str] | None:
    """The artist and the title ``text`` names (module docstring); None for a text that doesn't say who its artist is.

    ``songs`` are your library's (None: the database's, ``songs.list_songs``); no database (``conn`` None) knows
    nothing but the channels given. ``channel``: ``text`` is the title of a video of that channel's, whose song it
    always names, "" for a part it can't tell. ``video``: the title and the channel of the video suggested for
    ``text``, a query."""
    if songs is None:
        from caracole.songs import list_songs

        songs = list_songs(conn) if conn is not None else ()
    hints = [h for h in (clean_channel(c) for c in (channel, video[1] if video else None) if c) if h]
    known = _Known(conn, songs, hints)
    cleaned = clean(text)
    named = _two_parts(cleaned, known) or _known_artist_in(cleaned, known)
    if named is not None:
        return named
    if channel is not None:
        return clean_channel(channel), cleaned
    if video is not None and name_words(cleaned):
        artist, title = read_names(conn, video[0], songs=songs, channel=video[1])
        if artist and name_words(title) == name_words(cleaned):
            return artist, cleaned
    return None


def _two_parts(text: str, known: _Known) -> tuple[str, str] | None:
    """Rule 1: "A - B", turned round when only B is a known artist."""
    mark = _MARK.search(text)
    if mark is None:
        return None
    first, second = _unquoted(text[:mark.start()].strip()), _unquoted(text[mark.end():].strip())
    if not name_words(first) or not name_words(second):
        return None
    if known.artist(second) is not None and known.artist(first) is None:
        return second, first
    return first, second


def _known_artist_in(text: str, known: _Known) -> tuple[str, str] | None:
    """Rule 2: a known artist first, or after the last " by ", the one of more words; none for a title whole."""
    found = [named for named in (_after_by(text, known), _first(text, known)) if named is not None]
    if not found or known.title(text):
        return None
    return max(found, key=lambda named: len(name_words(named[0])))  # a tie: " by "'s, the first


def _after_by(text: str, known: _Known) -> tuple[str, str] | None:
    for by in reversed(list(_BY.finditer(text))):
        title, artist = text[:by.start()], text[by.end():]
        name = known.artist(artist) if name_words(title) else None
        if name is not None:
            return name, title
    return None


def _first(text: str, known: _Known) -> tuple[str, str] | None:
    words = text.split()
    for n in range(len(words) - 1, 0, -1):
        artist, title = " ".join(words[:n]), " ".join(words[n:])
        if n > 1 and identity_key(artist, "") == identity_key(" ".join(words[:n - 1]), ""):
            continue  # "Joaquín Sabina y nos dieron las diez": "y" ends no name
        name = known.artist(artist) if name_words(title) else None
        if name is not None:
            return name, title
    return None


# --- what is known ---------------------------------------------------------------------------------------------------


def _forms(name: str) -> set[str]:
    return {compact(f) for f in name_forms(name)} - {""}


class _Known:
    """The artists and titles known to the library, the channels given and the local indexes (module docstring),
    each name looked up once."""

    def __init__(self, conn: sqlite3.Connection | None, songs: Sequence[Song], hints: Sequence[str]) -> None:
        self.conn, self.songs, self.hints = conn, songs, hints
        self._artists: dict[str, str | None] = {}
        self._titles: dict[str, bool] = {}
        self._indexed: dict[str, int] = {}

    def artist(self, name: str) -> str | None:
        """The artist ``name`` is, as your library writes them, else as a channel does, else as written; None for a
        name no one knows as an artist's whole name."""
        name = " ".join(name.split())
        if name not in self._artists:
            self._artists[name] = self._artist(name)
        return self._artists[name]

    def _artist(self, name: str) -> str | None:
        from caracole.search import library_by_artist

        if placeholder_artist(name) or not name_words(name):
            return None
        wanted = _forms(name)
        mine = library_by_artist(self.songs, name)
        spelled = next((a for s in mine for a in dict.fromkeys(s.artists or [s.artist]) if wanted & _forms(a)), None)
        if spelled is not None and (len(name_words(spelled)) > 1 or self._credible(mine)
                                    or self._index_songs(name) >= 1):
            return spelled
        for given in self.hints:
            if not placeholder_artist(given) and wanted & _forms(given):
                return " ".join(given.split())
        least = ONE_WORD_ARTIST if len(name_words(name)) == 1 else 1
        return name if self._index_songs(name) >= least else None

    def _credible(self, mine: Sequence[Song]) -> bool:
        """Whether a one-word artist of yours is one: two songs of theirs or more, or a sheet from a site for one."""
        from caracole.songs import HUMAN_SHEET

        if len(mine) > 1:
            return True
        ids = [s.id for s in mine]
        return bool(ids) and self.conn is not None and self.conn.execute(
            f"SELECT 1 FROM files WHERE name = ? AND song_id IN ({', '.join('?' * len(ids))}) LIMIT 1",
            [HUMAN_SHEET, *ids]).fetchone() is not None

    def _index_songs(self, name: str) -> int:
        """The most songs an index has of the artist ``name`` is: Ultimate Guitar's and the artist pages caracole read,
        gtptabs.com's, LaCuerda's listings (an artist's row counts their songs), harptabs.com's (as many tabs as their
        page says once read, else one). No one's name ("misc-…") has none."""
        if name in self._indexed:
            return self._indexed[name]
        from caracole.lacuerda_index import name_key
        from caracole.search import _song_counts, gtptabs_songs, no_ones

        forms = [f for f in name_forms(name) if f and not no_ones(f)]
        counts = [0]
        conn = self.conn
        if forms and conn is not None:
            counts += [max(_song_counts(conn, forms).values(), default=0), gtptabs_songs(conn, name)]
            lc_keys = list(dict.fromkeys(k for k in (name_key(f) for f in [name, *forms]) if k))
            if lc_keys:
                counts.append(conn.execute(
                    f"SELECT COALESCE(MAX(songs), 0) FROM lacuerda_index WHERE artist_key IN "
                    f"({', '.join('?' * len(lc_keys))}) AND title = ''", lc_keys).fetchone()[0])
            counts.append(conn.execute(
                "SELECT COALESCE(MAX(COALESCE(a.tabs, 1)), 0) FROM harptabs_index i LEFT JOIN harptabs_artists a "
                f"ON a.path = i.path WHERE i.kind = 'artist' AND i.key IN ({', '.join('?' * len(forms))}) "
                "AND (a.name IS NULL OR a.name != '')", forms).fetchone()[0])
        self._indexed[name] = max(counts)
        return self._indexed[name]

    def title(self, text: str) -> bool:
        """Whether ``text``, whole, is a song's title: yours, Ultimate Guitar's or LaCuerda's."""
        if text not in self._titles:
            self._titles[text] = self._title(text)
        return self._titles[text]

    def _title(self, title: str) -> bool:
        from caracole.lacuerda_index import title_key

        mine = identity_key("", title).partition("/")[2]
        if mine and any(s.key.partition("/")[2] == mine for s in self.songs):
            return True
        if self.conn is None:
            return False
        key = slug_key(title)
        if key and self.conn.execute("SELECT 1 FROM ug_index WHERE song_key = ? LIMIT 1", (key,)).fetchone():
            return True
        lc = title_key(title)
        return bool(lc and self.conn.execute("SELECT 1 FROM lacuerda_index WHERE title_key = ? AND title != '' LIMIT 1",
                                             (lc,)).fetchone())
