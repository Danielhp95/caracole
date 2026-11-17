"""``caracole ug --link URL``: an Ultimate Guitar page pasted into the library page's search box, read now; and
``caracole ug --directory``: UG's artist directory read (ug/directory.py), bulk work at the pace the owner chose for it.

A tab's page (``/tab/{id}`` or a slugged one), then its artist's page, whose lists the fetch reads too, or an artist's
page alone (``/artist/…``): an interactive lookup, at the lookup pace (as ``caracole harptabs --artist`` asks: a
lookup's budget, within the hour's lookups, no ntfy alert), what caracole serve's library page sends by itself for a UG
link pasted into its box (web/ug_link_routes.py). Every list read is kept for searches (ug/artist_tabs.py), so a search
then finds every song of that artist: UG's sitemaps name many of them by a bare id alone. ug/link.py does the work.

A link caracole knows already (its tab's song, or its artist's page read), one of a type caracole keeps nothing of,
and one UG answered 404 for are said with no request. A cooldown, a block, a spent budget and an error say so and exit
0, as a lookup's would; a read that failed is remembered for an hour (kv ``ug:link-failed``), in which the page doesn't
send it by itself again. Its last line starts with what UG answered, which caracole serve's request line shows
(web/status.py): "Read: ", "Not found: " or "Not read: " (nothing changed). With ``--progress``, a JSON line a stage
(get.py's), ``tab`` and ``artist``, as ``caracole youtube --video --progress`` writes them.

Every command module is imported on every start, so the work is imported inside the command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from caracole.commands import _common
from caracole.commands._common import exclusive, load_cfg, load_ovr, make_client, open_db, utcnow

if TYPE_CHECKING:
    from caracole.config import Config

NOT_READ = "Not read: "  # how a read that asked nothing, or got no answer, ends


def register(app: typer.Typer) -> None:
    @app.command("ug")
    def ug_cmd(
        ctx: typer.Context,
        link: str | None = typer.Option(
            None, "--link", metavar="URL",
            help="An Ultimate Guitar page to read now, at the lookup pace: a tab's page (then its artist's page) or an "
                 "artist's page, their tabs kept for searches.",
        ),
        directory: bool = typer.Option(
            False, "--directory",
            help="Instead, read UG's artist directory: its letter listings, then the page of every artist they name "
                 "by a bare address, several requests at once (\\[ug_directory]), going on where the last pass "
                 "stopped.",
        ),
        budget: int | None = typer.Option(
            None, "--budget", metavar="N", min=0,
            help="With --directory: the requests it may send (default \\[ug_directory].budget).",
        ),
        progress: bool = typer.Option(
            False, "--progress", help="A JSON line per stage (the tab page, the artist page), for caracole serve.",
        ),
    ) -> None:
        """Read an Ultimate Guitar page pasted into the library page now (--link), or UG's artist directory
        (--directory)."""
        from caracole.ug_urls import read_link

        if directory == (link is not None):
            _common.fail("give --link URL (a page now) or --directory (UG's artist directory), one of them", 2)
        if budget is not None and not directory:
            _common.fail("--budget goes with --directory", 2)
        if directory:
            _directory(load_cfg(ctx, builds_index="ug --directory"), budget)
            return
        found = read_link(link)
        if found is None:
            _common.fail(f"--link: not an Ultimate Guitar tab's or artist's page: {link!r}", 2)
        _read(load_cfg(ctx), found, progress=progress)


def _directory(cfg: Config, budget: int | None) -> None:
    """``--directory``: a pass of UG's artist directory (ug/directory.py), at its own pace and budget, then what it
    read and how far the directory has got. A cooldown or a block says so and exits 0, as the nightly run's steps
    do; a block records UG's cooldown (the fetch and lookups cool too) and sends one alert."""
    from contextlib import closing

    from caracole.health import answered_any, get_state, is_cooling, record_block, record_error, record_ok
    from caracole.http import ProviderBlocked
    from caracole.logs import plural
    from caracole.stamps import shown
    from caracole.ug.directory import PROVIDER, directory_pass, index_state

    overrides = load_ovr(cfg)
    with exclusive(cfg, "ug --directory"), closing(open_db(cfg)) as conn:
        now = utcnow()
        if is_cooling(conn, PROVIDER, now):
            typer.echo(f"Ultimate Guitar is cooling down after a block until "
                       f"{shown(get_state(conn, PROVIDER).cooldown_until)}; caracole won't ask it before then.")
            return
        run_id = _common.run_id_for(now)
        client = _common.directory_client(cfg, conn, run_id, budget=budget)
        try:
            stats = directory_pass(conn, client, now, overrides=overrides, library_dir=cfg.library_dir)
        except ProviderBlocked as e:
            state = record_block(conn, PROVIDER, now, str(e))
            message = (f"{e}\nNo more requests to Ultimate Guitar until {shown(state.cooldown_until)} "
                       f"(block #{state.strikes}). Nothing was marked missing.")
            _common.alert_block(cfg, PROVIDER, message, strikes=state.strikes)
            typer.echo(f"Ultimate Guitar blocked caracole: {message}")
            _say_state(index_state(conn))
            return
        finally:
            client.close()
        if stats.errors:
            record_error(conn, PROVIDER, now, f"{plural(stats.errors, 'page')} of UG's directory couldn't be read")
        if answered_any(conn, run_id, PROVIDER, client.requests_made):
            record_ok(conn, PROVIDER, now)
        done = f"; read whole: {', '.join(stats.letters_done)}" if stats.letters_done else ""
        typer.echo(f"UG's listings: {plural(stats.pages, 'page')} read, {plural(stats.artists, 'artist')} "
                   f"({stats.new:,} new){done}.")
        gone = f", {stats.gone} gone" if stats.gone else ""
        typer.echo(f"Bare artists' pages: {plural(stats.read, 'page')} read{gone}.")
        if stats.errors:
            typer.echo(f"{plural(stats.errors, 'page')} couldn't be read; each is asked for again on the next pass, "
                       "and the log says why.")
        if stats.budget_exhausted:
            typer.echo(f"The budget of {plural(client.policy.budget, 'request')} is spent: the next pass goes on "
                       "where this one stopped.")
        _say_state(index_state(conn))


