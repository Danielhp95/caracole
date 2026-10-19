"""Spotify: an optional source of songs, from Liked Songs and the playlists you name.

Spotify is never make-or-break. Without a ``client_id`` it is off, and without a
saved token ``client_from_config`` returns None. Every failure is raised as
``SpotifyAuthError`` (run ``tabarr auth spotify``), its ``SpotifySetupError``
(the client secret is missing, say: authorizing can't help yet) or
``SpotifySourceError``, which the nightly run reports and moves past. Nothing
here prompts, except ``authorize``, which ``tabarr auth spotify`` drives.

Spotify's February 2026 changes for Development Mode apps, as handled here:

- a playlist item carries its track under ``item``; older responses use ``track``;
- a playlist you neither own nor collaborate on comes back without ``items``, so
  it is reported as missing instead of being read as empty;
- ``external_ids`` (the ISRC) is back, and kept when present.

An HTTP 429 that outlasts the session's few retries, or that asks for a wait
longer than MAX_RETRY_AFTER, stops the sync (``SpotifyRateLimited``): Spotify
sends long waits only to an app already over its limits, and asking again is
how it stays there.
"""

from __future__ import annotations

import email.utils
import json
import logging
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, Protocol

import requests
import spotipy
from requests.adapters import HTTPAdapter
from spotipy.cache_handler import CacheFileHandler
from spotipy.exceptions import SpotifyException, SpotifyOauthError
from urllib3.exceptions import MaxRetryError, ResponseError
from urllib3.util.retry import Retry

from tabarr.config import Config, SpotifyConfig
from tabarr.sources import KvSet, SyncStats, Upsert, default_kv_set, default_upsert, utc_stamp

log = logging.getLogger(__name__)

SCOPES = "user-library-read playlist-read-private playlist-read-collaborative user-top-read"
SOURCE = "spotify"
TOP_TRACKS_KEY = "spotify:top_tracks"
# The added_at of a track Spotify gives no date: fixed, so a nightly sync never
# moves the song, and the earliest possible, so the song goes last.
UNDATED = "1970-01-01T00:00:00Z"
TOKEN_FILE = "spotify_token.json"
PAGE_SIZE = 50  # the most Spotify returns per page
REQUEST_TIMEOUT = 20  # seconds, for API and token requests alike
MAX_RETRY_AFTER = 30  # seconds; Spotify's rate limit works over a rolling 30-second window

# OAuth error codes (RFC 6749 §4.1.2.1 and §5.2) that mean the authorization itself is bad.
# Anything else spotipy reports as an OAuth error is a failing accounts service.
_AUTH_ERROR_CODES = frozenset(
    {
        "invalid_request",
        "invalid_client",
        "invalid_grant",
        "unauthorized_client",
        "unsupported_grant_type",
        "invalid_scope",
        "access_denied",
    }
)
_CODE = re.compile(r"[A-Za-z0-9_-]+")
_PLAYLIST_URI = re.compile(r"spotify:(?:user:[^:]+:)?playlist:([0-9A-Za-z]+)")
_PLAYLIST_URL = re.compile(
    r"(?:https?://)?open\.spotify\.com/(?:intl-[\w-]+/)?(?:user/[^/]+/)?"
    r"playlist/([0-9A-Za-z]+)/?(?:[?#].*)?",
    re.IGNORECASE,
)
_PLAYLIST_ID = re.compile(r"[0-9A-Za-z]{22}")


class SpotifyError(Exception):
    """A Spotify failure. Never fatal for a run: the pipeline reports it and goes on."""


class SpotifyAuthError(SpotifyError):
    """Spotify needs authorizing: no usable token, an expired or revoked one, a 401."""

    _message = "Spotify: {problem}. Run `tabarr auth spotify`."

    def __init__(self, problem: str):
        self.problem = problem
        super().__init__(self._message.format(problem=problem))


class SpotifySetupError(SpotifyAuthError):
    """Spotify is set up only in part: no client secret, say. ``tabarr auth spotify`` would
    fail the same way, so the advice is what to set, not to authorize."""

    _message = "Spotify isn't fully set up: {problem}."


class SpotifySourceError(SpotifyError):
    """Any other Spotify or network failure; ``status`` is the HTTP status when there was one."""

    def __init__(self, message: str, *, status: int | None = None):
        self.status = status
        super().__init__(message)


