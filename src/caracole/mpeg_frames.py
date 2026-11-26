"""An MP3's length counted from its frames, for one whose first frame names no length.

An MPEG audio file says how long it is only in a header of its first frame, Xing's (or its Info for CBR, LAME's) with
a count of frames, or Fraunhofer's VBRI. A file with neither (a recorder that streams its frames as it encodes them
and never goes back to write one) leaves every reader to guess: mutagen and libsndfile (mpg123's estimate) take the
file's size over its first frame's bitrate, exact for a CBR file and far off for a VBR one whose first frame is louder
or quieter than the rest, and libsndfile's reads then stop at that guess, with no error. FFmpeg decodes every frame.

``count`` walks the frames: ID3v2 tags skipped at the start (stacked ones too), an ID3v1 tag and an APE tag left out at
the end; each frame's sync word, version, layer, bitrate, rate and padding read, its size from them, the next frame
there; bytes that are no frame (junk between frames) passed over, a frame found again only where the one after it
follows. Its samples (384, 1152, or 576 for MPEG-2's Layer III) over the stream's rate are the length. A file whose
first frame names its length, or that isn't MPEG audio, gets None: its readers already agree.

music.py ``read_audio`` and audio_store.py ``_read`` take this length in place of mutagen's; autochords/audio.py
``load_mono`` reads a file through FFmpeg where libsndfile's decode disagrees with it; autochords/remeasure.py makes
again once what was made before from such a file. Read through ``mmap``, about 1.6 µs a frame: 30 ms for a
seven-minute recording, 0.3 s for 20 MB of 32 kbps frames.

The standard library alone.
"""

from __future__ import annotations

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
    mono: bool


def _frame(buf: bytes | mmap.mmap, at: int) -> _Frame | None:
    """The frame whose header is at ``at``, or None for bytes that are no MPEG audio frame's header (free format,
    whose size no header gives, among them)."""
    if at + 4 > len(buf) or buf[at] != 0xFF or buf[at + 1] & 0xE0 != 0xE0:
        return None
    version, layer = (buf[at + 1] >> 3) & 3, (buf[at + 1] >> 1) & 3
    index, rate_bits, pad = buf[at + 2] >> 4, (buf[at + 2] >> 2) & 3, (buf[at + 2] >> 1) & 1
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
    return _Frame(size, samples, rate, kbps, (version, layer, rate), buf[at + 3] >> 6 == 3)


def _names_its_length(buf: bytes | mmap.mmap, at: int, first: _Frame) -> bool:
    """Whether the first frame, at ``at``, holds a Xing or Info header with a count of frames, or a VBRI header: a
    length every reader takes from it."""
    version = first.stream[0]
    side = (32 if not first.mono else 17) if version == 3 else (17 if not first.mono else 9)
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


def _count(buf: bytes | mmap.mmap) -> Count | None:
    start, end = _audio_bounds(buf)
    at, first = start, None
    while at < min(end, start + FIRST_WITHIN):
        first = _follows(buf, at, end, None)
        if first is not None:
            break
        if at == start and bytes(buf[at:at + 1]) not in (b"\xff", b"\x00"):
            return None  # a file that begins with no tag, no frame and no padding is no MPEG audio
        found = buf.find(b"\xff", at + 1, min(end, start + FIRST_WITHIN))
        if found < 0:
            return None
        at = found
    if first is None or _names_its_length(buf, at, first):
        return None
    guessed = 8 * (len(buf) - at) / (first.kbps * 1000)
    samples = frames = 0
    stream = first.stream
    while at + 4 <= end:
        frame = _frame(buf, at)
        if frame is not None and frame.stream == stream and at + frame.size <= end:
            samples += frame.samples
            frames += 1
            at += frame.size
            continue
        at = _resync(buf, at + 1, end, stream)  # junk: the next frame that is followed by another
        if at < 0:
            break
    return Count(samples / first.rate, guessed, frames)


def _resync(buf: bytes | mmap.mmap, at: int, end: int, stream: tuple[int, int, int]) -> int:
    while True:
        at = buf.find(b"\xff", at, end)
        if at < 0 or _follows(buf, at, end, stream) is not None:
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
