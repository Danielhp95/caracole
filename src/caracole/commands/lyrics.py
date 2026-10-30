"""``caracole lyrics``, ``lacuerda``, ``gtptabs``, ``harptabs``, ``gametabs`` and ``musescore``: one step of the
nightly run, by hand.

Each makes the same pass as its ``caracole run`` step, with a client of its own:
this run's budget, and the HTTP cache the nightly run uses too; the lacuerda step's
two, its sheets and its listings of every artist, are ``caracole lacuerda`` and
``caracole lacuerda --index``, which reads the listings even for an empty library.
``caracole lacuerda --artist NAME`` reads one artist's page into that index now,
at the lookup pace (as ``caracole get`` asks: a lookup's budgets, no ntfy alert):
what caracole serve's Songs of a LaCuerda artist runs. ``caracole lacuerda
--search QUERY`` asks LaCuerda's search for the songs of a query, one request at
the same pace (lacuerda_search.py), and puts what it answers into the index: what
caracole serve's search bar sends once a query has settled (``--auto``, within its
share of the hour's lookups), and its Ask LaCuerda button (``--progress``, a
JSON line per event for the request's stages).
As in the run,
a provider cooling down after a block is left alone, and a block starts (or
extends) its cooldown and sends one ntfy alert. Neither is a failure, and
neither is a spent budget: each prints what happened and exits 0, as
``caracole fetch`` and ``caracole index`` do, and the songs left wait for the
next run. Then each rewrites _todo.md and index.html, which read
overrides.toml, unless it did nothing (a cooldown, or no song to ask about).
``caracole gtptabs``, ``caracole harptabs``, ``caracole gametabs`` and ``caracole musescore`` with
their site turned off in caracole.toml say so and ask nothing. ``caracole harptabs --index`` reads harptabs.com's
artist pages into its local index (harptabs_index.py), the artists of your songs first, at the
bulk pace, with a budget of its own (``--budget``, ``caracole index build``'s by default), and
goes on where it stopped the next time, even for an empty library; ``caracole harptabs
--artist NAME`` reads one artist's page now, at the lookup pace: what caracole serve's Songs of
a harptabs.com artist runs. Its last line starts as ``caracole lacuerda --artist``'s does.
``caracole gametabs --index`` reads gametabs.net's game pages into its local index
(gametabs_index.py), the games of your songs first, the same way: their tabs' composers and
instruments, so that a song is found by its composer.

Every command module is imported on every start, so the passes are imported
inside the commands.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import TYPE_CHECKING

import typer

from caracole.commands import _common
from caracole.commands._common import (
    exclusive,
    load_cfg,
    load_ovr,
    make_client,
    open_db,
    run_id_for,
    utcnow,
    write_pages,
)
from caracole.commands.index import BUILD_BUDGET
from caracole.health import answered_any, get_state, is_cooling, record_block, record_ok
from caracole.logs import plural, provider_name
from caracole.stamps import parse as stamps_parse
from caracole.stamps import shown

if TYPE_CHECKING:
    from caracole.config import Config, ProviderPolicy
    from caracole.gametabs_fetch import GameTabsStats
    from caracole.gametabs_index import GamePassStats
    from caracole.gametabs_index import IndexState as GameIndexState
    from caracole.gtptabs_fetch import GtpTabsStats
    from caracole.harptabs_fetch import HarpTabsStats
    from caracole.harptabs_index import ArtistPassStats, IndexState
    from caracole.http import Client
    from caracole.lacuerda_fetch import LaCuerdaStats
    from caracole.lacuerda_index import IndexStats
    from caracole.lyrics import LyricsStats
    from caracole.musescore_fetch import MuseScoreStats
    from caracole.overrides import Overrides

# Each provider's command, for the lock.
_COMMANDS = {"lrclib": "lyrics", "megalobiz": "lyrics", "azlyrics": "lyrics", "lacuerda": "lacuerda", "gtptabs": "gtptabs",
             "harptabs": "harptabs", "gametabs": "gametabs", "musescore": "musescore"}
LACUERDA_SEARCHES_PER_HOUR = 20  # lacuerda_search.SEARCHES_PER_HOUR, for the help, which imports no pass


def register(app: typer.Typer) -> None:
    @app.command("lyrics")
    def lyrics_cmd(ctx: typer.Context) -> None:
        """Fetch lyrics from LRCLIB for songs that have none yet, timed ones from Megalobiz, then AZLyrics' where none."""
        _lyrics(load_cfg(ctx))

    @app.command("lacuerda")
    def lacuerda_cmd(
        ctx: typer.Context,
        index: bool = typer.Option(
            False, "--index",
            help="Instead, read LaCuerda's listings of every artist into its local index (artist slugs, for searches).",
        ),
        artist: str | None = typer.Option(
            None, "--artist", metavar="NAME",
            help="Instead, read this artist's page into the index now (their name, or their page's slug), "
                 "at the lookup pace: their songs, for searches.",
        ),
        search: str | None = typer.Option(
            None, "--search", metavar="QUERY",
            help="Instead, ask LaCuerda's search for the songs of QUERY now, one request at the lookup pace, at "
                 "most once in 30 days a query, and put what it answers into the index.",
        ),
        auto: bool = typer.Option(
            False, "--auto",
            help="With --search: a search the page sent by itself, within its share of the hour's lookups "
                 f"({LACUERDA_SEARCHES_PER_HOUR} searches).",
        ),
        progress: bool = typer.Option(
            False, "--progress", help="With --search: a JSON line per event, for caracole serve's request page.",
        ),
    ) -> None:
        """Look for LaCuerda chord sheets for Spanish songs without a complete one."""
        cfg = load_cfg(ctx, builds_index="lacuerda --index" if index else None)
        if sum((index, artist is not None, search is not None)) > 1:
            _common.fail("--index reads every artist's listing, --artist one artist's page and --search one query "
                         "of LaCuerda's search: give one of them", 2)
        if (auto or progress) and search is None:
            _common.fail("--auto and --progress go with --search", 2)
        if search is not None:
            _lacuerda_search(cfg, " ".join(search.split()), auto=auto, progress=progress)
        elif artist is not None:
            _lacuerda_artist(cfg, " ".join(artist.split()))
        elif index:
            _lacuerda_index(cfg)
        else:
            _lacuerda(cfg)

    @app.command("gtptabs")
    def gtptabs_cmd(ctx: typer.Context) -> None:
        """Download a Guitar Pro file from gtptabs.com for each song that has none."""
        _gtptabs(load_cfg(ctx, builds_index="gtptabs"))

    @app.command("harptabs")
    def harptabs_cmd(
        ctx: typer.Context,
        index: bool = typer.Option(
            False, "--index",
            help="Instead, read harptabs.com's artist pages into its local index (their tabs, for searches): your "
                 "songs' artists first, then the rest, going on where the last one stopped.",
        ),
        budget: int | None = typer.Option(
            None, "--budget", metavar="N", min=1,
            help=f"With --index: the requests it may send (default {BUILD_BUDGET}, at the bulk pace).",
        ),
        artist: str | None = typer.Option(
            None, "--artist", metavar="NAME",
            help="Instead, read this artist's page into the index now (their name, or their page's address), at "
                 "the lookup pace, once in 30 days.",
        ),
    ) -> None:
        """Keep a harmonica tab from harptabs.com for each song that has none and a tab there by its artist."""
        if index and artist is not None:
            _common.fail("--index reads every artist's page and --artist one artist's: give one of them", 2)
        if budget is not None and not index:
            _common.fail("--budget goes with --index", 2)
        cfg = load_cfg(ctx, builds_index="harptabs --index" if index else None)
        if artist is not None:
            _harptabs_artist(cfg, " ".join(artist.split()))
        elif index:
            _harptabs_index(cfg, budget)
        else:
            _harptabs(cfg)

    @app.command("gametabs")
    def gametabs_cmd(
        ctx: typer.Context,
        index: bool = typer.Option(
            False, "--index",
            help="Instead, read gametabs.net's game pages into its local index (their tabs' composers and "
                 "instruments): your songs' games first, then the rest, going on where the last one stopped.",
        ),
        budget: int | None = typer.Option(
            None, "--budget", metavar="N", min=1,
            help=f"With --index: the requests it may send (default {BUILD_BUDGET}, at the bulk pace).",
        ),
    ) -> None:
        """Keep a text tab from gametabs.net for each song that has none and a tab there of its game or composer."""
        if budget is not None and not index:
            _common.fail("--budget goes with --index", 2)
        cfg = load_cfg(ctx, builds_index="gametabs --index" if index else None)
        if index:
            _gametabs_index(cfg, budget)
        else:
            _gametabs(cfg)

    @app.command("musescore")
    def musescore_cmd(ctx: typer.Context) -> None:
        """Read MuseScore's song sitemaps into the index the to-do page's links come from."""
        _musescore(load_cfg(ctx, builds_index="musescore"))


