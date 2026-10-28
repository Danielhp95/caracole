"""icons.py: each source's icon, its site's favicon fetched once, kept small and sanitized."""

from __future__ import annotations

import base64
import random
import struct
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from helpers.ntfy import CONFIG as NTFY_CONFIG
from helpers.ntfy import FakeNtfy
from helpers.icon_files import CLEAR, RED, bmp_image, chunk, ico, pixels, png

from caracole import icons
from caracole.config import ProviderPolicy
from caracole.http import PoliteClient, ProviderBlocked

BLUE = (20, 60, 200, 255)


# --- what an icon may be --------------------------------------------------------------------


def test_a_png_keeps_its_image_and_loses_its_text_chunks():
    data = png(32, extra=[(b"tEXt", b"Comment\x00made by a site"), (b"eXIf", b"MM\x00*")],
               before_idat=[(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00<x:xmpmeta/>")])
    clean = icons.sanitize(data)
    assert clean is not None
    assert b"tEXt" not in clean and b"iTXt" not in clean and b"eXIf" not in clean and b"xmpmeta" not in clean
    assert pixels(clean) == pixels(data)


def test_an_animated_png_keeps_its_first_frame_alone():
    data = png(16, before_idat=[(b"acTL", struct.pack(">II", 2, 0)), (b"fcTL", b"\x00" * 26)],
               extra=[(b"fdAT", b"\x00\x00\x00\x01" + zlib.compress(b"\x00" * 65 * 16))])
    clean = icons.sanitize(data)
    assert clean is not None and b"acTL" not in clean and b"fdAT" not in clean
    assert pixels(clean) == pixels(png(16))


@pytest.mark.parametrize("data", [
    b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
    b"\xef\xbb\xbf<?xml version='1.0'?><svg/>",
    b"GIF89a\x10\x00\x10\x00",
    b"\xff\xd8\xff\xe0\x00\x10JFIF",
    b"RIFF\x00\x00\x00\x00WEBPVP8 ",
    b"<!doctype html><title>Just a moment...</title>",
    b"",
])
def test_anything_but_a_png_or_an_ico_is_refused(data):
    assert icons.sanitize(data) is None


def test_a_broken_png_is_refused():
    good = png(16)
    assert icons.sanitize(good[:-12]) is None  # no IEND
    assert icons.sanitize(good[:40]) is None  # cut short
    idat = good.index(b"IDAT")
    flipped = bytearray(good)
    flipped[idat + 6] ^= 0xFF  # a byte of the image, so its CRC no longer matches
    assert icons.sanitize(bytes(flipped)) is None
    assert icons.sanitize(good[:-4] + b"\x00\x00\x00\x00") is None  # IEND's CRC
    short = png(16)[:8] + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0)) + chunk(
        b"IDAT", zlib.compress(b"\x00" * 10)) + chunk(b"IEND", b"")
    assert icons.sanitize(short) is None  # fewer pixels than its header says


def test_a_png_too_big_to_be_an_icon_is_refused():
    assert icons.sanitize(png(257)) is None
    assert icons.sanitize(png(16, height=300)) is None
    noisy = png(16, extra=[(b"zTXt", b"x" * (icons.MAX_DOWNLOAD + 1))])
    assert icons.sanitize(noisy) is None  # the download itself is too big
    # Within the download's limit, but bigger than an icon the page inlines.
    assert len(icons.sanitize(png(200))) < icons.MAX_ICON  # one colour compresses well...
    noise = random.Random(1).randbytes(200 * 4 * 200)
    rows = b"".join(b"\x00" + noise[y * 800:(y + 1) * 800] for y in range(200))
    random_png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 200, 200, 8, 6, 0, 0, 0))
                  + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    assert icons.sanitize(random_png) is None  # ...noise doesn't


def test_an_ico_gives_its_32_pixel_image_as_a_png():
    data = ico((16, bmp_image(16, BLUE)), (32, bmp_image(32, RED)), (48, bmp_image(48, BLUE)))
    clean = icons.sanitize(data)
    assert clean is not None and clean.startswith(b"\x89PNG")
    width, height, seen = pixels(clean)
    assert (width, height) == (32, 32) and set(seen) == {RED}


