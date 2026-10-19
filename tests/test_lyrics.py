"""LRCLIB lyrics: records, storage, the lookup, the choice of candidate, and files.

Fixtures in ``tests/fixtures/lrclib/`` copy the structure of LRCLIB responses
captured on 2026-10-18, with synthetic lyrics:

- ``get_hit.json``: an ``/api/get`` hit (Soda Stereo's record, with plain and synced lyrics).
- ``search_banma.json``: the three ``/api/search`` records for 宋冬野 – 斑马斑马, with plain
  lyrics only. As in the real records, the title is Simplified and the lyrics Traditional.
- ``search_empty.json``: ``/api/search`` for a miss.
- ``get_instrumental.json``: not captured; the documented shape of an instrumental
  track (``instrumental`` true, both lyric fields null).
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path

import pytest

from caracole.http import (
    BudgetExhausted,
    Client,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    Response,
)
from caracole.lyrics import (
    LRCLIB_API,
    Lyrics,
    LyricsResult,
    fetch_lyrics,
    lyric_lines,
    lyrics_from_json,
    pick_candidate,
    song_lyrics,
    write_lyrics,
)

FIXTURES = Path(__file__).parent / "fixtures" / "lrclib"

# LRCLIB's error bodies. A miss on /api/get currently comes back as the 503 (spike).
NOT_FOUND = (
    404,
    {"code": 404, "name": "TrackNotFound", "message": "Failed to find specified track"},
)
OVERLOADED = (503, {"name": "ServerOverloaded"})


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def record(**fields):
    """A complete LRCLIB record: the get_hit fixture with some fields replaced."""
    return {**load("get_hit.json"), **fields}


def track(title, **fields):
    """A complete LRCLIB record for another title by the same artist."""
    return record(name=title, trackName=title, **fields)


@dataclass(frozen=True)
class Call:
    url: str
    params: dict
    accept: tuple[int, ...]
    cache: bool = True
    max_age: timedelta | None = None


class FakeClient:
    """A ``caracole.http.Client`` that answers each endpoint from a canned reply.

    A reply is ``(status, body)`` or an exception to raise. Like ``PoliteClient``, a
    status the caller did not accept raises ``ProviderError``. Every call is recorded.
    """

    def __init__(self, *, get=None, search=None):
        self.replies = {"/get": get, "/search": search}
        self.calls: list[Call] = []
        self.requests_made = 0

    def get(self, url, *, params=None, cache=True, conditional=False, accept=(200,), max_age=None):
        self.calls.append(Call(url, dict(params or {}), tuple(accept), cache, max_age))
        reply = self.replies.get(url.removeprefix(LRCLIB_API))
        if reply is None:
            raise AssertionError(f"unexpected request: {url}")
        if isinstance(reply, BaseException):
            raise reply
        status, body = reply
        if status not in accept:
            raise ProviderError("lrclib", url, status, "status not accepted")
        self.requests_made += 1
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return Response(url=url, status=status, content=content, headers={}, from_cache=False)

    def endpoints(self) -> list[str]:
        return [call.url.removeprefix(LRCLIB_API) for call in self.calls]


def fetch(
    client,
    *,
    artist="Soda Stereo",
    title="De Música Ligera",
    album="Canción Animal",
    duration_s=213.0,
    **options,
):
    return fetch_lyrics(
        client, artist=artist, title=title, album=album, duration_s=duration_s, **options
    )


# The get_hit song: Soda Stereo – De Música Ligera, 213 s.
pick = partial(pick_candidate, artist="Soda Stereo", title="De Música Ligera")


def test_fake_client_is_a_client():
    assert isinstance(FakeClient(), Client)


# Records


def test_from_record_reads_lrclib_fields():
    raw = load("get_hit.json")
    lyrics = Lyrics.from_record(raw)
    assert lyrics.plain == raw["plainLyrics"]
    assert lyrics.synced == raw["syncedLyrics"]
    assert lyrics.instrumental is False
    assert lyrics.duration == 213.0
    assert lyrics.lrclib_id == 1040023
    assert lyrics.raw == raw


def test_from_record_derives_plain_from_synced():
    raw = record(plainLyrics="")
    assert Lyrics.from_record(raw).plain == (
        "Línea uno de prueba bajo la luz\n"
        "Línea dos de prueba sin canción\n"
        "Línea tres de prueba en la ciudad\n"
        "Línea cuatro de prueba al final\n"
        "\n"
        "Coro de prueba, coro de prueba\n"
        "Coro de prueba, coro de prueba"
    )


def test_from_record_drops_lrc_id_tags_from_plain():
    # Seen live: a record whose plain lyrics still carry the LRC file's ID tags.
    plain = (
        "[ti:Canción de Prueba]\n[ar:Artista de Prueba]\n[by:]\n[offset:0]\n\n"
        "Línea uno\n[Coro: Artista de Prueba]\nLínea dos"
    )
    assert Lyrics.from_record(record(plainLyrics=plain)).plain == (
        "Línea uno\n[Coro: Artista de Prueba]\nLínea dos"
    )


def test_plain_from_synced_orders_repeated_timestamps_and_drops_tags():
    synced = (
        "[ar:Artista de Prueba]\n"
        "[00:10.00][00:30.00] Coro de prueba\n"
        "[00:20.00] Verso <00:20.50>de <00:21.00>prueba"
    )
    assert Lyrics.from_record(record(plainLyrics=None, syncedLyrics=synced)).plain == (
        "Coro de prueba\nVerso de prueba\nCoro de prueba"
    )


def test_plain_from_synced_keeps_one_break_between_stanzas():
    synced = "[00:00.00] \n[00:05.00] Uno\n[00:09.00] \n[00:12.00] \n[00:15.00] Dos\n[00:20.00] "
    assert Lyrics.from_record(record(plainLyrics=None, syncedLyrics=synced)).plain == "Uno\n\nDos"


@pytest.mark.parametrize("synced", ["", "[00:00.00] \n[00:03.00] "])
def test_blank_lyric_fields_mean_no_lyrics(synced):
    lyrics = Lyrics.from_record(record(plainLyrics="  \n", syncedLyrics=synced))
    assert lyrics.plain == ""
    assert lyrics.synced is None
    assert not lyrics.has_lyrics


# Storage in the songs table


def test_lyrics_json_roundtrip():
    from_lrclib = Lyrics.from_record(load("search_banma.json")[2])
    by_hand = Lyrics(
        plain="una línea", synced=None, instrumental=False, duration=None, lrclib_id=None, raw={}
    )
    for lyrics in (from_lrclib, by_hand):
        assert lyrics_from_json(lyrics.to_json()) == lyrics


def test_lyrics_from_json_accepts_every_stored_form():
    raw = load("get_hit.json")
    lyrics = Lyrics.from_record(raw)
    assert lyrics_from_json(None) is None
    assert lyrics_from_json(json.loads(lyrics.to_json())) == lyrics  # a decoded JSON column
    assert lyrics_from_json(json.dumps(raw)) == lyrics  # the bare LRCLIB record


def test_song_lyrics_reads_a_decoded_lyrics_json_column():
    @dataclass
    class Song:
        lyrics_json: object

    stored = Lyrics.from_record(load("get_hit.json"))
    assert song_lyrics(Song(lyrics_json=json.loads(stored.to_json()))) == stored
    assert song_lyrics(Song(lyrics_json=None)) is None


# Lines for lyric coverage


def test_lyric_lines_dedupes_chorus():
    plain = "Línea uno\nCoro de prueba\n\nLínea dos\nCoro de prueba\ncoro, de PRUEBA!"
    assert lyric_lines(plain) == ["linea uno", "coro de prueba", "linea dos"]


def test_lyric_lines_skip_section_headers():
    assert lyric_lines("[Coro]\nCoro de prueba\n[Verse 2]\nVerso dos") == [
        "coro de prueba",
        "verso dos",
    ]


def test_lyric_lines_keep_cjk_text():
    assert lyric_lines(load("search_banma.json")[0]["plainLyrics"]) == [
        "範例歌詞 第一行 這是測試用的句子",
        "範例歌詞 第二行 沒有真正的歌詞",
        "範例歌詞 第三行 只用來檢查格式",
        "範例歌詞 第四行 結束",
    ]


def test_lyric_lines_use_the_given_normalizer():
    assert lyric_lines("Uno\ndos\nUNO", normalize=str.upper) == ["UNO", "DOS"]


# The lookup: /api/get


def test_get_hit_writes_txt_and_lrc(tmp_path):
    hit = load("get_hit.json")
    client = FakeClient(get=(200, hit))
    result = fetch(client)
    assert result.status == "found"
    assert result.lyrics.lrclib_id == 1040023
    assert client.endpoints() == ["/get"]
    song_dir = tmp_path / "Soda Stereo" / "De Música Ligera"
    assert write_lyrics(song_dir, result.lyrics) == [
        song_dir / "lyrics.txt",
        song_dir / "lyrics.lrc",
    ]
    assert (song_dir / "lyrics.txt").read_text(encoding="utf-8") == hit["plainLyrics"] + "\n"
    lrc = (song_dir / "lyrics.lrc").read_text(encoding="utf-8")
    assert lrc.startswith("[00:23.62] Línea uno de prueba bajo la luz\n")


@pytest.mark.parametrize("duration_s,sent", [(213000 / 1000, 213), (212.6, 213), (253.1004, 253)])
def test_duration_sent_as_whole_seconds(duration_s, sent):
    client = FakeClient(get=(200, load("get_hit.json")))
    fetch(client, duration_s=duration_s)
    assert client.calls[0].params["duration"] == sent
    assert type(client.calls[0].params["duration"]) is int


def test_get_sends_clean_title_original_artist_and_album():
    client = FakeClient(get=(200, load("get_hit.json")))
    fetch(client, title="De Música Ligera - Remastered 2007")
    call = client.calls[0]
    assert call.url == "https://lrclib.net/api/get"
    assert call.params == {
        "artist_name": "Soda Stereo",
        "track_name": "De Música Ligera",
        "album_name": "Canción Animal",
        "duration": 213,
    }
    assert set(call.accept) == {200, 404, 503}


def test_unknown_album_and_duration_are_not_sent():
    client = FakeClient(get=(200, load("get_hit.json")))
    fetch(client, album=None, duration_s=None)
    assert client.calls[0].params == {
        "artist_name": "Soda Stereo",
        "track_name": "De Música Ligera",
    }


def test_instrumental():
    client = FakeClient(get=(200, load("get_instrumental.json")))
    result = fetch(
        client,
        artist="Conjunto de Prueba",
        title="Interludio de Prueba",
        album=None,
        duration_s=184.0,
    )
    assert result.status == "instrumental"
    assert result.lyrics.instrumental and result.lyrics.lrclib_id == 4242424
    assert client.endpoints() == ["/get"]


@pytest.mark.parametrize("body", [b"<html><title>Maintenance</title></html>", [], None])
def test_unreadable_get_body_is_an_error_not_a_miss(body):
    client = FakeClient(get=(200, body))
    with pytest.raises(ProviderError):
        fetch(client)
    assert client.endpoints() == ["/get"]


@pytest.mark.parametrize(
    "error",
    [
        ProviderBlocked("lrclib", "https://lrclib.net/api/get", 429, "too many requests"),
        ProviderUnavailable("lrclib", "https://lrclib.net/api/get", None, "3 errors in a row"),
        BudgetExhausted("lrclib"),
    ],
)
def test_client_errors_on_get_propagate_unchanged(error):
    client = FakeClient(get=error)
    with pytest.raises(type(error)) as raised:
        fetch(client)
    assert raised.value is error
    assert client.endpoints() == ["/get"]


# The lookup: falling back to /api/search


def test_404_falls_back_to_search_with_duration_match():
    candidates = [
        track("Persiana Americana", id=101, duration=282.0),
        track("Persiana Americana", id=102, duration=291.4),
        track("Persiana Americana", id=103, duration=307.584),
    ]
    client = FakeClient(get=NOT_FOUND, search=(200, candidates))
    result = fetch(client, title="Persiana Americana", album="Signos", duration_s=291.0)
    assert result.status == "found"
    assert result.lyrics.lrclib_id == 102
    search = client.calls[1]
    assert search.url == "https://lrclib.net/api/search"
    assert search.params == {"track_name": "Persiana Americana", "artist_name": "Soda Stereo"}
    assert search.accept == (200,)


def test_get_record_without_lyrics_falls_back_to_search():
    empty = record(plainLyrics=None, syncedLyrics=None, instrumental=False)
    client = FakeClient(get=(200, empty), search=(200, [record(id=7)]))
    result = fetch(client)
    assert result.status == "found"
    assert result.lyrics.lrclib_id == 7
    assert client.endpoints() == ["/get", "/search"]


def test_503_then_empty_search_is_missing():
    client = FakeClient(get=OVERLOADED, search=(200, load("search_empty.json")))
    assert fetch(client) == LyricsResult("missing", None)
    assert client.endpoints() == ["/get", "/search"]


def test_search_without_a_matching_candidate_is_missing():
    client = FakeClient(get=OVERLOADED, search=(200, [track("Persiana Americana")]))
    assert fetch(client) == LyricsResult("missing", None)


def test_search_error_leaves_song_pending():
    error = ProviderError("lrclib", "https://lrclib.net/api/search", 500, "internal server error")
    client = FakeClient(get=OVERLOADED, search=error)
    with pytest.raises(ProviderError) as raised:
        fetch(client)
    assert raised.value is error


def test_overloaded_search_leaves_song_pending():
    client = FakeClient(get=OVERLOADED, search=OVERLOADED)
    with pytest.raises(ProviderError) as raised:
        fetch(client)
    assert raised.value.status == 503


def test_unreadable_search_body_is_an_error_not_a_miss():
    client = FakeClient(get=OVERLOADED, search=(200, {"code": 500, "name": "Oops"}))
    with pytest.raises(ProviderError):
        fetch(client)


def test_instrumental_found_by_search():
    client = FakeClient(get=NOT_FOUND, search=(200, [load("get_instrumental.json")]))
    result = fetch(
        client,
        artist="Conjunto de Prueba",
        title="Interludio de Prueba",
        album=None,
        duration_s=184.0,
    )
    assert result.status == "instrumental"
    assert result.lyrics.lrclib_id == 4242424


@pytest.mark.parametrize(
    "title,searched",
    [
        (
            "斑马，斑马",
            "斑马斑马",
        ),  # Han text split by punctuation: searched the way LRCLIB lists it
        ("너의 의미", "너의 의미"),  # Hangul words keep their space
        ("Persiana Americana", "Persiana Americana"),
    ],
)
def test_search_title_joins_han_split_by_punctuation(title, searched):
    client = FakeClient(get=OVERLOADED, search=(200, []))
    fetch(client, artist="Artista", title=title, album=None, duration_s=None)
    assert client.calls[0].params["track_name"] == title
    assert client.calls[1].params["track_name"] == searched


def test_lookup_reads_the_cache_forever_by_default():
    client = FakeClient(get=OVERLOADED, search=(200, []))
    fetch(client)
    assert [(c.cache, c.max_age) for c in client.calls] == [(True, None), (True, None)]


def test_cache_options_reach_every_request():
    # A re-check of a missing song must get past the cached miss on both endpoints.
    client = FakeClient(get=OVERLOADED, search=(200, []))
    fetch(client, cache=False, max_age=timedelta(days=30))
    assert [(c.cache, c.max_age) for c in client.calls] == [
        (False, timedelta(days=30)),
        (False, timedelta(days=30)),
    ]


def test_banma_plain_only_found_with_duration_253(tmp_path):
    client = FakeClient(get=OVERLOADED, search=(200, load("search_banma.json")))
    result = fetch(client, artist="宋冬野", title="斑马斑马", album="安和桥北", duration_s=253.0)
    assert result.status == "found"
    assert result.lyrics.lrclib_id == 29499942
    assert result.lyrics.synced is None
    assert result.lyrics.plain.startswith("範例歌詞 第一行")
    assert write_lyrics(tmp_path, result.lyrics) == [tmp_path / "lyrics.txt"]


# Choosing among search records


def test_pick_prefers_close_duration_then_synced():
    far_synced = record(id=1, duration=205.0)
    close_plain = record(id=2, duration=201.0, syncedLyrics=None)
    close_synced = record(id=3, duration=201.8)
    closest_plain = record(id=4, duration=200.2, syncedLyrics=None)
    assert pick([far_synced, close_plain, close_synced, closest_plain], duration_s=200.0)["id"] == 3
    assert pick([far_synced, close_plain, closest_plain], duration_s=200.0)["id"] == 4
    assert pick([record(id=5, duration=207.0), far_synced], duration_s=200.0)["id"] == 1


def test_pick_accepts_a_text_match_within_10s():
    # Neither key equals the song's, but both are close: ratios 87.5 and 91.7.
    near = track("La Música Ligera", id=1, duration=221.0, artistName="Sonda Estéreo")
    assert pick([near], duration_s=213.0)["id"] == 1


def test_pick_beyond_10s_needs_equal_title_and_artist_keys():
    near_title = track("De Música Ligeras", id=1, duration=243.0)
    same_keys = record(id=2, duration=243.0)
    assert pick([near_title], duration_s=213.0) is None
    assert pick([near_title, same_keys], duration_s=213.0)["id"] == 2


def test_pick_prefers_within_10s_over_synced_beyond():
    plain_near = record(id=1, duration=218.0, syncedLyrics=None)
    synced_far = record(id=2, duration=243.0)
    assert pick([synced_far, plain_near], duration_s=213.0)["id"] == 1


def test_pick_without_duration_prefers_synced():
    plain = record(id=1, duration=150.0, syncedLyrics=None)
    synced = record(id=2, duration=400.0)
    assert pick([plain, synced], duration_s=None)["id"] == 2


def test_pick_rejects_other_titles_and_artists():
    # Close, but under 85: ratios 78.8 and 81.8.
    other_title = track("De Musica Liviana", id=1)
    other_artist = record(id=2, artistName="Sada Sterea")
    no_artist = record(id=3, artistName=None)
    assert pick([other_title, other_artist, no_artist], duration_s=213.0) is None


def test_pick_accepts_one_artist_key_inside_the_other():
    duet = record(id=1, artistName="Soda Stereo & Andrea Echeverri")
    assert pick([duet], duration_s=213.0)["id"] == 1
    band = record(id=2, artistName="Bob Marley")
    marley = partial(pick_candidate, artist="Bob Marley & The Wailers", title="De Música Ligera")
    assert marley([band], duration_s=213.0)["id"] == 2


def test_pick_compares_punctuation_only_names_as_written():
    # slug_key leaves nothing of "!!!" or "?", so such names are compared as written.
    song = track("?", artistName="!!!")
    assert pick_candidate([song], artist="!!!", title="?", duration_s=213.0) == song
    assert pick_candidate([song], artist="!!!", title="¡!", duration_s=213.0) is None
    assert pick_candidate([song], artist="Soda Stereo", title="?", duration_s=213.0) is None


def test_pick_skips_records_without_lyrics():
    empty = record(id=1, duration=213.0, plainLyrics=None, syncedLyrics=None)
    assert pick([empty, record(id=2, duration=214.5)], duration_s=213.0)["id"] == 2


@pytest.mark.parametrize("wanted,listed", [("斑马，斑马", "斑马斑马"), ("斑马斑马", "斑马，斑马")])
def test_cjk_title_variants_match(wanted, listed):
    candidates = [{**c, "name": listed, "trackName": listed} for c in load("search_banma.json")]
    best = pick_candidate(candidates, artist="宋冬野", title=wanted, duration_s=253.0)
    assert best is not None and best["id"] == 29499942


# Files


def test_write_lyrics_ends_each_file_with_one_newline(tmp_path):
    song_dir = tmp_path / "Artista" / "Canción"
    lyrics = Lyrics(
        plain="Uno\nDos\n\n",
        synced="[00:01.00] Uno\n[00:02.00] Dos",
        instrumental=False,
        duration=None,
        lrclib_id=None,
    )
    assert write_lyrics(song_dir, lyrics) == [song_dir / "lyrics.txt", song_dir / "lyrics.lrc"]
    assert (song_dir / "lyrics.txt").read_text(encoding="utf-8") == "Uno\nDos\n"
    assert (song_dir / "lyrics.lrc").read_text(
        encoding="utf-8"
    ) == "[00:01.00] Uno\n[00:02.00] Dos\n"


def test_plain_only_lyrics_write_no_lrc_and_drop_a_stale_one(tmp_path):
    (tmp_path / "lyrics.lrc").write_text("[00:01.00] vieja\n", encoding="utf-8")
    lyrics = Lyrics.from_record(load("search_banma.json")[2])
    assert write_lyrics(tmp_path, lyrics) == [tmp_path / "lyrics.txt"]
    assert not (tmp_path / "lyrics.lrc").exists()


def test_lyrics_without_text_write_nothing(tmp_path):
    song_dir = tmp_path / "Conjunto de Prueba" / "Interludio de Prueba"
    assert write_lyrics(song_dir, Lyrics.from_record(load("get_instrumental.json"))) == []
    assert not song_dir.exists()


def test_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    (tmp_path / "lyrics.txt").write_text("versión anterior\n", encoding="utf-8")

    def disk_full(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError, match="disk full"):
        write_lyrics(tmp_path, Lyrics.from_record(load("get_hit.json")))
    assert (tmp_path / "lyrics.txt").read_text(encoding="utf-8") == "versión anterior\n"
    assert [p.name for p in tmp_path.iterdir()] == ["lyrics.txt"]


def test_written_files_follow_the_umask(tmp_path):
    # The service runs with UMask=0027 and Syncthing reads the library through the group.
    old = os.umask(0o027)
    try:
        write_lyrics(tmp_path, Lyrics.from_record(load("get_hit.json")))
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "lyrics.txt").stat().st_mode) == 0o640
