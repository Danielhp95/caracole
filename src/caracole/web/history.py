"""The Requests tab's history, kept across a restart of caracole serve: ``state_dir/requests.jsonl``.

Each line is a JSON object: a request as it stood when it last changed (``{"v": 1, "id": 12, "title": …}``, every
field of jobs.py's ``Job``, its steps with what each command printed, its stages, its times), or the first line of a
file written whole, ``{"v": 1, "next": 31}``, the id the next request gets. The queue (``JobQueue``) saves a request
when it is queued or changed while it waits, when it starts, and when it is over or cancelled, a line appended in one
write (``save``); the last line of a request is what it was.

The server reads it when it starts (``load``): the requests of the last ``days`` days, the ``keep`` newest of them,
as the Requests tab showed them, the ids it gives next after theirs, so a ``job=N`` link never names another
request. A request that waited or ran when the server stopped, a crash or a kill that left it so, is
**interrupted** (``INTERRUPTED``): its running step and stage too, the rest skipped. Stopped as systemd or Ctrl-C
stops it, the queue ends the running command and saves the request interrupted itself, with what it printed. A
request interrupted is over: Try again queues its steps again.

The file never grows without bound: a step keeps its last ``lines`` lines, each of ``line_chars`` characters at most,
and the file is written again whole, with the requests the queue remembers (those ``load`` keeps), when it holds
more than three lines a request kept or more than ``max_bytes``; it is written whole once more when the server
starts. A file written whole goes to a temporary file in the same folder, synced, then renamed over the old one, so
a crash leaves one or the other; a crash during an append leaves at most a line cut short. A line that can't be read
(cut short, not JSON, not a request of this version) is skipped, and gone from the file once it is written whole.
Nothing here ever stops a request: a history that can't be read or written is logged, and the queue goes on.

Why a file of its own, not a table in caracole.sqlite: ``caracole serve`` never takes caracole's lock, and its
requests are written by its own threads, while a command runs under that lock in a child process. caracole serve
is this file's one writer and reader, so it needs no lock but the queue's own (``JobQueue``'s, which every save is
made under, in order), and a database it never writes keeps its rule: every change to it is a caracole command's.
A line a request also reads well in a terminal (``tail state/requests.jsonl``), for a question about what ran. The
state folder is private, and so is the file (0600): what the commands printed is there.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from caracole.web.jobs import INTERRUPTED, KEEP, Job, Stage, Step

log = logging.getLogger(__name__)

FILE_NAME = "requests.jsonl"
VERSION = 1
DAYS = 30  # a request over longer ago than this is not read back (and the newest ``KEEP``, jobs.py, at most)
LINES = 200  # the last lines of a step's output kept
LINE_CHARS = 1000  # characters of a line kept
MAX_BYTES = 4 * 1024 * 1024  # the file written whole beyond this
_READ_AT_MOST = 4 * MAX_BYTES  # of a file grown beyond its size (its rewrites failing): its end alone is read
_JOB_STATES = frozenset({"queued", "running", "done", "failed", "cancelled", INTERRUPTED})
_STEP_STATES = frozenset({"waiting", "running", "done", "failed", "skipped", INTERRUPTED})


class History:
    """The requests of caracole serve, in the file at ``path``."""

    def __init__(self, path: Path, *, keep: int = KEEP, days: int = DAYS, lines: int = LINES,
                 line_chars: int = LINE_CHARS, max_bytes: int = MAX_BYTES):
        self.path = path
        self.keep = keep
        self.days = days
        self.lines = lines
        self.line_chars = line_chars
        self.max_bytes = max_bytes
        self._count = 0  # lines in the file
        self._size = 0  # its bytes
        self._failed = False  # the last write failed: said once until one succeeds

    # --- reading -----------------------------------------------------------------------------------------------------

    def load(self, now: datetime | None = None) -> tuple[list[Job], int]:
        """The requests to show again, oldest first, each one that waited or ran interrupted, and the id the next
        request gets; the file written again whole with them."""
        now = now or datetime.now(UTC)
        try:
            data = self._read()
        except FileNotFoundError:
            return [], 1
        except OSError as e:
            log.warning("caracole serve: its request history %s can't be read (%s): it starts with none",
                        self.path, e.strerror or e)
            return [], 1
        jobs: dict[int, Job] = {}
        next_id, skipped = 1, 0
        for line in data.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict) or record.get("v") != VERSION:
                    raise ValueError("not a record of this version")
                if "next" in record and "id" not in record:
                    next_id = max(next_id, _int(record["next"]))
                    continue
                job = _job(record)
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                skipped += 1
                continue
            jobs[job.id] = job
            next_id = max(next_id, job.id + 1)
        if skipped:
            log.warning("caracole serve: %d line(s) of its request history %s couldn't be read and are left out",
                        skipped, self.path)
        for job in jobs.values():
            if job.active:
                interrupt(job, at=job.finished_at or job.started_at or job.queued_at)
        kept = self._kept(sorted(jobs.values(), key=lambda job: job.id), now)
        self.rewrite(kept, next_id)
        return kept, next_id

    def _read(self) -> bytes:
        with self.path.open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size > _READ_AT_MOST:  # the end of it alone, from its first whole line
                f.seek(size - _READ_AT_MOST)
                f.readline()
            return f.read()

    def _kept(self, jobs: Sequence[Job], now: datetime) -> list[Job]:
        """Of ``jobs`` (oldest first), those a file written whole keeps: every one waiting or running, and the
        ``keep`` newest of those over within ``days`` days."""
        since = now - timedelta(days=self.days)
        over = [job for job in jobs if not job.active and (job.finished_at or job.queued_at) >= since]
        kept = {job.id for job in over[max(0, len(over) - self.keep):]}
        return [job for job in jobs if job.active or job.id in kept]

    # --- writing -----------------------------------------------------------------------------------------------------

    def save(self, job: Job, jobs: Sequence[Job], next_id: int) -> None:
        """Add ``job`` as it is now, in one write; then, when the file holds too much, write it again whole with
        ``jobs`` (the queue's, oldest first) and ``next_id``."""
        line = self._line(_record(job, self.lines, self.line_chars))
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
            try:
                _write_all(fd, line)
            finally:
                os.close(fd)
        except OSError as e:
            self._could_not("add to", e)
            return
        self._ok()
        self._count += 1
        self._size += len(line)
        if self._count > 3 * self.keep or self._size > self.max_bytes:
            self.rewrite(self._kept(jobs, datetime.now(UTC)), next_id)

    def rewrite(self, jobs: Sequence[Job], next_id: int) -> None:
        """Write the file again whole: its first line ``next_id``, then ``jobs`` (oldest first), the oldest over
        left out while it holds more than ``max_bytes`` (never the newest, nor one waiting or running)."""
        lines = [self._line(_record(job, self.lines, self.line_chars)) for job in jobs]
        head = self._line({"v": VERSION, "next": next_id})
        size = len(head) + sum(map(len, lines))
        dropped = set()
        for n, job in enumerate(jobs[:-1]):
            if size <= self.max_bytes:
                break
            if not job.active:
                dropped.add(n)
                size -= len(lines[n])
        data = head + b"".join(line for n, line in enumerate(lines) if n not in dropped)
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(6)}.tmp")
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            try:
                _write_all(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, self.path)
            _sync_folder(self.path.parent)
        except OSError as e:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            self._could_not("write", e)
            return
        self._ok()
        self._count = 1 + len(lines) - len(dropped)
        self._size = len(data)

    def _line(self, record: Mapping[str, Any]) -> bytes:
        text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        return text.encode("utf-8", errors="replace") + b"\n"

    def _could_not(self, what: str, e: OSError) -> None:
        if not self._failed:
            log.warning("caracole serve: can't %s its request history %s (%s): the requests go on, and a restart "
                        "may forget them", what, self.path, e.strerror or e)
        self._failed = True

    def _ok(self) -> None:
        if self._failed:
            log.info("caracole serve: its request history %s is written again", self.path)
        self._failed = False


