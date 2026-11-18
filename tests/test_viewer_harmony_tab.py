"""The overlay's Harmony tab (overlay.js, viewer.js, viewer.css): "Guitar | Harmonica | Harmony" in the rail from
1200 px and in the phone's sheet of necks, on a sheet whose key caracole can tell (a harmonica tab's page has none).

Under the key the numerals are read in, it heads with the key's neck (its scale, or its pentatonic box), which the
Guitar tab then leaves out, then the tempo and each section's progression: its numerals, one cycle, the times it is
played (and how many of those vary it), its name, the named progressions it plays within it and how it ends. A tap goes
to its section; ▶ plays it with strum.js's synthesis. Leaving the tab (another tab, ✕, Escape, Hide, the window narrowed
past the rail) stops it, as closing the Harmony panel did; the settings have no Harmony row. The tests drive the page in
Chromium on real time (helpers/browser.py's ``Browser``); test_viewer_sound.py records what it plays."""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.browser import in_chromium
from helpers.targets import small_targets
from helpers.viewer_pages import harmony_tab, viewer, written

from caracole.viewer import build_viewer

PHONE = {"width": 390, "height": 844, "mobile": True}
DESKTOP = {"width": 1280, "height": 800, "mobile": False}

SONG = ("{title: Progressions}\n{artist: Synthetic}\n{key: C}\n"
        "{comment: Verse}\n" + "[C]made [G]up [Am]words [F]here\n" * 4 + "\n"
        "{comment: Chorus}\n[F]and [G]the [C]cho[Am]rus\n[F]ends [G]at [C]home\n\n"
        "{comment: Riff}\n[N.C.]no chords here\n\n"
        "{comment: Bridge}\n[Am]down [G]the [F]stairs [E7]again\n")
UNNAMED = "{title: Unnamed}\n{artist: Synthetic}\n[Am]down [G]the [F]stairs [E7]again\n[Am]down [G]the [F]stairs [E7]again\n"
IN_C = "{title: In C}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n[C]made [G]up [Am]words [F]here\n"
NO_KEY = "{title: Riffs}\n{artist: Synthetic}\n{capo: 1}\n{comment: Verse}\n[N.C.]Made up [Xq]words\n"
# A verse that plays the pop progression twice within it, and folds round one pass that varies it; a chorus on
# the Andalusian cadence, its last pass with a chord more.
NAMED = ("{title: Named}\n{artist: Synthetic}\n{key: Am}\n"
         "{comment: Verse}\n[Dm]made [C]up [G]words [Am]to [F]sing\n[Bb]and [C]more [G]of [Am]them [F]here\n\n"
         "{comment: Chorus}\n" + "[Am]la [G]la [F]la [E7]la\n" * 3 + "[Am]la [G]la [F]la [Dm]la [E7]la\n")
# A verse that plays ii–V–I, then the Andalusian cadence read in C major: a link to the songs with each.
# In C major, named with its mode: "C" alone over chords that centre on A minor is A minor (theory.bare_key)
TWO = "{title: Two}\n{artist: Synthetic}\n{key: C major}\n{comment: Verse}\n[Dm7]a [G7]b [Cmaj7]c [Am]d [G]e [F]f [E7]g\n"

# What the Harmony tab lists, section by section, and where it is; None while it isn't drawn.
HARMONY = """(() => { const h = document.querySelector('#necks #harmony'); if (!h) return null;
  const box = (el) => { const r = el.getBoundingClientRect();
    return {top: Math.round(r.top), bottom: Math.round(r.bottom), left: Math.round(r.left), right: Math.round(r.right)}; };
  const rail = document.getElementById('necks'), kn = h.querySelector('.kn');
  return {box: box(h), rail: box(rail), sheet: rail.dataset.sheet || null,
    tabs: [...rail.querySelectorAll('[role=tab]')].map((t) => [t.textContent, t.getAttribute('aria-selected')]),
    key: document.getElementById('harmony-key').textContent,
    neck: kn ? kn.querySelector('.kn-name').textContent : null,
    // the key's neck first, before the tempo and the progressions
    first: Boolean(kn) && [...h.querySelectorAll('.kn, #tempo-row, #progs')][0] === kn,
    tempo: !document.getElementById('tempo-row').hidden, bpm: document.getElementById('bpm').textContent,
    rows: [...h.querySelectorAll('.prog')].map((li) => ({
      section: li.querySelector('.prog-sec').textContent,
      numerals: [...li.querySelectorAll('.prog-nums .pn')].map((n) => n.textContent),
      repeats: li.querySelector('.prog-x') ? li.querySelector('.prog-x').textContent : '',
      about: li.querySelector('.prog-about').textContent,
      play: !li.querySelector('.prog-play').hidden,
      songs: li.querySelector('.prog-songs').getAttribute('href'),
      named: [...li.querySelectorAll('.prog-named')].map((a) => [a.textContent, a.getAttribute('href')])})),
    none: !document.getElementById('progs-none').hidden,
    focus: document.activeElement ? document.activeElement.id : '', panel: !document.getElementById('panel').hidden,
    inside: rail.scrollWidth <= rail.clientWidth, page: document.documentElement.scrollWidth}; })()"""
