"""Tiny audio files of every format caracole keeps as a song's audio (audio_store.py), made by hand at test time.

``audio(fmt, seconds)`` is a file of the format ``fmt`` names (audio_store's ``FORMATS``: MP3, M4A, FLAC, WAV, Ogg,
AIFF) that mutagen reads as ``seconds`` long, with no encoder and no third-party package: silence, as the format
writes it. ``write(path, fmt, seconds, artist=, title=, album=)`` writes one at ``path`` and tags it through mutagen;
``given(conn, state_dir, song, fmt)`` puts one in the store as the song's own audio, as ``audio_store.keep`` would.

WAV and AIFF are PCM, FLAC its frames of a constant sample, MP3 silent MPEG-1 Layer III frames and Ogg Opus's silent
packets, each a file a decoder plays; M4A is the MP4 container alone (its AAC sample entry, its track's length, an
mdat of nothing), which mutagen reads and no decoder plays: helpers/aac.py makes real AAC where torch is. ``mp4``
makes one of other brands (YouTube's raw ``dash``, FFmpeg's ``isom``…), or an .mp4 whose one track is video.
"""

from __future__ import annotations

import io
import struct
import wave
from pathlib import Path

RATE = 8000  # samples a second of the PCM, FLAC and AIFF files


def audio(fmt: str, seconds: float = 1.0) -> bytes:
    """A file of the format ``fmt`` that mutagen reads as ``seconds`` long."""
    return _MAKERS[fmt](seconds)


def given(conn, state_dir: Path, song, fmt: str = "MP3", seconds: float = 1.0) -> Path:
    """The file ``audio_store.keep`` keeps of ``audio(fmt, seconds)`` for ``song``, put in its place by hand (asking
    the disk for no room) and linked as the song's audio, as keep links it; its path."""
    import hashlib

    from caracole.audio_store import FOLDER, FORMATS
    from caracole.songs import update_song

    data = audio(fmt, seconds)
    path = state_dir / FOLDER / f"{song.id}-{hashlib.sha256(data).hexdigest()[:16]}{FORMATS[fmt]}"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(data)
    update_song(conn, song.id, audio_path=str(path), audio_mtime=path.stat().st_mtime)
    return path


def write(path: Path, fmt: str, seconds: float = 1.0, *, artist: str | None = None, title: str | None = None,
          album: str | None = None) -> Path:
    """``audio(fmt, seconds)`` written at ``path``, tagged with what is given (through mutagen, as a player tags
    it); the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio(fmt, seconds))
    tags = {k: v for k, v in (("artist", artist), ("title", title), ("album", album)) if v}
    if tags:
        _tag(path, fmt, tags)
    return path


def _tag(path: Path, fmt: str, tags: dict[str, str]) -> None:
    import mutagen
    from mutagen.id3 import TALB, TIT2, TPE1

    if fmt in ("WAV", "AIFF"):  # tagged with an ID3 chunk, which has no easy keys
        f = mutagen.File(path)
        if f.tags is None:
            f.add_tags()
        frames = {"artist": TPE1, "title": TIT2, "album": TALB}
        for key, value in tags.items():
            f.tags.add(frames[key](encoding=3, text=value))
    else:
        f = mutagen.File(path, easy=True)
        if f.tags is None:
            f.add_tags()
        for key, value in tags.items():
            f[key] = value
    f.save()


# --- each format ----------------------------------------------------------------------------------------------


def _frames(seconds: float) -> int:
    return round(seconds * RATE)


def _wav(seconds: float) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * _frames(seconds))
    return out.getvalue()


def _extended(rate: int) -> bytes:
    """``rate`` as the 80-bit IEEE extended float AIFF writes a sample rate in."""
    top = rate.bit_length() - 1
    return struct.pack(">HQ", 16383 + top, rate << (63 - top))


def _aiff(seconds: float) -> bytes:
    frames = _frames(seconds)
    comm = b"COMM" + struct.pack(">IhIh", 18, 1, frames, 16) + _extended(RATE)
    ssnd = b"SSND" + struct.pack(">III", 8 + 2 * frames, 0, 0) + b"\x00\x00" * frames
    body = b"AIFF" + comm + ssnd
    return b"FORM" + struct.pack(">I", len(body)) + body


def _crc(data: bytes, poly: int, width: int) -> int:
    """A CRC of ``width`` bits, MSB first, from 0, as FLAC's frames check theirs."""
    top, mask, crc = 1 << (width - 1), (1 << width) - 1, 0
    for byte in data:
        crc ^= byte << (width - 8)
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & mask if crc & top else (crc << 1) & mask
    return crc


