from datetime import UTC, datetime

import pytest

from tabarr.sources import SyncStats
from tabarr.wanted import (
    HEADER,
    WantedLine,
    append_wanted,
    find_wanted,
    format_duration,
    format_line,
    parse_duration,
    parse_wanted,
    sync_wanted,
)


def one(text):
    lines, errors = parse_wanted(text)
    assert errors == []
    assert len(lines) == 1
    return lines[0]


# --- parsing --------------------------------------------------------------------------------


def test_worked_example_banma():
    assert one("宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n") == WantedLine(
        artist="宋冬野", title="斑马斑马", album="安和桥北", duration_ms=253000, line_no=1
    )


def test_spanish_line_without_album_or_duration():
    assert one("Soda Stereo - De Música Ligera") == WantedLine(
        artist="Soda Stereo", title="De Música Ligera", album=None, duration_ms=None, line_no=1
    )


def test_english_line_with_album_and_plain_seconds():
    line = one("Oasis - Wonderwall | (What's the Story) Morning Glory? | 258")
    assert (line.artist, line.title) == ("Oasis", "Wonderwall")
    assert line.album == "(What's the Story) Morning Glory?"
    assert line.duration_ms == 258000


def test_album_alone_and_duration_alone():
    assert one("Radiohead - Creep | Pablo Honey").album == "Pablo Honey"
    line = one("Radiohead - Creep | 3:58")
    assert (line.album, line.duration_ms) == (None, 238000)


def test_duration_then_album_is_also_understood():
    line = one("Radiohead - Creep | 3:58 | Pablo Honey")
    assert (line.album, line.duration_ms) == ("Pablo Honey", 238000)


def test_numeric_album_is_read_as_seconds_unless_a_field_follows():
    assert one("Adele - Someone Like You | 21").duration_ms == 21000
    line = one("Adele - Someone Like You | 21 |")
    assert (line.album, line.duration_ms) == ("21", None)
    line = one("Adele - Someone Like You | 21 | 4:45")
    assert (line.album, line.duration_ms) == ("21", 285000)


def test_split_on_first_separator_keeps_dashes_in_the_title():
    line = one("Queen - Bohemian Rhapsody - Remastered 2011")
    assert (line.artist, line.title) == ("Queen", "Bohemian Rhapsody - Remastered 2011")


def test_en_and_em_dash_separators():
    assert one("Soda Stereo – Persiana Americana").artist == "Soda Stereo"
    assert one("Soda Stereo — Persiana Americana").title == "Persiana Americana"


def test_hyphen_inside_a_name_is_not_a_separator():
    line = one("Jay-Z - Run This Town")
    assert (line.artist, line.title) == ("Jay-Z", "Run This Town")


def test_comments_blank_lines_and_line_numbers():
    text = (
        "# songs to learn\n"
        "\n"
        "   # an indented comment\n"
        "Soda Stereo - Persiana Americana   # learn the riff first\n"
        "\t \n"
        "Radiohead - Creep #capo 2\n"
    )
    lines, errors = parse_wanted(text)
    assert errors == []
    assert [(line.line_no, line.artist, line.title) for line in lines] == [
        (4, "Soda Stereo", "Persiana Americana"),
        (6, "Radiohead", "Creep"),
    ]


def test_hash_inside_a_word_is_not_a_comment():
    assert one("Some Band - C# Minor Blues").title == "C# Minor Blues"


def test_escaped_hash_and_pipe():
    line = one(r"John Lennon - \#9 Dream | Walls and Bridges")
    assert (line.title, line.album) == ("#9 Dream", "Walls and Bridges")
    assert one(r"Some Band - Either \| Or").title == "Either | Or"


def test_unescaped_hash_cuts_the_title_and_the_error_says_how_to_escape():
    lines, errors = parse_wanted("Garbage - #1 Crush\n")
    assert lines == []
    assert len(errors) == 1 and errors[0][0] == 1
    assert "\\#" in errors[0][1]


