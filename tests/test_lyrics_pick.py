"""lyrics_pick.py: one row of a song's kept lyrics search made its lyrics, its auto sheet laid over them at once.

LRCLIB is a fake here (``/api/search``, ``/api/get`` and ``/api/get/{id}``), Megalobiz and AZLyrics tests/helpers/'
fakes, each behind a real ``PoliteClient`` made by ``_common.make_client`` (``transport_for``); auto-chords' models
test_youtube_sheet.py's fake recognizer and beats, chordpro ``fake_chordpro``: nothing reaches the network, and no
model runs. Each search is a real ``search_lyrics``, so its answers are in the HTTP cache as a pick finds them.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import add_song
from helpers.azlyrics_site import FakeAzLyrics
from helpers.megalobiz_site import FakeMegalobiz
from helpers.megalobiz_site import record as mz_record
from helpers.rendered import fake_chordpro
from test_youtube_sheet import Heard, Recognizer, beats, wav

from caracole import youtube_fetch
from caracole.autochords.transcript import (
    PICKED_NONE,
    Transcript,
    keep_transcript,
    transcript_of,
    why_not_offered,
)
from caracole.commands import _common
from caracole.db import kv_get, kv_set
from caracole.library import kept_files, song_dir
from caracole.lyrics import Lyrics, song_lyrics
from caracole.lyrics_pick import STAGES, PickRequest, clear_pick, pick_lyrics
from caracole.lyrics_search import KV, search_lyrics
from caracole.overrides import load_overrides, override_key, set_lyrics_name, set_lyrics_record
from caracole.songs import AUTO_SHEET, get_song, update_song
from caracole.versions import get_version, set_raw

NOW = datetime(2026, 11, 26, 13, 0, tzinfo=UTC)
SONG = ("Nick Cani", "Vikingos veganos (Video Oficial)")
NAME = ("Nick Cani", "Vikingos veganos")
SYNCED = "[00:00.50]Somos vikingos de prueba\n[00:05.20]comemos lechuga de prueba\n"
OTHER = "[00:00.50]Otras palabras\n[00:05.20]nada que ver\n"


def lrc(lrclib_id=77, *, synced=SYNCED, plain=None, duration=10.0, album="Pruebas", instrumental=False) -> dict:
    from caracole.lyrics import plain_from_synced

    return {"id": lrclib_id, "name": "Vikingos veganos", "trackName": "Vikingos veganos", "artistName": "Nick Cani",
            "albumName": album,
            "duration": duration, "instrumental": instrumental,
            "plainLyrics": plain if plain is not None else (plain_from_synced(synced) if synced else None),
            "syncedLyrics": synced}


class Lrclib:
    """``/api/search`` answers ``search``; ``/api/get/{id}`` the record of ``records`` with that id, else its 404;
    ``/api/get`` its 404. ``status`` answers every request with it. Every request kept."""

    def __init__(self):
        self.search: list[dict] = []
        self.records: list[dict] = []
        self.status: int | None = None
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/")
        self.requests.append(endpoint)
        if self.status is not None:
            return httpx.Response(self.status, text="Bad Gateway")
        if endpoint == "search":
            return httpx.Response(200, json=self.search)
        if endpoint.startswith("get/"):
            found = [r for r in self.records + self.search if str(r["id"]) == endpoint.removeprefix("get/")]
            return httpx.Response(200, json=found[0]) if found else httpx.Response(404, json={"name": "NotFound"})
        return httpx.Response(404, json={"name": "NotFound"})


class Sites:
    def __init__(self):
        self.lrclib = Lrclib()
        self.megalobiz = FakeMegalobiz()
        self.azlyrics = FakeAzLyrics({})

    def requests(self) -> int:
        return len(self.lrclib.requests) + len(self.megalobiz.requests) + len(self.azlyrics.requests)

    def forget(self) -> None:
        self.lrclib.requests.clear()
        self.megalobiz.requests.clear()
        self.azlyrics.requests.clear()


@pytest.fixture
def sites(monkeypatch):
    s = Sites()

    def transport(provider):
        handlers = {"lrclib": lambda r: s.lrclib.handler(r), "megalobiz": lambda r: s.megalobiz.handler(r),
                    "azlyrics": lambda r: s.azlyrics.handler(r)}
        if provider not in handlers:
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(handlers[provider])

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return s


@pytest.fixture
def here(monkeypatch):
    """auto-chords taken to be here (its packages and model files): the chords stage runs the fakes."""
    monkeypatch.setattr(youtube_fetch, "autochords_problem", lambda cfg: None)


@pytest.fixture
def song(cfg, conn):
    """Nick Cani - Vikingos veganos (Video Oficial): a video's decorated title, with 10 s of audio of its own, its
    lyrics missing under it."""
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    s = add_song(conn, *SONG, duration_ms=None)
    audio = wav(cfg.cache_dir / "audio" / f"{s.id}.wav", 10.0)
    update_song(conn, s.id, audio_path=str(audio), audio_mtime=audio.stat().st_mtime, lyrics_status="missing",
                lyrics_at="2026-11-20T00:00:00Z")
    for site in ("megalobiz", "azlyrics"):
        kv_set(conn, f"{site}:checked:{s.id}", "2026-11-20T00:00:00Z")
    return get_song(conn, s.id)


def searched(cfg, conn, song, sites, name=NAME, now=NOW):
    found = search_lyrics(cfg, conn, get_song(conn, song.id), name, now=now)
    sites.forget()
    return found


def pick(cfg, *, n=None, record=None, recognizer=None, now=NOW):
    heard = Heard()
    result = pick_lyrics(cfg, PickRequest(*SONG, pick=n, record=record), heard, runner=fake_chordpro,
                         recognizer=recognizer or Recognizer(), beats_fn=beats, now=now)
    return result, heard


def auto_sheet_of(cfg, conn, song, *, recognizer=None):
    """The song's auto sheet made now, by the fakes, over whatever lyrics it has."""
    from caracole.autochords.run import autochords_pending

    autochords_pending(conn, cfg, recognizer=recognizer or Recognizer(), beats_fn=beats, now=NOW,
                       only={song.id})
    return auto_raw(conn, song)


