"""songbook_section.songbooks_data: the Songbooks tab's data, and the files a caracole makes of a songbook.

The computer makes a songbook's PDF, its page for the phone and its ChordPro file; the phone makes the page alone
(``files``, the phone's ``[("songbook.html", "Phone page")]``), never chordpro's PDF or .cho: its tab names those it
makes, in their order, and links only them, whatever else is in the folder.
"""

from __future__ import annotations

from caracole.overrides import Overrides
from caracole.songbook import FILE_NAME, FOLDER, make_songbook
from caracole.songbook_section import FILES, songbooks_data

PHONE = (("songbook.html", "Phone page"),)


def _campfire(cfg) -> None:
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    make_songbook(cfg.library_dir / FILE_NAME, "Camp Fire", ["Oasis - Wonderwall"])
    folder = cfg.library_dir / FOLDER / "Camp Fire"
    folder.mkdir(parents=True)
    for name in ("songbook.pdf", "songbook.html", "songbook.cho"):
        (folder / name).write_bytes(b"made")


def test_a_songbooks_files_are_the_computers_by_default(conn, cfg):
    _campfire(cfg)
    data = songbooks_data(conn, cfg, Overrides())
    assert data["fileLabels"] == [label for _, label in FILES] == ["PDF", "PDF, Traditional", "Phone page", "ChordPro"]
    [book] = data["books"]
    assert [(f["name"], f["label"], f["href"]) for f in book["files"]] == [
        ("songbook.pdf", "PDF", "_songbooks/Camp%20Fire/songbook.pdf"),
        ("songbook.html", "Phone page", "_songbooks/Camp%20Fire/songbook.html"),
        ("songbook.cho", "ChordPro", "_songbooks/Camp%20Fire/songbook.cho")]


def test_the_phone_makes_its_page_alone_and_its_tab_links_nothing_else(conn, cfg):
    _campfire(cfg)
    data = songbooks_data(conn, cfg, Overrides(), files=PHONE)
    assert data["fileLabels"] == ["Phone page"]
    [book] = data["books"]
    assert [(f["name"], f["label"]) for f in book["files"]] == [("songbook.html", "Phone page")]
    assert book["changed"] is not None  # when the page was written: the PDF beside it says nothing
    (cfg.library_dir / FOLDER / "Camp Fire" / "songbook.html").unlink()
    [book] = songbooks_data(conn, cfg, Overrides(), files=PHONE)["books"]
    assert book["files"] == [] and book["changed"] is None


def test_a_songbooks_file_that_cant_be_read_names_the_files_all_the_same(conn, cfg):
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    (cfg.library_dir / FILE_NAME).write_text("[broken\n", encoding="utf-8")
    data = songbooks_data(conn, cfg, Overrides(), files=PHONE)
    assert data["books"] == [] and data["error"] and data["fileLabels"] == ["Phone page"]
