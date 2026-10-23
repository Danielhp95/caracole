"""Taking a song out of caracole for good: ``caracole remove`` and the web page's Remove button.

A removal takes, in this order:

1. the song's lines out of wanted.txt (``wanted.remove_wanted``), the rest of the
   file kept byte for byte. A wanted.txt caracole can't read stops it here, before
   anything goes: a line it left there would bring the song back;
2. its record out of the database, with its versions, its kept files' rows, its
   match and lyrics, and what other modules keep in kv under its id or its lines'
   keys, and leaves its tombstone (``songs.mark_removed``), so that nothing brings
   it back until you ask for it again (``songs.upsert_song``);
3. the files caracole wrote out of its folder (``plan_removal`` says which), then
   the folder, and its artist's, once empty;
4. the audio caracole took from YouTube for it (youtube_fetch.py), from caracole's
   cache, where nothing else would ever use it.

The library is synced, so every device lets go of the files too. Files caracole
didn't write stay where they are, and the removal names each: nothing of yours
is deleted, and nothing outside the song's folder. The folders are opened one at
a time from the library down, never through a symbolic link, and every file is
deleted by name in its folder, never through one either. The audio you bought,
in Music/, is never touched: the song lets go of it.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from caracole.config import Config
from caracole.db import kv_delete, kv_get_json, savepoint
from caracole.logs import plural
from caracole.library import song_dir, song_folder, songs_in_folder
from caracole.sheet_versions import tab_of, version_names
from caracole.songs import SHEET_OUTPUTS, Song, delete_song_kv, is_export, mark_removed

_LYRICS = ("lyrics.txt", "lyrics.lrc")
_INFO = "info.json"
# What a write caracole didn't finish leaves beside a file (library.write_atomic, lyrics.py).
_LEFTOVER = re.compile(r"\.(?P<name>.+)\.[0-9a-f]{8}\.tmp")
_LINK = "a symbolic link, which caracole doesn't follow"
# Why an entry of the song's folder stays, by what it is.
_WHY = {"file": "caracole didn't write it", "link": _LINK, "folder": "a folder"}


class RemovalError(Exception):
    """The song couldn't be removed, and nothing of it was."""


@dataclass(frozen=True)
class RemovalPlan:
    """What removing a song would take, and what it would leave.

    ``folder`` is the song's folder, relative to the library. ``delete`` names the
    files caracole wrote there, and ``keep`` the rest, each with why it stays.
    ``folder_problem`` says why nothing in the folder can go (a symbolic link in
    its place). ``elsewhere`` holds kept files the database places in another
    folder, which stay. ``wanted_lines`` are the song's lines in wanted.txt, and
    ``wanted_problem`` why the file can't be read. ``audio`` is the purchase the
    song lets go of, and ``youtube_audio`` the files of audio caracole took from
    YouTube for it, in its cache, which go.
    """

    song: Song
    folder: PurePosixPath
    delete: tuple[str, ...] = ()
    keep: tuple[tuple[str, str], ...] = ()
    folder_problem: str | None = None
    elsewhere: tuple[str, ...] = ()
    wanted_lines: tuple[int, ...] = ()
    wanted_problem: str | None = None
    audio: str | None = None
    versions: int = 0
    youtube_audio: tuple[str, ...] = ()


@dataclass
class RemovalResult:
    """What a removal did: the files deleted, those left, the lines taken out of wanted.txt."""

    deleted: list[str] = field(default_factory=list)
    kept: list[tuple[str, str]] = field(default_factory=list)
    wanted_lines: list[int] = field(default_factory=list)
    folder_gone: bool = False
    errors: list[str] = field(default_factory=list)


