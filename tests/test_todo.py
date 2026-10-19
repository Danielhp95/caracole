import re
from datetime import UTC, datetime
from urllib.parse import quote

from caracole.db import kv_set, kv_set_json
from caracole.health import record_block
from caracole.library import keep_file
from caracole.normalize import slug_key
from caracole.overrides import Overrides, load_overrides
from caracole.songs import update_song
from caracole.todo import build_todo, md, search_links, write_todo
from caracole.versions import set_coverage, set_picks, upsert_version

from conftest import add_song

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)


def index(conn, rows):
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen) VALUES (?, ?, ?, ?, '1', 'x')",
        rows,
    )


def version(conn, song, tab_id, *, slot="sheet", kind="chords", rating=4.6, votes=35, ver=2):
    return upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot=slot, kind=kind,
                          rating=rating, votes=votes, version=ver, label=None,
                          url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}", raw={}, now="x")


def todo(conn, cfg, overrides=None):
    return build_todo(conn, cfg, overrides or Overrides(), NOW)


def test_summary_counts(conn, cfg):
    add_song(conn, "A", "One")
    s2 = add_song(conn, "B", "Two")
    s3 = add_song(conn, "C", "Three")
    update_song(conn, s2.id, status="found")
    update_song(conn, s3.id, status="ignored")
    text = todo(conn, cfg)
    assert text.startswith("# caracole to-do")
    assert "3 songs: 1 found, 1 wanted, 1 ignored" in text
    assert "2026-10-18 03:41 UTC" in text


def test_review_item_has_links_and_paste_line(conn, cfg):
    index(conn, [(1081460, "soda-stereo", "persiana-americana", "chords"),
                 (1081462, "soda-stereo", "persiana-americana", "tabs")])
    s = add_song(conn, "Soda", "Persiana Americana - Remasterizado 2007")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": "fuzzy_artist"},
    ])
    text = todo(conn, cfg)
    assert "## Review (1)" in text
    assert "Soda - Persiana Americana" in text
    assert "82" in text
    assert "https://tabs.ultimate-guitar.com/tab/1081460" in text
    assert "https://tabs.ultimate-guitar.com/tab/1081462" in text
    assert '"Soda - Persiana Americana" = "soda-stereo/persiana-americana"  # under [match]' in text
    assert '"Soda" = "soda-stereo"  # under [alias]' in text


def test_a_reviews_heading_is_set_off_from_its_first_candidate(conn, cfg):
    index(conn, [(1, "radiohead", "creep", "chords")])
    s = add_song(conn, "Radio Head", "Crep")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.0, "step": "fuzzy_title"}])
    text = todo(conn, cfg)
    assert "probably covers" not in text
    assert "\n### Radio Head - Crep\n\n- 89 · `radiohead/creep` (fuzzy_title)" in text
    covers_only(conn, "Maná", "Rayando el Sol", "ana-gabriel")  # with a note: one blank line each side
    assert re.search(r"\n### Maná - Rayando el Sol\n\nOnly other artists' [^\n]*\n\n- 100 · ", todo(conn, cfg))


def test_review_links_use_the_slugged_url(conn, cfg):
    conn.execute(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (1081462, 'soda-stereo', 'persiana-americana', 'tabs', '1', 'x', "
        "'soda-stereo/persiana-americana-tabs-1081462')"
    )
    s = add_song(conn, "Soda", "Persiana Americana")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": "fuzzy_artist"},
    ])
    assert "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-tabs-1081462" in todo(conn, cfg)


def test_title_only_candidate_gets_no_alias_line(conn, cfg):
    index(conn, [(5, "jeff-buckley", "hallelujah", "chords")])
    s = add_song(conn, "Someone", "Hallelujah")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "jeff-buckley", "song_key": "hallelujah", "score": 100.0, "step": "title_only"},
    ])
    text = todo(conn, cfg)
    assert '"Someone - Hallelujah" = "jeff-buckley/hallelujah"  # under [match]' in text
    assert "# under [alias]" not in text


def covers_only(conn, artist, title, *covers):
    """A song reviewed on its title alone: its only candidates are other artists' songs (covers)."""
    s = add_song(conn, artist, title)
    song_key = slug_key(title)
    index(conn, [(500 + i, a, song_key, "chords") for i, a in enumerate(covers)])
    update_song(conn, s.id, review=True, match_decision="review", match_step="title_only", match_score=100.0,
                match_artist_key=covers[0], match_song_key=song_key, match_candidates=[
                    {"artist_key": a, "song_key": song_key, "score": 100.0, "step": "title_only"} for a in covers])
    return s


