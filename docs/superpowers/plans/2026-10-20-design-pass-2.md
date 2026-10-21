# Design Pass 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the owner's four choices: a dense artist-grouped library that searches the local indexes as you type, a neck-per-chord rail on the laptop sheet, a clean two-column PDF with "Export PDF of this version", and a Songbooks tab with per-song key, capo and mode.

**Architecture:** Five lanes on separate branches from caracole-v1. **P** (PDF) and **N** (neck rail) start now and touch disjoint files. **E** (export and "my version") follows P and N. **L** (library lines) starts once branch dev-speed (library_page.py → library_assets/, web/app.py → route modules) has merged. **B** (Songbooks tab) follows L. The music theory stays in Python (viewer/theory.py). One new Python module, viewer/version.py, applies a viewer state (key, capo, mode, positions, swaps) to a sheet. Exports, "my version" and songbook settings all go through it, so a PDF always matches the viewer.

**Tech Stack:** Python 3.14, chordpro 6.050.7, vanilla JS/CSS inlined under hash CSPs, SQLite, pytest + pytest-xdist, headless Chromium (tests/helpers/browser.py, helpers/viewer_pages.py).

**Spec:** docs/superpowers/specs/2026-10-20-design-pass-2-design.md (approved 2026-10-20).

## Global Constraints

- Every invariant in AGENTS.md holds. In particular, typing never sends a request to a music site, and only Get it or adding a song you don't have runs a lookup, at the lookup pace.
- index.html, sheet.html and songbook.html keep working from file:// (CSP `default-src 'none'`, hashed inline scripts and styles). The served pages keep their sandbox and security rules. The served viewer stays `sandbox allow-scripts` and opens serve pages by same-tab links only.
- Theory lives in viewer/theory.py and viewer/voicings.py. viewer.js only looks up what page.py computed.
- Autoscroll is out of scope: don't change it.
- Cards and the Cards/Rows switch go. The owner said "Cards go".
- 390x844 and 1280x800, light and dark. No sideways scroll, no target under 44 px on touch (`helpers/targets.small_targets`), no layout shift.
- Tests first. Run them with `nix develop -c pytest -q -p no:cacheprovider`: the whole suite takes about 35 s, `-m "not slow"` about 6 s. Mark browser tests `@in_chromium`. Never make a live request.
- docs/usage.md and AGENTS.md stay in step, in the same commit. Use conventional commits with no AI attribution, and never run omnibin-shell. Lint with `nix run nixpkgs#ruff -- check --select E4,E7,E9,F src tests`.

## Review Focus

1. **A chord the theory can't read:** "N.C.", "Cadd9(no3)", a typo. An export, "my version" or a songbook setting writes it unchanged and never crashes. Test in Task E1.
2. **A song whose key is unknown** (no key, none estimated), given a songbook setting "G Dorian". The PDF keeps the written chords and the chip says "key unknown, as written". Test in Task B2.
3. **Fast typing, or a slow common word** ("the", about 0.1 s). Only the newest query's results ever show, no older answer replaces them, and the user's songs stay visible throughout. Test in Task L3.
4. **A song with 12 or more distinct chords** on the neck rail. The rail scrolls on its own; neither the page nor the sheet scrolls sideways. Test in Task N3.
5. **The same version exported twice, and an export of a song with an accented or CJK name.** The second export replaces the first, the file name is safe, and `caracole remove` deletes it. Test in Task E2.

---

## Lane P: a clean two-column PDF (start now)

Branch `pdf-clean` from caracole-v1. The library sheet.cho stays the viewer's input. The PDF gets its own text, made in render.py's private copy (`_render_into`).

### Task P1: Trim stray spaces after a line's first chord

**Files:** Modify `src/caracole/chordpro.py` (`merge_chord_line`, ~65-83). Test: `tests/test_chordpro.py`.

- [ ] **Step 1: Write the failing tests**
```python
def test_spaces_after_a_lines_first_chord_are_trimmed():
    out = to_chordpro("[Verse]\n[ch]Em7[/ch]            [ch]G[/ch]\n  Today is gonna be the day\n", title="T", artist="A")
    assert "[Em7]Today is g" in out or "[Em7]Today is gonna" in out
    assert "[Em7]  Today" not in out

def test_spaces_between_later_chords_stay():
    out = to_chordpro("[Verse]\n[ch]C[/ch]   [ch]F[/ch]\nla la   con\n", title="T", artist="A")
    assert "   " in out.split("[F]")[0] or "[F]" in out  # interior spacing unchanged
```
Keep `test_render_all.py:408-409` (`[F]   con`) green unchanged.
- [ ] **Step 2: Run them.** `nix develop -c pytest -q tests/test_chordpro.py -k spaces` FAILS on the first.
- [ ] **Step 3: Implement.** In `merge_chord_line`, after the chords are inserted at their columns of the original lyric, remove the whitespace that directly follows the line's leading run of chord tags, and only there.
- [ ] **Step 4: Run** test_chordpro.py, test_render_all.py and test_viewer*.py. All PASS.
- [ ] **Step 5: Commit** `fix(chordpro): no stray spaces after a line's first chord`.