def interrupt(job: Job, *, at: datetime) -> None:
    """A request the server stopped before it was over: interrupted, its running step and stage too, those waiting
    skipped; over ``at``, unless it says when already."""
    job.state = INTERRUPTED
    job.finished_at = job.finished_at or at
    for part in (*job.steps, *job.stages):
        if part.state == "running":
            part.state = INTERRUPTED
        elif part.state == "waiting":
            part.state = "skipped"


# --- a request as a line, and back ----------------------------------------------------------------------------------


def _record(job: Job, lines: int, line_chars: int) -> dict[str, Any]:
    return {
        "v": VERSION, "id": job.id, "title": job.title, "song_key": job.song_key, "display": job.display,
        "state": job.state, "fetching": job.fetching, "note": job.note,
        "queued_at": _when(job.queued_at), "started_at": _when(job.started_at), "finished_at": _when(job.finished_at),
        "steps": [_step(step, lines, line_chars) for step in job.steps],
        "stages": [{"name": s.name, "label": s.label, "state": s.state, "detail": s.detail,
                    "running_detail": s.running_detail} for s in job.stages],
        "song_id": job.song_id, "song_display": job.song_display, "files": dict(job.files),
        "seconds_to_sheet": job.seconds_to_sheet, "together": list(job.together),
    }


