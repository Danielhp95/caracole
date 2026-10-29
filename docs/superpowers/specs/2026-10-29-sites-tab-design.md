# The Sites tab: what caracole has from each website

caracole reads eight websites, but nothing on its pages says how much it has from each one, how far each index
has got, or what each site's robots.txt keeps it out of. The owner wants a tab that says so at a glance:
how many songs caracole has indexed from Ultimate Guitar, how many it has downloaded from it, and a few
other figures around those, plus a line or two on what robots.txt closes and each site's icon. It is for
the owner, the only user: to see that the sources are healthy and what each one gives, without opening the
database or reading `caracole index stats`.

## Decisions (the owner's, 2026-10-28 and 2026-10-29)

Mockup: `.superpowers/brainstorm/…/content/sites-ledger.html` (from `sites-directions-v2.html`, option B).

- **A tab, the third:** Library · Songbooks · **Sites** · Requests. Requests stays the last tab, and Sites goes
  just before it. It builds on branch `requests-tab` (473a8d1), which made Requests a tab and added
  library_assets/tabs.js, which reads the tabs from body.html's tablist (the `__TABREQUESTS__` blank ends it),
  with main merged in first: main's d19226e (the owner's, 2026-10-28) removed `http.ROBOTS_CRAWL_DELAY` and set
  gametabs.net to one request a second.
- **The ledger layout (option B):** one line per site, as your songs are lines. A header line: "Sites", then
  pills: how many sites, songs indexed in all, things kept from them, and last night's run (its start and end
  times, its requests). Columns: **Site** (icon, name, what it is for), **Indexed**, **In your library**,
  **Last night**, **Status**, and a chevron. A line opens under itself to show the rest (below). On a phone only
  Site, Status and the chevron stay on the line; the other columns move into the opened part.
- **Data baked into the page (approach 1, below):** the figures are part of index.html's data, as the Songbooks
  tab's are, so the tab works on the served page (fresh on every load) and in the file in the library (as of
  when it was last written, which includes the Android app's offline copy).
