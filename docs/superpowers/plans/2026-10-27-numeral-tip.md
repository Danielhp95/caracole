# Numeral tooltip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The numeral tooltip shows the chord's notes: a twelve-note circle (default) or tiles and a keyboard,
with a switch between them, ▶ Hear it and Shapes →.

**Architecture:** harmony_tables.py adds pitch classes to `tones`; page.py's `#tip` markup gains the head, the
picture, the switch and the footer; viewer.js `showTip` fills them; viewer.css draws them.

**Tech Stack:** Python tables, vanilla JS/SVG (createElementNS), CSS; pytest + Chromium.

**Spec:** `docs/superpowers/specs/2026-10-27-numeral-tip-design.md`; mockup
`/home/dani/Projects/caracole/.superpowers/brainstorm/2818486-1793122579/content/numeral-tip-directions.html`
(directions C and A).

## Global Constraints

- AGENTS.md viewer rules (no music theory in viewer.js; tables checked on every transposition; BUILD_FILES;
  CSP; createElementNS; no style attributes); both themes; 390 px; 44 px under `pointer: coarse`.
- Copy: "Hear it", "Shapes", "outside the key", "off key", "root", "<note> isn't in <key> (it has <note>)",
  switch names "Show the notes on a circle" / "Show the notes on a keyboard".
- localStorage key `caracole-viewer-tipview`, values `circle` | `keys`.
- Tests via `nix develop -c pytest …`; whole suite before the last commit; commits `feat(viewer): …`; no AI
  attribution.

## Review Focus

- A chord the tables can't name (no `tones` entry), an alternative chord chosen in the card, a slash chord: the
  tooltip still opens, with what it has.
- Transposed (the key line's −/+) and with a capo: notes named in the key shown, the circle turned accordingly.
- Storage refused (a songbook's sandbox): the circle, and the switch still works for the page's life.
- Sound Off, or no strum.js (the songbook?): no Hear it button, nothing thrown.
- 390 px near the screen's bottom edge: the taller tooltip still placed above the numeral when there's no room
  below (`placeTip`).

---

### Task 1: Pitch classes in `tones`

**Files:** `src/caracole/viewer/harmony_tables.py` (and its docstring), `tests/test_viewer_harmony.py` or the
tables' test (`git grep -l "tones" tests/test_viewer_*`).

- [ ] Failing test: `test_tones_carry_each_notes_pitch_class` ("D7" → "D F# A C|R 3 5 ♭7|2 6 9 0", on every
  transposition the table holds), and the card's notes unchanged (`drawNotes` reads two fields).
- [ ] Run → FAIL. Implement. PASS. Commit.

### Task 2: The tooltip's head, circle, notes list and footer

**Files:** `viewer/page.py` (`#tip` markup), `viewer/viewer.js` (`showTip`, `placeTip`), `viewer/viewer.css`;
tests in the file that covers the tooltip (`git grep -l "tip-line" tests`).

- [ ] Failing tests: `test_the_tip_heads_with_chord_numeral_and_role`; `test_the_circle_rings_the_key_and_joins_the_chords_notes`
  (D7 in G: dots lit for D F♯ A C, the root marked, G major's seven ringed); `test_an_outside_note_is_marked_and_named`
  (G7 in G: F dashed, "F isn't in G major (it has F♯)"); `test_hear_it_strums_the_chord_and_hides_when_sound_is_off`;
  `test_shapes_opens_the_chords_card`; `test_the_tip_fits_390px_and_flips_above_near_the_bottom`.
- [ ] Run → FAIL. Implement. PASS. Commit.

### Task 3: The keyboard view and the switch

- [ ] Failing tests: `test_the_keyboard_button_shows_the_keyboard_and_circle_goes_back` (the labelled button,
  "Keyboard ›" / "‹ Circle", ← →; the dots `aria-hidden`);
  `test_the_keyboard_stacks_the_notes_up_from_the_root` (D7: D4 F♯4 A4 C5 lit); `test_the_view_chosen_is_kept_for_every_page`
  (localStorage, and circle when storage is refused); `test_the_songbook_has_the_same_tip`.
- [ ] Run → FAIL. Implement. PASS.
- [ ] Screenshots in Chromium (light and dark, 1280 and 390, both views, D7 and G7 in Amazing Grace-like G) under
  `/tmp/nix-shell.wBNcon/claude-1000/-home-dani-Projects-caracole/4b56bdb2-8fb1-410a-9ee6-52d74abce9f3/scratchpad/shots/tip/`;
  compare with the mockup. README screenshots if one shows the tooltip (`docs/screenshots/make.py`).
- [ ] `nix develop -c pytest -q` → PASS. Commit.