def _step(step: Step, lines: int, line_chars: int) -> dict[str, Any]:
    output = step.output[-lines:] if lines else []
    return {"label": step.label, "args": list(step.args), "state": step.state, "code": step.code,
            "output": [line if len(line) <= line_chars else line[:max(0, line_chars - 1)] + "…" for line in output],
            "dropped": step.dropped + len(step.output) - len(output)}


def _job(record: Mapping[str, Any]) -> Job:
    """A request from its line; ValueError (or TypeError, KeyError) for one that isn't one."""
    state = _str(record["state"])
    if state not in _JOB_STATES:
        raise ValueError(f"no such state: {state}")
    return Job(
        _int(record["id"]), _str(record["title"]), _str(record["song_key"]),
        [_step_of(step) for step in _list(record["steps"])],
        fetching=_bool(record.get("fetching", False)), note=_str(record.get("note", "")),
        display=_str(record.get("display", "")), state=state,
        queued_at=_time(record["queued_at"]), started_at=_maybe_time(record.get("started_at")),
        finished_at=_maybe_time(record.get("finished_at")),
        stages=[_stage_of(stage) for stage in _list(record.get("stages", []))],
        song_id=_maybe_int(record.get("song_id")), song_display=_maybe_str(record.get("song_display")),
        files={_str(k): _str(v) for k, v in _dict(record.get("files", {})).items()},
        seconds_to_sheet=_maybe_number(record.get("seconds_to_sheet")),
        together=tuple(_int(n) for n in _list(record.get("together", []))),
    )


def _step_of(record: Any) -> Step:
    record = _dict(record)
    state = _str(record["state"])
    if state not in _STEP_STATES:
        raise ValueError(f"no such state: {state}")
    return Step(_str(record["label"]), tuple(_str(arg) for arg in _list(record["args"])), state=state,
                code=_maybe_int(record.get("code")), output=[_str(line) for line in _list(record.get("output", []))],
                dropped=_int(record.get("dropped", 0)))


def _stage_of(record: Any) -> Stage:
    record = _dict(record)
    return Stage(_str(record["name"]), _str(record["label"]), state=_str(record.get("state", "waiting")),
                 detail=_str(record.get("detail", "")), running_detail=_str(record.get("running_detail", "")))


def _when(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt is not None else None


def _time(value: Any) -> datetime:
    dt = datetime.fromisoformat(_str(value))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)  # a naive time is UTC (stamps.py)


def _maybe_time(value: Any) -> datetime | None:
    return None if value is None else _time(value)


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"not a string: {value!r}")
    return value


def _maybe_str(value: Any) -> str | None:
    return None if value is None else _str(value)


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"not a whole number: {value!r}")
    return value


def _maybe_int(value: Any) -> int | None:
    return None if value is None else _int(value)


def _maybe_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"not a number: {value!r}")
    return float(value)


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"not true or false: {value!r}")
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"not a list: {value!r}")
    return value


def _dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"not an object: {value!r}")
    return value


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _sync_folder(folder: Path) -> None:
    """Sync the folder, so that a rename survives a crash; a system that can't is let be."""
    try:
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