def test_an_ico_without_a_32_pixel_image_gives_the_nearest_bigger_one_else_its_biggest():
    assert pixels(icons.sanitize(ico((16, bmp_image(16)), (48, bmp_image(48)))))[:2] == (48, 48)
    assert pixels(icons.sanitize(ico((16, bmp_image(16)))))[:2] == (16, 16)


def test_an_ico_whose_best_image_is_broken_or_too_big_gives_the_next_one():
    noise = random.Random(2).randbytes(100 * 4 * 100)
    rows = b"".join(b"\x00" + noise[y * 400:(y + 1) * 400] for y in range(100))
    big = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 100, 100, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    assert icons.MAX_ICON < len(big) < icons.MAX_DOWNLOAD
    assert pixels(icons.sanitize(ico((32, png(32)[:-12]), (16, bmp_image(16)))))[:2] == (16, 16)
    assert pixels(icons.sanitize(ico((100, big), (48, bmp_image(48)))))[:2] == (48, 48)


def test_an_icos_and_mask_makes_its_pixels_transparent():
    hole = {(0, 0), (31, 31)}
    for image in (bmp_image(32, RED, bpp=24, transparent=hole), bmp_image(32, RED, bpp=8, transparent=hole),
                  bmp_image(32, RED, bpp=32, transparent=hole, alpha=False)):
        _, _, seen = pixels(icons.sanitize(ico((32, image))))
        assert seen[0] == CLEAR and seen[-1] == CLEAR and seen[1] == RED, seen[:2]


def test_a_32_bit_ico_keeps_its_own_alpha():
    _, _, seen = pixels(icons.sanitize(ico((32, bmp_image(32, (220, 30, 40, 128))))))
    assert set(seen) == {(220, 30, 40, 128)}


def test_an_ico_holding_a_png_gives_that_png_sanitized():
    inner = png(32, BLUE, extra=[(b"tEXt", b"Software\x00some editor")])
    clean = icons.sanitize(ico((32, inner)))
    assert clean is not None and b"tEXt" not in clean and pixels(clean) == pixels(png(32, BLUE))


def test_a_png_sent_as_favicon_ico_is_read_as_a_png():
    # Ultimate Guitar's /favicon.ico is a PNG; the bytes decide, never the name or the header.
    assert icons.sanitize(png(32)) is not None


def patched(data: bytes, at: int, new: bytes) -> bytes:
    return data[:at] + new + data[at + len(new):]


@pytest.mark.parametrize("data", [
    ico((32, bmp_image(32)), kind=2),  # a cursor
    ico((32, bmp_image(32)))[:30],  # cut short
    struct.pack("<HHH", 0, 1, 0),  # no image
    ico((32, bmp_image(32)))[:6] + struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, 99999, 22),  # past the end
    ico((32, bmp_image(32)[:100])),  # fewer pixels than its header says
    ico((32, patched(bmp_image(32), 14, struct.pack("<H", 16)))),  # 16 bits a pixel
    ico((32, patched(bmp_image(32), 16, struct.pack("<I", 1)))),  # RLE-compressed
    ico((32, patched(bmp_image(32), 8, struct.pack("<i", 32)))),  # the height not doubled
    ico((32, png(32)[:-12])),  # a broken PNG inside
])
def test_a_broken_or_odd_ico_is_refused(data):
    assert icons.sanitize(data) is None


def test_a_sanitized_icon_is_small():
    for data in (png(32), ico((16, bmp_image(16)), (32, bmp_image(32)), (48, bmp_image(48)))):
        assert len(icons.sanitize(data)) <= icons.MAX_ICON


# --- the sources ------------------------------------------------------------------------------