- **What each line shows** (the mockup's figures, which the owner accepted as they are):
  - **Indexed:** songs, as a number in its own unit ("642,318 songs"), and, where the site counts something
    else, that count in the smaller line ("1,284,310 tabs, from its sitemap"). For a site caracole indexes
    a little each night, a meter of how far it has got. A site with no index says how it is asked instead
    (LRCLIB "Asked song by song", YouTube "Searched song by song").
  - **In your library:** how many of the site's things caracole keeps for your songs, in the site's unit (UG
    and LaCuerda: sheets; LRCLIB: lyrics; gtptabs.com: Guitar Pro files; MuseScore: links; harptabs.com:
    harmonica tabs; gametabs.net: tabs; YouTube: auto sheets from its audio), and that as a share of your songs.
  - **Last night:** requests sent out of the night's budget (YouTube: yt-dlp runs), with a meter.
  - **Status:** OK, Indexing (its index is partial), Cooling down (after a block, with until when and why), Off
    (turned off in caracole.toml, or YouTube with auto-chords not installed). Each a badge with a word and a
    dot, never colour alone.
  - **Opened:** robots.txt in one plain sentence, then the closed paths that matter as code chips, each with its
    meaning as a tooltip; the site's terms note where it has one (harptabs.com, gametabs.net, YouTube: the
    exceptions AGENTS.md names, worded as the mockup words them); the index meter in full; caracole's pace
    with the site; and the last contact (the last request's time, and a cooldown or the last error, if any).
    Times are shown as dates and clock times, never "tonight" or "41 days ago", which go stale in the file.
- **Icons:** the ones the page already inlines (`data["icons"]`, icons.py `page_icons`): a site's favicon, or
  caracole's lettered badge where none was fetched (harptabs.com and gametabs.net today).
- **Robots words are written by hand; the paths come from caracole's own table.** caracole doesn't read
  robots.txt at run time: `http.ROBOTS_DISALLOW` lists each host's closed paths, pinned to the live files by
  tests. The tab names the few that matter per site, with words, and every one it names must be in that table
  for one of the site's hosts (a test checks), so the page never claims a rule caracole doesn't keep.

## Intent, goals, non-goals, anti-goals

- **Goals:** the figures above, per site, correct and in the site's own units; readable on a 390 px phone with
  four tabs on one line; light and dark, as every page.
- **Non-goals:** acting on a site from the tab (no "index now", no turning a site off): the tab only shows
  (my call: the owner asked for information only). No history over time, no charts beyond the meters. No
  count badge on the tab (my call: nothing there waits on you).
- **Anti-goals:** the tab must never send a request to any site, nor add one to building the page: every figure
  is read from the database, the config and caracole's own tables. Building the page (every served load of `/`)
  must not get noticeably slower. A partial index must never read as complete, and an error never as a miss.

## Constraints

AGENTS.md binds the page: every script and stylesheet inlined by hash (library_assets/, listed in
`library_page.STYLESHEETS` and `SCRIPTS`, test_library_assets.py), elements built with `createElement` and
`textContent`, the data a JSON block, nothing loaded from the network. The tab works on the page read from a
file, where no server answers. Docs (docs/usage.md) move in the same commit.

## Approaches

1. **Data baked into the page, like Songbooks (chosen).** `library_page.build_library_page` adds
   `data["sites"]` from a new module, sites.py; a new sites.js draws the ledger. Fresh on every served load,
   and a snapshot in the written file. Cost: the counting runs whenever the page is built.
2. **Served only, fetched when the tab opens** (`/api/sites`). No cost on page load and always live, but no Sites
   tab in the written file or the phone app's copy, and a loading state and fetch path to build.
3. **A page of its own (`/sites`).** Ruled out: the owner just moved Requests into the tab row so that it
   wouldn't be one.

The owner chose 1: the Library and Songbooks tabs work offline, and these figures mostly change overnight.

## How (decided)

- **sites.py** (new, outside commands/, a docstring that says what and why, as every module): `sites_data(conn,
  cfg, now)` returns the tab's data: the sites in icons.SOURCES' order (UG, LaCuerda, LRCLIB, gtptabs.com,
  MuseScore, harptabs.com, gametabs.net, YouTube; not the audio model or the inbox, which are no site), each
  with its figures, and the totals for the header. The hand-written parts (each site's role, robots sentence,
  named paths with their words, terms note) live there as data.
- **Where each figure comes from:**
  - Indexed: each site's own tables (`ug_index`, `lacuerda_index`, `gtptabs_index`, `musescore_index`,
    `harptabs_index` with `harptabs_artist_tabs`, `gametabs_index` with `gametabs_game_tabs`). "Songs" means
    distinct song keys in that site's index (UG: artist and song key; MuseScore has titles only, so titles).
  - LaCuerda (the owner's answer, 2026-10-29): the songs caracole knows lead, its song rows (`index_size`'s
    songs: the artist pages read, for your songs' artists, the popular ones and LaCuerda's search), never the
    site's own total. The smaller line gives that total, "of 41,870 its listings count", the sum of the `songs`
    the listings give each artist row, with the artists. The badge says OK once every listing is read
    (`index_state(...).complete`): caracole reads an artist's songs only when it needs them, so the songs it
    knows never reach that total, and that isn't an unfinished index. Indexing while letters are still unread.
  - Index progress: the existing `index_state` functions (lacuerda_index.py, harptabs_index.py,
    gametabs_index.py) and UG's `ug.index.index_coverage` while partial. LaCuerda's is shown as letters read
    (`letters_read` of `LETTERS`), since its listing pages' total isn't known until each letter's first page
    is read (my call: the mockup's "122 of 200 listing pages" can't be computed).
  - In your library: kept files by their version's provider (icons.py `kept_sources`, the YouTube case
    included); LRCLIB by songs with `lyrics.txt` or `lyrics.lrc`; MuseScore by the songs with a possible match
    the to-do page links (`musescore.song_pages`). The share is out of the songs the library page lists.
  - Last night: the nightly run alone, from kv `run:last` (pipeline.py's record of it: its start and end, each
    site's requests counted as the budget counts them, its budgets, blocks and errors; todo.py's health table
    reads it already). Not the latest run in `events`: every bulk command (`caracole fetch --song` from the
    review page, `caracole index build`, `caracole harptabs --index`…) has a run id of the same shape, so a
    daytime pick would read as "last night". An index read started by hand doesn't show here. The written file
    is made by the run's todo step before the run ends, so its record has no end yet: the header then gives the
    start alone ("last night from 03:00").
  - Status: `health.get_state` (cooldown, last error), `cfg` (`enabled`, `config.SWITCHABLE`),
    `youtube_fetch.route_problem` for YouTube, and the index progress.
  - Pace: the provider's `delay` (`cfg.provider(name).delay`) alone: since d19226e a robots `Crawl-delay` is no
    floor. gametabs.net's robots sentence says plainly that its robots.txt asks for 5 s and caracole asks once a
    second, by your choice (my call: the page never claims a rule caracole doesn't keep, and leaving the 5 s out
    would hide the one place caracole departs from robots.txt's pace).
  - Robots: the named paths are checked against `http.ROBOTS_DISALLOW`; "and N more" counts the rest. YouTube is
    the exception: its closed paths (`/results`, `/youtubei/`) aren't in that table, as caracole goes against
    them by the owner's choice, so its line names them from robots.txt and its sentence says so.
- **library_page.py:** `data["sites"] = sites_data(...)` for both the file and the served page.
- **library_assets/:** body.html gets the Sites tab button just before `__TABREQUESTS__`, and its panel
  (`#sites`, `#tab=sites` in the address through tabs.js); sites.css and sites.js are added to the lists, after
  tabs.js. sites.js draws from `data.sites` and the page's `icons`, reusing rows.js's way of drawing a source's
  icon. Opening a line is a disclosure button with `aria-expanded`.
- **Refresh:** on page load only (my call). The served page doesn't redraw the tab after a job ends; a reload
  shows the new figures.
- **Speed:** measure `sites_data` against a database with a full UG index (about 1.28 M rows). If it adds more
  than 50 ms to building the page, each index records its song count when it is refreshed (kv, written where the
  index is) and sites_data reads that instead. Counting distinct songs in `ug_index` probably needs this.
- **Tests:** sites.py, a test per figure against the `conn` fixture (an empty database too: zero indexed, no run
  last night, which the tab shows as "—" and "No run yet"); the named robots paths each in `ROBOTS_DISALLOW`
  (YouTube's aside);
  the three terms notes present; the page's data holds `sites`. In Chromium (`@in_chromium`): the tab at 390 px
  and 1280 px in light and dark, four tabs on one line with no sideways scroll, a line opened by click and by
  keyboard, and the written file (no server) drawing the tab.
- **Docs:** docs/usage.md's library page section gains the Sites tab and what each figure means; AGENTS.md's
  layout table gains sites.py. The README's library picture is retaken if it shows the tab row.

## Left to the builder

The exact query per site; the wording of the sentences, starting from the mockup's; whether several lines can be
open at once; how a time is shown (stamps.py, local as the Requests tab shows times); how a provider whose last
run failed without a block reads (an error note on an OK line, say); and the phone layout within 390 px.
