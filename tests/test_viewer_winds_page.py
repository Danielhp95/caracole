"""The sheet viewer's harmonica, flute and recorder (viewer/winds.js, registered with instruments.js): the harmonica's
line under the key line and its settings row (the harps for the song, each chord's holes on the one chosen, the
song's harmonica tabs), the winds' row (the key's scale and each chord's notes, fingered; A–G or Do–Si; the
recorder's baroque or German fingering), each chord's card on them, the capo folded in, and a phone's width.

The tests open a viewer in a Chromium of their own (helpers/viewer_pages.py) and read what it draws back against
what harp.py and winds.py answer: a hole strip says what it plays (data-kind, data-breath, data-holes), a fingering
which note it is (data-note, as read) and how (data-fingering, the states of the instrument's keys).
"""

from __future__ import annotations

import json

from caracole.viewer import build_viewer, harp
from caracole.viewer.harmony import chord_tones
from caracole.viewer.theory import Key, parse_chord, spelling
from caracole.viewer.winds import FLUTE, RECORDER, chord_notes, fingerings, scale_notes

from helpers.browser import CHROMIUM_MARKS, Browser
from helpers.viewer_pages import viewer as open_viewer, written
from test_viewer_instruments_page import SETTINGS, choose, strip
from test_viewer_necks import reload

pytestmark = CHROMIUM_MARKS

DESKTOP = {"width": 1280, "height": 800, "mobile": False}
SONG = ("{title: Winds}\n{artist: Synthetic}\n{key: G}\n{comment: Verse}\n"
        "[G]made [C]up [D7]words [Em]here\n[Am]and [G/B]some [Cmaj7]more [Bb]there\n")
CHORDS = ["G", "C", "D7", "Em", "Am", "G/B", "Cmaj7", "Bb"]
# Em shapes with capo 2: the song sounds in F#m, and so a harmonica plays it.
CAPO_2 = ("{title: Capo}\n{artist: Synthetic}\n{key: Em}\n{capo: 2}\n{comment: Verse}\n"
          "[Em]la la [C]la la [G]la la [D]la\n")
G = Key(7, "ionian")

PANEL = """(() => {
  const box = document.getElementById('inst-panel');
  return {
    shown: !box.hidden,
    chips: [...box.querySelectorAll('.chip')].map((c) => [c.firstChild.textContent, c.getAttribute('aria-pressed')]),
    rows: [...box.querySelectorAll('.wl-row')].map((r) => [r.dataset.chord, r.querySelector('.wl-text')
      ? r.querySelector('.wl-text').textContent : null]),
    holes: [...box.querySelectorAll('.wl-row svg.hp')].map((s) => [s.dataset.kind, s.dataset.breath || null,
      s.dataset.holes || null]),
    title: [...box.querySelectorAll('.wd-title')].map((p) => p.textContent),
    scale: [...box.querySelectorAll('.wd-part .wd-tone')].map((t) => [t.querySelector('svg').dataset.note | 0,
      t.querySelector('svg').dataset.fingering, t.querySelector('.wd-name').textContent]),
    tones: [...box.querySelectorAll('.wd-row')].map((r) => [r.dataset.chord, [...r.querySelectorAll('.wd-tone')]
      .map((t) => [t.querySelector('svg').dataset.note | 0, t.querySelector('svg').dataset.fingering,
                   t.querySelector('.wd-name').textContent])]),
    tabs: [...box.querySelectorAll('.wd-tabs li')].map((li) => [li.querySelector('a').textContent,
      li.querySelector('a').getAttribute('href'), li.querySelector('.wd-key') ? li.querySelector('.wd-key').textContent : null,
      li.querySelector('.wd-key') ? li.querySelector('.wd-key').title : null]),
  };
})()"""
FACTS = "document.getElementById('facts').textContent"


def chords_in(key: Key, names: list[str]) -> list:
    return [parse_chord(n) for n in names]


def open_on(b: Browser, name: str) -> None:
    """The settings open on the instrument ``name``."""
    choose(b, name)
    assert b.wait("!document.getElementById('inst-panel').hidden")


