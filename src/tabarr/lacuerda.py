"""LaCuerda (acordes.lacuerda.net): chord sheets for Spanish songs.

Ultimate Guitar's sitemaps hide every artist with an accented name behind bare
ids, but a LaCuerda artist URL can be built from the name. What the pages look
like (captured 18 October 2026):

- **Artist slugs** are the name lowercased, with accents stripped, "ñ" written
  "ni", each space turned into "_" and any other punctuation removed without a
  trace ("Fito & Fitipaldis" → ``fito__fitipaldis``). A leading article is
  dropped ("Las Pastillas del Abuelo" → ``pastillas_del_abuelo``).
"""

from __future__ import annotations

import re
import unicodedata

from tabarr.normalize import fold

BASE_URL = "https://acordes.lacuerda.net"

_ARTICLES = frozenset({"el", "la", "los", "las", "the"})
_NOT_SLUG = re.compile(r"[^a-z0-9 ]")
_AND_WORD = re.compile(r"(?i)(?<!\S)y(?!\S)")


def _words(name: str) -> list[str]:
    """The name's slug words. Removed punctuation leaves an empty word behind."""
    s = unicodedata.normalize("NFC", name).lower().replace("ñ", "ni")
    s = _NOT_SLUG.sub("", fold(" ".join(s.split())))
    return s.strip().split(" ") if s.strip() else []


def _join(words: list[str]) -> str:
    return "_".join(words)


def artist_slug(name: str) -> str:
    """LaCuerda's slug for an artist: "Joaquín Sabina" → ``joaquin_sabina``.

    Returns "" when nothing of the name survives (a name in Chinese characters,
    say); LaCuerda can't be asked about that artist.
    """
    words = _words(name)
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    return _join(words)


def artist_slug_candidates(name: str) -> tuple[str, ...]:
    """Slugs worth trying for an artist, best guess first.

    After :func:`artist_slug` come the slug that keeps a leading article and the
    slug with "y" and "&" swapped, because sources disagree on both
    (Spotify's "Fito y Fitipaldis" is LaCuerda's ``fito__fitipaldis``). Each
    extra candidate costs a request only when the ones before it miss.
    """
    variants = [name]
    if _AND_WORD.search(name):
        variants.append(_AND_WORD.sub("&", name))
    if "&" in name:
        variants.append(name.replace("&", " y "))
    out: list[str] = []
    for variant in variants:
        for slug in (artist_slug(variant), _join(_words(variant))):
            if slug and slug not in out:
                out.append(slug)
    return tuple(out)


def artist_url(slug: str) -> str:
    """The artist page: ``artist_url("soda_stereo")`` → ".../soda_stereo/"."""
    if not slug:
        raise ValueError("empty LaCuerda artist slug")
    return f"{BASE_URL}/{slug}/"


def version_url(artist: str, song: str, n: int) -> str:
    """The page of version ``n`` of a song: ``song.shtml`` for 1, ``song-n.shtml`` after that."""
    if not artist or not song:
        raise ValueError("empty LaCuerda artist or song slug")
    if n < 1:
        raise ValueError(f"LaCuerda version numbers start at 1, not {n}")
    suffix = "" if n == 1 else f"-{n}"
    return f"{BASE_URL}/{artist}/{song}{suffix}.shtml"
