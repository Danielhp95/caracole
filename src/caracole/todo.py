"""_todo.md: the whole user interface until a richer one is needed (plan §5).

Every section is a list of things only you can do: confirm a match, download a
Guitar Pro file, buy a track, replace a purchase auto-chords can't read, find an
artist's UG page. Each comes with the links to do it, and the exact
overrides.toml line to paste.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from caracole.config import Config
from caracole.db import kv_get_json
from caracole.health import get_state
from caracole.inbox import GP_EXTENSIONS
from caracole.lacuerda import artist_slug_candidates, looks_spanish
from caracole.library import write_atomic
from caracole.lyrics import song_lyrics
from caracole.match import NO_ALIAS_STEPS, PERFORMER_CATCH_ALLS
from caracole.normalize import clean_title, display_key, has_han, identity_key, slug_key
from caracole.overrides import ARTIST_PAGE_SHAPE, TAB_PAGE_SHAPE, Overrides
from caracole.songs import Song, list_songs
from caracole.ug.fetch import artist_is_known, needs_artist_page, pasted_page_problem, songs_to_fetch
from caracole.ug.index import index_state
from caracole.ug.lookup import song_tabs

PROVIDERS = ("ug", "lrclib", "lacuerda")
GUITAR_KINDS = ("guitar-pro", "power", "tabs")
_MD_SPECIAL = "\\`*_[]<>|"
_KIND_NAMES = {"guitar-pro": "Guitar Pro", "power": "Power Tab", "tabs": "Tab", "chords": "Chords"}
PERFORMER = "catch_all:performer"  # a catch_all candidate under misc-originals or misc-unsigned-bands


def md(s: str) -> str:
    """Escape text for Markdown."""
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in s)


def ug_url(tab_id: int | str) -> str:
    return f"https://tabs.ultimate-guitar.com/tab/{tab_id}"


def search_links(artist: str, title: str) -> dict[str, str]:
    """Links for things caracole won't do itself: buying, Chordify, Songsterr, YouTube, a UG search."""
    q = f"{artist} {clean_title(title)}"
    lesson = f"{q} 吉他教学" if has_han(q) else f"{q} guitar lesson"
    return {
        "bandcamp": f"https://bandcamp.com/search?q={quote(q)}&item_type=t",
        "qobuz": f"https://www.qobuz.com/us-en/search?q={quote(q)}",
        "itunes": f"https://music.apple.com/us/search?term={quote(q)}",
        "chordify": f"https://chordify.net/search/{quote(q)}",
        "songsterr": f"https://www.songsterr.com/?pattern={quote(q)}",
        "youtube": f"https://www.youtube.com/results?search_query={quote(lesson)}",
        "ug_search": f"https://www.ultimate-guitar.com/search.php?search_type=title&value={quote(q)}",
    }


def _link(text: str, url: str) -> str:
    return f"[{md(text)}]({url})"


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _paste(lines: list[str]) -> list[str]:
    return ["", "```toml", *lines, "```", ""]


def _section(title: str, items: list[str], intro: str | None = None, count: int | None = None) -> list[str]:
    n = len(items) if count is None else count
    out = [f"## {title} ({n})" if items else f"## {title}", ""]
    if intro:
        out += [intro, ""]
    return out + items + [""]


# What a review's candidates are, by the step that found them, for the steps that never accept
# (match.REVIEW_ONLY_STEPS); "{artists}" is filled with the catch-all artists among them.
_NEAR_NAMES = {
    "catch_all": "songs UG files under a catch-all artist ({artists}) with the show's name in the title",
    # A catch_all candidate under match.PERFORMER_CATCH_ALLS, which files "performer-title".
    PERFORMER: "songs UG files under {artists} with the performer's name at the start of the title",
    "typo_artist": "songs of artists whose names are a letter or two off this one's",
    "word_title": "the artist's titles that hold this one word for word or that it holds",
    "title_only": "other artists' songs with this title (probably covers)",
}
# The Review section's word on each step of names that aren't quite UG's (match.TOLERANT_STEPS).
_NEAR_NAME_STEPS = {
    "catch_all": "`catch_all`: a song UG files under a catch-all artist such as `misc-musicals`, with the "
                 "show's name in its title.",
    PERFORMER: "`catch_all` under `misc-originals` or `misc-unsigned-bands`: a song UG files with its "
               "performer's name at the start of its title.",
    "typo_artist": "`typo_artist`: a song of an artist whose name is a letter or two off yours.",
    "word_title": "`word_title`: a title of the artist's that holds yours word for word, or that yours holds.",
}


