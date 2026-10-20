import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import pairwise
from typing import ClassVar

import pytest
import requests
import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.exceptions import SpotifyException, SpotifyOauthError

from caracole.config import Config, SpotifyConfig
from caracole.sources import SyncStats
from caracole.spotify import (
    MAX_RETRY_AFTER,
    REQUEST_TIMEOUT,
    SCOPES,
    TOP_TRACKS_KEY,
    UNDATED,
    PlaylistUnavailable,
    SpotifyAuthError,
    SpotifyRateLimited,
    SpotifySetupError,
    SpotifySourceError,
    SpotifyTrack,
    _api_session,
    authorize,
    client_from_config,
    iter_playlist_tracks,
    iter_saved_tracks,
    make_auth,
    sync_spotify,
    token_path,
    top_tracks,
    track_from_item,
)

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
CONN = object()
LEARN = "0LearnPlaylist00000000"
ROAD = "0RoadTripPlaylist00000"
EDITORIAL = "37i9dQZF1DXEditorial01"
assert len(LEARN) == len(ROAD) == len(EDITORIAL) == 22  # Spotify ids are 22 base-62 characters


# --- fakes and builders ---------------------------------------------------------------------


def track(tid, name, *artists, album="An Album", duration_ms=200000, isrc=None):
    return {
        "type": "track",
        "id": tid,
        "uri": f"spotify:track:{tid}",
        "name": name,
        "is_local": False,
        "artists": [
            {"type": "artist", "id": f"artist{i}", "name": a} for i, a in enumerate(artists)
        ],
        "album": {"type": "album", "name": album},
        "duration_ms": duration_ms,
        "external_ids": {"isrc": isrc} if isrc else {},
    }


def saved(t, added_at="2026-10-01T12:00:00Z"):
    """A Liked Songs entry."""
    return {"added_at": added_at, "track": t}


def entry(t, added_at="2026-10-01T12:00:00Z", key="item"):
    """A playlist entry: the track sits under "item" since February 2026, "track" before."""
    return {"added_at": added_at, "added_by": {"id": "me"}, "is_local": False, key: t}


def playlist(pid, name):
    return {
        "type": "playlist",
        "id": pid,
        "name": name,
        "uri": f"spotify:playlist:{pid}",
        "owner": {"id": "me"},
        "collaborative": False,
        "items": {"href": f"https://api.spotify.com/v1/playlists/{pid}/items", "total": 1},
    }


BANMA = track(
    "tBanma", "斑马，斑马", "宋冬野", album="安和桥北", duration_ms=253000, isrc="CNA121400056"
)
SODA = track("tSoda", "De Música Ligera", "Soda Stereo", album="Canción Animal", duration_ms=213000)
CREEP = track("tCreep", "Creep", "Radiohead", album="Pablo Honey", duration_ms=238000)
WONDER = track(
    "tWonder", "Wonderwall", "Oasis", album="(What's the Story) Morning Glory?", duration_ms=258000
)


class FakeSpotify:
    """The spotipy calls caracole makes, answering with paged dicts that next() follows."""

    def __init__(self, *, saved=(), playlists=(), items=None, top=(), page_size=2, fail=None):
        self.saved, self.playlists, self.top = list(saved), list(playlists), list(top)
        self.items = dict(items or {})
        self.page_size = page_size
        self.fail = dict(fail or {})
        self.calls = []
        self._pages = {}

    def _call(self, name):
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def _paged(self, name, entries):
        n = self.page_size
        chunks = [entries[i : i + n] for i in range(0, len(entries), n)] or [[]]
        pages = [
            {
                "href": f"https://api.spotify.com/v1/{name}?offset={i * n}",
                "items": chunk,
                "limit": n,
                "offset": i * n,
                "total": len(entries),
                "previous": None,
                "next": None,
            }
            for i, chunk in enumerate(chunks)
        ]
        for page, following in pairwise(pages):
            page["next"] = following["href"]
            self._pages[following["href"]] = (name, following)
        return pages[0]

    def current_user_saved_tracks(self, limit=20, offset=0, market=None):
        self._call("saved")
        return self._paged("me/tracks", self.saved)

    def current_user_playlists(self, limit=50, offset=0):
        self._call("playlists")
        return self._paged("me/playlists", self.playlists)

    def playlist_items(
        self,
        playlist_id,
        fields=None,
        limit=50,
        offset=0,
        market=None,
        additional_types=("track", "episode"),
    ):
        self._call(f"items:{playlist_id}")
        if playlist_id not in self.items:
            raise SpotifyException(
                404,
                -1,
                f"https://api.spotify.com/v1/playlists/{playlist_id}/items:\n Resource not found",
            )
        found = self.items[playlist_id]
        return (
            found
            if isinstance(found, dict)
            else self._paged(f"playlists/{playlist_id}/items", found)
        )

    def current_user_top_tracks(self, limit=20, offset=0, time_range="medium_term"):
        self._call("top")
        return self._paged("me/top/tracks", self.top[:limit])

    def next(self, result):
        if not result["next"]:
            return None
        name, page = self._pages[result["next"]]
        self._call(f"next:{name}")
        return page


