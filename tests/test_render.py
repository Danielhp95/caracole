import json
import os
import re
import shutil
import struct
import subprocess
import unicodedata
import zlib
from pathlib import Path

import pytest

from caracole.pdf_fonts import in_folder
from caracole.pdf_text import pdf_text as printed_text
from caracole.render import STYLE_FILE, RenderError, needs_font_file, pdf_font, render_pdf, write_chordpro
from caracole.viewer.theory import Key
from helpers.fonts import PDF_FONTS, font_folder
from helpers.pdf_pages import decode, pdf_objects, pdf_pages, to_unicode as parse_to_unicode

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
CHORDPRO = os.environ.get("CARACOLE_CHORDPRO_BIN") or shutil.which("chordpro")
CJK_FONT = os.environ.get("CARACOLE_CJK_FONT")

real_chordpro = pytest.mark.skipif(
    CHORDPRO is None, reason="chordpro not found on PATH or in CARACOLE_CHORDPRO_BIN"
)
cjk_font = pytest.mark.skipif(
    not (CJK_FONT and Path(CJK_FONT).is_file()),
    reason="set CARACOLE_CJK_FONT to a single-font CJK .ttf/.otf",
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("utf-8")


class FakeRunner:
    """Stands in for subprocess.run: records the command and writes a dummy PDF."""

    def __init__(self, returncode: int = 0, stderr: str = "", write: bool = True):
        self.returncode, self.stderr, self.write = returncode, stderr, write
        self.cmd: list[str] = []
        self.kwargs: dict = {}

    def __call__(self, cmd, **kwargs):
        self.cmd, self.kwargs = list(cmd), kwargs
        if self.write and self.returncode == 0:
            out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output="))
            Path(out).write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(cmd, self.returncode, stdout="", stderr=self.stderr)


def sfnt(glyph_lengths=(10, 12), *, short_loca: bool = False, cff: bool = False) -> bytes:
    """A skeletal font: only the tables render.py's font check reads."""

    def head(loca_format: int) -> bytes:
        return bytes(50) + struct.pack(">hh", loca_format, 0)

    if cff:
        tables = {b"CFF ": bytes(4), b"head": head(0)}
    else:
        offsets = [0]
        for n in glyph_lengths:
            offsets.append(offsets[-1] + n)
        if short_loca:
            loca = struct.pack(f">{len(offsets)}H", *(o // 2 for o in offsets))
        else:
            loca = struct.pack(f">{len(offsets)}I", *offsets)
        tables = {b"glyf": bytes(offsets[-1]), b"head": head(0 if short_loca else 1), b"loca": loca}
    directory, data = b"", b""
    start = 12 + 16 * len(tables)
    for tag, body in tables.items():
        directory += struct.pack(">4sIII", tag, 0, start + len(data), len(body))
        data += body + bytes(-len(body) % 4)
    version = b"OTTO" if cff else b"\x00\x01\x00\x00"
    return version + struct.pack(">HHHH", len(tables), 0, 0, 0) + directory + data


@pytest.fixture
def font(tmp_path) -> Path:
    path = tmp_path / "Font.ttf"
    path.write_bytes(sfnt())
    return path


@pytest.fixture
def cho(tmp_path) -> Path:
    path = tmp_path / "sheet.cho"
    path.write_text("{title: T}\n{artist: A}\n[G]Hello\n", encoding="utf-8")
    return path


# --- the command line ---------------------------------------------------------------


def test_render_pdf_command_line(cho, tmp_path):
    pdf = tmp_path / "sheet.pdf"
    run = FakeRunner()
    render_pdf(cho, pdf, chordpro_bin="/opt/chordpro/bin/chordpro", runner=run)
    assert run.cmd[0] == "/opt/chordpro/bin/chordpro"
    assert f"--output={pdf}" in run.cmd
    assert run.cmd[-1] == str(cho)
    assert pdf.exists()


def test_chordpro_transposes_nothing(cho, tmp_path):
    # The text it is given names each chord where the song is played, as the viewer does
    # (viewer/version.py apply_version): chordpro's own transposition spells A# for Bb.
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", runner=run)
    assert not any(a.startswith("--transpose") for a in run.cmd)
    with pytest.raises(TypeError):
        render_pdf(cho, tmp_path / "sheet.pdf", transpose=-2, runner=run)


def test_default_configs_are_ignored(cho, tmp_path):
    """ChordPro would read sheet.json (UG's raw JSON) beside sheet.cho as a song config."""
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", runner=run)
    assert "--nodefaultconfigs" in run.cmd


def test_the_pdf_takes_caracoles_style(cho, tmp_path):
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", runner=run)
    assert f"--config={STYLE_FILE}" in run.cmd
    assert run.cmd.index("--nodefaultconfigs") < run.cmd.index(f"--config={STYLE_FILE}")


def test_the_style_puts_key_and_capo_under_the_title_and_colours_the_chords():
    pdf = json.loads(STYLE_FILE.read_text(encoding="utf-8"))["pdf"]
    # ChordPro prints neither {artist} nor {capo} by default; a capo the guitarist can't see
    # means playing in the wrong key. A sheet's PDF says its {subtitle} (pdf_text.py: the viewer's
    # key line, a tuning), and a text with none (a songbook's song) the key, transposed along with
    # the chords, and the capo.
    assert pdf["formats"]["title"]["title"] == ["%{title}", "", ""]
    assert pdf["formats"]["title"]["subtitle"] == ["%{subtitle}", "", ""]
    assert pdf["fonts"]["chord"]["name"] == "Helvetica-Bold" and pdf["fonts"]["chord"]["color"] == "#b4441e"
    # White, not the theme's foreground-light, which chordpro would put behind every section name.
    assert pdf["fonts"]["comment"] == {"name": "Helvetica-Bold", "size": 9, "color": "#b4441e", "background": "#ffffff"}
    assert pdf["diagrams"]["show"] == "top"  # the shapes before the song, not after it
    # The chord boxes of style C as the sketches page rendered it (B's 9 pt boxes, smaller in two columns)
    assert {k: pdf["diagrams"][k] for k in ("width", "height", "hspace", "dotsize")} == {
        "width": 7, "height": 7, "hspace": 3.6, "dotsize": 0.85}


def test_the_style_leaves_every_text_element_to_the_cjk_font():
    # An element naming a font file of its own would keep a Chinese sheet's font file from it.
    fonts = json.loads(STYLE_FILE.read_text(encoding="utf-8"))["pdf"]["fonts"]
    assert all("file" not in font for font in fonts.values())


def test_font_file_used_for_lyrics_and_titles(cho, font, tmp_path):
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", font_file=font, runner=run)
    assert f"--define=pdf.fonts.text.file={font}" in run.cmd
    assert f"--define=pdf.fonts.title.file={font}" in run.cmd


def test_no_font_options_without_font_file(cho, tmp_path):
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", runner=run)
    assert not any("pdf.fonts" in a for a in run.cmd)


def test_font_collection_rejected(cho, tmp_path):
    font = tmp_path / "NotoSansCJK-VF.otf.ttc"
    font.write_bytes(b"ttcf" + bytes(60))
    with pytest.raises(RenderError, match="collection"):
        render_pdf(cho, tmp_path / "sheet.pdf", font_file=font, runner=FakeRunner())


def test_font_with_odd_length_glyphs_rejected(cho, tmp_path):
    """PDF::API2 2.045 corrupts subsets of such fonts: the PDF would lose glyphs silently."""
    font = tmp_path / "LXGWNeoXiHei.ttf"
    font.write_bytes(sfnt((10, 11, 12)))
    run = FakeRunner()
    with pytest.raises(RenderError, match="odd-length glyph"):
        render_pdf(cho, tmp_path / "sheet.pdf", font_file=font, runner=run)
    assert run.cmd == []


@pytest.mark.parametrize("data", [sfnt((10, 12)), sfnt((10, 12), short_loca=True), sfnt(cff=True)])
def test_fonts_chordpro_embeds_correctly_accepted(cho, tmp_path, data):
    font = tmp_path / "Font.ttf"
    font.write_bytes(data)
    render_pdf(cho, tmp_path / "sheet.pdf", font_file=font, runner=FakeRunner())


def test_non_font_rejected(cho, tmp_path):
    font = tmp_path / "notes.ttf"
    font.write_bytes(b"just some text, not a font")
    with pytest.raises(RenderError, match="not a TrueType/OpenType font"):
        render_pdf(cho, tmp_path / "sheet.pdf", font_file=font, runner=FakeRunner())


def test_missing_font_file_rejected(cho, tmp_path):
    with pytest.raises(RenderError, match="font file not found"):
        render_pdf(
            cho, tmp_path / "sheet.pdf", font_file=tmp_path / "gone.ttf", runner=FakeRunner()
        )


# --- the fonts the PDFs are set in (pdf_fonts) ---------------------------------------------------

# Every element chordpro sets text in: STYLE_FILE's, and those chordpro derives from another's (its
# Output/PDF.pm configurator), which a font file of the other's would set otherwise.
CHORDPRO_ELEMENTS = {"title", "subtitle", "text", "chorus", "empty", "chord", "annotation", "comment",
                     "comment_italic", "comment_box", "tab", "footer", "toc", "diagram", "diagram_base", "grid",
                     "grid_margin"}


def defined_fonts(cmd: list[str]) -> dict[str, str]:
    """The font file a chordpro command line gives each element."""
    return {name.removeprefix("pdf.fonts.").removesuffix(".file"): value
            for name, _, value in (a.removeprefix("--define=").partition("=") for a in cmd if a.startswith("--define="))
            if name.startswith("pdf.fonts.")}


def test_the_pdf_fonts_set_every_element_bold_italic_or_mono_as_the_style_has_it(cho, tmp_path):
    fonts = in_folder(font_folder(tmp_path / "fonts"))
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", fonts=fonts, runner=run)
    defined = defined_fonts(run.cmd)
    assert set(defined) == CHORDPRO_ELEMENTS >= set(json.loads(STYLE_FILE.read_text(encoding="utf-8"))["pdf"]["fonts"])
    by_file = {path: {e for e, p in defined.items() if p == str(path)} for path in
               (fonts.regular, fonts.bold, fonts.italic, fonts.mono)}
    assert by_file == {
        fonts.regular: {"text", "subtitle", "chorus", "empty", "comment_box", "footer", "toc", "diagram_base"},
        fonts.bold: {"title", "chord", "comment", "diagram", "grid", "grid_margin"},
        fonts.italic: {"annotation", "comment_italic"},
        fonts.mono: {"tab"},
    }


def test_a_cjk_font_takes_the_words_from_the_pdf_fonts_as_it_takes_them_from_the_built_in_ones(cho, font, tmp_path):
    # The elements a CJK font's file reaches today through chordpro's derivations (text, title, and all that
    # derive from text); the chords, their annotations and the tab keep the PDF fonts as they keep Helvetica and Courier.
    fonts = in_folder(font_folder(tmp_path / "fonts"))
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", fonts=fonts, font_file=font, runner=run)
    defined = defined_fonts(run.cmd)
    assert {e for e, p in defined.items() if p == str(font)} == CHORDPRO_ELEMENTS - {"chord", "annotation", "grid", "tab"}
    assert (defined["chord"], defined["annotation"], defined["grid"], defined["tab"]) == (
        str(fonts.bold), str(fonts.italic), str(fonts.bold), str(fonts.mono))


def test_pdf_fonts_chordpro_would_draw_wrongly_are_refused(cho, tmp_path):
    fonts = in_folder(font_folder(tmp_path / "fonts", bold=sfnt((10, 11, 12))))
    run = FakeRunner()
    with pytest.raises(RenderError, match="odd-length glyph"):
        render_pdf(cho, tmp_path / "sheet.pdf", fonts=fonts, runner=run)
    assert run.cmd == []


@pytest.mark.parametrize("text", ["Don’t stop me now", "Epicʼs song", "Fito Páez, señorita", "Λάμπρος",
                                  "Кино — Группа крови", "Smart “quotes” · x2"])
def test_with_the_pdf_fonts_latin_greek_or_cyrillic_needs_no_cjk_font(tmp_path, font, text):
    fonts = in_folder(font_folder(tmp_path / "fonts"))
    assert pdf_font(text, font, fonts) == (None, None)


def test_with_the_built_in_fonts_a_modifier_apostrophe_took_the_cjk_font_and_still_does(font):
    # The Epic songbook went brush entirely for one ʼ (U+02BC, a letter cp1252 lacks): no pdf_fonts, no change.
    assert pdf_font("Epicʼs song", font) == (font, None)
    assert pdf_font("Don’t stop", font) == (None, None)  # ’ is in WinAnsi


def test_with_the_pdf_fonts_chinese_takes_the_cjk_font_or_waits_for_one(tmp_path, font):
    fonts = in_folder(font_folder(tmp_path / "fonts"))
    assert pdf_font("斑马斑马 · Don’t", font, fonts) == (font, None)
    assert pdf_font("Don’t 斑马斑马", None, fonts) == (None, "斑")


def test_with_the_pdf_fonts_a_symbol_they_lack_never_brings_the_cjk_font(tmp_path, font):
    fonts = in_folder(font_folder(tmp_path / "fonts"))
    assert pdf_font("Una canción ♪ \U0001f3b8", font, fonts) == (None, None)  # blemished, not brushed
    assert pdf_font("Una canción ♪", font) == (font, None)  # as with the built-in fonts today


# --- failures -------------------------------------------------------------------------


def test_nonzero_exit_raises_with_stderr(cho, tmp_path):
    run = FakeRunner(
        returncode=2, stderr='No font found for "text"\nUnhandled fonts detected -- aborted\n'
    )
    with pytest.raises(RenderError) as err:
        render_pdf(cho, tmp_path / "sheet.pdf", runner=run)
    assert "Unhandled fonts detected" in err.value.stderr
    assert "Unhandled fonts detected" in str(err.value)


def test_missing_binary_raises_render_error(cho, tmp_path):
    with pytest.raises(RenderError, match="not found"):
        render_pdf(cho, tmp_path / "sheet.pdf", chordpro_bin=str(tmp_path / "no-such-chordpro"))


def test_timeout_raises_render_error(cho, tmp_path):
    def hang(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    with pytest.raises(RenderError, match="timed out"):
        render_pdf(cho, tmp_path / "sheet.pdf", runner=hang)


def test_success_without_pdf_raises(cho, tmp_path):
    with pytest.raises(RenderError, match="no PDF"):
        render_pdf(cho, tmp_path / "sheet.pdf", runner=FakeRunner(write=False))


# --- when a sheet needs font_file -------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["De Música Ligera, señorita", "Hold \u2039b> note \u00d72", "Smart “quotes” — dash"]
)
def test_core_fonts_cover_latin_text(text):
    assert not needs_font_file(text)


@pytest.mark.parametrize("text", ["斑马斑马", "宋冬野", "Mix of 中文 and words", "Привет"])
def test_text_beyond_winansi_needs_font_file(text):
    assert needs_font_file(text)


# --- writing the .cho -------------------------------------------------------------------


def test_write_chordpro(tmp_path):
    path = write_chordpro(
        "[ch]G[/ch]\nHello",
        tmp_path / "Artist" / "Song" / "sheet.cho",
        title="T",
        artist="A",
        key="G",
    )
    assert path == tmp_path / "Artist" / "Song" / "sheet.cho"
    assert path.read_text(encoding="utf-8") == "{title: T}\n{artist: A}\n{key: G}\n[G]Hello\n"


def test_write_chordpro_leaves_unchanged_file_alone(tmp_path):
    path = write_chordpro("[ch]G[/ch]\nHello", tmp_path / "sheet.cho", title="T", artist="A")
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    write_chordpro("[ch]G[/ch]\nHello", path, title="T", artist="A")
    assert path.stat().st_mtime_ns == 1_000_000_000
    write_chordpro("[ch]D[/ch]\nHello", path, title="T", artist="A")
    assert "[D]Hello" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("planted", ["link", "fifo"])
def test_write_chordpro_refuses_what_is_not_a_regular_file(tmp_path, planted):
    # The old file is read only to compare, but anyone who can write to the library can
    # plant a link there to any file caracole can read, or a FIFO that never answers.
    secret = tmp_path / "private.json"
    secret.write_text('{"token": "secret"}', encoding="utf-8")
    cho = tmp_path / "sheet.cho"
    if planted == "link":
        cho.symlink_to(secret)
    else:
        os.mkfifo(cho)
    problem = "symbolic link" if planted == "link" else "not a regular file"
    with pytest.raises(RenderError, match=problem):
        write_chordpro("[ch]G[/ch]\nHello", cho, title="T", artist="A")
    assert secret.read_text(encoding="utf-8") == '{"token": "secret"}'


# --- the real binary ----------------------------------------------------------------------

CORE_FONTS = {
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Symbol",
    "ZapfDingbats",
}


def pdf_strings(path: Path) -> list[tuple[str, str]]:
    """Each string a ChordPro PDF draws, as (font BaseFont, text), in drawing order."""
    return [(font, text) for font, text, _ in pdf_runs(path)[0]]


def pdf_runs(path: Path) -> tuple[list[tuple[str, str, list[int]]], dict[str, bytes]]:
    """What a ChordPro PDF draws: (font BaseFont, text, glyph ids) per string, in drawing
    order, plus each embedded TrueType program by BaseFont.

    Just enough PDF for these tests: Flate streams, simple fonts read as WinAnsi,
    and Type0 fonts (Identity-H, so codes are glyph ids) read through ToUnicode.
    """
    objects = pdf_objects(path.read_bytes())

    def ref(head: bytes, key: bytes) -> int | None:
        m = re.search(rb"/" + key + rb" \[?\s*(\d+) 0 R", head)
        return int(m.group(1)) if m else None

    programs: dict[str, bytes] = {}
    fonts: dict[str, tuple[str, dict[int, str] | None]] = {}
    for head, _ in objects.values():
        if b"/Type /Font" not in head:
            continue
        name = re.search(rb"/Name /(\S+)", head)
        base = re.search(rb"/BaseFont /(\S+)", head)
        if not (name and base):
            continue
        cmap = None
        if to_unicode := re.search(rb"/ToUnicode (\d+) 0 R", head):
            cmap = parse_to_unicode(objects[int(to_unicode.group(1))][1] or b"")
        fonts[name.group(1).decode()] = (base.group(1).decode(), cmap)
        cid = ref(head, b"DescendantFonts")
        desc = ref(objects[cid][0], b"FontDescriptor") if cid else None
        prog = ref(objects[desc][0], b"FontFile2") if desc else None
        if prog is not None:
            programs[base.group(1).decode()] = objects[prog][1] or b""

    shown: list[tuple[str, str, list[int]]] = []
    token = re.compile(
        rb"/([^\s/\[\]()<>]+)\s+[\d.]+\s+Tf"  # font switch
        rb"|\[((?:\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f]*>|[^\]])*)\]\s*TJ"  # string array
        rb"|(\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f]*>)\s*Tj"  # single string
    )
    for _, stream in objects.values():
        if not stream or b" Tf" not in stream:
            continue
        font = ("", None)
        for m in token.finditer(stream):
            if m.group(1):
                font = fonts.get(m.group(1).decode(), ("", None))
                continue
            parts = re.findall(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f]*>", m.group(2) or m.group(3))
            codes = []
            if font[1] is not None:
                for p in parts:
                    raw = bytes.fromhex(p[1:-1].decode()) if p.startswith(b"<") else b""
                    codes += [int.from_bytes(raw[i : i + 2]) for i in range(0, len(raw), 2)]
            shown.append((font[0], "".join(decode(p, font[1]) for p in parts), codes))
    return shown, programs


def glyph_records(font: bytes, gids) -> dict[int, bytes]:
    """The raw glyf records of some glyph ids of a TrueType font program."""
    (count,) = struct.unpack(">H", font[4:6])
    tables = {
        tag: offset
        for tag, _, offset, _ in struct.iter_unpack(">4sIII", font[12 : 12 + 16 * count])
    }
    (long_loca,) = struct.unpack(">h", font[tables[b"head"] + 50 : tables[b"head"] + 52])
    loca, glyf = tables[b"loca"], tables[b"glyf"]

    def at(i: int) -> int:
        if long_loca:
            return struct.unpack(">I", font[loca + 4 * i : loca + 4 * i + 4])[0]
        return 2 * struct.unpack(">H", font[loca + 2 * i : loca + 2 * i + 2])[0]

    return {g: font[glyf + at(g) : glyf + at(g + 1)].rstrip(b"\0") for g in gids}


def pdf_text(path: Path) -> str:
    return "\n".join(text for _, text in pdf_strings(path))


@pytest.mark.chordpro
@real_chordpro
def test_render_real_chordpro_binary(tmp_path):
    cho = write_chordpro(
        fixture("ug_sheet.txt"),
        tmp_path / "sheet.cho",
        title="Synthetic Test Song",
        artist="The Placeholders",
        key="G",
        capo=2,
    )
    pdf = tmp_path / "sheet.pdf"
    printed = tmp_path / "printed.cho"  # the PDF's own text, whose {subtitle} the style prints
    printed.write_text(printed_text(cho.read_text(encoding="utf-8"), key=Key(7, "ionian"), capo=None), encoding="utf-8")
    render_pdf(printed, pdf, chordpro_bin=CHORDPRO)
    assert pdf.read_bytes().startswith(b"%PDF")
    text = pdf_text(pdf)
    for shown in [
        "Synthetic Test Song",
        "The Placeholders · Key G",
        "VERSE 1",
        "Tiny test",
    ]:
        assert shown in text
    assert "e|-----0---0---|" in text
    strings = pdf_strings(pdf)
    assert ("Helvetica-Bold", "Synthetic Test Song") in strings
    assert any(font == "Helvetica" and "Tiny test" in shown for font, shown in strings)
    assert {"G", "D", "Em", "C", "G/B", "Am", "F"} <= {s.strip() for f, s in strings if f == "Helvetica-Bold"}
    assert b"0.705882 0.266667 0.117647 rg" in b"".join(_streams(pdf))  # the chords' colour, #b4441e
    assert b"0.937255 0.92549 0.901961 rg" not in b"".join(_streams(pdf))  # no box behind "VERSE 1": #efece6


@pytest.mark.chordpro
@real_chordpro
def test_render_real_prints_the_tuning_under_the_title_in_place_of_key_and_capo(tmp_path):
    # A sheet's PDF text says its key line and the tuning its notes name in {subtitle}
    # (pdf_text.py), which the style prints; a song a half step down never reads as in standard tuning.
    sheet = ("{title: Tuned}\n{artist: The Placeholders}\n{key: Em}\n{capo: 2}\n"
             "Tuning: Eb Ab Db Gb Bb Eb (half step down)\n\n{comment: Verse}\n[Em]Tiny test\n")
    cho = tmp_path / "sheet.cho"
    cho.write_text(printed_text(sheet, key=Key(4, "aeolian"), capo=2), encoding="utf-8")
    pdf = tmp_path / "sheet.pdf"
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO)
    text = pdf_text(pdf)
    assert "The Placeholders · Em shapes · capo 2 · sounds F#m · half step down" in text
    assert "Key Em" not in text and "Tuning" not in text and "VERSE" in text


def _streams(path: Path) -> list[bytes]:
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", path.read_bytes(), re.DOTALL):
        try:
            out.append(zlib.decompressobj().decompress(m.group(1)))
        except zlib.error:
            continue
    return out


@pytest.mark.chordpro
@real_chordpro
def test_render_real_draws_the_chords_and_key_of_a_version(tmp_path):
    # Moved by the viewer's own rules (apply_version), not by chordpro, which transposes nothing now.
    from caracole.viewer.page import viewer_key
    from caracole.viewer.version import Version, apply_version, played_key

    cho = write_chordpro(
        "[ch]C#m7[/ch]     [ch]A[/ch]\nSome words to sing",
        tmp_path / "sheet.cho",
        title="T",
        artist="A",
        key="E",
    )
    sheet, down = cho.read_text(encoding="utf-8"), Version(t=-2)
    shapes = viewer_key(sheet)
    played, capo = played_key(down, shapes, None)
    cho.write_text(printed_text(apply_version(sheet, down, key=shapes, capo_sheet=None), key=played, capo=capo),
                   encoding="utf-8")
    pdf = tmp_path / "sheet.pdf"
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO)
    text = pdf_text(pdf)
    assert "Bm7" in text and "G" in text and "A · Key D" in text
    assert "C#m7" not in text


@pytest.mark.chordpro
@real_chordpro
def test_render_real_shows_escaped_text_as_written(tmp_path):
    bs = "\\"
    markup = "\n".join(
        [
            "Sing it again [x2]",
            "#1 in my heart",
            "{softly}",
            "Worth 100%{title} of it",
            "Hold <b>this</b> note",
            f"Ends with {bs}",
            "Next line",
        ]
    )
    cho = write_chordpro(markup, tmp_path / "sheet.cho", title="Escapes", artist="A")
    pdf = tmp_path / "sheet.pdf"
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO)
    lines = [text.strip() for _, text in pdf_strings(pdf)]
    for shown in [
        "Sing it again (x2)",
        "#1 in my heart",
        "(softly)",
        "Worth 100%(title) of it",
        "Hold ‹b>this‹/b> note",
        f"Ends with {bs}",
        "Next line",
    ]:
        assert shown in lines