def _kind(cand: dict[str, Any]) -> str | None:
    """A candidate's step, or ``PERFORMER`` for a catch_all one under a performer's catch-all."""
    step = cand.get("step")
    return PERFORMER if step == "catch_all" and cand.get("artist_key") in PERFORMER_CATCH_ALLS else step


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _what_candidates_are(song: Song) -> str:
    """"Only …": what a review's candidates are, when every one comes from a step that never accepts."""
    cands = song.match_candidates or []
    kinds = [k for k in dict.fromkeys(_kind(c) for c in cands) if k in _NEAR_NAMES]

    def artists(kind: str) -> str:
        return ", ".join(f"`{a}`" for a in dict.fromkeys(c.get("artist_key") for c in cands if _kind(c) == kind))
    return "Only " + _and([_NEAR_NAMES[k].format(artists=artists(k)) for k in kinds])


# Candidates likelier the song than a page of its artist's that UG lists only by bare ids: the right
# spelling of a misspelt artist's name, or a catch-all artist's song (a show's, or a performer's).
_LEADS_ELSEWHERE = ("typo_artist", "catch_all")


def _leads_elsewhere(song: Song) -> bool:
    return any(c.get("step") in _LEADS_ELSEWHERE for c in song.match_candidates or [])


def _covers_note(conn: sqlite3.Connection, song: Song, overrides: Overrides, due: set[int]) -> str | None:
    """What to do when no candidate is right, for a review whose candidates all come from steps that
    never accept: other artists' songs of the title (probably covers), and names that aren't quite
    UG's. The index has nothing surer of the song's own artist, and its UG page may (A6)."""
    if song.match_decision != "review" or not needs_artist_page(song):
        return None
    head, artist = _what_candidates_are(song), md(song.artist)
    if song.status == "found":  # a cover's [match] would bring that artist's guitar parts, and no better sheet
        head += ", and the song has a sheet already: nothing is lost by leaving this"
    if not artist_is_known(conn, song, overrides):
        steps = {c.get("step") for c in song.match_candidates or []}
        spelt = f" and {artist} is spelt right" if "typo_artist" in steps else ""
        if _leads_elsewhere(song):  # not under Artists to find while these candidates stand
            return (f"{head}. If none is the song you want{spelt}, dismiss them all (below): UG may list {artist} "
                    "only by bare ids, and the to-do page then lists them under Artists to find.")
        lists = "probably lists" if steps == {"title_only"} else "may list"
        return (f"{head}. If none is the song you want{spelt}, UG {lists} {artist} only by bare ids: find the "
                "artist's page, or one of their tab pages (see Artists to find below), and paste its address "
                "under `[artist_url]`, and caracole looks for the song there.")
    if song.id in due:
        return (f"{head}. caracole looks for it on {artist}'s UG page in the next run: wait for that before "
                "you pick one.")
    return (f"{head}. caracole didn't find it on {artist}'s UG page either. Pick one only if it is the "
            "version you want; if none is, dismiss them all (below): caracole looks at the artist page again "
            "after 30 days.")


def _near_names_intro(songs: list[Song]) -> list[str]:
    """The Review section's word on the candidates of names that aren't quite UG's, for the steps the
    candidates listed come from (none, when no candidate does)."""
    steps = {_kind(c) for s in songs if s.review and s.status != "ignored"
             for c in (s.match_candidates or [])[:5]}
    named = [text for step, text in _NEAR_NAME_STEPS.items() if step in steps]
    if not named:
        return []
    return ["Some candidates come from names that aren't quite UG's, and are never accepted without you:", "",
            *(f"- {text}" for text in named), ""]