class RecordingUpsert:
    """Records upsert_song calls; a source id seen before is a merge, not a new song."""

    def __init__(self):
        self.calls = []
        self.ids = {}

    def __call__(
        self, conn, *, artists, title, album, duration_ms, isrc, source, source_id, added_at
    ):
        assert conn is CONN
        self.calls.append(
            {
                "artists": list(artists),
                "title": title,
                "album": album,
                "duration_ms": duration_ms,
                "isrc": isrc,
                "source": source,
                "source_id": source_id,
                "added_at": added_at,
            }
        )
        created = source_id not in self.ids
        self.ids.setdefault(source_id, len(self.ids) + 1)
        return self.ids[source_id], created


def sync(sp, cfg):
    up, kv = RecordingUpsert(), {}

    def kv_set(conn, key, value):
        assert conn is CONN
        kv[key] = value

    return sync_spotify(CONN, sp, cfg, NOW, upsert=up, kv_set=kv_set), up, kv


def spotify(**fields):
    return SpotifyConfig(client_id="cid", **fields)


# --- reading tracks -------------------------------------------------------------------------


def test_track_from_item_reads_the_fields_caracole_keeps():
    assert track_from_item(BANMA, "2026-10-17T21:04:05Z") == SpotifyTrack(
        id="tBanma",
        title="斑马，斑马",
        artists=("宋冬野",),
        album="安和桥北",
        duration_ms=253000,
        isrc="CNA121400056",
        added_at="2026-10-17T21:04:05Z",
    )
    duet = track("tDuet", "La Tortura", "Shakira", "Alejandro Sanz")
    assert track_from_item(duet, None).artists == ("Shakira", "Alejandro Sanz")


def test_track_from_item_normalizes_added_at_to_utc():
    assert (
        track_from_item(BANMA, "2026-10-17T23:04:05.123+02:00").added_at == "2026-10-17T21:04:05Z"
    )
    assert track_from_item(BANMA, None).added_at is None
    assert track_from_item(BANMA, "yesterday").added_at is None


def test_local_files_and_episodes_skipped():
    local = {
        **track(None, "Riff Demo", "Me"),
        "is_local": True,
        "uri": "spotify:local:Me:Demos:Riff+Demo:120",
    }
    episode = {
        "type": "episode",
        "id": "ep1",
        "name": "Episode 1",
        "show": {"name": "A Podcast"},
        "duration_ms": 3600000,
    }
    old_style_episode = {**track("ep2", "Episode 2", "A Podcast"), "episode": True, "track": False}
    for item in (None, local, episode, old_style_episode):
        assert track_from_item(item, "2026-10-01T12:00:00Z") is None
    sp = FakeSpotify(
        items={
            LEARN: [
                entry(local),
                {**entry(local), "is_local": True},
                entry(episode),
                entry(old_style_episode),
                entry(None),
                None,
                entry(BANMA),
            ]
        },
        page_size=10,
    )
    assert [t.id for t in iter_playlist_tracks(sp, LEARN)] == ["tBanma"]


def test_saved_tracks_paginate():
    sp = FakeSpotify(
        saved=[saved(track(f"t{i}", f"Song {i}", "Some Artist")) for i in range(5)], page_size=2
    )
    assert [t.id for t in iter_saved_tracks(sp)] == ["t0", "t1", "t2", "t3", "t4"]
    assert sp.calls == ["saved", "next:me/tracks", "next:me/tracks"]


def test_playlist_item_key_and_track_key():
    sp = FakeSpotify(items={LEARN: [entry(SODA, key="item"), entry(CREEP, key="track")]})
    assert [(t.id, t.artists) for t in iter_playlist_tracks(sp, LEARN)] == [
        ("tSoda", ("Soda Stereo",)),
        ("tCreep", ("Radiohead",)),
    ]
    assert "playlists" not in sp.calls  # a bare id needs no lookup


