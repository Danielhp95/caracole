"""The title and creators a MusicXML file names in its header: cheap, and safe on any file.

inbox.py files a score you dropped into ``_inbox/`` by its name, and a MusicXML one
(``.musicxml``, or ``.mxl``, its zip) also by what it says it is: its ``work-title`` (or,
without one, its ``movement-title``) and the ``creator`` lines of its ``identification``.
They come before the part list, so the file is read up to there and no further, in small
pieces: a long score costs no more than its header, and what follows is never parsed.

A file in the inbox is anyone's. expat never fetches an external entity, and stops an
entity that expands without bound (its amplification limit); a header that doesn't come
within ``MAX_HEADER`` bytes, a zip that isn't one, or XML that won't parse is no header.
"""

from __future__ import annotations

import io
import zipfile
from typing import IO, NamedTuple
from xml.etree import ElementTree as ET

MAX_HEADER = 1 << 20  # bytes read, at most, before the part list
_CHUNK = 4096
_MAX_CONTAINER = 1 << 16
_STOP = frozenset({"part-list", "part"})  # where the header ends
_ERRORS = (ET.ParseError, zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, OSError, EOFError, ValueError,
           NotImplementedError, RuntimeError, UnicodeError)


class Header(NamedTuple):
    title: str
    creators: tuple[str, ...]


def header(data: bytes, ext: str) -> Header | None:
    """The header of a ``.musicxml`` or ``.mxl`` file; None when there is none to read."""
    try:
        if ext == ".mxl":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                path = _root_file(z)
                if path is None:
                    return None
                with z.open(path) as f:
                    return _read(f)
        return _read(io.BytesIO(data))
    except _ERRORS:
        return None


def _root_file(z: zipfile.ZipFile) -> str | None:
    """The score a compressed MusicXML file holds: the one its container names, else its first XML."""
    names = z.namelist()
    if "META-INF/container.xml" in names and z.getinfo("META-INF/container.xml").file_size <= _MAX_CONTAINER:
        for el in ET.fromstring(z.read("META-INF/container.xml")).iter():
            if _local(el.tag) == "rootfile" and el.get("full-path") in names:
                return el.get("full-path")
    return next((n for n in names if n.lower().endswith((".musicxml", ".xml")) and not n.startswith("META-INF/")),
                None)


def _read(stream: IO[bytes]) -> Header | None:
    parser = ET.XMLPullParser(events=("start", "end"))
    found = _Found()
    read = 0
    while read < MAX_HEADER:
        chunk = stream.read(_CHUNK)
        if not chunk:
            parser.close()  # a file that ends without a part list must at least be whole
            found.take(parser)
            break
        read += len(chunk)
        parser.feed(chunk)  # an error waits in the events, after those parsed before it
        if found.take(parser):
            break
    else:
        return None
    title = found.work_title or found.movement_title
    return Header(title, tuple(found.creators)) if title else None


class _Found:
    def __init__(self) -> None:
        self.work_title: str | None = None
        self.movement_title: str | None = None
        self.creators: list[str] = []
        self.done = False

    def take(self, parser: ET.XMLPullParser) -> bool:
        """Read the events parsed so far; True once the header has ended. A parse error raises,
        unless it comes after the header: what follows the header doesn't matter."""
        try:
            for event, el in parser.read_events():
                if self.done:
                    continue
                tag = _local(el.tag)
                if event == "start":
                    self.done = tag in _STOP
                    continue
                text = " ".join((el.text or "").split())
                if not text:
                    continue
                if tag == "work-title" and self.work_title is None:
                    self.work_title = text
                elif tag == "movement-title" and self.movement_title is None:
                    self.movement_title = text
                elif tag == "creator":
                    self.creators.append(text)
        except ET.ParseError:
            if not self.done:
                raise
        return self.done


def _local(tag: str) -> str:
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""
