# Sheet versions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** keep a song's three best Ultimate Guitar chords versions beside its sheet, each with a viewer page, let
the owner step through them, list every version UG has, and make any of them "the one" the title opens.

**Architecture:** one new module, `sheet_versions.py`, owns the names and the list (`SheetVersion`), read by
every other part. The fetch step writes the two runner-up texts it already downloads as flat files beside the
sheet; the render step gives each a viewer page; the viewer, caracole serve and the library page show and switch
them; a new `caracole versions` command lists, keeps, chooses and clears. Five lanes run in parallel against the
interfaces below, each merging lane D's branch once its Task D1 is committed.

**Tech Stack:** Python 3.14, SQLite (no schema change), viewer.js / library.js (no network, hashed inline
scripts), pytest with pytest-xdist and Chromium.

**Spec:** `docs/superpowers/specs/2026-10-21-sheet-versions-design.md` (approved 2026-10-21).

## Global Constraints

- With no choice of yours the title opens `rank.rank_sheets` order's first (complete first, then `bayes`, m =
  `RankPolicy.prior_votes` 10); complete = coverage ≥ `RankPolicy.coverage_threshold` (0.8).
- Kept: the `RankPolicy.scored_sheets` (3) versions the fetch already scores, plus a version you chose or kept.
  No extra request in the nightly run.
- The chosen version stays `sheet.txt`, `sheet.json`, `sheet.html`, `sheet.pdf`: every link, the PDF and
  songbooks unchanged.