def test_playlist_resolved_by_name_case_insensitive():
    sp = FakeSpotify(
        playlists=[playlist(ROAD, "Road Trip"), playlist(LEARN, "Learn")],
        items={LEARN: [entry(SODA)]},
        page_size=1,
    )
    assert [t.id for t in iter_playlist_tracks(sp, " learn ")] == ["tSoda"]
    assert sp.calls == ["playlists", "next:me/playlists", f"items:{LEARN}"]


def test_playlist_name_with_the_exact_case_wins():
    sp = FakeSpotify(
        playlists=[playlist(ROAD, "learn"), playlist(LEARN, "Learn")],
        items={LEARN: [entry(SODA)], ROAD: [entry(CREEP)]},
    )
    assert [t.id for t in iter_playlist_tracks(sp, "Learn")] == ["tSoda"]
    assert [t.id for t in iter_playlist_tracks(sp, "LEARN")] == ["tCreep"]


@pytest.mark.parametrize(
    "ref",
    [
        f"spotify:playlist:{LEARN}",
        f"spotify:user:alice:playlist:{LEARN}",
        f"https://open.spotify.com/playlist/{LEARN}?si=0123abcd",
        f"https://open.spotify.com/intl-es/playlist/{LEARN}",
        f"open.spotify.com/playlist/{LEARN}",
    ],
)
def test_playlist_by_uri_or_url(ref):
    sp = FakeSpotify(items={LEARN: [entry(SODA)]})
    assert [t.id for t in iter_playlist_tracks(sp, ref)] == ["tSoda"]
    assert sp.calls == [f"items:{LEARN}"]


def test_top_tracks_stop_at_the_limit():
    sp = FakeSpotify(
        top=[track(f"t{i}", f"Song {i}", "Some Artist") for i in range(5)], page_size=2
    )
    assert [t.id for t in top_tracks(sp, limit=3)] == ["t0", "t1", "t2"]
    assert top_tracks(FakeSpotify(), limit=0) == []


def test_network_failure_is_a_source_error():
    sp = FakeSpotify(fail={"saved": requests.Timeout("read timed out")})
    with pytest.raises(SpotifySourceError, match="Liked Songs"):
        list(iter_saved_tracks(sp))


# --- syncing --------------------------------------------------------------------------------


def test_sync_upserts_spotify_tracks_newest_first():
    sp = FakeSpotify(
        saved=[saved(SODA, "2025-05-01T10:00:00Z"), saved(BANMA, "2026-10-17T21:04:05Z")],
        items={LEARN: [entry(CREEP, "2026-06-01T00:00:00Z")]},
    )
    stats, up, _ = sync(sp, spotify(playlists=(LEARN,), suggest_top_tracks=False))
    assert [c["source_id"] for c in up.calls] == ["tBanma", "tCreep", "tSoda"]
    assert up.calls[0] == {
        "artists": ["宋冬野"],
        "title": "斑马，斑马",
        "album": "安和桥北",
        "duration_ms": 253000,
        "isrc": "CNA121400056",
        "source": "spotify",
        "source_id": "tBanma",
        "added_at": "2026-10-17T21:04:05Z",
    }
    assert stats == SyncStats(seen=3, new=3)


def test_liked_and_playlist_dedupe():
    sp = FakeSpotify(
        saved=[saved(BANMA, "2026-01-01T00:00:00Z")],
        items={LEARN: [entry(BANMA, "2026-03-01T00:00:00Z"), entry(BANMA, "2026-02-01T00:00:00Z")]},
    )
    stats, up, _ = sync(sp, spotify(playlists=(LEARN,), suggest_top_tracks=False))
    assert [(c["source_id"], c["added_at"]) for c in up.calls] == [
        ("tBanma", "2026-03-01T00:00:00Z")
    ]
    assert (stats.seen, stats.new) == (1, 1)


def test_the_same_song_under_two_track_ids_reaches_the_repository_with_both():
    single = {
        **BANMA,
        "id": "tBanmaSingle",
        "album": {"type": "album", "name": "斑马，斑马 (单曲)"},
    }
    sp = FakeSpotify(
        saved=[saved(BANMA, "2026-01-01T00:00:00Z")],
        items={LEARN: [entry(single, "2026-03-01T00:00:00Z")]},
    )
    stats, up, _ = sync(sp, spotify(playlists=(LEARN,), suggest_top_tracks=False))
    # Track ids are deduplicated, songs are not: the repository merges both ids into one song.
    assert [c["source_id"] for c in up.calls] == ["tBanmaSingle", "tBanma"]
    assert stats.seen == 2


