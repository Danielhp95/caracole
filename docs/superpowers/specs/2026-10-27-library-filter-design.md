# The library's filters in one Filter button, with instruments

The library page's toolbar (body.html `.toolbar`) is the Show chips (All, Found, Wanted, Needs review, and an
artist's chip), Select (select.js's `.pick-toggle`, which starts picking songs for a songbook, set among them),
and two native menus, Key and Sort. There is no way to ask for an instrument ("my harmonica songs"), Select
looks like a filter, three kinds of control do one job, and nothing near the list says what is filtered.

## Decisions (the owner's, 2026-10-27)

Mockups (gitignored, in the main checkout): `.superpowers/brainstorm/2818486-1793122579/content/`
library-filter-directions.html, direction B ("One Filter button, everything inside"); library-filter-b-v2.html,
take **B.1** ("A popover under the button; a bottom sheet on a phone").

## The toolbar

Left to right: the active filters as tags, each removable (×), then Clear (all filters, never the search) when
any is on; at the right, **Filter** (a sliders icon, "Filter", and a count of filters on when there are any, the
button in the accent then), **Sort** (a sort icon and the order's name: Artist A–Z, Title A–Z, Recently added;
it stays the native `#sort` select, styled as a button), a thin divider, and **Select** (a checkbox icon,
"Select"), set apart from the filters. The artist's filter (today's `#artist` chip, the funnel's) is one of the
tags ("by Eagles ×"). The progression filter's line (`#prog`) stays as it is.

Tags read: "Wanted", "Needs review", "Found" (Status, not All); "Harmonica", "Guitar tab"… (each instrument, with
its glyph); "A minor", "Major", "Minor", or "A" (a key, a mode, a tonic in either mode); "by <artist>".

## The Filter panel

On a computer (from 720 px) a popover under Filter: a non-modal dialog (`aria-expanded`/`aria-controls` on
the button), the list behind it filtering as you tap, no Apply. A click outside it, Escape or Filter again closes
it; the focus goes back to Filter. On a phone (below 720 px) a sheet from the bottom over a dimmed page, ending in
**Show N songs**, which closes it (the list filters as you tap there too). In it, top to bottom:

1. **Status**: a segmented control, All · Found · Wanted · Review, each with its count (Review only while a song
   needs it, as today's chip). It is today's `show` (`SHOWS`), the same values.
2. **Has something for** ("any of these"): a chip per instrument, each its glyph (rows.js `glyph`), its name and
   its count; any number on at once, a song showing when it has any of those on. A chip with no song is greyed
   and disabled. What each means, from the song's data:
   - Chord sheet: a human or an auto sheet (a primary file);
   - Guitar tab: a Guitar Pro file (`guitar-N.*`) or a text tab (`tab.txt`);
   - Ukulele: `instruments` holds "ukulele" (UG's Ukulele Chords sheet);
   - Harmonica: `instruments` holds "harmonica" (a harptabs.com tab);
   - Score: `instruments` holds "score" (a score you filed).
   These are the closed line's `holds` (rows.js), read the same way. While any is on, each line's glyph of an
   instrument that is on is drawn in the accent.
3. **Key**: a segmented control, Any · Major · Minor, then the twelve tonics in a grid in circle-of-fifths order
   (C G D A E B F♯ D♭ A♭ E♭ B♭ F, two rows of six), each named as the page names keys; a tonic with no song in
   the mode chosen is dashed and disabled. Mode alone filters by mode; a tonic alone, that tonic in either mode;
   both, that key (today's Key filter). Pressing the chosen tonic again lets it go.
4. **Clear all** (as Clear) and, at the right, how many songs show ("4 songs"; on a phone the Show N songs
   button).

Counts: each option's count is the songs that would show with it chosen and the other groups as they are (the
search and the artist's filter included).

## State

In the address as today's filters are (`save()`, `addressed()`): `show=`, `key=` (an exact key, today's values,
so old links keep working), `mode=major|minor`, `tonic=` (a key id's pitch class, in the page's spelling),
`inst=` (a comma-separated list of `sheet`, `guitar`, `ukulele`, `harmonica`, `score`). Each filter's empty-list
message ("No songs in A minor. Show all") covers instruments and modes too, naming them.

## Constraints

- AGENTS.md's page rules (createElement only, nothing from the network, assets in library_assets/ listed in
  `library_page.STYLESHEETS`/`SCRIPTS`, both themes, 390 px with no horizontal scroll, 44 px targets under
  `pointer: coarse`, keyboard: Tab order follows the panel, arrow keys within a segmented control).
- Served and from a file alike (the panel needs no server). The Android app's copy of index.html is the file's.
- select.js's Select keeps its behaviour; only its place and look change.
- Search results (the sites' rows under the bar) are not filtered by instrument: the filters are your songs'.

## Left to the builder

Positioning the popover (it stays within the viewport), the sheet's animation (none under
`prefers-reduced-motion`), class names, how the counts are computed efficiently.
