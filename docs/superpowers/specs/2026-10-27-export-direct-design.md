# Export PDF downloads at once; a chord's card reaches its notes

Two changes to the sheet viewer, the owner's, 2026-10-27.

## 1. A chord's card opens the notes tooltip

Tapping a chord's name opens its card (shapes, alternatives, its notes and solo scale). The numeral's tooltip
(the twelve-note circle or the keyboard, with Hear it: docs/superpowers/specs/2026-10-27-numeral-tip-design.md)
was reachable only by hovering or tapping a numeral, so not at all with the chord names alone. **The card gets a
button, "Circle & keyboard"**, that closes the card and opens that chord's tooltip, anchored at the chord (its
numeral when shown, else its name), in the view the reader keeps (`caracole-viewer-tipview`). Shown wherever the
tooltip has something to draw for the chord (the key known and the chord's notes in the tables); hidden
otherwise. The tooltip shows the chord the card shows: the one played now (an alternative chosen, its own).

## 2. Export PDF downloads; no /export page

Today Export PDF (the viewer's settings, served) goes to caracole serve's `/export` page, whose form queues
`caracole render --song --version` (the PDF written into the song's folder, listed under the card's PDF
exports) and, as a second button, Make this my version (`--mine`: overrides.toml's `[version]`, then the song
rendered in it). The owner wants the PDF downloaded at once, no page, and that page gone.

- **`GET /export.pdf?sheet=<viewer's library path>&<the version, as the viewer's address holds it>`**
  (web/export_routes.py, rewritten): renders that version of the song's sheet now, in-process, in a private
  0700 folder under the cache (render.py's `private_dir`, `run_chordpro`, the version applied as
  `render_version` applies it), and answers the PDF as an attachment named as `download_names` names a kept file
  with the version in it ("John Newton - Amazing Grace (D, capo 2).pdf"). **Nothing is written into the library
  and no kv is recorded** ("Just download", the owner's): no lock, no queue, no PDF exports entry. Refused as the
  export page refused (a sheet that is no viewer caracole wrote for a song, the auto sheet kept beside a human one,
  a kept version's page, an address that can't be read): an error page, as `Refused` is answered.
- **`&mine=1`** also queues today's `caracole render --song … --version … --mine` job (it writes `[version]`
  under caracole's lock and renders the song in it), under the song's key, as the export page's form did, and
  still answers the PDF. **No form token and no cross-origin check: a plain link, the owner's explicit choice**
  (a website could change a song's saved version with a crafted link; nothing is lost, and Reset or another
  version undoes it). The host-name check (DNS rebinding) still applies. AGENTS.md records this exception, as it
  does YouTube's.
- **The viewer**: the settings' Export PDF row, served, is a link to `/export.pdf?…`. Pressed while the page plays
  the song's own version (the one it opens in: the key, mode, capo, shapes and swaps it started with, the reading
  settings aside), it downloads at once. Pressed while the version differs in any way, **a pop-up** in the
  viewer (a dialog, its focus kept inside, Escape and ✕ close it) asks: "Make this your version of <song>?",
  the version in words ("D Dorian, capo 2"), and a line on what that does ("Its PDF, its viewer and your
  songbooks will start there."), with **Download and make it mine** (the link with `&mine=1`, primary), **Just
  download** (the link), and Cancel. The page stays where it is (the download needs the viewer's sandbox to allow
  downloads: `viewer_csp` adds `allow-downloads`; nothing else in the sandbox changes).
- From a file (no server), the row stays as today: the command and Copy.
- **Removed**: `GET /export` and `POST /export`, their page and its tests; the export page's "Keep it in this key"
  (an own version kept as a move: the pop-up's Download and make it mine writes it by its key anyway). The CLI's
  `caracole render --version` (an export written beside the sheet) stays, as do the exports already kept, which
  the library card lists.

## Constraints

- AGENTS.md: the pages' rules (no innerHTML; CSP; createElement), the viewer rules (BUILD_FILES; viewer.js no
  music theory), One caracole at a time (the download takes no lock and writes nothing in the library; `mine`
  runs as a queued job), the library is synced (nothing written there by the download), politeness (no request
  to any site).
- docs/usage.md (the viewer's Export PDF, Make this my version; the routes), AGENTS.md (the exception; the pages
  rule that named `/export` among the GET pages a sandboxed viewer reaches a form through).

## Left to the builder

The pop-up's look (the viewer's dialogs'), the attachment's name in an edge case, how the in-process render
shares code with `render_version` without copying it.