def auto_raw(conn, song) -> dict:
    [auto] = [f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET]
    return get_version(conn, auto.version_id).raw


def sheet_text(cfg, song) -> str:
    return (song_dir(cfg.library_dir, song) / AUTO_SHEET).read_text(encoding="utf-8")


def keep_human_sheet(conn, cfg, song):
    """A UG sheet kept for the song, with the sheet.json its render reads (helpers/rendered.py's)."""
    import json

    from helpers.rendered import FETCHED, SHEET
    from helpers.ug_pages import version_dict

    from caracole.library import keep_file, write_atomic
    from caracole.ug.page import strip_markup
    from caracole.versions import upsert_version

    raw = version_dict(85053, song=song.title, artist=song.artist, tonality_name="G")
    vid = upsert_version(conn, provider="ug", tab_id=str(raw["id"]), song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(SHEET).encode("utf-8"), rank=1)
    doc = {"version": raw, "content": SHEET, "url": raw["tab_url"], "meta": []}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json", json.dumps(doc, ensure_ascii=False).encode())


def entry(cfg):
    return load_overrides(cfg.overrides_file).lyrics.get(override_key(" - ".join(SONG)))


# --- each site's record --------------------------------------------------------------------------------------------


def test_an_lrclib_record_is_taken_from_the_searchs_cached_answer_with_no_request(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    result, heard = pick(cfg, n=1)
    assert result.ok, result
    assert sites.requests() == 0 and result.requests.get("lrclib", 0) == 0
    assert heard.ends()["lyrics"] == ("done", "timed lyrics from LRCLIB: Nick Cani - Vikingos veganos (Pruebas, 0:10)")
    after = get_song(conn, song.id)
    assert after.lyrics_status == "found" and song_lyrics(after).synced == SYNCED
    assert (song_dir(cfg.library_dir, after) / "lyrics.lrc").read_text(encoding="utf-8") == SYNCED


def test_an_lrclib_record_the_cache_lost_is_one_get_by_its_id(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    shutil.rmtree(cfg.cache_dir / "http" / "lrclib")
    result, heard = pick(cfg, record="lrclib:77")
    assert result.ok, result
    assert sites.lrclib.requests == ["get/77"] and result.requests == {"lrclib": 1}
    assert get_song(conn, song.id).lyrics_status == "found"


def test_a_megalobiz_record_is_one_lrc_request(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=8, title="Vikingos veganos", artist="Nick Cani", duration=10.0)]
    searched(cfg, conn, song, sites)
    result, heard = pick(cfg, record="megalobiz:8")
    assert result.ok, result
    assert sites.megalobiz.endpoints() == ["lrc"] and sites.requests() == 1
    state, said = heard.ends()["lyrics"]
    assert state == "done" and said.startswith("timed lyrics from Megalobiz: Nick Cani - Vikingos veganos")
    lyrics = song_lyrics(get_song(conn, song.id))
    assert lyrics.provider == "megalobiz" and lyrics.synced


def test_an_azlyrics_record_is_one_page_request(cfg, conn, sites):
    from helpers.azlyrics_site import POMME, SONG as PAGE

    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    s = add_song(conn, "Pomme", "Mononoke (clip officiel)", duration_ms=None)
    sites.azlyrics.pages = dict(POMME)
    search_lyrics(cfg, conn, s, ("Pomme", "Mononoke"), now=NOW)
    sites.forget()
    heard = Heard()
    result = pick_lyrics(cfg, PickRequest("Pomme", "Mononoke (clip officiel)", record="azlyrics:pomme/mononoke"),
                         heard, runner=fake_chordpro, now=NOW)
    assert result.ok, result
    assert sites.azlyrics.requests == [PAGE] and sites.requests() == 1
    state, said = heard.ends()["lyrics"]
    assert state == "done" and said.startswith("plain lyrics from AZLyrics: ")
    lyrics = song_lyrics(get_song(conn, s.id))
    assert lyrics.provider == "azlyrics" and lyrics.has_lyrics and not lyrics.synced


# --- what is kept -------------------------------------------------------------------------------------------------


def test_the_picked_lyrics_replace_better_ones_and_say_what_they_replaced(cfg, conn, song, sites):
    timed = Lyrics(plain="Somos vikingos", synced="[00:00.50]Somos vikingos\n", instrumental=False, duration=10.0,
                   lrclib_id=9)
    update_song(conn, song.id, lyrics_status="found", lyrics_json=timed.to_json(), lyrics_at="2026-11-20T00:00:00Z")
    sites.lrclib.search = [lrc(77, synced=None, plain="Otras palabras", duration=36.0)]
    searched(cfg, conn, song, sites)
    result, heard = pick(cfg, n=1)
    assert result.ok, result
    assert heard.ends()["lyrics"] == (
        "done", "plain lyrics from LRCLIB: Nick Cani - Vikingos veganos (Pruebas, 0:36); "
                "in place of LRCLIB's timed lyrics; "
                "the audio is 26 s shorter")
    lyrics = song_lyrics(get_song(conn, song.id))
    assert (lyrics.plain, lyrics.synced, lyrics.lrclib_id) == ("Otras palabras", None, 77)


def test_the_record_is_noted_under_lyrics_with_the_name_kept(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    pick(cfg, n=1)
    noted = entry(cfg)
    assert noted.asked == NAME and noted.record.text == "lrclib:77"
    assert kv_get(conn, f"{KV}{song.id}") is not None  # the search stays, for the page's "In use"


def test_a_record_not_among_the_last_searchs_rows_is_refused(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    result, heard = pick(cfg, record="lrclib:1")
    assert result.refused == "“lrclib:1” isn't among the records its last search listed"
    assert heard.ends()["song"] == ("failed", result.refused)
    assert all(heard.ends()[name][0] == "skipped" for name, _ in STAGES[1:])
    assert sites.requests() == 0 and entry(cfg).record is None
    assert get_song(conn, song.id).lyrics_status == "pending"  # as the search under another name left it


@pytest.mark.parametrize("kept,said", [
    (False, "search Nick Cani - Vikingos veganos (Video Oficial)'s lyrics first (caracole lyrics --song … --as …)"),
    (True, "its last search is over a week old: search again"),
], ids=["none kept", "over a week old"])
def test_a_search_over_a_week_old_is_refused(cfg, conn, song, sites, kept, said):
    sites.lrclib.search = [lrc(77)]
    if kept:
        searched(cfg, conn, song, sites, now=NOW - timedelta(days=8))
    result, _ = pick(cfg, n=1)
    assert result.refused == said and sites.requests() == 0


def test_a_song_not_in_the_book_is_refused(cfg, conn, sites):
    result, _ = pick(cfg, n=1)
    assert result.refused == "Nick Cani - Vikingos veganos (Video Oficial) isn't in the book"


def test_pick_n_is_the_nth_row(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77), lrc(78, synced=OTHER, album="Live")]
    found = searched(cfg, conn, song, sites)
    result, _ = pick(cfg, n=2)
    assert result.ok, result
    assert entry(cfg).record.text == found.rows[1].record
    result, _ = pick(cfg, n=3)
    assert result.refused == "its last search listed 2 records: there is no row 3"


# --- what isn't kept ----------------------------------------------------------------------------------------------


def test_a_record_with_no_lyrics_now_keeps_nothing(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=8, title="Vikingos veganos", artist="Nick Cani", duration=10.0)]
    searched(cfg, conn, song, sites)
    sites.megalobiz.records = []  # gone since: its 404
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-11-20T00:00:00Z")
    update_song(conn, song.id, lyrics_status="missing", lyrics_at="2026-11-20T00:00:00Z")
    result, heard = pick(cfg, record="megalobiz:8")
    assert result.ok, result
    assert heard.ends()["lyrics"] == ("skipped", "Megalobiz's record 8 has no lyrics now; nothing kept")
    assert heard.ends()["chords"] == ("skipped", "no new lyrics")
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_at) == ("missing", "2026-11-20T00:00:00Z")
    assert entry(cfg).record is None