def review_item(text, display):
    return text.split(f"### {display}\n", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]


def test_title_only_review_of_an_artist_ug_lists_by_bare_ids_asks_for_its_artist_page(conn, cfg):
    # UG lists Maná only by bare ids: the index has covers of the title, and nothing of Maná's.
    from caracole.ug.fetch import songs_to_fetch

    s = covers_only(conn, "Maná", "Rayando el Sol", "ana-gabriel", "pablo-alboran")
    text = todo(conn, cfg)
    assert "## Artists to find on Ultimate Guitar (1)" in text
    assert "**Maná** (1 song)" in text
    item = review_item(text, "Maná - Rayando el Sol")
    assert "other artists' songs with this title (probably covers)" in item
    assert "[artist_url]" in item and "Artists to find" in item
    # Once the page is pasted, the next fetch looks for the song there.
    o = Overrides(artist_url={"mana": "https://www.ultimate-guitar.com/artist/mana_1234"})
    assert [x.id for x in songs_to_fetch(conn, o, NOW)] == [s.id]
    text = todo(conn, cfg, o)
    assert "## Artists to find" not in text
    assert "caracole looks for it on Maná's UG page in the next run" in review_item(text, "Maná - Rayando el Sol")


def test_title_only_review_of_an_indexed_artist_says_its_page_is_checked_first(conn, cfg):
    index(conn, [(1, "soda-stereo", "persiana-americana", "chords")])
    s = covers_only(conn, "Soda Stereo", "De Música Ligera", "os-paralamas-do-sucesso", "ana-mena", "pereza")
    text = todo(conn, cfg)
    assert "## Artists to find" not in text
    item = review_item(text, "Soda Stereo - De Música Ligera")
    assert "other artists' songs with this title (probably covers)" in item
    assert "caracole looks for it on Soda Stereo's UG page in the next run" in item
    # The page was read and doesn't list it: say so, and that it is read again.
    kv_set(conn, f"ug:artist_page_checked:{s.id}", "2026-10-18T03:35:00Z")
    item = review_item(todo(conn, cfg), "Soda Stereo - De Música Ligera")
    assert "caracole didn't find it on Soda Stereo's UG page either" in item and "after 30 days" in item
    assert "if none is, dismiss them all (below)" in item and "leave it" not in item


def test_title_only_review_of_a_song_with_a_sheet_says_nothing_is_lost_by_leaving_it(conn, cfg):
    # The live smoke: De Música Ligera had a 100% LaCuerda sheet and still offered three covers to pick.
    index(conn, [(1, "soda-stereo", "persiana-americana", "chords")])
    s = covers_only(conn, "Soda Stereo", "De Música Ligera", "os-paralamas-do-sucesso", "pereza")
    update_song(conn, s.id, status="found")
    item = review_item(todo(conn, cfg), "Soda Stereo - De Música Ligera")
    assert "probably covers" in item and "has a sheet already" in item


def test_a_review_with_a_candidate_by_the_songs_own_artist_gets_no_covers_note(conn, cfg):
    index(conn, [(1, "radiohead", "creep", "chords")])
    s = add_song(conn, "Radio Head", "Crep")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.0, "step": "fuzzy_title"},
        {"artist_key": "stone-temple-pilots", "song_key": "creep", "score": 80.0, "step": "title_only"},
    ])
    assert "probably covers" not in todo(conn, cfg)


def test_partial_sheet_listed_with_percent(conn, cfg):
    s = add_song(conn)
    v = version(conn, s, 85053)
    set_coverage(conn, v, 0.45)
    keep_file(conn, cfg.library_dir, song=s, version_id=v, name="sheet.txt", data=b"x", rank=1)
    text = todo(conn, cfg)
    assert "## Partial sheets (1)" in text
    assert "Soda Stereo - De Música Ligera" in text and "45%" in text
    assert "https://tabs.ultimate-guitar.com/tab/85053" in text


def first_section(text):
    return text.split("\n## ", 1)[1].split("\n## ", 1)[0]


def test_setup_problems_say_the_index_isnt_built_before_anything_else(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.0, "step": "fuzzy_title"}])
    setup = first_section(todo(conn, cfg))
    assert setup.startswith("Setup problems")
    assert "The Ultimate Guitar index isn't built" in setup
    assert "`caracole index build`" in setup and "`sudo caracole-admin index build`" in setup


