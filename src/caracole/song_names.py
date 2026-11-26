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

**The text, cleaned** (``clean``): its spaces folded; then, of its groups, each bracket pair closed by its own mark
(( ) [ ] （ ） ［ ］ 【 】 「 」 『 』 《 》 〈 〉 〖 〗 〔 〕), these go wherever they are:

- a group of a video's words: of Latin words, every one a video's with one strong among them ("(Official Video)",
  "[Videoclip Oficial]", "(Letra)", "(Visualizer)", "(Karaoke Version)", "【MV】", a year beside them too); holding CJK,
  two thirds of its letters (CJK characters, Latin letters and digits) a video's or a lyric channel's (``_CJK_NOISE``:
  "『动态歌词MV』", "【抖音】", "【中文字幕】", "(華納 official 高畫質 HD 官方完整版MV)", 20 of 22; never "(Cover 葛東琪)");
- a lyric quoted in 「」 or 『』, a sentence (ending in 。！？…, a space between two CJK characters, or, holding a CJK
  character, longer than ``LYRIC_CHARS``), unless it is the whole text: "野人『不再借世人的手 替我开脱，…也能够耐住寂寞。』"
  is 野人, and "宋冬野「斑马，斑马」" and "Live「Lightning Crashes」" stay.

Then a last part of a video's words after a mark ("… | Official Video"), then such words loose at its end, two or more
("… Official Video", "… Con Letra", "… 官方完整版 MV": a run of a lyric channel's words is one of them) or one of a
format's ("HD", "4K", "MV"), a group's edges being word edges ("…Love Confession】Official MV"), and quotes around it.
The song's own words stay: "(feat. …)", "(En Vivo)", a title that ends with one such word ("Radio Video"). Its case,
accents and marks are kept as written.

**A tag's bracket** (``_tag``): a CJK title group of a version's or an upload's tag alone (``_TAGS``, a video's words
beside them: "【Live】", "【现场版】", "【翻唱】", "【DJ版】") is never a title. Leading the text or a part, the upload's
tag, it goes where words follow it (``_untagged``: "【翻唱】大鱼" is 大鱼); after the song's words it is the song's, as
written, as "(Live)" is ("周深 大鱼【Live】" from 周深's channel is 大鱼【Live】 by 周深).

**The rules, in order** (the first that reads the cleaned text names the song):

1. **Two parts.** "A - B" (an en or em dash, "|", "~", "//" or "_" too, with a space on each side, at the first such
   mark) with a word on each side is the artist A and the title B, whoever they are, as wanted.txt reads a line
   ("Silvana Estrada – Que problema"; "Muse - Hysteria - Live" is "Hysteria - Live" by Muse; "IU(아이유) _
   Blueming(블루밍)"); turned round when B is a known artist and A isn't, as in a fan's upload ("Somos vikingos
   veganos - Hyperfanes", once Hyperfanes is known). Each part is its own words (``_own``): less its CJK title groups
   (【】《》「」『』〈〉) where words of its own are outside its groups, a video's or a tag's alone being none
   ("消愁《Xiao Chou》" is 消愁, "【翻唱】周深" 周深), a lone "by" none too; else its first title group's content
   ("《消愁》「Xiao Chou」", "《大鱼》 Live" and "《大鱼》 by" are 消愁 and 大鱼). Its other groups are its own words, as
   written ("(En Vivo)", "（feat. 宋冬野）", "大鱼【Live】"), and so are a tag's or a video's words where it holds no
   title group ("Madonna - Music").
2. **A bracketed title.** A text no mark parts that holds a CJK title group has the first as the title. The words
   before it are the artist, less a video's words loose at their end as the cleaning cuts them, one glued to the name
   too ("米津玄師 MV「Lemon」" and "米津玄師MV「Lemon」" are Lemon by 米津玄師; "Bethel Music「Goodness of God」" keeps
   Bethel Music), and what follows it is decoration: a video's words, a film's name, the artist written again
   ("周杰倫 Jay Chou【告白氣球 Love Confession】Official MV"). But words before it that begin with a known artist (the
   channel's name among them, below) and go on are the title, and the group with all after it decoration ("陈奕迅
   孤勇者《英雄联盟：双城之战》动画主题曲" from 陈奕迅's channel is 孤勇者); with neither, it can't know where the artist
   ends. With no words before it, the words after it, less their groups and a leading "by" in any case, are the
   artist ("《孤勇者》 by 陈奕迅"; before it, a band's own "By" stays: "By Divine Right「Song」"); a title group alone,
   or with "by" alone, names no one.
3. **A known artist first, or after " by ".** The longest run of the first words that is a known artist's whole name
   is the artist, the rest the title ("silvana estrada que problema"; never a name that ends with a word names leave
   out, ``identity_key``: "Joaquín Sabina y nos dieron las diez"); or the words after the last " by " are, those before
   it the title ("Que problema by Silvana Estrada"). Where both read the text, the artist of more words ("Ben E King
   Stand by Me" is Ben E King's even where an index knows an artist "Me"); of as many, " by "'s. Neither reads a text
   that is a song's title whole, yours, Ultimate Guitar's or LaCuerda's ("Love Me Tender" is no song "Me Tender" by
   Love, "Stand by Me" none by Me).
4. **A video's channel.** The title of a video (``channel``) that none of these reads is its channel's song: the
   channel, its label words gone (``clean_channel``: "Radiohead - Topic", "EstopaVEVO", "Queen Official"), is the
   artist ("Creep" from "Radiohead - Topic"), the title its own words as a part's are ("《孤勇者》" from 陈奕迅's).
5. **The suggested video's song.** A query none of these reads, whose suggested video (``video``) is that song, names
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

from caracole.normalize import _CJK, compact, identity_key, name_forms, name_words, placeholder_artist, slug_key

if TYPE_CHECKING:
    from caracole.songs import Song

ONE_WORD_ARTIST = 5  # a one-word name is an index's artist with this many songs there, or a credible one of yours
LYRIC_CHARS = 16  # a 「」 or 『』 group holding CJK longer than this quotes a lyric, no title
_MARK = re.compile(r"\s+(?:-|–|—|\||~|//|_)\s+")  # the first splits "Artist - Title"
_BY = re.compile(r"\s+by\s+", re.IGNORECASE)  # "Title by Artist"

# A video's words, no song's: a bracket of them alone goes, and so do they at the title's end.
_NOISE = frozenset({
    "official", "oficial", "officiel", "ufficiale", "music", "musical", "video", "vídeo", "videoclip", "clip",
    "audio", "lyric", "lyrics", "letra", "letras", "con", "with", "hd", "hq", "4k", "1080p", "720p", "mv", "m/v",
    "visualizer", "visualiser", "remastered", "remaster", "remasterizado", "remasterizada", "version", "versión",
    "pinyin", "karaoke", "ktv", "8d",
})
_STRONG = _NOISE - {"music", "musical", "con", "with", "version", "versión", "clip"}  # one of them makes words noise
_FORMAT = frozenset({"hd", "hq", "4k", "1080p", "720p", "mv", "m/v"})  # noise alone, even loose at a title's end
_YEAR = re.compile(r"(?:19|20)\d\d")
# A lyric channel's words, no song's, in simplified and traditional characters, Japanese and Korean: noise as _NOISE's.
_CJK_NOISE = (
    "动态歌词", "動態歌詞", "歌词", "歌詞", "字幕", "中英字幕", "拼音", "官方", "完整版", "高音质", "高音質", "高画质", "高畫質",
    "高清", "无损", "無損", "纯音乐", "純音樂", "抖音", "热门", "熱門", "循环", "循環", "版",
    "中文字幕", "繁體字幕", "简体字幕", "中字", "字幕版",
    "公式", "歌詞付き", "フル",
    "가사", "뮤직비디오", "공식",
)
_CJK_NOISE_PHRASE = re.compile("|".join(sorted(_CJK_NOISE, key=lambda p: (-len(p), p))))  # the longest first
# A version's or an upload's tag, no title's: a bracket of them alone is never the title ("DJ版" is dj and 版).
_TAGS = frozenset({
    "live", "cover", "remix", "demo", "acoustic", "instrumental", "piano", "version", "ver", "dj",
    "翻唱", "现场", "現場", "现场版", "現場版", "伴奏", "纯享", "純享", "纯享版", "純享版", "合唱", "合唱版", "钢琴版", "鋼琴版",
    "吉他版", "女声版", "女聲版", "男声版", "男聲版", "加长版", "加長版", "重制版", "重製版", "原唱", "原版",
})
_CJK_LETTERS = _CJK.pattern[1:-1]  # Hangul, kana and Han: normalize.py's _CJK, its one class
# A text holding CJK in words: runs of CJK, and of other letters and digits ("m/v" whole), marks and spaces between.
_PIECE = re.compile(f"[{_CJK_LETTERS}]+|m/v(?![^\\W_{_CJK_LETTERS}])|[^\\W_{_CJK_LETTERS}]+")
_CJK_GAP = re.compile(f"[{_CJK_LETTERS}]\\s+[{_CJK_LETTERS}]")  # a space between two CJK characters: a sentence's
# A bracket pair, each opener closed by its own closer (the full-width （） and ［］ as () and [] are, kept as written).
_GROUPS = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|（[^（）]*）|［[^［］]*］|【[^【】]*】|「[^「」]*」|『[^『』]*』|《[^《》]*》"
                     r"|〈[^〈〉]*〉|〖[^〖〗]*〗|〔[^〔〕]*〕")
_LYRIC_QUOTES = "「『"  # the groups that quote a lyric
_TITLE_OPENERS = "【《「『〈"  # the groups that name a title: 【】《》「」『』〈〉
_SENTENCE_END = "。！？…"
_QUOTES = "\"'“”‘’«»「」『』"
_TOPIC = re.compile(r"^(.*\S)\s+-\s+topic$", re.IGNORECASE)
_LABEL = re.compile(r"\s*(?:vevo|official|oficial|officiel)(?:\s+channel)?$", re.IGNORECASE)


# --- the text, cleaned -----------------------------------------------------------------------------------------------


def _words(text: str) -> list[str]:
    """The words of ``text``, NFKC casefolded: split at spaces and Latin punctuation; in a text holding CJK, its runs
    of CJK and of other letters (``_PIECE``), marks left out."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    if _CJK.search(folded):
        return _PIECE.findall(folded)
    return [w for w in re.split(r"[\s,.:!¡¿?\-–—]+", folded) if w]


def _covered(run: str) -> int:
    """How many characters of a run of CJK its ``_CJK_NOISE`` phrases cover."""
    return sum(len(m.group()) for m in _CJK_NOISE_PHRASE.finditer(run))


def _is_noise(word: str) -> bool:
    """Whether one of ``_words``' words is a video's: in ``_NOISE``, a year, or a run of CJK of noise phrases alone."""
    if _CJK.match(word):
        return _covered(word) == len(word)
    return word in _NOISE or _YEAR.fullmatch(word) is not None


def _letters(word: str) -> int:
    return len(word) - word.count("/")  # "m/v"'s two


def _noise_letters(word: str) -> int:
    """How many of a word's letters are a video's: all of a word of ``_NOISE`` or a year's, those its phrases cover of
    a run of CJK."""
    if _CJK.match(word):
        return _covered(word)
    return _letters(word) if _is_noise(word) else 0


def _noise(text: str) -> bool:
    """Whether words are a video's alone: one strong word at least, a year or a lyric channel's words beside them."""
    words = _words(text)
    return bool(words) and any(w in _STRONG for w in words) and all(_is_noise(w) for w in words)


def _noise_word(word: str) -> bool:
    words = _words(word)
    return bool(words) and all(_is_noise(w) for w in words)


def _noise_group(inner: str) -> bool:
    """Whether a bracket's words are a video's: Latin ones by ``_noise``; ones holding CJK when a video's and a lyric
    channel's words are two thirds of their letters or more (CJK characters, Latin letters and digits)."""
    if not _CJK.search(unicodedata.normalize("NFKC", inner)):
        return _noise(inner)
    words = _words(inner)
    letters = sum(_letters(w) for w in words)
    return letters > 0 and 3 * sum(_noise_letters(w) for w in words) >= 2 * letters


def _lyric(inner: str) -> bool:
    """Whether a 「」 or 『』 group's words are a sentence: ending as one, a space between two CJK characters, or,
    holding a CJK character, longer than ``LYRIC_CHARS`` (sixteen Latin letters are a title's)."""
    inner = inner.strip()
    return bool(inner) and (inner[-1] in _SENTENCE_END or _CJK_GAP.search(inner) is not None
                            or len(inner) > LYRIC_CHARS and _CJK.search(inner) is not None)


def _decoration(group: re.Match[str], text: str) -> bool:
    """Whether a group of ``text`` is a video's: its words noise, or a lyric quoted where it isn't the whole text."""
    inner = group.group()[1:-1]
    return _noise_group(inner) or group.group()[0] in _LYRIC_QUOTES and _lyric(inner) \
        and not (group.start() == 0 and group.end() == len(text))


def _tokens(text: str) -> list[tuple[int, str, bool]]:
    """The words of ``text``, whose spaces are folded, each with where it begins and whether it is a group: a group
    whole, and each run of other characters between spaces and groups (a group's edges are word edges)."""
    out: list[tuple[int, str, bool]] = []
    at = 0
    for group in [*_GROUPS.finditer(text), None]:
        end = group.start() if group else len(text)
        for word in text[at:end].split(" "):
            if word:
                out.append((at, word, False))
            at += len(word) + 1
        if group:
            out.append((group.start(), group.group(), True))
            at = group.end()
    return out


def _undecorated(text: str) -> str:
    """``text``, whose spaces are folded, without its groups that are a video's, each with the spaces before it."""
    out, at = "", 0
    for group in _GROUPS.finditer(text):
        out += text[at:group.start()]
        out = out.rstrip(" ") if _decoration(group, text) else out + group.group()
        at = group.end()
    return out + text[at:]


def _unquoted(text: str) -> str:
    while len(text) > 1 and text[0] in _QUOTES and text[-1] in _QUOTES:
        text = text[1:-1].strip()
    return text


def clean(text: str) -> str:
    """``text`` without what a video's title adds to a song's name (module docstring), its spaces folded."""
    text = " ".join(_undecorated(" ".join(text.split())).split())
    while (marks := list(_MARK.finditer(text))) and _noise(text[marks[-1].end():]):
        text = text[:marks[-1].start()]  # "… | Official Video"
    if (at := _loose_at(_tokens(text))) is not None:
        text = text[:at].rstrip()
    text = _unquoted(text)
    return "" if _noise(text) else text


def _loose_at(words: list[tuple[int, str, bool]]) -> int | None:
    """Where a video's words loose at the end of ``words`` (``_tokens``') begin: two or more, one strong among them,
    or one of a format's ("HD"); None where there are none, or they stay (one alone: "Radio Video")."""
    cut = len(words)
    while cut > 1 and not words[cut - 1][2] and _noise_word(words[cut - 1][1]):
        cut -= 1
    loose = [word for _, word, _ in words[cut:]]
    if len(loose) > 1 and _noise(" ".join(loose)) or len(loose) == 1 and _words(loose[0]) and \
            all(w in _FORMAT for w in _words(loose[0])):
        return words[cut][0]
    return None


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
    cleaned = _untagged(clean(text))
    named = _two_parts(cleaned, known) or _bracketed(cleaned, known) or _known_artist_in(cleaned, known)
    if named is not None:
        return named
    if channel is not None:
        return clean_channel(channel), _own(cleaned)
    if video is not None and name_words(cleaned):
        artist, title = read_names(conn, video[0], songs=songs, channel=video[1])
        if artist and name_words(title) == name_words(cleaned):
            return artist, cleaned
    return None


def _two_parts(text: str, known: _Known) -> tuple[str, str] | None:
    """Rule 1: "A - B", each its own words, turned round when only B is a known artist."""
    mark = _MARK.search(text)
    if mark is None:
        return None
    first, second = _unquoted(_own(text[:mark.start()].strip())), _unquoted(_own(text[mark.end():].strip()))
    if not name_words(first) or not name_words(second):
        return None
    if known.artist(second) is not None and known.artist(first) is None:
        return second, first
    return first, second


def _tagged(words: list[str]) -> bool:
    """Whether ``_words``' words are a version's or an upload's tag (``_TAGS``) alone, a video's beside them."""
    return any(w in _TAGS for w in words) and all(w in _TAGS or _is_noise(w) for w in words)


def _tag(group: re.Match[str]) -> bool:
    """Whether a group is a CJK title group of a tag's words alone ("【Live】", "【现场版】", "【DJ版】"): never a title."""
    return group.group()[0] in _TITLE_OPENERS and _tagged(_words(group.group()[1:-1]))


def _titles(text: str) -> list[re.Match[str]]:
    """``text``'s CJK title groups (【】《》「」『』〈〉), in order, but a tag's (``_tag``)."""
    return [group for group in _GROUPS.finditer(text) if group.group()[0] in _TITLE_OPENERS and not _tag(group)]


def _untagged(text: str) -> str:
    """``text`` less the tag groups that lead it where words follow them, the upload's ("【翻唱】大鱼" is 大鱼); a tag
    group after the song's words is the song's, as written ("大鱼【Live】")."""
    while (group := _GROUPS.match(text)) and _tag(group) and name_words(text[group.end():]):
        text = text[group.end():].lstrip(" ")
    return text


def _ungrouped(text: str) -> str:
    """``text`` less every group, its spaces folded."""
    return " ".join(_GROUPS.sub(" ", text).split())


def _own_words(text: str) -> bool:
    """Whether ``text`` has words of its own outside its groups: a video's or a tag's alone ("MV", "Live") are none,
    and so is a lone "by" ("《孤勇者》 by")."""
    words = _ungrouped(text)
    found = _words(words)
    return bool(name_words(words)) and words.casefold() != "by" \
        and not (found and all(w in _TAGS or _is_noise(w) for w in found))


def _pieces(text: str) -> list[tuple[int, str, bool]]:
    """``_tokens``' words of ``text``, one holding CJK cut where its runs of CJK meet other letters ("米津玄師MV" is
    米津玄師 and MV)."""
    out: list[tuple[int, str, bool]] = []
    for at, word, group in _tokens(text):
        if not group and _CJK.search(word):
            out += [(at + piece.start(), piece.group(), False) for piece in _PIECE.finditer(word)]
        else:
            out.append((at, word, group))
    return out


def _artist_words(text: str) -> str:
    """``text``, its spaces folded, less a video's words loose at its end as ``clean`` cuts them (``_loose_at``), one
    glued to a CJK name too: "米津玄師 MV" and "米津玄師MV" are 米津玄師, "Bethel Music" stays."""
    text = " ".join(text.split())
    at = _loose_at(_pieces(text))
    return text if at is None else text[:at].rstrip()


def _without_by(artist: str) -> str:
    """``artist`` less a leading "by", in any case, a whole word ("by 陈奕迅" is 陈奕迅)."""
    first, _, rest = artist.partition(" ")
    return rest if first.casefold() == "by" else artist


def _own(part: str) -> str:
    """A part's own words (rule 1): less the tag groups that lead it (``_untagged``); then less its CJK title groups
    where words of its own are outside its groups ("消愁《Xiao Chou》" is 消愁, "【翻唱】周深" 周深), else its first title
    group's content ("《消愁》「Xiao Chou」" and "《消愁》 Live" are 消愁), its spaces folded; a part with no title group
    as it is, its words a tag's or a video's or not ("Music「Live」")."""
    part = _untagged(part)
    titles = _titles(part)
    if not titles:
        return part
    if not _own_words(part):
        return titles[0].group()[1:-1].strip()
    out, at = "", 0
    for group in titles:
        out += part[at:group.start()] + " "
        at = group.end()
    return " ".join((out + part[at:]).split())


def _bracketed(text: str, known: _Known) -> tuple[str, str] | None:
    """Rule 2: a text no mark parts, its first CJK title group the title; the words before it the artist, less a video's
    words loose at their end, but where they begin with an artist ``known`` knows and go on, those words the title;
    else the words after it, less their groups and a leading "by" ("By Divine Right" before it stays); none for a
    title group alone."""
    titles = _titles(text)
    if _MARK.search(text) or not titles:
        return None
    title = titles[0].group()[1:-1].strip()
    before = _artist_words(text[:titles[0].start()])
    if _own_words(before):
        if known.artist(before) is None and not known.title(before) and (named := _first(before, known)):
            return named  # "陈奕迅 孤勇者《英雄联盟：双城之战》" from 陈奕迅's channel
        artist = before
    else:
        artist = _without_by(_artist_words(_ungrouped(text[titles[0].end():])))
    if not name_words(artist) or not name_words(title):
        return None
    return artist, title


def _known_artist_in(text: str, known: _Known) -> tuple[str, str] | None:
    """Rule 3: a known artist first, or after the last " by ", the one of more words; none for a title whole."""
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
