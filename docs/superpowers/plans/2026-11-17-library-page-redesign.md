# The library page, redesigned: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the owner's approved redesign of the library page (index.html, caracole serve's `/`, the Android app's
page): slimmer phone rows, search that takes the phone screen, a Back that undoes what the page opens, progress as a
segmented bar with a fixed total, the laptop's list and card pane, labelled play chips with a mouse, a calmer page.

**Architecture:** Four lanes, each a branch from `main` in a worktree of its own, split by file so they rarely collide:
lane 1 the list page's own scripts and styles (six stages, merged one by one), lane 2 progress (Python, its Kotlin
port, the Journal), lane 3 the card and the play buttons (card.js, card.css), lane 4 Songbooks. Every lane is test
first, regenerates the conformance corpus in the commit that changes what it pins, and merges into `main` when the
whole suite, the corpus check and gradle pass.

**Tech Stack:** plain JavaScript and CSS inlined into the pages (library_assets/), Python 3.14 (caracole, pytest with
pytest-xdist, Chromium browser tests through tests/helpers/browser.py), Kotlin (the Android app's port, Gradle), Nix
dev shells.

**Spec:** `docs/superpowers/specs/2026-11-17-library-page-redesign-design.md` (approved 2026-11-17), its mockups in
`docs/superpowers/specs/2026-11-17-library-page-redesign/`, and the research behind it in
`.claude/handoff/ui-research-2026-11-17/reports/Library page UI UX research.md` (local).

## Global Constraints

- Nothing loaded from the network; inline scripts and styles allowed by hash; every element built with
  `createElement`/`textContent`, never `innerHTML`; the page works served by caracole serve and opened as a file, and
  in the Android app's WebView.
- Today's colours (accent `#b4441e` light, `#f0895c` dark, the wordmark in the accent), today's logo mark and the
  system font: unchanged.
- No bottom navigation bar, no card as a bottom sheet, no per-site result tabs, no trailing A–Z index, no virtualized
  list; nothing pinned over the list or a sheet.
- A change to `src/caracole/library_assets/`, `web/outcome.py`, `web/status.py` or the schema regenerates the corpus in
  the same commit (`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, run twice, then
  once without `CARACOLE_CORPUS`), and `nix develop ./android -c gradle -p android test` passes before the merge; a
  Kotlin test that breaks is followed in the same lane.
- Tests first; browser tests `@in_chromium`; one file `nix develop -c pytest -q -n 0 tests/<file>.py`; the whole suite
  `nix develop -c pytest -q` before every merge; `nix flake check` at each lane's or stage's merge.
- docs/usage.md and AGENTS.md change with behaviour, in the same commit; no Claude or AI attribution anywhere;
  conventional commits scoped by area.
- Breakpoints: phone layout under 720 px; the laptop's list and pane from 1200 px wide; touch sizes under
  `(pointer: coarse)`, chips otherwise.
- Sizes from the spec: artist band 34 px; a folded line about 64 px; play tiles 48 × 48 px, 8 px apart, letters 8 px;
  chips about 28 px tall; the list about 760 px beside a 400–480 px pane, one column of about 800 px under 1200 px;
  radii 4, 8, 12 and 999 px; up to five recently opened songs; nothing drawn for a request's first second.

## Review Focus

These are the inputs most likely to bite the owner that no single task's own feature tests would meet; each is pinned
by the task named.

1. **The page opened as a file** (no server, `history.pushState` refused by some browsers on `file:`): search mode, ←,
   the tabs' Back entry and the ⋯ menu still open and close, with no exception. Tasks 1a.4, 1c.2 and 3b.5 each carry a
   test with `history.pushState` made to throw.
2. **Chinese and long names** (茉莉花, 宋冬野 斑马斑马, a 60-character artist): bands, overlines, the card's sticky head
   and the laptop chips ellipsize and never push the key or a play button off the line. Tasks 1b.2, 1b.3, 1d.4 and
   3a.3.
3. **A library of one-song artists, and one artist of 300 songs**: folding, bands and the long-list containers (runs of
   40, groups over 50 cut) all right. Tasks 1b.3 and 1e.3.
4. **A blocked, turned-off or empty site in a search, and a search where every count is 0**: the count row's rules
   (a site's 0, a blocked one's too, folds into "0 on N more", its state in the tooltip, as the spec says), no row at
   all at 0. Task 1c.5.
5. **A request cancelled, interrupted, failed in its first second, or all of whose steps were skipped**: the fixed
   total, the frozen bar, Ready folding away, no bar for a sub-second job after a reload. Tasks 2.1, 2.2 and 2.6.

## Before the lanes

### Task 0: The spec and this plan on `main`

- [ ] **Step 1:** In the main checkout, `git switch main && git merge --no-ff design/library-page-redesign` (the spec,
  its mockups and this plan, committed on that branch). Expected: a merge commit, nothing else changed.
- [ ] **Step 2:** `nix develop -c pytest -q -m "not slow"` passes (docs only).
- [ ] **Step 3:** Push `main` as the owner pushes (`GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin
  main`). Every lane branches from this commit or later.

## Where the lanes meet

The planners of the four lanes raised these; they are settled here, and where a lane's own section below says
otherwise, this section wins.

1. **History.** Lane 1's rules (1a, 1c, "Interfaces these stages produce") are the page's: every `replaceState`
   passes `history.state`, never `null`; a script that pushes an entry pushes an object with a marker of its own;
   any entry pushed while `body.search-mode` is on also carries `search: (Number(history.state &&
   history.state.search) || 0) + 1`; a `popstate` handler acts only on its own marker; a `pushState` that throws falls
   back quietly. There is no shared `backEntry` helper: lane 1d's draft named one as a placeholder.
2. **Back closes the card's ⋯ menu: lane 3 (Task 3b.5), not lane 1.** The menu is card.js's. Task 1d.5 is dropped;
   its one guard, "opening a card adds no history entry, at 390 and 1280 px", moves into Task 1d.6's tests. The
   menu's entry is `{ caracoleMenu: n }` (n a serial), plus `search: (Number(history.state && history.state.search)
   || 0) + 1` in search mode as rule 1 says, never `search` spread from `history.state`; lane 1 never copies
   `caracoleMenu` into its own entries.
3. **The card's CSS seam.** Task 3a.1 moves into card.css the `.play`, `.line-plays` and `.foot` rules and filter.css's
   lit rule, deleting them from rows.css, library.css and filter.css (a named crossing); `.line-title > .line-plays`
   stays in rows.css as its one placement rule, and `.line-plays` stays a direct child of `.line-title` (lane 1b's
   folded grid depends on it). The opened line's box rules stay in card.css: Task 3b.4 keys
   `.line:not(.hit) > .line-panel` to `.line-panel.song-card` (the foot's rule is a plain `.foot` since 3a.1), and
   adds `:not(.selected)` to `.line:not(.hit):has(> .line-more[aria-expanded="true"])`, using the classes Task 1d.2
   and 1d.6 introduce (`song-card` on every song's panel, `selected` on a line whose card is in the pane). Lane 1
   styles `#card-pane` in library.css and never re-adds `.play` or `.foot` rules (test_library_assets.py guards it:
   outside card.css, `.play`, `.line-plays` and `.foot*` are named only by lane 1's placement rules, a selector
   ending `.line-title > .line-plays` in rows.css or library.css (1b.3's and 1b.4's folded grids), and its
   `#card-pane …` rules in library.css (1d.6's `#card-pane .foot-menu`)).
4. **Four radii.** Task 1f.1 defines `--radius-s: 4px; --radius-m: 8px; --radius-l: 12px; --radius-pill: 999px` in
   base.css. Lanes 2, 3 and 4 write `var(--radius-m, 8px)` and the like, so they hold before and after 1f lands:
   Task 2.8 brings requests.css's radii to the four and Task 4.1 songbooks.css's (`.pickbar` and `.selecting .pick`
   too); 3a.2, 3a.3 and 3b.6 write theirs as tokens with fallbacks; lane 2's bar segments have square ends (radius 0,
   allowed). 1f's radius test, `odd_radii(skip)`, counts rendered elements alone and leaves out what is inside an
   element its skip list matches; the last of 1f, lane 2, 3b and lane 4 to merge removes the skip list.
5. **Withdrawn** (the pre-flight scan's F20: the spec wins). A blocked site's 0 is a zero as the others are: it folds
   into "0 on N more", its state in the tooltip (Task 1c.5).
6. **Dead step CSS.** Lane 2 deletes `.line > .step-chips` and `.row > .step-chips` (rows.css) and
   `.progress .steps-over` (library.css) in Task 2.6, a named crossing; lane 1b's line grid keeps `.line > .progress`
   and `.line > .steps` spanning the whole line.
7. **The step list in the pane.** Lane 2's open-card list is `.line > .steps > ol.step-list`. Whichever of Tasks 1d.6
   and 2.6 merges second shows it for the selected line in the pane (moved into `#card-pane`, or the rule widened),
   with a test at 1280 px; both tasks carry that step, each doing it only when the other has merged.
8. **The phone tabs' assertion in `tests/test_requests_tab.py`** (lane 2's file) is changed by Task 1a.2, a named
   crossing.
9. **`replaceState(null, …)` elsewhere:** songbooks.js is lane 4's to fix (Task 4.1), requests.js lane 2's (Task 2.8),
   sync.js lane 1's (Task 1a.4): each passes `history.state`.
10. **Leftovers of the one-artist view in songbooks.css** (`.selecting` rules for the funnel, a `by` column): lane 4
    deletes them in Task 4.1, once Task 1b.1 has merged (else in Task 4.3's rebase).
11. **AGENTS.md's rule that a play button shows its sites' marks** becomes, in Task 3a.3: "on a touch screen, its
    sites' marks; with a mouse, its kind and its site in words".
12. **Room on a laptop's line for chips** (100–150 px each): Task 1d.6 sizes the title column and lets
    `.line-title > .line-plays` wrap below the title rather than push the key off the line.
13. **Lane 4 is removed** (the owner, 2026-11-17: "Remove the songbooks lane. I realized I don't need it"; the
    spec's Songbooks section says so). Tasks 4.1–4.3 are not built and no lane changes songbooks.js; wherever this
    plan names lane 4 or Task 4.3 (the merge tasks, "the last of 1f, lane 2, 3b and lane 4", the screenshots), read
    it without them. In their place:
    - rule 4: songbooks.css keeps its radii; 1f's radius test keeps `#songbooks` in its skip list for good, and the
      last of 1f, lane 2 and 3b to merge cuts the skip list to `("#songbooks",)` rather than emptying it;
    - rule 9: songbooks.js's `replaceState(null, …)` calls pass `history.state` all the same (one token each, no change
      to what the tab does), a named crossing of Task 1a.4's: a `null` there wipes tabs.js's `{ tab: 1 }` entry and
      1c's `search` count, so it is not harmless after all;
    - rule 10: Task 1b.1 deletes songbooks.css's one-artist leftovers itself (the `.selecting` rules naming
      `.filter-mark` or `.artist-only`, and the `by` column at ≥ 720 px), a named crossing, as the task that makes
      them dead;
    - lane 2's meeting point with songbooks.js (`showLine` keeps its signature) still holds: songbooks.js calls it
      as today.

**Merge order.** Lane 1's stages in order (1a, 1b, 1c, 1d, 1e, 1f), each from `main` after the one before merged.
Lanes 2, 3a and 4 any time. Lane 3b after 1d (its container queries and `song-card` keys depend on it). Whoever
merges second in any pair rebases and regenerates the corpus.

**Every merge task** (1a.5, 1b.5, 1c.8, 1d.8, 1e.5, 1f.4, 2.9, 3a.4, 3b.7, 4.3) runs the whole suite (`nix develop -c
pytest -q`), the corpus twice, `nix develop ./android -c gradle -p android test`, `nix flake check`, and
`CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` when the corpus moved; merges with
`git merge --no-ff`; then pushes main, `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`. Docs
change in the task that changes the behaviour; a merge task only checks them. The README's screenshots are retaken
once, in the merge task of whichever of lane 1 (1f.4), lane 2 (2.9), lane 3 (3b.7) and lane 4 (4.3) merges last.

## Calls the planners made where the spec was silent (the owner may overrule)

- ← empties the box as it leaves search (text in the box is what keeps search on); Escape on a laptop keeps today's
  behaviour; search mode starts on focus at every width, the masthead hides only under 720 px (1c.2, 1c.3).
- Artist bands and overlines both in the artist colour (`--artist`), as the laptop mockup shows (1b.2).
- Nothing found says "in the sites' indexes" alone when one of your songs matched (1c.6).
- "3 of 7" is the place of the step in hand; the server decides the first second, so a reload agrees (2.1, 2.2); a
  finished lookup keeps its list in the Journal (2.4).
- One drawer per tile, holding its downloads first, then one part per source, in place of today's chip per source
  (3b.3); a UG version named by what differs where UG's data has a label (3b.2).
- A songbook's Play opens its first song with a sheet, and also sits in an opened songbook's head (4.1, 4.2).
- The card's own compact head sticks, not the line's, which a CSS grid can't (1d.4); the pane clears when a search or
  filter hides its line (1d.6).

---

## Lane 1 · The list page: stages 1a, 1b, 1c

Design: `docs/superpowers/specs/2026-11-17-library-page-redesign-design.md` (branch `design/library-page-redesign`; a lane
branch from `main` doesn't have it until that branch merges: read it from the design branch). Mockups:
`phone-navigation.html` (A), `phone-rows.html` (A1), `search.html` (A).

Worktree: `git worktree add ../caracole-lane1 -b feat/library-1a-navigation main`. Each stage is its own branch from
`main` after the previous stage merged (`git -C ../caracole-lane1 switch -c feat/library-1b-list main`, then
`feat/library-1c-search`). All paths below are relative to that worktree.

Commands used throughout:

- one test: `nix develop -c pytest -q -n 0 tests/<file>.py::<test>`
- the corpus file library_assets feeds (the one generator that reads them, `rg -l library_assets
  tests/test_conformance_*.py`): `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_library_page.py`
- the whole corpus, at each merge, twice: `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`

Every task that edits a file of `src/caracole/library_assets/` regenerates `tests/test_conformance_library_page.py`'s
vectors and `git add`s `tests/conformance/` in the same commit (the page's hashes and the phone's page change with any
byte of those files).

### Interfaces these stages produce (for 1d–1f, lane 2, lane 3)

History (1a, 1c):

- **Every `history.replaceState` in library.js and tabs.js passes `history.state`**, never `null`, so an entry's marker
  survives the list's and the tabs' own address writes. A script that pushes an entry pushes an object with a marker.
- tabs.js pushes one entry when Library is left for another tab (`pushState({ tab: 1 }, …)`, rule 1's marker, plus an
  in-memory flag, `fromLibrary`), replaces between the other tabs, and the Library tab pressed while `fromLibrary` is
  set is `history.back()`. A tab change never touches `history.state.search`.
- Search mode's entries carry `{ search: n }` (n = how many entries since search began: 1 for the entry pushed on
  entering search from an empty box, +1 for each `searchFor` push). **Any entry pushed while `body.search-mode` is on
  carries `search: (Number(history.state && history.state.search) || 0) + 1` beside its own marker**, so ← can take
  every one back with `history.go(-n)`: lane 3's card ⋯ menu entry (design: "adds a history entry, so Back closes it")
  is `{ caracoleMenu: n, search: … }` in search and `{ caracoleMenu: n }` out of it (n a serial, `search` never spread
  from `history.state`), and never `replaceState(null, …)`; 1d's laptop pane pushes nothing. tabs.js's push is
  `{ tab: 1 }`, with rule 1's `search` beside it while `body.search-mode` is on.
- songbooks.js (lane 4), requests.js (lane 2) and sync.js call `replaceState(null, …)` today. Their entries are never
  search entries, so this is harmless; still, Tasks 4.1 (songbooks.js line 89), 2.8 (requests.js line 293) and 1a.4
  (sync.js line 1129) each make theirs pass `history.state` ("Where the lanes meet" 9).

Masthead and search mode (1a, 1c):

- `WebControls.in_app: bool = False` (Python, library_page.py) and `ServerControls.inApp: Boolean = false` (Kotlin,
  server/page/LibraryPage.kt), set `true` by the phone's `Assembly.controls()`: the page then has no `.libname` at all.
  Vector key: `controls.in_app` in `vectors/web/library_page.json`'s cases.
- Phone masthead grid (`max-width: 719px`): areas `"app name tabs" "sum sum sum"`; `.masthead.lib .tabs` scrolls
  sideways (`overflow-x: auto`) whatever the number of tabs; each `.tab` ≥ 48 px tall on `pointer: coarse`.
- `body.search-mode`: set while the box is focused or holds text, until ←, Back or Escape-in-an-empty-box. Under 720 px
  it hides `.masthead.lib` (`visibility: hidden`, `margin-top: calc(-1 * var(--mast-h))`, `--mast-h` set by library.js
  on `.masthead.lib` as search starts). 1d's pane and 1f's calmer page keep both selectors working.
- `#leave` (body.html, in `.field` before `#q`): the ←, `aria-label="Back to your songs"`, shown in search mode at every
  width. There is no other "Back to your songs" control.
- library.js functions (inside its closure, same lane): `enterSearch()`, `leaveSearch()` (box empty, results closed,
  focus out, mode off, address replaced), `backFromSearch()` (#leave's: `history.go(-depth)` or `leaveSearch()`),
  `searchFor(name)` (served or from a file: the box filled with the name, one `{ search: n+1 }` entry pushed).
- Recently opened: localStorage `caracole-library-recent` (JSON array, ≤ 5, newest first, one entry a song:
  `{ identity, href, said }`), drawn in `#recent` (body.html, in `.searchbar` after `.bar-said`); `rememberOpened(line,
  link)` in library.js records it from any click on `a[href]` inside an `article.line[data-id]` (and its `.line-panel`).
  Task 1d.6 makes the listener find a link's line through `itemOf(node)`, so a link in the pane is the selected line's.

The list (1b):

- No `state.artist`, no `#artist` tag, no `artistOnly`, `artistFilter`, `.artist-pair`, `.filter-mark` anywhere.
  `#artist=KEY` and `#by=NAME` are read once as the name's tap (the box filled with the name; served, the sites searched
  too) and the page writes `#q=…` in their place.
- `rows.js`: `artistOf(name, onSearch, cls)` (two arguments of meaning: a function makes `button.artist.artist-search`,
  else a `span`); `caracoleRows(icons, does)` with `does.searchArtist(name)`: library.js passes
  `{ searchArtist: (name) => searchFor(name) }`, and `indexLine`'s artist is that button.
- `artistGroup(artist, items, counts)`: `artist = { key, name, meant, search, tail }`; `tail` (a Node or null) is
  appended by artistGroup after the lines. The group **folds** iff `items.length === 1 && !artist.meant &&
  !artist.tail`: `section.artist.folded`, its `h2.artist-title` visually hidden and plain text (`span.artist-name`,
  `span.artist-counts`), the line's own `.line-by` (the artist button) shown as an overline.
- A band: `section.artist:not(.folded) > h2.artist-title`, `height: var(--band-h)` (34 px), the name
  (`button.artist.artist-search` or `span.artist-name`) ellipsized, `span.artist-counts` right-aligned, its textContent
  as today (`" · yours 2"`, `" · yours 1 · UG 3"`), what shows, in a `span` of its own: `2` in the list, `yours 1 · UG
  3` in results (a `span.visually-hidden` before it holds the rest).
- Folded lines are by context, never a class on the line (lines are cached and move between list and results):
  `section.artist.folded .line` and `section.flat .line` (descendant: 1e may wrap runs of flat lines). On a phone their
  grid is `"meta plays act key more" "name plays act key more"` with `.line-title { display: contents }`, so lane 3's
  `.line-plays` **must stay a direct child of `.line-title`** and its 48 px hit areas fit the line's `--fold-h` (64 px).
- Tokens on `.list, #found`: `--band-h: 34px`, `--fold-h: 64px` (a folded line's `min-height` on `pointer: coarse`), for
  1e's `contain-intrinsic-size`.
- Tap targets: on `pointer: coarse` every control ≥ 44 px as today but the band's and the overline's artist button
  (`.artist-title button.artist`, `button.artist.line-by`), ≥ 24 px. `tests/helpers/targets.py`'s
  `small_targets(exempt="", least=44)` measures either floor; `ARTIST_NAMES = ".artist-title button.artist,
  button.artist.line-by"` is the exemption the 44 px checks use.

Search (1c, shared with caracole serve's lookup page):

- rows.js `countMarks(data, yours, found)` returns `[]` when every count is 0; else yours first, the sites with a count
  > 0 in `looked` order, then at most one `li.count-mark.rest` (`data-source="rest"`, `data-n="0"`). Each site mark holds
  `span.count-name` (the site's name in full, shown from 720 px unless the list has class `short`).
- rows.js `fitCounts(list)`: after drawing, sets `short` on the list when its marks with names shown take more than one
  line; refits on the list's resize.
- rows.js `drawCountMarks(list, data, yours, found)`: the row drawn for both pages (library.js `drawCounts`,
  lookup_page.py `showCounts`): `list.replaceChildren(...countMarks(…))`, `list.hidden` when there are none,
  `fitCounts(list)`; it returns the marks.
- rows.js `countsSaid(data, yours, found)`: no site with a count says `"nothing in the sites' indexes"`, nothing at all
  `"Nothing in your songs or the sites' indexes"`.
- rows.js `nothingFound(data, query, does)`: `does.yours` (a number; > 0 drops "your songs or" from its words); its
  band `h2.miss-band` says `Nothing for “QUERY” in your songs or the sites' indexes`; its line's `h3` is the query as
  typed (no quotes, normal text); its Request `.btn.small.primary.miss-request`, filled.

### Stage 1a · Navigation and Back

#### Task 1a.1: The app's page draws no library-name row

**Files:**
- Modify: `src/caracole/library_page.py` (`WebControls`: new field `in_app: bool = False` and its line in the docstring;
  `assemble_page`: `__LIBRARY__` → `""` when `controls is not None and controls.in_app`)
- Modify: `tests/test_conformance_library_page.py` (`CASES`, `phone_page`, `library_page_json`'s case names,
  `test_the_cases_cover_what_the_page_writes_otherwise`, `test_the_phones_page_has_the_requests_tab…`,
  `test_the_phones_own_data_shapes_draw_with_no_script_error`)
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/page/LibraryPage.kt` (`ServerControls`:
  `val inApp: Boolean = false`; `served`: `__LIBRARY__` → `""` when `controls.inApp`)
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/Assembly.kt` (`controls()`: `inApp = true`)
- Modify: `docs/usage.md` (the library page's header paragraph, ~line 2366: in the Android app no name row, its own
  bar names the library), `AGENTS.md` ("#### library_name.py" or the page's header line: `WebControls.in_app`)
- Test: `tests/test_library_name_pages.py`, `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/page/LibraryPageTest.kt`,
  `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/PhoneServesTest.kt`

**Interfaces:**
- Produces: `WebControls.in_app`, `ServerControls.inApp`, the vector's `controls.in_app`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_library_name_pages.py
def test_the_apps_page_draws_no_name_row_and_its_title_still_names_the_library(conn, cfg):
    # The Android app's own bar says "Phone · caracole · Tabs": its page draws no row for it.
    from caracole.library_page import assemble_page
    app = WebControls(csrf="tok", badge="Phone", in_app=True)
    html = assemble_page({"songs": []}, app, problem=None, library_name="Tabs")
    assert 'class="libname"' not in html
    assert "<title>Phone · caracole · Tabs</title>" in html
    assert WebControls(csrf="tok").in_app is False  # caracole serve never sets it
```

```python
# tests/test_conformance_library_page.py: every case says it; the first, kept whole, is the app's.
CASES = (
    ("empty", {"csrf": CSRF, "badge": "Phone", "sync": "sheet", "active": 0, "in_app": True}),
    ("empty", {"csrf": CSRF, "badge": "Phone", "sync": None, "active": 0, "in_app": False}),
    ("chinese", {"csrf": CSRF, "badge": "Phone", "sync": None, "active": 2, "in_app": True}),
    ("chinese", {"csrf": CSRF, "badge": "Phone", "sync": "sheet", "active": 2, "in_app": True}),
    ("chinese", {"csrf": CSRF, "badge": None, "sync": "sheet", "active": 2, "in_app": False}),
    ("chinese", {"csrf": CSRF, "badge": None, "sync": "tab", "active": 2, "in_app": False}),
)
# in test_the_cases_cover_what_the_page_writes_otherwise:
assert {controls["in_app"] for _, controls in CASES} == {True, False} and CASES[0][1]["in_app"] is True
```

`phone_page` builds `WebControls(..., in_app=controls["in_app"])`; the case name gains `, app {in_app}`.

```kotlin
// LibraryPageTest.kt: controls(of) reads it
inApp = of.getValue("in_app").jsonPrimitive.boolean,
// and
@Test fun `the app's page has no library-name row and keeps its title`() {
    val made = page.served(mirroredData(emptyList()), ServerControls("tok", inApp = true), "Tabs")
    assertFalse("class=\"libname\"" in made)
    assertTrue("<title>Phone · caracole · Tabs</title>" in made)
}
// PhoneServesTest.kt, as aSongAReviewMustComeFirstForIsNotFetchableOnThePage builds its phone: the page
// Assembly serves at "/" holds no `class="libname"`, and its <title> starts "Phone · caracole".
@Test fun thePhonesPageDrawsNoLibraryNameRow()
```

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q -n 0 tests/test_library_name_pages.py::test_the_apps_page_draws_no_name_row_and_its_title_still_names_the_library`
  (TypeError: unexpected keyword `in_app`).
- [ ] **Step 3: Implement** — the field, the one `replace` in each `assemble_page`/`served`, `inApp = true` in
  `Assembly.controls()`; the docs above. Regenerate `tests/test_conformance_library_page.py`'s vectors.
- [ ] **Step 4: Run them and see them pass** — the Python test, `nix develop -c pytest -q -n 0
  tests/test_conformance_library_page.py`, then `nix develop ./android -c gradle -p android :server:test --tests
  '*LibraryPageTest' --tests '*PhoneServesTest' --tests '*PageRoutesTest'`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_page.py tests/test_library_name_pages.py
  tests/test_conformance_library_page.py tests/conformance android/server docs/usage.md AGENTS.md` ·
  `feat(android): the app's library page draws no library-name row, its own bar names the library`

#### Task 1a.2: Larger tabs on a phone, a row that scrolls sideways

**Files:**
- Modify: `src/caracole/library_assets/library-screens.css` (coarse: `.tab { min-height: 48px }` in place of 44)
- Modify: `src/caracole/library_assets/library.css` (one phone block for the masthead, `@media (max-width: 719px)`:
  `.masthead.lib .tabs { overflow: auto hidden; overscroll-behavior-x: contain; scrollbar-width: none; padding-bottom:
  1px }`, its `::-webkit-scrollbar { display: none }`, `.masthead.lib .tab { padding: 0 10px; font-size: .9rem; gap: 4px
  }`)
- Modify: `src/caracole/library_assets/filter.css` (move its `.masthead.lib` phone rules into library.css's phone block;
  drop its `.masthead.lib .tab { padding: 0 4px; font-size: .86rem }`)
- Modify: `src/caracole/library_assets/sync.css` (drop `.masthead.lib .tabs:has(#tab-sync)`'s scrolling and its `.tab {
  padding: 0 3px; font-size: .84rem }`, now every tab row's; keep the 380 px rule)
- Modify: `src/caracole/library_assets/tabs.js` (`show`: the chosen tab scrolled into the row's view, the row only)
- Modify: `docs/usage.md` (the library page's header paragraph, ~line 2366: "On a phone the tabs fit beside the mark"
  → each tab a thumb's 48 px, the row scrolling sideways when they don't fit)
- Test: `tests/test_library_tabs.py` (new), `tests/test_requests_tab.py`
  (`test_the_tab_draws_every_request_and_fits_a_phone_with_five_tabs_in_light_and_dark`: lane 2's file, this one
  assertion block only)

**Interfaces:**
- Produces: `.tab` ≥ 48 px on coarse; `.masthead.lib .tabs` scrolls; tabs.js keeps the chosen tab in the row's view.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_library_tabs.py — tabs.js and the masthead's tab row, in Chromium.
pytestmark = CHROMIUM_MARKS
TABS = """(() => { const row = document.querySelector('.masthead .tabs');
  return { row: [row.scrollWidth, row.clientWidth, getComputedStyle(row).overflowX, row.getBoundingClientRect().left,
                 row.getBoundingClientRect().right],
    tabs: [...row.querySelectorAll('[role=tab]')].map((t) => { const r = t.getBoundingClientRect();
      return [t.id, r.height, parseFloat(getComputedStyle(t).paddingLeft), r.left, r.right, Math.round(r.top)]; }),
    page: document.documentElement.scrollWidth <= innerWidth }; })()"""

@pytest.mark.parametrize("width", [320, 390])
@pytest.mark.parametrize("sync", ["tab", None])  # five tabs (caracole serve's, Share last), or four
def test_on_a_phone_each_tab_is_48px_tall_and_a_row_too_wide_scrolls_on_its_own(conn, cfg, tmp_path, width, sync):
    # served markup (WebControls(csrf="tok", active=1, sync=sync)) written to the library, opened in
    # Browser(width=width, height=844, mobile=True), pointer coarse (assert matchMedia first)
    seen = phone.js(TABS)
    assert all(h >= 48 and pad >= 10 for _, h, pad, *_ in seen["tabs"]), seen
    assert len({top for *_, top in seen["tabs"]}) == 1 and seen["page"], seen  # one row; the page never scrolls sideways
    assert seen["row"][2] == "auto"
    if sync == "tab":
        assert seen["row"][0] > seen["row"][1]  # five don't fit: the row scrolls
        phone.js("window.caracoleTabs.show('sync')")  # the last, past the row's edge: chosen, it comes into view
        left, right = phone.js("(() => { const r = document.getElementById('tab-sync').getBoundingClientRect(); "
                               "return [r.left, r.right]; })()")
        assert seen["row"][3] - 0.5 <= left and right <= seen["row"][4] + 0.5
```

In `test_the_tab_draws_every_request_and_fits_a_phone_with_five_tabs_in_light_and_dark`, at 390 the five tabs are one
row with the page not scrolling sideways (`five["wide"] <= shown["page"]` stays); the assertion
`tabs[-1][2] <= shown["edge"]` holds at 1280 alone.

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q -n 0 tests/test_library_tabs.py` (heights 44,
  padding 3–4 px, four tabs' row `overflow-x: visible`).
- [ ] **Step 3: Implement** — the CSS above. In tabs.js `show`, after the panels: when `list.scrollWidth >
  list.clientWidth`, set `list.scrollLeft` so the chosen tab is wholly in view (`tab.offsetLeft` against
  `list.scrollLeft` and `list.clientWidth`; never `scrollIntoView`, which would move the page). docs/usage.md as
  above. Regenerate the corpus file.
- [ ] **Step 4: Run it and see it pass** — the new file, `tests/test_requests_tab.py`, `tests/test_sync_sheet.py -k tab`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests/test_library_tabs.py tests/test_requests_tab.py
  tests/conformance docs/usage.md` · `feat(library): a thumb's tabs on a phone, the row scrolling sideways when they
  don't fit`

#### Task 1a.3: A badge in a phone browser is a pill in the tab row

**Files:**
- Modify: `src/caracole/library_assets/library.css` (the phone block: `grid-template-columns: auto auto minmax(0, 1fr);
  grid-template-areas: "app name tabs" "sum sum sum"`; `.masthead.lib .libname` visually hidden unless it `:has(.scratch)`,
  then static with its `.name` visually hidden and `.scratch` at `font-size: .62rem; padding: 0 6px; line-height: 1.6`;
  drop the `"name name"` row)
- Modify: `src/caracole/library_assets/sync.css` (its below-380 px rule, five tabs: `grid-template-columns: auto
  minmax(0, 1fr)`, as the phone grid now has three columns; `.masthead.lib:has(#tab-sync)`'s `"app sum" "tabs tabs"`
  stays; `:has(.scratch)`'s `"app name" "tabs tabs" "sum sum"`, which puts the badge beside the mark, is replaced by
  `"app sum" "name tabs"`, so the pill sits in the tab row, before the tabs)
- Modify: `docs/usage.md` (the library page's header paragraph, ~line 2366: a badge a pill in the tab row)
- Test: `tests/test_library_name_pages.py`
  (`test_on_a_phone_the_badge_shows_under_the_bar_and_the_usual_library_keeps_one_bar` → renamed
  `test_on_a_phone_the_badge_is_a_pill_in_the_tab_row_and_the_usual_library_shows_none`; `library_page(conn, cfg,
  badge=None, sync=None)`, its `sync` passed to `WebControls`)

**Interfaces:**
- Produces: phone masthead areas `"app name tabs" "sum sum sum"`; below 380 px with the Sync tab, `"app sum" "name
  tabs"` when badged.

- [ ] **Step 1: Write the failing test** — `LOOK` and `look` as they are; parametrize `size` over `(390, 844)` and
  `(320, 640)`, and `sync` over `None` (four tabs) and `"tab"` (caracole serve's page with the Sync tab, five tabs:
  at 320 px its below-380 px rule is the one tested), each `library_page(...)` call passing `sync=sync`:

```python
usual = look(library_page(conn, cfg), tmp_path, size, scheme)
assert usual["fits"] and usual["badge"] is None and usual["name"] is None, usual
badged = look(library_page(conn, cfg, "Demo"), tmp_path, size, scheme)
mid = badged["badge"][1] + badged["badge"][3] / 2
assert badged["tabs"][1] <= mid <= badged["tabs"][1] + badged["tabs"][3], badged  # in the tab row
assert badged["badge"][3] <= 22 and badged["name"] is None and badged["fits"], badged  # a pill; the name in the title
assert badged["first"] <= usual["first"] + 1, badged  # no row of its own
assert badged["colour"] != badged["background"], badged
```

- [ ] **Step 2: Run it and see it fail** — the pill is a row of its own today (`first` 40 px lower); at 320 px with
  the Sync tab, beside the mark, the tabs on a row of their own.
- [ ] **Step 3: Implement** — the grid and the pill's rules above, sync.css's below-380 px areas; docs/usage.md;
  regenerate the corpus file.
- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q -n 0 tests/test_library_name_pages.py
  tests/test_library_tabs.py`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests/test_library_name_pages.py tests/conformance
  docs/usage.md` · `feat(library): a Demo or Scratch badge on a phone is a pill in the tab row`

#### Task 1a.4: Leaving Library is a step Back returns from

**Files:**
- Modify: `src/caracole/library_assets/tabs.js` (`save(how)`, `show`'s `push`/`pop`/`load` options, the Library tab and
  its keys, `popstate`)
- Modify: `src/caracole/library_assets/library.js` (`save`: `history.replaceState(history.state, …)`)
- Modify: `src/caracole/library_assets/sync.js` (line 1129: `history.replaceState(history.state, "", "#" +
  params.toString())` in place of `null`, "Where the lanes meet" 9)
- Modify: `src/caracole/library_assets/__init__.py` (tabs.js's paragraph: Back)
- Modify: `docs/usage.md` (the library page's header paragraph, ~line 2366: Back from Songbooks, Sites, Journal or
  Share returns to Library, the other tabs replacing one another), `AGENTS.md` ("Songs gone, and the page's tabs":
  the Back rule, `fromLibrary`, tabs.js's `{ tab: 1 }` entry, every replace passing `history.state`; "##### The Sync
  tab and its sheet" untouched)
- Test: `tests/test_library_tabs.py`

**Interfaces:**
- Consumes: 1a.2's tabs.js.
- Produces: the history rules at the top (`fromLibrary`, the `{ tab: 1 }` entry, `history.state` preserved by every
  replace).

- [ ] **Step 1: Write the failing tests**

```python
CURRENT = "window.caracoleTabs.current()"

@pytest.mark.parametrize("served", [True, False])  # the served markup (Journal) or the plain file (three tabs)
def test_leaving_library_is_one_step_back_and_the_other_tabs_replace_it(conn, cfg, tmp_path, served):
    page.open(url + "#sort=title")
    n = page.js("history.length")
    page.click("#tab-sites")
    assert page.wait(f"{CURRENT} === 'sites'") and page.js("history.length") == n + 1
    assert page.js("history.state && history.state.tab") == 1  # rule 1's marker
    assert page.js("[...new URLSearchParams(location.hash.slice(1))].sort().join()") == "sort,title,tab,sites"
    page.click("#tab-songbooks")  # between other tabs: replaced
    assert page.wait(f"{CURRENT} === 'songbooks'") and page.js("history.length") == n + 1
    page.js("history.back()")
    assert page.wait(f"{CURRENT} === 'library'") and page.js("location.hash") == "#sort=title"
    assert page.js("document.querySelector('#list section.flat') !== null")  # the list as its address had it
    page.click("#tab-sites")
    page.click("#tab-library")  # Library pressed: the step taken back, no step added
    assert page.wait(f"{CURRENT} === 'library'") and page.js("history.length") == n + 1
    page.js("history.back()")  # nothing of the page's left to go back to: the page before it, or none
    assert page.wait("document.readyState === 'complete'")

def test_the_tabs_keys_leave_library_with_a_step_and_come_back_with_it(...):
    # focus #tab-library, ArrowRight (Songbooks: +1), ArrowRight (Sites: replaced), Home: Library, history.back()'d,
    # the focus on #tab-library once it shows
def test_an_address_that_names_a_tab_opens_it_with_no_step(...):
    # open url + "#tab=sites": Sites shows, history.length as the open left it
def test_where_the_browser_refuses_a_step_the_tabs_change_all_the_same(...):  # case 1: a file:// browser's refusal
    page.js("window.errors = []; addEventListener('error', (e) => errors.push(String(e.message)));"
            "history.pushState = () => { throw new DOMException('denied', 'SecurityError'); }")
    page.click("#tab-sites")
    assert page.wait(f"{CURRENT} === 'sites'") and page.js("location.hash") == "#tab=sites"
    assert page.js("errors") == []
```

- [ ] **Step 2: Run them and see them fail** — `history.length` stays `n` (tabs.js only replaces).
- [ ] **Step 3: Implement** — `save(how)`: `"push"` tries `history.pushState({ tab: 1 }, "", url)` (with rule 1's
  `search: (Number(history.state && history.state.search) || 0) + 1` beside `tab` while `body.search-mode` is on, a
  class 1c.2 brings) and sets `fromLibrary = true`, falling back to `replaceState` when it throws; otherwise
  `replaceState(history.state, "", url)`. `show(name, {focus, words, pop, load})`: push when `from === first && to !==
  first && !pop && !load`, else replace. The Library tab
  (click, or the tablist's keys landing on it) while `fromLibrary`: `history.back()` and nothing else, with the focus
  owed to the tab when a key asked (`refocus`); `popstate` clears `fromLibrary`, then shows the address's tab with `{
  pop: true, focus: refocus }`. In library.js `save` and sync.js's line 1129, pass `history.state`. The docs above.
  Regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass** — `nix develop -c pytest -q -n 0 tests/test_library_tabs.py
  tests/test_web_server.py -k keeps_its_settings tests/test_web_page_search.py -k back tests/test_sync_sheet.py`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests/test_library_tabs.py tests/conformance
  docs/usage.md AGENTS.md` · `feat(library): Back from another tab returns to Library`

#### Task 1a.5: Merge stage 1a

**Files:**
- Check (written by the tasks that changed the behaviour: 1a.1 to 1a.4): `docs/usage.md` (the library page's header
  paragraph, ~line 2366: each tab a thumb's 48 px, the row scrolling sideways when they don't fit; a badge a pill in
  the tab row; in the Android app no name row; Back from Songbooks, Sites, Journal or Share returns to Library, the
  other tabs replacing one another), `AGENTS.md` ("Songs gone, and the page's tabs": the Back rule, `fromLibrary`,
  every replace passing `history.state`; `WebControls.in_app`)

- [ ] **Step 1** — `nix develop -c pytest -q` (whole suite) and the whole corpus twice; `git status` shows no vector
  left changed after the second run.
- [ ] **Step 2** — `nix develop ./android -c gradle -p android test`;
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (android/ was touched, the corpus
  moved); `nix flake check`.
- [ ] **Step 3** — check the docs above against what the stage does; a gap goes into a `docs:` commit here, and is
  named in the merge's report.
- [ ] **Step 4** — look at it on screen: `caracole serve` on a phone-width window and in the app (adb), Back from
  Sites, a Scratch badge.
- [ ] **Step 5** — `git switch main && git merge --no-ff feat/library-1a-navigation`, then push main:
  `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

### Stage 1b · The phone list

#### Task 1b.1: No funnel and no one-artist view: an artist's name searches, served or from a file

**Files:**
- Modify: `src/caracole/library_assets/rows.js` (delete `artistFilter`, `artistOnly` and their export; `artistOf(name,
  onSearch, cls)`; `denseLine`/`resultRow` pass `r.onSearch` alone; `caracoleRows`'s header comment)
- Modify: `src/caracole/library_assets/library.js` (delete `state.artist`, `setArtist`, `artistChip` and its listener,
  the artist parts of `render`'s filter, `filtered`, `clearFilters`, `filtersSaid`, `kept`, `keptSaid`, `drawTags`,
  `save`; `drawTags` puts tags before `clearTags`; `lineFor`: `onSearch: () => searchFor(String(s.artist))`, no
  `onArtist`; `artistGroup`: the name is `artistSearch(name, () => searchFor(name))` wherever `name && a.search !==
  false`, no `only`; `searchFor` with no `server` check anywhere it is called; `addressed`: `#by=` and `#artist=` below;
  `cameBy` also for `artist`; `caracoleRows(ICONS, { searchArtist: (name) => searchFor(name) })`)
- Modify: `src/caracole/library_assets/body.html` (delete `<button … class="tag person" id="artist" hidden>`)
- Modify: `src/caracole/library_assets/rows.css` (delete `.filter-mark`, `.artist-pair`, `button.artist-only` rules;
  coarse `button.artist` alone), `library.css` (delete `.artist-title .filter-mark`, `.artist-title button.artist-only`
  rules)
- Modify: `src/caracole/library_page.py` (module docstring, ~line 60: the funnel's paragraph)
- Modify: `docs/usage.md` (~line 2513, the artist's name: no funnel; a name searches for the artist, served or from a
  file, and `#by=`/`#artist=` do the same; the tags no longer have "by Queen ×"), `AGENTS.md` ("##### The library
  page's list": "An artist's name" drops the funnel and `artistFilter`; "##### Searching from the pages": "Your songs
  there keep to the Filter panel's filters" without the artist's tag)
- Test: `tests/test_library_page.py`, `tests/test_library_filter.py`, `tests/test_web_page_search.py`,
  `tests/test_library_page_songbooks.py` (`LINE_TARGETS`' `funnel`)

**Interfaces:**
- Produces: `searchFor(name)` from a file; `artistOf(name, onSearch, cls)`; `caracoleRows(icons, { searchArtist })`;
  `#artist=`/`#by=` read as the tap.

- [ ] **Step 1: Write the failing tests** — find every test of the funnel or the view: `rg -n
  "artist-only|artistOnly|filter-mark|artistFilter|artist-pair|#artist|artist=|getElementById\(.artist.\)|tag.person"
  tests/`. Rewrite them to these, deleting what pinned the view itself (`test_the_artist_filter_is_a_tag`,
  `test_back_after_an_artists_name_and_its_funnel_brings_the_whole_address_again`, the funnel half of
  `test_an_artists_name_in_your_list_searches_for_them_and_its_funnel_shows_their_songs_alone`, the artist half of
  `test_your_songs_among_the_results_keep_to_the_status_buttons_and_the_artist_and_the_results_say_so`):

```python
# test_library_page.py (from a file): replaces test_an_artists_name_shows_that_artist_alone_not_every_song_with_the_word
def test_from_a_file_an_artists_name_puts_them_in_the_box_and_searches_your_songs(conn, cfg, driven):
    # Queen ×2, ABBA "Dancing Queen", Queens of the Stone Age; the file, in Browser
    n = driven.js("history.length")
    driven.click('#list section.artist[data-artist="queen"] h2 button.artist')
    assert driven.wait("document.getElementById('q').value === 'Queen'")
    assert driven.js("location.hash") == "#q=Queen" and driven.js("history.length") == n + 1
    assert {"Bohemian Rhapsody", "Don't Stop Me Now"} <= set(driven.js(SHOWN_TITLES))  # and what else "Queen" finds
    assert driven.js("document.querySelector('#artist, .artist-only, .filter-mark, .artist-pair') === null")
    assert driven.js("document.activeElement.id") == "q"
    driven.js("history.back()")  # the step before the search
    assert driven.wait("document.getElementById('q').value === ''")

@pytest.mark.parametrize("address,q", [("#by=Queen", "Queen"), ("#by=queen", "queen"), ("#by=%E5%AE%8B%E5%86%AC%E9%87%8E",
                         "宋冬野"), ("#artist=queen", "Queen"), ("#artist=song-dong-ye", "宋冬野")])
def test_from_a_file_an_artist_a_sheet_links_to_is_searched_for_in_your_songs(conn, cfg, tmp_path, address, q):
    # SHOWN_NOW as it is but no `chip`: now["q"] == q, now["hash"] == "#" + urlencode({"q": q}), now["results"] is
    # False, and the artist's titles among now["titles"]
```

```python
# test_web_page_search.py (served)
def test_an_old_artist_address_searches_for_them_as_their_name_does(cfg, live, browser):
    # library C Tangana "Demasiadas Mujeres"; sites as test_an_artists_name_in_your_list_… has them
    browser.open(base + "#artist=c-tangana")
    assert browser.wait("document.getElementById('found').dataset.query === 'C Tangana'")
    assert browser.js("location.hash") == "#q=C+Tangana&all=1"
```

`test_from_a_file_a_sheets_artist_opens_their_songs_and_back_returns_to_the_sheet` keeps its walk, asserting `q ===
'Queen'` and `location.hash === '#q=Queen'`; `test_a_lines_menu_opens_and_closes_and_its_artists_name_shows_their_songs`
asserts `#q=Radiohead`; `test_an_artists_name_shows_it_is_a_filter_over_their_songs_and_on_a_line_alone` becomes
`…_is_a_button_that_searches_for_them`: `<button class="artist artist-search" type="button" title="Search
Radiohead"><span class="artist-name">Radiohead</span></button>` in the band and on the title-sorted line;
`test_on_a_phone_the_tags_wrap_under_the_buttons…` opens `#show=wanted&inst=harmonica`, measuring the first `.tag`;
test_library_filter.py's addresses lose `&artist=eagles` and their "by Eagles" expectations;
`test_filters_key_sort_and_letters_work_on_the_lines` drops its `#artist=queen` lines.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q -n 0 tests/test_library_page.py -k
  "artist or by" tests/test_web_page_search.py -k artist` (the funnel's view, `#artist=queen` kept).
- [ ] **Step 3: Implement** — the deletions above. `addressed()`: `const by = normal(params.get("by") || "")`; `const
  named = artistName(params.get("artist") || "")`; when `!at.q && !at.prog`, `at.q = by || named` and `at.all =
  searchesAsYouType(at.q)`. `cameBy` is `has("by") || has("artist")`. `searchFor` keeps today's push (1c gives it its
  marker). The docs above. Regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass** — the files above, then `nix develop -c pytest -q -m "not slow"`.
- [ ] **Step 5: Commit** — `git add src/caracole tests docs/usage.md AGENTS.md` · `feat(library): an artist's name
  searches for them, served or from a file; no funnel, no one-artist view`

#### Task 1b.2: A 34 px band for an artist of two or more lines

**Files:**
- Modify: `src/caracole/library_assets/library.js` (`artistGroup`'s counts: `span.artist-counts` =
  `span.visually-hidden(" · yours ")` + `span(mine)` when the counts hold `mine` alone, else
  `span.visually-hidden(" · ")` + `span(said.join(" · "))`: what shows in a `span` of its own, textContent unchanged)
- Modify: `src/caracole/library_assets/library.css` (`.list, #found { --band-h: 34px; --fold-h: 64px }`; `.artist-title`:
  `display: flex; flex-wrap: nowrap; align-items: center; gap: 8px; height: var(--band-h); min-height: 0; padding: 0
  12px; font-size: .906rem; font-weight: 700; line-height: 1.2; overflow: hidden; color: var(--artist)`; its name
  `white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 0 1 auto; min-width: 0`; `.artist-counts {
  margin-left: auto; flex: 0 100 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--muted); font-size: .78rem; font-weight: 600 }`; coarse: `.artist-title button.artist { min-width: 24px;
  min-height: 24px }`)
- Modify: `tests/helpers/targets.py` (`small_targets(exempt: str = "", least: int = 44)`: the threshold `least - 0.5`;
  the module docstring)
- Modify: `docs/usage.md` (~2611, touch: 44 px but an artist's name, 24 px; the list: an artist of two or more songs
  under a 34 px band, your count on its right), `src/caracole/library_assets/__init__.py` (rows.css/library.css
  paragraph: the bands)
- Test: `tests/test_library_bands.py` (new), `tests/test_library_page.py`
  (`test_an_artists_name_is_bigger_than_their_songs_titles_in_a_colour_of_its_own`: deleted, replaced below;
  `test_lines_meet_touch_and_contrast`), `tests/test_web_page_search.py` (`test_the_bar_and_its_results_fit_a_phone`,
  `test_a_title_suggestion_fits_a_phone`, `test_the_miss_and_a_typos_band_fit_a_phone_and_read_in_light_and_dark`)

**Interfaces:**
- Produces: the band (top), `--band-h`, `--fold-h`, `small_targets(least=)`, `ARTIST_NAMES` in
  `tests/helpers/targets.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_library_bands.py — artist bands and folded lines on index.html, in Chromium.
BAND = """(() => { const s = document.querySelector('#list section.artist[data-artist="oasis"]');
  const h = s.querySelector('.artist-title'), name = h.querySelector('.artist-name'), c = h.querySelector('.artist-counts');
  const css = getComputedStyle, box = (n) => n.getBoundingClientRect();
  return { height: box(h).height, size: parseFloat(css(name).fontSize), weight: Number(css(name).fontWeight),
    colour: css(name).color, counts: [c.querySelector(':scope > span:not(.visually-hidden)').textContent, c.textContent,
      css(c).color, box(h).right - box(c).right],
    target: box(h.querySelector('button.artist')).height, tokens: TOKENS }; })()"""
# TOKENS: {"--artist": …, "--muted": …, "--text": …, "--accent": …}, each resolved by a probe span as
# test_library_page.py's HEADER_LOOK resolves them (move its `token` probe into a string both files share).

@pytest.mark.parametrize("size,touch", [("390,844", True), ("1280,900", False)])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_an_artist_with_two_songs_has_a_34px_band_naming_them_in_their_colour_and_counting_yours(...):
    # Oasis ×2, Eagles ×1
    band = noted(dom, "data-band")
    assert 33.5 <= band["height"] <= 34.5 and 14 <= band["size"] <= 15 and band["weight"] >= 700, band
    assert band["colour"] == band["tokens"]["--artist"]
    # what shows is the visible count span's textContent (innerText would hold the hidden " · yours " too)
    assert band["counts"][:2] == ["2", " · yours 2"] and band["counts"][2] == band["tokens"]["--muted"]
    assert band["counts"][3] <= 16  # on the band's right
    if touch:
        assert band["target"] >= 24
```

`test_lines_meet_touch_and_contrast` becomes `short = small_targets(ARTIST_NAMES)` and `floor = small_targets("",
least=24)`, both `[]`; the three phone tests of test_web_page_search.py the same pair.

- [ ] **Step 2: Run it and see it fail** — the band is ~41 px at 1.125rem today.
- [ ] **Step 3: Implement** — the CSS and the counts' markup above; the docs above; regenerate the corpus file.
- [ ] **Step 4: Run it and see it pass** — `tests/test_library_bands.py`, `tests/test_library_page.py -k "touch or
  header or grouped"`, `tests/test_web_page_search.py -k phone`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests docs/usage.md` · `feat(library): an artist's
  songs under a 34 px band, their name in their colour and your count on its right`

#### Task 1b.3: A one-song artist folds into its line

**Files:**
- Modify: `src/caracole/library_assets/library.js` (`artistGroup(artist, items, counts)`: the fold rule and `artist.tail`;
  `render`'s groups; `drawGroups` passes `tail: tailOf(g.model)` in the artist object, no `section.appendChild(tail)`)
- Modify: `src/caracole/library_assets/rows.js` (`indexLine`: `onSearch: searchesFor(artist)` in its `resultRow`)
- Modify: `src/caracole/library_assets/library.css` (`section.artist .line-by { display: none }` →
  `section.artist:not(.folded) .line-by`; `section.artist .line` at ≥ 720 → `section.artist:not(.folded) .line`;
  `section.artist.folded > .artist-title` visually hidden; the folded line's phone grid; the overline's type)
- Modify: `docs/usage.md` (the list: a one-song artist folded into its line, their name an overline over the title),
  `AGENTS.md` ("##### The library page's list": bands and folding by context, `artistGroup`'s `tail`),
  `src/caracole/library_assets/__init__.py` (rows.css/library.css paragraph: folded lines)
- Test: `tests/test_library_bands.py`, `tests/test_library_page.py`
  (`test_the_library_is_lines_grouped_by_artist_a_to_z`: four of its five artists now fold, its headings' texts stay)

**Interfaces:**
- Consumes: 1b.2's band; lane 3's `.line-title > .line-plays`.
- Produces: `section.artist.folded`, the folded grid, `artistGroup`'s `tail`.

- [ ] **Step 1: Write the failing tests**

```python
FOLDED = """(() => { const s = document.querySelector('#list section.artist[data-artist="eagles"]');
  const line = s.querySelector('article.line'), by = line.querySelector('.line-by'), h3 = line.querySelector('h3');
  const css = getComputedStyle, box = (n) => n.getBoundingClientRect();
  return { folded: s.classList.contains('folded'), head: [box(s.querySelector('.artist-title')).width,
    s.querySelector('.artist-title').textContent], by: [by.checkVisibility(), by.textContent, css(by).textTransform,
    parseFloat(css(by).fontSize), Number(css(by).fontWeight), parseFloat(css(by).letterSpacing), css(by).color,
    box(by).bottom, box(by).height], h3top: box(h3).top, line: box(line).height,
    oasis: [document.querySelector('#list section.artist[data-artist="oasis"]').classList.contains('folded'),
            [...document.querySelectorAll('#list section[data-artist="oasis"] .line-by')].some((n) => n.checkVisibility())],
    outline: [document.querySelectorAll('#list h2').length, document.querySelectorAll('#list h3').length] }; })()"""

@pytest.mark.parametrize("size,touch", [("390,844", True), ("320,640", True), ("1280,900", False)])
def test_a_one_song_artist_folds_into_its_line_under_their_name_as_an_overline(...):
    f = noted(dom, "data-folded")
    assert f["folded"] and f["head"][0] <= 1 and f["head"][1] == "Eagles · yours 1", f  # a screen reader's alone
    shown, text, case, size_, weight, spacing, colour, bottom, height = f["by"]
    assert shown and text == "Eagles" and case == "uppercase" and 11 <= size_ <= 12 and weight >= 700, f
    assert spacing > 0 and colour == tokens["--artist"]
    if touch:
        assert bottom <= f["h3top"] + 1 and 60 <= f["line"] <= 68 and height >= 24, f  # above the title; 64 px
    assert f["oasis"] == [False, False] and f["outline"] == [2, 3], f  # a band; an h2 an artist, an h3 a song

def test_a_library_of_one_song_artists_folds_every_group_and_an_artist_of_many_is_one_band(...):  # case 3
    # five one-song artists: five folded sections, no band visible; then one artist of 12 songs: one band, none folded

@pytest.mark.parametrize("width", [320, 390])
def test_long_and_chinese_names_are_cut_short_never_wrapped_into_the_buttons(...):  # case 2
    # 周杰伦 ×2 (a band), 宋冬野 "斑马，斑马" ×1 (folded), "The Red Hot Chili Peppers and the Extremely Long Named Friends"
    # ×1 (folded) and ×2 of another long name (a band); each with a sheet, so its line has a play button
    # every band 33.5–34.5 tall; the long band's name scrollWidth > clientWidth, textOverflow "ellipsis",
    # whiteSpace "nowrap"; each overline one line (height ≤ 26) whose right ≤ its line's .line-plays left + 0.5;
    # each h3's right ≤ .line-plays left + 0.5; document.documentElement.scrollWidth <= innerWidth

def test_a_results_group_folds_only_when_it_holds_one_line_and_nothing_else(cfg, live, phone):
    # (served: fixtures from test_web_page_search) ug: radiohead/creep ×2 versions, estopa cancion-0..5;
    # search "creep": Radiohead's group (one line, no tail) folded, its overline a button that searches "Radiohead";
    # search "estopa": the band, with its .group-tail ("+ N more"), not folded; a typo ("radiohed") whose
    # section.meant holds one line: not folded
```

- [ ] **Step 2: Run them and see them fail** — no `folded` class; the band shows for Eagles.
- [ ] **Step 3: Implement** — artistGroup: `const folds = listOf(items).length === 1 && !a.meant && !a.tail`; folded,
  the h2 holds `span.artist-name` (text) and the counts, no button. CSS, phone (`max-width: 719px`):

```css
section.artist.folded .line { grid-template-columns: minmax(0, 1fr) auto auto auto var(--line-more);
  grid-template-areas: "meta plays act key more" "name plays act key more"; align-content: center; }
section.artist.folded .line > .line-title { display: contents; }
section.artist.folded .line > .line-title > h3 { grid-area: name; }
section.artist.folded .line > .line-title > .line-plays { grid-area: plays; }
@media (pointer: coarse) { section.artist.folded .line { min-height: var(--fold-h); } }
```

  and the overline at every width (`section.artist.folded .line-by`): `color: var(--artist); font-size: .72rem;
  font-weight: 700; letter-spacing: .06em; text-transform: uppercase; line-height: 1.2; white-space: nowrap; overflow:
  hidden; text-overflow: ellipsis; max-width: 100%`, coarse `min-height: 24px`. From 720 px a folded line takes the flat
  line's columns (rows.css's `"title by status act key more"`, `.line.hit`'s with `src`), the overline in the `by`
  column. The docs above. Regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass** — `tests/test_library_bands.py`, `tests/test_library_page.py`,
  `tests/test_web_page_search.py -k "group or artist"`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests docs/usage.md AGENTS.md` · `feat(library): a
  one-song artist folds into its line, their name an overline over the title`

#### Task 1b.4: Sorted by title or by when they came, every line is folded

**Files:**
- Modify: `src/caracole/library_assets/library.css` (the 1b.3 phone grid and overline type also for `section.flat .line`
  and `section.flat .line-by`)
- Modify: `docs/usage.md` (the list: sorted by title or by when they came, every line folded, the artist above the
  title)
- Test: `tests/test_library_bands.py`, `tests/test_library_page.py`
  (`test_a_phones_line_keeps_its_artist_beside_its_status_and_its_key_beside_its_title` → renamed
  `test_a_phones_title_sorted_line_has_its_artist_above_its_title_and_its_status_beside_it`)

**Interfaces:**
- Produces: `section.flat .line` folded (descendant selector, for 1e's runs).

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.parametrize("sort", ["title", "recent"])
def test_a_sorted_list_folds_every_line_its_artist_above_its_title(conn, cfg, tmp_path, sort):
    # 390×844 touch, "#sort=" + sort; Oasis ×2, Eagles ×1, 宋冬野 ×1
    # every #list section.flat article.line: its .line-by visible, uppercase, bottom ≤ its h3's top + 1, the line
    # 60–68 px; at 1280 every .line-by visible in its own column (its left > its h3's right)
```

  The renamed phone test keeps its library and asserts each artist whole above its title (`.line-by` width ≥ its
  scrollWidth for ABBA and Queen), "Needs review" beside it, the long name cut, nothing sideways.
- [ ] **Step 2: Run it and see it fail** — today the artist sits under the title.
- [ ] **Step 3: Implement** — add `section.flat` to 1b.3's selectors (one selector list each rule); docs/usage.md;
  regenerate the corpus file.
- [ ] **Step 4: Run it and see it pass** — `tests/test_library_bands.py`, `tests/test_library_page.py -k "phone or sort"`,
  `tests/test_library_page_songbooks.py`, `tests/test_songbooks_tab.py -k select`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests docs/usage.md` · `feat(library): a list by title
  or by when they came folds every line, artist above title`

#### Task 1b.5: Merge stage 1b

**Files:**
- Check (written by 1b.1 to 1b.4): `docs/usage.md` (~line 2513, the artist's name: no funnel; a name searches for the
  artist, served or from a file, and `#by=`/`#artist=` do the same; ~2611, touch: 44 px but an artist's name, 24 px;
  the list: 34 px bands, folded one-song artists, folded lines sorted by title or by when they came; the tags no longer
  have "by Queen ×"), `AGENTS.md` ("##### The library page's list": "An artist's name" without the funnel and
  `artistFilter`; bands and folding by context, `artistGroup`'s `tail`; "##### Searching from the pages": "Your songs
  there keep to the Filter panel's filters" without the artist's tag), `src/caracole/library_assets/__init__.py`
  (rows.css/library.css paragraph: bands, folded lines)

- [ ] **Step 1** — whole suite; corpus twice; `nix develop ./android -c gradle -p android test`;
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus moved); `nix flake
  check`.
- [ ] **Step 2** — check the docs above against what the stage does; a gap goes into a `docs:` commit here.
- [ ] **Step 3** — on screen: a phone browser and the app, the owner's library (宋冬野 斑马斑马), title sort, a search.
- [ ] **Step 4** — raise with lane 4: songbooks.css's `.selecting` rules name `.filter-mark`, `.artist-only` (dead now)
  and give a `by` column at ≥ 720 px that a grouped line no longer has (Task 4.1 deletes them, or 4.3's rebase).
- [ ] **Step 5** — `git switch main && git merge --no-ff feat/library-1b-list`, then push main:
  `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

### Stage 1c · Search

#### Task 1c.1: The keyboard resizes the page in Chrome on Android

**Files:**
- Modify: `src/caracole/library_assets/head.html` (`<meta name="viewport" content="width=device-width, initial-scale=1,
  interactive-widget=resizes-content">`)
- Test: `tests/test_library_page.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_viewport_lets_the_keyboard_resize_the_page(conn, cfg):
    meta = '<meta name="viewport" content="width=device-width, initial-scale=1, interactive-widget=resizes-content">'
    assert meta in page(conn, cfg)
    assert meta in build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
```

- [ ] **Step 2–4** — fails on the old meta; edit head.html; regenerate the corpus file; passes.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/head.html tests/test_library_page.py tests/conformance` ·
  `feat(library): the keyboard resizes the library page in Chrome on Android`

#### Task 1c.2: Search mode: ← and Back leave it, × clears and stays

**Files:**
- Modify: `src/caracole/library_assets/body.html` (`<button type="button" id="leave" class="leave" aria-label="Back to
  your songs" hidden><span aria-hidden="true">←</span></button>` first in `.field`)
- Modify: `src/caracole/library_assets/library.js` (`searchMode(on)`, `enterSearch`, `leaveSearch`, `backFromSearch`;
  `input`'s `focus`; `render` turns it on while `state.q`; `searchFor` pushes `{ search: depth + 1 }`; `popstate`; the
  Escape listener; delete `backButton` and its `results-head` button, keeping `keptNote`)
- Modify: `src/caracole/library_assets/library.css` (`.leave`: absolute at the field's left, 44 × 44, muted; `.field:has(>
  .leave:not([hidden])) input { padding-left: 44px }`)
- Modify: `docs/usage.md` (~4121: ← and Back leave search, × clears and stays, no "Back to your songs" row),
  `AGENTS.md` ("##### Searching from the pages": search mode, `#leave`, the `{ search: n }` entries; the history rules
  of this plan's "Where the lanes meet" 1), `src/caracole/library_assets/__init__.py` (library.js's paragraph: search
  mode)
- Test: `tests/test_library_search_mode.py` (new), `tests/test_web_page_search.py` (`BACK` and the tests using it:
  `test_a_query_that_finds_nothing_…`, the one at ~line 1313, ~line 512's "Back to your songs" walk)

**Interfaces:**
- Produces: `body.search-mode`, `#leave`, `{ search: n }` entries, the four functions.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_library_search_mode.py — the library page's search mode: the box, ←, Back, the masthead, recent songs.
MODE = "document.body.classList.contains('search-mode')"

def test_focusing_the_empty_box_is_one_step_that_back_and_the_arrow_take_back(conn, cfg, phone_page):  # the file
    n = phone_page.js("history.length")
    phone_page.js("document.getElementById('q').focus()")
    assert phone_page.wait(MODE) and phone_page.js("history.length") == n + 1
    assert phone_page.js("history.state.search") == 1
    assert phone_page.js("document.getElementById('leave').checkVisibility()")
    phone_page.type("creep")
    assert phone_page.js("history.length") == n + 1  # typing adds no step
    phone_page.js("history.back()")
    assert phone_page.wait(f"!{MODE}") and phone_page.js("document.getElementById('q').value") == ""
    assert phone_page.js("document.activeElement.id") != "q"
    phone_page.js("document.getElementById('q').focus()")
    phone_page.click("#leave")
    assert phone_page.wait(f"!{MODE}") and phone_page.js("history.state") is None

def test_the_arrow_leaves_search_from_any_number_of_steps_in(cfg, live, browser):  # served
    # type "los tontos"; click the band's artist name (searchFor: a second step); click #leave:
    # not in search mode, box empty, #results hidden, history.state null
def test_clear_empties_the_box_and_keeps_the_focus_in_search(...):
    # type "creep"; click #clear: value "", activeElement #q, still MODE
def test_escape_in_the_empty_box_leaves_search(...):  # 1280; Escape with text and the sites' results keeps today's ways
def test_where_the_browser_refuses_a_step_search_still_comes_and_goes(...):  # case 1
    # pushState throwing (as 1a.4): focus → MODE, no error; #leave → !MODE
def test_no_row_over_the_results_says_back_to_your_songs_the_arrow_does(cfg, live, browser):
    # after an answer: no #results button whose textContent is "Back to your songs"; one control named so, #leave
```

- [ ] **Step 2: Run them and see them fail** — no `#leave`; `history.length` unchanged on focus.
- [ ] **Step 3: Implement**
  - `searchMode(on)`: the body class, `leave.hidden = !on`; on, it sets `--mast-h` (1c.3).
  - focus of `#q` when not in search mode: `pushState({ search: 1 }, "", location.href)` in try/catch, only when the box
    is empty; then `searchMode(true)`. `render()` calls `searchMode(true)` when `state.q`. Blur leaves nothing.
  - `searchFor`: `pushState({ search: (Number(history.state && history.state.search) || 0) + 1 }, …)` where it pushes
    today.
  - `backFromSearch()` (#leave): `const depth = Number(history.state && history.state.search) || 0`; depth > 0 →
    `leaving = true; history.go(-depth)`; else `leaveSearch()`.
  - `leaveSearch()`: `setQuery("")`, `input.blur()`, `searchMode(false)`.
  - `popstate`, **before** today's early return for an address that changes nothing (an entry pushed on focus has the
    same address as the one under it): `leaving` and still `state.q` once restored → `leaveSearch()`; else no `q` in the
    address and no `history.state.search` → `input.blur()`, `searchMode(false)`; `leaving = false`.
  - `searchFor` sets `state.q` and renders before it focuses the box, so the focus finds search mode on and pushes
    nothing more.
  - Escape, the box focused and empty, in search mode: `backFromSearch()`.
  - The docs above.
  Regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass** — the new file, `tests/test_web_page_search.py`, `tests/test_library_tabs.py`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests docs/usage.md AGENTS.md` · `feat(library): search
  is a step of its own: ← and Back leave it, × clears and stays`

#### Task 1c.3: On a phone, search takes the screen

**Files:**
- Modify: `src/caracole/library_assets/library.js` (`searchMode(true)`: `masthead.style.setProperty("--mast-h",
  masthead.getBoundingClientRect().height + "px")`, measured before the class goes on)
- Modify: `src/caracole/library_assets/library.css` (`@media (max-width: 719px) { body.search-mode .masthead.lib {
  margin-top: calc(-1 * var(--mast-h, 0px)); visibility: hidden; } }`; `@media (prefers-reduced-motion: no-preference) {
  .masthead.lib { transition: margin-top .2s ease, visibility 0s linear 0s; } body.search-mode .masthead.lib {
  transition: margin-top .2s ease, visibility 0s linear .2s; } }`)
- Modify: `docs/usage.md` (~4121: on a phone the logo and tabs slide away while you search)
- Test: `tests/test_library_search_mode.py`

- [ ] **Step 1: Write the failing tests**

```python
HIDDEN = ("getComputedStyle(document.querySelector('.masthead.lib')).visibility === 'hidden' && "
          "document.querySelector('.searchbar').getBoundingClientRect().top <= 1")

@pytest.mark.parametrize("width", [320, 390])  # case 7
def test_on_a_phone_the_masthead_slides_away_for_search_and_comes_back(conn, cfg, tmp_path, width):
    # Browser(width=width, mobile=True): duration = parseFloat(getComputedStyle(masthead).transitionDuration) > 0
    # focus #q → wait HIDDEN; the field within the 16 px gutters, nothing sideways; #leave → masthead visible, top ≥ 0
def test_with_reduced_motion_the_masthead_goes_at_once(...):  # case 6
    # Emulation.setEmulatedMedia prefers-reduced-motion: reduce; transitionDuration "0s";
    # js("q.focus(); getComputedStyle(masthead).visibility") == "hidden"  (the same task)
def test_scrolled_down_search_moves_no_line_on_the_screen(...):
    # 40 songs; scrollTo(0, 800); a line's top noted; focus → HIDDEN; that line's top within 2 px
def test_on_a_laptop_the_masthead_stays_in_search(...):  # 1280: focus → search-mode, masthead visible
```

- [ ] **Step 2: Run them and see them fail** — the masthead stays visible.
- [ ] **Step 3: Implement** — the property and the CSS above; if the scrolled-down test fails where scroll anchoring
  doesn't hold, `window.scrollBy(0, -height)` in the same frame when `scrollY >= height` (and `+height` on leaving).
  docs/usage.md. Regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests/test_library_search_mode.py tests/conformance
  docs/usage.md` · `feat(library): on a phone the logo and tabs slide away while you search`

#### Task 1c.4: Scrolling the results puts the keyboard away

**Files:**
- Modify: `src/caracole/library_assets/library.js` (`document.addEventListener("touchmove", …, { passive: true })`: the
  box focused and the touch outside `.searchbar` → `input.blur()`)
- Modify: `docs/usage.md` (~4121: scrolling the results puts the keyboard away)
- Test: `tests/test_library_search_mode.py`

- [ ] **Step 1: Write the failing test** — served (`live`), phone: type "creep", wait for the answer, then
  `Input.dispatchTouchEvent` touchStart/touchMove (−150 px)/touchEnd over the first `#results article`:
  `document.activeElement.id !== 'q'` and still search mode; at 1280 a `mouseWheel` over the results leaves the focus in
  the box.
- [ ] **Step 2–4** — fails (the focus stays); the listener and docs/usage.md; regenerate the corpus file; passes.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests/test_library_search_mode.py tests/conformance
  docs/usage.md` · `feat(library): scrolling the results puts the keyboard away`

#### Task 1c.5: The count row: yours, the sites that found something, then the rest in one mark

**Files:**
- Modify: `src/caracole/library_assets/rows.js` (`countMarks`, `countsSaid`, new `fitCounts` and `drawCountMarks`, the
  export list; the section's comment)
- Modify: `src/caracole/library_assets/rows.css` (`.count-name` hidden, shown from 720 px in `.counts:not(.short)`;
  `.count-mark.rest` as today's `[data-n="0"]`; `.counts-row.counted > .counts ~ *` screen reader's alone, the `:not([hidden])`
  gone; `.bar-said.counted:has(> .counts[hidden])` takes no room; the row still wraps, `fitCounts` dropping the names
  first)
- Modify: `src/caracole/library_assets/library.js` (`drawCounts`: `drawCountMarks(barCounts, …)` in place of its
  `replaceChildren`; `say(…, true)` either way)
- Modify: `src/caracole/web/lookup_page.py` (`showCounts`: the same one call, `drawCountMarks(…)`, no lines of its own)
- Modify: `src/caracole/library_page.py` (docstring ~lines 118–126)
- Modify: `docs/usage.md` (~4041–4073: the count row's new rules, "0 on N more", a blocked site's 0 among the rest, no
  row at all, names in full on a laptop), `AGENTS.md` ("##### What a search says beside its results": `countMarks`,
  `fitCounts`, `drawCountMarks`, `countsSaid`), `src/caracole/library_assets/__init__.py` (rows.js's paragraph: the
  count row)
- Test: `tests/test_web_page_search.py`, `tests/test_web_lookup_page.py`

**Interfaces:**
- Produces: `countMarks`, `fitCounts`, `drawCountMarks`, `countsSaid` as at the top: one rows.js helper draws the row
  for both pages, so neither page holds lines of its own for it.

- [ ] **Step 1: Write the failing tests** — `rg -n "count-mark|bar-counts|COUNTS_SHOWN|ROW_FITS|Not on the sites"
  tests/test_web_page_search.py tests/test_web_lookup_page.py` lists those that move.

```python
MARKS = """[...document.querySelectorAll('#bar-counts > li')].map((li) => [li.dataset.source, li.dataset.n,
  li.querySelector('.count-rest') ? li.querySelector('.count-rest').textContent : null,
  (li.querySelector('.visually-hidden') || {}).textContent || null, li.title])"""

@pytest.mark.parametrize("where", ["library", "lookup"])
def test_the_row_shows_yours_then_the_sites_that_found_some_then_the_rest_in_one_quiet_mark(cfg, live, browser, where):
    # ug radiohead/creep ×4; gtptabs a creep page; read_to(cfg, ("_num", "a", "b", "c")) (LaCuerda in part);
    # blocking(cfg, "musescore"); harptabs and gametabs empty; library Radiohead - Creep; query "creep"
    marks = browser.js(MARKS)
    assert [m[0] for m in marks] == ["library", "ug", "gtptabs", "rest"]  # a blocked site's 0 is one of the rest
    rest = marks[-1]
    assert rest[1] == "0" and rest[2] == "0 on 4 more"
    assert rest[3] == "0 on 4 more: LaCuerda, MuseScore, harptabs.com, gametabs.net"  # `looked` order
    assert rest[4].split("\n") == ["0 on LaCuerda · index in part, up to C", "0 on MuseScore · turned us back",
                                   "0 on harptabs.com · index empty", "0 on gametabs.net · index empty"]
    # (each line countSaid's for that site's `looked` entry, its state in it, MuseScore's blocked one too: take the
    # exact words from the answer if _looked's differ)

def test_a_search_whose_every_count_is_0_has_no_count_row(cfg, live, phone):  # case 4
    # empty indexes, no song of yours matching "zzzqqq": #bar-counts hidden, no li; .bar-said height ≤ 1;
    # #bar-status textContent "Nothing in your songs or the sites' indexes"
def test_a_site_turned_off_or_empty_is_named_in_the_rest(...):  # case 4: gametabs off in caracole.toml → "gametabs.net: off"
def test_on_a_laptop_the_sites_are_named_in_full_where_the_row_fits_one_line(cfg, live, browser):
    # 1280: li[data-source=ug] .count-name visible, "Ultimate Guitar"; the marks one line (one top);
    # 760 wide with all six sites finding something: one line, names or not (.short says which)
```

`test_the_row_of_marks_wraps_cleanly_on_a_phone_and_reads_in_light_and_dark`: `fits["n"] == 3` (yours, UG, the rest)
and `fits["lines"] == 1`; `COUNT_READS` also reads `.count-rest`.

- [ ] **Step 2: Run them and see them fail** — seven marks, zeros each a mark.
- [ ] **Step 3: Implement** — `countMarks`: compute every site's `n` (and `state`) first; `if (!(Number(yours) > 0) &&
  sites.every(n === 0)) return []`; yours' mark first (when `yours` isn't null); each site with `n > 0` and a searched
  state, as today, plus `el("span", "count-name", siteName(s))` between its mark and its count; the others, whatever
  their state (a blocked site's 0 among them), gathered into one `li.count-mark.rest` (`dataset.source = "rest"`,
  `dataset.n = "0"`, `span.count-rest` aria-hidden with `"0 on " + k + " more"`, `span.visually-hidden` with that,
  `": "` and their names joined by `", "`, `title` their `countSaid` lines, each saying its site's state, joined by
  `"\n"`).
  `fitCounts(list)`: remove `short`; if the first `.count-name` doesn't show, stop; when the items' `offsetTop`s differ,
  add `short`; a `ResizeObserver` (once a list, a WeakSet) fits it again. `drawCountMarks(list, data, yours, found)`:
  `const items = countMarks(data, yours, found)`, `list.replaceChildren(...items)`, `list.hidden = !items.length`,
  `fitCounts(list)`, `return items`; library.js's `drawCounts` and lookup_page.py's `showCounts` call it and nothing
  else for the row. `countsSaid`'s last member: `mine.length ? "nothing in the sites' indexes" : "Nothing in your songs
  or the sites' indexes"`. The docs above. Regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass** — both files.
- [ ] **Step 5: Commit** — `git add src/caracole tests docs/usage.md AGENTS.md` · `feat(search): the count row shows
  what found something, the rest in one quiet mark`

#### Task 1c.6: Nothing found: where caracole looked, and Request the one filled button

**Files:**
- Modify: `src/caracole/library_assets/rows.js` (`nothingFound`: `does.yours`; the band's words; the line's title the
  query; Request `button("Request", "small primary miss-request", …)`)
- Modify: `src/caracole/library_assets/library.js` (`missOf`: `yours: mine.length` in its `does`, `model.card` made again
  when that number changes)
- Modify: `src/caracole/library_assets/rows.css` (`.line.miss h3, .row.miss .row-title`: normal style, `var(--text)`,
  600; `.miss-request` filled: `background: var(--accent); border-color: var(--accent); color: var(--on-accent)`;
  `.line.miss` phone grid `"title more" "act act"` with the action `justify-self: start`; from 720 px
  `grid-template-columns: minmax(0, max-content) auto minmax(0, 1fr) var(--line-more); grid-template-areas: "title act .
  more"`; `.row.miss` the same areas)
- Modify: `src/caracole/web/lookup_page.py` (its comment's "Not on the sites")
- Modify: `docs/usage.md` (~4041–4073: nothing found's words and its Request), `AGENTS.md` ("##### What a search says
  beside its results": `nothingFound`'s words and `does.yours`)
- Test: `tests/test_web_page_search.py`, `tests/test_web_lookup_page.py`

**Interfaces:**
- Produces: `nothingFound(data, query, does)` with `does.yours`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_query_that_finds_nothing_says_where_it_looked_and_request_is_the_one_filled_button(cfg, live, tmp_path):
    for width in (390, 1280):  # replaces test_a_query_that_finds_nothing_is_one_line_under_a_quiet_band_…
        # search "zzzqqq"
        assert page.js(f"document.querySelector('{NOTHING} > h2').textContent") == \
            "Nothing for “zzzqqq” in your songs or the sites' indexes"
        title = page.js(f"(() => {{ const h = document.querySelector('{NOTHING} article h3'), s = getComputedStyle(h);"
                        " return [h.textContent, s.fontStyle, s.color]; }})()")
        assert title == ["zzzqqq", "normal", tokens["--text"]]  # TOKENS as in test_library_bands.py
        req, h3 = (page.js(f"document.querySelector('{s}').getBoundingClientRect().toJSON()")
                   for s in (f"{NOTHING} .miss-request", f"{NOTHING} article h3"))
        assert page.js(f"getComputedStyle(document.querySelector('{NOTHING} .miss-request')).backgroundColor") == \
            tokens["--accent"]
        if width < 720:
            assert req["top"] >= h3["bottom"] and abs(req["left"] - h3["left"]) <= 2  # under the query
        else:
            assert req["top"] < h3["bottom"] and 0 <= req["left"] - h3["right"] <= 24  # right after it
        # Ask LaCuerda, where the listings don't reach the name, under the chevron, not filled

def test_nothing_on_the_sites_but_a_song_of_yours_says_the_sites_indexes_alone(cfg, live, browser):
    # library Radiohead - Creep, empty indexes, "creep": your line, then "Nothing for “creep” in the sites' indexes"
```

  The lookup page's `test_a_close_spelling_says_did_you_mean_…` headings end with `"Nothing for “lynrd” in your songs or
  the sites' indexes"`; `READS`' selectors stay and its 4.5:1 checks hold.
- [ ] **Step 2: Run them and see them fail** — "Not on the sites", the italic quoted query.
- [ ] **Step 3: Implement** — as above, the docs too; regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass** — both files, `tests/test_web_page_lacuerda_search.py`.
- [ ] **Step 5: Commit** — `git add src/caracole tests docs/usage.md AGENTS.md` · `feat(search): nothing found says
  where caracole looked, with Request the one filled button`

#### Task 1c.7: Recently opened songs in the empty box

**Files:**
- Modify: `src/caracole/library_assets/body.html` (`<section class="recent" id="recent" aria-labelledby="recent-head"
  hidden><h2 class="recent-head" id="recent-head">Recently opened</h2><ul class="recent-list" id="recent-list"></ul>
  </section>` after `.bar-said`)
- Modify: `src/caracole/library_assets/library.js` (`RECENT = "caracole-library-recent"`, `RECENT_MAX = 5`,
  `readRecent()`, `rememberOpened(line, link)`, `drawRecent()`; the document's click listener; `#recent`'s `mousedown`
  `preventDefault`, so a tap opens it with the box's focus kept)
- Modify: `src/caracole/library_assets/library.css` (`.recent`: under the box, a line a song, its title then its artist
  muted, each link ≥ 44 px on coarse)
- Modify: `docs/usage.md` (~4121: recently opened, in the empty box), `src/caracole/library_assets/__init__.py`
  (library.js's paragraph: recently opened)
- Test: `tests/test_library_search_mode.py`

**Interfaces:**
- Produces: the storage key, `#recent`, `rememberOpened`.

- [ ] **Step 1: Write the failing tests**

```python
RECENT = "[...document.querySelectorAll('#recent a')].map((a) => [a.textContent, a.getAttribute('href')])"
STAY = "document.addEventListener('click', (e) => e.preventDefault())"  # the play opens nothing during the test

def test_the_focused_empty_box_lists_the_songs_opened_last_newest_first(conn, cfg, phone_page):
    # six songs with a sheet each; open each one's first `.line-plays a`, in order, then the first again, with STAY
    phone_page.open(url)  # a reload: kept in this browser's storage
    phone_page.js("document.getElementById('q').focus()")
    assert phone_page.wait("document.getElementById('recent').checkVisibility()")
    shown = phone_page.js(RECENT)
    assert len(shown) == 5 and shown[0][0].startswith(FIRST_TITLE) and shown[0][1] == FIRST_HREF
    phone_page.type("c")  # typed: gone
    assert phone_page.wait("!document.getElementById('recent').checkVisibility()")

def test_a_recent_song_opens_what_it_opened_before(...):   # a tap on #recent a: location.pathname its sheet.html
def test_a_song_removed_since_is_not_among_them(...):      # its identity no song's: left out
def test_with_no_storage_the_box_works_and_lists_nothing(...):  # NO_STORAGE (test_viewer_numerals.py) by
    # Page.addScriptToEvaluateOnNewDocument: no error, #recent hidden, searching works
```

- [ ] **Step 2: Run them and see them fail** — no `#recent`.
- [ ] **Step 3: Implement** — `rememberOpened`: the line's song (`byIndex.get(Number(line.dataset.id))`), `{ identity,
  href: link.getAttribute("href"), said: link.getAttribute("aria-label") || link.textContent }`, put first, the same
  identity dropped, cut to 5, written in try/catch. The click listener: `a[href]:not([download]):not([target=_blank])`
  inside `article.line[data-id]`. `drawRecent`: shown when the box has the focus, is empty and the Library tab shows;
  each entry whose identity is a counted song's, `a.recent-song` (`safeHref`), its title and artist by `shownName`,
  `title` its `said`. The docs above. Regenerate the corpus file.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests/test_library_search_mode.py tests/conformance
  docs/usage.md` · `feat(library): the songs you opened last, in the empty search box`

#### Task 1c.8: Merge stage 1c

**Files:**
- Check (written by 1c.2 to 1c.7): `docs/usage.md` (~4041–4073: the count row's new rules, "0 on N more", no row at
  all, names in full on a laptop; nothing found's words and its Request; ~4121: ← and Back leave search, × clears and
  stays, no "Back to your songs" row; the phone's masthead in search; scrolling puts the keyboard away; recently
  opened), `AGENTS.md` ("##### What a search says beside its results": `countMarks`, `fitCounts`, `drawCountMarks`,
  `countsSaid`, `nothingFound`'s words and `does.yours`; "##### Searching from the pages": search mode, `#leave`, the
  `{ search: n }` entries; the history rules at the top of this plan), `src/caracole/library_assets/__init__.py`
  (rows.js's and library.js's paragraphs)

- [ ] **Step 1** — whole suite; corpus twice; `nix develop ./android -c gradle -p android test`;
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus moved); `nix flake
  check`.
- [ ] **Step 2** — check the docs above against what the stage does; a gap goes into a `docs:` commit here.
- [ ] **Step 3** — on screen: the owner's Sony in the app and in Chrome (the keyboard up, ←, Back), the lookup page.
- [ ] **Step 4** — `git switch main && git merge --no-ff feat/library-1c-search`, then push main:
  `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

### What the design leaves open or the code makes awkward (decided here, flagged for review)

1. **← clears the box.** Today's "Back to your songs" kept the query and showed your songs it matched. With "with
   text in the box" keeping search mode on, leaving search must empty the box; Escape keeps today's "back to your
   songs, the search kept" for keyboards, and "All N of your songs" does it on a phone.
2. **The band's colour.** "the artist's name in the accent" against the overline "in the colour artist names use":
   both keep `--artist` (the laptop mockup's `#e3b48a` is `--artist`).
3. **"Nothing for … in your songs or the sites' indexes" is false on the library page when a song of yours matched**
   (nothingFound shows whenever the sites found nothing): it then says "in the sites' indexes" (`does.yours`).
4. **The count row's zeros.** Yours stays first at 0 when a site found something; a site off, empty, in part or
   blocked with 0 goes into "0 on N more", its state in the tooltip (the spec's row: "Where the lanes meet" 5 is
   withdrawn).
5. **"On a phone, their letters"** read as today's mark (the site's icon, else its letters); "on a laptop" as ≥ 720 px,
   the fit measured per draw (`fitCounts`).
6. **24 px vs 44 px.** base.css gives every control 44 px on touch; only the two artist names (band, overline) drop to the
   24 px floor, as a 34 px band can't hold 44; the suite's 44 px checks exempt them.
7. **Folding by context, not by class**: lines are cached and move between the list and the results, so
   `section.artist.folded` and `section.flat` decide; a folded results group loses its band's site counts (its group has
   one line and no "+ N more", so they are small); "Recently added" folds as Title A–Z does (the design names only the
   latter).
8. **Search mode starts on focus at every width** (the ← shows on a laptop too); only the masthead's hiding is a
   phone's. Blur alone doesn't leave it.
9. **`pushState` on a file**: Chromium allows it; where a browser refuses, tabs and search still change, ← leaves
   directly and the system Back leaves the page.
10. **Crossings to raise, not done**: test_requests_tab.py (lane 2's file) holds the five-tabs-fit assertion 1a.2
    changes; songbooks.css's `.selecting` rules (lane 4) reference the funnel and a `by` column (Task 4.1 deletes
    them); songbooks.js's and requests.js's `replaceState(null, …)` (Tasks 4.1 and 2.8 pass `history.state`; sync.js's
    is 1a.4's); lane 3 keeps `.line-plays` a child of `.line-title`.

---

## Lane 1 · The list page — stages 1d, 1e and 1f

Design: `docs/superpowers/specs/2026-11-17-library-page-redesign-design.md` ("The laptop", "The card" for its placement,
"Long lists", "A calmer page"). Stages 1a–1c (navigation and Back, the phone list, search) merge before these.

### Before you start

- **One branch a stage**, each from `main` once the stage before it merged, in a worktree of its own:
  `git worktree add ../caracole-1d -b feat/library-card-place main` (1e: `perf/library-long-lists`, 1f:
  `style/library-calm`; lane 3b's branch is `feat/library-card-insides`).
- **What these stages take from 1a–1c** (named for what they are; the coordinator aligns the names):
  - 1a's Back entries: the helper that pushes a history entry whose Back runs an `undo`, and drops it (popped without
    running `undo`) when the thing it undoes was closed otherwise; it degrades quietly where `history.pushState`
    throws. There is no such helper: the plan's "Where the lanes meet" 1 gives the history rules instead.
  - 1b's line: the element library.js's `lineFor(s)` builds through rows.js `resultRow({ dense: true, … })` (an
    `article.line`, its `.line-title` holding the title and, folded, the artist's overline; its chevron
    `.line-more`, a direct child, whose `aria-controls` names its panel `.line-panel`); the folded group of a
    one-song artist (called `section.artist.folded` below) and the band group (`section.artist` of two lines or
    more); and the heights of a band, a band's line and a folded line.
  - 1c's sticky search bar (`.searchbar`, with whatever 1c put in it) and search mode (`state.all`, your songs'
    lines moved into `#found` by `drawGroups`). If 1c already keeps the bar's height in a custom property, use it
    where this plan says `--bar-h`.
- **Meeting points, raised, not done here:**
  - Lane 3 (card.css): `.line:not(.hit) > .line-panel { … }` and `.line:not(.hit) > .line-panel > .foot { … }` don't
    match a card in the laptop's pane; `.line:not(.hit):has(> .line-more[aria-expanded="true"])` raises a selected
    line as a card although its card is in the pane. 1d gives every song's panel the class `song-card` and every
    line whose card is in the pane the class `selected`: lane 3 keys the first two rules to `.line-panel.song-card`
    and adds `:not(.selected)` to the third.
  - Lane 3: "one row per tile" on a phone is card.css's; 1d only orders the parts.
  - Lane 2: untouched. `.line-meta` stays a direct child of the line, so `progressIn` finds it as before; the card's
    head (below) lives in the panel, not the line.
  - 1f's radius test leaves out lane 2's (`.step-chips`, `#requests`), lane 3's (`.line-panel`, `.play`) and lane
    4's (`#songbooks`, `.pickbar`, `.pick`) elements, for them to follow (2.8, 3a.2, 3a.3, 3b.6 and 4.1 write the
    tokens); the last of 1f, lane 2, 3b and lane 4 to merge removes the skip list.
- **The tests' default window is 1280 × 900** (`test_library_page.dump_dom`, `helpers.browser.Browser`), which is
  past 1200 px: once the pane lands, a card is not inside its line there; and once cards are built on first open, an
  unopened line's card has nothing in it. Task 1d.1 moves every test that reads a card to helpers that find it
  wherever it is, before either change.
- Every task that changes `src/caracole/library_assets/` regenerates the corpus in its commit
  (`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, twice, then once without
  `CARACOLE_CORPUS`); gradle runs at each stage's merge.

---

### Stage 1d · The card: built on first open, in order, its head, and the laptop's pane

#### Task 1d.1: The tests find a card by its chevron

**Files:**
- Create: `tests/helpers/cards.py`
- Modify: every test that reads a song's card inside its line. Find them with
  `rg -n "line-panel|\.tiles|drawer|\.foot|card-sites|progressions|find-elsewhere|details\.picker|pick-form|again|youtube-sheet|form\.remove|lacuerda-pick|\.facts" tests/test_library*.py tests/test_web_page*.py tests/test_web_downloads.py tests/test_web_guitar_browser.py`
  (about 16 files; test_library_card.py's `KIT`, test_library_page.py, test_web_page.py's `COUNTDOWN`,
  test_web_page_again.py, test_web_page_search.py hold most).
- Test: `tests/test_library_card_place.py` (new: stage 1d's tests)

**Interfaces:**
- Produces, in `tests/helpers/cards.py` (module docstring says what each gives, as tests/helpers/' modules do):
  - `KIT`, JavaScript: `cardOf(line)` (the element whose id the line's `.line-more` names in `aria-controls`, or
    null), `openCardOf(line)` (clicks the chevron unless `aria-expanded` is `"true"`; returns `cardOf(line)`),
    `closeCard(line)`. The line form is `openCardOf`, so a script that also holds test_library_card.py's title form,
    `openCard(title)`, declares each name once.
  - `install(page)`: for a `Browser`, the same three as `window.cardOf`, `window.openCardOf`, `window.closeCard`, for
    `page.js` and `page.wait` (an evaluation can't declare a `const` twice); `open_card(page, line_selector) -> str`
    opens the line's card and returns `"#" + its id`, a selector for `page.click`.
  - `card_of(dom, title) -> str`: from a DOM dump, the markup of the element the chevron of the line headed `title`
    names (html.parser, nested elements counted); `""` when there is none.
  - `IN_PLACE = "1024,900"`: the widest window whose cards open under their lines (for a test that reads several
    cards of one page).

- [ ] **Step 1: Write the failing test** — `test_the_tests_find_a_card_by_its_chevron(conn, cfg, tmp_path)`: Creep
  and Karma Police (Radiohead), found, `sheet.pdf` each; the file page with `cards.KIT` and a script that runs
  `openCardOf(lineOf("Creep"))` and notes `{ id: cardOf(line).id, named: line.querySelector(".line-more").getAttribute("aria-controls"), other: cardOf(lineOf("Karma Police")).hidden }`.
  Assert `noted["id"] == noted["named"]`, `noted["other"] is True`, and
  `cards.card_of(dom, "Creep").startswith('<div class="line-panel')` with `"Add to a songbook…" in` it.
- [ ] **Step 2: Run it and see it fail** —
  `nix develop -c pytest -q tests/test_library_card_place.py::test_the_tests_find_a_card_by_its_chevron`:
  `ModuleNotFoundError: No module named 'helpers.cards'`.
- [ ] **Step 3: Implement** — the module, then the switch, by one rule: a test that reads a part of a song's card
  opens the card first (`openCardOf`, `open_card`, or a script that opens it before the dump) and reads it through
  `cardOf` / `card_of`, never `line.querySelector` or `line_of(...)`'s string; a test that reads several cards of one
  page in one dump runs at `IN_PLACE`. test_library_card.py's `KIT` gets `cards.KIT`; its own title form,
  `openCard(title)`, stays (`openCardOf(lineOf(title))`, returning the line as today), and its `noteCard`,
  `noteDrawer`, `chipOf` read `cardOf(lineOf(title))`. No product change.
- [ ] **Step 4: Run it and see it pass** — the new test, then every file Step 3 touched:
  `nix develop -c pytest -q tests/test_library_card_place.py tests/test_library_card.py tests/test_library_page.py tests/test_web_page*.py tests/test_web_downloads.py tests/test_web_guitar_browser.py`: all pass.
- [ ] **Step 5: Commit** — `git add tests/` ;
  `git commit -m "test(library): tests find a song's card by its chevron, wherever it is"`.

#### Task 1d.2: A song's card is built the first time it opens

**Files:**
- Modify: `src/caracole/library_assets/rows.js` (`foldMore`, `denseLine`, `resultRow`'s options)
- Modify: `src/caracole/library_assets/library.js` (`lineFor` split into `lineFor` and `cardFor`; `makePicker`'s
  `pickable` as `canPick`; `serverAction`; `refill`; `pickHere`; `showPicker`; `countdownIn`)
- Modify: `AGENTS.md` ("index.html's assets (library_assets/)": a song's card built on first open by `cardFor`),
  `src/caracole/library_assets/__init__.py` (card.css and card.js's paragraph: "library.js `cardFor` puts its parts in
  the line's panel, the first time it opens")
- Test: `tests/test_library_card_place.py`

**Interfaces:**
- Consumes: 1b's line; `cards.KIT`.
- Produces:
  - rows.js `resultRow({ more, onToggle, … })`: `more` is an array (as today: built at once) or a function returning
    that array, called the first time the chevron opens; with a function the chevron is always drawn and its panel is
    made empty and hidden, with its id, so `aria-controls` names it from the start. `onToggle(open, panel, event)`,
    if given, is called after every open or close, the panel already shown or hidden (`event`: the click).
  - library.js `cardFor(s)`: the card's parts (today's `more`), built once per line; `openCard(item)` and
    `closeCard(item)` (the chevron clicked unless already in that state); `canPick(s)` (served, a review with
    candidates, not busy, no active job: what makes `makePicker` draw a form); `serverAction(s, pickable)` takes
    that boolean, and Pick the match opens the card (`openCard`) and then its picker (`showPicker`).
  - The panel of a song of yours has the class `song-card` beside `line-panel`.

- [ ] **Step 1: Write the failing test** —
  - `test_a_songs_card_is_made_the_first_time_it_opens`: `hotel(conn, cfg)` (test_library_card.py's) and Creep;
    file page; a script notes, before anything opens, every song line's panel `{ empty: panel.childElementCount === 0, hidden: panel.hidden, cls: panel.className }`,
    then `openCardOf(lineOf("Hotel California"))` and notes its card's child count and Creep's panel's again. Assert
    every panel `empty and hidden` and `"song-card" in cls` before; Hotel California's card has children after; Creep's
    still `empty`.
  - `test_a_card_first_opened_while_its_request_runs_has_no_pick_and_no_fetch_again` (served: test_web_page_again.py's
    `live`, `lookup` and `browser`, `lookup.hold.clear()`, at `cards.IN_PLACE`): a found song and a song in review
    with two candidates; the test posts `POST /lookup` for each (`csrf=tok`, the song's id and identity) with
    `fetch()`, waits until both lines say they run, then opens both cards: no `.actions.again` in the found song's,
    and the review's picker is the read-only one (`details.picker` with no `form.pick-form`, "This song is being
    fetched. Pick once it ends.").
  - `test_pick_the_match_opens_the_card_and_its_picker` (served, a wanted song with candidates and
    `fetchable` false): click `.line-pick`; `aria-expanded` is `"true"`, `cardOf(line).querySelector("details.picker").open`,
    the focus on its first `input[name=pick]`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card_place.py -k "first_time or first_opened or pick_the_match"`:
  the first fails on `empty` (cards are built with the list); the others may pass already and stay as guards.
- [ ] **Step 3: Implement** —
  - rows.js `foldMore(item, title, more, kind, onToggle)`: for a function, `built` false until the first open, then
    `panel.append(...more().map(linkGroup).filter(Boolean))`.
  - library.js `lineFor(s)` keeps the line (title, plays, status, key, action, its request line, its countdown) and
    passes `more: () => cardFor(s)`; `cardFor(s)` holds what `lineFor` built under the chevron, unchanged in content
    and order (1d.3 reorders it). A card built while the song's removal counts down disables its forms' buttons and
    adds them to that removal's `held` (`removals.get(id)`), as `countdownIn` does for the line.
  - `refill(old, fresh)`: where old's card was open, `openCard(fresh)` (it builds it) in place of setting
    `aria-expanded` and `hidden` by hand.
  - `pickHere` and `showPicker`: open the card first, then find `details.picker` in it.
  - Update test_library_card.py's and test_library_page.py's assertions that expected a card built with the list,
    if 1d.1 left any.
  - The docs above.
- [ ] **Step 4: Run it and see it pass** — the three tests, then
  `nix develop -c pytest -q tests/test_library_card.py tests/test_library_page.py tests/test_web_page.py tests/test_web_page_again.py tests/test_library_page_songbooks.py`
  (`test_a_line_drawn_again_keeps_its_card_open_and_its_drawer_closed` among them); the corpus regenerated and checked.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/rows.js src/caracole/library_assets/library.js
  src/caracole/library_assets/__init__.py AGENTS.md tests/ tests/conformance/` ;
  `git commit -m "feat(library): a song's card is built the first time it opens, not with the list"`.

#### Task 1d.3: The card's parts in order, with a head

**Files:**
- Modify: `src/caracole/library_assets/library.js` (`cardFor`; new `cardHead(s)`)
- Modify: `src/caracole/library_assets/library.css` (`.card-head`, `.card-name`, `.card-by`, `.card-close`)
- Modify: `tests/test_library_card.py` (the two `parts` assertions: `test_a_song_with_no_sheet_has_no_tiles_but_its_notes_and_links`,
  `test_musescore_links_show_beside_a_sheet_too`)
- Modify: `docs/usage.md` ("Library/index.html": the card's paragraphs, "Its chevron opens the song in place…": the
  order of its parts), `AGENTS.md` ("index.html's assets (library_assets/)": the card's order, `.card-head`)
- Test: `tests/test_library_card_place.py`

**Interfaces:**
- Consumes: `cardFor(s)`; card.js `caracoleCard`'s `tiles`, `foot`, `sites`, `findElsewhere`, `progressions`
  (unchanged).
- Produces: `cardHead(s)`: `div.card-head` > `div.card-head-in` > `h2.card-name` (id `card-name-<song id>`, the title,
  then `span.card-by` " · " and the artist) and `button.card-close` (the close glyph, `aria-label` "Close <title>").
  In place it carries `aria-hidden="true"` and its button `tabindex="-1"` (the line's own head says the same); 1d.4
  shows it, 1d.6 makes it the pane's heading.

- [ ] **Step 1: Write the failing test** — `test_a_cards_parts_come_in_the_phones_order` (parametrized over
  `"390,844"` and `"1280,900"`): `hotel(conn, cfg)` with `info.json` (`put`), its MuseScore link (as
  test_musescore_links_show_beside_a_sheet_too inserts one) and progressions (`progression_library`'s way of
  recording them for Hotel California); served (`SERVED`); open the card; its children's first classes are
  `["card-head", "facts", "tiles", "foot", "card-sites", "find-elsewhere", "progressions"]`; the foot's buttons
  `["Fetch again", "Use LaCuerda's sheet", "Add to a songbook…", "⋯"]` with Remove inside the ⋯ menu; the head's text
  `"Hotel California · Eagles"`. And Yesterday (not found, served): `["card-head", "facts", "actions", "foot",
  "card-sites", "find-elsewhere"]`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card_place.py::test_a_cards_parts_come_in_the_phones_order`:
  the parts come as `[…, "tiles", "card-sites", …, "foot"]`.
- [ ] **Step 3: Implement** — `cardFor(s)` pushes, in this order, at every width (the pane shows the same element):
  `cardHead(s)`; the facts; what needs you (the picker or why there is none, the YouTube note, the sheet from a
  YouTube video, the LaCuerda pick, Look in the index); the tiles; the foot (Fetch again, Use LaCuerda's sheet, Add
  to a songbook…, ⋯ with info.json and Remove); the Files group and the alphaTab note; On the sites; Elsewhere;
  Progressions. `.card-head` until 1d.4: `display: none`. The two older `parts` assertions take the new order. The
  docs above.
- [ ] **Step 4: Run it and see it pass** — the new test and `nix develop -c pytest -q tests/test_library_card.py`;
  the corpus regenerated and checked.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/ tests/ tests/conformance/ docs/usage.md AGENTS.md` ;
  `git commit -m "feat(library): a card's parts in the phone's order: facts, tiles, actions, sites, progressions last"`.

#### Task 1d.4: The card's head sticks under the bar; closing brings the line back

**Files:**
- Modify: `src/caracole/library_assets/rows.css` (`.line-panel`: `display: flex; flex-direction: column`, its gap and
  padding kept)
- Modify: `src/caracole/library_assets/library.css` (`--bar-h`, `.card-head`'s stuck state, `.head-away`)
- Modify: `src/caracole/library_assets/library-screens.css` (`scroll-margin-top: calc(var(--bar-h) + 8px)` in place of
  `108px`)
- Modify: `src/caracole/library_assets/library.js` (the bar's height, the away watch, the close)
- Modify: `docs/usage.md` ("Library/index.html": the card's paragraphs: a long card's head sticks under the search
  bar, and closing it brings its line back)
- Test: `tests/test_library_card_place.py`

**Interfaces:**
- Consumes: `cardHead`, `onToggle`, 1c's `.searchbar`.
- Produces: `--bar-h` on `:root` (the sticky bar's height in px, `0px` until measured); the class `head-away` on a
  card in place whose line's chevron is under the bar while the card is still on the screen.

Why not the line's own head: a line is a grid, and a sticky grid item stays inside its grid area, so the title row
can't stick past itself; wrapping the head would take `.line-more` and `.line-meta` out from under the line, which
card.css and lane 2's `progressIn` select. A flex column's child sticks within the whole column, so the head is the
card's own, in its panel.

- [ ] **Step 1: Write the failing test** — at 390 × 844 (`Browser(mobile=True)`, file page):
  - `test_a_long_cards_head_sticks_under_the_bar_and_closes_it`: Hotel California (`hotel`) with its UG drawer open
    (the card taller than the screen); scroll until the line's chevron is above the bar's bottom; then the card's
    `.card-head-in` is visible (`checkVisibility({visibilityProperty: true})`), its top equals the bar's bottom ±1, and
    its name is one line; tapping `.card-close` closes the card (`aria-expanded` `"false"`) and the line's top is
    between the bar's bottom and the viewport's middle. Scrolled back to the top with the card open, the head is
    hidden again.
  - `test_closing_by_the_chevron_brings_the_line_back_too`: the same, closing with the line's chevron reached by
    `scrollBy` so that only its lower half shows.
  - `test_with_reduced_motion_closing_lands_at_once` (`Emulation.setEmulatedMedia` `prefers-reduced-motion: reduce`):
    `scrollY` read in the same task as the click equals the one a frame later.
  - `test_at_320_px_a_chinese_or_long_name_stays_one_line` (320 × 640): 宋冬野 · 斑马，斑马 and a 120-character title;
    each card head's name one line (`clientHeight` ≤ 1.5 × its line height), cut short (`scrollWidth > clientWidth`
    for the long one), its close 44 × 44; `document.documentElement.scrollWidth <= 320`.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card_place.py -k "sticks or chevron_brings or reduced_motion or 320"`:
  the head is `display: none`.
- [ ] **Step 3: Implement** —
  - The bar's height: one `ResizeObserver` on `.searchbar` writes `--bar-h` from `borderBoxSize[0].blockSize` and
    remakes the away watch with `rootMargin: "-<h>px 0px 0px 0px"`.
  - The away watch: an `IntersectionObserver` observing the chevron of each card open in place (from `onToggle`;
    unobserved on close), which sets `head-away` on the card when its chevron is not intersecting and
    `boundingClientRect.top < rootBounds.top`, and takes it off otherwise. No layout read.
  - CSS: `.line-panel > .card-head { display: block; position: sticky; top: var(--bar-h); z-index: 1; height: 0; }`;
    `.card-head-in` absolute over the card's width, `min-height: 44px`, `background: var(--card)`, a bottom
    divider, `visibility: hidden`; `.head-away > .card-head > .card-head-in { visibility: visible; }`; `.card-name`
    one line with an ellipsis; no transition.
  - Closing in place (from `onToggle(false, …)`, whatever closed it): `line.scrollIntoView({ block: "nearest",
    behavior: smooth() })`. `.card-close` in place calls `closeCard(line)`.
  - The docs above.
- [ ] **Step 4: Run it and see it pass** — the four tests, and
  `nix develop -c pytest -q tests/test_library_card.py tests/test_library_page.py -k "card or line"`; the corpus.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/ tests/ tests/conformance/ docs/usage.md` ;
  `git commit -m "feat(library): a long card's head sticks under the search bar, and closing it brings its line back"`.

#### Task 1d.5: (moved to lane 3)

Back closing the card's ⋯ menu is Task 3b.5's (the plan's "Where the lanes meet" 2), which documents it too. This stage keeps one guard, in Task 1d.6's tests: opening a card adds no history entry, at 390 × 844 and 1280 × 900 (`history.length` unchanged after `openCardOf`).

#### Task 1d.6: The laptop: one column under 1200 px, the list and the pane from 1200 px

**Files:**
- Modify: `src/caracole/library_assets/body.html` (the library view's columns and the pane)
- Modify: `src/caracole/library_assets/library.css` (the column, the columns, the pane, `.line.selected`)
- Modify: `src/caracole/library_assets/library.js` (placing a card; the helpers that find a line's card wherever it
  is, used where the code assumed the card inside its line; 1c.7's click listener finds a link's line by `itemOf`)
- Modify: `docs/usage.md` ("Library/index.html": the card's paragraphs: the pane from 1200 px and the 800 px column),
  `AGENTS.md` ("index.html's assets (library_assets/)": the pane `#card-pane` from 1200 px and
  `cardOf`/`itemOf`/`partsOf`/`inItem`; "##### The library page's list": the card in the pane),
  `src/caracole/library_assets/__init__.py` (card.css and card.js's paragraph: "…the first time it opens, under the
  line or in the pane")
- Modify, only if lane 2's Task 2.6 has merged ("Where the lanes meet" 7): `src/caracole/library_assets/steps.css`
  or library.js (the selected line's `ol.step-list` shown in the pane), as a named crossing
- Test: `tests/test_library_card_place.py`; and, only if Task 2.6 has merged, `tests/test_web_page_steps.py`

**Interfaces:**
- Consumes: `onToggle`, `cardHead`, `openCard`/`closeCard`, `--bar-h`, `refill`.
- Produces:
  - body.html: in `#library-view`, after `.searchbar`, `<div class="lib-cols"><div class="lib-main">` around
    `__REQUESTED__`, the results, the toolbar, `#prog`, `#jump`, `#count`, `#list` and the noscript, then
    `<aside class="card-pane" id="card-pane" aria-label="Song"><p class="pane-empty">Open a song to see its card
    here.</p></aside></div>`.
  - library.js: `paneWide` (`matchMedia("(min-width: 1200px)")`), `selected` (the line whose card the pane holds, or
    null), `selectLine(line, panel, byKeyboard)`, `unselect({ keepOpen })`; `cardOf(item)` (by the chevron's
    `aria-controls`), `itemOf(node)` (`node.closest("article")`, else `selected` for a node in the pane), `partsOf(item)`
    (`[item]`, and its card when it is outside it), `inItem(item, selector)` (the first match in `partsOf(item)`).
  - CSS: `.line.selected` with `aria-current="true"`; `.card-pane`, `.pane-empty`; `#card-pane .foot-menu` (the one
    way lane 1 names a card's `.foot*` part, which 3a.1's guard allows); from 1200 px the line's title column sized and
    `.line-title > .line-plays` wrapping below the title ("Where the lanes meet" 12).
  - The guard "Where the lanes meet" 2 moved here: opening a card adds no history entry, at 390 × 844 and 1280 × 900.

- [ ] **Step 1: Write the failing test** — on the file page, in `Browser`:
  - `test_from_1200_px_the_list_and_an_empty_pane` (1280 × 900 and 1200 × 900): `.pane-empty` shows "Open a song to
    see its card here."; `#list`'s width is 760 at 1280 and at least 700 at 1200; the pane's 400–480, right of the
    list.
  - `test_a_title_puts_its_card_in_the_pane_and_marks_its_line`: click Creep's title: `cardOf(line)` is in
    `#card-pane`, its `.card-name` "Creep · Radiohead" without `aria-hidden`, the line `.selected` with
    `aria-current="true"`, its chevron `aria-expanded="true"`, `.pane-empty` hidden, `history.length` unchanged. Then
    Karma Police's chevron: Creep's line no longer selected and its card back inside it, hidden; Karma Police's in the
    pane. Karma Police's chevron again: the pane empty.
  - `test_the_keyboard_goes_into_the_pane_and_escape_comes_back`: focus Creep's chevron, `press("Enter")`: the focus on
    the pane's `.card-name`; `press("Escape")`: on Creep's chevron, the card still in the pane.
  - `test_crossing_1200_px_moves_the_open_card`: select Creep at 1280; `Emulation.setDeviceMetricsOverride` to 1000:
    its card inside its line, open, no line selected, the pane not shown; back to 1280: in the pane, Creep selected.
  - `test_under_1200_px_one_column_of_800`: at 1000 × 900 `#library-view` is 800 wide and centred; `.searchbar` and
    `.counts-row` inside it; Creep's card opens under its line.
  - `test_the_pane_empties_when_its_line_leaves_the_list`: select Creep, type "karma": the pane empty, no `.selected`
    line.
  - `test_the_panes_head_keeps_a_long_name_on_one_line`: 宋冬野 with a 120-character title, selected at 1280: its
    `.card-name` one line, cut short.
  - `test_opening_a_card_adds_no_history_entry` (parametrized over 390 × 844, `mobile=True`, the card in place, and
    1280 × 900, the card in the pane): `history.length` and `history.state` the same before and after
    `openCardOf(lineOf("Creep"))`, and after closing it.
  - `test_on_a_laptop_chips_wrap_under_the_title_and_never_push_the_key_off` (1280 × 900): Hotel California
    (test_library_card.py's `hotel`: five play buttons, chips of 100–150 px each once lane 3a has merged) and Creep (one
    play button): each line's `.line-key` and `.line-more` keep their columns (their lefts the same on both lines
    within 1 px, their rights inside the 760 px list), every `.play` inside its line, Hotel California's
    `.line-plays` below its title (its top ≥ the `h3`'s bottom − 1) when they don't fit beside it, its `h3` at least
    half the line's width; `document.documentElement.scrollWidth <= innerWidth`.
  - `test_a_song_opened_from_the_pane_is_recently_opened` (1280 × 900, `STAY` as 1c.7's tests): select Creep, click
    its card's first `a.tile-open` in `#card-pane`; focus `#q`: `#recent`'s first link is Creep's, its href the
    tile's.
  - Only if Task 2.6 has merged: `test_on_a_laptop_the_selected_lines_steps_are_listed_in_the_pane` in
    tests/test_web_page_steps.py (served, 1280 × 900; Estopa - Tu Calorro, `NOT_ON_UG`, as
    `test_a_lookup_that_ends_otherwise_keeps_its_bar_frozen_under_its_line` sets it up): once it ended, click the
    line's title (its card in the pane): an `ol.step-list` inside `#card-pane` is visible with `steps_of`'s six
    entries, while the line in `#list` shows its frozen `.step-bar` and no list.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card_place.py -k "pane or 1200 or 800 or history_entry or chips_wrap"`:
  no `.pane-empty` (the 390 px no-entry case may pass already and stays as the guard).
- [ ] **Step 3: Implement** —
  - CSS: `.card-pane { display: none; }`; `@media (min-width: 720px) and (max-width: 1199px) { #library-view {
    max-width: 800px; margin: 0 auto; } }` (the masthead and the other tabs keep the page's width);
    `@media (min-width: 1200px)`: `.lib-cols { display: grid; grid-template-columns: minmax(0, 760px) minmax(400px,
    480px); column-gap: 24px; align-items: start; }`, `.card-pane { display: block; position: sticky; top:
    calc(var(--bar-h) + 8px); max-height: calc(100vh - var(--bar-h) - 16px); overflow-y: auto; overscroll-behavior:
    contain; margin-top: 10px; background: var(--card); }`, the pane's `.card-head` static and always visible,
    `#card-pane .foot-menu { top: calc(100% + 6px); bottom: auto; }` (its ⋯ menu opening downward), `.line.selected {
    background: var(--raised); box-shadow: inset 3px 0 0 var(--accent); }`; room for chips: the line's title column
    `minmax(0, 1fr)` beside its key and chevron columns, `.line-title { flex-wrap: wrap; }` and `.line-title >
    .line-plays { max-width: 100%; }`, so the play buttons wrap below the title rather than push the key off the line.
  - `onToggle(open, panel, e)` of a song's line: wide and open → `selectLine(line, panel, e.isTrusted && e.detail ===
    0)`; closed and `line === selected` → `unselect()`; narrow → 1d.4's in-place behaviour.
  - `selectLine`: closes the line selected before (`closeCard`); moves `panel` into the pane; `.selected` and
    `aria-current` on the line; the head out of `aria-hidden`, its close tabbable, the pane `aria-labelledby` its
    name; by keyboard, the focus to `.card-name` (`tabindex="-1"`). `unselect({ keepOpen })` puts the card back right
    after the line's chevron, hidden unless `keepOpen`, the head hidden from a screen reader again, and the empty line
    shown. An Escape the card's own parts left (`!e.defaultPrevented`) in the pane: the focus to the selected line's
    chevron, `stopPropagation`.
  - `paneWide`'s `change`: wide → the card opened last of those open in place goes to the pane, the others close;
    narrow → `unselect({ keepOpen: true })`.
  - After `render()` and `drawGroups()`: `if (selected && !selected.checkVisibility()) unselect()` (one element).
  - Recently opened: 1c.7's click listener takes the link's line from `itemOf(link)` (a link in the pane is the
    selected line's, which keeps its `data-id`) in place of `link.closest("article.line[data-id]")`, so a play or a
    tile opened from the pane is remembered (`rememberOpened(itemOf(link), link)`).
  - Only if Task 2.6 has merged ("Where the lanes meet" 7): the selected line's `.steps > ol.step-list` shows in the
    pane (moved into `#card-pane` with the card and back with it, or the rule widened), and steps.css's
    `.line:has(> .line-more[aria-expanded="true"])` rule leaves a `.selected` line its frozen bar; else this is Task
    2.6's, when it merges second.
  - Use the helpers where the code took the card to be inside its line: `postInPlace` and `removeForm`'s submit
    (`itemOf(form)`), `countdownIn` (`partsOf(item)`'s form buttons), `stopRemoval` (the item holding the focus and its
    Remove, through `partsOf`/`inItem`), `paint` (`.actions.again`, `form.youtube-sheet`, `form.pick-form` through
    `inItem`), `pickHere`, `showPicker`, `refill` (old's card read with `cardOf` before the merge: in the pane, it
    gives its place to fresh's card, opened; outside old and closed, it goes), `removed`'s `card-gone` (not for a
    selected line).
  - The docs above.
- [ ] **Step 4: Run it and see it pass** — the tests, and every Chromium test of the library page at its default 1280
  width: `nix develop -c pytest -q tests/test_library_card.py tests/test_library_card_place.py tests/test_library_page.py tests/test_library_plays.py tests/test_library_filter.py tests/test_library_page_songbooks.py tests/test_library_search_mode.py`
  (and `tests/test_web_page_steps.py` if Task 2.6 has merged); the corpus.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/ tests/ tests/conformance/ docs/usage.md AGENTS.md` ;
  `git commit -m "feat(library): from 1200 px the list and the selected song's card side by side; one column of 800 px under"`.

#### Task 1d.7: The pane's forms on caracole serve's page

**Files:**
- Modify: `src/caracole/library_assets/library.js` (only what the tests find missing from 1d.6's helpers)
- Modify: `tests/test_web_page.py` (`COUNTDOWN`'s `window.song.querySelector('form.remove button')` through
  `cardOf`, if 1d.1 left it)
- Test: `tests/test_library_card_place.py`

**Interfaces:**
- Consumes: 1d.6's pane and helpers; test_web_page.py's `serve`, `FakeCaracole`, `QUICK`, `press_remove`;
  select.js's "caracole:pick".
- Produces: nothing new.

- [ ] **Step 1: Write the failing test** — served at 1280 × 900 (`serve(runner, cards.KIT, timers=QUICK)`):
  - `test_fetch_again_from_the_pane_follows_on_the_songs_line`: select Creep; click the pane's Fetch again: one
    `POST /lookup` with Creep's id and identity; the line's `.progress` says it runs; the pane's card has no
    `.actions.again` while it does.
  - `test_remove_from_the_pane_counts_down_on_the_line_and_undo_keeps_it`: the pane's Remove (behind ⋯): the line says
    "Removing in 5 s · Undo", the pane's form buttons disabled; Undo: "Not removed", the buttons enabled.
  - `test_a_song_removed_from_the_pane_empties_it`: Remove, the seconds over: the line says Removed, `#card-pane` holds
    no `.line-panel` and `.pane-empty` shows.
  - `test_add_to_a_songbook_from_the_pane_starts_select_with_the_song`: `body.selecting`, Creep picked (select.js's box
    on its line checked).
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card_place.py -k "from_the_pane"`:
  whatever 1d.6 left unrouted fails here (the removal's held buttons are the likeliest).
- [ ] **Step 3: Implement** — route what failed through `itemOf` / `partsOf` / `inItem`; no new mechanism.
- [ ] **Step 4: Run it and see it pass** — the tests and `nix develop -c pytest -q tests/test_web_page.py tests/test_web_page_again.py tests/test_web_page_same_song.py tests/test_library_page_songbooks.py`.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/library.js tests/ tests/conformance/` ;
  `git commit -m "fix(library): Fetch again, Remove and Add to a songbook from the pane act on the song's line"`.

#### Task 1d.8: Merge stage 1d

**Files:**
- Check (written by 1d.2 to 1d.6): `docs/usage.md` ("Library/index.html": the card's paragraphs, "Its chevron opens
  the song in place…" to "…keeps its card open, its drawer closed": the order, the head that sticks, the pane from
  1200 px and the 800 px column; Back closing ⋯ is 3b.5's, not this stage's), `AGENTS.md` ("index.html's assets
  (library_assets/)": a song's card built on first open by `cardFor`, its order, `.card-head`, the pane `#card-pane`
  from 1200 px and `cardOf`/`itemOf`/`partsOf`/`inItem`; "##### The library page's list": the card in the pane),
  `src/caracole/library_assets/__init__.py` (card.css and card.js's paragraph: "library.js `cardFor` puts its parts in
  the line's panel, the first time it opens, under the line or in the pane")

- [ ] **Step 1:** Rebase onto `main` (1a–1c and whatever of lanes 2–4 merged); with lane 3 merged, check its card.css
  selectors match `.song-card` and `:not(.selected)` (raised above), else raise it again before merging.
- [ ] **Step 2:** `nix develop -c pytest -q` (the whole suite); the corpus regenerated twice and checked; `nix develop
  ./android -c gradle -p android test` (`LibraryPageTest` and the `web` and `job-views` replays read the regenerated
  vectors; a break there is fixed in this lane's Kotlin, `server/page/LibraryPage.kt`);
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus moved); `nix flake
  check`.
- [ ] **Step 3:** On screen: `nix develop -c python docs/screenshots/make.py --serve`, at 390 (a phone's window) and
  1280: a long card's head, the pane.
- [ ] **Step 4:** Check the docs above against what the stage does (a gap goes into a `docs:` commit here), then
  `git checkout main && git merge --no-ff feat/library-card-place`, then push main:
  `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

---

### Stage 1e · Long lists

#### Task 1e.1: A library of 2,000 songs, and its measurement

**Files:**
- Create: `tests/helpers/big_library.py`
- Test: `tests/test_big_library.py`
- Modify: `docs/superpowers/specs/2026-11-17-library-page-redesign-design.md` ("Measurements before building": a
  table "2,000 songs on a phone", the before column)
- Modify: `AGENTS.md` ("### Running the tests": `python -m tests.helpers.big_library measure`)

**Interfaces:**
- Produces:
  - `build(folder: Path, songs: int = 2000, *, seed: int = 7) -> Path`: a library in `folder`, built with caracole's
    own functions as tests/helpers/e2e_library.py builds its computer (no request, no clock in what it writes), and its
    index.html, whose path it returns. Its songs: found, each with `sheet.txt`, `sheet.html` and `sheet.pdf` stand-ins
    and a key; every fifth a Guitar Pro file, every ninth a harmonica tab; artists so that 55 % are one-song artists,
    the rest 2–15 songs, one artist 150; 5 % Chinese names; a few 120-character titles. Deterministic.
  - `measure(page: Path, *, width=390, height=844, mobile=True, cpu=4) -> dict`: the page in `Browser`, CPU slowed
    (`Emulation.setCPUThrottlingRate`), `Performance.enable`; timings written by a script injected with
    `Page.addScriptToEvaluateOnNewDocument`. It records: `drawn_ms` (navigation start to the body losing `drawing`),
    `fcp_ms`; `Performance.getMetrics`' `ScriptDuration`, `LayoutDuration`, `RecalcStyleDuration`, `LayoutCount`,
    `Nodes`, `JSHeapUsedSize` after load; `scroll` (to the end, 800 px a frame: `frames`, `p50_ms`, `p95_ms`,
    `max_ms`, `over_50ms`, `long_tasks`); `type_ms` ("a" typed in `#q`, to the second frame after its input event);
    `open_ms` (a chevron in the middle of the list clicked, to the next frame).
  - `python -m tests.helpers.big_library measure [--songs N] [--src PATH] [--out FILE]` (in nix develop, from the
    repository's root): builds in a temporary folder, prints the JSON; `--src`, another checkout's `src/` to build
    the page from (the commit before 1d merged, to show what the card built on first open gained).

- [ ] **Step 1: Write the failing test** — `test_the_big_library_has_every_shape` (slow): `build(tmp_path, 400)`: 400
  songs in the page's data, one-song artists 50–60 % of artists, one artist of 30 or more (scaled), a Chinese title;
  `test_measure_answers_every_number` (slow, `@in_chromium`, 200 songs): every key above present, each number ≥ 0,
  `scroll.frames` > 0.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_big_library.py`: no module.
- [ ] **Step 3: Implement** — as above; run `measure` on 2,000 songs at the branch's base (and with `--src` at the
  commit before 1d's merge) and write the numbers in the spec's new table (columns: before 1d, before 1e, after 1e),
  with how they were taken: headless Chromium, 390 × 844, touch, CPU 4× slower. If the owner's phone is at hand
  (wireless adb), the same five actions by hand in Chrome's remote DevTools on the page `build` wrote, a row of their
  own. AGENTS.md's line for the command.
- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_big_library.py`.
- [ ] **Step 5: Commit** — `git add tests/helpers/big_library.py tests/test_big_library.py docs/superpowers/specs/2026-11-17-library-page-redesign-design.md AGENTS.md` ;
  `git commit -m "test(library): a library of 2,000 songs, and how the list does with it on a phone"`.

#### Task 1e.2: One SVG sprite for the glyphs

**Files:**
- Modify: `src/caracole/library_assets/rows.js` (`glyph`, a `sprite()` made once)
- Modify: `src/caracole/library_assets/rows.css` (`.glyph-sprite`)
- Modify: `AGENTS.md` ("index.html's assets": the glyphs, one sprite), `src/caracole/library_assets/__init__.py`
  (rows.js's paragraph: the glyphs one sprite)
- Test: `tests/test_library_long.py` (new: stage 1e's tests)

**Interfaces:**
- Produces: `glyph(name, label)` as today (`svg.glyph.glyph-NAME`, its size, stroke, `aria-hidden` or
  `role="img"`/`aria-label`/`title`), drawing `<use href="#glyph-NAME">`; the first call puts in the document one
  `<svg class="glyph-sprite" aria-hidden="true" focusable="false">` with a `<symbol id="glyph-NAME" viewBox="0 0 24
  24">` of every `GLYPHS` entry's paths. Same on the lookup page, which runs rows.js.

- [ ] **Step 1: Write the failing test** — `test_every_glyph_is_one_use_of_one_sprite` (file page, 50 songs, three
  cards and the Filter panel open): one `svg.glyph-sprite`, one `symbol` per `GLYPHS` name; outside it no `path` under
  an `svg.glyph`; each `svg.glyph` holds one `use` whose `href` names a symbol there, its `getBBox().width > 0`; the
  same on the served lookup page with results (test_web_lookup_page.py's `served`).
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_long.py::test_every_glyph_is_one_use_of_one_sprite`:
  no sprite.
- [ ] **Step 3: Implement** — as above; `.glyph-sprite { position: absolute; width: 0; height: 0; overflow: hidden; }`
  (no `style` attribute: the policy allows none). `test_no_external_resources_and_no_urls_outside_the_data` still finds
  the SVG namespace once. The docs above.
- [ ] **Step 4: Run it and see it pass** — the test, `nix develop -c pytest -q tests/test_library_filter.py tests/test_library_plays.py tests/test_library_page.py tests/test_web_lookup_page.py`
  (they read `glyph glyph-NAME` classes); the corpus.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/ tests/ tests/conformance/ AGENTS.md` ;
  `git commit -m "perf(library): the glyphs, one SVG sprite drawn by <use>"`.

#### Task 1e.3: Groups and runs off the screen aren't laid out

**Files:**
- Modify: `src/caracole/library_assets/library.js` (`render`: groups and runs marked, runs made)
- Modify: `src/caracole/library_assets/library.css` (`.cv`, the heights, the dividers across runs)
- Modify: `AGENTS.md` ("index.html's assets": the runs and `content-visibility`)
- Test: `tests/test_library_long.py`

**Interfaces:**
- Consumes: 1b's band groups and folded groups; `big_library.build`.
- Produces: `RUN = 40`, `RUN_MIN = 8`, `BIG_GROUP = 50`; `div.run` (a run of lines or of folded groups); the class
  `cv` on each band group and run that gets `content-visibility: auto`; the custom properties `--bands`, `--lines`,
  `--folds` (counts, set with `style.setProperty`) and `--band-h`, `--line-h`, `--fold-h` (heights, per breakpoint
  and pointer, in library.css).

- [ ] **Step 1: Write the failing test** (slow, `@in_chromium`; `big_library.build(tmp_path, 600)` unless said):
  - `test_groups_and_runs_skip_what_is_off_the_screen` (390 mobile; 1280): each band group and each `div.run` has
    computed `content-visibility` `auto`; no `.line` and no element holding a single line has it; each run holds
    30–50 lines but the last of a sequence, which holds 8 or more, or is no run; every line of `#list` is inside a
    `.cv` or in a sequence shorter than 8.
  - `test_each_estimate_is_within_a_quarter_of_its_height` (390 mobile; 1280; both sorts): each `.cv`'s computed
    `containIntrinsicHeight`'s length against its height once its `style.contentVisibility` is `"visible"`: within 25 %.
  - `test_a_library_of_one_song_artists_is_runs_alone` (300 songs, one artist each; Artist A–Z and Title A–Z).
  - `test_one_artist_of_300_songs_is_cut_into_runs_inside_its_group`: its group isn't `.cv`; its runs are.
  - `test_dividers_stay_between_runs_and_groups`: the first line of each run but the list's first, and each group but
    the first, have a 1 px top border.
  - `test_find_in_page_finds_a_song_off_the_screen`: `window.find(<the last song's title>)` is true.
  - `test_a_cards_menu_at_a_runs_top_is_not_cut` (390 × 844, mobile: the card in place, inside its run, where a run's
    containment could cut it; at 1280 it would be in the pane, outside every run): the card of a run's first line with
    no tiles, its ⋯ open: `elementFromPoint` at Remove's centre (served) is Remove.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_long.py -k "runs or estimate or dividers or find_in_page or menu"`:
  no `.cv`.
- [ ] **Step 3: Implement** — in `render()`, after the groups are drawn: a band group of `BIG_GROUP` lines or fewer is
  `.cv` with `--bands: 1; --lines: n`; a larger one has its lines in runs of `RUN`, each `.cv` with `--lines`;
  consecutive folded groups go into runs of `RUN` (`--folds`), the last of a sequence a `.cv` only if it holds
  `RUN_MIN` or more; Title A–Z and Recently added: the flat lines in runs of `RUN` (`--folds` or `--lines`, as 1b draws
  them). CSS: `#list .cv { content-visibility: auto; contain-intrinsic-size: auto calc(var(--bands, 0) * var(--band-h)
  + var(--lines, 0) * var(--line-h) + var(--folds, 0) * var(--fold-h)); }`, the heights measured once at 390 coarse
  and 1280 fine and written in; `#list .cv:has(.line-panel:not([hidden])) { content-visibility: visible; }` (an open
  card's drawer and menu are never clipped by a run's containment); the dividers' selectors follow the runs. The
  docs above.
- [ ] **Step 4: Run it and see it pass** — the tests; `nix develop -c pytest -q tests/test_library_page.py tests/test_library_page_songbooks.py tests/test_library_filter.py`
  (the A–Z strip, Select's boxes); the corpus.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/ tests/ tests/conformance/ AGENTS.md` ;
  `git commit -m "perf(library): groups and runs of lines off the screen are not laid out"`.

#### Task 1e.4: No layout read across many lines

**Files:**
- Modify: whatever the test finds reading layout line by line (in lane 1's files; a read in lane 2's or 3's code is
  raised)
- Test: `tests/test_library_long.py`

**Interfaces:**
- Consumes: `big_library.build`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test** — `test_no_action_reads_the_layout_of_more_lines_with_more_songs` (slow,
  `@in_chromium`, 390 mobile): `Page.addScriptToEvaluateOnNewDocument` wraps `getBoundingClientRect`,
  `getClientRects`, `checkVisibility`, `getComputedStyle` and the `offset*`, `client*` and `scroll*` getters, counting
  the calls on an element inside `#list`, per action: the load; "ra" typed; a card opened; the box cleared; a scroll to
  the end. For 200 songs and 2,000: each action's count is 12 or fewer, and the two counts differ by 2 at most.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_long.py::test_no_action_reads_the_layout_of_more_lines_with_more_songs`:
  it fails where some code reads every line; if it passes at once it stays as the guard, and the commit says so.
- [ ] **Step 3: Implement** — move any per-line read the test names to an observer or to the one element concerned.
- [ ] **Step 4: Run it and see it pass** — the test.
- [ ] **Step 5: Commit** — `git add tests/test_library_long.py src/caracole/library_assets/ tests/conformance/` ;
  `git commit -m "test(library): no action reads the layout of more lines when the library grows"`.

#### Task 1e.5: Merge stage 1e

**Files:**
- Modify: `docs/superpowers/specs/2026-11-17-library-page-redesign-design.md` (the table's after column: measured at
  the merge, after the stage)
- Check (written by 1e.1 to 1e.3): `AGENTS.md` ("index.html's assets": the runs and `content-visibility`, the sprite;
  "### Running the tests": `python -m tests.helpers.big_library measure`), `src/caracole/library_assets/__init__.py`
  (rows.js's paragraph: the glyphs one sprite)

- [ ] **Step 1:** Rebase onto `main`; `measure` again, the after column written; a number worse than before is
  explained there or fixed before merging.
- [ ] **Step 2:** `nix develop -c pytest -q`; the corpus regenerated twice and checked; `nix develop ./android -c
  gradle -p android test`; `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus
  moved); `nix flake check`.
- [ ] **Step 3:** On screen, 2,000 songs (`build`'s page opened as a file) at 390 and 1280: scrolling, the A–Z strip,
  find-in-page; check the docs above (a gap goes into a `docs:` commit here).
- [ ] **Step 4:** Commit (`docs: the list with 2,000 songs, measured`); `git checkout main && git merge --no-ff
  perf/library-long-lists`, then push main: `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

---

### Stage 1f · A calmer page

#### Task 1f.1: Four corner radii

**Files:**
- Modify: `src/caracole/library_assets/base.css` (`:root`: `--radius-s: 4px; --radius-m: 8px; --radius-l: 12px;
  --radius-pill: 999px;` and its own radii)
- Modify: `src/caracole/library_assets/library.css`, `filter.css`, `rows.css` (not `.play` rules), `sync.css`,
  `sites.css`, `picker.css` (every `border-radius` one of the four, or 0)
- Create: in `tests/helpers/targets.py`, `odd_radii(skip)`: the JavaScript expression that lists each element (a short
  path) whose computed corner radius is none of `0px`, `4px`, `8px`, `12px`, `999px`, `50%`, counting rendered
  elements alone (an element with `!el.checkVisibility()` is left out) and leaving out every element inside one the
  skip list matches (`skip` a tuple of selectors; an element is left out when `el.closest(skip.join(", "))`)
- Modify: `AGENTS.md` ("The pages caracole writes and serves" or "index.html's assets": base.css's four radii),
  `src/caracole/library_assets/__init__.py` (base.css's paragraph: the radius tokens)
- Test: `tests/test_page_calm.py` (new: stage 1f's tests)

**Interfaces:**
- Produces: the four tokens, for every stylesheet built on base.css; `odd_radii`.

- [ ] **Step 1: Write the failing test** — `test_the_library_page_has_four_corner_radii` (`@in_chromium`, served, 390
  mobile and 1280, light and dark): with each tab shown in turn, the Filter panel open, a search's results, the Sync
  sheet open and a request in the tray, `odd_radii(OTHER_LANES)` is `[]`, where `OTHER_LANES = (".line-panel",
  ".play", "#songbooks", ".pickbar", ".pick", ".step-chips", "#requests")`: the elements of the lanes not merged yet
  (raised above; lane 2's bar segments are square, radius 0, and need no place in it). The last of 1f, lane 2, 3b and
  lane 4 to merge empties it (`odd_radii(())`); if 1f.1 is itself written after the three others merged, it is `()`
  from the start.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_page_calm.py::test_the_library_page_has_four_corner_radii`:
  `11px`, `14px`, `16px`…
- [ ] **Step 3: Implement** — each radius to its token: 6 px or less `--radius-s` (marks, `code`, a source's letters),
  7–11 px `--radius-m` (buttons, fields, chips, the key, the jump letters), 12–20 px `--radius-l` (boxes, panels,
  dialogs, sheets, the tray open, the request form), pills and dots `--radius-pill`; a corner set (`11px 11px 0 0`)
  with its token; a computed one (`calc(var(--mark-size) / 2)`) is `.play`'s, lane 3's. The docs above.
- [ ] **Step 4: Run it and see it pass** — the test, `nix develop -c pytest -q tests/test_library_page.py tests/test_library_filter.py tests/test_web_pages.py`;
  the corpus.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/ tests/ tests/conformance/ AGENTS.md` ;
  `git commit -m "style(library): four corner radii, as base.css tokens"`.

#### Task 1f.2: No outline around the list or the key; one weight a role

**Files:**
- Modify: `src/caracole/library_assets/library.css` (`.lines, .groups`, the first band's corners)
- Modify: `src/caracole/library_assets/rows.css` (`.rows`, `.line-key`, `.row-key`, `.row-title`, `#results` titles)
- Modify: `AGENTS.md` ("The pages caracole writes and serves" or "index.html's assets": the list with no outline),
  `docs/usage.md` only where it describes a look that changed (the line's key "in a small box" in
  "Library/index.html" becomes plain muted text)
- Test: `tests/test_page_calm.py`

**Interfaces:**
- Consumes: 1b's band (`.artist-title`, its counts `.artist-counts`).
- Produces: nothing new.

- [ ] **Step 1: Write the failing test** — `test_no_outline_around_the_list_or_the_key` (`@in_chromium`, file page,
  390 mobile and 1280, light and dark, Artist A–Z and Title A–Z, and a served search's results): `#list .groups`,
  `#list section.flat .lines` and the lookup page's `.rows` have no border (each width `0px`) and `box-shadow`
  `none`; each line after a group's first keeps a 1 px top border; `.line-key` has no border, the colour of a probe
  styled `color: var(--muted)`, weight 700; every song title (`.line-title h3`, `#results .line h3`, `.row-title`)
  weight 600; a band's name weight 700 in `var(--artist)`'s colour; `.artist-counts` in `--muted`'s.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_page_calm.py::test_no_outline_around_the_list_or_the_key`:
  the list's 1 px border.
- [ ] **Step 3: Implement** — `.lines, .groups` and `.rows`: no border, shadow or background of their own (the bands
  keep theirs, the dividers stay); `.line-key`/`.row-key`: plain text, `color: var(--muted); font-weight: 700`, no
  border or padding; titles 600 everywhere, the results' "one weight for all" kept at 600. The docs above.
- [ ] **Step 4: Run it and see it pass** — the test, `nix develop -c pytest -q tests/test_library_page.py tests/test_web_page_search.py tests/test_web_lookup_page.py`
  (their contrast and layout tests); the corpus.
- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/ tests/ tests/conformance/ AGENTS.md docs/usage.md` ;
  `git commit -m "style(library): no outline around the list or the key; titles semi-bold, counts and keys muted"`.

#### Task 1f.3: caracole serve's own pages, and the phone's, as calm

**Files:**
- Modify: `src/caracole/web/pages.py` (`PAGE_STYLE`'s own radii), `src/caracole/web/lookup_page.py` (`STYLE`'s),
  `src/caracole/web/guitar.css` (its radii; `2px` to `--radius-s`)
- Modify: the corpus: `tests/conformance/data/caracole/page/message.json`, `tests/conformance/vectors/web/guitar.jsonl`
  and whatever else moves (regenerated, never by hand)
- Test: `tests/test_page_calm.py`

**Interfaces:**
- Consumes: the tokens, `odd_radii`.
- Produces: nothing new. The phone's MessagePage (style from message.json) and GuitarPage (base.css and guitar.css
  copied at build) follow from the files; no Kotlin change expected.

- [ ] **Step 1: Write the failing test** — `test_caracole_serves_own_pages_have_the_same_four_radii` (`@in_chromium`,
  390 mobile and 1280): test_web_pages.py's `pages()` (the pick and the removal), a message page (`pages.page`), the
  lookup page served with results, and the Guitar Pro page (test_web_guitar_browser.py's set-up; skipped without
  `CARACOLE_ALPHATAB_DIR`): `odd_radii(())` is `[]` on each.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_page_calm.py::test_caracole_serves_own_pages_have_the_same_four_radii`:
  `14px`, `16px` on the lookup page.
- [ ] **Step 3: Implement** — each page's own radii to the tokens, as in 1f.1.
- [ ] **Step 4: Run it and see it pass** — the test, `nix develop -c pytest -q tests/test_web_pages.py tests/test_web_lookup_page.py tests/test_web_guitar_browser.py tests/test_library_name_pages.py`;
  the corpus regenerated and checked; `nix develop ./android -c gradle -p android test` (`MessagePageTest`,
  `GuitarPageTest`, the `review`, `choices` and `guitar` replays).
- [ ] **Step 5: Commit** — `git add src/caracole/web/ tests/ tests/conformance/` ;
  `git commit -m "style(web): caracole serve's own pages share the four radii"`.

#### Task 1f.4: Merge stage 1f, and the README's screenshots if lane 1 merges last

**Files:**
- Check (written by 1f.1 and 1f.2): `AGENTS.md` ("The pages caracole writes and serves" or "index.html's assets":
  base.css's four radii, the list with no outline), `src/caracole/library_assets/__init__.py` (base.css's paragraph:
  the radius tokens), `docs/usage.md` (the line's key plain muted text, no longer "in a small box")
- Modify, only if lanes 2, 3b and 4 have all merged: `tests/test_page_calm.py` (`OTHER_LANES` emptied),
  `docs/screenshots/*.png` (only those that changed)

- [ ] **Step 1:** Rebase onto `main`; `nix develop -c pytest -q`; the corpus twice; `nix develop ./android -c gradle
  -p android test`; `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus
  moved); `nix flake check`.
- [ ] **Step 2:** On screen, served and as a file, 390 and 1280, light and dark: the Library, Songbooks, Sites,
  Journal and Share tabs, the lookup page, a pick, a message page, the Guitar Pro page; check the docs above (a gap
  goes into a `docs:` commit here).
- [ ] **Step 3:** The radius skip list: if lanes 2, 3b and 4 have all merged, this merge is the last of 1f, lane 2, 3b
  and lane 4: `OTHER_LANES = ()` and `test_the_library_page_has_four_corner_radii` passes with it (commit
  `test(library): the four radii across the whole page, no lane left out`); else the list stays, for the last of them
  to remove.
- [ ] **Step 4:** Only if lanes 2, 3 (3b) and 4 have all merged (lane 1 the last of the four): retake the README's
  screenshots. `nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python docs/screenshots/make.py`;
  for each picture, `git show HEAD:docs/screenshots/<name>.png > old.png` (outside the repository) and
  `compare -metric AE old.png docs/screenshots/<name>.png null:` (ImageMagick, through `omnibin-shell` if it isn't
  on PATH): `git restore` those with 0 differing pixels, keep the others; commit (`docs: the README's screenshots of
  the redesigned page`). Else leave them to the last lane's merge task.
- [ ] **Step 5:** `git checkout main && git merge --no-ff style/library-calm`, then push main:
  `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

---

## Lane 2 · Progress

The design's "Progress" section: a request's steps as a segmented bar on its song's line, a fixed total, nothing for
the first second, Cancel beside a queued line, a frozen bar under a line that ended otherwise than Ready, and a list of
steps in the open card and the Journal. Python first (outcome.py, feed.py, jobs_routes.py), each data task with its
corpus and its Kotlin port in the same commit; then the page (library.js's progress functions, steps.css, requests.js,
requests.css).

**Branch and worktree** (before 2.1): `git worktree add ../caracole-progress -b feat/progress-bar main`; every path
below is relative to that worktree.

**What this lane owns**: `src/caracole/web/outcome.py`, `src/caracole/web/feed.py` (the Journal's data, outcome.py's
reader), the `view`/`views` signatures in `src/caracole/web/jobs_routes.py`, `library_assets/steps.css`,
`library_assets/requests.js`, `library_assets/requests.css`, and in `library_assets/library.js` only the block around
lines 630–760: `showLine`, `STEP_MARKS`/`STEP_STATES`, `stepsAfter`, `drawSteps`, `showRequest` (the caller of
`showLine` and `drawSteps`: "showLine's steps"), `progressIn`, and the new helpers placed beside them. `status.py` is
unchanged: its words (Queued · N requests ahead…, the running stage lines) stay as they are. Kotlin:
`android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/{Outcomes,JobViews,JobsRoutes,Feed}.kt`,
`.../server/routes/RequestsRoutes.kt`, their tests and replays.

### The contract the tasks build (later tasks and lanes rely on it)

**The view** (`/jobs.json`, `jobs_routes.view`, a song's job), from `outcome.progress(job, line, facts, *, now)`:

- `{}` for a job that runs no lookup (neither `looks_up` nor `from_youtube`), one queued, cancelled or never started
  (`started_at is None`), one whose line is Ready (its steps fold away), and one that has run less than
  `outcome.BAR_AFTER` (`timedelta(seconds=1)`): running with `now - started_at < BAR_AFTER`, or over with
  `finished_at - started_at < BAR_AFTER`.
- Else `{"steps": [...], "at": i, "count": "N of T"}`; `at` and `count` only when there is a step in hand:
  - while it runs, the running step, else the first waiting one (between two steps), else the last;
  - once over, the first step that failed, else none (no `at`, no `count`).
  - `count` is `f"{at + 1} of {len(steps)}"`; the total is every step the job has from its start, so it only rises.

**A step** (`outcome.Chip`, Kotlin `Chip`): `Chip(name, state, site="", found="")`, JSON
`{"name", "site", "state", "found"}` in that order.

- `state`: waiting, running, done, failed, skipped (every stage of it ended skipped: it keeps its place and is over),
  or plain (over and no failure, "Match · not on UG").
- `site`: the site it names, in full (`outcome.SITE_NAMES[tag]`: "Ultimate Guitar", "LaCuerda", "YouTube"); "" for
  none. It replaces today's `source` (a tag).
- `found`: what it found, for the lists: each of its stages that ended done, or failed as the step reads it (the sheet
  a wait stopped, the audio of a YouTube sheet), in order, joined by " · "; a failed one in `_stage_reason`'s words
  when they say something, else as the stage said it; "" for a plain step, a skipped one and one still waiting.

**The Journal** (`/requests.json`, feed.py): the running request's `steps` as today (any kind); a finished request's
`steps` when `outcome.lists_steps(job)` (a lookup or a YouTube sheet that started), placed right after `reason`.

**The page** (library.js, steps.css):

- A running line with steps: `p.progress.barred[role=status]` holds `span.step-segs[aria-hidden=true]` (one
  `i.seg.<state>` a step, a failed one's text "!"), `span.step-at` (`<b>name</b>` and " · site") and
  `span.step-count` (" · N of T"). Its text, which a screen reader hears, is "Sheet · Ultimate Guitar · 3 of 7".
- `div.steps`, the one sibling right after `p` (as `refill` keeps one): once the line is no longer barred (ended, or
  a line that says something else) `div.step-bar[role=img][aria-label="Steps: …"]` (the segments and the words,
  frozen), then always `ol.step-list[aria-label=Steps]`. The list shows only while the line's card is open
  (`.line:has(> .line-more[aria-expanded="true"])`), and the frozen bar hides then.
- `ol.step-list > li.step.<state>`: `span.step-glyph[aria-hidden=true]` (done ✓, plain ✓, running ◐, waiting ○,
  skipped –, failed !), `span.step-name` (`<b>name</b>` and " · site"), `span.step-found` when it found something,
  `span.visually-hidden` (": state", a plain one ": done"); the running one `aria-current="step"`. Once the request
  is over, its skipped steps fold into one last `li.step.skipped-all`: its glyph "–", then the text "Skipped: PDF,
  Songbooks" (no name span, no hidden state).
- A queued line on a served page: its words, `span.dot`, `button.cancel` "Cancel" (aria-label "Cancel <display>").
- Colours: done and plain `var(--accent)`; running `var(--accent)` at opacity .5, pulsing (`@keyframes step-pulse`,
  1.2 s) only under `prefers-reduced-motion: no-preference`; waiting `var(--border-strong)`; skipped transparent with
  an inset 1 px `var(--control-edge)`; failed `var(--failed)`, 12 px tall, its "!" in `var(--surface)`.

### Meeting points to raise (not done here)

- **Lane 1 (rows.css, library.css)**: after 2.6, `.line > .step-chips` and `.row > .step-chips` in rows.css and
  `.progress .steps-over` in library.css are dead; Task 2.6 deletes them, a named crossing ("Where the lanes meet" 6;
  both files in its Files). steps.css places `.line > .steps` and `.row > .steps` itself. Lane 1b's new line grid keeps
  `.line > .progress` and `.line > .steps` spanning the whole line.
- **Lane 1d (the laptop's pane)**: the open card's step list is `.line > .steps > ol.step-list`, shown by
  `.line:has(> .line-more[aria-expanded="true"])`. In the pane layout the list must show in the pane (moved, or the
  rule widened to the selected line): whichever of Tasks 1d.6 and 2.6 merges second wires it, with a test at 1280 px
  (both tasks carry the step, conditional: "Where the lanes meet" 7).
- **`window.caracoleLibrary`** (lane 1's frozen object) gains one member, `stepList`, in Task 2.6 (a named crossing),
  for requests.js (2.8) to draw the Journal's list with the same function.
- **Lane 4 (songbooks.js)**: `window.caracoleLibrary.showLine(p, view)` keeps its signature; a set list's line stays a
  line of words (no bar, no Cancel), as the third argument is library.js's own.
- library.js's `postTo`, `isActive`, `server`, `failure`, `UNREACHABLE` are read, never edited.

### Where the design left a choice, and what this lane takes (for the owner to overrule)

- **"3 of 7"** is the place of the step in hand (the running one), not how many are over: two done and the sheet
  running is "3 of 7", as the mockup draws it. Once over, the words name the step that failed; a request that ended
  with no failure (Not on the sites, Needs your pick) keeps its frozen bar with no words.
- **The first second is the server's**: the view carries no steps until the job has run a second, so the rule holds
  after a reload too. A job that ended within its first second never gets a bar, frozen or not: a quick failure has
  its outcome line and Details alone.
- **Where the bar sits**: while it runs, in the request line itself (the line's live region, the focus Fetch hands to
  it stays visible); once over, under the outcome line. The tray's lines (lane 1) and the set lists (lane 4) keep
  their words.
- **Plain** ("Match · not on UG") is drawn as done in the bar and ticked in the list.
- **The "!"** can't fit a 6 px segment: a failed segment is 12 px tall with the glyph in it.
- **The open card**: the list is drawn beside the bar on the line and shown while the card is open; the bar stays on
  the line's row above it. On the laptop's pane, whichever of 1d.6 and 2.6 merges second places it (above).
- **The Journal**: a finished lookup keeps its list (every lookup and YouTube sheet that started), its skipped steps
  folded; it lengthens the Journal by up to seven lines a request.
- **"What it found"** is get.py's stage words as the stages say them ("in the book", "tab 1 from Ultimate Guitar",
  "found"); a failure in the outcome's reason words where they parse. Rewording get.py's details is out of scope (it
  would move the lookup vectors).

---

#### Task 2.1: A fixed total, and the step in hand

**Files:**
- Modify: `src/caracole/web/outcome.py` (`_state`, `_youtube_steps`, `progress`; new `_in_hand`; the module
  docstring's Steps and Progress paragraphs)
- Modify: `src/caracole/library_assets/library.js` (`STEP_STATES` gains "skipped"; `showLine` writes `count` only while
  `isActive(view)`), `src/caracole/library_assets/requests.js` (`STATES` gains "skipped")
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/Outcomes.kt` (`stateOf`,
  `progress`, new `inHand`)
- Modify: `docs/usage.md` (the count's examples, "4 of 7 done"; the Journal's "leaving out a step it doesn't use"
  sentence, around lines 4145, 4398, 4471), `AGENTS.md` (the "The library page's lines read only its steps" bullet:
  `outcome.progress`'s rules, `at`, `count`, a skipped step kept in its place)
- Test: `tests/test_web_outcome.py`, `tests/test_conformance_web.py` (`test_a_skipped_pdf_stage_is_no_chip_and_says_
  nothing`), `tests/test_web_page_steps.py`, `tests/test_web_page_youtube.py`, `tests/test_requests_tab.py`,
  `tests/test_web_jobs.py`, `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/JobViewsTest.kt`

**Interfaces:**
- Produces: `steps()` keeps every lookup and YouTube step, a step whose stages all ended skipped as `state="skipped"`
  (the `--no-songbooks` Songbooks step still left out: it is fixed by the command); `progress()`'s `at` and `count` as
  the contract says. Peer, staged and command jobs keep today's rule (each skipped one not drawn).

- [ ] **Step 1: Write the failing tests** in `tests/test_web_outcome.py`; add a helper beside `ended`:

```python
def upto(name, state="running", **said):
    """A lookup's stages: those before ``name`` done, ``name`` in ``state``, then ``said`` over them."""
    names = [n for n, _ in STAGES]
    return {n: ("done", "") for n in names[:names.index(name)]} | {name: (state, "")} | said


def test_a_lookups_steps_are_fixed_when_it_starts_and_a_skipped_one_keeps_its_place():
    skipped = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND),
                             "sheet": ("skipped", NOT_IN_INDEX), "pdf": ("skipped", "no sheet yet"),
                             "lyrics": ("running", "")})
    assert [(c.name, c.state) for c in steps(skipped)] == [
        ("Song", "done"), ("Match · not on UG", "plain"), ("Sheet", "skipped"), ("PDF", "skipped"),
        ("Lyrics", "running"), ("Extras", "waiting"), ("Songbooks", "waiting")]
    leaves = lookup(args=lookup_steps("Muse", "Hysteria", songbooks=False)[0][1])  # fixed by its command
    assert [c.name for c in steps(leaves)] == ["Song", "Match", "Sheet", "PDF", "Lyrics", "Extras"]


def test_the_count_names_the_step_in_hand_and_only_rises():
    said = [{}, upto("song"), upto("match", "waiting"),
            upto("lyrics", sheet=("skipped", NOT_IN_INDEX), pdf=("skipped", "no sheet yet")),
            upto("lacuerda", "waiting"), upto("pages"), upto("songbooks")]
    shown = [progress(job, job_line(job, None), None) for job in (lookup(stages=s) for s in said)]
    assert [s["count"] for s in shown] == ["1 of 7", "1 of 7", "2 of 7", "5 of 7", "6 of 7", "7 of 7", "7 of 7"]
    assert [s["at"] for s in shown] == [0, 0, 1, 4, 5, 6, 6] and {len(s["steps"]) for s in shown} == {7}


def test_once_over_the_count_names_the_step_that_failed_and_nothing_else():
    stopped = ended({"sheet": ("skipped", COOLING), "pdf": ("skipped", "no sheet yet"),
                     "songbooks": ("skipped", "in no songbook")})
    shown = progress(stopped, job_line(stopped, SongFacts()), SongFacts())
    assert [s["state"] for s in shown["steps"]] == ["done", "done", "failed", "skipped", "done", "done", "skipped"]
    assert (shown["at"], shown["count"]) == (2, "3 of 7")
    missing = ended({"match": ("done", MATCH_NOT_FOUND), "sheet": ("skipped", NOT_IN_INDEX),
                     "pdf": ("skipped", "no sheet yet"), "songbooks": ("skipped", "in no songbook")})
    facts = SongFacts(not_found=True, checked_now=True)
    assert set(progress(missing, job_line(missing, facts), facts)) == {"steps"}  # no failure: the bar alone
    refused = ended({"song": ("failed", "overrides.toml can't be read: line 3")}
                    | {name: ("skipped", "") for name, _ in STAGES[1:]}, state="failed")
    shown = progress(refused, job_line(refused, None), None)
    assert [s["state"] for s in shown["steps"]] == ["failed"] + ["skipped"] * 6 and shown["count"] == "1 of 7"
    cut = ended(upto("sheet", INTERRUPTED) | {n: ("skipped", "") for n, _ in STAGES[3:]}, state=INTERRUPTED)
    shown = progress(cut, job_line(cut, None), None)
    assert [s["state"] for s in shown["steps"]] == ["done", "done", "failed"] + ["skipped"] * 4
    assert shown["count"] == "3 of 7"
```

  Import `INTERRUPTED` from `caracole.web.jobs`. Rewrite the tests whose numbers move:
  `test_a_step_the_request_doesnt_use_is_not_drawn` goes (the first test above replaces it; keep its PDF-failed
  assertion there); in `test_the_library_page_draws_a_running_lookups_steps_with_the_count_of_those_over` the counts
  become "5 of 7" (lyrics), "3 of 7" (LaCuerda), "5 of 7" (dropped) and each dict gains `"at"`; in
  `test_the_steps_fold_away_once_…` `missing` has seven steps (Sheet, PDF, Songbooks skipped) and `failed` is the
  refused one above; in `test_a_sheet_a_block_…` each `waited` has seven steps (PDF and Songbooks skipped) with
  `"at": 2, "count": "3 of 7"`, and `running`'s count is "5 of 7"; the YouTube test's is "3 of 5". In
  `tests/test_conformance_web.py`, `test_a_skipped_pdf_stage_is_no_chip_and_says_nothing` becomes
  `test_a_skipped_pdf_stage_is_a_skipped_step_and_says_nothing`: `("PDF", "skipped")` among the steps, the reason
  still "".

- [ ] **Step 2: Run them and see them fail** —
  `nix develop -c pytest -q tests/test_web_outcome.py tests/test_conformance_web.py -k "fixed or in_hand or failed_and or skipped_pdf or count or fold or block"`:
  the skipped steps are missing and `count` is "N of T done".

- [ ] **Step 3: Implement.**
  - `_state(states)`: `None` only for no stage; every stage skipped → `"skipped"`.
  - `_in_hand(chips, *, running) -> int | None` (the contract's rule), and `progress` sets `at`, then `count`, after
    `steps`, only when `_in_hand` gives one. A plain step is over, a skipped one too.
  - library.js: `STEP_STATES` gains "skipped"; `showLine`'s count is written only when `counted && isActive(view)`
    (an ended view may carry a count now). requests.js: `STATES` gains "skipped".
  - Kotlin `Outcomes.stateOf` and `progress` alike (`inHand`, `"at"` then `"count"` in the map's order).
  - Docstrings: outcome.py's Steps paragraph ("A step the request doesn't use is not drawn…") says the steps are fixed
    when it starts, a step whose every stage ended skipped keeping its place; Progress says `at` and `count`.
  - docs/usage.md as listed in Files; AGENTS.md's bullet on the library page's lines says `outcome.progress`'s rules
    (`at`, `count`, a skipped step kept in its place).
  - Chromium and other expectations: test_web_page_steps.py's `said(...)` counts become "3 of 7" and "5 of 7", its
    `NOT_ON_UG` end chips `[["done","✓ Song"],["plain","Match · not on UG"],["failed","✕ Sheet LaCuerda"],
    ["skipped","PDF"],["done","✓ Lyrics"],["failed","✕ Extras"],["skipped","Songbooks"]]`; test_web_page_youtube.py's
    line "Working out the chords…·4 of 5"; test_requests_tab.py's `asking["count"] == "3 of 7"`,
    `lyrics["count"] == "5 of 7"`; test_web_jobs.py's "3 of 7"; JobViewsTest's
    `aLookupOfCommandsSaysItsRunningStageAndCountsItsSteps` "3 of 7" and `view["at"] == 2`.
  - Regenerate the corpus: `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_web.py
    tests/test_conformance_sync_routes.py tests/test_conformance_requests.py tests/test_conformance_library_page.py`.

- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_web_outcome.py tests/test_conformance_*.py
  tests/test_requests_tab.py tests/test_web_jobs.py tests/test_web_page_steps.py tests/test_web_page_youtube.py`, then
  `nix develop ./android -c gradle -p android :server:test --tests 'io.github.danielhp95.caracole.server.jobs.*'`
  and `--tests 'io.github.danielhp95.caracole.server.page.*'`: all pass.

- [ ] **Step 5: Commit** — `git add src/caracole/web/outcome.py src/caracole/library_assets/library.js
  src/caracole/library_assets/requests.js tests/ docs/usage.md AGENTS.md android/server/src`
  `git commit -m "feat(web): a request's steps fixed when it starts, a skipped one keeping its place, and the step in hand counted"`

#### Task 2.2: Nothing for the first second

**Files:**
- Modify: `src/caracole/web/outcome.py` (`BAR_AFTER`, `progress(..., *, now=None)`), `src/caracole/web/jobs_routes.py`
  (`view(..., now=None)`; `views` computes one `now` an answer and passes it)
- Modify: `Outcomes.kt` (`BAR_AFTER: Duration`, `progress(job, line, facts, now: Instant = Instant.now())`),
  `JobViews.kt` (both `view` overloads gain `now: Instant = Instant.now()`), `JobsRoutes.kt` (`/jobs.json` passes
  `clock()` once an answer)
- Modify: `tests/test_conformance_web.py` (`V_ENDED`, `V_NOW`; `in_state`, `phone_job`, the view and outcome records),
  `tests/test_conformance_sync_routes.py` (`view_record` records `now`), and
  `android/server/src/testFixtures/kotlin/io/github/danielhp95/caracole/server/testing/replays/JobViewsReplay.kt`
- Test: `tests/test_web_outcome.py`, `tests/test_requests_tab.py`, `tests/test_web_jobs.py`, `JobViewsTest.kt`

**Interfaces:**
- Consumes: 2.1's `progress`.
- Produces: `outcome.BAR_AFTER`; `progress(job, line, facts, *, now=None)` (None: `datetime.now(UTC)`);
  `jobs_routes.view(job, jobs, song_id, facts, *, songbook_page=None, now=None)`; Kotlin `Outcomes.progress(...,
  now)`, `JobViews.view(..., now)`. Records of job_views.jsonl, job_views_kinds.jsonl and outcome.jsonl carry `now`
  (a stamp) and their `job` its `finished_at`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_web_outcome.py` give `lookup()` times: `START =
  datetime(2026, 11, 3, 9, 0, tzinfo=UTC)` (long past, so a running lookup called with no `now` has run more than a
  second at the clock's), `started_at=START` unless queued or cancelled, `finished_at=START + timedelta(seconds=30)`
  once over; then:

```python
def test_a_request_draws_nothing_for_its_first_second_and_none_if_it_ends_within_it():
    running = lookup(stages=upto("song"))
    assert progress(running, job_line(running, None), None, now=START + timedelta(milliseconds=999)) == {}
    assert progress(running, job_line(running, None), None, now=START + timedelta(seconds=1))["count"] == "1 of 7"
    quick = ended({"sheet": ("skipped", COOLING)})
    quick.finished_at = START + timedelta(milliseconds=600)
    assert progress(quick, job_line(quick, SongFacts()), SongFacts()) == {}  # no bar, frozen or not
    quick.finished_at = START + timedelta(seconds=3)
    assert progress(quick, job_line(quick, SongFacts()), SongFacts())["count"] == "3 of 7"
    never = ended({}, state=INTERRUPTED)
    never.started_at = None  # interrupted while it waited
    assert progress(never, job_line(never, None), None) == {}
```

  In `tests/test_requests_tab.py` add `test_a_views_steps_come_once_its_job_has_run_a_second`: a job of
  `lookup(6, "Muse - Hysteria", {...}, state="running")` with `started_at = NOW`; `jobs_routes.view(job, [job], None,
  None, now=NOW + timedelta(milliseconds=500))` has no `"steps"`, with `now=NOW + timedelta(seconds=2)` it has seven.
  `test_a_lookups_progress_shows_in_the_tab_and_on_its_songs_line`, which reads `/jobs.json` while the command runs,
  takes `monkeypatch.setattr(outcome, "BAR_AFTER", timedelta(0))`; test_web_jobs.py's call passes
  `now=job.started_at + timedelta(seconds=5)`; JobViewsTest's `aLookupOfCommandsSaysItsRunningStageAndCountsItsSteps`
  passes `now = queue.job(job.id)!!.startedAt!!.plusSeconds(5)`. In `tests/test_conformance_web.py` add two jobs to
  `kinds_jobs()`: "a lookup running, its first second" (`started_at = V_NOW`, so at the records' `now` it has run
  0 s: no steps) and "a lookup done within its first second" (`finished_at = V_WHEN`, as it started).

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q tests/test_web_outcome.py -k first_second`
  (TypeError: unexpected keyword `now`) and `tests/test_requests_tab.py -k run_a_second`.

- [ ] **Step 3: Implement.**
  - `progress`: the contract's time rule, `BAR_AFTER` read at call time (so a test may patch it); an over job with no
    `finished_at` is measured to `now`.
  - `jobs_routes.views`: `now = datetime.now(UTC)` once, passed to every `view`; `view` passes it to `progress`.
  - Vectors: `V_ENDED = V_WHEN + timedelta(seconds=30)`, `V_NOW = V_WHEN + timedelta(seconds=12)`; `in_state` sets
    `finished_at = V_ENDED` for a job over; `phone_job` adds `"finished_at": _stamp(job.finished_at)` after
    `started_at`; `view_kind_records` and `outcome_records` call with `now=V_NOW` and write `"now": _stamp(V_NOW)` in
    each record; `view_record` in test_conformance_sync_routes.py passes and records a fixed `now` of its own alike.
  - Kotlin: `JobViewsReplay.jobOf` reads `finished_at` beside `started_at`; `view` and `outcome` pass
    `Instant.parse(r.extra["now"])`; `JobsRoutes`' `/jobs.json` passes `now = clock()`.
  - Regenerate the corpus (2.1's command, twice if a check reads a file another wrote).

- [ ] **Step 4: Run it and see it pass** — the Python files of Step 1, `tests/test_conformance_*.py`, then the gradle
  command of 2.1: all pass. Then `nix develop -c pytest -q tests/test_web_page_steps.py tests/test_web_page_youtube.py`:
  they pass unchanged (they wait for the steps, which come after a second now).

- [ ] **Step 5: Commit** — `git add src/caracole/web tests android/server/src`
  `git commit -m "feat(web): a request's steps only once it has run a second, so a quick one draws none"`

#### Task 2.3: Each step names its site in full and what it found

**Files:**
- Modify: `src/caracole/web/outcome.py` (`Chip`, `SITE_NAMES`, `_match`, `_sheet_source`'s callers,
  `_lookup_steps`, `_youtube_steps`, new `_found`)
- Modify: `library.js` (`drawSteps` reads `c.site`), `requests.js` (`stepChips` reads `c.site`)
- Modify: `Outcomes.kt` (`Chip`, `SITE_NAMES`, `found`), `RequestsReplay.kt` (`chip()` reads `site` and `found`),
  `JobViewsReplay.kt` (`tables` holds `SITE_NAMES`); `tests/test_conformance_web.py` (`tables_record` adds
  `"SITE_NAMES"`)
- Test: `tests/test_web_outcome.py`, `tests/test_requests_tab.py`, `tests/test_web_page_steps.py`,
  `tests/test_web_page_youtube.py`, `JobViewsTest.kt`

**Interfaces:**
- Produces: the contract's `Chip(name, state, site="", found="")` and its JSON; `outcome.SITE_NAMES =
  {tag(key): name for key, name in get.NAMES.items()} | {YOUTUBE_SOURCE: "YouTube", tag(AUTO): "auto-chords",
  tag(INBOX): "your inbox"}` (an unknown tag is itself). `source` is gone everywhere.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_outcome.py`:

```python
def test_each_step_names_its_site_in_full_and_says_what_it_found():
    job = lookup(stages={"song": ("done", "in the book"), "match": ("done", "matched to muse/hysteria"),
                         "sheet": ("done", "tab 1 from Ultimate Guitar"), "pdf": ("running", "")})
    assert steps(job, SongFacts(sheet="Muse/Hysteria/sheet.html", sheet_from="UG"))[:4] == [
        Chip("Song", "done", "", "in the book"), Chip("Match", "done", "Ultimate Guitar", "matched to muse/hysteria"),
        Chip("Sheet", "done", "Ultimate Guitar", "tab 1 from Ultimate Guitar"), Chip("PDF", "running")]
    extras = ended({"ug": ("done", "sheet 1"), "lacuerda": ("skipped", "not for LaCuerda"),
                    "gtptabs": ("done", GTPTABS_KEPT)})
    assert steps(extras)[5] == Chip("Extras", "done", "", "sheet 1 · " + GTPTABS_KEPT)
    failed = lookup(stages={"song": ("done", ""), "match": ("done", "")})
    failed.heard({"stage": "sheet", "state": "running", "detail": SHEET_FROM["ug"]})
    failed.heard({"stage": "sheet", "state": "failed", "detail": "Ultimate Guitar failed (ug: 502); tried again tonight"})
    assert steps(failed)[2] == Chip("Sheet", "failed", "Ultimate Guitar",
                                    "Ultimate Guitar answered 502. The sheet waits until tonight.")
    plain = lookup(stages={"song": ("done", ""), "match": ("done", MATCH_NOT_FOUND)})
    assert steps(plain)[1] == Chip("Match · not on UG", "plain")  # its name says it: nothing found to add
    assert SITE_NAMES["UG"] == "Ultimate Guitar" and SITE_NAMES["LaCuerda"] == "LaCuerda"
```

  Import `GTPTABS_KEPT` from `caracole.get`, `SITE_NAMES` from `caracole.web.outcome`. Every other `Chip(..., "UG")`
  and `Chip(..., "LaCuerda")` in this file names its site in full ("Ultimate Guitar"), each JSON step dict is
  `{"name", "site", "state", "found"}`, and the YouTube test's Audio step is `Chip("Audio", "done", "YouTube", <its
  detail>)`. In `tests/test_requests_tab.py` the dicts become `{"name": "Song", "site": "", "state": "done", "found":
  "in the book"}`, `{"name": "Match", "site": "Ultimate Guitar", "state": "done", "found":
  "matched to radiohead/creep"}`, `{"name": "Sheet", "site": "Ultimate Guitar", "state": "running", "found": ""}`; the
  mockup's tuples read `c["site"]` ("Ultimate Guitar" for Match and Sheet).

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q tests/test_web_outcome.py
  tests/test_requests_tab.py -k "site or steps or progress"`: `Chip` has no `found`, `SITE_NAMES` doesn't exist.

- [ ] **Step 3: Implement.**
  - `Chip` as the contract says (its docstring says each field). `_match` names `SITE_NAMES[MATCHED_IN]`; the Sheet
    step `SITE_NAMES.get(tag, tag)` of what `_sheet_source` gives ("" stays ""); Audio `SITE_NAMES[YOUTUBE_SOURCE]`.
  - `_found(read: list[tuple[Stage, str]]) -> str`, each stage with its state as the step reads it (`_sheet_waited`,
    and `_youtube_steps`' audio rule); `_lookup_steps` and `_youtube_steps` build `read` once and give it to `_state`
    and `_found`; a plain step's `found` is "". Peer, staged and command chips have no site and no `found`.
  - library.js `drawSteps` and requests.js `stepChips`: `c.site` in place of `c.source`.
  - Kotlin: `Chip(name, state, site = "", found = "")`, `asJson` in the same order; `SITE_NAMES` as Python's (the
    `tables` record holds it whole); `found` as `_found`, with `stageReason`.
  - Expectations: test_web_page_steps.py's chips "✓ Match Ultimate Guitar", "Sheet Ultimate Guitar" (LaCuerda's stay);
    test_requests_tab.py's `DRAWN` chips "✓ Match Ultimate Guitar: done", "✓ Sheet Ultimate Guitar: done";
    JobViewsTest's Sheet JSON `{"name":"Sheet","site":"LaCuerda","state":"running","found":""}`.
  - Regenerate the corpus.

- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_web_outcome.py tests/test_requests_tab.py
  tests/test_conformance_*.py tests/test_web_page_steps.py tests/test_web_page_youtube.py`, then the gradle command of
  2.1.

- [ ] **Step 5: Commit** — `git add src/caracole/web/outcome.py src/caracole/library_assets tests android/server/src`
  `git commit -m "feat(web): each step names its site in full and says what it found"`

#### Task 2.4: The Journal keeps a finished lookup's steps

**Files:**
- Modify: `src/caracole/web/outcome.py` (new `lists_steps`), `src/caracole/web/feed.py` (`feed`, `_finished`; module
  docstring)
- Modify: `Feed.kt` (`feed`, `finished`), `RequestsRoutes.kt` (the `steps` map), `Outcomes.kt` (`listsSteps`)
- Modify: `tests/test_conformance_requests.py` (`feed_record`'s `chips`), `docs/usage.md` (the Journal's finished
  requests, around line 4486), `AGENTS.md` (the bullet on the library page's lines, or the Requests tab's: feed.py's
  finished steps, `lists_steps`)
- Test: `tests/test_requests_tab.py`, `android/server/src/test/kotlin/io/github/danielhp95/caracole/server/jobs/FeedTest.kt`

**Interfaces:**
- Consumes: 2.1–2.3's steps.
- Produces: `outcome.lists_steps(job) -> bool` (`not job.active and job.started_at is not None and (job.looks_up or
  job.from_youtube)`); a finished request's `"steps"` in `/requests.json`, right after `"reason"`. Kotlin
  `Outcomes.listsSteps(job)`; `Feed.feed`'s `steps` map holds them (else `Outcomes.steps(job)` for a listed job).

- [ ] **Step 1: Write the failing test** in `tests/test_requests_tab.py`:

```python
def test_a_finished_lookup_keeps_its_steps_and_nothing_else_does():
    shown = by_id(mockup_feed())
    assert [(c["name"], c["state"]) for c in shown[5]["steps"]] == [
        ("Song", "done"), ("Match", "done"), ("Sheet", "skipped"), ("PDF", "skipped"), ("Lyrics", "done"),
        ("Extras", "done"), ("Songbooks", "done")]
    assert list(shown[5])[:6] == ["id", "display", "state", "says", "reason", "steps"]
    assert "steps" not in shown[2]  # a songbook deleted: no lookup
    assert "steps" not in shown[7]  # queued: its place and Cancel
```

  And one for a cancelled lookup (`state="cancelled"`, `started_at=None`): no `"steps"`.

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_requests_tab.py -k keeps_its_steps`:
  KeyError `steps`.

- [ ] **Step 3: Implement** — `feed` gives `_finished` the chips of a job `lists_steps` takes
  (`steps(job, facts.get(job.id))`), which it writes after the reason. `feed_record` puts those jobs' chips in its
  `steps` too. Kotlin: `RequestsRoutes` computes steps for running and listed jobs; `Feed.finished(..., chips)` writes
  them in the same place. docs/usage.md: a finished lookup in the Journal lists its steps (their look comes in 2.8);
  AGENTS.md: feed.py's finished steps (`lists_steps`). Regenerate the corpus.

- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_requests_tab.py
  tests/test_conformance_requests.py`, then the gradle command of 2.1.

- [ ] **Step 5: Commit** — `git add src/caracole/web tests docs/usage.md AGENTS.md android/server/src`
  `git commit -m "feat(web): the Journal keeps a finished lookup's steps"`

#### Task 2.5: The segmented bar on a running line

**Files:**
- Modify: `src/caracole/library_assets/library.js` (`showLine`, `showRequest`, `drawSteps`; new `chipsOf`, `segsOf`,
  `stepWords` beside them), `src/caracole/library_assets/steps.css` (the bar's rules; its header)
- Modify: `docs/usage.md` (a running line, around lines 4145, 4251, 4398), `AGENTS.md` (the "The library page's
  lines read only its steps" bullet)
- Test: `tests/test_web_page_steps.py` (rewritten for the bar; its module docstring), `tests/test_web_page_youtube.py`

**Interfaces:**
- Consumes: the view's `steps`, `at`, `count` (2.1–2.3).
- Produces: `p.progress.barred` and its children as the contract says; `showLine(p, view, onLine)` (the third
  argument renamed from `counted`: a song's line or a result's row, which `showRequest` passes); `chipsOf(view)`,
  `segsOf(chips)`, `stepWords(chips, view)`. While `p` is barred, `drawSteps` draws no chips.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_page_steps.py`, with helpers:

```python
def bar_of(item: str) -> str:
    """The expression for the segments of ``item``'s bar (its running one, else its frozen one): each one's state."""
    segs = f"{item} .progress.barred .step-segs > i, {item} .steps > .step-bar .step-segs > i"
    return f"[...document.querySelectorAll({json.dumps(segs)})].map((s) => s.className.replace('seg ', ''))"


def words_of(item: str) -> str:
    """The expression for the words beside ``item``'s bar: [the step and its site, the count]."""
    return (f"(() => {{ const b = document.querySelector({json.dumps(item + ' .progress.barred, ' + item + ' .step-bar')});"
            " const t = (s) => (b && b.querySelector(s) || {}).textContent || ''; return [t('.step-at'), t('.step-count')]; })()")
```

```python
@pytest.mark.parametrize("width", [1280, 390, 320])
def test_a_running_lookup_is_a_segmented_bar_on_its_line_in_one_row(cfg, live, tmp_path, width):
    ...  # Creep, FROM_UG, as the test it replaces sets it up
        page.click(f"{line} form.fetch button")
        wait_for(page, bar_of(line), ["done", "done", "running", "waiting", "waiting", "waiting", "waiting"])
        wait_for(page, words_of(line), ["Sheet · Ultimate Guitar", " · 3 of 7"])
        p = f"document.querySelector('{line} .progress')"
        assert page.js(f"{p}.textContent") == "Sheet · Ultimate Guitar · 3 of 7"  # what a screen reader hears
        assert page.js(f"{p}.getAttribute('role')") == "status"
        assert page.js(f"document.querySelector('{line} .step-chips, {line} .steps')") is None
        one_row(page, line)  # segments and count on one top, the count inside the line, no sideways scroll
        assert page.js(f"getComputedStyle(document.querySelector('{line} .seg.running')).animationName") == "step-pulse"
        assert page.js(f"getComputedStyle(document.querySelector('{line} .seg.done')).backgroundColor") == page.js(ACCENT)
        assert page.js(f"getComputedStyle(document.querySelector('{line} .seg')).borderTopLeftRadius") == "0px"  # square
        runner.go()
        wait_for(page, bar_of(line), ["done"] * 4 + ["running", "waiting", "waiting"])
        wait_for(page, words_of(line), ["Lyrics", " · 5 of 7"])
        runner.go()
        # Ready: the bar folds away, as the chips did; the line is the song's.
        assert page.wait(f"{p}.dataset.tone === 'ready'", timeout=15)
        assert page.js(f"{p}.classList.contains('barred')") is False and page.js(f"{p}.getBoundingClientRect().height") <= 1
```

  `ACCENT` is a probe: an `<i>` with `background: var(--accent)` appended to the body, its computed backgroundColor.
  `one_row(page, item)` asserts `.step-segs`' and `.step-count`'s rects share a vertical centre within 2 px, the
  count's right ≤ the line's right + 0.5, and `document.documentElement.scrollWidth <= innerWidth`.

```python
def test_the_bar_comes_after_a_second_and_a_quick_request_draws_none(cfg, live, tmp_path):
    # Quick (the script with no hold): it ends Not on the sites within its first second, and no bar was ever drawn.
    # Held: the bar shows a second or more after Fetch.
```

  The quick half sets `runner.script = [s for s in NOT_ON_UG if s is not HOLD]` and
  `monkeypatch.setattr(outcome, "BAR_AFTER", timedelta(seconds=30))` (the server is in-process: the script surely ends
  within it, on a busy machine too), installs before the click
  `new MutationObserver(() => { if (document.querySelector('#list .step-segs, #list .steps')) window.barSeen = true; })
  .observe(document.getElementById('list'), {subtree: true, childList: true})`, waits for the line's words
  "Not on the sites·To-do page" and asserts `window.barSeen` is not true. The held half (FROM_UG, another song) notes
  `performance.now()` at the click and the first time an observer sees `.step-segs`, and asserts the gap ≥ 950 ms.

```python
def test_the_running_segment_is_steady_under_reduced_motion(cfg, live, tmp_path):
    # page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
    # before page.open; FROM_UG; once the running segment shows: animationName "none", opacity "0.5".
```

  The search result's test (`test_a_search_results_get_it_shows_…`) checks the bar in the row (`bar_of(RYAN)`, its
  words, `one_row`) in place of the chips. test_web_page_youtube.py waits for `bar_of(line(song))` == `["done",
  "done", "done", "running", "waiting"]` and the words `["Chords", " · 4 of 5"]`.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q tests/test_web_page_steps.py -k "bar or
  steady"`: no `.progress.barred`.

- [ ] **Step 3: Implement.**
  - `chipsOf(view)`: the view's steps that are objects with a name. `segsOf(chips)`: `span.step-segs`
    (`aria-hidden="true"`), an `i.seg.<state>` a step (an unknown state "waiting"), the failed one's text "!".
    `stepWords(chips, view)`: `[span.step-at, span.step-count]` when `view.at` is an integer naming a step and
    `view.count` is a string, else `[]`.
  - `showLine(p, view, onLine)`: barred is `onLine && line.tone === "running" && isActive(view)` and steps; the key
    adds the chips' names, sites and states, `at` and `count` while barred; `p.classList.toggle("barred", barred)`;
    barred, `p` holds `segsOf` and `stepWords`, nothing else; else today's words and links (no count any more).
  - `drawSteps(p, view)`: no steps, or `p` barred → it removes what it drew after `p`; else today's chips (2.6
    replaces them).
  - steps.css: `.progress.barred` (flex, centred, gap 8 px, `white-space: nowrap`, `overflow: hidden`, muted, weight
    500; `::before { content: none }`, the line's dot), `.step-segs` (flex: none, width 112 px, gap 3 px), `.seg` and
    its states (the contract's colours; 6 px tall, a failed one 12 px; square ends, `border-radius: 0`, which the four
    radii allow: "Where the lanes meet" 4; any other radius this lane writes is a token with its fallback,
    `var(--radius-m, 8px)` and the like), `.step-at` (min-width 0, ellipsis; its `b` in
    `var(--text)`, weight 600), `.step-count` (flex: none), `@keyframes step-pulse { 50% { opacity: .2 } }` under
    `@media (prefers-reduced-motion: no-preference)`.
  - docs/usage.md: the running line is a bar of its steps and "Sheet · Ultimate Guitar · 3 of 7", from its first
    second; AGENTS.md's bullet says the same (`outcome.progress`, `BAR_AFTER`). Regenerate library_page.json
    (`tests/test_conformance_library_page.py`).

- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_web_page_steps.py
  tests/test_web_page_youtube.py tests/test_web_page.py tests/test_conformance_library_page.py`, then `nix develop
  ./android -c gradle -p android :server:test --tests 'io.github.danielhp95.caracole.server.page.*'`.

- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/library.js src/caracole/library_assets/steps.css tests
  docs/usage.md AGENTS.md`
  `git commit -m "feat(library): a running request is a segmented bar on its song's line"`

#### Task 2.6: The frozen bar under a line that ended, and the open card's list

**Files:**
- Modify: `library.js` (`drawSteps`, `stepsAfter`; new `stepList`; `STEP_MARKS` goes; and one member more on
  `window.caracoleLibrary`, `stepList`, a named crossing: the frozen object is lane 1's), `steps.css` (`.steps`,
  `.step-bar`, `.step-list`, `.step`; `.line > .steps` and `.row > .steps` placed as rows.css places today's chips)
- Modify: `src/caracole/library_assets/rows.css` (delete `.line > .step-chips` and `.row > .step-chips`) and
  `src/caracole/library_assets/library.css` (delete `.progress .steps-over`): dead once the chips go, a named crossing
  ("Where the lanes meet" 6)
- Modify, only if lane 1's Task 1d.6 has merged ("Where the lanes meet" 7): library.js or steps.css (the selected
  line's `ol.step-list` shown in `#card-pane`), as a named crossing
- Modify: `docs/usage.md` (a line that ended otherwise than Ready; the open card's list)
- Test: `tests/test_web_page_steps.py`, `tests/test_web_page.py` (the tray's assertion: `'class="steps"'` and
  `step-segs` not in it)

**Interfaces:**
- Consumes: 2.5's `chipsOf`, `segsOf`, `stepWords`, `p.barred`.
- Produces: `div.steps` > `div.step-bar[role=img]` and `ol.step-list` as the contract says; `stepList(chips, over)`,
  also `window.caracoleLibrary.stepList` (requests.js's, 2.8); `stepsAfter(p)` finds `div.steps` (so `refill` and
  `countdownIn` keep working unchanged); `drawSteps(p, null)` also takes `barred` off `p`.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_page_steps.py`:

```python
def steps_of(item: str) -> str:
    """The expression for ``item``'s list of steps: each one's state, glyph, step and site, and what it found."""
    return (f"[...document.querySelectorAll({json.dumps(item + ' .steps > .step-list > li')})].map((li) => ["
            "li.className.replace('step ', ''), li.querySelector('.step-glyph').textContent, "
            "li.querySelector('.step-name') ? li.querySelector('.step-name').textContent : li.lastChild.textContent, "
            "(li.querySelector('.step-found') || {}).textContent || ''])")


def test_a_lookup_that_ends_otherwise_keeps_its_bar_frozen_under_its_line(cfg, live, tmp_path):
    ...  # Estopa - Tu Calorro, NOT_ON_UG, at 1280 and 390
        wait_for(page, bar_of(line), ["done", "plain", "running"] + ["waiting"] * 4)
        wait_for(page, words_of(line), ["Sheet · LaCuerda", " · 3 of 7"])
        runner.go()
        wait_for(page, f"document.querySelector('{line} .progress').textContent", "Not on the sites·To-do page")
        wait_for(page, bar_of(line), ["done", "plain", "failed", "skipped", "done", "failed", "skipped"])
        assert page.js(words_of(line)) == ["Sheet · LaCuerda", " · 3 of 7"]
        assert page.js(f"document.querySelector('{line} .step-bar').getAttribute('aria-label')") == (
            "Steps: Song: done; Match · not on UG: done; Sheet, LaCuerda: failed; PDF: skipped; Lyrics: done; "
            "Extras: failed; Songbooks: skipped")
        assert page.js(f"document.querySelector('{line} .seg.failed').textContent") == "!"
        assert page.js(f"getComputedStyle(document.querySelector('{line} .step-list')).display") == "none"
        page.click(f"{line} .line-more")  # the card open: the list in the bar's place
        assert page.js(f"getComputedStyle(document.querySelector('{line} .step-bar')).display") == "none"
        assert page.js(steps_of(line)) == [
            ["done", "✓", "Song", "in the book"], ["plain", "✓", "Match · not on UG", ""],
            ["failed", "!", "Sheet · LaCuerda", LACUERDA_FAILS], ["done", "✓", "Lyrics", "found"],
            ["failed", "!", "Extras", "asked already, for the sheet: " + LACUERDA_FAILS],
            ["skipped-all", "–", "Skipped: PDF, Songbooks", ""]]


def test_the_open_cards_list_follows_a_running_lookup_and_folds_away_once_ready(cfg, live, tmp_path):
    # FROM_UG with Creep's card open: the list shows the running step (aria-current="step", ◐ "Sheet · Ultimate
    # Guitar"), those before it ticked with what they found ("in the book", "matched to it"), those after ○; the bar
    # stays on the line's row. Ready: no .steps, as on a closed line.
```

  2.5's running-line assertion, `document.querySelector('{line} .step-chips, {line} .steps')` is None, is rewritten to
  this task's contract: no `{line} .step-chips`, and `{line} .step-list` not displayed
  (`getComputedStyle(...).display === "none"`) while the card is closed.

  Only if Task 1d.6 has merged: `test_on_a_laptop_the_selected_lines_steps_are_listed_in_the_pane` (1280 × 900;
  Estopa - Tu Calorro, `NOT_ON_UG`, as the frozen bar's test sets it up): once it ended, click the line's title (its
  card in the pane): an `ol.step-list` inside `#card-pane` is visible with `steps_of`'s six entries, while the line in
  `#list` shows its frozen `.step-bar` and no list. Else Task 1d.6 writes it, when it merges second.

- [ ] **Step 2: Run them and see them fail** — `nix develop -c pytest -q tests/test_web_page_steps.py -k "frozen or
  open_cards"`: no `.step-bar`, no `.step-list`.

- [ ] **Step 3: Implement.**
  - `drawSteps(p, view)`: the contract's `div.steps` (keyed as today on what it draws, and on `p` barred and the view
    over), a frozen `.step-bar` only while `p` isn't barred (its aria-label "Steps: " and each step's "name[, site]:
    state", joined by "; ", a plain one "done"), then `stepList(chips, !isActive(view))`.
  - `stepList(chips, over)`: the contract's list; over, the skipped steps leave their places for one last
    `li.step.skipped-all` (its glyph "–", "Skipped: " and their names joined by ", "). It is handed to requests.js as
    `window.caracoleLibrary.stepList` (one more member of the frozen object), the one function that draws a list of
    steps.
  - The dead chips' rules go: rows.css's `.line > .step-chips` and `.row > .step-chips`, library.css's `.progress
    .steps-over`.
  - Only if Task 1d.6 has merged: the selected line's `.steps > ol.step-list` shows in the pane (moved into
    `#card-pane` with the card and back with it, or the rule widened), and the
    `.line:has(> .line-more[aria-expanded="true"])` rule leaves a `.selected` line its frozen bar.
  - steps.css: `.line > .steps` (`grid-column: 1 / -1; margin: 3px 0 4px`), `.row > .steps` (`grid-column: 2 / -1;
    margin: 3px 0 2px`); `.step-bar` as `.progress.barred`'s row; `.steps > .step-list { display: none }`, and under
    `.line:has(> .line-more[aria-expanded="true"])` the list `display: grid` and the bar `display: none`; `.step-list`
    (grid, gap 2 px, no bullets, .85rem), `.step` (flex, baseline, gap 8 px, min-width 0), `.step-glyph` (1.1em,
    centred; accent for done, plain and running, `var(--failed)` for failed), waiting, skipped and skipped-all muted,
    the running one weight 600, `.step-found` muted, `overflow-wrap: anywhere`.
  - The other tests of the file: the chips' assertions become `bar_of` and `steps_of`; Ready asserts no `.steps`; 2.5's
    running-line assertion as Step 1 says.
  - docs/usage.md says the frozen bar and the card's list. Regenerate library_page.json.

- [ ] **Step 4: Run it and see it pass** — 2.5's Step 4 commands.

- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/library.js src/caracole/library_assets/steps.css
  src/caracole/library_assets/rows.css src/caracole/library_assets/library.css tests docs/usage.md`
  `git commit -m "feat(library): a request that ended keeps its bar frozen under its line, and its card lists the steps"`

#### Task 2.7: Cancel beside a queued line

**Files:**
- Modify: `library.js` (`showLine`; new `cancelButton(p, view)` beside it), `steps.css` (`.progress .cancel`)
- Modify: `docs/usage.md` (Cancel on the song's line, beside the Journal's, around line 4478)
- Test: `tests/test_web_page_steps.py`

**Interfaces:**
- Consumes: `postTo`, `server.csrf`, `failure`, `UNREACHABLE` (library.js's, read only); `POST /jobs/cancel` (caracole
  serve's and the phone's JobsRoutes, both answering `{"cancelled": id}` to the script).
- Produces: `button.cancel` on a line whose view is queued, on a served page.

- [ ] **Step 1: Write the failing test:**

```python
def test_a_queued_request_says_its_place_with_cancel_beside_it(cfg, live, tmp_path):
    # Creep looked up (FROM_UG, held at its sheet); Wonderwall's Fetch queues behind it.
        wait_for(page, f"document.querySelector('{wonderwall} .progress').textContent",
                 "Queued · 1 request ahead…·Cancel")
        assert page.js(f"document.querySelector('{wonderwall} .progress button.cancel')"
                       ".getAttribute('aria-label')") == "Cancel Oasis - Wonderwall"
        page.click(f"{wonderwall} .progress button.cancel")
        wait_for(page, f"document.querySelector('{wonderwall} .progress').textContent", "Cancelled")
        assert page.wait(f"!!document.querySelector('{wonderwall} form.fetch button')")  # its Fetch is back
        assert page.js(bar_of(creep))[2] == "running"  # the one that runs is never stopped
```

  At 390 px too (parametrized), where the button is at least 44 px tall under `(pointer: coarse)`.

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_web_page_steps.py -k cancel`: the
  line says "Queued · 1 request ahead…" alone.

- [ ] **Step 3: Implement** — `showLine` with `onLine`, a served page and a view queued with an id: after the words, a
  dot and `cancelButton(p, view)` (the key gains the id). Its click disables it and posts `csrf` and `job`: answered,
  the line says `{tone: "cancelled", text: "Cancelled"}` (what the next view says too); refused, `failure(answer)`;
  no answer, `UNREACHABLE`; the next view of the job draws the line again. The focus stays on the line (`showLine`
  keeps it). steps.css: `.progress .cancel` as library.css's `.progress .undo` (a text button, 32 px; its radius
  `var(--radius-m, 8px)`, "Where the lanes meet" 4), 44 × 44 px under `(pointer: coarse)`. docs/usage.md. Regenerate
  library_page.json.

- [ ] **Step 4: Run it and see it pass** — 2.5's Step 4 commands.

- [ ] **Step 5: Commit** — `git add src/caracole/library_assets/library.js src/caracole/library_assets/steps.css tests
  docs/usage.md`
  `git commit -m "feat(library): a queued request's line has Cancel beside its place"`

#### Task 2.8: The Journal's list of steps

**Files:**
- Modify: `src/caracole/library_assets/requests.js` (`stepChips` goes: the list is library.js's `stepList`, through
  `window.caracoleLibrary.stepList`, no copy of it here; line 293's `history.replaceState(null, "", "#" +
  params.toString())` passes `history.state`, "Where the lanes meet" 9; its header),
  `src/caracole/library_assets/requests.css` (`.req .step-list` in place of the `.req .step-chips` rules; every
  `border-radius` one of the four as a token with its fallback, by 1f.1's mapping: `.req`'s 14 px `var(--radius-l,
  12px)`, `.req-step`'s 10 px and `.req-output pre`'s 8 px `var(--radius-m, 8px)`, `.req-says`' 999 px
  `var(--radius-pill, 999px)`), `src/caracole/library_assets/steps.css` (the `.step-chips` and `.step-chip` rules go:
  nothing draws them now)
- Modify: `docs/usage.md` (the Journal's Now and finished requests, around lines 4465–4486)
- Test: `tests/test_requests_tab.py` (`DRAWN`)

**Interfaces:**
- Consumes: 2.4's finished `steps`; 2.6's list markup, `window.caracoleLibrary.stepList` and steps.css's
  `.step-list` rules.
- Produces: `li.req > ol.step-list` for every request with steps, over ones with their skipped steps folded.

- [ ] **Step 1: Write the failing test** — in `DRAWN`, `chips:` becomes

```js
list: Array.from(document.querySelectorAll("#req-6 .step-list > li")).map((li) => [li.className,
  li.querySelector(".step-glyph").textContent, (li.querySelector(".step-name") || li.lastChild).textContent]),
over: Array.from(document.querySelectorAll("#req-5 .step-list > li")).map((li) => [li.className,
  (li.querySelector(".step-name") || li.lastChild).textContent]),
```

  and the test asserts

```python
assert shown["list"] == [["step done", "✓", "Song"], ["step done", "✓", "Match · Ultimate Guitar"],
                         ["step done", "✓", "Sheet · Ultimate Guitar"], ["step running", "◐", "PDF"],
                         ["step waiting", "○", "Lyrics"], ["step waiting", "○", "Extras"],
                         ["step waiting", "○", "Songbooks"]]
assert shown["over"] == [["step done", "Song"], ["step done", "Match · Ultimate Guitar"], ["step done", "Lyrics"],
                         ["step done", "Extras"], ["step done", "Songbooks"],
                         ["step skipped-all", "Skipped: Sheet, PDF"]]
```

  (the phone and laptop widths, light and dark, as the test runs; no small targets, no sideways scroll). `DRAWN` also
  notes `radii`, the computed `borderTopLeftRadius` of every rendered element in `#requests`
  (`checkVisibility()`), and the test asserts `set(shown["radii"]) <= {"0px", "4px", "8px", "12px", "999px"}`; and
  requests.js's text has no `stepChips` and defines no `stepList` of its own
  (`re.search(r"\b(function|const|let)\s+stepList\b", text)` is None): one function draws a list of steps.

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_requests_tab.py -k draws_every`: no
  `.step-list`.

- [ ] **Step 3: Implement** — `makeItem` draws `window.caracoleLibrary.stepList(chips, over)` where the chips were
  (over: the item's state neither running nor queued), the contract's markup; where `window.caracoleLibrary` has no
  `stepList`, the steps' names as plain words. requests.css: `.req .step-list { grid-column: 1 / -1; margin: 2px 0 0 }`
  (the list is no `.steps` child, so steps.css's closed-line rule doesn't hide it), and its radii as the tokens above.
  requests.js's line 293 passes `history.state`. docs/usage.md: the Journal lists a request's steps, one line a step,
  skipped ones folded once it ends. Regenerate library_page.json.

- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_requests_tab.py
  tests/test_conformance_library_page.py tests/test_web_page_steps.py`, then the page's gradle command of 2.5.

- [ ] **Step 5: Commit** — `git add src/caracole/library_assets tests docs/usage.md`
  `git commit -m "feat(library): the Journal lists a request's steps, skipped ones folded once it ends"`

#### Task 2.9: Merge the lane

**Files:**
- Check (written by 2.1 to 2.8): `AGENTS.md`, `docs/usage.md` (a last read against what the lane did); the corpus
- Modify, only if this merge is the last of 1f, lane 2, 3b and lane 4: `tests/test_page_calm.py` (`OTHER_LANES`
  emptied); only if lane 2 is the last of the four lanes to merge: `docs/screenshots/*.png` (those that changed)

- [ ] **Step 1: Bring main in** — `git fetch . main && git rebase main` (lane 1 may have merged a stage: library.js,
  rows.css and test_web_page*.py are the likely conflicts; keep lane 1's code, re-apply this lane's block). Raise the
  meeting points above with lane 1 and lane 4 if they aren't settled.
- [ ] **Step 2: Corpus** — `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`, twice if
  a check reads a file another writes; `git status` shows only the vectors this lane's changes explain.
- [ ] **Step 3: The whole suite and the checks** — `nix develop -c pytest -q`;
  `nix develop ./android -c gradle -p android test`;
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus moved);
  `nix flake check`. All pass; a Kotlin test that breaks is this lane's to follow here (Outcomes.kt, JobViews.kt,
  Feed.kt, RequestsRoutes.kt, JobViewsTest, FeedTest, JobViewsReplay, RequestsReplay).
- [ ] **Step 4: Docs, checked** — docs/usage.md says (each task wrote its part): the running bar and its words from
  the first second, Cancel beside a queued line, the frozen bar under a line that ended otherwise than Ready, the open
  card's and the Journal's lists, skipped steps kept in place and folded once over; AGENTS.md's bullet on the library
  page's lines says `outcome.progress`'s rules (`BAR_AFTER`, `at`, `count`, skipped kept) and feed.py's finished
  steps (`lists_steps`). A gap goes into a `docs:` commit here.
- [ ] **Step 5: The radius skip list** — only if 1f, 3b and lane 4 have all merged, this merge is the last of 1f, lane
  2, 3b and lane 4: `tests/test_page_calm.py`'s `OTHER_LANES = ()` and `test_the_library_page_has_four_corner_radii`
  passes with it (commit `test(library): the four radii across the whole page, no lane left out`); else the list
  stays, for the last of them to remove.
- [ ] **Step 6: The README's screenshots** — only if lanes 1 (1f), 3 (3b) and 4 have all merged (lane 2 the last of
  the four): retake them: `nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python
  docs/screenshots/make.py`; for each picture, `git show HEAD:docs/screenshots/<name>.png > old.png` (outside the
  repository) and `compare -metric AE old.png docs/screenshots/<name>.png null:` (ImageMagick, through
  `omnibin-shell` if it isn't on PATH): `git restore` those with 0 differing pixels, keep the others; commit `docs: the
  README's screenshots of the redesigned page`. Else they wait for the last lane.
- [ ] **Step 7: Merge** — `git checkout main && git merge --no-ff feat/progress-bar` (a merge commit, as the lanes
  before, even where the rebase would let it fast-forward), then push main: `GH_TOKEN="$(gh auth token --user
  Danielhp95)" git push origin main`, then `git worktree remove ../caracole-progress`.

---

## Lanes 3 and 4: the card and the play buttons; Songbooks

The design is `docs/superpowers/specs/2026-11-17-library-page-redesign-design.md` ("Play buttons", "The card",
"A calmer page", "Songbooks", "The lanes"); the mockup `2026-11-17-library-page-redesign/play-buttons.html`, C for the
laptop, Today (letters grown) for the phone.

### Facts the tasks rest on (checked in the code and in the test Chromium, 2026-11-17)

- **The test Chromium has no pointer.** Headless Chromium as `helpers.browser` runs it matches `(pointer: none)` and
  `(hover: none)`; `touch=True` (or `Browser(mobile=True)`) makes it `(pointer: coarse)`. `Emulation.setEmulatedMedia`
  can't emulate `pointer`. The switch `--blink-settings=primaryPointerType=4,availablePointerTypes=4,primaryHoverType=2,availableHoverTypes=2`
  makes it `(pointer: fine)` and `(hover: hover)` (checked with `chromium --headless=new --dump-dom`). So the chips are
  the **base** rules and the tiles live under `@media (pointer: coarse)`, today's convention in rows.css and card.css:
  `pointer: fine` gets chips, `pointer: coarse` tiles, as the design says, and `pointer: none` (rare) gets chips. One
  test proves the `pointer: fine` case through `Browser(args=FINE_POINTER)`.
- **The lookup page** (web/lookup_page.py) inlines rows.css but not card.css, and draws no play buttons (no card.js):
  moving the `.play` rules out of rows.css changes nothing there.
- **The data names a version by what differs.** Each UG chords version of a song's `versions.list` (library_page.py
  `_versions_data`, which copies `sheet_versions.as_data`'s entries) has `label`: UG's part ("intro", "solo", ...), else
  "acoustic" for an acoustic recording, else null (ug/page.py `UGVersion.label`). LaCuerda's versions
  (`lacuerdaVersions`), Guitar Pro files and harmonica tabs have none. So only UG's rows can be named that way.
- **An unrated UG version** is stored with `rating=0, votes=0` (ug/page.py: "A null rating or vote count is 0";
  ug/fetch.py's pasted tab).
- **The songbook viewer** (viewer/book.js) opens the song the address names, `#song-N`, where N is the song's place in
  the songbook counting every song (book.py `_contents`, `_song`: `data-n`, from 1), and a song without a sheet has no
  section: `#song-1` on a songbook whose first song has no sheet shows the contents. The Songbooks tab's data
  (songbook_section.py `_book`) gives each set entry its `n` and its `href` (None without a sheet: the same `e.cho` that
  decides whether book.py writes its section), and each book its made `files` (`{name, label, href}`, `songbook.html`
  labelled "Phone page"); the phone's `SongbookSection.kt` gives the same shape (`PHONE_FILES`).
- library_assets/ changes regenerate `tests/conformance/vectors/web/library_page.json` (the page's script and style
  hashes and pages). No Kotlin source changes: the phone copies library_assets/ byte for byte. The Kotlin tests that
  read the regenerated vector are `server/.../page/LibraryPageTest.kt` ("every case the phone serves has Python's
  SHA-256", "the phone's page is the sheet case byte for byte"), `LibraryAssetsTest.kt` and `AssemblyTest.kt` (the
  copied assets); `app/src/androidTest/.../SongbooksOnDeviceTest.kt` clicks `#songbooks .book-files
  a[href$="songbook.html"]`, which lane 4 leaves alone.

### The interface lane 1 consumes (card.js)

Unchanged entry point and signatures; what changes is said under each task.

```js
const card = caracoleCard(icons, rows);  // icons: data.icons; rows: caracoleRows(icons)
card.plays(s, { guitar })               // <span class="line-plays"> | null, put right after the title (rows.js resultRow)
card.tiles(s, { guitar, acts, claimed }) // <div class="tiles"> | null; claimed (a Set) gets every file a tile shows
card.sites(sites)                        // <div class="card-sites"> | null
card.progressions(items)                 // <div class="progressions"> | null
card.findElsewhere(groups)               // <div class="find-elsewhere"> | null
card.foot(s, { actions, book, info, remove }) // <div class="foot"> | null
```

- Each part is a self-contained element styled by its own classes in card.css, never by where lane 1 puts it (3a.1
  makes that true of the parts, and 3b.4 of the card's box, keyed to `.line-panel.song-card`); lane 1 orders and
  places them (in the line on a phone, in the pane on a laptop) and may build them on first open: nothing in card.js measures the page or observes a resize after 3b.3.
- `plays`: each child is `a.play.play-<kind>[.auto]` with `data-kind`, `data-inst`, `aria-label` and `title` as today
  (library.js `showRequest` focuses `.line-plays a`); inside, `svg.glyph`, `span.play-words[aria-hidden]`
  (`span.play-kind`, `span.play-site`), `span.n[aria-hidden]` (more than one version) and `span.marks[aria-hidden]`.
  card.css shows the words with a mouse and the marks on a touch screen.
- Placement stays lane 1's: rows.css keeps one rule for the buttons, `.line-title > .line-plays { flex: none;
  max-width: calc(100% - 5rem); }`, which lane 1 may change, and library.css lane 1's other placement rules (a
  selector ending `.line-title > .line-plays`, 1b's folded grids) and its `#card-pane …` rules (1d.6's
  `#card-pane .foot-menu`), the only names of `.play`, `.line-plays` or `.foot*` outside card.css that 3a.1's guard
  allows. **Chips are wide** ("Guitar Pro · gtptabs" is about
  150 px): lane 1's laptop line (1b, 1d's 760 px list) gives them room as the mockup does (title, chips, key, chevron;
  no artist column), or they wrap under that rule.
- **History**: the card's ⋯ menu (3b.5) pushes `{ caracoleMenu: <n> }` on a touch screen, plus `search:
  (Number(history.state && history.state.search) || 0) + 1` while `body.search-mode` is on ("Where the lanes meet" 1
  and 2), never a spread of `history.state` (which would copy `search: n` where n + 1 is owed). Lane 1's own pushes
  (search mode, leaving Library) build their state from their own members and never carry `caracoleMenu`; its
  `popstate` handlers read their own members alone and act only when those changed. card.js's handler skips
  (`history.back()`) an entry that still carries `caracoleMenu` once its menu has closed.

Cross-lane points this section raises are listed at its end.

---

### Lane 3a: the play buttons

Branch `feat/library-play-buttons` from `main`, worktree `git worktree add ../caracole-play -b
feat/library-play-buttons main`.

#### Task 3a.1: The play buttons' rules in card.css, the line's in rows.css

A move: nothing looks different.

**Files:**
- Modify: `src/caracole/library_assets/card.css` (gains the play buttons' rules and the lit rule; keeps the opened
  line's box, its first block, where it is: "Where the lanes meet" 3, which 3b.4 keys; its foot rule written by the
  foot's own class)
- Modify: `src/caracole/library_assets/rows.css` (loses `.line-plays`' inner rules, every `.play` rule, including the
  `@media (pointer: coarse)` block's five lines "A play button a thumb's 44 px square…", and `.line-panel .foot`;
  keeps `.line-title > .line-plays { flex: none; max-width: calc(100% - 5rem); }`)
- Modify: `src/caracole/library_assets/filter.css` (loses the lit rule `[data-lit~="sheet"] .line-plays
  .play[data-inst~="sheet"], …`)
- Modify: `src/caracole/library_assets/library.css` (loses `.foot { display: flex; }` and `.foot form { margin: 0; }`)
- Modify: `AGENTS.md` ("index.html's assets (library_assets/)": a line "The play buttons', the foot's and the opened
  card's box's rules are card.css's; where the buttons sit on a line (a selector ending `.line-title > .line-plays`,
  rows.css and library.css) and the laptop's pane (`#card-pane …`, library.css) are lane 1's: test_library_assets.py")
- Test: `tests/test_library_assets.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the seam both lanes keep, pinned by the test: `.play`, `.line-plays` and `.foot*` are styled in card.css
  alone, but for lane 1's placement rules (a selector ending `.line-title > .line-plays`, in rows.css or library.css:
  rows.css's one rule and 1b.3's and 1b.4's folded grids) and its `#card-pane …` rules (library.css: 1d.6's
  `#card-pane .foot-menu`); card.css's `.line`, `.line-panel` and `.line-title` selectors are the opened line's box
  alone (`.line:not(.hit)…`, `.line.card-gone…`, and `.line-panel.song-card` once 3b.4 keys it).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_library_assets.py
SELECTORS = re.compile(r"(?:^|[{}])\s*([^{}@][^{}]*?)\s*\{")  # each rule's selector list, inside @media too
PLAY = re.compile(r"\.(?:play|line-plays|foot(?:-[a-z]+)?)(?![\w-])")
LINE = re.compile(r"\.line(?:-panel|-title)?(?![\w-])")
PLACED = re.compile(r"\.line-title > \.line-plays$")  # lane 1's: where the buttons sit on a line
PANE = re.compile(r"^#card-pane(?![\w-])")  # lane 1's: the laptop's pane (1d.6)
BOX = re.compile(r"^\.line(?::not\(\.hit\)|\.card-gone)|^\.line-panel\.song-card(?![\w-])")  # the opened card's box
LANE_1 = {"rows.css": (PLACED,), "library.css": (PLACED, PANE)}


def selectors_of(name):
    """Each selector of ``name``'s rules, a list split at its top-level commas."""
    lists = SELECTORS.findall(re.sub(r"/\*.*?\*/", "", text_of(name), flags=re.S))
    return [s.strip() for l in lists for s in re.split(r",(?![^()]*\))", l)]


def test_the_play_buttons_and_the_cards_parts_are_styled_in_card_css_alone():
    from caracole.library_page import STYLESHEETS

    others = {name: [s for s in selectors_of(name) if PLAY.search(s)
                     and not any(p.search(s) for p in LANE_1.get(name, ()))]
              for name in STYLESHEETS if name != "card.css"}
    assert {name: found for name, found in others.items() if found} == {}  # but lane 1's placement and pane rules
    assert [s for s in selectors_of("card.css") if LINE.search(s) and not BOX.search(s)] == []  # the box alone
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q
  tests/test_library_assets.py::test_the_play_buttons_and_the_cards_parts_are_styled_in_card_css_alone`: fails,
  listing rows.css's `.play…` selectors, filter.css's lit rule and library.css's `.foot`.
- [ ] **Step 3: Implement** — Move, text unchanged but for the selectors named here:
  - into card.css, at its end under a comment "A song's line's buttons (card.js plays)": rows.css's `.line-plays` rule
    less `flex` and `max-width` (its `--over`, display, wrap, gap, padding), every `.play…` rule, the `(pointer:
    coarse)` block's `.line-plays` and `.play…` lines in a `@media (pointer: coarse)` of its own, and filter.css's lit
    rule with its comment (card.css comes after filter.css and rows.css in `STYLESHEETS`, and the selectors keep their
    specificity, so the cascade is the same);
  - card.css's first block, the opened line's box (its comment, `.line:not(.hit):has(> .line-more[aria-expanded="true"]),
    .line.card-gone`, its `+ .line` rule, `.line:not(.hit) > .line-panel`), stays where it is, unchanged: 3b.4 keys it
    to `.line-panel.song-card` and `:not(.selected)` ("Where the lanes meet" 3);
  - card.css's `.line:not(.hit) > .line-panel > .foot` becomes `.foot`, merged with library.css's `.foot { display:
    flex; }` and rows.css's `.line-panel .foot` (whose `justify-content: flex-start` it takes; its `margin-top: 2px`
    goes, card.css's `margin: 0` wins today); library.css's `.foot form` moves with it.
  - AGENTS.md's line above.
- [ ] **Step 4: Run it and see it pass** — the test above, then the browser tests that pin today's look:
  `nix develop -c pytest -q tests/test_library_plays.py tests/test_library_card.py
  tests/test_library_filter.py::test_a_lines_button_of_a_chosen_instrument_is_lit` (all pass unchanged), and
  `nix develop -c pytest -q -m "not slow"`.
- [ ] **Step 5: Commit** — regenerate the corpus first (`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0
  tests/test_conformance_*.py`, twice), then `git add src/caracole/library_assets/card.css
  src/caracole/library_assets/rows.css src/caracole/library_assets/filter.css src/caracole/library_assets/library.css
  tests/test_library_assets.py tests/conformance/vectors/web/library_page.json AGENTS.md` and `git commit -m
  "refactor(library): the play buttons' and the foot's rules in card.css alone"`.

#### Task 3a.2: On a touch screen, filled tiles of 48 px, 8 px apart, their sites' letters at 8 px

**Files:**
- Modify: `src/caracole/library_assets/card.css` (its `@media (pointer: coarse)` block of the play buttons)
- Modify: `docs/usage.md` (the paragraph on a song's line, from "A tap on one opens that one at once": on a touch
  screen each button is a tile, the sites' letters (or icons) at its corner, how many versions at the other)
- Test: `tests/test_library_plays.py`

**Interfaces:**
- Consumes: 3a.1's play rules in card.css.
- Produces: on `(pointer: coarse)`, `a.play` 48 × 48 px, no border, filled with `--raised`, radius 12 px
  (`var(--radius-l, 12px)`: "Where the lanes meet" 4);
  `.line-plays` `gap: 8px`; `.n` and `.marks` inside the box's corners (no overhang: `--over` goes); marks 16 px tall,
  their letters 8 px.

- [ ] **Step 1: Write the failing test** — in `test_a_line_is_one_row_its_buttons_whole_and_needs_review_under_it_on_a_phone`,
  add `("320,640", True)` to its sizes and change its target check to:

```python
            w, h = p["box"][1] - p["box"][0], p["box"][3] - p["box"][2]
            if touch:  # a thumb's target, 48 px square, its marks and count inside it
                assert (round(w), round(h)) == (48, 48), p
                assert all(p["box"][0] - .5 <= q[0] and q[1] <= p["box"][1] + .5 and p["box"][2] - .5 <= q[2]
                           and q[3] <= p["box"][3] + .5 for q in p["parts"]), p
        if touch:  # 8 px between two on a row
            boxes = [p["box"] for p in line["plays"]]
            assert all(b[0] - a[1] >= 7.5 for a, b in zip(boxes, boxes[1:]) if same_row(a, b)), (title, boxes)
```

  (the mouse case moves to 3a.3), and a new test:

```python
def test_on_a_touch_screen_a_play_is_a_filled_tile_its_sites_letters_8px(conn, cfg, tmp_path):
    hotel_california(conn, cfg)
    script = PLAYS + """
    const look = (n) => { const s = getComputedStyle(n); return [s.borderTopStyle, s.backgroundColor !== "rgba(0, 0, 0, 0)"]; };
    note("tiles", { tiles: Array.from(lineOf("Hotel California").querySelectorAll(".line-plays > .play")).map(look),
      letters: Array.from(lineOf("Hotel California").querySelectorAll(".play .marks > .source")).map((m) =>
        [m.dataset.source, getComputedStyle(m).fontSize, Math.round(m.getBoundingClientRect().height)]) });"""
    drawn = attribute_of(run(conn, cfg, tmp_path, script, size="390,844", touch=True), "data-tiles")
    assert drawn["tiles"] == [["none", True]] * 5  # no outline; the fill keeps its shape
    # The sheet's UG, the Guitar Pro files' gtptabs and inbox, the harmonica tab's harptabs, the score's inbox (the
    # text tab has no site): letters, or the inbox's glyph, at 8 px on a mark 16 px tall.
    assert drawn["letters"] == [["ug", "8px", 16], ["gtptabs", "8px", 16], ["inbox", "8px", 16],
                                ["harptabs", "8px", 16], ["inbox", "8px", 16]], drawn
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_plays.py -k "touch or one_row"`:
  44 ≠ 48, the marks overhang by 4 px, `borderTopStyle` is "solid", the letters are "7px" and 15 px tall.
- [ ] **Step 3: Implement** — in card.css's coarse block: `.line-plays { gap: 8px; padding: 0; }`, `.play { --mark-size:
  16px; width: 48px; height: 48px; border: 0; border-radius: var(--radius-l, 12px); background: var(--raised); }`,
  `.play svg.glyph` 24 px, `.play .n { top: 3px; right: 3px; font-size: 10px; }`, `.play .marks { right: 3px; bottom: 3px; }`, `.play
  .marks > .source { width: auto; min-width: 16px; height: 16px; padding: 0 2px; font-size: 8px; line-height: 16px; }`
  (an `img.source` stays 16 × 16). `:hover` keeps the fill, a shade darker (`color-mix(in srgb, var(--text) 8%,
  var(--raised))`). docs/usage.md's tile.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_library_card.py
  -k "reads or touch"` (contrast and targets still met).
- [ ] **Step 5: Commit** — corpus regenerated as in 3a.1; `git add src/caracole/library_assets/card.css
  tests/test_library_plays.py tests/conformance/vectors/web/library_page.json docs/usage.md`; `git commit -m "feat(library): a
  phone's play tiles 48 px, 8 px apart, their sites' letters at 8 px"`.

#### Task 3a.3: With a mouse, a chip naming the kind and the site ("Chords · UG")

**Files:**
- Modify: `src/caracole/library_assets/card.js` (`plays`; new `PLAY_KIND`, `PLAY_SITE`, `playWords`)
- Modify: `src/caracole/library_assets/card.css` (the play buttons' base rules become the chip; the coarse block
  hides the words and shows the marks; the lit rule covers the chip's glyph and site)
- Modify: `tests/helpers/browser.py` (`FINE_POINTER`)
- Modify: `docs/usage.md` (the paragraph on a song's line, from "A tap on one opens that one at once": with a mouse a
  chip that says what it is and where it came from, "Chords · UG", "Guitar Pro · gtptabs", "Harmonica · harptabs",
  how many after it, whatever the window's width), `AGENTS.md` ("index.html's assets (library_assets/)": rule 11 of
  "Where the lanes meet": the line's buttons are card.js `plays`, each showing, on a touch screen, its sites' marks;
  with a mouse, its kind and its site in words (`play-words`); how many)
- Test: `tests/test_library_plays.py`, `tests/test_library_filter.py`

**Interfaces:**
- Consumes: 3a.2's coarse tile.
- Produces: in every `a.play`, after its `svg.glyph`, `span.play-words[aria-hidden="true"]` holding `span.play-kind`
  (the kind) and, where the thing has a site, `span.play-site` (" · " and the site); then `.n`, then `.marks`. The
  `aria-label` and `title` are as today. `tests/helpers/browser.py` `FINE_POINTER`, the switches for a mouse.

- [ ] **Step 1: Write the failing test**

```python
# tests/helpers/browser.py
# Chromium's switches for a mouse, (pointer: fine) and (hover: hover), which headless Chromium reports as none:
# Browser(profile, args=FINE_POINTER).
FINE_POINTER = ("--blink-settings=primaryPointerType=4,availablePointerTypes=4,primaryHoverType=2,availableHoverTypes=2",)
```

```python
# tests/test_library_plays.py
CHIPS = PLAYS + r"""
note("chips", Array.from(document.querySelectorAll("#list .line")).map((l) => [l.querySelector("h3").textContent,
  Array.from(l.querySelectorAll(".line-plays > .play")).map((a) => ({
    words: a.querySelector(".play-words").checkVisibility() ? text(a.querySelector(".play-words")) : null,
    n: a.querySelector(".n") && a.querySelector(".n").checkVisibility() ? text(a.querySelector(".n")) : null,
    marks: a.querySelector(".marks") ? a.querySelector(".marks").checkVisibility() : null,
    height: Math.round(a.getBoundingClientRect().height),
    hidden: a.querySelector(".play-words").getAttribute("aria-hidden") }))]));
"""
WORDS = {"Hotel California": ["Chords · UG", "Guitar Pro · gtptabs", "Tab", "Harmonica · harptabs", "Score · inbox"],
         "Take It Easy": ["Chords · UG", "Harmonica · harptabs"], "斑马，斑马": ["Auto sheet"],
         "De Música Ligera": ["Chords · LaCuerda"]}


def chip_library(conn, cfg):
    """Hotel California with its versions (6 of its sheet, 2 Guitar Pro files), Take It Easy, an auto sheet alone
    and a LaCuerda sheet: nine buttons."""
    with_versions(conn, cfg, hotel_california(conn, cfg))
    harmonica_song(conn, cfg)
    zebra = add_song(conn, "宋冬野", "斑马，斑马")
    put(cfg, zebra, "sheet (auto).html", "sheet (auto).pdf")
    update_song(conn, zebra.id, status="found")
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")  # a LaCuerda sheet
    lc = upsert_version(conn, provider="lacuerda", tab_id="soda_stereo/de_musica_ligera", song_id=soda.id,
                        slot="sheet", kind="acordes", rating=0, votes=0, version=1, label=None,
                        url="https://acordes.lacuerda.net/soda_stereo/de_musica_ligera.shtml", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=soda, version_id=lc, name="sheet.txt", data=b"[ch]Am[/ch]\nx", rank=1)
    put(cfg, soda, "sheet.html")
    update_song(conn, soda.id, status="found")


@pytest.mark.parametrize(("size", "touch"), [("1280,900", False), ("390,844", False), ("1280,900", True)])
def test_the_pointer_decides_chips_for_a_mouse_tiles_for_a_thumb_whatever_the_width(conn, cfg, tmp_path, size, touch):
    chip_library(conn, cfg)
    drawn = dict(attribute_of(run(conn, cfg, tmp_path, CHIPS, size=size, touch=touch), "data-chips"))
    for title, words in WORDS.items():
        shown = drawn[title]
        if touch:  # a tile: its icon, the sites' marks at its corner, no words
            assert all(p["words"] is None and p["marks"] is not False and p["height"] == 48 for p in shown), shown
        else:  # a chip of about 28 px: the kind and the site in words, its count after them, no marks
            assert [p["words"] for p in shown] == words, (title, shown)
            assert all(p["height"] == 28 and p["marks"] in (False, None) for p in shown), shown
        assert all(p["hidden"] == "true" for p in shown)  # its name is its aria-label, as before
    if not touch:
        assert [p["n"] for p in drawn["Hotel California"]] == ["6", "2", None, None, None]


def test_a_real_mouse_gets_the_chips(conn, cfg, tmp_path):
    from helpers.browser import FINE_POINTER, Browser
    from test_library_page import page

    from caracole.library_page import write_library_page

    chip_library(conn, cfg)
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    with Browser(tmp_path / "chrome", args=FINE_POINTER) as b:
        b.open(path.as_uri())
        assert b.wait("document.querySelectorAll('#list .line-plays .play').length === 9")
        assert b.js("matchMedia('(pointer: fine)').matches") is True
        assert b.js("Array.from(document.querySelectorAll('#list .line-plays .play-words'))"
                    ".filter((w) => w.checkVisibility()).length") == 9


def test_a_chip_never_wraps_its_words_beside_a_long_title(conn, cfg, tmp_path):
    long = add_song(conn, "宋冬野", "斑马，斑马，你不要睡着啦，再给我看看你受伤的尾巴，我不想去触碰你伤口的疤")
    put(cfg, long, "sheet (auto).html", "sheet (auto).pdf")
    update_song(conn, long.id, status="found")
    script = PLAYS + """const l = document.querySelector("#list .line"), h3 = l.querySelector("h3");
    note("long", { cut: h3.scrollWidth > h3.clientWidth, chips: Array.from(l.querySelectorAll(".play"))
      .map((a) => Math.round(a.getBoundingClientRect().height)) });"""
    phone = attribute_of(run(conn, cfg, tmp_path, script, size="390,844"), "data-long")
    assert phone == {"cut": True, "chips": [28]}, phone  # the title cut short, the chip whole on one line
    assert attribute_of(run(conn, cfg, tmp_path, script, size="1280,900"), "data-long")["chips"] == [28]
```

  In `test_a_line_is_one_row…` the mouse's size check becomes `assert round(h) == 28 and round(w) >= 28, p`. In
  `tests/test_library_filter.py::test_a_lines_button_of_a_chosen_instrument_is_lit` (a mouse: chips), `held` notes
  too each lit chip's `getComputedStyle(a.querySelector("svg.glyph")).color` and `.play-site`'s, and the test asserts
  both equal the `--on-accent` probe's colour on the lit ones.
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_plays.py -k "chip or mouse or
  pointer" tests/test_library_filter.py -k lit`: no `.play-words` (`querySelector(...)` is null), 24 ≠ 28.
- [ ] **Step 3: Implement** — card.js, beside `PLAYS`:
  - `PLAY_KIND = { sheet: "Chords", ukulele: "Ukulele", auto: "Auto sheet", guitar: "Guitar Pro", tab: "Tab",
    harmonica: "Harmonica", gametab: "Game tab", score: "Score" }`, a sheet's key `auto` when `t.auto`, `ukulele` when
    `t.glyph === "ukulele"`;
  - `PLAY_SITE = { auto: "", inbox: "inbox" }`, else the source's `ICONS` name (`nameOf`, only for a key ICONS has);
  - the site is the thing's first source (`t.sources[0]`, the one in use); none: no `.play-site`;
  - `plays` appends, after the glyph, `span.play-words` (`aria-hidden="true"`) with `span.play-kind` and `span.play-site`
    (text " · " + site), then `.n`, then `.marks`.
  - card.css base (no media query, so a mouse and no pointer): `.play { display: inline-flex; align-items: center;
    gap: 5px; height: 28px; padding: 0 9px 0 7px; border: 0; border-radius: var(--radius-m, 8px); background:
    var(--raised); color: var(--text); font-size: .8rem; font-weight: 600; line-height: 1; white-space: nowrap; text-decoration: none; }`,
    `.play svg.glyph { flex: none; width: 16px; height: 16px; color: var(--accent); }`, `.play.auto svg.glyph { color:
    var(--auto); }`, `.play-site { color: var(--muted); font-weight: 600; }`, `.play .n` static, a muted count after the
    words (`margin-left: 2px; color: var(--muted); font-variant-numeric: tabular-nums;`), `.play .marks { display:
    none; }`; coarse: `.play { display: inline-grid; place-items: center; padding: 0; }`, `.play-words { display:
    none; }`, `.play .marks { display: flex; }`, `.n` absolute as 3a.2. The lit rule gains `… .play[data-inst~="X"]
    :is(svg.glyph, .play-site, .n) { color: inherit; }` for each instrument.
  - docs/usage.md's chip, and AGENTS.md's sentence (rule 11): "on a touch screen, its sites' marks; with a mouse, its
    kind and its site in words".
- [ ] **Step 4: Run it and see it pass** — the command of step 2, then `nix develop -c pytest -q
  tests/test_library_plays.py tests/test_library_card.py tests/test_library_page.py tests/test_web_page.py`.
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/card.js
  src/caracole/library_assets/card.css tests/helpers/browser.py tests/test_library_plays.py
  tests/test_library_filter.py tests/conformance/vectors/web/library_page.json docs/usage.md AGENTS.md`; `git commit -m "feat(library): with a
  mouse a play button is a chip naming its kind and its site"`.

#### Task 3a.4: Merge 3a

- [ ] **Step 1: Docs, checked** (written by 3a.1 to 3a.3) — docs/usage.md, the paragraph on a song's line (from "A tap
  on one opens that one at once"): on a touch screen each button is a tile, the sites' letters (or icons) at its
  corner, how many versions at the other; with a mouse a chip that says what it is and where it came from ("Chords ·
  UG", "Guitar Pro · gtptabs", "Harmonica · harptabs"), how many after it, whatever the window's width. AGENTS.md,
  "index.html's assets (library_assets/)": the line's buttons are card.js `plays`, on a touch screen its sites'
  marks, with a mouse its kind and its site in words (rule 11, 3a.3's); and 3a.1's line on the seam (the play
  buttons', the foot's and the opened card's box's rules card.css's; lane 1's placement and pane rules;
  test_library_assets.py). A gap goes into a `docs:` commit here.
- [ ] **Step 2: The gates** — `nix develop -c pytest -q` (whole suite); `CARACOLE_CORPUS=write nix develop -c pytest -q
  -n 0 tests/test_conformance_*.py` twice and `git status` shows only `tests/conformance/vectors/web/library_page.json`
  changed, then `nix develop -c pytest -q -n 0 tests/test_conformance_*.py` passes in check mode; `nix develop
  ./android -c gradle -p android test` (LibraryPageTest, LibraryAssetsTest, AssemblyTest read the new vector and
  copies); `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus moved);
  `nix flake check`.
- [ ] **Step 3: Look at it** — `caracole serve` on a demo library (docs/screenshots/make.py builds one): a laptop's
  chips, and the phone (the app on the Sony, or Chromium's device mode with touch) at 390 and 320 px.
- [ ] **Step 4: Merge** — rebase onto `main` if lane 1 merged first (rows.css, filter.css, library.css: keep lane 1's
  lines, move only the rules 3a.1 names); `git checkout main && git merge --no-ff feat/library-play-buttons`, then
  push main: `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

---

### Lane 3b: the card's insides

Branch `feat/library-card-insides` from `main` once 3a and lane 1's 1d have merged: `git worktree add ../caracole-card
-b feat/library-card-insides main`. Its tests read a card's parts only through tests/helpers/cards.py (1d.1: `cardOf`,
`openCardOf`, `open_card`, `card_of`), at every width: from 1200 px an open card is in `#card-pane`, not in its line.

#### Task 3b.1: A rating as "★ 4.85 (81)", "New" without one

**Files:**
- Modify: `src/caracole/library_assets/card.js` (`stars` becomes `rated`; `versionRow`'s `votes` goes; `ugDrawer`;
  `things`' sheet `from`)
- Modify: `src/caracole/library_assets/card.css` (`.vrow .stars .new`)
- Modify: `docs/usage.md` (the card's paragraphs, from "Then what you play from it, a tile each": a tile's name and
  version, `Ver 3 · ★ 4.86 (408) · in use`; a rating with its votes, "New" for a version nobody rated)
- Test: `tests/test_library_card.py`, `tests/test_library_page.py`, `tests/test_sheet_versions_end_to_end.py`

**Interfaces:**
- Consumes: the data's `versions.list[]` `rating` and `votes`.
- Produces: `rated(v)`: `"★ " + rating.toFixed(2) + " (" + votes.toLocaleString("en") + ")"` when
  `typeof v.rating === "number" && isFinite(v.rating) && Number(v.votes) > 0`, else `"New"`. A UG row's `.stars`
  holds `<b>★ 4.86</b> (408)` or `<span class="new">New</span>`; the sheet tile's `from` is
  `"Ver 3 · ★ 4.86 (408) · in use"`.

- [ ] **Step 1: Write the failing test** — change the expected values: in `test_tiles_in_order_with_their_open_links`
  `from` is `"Ver 3 · ★ 4.86 (408) · in use"`; in `test_the_ug_drawer_lists_the_kept_versions_and_counts_the_rest` the
  stars are `"★ 4.86 (408)"`, `"★ 4.75 (850)"`, `"★ 4.70 (800)"`; in test_library_page.py's
  `test_a_lines_menu_lists_its_kept_versions…` `"★ 4.86 (408)"`, `"★ 4.85 (12,629)"`, `"★ 4.70 (3,000)"`; in
  test_sheet_versions_end_to_end.py `"★ 4.90 (100)"`. New:

```python
def test_a_version_with_no_rating_is_new(conn, cfg, tmp_path):
    song = add_song(conn, "Radiohead", "Creep")
    v = upsert_version(conn, provider="ug", tab_id="7", song_id=song.id, slot="sheet", kind="chords", rating=0,
                       votes=0, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-7",
                       raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.txt", data=b"[ch]G[/ch]\nx", rank=1)
    upsert_version(conn, provider="ug", tab_id="8", song_id=song.id, slot="sheet", kind="chords", rating=4.5, votes=3,
                   version=2, label=None, url="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-8", raw={},
                   now="x")  # a second, not kept: one version alone would be a fixed chip, with no drawer to open
    put(cfg, song, "sheet.html")
    update_song(conn, song.id, status="found")
    script = ('const card = noteCard("Creep");\nchipOf("Creep", "ug").click();\n'
              'note("new", { from: card.tiles[0].from, stars: noteDrawer("Creep").rows.map((r) => r.stars) });')
    assert attribute_of(run(conn, cfg, tmp_path, script), "data-new") == {"from": "Ver 1 · New · in use",
                                                                         "stars": ["New"]}
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card.py -k "new or tiles_in_order
  or ug_drawer" tests/test_sheet_versions_end_to_end.py tests/test_library_page.py -k "kept_versions or
  sheet_versions"`: "4.86★ · 408 votes" ≠ "★ 4.86 (408)", "Ver 1 · 0.00★ · in use".
- [ ] **Step 3: Implement** — `rated` as above; `ugDrawer` gives `versionRow` `{ ver, stars: rated(x), … }` and
  `versionRow` draws `★ r` bold and ` (n)` plain, or `span.new`; the sheet's `from` joins `rated(one)`. `.vrow .stars
  .new { color: var(--muted); font-weight: 650; }`. docs/usage.md as above.
- [ ] **Step 4: Run it and see it pass** — the command of step 2, then `nix develop -c pytest -q
  tests/test_library_card.py::test_the_card_reads_in_both_themes`.
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/card.js
  src/caracole/library_assets/card.css tests/test_library_card.py tests/test_library_page.py
  tests/test_sheet_versions_end_to_end.py tests/conformance/vectors/web/library_page.json docs/usage.md`; `git commit -m
  "feat(library): a version's rating with its votes, ★ 4.85 (81), and New for none"`.

#### Task 3b.2: A UG version named by what differs ("Acoustic")

**Files:**
- Modify: `src/caracole/library_assets/card.js` (`ugDrawer`'s note)
- Modify: `docs/usage.md` (the card's paragraphs: a UG version's note names what differs, "Acoustic")
- Test: `tests/test_library_card.py`

**Interfaces:**
- Consumes: `versions.list[].label` (null, or UG's part, or "acoustic").
- Produces: a UG row's note starts with the label, its first letter upper-case ("Acoustic", "Intro"), before its share
  of the lyrics; the row's `.ver` stays "Ver N", so the ratings' column lines up.

- [ ] **Step 1: Write the failing test**

```python
def test_a_ug_version_is_named_by_what_differs(conn, cfg, tmp_path):
    song = hotel(conn, cfg)
    conn.execute("UPDATE versions SET label = 'acoustic' WHERE song_id = ? AND tab_id = '46191'", (song.id,))
    script = 'chipOf("Hotel California", "ug").click();\nnote("drawer", noteDrawer("Hotel California"));'
    rows = attribute_of(run(conn, cfg, tmp_path, script), "data-drawer")["rows"]
    assert [(r["ver"], r["note"]) for r in rows] == [("Ver 3", "All the lyrics · our pick"),
                                                     ("Ver 4", "Acoustic · 80% of the lyrics"),
                                                     ("Ver 5", "50% of the lyrics")]
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card.py -k differs`: the note
  is "80% of the lyrics".
- [ ] **Step 3: Implement** — in `ugDrawer`, before `share`: `if (typeof x.label === "string" && x.label)
  note.push(x.label.charAt(0).toUpperCase() + x.label.slice(1))`; docs/usage.md as above.
- [ ] **Step 4: Run it and see it pass** — the same command.
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/card.js tests/test_library_card.py
  tests/conformance/vectors/web/library_page.json docs/usage.md`; `git commit -m "feat(library): a UG version named
  by what differs, Acoustic, Intro"`.

#### Task 3b.3: A drawer for each tile, its versions by source and its downloads in it

The tile's chips go: a tile has one chevron, which opens its drawer right under it, holding its downloads (PDF, Text,
ChordPro, the exports; a Guitar Pro file's; …) and a part a source of its versions (UG's, LaCuerda's, the auto sheet,
a Guitar Pro file's source…), each part what that chip's drawer was. Grouped by kind, as the tiles already are.

**Files:**
- Modify: `src/caracole/library_assets/card.js` (`tileOf`, `tiles`, `drawerHead` and the four drawers' targets;
  `place`, `placed` and the `ResizeObserver` go)
- Modify: `src/caracole/library_assets/card.css` (`.tile-source`, `.tile-more`, `.drawer-files`, `.drawer-part`; the
  `.vchip`, `.tile-versions`, `.tile-downloads` rules go; the drawer's `--point` arrow goes)
- Modify: `docs/usage.md` (the card's paragraphs: the chevron opens its drawer under it, its downloads first (the
  sheet's PDF, PDF Traditional, Text, ChordPro and its exports; a Guitar Pro file's; the lyrics' Text and Timed; each
  score's format), then a part a source of its versions, as the chips' drawers were; the Lyrics tile's "From
  Megalobiz" (lines 1943, 1969) is its source's link on the tile's row), `AGENTS.md` ("index.html's assets": "a tile
  for each thing to play from, every one alike, its chevron opening its drawer under it (its downloads, then a part
  a source of its versions), which reads the page's data alone, never a request"; under megalobiz, "the card's Lyrics
  tile" stays true)
- Test: `tests/test_library_card.py` (`KIT` and the tests below), `tests/test_library_page.py`,
  `tests/test_sheet_versions_end_to_end.py`, `tests/test_web_downloads.py`

**Interfaces:**
- Consumes: `things(s, opts)`'s `{ kind, name, open, said, from, chips, downloads, sources, count, unit }`, unchanged.
- Produces (lane 1 and the tests read these):
  - `div.tile.tile-<kind>[.auto][.stack][.open]`: `a.tile-open` (as today: `.tile-ico`, `.tile-words` with
    `.tile-name` (its id the drawer's label) and `.tile-from`, `.tile-go`); `.tile-source`, the thing's sources' marks
    (`t.sources`, two at most, as its play button; none for a thing with no source), or, for a tile with one fixed
    source that links back
    (`chip.href`: Megalobiz's, AZLyrics' lyrics), `a.tile-source[target=_blank][rel="noopener noreferrer"]` with the mark
    and `span.tile-source-name`, `aria-label` "Lyrics: its page on Megalobiz"; `button.tile-more` (a chevron glyph,
    `aria-expanded`, `aria-controls` the drawer's id, `aria-label` `t.name + ": its " + words`, words "versions and
    downloads", "files and downloads", "tabs and downloads" by `t.unit`, or "downloads" alone), present when the
    drawer would hold anything.
  - one `div.drawer[role=region][hidden]` a card, `aria-labelledby` the open tile's `.tile-name`, `data-tile` its
    kind, placed right after that tile: `button.drawer-close` ("Close: " + name), then `div.drawer-files` (`span.lead`
    "Download", then `t.downloads`' `a.dl`s) when it has any, then a `section.drawer-part[data-source]` a chip that
    has a `fill`, unless the tile's one chip is `fixed` (then its mark in `.tile-source` says it all): its
    `.drawer-head` (mark, `h4.drawer-what`, `.drawer-said`, its extra: Back to our pick, the pin note), `ol.vrows`,
    `.drawer-rest`, as each drawer drew them (`ugDrawer(s, part, acts)`, `lacuerdaDrawer`, `autoDrawer`,
    `filesDrawer`, now given the part).
  - One drawer open at a time: a chevron opens its tile's (closing another), again closes it; ✕ and Escape close it
    and give the focus back to the chevron; nothing is asked of anyone.
  - Test KIT (`tests/test_library_card.py`, shared by test_library_page.py, test_library_plays.py,
    test_sheet_versions_end_to_end.py), each of its helpers reading the card through cards.KIT's
    `cardOf(lineOf(title))` (1d.1), so a card in `#card-pane` too: `chipOf` goes; `drawerOf(title, kind)` opens the
    card and that tile's drawer and returns its chevron; `noteDrawer(title, source)` returns `{ hidden, id, after, label, tile, files: [{ text,
    said, href, download }], parts: [source…], what, said, head, rows, rest, command, restButtons }`, the last seven of
    the part of `source` (the first part when none is given), as the drawer's were; `noteCard`'s tiles lose `lead`,
    `chips` and `downloads` and gain `sources` (each `.tile-source [data-source]`), `link` (`a.tile-source`'s href, or
    null) and `more` (the chevron's `aria-label`, or null).

- [ ] **Step 1: Write the failing test** — the KIT as above, then:

```python
def test_each_tiles_drawer_holds_its_downloads_and_a_part_a_source(conn, cfg, tmp_path):
    hotel(conn, cfg)
    script = """const card = noteCard("Hotel California");
    const kinds = ["sheet", "guitar", "tab", "harmonica", "lyrics", "score"];
    note("drawers", { more: card.tiles.map((t) => t.more), sources: card.tiles.map((t) => t.sources),
      drawers: kinds.map((k) => { drawerOf("Hotel California", k); const d = noteDrawer("Hotel California");
        return [d.tile, d.after.split(" ")[1], d.files.map((f) => f.text), d.parts]; }),
      open: cardOf(lineOf("Hotel California")).querySelectorAll(".drawer:not([hidden])").length });"""
    shown = attribute_of(run(conn, cfg, tmp_path, script), "data-drawers")
    assert shown["more"] == ["Chord sheet: its versions and downloads", "Guitar Pro: its files and downloads",
                             "Guitar tab: its downloads", "Harmonica tab: its downloads", "Lyrics: its downloads",
                             "Score: its downloads"]
    assert shown["sources"] == [["ug", "lacuerda"], ["gtptabs", "inbox"], [], ["harptabs"], ["lrclib"], ["inbox"]]
    assert shown["drawers"] == [
        ["sheet", "tile-sheet", ["PDF", "Text", "ChordPro", "PDF · G Dorian, capo 0"], ["ug", "lacuerda", "auto"]],
        ["guitar", "tile-guitar", [".gp5"], ["gtptabs", "inbox"]], ["tab", "tile-tab", ["Text"], []],
        ["harmonica", "tile-harmonica", ["Text"], []], ["lyrics", "tile-lyrics", ["Text", "Timed (.lrc)"], []],
        ["score", "tile-score", ["MusicXML"], []]]
    assert shown["open"] == 1  # one at a time, right after its own tile
```

  and migrate, keeping each test's assertions on what it shows:
  - test_library_card.py: `test_tiles_in_order_with_their_open_links` (its `downloads` asserts go to the new test),
    `test_lyrics_from_megalobiz…` and `…azlyrics…` (`.tile-lyrics a.tile-source`, its `.tile-source-name`),
    `test_a_tab_of_game_music…` (`sources == ["gametabs"]`, its drawer's files `["Text"]`, part `gametabs` said "2
    tabs"), `test_the_sheet_tile_downloads_pdf_text_chordpro_and_each_export` (the sheet drawer's `files`),
    `test_chips_count_versions_per_source` (goes: the new test and the parts' `said` in the drawer tests hold it;
    the stack asserts move to the new test), `test_a_chip_opens_its_drawer_and_another_chip_closes_it` (becomes
    `test_a_tiles_chevron_opens_its_drawer_and_another_closes_it`: the sheet's chevron, then the guitar's, then the
    guitar's again), the UG, LaCuerda and auto, files and Escape tests (`drawerOf` and `noteDrawer(title, source)`;
    Escape gives the focus to `.tile-sheet button.tile-more`), `QUIET` (every `button.tile-more` twice: `chevrons:
    6`), `test_a_text_tab_alone…`, `test_a_score_you_filed…`, `test_an_auto_sheet_alone…` (their drawers' files),
    `test_the_file_page_offers_no_change…`, `test_the_card_meets_touch_targets_with_a_drawer_open` (`drawerOf`),
    `READS` (`.dl` as `.drawer .dl`, no `.tile-versions .lead` or `.vchip .n`, plus `.tile-from`),
    `test_a_line_drawn_again_keeps_its_card_open_and_its_drawer_closed` (six chevrons all `"false"`), and the served
    tests (`drawer_of(browser, song)` opens the sheet's; `press` and the `.vrow` lists scoped to
    `.drawer-part[data-source="ug"]` or `"lacuerda"`, where both parts now show a Use this one);
    `test_a_drawer_left_open_in_a_folded_card_is_placed_again…` goes: the drawer is its tile's next sibling, so
    nothing is placed again.
  - test_library_page.py: `test_the_written_pages_guitar_pro_links…` (opens the sheet's, the guitar's and the score's
    drawers one after the other, noting the downloads of each), `test_each_file_shows_its_sites_icon_or_badge…`
    (`MARKS`'s `where` names `.tile-source` "tile": UG's and LRCLIB's marks are the tiles'),
    `test_a_lines_menu_lists_its_kept_versions…` (its export is in the sheet drawer's files), `test_a_song_whose_sheet_is_lacuerdas…`.
  - test_sheet_versions_end_to_end.py (`drawerOf("Creep", "sheet")`, `noteDrawer("Creep", "ug")`), test_web_downloads.py
    (`.tile-guitar button.tile-more`).
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card.py -k
  each_tiles_drawer`: no `button.tile-more` (`drawerOf` throws: `more` is null).
- [ ] **Step 3: Implement** — `tileOf(t, i)` builds the row above; `tiles` keeps one drawer, a `fill(t, tileBox)` that
  `replaceChildren`s it (close, files, parts) and `tileBox.after(drawer)`, `tileBox.classList.add("open")`; `close`
  empties it, takes `open` off and hides it. A tile's downloads are made once in `things` and moved into the drawer
  each time it opens. card.css: `.tile-source { display: flex; align-items: center; gap: 4px; }`, `.tile-more` a
  32 × 32 px glyph button (44 on a touch screen), its chevron turned while expanded (the transition only under
  `prefers-reduced-motion: no-preference`), `.drawer-files { display: flex; flex-wrap: wrap; align-items: center; gap:
  4px 14px; padding: 10px 48px 10px 12px; }`, `.drawer-part + .drawer-part, .drawer-files + .drawer-part { border-top:
  1px solid var(--border); }`, `.drawer-close` at the drawer's top right as today. The docs above.
- [ ] **Step 4: Run it and see it pass** — `nix develop -c pytest -q tests/test_library_card.py
  tests/test_library_page.py tests/test_sheet_versions_end_to_end.py tests/test_web_downloads.py
  tests/test_library_plays.py`.
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/card.js
  src/caracole/library_assets/card.css tests/test_library_card.py tests/test_library_page.py
  tests/test_sheet_versions_end_to_end.py tests/test_web_downloads.py tests/conformance/vectors/web/library_page.json
  docs/usage.md AGENTS.md`; `git commit -m "feat(library): a drawer for each tile, its downloads and its versions by
  source in it"`.

#### Task 3b.4: A tile one row at every width; the card at a pane's width

**Files:**
- Modify: `src/caracole/library_assets/card.css` (`.tiles` a container; `.tile` one grid row; the `@media (min-width:
  720px)` and `(max-width: 719px)` rules become `@container tiles` rules; the opened card's box keyed, "Where the
  lanes meet" 3: `.line:not(.hit) > .line-panel` becomes `.line-panel.song-card`, and `:not(.selected)` joins
  `.line:not(.hit):has(> .line-more[aria-expanded="true"])` and its `+ .line` rule)
- Modify: `docs/usage.md` (the card's paragraphs: a tile is one row, its name and version, the marks of where it came
  from, a chevron), `AGENTS.md` (3b.3's tile sentence: "every one alike, one row")
- Test: `tests/test_library_card.py`

**Interfaces:**
- Consumes: 3b.3's tile and drawer; 1d.2's `song-card` on every song's panel, 1d.6's `selected` on a line whose card
  is in `#card-pane`.
- Produces: `.tiles { container: tiles / inline-size; grid-template-columns: 1fr; }`; a tile is one row (its open
  link, its sources, its chevron) 56–64 px tall on a touch screen, at most 48 px with a mouse; its drawer touches it
  (`.tile.open` square bottom corners, the drawer square top ones, same left and right); `.vrow`'s four columns from
  a card 560 px wide (`@container tiles (min-width: 560px)`), stacked below, whatever the window, so the card reads
  the same in lane 1's 400–480 px pane and in place. The box (raised, its margin, its panel's gap and padding) is
  `.line-panel.song-card`'s wherever the card is, and a `.selected` line, whose card is in the pane, is no empty card.

- [ ] **Step 1: Write the failing test** — `test_a_tile_is_one_row…` parametrized over `("390,844", True)` and
  `("1280,900", False)`, its `mids` of `.tile-open`, `.tile-source`, `.tile-more` within 16 px, heights `56 <= h <=
  64` on touch and `h <= 48` with a mouse; `test_the_card_fits_with_the_drawer_under_its_tile` over `("320,640",
  True)`, `("390,844", True)`, `("1280,900", False)`: for the sheet and the guitar, the drawer is the tile's next
  sibling, its top within 1 px of the tile's bottom, its left and right those of the tile, the score's tile under the
  guitar's drawer, no horizontal scroll; and:

```python
PANE = """
const line = openCard("Hotel California");  // at 1440 its card goes into lane 1's #card-pane (1d.6), 400-480 px wide
const card = cardOf(line), pane = document.getElementById("card-pane");
drawerOf("Hotel California", "sheet");
const box = (n) => n.getBoundingClientRect();
const row = card.querySelector('.drawer-part[data-source="ug"] .vrow');
note("pane", { inPane: pane.contains(card), width: pane.clientWidth, wide: pane.scrollWidth,
  stacked: box(row.querySelector(".vbtns")).top >= box(row.querySelector(".ver")).bottom - 0.5,
  rows: Array.from(card.querySelectorAll(".tile")).map((t) => Math.round(box(t).height)) });
"""


def test_the_card_fits_the_laptops_pane_on_a_wide_screen(conn, cfg, tmp_path):
    hotel(conn, cfg)
    pane = attribute_of(run(conn, cfg, tmp_path, PANE, controls=SERVED, size="1440,900"), "data-pane")
    assert pane["inPane"] and 400 <= pane["width"] <= 480 and pane["wide"] <= pane["width"], pane
    assert pane["stacked"] is True and all(h <= 48 for h in pane["rows"]), pane


BOX = """
const line = openCard("Hotel California"), card = cardOf(line), css = getComputedStyle;
note("box", { inPane: document.getElementById("card-pane").contains(card), selected: line.classList.contains("selected"),
  line: css(line).marginTop, card: [css(card).rowGap, css(card).paddingBottom], foot: css(card.querySelector(".foot")).display });
"""


@pytest.mark.parametrize("size", ["1280,900", cards.IN_PLACE])
def test_the_cards_box_is_its_panels_own_and_a_selected_line_is_no_empty_card(conn, cfg, tmp_path, size):
    hotel(conn, cfg)
    box = attribute_of(run(conn, cfg, tmp_path, BOX, controls=SERVED, size=size), "data-box")
    assert box["card"] == ["14px", "14px"] and box["foot"] == "flex", box  # .line-panel.song-card's, in place or not
    if size == "1280,900":  # the card in the pane: its line, selected, isn't raised as an empty card
        assert box["inPane"] and box["selected"] and box["line"] == "0px", box
    else:  # in place, the opened line is raised as today
        assert not box["inPane"] and box["line"] == "6px", box
```

  (`openCard(title)` opens the line's card and returns the line; the KIT's `drawerOf(title, kind)` and the tests read
  the card through `cardOf`, 1d.1's, so the same calls find it in the pane: 3b runs after 1d.)
- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card.py -k "one_row or
  under_its_tile or pane or box"`: at 1440 the `.vrow` has its four columns (the viewport is past 720), the phone's
  tile is three rows high; in the pane the card has no gap or padding of its own (`.line:not(.hit) > .line-panel`
  doesn't match it) and its selected line is raised as an empty card.
- [ ] **Step 3: Implement** — `.tile { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items:
  center; column-gap: 8px; padding-right: 6px; }`, `.tile-open` `padding: 5px 4px 5px 10px` (a mouse) and `9px 4px
  9px 10px` on a touch screen, `.tiles { gap: 8px; }`, `.drawer { margin-top: -8px; }`; the `.vrow` and `.drawer-head`
  width rules under `@container tiles (min-width: 560px)` and `(max-width: 559px)`; the `(min-width: 720px)` tile rules
  go (one row everywhere). The box keyed: card.css's first block becomes `.line:not(.hit):not(.selected):has(>
  .line-more[aria-expanded="true"]), .line.card-gone`, its `+ .line` rule the same, and `.line:not(.hit) >
  .line-panel` becomes `.line-panel.song-card` (its gap and padding the same). The docs above.
- [ ] **Step 4: Run it and see it pass** — the command of step 2, then `nix develop -c pytest -q
  tests/test_library_card.py tests/test_library_page.py -k "mark or card"`.
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/card.css tests/test_library_card.py
  tests/conformance/vectors/web/library_page.json docs/usage.md AGENTS.md`; `git commit -m "feat(library): a card's
  tile one row at every width, the card as at home in a pane"`.

#### Task 3b.5: On a touch screen the ⋯ menu is a history entry, so Back closes it

**Files:**
- Modify: `src/caracole/library_assets/card.js` (`foot`'s `details.foot-more`; one module-level `popstate` listener)
- Modify: `docs/usage.md` (the card's paragraphs: on a touch screen Back closes the ⋯ menu; 1d.8 leaves this to
  this task), `AGENTS.md` (the history contract, `caracoleMenu` and its `search` in search mode, in a line of its own
  under "The pages caracole writes and serves")
- Test: `tests/test_library_card.py`

**Interfaces:**
- Consumes: the history contract above (lane 1's pushes carry no `caracoleMenu`); `body.search-mode` (1c.2);
  tests/helpers/cards.py (1d.1).
- Produces: under `matchMedia("(pointer: coarse)")`, opening ⋯ pushes `{ caracoleMenu: n }` (n a serial), plus
  `search: (Number(history.state && history.state.search) || 0) + 1` while `body.search-mode` is on ("Where the lanes
  meet" 1 and 2), never a spread of `history.state`, same address; Back closes it and leaves the card open; closing it
  otherwise takes that entry back; a mouse pushes nothing.

- [ ] **Step 1: Write the failing test** — on caracole serve's page, served by the `versions_served` fixture (⋯ holds
  Remove there), its card's ⋯ opened by a tap:

```python
MORE = "document.querySelector('{card} details.foot-more')"  # the card wherever it is: cards.open_card's selector
OURS = "Boolean(history.state && history.state.caracoleMenu)"


@contextmanager
def more_menu(conn, cfg, versions_served, tmp_path, *, touch=True):
    """The page in a Browser (a phone's, touch, or a laptop's), Hotel California's card open, then its ⋯; yields the
    browser, the menu's expression, and history's length and address before the ⋯. The card is found through
    tests/helpers/cards.py: under its line on the phone, in #card-pane on the laptop."""
    base, _, _ = versions_served
    song = hotel(conn, cfg)
    with Browser(tmp_path / "chrome", width=390 if touch else 1280, height=844, mobile=touch) as b:
        b.open(base)
        cards.install(b)
        card = cards.open_card(b, f'article.line[data-id="{song.id}"]')
        before = (b.js("history.length"), b.js("location.href"))
        b.click(card + " details.foot-more > summary")
        menu = MORE.format(card=card)
        assert b.wait(f"{menu}.open")
        yield b, menu, before


def test_on_a_touch_screen_back_closes_the_more_menu_and_nothing_else(conn, cfg, versions_served, tmp_path):
    with more_menu(conn, cfg, versions_served, tmp_path) as (b, menu, (length, href)):
        assert b.js("history.length") == length + 1 and b.js(OURS) is True
        b.js("history.back()")
        assert b.wait(f"!{menu}.open")
        assert b.js(f"{menu}.closest('article').querySelector('.line-more').getAttribute('aria-expanded')") == "true"
        assert b.js("location.href") == href and b.js(OURS) is False


def test_closing_the_more_menu_with_escape_takes_its_history_entry_back(conn, cfg, versions_served, tmp_path):
    with more_menu(conn, cfg, versions_served, tmp_path) as (b, menu, _):
        b.press("Escape")
        assert b.wait(f"!{menu}.open && !{OURS}")


def test_an_entry_pushed_as_the_menu_closes_stays_and_the_menus_is_skipped(conn, cfg, versions_served, tmp_path):
    # A tap elsewhere closes the menu, and another part of the page pushes an entry of its own (lane 1's search would).
    with more_menu(conn, cfg, versions_served, tmp_path) as (b, menu, _):
        b.js("document.addEventListener('click', () => history.pushState({ other: 1 }, ''), { once: true });"
             "document.body.click()")
        assert b.wait(f"!{menu}.open && history.state && history.state.other === 1")
        b.js("history.back()")  # one press: the other's entry, and the menu's behind it, skipped
        assert b.wait(f"!(history.state && history.state.other) && !{OURS}")
        assert b.js(f"{menu}.open") is False


def test_with_a_mouse_the_more_menu_pushes_nothing(conn, cfg, versions_served, tmp_path):
    with more_menu(conn, cfg, versions_served, tmp_path, touch=False) as (b, _, (length, _)):  # its card in the pane
        assert b.js("history.length") == length and b.js(OURS) is False


def test_in_search_mode_the_menus_entry_is_one_step_more_and_the_arrow_leaves_search(conn, cfg, versions_served,
                                                                                    tmp_path):
    # "Where the lanes meet" 1 and 2: pushed in search mode, the entry counts one step more than the one under it.
    base, _, _ = versions_served
    song = hotel(conn, cfg)
    with Browser(tmp_path / "chrome", width=390, height=844, mobile=True) as b:
        b.open(base)
        cards.install(b)
        b.click("#q")
        b.type("hotel")  # search mode: one step, { search: 1 }
        assert b.wait("document.body.classList.contains('search-mode') && history.state && history.state.search === 1")
        card = cards.open_card(b, f'article.line[data-id="{song.id}"]')
        b.click(card + " details.foot-more > summary")
        assert b.wait(f"{OURS} && history.state.search === 2")
        b.click("#leave")  # ← takes back both steps: search left, nothing of the menu's left behind
        assert b.wait("!document.body.classList.contains('search-mode')")
        assert b.js("history.state") is None and b.js(f"{MORE.format(card=card)}.open") is False


def test_where_history_refuses_a_push_the_more_menu_still_opens_and_closes(conn, cfg, tmp_path):
    # The file page (⋯ holds info.json there), on a browser that refuses pushState for a file: no error.
    put(cfg, hotel(conn, cfg), "info.json")
    path = write_library_page(cfg.library_dir, page(conn, cfg))
    with Browser(tmp_path / "chrome", width=390, height=844, mobile=True) as b:
        b.open(path.as_uri())
        b.js("history.pushState = () => { throw new DOMException('refused', 'SecurityError'); };"
             "window.errors = 0; addEventListener('error', () => { window.errors += 1; })")
        b.click("#list .line .line-more")
        b.click("#list .line details.foot-more > summary")
        assert b.wait("document.querySelector('#list details.foot-more').open")
        b.press("Escape")
        assert b.wait("!document.querySelector('#list details.foot-more').open") and b.js("window.errors") == 0
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card.py -k "more_menu or
  menus_entry"`: `history.length` unchanged on open.
- [ ] **Step 3: Implement** — the algorithm the tests leave open:

```js
// card.js, beside foot: the ⋯ menus' history entries (a touch screen's Back closes one).
const MENU = "caracoleMenu";
let menus = 0, shown = null;  // shown: { more, n } of the menu whose entry is in the history
const ours = (n) => Boolean(history.state && history.state[MENU] === n);
addEventListener("popstate", () => {
  if (shown && !ours(shown.n)) { const was = shown; shown = null; was.more.open = false; return; }  // Back closed it
  if (!shown && history.state && history.state[MENU]) history.back();  // a closed menu's entry: skip it
});
// in foot, on "toggle":
//   open && matchMedia("(pointer: coarse)").matches: n = ++menus; const entry = { [MENU]: n };
//     if (document.body.classList.contains("search-mode"))  // one step more, never a copy of history.state's
//       entry.search = (Number(history.state && history.state.search) || 0) + 1;
//     try { history.pushState(entry, ""); shown = { more, n }; } catch (err) { /* no entry: it opens all the same */ }
//   closed && shown && shown.more === more: const n = shown.n; shown = null;
//     setTimeout(() => { if (ours(n)) history.back(); }, 0);  // after the tap's own handlers: one that pushed keeps its entry
```

  docs/usage.md (on a touch screen Back closes the ⋯ menu) and AGENTS.md's line (the `caracoleMenu` entry, its
  `search` in search mode, never a spread of `history.state`).

- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_library_card.py
  -k "remove or foot"` and `nix develop -c pytest -q tests/test_library_search_mode.py`.
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/card.js tests/test_library_card.py
  tests/conformance/vectors/web/library_page.json docs/usage.md AGENTS.md`; `git commit -m "feat(library): on a touch
  screen Back closes a card's ⋯ menu"`.

#### Task 3b.6: A calmer card

**Files:**
- Modify: `src/caracole/library_assets/card.css`
- Test: `tests/test_library_card.py`

**Interfaces:**
- Consumes: lane 1f's four corner radii, written as base.css's tokens with their values as fallbacks
  (`var(--radius-s, 4px)`, `var(--radius-m, 8px)`, `var(--radius-l, 12px)`, `var(--radius-pill, 999px)`: "Where the
  lanes meet" 4), so they hold before and after 1f merges.
- Produces: no outline around a tile (its fill keeps its shape) nor an accent edge around the drawer (an edge of
  `--border`); the tile's name and a part's heading at 600; every radius in the card one of 4 px (marks), 8 px
  (buttons, chips, a play chip), 12 px (tiles, the drawer, a play tile), 999 px (pills), each as its token.

- [ ] **Step 1: Write the failing test**

```python
CALM = """
const line = openCard("Hotel California"), card = cardOf(line);  // the card wherever it is (1d.1): the pane at 1280
drawerOf("Hotel California", "sheet");
// card.css's own: base.css's .btn and code are lane 1f's (and the radii it gives them).
const parts = [...line.querySelectorAll(".line-plays, .line-plays *"),
  ...card.querySelectorAll(".tiles, .tiles *, .card-sites *, .progressions *, .find-elsewhere *, .foot, .foot *")]
  .filter((n) => !n.closest(".btn, code"));
note("calm", { tile: getComputedStyle(card.querySelector(".tile")).borderTopStyle,
  drawer: getComputedStyle(card.querySelector(".drawer")).borderTopColor,
  weights: [".tile-name", ".drawer-what"].map((s) => getComputedStyle(card.querySelector(s)).fontWeight),
  radii: [...new Set(parts.map((n) => getComputedStyle(n).borderTopLeftRadius))].sort() });
"""


def test_the_card_is_calm(conn, cfg, tmp_path):
    hotel(conn, cfg)
    calm = attribute_of(run(conn, cfg, tmp_path, CALM, controls=SERVED), "data-calm")
    assert calm["tile"] == "none" and calm["weights"] == ["600", "600"], calm
    assert set(calm["radii"]) <= {"0px", "4px", "8px", "12px", "999px"}, calm
    # and the drawer's edge is --border's, not the accent's (a probe of each, as REMOVE reads --failed)
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_library_card.py -k calm`: the tile's
  border is "solid", 650, radii "11px", "10px", "9px", "7px".
- [ ] **Step 3: Implement** — `.tile { border: 0; }` (`.tile.auto` keeps its colour on its icon), `.drawer { border:
  1px solid var(--border); }`, the stack's layers with no edge, `font-weight: 600` on `.tile-name`, `.drawer-what`,
  `.vrow .ver`; the radii as listed, each as its token with its value for fallback (`.tile-open` `var(--radius-l,
  12px)`, the inner 11 px ones gone with the borders; `.tile-ico` and `.drawer-close` `var(--radius-m, 8px)`; a
  site's mark in the card, `.tile-source .source`, `.drawer-head .source`, and `.play .marks > .source`,
  `var(--radius-s, 4px)`, where rows.css's `.source.letters` gives 5).
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_library_card.py
  -k "reads or touch"` (contrast and targets after the change).
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/card.css tests/test_library_card.py
  tests/conformance/vectors/web/library_page.json`; `git commit -m "style(library): a calmer card, no tile outline,
  titles at 600, four radii"`.

#### Task 3b.7: Merge 3b

- [ ] **Step 1: Docs, checked** (written by 3b.1 to 3b.5) — docs/usage.md, the card's paragraphs (from "Then what you
  play from it, a tile each"): a tile is one row (its name and version, `Ver 3 · ★ 4.86 (408) · in use`, the marks of
  where it came from, a chevron); the chevron opens its drawer under it: its downloads first (the sheet's PDF, PDF
  Traditional, Text, ChordPro and its exports; a Guitar Pro file's; the lyrics' Text and Timed; each score's format),
  then a part a source of its versions, as the chips' drawers were; a rating with its votes, "New" for a version
  nobody rated; a UG version's note names what differs ("Acoustic"); on a touch screen Back closes the ⋯ menu. The
  Lyrics tile's "From Megalobiz" (lines 1943, 1969) is its source's link on the tile's row. AGENTS.md, "index.html's
  assets": "a tile for each thing to play from, every one alike, one row, its chevron opening its drawer under it
  (its downloads, then a part a source of its versions), which reads the page's data alone, never a request"; under
  megalobiz, "the card's Lyrics tile" stays true; the history contract (`caracoleMenu`) in a line of its own under
  "The pages caracole writes and serves". A gap goes into a `docs:` commit here.
- [ ] **Step 2: The gates** — as 3a.4's step 2: `nix develop -c pytest -q` (whole suite); `CARACOLE_CORPUS=write nix
  develop -c pytest -q -n 0 tests/test_conformance_*.py` twice, then `nix develop -c pytest -q -n 0
  tests/test_conformance_*.py` passes in check mode; `nix develop ./android -c gradle -p android test`;
  `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py` (the corpus moved); `nix flake
  check`.
- [ ] **Step 3: Look at it** — a card on the laptop (in place at 1000 px, in lane 1d's pane at 1440 px) and on the
  phone: a long card (Hotel California's), each drawer, ⋯ then Back in the app.
- [ ] **Step 4: The radius skip list** — only if 1f, lane 2 and lane 4 have all merged, this merge is the last of 1f,
  lane 2, 3b and lane 4: `tests/test_page_calm.py`'s `OTHER_LANES = ()` and `test_the_library_page_has_four_corner_radii`
  passes with it (commit `test(library): the four radii across the whole page, no lane left out`); else the list
  stays, for the last of them to remove.
- [ ] **Step 5: The README's screenshots** — only if lanes 1 (1f), 2 and 4 have all merged (lane 3 the last of the
  four): retake them: `nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python
  docs/screenshots/make.py`; for each picture, `git show HEAD:docs/screenshots/<name>.png > old.png` (outside the
  repository) and `compare -metric AE old.png docs/screenshots/<name>.png null:` (ImageMagick, through
  `omnibin-shell` if it isn't on PATH): `git restore` those with 0 differing pixels, keep the others; commit `docs: the
  README's screenshots of the redesigned page`. Else they wait for the last lane.
- [ ] **Step 6: Merge** — rebase onto `main` if anything merged since (1d's card order and lazy build call these
  parts unchanged); `git checkout main && git merge --no-ff feat/library-card-insides`, then push main:
  `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

---

### Lane 4: Songbooks

Branch `feat/songbooks-play` from `main`: `git worktree add ../caracole-songbooks -b feat/songbooks-play main`.

#### Task 4.1: A Play on each songbook's line, its phone page at its first song

**Files:**
- Modify: `src/caracole/library_assets/songbooks.js` (`playOf(b)`, new; `drawList` puts it in each line's `li`; line
  89's `history.replaceState(null, "", "#" + params.toString())` passes `history.state`, "Where the lanes meet" 9)
- Modify: `src/caracole/library_assets/songbooks.css` (`.book-lines > li`, `.book-play`; every `border-radius` one of
  the four as a token with its fallback, by 1f.1's mapping, `.pickbar`'s and `.selecting .pick`'s too, which select.js
  builds outside `#songbooks`: 12 px `var(--radius-l, 12px)`, 10 and 9 px `var(--radius-m, 8px)` (a corner set such
  as `9px 9px 0 0` with its token), 8 px `var(--radius-m, 8px)`, 6 px `var(--radius-s, 4px)`, 999 px
  `var(--radius-pill, 999px)`; and, once Task 1b.1 has merged, the one-artist view's leftovers deleted, "Where the
  lanes meet" 10: `.selecting [data-picker] .filter-mark` and `.selecting [data-picker] .artist-only` out of their
  selector list, and the dead `by` column of `.selecting .line` at ≥ 720 px, which a grouped line no longer has; if
  1b.1 merges after this lane, Task 4.3's rebase deletes them)
- Modify: `docs/usage.md` ("The Songbooks tab": each songbook's line has **Play**, its phone page at its first song
  with a sheet), `AGENTS.md` ("The Songbooks tab": each songbook's Play on its line, songbooks.js `playOf`: its
  `songbook.html` at `#song-N`, N the first set entry with a sheet, `set[].href`, as book.js opens a song)
- Test: `tests/test_songbooks_tab.py`

**Interfaces:**
- Consumes: the tab's data: a book's `files` (`{name, label, href}`), its `set` (`{n, title, href, …}`).
- Produces: `playOf(b)`: `a.btn.small.book-play` with a play glyph (an inline SVG triangle made with
  `createElementNS`, `aria-hidden`) and "Play", `href` = the `files` entry named `songbook.html`'s href + `"#song-" +
  n` of the first set entry with a sheet (`typeof e.href === "string" && e.href`), `aria-label` "Play " + name + " from
  " + that song's title, `title` "Its phone page, at its first song"; null when the songbook has no songbook.html or no
  song with a sheet. The href passes `drawFiles`' rule (`#` for a scheme or a leading `/`).

- [ ] **Step 1: Write the failing test**

```python
PLAYS = """Array.from(document.querySelectorAll('#songbooks .book-lines > li')).map((li) => {
  const a = li.querySelector('a.book-play');
  return [li.dataset.book, a ? a.getAttribute('href') : null, a ? a.getAttribute('aria-label') : null]; })"""


@SIZES
def test_each_songbook_has_a_play_that_opens_its_phone_page_at_its_first_song(serve, conn, cfg, library, tmp_path,
                                                                            size):
    from urllib.parse import quote

    toml = songbooks_file(cfg.library_dir)
    make_songbook(toml, "Hysteria first", ["Muse - Hysteria", "Radiohead - Creep"])  # its first song has no sheet
    make_songbook(toml, "Nothing yet", ["Muse - Hysteria"])
    render_songbooks(conn, cfg, Overrides(), runner=FakeChordPro())
    conn.commit()
    page_of = {b.name: f"_songbooks/{quote(b.folder, safe='')}/songbook.html" for b in books_toml(cfg)}
    url, _ = serve(Fake(cfg))
    with opened(tmp_path, *size) as page:
        page.open(url + "#tab=songbooks")
        assert page.js(PLAYS) == [
            ["Campfire", page_of["Campfire"] + "#song-1", "Play Campfire from Creep"],
            ["Road trip", page_of["Road trip"] + "#song-1", "Play Road trip from De Música Ligera"],
            ["Hysteria first", page_of["Hysteria first"] + "#song-2", "Play Hysteria first from Creep"],
            ["Nothing yet", None, None]]
        if size[0] < 500:  # a thumb's target
            box = page.js("(() => { const r = document.querySelector('#songbooks a.book-play').getBoundingClientRect();"
                          " return [r.width, r.height]; })()")
            assert min(box) >= 43.5, box
        radii = page.js("[...new Set([...document.querySelectorAll('#songbooks *')].filter((n) => n.checkVisibility())"
                        ".map((n) => getComputedStyle(n).borderTopLeftRadius))]")
        assert set(radii) <= {"0px", "4px", "8px", "12px", "999px"}, radii  # the four radii ("Where the lanes meet" 4)
        page.click('#songbooks li[data-book="Campfire"] a.book-play')
        assert page.wait("location.pathname === '/_songbooks/Campfire/songbook.html'")
        assert page.wait("document.documentElement.dataset.view === 'song'")
        assert page.js("document.querySelector('section.song:not([hidden])').dataset.n") == "1"


def test_the_file_pages_play_opens_the_songbook_viewer_too(conn, cfg, library, tmp_path):
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW))
    with opened(tmp_path) as page:
        page.open(path.as_uri() + "#tab=songbooks")
        page.click('#songbooks li[data-book="Road trip"] a.book-play')
        assert page.wait("location.href.endsWith('songbook.html#song-1')")
        assert page.wait("document.documentElement.dataset.view === 'song'")
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_songbooks_tab.py -k play`: no
  `a.book-play` (`[…, null, null]` for each).
- [ ] **Step 3: Implement** — `drawList`: `li.replaceChildren(go, ...(play ? [play] : []))`, the focus kept on the Play
  when it had it (as `go`'s is). songbooks.css: `.book-lines > li { display: flex; align-items: center; }`,
  `.book-lines > li > .book-line { flex: 1 1 auto; min-width: 0; }`, `.book-play { flex: none; gap: 6px; margin:
  0 8px; }`, its glyph 14 px in the accent; the current line's tint and edge on the `li`
  (`.book-lines > li:has(> .book-line[aria-current="true"])`) so the Play sits on it; under `(pointer: coarse)`
  `.book-play { min-width: 44px; min-height: 44px; }`. The radii to the tokens above; songbooks.js's line 89 passes
  `history.state`; the one-artist view's leftovers deleted if 1b.1 has merged (else 4.3's); the docs above.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_songbooks_tab.py
  -k "lists_each or touch_contrast"` (the lines' meta and the tab's targets and contrast).
- [ ] **Step 5: Commit** — corpus regenerated (`CARACOLE_CORPUS=write nix develop -c pytest -q -n 0
  tests/test_conformance_*.py`, twice); `git add src/caracole/library_assets/songbooks.js
  src/caracole/library_assets/songbooks.css tests/test_songbooks_tab.py
  tests/conformance/vectors/web/library_page.json docs/usage.md AGENTS.md`; `git commit -m "feat(songbooks): Play on
  each songbook, its phone page at its first song"`.

#### Task 4.2: The same Play in the opened songbook's head

On a phone the opened songbook takes the screen, its list hidden: the Play comes with it.

**Files:**
- Modify: `src/caracole/library_assets/songbooks.js` (`draw`: the head's Play, from `playOf(b)`)
- Modify: `src/caracole/library_assets/songbooks.css` (`.book-head .book-play`)
- Modify: `docs/usage.md` ("The Songbooks tab": "…and so has the songbook opened"; none before caracole has made it,
  or while none of its songs has a sheet), `AGENTS.md` ("The Songbooks tab": the Play in its head too)
- Test: `tests/test_songbooks_tab.py`

**Interfaces:**
- Consumes: 4.1's `playOf(b)`.
- Produces: `.book-head > a.book-play` after the `h2`'s meta, replaced on each draw (a rename's, a move's), none
  where `playOf` gives none; `.book-files` unchanged (its links stay PDF, Phone page, ChordPro).

- [ ] **Step 1: Write the failing test**

```python
@SIZES
def test_the_opened_songbook_has_its_play_in_its_head(serve, cfg, library, tmp_path, size):
    url, _ = serve(Fake(cfg))
    with opened(tmp_path, *size) as page:
        page.open(url + CAMPFIRE)
        assert page.js("document.querySelector('#songbooks .book-head a.book-play').getAttribute('href')") == \
            "_songbooks/Campfire/songbook.html#song-1"
        assert page.js(f"{SHOWN}('#songbooks .book-head a.book-play')")
        assert page.js("Array.from(document.querySelectorAll('#songbooks .book-files a')).map((a) => a.textContent)") \
            == ["PDF", "Phone page", "ChordPro"]
```

- [ ] **Step 2: Run it and see it fail** — `nix develop -c pytest -q tests/test_songbooks_tab.py -k in_its_head`:
  `querySelector(...)` is null.
- [ ] **Step 3: Implement** — in `draw`, after `showTitle`: drop the head's `.book-play`, append `playOf(b)` when there
  is one. `.book-head .book-play { margin-left: auto; align-self: center; }`. The docs above.
- [ ] **Step 4: Run it and see it pass** — the same command, then `nix develop -c pytest -q tests/test_songbooks_tab.py`.
- [ ] **Step 5: Commit** — corpus regenerated; `git add src/caracole/library_assets/songbooks.js
  src/caracole/library_assets/songbooks.css tests/test_songbooks_tab.py
  tests/conformance/vectors/web/library_page.json docs/usage.md AGENTS.md`; `git commit -m "feat(songbooks): the opened
  songbook's Play in its head"`.

#### Task 4.3: Merge lane 4

- [ ] **Step 1: Docs, checked** (written by 4.1 and 4.2) — docs/usage.md, "The Songbooks tab": "Each songbook's line
  has **Play**, and so has the songbook opened: its phone page (`songbook.html`) at its first song with a sheet
  (`#song-2` when the first has none yet); none before caracole has made it, or while none of its songs has a sheet."
  AGENTS.md, "The Songbooks tab": "each songbook's Play, on its line and in its head (songbooks.js `playOf`): its
  `songbook.html` at `#song-N`, N the first set entry with a sheet (`set[].href`), as book.js opens a song". A gap
  goes into a `docs:` commit here.
- [ ] **Step 2: Rebase** onto `main`; if Task 1b.1 merged after 4.1 was written, delete songbooks.css's one-artist
  view leftovers here ("Where the lanes meet" 10: `.selecting [data-picker] .filter-mark`, `.selecting [data-picker]
  .artist-only` and the dead `by` column of `.selecting .line` at ≥ 720 px), corpus regenerated, commit
  `fix(songbooks): no rules left for the funnel the list no longer has`.
- [ ] **Step 3: The gates** — as 3a.4's step 2: `nix develop -c pytest -q` (whole suite); `CARACOLE_CORPUS=write nix
  develop -c pytest -q -n 0 tests/test_conformance_*.py` twice, then `nix develop -c pytest -q -n 0
  tests/test_conformance_*.py` passes in check mode; `nix develop ./android -c gradle -p android test`
  (SongbooksOnDeviceTest, on the device step if the owner runs it, still clicks `.book-files
  a[href$="songbook.html"]`, which this lane leaves); `CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0
  tests/test_android_e2e.py` (the corpus moved); `nix flake check`.
- [ ] **Step 4: Look at it** — the tab on the laptop and on the phone's app (its Songbooks tab's data is
  `SongbookSection.kt`'s, the same shape): Play, then Back to the tab.
- [ ] **Step 5: The radius skip list** — only if 1f, lane 2 and 3b have all merged, this merge is the last of 1f, lane
  2, 3b and lane 4: `tests/test_page_calm.py`'s `OTHER_LANES = ()` and `test_the_library_page_has_four_corner_radii`
  passes with it (commit `test(library): the four radii across the whole page, no lane left out`); else the list
  stays, for the last of them to remove.
- [ ] **Step 6: The README's screenshots** — only if lanes 1 (1f), 2 and 3 (3b) have all merged (lane 4 the last of
  the four): retake them: `nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python
  docs/screenshots/make.py`; for each picture, `git show HEAD:docs/screenshots/<name>.png > old.png` (outside the
  repository) and `compare -metric AE old.png docs/screenshots/<name>.png null:` (ImageMagick, through
  `omnibin-shell` if it isn't on PATH): `git restore` those with 0 differing pixels, keep the others; commit `docs: the
  README's screenshots of the redesigned page`. Else they wait for the last lane.
- [ ] **Step 7: Merge** — `git checkout main && git merge --no-ff feat/songbooks-play`, then push main:
  `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin main`.

---

### Cross-lane points, for the plan's owner to settle with lane 1's planner

1. **The seam both ways (3a.1)**, settled by "Where the lanes meet" 3. card.css keeps the opened-line box
   (`.line:not(.hit):has(> .line-more…)`, its `+ .line`, `.line:not(.hit) > .line-panel`), which 3b.4 keys to
   `.line-panel.song-card` and `:not(.selected)` for lane 1d's pane; library.css's `.foot` and rows.css's `.line-panel
   .foot` move into card.css, besides the `.play` rules and filter.css's lit rule; the lit rule must cover the chip's
   glyph and site word. Lane 1 should not re-add `.play`/`.foot` rules (test_library_assets.py fails if it does), but
   for its placement rules (a selector ending `.line-title > .line-plays`, rows.css and library.css) and its
   `#card-pane …` rules (library.css).
2. **Room for chips on a laptop's line** (lane 1b/1d), settled by "Where the lanes meet" 12: the chips are 100–150 px
   each; Task 1d.6 sizes the title's column and lets `.line-title > .line-plays` wrap below the title.
3. **The history contract** (3b.5): lane 1's pushes never copy `caracoleMenu`, and its popstate handlers act on their
   own members only; the menu's entry is `{ caracoleMenu: n }`, with `search: n + 1` in search mode, never a spread of
   `history.state` ("Where the lanes meet" 1 and 2).
4. **Four radii** (3b.6), settled by "Where the lanes meet" 4: this plan uses 4, 8, 12 and 999 px in the card and the
   play buttons, written as 1f's tokens with those values as fallbacks.
5. **Phone line height** (lane 1b): a play tile is 48 px tall, so a line that holds one is at least 48 px plus its
   padding.
