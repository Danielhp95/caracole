"""Text normalization shared by every source and provider.

The same token rules are applied to names from Spotify or ``wanted.txt`` and to
Ultimate Guitar's URL slugs, so the two sides meet in one key space:

- accents are stripped and a few letters transliterated (``ñ`` → ``n``, ``ß`` → ``ss``);
- apostrophes vanish (``I'll`` → ``ill``), other punctuation splits words;
- ``&`` and the word ``and`` are dropped (UG writes "Simon & Garfunkel" as
  ``simon-garfunkel`` but "Adam and the Ants" as ``adam-and-the-ants``);
- a leading ``the`` is dropped;
- runs of CJK characters are joined without hyphens, so "斑马，斑马" and
  "斑马斑马" share a key.

A song's identity key folds more than that, because it only has to meet other
spellings of the same song, never UG's slugs: Traditional Chinese becomes
Simplified, number words become digits, and an artist's "y" goes the way of
"and", as does a leading Spanish article (:func:`identity_key`).
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Iterator

VARIANT_TOKENS = ("intro", "solo", "outro", "riff", "lesson", "acoustic", "live", "unplugged")

# The version of the rules that make identity keys. Bump it with any change to
# clean_title, slug_key or identity_key that can change a key: songs.py then
# re-keys the stored songs once (songs.ensure_current_keys). Version 1 had no
# Spanish live or acoustic suffixes and no identity folding (October 2026).
KEY_VERSION = 2

_TRANSLIT = str.maketrans(
    {
        "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ß": "ss",
        "ẞ": "ss", "đ": "d", "Đ": "d", "ł": "l", "Ł": "l", "þ": "th", "Þ": "th",
        "ð": "d", "Ð": "d", "ı": "i", "ħ": "h", "Ħ": "h",
    }
)
_APOSTROPHES = re.compile(r"['’‘`´ʼ]")
_SPLIT = re.compile(r"[\W_]+")
_CJK = re.compile(
    "[ᄀ-ᇿ぀-ヿ㐀-䶿一-鿿가-힯豈-﫿"
    "\U00020000-\U0002ebef]"
)
_HAN = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ebef]")

# Spotify's version suffixes. Each is removed only as a " - …" suffix or as a
# parenthesized group, never from the start of a title ("Live and Let Die").
# Live and acoustic versions are named in Spanish and Portuguese too ("En Vivo",
# "Ao Vivo", "Versión Acústica"), and may run on after a ";" or a ","
# ("Acoustic; Live at MTV Unplugged, …; 2013 Remaster").
_LIVE = r"live|(?:en|ao)\s+vivo|en\s+directo"
_ACOUSTIC = r"acoustic|(?:en\s+)?ac[uú]stic[oa]|versi[oó]n\s+ac[uú]stica"
_RUN_ON = r"(?:[\s;,/].*)?"
_DASH_SUFFIX = re.compile(
    r"\s+[-–—]\s+(?:"
    r"(?:\d{4}\s+)?(?:digital\s+)?remaster(?:ed)?(?:\s+(?:version|edition|\d{4}))*"
    r"|remasterizad[oa](?:\s+\d{4})?"
    rf"|(?:{_LIVE}|(?:mtv\s+)?unplugged|{_ACOUSTIC}){_RUN_ON}"
    r"|radio\s+(?:edit|version)|single\s+(?:edit|version)|album\s+version|edit"
    r"|demo(?:\s+version)?|bonus\s+track"
    r"|mono|stereo|(?:\d{4}\s+)?(?:stereo|mono)\s+(?:mix|version)|\d{4}\s+mix"
    r"|recorded\s+(?:live\s+)?at\s.*|[^-–—]*\bsessions?"
    r"|from\s.*\bsoundtrack\b.*|from\s+[\"“].*"
    r")\s*$",
    re.IGNORECASE,
)
_PAREN_FEAT = re.compile(r"\s*[\(\[](?:feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]", re.IGNORECASE)
_PAREN_SUFFIX = re.compile(
    r"\s*[\(\[](?:"
    r"live(?:\s+(?:at|from|in|on)\b[^\)\]]*)?|(?:(?:en|ao)\s+vivo|en\s+directo)(?:\s[^\)\]]*)?"
    r"|(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?"
    r"|remasterizad[oa](?:\s+\d{4})?"
    rf"|(?:{_ACOUSTIC})(?:\s+version)?|(?:mtv\s+)?unplugged"
    r"|radio\s+(?:edit|version)|single\s+edit|demo(?:\s+version)?|\d{4}\s+mix|mono|stereo"
    r"|from\s[^\)\]]*\bsoundtrack\b[^\)\]]*|from\s+[\"“][^\)\]]*"
    r")[\)\]]",
    re.IGNORECASE,
)
# What title_variant reads in a removed suffix.
_ACOUSTIC_WORD = re.compile(r"\b(?:acoustic|ac[uú]stic[oa]|unplugged)\b", re.IGNORECASE)
_LIVE_WORD = re.compile(r"\b(?:live|vivo|directo)\b", re.IGNORECASE)


def fold(s: str) -> str:
    """Lowercase, strip accents and transliterate letters NFKD can't decompose."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.translate(_TRANSLIT).lower()


def clean_title(title: str) -> str:
    """Drop Spotify's version suffixes: remasters, live and acoustic versions (in English,
    Spanish or Portuguese), featurings, mixes, edits, demos and session recordings."""
    prev = None
    cur = title.strip()
    while cur != prev:
        prev = cur
        cur = _PAREN_FEAT.sub("", cur)
        cur = _PAREN_SUFFIX.sub("", cur)
        cur = _DASH_SUFFIX.sub("", cur).strip()
    return cur or title.strip()


def title_variant(title: str) -> str | None:
    """"acoustic" or "live" when the source title says so ("Acústico", "En Vivo" too), else None."""
    suffix = title[len(clean_title(title)) :]
    if _ACOUSTIC_WORD.search(suffix):
        return "acoustic"
    if _LIVE_WORD.search(suffix):
        return "live"
    return None


def canonical_variant(label: str | None) -> str | None:
    """Map equivalent labels together: an unplugged version is an acoustic one."""
    return "acoustic" if label == "unplugged" else label


def _join(tokens: list[str]) -> str:
    out = ""
    for tok in tokens:
        if out and _CJK.match(out[-1]) and _CJK.match(tok[0]):
            out += tok
        elif out:
            out += "-" + tok
        else:
            out = tok
    return out


def _canon(tokens: list[str]) -> str:
    present = [t for t in tokens if t]
    # Drop "and", unless the name is nothing but "and" (the band "And And And").
    tokens = [t for t in present if t != "and"] or present
    if len(tokens) > 1 and tokens[0] == "the":
        tokens = tokens[1:]
    return _join(tokens)


def slug_key(s: str) -> str:
    """The canonical key of a name or title."""
    return _canon(_SPLIT.split(_APOSTROPHES.sub("", fold(s))))


def ug_slug_key(slug: str) -> str:
    """The canonical key of an Ultimate Guitar URL slug such as ``the-rifles``."""
    return _canon(fold(slug).split("-"))


def compact(key: str) -> str:
    """A key with its hyphens removed, so ``ac-dc`` meets ``acdc``."""
    return key.replace("-", "")


# What one writes for an artist one doesn't know, as folded words: no one's name ("misc - 斑马").
_PLACEHOLDER_ARTISTS = frozenset({
    "", "misc", "miscellaneous", "unknown", "unknown-artist", "unknown-artists", "various", "various-artists",
    "va", "v-a", "na", "n-a", "none", "anon", "anonymous", "artist", "desconocido", "anonimo", "varios",
    "varios-artistas",
})