@pytest.mark.chordpro
@real_chordpro
def test_render_real_ignores_sheet_json_beside_the_sheet(tmp_path):
    cho = write_chordpro("[ch]G[/ch]\nHello", tmp_path / "sheet.cho", title="T", artist="A")
    (tmp_path / "sheet.json").write_text('not a ChordPro config {"tab": {}}', encoding="utf-8")
    render_pdf(cho, tmp_path / "sheet.pdf", chordpro_bin=CHORDPRO)
    assert (tmp_path / "sheet.pdf").read_bytes().startswith(b"%PDF")


@pytest.mark.chordpro
@real_chordpro
def test_render_real_failure_carries_stderr(tmp_path):
    with pytest.raises(RenderError) as err:
        render_pdf(tmp_path / "missing.cho", tmp_path / "sheet.pdf", chordpro_bin=CHORDPRO)
    assert "No such file or directory" in err.value.stderr


@pytest.mark.chordpro
@real_chordpro
@cjk_font
def test_render_real_chinese_sheet_with_cjk_font(tmp_path):
    cho = write_chordpro(
        fixture("zh_sheet.txt"), tmp_path / "sheet.cho", title="斑马斑马", artist="宋冬野"
    )
    cho.write_text(printed_text(cho.read_text(encoding="utf-8"), key=None, capo=None), encoding="utf-8")
    pdf = tmp_path / "sheet.pdf"
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO, font_file=Path(CJK_FONT))
    runs, programs = pdf_runs(pdf)
    # PDF::API2 maps a glyph the font shares between a Kangxi radical and an
    # ideograph to the radical (一 comes out as U+2F00); NFKC maps it back.
    shown = [(font, unicodedata.normalize("NFKC", text)) for font, text, _ in runs]
    for phrase in [
        "斑马斑马",
        "宋冬野",
        "这是一个",
        "合成的例子",
        "测试歌词第二",
        "和弦",
        "只为检查",
        "对齐",
    ]:
        fonts = {font for font, text in shown if phrase in text}
        assert fonts, f"{phrase} is not drawn"
        assert not fonts & CORE_FONTS
    # The glyphs must be the font's own: text extraction alone would pass a PDF
    # whose embedded subset is corrupt, which viewers show with glyphs missing.
    (embedded,) = {font for font, _, codes in runs if codes and font in programs}
    gids = {g for font, _, codes in runs if font == embedded for g in codes}
    assert glyph_records(programs[embedded], gids) == glyph_records(
        Path(CJK_FONT).read_bytes(), gids
    )


