# A caracole server on the phone, and syncing two servers

## What the owner wants

On the computer: search for 20 songs, change the chords of some (Make this my version), pick versions. Then, on the
phone: sync, and have those 20 songs with every change. Turn the computer off. On the phone, alone: search the sites,
add songs, fetch lyrics and Guitar Pro tabs, change chords, as on the computer. Later, with the computer on again:
sync, and see what is different between the two (three songs added on the phone, three on the computer, a song whose
chords changed on both), choose for each difference which side to keep, and end with the same library on both.

The phone is a second, independent caracole, not a window on the computer's. Today's Android app (android/) is a
read-only copy of what the computer's `caracole serve` lists at `/api/offline`: with the computer off, it can't
search, add or fetch anything.

## Two parts

1. **caracole running on the phone.** The real caracole (Python), not a rewrite: every feature it has, the same
   code, the same tests. It runs in a Linux userland on Android: nix-on-droid (Nix on aarch64, through proot), where
   the flake's own package builds as it does on the computer, or Termux (Python, Perl for chordpro, SQLite). The
   app opens the phone's own `caracole serve` (`http://127.0.0.1:8737`) when it answers, and the offline copy
   otherwise. What it drops: auto-chords (torch and its models are too heavy for a phone; a song with no human
   sheet waits for the computer's run), and the nightly run (the phone does lookups, as the owner asks for each song;
   the computer keeps the bulk work, so the sites see one caracole's pace, not two).
2. **Syncing two caracoles** (`caracole peer`, and a Sync page in caracole serve; `caracole sync` is taken, by
   wanted.txt's sync): what each library holds,
   compared song by song, the differences shown, the owner choosing a side for each, then each side taking what it
   was chosen to take from the other.

Part 2 is the larger one and the one that matters on any two machines (a laptop and the server too), so it comes
first. Part 1 is packaging and the app's switch between the live server and the offline copy.

## What syncs: units

A library's state is cut into **units**, each compared on its own and taken whole from one side:

| Unit | Its id | What it is |
|---|---|---|
| a song | `song/<identity key>` | its wanted.txt line (artist, title, album, duration, variant), its record's decisions (status, review, the match, its lyrics), its versions (provider, tab, slot, kind, pick, the raw text's hash), its kept files (name and SHA-256: the sheet's text, tabs, Guitar Pro files, harmonica tabs), and every overrides.toml entry about it (`[version]`, `[pin]`, `[transpose]`, `[match]`, `[reject]`, `[ignore]`, `[youtube]`, `[lacuerda]`, `[harptabs]`, `[gametabs]`, `[azlyrics]`, `[harmonica]`) |
| a removal | `removed/<identity key>` | a tombstone: the song `caracole remove` took out, and when |
| a songbook | `songbook/<name key>` | its name and its set list, each song with its setting |
| an artist's alias | `alias/<artist key>` | an `[alias]` entry |
| an artist's page | `artist_url/<artist key>` | an `[artist_url]` entry |
| a blocked tab | `block/<tab id>` | a `[block]` tab id |

A unit's **digest** is the SHA-256 of its canonical JSON. What caracole makes from a unit (PDFs, viewers, `.cho`,
info.json, the library page, songbooks' files) is not in it: a side that takes a song renders it again, so two
caracoles of different versions still agree on what a song *is*. Nor is anything a lookup would find again (a
cooldown, a miss's date, the HTTP cache): those are each side's own.

The site indexes (UG's sitemap index, LaCuerda's listings, …) are not units: they merge as `caracole index merge`
already merges them (index_transfer.py: what was read more recently wins, nothing is lost), both ways, at every sync.

## Comparing: three ways

Each caracole has an id of its own (kv `sync:id`, made at first use). After a sync with a peer, each side keeps the
digest every unit had then (kv `sync:base:<peer id>`): the **base**. Then, for each unit:

| mine vs base | theirs vs base | what the sync proposes |
|---|---|---|
| same | same | nothing |
| changed | same | mine (theirs takes it) |
| same | changed | theirs (I take it) |
| changed | changed, to the same | nothing (both made the same change) |
| changed | changed, differently | **a conflict**: the owner chooses |

"Changed" includes appearing (a song added) and going (a song removed: its `song/` unit goes, its `removed/` unit
appears). With no base yet (the first sync), a unit on one side only is that side's, and a unit on both that differs
is a conflict.

The owner sees every difference, not only conflicts, and may turn any proposal around ("take the computer's chords for
this one after all"). A conflict has no default: the sync applies nothing until each one is chosen, or the owner
chooses a side for all at once ("keep the phone's for every conflict").

## Applying

A side takes a unit from its peer (a pull; both directions are pulls, the one the owner is on asking the other to pull
what it was chosen to take):

- **a song**: its wanted.txt line written (`songs.upsert_song`, the one way a song is added, so a tombstone of it goes),
  its record's decisions, versions and kept files replaced by the peer's (files fetched by name and checked by their
  SHA-256), its overrides.toml entries set through overrides.py's writers (comments and layout kept), then the song
  rendered again and the songbooks it is in made again;
- **a removal**: `caracole remove --yes` of the song, as the owner would;
- **a songbook**: its table in songbooks.toml written through songbook.py's writers, then made again;
- **an alias, an artist page, a blocked tab**: the entry written, or taken out.

Each unit applies under caracole's lock, as a lookup does (`exclusive(..., interactive=True)`), in a savepoint for
its database rows. Then the library page is written again. The database is backed up first (backup.py,
`before-sync`), as `index merge` is. The base moves on only for the units that applied, so a sync cut short is
finished by the next one.

## How the two talk

Over HTTP, between two `caracole serve`s on a network the owner trusts (the LAN, a tailnet), as the Android app talks
to it already:

- `GET /api/peer/state`: this side's id, its caracole version, its library's name, and each unit's digest and label.
  A read, as `/api/offline` is: no lock, no site asked.
- `GET /api/peer/unit?id=…` and its files: what a pull reads (phase 2).
- `GET /api/peer/index`: the site indexes as `caracole index export` writes them (phase 2).
- `POST /peer/pull`: "take these units from that peer", with the form token, as every write is (phase 2).

`caracole peer diff ADDRESS` (phase 1) shows the comparison with no change; `caracole peer sync ADDRESS` (phase 2) shows it,
asks, and applies. caracole serve gets a Sync page in its Requests tab's spirit (phase 3): the peer's address, the
list of differences, a side chosen for each, and Sync.

## Politeness

The phone keeps every rule caracole keeps (http.py, health.py): its lookups at the lookup pace and budget, robots.txt,
blocks honoured. Two caracoles each count their own budgets; the owner uses one at a time, and the phone runs no
nightly run, so the sites see what they see today. A block one side met moves to the other at a sync: health.py's
cooldowns merge, the later end kept (phase 2).

## Phases

1. **The comparison** (this commit): peer_sync.py's units, digests and three-way diff; `GET /api/peer/state`;
   `caracole peer diff ADDRESS`. Nothing written but the server's id.
2. **Applying**: the unit reads, pulls, the base kept, `caracole peer sync ADDRESS`, index merge both ways, cooldowns.
3. **The Sync page** in caracole serve, usable from the phone's browser and the app.
4. **The phone**: nix-on-droid and Termux instructions and checks (android/README.md), the app opening the phone's
   own server when it answers.

## Not done, and why

- **No sync through Syncthing alone.** Syncthing would carry the library folder, but each side's database (versions,
  render records, tombstones) would disagree with it, and both sides rendering into one folder would overwrite each
  other's files with no way to choose.
- **No merge inside a song.** A song is taken whole from one side: its chords from one and its lyrics from the other
  would be a song neither side ever had.
- **No sign-in between servers.** caracole has none by the owner's choice; sync is for a network they trust, as caracole
  serve is.