def placeholder_artist(name: str) -> bool:
    """Whether an artist, as written, stands for an artist one doesn't know ("misc", "unknown",
    "Various Artists"): no one's name, so nothing can be found by it. "The Unknown" is a name."""
    return "-".join(w for w in _SPLIT.split(_APOSTROPHES.sub("", fold(name))) if w) in _PLACEHOLDER_ARTISTS


def split_variant(song_key: str) -> tuple[str, str | None]:
    """Split a trailing variant label off a song key: ``x-intro`` → (``x``, ``intro``)."""
    head, sep, last = song_key.rpartition("-")
    if sep and head and last in VARIANT_TOKENS:
        return head, last
    return song_key, None


def identity_key(artist: str, title: str) -> str:
    """The identity of a song: the same song from any source gets the same key.

    On top of :func:`slug_key`'s rules, spellings that name the same song meet:
    Traditional and Simplified characters (斑馬斑馬 is 斑马斑马), number words
    and digits ("Té Para Tres" is "Té para 3"), and an artist written with "y"
    or "&" ("Fito y Fitipaldis"), or with or without a leading Spanish article
    ("Los Enanitos Verdes"). ``slug_key`` itself keeps none of these: the
    matcher compares it with UG's slugs as the index stored them.
    """
    return f"{_identity(artist, artist=True)}/{_identity(clean_title(title), artist=False)}"


# What identity keys fold beyond slug_key (see identity_key). An artist's "y" goes
# like "and"; a title keeps it ("19 Días y 500 Noches").
_ARTIST_DROPPED = frozenset({"and", "y"})
_TITLE_DROPPED = frozenset({"and"})
_SPANISH_ARTICLES = frozenset({"los", "las", "el", "la"})
_NUMBER_WORDS = {
    "zero": "0", "cero": "0", "one": "1", "uno": "1", "two": "2", "dos": "2", "three": "3",
    "tres": "3", "four": "4", "cuatro": "4", "five": "5", "cinco": "5", "six": "6", "seis": "6",
    "seven": "7", "siete": "7", "eight": "8", "ocho": "8", "nine": "9", "nueve": "9", "ten": "10",
    "diez": "10", "eleven": "11", "twelve": "12", "doce": "12",
}


def _identity(name: str, *, artist: bool) -> str:
    """One side of an identity key: ``slug_key``'s tokens, folded further."""
    present = [t for t in _SPLIT.split(_APOSTROPHES.sub("", _simplified(fold(name)))) if t]
    dropped = _ARTIST_DROPPED if artist else _TITLE_DROPPED
    tokens = [t for t in present if t not in dropped] or present
    tokens = [_NUMBER_WORDS.get(t, t) for t in tokens]
    if len(tokens) > 1 and (tokens[0] == "the" or (artist and tokens[0] in _SPANISH_ARTICLES)):
        tokens = tokens[1:]
    return _join(tokens)


def _simplified(s: str) -> str:
    """Traditional Chinese characters written as Simplified ones (斑馬 → 斑马)."""
    return s.translate(_t2s_table()) if has_han(s) else s


def simplified(s: str) -> str:
    """A text with its Traditional Chinese characters written as Simplified ones (斑馬 → 斑马), for
    comparing it with names whose forms are Simplified (youtube.py's video titles)."""
    return _simplified(s)


@functools.cache
def _t2s_table() -> dict[int, int]:
    return str.maketrans(_T2S_PAIRS[0::2], _T2S_PAIRS[1::2])


def display_key(artist: str, title: str) -> str:
    """How a song is written in overrides.toml and on the to-do page."""
    return f"{artist.strip()} - {clean_title(title)}"


def has_han(s: str) -> bool:
    """Whether the text contains Chinese characters."""
    return _HAN.search(s) is not None


def has_other_script(s: str) -> bool:
    """Whether the text has letters of a script other than Latin (Chinese, Japanese, Korean, Cyrillic...)."""
    return any(_foreign(c) for c in s)


def romanize(s: str) -> str:
    """Hanyu Pinyin for Chinese characters, so "宋冬野" can meet UG's ``song-dongye``.

    Text without Chinese characters is returned unchanged.
    """
    if not has_han(s):
        return s
    from pypinyin import lazy_pinyin

    parts = [p.strip() for p in lazy_pinyin(s)]
    words = [p for p in parts if p and not _SPLIT.fullmatch(p)]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


# --- a name's forms --------------------------------------------------------------------------

# A part of a name made only of these words, numbers and single letters names a version or a part
# of a song, never the song or its artist, so it is no form of the name (name_forms).
GENERIC_WORDS = frozenset({
    *VARIANT_TOKENS, "remix", "mix", "version", "ver", "edit", "demo", "cover", "instrumental", "karaoke",
    "remaster", "remastered", "mono", "stereo", "ost", "tv", "size", "short", "full", "feat", "ft",
    "official", "original", "chords", "tab", "tabs", "guitar", "bass", "ukulele", "piano", "mv", "part",
    "pt", "english", "chinese", "mandarin", "cantonese", "japanese", "korean", "russian", "translation",
    "romanized", "lyrics",
})
# Where a name written in two scripts breaks into its parts, besides where its original ends (_cut):
# brackets of every width ("Song Dongye (宋冬野)", "【斑马斑马】Zebra Zebra") and a spaced " / " or " - ".
_PART_BREAK = re.compile(r"\s+[-–—/|]\s+|[()\[\]{}（）［］｛｝【】「」『』《》〈〉〔〕〖〗／｜]")
_LATIN, _CJK_SCRIPT, _OTHER = "latin", "cjk", "other"
# The artists a name features, bracketed in any width or after it: "Ma Di (feat. 宋冬野)", "南山南（feat.
# 宋冬野）", "Ma Di feat. 宋冬野". Spotify's ASCII-bracketed featurings leave titles in clean_title.
_FEATURING = re.compile(
    r"\s*[(\[（［【]\s*(?:feat\.|ft\.|(?:feat|ft|featuring|with)\s)[^)\]）］】]*[)\]）］】]"
    r"|\s+(?:feat\.|ft\.|featuring\s).*$",
    re.IGNORECASE,
)


def without_featuring(name: str) -> str:
    """The name without the artists it features ("Ma Di (feat. 宋冬野)" is "Ma Di"); the name itself when
    it features nobody, or is nothing else."""
    return _FEATURING.sub("", name).strip() or name.strip()


@functools.lru_cache(maxsize=8192)
def name_forms(name: str) -> tuple[str, ...]:
    """The keys a name is compared by wherever a name caracole didn't write meets yours: UG's
    artist pages and sitemap slugs, the artist pages learned from UG's tab pages, purchases'
    tags, UG's names for a download, and the names of your ``[artist_url]`` entries. Forms are
    for comparing; no key is made from them.

    First come the keys a name always had: its slug key, then, for Chinese, its pinyin key and
    its Simplified one. A Latin name has its slug key alone, and a name in one other script
    these keys alone.

    UG writes many non-Latin names in two scripts, each part a name on its own: the original,
    a romanization, a translation, in any order when bracketed or after " / " or " - "
    ("Song Dongye (宋冬野)", "봄날 (Spring Day)", "Кино (Kino)"); with nothing between them,
    the original first and the rest after a space ("斑马 斑马 Banma Banma Zebra Zebra",
    "与我交谈 Speak With Me", "17岁 17 Sui"). Latin before the original, or glued to it, is
    part of the title ("Baby 对不起", "我的Baby", "K歌之王"), never another song's name. Each
    part of such a name is a form too, with its pinyin and its Simplified key when it is
    Chinese, so "宋冬野" meets "Song Dongye (宋冬野)" and "Song Dong Ye" meets "Song Dongye". A
    Latin part that starts or ends with a romanization of the original also gives the
    romanization and the rest (a translation) apart (``_romanized``): "banma-banma" and
    "zebra-zebra", "bomnal" and "spring-day" after 봄날, "yoru-ni-kakeru" and
    "racing-into-the-night" after 夜に駆ける. Chinese is read in any of its characters' readings
    (重来 is chong lai too), Korean and kana by tables, a kanji as any one to three morae.
    Scripts read nowhere here (Cyrillic, Greek, ...) meet on their original part, or on the
    Latin one whole.

    The artists a name features are no part of it: "Ma Di (feat. 宋冬野)" and "Ma Di feat. 宋冬野"
    are Ma Di's, never 宋冬野's, and "南山南（feat. 宋冬野）" is 南山南, so the name without them
    (``without_featuring``) gives its keys and its parts.

    A part that is only words such as "Live", "Acoustic" or "Remix" (``GENERIC_WORDS``),
    numbers or a single Latin letter is no form: it never makes a match on its own. Two Latin
    letters are a name ("爱 Ai", "IU (아이유)"), and an original in another script is one at any
    length ("Ты (Ty)", "ใจ (Jai)"). Nor is a name with two non-Latin parts split ("A (甲) & B
    (乙)", two singers): its parts would be other artists' names.
    """
    core = without_featuring(name)
    forms = _own_keys(name)
    if core != name.strip():
        forms += _own_keys(core)
    parts = _parts(core)
    for part in parts:
        forms += _part_forms(part, parts)
    return tuple(f for f in dict.fromkeys(forms) if f)


