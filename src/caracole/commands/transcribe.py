"""``caracole transcribe``: a song's lyrics transcribed from its YouTube audio, and its auto sheet made again over them.

``--song "Artist - Title"`` names a song of the library whose audio came from YouTube and that every lyrics site
switched on missed (transcript.py ``why_not_offered``): its vocals separated by demucs-rs, its words heard by Whisper
large-v3 on the full mix, those outside the singing dropped, the rest kept as its transcript (never as its lyrics),
then its auto sheet made again with the chords over them, its PDF and viewer, and the pages (transcribe_job.py).
``--progress`` adds a JSON line per stage, which caracole serve reads, as ``caracole get --progress`` does; without it,
what a long stage is doing is a live line on a terminal and a line a minute in the journal (progress.py ``ticker``).

The owner's word over caracole's either way: ``--force`` ("it is sung", the card's Transcribe anyway) hears a song
heard to have nothing sung, or said not sung, or whose audio Whisper couldn't load (after an ffmpeg or Whisper
upgrade), with neither rule of nothing sung (a song offered a transcription anyway is simply transcribed); ``--none``
("it isn't sung", Not sung: chords only) drops a song's transcript, notes its audio not sung, never heard again until
``--force`` or a new file (a new file is a new start), and makes its sheet again of its chords alone.

It takes caracole's lock as asked for now, and hands it to a waiting lookup before each long stage. It exits 0 once
the sheet is made; 2 for both ``--force`` and ``--none``; 1 for a song not offered a transcription (with ``--none``,
one with no transcript of its own audio), for no singing heard, for audio Whisper can't read, for
a loudness reader, a separator or a GPU that can't run here, and, saying so before it asks anything, for a caracole
that transcribes nothing (``youtube_fetch.transcribe_problem``: no auto-chords, no Whisper, a model file or demucs-rs
missing).

Every command module is imported on every start, so the job is imported inside the command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from caracole.commands._common import fail, load_cfg, staged_end

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
        force: bool = typer.Option(
            False, "--force",
            help="It is sung: hear it even where nothing sung was heard, you said so, or Whisper couldn't read it "
                 "(a song offered a transcription is simply transcribed).",
        ),
        none: bool = typer.Option(
            False, "--none",
            help="It isn't sung: drop its transcript, never hear this audio again, its sheet the chords alone.",
        ),
        progress: bool = typer.Option(False, "--progress", help="A JSON line per stage too, for caracole serve."),
    ) -> None:
        """Transcribe a song's lyrics from its YouTube audio (Whisper), and make its auto sheet again over them."""
        if force and none:
            fail("--force and --none say opposite things: give one.", 2)
        _transcribe(load_cfg(ctx), song, progress=progress, force=force, none=none)


def _transcribe(cfg: Config, display: str, *, progress: bool, force: bool = False, none: bool = False) -> None:
    """The song's lyrics transcribed now (transcribe_job.py), said a stage a line, as ``caracole get`` says its own;
    nothing is done when this caracole transcribes nothing."""
    from caracole.commands.get import _Lines
    from caracole.overrides import OverridesError, override_key
    from caracole.progress import ticker
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
    with _Lines(cfg.library_dir, show=False, json_lines=progress, ticker=None if progress else ticker()) as reporter:
        result = make_transcript(cfg, TranscribeRequest(artist.strip(), title.strip(), force=force, none=none),
                                 reporter)
        if none:
            stopped = "Nothing changed" if result.states.get("words") != "done" else "Transcript dropped; no sheet made"
        elif not result.transcript_kept:
            stopped = "No transcript made"
        elif result.states.get("chords") == "done":  # a bug after the sheet over it was kept
            stopped = "Transcript and sheet kept"
        else:
            stopped = "Transcript kept; no sheet made"
        staged_end(reporter, result, progress=progress, refused=stopped, done=f"Done in {result.seconds:.1f} s.")
