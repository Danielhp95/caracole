"""The requests ``caracole serve`` queues, each a few caracole commands, run one at a time.

A job is a list of steps; a step is one run of the ``caracole`` command line, in
a child process with the server's environment and config. A request is
``caracole add``; fetching a song now adds ``caracole match`` (offline), ``caracole
fetch --song`` and ``caracole render`` (offline). Each command takes caracole's
lock, waits behind a nightly run that holds it, keeps the pause after the last
request any caracole sent, and keeps its budget and cooldowns, exactly as from
a terminal. One worker thread runs the jobs in order, so the server never runs
two commands at once: it can be no more aggressive than someone typing them.

A step that exits non-zero fails its job, and the job's other steps are
skipped. The queue holds ``limit`` jobs waiting or running, one per song (a
fetch joins the song's waiting add, or follows it once it runs), and
remembers the last ``keep`` finished ones, in memory only: a request is in
wanted.txt from the moment it's made, so a restart loses no song, only the
fetch that would have come before the nightly run.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

Runner = Callable[[Sequence[str], Callable[[str], None]], int]
LIMIT = 20  # jobs waiting or running
KEEP = 30  # finished jobs remembered
MAX_LINES = 400  # output kept per step: the last lines


class QueueFull(Exception):
    """The queue holds ``limit`` jobs already."""


@dataclass
class Step:
    label: str
    args: tuple[str, ...]
    state: str = "waiting"  # waiting, running, done, failed, skipped
    code: int | None = None
    output: list[str] = field(default_factory=list)  # its last lines
    dropped: int = 0  # the lines before them


@dataclass
class Job:
    id: int
    title: str
    song_key: str
    steps: list[Step]
    fetching: bool = False
    note: str = ""
    state: str = "queued"  # queued, running, done, failed
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")


def add_steps(artist: str, title: str, *, album: str | None = None,
              duration_ms: int | None = None) -> list[tuple[str, tuple[str, ...]]]:
    """``caracole add``, as you'd type it; ``--`` ends the options, so a name may start with "-"."""
    from caracole.wanted import format_duration

    args = ["add"]
    if album:
        args.append(f"--album={album}")
    if duration_ms is not None:
        args.append(f"--duration={format_duration(duration_ms)}")
    return [("Add to the library", (*args, "--", artist, title))]


def fetch_steps(display: str) -> list[tuple[str, tuple[str, ...]]]:
    """Fetch one song now: match it (offline), fetch it from UG, render its PDF (offline)."""
    return [
        ("Match against the index", ("match",)),
        ("Fetch from Ultimate Guitar", ("fetch", f"--song={display}")),
        ("Render the PDF", ("render",)),
    ]


REMOVING = "remove:"  # a removal's song_key: the song's key after it, so it never joins the song's add or fetch


def remove_steps(display: str) -> list[tuple[str, tuple[str, ...]]]:
    """``caracole remove --yes``: the page asked already, and showed what goes."""
    return [("Remove from caracole", ("remove", "--yes", "--", display))]