adwaita = pytest.mark.skipif(PDF_FONTS is None, reason="set CARACOLE_PDF_FONTS to nix/pdf-fonts.nix's folder")


def adwaita_file(base: str) -> Path:
    """The file of CARACOLE_PDF_FONTS's folder a PDF's font named ``base`` (its BaseFont) was embedded from."""
    fonts = in_folder(PDF_FONTS)
    if base.startswith("AdwaitaMono"):
        return fonts.mono
    return fonts.bold if "Bold" in base else fonts.italic if "Italic" in base else fonts.regular


@pytest.mark.chordpro
@real_chordpro
@adwaita
def test_render_real_sets_the_sheet_in_adwaita_sans_and_its_tab_in_adwaita_mono(tmp_path):
    fonts = in_folder(PDF_FONTS)
    markup = fixture("ug_sheet.txt").replace("Tiny test", "Tiny test, don’t stop ʼ señorita")
    cho = write_chordpro(markup, tmp_path / "sheet.cho", title="Synthetic Test Song", artist="The Placeholders",
                         key="G", capo=2)
    printed = tmp_path / "printed.cho"
    printed.write_text(printed_text(cho.read_text(encoding="utf-8"), key=Key(7, "ionian"), capo=None, fonts=fonts),
                       encoding="utf-8")
    pdf = tmp_path / "sheet.pdf"
    render_pdf(printed, pdf, chordpro_bin=CHORDPRO, fonts=fonts)
    runs, programs = pdf_runs(pdf)

    def font_of(shown: str) -> set[str]:
        return {font for font, text, _ in runs if shown in text}

    assert {font for font, _, _ in runs} <= set(programs)  # every string in a font embedded, none built in
    # Adwaita's, and ChordPro's own symbols, which number the fingers in the diagrams' dots whatever the fonts
    programs.pop("MusicalSymbolsForChordPro", None)
    assert programs and all(base.startswith(("AdwaitaSans", "AdwaitaMono")) for base in programs), list(programs)
    (title,) = font_of("Synthetic Test Song")
    assert title.startswith("AdwaitaSans") and "Bold" in title
    (words,) = font_of("señorita")
    assert words.startswith("AdwaitaSans") and "Bold" not in words and "Italic" not in words
    # No letter lost. Adwaita draws ’ and ʼ with one glyph, which the PDF's text names by one of the two.
    assert re.search("don[’ʼ]t stop [’ʼ] señorita", pdf_text(pdf))
    assert {"G", "D", "Em", "C", "G/B", "Am", "F"} <= {text.strip() for font, text, _ in runs if font == title}
    (repeat,) = font_of("x2")
    assert "Italic" in repeat
    assert font_of("e|-----0---0---|") == {next(base for base in programs if base.startswith("AdwaitaMono"))}
    # The glyphs drawn are the fonts' own: a subset of a font with odd-length glyph records would be corrupt.
    for base, program in programs.items():
        gids = {g for font, _, codes in runs if font == base for g in codes}
        assert gids and glyph_records(program, gids) == glyph_records(adwaita_file(base).read_bytes(), gids), base


