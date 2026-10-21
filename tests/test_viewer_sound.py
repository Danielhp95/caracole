"""caracole.viewer: hear a chord (strum.js, viewer.js): the voicing a chord's card shows, strummed in Web Audio.

A tap on a chord's name (in the sheet or the strip) or on its card's diagram strums the shape shown, at
the capo, in standard tuning, by a plucked-string synthesis (Karplus-Strong) that loads nothing. Nothing
sounds without a tap: the AudioContext is made on the first one, and one the browser suspended (the page
was hidden) is resumed on the next. One sound at a time. The volume is a setting (``vol`` in the address).

The page writes the frequencies it strummed last on ``<html data-heard>`` for these tests. They count
the AudioContexts the page makes with a script the browser runs before the page's own
(``Page.addScriptToEvaluateOnNewDocument``, which the page's policy doesn't stop), in a Chromium of their
own on real time (helpers/browser.py's ``Browser``).
"""

from __future__ import annotations

import http.server
import json
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from helpers import browser
from helpers.browser import Browser, in_chromium
from helpers.viewer_pages import key, tap_at

from caracole.inline import sha256_source
from caracole.viewer import build_viewer, page, viewer_csp
from caracole.viewer.book import BookSong, build_songbook

# C, G, Am and F in C major (data-c 0 to 3).
SONG = "{title: Sound}\n{artist: Synthetic}\n{key: C}\n" + "".join(
    f"[C]Synthetic line [G]number {n} [Am]made up to [F]play by\n" for n in range(6))
# chords-db's first C (x32010): C3 E3 G3 C4 E4, low string first; with the capo on 3, the A shape
# (x02220) that plays it: C3 G3 C4 E4 G4.
C_OPEN = "130.81 164.81 196.00 261.63 329.63"
C_AS_A_SHAPE_CAPO_3 = "130.81 196.00 261.63 329.63 392.00"

# Run before the page's own script: every AudioContext the page makes, every resume() it asks for, and
# every sound it starts, stops, and that ends (stopped, or rung out).
SPY = """(() => {
  const Real = window.AudioContext;
  window.spy = { contexts: [], resumes: 0, started: [], stopped: new Set(), ended: new Set() };
  window.AudioContext = class extends Real {
    constructor(...args) { super(...args); window.spy.contexts.push(this); }
    resume() { window.spy.resumes += 1; return super.resume(); }
  };
  // AudioBufferSourceNode has a start of its own (an offset, a duration).
  for (const proto of [AudioScheduledSourceNode.prototype, AudioBufferSourceNode.prototype]) {
    const start = Object.getOwnPropertyDescriptor(proto, "start"), stop = Object.getOwnPropertyDescriptor(proto, "stop");
    if (start) proto.start = function (...args) {
      window.spy.started.push(this);
      this.when = args[0];
      this.addEventListener("ended", () => window.spy.ended.add(this));
      return start.value.apply(this, args);
    };
    if (stop) proto.stop = function (...args) { window.spy.stopped.add(this); return stop.value.apply(this, args); };
  }
})()"""

# What the page has made and played.
LOOK = """(() => ({
  contexts: spy.contexts.length, state: spy.contexts.length ? spy.contexts[0].state : null,
  resumes: spy.resumes, started: spy.started.length,
  heard: document.documentElement.dataset.heard === undefined ? null : document.documentElement.dataset.heard,
}))()"""


@contextmanager
def opened(tmp_path: Path, url: str, *, width: int = 390, height: int = 844, mobile: bool = True):
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), width=width, height=height,
                 mobile=mobile) as b:
        b.send("Page.addScriptToEvaluateOnNewDocument", source=SPY)
        b.open(url)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        yield b


def written(tmp_path: Path, html: str, name: str = "sheet.html") -> str:
    path = tmp_path / "Artist" / "Title" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path.as_uri()


def middle(b: Browser, selector: str) -> list[float]:
    """Where to tap ``selector``: the middle of the first in view, scrolled there first."""
    return b.js(f"""(() => {{
      const el = document.querySelector({json.dumps(selector)});
      el.scrollIntoView({{block: "center"}});
      const r = el.getBoundingClientRect();
      return [r.x + r.width / 2, r.y + r.height / 2];
    }})()""")


def tap(b: Browser, selector: str) -> None:
    tap_at(b, *middle(b, selector))


def look(b: Browser) -> dict:
    return b.js(LOOK)


# --- the page ------------------------------------------------------------------------------------------


