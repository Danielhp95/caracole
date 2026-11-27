"""An MP3's length counted from its frames, for one whose first frame names no length.

An MPEG audio file says how long it is only in a header of its first frame, Xing's (or its Info for CBR, LAME's) with
a count of frames, or Fraunhofer's VBRI. A file with neither (a recorder that streams its frames as it encodes them
and never goes back to write one) leaves every reader to guess: mutagen and libsndfile (mpg123's estimate) take the
file's size over its first frame's bitrate, exact for a CBR file and far off for a VBR one whose first frame is louder
or quieter than the rest, and libsndfile's reads then stop at that guess, with no error. FFmpeg decodes every frame.

``count`` walks the frames: ID3v2 tags skipped at the start (stacked ones too), an ID3v1 tag and an APE tag left out at
the end; each frame's sync word, version, layer, bitrate, rate and padding read, its size from them, the next frame
there; bytes that are no frame (junk between frames, or within ``FIRST_WITHIN`` after the ID3v2 tags) passed over, a
frame found again only where the one after it follows. Each frame's samples (384, 1152, or 576 for MPEG-2's Layer III)
over its own rate, summed, are the length: a stream that changes its rate, version or layer is counted through. A file whose
first frame names its length, or that isn't MPEG audio, gets None: its readers already agree.

music.py ``read_audio`` and audio_store.py ``_read`` take this length in place of mutagen's; autochords/audio.py
``load_mono`` reads a file through FFmpeg where libsndfile's decode disagrees with it; autochords/remeasure.py makes
again once what was made before from such a file. Read through ``mmap``, a frame's header looked up by its two
bytes, about 0.4 µs a frame: 4 ms for a four-minute CBR song, 75 ms for 20 MB of 32 kbps frames; the nightly scan of
Music/ walks a headerless file once, its length then kept until the file changes (music.py ``FRAMES_KEY``).

The standard library alone.
"""

from __future__ import annotations

import functools
import mmap
import os
from dataclasses import dataclass
from pathlib import Path
from typing import IO

