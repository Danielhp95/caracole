# A numeral's tooltip: the chord's notes, as a circle or on a keyboard

With the chord names showing numerals, hovering a numeral (or tapping it) opens the viewer's tooltip (`#tip`,
viewer.js `showTip`): one sentence (`explains`, "I: the 1st chord of G major, major (upper case)"), "In the key
of G (from the tab).", and a button to the chord's shapes. It names no note and shows nothing. The owner wants
something visual that shows which notes make the chord (a D7: D + F♯ + A + C).

## Decisions (the owner's, 2026-10-27)

Mockup (gitignored, in the main checkout): `.superpowers/brainstorm/2818486-1793122579/content/`
numeral-tip-directions.html. **C, the twelve-note circle, is the default view; A, notes and a keyboard, is the
second; an arrow or other indicator cycles between the two.** (The owner wrote "add 1": taken as the first
direction, A.)

## The tooltip, top to bottom

1. **Head**: the chord as the sheet names it now (big, "D7"), its numeral in its role's colour as the sheet draws
   it ("V7", dotted underline for one from outside the key), and its role in words at the right ("pull", "home",
   "away", in their colours; "outside the key" for a chord with no family).
2. **The line** (`explains`, as today) and, small and muted, "In the key of G" (today's `tip-key`).
3. **The picture**, one of two views:
   - **Circle** (default): the twelve notes as a clock, C at the top, each named as the page names notes in the
     key shown; the key's seven notes ringed, the others faint; the chord's notes as larger dots joined in pitch
     order into a shape in its role's colour; the root filled in the accent; a note from outside the key with a
     dashed red edge. Beside it, the chord's notes as a list, each with its interval (root, 3, 5, ♭7), the root's
     row in the accent, an outside note's row dashed red ("♭7 · off key").
   - **Keyboard**: the chord's notes as tiles in a row, each its name and interval (the root in the accent, an
     outside note dashed red), then a two-octave keyboard from the C at or below the root, the chord's notes lit
     stacked upward from the root (each note above the one before), the root in the accent, the rest in the
     role's colour, an outside note red.
   Under either, when a note is outside the key, one line: "F isn't in G major (it has F♯)" (the key's note of
   that letter, when it has one; otherwise "F isn't in G major").
4. **The switch**: under the picture, centred: ‹, two dots (the view shown filled), › . Either arrow, or a dot,
   goes to the other view; ← and → do too while the focus is in the tooltip. The arrows and dots are buttons named
   for the view they show ("Show the notes on a keyboard", "Show the notes on a circle"); the dots
   `aria-pressed`. The view chosen is the reader's, kept for every page as the chord necks are (localStorage
   `caracole-viewer-tipview`, `"circle"` or `"keys"`; circle when nothing is kept or storage is refused).
5. **Footer**: **▶ Hear it**, the chord strummed by `window.caracoleSound` on the instrument and loudness set
   (hidden when there is no sound or it is Off); and **Shapes →**, today's `tip-card` (opens the chord's card).

The tooltip keeps its behaviour: shown on a mouse's hover over a numeral or a finger's tap, placed by
`placeTip`, closed by Escape, a tap elsewhere or the mouse leaving; it fits 390 px (the circle beside the list
needs about 320 px; narrower, the list goes under the circle).

## Data

viewer.js computes no music theory (AGENTS.md): every note, interval and pitch class comes from the page's
data. `tones` (harmony_tables.py, `harmony.chord_tones`) gains each note's pitch class: "D F# A C|R 3 5 ♭7|2 6 9 0"
(a third field; the card's `drawNotes` reads the first two, unchanged). The key's notes are `keyScale[mode]`
above the tonic shown. Whether a note is in the key is membership in that set; stacking upward is arithmetic
on those pitch classes. The note names on the circle are the page's own names in the key shown (`names`). The
"it has F♯" note is the key's note of the same letter, from the key's scale names (`scales` / the page's
names): if the builder needs a table for it, it goes in harmony_tables.py, checked against harmony.py like the
others.

## Constraints

- AGENTS.md's viewer rules: `page.BUILD_FILES`, CSP hashes, createElement/createElementNS and textContent, no
  style attribute in markup (CSSOM `style.setProperty` only), no music theory in viewer.js, harmony_tables'
  texts checked on every transposition (test_viewer_numerals.py).
- strum.js stays the one place that makes sound; a tap is the user activation it needs.
- Light and dark themes; 390 px; 44 px targets under `pointer: coarse`; keyboard and screen reader (the
  pictures `aria-hidden`, the notes list and the switch's names say it all).
- The songbook (book.py) has the same tooltip.

## Left to the builder

Sizes, the circle's exact geometry, the keyboard's drawing, the animation between views (none under
`prefers-reduced-motion`).
