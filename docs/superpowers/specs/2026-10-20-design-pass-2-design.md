# Design pass 2: a denser library, a guitar neck, a cleaner PDF, a songbook page

Date: 2026-10-20. Owner's choices made on the sketches page
(https://claude.ai/artifact/3m2ThkGDtqfCJg13Bh7Sw2): library **B**, laptop sheet **A**, PDF **C**,
songbooks **A**. This document is what a builder plans from. Lines marked *(my call)* are
decisions the owner didn't make and may still change; everything else is theirs.

## Why

caracole works, but on the owner's laptop and phone the library and the laptop sheet "are not
nice", and the PDF is "a bit janky". The owner plays from these pages and builds set lists from
them, and wants the experience to feel closer to Ultimate Guitar, which they like:

- **More information on screen.** Today's cards show one or two songs per phone screen and
  a few per laptop screen. The owner wants density, like UG's lists.
- **Search everything while typing.** Typing should filter not only the songs already
  downloaded, but also what caracole's indexes hold (Ultimate Guitar, LaCuerda, gtptabs.com,
  MuseScore), without pressing Enter.
- **See every way to play a chord** on the laptop: a guitar neck with all positions.
- **A PDF that looks clean**, and one that can carry other chords than the tab's: "export to
  PDF different chords from the original song (i.e. changing from major to Dorian)".
- **Songbooks you browse and edit in one place.**

## Goals

1. The library page shows songs as dense lines grouped by artist, at rest and while searching;
   cards and the Cards/Rows switch go.
2. Typing in the search box lists, under your own songs, the matching songs and artists from
   every local index, updating as you type, on `caracole serve`.
3. On a laptop, the sheet viewer shows a rail on the left with a guitar neck per chord of the
   song, every position of the chord drawn on it; picking a position makes it the shape used.
4. The PDF is clean, in two columns, and its chord boxes show the shapes the sheet uses.
5. From the sheet, the owner can export a PDF of the version on screen: another key, capo or
   mode (G Dorian instead of G major), their chosen positions.
6. A Songbooks page lists the songbooks and edits one as a set list, each song with its own
   key, capo and mode, which its PDF and phone page use.

## Non-goals

- Autoscroll. The owner said "I really don't care about autoscroll": leave it as it is.
- A web search or any request to a site while typing: the indexes are local tables.
- Changing how songs are found, matched or fetched, or the nightly run.
- A neck rail on phones: the phone keeps today's chord card.
- Paged or swipe layouts for the sheet, View Transitions, a JavaScript framework.

## Anti-goals (failure even if it works)