class PlaylistUnavailable(SpotifySourceError):
    """A configured playlist that can't be read: no such name, not yours, or refused."""

    def __init__(self, ref: str, reason: str, *, status: int | None = None):
        self.ref = ref
        self.reason = reason
        super().__init__(f"Spotify playlist {ref!r}: {reason}", status=status)


class SpotifyRateLimited(SpotifySourceError):
    """HTTP 429 that the session didn't retry away: stop asking Spotify.

    ``retry_after`` is the wait Spotify asked for, in seconds, when it gave one.
    """

    def __init__(self, what: str, retry_after: float | None, detail: str = ""):
        self.retry_after = retry_after
        wait = f"; it asked tabarr to wait {retry_after:.0f} s" if retry_after is not None else ""
        super().__init__(f"Spotify {what}: HTTP 429" + (f": {detail}" if detail else "") + wait,
                         status=429)


@dataclass(frozen=True)
class SpotifyTrack:
    """A track as tabarr keeps it; ``added_at`` is ISO 8601 UTC, or None if Spotify gave none."""

    id: str
    title: str
    artists: tuple[str, ...]
    album: str | None
    duration_ms: int | None
    isrc: str | None
    added_at: str | None


class SpotifyAPI(Protocol):
    """The part of ``spotipy.Spotify`` tabarr uses; tests pass a fake."""

    def current_user_saved_tracks(
        self, limit: int = 20, offset: int = 0, market: str | None = None
    ) -> Any: ...

    def current_user_playlists(self, limit: int = 50, offset: int = 0) -> Any: ...

    def playlist_items(
        self,
        playlist_id: str,
        fields: str | None = None,
        limit: int = 50,
        offset: int = 0,
        market: str | None = None,
        additional_types: tuple[str, ...] = ("track", "episode"),
    ) -> Any: ...

    def current_user_top_tracks(
        self, limit: int = 20, offset: int = 0, time_range: str = "medium_term"
    ) -> Any: ...

    def next(self, result: Mapping[str, Any]) -> Any: ...


# --- authorization --------------------------------------------------------------------------


class _NoPromptOAuth(spotipy.SpotifyOAuth):
    """SpotifyOAuth that never asks for input.

    spotipy falls back to an interactive prompt whenever it has no valid saved
    token (none at all, or one missing a scope). In a nightly systemd unit that
    would hang or crash the run, so here the fallback raises SpotifyAuthError.
    """

    def get_auth_response(self, open_browser: bool | None = None) -> NoReturn:
        where = getattr(self.cache_handler, "cache_path", "the token cache")
        raise SpotifyAuthError(f"no usable authorization in {where}")


def token_path(state_dir: Path) -> Path:
    """Where the Spotify token is kept: the state directory, never the library."""
    return Path(state_dir) / TOKEN_FILE


def make_auth(cfg: SpotifyConfig, state_dir: Path) -> spotipy.SpotifyOAuth:
    """The OAuth manager for your Spotify app, keeping its token in ``state_dir``.

    It never opens a browser and never prompts. The client id, secret and
    redirect URI come from tabarr's config only (spotipy's ``SPOTIPY_*``
    variables are not consulted); a missing one raises SpotifySetupError.
    """
    if not cfg.client_id:
        raise SpotifySetupError("no client id: set [spotify] client_id in tabarr.toml")
    if not cfg.client_secret:
        raise SpotifySetupError(
            "the client secret is missing; put it in $CREDENTIALS_DIRECTORY/spotify_client_secret, "
            "a [spotify] client_secret_file or $TABARR_SPOTIFY_CLIENT_SECRET, or on NixOS set "
            "services.tabarr.credentials.spotify_client_secret"
        )
    if not cfg.redirect_uri:
        raise SpotifySetupError("no redirect URI: set [spotify] redirect_uri in tabarr.toml")
    state = Path(state_dir)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    return _NoPromptOAuth(
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        redirect_uri=cfg.redirect_uri,
        scope=SCOPES,
        cache_handler=CacheFileHandler(cache_path=str(token_path(state))),
        open_browser=False,
        requests_timeout=REQUEST_TIMEOUT,
    )


