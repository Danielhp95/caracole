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


def test_a_songs_own_version_is_the_transposition_its_line_shows(conn, cfg):
    # [version] wins over [transpose]: its PDF is moved by the version's t
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    o = Overrides(transpose={s.key: -2}, version={s.key: "t=3&mode=dorian"})
    assert songs_of(page(conn, cfg, o))["Soda Stereo - De Música Ligera"]["transpose"] == 3


def test_a_version_kept_by_its_key_shows_what_its_pdf_is_moved_by(conn, cfg):
    # Its key moves each sheet by its own: the line says what the PDF was made in, once it was
    from helpers.rendered import fake_chordpro

    from caracole.render import render_all

    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet_json(conn, cfg, s, AM_F_C_G)  # A minor
    o = Overrides(transpose={s.key: 3}, version={s.key: "key=G&mode=dorian&capo=0"})
    assert songs_of(page(conn, cfg, o))[s.display]["transpose"] == 0  # no PDF yet
    assert render_all(conn, cfg, o, runner=fake_chordpro).rendered == 1
    assert songs_of(page(conn, cfg, o))[s.display]["transpose"] == -2  # down to G, its [transpose] left out


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


def test_each_song_has_its_jump_letters_by_artist_and_by_title(conn, cfg):
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    han = add_song(conn, "宋冬野", "斑马，斑马")
    beatles = add_song(conn, "The Beatles", "Yesterday")
    pac = add_song(conn, "2Pac", "Changes")
    songs = songs_of(page(conn, cfg))
    # The A-Z strip's letters come from the sort keys: "The Beatles" is under B, 宋冬野 under S.
    assert [songs[s.display]["artistLetter"] for s in (soda, han, beatles, pac)] == ["S", "S", "B", "#"]
    assert [songs[s.display]["titleLetter"] for s in (soda, han, beatles, pac)] == ["D", "B", "Y", "C"]
    assert not {"monogram", "hue"} & set(songs[soda.display])  # the cards' badges went with them


def test_each_song_names_its_identity_which_the_served_search_groups_and_merges_by(conn, cfg):
    # Typed into the served page's bar, a song of yours and the sites' rows of its artist share a header: the
    # artist part of its identity key is their rows' artist key (/api/search).
    from caracole.normalize import identity_key

    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    han = add_song(conn, "宋冬野", "斑马，斑马")
    songs = songs_of(page(conn, cfg))
    assert songs[soda.display]["identity"] == soda.key == identity_key("Soda Stereo", "De Música Ligera")
    assert songs[han.display]["identity"] == han.key


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


def bar_of(html):
    found = re.search(r'<div class="searchbar"[^>]*>.*?</div>\n</div>', html, re.S)
    assert found, html[:3000]
    return found.group(0)


def test_the_bar_has_a_status_line_and_no_search_all_button_in_both_pages(conn, cfg):
    # Served, typing searches the sites too; on the file, Enter shows the line that does: no button for either.
    from caracole.library_page import WebControls

    add_song(conn, "Radiohead", "Creep")
    for html in (page(conn, cfg), build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))):
        bar = bar_of(JSON_BLOCK.sub("", html))
        assert 'id="all"' not in bar and "Search all" not in html
        status = re.search(r'<p class="bar-status" id="bar-status"[^>]*>', bar)
        assert status and 'aria-live="polite"' in status.group(0)
        assert re.search(r'<input id="q"[^>]*aria-describedby="bar-status"', bar, re.S)
        assert re.search(r'<section class="results" id="results" aria-label="Search results">', html)


def test_the_request_form_is_under_the_results_not_above_the_bar(conn, cfg):
    from caracole.library_page import WebControls

    html = JSON_BLOCK.sub("", build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok")))
    bar, results, form = html.index('id="q"'), html.index('id="results"'), html.index('action="/request"')
    assert bar < results < form < html.index('class="toolbar"')
    box = re.search(r'<details class="request" id="request-box">\s*<summary>(.*?)</summary>', html, re.S)
    assert box and "Not in the list? Request it by name" in box.group(1)
    # The songs just requested show under the bar in both modes, above the results and the grid.
    assert html.index('id="q"') < html.index('id="requested"') < html.index('id="results"')
    assert 'href="/lookup"' not in html  # the bar is the way in: no Look up link in the masthead


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


def test_a_songs_exports_are_listed_after_its_sheets_pdfs_by_their_versions(conn, cfg):
    # The PDFs caracole made in other versions (render.py render_version, recorded under their labels), after
    # the sheet's viewer and PDF, each named by its version; never a "sheet (…).pdf" caracole didn't make, nor
    # one recorded that is gone from the folder.
    from caracole.library_page import result_cards
    from caracole.render import EXPORT_KV

    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    v = version(conn, s, 85053)
    keep_file(conn, cfg.library_dir, song=s, version_id=v, name="sheet.txt", data=b"[G]la", rank=1)
    put(cfg, s, "sheet.html", "sheet.pdf", "sheet (G Dorian, capo 0).pdf", "sheet (B Minor, capo 2).pdf",
        "sheet (yours).pdf", "lyrics.txt")
    db.kv_set_json(conn, f"{EXPORT_KV}{s.id}", {
        "G Dorian, capo 0": {"pdf": "sheet (G Dorian, capo 0).pdf", "query": "t=0&mode=dorian"},
        "B Minor, capo 2": {"pdf": "sheet (B Minor, capo 2).pdf", "query": "t=4&capo=2"},
        "A Major, capo 0": {"pdf": "sheet (A Major, capo 0).pdf", "query": "t=2"},  # deleted on a device
    })
    files = songs_of(page(conn, cfg))[s.display]["files"]
    assert [(f["name"], f["label"], f["primary"]) for f in files] == [
        ("sheet.html", "Sheet viewer", True), ("sheet.pdf", "Sheet PDF", False),
        ("sheet (B Minor, capo 2).pdf", "Sheet PDF, B Minor, capo 2", False),
        ("sheet (G Dorian, capo 0).pdf", "Sheet PDF, G Dorian, capo 0", False),
        ("sheet.txt", "Sheet text", False), ("lyrics.txt", "Lyrics", False)]
    # Each export says its version, which its line's "⋯" lists it by (under Versions); no other file has one.
    assert [f.get("version") for f in files] == [None, None, "B Minor, capo 2", "G Dorian, capo 0", None, None]
    export = next(f for f in files if f["name"] == "sheet (G Dorian, capo 0).pdf")
    assert export["href"] == "Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet%20%28G%20Dorian%2C%20capo%200%29.pdf"
    assert export["source"] == "ug"  # made from the sheet: where it came from
    assert [f["name"] for f in result_cards(conn, cfg, [s])[s.id]["links"]] == [f["name"] for f in files]


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


def test_a_song_picked_on_lacuerda_says_tonights_run_gets_that_sheet_not_that_it_is_missing(conn, cfg):
    # UG has no song of theirs by that name, which is no matter: the sheet is the one picked on LaCuerda.
    from caracole.overrides import LaCuerdaPick

    s = add_song(conn, "Andrés Calamaro", "Flaca")
    update_song(conn, s.id, match_decision="not_found")
    picked = Overrides(lacuerda={s.key: LaCuerdaPick("andres_calamaro", "flaca")})
    card = songs_of(page(conn, cfg, picked))[s.display]
    assert card["lacuerda"] == {"label": "the sheet you picked on LaCuerda",
                                "href": "https://acordes.lacuerda.net/andres_calamaro/flaca"}
    assert "notFound" not in card and not card["review"]
    update_song(conn, s.id, lacuerda_checked_at="2026-10-18T03:36:00Z")  # LaCuerda had no such sheet: the usual
    card = songs_of(page(conn, cfg, picked))[s.display]
    assert card["lacuerda"] is None and card["notFound"] is True


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


def test_each_song_carries_its_titles_initials_for_the_search_box(conn, cfg):
    wish = add_song(conn, "Pink Floyd", "Wish You Were Here")
    dont = add_song(conn, "Queen", "Don't Stop Me Now")
    one = add_song(conn, "Radiohead", "Creep")
    han = add_song(conn, "宋冬野", "斑马，斑马")
    songs = songs_of(page(conn, cfg))
    assert songs[wish.display]["initials"] == "wywh" and songs[dont.display]["initials"] == "dsmn"
    assert songs[han.display]["initials"] == "bmbm"  # by pinyin
    assert "initials" not in songs[one.display]  # one word: no initials worth typing


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


def line_of(shown: str, title: str) -> str:
    """The rendered line (an ``article.line``) whose heading is ``title``."""
    for line in re.findall(r'<article class="line[^"]*"[^>]*>.*?</article>', shown, re.S):
        if re.search(r"<h3[^>]*>" + re.escape(title) + "</h3>", line):
            return line
    raise AssertionError(f"no line {title!r} in {shown[-1500:]}")


def titles_in(shown: str) -> list[str]:
    """The songs' titles, in the order they show."""
    return re.findall(r"<h3[^>]*>([^<]*)</h3>", shown)


def panel_of(line: str) -> str:
    """What a line's "⋯" holds."""
    found = re.search(r'<div class="line-panel"[^>]*>.*', line, re.S)
    assert found, line
    return found.group(0)


@in_chromium
def test_the_page_renders_and_filters_in_a_real_browser(conn, cfg, tmp_path):
    s = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, s, "lyrics.txt")
    add_song(conn, "Soda Stereo", "De Música Ligera")
    add_song(conn, "Radiohead", "Creep</script><b>x</b>")
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    shown = listing(dump_dom(path, tmp_path))
    assert shown.count("<article") == 3  # one line per song
    assert "Creep&lt;/script&gt;&lt;b&gt;x&lt;/b&gt;" in shown  # shown as text, never as markup
    assert "<b>x</b>" not in shown

    for query, title in (("ban ma", "斑马，斑马"), ("musica", "De Música Ligera"), ("MÚSICA", "De Música Ligera")):
        shown = listing(dump_dom(path, tmp_path, "#q=" + quote(query)))
        assert shown.count("<article") == 1, query
        assert title in shown


@in_chromium
def test_a_lines_youtube_note_links_its_video_in_a_real_browser(conn, cfg, tmp_path, monkeypatch):
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
        return sorted(titles_in(listing(dump_dom(path, tmp_path, "#q=" + quote(query)))))

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
        assert sorted(titles_in(shown)) == ["Hysteria", "Lucky"], spelling
    shown = listing(dump_dom(path, tmp_path, "#key=" + quote("F#") + "&q=lucky"))
    assert "No songs in F# major match" not in shown and shown.count("<article") == 2  # no such key: any


