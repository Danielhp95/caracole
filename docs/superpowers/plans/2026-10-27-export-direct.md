# Export download and card-to-tooltip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chord's card opens its notes tooltip; Export PDF downloads at once (a pop-up offers Make it mine
when the version differs), and the /export page is gone.

**Architecture:** render.py gains an in-process render of a version to bytes (sharing `render_version`'s
steps); web/export_routes.py becomes `GET /export.pdf`; viewer/page.py and viewer.js gain the card's button and
the pop-up; `viewer_csp` allows downloads.

**Spec:** `docs/superpowers/specs/2026-10-27-export-direct-design.md`.

## Global Constraints

- AGENTS.md's rules; test first; never a live request; `nix develop -c pytest …`; whole suite before the last
  commit; `feat(viewer): …` / `feat(web): …`; no AI attribution.
- Copy: "Circle & keyboard"; "Make this your version of <song>?"; "Its PDF, its viewer and your songbooks will
  start there."; "Download and make it mine"; "Just download"; "Cancel".
- The download writes nothing into the library and takes no lock; `mine=1` queues the existing
  `caracole render --song --version --mine` job.

## Review Focus

- A version whose only change is a reading setting (text size, scroll speed, necks, pinyin, sound): no pop-up.
- The auto sheet's viewer beside a human sheet, a kept version's page: no Export row (as today), and the route
  refuses them.
- chordpro failing or a CJK font missing: an error answer naming why, never a broken PDF.
- Two downloads at once (two tabs): each renders in its own private folder.
- A songbook page: no Export row (as today); the card's Circle & keyboard works there too.

---

### Task 1: The card's Circle & keyboard button

- [ ] Failing tests (browser, the tooltip's test file): `test_the_cards_circle_and_keyboard_opens_the_chords_tip`
  (chords only, no numerals shown: the tooltip opens for that chord, the card closed);
  `test_the_button_hides_where_the_tip_has_nothing_to_draw` (no key); `test_it_follows_the_chord_played_now`
  (an alternative chosen).
- [ ] Implement in viewer/page.py (`#card` markup), viewer.js (`openCard`, `showTip` callable for a chord element
  with no numeral shown, `placeTip` anchoring to the chord's name). PASS. Commit.

### Task 2: `GET /export.pdf`

- [ ] Failing tests (tests/test_web_export.py or the export routes' test file, rewritten): the PDF answered as an
  attachment with its name, nothing written in the library or kv, no lock taken; refusals as before; `mine=1`
  queues the `--mine` job under the song's key and answers the PDF; no token needed; the host check still
  refuses another host; `GET /export` and `POST /export` are 404.
- [ ] Implement (render.py: a function rendering a version to bytes in a private folder, shared with
  `render_version`; web/export_routes.py). PASS. Commit.

### Task 3: The viewer's Export row and the pop-up; docs

- [ ] Failing tests (browser): `test_export_downloads_the_own_version_at_once` (the link's href is
  `/export.pdf?…`, no dialog); `test_a_changed_version_asks_before_downloading` (capo moved: the dialog, its
  three buttons, their hrefs, Escape closes it); `test_reading_settings_are_no_change`; `test_viewer_csp_allows_downloads`.
- [ ] Implement. Update docs/usage.md and AGENTS.md (the exception, the GET pages rule). PASS.
- [ ] Screenshots of the pop-up (light, dark, 390 px) under
  `/tmp/nix-shell.wBNcon/claude-1000/-home-dani-Projects-caracole/4b56bdb2-8fb1-410a-9ee6-52d74abce9f3/scratchpad/shots/export/`.
- [ ] `nix develop -c pytest -q` → PASS. Commit.