# --- the harmonica: the harps for the song, under the key line -----------------------------------------------------


def test_the_settings_offer_the_harmonica_the_flute_and_the_recorder(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.click("#more")
        seen = b.js(SETTINGS)
        choose(b, "Recorder")
        recorder = b.js(SETTINGS)
    assert [c[0] for c in seen["chips"]][-3:] == ["Harmonica", "Flute", "Recorder"]
    assert recorder["hash"] == "#inst=recorder" and not recorder["capo"] and "octave above" in recorder["hint"]


def test_the_harmonica_line_names_the_harps_for_the_song_and_follows_the_key(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        guitar = b.js(FACTS)
        choose(b, "Harmonica")
        here = b.js(FACTS)
        b.click("#t-up")
        b.click("#t-up")
        up = b.js(FACTS)
    assert "Harmonica" not in guitar
    assert here == "Key G from the sheet" + "Harmonica: G harp (1st position) · C harp (2nd)"
    assert here.endswith(harp.header_line(G, chords_in(G, CHORDS)))
    assert up.endswith("Harmonica: A harp (1st position) · D harp (2nd)")


def test_with_a_capo_the_harmonica_plays_the_key_the_song_sounds_in(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, CAPO_2) + "#inst=harmonica") as b:
        facts = b.js(FACTS)
        names = b.js("[...document.querySelectorAll('#sheet .c')].map((c) => c.textContent)")
    sounding = Key(6, "aeolian")  # F#m
    assert names == ["F#m", "D", "A", "E"]
    assert facts == "Key F#m from the sheet" + harp.header_line(sounding, chords_in(sounding, names))
    assert facts.endswith("Harmonica: E harp (3rd position, dorian) · D harp (5th, phrygian) · A harp (4th, aeolian)")


# --- its settings row: each chord on the harp chosen ------------------------------------------------------------------


def expected_rows(harp_key: int) -> list[list[str]]:
    names = spelling(G)
    return [[n, harp.play(parse_chord(n), harp_key).text(names)] for n in CHORDS]


def test_the_harmonica_row_lists_each_chord_on_the_harp_chosen(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_on(b, "Harmonica")
        first = b.js(PANEL)
        b.js("document.querySelector('[data-wind-chip=\"harp-2\"]').click()")
        cross = b.js(PANEL)
        focused = b.js("document.activeElement.dataset.windChip")
    assert first["chips"] == [["G harp", "true"], ["C harp", "false"]]
    assert first["rows"] == expected_rows(7)
    assert first["rows"][2] == ["D7", "draw 2–5"] and first["rows"][1] == ["C", "not on this harp"]
    assert cross["chips"] == [["G harp", "false"], ["C harp", "true"]] and focused == "harp-2"
    assert cross["rows"] == expected_rows(0)
    assert cross["rows"][2] == ["D7", "draw 4–6 (as Dm, minor substitute)"] and cross["rows"][6][1] == "blow 1–3 (as C)"
    for (name, _), (kind, breath, holes) in zip(cross["rows"], cross["holes"], strict=True):
        played = harp.play(parse_chord(name), 0)
        assert kind == played.kind and breath == played.breath
        assert holes == (None if played.holes is None else "%d-%d" % played.holes)


def test_the_harmonica_row_links_the_songs_harmonica_tabs(tmp_path):
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True)
    page.write_text(build_viewer(SONG, harmonica=[{"name": "harmonica-1.txt", "href": "harmonica-1.txt", "key": "C"},
                                                  {"name": "harmonica-2.txt", "href": "harmonica-2.txt"}]),
                    encoding="utf-8")
    (page.parent / "harmonica-1.txt").write_text("6 6 6 -5 5\n", encoding="utf-8")
    with open_viewer(tmp_path, page.as_uri() + "#inst=harmonica") as b:
        b.click("#more")
        found = b.js(PANEL)
        b.js("document.querySelector('.wd-tabs a').click()")
        assert b.wait("location.href.endsWith('harmonica-1.txt')")
        text = b.js("document.body.textContent")
    assert found["title"] == ["Harmonica tabs"]
    # harptabs.com's Key chip is the song's key on some tabs and the harp's on others: never named a harp here.
    said = "The key harptabs.com's page names: the song's on some tabs, the harp's on others"
    assert found["tabs"] == [["harmonica-1.txt", "harmonica-1.txt", "key C (harptabs.com)", said],
                             ["harmonica-2.txt", "harmonica-2.txt", None, None]]
    assert "6 6 6 -5 5" in text


def test_a_chords_card_and_the_strip_show_its_holes(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG) + "#inst=harmonica") as b:
        strip(b)
        bare = b.js("[...document.querySelectorAll('#strip svg.hp')].map((s) => [s.dataset.kind, s.dataset.holes || null])")
        b.click('#sheet .c[data-c="2"]')  # D7
        assert b.wait("document.getElementById('card-name').textContent === 'D7'")
        card = b.js("""(() => { const s = document.querySelector('#diagram svg.hp');
          return [s.dataset.kind, s.dataset.breath, s.dataset.holes, [...s.querySelectorAll('.hp-on')].map((h) => h.dataset.hole | 0),
                  document.querySelector('#diagram .hp-text').textContent, document.querySelector('#diagram .hp-harp').textContent]; })()""")
        heard = b.wait("document.documentElement.dataset.heard !== undefined") and b.js(
            "document.documentElement.dataset.heard")
    on_g = [harp.play(parse_chord(n), 7) for n in CHORDS]
    assert bare == [[p.kind, None if p.holes is None else "%d-%d" % p.holes] for p in on_g]
    assert card == ["yes", "draw", "2-5", [2, 3, 4, 5], "draw 2–5", "G harp, 1st position"]
    # G harp draw 2-5: D4 F#4 A4 C5 (the G harp is pitched a fourth below a C harp: hole 1 blows G3).
    assert heard == " ".join(f"{440 * 2 ** ((m - 69) / 12):.2f}" for m in harp.layout(7).draw[1:5])


