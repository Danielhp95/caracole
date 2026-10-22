"""download_names.py: the name a file caracole keeps is downloaded under, and the header that names it."""

from urllib.parse import unquote

import pytest

from caracole.download_names import MAX_BYTES, content_disposition, download_name


def test_a_guitar_pro_file_is_named_for_its_song_its_second_numbered():
    assert download_name("Eagles", "Hotel California", "guitar-1.gp3") == "Eagles - Hotel California.gp3"
    assert download_name("Eagles", "Hotel California", "guitar-2.gp5") == "Eagles - Hotel California (2).gp5"
    assert download_name("Eagles", "Hotel California", "guitar-3.PTB") == "Eagles - Hotel California (3).ptb"
    assert download_name("Eagles", "Hotel California", "score-1.mscz") == "Eagles - Hotel California.mscz"
    assert download_name("Eagles", "Hotel California", "score-2.mid") == "Eagles - Hotel California (2).mid"


def test_accents_and_chinese_stay_and_what_a_system_refuses_goes():
    assert download_name("Joaquín Sabina", "19 días y 500 noches", "guitar-1.gp5") == \
        "Joaquín Sabina - 19 días y 500 noches.gp5"
    assert download_name("宋冬野", "斑马，斑马", "guitar-1.gp") == "宋冬野 - 斑马，斑马.gp"
    assert download_name("AC/DC", 'What Do You Do for Money Honey?', "guitar-1.gp5") == \
        "AC_DC - What Do You Do for Money Honey_.gp5"
    unsafe = download_name('a\\b:c*d"e<f>g|h', "x\ty\x00z\x7f‮.", "guitar-1.gp5")
    assert unsafe == "a_b_c_d_e_f_g_h - x y_z_.gp5"
    assert not any(c in unsafe for c in '/\\:*?"<>|') and all(ord(c) >= 32 for c in unsafe)


def test_a_name_without_one_part_or_with_dots_at_its_ends_is_still_a_file_name():
    assert download_name("", "Untitled", "guitar-1.gp5") == "Untitled.gp5"
    assert download_name("", "", "guitar-2.gp5") == "guitar-2.gp5"
    assert download_name("...", "  ", "guitar-1.gp5") == "guitar-1.gp5"
    assert download_name(".hidden", "Song.", "guitar-1.gp5") == "hidden - Song.gp5"  # never a hidden file
    assert download_name("Muse", "Hysteria", "lyrics.lrc") == "Muse - Hysteria.lrc"


@pytest.mark.parametrize("artist", ["A" * 400, "宋" * 400])
def test_a_long_name_is_cut_on_a_character_keeping_its_number_and_extension(artist):
    name = download_name(artist, "Song", "guitar-2.gp5")
    assert name.endswith(" (2).gp5")
    assert len(name.removesuffix(" (2).gp5").encode("utf-8")) <= MAX_BYTES
    assert len(name.encode("utf-8")) <= 255
    name.encode("utf-8").decode("utf-8")  # whole characters


def test_the_header_names_the_file_in_ascii_and_in_utf_8():
    header = content_disposition("Joaquín Sabina - 19 días y 500 noches (2).gp5")
    assert header == ('attachment; filename="Joaquin Sabina - 19 dias y 500 noches (2).gp5"; '
                      "filename*=UTF-8''Joaqu%C3%ADn%20Sabina%20-%2019%20d%C3%ADas%20y%20500%20noches%20%282%29.gp5")
    chinese = content_disposition("宋冬野 - 斑马.gp")
    fallback = chinese.split('filename="', 1)[1].split('"', 1)[0]
    assert fallback.isascii() and fallback.endswith(".gp")
    assert unquote(chinese.split("filename*=UTF-8''", 1)[1]) == "宋冬野 - 斑马.gp"
    assert content_disposition("100% - Song.gp5").startswith('attachment; filename="100_ - Song.gp5"; ')