def test_setup_problems_count_the_wanted_lines_caracole_couldnt_read(conn, cfg):
    from caracole.ug.index import mark_built

    index(conn, [(1, "radiohead", "creep", "chords")])
    mark_built(conn, NOW)
    assert "## Setup problems" not in todo(conn, cfg)
    kv_set_json(conn, "source:wanted", {"at": "2026-10-18T03:30:00Z", "lines": 12, "new": 0,
                                        "errors": [[3, "expected \"Artist - Title\""], [7, "bad duration"]]})
    setup = first_section(todo(conn, cfg))
    assert setup.startswith("Setup problems")
    assert "wanted.txt has 2 lines caracole couldn't read" in setup and "Sources" in setup


def test_a_wanted_file_caracole_cant_read_says_so_rather_than_count_a_bad_line(conn, cfg):
    # The sync stores an error about the whole file, such as a link refused unread, as line 0.
    from caracole.sources import sync_sources
    from caracole.ug.index import mark_built

    index(conn, [(1, "radiohead", "creep", "chords")])
    mark_built(conn, NOW)
    private = cfg.state_dir / "spotify-token.json"
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text("{}", encoding="utf-8")
    cfg.wanted_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.wanted_file.symlink_to(private)
    sync_sources(conn, cfg, NOW, spotify=None)
    text = todo(conn, cfg)
    why = (f"wanted.txt: not read: {cfg.wanted_file} is a symbolic link, which caracole doesn't follow; put the "
           "file itself there")
    setup = first_section(text)
    assert setup.startswith("Setup problems (1)")
    assert ("- **wanted.txt can't be read**, so caracole doesn't see the songs you add to it (those it read "
            f"before are still looked for): `{why}`.") in setup
    assert "couldn't read" not in setup and "line" not in setup
    sources = section_of(text, "Sources")
    assert f"- wanted.txt: error at 2026-10-18T03:41:00Z: {md(why)}" in sources
    assert "line 0" not in sources and "0 songs" not in sources


def test_partial_sheets_say_how_to_choose_another_version(conn, cfg):
    s = add_song(conn)
    v = version(conn, s, 85053)
    set_coverage(conn, v, 0.45)
    keep_file(conn, cfg.library_dir, song=s, version_id=v, name="sheet.txt", data=b"x", rank=1)
    section = section_of(todo(conn, cfg), "Partial sheets")
    assert "pin its page under `[pin]`" in section
    assert '`"Artist - Title" = ["https://tabs.ultimate-guitar.com/tab/…"]`' in section