def test_the_synthesis_is_a_script_of_its_own_inlined_and_hashed_before_the_viewers():
    html = build_viewer(SONG)
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    strum = (page.HERE / "strum.js").read_text(encoding="utf-8")
    viewer = (page.HERE / "viewer.js").read_text(encoding="utf-8")
    assert scripts == [strum, viewer]
    assert f"script-src {sha256_source(strum)} {sha256_source(viewer)};" in csp
    assert page.HERE / "strum.js" in page.BUILD_FILES
    # It loads nothing: no worklet module, no sample, no fetch.
    for word in ("addModule", "fetch(", "XMLHttpRequest", "import(", "new Audio(", "innerHTML", "eval("):
        assert word not in strum, word


def test_a_songbook_inlines_it_too():
    cho = "{title: A}\n{key: C}\n[C]la [G]la\n"
    html = build_songbook("B", [BookSong("A", "X", cho=cho, key="C")])
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert (page.HERE / "strum.js").read_text(encoding="utf-8") in scripts
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    assert all(sha256_source(s) in csp for s in scripts)


def test_the_settings_have_a_sound_row():
    html = build_viewer(SONG)
    row = re.search(r'<div class="row" id="sound-row".*?</div>', html, re.S)
    assert row and 'id="volumes"' in row.group(0)
    assert re.search(r'<div class="diagram" id="diagram"', html)


@in_chromium
def test_the_volume_is_a_setting_kept_in_the_address(tmp_path):
    url = written(tmp_path, build_viewer(SONG))
    chips = "[...document.querySelectorAll('#volumes .chip')].map((c) => [c.textContent, c.getAttribute('aria-pressed')])"
    dom = browser.dump_dom(url + "#vol=1", (390, 844))
    assert 'id="sound-row"' in dom and 'id="sound-row" hidden' not in dom
    with opened(tmp_path, url) as b:
        assert b.js(chips) == [["Off", "false"], ["Soft", "false"], ["Medium", "true"], ["Loud", "false"]]
        assert "vol" not in b.js("location.hash")
        b.click("#more")
        b.click("#volumes .chip:nth-child(4)")
        assert b.js(chips)[3] == ["Loud", "true"]
        assert "vol=3" in b.js("location.hash")
        assert look(b)["contexts"] == 0  # choosing it plays nothing
    with opened(tmp_path, url + "#vol=0") as b:
        assert b.js(chips)[0] == ["Off", "true"]
    with opened(tmp_path, url + "#vol=loud") as b:  # nothing the page can't do: its own
        assert b.js(chips)[2] == ["Medium", "true"]


# --- a tap, and nothing without one ------------------------------------------------------------------


@in_chromium
def test_a_tap_on_a_chord_makes_and_starts_one_audio_context_and_strums_its_shape(tmp_path):
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        assert look(b) == {"contexts": 0, "state": None, "resumes": 0, "started": 0, "heard": None}
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("!document.querySelector('#card').hidden")
        assert b.wait("spy.contexts.length === 1 && spy.contexts[0].state === 'running'")
        assert b.wait("document.documentElement.dataset.heard !== undefined")
        first = look(b)
        assert first["heard"] == C_OPEN
        assert b.wait("spy.started.length === 5")  # a note a string played, the muted one silent

        # Its card's diagram strums it again, in the same context; the sound before it stops.
        tap(b, "#diagram")
        assert b.wait("spy.started.length === 10")
        again = look(b)
        assert again["contexts"] == 1 and again["heard"] == C_OPEN
        assert b.js("spy.started.slice(0, 5).every((s) => spy.stopped.has(s))")  # one sound at a time

        # Another chord: its own notes.
        tap(b, '#sheet .c[data-c="2"]')
        assert b.wait("document.querySelector('#card-name').textContent === 'Am'")
        assert b.wait("spy.started.length > 10")
        assert look(b)["heard"] == "110.00 164.81 220.00 261.63 329.63"  # x02210: A2 E3 A3 C4 E4
        assert look(b)["contexts"] == 1


@in_chromium
def test_the_shape_is_played_at_the_capo_so_it_sounds_the_song(tmp_path):
    # With the capo on 3, C is played as an A shape: what sounds is a C chord all the same.
    with opened(tmp_path, written(tmp_path, build_viewer(SONG)) + "#capo=3") as b:
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("document.querySelector('#card-name').textContent === 'A'")
        assert b.wait("document.documentElement.dataset.heard !== undefined")
        assert look(b)["heard"] == C_AS_A_SHAPE_CAPO_3
        # The next shape, then the diagram: the shape shown is the one played.
        b.click("#next")
        tap(b, "#diagram")
        assert b.wait(f"document.documentElement.dataset.heard !== {json.dumps(C_AS_A_SHAPE_CAPO_3)}")


