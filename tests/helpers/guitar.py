"""Guitar Pro files for the tests of caracole serve's Guitar Pro page (test_web_guitar.py): a synthetic score, kept
for a song as caracole keeps one, and alphaTab, when the dev shell has it.

``SYNTHETIC`` is tests/fixtures/guitar/synthetic.gp, "Synthetic Étude" (a title whose accent rises above the line
alphaTab hangs it from): two tracks of three bars ("Lead guitar", six strings in dropped D, which alphaTab names in a
box over its strings, score and tab; "Bass", four strings, tab), written by nobody but alphaTab, from
synthetic.alphatex beside it, by its Gp7Exporter (``export_alphatex``: test_web_guitar_browser.py checks the file is
still what alphaTab makes of it). No real song's tab is a fixture here: the repository is public.

``keep_guitar(conn, cfg, song, data)`` records ``data`` as the song's ``guitar-N.<ext>``, as gtptabs_fetch.py keeps
a download (a ``gtptabs`` version of kind ``guitar-pro``, or ``power`` for a .ptb), and returns its library path.

``alphatab_dir()`` is ``CARACOLE_ALPHATAB_DIR`` when it holds alphaTab's three files (both dev shells set it,
nix/alphatab.nix), else the test skips.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from caracole.library import keep_file, song_dir
from caracole.versions import upsert_version

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "guitar"
SYNTHETIC = FIXTURES / "synthetic.gp"
SYNTHETIC_TEX = FIXTURES / "synthetic.alphatex"


def keep_guitar(conn, cfg, song, data: bytes, *, name: str = "guitar-1.gp", tab: str = "12") -> str:
    """``data`` kept as the song's ``name``, as gtptabs.com's download is; its path in the library."""
    kind = "power" if name.lower().endswith(".ptb") else "guitar-pro"
    version = upsert_version(conn, provider="gtptabs", tab_id=tab, song_id=song.id, slot="guitar", kind=kind,
                             rating=4, votes=0, version=1, label=None, url=f"https://gtptabs.com/tabs/{tab}.html",
                             raw={}, now="2026-10-01T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=version, name=name, data=data, rank=1)
    return (song_dir(cfg.library_dir, song) / name).relative_to(cfg.library_dir).as_posix()


def alphatab_dir() -> Path:
    """Where alphaTab's files are (``CARACOLE_ALPHATAB_DIR``); the test skips without them."""
    from caracole.web.alphatab import FILES

    value = os.environ.get("CARACOLE_ALPHATAB_DIR")
    if not value or not all((Path(value) / name).is_file() for name in FILES):
        pytest.skip("CARACOLE_ALPHATAB_DIR doesn't hold alphaTab's files: run the tests in nix develop")
    return Path(value)


def export_alphatex(browser, tex: str) -> bytes:
    """The Guitar Pro 7 file alphaTab's Gp7Exporter writes of the AlphaTex ``tex``, in ``browser``
    (helpers.browser.Browser, on a page of nothing)."""
    from caracole.web.alphatab import LIBRARY

    browser.js((alphatab_dir() / LIBRARY).read_text(encoding="utf-8") + ";0", said="alphaTab")
    written = browser.js(f"""(() => {{
      const settings = new alphaTab.Settings();
      const importer = new alphaTab.importer.AlphaTexImporter();
      importer.initFromString({json.dumps(tex)}, settings);
      const bytes = new alphaTab.exporter.Gp7Exporter().export(importer.readScore(), settings);
      let text = "";
      for (const b of bytes) text += String.fromCharCode(b);
      return btoa(text);
    }})()""", said="Gp7Exporter")
    return base64.b64decode(written)