def test_buy_list_links(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马，斑马", album="安和桥北", duration_ms=253000)
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Buy list (1)" in text
    assert "宋冬野 - 斑马，斑马" in text
    links = search_links("宋冬野", "斑马，斑马")
    for name in ("bandcamp", "qobuz", "itunes", "chordify", "songsterr", "youtube"):
        assert links[name] in text
    assert quote("宋冬野 斑马，斑马 吉他教学") in links["youtube"]
    assert "guitar+lesson" in search_links("Radiohead", "Creep")["youtube"] or "guitar%20lesson" in search_links("Radiohead", "Creep")["youtube"]


def test_buy_list_excludes_found_and_songs_with_audio(conn, cfg):
    s1 = add_song(conn, "A", "Has Audio")
    update_song(conn, s1.id, audio_path="/music/a.flac", match_decision="not_found")
    s2 = add_song(conn, "B", "Found")
    update_song(conn, s2.id, status="found", match_decision="accept")
    assert "## Buy list" not in todo(conn, cfg)


def test_buy_list_waits_while_the_index_is_incomplete(conn, cfg):
    # A build stopped part-way: UG may have sheets for a song marked not found against it.
    from caracole.ug.index import mark_built

    index(conn, [(1001, "oasis", "wonderwall", "chords")])
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Buy list" not in text
    assert "The Ultimate Guitar index is incomplete" in text.split("\n## Review", 1)[0]
    mark_built(conn, NOW)
    text = todo(conn, cfg)
    assert "## Buy list (1)" in text and "index is incomplete" not in text


def test_buy_list_waits_for_a_due_artist_page_check(conn, cfg):
    # You just pasted the artist page: the next fetch looks for the song there before anything is bought.
    s = add_song(conn, "宋冬野", "斑马斑马")
    update_song(conn, s.id, match_decision="not_found")
    o = Overrides(artist_url={"宋冬野": "https://www.ultimate-guitar.com/artist/song_dongye_1234567"})
    text = todo(conn, cfg, o)
    assert "## Buy list" not in text
    assert "1 song waiting for the nightly fetch" in text
    # Once the page has been read for the song (and didn't list it), buying is the next step.
    kv_set(conn, f"ug:artist_page_checked:{s.id}", "2026-10-18T03:35:00Z")
    assert "## Buy list (1)" in todo(conn, cfg, o)


def test_buy_list_waits_for_lacuerda_to_be_asked(conn, cfg):
    s = add_song(conn, "Joaquín Sabina", "Y Nos Dieron las Diez")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Buy list" not in text and "1 song waiting for the nightly fetch" in text
    update_song(conn, s.id, lacuerda_checked_at="2026-10-18T03:36:00Z")  # LaCuerda had none
    text = todo(conn, cfg)
    assert "## Buy list (1)" in text and "No human sheet found yet" in text
    assert "No human sheet exists" not in text


def test_buy_list_waits_for_pending_fetches(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="accept")
    text = todo(conn, cfg)
    assert "## Buy list" not in text
    assert "1 song waiting for the nightly fetch" in text


def test_guitar_pro_pages_to_click(conn, cfg):
    s = add_song(conn)
    v1 = version(conn, s, 555890, slot="guitar", kind="guitar-pro", rating=4.2, votes=5, ver=1)
    v2 = version(conn, s, 555891, slot="guitar", kind="power", rating=4.0, votes=2, ver=1)
    set_picks(conn, s.id, ["guitar-pro", "power"], [v1, v2])
    text = todo(conn, cfg)
    assert "## Guitar Pro pages to click (2)" in text
    assert "https://tabs.ultimate-guitar.com/tab/555890" in text
    assert "_inbox" in text
    # Once a file exists for a pick it's no longer listed.
    keep_file(conn, cfg.library_dir, song=s, version_id=v1, name="guitar-1.gp5", data=b"gp", rank=1)
    keep_file(conn, cfg.library_dir, song=s, version_id=v2, name="guitar-2.ptb", data=b"pt", rank=2)
    assert "## Guitar Pro pages to click" not in todo(conn, cfg)


def test_guitar_parts_not_found(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="accept", ug_checked_at="2026-10-18T03:35:00Z")
    text = todo(conn, cfg)
    assert "## Guitar parts not found (1)" in text
    assert search_links("Radiohead", "Creep")["songsterr"] in text


def test_inbox_unmatched_files_listed(conn, cfg):
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "mystery.gp5").write_bytes(b"x")
    (inbox / ".hidden").write_bytes(b"x")
    text = todo(conn, cfg)
    assert "## Inbox: files caracole couldn't place (1)" in text
    assert "mystery.gp5" in text and ".hidden" not in text


def test_inbox_advice_is_a_name_the_inbox_files_not_a_move_by_hand(conn, cfg):
    # A file moved into a song's folder by hand gets no record: index.html never lists it, and its
    # Guitar Pro page stays on the list to click.
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "Radiohead - Creep live bootleg.gp5").write_bytes(b"x")
    (inbox / "notes.pdf").write_bytes(b"x")
    section = section_of(todo(conn, cfg), "Inbox: files caracole couldn't place")
    assert "move it into the song's folder" not in section
    assert '`Radiohead - Creep live bootleg.gp5`: rename it "Artist - Title (ver N).gp5"' in section
    assert "Guitar Pro pages to click" in section
    assert "`notes.pdf`: not a Guitar Pro or Power Tab file" in section


def test_inbox_lists_a_link_as_refused_never_as_a_file_to_rename(conn, cfg):
    # Anyone who can write to the library can put a link in the inbox; caracole files only regular files.
    private = cfg.state_dir / "spotify-token.json"
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text("{}", encoding="utf-8")
    inbox = cfg.library_dir / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "Soda Stereo - Signos.gp5").symlink_to(private)
    (inbox / "gone.gp5").symlink_to(cfg.state_dir / "nothing")
    (inbox / "a folder").mkdir()
    section = section_of(todo(conn, cfg), "Inbox: files caracole couldn't place")
    refused = ": a symbolic link; caracole files only regular files. Put the file itself there."
    assert section.startswith(" (2)\n")
    assert f"- `Soda Stereo - Signos.gp5`{refused}" in section and f"- `gone.gp5`{refused}" in section
    assert "rename it" not in section and "a folder" not in section


def test_a_linked_inbox_lists_nothing_of_what_it_points_at(conn, cfg):
    # A link in place of _inbox/ would list the folder it points at: the credentials' names, say.
    private = cfg.state_dir / "credentials"
    private.mkdir(parents=True)
    (private / "spotify_client_secret").write_text("x", encoding="utf-8")
    cfg.library_dir.mkdir(parents=True)
    (cfg.library_dir / "_inbox").symlink_to(private)
    text = todo(conn, cfg)
    assert "spotify_client_secret" not in text
    section = section_of(text, "Inbox: files caracole couldn't place")
    assert "- `_inbox` is a symbolic link, so this page doesn't list what it points at. Make `_inbox` a folder " \
           "of its own." in section


