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

from caracole.pdf_text import pdf_text as printed_text
from caracole.render import STYLE_FILE, RenderError, needs_font_file, render_pdf, write_chordpro
from caracole.viewer.theory import Key

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
    render_pdf(cho, pdf, transpose=-2, chordpro_bin="/opt/chordpro/bin/chordpro", runner=run)
    assert run.cmd[0] == "/opt/chordpro/bin/chordpro"
    assert "--transpose=-2" in run.cmd
    assert f"--output={pdf}" in run.cmd
    assert run.cmd[-1] == str(cho)
    assert pdf.exists()


def test_no_transpose_option_at_zero(cho, tmp_path):
    run = FakeRunner()
    render_pdf(cho, tmp_path / "sheet.pdf", runner=run)
    assert not any(a.startswith("--transpose") for a in run.cmd)


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
    assert pdf["fonts"]["comment"] == {"name": "Helvetica-Bold", "size": 9, "color": "#b4441e"}  # no background
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
    secret = tmp_path / "spotify_token.json"
    secret.write_text('{"refresh_token": "secret"}', encoding="utf-8")
    cho = tmp_path / "sheet.cho"
    if planted == "link":
        cho.symlink_to(secret)
    else:
        os.mkfifo(cho)
    problem = "symbolic link" if planted == "link" else "not a regular file"
    with pytest.raises(RenderError, match=problem):
        write_chordpro("[ch]G[/ch]\nHello", cho, title="T", artist="A")
    assert secret.read_text(encoding="utf-8") == '{"refresh_token": "secret"}'


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
    data = path.read_bytes()
    objects: dict[int, tuple[bytes, bytes | None]] = {}
    for m in re.finditer(rb"(\d+) 0 obj(.*?)endobj", data, re.DOTALL):
        head, _, rest = m.group(2).partition(b"stream")
        stream = None
        if rest:
            stream = rest.lstrip(b"\r\n").rpartition(b"endstream")[0]
            if b"/FlateDecode" in head:
                stream = zlib.decompress(stream)
        objects[int(m.group(1))] = (head, stream)

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
            cmap = _parse_cmap(objects[int(to_unicode.group(1))][1] or b"")
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
            shown.append((font[0], "".join(_decode(p, font[1]) for p in parts), codes))
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


def _parse_cmap(text: bytes) -> dict[int, str]:
    cmap: dict[int, str] = {}
    for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", text):
        for i, code in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
            cmap[code] = chr(int(dst, 16) + i)
    return cmap


def _decode(part: bytes, cmap: dict[int, str] | None) -> str:
    if part.startswith(b"<"):
        raw = bytes.fromhex(part[1:-1].decode())
        if cmap is not None:
            return "".join(
                cmap.get(int.from_bytes(raw[i : i + 2]), "") for i in range(0, len(raw), 2)
            )
        return raw.decode("cp1252", "replace")
    escapes = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}

    def unescape(m: re.Match) -> bytes:
        code = m.group(1)
        return bytes([int(code, 8) & 0xFF]) if code[:1].isdigit() else escapes.get(code, code)

    return re.sub(rb"\\([0-7]{1,3}|.)", unescape, part[1:-1], flags=re.DOTALL).decode(
        "cp1252", "replace"
    )


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
def test_render_real_transposes_chords_and_key(tmp_path):
    cho = write_chordpro(
        "[ch]C#m7[/ch]     [ch]A[/ch]\nSome words to sing",
        tmp_path / "sheet.cho",
        title="T",
        artist="A",
        key="E",
    )
    cho.write_text(printed_text(cho.read_text(encoding="utf-8"), key=Key(2, "ionian"), capo=None), encoding="utf-8")
    pdf = tmp_path / "sheet.pdf"
    render_pdf(cho, pdf, transpose=-2, chordpro_bin=CHORDPRO)
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