def test_an_error_keeps_nothing_and_writes_no_record(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=8, title="Vikingos veganos", artist="Nick Cani", duration=10.0)]
    searched(cfg, conn, song, sites)
    sites.megalobiz.failing = {"lrc": 502}
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-11-20T00:00:00Z")
    update_song(conn, song.id, lyrics_status="missing", lyrics_at="2026-11-20T00:00:00Z")
    result, heard = pick(cfg, record="megalobiz:8")
    assert result.ok, result  # a site that fails is no failure of the command: it exits 0
    state, said = heard.ends()["lyrics"]
    assert state == "failed" and said.startswith("Megalobiz failed (") and said.endswith("; nothing kept")
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_at) == ("missing", "2026-11-20T00:00:00Z")
    assert kv_get(conn, f"megalobiz:checked:{song.id}") == "2026-11-20T00:00:00Z"
    assert entry(cfg).record is None


# --- the sheet ----------------------------------------------------------------------------------------------------


def test_the_auto_sheet_is_made_again_over_the_picked_lyrics(cfg, conn, song, sites, here):
    assert auto_sheet_of(cfg, conn, song)["lyrics"] == "none"
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    recognizer = Recognizer()
    result, heard = pick(cfg, n=1, recognizer=recognizer)
    assert result.ok, result
    assert heard.ends()["chords"] == ("done", "chords over the lyrics")
    assert recognizer.calls and auto_raw(conn, song)["lyrics"] == "synced"
    assert "Somos vikingos de prueba" in sheet_text(cfg, song)
    assert heard.ends()["pdf"][0] == "done" and result.files