def test_missing_lyrics(conn, cfg):
    s = add_song(conn, "宋冬野", "斑马斑马")
    update_song(conn, s.id, lyrics_status="missing")
    assert "## Missing lyrics (1)" in todo(conn, cfg)


def test_find_artist_on_ug(conn, cfg):
    s = add_song(conn, "Joaquín Sabina", "19 Días y 500 Noches")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert "## Artists to find on Ultimate Guitar (1)" in text
    assert '[artist_url]\n"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/…"' in text
    assert "<name>" not in text  # an artist page's address, as your browser shows it, may have no name
    assert "search.php" in text  # a link for you to click; caracole itself never requests search.php
    # Known artist page (override): no longer asked for.
    o = Overrides(artist_url={"joaquin-sabina": "https://www.ultimate-guitar.com/artist/joaquin_sabina_1"})
    assert "## Artists to find" not in todo(conn, cfg, o)


def toml_blocks(text):
    return re.findall(r"```toml\n(.*?)```", text, re.S)


def section_of(text, title):
    return text.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


def test_the_artist_lines_pasted_as_shown_keep_overrides_readable(conn, cfg):
    # Two artists to find: pasting every block of the section, one after the other, must still load.
    for artist, title in (("Joaquín Sabina", "19 Días y 500 Noches"), ("宋冬野", "斑马斑马")):
        s = add_song(conn, artist, title)
        update_song(conn, s.id, match_decision="not_found")
    section = section_of(todo(conn, cfg), "Artists to find")
    pasted = "".join(toml_blocks(section)).replace("…", "634073")
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(pasted, encoding="utf-8")
    assert set(load_overrides(cfg.overrides_file).artist_url) == {"joaquin-sabina", "宋冬野"}


def test_artist_lines_for_a_file_with_the_table_already_leave_its_header_out(conn, cfg):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text('[artist_url]\n"Maná" = "https://www.ultimate-guitar.com/artist/mana_1"\n',
                                  encoding="utf-8")
    s = add_song(conn, "宋冬野", "斑马斑马")
    update_song(conn, s.id, match_decision="not_found")
    section = section_of(todo(conn, cfg, load_overrides(cfg.overrides_file)), "Artists to find")
    lines = "".join(toml_blocks(section)).replace("…", "song_dongye_2")
    assert "[artist_url]" not in lines and "under the `[artist_url]` table" in section
    text = cfg.overrides_file.read_text(encoding="utf-8").replace("[artist_url]\n", "[artist_url]\n" + lines, 1)
    cfg.overrides_file.write_text(text, encoding="utf-8")
    assert set(load_overrides(cfg.overrides_file).artist_url) == {"mana", "宋冬野"}


def test_review_lines_paste_under_the_tables_caracole_review_wrote(conn, cfg):
    from caracole.overrides import add_alias, add_match

    # `caracole review` settled another song: overrides.toml has [match] and [alias] already.
    add_match(cfg.overrides_file, "Soda - Persiana Americana", "soda-stereo/persiana-americana")
    add_alias(cfg.overrides_file, "Soda", "soda-stereo")
    index(conn, [(1, "radiohead", "creep", "chords")])
    s = add_song(conn, "Radio Head", "Crep")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.0, "step": "fuzzy_title"}])
    blocks = toml_blocks(review_item(todo(conn, cfg, load_overrides(cfg.overrides_file)), "Radio Head - Crep"))
    for block in blocks:
        assert not [line for line in block.splitlines() if line.startswith("[")], f"a header would repeat:\n{block}"
    block, dismiss = blocks  # the candidate's lines, then the [reject] line for none of them
    assert dismiss.endswith("  # under [reject]\n")
    # Each line goes under the table its comment names, as the section says.
    text = cfg.overrides_file.read_text(encoding="utf-8")
    for line in block.splitlines():
        table = re.search(r"# under (\[\w+\])$", line).group(1)
        text = text.replace(f"{table}\n", f"{table}\n{line}\n", 1)
    cfg.overrides_file.write_text(text, encoding="utf-8")
    o = load_overrides(cfg.overrides_file)
    assert o.match["radio-head/crep"] == ("radiohead", "creep") and o.alias["radio-head"] == ("radiohead",)
    assert o.match["soda/persiana-americana"] == ("soda-stereo", "persiana-americana")


