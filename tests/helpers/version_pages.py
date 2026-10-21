"""A song's sheet viewer and its kept versions' viewers, written to a folder with the data the version
switcher reads (``versions``: ``sheet_versions.as_data``'s shape, with render.py's ``sheet``, the provider
of the sheet the title opens, and each entry's ``this`` for the page that holds it), for the viewer's tests::

    from helpers.version_pages import WONDERWALL, folder

    pages = folder(tmp_path, WONDERWALL)  # {"sheet.html": Path, "version-39144.html": Path, ...}

``WONDERWALL`` is thirteen chords versions as UG lists Wonderwall's: the one (Ver 3, 4.86★ from 408 votes) and
two kept beside it, then ten that aren't, one of them gone from UG. ``entry`` makes one more, ``with_versions``
puts the data into a page ``build_viewer`` made, as ``folder`` does into each page, each entry's ``this`` saying
whether it is that page's (a page none is, LaCuerda's sheet's or an auto sheet's, has every ``this`` false).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from caracole.inline import json_block
from caracole.viewer import build_viewer

CHO = (Path(__file__).parent.parent / "fixtures" / "chordpro" / "ug_sheet.cho").read_text(encoding="utf-8")
UG = "https://tabs.ultimate-guitar.com/tab/the-placeholders/synthetic-test-song-chords-"


def entry(tab: str, number: int | None, rating: float | None, votes: int | None, rank: int, *,
          kept: bool = False, chosen: bool = False, gone: bool = False, page: str | None = None,
          label: str | None = None, note: str | None = None) -> dict[str, Any]:
    """One version, as ``as_data`` lists it."""
    return {"tab": tab, "number": number, "rating": rating, "votes": votes, "label": label, "note": note,
            "rank": rank, "kept": kept, "chosen": chosen, "gone": gone, "page": page, "url": UG + tab}


WONDERWALL: dict[str, Any] = {
    "total": 13,
    "sheet": "ug",
    "list": [
        entry("1064463", 3, 4.86, 408, 1, kept=True, chosen=True, page="sheet.html",
              note="the version that oasis play on Wembley 2008"),
        entry("39144", 1, 4.85, 12629, 2, kept=True, page="version-39144.html"),
        entry("2161290", 7, 4.8, 1204, 3, kept=True, page="version-2161290.html", label="acoustic"),
        *(entry(str(500 + n), n, round(4.7 - n / 50, 2), 300 - n * 20, n, gone=n == 9,
                note="capo 2, easy chords" if n == 5 else None) for n in range(4, 14)),
    ],
}


def with_versions(page: str, versions: dict[str, Any] | None, name: str | None = None) -> str:
    """``page``, a viewer ``build_viewer`` made, with ``versions`` as its data's ``versions``: as the page
    ``name`` holds them, each entry's ``this`` true for the entry whose page that is."""
    found = re.search(r'<script type="application/json" id="song">(.*?)</script>\n', page)
    assert found, "no song data in the page"
    data = json.loads(found.group(1))
    if versions is not None and name is not None:
        versions = {**versions, "list": [{**v, "this": v["page"] == name and (name != "sheet.html" or v["chosen"])}
                                         for v in versions["list"]]}
    data["versions"] = versions
    return page[:found.start()] + json_block("song", data) + page[found.end():]


def folder(tmp_path: Path, versions: dict[str, Any] | None, *, name: str = "Title",
           pages: tuple[str, ...] | None = None) -> dict[str, Path]:
    """The song's folder, Artist/<name>/ under ``tmp_path``, with sheet.html and each page ``versions`` names
    (or ``pages``), each the viewer of the same sheet with ``versions``; each page by its name."""
    where = tmp_path / "Artist" / name
    where.mkdir(parents=True, exist_ok=True)
    names = pages or ("sheet.html", *(v["page"] for v in (versions or {}).get("list", []) if v["page"]))
    out = {}
    for page in dict.fromkeys(names):
        (where / page).write_text(with_versions(build_viewer(CHO), versions, page), encoding="utf-8")
        out[page] = where / page
    return out