- Typing that sends requests to Ultimate Guitar, LaCuerda, gtptabs.com, MuseScore or LRCLIB.
  Only Get it (or adding a song you don't have to a songbook) may, at the lookup pace, as today.
- A library that is denser but harder to act on: every action the cards have today must stay
  one or two taps away.
- An exported or songbook PDF whose chords don't match what the viewer showed for the same
  key, capo and mode. The music theory stays in Python, in one place (viewer/theory.py).
- Losing anything on the file page (index.html opened from the synced folder, no server).
- Layout shift, sideways scroll at 390 px, targets under 44 px on touch, broken dark mode.

## Constraints

Everything in AGENTS.md's invariants holds. The ones this work touches most:

- **Two ways to open the pages.** index.html, sheet.html and songbook.html open from disk
  (file://, offline, CSP `default-src 'none'` with hashed inline scripts and styles) and are
  served by `caracole serve`. Only the served page can ask the server for index results; the
  file page filters your own songs and shows the `caracole search` line to run, as today.
- **The indexes are local** (ug_index with its trigram search, lacuerda_index, gtptabs_index,
  musescore_index): `/api/search` answers in 1–100 ms on 1.6 million tabs. It runs one query at
  a time, the newest first (`set_progress_handler`); the page asks with a short pause and
  cancels older questions. The index rows have **no ratings** (UG's index holds tab counts
  only; ratings exist only for sheets caracole fetched), so index rows show tab counts, not
  stars. MuseScore matches titles only and is often blocked (Cloudflare): show what it has.
- **Writes go through the existing paths**: a request or Get it is a job (`caracole get`,
  one command at a time); songbooks.toml through songbook.py's writers (tomlkit, comments kept);
  overrides.toml through overrides.py's `add_*`; schema changes through db.py.
- **The viewer**: viewer.js and viewer.css are inlined with CSP hashes; the served viewer runs in
  `sandbox allow-scripts` with no storage (state that survives a reload goes in the address).
  The chord data (voicings.json, a checked subset of chords-db, about four positions per chord,
  plus the sheet's own shapes first) and the theory (transposition, modes, alternatives) are
  computed in Python by page.py; the script only looks up.
- **PDFs** come from chordpro 6 with caracole's style (chordpro-style.json), on a copy in a
  private cache folder. Songbooks already render each song with its `{transpose}`.
- Tests first; Chromium tests for layout and behaviour at 390x844 and 1280x800, light and dark;
  run with `nix develop -c pytest -q` (35 s) and `-m "not slow"` (6 s).
- Two code changes are merging first and this work builds on them: library_page.py's CSS and
  JavaScript moved into package files and web/app.py split by area (branch dev-speed).

## The parts

### 1. Library: dense lines grouped by artist (choice B)

- **At rest and while searching, the only view.** The owner: "Cards go". The dense lines
  replace both Cards and Rows; the Cards/Rows switch (`#view=`) goes, and with it the card code
  and its tests. At rest: your library as lines grouped under artist headers, artists A–Z. A header reads "Soda Stereo · you
  have 2", and while searching also "· UG 96 · LaCuerda 140 · Guitar Pro 12". A song line holds
  its title, status (Found, Wanted, Needs review, Not found), key, the icons of where its sheet
  and files came from, and its main action (Open, Fetch now, Pick the match). The rest (other
  files, versions, Remove, add to a songbook) is under the line's ⋯. About 30 lines on a laptop
  screen; two lines per song on a phone.
- **While typing** (served page): your matching songs, then matching artists and songs from
  every index, under the same artist headers. A song the sites have under several sources is
  one line with each source's icon *(merge by the song's identity key; the builder picks the
  rule for near-duplicates)*. Index lines show "chords ×6"-style counts and a Get it; nothing is
  fetched until it's pressed. An artist group shows a few of its index songs, most tabbed first,
  then "+ 211 more by Estopa", which lists them all (`/api/artist`, 50 at a time).
- The filters, Key menu, sort, and the A–Z letters stay and work on the dense lines; the
  review picker, request progress, Remove's Undo and Select's songbook making keep working, on
  the lines.
- The file page: the same dense lines for your songs; typing filters them; Enter shows the
  `caracole search` line.

### 2. Laptop sheet: a neck per chord (choice A)

- On a wide screen *(my call: from about 1200 px, the builder settles it with the settings rail
  that opens on the right from 900 px)*, a rail on the left lists each chord of the song, in
  order of first appearance, each with a horizontal neck (frets 0–15) showing all its
  positions in distinct colours, a legend ("the tab's", "open", "fret 7"), and the tab's own
  shape marked.
- The necks follow the viewer's state: transposing, moving the capo or changing the mode
  redraws them for the chords now shown.
- Picking a position (clicking it on the neck or in its legend) makes it the shape used for that
  chord in the strip and the chord card, kept in the address with the rest of the viewer's state
  (so the served viewer keeps it on reload), and used by "Export PDF of this version".
- The rail scrolls on its own, so a song with many chords still works; the phone and narrow
  screens keep today's chord card.

### 3. PDF: clean, two columns (choice C)

What's janky today, all seen in Wonderwall: the tab's opening notes print as lyrics (a YouTube
link with a raw "&amp;amp;", a half-read chord legend, a stray "EADGBe"); lyric lines start with
stray spaces; section names sit in grey boxes; a short song takes three pages.

- The tab's notes before its first section stay out of the PDF, *except* tab blocks (Hotel
  California's intro riff), the chord legend, whose shapes become the PDF's chord boxes
  (`{define}`), and *(my call)* a tuning or capo note ("Tuning: Eb standard", "half step down",
  "Capo 2"), which goes into the header line beside the key so a song in another tuning never
  prints as if in standard tuning. Strumming notes and the rest are dropped.
- HTML entities that UG escaped twice are decoded where caracole reads the sheet, so the .cho,
  the viewer and the PDF all get the right text.
- Stray leading spaces after a line's first chord are trimmed.
- Section names in small coloured capitals, no box; chord boxes larger; the header line reads like
  the viewer's ("Em shapes · capo 2 · sounds F#m"); two columns (`{columns: 2}`), about one page
  less per song. The renders on the sketches page are the reference (style C).
- Songbook PDFs use the same style.

### 4. Export a changed version, and a song's own version

- **Export PDF of this version** on the sheet: makes a PDF of what's on screen (its key, capo,
  mode, chosen positions and any "play X for every Y" swaps, so it always matches the screen) as a
  file beside the original, e.g. "sheet (G Dorian, capo 0).pdf" *(my call on the name)*.
  - *(my call, forced by the sandbox)* The served viewer runs in `sandbox allow-scripts` with no
    form posts and no connection to the server, a rule this design keeps. So the button opens a
    caracole serve page in a new tab, with the version in its address: it shows what will be made
    and a Make PDF button (a POST with the form token, as other served actions), the job's
    progress, then the PDF to open. On the file page, the button shows the command to run.
  - *(my call)* Exports are files caracole looks after: recorded like the sheet's own outputs, so
    `caracole remove` deletes them, a later sheet or style change remakes them, and an export with
    the same settings replaces the last one. They are listed under the song line's ⋯.
  - The swaps go into the viewer's address with the rest of its state (today they live only in
    the browser's storage, which the served viewer doesn't have).
