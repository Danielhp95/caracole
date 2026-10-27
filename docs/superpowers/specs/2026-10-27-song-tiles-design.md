# A song opened in the library: tiles, and each source's versions

On index.html a song's line unfolds under its "⋯" into one flat run of grey pills: its progressions, Fetch
again, Files (Sheet PDF, Sheet text, ChordPro, Lyrics, Timed lyrics, Harmonica tab 1 · harptabs.com, Tab,
Info), a group per Guitar Pro file, Add to a songbook… and Remove…. The owner's complaint: its affordances
aren't clear and it isn't pleasant to look at. What goes wrong:

1. Opening a sheet, downloading a file, finding the songs that play a progression and changing the song are
   the same pill: nothing says what a click does.
2. The opened song has no edge: its buttons run into the next song's line.
3. Formats of one thing are scattered (Sheet PDF, Sheet text, ChordPro; Lyrics, Timed lyrics; Tab far from
   Guitar Pro).
4. Fetch again floats unlabelled; Remove… sits beside Add to a songbook….
5. The closed line spends its room on "Found" (nearly every song) and on where files came from, not on what
   you can play; an instrument badge spills into the key's column ("HarmonAca").
6. "⋯" reads as a menu, but it unfolds the song in place.

The intent: one look at an opened song tells what you can play from it and where each came from, how many
versions each source has (Ultimate Guitar lists many chords versions of a song), what opens, what downloads
and what changes the song, with Remove kept apart.

## Decisions (the owner's, 2026-10-27)