def test_bad_lines_are_reported_and_good_lines_kept():
    text = (
        "Soda Stereo De Música Ligera\n"
        "Oasis - Wonderwall\n"
        "Oasis - Wonderwall | Album | 4:18 | extra\n"
        "Oasis - Wonderwall | 4:75\n"
        "Oasis - Wonderwall | Album | Another Album\n"
        "- Wonderwall\n"
    )
    lines, errors = parse_wanted(text)
    assert [line.line_no for line in lines] == [2]
    assert [n for n, _ in errors] == [1, 3, 4, 5, 6]
    messages = dict(errors)
    assert "Artist - Title" in messages[1] and "Soda Stereo De Música Ligera" in messages[1]
    assert "too many" in messages[3]
    assert "4:75" in messages[4]
    assert "Another Album" in messages[5]


def test_crlf_bom_extra_spaces_and_nbsp():
    text = "\ufeffSoda Stereo  -  De Música   Ligera \r\nOasis\u00a0-\u00a0Wonderwall\r\n"
    lines, errors = parse_wanted(text)
    assert errors == []
    assert [(line.artist, line.title, line.line_no) for line in lines] == [
        ("Soda Stereo", "De Música Ligera", 1),
        ("Oasis", "Wonderwall", 2),
    ]


def test_text_is_nfc_normalized():
    decomposed = "Soda Stereo - De Mu\u0301sica Ligera"
    assert one(decomposed).title == "De Música Ligera"


def test_identity_ignores_cjk_punctuation():
    a = one("宋冬野 - 斑马，斑马")
    b = one("宋冬野 - 斑马斑马")
    assert a.identity == b.identity == "宋冬野/斑马斑马"


# --- durations and formatting --------------------------------------------------------------


@pytest.mark.parametrize(
    "text,ms",
    [
        ("4:13", 253000),
        ("04:13", 253000),
        ("1:02:03", 3723000),
        ("253", 253000),
        (" 4:13 ", 253000),
        ("４：１３", 253000),
    ],
)
def test_parse_duration(text, ms):
    assert parse_duration(text) == ms