@in_chromium
def test_the_strip_and_the_keyboard_play_it_too(tmp_path):
    with opened(tmp_path, written(tmp_path, build_viewer(SONG)), width=1000, height=800, mobile=False) as b:
        b.click("#more")
        b.click("#strip-toggle")
        b.click("#strip button:nth-child(2)")  # G: 320003
        assert b.wait("document.documentElement.dataset.heard === '98.00 123.47 146.83 196.00 246.94 392.00'")
        b.js("document.querySelector('#diagram').focus()")
        b.js("delete document.documentElement.dataset.heard")
        key(b, "Enter", 13)
        assert b.wait("document.documentElement.dataset.heard !== undefined")
        assert b.js("document.querySelector('#diagram').getAttribute('role')") == "button"
        assert look(b)["contexts"] == 1


@in_chromium
def test_nothing_sounds_without_a_tap(tmp_path):
    # The card opened by the address, a shape changed, the settings opened: no sound, no AudioContext.
    with opened(tmp_path, written(tmp_path, build_viewer(SONG)) + "#chord=0") as b:
        assert b.wait("!document.querySelector('#card').hidden")
        b.js("document.querySelector('#next').click()")
        time.sleep(0.3)
        assert look(b) == {"contexts": 0, "state": None, "resumes": 0, "started": 0, "heard": None}
        # Nor does the script itself start one when no gesture asked for it.
        assert b.js("window.caracoleSound.strum([\"x32010\", \"032010\", 1, []], {capo: 0})") is False
        assert b.js("window.caracoleSound.play([{position: [\"x32010\", \"032010\", 1, []]}]).playing") is False
        assert look(b)["contexts"] == 0


@in_chromium
def test_with_the_sound_off_a_tap_opens_the_card_alone(tmp_path):
    with opened(tmp_path, written(tmp_path, build_viewer(SONG)) + "#vol=0") as b:
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("!document.querySelector('#card').hidden")
        time.sleep(0.3)
        assert look(b)["contexts"] == 0 and look(b)["heard"] is None
        assert b.js("document.querySelector('#diagram').getAttribute('role')") is None


@in_chromium
def test_hidden_it_falls_silent_and_the_next_tap_resumes_it(tmp_path):
    hide = """(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "%s" });
      document.dispatchEvent(new Event("visibilitychange"));
    })()"""
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("spy.contexts.length === 1 && spy.contexts[0].state === 'running'")
        b.js(hide % "hidden")
        assert b.wait("spy.contexts[0].state === 'suspended'")
        assert b.js("spy.started.every((s) => spy.stopped.has(s))")  # nothing plays in the background
        b.js(hide % "visible")
        time.sleep(0.3)
        assert look(b)["state"] == "suspended"  # back in view, still silent: nothing plays on its own
        resumes = look(b)["resumes"]
        b.js("delete document.documentElement.dataset.heard")
        tap(b, "#diagram")
        assert b.wait("spy.contexts[0].state === 'running'")
        assert look(b)["resumes"] > resumes and look(b)["contexts"] == 1
        assert b.wait("document.documentElement.dataset.heard !== undefined")


@in_chromium
def test_silent_a_while_it_lets_the_audio_sleep_until_the_next_tap(tmp_path):
    # Once the strum has rung out and two seconds more have passed, the context is suspended (a phone's
    # audio may sleep); the next tap resumes it, in the same context.
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("spy.contexts.length === 1 && spy.contexts[0].state === 'running'")
        assert b.wait("spy.contexts[0].state === 'suspended'", 20)
        b.js("delete document.documentElement.dataset.heard")
        tap(b, "#diagram")
        assert b.wait("spy.contexts[0].state === 'running'")
        assert b.wait(f"document.documentElement.dataset.heard === {json.dumps(C_OPEN)}")
        assert look(b)["contexts"] == 1


@in_chromium
def test_served_in_a_sandbox_it_plays_too(tmp_path):
    html = build_viewer(SONG).encode("utf-8")

    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", viewer_csp(html))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        with opened(tmp_path, f"http://127.0.0.1:{server.server_port}/Artist/Title/sheet.html#vol=3") as b:
            assert b.js("window.origin") == "null"  # sandboxed: an origin of its own
            tap(b, '#sheet .c[data-c="0"]')
            assert b.wait("spy.contexts.length === 1 && spy.contexts[0].state === 'running'")
            assert b.wait(f"document.documentElement.dataset.heard === {json.dumps(C_OPEN)}")
            assert "vol=3" in b.js("location.hash")
    finally:
        server.shutdown()
        server.server_close()


@in_chromium
def test_a_songbooks_song_plays_its_chords(tmp_path):
    cho = "{title: A}\n{key: C}\n[C]la la [G]la\n"
    url = written(tmp_path, build_songbook("B", [BookSong("A", "X", cho=cho, key="C")]), "songbook.html")
    with opened(tmp_path, url + "#song-1") as b:
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait(f"document.documentElement.dataset.heard === {json.dumps(C_OPEN)}")


# --- the synthesis, and what a Harmony panel calls ------------------------------------------------------