def _flac(seconds: float) -> bytes:
    total, block = _frames(seconds), 4096
    info = struct.pack(">HH", block, block) + b"\x00" * 6  # block sizes; frame sizes unknown
    info += ((RATE << 44) | (0 << 41) | (15 << 36) | total).to_bytes(8, "big")  # rate, mono, 16 bits, samples
    info += b"\x00" * 16  # no MD5
    out = b"fLaC" + bytes([0x80]) + len(info).to_bytes(3, "big") + info  # STREAMINFO, the last block
    for number, start in enumerate(range(0, total, block)):
        size = min(block, total - start)
        # Sync, fixed blocks; a 16-bit block size after the header, 8 kHz; mono, 16 bits; the frame's number.
        header = bytes([0xFF, 0xF8, 0x74, 0x08]) + _utf8_number(number) + struct.pack(">H", size - 1)
        header += bytes([_crc(header, 0x07, 8)])
        frame = header + b"\x00" + b"\x00\x00"  # a CONSTANT subframe of the sample 0
        out += frame + struct.pack(">H", _crc(frame, 0x8005, 16))
    return out


def _utf8_number(n: int) -> bytes:
    return chr(n).encode("utf-8")  # FLAC codes a frame's number as UTF-8 does a code point


def _mp3(seconds: float) -> bytes:
    # MPEG-1 Layer III, 128 kb/s, 44.1 kHz, mono, no CRC: 417 bytes and 1152 samples a frame; side info and main
    # data all zero, which a decoder plays as silence.
    header = bytes([0xFF, 0xFB, 0x90, 0xC0])
    frame = header + b"\x00" * (417 - len(header))
    return frame * max(2, round(seconds * 44100 / 1152))


def _ogg_crc(data: bytes) -> int:
    return _crc(data, 0x04C11DB7, 32)


