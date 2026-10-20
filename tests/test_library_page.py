import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from helpers import browser
from helpers.browser import in_chromium
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.library import keep_file, song_dir
from caracole.library_page import build_library_page, write_library_page
from caracole.normalize import fold
from caracole.overrides import Overrides
from caracole.songs import update_song
from caracole.todo import search_links
from caracole.versions import set_picks, upsert_version

from conftest import add_song

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)
JSON_BLOCK = re.compile(r'<script type="application/json" id="songs">(.*?)</script>', re.S)


def page(conn, cfg, overrides=None):
    return build_library_page(conn, cfg, overrides or Overrides(), NOW)


def data_of(html):
    blocks = JSON_BLOCK.findall(html)
    assert len(blocks) == 1
    return json.loads(blocks[0])


def songs_of(html):
    return {s["display"]: s for s in data_of(html)["songs"]}


def csp_of(html):
    return re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)


def sha(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def put(cfg, song, *names, data=b"x"):
    folder = song_dir(cfg.library_dir, song)
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(data)
    return folder


def version(conn, song, tab_id, *, slot="sheet", kind="chords", raw=None, ver=1, rating=4.5, votes=12):
    return upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot=slot, kind=kind,
                          rating=rating, votes=votes, version=ver, label=None,
                          url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}", raw=raw or {}, now="x")


# --- the data ------------------------------------------------------------------------


def test_every_song_is_in_the_json_with_its_status_and_facts(conn, cfg):
    s1 = add_song(conn, "Soda Stereo", "De Música Ligera", added_at="2026-10-01T00:00:00Z")
    s2 = add_song(conn, "Radiohead", "Creep - Remastered 2009", added_at="2026-10-05T00:00:00Z")
    s3 = add_song(conn, "Some Artist", "Some Interlude")
    update_song(conn, s1.id, status="found", lyrics_status="found")
    update_song(conn, s2.id, review=True, lyrics_status="missing")
    update_song(conn, s3.id, status="ignored")
    data = data_of(page(conn, cfg))
    assert data["generated"] == "2026-10-18T03:41:00Z"
    songs = {s["display"]: s for s in data["songs"]}
    assert set(songs) == {"Soda Stereo - De Música Ligera", "Radiohead - Creep", "Some Artist - Some Interlude"}
    soda = songs["Soda Stereo - De Música Ligera"]
    assert (soda["artist"], soda["title"], soda["status"], soda["lyrics"]) == (
        "Soda Stereo", "De Música Ligera", "found", "found")
    assert soda["added"] == "2026-10-01T00:00:00Z" and soda["review"] is False
    creep = songs["Radiohead - Creep"]
    assert (creep["title"], creep["status"], creep["review"], creep["lyrics"]) == (
        "Creep", "wanted", True, "missing")
    assert songs["Some Artist - Some Interlude"]["status"] == "ignored"


