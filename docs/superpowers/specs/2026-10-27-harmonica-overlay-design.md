# The overlay: chord necks and a harmonica, a tab apart

27 Oct 2026. The owner's choice from five mockups and two combinations (the visual companion), and the calls made
for them. Building it.

## Why

To jam: a guitarist and a harmonica player on one song. The wide screen's rail of chord necks shows a guitarist
where each chord sits; the owner wants the same for a harmonica, "which harmonica key / position combination can be
used to play the song at the given key", shown as the necks are, as a tab of that rail. The rail becomes the
overlay: Guitar and Harmonica. A chord sheet opens on Guitar, a harmonica tab's page (`harmonica-N.html`) on
Harmonica, and each shows the other a tap away, "so that I can jam with people".

## What gets built

**The overlay** is today's rail of necks (from 1200 px, on the left, `state.necks`, its Hide, the bar's button
and the settings' row as they are). A segmented control takes the place of its "Chord necks" title: Guitar and
Harmonica. On a chord sheet Guitar comes first and is the one shown; on a harmonica tab's page Harmonica comes
first and is shown. Each page opens on its own; the tab chosen is not remembered for other pages.

**Guitar** is today's rail, unchanged: the key's neck (Scale or Pentatonic), then each chord's neck and its
positions. With a ukulele or a baritone chosen, it is theirs and named so; with an instrument that has no neck
(piano, flute, recorder, harmonica), it is the guitar's.

**Harmonica**, from the top:

1. **The circle of fifths, small** (about 172 px across), the song's key in the middle as it sounds ("Bm"), and
   the 12 harps round it, each at its position: the 1st at the top (the harp in the song's key), then counted
   round the circle the other way (↺), 1st to 12th, the ordinal outside each harp that `harp.choices` picks. Those
   harps are shaded (filled dark), on a soft band; the harp chosen is in the accent colour; the rest are plain.
   Tap a harp to choose it. Beside the circle: the harp's name ("D harp"), its position and mode ("4th position,
   aeolian"), a badge "the tab's" on the harp the song's harmonica tab plays on (harpfit.py's record harp), and
   what it plays: "Plays A, D and Em; E as Em." (each chord it plays whole or as its triad, then each it plays as
   its minor stand-in), or "Plays none of the song's chords: melody only." Under the circle: "Tap a harp.
   Shaded: the ones that play the song's chords."
2. **The key on that harp**: "Bm on a D harp", its position; chips Scale · Minor pentatonic (Major pentatonic in
   a major key) · Blues; then the harp's ten holes: a comb of hole numbers 1 to 10, the blow notes above it, the
   draw notes below, and each hole's bends beyond its row (the blow bends of holes 8 to 10 above, the draw bends
   of holes 1 to 6 below, the deepest farthest). Each note is its name in a circle: the tonic filled in the
   accent colour, a note of the scale filled dark, any other outlined and faint; a bent note in the scale
   outlined in `--pull`, one outside it a faint dot. A legend (the tonic, in the scale, bent) and one line: the
   harp's notes outside the key ("Outside B minor: C.") or "Every note it blows or draws is in B minor." Nothing
   about how well the tab fits the record (the owner removed that line).
3. **A card per chord**, in the order the guitar tab lists them: the chord's name as it sounds, and "Am shape"
   when the capo or the transposition makes the shape another; the harp's ten holes (blow row, comb, draw row, no
   bends) with the run of holes that plays it filled in its breath's colour (blow the accent, draw `--away`) on a
   soft band (dashed for a minor stand-in), the chord's other notes outlined in their breath's colour, the rest
   faint; then one line: "draw 4–6", "blow 1–3 · as F#, its triad", "draw 4–6 · as Em, the minor stand-in", or
   "no chord here: its notes, one hole at a time".
4. **A slim bar**: once the circle has scrolled out of the rail, a bar slides in at the rail's top naming the
   harp ("D harp · 4th, aeolian") with a Change harp button that scrolls the rail back to the circle.

**The harp chosen** follows the song as it sounds (a harmonica takes no capo; a transposition moves every
harp). On a chord sheet it starts as the harp the song's harmonica tab plays on, when the song has one, else as
`harp.choices`' first. On a harmonica tab's page it is the page's harp, both ways: a harp tapped on the circle is
the one the page plays and names its notes on, and the bar's − and + move the circle's choice.

**On a harmonica tab's page** the Guitar tab shows the song's chord sheet (the one the page already reads, its
human one, else its auto one): its key's neck and its chords' necks, played as that sheet plays them. A song with
no sheet has no Guitar tab, and its Harmonica tab no chord cards.

## Approaches considered

