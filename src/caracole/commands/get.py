"""``caracole get``: one song, now, sheet first (get.py), at the interactive pace.

    caracole get "Oasis - Wonderwall"
    caracole get --print Oasis Wonderwall      # and the sheet itself, the moment it is kept

It says where the sheet is as soon as it is kept, then what each other stage
did. ``--ug`` and ``--tab`` record the Ultimate Guitar song or tab you picked
(``[match]``, ``[pin]``). ``--progress`` adds a JSON line per event, which
caracole serve reads (``get.read_progress_line``). A block or a spent budget
exits 0, as in every command; a song caracole won't look up (ignored, or one
wanted.txt can't hold) exits 1, as does a bug; a usage error exits 2. The
lookup code is imported inside the command, as every command module is
imported on every start.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import fail, load_cfg

if TYPE_CHECKING:
    from caracole.config import Config
    from caracole.get import LookupResult

_SHORT = {"song": "Song", "match": "Match", "sheet": "Sheet", "pdf": "PDF", "lyrics": "Lyrics",
          "ug": "Ultimate Guitar", "lacuerda": "LaCuerda", "gtptabs": "gtptabs.com", "pages": "Pages"}
_SONG_SHAPE = 'a song as "Artist - Title", or as ARTIST TITLE'


def register(app: typer.Typer) -> None:
    @app.command("get")
    def get_cmd(
        ctx: typer.Context,
        song: list[str] = typer.Argument(..., metavar='"ARTIST - TITLE"', help='"Artist - Title", or ARTIST TITLE.'),
        album: str | None = typer.Option(None, "--album", help="The album, for a song new to the library."),
        duration: str | None = typer.Option(None, "--duration", metavar="M:SS",
                                            help="The length, as m:ss or seconds, for a song new to the library."),
        ug: str | None = typer.Option(None, "--ug", metavar="ARTIST-KEY/SONG-KEY",
                                      help="The Ultimate Guitar song to use, as caracole search shows it; "
                                           "recorded under [match] in overrides.toml."),
        tab: str | None = typer.Option(None, "--tab", metavar="URL",
                                       help="The Ultimate Guitar tab to use, its page's address or id; "
                                            "recorded under [pin] in overrides.toml."),
        show: bool = typer.Option(False, "--print", help="Print the sheet itself as soon as it is kept."),
        progress: bool = typer.Option(False, "--progress", help="A JSON line per stage too, for caracole serve."),
    ) -> None:
        """Look one song up now: its sheet first, in seconds, then its lyrics, PDF and the rest."""
        if len(song) == 1 and " - " not in song[0] and any(c.isalnum() for c in song[0]):
            from caracole.commands.search import offer_songs  # one name: no song, so nothing is looked up

            offer_songs(load_cfg(ctx), " ".join(song[0].split()), "get")
        artist, title = _artist_title(song)
        _check_pick(ug, tab)
        duration_ms = _duration(duration)
        _get(load_cfg(ctx), artist, title, album, duration_ms, ug, tab, show=show, progress=progress)


def _artist_title(words: list[str]) -> tuple[str, str]:
    if len(words) == 1:
        artist, sep, title = words[0].partition(" - ")
    elif len(words) == 2:
        (artist, title), sep = words, " - "
    else:
        fail(f"caracole get takes {_SONG_SHAPE}", 2)
    if not sep or not artist.strip() or not title.strip():
        fail(f"caracole get takes {_SONG_SHAPE}, not {' '.join(words)!r}", 2)
    return artist.strip(), title.strip()


def _check_pick(ug: str | None, tab: str | None) -> None:
    from caracole.overrides import OverridesError, tab_id_from_url

    if ug is not None:
        artist_key, sep, song_key = ug.strip().partition("/")
        if not sep or not artist_key or not song_key or "/" in song_key:
            fail(f"--ug takes an Ultimate Guitar song as artist-key/song-key (radiohead/creep), not {ug!r}", 2)
    if tab is not None:
        try:
            tab_id_from_url(tab)
        except OverridesError as e:
            fail(f"--tab: {e}", 2)


def _duration(text: str | None) -> int | None:
    if text is None:
        return None
    from caracole.wanted import parse_duration

    try:
        ms = parse_duration(text)
    except ValueError as e:
        fail(f"--duration: {e}", 2)
    if ms is None:
        fail(f"--duration: {text.strip()!r} isn't a duration: write m:ss, h:mm:ss or seconds", 2)
    return ms


def _get(cfg: Config, artist: str, title: str, album: str | None, duration_ms: int | None, ug: str | None,
         tab: str | None, *, show: bool, progress: bool) -> None:
    from caracole.get import LookupRequest, look_up

    request = LookupRequest(artist, title, album=album, duration_ms=duration_ms, ug=ug, tab=tab)
    reporter = _Lines(cfg.library_dir, show=show, json_lines=progress)
    result = look_up(cfg, request, reporter)
    reporter.flush()
    typer.echo(_totals(result))
    if progress:
        typer.echo(reporter.event({"done": {"seconds": round(result.seconds, 3), "requests": result.requests,
                                            "seconds_to_sheet": result.seconds_to_sheet, "ok": result.ok,
                                            "refused": result.refused}}))
    if result.refused or not result.ok:
        raise typer.Exit(1)


class _Lines:
    """The lookup as lines: one per stage, the sheet's path the moment it is readable."""

    def __init__(self, library: Path, *, show: bool, json_lines: bool):
        self.library, self.show, self.json_lines = library, show, json_lines
        self.held: str | None = None  # the sheet stage's line, said with its path
        self.files: dict[str, str] = {}

    def event(self, event: Mapping) -> str:
        from caracole.get import progress_line

        return progress_line(event)

    def _json(self, event: Mapping) -> None:
        if self.json_lines:
            typer.echo(self.event(event))

    def flush(self) -> None:
        if self.held is not None:
            typer.echo(self.held)
            self.held = None

    # --- what get.py calls ---------------------------------------------------------------------

    def stage(self, name: str, state: str, detail: str = "") -> None:
        self._json({"stage": name, "state": state, "detail": detail})
        if state == "running":
            self.flush()
            return
        said = detail or state
        if state != "done" and detail:
            said = f"{state}: {detail}"
        line = f"{_SHORT.get(name, name)}: {said}."
        if name == "sheet" and state == "done":
            self.held = line  # said with the sheet's path, next
            return
        typer.echo(line)

    def song(self, song_id: int, display: str) -> None:
        self._json({"song": {"id": song_id, "display": display}})

    def readable(self, files: Mapping[str, str], seconds: float) -> None:
        self._json({"files": dict(files), "seconds": round(seconds, 3)})
        first = not self.files
        sheet = self.library / files["sheet"]
        if first:
            said = (self.held or "Sheet: ").rstrip(".")
            self.held = None
            typer.echo(f"{said}: {sheet}, readable after {seconds:.1f} s.")
            if self.show:
                typer.echo(_sheet_text(sheet))
        else:
            for name, label in (("pdf", "PDF"), ("viewer", "Viewer")):
                if name in files and name not in self.files:
                    typer.echo(f"{label}: {self.library / files[name]}")
            if files == self.files:
                typer.echo(f"Sheet: a better one replaced it, in {sheet}.")
                if self.show:
                    typer.echo(_sheet_text(sheet))
        self.files = dict(files)


def _sheet_text(path: Path) -> str:
    from caracole.library import read_regular

    try:
        return read_regular(path).decode("utf-8", "replace").rstrip("\n")
    except OSError as e:
        return f"(the sheet can't be read: {e.strerror or e})"


def _totals(result: LookupResult) -> str:
    from caracole.get import NAMES

    sent = {p: n for p, n in result.requests.items() if n}
    total = sum(sent.values())
    words = f"{total} request" + ("" if total == 1 else "s")
    if sent:
        words += " (" + ", ".join(f"{NAMES.get(p, p)} {n}" for p, n in sent.items()) + ")"
    if result.refused:
        return f"Nothing looked up: {result.refused}."
    return f"Done in {result.seconds:.1f} s: {words}."