def test_a_track_without_added_at_counts_as_added_at_the_epoch_and_goes_last():
    sp = FakeSpotify(
        saved=[saved(SODA, "2026-01-01T00:00:00Z")],
        items={
            LEARN: [entry(SODA, None), entry(CREEP, None), entry(BANMA, "2025-05-01T00:00:00Z")]
        },
    )
    _, up, _ = sync(sp, spotify(playlists=(LEARN,), suggest_top_tracks=False))
    assert [(c["source_id"], c["added_at"]) for c in up.calls] == [
        ("tSoda", "2026-01-01T00:00:00Z"),
        ("tBanma", "2025-05-01T00:00:00Z"),
        ("tCreep", UNDATED),
    ]
    assert UNDATED == "1970-01-01T00:00:00Z"


def test_a_track_without_added_at_is_not_restamped_by_later_runs(conn):
    from caracole.songs import list_songs

    sp = FakeSpotify(
        saved=[saved(SODA, "2026-01-01T00:00:00Z")], items={LEARN: [entry(CREEP, None)]}
    )
    cfg = spotify(playlists=(LEARN,), suggest_top_tracks=False)
    for night in (NOW, NOW + timedelta(days=1), NOW + timedelta(days=2)):
        sync_spotify(conn, sp, cfg, night)
    # The undated track keeps its date, so it never jumps ahead of a song added since.
    assert [(s.title, s.added_at) for s in list_songs(conn)] == [
        ("De Música Ligera", "2026-01-01T00:00:00Z"),
        ("Creep", "1970-01-01T00:00:00Z"),
    ]


def test_a_removed_song_stays_out_until_you_add_it_on_spotify_again(conn):
    # caracole remove left a tombstone; your Liked Songs and Learn still list the tracks.
    from caracole.songs import list_removed, list_songs, mark_removed

    cfg = spotify(playlists=(LEARN,), suggest_top_tracks=False)
    sync_spotify(conn, FakeSpotify(saved=[saved(SODA, "2026-01-01T00:00:00Z")],
                                   items={LEARN: [entry(CREEP, "2026-02-01T00:00:00Z")]}), cfg, NOW)
    for song in list_songs(conn):
        mark_removed(conn, song, "2026-10-10T00:00:00Z")
    conn.execute("DELETE FROM songs")

    sp = FakeSpotify(saved=[saved(SODA, "2026-01-01T00:00:00Z")],
                     items={LEARN: [entry(CREEP, "2026-02-01T00:00:00Z"), entry(BANMA, "2026-10-11T00:00:00Z")]})
    stats = sync_spotify(conn, sp, cfg, NOW)
    assert (stats.seen, stats.new, stats.removed) == (1, 1, 2)
    assert [s.title for s in list_songs(conn)] == ["斑马，斑马"]
    # Put on Learn again after the removal, Creep comes back.
    sp.items[LEARN].append(entry(CREEP, "2026-10-12T00:00:00Z"))
    stats = sync_spotify(conn, sp, cfg, NOW)
    assert (stats.seen, stats.new, stats.removed) == (2, 1, 1)
    assert [r.display for r in list_removed(conn)] == ["Soda Stereo - De Música Ligera"]


def test_liked_songs_can_be_left_out():
    sp = FakeSpotify(saved=[saved(SODA)], items={LEARN: [entry(CREEP)]})
    _, up, _ = sync(sp, spotify(liked_songs=False, playlists=(LEARN,), suggest_top_tracks=False))
    assert [c["source_id"] for c in up.calls] == ["tCreep"]
    assert "saved" not in sp.calls


def test_missing_playlist_reported():
    no_items = {
        "href": f"https://api.spotify.com/v1/playlists/{EDITORIAL}/items",
        "limit": 50,
        "next": None,
        "offset": 0,
        "previous": None,
        "total": 50,
    }
    sp = FakeSpotify(
        playlists=[playlist(EDITORIAL, "Editorial Picks"), playlist(LEARN, "Learn")],
        items={EDITORIAL: no_items, LEARN: [entry(SODA)]},
    )
    album_link = f"https://open.spotify.com/album/{LEARN}"
    cfg = spotify(
        liked_songs=False,
        suggest_top_tracks=False,
        playlists=("Editorial Picks", "No Such Playlist", album_link, "Learn"),
    )
    stats, up, _ = sync(sp, cfg)
    assert stats.missing_playlists == ["Editorial Picks", "No Such Playlist", album_link]
    assert [c["source_id"] for c in up.calls] == ["tSoda"]
    assert stats.errors == []


