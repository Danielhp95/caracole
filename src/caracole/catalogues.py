"""The public catalogue file: ``caracole index publish DIR`` writes every site's index, gzipped, under a name that
holds its schema and its minute, with a sidecar (``published.json``) and the rule
for which published files stay.

- ``indexes-s17-20261124T0312Z.sqlite.gz``: ``name_for`` and ``read_name``. The gzip is made with no name and a
  time of 0, so the same export is the same bytes.
- ``publish``: ``index_transfer.export`` (``PUBLIC_OMIT``: nothing private) into a temporary file in the folder,
  ``PRAGMA quick_check``, gzip -9 streamed while hashed, renamed into place, ``published.json`` written, the
  folder's older files deleted. Refused (``PublishError``, nothing left behind) for a name that exists, a UG index
  not built whole, or a site holding a tenth fewer rows than the last file's, unless ``last`` is None (--force).
- ``kept``: the Keep rule, one function, the upload script's (``caracole index publish --kept``).
  A name that isn't a catalogue file is always kept; of the others, the publishing schema's two newest whatever
  their age, and every other schema's newest while it is no older than ``keep_days``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import secrets
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PREFIX = "indexes"
SIDECAR = "published.json"
KEEP_DAYS = 180
FEWER = 0.9
CHUNK = 1 << 20
_NAME = re.compile(rf"{PREFIX}-s(\d+)-(\d{{8}}T\d{{4}}Z)\.sqlite\.gz")
_STAMP = "%Y%m%dT%H%MZ"


class PublishError(Exception):
    """A publication refused, nothing left behind: its words say why."""


@dataclass(frozen=True)
class Named:
    schema: int
    at: datetime


@dataclass(frozen=True)
class Published:
    name: str
    schema: int
    made: str
    bytes: int
    raw_bytes: int
    sha256: str
    rows: dict[str, int]

    def as_json(self) -> dict[str, Any]:
        return {"file": self.name, "schema": self.schema, "made": self.made, "bytes": self.bytes,
                "raw_bytes": self.raw_bytes, "sha256": self.sha256, "sites": dict(self.rows)}


def name_for(schema: int, at: datetime) -> str:
    return f"{PREFIX}-s{schema}-{_utc(at).strftime(_STAMP)}.sqlite.gz"


def read_name(name: str) -> Named | None:
    m = _NAME.fullmatch(name)
    if m is None:
        return None
    try:
        at = datetime.strptime(m.group(2), _STAMP).replace(tzinfo=UTC)
    except ValueError:
        return None
    return Named(int(m.group(1)), at)


def _utc(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def published(folder: Path) -> Published | None:
    """What ``published.json`` in ``folder`` says, or None where it is missing or unreadable."""
    try:
        d = json.loads((folder / SIDECAR).read_text(encoding="utf-8"))
        return Published(d["file"], d["schema"], d["made"], d["bytes"], d["raw_bytes"], d["sha256"],
                         {str(k): int(v) for k, v in d["sites"].items()})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def kept(names: Iterable[str], *, schema: int, now: datetime, keep_days: int = KEEP_DAYS) -> set[str]:
    """Of ``names``, those the Keep rule keeps."""
    now = _utc(now)
    out: set[str] = set()
    by_schema: dict[int, list[tuple[datetime, str]]] = {}
    for name in names:
        named = read_name(name)
        if named is None:
            out.add(name)
        else:
            by_schema.setdefault(named.schema, []).append((named.at, name))
    for s, found in by_schema.items():
        found.sort(reverse=True)
        if s == schema:
            out.update(n for _, n in found[:2])
        elif now - found[0][0] <= timedelta(days=keep_days):
            out.add(found[0][1])
    return out


def publish(conn: sqlite3.Connection, folder: Path, *, now: datetime, last: Published | None) -> Published:
    from caracole import db, stamps
    from caracole import index_transfer as transfer
    from caracole.ug.index import BUILT_KEY

    now = _utc(now)
    name = name_for(db.SCHEMA_VERSION, now)
    target = folder / name
    if os.path.lexists(target):
        raise PublishError(f"{target} exists: wait a minute, or remove it first")
    if db.kv_get(conn, BUILT_KEY) is None:
        raise PublishError("UG's index isn't built whole yet")
    token = secrets.token_hex(6)
    raw = folder / f".export-{token}.sqlite"
    part = folder / f".{name}.{token}.part"
    try:
        try:
            exported = transfer.export(conn, raw, now=now, omit=transfer.PUBLIC_OMIT)
        except transfer.TransferError as e:
            raise PublishError(str(e)) from e
        rows = {site: exported.rows[transfer.SITES[site].tables[0]] for site in exported.sites}
        if last is not None:
            for site, before in last.rows.items():
                if site in rows and before > 0 and rows[site] < FEWER * before:
                    raise PublishError(f"{transfer.SITES[site].title} holds {rows[site]:,} rows, a tenth fewer "
                                       f"than the last file's {before:,}: --force publishes it")
        check = sqlite3.connect(raw)
        try:
            (verdict,) = check.execute("PRAGMA quick_check").fetchone()
        finally:
            check.close()
        if verdict != "ok":
            raise PublishError(f"the export fails its check: {verdict}")
        digest = hashlib.sha256()
        with open(part, "wb") as out, open(raw, "rb") as src:
            hashed = _Hashing(out, digest)
            with gzip.GzipFile(filename="", mode="wb", compresslevel=9, mtime=0, fileobj=hashed) as gz:
                while chunk := src.read(CHUNK):
                    gz.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.replace(part, target)
        result = Published(name, db.SCHEMA_VERSION, stamps.stamp(now), target.stat().st_size, exported.size,
                           digest.hexdigest(), rows)
    except OSError as e:
        raise PublishError(f"can't write in {folder}: {e}") from e
    finally:
        raw.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
    side = folder / f".{SIDECAR}.{token}"
    side.write_text(json.dumps(result.as_json(), indent=2) + "\n", encoding="utf-8")
    os.replace(side, folder / SIDECAR)
    for other in folder.glob(f"{PREFIX}-*.sqlite.gz"):
        if other.name != name:
            other.unlink(missing_ok=True)
    return result


class _Hashing:
    """A write-only file that hashes what the gzip writes through it."""

    def __init__(self, out, digest) -> None:
        self._out, self._digest = out, digest

    def write(self, data: bytes) -> int:
        self._digest.update(data)
        return self._out.write(data)

    def flush(self) -> None:
        self._out.flush()
