# Library filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take B.1: the library toolbar becomes tags + Filter + Sort + Select; Filter opens a popover (a bottom
sheet on a phone) with Status, instruments and Key.

**Architecture:** body.html's `.toolbar` markup; library.js's state (`state`, `addressed`, `save`, the filter
predicate near line 1866, `render`'s chip and key code); a new `library_assets/filter.css` (listed after
library.css) for the toolbar, the popover and the sheet; select.js moves its toggle. rows.js's `glyph` and the
closed line's `holds` (commit 99c4d2f, this branch's base) are what the instruments use.

**Tech Stack:** vanilla JS/CSS, pytest + Chromium (`helpers.browser`).

**Spec:** `docs/superpowers/specs/2026-10-27-library-filter-design.md`; mockup
`/home/dani/Projects/caracole/.superpowers/brainstorm/2818486-1793122579/content/library-filter-b-v2.html` (B.1,
the first panel and its phone).

## Global Constraints

- AGENTS.md's page rules; both themes; 390 px; 44 px under `pointer: coarse`.
- Copy: "Filter", "Sort", "Select", "Clear", "Clear all", "Status", "All", "Found", "Wanted", "Review", "Has
  something for", "any of these", "Chord sheet", "Guitar tab", "Ukulele", "Harmonica", "Score", "Key", "Any",
  "Major", "Minor", "N songs", "Show N songs".
- Address parameters: `show`, `key` (unchanged values), `mode`, `tonic`, `inst`.
- Tests through `nix develop -c pytest …`; whole suite before the last commit. Commits `feat(library): …`, no AI
  attribution.

## Review Focus

- An old address (`#show=wanted&key=…`) opens with those filters as tags, and Back/forward keep working.
- Every filter on at once leaving no song: the empty message names them all and its Show all clears them.
- A library with no keyed songs (no Key group) and none with any instrument but sheets: the panel shows only
  what applies.
- The phone sheet: focus kept inside while open, Escape and Show N songs close it, the page does not scroll
  behind it.
- Select's pick mode with filters on: picking still works on the filtered list, and its bar sits as before.

---

### Task 1: The toolbar and the popover shell

**Files:** body.html, library.js, select.js, new filter.css, library_page.py (STYLESHEETS); tests in
`tests/test_web_page.py` / `tests/test_library_page.py` (browser) — or a new `tests/test_library_filter.py`.

- [ ] Failing tests: `test_the_toolbar_is_tags_filter_sort_and_select`; `test_filter_opens_a_popover_and_escape_closes_it_returning_focus`;
  `test_a_click_outside_closes_the_popover`; `test_below_720px_filter_opens_a_bottom_sheet_with_show_n_songs`;
  `test_select_sits_last_and_still_starts_picking`. Move the tests that press `[data-show]` chips or read `#key`
  options to the panel's controls, keeping their intent.
- [ ] Run → FAIL. Implement (Status moves into the panel here, as a segmented control keeping `data-show`). PASS. Commit.

### Task 2: Instruments

- [ ] Failing tests: `test_instrument_chips_count_and_filter_any_of`; `test_an_instrument_with_no_song_is_disabled`;
  `test_a_lines_glyph_of_a_chosen_instrument_is_lit`; `test_inst_is_kept_in_the_address_and_read_back`;
  `test_counts_follow_the_other_filters_and_the_search`.
- [ ] Run → FAIL. Implement. PASS. Commit.

### Task 3: Key: mode and tonic grid

- [ ] Failing tests: `test_mode_alone_filters_by_mode`; `test_a_tonic_alone_is_that_tonic_in_either_mode`;
  `test_mode_and_tonic_is_todays_exact_key_and_writes_key`; `test_an_old_key_address_opens_as_mode_and_tonic`;
  `test_a_tonic_with_no_song_is_dashed_and_disabled`; `test_the_tonics_are_in_circle_of_fifths_order`.
- [ ] Run → FAIL. Implement. PASS. Commit.

### Task 4: Tags, Clear, counts, empty messages, docs

- [ ] Failing tests: `test_each_active_filter_is_a_removable_tag`; `test_clear_lets_every_filter_go_but_the_search`;
  `test_the_artist_filter_is_a_tag`; `test_no_match_names_every_filter_and_show_all_clears_them`.
- [ ] Run → FAIL. Implement. PASS.
- [ ] Screenshots in Chromium at 1280 and 390, light and dark, popover and sheet open with Harmonica on; compare
  with the mockup. `docs/usage.md`'s library page section; README screenshots if they show the toolbar
  (`docs/screenshots/make.py`).
- [ ] `nix develop -c pytest -q` → PASS. Commit.