def client_from_config(cfg: Config) -> spotipy.Spotify | None:
    """A Spotify client using the saved token; None when Spotify is off or not authorized yet.

    It never prompts. It raises SpotifySetupError when a token is saved but the
    client secret is missing.
    """
    if not cfg.spotify.enabled or not token_path(cfg.state_dir).is_file():
        return None
    auth = make_auth(cfg.spotify, cfg.state_dir)
    if not auth.cache_handler.get_cached_token():
        return None
    return spotipy.Spotify(
        auth_manager=auth, requests_session=_api_session(), requests_timeout=REQUEST_TIMEOUT
    )


def no_client_error(cfg: Config) -> SpotifyAuthError:
    """Why ``client_from_config`` gave no client although Spotify is configured."""
    try:
        auth = make_auth(cfg.spotify, cfg.state_dir)
    except SpotifyAuthError as e:
        return e
    if not auth.cache_handler.get_cached_token():
        return SpotifyAuthError(
            f"no Spotify authorization is saved yet (no token in {token_path(cfg.state_dir)})"
        )
    return SpotifyAuthError("the Spotify client couldn't be created")


def _retry_after_seconds(value: str | None) -> float | None:
    """A Retry-After header in seconds, uncapped: a number of seconds or an HTTP date."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


class _ShortWaitRetry(Retry):
    """urllib3's Retry, except that a Retry-After over MAX_RETRY_AFTER ends the retries.

    urllib3 would cut such a wait to ``retry_after_max`` and ask again, up to
    ``total`` times. Instead the response goes back as it is, and spotipy raises
    it as an HTTP 429 with Spotify's Retry-After (``raise_on_status`` is off).
    """

    def increment(self, method=None, url=None, response=None, error=None, _pool=None,
                  _stacktrace=None):
        header = response.headers.get("Retry-After") if response is not None else None
        wait = _retry_after_seconds(header)
        if wait is not None and wait > MAX_RETRY_AFTER:
            raise MaxRetryError(_pool, url, ResponseError(f"Retry-After {wait:.0f} s"))
        return super().increment(method, url, response, error, _pool, _stacktrace)


def _api_session() -> requests.Session:
    """A session that retries briefly and never sits out a long Retry-After.

    spotipy's own session honours Retry-After up to urllib3's six-hour cap, which
    could hold the nightly run for hours. Here a wait of up to MAX_RETRY_AFTER
    is waited out, a longer one is not retried at all, and after a few tries
    the request fails with the last response, so the sync can stop asking.
    """
    retry = _ShortWaitRetry(
        total=3,
        connect=3,
        read=False,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        retry_after_max=MAX_RETRY_AFTER,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def authorize(
    auth: spotipy.SpotifyOAuth, *, read: Callable[[str], str], write: Callable[[str], None]
) -> None:
    """Authorize tabarr by hand: show the authorize URL, take the pasted redirect, save the token.

    ``write`` shows text to the user; ``read(prompt)`` returns what they paste:
    the address the browser was sent to, or just its ``code``.
    """
    redirect = getattr(auth, "redirect_uri", "the redirect URI")
    write(
        "\n".join(
            [
                "To let tabarr read your Spotify library:",
                "1. In your app's settings on developer.spotify.com, add this redirect URI:",
                f"   {redirect}",
                "2. Open this address in a browser and allow access:",
                f"   {auth.get_authorize_url()}",
                f"3. Spotify then sends the browser to {redirect}?code=… That page won't load,",
                "   because nothing listens there; that's expected.",
                "4. Copy the whole address from the address bar and paste it below.",
            ]
        )
    )
    pasted = read("Address: ").strip()
    if not pasted:
        raise SpotifyAuthError("nothing was pasted")
    try:
        code = auth.parse_response_code(pasted)
    except SpotifyOauthError as e:
        raise _oauth_failure(e, exchanging=True) from e
    if not code or not _CODE.fullmatch(code):
        raise SpotifyAuthError("what was pasted has no ?code= in it")
    try:
        auth.get_access_token(code, as_dict=False, check_cache=False)
    except SpotifyOauthError as e:
        raise _oauth_failure(e, exchanging=True) from e
    except requests.RequestException as e:
        raise SpotifySourceError(f"Spotify: couldn't reach accounts.spotify.com: {e}") from e
    # spotipy's file cache only logs a warning when it can't write the token.
    where = getattr(auth.cache_handler, "cache_path", None)
    if not auth.cache_handler.get_cached_token():
        raise SpotifyAuthError(f"the token couldn't be saved to {where or 'the token cache'}")
    write(f"Spotify authorized; the token is in {where}." if where else "Spotify authorized.")


def _oauth_failure(
    e: SpotifyOauthError, *, what: str | None = None, exchanging: bool = False
) -> SpotifyError:
    error = e.error if isinstance(e.error, str) else None
    if error not in _AUTH_ERROR_CODES:
        where = f"Spotify {what}" if what else "Spotify"
        return SpotifySourceError(f"{where}: the accounts service failed: {_short(str(e))}")
    if error == "access_denied":
        return SpotifyAuthError("access was refused in the browser (access_denied)")
    if error == "invalid_client":
        return SpotifyAuthError("Spotify rejected the client id or secret (invalid_client)")
    if error == "invalid_grant":
        if exchanging:
            return SpotifyAuthError(
                "Spotify refused the code (invalid_grant); a code works once, for a few minutes"
            )
        return SpotifyAuthError("the saved authorization expired or was revoked (invalid_grant)")
    return SpotifyAuthError(f"authorization failed ({error})")


# --- reading tracks -------------------------------------------------------------------------


def track_from_item(item: Mapping[str, Any] | None, added_at: str | None) -> SpotifyTrack | None:
    """The track in a saved or playlist item, or None for what tabarr skips.

    ``item`` is the object under an item's ``item`` key (``track`` before 2026),
    or an entry of the top tracks. Local files, podcast episodes and null tracks
    are skipped. Raises ValueError for an object that isn't shaped like a track:
    one without an id, a name or an artist (only local files lack an id).
    """
    if item is None:
        return None
    if not isinstance(item, Mapping):
        # ValueError, like every other malformed item, so callers catch one exception type.
        raise ValueError(f"expected a track object, got {type(item).__name__}")  # noqa: TRY004
    if item.get("type", "track") != "track" or item.get("episode") is True or item.get("is_local"):
        return None
    track_id = item.get("id")
    title = _text(item.get("name"))
    artists = tuple(
        name
        for a in item.get("artists") or ()
        if isinstance(a, Mapping) and (name := _text(a.get("name")))
    )
    if not isinstance(track_id, str) or not track_id or not title or not artists:
        raise ValueError(f"track {track_id!r} has no id, name or artists")
    album = item.get("album")
    external_ids = item.get("external_ids")
    isrc = _text(external_ids.get("isrc")) if isinstance(external_ids, Mapping) else None
    duration = item.get("duration_ms")
    return SpotifyTrack(
        id=track_id,
        title=title,
        artists=artists,
        album=_text(album.get("name")) if isinstance(album, Mapping) else None,
        duration_ms=int(duration)
        if isinstance(duration, int | float) and not isinstance(duration, bool) and duration > 0
        else None,
        isrc=isrc.upper() if isrc else None,
        added_at=_utc(added_at),
    )


def iter_saved_tracks(sp: SpotifyAPI) -> Iterator[SpotifyTrack]:
    """Your Liked Songs, newest first as Spotify lists them.

    Raises SpotifySourceError, after yielding every usable track, if some items
    had an unexpected shape.
    """
    what = "Liked Songs"
    yield from _tracks(sp, _call(what, sp.current_user_saved_tracks, limit=PAGE_SIZE), what)


def iter_playlist_tracks(sp: SpotifyAPI, ref: str) -> Iterator[SpotifyTrack]:
    """The tracks of a playlist given by name (case-insensitive, among yours), id, URI or URL.

    Raises PlaylistUnavailable when the playlist can't be read: none of your
    playlists has the name, Spotify refuses it (HTTP 400, 403 or 404), or it
    comes back without items, which is Spotify's answer since February 2026 for
    a playlist you neither own nor collaborate on.
    """
    playlist_id = _playlist_id(sp, ref)
    what = f"playlist {ref!r}"
    try:
        first = _call(what, sp.playlist_items, playlist_id, limit=PAGE_SIZE)
    except SpotifySourceError as e:
        if e.status in (400, 403, 404):
            answer = str(e).removeprefix(f"Spotify {what}: ")  # "HTTP 403: Forbidden"
            raise PlaylistUnavailable(ref, f"Spotify refused it ({answer})", status=e.status) from e
        raise
    if isinstance(first, Mapping):
        items, total = first.get("items"), first.get("total")
        if items is None:
            raise PlaylistUnavailable(
                ref,
                "Spotify sent no items; it only shows the items of "
                "playlists you own or collaborate on",
            )
        if not items and isinstance(total, int) and total > 0:
            raise PlaylistUnavailable(ref, f"Spotify sent none of its {total} items")
    yield from _tracks(sp, first, what)


def top_tracks(
    sp: SpotifyAPI, limit: int = 20, *, time_range: str = "medium_term"
) -> list[SpotifyTrack]:
    """Your most played tracks (over about six months, by default). Suggestions, never songs."""
    if limit <= 0:
        return []
    what = "top tracks"
    first = _call(
        what, sp.current_user_top_tracks, limit=min(limit, PAGE_SIZE), time_range=time_range
    )
    found: list[SpotifyTrack] = []
    for track in _tracks(sp, first, what, wrapped=False, strict=False):
        found.append(track)
        if len(found) >= limit:
            break
    return found


def _playlist_id(sp: SpotifyAPI, ref: str) -> str:
    key = ref.strip()
    for pattern in (_PLAYLIST_URI, _PLAYLIST_URL):
        if m := pattern.fullmatch(key):
            return m.group(1)
    if _PLAYLIST_ID.fullmatch(key):
        return key
    if key.startswith("spotify:") or "spotify.com/" in key.lower():
        raise PlaylistUnavailable(ref, "this link or URI isn't a playlist")
    return _playlist_by_name(sp, ref)


def _playlist_by_name(sp: SpotifyAPI, ref: str) -> str:
    """The id of your playlist with this name: the same case first, then ignoring case."""
    name, folded = ref.strip(), _fold(ref)
    loose: str | None = None
    what = "your playlists"
    for page in _pages(sp, _call(what, sp.current_user_playlists, limit=PAGE_SIZE), what):
        for p in page.get("items") or ():
            if not isinstance(p, Mapping) or not isinstance(p.get("id"), str):
                continue
            if not isinstance(p.get("name"), str):
                continue
            if p["name"].strip() == name:
                return p["id"]
            if loose is None and _fold(p["name"]) == folded:
                loose = p["id"]
    if loose is None:
        raise PlaylistUnavailable(ref, "none of your playlists has this name")
    return loose


def _tracks(
    sp: SpotifyAPI, first: Any, what: str, *, wrapped: bool = True, strict: bool = True
) -> Iterator[SpotifyTrack]:
    """Every usable track in a paged list of items (or of bare tracks, when not ``wrapped``).

    Items of an unexpected shape are skipped; when ``strict``, a SpotifySourceError
    reports them after the last good track, so that errors never pass for misses.
    """
    odd = 0
    for page in _pages(sp, first, what):
        for entry in page.get("items") or ():
            try:
                if wrapped:
                    if entry is None:
                        continue
                    if not isinstance(entry, Mapping):
                        raise ValueError(f"expected an item object, got {type(entry).__name__}")
                    if entry.get("is_local"):
                        continue
                    track = track_from_item(
                        entry.get("item") or entry.get("track"), entry.get("added_at")
                    )
                else:
                    track = track_from_item(entry, None)
            except ValueError as e:
                odd += 1
                log.warning("Spotify %s: skipped an item: %s", what, e)
                continue
            if track is not None:
                yield track
    if odd and strict:
        items = "item" if odd == 1 else "items"
        raise SpotifySourceError(f"Spotify {what}: skipped {odd} {items} in an unexpected shape")


def _pages(sp: SpotifyAPI, first: Any, what: str) -> Iterator[Mapping[str, Any]]:
    page = first
    while page is not None:
        if not isinstance(page, Mapping):
            raise SpotifySourceError(f"Spotify {what}: unexpected response")
        yield page
        page = _call(what, sp.next, page) if page.get("next") else None


def _call(what: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call spotipy, turning its failures into SpotifyAuthError or SpotifySourceError."""
    try:
        return fn(*args, **kwargs)
    except SpotifyOauthError as e:
        raise _oauth_failure(e, what=what) from e
    except SpotifyException as e:
        if e.http_status == 401:
            raise SpotifyAuthError("the access token was refused (HTTP 401)") from e
        detail = _short(str(e.msg).strip().splitlines()[-1] if e.msg else "")
        if e.http_status == 429:
            headers = e.headers or {}
            wait = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
            raise SpotifyRateLimited(what, _retry_after_seconds(wait), detail) from e
        raise SpotifySourceError(
            f"Spotify {what}: HTTP {e.http_status}" + (f": {detail}" if detail else ""),
            status=e.http_status,
        ) from e
    except requests.RequestException as e:
        raise SpotifySourceError(f"Spotify {what}: {type(e).__name__}: {_short(str(e))}") from e