def test_every_source_has_a_name_a_tag_and_a_badge():
    for key in ("ug", "lacuerda", "lrclib", "gtptabs", "musescore", "youtube", "auto", "inbox"):
        source = icons.SOURCES[key]
        assert source.key == key and source.name and source.tag and source.letters
        assert source.label == f"from {source.name}"
    assert icons.SOURCES["ug"].name == "Ultimate Guitar" and icons.SOURCES["ug"].tag == "UG"
    assert icons.SOURCES["lacuerda"].tag == "LaCuerda"
    # The audio model and the inbox are no site: a glyph of caracole's own, never fetched.
    assert icons.SOURCES["auto"].site is None and icons.SOURCES["inbox"].site is None
    assert all(s.site.startswith("https://") for s in icons.SOURCES.values() if s.site)


def test_a_source_has_a_tag_known_or_not():
    assert icons.tag("songsterr") == "songsterr"
    assert icons.tag("ug") == "UG"


# --- the cache --------------------------------------------------------------------------------


def test_a_kept_icon_is_inlined_as_a_data_uri(tmp_path):
    clean = icons.sanitize(png(32))
    icons.keep_icon(tmp_path, "ug", clean)
    assert (tmp_path / "icons" / "ug.png").read_bytes() == clean
    uri = icons.icon_uri(tmp_path, "ug")
    assert uri == "data:image/png;base64," + base64.b64encode(clean).decode()
    assert icons.icon_uri(tmp_path, "lacuerda") is None


def test_the_page_gets_every_sources_name_and_badge_and_the_icons_there_are(tmp_path):
    icons.keep_icon(tmp_path, "lacuerda", icons.sanitize(png(16)))
    shown = icons.page_icons(tmp_path)
    assert set(shown) == set(icons.SOURCES)
    assert shown["lacuerda"]["src"].startswith("data:image/png;base64,")
    assert "src" not in shown["ug"] and shown["ug"] == {"name": "Ultimate Guitar", "letters": "UG"}
    assert shown["auto"]["glyph"] is True and "src" not in shown["auto"]


def test_an_icon_file_that_isnt_a_clean_png_is_never_inlined(tmp_path):
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "ug.png").write_bytes(b"<svg onload='alert(1)'/>")
    (tmp_path / "icons" / "lacuerda.png").write_bytes(png(16, extra=[(b"tEXt", b"a\x00b")]))
    assert icons.icon_uri(tmp_path, "ug") is None
    assert icons.icon_uri(tmp_path, "lacuerda") is None  # not as caracole writes it
    (tmp_path / "icons" / "ug.png").write_bytes(png(16) + b"\x00" * icons.MAX_ICON)
    assert icons.icon_uri(tmp_path, "ug") is None


def test_a_link_in_place_of_an_icon_is_never_read(tmp_path):
    outside = tmp_path / "elsewhere.png"
    outside.write_bytes(icons.sanitize(png(16)))
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "ug.png").symlink_to(outside)
    assert icons.icon_uri(tmp_path, "ug") is None


@pytest.mark.parametrize("key", ["../ug", "UG", "u/g", "", "ug.png"])
def test_a_source_key_is_never_a_path(tmp_path, key):
    with pytest.raises(ValueError):
        icons.keep_icon(tmp_path, key, icons.sanitize(png(16)))
    assert icons.icon_uri(tmp_path, key) is None


# --- fetching, politely ---------------------------------------------------------------------

NOW = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)


class Site:
    """A fake site behind a real PoliteClient: ``pages`` maps a path to (status, body)."""

    def __init__(self, provider: str, pages: dict[str, tuple[int, bytes]], *, budget: int = 10):
        self.provider = provider
        self.pages = pages
        self.asked: list[str] = []
        self.budget = budget

    def handler(self, request: httpx.Request) -> httpx.Response:
        target = request.url.raw_path.decode()
        self.asked.append(f"{request.url.host}{target}")
        status, body = self.pages.get(target, (404, b"not here"))
        return httpx.Response(status, content=body)

    def client(self, cache_dir: Path, now: datetime | None = None) -> PoliteClient:
        """A client whose clock (what its cache's answers are dated by) says ``now``, else the time."""
        return PoliteClient(self.provider, ProviderPolicy(budget=self.budget, delay=(0.0, 0.0)), cache_dir,
                            user_agent="caracole-test", transport=httpx.MockTransport(self.handler),
                            sleep=lambda s: None, wall_clock=lambda: now or datetime.now(UTC))