def _lyrics(cfg: Config) -> None:
    """Look up every song still waiting for lyrics, and old misses, then print the counts."""
    from caracole.lyrics import fetch_pending_lyrics

    overrides = load_ovr(cfg)  # for the pages

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        return fetch_pending_lyrics(conn, client, cfg.library_dir, now)

    def ran(s: LyricsStats) -> bool:
        return bool(s.tried or s.budget_exhausted)

    handed = _common.handoffs()  # a lookup LRCLIB's pass lets go first may change overrides.toml: Megalobiz's reads it
    s = _provider_pass(cfg, "lrclib", run, overrides, ran)
    if s is not None:
        if not ran(s):
            typer.echo("No song is waiting for lyrics.")
        else:
            counts = f"{s.found} found, {s.missing} missing, {s.instrumental} instrumental"
            typer.echo(f"Lyrics: {counts}, {plural(s.errors, 'error')}")
            if s.errors:
                typer.echo("Songs with an error stay pending; the next run asks LRCLIB again.")
            if s.budget_exhausted:
                _budget_spent(cfg, "lrclib")
    overrides = _common.overrides_since(cfg, overrides, handed)
    handed = _common.handoffs()
    _megalobiz(cfg, overrides)
    _azlyrics(cfg, _common.overrides_since(cfg, overrides, handed))