def paste_as_commented(text, block):
    """overrides.toml's text with each line of a paste block put where its comment says: under the
    table it names, or in place of the line the file has for the same key (tomlkit writes it bare)."""
    for line in block.splitlines():
        table = re.search(r"under (\[\w+\])$", line).group(1)
        if "# in place of" in line:
            key = line.split(" = ", 1)[0]
            bare = key.strip('"')
            [old] = [k for k in text.splitlines() if k.startswith((f"{key} = ", f"{bare} = "))]
            text = text.replace(old, line, 1)
        else:
            text = text.replace(f"{table}\n", f"{table}\n{line}\n", 1)
    return text


def review_blocks_with_an_alias(conn, cfg, alias, step):
    """The paste blocks of a review of Soda - Persiana Americana, whose candidate is under UG's
    soda-stereo, with overrides.toml holding [match] for another song and ``alias`` for Soda."""
    from caracole.overrides import add_alias, add_match

    add_match(cfg.overrides_file, "Soda - Signos", "soda-stereo/signos")
    for slug in alias:
        add_alias(cfg.overrides_file, "Soda", slug)
    index(conn, [(1081460, "soda-stereo", "persiana-americana", "chords")])
    s = add_song(conn, "Soda", "Persiana Americana")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": step}])
    text = todo(conn, cfg, load_overrides(cfg.overrides_file))
    return toml_blocks(review_item(text, "Soda - Persiana Americana"))


def test_an_alias_line_for_an_artist_with_aliases_replaces_its_line_and_keeps_them(conn, cfg):
    # Soda has an alias already: a second "Soda" key under [alias] would make overrides.toml unreadable
    # ("Cannot overwrite a value"), so the page gives Soda's whole line, its other UG name included.
    block, _ = review_blocks_with_an_alias(conn, cfg, ["soda-stereo-ar"], "fuzzy_artist")
    assert '"Soda" = ["soda-stereo-ar", "soda-stereo"]  # in place of the artist\'s line under [alias]' in block
    text = paste_as_commented(cfg.overrides_file.read_text(encoding="utf-8"), block)
    cfg.overrides_file.write_text(text, encoding="utf-8")
    o = load_overrides(cfg.overrides_file)
    assert o.alias["soda"] == ("soda-stereo-ar", "soda-stereo")
    assert o.match["soda/persiana-americana"] == ("soda-stereo", "persiana-americana")


def test_no_alias_line_for_an_artist_whose_aliases_name_the_candidates_artist(conn, cfg):
    # Matched under its alias, on a fuzzy title: the alias is there already, so only [match] is new.
    block, _ = review_blocks_with_an_alias(conn, cfg, ["soda-stereo-ar", "soda-stereo"], "fuzzy_title")
    assert block == '"Soda - Persiana Americana" = "soda-stereo/persiana-americana"  # under [match]\n'
    text = paste_as_commented(cfg.overrides_file.read_text(encoding="utf-8"), block)
    cfg.overrides_file.write_text(text, encoding="utf-8")
    o = load_overrides(cfg.overrides_file)
    assert o.alias["soda"] == ("soda-stereo-ar", "soda-stereo")
    assert o.match["soda/persiana-americana"] == ("soda-stereo", "persiana-americana")


def test_a_review_says_how_to_dismiss_every_candidate(conn, cfg):
    index(conn, [(1081460, "soda-stereo", "persiana-americana", "chords")])
    s = add_song(conn, "Soda", "Persiana Americana")
    update_song(conn, s.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "soda-stereo", "song_key": "persiana-americana", "score": 82.0, "step": "fuzzy_artist"},
        {"artist_key": "soda-stereo", "song_key": "persiana", "score": 76.0, "step": "fuzzy_artist"},
    ])
    text = todo(conn, cfg)
    assert "(`[match]`, `[alias]`, `[reject]`)" in section_of(text, "Review")
    item = review_item(text, "Soda - Persiana Americana")
    assert "None of these? Answer `n` in `caracole review`, or add this line under `[reject]`" in item
    *_, block = toml_blocks(item)
    assert block == ('"Soda - Persiana Americana" = ["soda-stereo/persiana-americana", "soda-stereo/persiana"]'
                     "  # under [reject]\n")
    # Pasted under the table its comment names, it drops both, and the file still loads.
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text("[reject]\n" + block, encoding="utf-8")
    assert load_overrides(cfg.overrides_file).reject[s.key] == frozenset({
        ("soda-stereo", "persiana-americana"), ("soda-stereo", "persiana")})