# --- syncing --------------------------------------------------------------------------------


def sync_spotify(
    conn: sqlite3.Connection,
    sp: SpotifyAPI,
    cfg: SpotifyConfig,
    now: datetime,
    *,
    upsert: Upsert | None = None,
    kv_set: KvSet | None = None,
) -> SyncStats:
    """Hand Liked Songs and the configured playlists to the song repository, as source "spotify".

    Liked Songs are read when ``cfg.liked_songs``, then each playlist of
    ``cfg.playlists``. A track found in several of them is upserted once, with
    the newest date it was added, and tracks go newest first. Spotify leaves
    that date empty on some very old playlists; such a track counts as added
    at ``UNDATED``, the Unix epoch, so it goes last and stays put. Stamping it
    with the run's time instead would move it to the front of the queue every
    night, ahead of songs you just added; ``now`` dates no track, only the end
    of a rate limit's wait.

    A playlist that can't be read is listed in ``stats.missing_playlists``. Any
    other failure of one source lands in ``stats.errors`` and the other sources
    still sync, except a rate limit (HTTP 429): nothing more is asked, the
    tracks read so far are kept, and when Spotify said how long to wait,
    ``stats.retry_after_until`` says until when. A SpotifyAuthError is raised:
    nothing can be read without authorization.

    With ``cfg.suggest_top_tracks``, the top tracks are stored as a JSON list under
    ``kv["spotify:top_tracks"]`` for the to-do page. They never become songs.
    """
    upsert = upsert or default_upsert()
    stats = SyncStats()
    newest: dict[str, SpotifyTrack] = {}
    refs: list[str | None] = [None] if cfg.liked_songs else []
    refs += [ref for ref in cfg.playlists if ref.strip()]
    limited: SpotifyRateLimited | None = None

    def stop(e: SpotifyRateLimited) -> None:
        nonlocal limited
        limited = e
        stats.errors.append(str(e))
        if e.retry_after is not None:
            stats.retry_after_until = utc_stamp(now + timedelta(seconds=e.retry_after))

    for ref in refs:
        tracks = iter_saved_tracks(sp) if ref is None else iter_playlist_tracks(sp, ref)
        try:
            for track in tracks:
                kept = newest.get(track.id)
                if kept is None or (track.added_at or "") > (kept.added_at or ""):
                    newest[track.id] = track
        except PlaylistUnavailable as e:
            log.warning("%s", e)
            stats.missing_playlists.append(e.ref)
        except SpotifyRateLimited as e:
            stop(e)
            break
        except SpotifySourceError as e:
            stats.errors.append(str(e))

    for track in sorted(newest.values(), key=lambda t: t.added_at or UNDATED, reverse=True):
        _, created = upsert(
            conn,
            artists=list(track.artists),
            title=track.title,
            album=track.album,
            duration_ms=track.duration_ms,
            isrc=track.isrc,
            source=SOURCE,
            source_id=track.id,
            added_at=track.added_at or UNDATED,
        )
        stats.seen += 1
        stats.new += int(created)

    if cfg.suggest_top_tracks and limited is None:
        try:
            suggestions = [_suggestion(t) for t in top_tracks(sp)]
        except SpotifyRateLimited as e:
            stop(e)
        except SpotifySourceError as e:
            stats.errors.append(str(e))
        else:
            (kv_set or default_kv_set())(
                conn, TOP_TRACKS_KEY, json.dumps(suggestions, ensure_ascii=False)
            )
    return stats


def _suggestion(track: SpotifyTrack) -> dict[str, Any]:
    return {
        "id": track.id,
        "title": track.title,
        "artists": list(track.artists),
        "album": track.album,
        "duration_ms": track.duration_ms,
        "isrc": track.isrc,
        "url": f"https://open.spotify.com/track/{track.id}",
    }


def _text(value: Any) -> str | None:
    """A non-empty stripped string, or None."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _utc(value: Any) -> str | None:
    """Spotify's timestamp as ISO 8601 UTC to the second; None if absent or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return utc_stamp(datetime.fromisoformat(value))
    except ValueError:
        return None


def _fold(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def _short(text: str, width: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"
