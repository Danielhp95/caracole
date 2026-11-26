"""One song at a time through a provider: the ladder every per-song pass climbs (lyrics.py,
lacuerda_fetch.py, gtptabs_fetch.py, youtube_fetch.py).

Errors are never misses. A block propagates. A spent budget ends the pass
(``budget_exhausted``). Once the client gives up on the provider for the run
(``ProviderUnavailable``), the pass ends and every song left, that one first, is a
failure with that error, never asked about and no error of its own. Any other
``ProviderError`` counts the song in ``tried`` and ``errors``, names it in
``failures`` with its error, and leaves it for the next run; the pass goes on,
unless the error is one of ``stop_on``. ``on_cut`` hears the song whose turn a block, a spent budget or the
client giving up cut short (a pass whose miss would stand for the site's answer puts it back: megalobiz_fetch.py).

A pass lists its songs at its start, and bulk work hands caracole's lock to a lookup or a sync in its pauses
(commands/_common.py ``hand_over``), which may give a song on the list what the pass is for, or remove it: each
song is read again just before its turn (``as_now``), and passed over once it is gone or no longer due. What a pass
holds of overrides.toml is read again once such a hand-over came (``Reread``): before a song's turn, and after it, so
that what the site answered in a turn a hand-over came in is kept only while the song still is one to ask, as it was
asked.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError, ProviderUnavailable
from caracole.songs import Song, get_song

log = logging.getLogger(__name__)

T = TypeVar("T")
V = TypeVar("V")


@dataclass
class PassStats:
    """What a pass did, whatever its provider: the songs ``tried`` (errors included), the
    ``errors``, whether the budget ran out, and ``failures``: the songs a provider error
    left for the next run, each with its error, the ``errors`` counted, then the songs not
    asked about once the client gave up on the provider for the run."""

    tried: int = 0
    errors: int = 0
    budget_exhausted: bool = False
    failures: list[tuple[Song, ProviderError]] = field(default_factory=list, compare=False, repr=False)


def again(conn: sqlite3.Connection, song: Song, due: Callable[[Song], bool] = lambda song: True) -> Song | None:
    """``song`` as the database has it now, while it is still due (``due``, read of the song as it is now); None once
    it is removed (or its id is another song's now) or no longer due."""
    try:
        now = get_song(conn, song.id)
    except KeyError:
        return None
    return now if now.key == song.key and due(now) else None


def as_now(conn: sqlite3.Connection, songs: Iterable[Song],
           due: Callable[[Song], bool] = lambda song: True) -> Iterator[Song]:
    """Each of ``songs`` as the database has it now, read lazily, just before its turn (``again``): one removed since
    (or whose id another song has now) left out, and one ``due`` no longer says is due."""
    for song in songs:
        now = again(conn, song, due)
        if now is not None:
            yield now


def handed_over(client: object) -> int:
    """How many times the client's process has handed caracole's lock over (commands/_common.py's clients'
    ``handoffs``; any other client, none)."""
    return int(getattr(client, "handoffs", 0) or 0)


class Reread(Generic[V]):
    """What a pass holds of overrides.toml, ``value``, as the jobs its client let go first left it: bulk work hands
    caracole's lock over in its client's pauses (commands/_common.py ``hand_over``), and the job that took it may have
    picked a record, cleared one or typed a name. ``look`` says whether a hand-over came since the last look, and reads
    ``value`` again when one did (``reload``; the copy read before when the file can't be read now)."""

    def __init__(self, client: object, value: V, reload: Callable[[], V] | None):
        self.client, self.value, self.reload = client, value, reload
        self.seen = handed_over(client)

    def look(self) -> bool:
        count = handed_over(self.client)
        if count == self.seen:
            return False
        self.seen = count
        if self.reload is not None:
            from caracole.overrides import OverridesError

            try:
                self.value = self.reload()
            except OverridesError as e:
                log.info("overrides.toml couldn't be read again (%s); going on with what was read before.", e)
        return True


def each_song(
    songs: Iterable[Song],
    stats: PassStats,
    turn: Callable[[Song], T],
    *,
    site: str,
    level: int = logging.DEBUG,
    stop_on: tuple[type[ProviderError], ...] = (),
    on_error: Callable[[Song, ProviderError], None] | None = None,
    on_cut: Callable[[Song, Exception], None] | None = None,
) -> Iterator[tuple[Song, T]]:
    """Each song's ``turn``, in order, and what it came to, for the songs it came to something
    for; see the module docstring for the rest. ``songs`` is read lazily, a song just before its
    turn, so a filter in it sees what the turns before did. ``site`` names the provider in the
    log, where a song's error goes at ``level``; ``on_error`` hears it after."""
    left = iter(songs)
    for song in left:
        try:
            outcome = turn(song)
        except (ProviderBlocked, BudgetExhausted, ProviderUnavailable) as e:
            if on_cut is not None:
                on_cut(song, e)
            if isinstance(e, ProviderBlocked):
                raise
            if isinstance(e, BudgetExhausted):
                stats.budget_exhausted = True
                return
            log.info("%s is unavailable for the rest of this run: %s", site, e)
            stats.failures += [(song, e), *((other, e) for other in left)]
            return
        except ProviderError as e:
            stats.tried += 1
            stats.errors += 1
            stats.failures.append((song, e))
            log.log(level, "%s for %s: %s", site, song.display, e)
            if on_error is not None:
                on_error(song, e)
            if isinstance(e, stop_on):
                return
            continue
        stats.tried += 1
        yield song, outcome
