"""``caracole audio``: a song's auto sheet from an audio file you give it, now.

``caracole audio FILE`` copies the file into caracole's own folder (``state_dir/audio/``, audio_store.py) as the song's
audio, whatever it had (a purchase, whose file stays in Music/, or YouTube's), and makes its auto sheet from it
(audio_sheet.py): its lyrics from the lyrics sites, else its words heard from the file where this caracole can
transcribe and ``[autochords] transcribe`` is on, the chords from the file, its PDF and viewer, then the pages.
``caracole audio --upload ID`` takes a file caracole serve staged there instead, moved into place (the library page's
"+"). The song is ``--song "ARTIST - TITLE"``, else what the file names (``audio_sheet.names_of``: its tags, else its
own name), said as it is read; a song new to the library goes into wanted.txt with the file's album and length.
``--progress`` adds a JSON line per stage, which caracole serve reads, as ``caracole get --progress`` does; without
it, what a long stage is doing goes on progress.py's ticker.

It takes caracole's lock as asked for now, and hands it to a waiting lookup before each of the vocals, the words and
the chords. It exits 0 once the sheet is made, words or none, and for a site's wait (a block, a cooldown, a spent
budget, a site's error); 1 for a song it won't make a sheet of (ignored, or with a human sheet), a file caracole
doesn't read, audio auto-chords can't read, and, saying so before it reads anything, a caracole that makes no chords
(``youtube_fetch.autochords_problem``: no auto-chords, or its model files missing; neither YouTube nor yt-dlp is
needed); 2 for a file that names no artist with no ``--song``, as for any usage error.

Every command module is imported on every start, so the job, the tag reader and the models are imported inside the
command.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from caracole.commands._common import fail, load_cfg, staged_end

if TYPE_CHECKING:
    from caracole.config import Config

NOT_BUILT = "use the flake's packages.autochords"


def register(app: typer.Typer) -> None:
    @app.command("audio")
    def audio_cmd(
        ctx: typer.Context,
        file: Path | None = typer.Argument(
            None, metavar="FILE", exists=True, dir_okay=False,
            help="The audio file (MP3, M4A, FLAC, WAV, Ogg or AIFF): copied into caracole's own folder.",
        ),
        song: str | None = typer.Option(
            None, "--song", metavar='"ARTIST - TITLE"',
            help="The song; without it, the one the file's tags name, else its name.",
        ),
        upload: str | None = typer.Option(
            None, "--upload", metavar="ID", help="An upload caracole serve staged, in place of FILE: moved into place.",
        ),
        progress: bool = typer.Option(False, "--progress", help="A JSON line per stage too, for caracole serve."),
    ) -> None:
        """Make a song's auto sheet from an audio file of yours: its chords, and its lyrics from the lyrics sites, else
        heard from the file."""
        if (file is None) == (upload is None):
            raise typer.BadParameter("give an audio FILE or --upload ID, one of them", param_hint="FILE/--upload")
        _audio(load_cfg(ctx), file, upload, song, progress=progress)


def _audio(cfg: Config, file: Path | None, upload: str | None, display: str | None, *, progress: bool) -> None:
    """The song's auto sheet from the file now (audio_sheet.py), said a stage a line, as ``caracole get`` says its own;
    nothing is read or asked when this caracole makes no chords, nor written when the file is no audio it reads."""
    from caracole import audio_store
    from caracole.audio_sheet import AudioRequest, make_audio_sheet
    from caracole.commands.get import _Lines
    from caracole.logs import plural, provider_name
    from caracole.overrides import OverridesError, override_key
    from caracole.progress import ticker
    from caracole.youtube_fetch import autochords_problem

    if display is not None:
        try:
            override_key(display)
        except OverridesError as e:
            fail(str(e), 2)
    problem = autochords_problem(cfg)
    if problem is not None:
        hint = f"; {NOT_BUILT}" if "built without" in problem else ""
        fail(f"caracole makes no sheet from an audio file here: {problem}{hint}")
    try:
        if upload is not None:
            up = audio_store.staged(cfg, upload)
            name, duration, tags = up.name, up.duration, up.tags
        else:  # FILE, the one of the two given
            found = audio_store.examine(file)
            name, duration, tags = file.name, found.duration, found.tags
    except audio_store.AudioError as e:
        fail(str(e), 2 if e.status == 400 else 1)
    except OSError as e:
        fail(f"can't read {file}: {e.strerror or e}")
    if display is not None:
        artist, _, title = display.partition(" - ")
    else:
        artist, title = _named(cfg, name, tags)
    request = AudioRequest(artist.strip(), title.strip(), file=file, upload=upload, album=tags.get("album"),
                           duration=duration)
    with _Lines(cfg.library_dir, show=False, json_lines=progress, ticker=None if progress else ticker()) as reporter:
        result = make_audio_sheet(cfg, request, reporter)
        sent = ", ".join(plural(n, f"{provider_name(p)} request") for p, n in result.requests.items() if n)
        staged_end(reporter, result, progress=progress, refused="No sheet made",
                   done=f"Done in {result.seconds:.1f} s" + (f": {sent}." if sent else ", asking nothing."))


def _named(cfg: Config, name: str, tags: dict[str, str | None]) -> tuple[str, str]:
    """The song the file names, by its tags or its name, said; exit 2 for one that names no artist. A database
    caracole can't open now knows no artist, and the name is read all the same."""
    import sqlite3

    from caracole import db
    from caracole.audio_sheet import names_of

    try:
        conn: sqlite3.Connection | None = db.connect(cfg.db_path)
    except (OSError, sqlite3.Error):
        conn = None
    try:
        artist, title = names_of(conn, name, tags)
    finally:
        if conn is not None:
            conn.close()
    if artist is None:
        fail(f"Its tags and its name don't say who its artist is: name the song, --song \"ARTIST - {title}\"", 2)
    typer.echo(f"Read “{name}” as {artist} - {title}.")
    return artist, title