TABS = "[...document.querySelectorAll('#necks [role=tab]')].map((t) => t.textContent)"
# A stand-in for HV3's synthesis (strum.js: window.caracoleSound), noting what it is asked to play.
FAKE_SOUND = """window.caracoleSound = {available: true, stop() {},
  play(chords, options) { window.asked = {chords, bpm: options.bpm}; window.playing = options;
    options.onChord(0);
    return {playing: true, stop() { window.stopped = true; options.onEnd(false); }}; }};"""
PLAY = "document.querySelectorAll('#harmony .prog-play')[0].click()"
SAID = "document.querySelectorAll('#harmony .prog-play')[0].getAttribute('aria-label')"


def tab(b, name: str) -> None:
    """The overlay's tab ``name`` pressed, once it shows."""
    b.js(f"document.querySelector('#necks [role=tab][data-tab={name}]').click()")
    assert b.wait(f"document.querySelector('#necks .ov-pane').dataset.tab === '{name}'")


# --- the page as written --------------------------------------------------------------------------------------------


def test_the_page_has_no_harmony_panel_and_the_settings_no_harmony_row():
    html = build_viewer(SONG)
    assert 'id="harmony-open"' not in html and 'id="harmony-row"' not in html and 'id="harmony"' not in html
    assert 'id="progs"' not in html and 'id="bpm"' not in html  # the tab draws them


# --- the tab, and the key's neck --------------------------------------------------------------------------------------


@in_chromium
def test_a_sheet_with_a_key_has_harmony_as_the_overlays_third_tab(tmp_path):
    from test_viewer_harptab_browser import WIDE_SCREEN, opened, with_sheet

    with viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        rail = b.js(TABS)
    with viewer(tmp_path, written(tmp_path, SONG, name="Phone")) as b:
        b.click("#necks-open")
        assert b.wait("document.getElementById('necks').dataset.sheet === 'half'")
        phone = b.js(TABS)
    with viewer(tmp_path, written(tmp_path, NO_KEY, name="Riffs"), **DESKTOP) as b:
        no_key = b.js(TABS)
    with opened(tmp_path, with_sheet(tmp_path), **WIDE_SCREEN) as b:
        harmonica = b.js(TABS)
    assert rail == phone == ["Guitar", "Harmonica", "Harmony"]
    assert no_key == ["Guitar", "Harmonica"]  # no key, no numerals to read the progressions in
    assert harmonica == ["Harmonica", "Guitar"]  # a harmonica tab's page has none


@in_chromium
def test_the_keys_neck_heads_the_harmony_tab_and_the_guitar_tab_has_the_chords_alone(tmp_path):
    from test_viewer_harptab_browser import WIDE_SCREEN, opened, with_sheet

    necks = "[[...document.querySelectorAll('#necks .kn')].length, " \
            "[...document.querySelectorAll('#necks .nk-name')].map((n) => n.textContent)]"
    with viewer(tmp_path, written(tmp_path, IN_C), **DESKTOP) as b:
        guitar = b.js(necks)
        harmony_tab(b)
        seen = b.js(HARMONY)
        b.click("#harmony .kn .chip:nth-of-type(2)")
        box = [b.js(HARMONY)["neck"], b.js("document.activeElement.textContent")]
    with opened(tmp_path, with_sheet(tmp_path), **WIDE_SCREEN) as b:
        tab(b, "guitar")
        harmonica_page = b.js("document.querySelector('#necks .ov-pane > .kn .kn-name').textContent")
    assert guitar == [0, ["C", "G", "Am", "F"]]  # the chords alone: the key's neck is Harmony's
    assert seen["neck"] == "C scale" and seen["first"]
    assert box == ["C major pentatonic", "Major pentatonic"]  # switched, the focus kept on the switch
    assert harmonica_page == "Am scale"  # with no Harmony tab, the Guitar tab heads with it still


