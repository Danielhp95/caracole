"""``caracole transcribe``: a song's lyrics transcribed from its YouTube audio, and its auto sheet made again over them.

``--song "Artist - Title"`` names a song of the library whose audio came from YouTube and that every lyrics site
switched on missed (transcript.py ``why_not_offered``): its vocals separated by demucs-rs, its words heard by Whisper
large-v3 on the full mix, those outside the singing dropped, the rest kept as its transcript (never as its lyrics),
then its auto sheet made again with the chords over them, its PDF and viewer, and the pages (transcribe_job.py).
``--progress`` adds a JSON line per stage, which caracole serve reads, as ``caracole get --progress`` does.

It takes caracole's lock as asked for now, and hands it to a waiting lookup before each long stage. It exits 0 once
the sheet is made; 1 for a song not offered a transcription, for no singing heard, for audio that can't be read, for
a separator or a GPU that can't run here, and, saying so before it asks anything, for a caracole that transcribes
nothing (``youtube_fetch.transcribe_problem``: no auto-chords, no Whisper, a model file or demucs-rs missing).

Every command module is imported on every start, so the job is imported inside the command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from caracole.commands._common import fail, load_cfg

if TYPE_CHECKING:
    from caracole.config import Config


def register(app: typer.Typer) -> None:
    @app.command("transcribe")
    def transcribe_cmd(
        ctx: typer.Context,
        song: str = typer.Option(
            ..., "--song", metavar='"ARTIST - TITLE"',
            help="The song: one whose audio came from YouTube and whose lyrics no lyrics site has.",
        ),
        progress: bool = typer.Option(False, "--progress", help="A JSON line per stage too, for caracole serve."),
    ) -> None:
        """Transcribe a song's lyrics from its YouTube audio (Whisper), and make its auto sheet again over them."""
        _transcribe(load_cfg(ctx), song, progress=progress)


def _transcribe(cfg: Config, display: str, *, progress: bool) -> None:
    """The song's lyrics transcribed now (transcribe_job.py), said a stage a line, as ``caracole get`` says its own;
    nothing is done when this caracole transcribes nothing."""
    from caracole.commands.get import _Lines
    from caracole.overrides import OverridesError, override_key
    from caracole.transcribe_job import TranscribeRequest, make_transcript
    from caracole.youtube_fetch import transcribe_problem

    try:
        override_key(display)
    except OverridesError as e:
        fail(str(e), 2)
    problem = transcribe_problem(cfg)
    if problem is not None:
        fail(f"caracole transcribes nothing here: {problem}")
    artist, _, title = display.partition(" - ")
    reporter = _Lines(cfg.library_dir, show=False, json_lines=progress)
    result = make_transcript(cfg, TranscribeRequest(artist.strip(), title.strip()), reporter)
    reporter.flush()
    if result.refused:
        typer.echo(f"No transcript made: {result.refused}.")
    else:
        typer.echo(f"Done in {result.seconds:.1f} s.")
    if progress:
        typer.echo(reporter.event({"done": {"seconds": round(result.seconds, 3), "requests": result.requests,
                                            "ok": result.ok, "refused": result.refused}}))
    if not result.ok:
        raise typer.Exit(1)