def plan_removal(conn: sqlite3.Connection, cfg: Config, song: Song) -> RemovalPlan:
    """What removing the song would take and leave; this reads, and changes nothing."""
    folder = PurePosixPath(song_dir(cfg.library_dir, song).relative_to(cfg.library_dir).as_posix())
    kept_here, elsewhere = _kept_files(conn, song, folder)
    ours = _caracoles(conn, song, kept_here)
    why = dict(_WHY)
    # Two songs whose names make one folder: its info.json, lyrics and PDFs may be the other's.
    other = next((s for s in songs_in_folder(conn, song_folder(song.artist, song.title)) if s.id != song.id), None)
    if other is not None:
        ours = set(kept_here)
        why["file"] = f"the folder is {other.display}'s too"
    delete: list[str] = []
    keep: list[tuple[str, str]] = []
    problem = None
    try:
        for name, kind in _entries(cfg.library_dir, folder):
            if kind == "file" and _is_caracoles(name, ours):
                delete.append(name)
            else:
                keep.append((name, why.get(kind, "not a regular file")))
    except _NoFolder:
        pass
    except _NotFollowed as e:
        problem = str(e)
    lines, wanted_problem = _wanted_lines(cfg, song)
    versions = conn.execute("SELECT COUNT(*) FROM versions WHERE song_id = ?", (song.id,)).fetchone()[0]
    youtube = _youtube_audio(conn, cfg, song)
    bought = song.audio_path if song.audio_path and song.audio_path not in youtube else None
    return RemovalPlan(song, folder, tuple(sorted(delete)), tuple(sorted(keep)), problem, tuple(elsewhere),
                       lines, wanted_problem, bought, versions, youtube)


def remove_song(conn: sqlite3.Connection, cfg: Config, plan: RemovalPlan, *, now: datetime | None = None
                ) -> RemovalResult:
    """Remove the song as ``plan`` says: its wanted.txt lines, its record (leaving its tombstone), its files.

    Make the plan just before, under caracole's lock (``commands._common.exclusive``),
    so that it holds what is there. Raises RemovalError, having removed nothing,
    when wanted.txt can't be read or rewritten. A file that can't be deleted is
    in ``errors``; the rest of the song is gone all the same.
    """
    from caracole.wanted import FIRST_SEEN_KEY, remove_wanted

    song = plan.song
    if plan.wanted_problem:
        raise RemovalError(f"wanted.txt can't be read ({plan.wanted_problem}), so {song.display} would come back "
                           "from it: fix the file, then remove the song. Nothing was removed.")
    result = RemovalResult(kept=list(plan.keep))
    try:
        for key in _wanted_keys(song):
            result.wanted_lines += remove_wanted(cfg.wanted_file, key)
    except OSError as e:
        raise RemovalError(f"wanted.txt can't be rewritten ({e.strerror or e}). Nothing was removed.") from e
    result.wanted_lines.sort()
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with savepoint(conn, "remove_song"):
        mark_removed(conn, song, stamp)
        delete_song_kv(conn, song.id)
        for key in _wanted_keys(song):
            kv_delete(conn, FIRST_SEEN_KEY + key)
        conn.execute("DELETE FROM songs WHERE id = ?", (song.id,))  # its versions and files go with it
    if plan.folder_problem is None:
        _delete_files(cfg.library_dir, plan, result)
    for path in plan.youtube_audio:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:  # the next youtube step's tidy deletes it: no song names it now
            result.errors.append(f"can't delete {path}: {e.strerror or e}")
    return result


def describe(plan: RemovalPlan, cfg: Config) -> tuple[list[str], list[str], list[str]]:
    """What goes, what stays, and what else to know, a line each, as ``caracole remove`` and the web
    page say it; the last line is ``AFTER``."""
    folder = f"{plan.folder}/"
    goes: list[str] = []
    if plan.wanted_lines:
        n = len(plan.wanted_lines)
        numbers = ", ".join(str(n) for n in plan.wanted_lines)
        goes.append(f"its line{'s' if n > 1 else ''} in wanted.txt (line{'s' if n > 1 else ''} {numbers})")
    if plan.delete:
        goes.append(f"{plural(len(plan.delete), 'file')} caracole wrote in {folder}: {', '.join(plan.delete)}")
    if not plan.keep and not plan.folder_problem:
        goes.append(f"the folder {folder}, and its artist's once empty")
    record = "its record in caracole's database: its match, its lyrics"
    goes.append(record + (f" and {plural(plan.versions, 'version')} seen of it" if plan.versions else ""))
    if plan.youtube_audio:
        goes.append("the audio caracole took from YouTube for it, from caracole's cache")
    stays = [f"{folder}{name}: {why}" for name, why in plan.keep]
    if plan.folder_problem:
        stays.append(f"{folder}: {plan.folder_problem}, so nothing in it is deleted")
    stays += [f"{path}: outside the song's folder" for path in plan.elsewhere]
    if plan.audio:
        stays.append(f"{_audio(plan.audio, cfg)}: the audio you bought, which caracole never deletes; "
                     "the song lets go of it")
    return goes, stays, [AFTER]


