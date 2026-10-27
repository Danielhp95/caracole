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
geometry; what the overlay does below 1200 px (nothing new: phones keep the settings' panels); sizes by
viewer.css's `--nk`.

## Not in this

The record fit's percentages anywhere in the overlay; a harp following the song as it plays (D); a Together tab
(E); phones.
