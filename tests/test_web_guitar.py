"""caracole serve's Guitar Pro page (web/guitar_routes.py, guitar_page.py) and alphaTab's bundle (web/alphatab.py),
without a browser: what is shown, what is refused, the policy, the bundle's headers and hashes, and the links to
the page from the library page and the sheet viewer. test_web_guitar_browser.py opens the page in Chromium."""

import base64
import hashlib
import json
import os
import re
from dataclasses import replace
from html import unescape
from urllib.parse import quote, urlencode

import pytest
from helpers.guitar import SYNTHETIC, keep_guitar
from helpers.rendered import rendered_song

from caracole.library import song_dir
from caracole.library_page import WebControls, build_library_page
from caracole.overrides import Overrides
from caracole.render import render_all
from caracole.songs import get_song
from caracole.web import alphatab, guitar_page
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue

from conftest import add_song
from test_web_app import ALLOWED, Recorder, get, header, text

LIBRARY = b"/*! alphaTab, as far as these tests go */\n!function(t){t.alphaTab={}}(this);\n"
FONT = b"wOF2 not a real font"
SOUND_FONT = b"sfbk not a real SoundFont"


@pytest.fixture
def fake_alphatab(tmp_path):
    """A folder with alphaTab's three file names, holding stand-ins: the server reads them, no browser runs them."""
    folder = tmp_path / "alphatab"
    folder.mkdir()
    for name, data in zip(alphatab.FILES, (LIBRARY, FONT, SOUND_FONT), strict=True):
        (folder / name).write_bytes(data)
    return folder


@pytest.fixture
def app(cfg, fake_alphatab):
    return WebApp(replace(cfg, alphatab_dir=fake_alphatab), JobQueue(Recorder()), allowed=ALLOWED, csrf="tok")


def guitar_url(path):
    return "/guitar?" + urlencode({"file": path})


def song_with_gp(conn, cfg, name="guitar-1.gp", data=None):
    song = add_song(conn, "caracole tests", "Synthetic Study")
    return song, keep_guitar(conn, cfg, song, SYNTHETIC.read_bytes() if data is None else data, name=name)


def b64(data):
    return base64.b64encode(data).decode("ascii")


def sha_source(data):
    return "'sha256-" + b64(hashlib.sha256(data).digest()) + "'"


# --- the bundle ------------------------------------------------------------------------------------------------


def test_the_bundle_holds_the_library_in_a_function_with_the_font_and_the_soundfont(fake_alphatab):
    at = alphatab.load(fake_alphatab)
    body = at.body.decode("utf-8")
    font = "data:font/woff2;base64," + b64(FONT)
    assert f"font: {json.dumps(font)}," in body and f"soundFont: {json.dumps(b64(SOUND_FONT))}," in body
    # The library itself, whole, inside the function the page makes its worker from, which the bundle calls.
    assert "library: function () {\n" + LIBRARY.decode() + "\n}\n" in body
    assert body.endswith("window.caracoleAlphaTab.library();\n")
    # Its name holds its hash: a new alphaTab is a new address, so the old one may be kept for good.
    assert re.fullmatch(r"alphatab-1\.8\.4-[0-9a-f]{16}\.js", at.name)
    assert at.name[len("alphatab-1.8.4-"):-3] == hashlib.sha256(at.body).hexdigest()[:16]
    assert at.integrity == "sha256-" + b64(hashlib.sha256(at.body).digest())
    assert at.script_source == sha_source(at.body)
    assert at.font_face == sha_source(alphatab.font_face(font).encode())
    assert at.href == "/assets/alphatab/" + at.name


def test_without_alphatab_s_files_there_is_no_bundle(tmp_path, fake_alphatab):
    assert not alphatab.available(None) and not alphatab.available(tmp_path / "nowhere")
    assert alphatab.available(fake_alphatab)
    short = tmp_path / "short"
    short.mkdir()
    for name in alphatab.FILES[:2]:
        (short / name).write_bytes((fake_alphatab / name).read_bytes())
    with pytest.raises(alphatab.Missing, match="can't be read"):
        alphatab.load(short)


def test_the_font_face_alphatab_adds_is_its_template_with_the_font_s_data_uri():
    css = alphatab.font_face("data:font/woff2;base64,AAAA")
    assert css.startswith("\n            @font-face {\n                font-display: block;\n")
    assert "src: url(\"data:font/woff2;base64,AAAA\") format('woff2');" in css
    assert ".at-surface.at .at {" in css and "font-size: 36px;" in css and css.endswith("!important;\n            }")


# --- the asset route ----------------------------------------------------------------------------------------------