def brief(plan: RemovalPlan) -> str:
    """What removing the song takes and leaves, in one sentence, as the web page's card says it while it counts
    down to the removal: caracole's files of the song, its record, its wanted.txt lines and the audio caracole
    took from YouTube; what stays in its folder; never Music/. ``describe`` says it whole."""
    goes = []
    if plan.delete:
        goes.append(f"caracole's {plural(len(plan.delete), 'file')} for it")
    goes.append("its record")
    if plan.wanted_lines:
        n = len(plan.wanted_lines)
        goes.append("its wanted.txt line" if n == 1 else f"its {n} wanted.txt lines")
    if plan.youtube_audio:
        goes.append("its audio from YouTube")
    said = "Deletes " + (", ".join(goes[:-1]) + " and " + goes[-1] if len(goes) > 1 else goes[0])
    left = len(plan.keep) + len(plan.elsewhere)
    if plan.folder_problem:
        said += f"; leaves its folder ({plan.folder_problem})"
    elif left:
        said += f"; leaves {plural(left, 'other file')}"
    said += "; never touches Music/."
    if plan.wanted_problem:  # caracole remove stops before anything goes: a line left would bring it back
        return f"wanted.txt can't be read ({plan.wanted_problem}), so nothing goes until it can. {said}"
    return said


AFTER = ("caracole won't bring it back, from wanted.txt or the nightly run, until you ask for it "
         "again: caracole add, the web page's request form, or a line in wanted.txt.")


# --- the folder ---------------------------------------------------------------------------------


class _NoFolder(Exception):
    pass


class _NotFollowed(Exception):
    pass


def _open_folder(library_dir: Path, folder: PurePosixPath) -> list[int]:
    """Descriptors of the library and of each folder down to the song's, none opened through a link."""
    fds = [os.open(library_dir, os.O_RDONLY | os.O_DIRECTORY)]
    try:
        for i, part in enumerate(folder.parts):
            try:
                fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
            except FileNotFoundError:
                raise _NoFolder() from None
            except OSError as e:
                where = "/".join(folder.parts[: i + 1]) + "/"
                kind = _LINK if os.path.islink(library_dir.joinpath(*folder.parts[: i + 1])) else "not a folder"
                raise _NotFollowed(f"{where} is {kind}") from e
    except BaseException:
        for fd in fds:
            os.close(fd)
        raise
    return fds


def _entries(library_dir: Path, folder: PurePosixPath) -> list[tuple[str, str]]:
    """Each name in the song's folder, with what it is: "file", "link", "folder" or "other"."""
    try:
        fds = _open_folder(library_dir, folder)
    except FileNotFoundError:  # no library yet
        raise _NoFolder() from None
    try:
        found = []
        with os.scandir(fds[-1]) as it:
            for entry in it:
                mode = entry.stat(follow_symlinks=False).st_mode
                kind = ("file" if stat.S_ISREG(mode) else "link" if stat.S_ISLNK(mode)
                        else "folder" if stat.S_ISDIR(mode) else "other")
                found.append((entry.name, kind))
        return sorted(found)
    finally:
        for fd in fds:
            os.close(fd)


def _delete_files(library_dir: Path, plan: RemovalPlan, result: RemovalResult) -> None:
    """Delete the plan's files by name in the song's folder, each still a regular file, then the empty folders."""
    try:
        fds = _open_folder(library_dir, plan.folder)
    except (_NoFolder, FileNotFoundError):
        result.folder_gone = True
        return
    except _NotFollowed as e:
        result.errors.append(f"{e}: nothing in it was deleted")
        return
    try:
        here = fds[-1]
        for name in plan.delete:
            try:
                if not stat.S_ISREG(os.stat(name, dir_fd=here, follow_symlinks=False).st_mode):
                    result.kept.append((name, "no longer a regular file"))
                    continue
                os.unlink(name, dir_fd=here)
            except FileNotFoundError:
                continue  # gone already (a synced device deleted it)
            except OSError as e:
                result.errors.append(f"can't delete {plan.folder}/{name}: {e.strerror or e}")
                continue
            result.deleted.append(name)
        # The folders, emptied, go too: the song's, then its artist's, unless they hold something.
        for depth in range(len(fds) - 1, 0, -1):
            try:
                os.rmdir(plan.folder.parts[depth - 1], dir_fd=fds[depth - 1])
            except OSError:
                break
            if depth == len(fds) - 1:
                result.folder_gone = True
    finally:
        for fd in fds:
            os.close(fd)


# --- what caracole wrote ------------------------------------------------------------------------