def fetch(conn, cache, *sites, now=NOW, **kw):
    return icons.fetch_icons(conn, cache, {s.provider: s.client(cache, now) for s in sites}, now, **kw)


def test_a_sites_favicon_is_asked_for_once_and_kept(conn, tmp_path):
    ug = Site("ug", {"/favicon.ico": (200, png(32))})
    run = fetch(conn, tmp_path, ug)
    assert run.fetched == ["ug"] and ug.asked == ["www.ultimate-guitar.com/favicon.ico"]
    assert icons.icon_uri(tmp_path, "ug") is not None
    again = fetch(conn, tmp_path, ug)
    assert again.fetched == [] and ug.asked == ["www.ultimate-guitar.com/favicon.ico"]  # nothing asked again


def test_each_site_is_asked_with_its_own_client_and_no_glyph_is_fetched(conn, tmp_path):
    ug = Site("ug", {"/favicon.ico": (200, png(32))})
    lacuerda = Site("lacuerda", {"/favicon.ico": (200, ico((32, bmp_image(32))))})
    run = fetch(conn, tmp_path, ug, lacuerda)
    assert sorted(run.fetched) == ["lacuerda", "ug"]
    assert lacuerda.asked == ["acordes.lacuerda.net/favicon.ico"]
    # The rest have no client this time: they wait, unmarked, for one that has.
    assert sorted(run.waiting) == ["gametabs", "gtptabs", "harptabs", "lrclib", "musescore", "youtube"]


HOME = b"""<!doctype html><html><head><title>MuseScore</title>
<link rel="icon" type="image/svg+xml" href="/static/icon.svg">
<link rel="icon" href="/api/jmuse?type=img">
<link rel="icon" sizes="16x16" href="/static/icon-16.png">
<link rel="shortcut icon" sizes="32x32" href="/static/icon-32.png">
<link rel="apple-touch-icon" href="https://cdn.elsewhere.net/apple.png">
<link rel="stylesheet" href="/static/site.css">
</head><body><link rel="icon" href="/late.png"></body></html>"""


def test_without_a_favicon_the_home_pages_icon_links_are_tried_on_the_same_site(conn, tmp_path):
    site = Site("musescore", {"/": (200, HOME), "/static/icon-32.png": (200, png(32)),
                              "/static/icon-16.png": (200, png(16))})
    run = fetch(conn, tmp_path, site)
    assert run.fetched == ["musescore"]
    # Its 32-pixel icon first; never the SVG, a URL robots.txt closes, another site, or the body's.
    assert site.asked == ["musescore.com/favicon.ico", "musescore.com/", "musescore.com/static/icon-32.png"]


def test_the_next_link_is_tried_when_one_gives_no_icon(conn, tmp_path):
    site = Site("musescore", {"/": (200, HOME), "/static/icon-32.png": (200, b"<html>gone</html>"),
                              "/static/icon-16.png": (200, png(16))})
    assert fetch(conn, tmp_path, site).fetched == ["musescore"]
    assert site.asked[-2:] == ["musescore.com/static/icon-32.png", "musescore.com/static/icon-16.png"]


def test_a_site_with_no_icon_gets_its_badge_and_is_asked_again_only_after_a_week(conn, tmp_path):
    site = Site("lrclib", {"/favicon.ico": (200, b"<svg onload='x()'/>"), "/": (200, b"<html>no links</html>")})
    run = fetch(conn, tmp_path, site)
    assert run.missing == ["lrclib"] and run.fetched == [] and icons.icon_uri(tmp_path, "lrclib") is None
    assert len(site.asked) == 2
    fetch(conn, tmp_path, site, now=NOW + timedelta(days=6))
    assert len(site.asked) == 2  # left alone
    later = fetch(conn, tmp_path, site, now=NOW + timedelta(days=8))
    assert later.missing == ["lrclib"] and len(site.asked) == 4  # asked again: its answers are a week old