### Task P2: Entities UG escaped twice

**Files:** Modify `src/caracole/ug/page.py:237-240` and `src/caracole/render.py` (`_human_sheet`, ~779-805). Test: `tests/test_page.py`, `tests/test_render_all.py`.

- [ ] **Step 1: Write the failing tests.** `test_page.py::test_a_twice_escaped_entity_is_decoded`: a tab page whose content holds `&amp;amp;feature` parses to `&feature`. `test_render_all.py::test_a_kept_sheet_with_a_twice_escaped_entity_renders_decoded`: a sheet.json on disk with `&amp;` in its content gives a sheet.cho with `&`.
- [ ] **Step 2: Run them.** Both FAIL.
- [ ] **Step 3: Implement `decode_twice(text: str) -> str`** in ug/page.py: `html.unescape`, applied a second time only when the result still matches `&(#\d+|#x[0-9a-f]+|[a-z]+);`. Call it in `parse_tab_page` and on `raw["content"]` in `_human_sheet`. Update `test_viewer_preamble.py:40`, which pins `&amp;amp;` in the HTML, to the decoded text.
- [ ] **Step 4: Run** test_page.py, test_render_all.py and test_viewer_preamble.py. All PASS.
- [ ] **Step 5: Commit** `fix(page): decode entities UG escaped twice, on sheets already kept too`.

### Task P3: One preamble rule, shared

**Files:** Create `split_preamble` in `src/caracole/viewer/sheet.py`. Modify `src/caracole/viewer/page.py` (`_preamble` 400-418, `_played_line` 421, `_given_shapes` 292) to use it. Test: `tests/test_viewer_sheet.py` (new) plus the existing test_viewer_preamble.py.

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class Preamble:
    notes: tuple[str, ...]                    # the text lines folded away (not tab, not legend)
    legend: tuple[tuple[Chord, Position], ...]  # from voicings.chord_legend
    tabs: tuple[tuple[int, int], ...]        # (start, end) line spans of tab blocks inside it, kept
    tuning: str | None                       # e.g. "Eb standard", "half step down", "Drop D"
    capo_note: str | None                    # e.g. "Capo 2"
    end: int                                 # index of the first body line
