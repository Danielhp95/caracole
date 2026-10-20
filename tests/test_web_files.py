"""caracole/web/files.py: the library's files over HTTP, never through a link, never a private one."""

import os

import pytest

from caracole.web.files import NotServed, read_library_file, read_written_page


@pytest.fixture
def library(tmp_path):
    lib = tmp_path / "lib"
    song = lib / "Soda Stereo" / "De Música Ligera"
    song.mkdir(parents=True)
    (song / "sheet.pdf").write_bytes(b"%PDF-1.7 sheet")
    (song / "lyrics.txt").write_text("letra\n", encoding="utf-8")
    (song / "guitar-1.gp5").write_bytes(b"gp5")
    (song / "info.json").write_text("{}", encoding="utf-8")
    (lib / "_todo.md").write_text("# To do\n", encoding="utf-8")
    return lib


def test_a_kept_file_comes_with_its_type(library):
    data, kind, attachment = read_library_file(library, "Soda Stereo/De Música Ligera/sheet.pdf")
    assert (data, kind, attachment) == (b"%PDF-1.7 sheet", "application/pdf", False)
    assert read_library_file(library, "Soda Stereo/De Música Ligera/lyrics.txt")[1] == "text/plain; charset=utf-8"
    assert read_library_file(library, "_todo.md")[1] == "text/plain; charset=utf-8"
    assert read_library_file(library, "Soda Stereo/De Música Ligera/info.json")[1].startswith("application/json")


def test_guitar_pro_files_are_downloads(library):
    data, kind, attachment = read_library_file(library, "Soda Stereo/De Música Ligera/guitar-1.gp5")
    assert (data, kind, attachment) == (b"gp5", "application/octet-stream", True)


@pytest.mark.parametrize("path", [
    "", "/", "Soda Stereo", "Soda Stereo/De Música Ligera", "../lib/_todo.md", "Soda Stereo/../_todo.md",
    "./_todo.md", "Soda Stereo//De Música Ligera/sheet.pdf", ".stfolder/x.txt", "Soda Stereo/.sheet.pdf.1a2b.tmp",
    "missing.pdf", "index.html", "page.htm", "image.svg", "overrides.toml", "caracole.sqlite", "notes.txt\x00.pdf",
])
def test_anything_else_is_not_served(library, path):
    (library / "index.html").write_text("<script></script>", encoding="utf-8")
    (library / "page.htm").write_text("<script></script>", encoding="utf-8")
    (library / "image.svg").write_text("<svg/>", encoding="utf-8")
    (library / "overrides.toml").write_text("[ignore]\n", encoding="utf-8")
    (library / "caracole.sqlite").write_bytes(b"SQLite format 3")
    with pytest.raises(NotServed):
        read_library_file(library, path)


def test_no_link_is_followed_to_a_file_or_through_a_folder(library, tmp_path):
    private = tmp_path / "state"
    private.mkdir()
    (private / "spotify_token.json").write_text('{"refresh_token": "secret"}', encoding="utf-8")
    (library / "Evil").symlink_to(private, target_is_directory=True)
    (library / "token.json").symlink_to(private / "spotify_token.json")
    for path in ("Evil/spotify_token.json", "token.json"):
        with pytest.raises(NotServed):
            read_library_file(library, path)


def test_a_fifo_is_never_waited_on(library):
    os.mkfifo(library / "trap.txt")
    with pytest.raises(NotServed):
        read_library_file(library, "trap.txt")


def test_caracoles_private_folders_inside_the_library_stay_private(library):
    (library / "state").mkdir()
    (library / "state" / "spotify_token.json").write_text("{}", encoding="utf-8")
    (library / "cache" / "http").mkdir(parents=True)
    (library / "cache" / "http" / "page.txt").write_text("cached", encoding="utf-8")
    hidden = [library / "state", library / "cache"]
    for path in ("state/spotify_token.json", "cache/http/page.txt"):
        with pytest.raises(NotServed):
            read_library_file(library, path, hidden=hidden)
    assert read_library_file(library, "_todo.md", hidden=hidden)[0] == b"# To do\n"


# --- the pages caracole wrote ------------------------------------------------------------------

PAGE = b"<!doctype html><title>Sheet</title><script>/* caracole's own */</script>"
VIEWER = "Soda Stereo/De Música Ligera/sheet.html"


def wrote(page: bytes = PAGE, *, anywhere: bool = False):
    """A lookup that says caracole wrote ``page`` at VIEWER (``anywhere``: at every path), and
    nothing anywhere else; ``asked`` lists the paths it was asked about."""
    import hashlib

    asked = []

    def written(parts):
        asked.append(parts)
        there = anywhere or "/".join(parts) == VIEWER
        return [(hashlib.sha256(page).hexdigest(), len(page))] if there else []

    written.asked = asked
    return written


