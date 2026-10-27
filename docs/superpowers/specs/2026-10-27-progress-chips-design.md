# A request's progress as step chips, under the song's line

The library page said how a lookup went in one line ("Fetching from Ultimate Guitar…", then "Ready · Open
sheet"). The requests page already drew a running lookup's steps as chips (Song, Match, Sheet, PDF, Lyrics,
Extras, Songbooks). The intent: the same chips where you asked, under the song's line, so you see what is done,
what runs and what is still to come; and where the sheet came from, so a Spanish song UG lacks reads as such,
not as a failure.

## Decisions (the owner's, 2026-10-27)

Mockups: progress-chips-v2.html, option A with sources, its "Folded" ending; progress-shapes.html, option A.

- **While a song is looked up** (Fetch now, Fetch again, a search result's Get it, Get the missing songs, the
  Songbooks tab's Add a song, Try again: any request that runs `caracole get`), a row of chips under the song's
  line: Song · Match **UG** · Sheet **UG** / **LaCuerda** · PDF · Lyrics · Extras · Songbooks. Done chips green
  with ✓, the running one lit, the rest grey: the requests page's chips, shared, not copied.
- The running line keeps its words and gains a count: "Fetching the lyrics from LRCLIB… · 4 of 7 done".
- **Match** says the index it matched in, always UG's offline index today: "Match UG". A song that index lacks
  reads "Match: not on UG", drawn plain (dashed border, muted), never as a failure: the sheet may come from
  LaCuerda.
- **Sheet** says the site: "Sheet" until it asks one; "Sheet UG" or "Sheet LaCuerda" while it runs, switching
  when the stage falls back from one site to the other; once done, where the sheet came from, read from the
  song's state, never guessed.
- A step that turns out not to apply drops out and the count shrinks (outcome.py's rule: a step whose every
  stage ended skipped is not drawn; Songbooks not drawn for `--no-songbooks`).
- **Ends well** (Ready): the chips fold away and nothing replaces them, no "Ready · Open sheet". The line shows
  the song's status (Found), and its Open or its title opens the sheet, as for any song. A search result's row
  the same: the song as yours, with its Open.
- **Ends otherwise** (Not found, Needs review, Not fetched yet, Failed): the line keeps its words and next step
  ("Needs review · Pick the match"), and the chips stay, so you see which step stopped.
- **Elsewhere**: the same chips under a search result's row while its Get it runs; the requests page's chips
  take the same names (Match UG, Sheet LaCuerda); the corner tray keeps one line per request, a finished good
  one saying just "Ready", its song's name opening the sheet. Requests that run no lookup (a songbook's make, a
  removal, an export, a LaCuerda artist read or search) keep their single line.

## How

The server computes everything; the page's scripts only draw.

- **get.py** says the sheet stage's site whenever it asks one (`SHEET_FROM`, its running detail), Ultimate
  Guitar alone included (before, only once LaCuerda was one of them), and names its match words for a song the
  index lacks (`MATCH_NOT_FOUND`).
- **jobs.py**: a `Stage` keeps what it said last while it ran (`running_detail`), so a sheet that failed names
  the site it asked; `Job.looks_up` says whether a request runs a lookup.
- **outcome.py**: `Chip` gains `source` ("UG", "LaCuerda") and the `plain` state; `steps(job, facts)` names
  Match's index and Sheet's site (running: the running detail; failed: the last site asked; done:
  `SongFacts.sheet_from`, the kept sheet's version's provider, as icons.py tags it). `progress(job, line, facts)`
  is what the library page draws: `steps` and, while it runs, `count` ("4 of 7 done", a plain step being over);
  nothing for a request that runs no lookup, one queued or cancelled, and one that ended Ready.
- **status.py**: the line keeps being the one line. `song_line` is how a song's line says it: "Ready" with no
  link. The requests page's outcome still reads the line with its link (its Open).
- **jobs_routes.py**: `/jobs.json`'s view carries `line` as `song_line` says it, `sheet` (the sheet's link, for a
  Ready line: the tray's song name opens it), `steps` (`[{name, source, state}]`, states waiting, running,
  done, failed, plain) and `count`.
- **library_assets/steps.css**: the chips' look, shared by index.html (`library_page.STYLESHEETS`) and the
  requests page (`pages.PAGE_STYLE`), the same markup (`ol.step-chips > li.step-chip`, a ✓ or ✕ hidden from
  screen readers, the site in bold, the state in words for a screen reader alone). The requests page's chips
  stretch across its card; the library page's keep their size.
- **library.js**: `showRequest` draws a song's line, a result's row or a line under the bar: the request line
  with its count (`showLine`), then the chips (`drawSteps`), built with createElement and textContent. The chips
  are a list under the line, not part of its live region: the line, with its count, is what a screen reader
  hears change. A line drawn again around its request line (`refill`) keeps its chips too. The tray and the
  Songbooks tab's set lists keep the one line (`showLine`).

## Left to me

- **How Ready folds.** The request line stays in the page (its live region, read out to the last) with its
  words for a screen reader alone (rows.css, on a song's line or a result's row); the chips go. The focus Fetch
  now gave the request line goes to the line's Open, which took Fetch now's place: a focused line no one can
  see would lose the keyboard.
- **No chips while queued.** A request waiting its turn says its place, "Queued behind 2 requests…"; the chips
  come once it runs.
- **The count only while it runs.** Ended otherwise, the line's words and next step say how it ended; the chips
  show which step stopped.
- **Needs review's Match** is "Match UG", done: the index found candidates there; the line says the rest.
- **A failed Sheet** names the site it was asking when it failed ("✕ Sheet LaCuerda").
- **The Songbooks tab's set lists** keep their one line, "Ready" with no link now (its title opens the sheet):
  chips there would move the set list while you look at it.
- **caracole serve's own lookup page** (/lookup, lookup_page.py), which follows a request on `/api/jobs`, is
  unchanged.