def _megalobiz(cfg: Config, overrides: Overrides) -> None:
    """Megalobiz's pass after LRCLIB's, as the nightly run's step follows LRCLIB's: the songs LRCLIB left without
    timed lyrics. Nothing, not a word, when it is turned off or has no song to ask about."""
    from caracole.megalobiz_fetch import MegalobizStats, megalobiz_lyrics, songs_to_ask

    if not cfg.provider("megalobiz").enabled:
        return
    with closing(open_db(cfg)) as conn:
        if not songs_to_ask(conn, utcnow()):
            return

    def run(conn: sqlite3.Connection, client: Client, now: datetime) -> MegalobizStats:
        return megalobiz_lyrics(conn, client, cfg.library_dir, now)

    def ran(s: MegalobizStats) -> bool:
        return bool(s.tried or s.budget_exhausted)

    s = _provider_pass(cfg, "megalobiz", run, overrides, ran)
    if s is None or not ran(s):
        return
    typer.echo(f"Megalobiz: {s.found} found, {s.timed} timed, {s.missing} missing, {plural(s.errors, 'error')}")
    if s.errors:
        typer.echo("Songs with an error wait; the next run asks LRCLIB, then Megalobiz, again.")
    if s.budget_exhausted:
        _budget_spent(cfg, "megalobiz")


def _azlyrics(cfg: Config, overrides: Overrides) -> None:
    """AZLyrics' pass after Megalobiz's, as the nightly run's step follows it: the songs still without lyrics. Nothing,
    not a word, when it is turned off or has no song to ask about."""
    from caracole.azlyrics_fetch import AzLyricsStats, azlyrics_lyrics, songs_to_ask

    if not cfg.provider("azlyrics").enabled:
        return
    with closing(open_db(cfg)) as conn:
        if not songs_to_ask(conn, utcnow(), picks=overrides.azlyrics):
            return

    def run(conn: sqlite3.Connection, client: Client, now: datetime) -> AzLyricsStats:
        return azlyrics_lyrics(conn, client, cfg.library_dir, now, picks=overrides.azlyrics)

    def ran(s: AzLyricsStats) -> bool:
        return bool(s.tried or s.budget_exhausted)

    s = _provider_pass(cfg, "azlyrics", run, overrides, ran)
    if s is None or not ran(s):
        return
    typer.echo(f"AZLyrics: {s.found} found, {s.missing} missing, {plural(s.errors, 'error')}")
    if s.errors:
        typer.echo("Songs with an error wait; the next run asks the sites again.")
    if s.budget_exhausted:
        _budget_spent(cfg, "azlyrics")


def _lacuerda(cfg: Config) -> None:
    """Try LaCuerda for the Spanish songs that need a sheet, then print the counts."""
    from caracole.lacuerda_fetch import lacuerda_sheets
    from caracole.overrides import load_overrides
    from caracole.report import shared_folder
    from caracole.ug.fetch import rescore_kept_sheets

    overrides = load_ovr(cfg)
    rescored = 0

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        nonlocal rescored
        # As the run does before its fetch: a sheet kept before its lyrics is scored first (no
        # request), or no partial LaCuerda sheet could replace it, and a complete one is left be.
        rescored = rescore_kept_sheets(conn, cfg.library_dir, cfg.rank)
        # A lookup the client lets go first in a pause may pin a tab or pick a sheet: read again after one.
        return lacuerda_sheets(conn, client, cfg.library_dir, cfg.rank, now, overrides=overrides,
                               reload_overrides=lambda: load_overrides(cfg.overrides_file))

    def ran(s: LaCuerdaStats) -> bool:
        return bool(rescored or s.tried or s.budget_exhausted)

    s = _provider_pass(cfg, "lacuerda", run, overrides, ran)
    if s is None:
        return
    if not (s.tried or s.budget_exhausted):
        typer.echo("No song to try on LaCuerda.")
        return
    counts = f"{s.tried} tried, {plural(s.kept, 'sheet')} kept, {s.missing} missing"
    typer.echo(f"LaCuerda: {counts}, {plural(s.errors, 'error')}")
    for shared in s.shared:
        typer.echo(shared_folder(shared).text)
    if s.errors:
        typer.echo("Songs with an error are tried again next run.")
    if s.budget_exhausted:
        _budget_spent(cfg, "lacuerda")