@in_chromium
def test_the_letter_strip_lists_the_artists_initials_once_there_are_many_songs(conn, cfg, tmp_path):
    for artist, title in (("The Beatles", "Yesterday"), ("Radiohead", "Creep"), ("Soda Stereo", "Música"),
                          ("宋冬野", "斑马，斑马")):
        add_song(conn, artist, title)
    few = write_library_page(cfg.library_dir, page(conn, cfg))
    assert re.search(r'<nav[^>]*id="jump"[^>]*hidden', dump_dom(few, tmp_path))  # four songs: scroll, no letters
    for n in range(36):
        add_song(conn, "Radiohead", f"Song {n}")
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    dom = dump_dom(path, tmp_path)
    strip = re.search(r'<nav[^>]*id="jump"[^>]*>(.*?)</nav>', dom, re.S)
    assert strip and "hidden" not in strip.group(0)[:60], dom[-2000:]
    assert re.findall(r"<button[^>]*>([^<]+)</button>", strip.group(1)) == ["B", "R", "S"]
    shown = listing(dump_dom(path, tmp_path, "#sort=recent"))
    assert shown.count("<article") == 40
    assert re.search(r'<nav[^>]*id="jump"[^>]*hidden', dump_dom(path, tmp_path, "#sort=recent"))
    # A search that shows a few of them leaves the letters out too.
    assert re.search(r'<nav[^>]*id="jump"[^>]*hidden', dump_dom(path, tmp_path, "#q=creep"))


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
    assert 'aria-label="Fetch Creep by Radiohead now"' in forms[0]
    # The song with a job queued says so instead, on a line of its own.
    assert "Fetching" in line_of(shown, "Wonderwall") and "/fetch" not in line_of(shown, "Wonderwall")
    # The song caracole fetch would refuse until it's reviewed says so instead of offering a fetch.
    held = line_of(shown, "Bohemian Rhapsody")
    assert re.search(r"<button[^>]*disabled[^>]*>Review first</button>", held) and "/fetch" not in held


@in_chromium
def test_the_served_page_offers_a_remove_on_every_line(conn, cfg, tmp_path):
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
    going = line_of(shown, "Wonderwall")
    assert "Removing…" in going and "/remove" not in going
    assert "/fetch" not in going  # a fetch now would run before the removal and fetch for nothing
    # The page on disk has no server to remove anything.
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW))
    assert "/remove" not in listing(dump_dom(path, tmp_path))


# Notes how a line's Removing… and a line's Fetching… look.
LOOKS = """
(() => {
  const look = (node) => {
    const style = getComputedStyle(node);
    return [style.color, style.fontWeight].join(" ");
  };
  const removing = document.querySelector("#list .line-busy");
  const fetching = document.querySelector("#list .progress");
  document.body.setAttribute("data-removing", removing ? look(removing) : "none");
  document.body.setAttribute("data-fetching", fetching ? look(fetching) : "none");
})();
"""


@in_chromium
def test_a_lines_removing_looks_like_its_fetching_line(conn, cfg, tmp_path):
    # Removing…, where a line's button was, and a request's line under another are both "something runs": one look.
    from caracole.library_page import WebControls

    fetching = add_song(conn, "Oasis", "Wonderwall")
    going = add_song(conn, "The Beatles", "Yesterday")
    controls = WebControls(csrf="tok", busy=frozenset({fetching.id}), active=2, removing=frozenset({going.id}))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(html, LOOKS)), tmp_path)
    removing = re.search(r'<body[^>]*data-removing="([^"]*)"', dom).group(1)
    line = re.search(r'<body[^>]*data-fetching="([^"]*)"', dom).group(1)
    assert removing != "none" and line != "none", dom[-1500:]
    *color, weight = removing.split(" ")
    assert color == line.split(" ")[:-1] and int(weight) >= 600


def with_script(html: str, script: str) -> str:
    """The page with a test's script after its own, allowed by its hash."""
    csp = csp_of(html)
    html = html.replace(csp, csp.replace("script-src ", f"script-src {sha(script)} "))
    return html.replace("</body>", f"<script>{script}</script>\n</body>")


# Clicks the A-Z strip's "R" and notes where the focus is then: the group of R's first artist.
JUMP = """
(() => {
  const r = Array.from(document.querySelectorAll("#jump button")).find((b) => b.textContent === "R");
  r.click();
  const group = document.activeElement.closest("section.artist");
  document.body.setAttribute("data-focus", group ? group.dataset.artist : "none");
})();
"""


@in_chromium
def test_a_screen_reader_hears_each_artist_and_song_and_a_jump_moves_the_focus(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    add_song(conn, "The Beatles", "Yesterday")
    add_song(conn, "Radiohead", "Creep")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    path = write_library_page(cfg.library_dir, with_script(html, JUMP))
    dom = dump_dom(path, tmp_path)
    shown = listing(dom)
    # Under the page's h1, each artist is a heading, each of their songs one under it; each button names its song.
    heads = [re.sub(r"<[^>]+>", "", h) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", shown, re.S)]
    assert heads == ["The Beatles · you have 1", "Radiohead · you have 1"] and titles_in(shown) == ["Yesterday", "Creep"]
    assert 'aria-label="Fetch Creep by Radiohead now"' in shown
    assert 'aria-label="Fetch Yesterday by The Beatles now"' in shown
    # After a jump, the next Tab goes on from the artist jumped to, not from the strip.
    assert re.search(r'<body[^>]*data-focus="radiohead"', dom), dom[-1500:]


# Clicks Queen's name over their songs, then notes the titles shown and the chip.
ARTIST_CLICK = """
(() => {
  document.querySelector('#list section.artist[data-artist="queen"] h2 button.artist').click();
  const titles = Array.from(document.querySelectorAll("#list article h3")).map((h) => h.textContent);
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


@in_chromium
def test_the_file_shows_a_reviews_candidates_and_the_line_that_picks_one(conn, cfg, tmp_path):
    index_tabs(conn, (1, "radiohead", "creep", "chords"), (3, "radiohead", "creep", "tabs"))
    in_review(conn)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    card = line_of(listing(dump_dom(path, tmp_path)), "Crep")
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
    card = line_of(shown, "Crep")
    assert "Review first" not in card and "/fetch" not in card
    # Its button opens the picker, under its "⋯", folded as "3 candidates".
    assert re.search(r'<div class="line-action"><button class="btn small line-pick"[^>]*>Pick the match</button>', card)
    assert re.search(r'<summary class="picker-open"[^>]*>3 candidates</summary>', panel_of(card))
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
    plain = line_of(shown, "Bohemian Rhapsody")
    assert re.search(r"<button[^>]*disabled[^>]*>Review first</button>", plain) and "picker" not in plain


@in_chromium
def test_the_served_picker_of_a_song_being_fetched_is_read_only_until_its_request_ends(conn, cfg, tmp_path):
    # POST /review would refuse a pick while the song's request waits or runs: the card offers none.
    from caracole.library_page import WebControls

    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    s = in_review(conn)
    controls = WebControls(csrf="tok", busy=frozenset({s.id}), active=1, held=frozenset({s.id}))
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    card = line_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
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
    card = line_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
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
    card = line_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
    assert 'data-status="found"' in card and "/fetch" not in card
    form = re.search(r'<form[^>]*action="/review"[^>]*>(.*?)</form>', card, re.S)
    assert form and f'name="song" value="{s.id}"' in form.group(1)
    radios = re.findall(r'<input type="radio" name="pick" value="([^"]*)"', form.group(1))
    assert radios == ["radiohead/creep", "jeff-buckley/creep", "misc-musicals/creep-the-musical", "none"]


# Opens the first picker from its line's "⋯", by its summary, as a click or Enter does, then notes where the focus
# went.
OPEN_PICKER = """
(() => {
  const picker = document.querySelector("#list details.picker");
  picker.closest("article").querySelector(".line-more").click();
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
def test_the_served_line_of_a_song_not_found_links_to_its_search_hits(conn, cfg, tmp_path):
    from caracole.library_page import WebControls

    lost = add_song(conn, "Radio Head", "Crep")
    update_song(conn, lost.id, match_decision="not_found")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    card = line_of(listing(dump_dom(write_library_page(cfg.library_dir, html), tmp_path)), "Crep")
    assert re.search(rf'<a class="btn small" href="/review\?song={lost.id}"[^>]*>Look in the index</a>',
                     panel_of(card))
    assert "/fetch" in card  # its artist's UG page may have it: Fetch now still asks
    on_file = line_of(listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path)), "Crep")
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
    from helpers.targets import UNFOLD

    sourced_library(conn, cfg)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), UNFOLD + MARKS))
    marks = marks_of(dump_dom(path, tmp_path))
    ug = [m for m in marks if m["source"] == "ug"]
    assert ug and all(m["tag"] == "img" and m["loaded"] and m["name"] == "from Ultimate Guitar" for m in ug), ug
    # The line says once where its sheet came from; its files from there carry no mark of their own...
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
    # A line's own marks: where its sheet came from, then its files' other sites, each once (LRCLIB's lyrics).
    creep = [m["source"] for m in marks if m["link"] is None and m["source"] in ("ug", "lrclib")]
    assert creep == ["ug", "lrclib"], marks
    # A site's icon is 16 px; its badge, there until the icon is in, is bigger, its letters
    # big enough to read and in the text's own colour.
    assert {m["width"] for m in ug} == {16}, ug
    badges = [m for m in marks if m["tag"] == "span"]
    assert badges and all(m["width"] >= 18 and m["font"] >= 10 for m in badges), badges
    assert all(m["colour"] == m["text_colour"] for m in badges if m["text"] in ("LC", "LR", "YT")), badges


# --- a song's title opens its sheet, as its line's button, the primary one, does ------------------------


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
def test_a_songs_title_opens_its_sheet_and_its_lines_button_does_too(conn, cfg, tmp_path):
    filed_library(conn, cfg)
    shown = listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path))
    # The title opens the viewer, else the PDF: out of the Tab order, as the line's button opens the same.
    creep = line_of(shown, "Creep")
    title = re.search(r'<a class="line-title" ([^>]*)><h3[^>]*>Creep</h3></a>', creep)
    assert title and 'href="Radiohead/Creep/sheet.html"' in title.group(1) and 'tabindex="-1"' in title.group(1)
    main = re.search(r'<div class="line-action"><a class="btn small primary" ([^>]*)>Open</a>', creep)
    assert main and 'href="Radiohead/Creep/sheet.html"' in main.group(1), creep
    assert 'aria-label="Open Creep by Radiohead"' in main.group(1) and 'title="Sheet viewer"' in main.group(1)
    wonderwall = line_of(shown, "Wonderwall")
    assert re.search(r'<a class="line-title" href="Oasis/Wonderwall/sheet.pdf"[^>]*><h3[^>]*>Wonderwall</h3></a>',
                     wonderwall), wonderwall
    opened = re.search(r'<a class="btn small primary" ([^>]*)>Open PDF</a>', wonderwall)
    assert opened and 'aria-label="Open PDF of Wonderwall by Oasis"' in opened.group(1), wonderwall
    assert '<a class="line-title"' not in line_of(shown, "Yesterday")  # no file: a plain title