def _dismissal(song: Song, refs: list[str], overrides: Overrides) -> list[str]:
    """How to say that no candidate is the song: ``caracole review``, or the song's ``[reject]`` line.

    A song rejected before gets its whole line, the UG songs rejected then included, to put in place
    of the one it has: a second line for the same song would make overrides.toml unreadable.
    """
    before = [f"{a}/{s}" for a, s in sorted(overrides.reject.get(song.key, ()))]
    listed = ", ".join(_toml_str(r) for r in dict.fromkeys([*before, *refs]))
    where = "put this line in place of the song's line under" if before else "add this line under"
    return [f"None of these? Answer `n` in `caracole review`, or {where} `[reject]`: caracole drops these "
            "candidates for good and goes on looking for the song.",
            *_paste([f"{_toml_str(song.display)} = [{listed}]  # under [reject]"])]


def _alias_line(artist: str, akey: str, overrides: Overrides) -> list[str]:
    """The ``[alias]`` line that adds ``akey`` to the artist's UG names, as ``caracole review`` adds it.

    No line when it is one of them already; for an artist with aliases, the whole line, theirs included,
    to put in place of the one it has: a second line for the artist would make overrides.toml unreadable.
    """
    have = overrides.alias.get(slug_key(artist), ())
    if akey in have:
        return []
    if not have:
        return [f"{_toml_str(artist)} = {_toml_str(akey)}  # under [alias]"]
    listed = ", ".join(_toml_str(a) for a in (*have, akey))
    return [f"{_toml_str(artist)} = [{listed}]  # in place of the artist's line under [alias]"]


def _review(conn: sqlite3.Connection, songs: list[Song], overrides: Overrides, due: set[int]) -> list[str]:
    items: list[str] = []
    for s in songs:
        if not s.review or s.status == "ignored":
            continue
        items += [f"### {md(s.display)}", ""]
        note = _covers_note(conn, s, overrides, due)
        if note:
            items += [note, ""]
        refs: list[str] = []
        for cand in (s.match_candidates or [])[:5]:
            akey, skey = cand.get("artist_key"), cand.get("song_key")
            if not akey or not skey:
                continue
            refs.append(f"{akey}/{skey}")
            tabs = song_tabs(conn, akey, skey)
            first: dict[str, str] = {}
            for t in tabs:
                first.setdefault(t.type, t.url)
            links = " · ".join(_link(_KIND_NAMES.get(k, k), url) for k, url in first.items())
            step = cand.get("step") or ""
            items.append(f"- {float(cand.get('score') or 0):.0f} · `{akey}/{skey}` ({step}) · {links}".rstrip(" ·"))
            # No table headers: overrides.toml may hold [match] and [alias] already (`caracole review`
            # writes them), and a table declared twice makes the whole file unreadable.
            lines = [f"{_toml_str(s.display)} = {_toml_str(f'{akey}/{skey}')}  # under [match]"]
            if step not in NO_ALIAS_STEPS and slug_key(s.artist) != akey:
                lines += _alias_line(s.artist, akey, overrides)
            items += _paste(lines)
        if refs:
            items += _dismissal(s, refs, overrides)
        items.append("")
    return items


def _partial_sheets(conn: sqlite3.Connection, cfg: Config, songs_by_id: dict[int, Song]) -> list[str]:
    rows = conn.execute(
        "SELECT f.song_id, f.path, v.coverage, v.url FROM files f JOIN versions v ON v.id = f.version_id "
        "WHERE f.name = 'sheet.txt' AND v.coverage IS NOT NULL AND v.coverage < ? ORDER BY v.coverage",
        (cfg.rank.coverage_threshold,),
    ).fetchall()
    items = []
    for r in rows:
        s = songs_by_id.get(r["song_id"])
        if s is None or s.status == "ignored":
            continue
        items.append(
            f"- **{md(s.display)}**: {r['coverage']:.0%} of the lyrics · {_link('sheet', quote(r['path']))}"
            f" · {_link('source', r['url'])}"
        )
    return items


