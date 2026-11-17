"""ug_urls.py: UG's addresses as an address bar shows them, and a link pasted into a search box.

The shapes are helpers/ug_links.py's, the one list library.js's ``ugLink`` is held to as well
(test_web_page_ug_link.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import subprocess_pythonpath
from helpers.ug_links import SHAPES

from caracole.ug_urls import UgLink, read_link


@pytest.mark.parametrize(("text", "read"), SHAPES, ids=[repr(t)[:60] for t, _ in SHAPES])
def test_a_link_is_read_as_an_address_bar_shows_it(text, read):
    assert read_link(text) == (UgLink(*read) if read is not None else None)


def test_the_address_read_is_the_one_caracole_asks_for_and_reads_the_same_again():
    for text, read in SHAPES:
        if read is not None:
            assert read_link(read[1]) == UgLink(*read), text


def test_overrides_reads_ugs_addresses_the_same_way():
    from caracole.overrides import artist_page_address, pin_url, tab_id_from_url

    for text, read in SHAPES:
        if read is None:
            continue
        if read[0] == "tab":
            assert (pin_url(text), tab_id_from_url(text)) == (read[1], read[2]), text
        else:
            assert artist_page_address(text) == read[1], text


def test_anything_but_text_is_no_link():
    assert read_link(None) is None and read_link(4180894) is None and read_link(b"https://x") is None


@pytest.mark.slow
def test_it_loads_the_standard_library_alone():
    # overrides.py, the library page's routes and the phone's port read links with it: no page parser, no HTTP client.
    code = ("import sys; import caracole.ug_urls; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in "
            "('httpx', 'selectolax', 'tomlkit', 'rapidfuzz', 'pypinyin') or m.startswith('caracole.') "
            "and m != 'caracole.ug_urls'))")
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.strip() == "[]"