def test_key_comes_from_the_kept_sheets_version_and_transpose_from_overrides(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    v = version(conn, s, 85053, raw={"tonality_name": "Bm"})
    keep_file(conn, cfg.library_dir, song=s, version_id=v, name="sheet.txt", data=b"sheet", rank=1)
    plain = add_song(conn, "Radiohead", "Creep")
    o = Overrides(transpose={s.key: -2})
    songs = songs_of(page(conn, cfg, o))
    soda, creep = songs["Soda Stereo - De Música Ligera"], songs["Radiohead - Creep"]
    assert (soda["key"], soda["key_source"]) == ("B minor", "tab")
    assert soda["transpose"] == -2
    assert (creep["key"], creep["key_source"]) == (None, None) and creep["transpose"] == 0
    assert plain.key not in o.transpose


def keep_sheet_json(conn, cfg, song, content, *, raw=None, tab_id=1):
    v = version(conn, song, tab_id, raw=raw)
    doc = json.dumps({"content": content}).encode()
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.json", data=doc, rank=1)
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.txt", data=content.encode(), rank=1)


AM_F_C_G = "[ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch]\nWords\n" * 3


def test_the_page_says_where_a_key_came_from_as_keys_py_does():
    from caracole.keys import SOURCES
    from caracole.library_page import _SCRIPT

    for source, text in SOURCES.items():
        assert f'{source}: "{text}"' in _SCRIPT


def test_without_ugs_key_the_page_has_the_key_estimated_from_the_chords(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet_json(conn, cfg, s, AM_F_C_G)
    soda = songs_of(page(conn, cfg))[s.display]
    assert (soda["key"], soda["key_source"]) == ("A minor", "chords")
    # The page's script finds a typed key by its pitch class; the search text keeps only the mode,
    # so "a minor" can't match any minor song with an "a" in its name.
    words = soda["search"].split(" | ")
    assert "minor" in words and not any(w in words for w in ("a minor", "aminor"))


def test_a_song_in_the_ignore_override_shows_as_ignored(conn, cfg):
    s = add_song(conn, "Some Artist", "Some Interlude")
    assert songs_of(page(conn, cfg, Overrides(ignore=frozenset({s.key}))))[s.display]["status"] == "ignored"


def test_an_empty_library_still_makes_a_page(conn, cfg):
    html = page(conn, cfg)
    assert data_of(html)["songs"] == []
    assert html.lstrip().lower().startswith("<!doctype html>")


def test_each_card_has_its_artists_monogram_hue_and_jump_letters(conn, cfg):
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    other = add_song(conn, "Soda Stereo", "Persiana Americana")
    han = add_song(conn, "宋冬野", "斑马，斑马")
    beatles = add_song(conn, "The Beatles", "Yesterday")
    pac = add_song(conn, "2Pac", "Changes")
    songs = songs_of(page(conn, cfg))
    assert [songs[s.display]["monogram"] for s in (soda, han, beatles, pac)] == ["SS", "宋", "TB", "2"]
    assert songs[soda.display]["hue"] == songs[other.display]["hue"]  # one artist, one colour
    assert all(songs[s.display]["hue"] in range(8) for s in (soda, han, beatles, pac))
    # The A-Z strip's letters come from the sort keys: "The Beatles" is under B, 宋冬野 under S.
    assert [songs[s.display]["artistLetter"] for s in (soda, han, beatles, pac)] == ["S", "S", "B", "#"]
    assert [songs[s.display]["titleLetter"] for s in (soda, han, beatles, pac)] == ["D", "B", "Y", "C"]


def test_the_page_on_disk_has_no_forms_and_lets_none_be_sent(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    html = page(conn, cfg)
    assert "form-action 'none'" in csp_of(html)
    assert "connect-src" not in csp_of(html)  # default-src 'none': the file asks nothing of anyone
    assert "<form" not in JSON_BLOCK.sub("", html)
    assert "server" not in data_of(html)
    assert 'id="requested"' not in html and 'id="tray"' not in html


def test_the_served_page_has_the_request_form_and_its_token(conn, cfg):
    from caracole.library_page import WebControls

    wanted = add_song(conn, "Radiohead", "Creep")
    found = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, found.id, status="found")
    job = {"id": 4, "display": "Radiohead - Creep", "songId": wanted.id, "state": "running", "fetching": True,
           "line": {"tone": "running", "text": "Fetching from Ultimate Guitar…", "link": None},
           "details": "jobs?job=4#job-4"}
    controls = WebControls(csrf='t0k"<en', busy=frozenset({wanted.id}), active=2, removing=frozenset({found.id}),
                           jobs=(job,))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    shell = JSON_BLOCK.sub("", html)
    form = re.search(r'<form[^>]*action="/request"[^>]*>(.*?)</form>', shell, re.S)
    assert form and 'method="post"' in form.group(0)
    for name in ("artist", "title", "album", "duration", "fetch"):
        assert f'name="{name}"' in form.group(1), name
    assert '<input type="hidden" name="csrf" value="t0k&quot;&lt;en">' in form.group(1)
    # A phone's digits-only keypad has no ":", so the length field gets the full keyboard.
    duration = re.search(r'<input name="duration"[^>]*>', form.group(1), re.S).group(0)
    assert "inputmode" not in duration and "m:ss or seconds" in form.group(1)
    assert 'href="/jobs"' in shell
    assert "form-action 'self'" in csp_of(html) and "form-action 'none'" not in csp_of(html)
    # Its script may ask the server how the requests go, and nothing else.
    assert "connect-src 'self'" in csp_of(html) and "default-src 'none'" in csp_of(html)
    assert data_of(html)["server"] == {"csrf": 't0k"<en', "busy": [wanted.id], "active": 2, "removing": [found.id],
                                       "jobs": [job]}
    # Where the songs just requested go, and the list of requests.
    assert re.search(r'<section class="requested" id="requested"[^>]*hidden>', shell)
    assert re.search(r'<aside class="tray" id="tray"[^>]*hidden>', shell)
    # Still one script and one style, each allowed by its hash.
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    styles = re.findall(r"<style>(.*?)</style>", html, re.S)
    assert len(scripts) == 1 and len(styles) == 1
    assert sha(scripts[0]) in csp_of(html) and sha(styles[0]) in csp_of(html)


# --- files ---------------------------------------------------------------------------


def test_links_to_kept_files_are_relative_percent_encoded_and_in_order(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    put(cfg, s, "info.json", "tab.txt", "guitar-2.ptb", "guitar-1.gp5", "lyrics.lrc", "lyrics.txt",
        "sheet.cho", "sheet.txt", "sheet.json", "tab.json", "sheet.pdf", ".sheet.pdf.tmp", "notes.md")
    files = songs_of(page(conn, cfg))[s.display]["files"]
    folder = "Soda%20Stereo/De%20M%C3%BAsica%20Ligera/"
    assert [f["href"] for f in files] == [folder + n for n in (
        "sheet.pdf", "sheet.txt", "sheet.cho", "lyrics.txt", "lyrics.lrc", "guitar-1.gp5", "guitar-2.ptb",
        "tab.txt", "info.json")]
    assert [f["label"] for f in files][:2] == ["Sheet PDF", "Sheet text"]
    assert {f["label"] for f in files} >= {"Guitar Pro 1", "Power Tab 2", "Lyrics", "Info"}
    assert [f["primary"] for f in files] == [True] + [False] * 8


def test_scores_are_linked_after_the_guitar_pro_files_and_a_score_pdf_is_never_the_primary(conn, cfg):
    # caracole renders sheet.pdf; a PDF from MuseScore is a score, so the sheet text stays first.
    s = add_song(conn, "Oasis", "Wonderwall")
    put(cfg, s, "sheet.txt", "score-2.pdf", "score-1.mscz", "guitar-1.gp5", "score-1.pdf", "score-1.mid", "tab.txt")
    files = songs_of(page(conn, cfg))[s.display]["files"]
    assert [(f["name"], f["label"]) for f in files] == [
        ("sheet.txt", "Sheet text"), ("guitar-1.gp5", "Guitar Pro 1"), ("score-1.mscz", "Score 1 (MuseScore)"),
        ("score-1.pdf", "Score 1 (PDF)"), ("score-1.mid", "Score 1 (MIDI)"), ("score-2.pdf", "Score 2 (PDF)"),
        ("tab.txt", "Tab")]
    assert [f["name"] for f in files if f["primary"]] == ["sheet.txt"]


def test_a_songs_musescore_pages_are_linked_as_possible_matches(conn, cfg):
    import dataclasses

    from caracole.config import ProviderPolicy
    from caracole.musescore import parse_song_url

    for path in ("song/wonderwall-680101", "song/creep-680102"):
        conn.execute("INSERT INTO musescore_index VALUES (?, ?, ?, '18')", parse_song_url(f"https://musescore.com/{path}"))
    oasis = add_song(conn, "Oasis", "Wonderwall")
    ignored = add_song(conn, "Radiohead", "Creep")
    html = page(conn, cfg, Overrides(ignore=frozenset({ignored.key})))
    cards = songs_of(html)
    assert cards[oasis.display]["museScore"] == [
        {"label": "wonderwall-680101 (possible match)", "href": "https://musescore.com/song/wonderwall-680101",
         "source": "musescore"}]
    assert cards[ignored.display]["museScore"] == []
    assert '"Scores on MuseScore"' in html  # the card's heading for them
    off = dataclasses.replace(cfg, providers={**cfg.providers, "musescore": ProviderPolicy(10, (10.0, 20.0), False)})
    assert songs_of(page(conn, off))[oasis.display]["museScore"] == []


def test_a_guitar_pro_file_from_gtptabs_says_where_it_came_from(conn, cfg):
    # One downloaded for you, beside one you filed from _inbox for a UG pick.
    s = add_song(conn, "Blur", "Song 2")
    gtp = upsert_version(conn, provider="gtptabs", tab_id="12", song_id=s.id, slot="guitar", kind="guitar-pro",
                         rating=4, votes=0, version=1, label=None, url="https://gtptabs.com/tabs/2/blur/song-2.html",
                         raw={}, now="2026-10-17T03:30:00Z")
    keep_file(conn, cfg.library_dir, song=s, version_id=gtp, name="guitar-1.gpx", data=b"gpx", rank=1)
    ug = version(conn, s, 555890, slot="guitar", kind="guitar-pro")
    keep_file(conn, cfg.library_dir, song=s, version_id=ug, name="guitar-2.gp5", data=b"gp5", rank=2)
    files = {f["name"]: f["label"] for f in songs_of(page(conn, cfg))["Blur - Song 2"]["files"]}
    assert files == {"guitar-1.gpx": "Guitar Pro 1 · gtptabs.com", "guitar-2.gp5": "Guitar Pro 2"}


def test_the_sheet_viewer_is_the_first_link_for_the_phone(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    put(cfg, s, "sheet.pdf", "sheet.html", "sheet.txt", "sheet (auto).html", "sheet (auto).pdf")
    files = songs_of(page(conn, cfg))[s.display]["files"]
    assert [(f["name"], f["label"], f["primary"]) for f in files] == [
        ("sheet.html", "Sheet viewer", True), ("sheet.pdf", "Sheet PDF", False),
        ("sheet (auto).html", "Auto sheet viewer", False), ("sheet (auto).pdf", "Auto sheet PDF", False),
        ("sheet.txt", "Sheet text", False)]
    auto = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, auto, "sheet (auto).pdf", "sheet (auto).html")
    files = songs_of(page(conn, cfg))[auto.display]["files"]
    assert [(f["name"], f["primary"]) for f in files] == [("sheet (auto).html", True), ("sheet (auto).pdf", False)]
    assert files[0]["href"].endswith("/sheet%20%28auto%29.html")


def test_only_files_that_exist_are_linked(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    v = version(conn, s, 4169)
    keep_file(conn, cfg.library_dir, song=s, version_id=v, name="tab.txt", data=b"tab", rank=1)
    (song_dir(cfg.library_dir, s) / "tab.txt").unlink()  # recorded in the database, gone from disk
    put(cfg, s, "lyrics.txt")
    assert [f["name"] for f in songs_of(page(conn, cfg))[s.display]["files"]] == ["lyrics.txt"]
    nowhere = add_song(conn, "Nobody", "No Folder")
    assert songs_of(page(conn, cfg))[nowhere.display]["files"] == []


def test_auto_sheets_are_linked_and_marked(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, s, "sheet (auto).txt", "sheet (auto).cho", "sheet (auto).pdf", "lyrics.txt")
    song = songs_of(page(conn, cfg))[s.display]
    hrefs = [unquote(f["href"]).rsplit("/", 1)[1] for f in song["files"]]
    assert hrefs == ["sheet (auto).pdf", "lyrics.txt", "sheet (auto).txt", "sheet (auto).cho"]
    assert song["files"][0]["href"].endswith("/sheet%20%28auto%29.pdf")
    assert song["files"][0]["primary"] is True
    assert song["auto"] is True


@pytest.mark.parametrize("artist,title,folder", [
    ("AC/DC", "Back in Black", "AC-DC/Back%20in%20Black"),
    ("John Lennon", "#9 Dream", "John%20Lennon/%239%20Dream"),
    ("4 Non Blondes", "What's Up?", "4%20Non%20Blondes/What%27s%20Up"),
])
def test_path_unsafe_names_link_to_the_folder_the_library_uses(conn, cfg, artist, title, folder):
    s = add_song(conn, artist, title)
    put(cfg, s, "lyrics.txt")
    href = songs_of(page(conn, cfg))[s.display]["files"][0]["href"]
    assert href == f"{folder}/lyrics.txt"
    assert (cfg.library_dir / unquote(href)).is_file()


# --- links for songs without a sheet ----------------------------------------------------


def test_songs_without_a_sheet_get_buy_and_search_links(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马，斑马")
    update_song(conn, s.id, match_decision="not_found")  # UG has nothing caracole can see
    found = add_song(conn, "Radiohead", "Creep")
    update_song(conn, found.id, status="found")
    put(cfg, found, "sheet.txt")
    ignored = add_song(conn, "Some Artist", "Some Interlude")
    update_song(conn, ignored.id, status="ignored")
    songs = songs_of(page(conn, cfg))
    expected = search_links("宋冬野", "斑马，斑马")
    links = {link["label"]: link["href"] for link in songs[s.display]["links"]}
    buy = {link["label"]: link["href"] for link in songs[s.display]["buy"]}
    assert links == {"Chordify": expected["chordify"], "YouTube": expected["youtube"]}
    assert buy == {"Bandcamp": expected["bandcamp"], "Qobuz": expected["qobuz"], "iTunes": expected["itunes"]}
    for song in (songs[found.display], songs[ignored.display]):
        assert song["links"] == [] and song["buy"] == []


def test_songs_caracole_will_still_look_for_get_no_buy_links(conn, cfg):
    # The to-do page's rule: no "buy the track" while a fetch, an artist page or LaCuerda is still to come.
    from caracole.db import kv_set

    waiting = add_song(conn, "Radiohead", "Creep")  # accepted, not fetched yet (33 UG tabs)
    update_song(conn, waiting.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    unmatched = add_song(conn, "Oasis", "Wonderwall")  # not matched yet
    spanish = add_song(conn, "Joaquín Sabina", "Y Nos Dieron las Diez")  # LaCuerda not asked yet
    update_song(conn, spanish.id, match_decision="not_found")
    pasted = add_song(conn, "宋冬野", "斑马斑马")  # its artist page was just pasted
    update_song(conn, pasted.id, match_decision="not_found")
    o = Overrides(artist_url={"宋冬野": "https://www.ultimate-guitar.com/artist/song_dongye_1234567"})
    songs = songs_of(page(conn, cfg, o))
    for s in (waiting, unmatched, spanish, pasted):
        assert songs[s.display]["buy"] == [], s.display
        assert [link["label"] for link in songs[s.display]["links"]] == ["Chordify", "YouTube"]
    update_song(conn, spanish.id, lacuerda_checked_at="2026-10-18T03:36:00Z")
    kv_set(conn, f"ug:artist_page_checked:{pasted.id}", "2026-10-18T03:35:00Z")
    update_song(conn, waiting.id, ug_dirty=False, ug_checked_at="2026-10-18T03:35:00Z")
    songs = songs_of(page(conn, cfg, o))
    for s in (waiting, spanish, pasted):
        assert [link["label"] for link in songs[s.display]["buy"]] == ["Bandcamp", "Qobuz", "iTunes"], s.display
    assert songs[unmatched.display]["buy"] == []


def test_a_song_whose_audio_you_have_gets_no_buy_links(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马斑马")
    update_song(conn, s.id, match_decision="not_found", audio_path="/music/斑马斑马.flac")
    assert songs_of(page(conn, cfg))[s.display]["buy"] == []


def test_with_the_youtube_route_on_a_card_says_where_its_audio_comes_from_and_offers_no_buying(
        conn, cfg, tmp_path, monkeypatch):
    from helpers.fake_ytdlp import route_on

    from caracole.db import kv_set_json

    on, _ = route_on(cfg, tmp_path, monkeypatch)
    queued = add_song(conn, "Radiohead", "Airbag")
    downloaded = add_song(conn, "Radiohead", "Creep")
    missing = add_song(conn, "Radiohead", "Let Down")
    declined = add_song(conn, "Blur", "Tender")
    for s in (queued, downloaded, missing, declined):
        update_song(conn, s.id, match_decision="not_found")
    audio = on.cache_dir / "youtube" / f"{downloaded.id}-XFkzRNyygfk.m4a"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"aac")
    update_song(conn, downloaded.id, audio_path=str(audio), audio_mtime=audio.stat().st_mtime)
    kv_set_json(conn, f"youtube:{downloaded.id}", {
        "video": {"id": "XFkzRNyygfk", "title": "Creep", "channel": "Radiohead - Topic"}, "source": "search",
        "audio": str(audio)})
    kv_set_json(conn, f"youtube:{missing.id}", {"missing_at": "2026-10-18T03:30:00Z"})
    songs = songs_of(page(conn, on, Overrides(youtube={declined.key: None})))
    assert songs[queued.display]["youtube"] == {
        "text": "No human sheet yet: caracole takes the audio from YouTube next", "video": None}
    assert songs[downloaded.display]["youtube"] == {
        "text": "Audio from YouTube: auto-chords works out the chords next",
        "video": {"label": "Creep (Radiohead - Topic)", "href": "https://www.youtube.com/watch?v=XFkzRNyygfk"}}
    assert songs[missing.display]["youtube"]["text"] == "Nothing on YouTube fits: see the to-do page"
    for s in (queued, downloaded, missing):
        assert songs[s.display]["buy"] == [], s.display
        assert [link["label"] for link in songs[s.display]["links"]] == ["Chordify", "YouTube"]
    assert songs[declined.display]["youtube"] is None  # you turned YouTube down: buying is the way
    assert [link["label"] for link in songs[declined.display]["buy"]] == ["Bandcamp", "Qobuz", "iTunes"]
    assert str(on.cache_dir) not in page(conn, on)  # where caracole keeps the audio is its own


def test_without_the_youtube_route_no_card_mentions_youtube_audio(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马，斑马")
    update_song(conn, s.id, match_decision="not_found")
    card = songs_of(page(conn, cfg))[s.display]
    assert card["youtube"] is None and card["buy"]


# --- songs that need review: their candidates ------------------------------------------------


def index_tabs(conn, *rows):
    """Rows of the UG index: (tab id, artist key, song key, type), at their slugged paths."""
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, '1', 'x', ?)",
        [(t, a, s, kind, f"{a}/{s}-{kind}-{t}") for t, a, s, kind in rows])


CREEP = [{"artist_key": "radiohead", "song_key": "creep", "score": 89.4, "step": "fuzzy_artist"},
         {"artist_key": "jeff-buckley", "song_key": "creep", "score": 80.0, "step": "title_only"},
         {"artist_key": "misc-musicals", "song_key": "creep-the-musical", "score": 76.0, "step": "catch_all"},
         {"artist_key": None, "song_key": "creep", "score": 70.0, "step": "fuzzy_artist"}]


def in_review(conn, artist="Radio Head", title="Crep", cands=CREEP):
    s = add_song(conn, artist, title)
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=cands)
    return s


def test_a_song_in_review_carries_its_candidates_as_caracole_review_lists_them(conn, cfg):
    index_tabs(conn, (1, "radiohead", "creep", "chords"), (2, "radiohead", "creep", "chords"),
               (3, "radiohead", "creep", "tabs"), (4, "the-radiohead", "x", "chords"),
               (5, "jeff-buckley", "creep", "guitar-pro"))
    s = in_review(conn)
    plain = add_song(conn, "Oasis", "Wonderwall")
    songs = songs_of(page(conn, cfg))
    assert songs[s.display]["candidates"] == [
        {"n": 1, "ref": "radiohead/creep", "artist": "Radiohead", "title": "Creep", "score": 89,
         "why": "artist spelled differently", "tabs": "Chords ×2 · Tabs ×1",
         "href": "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-1"},
        {"n": 2, "ref": "jeff-buckley/creep", "artist": "Jeff Buckley", "title": "Creep", "score": 80,
         "why": "title only: another artist's song, probably a cover", "tabs": "Guitar Pro ×1",
         "href": "https://tabs.ultimate-guitar.com/tab/jeff-buckley/creep-guitar-pro-5"},
        # Not in the index (any more): its names come from its keys, and it has no page to open.
        {"n": 3, "ref": "misc-musicals/creep-the-musical", "artist": "Misc Musicals", "title": "Creep The Musical",
         "score": 76, "why": "under UG's catch-all misc-musicals", "tabs": "", "href": ""},
    ]
    assert "candidates" not in songs[plain.display]


def test_an_ignored_song_in_review_has_no_candidates_to_pick(conn, cfg):
    s = in_review(conn)
    o = Overrides(ignore=frozenset({s.key}))
    assert "candidates" not in songs_of(page(conn, cfg, o))[s.display]


def test_a_song_not_found_says_so_for_the_served_card_to_look_in_the_index(conn, cfg):
    # Its search hits cost a search each, so the page carries none: caracole serve's /review runs it.
    lost = add_song(conn, "Radio Head", "Crep")
    update_song(conn, lost.id, match_decision="not_found")
    ignored = add_song(conn, "Nobody", "Nothing")
    update_song(conn, ignored.id, match_decision="not_found", status="ignored")
    plain = add_song(conn, "Oasis", "Wonderwall")
    songs = songs_of(page(conn, cfg))
    assert songs[lost.display]["notFound"] is True and "candidates" not in songs[lost.display]
    assert "notFound" not in songs[ignored.display] and "notFound" not in songs[plain.display]


def test_guitar_pro_pages_to_click_are_the_picks_without_files(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    v1 = version(conn, s, 555890, slot="guitar", kind="guitar-pro", ver=2, rating=4.2, votes=5)
    v2 = version(conn, s, 555891, slot="guitar", kind="power", ver=1, rating=4.0, votes=2)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v1, v2])
    keep_file(conn, cfg.library_dir, song=s, version_id=v2, name="guitar-2.ptb", data=b"pt", rank=2)
    gp = songs_of(page(conn, cfg))[s.display]["guitarPro"]
    assert [g["href"] for g in gp] == ["https://tabs.ultimate-guitar.com/tab/555890"]
    assert "Guitar Pro" in gp[0]["label"] and "ver 2" in gp[0]["label"] and "4.2" in gp[0]["label"]


def test_a_link_that_isnt_http_is_dropped(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    v = upsert_version(conn, provider="ug", tab_id="1", song_id=s.id, slot="guitar", kind="guitar-pro",
                       rating=4, votes=1, version=1, label=None, url="javascript:alert(1)", raw={}, now="x")
    set_picks(conn, s.id, ["guitar-pro"], [v])
    html = page(conn, cfg)
    assert songs_of(html)[s.display]["guitarPro"] == []
    assert "javascript:alert" not in html


# --- search haystack -------------------------------------------------------------------


def test_haystack_holds_folded_text_and_pinyin_for_han(conn, cfg):
    han = add_song(conn, "宋冬野", "斑马，斑马")
    accented = add_song(conn, "Soda Stereo", "De Música Ligera")
    initials = add_song(conn, "AC/DC", "Back in Black")
    songs = songs_of(page(conn, cfg))
    hay = songs[han.display]["search"]
    # fold() is NFKD, so the fullwidth comma is folded to "," on both sides (the page folds the query too).
    for needle in (fold("斑马，斑马"), "宋冬野", "斑马斑马", "ban ma ban ma", "banma", "song dong ye", "songdongye"):
        assert needle in hay
    assert "musica" in songs[accented.display]["search"] and "soda stereo" in songs[accented.display]["search"]
    assert "acdc" in songs[initials.display]["search"] and "ac/dc" in songs[initials.display]["search"]


def test_the_page_folds_queries_with_the_same_letters_as_the_haystack(conn, cfg):
    s = add_song(conn, "Røyksopp", "Ståle Straße")
    data = data_of(page(conn, cfg))
    assert "royksopp" in data["songs"][0]["search"] and "strasse" in data["songs"][0]["search"]
    assert data["fold"]["ø"] == "o" and data["fold"]["ß"] == "ss"
    assert s.display == data["songs"][0]["display"]


# --- safety and self-containment ------------------------------------------------------------


@pytest.mark.parametrize("title", [
    "</script><script>alert(1)</script>",
    "<!--<script>",
    "</SCRIPT >&amp; <b>bold</b>",
])
def test_a_title_cannot_break_out_of_the_json_block(conn, cfg, title):
    add_song(conn, "Evil", title)
    html = page(conn, cfg)
    block = JSON_BLOCK.findall(html)[0]
    assert "<" not in block  # no "</script", no "<!--": the HTML tokenizer can't leave the block
    assert data_of(html)["songs"][0]["title"] == title
    assert html.lower().count("<script") == 2 and html.lower().count("</script>") == 2


def test_no_external_resources_and_no_urls_outside_the_data(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马，斑马")
    v = version(conn, s, 555890, slot="guitar", kind="guitar-pro")
    set_picks(conn, s.id, ["guitar-pro"], [v])
    html = page(conn, cfg)
    # The CSP's hashes are base64, which may hold "//" before a letter: they are no addresses.
    shell = re.sub(r"'sha256-[A-Za-z0-9+/]+=*'", "'sha256'", JSON_BLOCK.sub("", html))
    assert not re.search(r"https?://|//[a-z]", shell, re.I)  # no CDN, fonts, images, fetches
    assert not re.search(r"<(link|img|iframe|object|embed)\b|\bsrc=|@import|url\(", shell, re.I)
    allowed = set(search_links("宋冬野", "斑马，斑马").values()) | {"https://tabs.ultimate-guitar.com/tab/555890"}
    assert set(re.findall(r'https?://[^"\s]+', JSON_BLOCK.findall(html)[0])) <= allowed


def test_the_content_security_policy_allows_exactly_the_inline_script_and_style(conn, cfg):
    html = page(conn, cfg)
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    styles = re.findall(r"<style>(.*?)</style>", html, re.S)
    assert len(scripts) == 1 and len(styles) == 1
    assert f"script-src {sha(scripts[0])}" in csp
    assert f"style-src {sha(styles[0])}" in csp


def test_the_page_has_no_invisible_characters(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    html = JSON_BLOCK.sub("", page(conn, cfg))
    invisible = "[" + chr(0x200B) + "-" + chr(0x200F) + chr(0x2028) + chr(0x2029) + chr(0xFEFF) + "]"
    assert not re.search(invisible, html)


def test_write_library_page(cfg):
    path = write_library_page(cfg.library_dir, "<!doctype html>\n")
    assert path == cfg.library_dir / "index.html"
    assert path.read_text(encoding="utf-8") == "<!doctype html>\n"


# --- where it is written -------------------------------------------------------------------


def config(tmp_path: Path) -> Path:
    p = tmp_path / "caracole.toml"
    p.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n',
        encoding="utf-8",
    )
    return p


def test_caracole_todo_also_writes_index_html(tmp_path):
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    add_song(conn, "宋冬野", "斑马，斑马")
    result = CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), "todo"])
    assert result.exit_code == 0, result.output
    html = (tmp_path / "lib" / "index.html").read_text(encoding="utf-8")
    assert "宋冬野 - 斑马，斑马" in [s["display"] for s in data_of(html)["songs"]]
    assert "index.html" in result.output and "_todo.md" in result.output


def test_the_nightly_todo_step_also_writes_index_html(conn, cfg):
    from caracole.notify import Notifier
    from caracole.pipeline import Services, default_steps, run_pipeline

    add_song(conn, "Radiohead", "Creep")
    todo = [s for s in default_steps() if s.name == "todo"]
    services = Services(clients={}, spotify=None, notifier=Notifier(None, None))
    report = run_pipeline(cfg, conn=conn, services=services, steps=todo, now=NOW)
    assert report.ok, report.errors
    html = (cfg.library_dir / "index.html").read_text(encoding="utf-8")
    assert [s["display"] for s in data_of(html)["songs"]] == ["Radiohead - Creep"]


# --- in a real browser ---------------------------------------------------------------------

NARROWEST_WINDOW = 500  # a --window-size narrower than this, headless Chromium widens to it


def dump_dom(path: Path, tmp_path: Path, fragment: str = "", size: str = "1280,900", *, touch: bool = False,
             media: dict[str, str] | None = None) -> str:
    """The page's DOM after its script ran, laid out in a window of ``size`` ("width,height"), in a
    browser context of its own (helpers/browser.py); skips the test when this machine can't run
    Chromium. A phone's width, narrower than any window, is laid out as a phone's screen; ``touch``,
    on a touch screen; ``media``, with media features such as ``{"prefers-color-scheme": "dark"}``."""
    width, height = (int(n) for n in size.split(","))
    return browser.dump_dom(path.as_uri() + fragment, (width, height), hide_scrollbars=True,
                            mobile=width < NARROWEST_WINDOW, touch=touch, media=media)


def listing(dom: str) -> str:
    """The rendered song list (the DOM dump also holds the page's own script text)."""
    found = re.search(r'<main[^>]*id="list"[^>]*>(.*?)</main>', dom, re.S)
    assert found, dom[-2000:]
    return found.group(1)


@in_chromium
def test_the_page_renders_and_filters_in_a_real_browser(conn, cfg, tmp_path):
    s = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, s, "lyrics.txt")
    add_song(conn, "Soda Stereo", "De Música Ligera")
    add_song(conn, "Radiohead", "Creep</script><b>x</b>")
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    shown = listing(dump_dom(path, tmp_path))
    assert shown.count("<article") == 3  # one card per song
    assert "Creep&lt;/script&gt;&lt;b&gt;x&lt;/b&gt;" in shown  # shown as text, never as markup
    assert "<b>x</b>" not in shown

    for query, title in (("ban ma", "斑马，斑马"), ("musica", "De Música Ligera"), ("MÚSICA", "De Música Ligera")):
        shown = listing(dump_dom(path, tmp_path, "#q=" + quote(query)))
        assert shown.count("<article") == 1, query
        assert title in shown


@in_chromium
def test_a_cards_youtube_note_links_its_video_in_a_real_browser(conn, cfg, tmp_path, monkeypatch):
    from helpers.fake_ytdlp import route_on

    from caracole.db import kv_set_json

    on, _ = route_on(cfg, tmp_path, monkeypatch)
    s = add_song(conn, "Radiohead", "Creep")
    audio = on.cache_dir / "youtube" / f"{s.id}-XFkzRNyygfk.m4a"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"aac")
    update_song(conn, s.id, match_decision="not_found", audio_path=str(audio), audio_mtime=audio.stat().st_mtime)
    kv_set_json(conn, f"youtube:{s.id}", {
        "video": {"id": "XFkzRNyygfk", "title": "Creep", "channel": "Radiohead - Topic"}, "source": "search",
        "audio": str(audio)})
    path = write_library_page(on.library_dir, page(conn, on))
    shown = listing(dump_dom(path, tmp_path))
    note = re.search(r'<p class="youtube">(.*?)</p>', shown, re.S)
    assert note, shown[-2000:]
    assert note.group(1).startswith("Audio from YouTube: auto-chords works out the chords next · <a")
    assert 'href="https://www.youtube.com/watch?v=XFkzRNyygfk"' in note.group(1)
    assert "Creep (Radiohead - Topic) ↗" in note.group(1) and 'rel="noopener noreferrer"' in note.group(1)