def test_playlists_spotify_refuses_are_missing():
    gone, forbidden, emptied = (
        "0GonePlaylist000000000",
        "0ForbiddenPlaylist0000",
        "0EmptiedPlaylist000000",
    )
    emptied_page = {
        "href": "x",
        "items": [],
        "limit": 50,
        "next": None,
        "offset": 0,
        "previous": None,
        "total": 12,
    }
    sp = FakeSpotify(
        items={forbidden: [], emptied: emptied_page},
        fail={f"items:{forbidden}": SpotifyException(403, -1, "x:\n Forbidden")},
    )
    stats, _, _ = sync(
        sp,
        spotify(liked_songs=False, suggest_top_tracks=False, playlists=(gone, forbidden, emptied)),
    )
    assert stats.missing_playlists == [gone, forbidden, emptied]
    assert stats.errors == []
    assert "playlists" not in sp.calls  # all three were read as ids, not looked up by name


def test_a_refused_playlist_says_why_once():
    sp = FakeSpotify(fail={f"items:{LEARN}": SpotifyException(403, -1, "x:\n Forbidden")})
    with pytest.raises(PlaylistUnavailable) as caught:
        list(iter_playlist_tracks(sp, LEARN))
    assert (
        str(caught.value) == f"Spotify playlist {LEARN!r}: Spotify refused it (HTTP 403: Forbidden)"
    )


def test_top_tracks_stored_as_suggestions_not_songs():
    sp = FakeSpotify(saved=[saved(BANMA)], top=[BANMA, WONDER])
    stats, up, kv = sync(sp, spotify(suggest_top_tracks=True))
    assert [c["source_id"] for c in up.calls] == ["tBanma"]
    assert stats.seen == 1
    suggestions = json.loads(kv[TOP_TRACKS_KEY])
    assert [s["id"] for s in suggestions] == ["tBanma", "tWonder"]
    assert suggestions[1] == {
        "id": "tWonder",
        "title": "Wonderwall",
        "artists": ["Oasis"],
        "album": "(What's the Story) Morning Glory?",
        "duration_ms": 258000,
        "isrc": None,
        "url": "https://open.spotify.com/track/tWonder",
    }


def test_top_tracks_are_not_read_when_not_wanted():
    sp = FakeSpotify(saved=[saved(BANMA)], top=[WONDER])
    _, _, kv = sync(sp, spotify(suggest_top_tracks=False))
    assert "top" not in sp.calls
    assert kv == {}


@pytest.mark.parametrize(
    "error",
    [
        SpotifyException(
            401, -1, "https://api.spotify.com/v1/me/tracks:\n The access token expired"
        ),
        SpotifyOauthError(
            "error: invalid_grant, error_description: Refresh token revoked",
            error="invalid_grant",
            error_description="Refresh token revoked",
        ),
    ],
)
def test_auth_failure_maps_to_spotify_auth_error(error):
    sp = FakeSpotify(fail={"saved": error}, items={LEARN: [entry(SODA)]})
    with pytest.raises(SpotifyAuthError, match="caracole auth spotify"):
        sync(sp, spotify(playlists=(LEARN,)))


def test_auth_failure_in_a_playlist_is_not_swallowed():
    sp = FakeSpotify(
        saved=[saved(SODA)],
        items={LEARN: [entry(CREEP)]},
        fail={f"items:{LEARN}": SpotifyException(401, -1, "x:\n The access token expired")},
    )
    with pytest.raises(SpotifyAuthError):
        sync(sp, spotify(playlists=(LEARN,)))


def test_other_failures_are_reported_and_the_sync_goes_on():
    sp = FakeSpotify(
        saved=[saved(SODA), saved(CREEP), saved(BANMA)],
        page_size=2,
        items={LEARN: [entry(WONDER)]},
        fail={
            "next:me/tracks": SpotifyException(
                502, -1, "https://api.spotify.com/v1/me/tracks:\n Bad gateway"
            ),
            "top": requests.ConnectionError("Connection refused"),
        },
    )
    stats, up, kv = sync(sp, spotify(playlists=(LEARN,), suggest_top_tracks=True))
    # The first page of Liked Songs arrived before the failure, so it still counts.
    assert sorted(c["source_id"] for c in up.calls) == ["tCreep", "tSoda", "tWonder"]
    assert len(stats.errors) == 2
    assert (
        "Liked Songs" in stats.errors[0]
        and "502" in stats.errors[0]
        and "Bad gateway" in stats.errors[0]
    )
    assert "top tracks" in stats.errors[1]
    assert TOP_TRACKS_KEY not in kv  # the previous suggestions stay


