import functools
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from caracole.chordpro import is_chord_line, merge_chord_line, normalize_chord, to_chordpro

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"


def fixture(name: str) -> str:
    """A fixture's text with its line endings intact (UG sends CRLF)."""
    return (FIXTURES / name).read_bytes().decode("utf-8")


def body(content: str, **kw) -> list[str]:
    """The converted document without its header directives."""
    kw.setdefault("title", "Test Song")
    kw.setdefault("artist", "Test Artist")
    lines = to_chordpro(content, **kw).splitlines()
    return [ln for ln in lines if not ln.startswith(("{title:", "{artist:"))]


# --- chord lines over lyric lines -------------------------------------------------


def test_chord_line_merged_into_lyrics():
    content = "[tab][ch]G[/ch]              [ch]D[/ch]\nHello there my friend[/tab]"
    assert body(content) == ["[G]Hello there my [D]friend"]


def test_merge_chord_line_places_chords_at_their_columns():
    assert (
        merge_chord_line("    [ch]Am[/ch]  [ch]F[/ch]", "One two three") == "One [Am]two [F]three"
    )


def test_chords_past_line_end_padded():
    assert merge_chord_line("[ch]C[/ch]       [ch]G[/ch]", "Hi") == "[C]Hi      [G]"


def test_chord_only_line():
    content = "[ch]G[/ch]   [ch]D[/ch]  [ch]Em[/ch]    [ch]C[/ch]\n\nA lyric after a blank"
    assert body(content) == ["[G] [D] [Em] [C]", "", "A lyric after a blank"]


def test_chord_line_before_another_chord_line_is_chord_only():
    content = "[ch]G[/ch]  [ch]D[/ch]\n[ch]Em[/ch]    [ch]C[/ch]\nWords under the second"
    assert body(content) == ["[G] [D]", "[Em]Words [C]under the second"]


def test_chord_line_at_end_is_chord_only():
    assert body("Some words\n[ch]G[/ch] [ch]D[/ch]") == ["Some words", "[G] [D]"]


# --- structure -----------------------------------------------------------------


@pytest.mark.parametrize(
    "header,comment",
    [
        ("[Verse 1]", "Verse 1"),
        ("[Chorus]", "Chorus"),
        ("[Intro]", "Intro"),
        ("  [Pre-Chorus]  ", "Pre-Chorus"),
    ],
)
def test_section_header_becomes_comment(header, comment):
    assert body(header) == [f"{{comment: {comment}}}"]


def test_tab_block_becomes_tab_environment():
    content = "[tab]e|---3---|\nB|---0---|\nG|---0---|[/tab]"
    assert body(content) == [
        "{start_of_tab}",
        "e|---3---|",
        "B|---0---|",
        "G|---0---|",
        "{end_of_tab}",
    ]


def test_header_directives():
    doc = to_chordpro("", title="De Música Ligera", artist="Soda Stereo", key="Bm", capo=2)
    assert doc.splitlines()[:4] == [
        "{title: De Música Ligera}",
        "{artist: Soda Stereo}",
        "{key: Bm}",
        "{capo: 2}",
    ]


def test_header_without_key_or_capo():
    doc = to_chordpro("[ch]G[/ch]", title="T", artist="A")
    assert doc.splitlines() == ["{title: T}", "{artist: A}", "[G]"]


def test_auto_sheet_is_marked_unverified():
    doc = to_chordpro("[ch]G[/ch]", title="T", artist="A", auto=True)
    assert "{comment: auto-generated, unverified}" in doc.splitlines()
    assert "auto-generated" not in to_chordpro("[ch]G[/ch]", title="T", artist="A")


# --- chord lines -----------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "[ch]G[/ch]  [ch]D[/ch]",
        "| [ch]G[/ch] | [ch]D[/ch] |",
        "[ch]Bm[/ch]-[ch]G[/ch]-[ch]D[/ch]-[ch]A[/ch](4)",
        "[ch]G[/ch] / / / [ch]D[/ch] / / /  x2",
        "[ch]Am[/ch]  [ch]G[/ch]  (x4)",
        "  [ch]C[/ch]",
    ],
)
def test_is_chord_line(line):
    assert is_chord_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "Hello there my friend",
        "",
        "CHORDS:[ch]Bm[/ch], [ch]G[/ch], [ch]D[/ch]",
        "   [ch]B[/ch]|3    [ch]B[/ch]|3",
        "[Verse 1]",
    ],
)
def test_is_not_chord_line(line):
    assert not is_chord_line(line)


# --- solfège -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,letter",
    [
        ("Do", "C"),
        ("Re", "D"),
        ("Mi", "E"),
        ("Fa", "F"),
        ("Sol", "G"),
        ("La", "A"),
        ("Si", "B"),
        ("Do#m7", "C#m7"),
        ("Rem", "Dm"),
        ("Sol7", "G7"),
        ("La#m", "A#m"),
        ("Sib", "Bb"),
        ("Mi7/Sol#", "E7/G#"),
        ("Famaj7", "Fmaj7"),
        ("LAm", "Am"),
    ],
)
def test_solfege(name, letter):
    assert normalize_chord(name) == letter