def test_a_site_that_puts_an_icon_up_later_gets_it_at_the_next_weeks_try(conn, tmp_path):
    site = Site("lacuerda", {"/": (200, b"<html><head><title>no icon</title></head></html>")})
    assert fetch(conn, tmp_path, site).missing == ["lacuerda"]
    site.pages["/favicon.ico"] = (200, ico((32, bmp_image(32))))
    # Asked now, as caracole icons asks: what the site answered less than a week ago stands.
    assert fetch(conn, tmp_path, site, now=NOW + timedelta(days=2), wait=None).missing == ["lacuerda"]
    assert len(site.asked) == 2
    later = fetch(conn, tmp_path, site, now=NOW + timedelta(days=9))
    assert later.fetched == ["lacuerda"] and site.asked[2:] == ["acordes.lacuerda.net/favicon.ico"]
    assert icons.icon_uri(tmp_path, "lacuerda") is not None


def test_an_icon_kept_in_the_cache_is_read_again_from_it_however_old(conn, tmp_path):
    # Deleting cache_dir/icons/ makes caracole read the icons again from the answers it keeps.
    ug = Site("ug", {"/favicon.ico": (200, png(32))})
    assert fetch(conn, tmp_path, ug).fetched == ["ug"]
    (tmp_path / "icons" / "ug.png").unlink()
    assert fetch(conn, tmp_path, ug, now=NOW + timedelta(days=60)).fetched == ["ug"]
    assert len(ug.asked) == 1


def test_a_spent_budget_leaves_the_icon_for_the_next_run_unmarked(conn, tmp_path):
    site = Site("gtptabs", {"/favicon.ico": (200, png(16))}, budget=0)
    run = fetch(conn, tmp_path, site)
    assert "gtptabs" in run.waiting and not site.asked
    site.budget = 5
    assert fetch(conn, tmp_path, site).fetched == ["gtptabs"]  # the next run, the same day


def test_an_error_is_no_miss_but_waits_a_week(conn, tmp_path):
    site = Site("ug", {"/favicon.ico": (503, b"busy")})
    run = fetch(conn, tmp_path, site)
    assert run.errors == ["ug"] and run.missing == []
    assert len(site.asked) == 1  # the home page isn't asked after an error
    fetch(conn, tmp_path, site, now=NOW + timedelta(days=1))
    assert len(site.asked) == 1
    site.pages["/favicon.ico"] = (200, png(32))
    assert fetch(conn, tmp_path, site, now=NOW + timedelta(days=8)).fetched == ["ug"]


def test_a_block_raises_as_any_block_does_and_the_site_waits_a_week(conn, tmp_path):
    site = Site("ug", {"/favicon.ico": (403, b"no")})
    with pytest.raises(ProviderBlocked):
        fetch(conn, tmp_path, site)
    assert len(site.asked) == 1
    site.pages["/favicon.ico"] = (200, png(32))
    assert fetch(conn, tmp_path, site, now=NOW + timedelta(days=3)).fetched == []
    assert len(site.asked) == 1


def test_asking_now_ignores_the_week(conn, tmp_path):
    site = Site("ug", {"/favicon.ico": (503, b"busy")})
    fetch(conn, tmp_path, site)
    site.pages["/favicon.ico"] = (200, png(32))
    assert fetch(conn, tmp_path, site, wait=None).fetched == ["ug"]


# --- in the nightly run, and on its own ------------------------------------------------------


def icons_step():
    from caracole.pipeline import default_steps

    return [s for s in default_steps() if s.name == "icons"]


def run_icons(conn, cfg, *sites):
    from caracole.notify import Notifier
    from caracole.pipeline import Services, run_pipeline

    clients = {s.provider: s.client(cfg.cache_dir) for s in sites}
    return run_pipeline(cfg, conn=conn, services=Services(clients, Notifier(None)),
                        steps=icons_step(), now=NOW)