def _kept_files(conn: sqlite3.Connection, song: Song, folder: PurePosixPath) -> tuple[set[str], list[str]]:
    """The song's kept files in its folder, by name, and those the database places elsewhere, by path."""
    here: set[str] = set()
    elsewhere: list[str] = []
    for (path,) in conn.execute("SELECT path FROM files WHERE song_id = ? ORDER BY path", (song.id,)):
        p = PurePosixPath(path)
        if p.parent == folder:
            here.add(p.name)
        else:
            elsewhere.append(path)
    return here, elsewhere


def _caracoles(conn: sqlite3.Connection, song: Song, kept_here: set[str]) -> set[str]:
    """The names of the files caracole wrote in the song's folder.

    Its kept files; the ChordPro, PDF and page it makes from a kept sheet, or
    that a render record names (``render.py``: the record goes with the outputs);
    the page of a version kept beside the sheet, ``version-<tab>.html``, that render.py
    recorded writing (kv ``render:files:``; a version the fetch let go keeps its page
    until the next render, and one no render wrote is yours); the PDFs it exported in
    other versions (kv ``render:export:``); the lyrics, when LRCLIB's were written;
    info.json. A ``sheet.pdf`` or a ``lyrics.txt`` of yours, in a folder caracole
    made none in, isn't one.
    """
    from caracole.render import EXPORT_KV, FILES_KEY

    ours = set(kept_here) | {_INFO}
    for sheet, outputs in SHEET_OUTPUTS.items():  # its ChordPro, its PDF and its viewer
        if sheet in kept_here:
            ours.update(outputs)
    written = kv_get_json(conn, f"{FILES_KEY}{song.id}")  # a version's page: only one a render wrote
    ours.update(name for name in (written if isinstance(written, dict) else ())
                if (tab := tab_of(name)) is not None and name == version_names(tab)[2])
    for key in (f"render:{song.id}", f"render:{song.id}:auto"):
        record = kv_get_json(conn, key)
        pdf = record.get("pdf") if isinstance(record, dict) else None
        if isinstance(pdf, str):
            stem = pdf.removesuffix(".pdf")
            ours.update((pdf, f"{stem}.cho", f"{stem}.html"))
    exports = kv_get_json(conn, f"{EXPORT_KV}{song.id}")  # render_version's PDFs in other versions
    for entry in exports.values() if isinstance(exports, dict) else ():
        pdf = entry.get("pdf") if isinstance(entry, dict) else None
        if isinstance(pdf, str) and is_export(pdf):
            ours.add(pdf)
    if song.lyrics_status == "found":
        ours.update(_LYRICS)
    return ours


def _is_caracoles(name: str, ours: set[str]) -> bool:
    if name in ours:
        return True
    leftover = _LEFTOVER.fullmatch(name)
    return leftover is not None and leftover.group("name") in ours


# --- wanted.txt --------------------------------------------------------------------------------


def _wanted_keys(song: Song) -> list[str]:
    """The keys of the song's wanted.txt lines: its own, and any line's it took in."""
    return list(dict.fromkeys([song.key, *song.source_ids.get("wanted", [])]))


def _wanted_lines(cfg: Config, song: Song) -> tuple[tuple[int, ...], str | None]:
    """The song's line numbers in wanted.txt, or why the file can't be read."""
    from caracole.library import NotRegularFile
    from caracole.wanted import wanted_lines

    lines: list[int] = []
    try:
        for key in _wanted_keys(song):
            lines += wanted_lines(cfg.wanted_file, key)
    except NotRegularFile as e:
        return (), f"{cfg.wanted_file} is {e.strerror}"
    except OSError as e:
        return (), f"{cfg.wanted_file}: {e.strerror or e}"
    return tuple(sorted(set(lines))), None


def _youtube_audio(conn: sqlite3.Connection, cfg: Config, song: Song) -> tuple[str, ...]:
    """The song's files of audio caracole took from YouTube: what its record and its link name, in
    caracole's own folder for them (``youtube_fetch.audio_dir``), never a file anywhere else."""
    from caracole.youtube_fetch import audio_dir, load_record

    folder = audio_dir(cfg)
    named = (load_record(conn, song.id).audio, song.audio_path)
    return tuple(dict.fromkeys(p for p in named if p and Path(p).parent == folder))


def _audio(path: str, cfg: Config) -> str:
    try:
        return f"Music/{Path(path).relative_to(cfg.music_dir).as_posix()}"
    except ValueError:
        return path
