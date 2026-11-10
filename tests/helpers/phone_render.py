"""render.py's page path with no PDF, as the phone runs it: the reference the phone's own pages are held to
(tests/test_conformance_viewer_render.py; milestone 5's end-to-end checks and the integration compare with it, never
with the computer's own pages, which link their PDFs)::

    from helpers.phone_render import phone_render

    made = phone_render(conn, cfg, song_ids=[song.id])  # what PhoneRender.render writes for those songs

``phone_render`` runs ``render.render_all`` as it is, overrides.toml read as the phone reads its own (the phone keeps
them in its database), with what makes a PDF turned off (``pdfs_off``):

- ``_render_sheet_pdf`` makes none and runs no chordpro: no sheet.pdf, so every viewer gets ``pdf=None`` and
  ``pdf_traditional=None``, and no PDF's record (kv ``render:<id>``) is written;
- ``_render_traditional`` makes none (nor its record, kv ``render:<id>:trad``);
- ``_remake_exports`` makes none: an export is a PDF.

Then what the phone keeps that the computer doesn't (``_phone_records``), for each song the pass rendered:

- each entry of kv ``render:files:<id>`` names the song unit's digest it was made at (``unit``: peer_sync's
  ``digest_of(song_value(…))``, the phone's ``Units.digestOf("song/<key>")``), by which the phone serves its page
  only while the song is still as it was made of (lane written-pages);
- kv ``render:<id>:phone``: that digest (``unit``) and the phone's build it was made by (``build``: the viewer's assets
  and data hashed, with the app's version; ``BUILD`` here), and, for a song whose sheet's words are Chinese, the
  characters they are written in (``script``: ``page.written_script`` of the sheet ``progressions.record`` reads, its
  human sheet's, else its auto sheet's), which the library page's cards read for its names in either script: the
  phone makes no PDF, so no PDF's record names it as render.chinese_songs reads one;
- info.json as ``library.write_info`` writes it, its ``render`` null: no PDF's record;
- no kv ``render:status``, the to-do page's: the phone has none.

What differs from the computer's own pages by design, then: the PDF (no sheet.pdf, no Traditional PDF, no export, so
no viewer links one, and info.json's ``render`` is null); a songbook's file labels (lane songbook-entries'); and
``page.build_version``, which no sheet's page embeds and the phone never compares.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest import mock

from caracole import render
from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.library import write_info
from caracole.overrides import load_overrides
from caracole.peer_sync import digest_of, song_value
from caracole.songs import Song, get_song, list_songs
from caracole.viewer.page import written_script

BUILD = "corpus-build"  # the phone's build each record names (PhoneRender.build is the app's)
PHONE_KV = ":phone"  # kv render:<song id>:phone, the phone's record of each song it rendered


def unit_id(song: Song) -> str:
    """The song's sync unit, as peer_sync names it."""
    return f"song/{song.key}"


def unit_digest(conn, cfg, song: Song) -> str:
    """The song's unit's digest now, overrides.toml as it is now (peer_sync's ``song_value``)."""
    return digest_of(song_value(conn, get_song(conn, song.id), load_overrides(cfg.overrides_file)))


def _no_pdf(*args: Any, **kwargs: Any) -> render._Done:
    """``_render_sheet_pdf`` on the phone: no PDF made, no chordpro run, no record written."""
    return render._Done("pages")


@contextmanager
def pdfs_off(scripts: dict[int, str | None] | None = None) -> Iterator[None]:
    """render.py with no PDF made (the module's docstring). With ``scripts``, each song's sheet ``progressions.record``
    reads is noted there by its id, ``page.written_script`` of its text, as the phone notes it where it records the
    progressions."""
    note = render._note_progressions

    def noting(conn, song, text, key, key_source=None):
        note(conn, song, text, key, key_source)
        if scripts is not None:
            scripts[song.id] = written_script(text)

    with mock.patch.object(render, "_render_sheet_pdf", _no_pdf), \
            mock.patch.object(render, "_render_traditional", lambda *a, **k: None), \
            mock.patch.object(render, "_remake_exports", lambda *a, **k: None), \
            mock.patch.object(render, "_note_progressions", noting):
        yield


def _no_chordpro(cmd, **kwargs):
    raise AssertionError(f"the phone runs no chordpro: {cmd!r}")


@dataclass(frozen=True)
class PhoneRendered:
    """What a pass came to: the songs it rendered (newest first, as render_all goes), and those it failed (their
    display names, in that order)."""

    songs: list[Song]
    failed: list[str]


def phone_render(conn, cfg, *, song_ids: Collection[int] | None = None, build: str = BUILD) -> PhoneRendered:
    """render.py's page path with no PDF over the library, or the songs of ``song_ids``, as the phone renders them,
    overrides.toml read as it is now (the module's docstring)."""
    scripts: dict[int, str | None] = {}
    overrides = load_overrides(cfg.overrides_file)
    with pdfs_off(scripts):
        render.render_all(conn, cfg, overrides, song_ids=song_ids, runner=_no_chordpro)
    status = kv_get_json(conn, render.STATUS_KEY, default={})
    kv_delete(conn, render.STATUS_KEY)
    listed = list_songs(conn) if song_ids is None else render._songs_of(conn, song_ids)
    songs = [s for s in listed if s.status != "ignored" and s.key not in overrides.ignore]
    for song in songs:
        _phone_records(conn, cfg, get_song(conn, song.id), build, scripts.get(song.id))
    failed = status.get("failed") if isinstance(status, dict) else None
    return PhoneRendered(songs, list(failed) if isinstance(failed, list) else [])


def _phone_records(conn, cfg, song: Song, build: str, script: str | None) -> None:
    """The records the phone keeps of a song it rendered (the module's docstring), and its info.json."""
    digest = unit_digest(conn, cfg, song)
    key = f"{render.FILES_KEY}{song.id}"
    written = kv_get_json(conn, key)
    if isinstance(written, dict) and written:
        kv_set_json(conn, key, {name: {"sha256": entry["sha256"], "size": entry["size"], "unit": digest}
                                for name, entry in written.items()})
    kv_set_json(conn, phone_key(song.id), {"unit": digest, "build": build, **({"script": script} if script else {})})
    write_info(conn, cfg.library_dir, song)


def phone_key(song_id: int) -> str:
    """kv ``render:<song id>:phone``."""
    return f"render:{song_id}{PHONE_KV}"
