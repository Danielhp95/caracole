# Syncing, made one clear flow, with export and import (design)

Date: 2026-11-03. Status: design, agreed with the owner in conversation, reviewed by a builder; built
(2026-11-10, the plan's lanes sync-rules to sync-app): AGENTS.md's peer_file.py, sync_routes.py,
sync_file_routes.py and "Syncing on the phone" sections say how, android/README.md's "Sync from the phone" and
docs/usage.md's "The Sync tab" how it is used.
Mockups the owner settled on: [phone.html](2026-11-03-sync-redesign/phone.html) and
[laptop.html](2026-11-03-sync-redesign/laptop.html) (open them in a browser; they're throwaway HTML, not the
pages' code).

## Why

After milestones 1-3 of the Android port, the owner synced their phone for the first time and found four ways in, each
a different flow:

1. the app's Settings: Import indexes, From the computer or From a file;
2. Settings: Sync now, after typing the address (it copies the computer's pages and nothing else);
3. the library page's ⋮ menu: Sync now (the same page copy);
4. the ⋮ menu: Sync with the computer, which opens the Sync tab (the full two-way sync: Compare, every difference
   with Here, There or Skip, then Sync).

Their words: "it's not going to be clear for a new user what is the correct way, or if you're missing out." They want
one way to sync, the same wherever it starts, that does everything and asks only what it must; a summary that shows
what happened at a glance, "more visual than textual while keeping textual information"; and the same on the laptop.
They also want to export a library to a file (to share with another caracole user, to keep, to back up) and import
one, "as if they are syncing with a computer that had that information".

## Goals

- One sync, one entry point per device, one flow: what to sync, the conflicts if any, what it did.
- A sync takes and gives every change made on one side by itself, and stops only for a conflict.
- The summary is a picture first (the two sides, an arrow per kind of change with its count), with the details a tap
  away.
- Export and import a library as a file, on the phone and on the laptop; an import is a sync with the file.
- The phone and the laptop run the same code for all of it (the owner: "the more shared code the better").

## Non-goals

- The computer never starts a sync with the phone (the phone runs no server the network reaches). Unchanged.
- No new sync rules but one: what a unit is, how two sides compare against their base, and how a unit is taken stay
  as peer_sync.py and the Kotlin sync engine have them. The one addition is an import's remembered answer (below).
- The library page's song lines and cards (a separate design, in progress) and sharing a music app's link to the app
  (not designed yet) are not part of this.
- `caracole peer diff`, `pull` and `sync` on the command line keep working; the CLI gains export and import.

## Anti-goals (it fails if)

- A sync changes anything the owner was asked about before they answer.
- Two buttons on the same device are called "Sync" and do different things.
- The phone's and the laptop's flows drift apart, because they are two implementations.
- An export or import sends anything to a music site, or a page loads anything from the network.

## Constraints

- The pages' rules hold (AGENTS.md, "The pages caracole writes and serves"): no network, every inline script and
  style allowed by its hash, `createElement` and `textContent`, never `innerHTML`; library_assets/ inlined byte for
  byte, the phone serving the same bytes (`copyLibraryAssets`); a change to library_assets regenerates the
  conformance corpus in the same commit.
- Every write passes the cross-origin check and carries the form token; a `bytes` route declares its limit.
- caracole serve never takes caracole's lock and writes only its own few files (AGENTS.md, "`serve` never takes
  it"). An import is a queued `caracole` command; the export is a read, as `GET /api/peer/index`'s is. The new things
  serve writes (an export's temporary file, an import's staging folder) are added to that list in AGENTS.md, as the
  push's staging folder was.
- On the phone, the local server's launch cookie and security rules hold; the WebView gives the page no JavaScript
  bridge.
- A removed song stays removed, `upsert_song` stays the one way a song is added, schema changes go through db.py, and
  the library is synced (Syncthing): an import takes its units exactly as a pull or a push does.

## Approaches considered

1. **One flow in the library page, for both devices.** *Chosen by the owner.* The sync sheet, the conflict cards,
   the summary, the export and the import are written once in library_assets (sync.js and its templates and css),
   which the laptop's caracole serve and the phone's local server already both serve. The phone's native top-bar
   button opens that sheet; files use the web's own means, a download and a file input, which Android's WebView
   hands to the share sheet and the file picker. One implementation, tested once in Chromium and again on the
   emulator; the cost is a little native wiring for the download and the file chooser.
2. **Native screens on the phone, the page on the laptop.** Feels more native on the phone and reaches the share
   sheet and picker directly, but every screen exists twice and the two drift. Rejected: it works against the
   owner's "the more shared code the better" and the anti-goal of drifting flows.
3. **For the file**, a SQLite file (like `caracole index export`) holding everything as tables was weighed against
   a recording of what a sync reads from the other side. The recording was chosen (builder's call, confirmed by the
   owner's yes to the approach): it lets an import run the sync code unchanged, as a source the take reads from.

## What was decided

### Where syncing lives

**Phone.** One sync button in the app's top bar, on every page (the circular-arrows icon, left of ⋮). It replaces
Settings' Sync now, Settings' Import indexes → From the computer, and the ⋮ menu's Sync now and Sync with the
computer, which all go. The phone's library page has no Sync tab any more; its tabs stay Library, Songbooks, Sites
(the narrow bar has no room to split them, and Sync moved to the button).

Settings keeps the computer's address with its **Test** button (typed once, remembered), and gains **Export** and
**Import a file**. **Sync on Wi-Fi by itself** stays, and becomes this same sync, unattended (the owner's choice):
every 6 hours on an unmetered network, when the computer answers, with the three parts ticked, it takes and gives
every one-sided change and leaves each conflict for the next sync started by hand, telling the owner in a
notification ("2 songs changed on both sides: tap to choose"). Import indexes → From a file goes: an index file is one kind of import (below). No item text ends
in "…".

**Laptop.** The library page's tab bar splits: **Library** and **Songbooks** on the left; **Sites**, **Requests**
and **Sync** on the right, in that order. The Sync tab holds three panels side by side:

- **Sync with a server**: its address (remembered), a **Test** button beside it, which asks that server and
  changes nothing ("✓ studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26"), the last sync with it
  and a **Sync** button;
- **Export**: this library in one file, to share or to keep;
- **Import a file**: a file a phone or a server exported, synced as if its caracole were here.

### The flow (both devices; the mockups' steps 2-4)

**1. What to sync.** A sheet titled "Sync with <name>", the address and when it last synced, and three checkboxes,
all ticked:

- **Library**: your songs, their sheets and pages, both ways (on the phone, this includes copying the computer's
  pages: the mirror);
- **Songbooks**: your songbooks and their set lists, both ways; a song a songbook lists comes along with it even when
  Library isn't ticked (the owner's rule);
- **Site indexes**: for searching offline; whichever side read a site more recently gives it to the other (the
  phone, which builds no index until milestone 4, only takes). Each line says what's waiting where it is known
  ("newer on the computer: Ultimate Guitar (read today)", "2 changed on the computer").

**Cancel** on the left, **Sync** on the right.

**2. A conflict stops it to ask.** Every change made on one side only is taken or given by itself. A unit changed
differently on both sides since the last sync stops the sync for a card: the song's name, "1 of N", and each side's
version (this device on the left, the other side on the right, each with its icon), showing **how the two differ**
(its own key, capo, sheet version, an override, a songbook's set list: whatever the two documents hold differently).
It does not say which side made which change, nor when: a sync keeps only a fingerprint of what the two agreed on,
neither its contents nor a time (the owner chose this over tracking every change, 2026-11-03; the mockups' "changed
today, 18:40" lines go). Then, centred, **Which version to keep**, and two buttons side by side, named for the sides:
**Phone** and **Computer** from the phone; **This computer** and the server's name from the laptop; **File** when
importing. Under them, a small **Same for the other N** applies that side to every conflict left (builder's call, for
a first sync with many). There is no Skip: Cancel ends the sync with nothing taken or given. Above the card, a
git-status-like row of counts with icons: green ↓ N to take, blue ↑ N to give, orange ⚠ N changed on both; and the
steps as chips (Compared, Your choice, Library, Songbooks, Indexes).

**3. What it did.** "Synced with: **<name>**" (the name in the accent colour, the only bold text), the date and
time as dd/mm/yy, HH:MM. Below it the two sides as icons (phone, computer tower, server, or file; this device always
on the left) and, between them, one section per kind of change, each a coloured arrow pointing the way things went,
with its count, and a chevron that opens it:

- green, songs taken: each "Song – Artist";
- blue, songs given: each "Song – Artist", with why ("added on the phone");
- orange dashed, conflicts, which side was kept: each song with how the kept version differs from the other;
- yellow, songbooks taken or given: each songbook with what changed in it;
- purple, indexes taken or given, with the change in tabs tracked: the net total on the arrow (+12,130 tabs), and per
  site, opened, its count before and after and when it was read. A site can go down ("LaCuerda · −210 tabs": its
  listings no longer name them, so they would not have opened); up in green, down in red.

The sections start closed. **Done** closes it.

### Export and import

**Export** opens a sheet like step 1: "Export this library", the library's name, songs and date, and the three
checkboxes with the size of each (Library · 34 MB, Songbooks · 2 songbooks, Site indexes · 207 MB). Library and
Songbooks start ticked; **Site indexes starts unticked** (its size; the owner agreed). Cancel left, Export right.
On the laptop, the browser downloads `<library name>-dd-mm-yy.caracole`; on the phone, Android's share sheet opens
with the same file (send it, or save it to Files).

**Import a file** picks a file (the browser's file chooser; on the phone, Android's file picker), then opens the
same sheet as a sync: "Sync with a file from **<its library's name>**", when it was exported, the three checkboxes,
any part the file doesn't hold greyed out ("Not in this file"). Then steps 2 and 3 as a sync, with the file in the
other side's place (the file icon, "In the file", **File**), and no arrows going out: a file takes nothing back. To
give one's changes, one exports a file of one's own.

After an import, this side records its agreement with the file's caracole (its id) as after a network sync, so the
next file from it, or a network sync with it, shows only what changed since.

- **A conflict answered "keep mine" in an import is remembered** (the owner's choice): the file can't take the kept
  version, so the agreement records, for that unit, the two versions the owner chose between, and the next import or
  sync with that caracole doesn't ask again while neither side has changed it since. A change on either side after
  that is compared as usual. This is the one change to the sync's rules here; Python and Kotlin make it alike, held by
  the corpus.
- **A file older than the last sync with its caracole is refused** ("Nothing in this file is newer than your sync with
  horde_logbook on 03/11/26"), since taking it would quietly put songs back as they were (builder's call).
- **A library's own export can't be imported into it**, as a sync with oneself is refused today. A Restore that puts a
  library back as its own file had it is a later feature (the owner agreed); until then a backup is `caracole backup`
  on the computer.

The file is a recording of what a sync reads from the other side: its state document, its units' documents and the
kept files they name (each checked by its SHA-256 as a push's are), **the pages caracole made of them** (what
`GET /api/offline` lists: the viewers, version and harmonica pages, songbook pages, PDFs, with their hashes), its site
indexes when ticked (the file `caracole index export` writes, inside it), and a manifest (the caracole and schema that
made it, its id and name, when, which parts). The pages come along because the phone builds none until milestone 5:
without them a song taken from a friend's file would open no sheet. On the phone, a file's pages sit beside the
computer's mirror, each song's pages from the side its unit was taken from (how: the builder's).

**A file holds everything, to share as the owner likes** (the owner's choice, 2026-11-03: "ignore the privacy, share
everything"). That includes what harptabs.com, gametabs.net and AZLyrics gave, which caracole keeps "privately, in
the library" on the owner's terms for those sites; the export is the owner's own act on their own library, and
AGENTS.md records this choice beside those sites' terms. Nothing in the file is ever sent anywhere by caracole. An import reads it as the take reads a peer or a staged push (`peer_sync.UnitSource`), so nothing of the
sync's rules changes. On the command line: `caracole peer export FILE` and `caracole peer import FILE`.

## Left to the builder

- The file's exact layout (a zip of the recorded answers is the expectation; its manifest fields and versioning), how
  big imports reach the server (a streamed `bytes` route with a limit large enough for indexes, staged to
  `state_dir/peer/`), and where the export is made (`cache_dir/peer/`, deleted once sent).
- How the sync job reports each section's data (counts, names, tabs before and after per site) to the page, and how
  the phone counts each site's rows around its merge.
- The native wiring on the phone: the top-bar button opening the page's sheet, the WebView's file chooser and its
  downloads (a FileProvider URI to the share sheet), within the app's existing security rules.
- How the Test buttons phrase what they found, and the copy everywhere else, in caracole's usual plain style.
- Removing what this replaces (the page copy's Sync now, the ⋮ entries, Import indexes, the old Compare screen's
  Here/There/Skip) and the tests that pinned them, with docs/usage.md, android/README.md and AGENTS.md in step.
