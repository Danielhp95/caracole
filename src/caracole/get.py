"""One song looked up now: ``caracole get``, which caracole serve's lookups run too.

The nightly run fills the library in bulk; a lookup is the one song you want to
play now, so it does the whole run's work for that song alone, in one process,
sheet first, at the interactive pace (commands/_common.py): about a second
between two requests to a site, a few requests per site, and an hourly budget.
Its stages, in order, each reported as it starts and ends (``Progress``):

- ``song``: the song, found in the library or added to wanted.txt as
  ``caracole add`` adds it, then synced; the Ultimate Guitar song you picked
  recorded under ``[match]`` in overrides.toml, and the tab under ``[pin]``,
  in place of the song's pin of its kind group alone (``_other_pins``); the
  LaCuerda song or version you picked under ``[lacuerda]``.
- ``match``: matched against the offline index, alone.
- ``sheet``: the LaCuerda sheet you picked, first (its version's page, and its
  artist's page when the index doesn't name its best version). Else, or when
  LaCuerda can't give it now (said first: a failure, a cooldown, the Ultimate
  Guitar tab you pinned, which no pick replaces), Ultimate Guitar's sheet, from
  as few pages as can be: one page lists every version of its kind with its
  rating, and the best rated is kept (two requests at most; one when the first
  page read is the best). Without one, LaCuerda's, for a song LaCuerda would
  be asked about tonight. The sheet is readable from here on
  (``Progress.readable``). Once it asks LaCuerda, the stage says, running,
  which site it asks (``SHEET_FROM``), for caracole serve's line.
- ``pdf``: ChordPro and the PDF (render.py), and the HTML viewer where render
  writes one, for this song alone (``render_all``'s ``song_ids``): another
  song's failure, or its wait for a CJK font, is not this one's.
- ``lyrics``: LRCLIB.
- ``ug``: Ultimate Guitar again, as the nightly run would: the top sheets
  scored against the lyrics (a better one replaces the first, and the others
  are kept beside it, said as "kept beside it: tab B, tab C"), guitar parts
  and the text tab. It spends only what leaves ``SHEETS_SHARE`` of the hour's
  lookup requests to UG for sheets (``after_the_sheet``), so that an evening
  of lookups keeps getting them.
- ``lacuerda``: LaCuerda, for a Spanish song without a complete sheet; within
  ``SHEETS_SHARE`` too, once the song has a sheet.
- ``gtptabs``: a Guitar Pro file from gtptabs.com, from the index the nightly
  run keeps.
- ``pages``: the PDF again if the sheet changed, then _todo.md and index.html,
  whose MuseScore links come from the local index.
- ``songbooks``: the songbooks of songbooks.toml that list the song, made again
  as ``caracole songbook render`` does (a songbook whose inputs did not change
  is left as it is), then _todo.md and index.html again once one was, as they
  show each songbook's files; the others are left alone, and a songbooks.toml
  that can't be read is said and stops nothing.

A block cools its site down and ends that site's stages; a spent budget (the
lookup's or the hour's) and a provider's error leave the song to the nightly
run; neither is a failure, and neither makes a song not found. The lookup holds
caracole's lock throughout, and a nightly run that holds it lets the lookup go
first at its next pause, or between two songs for work that sends no request
(auto-chords, the PDF pass; ``_common.hand_over``).
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from caracole.config import Config
from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError

log = logging.getLogger(__name__)

STAGES = (
    ("song", "Find the song"),
    ("match", "Match it against the offline index"),
    ("sheet", "The sheet"),
    ("pdf", "The PDF"),
    ("lyrics", "Lyrics from LRCLIB"),
    ("ug", "Ultimate Guitar: the sheets scored, guitar parts"),
    ("lacuerda", "LaCuerda"),
    ("gtptabs", "A Guitar Pro file from gtptabs.com"),
    ("pages", "The library page"),
    ("songbooks", "The songbooks it is in"),
)
STAGE_LABELS = dict(STAGES)
NAMES = {"ug": "Ultimate Guitar", "lrclib": "LRCLIB", "lacuerda": "LaCuerda", "gtptabs": "gtptabs.com",
         "musescore": "MuseScore"}
PROGRESS_PREFIX = "caracole-progress: "  # a JSON line of `caracole get --progress`
_FIRST_PAGES = 1  # versions pages read before the first sheet is kept: the first lists them all
_FIRST_SCORED = 1  # sheets fetched for it: the best rated
SHEETS_SHARE = 0.5  # of an hour's lookup requests to a site, kept for sheets: what follows one spends the rest
# A running sheet stage's detail, once LaCuerda is one of the sites it asks: the site it asks now, which caracole
# serve's line follows (web/status.py), "Fetching from LaCuerda…" rather than Ultimate Guitar's.
SHEET_FROM = {"lacuerda": "from LaCuerda", "ug": "from Ultimate Guitar"}
GTPTABS_KEPT = "Guitar Pro file downloaded"  # the gtptabs stage's detail for a file kept, which caracole serve reads
# The sheet stage's detail for a song Ultimate Guitar can't be asked about, which caracole serve reads.
NOT_IN_INDEX = "the offline index doesn't have it, and its artist's UG page isn't known"


@dataclass(frozen=True)
class LookupRequest:
    """A song to look up now, by name; ``songbooks`` False leaves the stage that makes its songbooks again; ``ug`` ("artist-key/song-key") is the Ultimate Guitar song you
    picked, ``tab`` the tab (its page's address, or its id), ``lacuerda`` the LaCuerda song or version
    (its page's address)."""

    artist: str
    title: str
    album: str | None = None
    duration_ms: int | None = None
    ug: str | None = None
    tab: str | None = None
    lacuerda: str | None = None
    songbooks: bool = True  # False: leave the songbooks to a job that makes them once (Get the missing songs)

    @property
    def display(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass
class LookupResult:
    song_id: int | None = None
    display: str = ""
    states: dict[str, str] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    sheet: Path | None = None  # the readable sheet, in the library
    files: dict[str, str] = field(default_factory=dict)  # name -> library-relative path
    seconds_to_sheet: float | None = None
    seconds: float = 0.0
    requests: dict[str, int] = field(default_factory=dict)
    bug: str | None = None
    refused: str | None = None

    @property
    def ok(self) -> bool:
        """No bug: a block, a spent budget or a site's error is expected, and no failure of caracole."""
        return self.bug is None


class Progress:
    """What a lookup reports; subclasses print it, or pass it on to caracole serve."""

    def stage(self, name: str, state: str, detail: str = "") -> None:
        """A stage starts (``running``) or ends: ``done``, ``skipped`` (nothing to do, or left for the
        nightly run) or ``failed`` (a site's error, or a bug)."""

    def readable(self, files: Mapping[str, str], seconds: float) -> None:
        """The song's sheet can be read: ``files`` names its library-relative paths (``sheet``, and
        ``pdf`` and ``viewer`` once they are there), ``seconds`` after the lookup began."""

    def song(self, song_id: int, display: str) -> None:
        """The song the lookup is about, once it is in the library."""


def progress_line(event: Mapping[str, Any]) -> str:
    """A progress event as a line of `caracole get --progress`."""
    return PROGRESS_PREFIX + json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"))


def read_progress_line(line: str) -> dict[str, Any] | None:
    """The event in a line `caracole get --progress` printed, or None for any other line."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        event = json.loads(line[len(PROGRESS_PREFIX):])
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def kept_sheet(conn, song):
    """The song's kept sheet (a ``library.KeptFile``): the human one, else the auto-chords one; or None."""
    from caracole.library import kept_files
    from caracole.songs import SHEET_FILE_NAMES

    kept = {f.name: f for f in kept_files(conn, song.id)}
    return next((kept[n] for n in SHEET_FILE_NAMES if n in kept), None)


def readable_files(conn, library_dir: Path, song) -> dict[str, str]:
    """Where the song's sheet can be read, as paths in the library: ``sheet`` (its text), and ``pdf`` and
    ``viewer`` (render's HTML viewer) when they are there. Empty without a kept sheet."""
    from caracole.library import song_dir

    kept = kept_sheet(conn, song)
    if kept is None:
        return {}
    folder, base, stem = song_dir(library_dir, song), Path(kept.path).parent, Path(kept.name).stem
    files = {"sheet": kept.path}
    for name, file in (("pdf", f"{stem}.pdf"), ("viewer", f"{stem}.html")):
        if (folder / file).is_file():
            files[name] = (base / file).as_posix()
    return files


class _Stop(Exception):
    """The lookup can't go on (an ignored song, a pick that isn't one): said in the song's stage."""


class _Lookup:
    def __init__(self, cfg: Config, request: LookupRequest, progress: Progress, *, runner: Callable,
                 now: datetime | None, clock: Callable[[], float]):
        from caracole.commands._common import lookup_run_id, utcnow

        self.cfg, self.request, self.progress = cfg, request, progress
        self.runner, self.clock = runner, clock
        self.started = clock()
        self.now = (now or utcnow()).replace(microsecond=0)
        self.run_id = lookup_run_id(self.now)
        self.result = LookupResult(display=request.display)
        self.clients: dict[str, Any] = {}
        self.blocked: set[str] = set()
        self.failed: set[str] = set()
        self.kept_for_sheets: set[str] = set()  # sites whose client a stage after the sheet holds to SHEETS_SHARE
        self.lacuerda_asked = False
        self.lacuerda_said: tuple[str, str] = ("done", "")  # what LaCuerda's first ask came to
        self.running: str | None = None  # the stage running
        self.sheet_from: str | None = None  # the site the sheet stage said it asks (SHEET_FROM), if it said one
        self.conn = None
        self.overrides = None
        self.song = None
        self.sheet_version: int | None = None

    # --- reporting --------------------------------------------------------------------------------

    def _report(self, name: str, state: str, detail: str = "") -> None:
        self.result.states[name] = state
        if state != "running":
            self.result.details[name] = detail
        self.progress.stage(name, state, detail)

    def stage(self, name: str, run: Callable[[], tuple[str, str] | str | None]) -> None:
        """Run one stage; what it returns is its end, ``(state, detail)`` or a detail of ``done``."""
        self._report(name, "running")
        self.running = name
        try:
            out = run()
        except _Stop:
            raise
        except Exception as e:  # a bug: say so, go on with the other stages, exit 1 at the end
            log.error("The %s stage failed: %s: %s. That's a bug in caracole; its traceback follows.", name,
                      type(e).__name__, e, exc_info=True)
            self.result.bug = self.result.bug or f"{name}: {type(e).__name__}: {e}"
            self._report(name, "failed", f"a bug in caracole: {type(e).__name__}: {e}")
            return
        finally:
            self.running = None
        state, detail = out if isinstance(out, tuple) else ("done", out or "")
        self._report(name, state, detail)
        self._check_readable()

    # --- clients and the sites ------------------------------------------------------------------------

    def _usable(self, provider: str) -> str | None:
        """Why a site can't be asked now, or None when it can."""
        from caracole.health import get_state, is_cooling

        if not self.cfg.provider(provider).enabled:
            return f"{NAMES[provider]} is off in caracole.toml"
        if provider in self.blocked:
            return f"{NAMES[provider]} blocked caracole: it cools down, and the nightly run asks again later"
        if provider in self.failed:
            return f"{NAMES[provider]} failed earlier in this lookup; the nightly run tries again"
        if is_cooling(self.conn, provider, self.now):
            until = get_state(self.conn, provider).cooldown_until
            when = until.strftime("%Y-%m-%d %H:%M UTC") if until else "later"
            return f"{NAMES[provider]} is cooling down after a block, until {when}"
        return None

    def client(self, provider: str):
        from caracole.commands._common import make_client

        if provider not in self.clients:
            self.clients[provider] = make_client(self.cfg, self.conn, provider, self.run_id, interactive=True)
        return self.clients[provider]

    def asking(self, provider: str, work: Callable[[Any], tuple[str, str] | str]) -> tuple[str, str] | str:
        """Ask a site, the way every stage does: a block, a spent budget or an error ends it as it ends a
        nightly step, without a miss."""
        from caracole.health import record_block, record_error

        why = self._usable(provider)
        if why is not None:
            self._owed(provider)
            return "skipped", why
        client = self.client(provider)
        try:
            return work(client)
        except ProviderBlocked as e:
            self._owed(provider)
            state = record_block(self.conn, e.provider, self.now, str(e))
            self.blocked.add(e.provider)
            until = state.cooldown_until.strftime("%Y-%m-%d %H:%M UTC") if state.cooldown_until else "later"
            return "skipped", (f"{NAMES[e.provider]} blocked caracole ({e}): no more requests to it until {until}. "
                               "Nothing was marked not found.")
        except BudgetExhausted as e:
            self._owed(provider)
            p = self.cfg.provider(e.provider)
            if e.provider in self.kept_for_sheets:
                spent = self._kept_for_sheets(e.provider)
            elif client.policy.budget < p.lookup_requests:
                spent = f"this hour's {p.lookup_per_hour} lookup requests to {NAMES[e.provider]} are spent"
            else:
                spent = f"the lookup's {p.lookup_requests} requests to {NAMES[e.provider]} are spent"
            return "skipped", f"{spent}; the nightly run does the rest"
        except ProviderError as e:
            self._owed(provider)
            record_error(self.conn, e.provider, self.now, str(e))
            self.failed.add(e.provider)  # as in a nightly step: an error ends the site's part for this lookup
            return "failed", f"{NAMES.get(e.provider, e.provider)} failed ({e}); the nightly run tries again"

    def _owed(self, provider: str) -> None:
        """A song whose Ultimate Guitar part a cooldown, a block, a spent budget or an error cut short is
        marked to fetch, as ``caracole fetch --song`` marks it: asked for, it is owed a fetch at night,
        even when it was clean (fetched before, nothing new). caracole serve's line then says Not fetched
        yet, and the nightly run does fetch it."""
        from caracole.songs import get_song, update_song

        if provider != "ug" or self.song is None:
            return
        song = get_song(self.conn, self.song.id)
        if song.match_decision in ("accept", "pinned") and not song.ug_dirty:
            update_song(self.conn, song.id, ug_dirty=True)

    def after_the_sheet(self, provider: str, work: Callable[[Any], tuple[str, str] | str]) -> tuple[str, str] | str:
        """Ask a site for what follows the sheet, which the nightly run would do anyway: within what leaves
        ``SHEETS_SHARE`` of the hour's lookup requests to it for sheets, so an evening of songs looked up
        on the spot keeps getting them."""
        from caracole.commands._common import lookup_requests_used

        p = self.cfg.provider(provider)
        left = p.lookup_per_hour - math.ceil(p.lookup_per_hour * SHEETS_SHARE) - lookup_requests_used(self.conn, provider)
        if left <= 0 and self._usable(provider) is None:
            return "skipped", f"{self._kept_for_sheets(provider)}; the nightly run does the rest"

        def within(client) -> tuple[str, str] | str:
            if client.requests_made + left < client.policy.budget:  # no stage after it asks this site for a sheet
                client.policy = replace(client.policy, budget=client.requests_made + left)
                self.kept_for_sheets.add(provider)
            return work(client)

        return self.asking(provider, within)

    def _kept_for_sheets(self, provider: str) -> str:
        p = self.cfg.provider(provider)  # SHEETS_SHARE is a half
        return (f"this hour's lookups have spent half of their {p.lookup_per_hour} requests to {NAMES[provider]}, "
                "and the other half is kept for sheets")

    # --- what can be read -----------------------------------------------------------------------------

    def _kept_sheet(self):
        return kept_sheet(self.conn, self.song) if self.song is not None else None

    def _check_readable(self) -> None:
        """Say the sheet is readable when one is kept, and again when it, its PDF or its viewer changes."""
        kept = self._kept_sheet()
        if kept is None:
            return
        files = readable_files(self.conn, self.cfg.library_dir, self.song)
        if files == self.result.files and kept.version_id == self.sheet_version:
            return
        first = self.result.seconds_to_sheet is None
        self.sheet_version = kept.version_id
        self.result.files = files
        self.result.sheet = self.cfg.library_dir / kept.path
        if first:
            self.result.seconds_to_sheet = self.clock() - self.started
        self.progress.readable(files, self.clock() - self.started)

    # --- the stages -------------------------------------------------------------------------------

    def find_song(self) -> str:
        from caracole.normalize import identity_key
        from caracole.overrides import (
            OverridesError,
            add_lacuerda,
            add_match,
            add_pin,
            lacuerda_pick_from_url,
            load_overrides,
            tab_id_from_url,
        )
        from caracole.songs import find_song, update_song
        from caracole.wanted import append_wanted, sync_wanted

        req = self.request
        key = identity_key(req.artist, req.title)
        if key in self.overrides.ignore:
            raise _Stop(f"{req.display} is ignored in overrides.toml: take it out of [ignore] to look it up")
        song = find_song(self.conn, key)
        said = "in the library"
        if song is None:
            try:
                line = append_wanted(self.cfg.wanted_file, req.artist, req.title, req.album, req.duration_ms)
            except ValueError as e:  # a song the file can't hold, such as an artist with " - " in it
                raise _Stop(f"caracole can't add this song: {e}") from e
            except OSError as e:
                raise _Stop(f"wanted.txt can't be written: {e.strerror or e}") from e
            sync_wanted(self.conn, self.cfg.wanted_file, self.now)
            song = find_song(self.conn, line.identity)
            if song is None:
                raise _Stop(f"{req.display} is in wanted.txt, line {line.line_no}, but couldn't be synced")
            said = f"added to wanted.txt, line {line.line_no}"
        if song.status == "ignored":
            raise _Stop(f"{song.display} is ignored in overrides.toml: take it out of [ignore] to look it up")
        picked = []
        try:
            if req.ug:
                add_match(self.cfg.overrides_file, song.display, req.ug)
                picked.append(f"[match] {req.ug}")
            if req.tab:
                tab_id = tab_id_from_url(req.tab)
                add_pin(self.cfg.overrides_file, song.display, [req.tab, *self._other_pins(song, tab_id)])
                picked.append(f"[pin] tab {tab_id}")
            if req.lacuerda:
                pick = lacuerda_pick_from_url(req.lacuerda)
                add_lacuerda(self.cfg.overrides_file, song.display, pick.url)
                update_song(self.conn, song.id, lacuerda_checked_at=None)  # a new pick is asked for at once
                picked.append(f"[lacuerda] {pick.url}")
            if picked:
                self.overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            raise _Stop(f"your pick can't be recorded in overrides.toml: {e}") from e
        self.song = song
        self.result.song_id, self.result.display = song.id, song.display
        tell = getattr(self.progress, "song", None)  # a Progress of another shape may not hear it
        if tell is not None:
            tell(song.id, song.display)
        return said + (f"; recorded in overrides.toml: {', '.join(picked)}" if picked else "")

    def _other_pins(self, song, tab_id: int) -> list[str]:
        """The song's pins that stay beside a tab you pick, as written: those of another kind group (a
        chords sheet beside a Guitar Pro pick), by the offline index's types. A pin of the pick's group,
        or of a kind the index doesn't know on either side, is replaced; the pick goes first anyway."""
        from caracole.ug.fetch import CHORDS_KINDS, GUITAR_PRO_KINDS, TAB_KINDS

        def group(tab: int) -> tuple[str, ...] | None:
            row = self.conn.execute("SELECT type FROM ug_index WHERE tab_id = ?", (tab,)).fetchone()
            kinds = (CHORDS_KINDS, GUITAR_PRO_KINDS, TAB_KINDS)  # the groups a pin replaces (ug/fetch.py)
            return next((g for g in kinds if row is not None and row[0] in g), None)

        mine = group(tab_id)
        if mine is None:
            return []
        pasted = self.overrides.pin_urls.get(song.key, ())
        return [pasted[i] if i < len(pasted) else str(pin)
                for i, pin in enumerate(self.overrides.pin.get(song.key, ()))
                if group(pin) not in (None, mine)]

    def match(self) -> tuple[str, str] | str:
        from caracole.http import CachedAnswers
        from caracole.match import match_all
        from caracole.songs import get_song
        from caracole.ug.artist_tabs import backfill
        from caracole.ug.index import index_state

        # Once, the artist pages caracole read before it kept their tabs for searches: from the HTTP cache
        # alone, which sends nothing and needs no client (the lookup makes Ultimate Guitar's only to ask it,
        # never while it cools down).
        backfill(self.conn, CachedAnswers("ug", self.cfg.cache_dir), self.overrides)
        state = index_state(self.conn)
        [change] = match_all(self.conn, self.overrides, self.cfg.match, songs=[self.song])
        self.song = get_song(self.conn, self.song.id)
        r = change.new
        target = f"{r.artist_key}/{r.song_key}" if r.artist_key and r.song_key else ""
        words = {"accept": f"matched to {target}", "pinned": f"pinned to {target or 'your tab'}",
                 "review": f"not sure which Ultimate Guitar song: {target} is the nearest",
                 "not_found": "not in the offline Ultimate Guitar index", "ignored": "ignored in overrides.toml"}
        said = words.get(self.song.match_decision or "not_found", self.song.match_decision or "")
        if state != "complete" and r.step not in ("override", "pin"):
            said += (" (the offline index is empty: run caracole index build once)" if state == "empty"
                     else " (the offline index is incomplete)")
        return said

    def _ug_ready(self) -> str | None:
        """Why Ultimate Guitar has nothing to fetch for the song, or None when it has."""
        from caracole.ug.fetch import artist_is_known, needs_artist_page

        song = self.song
        if song.match_decision in ("accept", "pinned"):
            return None
        if needs_artist_page(song) and artist_is_known(self.conn, song, self.overrides):
            return None  # its artist's UG page may list it (A6)
        if song.match_decision == "review":
            return ("caracole isn't sure which Ultimate Guitar song this is: pick it on the lookup page, "
                    "or run caracole review")
        return NOT_IN_INDEX

    def _fetch_context(self, client, *, first: bool):
        from caracole.overrides import load_overrides
        from caracole.ug.fetch import FetchContext

        rank = replace(self.cfg.rank, scored_sheets=_FIRST_SCORED) if first else self.cfg.rank
        # The first pass scores one sheet alone: the versions kept beside it wait for the ug stage.
        extra = {"max_pages_per_group": _FIRST_PAGES, "versions": False} if first else {}
        return FetchContext(conn=self.conn, client=client, overrides=self.overrides, rank=rank,
                            library_dir=self.cfg.library_dir, now=self.now,
                            reload_overrides=lambda: load_overrides(self.cfg.overrides_file), **extra)

    def _picked(self):
        """The LaCuerda song or version you picked for the song (``[lacuerda]``), or None."""
        return self.overrides.lacuerda.get(self.song.key) if self.song is not None else None

    def _holds_pick(self) -> bool:
        """Whether the sheet kept is the LaCuerda one you picked."""
        from caracole.versions import get_version

        pick, kept = self._picked(), self._kept_sheet()
        if pick is None or kept is None:
            return False
        version = get_version(self.conn, kept.version_id)
        return version.provider == "lacuerda" and pick.holds(version.tab_id)

    def _sheet_from(self, provider: str) -> None:
        """Say which site the running sheet stage asks now, once LaCuerda is one of them (``SHEET_FROM``):
        caracole serve's line then says LaCuerda, and Ultimate Guitar again after it. A sheet Ultimate Guitar
        alone is asked for says nothing more."""
        if self.running != "sheet" or self.sheet_from == provider or (provider == "ug" and self.sheet_from is None):
            return
        self.sheet_from = provider
        self._report("sheet", "running", SHEET_FROM[provider])

    def sheet(self) -> tuple[str, str] | str:
        if self._picked() is None:
            return self._sheet_from_ug()
        # Your pick on LaCuerda is the sheet; Ultimate Guitar's only when LaCuerda can't give it, and then the
        # stage says why not before what Ultimate Guitar gave.
        lc = self.lacuerda()
        said = lc[1] if isinstance(lc, tuple) else lc
        if self._holds_pick():
            return "done", said
        ug = self._sheet_from_ug()
        ug_state, ug_said = ug if isinstance(ug, tuple) else ("done", ug)
        return ug_state, f"{said}; {ug_said}" if said else ug_said

    def _sheet_from_ug(self) -> tuple[str, str] | str:
        from caracole.songs import get_song
        from caracole.ug.fetch import process_song

        why = self._ug_ready()
        ug: tuple[str, str] | str
        if why is None:
            def first(client) -> str:
                self._sheet_from("ug")
                out = process_song(self._fetch_context(client, first=True), self.song, guitar=False)
                return (f"tab {out.sheet} from Ultimate Guitar" if out.sheet is not None
                        else "Ultimate Guitar has no sheet to keep")
            ug = self.asking("ug", first)
            self.song = get_song(self.conn, self.song.id)
        else:
            ug = ("skipped", why)
        if self._kept_sheet() is not None:
            return ug if isinstance(ug, tuple) else ("done", ug)
        # No sheet from UG: LaCuerda's, now, when it would be asked tonight.
        lc = self.lacuerda()
        if self._kept_sheet() is not None:
            return "done", lc[1] if isinstance(lc, tuple) else lc
        ug_state, ug_said = ug if isinstance(ug, tuple) else ("done", ug)
        return ("skipped" if ug_state == "done" else ug_state), ug_said

    def pdf(self) -> tuple[str, str] | str:
        from caracole.render import render_all

        if self._kept_sheet() is None:
            return "skipped", "no sheet yet"
        stats = render_all(self.conn, self.cfg, self.overrides, runner=self.runner, now=self.now,
                           song_ids={self.song.id})
        if stats.font_error:
            return "failed", stats.font_error
        if stats.failed:
            return "failed", "chordpro couldn't make the PDF; the log says why"
        return "made" if stats.rendered else "up to date"

    def lyrics(self) -> tuple[str, str] | str:
        from caracole.lyrics import fetch_pending_lyrics
        from caracole.songs import get_song

        def ask(client) -> tuple[str, str] | str:
            s = fetch_pending_lyrics(self.conn, client, self.cfg.library_dir, self.now, only={self.song.id})
            if s.budget_exhausted:
                raise BudgetExhausted("lrclib")
            if s.failures:
                _, e = s.failures[0]
                raise e
            return {(1, 0, 0): "found", (0, 1, 0): "LRCLIB has none",
                    (0, 0, 1): "an instrumental"}.get((s.found, s.missing, s.instrumental), "already there")

        song = get_song(self.conn, self.song.id)
        if song.lyrics_status in ("found", "instrumental"):
            return "already there"
        out = self.asking("lrclib", ask)
        self.song = get_song(self.conn, self.song.id)
        return out

    def ug(self) -> tuple[str, str] | str:
        from caracole.songs import get_song
        from caracole.ug.fetch import process_song

        why = self._ug_ready()
        if why is not None:
            return "skipped", why

        def rest(client) -> str:
            out = process_song(self._fetch_context(client, first=False), get_song(self.conn, self.song.id))
            parts = [f"sheet {out.sheet}" if out.sheet is not None else "no UG sheet"]
            if out.guitar_pro:
                parts.append("Guitar Pro " + ", ".join(str(t) for t in out.guitar_pro))
            if out.tab is not None:
                parts.append(f"tab {out.tab}")
            if out.kept_versions:
                parts.append("kept beside it: " + ", ".join(f"tab {t}" for t in out.kept_versions))
            return " · ".join(parts)

        out = self.after_the_sheet("ug", rest)
        self.song = get_song(self.conn, self.song.id)
        return out

    def lacuerda(self) -> tuple[str, str] | str:
        from caracole.lacuerda_fetch import lacuerda_sheets
        from caracole.songs import get_song

        if self.lacuerda_asked:  # for the sheet: what it came to is said again, a failure as one
            state, said = self.lacuerda_said
            again = "asked already, for the sheet" + (f": {said}" if said else "")
            return ("skipped" if state == "done" else state), again
        self.lacuerda_asked = True

        def ask(client) -> tuple[str, str] | str:
            self._sheet_from("lacuerda")  # for the sheet stage alone
            s = lacuerda_sheets(self.conn, client, self.cfg.library_dir, self.cfg.rank, self.now,
                                overrides=self.overrides, only={self.song.id})
            if s.budget_exhausted:
                raise BudgetExhausted("lacuerda")
            if s.failures:
                _, e = s.failures[0]
                raise e
            if not s.tried and self._holds_pick():
                return "done", "the LaCuerda sheet you picked is the sheet already"
            if not s.tried and self._picked() is not None:
                return "skipped", self._pick_waits()
            if not s.tried:
                return "skipped", "not a song for LaCuerda: not Spanish, a complete sheet already, or asked this month"
            return "sheet kept from LaCuerda" if s.kept else ("not on LaCuerda" if s.missing else "kept what it had")

        # Without a sheet yet, LaCuerda's is the sheet, and so is the one you picked there; with one, a better one
        # the nightly run would look for too.
        first = self._kept_sheet() is None or self._picked() is not None
        out = self.asking("lacuerda", ask) if first else self.after_the_sheet("lacuerda", ask)
        self.lacuerda_said = out if isinstance(out, tuple) else ("done", out)
        self.song = get_song(self.conn, self.song.id)
        return out

    def _pick_waits(self) -> str:
        """Why the LaCuerda song you picked wasn't asked for (``lacuerda_fetch._songs_to_try``): the tab you pinned
        on Ultimate Guitar is the sheet kept, which no pick replaces, or LaCuerda answered for the song this
        month."""
        from caracole.songs import get_song
        from caracole.versions import get_version

        kept = self._kept_sheet()
        version = get_version(self.conn, kept.version_id) if kept is not None else None
        if (version is not None and version.provider == "ug" and version.tab_id.isdigit()
                and int(version.tab_id) in self.overrides.pin.get(self.song.key, ())):
            return "the Ultimate Guitar tab you pinned is kept over your LaCuerda pick"
        if get_song(self.conn, self.song.id).lacuerda_checked_at:
            return "your pick on LaCuerda waits: it was asked for this month"
        return "your pick on LaCuerda waits for the nightly run"

    def gtptabs(self) -> tuple[str, str] | str:
        from caracole.gtptabs_fetch import gtptabs_files

        def ask(client) -> tuple[str, str] | str:
            s = gtptabs_files(self.conn, client, self.cfg.library_dir, self.now, overrides=self.overrides,
                              only={self.song.id}, refresh_index=False)
            if s.budget_exhausted:
                raise BudgetExhausted("gtptabs")
            if s.failures:
                _, e = s.failures[0]
                raise e
            if not s.tried:
                return "skipped", "no file wanted, or gtptabs.com's index doesn't know the artist"
            return GTPTABS_KEPT if s.kept else "no file there"

        return self.asking("gtptabs", ask)

    def pages(self) -> str:
        from caracole.render import render_all
        from caracole.todo import write_pages

        if self._kept_sheet() is not None:
            render_all(self.conn, self.cfg, self.overrides, runner=self.runner, now=self.now,
                       song_ids={self.song.id})
        write_pages(self.conn, self.cfg, self.overrides, self.now)
        return "_todo.md and index.html rewritten"

    def songbooks(self) -> tuple[str, str] | str:
        from caracole.songbook import SongbookError, load_songbooks, render_songbooks, songbooks_file
        from caracole.songbook import songbooks_listing
        from caracole.todo import write_pages

        try:
            books = load_songbooks(songbooks_file(self.cfg.library_dir))
        except SongbookError as e:
            return "skipped", f"songbooks.toml can't be read ({e}); no songbook was made again"
        if not self.request.songbooks:
            return "skipped", "left to the job that makes the songbook after the lookups"
        mine = songbooks_listing(self.conn, books, self.song)
        if not mine:
            return "skipped", "no songbook lists it"
        names = ", ".join(b.name for b in mine)
        # The stage began as "running" without detail (self.stage); this second event is deliberate: it carries the
        # names for caracole serve's "Remaking songbook X…", and Job.stages updates the stage's detail in place.
        self.progress.stage("songbooks", "running", names)
        stats = render_songbooks(self.conn, self.cfg, self.overrides, runner=self.runner,
                                 only=[b.name for b in mine])
        if stats.rendered or stats.failed:  # index.html shows each songbook's files: written again after them
            write_pages(self.conn, self.cfg, self.overrides, self.now)
        if stats.failed:
            return "failed", f"a file of {', '.join(stats.failed)} couldn't be made; the nightly run tries again"
        if stats.font_error:
            return "skipped", stats.font_error
        return f"{names} made again" if stats.rendered else f"{names} up to date"

    # --- the whole lookup ---------------------------------------------------------------------------

    def run(self) -> LookupResult:
        from caracole import db
        from caracole.commands._common import exclusive
        from caracole.health import record_ok
        from caracole.overrides import OverridesError, load_overrides
        from caracole.songs import ensure_current_keys
        from caracole.ug.fetch import note_looked_up

        self._report("song", "running")
        try:
            self.overrides = load_overrides(self.cfg.overrides_file)
        except OverridesError as e:
            return self._refuse(f"overrides.toml can't be read: {e}")

        def waiting(holder: str) -> None:
            self.progress.stage("song", "running", f"waiting for another caracole ({holder}), which lets a "
                                                   "lookup go first at its next pause, or between two songs")

        with exclusive(self.cfg, f"get {self.request.display}", interactive=True, on_wait=waiting):
            with closing(db.connect(self.cfg.db_path)) as conn:
                self.conn = conn
                ensure_current_keys(conn)
                try:
                    try:
                        self._report("song", "done", self.find_song())
                    except _Stop as e:
                        return self._refuse(str(e))
                    for name, work in (("match", self.match), ("sheet", self.sheet), ("pdf", self.pdf),
                                       ("lyrics", self.lyrics), ("ug", self.ug), ("lacuerda", self.lacuerda),
                                       ("gtptabs", self.gtptabs), ("pages", self.pages),
                                       ("songbooks", self.songbooks)):
                        self.stage(name, work)
                    note_looked_up(conn, self.song.id)
                    for provider, client in self.clients.items():
                        if client.requests_made and provider not in self.blocked:
                            record_ok(conn, provider, self.now)
                finally:
                    for provider, client in self.clients.items():
                        self.result.requests[provider] = client.requests_made
                        client.close()
        self.result.seconds = self.clock() - self.started
        return self.result

    def _refuse(self, why: str) -> LookupResult:
        self.result.refused = why
        self._report("song", "failed", why)
        for name, _ in STAGES[1:]:
            self._report(name, "skipped", "")
        self.result.seconds = self.clock() - self.started
        return self.result


def look_up(cfg: Config, request: LookupRequest, progress: Progress | None = None, *,
            runner: Callable = subprocess.run, now: datetime | None = None,
            clock: Callable[[], float] = time.monotonic) -> LookupResult:
    """Look one song up now, stage by stage (see the module docstring), reporting to ``progress``.

    ``runner`` runs chordpro (tests pass a fake); ``now`` is the lookup's time.
    """
    return _Lookup(cfg, request, progress or Progress(), runner=runner, now=now, clock=clock).run()
