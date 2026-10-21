# The music theory edition

Owner's request (2026-10-21): "Using the same code as changing modes like major to Dorian, I want to be able
to specify next to the chord what chord in the key it is: in C major, C F G are I, IV, V. I want to be able to
abstract away the chord and just have what chord in the key it is." Then, from the suggestions: chords outside
the key explained, progressions named, the key on the neck, and hear it.

## Decisions (the owner's, 2026-10-21)

- Roman numerals, case for quality: in C major, C Dm Em F G Am Bdim are I ii iii IV V vi vii°.
- A glossary: tap or hover a numeral for a one-line explanation; a "What do the numerals mean?" page in the
  viewer's settings explains the notation.
- Numerals in the viewer, in PDFs (Export PDF of this version, Make this my version) and in songbooks (each
  song's setting).
- All four additions: chords outside the key explained, progressions named, the key on the neck, hear it.

## Where it lives

theory.py (Python) answers every question; page.py hands the answers to the page as tables, as it already
does for each mode's mapped chords (`data.mapped[mode]`); viewer.js only looks up. This keeps the AGENTS.md
rule ("theory lives in viewer/theory.py and viewer/voicings.py") and makes the PDF (version.py, pdf_text.py)
and the page say the same thing. Numerals don't depend on the transposition or the capo (a I is a I in every
key), so a table per mode is enough.

## 1. Numerals

- **Notation.** The numeral of the chord's root against the key's tonic, written against the tonic's major
  scale: a degree the mode lowers or raises gets ♭ or ♯ (C Mixolydian's B♭ is ♭VII; A minor's C is ♭III; the
  Andalusian cadence is i–♭VII–♭VI–V). Upper case for a major or augmented triad's family, lower case for
  minor and diminished. Then the quality as written in classical and pop analysis: ° diminished, ø
  half-diminished (m7♭5), + augmented, 7, maj7, 6, sus2/sus4, add9, 5 (a power chord); extensions as the
  chord name has them (V9, ii7). vii°7 for a diminished seventh.
- **A different bass** (slash chords) is written as the bass's degree in Arabic numerals after a slash, I/3
  for C/E in C, V/♭7 for G/F; Roman after a slash is kept for "of" (V/V, item 3). The glossary says so.
- **Display.** A viewer setting, "Chord names": Chords · Chords + numerals · Numerals only, kept in the
  address with the viewer's other settings. With both, the numeral sits after the chord name, smaller and in
  its own colour, without moving the chord off its syllable more than the chord name already does; with
  numerals only, the numerals take the chord names' place. The mode chips re-label the numerals with the
  mapped chords; the key buttons (transposition) and the capo leave them as they are.
- **No key, no numerals.** A song whose key caracole can't tell offers no numerals and says why in the
  setting. A chord theory.py can't read (N.C., a riff label) is shown as written in every display.
- **The glossary.** Tapping (touch) or hovering (mouse) a numeral shows one line: "vi: the 6th chord of the
  key, minor (lower case)"; "♭VII: built on the lowered 7th degree; borrowed from C minor"; "V/V: the V of V,
  leads to G". The settings panel's "What do the numerals mean?" explains the whole notation, with this
  song's own chords as the examples where it can.
- **PDFs and songbooks.** `Version` (viewer/version.py) carries the chord-names setting; Export PDF of this
  version, Make this my version (as a key, per the sheet-versions decision 2026-10-21) and a songbook song's
  setting carry it too. A "numerals only" PDF is a chart that works in any key: it says the key it was read
  in under the title and leaves out the chord diagrams. Both kinds of PDF end with a short legend of the
  symbols that song uses.

## 2. Chords outside the key, explained

- theory.py tells each chord's relation to the key: **in the key**; **borrowed** from the parallel key or a
  mode on the same tonic (says which: "borrowed from C minor", "from C Mixolydian"); **a secondary dominant**
  (a major or dominant-seventh chord a fifth above a chord of the key, written V/x, and "leads to x" when the
  next chord is x); **a secondary leading-tone chord** (vii°/x); or **outside the key** otherwise.