@pytest.mark.chordpro
@real_chordpro
def test_chinese_glyphs_lost_with_core_fonts(tmp_path):
    """Why font_file exists: ChordPro's default PDF core fonts have no CJK glyphs."""
    cho = write_chordpro(
        fixture("zh_sheet.txt"), tmp_path / "sheet.cho", title="斑马斑马", artist="宋冬野"
    )
    pdf = tmp_path / "sheet.pdf"
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO)
    text = pdf_text(pdf)
    assert "这是一个" not in text and "斑马" not in text


@pytest.mark.chordpro
@real_chordpro
def test_render_real_paths_with_chinese_names(tmp_path):
    song = tmp_path / "宋冬野" / "斑马斑马"
    cho = write_chordpro("[ch]G[/ch]\nHello", song / "sheet.cho", title="斑马斑马", artist="宋冬野")
    render_pdf(cho, song / "sheet.pdf", chordpro_bin=CHORDPRO)
    assert sorted(p.name for p in song.iterdir()) == ["sheet.cho", "sheet.pdf"]


# The theory edition's chord names, printed by the real chordpro: a chord and its numeral, or the numerals alone.
NUMBERED = ("{title: Numbered}\n{artist: The Placeholders}\n{key: C}\n\n{comment: Verse}\n"
            "[C]Words [Am]to [F]sing [G]here\n[D]more [G]words [D]and [C]home\n")