# Notes how each line is laid out: how tall its title's link is against its button, how many lines its title
# takes, and its button's colour against the accent's.
LINE_LAYOUT = """
(() => {
  const box = (n) => n.getBoundingClientRect();
  const lines = {};
  for (const l of document.querySelectorAll("#list .line")) {
    const h3 = l.querySelector("h3");
    const title = l.querySelector("a.line-title");
    const main = l.querySelector(".line-action > a");
    lines[h3.textContent] = {
      title: title ? Math.round(box(title).height) : null,
      button: main ? Math.round(box(main).height) : null,
      lines: Math.round(box(h3).height / parseFloat(getComputedStyle(h3).lineHeight)),
      colour: main ? getComputedStyle(main).color : null,
    };
  }
  const accent = document.createElement("span");
  accent.style.color = "var(--accent)";
  document.body.appendChild(accent);
  document.body.setAttribute("data-lines", JSON.stringify({ lines, accent: getComputedStyle(accent).color,
    page: innerWidth, scroll: document.documentElement.scrollWidth }));
  accent.remove();
})();
"""


@pytest.mark.parametrize("size", ["390,844", "1280,800"])
@in_chromium
def test_a_lines_title_is_as_easy_to_hit_as_its_button(conn, cfg, tmp_path, size):
    import html as html_module

    filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), LINE_LAYOUT))
    found = re.search(r'data-lines="([^"]*)"', dump_dom(path, tmp_path, size=size))
    assert found
    laid = json.loads(html_module.unescape(found.group(1)))
    lines = laid["lines"]
    assert laid["scroll"] <= laid["page"], laid
    # The title's link fills its line, as tall as the button beside it, and the title stays on one line.
    for title in ("Creep", "Wonderwall"):
        assert lines[title]["title"] >= lines[title]["button"] > 0 and lines[title]["lines"] == 1, lines
        assert lines[title]["colour"] == laid["accent"], lines  # the sheet is the line's primary action
    assert lines["Yesterday"]["title"] is None, lines


@in_chromium
def test_a_wanted_songs_auto_sheet_opens_from_its_title_and_leads_its_files_under_fetch_now(conn, cfg, tmp_path):
    line = line_of(listing(dump_dom(served_auto_sheet(conn, cfg), tmp_path)), "斑马，斑马")
    # Fetch now is the line's one primary button; its title opens the auto sheet, which also leads its files.
    assert re.search(r'<div class="line-action"><form[^>]*action="/fetch"', line), line
    assert line.count("btn primary") == 1, line
    assert re.search(r'<a class="line-title" ' + AUTO_VIEWER + r' tabindex="-1">', line), line
    assert link_texts(panel_of(line))[:1] == ["Auto sheet viewer"], line


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


# --- a line opens its sheet from one button; its other files wait under its "⋯" ---------------------------


@in_chromium
def test_a_line_opens_its_sheet_from_one_button_and_its_other_files_wait_under_its_menu(conn, cfg, tmp_path):
    filed_library(conn, cfg)
    shown = listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path))

    creep = line_of(shown, "Creep")
    top, menu = creep.split('class="line-panel"', 1)
    # One button opens the viewer, as the title does.
    assert link_texts(top) == ["Open"], top
    # Every other file, and the Guitar Pro versions to download, under "⋯": closed, small.
    assert re.search(r'<button class="line-more"[^>]*aria-expanded="false"', top) and re.search(r'^[^>]*hidden', menu)
    assert link_texts(menu) == ["Sheet PDF", "Sheet text", "ChordPro", "Lyrics", "Timed lyrics", "Guitar Pro 1",
                                "Tab", "Info", "Guitar Pro ver 1 · 4.5★ · 12 votes ↗"], menu
    assert '<p class="subhead">Files</p>' in menu and '<p class="subhead">Guitar Pro to download</p>' in menu
    assert all(cls.startswith("btn small") for cls in re.findall(r'<a class="([^"]*)"', menu)), menu
    # A sheet with no viewer opens its PDF; nothing else to list.
    wonderwall = line_of(shown, "Wonderwall")
    assert link_texts(wonderwall.split('class="line-panel"', 1)[0]) == ["Open PDF"]
    assert link_texts(panel_of(wonderwall)) == [] and '<p class="subhead">Files</p>' not in wonderwall
    # A song with no file has nothing to open.
    yesterday = line_of(shown, "Yesterday")
    assert ">Open" not in yesterday and '<p class="subhead">Files</p>' not in yesterday


@in_chromium
def test_a_lines_menu_lists_the_sheets_versions_apart_from_its_files(conn, cfg, tmp_path):
    # The PDFs caracole made of the sheet in other versions (Export PDF of this version) are the song's versions:
    # under its "⋯", by their versions, before its other files, which no longer list them.
    from caracole.render import EXPORT_KV

    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet_json(conn, cfg, s, "Words\n", raw={"tonality_name": "E"})
    update_song(conn, s.id, status="found")
    put(cfg, s, "sheet.html", "sheet.pdf", "sheet (G Dorian, capo 0).pdf", "sheet (B Minor, capo 2).pdf")
    db.kv_set_json(conn, f"{EXPORT_KV}{s.id}", {
        "G Dorian, capo 0": {"pdf": "sheet (G Dorian, capo 0).pdf", "query": "t=0&mode=dorian"},
        "B Minor, capo 2": {"pdf": "sheet (B Minor, capo 2).pdf", "query": "t=4&capo=2"},
    })
    plain = add_song(conn, "Radiohead", "Creep")
    keep_sheet_json(conn, cfg, plain, "Words\n", raw={"tonality_name": "G"}, tab_id=2)
    update_song(conn, plain.id, status="found")
    put(cfg, plain, "sheet.html", "sheet.pdf")
    shown = listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path))

    soda = line_of(shown, "De Música Ligera")
    assert link_texts(soda.split('class="line-panel"', 1)[0]) == ["Open"]
    groups = re.findall(r'<p class="subhead">([^<]*)</p><div class="actions">(.*?)</div>', panel_of(soda), re.S)
    assert [(heading, link_texts(links)) for heading, links in groups][:2] == [
        ("Versions", ["B Minor, capo 2", "G Dorian, capo 0"]), ("Files", ["Sheet PDF", "Sheet text"])], groups
    versions = dict(groups)["Versions"]
    assert 'href="Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet%20%28G%20Dorian%2C%20capo%200%29.pdf"' in versions
    # A song with no export has no Versions.
    assert '<p class="subhead">Versions</p>' not in line_of(shown, "Creep")


@in_chromium
def test_on_a_phone_files_open_with_a_tap_the_title_opens_the_viewer_and_tab_skips_the_title(conn, cfg, tmp_path):
    from helpers.browser import Browser, BrowserError

    creep = filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    try:
        phone = Browser(tmp_path / "chrome", width=390, height=844, mobile=True)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    line = f'#list .line[data-id="{creep.id}"]'
    with phone:
        phone.open(path.as_uri())
        assert phone.wait(f"document.querySelector({json.dumps(line)}) !== null")
        q = f"document.querySelector({json.dumps(line)})"
        # A thumb's target: "⋯", and each file once it's open.
        assert phone.js(f"{q}.querySelector('.line-more').getBoundingClientRect().height") >= 44
        phone.click(line + " .line-more")
        assert phone.wait(f"!{q}.querySelector('.line-panel').hidden")
        heights = phone.js(f"Array.from({q}.querySelectorAll('.line-panel a')).map((a) => a.getBoundingClientRect().height)")
        assert len(heights) == 9 and min(heights) >= 44, heights
        # From the line, Tab goes to Open: the title opens the same, and isn't a stop of its own.
        phone.js(f"{q}.focus()")
        phone.press("Tab")
        assert phone.js("document.activeElement.textContent") == "Open"
        phone.click(line + " .line-title")
        assert phone.wait("location.pathname.endsWith('/Radiohead/Creep/sheet.html')")


@in_chromium
def test_an_artists_name_shows_it_is_a_filter_over_their_songs_and_on_a_line_alone(conn, cfg, tmp_path):
    filed_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    grouped = listing(dump_dom(path, tmp_path))
    head = re.search(r'<section class="artist" data-artist="radiohead"[^>]*><h2[^>]*>(.*?)</h2>', grouped, re.S)
    flat = line_of(listing(dump_dom(path, tmp_path, "#sort=title")), "Creep")  # no group over it: its own
    for shown in (head.group(1), flat):
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
    file), a review's candidates to pick, a wanted song with an auto sheet, a songbook, the form to
    request a song, and the A-Z strip, which takes 40 songs shown (``JUMP_FROM``)."""
    from caracole.library_page import WebControls
    from caracole.songbook import FILE_NAME, make_songbook

    filed_library(conn, cfg)
    index_tabs(conn, (1, "radiohead", "creep", "chords"), (3, "radiohead", "creep", "tabs"))
    in_review(conn)
    auto = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, auto, "sheet (auto).txt", "sheet (auto).html", "sheet (auto).pdf")
    for n in range(35):  # wanted, no file: last in the artists' order
        add_song(conn, "Zucchero", f"Song {n:02d}")
    # Songs of it without a sheet: served, its card offers to get them now.
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Radiohead - Creep", "Oasis - Wonderwall",
                                                             "Zucchero - Song 00"])
    controls = WebControls(csrf="tok") if served else None
    return build_library_page(conn, cfg, Overrides(), NOW, controls=controls)


# On the file on disk, Select a song, name a songbook and make it: the bar then shows the command to run. On a
# phone the name field waits under "Make songbook…".
MAKE_FROM_DISK = """
document.querySelector(".pick-toggle").click();
document.querySelector("#list .pick input").click();
if (document.querySelector(".pick-open").checkVisibility()) document.querySelector(".pick-open").click();
document.querySelector(".pick-name").value = "Campfire 2";
document.querySelector(".pickbar-form button[type=submit]").click();
document.body.setAttribute("data-command", String(!document.querySelector(".pick-command").hidden));
"""


@in_chromium
def test_the_select_bar_of_the_file_on_disk_and_its_command_on_a_touch_phone(conn, cfg, tmp_path):
    from helpers.targets import UNFOLD, noted, noting, small_targets, weak_edges

    # The search field is the search bar's, which another change redraws. While selecting, a line is one
    # target, its title and its artist's name no targets of their own.
    exempt = ".selecting [data-picker] .line-title, .selecting [data-picker] .artist"
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
  return { line: tall("#list .line-action .btn"), more: tall("#list .line-more"), artist: tall("#list button.artist"),
           file: tall("#list .line-panel .btn.small"), letter: tall("#jump button"), chip: tall(".chip"),
           menu: tall("#sort") };
})()
"""