@in_chromium
def test_a_plucked_note_is_in_tune_and_dies_away(tmp_path):
    # The fundamental of each string's note, found by autocorrelation, within two cents of its pitch; the
    # sound fades out, never ends on a click.
    measure = """((hz, rate) => {
      const s = window.caracoleSound.pluck(hz, rate, 1.0);
      const from = Math.round(rate * 0.2), n = Math.round(rate * 0.3);
      const at = (lag) => { let sum = 0; for (let i = from; i < from + n; i++) sum += s[i] * s[i + lag]; return sum; };
      const period = rate / hz;
      let best = 0, lag = 0;
      for (let l = Math.floor(period * 0.9); l <= Math.ceil(period * 1.1); l++) { const v = at(l); if (v > best) { best = v; lag = l; } }
      const a = at(lag - 1), b = at(lag), c = at(lag + 1);
      const exact = lag + (a - c) / (2 * (a - 2 * b + c));
      const peak = (i0, i1) => { let m = 0; for (let i = i0; i < i1; i++) m = Math.max(m, Math.abs(s[i])); return m; };
      return { cents: 1200 * Math.log2((rate / exact) / hz), early: peak(0, rate * 0.1), late: peak(rate * 0.9, rate),
               last: Math.abs(s[s.length - 1]), length: s.length };
    })(%s, %s)"""
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        for hz in (82.41, 110.0, 146.83, 196.0, 246.94, 329.63, 659.26):
            for rate in (44100, 48000):
                found = b.js(measure % (hz, rate))
                assert abs(found["cents"]) < 2, (hz, rate, found)
                assert found["length"] == rate
                assert found["late"] < found["early"] / 2, (hz, rate, found)
                assert found["last"] < 1e-3


@in_chromium
def test_the_notes_of_a_voicing_at_a_capo(tmp_path):
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        notes = "window.caracoleSound.notes(%s, %d)"
        assert b.js(notes % ('["x32010", "032010", 1, []]', 0)) == [48, 52, 55, 60, 64]
        assert b.js(notes % ('["x02220", "001230", 1, []]', 3)) == [48, 55, 60, 64, 67]
        # A shape up the neck counts from its base fret: Bm at the 2nd fret (x13321 from fret 2).
        assert b.js(notes % ('["x13321", "013421", 2, [1]]', 0)) == [47, 54, 59, 62, 66]
        assert b.js(notes % ('["xxxxxx", "000000", 1, []]', 0)) == []
        assert b.js(notes % ("null", 0)) == []
        assert b.js("window.caracoleSound.frequencies([\"x32010\", \"032010\", 1, []], 0)") == [
            pytest.approx(float(f), abs=0.01) for f in C_OPEN.split()]


@in_chromium
def test_a_progression_plays_a_chord_a_bar_at_its_tempo_and_stops(tmp_path):
    progression = """window.played = []; window.ended = null;
      window.playing = window.caracoleSound.play([
        { position: ["x32010", "032010", 1, []], capo: 0 },
        null,
        { position: ["320003", "210003", 1, []], capo: 0 },
      ], { bpm: 480, beats: 2, onChord: (i) => played.push([i, performance.now()]), onEnd: (done) => { ended = done; } });
      window.playing.playing"""
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        # Run as a tap would run it.
        started = b.send("Runtime.evaluate", expression=progression, userGesture=True, returnByValue=True)
        assert started["result"]["value"] is True
        assert b.wait("ended !== null", 5)
        assert b.js("ended") is True
        assert [i for i, _ in b.js("played")] == [0, 1, 2]  # the rest (a chord theory can't read) has its bar too
        # A strum a beat, on the context's clock: C's two (5 strings each), the bar of silence, G's two (6).
        when = b.js("spy.started.map((s) => s.when)")
        beat = 60 / 480
        assert len(when) == 22
        strums = [when[0], when[5], when[10], when[16]]
        assert [t - when[0] for t in strums] == pytest.approx([0, beat, 4 * beat, 5 * beat])
        assert when[1] - when[0] == pytest.approx(0.022)  # string after string
        assert look(b)["contexts"] == 1
        assert look(b)["heard"] == "98.00 123.47 146.83 196.00 246.94 392.00"

        # Stopped: it ends at once, as not done, and every sound stops; a tap's strum stops it too.
        b.send("Runtime.evaluate", expression=progression.replace("bpm: 480", "bpm: 60"), userGesture=True)
        assert b.wait("played.length >= 1", 5)
        b.js("playing.stop()")
        assert b.js("ended") is False
        assert b.js("playing.playing") is False
        assert b.js("spy.started.every((s) => spy.stopped.has(s) || spy.ended.has(s))")
        b.send("Runtime.evaluate", expression=progression.replace("bpm: 480", "bpm: 60"), userGesture=True)
        assert b.wait("played.length >= 1", 5)
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("ended === false")
