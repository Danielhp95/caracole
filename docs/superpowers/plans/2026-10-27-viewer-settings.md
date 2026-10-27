# Viewer settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The viewer's ⋯ settings as take A.2: a head that says what is set, Transpose and Capo on one line,
modes marked (the song's own, the chosen), switches for on/off, the instrument and strum on one line, places to
go as rows, no numerals glossary.

**Architecture:** Markup in `viewer/page.py` (`_CONTROLS`, `_EXPORT_ROW`, `_GUITAR_ROW`, `_RESET_ROW`), behaviour
in `viewer/viewer.js` (the functions that fill those rows), looks in `viewer/viewer.css`; same ids, new control
types.

**Tech Stack:** Python 3.14 page builder, vanilla JS, CSS; pytest, Chromium (`helpers.browser`, `helpers.viewer_pages`).

**Spec:** `docs/superpowers/specs/2026-10-27-viewer-settings-design.md`; mockup
`/home/dani/Projects/caracole/.superpowers/brainstorm/2818486-1793122579/content/viewer-panel-a-v2.html` (take A.2).

## Global Constraints

- AGENTS.md's viewer and page rules (BUILD_FILES, CSP hashes, no innerHTML, no style attributes, no music theory in
  viewer.js); both themes; 390 px; 44 px under `pointer: coarse`.
- Copy: "Settings"; "Transpose"; "Capo"; "↺ Reset"; "Easier shapes"; "Mode"; "Chords", "+ Numerals", "Numerals";
  "Role colours" + "home away pull"; "All chord shapes"; "Chord necks"; "Pinyin"; "Harmony"; "Guitar Pro tab";
  "Export PDF"; "Reset everything". No "as written". No "What do the numerals mean?".
- Ids kept (spec, Constraints). Toggles keep `aria-pressed`.
- Tests: `nix develop -c pytest -q -m "not slow"` while working; `nix develop -c pytest -q` before each commit.
- Commits `feat(viewer): …`, no AI attribution.

## Review Focus

- A sheet with no key (no Mode, no numerals): the head says "as written", the names hint explains, nothing empty.
- Piano or a wind instrument (no capo, maybe no strum): Transpose alone at full width, the select alone.
- A transposed PDF (`data.transpose` ≠ 0): Transpose's Reset is hidden at that value and shows at any other.
- The songbook's panel (no Export, a song switched): the head follows the song shown.
- 390 px, dark and light: the pair of steppers, the segmented names and the loudness icons fit without wrapping
  badly; every target 44 px under `pointer: coarse`.

---

### Task 1: The head and the Transpose/Capo line

**Files:** Modify `src/caracole/viewer/page.py`, `viewer.js`, `viewer.css`; Test `tests/test_viewer_panels.py` (or the
viewer test file that already covers the settings: find it with `git grep -l reset-capo tests`).

- [ ] Failing tests: `test_the_settings_head_says_key_mode_capo_and_instrument` ("D Dorian · capo 2 · Guitar"
  after choosing Dorian and capo 2; "as written" without a key); `test_a_reset_shows_only_while_a_value_differs`
  (transpose 0 and the sheet's capo: both Resets hidden; capo 2: Capo's shown and its stepper marked);
  `test_transpose_reset_goes_back_to_the_pdfs_transposition`; `test_transpose_and_capo_share_a_line_at_390px`
  (their boxes' tops equal); `test_an_instrument_without_a_capo_shows_transpose_alone`.
- [ ] Run → FAIL. Implement. Run the viewer tests → PASS. Commit.

### Task 2: Modes

- [ ] Failing tests: `test_the_songs_own_mode_is_marked_and_says_no_as_written` (its pill has class `orig`; no
  text "as written" anywhere in `#panel`); `test_the_chosen_mode_is_the_accent_and_the_own_one_keeps_its_mark`
  (choose Dorian: Dorian pressed, Major still `orig`, not pressed); `test_the_mode_line_says_what_it_sounds_like`.
- [ ] Run → FAIL. Implement. PASS. Commit.

### Task 3: Chords: names, switches, no glossary

- [ ] Failing tests: `test_chord_names_is_one_segmented_control` (three buttons, one pressed);
  `test_role_colours_all_shapes_necks_and_pinyin_are_switches` (each `.switch` with `aria-pressed`, toggling it
  toggles what it did before; shapes stay in step with the bar's guitar button);
  `test_no_numerals_glossary` (`#gloss` absent); `test_the_names_hint_shows_only_without_a_key`. Move the tests
  that read `#gloss` or the chips' words ("Show", "Hide", "Show all") to the new controls, keeping their intent.
- [ ] Run → FAIL. Implement. PASS. Commit.

### Task 4: Instrument and strum on one line

- [ ] Failing tests: `test_the_instrument_is_a_select_that_switches_the_instrument` (`#insts` a `<select>`, its
  change does what a chip did, stored as before); `test_loudness_is_four_named_icon_buttons` (`#volumes`: Off,
  Soft, Medium, Loud by aria-label, one pressed, choosing one sets caracoleSound's volume as before);
  `test_an_instruments_own_rows_follow_that_line`.
- [ ] Run → FAIL. Implement. PASS. Commit.

### Task 5: Places to go, Reset everything, the songbook

- [ ] Failing tests: `test_harmony_guitar_pro_and_export_are_rows_at_the_end` (in that order, after the
  instrument line; Harmony › opens the Harmony panel; Guitar Pro ↗ per file; Export PDF shows the version in
  words, served a link to `/export`, from a file the command and Copy); `test_reset_everything_is_last_and_quiet`;
  `test_the_songbook_has_the_same_panel_without_export`.
- [ ] Run → FAIL. Implement. PASS.
- [ ] Screenshots: the panel at 390 px and at 1280 px, dark and light, in Chromium (scratch files, not committed);
  compare with the mockup and fix what differs. Retake the README pictures if one shows the settings
  (`docs/screenshots/make.py`). `docs/usage.md`: the viewer's settings, if it describes them.
- [ ] `nix develop -c pytest -q` → PASS. Commit.