- **How the chords are written** *(my call)*: caracole writes every transposed or mode-mapped
  chord name and its shape into the .cho it hands chordpro, using viewer/theory.py (`map_chord`,
  the viewer's sharps-or-flats spelling) and the sheet's or chosen positions as `{define}`s, and
  stops using chordpro's `{transpose}`. chordpro 6.050 spells A# where the viewer shows Bb and
  doesn't move `{define}` shapes with the chords. This also changes how `[transpose]`d PDFs and
  songbooks render today, for the better: their chords then match the viewer's.
- *(my call, smaller)* **Make this my version**: saves the song's key, capo, mode and positions
  in overrides.toml, so the song's main PDF, the viewer's starting state and songbooks use them.
  `[transpose]` exists today; the rest needs new tables.

### 5. Songbooks page (choice A)

- A **Songbooks** tab beside Library. On the left, the songbooks as lines: name, songs,
  how many still need a sheet, last changed; "+ New songbook".
- On the right, the open songbook as a set list: drag to reorder (and a keyboard way to move
  a song), each song's "plays in" chip (key, capo, mode) that edits that song's setting for this
  songbook only, × to take a song out, Get it for a song with no sheet yet, "Get the N missing
  songs now", Rename and Delete, and its exports: PDF (style C), phone page, ChordPro.
- **Add a song**: a search box that searches your songs and the indexes as you type, like the
  library's. Adding a song you don't have adds it to the library and looks it up (as Get it
  does), then puts it in the songbook.
- **What a setting is** *(my call)*: a song's setting in a songbook names the key it plays in
  (tonic and mode, "G Dorian") and its capo, not a shift from the sheet, so replacing a song's sheet
  with one in another key leaves the set list's key alone; the chip shows that key. A song with no
  setting of its own follows the song's own version ("my version", else the sheet as written),
  including later changes to it.
- **Storage**: each song in songbooks.toml may carry its own settings *(my call on the shape)*,
  e.g. `{ song = "Soda Stereo - De Música Ligera", key = "G", mode = "dorian", capo = 0 }`
  beside plain `"Artist - Title"` entries, written through songbook.py's writers so comments
  and layout survive; `caracole songbook` gains a way to set them.
- The file page shows the songbooks read-only with their files and the commands to change them.
- Select on the library *(my call)* stays as the quick way to put several songs in a songbook.

## Left to the builder

Breakpoints, colours and exact wording; how the dense lines look in detail; the merge rule for
index songs across sites; how many index songs an artist group shows before "+ more"; the neck's
drawing; the export file's name; the songbooks.toml shape for per-song settings; the order of the
work. Suggested order, since the parts share files: (1) PDF cleanup and style (render, chordpro,
ug/page) and (2) the neck rail (viewer) can start right away and run beside each other; (3) the
library lines and (4) the Songbooks page both change library_page.py and web/, so one after the
other, after dev-speed merges; (5) export and "my version" after (2) and (3).