# --- the flute and the recorder ----------------------------------------------------------------------------------------


def fingered(wind, notes: list[int], system: str | None = None) -> list[tuple[int, str]]:
    return [[n, fingerings(wind, n, system=system)[0].text] for n in notes]


def test_the_flute_row_fingers_the_keys_scale_and_each_chords_notes(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_on(b, "Flute")
        letters = b.js(PANEL)
        b.js("document.querySelector('[data-wind-chip=\"names-solfege\"]').click()")
        solfege = b.js(PANEL)
        focused = b.js("document.activeElement.dataset.windChip")
        reload(b)
        b.click("#more")
        kept = b.js(PANEL)
    assert letters["chips"] == [["A–G", "true"], ["Do–Si", "false"]]
    assert letters["title"] == ["G scale"]
    assert [[n, f] for n, f, _ in letters["scale"]] == fingered(FLUTE, scale_notes(G))
    assert [name for _, _, name in letters["scale"]] == "G A B C D E F# G".split()
    for chord, tones in letters["tones"]:
        found = parse_chord(chord)
        assert [[n, f] for n, f, _ in tones] == fingered(FLUTE, chord_notes(found)), chord
        assert [name for _, _, name in tones] == [name for name, _ in chord_tones(found, G)], chord
    assert [c for c, _ in letters["tones"]] == CHORDS
    assert [name for _, _, name in solfege["scale"]] == "Sol La Si Do Re Mi Fa# Sol".split() and focused == "names-solfege"
    assert [name for _, _, name in solfege["tones"][7][1]] == ["Sib", "Re", "Fa"]  # Bb
    assert kept["chips"] == [["A–G", "false"], ["Do–Si", "true"]]  # the browser keeps it for every page


def test_the_recorder_reads_the_same_notes_in_baroque_or_german_fingering(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG)) as b:
        open_on(b, "Recorder")
        baroque = b.js(PANEL)
        b.js("document.querySelector('[data-wind-chip=\"recorder-german\"]').click()")
        german = b.js(PANEL)
    assert baroque["chips"] == [["A–G", "true"], ["Do–Si", "false"], ["Baroque", "true"], ["German", "false"]]
    assert [[n, f] for n, f, _ in baroque["scale"]] == fingered(RECORDER, scale_notes(G), "baroque")
    assert [[n, f] for n, f, _ in german["scale"]] == fingered(RECORDER, scale_notes(G), "german")
    f_sharp = [f for n, f, _ in baroque["scale"] if n == 78] + [f for n, f, _ in german["scale"] if n == 78]
    assert f_sharp == ["hxxxoxooo", "hxxxoxoxo"]  # F#5: the second finger alone, or the little finger with it


