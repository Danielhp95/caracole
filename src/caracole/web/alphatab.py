"""alphaTab, which the Guitar Pro page (guitar_routes.py) draws and plays a song's Guitar Pro file with, as the one
script caracole serve sends that page besides its own.

alphaTab 1.8.4 (@coderline/alphatab, MPL-2.0) is not in nixpkgs: nix/alphatab.nix fetches its npm package and
keeps three files of it, which the packages' wrapper and the dev shells point ``CARACOLE_ALPHATAB_DIR`` at
(``Config.alphatab_dir``): its browser build (``LIBRARY``), the Bravura music font (``FONT``, SIL OFL 1.1) and the
Sonivox SoundFont its synthesizer plays (``SOUND_FONT``, Apache-2.0). Without them caracole serve runs all the
same, and a Guitar Pro file is a download alone (``available``).

The three go to the page as one script, the bundle (``bundle``), made once a process: the font as a ``data:`` URI,
the SoundFont in base64, and the library itself inside a function (``window.caracoleAlphaTab.library``), which the
bundle then calls. The page is served in a sandbox, an origin of its own, where a Web Worker can't load a script
from the server: alphaTab's synthesizer runs in a worker made from a ``blob:`` of that function's own text
(``Function.prototype.toString``, the very text the bundle holds), so the library comes once, and nothing is
asked for but the bundle. The page loads it from caracole serve by ``<script src integrity crossorigin>``, which
its Content-Security-Policy allows by the bundle's SHA-256 (``script_source``), as Subresource Integrity checks it
(``integrity``); its address names its hash (``name``), so it can be kept for good (``ASSETS``).

alphaTab adds one stylesheet of its own to the page, the music font's ``@font-face`` and the rule that sets it,
whose text is known beforehand from the font's ``data:`` URI: the policy allows it by its hash (``font_face``).
A browser test pins it (test_web_guitar.py), so an alphaTab whose stylesheet differs fails there, not on a
phone. Its other stylesheet, its shared rules, it adds only when the page has none named ``alphaTabStyle``: the
page has one, and those two rules in its own stylesheet (guitar_page.py).
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from caracole.inline import sha256_source

VERSION = "1.8.4"
LIBRARY = "alphaTab.min.js"
FONT = "Bravura.woff2"
SOUND_FONT = "sonivox.sf3"
FILES = (LIBRARY, FONT, SOUND_FONT)
ASSETS = "/assets/alphatab/"  # where caracole serve answers the bundle (guitar_routes.py)
MUSIC_FONT_SIZE = 36  # px: alphaTab's engraving settings' musicFontSize, which its @font-face style names
MAX_BYTES = 16 * 1024 * 1024  # each file: alphaTab's is about 1.1 MB, the SoundFont 1 MB


class Missing(Exception):
    """alphaTab's files aren't there (``CARACOLE_ALPHATAB_DIR`` unset, or a file of it missing or unreadable)."""


@dataclass(frozen=True)
class AlphaTab:
    """The bundle, as the page loads it: ``name``, its file name under ``ASSETS``; ``body``, its bytes;
    ``integrity``, its SRI string; ``script_source``, the CSP source that allows it; ``font_face``, the CSP
    source that allows the stylesheet alphaTab adds."""

    name: str
    body: bytes
    integrity: str
    script_source: str
    font_face: str

    @property
    def href(self) -> str:
        return ASSETS + self.name


def available(directory: Path | None) -> bool:
    """Whether alphaTab's files are in ``directory`` (``Config.alphatab_dir``) and can be read."""
    try:
        load(directory)
    except Missing:
        return False
    return True


def load(directory: Path | None) -> AlphaTab:
    """The bundle made from the files in ``directory``; Missing without them."""
    if directory is None:
        raise Missing("CARACOLE_ALPHATAB_DIR is not set")
    return _load(Path(directory))


@lru_cache(maxsize=4)
def _load(directory: Path) -> AlphaTab:
    try:
        library, font, sound_font = (_read(directory / name) for name in FILES)
    except OSError as e:
        raise Missing(f"alphaTab's files can't be read in {directory}: {e}") from e
    try:
        text = library.decode("utf-8")
    except UnicodeDecodeError as e:
        raise Missing(f"{directory / LIBRARY} isn't UTF-8") from e
    font_uri = "data:font/woff2;base64," + base64.b64encode(font).decode("ascii")
    body = bundle(text, font_uri, base64.b64encode(sound_font).decode("ascii")).encode("utf-8")
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode("ascii")
    return AlphaTab(
        name=f"alphatab-{VERSION}-{hashlib.sha256(body).hexdigest()[:16]}.js",
        body=body,
        integrity=f"sha256-{digest}",
        script_source=f"'sha256-{digest}'",
        font_face=sha256_source(font_face(font_uri)),
    )


def _read(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise OSError(f"{path.name} is larger than {MAX_BYTES} bytes")
    return data


def bundle(library: str, font_uri: str, sound_font: str) -> str:
    """The one script the page loads: the font and the SoundFont as data, and the library in a function the
    page's worker is made from (its text), called at once."""
    return (
        f"/* alphaTab {VERSION} (MPL-2.0), the Bravura font (SIL OFL 1.1) and the Sonivox SoundFont (Apache-2.0),\n"
        "   for caracole serve's Guitar Pro page: their licences are beside the files caracole read. */\n"
        "window.caracoleAlphaTab = {\n"
        f"font: {json.dumps(font_uri)},\n"
        f"soundFont: {json.dumps(sound_font)},\n"
        "library: function () {\n"
        f"{library}\n"
        "}\n"
        "};\n"
        "window.caracoleAlphaTab.library();\n"
    )


def font_face(font_uri: str) -> str:
    """The stylesheet alphaTab 1.8.4 adds to the page for its music font (``BrowserUiFacade._createStyleElements``),
    given the font's only source, ``font_uri``, as the page sets it (``core.smuflFontSources``), the first and only
    font it registers (no number after its family's name)."""
    return (
        "\n            @font-face {\n"
        "                font-display: block;\n"
        "                font-family: 'alphaTab';\n"
        f"                src: url({json.dumps(font_uri)}) format('woff2');\n"
        "                font-weight: normal;\n"
        "                font-style: normal;\n"
        "            }\n"
        "            .at-surface.at .at {\n"
        "                font-family: 'alphaTab';\n"
        "                speak: none;\n"
        "                font-style: normal;\n"
        "                font-weight: normal;\n"
        "                font-variant: normal;\n"
        "                text-transform: none;\n"
        "                line-height: 1;\n"
        "                line-height: 1;\n"
        "                -webkit-font-smoothing: antialiased;\n"
        "                -moz-osx-font-smoothing: grayscale;\n"
        f"                font-size: {MUSIC_FONT_SIZE}px;\n"
        "                overflow: visible !important;\n"
        "            }"
    )
