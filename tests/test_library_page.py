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
    assert songs["Soda Stereo - De Música Ligera"]["key"] == "Bm"
    assert songs["Soda Stereo - De Música Ligera"]["transpose"] == -2
    assert songs["Radiohead - Creep"]["key"] is None and songs["Radiohead - Creep"]["transpose"] == 0
    assert plain.key not in o.transpose


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


def dump_dom(path: Path, tmp_path: Path, fragment: str = "", size: str = "1280,900") -> str:
    """The page's DOM after its script ran; skips the test when this machine can't run Chromium."""
    url = path.as_uri() + fragment
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
    assert len(wide["tops"]) == 4
    assert wide["tops"].count(wide["tops"][0]) >= 3, wide  # at least three cards share the first row
    assert wide["scroll"] <= wide["page"]

    phone = layout_of(dump_dom(path, tmp_path, size="390,844"))
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