def split_preamble(lines: list[str]) -> Preamble
```
The rule is the viewer's: an unlabelled first section, only when another section follows, up to its first tab block, with nothing played in it. Legend lines count as not played.

- [ ] **Step 1: Write the failing tests** in test_viewer_sheet.py, using `tests/fixtures/chordpro/legend_sheet.cho`: `test_the_preamble_holds_the_notes_the_legend_and_the_tuning`. Assert `notes` contains the YouTube line, `legend` has Em7 → `022033`, `tuning is None` and `capo_note == "Capo 2"`. Also `test_a_tuning_note_is_read` (`"Tuning: Eb Ab Db Gb Bb Eb (half step down)"` → `"half step down"` or the full text) and `test_a_lacuerda_sheet_without_sections_has_no_preamble`.
- [ ] **Step 2: Run them.** FAIL (no name).
- [ ] **Step 3: Implement** `split_preamble`. Move the viewer's rule there, and make page.py call it. Use the tuning pattern `(?i)\btuning\b|half[- ]step down|drop [a-g]|[a-g]b standard` and the capo pattern `(?i)\bcapo\b\D{0,6}(\d+)`.
- [ ] **Step 4: Run** test_viewer_sheet.py, test_viewer_preamble.py and test_viewer_shapes.py. All PASS, and the existing ones are unchanged.
- [ ] **Step 5: Commit** `refactor(viewer): one preamble rule for the viewer and the PDF`.

### Task P4: The PDF's own text

**Files:** Create `src/caracole/pdf_text.py`. Modify `src/caracole/render.py` (`_render_sheet_pdf` 606, `_render_into` 819, state keys 624-630). Test: `tests/test_pdf_text.py` (new), `tests/test_render_all.py`.

**Interfaces:**
- Consumes: `split_preamble` (P3), `key_line_text` (below), `voicings.parse_fingering`.
- Produces:
```python
PDF_TEXT_VERSION = 1   # in render state; bump to re-render every PDF
def key_line_text(key: Key | None, capo: int | None) -> str   # in viewer/page.py, beside _facts: "Em shapes · capo 2 · sounds F#m" / "Key Em" / ""
def pdf_text(cho: str, *, key: Key | None, capo: int | None, columns: int = 2) -> str
```
`pdf_text` does five things:
- Drops the preamble's notes and keeps its tab blocks.
- Writes each legend shape as `{define: NAME base-fret B frets f f f f f f fingers g g g g g g}`.
- Writes `{subtitle: <artist> · <key_line_text> · <tuning>}`, leaving out empty parts.
- Uppercases section comments.
- Inserts `{columns: N}` after the header.

`_render_into` writes `pdf_text(...)` to the private copy and sheet.cho stays as it is. The render state gains `"pdf_text": PDF_TEXT_VERSION`.

- [ ] **Step 1: Write the failing tests.**
  - `test_pdf_text.py::test_the_notes_go_the_tab_blocks_stay`: legend_sheet.cho has no YouTube line, keeps its riff, and gains `{define: Em7 base-fret 1 frets 0 2 2 0 3 3`.
  - `::test_the_header_reads_like_the_viewer`: `{subtitle: Oasis · Em shapes · capo 2 · sounds F#m}`.
  - `::test_a_tuning_note_goes_into_the_header`.
  - `::test_sections_are_capitals_and_the_song_is_in_two_columns`: `{comment: VERSE}`, then `{columns: 2}` after the header.
  - `::test_key_line_text_matches_the_viewers_facts`: parametrized on the cases in test_viewer.py:357-363.
  - `test_render_all.py::test_the_pdf_is_made_from_its_own_text_and_sheet_cho_keeps_the_notes`: the fake chordpro sees `{columns: 2}`, and sheet.cho still has the notes.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement** `key_line_text` (the same words as `_facts`, no markup), `pdf_text`, and the render hook. `test_render_record_says_what_the_pdf_was_made_from` keeps `source_sha == sha256(sheet.cho)` and now also expects `"pdf_text": 1`.
- [ ] **Step 4: Run** test_pdf_text.py, test_render.py, test_render_all.py and test_viewer.py. All PASS.
- [ ] **Step 5: Commit** `feat(render): the PDF has its own text: no notes, the tab's shapes, the viewer's key line, two columns`.

### Task P5: The style, and songbooks

**Files:** Modify `src/caracole/chordpro-style.json` and `src/caracole/songbook.py` (`_song_file` 865, PDF inputs `"v": 2` → 3). Test: `tests/test_render.py`, `tests/test_songbook_render.py`.

The style values come from the sketches (style C):
- `fonts.comment = {"name":"Helvetica-Bold","size":9,"color":"#b4441e"}`, with no background.
- `fonts.chord.size = 10.5`, `fonts.text.size = 11`, `fonts.title.size = 24`.
- `diagrams.width = 7`, `height = 7`.
- `formats.title.title = ["%{title}","",""]`, `subtitle = ["%{subtitle}","",""]`.
- `margintop = 92`, `headspace = 64`.
- `spacing.lyrics = 1.15`, `chords = 1.0`, `empty = 0.6`.

- [ ] **Step 1: Update the failing tests.** `test_the_style_puts_key_and_capo_under_the_title_and_colours_the_chords` now expects the `%{subtitle}` format, the colour `#b4441e`, and no `background` on `comment`. `test_render_real_chordpro_binary` (real chordpro) asserts the subtitle text `"The Placeholders · Key G"` in pdftotext output when available. `test_songbook_render.py::test_each_song_goes_in_as_its_pdf_text`: each `NNN.cho` holds `{columns: 2}` and `{subtitle:`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.** Apply the style values. In `_song_file`, use `pdf_text(entry.cho, key=…, capo=…)`, keeping the `{transpose}` prefix until Task B2, and bump `"v"` to 3.
- [ ] **Step 4: Run** test_render.py, test_render_all.py and test_songbook_render.py, real chordpro included. All PASS. Render Wonderwall and Hotel California from `tests/fixtures`, look at page 1 (pdftoppm), and compare with the sketches' style C.
- [ ] **Step 5: Commit** `feat(render): the clean two-column style for sheets and songbooks`. Update docs/usage.md's PDF paragraph.

---

## Lane N: a neck per chord on the laptop sheet (start now)

Branch `neck-rail` from caracole-v1. Touches viewer/page.py (`_song_html`, data), viewer.js, viewer.css and book.js. This lane avoids P3's preamble code in page.py; if both lanes edit page.py, keep each lane's hunks separate.

### Task N1: Positions and swaps kept in the address

**Files:** Modify `src/caracole/viewer/viewer.js` (`state` 38, read 62-67, `save` 68-88, `openCard`/`drawCard`/`pick` 445-534, `drawStrip` 423-439). Test: `tests/test_viewer.py` (run_in_page pattern, as `test_the_address_keeps_where_the_song_is_played`).

**Interfaces — Produces** the address parameters, which E1 parses:
- `at=<i>.<n>,<i>.<n>`: for chord index i (`data-c`), the position index n in `shapesOf(current(i), shift()).list`. Omitted when 0.
- `alt=<mode>.<i>.<root>.<suffix>.<bass>,…`: suffix URL-encoded, bass empty for none. This is today's `state.alt` moved into the address. localStorage keeps it too.

`state.at` is an object of index to number. The card's `shown.at` starts from `state.at[i]`, and the strip draws `list[state.at[i] || 0]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_address_keeps_a_chords_chosen_position`: open the card at `#chord=3`, press › twice and reload; the hash holds `at=3.2`, and the strip's diagram for chord 3 is position 2.
  - `test_the_address_keeps_a_swap`: `#use` gives `alt=ionian.0.7.maj7.`. The served-sandbox variant (a local http.server with viewer_csp, as test_viewer.py:379) keeps both across a reload.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement** the read and `save()` for `at` and `alt`. Positions reset for a chord when its name changes (transpose or mode): key `state.at` by index and clear an entry when `shapesOf` returns a different list length.
- [ ] **Step 4: Run** test_viewer*.py. All PASS.
- [ ] **Step 5: Commit** `feat(viewer): a chord's chosen position and swaps are kept in the address`.

### Task N2: The neck drawing

**Files:** Modify `src/caracole/viewer/viewer.js` (add `neck(positions, opts)` beside `diagram` 198-238) and `viewer.css` (neck classes and a position palette `--p1…--p4` in light and dark). Test: `tests/test_viewer_necks.py` (new, `pytestmark = CHROMIUM_MARKS`).

**Interfaces — Produces:** `neck(positions: Position[], {chosen: number, mine: number, frets: 15}) -> SVGElement`, with `role="img"` and aria-label "Em7: 4 positions". Each position draws as dots in its colour at absolute frets (`n + base - 1`), open strings as rings at the nut, and muted strings as nothing. The chosen position is drawn bolder; positions with an index below `mine` get a "the tab's" legend entry.

- [ ] **Step 1: Write the failing test.** `test_a_neck_draws_every_position_at_its_frets`: open a viewer of legend_sheet.cho at 1280x800 and read `#necks svg[aria-label^="G"] circle` positions. G's four chords-db positions sit at frets {open, 3, 5, 7} plus the tab's 320033.
- [ ] **Step 2: Run it.** FAIL.
- [ ] **Step 3: Implement** `neck`, using the sketches' geometry: frets 0–15, inlays at 3 5 7 9 12 15, high e on top.
- [ ] **Step 4: Run** test_viewer_necks.py. PASS.
- [ ] **Step 5: Commit** `feat(viewer): draw a chord's positions along the neck`.

### Task N3: The rail

**Files:** Modify `src/caracole/viewer/page.py` (`_song_html` 341-350: `<aside class="necks" id="necks{suffix}" hidden aria-label="Chord positions">`), `viewer.js` (`drawNecks()` called from `render()`, a click to set `state.at`, `matchMedia("(min-width: 1200px)")`), `viewer.css` (from 1200 px: fixed left rail `--necks: 300px`, `body { padding-left: var(--necks) }`, `.bar { left: var(--necks) }`, the rail's own `overflow-y: auto`, hidden in print), and `book.js:53` (add `necks-N` to the per-song ids). Test: `tests/test_viewer_necks.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_from_1200_px_a_rail_on_the_left_shows_a_neck_per_chord`: chords in order of first appearance, each with its legend.
  - `test_below_1200_px_there_is_no_rail`: at 1100 and 390.
  - `test_picking_a_position_on_the_neck_makes_it_the_chords_shape_in_the_strip_and_card`, and the address holds `at=`.
  - `test_the_necks_follow_transposition_and_mode`: + once, and G's neck is now G#/Ab.
  - `test_the_rail_and_the_settings_rail_fit_together`: at 1440x900 with the panel open, no element overlaps the sheet and nothing scrolls sideways.
  - `test_a_song_with_many_chords_scrolls_the_rail_alone`: a 14-chord sheet; the rail's scrollHeight is greater than its clientHeight, and the page doesn't scroll sideways. This is Review Focus 4.
  - `test_the_rail_in_dark_mode_keeps_its_contrast` (`media=dark`).
  - `test_a_songbook_song_has_its_own_rail` (test_viewer_book pattern).
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.** Reuse `shapesOf(current(i), shift())` for each chord in `sheet.chords` order, deduplicating by name, and keep theory out of the script. `layout()` measures with the rail's width taken off.
- [ ] **Step 4: Run** test_viewer*.py and test_web_server.py. All PASS. Check `small_targets` on the rail at 1280: legend entries are 44 px or more on touch.
- [ ] **Step 5: Commit** `feat(viewer): from 1200 px a rail of necks, one per chord`. Update docs/usage.md's viewer section.

---

## Lane E: export a version, and "my version" (after P and N merge)

Branch `export` from caracole-v1 once P and N are in.

### Task E1: A version applied in Python

**Files:** Create `src/caracole/viewer/version.py`; add it to `page.BUILD_FILES` (page.py:89-95). Test: `tests/test_viewer_version.py` (new).

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class Version:
    t: int = 0                    # semitones, the viewer's state.t
    mode: str | None = None       # one of theory.MODES, None = as written
    capo: int | None = None       # None = the sheet's
    at: Mapping[int, int] = {}    # chord index -> position index
    alt: Mapping[str, Mapping[int, tuple[int, str, int | None]]] = {}
def version_from_query(query: str) -> Version          # the viewer's address params (t, mode, capo, at, alt)
def version_query(v: Version) -> str                    # the inverse, same order as viewer.js save()
def version_label(v: Version, key: Key | None, capo_sheet: int | None) -> str   # "G Dorian, capo 0"
def apply_version(cho: str, v: Version, *, key: Key | None, capo_sheet: int | None) -> str
```
`apply_version` returns ChordPro text with every chord renamed as the viewer names it (the Python twin of viewer.js `shift`, `names` and `nameOf`, using `theory.spelling`, `map_chord` and the swaps), a `{define}` for each chord's chosen position (`shapesOf`'s rule with `sheet_shapes` and `load_voicings`), `{capo}` and `{key}` updated, and no `{transpose}`. A chord `parse_chord` can't read stays as written.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_version_names_chords_as_the_viewer_does`: Em key, t=1 → `Fm7`, `Ab`, `Ebsus4/G`, `Bb7sus4`; E dorian maps Cadd9 → `C#m7b5`.
  - `test_the_query_round_trips`.
  - `test_an_unreadable_chord_stays_as_written`: "N.C." and "Cadd9(no3)". This is Review Focus 1.
  - `test_a_chosen_position_becomes_its_define`.
  - `test_python_and_the_viewer_name_every_chord_alike` (Chromium): for legend_sheet.cho and ug_sheet.cho across 6 versions (t ±3, three modes, capo 0/3, with a swap), the viewer's chord texts equal `apply_version`'s chord names.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement** in version.py. Reuse `viewer/page.py`'s key reading (`_song_key`) for `key`.
- [ ] **Step 4: Run** test_viewer_version.py and test_viewer.py. All PASS.
- [ ] **Step 5: Commit** `feat(viewer): apply a viewer version to a sheet in Python`.

### Task E2: Render an export

**Files:** Modify `src/caracole/render.py` (add `render_version`), `src/caracole/commands/render.py` (`--version QUERY`), `src/caracole/removal.py` (`_caracoles`: exports), `src/caracole/icons.py` (`_MADE_FROM`: exports come from sheet.txt), `src/caracole/songs.py` (the kv prefix `render:export:` in `_PER_SONG_KV`). Test: `tests/test_render_all.py`, `tests/test_removal.py`, `tests/test_commands_render.py`.

**Interfaces — Produces:**
```python
EXPORT_KV = "render:export:"   # + "<song id>" -> {label: {"pdf": name, "query": q, "source_sha", "style", "pdf_sha256", "pdf_size"}}
def render_version(conn, cfg, overrides, song: Song, v: Version, *, runner=subprocess.run) -> Path
```
The file is named `f"sheet ({library.safe_name(version_label(...))}).pdf"`. A second export with the same label replaces the file and its record. A later render pass remakes exports whose sheet or style changed.

- [ ] **Step 1: Write the failing tests.**
  - `test_an_export_is_a_pdf_beside_the_sheet_in_that_version`: the fake chordpro sees `[Am]` for G+2, no `{transpose`.
  - `test_the_same_export_again_replaces_it`.
  - `test_an_export_of_a_song_with_an_accented_or_chinese_name_has_a_safe_name`. This is Review Focus 5.
  - `test_removal.py::test_a_removal_deletes_the_songs_exports`.
  - `test_commands_render.py::test_render_version_exports_one_song`: `caracole render --song "A - T" --version "t=2&mode=dorian"`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.** `pdf_text(apply_version(sheet_cho, v, …), …)` goes into `_render_into`; record under EXPORT_KV.
- [ ] **Step 4: Run** test_render_all.py, test_removal.py, test_icons.py and test_commands_render.py. All PASS.
- [ ] **Step 5: Commit** `feat(render): export a song's PDF in another version`. Update docs/usage.md (render, remove).

### Task E3: The export page and the viewer's button

**Files:** Create `src/caracole/web/export_routes.py` (GET `/export?sheet=<library path>&<version query>`, POST `/export`), registered in the router as dev-speed left it. Modify `src/caracole/viewer/page.py` (`_CONTROLS` panel: an `<a id="export">Export PDF of this version</a>` row) and `viewer.js` (served: the href is `/export?sheet=…&` plus the version query, same tab; file:// shows `caracole render --song '…' --version '…'` with Copy). Test: `tests/test_web_export.py` (new) and `tests/test_viewer.py`.

The page shows the version label, "Make PDF" (a POST with the form token, checked as other served forms are), the job's line, then "Open the PDF" and "Back to the sheet" (the viewer URL with the same hash). The job is `caracole render --song=… --version=…`.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_export_page_names_the_version_and_makes_its_pdf`.
  - `test_the_export_post_needs_the_form_token_and_the_same_origin`.
  - `test_an_unknown_sheet_or_a_bad_version_is_refused` (404 / 400).
  - `test_the_served_viewer_links_to_its_export_in_the_same_tab` (Chromium, a served sandbox).
  - `test_the_file_viewer_shows_the_command_to_export`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.** Find the song from the sheet path as `_viewers_written` does.
- [ ] **Step 4: Run** test_web_*.py and test_viewer.py. All PASS.
- [ ] **Step 5: Commit** `feat(serve): Export PDF of this version from the sheet`.

### Task E4: Make this my version

**Files:** Modify `src/caracole/overrides.py` (table `version` in `_TABLES`, field `version: Mapping[str, str]`, `add_version(path, display, query | None)`), `render.py` (the main PDF always goes through `apply_version`: a song's `[version]`, else `Version(t=[transpose])`, else the sheet as written; `render_pdf` stops passing `--transpose`, as the spec says; `[transpose]` keeps working and `[version]` wins), `viewer/page.py` (data `start`: the version's query, read by viewer.js as its starting state when the address has none), `songbook.py` (`_entry_of`: a song's version as its default), and `web/export_routes.py` (a "Make this my version" button: POST, then the job `caracole render --song`). Test: `tests/test_overrides.py`, `tests/test_render_all.py`, `tests/test_viewer.py`, `tests/test_web_export.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_add_version_writes_and_clears_the_table_keeping_comments`.
  - `test_a_songs_version_makes_its_main_pdf`.
  - `test_the_viewer_starts_in_the_songs_version`.
  - `test_make_this_my_version_saves_it_and_renders_the_song`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the suite. PASS.
- [ ] **Step 5: Commit** `feat(overrides): a song's own version: its PDF, its viewer and its songbooks follow it`. Update docs/usage.md (overrides.toml `[version]`).

---

## Lane L: library lines grouped by artist (after dev-speed merges)

Branch `library-lines` from caracole-v1 once dev-speed is in. Files as dev-speed leaves them:
- `src/caracole/library_assets/library.js` (`makeCard`, `cardFor`, `songRow`, `rowFor`, `VIEWS`, `state`, `render`, `sendAsk`, `showSites`, `hitKey`, `enterAll`).
- `rows.js` (`caracoleRows`, `resultRow`, `ugHit`, `artistHit`, `siteHit`).
- The templates `body.html`, `rows.css` and `library.css`.
- `src/caracole/web/search_routes.py` (`api_search`, `_found_for`, `api_artist`).

### Task L1: Lines grouped by artist, the only view

**Files:**
- Modify `library_assets/library.js`: replace `makeCard`/`cardFor`/`songRow`/`rowFor`/`VIEWS` with `lineFor(song)` and `artistGroup(name, items)`, and make `render()` group by `sortArtist`.
- Modify `rows.js` (`resultRow` gains a `dense` line form).
- Modify `body.html`: remove `#view-toggle`/`#view-panel`.
- Modify `library.css` / `rows.css`.
- Test: `tests/test_library_page.py`. Retire the card and rows tests the library map names, port their checks, and add new ones.

**Interfaces — Produces:**
- `lineFor(song) -> HTMLElement`: an `article.line[data-id]` with `.line-title` (link that opens the sheet), `.line-status`, `.line-key`, `.line-sources` (icons), `.line-action` (serverAction or sheetAction) and `.line-more` (⋯ panel: files, versions, Guitar Pro, MuseScore, Buy, Remove…, add to songbook).
- `artistGroup(artist, lines, counts) -> HTMLElement`: `section.artist[data-artist]` with a header reading "Soda Stereo · you have 2".

- [ ] **Step 1: Write the failing tests.**
  - `test_the_library_is_lines_grouped_by_artist_a_to_z`.
  - `test_about_thirty_lines_fit_a_laptop_screen_and_a_phone_shows_two_lines_a_song` (1280x800 ≥ 28 lines; 390x844 each line ≤ 2 text rows).
  - `test_every_action_a_card_had_is_on_the_line_or_its_menu` (Fetch now, Pick the match, Remove…'s Undo, Select box, review picker, request progress).
  - `test_filters_key_sort_and_letters_work_on_the_lines`.
  - `test_there_is_no_cards_rows_switch`.
  - `test_lines_meet_touch_and_contrast` (`small_targets`, `weak_edges`).
  - A dark-mode check.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.** Keep the review picker, request lines, Remove's Undo and Select working on `[data-id]` lines; Select's `decorate()` already targets `#list [data-id]`.
- [ ] **Step 4: Run** test_library_page*.py and test_web_page*.py. All PASS.
- [ ] **Step 5: Commit** `feat(library): dense lines grouped by artist replace cards and rows`. Update docs/usage.md (index.html).

### Task L2: Index rows carry the keys to merge

**Files:** Modify `src/caracole/web/search_routes.py` (`_found_for`: each index, gtptabs and lacuerda row gains `artist_key` and `title_key` from `normalize.identity_key`). Test: `tests/test_web_app.py`.

- [ ] **Step 1: Write the failing test.** `test_every_search_row_carries_its_artist_and_title_keys`, and the same song from UG and LaCuerda shares both keys.
- [ ] **Step 2: Run it.** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** test_web_app.py. PASS.
- [ ] **Step 5: Commit** `feat(search): rows say which artist and song they are, to merge across sites`.

### Task L3: Search as you type, inside the artist groups

**Files:** Modify `library_assets/library.js` (`sendAsk` on every input after `SEARCH_PAUSE`, no Enter needed; `showSites` → `mergeSites(data)` placing index rows into `artistGroup`s by `artist_key`, merging rows that share `artist_key` + `title_key` into one line with several source icons; "+ N more by X" → `/api/artist`; `#all`/Enter kept as no-ops or a jump to results). Test: `tests/test_web_page_search.py`, `tests/test_web_page_lacuerda.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_typing_lists_your_songs_and_the_indexes_without_enter`.
  - `test_one_song_from_two_sites_is_one_line_with_two_icons`.
  - `test_an_artist_group_shows_a_few_index_songs_then_more`.
  - `test_index_lines_show_tab_counts_not_stars`.
  - `test_typing_fast_shows_only_the_newest_answer` (a fake `/api/search` that answers the first query late). This is Review Focus 3.
  - `test_typing_never_asks_a_music_site` (existing invariant test kept).
  - `test_the_file_page_filters_your_songs_and_enter_shows_the_command`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.** Keep `hitKey`/`settleSpots` so a running Get it keeps its line.
- [ ] **Step 4: Run** test_web_page_search.py, test_web_page_lacuerda.py and test_library_page.py. All PASS.
- [ ] **Step 5: Commit** `feat(library): typing searches your songs and every index, grouped by artist`.

---

## Lane B: the Songbooks tab (after L merges, and after E1)

Branch `songbooks-tab` from caracole-v1 once L and E1 are in.

### Task B1: Per-song settings in songbooks.toml

**Files:** Modify `src/caracole/songbook.py` (`_KEYS`, `_parse` 294-321, `_entry` 266, `Songbook.songs` → `tuple[BookSong, ...]`, writers keep plain strings for songs with no setting) and `src/caracole/commands/songbook.py` (`caracole songbook set NAME SONG [--key K] [--mode M] [--capo N] | --clear`). Test: `tests/test_songbook.py`, `tests/test_commands_songbook.py`.

**Interfaces — Produces:**
```python
@dataclass(frozen=True)
class Setting:
    key: str | None = None     # a tonic as written, "G", "F#", "Bb"
    mode: str | None = None    # theory.MODES
    capo: int | None = None
@dataclass(frozen=True)
class BookSong:               # the songbook's entry, distinct from viewer/book.py's BookSong: name it SongbookSong if that clashes
    text: str                 # "Artist - Title"
    setting: Setting | None = None
def set_song_setting(path: Path, name: str, entry: str, setting: Setting | None) -> None
```
In the TOML file, `songs = ["Oasis - Wonderwall", { song = "Soda Stereo - De Música Ligera", key = "G", mode = "dorian", capo = 0 }]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_song_can_carry_its_key_mode_and_capo`.
  - `test_set_and_clear_keep_comments_and_plain_entries_plain`.
  - `test_a_bad_setting_is_an_error_naming_the_line`.
  - `test_cli_songbook_set_and_clear`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** test_songbook.py and test_commands_songbook.py. All PASS.
- [ ] **Step 5: Commit** `feat(songbook): each song may carry its own key, mode and capo`. Update docs/usage.md.

### Task B2: Songbooks render in each song's setting

**Files:** Modify `src/caracole/songbook.py` (`_entry_of` 573 and `_song_file` 865, through `version.apply_version`: the setting's key gives `t` = target tonic − the song's shapes key tonic; a song with no setting follows its `[version]` (E4), else as written; drop the `{transpose}` prefix; PDF and cho inputs `"v"` → 4) and `src/caracole/viewer/book.py` (each song starts in its setting: the BookSong carries the version query). Test: `tests/test_songbook_render.py`, `tests/test_viewer_book.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_song_in_g_dorian_is_written_in_g_dorian` (the fake chordpro sees the mapped chords, no `{transpose`).
  - `test_a_song_without_a_setting_follows_its_own_version`.
  - `test_replacing_a_songs_sheet_keeps_the_songbooks_key`.
  - `test_a_song_whose_key_is_unknown_stays_as_written` (and the chip text "key unknown, as written"). This is Review Focus 2.
  - `test_the_phone_page_opens_each_song_in_its_setting`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** test_songbook_render.py and test_viewer_book.py, with real chordpro. All PASS.
- [ ] **Step 5: Commit** `feat(songbook): songbooks render each song in its own setting`.

### Task B3: The Songbooks tab

**Files:**
- Modify `body.html` (a Library | Songbooks tab pair; `#tab=songbooks` in the address).
- Create `library_assets/songbooks.js` (the songbook list, the set list with drag and keyboard reorder, chips, ×, Get it, Get the N missing, rename/delete, exports, Add a song).
- Modify `songbooks.css`, `src/caracole/songbook_section.py` (data for the tab instead of the section above the bar), and `src/caracole/web/songbook_routes.py` (POST `/songbook/set`; POST `/songbook/add-song` for a song from an index: queue `caracole get` when not in the library, then `caracole songbook add`).
- Test: `tests/test_songbooks_tab.py` (new; Chromium plus a served WebApp, as test_web_songbooks.py), `tests/test_web_songbooks.py`.

- [ ] **Step 1: Write the failing tests.**
  - `test_the_songbooks_tab_lists_each_songbook_with_its_counts`.
  - `test_opening_a_songbook_shows_its_set_list_with_each_songs_setting`.
  - `test_dragging_a_song_moves_it_and_the_keyboard_can_too` (posts `/songbook/move`).
  - `test_a_settings_chip_changes_that_songs_key_mode_and_capo` (posts `/songbook/set`, then the song line says "G Dorian").
  - `test_add_a_song_searches_everything_and_a_site_song_is_looked_up_then_added`.
  - `test_exports_are_the_pdf_the_phone_page_and_chordpro`.
  - `test_the_file_page_shows_the_songbooks_read_only_with_their_commands`.
  - `test_the_tab_meets_touch_contrast_and_dark_mode`.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.** The old Songbooks section above the search goes. Select's "Make songbook" stays and lands in the tab.
- [ ] **Step 4: Run** the whole suite. PASS.
- [ ] **Step 5: Commit** `feat(library): a Songbooks tab: the list, the set list, each song's key, and Add a song`. Update docs/usage.md (index.html, caracole serve, songbooks).

---

## Order and merging

1. Run **P** and **N** now, in parallel.
2. Merge dev-speed when it passes.
3. Run **L** after dev-speed.
4. Run **E** after P and N.
5. Run **B** after L and E1.

After each lane:
1. One review round (a fresh agent tries to refute it, in the browser where it's UI).
2. Merge to caracole-v1 and run the suite (`nix develop -c pytest -q`).
3. Push, restart the served test library, and tell the owner what changed.
4. Close the improvements.md "Design pass" entry with a note when B lands.