def numbered_pdf(tmp_path: Path, names: str, sheet: str = NUMBERED) -> list[tuple[str, str]]:
    cho = tmp_path / f"{names}.cho"
    cho.write_text(printed_text(sheet, key=Key(0, "ionian"), capo=None, names=names), encoding="utf-8")
    pdf = tmp_path / f"{names}.pdf"
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO)
    return pdf_strings(pdf)


@pytest.mark.chordpro
@real_chordpro
def test_render_real_prints_each_chord_with_its_numeral_and_draws_its_diagram(tmp_path):
    drawn = numbered_pdf(tmp_path, "both")
    texts = [text.strip() for _, text in drawn]
    for shown in ("C · I", "Am · vi", "D · V/V", "D · II"):
        assert texts.count(shown) >= 2, (shown, texts)  # over the words, and over its diagram
    assert "Words" in texts and "THE NUMERALS, IN C MAJOR" in texts
    assert any(t.startswith("The Placeholders · Key C · numerals in C major") for t in texts)


@pytest.mark.chordpro
@real_chordpro
def test_render_real_numerals_chart_says_its_key_and_draws_no_diagrams(tmp_path):
    plain = numbered_pdf(tmp_path, "chords")
    chart = numbered_pdf(tmp_path, "numerals")
    texts = [text.strip() for _, text in chart]
    for numeral in ("I", "vi", "IV", "V", "V/V", "II"):  # in the chords' style
        assert ("Helvetica-Bold", numeral) in [(font, text.strip()) for font, text in chart], (numeral, chart)
    assert not {"C", "Am", "F", "G", "D"} & set(texts)  # no chord, over the words or as a diagram's name
    assert any(t.startswith("The Placeholders · Key C · numerals in C major") for t in texts)
    # The same song by its chords names each chord over its words and over its diagram: the chart, neither.
    named = [text.strip() for _, text in plain]
    assert all(named.count(chord) >= 2 for chord in ("C", "Am", "F", "G")), named


