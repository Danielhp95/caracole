# The sheet pages, redesigned: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the owner's approved redesign of the sheet pages (sheet.html and the kept versions' pages, the songbook
viewer, the harmonica tab's page): Back closing every layer and a full screen you choose; UG's header order with a
version line that counts each kind; lines that read as sung, bar cells for intros, narrower columns; a scroll arrow and
words under the bar's buttons, a key that says what changed with a list of keys, Harmony beside the necks, a laptop
toolbar; Auto/Light/Dark and a strip of chord shapes; the sung line lit, a key map for pedals and a screen kept on.

**Architecture:** Lane 5, beside the library page's four lanes, in six stages (5a–5f) merged into `main` one by one,
each a branch from `main` after the one before merged, in the worktree `../caracole-lane5`. It owns
src/caracole/viewer/ and render.py's page data, and their Kotlin port in `android/viewer` (SheetPage, HarmonicaPage, the
songbook, SongPass); every change to what a page holds regenerates the corpus and moves the port in the same commit.

**Tech Stack:** plain JavaScript and CSS inlined into the pages (viewer/), Python 3.14 (page.py, book.py, render.py;
pytest with pytest-xdist; Chromium browser tests through tests/helpers/browser.py), Kotlin (`:viewer`, Gradle), Nix
dev shells.

**Spec:** `docs/superpowers/specs/2026-11-17-sheet-pages-redesign-design.md` (approved 2026-11-17), its mockups in
`docs/superpowers/specs/2026-11-17-sheet-pages-redesign/`, the owner's decisions in
`.claude/handoff/ui-research-2026-11-17/sheet-decisions.md` (local; D8 was revised there after planning: narrower
columns), and the research in `.claude/handoff/ui-research-2026-11-17/reports/Sheet pages UI UX research.md` (local).

## Global Constraints