def _say_state(state) -> None:
    from caracole.ug.bands import LETTERS

    typer.echo(f"The directory: {state.artists:,} of about {state.counted:,} artists, {state.letters_read} of "
               f"{len(LETTERS)} listings read whole; {state.read:,} of {state.bare:,} bare artists' pages read.")


def _read(cfg: Config, link, *, progress: bool) -> None:
    """``--link``: the link's page read now (ug/link.py ``read``), and what it came to said (the module's docstring)."""
    from contextlib import closing

    from caracole.get import progress_line
    from caracole.health import answered_any, get_state, is_cooling, record_block, record_error, record_ok
    from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
    from caracole.stamps import shown
    from caracole.ug.fetch import FetchContext
    from caracole.ug.link import PROVIDER, forget_failure, known, known_line, read, record_failure, said

    first = "tab" if link.kind == "tab" else "artist"
    at = [first]  # the stage running: the one the last line ends

    def stage(name: str, state: str, detail: str = "") -> None:
        at[0] = name
        if progress:
            typer.echo(progress_line({"stage": name, "state": state, "detail": detail}))

    def end(line: str, state: str = "skipped") -> None:
        stage(at[0], state, line)
        typer.echo(line)

    stage(first, "running", "asking Ultimate Guitar")
    overrides = load_ovr(cfg)
    with exclusive(cfg, f"ug --link {link.url}", interactive=True), closing(open_db(cfg)) as conn:
        now = utcnow()
        was = known(cfg, conn, link, now)
        if was.state in ("found", "other", "gone"):
            end(known_line(conn, was), "done")
            return
        if is_cooling(conn, PROVIDER, now):
            end(f"{NOT_READ}waiting out UG until {shown(get_state(conn, PROVIDER).cooldown_until)}.")
            return
        if was.state == "spent":
            end(f"{NOT_READ}{was.why}. Ask again later.")
            return
        run_id = _common.lookup_run_id(now)
        client = make_client(cfg, conn, PROVIDER, run_id, interactive=True)
        ctx = FetchContext(conn=conn, client=client, overrides=overrides, rank=cfg.rank, library_dir=cfg.library_dir,
                           now=now)
        try:
            done = read(ctx, link, stage)
        except ProviderBlocked as e:
            state = record_block(conn, PROVIDER, now, str(e))
            end(f"{NOT_READ}UG turned us back ({e}); no asks until {shown(state.cooldown_until)}.")
            return
        except BudgetExhausted:
            p = cfg.provider(PROVIDER)
            spent = (f"no more asks of UG this hour ({p.lookup_per_hour} spent)"
                     if client.policy.budget < p.lookup_requests else
                     f"this lookup's {p.lookup_requests} asks of UG are spent")
            end(f"{NOT_READ}{spent}. Ask again later.")
            return
        except ProviderError as e:
            record_error(conn, PROVIDER, now, str(e))
            record_failure(conn, link.url, now, str(e))  # not sent by the page by itself for an hour
            end(f"{NOT_READ}UG failed ({e}). Try again later.")
            return
        finally:
            client.close()
        # The tab known, its artist's page stopped: a block or an error is UG's still, never the link's failure.
        if isinstance(done.stopped, ProviderBlocked):
            record_block(conn, PROVIDER, now, str(done.stopped))
        elif isinstance(done.stopped, ProviderError):
            record_error(conn, PROVIDER, now, str(done.stopped))
        elif answered_any(conn, run_id, PROVIDER, client.requests_made):
            record_ok(conn, PROVIDER, now)
        line = said(done)
        if not line.startswith(NOT_READ):
            forget_failure(conn, link.url, now)
    end(line, "skipped" if line.startswith(NOT_READ) else "done")