@pytest.mark.chordpro
@real_chordpro
def test_render_real_numerals_chart_draws_not_even_the_diagram_of_a_chord_the_sheet_defines(tmp_path):
    # Hm is no chord caracole reads: it stays as written, with the sheet's own {define}, which chordpro
    # would draw as a diagram named Hm but for the chart's {diagrams: off}.
    sheet = NUMBERED.replace("{key: C}\n", "{key: C}\n{define: Hm base-fret 1 frets x 2 4 4 3 2}\n").replace(
        "[G]here", "[Hm]here")
    texts = [text.strip() for _, text in numbered_pdf(tmp_path, "numerals", sheet)]
    assert texts.count("Hm") == 1, texts  # over its words alone


# --- two columns that end level (pdf_text.py's estimate, against the real chordpro) ---------------

def drawn_at(tmp_path: Path, text: str, *, font: str | None = None, fonts=None) -> list[list[tuple[float, float, str]]]:
    """What chordpro draws of the ChordPro ``text``, page by page: (x, y, string), in the PDF fonts ``fonts``
    (None: the built-in ones), the CJK ``font`` taking the words from them."""
    cho = tmp_path / "estimate.cho"
    cho.write_text(text, encoding="utf-8")
    pdf = tmp_path / "estimate.pdf"
    render_pdf(cho, pdf, chordpro_bin=CHORDPRO, font_file=Path(font) if font else None, fonts=fonts)
    return pdf_pages(pdf)