@in_chromium
def test_apostrophes_and_empty_results_in_a_real_browser(conn, cfg, tmp_path):
    add_song(conn, "Queen", "Don't Stop Me Now")
    oasis = add_song(conn, "Oasis", "Don’t Look Back in Anger")
    update_song(conn, oasis.id, status="found")
    add_song(conn, "Radiohead", "Creep")
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    # A phone's keyboard types curly apostrophes; the titles may have either kind.
    for query, title in (("don’t stop", "Don't Stop Me Now"), ("don't look", "Don’t Look Back in Anger")):
        shown = listing(dump_dom(path, tmp_path, "#q=" + quote(query)))
        assert shown.count("<article") == 1, query
        assert title in shown

    # A match hidden by the status filter is offered, not reported missing.
    shown = listing(dump_dom(path, tmp_path, "#show=found&q=creep"))
    assert shown.count("<article") == 0
    assert "Show all 1 match" in shown and "caracole search" not in shown

    # The suggested command is quoted for a shell.
    shown = listing(dump_dom(path, tmp_path, "#q=" + quote("guns n' roses")))
    assert "caracole search 'guns n'\\'' roses'" in shown


@in_chromium
def test_the_commands_the_file_names_quote_each_word_so_no_shell_expands_it(conn, cfg, tmp_path):
    # bash and zsh expand ! even in double quotes ("event not found"): each word goes in single quotes, each '
    # written '\'', as the Select bar's command writes them.
    import html as html_module
    import shlex

    artist, title = "Rock'n Band", 'Wow!Wow $HOME `id` "x"'
    in_review(conn, artist, title)
    lost = add_song(conn, "It's", "$5! `ls` \"y\"")
    update_song(conn, lost.id, match_decision="not_found")
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    shown = listing(dump_dom(path, tmp_path))
    codes = [html_module.unescape(c) for c in re.findall(r"<code>(.*?)</code>", shown, re.S)]
    review = [c for c in codes if c.startswith("caracole review --song")]
    assert review == ["caracole review --song 'It'\\''s - $5! `ls` \"y\"'",  # by artist
                      "caracole review --song 'Rock'\\''n Band - Wow!Wow $HOME `id` \"x\"'"]
    assert [shlex.split(c)[3] for c in review] == [lost.display, f"{artist} - {title}"]

    query = "It's $5! no such `song` \"z\""
    searched = listing(dump_dom(path, tmp_path, "#q=" + quote(query)))
    hint = [html_module.unescape(c) for c in re.findall(r"<code>(caracole search .*?)</code>", searched, re.S)]
    assert hint == ["caracole search 'It'\\''s $5! no such `song` \"z\"'"]
    assert shlex.split(hint[0]) == ["caracole", "search", query]


@in_chromium
def test_keys_show_with_their_source_and_filter_in_a_real_browser(conn, cfg, tmp_path):
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet_json(conn, cfg, soda, AM_F_C_G)
    creep = add_song(conn, "Radiohead", "Creep")
    keep_sheet_json(conn, cfg, creep, "Words\n", raw={"tonality_name": "G"}, tab_id=2)
    add_song(conn, "Queen", "Don't Stop Me Now")
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    dom = dump_dom(path, tmp_path)
    shown = listing(dom)
    assert "Key A minor (estimated from the chords)" in shown and "Key G major (from the tab)" in shown
    assert re.search(r'<option value="A minor"[^>]*>A minor', dom) and re.search(r'<option value="G"[^>]*>G major', dom)

    shown = listing(dump_dom(path, tmp_path, "#key=" + quote("A minor")))
    assert shown.count("<article") == 1 and "De Música Ligera" in shown

    shown = listing(dump_dom(path, tmp_path, "#key=G&q=soda"))
    assert shown.count("<article") == 0 and "No songs in G major match" in shown
    assert "caracole search" not in shown  # the key hides it, not the library

    shown = listing(dump_dom(path, tmp_path, "#q=" + quote("a minor")))
    assert shown.count("<article") == 1 and "De Música Ligera" in shown


@in_chromium
def test_a_key_typed_in_the_search_box_finds_that_key_only_in_a_real_browser(conn, cfg, tmp_path):
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet_json(conn, cfg, soda, AM_F_C_G)
    keyed = {("Radiohead", "Paranoid Android"): "Em", ("Muse", "Hysteria"): "F#m",
             ("Daft Punk", "Get Lucky"): "Fm", ("Queen", "Bohemian Rhapsody"): "Bb"}
    for tab_id, ((artist, title), key) in enumerate(keyed.items(), start=2):
        keep_sheet_json(conn, cfg, add_song(conn, artist, title), "Words\n", raw={"tonality_name": key},
                        tab_id=tab_id)
    add_song(conn, "The Beatles", "I Am the Walrus")  # no key, "am" in its name
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    def found(query):
        shown = listing(dump_dom(path, tmp_path, "#q=" + quote(query)))
        return sorted(re.findall(r"<h2>(.*?)</h2>", shown))

    # Paranoid Android is in a minor key and has an "a" in its name: still not A minor.
    assert found("a minor") == found("A Minor") == found("aminor") == ["De Música Ligera"]
    assert found("f# minor") == found("gb minor") == found("f#m") == found("F♯ minor") == ["Hysteria"]
    assert found("f minor") == found("fm") == ["Get Lucky"]
    assert found("bb major") == found("a# major") == ["Bohemian Rhapsody"]
    assert found("e minor android") == ["Paranoid Android"] and found("e minor lucky") == []
    assert found("minor") == ["De Música Ligera", "Get Lucky", "Hysteria", "Paranoid Android"]
    # A key written as a chord is a word too: "am" finds A minor and the names with "am" in them.
    assert found("am") == ["De Música Ligera", "I Am the Walrus"]
    shown = listing(dump_dom(path, tmp_path, "#q=" + quote("c major")))
    assert "No songs match" in shown and "caracole search" not in shown  # the index has no keys


@in_chromium
def test_the_key_menu_puts_the_spellings_of_one_key_together_in_a_real_browser(conn, cfg, tmp_path):
    keyed = {("Muse", "Hysteria"): "F#m", ("Radiohead", "Lucky"): "Gbm", ("Daft Punk", "Get Lucky"): "Fm",
             ("Queen", "Bohemian Rhapsody"): "Bb", ("Oasis", "Wonderwall"): "A#"}
    for tab_id, ((artist, title), key) in enumerate(keyed.items(), start=1):
        keep_sheet_json(conn, cfg, add_song(conn, artist, title), "Words\n", raw={"tonality_name": key},
                        tab_id=tab_id)
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    dom = dump_dom(path, tmp_path)
    menu = re.search(r'<select id="key">(.*?)</select>', dom, re.S).group(1)
    options = re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', menu)
    assert options == [("", "Any"), ("A#", "A# / Bb major · 2"), ("F minor", "F minor · 1"),
                       ("F# minor", "F# / Gb minor · 2")]
    # Each song keeps its own spelling.
    shown = listing(dom)
    assert "Key Gb minor (from the tab)" in shown and "Key F# minor (from the tab)" in shown

    for spelling in ("F# minor", "Gb minor"):  # an address with either spelling selects the key
        shown = listing(dump_dom(path, tmp_path, "#key=" + quote(spelling)))
        assert sorted(re.findall(r"<h2>(.*?)</h2>", shown)) == ["Hysteria", "Lucky"], spelling
    shown = listing(dump_dom(path, tmp_path, "#key=" + quote("F#") + "&q=lucky"))
    assert "No songs in F# major match" not in shown and shown.count("<article") == 2  # no such key: any


# A script the tests add to a copy of the page, allowed by its hash, to read the layout back.
MEASURE = """
(() => {
  const cards = Array.from(document.querySelectorAll("#list article"));
  const box = (node) => node.getBoundingClientRect();
  document.body.setAttribute("data-layout", JSON.stringify({
    tops: cards.map((c) => Math.round(box(c).top + window.scrollY)),
    widths: cards.map((c) => Math.round(box(c).width)),
    page: window.innerWidth,
    scroll: document.documentElement.scrollWidth,
  }));
})();
"""


def measured(html: str) -> str:
    csp = csp_of(html)
    html = html.replace(csp, csp.replace("script-src ", f"script-src {sha(MEASURE)} "))
    return html.replace("</body>", f"<script>{MEASURE}</script>\n</body>")


def layout_of(dom: str) -> dict:
    import html as html_module

    found = re.search(r'data-layout="([^"]*)"', dom)
    assert found, dom[-2000:]
    return json.loads(html_module.unescape(found.group(1)))


@in_chromium
def test_cards_fill_a_desktop_row_and_stack_on_a_phone(conn, cfg, tmp_path):
    # One song per artist: each artist used to get a section of its own, one narrow card wide.
    for artist, title in (("Radiohead", "Creep"), ("Soda Stereo", "De Música Ligera"), ("Oasis", "Wonderwall"),
                          ("宋冬野", "斑马，斑马")):
        add_song(conn, artist, title)
    path = write_library_page(cfg.library_dir, measured(page(conn, cfg)))

    wide = layout_of(dump_dom(path, tmp_path, size="1280,900"))
    assert wide["page"] == 1280, wide  # laid out at the width asked for
    assert len(wide["tops"]) == 4
    assert wide["tops"].count(wide["tops"][0]) >= 3, wide  # at least three cards share the first row
    assert wide["scroll"] <= wide["page"]

    phone = layout_of(dump_dom(path, tmp_path, size="390,844"))
    assert phone["page"] == 390, phone  # a phone's width, not headless Chromium's narrowest window
    assert len(set(phone["tops"])) == 4, phone  # one card per row
    assert phone["scroll"] <= phone["page"], phone  # nothing wider than the screen
    assert all(w >= phone["page"] - 40 for w in phone["widths"]), phone


