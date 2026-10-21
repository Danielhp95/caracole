# Several versions of a song's sheet, and the one you choose

Owner's request (2026-10-21): "Normally Ultimate Guitar will keep different tabs, and I would go through some of
them and choose the one that I like the most. I want to be able to have multiple tabs and choose the one I like
most, so that when I click the title it takes me to that tab. And clicking the title brings me to the tab that
has the highest rating."

## Today

- caracole records every chords version UG lists for a song (`versions` table: rating, votes, UG's version
  number; Wonderwall has 13) and downloads the top `RankPolicy.scored_sheets` (3) by rating to score their
  lyric coverage against LRCLIB. It keeps one as `sheet.txt`/`sheet.json`, and the title, the PDF, the
  viewer and songbooks all use that one.
- Which one: a complete sheet (coverage ≥ 0.8) first, then the rating weighed by votes (rank.py `bayes`,
  m = 10). Wonderwall keeps tab 1064463, 4.86★ from 408 votes ("the version that oasis play on Wembley
  2008"), over 39144, 4.85★ from 12,629.
- `caracole get "A - T" --tab URL|ID` makes a tab the sheet and records it under `[pin]`. The page offers no
  way to see or choose versions.

## Decisions (the owner's, 2026-10-21)

1. With no choice of yours, the title opens the best rating weighed by votes (today's `bayes`).
2. Among those with the lyrics: a version missing most of them (coverage < 0.8) never opens first, but stays
   in the list to switch to (today's complete-first rule).
3. caracole keeps the top 3 versions: the three it already downloads to compare, so no extra requests.
   The rest are listed with their ratings and fetched when you open one.

## What it does

- **Kept versions.** A song's three best chords versions, by the rule above, are kept in its folder beside
  the sheet, each with its own viewer page (no PDF of its own). The chosen one stays `sheet.txt` and
  `sheet.html` as today, so every existing link, the PDF and songbooks keep working unchanged. When the
  ranking changes (new versions, new votes), the kept set follows it; files caracole wrote for a version
  that leaves the set are deleted by the removal rules (only what caracole wrote, by name, no link followed).
  A version you chose is always kept.
- **The viewer's version switcher.** On every kept version's page: "Ver 3 of 13 · 4.86★ (408) · the one",
  with ‹ › to step through the kept versions in rank order and a list of all of UG's versions (rating,
  votes, kept or not, the first lines of the tabber's note when there is one). Each version opens in the
  same tab (the served viewer's sandbox).
- **Make this the one.** On a version's page. Served: a form post that queues `caracole get --tab` for it
  (recorded under `[pin]`, as today), then the title, the PDF, the viewer's default and songbooks use it.
  From the file: the command to copy. A way to go back to caracole's pick (clearing the pin), on the page
  and in the CLI.
- **A version not kept** (the 4th and beyond): served, opening it from the list fetches it now, at the lookup
  pace (one tab page), and keeps it as a version without choosing it; from the file, the list links to UG's
  page and shows the command.
- **The library page.** A song's ⋯ lists its kept versions (rating, votes, which is the one) and links each
  viewer; the title opens the one. The ⋯ "Versions" heading lane E uses for PDF exports is renamed so the
  two don't read alike.
- `caracole get` says which version it kept and which are kept beside it; `caracole search` and the to-do
  page are unchanged.

## Not in this

- LaCuerda's versions and auto-chords: the sheet slot can hold a LaCuerda or auto sheet; this design covers
  UG chords versions. A song whose sheet is LaCuerda's shows its UG versions to switch to if UG has the song.
- Tabs (`tab.txt`) and Guitar Pro picks: unchanged.
- A PDF per version: Export PDF of this version (lane E) already makes one from any viewer.

## Constraints

- Politeness: no extra request in the nightly run (the three are already read); a version fetched from the
  list is an interactive lookup (`make_client(..., interactive=True)`, its budget and hourly cap).
- Errors are never misses; a version page that won't parse is not kept and waits.
- The library is synced: `library.write_atomic`, records of what caracole wrote, removal only of those.
- Served pages keep their CSP and sandbox; file:// pages keep working.

## Left to the builder

File names for kept versions (beside the sheet, named by UG's version number or tab id), the switcher's
exact look within the viewer's bar, where the list of all versions lives (a panel like the settings), and
the CLI to clear a pin.
