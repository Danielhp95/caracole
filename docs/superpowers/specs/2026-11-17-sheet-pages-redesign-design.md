# The sheet pages, redesigned

Status: approved by the owner on 2026-11-17, to be planned and built as a fifth lane beside the library page's four.
Research: `.claude/handoff/ui-research-2026-11-17/reports/Sheet pages UI UX research.md` (local, not in git), the
owner's picks in `.claude/handoff/ui-research-2026-11-17/sheet-decisions.md`. Mockups of each decision beside this
file in `2026-11-17-sheet-pages-redesign/` (fragments drawn for the brainstorming companion's frame).

## Why

The owner asked for the same rework of the sheet pages as of the library page, with Ultimate Guitar's tab page as the
reference. The research found the reading core sound (proportional type anchored to the syllable, the tap-a-chord
card, autoscroll with a wake lock) and the trouble concrete: a header that costs a quarter of the phone, a song's other
kinds two taps deep, wrapped tails that read as new lines, Android's Back leaving the song with a panel open, a scroll
button that reads as "play a sound", a key that hides that it moved, a Harmony panel that repeats the necks, a laptop
bar split 700 px apart, a screen that sleeps when autoscroll is off. The owner chose each change below from mockups.

## Goals

- The song owns the screen: the facts the owner chose up top, then the sheet, with nothing pinned over it.
- Every kind and version of a song one tap away, with how many there are.
- Lines that read as sung, intros that keep their bars, two columns on a laptop more often.
- Controls that say what they do, a key that says it moved, one theory surface.
- Hands-free playing: keys and pedals, the sung line lit, a screen that stays on while you play.
- Back undoes whatever a sheet page opens.

## Non-goals

- No change of colours, logo or font; no relative text-size steps, no Stage preset, no Night palette (the owner kept
  today's text size control and chose Auto / Light / Dark).
- No change to how settings are split (the owner kept today's: Aa for the size, ⋯ for the rest), no bumper or
  run-through at a song's end in a songbook, no duration-based autoscroll speed.
- The library page is the other lanes' (docs/superpowers/specs/2026-11-17-library-page-redesign-design.md).

## Anti-goals

- A big-bang change (UG's July 2026 tab page, rolled back): the lane merges in stages, each checked on screen.
- Anything pinned over the sheet; a bar that hides the song's last lines.
- Losing what the pages guarantee: nothing loaded from the network, the same page served and from a file, find-in-page,
  the sandbox, the byte-for-byte agreement with the phone's Kotlin page builder.

## Constraints

- AGENTS.md's rules for the pages (no network, inline assets by hash, `createElement`/`textContent`, served or from a
  file, the WebView) and for viewer/: `page.BUILD_FILES`; version.py naming chords as viewer.js does; viewer.js
  computing no music theory (it looks up harmony_tables); strum.js the one place a page makes sound; the settings kept
  for every page at once (localStorage plus an address flag that `carryScreen` carries).
- The phone builds the same pages in Kotlin (`:viewer`, `viewer.pages.SheetPage`, `HarmonicaPage`, the songbook): a
  change to page.py's markup or data, or to the viewer's assets, regenerates the corpus (vectors/viewer/pages*,
  harmonica_pages*, page.json, render.jsonl) in the same commit and moves the Kotlin port with it; gradle passes before
  a merge.
- Tests first; browser tests `@in_chromium`; the whole suite before each merge; docs/usage.md and AGENTS.md in step.

## Approaches

1. **A fifth lane beside the library's four** (chosen): the viewer's files (viewer/*.js, viewer.css, page.py,
   harptab_page.py, book.js) and their Kotlin port barely meet the library lanes' (library_assets/, card.js,
   outcome.py), so it runs in parallel, in stages merged one by one.
2. After the library lanes merge: one redesign on main at a time, slower.
3. Several parallel sheet lanes: most of the work sits in one 2,800-line viewer.js, so they would collide.

## What the owner decided

### The header (mockup `header.html`, D1 C)

- A title block: "‹" (back to the library, a 48 px target), the title, the artist (a link to the library's search for
  them, as today's artist line), then the version line (below).
- Then the song's facts on three lines, label and value: **Tuning** (the instrument's open strings as notes, e.g.
  "E A D G B E", or the sheet's own tuning when it names one), **Capo** (the capo as currently set: "none" or the
  fret), **Key** in today's honest wording (my call): the key alone with no capo ("Am · from the tab"), and with one
  "Em shapes · sounds F#m", as page.py's `_facts` and viewer.js's `keyLine` say it today, so "Key Em" is never read as
  the song's key. My call: on an instrument with no strings (piano, harmonica, the winds) the Tuning line is left
  out.
- Then the sheet. Today's "Key Am · from the tab" line and the versions box go, folded into these.

### Versions and kinds (mockup `kinds-versions.html`, D2 C plus the owner's icons)

- The version line reads "Chords · Ver 1 of 3 · ★ 4.80 (120) ⌄" ("New" where a version has no rating; no "Ver 1 of 1"
  for a single version), followed by **an icon for each kind of thing to play the song has, with how many versions of
  it**: the chord sheet's icon and "3", the harmonica's and "1", Guitar Pro's and "1" (the same glyphs as the library's
  play buttons). The owner's addition.
- Tapping the line opens **one list grouped by kind** (my calls on its contents): **Chords** is today's versions list
  as it is (every UG chords version caracole has recorded, kept or not, the one shown ticked, "★ 4.85 (81)" or "New",
  named by what differs where UG's data says, e.g. "acoustic", with today's actions: Keep, Make this the one, Back to
  our pick, and the "On UG" line with its command from a file), so nothing the switcher does today is lost; then a
  group for each other kind the song has, **the same kinds the library card shows as play buttons** (the chord sheet's
  ukulele variant, UG's text tab, Guitar Pro, harmonica, game-music tab, score), each entry opening its page. "Ver 1 of
  N" and the chord icon's number are the same count, today's N. The same list on the version pages
  (version-<tab>.html) and the harmonica page; render.py passes the other kinds the page doesn't carry today, in Python
  and the Kotlin port alike.
- My call: on a phone it opens as a sheet from the bottom (one layer, Back closes it); on a laptop as a popover under
  the line.

### Lines (mockup `lines.html`)

- **A sung line longer than the phone (D3 A)**: wrapped tails stay flush left; more space between one sung line and
  the next (about 0.4 em) than within one. No hanging indent, no shrink-to-fit.
- **A chord inside a word never splits the word across rows** (the research's fix, unanimous): a word and its chords
  wrap together.
- **Chord-only lines (D4 C)**: where a sheet writes bars ("Am C | G Em |"), the line is drawn as a row of bar cells,
  each with its chords and beat dots, like Chordify's grid; a chord-only line without bars keeps today's even spacing.
  How beats are counted (from the spacing between chords inside a bar, or evenly) is left to the builder. My call: the
  PDF keeps printing such a line as text ("Am C | G Em |"); only the page draws cells, and page.py and pdf_text.py read
  a bar's contents by one shared rule.

### Reading settings (mockup `reading.html`)

- **Text size (D5 A)**: today's "A− 18 px A+", 13–30 px; the section labels keep today's fixed size (the owner's pick
  bundles it; the research's proposal to scale them is not taken).
- **Theme (D6 B)**: an Auto / Light / Dark control in the Aa popover, kept for every viewer page (localStorage
  `caracole-viewer-theme`, an address flag carried by `carryScreen` for the songbook's sandbox, as the necks setting
  is). Auto follows the system as today. The library page keeps following the system.
- **Chord shapes before playing (D7 B)**: on a phone, a strip of the song's chord shapes on the instrument shown, in a
  row above the first section, scrolling away with the sheet; on by default; today's setting for the strip of all
  chord shapes becomes its switch. Tapping a chord still opens its card.

### Two columns on a laptop (mockup `columns-bar.html`, D8 B)

- From 1100 px, before falling back to one column at 21 px, the song is tried in two columns at sizes stepping down to
  about 18 px; the first that fits whole is used. Shorter songs as today.

### The bar (mockup `columns-bar.html`)

- **The scroll button (D9 C)**: a downward-arrow glyph in place of ▶ (lit while scrolling), and **a word under every
  bar button**: the key keeps "key" (or what changed, below), then "Shapes", "Text", "Scroll", "More". The bar grows by
  about 10 px; the sheet's end keeps room for it (below).
- **The key (D10 C)**: under the key, what changed: "+2" when transposed, "capo 2" when a capo plays it, "key" when
  neither; the settings say transposition the same way. Tapping the key opens the twelve keys in the song's mode, "Am ·
  as written" first, the current one marked; choosing one transposes there.

### Panels (mockup `controls.html`)

- **Settings (D11 A)**: today's split (Aa for the size and now the theme; ⋯ "More" for everything else); with D9's
  words the ⋯ button reads "More". Today's duplicated switches (Chord necks, All chord shapes) appear once each (the
  research's fix); Mode keeps its chips (the owner kept today's settings).
- **Harmony (D12 B)**: a third tab beside the necks: "Guitar | Harmonica | Harmony" in the rail (from 1200 px) and in
  the phone's sheet of necks; the Harmony panel and its row in the settings go, and the duplicated scale neck with
  them; a progression's ▶ plays as today.
- **The laptop's bar (D13 C)**: from 1200 px wide, the controls are a toolbar of pills under the title, in the phone's
  order (key, Shapes, Text, Scroll, More); below 1200 px the bottom bar as on the phone. My call: once the title
  scrolls away the toolbar sticks to the top of the window, the sheet keeping room for it so it never covers a line
  (today's bottom bar likewise always stays in view); the autoscroll pill and the full-screen handle sit under it.
- **Full screen (D14 C)**: "Hide controls" in More, or a double tap on the page's margins, hides the bar (or the
  laptop's toolbar), the header's facts and the rail; a thin handle stays at the foot; a tap on it, Escape or Back
  brings everything back. On a screen under about 500 px tall (a phone on its side) the controls slim to the handle by
  themselves until tapped. While autoscroll runs the bar hides as today.

### Layers and Back (the research's fix, the owner's rule from the library page)

- Each layer a sheet page opens (the settings, Aa, a chord's card, the necks' sheet, the versions list, the key list,
  full screen) adds one history entry while open; Back, Escape or ✕ closes the top one. On a phone one layer at a time:
  opening another closes the one open.

### Hands-free (mockup `hands-free.html`)

- **Autoscroll's speed (D15 A + D's highlight)**: today's speed ("− 6 +", steps 1–30, saved per song). Where the song
  has timed lyrics, **the line being sung is lit** while autoscroll runs: the lyrics' clock starts when autoscroll
  starts (after its count-in), a pause stops the clock. My call: a tap on a line pauses autoscroll, as any touch does
  today, and sets the clock to that line's time, so resuming (after the count-in) goes on from there. The scroll
  keeps its chosen speed; the highlight follows the lyrics' times. Matching the timed lyrics' lines to the sheet's lines
  (sheets repeat and abbreviate sections) is done when the page is built, in Python and its Kotlin port alike; a line
  with no match is never lit, and a song with too few matches (the builder's threshold) shows no highlight.
- **Keys and pedals (D16 B)**: Space or Enter starts and stops autoscroll; PageDown or ↓ turns a screen less two lines;
  PageUp or ↑ goes back a screen; any of these while autoscroll runs pauses it; ← → keep changing songs in a songbook.
  Keys are ignored while a text field or a layer has the focus; the version switcher is never in the key map.
- **The end of a song in a songbook (D17 A)**: as today.
- **Keeping the screen on (D18 C)**: while a sheet page shows, the screen is kept on until 10 minutes after the last
  touch, key or scroll, and always while autoscroll runs (as today); the 10 minutes are a setting in More ("Keep the
  screen on: 10 min", from off to 60 min), kept for every viewer page. Through the Screen Wake Lock API, never gated on
  `navigator.permissions.query` (Android's WebView answers it "denied" while granting the lock).

### Fixes that need no choice (the research's, unanimous)

- The sheet's end leaves room for the bar and its inset, plus half a screen of over-scroll, so the bar never covers the
  last lines.
- The highlighted chord at 4.5:1 contrast or more in the light theme; the dark theme's role colours told apart by
  lightness, not hue alone.
- 48 px hit areas under `pointer: coarse` (the bar's buttons are 44 px today), the corner buttons' areas reaching the
  screen's edge.
- Autoscroll and the key map tested under page zoom and in the WebView.

## Where it applies

- **The harmonica tab's page** (harptab.js, harptab_page.py; my call): the layers and Back, the theme, the screen
  timer, the key map, full screen, the words under its bar's buttons, the laptop toolbar, and the version-and-kind line
  with its list. It keeps its own header facts (the harp, "Read as") and its harp −/+ where the key is; no key list,
  no Harmony tab, no strip of chord shapes.
- **The songbook's songs** (book.js, book.py; my call): the three facts lines (Tuning, Capo, Key) and the line, bar-cell
  and two-column rules, since they share the viewer's renderer; no version line or icons (a songbook carries no versions
  data); its contents, pagers and ← → as today.
- **The version pages** (version-<tab>.html): everything a sheet.html has.

## The lane

Lane 5, `feat/sheet-*` branches from `main`, each stage merged as it passes (whole suite, corpus regenerated, gradle
with the Kotlin port following, `nix flake check`, the e2e test when the corpus moved):

| Stage | What |
|---|---|
| 5a Layers and Back | the history entry per layer, one layer at a time on a phone, full screen (D14) |
| 5b The header and the versions list | D1, D2 and the icons; page.py's markup and data, the Kotlin port |
| 5c Lines | D3, the unsplit word, D4's bar cells (with the PDF), D8's two columns, the sheet's end room |
| 5d The bar and panels | D9's glyph and words, D10's key and key list, D12's Harmony tab, D13's laptop toolbar, the deduplicated settings, 48 px targets |
| 5e Reading settings | D6's theme, D7's strip, the contrast fixes |
| 5f Hands-free | D15's highlight (the timed lyrics matched at build time, Python and Kotlin), D16's key map, D18's screen timer |

It owns src/caracole/viewer/ (viewer.js, viewer.css, page.py, harptab_page.py, book.js, overlay.js, instruments.js,
winds.js, harptab.js) and render.py's parts that feed the page's data, and their Kotlin ports in `:viewer`. It meets the
library lanes only at the library page's link to a sheet and at the play buttons' glyphs (lane 3's): it reuses those
glyphs' drawings rather than drawing its own.

## Left to the builder

The exact sizes not stated above; how bar beats are counted; the highlight's threshold and look; animation timing; the
key list's layout; where in More the screen-on setting sits; the order of stages 5c–5f after 5a and 5b.