@pytest.fixture(scope="module", params=["built-in", "adwaita"])
def pdf_fonts(request):
    """The fonts the estimates are checked in: ChordPro's built-in ones (None), and Adwaita's
    (CARACOLE_PDF_FONTS, skipped without it), whose letters are wider and wrap sooner."""
    if request.param == "built-in":
        return None
    if PDF_FONTS is None:
        pytest.skip("set CARACOLE_PDF_FONTS to nix/pdf-fonts.nix's folder")
    return in_folder(PDF_FONTS)


_WORDS = " ".join(["placeholder"] * 12)
# Each kind of line, by name.
_KINDS = {
    "chords-over-words": "[C]A chord [G]over words\n",
    "words": "Words alone\n",
    "chords": "[C] [G] [Am]\n",
    "repeat-mark": "[*x2]\n",
    "blank": "\n",
    "blanks": "\n\n\n",
    "heading": "{comment: VERSE 1}\n",
    "highlight": "{highlight: CHORUS}\n",
    "tab": "{start_of_tab}\ne|---0---|\n\nB|---1---|\n{end_of_tab}\n",
    "silent": "# a ChordPro comment\n{define: C base-fret 1 frets x 3 2 0 1 0}\n",
    "wrapped-words": _WORDS + "\n",
    "wrapped-chords-and-words": "[C]" + _WORDS + " [G]more\n",
    "words-pushed-to-a-line-of-their-own": "y en la cara dos so[C]les que [G]sin palabras [Am]hablan, [C]  [G]   [Am]\n",
    "a-chord-too-wide-for-where-its-words-start": "[C]placeholder placeholder placeholder placehold[Am7]s\n",
    "wrapped-heading": "{comment: " + _WORDS + " " + _WORDS + "}\n",
    # Its rest fits a column, but not past the indent a wrapped line's next part starts at.
    "a-wrapped-rest-the-indent-pushes-onto-a-third-line": "[C]" + " ".join(["placeholder"] * 7) + " placeholdera\n",
    # The theory edition's "D · V/V": chordpro places a chord by the name it displays, wider than its own.
    "a-displayed-chord-too-wide-for-where-its-words-start":
        '{define: Q base-fret 1 frets x 0 2 0 1 0 display "Am7 · vi7 of V/V"}\n'
        "[C]placeholder placeholder placeholder placehold[Q]s\n",
    "comment-italic": "{comment_italic: VERSE 1}\n",  # in chordpro's own 12 pt, which the style leaves
    "comment-box": "{comment_box: VERSE 1}\n",
    "chorus-recalled": "{chorus}\n",  # a heading, "Chorus"
    "chorus-recalled-by-its-label": "{chorus: Again}\n",
}
# One PDF holds them all, each between a line of its own before it ("ZZZ 3") and one after it
# ("YYY 3"), half of them in each column.
_KINDS_TEXT = "{title: Estimate}\n{subtitle: The Placeholders}\n{columns: 2}\n" + "".join(
    f"ZZZ {n}\n{lines}YYY {n}\n" + ("{column_break}\n" if n == len(_KINDS) // 2 else "")
    for n, lines in enumerate(_KINDS.values()))


@pytest.fixture(scope="module")
def kinds_drawn(tmp_path_factory, pdf_fonts):
    """Where chordpro draws each "ZZZ n" and "YYY n" line of _KINDS_TEXT, by its text, on one page."""
    pages = drawn_at(tmp_path_factory.mktemp("kinds"), _KINDS_TEXT, fonts=pdf_fonts)
    assert len(pages) == 1
    return {s.strip(): (x, y) for x, y, s in pages[0] if s.startswith(("ZZZ", "YYY"))}


@pytest.mark.chordpro
@real_chordpro
@pytest.mark.parametrize("kind", list(_KINDS))
def test_the_estimate_of_a_lines_height_is_chordpros(kinds_drawn, pdf_fonts, kind):
    from caracole.pdf_text import layout, line_heights

    shape, n = layout(pdf_fonts), list(_KINDS).index(kind)
    lines = _KINDS_TEXT.splitlines()
    estimate = sum(line_heights(lines, shape)[lines.index(f"ZZZ {n}") + 1:lines.index(f"YYY {n}")])
    (x, top), (x_after, bottom) = kinds_drawn[f"ZZZ {n}"], kinds_drawn[f"YYY {n}"]
    assert x == x_after  # in one column
    assert estimate == pytest.approx(top - bottom - shape.lyrics, abs=0.01)


@pytest.mark.chordpro
@real_chordpro
@pytest.mark.parametrize(("chords", "header"), [
    (["C", "G"], ""),
    (["C", "D", "E", "F", "G", "A", "B", "Am", "Dm", "Em"], ""),
    (["C", "D", "E", "F", "G", "A", "B", "Am", "Dm", "Em"], "{diagrams: off}\n"),  # a numerals chart
], ids=["a row of diagrams", "two rows", "no diagrams"])
def test_the_estimate_of_the_first_pages_column_is_chordpros(tmp_path, pdf_fonts, chords, header):
    from caracole.pdf_text import column_height, layout, line_heights

    lines = [f"[{chords[i % len(chords)]}]Line {i:02d}" for i in range(60)]
    text = "{title: Estimate}\n" + header + "{columns: 2}\n" + "\n".join(lines) + "\n"
    shape = layout(pdf_fonts)
    room, held = column_height(text.splitlines(), shape), 0
    for height in line_heights(lines, shape):
        if room < height:
            break
        room, held = room - height, held + 1
    first = drawn_at(tmp_path, text, fonts=pdf_fonts)[0]
    assert sorted(s for x, y, s in first if s.startswith("Line") and x < shape.second_column) == [
        f"Line {i:02d}" for i in range(held)]


def level_song(lyric: str = "Made up words to sing") -> str:
    """宋冬野's 斑马斑马 in shape (synthetic words): chordpro filled the first column and left one line
    alone in the second."""
    out = ["{title: Level}", "{artist: The Placeholders}"]
    for n, count in enumerate([4, 4, 4, 8, 5], 1):
        out += ["", f"{{comment: Part {n}}}"]
        out += [f"[C]{lyric} [D]{n}.{i} [Bm]and [Em]more" for i in range(count)]
    return "\n".join(out) + "\n"


def columns_of(page, shape, mark: str) -> tuple[list[str], list[str]]:
    lines = [(x, y, s) for x, y, s in page if mark in s]
    return ([s for x, y, s in lines if x < shape.second_column], [s for x, y, s in lines if x >= shape.second_column])


@pytest.mark.chordpro
@real_chordpro
def test_a_mid_length_songs_two_columns_each_hold_a_fair_share(tmp_path, pdf_fonts):
    from caracole.pdf_text import layout

    pages = drawn_at(tmp_path, printed_text(level_song(), key=Key(0, "ionian"), capo=None, fonts=pdf_fonts),
                     fonts=pdf_fonts)
    left, right = columns_of(pages[0], layout(pdf_fonts), "Made up words")
    assert len(pages) == 1 and len(left) + len(right) == 25
    assert min(len(left), len(right)) >= 10, (left, right)  # chordpro alone: 24 and 1
    second = [s for x, y, s in sorted(pages[0], key=lambda r: -r[1]) if x >= layout(pdf_fonts).second_column]
    assert second[0] == "PART 4"  # a section starts the second column


@pytest.mark.chordpro
@real_chordpro
@cjk_font
def test_a_mid_length_chinese_songs_two_columns_each_hold_a_fair_share(tmp_path, pdf_fonts):
    from caracole.pdf_text import layout

    printed = printed_text(level_song("斑马斑马你不要睡着啦"), key=Key(4, "aeolian"), capo=None, fonts=pdf_fonts)
    pages = drawn_at(tmp_path, printed, font=CJK_FONT, fonts=pdf_fonts)
    left, right = columns_of(pages[0], layout(pdf_fonts), "斑马")
    assert len(pages) == 1 and len(left) + len(right) == 25
    assert min(len(left), len(right)) >= 10, (left, right)


@pytest.mark.chordpro
@real_chordpro
@pytest.mark.parametrize("names", ["both", "numerals"])
def test_a_numbered_songs_two_columns_each_hold_a_fair_share_its_legend_too(tmp_path, pdf_fonts, names):
    # "D · V/V" over the words and the diagrams, or the numerals with none, and a legend after the song.
    from caracole.pdf_text import layout

    pages = drawn_at(tmp_path, printed_text(level_song(), key=Key(0, "ionian"), capo=None, names=names,
                                            fonts=pdf_fonts), fonts=pdf_fonts)
    left, right = columns_of(pages[0], layout(pdf_fonts), "Made up words")
    assert len(pages) == 1 and len(left) + len(right) == 25
    assert min(len(left), len(right)) >= 10, (left, right)
    assert "THE NUMERALS, IN C MAJOR" in [s.strip() for x, y, s in pages[0]]
