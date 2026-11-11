# The Guitar Pro page's tracks on a phone: one button and a sheet — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under 600 px, the Guitar Pro page's row of track chips becomes one button that opens a sheet listing every
track (a tick to show it, its speaker to mute it); wider screens keep today's chips.

**Architecture:** guitar.js builds the button (`#tracks-open`) and the sheet (a modal `<dialog id="tracks-sheet">`) with
`createElement`, beside the chips it builds today, and keeps the three in step through its existing `mark()` and
`mute()`; guitar.css shows the chips or the button by the page's phone width. guitar_page.py's `_BAR` is not touched,
so the phone's Kotlin `GuitarPage.BAR` stays byte for byte as it is; only the inlined script and stylesheet change.

**Tech Stack:** plain JavaScript and CSS in `src/caracole/web/`; pytest with Chromium (`helpers.browser.Browser`); the
conformance corpus (`tests/test_conformance_guitar.py`); Gradle for `:server` and the app's `GuitarPageTest`.

**Spec:** `docs/superpowers/specs/2026-11-10-guitar-tracks-sheet-design.md`

## Global Constraints

- The phone width is guitar.css's own: `@media (max-width: 599px)`; guitar.js reads the same, `matchMedia("(max-width: 599px)")`.
- Every target 44 px each way at the least (the page's rule).
- Elements by `createElement` and `textContent` only, never `innerHTML` (AGENTS.md, the pages caracole writes and serves).
- No change to `_BAR` in guitar_page.py or to the page's policy: the dialog is markup the script makes, no new source.
- The last track shown can't be taken away (today's rule: "the last one stays").
- Mutes take effect at once; the tracks shown are drawn once, when the sheet closes (`showTracks`), only if they changed.
- Tests drive the page on real time and wait for states, never a fixed time (AGENTS.md, Browser tests).
- No live request in any test; no Claude or AI attribution in commits.
- Conventional commits: `feat(web): …`, `test(web): …`, `docs: …`.

## Review Focus

1. **The phone turned to landscape (past 599 px) with the sheet open**: the sheet closes, its ticks are applied, and
   the chips show the same tracks shown and muted. (Task 2, `test_a_sheet_open_as_the_screen_widens_closes_and_keeps_its_ticks`.)
2. **Android's Back with the sheet open** closes the sheet and leaves the page where it was, never the page itself
   (the app's Back goes back in the WebView's history: opening pushes one entry, `popstate` closes). (Task 2.)
3. **The keyboard and a screen reader**: the button says what it opens (`aria-haspopup="dialog"`, `aria-expanded`),
   focus lands in the sheet when it opens and back on the button when it closes. (Task 1.)