def _artists_to_find(conn: sqlite3.Connection, songs: list[Song], overrides: Overrides) -> tuple[list[str], int]:
    wanted: dict[str, list[Song]] = {}
    pasted: dict[str, tuple[str, str]] = {}  # artist -> (the tab page under [artist_url], what is wrong with it)
    for s in songs:
        # Not found, or reviewed on its title alone (only covers) or on names that aren't quite UG's, by
        # an artist whose UG page the fetch can't find: the index has no slugged tab of theirs, and no
        # address was pasted or learned (or the tab page pasted leads to none). Not while a misspelling's
        # or a catch-all's candidate is likelier the song than bare ids: dismissed, it gives way.
        if s.status == "ignored" or not needs_artist_page(s) or artist_is_known(conn, s, overrides):
            continue
        if _leads_elsewhere(s):
            continue
        wanted.setdefault(s.artist, []).append(s)
        if (problem := pasted_page_problem(conn, s, overrides)) is not None:
            pasted.setdefault(s.artist, problem)
    items = []
    for artist, group in sorted(wanted.items()):
        n = len(group)
        search = f"https://www.ultimate-guitar.com/search.php?search_type=band&value={quote(artist)}"
        item = f"- **{md(artist)}** ({n} song{'s' if n != 1 else ''}): {_link('search Ultimate Guitar', search)}"
        if artist in pasted:
            url, problem = pasted[artist]
            item += (f" · the page under `[artist_url]` for them, {_link(url, url)}: {md(problem)}. Put the "
                     "artist's page, or another of their tab pages, in its place.")
        items.append(item)
    # An artist whose line overrides.toml has already gets no other: the same key twice in a table
    # makes the file unreadable. Its item says to change that line instead.
    new = [a for a in sorted(wanted) if a not in pasted]
    if new:
        # One block for every artist, with the table's header only when the file has no such table:
        # a table declared twice makes overrides.toml unreadable, and the nightly run stops.
        lines = [f"{_toml_str(a)} = {_toml_str(ARTIST_PAGE_SHAPE)}" for a in new]
        if overrides.artist_url:
            how = ("Then add these lines under the `[artist_url]` table your overrides.toml already has (a second "
                   "`[artist_url]` header would make the file unreadable)")
        else:
            how, lines = "Then paste this block into overrides.toml", ["[artist_url]", *lines]
        items += ["", f"{how}, with each address, as your browser shows it, in place of `{ARTIST_PAGE_SHAPE}`. "
                      "An artist page's ends in the artist's number, as "
                      "`https://www.ultimate-guitar.com/artist/634073` does; for a tab page's "
                      f"(`{TAB_PAGE_SHAPE}`), the next run reads that page once for its artist's page:",
                  *_paste(lines)]
    return items, len(wanted)


def _lacuerda_due(song: Song) -> bool:
    """Whether LaCuerda is still to be asked for a song with no sheet (``lacuerda_fetch``'s rule):
    it looks Spanish, an artist slug can be built from its name, and LaCuerda never answered for it."""
    if song.lacuerda_checked_at is not None:
        return False
    lyrics = song_lyrics(song)
    return looks_spanish(clean_title(song.title), lyrics.plain if lyrics is not None else None) and bool(
        artist_slug_candidates(song.artists[0]))


def songs_to_buy(conn: sqlite3.Connection, songs: list[Song], overrides: Overrides,
                 now: datetime) -> tuple[list[Song], int]:
    """The wanted songs whose next step is buying the track, and how many wait for caracole first.

    A song is for buying once nothing caracole will still do may find it a human
    sheet: its UG match was fetched, or UG doesn't have it; no fetch, artist
    page or LaCuerda check is due for it (those songs are the waiting ones);
    and, for a song not found, the index is complete. Songs not matched yet,
    reviews and songs whose audio you have are neither.
    """
    due = {s.id for s in songs_to_fetch(conn, overrides, now)}
    partial = index_state(conn) == "partial"
    buy, waiting = [], 0
    for s in songs:
        if s.status != "wanted" or s.audio_path or s.key in overrides.ignore:
            continue
        if s.match_decision not in ("accept", "pinned", "not_found"):
            continue
        unfetched = s.match_decision != "not_found" and not s.ug_checked_at
        if s.id in due or unfetched or _lacuerda_due(s):
            waiting += 1
        elif not (partial and s.match_decision == "not_found"):  # see _setup
            buy.append(s)
    return buy, waiting