def test_a_keyless_auto_sheet_is_made_due_by_a_pick_of_other_words(cfg, conn, song, sites, monkeypatch):
    # A sheet made before its version kept the words' key (D1) would keep its old words for good.
    from caracole.autochords.run import autochords_pending

    monkeypatch.setattr(youtube_fetch, "autochords_problem", lambda cfg: "built without auto-chords")

    update_song(conn, song.id, lyrics_status="found", lyrics_at="2026-11-20T00:00:00Z",
                lyrics_json=Lyrics.from_record(lrc(9, synced=OTHER)).to_json())
    raw = auto_sheet_of(cfg, conn, song)
    assert raw["lyrics"] == "synced"
    [auto] = [f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET]
    set_raw(conn, auto.version_id, {k: v for k, v in raw.items() if k != "lyrics_key"})
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    result, heard = pick(cfg, n=1)  # auto-chords isn't here: tonight's run makes it again
    assert heard.ends()["chords"][0] == "skipped"
    stats = autochords_pending(conn, cfg, recognizer=Recognizer(), beats_fn=beats, now=NOW, only={song.id})
    assert stats.generated == 1
    assert "Somos vikingos de prueba" in sheet_text(cfg, song) and "Otras palabras" not in sheet_text(cfg, song)


def test_a_transcript_sheet_is_made_again_over_the_site_lyrics_and_the_transcript_kept(cfg, conn, song, sites,
                                                                                      here):
    transcript = Transcript(lrc="[00:00.50]Palabras oidas\n", audio=song.audio_path, audio_mtime=song.audio_mtime,
                            model="whisper-large-v3", language="es", device="cpu", words_dropped=0,
                            made_at="2026-11-21T00:00:00Z")
    keep_transcript(conn, song, transcript)
    assert auto_sheet_of(cfg, conn, song).get("lyrics_source") == "transcript"
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    result, heard = pick(cfg, n=1)
    assert result.ok, result
    assert heard.ends()["chords"] == ("done", "chords over the lyrics")
    raw = auto_raw(conn, song)
    assert "lyrics_source" not in raw and "Somos vikingos de prueba" in sheet_text(cfg, song)
    assert transcript_of(conn, get_song(conn, song.id)) == transcript  # kept, unused