def _lacuerda_index(cfg: Config) -> None:
    """Read LaCuerda's listings of every artist into the index when due, then say what it holds."""
    from caracole.lacuerda_index import index_pass, index_size

    overrides = load_ovr(cfg)  # for the pages

    def run(conn: sqlite3.Connection, client: Client, now: datetime) -> tuple[IndexStats, tuple[int, int]]:
        return index_pass(conn, client, now), index_size(conn)

    def ran(result: tuple[IndexStats, tuple[int, int]]) -> bool:
        s = result[0]
        return bool(s.pages or s.errors or s.budget_exhausted)

    result = _provider_pass(cfg, "lacuerda", run, overrides, ran)
    if result is None:
        return
    s, (artists, songs) = result
    held = f"{plural(artists, 'artist')} and {plural(songs, 'song')}"
    if not ran(result):
        typer.echo(f"LaCuerda's artist index is up to date: {held}.")
        return
    if s.pages:
        typer.echo(f"Index: {plural(s.pages, 'page')} of artists read.")
    errors = f", {plural(s.errors, 'error')}; the next run asks again" if s.errors else ""
    typer.echo(f"LaCuerda: {held} in the index{errors}.")
    if s.budget_exhausted:
        typer.echo(f"LaCuerda's budget of {plural(cfg.provider('lacuerda').budget, 'request')} per run is spent; "
                   "the next run reads the rest of its listings.")


NOT_READ = "Not read: "  # how a read of an artist page that asked nothing, or got no answer, ends


def _lacuerda_artist(cfg: Config, artist: str) -> None:
    """Read one artist's page into LaCuerda's index now, at the lookup pace, then say what it lists. A
    cooldown, a block, a spent budget or an error says so and exits 0, as a lookup's would.

    Its last line starts with what LaCuerda answered, which caracole serve's request line shows
    (web/status.py): "Read: " (the page, in the index now), "Not found: " (no artist page by that
    name or slug) or "Not read: " (a cooldown, a block, a spent budget or an error: nothing changed)."""
    from caracole.health import record_error
    from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
    from caracole.lacuerda_fetch import read_artist_page

    with exclusive(cfg, f"lacuerda --artist {artist}", interactive=True), closing(open_db(cfg)) as conn:
        now = utcnow()
        if is_cooling(conn, "lacuerda", now):
            typer.echo(f"{NOT_READ}LaCuerda is cooling down after a block until "
                       f"{shown(get_state(conn, 'lacuerda').cooldown_until)}; caracole won't ask it before then.")
            return
        run_id = _common.lookup_run_id(now)
        client = make_client(cfg, conn, "lacuerda", run_id, interactive=True)
        try:
            found = read_artist_page(conn, client, artist, now)
        except ProviderBlocked as e:
            state = record_block(conn, "lacuerda", now, str(e))
            typer.echo(f"{NOT_READ}LaCuerda blocked caracole ({e}); no more requests to it until "
                       f"{shown(state.cooldown_until)}.")
            return
        except BudgetExhausted:
            p = cfg.provider("lacuerda")
            spent = (f"this hour's {p.lookup_per_hour} lookup requests to LaCuerda are spent"
                     if client.policy.budget < p.lookup_requests else
                     f"the lookup's {p.lookup_requests} requests to LaCuerda are spent")
            typer.echo(f"{NOT_READ}{spent}; ask again later.")
            return
        except ProviderError as e:
            record_error(conn, "lacuerda", now, str(e))
            typer.echo(f"{NOT_READ}LaCuerda failed ({e}); nothing changed: try again later.")
            return
        finally:
            client.close()
        if answered_any(conn, run_id, "lacuerda", client.requests_made):
            record_ok(conn, "lacuerda", now)
        row = found and conn.execute("SELECT artist FROM lacuerda_index WHERE artist_slug = ? LIMIT 1",
                                     (found[0],)).fetchone()
    if not found:
        typer.echo(f"Not found: LaCuerda has no artist page for {artist}.")
        return
    typer.echo(f"Read: LaCuerda's page of {row[0] if row else artist} lists {plural(found[1], 'song')}, in the "
               "index now.")


NOT_SEARCHED = "Not searched: "  # how a search that asked nothing, or got no answer, ends