# A bracketed group, in any width, as a listing in Latin letters alone holds a translation (listing_forms).
_BRACKETED = re.compile(r"[(\[（［【][^)\]）］】]*[)\]）］】]")


@functools.lru_cache(maxsize=8192)
def listing_forms(title: str) -> tuple[str, ...]:
    """The forms of a title as UG lists it on an artist page: its ``name_forms``, and, for a title in
    Latin letters alone, the key of the title outside its brackets.

    UG lists some titles as a romanization with its translation bracketed ("Hong Dou (Red Bean)" for
    红豆, "Nơi Này Có Anh (Where This Is You)"), and outside the brackets is the title whatever they
    hold; what they hold may be anything, so it is no form. Only a listing's: a title you bracket is
    compared whole, so "Another Brick in the Wall (Part 1)" never takes the tabs of another part.
    """
    forms = list(name_forms(title))
    if not has_other_script(title):
        outside = slug_key(_BRACKETED.sub(" ", title))
        if outside and not _generic(outside):
            forms.append(outside)
    return tuple(dict.fromkeys(forms))


def _own_keys(name: str) -> list[str]:
    """The keys a name always had: its slug key, and its pinyin and Simplified keys when it is Chinese."""
    if has_han(name):
        return [slug_key(name), slug_key(romanize(name)), slug_key(_simplified(name))]
    return [slug_key(name)]


def _script(c: str) -> str | None:
    """A letter's script as name forms tell parts apart (CJK, Latin or other); None for a non-letter.
    A Latin letter that folds to no ASCII one (ŋ, ə) is Latin all the same."""
    if not c.isalpha():
        return None
    if _CJK.match(c):
        return _CJK_SCRIPT
    return _LATIN if fold(c).isascii() or "LATIN" in unicodedata.name(c, "") else _OTHER


def _foreign(c: str) -> bool:
    """Whether a character is a letter of a script other than Latin."""
    return _script(c) in (_CJK_SCRIPT, _OTHER)


def _cut(piece: str) -> list[str]:
    """A piece of a name with nothing between its parts, cut where the original ends and its romanization
    or translation starts: at the space (or punctuation) after the original's last letter, when Latin
    letters follow. UG writes the original first ("斑马 斑马 Banma Banma Zebra Zebra", "17岁 17 Sui"),
    so Latin before it, or glued to it, is part of the title ("Baby 对不起", "我的Baby", "K歌之王")."""
    last = max((i for i, c in enumerate(piece) if _foreign(c)), default=None)
    if last is None:
        return [piece]
    for i in range(last + 1, len(piece)):
        c = piece[i]
        if _script(c) == _LATIN:
            return [piece]
        if c.isspace() or unicodedata.category(c)[0] in "PSZ":
            rest = piece[i:]
            return [piece[:i], rest] if any(_script(r) == _LATIN for r in rest) else [piece]
    return [piece]


def _parts(name: str) -> list[str]:
    """The parts of a name written in two scripts or more, with one non-Latin part; else none."""
    text = _APOSTROPHES.sub("", name)
    if len({s for c in text if (s := _script(c)) is not None}) < 2:
        return []
    parts = [part for piece in _PART_BREAK.split(text) for part in _cut(piece) if slug_key(part)]
    foreign = [p for p in parts if any(_foreign(c) for c in p)]
    return parts if len(parts) > 1 and len(foreign) == 1 else []


def _part_forms(part: str, parts: list[str]) -> list[str]:
    """One part's forms: its key, then its Simplified and pinyin keys (Chinese), or the romanization
    of the name's original part it holds and the rest apart (Latin)."""
    key = slug_key(part)
    if _generic(key):
        return []
    forms = [key]
    if has_han(part):
        forms += [slug_key(_simplified(part)), slug_key(romanize(part))]
    else:
        for other in parts:
            if other is not part and has_other_script(other):
                forms += _romanized(key, other)
    return [f for f in forms if not _generic(f)]


def _romanized(key: str, original: str) -> list[str]:
    """A Latin part's key split where the romanization of ``original`` starts or ends it
    (``_reads_as``): ``banma-banma-zebra-zebra`` after 斑马 斑马 gives ``banma-banma`` and
    ``zebra-zebra``, ``bomnal-spring-day`` after 봄날 ``bomnal`` and ``spring-day``."""
    readings = _readings(original)
    if not readings:
        return []
    words = key.split("-")
    for n in range(1, len(words)):  # each piece keyed as slug_key would key it ("the meaning of you")
        if _reads_as("".join(words[:n]), readings):
            return [_canon(words[:n]), _canon(words[n:])]
        if _reads_as("".join(words[-n:]), readings):
            return [_canon(words[-n:]), _canon(words[:-n])]
    return []


# --- reading an original, to tell its romanization from a translation after it --------------------

# Hangul: each syllable block's initial, medial and final jamo, and how each is romanized: the Revised
# Romanization first, then the spellings titles also use (k for g, eo as o or u, ...).
_HANGUL_INITIALS = ("g k", "kk gg k", "n", "d t", "tt dd", "r l", "m", "b p", "pp bb", "s sh", "ss s", "",
                    "j ch", "jj tch", "ch", "k", "t", "p", "h")
_HANGUL_MEDIALS = ("a", "ae e", "ya", "yae ye", "eo o u", "e", "yeo yo", "ye", "o", "wa", "wae we", "oe we",
                   "yo", "u oo", "wo", "we", "wi", "yu", "eu u", "ui eui i", "i ee")
_HANGUL_FINALS = ("", "k g", "k kk", "k", "n", "n", "n", "t d", "l r", "k", "m", "l", "l", "l", "p", "l", "m",
                  "p b", "p", "t s", "t ss", "ng", "t j", "t ch", "k", "t", "p", "t h")