@in_chromium
def test_a_mouse_keeps_the_compact_controls(conn, cfg, tmp_path):
    from helpers.targets import UNFOLD, noted, noting

    html = with_script(every_control(conn, cfg), UNFOLD + noting("data-compact", COMPACT))
    heights = noted(dump_dom(write_library_page(cfg.library_dir, html), tmp_path, size="1280,800"), "data-compact")
    assert all(h is not None and h < 44 for h in heights.values()), heights


# The songs' box's border against a field's, both as the browser draws them.
BORDERS = """
({ box: getComputedStyle(document.querySelector("#list .groups")).borderTopColor,
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
    assert borders["box"] != borders["field"], borders  # the songs' box keeps its soft border: it is no control


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
def test_a_controls_edge_is_three_to_one_against_every_background_a_box_keeps_its_soft_border(dark):
    from caracole.library_page import BASE_STYLE

    tokens = css_tokens(BASE_STYLE, dark=dark)
    for background in ("--bg", "--surface", "--raised"):
        assert contrast(tokens["--control-edge"], tokens[background]) >= 3, (background, tokens)
    assert contrast(tokens["--border"], tokens["--surface"]) < 3  # boxes and dividers: no control's edge


def row_of(shown: str, title: str) -> str:
    found = re.search(r'<article class="row"[^>]*>(?:(?!</article>).)*?' + re.escape(title) + r".*?</article>",
                      shown, re.S)
    assert found, shown[-2000:]
    return found.group(0)


@in_chromium
def test_a_line_shows_its_title_status_key_marks_and_main_action(conn, cfg, tmp_path):
    sourced_library(conn, cfg)
    shown = listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path))
    assert shown.count('<article class="line') == 4
    creep = line_of(shown, "Creep")
    top = creep.split('class="line-panel"', 1)[0]
    assert re.search(r'<h3[^>]*>Creep</h3>', top) and 'alt="from Ultimate Guitar"' in top
    assert "Key G major (from the tab)" in top and ">Found<" in top
    main = re.search(r'<div class="line-action"><a ([^>]*)>Open PDF</a>', creep)
    assert main and 'href="Radiohead/Creep/sheet.pdf"' in main.group(1)
    assert 'aria-label="Open PDF of Creep by Radiohead"' in main.group(1)
    # The rest waits behind a small button, closed.
    more = re.search(r'<button class="line-more"[^>]*aria-expanded="false"[^>]*aria-controls="([^"]+)"', creep)
    assert more and re.search(rf'<div class="line-panel" id="{more.group(1)}" hidden', creep)
    assert ">More for Creep<" in creep and "Lyrics" in panel_of(creep)
    soda = line_of(shown, "De Música Ligera")
    assert 'aria-label="from LaCuerda"' in soda and ">Open text<" in soda
    wonderwall = line_of(shown, "Wonderwall")
    assert ">Wanted<" in wonderwall and "line-action" in wonderwall and "Find the chords" in panel_of(wonderwall)


# Measures the lines: each one's height, its artist's width and whole width, and how many lines its parts take (by
# their middles), the page's width and how far it scrolls sideways.
ROWS = """
(() => {
  const lines = Array.from(document.querySelectorAll("#list .line"));
  const box = (node) => node.getBoundingClientRect();
  const name = (l) => l.querySelector(".line-by .artist-name") || l.querySelector(".line-by");
  const rows = (l) => {
    const parts = l.querySelectorAll(".line-title h3, .line-by, .line-status > *, .line-key, .line-sources > *, " +
      ".line-action > *, .line-more");
    const middles = Array.from(parts).filter((p) => p.checkVisibility() && box(p).height > 0)
      .map((p) => box(p).top + box(p).height / 2).sort((a, b) => a - b);
    return middles.filter((m, i) => i === 0 || m - middles[i - 1] > 6).length;
  };
  document.body.setAttribute("data-layout", JSON.stringify({
    artists: lines.map((l) => (name(l) ? Math.round(box(name(l)).width) : null)),
    whole: lines.map((l) => (name(l) ? name(l).scrollWidth : null)),
    lines: lines.map(rows), page: window.innerWidth, scroll: document.documentElement.scrollWidth,
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
def test_an_auto_sheet_from_youtube_audio_shows_where_it_came_from(conn, cfg, tmp_path, monkeypatch):
    from helpers.fake_ytdlp import route_on

    on, _ = route_on(cfg, tmp_path, monkeypatch)
    youtube_auto_sheet(conn, on)
    bought = add_song(conn, "宋冬野", "斑马，斑马")  # a purchase's auto sheet beside it: the audio model's ♪
    put(on, bought, "sheet (auto).txt", "sheet (auto).pdf")
    update_song(conn, bought.id, status="found")
    html = page(conn, on)
    assert songs_of(html)["Radiohead - Creep"]["source"] == "youtube"
    shown = listing(dump_dom(write_library_page(on.library_dir, html), tmp_path))

    line = line_of(shown, "Creep")
    assert re.search(r'<span class="line-sources"><span class="source letters"[^>]*aria-label="from YouTube"', line), line
    # Its button says what it opens ("Auto sheet PDF"), as its mark says where that came from: no badge. A touch
    # screen shows no title, and YouTube's mark says only where the audio came from: the button's name says it is an
    # auto sheet too, for a screen reader.
    assert re.search(r'<div class="line-action"><a [^>]*title="Auto sheet PDF"[^>]*>Open PDF</a>', line), line
    assert 'aria-label="Open PDF of Creep by Radiohead, an auto sheet"' in line, line
    assert ">Auto sheet<" not in line
    # The video waits behind the line's ⋯, with the rest of what a card said.
    note = re.search(r'<p class="youtube">(.*?)</p>', panel_of(line), re.S)
    assert note and note.group(1).startswith("Auto sheet from YouTube audio · <a"), line
    assert 'href="https://www.youtube.com/watch?v=XFkzRNyygfk"' in note.group(1)
    assert "Creep (Radiohead - Topic) ↗" in note.group(1)
    zebra = line_of(shown, "斑马，斑马")
    assert 'aria-label="from the audio (auto-chords)"' in zebra
    assert 'aria-label="Open PDF of 斑马，斑马 by 宋冬野, an auto sheet"' in zebra, zebra


def layout_of(dom: str) -> dict:
    import html as html_module

    found = re.search(r'data-layout="([^"]*)"', dom)
    assert found, dom[-2000:]
    return json.loads(html_module.unescape(found.group(1)))


@in_chromium
def test_a_phones_line_keeps_its_artist_beside_its_status_key_and_marks(conn, cfg, tmp_path):
    # Sorted by title, a line has no artist's group over it: the fullest second lines, an auto sheet's mark, a key
    # and Needs review; a long name beside Needs review.
    abba = add_song(conn, "ABBA", "Dancing Queen")
    auto = upsert_version(conn, provider="auto", tab_id=str(abba.id), song_id=abba.id, slot="sheet", kind="auto",
                          rating=0, votes=0, version=1, label=None, url="file:///x.flac",
                          raw={"key": "A major"}, now="2026-10-18T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=abba, version_id=auto, name="sheet (auto).txt", data=b"A\nWords\n", rank=1)
    put(cfg, abba, "sheet (auto).pdf", "lyrics.txt")
    update_song(conn, abba.id, status="found", review=True)
    queen = add_song(conn, "Queen", "Bohemian Rhapsody")
    keep_sheet_json(conn, cfg, queen, "Words\n", raw={"tonality_name": "Bb"})
    put(cfg, queen, "sheet.pdf", "lyrics.txt")
    update_song(conn, queen.id, status="found", review=True)
    longest = add_song(conn, "Florence + The Machine and the Long Named Friends", "Dog Days Are Over")
    update_song(conn, longest.id, review=True)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), ROWS))

    phone = layout_of(dump_dom(path, tmp_path, "#sort=title", size="390,844"))
    assert phone["page"] == 390, phone
    queen_line, abba_line, florence_line = range(3)  # by title: Bohemian, Dancing, Dog Days
    # "ABBA" and "Queen" whole, never squeezed out by the badges; a long name cut, but readable.
    for short in (abba_line, queen_line):
        assert phone["artists"][short] >= phone["whole"][short] > 30, phone
    assert phone["artists"][florence_line] > 40, phone
    assert max(phone["lines"]) <= 2 and phone["scroll"] <= phone["page"], phone
    # The auto sheet's line says where it came from by its mark and its button, as a badge would.
    dancing = line_of(listing(dump_dom(path, tmp_path, "#sort=title")), "Dancing Queen")
    assert 'aria-label="from the audio (auto-chords)"' in dancing and 'title="Auto sheet PDF"' in dancing
    assert ">Needs review<" in dancing and ">Auto sheet<" not in dancing


# Opens a line's other links and closes them, then clicks its artist's name over it; notes each step.
LINE_CLICKS_MENU = """
(() => {
  const notes = {};
  const line = Array.from(document.querySelectorAll("#list .line"))
    .find((l) => l.querySelector("h3").textContent === "Creep");
  const more = line.querySelector(".line-more");
  more.click();
  const panel = document.getElementById(more.getAttribute("aria-controls"));
  notes.opened = { expanded: more.getAttribute("aria-expanded"), hidden: panel.hidden,
                   links: Array.from(panel.querySelectorAll("a")).map((a) => a.firstChild.textContent) };
  more.click();
  notes.closed = { expanded: more.getAttribute("aria-expanded"), hidden: panel.hidden };
  line.closest("section.artist").querySelector("h2 button.artist").click();
  notes.artist = { hash: location.hash, titles: Array.from(document.querySelectorAll("#list .line h3"))
    .map((h) => h.textContent) };
  document.body.setAttribute("data-notes", JSON.stringify(notes));
})();
"""


@in_chromium
def test_a_lines_menu_opens_and_closes_and_its_artists_name_shows_their_songs(conn, cfg, tmp_path):
    import html as html_module

    creep = add_song(conn, "Radiohead", "Creep")
    put(cfg, creep, "sheet.pdf", "lyrics.txt", "tab.txt")
    add_song(conn, "Radiohead", "Lucky")
    add_song(conn, "The Beatles", "Yesterday")
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), LINE_CLICKS_MENU))
    dom = dump_dom(path, tmp_path)
    notes = json.loads(html_module.unescape(re.search(r'data-notes="([^"]*)"', dom).group(1)))
    assert notes["opened"] == {"expanded": "true", "hidden": False, "links": ["Lyrics", "Tab"]}, notes
    assert notes["closed"] == {"expanded": "false", "hidden": True}, notes
    assert notes["artist"]["hash"] == "#artist=radiohead", notes
    assert sorted(notes["artist"]["titles"]) == ["Creep", "Lucky"], notes


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


