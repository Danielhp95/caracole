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


def test_an_unknown_source_still_has_a_name_and_a_tag():
    assert icons.source_name("songsterr") == "songsterr" and icons.tag("songsterr") == "songsterr"
    assert icons.tag("ug") == "UG" and icons.source_name("lrclib") == "LRCLIB"


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

    def client(self, cache_dir: Path) -> PoliteClient:
        return PoliteClient(self.provider, ProviderPolicy(budget=self.budget, delay=(0.0, 0.0)), cache_dir,
                            user_agent="caracole-test", transport=httpx.MockTransport(self.handler),
                            sleep=lambda s: None)


def fetch(conn, cache, *sites, now=NOW, **kw):
    return icons.fetch_icons(conn, cache, {s.provider: s.client(cache) for s in sites}, now, **kw)


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
    assert sorted(run.waiting) == ["gtptabs", "lrclib", "musescore", "youtube"]


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
    assert later.missing == ["lrclib"] and len(site.asked) == 2  # asked again, from the cache: no request


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
    return run_pipeline(cfg, conn=conn, services=Services(clients, None, Notifier(None, None)),
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
    }


def icons_command(tmp_path, monkeypatch, sites, extra=""):
    from typer.testing import CliRunner

    from caracole.cli import build_app

    config = tmp_path / "caracole.toml"
    config.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n' + extra,
        encoding="utf-8",
    )
    monkeypatch.setattr("caracole.commands._common.transport_for",
                        lambda provider: httpx.MockTransport(sites[provider].handler))
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
        "gtptabs.png", "lacuerda.png", "lrclib.png", "ug.png", "youtube.png"]
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    assert is_cooling(conn, "musescore", datetime.now(UTC))
    conn.close()
    # A second time, every icon is kept or its site cooling down: nothing is asked.
    asked = {k: len(s.asked) for k, s in sites.items()}
    again = icons_command(tmp_path, monkeypatch, sites)
    assert again.exit_code == 0, again.output
    assert {k: len(s.asked) for k, s in sites.items()} == asked
    assert "Ultimate Guitar: kept already" in again.output and "MuseScore: cooling down" in again.output


def test_caracole_icons_says_when_a_site_has_none_and_leaves_one_turned_off_alone(tmp_path, monkeypatch):
    sites = icon_sites()
    sites["lrclib"].pages = {}
    result = icons_command(tmp_path, monkeypatch, sites, "[providers.gtptabs]\nenabled = false\n")
    assert result.exit_code == 0, result.output
    assert not sites["gtptabs"].asked and "gtptabs.com: turned off" in result.output
    assert "LRCLIB: no icon there; its badge stands in" in result.output
