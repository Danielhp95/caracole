"""caracole.viewer: hear a chord (strum.js, viewer.js): the voicing a chord's card shows, strummed in Web Audio.

A tap on a chord's name (in the sheet or the strip) or on its card's diagram strums the shape shown, at
the capo, in standard tuning, by a plucked-string synthesis (Karplus-Strong) that loads nothing. Nothing
sounds without a tap: the AudioContext is made on the first one, and one the browser suspended (the page
was hidden) is resumed on the next. One sound at a time. The volume is a setting (``vol`` in the address).

The page writes the frequencies it strummed last on ``<html data-heard>`` for these tests. They count
the AudioContexts the page makes with a script the browser runs before the page's own
(``Page.addScriptToEvaluateOnNewDocument``, which the page's policy doesn't stop), in a Chromium of their
own on real time (helpers/browser.py's ``Browser``). A progression's tests record every note the page
schedules and every timer it sets the same way (``SCHEDULE``): it plays in its order at its tempo, and once
stopped nothing of it sounds and no timer of strum.js is left.
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
      this.at = this.context.currentTime;
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
    instruments = (page.HERE / "instruments.js").read_text(encoding="utf-8")
    winds = (page.HERE / "winds.js").read_text(encoding="utf-8")
    overlay = (page.HERE / "overlay.js").read_text(encoding="utf-8")
    viewer = (page.HERE / "viewer.js").read_text(encoding="utf-8")
    assert scripts == [strum, overlay, instruments, winds, viewer]
    assert (f"script-src {sha256_source(strum)} {sha256_source(overlay)} {sha256_source(instruments)} "
            f"{sha256_source(winds)} {sha256_source(viewer)};") in csp
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
    row = re.search(r'<span id="sound-row" hidden>.*?</span></span>', html, re.S)
    assert row and 'id="volumes"' in row.group(0) and 'role="group" aria-label="Strum"' in row.group(0)
    assert re.search(r'<div class="diagram" id="diagram"', html)


@in_chromium
def test_the_volume_is_a_setting_kept_in_the_address(tmp_path):
    url = written(tmp_path, build_viewer(SONG))
    chips = ("[...document.querySelectorAll('#volumes > button')].map((c) => [c.getAttribute('aria-label'), "
             "c.getAttribute('aria-pressed')])")
    dom = browser.dump_dom(url + "#vol=1", (390, 844))
    assert 'id="sound-row"' in dom and 'id="sound-row" hidden' not in dom
    with opened(tmp_path, url) as b:
        assert b.js(chips) == [["Off", "false"], ["Soft", "false"], ["Medium", "true"], ["Loud", "false"]]
        assert "vol" not in b.js("location.hash")
        b.click("#more")
        b.click("#volumes > button:nth-child(4)")
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
        # A strum a beat, on the context's clock: C's two (5 strings each), the bar of silence, G's two (6);
        # later only where one came late (the machine busy: scheduled at the soonest, 0.05 s ahead), which a
        # beat of the bar of silence may be too, never sooner.
        when, at = zip(*b.js("spy.started.map((s) => [s.when, s.at])"))
        beat = 60 / 480
        assert len(when) == 22
        for a, b2 in ((0, 5), (10, 16)):
            gap = when[b2] - when[a]
            assert gap == pytest.approx(beat) or (gap > beat and when[b2] - at[b2] <= 0.05 + 1e-6), (gap, at[b2])
        assert when[10] - when[5] >= 3 * beat - 1e-6
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


# --- a progression in its order, and nothing after it stops ---------------------------------------------
# What the page schedules, for these tests (a script run before the page's own, as SPY): every note started,
# with its strum (``strum``: the notes started through one gain node, as strum.js plays a strum), its time on
# the context's clock (``when``), the clock when it was scheduled (``at``), what <html
# data-heard> said just before it (the page writes a strum's frequencies once its notes are started: so the
# strum before its own), when it is to stop (the last stop() asked, unless it had stopped already: at once
# for a time gone by), when its sound was cut off (the node it plays through disconnected); and the timers
# alive, each with the line of the page that set it. ``strumsNow()`` groups the notes into strums as
# ``strums`` does, for a test to wait for the ones it needs. And two things a slow device does, on demand:
# with ``log.hold`` an array, each resume() the page asks for waits there until the test lets it go
# (``woken``), as a context takes a while to wake; ``endNow()`` runs at once every note's "ended" not come yet,
# as a busy machine brings them late.
SCHEDULE = """(() => {
  const Real = window.AudioContext;
  const log = window.log = { context: null, notes: [], timers: new Map(), hold: null };
  window.AudioContext = class extends Real {
    constructor(...args) { super(...args); log.context = this; }
    resume() {
      if (!log.hold) return super.resume();
      return new Promise((ok, no) => log.hold.push(() => super.resume().then(ok, no)));
    }
  };
  const ended = Object.getOwnPropertyDescriptor(AudioScheduledSourceNode.prototype, "onended");
  Object.defineProperty(AudioScheduledSourceNode.prototype, "onended", {
    configurable: true, enumerable: true, get() { return ended.get.call(this); },
    set(fn) {
      const node = this;
      node.ended = false;
      ended.set.call(this, typeof fn !== "function" ? fn : function (...args) {
        if (node.ended) return undefined;
        node.ended = true;
        return fn.apply(this, args);
      });
    },
  });
  window.endNow = () => log.notes.forEach((n) => { if (n.node.ended === false) n.node.onended(new Event("ended")); });
  const connect = AudioNode.prototype.connect, disconnect = AudioNode.prototype.disconnect;
  AudioNode.prototype.connect = function (to, ...rest) {
    this.through = to;
    return connect.call(this, to, ...rest);
  };
  AudioNode.prototype.disconnect = function (...args) {
    if (this.cut === undefined) this.cut = this.context.currentTime;
    return disconnect.apply(this, args);
  };
  const start = AudioBufferSourceNode.prototype.start, strumOf = new WeakMap();
  let strums = 0;
  AudioBufferSourceNode.prototype.start = function (when, ...rest) {
    const through = this.through || this;
    if (!strumOf.has(through)) strumOf.set(through, (strums += 1));
    this.note = { when, at: this.context.currentTime, before: document.documentElement.dataset.heard || null,
      stop: null, node: this, strum: strumOf.get(through) };
    log.notes.push(this.note);
    return start.call(this, when, ...rest);
  };
  const stop = AudioScheduledSourceNode.prototype.stop;
  AudioScheduledSourceNode.prototype.stop = function (when) {
    const now = this.context.currentTime;
    if (this.note && !(this.note.stop !== null && this.note.stop <= now)) this.note.stop = Math.max(when || 0, now);
    return stop.call(this, when);
  };
  window.notesNow = () => log.notes.map((n) => {
    const cuts = [n.node.cut, n.node.through && n.node.through.cut].filter((t) => t !== undefined);
    return { strum: n.strum, when: n.when, at: n.at, before: n.before, stop: n.stop,
      cut: cuts.length ? Math.min(...cuts) : null };
  });
  window.strumsNow = () => {
    const found = [];
    log.notes.forEach((n, k) => {
      const last = found[found.length - 1];
      if (last && last.strum === n.strum) last.notes += 1;
      else found.push({ strum: n.strum, when: n.when, at: n.at, first: k, notes: 1 });
    });
    return found;
  };
  const set = window.setTimeout, clear = window.clearTimeout;
  window.setTimeout = function (fn, ms, ...rest) {
    const caller = (new Error().stack || "").split("\\n")[2] || "";
    const line = Number((caller.match(/:(\\d+):\\d+\\)?$/) || [0, 0])[1]);
    const id = set.call(window, (...args) => {
      log.timers.delete(id);
      if (typeof fn === "function") fn(...args);
    }, ms, ...rest);
    log.timers.set(id, line);
    return id;
  };
  window.clearTimeout = function (id) {
    log.timers.delete(id);
    return clear.call(window, id);
  };
})()"""

G_OPEN = "98.00 123.47 146.83 196.00 246.94 392.00"  # 320003
AM_OPEN = "110.00 164.81 220.00 261.63 329.63"  # x02210
F_BARRE = "87.31 130.81 174.61 220.00 261.63 349.23"  # 133211
POSITIONS = {C_OPEN: '["x32010", "032010", 1, []]', G_OPEN: '["320003", "210003", 1, []]',
             AM_OPEN: '["x02210", "002310", 1, []]', F_BARRE: '["133211", "134211", 1, [1]]'}
# Two sections: the verse I–V–vi–IV four times, the chorus IV–V–I–vi twice (▶ 0 and ▶ 1 in the Harmony panel).
SECTIONS = ("{title: Sections}\n{artist: Synthetic}\n{key: C}\n{comment: Verse}\n"
            + "[C]made [G]up [Am]words [F]here\n" * 4 + "\n{comment: Chorus}\n" + "[F]and [G]the [C]cho[Am]rus\n" * 2)
VERSE = [C_OPEN, G_OPEN, AM_OPEN, F_BARRE] * 4
CHORUS = [F_BARRE, G_OPEN, C_OPEN, AM_OPEN] * 2
GAP = 0.022  # strum.js: a string after the one before it
FADE = 0.3  # the most a sound stopped takes to fade out (strum.js: DAMP, eight times)
LEAD = 0.05  # strum.js: the soonest a strum is scheduled on the clock, as one that came late is


@contextmanager
def scheduled(tmp_path: Path, cho: str, address: str = "", **size):
    """The viewer of ``cho`` with SCHEDULE run before its script, and the lines its strum.js takes in the page."""
    html = build_viewer(cho)
    strum = (page.HERE / "strum.js").read_text(encoding="utf-8")
    first = html[:html.index(strum)].count("\n") + 1
    with Browser(Path(tempfile.mkdtemp(prefix="profile-", dir=tmp_path)), **({"width": 390, "height": 844,
                                                                             "mobile": True} | size)) as b:
        b.send("Page.addScriptToEvaluateOnNewDocument", source=SCHEDULE)
        b.open(written(tmp_path, html) + address)
        assert b.wait("document.documentElement.dataset.ready === '1'")
        b.strum_lines = range(first, first + strum.count("\n") + 1)
        yield b


def tapped(b: Browser, expression: str):
    """``expression``'s value, run as a tap runs: with the user's activation."""
    found = b.send("Runtime.evaluate", expression=expression, userGesture=True, returnByValue=True)
    assert "exceptionDetails" not in found, found
    return found["result"].get("value")


def strums(b: Browser) -> list[dict]:
    """The strums the page scheduled, in order: each its notes (started through one gain node, one a GAP after
    the one before), its time, the clock when it was scheduled, its first note's place among all the page scheduled (``first``), and what it
    strummed (what the next one's first note found the page saying it strummed last, or what it says now)."""
    found: list[dict] = []
    notes, last_heard = b.js("[notesNow(), document.documentElement.dataset.heard || null]")
    for k, note in enumerate(notes):
        last = found[-1] if found else None
        if last and last["notes"][0]["strum"] == note["strum"]:
            assert note["when"] == pytest.approx(last["when"] + GAP * len(last["notes"])), (last, note)
            last["notes"].append(note)
        else:
            found.append({"when": note["when"], "at": note["at"], "first": k, "notes": [note]})
    for k, strum in enumerate(found):
        strum["heard"] = found[k + 1]["notes"][0]["before"] if k + 1 < len(found) else last_heard
    return found


def sounds(note: dict) -> bool:
    """Whether a note is heard at all: stopped or cut off only once it began."""
    return all(t is None or t > note["when"] for t in (note["stop"], note["cut"]))


def ends(note: dict) -> float:
    return min(t for t in (note["stop"], note["cut"], note["when"] + 2.6) if t is not None)


def heard_after(found: list[dict], t: float) -> list[dict]:
    """The strums of ``found`` some note of which is heard after the time ``t``."""
    return [s for s in found if any(sounds(n) and ends(n) > t for n in s["notes"])]


def silent_after(b: Browser, t: float) -> None:
    """Nothing the page scheduled sounds once ``t`` is past but a fade: no note due after it is heard at all."""
    for strum in strums(b):
        for note in strum["notes"]:
            if note["when"] > t + 0.01:
                assert not sounds(note), (t, strum["heard"], note)
            else:
                assert ends(note) <= t + FADE + 1e-6, (t, strum["heard"], note)


def strum_timers(b: Browser) -> list[int]:
    return [line for line in b.js("[...log.timers.values()]") if line in b.strum_lines]


def on_the_beat(found: list[dict], beat) -> list[float]:
    """Each gap from a strum of ``found`` to the next is ``beat(next)`` seconds, or longer only where the next
    came late (a busy page, a busy machine: scheduled at the soonest, LEAD ahead of the clock), never shorter;
    the gaps."""
    gaps = []
    for a, b2 in zip(found, found[1:]):
        gap, want = b2["when"] - a["when"], beat(b2)
        assert abs(gap - want) < 1e-6 or (gap > want and b2["when"] - b2["at"] <= LEAD + 1e-6), (a, b2, want)
        gaps.append(gap)
    return gaps


# A moment when the page has scheduled a strum ahead of its time on the clock: what the tests stop it in.
AHEAD = "strumsNow().some((s) => s.when > log.context.currentTime + 0.05)"


def when_ahead(b: Browser, action: str) -> tuple[float, float]:
    """Waits for a strum scheduled ahead, then runs ``action`` as a tap at once: the clock just before it and
    just after (a busy machine may take a while between), and in ``log.mark`` the notes scheduled before it
    (the clock may read the same a moment after)."""
    for _ in range(400):
        found = tapped(b, f"(() => {{ const t = log.context.currentTime; if (!strumsNow().some((s) => s.when > t + 0.05)) "
                          f"return null; log.mark = log.notes.length; {action}; return [t, log.context.currentTime]; }})()")
        if found is not None:
            return found[0], found[1]
        time.sleep(0.01)
    raise AssertionError("no strum scheduled ahead")


def harmony_at_200_bpm(b: Browser) -> None:
    tapped(b, "document.getElementById('more').click(); document.getElementById('harmony-open').click();"
              "for (let k = 0; k < 24; k++) document.getElementById('bpm-up').click()")
    assert b.js("document.getElementById('bpm').textContent") == "200"


PLAY = "document.querySelectorAll('#harmony .prog-play')[%d].click()"


@in_chromium
def test_a_progression_plays_in_its_order_across_its_repeats_even_when_the_page_is_busy(tmp_path):
    # C G Am F three times, a strum a bar at 600 bpm; the page busy for 0.7 s after the fourth: the rest comes
    # later, in its order, a beat apart, never late and crammed together.
    with scheduled(tmp_path, SONG) as b:
        cycle = [C_OPEN, G_OPEN, AM_OPEN, F_BARRE]
        chords = ", ".join("{position: %s, capo: 0}" % POSITIONS[c] for c in cycle * 3)
        assert tapped(b, f"""window.marked = []; window.ended = null;
          window.caracoleSound.play([{chords}], {{ bpm: 600, beats: 1, onChord: (i) => marked.push(i),
            onEnd: (done) => {{ ended = done; }} }}).playing""") is True
        assert b.wait("marked.length >= 4", 5)
        b.js("(() => { const t = performance.now(); while (performance.now() - t < 700) {} })()")
        assert b.wait("ended !== null", 10)
        found = strums(b)
        assert b.js("ended") is True and b.js("marked") == list(range(12))
    assert [s["heard"] for s in found] == cycle * 3
    beat = 60 / 600
    for strum in found:  # scheduled ahead of its time, never after it (but by a moment the machine stops the page)
        assert strum["when"] >= strum["at"] - 0.01, strum
    gaps = on_the_beat(found, lambda _: beat)
    assert any(gap > beat + 1e-6 for gap in gaps)  # where the page was busy
    assert sum(abs(gap - beat) < 1e-6 for gap in gaps) >= 6  # the tempo elsewhere


@in_chromium
def test_a_second_play_stops_the_first_and_nothing_of_it_sounds_after(tmp_path):
    with scheduled(tmp_path, SECTIONS) as b:
        harmony_at_200_bpm(b)
        tapped(b, PLAY % 0)  # the verse
        assert b.wait("notesNow().length >= 15")
        t, after = when_ahead(b, PLAY % 1)  # the chorus, while a strum of the verse waits for its time
        mark = b.js("log.mark")
        assert b.wait("strumsNow().filter((s) => s.first >= log.mark).length >= 6", 15)
        found = strums(b)
        label = b.js("[...document.querySelectorAll('#harmony .prog-play')].map((p) => p.textContent)")
    verse = [s for s in found if s["first"] < mark]
    chorus = [s for s in found if s["first"] >= mark]
    assert any(s["when"] > t + 0.05 for s in verse)  # one of the verse's was waiting for its time
    for strum in verse:  # it never sounds, and the one ringing fades out
        for note in strum["notes"]:
            assert not sounds(note) if note["when"] > after + 0.01 else ends(note) <= after + FADE + 1e-6, note
    assert not [s for s in heard_after(found, after + FADE) if s["first"] < mark]
    assert len(chorus) >= 6 and [s["heard"] for s in chorus] == [c for c in CHORUS for _ in range(4)][:len(chorus)]
    assert label == ["▶", "■"]


@in_chromium
def test_play_twice_at_once_plays_the_second_alone(tmp_path):
    with scheduled(tmp_path, SECTIONS) as b:
        harmony_at_200_bpm(b)
        tapped(b, f"{PLAY % 0}; {PLAY % 1}")
        assert b.wait("strumsNow().length >= 5", 15)
        found = strums(b)
    heard = [s["heard"] for s in found if any(sounds(n) for n in s["notes"])]
    assert len(heard) >= 4 and heard == [c for c in CHORUS for _ in range(4)][:len(heard)]  # never the verse's C


@in_chromium
def test_closing_the_panel_stops_every_sound_and_leaves_no_timer(tmp_path):
    with scheduled(tmp_path, SECTIONS) as b:
        harmony_at_200_bpm(b)
        tapped(b, PLAY % 0)
        assert b.wait("notesNow().length >= 15")
        _, t = when_ahead(b, "document.querySelector('#harmony [data-close]').click()")
        time.sleep(0.6)
        silent_after(b, t)
        before = len(b.js("notesNow()"))
        time.sleep(0.5)
        assert len(b.js("notesNow()")) == before  # nothing more is scheduled
        assert b.wait("log.context.state === 'suspended'", 8)  # silent, it lets the device's audio sleep
        assert strum_timers(b) == []

        # A chord's strum, ringing when the panel closes, stops with it.
        tapped(b, "document.getElementById('more').click(); document.getElementById('harmony-open').click()")
        tapped(b, "document.querySelector('#sheet .c[data-c=\"1\"]').click()")
        assert b.wait("log.context.state === 'running' && document.documentElement.dataset.heard === %s" % json.dumps(G_OPEN))
        t = tapped(b, "document.querySelector('#harmony [data-close]').click(); log.context.currentTime")
        silent_after(b, t)


@in_chromium
def test_hidden_or_left_the_progression_stops_and_nothing_plays_when_it_is_back(tmp_path):
    with scheduled(tmp_path, SECTIONS) as b:
        harmony_at_200_bpm(b)
        tapped(b, PLAY % 0)
        assert b.wait("notesNow().length >= 15")
        assert b.wait(AHEAD)
        other = b._send("Target.createTarget", url="about:blank")["targetId"]
        b._send("Target.activateTarget", targetId=other)  # another tab
        assert b.wait("document.visibilityState === 'hidden' && log.context.state === 'suspended'")
        silent_after(b, b.js("log.context.currentTime"))
        b.js("endNow()")  # the notes cut tell they ended only now, as on a busy machine: still no timer
        assert strum_timers(b) == []
        assert b.js("document.querySelectorAll('#harmony .prog-play')[0].textContent") == "▶"
        before = len(b.js("notesNow()"))
        b._send("Target.closeTarget", targetId=other)
        assert b.wait("document.visibilityState === 'visible'")
        time.sleep(0.5)
        assert len(b.js("notesNow()")) == before and b.js("log.context.state") == "suspended"

        # Left (pagehide, as Back or a link from a server's sandbox): the same.
        tapped(b, PLAY % 1)
        assert b.wait("log.context.state === 'running'")
        assert b.wait(AHEAD)
        b.js("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        assert b.wait("log.context.state === 'suspended'")
        silent_after(b, b.js("log.context.currentTime"))
        b.js("endNow()")
        assert strum_timers(b) == []


def asleep_and_slow_to_wake(b: Browser) -> int:
    """The sound stopped, and once it has faded out the context put to sleep by the page (two seconds idle,
    nothing left ringing), the next resume() it is asked for held until ``woken``; the notes scheduled so far."""
    b.js("window.caracoleSound.stop()")
    assert b.wait("log.context.state === 'suspended' && strumsNow().length > 0", 10)
    b.js("log.hold = []")
    return len(b.js("notesNow()"))


def woken(b: Browser) -> None:
    """Every resume() held goes on (and none is held after), and what the page does once they have."""
    assert b.js("log.hold.length") >= 1  # the page asked for one: what it plays waits for the context
    b.js("(async () => { const held = log.hold; log.hold = null; await Promise.all(held.map((go) => go()));"
         " await new Promise((done) => setTimeout(done, 50)); })()")


CHORD = "document.querySelector('#sheet .c[data-c=\"%d\"]').click()"
OPEN_HARMONY = "document.getElementById('more').click(); document.getElementById('harmony-open').click()"


@in_chromium
def test_while_the_context_wakes_only_what_was_asked_last_sounds(tmp_path):
    with scheduled(tmp_path, SECTIONS) as b:
        tapped(b, OPEN_HARMONY)
        tapped(b, CHORD % 0)  # C: the context made, running at once
        assert b.wait("log.context !== null && log.context.state === 'running' && notesNow().length === 5")

        # G tapped, then the panel closed, before the context woke: once awake, nothing sounds, and it goes
        # back to sleep with no timer left.
        before = asleep_and_slow_to_wake(b)
        tapped(b, CHORD % 1)
        tapped(b, "document.querySelector('#harmony [data-close]').click()")
        woken(b)
        assert b.js("log.context.state") == "running" and len(b.js("notesNow()")) == before
        assert b.wait("log.context.state === 'suspended'", 8)
        assert strum_timers(b) == []

        # G tapped, then the verse's ▶: the verse alone, from its first chord.
        before = asleep_and_slow_to_wake(b)
        tapped(b, OPEN_HARMONY)
        tapped(b, CHORD % 1)
        tapped(b, PLAY % 0)
        woken(b)
        assert b.wait(f"strumsNow().filter((s) => s.first >= {before}).length >= 3", 15)
        found = [s for s in strums(b) if s["first"] >= before]
        tapped(b, PLAY % 0)  # ■
    assert [s["heard"] for s in found] == [c for c in VERSE for _ in range(4)][:len(found)]


@in_chromium
def test_hidden_while_the_context_wakes_it_goes_back_to_sleep(tmp_path):
    with scheduled(tmp_path, SECTIONS) as b:
        tapped(b, CHORD % 0)
        assert b.wait("log.context !== null && log.context.state === 'running' && notesNow().length === 5")
        before = asleep_and_slow_to_wake(b)
        tapped(b, CHORD % 1)
        other = b._send("Target.createTarget", url="about:blank")["targetId"]
        b._send("Target.activateTarget", targetId=other)  # another tab, before the context woke
        assert b.wait("document.visibilityState === 'hidden'")
        woken(b)  # awake out of sight: nothing sounds, and it sleeps again at once
        assert b.wait("log.context.state === 'suspended'", 1)
        assert len(b.js("notesNow()")) == before and strum_timers(b) == []


@in_chromium
def test_the_tempo_changed_as_it_plays_keeps_the_order_and_takes_the_new_beat(tmp_path):
    with scheduled(tmp_path, SECTIONS) as b:
        harmony_at_200_bpm(b)
        tapped(b, PLAY % 0)
        assert b.wait("notesNow().length >= 15")
        when_ahead(b, "for (let k = 0; k < 8; k++) document.getElementById('bpm-down').click()")  # 160 bpm
        mark = b.js("log.mark")
        assert b.wait("strumsNow().filter((s) => s.first >= log.mark).length >= 5", 15)
        found = strums(b)
        tapped(b, PLAY % 0)  # ■
        assert b.js("document.getElementById('bpm').textContent") == "160"
    assert [s["heard"] for s in found] == [c for c in VERSE for _ in range(4)][:len(found)]
    # The strums scheduled before the change keep 200 bpm's beat; from the last of them on, 160 bpm's.
    on_the_beat(found, lambda strum: 0.3 if strum["first"] < mark else 0.375)
    after = [b2["when"] - a["when"] for a, b2 in zip(found, found[1:]) if b2["first"] >= mark]
    assert len(after) >= 5 and sum(abs(gap - 0.375) < 1e-6 for gap in after) >= 2


# --- on each instrument (viewer/instruments.py): its strings, or a piano ------------------------------------------


def heard_for(inst, name: str, shift: int = 0) -> str:
    """What the page writes it strummed for the chord ``name``'s first shape on ``inst``, as Python shapes it."""
    from caracole.viewer.instruments import chord_shapes
    from caracole.viewer.theory import parse_chord
    from caracole.viewer.voicings import notes_of

    position = chord_shapes(inst, parse_chord(name), shift)[0]
    midis = position if inst.kind == "keys" else notes_of(position, inst.tuning)
    return " ".join(f"{440 * 2 ** ((m - 69) / 12):.2f}" for m in midis)


@in_chromium
@pytest.mark.parametrize("inst", ["ukulele", "ukulele-low-g", "baritone", "piano"])
def test_each_instrument_strums_its_own_notes(tmp_path, inst):
    from caracole.viewer.instruments import instrument

    with opened(tmp_path, written(tmp_path, build_viewer(SONG)) + "#inst=" + inst) as b:
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("document.documentElement.dataset.heard !== undefined")
        heard = look(b)["heard"]
    assert heard == heard_for(instrument(inst), "C")
    expected = {"ukulele": "392.00 261.63 329.63 523.25",  # 0003: G4 C4 E4 C5, the G string high
                "ukulele-low-g": "196.00 261.63 329.63 523.25",  # G3
                "baritone": "164.81 196.00 261.63 329.63",  # a ukulele's F shape, 2010, on D3 G3 B3 E4: E3 G3 C4 E4
                "piano": "130.81 261.63 329.63 392.00"}  # C3 in the bass; C4 E4 G4
    assert heard == expected[inst]


@in_chromium
def test_the_notes_of_a_voicing_on_any_tuning_and_a_pianos_as_they_are(tmp_path):
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        notes = "window.caracoleSound.notes(%s, %d, %s)"
        assert b.js(notes % ('["0003", "0003", 1, []]', 0, "[67, 60, 64, 69]")) == [67, 60, 64, 72]
        assert b.js(notes % ('["0003", "0003", 1, []]', 2, "[67, 60, 64, 69]")) == [69, 62, 66, 74]  # at the capo
        assert b.js(notes % ('["1343", "1243", 5, []]', 0, "[55, 60, 64, 69]")) == [60, 67, 72, 76]  # from fret 5
        assert b.js(notes % ('["0003", "0003", 1, []]', 0, "null")) == []  # four frets: no guitar's
        assert b.js(notes % ("[48, 60, 64, 67]", 0, "null")) == [48, 60, 64, 67]
        assert b.js("window.caracoleSound.voices") == ["guitar", "ukulele", "piano", "reed", "flute", "recorder"]


@in_chromium
def test_a_piano_note_is_in_tune_and_dies_away_and_a_ukuleles_rings_shorter_than_a_guitars(tmp_path):
    measure = """((hz, rate, make) => {
      const s = make(hz, rate);
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
    })(%s, %s, %s)"""
    strike = "(hz, rate) => window.caracoleSound.strike(hz, rate, 1.0)"
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        for hz in (87.31, 130.81, 261.63, 392.0, 659.26):
            for rate in (44100, 48000):
                found = b.js(measure % (hz, rate, strike))
                assert abs(found["cents"]) < 3, (hz, rate, found)
                assert found["length"] == rate and found["last"] < 1e-3
                assert found["late"] < found["early"] / 2, (hz, rate, found)
        for hz in (261.63, 392.0, 440.0):
            uke = b.js(measure % (hz, 48000, "(hz, rate) => window.caracoleSound.pluck(hz, rate, 1.0, 'ukulele')"))
            guitar = b.js(measure % (hz, 48000, "(hz, rate) => window.caracoleSound.pluck(hz, rate, 1.0)"))
            assert abs(uke["cents"]) < 2, (hz, uke)
            assert uke["late"] / uke["early"] < guitar["late"] / guitar["early"] / 2, (hz, uke, guitar)


@in_chromium
def test_a_progression_on_the_piano_strikes_each_chord_at_once_and_stops(tmp_path):
    from caracole.viewer.instruments import PIANO

    with scheduled(tmp_path, SECTIONS, "#inst=piano") as b:
        harmony_at_200_bpm(b)
        tapped(b, PLAY % 0)  # the verse: C G Am F
        assert b.wait("notesNow().length >= 24")
        notes = b.js("notesNow()")
        heard = b.js("document.documentElement.dataset.heard")
        _, t = when_ahead(b, "document.querySelector('#harmony [data-close]').click()")
        time.sleep(0.6)
        for note in b.js("notesNow()"):  # nothing due after it is heard, and what rang fades out
            assert not sounds(note) if note["when"] > t + 0.01 else ends(note) <= t + FADE + 1e-6, (t, note)
        assert b.wait("log.context.state === 'suspended'", 8)
        assert strum_timers(b) == []
    struck: dict[int, list[float]] = {}
    for note in notes:
        struck.setdefault(note["strum"], []).append(note["when"])
    firsts = [whens for _, whens in sorted(struck.items())][:6]
    assert all(len(whens) == 4 and max(whens) == min(whens) for whens in firsts)  # bass and triad, together
    assert heard in {heard_for(PIANO, name) for name in ("C", "G", "Am", "F")}


# --- the harmonica, the flute and the recorder (winds.js): a breath, not a pluck ------------------------------------


@in_chromium
def test_a_reeds_and_a_flutes_note_is_in_tune_held_and_ends_silent(tmp_path):
    # Held as long as it is blown, as a plucked string is not: as loud after half a second as as it began, then
    # faded out, never ending on a click; in tune within three cents (a flute's vibrato comes later).
    measure = """((hz, rate, voice) => {
      const s = window.caracoleSound.blow(hz, rate, 1.0, voice);
      const from = Math.round(rate * 0.2), n = Math.round(rate * 0.25);
      const at = (lag) => { let sum = 0; for (let i = from; i < from + n; i++) sum += s[i] * s[i + lag]; return sum; };
      const period = rate / hz;
      let best = 0, lag = 0;
      for (let l = Math.floor(period * 0.9); l <= Math.ceil(period * 1.1); l++) { const v = at(l); if (v > best) { best = v; lag = l; } }
      const a = at(lag - 1), b = at(lag), c = at(lag + 1);
      const exact = lag + (a - c) / (2 * (a - 2 * b + c));
      const rms = (t0, t1) => { let m = 0; const i0 = Math.round(rate * t0), i1 = Math.round(rate * t1);
        for (let i = i0; i < i1; i++) m += s[i] * s[i]; return Math.sqrt(m / (i1 - i0)); };
      return { cents: 1200 * Math.log2((rate / exact) / hz), early: rms(0.12, 0.22), held: rms(0.42, 0.52),
               last: Math.abs(s[s.length - 1]), length: s.length, top: Math.max(...s.map(Math.abs)) };
    })(%s, %s, %s)"""
    with opened(tmp_path, written(tmp_path, build_viewer(SONG))) as b:
        for voice in ("reed", "flute", "recorder"):
            for hz in (261.63, 392.0, 587.33, 1046.5):
                for rate in (44100, 48000):
                    found = b.js(measure % (hz, rate, json.dumps(voice)))
                    assert abs(found["cents"]) < 3, (voice, hz, rate, found)
                    assert found["length"] == rate and found["last"] < 1e-3 and found["top"] <= 1.0001
                    assert found["held"] > 0.8 * found["early"], (voice, hz, found)
        plucked = b.js(measure.replace("blow(hz, rate, 1.0, voice)", "pluck(hz, rate, 1.0)") % (587.33, 48000, '"guitar"'))
        assert plucked["held"] < 0.8 * plucked["early"]  # a plucked string dies away


@in_chromium
@pytest.mark.parametrize(("inst", "heard"), [
    ("harmonica", "261.63 329.63 392.00"),  # a song in C: a C harp, 1st position; C is blow 1–3, C4 E4 G4
    ("flute", "261.63 329.63 392.00"),  # C4 E4 G4, as read and as it sounds
    ("recorder", "523.25 659.26 783.99"),  # read C4 E4 G4, sounding an octave higher
])
def test_the_harmonica_and_the_winds_play_their_own_notes(tmp_path, inst, heard):
    with opened(tmp_path, written(tmp_path, build_viewer(SONG)) + "#inst=" + inst) as b:
        tap(b, '#sheet .c[data-c="0"]')
        assert b.wait("document.documentElement.dataset.heard !== undefined")
        assert look(b)["heard"] == heard


@in_chromium
def test_a_progression_on_the_harmonica_blows_or_draws_each_chord_at_once_and_stops(tmp_path):
    from caracole.viewer import harp
    from caracole.viewer.theory import parse_chord

    with scheduled(tmp_path, SECTIONS, "#inst=harmonica") as b:
        harmony_at_200_bpm(b)
        tapped(b, PLAY % 0)  # the verse: C G Am F, on a C harp
        assert b.wait("notesNow().length >= 9")
        notes = b.js("notesNow()")
        _, t = when_ahead(b, "document.querySelector('#harmony [data-close]').click()")
        time.sleep(0.6)
        for note in b.js("notesNow()"):  # nothing due after it is heard, and what rang fades out
            assert not sounds(note) if note["when"] > t + 0.01 else ends(note) <= t + FADE + 1e-6, (t, note)
        assert b.wait("log.context.state === 'suspended'", 8)
        assert strum_timers(b) == []
    blown: dict[int, list[float]] = {}
    for note in notes:
        blown.setdefault(note["strum"], []).append(note["when"])
    # C, blow 1–3, and G, draw 2–4, each three holes at once; Am and F, not on a C harp: bars of silence.
    assert blown and all(len(whens) == 3 and max(whens) == min(whens) for whens in blown.values())
    assert [harp.play(parse_chord(c), 0).kind for c in ("C", "G", "Am", "F")] == ["yes", "yes", "no", "no"]
