# Song tiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A song opened on index.html becomes a card of tiles (what you play from, each source's versions as
chips opening a drawer), with a quieter closed line, a red Remove, and `caracole versions --keep-more` to fetch
the Ultimate Guitar versions not kept, within a lookup's budget.

**Architecture:** The server computes the counts (library_page.py's data); the page's scripts only draw. A new
`card.js` / `card.css` in library_assets/ holds the card's parts, which library.js `lineFor` hands to rows.js's
dense line as Nodes in `more`; rows.js gains the glyphs and the closed line's icons. `--keep-more` is
versions_cmd.py's `keep` looped at the lookup pace, with its own served route.

**Tech Stack:** Python 3.14 (typer, sqlite3), vanilla JS (createElement/createElementNS only), CSS; pytest with
pytest-xdist, Chromium browser tests (`helpers.browser`).

**Spec:** `docs/superpowers/specs/2026-10-27-song-tiles-design.md` (read it first; the mockups it names are in
the main checkout's `.superpowers/brainstorm/2818486-1793122579/content/song-line-a-v2.html`).

## Global Constraints

- AGENTS.md's rules, all of them; in particular: no `innerHTML`; nothing loaded from the network; every inline
  asset is a file of `src/caracole/library_assets/` listed in `library_page.STYLESHEETS` / `SCRIPTS`; no style
  attribute in markup (CSSOM `style.setProperty` only); test first; never a live request in a test.
- Tests through the dev shell: `nix develop -c pytest -q -m "not slow"` while working, `nix develop -c pytest -q`
  before each commit that touches more than one test file. Browser tests are `@in_chromium` and `slow`.
- Copy fixed by the spec: "Chord sheet", "Auto sheet", "Ukulele chords", "Guitar Pro", "Guitar tab", "Harmonica
  tab", "Lyrics", "Score"; chip leads "Versions", "Files", "Tabs", "From"; "Ultimate Guitar · chord sheets";
  "N versions on the site · K kept in your library"; "N more on Ultimate Guitar, not kept"; "Fetch them" /
  "Fetch N more"; "In use"; "Use this one"; "Back to caracole's pick"; "Progressions" with "find your songs that
  play one"; "Remove" (no ellipsis).
- Remove: outlined, text and border in `--failed`, never filled; behaviour unchanged (five seconds, Undo).
- Both themes (base.css tokens; new colours go in as tokens with dark values), 390 px with no horizontal scroll,
  44 px targets under `pointer: coarse`.
- Commits: conventional, scoped (`feat(versions): …`, `feat(library): …`, `test(library): …`), no AI attribution.

## Review Focus

- A song with no sheet (wanted, not found, needs review, YouTube route): no empty tile row; its notes, picker,
  Look in the index and Find it elsewhere links all still there; Fetch now still its line's action.
- A sheet that is LaCuerda's or the auto one while UG versions are recorded: UG's chip still counts; In use is on
  LaCuerda's row (or nowhere for the auto sheet), never on a UG row.
- `--keep-more` when UG cools down, the hour's lookups are spent, or a page won't parse mid-way: what was kept
  stays kept and is rendered; exit 0; the drawer's count and button come back right after the job.
- A line drawn again (a job over, `/jobs.json`'s view, LaCuerda found) keeps its card open, as today, and its
  drawer closed; opening a chip sends no request.
- 390 px with long titles, 13 versions and four tiles: no horizontal scroll, the drawer under its own tile.

---

### Task 1: `caracole versions --keep-more`

**Files:**
- Modify: `src/caracole/versions_cmd.py` (new `keep_more`, beside `keep`; module docstring gains its bullet)
- Modify: `src/caracole/commands/versions.py` (option `--keep-more`, flag; one of `--keep`, `--keep-more`,
  `--choose`, `--clear`)
- Test: `tests/test_commands_versions.py` (a `# --- --keep-more` section, reusing its CREEP fixtures)

**Interfaces:**
- Produces: `versions_cmd.keep_more(cfg: Config, display: str, *, progress: bool = False) -> None`; CLI
  `caracole versions SONG --keep-more [--progress]`; progress stages `song`, `version`, `pdf`, `pages`, then
  `done` (as `keep`).

- [ ] **Step 1: Write the failing tests**
  - `test_keep_more_keeps_the_next_versions_in_rank_order_within_the_lookups_budget`: a song with 10 versions
    not kept, `lookup_requests = 3` in its config: exactly the first 3 not kept in rank order get
    `version-<tab>.txt`, each in `sheet_versions.kept_by_you`; output names 3 kept and "7 more not kept".
  - `test_keep_more_takes_the_lock_as_a_lookup_does`: `locks == [(f"versions {CREEP} --keep-more", True)]`.
  - `test_keep_more_passes_over_the_sheet_gone_and_blocked_versions`: the chosen one, a gone one and one under
    `[block]` get no request (the transport's log holds none of their URLs).
  - `test_keep_more_stops_at_a_block_and_keeps_what_it_kept`: the 2nd page answers 403: the 1st is kept and
    rendered, `record_block` cooled UG, exit 0.
  - `test_keep_more_with_nothing_left_sends_nothing`: every version kept: says so, no request, exit 0.
  - `test_keep_more_notes_the_versions_it_cant_keep`: a page with no sheet text: noted in `unkeepable`, so a
    second run sends no request for it.
  - `test_keep_more_progress_counts_in_the_version_stage`: `--progress` lines: `version` done with detail
    "kept 3 of 10", then `pdf`, `pages`, `done` with `requests == {"ug": 3}`.
- [ ] **Step 2: Run them**: `nix develop -c pytest -q tests/test_commands_versions.py -k keep_more` → FAIL
  (no such option).
- [ ] **Step 3: Implement `keep_more`**: one client (`make_client(cfg, conn, "ug", lookup_run_id(now),
  interactive=True)`) for the whole loop; candidates `sheet_versions.may_keep(conn, song.id, in_library(...),
  overrides.block)` (already on the branch, b47f376); an outcome `no text` or `held` is noted with
  `note_unkeepable` (in `keep` too: add a test `test_keep_notes_a_version_it_cant_keep`); `keep_version(ctx, song, int(v.tab_id))` each, stopping on
  `BudgetExhausted`, `ProviderBlocked` (record_block), `ProviderError` (record_error) with `keep`'s words; one
  `render_all(..., song_ids={song.id})` if any kept, one `write_pages`. Share `keep`'s cooling check and
  messages rather than copying them (a helper both call).
- [ ] **Step 4: Run them** → PASS; then `nix develop -c pytest -q -m "not slow"` → PASS.
- [ ] **Step 5: Commit** `feat(versions): --keep-more keeps the versions not kept, within a lookup's budget`.

### Task 2: The served route, and posts by song

**Files:**
- Modify: `src/caracole/web/versions_routes.py` (`POST /versions/keep-more`; every post may name the song by
  `song` id instead of `sheet`; docstring lines)
- Modify: `src/caracole/web/jobs.py` (`version_steps(..., keep_more: bool = False)`)
- Modify: `docs/usage.md` (`caracole versions --keep-more`; the served route under the web page's section)
- Test: `tests/test_web_versions.py`

**Interfaces:**
- Consumes: Task 1's CLI.
- Produces: `POST /versions/keep-more` with form `csrf`, `song` (id); `POST /versions/choose` and
  `/versions/clear` also accept `song` (id) with `tab` in place of `sheet` (the card posts these). Each answers
  as the other posts do (`app.queued`), so library.js's `postInPlace` follows the job. Job title "Fetch the other
  versions of <display>"; step label "Fetching versions from Ultimate Guitar"; argv
  `(VERSIONS, "--keep-more", "--progress", "--", artist, title)`.

- [ ] **Step 1: Write the failing tests**: `test_keep_more_queues_one_job_under_the_songs_key` (two posts, one
  job, `fetching=True`); `test_keep_more_is_refused_with_nothing_left_to_keep` (409);
  `test_keep_more_is_refused_for_an_ignored_song`; `test_choose_by_song_id_queues_what_choose_by_sheet_does`
  (same argv); `test_a_post_by_song_id_needs_the_form_token_and_same_origin` (as the others).
- [ ] **Step 2: Run** `nix develop -c pytest -q tests/test_web_versions.py` → FAIL.
- [ ] **Step 3: Implement**: `_asked` gains a by-id branch (`songs.get_song`, the versions from `in_library`),
  `_cant("keep-more", asked)` refuses when `may_keep` is empty; `DOINGS` gains `"keep-more"`.
- [ ] **Step 4: Run** → PASS; `nix develop -c pytest -q -m "not slow"` → PASS. Write usage.md's lines.
- [ ] **Step 5: Commit** `feat(web): Fetch them, the versions not kept, as a queued job`.

### Task 3: The page's data: versions per source

**Files:**
- Modify: `src/caracole/library_page.py` (`_versions_data`, a counting query beside `_kept_versions`,
  `_lacuerda_versions`, `_song`)
- Test: `tests/test_library_page.py`

**Interfaces:**
- Produces, on each song of index.html's data (library.js reads these, Tasks 5–6):
  - `versions`: `null` when the song has no UG version recorded in its sheet group; else
    `{"total": int, "list": [...], "rest": int, "keepMore": int, "pinned": bool}`. `total`: versions UG still
    has (not gone, not stale); `list`: the kept ones as today (each `as_data` entry with `href`, `source:"ug"`)
    plus `complete: bool|None` and `coverage: float|None`; `rest`: `len(sheet_versions.may_keep(...))`;
    `keepMore`: `min(rest, cfg.provider("ug").lookup_requests)`; `pinned`: `sheet_pins` names one.
  - `lacuerdaVersions`: `[{"href": str, "coverage": float|None, "sheet": bool}]`, best first (as
    `_lacuerda_met` orders), LaCuerda's not-gone `sheet` rows; `[]` for none.
  - `autoSheet` (only for a song with both a human and an auto sheet): `{"href": viewer, "files": [{label,
    href, download}]}` of `sheet (auto).*`, which the card shows as the sheet tile's Auto chip.
- `in_library` for every song with UG versions recorded is a few queries a song: check the page's build time on
  a 600-song library (a test helper, not a committed benchmark) and, if it grows by more than a fifth, count
  `total` and `rest` in one query instead, pinned equal to `may_keep(in_library(...))` by a test.

- [ ] **Step 1: Write the failing tests**: `test_versions_counts_ug_versions_for_a_song_with_none_kept`
  (total 13, list [], rest 12, keepMore 6); `test_versions_counts_match_in_library`
  (for a song with kept, gone and stale versions, total/rest equal what `in_library` says);
  `test_keep_more_is_capped_by_the_lookup_budget` (`lookup_requests = 2` → 2);
  `test_pinned_says_a_pin_chooses_the_sheet`; `test_lacuerda_versions_best_first_and_the_sheet_marked`;
  `test_versions_is_null_without_ug_versions`.
- [ ] **Step 2: Run** `nix develop -c pytest -q tests/test_library_page.py -k "versions"` → FAIL.
- [ ] **Step 3: Implement** as the Interfaces say; update `_versions_data`'s and `_song`'s docstrings.
- [ ] **Step 4: Run** → PASS; `-m "not slow"` → PASS.
- [ ] **Step 5: Commit** `feat(library): each song's versions counted per source for the page`.

### Task 4: The closed line

**Files:**
- Modify: `src/caracole/library_assets/rows.js` (`glyph`, `denseLine`'s `holds` and chevron; export `glyph`)
- Modify: `src/caracole/library_assets/rows.css` (line columns: holds, key chip; badges never over the key)
- Modify: `src/caracole/library_assets/library.js` (`statusOf` returns null for a plainly found song;
  `lineFor` passes `holds` instead of `sources`)
- Test: `tests/test_library_page.py` (DOM via `dump_dom`), `tests/test_web_page.py` (served)

**Interfaces:**
- Produces: `glyph(name: "sheet"|"guitar"|"harmonica"|"lyrics"|"score"|"download"|"open"|"chevron"|"search"|
  "refresh"|"book"|"trash"|"info"|"check"|"close"|"plus", label?: string) -> SVGSVGElement` (createElementNS,
  `aria-hidden` unless labelled), from rows.js's returned object; `resultRow({dense: true, holds: [names],
  ...})`: with `holds`, the line shows those glyphs (each titled "Chord sheet", "Guitar Pro", …) and no source
  marks; without, the marks as today (search hits). Every dense line's fold button (`.line-more`) shows
  `glyph("chevron")`, turned by `[aria-expanded="true"]`.
- `holds` order: sheet (auto sheet: class `auto`), guitar (a Guitar Pro file or `tab.txt`), harmonica, lyrics,
  score; read from `files` and `instruments`.

- [ ] **Step 1: Write the failing tests**: `test_a_found_songs_line_has_no_status_badge`;
  `test_a_wanted_songs_line_keeps_its_badge`; `test_a_line_shows_what_the_song_holds_not_its_sources`
  (Hotel California fixture: glyph titles in order); `test_a_search_hits_line_keeps_its_sites_marks`;
  `test_the_fold_button_is_a_chevron_named_more_for_the_song`; browser:
  `test_a_badge_never_covers_the_key_column` (a hit with Harmonica: the badge's box and the key's don't overlap
  at 1280 px).
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement.** Update the tests that read `.line-sources` or `badge found` on your songs' lines to
  the new line (keep their intent; list each changed test in the commit body).
- [ ] **Step 4: Run** `nix develop -c pytest -q` → PASS.
- [ ] **Step 5: Commit** `feat(library): a song's closed line says what it holds`.

### Task 5: The card and its tiles

**Files:**
- Create: `src/caracole/library_assets/card.js` (`const caracoleCard = (icons, rows) => ({ tiles, drawerFor,
  progressions, findLinks, foot })`), `src/caracole/library_assets/card.css`
- Modify: `src/caracole/library_page.py` (`SCRIPTS`: card.js after rows.js; `STYLESHEETS`: card.css after
  rows.css), `src/caracole/library_assets/library.js` (`lineFor` builds `more` from caracoleCard's parts; the
  old Files / Sheet versions / PDF exports / Guitar Pro groups and `progressionsOf` go), rows.js `foldMore`
  (the line gets class `open` while its panel shows: card.css draws the card from it)
- Test: new `tests/test_library_card.py` (`@in_chromium` module: the card in a written index.html and served)

**Interfaces:**
- Consumes: Task 3's data; Task 4's `glyph`.
- Produces: in a line's panel, in order: `p.facts`, the notes, `div.tiles > article.tile` (each: `a.tile-open`
  with an accessible name "Open the chord sheet of <title>" etc., `div.tile-versions` of `button.vchip`
  (`aria-expanded`, `aria-controls`) or `span.vchip.one`, `div.tile-downloads` of `a[download]`), then
  `section.drawer` (hidden until a chip opens it; one per card), `div.progressions`, `div.find-elsewhere`,
  `div.foot` (Fetch again / Fetch now / Use LaCuerda's sheet, Add to a songbook…, `info.json`, Remove).
  `section.drawer` holds `.drawer-head` and `.vrow`s.

- [ ] **Step 1: Write the failing tests** (in Chromium, Hotel California and a wanted song as fixtures):
  `test_tiles_in_order_with_their_open_links` (Chord sheet → viewer, Guitar Pro → Guitar Pro page when served,
  Harmonica tab, Lyrics); `test_the_sheet_tile_downloads_pdf_text_chordpro_and_each_export`;
  `test_chips_count_versions_per_source` ("13" UG, "2" LaCuerda, an Auto chip beside a human sheet; Files gtptabs 1 + inbox 1; Lyrics "From
  LRCLIB" with no button); `test_a_chip_opens_its_drawer_and_another_chip_closes_it`;
  `test_escape_closes_the_drawer_and_gives_the_focus_back_to_its_chip`;
  `test_opening_a_drawer_sends_no_request` (the page's fetch log unchanged);
  `test_the_ug_drawer_lists_the_kept_versions_and_counts_the_rest`;
  `test_a_song_with_no_sheet_has_no_tiles_but_its_notes_and_links`; `test_musescore_links_show_beside_a_sheet_too`;
  `test_a_text_tab_alone_is_a_guitar_tab_tile`; `test_a_score_you_filed_is_a_tile`;
  `test_remove_says_remove_and_is_red_and_last`; `test_progressions_are_search_chips_that_filter`;
  `test_the_card_fits_390px_with_the_drawer_under_its_tile`;
  `test_a_line_drawn_again_keeps_its_card_open_and_its_drawer_closed`; and the file page (not served): no Use
  this one / Fetch them / Remove / Fetch again, the `--keep-more` command shown instead.
- [ ] **Step 2: Run** `nix develop -c pytest -q tests/test_library_card.py` → FAIL.
- [ ] **Step 3: Implement** card.js/card.css to the mockup (tokens from base.css, light values too); move
  library.js's tests' expectations for the old panel (`Sheet versions`, `PDF exports`, `Files`, `Open in the
  browser`, `Remove…`, `.subhead`) to the card, keeping each test's intent.
- [ ] **Step 4: Run** `nix develop -c pytest -q` → PASS; `test_library_assets.py` passes with the new files.
- [ ] **Step 5: Commit** `feat(library): a song opens as a card of tiles, each source's versions a chip`.

### Task 6: The drawer's served actions

**Files:**
- Modify: `src/caracole/library_assets/card.js`, `library.js` (the forms: `songForm` and `postInPlace`)
- Test: `tests/test_library_card.py`

**Interfaces:**
- Consumes: Task 2's routes; library.js `songForm(cls, action, s)`, `postInPlace(form, go, s)`,
  `lookupForm(s, label, aria, lacuerda)`.
- Produces: in the UG drawer, Use this one → `POST /versions/choose` (`song`, `tab`); Back to caracole's pick →
  `POST /versions/clear` (`song`); Fetch them / Fetch N more → `POST /versions/keep-more` (`song`); in the
  LaCuerda drawer, Use this one → the lookup with that LaCuerda page kept (today's `lacuerdaSheet` post). Each
  follows its job on the song's line as Fetch again does; the drawer's counts come back with the job's view.

- [ ] **Step 1: Write the failing tests** (served, `WebApp(timers=QUICK)`, a fake queue as test_web_page_again.py
  does): `test_use_this_one_posts_choose_with_the_tab`; `test_fetch_them_posts_keep_more_and_says_fetch_n_more`
  ("Fetch 6 more" when rest 10 > keepMore 6, "Fetch them" when rest ≤ keepMore);
  `test_back_to_caracoles_pick_only_when_pinned`; `test_lacuerda_use_this_one_posts_the_lookup_with_its_page`; `test_lacuerda_use_this_one_waits_for_a_pin_to_go`;
  `test_after_keep_more_the_drawer_counts_again_from_the_jobs_view`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `nix develop -c pytest -q` → PASS.
- [ ] **Step 5: Commit** `feat(library): the versions drawer chooses, fetches and goes back`.

### Task 7: Docs, screenshots, the whole check

**Files:** `docs/usage.md` (the library page's song: tiles, versions, Remove), `README.md` pictures via
`docs/screenshots/make.py`, AGENTS.md's library_assets lines (card.js, card.css; `glyph` in rows.js).

- [ ] **Step 1:** Retake the screenshots (`docs/screenshots/make.py`, its docstring says how); look at each.
- [ ] **Step 2:** `nix develop -c pytest -q` → PASS; `nix flake check` → PASS (`git add` new files first).
- [ ] **Step 3: Commit** `docs: the library page's song card`.