def _lacuerda_search(cfg: Config, query: str, *, auto: bool, progress: bool) -> None:
    """Ask LaCuerda's search for the songs of ``query`` now, at the lookup pace, and say what it answered. A query
    asked within 30 days, a cooldown, a block, a spent share or budget, or an error says so and exits 0.

    Its last line starts with what LaCuerda answered, which caracole serve's request line shows (web/status.py):
    "Searched: " (its songs, in the index now, or asked within 30 days), "Found already: " (your library or the
    index answers it well, once the artist pages the HTTP cache holds are in the index: no request), "Nothing
    found: " (no song) or "Not searched: " (no word LaCuerda reads, a cooldown, a block, a spent share or budget,
    an error, or, ``auto``, a search that failed lately: nothing changed). An error is remembered for an hour
    (``lacuerda_search.record_failure``), in which the page doesn't send the query by itself again.
    With ``progress``, that line is also the detail of its one stage's last JSON line (get.py's), "search"."""
    from dataclasses import replace

    from caracole.get import progress_line
    from caracole.health import record_error
    from caracole.http import BudgetExhausted, CachedAnswers, ProviderBlocked, ProviderError
    from caracole.lacuerda_index import backfill_cached
    from caracole.lacuerda_search import (
        RUN,
        SEARCHES_PER_HOUR,
        answered,
        asked,
        failed,
        query_key,
        record_failure,
        search,
        searches_used,
    )

    def say(state: str, detail: str) -> None:
        if progress:
            typer.echo(progress_line({"stage": "search", "state": state, "detail": detail}))

    def end(line: str, state: str = "skipped") -> None:
        say(state, line)
        typer.echo(line)

    shown_query = f"“{query}”"
    key = query_key(query)
    if not key:
        end(f"{NOT_SEARCHED}LaCuerda's search reads only words of 4 letters or more, and {shown_query} has none.")
        return
    say("running", "asking LaCuerda")
    with exclusive(cfg, f"lacuerda --search {query}", interactive=True), closing(open_db(cfg)) as conn:
        now = utcnow()
        backfill_cached(conn, CachedAnswers("lacuerda", cfg.cache_dir))  # the artist pages it holds: no request
        was = asked(conn, key, now)
        if was is not None:
            end(f"Searched: LaCuerda was asked for {shown_query} on {shown(stamps_parse(was.get('at')))}: "
                f"{plural(int(was.get('songs') or 0), 'song')}, in the index.", "done")
            return
        if answered(conn, query):  # what the page's gate saw may be older than what the cache just gave
            end(f"Found already: caracole has {shown_query} already, in your library or its copy of LaCuerda's "
                "index; no request sent.", "done")
            return
        p = cfg.provider("lacuerda")
        if is_cooling(conn, "lacuerda", now):
            end(f"{NOT_SEARCHED}LaCuerda is cooling down after a block until "
                f"{shown(get_state(conn, 'lacuerda').cooldown_until)}; caracole won't ask it before then.")
            return
        policy = _common.lookup_policy(cfg, conn, "lacuerda", now)
        if policy.budget < 1:
            end(f"{NOT_SEARCHED}this hour's {p.lookup_per_hour} lookup requests to LaCuerda are spent; ask again "
                "later.")
            return
        failure = failed(conn, key, now) if auto else None
        if failure is not None:
            end(f"{NOT_SEARCHED}{failure.said(shown_query)}; its Ask LaCuerda button, Try again or a terminal "
                "asks now.")
            return
        if auto and searches_used(conn, now) >= SEARCHES_PER_HOUR:
            end(f"{NOT_SEARCHED}this hour's {SEARCHES_PER_HOUR} searches of LaCuerda the page sends by itself are "
                "spent; its Ask LaCuerda button, or a terminal, asks anyway.")
            return
        run_id = _common.LOOKUP_RUN + RUN + run_id_for(now)
        client = make_client(cfg, conn, "lacuerda", run_id, policy=replace(policy, budget=1), interactive=True)
        try:
            answer = search(conn, client, query, now)
        except ProviderBlocked as e:
            state = record_block(conn, "lacuerda", now, str(e))
            end(f"{NOT_SEARCHED}LaCuerda blocked caracole ({e}); no more requests to it until "
                f"{shown(state.cooldown_until)}.")
            return
        except BudgetExhausted:
            end(f"{NOT_SEARCHED}the search's one request to LaCuerda is spent; ask again later.")
            return
        except ProviderError as e:
            record_error(conn, "lacuerda", now, str(e))
            record_failure(conn, key, now, f"LaCuerda failed: {e}")  # not sent by the page by itself for an hour
            end(f"{NOT_SEARCHED}LaCuerda failed ({e}); nothing changed: try again later.")
            return
        finally:
            client.close()
        if answered_any(conn, run_id, "lacuerda", client.requests_made):
            record_ok(conn, "lacuerda", now)
    if answer.songs:
        some = (f"{plural(answer.stated, 'song')} for {shown_query}: the first {len(answer.songs)} are"
                if answer.stated > len(answer.songs) else f"{plural(len(answer.songs), 'song')} for {shown_query},")
        end(f"Searched: LaCuerda has {some} in the index now.", "done")
    elif answer.artists:
        end(f"Searched: LaCuerda names {plural(len(answer.artists), 'artist')} for {shown_query}, in the index now.",
            "done")
    else:
        end(f"Nothing found: LaCuerda has no song for {shown_query}.", "done")


def _gtptabs(cfg: Config) -> None:
    """Read gtptabs.com's sitemaps when due, download what the songs need, then print the counts."""
    from caracole.gtptabs_fetch import gtptabs_files

    if not cfg.provider("gtptabs").enabled:
        typer.echo("gtptabs.com is off ([providers.gtptabs] enabled = false); nothing was asked.")
        return
    overrides = load_ovr(cfg)

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        return gtptabs_files(conn, client, cfg.library_dir, now, overrides=overrides)

    def ran(s: GtpTabsStats) -> bool:
        return bool(s.sitemaps or s.tried or s.errors or s.budget_exhausted)

    s = _provider_pass(cfg, "gtptabs", run, overrides, ran)
    if s is None:
        return
    if not ran(s):
        typer.echo("No song to look up on gtptabs.com.")
        return
    if s.sitemaps:
        typer.echo(f"Index: {plural(s.sitemaps, 'sitemap')} read.")
    counts = f"{s.tried} tried, {plural(s.kept, 'Guitar Pro file')} kept, {s.missing} not on gtptabs.com"
    typer.echo(f"gtptabs.com: {counts}, {plural(s.errors, 'error')}")
    if s.errors:
        typer.echo("Songs with an error are tried again next run.")
    if s.budget_exhausted:
        _budget_spent(cfg, "gtptabs")