Mockups in `.superpowers/brainstorm/` (gitignored): song-line-directions.html, direction A ("What you can play,
as tiles"); song-line-a-v2.html, its versions per source and Remove.

- **Tiles.** An opened song is a card (the line and its panel in one bordered box, raised over the list) whose
  core is a row of tiles, one per thing you play from. A tile's body opens the thing; its formats sit under it
  as downloads (↓); the sheet's tile is the accent one.
- **Versions per source.** Each tile has a row of chips, one per source, each the source's mark and a count
  ("Versions [UG] 13 [LaCuerda] 2", "Files [gtptabs] 1 [inbox] 1", "Tabs [harptabs] 3"). A tile with more
  than one version is drawn as a small stack. A chip opens that source's versions in a drawer: each version
  with what tells it apart, which one is in use, Open, and Use this one where one can be chosen.
- **Versions caracole hasn't kept are counted, not listed**: "10 more on Ultimate Guitar, not kept", and a
  button that fetches them when pressed (below: within a lookup's budget, so a press may keep only some).
- **Remove** says "Remove", no ellipsis, red from the start (outlined, `--failed`), alone at the footer's end.
  Its behaviour is unchanged: the line counts down five seconds with Undo.
- **The closed line**, as all three mockups drew it (not objected to): your song's line shows the title, icons
  of what it holds (sheet, guitar, harmonica, lyrics, score), its key as a small chip, its main action, and a
  chevron that turns when the song is open, in place of "⋯". The status badge shows only when the song needs
  something or isn't plainly yours (Wanted, Not found, Needs review, Ignored, Removed): no "Found". The
  sources' marks leave your songs' lines (the tiles say where each thing came from); a search hit's line (a
  site's song, `.line.hit`) keeps its marks and instrument badges, which say which site lists it, and no badge
  ever spills into the key's column.

## Approaches considered

- **A, tiles** (chosen): biggest targets, best on a phone at rehearsal, open-versus-download obvious; the
  tallest when opened.
- B, two columns (play on the left as a settings-style list with Open and ↓ at each row's end; facts,
  progressions and every change on the right): most orderly, but reads like a file manager.
- C, compact segmented controls (each thing one joined control, changes as icon buttons): shortest, but its
  icon-only actions need hovering to learn, and it wraps into a jumble on a phone.

For "fetch the ones not kept":

- **One press keeps as many as one lookup may** (chosen): `caracole versions --keep-more`, the next versions
  not kept in rank order, at the lookup pace, until the lookup's budget (`lookup_requests`, 6) or the hour's
  (`lookup_per_hour`) is spent; the rest stay counted, and the button keeps the next ones on the next press.
- All of them in one job: 10 tab pages is past a lookup's budget of 6, an invariant (AGENTS.md, Politeness).
- Queued for tonight's run: within the bulk budget, but the owner asked for them when pressed.

## The card, part by part

Order inside the opened card, top to bottom; a part with nothing to show is left out.

1. **The line**, as closed, its chevron turned (`aria-expanded="true"`).
2. **Facts**, one muted line: the key in words and where it came from, the PDF's transposition, the lyrics'
   state, when the song came, its other artists (today's `factsOf`).
3. **What needs you**, before the tiles, as today: the match picker or why there is none, the YouTube note,
   the LaCuerda pick note, Look in the index for a song not found. Their behaviour is unchanged.
4. **Tiles**, in this order, each only when the song has it:
   - **Chord sheet** (accent): opens the primary file (viewer, else PDF, else text). Named "Chord sheet", or
     "Auto sheet" for an auto one (in `--auto`'s colour, not the accent), "Ukulele chords" for UG's Ukulele
     Chords. Subtitle: what is in use ("Ver 3 · 4.86★ · in use" for UG's; "LaCuerda" for LaCuerda's; "from
     the recording" for an auto sheet). Versions chips: Ultimate Guitar's, LaCuerda's (when caracole met
     LaCuerda versions of the song). Downloads: PDF, Text, ChordPro (the auto sheet's own when that is the
     sheet), then each PDF export by its label ("PDF · G Dorian, capo 0").
   - **Guitar Pro**: opens its first Guitar Pro file in caracole serve's Guitar Pro page when served with
     alphaTab, else downloads it. Named "Guitar tab" when the song has a text tab (`tab.txt`) and no Guitar
     Pro file, and then opens the text. Files chips per source (gtptabs.com, your inbox). Downloads: the
     opened file's, and Text tab when there is one.
   - **Harmonica tab**: opens its first tab; Tabs chips per source (harptabs.com); Downloads: Text.
   - **Lyrics**: opens `lyrics.txt`; one source, LRCLIB, shown as "From [LRCLIB]" with no drawer; Downloads:
     Text, Timed (.lrc).
   - **Score**: a score you filed (`score-N.*`), opening the first; Files chip (your inbox); Downloads: each.
   A chip of one source with one version and nothing to choose is shown as "From [mark] name", no chevron.
5. **The versions drawer**, when a chip is open. One open at a time per card; the chip shows it open
   (`aria-expanded`, `aria-controls`), pressing it again or the drawer's ✕ closes it, and Escape inside it
   closes it and gives the focus back to the chip. It sits under the row of tiles that holds its tile,
   pointing at its tile; on a phone (one column) right under its tile.
   - **Ultimate Guitar**: "Ultimate Guitar · chord sheets", "13 versions on the site · 3 kept in your
     library". A row per kept version, in rank order: Ver N; rating and votes; what tells it apart (every line
     of the lyrics, or its share; the tabber's note; caracole's pick); In use for the one, else Use this one
     (served: `caracole versions --choose` as the versions page posts it); Open (its viewer page). A version
     UG no longer has is shown muted, "gone from Ultimate Guitar", with no Use this one. When a `[pin]`
     chooses the sheet, the header offers Back to caracole's pick (`--clear`). Then, when some aren't kept:
     "10 more on Ultimate Guitar, not kept" and, served, the button **Fetch them** (`--keep-more`; worded
     "Fetch 6 more" when more remain than one press keeps); from the file, the command that does it
     (`caracole versions --keep-more "<display>"`), as the file page gives other commands.
   - **LaCuerda**: its versions caracole met, best first: each its LaCuerda page (opens on the site, ↗) and
     its share of the lyrics; In use for the one that is the sheet, else Use this one (served: the lookup that
     keeps that LaCuerda sheet, `lacuerdaSheet`'s post today). No fetching: they are links.
   - **Guitar Pro, harmonica, score**: a row per file of that source: its label, Open (in the browser where
     caracole serve shows it), Download.
   Nothing in a drawer sends a request when it opens: it reads the page's data alone.
6. **Progressions**, "find your songs that play one": each a chip with a search mark, which filters the list
   (today's `setProg`), visibly unlike a file or an action.
7. **Find it elsewhere**: Find the chords, Scores on MuseScore, Buy the track for an auto sheet, whichever
   the song has, as links that leave caracole (↗), grouped as today.
8. **Footer**: Fetch again / Fetch now, Use LaCuerda's sheet (today's `againActions`), Add to a songbook…;
   then, at the far end, `info.json` as a quiet download and **Remove** in red.

## The fetch of versions not kept

- **`caracole versions --keep-more SONG`** (versions_cmd.py, beside `keep`): under the lock as a lookup takes
  it (`exclusive(..., interactive=True)`), one client from `make_client(..., interactive=True)`; for each
  version not kept, not the sheet, not gone and not under `[block]`, in rank order, `ug.fetch.keep_version`;
  stops at `BudgetExhausted` (the lookup's or the hour's), a block (`record_block`, as `keep` does) or an
  error (`record_error`), keeping what it kept before. Each kept one is noted as yours (`keep_version` does
  so), so the nightly fetch keeps it. Then `render_all` for the song once, and `write_pages` once.
  Exits 0 in every one of those cases; says "Kept 6 versions of <song>; 4 more not kept: ask again." or why it
  kept none. `--progress` reports the stages `song`, `version` (its detail counting: "kept 3 of 10"), `pdf`,
  `pages` and `done`, as `keep` does. Nothing left to keep: says so, keeps nothing, sends nothing.
- **Served**: `POST /versions/keep-more` (versions_routes.py, with the form token and the cross-origin check),
  one job queued under the song's key as the other versions posts are (jobs.py joins it), refused (409) for an
  ignored song or one with nothing left to keep. The card's line shows the job as any request, and once it is
  over the page's data comes again (`/jobs.json`'s view) and the drawer counts again.
- No request goes out but the tab pages: the drawer's counts come from the versions caracole already records
  (the sitemap index and the artist page it read), never a new search.

## The page's data (library_page.py)

- `versions` for every song whose sheet group has Ultimate Guitar versions recorded, not only those with some
  kept beside the sheet: `total` (versions UG still has), `kept` (the list with links, as today), `rest` (how
  many are neither kept nor the sheet nor gone), `pinned` (a `[pin]` chooses the sheet), and `keepMore` (how
  many one press keeps: the smaller of `rest` and the lookup's budget).
- `lacuerdaVersions`: the LaCuerda sheets caracole met for the song and LaCuerda still has (`versions` rows,
  provider `lacuerda`, slot `sheet`, not gone), best first, each its page, its coverage and whether it is the
  sheet.
- Files keep their `source`; the tiles group them by kind and source in library.js. What a line holds (its
  icons) is read from the files and `instruments`.

## Constraints

- AGENTS.md's page rules hold: nothing from the network; every element made with `createElement` /
  `createElementNS` and `textContent`; icons are inline SVG made that way (no icon font, no `<img>`, no style
  attribute: a drawer's pointer is placed with `style.setProperty`, which the CSP allows); index.html's assets
  stay the files of library_assets/, listed in `library_page.STYLESHEETS` / `SCRIPTS`.
- Both themes (light and dark tokens of base.css), 390 px without a horizontal scroll, 44 px targets on a
  touch screen (`pointer: coarse`), keyboard and screen reader: the chevron and the chips are buttons with
  `aria-expanded`; Remove, the downloads and the tiles say what they do in their accessible names ("Open the
  chord sheet of Hotel California", "Download the PDF of …").
- The file page (index.html opened from disk) shows everything but what needs caracole serve (Use this one,
  Fetch them, Back to caracole's pick, Remove, Fetch again), as today.
- Politeness: `--keep-more` is an interactive lookup within its budgets; nothing new for bulk work.

## Goals, non-goals, anti-goals

- Goals: the card above, on the served page and the file; `--keep-more` and its route; tests; docs (usage.md:
  the library page, `caracole versions --keep-more`); the README's screenshots retaken (docs/screenshots/make.py).
- Non-goals: the search hits' rows beyond the badge overflow; the sheet viewer's version switcher; the
  Songbooks tab; the requests page.
- Anti-goals: a request when a drawer opens; fetching past a lookup's budget; a red Remove that looks like the
  main thing to do (it stays outlined, never filled); losing anything the panel offers today.

## Settled after the builder check (my calls, to be checked by the owner)

- **Two kinds of choice.** A UG version chosen (Use this one) is a `[pin]`, which outranks a LaCuerda pick
  (get.py, ug/fetch.py `_sheet_slot`). So LaCuerda's Use this one shows only while no `[pin]` chooses the sheet;
  otherwise its drawer says "Your choice on Ultimate Guitar is in use: Back to caracole's pick first". Back to
  caracole's pick takes the UG pins out, as `--clear` does today; no new overrides writer.
- **What "not kept" counts**: `sheet_versions.may_keep` (b47f376), the versions a keep may still keep: neither
  kept nor the one nor gone, not under `[block]`, not at an address robots.txt closes, and none a keep found it
  can't keep (`no text`, `held`: `note_unkeepable`, kv `sheet_versions:unkeepable:<song id>`, in
  `songs._PER_SONG_KV`). A page that won't parse stays counted: it waits, as any does. So the button goes once
  nothing is left, and a press never re-reads a page it can't keep.
- **A kept version may become the sheet** at the next nightly run when it covers more of the lyrics, as one
  kept with `--keep` may today (caracole's ranking); Use this one (a `[pin]`) holds a choice.
- **An auto sheet beside a human one** is a chip of its own in the chord sheet's Versions row (the auto
  source's mark, 1); its drawer row opens the auto viewer and downloads its PDF, text and ChordPro.
- **MuseScore's links** show for every song not ignored, as today: Find it elsewhere shows whatever links the
  song has (Find the chords and Buy the track only come for a song with no sheet).

## Left to the builder

The exact icons' paths, spacing and the stack's drawing; how the drawer's pointer finds its tile; the class
names (keeping `line-more` and `line-panel` where tests and other scripts find them, or moving those with
them); whether Use this one posts in place or opens the versions page.