def seen_on(conn, *providers):
    """A song with a version from each provider, as a fetch leaves them."""
    from conftest import add_song

    from caracole.versions import upsert_version

    song = add_song(conn, "Radiohead", "Creep")
    for n, provider in enumerate(providers):
        upsert_version(conn, provider=provider, tab_id=str(n), song_id=song.id, slot="sheet", kind="chords",
                       rating=0, votes=0, version=1, label=None, url="https://example.com/", raw={}, now="x")
    return song


def test_the_sources_in_use_are_those_the_library_has_something_from(conn):
    from caracole.songs import update_song

    assert icons.sources_in_use(conn) == set()
    song = seen_on(conn, "ug", "auto")
    assert icons.sources_in_use(conn) == {"ug", "auto"}
    update_song(conn, song.id, lyrics_status="found")
    conn.execute("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (1, 'song/creep-1', "
                 "'creep', 's1')")
    assert icons.sources_in_use(conn) == {"ug", "auto", "lrclib", "musescore"}


def test_an_auto_sheet_made_from_youtube_audio_comes_from_youtube(conn, cfg):
    # autochords/run.py keeps the video in the auto sheet's version when its audio came from YouTube
    # (youtube_fetch.py); a purchase's auto sheet is the audio model's alone.
    from conftest import add_song

    from caracole.library import keep_file
    from caracole.versions import upsert_version

    video = {"id": "XFkzRNyygfk", "title": "Creep", "channel": "Radiohead - Topic",
             "url": "https://www.youtube.com/watch?v=XFkzRNyygfk"}
    kept = {}
    for artist, raw in (("Radiohead", {"audio": "/cache/youtube/1-XFkzRNyygfk.m4a", "youtube": video}),
                        ("Oasis", {"audio": "/music/Oasis - Wonderwall.flac"})):
        song = add_song(conn, artist, "Creep")
        v = upsert_version(conn, provider="auto", tab_id=str(song.id), song_id=song.id, slot="sheet", kind="auto",
                           rating=0, votes=0, version=1, label=None, url=video["url"], raw=raw, now="x")
        keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet (auto).txt", data=b"A\n", rank=1)
        kept[artist] = icons.kept_sources(conn)[song.id]
    assert kept["Radiohead"] == {"sheet (auto).txt": "youtube"}
    assert icons.source_of("sheet (auto).pdf", kept["Radiohead"]) == "youtube"
    assert icons.sheet_source(kept["Radiohead"]) == "youtube"
    assert kept["Oasis"] == {"sheet (auto).txt": "auto"} and icons.sheet_source(kept["Oasis"]) == "auto"


def test_the_nightly_run_asks_only_for_the_icons_of_sources_in_use(conn, cfg):
    ug = Site("ug", {"/favicon.ico": (200, png(32))})
    lacuerda = Site("lacuerda", {"/favicon.ico": (200, png(32))})
    seen_on(conn, "ug")
    report = run_icons(conn, cfg, ug, lacuerda)
    assert icons.icon_uri(cfg.cache_dir, "ug") is not None and not lacuerda.asked
    assert report.ok, report.errors


def test_the_nightly_run_fetches_the_icons_with_its_clients_never_a_cooling_ones(conn, cfg):
    from caracole.health import record_block

    ug = Site("ug", {"/favicon.ico": (200, png(32))})
    lacuerda = Site("lacuerda", {"/favicon.ico": (200, png(32))})
    seen_on(conn, "ug", "lacuerda")
    record_block(conn, "lacuerda", NOW - timedelta(hours=1), "HTTP 403")
    report = run_icons(conn, cfg, ug, lacuerda)
    assert report.ok, report.errors
    assert icons.icon_uri(cfg.cache_dir, "ug") is not None and not lacuerda.asked
    assert "Site icons: 1 fetched." in report.summary()
    # Every icon there, or waiting for a client: a quiet step, with no line in the summary.
    again = run_icons(conn, cfg, ug)
    assert "Site icons" not in again.summary() and len(ug.asked) == 1