def _harptabs(cfg: Config) -> None:
    """Read harptabs.com's sitemap when due, keep the tabs the songs need, then print the counts."""
    from caracole.harptabs_fetch import harptabs_tabs

    if not cfg.provider("harptabs").enabled:
        typer.echo("harptabs.com is off ([providers.harptabs] enabled = false); nothing was asked.")
        return
    overrides = load_ovr(cfg)

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        return harptabs_tabs(conn, client, cfg.library_dir, now, overrides=overrides)

    def ran(s: HarpTabsStats) -> bool:
        return bool(s.sitemaps or s.tried or s.errors or s.budget_exhausted)

    s = _provider_pass(cfg, "harptabs", run, overrides, ran)
    if s is None:
        return
    if not ran(s):
        typer.echo("No song to look up on harptabs.com.")
        return
    if s.sitemaps:
        typer.echo(f"Index: {plural(s.sitemaps, 'sitemap')} read.")
    counts = f"{s.tried} tried, {plural(s.kept, 'harmonica tab')} kept, {s.missing} not on harptabs.com"
    typer.echo(f"harptabs.com: {counts}, {plural(s.errors, 'error')}")
    if s.errors:
        typer.echo("Songs with an error are tried again next run.")
    if s.budget_exhausted:
        _budget_spent(cfg, "harptabs")


def _gametabs(cfg: Config) -> None:
    """Read gametabs.net's sitemaps when due, keep the tabs the songs need, then print the counts."""
    from caracole.gametabs_fetch import gametabs_tabs

    if not cfg.provider("gametabs").enabled:
        typer.echo("gametabs.net is off ([providers.gametabs] enabled = false); nothing was asked.")
        return
    overrides = load_ovr(cfg)

    def run(conn: sqlite3.Connection, client: Client, now: datetime):
        return gametabs_tabs(conn, client, cfg.library_dir, now, overrides=overrides)

    def ran(s: GameTabsStats) -> bool:
        return bool(s.sitemaps or s.tried or s.errors or s.budget_exhausted)

    s = _provider_pass(cfg, "gametabs", run, overrides, ran)
    if s is None:
        return
    if not ran(s):
        typer.echo("No song to look up on gametabs.net.")
        return
    if s.sitemaps:
        typer.echo(f"Index: {plural(s.sitemaps, 'sitemap')} read.")
    counts = f"{s.tried} tried, {plural(s.kept, 'tab')} kept, {s.missing} not on gametabs.net"
    typer.echo(f"gametabs.net: {counts}, {plural(s.errors, 'error')}")
    if s.errors:
        typer.echo("Songs with an error are tried again next run.")
    if s.budget_exhausted:
        _budget_spent(cfg, "gametabs")


def _gametabs_index(cfg: Config, budget: int | None) -> None:
    """Read gametabs.net's game pages into its index, the sitemaps first when due, a budget at a time (its own,
    ``--budget``), then say how far the index has got and how long the rest would take at this pace."""
    from dataclasses import replace

    from caracole.gametabs_index import game_pass, index_state
    from caracole.progress import about

    if not cfg.provider("gametabs").enabled:
        typer.echo("gametabs.net is off ([providers.gametabs] enabled = false); nothing was asked.")
        return
    overrides = load_ovr(cfg)  # your songs' games first, and the pages
    p = cfg.provider("gametabs")
    policy = replace(p, budget=budget if budget is not None else max(BUILD_BUDGET, p.budget))

    def run(conn: sqlite3.Connection, client: Client, now: datetime) -> tuple[GamePassStats, GameIndexState]:
        return game_pass(conn, client, now, overrides=overrides), index_state(conn)

    def ran(result: tuple[GamePassStats, GameIndexState]) -> bool:
        s = result[0]
        return bool(s.sitemaps or s.read or s.errors or s.budget_exhausted)

    result = _provider_pass(cfg, "gametabs", run, overrides, ran, policy=policy, command="gametabs --index")
    if result is None:
        return
    s, now = result
    held = f"{now.read:,} of {plural(now.pages, 'game page')} read"
    if not ran(result):
        typer.echo(f"gametabs.net's game index is up to date: {held}, {plural(now.tabs, 'tab')}.")
        return
    if s.sitemaps:
        typer.echo(f"Index: gametabs.net's {plural(s.sitemaps, 'sitemap')} read.")
    gone = f", {s.gone} gone" if s.gone else ""
    errors = f", {plural(s.errors, 'error')} (asked for again next time)" if s.errors else ""
    typer.echo(f"gametabs.net: {plural(s.read, 'game page')} read{gone}{errors}; {held}, "
               f"{plural(now.tabs, 'tab')} in the index.")
    if s.budget_exhausted:
        left = max(now.pages - now.read, 0)
        pace = about(left * sum(p.delay) / 2)
        typer.echo(f"The budget of {plural(policy.budget, 'request')} is spent: caracole gametabs --index reads the "
                   f"next {plural(left, 'game page')}, {pace} of requests at this pace.")


