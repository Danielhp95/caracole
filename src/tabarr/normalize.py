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
"""

from __future__ import annotations

import re
import unicodedata

VARIANT_TOKENS = ("intro", "solo", "outro", "riff", "lesson", "acoustic", "live", "unplugged")

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
_DASH_SUFFIX = re.compile(
    r"\s+[-–—]\s+(?:"
    r"(?:\d{4}\s+)?(?:digital\s+)?remaster(?:ed)?(?:\s+(?:version|edition|\d{4}))*"
    r"|remasterizad[oa](?:\s+\d{4})?"
    r"|live(?:\s.*)?"
    r"|(?:mtv\s+)?unplugged(?:\s.*)?"
    r"|acoustic(?:\s+version)?"
    r"|radio\s+edit|single\s+version|album\s+version|edit|demo|bonus\s+track"
    r"|mono|stereo|(?:\d{4}\s+)?(?:stereo|mono)\s+(?:mix|version)"
    r")\s*$",
    re.IGNORECASE,
)
_PAREN_FEAT = re.compile(r"\s*[\(\[](?:feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]", re.IGNORECASE)
_PAREN_SUFFIX = re.compile(
    r"\s*[\(\[](?:"
    r"live(?:\s+(?:at|from|in|on)\b[^\)\]]*)?"
    r"|(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?"
    r"|remasterizad[oa](?:\s+\d{4})?"
    r"|acoustic(?:\s+version)?|(?:mtv\s+)?unplugged"
    r"|radio\s+edit|mono|stereo"
    r")[\)\]]",
    re.IGNORECASE,
)


def fold(s: str) -> str:
    """Lowercase, strip accents and transliterate letters NFKD can't decompose."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.translate(_TRANSLIT).lower()


def clean_title(title: str) -> str:
    """Drop Spotify's version suffixes: remasters, live, featurings, radio edits."""
    prev = None
    cur = title.strip()
    while cur != prev:
        prev = cur
        cur = _PAREN_FEAT.sub("", cur)
        cur = _PAREN_SUFFIX.sub("", cur)
        cur = _DASH_SUFFIX.sub("", cur).strip()
    return cur or title.strip()


def title_variant(title: str) -> str | None:
    """"acoustic" or "live" when the source title says so, else None."""
    suffix = title[len(clean_title(title)) :].lower()
    if "acoustic" in suffix or "unplugged" in suffix:
        return "acoustic"
    if "live" in suffix:
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


def split_variant(song_key: str) -> tuple[str, str | None]:
    """Split a trailing variant label off a song key: ``x-intro`` → (``x``, ``intro``)."""
    head, sep, last = song_key.rpartition("-")
    if sep and head and last in VARIANT_TOKENS:
        return head, last
    return song_key, None


def identity_key(artist: str, title: str) -> str:
    """The identity of a song: the same song from any source gets the same key."""
    return f"{slug_key(artist)}/{slug_key(clean_title(title))}"


def display_key(artist: str, title: str) -> str:
    """How a song is written in overrides.toml and on the to-do page."""
    return f"{artist.strip()} - {clean_title(title)}"


def has_han(s: str) -> bool:
    """Whether the text contains Chinese characters."""
    return _HAN.search(s) is not None


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