def test_a_song_with_a_human_sheet_gets_its_lyrics_and_page_and_no_chords(cfg, conn, song, sites, here):
    keep_human_sheet(conn, cfg, song)
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    recognizer = Recognizer()
    result, heard = pick(cfg, n=1, recognizer=recognizer)
    assert result.ok, result
    ends = heard.ends()
    assert ends["lyrics"][0] == "done"
    assert ends["chords"] == ("skipped", "its sheet is a site's: no auto sheet to make again")
    assert ends["pdf"][0] == "done" and ends["pages"][0] == "done"
    assert recognizer.calls == []


def test_a_song_with_its_audio_and_no_auto_sheet_gets_one_over_the_picked_lyrics_at_once(cfg, conn, song, sites,
                                                                                         here):
    # The feature's main case: a video whose decorated title found no lyrics; the owner searches, picks, and the sheet
    # comes with its words at once.
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    recognizer = Recognizer()
    result, heard = pick(cfg, n=1, recognizer=recognizer)
    assert result.ok, result
    assert heard.ends()["chords"] == ("done", "chords over the lyrics")
    assert recognizer.calls and auto_raw(conn, song)["lyrics"] == "synced"
    assert heard.ends()["pdf"][0] == "done" and heard.ends()["pdf"][1] != "no sheet"


def test_without_auto_chords_a_song_with_no_auto_sheet_waits_for_tonights(cfg, conn, song, sites, monkeypatch):
    monkeypatch.setattr(youtube_fetch, "autochords_problem", lambda cfg: "built without auto-chords (missing: torch)")
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    result, heard = pick(cfg, n=1)
    assert result.ok, result
    assert heard.ends()["chords"] == (
        "skipped", "auto-chords isn't here (built without auto-chords (missing: torch)); tonight's run makes it again")
    assert heard.ends()["pdf"] == ("skipped", "no sheet")


def test_without_auto_chords_the_chords_wait_for_tonight_and_it_exits_0(cfg, conn, song, sites, monkeypatch):
    auto_sheet_of(cfg, conn, song)
    monkeypatch.setattr(youtube_fetch, "autochords_problem", lambda cfg: "built without auto-chords (missing: torch)")
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    recognizer = Recognizer()
    result, heard = pick(cfg, n=1, recognizer=recognizer)
    assert result.ok and result.failed is None, result
    assert heard.ends()["chords"] == (
        "skipped", "auto-chords isn't here (built without auto-chords (missing: torch)); tonight's run makes it again")
    assert recognizer.calls == []
    # Its chart takes the words as plain lyrics now, with no model (sheet_lyrics.py, the PDF's render).
    assert auto_raw(conn, song)["lyrics"] == "plain" and "Somos vikingos de prueba" in sheet_text(cfg, song)


def test_a_waiting_lookup_goes_first_before_the_chords(cfg, conn, song, sites, here, monkeypatch):
    auto_sheet_of(cfg, conn, song)
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    order: list[str] = []
    monkeypatch.setattr(_common, "hand_over", lambda cfg, conn=None: order.append("lookup") or True)

    class Noted(Recognizer):
        def recognize(self, path):
            order.append("recognizer")
            return super().recognize(path)

    result, _ = pick(cfg, n=1, recognizer=Noted())
    assert result.ok, result
    assert order == ["lookup", "recognizer"]


def test_no_transcription_is_offered_once_lyrics_are_picked(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    pick(cfg, n=1)
    overrides = load_overrides(cfg.overrides_file)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), overrides) == "its lyrics are found"


# --- a pick cleared: a new question -------------------------------------------------------------------------------