def test_a_page_caracole_wrote_is_served_while_it_holds_those_bytes(library):
    (library / VIEWER).write_bytes(PAGE)
    lookup = wrote()
    assert read_written_page(library, VIEWER, lookup) == PAGE
    assert lookup.asked == [("Soda Stereo", "De Música Ligera", "sheet.html")]


def test_a_page_caracole_never_wrote_there_is_not_served_nor_opened(library, monkeypatch):
    from caracole.web import files

    (library / "_todo.html").write_bytes(PAGE)  # its bytes, at a path caracole wrote nothing at
    os.mkfifo(library / "Soda Stereo" / "trap.html")  # opened, it would hold the server up
    opened = []
    monkeypatch.setattr(files, "_open", lambda folder, parts: opened.append(parts) or os.open(os.devnull, 0))
    for path in ("_todo.html", "Soda Stereo/trap.html"):
        with pytest.raises(NotServed):
            read_written_page(library, path, wrote())
    assert opened == []  # the record is asked first, and says nothing was written there


@pytest.mark.parametrize("edited", [
    PAGE + b"<script>fetch('/caracole.sqlite')</script>",  # longer
    PAGE.replace(b"own", b"OWN"),  # the same length
    b"",  # emptied on a synced device
])
def test_an_edited_page_is_not_served(library, edited):
    (library / VIEWER).write_bytes(edited)
    with pytest.raises(NotServed):
        read_written_page(library, VIEWER, wrote())


def test_a_page_is_never_read_through_a_link(library, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "De Música Ligera").mkdir(parents=True)
    (elsewhere / "De Música Ligera" / "sheet.html").write_bytes(PAGE)  # even with the very bytes
    (library / VIEWER).symlink_to(elsewhere / "De Música Ligera" / "sheet.html")
    with pytest.raises(NotServed):
        read_written_page(library, VIEWER, wrote())
    (library / VIEWER).unlink()
    (library / "Soda Stereo" / "De Música Ligera").rename(library / "Soda Stereo" / "moved")
    (library / "Soda Stereo" / "De Música Ligera").symlink_to(elsewhere / "De Música Ligera")
    with pytest.raises(NotServed):
        read_written_page(library, VIEWER, wrote())


def test_a_fifo_in_a_pages_place_is_never_waited_on(library):
    os.mkfifo(library / VIEWER)
    with pytest.raises(NotServed):
        read_written_page(library, VIEWER, wrote())


@pytest.mark.parametrize("path", [
    "../lib/" + VIEWER, "Soda Stereo/../Soda Stereo/De Música Ligera/sheet.html", "./" + VIEWER,
    "Soda Stereo//De Música Ligera/sheet.html", "Soda Stereo/De Música Ligera/.sheet.html.1a2b.tmp", "",
])
def test_a_pages_path_is_checked_as_any_files_is(library, path):
    (library / VIEWER).write_bytes(PAGE)
    (library / "Soda Stereo" / "De Música Ligera" / ".sheet.html.1a2b.tmp").write_bytes(PAGE)
    lookup = wrote(anywhere=True)
    with pytest.raises(NotServed):
        read_written_page(library, path, lookup)
    assert lookup.asked == []


def test_a_page_in_caracoles_private_folders_is_not_served(library):
    (library / VIEWER).write_bytes(PAGE)
    with pytest.raises(NotServed):
        read_written_page(library, VIEWER, wrote(anywhere=True), hidden=[library / "Soda Stereo"])


def test_a_page_too_large_is_not_served(library, monkeypatch):
    from caracole.web import files

    (library / VIEWER).write_bytes(PAGE)
    monkeypatch.setattr(files, "MAX_BYTES", len(PAGE) - 1)
    with pytest.raises(NotServed):
        read_written_page(library, VIEWER, wrote())


def test_a_record_kept_as_lists_serves_the_page_and_an_odd_one_none(library):
    # A kind's lookup may give its records as JSON gives them, as lists: they count all the same.
    import hashlib

    (library / VIEWER).write_bytes(PAGE)
    sha = hashlib.sha256(PAGE).hexdigest()
    assert read_written_page(library, VIEWER, lambda parts: [[sha, len(PAGE)]]) == PAGE
    for odd in ([None], [[sha]], [[sha, str(len(PAGE))]], [[sha, len(PAGE), "x"]], [{"sha256": sha}],
                [[sha, True]], [[None, len(PAGE)]]):
        with pytest.raises(NotServed):
            read_written_page(library, VIEWER, lambda parts, odd=odd: odd)


def test_a_page_that_cant_be_read_is_not_served(library, monkeypatch):
    # A disk error reading the page is the page's, not the database's: the server answers 404 for it.
    import errno

    from caracole.web import files

    (library / VIEWER).write_bytes(PAGE)

    def fails(fd):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(files.os, "fstat", fails)
    with pytest.raises(NotServed):
        read_written_page(library, VIEWER, wrote())