- **Role colours.** Each chord in the key belongs to a family: home (I, iii, vi; i, ♭III, ♭VI in minor),
  moving away (IV, ii; iv, ii°), pulling home (V, vii°; ♭VII where it leads home). With numerals shown,
  numerals are coloured by family, and a chord from outside the key is marked (a dotted underline). Colour
  never carries the meaning alone: the tooltip says it, and both palettes meet the pages' contrast rules in
  light and dark mode. A setting turns the colours off.

## 3. Progressions named

- For each section of the sheet, its chord sequence in numerals, repeats folded ("vi–IV–I–V ×4"), and the
  common name when it matches one from a catalogue in theory.py, in any rotation and key: I–V–vi–IV (the pop
  progression), I–vi–IV–V (the '50s progression), ii–V–I, I–IV–V, the 12-bar blues, i–♭VII–♭VI–V (the
  Andalusian cadence), I–♭VII–IV, vi–ii–V–I (circle of fifths), the Canon (I–V–vi–iii–IV–I–IV–V), and a
  few more the builder can source. How each section ends: V–I (authentic cadence), IV–I (plagal), ends on V
  (half cadence), V–vi (deceptive).
- **In the viewer:** a "Harmony" panel (beside the settings, the same docked or rail behaviour) lists the
  sections with their progressions, names and endings; tapping one scrolls to the section. With numerals on,
  a section's name on the sheet shows its progression's name in small type.
- **Songs with the same progression.** index.html's data carries each song's section progressions (as
  numerals, key-free); the library page and the served search find songs by progression ("vi IV I V", or a
  name, "andalusian"), and the Harmony panel links to the library page filtered to that progression
  (`index.html#prog=…`, a relative link that works from the file and when served). `caracole search
  --progression "vi IV I V"` does the same in the terminal. A viewer never embeds other songs' data (one
  song's change must not rebuild every viewer).

## 4. The key on the neck

- **The key's neck.** At the top of the neck rail (from 1200 px), a neck showing the key's scale across the
  frets (the tonic marked), with a switch for the major or minor pentatonic box; on a phone, the same neck in
  the Harmony panel. It follows the key and mode shown and the capo (positions shown as played).
- **A chord's card** lists the chord's notes with their intervals (C E G B♭ = R 3 5 ♭7), and the scale that
  fits over it for a solo: the key's own mode on that chord's root for a chord in the key (Dm7 in C: D
  Dorian), the borrowed-from mode for a borrowed chord, Mixolydian for a secondary dominant, and by quality
  otherwise (Locrian for m7♭5, the whole-half diminished scale for °7, as jazz teaching reads it, its notes the
  chord's and a whole step above each; the half-whole one is the dominant's, for 7♭9 and 7♯9); each with its
  notes, one letter a degree.

## 5. Hear it

- Tapping a chord's name or card plays it: the voicing the page shows (the chosen position's frets, standard
  tuning, the capo applied), strummed low to high, synthesized in the browser (Web Audio; a plucked-string
  synthesis, no samples, no network). Never on its own: only on a tap or a click; one sound at a time; a
  volume in the settings; nothing plays in a page left in the background.
- A section's ▶ in the Harmony panel plays its progression, a chord per bar at a tempo you set (default 80
  bpm), and shows which chord is playing; ■ stops it.
- It works in the file:// viewer and in the served viewer's sandbox (allow-scripts), and the CSP needs no
  new source.

## Not in this

- Melodies and the singer's range (there is no melody data); key changes inside a song beyond saying a
  section's chords fit another key better (left to a later pass); notation other than Roman numerals.

## Constraints

- Theory in Python (theory.py), the page only looks up; `page.BUILD_FILES` changes rebuild viewers; theory.py
  keeps its frozen, cached answers (test_viewer_theory.py).
- Viewer size: the new tables (numerals, relations, families, tooltips per mode; notes and scales per chord)
  are measured, and kept to what the page shows.
- 390x844 and 1280x800, light and dark: no sideways scroll, 44 px touch targets, contrast rules, no layout
  shift; file:// pages keep their hashed CSP; served pages keep their sandbox.
- docs/usage.md says what each display, panel and sound does.

## Left to the builder

The colours of the three families and the outside-the-key mark; the exact tooltip wording; the progression
catalogue's other entries (with sources in a comment); the synthesis; how the Harmony panel shares space with
settings and the chord card on a phone.