# What another list does with the line renderer, resultRow's dense form.
DENSE_LINES = """
(() => {
  const list = document.createElement("div");
  list.className = "lines";
  list.id = "results";
  list.appendChild(window.caracole.resultRow({
    dense: true, title: "Creep", artist: "Radiohead", sources: ["ug", "lrclib", "ug"], key: "G", status: "found",
    badges: [{ kind: "found", text: "Found" }], facts: "chords ×6",
    action: { label: "Chords", href: "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169" },
    more: [{ heading: "Tabs", links: [{ label: "Tab", href: "javascript:alert(1)", source: "ug" }] }],
  }));
  list.appendChild(window.caracole.resultRow({ dense: true, title: "Nameless" }));
  document.body.appendChild(list);
})();
"""


@in_chromium
def test_the_line_renderer_takes_any_result_in_a_real_browser(conn, cfg, tmp_path):
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), DENSE_LINES))
    results = re.search(r'<div class="lines" id="results">(.*?)</div>\s*</body>', dump_dom(path, tmp_path), re.S)
    creep = line_of(results.group(1), "Creep")
    assert re.search(r'<article class="line" tabindex="-1" data-status="found"><div class="line-title"><h3', creep)
    assert '<span class="line-by">Radiohead</span>' in creep  # no filter given: its name alone
    assert re.search(r'<span class="line-status"><span class="badge found">Found</span>'
                     r'<span class="line-facts" title="chords ×6">chords ×6</span></span>', creep), creep  # all of it
    assert re.search(r'<span class="line-key" title="Key G major"><span aria-hidden="true">G</span>', creep)
    marks = re.search(r'<span class="line-sources">(.*?)</span></div>', creep, re.S).group(1)
    assert re.findall(r'data-source="([^"]+)"', marks) == ["ug", "lrclib"]  # each once, in order
    main = re.search(r'<div class="line-action"><a ([^>]*)>Chords ↗</a>', creep)
    assert main and 'target="_blank"' in main.group(1) and 'rel="noopener noreferrer"' in main.group(1)
    assert "javascript:" not in creep and re.search(r'<div class="line-panel" id="line-more-\d+" hidden', creep)
    nameless = line_of(results.group(1), "Nameless")
    assert "line-more" not in nameless and "line-by" not in nameless  # nothing more to show, no button


# --- lines on the served page: every state a card showed -----------------------------------------


def served_states(conn, cfg):
    """A song in each state a served card showed: in review with candidates to pick (Crep), being removed
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


@in_chromium
def test_the_file_lines_show_a_reviews_candidates_and_a_song_not_founds_line(conn, cfg, tmp_path):
    index_tabs(conn, (1, "radiohead", "creep", "chords"))
    in_review(conn)
    lost = add_song(conn, "The Beatles", "Yesterday")
    update_song(conn, lost.id, match_decision="not_found")
    shown = listing(dump_dom(write_library_page(cfg.library_dir, page(conn, cfg)), tmp_path))
    crep = panel_of(line_of(shown, "Crep"))
    assert re.search(r'<details class="picker"', crep) and "<form" not in crep
    assert "<code>caracole review --song 'Radio Head - Crep'</code>" in crep
    hint = re.search(r'<p class="pick-hint">(.*?)</p>', panel_of(line_of(shown, "Yesterday")), re.S)
    assert hint and "<code>caracole review --song 'The Beatles - Yesterday'</code>" in hint.group(1)


# Measures each line (its height, whether a part of it leaves it or covers another), then opens Crep's picker from
# its line's button and notes where the focus went and how wide the page got.
LINE_STATES = """
(() => {
  const box = (n) => n.getBoundingClientRect();
  const lines = Array.from(document.querySelectorAll("#list .line"));
  const measured = {};
  for (const l of lines) {
    const lb = box(l);
    const parts = Array.from(l.querySelectorAll(".line-title, .line-status > *, .line-key, .line-sources > *, " +
      ".line-action > *, .line-more, .line > .progress")).filter((p) => p.checkVisibility() && box(p).height > 0);
    const out = parts.filter((p) => box(p).right > lb.right + 0.5 || box(p).left < lb.left - 0.5)
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
    measured[l.querySelector("h3").textContent] = { height: Math.round(lb.height), out, over };
  }
  const crep = lines.find((l) => l.querySelector("h3").textContent === "Crep");
  crep.querySelector(".line-action button").click();
  setTimeout(() => {
    const picker = crep.querySelector("details.picker");
    const at = document.activeElement;
    document.body.setAttribute("data-states", JSON.stringify({
      lines: measured, open: picker.open, panel: !picker.closest(".line-panel").hidden,
      expanded: crep.querySelector(".line-more").getAttribute("aria-expanded"),
      focus: at && at.name === "pick" ? at.value : null,
      scroll: document.documentElement.scrollWidth, page: window.innerWidth,
    }));
  }, 50);
})();
"""


@pytest.mark.parametrize("size", ["390,844", "1280,900"])
@in_chromium
def test_a_lines_states_fit_its_line_and_its_pick_opens_the_picker_where_it_is(conn, cfg, tmp_path, size):
    import html as html_module

    controls, _ = served_states(conn, cfg)
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=controls)
    path = write_library_page(cfg.library_dir, with_script(html, LINE_STATES))
    dom = dump_dom(path, tmp_path, size=size)
    found = re.search(r'data-states="([^"]*)"', dom)
    assert found, dom[-2000:]
    states = json.loads(html_module.unescape(found.group(1)))
    assert states["page"] == int(size.split(",")[0]) and states["scroll"] <= states["page"], states
    for title, line in states["lines"].items():
        assert line["out"] == [] and line["over"] == [], (title, line)
    # A line with a request's line is one line taller than the rest, no more.
    plain = max(line["height"] for title, line in states["lines"].items() if title != "Bohemian Rhapsody")
    assert plain < states["lines"]["Bohemian Rhapsody"]["height"] <= plain + 30, states
    assert states["open"] and states["panel"] and states["expanded"] == "true", states
    assert states["focus"] == "radiohead/creep", states


# --- the bar: type to filter, Enter for the sites ----------------------------------------------------


@pytest.fixture
def driven(tmp_path):
    """A page driven as you would, typing and pressing keys (helpers/browser.py's Browser)."""
    from helpers.browser import Browser, BrowserError

    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


SHOWN_TITLES = "[...document.querySelectorAll('#list article h3')].map((h) => h.textContent)"
COMPOSING_ENTER = ("document.getElementById('q').dispatchEvent(new KeyboardEvent('keydown', "
                   "{ key: 'Enter', keyCode: 229, isComposing: true, bubbles: true, cancelable: true }))")


@in_chromium
def test_the_file_page_filters_your_songs_and_enter_shows_the_command(conn, cfg, driven):
    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Pink Floyd", "Wish You Were Here")
    add_song(conn, "Oasis", "Wonderwall")
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    driven.open(path.as_uri())
    driven.js("document.getElementById('q').focus()")
    driven.type("wywh")  # a title's initials find it, as you type: the same lines, filtered
    assert driven.wait(f"{SHOWN_TITLES}.join() === 'Wish You Were Here'")
    assert driven.js("document.querySelector('#list section.artist .artist-name').textContent") == "Pink Floyd"
    assert driven.js("document.getElementById('results').hidden") is True  # typing alone asks for nothing more
    assert "Enter" in driven.js("document.getElementById('bar-status').textContent")
    driven.js(COMPOSING_ENTER)  # the Enter that ends a pinyin word: still typing
    assert driven.js("document.getElementById('results').hidden") is True
    driven.press("Enter")
    assert driven.wait("!document.getElementById('results').hidden")
    assert driven.js("document.querySelector('#results .file-answer code').textContent") == "caracole search 'wywh'"
    assert "caracole serve" in driven.js("document.querySelector('#results .file-answer').textContent")
    assert driven.js(f"{SHOWN_TITLES}.join()") == "Wish You Were Here"  # the songs stay where they are
    assert driven.js("location.hash").endswith("all=1")
    driven.press("Escape")
    assert driven.wait("document.getElementById('results').hidden")
    assert driven.js("document.getElementById('q').value") == "wywh"  # Escape leaves the answer, not the search
    # Nothing was asked of anyone: no fetch, no image, no script but the page's own.
    assert driven.js("performance.getEntriesByType('resource').length") == 0


@in_chromium
def test_with_none_of_your_songs_matching_the_file_page_says_what_to_run_at_once(conn, cfg, tmp_path):
    add_song(conn, "Radiohead", "Creep")
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    dom = dump_dom(path, tmp_path, "#q=" + quote("karma police"))
    shown = listing(dom)
    assert "No songs match “karma police”." in shown
    assert "<code>caracole search 'karma police'</code>" in shown and "Copy</button>" in shown


@in_chromium
def test_a_key_filters_your_songs_alone_as_the_sites_know_no_keys(conn, cfg, driven):
    from caracole.library_page import WebControls

    keep_sheet_json(conn, cfg, add_song(conn, "Soda Stereo", "De Música Ligera"), AM_F_C_G)
    add_song(conn, "Radiohead", "Creep")
    served = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", active=0))
    status = "document.getElementById('bar-status').textContent"
    for html in (page(conn, cfg), served):
        path = write_library_page(cfg.library_dir, html)
        driven.send("Page.navigate", url="about:blank")
        driven.open(path.as_uri() + "#q=" + quote("a minor") + "&all=1")  # an address asking the sites for a key
        assert driven.wait(f"{SHOWN_TITLES}.join() === 'De Música Ligera'")
        assert driven.js(status) == "A key filters your songs alone: the sites know no keys"
        assert driven.js("document.getElementById('results').hidden") is True
        driven.js("document.getElementById('q').focus()")
        driven.press("Enter")
        assert driven.js("document.getElementById('results').hidden") is True  # still your songs alone
        driven.js("document.getElementById('q').select()")
        driven.type("f# minor")  # no song in that key: nothing below to run or press
        assert driven.wait(f"{status} === 'None of yours match: the sites know no keys'")
        assert driven.js(f"{SHOWN_TITLES}.length") == 0
        driven.press("Enter")
        assert driven.js("document.querySelectorAll('.file-answer, #list .btn.primary').length") == 0
        assert driven.js("document.getElementById('results').hidden") is True
        assert driven.js("location.hash.includes('all=1')") is False
        driven.js("document.getElementById('q').select()")
        driven.type("creep")  # no key: the sites again
        assert driven.wait(f"!{status}.includes('know no keys')")


# --- the header on a phone, and the bar that stays at the top ----------------------------------------


@pytest.fixture
def phone_page(tmp_path):
    from helpers.browser import Browser, BrowserError

    try:
        page = Browser(tmp_path / "chrome-phone", width=390, height=844, mobile=True)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    yield page
    page.close()


FIRST_SONG = "document.querySelector('#list article').getBoundingClientRect().top"
SHOWN = "((e) => !!e && e.getClientRects().length > 0)"


@in_chromium
def test_on_a_phone_the_first_song_starts_on_the_first_screen(conn, cfg, phone_page):
    from caracole.library_page import WebControls

    for n, (artist, title) in enumerate((("Radiohead", "Creep"), ("Oasis", "Wonderwall"), ("Muse", "Hysteria"))):
        song = add_song(conn, artist, title)
        if n:
            update_song(conn, song.id, status="found")
        keep_sheet_json(conn, cfg, song, "Words\n", raw={"tonality_name": "Am"}, tab_id=n + 1)  # the Key menu shows
    served = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", active=1))
    for html in (served, page(conn, cfg)):
        path = write_library_page(cfg.library_dir, html)
        phone_page.open(path.as_uri())
        top = phone_page.js(FIRST_SONG)
        assert top < 400, top  # under the header, the bar and the buttons: more than half the screen is songs
        assert phone_page.js("document.documentElement.scrollWidth <= innerWidth")
        # The numbers sit beside the title, and the buttons are one row that scrolls sideways.
        title = phone_page.js("document.querySelector('h1').getBoundingClientRect().top")
        stats = phone_page.js("document.getElementById('summary').getBoundingClientRect().top")
        assert abs(title - stats) < 16, (title, stats)
        # No song needs review: no Needs review button. All, Found, Wanted, then Select, Key and Sort: one row that
        # scrolls sideways, a thumb's worth each.
        assert not phone_page.js(f"{SHOWN}(document.querySelector('.chip[data-show=\"review\"]'))")
        row = phone_page.js("[...document.querySelectorAll('.toolbar .chip, .toolbar select')].filter((c) => c.offsetParent)"
                            ".map((c) => [Math.round(c.getBoundingClientRect().top), c.getBoundingClientRect().height])")
        assert len(row) == 6 and max(t for t, _ in row) - min(t for t, _ in row) < 8, row
        assert min(h for _, h in row) >= 44, row
        assert phone_page.js("document.querySelector('.toolbar').scrollWidth > innerWidth")


@in_chromium
def test_on_a_phone_the_row_of_buttons_fades_where_it_goes_on_out_of_sight(conn, cfg, phone_page):
    from caracole.library_page import WebControls

    for n, (artist, title) in enumerate((("Radiohead", "Creep"), ("Oasis", "Wonderwall"), ("Muse", "Hysteria"))):
        song = add_song(conn, artist, title)
        update_song(conn, song.id, status="found" if n else "wanted", review=bool(n == 2))
    served = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", active=1))
    phone_page.open(write_library_page(cfg.library_dir, served).as_uri())
    row = "document.querySelector('.toolbar')"
    mask = f"(getComputedStyle({row}).maskImage || getComputedStyle({row}).webkitMaskImage || 'none')"
    assert phone_page.js(f"{row}.scrollWidth > {row}.clientWidth")  # Needs review is out of sight
    assert phone_page.wait(f"{row}.classList.contains('more-end')")
    assert "gradient" in phone_page.js(mask) and not phone_page.js(f"{row}.classList.contains('more-start')")
    phone_page.js(f"{row}.scrollLeft = {row}.scrollWidth")  # at its end: the fade moves to where it came from
    assert phone_page.wait(f"!{row}.classList.contains('more-end') && {row}.classList.contains('more-start')")
    assert "gradient" in phone_page.js(mask)


@in_chromium
def test_on_a_desktop_the_menus_sit_beside_the_buttons_and_needs_review_shows_once_a_song_does(conn, cfg, tmp_path):
    from helpers.targets import noted, noting

    add_song(conn, "Radiohead", "Creep")
    in_review(conn)
    tops = noting("data-tops", "[...document.querySelectorAll('.toolbar .chip:not([hidden]), #sort')]"
                               ".map((e) => Math.round(e.getBoundingClientRect().top))")
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(page(conn, cfg), tops)), tmp_path, size="1280,900")
    assert not re.search(r'data-show="review"[^>]*hidden', dom)
    toolbar = re.search(r'<div class="toolbar">(.*?)<nav class="jump"', dom, re.S).group(1)
    assert 'id="sort"' in toolbar and 'id="key"' in toolbar and 'id="view' not in toolbar
    assert max(noted(dom, "data-tops")) - min(noted(dom, "data-tops")) < 8  # one line: it all fits