def _harptabs_index(cfg: Config, budget: int | None) -> None:
    """Read harptabs.com's artist pages into its index, the sitemap first when due, a budget at a time (its own,
    ``--budget``), then say how far the index has got and how long the rest would take at this pace."""
    from dataclasses import replace

    from caracole.harptabs_index import artist_pass, index_state
    from caracole.progress import about

    if not cfg.provider("harptabs").enabled:
        typer.echo("harptabs.com is off ([providers.harptabs] enabled = false); nothing was asked.")
        return
    overrides = load_ovr(cfg)  # your songs' artists first, and the pages
    p = cfg.provider("harptabs")
    policy = replace(p, budget=budget if budget is not None else max(BUILD_BUDGET, p.budget))

    def run(conn: sqlite3.Connection, client: Client, now: datetime) -> tuple[ArtistPassStats, IndexState]:
        return artist_pass(conn, client, now, overrides=overrides), index_state(conn)

    def ran(result: tuple[ArtistPassStats, IndexState]) -> bool:
        s = result[0]
        return bool(s.sitemaps or s.read or s.errors or s.budget_exhausted)

    result = _provider_pass(cfg, "harptabs", run, overrides, ran, policy=policy, command="harptabs --index")
    if result is None:
        return
    s, now = result
    held = f"{now.read:,} of {plural(now.artists, 'artist')} read"
    if not ran(result):
        typer.echo(f"harptabs.com's artist index is up to date: {held}, {plural(now.tabs, 'tab')}.")
        return
    if s.sitemaps:
        typer.echo("Index: harptabs.com's sitemap read.")
    gone = f", {s.gone} gone" if s.gone else ""
    errors = f", {plural(s.errors, 'error')} (asked for again next time)" if s.errors else ""
    typer.echo(f"harptabs.com: {plural(s.read, 'artist page')} read{gone}{errors}; {held}, "
               f"{plural(now.tabs, 'tab')} in the index.")
    if s.budget_exhausted:
        left = max(now.artists - now.read, 0)
        pace = about(left * sum(p.delay) / 2)
        typer.echo(f"The budget of {plural(policy.budget, 'request')} is spent: caracole harptabs --index reads the "
                   f"next {plural(left, 'artist')}, {pace} of requests at this pace.")


def _harptabs_artist(cfg: Config, artist: str) -> None:
    """Read one artist's page into harptabs.com's index now, at the lookup pace, then say what it lists. A
    cooldown, a block, a spent budget or an error says so and exits 0, as a lookup's would.

    Its last line starts as ``caracole lacuerda --artist``'s does, which caracole serve's request line shows
    (web/status.py): "Read: " (the page, in the index now, or read within 30 days), "Not found: " (no artist
    page by that name, or one gone) or "Not read: " (the site turned off, its index empty, a cooldown, a block,
    a spent budget or an error: nothing changed)."""
    from caracole.harptabs_index import artist_paths, read_artist
    from caracole.health import record_error
    from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError

    if not cfg.provider("harptabs").enabled:
        typer.echo(f"{NOT_READ}harptabs.com is off ([providers.harptabs] enabled = false); nothing was asked.")
        return
    with exclusive(cfg, f"harptabs --artist {artist}", interactive=True), closing(open_db(cfg)) as conn:
        now = utcnow()
        paths = artist_paths(conn, artist)
        if not paths:
            if conn.execute("SELECT 1 FROM harptabs_index LIMIT 1").fetchone() is None:
                typer.echo(f"{NOT_READ}harptabs.com's index is empty: the nightly run reads its sitemap, or "
                           "caracole harptabs --index now.")
            else:
                typer.echo(f"Not found: harptabs.com's sitemap lists no artist named {artist}.")
            return
        if is_cooling(conn, "harptabs", now):
            typer.echo(f"{NOT_READ}harptabs.com is cooling down after a block until "
                       f"{shown(get_state(conn, 'harptabs').cooldown_until)}; caracole won't ask it before then.")
            return
        run_id = _common.lookup_run_id(now)
        client = make_client(cfg, conn, "harptabs", run_id, interactive=True)
        try:
            page = read_artist(conn, client, paths[0], now)
        except ProviderBlocked as e:
            state = record_block(conn, "harptabs", now, str(e))
            typer.echo(f"{NOT_READ}harptabs.com blocked caracole ({e}); no more requests to it until "
                       f"{shown(state.cooldown_until)}.")
            return
        except BudgetExhausted:
            p = cfg.provider("harptabs")
            spent = (f"this hour's {p.lookup_per_hour} lookup requests to harptabs.com are spent"
                     if client.policy.budget < p.lookup_requests else
                     f"the lookup's {p.lookup_requests} requests to harptabs.com are spent")
            typer.echo(f"{NOT_READ}{spent}; ask again later.")
            return
        except ProviderError as e:
            record_error(conn, "harptabs", now, str(e))
            typer.echo(f"{NOT_READ}harptabs.com failed ({e}); nothing changed: try again later.")
            return
        finally:
            client.close()
        if answered_any(conn, run_id, "harptabs", client.requests_made):
            record_ok(conn, "harptabs", now)
    if page is None:
        typer.echo(f"Not found: harptabs.com no longer has the page of {artist}.")
        return
    listed = len(page.listed)
    lists = (f"{listed} of their {plural(page.tabs, 'tab')}" if page.tabs > listed else
             f"their {plural(listed, 'tab')}" if listed else "no tab")
    typer.echo(f"Read: harptabs.com's page of {page.name} lists {lists}, in the index now.")