def test_accounts_service_outage_is_not_an_auth_error():
    outage = SpotifyOauthError(
        "error: <html>502 Bad Gateway</html>, error_description: None",
        error="<html>502 Bad Gateway</html>",
        error_description=None,
    )
    sp = FakeSpotify(fail={"saved": outage})
    stats, _, _ = sync(sp, spotify(suggest_top_tracks=False))
    assert len(stats.errors) == 1 and "Liked Songs" in stats.errors[0]


def test_malformed_items_are_reported_and_good_tracks_kept():
    no_artists = {"type": "track", "id": "tOdd", "name": "No Artists", "artists": []}
    no_id = {
        "type": "track",
        "track_id": "tRenamed",
        "name": "Creep",
        "artists": [{"name": "Radiohead"}],
    }
    sp = FakeSpotify(
        saved=[saved(SODA), saved(no_artists), saved(no_id), "not an item"], page_size=10
    )
    stats, up, _ = sync(sp, spotify(suggest_top_tracks=False))
    assert [c["source_id"] for c in up.calls] == ["tSoda"]
    assert len(stats.errors) == 1 and "3 items" in stats.errors[0]


def rate_limit(seconds="3600"):
    return SpotifyException(
        429, -1, "https://api.spotify.com/v1/x:\n API rate limit exceeded",
        headers={"Retry-After": seconds},
    )


def test_a_rate_limit_stops_the_sync_and_keeps_what_was_read():
    sp = FakeSpotify(
        saved=[saved(SODA)],
        items={LEARN: [entry(CREEP)], ROAD: [entry(WONDER)]},
        fail={f"items:{LEARN}": rate_limit()},
    )
    stats, up, kv = sync(sp, spotify(playlists=(LEARN, ROAD), suggest_top_tracks=True))
    assert [c["source_id"] for c in up.calls] == ["tSoda"]  # read before Spotify said stop
    assert f"items:{ROAD}" not in sp.calls and "top" not in sp.calls  # nothing more asked
    assert len(stats.errors) == 1 and "HTTP 429" in stats.errors[0]
    assert stats.retry_after_until == "2026-10-18T04:30:00Z"
    assert TOP_TRACKS_KEY not in kv


def test_an_absurd_retry_after_is_waited_out_for_a_week_at_most():
    sp = FakeSpotify(saved=[saved(SODA)], fail={"saved": rate_limit("99999999999999999")})
    stats, _, _ = sync(sp, spotify())
    assert stats.retry_after_until == "2026-10-25T03:30:00Z"


def test_a_rate_limit_without_a_wait_still_stops_the_sync():
    sp = FakeSpotify(saved=[saved(SODA)], items={LEARN: [entry(CREEP)]},
                     fail={"saved": SpotifyException(429, -1, "x:\n Too many requests")})
    stats, up, _ = sync(sp, spotify(playlists=(LEARN,)))
    assert up.calls == [] and sp.calls == ["saved"]
    assert stats.retry_after_until is None and "HTTP 429" in stats.errors[0]