def test_a_block_in_the_icons_step_cools_the_provider_down(conn, cfg):
    from caracole.health import is_cooling

    seen_on(conn, "ug")
    report = run_icons(conn, cfg, Site("ug", {"/favicon.ico": (403, b"no")}))
    assert report.blocked == ["ug"] and is_cooling(conn, "ug", NOW + timedelta(hours=1))
    assert report.ok  # a block is expected behaviour, not a failed run


def test_the_icons_step_comes_right_after_the_sync():
    # Before the steps that may spend a site's budget: an icon costs one request, once.
    from caracole.pipeline import default_steps

    names = [s.name for s in default_steps()]
    assert names.index("icons") == names.index("sync") + 1


def icon_sites():
    return {
        "ug": Site("ug", {"/favicon.ico": (200, png(32))}),
        "lacuerda": Site("lacuerda", {"/favicon.ico": (200, ico((32, bmp_image(32))))}),
        "lrclib": Site("lrclib", {"/favicon.ico": (200, ico((16, bmp_image(16)), (32, bmp_image(32))))}),
        "gtptabs": Site("gtptabs", {"/favicon.ico": (200, ico((16, bmp_image(16))))}),
        "musescore": Site("musescore", {"/favicon.ico": (403, b"Just a moment...")}),
        "youtube": Site("youtube", {"/favicon.ico": (200, ico((16, bmp_image(16))))}),
        "harptabs": Site("harptabs", {"/favicon.ico": (200, png(32))}),
        "gametabs": Site("gametabs", {"/favicon.ico": (200, png(32))}),
    }


def icons_command(tmp_path, monkeypatch, sites, extra="", ntfy=None):
    from typer.testing import CliRunner

    from caracole.cli import build_app

    config = tmp_path / "caracole.toml"
    config.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n' + extra,
        encoding="utf-8",
    )
    if ntfy is not None:
        config.write_text(config.read_text(encoding="utf-8") + NTFY_CONFIG, encoding="utf-8")
    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(
        ntfy.handler if provider == "ntfy" else sites[provider].handler))
    monkeypatch.setattr("caracole.commands._common.sleep", lambda s: None)
    return CliRunner().invoke(build_app(), ["--config", str(config), "icons"])


def test_caracole_icons_fetches_what_is_missing_and_rewrites_the_pages(tmp_path, monkeypatch):
    from caracole import db
    from caracole.health import is_cooling

    sites = icon_sites()
    result = icons_command(tmp_path, monkeypatch, sites)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Ultimate Guitar: icon fetched" in out and "YouTube: icon fetched" in out
    assert "MuseScore blocked caracole" in out
    assert "index.html" in out and (tmp_path / "lib" / "index.html").is_file()
    assert sorted(p.name for p in (tmp_path / "cache" / "icons").iterdir()) == [
        "gametabs.png", "gtptabs.png", "harptabs.png", "lacuerda.png", "lrclib.png", "ug.png", "youtube.png"]
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    assert is_cooling(conn, "musescore", datetime.now(UTC))
    conn.close()
    # A second time, every icon is kept or its site cooling down: nothing is asked.
    asked = {k: len(s.asked) for k, s in sites.items()}
    again = icons_command(tmp_path, monkeypatch, sites)
    assert again.exit_code == 0, again.output
    assert {k: len(s.asked) for k, s in sites.items()} == asked
    assert "Ultimate Guitar: kept already" in again.output and "MuseScore: cooling down" in again.output


def test_caracole_icons_sends_one_alert_for_a_block_as_the_nightly_run_does(tmp_path, monkeypatch):
    ntfy = FakeNtfy()
    sites = icon_sites()
    result = icons_command(tmp_path, monkeypatch, sites, ntfy=ntfy)
    assert result.exit_code == 0, result.output
    assert ntfy.titles == ["caracole: MuseScore blocked"]  # the one site that blocked, once
    (alert,) = ntfy.posts
    assert alert.headers["priority"] == "high" and alert.headers["tags"] == "warning"
    assert "MuseScore blocked caracole" in alert.content.decode()
    assert icons_command(tmp_path, monkeypatch, sites, ntfy=ntfy).exit_code == 0  # cooling down: no alert
    assert len(ntfy.posts) == 1


