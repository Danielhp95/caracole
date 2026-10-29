# A new source, piece by piece

What each touch point is for, the decision it needs, and how gametabs.net (2026-10-28) and harptabs.com (2026-10-26)
answered it. `scripts/touchpoints.py gametabs` shows the exact lines today; this file says why they are there.
`<site>` below is the provider's name (one word, lowercase: `gametabs`), `<Site>` its class prefix (`GameTabs`).

## Contents
1. Decisions to make first
2. The provider's own modules
3. Settings, robots and politeness
4. Schema and per-song state
5. The nightly step
6. Files kept, picks, removal
7. A lookup
8. Commands
9. Search
10. Marks, library page, serve
11. Viewer and render
12. Nix and docs
13. Tests

## 1. Decisions to make first

Settle these with the owner where they change what caracole keeps or shows; settle the rest yourself and say so.

| Decision | gametabs.net | harptabs.com |
|---|---|---|
| What is kept, and as what file | the page's inline text tab, `gametab-N.txt`, kind `gametab` | the tab's text, `harmonica-N.txt`, kind `harmonica`, plus a rendered page `harmonica-N.html` |
| How a wanted line matches | track title, and artist = the game or a composer | title, artist confirmed on the tab page |
| Where the index comes from | sitemaps (games, tabs) + a game-page pass for composers | sitemap (tabs by title) + an artist-page pass for artists |
| Candidates read per song | at most 4, most viewed first | `CANDIDATES` = 8 |
| Nightly budget / delay | 20, 10–20 s (Crawl-delay 5) | 20, 10–20 s (the owner later ran 2.5–5 s by hand for the index) |
| Login-only content | never (GP5/MIDI/PDF needed an account) | never |
| A miss | candidates all answered, none matching; asked again after 30 days | the same |
| Terms against bots | the owner's choice to read anyway, recorded in AGENTS.md | the same |

## 2. The provider's own modules (new files)

