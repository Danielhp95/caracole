# The library page, redesigned

Status: approved by the owner on 2026-11-17, to be planned and built in four lanes. Research: `.claude/handoff/ui-research-2026-11-17/`
(local, not in git; its report is `reports/Library page UI UX research.md`). Mockups of each decision beside this file in
`2026-11-17-library-page-redesign/` (fragments drawn for the brainstorming companion's frame: open them there, or
read them as markup).

## Why

The owner wants the library page (index.html, caracole serve's `/`, and the same page in the Android app's WebView)
to be nicer to use, with Ultimate Guitar's app as the reference. The research (2026-11-17) found the page's patterns
mostly sound and its problems concrete: too few songs per phone screen (a one-song artist costs about 108 px), search
squeezed under the keyboard, Android's Back leaving the app instead of undoing what the page opened, a progress row
of chips that wraps, a laptop list whose title and key sit about 1,100 px apart, and a page where borders and bold
compete everywhere. The owner chose each change below from side-by-side mockups.

## Goals

- More songs on a phone screen, and a list that reads at a glance.
- Search that works with the keyboard up, and a Back that undoes what the page opened.
- A request's progress readable in one row.
- A laptop layout that uses its width.
- A calmer page, the same caracole: its colours, logo and font unchanged.

## Non-goals