def test_a_dead_record_cleared_has_every_site_asked_under_the_songs_own_name_before_any_transcription(
        cfg, conn, song, sites):
    from caracole.azlyrics_fetch import azlyrics_lyrics
    from caracole.lyrics import fetch_pending_lyrics
    from caracole.megalobiz_fetch import megalobiz_lyrics

    # Megalobiz's record 8, picked, is gone: its miss stamped the song's lyrics_at and megalobiz:checked:.
    set_lyrics_record(cfg.overrides_file, song.display, "megalobiz:8")
    update_song(conn, song.id, lyrics_status="missing", lyrics_at="2026-11-25T00:00:00Z")
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-11-25T00:00:00Z")
    overrides = load_overrides(cfg.overrides_file)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), overrides) == PICKED_NONE.format(record="megalobiz 8")

    said = clear_pick(cfg, conn, get_song(conn, song.id), overrides)
    assert said.startswith(
        "Cleared the record you picked for Nick Cani - Vikingos veganos (Video Oficial) (megalobiz 8)")
    assert entry(cfg) is None
    overrides = load_overrides(cfg.overrides_file)
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_at) == ("pending", None)
    assert all(kv_get(conn, f"{p}{song.id}") is None
               for p in ("megalobiz:checked:", "azlyrics:checked:", "lyrics:failed:"))
    assert why_not_offered(conn, cfg, after, overrides) == "its lyrics are pending"
    assert sites.requests() == 0  # a clear asks nothing

    # The next nightly pass asks the three at once, under the song's own name, and only then is it offered.
    picks = overrides.lyrics
    lrclib = fetch_pending_lyrics(conn, sites_client(cfg, conn, "lrclib"), cfg.library_dir, NOW, picks=picks)
    assert lrclib.missing == 1
    assert why_not_offered(conn, cfg, get_song(conn, song.id), overrides) == "megalobiz hasn't been asked"
    megalobiz_lyrics(conn, sites_client(cfg, conn, "megalobiz"), cfg.library_dir, NOW, picks=picks)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), overrides) == "azlyrics hasn't been asked"
    azlyrics_lyrics(conn, sites_client(cfg, conn, "azlyrics"), cfg.library_dir, NOW, lyrics=picks)
    assert [e for e, _ in sites.megalobiz.requests] == ["search"]
    assert sites.megalobiz.requests[0][1]["artist"] == SONG[0]  # the song's own name: no [lyrics] holds
    assert sites.azlyrics.requests == ["/n/nickcani.html"]  # its artist's page, under the song's own name
    assert why_not_offered(conn, cfg, get_song(conn, song.id), overrides) is None


def sites_client(cfg, conn, provider):
    return _common.make_client(cfg, conn, provider, "2026-11-26T13:00:00Z")


def test_a_clear_drops_the_lyrics_its_record_gave_and_makes_the_sheet_due(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    set_lyrics_name(cfg.overrides_file, song.display, None)
    pick(cfg, n=1)
    auto_sheet_of(cfg, conn, song)
    folder = song_dir(cfg.library_dir, song)
    assert (folder / "lyrics.lrc").is_file()
    said = clear_pick(cfg, conn, get_song(conn, song.id), load_overrides(cfg.overrides_file))
    assert "its lyrics from it dropped" in said
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_json, after.autochords_mtime) == ("pending", None, None)
    assert not (folder / "lyrics.lrc").exists() and not (folder / "lyrics.txt").exists()


def test_a_clear_with_no_record_is_nothing_to_clear(cfg, conn, song, sites):
    set_lyrics_name(cfg.overrides_file, song.display, "Nick Cani - Vikingos veganos")
    assert clear_pick(cfg, conn, song, load_overrides(cfg.overrides_file)) is None
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_at) == ("missing", "2026-11-20T00:00:00Z")
    assert entry(cfg).asked == NAME


# --- fix round 1 ---------------------------------------------------------------------------------------------------


def test_a_block_says_its_reason_and_keeps_nothing(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=8, title="Vikingos veganos", artist="Nick Cani", duration=10.0)]
    searched(cfg, conn, song, sites)
    sites.megalobiz.failing = {"lrc": 429}
    result, heard = pick(cfg, record="megalobiz:8")
    assert result.ok, result
    state, said = heard.ends()["lyrics"]
    assert state == "skipped" and said.startswith("Megalobiz turned us back (") and said.endswith(", nothing kept")
    assert "); no asks until " in said and entry(cfg).record is None


def test_a_kept_search_that_cant_be_read_is_no_search_never_an_old_one(cfg, conn, song, sites):
    from caracole.db import kv_set_json

    kv_set_json(conn, f"{KV}{song.id}", {"at": "2026-11-26T12:00:00Z", "as": "nonsense"})
    result, _ = pick(cfg, n=1)
    assert result.refused == (
        "search Nick Cani - Vikingos veganos (Video Oficial)'s lyrics first (caracole lyrics --song … --as …)")