def _musescore(cfg: Config) -> None:
    """Read MuseScore's song sitemaps when due, then say what the index holds."""
    from caracole.musescore_fetch import index_size, musescore_index, songs_wanting_pages

    if not cfg.provider("musescore").enabled:
        typer.echo("MuseScore is off ([providers.musescore] enabled = false); nothing was asked.")
        return
    overrides = load_ovr(cfg)

    def run(conn: sqlite3.Connection, client: Client, now: datetime) -> tuple[MuseScoreStats, int, bool]:
        stats = musescore_index(conn, client, now, overrides=overrides)
        return stats, index_size(conn), bool(songs_wanting_pages(conn, overrides))

    def ran(result: tuple[MuseScoreStats, int, bool]) -> bool:
        s = result[0]
        return bool(s.sitemaps or s.errors or s.budget_exhausted)

    result = _provider_pass(cfg, "musescore", run, overrides, ran)
    if result is None:
        return
    s, size, wanted = result
    if not ran(result):
        typer.echo(f"MuseScore's index is up to date: {plural(size, 'song page')}." if wanted
                   else "No song to look up on MuseScore.")
        return
    if s.sitemaps:
        typer.echo(f"Index: {plural(s.sitemaps, 'sitemap')} read.")
    errors = f", {plural(s.errors, 'error')}; the next run asks again" if s.errors else ""
    typer.echo(f"MuseScore: {plural(size, 'song page')} in the index{errors}.")
    if s.budget_exhausted:
        typer.echo(f"MuseScore's budget of {plural(cfg.provider('musescore').budget, 'request')} per run is "
                   "spent; the next run reads the rest of its sitemaps.")


def _provider_pass[T](
    cfg: Config,
    provider: str,
    run: Callable[[sqlite3.Connection, Client, datetime], T],
    overrides: Overrides,
    ran: Callable[[T], bool],
    *,
    policy: ProviderPolicy | None = None,
    command: str | None = None,
) -> T | None:
    """Run one provider's pass as the nightly run does; None after a cooldown or a block.

    Either way it says so first; neither is a failure, so the command exits 0.
    Requests are logged to ``events`` under a run id of their own. A pass the
    provider answered without a block clears its strikes, as a run does: one it
    answered with nothing but errors doesn't (``health.answered_any``).
    It holds caracole's lock throughout (under ``command``, the provider's by
    default), so the cooldown it reads is the one a caracole it waited for left.
    ``policy`` stands in for the provider's own (``caracole harptabs --index``'s
    budget). After a block, or a pass that did something
    (``ran``), it rewrites _todo.md and index.html, by overrides.toml as a lookup
    its client let go first in a pause left it (``_common.overrides_since``).
    """
    from caracole.http import ProviderBlocked

    name = provider_name(provider)
    with exclusive(cfg, command or _COMMANDS[provider]), closing(open_db(cfg)) as conn:
        now = utcnow()
        if is_cooling(conn, provider, now):
            until = get_state(conn, provider).cooldown_until
            typer.echo(f"{name} is cooling down after a block until {shown(until)}; "
                       "caracole won't ask it before then.")
            return None
        run_id = run_id_for(now)
        handed = _common.handoffs()  # the client's first pause may let a lookup go first too
        client = make_client(cfg, conn, provider, run_id, policy=policy)
        try:
            result = run(conn, client, now)
        except ProviderBlocked as e:
            state = record_block(conn, provider, now, str(e))
            message = (
                f"{e}\nNo more requests to {name} until {shown(state.cooldown_until)} "
                f"(block #{state.strikes}). Nothing was marked missing."
            )
            _common.alert_block(cfg, provider, message)
            typer.echo(f"{name} blocked caracole: {message}")
            write_pages(conn, cfg, _common.overrides_since(cfg, overrides, handed), utcnow())  # with the cooldown
            return None
        finally:
            client.close()
        if answered_any(conn, run_id, provider, client.requests_made):
            record_ok(conn, provider, now)
        if ran(result):
            write_pages(conn, cfg, _common.overrides_since(cfg, overrides, handed), utcnow())
    return result


def _budget_spent(cfg: Config, provider: str) -> None:
    budget = cfg.provider(provider).budget
    typer.echo(
        f"{provider_name(provider)}'s budget of {plural(budget, 'request')} per run is spent; "
        "the songs left wait for the next run."
    )