def test_the_bundle_is_served_to_any_origin_and_kept_for_good(app, fake_alphatab):
    at = alphatab.load(fake_alphatab)
    response = get(app, at.href)
    assert response.status == 200 and response.body == at.body
    assert header(response, "content-type") == "text/javascript; charset=utf-8"
    assert header(response, "access-control-allow-origin") == "*"
    assert header(response, "cross-origin-resource-policy") == "cross-origin"
    assert header(response, "cache-control") == "public, max-age=31536000, immutable"
    assert header(response, "x-content-type-options") == "nosniff"
    # Each header once: the route's own wins over the ones every answer has.
    names = [k.lower() for k, _ in response.headers]
    assert len(names) == len(set(names))
    assert header(response, "content-security-policy") == "default-src 'none'; frame-ancestors 'none'"
    assert "sha256-" + b64(hashlib.sha256(response.body).digest()) == at.integrity


def test_any_other_name_there_is_not_found(app, fake_alphatab):
    for name in ("alphaTab.min.js", "Bravura.woff2", "sonivox.sf3", "alphatab-1.8.4-0000000000000000.js", "",
                 "../alphatab/" + alphatab.load(fake_alphatab).name):
        assert get(app, "/assets/alphatab/" + name).status == 404, name


def test_without_alphatab_the_page_says_so_and_there_is_no_bundle(cfg, conn):
    plain = WebApp(cfg, JobQueue(Recorder()), allowed=ALLOWED, csrf="tok")
    _, path = song_with_gp(conn, cfg)
    response = get(plain, guitar_url(path))
    assert response.status == 503 and "CARACOLE_ALPHATAB_DIR" in text(response)
    assert get(plain, "/assets/alphatab/alphatab.js").status == 404
    assert get(plain, "/" + quote(path)).status == 200  # the file is a download all the same


# --- the page ---------------------------------------------------------------------------------------------------


def test_the_page_holds_the_file_and_loads_alphatab_by_its_hash(app, conn, cfg, fake_alphatab):
    song, path = song_with_gp(conn, cfg)
    response = get(app, guitar_url(path))
    assert response.status == 200
    html = text(response)
    at = alphatab.load(fake_alphatab)
    assert f'<script type="application/octet-stream" id="gp">{b64(SYNTHETIC.read_bytes())}</script>' in html
    assert (f'<script src="{at.href}" integrity="{at.integrity}" crossorigin="anonymous"></script>') in html
    assert "<h1>Synthetic Study</h1>" in html and '<header class="top">' in html
    assert '<span class="by">caracole tests</span>' in html and 'title="guitar-1.gp">Guitar Pro 1</span>' in html
    assert f'href="/#song={song.id}"' in html and f'href="/{quote(path)}" download>Download<' in html
    assert ">Sheet<" not in html  # the song has no sheet viewer
    # The page's own script and stylesheet, and the empty stylesheet that keeps alphaTab's shared rules out.
    assert f"<script>{guitar_page.script()}</script>" in html and f"<style>{guitar_page.style()}</style>" in html
    assert f'<style id="alphaTabStyle">{guitar_page.SHARED_STUB}</style>' in html
    # 44 px targets: Play, Stop, the tempo, the tracks, the view switch.
    for control in ('id="play"', 'id="stop"', 'id="tempo"', 'id="tracks"', 'name="view" value="tab"',
                    'name="view" value="score"'):
        assert control in html, control


