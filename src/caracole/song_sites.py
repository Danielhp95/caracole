"""Which sites have a song: its card's marks on index.html (library_page.py's ``sites``, rows.js ``siteMarks``).

Every site caracole asks that is on (``shown``), in one order (``ORDER``), is one of three to each song:

- ``have``: something of the song's came from it, or it has the song: UG's index matched it (``accept``, ``pinned``),
  LaCuerda's sheets caracole met, LRCLIB's lyrics or its word that the song is an instrumental, MuseScore's index a
  page of its title (a possible match), YouTube the audio of its auto sheet;
- ``none``: it was asked and had nothing: UG's index matched nothing (``not_found``), LaCuerda was asked
  (``lacuerda_checked_at``), LRCLIB's lyrics missing (or none timed, where Megalobiz's came: its lyrics show on the
  song's card, not as a mark), the misses of gtptabs.com, harptabs.com and gametabs.net (kv
  ``<site>:checked:<song id>``, which a song with a file from there never reads as one), MuseScore's index read and no
  page of its title, nothing on YouTube that fits;
- ``unasked``: not asked yet: the nightly run gets there.

Each with ``said``, its tooltip and its name for a screen reader: "harptabs.com: has it", "Ultimate Guitar: nothing for
it (looked 2026-10-16)", "gtptabs.com: not asked yet". YouTube is a site only for a song on its route (with no human
sheet, where auto-chords is): ``youtube`` names those.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from caracole.config import Config
from caracole.songs import Song

HAVE, NONE, UNASKED = "have", "none", "unasked"
ORDER = ("ug", "lacuerda", "lrclib", "gtptabs", "harptabs", "gametabs", "musescore", "youtube")
NAMES = {"ug": "UG", "lacuerda": "LaCuerda", "lrclib": "LRCLIB", "gtptabs": "gtptabs", "harptabs": "harptabs",
         "gametabs": "gametabs", "musescore": "MuseScore", "youtube": "YouTube"}
# The steps' own kv prefixes of a miss (gtptabs_fetch.py, harptabs_fetch.py, gametabs_fetch.py: their CHECKED_PREFIX),
# written here so the page imports none of the steps.
CHECKED = {"gtptabs": "gtptabs:checked:", "harptabs": "harptabs:checked:", "gametabs": "gametabs:checked:"}
_YOUTUBE = {"downloaded": HAVE, "chords": HAVE, "missing": NONE, "unusable": NONE, "queued": UNASKED,
            "blocked": UNASKED}  # youtube_fetch.py's states; "declined", your [youtube] "none", leaves it out


def shown(cfg: Config) -> tuple[str, ...]:
    """The sites a line names: those on (``config.SWITCHABLE``'s may be off), in ``ORDER``; YouTube among them, where
    a song's route state says so."""
    return tuple(s for s in ORDER if cfg.provider(s).enabled)


def checked(conn: sqlite3.Connection) -> dict[str, dict[int, str]]:
    """When each site's step last found nothing for a song, by site and song id (kv ``CHECKED``)."""
    found: dict[str, dict[int, str]] = {site: {} for site in CHECKED}
    for site, prefix in CHECKED.items():
        for key, value in conn.execute("SELECT key, value FROM kv WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)):
            rest = key[len(prefix):]
            if rest.isdigit():  # not "<id>:pick", the tab picked then
                found[site][int(rest)] = value
    return found


def musescore_read(conn: sqlite3.Connection) -> bool:
    """Whether MuseScore's index holds anything: till then, no title of yours is a miss there."""
    return conn.execute("SELECT 1 FROM musescore_index LIMIT 1").fetchone() is not None


def song_sites(song: Song, sites: tuple[str, ...], *, origins: Mapping[str, str], checks: Mapping[str, Mapping[int, str]],
               lacuerda: bool, musescore: bool | None, musescore_read: bool,
               youtube: str | None) -> list[dict[str, Any]]:
    """The song's marks, a site each of ``sites``: ``origins``, where each of its kept files came from
    (``icons.kept_sources``); ``checks``, the misses (``checked``); ``lacuerda``, whether caracole met a sheet of it on
    LaCuerda; ``musescore``, whether MuseScore's index lists a page of its title (None when that wasn't asked);
    ``youtube``, its state on YouTube's route, None off it."""
    came = set(origins.values())
    marks = []
    for site in sites:
        state, looked = UNASKED, None
        if site in came:
            state = HAVE
        elif site == "ug":
            if song.match_decision in ("accept", "pinned"):
                state = HAVE
            elif song.match_decision == "not_found":
                state, looked = NONE, song.matched_at
        elif site == "lacuerda":
            if lacuerda:
                state = HAVE
            elif song.lacuerda_checked_at:
                state, looked = NONE, song.lacuerda_checked_at
        elif site == "lrclib":
            if origins.get("lyrics.txt", "lrclib") != "lrclib":  # another site's lyrics: LRCLIB had none timed
                state, looked = NONE, song.lyrics_at
            elif song.lyrics_status in ("found", "instrumental"):
                state = HAVE
            elif song.lyrics_status == "missing":
                state, looked = NONE, song.lyrics_at
        elif site in CHECKED:
            if song.id in checks.get(site, {}):
                state, looked = NONE, checks[site][song.id]
        elif site == "musescore":
            if musescore:
                state = HAVE
            elif musescore_read:
                state = NONE
        elif site == "youtube":
            if youtube not in _YOUTUBE:
                continue
            state = _YOUTUBE[youtube]
        marks.append({"source": site, "state": state, "said": _said(site, state, looked, song)})
    return marks


def _day(stamp: str) -> str:
    """A stored time's day ("2026-10-18T03:30:00Z") as the pages write one: "18/10/26"; anything else as it is."""
    year, month, day = stamp[:4], stamp[5:7], stamp[8:10]
    if stamp[4:5] == "-" and stamp[7:8] == "-" and (year + month + day).isdigit():
        return f"{day}/{month}/{year[2:]}"
    return stamp[:10]


def _said(site: str, state: str, looked: str | None, song: Song) -> str:
    name = NAMES[site]
    if state == HAVE:
        if site == "lrclib" and song.lyrics_status == "instrumental":
            return f"{name}: instrumental, no words"
        if site == "musescore":
            return f"{name}: maybe, by its title"
        return f"{name}: has it"
    if state == NONE and site == "lrclib" and song.lyrics_status == "found":
        return f"{name}: nothing timed" + (f" · looked {_day(looked)}" if looked else "")
    if state == NONE:
        return f"{name}: not there" + (f" · looked {_day(looked)}" if looked else "")
    if site == "ug" and song.match_decision == "review":
        return f"{name}: unsure which song"
    return f"{name}: not asked yet"