def test_the_owners_case_a_chinese_name_is_picked_and_noted_under_its_key(cfg, conn, sites):
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    s = add_song(conn, "孟维来", "野人『MV』", duration_ms=None)
    update_song(conn, s.id, lyrics_status="missing", lyrics_at="2026-11-20T00:00:00Z")
    record = {**lrc(28399373, synced="[00:00.50]你是野人\n[00:05.20]我也是野人\n", duration=226.0, album="野人"),
              "name": "野人", "trackName": "野人", "artistName": "孟维来"}
    sites.lrclib.search = [record]
    search_lyrics(cfg, conn, s, ("孟维来", "野人"), now=NOW)
    sites.forget()
    heard = Heard()
    result = pick_lyrics(cfg, PickRequest("孟维来", "野人『MV』", pick=1), heard, runner=fake_chordpro, now=NOW)
    assert result.ok, result
    assert sites.requests() == 0
    ends = heard.ends()
    assert ends["lyrics"] == ("done", "timed lyrics from LRCLIB: 孟维来 - 野人 (野人, 3:46)")
    assert ends["chords"] == ("skipped", "no audio to make an auto sheet from")
    assert ends["pdf"] == ("skipped", "no sheet")
    after = get_song(conn, s.id)
    assert after.lyrics_status == "found" and "我也是野人" in song_lyrics(after).synced
    noted = load_overrides(cfg.overrides_file).lyrics[override_key("孟维来 - 野人『MV』")]
    assert noted.asked == ("孟维来", "野人") and noted.record.text == "lrclib:28399373"


def test_a_broken_overrides_file_fails_the_job_and_keeps_nothing(cfg, conn, song, sites):
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    before = get_song(conn, song.id)
    import caracole.overrides as ov

    def broken(*args, **kwargs):
        raise ov.OverridesError("overrides.toml: line 3: not TOML")

    from unittest import mock

    with mock.patch.object(ov, "set_lyrics_record", broken):
        result, heard = pick(cfg, n=1)
    assert not result.ok and result.failed.startswith("couldn't note the record in overrides.toml")
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_json, after.lyrics_at) == (
        before.lyrics_status, before.lyrics_json, before.lyrics_at)
    folder = song_dir(cfg.library_dir, song)
    assert not (folder / "lyrics.lrc").exists() and not (folder / "lyrics.txt").exists()


def test_lyric_files_that_cant_be_put_back_are_said_to_hold_the_new_words(cfg, conn, song, sites, monkeypatch):
    import caracole.lyrics as lyrics_module
    import caracole.overrides as ov

    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    before = get_song(conn, song.id)
    real, calls = lyrics_module.write_lyrics, []

    def once(folder, lyrics):  # the new words written, then the folder refuses them back
        calls.append(lyrics)
        if len(calls) > 1:
            raise OSError(30, "Read-only file system")
        return real(folder, lyrics)

    def broken(*args, **kwargs):
        raise ov.OverridesError("overrides.toml: line 3: not TOML")

    monkeypatch.setattr(lyrics_module, "write_lyrics", once)
    monkeypatch.setattr(ov, "set_lyrics_record", broken)
    result, heard = pick(cfg, n=1)
    assert not result.ok
    state, said = heard.ends()["lyrics"]
    assert state == "failed" and said.startswith("couldn't note the record in overrides.toml")
    assert "its lyric files may hold the new words" in said and "Read-only file system" in said
    assert not said.endswith("; nothing kept")
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_json) == (before.lyrics_status, before.lyrics_json)


def test_an_info_json_that_cant_be_written_fails_the_job_after_the_lyrics_are_kept(cfg, conn, song, sites,
                                                                                     monkeypatch):
    import caracole.library as library

    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    real, calls = library.write_info, []

    def once(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)

    monkeypatch.setattr(library, "write_info", once)
    result, heard = pick(cfg, n=1)
    assert not result.ok and result.bug is None
    state, said = heard.ends()["lyrics"]
    assert state == "done" and said.startswith("timed lyrics from LRCLIB")
    assert "info.json couldn't be written (" in said
    assert "its lyrics are kept" in result.failed
    assert get_song(conn, song.id).lyrics_status == "found" and entry(cfg).record.text == "lrclib:77"


