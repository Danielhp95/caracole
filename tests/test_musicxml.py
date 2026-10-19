"""The title and creators a MusicXML file names in its header, read cheaply and safely."""

from __future__ import annotations

import pytest
from helpers.scores import musicxml, mxl

from caracole.musicxml import Header, header


def test_an_uncompressed_files_work_title_and_creator():
    assert header(musicxml("Wonderwall", "Oasis"), ".musicxml") == Header("Wonderwall", ("Oasis",))


def test_the_movement_title_stands_in_for_a_missing_work_title():
    assert header(musicxml(None, "Oasis", movement="Wonderwall"), ".musicxml") == Header("Wonderwall", ("Oasis",))
    assert header(musicxml("Wonderwall", "Oasis", movement="Live"), ".musicxml").title == "Wonderwall"


def test_every_creator_is_read():
    xml = musicxml("Wonderwall", "Oasis").replace(
        b"</creator>", b'</creator><creator type="lyricist">Noel Gallagher</creator>', 1)
    assert header(xml, ".musicxml").creators == ("Oasis", "Noel Gallagher")


def test_a_compressed_file_is_read_through_its_container():
    assert header(mxl(musicxml("Wonderwall", "Oasis"), name="Oasis/Wonderwall.musicxml"), ".mxl") == Header(
        "Wonderwall", ("Oasis",))


def test_a_compressed_file_without_a_container_is_read_from_its_xml():
    assert header(mxl(musicxml("Wonderwall", "Oasis"), container=False), ".mxl").title == "Wonderwall"


def test_only_the_header_is_read():
    # Whatever follows the part list is never parsed: a long score costs no more than its header.
    assert header(musicxml("Wonderwall", "Oasis", parts="<part-list>\x01 not XML at all <<<"), ".musicxml") == (
        Header("Wonderwall", ("Oasis",)))


@pytest.mark.parametrize("data,ext", [
    (b"", ".musicxml"),
    (b"%PDF-1.7 not xml", ".musicxml"),
    (b"not a zip", ".mxl"),
    (mxl(b"<score-partwise><work><work-title>Wonder", container=False), ".mxl"),
    (musicxml(None, "Oasis"), ".musicxml"),  # no title at all
])
def test_a_file_without_a_readable_header_has_none(data, ext):
    assert header(data, ext) is None


def test_entities_are_never_expanded_into_a_bomb_or_read_from_a_file():
    # A file dropped into _inbox/ is anyone's: expat's amplification limit stops the first,
    # and an external entity is never fetched.
    bomb = ('<!DOCTYPE score-partwise [<!ENTITY a "aaaaaaaaaa">' + "".join(
        f'<!ENTITY {c} "{("&" + p + ";") * 10}">' for p, c in zip("abcdefgh", "bcdefghi")) + "]>\n")
    assert header(musicxml("&i;", "Oasis", doctype=bomb), ".musicxml") is None
    secret = '<!DOCTYPE score-partwise [<!ENTITY s SYSTEM "file:///etc/hostname">]>\n'
    assert header(musicxml("&s;", "Oasis", doctype=secret), ".musicxml") is None
