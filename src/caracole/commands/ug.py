"""``caracole ug --link URL``: an Ultimate Guitar page pasted into the library page's search box, read now.

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
        link: str = typer.Option(
            ..., "--link", metavar="URL",
            help="An Ultimate Guitar page to read now, at the lookup pace: a tab's page (then its artist's page) or an "
                 "artist's page, their tabs kept for searches.",
        ),
        progress: bool = typer.Option(
            False, "--progress", help="A JSON line per stage (the tab page, the artist page), for caracole serve.",
        ),
    ) -> None:
        """Read an Ultimate Guitar page pasted into the library page now: a tab and its artist's page."""
        from caracole.ug_urls import read_link

        found = read_link(link)
        if found is None:
            _common.fail(f"--link: not an Ultimate Guitar tab's or artist's page: {link!r}", 2)
        _read(load_cfg(ctx), found, progress=progress)


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
        line = said(conn, done)
        if not line.startswith(NOT_READ):
            forget_failure(conn, link.url, now)
    end(line, "skipped" if line.startswith(NOT_READ) else "done")