# Kana as Hepburn writes them (and Kunrei-shiki: si, ti, tu, hu); katakana as the hiragana they match.
_KANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o", "か": "ka", "き": "ki", "く": "ku", "け": "ke",
    "こ": "ko", "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go", "さ": "sa", "し": "shi si",
    "す": "su", "せ": "se", "そ": "so", "ざ": "za", "じ": "ji zi", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi ti", "つ": "tsu tu", "て": "te", "と": "to", "だ": "da", "ぢ": "ji di",
    "づ": "zu du", "で": "de", "ど": "do", "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha wa", "ひ": "hi", "ふ": "fu hu", "へ": "he e", "ほ": "ho", "ば": "ba", "び": "bi", "ぶ": "bu",
    "べ": "be", "ぼ": "bo", "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po", "ま": "ma",
    "み": "mi", "む": "mu", "め": "me", "も": "mo", "や": "ya", "ゆ": "yu", "よ": "yo", "ら": "ra",
    "り": "ri", "る": "ru", "れ": "re", "ろ": "ro", "わ": "wa", "ゐ": "i wi", "ゑ": "e we", "を": "wo o",
    "ん": "n m", "ゔ": "vu bu", "ゎ": "wa",
}
_SMALL_Y = {"ゃ": "a", "ゅ": "u", "ょ": "o"}  # with the kana before them: きゃ kya, しゃ sha
_SMALL_VOWELS = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}  # in katakana: ファ fa, ティ ti
_GEMINATE = frozenset({"", "k", "s", "t", "p", "c", "g", "d", "b", "z", "j", "h", "f"})  # っ doubles the next
_LONG = frozenset({"", "a", "i", "u", "e", "o", "h"})  # ー draws out the vowel before it
# A kanji in a Japanese name, whose reading isn't at hand here: one to three morae of _MORA's.
_KANJI = None
_MORA = re.compile(r"(?:[bcdfghjkmnprstvwz]?[hy]?|ts)[aeiou]|n(?![aeiouy])|([bcdfgjkpstz])(?=\1)|t(?=ch)")


def _kana_letter(c: str) -> bool:
    """Whether a character is a hiragana or katakana letter (not ・ or another mark of the block)."""
    return 0x3041 <= ord(c) <= 0x3096 or 0x30A1 <= ord(c) <= 0x30FA


@functools.lru_cache(maxsize=4096)
def _readings(original: str) -> tuple[frozenset[str] | None, ...] | None:
    """An original part of a name read one syllable at a time, each as the set of the ways it is
    romanized (``_KANJI`` for a kanji); None when it has letters caracole can't read (Cyrillic, say).

    Chinese is read in pinyin, in any of each character's readings (重 is zhong, chong or tong) as
    well as pypinyin's in context; ü may be written v or u. Hangul is read by its jamo, kana by
    Hepburn's table. In a name with kana, which is Japanese, a kanji is any one to three morae.
    Latin letters and digits in it read as themselves.
    """
    japanese = any(_kana_letter(c) for c in original)
    readings: list[frozenset[str] | None] = []
    pinyin = _pinyin_readings(original) if has_han(original) and not japanese else iter(())
    fixed = ""
    for c in original:
        letter = fold(c)
        if letter.isascii() and letter.isalnum():
            fixed += letter
            continue
        if fixed:
            readings.append(frozenset({fixed}))
            fixed = ""
        if _HAN.match(c):
            readings.append(_KANJI if japanese else next(pinyin, frozenset()))
        elif c == "々" and japanese:  # the kanji before it again
            readings.append(_KANJI)
        elif 0xAC00 <= ord(c) <= 0xD7A3:  # a Hangul syllable block
            readings.append(_hangul(c))
        elif _kana_letter(c) or c == "ー":
            _kana(readings, chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c)  # katakana as hiragana
        elif _foreign(c):
            return None
    if fixed:
        readings.append(frozenset({fixed}))
    return tuple(readings)


def _pinyin_readings(text: str) -> Iterator[frozenset[str]]:
    """Each Chinese character's readings in pinyin, in order: all of them, and pypinyin's in context."""
    from pypinyin import Style, lazy_pinyin, pinyin

    chars = [c for c in text if _HAN.match(c)]
    in_context = lazy_pinyin(text, errors="ignore")
    for i, c in enumerate(chars):
        found = set(pinyin(c, style=Style.NORMAL, heteronym=True)[0])
        if len(in_context) == len(chars):
            found.add(in_context[i])
        yield frozenset(r for f in found for r in (f, f.replace("v", "u")))


def _hangul(c: str) -> frozenset[str]:
    """A Hangul syllable's romanizations, from its jamo."""
    n = ord(c) - 0xAC00
    initial, medial, final = n // 588, n % 588 // 28, n % 28
    return frozenset(
        i + m + f
        for i in _HANGUL_INITIALS[initial].split(" ")
        for m in _HANGUL_MEDIALS[medial].split(" ")
        for f in _HANGUL_FINALS[final].split(" ")
    )


def _kana(readings: list[frozenset[str] | None], c: str) -> None:
    """Add a kana (as hiragana) to ``readings``: a small ya, yu, yo or vowel joins the kana before it."""
    before = readings[-1] if readings else None
    if c in _SMALL_Y and before:
        v = _SMALL_Y[c]
        joined = {r[:-1] + "y" + v for r in before}
        joined |= {r[:-1] + v for r in before if r[:-1] in ("sh", "ch", "j")}  # しゃ sha, ちゃ cha, じゃ ja
        readings[-1] = frozenset(joined)
    elif c in _SMALL_VOWELS and before:
        v = _SMALL_VOWELS[c]
        joined = {r[:-1] + v for r in before} | {r + v for r in before}
        if "u" in before:  # ウィ wi
            joined.add("w" + v)
        readings[-1] = frozenset(joined)
    elif c == "っ":
        readings.append(_GEMINATE)
    elif c == "ー":
        readings.append(_LONG)
    elif c in _SMALL_VOWELS or c in _SMALL_Y:
        readings.append(frozenset({_SMALL_VOWELS.get(c) or "y" + _SMALL_Y[c]}))
    elif c in _KANA:
        found = set(_KANA[c].split(" "))
        if c == "う" and before and any(r.endswith(("o", "u")) for r in before):
            found.add("")  # a long vowel: ありがとう is arigatou, or arigato
        readings.append(frozenset(found))


def _reads_as(text: str, readings: tuple[frozenset[str] | None, ...]) -> bool:
    """Whether ``text`` (compact Latin letters) is ``readings`` romanized, syllable after syllable."""

    @functools.cache
    def at(i: int, j: int) -> bool:
        if j == len(readings):
            return i == len(text)
        reading = readings[j]
        if reading is _KANJI:
            k = i
            for _ in range(3):
                mora = _MORA.match(text, k)
                if mora is None:
                    return False
                k = mora.end()
                if at(k, j + 1):
                    return True
            return False
        return any(text.startswith(r, i) and at(i + len(r), j + 1) for r in reading)

    return at(0, 0)


def _generic(key: str) -> bool:
    """Whether a key names no song or artist on its own (see ``name_forms``): letters of a script other
    than Latin name one at any length ("爱", "Ты", "ใจ"), Latin ones from two letters ("Ai", "IU")."""
    words = [w for w in key.split("-") if w and w not in GENERIC_WORDS and not w.isdigit()]
    if any(_foreign(c) for w in words for c in w):
        return False
    return sum(len(w) for w in words) < 2