@in_chromium
def test_the_letter_strip_lists_the_artists_initials(conn, cfg, tmp_path):
    for artist, title in (("The Beatles", "Yesterday"), ("Radiohead", "Creep"), ("Soda Stereo", "Música"),
                          ("宋冬野", "斑马，斑马")):
        add_song(conn, artist, title)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    dom = dump_dom(path, tmp_path)
    strip = re.search(r'<nav[^>]*id="jump"[^>]*>(.*?)</nav>', dom, re.S)
    assert strip, dom[-2000:]
    assert re.findall(r"<button[^>]*>([^<]+)</button>", strip.group(1)) == ["B", "R", "S"]
    shown = listing(dump_dom(path, tmp_path, "#sort=recent"))
    assert shown.count("<article") == 4
    assert re.search(r'<nav[^>]*id="jump"[^>]*hidden', dump_dom(path, tmp_path, "#sort=recent"))


@in_chromium
def test_the_served_page_offers_a_fetch_for_wanted_songs(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    wanted = add_song(conn, "Radiohead", "Creep")
    busy = add_song(conn, "Oasis", "Wonderwall")
    found = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, found.id, status="found")
    held = add_song(conn, "Queen", "Bohemian Rhapsody")
    update_song(conn, held.id, review=True)
    controls = WebControls(csrf="tok", busy=frozenset({busy.id}), active=1, held=frozenset({held.id}))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    path = write_library_page(cfg.library_dir, html)
    shown = listing(dump_dom(path, tmp_path))
    forms = re.findall(r'<form[^>]*action="/fetch"[^>]*>(.*?)</form>', shown, re.S)
    assert len(forms) == 1
    assert f'name="song" value="{wanted.id}"' in forms[0] and 'name="csrf" value="tok"' in forms[0]
    assert "Fetching" in shown  # the song with a job queued says so instead
    # The song caracole fetch would refuse until it's reviewed says so instead of offering a fetch.
    card = re.search(r"<article[^>]*>(?:(?!</article>).)*Bohemian Rhapsody.*?</article>", shown, re.S).group(0)
    assert re.search(r"<button[^>]*disabled[^>]*>Review first</button>", card) and "/fetch" not in card


@in_chromium
def test_the_served_page_offers_a_remove_on_every_card(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    wanted = add_song(conn, "Radiohead", "Creep")
    found = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, found.id, status="found")
    ignored = add_song(conn, "Queen", "Bohemian Rhapsody")
    update_song(conn, ignored.id, status="ignored")
    going = add_song(conn, "Oasis", "Wonderwall")
    controls = WebControls(csrf="tok", removing=frozenset({going.id}))
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW, controls=controls))
    shown = listing(dump_dom(path, tmp_path))
    forms = re.findall(r'<form[^>]*action="/remove"[^>]*>(.*?)</form>', shown, re.S)
    assert sorted(re.search(r'name="song" value="(\d+)"', f).group(1) for f in forms) == sorted(
        str(s.id) for s in (wanted, found, ignored))
    assert all('name="csrf" value="tok"' in f and "Remove…" in f for f in forms)
    assert 'aria-label="Remove Creep by Radiohead from caracole"' in shown
    card = re.search(r"<article[^>]*>(?:(?!</article>).)*Wonderwall.*?</article>", shown, re.S).group(0)
    assert "Removing…" in card and "/remove" not in card
    assert "/fetch" not in card  # a fetch now would run before the removal and fetch for nothing
    # The page on disk has no server to remove anything.
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW))
    assert "/remove" not in listing(dump_dom(path, tmp_path))


# Notes how a card's Removing… note and a card's Fetching… line look.
LOOKS = """
(() => {
  const look = (node) => {
    const style = getComputedStyle(node);
    return [style.marginTop, style.marginBottom, style.color, style.fontWeight].join(" ");
  };
  const removing = document.querySelector(".foot .busy");
  const fetching = document.querySelector(".progress");
  document.body.setAttribute("data-removing", removing ? look(removing) : "none");
  document.body.setAttribute("data-fetching", fetching ? look(fetching) : "none");
})();
"""


@in_chromium
def test_a_cards_removing_note_looks_like_its_fetching_line(conn, cfg, tmp_path):
    # Remove's note in the card's foot and the request's line above it are both "something runs": one look,
    # with no paragraph margins that push the foot down.
    from caracole.library_page import WebControls

    fetching = add_song(conn, "Oasis", "Wonderwall")
    going = add_song(conn, "The Beatles", "Yesterday")
    controls = WebControls(csrf="tok", busy=frozenset({fetching.id}), active=2, removing=frozenset({going.id}))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(html, LOOKS)), tmp_path)
    removing = re.search(r'<body[^>]*data-removing="([^"]*)"', dom).group(1)
    line = re.search(r'<body[^>]*data-fetching="([^"]*)"', dom).group(1)
    assert removing != "none" and line != "none", dom[-1500:]
    top, bottom, *color, weight = removing.split(" ")
    assert (top, bottom) == ("0px", "0px")
    assert color == line.split(" ")[2:-1] and int(weight) >= 600


def with_script(html: str, script: str) -> str:
    """The page with a test's script after its own, allowed by its hash."""
    csp = csp_of(html)
    html = html.replace(csp, csp.replace("script-src ", f"script-src {sha(script)} "))
    return html.replace("</body>", f"<script>{script}</script>\n</body>")


# Clicks the A-Z strip's "R" and notes which card has the focus then.
JUMP = """
(() => {
  const r = Array.from(document.querySelectorAll("#jump button")).find((b) => b.textContent === "R");
  r.click();
  const card = document.activeElement.closest("article");
  document.body.setAttribute("data-focus", card ? card.querySelector("h2").textContent : "none");
})();
"""


@in_chromium
def test_a_screen_reader_hears_each_cards_song_and_a_jump_moves_the_focus(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    add_song(conn, "The Beatles", "Yesterday")
    add_song(conn, "Radiohead", "Creep")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    path = write_library_page(cfg.library_dir, with_script(html, JUMP))
    dom = dump_dom(path, tmp_path)
    shown = listing(dom)
    # The cards' titles are headings under the page's h1, and each button names its song.
    assert re.findall(r"<h2>([^<]+)</h2>", shown) == ["Yesterday", "Creep"] and "<h3" not in shown
    assert 'aria-label="Fetch Creep by Radiohead now"' in shown
    assert 'aria-label="Fetch Yesterday by The Beatles now"' in shown
    # After a jump, the next Tab goes on from the card jumped to, not from the strip.
    assert re.search(r'<body[^>]*data-focus="Creep"', dom), dom[-1500:]


# Clicks the artist under the first card titled "Bohemian Rhapsody", then notes the titles shown and the chip.
ARTIST_CLICK = """
(() => {
  const card = Array.from(document.querySelectorAll("#list article"))
    .find((c) => c.querySelector("h2").textContent === "Bohemian Rhapsody");
  card.querySelector("button.artist").click();
  const titles = Array.from(document.querySelectorAll("#list article h2")).map((h) => h.textContent);
  const chip = document.getElementById("artist");
  document.body.setAttribute("data-after", JSON.stringify({titles, chip: chip.hidden ? null : chip.textContent,
    q: document.getElementById("q").value, hash: location.hash}));
  chip.click();
  document.body.setAttribute("data-cleared", String(document.querySelectorAll("#list article").length));
})();
"""


@in_chromium
def test_an_artists_name_shows_that_artist_alone_not_every_song_with_the_word(conn, cfg, tmp_path):
    import html as html_module

    add_song(conn, "Queen", "Bohemian Rhapsody")
    add_song(conn, "Queen", "Don't Stop Me Now")
    add_song(conn, "ABBA", "Dancing Queen")
    add_song(conn, "Queens of the Stone Age", "No One Knows")
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), ARTIST_CLICK))
    dom = dump_dom(path, tmp_path)
    after = json.loads(html_module.unescape(re.search(r'data-after="([^"]*)"', dom).group(1)))
    assert sorted(after["titles"]) == ["Bohemian Rhapsody", "Don't Stop Me Now"], after
    assert after["chip"].startswith("Queen") and after["q"] == "" and "artist=queen" in after["hash"]
    assert re.search(r'data-cleared="4"', dom)  # the chip takes the filter off

    # The address keeps the filter, as it keeps the search.
    plain = write_library_page(cfg.library_dir, page(conn, cfg))
    shown = listing(dump_dom(plain, tmp_path, "#artist=queen"))
    assert shown.count("<article") == 2 and "Dancing Queen" not in shown
    # A search that only another artist's songs answer says the filter is on, and offers to take it off.
    shown = listing(dump_dom(plain, tmp_path, "#artist=queen&q=dancing"))
    assert "No songs of Queen match “dancing”" in shown and "every artist" in shown
    assert "caracole search" not in shown


# --- the picker: a song in review's candidates, in a real browser -------------------------------


def card_of(shown: str, title: str) -> str:
    """The rendered card whose heading is ``title``."""
    for card in re.findall(r"<article[^>]*>.*?</article>", shown, re.S):
        if f"<h2>{title}</h2>" in card:
            return card
    raise AssertionError(f"no card {title!r} in {shown[-1500:]}")


@in_chromium
def test_the_file_shows_a_reviews_candidates_and_the_line_that_picks_one(conn, cfg, tmp_path):
    index_tabs(conn, (1, "radiohead", "creep", "chords"), (3, "radiohead", "creep", "tabs"))
    in_review(conn)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    card = card_of(listing(dump_dom(path, tmp_path)), "Crep")
    picker = re.search(r'<details class="picker">.*?</details>', card, re.S).group(0)
    assert re.search(r"<summary[^>]*>3 candidates</summary>", picker)
    names = re.findall(r'<span class="choice-name">([^<]*)</span>', picker)
    assert names == ["1. Radiohead – Creep", "2. Jeff Buckley – Creep", "3. Misc Musicals – Creep The Musical"]
    assert "artist spelled differently · score 89 · Chords ×1 · Tabs ×1" in picker
    assert 'href="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-1"' in picker
    assert 'target="_blank"' in picker and 'rel="noopener noreferrer"' in picker
    assert picker.count('class="choice-link"') == 1  # the candidate the index no longer has links nowhere
    assert "<code>caracole review --song 'Radio Head - Crep'</code>" in picker
    assert "<form" not in card and "<input" not in card  # the file sends nothing


@in_chromium
def test_the_served_page_picks_a_candidate_with_a_form_in_place_of_review_first(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    s = in_review(conn)
    bare = add_song(conn, "Queen", "Bohemian Rhapsody")  # in review with no candidate to pick
    update_song(conn, bare.id, review=True)
    controls = WebControls(csrf='t"k', held=frozenset({s.id, bare.id}))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    shown = listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path))
    card = card_of(shown, "Crep")
    assert "Review first" not in card and "/fetch" not in card
    assert re.search(r'<summary class="btn picker-open"[^>]*>Pick the match', card)
    form = re.search(r'<form[^>]*action="/review"[^>]*>(.*?)</form>', card, re.S)
    assert form and 'method="post"' in form.group(0)
    fields = form.group(1)
    assert 'name="csrf" value="t&quot;k"' in fields and f'name="song" value="{s.id}"' in fields
    assert 'name="shown" value="radiohead/creep jeff-buckley/creep misc-musicals/creep-the-musical"' in fields
    radios = re.findall(r'<input type="radio" name="pick" value="([^"]*)" required="">', fields)
    assert radios == ["radiohead/creep", "jeff-buckley/creep", "misc-musicals/creep-the-musical", "none"]
    assert re.search(r"<fieldset[^>]*><legend>Which Ultimate Guitar song is “Crep” by Radio Head\?</legend>", fields)
    assert re.search(r'<input type="checkbox" name="fetch" value="1" checked="">', fields)
    assert re.search(r'<button[^>]*type="submit"[^>]*>Pick</button>', fields)
    assert "None of these" in fields
    # A review with no candidate keeps its note and the button that says why it can't be fetched.
    plain = card_of(shown, "Bohemian Rhapsody")
    assert re.search(r"<button[^>]*disabled[^>]*>Review first</button>", plain) and "picker" not in plain


@in_chromium
def test_the_served_picker_of_a_song_being_fetched_is_read_only_until_its_request_ends(conn, cfg, tmp_path):
    # POST /review would refuse a pick while the song's request waits or runs: the card offers none.
    from caracole.library_page import WebControls

    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    s = in_review(conn)
    controls = WebControls(csrf="tok", busy=frozenset({s.id}), active=1, held=frozenset({s.id}))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    card = card_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
    # The card's one form is its foot's Remove…: no pick, and no input but Remove's.
    assert re.findall(r'<form[^>]*action="([^"]*)"', card) == ["/remove"]
    picker = re.search(r'<details class="picker">.*?</details>', card, re.S).group(0)
    assert "<input" not in picker and "<input" not in card.replace(re.search(
        r'<form[^>]*action="/remove".*?</form>', card, re.S).group(0), "")
    choices = re.search(r'<ol class="choices"[^>]*>(.*?)</ol>', picker, re.S)
    assert choices and re.findall(r'<span class="choice-name">([^<]*)</span>', choices.group(1)) == [
        "1. Radiohead – Creep", "2. Jeff Buckley – Creep", "3. Misc Musicals – Creep The Musical"]
    assert '<p class="pick-hint">A request for this song is running: pick one once it ends.</p>' in picker
    assert "Fetching…" in card


@in_chromium
def test_the_served_picker_is_read_only_while_any_request_of_its_song_waits(conn, cfg, tmp_path):
    # POST /review refuses a pick while any request of the song waits or runs, not only a fetch: a pick
    # without Fetch it now, say, or an add. The card's line says how that request goes; the picker waits.
    from caracole.library_page import WebControls

    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    s = in_review(conn)
    job = {"id": 4, "display": "Radio Head - Crep", "songId": s.id, "state": "queued", "fetching": False,
           "line": {"tone": "queued", "text": "Queued behind 1 request…", "link": None, "details": None},
           "details": "jobs?job=4#job-4"}
    controls = WebControls(csrf="tok", active=2, held=frozenset({s.id}), jobs=(job,))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    card = card_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
    assert re.findall(r'<form[^>]*action="([^"]*)"', card) == ["/remove"]
    picker = re.search(r'<details class="picker">.*?</details>', card, re.S).group(0)
    assert "<input" not in picker
    assert '<p class="pick-hint">A request for this song is running: pick one once it ends.</p>' in picker
    assert card.index('class="progress"') < card.index('class="picker"')  # its line, above the picker


@in_chromium
def test_a_found_song_in_review_gets_the_picker_too(conn, cfg, tmp_path):
    # A sheet from elsewhere (LaCuerda, say) while its UG match waits for review: no Fetch now, but a pick.
    from caracole.library_page import WebControls

    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    s = in_review(conn)
    update_song(conn, s.id, status="found")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", held=frozenset({s.id})))
    card = card_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
    assert 'data-status="found"' in card and "/fetch" not in card
    form = re.search(r'<form[^>]*action="/review"[^>]*>(.*?)</form>', card, re.S)
    assert form and f'name="song" value="{s.id}"' in form.group(1)
    radios = re.findall(r'<input type="radio" name="pick" value="([^"]*)"', form.group(1))
    assert radios == ["radiohead/creep", "jeff-buckley/creep", "misc-musicals/creep-the-musical", "none"]