def _buy_list(songs: list[Song]) -> list[str]:
    items = []
    for s in songs:
        L = search_links(s.artist, s.title)
        items.append(
            f"- **{md(s.display)}** · buy: {_link('Bandcamp', L['bandcamp'])} · {_link('Qobuz', L['qobuz'])}"
            f" · {_link('iTunes', L['itunes'])} · check first: {_link('Chordify', L['chordify'])}"
            f" · {_link('Songsterr', L['songsterr'])} · {_link('YouTube', L['youtube'])}"
        )
    return items


def _code(s: str) -> str:
    """Inline code, or escaped text when ``s`` has a backtick of its own."""
    return md(s) if "`" in s else f"`{s}`"


def _autochords_failures(conn: sqlite3.Connection, cfg: Config) -> tuple[list[str], str]:
    """Purchases auto-chords couldn't read, and what to do about them.

    They come from kv ``autochords:status``, written by ``autochords.run.autochords_pending``.
    A file in the music folder is shown from there, as it is on every synced copy.
    """
    status = kv_get_json(conn, "autochords:status", default=None)
    failed = status.get("failed") if isinstance(status, dict) else None
    items = []
    for f in failed if isinstance(failed, list) else []:
        if not isinstance(f, dict) or not all(isinstance(f.get(k), str) for k in ("song", "audio", "error")):
            continue
        audio = Path(f["audio"])
        shown = str(audio.relative_to(cfg.music_dir)) if audio.is_relative_to(cfg.music_dir) else f["audio"]
        items.append(f"- **{md(f['song'])}**: {_code(shown)} · {md(f['error'])}")
    if not items:
        return [], ""
    try:
        last = f" (last run {_fmt(datetime.fromisoformat(str(status['at'])))})"
    except (KeyError, ValueError):
        last = ""
    return items, ("Re-download each file, or convert it (to FLAC, say) and replace the original. "
                   f"Auto-chords tries a changed file again on its next run{last}.")


def _guitar_pro_pages(conn: sqlite3.Connection, songs_by_id: dict[int, Song]) -> tuple[list[str], int]:
    rows = conn.execute(
        "SELECT v.* FROM versions v WHERE v.kind IN ('guitar-pro', 'power') AND v.pick_rank IS NOT NULL "
        "AND v.gone = 0 AND NOT EXISTS (SELECT 1 FROM files f WHERE f.version_id = v.id) "
        "ORDER BY v.song_id, v.pick_rank"
    ).fetchall()
    by_song: dict[int, list[str]] = {}
    for v in rows:
        s = songs_by_id.get(v["song_id"])
        if s is None or s.status == "ignored":
            continue
        label = f" ({v['label']})" if v["label"] else ""
        text = (f"guitar-{v['pick_rank']}: {_KIND_NAMES[v['kind']]} ver {v['version']}{label} · "
                f"{v['rating']:.1f}★ ({v['votes']} votes)")
        by_song.setdefault(v["song_id"], []).append(_link(text, v["url"]))
    lines = [f"- **{md(songs_by_id[sid].display)}**: " + " · ".join(links) for sid, links in by_song.items()]
    return lines, sum(len(links) for links in by_song.values())


def _guitar_parts_not_found(conn: sqlite3.Connection, songs: list[Song]) -> list[str]:
    items = []
    for s in songs:
        if s.status == "ignored" or not s.ug_checked_at:
            continue
        has = conn.execute(
            "SELECT 1 FROM versions WHERE song_id = ? AND slot = 'guitar' AND pick_rank IS NOT NULL LIMIT 1", (s.id,)
        ).fetchone()
        if has:
            continue
        L = search_links(s.artist, s.title)
        items.append(f"- **{md(s.display)}** · {_link('Songsterr', L['songsterr'])} · {_link('YouTube', L['youtube'])}")
    return items