def test_a_song_rejected_before_gets_its_whole_reject_line_to_put_in_place(conn, cfg):
    # More covers turned up after you dismissed the first ones. A second line for the same song under
    # [reject] would make overrides.toml unreadable, so the page gives the song's whole line instead.
    from caracole.overrides import add_reject

    add_reject(cfg.overrides_file, "Maná - Rayando el Sol", ["ana-gabriel/rayando-el-sol"])
    s = covers_only(conn, "Maná", "Rayando el Sol", "pablo-alboran")
    item = review_item(todo(conn, cfg, load_overrides(cfg.overrides_file)), "Maná - Rayando el Sol")
    assert "or put this line in place of the song's line under `[reject]`" in item
    *_, block = toml_blocks(item)
    text = cfg.overrides_file.read_text(encoding="utf-8")
    [old] = [line for line in text.splitlines() if line.startswith('"Maná - Rayando el Sol"')]
    cfg.overrides_file.write_text(text.replace(old + "\n", block), encoding="utf-8")
    assert load_overrides(cfg.overrides_file).reject[s.key] == frozenset({
        ("ana-gabriel", "rayando-el-sol"), ("pablo-alboran", "rayando-el-sol")})


def test_an_unreadable_overrides_file_leads_the_page(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="accept")
    error = "/lib/overrides.toml: Cannot declare ('artist_url',) twice (at line 4, column 12)"
    text = build_todo(conn, cfg, Overrides(), NOW, overrides_error=error)
    first = text.split("\n## ", 1)[1]
    assert first.startswith("Setup problems")
    setup = first.split("\n## ", 1)[0]
    assert "overrides.toml can't be read" in setup and error in setup and "merge" in setup


def test_find_artist_skips_artists_in_index(conn, cfg):
    index(conn, [(1, "soda-stereo", "signos", "chords")])
    s = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, s.id, match_decision="not_found")
    assert "## Artists to find" not in todo(conn, cfg)


def test_provider_health_shows_cooldown(conn, cfg):
    record_block(conn, "ug", NOW, "HTTP 403 on https://tabs.ultimate-guitar.com/tab/1")
    text = todo(conn, cfg)
    assert "## Provider health" in text
    assert "cooling down until 2026-10-19 05:41 UTC" in text
    assert "HTTP 403" in text