# Opens the first picker by its summary, as a click or Enter does, then notes where the focus went.
OPEN_PICKER = """
(() => {
  const picker = document.querySelector("#list details.picker");
  picker.querySelector("summary").click();
  setTimeout(() => {
    const focus = document.activeElement;
    document.body.setAttribute("data-picker", JSON.stringify({
      open: picker.open,
      focus: focus ? (focus.name || "") + "=" + (focus.value || "") : "none",
      inPicker: picker.contains(focus),
      width: document.documentElement.scrollWidth, page: window.innerWidth,
    }));
  }, 50);
})();
"""


# --- where each file came from: the sites' icons ----------------------------------------------


def test_each_file_says_where_it_came_from_and_the_song_where_its_sheet_did(conn, cfg):
    from caracole.lacuerda_fetch import SHEET_DOCS

    ug = add_song(conn, "Radiohead", "Creep")
    keep_sheet_json(conn, cfg, ug, "Words\n")
    gtp = upsert_version(conn, provider="gtptabs", tab_id="12", song_id=ug.id, slot="guitar", kind="guitar-pro",
                         rating=4, votes=0, version=1, label=None, url="https://gtptabs.com/tabs/r/creep.html",
                         raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=ug, version_id=gtp, name="guitar-1.gp5", data=b"gp5", rank=1)
    score = upsert_version(conn, provider="inbox", tab_id="score", song_id=ug.id, slot="guitar", kind="score",
                           rating=0, votes=0, version=1, label=None, url="", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=ug, version_id=score, name="score-1.mscz", data=b"ms", rank=1)
    put(cfg, ug, "sheet.pdf", "sheet.cho", "lyrics.txt", "lyrics.lrc", "info.json")
    spanish = add_song(conn, "Soda Stereo", "De Música Ligera")
    lc = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/de_musica_ligera", song_id=spanish.id,
                        slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                        url="https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml", raw={}, now="x")
    for name in SHEET_DOCS:
        keep_file(conn, cfg.library_dir, song=spanish, version_id=lc, name=name, data=name.encode(), rank=1)
    auto = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, auto, "sheet (auto).txt", "sheet (auto).pdf")
    wanted = add_song(conn, "Oasis", "Wonderwall")

    songs = songs_of(page(conn, cfg))
    files = {f["name"]: f.get("source") for f in songs[ug.display]["files"]}
    assert files == {"sheet.pdf": "ug", "sheet.txt": "ug", "sheet.cho": "ug", "lyrics.txt": "lrclib",
                     "lyrics.lrc": "lrclib", "guitar-1.gp5": "gtptabs", "score-1.mscz": "inbox", "info.json": None}
    assert songs[ug.display]["source"] == "ug"
    assert songs[spanish.display]["source"] == "lacuerda"
    assert songs[auto.display]["source"] == "auto"
    assert {f["name"]: f["source"] for f in songs[auto.display]["files"]} == {
        "sheet (auto).pdf": "auto", "sheet (auto).txt": "auto"}
    assert songs[wanted.display]["source"] is None


def test_a_song_whose_first_link_is_its_viewer_shows_where_its_sheet_came_from(conn, cfg):
    # The viewer is a song's first link, so the song's mark (on its card and its row) is the
    # viewer's source: the sheet it was rendered from, never none.
    ug = add_song(conn, "Radiohead", "Creep")
    keep_sheet_json(conn, cfg, ug, "Words\n")
    put(cfg, ug, "sheet.html", "sheet.pdf", "sheet.cho")
    auto = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, auto, "sheet (auto).txt", "sheet (auto).html", "sheet (auto).pdf")

    songs = songs_of(page(conn, cfg))
    files = {f["name"]: f.get("source") for f in songs[ug.display]["files"]}
    assert files["sheet.html"] == "ug"
    assert next(f for f in songs[ug.display]["files"] if f["primary"])["name"] == "sheet.html"
    assert songs[ug.display]["source"] == "ug"
    assert {f["name"]: f["source"] for f in songs[auto.display]["files"]}["sheet (auto).html"] == "auto"
    assert songs[auto.display]["source"] == "auto"


def test_links_to_other_sites_name_them(conn, cfg):
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    v = version(conn, s, 555890, slot="guitar", kind="guitar-pro")
    set_picks(conn, s.id, ["guitar-pro"], [v])
    song = songs_of(page(conn, cfg))[s.display]
    assert [g["source"] for g in song["guitarPro"]] == ["ug"]
    assert {link["label"]: link.get("source") for link in song["links"]} == {"Chordify": None, "YouTube": "youtube"}


def test_the_page_inlines_the_icons_kept_and_allows_images_from_data_alone(conn, cfg):
    from helpers.icon_files import png

    from caracole import icons

    icons.keep_icon(cfg.cache_dir, "ug", icons.sanitize(png(32)))
    html = page(conn, cfg)
    shown = data_of(html)["icons"]
    assert shown["ug"]["src"] == icons.icon_uri(cfg.cache_dir, "ug")
    assert shown["lacuerda"] == {"name": "LaCuerda", "letters": "LC"}  # its badge, until it has an icon
    assert shown["auto"]["glyph"] is True
    csp = csp_of(html)
    assert "img-src data:;" in csp + ";" and "default-src 'none'" in csp
    assert not re.search(r"data:image/png;base64,[A-Za-z0-9+/]", JSON_BLOCK.sub("", html))  # only in the data


def sourced_library(conn, cfg):
    """Creep's sheet from UG (whose icon is kept), De Música Ligera's from LaCuerda (no icon yet),
    斑马，斑马's from the audio model, and Wonderwall wanted."""
    from helpers.icon_files import png

    from caracole import icons
    from caracole.lacuerda_fetch import SHEET_DOCS

    icons.keep_icon(cfg.cache_dir, "ug", icons.sanitize(png(32)))
    creep = add_song(conn, "Radiohead", "Creep")
    keep_sheet_json(conn, cfg, creep, "Words\n", raw={"tonality_name": "G"})
    put(cfg, creep, "sheet.pdf", "lyrics.txt")
    update_song(conn, creep.id, status="found")
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    lc = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/de_musica_ligera", song_id=soda.id,
                        slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                        url="https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml", raw={}, now="x")
    for name in SHEET_DOCS:
        data = AM_F_C_G.encode() if name.endswith(".txt") else json.dumps({"content": AM_F_C_G}).encode()
        keep_file(conn, cfg.library_dir, song=soda, version_id=lc, name=name, data=data, rank=1)
    update_song(conn, soda.id, status="found")
    auto = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, auto, "sheet (auto).txt")
    update_song(conn, auto.id, status="found")
    add_song(conn, "Oasis", "Wonderwall")
    return creep


# Notes each icon on the page: its source, its accessible name, and whether the image loaded.
MARKS = """
(() => {
  const marks = Array.from(document.querySelectorAll("#list .source")).map((m) => ({
    source: m.dataset.source, tag: m.tagName.toLowerCase(), text: m.textContent,
    name: m.getAttribute("alt") || m.getAttribute("aria-label"), role: m.getAttribute("role"),
    loaded: m.tagName === "IMG" ? m.complete && m.naturalWidth > 0 : null,
    link: m.closest("a") ? m.closest("a").textContent : null,
    width: m.getBoundingClientRect().width, font: parseFloat(getComputedStyle(m).fontSize),
    colour: getComputedStyle(m).color, text_colour: getComputedStyle(document.body).color,
  }));
  document.body.setAttribute("data-marks", JSON.stringify(marks));
})();
"""


@in_chromium
def test_opening_the_picker_takes_the_focus_to_its_first_candidate_and_fits_a_phone(conn, cfg, tmp_path):
    import html as html_module

    from caracole.library_page import WebControls

    in_review(conn, "Los Fabulosos Cadillacs y Los Auténticos Decadentes", "Matador (versión acústica en vivo)")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    path = write_library_page(cfg.library_dir, with_script(html, OPEN_PICKER))
    dom = dump_dom(path, tmp_path, size="390,844")
    found = re.search(r'data-picker="([^"]*)"', dom)
    assert found, dom[-2000:]
    state = json.loads(html_module.unescape(found.group(1)))
    assert state["open"] and state["inPicker"] and state["focus"] == "pick=radiohead/creep", state
    assert state["width"] <= state["page"], state  # nothing wider than the phone


@in_chromium
def test_the_served_card_of_a_song_not_found_links_to_its_search_hits(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    lost = add_song(conn, "Radio Head", "Crep")
    update_song(conn, lost.id, match_decision="not_found")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    card = card_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
    assert re.search(rf'<a class="btn" href="/review\?song={lost.id}"[^>]*>Look in the index</a>', card)
    assert "/fetch" in card  # its artist's UG page may have it: Fetch now still asks
    on_file = card_of(listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path)), "Crep")
    assert "/review" not in on_file
    # The file can't search: it names the line that lists the hits, numbered as --pick takes them.
    hint = re.search(r'<p class="pick-hint">(.*?)</p>', on_file, re.S)
    assert hint and "<code>caracole review --song 'Radio Head - Crep'</code>" in hint.group(1), on_file
    assert "caracole search finds for it" in hint.group(1)


def marks_of(dom: str) -> list[dict]:
    import html as html_module

    found = re.search(r'data-marks="([^"]*)"', dom)
    assert found, dom[-2000:]
    return json.loads(html_module.unescape(found.group(1)))


@in_chromium
def test_each_file_shows_its_sites_icon_or_badge_in_a_real_browser(conn, cfg, tmp_path):
    sourced_library(conn, cfg)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), MARKS))
    marks = marks_of(dump_dom(path, tmp_path))
    ug = [m for m in marks if m["source"] == "ug"]
    assert ug and all(m["tag"] == "img" and m["loaded"] and m["name"] == "from Ultimate Guitar" for m in ug), ug
    # The card says once where its sheet came from; its files from there carry no mark of their own...
    assert [m["link"] for m in ug] == [None], ug
    # ...and a file from elsewhere does, as the link's last word: "Lyrics from LRCLIB".
    assert any(m["source"] == "lrclib" and m["link"] == "LyricsLR" for m in marks), marks
    lc = [m for m in marks if m["source"] == "lacuerda"]
    assert lc and all(m["tag"] == "span" and m["role"] == "img" and m["text"] == "LC" and
                      m["name"] == "from LaCuerda" for m in lc), lc
    assert any(m["source"] == "lrclib" and m["text"] == "LR" for m in marks)
    assert any(m["source"] == "auto" and m["text"] == "♪" and m["name"] == "from the audio (auto-chords)"
               for m in marks)
    assert any(m["source"] == "youtube" for m in marks)  # Wonderwall's search link
    # A site's icon is 16 px; its badge, there until the icon is in, is bigger, its letters
    # big enough to read and in the text's own colour.
    assert {m["width"] for m in ug} == {16}, ug
    badges = [m for m in marks if m["tag"] == "span"]
    assert badges and all(m["width"] >= 18 and m["font"] >= 10 for m in badges), badges
    assert all(m["colour"] == m["text_colour"] for m in badges if m["text"] in ("LC", "LR", "YT")), badges


# --- a song's title opens its sheet, as its row's button, the primary one, does ------------------------


def filed_library(conn, cfg):
    """Creep, found, with every kind of file and a Guitar Pro version to download; Wonderwall, found, its
    PDF alone; The Underworld, wanted and in review (two badges); Yesterday, wanted, with no file."""
    creep = add_song(conn, "Radiohead", "Creep")
    keep_sheet_json(conn, cfg, creep, "Words\n", raw={"tonality_name": "G"})
    put(cfg, creep, "sheet.html", "sheet.pdf", "sheet.cho", "lyrics.txt", "lyrics.lrc", "guitar-1.gp5", "tab.txt",
        "info.json")
    set_picks(conn, creep.id, ["guitar-pro"], [version(conn, creep, 555890, slot="guitar", kind="guitar-pro")])
    update_song(conn, creep.id, status="found")
    wonderwall = add_song(conn, "Oasis", "Wonderwall")
    put(cfg, wonderwall, "sheet.pdf")
    update_song(conn, wonderwall.id, status="found")
    underworld = add_song(conn, "Epic", "The Underworld")
    update_song(conn, underworld.id, review=True)
    add_song(conn, "The Beatles", "Yesterday")
    return creep


def served_auto_sheet(conn, cfg):
    """斑马，斑马, wanted, with an auto sheet, on the page caracole serve serves."""
    from caracole.library_page import WebControls

    s = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, s, "sheet (auto).txt", "sheet (auto).html", "sheet (auto).pdf")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    return write_library_page(cfg.library_dir, html)


AUTO_VIEWER = r'href="[^"]*/sheet%20%28auto%29\.html"'


def link_texts(html: str) -> list[str]:
    """The text of each button-like link (its label, before any mark of where it came from)."""
    return re.findall(r'<a class="btn[^"]*"[^>]*>([^<]*)', html)


@in_chromium
def test_a_songs_title_opens_its_sheet_on_its_card_and_its_row_whose_button_is_the_primary_one(conn, cfg,
                                                                                               tmp_path):
    filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    cards = listing(dump_dom(path, tmp_path))
    # The title opens the viewer, else the PDF: out of the Tab order, as the card's button opens the same.
    title = re.search(r'<a class="title-link" ([^>]*)><h2>Creep</h2></a>', card_of(cards, "Creep"))
    assert title and 'href="Radiohead/Creep/sheet.html"' in title.group(1) and 'tabindex="-1"' in title.group(1)
    wonderwall = card_of(cards, "Wonderwall")
    assert re.search(r'<a class="title-link" href="Oasis/Wonderwall/sheet.pdf"[^>]*><h2>Wonderwall</h2></a>',
                     wonderwall), wonderwall
    assert "title-link" not in card_of(cards, "Yesterday")  # no file: a plain title

    rows = listing(dump_dom(path, tmp_path, "#view=rows"))
    creep = row_of(rows, "Creep")
    title = re.search(r'<a class="title-link" ([^>]*)><h2 class="row-title"[^>]*>Creep</h2></a>', creep)
    assert title and 'href="Radiohead/Creep/sheet.html"' in title.group(1) and 'tabindex="-1"' in title.group(1)
    # The row's button opens the same, and is the primary one, as Fetch now is on a wanted song's row.
    main = re.search(r'<div class="row-action"><a class="btn small primary" ([^>]*)>Sheet viewer</a>', creep)
    assert main and 'href="Radiohead/Creep/sheet.html"' in main.group(1), creep
    assert 'aria-label="Sheet viewer of Creep by Radiohead"' in main.group(1)
    assert "title-link" not in row_of(rows, "Yesterday")


# Notes how each row is laid out: how tall its title's link is against its button, how many lines its title
# takes, and its button's colour against a primary button's.
ROW_LAYOUT = """
(() => {
  const box = (n) => n.getBoundingClientRect();
  const rows = {};
  for (const r of document.querySelectorAll("#list .row")) {
    const h2 = r.querySelector("h2");
    const title = r.querySelector(".title-link");
    const main = r.querySelector(".row-action > a");
    rows[h2.textContent] = {
      title: title ? Math.round(box(title).height) : null,
      button: main ? Math.round(box(main).height) : null,
      lines: Math.round(box(h2).height / parseFloat(getComputedStyle(h2).lineHeight)),
      colour: main ? getComputedStyle(main).backgroundColor : null,
    };
  }
  const primary = document.createElement("a");
  primary.className = "btn primary";
  document.body.appendChild(primary);
  document.body.setAttribute("data-rows", JSON.stringify({ rows, accent: getComputedStyle(primary).backgroundColor,
    page: innerWidth, scroll: document.documentElement.scrollWidth }));
  primary.remove();
})();
"""