def test_solfege_sequence():
    assert [normalize_chord(c) for c in ["Do", "Rem", "Sol7", "La#m"]] == ["C", "Dm", "G7", "A#m"]


@pytest.mark.parametrize(
    "name", ["C", "C#m7", "Dm", "Dsus4", "Fadd9", "Faug", "Am7/G", "Bb", "N.C."]
)
def test_letter_chords_pass_through(name):
    assert normalize_chord(name) == name


def test_solfege_chords_converted_in_sheet():
    content = "[ch]Do[/ch]   [ch]Rem[/ch]\nHola amigo mio"
    assert body(content) == ["[C]Hola [Dm]amigo mio"]


# --- what ChordPro 6.050.7 would misread (checked against the real binary) ---------

BS = "\\"
ESCAPED_BS = BS + "u005c"  # ChordPro decodes this escape to one backslash


def test_brackets_in_lyrics_are_not_chords():
    assert body("Sing it again [x2]") == ["Sing it again (x2)"]


def test_braces_in_lyrics_are_not_directives_or_substitutions():
    assert body("{softly}") == ["(softly)"]
    assert body("Worth 100%{title} of it") == ["Worth 100%(title) of it"]


def test_leading_hash_is_not_a_comment():
    assert body("#1 in my heart") == [" #1 in my heart"]


def test_trailing_backslash_does_not_join_lines():
    assert body(f"Line ends here {BS}\nNext line") == [f"Line ends here {ESCAPED_BS}", "Next line"]


def test_backslash_u_sequence_is_not_decoded():
    assert body(f"Odd {BS}u0041 text") == [f"Odd {ESCAPED_BS}u0041 text"]


def test_other_backslashes_are_kept():
    assert body(f"Left {BS} right") == [f"Left {BS} right"]


def test_markup_lookalike_is_defused():
    assert body("Hold <b>this</b> note") == ["Hold ‹b>this‹/b> note"]
    assert body("I <3 you") == ["I <3 you"]


def test_markup_in_a_chord_name_is_defused():
    # ChordPro draws chord names with markup, and its <img> opens a local file.
    assert body('[ch]<img src="x.png"/>[/ch]\nHello world') == ['[‹img src="x.png"/>]Hello world']
    assert merge_chord_line('[ch]<img src="x.png"/>[/ch]', "Hi") == '[‹img src="x.png"/>]Hi'


def test_markup_and_braces_in_a_chord_only_line_are_defused():
    assert body("[ch]<b>G</b>[/ch] [ch]{D}[/ch]") == ["[‹b>G‹/b>] [(D)]"]


def test_escaping_keeps_chords_in_place():
    content = "[ch]G[/ch]          [ch]D[/ch]\n[x2] again {and} again"
    assert body(content) == ["[G](x2) again [D](and) again"]


def test_header_values_are_escaped():
    doc = to_chordpro("", title="Hey {You}\nthere", artist="A <b>B</b>", key="Do")
    assert doc.splitlines()[:3] == ["{title: Hey (You) there}", "{artist: A ‹b>B‹/b>}", "{key: C}"]


def test_section_header_text_is_escaped():
    assert body("[Verse %{x}]") == ["{comment: Verse %(x)}"]


def test_tab_lines_kept_verbatim_except_what_chordpro_misreads():
    content = f"[tab]#riff\ne|--5{BS}3--[x]--|\nB|--------{BS}\n{{eot}}\nG|---<b>---|[/tab]"
    assert body(content) == [
        "{start_of_tab}",
        " #riff",
        f"e|--5{BS}3--[x]--|",
        f"B|--------{ESCAPED_BS}",
        "(eot)",
        "G|---<b>---|",
        "{end_of_tab}",
    ]


# --- columns, line endings and marks -----------------------------------------------


def test_chinese_characters_take_two_columns():
    assert (
        merge_chord_line("[ch]C[/ch]       [ch]G[/ch]", "这是一个合成的例子")
        == "[C]这是一个[G]合成的例子"
    )


def test_chord_over_second_half_of_wide_character_goes_before_it():
    assert merge_chord_line(" [ch]Am[/ch]", "测试") == "[Am]测试"


def test_crlf_line_endings():
    assert body("[ch]G[/ch]\r\nHello\r\n\r\nBye\r\n") == ["[G]Hello", "", "Bye"]


def test_repeat_marks_kept_as_annotations():
    assert body("[ch]G[/ch] [ch]D[/ch]  x2") == ["[G] [D] [*x2]"]
    assert body("[ch]Bm[/ch]-[ch]G[/ch](4)") == ["[Bm] [G] [*(4)]"]


def test_repeat_mark_merged_at_its_column():
    assert (
        merge_chord_line("[ch]G[/ch]        (x2)", "Once more again") == "[G]Once more[*(x2)] again"
    )