def _inbox(cfg: Config) -> list[str]:
    """What is left in _inbox/. Nothing is followed through a link: a link planted in the library could
    point at caracole's private files, whose names would end up on this page, on every synced device."""
    inbox = cfg.library_dir / "_inbox"
    try:  # the folder itself, never what a link there points at, and listed as opened
        fd = os.open(inbox, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        if not inbox.is_symlink():
            return []
        return ["- `_inbox` is a symbolic link, so this page doesn't list what it points at. Make `_inbox` a "
                "folder of its own."]
    try:
        with os.scandir(fd) as found:
            entries = sorted((e.name, e.is_symlink(), e.is_file(follow_symlinks=False))
                             for e in found if not e.name.startswith("."))
    finally:
        os.close(fd)
    items = []
    for name, link, regular in entries:
        suffix = Path(name).suffix
        if link:
            items.append(f"- {_code(name)}: a symbolic link; caracole files only regular files. Put the file "
                         "itself there.")
        elif not regular:
            continue
        elif suffix.lower() in GP_EXTENSIONS:
            items.append(f"- {_code(name)}: rename it \"Artist - Title (ver N){suffix}\", as Guitar Pro pages "
                         "to click names the song and the version")
        else:
            items.append(f"- {_code(name)}: not a Guitar Pro or Power Tab file ({', '.join(GP_EXTENSIONS)}), "
                         "so caracole leaves it there")
    return items


def _suggestions(conn: sqlite3.Connection, songs: list[Song]) -> list[str]:
    tracks: list[dict[str, Any]] = kv_get_json(conn, "spotify:top_tracks", default=[]) or []
    have = {s.key for s in songs}
    items = []
    for t in tracks:
        artists = t.get("artists") or []
        if not artists or not t.get("title"):
            continue
        if identity_key(artists[0], t["title"]) in have:
            continue
        items.append(f"- {md(display_key(artists[0], t['title']))}")
    return items


def _sources(conn: sqlite3.Connection, cfg: Config) -> list[str]:
    out = ["## Sources", ""]
    sp = kv_get_json(conn, "source:spotify", default=None)
    if not cfg.spotify.enabled:
        out.append("- Spotify: not configured. It's optional; wanted.txt works on its own.")
    elif not sp:
        out.append("- Spotify: not synced yet.")
    elif sp.get("state") == "ok":
        out.append(f"- Spotify: OK, last sync {sp.get('at')} ({sp.get('new', 0)} new)")
    elif sp.get("state") == "auth_needed":
        reason = (sp.get("message") or "").strip().rstrip(".")
        out.append(f"- Spotify: needs authorization{': ' + md(reason) + '.' if reason else '.'} "
                   "Run `caracole auth spotify`.")
    else:
        out.append(f"- Spotify: error at {sp.get('at')}: {sp.get('message')}")
    w = kv_get_json(conn, "source:wanted", default=None)
    if w:
        errors = w.get("errors") or []
        unread = [str(message) for line_no, message in errors if line_no == 0]  # the file, not a line of it
        if unread:
            out.append(f"- wanted.txt: error at {w.get('at')}: {md('; '.join(unread))}")
        else:
            out.append(f"- wanted.txt: {w.get('lines', 0)} songs ({w.get('new', 0)} new at {w.get('at')})")
        for line_no, message in errors:
            if line_no != 0:
                out.append(f"  - line {line_no}: {md(str(message))}")
    elif not cfg.wanted_file.exists():
        out.append("- wanted.txt: not created yet. `caracole add ARTIST TITLE` creates it.")
    return out + [""]


def _render_status(conn: sqlite3.Connection) -> list[str]:
    """The last PDF render, from kv ``render:status`` (written by ``render.render_all``)."""
    status = kv_get_json(conn, "render:status", default=None)
    if not isinstance(status, dict):
        return []
    failed = status.get("failed")
    names = [str(name) for name in failed] if isinstance(failed, list) else []
    n_failed = failed if isinstance(failed, int) and not isinstance(failed, bool) else len(names)
    try:
        when = _fmt(datetime.fromisoformat(str(status.get("at"))))
    except ValueError:
        when = md(str(status.get("at")))
    out = ["## PDFs", "", f"- Last render {when}: {status.get('rendered', 0)} rendered, {n_failed} failed."]
    if status.get("font_error"):
        out.append(f"- Font: {md(str(status['font_error']))}")
    if names:
        out.append(f"- Couldn't render {len(names)} (the run's log says why):")
        out += [f"  - {md(name)}" for name in names]
    return out + [""]


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "never"


def _health(conn: sqlite3.Connection, now: datetime) -> list[str]:
    last = kv_get_json(conn, "run:last", default={}) or {}
    requests = last.get("requests", {})
    out = ["## Provider health", "", "| Provider | Status | Last OK | Last error | Requests last run |",
           "|---|---|---|---|---|"]
    for p in PROVIDERS:
        s = get_state(conn, p)
        if s.cooldown_until and now < s.cooldown_until:
            blocks = f"{s.strikes} block{'s' if s.strikes != 1 else ''}"
            status = f"cooling down until {_fmt(s.cooldown_until)} ({blocks})"
        elif s.last_error_at and (s.last_ok is None or s.last_ok < s.last_error_at):
            status = "errors"  # nothing has worked since the last error
        else:
            status = "OK"
        err = md(s.last_error) if s.last_error else ""
        if s.last_error_at:
            err += f" ({_fmt(s.last_error_at)})"
        out.append(f"| {p} | {status} | {_fmt(s.last_ok)} | {err} | {requests.get(p, '')} |")
    return out + [""]


_NUC_BUILD = "`caracole index build` (on the NUC: `sudo caracole-admin index build`)"


def _wanted_errors(conn: sqlite3.Connection) -> tuple[int, list[str]]:
    """How many wanted.txt lines the last sync couldn't read (listed under Sources), and why it
    couldn't read the file at all, if it couldn't: ``sources.sync_sources`` stores that as line 0."""
    w = kv_get_json(conn, "source:wanted", default=None)
    errors = w.get("errors") if isinstance(w, dict) else None
    if not isinstance(errors, list):
        return 0, []
    unread = [str(message) for line_no, message in errors if line_no == 0]
    return len(errors) - len(unread), unread


def _setup(index: str, overrides_error: str | None, unreadable_lines: int, unread_wanted: list[str]) -> list[str]:
    """What stops caracole from doing its job until you act, for the section at the top."""
    items = []
    if overrides_error:
        items.append(
            "- **overrides.toml can't be read**, so the nightly run stops before its first step: nothing is "
            "synced, matched or fetched until the file is fixed, and this page was built without your "
            f"overrides. {_code(overrides_error)}. Fix the file, then run `caracole run` or wait for the next "
            "night. A table such as `[match]` may appear only once in the file: when the error says one is "
            "declared twice, merge the two into one."
        )
    if index == "empty":
        items.append(
            "- **The Ultimate Guitar index isn't built**, so no song is matched yet, and none is looked for on "
            f"UG. Run {_NUC_BUILD} once: about 42 requests, 10 minutes."
        )
    elif index == "partial":
        items.append(
            "- **The Ultimate Guitar index is incomplete**: a build stopped before it read every sitemap. Until "
            "the rest are read, caracole matches no song and suggests buying none, so nothing UG has is taken for "
            f"missing. The nightly refresh reads them as its budget allows, or run {_NUC_BUILD}."
        )
    if unread_wanted:
        items.append("- **wanted.txt can't be read**, so caracole doesn't see the songs you add to it (those it "
                     f"read before are still looked for): {_code('; '.join(unread_wanted))}.")
    if unreadable_lines:
        lines = f"{unreadable_lines} line{'s' if unreadable_lines != 1 else ''}"
        items.append(f"- **wanted.txt has {lines} caracole couldn't read**, so those songs aren't looked for; "
                     "the other lines still count. Sources, below, says what is wrong with each.")
    return items


def build_todo(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime, *,
               overrides_error: str | None = None) -> str:
    """The whole page. ``overrides_error`` is why overrides.toml couldn't be read; the page then
    leads with it (``overrides`` are empty then)."""
    songs = list_songs(conn)
    index = index_state(conn)
    by_id = {s.id: s for s in songs}
    counts = {st: sum(1 for s in songs if s.status == st) for st in ("found", "wanted", "ignored")}
    n = len(songs)
    out = [
        "# caracole to-do",
        "",
        f"_Updated {_fmt(now)} · {n} song{'s' if n != 1 else ''}: {counts['found']} found, "
        f"{counts['wanted']} wanted, {counts['ignored']} ignored_",
        "",
        "Browse or search every song: [index.html](index.html)",
        "",
    ]
    to_buy, waiting = songs_to_buy(conn, songs, overrides, now)
    if waiting:
        out += [f"{waiting} song{'s' if waiting != 1 else ''} waiting for the nightly fetch.", ""]
    setup = _setup(index, overrides_error, *_wanted_errors(conn))
    if setup:
        out += _section("Setup problems", setup)

    review = _review(conn, songs, overrides, {s.id for s in songs_to_fetch(conn, overrides, now)})
    if review:
        # The count is of songs, not lines, so the header is built here rather than by _section.
        out += [f"## Review ({sum(1 for s in songs if s.review and s.status != 'ignored')})", "",
                "caracole wasn't sure about these matches. Run `caracole review` to settle them one by one, or add "
                "the right candidate's lines (or, when none is right, the `[reject]` line) to overrides.toml "
                "yourself, each under the table its comment names. The file holds each table once: write a "
                "table's header (`[match]`, `[alias]`, `[reject]`) only if the file doesn't have that table yet.",
                "", *_near_names_intro(songs), *review]
    artists, n_artists = _artists_to_find(conn, songs, overrides)
    unread, unread_intro = _autochords_failures(conn, cfg)
    gp_pages, n_pages = _guitar_pro_pages(conn, by_id)
    for title, items, intro, count in (
        ("Partial sheets", _partial_sheets(conn, cfg, by_id),
         f"These sheets cover less than {cfg.rank.coverage_threshold:.0%} of the lyrics. caracole keeps "
         "looking, and a more complete sheet takes a partial one's place when one turns up. To use another "
         "Ultimate Guitar version now, pin its page under `[pin]` in overrides.toml: "
         '`"Artist - Title" = ["https://tabs.ultimate-guitar.com/tab/…"]`.', None),
        ("Artists to find on Ultimate Guitar", artists,
         "UG's sitemaps list these artists only by bare ids (usually because of accents or non-Latin "
         "letters), so caracole can't see their tabs. Find each artist once: search Ultimate Guitar, "
         "open the artist's page, or any of their tab pages, and copy its address.", n_artists),
        ("Buy list", _buy_list(to_buy),
         "No human sheet found yet. Buy the track (DRM-free), drop it into Music/, and caracole will "
         "generate an auto sheet; a human sheet found later takes its place.", None),
        ("Auto-chords couldn't read these purchases", unread, unread_intro, None),
        ("Guitar Pro pages to click", gp_pages,
         "Download each file with the page's Download button and drop it into `_inbox/`; caracole "
         "files it under the right song.", n_pages),
        ("Guitar parts not found", _guitar_parts_not_found(conn, songs), None, None),
        ("Inbox: files caracole couldn't place", _inbox(cfg),
         "caracole files a download by its name, for a version listed under Guitar Pro pages to click: the "
         "next run, or `caracole scan`, makes it the song's guitar-N file. Don't move one into a song's folder "
         "yourself: caracole wouldn't know it is there.", None),
        ("Missing lyrics", [f"- {md(s.display)}" for s in songs
                            if s.lyrics_status == "missing" and s.status != "ignored"],
         "LRCLIB has no lyrics for these yet.", None),
        ("Suggestions from your Spotify top tracks", _suggestions(conn, songs),
         "Add any you want to learn to your Learn playlist or to wanted.txt.", None),
    ):
        if items:
            out += _section(title, items, intro, count)
    out += _render_status(conn)
    out += _sources(conn, cfg)
    out += _health(conn, now)
    return "\n".join(out).rstrip() + "\n"


def write_todo(library_dir: Path, text: str) -> Path:
    path = library_dir / "_todo.md"
    write_atomic(path, text.encode("utf-8"))
    return path


def write_pages(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime) -> tuple[Path, Path]:
    """Rewrite ``_todo.md`` and ``index.html`` from the database (no requests); return their paths.

    Whatever changes what the pages show calls this, so they never point at a stale state.
    """
    from caracole.library_page import build_library_page, write_library_page  # it imports this module

    todo = write_todo(cfg.library_dir, build_todo(conn, cfg, overrides, now))
    return todo, write_library_page(cfg.library_dir, build_library_page(conn, cfg, overrides, now))