def test_a_chords_card_on_the_flute_shows_its_notes_fingered(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG) + "#inst=flute") as b:
        strip(b)
        bare = b.js("[...document.querySelectorAll('#strip .wd-names')].map((s) => s.textContent)")
        b.click('#sheet .c[data-c="3"]')  # Em
        assert b.wait("document.getElementById('card-name').textContent === 'Em'")
        card = b.js("[...document.querySelectorAll('#diagram svg.wd')].map((s) => [s.dataset.note | 0, s.dataset.fingering])")
        heard = b.wait("document.documentElement.dataset.heard !== undefined") and b.js(
            "document.documentElement.dataset.heard")
    assert bare[3] == "E G B" and len(bare) == len(CHORDS)
    assert card == fingered(FLUTE, chord_notes(parse_chord("Em")))
    assert heard == "329.63 392.00 493.88"  # E4 G4 B4, one after the other


# --- a phone's width, and a laptop's ------------------------------------------------------------------------------------


def test_no_sideways_scroll_at_390_px_with_each_row_open(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG + "[C13]la [Bb11]la [G7#9]la [Dm9]la\n")) as b:
        for name in ("Harmonica", "Flute", "Recorder"):
            open_on(b, name)
            wide = b.js("""[document.documentElement.scrollWidth, innerWidth,
              Math.max(...[...document.querySelectorAll('#inst-panel *')].map((e) => e.getBoundingClientRect().right)),
              document.getElementById('panel').getBoundingClientRect().right]""")
            assert wide[0] == wide[1] == 390, name
            assert wide[2] <= wide[3], name


def test_the_rows_sit_in_the_settings_rail_on_a_laptop(tmp_path):
    with open_viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        for name in ("Harmonica", "Flute"):
            open_on(b, name)
            seen = b.js("""[document.documentElement.scrollWidth, innerWidth,
              Math.max(...[...document.querySelectorAll('#inst-panel *')].map((e) => e.getBoundingClientRect().right)),
              document.getElementById('panel').getBoundingClientRect().right]""")
            assert seen[0] == seen[1] and seen[2] <= seen[3], name
        b.click('#sheet .c[data-c="0"]')
        assert b.wait("!document.getElementById('card').hidden")
        card = b.js("""[document.querySelector('#diagram .wd-tones').getBoundingClientRect().right,
          document.getElementById('card').getBoundingClientRect().right]""")
    assert card[0] < card[1]


def test_a_songbooks_song_on_the_flute_reads_the_one_block_of_fingerings(tmp_path):
    from caracole.viewer.book import BookSong, build_songbook

    songs = [BookSong("One", "Synthetic", cho=SONG, id="aaaa"), BookSong("Two", "Synthetic", cho=CAPO_2, id="bbbb")]
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", songs), encoding="utf-8")
    with open_viewer(tmp_path, path.as_uri() + "#song-2") as b:
        open_on(b, "Flute")
        found = b.js(PANEL)
        facts = b.js(FACTS)
        choose(b, "Harmonica")
        line = b.js(FACTS)
    assert facts.startswith("Key F#m") and found["title"] == ["F#m scale"]
    assert [[n, f] for n, f, _ in found["scale"]] == fingered(FLUTE, scale_notes(Key(6, "aeolian")))
    assert line.endswith(harp.header_line(Key(6, "aeolian"), chords_in(Key(6, "aeolian"), ["F#m", "D", "A", "E"])))
    assert json.dumps(found)  # drawn, from the songbook's one block