def test_chord_names_in_running_text_stay_plain():
    content = "CHORDS:[ch]Bm[/ch], [ch]G[/ch], [ch]D[/ch].\n   [ch]B[/ch]|3    [ch]B[/ch]|3"
    assert body(content) == ["CHORDS:Bm, G, D.", "   B|3    B|3"]


def test_staff_lines_outside_tab_block_become_tab_environment():
    content = "[Intro]\ne|-----0-----|\nB|---1---1---|\nG|-2-------2-|\nSome words"
    assert body(content) == [
        "{comment: Intro}",
        "{start_of_tab}",
        "e|-----0-----|",
        "B|---1---1---|",
        "G|-2-------2-|",
        "{end_of_tab}",
        "Some words",
    ]


def test_chord_names_above_staff_in_tab_block_lose_their_tags():
    content = "[tab][ch]G[/ch]    [ch]D[/ch]\ne|--3---2--|\nB|--0---3--|[/tab]"
    assert body(content) == [
        "{start_of_tab}",
        "G    D",
        "e|--3---2--|",
        "B|--0---3--|",
        "{end_of_tab}",
    ]


def test_prose_in_tab_block_is_ordinary_text():
    assert body("[tab]THAT'S IT, MORE LATER.\nBY: SOMEONE[/tab]") == [
        "THAT'S IT, MORE LATER.",
        "BY: SOMEONE",
    ]


def test_blank_lines_kept_inside_trimmed_outside():
    assert body("\n\nOne\n\n\nTwo\n\n") == ["One", "", "", "Two"]


# --- whole sheets ------------------------------------------------------------------


def test_ug_sheet_converts_to_expected_chordpro():
    doc = to_chordpro(
        fixture("ug_sheet.txt"),
        title="Synthetic Test Song",
        artist="The Placeholders",
        key="G",
        capo=2,
    )
    assert doc == fixture("ug_sheet.cho")


def test_chinese_sheet_aligns_chords_by_display_width():
    assert body(fixture("zh_sheet.txt")) == [
        "{comment: Verse}",
        "[C]这是一个[G]合成的例子",
        "[Am]测试歌词第二[F]行",
        "",
        "{comment: Chorus}",
        "[F]和弦[C]只为检查[G]对齐",
    ]


def test_lacuerda_style_sheet():
    content = (
        "Intro:\n\n[ch]Sim[/ch]-[ch]Sol[/ch]-[ch]Re[/ch]-[ch]La[/ch](4)\n\n"
        "[ch]Sim[/ch]      [ch]Sol[/ch]\nPalabras de prueba aqui"
    )
    assert body(content) == [
        "Intro:",
        "",
        "[Bm] [G] [D] [A] [*(4)]",
        "",
        "[Bm]Palabras [G]de prueba aqui",
    ]


def test_marker_only_lines_leave_no_blank_lines():
    assert body("[tab]\n[ch]G[/ch]\nHello\n[/tab]\nNext") == ["[G]Hello", "Next"]


@pytest.mark.parametrize("key,capo", [("  ", None), (None, 0), (None, "0"), ("", " ")])
def test_blank_key_and_zero_capo_are_left_out(key, capo):
    assert to_chordpro("", title="T", artist="A", key=key, capo=capo).splitlines() == [
        "{title: T}",
        "{artist: A}",
    ]


def test_capo_given_as_text():
    assert "{capo: 3}" in to_chordpro("", title="T", artist="A", capo=" 3 ").splitlines()


def test_section_header_with_repeat_mark():
    assert body("[Chorus] x2") == ["{comment: Chorus x2}"]


def test_section_header_followed_by_chords_on_its_line():
    assert body("[Intro] [ch]G[/ch] [ch]D[/ch]\nWords") == ["{comment: Intro}", "[G] [D]", "Words"]


def test_bracketed_note_before_lyrics_stays_a_lyric_line():
    content = "[ch]G[/ch]          [ch]D[/ch]\n[x2] again and again"
    assert body(content) == ["[G](x2) again [D]and again"]


# --- with the real chordpro 6.050.7 ------------------------------------------------

CHORDPRO = os.environ.get("CARACOLE_CHORDPRO_BIN") or shutil.which("chordpro")
real_chordpro = pytest.mark.skipif(CHORDPRO is None, reason="needs the chordpro binary")


def _png(path: Path, width: int, height: int) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@real_chordpro
@pytest.mark.parametrize("image", ["private.png", "missing.png"])
def test_a_chord_name_cannot_embed_or_ask_for_a_local_image(tmp_path, image):
    from caracole.render import render_pdf

    _png(tmp_path / "private.png", 37, 11)  # stands for any image the caracole user can read
    cho = tmp_path / "sheet.cho"
    sheet = f'[ch]<img src="{image}"/>[/ch]\nHello world\n'
    cho.write_text(to_chordpro(sheet, title="T", artist="A"), encoding="utf-8")
    pdf = tmp_path / "sheet.pdf"
    # chordpro resolves the image against its working directory.
    in_tmp = functools.partial(subprocess.run, cwd=tmp_path)
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO, runner=in_tmp)
    data = pdf.read_bytes()
    assert not (b"/Width 37" in data and b"/Height 11" in data)
