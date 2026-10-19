from tabarr.coverage import coverage, lyric_lines, normalize_line, sheet_lyric_text

LYRICS = """Walking down the empty road tonight
Counting every light along the way

Walking down the empty road tonight
I keep on singing till the break of day
Nothing else will ever feel the same
"""

FULL_SHEET = """[Verse 1]
[tab][ch]G[/ch]          [ch]D[/ch]
Walking down the empty road tonight[/tab]
[tab][ch]Em[/ch]            [ch]C[/ch]
Counting every light along the way[/tab]

[Chorus]
[ch]G[/ch]   [ch]D[/ch]
I keep on singing till the break of day
[ch]Em[/ch]        [ch]C[/ch]
Nothing else will ever feel the same
"""

FIRST_VERSE_ONLY = """[Verse 1]
[ch]G[/ch]          [ch]D[/ch]
Walking down the empty road tonight
[ch]Em[/ch]            [ch]C[/ch]
Counting every light along the way
(repeat chords for the rest)
"""

CHORDS_ONLY = """[Intro]
[ch]G[/ch] [ch]D[/ch] [ch]Em[/ch] [ch]C[/ch]
[tab]e|-----3-----|
B|---0---0---|[/tab]
G D Em C   x4
"""


def test_lyric_lines_dedupes_and_normalizes():
    lines = lyric_lines(LYRICS)
    assert lines == [
        "walking down the empty road tonight",
        "counting every light along the way",
        "i keep on singing till the break of day",
        "nothing else will ever feel the same",
    ]


def test_normalize_line():
    assert normalize_line("¿Dónde estás, corazón?") == "donde estas corazon"
    assert normalize_line("斑马，斑马，你不要睡着啦") == "斑马 斑马 你不要睡着啦"


def test_sheet_lyric_text_drops_chords_tabs_and_headers():
    text = sheet_lyric_text(CHORDS_ONLY)
    assert text.strip() == ""
    text = sheet_lyric_text(FULL_SHEET)
    assert "verse" not in text and "[" not in text
    assert "walking down the empty road tonight" in text


def test_full_sheet_covers_all():
    assert coverage(FULL_SHEET, lyric_lines(LYRICS)) == 1.0


def test_first_verse_only_is_partial():
    assert coverage(FIRST_VERSE_ONLY, lyric_lines(LYRICS)) == 0.5


def test_chords_only_sheet_is_zero():
    assert coverage(CHORDS_ONLY, lyric_lines(LYRICS)) == 0.0


def test_accents_and_punctuation_still_match():
    lines = lyric_lines("Ella durmió al calor de las masas\nY yo desperté queriendo soñarla")
    sheet = "[ch]Bm[/ch]   [ch]G[/ch]\nElla durmio, al calor de las masas\n[ch]D[/ch]\nY yo desperte, queriendo sonarla"
    assert coverage(sheet, lines) == 1.0


def test_cjk_coverage():
    lines = lyric_lines("斑马斑马你不要睡着啦\n再给我看看你受伤的尾巴\n我不想去触碰你伤口的疤")
    sheet = "[ch]C[/ch]      [ch]G[/ch]\n斑马斑马 你不要睡着啦\n[ch]Am[/ch]     [ch]F[/ch]\n再给我看看你受伤的尾巴"
    assert round(coverage(sheet, lines), 2) == 0.67


def test_no_lines_is_none():
    assert coverage(FULL_SHEET, []) is None
    assert coverage(FULL_SHEET, lyric_lines("")) is None


def test_plain_text_chord_names_are_dropped():
    sheet = "G  D/F#  Em  C\nWalking down the empty road tonight\nAm7 Cadd9 Dsus4\n"
    assert sheet_lyric_text(sheet).strip() == "walking down the empty road tonight"


def test_simplified_sheet_covers_traditional_lyrics():
    # LRCLIB's 斑马斑马 lyrics are in Traditional characters (斑馬, 睡著) while sheets use Simplified.
    lines = lyric_lines("斑馬斑馬你不要睡著啦\n再給我看看你受傷的尾巴")
    sheet = "[ch]C[/ch]      [ch]G[/ch]\n斑马斑马 你不要睡着啦\n[ch]Am[/ch]     [ch]F[/ch]\n再给我看看你受伤的尾巴"
    assert coverage(sheet, lines) == 1.0