Five, mocked up: (A) the Harmonica tab as a twin of the necks (harp chips, the key's harp, a harp per chord);
(B) a "which harp?" list first; (C) the circle of fifths; (D) one big harp following the song; (E) a third
"Together" tab, both at once. The owner took C to choose the harp and A's cards for the chords, then, of two
ways to combine them (the whole circle first, then the cards; or a small circle pinned at the top), the first
with the second's small circle, scrolling away with the cards, not pinned. The live mockup:
`.superpowers/brainstorm/1185961-1793133988/content/overlay-final.html` in the owner's checkout.

## Constraints

AGENTS.md's, chiefly: viewer.js computes no theory (each harp's notes and their names in the key shown, the
scales, the runs and the choices come from Python tables, harp.py's, per mode and transposition); `createElement`
only; scripts inlined by hash and listed in `page.BUILD_FILES`; Chromium tests for the pages; docs/usage.md and
AGENTS.md in the same commit. The harmonica tab's page loads its scripts as sheet.html does, so what both pages
draw lives in one script both inline.

## The builder's calls

The address and state names; how the rail's script is shared between the two pages; the circle's exact
geometry; what the overlay does below 1200 px (nothing new: phones keep the settings' panels; since superseded by
the phone's sheet, below); sizes by viewer.css's `--nk`.

## Not in this

The record fit's percentages anywhere in the overlay; a harp following the song as it plays (D); a Together tab
(E); phones (since added: below).

## The phone: a sheet from the bar

Added the same day. The owner's choice from three phone mockups (a sheet from the bar; a row in the settings opening
a panel of its own; a dock over the bar with the chord being played): **A, a sheet from the bar**. Below 1200 px a
new button in the bar, a neck, slides the overlay up from the bar as a sheet over about half the screen (54 %), the
song readable and scrollable above it. A tap on its handle takes it to the whole screen (a strip of the song left at
the top) and back; ✕ closes it. It holds exactly what the rail holds: the tabs in the page's order, the circle, the
key card, the chord cards and the slim bar, the same harp, linked with a harmonica tab's page's −/+ as the rail is.
The rail's code draws it (overlay.js `rail`, the page's `sheet()`, `grow()` and `close()`); viewer.css makes the
aside a sheet where it carries `data-sheet`.

The builder's calls:

- **The bar.** The neck sits right after the key, the first of the tools at the end, tinted while the sheet is open.
  A sixth 44 px target would leave the key 44 px less. First built with the guitar kept beside the neck from 360 px,
  the key saying less there ("capo 2 · +1" at 390 px, "Ab mixolydian" cut short). The owner then chose: **"Let it
  replace the guitar icon in small phones."** Below 440 px the neck takes the guitar's place,
  the key keeps its room and its words as before ("Ab mixolydian" over "shapes · capo 2 · +1" whole at 390 px), and
  the settings' All chord shapes shows the strip. From 440 px the guitar is beside the neck, with room for the
  longest key a little smaller; 440 rather than the bar's phone width, 420, which left 420 to 433 px cutting "Ab
  mixolydian" short, so no key is ever cut beside both. On a harmonica tab's page (no guitar) all four
  tools fit; at 320 px the harp's name is a little smaller ("Ab harp" at 11.5 px). Nothing overflows, and every target
  stays 44 px.
- **Assistive tech.** The sheet is a dialog that is not modal (`role="dialog"`, no `aria-modal`), named "Necks and
  harps" as the neck is (`aria-haspopup="dialog"`, `aria-expanded`, `aria-controls`); the rail stays the
  complementary "Chord necks". The focus goes to the tab shown as it opens, back to the neck as it closes (✕, Escape,
  the neck again), unless it was somewhere else of yours. The handle is a toggle button, "Whole screen", pressed while
  the sheet is whole; its grip at the top, its reach the whole head under the tabs and ✕.
- **Kept or not.** Not kept: each page opens with the sheet closed, and it opens at half the screen. In a songbook
  each song is a page of its own, so the next song opens with it closed; the songbook's arrows and swipes stay with
  the sheet while it is open, as with the settings.
- **Across 1200 px.** Widened past it with the sheet open, the sheet closes and the rail takes its place where it is
  shown (the screen's choice), on the tab the sheet was on, the focus kept in it; narrowed again, nothing opens by
  itself.
- **The song under a half sheet.** The sheet docks on the bar as the settings do (viewer.js's layers: on a phone the
  one opened last shows, the others hidden until it closes; from 900 px it stays beside the settings' rail): the page
  leaves room under the song for it, so the song's last line comes up above it, by hand or by itself, and the pill
  rides above it. ▶ closes the settings and the card but leaves the sheet, at half the screen, the bar under it; going
  to the whole screen pauses the scroll, and its pill then sits over the sheet's foot. A finger on the sheet pauses
  the scroll, as anywhere on the page.
- **Chord necks and Hide.** The rail's alone: neither touches the sheet, and both show only from 1200 px.
- **Sizes.** The sheet is the page's own size (`--nk: 1`), at most 620 px wide as the settings docked are; the circle
  at most 54 % of its width, so the harp's words keep their room at 320 px.