@in_chromium
def test_on_a_phone_the_harmony_tab_lists_each_sections_progression(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        harmony_tab(b)
        seen = b.js(HARMONY)
        bar = b.js("Math.round(document.getElementById('bar').getBoundingClientRect().top)")
        targets = b.js(small_targets(".foot *"))
    assert seen["tabs"] == [["Guitar", "false"], ["Harmonica", "false"], ["Harmony", "true"]]
    assert seen["sheet"] == "half" and seen["focus"] == "necks-tab-harmony" and not seen["panel"]
    # The tab's box is the sheet's, on the bar, across the phone
    assert seen["rail"]["bottom"] == bar and seen["rail"]["left"] == 0 and seen["rail"]["right"] == 390
    assert seen["rail"]["left"] < seen["box"]["left"] and seen["box"]["right"] < seen["rail"]["right"]
    assert seen["key"] == "In the key of C (from the sheet)."
    assert seen["neck"] == "C scale" and seen["first"]
    verse, chorus, bridge = seen["rows"]  # the riff has no chord to read
    assert verse == {"section": "Verse", "numerals": ["I", "V", "vi", "IV"], "repeats": "×4",
                     "about": "the pop progression", "play": True,  # strum.js plays it
                     "songs": "../../index.html#prog=I%20V%20vi%20IV", "named": []}
    assert chorus["numerals"] == ["IV", "V", "I", "vi", "IV", "V", "I"] and chorus["repeats"] == ""
    # Its C Am F G, I–vi–IV–V, is the '50s progression from its own first chord, inside the longer chorus.
    assert chorus["about"] == "contains the '50s progression · ends on an authentic cadence (V–I)"
    assert chorus["named"] == [["Songs with the '50s progression", "../../index.html#prog=I%20vi%20IV%20V"]]
    assert verse["named"] == []  # the verse is the pop progression whole: its own link says so
    assert bridge["section"] == "Bridge" and bridge["numerals"][0] == "vi"
    assert seen["tempo"] and seen["bpm"] == "80" and not seen["none"]
    assert seen["inside"] and seen["page"] <= 390 and targets == []


@in_chromium
def test_a_page_that_cant_play_a_chord_offers_no_play_and_no_tempo(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.js("window.caracoleSound = undefined")  # as in a browser with no Web Audio
        harmony_tab(b)
        seen = b.js(HARMONY)
    assert seen["rows"] and not any(r["play"] for r in seen["rows"]) and not seen["tempo"]


@in_chromium
def test_with_the_sound_off_the_tab_offers_no_play_until_it_is_on_again(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG) + "#vol=0") as b:
        harmony_tab(b)
        off = b.js(HARMONY)
        b.click("#more")  # on a phone, in the sheet's place
        assert b.wait("document.querySelector('#necks #harmony') === null")
        b.js("[...document.querySelectorAll('#volumes > button')].find((c) => c.getAttribute('aria-label') === 'Soft').click()")
        harmony_tab(b)
        on = b.js(HARMONY)
    assert off["rows"] and not any(r["play"] for r in off["rows"]) and not off["tempo"]
    assert all(r["play"] for r in on["rows"]) and on["tempo"]


@in_chromium
def test_on_a_laptop_the_harmony_tab_is_in_the_rail_beside_the_settings(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG), **DESKTOP) as b:
        harmony_tab(b)
        seen = b.js(HARMONY)
        b.click("#more")  # the settings on the right, the tab still on the left
        both = b.js(HARMONY)
        panel = b.js("""(() => { const r = document.getElementById('panel').getBoundingClientRect();
          return [Math.round(r.left), Math.round(r.right), document.documentElement.clientWidth]; })()""")
    assert seen["rail"]["left"] == 0 and seen["rail"]["right"] == 345 and seen["sheet"] is None
    assert seen["box"]["right"] <= 345 and seen["neck"] == "C scale" and seen["page"] <= 1280
    assert both is not None and both["panel"] and both["rows"] == seen["rows"]
    assert panel[1] == panel[2] and panel[0] >= 345  # beside it, never over it


@in_chromium
def test_a_section_tapped_in_the_tab_comes_into_view(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG + "".join(f"{{comment: Outro {n}}}\n[C]la [G]la\n" for n in range(30)))) as b:
        harmony_tab(b)
        b.js("document.querySelectorAll('#harmony .prog-go')[2].click()")  # the bridge
        assert b.wait("Math.abs(document.querySelectorAll('#sheet section.sec')[3].getBoundingClientRect().top) < 40")
        still = b.js("document.querySelector('#necks #harmony') !== null")
    assert still


