# The viewer's settings, cleaner

The sheet viewer's ⋯ opens its settings (`#panel`: a rail beside the song from 900 px, docked on a phone). Today
it is fourteen rows of equal weight titled "Key D": an on/off chip (Role colours) drawn like the chosen chip of a
one-of row (Chords), two orange Resets shown when nothing differs, Mode's seven big chips, and the rows that go
elsewhere (Harmony, Guitar Pro, Export PDF) drawn like settings and left below the fold.

## Decisions (the owner's, 2026-10-27)

Mockups (gitignored, in the main checkout): `.superpowers/brainstorm/2818486-1793122579/content/`
viewer-panel-directions.html, direction A ("Grouped, all in view"); viewer-panel-a-v2.html, take **A.2** ("No
headings, just space"). The owner asked for: Transpose and Capo on one line; the song's own mode marked by a
thicker outline and a slightly lighter colour, with no "as written"; no "What do the numerals mean?".

Each kind of control has one look: a stepper for a number, a segmented control for one of a few, pills for one
of many, a switch for on or off, a row with › (opens something here) or ↗ (leaves the page) for a place to go.

## The panel, top to bottom

1. **Head**: "Settings" (`#panel-title`), ✕, and under it a line of what is set: the key and mode played ("D
   Dorian"; "as written" for a sheet with no key), the capo where there is one ("capo 2"), the instrument
   ("Guitar").
2. **Transpose and Capo on one line**, each labelled over its stepper. While a value differs from the sheet's
   (transpose: the PDF's, `data.transpose`, else 0; capo: the sheet's), a small "↺ Reset" by its label (the
   existing `#reset-t`, `#reset-capo`) and the stepper's edge in the accent; otherwise neither. On an instrument
   with no capo, Transpose alone. Under them, when there are some, the easier capos as small pills ("Easier
   shapes: No capo · Capo 2 · …", `#capo`), then Easy keys (`#easy-row`) as pills.
3. **Mode**: "Mode" and, on the same line at the right, what the mode chosen sounds like ("minor, with a brighter
   sixth"); then a pill a mode. The song's own mode: a 2 px edge in a lighter grey and a slightly lighter fill;
   the chosen one: the accent (a 2 px accent edge when it is the song's own too). No "as written".
4. **Chords**, after a rule: Chord names as a segmented control (Chords · + Numerals · Numerals); its hint only
   when the key is unknown (why there are no numerals). Then switches, each a label and a switch at the right:
   Role colours (its label followed by "home away pull" in their colours), All chord shapes, Chord necks (where
   the rail shows, ≥ 1200 px), Pinyin (a sheet with Chinese).
5. **Instrument and strum on one line**: the instruments as a select (a native `<select>`), and the strum's
   loudness as four icon buttons (Off, Soft, Medium, Loud: a speaker crossed out, then one, two and three
   waves; each named for a screen reader and titled). No strum, no buttons. An instrument's own rows
   (`#inst-panel`) right under this line.
6. **Places to go**, after a rule, each a full-width row: Harmony › (progressions, scale: opens the Harmony
   panel, as `#harmony-open` does); Guitar Pro tab ↗ (one row a file, as `#guitar-row` lists them; served "in
   the browser", from a file a download); Export PDF › with the version in words at its right ("D Dorian, capo
   2"; from a file, the row unfolds the command and Copy, as today).
7. **Reset everything** (`#reset-all`), quiet, centred, under a rule.

Gone: "What do the numerals mean?" (`#gloss` and its texts: a chord's card and tooltip still say what its
numeral does), and the hints under Transpose, Capo, Chord names (but the unknown key's), Instrument and Guitar Pro.

## Constraints

- AGENTS.md's viewer rules: what a page is made from is `page.BUILD_FILES` (its hash), the CSP allows each
  inline script and style by hash, every element made with `createElement`/`createElementNS` and `textContent`,
  no style attribute in markup, viewer.js computes no music theory. Light and dark themes (viewer.css tokens),
  390 px with no horizontal scroll, 44 px targets under `pointer: coarse`, keyboard reachable in visual order.
- The songbook (`book.py`, `_CONTROLS`) gets the same panel, without Export.
- Behaviour and stored settings do not change: every setting does what it does now, with the same storage
  keys and address parameters; the bar, the chord card, the Harmony panel and the versions list are untouched.
- Keep the ids the tests and scripts use (`#down`, `#up`, `#shift`, `#capo-at`, `#names`, `#roles`, `#modes`,
  `#insts`, `#strip-toggle`, `#necks-chip`, `#pinyin-chip`, `#volumes`, `#harmony-open`, `#reset-all`, …). A
  switch stays a toggle button with `aria-pressed` (pressed = on), drawn as a switch; one-of controls keep their
  pressed state. Change a test only where the design changes what it checks, keeping its intent.

## Left to the builder

Exact spacing and sizes, the icons' paths, how the select is styled, the head's wording for edge cases (no key,
a piano).