- Nothing loaded from the network; inline scripts and styles allowed by hash (a new viewer script is listed in
  `page.BUILD_FILES` and the page kind's script list, and in the Kotlin `ViewerAssets.Page` and `RenderBuild.ASSETS`);
  every element built with `createElement`/`textContent`, never `innerHTML`; a page works served by caracole serve, in
  its sandbox, opened as a file, and in the Android app's WebView; the songbook's sandbox has no storage (settings ride
  in the address, `carryScreen`).
- Today's colours (accent `#b4441e` light, `#f0895c` dark), logo and system font: unchanged; text size as today ("A− 18
  px A+", 13–30 px), section labels at today's fixed size.
- No relative text-size steps, Stage preset, Night palette, bumper or run-through, duration-based speed; nothing pinned
  over the sheet; the bar never covers the song's last lines.
- viewer.js computes no music theory (it looks up harmony_tables); strum.js is the one place a page makes sound;
  version.py names chords as viewer.js does; the phone's Kotlin builds every page byte for byte.
- A change to a viewer asset, page.py, book.py, harptab_page.py or render.py's page data regenerates the corpus in the
  same commit (`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, run twice, then once
  without `CARACOLE_CORPUS`), and `nix develop ./android -c gradle -p android test` passes before the merge; the Kotlin
  port follows in the same stage; the viewer corpus area stays within its budget (digests rather than a raised budget).
- Tests first; browser tests `@in_chromium`; the whole suite `nix develop -c pytest -q` before every merge; at each
  stage's merge: gradle, `nix flake check`, `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0
  tests/test_android_e2e.py` when the corpus moved, `git merge --no-ff`, `GH_TOKEN="$(gh auth token --user
  Danielhp95)" git push origin main`.
- docs/usage.md and AGENTS.md change with behaviour, in the same commit; no Claude or AI attribution anywhere;
  conventional commits scoped by area (`feat(viewer): …`).
- The library page's lanes run at the same time: lane 5 does not edit src/caracole/library_assets/, card.js,
  web/outcome.py or web/status.py.

## Review Focus

1. **A page with no storage and no history** (the songbook's sandbox; a browser refusing `pushState` on `file:`):
   layers still open and close, the theme and the screen minutes ride in the address, no exception. Tasks 5a.1, 5e.2,
   5f.5.
2. **A Chinese sheet** (pinyin on, Traditional and Simplified), long titles and artists: the header, the unsplit words,
   the line spacing and the lit line keep their columns. Tasks 5b.2, 5c.3, 5c.4, 5f.3.
3. **A capo set, and an instrument with no strings or no capo** (piano, harmonica, the winds): the header's facts, the
   key's word ("+2", "capo 2"), the key list. Tasks 5b.3, 5d.3, 5d.4.
4. **A song with no timed lyrics, and one whose lyrics match too few lines**: no highlight, no clock, nothing broken.
   Tasks 5f.1, 5f.3.
5. **A phone on its side, a 320 px phone, reduced motion**: the automatic full screen, 44–48 px targets, the steady
   segment-free page. Tasks 5a.7, 5d.7, 5f.4.

## Before the stages

### Task 5.0: The spec and this plan on `main`

- [ ] **Step 1:** In the main checkout, `git switch main && git merge --no-ff design/sheet-pages-redesign` (the spec,
  its mockups and this plan). Expected: a merge commit, docs only.
- [ ] **Step 2:** `nix develop -c pytest -q -m "not slow"` passes.
- [ ] **Step 3:** `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`; then
  `git worktree add ../caracole-lane5 -b feat/sheet-5a-layers main`.

## Where the stages meet

Where a stage's section below says otherwise, this section wins.

1. **Names.** 5a's and 5b's "Interfaces these stages produce" are the names every later stage uses: layers.js
   (`window.caracoleLayers`: `history`, `doubleTap`, `SHORT`, `placeUnder`), viewer.js's stack (`open`, `close`,
   `closeAll`, `topLayer`, `layers`, `DOCKED`), full screen's `data-controls` and `html[data-full]`, the header's
   `header.head` with `#versions`, `#ver-now`, `#ver-line`, `#kinds`, `dl.facts#facts`, and kinds.js
   (`window.caracoleKinds`). Where 5c–5f's sections name one of these by its role ("5a's layer helper", "the header"),
   they mean these.
2. **D8, revised by the owner after planning: narrower columns, not a step-down in size.** Task 5c.6 lowers the
   two-column layout's minimum column width (today 28 em) so two columns still fit the page at the reader's text size up
   to about 22 px; the rule that two columns show only when the whole song fits on the screen stays; no `COLUMN_SIZES`
   step-down and no `--cols-fs`. Its tests: at 1280 × 800 and 21 px a song that fits whole shows two columns (today it
   shows one); at 18 px nothing changes for a song too tall to fit whole.
3. **screen.js** (5e.2) is the one shared script for the reader's screen choices: the theme (5e), the key map (5f.4)
   and the screen timer (5f.5) all live in it; 5e.2 creates it (listed in `BUILD_FILES` and the Kotlin asset lists).
4. **The bar's height.** 5d.2 raises `--foot` from 53 to 63 px for the words under the buttons; 5c.5's end room is
   written in `var(--foot)`, so whichever merges second needs no change.
5. **The strip of chord shapes.** 5d.1 makes ⋯'s "All chord shapes" the strip's one switch (the bar's guitar button
   and the settings' "Chord necks" go); 5e.4 turns the strip on by default below 1200 px, per song (`state.shapes`).
6. **The harmonica tab's page has no More panel:** full screen there comes from a double tap and the short screen
   (5a.8); it has no screen-minutes control and follows the minutes kept from the sheet pages (5f.5).
7. **The library's glyphs** are copied into kinds.js (5b.5) with a browser test that fails if they drift from rows.js's;
   if a library lane changes a glyph in rows.js, the test tells lane 5 to follow.
8. **The version steppers (‹ ›) go** with the D2 C list, as the owner's mockups show.

**Merge order.** 5a, 5b, 5c, 5d, 5e, 5f, each from `main` after the one before merged; 5f.1 and 5f.2 land in one merge.

## Calls the planners made where the spec was silent (the owner may overrule)

- 5a: the Export PDF question opens on top of the settings without closing them; full screen counts as a layer, so
  opening a chord's card on a phone brings the controls back; the automatic full screen on a short screen has no
  history entry; layers opened at load (`#panel=1`, `#chord=`) push an entry.
- 5b: the Capo line is left out on an instrument with no capo, as Tuning on one with no strings; the auto sheet beside a
  human one keeps no version line; sources named as the library card names them ("gtptabs").
- 5c: bars are kept in the .cho (chordpro prints them as "Am C | G Em |"); four beats a bar, shared among its chords;
  marks before the first chord or after the last sit outside the cells; the harmonica page keeps its 0.12 em spacing.
- 5d: "+2" counts how far the chords on screen moved from the sheet as written (so taking off a sheet's capo reads
  "no capo · +2"); the settings keep "Transpose" over the bar's word; the key's scale neck moves to the Harmony tab
  (the harmonica page's Guitar tab keeps it); the toolbar is moved into the page by script (the tab order changes from
  1200 px) and doesn't slide away; 44 px widths below 380 px.
- 5e/5f: the strip is per song; no lit line in songbooks (their data has no lyrics); the lit line stays while paused
  and goes when autoscroll ends; ↑ and ↓ become page turns on sheet pages; ← → in a songbook stay blocked while any
  layer is open.

---

## Lane 5 · The sheet pages — stages 5a and 5b

Design: `docs/superpowers/specs/2026-11-17-sheet-pages-redesign-design.md` ("Layers and Back", D14 "Full screen", D1 "The
header", D2 "Versions and kinds", "Where it applies"). Mockups: `header.html` (option C), `kinds-versions.html` (option C).

### Interfaces these stages produce (5c–5f rely on them)

**layers.js** (new, inlined on every viewer page before the page's own script; `window.caracoleLayers`, frozen):

- `history(back)` → `{ sync(count) }`: the history's side of a page's layers. `sync(count)` says how many layers are
  open now; at the end of the task (a microtask) the helper makes the entries above the page's own equal `count`:
  `history.pushState({ caracoleLayer: n }, "")` for each one more (n = its depth, 1 for the first), `history.go(-k)` for
  k fewer. A Back (or the app's Back) that takes k entries off calls `back(k)`; the page closes its k top layers and
  calls `sync` again (a no-op then). Forward onto a layer's entry, or a page loaded at one (a reload, Back from a page a
  layer's link opened), goes back to the entry matching what is open. A `pushState` or `go` that throws turns it off
  for good: layers still open and close, and Back leaves the page as before 5a.
- The marker is `history.state.caracoleLayer` (an integer ≥ 1); **every `history.replaceState` in viewer/'s scripts
  passes `history.state`, never `null`** (a layer's entry keeps its depth through `save()`).
- `doubleTap(root, skip, then)`: `then(event)` on two `click`s within `DOUBLE_MS` (350) ms and `DOUBLE_PX` (30) px of
  each other whose targets are not inside `skip` (a selector), keyboard clicks (`detail === 0`) never counting.
- `SHORT`: `"(max-height: 499.98px)"`, the short screen (a phone on its side).
- `placeUnder(pop, anchor)` (5b.7): sets `--pop-top` and `--pop-left` on `pop` (px, in the page's coordinates) so it sits
  6 px under `anchor`'s box, its left edge on the anchor's, kept 8 px inside `.page`'s box. 5d's key list on a laptop
  uses it.

**viewer.js's stack** (5a.2): `layers` (`[{el, opener, nested}]`, last on top), `open(el, opener)`, `close(el)`,
`closeAll(keep)`, `topLayer()`; below 900 px (`wide`) one layer at a time (opening one closes every other but a nested
one); `DOCKED` (the elements that dock at the foot on a phone: `panel`, `card`, `harmony`, `vList`, `necksEl`), which
`dock()` reads. **5d's key list** is a layer: it is pushed with `open(keyList, keyButton)`, and is added to `DOCKED`.
**5f's key map** asks `layers.length` (a layer open) and `topLayer()`.

**Full screen** (5a.6–5a.8): `html[data-full="on"]` (a layer whose element is `button.handle#handle`) or
`html[data-full="auto"]` (the short screen's, no history entry). While it is set, CSS hides **every element marked
`data-controls`** (5a marks `#bar`; **5d marks its laptop toolbar `data-controls`** and nothing else changes), `.facts`
and `.why`; viewer.js's `railOn()` is false (the rail goes, the song takes the width). `#handle`'s click, Escape and
Back restore. The settings' row `#full-open` ("Hide controls") opens it.

**The header** (5b), on sheet.html, version pages and the harmonica page, in this order inside `header.head`:
`a.back` ("‹", 48 × 48 px, `aria-label` "Library" or, on a harmonica page with a sheet, "Chord sheet" with
`data-sheet`), `h1`, `p.artist`, `div.versions#versions[hidden]` (the version line: `button.vnow#ver-now` holding
`span#ver-line`, the chevron and `span.kinds#kinds`), then on sheet pages `dl.facts#facts` (rows
`div.fact[data-fact=tuning|capo|key|inst]`, each `dt` + `dd`; the songbook's songs have `dl.facts#facts-N`, renamed
`#facts` by book.js). **5d's laptop toolbar goes right after `header.head`.** page.py `facts_html(...)` writes the dl;
viewer.js `drawFacts()` redraws it in `render()`.

**kinds.js** (5b.5, on sheet pages and the harmonica page, not the songbook; `window.caracoleKinds`, frozen):
`GLYPHS` (the library card's drawings of `sheet`, `ukulele`, `guitar`, `harmonica`, `score`), `attach(o)` →
`{ links(), place() }` or null; the data member `kinds` (render.py `_kinds_data`, shape in 5b.4); the list
`#version-list` holds `section.kind-group[data-kind]` each with `h3.kind-head` and `ol.vers`.

### Before you start (both stages)

- **One branch a stage**, from `main`, in a worktree of its own: `git worktree add ../caracole-lane5 -b
  feat/sheet-5a-layers main`; after 5a merges, `git -C ../caracole-lane5 switch -c feat/sheet-5b-header main`.
- **Tests** through the dev shell; browser tests carry `pytestmark = CHROMIUM_MARKS` (helpers/browser.py) and wait for
  states (`b.wait(...)`), never fixed times. Phone `{"width": 390, "height": 844, "mobile": True}`, laptop
  `{"width": 1280, "height": 800, "mobile": False}`, as test_viewer_panels.py's `PHONE`/`DESKTOP`.
- **The corpus step** (every task below that changes a viewer asset, page.py's markup or data, harptab_page.py,
  book.py, book.js or render.py's page data — that is, nearly all of them; each says "corpus step" in its Step 4):
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py` (twice: some read what others
  write), then `nix develop -c pytest -q -n 0 tests/test_conformance_*.py` clean, then
  `nix develop ./android -c gradle -p android :viewer:test :server:test`; `git add tests/conformance/` with the task. A
  Kotlin test that breaks is this task's to fix, in the Kotlin file the task names.
- **Docs in the same commit**: docs/usage.md's "The sheet viewer" and AGENTS.md's "viewer/" bullets, where the task says.

---

### Stage 5a · Layers and Back, full screen

#### Task 5a.1: layers.js, the history of a page's layers

**Files:**
- Create: `src/caracole/viewer/layers.js`
- Modify: `src/caracole/viewer/page.py` (`BUILD_FILES` + `HERE / "layers.js"`; `_layers()` loader as `_winds()`;
  `build_viewer`'s scripts `(_sound(), _overlay(), _instruments(), _winds(), _layers(), script)`; the module docstring's
  "five scripts" → six)
- Modify: `src/caracole/viewer/book.py` (`build_songbook`'s scripts: `book_script, _sound(), _overlay(), _instruments(),
  _winds(), _layers(), script`; docstring "six scripts" → seven)
- Modify: `src/caracole/viewer/harptab_page.py` (scripts `(_sound(), _overlay(), _layers(), script)`; docstring)
- Modify: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/ViewerAssets.kt` (`Page`: `layers.js`
  before `viewer.js` in SHEET and SONGBOOK, before `harptab.js` in HARMONICA),
  `.../viewer/render/RenderBuild.kt` (`ASSETS` + `"layers.js"`), `.../viewer/pages/HarmonicaPage.kt` (KDoc's scripts)
- Modify: `tests/test_viewer_book.py` (`len(scripts) == 7`), `tests/test_viewer_harptab_page.py` (the scripts list:
  `strum.js, overlay.js, layers.js, harptab.js`; the `</script>` count + 1), `tests/test_conformance_viewer_harmonica.py`
  (the assets list near line 638 + `("layers.js", page._layers())`)
- Modify: `tests/helpers/viewer_pages.py` (`back`, `forward`, `entries`, `double_tap`)
- Test: `tests/test_viewer_layers.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `caracoleLayers.history(back) → { sync(count) }` and the marker rule above; `page._layers()`;
  helpers/viewer_pages.py `back(b)` and `forward(b)` (the browser's own Back and Forward:
  `Page.getNavigationHistory`, then `Page.navigateToHistoryEntry` of the entry before or after `currentIndex`, waiting
  until `currentIndex` moved), `entries(b) -> tuple[int, int]` (`currentIndex`, number of entries), `double_tap(b, x, y)`
  (two `tap_at` 80 ms apart).

- [ ] **Step 1: Write the failing test** — test_viewer_layers.py, section "the history" on a bare page the test writes:
  `tmp_path/"bare.html"` = two buttons `#open`, `#shut`, `<script>` layers.js's text, then
  ```js
  window.n = 0; window.backs = [];
  const h = caracoleLayers.history((k) => { backs.push(k); n -= k; h.sync(n); });
  document.getElementById("open").onclick = () => h.sync(++n);
  document.getElementById("shut").onclick = () => h.sync(--n);
  document.documentElement.dataset.ready = "1";
  ```
  opened from `about:blank` (so the bare page is entry 1). Tests:
  - `test_each_layer_opened_is_one_entry_and_back_takes_one_off_saying_so`: `b.click("#open")` twice →
    `entries(b) == (3, 4)`, `b.js("history.state.caracoleLayer") == 2`; `back(b)` → `backs == [1]`, `n == 1`,
    `entries(b)[0] == 2`; `back(b)` → `backs == [1, 1]`, `entries(b)[0] == 1`, same document (`window.marker`, set
    after load, still 1).
  - `test_a_layer_the_page_closes_takes_its_entry_off_and_says_nothing`: open, shut → `entries(b)[0] == 1`,
    `backs == []`; `back(b)` → `location.href == "about:blank"`.
  - `test_opened_and_shut_in_one_task_is_no_entry`: `b.js("for (const id of ['open', 'shut', 'open']) document.getElementById(id).click()")` →
    `entries(b) == (2, 3)`.
  - `test_forward_onto_a_layers_entry_with_none_open_comes_back`: open, `back(b)`, `forward(b)` → waits until
    `entries(b)[0] == 1` again; `backs == [1]`.
  - `test_a_page_come_back_to_at_a_layers_entry_goes_back_to_its_own`: open, then
    `location.href = other.html` (a second bare page), `back(b)` → the bare page loads again; waits for
    `!history.state || !history.state.caracoleLayer` and `entries(b)[0] == 1`.
  - `test_a_history_that_refuses_entries_leaves_back_to_the_browser`: before any click,
    `history.pushState = () => { throw new DOMException("denied", "SecurityError"); }` and `window.errors = []` with an
    `error` listener; open, shut, open → `errors == []`, `entries(b) == (1, 2)`, `backs == []`.
  - `test_every_viewer_page_inlines_layers_js_before_its_own_script` (no browser): in `build_viewer(UG_CHO)`,
    `build_songbook(...)` and `build_harmonica_viewer("4 -4 5", title="T", tab_file="harmonica-1.txt")`, layers.js's text
    is inlined, and its `<script>` comes right before viewer.js's (harptab.js's).
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_layers.py`: no such file
  layers.js (FileNotFoundError while writing the bare page).
- [ ] **Step 3: Implement** — layers.js, an IIFE, `"use strict"`, standard library only, no DOM writes. The
  reconciliation (the tests leave the bookkeeping open):
  ```js
  const depthOf = (s) => (s && Number.isInteger(s.caracoleLayer) && s.caracoleLayer > 0 ? s.caracoleLayer : 0);
  let pushed = depthOf(history.state), wanted = 0, pending = false, queued = false, off = false;
  const settle = () => {
    queued = false;
    if (off || pending || wanted === pushed) return;
    try {
      if (wanted > pushed) for (; pushed < wanted; pushed++) history.pushState({ caracoleLayer: pushed + 1 }, "");
      else { pending = true; history.go(wanted - pushed); }
    } catch (err) { off = true; pending = false; }
  };
  addEventListener("popstate", (e) => {
    const depth = depthOf(e.state);
    if (pending) pending = false;
    else if (depth < pushed) { const k = pushed - depth; pushed = depth; back(k); return settle(); }
    pushed = depth;
    settle();
  });
  // sync(count): wanted = count; one queueMicrotask(settle) per task. settle() once at start.
  ```
  `pushState` with no URL (the document's own: allowed in caracole serve's sandbox, as `replaceState` already is). The
  Python and Kotlin changes are the lists in Files.
- [ ] **Step 4: Run it and see it pass** — the same command: 7 passed; then `nix develop -c pytest -q
  tests/test_viewer_book.py tests/test_viewer_harptab_page.py`; corpus step (theory_assets.jsonl and every page's
  digests move; `PhoneRenderTest` holds `RenderBuild.ASSETS` to the folder).
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/layers.js src/caracole/viewer/page.py
  src/caracole/viewer/book.py src/caracole/viewer/harptab_page.py android/viewer tests/test_viewer_layers.py
  tests/helpers/viewer_pages.py tests/test_viewer_book.py tests/test_viewer_harptab_page.py
  tests/test_conformance_viewer_harmonica.py tests/conformance/` — `feat(viewer): layers.js, one history entry a layer`.

#### Task 5a.2: The sheet viewer's layers in the history, one at a time on a phone

**Files:**
- Modify: `src/caracole/viewer/viewer.js` (`open`, `close`, `restack`, `closeAll`, `dropSheet`, `dock`, the Escape
  listener near line 1816, `save()`'s `replaceState`, the bar's scroll reveal near line 2818)
- Modify: `tests/test_viewer_panels.py` (`test_escape_closes_the_one_on_top_and_the_focus_goes_back_to_its_opener`:
  its phone case now has the card in the settings' place), `tests/test_viewer_overlay_sheet.py`
  (`test_the_settings_open_over_the_sheet_and_it_comes_back_once_they_close` → `test_on_a_phone_the_settings_take_the_sheets_place`)
- Modify: `docs/usage.md` ("The sheet viewer": a bullet **Back and Escape**), `AGENTS.md` (viewer/: a bullet
  "**Layers and Back**": layers.js, the marker, `replaceState(history.state, …)`, one at a time below 900 px)
- Test: `tests/test_viewer_layers.py` (section "a sheet's layers")

**Interfaces:**
- Consumes: `caracoleLayers.history`, `back`, `entries` (5a.1); helpers/version_pages.py `folder`, `WONDERWALL`;
  test_viewer_necks.py `served` (a page served with its policy and sandbox).
- Produces: the stack and `DOCKED` as in Interfaces; every layer element opened through `open()`.

- [ ] **Step 1: Write the failing test** — each test opens the page from `about:blank` and sets `window.marker = 1`:
  - `test_each_layer_is_one_entry_and_back_closes_it` parametrized `[("settings", PHONE), ("settings", DESKTOP),
    ("card", PHONE), ("card", DESKTOP), ("necks sheet", PHONE), ("versions", PHONE), ("versions", DESKTOP)]`, opened by
    a real click or tap (`b.click("#more")`; the first `G` chord via test_viewer_panels.py's `chord` and `tap_at`;
    `#necks-open`;
    `#ver-now` on `folder(tmp_path, WONDERWALL)["sheet.html"]`): after it, `entries(b)[0] == 2` and
    `history.state.caracoleLayer == 1`; `back(b)` → the layer hidden (`#necks` without `data-sheet`), `entries(b)[0] ==
    1`, `window.marker == 1`, and the focus on its opener (`#more`, the chord, `#necks-open`, `#ver-now`) as Escape
    leaves it.
  - `test_escape_or_its_close_button_takes_its_entry_off_too` parametrized `["Escape", "x"]` (settings, phone): after
    closing, `entries(b)[0] == 1`; `back(b)` → `about:blank`.
  - `test_on_a_phone_one_layer_at_a_time`: settings open, then a chord's card: `#panel` hidden, `#card` shown,
    `entries(b) == (2, 3)`; `back(b)` → both hidden, `entries(b)[0] == 1`.
  - `test_on_a_laptop_back_closes_the_one_on_top_first`: settings rail, then a card: `entries(b)[0] == 3`; `back(b)` →
    card hidden, settings shown; `back(b)` → settings hidden.
  - `test_a_change_made_with_a_layer_open_stays_after_back`: phone, settings, `b.click("#up")` →
    `[location.hash, history.state.caracoleLayer] == ["#t=1", 1]`; `back(b)` → `location.hash == "#t=1"`,
    `#shift` "+1".
  - `test_a_file_whose_history_refuses_entries_still_opens_and_closes_them` (brief case 1): `pushState` made to throw
    (as 5a.1), settings opened and closed by Escape, a card by ×: no page error (`window.errors == []`),
    `entries(b) == (1, 2)`.
  - `test_in_caracole_serves_sandbox_back_closes_a_layer`: `served({"/Artist/Title/sheet.html": (build_viewer(LONG),
    viewer_csp)})`, settings, `back(b)` → closed, same document, `String(window.origin) == "null"`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_layers.py -k "layer or escape
  or phone or laptop or change or file or sandbox"`: `entries(b)[0] == 1` after opening (no entry pushed).
- [ ] **Step 3: Implement** —
  - `const layerHistory = window.caracoleLayers ? caracoleLayers.history((k) => { for (let i = 0; i < k &&
    layers.length; i++) close(topLayer()); save(); }) : { sync() {} };` and `restack()` ends with
    `layerHistory.sync(layers.length)`.
  - `open(which, opener, nested = false)`: below 900 px (`!wide.matches`) every open layer but a nested one is closed
    first; from 900 px today's rails rule stays (settings, Harmony, versions one at a time); entries carry `nested`.
  - `DOCKED = [panel, card, harmony, vList, necksEl].filter(Boolean)`; `dock()`'s `there` is, below 900 px, the top
    open layer that is in `DOCKED`.
  - `save()`: `history.replaceState(history.state, "", …)`.
  - The reveal's long condition (`!sizes.hidden || !panel.hidden || …`) becomes `layers.length > 0 || !sizes.hidden ||
    keyboardIn(bar)` (Aa joins the stack in 5a.3).
  - Update the two existing tests' phone expectations as named in Files.
- [ ] **Step 4: Run it and see it pass** — the same command; then `nix develop -c pytest -q tests/test_viewer_panels.py
  tests/test_viewer_overlay_sheet.py tests/test_viewer_versions.py tests/test_viewer_reload.py`; corpus step.
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/viewer.js tests/test_viewer_layers.py tests/test_viewer_panels.py
  tests/test_viewer_overlay_sheet.py docs/usage.md AGENTS.md tests/conformance/` — `feat(viewer): Back closes the
  layer on top, one layer at a time on a phone`.

#### Task 5a.3: Aa and Export PDF's question are layers too

**Files:**
- Modify: `src/caracole/viewer/viewer.js` (`showSizes` → `open(sizes, sizeButton)` / `close(sizes)`; the outside
  `pointerdown`, the box's `focusout` and `slide(true)` close it; `restack` sets `#size`'s `aria-expanded`; the export
  question: `ask.showModal()` pushes `{el: ask, nested: true}` through `open(ask, $("export"), true)`; its `close`
  event (Escape, ×, Cancel, the backdrop, an answer) takes it out of `layers` and calls `restack()`; `close(ask)` is
  `ask.close()`)
- Test: `tests/test_viewer_layers.py` (section "Aa and the question")

**Interfaces:**
- Consumes: 5a.2's stack.
- Produces: `#sizes` and `#export-ask` in `layers`; opening any other layer closes Aa at every width (as today).

- [ ] **Step 1: Write the failing test** —
  - `test_aa_is_a_layer` (phone): `b.click("#size")` → `#sizes` shown, `entries(b)[0] == 2`; `back(b)` → hidden,
    `#size[aria-expanded=false]`; `#size` again, then a tap on the sheet's words (`tap(b, "#sheet .w")`) → hidden and
    `entries(b)[0] == 1`; settings open, then `#size` → `#panel` hidden, one entry.
  - `test_aa_beside_the_settings_rail_and_back_closes_aa_first` (laptop): settings, Aa → `entries(b)[0] == 3`;
    `back(b)` → `#sizes` hidden, `#panel` shown.
  - `test_back_closes_the_question_and_leaves_the_settings_under_it` (served as
    test_viewer_panels.py's `test_a_changed_version_asks_before_downloading`, `STOP_LINKS`, capo up twice, `#export`):
    `export-ask.open` and `entries(b)[0] == 3` on a phone (settings and the question); `back(b)` → `!ask.open`, `#panel`
    shown; Escape on the question → its entry off too (`entries(b)[0] == 2`).
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_layers.py -k "aa or question"`:
  `entries(b)[0] == 1` after Aa.
- [ ] **Step 3: Implement** — as in Files. The Escape listener drops its `!sizes.hidden` branch (Aa is a layer); the
  question keeps its own `keydown` (its focus trap) and its native Escape.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_viewer_panels.py
  tests/test_viewer_text_size.py tests/test_viewer_bar.py`; corpus step.
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/viewer.js tests/test_viewer_layers.py tests/conformance/` —
  `feat(viewer): Back closes Aa and Export PDF's question`.

#### Task 5a.4: The songbook stays on its song when Back closes a layer

**Files:**
- Modify: `src/caracole/viewer/book.js` (the `hashchange` listener: `save(); carryScreen(e.oldURL);` then
  `location.reload()` only when `songOf(e.oldURL) !== songOf(e.newURL)`, `songOf(url)` = the `song-N` the fragment
  starts with, or `""` for the contents; its three `history.replaceState(null, …)` pass `history.state`)
- Modify: `docs/usage.md` (the songbook paragraph: Back closes what a song opened, ← → as before)
- Test: `tests/test_viewer_songbook_browser.py`

**Interfaces:**
- Consumes: 5a.2 (a songbook song runs viewer.js's stack).
- Produces: `songOf(url)` in book.js; a fragment change that names the same song never reloads.

- [ ] **Step 1: Write the failing test** —
  - `test_back_closes_a_songs_layer_and_stays_on_the_song` parametrized `["file", "sandbox"]` (the sandbox through
    test_viewer_necks.py `served` with `songbook_csp`; brief case 1: no storage there): song 1 of a songbook of two
    (`BookSong`s of test_viewer_instruments_page.py's `IN_E` and `THREE`), `window.marker = 1`, settings, `#up` → hash
    `song-1=&t=1`; `back(b)` → `#panel`
    hidden, `window.marker == 1` (no reload), `#shift` "+1", `location.hash` still has `t=1`.
  - `test_a_step_to_the_next_song_with_a_layer_open_then_back_returns_to_it` (laptop): settings rail, the pager's
    `a[rel=next]` → song 2 shown (a load: `window.marker` gone); `back(b)` → song 1, no layer open, and after its settle
    `history.state` has no `caracoleLayer`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_songbook_browser.py -k back`:
  `window.marker` undefined (book.js reloaded on the fragment's change).
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_viewer_book.py
  tests/test_viewer_songbook_browser.py tests/test_viewer_reload.py`; corpus step.
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/book.js tests/test_viewer_songbook_browser.py docs/usage.md
  tests/conformance/` — `fix(viewer): a songbook reloads only when its song changes`.

#### Task 5a.5: The harmonica tab's page: Aa and the sheet of necks as layers

**Files:**
- Modify: `src/caracole/viewer/harptab.js` (a stack `layers` of `"sizes"` and `"sheet"`; `openLayer(name)` /
  `closeLayer(name)` wrapping `showSizes`, `openSheet`, `closeSheet`; below 900 px one at a time; the Escape listener
  closes the top one; `caracoleLayers.history` as viewer.js; `save()`'s `replaceState(history.state, …)`)
- Test: `tests/test_viewer_layers.py` (section "a harmonica tab's page", pages from test_viewer_harptab_browser.py's
  helpers)

**Interfaces:**
- Consumes: 5a.1.
- Produces: harptab.js `openLayer(name, opener)`, `closeLayer(name)`, `layers` (5a.8 adds `"full"`, 5b.8 `"list"`).

- [ ] **Step 1: Write the failing test** — `test_on_a_harmonica_page_aa_and_the_necks_sheet_are_one_entry_each`
  (phone): `#size` → one entry, `back(b)` closes it; `#necks-open` → `#necks[data-sheet]`, one entry, `back(b)` closes
  it, the focus on `#necks-open`; sheet open then `#size` → the sheet closed, `entries(b)[0] == 2`;
  `#h-up` with the sheet open → `history.state.caracoleLayer == 1` still.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_layers.py -k harmonica`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q
  tests/test_viewer_harptab_browser.py tests/test_viewer_overlay_sheet.py`; corpus step.
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/harptab.js tests/test_viewer_layers.py tests/conformance/` —
  `feat(viewer): Back closes a harmonica page's layers`.

#### Task 5a.6: Full screen on the sheet viewer (Hide controls, a double tap, the handle)

**Files:**
- Modify: `src/caracole/viewer/page.py` (`_HANDLE = '<button type="button" class="handle" id="handle" hidden
  aria-label="Show controls"></button>\n'`; `_FULL_ROW = '<div id="full-row"><button type="button" class="goto"
  id="full-open"><span class="goto-lab">Hide controls</span><span class="goto-v">full screen' + _GO +
  '</span></button></div>\n'`; `_CONTROLS`: `data-controls` on `<div class="bar" id="bar" …>`, `_FULL_ROW` first in
  `#places` (before `_HARMONY_ROW`), `_HANDLE` right after the pill's `</div>`; the comment above `_CONTROLS`)
- Modify: `src/caracole/viewer/layers.js` (`doubleTap`, `DOUBLE_MS`, `DOUBLE_PX`)
- Modify: `src/caracole/viewer/viewer.css` (`.handle`; `html[data-full] :is([data-controls], .facts, .why) { display:
  none !important; }`)
- Modify: `src/caracole/viewer/viewer.js` (`handle` a layer: `open(handle, opener)` sets `doc.dataset.full = "on"`,
  shows it, `drawNecks()`, `layout()`; `close(handle)` the reverse; `landing(handle)` is the handle; `railOn()` and
  `drawNecks()` read `!doc.dataset.full`; `#full-open` → `close(panel)`, `open(handle, more)`; `doubleTap(document,
  MARGIN_SKIP, …)` opens it unless `data-full` is set; the handle's click closes it)
- Modify: `docs/usage.md` (a bullet **Full screen**), `AGENTS.md` (viewer/: full screen, `data-controls`)
- Test: `tests/test_viewer_full_screen.py` (new)

**Interfaces:**
- Consumes: 5a.2's stack, `double_tap` (5a.1).
- Produces: `#handle`, `#full-open`, `[data-controls]`, `html[data-full]`, `caracoleLayers.doubleTap`; viewer.js's
  `MARGIN_SKIP` = `"a, button, input, select, textarea, summary, label, [role=button], [tabindex], .c, .s, .w, .y, .m,
  pre, h1, h2, h3, .artist, .facts, .versions, .sheet-ui, .bar, .pill, .handle, .necks, .strip, .tip, details, .notice,
  .credit, .foot, .pager"`.

- [ ] **Step 1: Write the failing test** —
  - `test_the_page_has_a_handle_and_hide_controls` (no browser): `build_viewer(UG_CHO)` holds `_HANDLE` once, hidden,
    named "Show controls"; `#bar` carries `data-controls`; `#full-open` reads "Hide controls" and is the first row of
    `#places`; a songbook's page holds both too.
  - `test_hide_controls_hides_the_bar_the_facts_and_the_rail_and_the_handle_brings_them_back` (laptop 1280: the rail
    shows): `#more`, `#full-open` → `data-full == "on"`, `#bar`'s and `#facts`' `display == "none"`, `#necks` hidden and
    no `data-necks`, `#sheet` wider than before, `#handle` shown at the foot (its bottom within 1 px of `innerHeight`,
    centred), `#panel` hidden, `entries(b)[0] == 2`, the focus on `#handle`; `b.click("#handle")` → all back,
    `entries(b)[0] == 1`, the focus on `#more`.
  - `test_escape_or_back_brings_the_controls_back` parametrized `["Escape", "back"]`.
  - `test_a_double_tap_beside_the_song_hides_the_controls` (phone, LONG): `double_tap(b, 4, 420)` (the page's left
    padding) → `data-full == "on"`, one entry; laptop: two `click_at(b, 120, 400)` (the column's left margin) → the same.
    A double tap on a word (`#sheet .w`'s box) or on the title → no `data-full`.
  - `test_on_a_phone_a_layer_opened_in_full_screen_brings_the_controls_back`: full screen, then a chord tapped → the card
    docked, `#bar` shown, no `data-full`, `entries(b)[0] == 2`; laptop: the card opens over full screen (`data-full`
    kept, `entries(b)[0] == 3`), `back(b)` closes the card alone.
  - `test_the_handle_is_a_thumbs_target_at_320_px` (`width: 320`): its box ≥ 48 × 48 px, no sideways scroll
    (`helpers.targets.small_targets` finds none of it).
  - `test_full_screen_does_not_move_under_reduced_motion` (`reduced=True`): `getComputedStyle(handle).transitionDuration`
    and the bar's are `"0s"`.
  - `test_a_songbook_song_goes_full_screen_and_its_arrows_still_change_songs`: song 1 of the 5a.4 songbook, full
    screen, `key(b, "ArrowRight", 39)` → song 2 shown.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_full_screen.py`: no `#handle`.
- [ ] **Step 3: Implement** — as in Files. `.handle`: `position: fixed; z-index: 8; left: 50%; bottom: 0;
  transform: translateX(-50%); width: 96px; height: calc(28px + env(safe-area-inset-bottom)); padding: 0 0
  env(safe-area-inset-bottom); border: 0; background: none; cursor: pointer;` its bar a `::before` (40 × 5 px, radius
  3 px, `var(--muted)`, opacity .7); `@media (pointer: coarse) { .handle { height: calc(48px +
  env(safe-area-inset-bottom)); } }`; a 150 ms opacity transition, none under `prefers-reduced-motion`. A double tap
  while `data-full` is set does nothing.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_viewer_panels.py
  tests/test_viewer_necks.py tests/test_viewer_layout.py tests/test_viewer_print.py`; corpus step (page.json's
  `_CONTROLS` and `_SHEET_CONTROLS` move: the Kotlin port reads them as data and needs no change).
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/page.py src/caracole/viewer/layers.js src/caracole/viewer/viewer.css
  src/caracole/viewer/viewer.js tests/test_viewer_full_screen.py docs/usage.md AGENTS.md tests/conformance/` —
  `feat(viewer): full screen, from More or a double tap beside the song`.

#### Task 5a.7: On a short screen the controls slim to the handle by themselves

**Files:**
- Modify: `src/caracole/viewer/layers.js` (`SHORT`)
- Modify: `src/caracole/viewer/viewer.js` (`const short = matchMedia(caracoleLayers.SHORT)`; `autoFull()` at start and
  on `short`'s `change`: sets `doc.dataset.full = "auto"` and shows the handle when it matches, no layer is open and
  `data-full` is unset, and `slimmed` is false; ends it when it stops matching; the handle's click and Escape in
  `"auto"`, and any `open()`, end it and set `slimmed = true` until `short` changes again; no history entry)
- Modify: `docs/usage.md` (the Full screen bullet: on its side)
- Test: `tests/test_viewer_full_screen.py`

**Interfaces:**
- Consumes: 5a.6.
- Produces: `html[data-full="auto"]`; `caracoleLayers.SHORT`.

- [ ] **Step 1: Write the failing test** —
  - `test_under_500_px_tall_the_controls_slim_by_themselves_and_a_tap_brings_them_back` (`{"width": 844, "height":
    390, "mobile": True}`): at load `data-full == "auto"`, `#bar` not displayed, `entries(b) == (1, 2)` (no entry);
    `tap(b, "#handle")` → controls back, no `data-full`; a scroll down and up leaves them (no auto again).
    `Emulation.setDeviceMetricsOverride` to 390 × 844 → nothing; back to 844 × 390 → `"auto"` again.
  - `test_escape_and_a_layer_opened_bring_them_back_too`: `"auto"`, Escape → gone; another load, a chord tapped → card
    shown, `#bar` shown.
  - `test_501_px_tall_is_no_short_screen` (`height: 501`): no `data-full`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_full_screen.py -k "500 or
  short or escape_and"`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_viewer_bar.py
  tests/test_viewer_scroll.py`; corpus step.
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/layers.js src/caracole/viewer/viewer.js
  tests/test_viewer_full_screen.py docs/usage.md tests/conformance/` — `feat(viewer): a phone on its side slims the
  controls to the handle`.

#### Task 5a.8: Full screen on the harmonica tab's page

**Files:**
- Modify: `src/caracole/viewer/harptab_page.py` (`_BAR`, and so `_BAR_RAW`: `data-controls` on `#bar`;
  `_PILL = """…""" + page._HANDLE`, imported from page.py)
- Modify: `src/caracole/viewer/harptab.js` (layer `"full"`: `data-full`, the handle, the rail off while it is set
  (`drawRail`), Escape and Back; `caracoleLayers.doubleTap(document, MARGIN_SKIP + ", .h, .rp, .legend, .why", …)`; the
  short screen as viewer.js)
- Modify: `docs/usage.md` (the harmonica page's paragraph: full screen by a double tap and on its side)
- Test: `tests/test_viewer_full_screen.py` (section "a harmonica tab's page")

**Interfaces:**
- Consumes: 5a.5, 5a.6, 5a.7.
- Produces: harptab.js's `"full"` layer.

- [ ] **Step 1: Write the failing test** — `test_a_harmonica_page_goes_full_screen_by_a_double_tap` (laptop, a readable
  tab with a sheet): double click on the left margin → `#bar`, `#facts`, `.why` not displayed, `#necks` hidden, the
  handle shown, one entry; `back(b)` → all back. `test_a_harmonica_page_on_its_side_slims_its_controls` (844 × 390):
  `"auto"`. `test_a_tab_shown_as_written_has_the_handle_too` (`_BAR_RAW`).
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_full_screen.py -k harmonica`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q
  tests/test_viewer_harptab_page.py tests/test_viewer_harptab_browser.py`; corpus step (harmonica_page.json's `_BAR`,
  `_BAR_RAW` and `_PILL` move; HarmonicaPage.kt reads them as data).
- [ ] **Step 5: Commit** — `git add src/caracole/viewer/harptab_page.py src/caracole/viewer/harptab.js
  tests/test_viewer_full_screen.py docs/usage.md tests/conformance/` — `feat(viewer): full screen on a harmonica tab's
  page`.

#### Task 5a.9: Android's Back closes a sheet's layer in the app

**Files:**
- Create: `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/SheetLayersBackTest.kt`
- Modify: `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/Pages.kt` (`tapElement(scenario,
  selector)`: a touch down and up at the element's centre, its CSS box × `web.scale` from the WebView's place on the
  screen, injected as `tapLink` injects its touch, so the page's handler runs with a user activation)
- Test: that class, on the device step

**Interfaces:**
- Consumes: 5a.2; PagesServedTest's set-up (the render corpus's `ug_sheet` song, the phone's own pages).

- [ ] **Step 1: Write the failing test** — `aBackClosesTheSettingsAndTheSheetStays`: the song's `sheet.html` opened in
  MainActivity's WebView (as PagesServedTest's `open`), `window.marker = 1`; `tapElement(main, "#more")` → waits for
  `!document.getElementById('panel').hidden`; `instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)` → waits for
  `panel.hidden`, and `url(main)` still ends with `/sheet.html` (its fragment aside), `window.marker === 1`; a second
  Back → the library page.
- [ ] **Step 2: Run it and see it fail** — on 5a's branch before 5a.2 merges into it, or by reverting viewer.js's
  `restack` sync locally: `android/scripts/device-test.sh io.github.danielhp95.caracole.SheetLayersBackTest` fails on
  "sheet.html" after Back (the app left the page).
- [ ] **Step 3: Implement** — the test and `tapElement` only; MainActivity's Back already calls `web.goBack()`
  (`doUpdateVisitedHistory` registers its callback on a `pushState` too).
- [ ] **Step 4: Run it and see it pass** — `android/scripts/device-test.sh io.github.danielhp95.caracole.SheetLayersBackTest`.
- [ ] **Step 5: Commit** — `git add android/app/src/androidTest` — `test(android): Back closes a sheet's layer in the
  app`.

#### Task 5a.10: Merge 5a

- [ ] `nix develop -c pytest -q`; corpus check clean (`nix develop -c pytest -q -n 0 tests/test_conformance_*.py`);
  `nix develop ./android -c gradle -p android test`; `nix flake check`; `CARACOLE_ANDROID_E2E=1 nix develop -c pytest
  -q -n 0 tests/test_android_e2e.py` (the corpus moved); `android/scripts/device-test.sh --area pages,harmonica-page,render`
  and `android/scripts/device-test.sh io.github.danielhp95.caracole.SheetLayersBackTest`.
- [ ] Checked on screen (the anti-goal: each stage seen before it merges): `caracole serve` on a phone-sized window
  and the app — open each layer, Back closes it; Hide controls, the handle; a phone on its side.
- [ ] `git switch main && git merge --no-ff feat/sheet-5a-layers && GH_TOKEN="$(gh auth token --user Danielhp95)" git
  push origin main`.

---

### Stage 5b · The header and the versions list

#### Task 5b.1: The title block's ‹

**Files:**
- Modify: `src/caracole/viewer/page.py` (`_body`: `<a class="back" href="{LIBRARY_PAGE}" aria-label="Library"
  title="Library">‹</a>`)
- Modify: `src/caracole/viewer/harptab_page.py` (`_header`: `<a class="back" href="…" data-sheet aria-label="Chord
  sheet" title="Chord sheet">‹</a>`, or the library's as `_body`)
- Modify: `src/caracole/viewer/viewer.css` (`.back`: `width: 48px; height: 48px; margin: 0 0 0 -14px;
  justify-content: center; font-size: 1.75rem; line-height: 1;`)
- Modify: `android/viewer/.../pages/SheetPage.kt` (`body`), `.../pages/HarmonicaPage.kt` (`header`)
- Modify: `tests/test_viewer.py`, `tests/test_viewer_harptab_page.py` (their "‹ Library" / "‹ Chord sheet" text)
- Test: `tests/test_viewer_header.py` (new)

**Interfaces:**
- Produces: `a.back` as in Interfaces (harptab.js's `a.back[data-sheet]` unchanged).

- [ ] **Step 1: Write the failing test** — `test_the_title_block_opens_with_a_back_arrow_alone` (no browser): the
  sheet's `<a class="back" href="../../index.html" aria-label="Library" title="Library">‹</a>`; a harmonica page with
  `back="sheet.html"` → `href="sheet.html" data-sheet aria-label="Chord sheet"`. `test_the_back_arrow_is_48_px` (phone,
  320 px and 390 px): its box 48 × 48 px, its left ≥ 0.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_header.py`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same, then `nix develop -c pytest -q tests/test_viewer.py
  tests/test_viewer_harptab_page.py`; corpus step (`PagesReplay`, `HarmonicaPageReplay`).
- [ ] **Step 5: Commit** — `feat(viewer): the title block's ‹, a thumb's target` with the files above and
  `tests/conformance/`.

#### Task 5b.2: Tuning, Capo and Key as written (page.py, book.py, the Kotlin port)

**Files:**
- Modify: `src/caracole/viewer/page.py` (`_facts` → `facts_html(key, origin, capo, tuning, *, chords, suffix="")`;
  `GUITAR_STRINGS = " ".join(spelling(None)[n % 12] for n in instruments.GUITAR.tuning)` ("E A D G B E");
  `_read_song`: `data["tuningName"] = split_preamble(cho.splitlines()).tuning` when it names one (the PDF's rule,
  pdf_text.py); `_body` writes `facts_html(...)` in place of `<p class="facts" …>`; `key_line_text`'s docstring)
- Modify: `src/caracole/viewer/book.py` (`_song`: `facts_html(..., suffix=f"-{n}")`)
- Modify: `src/caracole/viewer/viewer.css` (`dl.facts { display: grid; grid-template-columns: max-content 1fr;
  gap: 2px 12px; margin: 10px 0 0; padding-top: 8px; border-top: 1px solid var(--border); font-size: .9rem; }`,
  `dl.facts .fact { display: contents; }`, `dl.facts dt { color: var(--muted); }`, `dl.facts dd { margin: 0;
  min-width: 0; overflow-wrap: anywhere; }`; `.facts .inst-line` goes)
- Modify: `android/viewer/.../pages/internal/PageHtml.kt` (`facts` → `factsHtml`), `.../pages/SheetPage.kt`
  (`factsHtml`, `body`, `readSong`'s `tuningName` through `Sheets.splitPreamble(PyStr.splitlines(cho)).tuning`),
  `.../pages/SongbookPage.kt` (its song's header), `android/viewer/src/testFixtures/.../replays/PagesReplay.kt`
  (`facts_html` in place of `_facts`)
- Modify: `tests/test_conformance_viewer_pages.py` (`parts_records`: `facts_html` records, every key of the corpus
  with origins, capos 0 and 2, tunings None and "Drop D", chords both ways, suffixes "" and "-3"; the docstring)
- Modify: `tests/test_viewer.py`, `tests/test_viewer_book.py` (their `_facts` assertions)
- Test: `tests/test_viewer_header.py`

**Interfaces:**
- Produces: `facts_html` and the dl as in Interfaces; the data's `tuningName`.

- [ ] **Step 1: Write the failing test** —
  - `test_the_facts_are_tuning_capo_and_key`: `facts_html(Key(9, "aeolian"), "from the tab", 0, None, chords=True)` ==
    `'<dl class="facts" id="facts">\n<div class="fact" data-fact="tuning"><dt>Tuning</dt><dd>E A D G B E</dd></div>\n'
    '<div class="fact" data-fact="capo"><dt>Capo</dt><dd>none</dd></div>\n<div class="fact" data-fact="key"><dt>Key'
    '</dt><dd><b>Am</b> · <span class="from">from the tab</span></dd></div>\n</dl>\n'`.
  - `test_with_a_capo_the_key_says_the_shapes_and_the_sound`: `Key(4, "aeolian")`, capo 2 → capo `<dd>2</dd>`, key
    `<dd><b>Em</b> shapes · sounds <b>F#m</b> · <span class="from">key from the tab</span></dd>` ("Key Em" never alone).
  - `test_a_tuning_the_sheet_names_is_its_tuning_line`: a ChordPro whose notes say "Tuning: Drop D" → `build_viewer`'s
    `<dd>Drop D</dd>` and data `tuningName == "Drop D"`; one with no tuning has no `tuningName`.
  - `test_no_key_no_key_line_and_no_chords_no_facts`: key None → Tuning and Capo rows only; `chords=False` → `""`.
  - `test_a_songbook_song_has_the_three_lines`: `build_songbook` song 2's `<dl class="facts" id="facts-2">`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_header.py -k facts`:
  `facts_html` missing.
- [ ] **Step 3: Implement** — as in Files; a value escaped, the key's words as today's `_facts` (no "Key " prefix,
  no "capo N" part: the Capo row says it).
- [ ] **Step 4: Run it and see it pass** — the same, then `nix develop -c pytest -q tests/test_viewer.py
  tests/test_viewer_book.py tests/test_keys.py tests/test_pdf_text.py`; corpus step (pages_parts.jsonl, pages-*.jsonl,
  songbook_pages.jsonl).
- [ ] **Step 5: Commit** — `feat(viewer): the song's facts on three lines, Tuning, Capo and Key` with the files above
  and `tests/conformance/`.

#### Task 5b.3: The facts as the song is played

**Files:**
- Modify: `src/caracole/viewer/viewer.js` (`drawFacts()` in `render()` in place of the `#facts` block near line 956;
  `keyFacts(moved)`: no capo `[["", sounds, moved, key.from]]`, a capo `[["", keyName(shift()), " shapes", ""],
  ["sounds ", sounds, moved, ""]]` and `["", "", "", "key " + key.from]`; `keyLine` stays for `keyLabel`)
- Modify: `docs/usage.md` ("The sheet viewer": the header's facts)
- Test: `tests/test_viewer_header.py`

**Interfaces:**
- Consumes: 5b.2's markup and `tuningName`; `data.names[""]` (the twelve names with no key) for an instrument's strings.
- Produces: `drawFacts()`; rows: Tuning on a `strings` instrument (the guitar: `tuningName`, else its strings; another:
  its `tuning`'s names), Capo where the instrument takes one (`takesCapo()`: "none" or `capoNow()`), Key with a key,
  and `inst` (`dt` the instrument's name, `dd` `headerLine()`) where its script gives one.

- [ ] **Step 1: Write the failing test** — `ROWS = "[...document.querySelectorAll('#facts .fact')].map((r) =>
  [r.dataset.fact, r.querySelector('dd').textContent])"`:
  - `test_the_facts_follow_the_capo_and_the_transposition` (UG_CHO, G shapes capo 2): at load `[["tuning", "E A D G B
    E"], ["capo", "2"], ["key", "G shapes · sounds A · key from the tab"]]`; `#capo-down` twice → capo "none", key
    "A · from the tab"; `#up` → key "A# (+1) · …" as `keyName` spells it (assert the bold text and " (+1)").
  - `test_another_instrument_has_its_own_strings_and_one_with_none_has_no_tuning_or_capo` (brief case 4): Instrument
    ukulele → tuning "G C E A"; piano → rows `["key"]` only; harmonica → no tuning, no capo, an `inst` row from
    winds.js.
  - `test_a_long_name_and_a_chinese_sheet_fit_a_320_px_phone` (brief case 2; test_viewer_pinyin.py's Chinese sheet, a
    120-character title and artist, Pinyin on and Traditional): no sideways scroll, every `dd` inside the screen,
    the h1 wrapped, the names in the characters chosen.
  - `test_a_songbook_song_draws_its_facts_too`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_header.py -k "follow or
  instrument or 320 or songbook"`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same, then `nix develop -c pytest -q tests/test_viewer_instruments_page.py
  tests/test_viewer_winds_page.py tests/test_viewer_pinyin.py tests/test_viewer_hanzi.py`; corpus step.
- [ ] **Step 5: Commit** — `feat(viewer): the facts follow the capo, the key and the instrument`.

#### Task 5b.4: render.py gives every page of the song its other kinds

**Files:**
- Modify: `src/caracole/render.py` (`_kinds_data(conn, song, files, tabs) -> dict`; `render_song` passes it as
  `kinds=` to the human sheet's viewer and an auto sheet standing alone (`_render_sheet`, `_write_viewer`) and to each
  version page (`_render_versions`, `_render_version`), never to an auto sheet beside a human one; `_SCORE_FORMATS`)
- Modify: `src/caracole/viewer/page.py` (`build_viewer(..., kinds=None)` → `data["kinds"] = dict(kinds)` after
  `versions`; docstrings)
- Modify: `android/viewer/.../pages/SheetPage.kt` (`ViewerInputs.kinds: JsonObject? = null`, `build`),
  `.../render/internal/SongPass.kt` (`kindsData()`, render.py's, passed where render.py passes it; a source's name from
  `page/empty_library.json`'s `icons`, as PhoneRender reads it), PagesReplay.kt (kw `kinds`)
- Modify: `tests/test_conformance_viewer_pages.py` (`_options` draws a `kinds` from `_kinds(rng)`)
- Test: `tests/test_render_kinds.py` (new; test_render_harmonica.py's `keep_sheet`, `keep_tab`, `render`, `data_of`)

**Interfaces:**
- Produces: the data's `kinds`:
  ```json
  {"sheet": "sheet", "page": "sheet.html", "groups": [
    {"kind": "guitar", "items": [{"name": "guitar-1.gp5", "label": "Guitar Pro 1 · gtptabs", "browser": true,
                                  "download": "Artist - Title.gp5"}]},
    {"kind": "tab", "items": [{"name": "tab.txt", "label": "Guitar tab · UG"}]},
    {"kind": "harmonica", "items": [{"name": "harmonica-1.txt", "label": "Harmonica tab 1 · harptabs",
                                     "page": "harmonica-1.html"}]},
    {"kind": "gametab", "items": [{"name": "gametab-1.txt", "label": "Game music tab 1 · gametabs"}]},
    {"kind": "score", "items": [{"name": "score-1.pdf", "label": "Score 1 (PDF)"},
                                {"name": "score-1.mscz", "label": "Score 1 (MuseScore)", "download": "Artist - Title.mscz"}]}]}
  ```
  `sheet`: `"ukulele"` when `sheet_versions.sheet_kind(conn, song.id) == "ukulele"`, `"sheet"` for any other kept
  sheet, null for none; `page`: `"sheet.html"` with a human sheet, else `"sheet (auto).html"`, else null; groups in
  the card's order (guitar, tab, harmonica, gametab, score), only those with items, items by N then name; a label's
  " · <source>" is `icons.SOURCES[provider].name` of the file's version, none for the inbox; "Power Tab N" for a `.ptb`;
  `download` is `download_name(song.artist, clean_title(song.title), name)` for every Guitar Pro file and every score
  but a PDF; `browser` is `GuitarFile.in_browser`.

- [ ] **Step 1: Write the failing test** — `test_every_viewer_of_the_song_names_its_other_kinds`: a song with a UG
  sheet and a kept version, `guitar-1.gp5` (gtptabs), `guitar-2.ptb` (inbox), `tab.txt`, `harmonica-1.txt`,
  `gametab-1.txt`, `score-1.pdf` and `score-1.mscz` (inbox) → `data_of(sheet.html, "song")["kinds"]` equals the shape
  above for those files, and the version page's data the same; `test_a_ukulele_sheet_is_ukulele_chords`;
  `test_an_auto_sheet_beside_a_human_one_names_none`; `test_a_song_with_nothing_else_has_its_sheet_alone`
  (`groups == []`); `test_the_score_formats_are_the_library_cards` (`render._SCORE_FORMATS ==
  library_page._SCORE_FORMATS`).
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_render_kinds.py`: no `kinds`.
- [ ] **Step 3: Implement** — as in Interfaces; one query of the song's files and their versions' providers
  (`kept_files`, `get_version`), `guitar_files`, the harmonica `tabs` already read in `render_song`.
- [ ] **Step 4: Run it and see it pass** — the same, then `nix develop -c pytest -q tests/test_render_versions.py
  tests/test_render_harmonica.py tests/test_render_all.py`; corpus step (render.jsonl: `RenderReplay` and SongPass.kt).
- [ ] **Step 5: Commit** — `feat(render): every viewer of a song names its other kinds`.

#### Task 5b.5: kinds.js and the version line with an icon a kind

**Files:**
- Create: `src/caracole/viewer/kinds.js` (`GLYPHS`; `attach(o)`; the line: `#ver-line`'s words and `#kinds`'s icons)
- Modify: `src/caracole/viewer/page.py` (`_VERSIONS` = `<div class="versions" id="versions" hidden>\n<button
  type="button" class="vnow" id="ver-now" aria-haspopup="dialog" aria-controls="version-list"
  aria-expanded="false"><span id="ver-line"></span><svg …today's chevron…/><span class="kinds" id="kinds"></span>
  </button>\n</div>\n`; `_body` places it after the artist line, before `facts_html`; `BUILD_FILES` + kinds.js;
  `_kinds()` loader; scripts `(…, _winds(), _layers(), _kinds(), script)`)
- Modify: `src/caracole/viewer/viewer.js` (the versions block near lines 2362–2534 moves into kinds.js; `‹ ›`
  (`vPages`, `vAt`, `#ver-prev`, `#ver-next`) go; `const kinds = window.caracoleKinds ? caracoleKinds.attach({data,
  here: pageName(), served, sheetPath: sheetPath(), carry: vAddress, open, close, inSight}) : null;` `save()` calls
  `kinds && kinds.links()` in place of `versionLinks()`)
- Modify: `src/caracole/viewer/viewer.css` (`.vstep` goes; `.kinds { display: inline-flex; gap: 10px; }`,
  `.kind { display: inline-flex; align-items: center; gap: 3px; color: var(--muted); }`, `.kind svg { width: 16px;
  height: 16px; }`, `.kind .n { font-size: .8rem; font-variant-numeric: tabular-nums; }`)
- Modify: `android/viewer/.../ViewerAssets.kt` (SHEET + `kinds.js` before `viewer.js`), `.../render/RenderBuild.kt`
  (`ASSETS` + `"kinds.js"`)
- Modify: `tests/test_viewer_versions.py` (`SEEN` drops prev/next; the line tests; ‹ › tests go;
  `test_the_text_size_goes_along_to_the_next_version` and `…rail_of_necks_hidden…` read a list link's `href`)
- Modify: `docs/usage.md` (the versions paragraph near line 2461), `AGENTS.md` (viewer/ **Versions** bullet)
- Test: `tests/test_viewer_versions.py`

**Interfaces:**
- Consumes: 5b.4's `kinds`; 5a's `open`/`close`.
- Produces: `caracoleKinds.attach(o)`: `o = {data, here, served, sheetPath, carry(page) → href, open(el, opener),
  close(el), inSight(el)}`, returning `{links(), place()}`, or null on a page with no `#versions` or nothing to show;
  `GLYPHS`; the line's words: `[group name ("Chords", "Ukulele chords"), this page's "Ver N of M" (M = `versions.total`,
  none for M = 1) or, on a page that is none of UG's, `vOne.label` ("LaCuerda's sheet"), then its rating
  "★ 4.86 (408)" (votes `toLocaleString("en-US")`) or "New"]` joined " · ", no "the one" tag on the line; the icons in
  the card's order, the chord sheet's count `versions.total` (1 without versions), each group's its items'; a `.vh`
  span names them ("13 chord versions, 2 Guitar Pro files, 1 harmonica tab"). The line shows where `versions` lists
  any version, or the song has more than this page alone.

- [ ] **Step 1: Write the failing test** —
  - `test_the_line_names_the_kind_the_version_and_its_rating` (WONDERWALL, kinds with 2 Guitar Pro files and a
    harmonica tab): sheet.html "Chords · Ver 3 of 13 · ★ 4.86 (408)", version-39144 "Chords · Ver 1 of 13 · ★ 4.85
    (12,629)", version-2161290 "Chords · Ver 7 of 13 · acoustic · ★ 4.80 (1,204)"; the icons `[["sheet", "13"],
    ["guitar", "2"], ["harmonica", "1"]]`; no `#ver-prev`.
  - `test_one_version_and_one_kind_is_no_ver_1_of_1_and_one_icon` (brief case 3): total 1 → "Chords · ★ 4.86 (408)",
    icons `[["sheet", "1"]]`; a version with no rating → "… · New".
  - `test_a_lacuerda_sheet_says_so` and `test_a_ukulele_sheet_is_ukulele_chords` (icon `ukulele`).
  - `test_without_versions_or_other_kinds_there_is_no_line` and `test_the_songbook_has_no_line` (as today's).
  - `test_the_kind_icons_are_the_library_cards_drawings`: a page inlining library_assets/rows.js, then kinds.js, then a
    script comparing, for each name of `caracoleKinds.GLYPHS`, its paths with `caracoleRows({}).glyph(name)`'s (the
    sprite's `#glyph-NAME` symbol's paths where rows.js draws a `<use>`, else the svg's own) → all equal.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_versions.py -k "line or one_version
  or lacuerda or ukulele or without or songbook or icons"`.
- [ ] **Step 3: Implement** — as in Files and Interfaces; the five GLYPHS' paths copied from rows.js's `GLYPHS`, drawn
  as rows.js's `glyph` draws them (24-unit grid, stroke `currentColor`, width 1.8, round caps, `aria-hidden`).
- [ ] **Step 4: Run it and see it pass** — the same, then `nix develop -c pytest -q tests/test_viewer_versions.py
  tests/test_render_versions.py tests/test_sheet_versions_end_to_end.py`; corpus step.
- [ ] **Step 5: Commit** — `feat(viewer): the version line names the kind and counts every kind the song has`.

#### Task 5b.6: One list grouped by kind

**Files:**
- Modify: `src/caracole/viewer/page.py` (`_VERSION_LIST`: its head as today, the h2 "Versions", then `<div
  id="kind-groups"></div>`; `#ver-acts` and `#ver-items` are drawn inside the Chords group)
- Modify: `src/caracole/viewer/kinds.js` (`drawGroups()`: `section.kind-group[data-kind]` > `h3.kind-head` (its glyph,
  its name, its count); Chords: `#ver-acts` then `ol.vers#ver-items`, today's rows, the page's own ticked (a check
  glyph before its name, `aria-current="page"`, no link), "★ 4.85 (81)" or "New", Keep, Make this the one, Back to our
  pick and "On UG" as today; without `versions`, one row, the chord sheet (`kinds.page`), named "Chord sheet" or
  "Ukulele chords"; each other group `ol.vers` of `li.ver > a.ver-main`, named by its `label`: Guitar Pro served and
  `browser` → `/guitar?file=` + the encoded library path, "in the browser"; else the file with its `download`; a text
  tab and a game music tab their file; a harmonica tab its `page` + `carry`; a score PDF the file, any other score its
  `download`)
- Modify: `src/caracole/viewer/viewer.css` (`.kind-group + .kind-group { margin-top: 10px; }`, `.kind-head { display:
  flex; align-items: center; gap: 6px; margin: 4px 0; color: var(--muted); font-size: .75rem; font-weight: 800;
  letter-spacing: .08em; text-transform: uppercase; }`)
- Modify: `src/caracole/viewer/viewer.js` (the settings' Guitar Pro row stays: 5d's deduplication)
- Modify: `docs/usage.md` (the list's groups)
- Test: `tests/test_viewer_versions.py`

**Interfaces:**
- Consumes: 5b.5.
- Produces: `#kind-groups` as in Interfaces; `#ver-items`, `#ver-acts` keep their ids.

- [ ] **Step 1: Write the failing test** — `GROUPS = "[...document.querySelectorAll('#kind-groups .kind-group')].map((g)
  => [g.dataset.kind, g.querySelector('.kind-head').textContent, [...g.querySelectorAll('.ver-main')].map((m) =>
  [m.textContent, m.getAttribute('href'), m.getAttribute('download'), m.getAttribute('aria-current')])])"`:
  - `test_the_list_groups_every_kind_in_the_cards_order` (from a file, the 5b.4 song's kinds): kinds `["sheet",
    "guitar", "tab", "harmonica", "gametab", "score"]`; heads "Chords13", "Guitar Pro2", …; Chords' rows as today's
    `test_the_list_shows_every_version_and_opens_the_kept_ones` (13 rows, the one current with no link, "★ 4.85
    (12,629)"); Guitar Pro `["Guitar Pro 1 · gtptabs", "guitar-1.gp5", "Artist - Title.gp5", null]`; harmonica
    `["Harmonica tab 1 · harptabs", "harmonica-1.html", null, null]` (with `#necks=0` once the rail is hidden).
  - `test_served_guitar_pro_opens_in_the_browser_and_versions_keep_through_caracole_serve` (served): Guitar Pro 1's
    href `/guitar?file=Artist%2FTitle%2Fguitar-1.gp5`, the Power Tab still a download; Keep's
    `/versions?sheet=Artist%2FTitle%2Fsheet.html&tab=…&do=keep` as today.
  - today's `test_from_a_file_a_version_not_kept_links_to_ug_and_shows_the_command_that_keeps_it`,
    `…gone_version…`, `…makes_it_the_one`, `…caracoles_pick_back`, `…while_a_pin_chooses_the_sheet` kept, over
    `#ver-items`.
  - `test_a_song_with_no_versions_lists_its_sheet_and_its_other_kinds`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_versions.py -k "groups or
  served_guitar or no_versions"`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_viewer_versions.py`; corpus step.
- [ ] **Step 5: Commit** — `feat(viewer): the versions list grouped by kind, every kind a tap from it`.

#### Task 5b.7: The list's place: a sheet from the bottom on a phone, a popover on a laptop

**Files:**
- Modify: `src/caracole/viewer/layers.js` (`placeUnder(pop, anchor)`)
- Modify: `src/caracole/viewer/kinds.js` (`place()`: from 900 px `caracoleLayers.placeUnder(list, $("ver-now"))`)
- Modify: `src/caracole/viewer/viewer.js` (`rails = [panel, harmony]`: the list leaves the rails; `place()` and the
  `resize` handler call `kinds.place()`)
- Modify: `src/caracole/viewer/viewer.css` (from 900 px `#version-list { position: absolute; top: var(--pop-top);
  left: var(--pop-left); right: auto; bottom: auto; width: min(380px, calc(100vw - 32px)); max-height: 60vh;
  border-bottom: 1px solid var(--border); border-radius: 14px; }`; below, today's docked `.sheet-ui`)
- Modify: `AGENTS.md` (the **Versions** bullet: a sheet from the bottom, a popover from 900 px)
- Test: `tests/test_viewer_versions.py` (`…docks_at_the_foot…` and `…is_a_rail_and_one_rail_at_a_time` rewritten)

**Interfaces:**
- Produces: `caracoleLayers.placeUnder` (5d's key list).

- [ ] **Step 1: Write the failing test** — `test_on_a_phone_the_list_is_a_sheet_from_the_bottom_and_back_closes_it`
  (390 and 320 px): docked above the bar, no sideways scroll, `back(b)` closes it, one entry.
  `test_on_a_laptop_the_list_is_a_popover_under_the_line`: its top within 6–8 px under `#ver-now`'s bottom, its left at
  the line's, no `data-panel` (the song's column unchanged), the settings rail open beside it (`entries(b)[0] == 3`),
  `back(b)` closes the list first; it scrolls with the page.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_viewer_versions.py -k "phone or laptop"`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same, then `nix develop -c pytest -q tests/test_viewer_layers.py
  tests/test_viewer_panels.py`; corpus step.
- [ ] **Step 5: Commit** — `feat(viewer): the versions list from the bottom on a phone, under its line on a laptop`.

#### Task 5b.8: The harmonica tab's page has the version line and the list

**Files:**
- Modify: `src/caracole/render.py` (`_render_harmonica(..., listed, kinds)`: `versions=_on_page(listed, None)`,
  `kinds=`)
- Modify: `src/caracole/viewer/harptab_page.py` (`build_harmonica_viewer(..., versions=None, kinds=None)` →
  `data["versions"]`, `data["kinds"]` after `data["overlay"]` when given; `_header` puts `page._VERSIONS` after the
  artist line; the body appends `page._VERSION_LIST` after `_PILL`; scripts `(…, _layers(), _kinds(), script)`;
  docstring)
- Modify: `src/caracole/viewer/harptab.js` (layer `"list"`; `caracoleKinds.attach({data, here, served, sheetPath:
  folder + "/" + data.kinds.page, carry, open: openLayer, close: closeLayer, inSight})`; `carry(page)` as
  `backToSheet` builds its address; on a phone the list docks (`.top`, `data-dock="version-list"`, `--dock`))
- Modify: `android/viewer/.../pages/HarmonicaPage.kt` (`build(..., versions, kinds)`, `header`, the body),
  `.../ViewerAssets.kt` (HARMONICA + `kinds.js`), `.../render/internal/SongPass.kt` (the harmonica pages' inputs),
  `android/viewer/src/testFixtures/.../replays/HarmonicaPageReplay.kt` (kw `versions`, `kinds`)
- Modify: `tests/test_conformance_viewer_harmonica.py` (pages with `versions` and `kinds`; the assets list)
- Modify: `docs/usage.md` (the harmonica page: its line and list)
- Test: `tests/test_render_kinds.py`, `tests/test_viewer_versions.py` (section "a harmonica tab's page")

**Interfaces:**
- Consumes: 5b.4–5b.7; 5a.5's `openLayer`/`closeLayer`.
- Produces: the harmonica line's words `["Harmonica", "Tab N of M" (M > 1)]`; its own tab ticked in the Harmonica group.

- [ ] **Step 1: Write the failing test** — `test_a_harmonica_page_names_the_versions_and_the_kinds`
  (test_render_kinds.py): its `harp-data` has `versions` (every `this` false) and the sheet's `kinds`.
  `test_a_harmonica_page_has_the_line_and_the_list` (two tabs, WONDERWALL): line "Harmonica · Tab 1 of 2", icons as
  the sheet's; the list's Chords rows link `sheet.html` and the kept versions, none current; the Harmonica group's
  tab 1 current; served, Keep links `/versions?sheet=Artist%2FTitle%2Fsheet.html&…`; `back(b)` closes the list.
  `test_a_tab_with_no_sheet_and_nothing_else_has_no_line`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_render_kinds.py
  tests/test_viewer_versions.py -k harmonica`.
- [ ] **Step 3: Implement** — as in Files.
- [ ] **Step 4: Run it and see it pass** — the same, then `nix develop -c pytest -q tests/test_viewer_harptab_page.py
  tests/test_viewer_harptab_browser.py tests/test_render_harmonica.py`; corpus step (harmonica_pages*.jsonl,
  render.jsonl, theory_assets.jsonl).
- [ ] **Step 5: Commit** — `feat(viewer): a harmonica tab's page has the version line and its list`.

#### Task 5b.9: Merge 5b

- [ ] As 5a.10 (whole suite, corpus clean, gradle, `nix flake check`, the e2e test, the device step's areas
  `pages,harmonica-page,render`), checked on screen at 320, 390 and 1280 px, served and from a file and in the app.
- [ ] `git switch main && git merge --no-ff feat/sheet-5b-header && GH_TOKEN="$(gh auth token --user Danielhp95)" git
  push origin main`.

---

### Choices this draft makes where the design is silent (for the coordinator)

1. The library's glyphs live in library_assets/rows.js (lanes 1 and 3's), which the sheet pages don't inline: kinds.js
   holds a copy of the five drawings and a browser test holds them equal to rows.js's (sprite or not), so a redrawn
   glyph fails here.
2. D1/D2 C's line has no ‹ ›: the version steppers go; the list opens each kept version.
3. The harmonica page has no More: full screen there comes by a double tap and the short screen only.
4. The songbook's bullet in "Where it applies" names no layers or full screen, but its songs run viewer.js: they get
   both, and book.js stops reloading on a Back that only closes a layer.
5. The short screen's slim controls push no history entry (nothing was opened): Back leaves the page there.
6. On a phone, a layer opened in full screen (a chord's card) brings the controls back (one layer at a time).
7. The Capo line is left out on an instrument that takes no capo (piano, harmonica, winds), as the Tuning line is.
8. Layers opened at load (`#panel=1`, `#chord=`) push an entry without a user activation, which Chrome may skip on Back.
9. A page come back to at a layer's entry steps back to its own entry (same-document in Chromium; at worst one reload).
10. The auto sheet beside a human one keeps no line, as it has no versions today; kinds' sources are named as the
    library card names them ("gtptabs", none for the inbox), not the mockup's "gtptabs.com".
11. Full screen is a page's layer: a songbook's next song opens with the controls.

---

### Stage 5c: Lines

The design's 5c row: D3 A (wrapped tails flush left, about 0.4 em between sung lines and none between a line's rows),
a chord inside a word never splitting the word, D4 C (a chord-only line that writes bars drawn as bar cells with beat
dots; the PDF prints it as written), D8 B (two columns stepped down before one column), and the sheet's end leaving
room for the bar plus half a screen. Everything goes through page.py's one renderer, so sheet.html, a kept version's
page (`build_viewer(export=False)`) and a songbook's songs (book.py reuses `_song_html`) all change; the harmonica
tab's page has its own line markup (harptab_page.py) and keeps it.

What the code says that the design doesn't:

- **The bars are gone before the page sees them.** chordpro.py's `_chord_only` joins a chord-only line's chords with
  single spaces, so `Am C | G Em |` is `[Am] [C] [G] [Em]` in every `.cho` today, and the PDF prints no bars either.
  5c.1 makes the `.cho` keep them, as `[*|]` annotations, which ChordPro 6.050.7 prints in the chord row ("Am C | G
  Em |", checked by hand on 2026-11-17 with the dev shell's chordpro). That is the "one shared rule": `sheet.BAR`,
  which chordpro.py writes and sheet.py reads. pdf_text.py needs no code: its estimate already counts an annotation's
  width (5c.1 pins it).
- **Beats are counted evenly** (the design left it to the builder): the `.cho` keeps no spacing, so four beats a
  bar, shared by its chords.
- **D8 is today's rule at the default size.** viewer.css already sets two columns at `--fs` (18 px) and one column
  at `--fs` + 3 px (21 px); the research read it as two columns at 21 px. 5c.6 does what the design says: it tries
  two columns at 21, 20, 19 and then 18 px. But `columns: 2 28em` in a page of at most 1180 px gets two columns only
  at 19 px or less. So at the default size a song gets two columns at 19 px where it got 18 px, and no song gets two
  columns that didn't before. The steps are a table, `COLUMN_SIZES`. If the owner wants more songs in two columns,
  the step-down must go below the reader's text size (for example `[3, 2, 1, 0, -1, -2]`), or the 28em minimum must
  shrink. That is the owner's call: the plan doesn't take it.
- **The class names `.bar` and `.wd` are taken** (the controls bar; winds.js's fingering SVG), so the cells are
  `span.barcell` and a word's columns `span.word`.

What 5c takes from 5a and 5b, by role only: the bar's room as those stages leave it (viewer.css's `--foot`, the bar's
height with the safe-area inset, and `--pill`); the bar hidden in full screen (5a), where a test reads the window's
foot in its place; and `layout()`, `fit()` and the header markup wherever 5a and 5b leave them in viewer.js and
page.py. 5d's taller bar changes `--foot`, and 5c.5's room follows it.

**Stage setup**: once 5b has merged, `git -C /home/dani/Projects/caracole-lane5 switch -c feat/sheet-5c-lines main`.
Every task below runs in that worktree.

#### Task 5c.1: The .cho keeps a chord-only line's bars

**Files:**
- Modify: `src/caracole/viewer/sheet.py`: new `BAR`.
- Modify: `src/caracole/chordpro.py`: `_chord_items(line, *, bars=False)` and `_chord_only`.
- Modify: `tests/fixtures/chordpro/ug_sheet.cho`: its Outro line.
- Modify: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/sheet/ChordPro.kt`: `chordItems`,
  `chordOnly`.
- Modify: `tests/test_conformance_viewer_sheet.py`: `BAR` among `sheet`'s exported patterns, and its docstring's list.
- Modify: `docs/usage.md` (the PDF's paragraph, "Then the chord diagrams above the song, …") and `AGENTS.md`
  (render's "**chordpro.py**" line).
- Test: `tests/test_chordpro.py`, `tests/test_viewer_sheet.py`, `tests/test_pdf_text.py`, `tests/test_render.py`,
  `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/sheet/ChordProTest.kt`.

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `caracole.viewer.sheet.BAR = re.compile(r"[|:]*\|[|:]*")`, a bar line as chordpro.py writes it in a
  mark (`|`, `||`, `|:`, `:|`). A `ChordRow` item that `BAR.fullmatch`es is a bar line. A chord-only line in the
  `.cho` writes each bar line in its place as `[*<as written>]`, joined with the chords by single spaces. Lines of
  chords over words drop their bars, as today.

- [ ] **Step 1: Write the failing tests**

  `tests/test_chordpro.py`:
  ```python
  def test_a_chord_only_line_keeps_its_bars_as_marks():
      assert body("[ch]Am[/ch]    [ch]C[/ch]   | [ch]G[/ch]    [ch]Em[/ch]  |") == ["[Am] [C] [*|] [G] [Em] [*|]"]
      assert body("|: [ch]Am[/ch] | [ch]E[/ch] :|  x2") == ["[*|:] [Am] [*|] [E] [*:|] [*x2]"]
      assert body("[Intro] | [ch]G[/ch] || [ch]D[/ch] |") == ["{comment: Intro}", "[*|] [G] [*||] [D] [*|]"]

  def test_bars_over_a_lyric_line_are_left_out_as_before():
      assert body("[ch]G[/ch]  |  [ch]D[/ch]\nHello there my friend") == ["[G]Hello [D]there my friend"]
  ```
  In `tests/fixtures/chordpro/ug_sheet.cho`, change the Outro's line to `[G] [*|] [D] [*|] [C] [*(x4)]`, which is
  what `test_ug_sheet_converts_to_expected_chordpro` will now expect from `ug_sheet.txt`'s
  `[ch]G[/ch] / / / | [ch]D[/ch] / / / | [ch]C[/ch] (x4)`.

  `tests/test_viewer_sheet.py`: in `test_a_line_of_chords_alone_is_a_chord_row_with_its_marks` the Outro becomes
  `[ChordRow([0, "|", 1, "|", 3, "(x4)"])]`, and:
  ```python
  def test_a_bar_line_is_a_mark_that_bar_reads():
      assert [t for t in ("|", "||", "|:", ":|", ":||:", ":", "x2", "(x4)", "N.C.") if BAR.fullmatch(t)] == [
          "|", "||", "|:", ":|", ":||:"]
  ```
  `tests/test_pdf_text.py` pins the PDF's side of the rule. It passes already, because a bar line is an annotation to
  pdf_text.py:
  ```python
  def test_a_line_of_bars_is_one_row_of_chords():
      shape = layout()
      assert line_heights(["[Am] [C] [*|] [G] [Em] [*|]"], shape) == [shape.chords]
  ```
  `tests/test_render.py`, beside `test_render_real_chordpro_binary` and written the same way:
  ```python
  @pytest.mark.chordpro
  @real_chordpro
  def test_render_real_prints_a_lines_bars_as_written(tmp_path):
      cho = write_chordpro("[Intro]\n[ch]Am[/ch]  [ch]C[/ch] | [ch]G[/ch]  [ch]Em[/ch] |", tmp_path / "sheet.cho",
                           title="T", artist="A")
      printed = tmp_path / "printed.cho"
      printed.write_text(printed_text(cho.read_text(encoding="utf-8"), key=Key(9, "aeolian"), capo=None),
                         encoding="utf-8")
      render_pdf(printed, tmp_path / "sheet.pdf", chordpro_bin=CHORDPRO)
      page = pdf_pages(tmp_path / "sheet.pdf")[0]
      y = next(y for _, y, text in page if text.strip() == "|")
      assert [text.strip() for _, _, text in sorted(s for s in page if s[1] == y)] == ["Am", "C", "|", "G", "Em", "|"]
  ```
  `ChordProTest.kt`:
  ```kotlin
  @Test fun aChordOnlyLineKeepsItsBars() {
      assertEquals(listOf("[Am] [C] [*|] [G] [Em] [*|]"), body("[ch]Am[/ch]    [ch]C[/ch]   | [ch]G[/ch]    [ch]Em[/ch]  |"))
      assertEquals(listOf("{comment: Intro}", "[*|] [G] [*||] [D] [*|]"), body("[Intro] | [ch]G[/ch] || [ch]D[/ch] |"))
      assertEquals(listOf("[G]Hello [D]there my friend"), body("[ch]G[/ch]  |  [ch]D[/ch]\nHello there my friend"))
  }
  ```
- [ ] **Step 2: Run them and see them fail**: `nix develop -c pytest -q tests/test_chordpro.py tests/test_viewer_sheet.py
  tests/test_pdf_text.py tests/test_render.py -k "bar or ug_sheet or chord_row"`. Expect an ImportError on `BAR`; once
  that is stubbed, `['[Am] [C] [G] [Em]']` where the bars should be, and the fixture test failing on the Outro. The
  pdf_text pin passes.
- [ ] **Step 3: Implement**
  - sheet.py: add `BAR` (above) with a comment naming chordpro.py as its writer and `bars` (5c.2) as its reader.
  - chordpro.py: import `BAR` from `caracole.viewer.sheet`. This adds no import: `caracole.viewer`'s `__init__`
    already loads sheet.py, as autochords/merge.py's comment says. With `bars=True`, `_chord_items` adds a token
    `[*<match>]` at its display column for each `BAR` match in the plain text that is outside a chord's span and a
    mark's span. `_chord_only` passes `bars=True`; `merge_chord_line` keeps the default. Docstrings: `to_chordpro`'s
    list gains "bar lines on a chord-only line become annotations (`[*|]`)".
  - ChordPro.kt: the same, `BAR` read as `SheetData.sheet.pattern("BAR")`.
  - test_conformance_viewer_sheet.py: `"BAR"` joins the `_patterns(sheet, …)` tuple, and the docstring's `sheet` list.
  - docs/usage.md, in the PDF paragraph: "a line of chords alone that writes bars prints them as written ("Am C | G
    Em |")". AGENTS.md: "**chordpro.py**: UG markup to ChordPro; a chord-only line keeps its bar lines, as `[*|]`
    marks (`sheet.BAR`, which the page reads)."
- [ ] **Step 4: Run them and see them pass**: the Step 2 command, and `nix develop -c pytest -q -m "not slow"`. Any other
  test that pinned a bar line without its bars follows the new `.cho`. Then regenerate the corpus:
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, run twice. sheet.json,
  chordpro.jsonl and sheet.jsonl move, and so do the page and render vectors of every sheet with a bar line. Then
  `nix develop ./android -c gradle -p android test` passes. A replay that still fails is the Kotlin side's to follow
  in this task: `ChordPro.kt` first, because `SheetReplay`, `PagesReplay` and `RenderReplay` read its output.
- [ ] **Step 5: Commit**: `git add src/caracole/viewer/sheet.py src/caracole/chordpro.py tests/fixtures/chordpro/ug_sheet.cho
  tests/test_chordpro.py tests/test_viewer_sheet.py tests/test_pdf_text.py tests/test_render.py
  tests/test_conformance_viewer_sheet.py tests/conformance android/viewer docs/usage.md AGENTS.md`, then
  `feat(chordpro): keep a chord-only line's bars, which the PDF prints as written`.

#### Task 5c.2: A line that writes bars is a row of bar cells

**Files:**
- Modify: `src/caracole/viewer/sheet.py`: `BEATS`, `Bars`, `bars`.
- Modify: `src/caracole/viewer/page.py`: `_line_html`'s `ChordRow` branch, and a new `_bars_html`.
- Modify: `src/caracole/viewer/viewer.css`: `.l.bars`, `.barcell`, `.beat`.
- Modify: `src/caracole/viewer/__init__.py`: the docstring's sheet.py line.
- Modify: `tests/helpers/viewer_corpus.py`: one more `EDGE_SHEETS` entry, at the end.
- Modify: `tests/test_conformance_viewer_sheet.py`: `BEATS` exported; `read_of` gains `"bars"`.
- Modify: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/sheet/Sheet.kt` (`Bars`,
  `Sheets.bars`), `…/viewer/pages/internal/PageHtml.kt` (`lineHtml`, new `barsHtml`), and
  `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/SheetReplay.kt`
  (`readOf` checks `"bars"`).
- Modify: `docs/usage.md` (the viewer's bullets, after "Chords over the lyrics") and `AGENTS.md` (viewer/'s rules).
- Test: `tests/test_viewer_sheet.py`, `tests/test_viewer.py`, `tests/test_viewer_lines.py` (create),
  `android/…/viewer/sheet/SheetsTest.kt`, `android/…/viewer/pages/SheetPageTest.kt`.

**Interfaces:**
- Consumes: `sheet.BAR`, and the `[*|]` marks the `.cho` writes (5c.1).
- Produces:
  - `sheet.BEATS = 4`, a bar's beats.
  - `@dataclass(frozen=True) class Bars` with three fields: `lead: tuple[str, ...]`,
    `cells: tuple[tuple[tuple[int | str, int], ...], ...]` (each bar's items, each with its beats) and
    `tail: tuple[str, ...]`.
  - `def bars(line: ChordRow) -> Bars | None`.
  - Markup: `<p class="l chords bars">`, then the lead's marks (`_mark_html`), then a `<span class="barcell">` for each
    bar, then the tail's marks, all joined with no separator. In a cell, each item's HTML (`_chord_html` or
    `_mark_html`) is followed by its beats less one `<span class="beat" aria-hidden="true">·</span>`. An empty bar
    holds four of them. It stays one `p.l`, so `_drawn_lines` and the data's `pinyin` keep one entry a line.
  - Kotlin: `data class Bars(val lead: List<String>, val cells: List<List<Pair<Item, Int>>>, val tail: List<String>)`,
    `Sheets.bars(line: ChordRow): Bars?` and `PageHtml.barsHtml(bars: Bars, names: List<String>): String`.
  - Vectors: `read_of`'s `"bars"` is `[[i, j, {"lead", "cells", "tail"}], …]`, one entry for each line j of section i
    that `bars` reads (an item an int or a string).

The rule, which `bars`' docstring states once:
- The answer is None unless the line holds a chord and a bar line.
- `lead` is the marks before its first chord, and `tail` the marks after its last. Bar lines there are dropped.
- From the first chord to the last, the items split at each bar line, and each piece is a cell. A piece with nothing
  in it, between two bar lines, is an empty cell.
- In a cell, its chords and marks share `BEATS`: `[BEATS // n + (i < BEATS % n) for i in range(n)]` for n ≤ `BEATS`
  items, else one beat each.
- A legend line (`is_legend`) is never drawn as bars.

- [ ] **Step 1: Write the failing tests**

  `tests/test_viewer_sheet.py`:
  ```python
  def row(text):
      return parse_sheet("{title: T}\n" + text + "\n").sections[0].lines[0]

  def test_a_line_of_chords_that_writes_bars_reads_as_bars_and_beats():
      assert bars(row("[Am] [C] [*|] [G] [Em] [*|]")) == Bars((), (((0, 2), (1, 2)), ((2, 2), (3, 2))), ())
      assert bars(row("[*|:] [Am] [*|] [*|] [E] [*:|] [*x2]")) == Bars((), (((0, 4),), (), ((1, 4),)), ("x2",))
      assert bars(row("[*x2] [*|] [Am] [C] [G] [*|] [A] [B] [C] [D] [E]")) == Bars(
          ("x2",), (((0, 2), (1, 1), (2, 1)), ((3, 1), (4, 1), (1, 1), (5, 1), (6, 1))), ())
      assert bars(row("[Am] [*|] [*N.C.] [*|] [E]")) == Bars((), (((0, 4),), (("N.C.", 4),), ((1, 4),)), ())

  def test_a_line_with_no_bar_or_no_chord_has_no_bars():
      assert bars(row("[G] [D] [*x2]")) is None
      assert bars(row("[*|] [*N.C.] [*|]")) is None
  ```
  `tests/test_viewer.py`, where `BARS` is `"{title: T}\n{artist: A}\n{comment: Intro}\n[Am] [C] [*|] [G] [*|] [*x2]\n"`
  followed by `"[G] [D]\n{comment: Verse}\n[Am]la [G]lo\n"`:
  ```python
  @pytest.mark.parametrize("built", [
      lambda: build_viewer(BARS), lambda: build_viewer(BARS, export=False),  # a sheet, a kept version's page
      lambda: build_songbook("Campfire", [BookSong("T", "A", cho=BARS, id="aaaa")])])
  def test_a_line_that_writes_bars_is_a_row_of_bar_cells(built):
      html = built()
      chord = lambda i, name: f'<b class="c" data-c="{i}" tabindex="0" role="button">{name}</b>'
      beat = '<span class="beat" aria-hidden="true">·</span>'
      assert (f'<p class="l chords bars"><span class="barcell">{chord(0, "Am")}{beat}{chord(1, "C")}{beat}</span>'
              f'<span class="barcell">{chord(2, "G")}{beat * 3}</span><i class="m">x2</i></p>') in html
      assert f'<p class="l chords">{chord(2, "G")} {chord(3, "D")}</p>' in html  # no bars: as today

  def test_a_bar_line_is_still_a_line_of_the_song_for_the_pinyin_after_it():
      html = build_viewer("{title: 月亮}\n{artist: A}\n{comment: Intro}\n[C] [*|] [G] [*|]\n{comment: Verse}\n[C]月亮代表[G]我的心\n")
      lines = re.findall(r'<p class="l[ "]', sheet_of(html))
      assert len(data_of(html)["pinyin"]) == len(lines) == 2 and data_of(html)["pinyin"][1]
  ```
  `tests/test_viewer_lines.py` (new; `pytestmark = CHROMIUM_MARKS`; `viewer` and `written` from helpers/viewer_pages.py),
  with `INTRO` set to a Greensleeves sheet:
  `{comment: Intro}` then `[Am] [C] [*|] [G] [Em] [*|] [Am] [*|] [E] [*|]`, then a verse whose first line is
  `[Am]Alas, my [C]love, you [G]do me [Em]wrong,`, then `{comment: Outro}` and `[Am] [E] [Am]`.
  - `test_an_intro_written_in_bars_is_a_row_of_bar_cells_with_its_beats`:
    - At 390×844 the cells read `[(["Am", "C"], 2), (["G", "Em"], 2), (["Am"], 3), (["E"], 3)]` (each cell's `.c`
      texts and its count of `.beat`), and all four share one top.
    - The Outro's line is `.l.chords:not(.bars)`.
    - At 320×640, `scrollWidth <= clientWidth`, and each cell's chords share that cell's top.
  - `test_a_bar_cells_chords_transpose_and_open_their_card`:
    - After `#t-up`, the four first cell chords' texts equal the sung line's four chords' texts.
    - `tap(b, "#sheet .l.bars .c")` opens `#card`.

  `SheetsTest.kt`, `aLineOfChordsThatWritesBarsReadsAsBars`: the first and third cases above, as `Sheets.bars`.
  `SheetPageTest.kt`, `aSungLineSetsEachChordOverItsSyllable`: its `ChordRow(listOf(Item.Chord(0), Item.Mark("|")))`
  is now a bar line, so expect `<p class="l chords bars"><span class="barcell">…G…` followed by three beats and
  `</span></p>`.
- [ ] **Step 2: Run them and see them fail**: `nix develop -c pytest -q tests/test_viewer_sheet.py tests/test_viewer.py
  tests/test_viewer_lines.py -k "bar"`. Expect an ImportError on `Bars`/`bars`, then `<i class="m">|</i>` where the
  cells should be.
- [ ] **Step 3: Implement**
  - sheet.py: `BEATS`, `Bars` and `bars` by the rule above.
  - page.py: `_line_html`'s `ChordRow` branch returns `_bars_html(found, names)` when the line is no legend and
    `bars(line)` is not None, and today's markup otherwise. `_line_html`'s docstring names the bar cells.
  - viewer.css, after `.l.chords .m`, with a comment that says what it draws, as the rules around it do:
    - `.l.bars`: `display: flex; flex-wrap: wrap`. The row wraps between cells and never inside one.
    - `.barcell`: `display: inline-flex; flex: 1 0 auto; min-width: 4.5em; align-items: baseline; gap: .45em;
      padding: 0 .5em`, with a 2 px bar line in `--border-strong` either side (adjacent cells share theirs).
    - `.l.bars .c { margin-right: 0 }`.
    - `.beat`: `color: var(--muted); font-weight: 400; user-select: none`.
    - Exact sizes are the builder's, within the test: four cells in a 358 px row at 18 px.
  - `__init__.py`: "sheet.py reads that file back, and a line of chords' bars (`bars`)".
  - viewer_corpus.py: append to `EDGE_SHEETS` a sheet holding the test's cases. Its lines are
    `[*|:] [Am] [*|] [*|] [E] [*:|] [*x2]`, `[*x2] [*|] [Am] [C] [G] [*|] [A] [B] [C] [D] [E]`,
    `[Am] [*|] [*N.C.] [*|] [E]` and `[*|] [*N.C.] [*|]`.
  - test_conformance_viewer_sheet.py:
    - `"BEATS": sheet.BEATS` in `sheet`'s member.
    - `read_of` records `"bars"` (Interfaces), and its docstring names it.
  - Kotlin: `Sheets.bars`, with `BEATS` read as `SheetData.sheet.int("BEATS")`; `PageHtml.barsHtml`; `lineHtml`'s
    `ChordRow` branch, as in Python; `SheetReplay.readOf` adds `check("bars")`.
  - docs/usage.md, a bullet after "Chords over the lyrics": "**Bars**: an intro or a riff the tab writes in bars ("Am
    C | G Em |") is a row of bar cells, each with its chords and a dot for each beat after a chord's first. A bar has
    four beats, shared evenly. A line of chords without bars is spaced evenly, as before. The PDF prints it as
    written."
  - AGENTS.md, under viewer/'s rules: "**A sheet's lines** (page.py `_line_html`): a chord-only line that writes bars
    (`sheet.BAR`) is a row of `span.barcell`s, each chord's beats from `sheet.bars` (`BEATS` a bar, shared evenly). It
    is still one `p.l.chords`, so the data's `pinyin` keeps its lines."
- [ ] **Step 4: Run them and see them pass**: the Step 2 command, then
  `nix develop -c pytest -q tests/test_viewer*.py tests/test_conformance_viewer_*.py`. Regenerate the corpus (5c.1's
  command, run twice), then run gradle's `test`. `SheetReplay` (area sheet) and `PagesReplay` (area pages) must pass
  with the Kotlin above.
- [ ] **Step 5: Commit**: `git add src/caracole/viewer tests/test_viewer_sheet.py tests/test_viewer.py tests/test_viewer_lines.py
  tests/helpers/viewer_corpus.py tests/test_conformance_viewer_sheet.py tests/conformance android/viewer docs/usage.md
  AGENTS.md`, then `feat(viewer): a line of chords that writes bars is a row of bar cells with its beats`.

#### Task 5c.3: A word with a chord inside it wraps whole

**Files:**
- Modify: `src/caracole/viewer/page.py`: `_line_html`'s `Lyrics` branch, and a new `_glued`.
- Modify: `src/caracole/viewer/viewer.css`: `.word`; the comment above `.s`; the pinyin rules' child selectors.
- Modify: `src/caracole/viewer/viewer.js`: `fit()`.
- Modify: `android/…/viewer/pages/internal/PageHtml.kt`: `lineHtml`, and a new `glued`.
- Modify: `tests/helpers/viewer_corpus.py`: one more `EDGE_SHEETS` entry.
- Modify: `tests/test_viewer_text_size.py`: `LAID_OUT`'s selector and `SONG`.
- Modify: `docs/usage.md` ("Chords over the lyrics") and `AGENTS.md` (5c.2's bullet).
- Test: `tests/test_viewer.py`, `tests/test_viewer_lines.py`, `android/…/viewer/pages/SheetPageTest.kt`.

**Interfaces:**
- Consumes: nothing from 5c.1–5c.2, beyond living in the same `_line_html`.
- Produces:
  - `page._glued(before: str, after: str) -> bool`: whether a chord between two texts sits inside a word. That is,
    both are non-empty, and `_words` would cut neither at the end of `before` nor at the start of `after` (no space
    and no wide character on either side).
  - Markup: a run of columns (`span.s`, `span.w`) that one word spans is wrapped in `<span class="word">…</span>` inside
    its `p.l`. That holds where a part's head is glued to the previous part's text, chain and all
    ("[C]a[G]la[D]bama"). Other columns are as today.
  - A line's columns are `p.l .s, p.l .w`, nested or not, in document order. `fit()` and the pinyin units read them
    so, and no rule or script may read them as a line's children.
  - Kotlin: `PageHtml.glued(before: String, after: String): Boolean`, in code points.

- [ ] **Step 1: Write the failing tests**

  `tests/test_viewer.py`:
  ```python
  def test_a_word_with_a_chord_inside_it_is_one_group_of_columns():
      sheet = sheet_of(build_viewer("{title: T}\n{artist: A}\n[Am]To cast me off dis[E]courteously, [C]a[G]la[D]bama\n"))
      c = lambda i, name: f'<b class="c" data-c="{i}" tabindex="0" role="button">{name}</b>'
      assert (f'<span class="word"><span class="w">dis</span><span class="s">{c(1, "E")}'
              '<span class="y">courteously, </span></span></span>') in sheet
      assert (f'<span class="word"><span class="s">{c(2, "C")}<span class="y">a</span></span><span class="s">{c(3, "G")}'
              f'<span class="y">la</span></span><span class="s">{c(4, "D")}<span class="y">bama</span></span></span>') in sheet
      assert sheet.count('class="word"') == 2

  def test_a_chord_beside_a_chinese_character_glues_nothing():
      zh = to_chordpro((FIXTURES / "zh_sheet.txt").read_text(encoding="utf-8"), title="斑马斑马", artist="宋冬野")
      assert 'class="word"' not in sheet_of(build_viewer(zh))
  ```
  `tests/test_viewer_lines.py`:
  - `test_a_chord_inside_a_word_never_parts_the_word_across_rows`: `[Am]To cast me [E]off dis[E7]courteously` at
    390×844 with `#fs=30`. The `.w` "dis" and the `.s` whose `.y` is "courteously" share a bottom and touch
    (`dis.right ≈ s.left`, ±1 px). "dis" starts its row (its left is the line's, ±1). The line wraps (its height is
    at least twice the column's). There is no sideways scroll.
  - `test_a_word_longer_than_the_line_wraps_inside_its_group_rather_than_widen_the_page`:
    `[G]Supercalifragilistic[D]expialidocious` at 320×640 with `#fs=30`: `scrollWidth <= clientWidth`.

  `tests/test_viewer_text_size.py`: `LAID_OUT` iterates `line.querySelectorAll('.s')`, and its `:scope > .c` and
  `:scope > .y` stay. `SONG` gains a line `[G]Ala[D]bama dis[E]courteously`, so a group's chords are checked in text
  drawn larger too.

  `SheetPageTest.kt`, `aWordWithAChordInsideItWrapsWhole`: the first `test_viewer` case, through
  `SheetPage.sectionHtml`.
- [ ] **Step 2: Run them and see them fail**: `nix develop -c pytest -q tests/test_viewer.py tests/test_viewer_lines.py
  -k "word or chinese_character"`. Expect no `span.word`, and "dis" ending row 1 with "courteously" on row 2.
- [ ] **Step 3: Implement**
  - page.py: the `Lyrics` branch builds its columns as today, each column with whether it is glued to the one before
    it: a part's first column is glued when `_glued(previous part's text, this part's text)`. Then it wraps each
    maximal run of glued columns, with the column it is glued to, in `span.word`.
  - viewer.css: `.word { display: inline-flex; flex-wrap: wrap; align-items: flex-end; max-width: 100%;
    vertical-align: bottom; }`. A group goes to the next row whole, and wraps inside itself only when it is wider
    than the line. Rewrite `.l.py > .s > .y::before`, `.l.py > .w::before`, `.l.py > .w > ruby.py > rt` and
    `.l.py > .s > .y > ruby.py > rt` with `.l.py .s` and `.l.py .w` in place of `.l.py > .s` and `.l.py > .w`. The
    comment above `.s` gains: "a word a chord falls inside is one group of its columns (.word), so a row breaks before
    the word, never inside it".
  - viewer.js `fit()`: `const kids = Array.from(line.querySelectorAll(".s, .w"))` in place of `line.children`, and
    the rest as it is.
  - Kotlin `lineHtml` and `glued`, the same.
  - viewer_corpus.py: append an edge sheet whose line is `Ala[C]bama dis[E]courteously [C]a[G]la[D]bama wo[G][D]rd
    我[C]们 in[*x2]side`, so the corpus holds a head-less part glued, a chain, two chords with no text between them
    (not glued), Chinese and a glued mark.
  - docs/usage.md, in "Chords over the lyrics": "A word with a chord inside it ("dis·courteously") wraps whole, onto
    the next row." AGENTS.md: 5c.2's bullet gains "a word a chord falls inside is one `span.word`, which wraps whole;
    a line's columns are `p.l .s, p.l .w`, nested or not".
- [ ] **Step 4: Run them and see them pass**: the Step 2 command, then `nix develop -c pytest -q tests/test_viewer*.py`.
  test_viewer_pinyin.py and test_viewer_text_size.py must pass unchanged but for the selector above. Regenerate the
  corpus, then run gradle's `test` (`PagesReplay`, `SongbookPageTest`, `RenderReplay`).
- [ ] **Step 5: Commit**: `git add src/caracole/viewer tests/test_viewer.py tests/test_viewer_lines.py
  tests/test_viewer_text_size.py tests/helpers/viewer_corpus.py tests/conformance android/viewer docs/usage.md AGENTS.md`,
  then `fix(viewer): a word with a chord inside it wraps whole`.

#### Task 5c.4: More space between sung lines than within one

**Files:**
- Modify: `src/caracole/viewer/viewer.css`: the `.l + .l` rule.
- Modify: `docs/usage.md` ("Chords over the lyrics").
- Test: `tests/test_viewer_lines.py`.

**Interfaces:**
- Consumes: the columns as 5c.3 leaves them (`p.l .s, p.l .w`), which the test measures.
- Produces: `.sheet:not(.harp-tab) .l + .l { margin-top: .4em; }`. The harmonica tab's page keeps `.l + .l`'s
  `.12em`, because the design gives it no line rule. `.gap` (between stanzas) stays `.65em`.

- [ ] **Step 1: Write the failing test**

  `tests/test_viewer_lines.py`, with `HARD_TIMES`, the design's song: `{key: D}`, `{comment: Verse 1}`,
  `[D]Let us pause in [G]life's pleasures and [D]count its many [A]tears,`, then
  `[D]While we [D]all sup sor[G]row with the [D]poor;`. Its `ROWS` script groups each `section.sec > p.l`'s columns
  into rows by their bottom (±2 px), each row with its top, bottom and first column's left, plus the line's left and
  font size.
  ```python
  @pytest.mark.parametrize("where", ["sheet", "songbook"])
  def test_a_wrapped_tail_starts_flush_left_closer_to_its_line_than_the_next_line_is(tmp_path, where):
      ...  # the sheet, or a songbook of it at #song-1, at 390×844
      first, second = b.js(ROWS)[:2]
      assert len(first["rows"]) >= 2  # it wraps at 390 px
      assert first["rows"][1]["top"] - first["rows"][0]["bottom"] <= 1  # a line's rows touch
      assert abs(second["rows"][0]["top"] - first["rows"][-1]["bottom"] - 0.4 * first["fs"]) <= 1
      assert all(abs(r["left"] - first["left"]) <= 1 for r in first["rows"])  # no hanging indent
  ```
  `test_with_pinyin_too_a_lines_rows_touch_and_lines_stand_apart`: the same three assertions on test_viewer_pinyin.py's
  `LONG` at `#py=1`, waiting for `ruby.py` first.

  `test_a_harmonica_tabs_rows_keep_their_spacing`: on test_viewer_harptab_browser.py's `written(tmp_path,
  tab("124_heart-of-gold"))`, the first `.harp-tab .l + .l` has a computed `margin-top` of 0.12 (±0.01) times its
  font size.
- [ ] **Step 2: Run it and see it fail**: `nix develop -c pytest -q tests/test_viewer_lines.py -k "wrapped or pinyin_too or
  harmonica"`. Expect a gap of 2.2 px (0.12 em) where 7.2 px is due. The harmonica test passes already.
- [ ] **Step 3: Implement**: add the rule above, after `.l + .l`, with the comment "a sung line's wrapped rows sit together,
  and the next line stands apart by more (D3): its tail never reads as a line of its own".
  docs/usage.md, in "Chords over the lyrics": "A long line's wrapped rows sit close together, starting at the left
  edge, with more space before the next sung line."
- [ ] **Step 4: Run it and see it pass**: the Step 2 command, then `nix develop -c pytest -q tests/test_viewer*.py`.
  Regenerate the corpus (every page inlines viewer.css, so the page, harmonica page and render vectors move), then run
  gradle's `test`. No Kotlin code changes, because the assets are copied byte for byte.
- [ ] **Step 5: Commit**: `git add src/caracole/viewer/viewer.css tests/test_viewer_lines.py tests/conformance docs/usage.md`,
  then `feat(viewer): more space between sung lines than between a line's rows`.

#### Task 5c.5: The song's end clears the bar and comes up half a screen

**Files:**
- Modify: `src/caracole/viewer/viewer.css`: `.page`'s padding, `html[data-dock] .page`, a new `.page::after`, and the
  `@media print` block.
- Modify: `docs/usage.md` (the viewer's bar section) and `AGENTS.md` (viewer/'s rules).
- Test: `tests/test_viewer_bar.py`, `tests/test_viewer_print.py`.

**Interfaces:**
- Consumes: `--foot` and `--pill` as 5a and 5b leave them; the bar hidden in full screen (5a).
- Produces:
  - `.page`'s `padding-bottom` is `calc(var(--foot) + 19px + var(--pill))`, today's 72 px and inset, now following
    the bar's height. `html[data-dock] .page` is the same plus `var(--dock)`.
  - `.page::after { content: ""; display: block; height: 50vh; }` is the over-scroll, and it is `content: none` in
    print.
  - `layout()` reads `.page`'s padding as the bar's room: the over-scroll is never in it, and 5c.6 relies on that.

- [ ] **Step 1: Write the failing tests**

  `tests/test_viewer_bar.py`:
  ```python
  @in_chromium
  @pytest.mark.parametrize("kind", KINDS)  # from test_viewer_print: sheet, songbook, harmonica
  def test_the_songs_end_comes_up_half_a_screen_clear_of_the_bar(tmp_path, kind):
      url, fragment = _written(tmp_path, kind)  # test_viewer_print's
      for width, height, mobile in ((390, 844, True), (844, 390, True), (1280, 800, False)):  # a phone, on its side, a laptop
          with viewer(tmp_path, url + fragment, width=width, height=height, mobile=mobile) as b:
              m = b.js("""(() => { scrollTo(0, document.documentElement.scrollHeight);
                const last = [...document.querySelectorAll('.foot > *')].filter((e) => e.getClientRects().length).pop()
                  .getBoundingClientRect();
                const bar = document.querySelector('#bar'), r = bar.getBoundingClientRect();
                const floor = bar.hidden || !r.height || bar.classList.contains('away') ? innerHeight : r.top;
                return {room: floor - last.bottom, half: innerHeight / 2}; })()""")
          assert m["room"] >= m["half"] - 1, (kind, width, m)
  ```
  The floor is the window's foot where the bar doesn't show (5a's full screen, or a phone on its side).

  `tests/test_viewer_print.py`, `test_the_over_scroll_is_left_off_the_paper` (for each of `KINDS`): with print media
  emulated as `_seen` does, `getComputedStyle(document.querySelector('.page'), '::after').content === 'none'`. On the
  screen it is `'""'`.
- [ ] **Step 2: Run them and see them fail**: `nix develop -c pytest -q tests/test_viewer_bar.py tests/test_viewer_print.py
  -k "half_a_screen or over_scroll"`. Expect a room of about 19 px against a half of 422.
- [ ] **Step 3: Implement**
  - viewer.css, per Interfaces. The comment over `.page` becomes: "room for the bar (--foot: its height and the
    screen's safe area) and a little more, and the pill's while it shows; then half a screen past the song's end
    (::after), so its last lines can come up to the middle of the screen. Never in the padding: layout() reads that as
    the bar's room".
  - docs/usage.md, in the bar's paragraph: "At the song's end the page scrolls on half a screen more, so its last lines
    come up clear of the bar, to the middle of the screen."
  - AGENTS.md, under viewer/'s rules: "**The song's end**: `.page`'s padding is the bar's room (`--foot`), which
    `layout()` measures two columns against; the half screen of over-scroll is `.page::after`, never in it."
- [ ] **Step 4: Run them and see them pass**: the Step 2 command, then `nix develop -c pytest -q tests/test_viewer_bar.py
  tests/test_viewer_layout.py tests/test_viewer_scroll.py tests/test_viewer_book.py`. The two-column tests must hold
  unchanged. Regenerate the corpus, then run gradle's `test`.
- [ ] **Step 5: Commit**: `git add src/caracole/viewer/viewer.css tests/test_viewer_bar.py tests/test_viewer_print.py tests/conformance
  docs/usage.md AGENTS.md`, then `fix(viewer): the song's end clears the bar and comes up half a screen`.

#### Task 5c.6: Two columns stepped down before one column

**Files:**
- Modify: `src/caracole/viewer/viewer.js`: `layout()`, and a new `COLUMN_SIZES` beside `FS`.
- Modify: `src/caracole/viewer/viewer.css`: the `@media (min-width: 1100px)` block.
- Modify: `docs/usage.md` ("On a wide screen") and `AGENTS.md` (5c.5's bullet).
- Test: `tests/test_viewer_layout.py`.

**Interfaces:**
- Consumes: the over-scroll outside `.page`'s padding (5c.5).
- Produces:
  - `const COLUMN_SIZES = [3, 2, 1, 0]`, the pixels above the text size at which two columns are tried, in order. The
    one column stays at `--fs` + 3 px.
  - viewer.js sets the custom property `--cols-fs` on `<html>` to the size being tried, and removes it when the song
    reads in one column.
  - viewer.css: `[data-columns="2"] .sheet { columns: 2 28em; column-gap: 56px; font-size: var(--cols-fs, var(--fs)); }`.

- [ ] **Step 1: Write the failing tests** in `tests/test_viewer_layout.py`.
  - `test_two_columns_take_the_largest_size_that_fits_from_the_one_columns_down`: `TINY` at `DESKTOP`, and at
    1199×800. Both give two columns (`right > 0`) at `font == 19`. Today's code gives 18. The page gives its columns
    1148 px (1180 less its padding): two of 28em fit at 19 px (1120 px with the gap) and not at 20 px (1176 px).
  - `test_a_window_too_low_for_larger_two_columns_steps_them_down_before_one_column`. Open `SHORT` at `DESKTOP`: two
    columns at 19.
    - Read the sheet's height (`h19`) and `.page`'s `paddingBottom` (`pad`).
    - Set `--cols-fs` to `18px` by hand and read `h18`. Assert `h19 - h18 > 4`, so the window below has room to fall
      between them.
    - With `resize`, make the window's `innerHeight` `pad + (h18 + h19) / 2`: resize, read `innerHeight`, then
      resize again by the difference. Wait for two columns at 18 px.
    - Make it `pad + h18 - 20`, and wait for one column (`right === 0`) at 21 px.
  - The existing tests stay as they are. `test_the_columns_follow_the_window_and_the_text_size`'s A+ (20 px) tries 23
    to 20 and gets one column. `test_the_settings_rail…` compares the two fonts, both 19.
- [ ] **Step 2: Run them and see them fail**: `nix develop -c pytest -q tests/test_viewer_layout.py -k "largest or steps"`.
  Expect `font == 18`.
- [ ] **Step 3: Implement**: `layout()` keeps its first branch, where two columns aren't offered: `data-columns` "1",
  `--cols-fs` removed. Otherwise, for each offset of `COLUMN_SIZES`, it sets `--cols-fs` to `state.fs + offset`,
  runs `fit()`, and keeps the first size whose end lies in the right half with a height within the room. The room
  is `innerHeight` less `.page`'s padding, as today. If no size fits, the song reads in one column at the larger
  size. The scroll position is restored once, at the end, as today. The comment over `layout()` says the steps and
  why they stop at the text size: the reader's own size is never undercut.
  - docs/usage.md, "On a wide screen": "A song is tried in two columns from the one column's size down to your text
    size, a pixel at a time, and the largest at which the window shows it whole is used; else one column."
  - AGENTS.md, 5c.5's bullet gains: "two columns are tried at `COLUMN_SIZES` above `--fs` (`--cols-fs`), the first
    that shows the song whole".
- [ ] **Step 4: Run them and see them pass**: the Step 2 command, then `nix develop -c pytest -q tests/test_viewer_layout.py
  tests/test_viewer_preamble.py tests/test_viewer_necks.py`. Regenerate the corpus, then run gradle's `test`.
- [ ] **Step 5: Commit**: `git add src/caracole/viewer tests/test_viewer_layout.py tests/conformance docs/usage.md AGENTS.md`,
  then `feat(viewer): two columns tried from the one column's size down to the text size`.

#### Task 5c.7: Merge stage 5c

**Files:** none new. This task checks the branch whole and merges it.

**Interfaces:**
- Consumes: 5c.1–5c.6 on `feat/sheet-5c-lines`.
- Produces: `main` with 5c, from which 5d's branch starts.

- [ ] **Step 1: Look at it on screen**: `caracole serve` on a copy of a library with a bar intro, a long-lined song and a
  Chinese song, at 390, 320, 844×390 and 1280×800, and in the Android app (`android/scripts/device-test.sh --app`).
  Check that the cells, a word with a chord inside it, the line spacing, the end's room and two columns look right.
  Note anything for the owner.
- [ ] **Step 2: Run every check**: `nix develop -c pytest -q`; `nix develop -c pytest -q tests/test_conformance_*.py`
  (the committed corpus, checked); `nix develop ./android -c gradle -p android test`; `nix flake check`; and, since
  the corpus moved, `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py`. Expect all
  green.
- [ ] **Step 3: Fix what failed**, with its own test, in its own commit, then Step 2 again.
- [ ] **Step 4: Merge**: in the checkout that has `main` checked out (`git worktree list` shows which), run
  `git merge --no-ff feat/sheet-5c-lines`.
- [ ] **Step 5: Push**: from the same checkout, `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.
  Then restart the laptop's service so the next run renders every page again, and the `.cho` of every sheet with a
  bar line (the viewer's build version moved).

---

### Stage 5d: the bar and panels

D9 C (a scroll arrow, a word under every bar button), D10 C (the key says what changed; the key list), D11 A (the
duplicated switches once each, Mode's chips kept), D12 B (Harmony as the overlay's third tab), D13 C (the laptop's
toolbar), and 48 px targets under `pointer: coarse` with the corners reaching the screen's edge.

**Where it applies** (the design's "Where it applies"; the bar, the settings and the overlay are one code for the sheet,
a kept version's page and a songbook song: page.py's `_CONTROLS`, viewer.js, viewer.css, overlay.js):

| | sheet.html, version-<tab>.html | a songbook song | harmonica-N.html |
|---|---|---|---|
| D11 one control each | yes | yes | its bar's toggle moves after the harp |
| D9 words, scroll arrow | yes | yes | yes ("Shapes", "Notes", "Text", "Scroll") |
| D10 key's word, key list | yes | yes | no: the harp −/+ and its "why" stay |
| D12 Harmony tab | yes | yes | no |
| D13 toolbar | yes | yes, under the shown song's header | yes |
| 48 px, corners | yes | yes | yes |

The songbook's "Where it applies" doesn't name the bar; it shares `_CONTROLS` and viewer.js, so it gets the bar as a
sheet does (the version line and icons are 5b's, which it has none of).

#### Before 5d.1: the branch, and what 5a and 5b left

- Once 5a and 5b are on `main`: `git -C /home/dani/Projects/caracole-lane5 switch -c feat/sheet-5d-bar main`. Every
  path and command below runs in `/home/dani/Projects/caracole-lane5`.
- Read what this stage consumes, under the names 5a and 5b gave them:
  - **5a's layer helper**: viewer.js's `open(which, opener)` / `close(which)` (or what 5a renamed them to), each layer
    one history entry while open, Back, Escape or ✕ closing the top one, one layer at a time below 900 px; the list of
    layers `restack()` walks; full screen's state on `<html>` and its handle at the foot; "Hide controls" in More.
  - **5b's header**: the song's `<header class="head">` (page.py `_body`, book.py `_song`, harptab_page.py `_header`):
    the title block, the facts lines, the version line. This stage only places the toolbar after it.
  - If 5c merged first: how it writes the page's room at its foot (`.page`'s `padding-bottom`). If 5e merged first:
    the strip's switch (D7) is still `#strip-toggle`; 5d.1 keeps it.
- Running the corpus and the phone, the same in every task below (call it **the corpus step**):
  ```
  CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py   # twice: one file reads another's
  CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py
  nix develop -c pytest -q -n 0 tests/test_conformance_viewer_pages.py tests/test_conformance_viewer_harmonica.py \
    tests/test_conformance_viewer_render.py          # passes as checked, no write
  nix develop ./android -c gradle -p android :viewer:test
  ```
  `git status tests/conformance` then shows only the viewer's (`data/caracole/viewer/page.json`, `harmonica_page.json`,
  `vectors/viewer/pages*.jsonl`, `page_whole.json`, `harmonica_pages*.jsonl`, `render.jsonl`) and any
  `vectors/songbook/` record of a songbook page's bytes changed; anything else moving is a mistake. No Kotlin code
  moves in any task but 5d.5: the bar's markup is page.json's and harmonica_page.json's data, and `:viewer` copies the
  `.js` and `.css` byte for byte.

#### Task 5d.1: One control each for the rail of necks and the strip of shapes (D11)

The research's duplicates: the bar's guitar and the settings' **All chord shapes** both show the strip; the bar's
sidebar button and the settings' **Chord necks** both show the rail. The phone's bar in every mockup (D9 C, D10, D12 B)
has five controls, key, "▭ Shapes", Aa, Scroll, More: "Shapes" is the necks' button. So the strip keeps its switch in
⋯ (which 5e's D7 makes the strip's switch), the rail keeps the bar's button and its own Hide, and the guitar and the
Chord necks row go. Mode keeps its chips (D11 A).

**Files:**
- Modify: `src/caracole/viewer/page.py` (`_CONTROLS`: the `#shapes` button out; `#necks-toggle` moved from the bar's
  start to right after the `#keys` group, before `#necks-open`; `<div id="necks-row" hidden>…</div>` out of the
  settings; the comment above `_CONTROLS`)
- Modify: `src/caracole/viewer/viewer.js` (`shapesButton`: its const, its click listener, `render()`'s
  `shapesButton.setAttribute("aria-pressed", …)`, the closing `shapesButton.hidden = count === 0`; `necksChip`: its
  const, `drawNecks()`'s `necks-row` branch, its listener; the comments that name either)
- Modify: `src/caracole/viewer/viewer.css` (`.bar .shapes …` rules and the guitar in the pressed list; the
  `max-width: 439px` rule; `.bar .necks-toggle` gets `.necks-open`'s `margin-left: auto`, the tools after either at 0)
- Modify: `src/caracole/viewer/harptab_page.py` (`_BAR`: `#necks-toggle` after the `#harps` group; `_BAR_RAW` cut from
  `<span class="keys"` to `<button type="button" class="tool necks-toggle"`, and `#notes` as today; the comment above)
- Modify: `docs/usage.md` (**The bar**: no guitar, the strip is ⋯'s All chord shapes on every screen; **Showing and
  hiding it**: the rail's Hide and the bar's button, no Chord necks switch; **On a phone or a tablet**: drop "the neck
  takes the guitar's place"), `AGENTS.md` (viewer/'s "Below 1200 px" bullet: drop the guitar's place and "Chord
  necks"; "The necks": "with its Hide and the bar's button in step")
- Test: `tests/test_viewer_bar.py`, `tests/test_viewer_necks.py`, `tests/test_viewer_panels.py`,
  `tests/test_viewer_hanzi.py`, `tests/test_viewer_harptab_page.py`

**Interfaces:**
- Produces: the bar in DOM order `#keys` (`#t-down`, `#key-now`, `#t-up`), `#necks-toggle`, `#necks-open`, `#size-box`,
  `#scroll`, `#more` (sheet, version, songbook); `#harps` (`#h-down`, `#harp-now`, `#h-up`), `#necks-toggle`,
  `#necks-open`, `#notes`, `#size-box`, `#scroll` (harmonica). The strip's one control `#strip-toggle`; the rail's two,
  `#necks-toggle` and the rail's `.nk-hide`. 5d.2 and 5d.6 rely on this order.

- [ ] **Step 1: Write the failing tests**

  In `tests/test_viewer_bar.py`:
  ```python
  def test_the_bar_is_on_the_page_hidden_until_the_script_runs():  # its id list rewritten
      ...
      assert re.findall(r'<button type="button"[^>]*id="([^"]+)"[^>]*aria-label="([^"]*)"', controls) == [
          ("t-down", "Down a semitone"), ("t-up", "Up a semitone"), ("necks-toggle", "Chord necks"),
          ("necks-open", "Necks and harps"), ("size", "Text size"), ("smaller", "Smaller text"),
          ("bigger", "Bigger text"), ("scroll", "Auto-scroll"), ("more", "Settings")]
      assert 'id="shapes"' not in html  # the strip's one switch is the settings' All chord shapes
      assert 'id="strip-toggle"' in panel and 'id="necks-chip"' not in html and 'id="necks-row"' not in html
  ```
  - `test_the_bar_fits_a_phone_and_a_desktop_and_the_song_ends_above_it`: `tools = ["t-down", "t-up", "necks-toggle"]
    if width >= 1200 else ["t-down", "t-up", "necks-open"]`, then `+ ["size", "scroll", "more"]` at every width.
  - `test_the_keyboard_reaches_every_control_even_when_the_bar_is_away`:
    `order == ["t-down", "t-up", "necks-toggle", "size", "scroll", "more"]`.
  - Delete `test_the_guitar_shows_the_chord_shapes_and_hides_them_again`,
    `test_the_guitar_and_the_settings_chip_stay_in_step_both_ways`,
    `test_the_guitar_brings_the_shapes_into_view_from_anywhere_in_the_song`; rename and move onto ⋯
    `test_the_guitars_choice_is_kept_across_a_reload` → `test_all_chord_shapes_is_kept_across_a_reload` and
    `test_a_songbook_songs_guitar_shows_its_shapes` → `test_a_songbook_songs_all_chord_shapes_shows_them` (`b.click("#more");
    b.click("#strip-toggle")`, same assertions on `strip`, `chip` and the names `["Cm", "Ab", "Bb", "G7"]`); `SHAPES`
    loses `pressed`; `WIDE_PHONE` goes if nothing uses it.

  In `tests/test_viewer_necks.py`: delete `test_the_settings_row_and_the_bars_button_say_the_same_both_ways`; its
  `TOGGLES` loses `chip`, `row` and `said`. In `tests/test_viewer_panels.py`:
  `test_role_colours_all_shapes_necks_and_pinyin_are_switches` → `test_role_colours_all_shapes_and_pinyin_are_switches`
  (no necks member). In `tests/test_viewer_hanzi.py`'s look (line ~494): drop `necks`. In
  `tests/test_viewer_harptab_page.py::test_the_page_has_the_overlays_rail_and_its_bars_button`:
  ```python
  assert re.search(r'<div class="bar-in">\n<span class="keys" id="harps"', html)
  assert re.search(r'</span>\n<button type="button" class="tool necks-toggle" id="necks-toggle" hidden', html)
  ```

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q tests/test_viewer_bar.py tests/test_viewer_harptab_page.py -k "hidden_until or fits or reaches or rail_and_its_bars"`:
  the id lists differ (`("necks-toggle", …)` first, `("shapes", "Chord shapes")` present).

- [ ] **Step 3: Implement** as the Files list says. `drawNecks()` keeps `necksButton` and `sheetButton` in step;
  Reset all still sets `necks: true` and calls `keepNecks()`.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q tests/test_viewer_bar.py tests/test_viewer_necks.py tests/test_viewer_panels.py
  tests/test_viewer_hanzi.py tests/test_viewer_harptab_page.py tests/test_viewer_harptab_browser.py
  tests/test_viewer_instruments_page.py tests/test_viewer_shapes.py`, then the corpus step.

- [ ] **Step 5: Commit**

  `git add src/caracole/viewer/page.py src/caracole/viewer/viewer.js src/caracole/viewer/viewer.css
  src/caracole/viewer/harptab_page.py docs/usage.md AGENTS.md tests/ && git commit -m "feat(viewer): one control each
  for the rail of necks and the strip of shapes"`

#### Task 5d.2: A word under every bar button, and a scroll arrow (D9)

**Files:**
- Modify: `src/caracole/viewer/page.py` (new `_SCROLL_ICON`; `_CONTROLS`' tools: a `<span class="bw">` word each,
  `#scroll`'s ▶ replaced by `<span class="disc">` + `_SCROLL_ICON`, the names below; the comment above `_CONTROLS`)
- Modify: `src/caracole/viewer/harptab_page.py` (`_BAR`: the same words, `#notes` "Notes", `#scroll` with
  `page._SCROLL_ICON`; `_PLAY_ICON` stays the line's ▶)
- Modify: `src/caracole/viewer/viewer.css` (`.bar .tool` icon over word, 54 px tall; `.keys` as tall; `.bw`;
  `.bar .play .disc` carries the accent; `.bar .play[aria-pressed="true"]` lit; `:root --foot: calc(63px +
  env(safe-area-inset-bottom))`; the page's foot room; the comments on the bar)
- Modify: `src/caracole/viewer/harptab.css` (`.bar .notes`: ♪ and its word)
- Modify: `src/caracole/viewer/viewer.js` (`showScroll()`), `src/caracole/viewer/harptab.js` (`showScroll()`)
- Modify: `docs/usage.md` (**The bar**: the words, the arrow, lit while autoscroll is on), `AGENTS.md` ("Below 1200
  px": "▶ leaves it at half" → "Scroll leaves it at half")
- Test: `tests/test_viewer_bar.py`, `tests/test_viewer_panels.py`, `tests/test_viewer_scroll.py`,
  `tests/test_viewer_harptab_page.py`, `tests/test_viewer_harptab_browser.py`, `tests/test_conformance_viewer_harmonica.py`

**Interfaces:**
- Consumes: 5d.1's bar order.
- Produces: `page._SCROLL_ICON`, a downward arrow over a line as a stroked path,
  `'<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v8.5M4.5 7 8 10.5 11.5 7M3.5 13.5h9" fill="none"
  stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'` (the builder may
  redraw it; tests find it by the constant); `.bw`, a bar button's word; `#scroll[aria-pressed]`, `"true"` while
  autoscroll is on (counting, running or paused), `"false"` off; `--foot`, the bar's height with the inset. 5d.6
  restyles `.bw` and `.disc` for the toolbar; 5d.7 widens the tools.

The words: `#necks-toggle` and `#necks-open` "Shapes", `#size` "Text", `#scroll` "Scroll", `#more` "More", the
harmonica page's `#notes` "Notes" (the key's own word is 5d.3's). Each button's name holds its visible word (WCAG 2.5.3):
`#necks-toggle` and `#necks-open` lose their `aria-label`s (named "Shapes", `title="Chord necks"` and
`title="Necks and harps"`), `#more` loses "Settings" (`title="Settings"`), `#notes` loses "Note names"; `#size` keeps
"Text size" and `#scroll` "Auto-scroll". One button as written, the others alike:

```html
<button type="button" class="tool play" id="scroll" aria-label="Auto-scroll" aria-pressed="false"><span class="disc">…_SCROLL_ICON…</span><span class="bw">Scroll</span></button>
```

- [ ] **Step 1: Write the failing tests**

  In `tests/test_viewer_bar.py`:
  ```python
  WORDS = [("necks-toggle", "Shapes"), ("necks-open", "Shapes"), ("size", "Text"), ("scroll", "Scroll"), ("more", "More")]

  def test_the_bar_is_on_the_page_hidden_until_the_script_runs():
      ...  # the buttons named by an aria-label now, the rest by their words
      assert re.findall(r'<button type="button"[^>]*id="([^"]+)"[^>]*aria-label="([^"]*)"', controls) == [
          ("t-down", "Down a semitone"), ("t-up", "Up a semitone"), ("size", "Text size"),
          ("smaller", "Smaller text"), ("bigger", "Bigger text"), ("scroll", "Auto-scroll")]
      assert re.search(r'id="necks-open" hidden title="Necks and harps" aria-haspopup="dialog"', controls)
      for id_, word in WORDS:
          assert re.search(rf'id="{id_}"[^>]*>(?:(?!</button>).)*<span class="bw">{word}</span></button>', controls), id_
      assert page._SCROLL_ICON in controls and "M4.5 2.4v11.2" not in controls  # no ▶ in the bar

  @in_chromium
  def test_every_bar_button_says_its_word_under_its_icon(tmp_path):
      # at (390, 844, True), (320, 640, True), (768, 1024, True), (1100, 800, False): each shown .bar .tool's .bw
      # whole (its text's range no wider than it), its top at or below its icon's bottom, centred on it within 1 px
      ...

  @in_chromium
  def test_the_scroll_button_is_lit_while_autoscroll_is_on(tmp_path):
      with viewer(tmp_path) as b:
          before = b.js("document.getElementById('scroll').getAttribute('aria-pressed')")
          b.click("#scroll")
          counting = b.js("document.getElementById('scroll').getAttribute('aria-pressed')")
          b.click("#go"); b.click("#go")  # started, paused: the bar is back
          paused = b.js("""[document.getElementById('scroll').getAttribute('aria-pressed'),
            getComputedStyle(document.querySelector('#scroll .disc')).boxShadow !== 'none']""")
          b.click("#pill-end")
          after = b.js("document.getElementById('scroll').getAttribute('aria-pressed')")
      assert (before, counting, paused, after) == ("false", "true", ["true", True], "false")
  ```
  - `test_the_bar_fits_a_phone_and_a_desktop_and_the_song_ends_above_it`: `60 <= m["height"] <= 66`, the song's end
    still above it (`clear`), at every width it lists.
  - `tests/test_viewer_panels.py::test_while_the_song_scrolls_by_itself_a_card_docks_on_the_bar_under_the_pill`:
    `alone["pill"]["bottom"] == 844 - 63 - 12`.
  - `tests/test_viewer_scroll.py`: whatever pins the pill's or the foot's place in px against a 53 px bar takes 63.
  - `tests/test_viewer_necks.py`: `TOGGLES`' `named` reads `#necks-toggle`'s `title` (still "Chord necks"), and a
    member `word`, its `.bw` ("Shapes").
  - `tests/test_viewer_harptab_page.py`: a test `test_the_harmonica_bar_says_shapes_notes_text_and_scroll` over `_BAR`
    with `[("necks-toggle", "Shapes"), ("necks-open", "Shapes"), ("notes", "Notes"), ("size", "Text"), ("scroll",
    "Scroll")]`, `page._SCROLL_ICON` once in its bar, `harptab_page._PLAY_ICON` still in each line's ▶.
  - `tests/test_viewer_harptab_browser.py::test_scrolling_by_itself_counts_down_then_scrolls_and_stops`: `#scroll`'s
    `aria-pressed` `"true"` while counting, `"false"` once ended.
  - `tests/test_conformance_viewer_harmonica.py` (line ~158): `data["harptab_page"]["_BAR"].count(page._SCROLL_ICON)
    == 1 and harptab_page._PLAY_ICON not in data["harptab_page"]["_BAR"]`.

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q tests/test_viewer_bar.py -k "hidden_until or word or lit or fits"`: no `bw` span, no
  `_SCROLL_ICON` (AttributeError), the bar 52 px tall.

- [ ] **Step 3: Implement**
  - viewer.css: `.bar .tool { display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 3px; height: 54px; }`, `.keys` 54 px tall, `.bw { font-size: .66rem; font-weight: 600; line-height: 1;
    color: var(--muted); }`, a pressed or open tool's word in the accent; `.bar .play` loses its round accent fill to
    `.bar .play .disc { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background:
    var(--accent); color: var(--on-accent); }`, lit: `.bar .play[aria-pressed="true"] .disc { box-shadow: 0 0 0 2px
    var(--surface), 0 0 0 4px var(--accent); }`; the arrow's path takes `fill: none` against `.bar svg`'s fill.
  - The bar is 10 px taller: `--foot: calc(63px + env(safe-area-inset-bottom))`. The page's foot room follows it:
    `.page { padding-bottom: calc(var(--foot) + 19px + var(--pill)); }` and `html[data-dock] .page` likewise with
    `var(--dock)` (72 px was 53 + 19); if 5c already writes that room from `--foot`, only `--foot` changes.
  - viewer.js and harptab.js `showScroll()`: `$("scroll").setAttribute("aria-pressed", scroll.state === "off" ? "false" : "true")`.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q tests/test_viewer_bar.py tests/test_viewer_panels.py tests/test_viewer_scroll.py
  tests/test_viewer_overlay_sheet.py tests/test_viewer_harptab_page.py tests/test_viewer_harptab_browser.py`, then
  the corpus step.

- [ ] **Step 5: Commit**

  `git add src/caracole/viewer/ docs/usage.md AGENTS.md tests/ && git commit -m "feat(viewer): a word under every
  bar button, and a scroll arrow in place of ▶"`

#### Task 5d.3: The key says what changed, on the bar and in the settings (D10 B)

Today the bar says "Em" over "shapes · capo 2 · +1". The design: "+2" when transposed, "capo 2" when a capo plays it,
"key" when neither; the mockup's second bar ("Greensleeves moved up two semitones": "Am" over "capo 2") counts what
moved the chords shown, not the sound. One rule, below; the settings' Transpose value says the same.

**Files:**
- Modify: `src/caracole/viewer/viewer.js` (new `moved()` and `changes()`; `keyShort()`, `keyLabel()`, `fitKey()`;
  `render()`'s `#shift`; move `wrapT` above `keyShort`)
- Modify: `src/caracole/viewer/page.py` (`_CONTROLS`' `#shift`: `<output id="shift"><span class="k">0</span><span
  class="d" aria-hidden="true"></span></output>`)
- Modify: `src/caracole/viewer/viewer.css` (`.now .d.changed`; `#panel .stepper output` two lines, `.k` and `.d` as
  the bar's)
- Modify: `docs/usage.md` (**The bar**: what's under the key; **The settings**: Transpose shows the key and the same word)
- Test: `tests/test_viewer_bar.py`, `tests/test_viewer_panels.py`, `tests/test_viewer.py`, `tests/test_viewer_reload.py`,
  `tests/test_viewer_songbook_browser.py`, `tests/test_viewer_instruments_page.py`

**Interfaces:**
- Produces (viewer.js): `moved()`, the semitones the chords shown moved from the sheet as written by your hand,
  `takesCapo() ? shift() : state.t` (on an instrument with no capo the sheet's capo is folded in, no move of yours);
  `changes()`, `[capo words] + [move]`: `"capo N"` when `takesCapo() && capoNow() > 0`, `"no capo"` when
  `saysNoCapo() && capoNow() === 0`, then `signed(wrapT(moved()))` when `moved() !== 0`; `keyShort()` returns
  `[key, words, changed]`: `key` is `keyName(shift())` (`"Transpose"` for a sheet with no key), `words` is
  `changes()`, else `["key"]` with a key, else `[]`, `changed` is `moved() !== 0 || (takesCapo() && capoNow() !==
  sheetCapo)`. `.now .d.changed` (the word in the accent, as the mockup's `small.ch`). 5d.4's key list marks
  `mod12(moved())`.

The rule's cases, which the tests pin (bar key, its word, the full line a screen reader hears):

| sheet | address | key | word | full (`#key-full`) |
|---|---|---|---|---|
| UG_CHO (G shapes, capo 2) | | G | capo 2 | G shapes · capo 2 · sounds A |
| WALL (Em, capo 2) | | Em | capo 2 | Em shapes · capo 2 · sounds F#m |
| MINOR (Cm) | | Cm | key | Key Cm |
| MINOR | `#t=3` | D#m | +3 (accent) | Key D#m · +3 |
| MINOR | `#t=2&capo=2` | Cm | capo 2 (accent) | Cm shapes · capo 2 · sounds Dm |
| UG_CHO | `#capo=0` | A | no capo · +2 (accent) | Key A · no capo · +2 |
| UG_CHO | `#mode=mixolydian&t=1` | Ab mixolydian | capo 2 · +1 (accent) | Ab mixolydian shapes · capo 2 · sounds Bb mixolydian · +1 |
| UG_CHO | `#inst=piano` | A | key | Key A |
| NO_KEY (capo 1) | | Transpose | capo 1 | Transpose · capo 1 |

`keyLabel(true)`: with a key, `keyLine("")`'s parts as today, then `signed(wrapT(moved()))` when `moved()` (it was
`signed(state.t)`); with none, `"Transpose"` and the move, then the capo words. The settings' `#shift`: with a key,
`.k` the bar's key and `.d` its word; with none, `.k` `signed(state.t)` and `.d` empty. `fitKey()` writes
`words.join(" · ")`, stacked a word a line where one line has no room (no "shapes" to drop first any more).

- [ ] **Step 1: Write the failing tests**
  - `tests/test_viewer_bar.py::test_the_bar_says_the_key_in_short_and_a_screen_reader_hears_it_whole`: the table
    above as its parameters (ids `capo`, `capo-on-open-shapes`, `no-capo`, `transposed`, `capo-plays-it`, `capo-off`,
    `mode`, `piano`, `no-key`); its regex reads `<span class="d( changed)?" aria-hidden="true">` and asserts the class
    on exactly the rows marked "accent".
  - `test_minus_and_plus_transpose_a_semitone_at_a_time`: `up["sub"] == "capo 2 · +1"`, `down["sub"] == "capo 2 · −1"`.
  - `test_the_bar_fits_a_phone_and_a_desktop_and_the_song_ends_above_it`: `m["said"] == ["capo 2 · +1"]` where one line
    fits it, `["capo 2", "+1"]` where it doesn't (as measured: the builder pins each width it lists).
  - `test_the_key_under_it_is_never_cut_short_by_a_fraction_of_a_pixel`: `seen == ["capo 2", True]` at 360 px.
  - `tests/test_viewer_panels.py`:
    ```python
    @in_chromium
    def test_the_settings_say_the_transposition_as_the_bar_does(tmp_path):
        with viewer(tmp_path, written(tmp_path, MINOR) + "#t=2") as b:  # MINOR as test_viewer_bar.py's
            b.click("#more")
            moved = b.js(SHIFT_SAID)  # ["Dm", "+2"]
            b.click("#capo-up"); b.click("#capo-up")
            capo = b.js(SHIFT_SAID)  # the capo plays it: ["Cm", "capo 2"]
            bar = b.js("[document.querySelector('#key-now .k').textContent, document.querySelector('#key-now .d').textContent]")
        with viewer(tmp_path, written(tmp_path, NO_KEY, name="Riffs") + "#t=2") as b:
            b.click("#more")
            keyless = b.js(SHIFT_SAID)
        assert moved == ["Dm", "+2"] and capo == ["Cm", "capo 2"] and bar == capo and keyless == ["+2", ""]
    ```
    with `SHIFT_SAID = "[...document.getElementById('shift').children].map((e) => e.textContent)"`; `SHIFT` becomes
    `"document.querySelector('#shift .d').textContent"`, and where it expected `"0"` it expects `"key"`
    (`test_transpose_reset_goes_back_to_the_pdfs_transposition`'s `zero`, `test_reset_everything_is_last_and_quiet`'s
    `after[0]`); line ~1273 reads `#shift .d` too (`"+2"`).
  - `tests/test_viewer_reload.py` `SAID` and `tests/test_viewer_songbook_browser.py` `SAID`: `#shift .d` (their
    `"+2"`, `"+4"`, `"+5"` stay; a `"0"` is `"key"`).
  - `tests/test_viewer.py`'s capo test of a keyless sheet (around line 630): its `#key-full` member after `#capo=0` is
    `"Transpose +1 · no capo"` (the chords moved a fret's worth); its `#facts` member is whatever 5b made it.
  - `tests/test_viewer_instruments_page.py::test_on_the_piano_the_capo_is_folded_in_and_the_guitar_gets_it_back`:
    `piano[2].startswith("F#m")` and `"capo" not in piano[2]` hold as they are; check they still do.

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q tests/test_viewer_bar.py tests/test_viewer_panels.py -k "says_the_key or transpose or
  settings_say"`: `"shapes · capo 2"` where `"capo 2"` is expected; `#shift` has no children.

- [ ] **Step 3: Implement** the rule as Interfaces states it, in viewer.js beside `keyShort`. CSS: `.now .d.changed {
  color: var(--accent); font-weight: 700; }`.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q tests/test_viewer_bar.py tests/test_viewer_panels.py tests/test_viewer.py
  tests/test_viewer_reload.py tests/test_viewer_songbook_browser.py tests/test_viewer_instruments_page.py
  tests/test_viewer_versions.py tests/test_web_page_search.py -k "not lacuerda"`, then the corpus step.

- [ ] **Step 5: Commit**

  `git add src/caracole/viewer/ docs/usage.md tests/ && git commit -m "feat(viewer): the key says what changed, on the
  bar and in the settings"`

#### Task 5d.4: The key list: the twelve keys, a tap away (D10 C)

**Files:**
- Modify: `src/caracole/viewer/page.py` (`_CONTROLS`: `#key-now` a button in place of the `<output>`; `_KEY_LIST`,
  appended in `_CONTROLS` right after the `#panel` section; the comments)
- Modify: `src/caracole/viewer/viewer.js` (`keyList`, `drawKeyList()`, `chooseKey(k)`, `#key-now`'s click; `rails` and
  `restack()`'s list and `aria-expanded`; `render()` draws the list while it is open; `keyNow.disabled = !key`)
- Modify: `src/caracole/viewer/viewer.css` (`.bar .now` as a button, off `.bar button`'s 44 px box; `.keys12`)
- Modify: `src/caracole/viewer/book.js` (`busy()`: `"key-list"` beside `"panel"` and `"card"`)
- Modify: `docs/usage.md` (**The bar**: tap the key for the twelve keys)
- Create: `tests/test_viewer_key_list.py`
- Test: `tests/test_viewer_bar.py` (the markup test, the keyboard order)

**Interfaces:**
- Consumes: 5d.3's `moved()`, `keyShort()`; viewer.js's `keyName(s)`, `step(t)`, `wrapT`, `mod12`, `takesCapo()`,
  `sheetCapo`; 5a's layer helper (`open(keyList, keyNow)`, `close(keyList)`: a history entry, Back, Escape and ✕,
  one layer at a time below 900 px).
- Produces: `#key-now`, `<button type="button" class="now" id="key-now" aria-haspopup="dialog" aria-controls="key-list"
  aria-expanded="false">` holding today's `.k`, `.d` and `#key-full` (its name: the full line); `#key-list`, a
  `.sheet-ui.panel.keylist` layer (docked on a phone, the right-hand rail from 900 px, in the settings' and the versions
  list's place, as `rails` holds them); `#key-items > button[data-k]` (k 0–11, `aria-pressed`), the first
  `.key-as` spanning its row. 5d.5 leaves `rails` with the key list in it.

```html
<section class="sheet-ui panel keylist" id="key-list" hidden role="dialog" aria-labelledby="key-list-title">
<header class="ui-head"><h2 id="key-list-title" tabindex="-1">Key</h2>
<button type="button" class="x" data-close aria-label="Close">×</button></header>
<div class="keys12" id="key-items" role="group" aria-labelledby="key-list-title"></div>
</section>
```

The list: `const writtenAt = () => (takesCapo() ? 0 : sheetCapo)`, the shift of the chords as written on this
instrument. Entry k (0–11): `keyName(writtenAt() + k)`, `" · as written"` after the first; `aria-pressed` on
`mod12(moved()) === k`. `chooseKey(k)`: `step(wrapT(state.t + mod12(k - moved() + 6) - 6))` (the nearest way, as Easy
keys moves; the capo stays), then `close(keyList)` and the focus on `#key-now`. viewer.css: `.keys12 { display: grid;
grid-template-columns: repeat(4, 1fr); gap: 6px; }`, `.key-as { grid-column: 1 / -1; }` in the own mode's look
(`.chip.orig`'s edge and fill), the pressed one in the accent's edge (the mockup's `.cur`), each 44 px tall, 48 under
`pointer: coarse`.

- [ ] **Step 1: Write the failing tests** (`tests/test_viewer_key_list.py`, `pytestmark = CHROMIUM_MARKS` but its first
  test, which reads markup; `MINOR`, `UG_CHO`, `NO_KEY` from test_viewer_bar.py; `data_of` from test_viewer.py)

  ```python
  def test_the_key_is_a_button_that_opens_the_key_list():
      for html in (build_viewer(UG_CHO), build_viewer(UG_CHO, export=False)):  # sheet.html and a kept version's page
          assert re.search(r'<button type="button" class="now" id="key-now" aria-haspopup="dialog" '
                           r'aria-controls="key-list" aria-expanded="false">', html)
          assert '<section class="sheet-ui panel keylist" id="key-list" hidden role="dialog"' in html
      # the harmonica page keeps its harp −/+ and no list (test_viewer_harptab_page.py's page and a_song)
      assert 'id="key-list"' not in page(TAB_D, cho=a_song(), key="Am", key_source="tab")

  KEYS = "[...document.querySelectorAll('#key-items button')].map((b) => [b.textContent, b.getAttribute('aria-pressed')])"

  def test_tapping_the_key_opens_the_twelve_keys_as_written_first(tmp_path):
      names = data_of(build_viewer(MINOR))["keyNames"]["aeolian"]  # Cm: tonic 0
      with viewer(tmp_path, written(tmp_path, MINOR)) as b:
          b.click("#key-now")
          shown = b.js(KEYS)
          where = b.js(LOOK)  # the list docked on the bar, the focus on its heading, #key-now aria-expanded "true"
      assert [t for t, _ in shown] == [names[0] + " · as written"] + names[1:]
      assert [p for _, p in shown] == ["true"] + ["false"] * 11
      ...

  def test_a_key_chosen_moves_the_song_there_the_nearest_way_and_the_list_closes(tmp_path):
      # MINOR: entry 4 → #t=4, the bar "+4", the list closed, the focus on #key-now; open again: entry 4 pressed.
      # entry 11 from as written → #t=-1, "−1". UG_CHO: entry 2 → #t=2, "capo 2 · +2", the capo still 2.

  def test_on_the_piano_the_list_starts_at_the_key_the_song_sounds_in(tmp_path):
      # UG_CHO#inst=piano: entry 0 is names[(7 + 2) % 12] + " · as written" (ionian), pressed

  def test_escape_back_and_close_close_it(tmp_path):
      # each closes it, the focus on #key-now; Back is history.back() (5a's entry)

  def test_from_900_px_it_is_a_rail_in_the_settings_place(tmp_path):
      # at 1280×800: its box right == client width, top 0; ⋯ opens the settings in its place

  def test_a_sheet_with_no_key_has_no_list(tmp_path):
      # NO_KEY: #key-now disabled; a click opens nothing

  def test_served_in_its_sandbox_with_no_storage_a_key_chosen_is_kept_by_the_address(tmp_path):
      # test_viewer_necks.served: choose entry 2, reload: #t=2, the bar "+2"

  def test_in_a_songbook_the_arrows_stay_with_the_open_list(tmp_path):
      # a two-song songbook, #song-1: the list open, ArrowRight leaves the song where it is
  ```
  In `tests/test_viewer_bar.py`: the markup test's regex for the key reads the button; the keyboard order test is
  `["t-down", "key-now", "t-up", "necks-toggle", "size", "scroll", "more"]`; the key-in-short test's regex reads
  `<button[^>]*id="key-now"[^>]*>`.

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q tests/test_viewer_key_list.py`: no `id="key-list"`; `#key-now` is an `<output>`.

- [ ] **Step 3: Implement** as above. `restack()` keeps `#key-now`'s `aria-expanded` in step and the list in its
  `top` toggling; Reset all and a render while it is open redraw it.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q tests/test_viewer_key_list.py tests/test_viewer_bar.py tests/test_viewer_panels.py
  tests/test_viewer_songbook_browser.py`, then the corpus step.

- [ ] **Step 5: Commit**

  `git add src/caracole/viewer/ docs/usage.md tests/ && git commit -m "feat(viewer): tap the key for the twelve keys, as
  written first"`

#### Task 5d.5: Harmony, the overlay's third tab (D12 B)

"Guitar | Harmonica | Harmony" in the rail (from 1200 px) and the phone's sheet; the Harmony panel and its settings
row go, and the duplicated scale neck with them: the key's neck heads the Harmony tab (the D12 B mockup: "Am scale",
Scale · Minor pentatonic, then the progressions), and leaves the Guitar tab where there is a Harmony tab. A
progression's ▶ plays as today; leaving the tab stops it, as closing the panel did.

**Files:**
- Modify: `src/caracole/viewer/overlay.js` (`rail()`: `page.harmony` and `page.left`; `tabsOf`, `draw`, `showTab`; the
  header's documentation of `window.caracoleOverlay`)
- Modify: `src/caracole/viewer/viewer.js` (`hasHarmony`; `harmonyPane(pane)` from today's `drawHarmony` and the
  panel's markup; `guitarTab()`'s `key` null where `hasHarmony`; the rail's `harmony` and `left`; `drawPlaying()` reads
  `#progs`; `setBpm()` with the pane not drawn; stops (below); out: the `harmony` const, its `rails` entry, restack's,
  the scroll reveal's `!harmony.hidden`, `close()`'s `which === harmony`, `#harmony-open`'s listener, `more`'s
  `close(harmony)`, render()'s `if (!harmony.hidden) drawHarmony()`, the railWide listener's `drawHarmony()`,
  `drawNames()`'s `harmony-row` line, `setKeyNeck()`'s own focus code)
- Modify: `src/caracole/viewer/page.py` (`_CONTROLS`: the `#harmony` section out; `_HARMONY_ROW` out; `_PLACES_OPEN =
  '<div class="places ruled" id="places">\n'`; `_with_guitar` puts `_GUITAR_ROW` right after `_PLACES_OPEN`; the
  comments on the settings' places)
- Modify: `src/caracole/viewer/viewer.css` (`.harmony` in the overlay; `#harmony-neck` out; `.ov-tabs` three tabs
  fitting the rail's head beside Hide)
- Modify: `src/caracole/viewer/book.js` (`busy()`: `"harmony"` out)
- Modify: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/pages/internal/PageConstants.kt`
  (`HARMONY_ROW` → `PLACES_OPEN = text("_PLACES_OPEN")`), `.../viewer/pages/SheetPage.kt` (`withGuitar` after
  `PLACES_OPEN`)
- Modify: `android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/pages/SheetPageTest.kt`
  (`theControlsHoldTheHarmonyRowOnceForTheGuitarProRowToFollow` → `theControlsOpenThePlacesOnceForTheGuitarProRowToFollow`:
  `<div class="places ruled" id="places">` once in `SheetPage.CONTROLS`)
- Modify: `tests/test_conformance_viewer_pages.py` (`CONSTANTS`: `"_HARMONY_ROW"` → `"_PLACES_OPEN"`; the docstring;
  `test_the_data_reads_back_as_page_py_holds_it` replaces after `_PLACES_OPEN`)
- Modify: `docs/screenshots/make.py` (the `harmony` shot: `#nm=both` with the rail shown, then `("click", "#necks
  [role=tab][data-tab=harmony]")`, `("wait", "document.querySelector('#harmony .prog') !== null")`), `README.md` (its
  alt text: "The Harmony tab beside the song: …")
- Modify: `docs/usage.md` (**Harmony ›** becomes **Harmony**, the overlay's third tab; **The overlay**: three tabs, the
  key's neck on Harmony; **Showing and hiding it**: drop "Hidden, the Harmony panel shows the key's neck"), `AGENTS.md`
  (strum.js: "the Harmony tab's ▶", "the Harmony tab left" for "the panel closed"; "The rail of necks": "three tabs on a
  sheet, Guitar, Harmonica and Harmony, and two on a harmonica tab's page, Harmonica first"; the viewer/ list's
  overlay.js line)
- Create: `tests/test_viewer_harmony_tab.py`
- Modify: `tests/helpers/viewer_pages.py` (`HARMONY_TAB`, `LEAVE_HARMONY`, `harmony_tab(b)`)
- Test: `tests/test_viewer_panels.py`, `tests/test_viewer_sound.py`, `tests/test_viewer_numerals.py`,
  `tests/test_viewer_songbook_browser.py`, `tests/test_viewer_necks.py`, `tests/test_viewer_overlay.py`,
  `tests/test_viewer_overlay_sheet.py`

**Interfaces:**
- Produces (overlay.js `rail(aside, page)`), two optional members of `page`:
  - `harmony(pane)`: the Harmony tab, always the last, drawn by the page into `pane` (the tab's `div.ov-pane`) on each
    draw while it is the tab shown; each control in it carries a `data-f` the focus comes back to as it is drawn anew.
    Absent: no Harmony tab (the harmonica page).
  - `left(tab)`: the tab `tab` no longer shown, another one pressed or reached by the arrows (called before the draw).
- Produces (viewer.js): `hasHarmony = Boolean(key) && Boolean(data.numerals) && Boolean(data.progressions)` (where
  today's Harmony row showed); `harmonyPane(pane)` draws `div#harmony.harmony`: `p.hint#harmony-key` ("In the key of C
  (from the sheet)."), the key's neck (`overlay.keyNeck(keySpec(s, it))` with `it = necksOf()`, `s` as `guitarTab()`
  takes it, where `data.keyScale`), `div.row#tempo-row` (`#bpm-down`, `output#bpm`, `#bpm-up`, "bpm · 1 chord a
  bar"), `ol.progs#progs`, `p#progs-none`. `data-f` values: `bpm-down`, `bpm-up`, `prog-go:<n>`, `prog-play:<n>`,
  `prog-songs:<n>`, `prog-named:<n>:<j>` (n the section, j the link's index); the neck's chips keep keyNeck's `kn`.
- Produces (page.py): `_PLACES_OPEN`; `_CONTROLS` with no `#harmony` and no `#harmony-row`. If 5b already removed
  `_GUITAR_ROW` and `_with_guitar` (Guitar Pro in the kinds list), only `_HARMONY_ROW` goes, and `CONSTANTS` and
  `PageConstants` lose it with nothing in its place.
- Produces (tests/helpers/viewer_pages.py): `HARMONY_TAB`, JavaScript that shows the Harmony tab at any width (below
  1200 px it presses `#necks-open` unless `#necks[data-sheet]` is open, then `#necks [role=tab][data-tab=harmony]`),
  for `tapped()` as for `b.js`; `LEAVE_HARMONY`, its leaving by the width's way (the sheet's `.ov-close`, the rail's
  `.nk-hide`); `harmony_tab(b)`, `HARMONY_TAB` then a wait for `#harmony`.

Stops: `left("harmony")` (another tab), `close(necksEl)` (✕, Escape, Shapes, Back, another layer on a phone),
`showNecks(false)` (Hide, the bar's toggle) and `drawNecks()` drawing no Harmony pane while `playing` (the window
crossing 1200 px with the sheet closed) each call `stopPlaying(true)` where the Harmony tab was shown: the progression
and every sound strum.js still makes, a chord tapped among them, as closing the panel did.

- [ ] **Step 1: Write the failing tests**

  `tests/test_viewer_harmony_tab.py` takes test_viewer_panels.py's "the Harmony panel" section (its `SONG`, `UNNAMED`,
  `NAMED`, `TWO`, `FAKE_SOUND`, and `HARMONY` reading `document.getElementById('harmony')` inside `#necks`) with these
  tests, their assertions kept but where noted:
  ```python
  def test_the_page_has_no_harmony_panel_and_the_settings_no_harmony_row():
      html = build_viewer(SONG)
      assert 'id="harmony-open"' not in html and 'id="harmony-row"' not in html and 'id="harmony"' not in html

  @in_chromium
  def test_a_sheet_with_a_key_has_harmony_as_the_overlays_third_tab(tmp_path):
      # 1280×800 rail and 390 sheet: tabs ["Guitar", "Harmonica", "Harmony"]; NO_KEY: ["Guitar", "Harmonica"];
      # a harmonica tab's page (test_viewer_harptab_browser's page): ["Harmonica", "Guitar"]

  @in_chromium
  def test_the_keys_neck_heads_the_harmony_tab_and_the_guitar_tab_has_the_chords_alone(tmp_path):
      # Harmony: '#harmony .kn .kn-name' "C scale" first; Guitar: no '.kn', its necks' names the chords'
      # (and on the harmonica page the Guitar tab still heads with the key's neck)

  test_on_a_phone_the_harmony_tab_lists_each_sections_progression   # the phone test: its rows, key line, tempo;
                                                                     # the tab's box is the sheet's, no overflow, no small target
  test_a_page_that_cant_play_a_chord_offers_no_play_and_no_tempo
  test_with_the_sound_off_the_tab_offers_no_play_until_it_is_on_again  # Soft in ⋯, then the tab again
  test_on_a_laptop_the_harmony_tab_is_in_the_rail_beside_the_settings  # at 1280: the rail's pane, the settings
                                                                        # rail open beside it at once
  test_a_section_tapped_in_the_tab_comes_into_view
  test_a_sheet_with_no_headings_has_one_section_to_list
  test_the_tab_names_a_progression_a_section_plays_within_it_and_a_cycle_that_varies
  test_a_link_focused_in_the_tab_keeps_the_focus_though_the_tab_is_drawn_anew  # drawn anew by #t-up's click
  test_play_asks_the_synthesis_for_the_progression_and_marks_the_chord_playing
  test_play_strums_the_progression_with_hv3s_synthesis
  test_a_progression_playing_stops_once_the_song_is_played_otherwise   # moved from test_viewer_panels.py

  @in_chromium
  def test_leaving_the_tab_stops_the_progression(tmp_path):
      # FAKE_SOUND; ▶ then the Guitar tab: window.stopped; ▶ then ✕ (phone): stopped; at 1280, ▶ then Hide: stopped

  @in_chromium
  def test_three_tabs_fit_the_rails_head_beside_hide(tmp_path):
      # at 1200 and 1400: each tab's text whole in its button, the tablist's right <= .nk-hide's left
  ```
  - test_viewer_panels.py: the Harmony section goes (moved); `test_harmony_guitar_pro_and_export_are_rows_at_the_end`
    → `test_guitar_pro_and_export_are_rows_at_the_end` (no Harmony row); `'harmony-open'` out of the lists in
    `test_the_songbook_has_the_same_panel_without_export` and `test_on_a_phone_every_control_of_the_settings_is_a_thumbs_target`.
  - test_viewer_sound.py: `harmony_at_200_bpm`, `OPEN_HARMONY` and `PLAY` through `HARMONY_TAB` and `#harmony
    .prog-play`; each `#harmony [data-close]` click is `LEAVE_HARMONY`; in
    `test_closing_the_panel_stops_every_sound_and_leaves_no_timer` (renamed `test_leaving_the_harmony_tab_stops_every_sound_and_leaves_no_timer`)
    the step with a chord tapped while the tab is open runs at `{"width": 1280, "height": 800, "mobile": False}` (the
    rail beside the card: on a phone the card takes the sheet's place, 5a's one layer at a time), leaving by the Guitar
    tab; likewise in `test_while_the_context_wakes_only_what_was_asked_last_sounds`.
  - test_viewer_numerals.py::`test_a_songbook_song_shows_its_numerals_and_its_harmony`: `harmony_tab(b)` for
    `b.click("#harmony-open")`.
  - test_viewer_songbook_browser.py: the `"harmony"` parameter opens the sheet on its Harmony tab (`harmony_tab(b)`);
    ← and → stay with it, the progression going on.
  - test_viewer_necks.py: `test_the_rails_first_neck_is_the_keys_scale_with_its_tonic_marked` →
    `test_the_harmony_tabs_first_neck_is_the_keys_scale_with_its_tonic_marked`;
    `test_the_keys_neck_follows_the_key_the_mode_and_the_capo` reads it on the Harmony tab;
    `test_with_the_rail_hidden_the_harmony_panel_shows_the_keys_neck` goes; its JS's `harmonyNeck` member goes.
  - test_viewer_overlay.py: `test_a_sheet_opens_on_guitar_and_harmonica_is_a_tab_away_and_not_kept` and
    `test_the_arrows_go_from_tab_to_tab_and_round_the_circle` expect three tabs (→ from Harmony back to Guitar).
  - test_viewer_overlay_sheet.py: `test_on_a_sheet_guitar_comes_first_…` expects three tabs;
    `test_nothing_overflows_and_every_target_is_a_thumbs_on_a_sheet` measures the Harmony tab too.

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q tests/test_viewer_harmony_tab.py`: `id="harmony-open"` still in the page; two tabs.

- [ ] **Step 3: Implement**
  - overlay.js: `tabsOf` appends `["harmony", "Harmony"]` when `typeof page.harmony === "function"`, after the
    order `first` gives; `draw` calls `page.harmony(pane)` for it; `showTab` calls `page.left(was)` before drawing.
  - viewer.js: the rail's `harmony: hasHarmony ? harmonyPane : undefined` and `left: (tab) => { if (tab === "harmony")
    stopPlaying(true); }`; `harmonyPane` keeps `drawHarmony`'s rows code and adds the `data-f`s; `drawPlaying()` walks
    `document.querySelectorAll("#progs > .prog")`; `setBpm()` writes `#bpm` only where it is drawn.
  - viewer.css: the panel's `.prog…` rules apply in the pane as they are; `.ov-tabs > button` padding at
    `calc(8px * var(--nk))` (or whatever makes the three fit, as the test says).
  - Kotlin, as Files says.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q tests/test_viewer_harmony_tab.py tests/test_viewer_panels.py tests/test_viewer_sound.py
  tests/test_viewer_numerals.py tests/test_viewer_songbook_browser.py tests/test_viewer_necks.py
  tests/test_viewer_overlay.py tests/test_viewer_overlay_sheet.py tests/test_viewer_harptab_browser.py
  tests/test_conformance_viewer_pages.py`, then the corpus step (its gradle now runs the Kotlin change:
  `SheetPageTest`, `PagesReplay`).

- [ ] **Step 5: Commit**

  `git add src/caracole/viewer/ android/viewer/ docs/ README.md AGENTS.md tests/ && git commit -m "feat(viewer):
  Harmony is the overlay's third tab, its panel and settings row gone"`

#### Task 5d.6: From 1200 px, a toolbar under the title (D13 C)

From 1200 px wide the bar is a toolbar of pills under the song's header, in the phone's order (key, Shapes, Text,
Scroll, More), in the page's flow so it sticks to the window's top once the title scrolls away; below 1200 px the
bottom bar as now. The sheet keeps room for it: it takes its own room under the title, and `scroll-padding-top` keeps
whatever is brought into view below it. It never slides away as you scroll; while autoscroll counts down and runs it
hides as the bar does, keeping its room so the song doesn't jump. The autoscroll pill and the full-screen handle sit
under it.

**Files:**
- Modify: `src/caracole/viewer/viewer.css` (a `@media screen and (min-width: 1200px)` block for the toolbar, below;
  the bar's `html[data-necks]`/`html[data-panel]` insets below 1200 px only)
- Modify: `src/caracole/viewer/viewer.js` (`toolbarWide`, `placeBar()`, `toolbarEdge()`; `dock()`; the scroll
  handler; `place()`; `layout()`'s room; the resize handler)
- Modify: `src/caracole/viewer/harptab.js` (`toolbarWide`, `placeBar()`, `toolbarEdge()`; `showScroll()`; its scroll
  handler), `src/caracole/viewer/harptab.css` (`.bar .keys`'s max-width in the toolbar)
- Modify: `docs/usage.md` (**The bar**: on a laptop, a toolbar under the title), `AGENTS.md` (viewer/: a bullet "From
  1200 px the bar is a toolbar…", naming `placeBar` and `data-asleep`)
- Create: `tests/test_viewer_toolbar.py`
- Test: `tests/test_viewer_bar.py`, `tests/test_viewer_necks.py`, `tests/test_viewer_panels.py`,
  `tests/test_viewer_scroll.py`, `tests/test_viewer_versions.py`, `tests/test_viewer_harptab_browser.py`

**Interfaces:**
- Consumes: 5b's song header, `<header class="head">`: on sheet.html, a kept version's page and the harmonica page
  `.page > header.head`; in a songbook the shown song's, `section.song > header.head` (`#sheet`'s parent's
  `:scope > header.head`); 5a's full-screen handle (the element 5a put at the foot) and its state; 5d.2's `.bw`,
  `.disc`; 5d.1's order.
- Produces: `toolbarWide` (`matchMedia("(min-width: 1200px)")`) and `placeBar()` in viewer.js and harptab.js (the bar
  right after the song's header while wide, back before `#pill`, where the page wrote it, while narrow; the focus kept
  on the control that had it); `bar[data-asleep]` while autoscroll counts down and runs (both scripts, every width);
  `--toolbar-bottom` on `<html>` (px: the toolbar's bottom edge in the window, 0 at least; written on scroll, resize
  and `placeBar()`, only while wide); `--toolbar` (56px, the toolbar's height, a viewer.css token).

viewer.css, the rules the tests hold it to (sizes are the builder's):
```css
@media screen and (min-width: 1200px) {
  :root { --foot: env(safe-area-inset-bottom); --toolbar: 56px; }  /* no bar at the foot */
  html { scroll-padding-top: calc(var(--toolbar) + 8px); }
  .bar { position: sticky; top: 0; left: auto; right: auto; bottom: auto; margin-top: 10px; padding: 6px 0;
    border: 0; background: var(--bg); box-shadow: none; transition: none; }
  .bar.away { transform: none; }               /* the toolbar never slides away */
  .bar[data-asleep] { visibility: hidden; }    /* autoscroll: out of the way, its room kept */
  .bar-in { justify-content: flex-start; gap: 8px; max-width: none; margin: 0; }
  /* each tool a pill, its icon and its word side by side; the key's pill its key over its word; none pushed right */
  .sizes { top: calc(100% + 10px); bottom: auto; }
  .pill { top: calc(var(--toolbar-bottom, 0px) + 12px); bottom: auto; }
  /* 5a's full-screen handle: top: 0; bottom: auto */
}
```
viewer.js: `dock()` sets `bar.hidden = away && !toolbarWide.matches` and `bar.toggleAttribute("data-asleep", away)`;
the scroll handler slides the bar below 1200 px alone (from 1200 it notes `reveal.y` and returns, and Aa's box stays
open); `place()`'s floor is the window's foot from 1200 px and its ceiling the toolbar's bottom (a card goes above its
chord only where it clears the toolbar); `layout()`'s room for two columns takes `--toolbar`'s height off from 1200 px.
harptab.js: `showScroll()` toggles `data-asleep` with `moving()`; its scroll handler slides below 1200 px alone.

- [ ] **Step 1: Write the failing tests** (`tests/test_viewer_toolbar.py`, `pytestmark = CHROMIUM_MARKS`;
  `DESKTOP = {"width": 1280, "height": 800, "mobile": False}`; LONG from test_viewer_bar.py)
  ```python
  TOOLBAR = """(() => { const r = (e) => e.getBoundingClientRect(), bar = document.getElementById('bar');
    const shown = [...bar.querySelectorAll('button')].filter((e) => e.getClientRects().length);
    return {bar: r(bar).toJSON(), head: r(document.querySelector('.page > header.head')).toJSON(),
      page: r(document.querySelector('.page')).toJSON(), sheet: r(document.getElementById('sheet')).toJSON(),
      ids: shown.map((e) => e.id), lefts: shown.map((e) => r(e).left), tops: shown.map((e) => Math.round(r(e).top)),
      visible: getComputedStyle(bar).visibility, after: bar.previousElementSibling.matches('header.head')}; })()"""

  def test_from_1200_px_the_bar_is_a_toolbar_under_the_title(tmp_path):
      # at scroll 0: after; bar top >= head bottom and < head bottom + 24; bar bottom <= sheet top;
      # ids == ["t-down", "key-now", "t-up", "necks-toggle", "size", "scroll", "more"], lefts increasing, one row
      # (tops alike within 4 px), within the page column; a long title (the brief's case 2) and a Chinese one alike

  def test_once_the_title_scrolls_away_the_toolbar_sticks_to_the_top_and_never_slides(tmp_path):
      # scrollTo(0, 1500): bar top == 0; a wheel down by 600: still 0 and visible; back to 0: under the title again

  def test_what_is_brought_into_view_is_never_under_the_toolbar(tmp_path):
      # a section's scrollIntoView({block: 'start'}) (as Harmony's go does): its top >= the toolbar's bottom

  def test_while_autoscroll_runs_the_toolbar_keeps_its_room_and_the_pill_sits_under_it(tmp_path):
      # #scroll at the page's top: visible == 'hidden' while counting, the bar's height and the sheet's top as before;
      # the pill's top >= the toolbar's bottom (or 0 + 12 once stuck); × : visible again

  def test_below_1200_px_the_bar_is_at_the_foot_again(tmp_path):
      # Emulation.setDeviceMetricsOverride 1280 → 1100 → 1280: at 1100 bar bottom == innerHeight and
      # bar.nextElementSibling is #pill; back at 1280 under the title; the focus on #t-up kept through both moves

  def test_the_aa_box_and_a_chords_card_open_below_the_toolbar(tmp_path):
      # #size: #sizes top >= #size bottom; stuck, a chord in the line right under it: #card top >= toolbar bottom

  def test_a_songbook_song_has_the_toolbar_under_its_own_title(tmp_path):
      # #song-1: bar.previousElementSibling is '#song-1 > header.head'

  def test_a_harmonica_tabs_page_has_the_toolbar_too(tmp_path):
      # ids == ["h-down", "h-up", "necks-toggle", "notes", "size", "scroll"]; scrolling by itself: visibility hidden

  def test_in_full_screen_its_handle_sits_at_the_top(tmp_path):
      # 5a's way into full screen (Hide controls in More): the handle's top == 0 at 1280
  ```
  Updates: test_viewer_bar.py's 1280 cases (`test_the_bar_fits_…` lists 1100 in its place for the bottom bar, the
  toolbar's own test above holds 1280; `test_the_keyboard_reaches_every_control_even_when_the_bar_is_away` at 1100,
  where `necks-open` is in `necks-toggle`'s place); test_viewer_necks.py (`seen["bar"]["left"] == rail["right"]` and
  `rail["bar"]["left"] == 345` from 1200 px become "the toolbar inside the song's column"); test_viewer_panels.py's
  desktop `look()` uses of `bar` (the card's floor), test_viewer_scroll.py's 1280 cases (the pill under the toolbar,
  not above a foot bar), test_viewer_versions.py line ~377 and test_viewer_harptab_browser.py's 1280 bar checks.

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q tests/test_viewer_toolbar.py`: the bar at the window's foot (`after` false, top 748).

- [ ] **Step 3: Implement** as Interfaces and the CSS above say.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q tests/test_viewer_toolbar.py tests/test_viewer_bar.py tests/test_viewer_necks.py
  tests/test_viewer_panels.py tests/test_viewer_scroll.py tests/test_viewer_versions.py tests/test_viewer_layout.py
  tests/test_viewer_harptab_browser.py tests/test_viewer_harmony_tab.py tests/test_viewer_key_list.py`, then the corpus
  step.

- [ ] **Step 5: Commit**

  `git add src/caracole/viewer/ docs/usage.md AGENTS.md tests/ && git commit -m "feat(viewer): from 1200 px the bar is a
  toolbar under the title, sticking at the top"`

#### Task 5d.7: A finger's 48 px, and the corners reaching the screen's edge

Under `pointer: coarse` the bar's and the pill's buttons grow from 44 to 48 px; the bottom corners' buttons (− at the
left, More at the right, or the harmonica page's Scroll, its last) take taps up to the screen's edges. Below 380 px a
phone keeps 44 px widths (48 tall): at 6 × 48 px a 320 px phone would leave the key 24 px.

**Files:**
- Modify: `src/caracole/viewer/viewer.css` (the bar's side paddings as tokens `--bar-l`, `--bar-r` (`max(8px,
  env(safe-area-inset-left))`, 4 px below 420 px, as today); `@media (pointer: coarse)`: `.bar .tool`, `.keys .step`,
  `.pill button` 48 × 48, `html[data-pill] { --pill: 68px; }`; `@media (pointer: coarse) and (max-width: 379.98px)`:
  their widths 44; `@media (pointer: coarse) and (max-width: 743.98px)`, where `.bar-in` spans the bar whole: `#t-down`
  and `#more`, `.bar-in > #scroll:last-child` `position: relative` and an `::after` reaching left (`calc(-1 *
  var(--bar-l))`) or right and down (`calc(-4px - env(safe-area-inset-bottom))`) to the edges)
- Modify: `docs/usage.md` (**The bar**: a finger's 48 px, the corners)
- Test: `tests/test_viewer_bar.py`, `tests/test_viewer_harptab_browser.py`

**Interfaces:**
- Consumes: 5d.1's order, 5d.2's `.tool` height, 5d.6's toolbar (the corner rule is the bottom bar's; the toolbar
  lies under 1200 px's limit of it already).

- [ ] **Step 1: Write the failing tests** (in `tests/test_viewer_bar.py`)
  ```python
  @in_chromium
  @pytest.mark.parametrize(("width", "height", "wide"), [(390, 844, 48), (430, 932, 48), (768, 1024, 48),
                                                         (360, 740, 44), (320, 640, 44)])
  def test_on_a_touch_screen_every_bar_and_pill_button_is_a_fingers_48_px(tmp_path, width, height, wide):
      # viewer(..., mobile=True): coarse. #scroll, #go twice (paused: the bar and the pill both shown); every shown
      # '#bar button, #pill button': height >= 48 and width >= wide; #key-now >= 48 wide; scrollWidth <= width

  @in_chromium
  def test_with_a_mouse_they_stay_44_px(tmp_path):
      # 1100×800 mobile=False: matchMedia('(pointer: coarse)').matches is False, the bar's buttons 44 wide

  @in_chromium
  def test_the_corner_buttons_reach_the_screens_edge(tmp_path):
      hit = "((x, y) => { const e = document.elementFromPoint(x, y); return e && e.closest('button') ? e.closest('button').id : null; })"
      with viewer(tmp_path) as b:  # 390×844, coarse
          corners = b.js(f"[{hit}(0, innerHeight - 1), {hit}(innerWidth - 1, innerHeight - 1)]")
      assert corners == ["t-down", "more"]
      # and the harmonica page's right corner is "scroll"
  ```
  `test_the_bar_fits_a_phone_and_a_desktop_and_the_song_ends_above_it`: `m["smallest"] >= (48 if mobile and width >=
  380 else 44)`; its key-size expectations as measured at 390 and 430 (the key keeps 94 px at 390: "Ab mixolydian"
  whole, `12 <= size <= 16`).

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q tests/test_viewer_bar.py -k "48 or corner or mouse or fits"`: 44 where 48 is expected;
  `elementFromPoint(0, …)` is the bar itself.

- [ ] **Step 3: Implement** the CSS as Files says.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q tests/test_viewer_bar.py tests/test_viewer_overlay_sheet.py tests/test_viewer_harptab_browser.py
  tests/test_viewer_panels.py tests/test_viewer_scroll.py`, then the corpus step.

- [ ] **Step 5: Commit**

  `git add src/caracole/viewer/viewer.css docs/usage.md tests/ && git commit -m "feat(viewer): a finger's 48 px on
  the bar and the pill, the corners reaching the screen's edge"`

#### Task 5d.8: Check it on screen, and merge

**Files:**
- Modify: `docs/screenshots/*.png` (retaken: the bar's words, the Harmony tab, the toolbar)

- [ ] **Step 1: The gate**, every one passing:
  ```
  nix develop -c pytest -q
  nix develop -c pytest -q -n 0 tests/test_conformance_*.py
  nix develop ./android -c gradle -p android test
  nix flake check
  CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py
  android/scripts/device-test.sh --area pages,harmonica-page,render --app   # EndToEndTest reads #key-now, #t-up, #more
  ```
- [ ] **Step 2: On screen** (the design's anti-goal: each stage checked on screen):
  `nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python docs/screenshots/make.py --serve`, and look
  at a sheet, a version's page, a songbook song and a harmonica tab's page at 320, 390, 768, 1100 and 1280 px and on a
  phone in the app: the words, the arrow lit while scrolling, "+2"/"capo 2", the key list, the Harmony tab, the toolbar
  stuck at the top with the pill under it, nothing over the song's last lines. Then the pictures:
  `nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python docs/screenshots/make.py`;
  `git add docs/screenshots && git commit -m "docs: the screenshots retaken with the bar's words and the Harmony tab"`.
- [ ] **Step 3: Merge**, in the checkout that holds `main` (its working tree clean):
  ```
  git switch main
  git merge --no-ff feat/sheet-5d-bar -m "Merge branch 'feat/sheet-5d-bar'"
  GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main
  ```
  Then restart the served library (http://127.0.0.1:8737/) and tell the owner what changed; the next stage branches
  from this `main`.

---

### Stages 5e (reading settings) and 5f (hands-free)

Design: `docs/superpowers/specs/2026-11-17-sheet-pages-redesign-design.md`, "Reading settings" (D5 A, D6 B, D7 B),
"Hands-free" (D15 A + D's highlight, D16 B, D17 A, D18 C), "Fixes that need no choice" (contrast; autoscroll and the
key map under zoom and in the WebView) and "Where it applies". D5 A and D17 A change nothing: today's text size control
and today's end of a song in a songbook stay; tests below pin that they still hold.

Each stage is a branch from `main` once the stage before merged, in the lane's worktree:
`git -C ../caracole-lane5 switch -c feat/sheet-5e-reading main`, then `feat/sheet-5f-hands-free`.

#### What these stages take from 5a–5d

Named by role, since those stages are planned apart. Where a name below differs from what merged, use the merged one.

- **5a's layers**: the one list of what a sheet page has open over or beside the song (viewer.js's `layers` and
  `topLayer()` today: the settings, the card, the Harmony panel, the versions list, the necks' sheet; 5a adds Aa,
  the key list and full screen). "A layer has the focus" below means `document.activeElement` is inside one of them,
  or inside `#sizes`, `#tip`, `#necks` or a `dialog`.
- **5b's version line and list**: their links to the song's other pages are still written by viewer.js's
  `vAddress(page)`, which calls `screenChoices(params)`.
- **5c's lines**: the sung lines are the elements the data's `pinyin` indexes (viewer.js `songLines`,
  `:scope > section.sec > p.l` today; page.py `_drawn_lines(sheet)`), whatever 5c draws a chord-only line as.
- **5d's bar and panels**: the Aa button and its popover (`#size`, `#sizes`), More (`#panel`), the one switch left
  for the strip of chord shapes (the settings' `#strip-toggle`; the bar's `#shapes` too if 5d kept it), and from
  1200 px the toolbar the bar became (5d: sticky at the top of the window).

#### New names these stages make

| Name | Where | What |
|---|---|---|
| `screen.js`, `window.caracoleScreen` | src/caracole/viewer/ | the screen's choices for every viewer page: the theme (5e), the key map and keeping the screen on (5f); inlined in a sheet, a songbook and a harmonica tab's page just before viewer.js or harptab.js |
| `html[data-theme]` | viewer.css | `light` or `dark` chosen; absent for Auto |
| localStorage `caracole-viewer-theme`, address `theme=` | screen.js | `auto`, `light`, `dark`; the address names it only while it is `light` or `dark` |
| `state.shapes` | viewer.js | the strip of chord shapes shown (`true`) or hidden (`false`) by hand for this song, `null` for the default |
| `sung.py`, `sung_lines` | src/caracole/viewer/ | the timed lyrics' lines matched to the sheet's (5f) |
| data member `sung` | page.py `build_viewer` | `[[ms, n or null], …]` |
| `.l.sung`, `--sung` | viewer.css | the line being sung |
| localStorage `caracole-viewer-awake`, address `awake=` | screen.js | the minutes the screen stays on, 0 (Off) to 60 by 5; the address names it while it isn't 10 |
| `html[data-awake="1"]` | screen.js | set while the page holds a screen wake lock |

---

### Stage 5e: Reading settings

#### Task 5e.1: The palette under a chosen theme

**Files:**
- Modify: `src/caracole/viewer/viewer.css` (the dark palette rule after `:root`, line 38; the print rule, line 77)
- Test: `tests/test_viewer_theme.py` (create), `tests/test_viewer_print.py`

**Interfaces:**
- Produces: `html[data-theme="light"]` and `html[data-theme="dark"]` pick the palette on screen whatever the system's
  scheme, and the root's `color-scheme` with it; no attribute is Auto, today's `prefers-color-scheme`. Paper is light
  always.

- [ ] **Step 1: Write the failing tests**

  `tests/test_viewer_theme.py` (module `pytestmark = CHROMIUM_MARKS`; `helpers.viewer_pages`' `viewer`, `written`):

  ```python
  PALETTE = """(() => { const root = [...document.styleSheets].flatMap((s) => [...s.cssRules])
      .find((r) => r.selectorText === ":root" && r.style.getPropertyValue("--bg"));
    const css = getComputedStyle(document.documentElement);
    return {scheme: css.colorScheme, vars: Object.fromEntries([...root.style].filter((n) => n.startsWith("--"))
      .map((n) => [n, css.getPropertyValue(n).trim()]))}; })()"""

  def test_a_chosen_theme_wins_over_the_system_on_screen(tmp_path):
      with viewer(tmp_path, written(tmp_path, SONG)) as b:
          own, chosen = {}, {}
          for system in ("light", "dark"):
              b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": system}])
              b.js("delete document.documentElement.dataset.theme")
              own[system] = b.js(PALETTE)
              for theme in ("light", "dark"):
                  b.js(f"document.documentElement.dataset.theme = '{theme}'")
                  chosen[system, theme] = b.js(PALETTE)
      assert own["light"]["vars"]["--bg"] == "#f7f6f3" and own["dark"]["vars"]["--bg"] == "#131312"
      for (system, theme), seen in chosen.items():
          assert seen["vars"] == own[theme]["vars"], (system, theme)  # one dark palette, one light
          assert seen["scheme"] == theme
  ```

  `SONG`: a short ChordPro sheet with a key, two sections and six sung lines (synthetic words).

  `tests/test_viewer_print.py`: `_seen(tmp_path, kind, media, scheme, theme=None)` sets
  `document.documentElement.dataset.theme = theme` once the page is ready, when given; then

  ```python
  @pytest.mark.parametrize("kind", KINDS)
  def test_a_page_with_dark_chosen_prints_in_the_light_palette(tmp_path, kind):
      printed = _seen(tmp_path, kind, "print", "light", theme="dark")
      on_screen = _seen(tmp_path, kind, "screen", "light")
      assert printed["scheme"] == "light" and printed["vars"] == on_screen["vars"]
  ```

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q -n 0 tests/test_viewer_theme.py tests/test_viewer_print.py` — the chosen theme changes
  nothing: `seen["vars"] == own[theme]["vars"]` fails for (light, dark) and (dark, light).

- [ ] **Step 3: Implement**

  viewer.css, the palette in three rules and the scheme in two:
  - the light palette stays the `:root` rule (test_viewer_print's `COLOURS` finds it by `selectorText === ":root"`);
  - `@media screen and (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { …today's dark palette… } }`;
  - `@media screen { :root[data-theme="dark"] { color-scheme: dark; …the same dark palette… } }`;
  - `:root[data-theme="light"] { color-scheme: light; }`;
  - `@media print { :root { color-scheme: light; } }` stays; the dark rules are under `@media screen`, so paper is
    light whatever is chosen.

  The dark palette is written twice (a media query and an attribute can't share one selector); a comment above the
  second says so, and `test_a_chosen_theme_wins_over_the_system_on_screen` fails on any token one copy lacks.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q -n 0 tests/test_viewer_theme.py tests/test_viewer_print.py tests/test_viewer_numerals.py`

  Then the corpus (viewer.css is inlined in every page):
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py` (twice if a file another reads
  moved), `nix develop ./android -c gradle -p android :viewer:test`: passes with no Kotlin change (the stylesheet is
  copied byte for byte).

- [ ] **Step 5: Commit**

  AGENTS.md: in ":viewer"'s sheet-page bullet "Printed, every viewer page is in the light palette", the dark palette is
  the screen's alone under `@media screen` both for the system's dark (`:root:not([data-theme="light"])`) and for Dark
  chosen (`:root[data-theme="dark"]`).

  `git add src/caracole/viewer/viewer.css tests/test_viewer_theme.py tests/test_viewer_print.py tests/conformance AGENTS.md`
  `git commit -m "feat(viewer): the palette follows a chosen theme on screen, paper stays light"`

#### Task 5e.2: screen.js and the theme in Aa, kept for every page

**Files:**
- Create: `src/caracole/viewer/screen.js`
- Modify: `src/caracole/viewer/page.py` (`BUILD_FILES`; a cached `_screen()` beside `_sound()`; `build_viewer`'s
  `scripts`; `_CONTROLS`' Aa box), `src/caracole/viewer/book.py` (`build_songbook`'s `scripts`),
  `src/caracole/viewer/harptab_page.py` (`build_harmonica_viewer`'s `scripts`), `src/caracole/viewer/viewer.js`
  (`save`, `screenChoices`, `exportLink`, the Aa box's wiring), `src/caracole/viewer/book.js` (`SCREEN`),
  `src/caracole/viewer/viewer.css` (`.sizes`), `tests/helpers/viewer_pages.py`
- Modify (Kotlin): `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/ViewerAssets.kt`
  (`Page`), `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/render/RenderBuild.kt` (`ASSETS`)
- Test: `tests/test_viewer_theme.py`, `tests/test_viewer_bar.py` (the Aa box's markup assertion),
  `tests/test_viewer_numerals.py` (imports `NO_STORAGE` from the helper)

**Interfaces:**
- Consumes: 5e.1's `html[data-theme]`; 5d's `#size`, `#sizes`.
- Produces: `window.caracoleScreen`, frozen: `THEME` (`"caracole-viewer-theme"`), `theme()` → `"auto" | "light" |
  "dark"`, `setTheme(choice)` (applies it, keeps it in localStorage; a value not of the three is ignored),
  `carry(params)` (sets `theme` in a `URLSearchParams` while the theme is light or dark, deletes it for Auto; returns
  `params`; 5f.5 adds `awake`). The Aa box's `#theme` group (`.seg`, `role="group"`, `aria-label="Theme"`) and its
  buttons `#theme-auto`, `#theme-light`, `#theme-dark` (`aria-pressed`). viewer.js's `screenKit`
  (`window.caracoleScreen || null`). `helpers.viewer_pages`: `NO_STORAGE` (moved from test_viewer_numerals.py) and
  `viewer(..., before=())`, each script of `before` given to `Page.addScriptToEvaluateOnNewDocument` before the page
  opens.

- [ ] **Step 1: Write the failing tests** (`tests/test_viewer_theme.py`)

  - `test_screen_js_is_inlined_before_each_pages_own_script`: `page.HERE / "screen.js" in page.BUILD_FILES`; in
    `build_viewer(SONG)`, `build_songbook(...)` and `build_harmonica_viewer(...)`, screen.js's text appears once, after
    winds.js's and before viewer.js's (harptab.js's on the harmonica page).
  - `test_aa_offers_auto_light_and_dark_and_the_choice_holds_for_every_page`: phone (390×844), system light. Click
    `#size`; the `#theme` buttons read `["Auto", "Light", "Dark"]`, `#theme-auto` pressed. Click `#theme-dark`:
    `html[data-theme] == "dark"`, body background `rgb(19, 19, 18)`, only `#theme-dark` pressed,
    `localStorage["caracole-viewer-theme"] == "dark"`, `"theme=dark"` in `location.hash`. Another song's page opened
    in the same browser with no address: dark. Back on the first, `#theme-auto`: no `data-theme`, no `theme=` in the
    address, localStorage `"auto"`; with the system dark the page is dark.
  - `test_light_chosen_holds_on_a_dark_system`: system dark, `#theme-light` → body `rgb(247, 246, 243)`, root
    `color-scheme` `light`; a reload keeps it.
  - `test_without_storage_the_address_carries_the_theme`: `viewer(..., before=[NO_STORAGE])`; Dark chosen, then
    `location.reload()` (wait for the new document, `window.before`): still dark, `theme=dark` in the address, no
    `data-error`.
  - `test_a_songbook_carries_the_theme_to_its_next_song_and_its_contents_follow`: a two-song songbook
    (`build_songbook`), `before=[NO_STORAGE]`, `#song-1`; Dark chosen; `key(b, "ArrowRight", 39)`; song 2 is dark and
    its address holds `theme=dark`; then `#` (the contents) with `theme=dark` in the address: `data-theme` dark.
  - `test_a_link_to_another_page_of_the_song_takes_the_theme`: `helpers.version_pages.folder(tmp_path, WONDERWALL)`'s
    sheet.html; Dark chosen; every link `vAddress` wrote (the versions list's, as 5b left it) has `theme=dark` in its
    fragment.
  - `test_reset_all_leaves_the_theme`: Dark chosen, More → `#reset-all`: still dark.
  - `test_the_aa_box_is_whole_on_a_320_px_phone`: 320×640, `#size` clicked: `#sizes`'s box within `[0, 320]`, each
    `#theme` button at least 44 px tall (`pointer: coarse`), `document.documentElement.scrollWidth <= 320`.
  - `test_the_text_size_is_as_it_was` (D5 A): A− and A+ step 13–30 px by 2 from 18 px as before
    (`#fs-now` "20 px" after A+, `fs=20` in the address).

  `tests/test_viewer_bar.py`: the assertion of the Aa box's markup becomes the new markup (below).

- [ ] **Step 2: Run them and see them fail**

  `nix develop -c pytest -q -n 0 tests/test_viewer_theme.py` — no screen.js in BUILD_FILES; no `#theme`.

- [ ] **Step 3: Implement**

  - **screen.js**: an IIFE, `"use strict"`, a header comment in the style of strum.js's: what it is, that it is the one
    place a viewer page keeps the screen's choices (theme now; keys and the wake lock in 5f), and the API. It reads the
    theme as viewer.js `choiceOf` reads a choice kept for every page (the address's `theme=light|dark` named by a link,
    else localStorage's, the browser's winning on a page come back to: `performance.getEntriesByType("navigation")`'s
    `reload` / `back_forward`), storage wrapped in try/catch; applies it at once (`doc.dataset.theme`, deleted for Auto),
    so the songbook's contents, where viewer.js doesn't run, follow it too.
  - **page.py**: `BUILD_FILES` gains `HERE / "screen.js"` (comment: "the screen's choices, before viewer.js and
    harptab.js"); `_screen()` as `_sound()`; `build_viewer`'s scripts
    `(_sound(), _overlay(), _instruments(), _winds(), _screen(), script)`. book.py's
    `(book_script, _sound(), _overlay(), _instruments(), _winds(), _screen(), script)`; harptab_page.py's
    `(_sound(), _overlay(), _screen(), script)` (its control is 5e.3's).
  - **The Aa box** (`_CONTROLS`): `#sizes` loses its `role` and `aria-label` and holds two rows:
    `<span class="size-row" role="group" aria-label="Text size">` with today's `#smaller`, `#fs-now`, `#bigger`, then
    `<span class="seg theme" id="theme" role="group" aria-label="Theme">` with
    `<button type="button" id="theme-auto" aria-pressed="true">Auto</button>`, `#theme-light` "Light",
    `#theme-dark` "Dark". viewer.css: `.sizes` a column (`flex-direction: column; align-items: stretch`), `.size-row`
    today's row; the box kept within the window (anchored at Aa's right edge, `left: auto; right: 0; transform: none`,
    where centring on Aa would cross the window's edge; the 320 px test decides).
  - **viewer.js**: `const screenKit = window.caracoleScreen || null;` by the other kits. `drawTheme()` (in `render`)
    sets each `#theme` button's `aria-pressed` from `screenKit.theme()`; a click on one: `screenKit.setTheme(…)`,
    `render()`. `save()` calls `screenKit.carry(params)` after the `keep(…)` lines; `screenChoices(params)` calls it too
    (so `vAddress`, `view().carry` and a harmonica tab's link take it); `exportLink`'s from-a-file command deletes
    `theme` with `fs`, `speed`, `vol`, `necks`, `py`. Reset all leaves it. Without screen.js (`screenKit` null) the
    control is hidden.
  - **book.js**: `SCREEN = ["necks", "py", "trad", "inst", "theme"]`, its comment naming the theme.
  - **Kotlin**: `ViewerAssets.Page`: `SHEET` scripts `strum.js, overlay.js, instruments.js, winds.js, screen.js,
    viewer.js`; `SONGBOOK` the same after `book.js`; `HARMONICA` `strum.js, overlay.js, screen.js, harptab.js`.
    `RenderBuild.ASSETS` gains `"screen.js"` between `"overlay.js"` and `"strum.js"`. Nothing else: copyViewerAssets
    copies every `*.js`, and page.json's `_CONTROLS` is regenerated.

- [ ] **Step 4: Run them and see them pass**

  `nix develop -c pytest -q -n 0 tests/test_viewer_theme.py tests/test_viewer_bar.py tests/test_viewer_book.py
  tests/test_viewer_songbook_browser.py tests/test_viewer_numerals.py`;
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py` (theory_assets.jsonl, page.json,
  pages*, harmonica_pages*, render.jsonl move); `nix develop ./android -c gradle -p android test` (PagesReplay,
  HarmonicaPageReplay, the theory replay's assets, PhoneRenderTest's `ASSETS` held to its folder).

- [ ] **Step 5: Commit**

  docs/usage.md, "The sheet viewer": the Aa bullet says the box holds the text size and Auto / Light / Dark (Auto as
  the system is; the choice kept for every sheet, songbook and harmonica tab page; printed pages light); the paragraph
  "The viewer remembers its settings" names `theme=dark` (kept so too). AGENTS.md: viewer/'s list gains **screen.js**
  (the screen's choices, `window.caracoleScreen`, inlined before viewer.js and harptab.js); "Settings kept for every
  page at once" gains **The theme** (`caracole-viewer-theme`, `theme=` while not Auto, carried by `carryScreen` and
  `screenChoices`, applied by screen.js before the page's script, the library page not affected).

  `git add src/caracole/viewer tests android/viewer docs/usage.md AGENTS.md`
  `git commit -m "feat(viewer): Auto, Light or Dark in Aa, kept for every viewer page"`

#### Task 5e.3: The harmonica tab's page takes the theme

**Files:**
- Modify: `src/caracole/viewer/harptab_page.py` (`_BAR`'s Aa box; `_BAR_RAW` follows from it),
  `src/caracole/viewer/harptab.js` (`save`, `backToSheet`, the box's wiring)
- Test: `tests/test_viewer_theme.py`

**Interfaces:**
- Consumes: 5e.2's `caracoleScreen` (`theme`, `setTheme`, `carry`) and the `#theme` markup.

- [ ] **Step 1: Write the failing test**

  `test_the_harmonica_tabs_page_offers_the_theme_and_takes_it_back_to_the_sheet` (parametrized over a tab caracole
  reads and one shown as written, `tests/fixtures/harptabs/tabs/124_heart-of-gold.txt` and an unreadable text as
  test_viewer_harptab_browser.py builds them, with `back="sheet.html"`): `#size` → `#theme-dark` → dark body;
  `a.back[data-sheet]`'s `href` fragment holds `theme=dark`; opened with `#theme=light` on a dark system: light; at
  320 px the box is whole.

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q -n 0 tests/test_viewer_theme.py -k harmonica`:
  no `#theme` on the page.

- [ ] **Step 3: Implement**

  `_BAR`'s Aa box as `_CONTROLS`' (5e.2). harptab.js: `screenKit`, the buttons' `aria-pressed` drawn in its `render`,
  a click `setTheme` then `render()` and `save()`; `save()` and `backToSheet()` call `screenKit.carry(params)`.

- [ ] **Step 4: Run it and see it pass** — the test, `tests/test_viewer_harptab_browser.py`,
  `tests/test_viewer_harptab_page.py`; the corpus written again (harmonica_page.json's `_BAR`, `_BAR_RAW`,
  harmonica_pages*); `nix develop ./android -c gradle -p android :viewer:test`.

- [ ] **Step 5: Commit** — docs/usage.md's harmonica tab's page paragraph ("Aa the text size …") names the theme.
  `git add src/caracole/viewer tests docs/usage.md` ·
  `git commit -m "feat(viewer): the harmonica tab's page offers the theme and carries it back to the sheet"`

#### Task 5e.4: The strip of chord shapes by default on a phone

**Files:**
- Modify: `src/caracole/viewer/viewer.js` (`state`, the saved settings' read, `drawStrip`, the strip's switch,
  `railWide`'s change listener)
- Test: `tests/test_viewer_strip.py` (create); the tests that press `#strip-toggle` expecting the strip hidden below
  1200 px: `tests/test_viewer_sound.py::test_the_strip_and_the_keyboard_play_it_too` (1000 px), the
  `run_in_page` test of `tests/test_viewer.py` near line 1005, and any other `rg -n "strip-toggle|#shapes" tests/`
  finds below 1200 px: each presses the switch only while `#strip` is hidden, as `test_viewer_instruments_page.strip`
  does.

**Interfaces:**
- Consumes: 5d's switch for the strip (`#strip-toggle`, and `#shapes` if kept); 5b's header (the strip stays between
  it and the sheet: page.py `_song_html` already puts `#strip` before `#sheet`).
- Produces: `state.shapes` (`null | true | false`, saved per song as today's `strip` was); `stripShown()` →
  `state.shapes ?? !railWide.matches`.

- [ ] **Step 1: Write the failing tests** (`tests/test_viewer_strip.py`, `@in_chromium` module)

  - `test_on_a_phone_the_strip_shows_the_songs_shapes_above_the_first_section` (390×844, no settings kept):
    `#strip` shown, one button per chord the sheet names once, its bottom ≤ the first `section.sec`'s top, the
    switch `aria-pressed="true"`; scrolled 800 px down, its bottom < 0 (it went with the sheet); tapping its second
    button opens the card on that chord (`#card-name`).
  - `test_from_1200_px_the_rail_holds_the_shapes_and_the_strip_waits_for_its_switch` (1280×900): hidden, switch
    false; pressed: shown.
  - `test_hidden_by_hand_it_stays_hidden_for_that_song_alone` (phone): switch → hidden; reload: hidden; another
    song's page: shown.
  - `test_a_song_opened_before_keeps_the_default`: localStorage holds today's record for the page
    (`{"base": 0, "strip": false, …}`): the strip shows (an old `strip` says nothing).
  - `test_the_strip_draws_the_instrument_shown`, parametrized `inst=ukulele` (boxes of 4 strings), `inst=piano`
    (`svg.kb`), `inst=harmonica` (`svg.hp`): default shown at 390 px.
  - `test_the_strip_fits_a_320_px_phone_and_one_on_its_side` (320×640 and 844×390): shown, `scrollWidth` ≤ the
    window's width.
  - `test_a_songbook_song_shows_its_strip_and_the_harmonica_page_has_none`.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q -n 0 tests/test_viewer_strip.py`: the
  strip is hidden by default.

- [ ] **Step 3: Implement**

  `state.strip` becomes `state.shapes: null`; the saved record's `shapes` is read when it is a boolean, its `strip`
  ignored (every song saved `strip: false` before, so it said nothing). `drawStrip` draws while `stripShown()` and
  sets the switch's (and `#shapes`') `aria-pressed` from it; a press sets `state.shapes = !stripShown()` and renders.
  `railWide`'s change listener calls `drawStrip()` before `layout()`. Reset all leaves `shapes`.

- [ ] **Step 4: Run them and see them pass** — the new file, then every viewer test that touches the strip:
  `nix develop -c pytest -q -n 0 tests/test_viewer_strip.py tests/test_viewer_sound.py tests/test_viewer.py
  tests/test_viewer_necks.py tests/test_viewer_instruments_page.py tests/test_viewer_winds_page.py
  tests/test_viewer_bar.py`; the corpus written again; `nix develop ./android -c gradle -p android :viewer:test`.

- [ ] **Step 5: Commit** — docs/usage.md: the strip bullet ("Every chord's shape in a strip above the song") says it
  shows by default below 1200 px (on the instrument shown; from 1200 px the rail holds the shapes and the strip waits
  for its switch), its switch kept for the song. AGENTS.md's "Below 1200 px" bullet: the strip shows by default there.
  `git add src/caracole/viewer tests docs/usage.md AGENTS.md` ·
  `git commit -m "feat(viewer): the strip of chord shapes shows by default on a phone"`

#### Task 5e.5: Contrast: the tapped chord in light, the dark role colours by lightness

**Files:**
- Modify: `src/caracole/viewer/viewer.css` (light `--mark`; dark `--home`, `--away`, `--pull` in both dark rules)
- Test: `tests/test_viewer_theme.py`; `tests/test_viewer_harptab_browser.py`
  (`test_blow_and_draw_in_the_viewers_colours_light_and_dark`'s dark draw colour)

**Interfaces:**
- Produces: light `--mark: #fde8cd` (was `#fbe3c4`); dark `--home: #b8f2c7`, `--away: #a0c6ff`, `--pull: #cc8ad9`
  (were `#6fd08f`, `#8ab8ff`, `#e5a3ef`).

- [ ] **Step 1: Write the failing tests** (`tests/test_viewer_theme.py`, with `luminance` and `contrast` as
  test_viewer_numerals.py's and `lightness(colour) = 116 * Y ** (1/3) - 16`, CIE L*)

  - `test_a_tapped_chord_reads_at_4_5_to_1_in_the_light_theme`, parametrized (system light, no theme) and (system
    dark, `theme=light`), `#nm=both`: tap a chord; `.c.on`'s colour against its background ≥ 4.5, and each of its
    `.nm`'s ≥ 4.5.
  - `test_the_dark_role_colours_differ_in_lightness`, parametrized (system dark) and (system light, `theme=dark`),
    `#nm=both` on a sheet with home, away and pull chords (test_viewer_numerals' `IN_C`): the colours of `.nm.r-h`,
    `.nm.r-a`, `.nm.r-p`; each ≥ 4.5:1 against the page's background, `--surface` (the tooltip's) and `--mark` (a
    tapped chord's); each pair's L* at least 10 apart.

  Today: 4.46:1 on the tapped chord; L* within 2 of each other in dark.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q -n 0 tests/test_viewer_theme.py -k "tapped or role"`.

- [ ] **Step 3: Implement** — the values above, in the light `:root` rule and in both dark rules (they give 4.65:1
  for the chord on `#fde8cd` and 4.51:1 for a home numeral on it; dark L* 90.7, 79.1 and 66.5, each ≥ 4.51:1 on dark
  `--mark` and ≥ 6.6:1 on `--surface`; `--on-away` text on the new `--away` 9.9:1). test_viewer_harptab_browser's
  dark draw becomes `"rgb(160, 198, 255)"`.

- [ ] **Step 4: Run them and see them pass** — the two files, `tests/test_viewer_numerals.py`,
  `tests/test_viewer_harp.py`, `tests/test_viewer_overlay.py`; the corpus written again; `:viewer:test`.

- [ ] **Step 5: Commit** — `git add src/caracole/viewer/viewer.css tests` ·
  `git commit -m "fix(viewer): a tapped chord at 4.5:1 in light, the dark role colours apart by lightness"`

#### Task 5e.6: Merge stage 5e

- [ ] On screen: `nix develop -c caracole serve` (a library of yours, or `docs/screenshots/make.py --serve`): a
  sheet, a version page, a songbook song and a harmonica tab's page on a phone-sized window and a laptop, each theme,
  the strip; then retake the README's pictures, whose phone sheets now show the strip:
  `nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python docs/screenshots/make.py`.
- [ ] `nix develop -c pytest -q`; `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`
  leaves `git status` clean; `nix develop ./android -c gradle -p android test`; `nix flake check`;
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py`.
- [ ] In the worktree: `git add docs/screenshots && git commit -m "docs: the README's pictures with the strip of chord
  shapes"`; then in the main checkout: `git switch main && git merge --no-ff feat/sheet-5e-reading &&
  GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

---

### Stage 5f: Hands-free

#### Task 5f.1: The timed lyrics matched to the sheet's lines (Python)

**Files:**
- Create: `src/caracole/viewer/sung.py`
- Modify: `src/caracole/viewer/page.py` (`BUILD_FILES`; `build_viewer(..., timed=())`),
  `src/caracole/render.py` (`_render_song`, `_render_versions`, `_render_version`, `_render_sheet`, `_write_viewer`;
  a new `_timed_lyrics(song)`)
- Modify (corpus generators): `tests/test_conformance_viewer_pages.py` (`constants`, `DEFAULTS`, `_options`,
  `parts_records`), `tests/test_conformance_viewer_render.py` (`store_lyrics(..., synced=None)`, one song with timed
  lyrics)
- Test: `tests/test_viewer_sung.py` (create), `tests/test_render_all.py`, `tests/test_render_versions.py`

**Interfaces:**
- Consumes: page.py `_drawn_lines(sheet)` (the lines the data's `pinyin` indexes, 5c's rule for them);
  lyrics.py `song_lyrics`, `synced_lines`; normalize.py `name_words`, `simplified`; rapidfuzz `fuzz.ratio`.
- Produces:
  - `sung.LINE_MATCH = 80`, `MIN_SHARE = 0.5`, `MIN_LINES = 4`, `MAX_SECONDS = 86400`;
  - `sung.line_key(text: str) -> str`: `" ".join(name_words(simplified(text)))`;
  - `sung.sung_lines(drawn: Sequence[str], timed: Sequence[Sequence]) -> list[list[int | None]] | None`: for each
    timed line `(seconds, text)` under `MAX_SECONDS`, in the order given, `[round(seconds * 1000), n]`, `n` the index
    in `drawn` of the sheet line it is sung on, or `None`; `None` for the whole when fewer than `MIN_LINES`, or fewer
    than `MIN_SHARE` of `drawn`'s lines with words, were matched;
  - `build_viewer(..., timed: Sequence[Sequence] = ())`: data member `sung` (after `guitarDownload`, the last
    `build_viewer` adds) when `sung_lines` gives a list; none otherwise;
  - render.py `_timed_lyrics(song: Song) -> tuple[tuple[float, str], ...]`, passed as `timed=` to every viewer of the
    song (sheet.html, sheet (auto).html, each version-<tab>.html).

- [ ] **Step 1: Write the failing tests**

  `tests/test_viewer_sung.py` (no browser):

  ```python
  DRAWN = ["Synthetic morning on the river", "", "Paper boats are drifting slowly", "Nobody counts the hours",
           "Sing it back to me", "Over the hills and home"]
  def lrc(*lines, start=8.0, gap=4.0):
      return [(start + gap * k, text) for k, text in enumerate(lines)]

  def test_each_timed_line_lights_the_sheet_line_it_is_sung_on():
      assert sung_lines(DRAWN, lrc(*[t for t in DRAWN if t])) == [
          [8000, 0], [12000, 2], [16000, 3], [20000, 4], [24000, 5]]

  def test_a_chorus_the_sheet_writes_once_is_lit_the_first_time_alone():
      timed = lrc(DRAWN[0], DRAWN[2], DRAWN[3], DRAWN[4], DRAWN[5], DRAWN[4], DRAWN[5])
      assert [n for _, n in sung_lines(DRAWN, timed)] == [0, 2, 3, 4, 5, None, None]

  def test_words_written_a_little_otherwise_still_match_another_line_never(): ...
      # "Paper boats are driftin' slowly" matches line 2; "Something else entirely here" matches nothing
  def test_an_instrumental_break_lights_nothing(): ...   # an empty timed line gives [ms, None]
  def test_too_few_matches_give_no_highlight(): ...      # 3 of 5 lines: None (MIN_LINES); 4 of 10: None (MIN_SHARE)
  def test_traditional_lyrics_meet_a_simplified_sheet(): ...  # "斑馬，斑馬" over "斑马 斑马", and 4 more lines
  def test_a_time_past_a_day_is_left_out(): ...           # (86400.0, …) gives no entry; 86399.999 gives one
  def test_build_viewer_puts_the_sung_lines_in_its_data_by_the_lines_pinyin_reads():
      # a sheet with notes before the song (a preamble) and a chord-only line: build_viewer(cho, timed=…)'s
      # data["sung"] indexes page._drawn_lines(parse_sheet(cho)); without timed, or too few matches, no "sung"
  ```

  `tests/test_render_all.py`:
  - `test_a_songs_timed_lyrics_light_its_viewers_lines(conn, cfg)`: `rendered_song(conn, cfg)`, then the song's
    `lyrics_json` set to `Lyrics(plain=…, synced=<an LRC of its sheet's sung lines, 4 s apart from 00:08.00>, …).to_json()`
    and `render_all` again: sheet.html's `viewer_data(...)["sung"]` is the list `sung_lines` gives for them.
  - `test_lyrics_that_cant_be_read_leave_the_viewer_without_sung_lines(conn, cfg)`: `lyrics_json` `"[1, 2]"` (a
    TypeError) and an LRC with a minute of 400 digits (an OverflowError): the viewer is written, no `sung`, nothing
    failed.

  `tests/test_render_versions.py::test_a_kept_versions_page_lights_its_own_lines_too`: `song_with_versions` with B's
  text `sheet(str(B)) * 3` (six sung lines), synced lyrics of those six lines 3 s apart: `version-39144.html`'s data
  `sung == [[0, 0], [3000, 1], [6000, 2], [9000, 3], [12000, 4], [15000, 5]]`.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q tests/test_viewer_sung.py
  tests/test_render_all.py -k "sung or timed" tests/test_render_versions.py -k lights`: no module `caracole.viewer.sung`.

- [ ] **Step 3: Implement**

  `sung.py`, its docstring the rule in words (why a monotone match: the sheet reads top to bottom as the song is
  sung; a sheet that writes a chorus once lights it the first time; lines the sheet words otherwise match within
  `LINE_MATCH`; Chinese meets either script by `simplified`). rapidfuzz imported inside `sung_lines` (importing
  `caracole.cli` must not load it). The match, which the tests leave a choice in:

  ```python
  keys = [line_key(t) for t in drawn]
  sung = [(round(s * 1000), line_key(t)) for s, t in timed if s < MAX_SECONDS]
  fits = [[bool(a) and bool(b) and fuzz.ratio(a, b) >= LINE_MATCH for _, b in sung] for a in keys]
  best[i][j]  # most pairs matchable from sheet line i and timed line j on: max(best[i+1][j], best[i][j+1],
              # 1 + best[i+1][j+1] where fits[i][j]); filled from the ends, 0 past either
  # the walk from (0, 0): where fits[i][j] and best[i][j] == 1 + best[i+1][j+1], pair them and step both;
  # else step j (a timed line this sheet line isn't) while best[i][j+1] >= best[i+1][j], else step i
  ```

  `round` is Python's (half to even), `MAX_SECONDS` keeps `seconds * 1000` finite. `build_viewer`: `timed` documented
  in its docstring; `BUILD_FILES` gains `HERE / "sung.py"`.

  render.py: `_timed_lyrics(song)` imports `song_lyrics` and `synced_lines` inside it and answers `()` for no lyrics,
  none timed, or `(TypeError, ValueError, OverflowError)`; `_render_song` reads it once and passes `timed=` down to
  every `_write_viewer` call (`_render_versions` → `_render_version`, and `render()` → `_render_sheet`).

  Corpus generators:
  - test_conformance_viewer_pages.py: `constants()["sung"] = {"LINE_MATCH": …, "MIN_SHARE": …, "MIN_LINES": …,
    "MAX_SECONDS": …}` from the module; `DEFAULTS["timed"] = ()`; `_options` draws `timed` for a third of the
    sheets: `_timed(rng, cho)`, the sheet's lines with words 3.5 s apart from 8.0 s, its first section's sung again at
    the end, one line in five with two letters swapped, one dropped, an empty line in the middle, and for one in four
    of those a run of unrelated lines that leaves too few matches; `parts_records` gains `caracole.viewer.sung.line_key`
    (a batch: `EDGE_WORDS` and the sheets' `_lyric_texts()`) and `caracole.viewer.sung.sung_lines` records
    (`SUNG_SHEETS = 20` corpus sheets with a `_timed`, plus every edge of the tests above: the pages carry the rest by
    their data's digest), so a mismatch names the function. The viewer area has about 2.9 MB of its 12 MB left
    today and 5b–5d write there too: `tests/test_corpus_budget.py` must still pass; if it doesn't, the `sung_lines`
    records keep each answer as the first 16 hex digits of its SHA-256, as version.jsonl's batches do, and the stage's
    report says so (a lane never raises a budget).
  - test_conformance_viewer_render.py: `store_lyrics(..., synced=None)`; the World's first song with a human UG sheet
    stores synced lyrics of its sheet's sung lines (`page._drawn_lines` of its .cho), 4 s apart, so render.jsonl
    holds a page with `sung`.

- [ ] **Step 4: Run them and see them pass** — the three test files; `nix develop -c pytest -q -m "not slow"`
  (`test_commands_index_match.py`'s import tests among them); then
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`. Gradle now fails on
  `PagesReplay` (pages_parts' counts and the pages with `timed`) and `RenderReplay` (the song with timed lyrics):
  5f.2 follows in this branch, which merges only with it.

- [ ] **Step 5: Commit** — AGENTS.md: render's "What every viewer of the song carries" gains `sung` (the song's timed
  lyrics matched to the sheet's lines, sung.py); viewer/'s list gains **sung.py**. docs/usage.md waits for 5f.3,
  where the page shows it.
  `git add src/caracole tests AGENTS.md` ·
  `git commit -m "feat(render): each viewer carries the song's timed lyrics matched to its lines"`

#### Task 5f.2: The phone builds the same `sung`

**Files:**
- Create: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/sung/Sung.kt`
- Modify: `android/viewer/src/main/kotlin/io/github/danielhp95/caracole/viewer/pages/SheetPage.kt` (`ViewerInputs`,
  `build`), `.../viewer/pages/internal/PageConstants.kt` (page.json's `sung`),
  `.../viewer/render/internal/SongPass.kt` (`pages`, `renderSheet`, `renderVersion`),
  `android/viewer/src/testFixtures/kotlin/io/github/danielhp95/caracole/viewer/testing/replays/PagesReplay.kt`
  (`inputs`, `everyPartIsPagePys`)
- Test: `:viewer`'s `SheetPageTest` (PagesReplay), the render replay (`RenderReplay`, PhoneRenderTest)

**Interfaces:**
- Consumes: 5f.1's vectors and page.json; `SheetView.drawnLines`, `Normalize.nameWords`, `Normalize.simplified`,
  `Fuzz.ratio`, `PyFormat.roundHalfEven`, core.lyrics' `lyricsFromJson` and `Lyrics.syncedLines`.
- Produces: `object Sung { fun lineKey(text: String): String; fun lines(drawn: List<String>, timed: List<Pair<Double,
  String>>): List<Pair<Long, Int?>>? }`; `ViewerInputs.timed: List<Pair<Double, String>> = emptyList()`.

- [ ] **Step 1: The failing tests** are 5f.1's vectors, which PagesReplay and the render replay already read; add
  `SungTest` (`android/viewer/src/test/kotlin/io/github/danielhp95/caracole/viewer/sung/SungTest.kt`) with 5f.1's
  `test_each_timed_line_lights_…` and `test_a_time_past_a_day_…` cases as Kotlin asserts.

- [ ] **Step 2: Run them and see them fail** — `nix develop ./android -c gradle -p android :viewer:test`: PagesReplay
  says `an unknown record: caracole.viewer.sung.…` and the pages with `timed` differ in their data's `sung`; the render
  replay's page with timed lyrics differs; SungTest doesn't compile.

- [ ] **Step 3: Implement**

  `Sung.kt` is sung.py function for function (its KDoc names it), its constants `PageConstants.SUNG_*` from page.json;
  Python's ratio compared `>= LINE_MATCH` on the Double rapidfuzz-cpp's port gives, `roundHalfEven(seconds * 1000)`;
  no JDK text API (ForbiddenApis). `SheetPage.build` sets `data["sung"]` after `guitarDownload`, each entry
  `[ms, n or null]`. `SongPass.pages` reads `lyricsFromJson(song.lyricsJson)?.synced` into `Lyrics.syncedLines` once,
  `emptyList()` for none or on `IllegalArgumentException` / `ArithmeticException` (Python's TypeError, ValueError,
  OverflowError), and passes it to `renderSheet` and `renderVersion`'s `ViewerInputs`. `PagesReplay.inputs` reads
  `kw["timed"]` (`[[seconds, text], …]`); `everyPartIsPagePys` answers `line_key` and `sung_lines` records and expects
  twelve kinds.

- [ ] **Step 4: Run them and see them pass** — `nix develop ./android -c gradle -p android test` (ForbiddenApiTest
  among them).

- [ ] **Step 5: Commit** — AGENTS.md, ":viewer" "The sheet page (pages)": `SheetPage.build` takes `timed`, `Sung` is
  sung.py's; "The phone's own pages": SongPass passes the song's timed lyrics to every page it makes.
  `git add android AGENTS.md` · `git commit -m "feat(android): the phone's sheet pages carry the sung lines too"`

#### Task 5f.3: The line being sung, lit while autoscroll is on

**Files:**
- Modify: `src/caracole/viewer/viewer.js` (the scroll's `run`, `pauseScroll`, `endScroll`, the sheet's click
  handler; a lyrics clock), `src/caracole/viewer/viewer.css` (`.l.sung`; `--sung` in the light palette and both dark
  rules), `tests/helpers/viewer_pages.py` (`written(tmp_path, cho, name="Title", **options)`, passed to
  `build_viewer`)
- Test: `tests/test_viewer_sung_browser.py` (create)

**Interfaces:**
- Consumes: 5f.1's data `sung`; 5c's sung lines (`songLines`, the elements `pinyin` indexes).
- Produces: `.l.sung` on the one line lit; `--sung` light `#fdf1e4`, dark `#2f2418`.

- [ ] **Step 1: Write the failing tests** (Browser on real time, 390×844, a page of `SONG` (eight sung lines) built
  with `timed` 0.8 s apart from 0.0, as `test_viewer_scroll`'s `start_now` starts it)

  ```python
  LIT = "[...document.querySelectorAll('#sheet section.sec > p.l')].findIndex((l) => l.classList.contains('sung'))"
  ```
  - `test_the_line_being_sung_is_lit_from_the_count_in_on`: nothing lit (`-1`) before ▶; counting down: `-1`; once it
    runs, `0`, then `1` within 2 s (`b.wait`); one line at a time.
  - `test_a_pause_stops_the_clock_and_a_tap_on_a_line_sets_it_there`: running, tap the words of line 5
    (`tap(b, ...)`): paused, line 5 lit and still lit 1.5 s later; `#go` twice (resume at once): line 5, then 6.
    A tap on a chord of line 2 opens its card and leaves the clock (line 5 still lit).
  - `test_ended_nothing_is_lit_and_the_clock_starts_over`: `#pill-end`: `-1`; started again: `0`.
  - `test_no_timed_lyrics_or_too_few_matches_light_nothing`: a page without `timed`, and one whose `timed` matches
    two lines: running 2 s, `-1` throughout.
  - `test_a_chinese_sheet_lights_its_lines_with_pinyin_shown`: a Chinese sheet (test_viewer_pinyin's), `#py=1`,
    Traditional timed lyrics: the line lit is the one its text says.
  - `test_the_lit_line_reads_at_4_5_to_1_in_both_themes` (`theme=light`, `theme=dark`): its words and each chord on
    it against the band's colour ≥ 4.5.
  - `test_with_reduced_motion_the_light_moves_with_no_transition` (`reduced=True`): `transitionDuration` `0s`.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q -n 0 tests/test_viewer_sung_browser.py`.

- [ ] **Step 3: Implement**

  viewer.js: `const SUNG = Array.isArray(data.sung) ? data.sung : [];` and for each sung line its first time
  (`timeOf`); a clock `{ at: 0, since: null }` in ms: `run()` sets `since = performance.now()`; `pauseScroll` folds
  the time run into `at` and sets `since = null`; `endScroll` sets both back (`0`, `null`). `lightSung()`: off, none
  lit; else the last entry at or before the clock's time, its line lit if it names one, none if it names `null`;
  called by each frame of `run`, by `pauseScroll`, `endScroll` and a tap. The sheet's click handler: while the scroll
  isn't off, a click inside a timed line and outside its chords sets `at` to that line's time (`since` kept running
  if autoscroll still runs: a mouse click pauses nothing) and lights it. The scroll's speed is untouched.
  viewer.css: `.l.sung { background: var(--sung); border-radius: 6px; box-shadow: 0 0 0 .2em var(--sung); }`, no
  transition; `--sung` in all three palette rules.

- [ ] **Step 4: Run them and see them pass** — the file and `tests/test_viewer_scroll.py`; the corpus written
  again; `nix develop ./android -c gradle -p android :viewer:test`.

- [ ] **Step 5: Commit** — docs/usage.md's Auto-scroll bullet: where the song has timed lyrics (LRCLIB's or
  Megalobiz's), the line being sung is lit while it scrolls, the lyrics' clock starting after the count-in and
  stopping with a pause; a tap on a line sets the clock there; a song whose lines caracole can't match shows none; no
  recording plays, so it is a guide, not a follower.
  `git add src/caracole/viewer tests docs/usage.md` ·
  `git commit -m "feat(viewer): the line being sung lit while it scrolls"`

#### Task 5f.4: Keys and pedals

**Files:**
- Modify: `src/caracole/viewer/screen.js` (`keys`), `src/caracole/viewer/viewer.js` (its `SCROLL_KEYS` listener;
  `screenKit.keys(...)`), `src/caracole/viewer/harptab.js` (the same)
- Test: `tests/test_viewer_keys.py` (create); `tests/test_viewer_scroll.py` (still passing)

**Interfaces:**
- Consumes: 5a's layers (`busy`), 5d's toolbar and bar (`room`).
- Produces: `caracoleScreen.keys({ toggle, pause, room, busy })`: binds the key map on `document` once. `toggle()`,
  the page's Space and Enter: the bar's ▶ when autoscroll is off, else the pill's `#go` (counting: at once; running:
  pause; paused: count-in again). `pause()`: autoscroll paused if it moves. `room()` → `{ top, bottom }`, the CSS px
  of the window the page's controls cover at its top and its foot. `busy()`: a layer of the page has the focus.
  Constants `KEPT = 2` (lines kept by a turn) and `LINE = 2.6` (a chord row and its words, in the text's em, for a
  turn with fewer than three whole lines in view).

- [ ] **Step 1: Write the failing tests** (`tests/test_viewer_keys.py`, `@in_chromium` module; a long sheet as
  test_viewer_scroll's `LONG`; `key(b, name, code)`, `b.press(" ")`)

  ```python
  # The lines wholly in view between the page's controls, by their index among the sheet's lines: below the toolbar
  # where the bar is one at the top (1280 px), above the bar's place where it sits at the foot (its height whether
  # slid away or not), and above the pill while it shows.
  WHOLE = """(() => { const bar = document.getElementById('bar'), pill = document.getElementById('pill');
    const atTop = bar.getBoundingClientRect().top < innerHeight / 2;
    const top = atTop && !bar.hidden ? bar.offsetHeight : 0;
    let bottom = !atTop && !bar.hidden ? innerHeight - bar.offsetHeight : innerHeight;
    if (!pill.hidden) bottom = Math.min(bottom, pill.getBoundingClientRect().top);
    return [...document.querySelectorAll('#sheet p, #sheet pre')].map((el, n) => [n, el.getBoundingClientRect()])
      .filter(([, r]) => r.height && r.top >= top - 1 && r.bottom <= bottom + 1).map(([n]) => n); })()"""
  ```
  - `test_pagedown_turns_a_screen_keeping_two_lines_and_pageup_turns_back`, parametrized: 390×844 phone, 844×390 on
    its side, 1280×900 laptop, 390×844 at `--force-device-scale-factor=1.75`, 390×844 with
    `--blink-settings=minimumFontSize=40` (the app's text zoom): from the top, `PageDown`: the last two lines wholly in
    view before are the first two after; `ArrowDown` the same again; `PageUp`: the first two before are the last two
    after; the scroll position always whole pixels.
  - `test_space_and_enter_start_and_stop_autoscroll` (focus on the page): Space → counting; Space → running; Enter →
    paused; Enter → counting; the page didn't move by Space's own scroll.
  - `test_a_page_key_while_it_scrolls_pauses_it_and_turns`: running; `PageDown`: `#go` "Resume" and turned as above.
  - `test_keys_are_left_alone_in_a_text_field_or_a_layer`: More open with the focus in it, then the card, the Aa
    box, the `#insts` menu, the rail's tabs at 1280 px: Space, PageDown and ArrowDown neither start nor turn; Space
    on a focused chord opens its card; with the focus on `#scroll`, Enter presses it (as today).
  - `test_a_modifier_leaves_the_key_to_the_browser`: Shift+Space and Alt+ArrowDown: no start, no turn by the map.
  - `test_no_key_changes_the_version`: helpers/version_pages' sheet.html; ArrowLeft, ArrowRight, PageDown, Space:
    `location.pathname` unchanged.
  - `test_a_songbook_turns_by_page_keys_and_changes_songs_by_arrows` (D17 A): PageDown to the end of song 1 stays on
    song 1; `ArrowRight` opens song 2; autoscroll run to the end pauses there ("Paused · end of song") as today.
  - `test_the_harmonica_page_answers_the_same_keys`: its tab, Space starts, PageDown turns keeping two lines.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q -n 0 tests/test_viewer_keys.py`.

- [ ] **Step 3: Implement**

  screen.js `keys`: one `keydown` listener. Left alone: `e.defaultPrevented`, any of Alt, Ctrl, Meta, Shift, a text
  field with the focus (`input, textarea, select, [contenteditable]`), `busy()`. Space and Enter, but not on a
  control with the focus (`button, a[href], summary, [role=button], [tabindex]`, whose own activation they are):
  `preventDefault`, `toggle()`. PageDown and ArrowDown, PageUp and ArrowUp: `preventDefault`, `pause()`, then a turn,
  measured after the pause (the bar comes back with it): with `[top, bottom]` from `room()`, the lines wholly between
  them (`#sheet p, #sheet pre`, shown); with three or more, PageDown scrolls the second-last to `top` and PageUp the
  second to `bottom`; else by `max((bottom - top) / 2, bottom - top - KEPT * LINE * fontSize)` of `#sheet`; one
  `window.scrollTo(0, Math.round(…))`, no smooth scroll. ArrowLeft and ArrowRight are not the map's (book.js keeps
  them for a songbook), nor is anything a version line does.

  viewer.js: `screenKit.keys({ toggle: () => (scroll.state === "off" ? $("scroll") : go).click(),
  pause: pauseScroll, room, busy })`; `room()`: `bottom` is `innerHeight` less the bar's height while it isn't hidden
  (`bar.offsetHeight`, slid away or not, as scrolling back up brings it) where the bar sits at the foot, and above that
  the pill's top while it shows or a docked layer's; `top` is the bar's height where 5d made it the toolbar at the
  top, else 0; `busy()` as "What these stages take from 5a–5d" says. Its `SCROLL_KEYS` listener keeps `Home` and `End`
  alone (the map now handles Space and the four page keys: left in, it would pause a scroll that Space then resumes).
  harptab.js likewise, with its bar and pill, its `busy()` the focus inside `#sizes` or `#necks`.

- [ ] **Step 4: Run them and see them pass** — the new file, `tests/test_viewer_scroll.py`,
  `tests/test_viewer_songbook_browser.py`, `tests/test_viewer_harptab_browser.py`; the corpus written again;
  `:viewer:test`.

- [ ] **Step 5: Commit** — docs/usage.md: a "Keys and pedals" bullet after Auto-scroll (a Bluetooth page turner is a
  keyboard: Space or Enter starts and stops autoscroll; PageDown or ↓ turns a screen keeping two lines, PageUp or ↑
  back; any of them pauses a scroll; ← → change songs in a songbook; nothing while the settings, a card or a menu has
  the focus; no key changes the version); the harmonica tab's page paragraph names them too. AGENTS.md: **screen.js**
  holds the key map; a page key never navigates.
  `git add src/caracole/viewer tests docs/usage.md AGENTS.md` ·
  `git commit -m "feat(viewer): a key map for pedals: start and stop, turn a screen keeping two lines"`

#### Task 5f.5: The screen kept on for minutes after the last touch

**Files:**
- Modify: `src/caracole/viewer/screen.js` (`awake`, `minutes`, `setMinutes`, `carry`),
  `src/caracole/viewer/page.py` (`_CONTROLS`: the minutes' row), `src/caracole/viewer/viewer.js` (its `holdScreen`,
  `letScreenSleep` and visibility listener go; `screenKit.awake`; the row's wiring; `exportLink`),
  `src/caracole/viewer/harptab.js` (its wake lock goes), `src/caracole/viewer/book.js` (`SCREEN`),
  `tests/helpers/viewer_pages.py` (`WAKE_LOCK`, moved from test_viewer_scroll.py; `LONG_TIMERS`; `DENIED`)
- Test: `tests/test_viewer_awake.py` (create); `tests/test_viewer_scroll.py`
  (`test_the_screen_stays_on_while_it_scrolls` moves to the new file as below)

**Interfaces:**
- Consumes: 5d's More (`#panel`).
- Produces: `caracoleScreen.AWAKE` (`"caracole-viewer-awake"`), `minutes()` (0 to 60 by 5, 10 by default; the
  address's `awake=` read as the theme is), `setMinutes(n)` (kept in localStorage), `carry(params)` writes `awake=`
  while it isn't 10, `awake(moving)` → `sync()`, which the page calls whenever `moving()` may have changed. While a
  lock is held, `html[data-awake="1"]`. More's row `#awake-row`: `#awake-lab` "Keep the screen on", a stepper
  `#awake-down` (aria-label "Fewer minutes"), `#awake-at` ("Off", "10 min"), `#awake-up` ("More minutes").

- [ ] **Step 1: Write the failing tests** (`tests/test_viewer_awake.py`; each page opened with
  `before=[WAKE_LOCK, LONG_TIMERS]`; `LONG_TIMERS` holds back every `setTimeout` of 60 s or more, `skip(ms)` moves
  `performance.now()` on by `ms` and runs those now due, `clearTimeout` drops them; `wakeLog` as today's fake)

  - `test_the_screen_stays_on_ten_minutes_after_the_last_touch`: opened: `["request screen"]` and `data-awake`;
    `skip(9 * 60_000)`: still held; a tap on the words; `skip(9 * 60_000)`: held; `skip(61_000)`: `"release"` and
    no `data-awake`; a key: `"request screen"` again.
  - `test_autoscroll_keeps_it_on_past_the_minutes`: start, `skip(15 * 60_000)`: held; a tap pauses it;
    `skip(10 * 60_000 + 1_000)`: released.
  - `test_off_holds_it_only_while_it_scrolls`: `#awake=0`: no request on opening; ▶: a request; a pause: released at
    once.
  - `test_hidden_and_shown_again_it_asks_again`: the fake's `system()` lets go, then `visibilitychange` visible: a
    request (as today's test).
  - `test_a_denied_permission_never_stops_it`: with `DENIED` (`navigator.permissions.query` answering `denied`,
    counting its calls): the lock requested, the query never asked.
  - `test_the_minutes_are_a_setting_kept_for_every_page`: More: `#awake-at` "10 min"; `#awake-up` → "15 min",
    localStorage `"15"`, `awake=15` in the address; `#awake-down` three times → "Off"; down again stays "Off"; at 60
    up stays 60; another song's page: the same; a version link (`vAddress`) carries it; with `NO_STORAGE`, a
    songbook's next song carries it (`carryScreen`); Reset all leaves it.
  - `test_the_harmonica_page_keeps_it_on_as_long`: `#awake=5` on its address: released after `skip(5 * 60_000 + 1_000)`;
    ‹ Chord sheet's link carries `awake=5`.
  - `test_the_row_fits_a_320_px_phone`.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q -n 0 tests/test_viewer_awake.py`.

- [ ] **Step 3: Implement**

  screen.js `awake(moving)`: the time is `performance.now()` alone. Activity (`touchstart`, `pointerdown`,
  `keydown`, `wheel`, `scroll`: capture, passive; and the page shown again) sets the last touch to now and, minutes
  on, schedules one `setTimeout` for the moment they run out (cleared and set again on the next). Wanted: the page
  visible and (`moving()` or minutes on and within them). `sync()`: a lock asked when wanted and none held or asked,
  released when not wanted; never `navigator.permissions.query`. A lock let go by the browser (its `release` event)
  clears `data-awake`. viewer.js and harptab.js call `const awake = screenKit.awake(moving)` and `awake()` where they
  called `holdScreen` and `letScreenSleep`. The row in `_CONTROLS` after the reading switches and before the places to
  go (`#places`), drawn by viewer.js's `render` (`#awake-down` disabled at 0, `#awake-up` at 60); `exportLink`'s
  command deletes `awake` too. book.js: `SCREEN` gains `"awake"`.

- [ ] **Step 4: Run them and see them pass** — the new file, `tests/test_viewer_scroll.py`,
  `tests/test_viewer_panels.py`, `tests/test_viewer_songbook_browser.py`, `tests/test_viewer_harptab_browser.py`;
  the corpus written again (page.json's `_CONTROLS`); `nix develop ./android -c gradle -p android test`.

- [ ] **Step 5: Commit** — docs/usage.md: Auto-scroll's "with the screen kept on" becomes the rule (kept on while a
  sheet shows until 10 minutes after the last touch, key or scroll, always while it scrolls; More's Keep the screen on
  sets the minutes, Off to 60, kept for every page; `awake=15` in the address); the songbook and harmonica paragraphs
  say they keep it on alike. AGENTS.md: "Settings kept for every page at once" gains **Keeping the screen on**
  (`caracole-viewer-awake`, `awake=`, screen.js the one place a page asks for a wake lock, never through
  `navigator.permissions.query`, whose answer Android's WebView gets wrong).
  `git add src/caracole/viewer tests android docs/usage.md AGENTS.md` ·
  `git commit -m "feat(viewer): the screen stays on for minutes after the last touch, a setting in More"`

#### Task 5f.6: A pedal and the wake lock in the app's WebView

**Files:**
- Create: `android/app/src/androidTest/kotlin/io/github/danielhp95/caracole/PedalTest.kt`
- Modify: `android/app/src/main/kotlin/io/github/danielhp95/caracole/MainActivity.kt` (`Client`: `onPageFinished`),
  `android/scripts/device-test.sh` (`--app`'s classes and its header)

**Interfaces:**
- Consumes: 5f.4's key map, 5f.5's `html[data-awake]`; androidTest's `Pages` (`url`, `evaluate`, `waitUntil`) and
  PinchTest's way to a synced sheet (`-e server`).

- [ ] **Step 1: Write the failing test** — `PedalTest`, PinchTest's set-up (the copy synced from `-e server`, a
  sheet opened in MainActivity; skipped without `server`): after the page loads, `instrumentation.sendKeyDownUpSync(
  KeyEvent.KEYCODE_PAGE_DOWN)` moves `scrollY` past half the window; `KEYCODE_SPACE` shows `#pill` with `#go`
  "Start"; `document.documentElement.dataset.awake === "1"` within 5 s of the load; the same on the next page opened
  from the library (the focus survives a load).

- [ ] **Step 2: Run it and see it fail** — `android/scripts/device-test.sh PedalTest="$(mktemp -d)"` (the script
  makes a computer in the folder and names it to the class as `-e server`): the first key goes nowhere (the research's
  inference: a WebView not focused after a load).

- [ ] **Step 3: Implement** — `Client.onPageFinished(view, url)`: `view.requestFocus()`. device-test.sh's `--app`
  loop (`for name in EndToEndTest PinchTest …`) and its header gain PedalTest.

- [ ] **Step 4: Run it and see it pass** — the same command; `nix develop ./android -c gradle -p android test`.

- [ ] **Step 5: Commit** — AGENTS.md's `app/src/androidTest/` list gains `PedalTest`.
  `git add android AGENTS.md` · `git commit -m "fix(android): the WebView keeps the focus after a load, so a pedal's first press turns"`

#### Task 5f.7: Merge stage 5f

- [ ] On screen: autoscroll with the lit line on a song with timed lyrics, a pedal or a keyboard's PageDown on a
  phone-sized window and a laptop, the screen-on row; the app on the owner's phone (memory: wireless debugging,
  `install --user 0`) with a pedal if one is at hand.
- [ ] `nix develop -c pytest -q`; `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`
  leaves `git status` clean; `nix develop ./android -c gradle -p android test`; `nix flake check`;
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py`;
  `android/scripts/device-test.sh PedalTest="$(mktemp -d)" PinchTest="$(mktemp -d)"` (the WebView's keys, wake lock
  and text zoom).
- [ ] `git switch main && git merge --no-ff feat/sheet-5f-hands-free &&
  GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

#### Cases from the brief, where they are pinned

| Case | Tests |
|---|---|
| 1. From a file; a sandbox with no storage | 5e.2 `test_without_storage_…`, `test_a_songbook_carries_…`; 5f.5 `test_the_minutes_…` (NO_STORAGE songbook); every browser test here opens a `file:` page |
| 2. Chinese, long names | 5f.1 `test_traditional_lyrics_meet_…`; 5f.3 `test_a_chinese_sheet_lights_…` |
| 4. An instrument with no strings | 5e.4 `test_the_strip_draws_the_instrument_shown` (piano, harmonica) |
| 5. No timed lyrics; too few matches | 5f.1 `test_too_few_matches_…`; 5f.3 `test_no_timed_lyrics_or_too_few_…` |
| 6. Reduced motion; 320 px; on its side | 5f.3 reduced motion; 5e.2, 5e.3, 5f.5 at 320 px; 5e.4 and 5f.4 at 844×390 |
| 7. Harmonica, version page, songbook | 5e.3, 5f.4, 5f.5 (harmonica); 5e.2, 5f.1, 5f.4 (version page); 5e.2, 5e.4, 5f.4, 5f.5 (songbook) |
