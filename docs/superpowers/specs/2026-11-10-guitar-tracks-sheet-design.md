# The Guitar Pro page's tracks on a phone: one button, a sheet

The owner's ask (2026-11-10): on a phone, the Guitar Pro page's tracks sit in one row of pills that scrolls
sideways, which is cumbersome when a file has many tracks. Of five arrangements shown as phone mockups
(`.superpowers/brainstorm/…/track-pills.html`), the owner picked **B: one button, a sheet of tracks**.

## Approaches

- A, two columns folded ("+ N more"): closest to today, but the bar grows while you play and the fold is one more
  tap.
- **B, one button and a sheet (picked)**: the bar keeps one short line; every track is a full-width row under the
  thumb; several are shown with ticks, no long press.
- C, one pill with ‹ ›: the smallest bar, but showing two tracks together still needs a list.
- D, grouped by family: everything visible, but the tallest bar.
- E, a rail down the edge: initials only, and a long press for anything but showing.

## The design

- **Where**: under 600 px, the page's phone width (guitar.css's `max-width: 599px`). A wider screen keeps today's
  wrapped chips, long press and all: they never scroll there. *(My call: the ask is about the phone.)*
- **The bar's second row** is one full-width button: the track shown ("Lead Guitar"; two shown, "Lead Guitar + 1"),
  then "9 tracks ▴". A score of one track has no button, as it has no chips today.
- **The sheet**: a modal `<dialog>` that slides up from the bottom, at most about 70 % of the screen, its list
  scrolling inside it; a grip, "Tracks" and **Done** at its top. One row a track, 44 px at least: a tick (shown), its
  name and kind ("6 strings", "no tab", as the chips say them), and the speaker on the right (muted: red, the name
  struck through, as the chips). Done, a tap outside it, Escape and Android's Back close it.
- **What a tap does**: a tick adds or takes away a track from those shown, several at once; the last one shown can't
  be unticked (as today: the last stays). A speaker mutes or unmutes at once, playing or not. The tracks shown are
  drawn when the sheet closes, once, not on each tick. *(My call: alphaTab redraws the whole score for a change of
  tracks, which takes a moment on a phone.)*
- **Both caracoles**: guitar.js and guitar.css are the phone's too (`:server` copies them), so the app gets the sheet
  with no Kotlin change; tests/conformance/vectors/web/guitar.jsonl is regenerated with the page's new bytes.

## Non-goals

- No change on a wide screen, to playback, the tempo, Tab or Score, or the score itself.
- No grouping, reordering or renaming of tracks.

## Left to the builder

- Tests first, in test_web_guitar_browser.py at a phone's width: the button names the track shown; the sheet opens,
  a second tick then Done shows both (`data-track`), the last tick stays; a speaker mutes from the sheet; with many
  tracks the sheet scrolls and the page never scrolls sideways; a wide screen still has its chips and long press.
- The docs that describe the tracks: guitar_page.py's docstring, guitar.css's and guitar.js's comments, docs/usage.md's
  Guitar Pro page, android/README.md's Guitar Pro.
- The wording branch (feature/wording) words the sheet's few new texts later.