@pytest.mark.parametrize("size", ["390,844", "1280,800"])
@in_chromium
def test_a_rows_title_is_as_easy_to_hit_as_its_button(conn, cfg, tmp_path, size):
    import html as html_module

    filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), ROW_LAYOUT))
    found = re.search(r'data-rows="([^"]*)"', dump_dom(path, tmp_path, "#view=rows", size=size))
    assert found
    laid = json.loads(html_module.unescape(found.group(1)))
    rows = laid["rows"]
    assert laid["scroll"] <= laid["page"], laid
    # The title's link fills its line, as tall as the button beside it, and the title stays on one line.
    for title in ("Creep", "Wonderwall"):
        assert rows[title]["title"] >= rows[title]["button"] > 0 and rows[title]["lines"] == 1, rows
        assert rows[title]["colour"] == laid["accent"], rows  # the sheet is the row's primary button
    assert rows["Yesterday"]["title"] is None, rows


@in_chromium
def test_a_wanted_songs_auto_sheet_opens_from_its_rows_title_and_leads_its_files(conn, cfg, tmp_path):
    row = row_of(listing(dump_dom(served_auto_sheet(conn, cfg), tmp_path, "#view=rows")), "斑马，斑马")
    assert re.search(r'<div class="row-action"><form[^>]*action="/fetch"', row), row
    # Fetch now has the row's button: its title opens the auto sheet, which also leads its files under "⋯".
    assert re.search(r'<a class="title-link" ' + AUTO_VIEWER + r' tabindex="-1">', row), row
    assert link_texts(panel_of(row))[:1] == ["Auto sheet viewer"], row


# The row renderer's title link, as another list uses it: a relative link, a site's, and one that isn't safe.
TITLE_ROWS = """
(() => {
  const list = document.createElement("div");
  list.className = "rows";
  list.id = "results";
  for (const [title, href] of [["Here", "Radiohead/Creep/sheet.html"], ["There", "https://example.org/creep"],
                               ["Nowhere", "javascript:alert(1)"], ["Plain", ""]]) {
    list.appendChild(window.caracole.resultRow({ title, href }));
  }
  document.body.appendChild(list);
})();
"""


@in_chromium
def test_a_result_rows_title_opens_what_its_href_says(conn, cfg, tmp_path):
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), TITLE_ROWS))
    results = re.search(r'<div class="rows" id="results">(.*?)</div>\s*</body>', dump_dom(path, tmp_path), re.S).group(1)
    here = re.search(r'<a class="title-link" ([^>]*)><h2 class="row-title"[^>]*>Here</h2>', results)
    assert here and 'href="Radiohead/Creep/sheet.html"' in here.group(1) and "target" not in here.group(1)
    there = re.search(r'<a class="title-link" ([^>]*)><h2 class="row-title"[^>]*>There</h2>', results)
    assert there and 'href="https://example.org/creep"' in there.group(1)
    assert 'target="_blank"' in there.group(1) and 'rel="noopener noreferrer"' in there.group(1)
    assert "javascript:" not in results and re.search(r'href="#"[^>]*><h2 class="row-title"[^>]*>Nowhere<', results)
    assert re.search(r'<article class="row" tabindex="-1"><h2 class="row-title"[^>]*>Plain</h2>', results), results


# --- a card opens its sheet from one button; its other files fold away ---------------------------------


@in_chromium
def test_a_card_opens_its_sheet_from_one_button_and_its_other_files_fold_away(conn, cfg, tmp_path):
    filed_library(conn, cfg)
    shown = listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path))

    creep = card_of(shown, "Creep")
    assert creep.count('<details class="more files">') == 1, creep
    top, files = creep.split('<details class="more files">')
    files = files.split("</details>", 1)[0]
    # One button opens the viewer, as the title does, named for the song.
    assert link_texts(top) == ["Open"], top
    opened = re.search(r'<a class="btn primary" ([^>]*)>Open</a>', top)
    assert 'href="Radiohead/Creep/sheet.html"' in opened.group(1)
    assert 'aria-label="Open Creep by Radiohead"' in opened.group(1) and 'title="Sheet viewer"' in opened.group(1)
    # Every other file, and the Guitar Pro versions to download, under Files: closed, small.
    assert files.startswith("<summary>Files</summary>"), files
    assert link_texts(files) == ["Sheet PDF", "Sheet text", "ChordPro", "Lyrics", "Timed lyrics", "Guitar Pro 1",
                                 "Tab", "Info", "Guitar Pro ver 1 · 4.5★ · 12 votes ↗"], files
    assert '<p class="subhead">Guitar Pro to download</p>' in files
    assert all(cls.startswith("btn small") for cls in re.findall(r'<a class="([^"]*)"', files)), files

    # A sheet with no viewer opens its PDF, and says so.
    wonderwall = card_of(shown, "Wonderwall")
    opened = re.search(r'<a class="btn primary" ([^>]*)>Open PDF</a>', wonderwall)
    assert opened and 'href="Oasis/Wonderwall/sheet.pdf"' in opened.group(1), wonderwall
    assert 'aria-label="Open PDF of Wonderwall by Oasis"' in opened.group(1)
    assert "more files" not in wonderwall  # nothing else to fold away
    # A song with no file has nothing to open.
    yesterday = card_of(shown, "Yesterday")
    assert ">Open" not in yesterday and "more files" not in yesterday


@in_chromium
def test_a_wanted_songs_card_keeps_fetch_now_its_one_primary_button(conn, cfg, tmp_path):
    card = card_of(listing(dump_dom(served_auto_sheet(conn, cfg), tmp_path)), "斑马，斑马")
    # Fetch now is the card's one primary button, as it is the row's; the auto sheet opens beside it.
    assert 'action="/fetch"' in card and card.count("btn primary") == 1, card
    assert re.search(r'<a class="btn" ' + AUTO_VIEWER + r"[^>]*>Open</a>", card), card


@in_chromium
def test_on_a_phone_files_open_with_a_tap_the_title_opens_the_viewer_and_tab_skips_the_title(conn, cfg, tmp_path):
    from helpers.browser import Browser, BrowserError

    creep = filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    try:
        phone = Browser(tmp_path / "chrome", width=390, height=844, mobile=True)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    card = f'#list .card[data-id="{creep.id}"]'
    with phone:
        phone.open(path.as_uri())
        assert phone.wait(f"document.querySelector({json.dumps(card)}) !== null")
        q = f"document.querySelector({json.dumps(card)})"
        # A thumb's target: Files, and each file once it's open.
        assert phone.js(f"{q}.querySelector('details.files > summary').getBoundingClientRect().height") >= 44
        phone.click(card + " details.files > summary")
        assert phone.wait(f"{q}.querySelector('details.files').open")
        heights = phone.js(f"Array.from({q}.querySelectorAll('details.files a')).map((a) => a.getBoundingClientRect().height)")
        assert len(heights) == 9 and min(heights) >= 44, heights
        # From the artist, Tab goes to Open: the title opens the same, and isn't a stop of its own.
        phone.js(f"{q}.querySelector('button.artist').focus()")
        phone.press("Tab")
        assert phone.js("document.activeElement.textContent") == "Open"
        phone.click(card + " .title-link")
        assert phone.wait("location.pathname.endsWith('/Radiohead/Creep/sheet.html')")


# --- a card's title keeps its line: its badges go beside its artist ------------------------------------


# Notes how each card is laid out: its height, how many lines its title takes, where its badges are against
# its title and its artist, how tall its artist and its Files are, and how many buttons it shows.
CARD_LAYOUT = """
(() => {
  const box = (n) => n.getBoundingClientRect();
  const cards = {};
  for (const c of document.querySelectorAll("#list .card")) {
    const h2 = c.querySelector("h2");
    const title = box(h2);
    const artist = box(c.querySelector("button.artist"));
    const badges = box(c.querySelector(".badges"));
    const files = c.querySelector("details.files > summary");
    cards[h2.textContent] = {
      height: Math.round(box(c).height),
      lines: Math.round(title.height / parseFloat(getComputedStyle(h2).lineHeight)),
      alone: badges.top >= title.bottom - 1,  // nothing beside the title: the badges are under it
      apart: badges.left >= artist.right - 1 || badges.top >= artist.bottom - 1,  // beside the artist, or under
      artist: Math.round(artist.height),
      buttons: Array.from(c.querySelectorAll(".btn")).filter((b) => b.checkVisibility()).length,
      files: files ? Math.round(box(files).height) : null,
    };
  }
  document.body.setAttribute("data-cards", JSON.stringify({ cards, page: innerWidth, screen: innerHeight,
    scroll: document.documentElement.scrollWidth }));
})();
"""


@pytest.mark.parametrize("size,touch", [("390,844", False), ("390,844", True), ("1280,800", False)])
@in_chromium
def test_lean_cards_fit_a_phone_and_their_titles_keep_a_line_of_their_own(conn, cfg, tmp_path, size, touch):
    import html as html_module

    filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), CARD_LAYOUT))
    dom = dump_dom(path, tmp_path, size=size, touch=touch)
    found = re.search(r'data-cards="([^"]*)"', dom)
    assert found, dom[-2000:]
    laid = json.loads(html_module.unescape(found.group(1)))
    cards = laid["cards"]
    assert laid["page"] == int(size.split(",")[0]) and laid["scroll"] <= laid["page"], laid
    assert cards["Creep"]["buttons"] == 1 and cards["Creep"]["files"], cards  # Open; the rest folded
    # The badges go on the artist's line, or under it: two of them leave the title its whole line.
    assert all(card["alone"] and card["apart"] for card in cards.values()), cards
    assert cards["The Underworld"]["lines"] == 1, cards
    if touch:
        # The artist, which shows that artist's songs alone, is a thumb's target, on the line it shares.
        assert min(card["artist"] for card in cards.values()) >= 44, cards
    else:
        assert max(card["artist"] for card in cards.values()) < 44, cards  # a mouse's: the line of text
    if laid["page"] < 480:
        # Three cards to a phone's screen, the fullest too, where its eight files and more made it 1.5.
        assert laid["screen"] // cards["Creep"]["height"] >= 3, cards


@in_chromium
def test_an_artists_name_shows_it_is_a_filter_on_its_card_and_its_row(conn, cfg, tmp_path):
    filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    for fragment, find in (("", card_of), ("#view=rows", row_of)):
        shown = find(listing(dump_dom(path, tmp_path, fragment)), "Creep")
        who = re.search(r'<button class="artist[^"]*" type="button" title="Show only Radiohead\'s songs">(.*?)</button>',
                        shown)
        assert who, shown
        # The name, then a filter's mark that a screen reader skips: the button's title says what it does.
        assert who.group(1) == ('<span class="artist-name">Radiohead</span>'
                                '<span class="filter-mark" aria-hidden="true"></span>'), who.group(1)


# --- touch and edges: a thumb's targets, and fields an eye can find ------------------------------------


def every_control(conn, cfg, *, served: bool = True) -> str:
    """The page caracole serve serves (``served``; else the file on disk), with a control of every kind:
    filed_library's songs (every file, a Guitar Pro version to download, a song in review, one with no
    file), a review's candidates to pick, a wanted song with an auto sheet, a songbook, and the form to
    request a song."""
    from caracole.library_page import WebControls
    from caracole.songbook import FILE_NAME, make_songbook

    filed_library(conn, cfg)
    index_tabs(conn, (1, "radiohead", "creep", "chords"), (3, "radiohead", "creep", "tabs"))
    in_review(conn)
    auto = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, auto, "sheet (auto).txt", "sheet (auto).html", "sheet (auto).pdf")
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Radiohead - Creep", "Oasis - Wonderwall"])
    controls = WebControls(csrf="tok") if served else None
    return build_library_page(conn, cfg, Overrides(), NOW, controls=controls)


# A card's title opens what its Open button opens, which is a thumb's size (WCAG 2.5.8's equivalent).
TITLES = ".card .title-link"


@pytest.mark.parametrize("size", ["390,844", "1280,800"])
@pytest.mark.parametrize("view", ["", "#view=rows"])
@in_chromium
def test_on_a_touch_screen_every_control_is_a_thumbs_size(conn, cfg, tmp_path, size, view):
    from helpers.targets import UNFOLD, noted, noting, small_targets

    html = with_script(every_control(conn, cfg), UNFOLD + noting("data-short", small_targets(TITLES)))
    dom = dump_dom(write_library_page(cfg.library_dir, html), tmp_path, view, size=size, touch=True)
    short = noted(dom, "data-short")
    assert short == [], short


# On the file on disk, Select a song, name a songbook and make it: the bar then shows the command to run.
MAKE_FROM_DISK = """
document.querySelector(".pick-toggle").click();
document.querySelector("#list .pick input").click();
document.querySelector(".pick-name").value = "Campfire 2";
document.querySelector(".pickbar-form button[type=submit]").click();
document.body.setAttribute("data-command", String(!document.querySelector(".pick-command").hidden));
"""


@in_chromium
def test_the_select_bar_of_the_file_on_disk_and_its_command_on_a_touch_phone(conn, cfg, tmp_path):
    from helpers.targets import UNFOLD, noted, noting, small_targets, weak_edges

    # The search field is the search bar's, which another change redraws. While selecting, a card is one
    # target, its artist's name no target of its own.
    exempt = TITLES + ", .selecting [data-picker] .artist"
    script = (UNFOLD + MAKE_FROM_DISK + noting("data-short", small_targets(exempt))
              + noting("data-weak", weak_edges("#q")))
    html = with_script(every_control(conn, cfg, served=False), script)
    dom = dump_dom(write_library_page(cfg.library_dir, html), tmp_path, size="390,844", touch=True)
    assert 'data-command="true"' in dom  # its Copy button is measured too
    short, weak = noted(dom, "data-short"), noted(dom, "data-weak")
    assert short == [] and weak == [], (short, weak)


# The heights of the compact controls, as a mouse gets them.
COMPACT = """
(() => {
  const tall = (selector) => {
    const node = Array.from(document.querySelectorAll(selector)).find((n) => n.checkVisibility());
    return node ? Math.round(node.getBoundingClientRect().height) : null;
  };
  return { row: tall("#list .row-action .btn"), more: tall("#list .row-more"), artist: tall("#list button.artist"),
           file: tall("#list .row-panel .btn.small"), view: tall(".views button"), letter: tall("#jump button"),
           chip: tall(".chip"), menu: tall("#sort") };
})()
"""


@in_chromium
def test_a_mouse_keeps_the_compact_controls(conn, cfg, tmp_path):
    from helpers.targets import UNFOLD, noted, noting

    html = with_script(every_control(conn, cfg), UNFOLD + noting("data-compact", COMPACT))
    heights = noted(dump_dom(write_library_page(cfg.library_dir, html), tmp_path, "#view=rows", size="1280,800"),
                    "data-compact")
    assert all(h is not None and h < 44 for h in heights.values()), heights


