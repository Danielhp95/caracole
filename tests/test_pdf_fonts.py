"""pdf_fonts.py: the folder of fonts the PDFs are set in, and what caracole reads of each font."""

from __future__ import annotations

import pytest

from caracole.pdf_fonts import PdfFonts, in_folder, metrics
from helpers.fonts import PDF_FONTS, font_folder, truetype

adwaita = pytest.mark.skipif(PDF_FONTS is None, reason="set CARACOLE_PDF_FONTS to nix/pdf-fonts.nix's folder")


def test_a_folder_holds_a_font_for_each_role(tmp_path):
    folder = font_folder(tmp_path / "fonts")
    fonts = in_folder(folder)
    assert fonts == PdfFonts(folder, folder / "regular.ttf", folder / "bold.ttf", folder / "italic.ttf",
                             folder / "mono.ttf")


def test_an_otf_will_do_for_a_role(tmp_path):
    folder = font_folder(tmp_path / "fonts")
    (folder / "bold.ttf").rename(folder / "bold.otf")
    assert in_folder(folder).bold == folder / "bold.otf"


def test_a_folder_without_one_of_them_names_it(tmp_path):
    folder = font_folder(tmp_path / "fonts")
    (folder / "italic.ttf").unlink()
    with pytest.raises(FileNotFoundError, match="italic"):
        in_folder(folder)
    with pytest.raises(FileNotFoundError):
        in_folder(tmp_path / "none")


def test_a_fonts_characters_and_their_widths(tmp_path):
    path = tmp_path / "f.ttf"
    path.write_bytes(truetype("ab’é", advance=500))
    found = metrics(path)
    assert set(found.widths) == {"a", "b", "’", "é"}
    assert found.widths["a"] == 500 and not found.variable


def test_a_fonts_characters_from_a_format_4_cmap(tmp_path):
    path = tmp_path / "f.ttf"
    path.write_bytes(truetype("ab’é—Я", advance=500, cmap_format=4))
    assert set(metrics(path).widths) == set("ab’é—Я")


def test_a_variable_font_is_told_apart(tmp_path):
    path = tmp_path / "f.ttf"
    path.write_bytes(truetype("ab", variable=True))
    assert metrics(path).variable


def test_what_isnt_a_font_is_a_value_error(tmp_path):
    path = tmp_path / "f.ttf"
    path.write_bytes(b"not a font at all, just some words")
    with pytest.raises(ValueError):
        metrics(path)


def test_a_font_changed_is_read_again(tmp_path):
    path = tmp_path / "f.ttf"
    path.write_bytes(truetype("ab"))
    assert "c" not in metrics(path).widths
    path.write_bytes(truetype("abc", advance=700))
    assert metrics(path).widths["c"] == 700


@adwaita
def test_adwaita_sans_has_every_latin_greek_and_cyrillic_letter_a_sheet_writes_and_no_chinese():
    fonts = in_folder(PDF_FONTS)
    for role in ("regular", "bold", "italic"):
        found = metrics(getattr(fonts, role))
        assert not found.variable, role  # a static instance: ChordPro draws a variable font's default alone
        assert set("’ʼ“”—éñüçÀßαΩЯж·") <= set(found.widths), role
        assert "斑" not in found.widths
    # Bold is bolder, so wider; Adwaita Mono is monospaced.
    assert metrics(fonts.bold).widths["n"] > metrics(fonts.regular).widths["n"]
    mono = metrics(fonts.mono).widths
    assert mono["i"] == mono["W"] == mono["|"]