def _ogg_page(packets: list[bytes], *, granule: int, sequence: int, first: bool = False, last: bool = False) -> bytes:
    lacing = b""
    for packet in packets:
        lacing += b"\xff" * (len(packet) // 255) + bytes([len(packet) % 255])
    flags = (0x02 if first else 0) | (0x04 if last else 0)
    page = b"OggS" + struct.pack("<BBqIII", 0, flags, granule, 0x6361726F, sequence, 0)
    page += bytes([len(lacing)]) + lacing + b"".join(packets)
    return page[:22] + struct.pack("<I", _ogg_crc(page)) + page[26:]


def _ogg(seconds: float) -> bytes:
    pre_skip = 312
    head = b"OpusHead" + struct.pack("<BBHIhB", 1, 1, pre_skip, 48000, 0, 0)
    vendor = b"caracole tests"
    tags = b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
    out = _ogg_page([head], granule=0, sequence=0, first=True) + _ogg_page([tags], granule=0, sequence=1)
    silence = bytes([0xF8, 0xFF, 0xFE])  # CELT, fullband, 20 ms, one frame: libopus's own packet of silence
    packets = max(1, round(seconds * 50))
    sequence, done = 2, 0
    while done < packets:
        n = min(100, packets - done)
        done += n
        out += _ogg_page([silence] * n, granule=pre_skip + 960 * done, sequence=sequence, last=done == packets)
        sequence += 1
    return out


def _box(kind: bytes, *parts: bytes) -> bytes:
    body = b"".join(parts)
    return struct.pack(">I", 8 + len(body)) + kind + body


def _full(kind: bytes, *parts: bytes, version: int = 0) -> bytes:
    return _box(kind, bytes([version, 0, 0, 0]), *parts)


def _descriptor(tag: int, body: bytes) -> bytes:
    return bytes([tag, len(body)]) + body


def mp4(seconds: float = 1.0, *, major: bytes = b"M4A ", compatible: tuple[bytes, ...] = (b"M4A ", b"isom", b"mp42"),
        video: bool = False) -> bytes:
    """An MP4 file of the brands given (``audio("M4A")``'s are iTunes'), its one track the AAC ``audio("M4A")`` has,
    or with ``video`` a video track alone (an .mp4 with no sound), whose length is the movie's."""
    scale, duration = 8000, round(seconds * 8000)
    matrix = struct.pack(">9I", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    mvhd = _full(b"mvhd", struct.pack(">IIII", 0, 0, scale, duration), struct.pack(">IH", 0x10000, 0x100),
                 b"\x00" * 10, matrix, b"\x00" * 24, struct.pack(">I", 2))
    tkhd = _box(b"tkhd", bytes([0, 0, 0, 7]), struct.pack(">IIIII", 0, 0, 1, 0, duration), b"\x00" * 8,
                struct.pack(">hhHH", 0, 0, 0x100, 0), matrix, struct.pack(">II", 0, 0))
    mdhd = _full(b"mdhd", struct.pack(">IIIIHH", 0, 0, scale, duration, 0x55C4, 0))  # "und"
    kind, name = (b"vide", b"VideoHandler\x00") if video else (b"soun", b"SoundHandler\x00")
    hdlr = _full(b"hdlr", struct.pack(">I", 0), kind, b"\x00" * 12, name)
    config = _descriptor(0x05, bytes([0x15, 0x88]))  # AAC LC, 8 kHz, mono
    decoder = _descriptor(0x04, bytes([0x40, 0x15]) + b"\x00\x00\x00" + struct.pack(">II", 128000, 128000) + config)
    esds = _full(b"esds", _descriptor(0x03, struct.pack(">HB", 1, 0) + decoder + _descriptor(0x06, b"\x02")))
    mp4a = _box(b"mp4a", b"\x00" * 6, struct.pack(">H", 1), b"\x00" * 8, struct.pack(">HHHHI", 1, 16, 0, 0,
                                                                                         scale << 16), esds)
    entries = _full(b"stsd", struct.pack(">I", 0)) if video else _full(b"stsd", struct.pack(">I", 1), mp4a)
    stbl = _box(b"stbl", entries, _full(b"stts", struct.pack(">I", 0)),
                _full(b"stsc", struct.pack(">I", 0)), _full(b"stsz", struct.pack(">II", 0, 0)),
                _full(b"stco", struct.pack(">I", 0)))
    dinf = _box(b"dinf", _full(b"dref", struct.pack(">I", 1), _box(b"url ", bytes([0, 0, 0, 1]))))
    header = _full(b"vmhd", struct.pack(">HHHH", 0, 0, 0, 0)) if video else _full(b"smhd", struct.pack(">HH", 0, 0))
    minf = _box(b"minf", header, dinf, stbl)
    moov = _box(b"moov", mvhd, _box(b"trak", tkhd, _box(b"mdia", mdhd, hdlr, minf)))
    ftyp = _box(b"ftyp", major, struct.pack(">I", 0), b"".join(compatible))
    return ftyp + moov + _box(b"mdat")


_MAKERS = {"MP3": _mp3, "M4A": mp4, "FLAC": _flac, "WAV": _wav, "Ogg": _ogg, "AIFF": _aiff}
FORMATS = tuple(_MAKERS)