# The card's border against a field's, both as the browser draws them.
BORDERS = """
({ card: getComputedStyle(document.querySelector("#list .card")).borderTopColor,
   field: getComputedStyle(document.querySelector(".request .f input")).borderTopColor })
"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
@in_chromium
def test_fields_menus_and_select_boxes_have_an_edge_of_three_to_one(conn, cfg, tmp_path, scheme):
    from helpers.targets import UNFOLD, noted, noting, weak_edges

    select = 'document.querySelector(".pick-toggle").click();\n'  # its boxes, and its bar's name and menu
    # The search field is the search bar's, which another change redraws.
    script = UNFOLD + select + noting("data-weak", weak_edges("#q")) + noting("data-borders", BORDERS)
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(every_control(conn, cfg), script)), tmp_path,
                   size="390,844", media={"prefers-color-scheme": scheme})
    weak = noted(dom, "data-weak")
    assert weak == [], weak
    borders = noted(dom, "data-borders")
    assert borders["card"] != borders["field"], borders  # a card keeps its soft border: it is no control


def css_tokens(style: str, *, dark: bool) -> dict[str, str]:
    """The colours of a stylesheet's first :root, or of its first :root for dark mode."""
    light, _, rest = style.partition("@media (prefers-color-scheme: dark)")
    root = re.search(r":root\s*\{(.*?)\}", rest if dark else light, re.S)
    assert root, style[:500]
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\b", root.group(1)))


def contrast(a: str, b: str) -> float:
    """WCAG's contrast ratio of two #rrggbb colours."""
    def luminance(colour: str) -> float:
        r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("dark", [False, True])
def test_a_controls_edge_is_three_to_one_against_every_background_a_card_keeps_its_soft_border(dark):
    from caracole.library_page import BASE_STYLE

    tokens = css_tokens(BASE_STYLE, dark=dark)
    for background in ("--bg", "--surface", "--raised"):
        assert contrast(tokens["--control-edge"], tokens[background]) >= 3, (background, tokens)
    assert contrast(tokens["--border"], tokens["--surface"]) < 3  # cards and dividers: no control's edge


def row_of(shown: str, title: str) -> str:
    found = re.search(r'<article class="row"[^>]*>(?:(?!</article>).)*?' + re.escape(title) + r".*?</article>",
                      shown, re.S)
    assert found, shown[-2000:]
    return found.group(0)


@in_chromium
def test_the_rows_view_shows_a_song_a_row_with_its_source_key_status_and_main_action(conn, cfg, tmp_path):
    sourced_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    dom = dump_dom(path, tmp_path, "#view=rows")
    shown = listing(dom)
    assert shown.count('<article class="row"') == 4 and 'class="card"' not in shown
    assert re.search(r'<button[^>]*data-view="rows"[^>]*aria-pressed="true"', dom)
    creep = row_of(shown, "Creep")
    assert re.search(r'<h2 class="row-title"[^>]*>Creep</h2>', creep)
    assert 'alt="from Ultimate Guitar"' in creep and '<span class="artist-name">Radiohead</span>' in creep
    assert "Key G major (from the tab)" in creep and ">Found<" in creep
    main = re.search(r'<div class="row-action"><a ([^>]*)>Sheet PDF</a>', creep)
    assert main and 'href="Radiohead/Creep/sheet.pdf"' in main.group(1)
    assert 'aria-label="Sheet PDF of Creep by Radiohead"' in main.group(1)
    # The other files wait behind a small button, closed.
    more = re.search(r'<button class="row-more"[^>]*aria-expanded="false"[^>]*aria-controls="([^"]+)"', creep)
    assert more and re.search(rf'<div class="row-panel" id="{more.group(1)}" hidden', creep)
    assert ">More for Creep<" in creep and "Lyrics" in creep.split("row-panel", 1)[1]
    soda = row_of(shown, "De Música Ligera")
    assert 'aria-label="from LaCuerda"' in soda and ">Sheet text<" in soda
    wonderwall = row_of(shown, "Wonderwall")
    assert ">Wanted<" in wonderwall and "row-action" in wonderwall and "Find the chords" in wonderwall


# Measures the rows: each one's top and height, its artist's width, how many lines its parts take
# (by their middles), the page's width and how far it scrolls sideways.
ROWS = """
(() => {
  const rows = Array.from(document.querySelectorAll("#list .row"));
  const box = (node) => node.getBoundingClientRect();
  // The artist's name: in the button that shows that artist's songs alone, or the row's text.
  const name = (r) => r.querySelector(".row-artist .artist-name") || r.querySelector(".row-artist");
  const lines = (r) => {
    const parts = r.querySelectorAll(".row-title, .row-artist, .row-meta > *, .row-action > *, .row-more, .row > .source");
    const middles = Array.from(parts).filter((p) => box(p).height > 0)
      .map((p) => box(p).top + box(p).height / 2).sort((a, b) => a - b);
    return middles.filter((m, i) => i === 0 || m - middles[i - 1] > 6).length;
  };
  document.body.setAttribute("data-layout", JSON.stringify({
    tops: rows.map((r) => Math.round(box(r).top + window.scrollY)),
    heights: rows.map((r) => Math.round(box(r).height)),
    titles: rows.map((r) => Math.round(box(r.querySelector("h2")).top)),
    actions: rows.map((r) => r.querySelector(".row-action > *") ? Math.round(box(r.querySelector(".row-action > *")).top) : null),
    artists: rows.map((r) => name(r) ? Math.round(box(name(r)).width) : null),
    whole: rows.map((r) => name(r) ? name(r).scrollWidth : null),
    lines: rows.map(lines),
    widths: rows.map((r) => Math.round(box(r).width)),
    page: window.innerWidth,
    screen: window.innerHeight,
    scroll: document.documentElement.scrollWidth,
  }));
})();
"""


def youtube_auto_sheet(conn, cfg):
    """Creep, whose auto sheet auto-chords made from the audio caracole took from YouTube."""
    from caracole.db import kv_set_json

    s = add_song(conn, "Radiohead", "Creep")
    audio = cfg.cache_dir / "youtube" / f"{s.id}-XFkzRNyygfk.m4a"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"aac")
    mtime = audio.stat().st_mtime
    video = {"id": "XFkzRNyygfk", "title": "Creep", "channel": "Radiohead - Topic", "duration": 238.0,
             "url": "https://www.youtube.com/watch?v=XFkzRNyygfk"}
    kv_set_json(conn, f"youtube:{s.id}", {"video": video, "source": "search", "audio": str(audio)})
    v = upsert_version(conn, provider="auto", tab_id=str(s.id), song_id=s.id, slot="sheet", kind="auto", rating=0,
                       votes=0, version=1, label=None, url=video["url"],
                       raw={"audio": str(audio), "model": "btc", "lyrics": "plain", "youtube": video}, now="x")
    keep_file(conn, cfg.library_dir, song=s, version_id=v, name="sheet (auto).txt", data=b"A\nWords\n", rank=1)
    put(cfg, s, "sheet (auto).pdf")
    update_song(conn, s.id, status="found", match_decision="not_found", audio_path=str(audio), audio_mtime=mtime,
                autochords_mtime=mtime)
    return s


@in_chromium
def test_an_auto_sheet_from_youtube_audio_shows_where_it_came_from_in_both_views(conn, cfg, tmp_path, monkeypatch):
    from helpers.fake_ytdlp import route_on

    on, _ = route_on(cfg, tmp_path, monkeypatch)
    youtube_auto_sheet(conn, on)
    bought = add_song(conn, "宋冬野", "斑马，斑马")  # a purchase's auto sheet beside it: the audio model's ♪
    put(on, bought, "sheet (auto).txt", "sheet (auto).pdf")
    update_song(conn, bought.id, status="found")
    html = page(conn, on)
    assert songs_of(html)["Radiohead - Creep"]["source"] == "youtube"
    path = write_library_page(on.library_dir, html)

    card = card_of(listing(dump_dom(path, tmp_path)), "Creep")
    assert re.search(r'<div class="badges"><span class="source letters"[^>]*aria-label="from YouTube"', card), card
    assert ">Auto sheet<" in card
    note = re.search(r'<p class="youtube">(.*?)</p>', card, re.S)
    assert note and note.group(1).startswith("Auto sheet from YouTube audio · <a"), card
    assert 'href="https://www.youtube.com/watch?v=XFkzRNyygfk"' in note.group(1)
    assert "Creep (Radiohead - Topic) ↗" in note.group(1)
    assert 'aria-label="from the audio (auto-chords)"' in card_of(listing(dump_dom(path, tmp_path)), "斑马，斑马")

    shown = listing(dump_dom(path, tmp_path, "#view=rows"))
    row = row_of(shown, "Creep")
    assert re.search(r'</div><span class="source letters"[^>]*aria-label="from YouTube"', row), row
    assert re.search(r'<div class="row-action"><a [^>]*>Auto sheet PDF</a>', row), row
    # The video waits behind the row's ⋯, as the rest of the card does.
    panel = row.split('class="row-panel"', 1)[1]
    note = re.search(r'<p class="youtube">(.*?)</p>', panel, re.S)
    assert note and note.group(1).startswith("Auto sheet from YouTube audio · <a"), row
    assert 'href="https://www.youtube.com/watch?v=XFkzRNyygfk"' in note.group(1)
    assert 'aria-label="from the audio (auto-chords)"' in row_of(shown, "斑马，斑马")


@in_chromium
def test_many_rows_fit_on_a_screen_and_a_phones_rows_wrap_to_two_lines(conn, cfg, tmp_path):
    for n in range(24):
        s = add_song(conn, f"Artist With A Long Name {n:02d}", f"A Song Title That Goes On For A While {n:02d}")
        keep_sheet_json(conn, cfg, s, "Words\n", raw={"tonality_name": "F#m"}, tab_id=100 + n)
        put(cfg, s, "sheet.pdf", "lyrics.txt")
        update_song(conn, s.id, status="found", review=n % 5 == 0)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), ROWS))

    wide = layout_of(dump_dom(path, tmp_path, "#view=rows", size="1280,900"))
    assert wide["page"] == 1280, wide  # laid out at the width asked for
    assert len(wide["tops"]) == 24 and wide["scroll"] <= wide["page"], wide
    assert all(abs(t - a) <= 8 for t, a in zip(wide["titles"], wide["actions"])), wide  # one line each
    assert set(wide["lines"]) == {1}, wide
    assert wide["screen"] // max(wide["heights"]) >= 20, wide  # a screen holds 20 rows, against 9 cards

    phone = layout_of(dump_dom(path, tmp_path, "#view=rows", size="390,844"))
    assert (phone["page"], phone["screen"]) == (390, 844), phone  # a phone's screen, exactly
    assert phone["scroll"] <= phone["page"], phone  # nothing wider than the screen
    assert all(w >= phone["page"] - 40 for w in phone["widths"]), phone
    assert set(phone["lines"]) == {2} and min(phone["artists"]) > 40, phone
    # Two lines at most, with buttons a thumb can hit: nine rows to a screen, against three cards.
    assert phone["screen"] // max(phone["heights"]) >= 9, phone
    # On a touch screen each row's button, "⋯" and artist are a thumb's size: eight rows still.
    touch = layout_of(dump_dom(path, tmp_path, "#view=rows", size="390,844", touch=True))
    assert set(touch["lines"]) == {2} and touch["scroll"] <= touch["page"], touch
    assert touch["screen"] // max(touch["heights"]) >= 8, touch
    tablet = layout_of(dump_dom(path, tmp_path, "#view=rows", size="1280,800", touch=True))
    assert set(tablet["lines"]) == {1}, tablet  # one line each, as with a mouse


@in_chromium
def test_a_phones_row_keeps_its_artist_beside_the_most_badges_a_song_has(conn, cfg, tmp_path):
    # The fullest second lines: a key, the status and Needs review, beside an auto sheet's mark; Wanted
    # and Needs review.
    abba = add_song(conn, "ABBA", "Dancing Queen")
    auto = upsert_version(conn, provider="auto", tab_id=str(abba.id), song_id=abba.id, slot="sheet", kind="auto",
                          rating=0, votes=0, version=1, label=None, url="file:///x.flac",
                          raw={"key": "A major"}, now="2026-10-18T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=abba, version_id=auto, name="sheet (auto).txt", data=b"A\nWords\n", rank=1)
    put(cfg, abba, "sheet (auto).pdf")
    update_song(conn, abba.id, status="found", review=True)
    queen = add_song(conn, "Queen", "Bohemian Rhapsody")
    keep_sheet_json(conn, cfg, queen, "Words\n", raw={"tonality_name": "Bb"})
    put(cfg, queen, "sheet.pdf")
    update_song(conn, queen.id, status="found", review=True)
    longest = add_song(conn, "Florence + The Machine", "Dog Days Are Over")
    update_song(conn, longest.id, review=True)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), ROWS))

    phone = layout_of(dump_dom(path, tmp_path, "#view=rows", size="390,844"))
    assert phone["page"] == 390, phone
    abba_row, florence_row, queen_row = range(3)  # by artist
    # "ABBA" and "Queen" whole, never squeezed out by the badges; a long name cut, but readable.
    for short in (abba_row, queen_row):
        assert phone["artists"][short] >= phone["whole"][short] > 30, phone
    assert phone["artists"][florence_row] > 40, phone
    assert max(phone["lines"]) <= 2, phone
    assert phone["scroll"] <= phone["page"], phone
    # The auto sheet's row says where it came from by its mark and its button, as a badge would.
    shown = listing(dump_dom(path, tmp_path, "#view=rows"))
    dancing = row_of(shown, "Dancing Queen")
    assert 'aria-label="from the audio (auto-chords)"' in dancing and ">Auto sheet PDF<" in dancing
    assert ">Needs review<" in dancing and ">Auto sheet<" not in dancing


@in_chromium
def test_the_filters_sort_key_menu_artist_and_letters_work_in_rows_in_a_real_browser(conn, cfg, tmp_path):
    for tab_id, (artist, title, key) in enumerate((("Queen", "Bohemian Rhapsody", "Bb"),
                                                    ("Queen", "Don't Stop Me Now", "F"),
                                                    ("ABBA", "Dancing Queen", "A"),
                                                    ("Radiohead", "Creep", "G")), start=1):
        s = add_song(conn, artist, title)
        keep_sheet_json(conn, cfg, s, "Words\n", raw={"tonality_name": key}, tab_id=tab_id)
        update_song(conn, s.id, status="found" if tab_id != 4 else "wanted")
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    def titles(fragment):
        shown = listing(dump_dom(path, tmp_path, fragment))
        assert 'class="card"' not in shown
        return sorted(re.findall(r'<h2 class="row-title"[^>]*>([^<]*)</h2>', shown))

    assert titles("#view=rows") == ["Bohemian Rhapsody", "Creep", "Dancing Queen", "Don't Stop Me Now"]
    assert titles("#view=rows&artist=queen") == ["Bohemian Rhapsody", "Don't Stop Me Now"]
    assert titles("#view=rows&key=G") == ["Creep"]
    assert titles("#view=rows&show=wanted") == ["Creep"]
    assert titles("#view=rows&q=dancing") == ["Dancing Queen"]
    shown = listing(dump_dom(path, tmp_path, "#view=rows&sort=title"))
    assert re.findall(r'<h2 class="row-title"[^>]*>([^<]*)</h2>', shown) == [
        "Bohemian Rhapsody", "Creep", "Dancing Queen", "Don't Stop Me Now"]
    strip = re.search(r'<nav[^>]*id="jump"[^>]*>(.*?)</nav>', dump_dom(path, tmp_path, "#view=rows&sort=title"), re.S)
    assert re.findall(r"<button[^>]*>([^<]+)</button>", strip.group(1)) == ["B", "C", "D"]