@in_chromium
def test_with_numerals_on_a_sections_heading_names_its_progression(tmp_path):
    heads = "[...document.querySelectorAll('#sheet h2.lbl')].map((h) => h.textContent)"
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        plain = b.js(heads)
    with viewer(tmp_path, written(tmp_path, SONG, name="Numbered") + "#nm=both") as b:
        named = b.js(heads)
    assert plain == ["Verse", "Chorus", "Riff", "Bridge"]
    # The bridge, vi V IV V7/vi, is the Andalusian cadence read in the relative major; the chorus plays the
    # '50s progression within it.
    assert named == ["Verse · the pop progression", "Chorus · contains the '50s progression", "Riff",
                     "Bridge · the Andalusian cadence"]


@in_chromium
def test_a_sheet_with_no_headings_has_one_section_to_list(tmp_path):
    with viewer(tmp_path, written(tmp_path, UNNAMED)) as b:
        harmony_tab(b)
        seen = b.js(HARMONY)
    assert [(r["section"], r["numerals"], r["repeats"], r["about"]) for r in seen["rows"]] == [
        ("Section 1", ["i", "♭VII", "♭VI", "V7"], "×2", "the Andalusian cadence · ends on a half cadence (on V)")]


@in_chromium
def test_the_tab_names_a_progression_a_section_plays_within_it_and_a_cycle_that_varies(tmp_path):
    with viewer(tmp_path, written(tmp_path, NAMED) + "#nm=numerals") as b:
        harmony_tab(b)
        seen = b.js(HARMONY)
        heads = b.js("[...document.querySelectorAll('#sheet h2.lbl')].map((h) => h.textContent)")
    verse, chorus = seen["rows"]
    assert verse["numerals"] == ["iv", "♭III", "♭VII", "i", "♭VI", "♭II", "♭III", "♭VII", "i", "♭VI"]
    assert verse["about"] == "contains the pop progression ×2"
    assert verse["named"] == [["Songs with the pop progression", "../../index.html#prog=I%20V%20vi%20IV"]]
    assert chorus["numerals"] == ["i", "♭VII", "♭VI", "V7"] and chorus["repeats"] == "×4, 1 variation"
    assert chorus["about"] == "the Andalusian cadence · ends on a half cadence (on V)" and chorus["named"] == []
    assert heads == ["Verse · contains the pop progression ×2", "Chorus · the Andalusian cadence"]


@in_chromium
def test_a_link_focused_in_the_tab_keeps_the_focus_though_the_tab_is_drawn_anew(tmp_path):
    with viewer(tmp_path, written(tmp_path, TWO)) as b:
        harmony_tab(b)
        links = b.js("[...document.querySelectorAll('#harmony .prog-named')].map((a) => a.textContent)")
        b.js("window.was = document.querySelectorAll('#harmony .prog-named')[1]; was.focus()")
        b.js("document.getElementById('t-up').click()")  # the song transposed: the tab is drawn anew
        after = b.js("[document.activeElement.textContent, document.activeElement.isConnected,"
                     " document.activeElement !== window.was, window.was.isConnected]")
        b.js("document.querySelector('#harmony #bpm-up').focus(); document.getElementById('t-down').click()")
        tempo = b.js("[document.activeElement.id, document.activeElement.isConnected]")
    assert links == ["Songs with ii–V–I", "Songs with the Andalusian cadence"]
    # the second link, as before, not the first: drawn anew, its own
    assert after == ["Songs with the Andalusian cadence", True, True, False]
    assert tempo == ["bpm-up", True]


# --- playing a progression --------------------------------------------------------------------------------------------