def test_the_pages_after_a_lookup_caracole_icons_let_go_first_read_overrides_toml_again(tmp_path, monkeypatch):
    # In the pause before a site's icon, the command let `caracole get --tab` go first, which pinned a tab: the
    # pages it writes at its end go by overrides.toml as the lookup left it.
    import caracole.commands.icons as cmd
    from caracole.commands import _common

    sites = icon_sites()
    overrides = tmp_path / "lib" / "overrides.toml"
    answer = sites["lrclib"].handler

    def lookup_first(request):
        if not overrides.exists():
            overrides.parent.mkdir(parents=True, exist_ok=True)
            overrides.write_text('[pin]\n"Radiohead - Creep" = ["https://tabs.ultimate-guitar.com/tab/2"]\n',
                                 encoding="utf-8")
            monkeypatch.setattr(_common, "_handoffs", _common.handoffs() + 1)
        return answer(request)

    monkeypatch.setattr(sites["lrclib"], "handler", lookup_first)
    seen = []

    def write_pages(conn, cfg, o, now):
        seen.append([*o.pin.values()])
        return cfg.library_dir / "_todo.md", cfg.library_dir / "index.html"

    monkeypatch.setattr(cmd, "write_pages", write_pages)
    result = icons_command(tmp_path, monkeypatch, sites)
    assert result.exit_code == 0, result.output
    assert seen == [[(2,)]]


def test_caracole_icons_says_when_a_site_has_none_and_leaves_one_turned_off_alone(tmp_path, monkeypatch):
    sites = icon_sites()
    sites["lrclib"].pages = {}
    result = icons_command(tmp_path, monkeypatch, sites, "[providers.gtptabs]\nenabled = false\n")
    assert result.exit_code == 0, result.output
    assert not sites["gtptabs"].asked and "gtptabs.com: turned off" in result.output
    assert "LRCLIB: no icon there; its badge stands in, and the site is asked again in a week" in result.output


def test_caracole_icons_leaves_youtube_alone_once_its_provider_is_turned_off(tmp_path, monkeypatch):
    # YouTube's provider is yt-dlp's (youtube.py): turned off, caracole asks YouTube for nothing.
    sites = icon_sites()
    result = icons_command(tmp_path, monkeypatch, sites, "[providers.youtube]\nenabled = false\n")
    assert result.exit_code == 0, result.output
    assert not sites["youtube"].asked and "YouTube: turned off ([providers.youtube] enabled = false)" in result.output
    assert "Ultimate Guitar: icon fetched" in result.output


def test_caracole_icons_answered_from_the_cache_alone_leaves_a_sites_strikes_as_they_are(tmp_path, monkeypatch):
    # Only a site that answered one of this run's requests had a good run (pipeline._record_ok):
    # an answer from the cache must not undo a block's backoff.
    from caracole import db
    from caracole.db import kv_set_json
    from caracole.health import get_state

    sites = icon_sites()
    sites["musescore"].pages = {"/": (200, b"<html><head><title>no icon links</title></head></html>")}
    first = icons_command(tmp_path, monkeypatch, sites)
    assert "MuseScore: no icon there" in first.output, first.output
    assert len(sites["musescore"].asked) == 2
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    assert get_state(conn, "musescore").last_ok is not None  # it answered, so it was a good run
    # Three blocks in a row since, and the last cooldown just over.
    ended = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kv_set_json(conn, "provider:musescore", {"strikes": 3, "cooldown_until": ended, "last_ok": None,
                                             "last_error": "HTTP 403", "last_error_at": ended})
    conn.commit()
    conn.close()
    again = icons_command(tmp_path, monkeypatch, sites)
    assert again.exit_code == 0, again.output
    assert "MuseScore: no icon there" in again.output
    assert len(sites["musescore"].asked) == 2  # every answer from the cache: nothing sent
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    state = get_state(conn, "musescore")
    conn.close()
    assert (state.strikes, state.last_ok) == (3, None) and state.cooldown_until is not None