def test_lyrics_that_cant_be_written_fail_the_job_and_leave_the_entry_and_the_song_as_they_were(
        cfg, conn, song, sites, monkeypatch):
    import caracole.lyrics as lyrics_module

    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-11-20T00:00:00Z")
    before = get_song(conn, song.id)

    def full(song_dir, lyrics):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(lyrics_module, "write_lyrics", full)
    result, heard = pick(cfg, n=1)
    assert not result.ok and "couldn't write its lyrics" in result.failed
    assert entry(cfg).record is None
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_at) == (before.lyrics_status, before.lyrics_at)
    assert kv_get(conn, f"megalobiz:checked:{song.id}") == "2026-11-20T00:00:00Z"


def test_a_pdf_that_cant_be_made_fails_the_job(cfg, conn, song, sites, monkeypatch):
    import caracole.render as render

    auto_sheet_of(cfg, conn, song)
    monkeypatch.setattr(youtube_fetch, "autochords_problem", lambda cfg: "built without auto-chords")
    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    real = render.render_all

    def failing(*args, **kwargs):
        stats = real(*args, **kwargs)
        stats.failed = 1
        return stats

    monkeypatch.setattr(render, "render_all", failing)
    result, heard = pick(cfg, n=1)
    assert heard.ends()["pdf"] == ("failed", "chordpro couldn't make the PDF (see the log)")
    assert result.failed == "chordpro couldn't make the PDF (see the log)" and not result.ok
    assert get_song(conn, song.id).lyrics_status == "found"  # the lyrics stay kept


def test_a_clear_after_a_megalobiz_pick_drops_its_lyrics(cfg, conn, song, sites):
    sites.megalobiz.records = [mz_record(lrc_id=8, title="Vikingos veganos", artist="Nick Cani", duration=10.0)]
    searched(cfg, conn, song, sites)
    assert pick(cfg, record="megalobiz:8")[0].ok
    said = clear_pick(cfg, conn, get_song(conn, song.id), load_overrides(cfg.overrides_file))
    assert "its lyrics from it dropped" in said
    assert get_song(conn, song.id).lyrics_json is None


def test_a_clear_after_an_azlyrics_pick_drops_its_lyrics(cfg, conn, sites):
    from helpers.azlyrics_site import POMME

    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    s = add_song(conn, "Pomme", "Mononoke (clip officiel)", duration_ms=None)
    sites.azlyrics.pages = dict(POMME)
    search_lyrics(cfg, conn, s, ("Pomme", "Mononoke"), now=NOW)
    pick_lyrics(cfg, PickRequest("Pomme", "Mononoke (clip officiel)", record="azlyrics:pomme/mononoke"), Heard(),
                runner=fake_chordpro, now=NOW)
    assert get_song(conn, s.id).lyrics_status == "found"
    said = clear_pick(cfg, conn, get_song(conn, s.id), load_overrides(cfg.overrides_file))
    assert "its lyrics from it dropped" in said
    after = get_song(conn, s.id)
    assert (after.lyrics_status, after.lyrics_json) == ("pending", None)
    assert not (song_dir(cfg.library_dir, after) / "lyrics.txt").exists()


def test_a_clear_leaves_lyrics_that_didnt_come_from_its_record_alone(cfg, conn, song, sites):
    other = Lyrics.from_record(lrc(9, synced=OTHER))
    update_song(conn, song.id, lyrics_status="found", lyrics_json=other.to_json(), lyrics_at="2026-11-20T00:00:00Z")
    set_lyrics_record(cfg.overrides_file, song.display, "megalobiz:8")  # written by hand, after they came
    said = clear_pick(cfg, conn, get_song(conn, song.id), load_overrides(cfg.overrides_file))
    assert said is not None and "dropped" not in said
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_json) == ("found", other.to_json())


def test_a_lyrics_file_that_cant_be_removed_is_said_and_the_clear_stands(cfg, conn, song, sites, monkeypatch):
    from pathlib import Path

    sites.lrclib.search = [lrc(77)]
    searched(cfg, conn, song, sites)
    assert pick(cfg, n=1)[0].ok
    real = Path.unlink

    def stuck(self, missing_ok=False):
        if self.name == "lyrics.lrc":
            raise PermissionError(13, "Permission denied")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", stuck)
    said = clear_pick(cfg, conn, get_song(conn, song.id), load_overrides(cfg.overrides_file))
    assert "lyrics.lrc couldn't be removed (" in said
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_json) == ("pending", None) and entry(cfg).record is None