- No change of accent colour, neutrals, logo mark, wordmark colour or font (the owner looked at copper accents, a
  simplified mark and an inlined font, and chose today's).
- No bottom navigation bar, no card as a bottom sheet, no per-site result tabs, no trailing A–Z index, no
  virtualized list.
- The sheet viewer, the songbook viewer and the harmonica page are untouched, except where a shared asset changes.

## Anti-goals

- A big-bang redesign that has to be rolled back (UG's July 2026 tab page): every lane merges in small steps, each
  checked on screen.
- Anything pinned over the list or the sheet, or any promotional or nagging element.
- Losing what the page already guarantees: nothing loaded from the network, the same page served and from a file,
  find-in-page, the list's structure for a screen reader, `#by=`/`#tab=`/`#sheet=` addresses.

## Constraints

- The pages' rules in AGENTS.md ("The pages caracole writes and serves"): no network, inline assets allowed by hash,
  elements built with `createElement`/`textContent`, served or from a file, one page in a WebView too.
- library_assets/ is copied byte for byte into the Android app and exported into the conformance corpus: a change to
  it, to `web/outcome.py` or `web/status.py` regenerates the corpus in the same commit, and
  `nix develop ./android -c gradle -p android test` passes before it merges. `outcome.py` and `status.py` have Kotlin
  ports (`server/jobs/Outcomes.kt`, `Status.kt`, `JobViews.kt`) that change with them.
- Tests first; browser tests marked `@in_chromium`; the whole suite before each merge; docs/usage.md, AGENTS.md and
  the README's screenshots kept in step.

## Approaches

1. **Six batches in sequence**, each a branch merged as it passes: the safest, the slowest.
2. **Four parallel lanes split by file** (chosen): one lane for the list page's own scripts and styles, done in
   stages; one for progress (Python and its Kotlin port); one for the card and the play buttons; one for Songbooks.
   Fastest, with one known meeting point (below). The owner's usual way of running work.
3. **A clickable prototype first**, then 1 or 2: catches how things feel, at the cost of a round.

The owner chose 2.

## What the owner decided

### The phone list (lane 1)

- **Artist bands, 34 px** (mockup `phone-rows.html`, A1): an artist with two or more lines gets a band 34 px tall,
  the artist's name in the accent at about 14.5 px, bold, and on the right, muted, the count of your songs (in search
  results, what the band shows today: yours and each site's counts).
- **A one-song artist folds into its line**: a line of about 64 px whose first line is the artist's name as a small
  overline (about 11.5 px, bold, uppercase, letter-spaced, in the colour artist names use) and whose second is the
  title. A group folds only when it holds exactly one line and nothing else (no "+ N more", no "Did you mean" band).
- **No filter icon, and no "one artist" view.** The funnel (rows.js `artistOnly`) goes everywhere, and so does the
  view it led to, the owner's choice: `state.artist`, the `#artist=` address, the toolbar's "by X" tag and its place
  among the Filter panel's filters. Tapping an artist's name keeps doing what it does today when served: it searches
  for the artist (library.js `searchFor`). From a file, where the page can't search the sites, the name puts the artist
  into the search box, which searches your songs (today it was the funnel's filter, `artistFilter`). The viewer's
  `index.html#by=<name>` link reads as that same tap, and so does an old `#artist=` address (my call, so old links
  still land somewhere useful).
- **Title sort** (Title A–Z): every line uses the folded shape, artist above title.
- **Tap targets**: on a phone (`pointer: coarse`), anything tappable at least 24 px tall (the play buttons' 48 × 48 px
  hit areas are lane 3's, below).

### Play buttons (lane 3; mockup `play-buttons.html`)

- **Phone: today's tiles**, the icon in a tile with the site's letters on its corner, those letters grown from 6 px
  to 8 px (the owner's mockup choice; the 8 px is my call, which the owner didn't object to). On a phone each hit area
  is at least 48 × 48 px with 8 px between them.
- **Laptop: labelled chips**, the kind and the site in words: "Chords · UG", "Tab · UG", "Guitar Pro · gtptabs",
  "Harmonica · harptabs", "Chords · LaCuerda", about 28 px tall. Which one applies is by pointer, not width:
  `pointer: fine` gets chips, `pointer: coarse` tiles (my call: a laptop with a narrow window still has a mouse).

### Navigation on the phone (lane 1; mockup `phone-navigation.html`, A)

- The same top tabs, each a larger target (about 48 px tall, more padding).
- **In the app, no library-name row**: the app's own bar already says "Phone · caracole · <name>". The phone's page
  carries a flag saying it is the app's (a `WebControls`/`ServerControls` member, my call on its name), and the name
  row is not drawn under it. The phone's viewer pages keep their badge.
- **In a phone browser**, a library with a badge (Demo, Scratch) shows the badge as a small pill in the tab row, not a
  row of its own (my call; the owner didn't pick). Without a badge, nothing, as today. Five tabs that don't fit 390 px
  scroll sideways.
- **Back**: leaving Library for another tab adds one history entry, so Back returns to Library; moving between the
  other tabs replaces it. Today tabs.js only `replaceState`s.

### Search (lane 1; mockup `search.html`)

- **Search takes the phone screen** (under 720 px): on focus, or with text in the box, the logo-and-tabs row slides
  up out of the way (animated; instant under `prefers-reduced-motion`) and comes back when you leave search. Leaving
  is a ← at the left of the box (its accessible name "Back to your songs"), or Android's Back; × at the right clears
  the text and keeps the focus. "Back to your songs" as a row of its own goes. Owner's choice: hide, not scroll away.
- **Back leaves search**: entering search from an empty box adds one history entry; ← and system Back pop it.
- **The count row** (rows.js `countMarks`, owner's A): your songs' mark (the logo) and count first, then only the
  sites that found something, then one quiet mark for the rest, "0 on N more", with their names in its tooltip and
  accessible name. No row at all when every count is 0. On a laptop the sites may be named in full where the row fits
  on one line (my call); on a phone, their letters.
- **Keyboard**: scrolling the results dismisses it; the page's viewport meta gains `interactive-widget=resizes-content`
  (Chrome on Android; the app already resizes).
- **Nothing found** (rows.js `nothingFound`): the query in normal text, the line "Nothing for “…” in your songs or the
  sites' indexes" (no longer "Not on the sites", which claims more than the local indexes know), and Request as the
  one filled button, right under the query on a phone and right after it on a laptop; Ask LaCuerda stays secondary.
- **Recently opened**: with the box focused and empty, up to five songs opened from this device most recently, newest
  first, each opening what it opened before. Kept in `localStorage` (wrapped in try/catch: a private window has none,
  and the page works without it), on this device alone, never synced.

### Progress (lane 2; mockup `progress.html`)

- **A segmented bar on a closed line** (owner's A, in the app's orange): one segment a step, done in the accent,
  running a lighter accent that pulses (steady under `prefers-reduced-motion`), waiting a neutral grey, a skipped step hollow,
  a failed one in the failure colour with a "!" glyph; then the step in words: "Sheet · Ultimate Guitar · 3 of 7".
  One row, never wrapping. It replaces today's status line and chips on the line.
- **A fixed total**: the job's steps are fixed when it starts; a skipped step keeps its place and counts as done, so
  "3 of 7" only rises and the bar never reflows (today `outcome.progress` drops a step whose stages all skipped, so the
  total can shrink).
- **Nothing for the first second**: a job that ends within about 1 s draws no bar.
- **Queued**: today's words (status.py's "Queued · 1 request ahead…") with Cancel beside them on the line (my call to
  keep the words; the mockup's "Waiting · 2nd in line" was illustrative).
- **When it ends** (my call, keeping today's behaviour): the outcome line stays as today, with its words and links
  (Pick, Details, the to-do page) and as the line's live region. A request that ends otherwise than Ready keeps its bar
  under that line, frozen where it stopped (the failed segment marked), in place of today's chips; one that ends Ready
  folds away as today, its line opening the sheet.
- **The open card and the Journal**: a list, one line a step: a glyph, the step and its site, what it found. No times
  (the stages record none; the mockup's "0:01" was illustrative, my call to drop them). When the request ends,
  skipped steps fold into one muted line.
- The Kotlin port follows: `Outcomes.kt`, `JobViews.kt`, and whatever the corpus's job-view vectors pin.

### The laptop (lanes 1 and 3; mockup `laptop.html`, B)

- **From 1200 px wide: the list and a card pane.** The list about 760 px wide on the left, the selected song's card in
  a pane on the right (about 400–480 px). Selecting a line (its title or chevron) shows its card there; the line is
  marked selected. No card selected: the pane says so quietly, or holds nothing (my call: a short muted line).
- **Narrower than 1200 px: one column**, about 800 px, the search bar and count row in it too, the card opening in
  place under its line, as on a phone.
- The pane is the same card (card.js), not a second one; the key keeps a fixed column so it doesn't drift.
- Opening a card on a laptop adds no history entry (my call); on a phone, the card's ⋯ menu does (below).

### The card (lane 3)

- **Phone**: one row per tile; Fetch again, Add to a songbook and ⋯ (Remove inside it) right after the tiles; PDF,
  Text and ChordPro inside each tile's drawer; "On the sites" and Progressions last; the card's head sticks under the
  sticky search bar while you scroll through a long card; closing scrolls its line back into view.
- **Versions**: a rating as "★ 4.85 (81)" (the vote count always shown), "New" for one with no rating; versions
  grouped by kind, as the tiles already are. Naming a version by what differs (UG's "Acoustic") where the data has it
  is the builder's call.
- **No new panels** (my call): Remove keeps its five seconds with Undo on the line, Add to a songbook keeps opening
  Select mode with the song picked. The ⋯ menu, while open, adds a history entry, so Back closes it.
- **Built on first open**: a song's card is created the first time it opens, not with the list.

### A calmer page (lane 1, its last stage; lane 3 for the card)

- Fewer borders: no outline around the list, around play tiles (a filled tile keeps its shape; my call) or around the
  key, which becomes plain muted bold text. Row dividers stay.
- No bold fight: song titles semi-bold (600), artist bands bold in the accent, counts and keys muted.
- At most four corner radii across the page (my call on the values).

### Long lists (lane 1)

- `content-visibility: auto` with `contain-intrinsic-size` computed from each group's line count, on artist groups
  (or runs of 30–50 folded lines), never on single lines; one inline SVG sprite for the icons (`<use>`).
- No layout reads across many lines. Measured before and after on a synthetic library of 2,000 songs, on a phone.

### Songbooks (lane 4)

- A Play button on each songbook in the Songbooks tab that opens its songbook viewer at its first song.

## Where it applies

The changes follow the shared code wherever it is used (my call: no fork): caracole serve's lookup page gets the same
count row and "nothing found" (rows.js, rows.css), and its own pages (the message, review, versions and harmonica
pages, the guitar page, the phone's MessagePage and GuitarPage) the calmer base.css. Their vectors and tests move with
them.

## The lanes

Each lane is a branch from `main` in a worktree of its own, merged into `main` as soon as it passes (whole pytest, the
corpus regenerated, gradle), in stages where it has them.

| Lane | Owns | Stages |
|---|---|---|
| 1 · The list page | library.js (all but lane 2's functions below), tabs.js, select.js, rows.js (all but the play buttons), body.html, head.html, base.css, library.css, filter.css, rows.css (all but the play buttons), sync.css, library-screens.css, sites.css, picker.css, library_page.py and the app flag (Python and its Kotlin LibraryPage) | 1a navigation and Back; 1b the phone list (bands, folding, no funnel or one-artist view, tap targets); 1c search; 1d the card's order on a phone, its sticky head, building it on first open, and the laptop's list-and-pane layout; 1e long lists; 1f the calmer page |
| 2 · Progress | web/outcome.py, web/status.py if needed, steps.css, requests.js, requests.css, the Kotlin ports and their vectors, and in library.js the functions that draw a request's progress on a line (`showLine`'s steps, `drawSteps`, `progressIn`) | one |
| 3 · The card and play buttons | card.js, card.css, and the play buttons' rules (moved from rows.css into card.css in this lane's first commit) | 3a play buttons (phone badge and hit areas, laptop chips); 3b the card's insides (ratings and votes, "New", downloads inside each tile's drawer) |
| 4 · Songbooks | songbooks.js, songbooks.css | one |

**The meeting points** (my call on who owns what): library.js is lane 1's but for lane 2's three functions; lane 3
keeps card.js's entry point (`caracoleCard`) and the parts it hands library.js, which lane 1 orders and places (in the
line on a phone, in the pane on a laptop). Lane 1 doesn't edit card.js or `.play` rules, lane 3 doesn't edit
library.js, and lane 2 only its three functions; a need to cross is raised, not done. Whichever lane merges second
rebases onto the first.

Each lane updates docs/usage.md and AGENTS.md for what it changed. The README's screenshots are retaken once, after
the last lane merges (docs/screenshots/make.py), keeping only those that changed.

## Measurements before building

These change details, not decisions: the share of one-song artists in the owner's library (how much folding gains);
lookup times (whether 1 s is the right threshold); the keyboard's height in the WebView on the owner's Sony
XQ-DQ72; frame times on 2,000 songs. Lane 1e measures the last before and after.

## Left to the builder

How each stage is tested and in what order within its lane; the exact sizes and radii not stated above; animation
timing; the app flag's name; naming versions by what differs; what an empty pane shows; where the recently opened list
sits in the empty box's dropdown; what the lookup page's and caracole serve's other pages need, beyond the shared
code, to look right after the change.