class TooManyRequests(BaseHTTPRequestHandler):
    """A local stand-in for api.spotify.com that answers every request 429 with Retry-After.

    The ``too_many_requests`` fixture gives each test a subclass with ``hits`` of its own.
    """

    retry_after = "3600"
    hits: ClassVar[list[str]]

    def do_GET(self):
        type(self).hits.append(self.path)
        body = b'{"error": {"status": 429, "message": "API rate limit exceeded"}}'
        self.send_response(429)
        self.send_header("Retry-After", type(self).retry_after)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def too_many_requests():
    """An API client with caracole's own session, pointed at TooManyRequests on 127.0.0.1."""
    handler = type("Handler", (TooManyRequests,), {"hits": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    # shutdown() returns at the next poll: every 10 ms, not every 500
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    sp = spotipy.Spotify(
        auth="AT", requests_session=_api_session(), requests_timeout=REQUEST_TIMEOUT
    )
    sp.prefix = f"http://127.0.0.1:{server.server_port}/v1/"
    yield sp, handler
    server.shutdown()
    server.server_close()


def test_a_long_retry_after_is_neither_cut_short_nor_retried(too_many_requests, monkeypatch):
    sp, handler = too_many_requests
    slept = []
    monkeypatch.setattr("urllib3.util.retry.time.sleep", slept.append)
    with pytest.raises(SpotifyRateLimited) as raised:
        list(iter_saved_tracks(sp))
    assert len(handler.hits) == 1 and slept == []  # asked once, and no 30-second wait
    assert raised.value.retry_after == 3600 and raised.value.status == 429


def test_a_short_retry_after_is_waited_out_and_retried(too_many_requests, monkeypatch):
    sp, handler = too_many_requests
    handler.retry_after = "2"
    slept = []
    monkeypatch.setattr("urllib3.util.retry.time.sleep", slept.append)
    with pytest.raises(SpotifyRateLimited) as raised:
        list(iter_saved_tracks(sp))
    assert len(handler.hits) == 4 and slept == [2, 2, 2]  # three retries, then it gives up
    assert raised.value.retry_after == 2


# --- authorization --------------------------------------------------------------------------

AUTHORIZE_URL = (
    "https://accounts.spotify.com/authorize?client_id=cid&response_type=code"
    "&redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback"
)


class FakeAuth:
    """The SpotifyOAuth calls authorize() makes, with an in-memory token cache."""

    redirect_uri = "http://127.0.0.1:8888/callback"

    def __init__(self, *, exchange_error=None, saves=True):
        self.cache_handler = MemoryCacheHandler()
        self.exchanged = []
        self.exchange_error = exchange_error
        self.saves = saves

    def get_authorize_url(self, state=None):
        return AUTHORIZE_URL

    def parse_response_code(self, url):
        _, code = spotipy.SpotifyOAuth.parse_auth_response_url(url)
        return code or url

    def get_access_token(self, code=None, as_dict=True, check_cache=True):
        self.exchanged.append((code, as_dict, check_cache))
        if self.exchange_error:
            raise self.exchange_error
        token = {
            "access_token": "AT",
            "refresh_token": "RT",
            "expires_at": 4102444800,
            "scope": SCOPES,
        }
        if self.saves:
            self.cache_handler.save_token_to_cache(token)
        return token if as_dict else "AT"


def test_authorize_exchanges_pasted_code():
    auth, out, prompts = FakeAuth(), [], []

    def read(prompt):
        prompts.append(prompt)
        return "  http://127.0.0.1:8888/callback?code=AQDcode-123_x  "

    authorize(auth, read=read, write=out.append)
    assert auth.exchanged == [("AQDcode-123_x", False, False)]
    assert auth.cache_handler.get_cached_token()["refresh_token"] == "RT"
    shown = "\n".join(out)
    assert AUTHORIZE_URL in shown and "http://127.0.0.1:8888/callback" in shown
    assert len(prompts) == 1


def test_authorize_accepts_the_bare_code():
    auth = FakeAuth()
    authorize(auth, read=lambda prompt: "AQDcode-123_x", write=lambda text: None)
    assert auth.exchanged == [("AQDcode-123_x", False, False)]


@pytest.mark.parametrize(
    "pasted",
    [
        "",
        "http://127.0.0.1:8888/callback?error=access_denied",
        "http://127.0.0.1:8888/callback",
        "I clicked Agree",
    ],
)
def test_authorize_refuses_a_paste_without_a_code(pasted):
    auth = FakeAuth()
    with pytest.raises(SpotifyAuthError, match="caracole auth spotify"):
        authorize(auth, read=lambda prompt: pasted, write=lambda text: None)
    assert auth.exchanged == []


def test_authorize_reports_a_code_spotify_rejects():
    rejected = SpotifyOauthError(
        "error: invalid_grant, error_description: Invalid authorization code",
        error="invalid_grant",
        error_description="Invalid authorization code",
    )
    with pytest.raises(SpotifyAuthError, match="code"):
        authorize(
            FakeAuth(exchange_error=rejected),
            read=lambda p: "http://127.0.0.1:8888/callback?code=AQD",
            write=lambda text: None,
        )


def test_authorize_fails_when_the_token_is_not_saved():
    with pytest.raises(SpotifyAuthError, match="saved"):
        authorize(
            FakeAuth(saves=False),
            read=lambda p: "http://127.0.0.1:8888/callback?code=AQD",
            write=lambda text: None,
        )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeTokenSession:
    """Stands in for the requests session SpotifyOAuth posts the code exchange with."""

    def __init__(self):
        self.posts = []

    def post(self, url, data=None, headers=None, **kwargs):
        self.posts.append((url, data, kwargs.get("timeout")))
        return FakeResponse(
            {
                "access_token": "AT",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "RT",
                "scope": SCOPES,
            }
        )


def test_authorize_with_spotipy_saves_the_token_in_the_state_dir(tmp_path, monkeypatch):
    auth = make_auth(spotify(client_secret="secret"), tmp_path / "state")
    session = FakeTokenSession()
    monkeypatch.setattr(auth, "_session", session)
    authorize(
        auth, read=lambda p: "http://127.0.0.1:8888/callback?code=AQDcode", write=lambda text: None
    )
    [(url, data, timeout)] = session.posts
    assert url == "https://accounts.spotify.com/api/token"
    assert data["code"] == "AQDcode" and data["redirect_uri"] == "http://127.0.0.1:8888/callback"
    assert timeout == REQUEST_TIMEOUT
    saved_token = json.loads(token_path(tmp_path / "state").read_text())
    assert saved_token["refresh_token"] == "RT"


# --- the client -----------------------------------------------------------------------------


def config(tmp_path, **fields):
    return Config(
        library_dir=tmp_path / "Tabs",
        music_dir=tmp_path / "Music",
        state_dir=tmp_path / "state",
        cache_dir=tmp_path / "cache",
        overrides_file=tmp_path / "Tabs" / "overrides.toml",
        wanted_file=tmp_path / "Tabs" / "wanted.txt",
        spotify=SpotifyConfig(**fields),
    )


def write_token(state_dir, scope=SCOPES):
    state_dir.mkdir(parents=True, exist_ok=True)
    token = {
        "access_token": "AT",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "RT",
        "scope": scope,
        "expires_at": 4102444800,
    }
    token_path(state_dir).write_text(json.dumps(token))


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("tried to reach the network")

    monkeypatch.setattr(requests.Session, "request", refuse)


def test_make_auth_settings(tmp_path):
    auth = make_auth(spotify(client_secret="secret"), tmp_path / "state")
    assert isinstance(auth, spotipy.SpotifyOAuth)
    assert auth.cache_handler.cache_path == str(tmp_path / "state" / "spotify_token.json")
    assert auth.open_browser is False
    assert auth.redirect_uri == "http://127.0.0.1:8888/callback"
    assert set(auth.scope.split()) == set(SCOPES.split())
    assert auth.requests_timeout == REQUEST_TIMEOUT
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback" in auth.get_authorize_url()


def test_make_auth_needs_the_client_secret_from_caracole_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIPY_CLIENT_SECRET", "from-spotipy-env")
    with pytest.raises(SpotifySetupError, match="client secret") as raised:
        make_auth(spotify(), tmp_path / "state")
    # Authorizing can't help until the secret is there, and on NixOS it's a module option.
    assert "caracole auth spotify" not in str(raised.value)
    assert "services.caracole.credentials.spotify_client_secret" in raised.value.problem
    assert isinstance(raised.value, SpotifyAuthError)  # what callers catch still covers it


def test_client_from_config_is_none_without_spotify_or_token(tmp_path):
    assert client_from_config(config(tmp_path)) is None
    assert client_from_config(config(tmp_path, client_id="cid", client_secret="secret")) is None
    write_token(tmp_path / "state")
    assert client_from_config(config(tmp_path)) is None  # Spotify off: the token is ignored


def test_client_from_config_uses_the_saved_token(tmp_path, no_network):
    write_token(tmp_path / "state")
    sp = client_from_config(config(tmp_path, client_id="cid", client_secret="secret"))
    assert isinstance(sp, spotipy.Spotify)
    assert sp.requests_timeout == REQUEST_TIMEOUT
    assert sp.auth_manager.get_access_token(as_dict=False) == "AT"


def test_client_waits_out_only_a_short_retry_after(tmp_path):
    write_token(tmp_path / "state")
    sp = client_from_config(config(tmp_path, client_id="cid", client_secret="secret"))
    retry = sp._session.get_adapter("https://api.spotify.com/v1/me/tracks").max_retries
    assert retry.retry_after_max == MAX_RETRY_AFTER
    assert 429 in retry.status_forcelist and retry.total >= 1


def test_client_never_prompts(tmp_path, monkeypatch, no_network):
    write_token(
        tmp_path / "state", scope="user-library-read"
    )  # a token from before a scope was added
    sp = client_from_config(config(tmp_path, client_id="cid", client_secret="secret"))
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("prompted for input"))
    with pytest.raises(SpotifyAuthError, match="caracole auth spotify"):
        list(iter_saved_tracks(sp))