# The bar as it is: kept at the top or not (an IntersectionObserver's answer), its edge, its sides.
STUCK = """(() => {
  const bar = document.querySelector(".searchbar");
  const box = bar.getBoundingClientRect();
  return { stuck: bar.classList.contains("stuck"), shadow: getComputedStyle(bar).boxShadow,
           left: box.left, right: box.right, top: box.top, page: innerWidth };
})()"""


@in_chromium
def test_the_bar_kept_at_the_top_has_an_edge_and_covers_the_page_side_to_side(conn, cfg, tmp_path):
    # On real time, scrolled to the end: the bar sticks once the page's IntersectionObserver answers, in a frame
    # drawn after the scroll, which a page on dump_dom's virtual clock may never get on a busy machine.
    from helpers.browser import Browser

    for n in range(30):
        add_song(conn, "Radiohead", f"Song {n}")
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    bars = {}
    for width, height in ((1280, 900), (390, 844)):
        with Browser(tmp_path / f"chrome-{width}", width=width, height=height) as b:
            b.send("Emulation.setScrollbarsHidden", hidden=True)  # as dump_dom lays a page out
            b.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1,
                   mobile=width < NARROWEST_WINDOW)
            b.open(path.as_uri())
            b.js("window.scrollTo(0, document.documentElement.scrollHeight)")
            assert b.wait("document.querySelector('.searchbar').classList.contains('stuck')"), b.js(STUCK)
            bars[f"{width},{height}"] = b.js(STUCK)
    at_top = bars["1280,900"]
    assert at_top["stuck"] and at_top["shadow"] != "none" and at_top["top"] == 0
    for size, bar in bars.items():
        assert bar["left"] <= 0 and bar["right"] >= bar["page"], (size, bar)  # nothing shows beside it


@in_chromium
def test_the_page_waits_unseen_for_its_scripts_and_shows_without_them_all_the_same(conn, cfg, tmp_path):
    # Until its scripts have drawn it, the page is unseen (nothing on it then can move once they have); should
    # they never get there, it shows two seconds on; with no script at all, at once.
    add_song(conn, "Radiohead", "Creep")
    html = build_library_page(conn, cfg, Overrides(), NOW)
    assert html.count('<body class="drawing">') == 1
    pages = {}
    for name, text in (("index.html", html),
                       ("stuck.html", html.replace("<script>", '<script type="text/plain">'))):  # no script runs
        pages[name] = tmp_path / name
        pages[name].write_text(text, encoding="utf-8")
    shown = "getComputedStyle(document.querySelector('.page')).visibility === 'visible'"
    with browser.Browser(tmp_path / "chrome") as b:
        b.open(pages["index.html"].as_uri())
        assert b.js(shown) and not b.js("document.body.classList.contains('drawing')")
        b.open(pages["stuck.html"].as_uri())
        assert b.js(f"!({shown})")  # waiting for scripts that never come
        assert b.wait(shown, 6)
        assert b.js("performance.now()") >= 1900  # two seconds after the page began
    with browser.Browser(tmp_path / "chrome-noscript") as b:
        b.send("Emulation.setScriptExecutionDisabled", value=True)
        b.open(pages["index.html"].as_uri())
        assert b.js(shown) and b.js("performance.now()") < 1900  # no script at all: at once


# --- lines grouped by artist: the library's one view ----------------------------------------------------


# Each artist's group as it shows: its key, its heading, its songs' titles and ids, in order.
GROUPS = """(() => Array.from(document.querySelectorAll("#list section.artist")).map((s) => ({
  artist: s.dataset.artist, heading: s.querySelector("h2").textContent,
  titles: Array.from(s.querySelectorAll("article.line h3")).map((h) => h.textContent),
  ids: Array.from(s.querySelectorAll("article.line")).map((a) => Number(a.dataset.id)),
})))()"""


@in_chromium
def test_the_library_is_lines_grouped_by_artist_a_to_z(conn, cfg, tmp_path):
    from helpers.targets import noted, noting

    for artist, title in (("Soda Stereo", "Persiana Americana"), ("宋冬野", "斑马，斑马"), ("The Beatles", "Yesterday"),
                          ("Soda Stereo", "De Música Ligera"), ("Radiohead", "Creep"), ("2Pac", "Changes")):
        add_song(conn, artist, title)
    html = page(conn, cfg)
    songs = songs_of(html)
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(html, noting("data-groups", GROUPS))), tmp_path)
    groups = noted(dom, "data-groups")
    # Artists A to Z by their sort keys: "The Beatles" under B, 宋冬野 by pinyin after Soda Stereo; each header
    # names the artist and how many of the songs listed are yours.
    assert [g["heading"] for g in groups] == ["2Pac · you have 1", "The Beatles · you have 1",
                                              "Radiohead · you have 1", "Soda Stereo · you have 2",
                                              "宋冬野 · you have 1"], groups
    soda = groups[3]
    assert soda["artist"] == songs["Soda Stereo - De Música Ligera"]["sortArtist"]
    assert soda["titles"] == ["De Música Ligera", "Persiana Americana"]  # its songs A to Z
    assert soda["ids"] == [songs["Soda Stereo - De Música Ligera"]["id"], songs["Soda Stereo - Persiana Americana"]["id"]]
    shown = listing(dom)
    assert shown.count('<article class="line') == 6 and "<article class=\"card" not in shown
    assert '<article class="row' not in shown
    # The outline under the page's h1: an h2 per artist, an h3 per song.
    assert len(re.findall(r"<h2\b", shown)) == 5 and len(re.findall(r"<h3\b", shown)) == 6