def test_the_page_s_policy_is_a_sandbox_that_loads_the_bundle_and_nothing_else(app, conn, cfg, fake_alphatab):
    _, path = song_with_gp(conn, cfg)
    at = alphatab.load(fake_alphatab)
    page = guitar_page
    expected = (
        "sandbox allow-scripts allow-downloads; default-src 'none'; "
        f"script-src {at.script_source} {sha_source(page.script().encode())}; "
        f"style-src {sha_source(page.style().encode())} {sha_source(page.SHARED_STUB.encode())} {at.font_face}; "
        "img-src data:; font-src data:; worker-src blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )
    response = get(app, guitar_url(path))
    assert header(response, "content-security-policy") == expected
    # No connect-src: the page asks caracole serve for nothing but the bundle.
    assert "connect-src" not in expected and "unsafe" not in expected


def test_the_page_links_the_song_s_sheet_viewer(app, conn, cfg):
    song = rendered_song(conn, cfg)
    path = keep_guitar(conn, cfg, song, SYNTHETIC.read_bytes(), name="guitar-2.gp5")
    html = text(get(app, guitar_url(path)))
    assert f'href="/{quote("Soda Stereo/De Música Ligera/sheet.html")}">Sheet<' in html
    assert 'title="guitar-2.gp5">Guitar Pro 2</span>' in html


def test_every_format_alphatab_reads_is_shown_and_a_power_tab_file_is_refused(app, conn, cfg):
    song = add_song(conn, "caracole tests", "Every Format")
    for n, ext in enumerate((".gp3", ".gp4", ".gp5", ".gpx", ".gp"), start=1):
        path = keep_guitar(conn, cfg, song, SYNTHETIC.read_bytes() + bytes([n]), name=f"guitar-{n}{ext}", tab=str(n))
        assert get(app, guitar_url(path)).status == 200, ext
    ptb = keep_guitar(conn, cfg, song, b"ptab", name="guitar-9.ptb", tab="9")
    refused = get(app, guitar_url(ptb))
    assert refused.status == 404 and "Power Tab" in unescape(text(refused))


def test_only_a_guitar_pro_file_caracole_keeps_is_shown(app, conn, cfg):
    song, path = song_with_gp(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "guitar-2.gp").write_bytes(SYNTHETIC.read_bytes())  # put there by hand: no record
    (folder / "info.json").write_text("{}")
    for asked in ("caracole tests/Synthetic Study/guitar-2.gp", "caracole tests/Synthetic Study/info.json",
                  "caracole tests/Synthetic Study/../Synthetic Study/guitar-1.gp", "../" + path, "/" + path,
                  path + "\n", "", "state/caracole.sqlite"):
        response = get(app, guitar_url(asked))
        assert response.status == 404, asked
        assert "That isn't a Guitar Pro file caracole keeps" in unescape(text(response))
    assert get(app, "/guitar").status == 404
    assert get(app, guitar_url(path) + "&" + urlencode({"file": path})).status == 404  # one file, not two


def test_a_link_in_place_of_the_file_or_of_its_folder_is_refused(app, conn, cfg, tmp_path):
    song, path = song_with_gp(conn, cfg)
    file = cfg.library_dir / path
    elsewhere = tmp_path / "elsewhere.gp"
    elsewhere.write_bytes(SYNTHETIC.read_bytes())
    file.unlink()
    file.symlink_to(elsewhere)
    response = get(app, guitar_url(path))
    assert response.status == 404 and "isn't in the library any more" in unescape(text(response))
    # The song's folder a link to another folder, the file in it: still refused.
    file.unlink()
    folder = song_dir(cfg.library_dir, song)
    os.rename(folder, tmp_path / "moved")
    (tmp_path / "moved" / "guitar-1.gp").write_bytes(SYNTHETIC.read_bytes())
    folder.symlink_to(tmp_path / "moved")
    assert get(app, guitar_url(path)).status == 404


def test_a_file_gone_from_the_library_says_so(app, conn, cfg):
    _, path = song_with_gp(conn, cfg)
    (cfg.library_dir / path).unlink()
    response = get(app, guitar_url(path))
    assert response.status == 404 and "isn't in the library any more" in unescape(text(response))


# --- the links to it --------------------------------------------------------------------------------------------


def test_the_served_library_page_gives_each_guitar_pro_file_its_page(conn, cfg, tmp_path):
    from datetime import UTC, datetime

    song, path = song_with_gp(conn, cfg)
    keep_guitar(conn, cfg, song, b"ptab", name="guitar-2.ptb", tab="13")
    (song_dir(cfg.library_dir, song) / "guitar-3.gp5").write_bytes(b"by hand")  # not kept: a file like any
    now = datetime(2026, 10, 21, tzinfo=UTC)
    for guitar in (True, False):
        html = build_library_page(conn, cfg, Overrides(), now, controls=WebControls("tok", guitar=guitar))
        data = json.loads(re.search(r'<script type="application/json" id="songs">(.*?)</script>', html, re.S)[1])
        assert data["server"]["guitar"] is guitar
        files = {f["name"]: f for f in data["songs"][0]["files"]}
        assert files["guitar-1.gp"]["guitarPage"] == "guitar?" + urlencode({"file": path})
        assert "guitarPage" not in files["guitar-2.ptb"] and "guitarPage" not in files["guitar-3.gp5"]
    # The page opened as a file has the same data, and no server to open it: its script lists the file alone.
    html = build_library_page(conn, cfg, Overrides(), now)
    assert '"server"' not in html


def test_the_library_page_served_says_where_the_alphatab_is(app, conn, cfg):
    song_with_gp(conn, cfg)
    html = text(get(app, "/"))
    assert '"guitar":true' in html
    plain = WebApp(cfg, JobQueue(Recorder()), allowed=ALLOWED, csrf="tok")
    assert '"guitar":false' in text(get(plain, "/"))


def test_each_viewer_of_a_song_with_a_guitar_pro_file_names_it(conn, cfg):
    song = rendered_song(conn, cfg)
    sheet = song_dir(cfg.library_dir, song) / "sheet.html"
    assert 'id="guitar-row"' not in sheet.read_text() and '"guitar":' not in sheet.read_text()  # no such data key
    keep_guitar(conn, cfg, song, SYNTHETIC.read_bytes(), name="guitar-1.gpx")
    keep_guitar(conn, cfg, song, b"ptab", name="guitar-2.ptb", tab="13")
    from helpers.rendered import fake_chordpro

    render_all(conn, cfg, Overrides(), runner=fake_chordpro)
    page = sheet.read_text()
    assert 'id="guitar-row"' in page and '"guitar":["guitar-1.gpx"]' in page
    assert get_song(conn, song.id).id == song.id