# kbps by bitrate index 1-14, for (MPEG-1, layer) and for MPEG-2 and 2.5's layer I, then II and III.
_KBPS = {
    (True, 1): (32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (True, 2): (32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 3): (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (False, 1): (32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (False, 2): (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}  # by version bits
FIRST_WITHIN = 64 * 1024  # bytes after the ID3v2 tags the first frame may begin within (padding, a stray byte)


@dataclass(frozen=True)
class Count:
    """What the frames of a file whose first frame names no length say: ``seconds``, their samples over the rate;
    ``guessed``, the length a reader that doesn't count them takes (mutagen's, and libsndfile's within a frame): the
    bytes from the first frame to the file's end over the first frame's bitrate; ``frames``, how many."""

    seconds: float
    guessed: float
    frames: int


@dataclass(frozen=True)
class _Frame:
    size: int
    samples: int
    rate: int
    kbps: int
    stream: tuple[int, int, int]  # version bits, layer bits, rate: the stream's, which a frame of junk seldom shares


@functools.cache
def _header(b1: int, b2: int) -> _Frame | None:
    """The frame a header's second and third bytes describe (all that a frame's size, samples and rate depend on),
    or None for bytes that are none (free format, whose size no header gives, among them)."""
    if b1 & 0xE0 != 0xE0:
        return None
    version, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
    index, rate_bits, pad = b2 >> 4, (b2 >> 2) & 3, (b2 >> 1) & 1
    if version == 1 or layer == 0 or index in (0, 15) or rate_bits == 3:
        return None
    mpeg1, number = version == 3, 4 - layer  # layer bits 3, 2, 1: Layer I, II, III
    kbps = _KBPS[(mpeg1, number if mpeg1 or number == 1 else 2)][index - 1]
    rate = _RATES[version][rate_bits]
    if number == 1:
        size, samples = (12 * kbps * 1000 // rate + pad) * 4, 384
    elif number == 3 and not mpeg1:
        size, samples = 72 * kbps * 1000 // rate + pad, 576
    else:
        size, samples = 144 * kbps * 1000 // rate + pad, 1152
    return _Frame(size, samples, rate, kbps, (version, layer, rate))


def _frame(buf: bytes | mmap.mmap, at: int) -> _Frame | None:
    """The frame whose header is at ``at``, or None for bytes that are no MPEG audio frame's header."""
    if at + 4 > len(buf) or buf[at] != 0xFF:
        return None
    return _header(buf[at + 1], buf[at + 2])


def _names_its_length(buf: bytes | mmap.mmap, at: int, first: _Frame) -> bool:
    """Whether the first frame, at ``at``, holds a Xing or Info header with a count of frames, or a VBRI header: a
    length every reader takes from it."""
    mono = buf[at + 3] >> 6 == 3
    side = (17 if mono else 32) if first.stream[0] == 3 else (9 if mono else 17)
    xing = at + 4 + side
    if bytes(buf[xing:xing + 4]) in (b"Xing", b"Info"):
        return bool(int.from_bytes(buf[xing + 4:xing + 8], "big") & 1)
    return bytes(buf[at + 36:at + 40]) == b"VBRI"


def _audio_bounds(buf: bytes | mmap.mmap) -> tuple[int, int]:
    """Where the frames begin (after any ID3v2 tags) and end (before an ID3v1 tag and an APE tag)."""
    start = 0
    while bytes(buf[start:start + 3]) == b"ID3" and start + 10 <= len(buf):
        size = (buf[start + 6] << 21) | (buf[start + 7] << 14) | (buf[start + 8] << 7) | buf[start + 9]
        start += 10 + size + (10 if buf[start + 5] & 0x10 else 0)  # a footer, when its flag says so
    end = len(buf)
    if end - 128 >= start and bytes(buf[end - 128:end - 125]) == b"TAG":
        end -= 128
    if end - 32 >= start and bytes(buf[end - 32:end - 24]) == b"APETAGEX":
        size = int.from_bytes(buf[end - 20:end - 16], "little")  # its items and this footer
        header = 32 if int.from_bytes(buf[end - 12:end - 8], "little") & 0x80000000 else 0
        end = max(start, end - size - header)
    return start, end


def _follows(buf: bytes | mmap.mmap, at: int, end: int, stream: tuple[int, int, int] | None) -> _Frame | None:
    """The frame at ``at`` if it is one of ``stream`` (any, for None) that ends at ``end`` or is followed by another
    of it: so a sync word that junk or a frame's own data happens to hold is no frame."""
    frame = _frame(buf, at)
    if frame is None or (stream is not None and frame.stream != stream) or at + frame.size > end:
        return None
    if at + frame.size == end:
        return frame
    after = _frame(buf, at + frame.size)
    return frame if after is not None and after.stream == frame.stream else None


def _first(buf: bytes | mmap.mmap, start: int, end: int) -> int:
    """Where the first frame is, one another follows (-1 for none): right at ``start`` (zero bytes before it passed
    over) in a file with no ID3v2 tag, which is no MPEG audio else; anywhere within ``FIRST_WITHIN`` bytes after the
    tags in one with them (padding, or junk a tagger left)."""
    bound = min(end, start + FIRST_WITHIN)
    if start == 0:
        at = start
        while at < bound and buf[at] == 0:
            at += 1
        return at if at < bound and _follows(buf, at, end, None) is not None else -1
    at = buf.find(b"\xff", start, bound)
    while at >= 0 and _follows(buf, at, end, None) is None:
        at = buf.find(b"\xff", at + 1, bound)
    return at


def _count(buf: bytes | mmap.mmap) -> Count | None:
    start, end = _audio_bounds(buf)
    at = _first(buf, start, end)
    if at < 0:
        return None
    first = _frame(buf, at)
    if _names_its_length(buf, at, first):
        return None
    guessed = 8 * (len(buf) - at) / (first.kbps * 1000)
    samples: dict[int, int] = {}  # by rate: a stream may change its rate, each frame's samples at its own
    frames = 0
    stream = first.stream
    while at + 4 <= end:
        frame = _frame(buf, at) if buf[at] == 0xFF else None
        if frame is not None and at + frame.size <= end and (
                frame.stream == stream or _follows(buf, at, end, None) is not None):
            stream = frame.stream  # another rate, version or layer: one that another frame of it follows
            samples[frame.rate] = samples.get(frame.rate, 0) + frame.samples
            frames += 1
            at += frame.size
            continue
        at = _resync(buf, at + 1, end)  # junk: the next frame that another follows
        if at < 0:
            break
    return Count(sum(n / rate for rate, n in samples.items()), guessed, frames)


def _resync(buf: bytes | mmap.mmap, at: int, end: int) -> int:
    while True:
        at = buf.find(b"\xff", at, end)
        if at < 0 or _follows(buf, at, end, None) is not None:
            return at
        at += 1


def count(source: Path | str | IO[bytes]) -> Count | None:
    """The frames of an MPEG audio file (a path, or a file open for reading in binary) whose first frame names no
    length; None for one whose first frame does, or that is no MPEG audio. An OSError reading it is the caller's."""
    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            return count(f)
    try:
        fd = source.fileno()
    except (AttributeError, OSError, ValueError):  # io.UnsupportedOperation is both
        fd = None
    if fd is not None:
        if os.fstat(fd).st_size == 0:
            return None
        with mmap.mmap(fd, 0, access=mmap.ACCESS_READ) as buf:
            return _count(buf)
    source.seek(0)
    return _count(source.read())


def counted_length(source: Path | str | IO[bytes]) -> float | None:
    """The length in seconds the frames of an MPEG audio file whose first frame names none say (``count``); None
    for any other file."""
    found = count(source)
    return found.seconds if found is not None else None