# Traditional -> Simplified, one character for one, for identity keys: each pair is a
# Traditional character and its Simplified form. Derived from OpenCC 1.4.1's
# TSCharacters dictionary (https://github.com/BYVoid/OpenCC, Apache License 2.0):
# every entry that maps one CJK ideograph of the Basic Multilingual Plane to another,
# taking its first candidate, with chains followed to their end (薴 → 苎).
_T2S_PAIRS = (
    "㑯㑔㑳㑇㑶㐹㓨刾㘚㘎㜄㚯㜏㛣㠏㟆㥮㤘㩜㨫㩳㧐㩵擜䁻䀥䃮鿎䊷䌶䋙䌺䋚䌻䋹䌿䋻䌾䍦䍠䎱䎬䙡䙌䜀䜧"
    "䝼䞍䥇䦂䥑鿏䥱䥾䦛䦶䦟䦷䯀䯅䰾鲃䱷䲣䱽䲝䲁鳚䲘鳤䴉鹮丟丢並并乾干亂乱亙亘亞亚佇伫佈布佔占併并"
    "來来侖仑侶侣侷局俁俣係系俔伣俠侠俥伡俬私倀伥倆俩倈俫倉仓個个們们倖幸倫伦倲㑈偉伟偑㐽側侧偵侦"
    "偽伪傌㐷傑杰傖伧傘伞備备傢家傭佣傯偬傳传傴伛債债傷伤傾倾僂偻僅仅僉佥僑侨僕仆僞伪僥侥僨偾僱雇"
    "價价儀仪儁俊儂侬億亿儈侩儉俭儎傤儐傧儔俦儕侪儘尽償偿優优儲储儷俪儸㑩儺傩儻傥儼俨兇凶兌兑兒儿"
    "兗兖內内兩两冊册冑胄冪幂凈净凍冻凜凛凱凯別别刪删剄刭則则剋克剎刹剗刬剛刚剝剥剮剐剴剀創创剷铲"
    "劃划劄札劇剧劉刘劊刽劌刿劍剑劏㓥劑剂劚㔉勁劲動动務务勛勋勝胜勞劳勢势勩勚勱劢勳勋勵励勸劝勻匀"
    "匭匦匯汇匱匮區区協协卹恤卻却卽即厙厍厠厕厤历厭厌厲厉厴厣參参叄叁叢丛吒咤吳吴吶呐呂吕咼呙員员"
    "唄呗唸念問问啓启啞哑啟启啢唡喎㖞喚唤喪丧喫吃喬乔單单喲哟嗆呛嗇啬嗊唝嗎吗嗚呜嗩唢嗶哔嘆叹嘍喽"
    "嘓啯嘔呕嘖啧嘗尝嘜唛嘩哗嘮唠嘯啸嘰叽嘵哓嘸呒嘽啴噁恶噓嘘噚㖊噝咝噠哒噥哝噦哕噯嗳噲哙噴喷噸吨"
    "噹当嚀咛嚇吓嚌哜嚐尝嚕噜嚙啮嚥咽嚦呖嚨咙嚮向嚲亸嚳喾嚴严嚶嘤囀啭囁嗫囂嚣囅冁囈呓囉啰囌苏囑嘱"
    "囪囱圇囵國国圍围園园圓圆圖图團团垻坝埡垭埰采執执堅坚堊垩堖垴堝埚堯尧報报場场塊块塋茔塏垲塒埘"
    "塗涂塚冢塢坞塤埙塵尘塹堑墊垫墜坠墮堕墰坛墳坟墶垯墻墙墾垦壇坛壋垱壎埙壓压壘垒壙圹壚垆壜坛壞坏"
    "壟垄壠垅壢坜壩坝壪塆壯壮壺壶壼壸壽寿夠够夢梦夥伙夾夹奐奂奧奥奩奁奪夺奬奖奮奋奼姹妝妆姍姗姦奸"
    "娛娱婁娄婦妇婭娅媧娲媯妫媰㛀媼媪媽妈嫋袅嫗妪嫵妩嫺娴嫻娴嫿婳嬀妫嬃媭嬈娆嬋婵嬌娇嬙嫱嬡嫒嬤嬷"
    "嬪嫔嬰婴嬸婶孃娘孋㛤孌娈孫孙學学孿孪宮宫寀采寢寝實实寧宁審审寫写寬宽寵宠寶宝將将專专尋寻對对"
    "導导尷尴屆届屍尸屓屃屜屉屢屡層层屨屦屬属岡冈峯峰峴岘島岛峽峡崍崃崑昆崗岗崙仑崢峥崬岽嵐岚嵗岁"
    "嵾㟥嶁嵝嶄崭嶇岖嶔嵚嶗崂嶠峤嶢峣嶧峄嶨峃嶮崄嶸嵘嶺岭嶼屿嶽岳巋岿巒峦巔巅巖岩巰巯巹卺帥帅師师"
    "帳帐帶带幀帧幃帏幓㡎幗帼幘帻幟帜幣币幫帮幬帱幷并幹干幾几庫库廁厕廂厢廄厩廈厦廎庼廕荫廚厨廝厮"
    "廟庙廠厂廡庑廢废廣广廩廪廬庐廳厅弒弑弔吊弳弪張张強强彆别彈弹彌弥彎弯彔录彙汇彠彟彥彦彫雕彲彨"
    "彿佛後后徑径從从徠徕復复徵征徹彻恆恒恥耻悅悦悞悮悵怅悶闷悽凄惡恶惱恼惲恽惻恻愛爱愜惬愨悫愴怆"
    "愷恺愾忾慄栗態态慍愠慘惨慚惭慟恸慣惯慤悫慪怄慫怂慮虑慳悭慶庆慺㥪慼戚慾欲憂忧憊惫憐怜憑凭憒愦"
    "憖慭憚惮憤愤憫悯憮怃憲宪憶忆懇恳應应懌怿懍懔懞蒙懟怼懣懑懤㤽懨恹懲惩懶懒懷怀懸悬懺忏懼惧懾慑"
    "戀恋戇戆戔戋戧戗戩戬戰战戱戯戲戏戶户扞捍拋抛拚拼挩捝挱挲挾挟捨舍捫扪捱挨捲卷掃扫掄抡掆㧏掗挜"
    "掙挣掛挂採采揀拣揚扬換换揮挥揯搄損损搖摇搗捣搧扇搵揾搶抢摑掴摜掼摟搂摯挚摳抠摶抟摺折摻掺撈捞"
    "撏挦撐撑撓挠撝㧑撟挢撣掸撥拨撫抚撲扑撳揿撻挞撾挝撿捡擁拥擄掳擇择擊击擋挡擓㧟擔担據据擠挤擡抬"
    "擣捣擬拟擯摈擰拧擱搁擲掷擴扩擷撷擺摆擻擞擼撸擽㧰擾扰攄摅攆撵攏拢攔拦攖撄攙搀攛撺攜携攝摄攢攒"
    "攣挛攤摊攪搅攬揽敎教敓敚敗败敘叙敵敌數数斂敛斃毙斆敩斕斓斬斩斷断於于旂旗旣既昇升時时晉晋晝昼"
    "暈晕暉晖暘旸暢畅暫暂曄晔曆历曇昙曉晓曏向曖暧曠旷曨昽曬晒書书會会朧胧朮术東东枴拐柵栅柺拐査查"
    "桿杆梔栀梘枧條条梟枭梲棁棄弃棊棋棖枨棗枣棟栋棡㭎棧栈棲栖棶梾椏桠椲㭏楊杨楓枫楨桢業业極极榘矩"
    "榦干榪杩榮荣榲榅榿桤構构槍枪槓杠槤梿槧椠槨椁槮椮槳桨槶椢槼椝樁桩樂乐樅枞樑梁樓楼標标樞枢樢㭤"
    "樣样樧榝樫㭴樳桪樸朴樹树樺桦樿椫橈桡橋桥機机橢椭橫横檁檩檉柽檔档檜桧檟槚檢检檣樯檮梼檯台檳槟"
    "檸柠檻槛櫃柜櫓橹櫚榈櫛栉櫝椟櫞橼櫟栎櫥橱櫧槠櫨栌櫪枥櫫橥櫬榇櫱蘖櫳栊櫸榉櫻樱欄栏欅榉權权欏椤"
    "欒栾欖榄欞棂欽钦歎叹歐欧歟欤歡欢歲岁歷历歸归歿殁殘残殞殒殤殇殨㱮殫殚殭僵殮殓殯殡殰㱩殲歼殺杀"
    "殻壳殼壳毀毁毆殴毿毵氂牦氈毡氌氇氣气氫氢氬氩氳氲氾泛汎泛汙污決决沒没沖冲況况泝溯洩泄洶汹浹浃"
    "涇泾涗涚涼凉淒凄淚泪淥渌淨净淩凌淪沦淵渊淶涞淺浅渙涣減减渢沨渦涡測测渾浑湊凑湞浈湧涌湯汤溈沩"
    "準准溝沟溫温溮浉溳涢溼湿滄沧滅灭滌涤滎荥滙汇滬沪滯滞滲渗滷卤滸浒滻浐滾滚滿满漁渔漊溇漚沤漢汉"
    "漣涟漬渍漲涨漵溆漸渐漿浆潁颍潑泼潔洁潙沩潚㴋潛潜潤润潯浔潰溃潷滗潿涠澀涩澆浇澇涝澐沄澗涧澠渑"
    "澤泽澦滪澩泶澮浍澱淀澾㳠濁浊濃浓濄㳡濕湿濘泞濚溁濛蒙濜浕濟济濤涛濧㳔濫滥濰潍濱滨濺溅濼泺濾滤"
    "瀂澛瀅滢瀆渎瀇㲿瀉泻瀋沈瀏浏瀕濒瀘泸瀝沥瀟潇瀠潆瀦潴瀧泷瀨濑瀰弥瀲潋瀾澜灃沣灄滠灑洒灕漓灘滩"
    "灝灏灡㳕灣湾灤滦灧滟灩滟災灾為为烏乌烴烃無无煉炼煒炜煙烟煢茕煥焕煩烦煬炀煱㶽熅煴熒荧熗炝熱热"
    "熲颎熾炽燁烨燈灯燉炖燒烧燙烫燜焖營营燦灿燬毁燭烛燴烩燶㶶燻熏燼烬燾焘爍烁爐炉爛烂爭争爲为爺爷"
    "爾尔牀床牆墙牘牍牴抵牽牵犖荦犛牦犢犊犧牺狀状狹狭狽狈猙狰猶犹猻狲獁犸獃呆獄狱獅狮獎奖獨独獪狯"
    "獫猃獮狝獰狞獱㺍獲获獵猎獷犷獸兽獺獭獻献獼猕玀猡現现琱雕琺珐琿珲瑋玮瑒玚瑣琐瑤瑶瑩莹瑪玛瑲玱"
    "璉琏璡琎璣玑璦瑷璫珰璯㻅環环璵玙璸瑸璽玺璿璇瓊琼瓏珑瓔璎瓚瓒甌瓯甕瓮產产産产畝亩畢毕畫画異异"
    "畵画當当疇畴疊叠痙痉痠酸痾疴瘂痖瘋疯瘍疡瘓痪瘞瘗瘡疮瘧疟瘮瘆瘲疭瘺瘘瘻瘘療疗癆痨癇痫癉瘅癒愈"
    "癘疠癟瘪癡痴癢痒癤疖癥症癧疬癩癞癬癣癭瘿癮瘾癰痈癱瘫癲癫發发皁皂皚皑皰疱皸皲皺皱盃杯盜盗盞盏"
    "盡尽監监盤盘盧卢盪荡眞真眥眦眾众睏困睜睁睞睐瞘眍瞜䁖瞞瞒瞶瞆瞼睑矇蒙矓眬矚瞩矯矫硃朱硜硁硤硖"
    "硨砗硯砚碕埼碩硕碭砀碸砜確确碼码碽䂵磑硙磚砖磠硵磣碜磧碛磯矶磽硗磾䃅礄硚礎础礙碍礦矿礪砺礫砾"
    "礬矾礱砻祕秘祿禄禍祸禎祯禕祎禡祃禦御禪禅禮礼禰祢禱祷禿秃秈籼稅税稈秆稏䅉稜棱稟禀種种稱称穀谷"
    "穇䅟穌稣積积穎颖穠秾穡穑穢秽穩稳穫获穭穞窩窝窪洼窮穷窯窑窵窎窶窭窺窥竄窜竅窍竇窦竈灶竊窃竪竖"
    "競竞筆笔筍笋筧笕筴䇲箇个箋笺箏筝箚札節节範范築筑篋箧篔筼篠筿篤笃篩筛篳筚簀箦簍篓簑蓑簞箪簡简"
    "簣篑簫箫簹筜簽签簾帘籃篮籌筹籔䉤籙箓籛篯籜箨籟籁籠笼籤签籩笾籪簖籬篱籮箩籲吁粵粤糉粽糝糁糞粪"
    "糧粮糰团糲粝糴籴糶粜糹纟糾纠紀纪紂纣約约紅红紆纡紇纥紈纨紉纫紋纹納纳紐纽紓纾純纯紕纰紖纼紗纱"
    "紘纮紙纸級级紛纷紜纭紝纴紡纺紬䌷紮扎細细紱绂紲绁紳绅紵纻紹绍紺绀紼绋紿绐絀绌終终絃弦組组絅䌹"
    "絆绊絎绗結结絕绝絛绦絝绔絞绞絡络絢绚給给絨绒絰绖統统絲丝絳绛絶绝絹绢綁绑綃绡綆绠綈绨綉绣綌绤"
    "綏绥綐䌼綑捆經经綜综綞缍綠绿綢绸綣绻綫线綬绶維维綯绹綰绾綱纲網网綳绷綴缀綵彩綸纶綹绺綺绮綻绽"
    "綽绰綾绫綿绵緄绲緇缁緊紧緋绯緑绿緒绪緓绬緔绱緗缃緘缄緙缂線线緝缉緞缎締缔緡缗緣缘緦缌編编緩缓"
    "緬缅緯纬緱缑緲缈練练緶缏緹缇緻致緼缊縈萦縉缙縊缢縋缒縐绉縑缣縕缊縗缞縛缚縝缜縞缟縟缛縣县縧绦"
    "縫缝縭缡縮缩縱纵縲缧縳䌸縴纤縵缦縶絷縷缕縹缥總总績绩繃绷繅缫繆缪繒缯織织繕缮繚缭繞绕繡绣繢缋"
    "繩绳繪绘繫系繭茧繮缰繯缳繰缲繳缴繸䍁繹绎繼继繽缤繾缱繿䍀纇颣纈缬纊纩續续纍累纏缠纓缨纔才纖纤"
    "纘缵纜缆缽钵罃䓨罈坛罌罂罎坛罰罚罵骂罷罢羅罗羆罴羈羁羋芈羣群羥羟羨羡義义羶膻習习翫玩翬翚翹翘"
    "翽翙耬耧耮耢聖圣聞闻聯联聰聪聲声聳耸聵聩聶聂職职聹聍聽听聾聋肅肃脅胁脈脉脛胫脣唇脩修脫脱脹胀"
    "腎肾腖胨腡脶腦脑腫肿腳脚腸肠膃腽膕腘膚肤膞䏝膠胶膩腻膽胆膾脍膿脓臉脸臍脐臏膑臘腊臚胪臟脏臠脔"
    "臢臜臥卧臨临臺台與与興兴舉举舊旧舖铺舘馆艙舱艤舣艦舰艫舻艱艰艷艳芻刍苧苎茲兹荊荆莊庄莖茎莢荚"
    "莧苋華华菴庵菸烟萇苌萊莱萬万萴荝萵莴葉叶葒荭葤荮葦苇葯药葷荤蒐搜蒓莼蒔莳蒕蒀蒞莅蒼苍蓀荪蓆席"
    "蓋盖蓮莲蓯苁蓴莼蓽荜蔔卜蔘参蔞蒌蔣蒋蔥葱蔦茑蔭荫蕁荨蕆蒇蕎荞蕒荬蕓芸蕕莸蕘荛蕢蒉蕩荡蕪芜蕭萧"
    "蕷蓣薀蕰薈荟薊蓟薌芗薑姜薔蔷薘荙薟莶薦荐薩萨薳䓕薴苎薵䓓薹苔薺荠藍蓝藎荩藝艺藥药藪薮藭䓖藴蕴"
    "藶苈藹蔼藺蔺蘀萚蘄蕲蘆芦蘇苏蘊蕴蘋苹蘚藓蘞蔹蘢茏蘭兰蘺蓠蘿萝虆蔂處处虛虚虜虏號号虧亏虯虬蛺蛱"
    "蛻蜕蜆蚬蝕蚀蝟猬蝦虾蝨虱蝸蜗螄蛳螞蚂螢萤螮䗖螻蝼螿螀蟄蛰蟈蝈蟎螨蟣虮蟬蝉蟯蛲蟲虫蟶蛏蟻蚁蠁蚃"
    "蠅蝇蠆虿蠍蝎蠐蛴蠑蝾蠔蚝蠟蜡蠣蛎蠨蟏蠱蛊蠶蚕蠻蛮衆众衊蔑術术衕同衚胡衛卫衝冲袞衮袷夹裊袅裏里"
    "補补裝装裡里製制複复褌裈褘袆褲裤褳裢褸褛褻亵襇裥襉裥襏袯襖袄襝裣襠裆襤褴襪袜襬摆襯衬襲袭襴襕"
    "覈核見见覎觃規规覓觅視视覘觇覡觋覥觍覦觎親亲覬觊覯觏覲觐覷觑覺觉覽览覿觌觀观觴觞觶觯觸触訁讠"
    "訂订訃讣計计訊讯訌讧討讨訐讦訒讱訓训訕讪訖讫託托記记訛讹訝讶訟讼訢䜣訣诀訥讷訩讻訪访設设許许"
    "訴诉訶诃診诊註注証证詁诂詆诋詎讵詐诈詒诒詔诏評评詖诐詗诇詘诎詛诅詞词詠咏詡诩詢询詣诣試试詩诗"
    "詫诧詬诟詭诡詮诠詰诘話话該该詳详詵诜詼诙詿诖誄诔誅诛誆诓誇夸誌志認认誑诳誒诶誕诞誘诱誚诮語语"
    "誠诚誡诫誣诬誤误誥诰誦诵誨诲說说説说誰谁課课誶谇誹诽誼谊誾訚調调諂谄諄谆談谈諉诿請请諍诤諏诹"
    "諑诼諒谅論论諗谂諛谀諜谍諝谞諞谝諡谥諢诨諤谔諦谛諧谐諫谏諭谕諮咨諱讳諳谙諶谌諷讽諸诸諺谚諼谖"
    "諾诺謀谋謁谒謂谓謄誊謅诌謊谎謎谜謐谧謔谑謖谡謗谤謙谦謚谥講讲謝谢謠谣謡谣謨谟謫谪謬谬謭谫謳讴"
    "謹谨謾谩譁哗證证譎谲譏讥譖谮識识譙谯譚谭譜谱譟噪譫谵譭毁譯译議议譴谴護护譸诪譽誉譾谫讀读讅谉"
    "變变讋詟讌䜩讎雠讒谗讓让讕谰讖谶讚赞讜谠讞谳谿溪豈岂豎竖豐丰豔艳豬猪豶豮貍狸貓猫貙䝙貝贝貞贞"
    "貟贠負负財财貢贡貧贫貨货販贩貪贪貫贯責责貯贮貰贳貲赀貳贰貴贵貶贬買买貸贷貺贶費费貼贴貽贻貿贸"
    "賀贺賁贲賂赂賃赁賄贿賅赅資资賈贾賊贼賑赈賒赊賓宾賕赇賙赒賚赉賜赐賞赏賠赔賡赓賢贤賣卖賤贱賦赋"
    "賧赕質质賫赍賬账賭赌賰䞐賴赖賵赗賺赚賻赙購购賽赛賾赜贄贽贅赘贇赟贈赠贊赞贋赝贍赡贏赢贐赆贓赃"
    "贔赑贖赎贗赝贛赣贜赃赬赪趕赶趙赵趨趋趲趱跡迹踐践踰逾踴踊蹌跄蹕跸蹟迹蹠跖蹣蹒蹤踪蹺跷躂跶躉趸"
    "躊踌躋跻躍跃躎䟢躑踯躒跞躓踬躕蹰躚跹躡蹑躥蹿躦躜躪躏軀躯車车軋轧軌轨軍军軑轪軒轩軔轫軛轭軟软"
    "軤轷軫轸軲轱軸轴軹轵軺轺軻轲軼轶軾轼較较輅辂輇辁輈辀載载輊轾輒辄輓挽輔辅輕轻輛辆輜辎輝辉輞辋"
    "輟辍輥辊輦辇輩辈輪轮輬辌輯辑輳辏輸输輻辐輼辒輾辗輿舆轀辒轂毂轄辖轅辕轆辘轉转轍辙轎轿轔辚轟轰"
    "轡辔轢轹轤轳辦办辭辞辮辫辯辩農农迴回逕径這这連连週周進进遊游運运過过達达違违遙遥遜逊遞递遠远"
    "遡溯適适遲迟遶绕遷迁選选遺遗遼辽邁迈還还邇迩邊边邏逻邐逦郟郏郵邮鄆郓鄉乡鄒邹鄔邬鄖郧鄧邓鄭郑"
    "鄰邻鄲郸鄴邺鄶郐鄺邝酇酂酈郦醃腌醖酝醜丑醞酝醟蒏醣糖醫医醬酱醱酦釀酿釁衅釃酾釅酽釋释釐厘釒钅"
    "釓钆釔钇釕钌釗钊釘钉釙钋針针釣钓釤钐釦扣釧钏釩钒釵钗釷钍釹钕釺钎釾䥺鈀钯鈁钫鈃钘鈄钭鈅钥鈈钚"
    "鈉钠鈍钝鈎钩鈐钤鈑钣鈒钑鈔钞鈕钮鈞钧鈡钟鈣钙鈥钬鈦钛鈧钪鈮铌鈰铈鈳钶鈴铃鈷钴鈸钹鈹铍鈺钰鈽钸"
    "鈾铀鈿钿鉀钾鉅巨鉆钻鉈铊鉉铉鉋铇鉍铋鉑铂鉕钷鉗钳鉚铆鉛铅鉞钺鉢钵鉤钩鉦钲鉬钼鉭钽鉳锫鉶铏鉸铰"
    "鉺铒鉻铬鉿铪銀银銃铳銅铜銍铚銑铣銓铨銖铢銘铭銚铫銛铦銜衔銠铑銣铷銥铱銦铟銨铵銩铥銪铕銫铯銬铐"
    "銱铞銳锐銷销銹锈銻锑銼锉鋁铝鋃锒鋅锌鋇钡鋌铤鋏铗鋒锋鋙铻鋝锊鋟锓鋣铘鋤锄鋥锃鋦锔鋨锇鋩铓鋪铺"
    "鋭锐鋮铖鋯锆鋰锂鋱铽鋶锍鋸锯鋼钢錁锞錄录錆锖錇锫錈锩錏铔錐锥錒锕錕锟錘锤錙锱錚铮錛锛錟锬錠锭"
    "錡锜錢钱錦锦錨锚錩锠錫锡錮锢錯错録录錳锰錶表錸铼錼镎鍀锝鍁锨鍃锪鍅钫鍆钔鍇锴鍈锳鍊炼鍋锅鍍镀"
    "鍔锷鍘铡鍚钖鍛锻鍠锽鍤锸鍥锲鍩锘鍬锹鍰锾鍵键鍶锶鍺锗鍼针鍾钟鎂镁鎄锿鎇镅鎊镑鎌镰鎔镕鎖锁鎘镉"
    "鎚锤鎛镈鎡镃鎢钨鎣蓥鎦镏鎧铠鎩铩鎪锼鎬镐鎭镇鎮镇鎰镒鎲镋鎳镍鎵镓鎶鿔鎸镌鎿镎鏃镞鏇旋鏈链鏌镆"
    "鏍镙鏐镠鏑镝鏗铿鏘锵鏜镗鏝镘鏞镛鏟铲鏡镜鏢镖鏤镂鏨錾鏰镚鏵铧鏷镤鏹镪鏺䥽鏽锈鐃铙鐋铴鐐镣鐒铹"
    "鐓镦鐔镡鐘钟鐙镫鐝镢鐠镨鐥䦅鐦锎鐧锏鐨镄鐫镌鐮镰鐯䦃鐲镯鐳镭鐵铁鐶镮鐸铎鐺铛鐿镱鑄铸鑊镬鑌镔"
    "鑑鉴鑒鉴鑔镲鑕锧鑞镴鑠铄鑣镳鑥镥鑭镧鑰钥鑱镵鑲镶鑷镊鑹镩鑼锣鑽钻鑾銮鑿凿钁镢钂镋長长門门閂闩"
    "閃闪閆闫閈闬閉闭開开閌闶閎闳閏闰閑闲閒闲間间閔闵閘闸閡阂閣阁閤合閥阀閨闺閩闽閫阃閬阆閭闾閱阅"
    "閲阅閶阊閹阉閻阎閼阏閽阍閾阈閿阌闃阒闆板闇暗闈闱闊阔闋阕闌阑闍阇闐阗闒阘闓闿闔阖闕阙闖闯關关"
    "闞阚闠阓闡阐闢辟闤阛闥闼陘陉陝陕陞升陣阵陰阴陳陈陸陆陽阳隉陧隊队階阶隕陨際际隨随險险隯陦隱隐"
    "隴陇隸隶隻只雋隽雖虽雙双雛雏雜杂雞鸡離离難难雲云電电霑沾霢霡霧雾霽霁靂雳靄霭靆叇靈灵靉叆靚靓"
    "靜静靝靔靦腼靨靥鞏巩鞝绱鞦秋鞽鞒韁缰韃鞑韆千韉鞯韋韦韌韧韍韨韓韩韙韪韜韬韝鞲韞韫韻韵響响頁页"
    "頂顶頃顷項项順顺頇顸須须頊顼頌颂頎颀頏颃預预頑顽頒颁頓顿頗颇領领頜颌頡颉頤颐頦颏頭头頮颒頰颊"
    "頲颋頴颕頷颔頸颈頹颓頻频頽颓顆颗題题額额顎颚顏颜顒颙顓颛顔颜願愿顙颡顛颠類类顢颟顥颢顧顾顫颤"
    "顬颥顯显顰颦顱颅顳颞顴颧風风颭飐颮飑颯飒颱台颳刮颶飓颸飔颺飏颻飖颼飕飀飗飄飘飆飙飈飚飛飞飠饣"
    "飢饥飣饤飥饦飩饨飪饪飫饫飭饬飯饭飱飧飲饮飴饴飼饲飽饱飾饰飿饳餃饺餄饸餅饼餈糍餉饷養养餌饵餎饹"
    "餏饻餑饽餒馁餓饿餕馂餖饾餘余餚肴餛馄餜馃餞饯餡馅館馆餬糊餱糇餳饧餵喂餶馉餷馇餺馎餼饩餾馏餿馊"
    "饁馌饃馍饅馒饈馐饉馑饊馓饋馈饌馔饑饥饒饶饗飨饜餍饞馋饢馕馬马馭驭馮冯馱驮馳驰馴驯馹驲駁驳駐驻"
    "駑驽駒驹駔驵駕驾駘骀駙驸駛驶駝驼駟驷駡骂駢骈駭骇駰骃駱骆駸骎駿骏騁骋騂骍騅骓騌骔騍骒騎骑騏骐"
    "騖骛騙骗騤骙騧䯄騫骞騭骘騮骝騰腾騶驺騷骚騸骟騾骡驀蓦驁骜驂骖驃骠驄骢驅驱驊骅驌骕驍骁驏骣驕骄"
    "驗验驚惊驛驿驟骤驢驴驤骧驥骥驦骦驪骊驫骉骯肮髏髅髒脏體体髕髌髖髋髮发鬆松鬍胡鬚须鬢鬓鬥斗鬧闹"
    "鬨哄鬩阋鬮阄鬱郁鬹鬶魎魉魘魇魚鱼魛鱽魢鱾魨鲀魯鲁魴鲂魷鱿魺鲄鮁鲅鮃鲆鮊鲌鮋鲉鮍鲏鮎鲇鮐鲐鮑鲍"
    "鮒鲋鮓鲊鮚鲒鮜鲘鮝鲞鮞鲕鮣䲟鮦鲖鮪鲔鮫鲛鮭鲑鮮鲜鮳鲓鮶鲪鮺鲝鯀鲧鯁鲠鯇鲩鯉鲤鯊鲨鯒鲬鯔鲻鯕鲯"
    "鯖鲭鯗鲞鯛鲷鯝鲴鯡鲱鯢鲵鯤鲲鯧鲳鯨鲸鯪鲮鯫鲰鯰鲶鯴鲺鯷鳀鯽鲫鯿鳊鰁鳈鰂鲗鰃鳂鰆䲠鰈鲽鰉鳇鰌䲡"
    "鰍鳅鰏鲾鰐鳄鰒鳆鰓鳃鰛鳁鰜鳒鰟鳑鰠鳋鰣鲥鰥鳏鰧䲢鰨鳎鰩鳐鰭鳍鰮鳁鰱鲢鰲鳌鰳鳓鰵鳘鰷鲦鰹鲣鰺鲹"
    "鰻鳗鰼鳛鰾鳔鱂鳉鱅鳙鱈鳕鱉鳖鱒鳟鱔鳝鱖鳜鱗鳞鱘鲟鱝鲼鱟鲎鱠鲙鱣鳣鱤鳡鱧鳢鱨鲿鱭鲚鱯鳠鱷鳄鱸鲈"
    "鱺鲡鳥鸟鳧凫鳩鸠鳬凫鳲鸤鳳凤鳴鸣鳶鸢鳾䴓鴆鸩鴇鸨鴉鸦鴒鸰鴕鸵鴛鸳鴝鸲鴞鸮鴟鸱鴣鸪鴦鸯鴨鸭鴯鸸"
    "鴰鸹鴴鸻鴷䴕鴻鸿鴿鸽鵁䴔鵂鸺鵃鸼鵐鹀鵑鹃鵒鹆鵓鹁鵜鹈鵝鹅鵠鹄鵡鹉鵪鹌鵬鹏鵮鹐鵯鹎鵰雕鵲鹊鵷鹓"
    "鵾鹍鶄䴖鶇鸫鶉鹑鶊鹒鶓鹋鶖鹙鶘鹕鶚鹗鶡鹖鶥鹛鶩鹜鶪䴗鶬鸧鶯莺鶲鹟鶴鹤鶹鹠鶺鹡鶻鹘鶼鹣鶿鹚鷀鹚"
    "鷁鹢鷂鹞鷄鸡鷉䴘鷊鹝鷓鹧鷖鹥鷗鸥鷙鸷鷚鹨鷥鸶鷦鹪鷫鹔鷯鹩鷲鹫鷳鹇鷴鹇鷸鹬鷹鹰鷺鹭鷽鸴鸂㶉鸇鹯"
    "鸊䴙鸌鹱鸏鹲鸕鸬鸘鹴鸚鹦鸛鹳鸝鹂鸞鸾鹵卤鹹咸鹺鹾鹼碱鹽盐麗丽麥麦麩麸麪面麫面麯曲麴曲麵面麼么"
    "麽么黃黄黌黉點点黨党黲黪黴霉黶黡黷黩黽黾黿鼋鼂鼌鼉鼍鼕冬鼴鼹齊齐齋斋齎赍齏齑齒齿齔龀齕龁齗龂"
    "齙龅齜龇齟龃齠龆齡龄齣出齦龈齧啮齪龊齬龉齲龋齶腭齷龌龍龙龎厐龐庞龑䶮龔龚龕龛龜龟鿁䜤鿓鿒"
)