def test_suggestions_exclude_songs_already_wanted(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    kv_set_json(conn, "spotify:top_tracks", [
        {"id": "1", "title": "Creep", "artists": ["Radiohead"]},
        {"id": "2", "title": "Karma Police", "artists": ["Radiohead"]},
    ])
    text = todo(conn, cfg)
    assert "## Suggestions from your Spotify top tracks (1)" in text
    assert "Radiohead - Karma Police" in text


def test_sources_status(conn, cfg):
    import dataclasses

    from caracole.config import SpotifyConfig

    text = todo(conn, cfg)
    assert "Spotify: not configured" in text
    cfg = dataclasses.replace(cfg, spotify=SpotifyConfig(client_id="abc"))
    assert "Spotify: not synced yet" in todo(conn, cfg)
    kv_set_json(conn, "source:spotify", {"state": "auth_needed", "at": "2026-10-18T03:30:00Z",
                                         "message": "run `caracole auth spotify`"})
    kv_set_json(conn, "source:wanted", {"at": "2026-10-18T03:30:00Z", "lines": 12, "new": 2,
                                        "errors": [[3, "expected \"Artist - Title\""]]})
    text = todo(conn, cfg)
    assert "caracole auth spotify" in text
    assert "wanted.txt: 12 songs" in text and "line 3" in text


def test_markdown_special_characters_are_escaped(conn, cfg):
    s = add_song(conn, "Artist_with_[brackets]*", "Title")
    update_song(conn, s.id, match_decision="not_found")
    text = todo(conn, cfg)
    assert r"Artist\_with\_\[brackets\]\*" in text


def test_write_todo(cfg):
    path = write_todo(cfg.library_dir, "# caracole to-do\n")
    assert path == cfg.library_dir / "_todo.md"
    assert path.read_text(encoding="utf-8") == "# caracole to-do\n"


def test_header_links_to_the_library_page(conn, cfg):
    head = todo(conn, cfg).split("\n## ", 1)[0]
    assert "[index.html](index.html)" in head


def test_render_status_line(conn, cfg):
    kv_set_json(conn, "render:status",
                {"at": "2026-10-18T03:40:00Z", "rendered": 12, "failed": [], "font_error": None})
    text = todo(conn, cfg)
    assert "## PDFs" in text
    assert "2026-10-18 03:40 UTC: 12 rendered, 0 failed" in text
    assert "Couldn't render" not in text and "Font" not in text


def test_render_failures_and_font_error_are_shown(conn, cfg):
    kv_set_json(conn, "render:status", {
        "at": "2026-10-18T03:40:00Z", "rendered": 3, "failed": ["Soda Stereo - Persiana Americana", "A_B - [C]"],
        "font_error": "set cjk_font or CARACOLE_CJK_FONT to render 宋冬野 - 斑马斑马",
    })
    text = todo(conn, cfg)
    assert "## PDFs" in text
    pdfs = text.split("## PDFs", 1)[1].split("\n## ", 1)[0]
    assert "3 rendered, 2 failed" in pdfs
    assert r"set cjk\_font or CARACOLE\_CJK\_FONT to render 宋冬野 - 斑马斑马" in pdfs
    assert "Soda Stereo - Persiana Americana" in pdfs and r"A\_B - \[C\]" in pdfs


def test_render_status_with_a_count_instead_of_names_still_renders(conn, cfg):
    kv_set_json(conn, "render:status", {"at": "2026-10-18T03:40:00Z", "rendered": 4, "failed": 2, "font_error": None})
    assert "4 rendered, 2 failed" in todo(conn, cfg)
    kv_set_json(conn, "render:status", {"at": "nonsense", "rendered": 4, "failed": "abc"})
    text = todo(conn, cfg)
    assert "4 rendered, 0 failed" in text and "  - a" not in text


def test_no_pdf_section_before_the_first_render_or_for_a_bad_record(conn, cfg):
    assert "## PDFs" not in todo(conn, cfg)
    kv_set_json(conn, "render:status", ["not", "a", "record"])
    assert "## PDFs" not in todo(conn, cfg)


def test_spotify_auth_line_keeps_reason_and_advice(conn, cfg):
    import dataclasses

    from caracole.config import SpotifyConfig

    cfg = dataclasses.replace(cfg, spotify=SpotifyConfig(client_id="abc"))
    kv_set_json(conn, "source:spotify", {"state": "auth_needed", "at": "2026-10-18T03:30:00Z",
                                         "message": "the refresh token was revoked"})
    text = todo(conn, cfg)
    assert "the refresh token was revoked" in text and "Run `caracole auth spotify`." in text


AUTOCHORDS = "## Auto-chords couldn't read these purchases"


def test_autochords_failures_listed_with_their_file_and_error(conn, cfg):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, match_decision="not_found")
    kv_set_json(conn, "autochords:status", {"at": "2026-10-18T04:12:00Z", "generated": 1, "skipped": 3, "failed": [
        {"song": "宋冬野 - 斑马斑马", "error": "RuntimeError: Error opening '…': Format not recognised.",
         "audio": str(cfg.music_dir / "宋冬野" / "斑马斑马.m4a")},
        {"song": "A_B - [C]", "error": "ValueError: too short_to [read]", "audio": "/elsewhere/a `b`.wav"},
    ]})
    text = todo(conn, cfg)
    assert f"{AUTOCHORDS} (2)\n" in text
    assert text.index("## Buy list") < text.index(AUTOCHORDS) < text.index("## Provider health")
    section = text.split(f"{AUTOCHORDS} (2)\n", 1)[1].split("\n## ", 1)[0]
    assert "Re-download" in section and "convert it" in section and "replace the original" in section
    assert "tries a changed file again" in section and "2026-10-18 04:12 UTC" in section
    # Files in Music/ are shown from there, as you'd find them on the laptop.
    assert "- **宋冬野 - 斑马斑马**: `宋冬野/斑马斑马.m4a` · RuntimeError: Error opening '…': Format not recognised." in section
    assert r"- **A\_B - \[C\]**: /elsewhere/a \`b\`.wav · ValueError: too short\_to \[read\]" in section


def test_autochords_section_only_with_failures(conn, cfg):
    assert AUTOCHORDS not in todo(conn, cfg)
    for record in ({"at": "2026-10-18T04:12:00Z", "generated": 2, "skipped": 0, "failed": []},
                   ["not", "a", "record"], {"failed": "A - T"}, {"failed": [None, "x", {"song": "A - T"}]}):
        kv_set_json(conn, "autochords:status", record)
        assert AUTOCHORDS not in todo(conn, cfg), record


def test_autochords_section_copes_with_a_bad_timestamp(conn, cfg):
    kv_set_json(conn, "autochords:status", {"at": "nonsense", "failed": [
        {"song": "A - T", "error": "EOFError", "audio": "/music/x.wav"}, {"song": "B - U"}]})
    text = todo(conn, cfg)
    assert f"{AUTOCHORDS} (1)" in text and "- **A - T**: `/music/x.wav` · EOFError" in text
    assert "nonsense" not in text and "B - U" not in text