@pytest.mark.parametrize("text", ["Pablo Honey", "4.13", "4'13", "", "4:13s"])
def test_parse_duration_returns_none_for_non_durations(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize("text", ["4:75", "4:5", "1:75:00", "0:00", "0"])
def test_parse_duration_rejects_bad_durations(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_format_duration_rounds_to_seconds():
    assert format_duration(253000) == "4:13"
    assert format_duration(253499) == "4:13"
    assert format_duration(253500) == "4:14"
    assert format_duration(3723000) == "1:02:03"


def test_format_line():
    assert (
        format_line("宋冬野", "斑马斑马", "安和桥北", 253000)
        == "宋冬野 - 斑马斑马 | 安和桥北 | 4:13"
    )
    assert format_line("Soda Stereo", "De Música Ligera") == "Soda Stereo - De Música Ligera"
    assert format_line("Radiohead", "Creep", duration_ms=238000) == "Radiohead - Creep | 3:58"


def test_format_line_escapes_what_the_parser_would_eat():
    assert format_line("John Lennon", "#9 Dream") == r"John Lennon - \#9 Dream"
    assert format_line("Some Band", "Either | Or") == r"Some Band - Either \| Or"
    assert format_line("Some Band", "C# Minor Blues") == "Some Band - C# Minor Blues"
    assert format_line("Adele", "Someone Like You", "21") == "Adele - Someone Like You | 21 |"


@pytest.mark.parametrize(
    "artist,title,album,ms",
    [
        ("John Lennon", "#9 Dream", None, None),
        ("Some Band", "Either | Or", "A | B", 61000),
        ("Adele", "Someone Like You", "21", None),
        ("宋冬野", "斑马，斑马", "安和桥北", 253000),
        ("Queen", "Bohemian Rhapsody - Remastered 2011", None, 354000),
    ],
)
def test_format_line_round_trips(artist, title, album, ms):
    line = one(format_line(artist, title, album, ms))
    assert (line.artist, line.title, line.album, line.duration_ms) == (artist, title, album, ms)


# --- appending ------------------------------------------------------------------------------


def test_append_creates_the_file_with_a_header_explaining_the_format(tmp_path):
    path = tmp_path / "Tabs" / "wanted.txt"
    line = append_wanted(path, "宋冬野", "斑马斑马", album="安和桥北", duration_ms=253000)
    text = path.read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert "Artist - Title" in HEADER and "m:ss" in HEADER and "\\#" in HEADER
    assert text.endswith("\n宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n")
    lines, errors = parse_wanted(text)
    assert errors == [] and lines == [line]
    assert line == WantedLine("宋冬野", "斑马斑马", "安和桥北", 253000, text.count("\n"))


def test_append_adds_a_line_at_the_end(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text("# mine\nSoda Stereo - De Música Ligera\n", encoding="utf-8")
    line = append_wanted(path, "Radiohead", "Creep", duration_ms=238000)
    assert path.read_text(encoding="utf-8") == (
        "# mine\nSoda Stereo - De Música Ligera\nRadiohead - Creep | 3:58\n"
    )
    assert line == WantedLine("Radiohead", "Creep", None, 238000, 3)


def test_append_skips_a_song_already_listed(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text(
        "宋冬野 - 斑马，斑马 | 安和桥北\nSoda Stereo - De Música Ligera\n", encoding="utf-8"
    )
    before = path.read_bytes()
    assert append_wanted(path, "宋冬野", "斑马斑马", duration_ms=253000) == WantedLine(
        "宋冬野", "斑马，斑马", "安和桥北", None, 1
    )
    assert append_wanted(path, "Soda Stereo", "De Música Ligera - Remasterizado 2007").line_no == 2
    assert path.read_bytes() == before


def test_append_keeps_crlf_and_adds_a_missing_final_newline(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_bytes("# list\r\nSoda Stereo - De Música Ligera".encode())
    line = append_wanted(path, "Oasis", "Wonderwall")
    assert (
        path.read_bytes()
        == "# list\r\nSoda Stereo - De Música Ligera\r\nOasis - Wonderwall\r\n".encode()
    )
    assert line.line_no == 3


def test_append_to_an_empty_file_adds_no_header(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text("", encoding="utf-8")
    assert append_wanted(path, "Oasis", "Wonderwall").line_no == 1
    assert path.read_text(encoding="utf-8") == "Oasis - Wonderwall\n"


def test_append_escapes_names_so_they_read_back(tmp_path):
    path = tmp_path / "wanted.txt"
    append_wanted(path, "John Lennon", "#9 Dream")
    append_wanted(path, "Adele", "Someone Like You", album="21")
    text = path.read_text(encoding="utf-8")
    assert text.endswith("John Lennon - \\#9 Dream\nAdele - Someone Like You | 21 |\n")
    assert find_wanted(path, "John Lennon", "#9 Dream").title == "#9 Dream"
    assert find_wanted(path, "Adele", "Someone Like You").album == "21"


def test_append_refuses_what_the_file_cant_hold(tmp_path):
    path = tmp_path / "wanted.txt"
    with pytest.raises(ValueError, match="Sergio Mendes"):
        append_wanted(path, "Sergio Mendes - Brasil '66", "Mas Que Nada")
    with pytest.raises(ValueError):
        append_wanted(path, "  ", "Creep")
    with pytest.raises(ValueError):
        append_wanted(path, "Radiohead", "Creep", duration_ms=0)
    assert not path.exists()


def test_find_wanted_by_identity(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text("Oasis - Wonderwall\nRadiohead - Creep\n", encoding="utf-8")
    assert find_wanted(path, "radiohead", "CREEP").line_no == 2
    assert find_wanted(path, "Oasis", "Champagne Supernova") is None
    assert find_wanted(tmp_path / "missing.txt", "Oasis", "Wonderwall") is None


# --- syncing --------------------------------------------------------------------------------

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
LATER = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
CONN = object()


class RecordingUpsert:
    """Records upsert_song calls; a source id seen before is a merge, not a new song."""

    def __init__(self):
        self.calls = []
        self.ids = {}

    def __call__(
        self, conn, *, artists, title, album, duration_ms, isrc, source, source_id, added_at
    ):
        assert conn is CONN
        self.calls.append(
            {
                "artists": list(artists),
                "title": title,
                "album": album,
                "duration_ms": duration_ms,
                "isrc": isrc,
                "source": source,
                "source_id": source_id,
                "added_at": added_at,
            }
        )
        created = source_id not in self.ids
        self.ids.setdefault(source_id, len(self.ids) + 1)
        return self.ids[source_id], created


class FakeKV:
    def __init__(self):
        self.data = {}

    def get(self, conn, key):
        assert conn is CONN
        return self.data.get(key)

    def set(self, conn, key, value):
        assert conn is CONN
        self.data[key] = value


def sync(path, now=NOW, kv=None):
    up, kv = RecordingUpsert(), kv or FakeKV()
    return sync_wanted(CONN, path, now, upsert=up, kv_get=kv.get, kv_set=kv.set), up


def test_sync_upserts_every_song_with_source_wanted(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text(
        "宋冬野 - 斑马斑马 | 安和桥北 | 4:13\nSoda Stereo - De Música Ligera\n", encoding="utf-8"
    )
    stats, up = sync(path)
    assert stats == SyncStats(seen=2, new=2)
    assert up.calls == [
        {
            "artists": ["宋冬野"],
            "title": "斑马斑马",
            "album": "安和桥北",
            "duration_ms": 253000,
            "isrc": None,
            "source": "wanted",
            "source_id": "宋冬野/斑马斑马",
            "added_at": "2026-10-18T03:30:00Z",
        },
        {
            "artists": ["Soda Stereo"],
            "title": "De Música Ligera",
            "album": None,
            "duration_ms": None,
            "isrc": None,
            "source": "wanted",
            "source_id": "soda-stereo/de-musica-ligera",
            "added_at": "2026-10-18T03:30:00Z",
        },
    ]


def test_sync_of_a_missing_file_is_empty(tmp_path):
    stats, up = sync(tmp_path / "wanted.txt")
    assert stats == SyncStats()
    assert up.calls == []


def test_sync_reports_bad_lines_and_never_raises(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text(
        "Oasis - Wonderwall\nno separator here\nRadiohead - Creep | 4:75\n", encoding="utf-8"
    )
    stats, up = sync(path)
    assert [c["title"] for c in up.calls] == ["Wonderwall"]
    assert (stats.seen, stats.new) == (1, 1)
    assert [n for n, _ in stats.line_errors] == [2, 3]
    assert stats.errors[0].startswith("wanted.txt line 2: expected 'Artist - Title'")
    assert stats.errors[1].startswith("wanted.txt line 3: bad duration '4:75'")


def test_sync_counts_the_same_song_twice_as_one(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_text("宋冬野 - 斑马，斑马\n宋冬野 - 斑马斑马 | 安和桥北 | 4:13\n", encoding="utf-8")
    stats, up = sync(path)
    assert (stats.seen, stats.new) == (1, 1)
    # Both lines reach the repository, which merges them: the second one fills in the album.
    assert [(c["source_id"], c["album"]) for c in up.calls] == [
        ("宋冬野/斑马斑马", None),
        ("宋冬野/斑马斑马", "安和桥北"),
    ]


def test_sync_keeps_the_time_a_line_was_first_seen(tmp_path):
    path = tmp_path / "wanted.txt"
    kv = FakeKV()
    path.write_text("宋冬野 - 斑马斑马\n", encoding="utf-8")
    sync(path, NOW, kv)
    path.write_text("宋冬野 - 斑马斑马\nSoda Stereo - De Música Ligera\n", encoding="utf-8")
    _, up = sync(path, LATER, kv)
    assert [(c["source_id"], c["added_at"]) for c in up.calls] == [
        ("宋冬野/斑马斑马", "2026-10-18T03:30:00Z"),
        ("soda-stereo/de-musica-ligera", "2026-10-19T03:30:00Z"),
    ]


def test_sync_reports_a_line_that_is_not_utf8(tmp_path):
    path = tmp_path / "wanted.txt"
    path.write_bytes(b"Soda Stereo - De M\xfasica Ligera\nOasis - Wonderwall\n")
    stats, up = sync(path)
    assert [c["title"] for c in up.calls] == ["Wonderwall"]
    assert stats.line_errors[0][0] == 1 and "UTF-8" in stats.line_errors[0][1]


def test_sync_of_an_unreadable_path_is_an_error_not_a_crash(tmp_path):
    path = tmp_path / "wanted.txt"
    path.mkdir()
    stats, up = sync(path)
    assert up.calls == []
    assert len(stats.errors) == 1 and "wanted.txt" in stats.errors[0]


def test_sync_reads_a_file_written_by_append(tmp_path):
    path = tmp_path / "Tabs" / "wanted.txt"
    append_wanted(path, "宋冬野", "斑马斑马", album="安和桥北", duration_ms=253000)
    stats, up = sync(path)
    assert stats == SyncStats(seen=1, new=1)
    assert up.calls[0]["source_id"] == "宋冬野/斑马斑马"