# Each line's height, width and how many rows of text it takes (by its parts' middles), and the page's.
LINES = """(() => {
  const box = (n) => n.getBoundingClientRect();
  const lines = Array.from(document.querySelectorAll("#list article.line"));
  const parts = ".line-title h3, .line-by, .line-status > *, .line-key, .line-sources > *, .line-action > *, .line-more";
  const rows = (line) => {
    const middles = Array.from(line.querySelectorAll(parts)).filter((p) => p.checkVisibility() && box(p).height > 0)
      .map((p) => box(p).top + box(p).height / 2).sort((a, b) => a - b);
    return middles.filter((m, i) => i === 0 || m - middles[i - 1] > 6).length;
  };
  const by = (line) => line.querySelector(".line-by .artist-name") || line.querySelector(".line-by");
  return { heights: lines.map((l) => Math.round(box(l).height)), rows: lines.map(rows),
           widths: lines.map((l) => Math.round(box(l).width)),
           artists: lines.map((l) => (by(l) && by(l).checkVisibility() ? Math.round(box(by(l)).width) : null)),
           whole: lines.map((l) => (by(l) ? by(l).scrollWidth : null)),
           page: innerWidth, screen: innerHeight, scroll: document.documentElement.scrollWidth };
})()"""


# The list's top scrolled to just under the bar kept at the top, as a laptop reads down a library: the lines and the
# artists' names whole in sight under the bar, then.
IN_VIEW = """(() => {
  const bar = document.querySelector(".searchbar");
  const groups = document.querySelector("#list .groups");
  window.scrollTo(0, groups.getBoundingClientRect().top + scrollY - bar.getBoundingClientRect().height);
  const under = bar.getBoundingClientRect().bottom;
  const whole = (selector) => Array.from(document.querySelectorAll(selector)).filter((n) => {
    const r = n.getBoundingClientRect();
    return r.height > 0 && r.top >= under - 0.5 && r.bottom <= innerHeight + 0.5;
  }).length;
  return { lines: whole("#list article.line"), heads: whole("#list section.artist > h2"), under: Math.round(under),
           top: Math.round(groups.getBoundingClientRect().top), screen: innerHeight };
})()"""


def busy_library(conn, cfg):
    """Four artists of eight songs each, long names among them, each song with a sheet, its lyrics and a key; some
    in review, some wanted."""
    for a in range(4):
        artist = ("Los Fabulosos Cadillacs y Los Auténticos Decadentes", "Radiohead", "Soda Stereo", "Wilco")[a]
        for n in range(8):
            title = f"A Song Title That Goes On For A While {n:02d}" if n % 3 == 0 else f"Song {n:02d}"
            s = add_song(conn, artist, title)
            keep_sheet_json(conn, cfg, s, "Words\n", raw={"tonality_name": "F#m"}, tab_id=100 + 10 * a + n)
            put(cfg, s, "sheet.pdf", "lyrics.txt")
            update_song(conn, s.id, status="found" if n % 4 else "wanted", review=n % 5 == 0)


@in_chromium
def test_a_laptop_screen_shows_twenty_odd_lines_under_the_bar_and_a_phone_two_lines_a_song(conn, cfg, tmp_path):
    from helpers.targets import noted, noting

    busy_library(conn, cfg)
    script = noting("data-lines", LINES) + noting("data-view", IN_VIEW)
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), script))

    dom = dump_dom(path, tmp_path, size="1280,800")
    wide = noted(dom, "data-lines")
    assert wide["page"] == 1280 and len(wide["heights"]) == 32 and wide["scroll"] <= wide["page"], wide
    assert set(wide["rows"]) == {1}, wide  # a song a line
    # 24 px a line, no less: its buttons keep the 24 px a pointer's target needs (WCAG 2.5.8), a pixel's slack.
    assert max(wide["heights"]) <= 25, wide
    # Read down under the bar, a laptop's screen (713 px of it the page's) holds twenty-odd lines and the names of
    # their artists: 21 and 3 today, two lines to spare.
    view = noted(dom, "data-view")
    assert abs(view["top"] - view["under"]) <= 1 and view["screen"] == wide["screen"], view
    assert view["lines"] >= 19 and view["lines"] + view["heads"] >= 22, view

    for touch in (False, True):
        phone = noted(dump_dom(path, tmp_path, size="390,844", touch=touch), "data-lines")
        assert (phone["page"], phone["screen"]) == (390, 844) and phone["scroll"] <= phone["page"], phone
        assert max(phone["rows"]) <= 2, (touch, phone)  # two lines a song at most
        assert all(w >= phone["page"] - 40 for w in phone["widths"]), phone
        assert phone["screen"] // max(phone["heights"]) >= (8 if touch else 10), (touch, phone)
    # Sorted by title, the lines have no artist over them: each says its own, whole or 40 px of it at the least,
    # still on two lines.
    flat = noted(dump_dom(path, tmp_path, "#sort=title", size="390,844"), "data-lines")
    assert max(flat["rows"]) <= 2 and flat["scroll"] <= flat["page"], flat
    assert all(shown >= min(whole, 40) for shown, whole in zip(flat["artists"], flat["whole"])), flat
    tablet = noted(dump_dom(path, tmp_path, size="1280,800", touch=True), "data-lines")
    assert set(tablet["rows"]) == {1}, tablet  # one line each, as with a mouse


# Clicks through what a line offers on the served page, and notes each step: Pick the match opens the picker under
# its "⋯", the focus on the first candidate; Remove… counts down on the line, the focus on Undo, which keeps the
# song; Select puts a box on each line; Add to a songbook… picks the song in it.
LINE_CLICKS = """
(() => {
  const notes = {};
  const lineOf = (title) => Array.from(document.querySelectorAll("#list article.line"))
    .find((l) => l.querySelector("h3").textContent === title);
  const say = () => document.body.setAttribute("data-clicks", JSON.stringify(notes));
  const crep = lineOf("Crep");
  crep.querySelector(".line-action .line-pick").click();
  setTimeout(() => {
    const at = document.activeElement;
    notes.pick = { panel: !crep.querySelector(".line-panel").hidden, open: crep.querySelector("details.picker").open,
                   expanded: crep.querySelector(".line-more").getAttribute("aria-expanded"),
                   focus: at && at.name === "pick" ? at.value : null };
    const soda = lineOf("De Música Ligera");
    soda.querySelector(".line-more").click();
    soda.querySelector("form.remove button").click();
    const line = soda.querySelector(".progress");
    notes.countdown = { text: line.textContent, focus: document.activeElement.textContent,
                        waits: soda.querySelector("form.remove button").disabled };
    document.activeElement.click();  // Undo
    notes.undone = { text: soda.querySelector(".progress").textContent, focus: document.activeElement.textContent,
                     sends: !soda.querySelector("form.remove button").disabled };
    document.querySelector(".pick-toggle").click();
    const boxes = Array.from(document.querySelectorAll("#list article.line .pick")).filter((p) => p.checkVisibility());
    const r = boxes[0].getBoundingClientRect();
    notes.select = { boxes: boxes.length, lines: document.querySelectorAll("#list article.line").length,
                     size: [Math.round(r.width), Math.round(r.height)] };
    document.querySelector(".pick-toggle").click();
    const queued = lineOf("Bohemian Rhapsody");
    queued.querySelector(".line-more").click();
    Array.from(queued.querySelectorAll(".line-panel button")).find((b) => b.textContent === "Add to a songbook…").click();
    notes.book = { selecting: document.body.classList.contains("selecting"),
                   count: document.querySelector(".pick-count").textContent, picked: queued.classList.contains("picked") };
    say();
  }, 50);
})();
"""


@in_chromium
def test_every_action_a_card_had_is_on_the_line_or_its_menu(conn, cfg, tmp_path):
    from helpers.targets import noted

    from caracole.musescore import parse_song_url

    controls, s = served_states(conn, cfg)
    conn.execute("INSERT INTO musescore_index VALUES (?, ?, ?, '18')",
                 parse_song_url("https://musescore.com/song/yesterday-680101"))
    gp = version(conn, s["soda"], 555890, slot="guitar", kind="guitar-pro")
    set_picks(conn, s["soda"].id, ["guitar-pro"], [gp])
    put(cfg, s["soda"], "lyrics.txt")
    overrides = Overrides(transpose={s["soda"].key: -2})
    html = build_library_page(conn, cfg, overrides, NOW, controls=controls)
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(html, LINE_CLICKS)), tmp_path)
    shown = listing(dom)
    assert shown.count('<article class="line') == 5 and '<article class="card' not in shown
    assert '<article class="row' not in shown

    # In review, with candidates: Pick the match is its button, the picker under its "⋯".
    crep = line_of(shown, "Crep")
    assert re.search(r'<div class="line-action"><button class="btn small line-pick"[^>]*>Pick the match</button>', crep)
    assert ">Needs review<" in crep and "Review first" not in crep and "/fetch" not in crep
    assert re.search(r'<form[^>]*action="/review"', crep.split('class="line-panel"', 1)[1])
    # Being removed: it says so where its button was, with no fetch and no other removal.
    going = line_of(shown, "Wonderwall")
    assert re.search(r'<div class="line-action"><a class="line-busy" href="/jobs"[^>]*>Removing…</a>', going)
    assert "/fetch" not in going and "/remove" not in going
    # Its request queued: its line says how it goes, a line of its own, Details and all.
    queued = line_of(shown, "Bohemian Rhapsody")
    line = re.search(r'<p class="progress"[^>]*>(.*?)</p>', queued, re.S)
    assert line and 'role="status"' in line.group(0) and "Queued behind 1 request…" in line.group(1)
    assert 'href="jobs?job=4#job-4"' in line.group(1) and "/fetch" not in queued
    # Not found: Fetch now still asks; the status says so; the menu looks in the index, and finds the chords elsewhere.
    lost = line_of(shown, "Yesterday")
    assert re.search(r'<div class="line-action"><form[^>]*action="/fetch"', lost) and ">Not found<" in lost
    menu = lost.split('class="line-panel"', 1)[1]
    assert re.search(rf'href="/review\?song={s["lost"].id}"[^>]*>Look in the index</a>', menu)
    assert "Scores on MuseScore" in menu and "Find the chords" in menu and "yesterday-680101 (possible match)" in menu
    # Found: Open, its key and its marks on the line; its files, its Guitar Pro to download, its key in words, its
    # transposition, Add to a songbook… and Remove… under "⋯".
    soda = line_of(shown, "De Música Ligera")
    assert re.search(r'<div class="line-action"><a class="btn small primary"[^>]*>Open PDF</a>', soda), soda
    assert re.search(r'<span class="line-key"[^>]*>', soda) and "Key A minor (from the tab)" in soda
    assert 'data-source="ug"' in soda.split('class="line-panel"', 1)[0]
    menu = soda.split('class="line-panel"', 1)[1]
    assert "Sheet text" in menu and "Lyrics" in menu and "Guitar Pro ver 1" in menu and "−2" in menu
    assert ">Add to a songbook…</button>" in menu and re.search(r'<form[^>]*action="/remove"', menu)

    clicks = noted(dom, "data-clicks")
    assert clicks["pick"] == {"panel": True, "open": True, "expanded": "true", "focus": "radiohead/creep"}, clicks
    assert clicks["countdown"]["text"].startswith("Removing in 5 s") and clicks["countdown"]["focus"] == "Undo", clicks
    assert clicks["countdown"]["waits"] is True
    assert clicks["undone"] == {"text": "Not removed", "focus": "Remove…", "sends": True}, clicks
    assert clicks["select"] == {"boxes": 5, "lines": 5, "size": [44, 44]}, clicks
    assert clicks["book"] == {"selecting": True, "count": "1 selected", "picked": True}, clicks


