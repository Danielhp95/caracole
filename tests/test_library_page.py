import base64
import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
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
    assert "<form" not in JSON_BLOCK.sub("", html)
    assert "server" not in data_of(html)


def test_the_served_page_has_the_request_form_and_its_token(conn, cfg):
    from caracole.library_page import WebControls

    wanted = add_song(conn, "Radiohead", "Creep")
    found = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, found.id, status="found")
    controls = WebControls(csrf='t0k"<en', busy=frozenset({wanted.id}), active=2)
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
    assert data_of(html)["server"] == {"csrf": 't0k"<en', "busy": [wanted.id], "active": 2}
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
    shell = JSON_BLOCK.sub("", html)
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

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


NARROWEST_WINDOW = 500  # headless Chromium makes a narrower --window-size this wide, whatever is asked


def dump_dom(path: Path, tmp_path: Path, fragment: str = "", size: str = "1280,900") -> str:
    """The page's DOM after its script ran, laid out in a window of ``size`` ("width,height");
    skips the test when this machine can't run Chromium. A phone's width, narrower than headless
    Chromium's narrowest window, is set as a phone's screen over the DevTools protocol."""
    url = path.as_uri() + fragment
    width, height = (int(n) for n in size.split(","))
    if width < NARROWEST_WINDOW:
        return phone_dom(url, tmp_path, width, height)
    try:
        result = subprocess.run(
            [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={tmp_path / 'chrome'}", f"--window-size={size}", "--hide-scrollbars",
             "--virtual-time-budget=3000", "--dump-dom", url],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"chromium couldn't run: {e}")
    if result.returncode != 0 or "<html" not in result.stdout:
        pytest.skip(f"chromium couldn't run: {result.stderr[-500:]}")
    return result.stdout


# Runs Chromium with the pipe it reads the DevTools protocol from as fd 3, and writes to as fd 4.
_PIPE_FDS = ("import os, sys; os.dup2(int(sys.argv[1]), 3); os.dup2(int(sys.argv[2]), 4); "
             "os.execv(sys.argv[3], sys.argv[3:])")


def phone_dom(url: str, tmp_path: Path, width: int, height: int, timeout: float = 60.0) -> str:
    """The DOM of ``url`` on a phone's screen of ``width`` × ``height`` CSS pixels
    (``Emulation.setDeviceMetricsOverride``, over ``--remote-debugging-pipe``), once its scripts
    ran and a frame was drawn."""
    import os
    import select
    import sys
    import time

    chrome_reads, to_chrome = os.pipe()
    from_chrome, chrome_writes = os.pipe()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _PIPE_FDS, str(chrome_reads), str(chrome_writes), CHROMIUM,
             "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={tmp_path / 'chrome'}", "--hide-scrollbars", "--remote-debugging-pipe",
             "about:blank"],
            pass_fds=(chrome_reads, chrome_writes), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    finally:
        os.close(chrome_reads)
        os.close(chrome_writes)
    deadline = time.monotonic() + timeout
    pending = b""
    heard: list[dict] = []
    sent = 0

    def hear() -> dict:
        nonlocal pending
        while b"\0" not in pending:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([from_chrome], [], [], left)[0]:
                raise TimeoutError("chromium answered nothing in time")
            chunk = os.read(from_chrome, 1 << 16)
            if not chunk:
                raise EOFError("chromium closed its pipe")
            pending += chunk
        message, pending = pending.split(b"\0", 1)
        return json.loads(message)

    def ask(method: str, params: dict | None = None, session: str | None = None) -> dict:
        nonlocal sent
        sent += 1
        message = {"id": sent, "method": method, "params": params or {}}
        if session is not None:
            message["sessionId"] = session
        os.write(to_chrome, json.dumps(message).encode() + b"\0")
        while (answer := hear()).get("id") != sent:
            heard.append(answer)
        if "error" in answer:
            raise RuntimeError(f"{method}: {answer['error']}")
        return answer.get("result", {})

    try:
        try:
            target = ask("Target.createTarget", {"url": "about:blank"})["targetId"]
        except (OSError, EOFError, TimeoutError, RuntimeError) as e:
            pytest.skip(f"chromium couldn't run: {e}")
        session = ask("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        ask("Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": True}, session)
        ask("Page.enable", None, session)
        ask("Page.navigate", {"url": url}, session)
        while not any(m.get("method") == "Page.loadEventFired" and m.get("sessionId") == session for m in heard):
            heard.append(hear())
        done = ask("Runtime.evaluate", {
            "expression": "new Promise((done) => requestAnimationFrame(() => setTimeout(done, 0)))"
                          ".then(() => document.documentElement.outerHTML)",
            "awaitPromise": True, "returnByValue": True}, session)
        return done["result"]["value"]
    finally:
        try:
            ask("Browser.close")
        except (OSError, EOFError, TimeoutError, RuntimeError):
            pass
        os.close(to_chrome)
        os.close(from_chrome)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def listing(dom: str) -> str:
    """The rendered song list (the DOM dump also holds the page's own script text)."""
    found = re.search(r'<main[^>]*id="list"[^>]*>(.*?)</main>', dom, re.S)
    assert found, dom[-2000:]
    return found.group(1)


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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
    assert "caracole search \"guns n' roses\"" in shown


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


def marks_of(dom: str) -> list[dict]:
    import html as html_module

    found = re.search(r'data-marks="([^"]*)"', dom)
    assert found, dom[-2000:]
    return json.loads(html_module.unescape(found.group(1)))


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


def row_of(shown: str, title: str) -> str:
    found = re.search(r'<article class="row"[^>]*>(?:(?!</article>).)*?' + re.escape(title) + r".*?</article>",
                      shown, re.S)
    assert found, shown[-2000:]
    return found.group(0)


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
def test_the_rows_view_shows_a_song_a_row_with_its_source_key_status_and_main_action(conn, cfg, tmp_path):
    sourced_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    dom = dump_dom(path, tmp_path, "#view=rows")
    shown = listing(dom)
    assert shown.count('<article class="row"') == 4 and 'class="card"' not in shown
    assert re.search(r'<button[^>]*data-view="rows"[^>]*aria-pressed="true"', dom)
    creep = row_of(shown, "Creep")
    assert re.search(r'<h2 class="row-title"[^>]*>Creep</h2>', creep)
    assert 'alt="from Ultimate Guitar"' in creep and ">Radiohead</button>" in creep
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
    artists: rows.map((r) => r.querySelector(".row-artist") ? Math.round(box(r.querySelector(".row-artist")).width) : null),
    whole: rows.map((r) => r.querySelector(".row-artist") ? r.querySelector(".row-artist").scrollWidth : null),
    lines: rows.map(lines),
    widths: rows.map((r) => Math.round(box(r).width)),
    page: window.innerWidth,
    screen: window.innerHeight,
    scroll: document.documentElement.scrollWidth,
  }));
})();
"""


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
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
