"""The name a file caracole keeps in a song's folder is downloaded under, and the header that names it.

A song's Guitar Pro, Power Tab and score files stay ``guitar-N.<ext>`` and ``score-N.<ext>`` in its folder (inbox.py,
gtptabs_fetch.py): a download is named for the song, ``<Artist> - <Title>.<ext>``, its second file
``<Artist> - <Title> (2).<ext>`` (the file's N, from 2 on), so that it still says what it is in a downloads folder.
The name is one every system takes: no ``/ \\ : * ? " < > |``, no control character (a tab or a new line is a
space, any other ``_``) and no invisible formatting one (a direction mark), never a dot or a space at either end
(Windows drops them; a leading dot hides a file), and its stem at most ``MAX_BYTES`` bytes of UTF-8, cut on a
whole character, the longer of the two names first, so that a long artist leaves the title its half and the dash
between; accents and Chinese stay as they are. A part with nothing left (dots alone) is none, and a song with no
name left is its file's own name.

``content_disposition`` is the header caracole serve sends such a file with (web/app.py): an attachment named in
ASCII for an old browser and, as RFC 6266 and RFC 5987 say, in UTF-8: the one name every browser keeps.
index.html and the sheet viewer put the same name in their links' ``download`` attribute (library_page.py,
viewer/page.py), which Chromium ignores on a page opened as a file (a file:// link saves under its own name, guitar-N);
it holds served, and in a browser that honours it there.

The standard library alone: the viewer imports it (viewer/page.py ``BUILD_FILES``).
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote

MAX_BYTES = 150  # the stem's, in UTF-8: Chinese is three bytes a character, and a file name 255 at most
_NUMBERED = re.compile(r"(?:guitar|score)-(\d+)(\.[A-Za-z0-9]+)")
_REFUSED = re.compile(r'[/\\:*?"<>|]')
_SPACES = re.compile(r"\s+")


def download_name(artist: str, title: str, file_name: str) -> str:
    """The name the file ``file_name`` of the song ``title`` by ``artist`` is downloaded under:
    ``download_name("Eagles", "Hotel California", "guitar-2.gp5") == "Eagles - Hotel California (2).gp5"``."""
    numbered = _NUMBERED.fullmatch(file_name)
    number = int(numbered.group(1)) if numbered else 1
    extension = (numbered.group(2) if numbered else PurePosixPath(file_name).suffix).lower()
    stem = " - ".join(_fit([_ends(_clean(part)) for part in (artist, title) if _ends(_clean(part))]))
    if not stem:
        return file_name
    return stem + (f" ({number})" if number > 1 else "") + extension


def content_disposition(name: str) -> str:
    """``attachment``, the file named ``name``: in ASCII (accents dropped, any other letter ``_``), then in UTF-8."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    plain = "".join(c if c.isascii() and c.isprintable() and c not in '%"\\' else "_" for c in plain)
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name, safe='')}"


def _clean(part: str) -> str:
    """A name with what a system refuses taken out, its spaces one each."""
    kept = []
    for c in unicodedata.normalize("NFC", part):
        kind = unicodedata.category(c)
        if c.isspace():
            kept.append(" ")
        elif kind == "Cf":  # a direction mark, a zero-width joiner: invisible, never in a file's name
            continue
        elif kind.startswith("C") or _REFUSED.match(c):
            kept.append("_")
        else:
            kept.append(c)
    return _SPACES.sub(" ", "".join(kept)).strip()


def _ends(stem: str) -> str:
    return stem.strip(" .")


def _fit(parts: list[str]) -> list[str]:
    """The parts of a stem, joined by " - ", cut to ``MAX_BYTES`` bytes of UTF-8 in all: a part shorter than its
    share whole, the other the rest, or each its half."""
    if len(parts) < 2:
        return [_ends(_cut(part, MAX_BYTES)) for part in parts]
    room = MAX_BYTES - len(" - ")
    sizes = [len(part.encode("utf-8")) for part in parts]
    if sum(sizes) <= room:
        return parts
    half = room // 2
    if sizes[0] <= half:
        budgets = [sizes[0], room - sizes[0]]
    elif sizes[1] <= half:
        budgets = [room - sizes[1], sizes[1]]
    else:
        budgets = [half, room - half]
    return [kept for part, budget in zip(parts, budgets) if (kept := _ends(_cut(part, budget)))]


def _cut(text: str, size: int) -> str:
    """``text``, cut to ``size`` bytes of UTF-8 on a whole character."""
    data = text.encode("utf-8")
    if len(data) <= size:
        return text
    return data[:size].decode("utf-8", errors="ignore")