class JobQueue:
    """Jobs in order, run by one worker thread (``start``), or by ``run_pending`` in tests."""

    def __init__(self, runner: Runner, *, limit: int = LIMIT, keep: int = KEEP, max_lines: int = MAX_LINES):
        self._runner = runner
        self._limit = limit
        self._keep = keep
        self._max_lines = max_lines
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._jobs: list[Job] = []
        self._next_id = 1
        self._stopping = False
        self._thread: threading.Thread | None = None

    # --- what the pages ask -------------------------------------------------------------------

    def submit(self, title: str, song_key: str, steps: Sequence[tuple[str, Sequence[str]]], *,
               fetching: bool = False, note: str = "") -> tuple[Job, bool]:
        """Queue a job, and say whether it is new: one per song, unless a fetch must come after an add.

        A song's waiting or running job that does as much (a fetch, or the new
        job fetches nothing) is the answer. A fetch joins a song's add that
        still waits: the add gets the fetch's steps of the commands it doesn't
        run (one ``caracole add``, whatever its album: the server wrote
        wanted.txt already). One asked for while the add runs comes after it,
        as a job of its own. Raises QueueFull when ``limit`` jobs are waiting
        or running.
        """
        with self._lock:
            mine = [job for job in self._jobs if job.active and job.song_key == song_key]
            enough = next((job for job in mine if job.fetching), None)  # a fetch does the most
            if enough is None and not fetching and mine:
                enough = mine[0]
            if enough is not None:
                return copy.deepcopy(enough), False
            waiting = next((job for job in mine if job.state == "queued"), None)
            if waiting is not None:
                runs = {step.args[0] for step in waiting.steps}
                waiting.steps += [Step(label, tuple(args)) for label, args in steps if args[0] not in runs]
                waiting.title, waiting.fetching = title, True
                waiting.note = waiting.note or note
                return copy.deepcopy(waiting), False
            if sum(job.active for job in self._jobs) >= self._limit:
                raise QueueFull(f"{self._limit} requests are waiting already")
            job = Job(self._next_id, title, song_key, [Step(label, tuple(args)) for label, args in steps],
                      fetching=fetching, note=note)
            self._next_id += 1
            self._jobs.append(job)
            self._wake.notify_all()
            return copy.deepcopy(job), True

    def snapshot(self) -> list[Job]:
        """Every job remembered, newest first, as copies."""
        with self._lock:
            return copy.deepcopy(self._jobs[::-1])

    def active_count(self) -> int:
        with self._lock:
            return sum(job.active for job in self._jobs)

    def fetching_keys(self) -> set[str]:
        """The songs a waiting or running job will fetch."""
        with self._lock:
            return {job.song_key for job in self._jobs if job.active and job.fetching}

    # --- the worker ------------------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="caracole-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        """Stop the worker, ending the command it runs."""
        with self._lock:
            self._stopping = True
            self._wake.notify_all()
        terminate = getattr(self._runner, "terminate", None)
        if terminate is not None:
            terminate()
        if self._thread is not None:
            self._thread.join(timeout)

    def run_pending(self) -> None:
        """Run the queued jobs here and now, in order."""
        while (job := self._next()) is not None:
            self._run(job)

    def _work(self) -> None:
        while True:
            with self._lock:
                while not self._stopping and not any(j.state == "queued" for j in self._jobs):
                    self._wake.wait()
                if self._stopping:
                    return
            job = self._next()
            if job is not None:
                self._run(job)

    def _next(self) -> Job | None:
        with self._lock:
            job = next((j for j in self._jobs if j.state == "queued"), None)
            if job is not None:
                job.state = "running"
                job.started_at = datetime.now(UTC)
            return job

    def _run(self, job: Job) -> None:
        failed = False
        for step in job.steps:
            with self._lock:
                if failed or self._stopping:
                    step.state = "skipped"
                    continue
                step.state = "running"

            def emit(line: str, step: Step = step) -> None:
                with self._lock:
                    step.output.append(line)
                    if len(step.output) > self._max_lines:
                        del step.output[0]
                        step.dropped += 1

            try:
                code = self._runner(step.args, emit)
            except Exception as e:  # noqa: BLE001 (the child couldn't start: the job fails, the queue goes on)
                emit(f"caracole couldn't start: {e}")
                code = None
            with self._lock:
                step.code = code
                step.state = "done" if code == 0 else "failed"
                failed = failed or code != 0
        with self._lock:
            job.state = "failed" if failed or any(s.state != "done" for s in job.steps) else "done"
            job.finished_at = datetime.now(UTC)
            self._forget()

    def _forget(self) -> None:
        """Keep the last ``keep`` finished jobs."""
        finished = [j for j in self._jobs if not j.active]
        for job in finished[: max(0, len(finished) - self._keep)]:
            self._jobs.remove(job)


# --- the caracole command line, in a child process ---------------------------------------------


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's environment: the server's, with this Python's path, its output unbuffered.

    The Nix wrapper adds caracole's dependencies to ``sys.path`` inside its script,
    not through the environment, so the child gets the path this process runs with.
    """
    env = dict(os.environ if base is None else base)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    env["PYTHONUNBUFFERED"] = "1"  # so each line shows on the requests page as it is printed
    return env


class CaracoleRunner:
    """Runs ``python -P -m caracole [--config FILE] ARGS…`` and hands each line it prints to ``emit``.

    ``-m`` alone would put the working directory first on the child's
    ``sys.path``, which the ``caracole`` script never does: started from the
    synced library, the server would run any ``typer.py`` a device dropped
    there. ``-P`` (Python 3.11) leaves it out.
    """

    def __init__(self, config_path: Path | None, *, python: str = sys.executable):
        self._argv = [python, "-P", "-m", "caracole", *(["--config", str(config_path)] if config_path else [])]
        self._env = child_env()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def __call__(self, args: Sequence[str], emit: Callable[[str], None]) -> int:
        process = subprocess.Popen(
            [*self._argv, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=self._env,
        )
        with self._lock:
            self._process = process
        try:
            assert process.stdout is not None
            for line in process.stdout:
                emit(line.rstrip("\n"))
            return process.wait()
        finally:
            with self._lock:
                self._process = None

    def terminate(self) -> None:
        """End the command running now, as Ctrl-C or systemd would: it lets go of the lock as it exits."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