# Switches to rows and back, jumps to "R", opens a row's other links, and clicks an artist; notes each step.
ROW_CLICKS = """
(() => {
  const notes = {};
  const view = (name) => document.querySelector('[data-view="' + name + '"]');
  view("rows").click();
  notes.rows = { hash: location.hash, rows: document.querySelectorAll("#list .row").length,
                 cards: document.querySelectorAll("#list .card").length,
                 pressed: view("rows").getAttribute("aria-pressed") };
  Array.from(document.querySelectorAll("#jump button")).find((b) => b.textContent === "R").click();
  const focused = document.activeElement.closest("article");
  notes.jump = focused ? focused.className + ":" + focused.querySelector("h2").textContent : "none";
  const row = Array.from(document.querySelectorAll("#list .row"))
    .find((r) => r.querySelector("h2").textContent === "Creep");
  const more = row.querySelector(".row-more");
  more.click();
  const panel = document.getElementById(more.getAttribute("aria-controls"));
  notes.opened = { expanded: more.getAttribute("aria-expanded"), hidden: panel.hidden,
                   links: Array.from(panel.querySelectorAll("a")).map((a) => a.firstChild.textContent) };
  more.click();
  notes.closed = { expanded: more.getAttribute("aria-expanded"), hidden: panel.hidden };
  row.querySelector("button.artist").click();
  notes.artist = { hash: location.hash, titles: Array.from(document.querySelectorAll("#list .row h2"))
    .map((h) => h.textContent) };
  view("cards").click();
  notes.cards = { hash: location.hash, cards: document.querySelectorAll("#list .card").length };
  document.body.setAttribute("data-notes", JSON.stringify(notes));
})();
"""


@in_chromium
def test_the_view_toggle_is_remembered_and_a_rows_controls_work_from_the_keyboard(conn, cfg, tmp_path):
    import html as html_module

    creep = add_song(conn, "Radiohead", "Creep")
    put(cfg, creep, "sheet.pdf", "lyrics.txt", "tab.txt")
    add_song(conn, "Radiohead", "Lucky")
    add_song(conn, "The Beatles", "Yesterday")
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), ROW_CLICKS))
    dom = dump_dom(path, tmp_path)
    notes = json.loads(html_module.unescape(re.search(r'data-notes="([^"]*)"', dom).group(1)))
    assert notes["rows"] == {"hash": "#view=rows", "rows": 3, "cards": 0, "pressed": "true"}, notes
    assert notes["jump"] == "row:Creep", notes  # the next Tab goes on from the row jumped to
    assert notes["opened"] == {"expanded": "true", "hidden": False, "links": ["Lyrics", "Tab"]}, notes
    assert notes["closed"] == {"expanded": "false", "hidden": True}, notes
    assert "view=rows" in notes["artist"]["hash"] and "artist=radiohead" in notes["artist"]["hash"], notes
    assert sorted(notes["artist"]["titles"]) == ["Creep", "Lucky"], notes
    assert "view=" not in notes["cards"]["hash"] and notes["cards"]["cards"] == 2, notes


@in_chromium
def test_the_served_pages_rows_offer_a_fetch_for_wanted_songs(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    wanted = add_song(conn, "Radiohead", "Creep")
    busy = add_song(conn, "Oasis", "Wonderwall")
    held = add_song(conn, "Queen", "Bohemian Rhapsody")
    update_song(conn, held.id, review=True)
    controls = WebControls(csrf="tok", busy=frozenset({busy.id}), active=1, held=frozenset({held.id}))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    shown = listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path, "#view=rows"))
    creep = row_of(shown, "Creep")
    form = re.search(r'<div class="row-action"><form[^>]*action="/fetch"[^>]*>(.*?)</form>', creep, re.S)
    assert form and f'name="song" value="{wanted.id}"' in form.group(1) and 'name="csrf" value="tok"' in form.group(1)
    assert 'aria-label="Fetch Creep by Radiohead now"' in form.group(1)
    assert "Fetching" in row_of(shown, "Wonderwall") and "/fetch" not in row_of(shown, "Wonderwall")
    assert re.search(r"<button[^>]*disabled[^>]*>Review first</button>", row_of(shown, "Bohemian Rhapsody"))


# What another list on the page (the served page's type-ahead) does with the row renderer.
RESULT_ROWS = """
(() => {
  const list = document.createElement("div");
  list.className = "rows";
  list.id = "results";
  list.appendChild(window.caracole.resultRow({
    title: "Creep", artist: "Radiohead", source: "ug", facts: "chords×3 tabs×2",
    action: { label: "Chords", href: "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169" },
    more: [{ heading: "Tabs", links: [{ label: "Tab", href: "javascript:alert(1)", source: "ug" }] }],
  }));
  list.appendChild(window.caracole.resultRow({ title: "Nameless" }));
  document.body.appendChild(list);
  document.body.setAttribute("data-api", Object.keys(window.caracole).sort().join(","));
})();
"""


@in_chromium
def test_the_row_renderer_takes_any_search_result_in_a_real_browser(conn, cfg, tmp_path):
    from helpers.icon_files import png

    from caracole import icons

    icons.keep_icon(cfg.cache_dir, "ug", icons.sanitize(png(32)))
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), RESULT_ROWS))
    dom = dump_dom(path, tmp_path)
    assert re.search(r'data-api="icons,resultRow,sourceMark"', dom)
    results = re.search(r'<div class="rows" id="results">(.*?)</div>\s*</body>', dom, re.S).group(1)
    creep = row_of(results, "Creep")
    assert 'alt="from Ultimate Guitar"' in creep and "chords×3 tabs×2" in creep
    main = re.search(r'<div class="row-action"><a ([^>]*)>Chords ↗</a>', creep)
    assert main and 'target="_blank"' in main.group(1) and 'rel="noopener noreferrer"' in main.group(1)
    assert "javascript:" not in creep and 'href="#"' in creep  # an unsafe link goes nowhere
    assert "row-more" not in row_of(results, "Nameless")  # nothing more to show, no button


# --- rows on the served page: every state a card shows ------------------------------------------


def served_states(conn, cfg):
    """A song in each state a served card shows: in review with candidates to pick (Crep), being removed
    (Wonderwall), its request queued (Bohemian Rhapsody), not found (Yesterday), found in a key (De Música
    Ligera); and the controls that say so."""
    from caracole.library_page import WebControls

    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    crep = in_review(conn)
    going = add_song(conn, "Oasis", "Wonderwall")
    queued = add_song(conn, "Queen", "Bohemian Rhapsody")
    lost = add_song(conn, "The Beatles", "Yesterday")
    update_song(conn, lost.id, match_decision="not_found")
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet_json(conn, cfg, soda, "Words\n", raw={"tonality_name": "Am"}, tab_id=7)
    put(cfg, soda, "sheet.pdf")
    update_song(conn, soda.id, status="found")
    job = {"id": 4, "display": queued.display, "songId": queued.id, "state": "queued", "fetching": True,
           "line": {"tone": "queued", "text": "Queued behind 1 request…", "link": None,
                    "details": "jobs?job=4#job-4"}, "details": "jobs?job=4#job-4"}
    controls = WebControls(csrf="tok", busy=frozenset({queued.id}), active=2, held=frozenset({crep.id}),
                           removing=frozenset({going.id}), jobs=(job,))
    return controls, {"crep": crep, "going": going, "queued": queued, "lost": lost, "soda": soda}


def panel_of(row: str) -> str:
    found = re.search(r'<div class="row-panel"[^>]*>.*', row, re.S)
    assert found, row
    return found.group(0)


@in_chromium
def test_the_served_rows_carry_every_state_a_card_shows(conn, cfg, tmp_path):
    controls, s = served_states(conn, cfg)
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    shown = listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path, "#view=rows"))
    assert shown.count('<article class="row"') == 5 and 'class="card"' not in shown

    # In review, with candidates: its button opens the picker, in its panel, instead of Review first.
    crep = row_of(shown, "Crep")
    assert re.search(r'<div class="row-action"><button class="btn small row-pick"[^>]*>Pick the match</button>', crep)
    assert "Review first" not in crep and "/fetch" not in crep
    # The button says Pick the match once: the picker under it folds as a card's read-only one does.
    assert re.search(r'<summary class="picker-open"[^>]*>3 candidates</summary>', panel_of(crep))
    pick = re.search(r'<form[^>]*action="/review"[^>]*>(.*?)</form>', panel_of(crep), re.S)
    assert pick and f'name="song" value="{s["crep"].id}"' in pick.group(1)
    assert re.findall(r'<input type="radio" name="pick" value="([^"]*)"', pick.group(1)) == [
        "radiohead/creep", "jeff-buckley/creep", "misc-musicals/creep-the-musical", "none"]

    # Being removed: it says so where its button was, and offers neither a fetch nor another removal.
    going = row_of(shown, "Wonderwall")
    assert re.search(r'<div class="row-action"><a class="row-busy" href="/jobs"[^>]*>Removing…</a>', going)
    assert "/fetch" not in going and "/remove" not in going

    # Its request queued: the row says how it goes, on its own line, as the card does.
    queued = row_of(shown, "Bohemian Rhapsody")
    line = re.search(r'<p class="progress"[^>]*>(.*?)</p>', queued, re.S)
    assert line and 'role="status"' in line.group(0) and 'data-tone="queued"' in line.group(0)
    assert "Queued behind 1 request…" in line.group(1) and 'href="jobs?job=4#job-4"' in line.group(1)
    assert "/fetch" not in queued and queued.count('class="progress"') == 1

    # Not found: Fetch now still asks its artist's UG page; the panel looks in the index.
    lost = row_of(shown, "Yesterday")
    assert re.search(r'<div class="row-action"><form[^>]*action="/fetch"', lost)
    assert re.search(rf'<a class="btn small" href="/review\?song={s["lost"].id}"[^>]*>Look in the index</a>',
                     panel_of(lost))

    # Found, in a key: the sheet, the key, and Remove… with the other files behind ⋯.
    soda = row_of(shown, "De Música Ligera")
    assert re.search(r'<div class="row-action"><a [^>]*>Sheet PDF</a>', soda) and "Key A minor" in soda
    removes = {title: re.findall(r'<form[^>]*action="/remove"[^>]*>(.*?)</form>', panel_of(row_of(shown, title)), re.S)
               for title in ("Crep", "Bohemian Rhapsody", "Yesterday", "De Música Ligera")}
    assert all(len(forms) == 1 and "Remove…" in forms[0] for forms in removes.values()), removes
    assert 'aria-label="Remove De Música Ligera by Soda Stereo from caracole"' in soda


@in_chromium
def test_the_file_rows_show_a_reviews_candidates_and_a_song_not_founds_line(conn, cfg, tmp_path):
    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    in_review(conn)
    lost = add_song(conn, "The Beatles", "Yesterday")
    update_song(conn, lost.id, match_decision="not_found")
    shown = listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path, "#view=rows"))
    crep = panel_of(row_of(shown, "Crep"))
    assert re.search(r'<details class="picker"', crep) and "<form" not in crep
    assert "<code>caracole review --song 'Radio Head - Crep'</code>" in crep
    hint = re.search(r'<p class="pick-hint">(.*?)</p>', panel_of(row_of(shown, "Yesterday")), re.S)
    assert hint and "<code>caracole review --song 'The Beatles - Yesterday'</code>" in hint.group(1)


# Measures each row (its height, whether a part of it leaves it or covers another), then opens Crep's picker
# from its row's button and notes where the focus went and how wide the page got.
ROW_STATES = """
(() => {
  const box = (n) => n.getBoundingClientRect();
  const rows = Array.from(document.querySelectorAll("#list .row"));
  const measured = {};
  for (const r of rows) {
    const rb = box(r);
    const parts = Array.from(r.querySelectorAll(
      ".row-title, .row-artist, .row-meta > *, .row-action > *, .row-more, .row > .source, .row > .progress"))
      .filter((p) => box(p).height > 0);
    const out = parts.filter((p) => box(p).right > rb.right + 0.5 || box(p).left < rb.left - 0.5)
      .map((p) => p.className);
    const over = [];
    for (let a = 0; a < parts.length; a++) {
      for (let b = a + 1; b < parts.length; b++) {
        const x = box(parts[a]);
        const y = box(parts[b]);
        if (x.left < y.right - 1 && y.left < x.right - 1 && x.top < y.bottom - 1 && y.top < x.bottom - 1) {
          over.push(parts[a].className + " / " + parts[b].className);
        }
      }
    }
    measured[r.querySelector("h2").textContent] = { height: Math.round(rb.height), out, over };
  }
  const crep = rows.find((r) => r.querySelector("h2").textContent === "Crep");
  crep.querySelector(".row-action button").click();
  setTimeout(() => {
    const picker = crep.querySelector("details.picker");
    const at = document.activeElement;
    document.body.setAttribute("data-states", JSON.stringify({
      rows: measured, open: picker.open, panel: !picker.closest(".row-panel").hidden,
      expanded: crep.querySelector(".row-more").getAttribute("aria-expanded"),
      focus: at && at.name === "pick" ? at.value : null,
      scroll: document.documentElement.scrollWidth, page: window.innerWidth,
    }));
  }, 50);
})();
"""


@pytest.mark.parametrize("size", ["390,844", "1280,900"])
@in_chromium
def test_a_rows_states_fit_its_row_and_its_pick_opens_the_picker_where_it_is(conn, cfg, tmp_path, size):
    import html as html_module

    controls, _ = served_states(conn, cfg)
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    path = write_library_page(cfg.library_dir, with_script(html, ROW_STATES))
    dom = dump_dom(path, tmp_path, "#view=rows", size=size)
    found = re.search(r'data-states="([^"]*)"', dom)
    assert found, dom[-2000:]
    states = json.loads(html_module.unescape(found.group(1)))
    assert states["page"] == int(size.split(",")[0]) and states["scroll"] <= states["page"], states
    for title, row in states["rows"].items():
        assert row["out"] == [] and row["over"] == [], (title, row)
    # A row with a request's line is one line taller than the rest, no more.
    plain = max(row["height"] for title, row in states["rows"].items() if title != "Bohemian Rhapsody")
    assert plain < states["rows"]["Bohemian Rhapsody"]["height"] <= plain + 30, states
    assert states["open"] and states["panel"] and states["expanded"] == "true", states
    assert states["focus"] == "radiohead/creep", states