@in_chromium
def test_play_asks_the_synthesis_for_the_progression_and_marks_the_chord_playing(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.js(FAKE_SOUND)
        harmony_tab(b)
        shown = b.js(HARMONY)
        b.js(PLAY)
        asked = b.js("window.asked")
        marked = b.js("[...document.querySelectorAll('#harmony .prog')[0].querySelectorAll('.pn.on')].map((n) => n.textContent)")
        label = b.js(SAID)
        b.js("window.playing.onChord(5)")
        later = b.js("[...document.querySelectorAll('#harmony .prog')[0].querySelectorAll('.pn.on')].map((n) => n.textContent)")
        shapes = b.js("""(() => { const d = JSON.parse(document.getElementById('song').textContent);
          const rep = d.chords[0]; return d.voicings[rep[3]][rep[0]][0]; })()""")
        b.click("#bpm-up")
        tempo = b.js("document.getElementById('bpm').textContent")
        b.js(PLAY)  # ■
        stopped = b.js(f"[window.stopped, {SAID}]")
    assert shown["tempo"] and all(r["play"] for r in shown["rows"])
    assert asked["bpm"] == 80 and len(asked["chords"]) == 4 * 4  # a chord a bar, the cycle four times
    # with the guitar's strings and its sound (strum.js: the default tuning and voice)
    assert asked["chords"][0] == {"position": shapes, "capo": 0, "tuning": [40, 45, 50, 55, 59, 64], "voice": "guitar"}
    assert marked == ["I"] and later == ["V"] and label == "Stop"
    assert tempo == "85"
    assert stopped == [True, "Play Verse"]


@in_chromium
@pytest.mark.skipif(not (Path(__file__).parents[1] / "src" / "caracole" / "viewer" / "strum.js").exists(),
                    reason="waits for HV3's synthesis (strum.js, window.caracoleSound)")
def test_play_strums_the_progression_with_hv3s_synthesis(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        harmony_tab(b)
        b.click("#harmony .prog-play")
        assert b.wait("document.documentElement.dataset.heard !== undefined", timeout=5)
        heard = b.js("document.documentElement.dataset.heard")
        b.click("#harmony .prog-play")
    assert heard


@in_chromium
@pytest.mark.parametrize("change", ["t-up", "capo-up"])
def test_a_progression_playing_stops_once_the_song_is_played_otherwise(tmp_path, change):
    """Transposed in the bar (or the capo moved) while a progression plays: it stops, ■ back to ▶, never going on in
    chords the page no longer shows."""
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.js(FAKE_SOUND)
        harmony_tab(b)
        b.js(PLAY)
        playing = b.js(SAID)
        b.js("window.stopped = false")
        b.js(f"document.getElementById('{change}').click()")
        after = b.js(f"[window.stopped, {SAID}]")
    assert playing == "Stop"
    assert after == [True, "Play Verse"], after


@in_chromium
def test_leaving_the_tab_stops_the_progression(tmp_path):
    # On a phone: another tab, then ✕, then Escape, each with the verse playing.
    stops = []
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.js(FAKE_SOUND)
        for leave in (lambda: tab(b, "guitar"), lambda: b.js("document.querySelector('#necks .ov-close').click()"),
                      lambda: b.press("Escape")):
            harmony_tab(b)
            b.js(f"window.stopped = false; {PLAY}")
            assert b.js(SAID) == "Stop"
            leave()
            stops.append(b.js("[window.stopped, document.querySelector('#necks #harmony') === null]"))
    # On a laptop: Hide, then the window narrowed past the rail.
    with viewer(tmp_path, written(tmp_path, SONG, name="Laptop"), **DESKTOP) as b:
        b.js(FAKE_SOUND)
        harmony_tab(b)
        b.js(f"window.stopped = false; {PLAY}")
        b.click("#necks .nk-hide")
        stops.append(b.js("[window.stopped, document.querySelector('#necks #harmony') === null]"))
        b.click("#necks-toggle")
        assert b.wait("document.querySelector('#necks #harmony') !== null")  # back on its tab
        b.js(f"window.stopped = false; {PLAY}")
        b.send("Emulation.setDeviceMetricsOverride", width=1100, height=800, deviceScaleFactor=1, mobile=False)
        assert b.wait("document.getElementById('necks').hidden")
        stops.append(b.js("[window.stopped, document.querySelector('#necks #harmony') === null]"))
    assert stops == [[True, True]] * 5


@in_chromium
@pytest.mark.parametrize("width", [1200, 1400])
def test_three_tabs_fit_the_rails_head_beside_hide(tmp_path, width):
    from test_viewer_necks import MANY_CHO  # enough necks for the rail to scroll, its scroll bar beside them

    fit = """(() => { const control = document.querySelector('#necks .ov-tabs'), box = control.getBoundingClientRect();
      const hide = document.querySelector('#necks .nk-hide').getBoundingClientRect();
      return {tabs: [...control.children].map((t) => { const r = t.getBoundingClientRect(), text = document.createRange();
          text.selectNodeContents(t); const w = text.getBoundingClientRect();
          return [t.textContent, w.left >= r.left && w.right <= r.right, r.left >= box.left && r.right <= box.right]; }),
        beside: box.right <= hide.left,
        scrolls: document.getElementById('necks').scrollHeight > document.getElementById('necks').clientHeight}; })()"""
    with viewer(tmp_path, written(tmp_path, MANY_CHO), width=width, height=800, mobile=False) as b:
        seen = b.js(fit)
        harmony_tab(b)
        on_harmony = b.js(fit)
    for now in (seen, on_harmony):
        assert now["tabs"] == [["Guitar", True, True], ["Harmonica", True, True], ["Harmony", True, True]], now
        assert now["beside"] and now["scrolls"], now