4. **A long track name** (the fixture's "Vocals, the melody written as a tab") is cut short in its row, whole in its
   title, and never makes the sheet wider than the screen. (Task 1.)
5. **A score of one track** gets no button and no sheet, as it gets no chips today. (Task 1,
   `test_a_score_of_one_track_has_no_button_on_a_phone`.)

---

### Task 1: The button and the sheet: showing tracks

**Files:**
- Modify: `src/caracole/web/guitar.js` (the tracks block, from `const HOLD = 450;` to the click handler)
- Modify: `src/caracole/web/guitar.css` (the tracks rules and the `max-width: 599px` block)
- Test: `tests/test_web_guitar_browser.py`

**Interfaces:**
- Consumes: guitar.js's `shown` (indexes shown), `buttons[]` (each `{item, button, show, label, name}`), `mark()`,
  `showTracks(indexes)`, `trackName(track, index)`, `trackKind(track)`, `says(name, kind)`, `speaker()`, `$("tracks")`.
- Produces (Task 2 relies on these):
  - `#tracks-open`: a `<button type="button" class="btn tracks-open">` inserted after `#tracks` in `#gp-bar`, with
    `aria-haspopup="dialog"`, `aria-expanded`, and two spans: `.now` (the first track shown, then ` + N` for N more
    shown) and `.count` (`"5 tracks"`, a `▴`).
  - `#tracks-sheet`: a `<dialog class="tracks-sheet" aria-labelledby="tracks-title">` appended to `document.body`:
    `.grip`, a header (`<h2 id="tracks-title">Tracks</h2>` and `<button id="tracks-done" class="btn">Done</button>`),
    then `<ul class="tracks-list">` with one `<li class="row">` a track: a `<label>` holding
    `<input type="checkbox">`, `.name` and `.kind` (as the chips', the kind left out where `says(name, kind)`), the
    label's `title` the whole name when it's cut short; then a `<button type="button" class="mute">` with
    `speaker()`, `aria-label` and `title` `"Mute " + name`, `aria-pressed`.
  - `rows[]`: each `{li, tick, mute}`, index-aligned with `buttons[]`; `mark()` also sets each `tick.checked`, the
    rows' and chips' muted state, and the button's text.
  - `openSheet()` and `closeSheet()`; `pending` (the ticked indexes while the sheet is open).

- [ ] **Step 1: Write the failing tests**

```python
PHONE = {"width": 390, "height": 844, "mobile": True}

def test_a_phone_s_tracks_are_one_button_that_opens_a_sheet(served, tmp_path):
    # after RENDERED, on PHONE:
    #  the chips are hidden: getComputedStyle(#tracks).display == "none"; #tracks-open shown, >= 44 px tall,
    #  its .now "Lead guitar", its .count starting "5 tracks"; aria-haspopup "dialog", aria-expanded "false"
    #  click #tracks-open -> #tracks-sheet.open is True, aria-expanded "true", document.activeElement inside the sheet
    #  rows' [name, kind] == [[VOCALS, "6 strings"], ["Lead guitar", "6 strings"], ["Bass", "4 strings"],
    #                        ["Keys", "no tab"], ["Drums"]]
    #  ticks checked == [False, True, False, False, False]; Lead guitar's tick disabled (the last one shown)
    #  the sheet's height <= 0.7 * 844; .tracks-list's overflowY == "auto"
    #  the Vocals row: its label's title == VOCALS, its name's scrollWidth > clientWidth (cut), the sheet's
    #  right edge <= 390, and documentElement.scrollWidth <= clientWidth
    #  tick Bass -> data-track still "1" and dataset.rendered unchanged (nothing drawn yet); Lead's tick enabled
    #  click #tracks-done -> sheet closed, focus on #tracks-open, data-track == "1,2", rendered >= 2,
    #  caracoleGuitar.tracks names == ["Lead guitar", "Bass"], .now == "Lead guitar + 1"
    #  open again, untick Bass, Done -> data-track "1"; open, Done with nothing changed -> rendered unchanged
    #  no policy violation (window.caracoleViolations == [])

def test_a_wide_screen_keeps_its_chips_and_no_sheet(served, tmp_path):
    # 1280x800: #tracks displayed (not "none"), #tracks-open's display == "none", no dialog open

def test_a_score_of_one_track_has_no_button_on_a_phone(cfg, conn, tmp_path):
    # a one-track file made with helpers.guitar.export_alphatex (a one-track alphaTex: a single \track, a bar of
    # notes), kept with keep_guitar and served as `served` does; on PHONE, after RENDERED:
    #   #tracks hidden as today, document.getElementById('tracks-open') is None, no <dialog> in the page
```

Also change `test_a_phone_gets_the_tab_alone_with_no_sideways_scroll`: drop its `#tracks` overflowX, chip-in-view and
scrollLeft assertions; the bar stays `<= 0.15 * 844` with `#tracks-open` on the row under Play.

Change `test_a_long_press_shows_a_track_beside_those_shown_on_a_touch_screen` to a wide touch screen
(`width=800, height=1000, mobile=True`): the long press stays the chips', which a phone no longer shows.

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q -n 0 tests/test_web_guitar_browser.py -k "one_button or keeps_its_chips"`
Expected: FAIL (`#tracks-open` is null).

- [ ] **Step 3: Build the button and the sheet in guitar.js; style them in guitar.css**

Build both only when the score has more than one track (where `#tracks` is shown today). Open: `pending` = a copy of
`shown`, ticks from it, `showModal()`, `aria-expanded` true. A tick toggles its index in `pending` (sorted as `shown`
is); the only ticked box is `disabled`. `closeSheet()`: `close()`, `aria-expanded` false, focus back on the button,
and `showTracks(pending)` only when `pending.join() !== shown.join()`. Done and the dialog's `close` event (Escape)
both end in `closeSheet()`, once.

CSS: `.tracks-open` and `.tracks-sheet` hidden by default; under 599 px `.gp-tracks { display: none }` and
`.tracks-open { display: flex }` full width (name left, count right, muted colour for the count). The sheet: fixed to
the bottom, full width, `max-height: 70vh`, top corners rounded, `::backdrop` a dim shade; `.tracks-list` scrolls
(`overflow-y: auto`); rows at least 44 px, the label taking the row's width with `min-width: 0` and the name
ellipsized; the mute button 44 × 44 on the right; the muted row as a muted chip (red speaker, name struck through).
Colours from base.css's tokens (`--surface`, `--border`, `--accent`, `--failed`, `--muted`), so dark mode follows.

- [ ] **Step 4: Run the page's tests**

Run: `nix develop -c pytest -q -n 0 tests/test_web_guitar_browser.py tests/test_web_guitar.py`
Expected: all pass (the existing wide-screen tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/caracole/web/guitar.js src/caracole/web/guitar.css tests/test_web_guitar_browser.py
git commit -m "feat(web): a phone's Guitar Pro tracks are one button and a sheet"
```

### Task 2: Muting in the sheet, and every way it closes

**Files:**
- Modify: `src/caracole/web/guitar.js`, `src/caracole/web/guitar.css`
- Test: `tests/test_web_guitar_browser.py`

**Interfaces:**
- Consumes: Task 1's `#tracks-sheet`, `rows[]`, `openSheet()`, `closeSheet()`; guitar.js's `mute(index, muted)`.
- Produces: nothing new for others.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_sheet_mutes_at_once_and_closes_by_escape_a_tap_outside_or_back(served, tmp_path):
    # PHONE, SPY_MUTE; open the sheet; click the Keys row's .mute ->
    #   window.mutes == [[[3], True]], score.tracks[3].playbackInfo.isMute True, the row and the chip .muted,
    #   the row's mute aria-pressed "true", data-track still "1", the sheet still open
    # Escape -> closed; open; a tap at (195, 40) (the backdrop, above the sheet) -> closed;
    # open; history.back() -> closed, location.href unchanged, still RENDERED; open, Done -> history.length as
    # before the first open plus at most one entry per open that Back didn't take (no entry left behind on Done:
    # Done takes its own entry back with history.back())

def test_a_sheet_open_as_the_screen_widens_closes_and_keeps_its_ticks(served, tmp_path):
    # PHONE; open; tick Bass; Emulation.setDeviceMetricsOverride to 800x1000 ->
    #   the sheet closed, data-track "1,2", the chips displayed with Lead guitar and Bass pressed
```

- [ ] **Step 2: Run them to see them fail**

Run: `nix develop -c pytest -q -n 0 tests/test_web_guitar_browser.py -k "mutes_at_once or widens"`
Expected: FAIL.

- [ ] **Step 3: Implement**

Each row's `.mute` calls `mute(index, …)` as the chip's does (`mute()` updates chip and row alike). A click on the
dialog itself (its backdrop: `event.target === dialog`) closes. Opening calls `history.pushState({tracksSheet: true},
"")` (no URL: the page's sandbox has an opaque origin); `popstate` while open closes without going back again;
Done, Escape and the backdrop close and then `history.back()` to take their entry away (a flag so that popstate
doesn't close twice). `matchMedia("(max-width: 599px)")`'s `change` to false closes the sheet (its ticks applied).

- [ ] **Step 4: Run the page's tests**

Run: `nix develop -c pytest -q -n 0 tests/test_web_guitar_browser.py tests/test_web_guitar.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/caracole/web/guitar.js src/caracole/web/guitar.css tests/test_web_guitar_browser.py
git commit -m "feat(web): the tracks sheet mutes at once and closes by Done, Escape, a tap outside or Back"
```

### Task 3: The phone's copy, the docs, and the gates

**Files:**
- Regenerate: `tests/conformance/vectors/web/guitar.jsonl`
- Modify: `src/caracole/web/guitar_page.py` (its docstring's tracks sentence), the comments heading guitar.css's and
  guitar.js's tracks blocks, `docs/usage.md` (the Guitar Pro page), `android/README.md` (## Guitar Pro)

- [ ] **Step 1: Regenerate the corpus**

Run: `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_guitar.py`, then check mode without
`CARACOLE_CORPUS`. Expected: the vector's page records change (script, stylesheet, their hashes); nothing else.

- [ ] **Step 2: The phone's side**

Run: `nix develop ./android -c gradle -p android :server:test :app:testDebugUnitTest` (GuitarPageTest, AlphaTabAssetsTest)
and `android/scripts/device-test.sh GuitarPageTest`. Expected: pass with no Kotlin change (GuitarPage reads the copied
guitar.js and guitar.css). A failure here is drift: stop and report, don't edit Kotlin to match.

- [ ] **Step 3: The docs**

guitar_page.py's docstring and docs/usage.md: on a phone the tracks are one button naming the track shown, which opens
a sheet of every track, a tick to show it and its speaker to mute it; on a wider screen, the chips as before.
android/README.md's Guitar Pro: the same in a sentence.

- [ ] **Step 4: The gates**

Run: `nix develop -c pytest -q` and `nix develop -c ruff check --select E4,E7,E9,F src tests`. Expected: all pass.

- [ ] **Step 5: Commit, then merge once the integration has ended**

```bash
git add -A tests/conformance/vectors/web/guitar.jsonl src/caracole/web docs android/README.md
git commit -m "docs: the Guitar Pro page's tracks sheet on a phone; the guitar page's vector regenerated"
```

Merge `feature/guitar-tracks-sheet` into main (`git merge --no-ff`, then push) only after the running integration
(wf_0c07c8b4-78b) has ended, so that it checks one main.