- `src/caracole/<site>.py`: URLs (`page_url`, the slug's keys), parsing of every page kind it reads (tab page, index or
  listing pages, sitemap rows), its `<Site>ParseError` (a page that won't parse is an error, never a miss), what its
  robots probe found. Pure: no client, no database.
- `src/caracole/<site>_fetch.py`: the step. A song's candidates from the index, each read once (`http.read_once_more`
  for a cached page that won't parse), the artist confirmed on the page, the kept file written with
  `library.write_atomic` at the lowest free number, its version recorded, `<site>:checked:<song id>` for a miss.
  Errors never misses (provider_pass.py's ladder). `<Site>Stats` for the report.
- `src/caracole/<site>_index.py` (when a sitemap alone can't name what a wanted line names): a pass over listing
  pages, resumed across runs, your songs' entries first, each page again after 30 days, within a budget;
  `index_state` (how far it has got) for `caracole index stats`.

## 3. Settings, robots and politeness

- `config.py`: `DEFAULT_PROVIDERS["<site>"] = ProviderPolicy(budget=…, delay=(10.0, 20.0))`, and `SWITCHABLE` if
  it may be turned off (every new source so far is). Comment why the budget is what it is.
- `http.py`: the host's robots rules as caracole reads them (`_<SITE>` rules, `ROBOTS_DISALLOW` by host),
  `ROBOTS_CRAWL_DELAY` from its Crawl-delay. gametabs.net needed `$` at the end of a rule understood. The fixture
  `tests/fixtures/<site>/robots.txt` is the live file of the day, and a test pins that each closed path is closed.
- `logs.py`: `provider_name` ("gametabs.net"), the name alerts and logs use.
- Blocks need nothing new: `ProviderBlocked`, `health.record_block` and the alert are shared. A test pins them
  (`test_pipeline.py::test_a_<site>_block_cools_it_down_and_marks_no_song`).

## 4. Schema and per-song state

- `db.py`: `SCHEMA_VERSION` + 1 and a script in `_MIGRATIONS` (never a transaction of its own), the tables'
  comment block, indexes for the keys search reads. `test_db.py` migrates an old database and checks the tables.
- `site_index.py`: reads a sitemap index and its children (gzipped too), resumes, and refuses a sitemap cut short.
  Use it rather than another reader.
- `songs.py`: add `<site>:checked:` (and any other per-song kv prefix) to `_PER_SONG_KV`, so a merge or a removal
  deletes them.
- Keys: `normalize`'s keys; if the slug needs its own keying (a contraction, a repeat number), say how a change to it
  re-keys the table (harptabs' `ensure_current_keys`, `ROW_KEYS`).

## 5. The nightly step

- `pipeline.py`: `_<site>(ctx)` after the step it follows (order in the module docstring), skipped when switched
  off, the sitemap refreshed (30 days), the songs' candidates, then the index pass with what the budget leaves.
  Returns a `StepResult`.

## 6. Files kept, picks, removal

- `inbox.py`: the kept file's pattern, its kind, and `<site>_number` (the lowest N no file holds, the user's own
  files included).
- `overrides.py`: `[<site>]`, "Artist - Title" → the page you picked (`<Site>Pick`, `<site>_pick_from_url`, the
  `add_*` writer through tomlkit and `write_atomic`); the section list and the docstring.
- `removal.py` needs nothing when the file is recorded in `files`: `_caracoles` deletes recorded files by name. Pin it
  in `test_removal.py`.

## 7. A lookup (`caracole get`)

- `get.py`: a `<site>` stage (its label), the pick passed through, `GAMETABS_KEPT`-style detail, the lookup pace
  and budget.
- `commands/get.py`: `--<site> URL`, its help, `_check_pick`.
- `web/jobs.py` (the argument), `web/library_routes.py` (`<site>_field`, `PICK_LIMITS`), `web/status.py` (the
  line "Fetching from <site>"), `web/outcome.py` (the stage's group and words).

## 8. Commands

- `commands/lyrics.py` holds the per-provider steps (`caracole lyrics`, `lacuerda`, `gtptabs`, `harptabs`,
  `gametabs`, `musescore`): add `caracole <site>` there, with `--index [--budget N]` if there is an index pass.
  Heavy imports inside the function (`test_commands_index_match.py` checks registering loads no provider module).
- `commands/index.py`: a line in `caracole index stats` ("gametabs.net: 412 of 1,658 game pages read").
- `commands/search.py`: the source's group in `caracole search`'s output.

## 9. Search

- `search.py`: `search_<site>` reading the new tables alone, never the site, and its keys in `/api/search`
  (`web/search_routes.py`); `suggestions` may add it to "Did you mean".

## 10. Marks, library page, serve

- `icons.py`: `_site("<site>", "<host>", "<site>", "XY", "https://<host>/")`, two letters no other source uses.
- `library_assets/rows.js`: the rows of its results (`siteHit`-style), its mark, `instrumentBadges` if it names an
  instrument; `library.js` `mergeSites`; `card.js`: the kept file's tile; `library_page.py`: the file's order and
  "downloaded from"; `web/lookup_page.py`: the lookup page's rows.
- The offline manifest needs nothing: it follows the library page's links.
- Another session may be editing the library page: keep these hunks small, and merge `origin/main` before the last run.

## 11. Viewer and render

Only when the kept file is drawn rather than opened as text (harptabs.com's `harmonica-N.html`: `render.py`
`_render_harmonica`, `app.written_pages`, its own viewer). A text tab opens as text like UG's `tab.txt`.

## 12. Nix and docs

- `nix/module.nix`: the budgets comment; `nix/module-check.nix` only if a unit's command changes.
- `AGENTS.md`: the layout table's row for the step, the Invariants (budgets, robots list, the owner's exceptions,
  errors never misses, keys). `docs/usage.md`: the provider, its config and defaults, the step, the commands, the file
  kept, `[<site>]`, search, index stats, the schema note. `docs/deploy.md`: only if a deployment sets something new.

## 13. Tests (first, and never live)

- `tests/helpers/<site>_site.py`: a fake site behind a real `PoliteClient` (`httpx.MockTransport`) serving the
  fixtures, counting requests.
- `test_<site>.py` (parsing), `test_<site>_fetch.py` (candidates, keeping, a miss, errors never misses, the cache),
  `test_<site>_index.py` (the pass, resuming, budgets), `test_commands_<site>.py`, and additions to `test_get.py`,
  `test_pipeline.py`, `test_http.py`, `test_search.py`, `test_db.py`, `test_overrides.py`, `test_removal.py`,
  `test_icons.py`, `test_library_card.py`, `test_library_page.py`, `test_web_app.py`, a Chromium
  `test_web_page_<site>.py`, and `test_commands_index_match.py` (no heavy import on registering).