- Version files are flat in the song folder, never a subfolder (removal treats a subfolder as not caracole's):
  `version-<tab_id>.txt`, `version-<tab_id>.json`, `version-<tab_id>.html`. No PDF per version.
- Kept version files are recorded in `files` (`library.keep_file`, `kept_rank` 2, 3, …); viewer pages through
  `render._note_written`. Deleted only by name, only what caracole wrote (`library.drop_file`,
  `render._forget_written`).
- A version fetched from the list is an interactive lookup: `make_client(..., interactive=True)`, its budget and
  hourly cap; never in the nightly run's budget.
- Errors are never misses: a version page that won't parse is not kept and waits.
- Served pages keep their CSP and `sandbox allow-scripts`; a sandboxed viewer reaches a form only through a GET
  page of caracole serve (as `exportLink` does). file:// pages show the command to copy.
- Tests first; `nix develop -c pytest -q`; browser tests `@in_chromium`; docs/usage.md and AGENTS.md in step in
  the same commit; conventional commits; no AI attribution.

## Review Focus

1. A version whose text is byte-identical to the sheet (two UG tabs, same text): `keep_file` refuses a second
   name with one sha256. Expect: it is listed as kept with `page` = "sheet.html", no error, no duplicate file.
   Test in Task D2.
2. A pin to a version outside the top 3, then the pin cleared: the pinned file must leave the kept set and its
   files be deleted, and sheet.txt go back to caracole's pick. Test in Task D3.
3. A song whose sheet is LaCuerda's or auto: its UG versions still list and switch; "the one" is the LaCuerda
   or auto sheet and is named so. Test in Task D1 (list) and Task V1 (label).
4. A song removed with version files: every `version-*` file goes, nothing else. Test in Task R1.
5. A version that left UG (`gone`): listed as gone, not openable from the list, its kept files kept until the
   next fetch drops it. Test in Task D2.

---

## Lane D: the kept versions (starts now; other lanes merge it after D1)

### Task D1: sheet_versions.py

**Files:** create `src/caracole/sheet_versions.py`; test `tests/test_sheet_versions.py`.

**Interfaces — produces:**
```python
PREFIX = "version-"
def version_names(tab_id: str) -> tuple[str, str, str]      # ("version-<tab>.txt", ".json", ".html")
def tab_of(name: str) -> str | None                          # the tab id of a version file name, else None
@dataclass(frozen=True)
class SheetVersion:
    version_id: int; tab_id: str; number: int | None         # UG's version number ("Ver 3")
    rating: float | None; votes: int | None; label: str | None
    note: str | None          # first 200 chars of raw["version_description"], whitespace folded
    coverage: float | None; complete: bool | None            # None: not scored
    rank: int                 # 1-based, rank_sheets order (scored first, then the rest by bayes)
    kept: bool; chosen: bool; gone: bool
    page: str | None          # "sheet.html" for the chosen one, version_names(tab)[2] when kept, else None
    url: str                  # its UG page
def song_sheet_versions(conn, song_id: int, policy: RankPolicy, *, chosen_tab: str | None,
                        kept_tabs: Collection[str]) -> list[SheetVersion]
def as_data(versions: Sequence[SheetVersion], total: int) -> dict   # the JSON both pages read, below
```
`as_data` returns `{"total": int, "list": [{"tab", "number", "rating", "votes", "label", "note", "rank",
"kept", "chosen", "gone", "page", "url"}]}`; `total` is UG's count of chords versions (rows, gone included).

- [ ] **Step 1: failing tests**: `test_versions_list_in_rank_order_complete_first` (three scored, one
  incomplete with the best rating comes after the complete ones; unscored ones follow by `bayes`);
  `test_the_chosen_and_kept_pages_are_named` (chosen → "sheet.html", kept → "version-<tab>.html", others None);
  `test_the_tabbers_note_is_folded_and_cut` (raw `version_description` "the version that oasis play\n on
  Wembley 2008" → "the version that oasis play on Wembley 2008"); `test_a_gone_version_lists_as_gone`;
  `test_names_round_trip` (`tab_of(version_names("39144")[1]) == "39144"`, `tab_of("sheet.txt") is None`).
- [ ] **Step 2: run, FAIL. Step 3: implement** from `versions.song_versions(..., kinds=("chords",),
  include_gone=True)` and `rank.Candidate` / `rank_sheets`. **Step 4: PASS; the whole suite.**
- [ ] **Step 5: commit** `feat(fetch): sheet_versions.py, a song's chords versions in rank order`.

### Task D2: keep the runners-up

**Files:** modify `src/caracole/ug/fetch.py` (`_sheet_slot`, `SongFetchOutcome`, `rescore_kept_sheets`,
`_send_back_lost`); test `tests/test_fetch_versions.py`.

**Interfaces — produces:** `SongFetchOutcome.kept_versions: tuple[str, ...]` (tab ids kept beside the sheet,
rank order); `_keep_version(run, version_id, page) -> bool` writing both names of `version_names` with
`kept_rank` 2, 3, …

- [ ] **Step 1: failing tests** (fake UG behind a real `PoliteClient`, as test_fetch.py): Wonderwall-like
  fixture with four chords versions: the run keeps sheet.txt plus `version-<b>.txt/.json` and
  `version-<c>.txt/.json`, no request more than today's (count the transport's requests); the 4th is not
  kept; next run with new votes reorders: the version leaving the set has its files deleted, the one entering is
  written (only from pages scored that run, never an extra request); Review Focus 1 and 5; a version page that
  won't parse is not kept and is no miss.
- [ ] **Step 2–4:** run FAIL, implement (the `pages` dict `_sheet_slot` already holds), PASS, whole suite.
- [ ] **Step 5: commit** `feat(fetch): keep the two runners-up of a song's sheet beside it`.

### Task D3: caracole versions

**Files:** create `src/caracole/commands/versions.py` (register only; logic in `src/caracole/versions_cmd.py`,
heavy imports inside); modify `src/caracole/overrides.py` (add `remove_pin`), `src/caracole/commands/get.py`
(the `ug` stage's line); test `tests/test_commands_versions.py`, `tests/test_overrides.py`.

**Interfaces — produces (the CLI the web routes and the viewer's copied commands run):**
- `caracole versions SONG` prints each version: `Ver 3 of 13 · 4.86★ (408) · kept · the one · <note>`.
- `caracole versions SONG --keep TAB` fetches one tab now at the lookup pace (one tab page), keeps it as a
  version (not chosen), renders its page. `--progress` as get's.
- `caracole versions SONG --choose TAB` = `caracole get` with `--tab TAB` (pins it; it becomes the sheet).
- `caracole versions SONG --clear` removes the song's `[pin]` (`overrides.remove_pin(path, display) -> bool`,
  matching the song as `add_version` does) and looks the song up again, so caracole's pick is the sheet.
- get's `ug` stage line adds `· kept beside it: tab B, tab C`.

- [ ] **Steps:** failing tests for each form (listing text; `--keep` takes the lock, one request, a spent
  budget exits 0 and keeps nothing; `--choose` writes `[pin]`; `--clear` keeps comments in overrides.toml and
  Review Focus 2), FAIL, implement, PASS, whole suite; registering imports no httpx
  (`test_registering_the_command…` as the others). Commit `feat(commands): caracole versions`.

## Lane R: version pages (merges D after D1)

### Task R1: render each kept version

**Files:** modify `src/caracole/render.py` (`_render_song`, a `_render_versions(conn, cfg, song, kept)`),
`src/caracole/removal.py` if `_caracoles` misses them; test `tests/test_render_versions.py`.

**Interfaces — consumes:** `version_names`, `tab_of`, `song_sheet_versions`, `as_data`. **Produces:** every
viewer page (sheet.html and each `version-<tab>.html`) carries the `as_data(...)` dict as data key `versions`
(`json_block("song", data)`'s `versions`); `build_viewer(..., versions: dict | None = None)`.

- [ ] **Steps:** failing tests: a song with two kept versions gets `version-<b>.html` and `version-<c>.html`
  (chordpro-free: `build_viewer` only), recorded by `_note_written`, rewritten only when bytes change; their
  data's `versions.list` marks the page's own entry; a version leaving the set has its page deleted while it
  still holds what caracole wrote; Review Focus 4 (`caracole remove` deletes every version file); no PDF per
  version. FAIL, implement, PASS, whole suite. Commit `feat(render): a viewer page for each kept version`.

## Lane V: the switcher in the viewer (data shape above; fixtures until R merges)

### Task V1: the switcher and the list

**Files:** modify `src/caracole/viewer/page.py` (`_SHEET_CONTROLS`: a `#versions` row in the bar or above the
sheet, a `#version-list` panel), `src/caracole/viewer/viewer.js`, `viewer.css`; test
`tests/test_viewer_versions.py`.

**Interfaces — consumes:** data key `versions` (above). **Produces:** the viewer's "Make this the one" and
"Keep it" links: served, `/versions?sheet=<path>&tab=<tab>&do=choose|keep` (Lane W's GET page); file://, the
`caracole versions "<display>" --choose|--keep <tab>` command with Copy, as `exportLink` does.

- [ ] **Steps:** failing Chromium tests: the line reads `Ver 3 of 13 · 4.86★ (408) · the one` (Review Focus
  3: "the one: LaCuerda's sheet" when the chosen page isn't UG's); ‹ › open the previous/next kept page in rank
  order (same tab), disabled at the ends; the list panel shows every version (rating, votes, kept, note) and
  opens kept ones, offers Keep it for the others (served) or the command (file://); a gone one isn't a link;
  no `versions` key → no switcher; songbook.html unaffected; 390 px no sideways scroll, 44 px targets. FAIL,
  implement, PASS, whole suite. Commit `feat(viewer): step through a song's versions, and list them all`.

## Lane W: caracole serve (CLI above)

### Task W1: the versions page and its posts

**Files:** create `src/caracole/web/versions_routes.py`; modify `src/caracole/web/app.py` (`written_pages`:
names matching `version-<tab>.html` served as viewers, `tab_of`), `src/caracole/web/export_routes.py`
(exports from a version page); test `tests/test_web_versions.py`.

**Interfaces — consumes:** the `caracole versions` CLI, `tab_of`. **Produces:** `GET /versions?sheet=&tab=&do=`
(a page with the one form), `POST /versions/choose`, `POST /versions/keep`, `POST /versions/clear`, each a job
running `caracole versions …` (`app.submit`, song key as a lookup's so it joins), refusals as `pages.Refused`.

- [ ] **Steps:** failing tests: a version page is served only while it holds what caracole wrote, with the
  viewer's CSP and sandbox; each POST needs the token and same origin and queues the right command; Clear only
  when the song has a pin; an export from a version page works. FAIL, implement, PASS, whole suite. Commit
  `feat(web): choose, keep and clear a song's version`.

## Lane L: the library page (data shape above)

### Task L1: kept versions under a song's ⋯

**Files:** modify `src/caracole/library_page.py` (`_song`: `versions` from `as_data`; `_files`: version
pages), `src/caracole/library_assets/library.js`; test `tests/test_library_page.py`.

- [ ] **Steps:** failing tests: a song's ⋯ has "Sheet versions" listing each kept one (rating, votes, "the
  one"), each linking its page; lane E's PDF exports heading becomes "PDF exports" (update
  test_library_page.py:1689); the title still opens sheet.html. FAIL, implement, PASS, whole suite. Commit
  `feat(library): a song's kept versions under its ⋯`.

## Order and merging

D1 first (short); R, V, W, L start at once against the interfaces and merge `sheet-d` once D1 is committed. D2
and D3 follow D1 in lane D. Merge order into caracole-v1: D, R, W, V, L; each after one review round and the
whole suite. Lanes running beside these touch viewer.js (neck, guitar button, theory), library.js (search names,
nav) and web/ (page icon): merge caracole-v1 into each before review.