@in_chromium
def test_filters_key_sort_and_letters_work_on_the_lines(conn, cfg, tmp_path):
    for tab_id, (artist, title, key) in enumerate((("Queen", "Bohemian Rhapsody", "Bb"),
                                                    ("Queen", "Don't Stop Me Now", "F"),
                                                    ("ABBA", "Dancing Queen", "A"),
                                                    ("Radiohead", "Creep", "G")), start=1):
        s = add_song(conn, artist, title)
        keep_sheet_json(conn, cfg, s, "Words\n", raw={"tonality_name": key}, tab_id=tab_id)
        update_song(conn, s.id, status="found" if tab_id != 4 else "wanted")
    path = write_library_page(cfg.library_dir, page(conn, cfg))

    def shown(fragment):
        found = listing(dump_dom(path, tmp_path, fragment))
        assert '<article class="card' not in found and '<article class="row' not in found
        return found

    assert titles_in(shown("")) == ["Dancing Queen", "Bohemian Rhapsody", "Don't Stop Me Now", "Creep"]  # by artist
    assert titles_in(shown("#artist=queen")) == ["Bohemian Rhapsody", "Don't Stop Me Now"]
    assert titles_in(shown("#key=G")) == ["Creep"]
    assert titles_in(shown("#show=wanted")) == ["Creep"]
    assert titles_in(shown("#q=dancing")) == ["Dancing Queen"]
    assert "Queen · you have 2" in re.sub(r"<[^>]+>", "", shown("#artist=queen"))
    # Sorted by title or by when they came, the lines stand alone, each with its artist (a filter, as a header's is).
    by_title = shown("#sort=title")
    assert titles_in(by_title) == ["Bohemian Rhapsody", "Creep", "Dancing Queen", "Don't Stop Me Now"]
    assert 'class="artist"' not in by_title.replace('class="artist line-by"', "")  # no artist's group
    assert re.search(r'<button class="artist line-by"[^>]*><span class="artist-name">ABBA</span>',
                     line_of(by_title, "Dancing Queen"))
    assert titles_in(shown("#sort=recent")) == ["Creep", "Dancing Queen", "Don't Stop Me Now", "Bohemian Rhapsody"]
    # Whatever the search or a filter leaves out, an artist's header counts every song of theirs you have.
    for fragment, heads, titles in (("#q=bohemian", ["Queen · you have 2"], ["Bohemian Rhapsody"]),
                                    ("#key=F", ["Queen · you have 2"], ["Don't Stop Me Now"]),
                                    ("#q=queen", ["ABBA · you have 1", "Queen · you have 2"],
                                     ["Dancing Queen", "Bohemian Rhapsody", "Don't Stop Me Now"])):
        found = shown(fragment)
        assert ([re.sub(r"<[^>]+>", "", h) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", found, re.S)],
                titles_in(found)) == (heads, titles), fragment
    # The letters jump to an artist's group by artist, to a title's first line by title, once 40 songs show.
    for n in range(36):
        add_song(conn, "Radiohead", f"Song {n:02d}")
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    strip = lambda fragment: re.findall(r"<button[^>]*>([^<]+)</button>",  # noqa: E731
                                        re.search(r'<nav[^>]*id="jump"[^>]*>(.*?)</nav>',
                                                  dump_dom(path, tmp_path, fragment), re.S).group(1))
    assert strip("") == ["A", "Q", "R"] and strip("#sort=title") == ["B", "C", "D", "S"]


# Clicks the A-Z strip's "R", then notes where the focus went.
JUMP_TO_R = """(() => {
  const r = Array.from(document.querySelectorAll("#jump button")).find((b) => b.textContent === "R");
  if (!r || r.closest("[hidden]")) return null;
  r.click();
  const at = document.activeElement;
  return at.matches("section.artist") ? at.dataset.artist + ":" + at.querySelector("h2").textContent : at.tagName;
})()"""


@in_chromium
def test_there_is_no_cards_rows_switch(conn, cfg, tmp_path):
    from helpers.targets import noted, noting

    from caracole.library_page import _PAGE_SCRIPT

    for n in range(20):
        add_song(conn, "The Beatles", f"Song {n:02d}")
        add_song(conn, "Radiohead", f"Tune {n:02d}")
    html = page(conn, cfg)
    for gone in ('id="view-toggle"', 'id="view-panel"', "data-view=", ">Cards<", ">Rows<"):
        assert gone not in html, gone
    for name in ("makeCard", "cardFor", "songRow", "rowFor", "VIEWS"):
        assert not re.search(rf"\b{name}\b", _PAGE_SCRIPT), name
    script = (noting("data-jump", JUMP_TO_R) + 'document.querySelector(".chip[data-show=all]").click();\n'
              + noting("data-hash", "location.hash"))
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(html, script)), tmp_path, "#view=rows&q=song")
    # An address from before, Rows and all, opens the lines, and the address forgets the view once it changes.
    shown = listing(dom)
    assert shown.count('<article class="line') == 20 and '<article class="row' not in shown
    assert '<article class="card' not in shown
    assert noted(dom, "data-hash") == "#q=song"
    # The letters: R's group takes the focus, so the next Tab goes on from there.
    dom = dump_dom(write_library_page(cfg.library_dir, with_script(html, script)), tmp_path)
    assert noted(dom, "data-jump") == "radiohead:Radiohead · you have 20"


@pytest.mark.parametrize("size", ["390,844", "1280,800"])
@in_chromium
def test_lines_meet_touch_and_contrast(conn, cfg, tmp_path, size):
    from helpers.targets import UNFOLD, noted, noting, small_targets, weak_edges

    # Every line's "⋯" open, so what each holds is measured too. The search field is the bar's, which another
    # change redraws.
    script = UNFOLD + noting("data-short", small_targets()) + noting("data-weak", weak_edges("#q"))
    html = with_script(every_control(conn, cfg), script)
    dom = dump_dom(write_library_page(cfg.library_dir, html), tmp_path, size=size, touch=True)
    assert re.search(r'class="line-panel"[^>]*id="line-more-\d+"(?! hidden)', dom)
    short, weak = noted(dom, "data-short"), noted(dom, "data-weak")
    assert short == [] and weak == [], (short, weak)


# The contrast of what a line says against what is behind it, and of its group's heading: WCAG's ratio of each
# text's colour to the first solid background under it.
READS = """(() => {
  const rgb = (text) => (/^rgba?\\(([\\d.]+),\\s*([\\d.]+),\\s*([\\d.]+)(?:,\\s*([\\d.]+))?\\)$/.exec(text) || []).slice(1)
    .map(Number);
  const lum = (c) => {
    const f = (v) => (v / 255 <= 0.04045 ? v / 255 / 12.92 : ((v / 255 + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const behind = (n) => {
    for (let at = n; at; at = at.parentElement) {
      const c = rgb(getComputedStyle(at).backgroundColor);
      if (c.length && !(c[3] < 1)) return c;  // no alpha, or a whole one
    }
    return [255, 255, 255];
  };
  const ratio = (n) => {
    const [hi, lo] = [lum(rgb(getComputedStyle(n).color)), lum(behind(n))].sort((a, b) => b - a);
    return Math.round((hi + 0.05) / (lo + 0.05) * 100) / 100;
  };
  const first = (selector) => document.querySelector("#list " + selector);
  const read = {};
  for (const [name, selector] of [["title", ".line-title h3"], ["status", ".line-status .badge"],
      ["key", ".line-key"], ["mark", ".line-sources .source.letters"], ["artist", "section.artist h2 .artist-name"],
      ["counts", ".artist-counts"], ["open", ".line-action .btn"]]) {
    read[name] = first(selector) ? ratio(first(selector)) : null;
  }
  read.box = Math.round(lum(behind(first("article.line"))) * 1000) / 1000;
  return read;
})()"""


@in_chromium
def test_the_lines_read_in_dark_mode(conn, cfg, tmp_path):
    from helpers.targets import UNFOLD, noted, noting, weak_edges

    sourced_library(conn, cfg)  # marks of every kind: an icon, LaCuerda's letters, the audio's glyph
    script = noting("data-reads", READS) + UNFOLD + noting("data-weak", weak_edges("#q"))
    path = write_library_page(cfg.library_dir, with_script(page(conn, cfg), script))
    for scheme in ("light", "dark"):
        dom = dump_dom(path, tmp_path, size="390,844", media={"prefers-color-scheme": scheme})
        reads = noted(dom, "data-reads")
        assert all(value is not None and value >= 4.5 for name, value in reads.items() if name != "box"), (scheme, reads)
        assert (reads["box"] < 0.05) if scheme == "dark" else (reads["box"] > 0.8), (scheme, reads)  # no white box at night
        assert noted(dom, "data-weak") == [], scheme
