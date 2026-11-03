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

A unit's **digest** is the SHA-256 of its canonical JSON (canonical.py, and the phone's `core.json.Canonical`: keys
in code-point order, no spaces, every character as it is, a non-integral number as its exact decimal), and a stored
JSON text in it (a version's raw record, a song's lyrics) is hashed by the JSON it holds, else by its bytes
(`canonical.stored_hash`), so two caracoles that wrote one record in two texts agree. What caracole makes from a unit
(PDFs, viewers, `.cho`, info.json, the library page, songbooks' files) is not in it: a side that takes a song renders
it again, so two caracoles of different versions still agree on what a song *is*. Nor is anything a lookup would
find again (a cooldown, a miss's date, the HTTP cache): those are each side's own.

The site indexes (UG's sitemap index, LaCuerda's listings, …) are not units: they merge as `caracole index merge`
already merges them (index_transfer.py: what was read more recently wins, nothing is lost), both ways, at every sync.

## Comparing: three ways

Each caracole has an id of its own (kv `sync:id`, made at first use). After a sync with a peer, each side keeps the
digest every unit had then (kv `sync:base:<peer id>`, `{"format": 2, "units": {"<unit id>": [digest or null,
"<when>"]}}`): the **base**. Then, for each unit:

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

## The format

Every document a side answers (its state, a unit, a push) says its **format**, 2, and a side refuses another; the
base is kept tagged with it. A base an earlier format kept is no base, and is never translated (the owner's rule
against compatibility shims): the first sync after an upgrade compares as a first sync, so a song one side removed
since shows as the other side's to take, and the owner turns that one around. Format 2's state document also says
`now`, its side's clock, which both sides stamp their agreement with, and `indexes`, the newest read of each of its
site indexes (`index_transfer.newest`), so the other side asks only for those it holds older; a reader ignores keys it
doesn't know.

A unit's document holds everything another side needs to take it, and its value, the one its digest is of, is read
back from the document alone (`peer_sync.value_of_document`), so the side taking it checks what it is given against
the digest it compared.

## Applying

A side takes a unit from its peer (a pull; both directions are pulls, the one the owner is on asking the other to pull
what it was chosen to take):

- **a song**: its wanted.txt line written (`songs.upsert_song`, the one way a song is added, so a tombstone of it goes),
  then its names as the peer writes them (artist, title, artists, album, duration, variant), its record's decisions,
  versions and kept files replaced by the peer's (files fetched by name and checked by their SHA-256, every one
  before anything changes), its overrides.toml entries set through overrides.py's writers (comments and layout kept),
  then the song rendered again and the songbooks it is in made again. The rows change in one savepoint, which
  overrides.toml failing rolls back, the folders' changes and wanted.txt (byte for byte, while no one wrote to it
  since) undone with it: all of a song or none. When the peer's spelling of the artist makes a folder that differs
  from this side's in case alone ("Radiohead", "radiohead"), every song of that artist here (one whose line was
  waiting in wanted.txt among them) takes the peer's spelling, its first artist too where that was the artist, and
  their folder is renamed once, through a temporary name, so that a file system blind to case keeps one folder; a
  song whose folder changes moves its files with it, through descriptors opened from the library down, never through
  a link, and a move that fails leaves the song whole where it was;
- **a removal**: `caracole remove --yes` of the song, as the owner would;
- **a songbook**: its table in songbooks.toml written through songbook.py's writers, then made again;
- **an alias, an artist page, a blocked tab**: the entry written, or taken out.

Each unit applies under caracole's lock, as a lookup does (`exclusive(..., interactive=True)`), in a savepoint for
its database rows. A unit is taken only while both sides hold it as compared (a compare-and-swap): one changed there
since is left, "changed there since the comparison", and one changed here since, "changed here since the
comparison". So is one whose document lacks what the take reads beyond its value (a file's rank, a tombstone's
time), "its document can't be read"; the others are taken all the same. Then the library page is written again. The
database is backed up first (backup.py, `before-sync`), as `index merge` is. The base moves on only for the units
that applied, so a sync cut short is finished by the next one.

## How the two talk

Over HTTP, between two `caracole serve`s on a network the owner trusts (the LAN, a tailnet), as the Android app talks
to it already:

- `GET /api/peer/state?peer=<id>`: this side's id, its caracole version, its library's name, each unit's digest and
  label, what it last agreed on with the asking side, and its form token. A read, as `/api/offline` is.
- `GET /api/peer/unit?id=…` and `GET /api/peer/file?song=…&name=…`: a unit whole, and a song's kept file while it is
  what caracole recorded: what a pull reads.
- `POST /peer/pull`: "take these units from that caracole", with the form token, as every write is: `caracole peer
  pull` queued.

**The base, kept by both.** Each side records what the two agree on at the end of every pull it makes, each unit's
digest and when; the other's record comes with its state, and the later agreement counts. So a unit the phone pushed to
the computer is known as synced on both, though only the computer pulled.

**The form token** comes with the state, for the pull a sync posts: no wider than today, since any client that
reaches caracole serve reads it from a page, and another site's page can read neither.

`caracole peer diff ADDRESS` shows the comparison with no change; `caracole peer sync ADDRESS` shows it, has the
owner settle each conflict, takes here what comes from there, and, with `--here`, asks there to take what goes
there. caracole serve gets a Sync page in its Requests tab's spirit (phase 3): the peer's address, the list of
differences, a side chosen for each, and Sync.

## Politeness

The phone keeps every rule caracole keeps (http.py, health.py): its lookups at the lookup pace and budget, robots.txt,
blocks honoured. Two caracoles each count their own budgets; the owner uses one at a time, and the phone runs no
nightly run, so the sites see what they see today. A block one side met moves to the other at a sync: health.py's
cooldowns merge, the later end kept (phase 2).

## Phases

1. **The comparison**, done: peer_sync.py's units, digests and three-way diff; `GET /api/peer/state`;
   `caracole peer diff ADDRESS`.
2. **Applying**, done: schema 15's id; the unit reads; `caracole peer pull` and `sync`; the base kept by both;
   overrides.py's and songbook.py's writers of a unit whole. Format 2, done: the tagged base, the state's `now` and
   `indexes`, the canonical hashing of a version's raw record and a song's lyrics, a unit's value read from its
   document, the compare-and-swap of both sides' digests, and a song taken with the peer's names, its artist
   respelled and its folder moved, whole or not at all. The push, done: `POST /peer/push/new`, `/peer/push/file` and
   `/peer/push` stage another caracole's units in caracole serve, `caracole peer take` takes them, and `caracole peer
   sync --push` gives a side its units with no need for it to reach this one, as the phone always does. The site
   indexes over HTTP, done one way: `GET /api/peer/index`, which the phone imports and a sync merges when the
   computer's are newer. Still to come, in the Android port's milestone 4 (docs/android_port.md): the indexes from
   the phone to the computer, and cooldowns moved across.
3. **The Sync page**, done: the library page's Sync tab (web/sync_routes.py, library_assets/sync.js), the same page
   and routes in caracole serve and in the Android app. The Requests tab on the phone comes with milestone 4.
4. **The phone**, built in Kotlin (docs/android_port.md, milestones 1–3): the app's own caracole on 127.0.0.1, its
   Sync tab syncing with the computer both ways. The Termux route below stays for caracole itself on a phone
   (android/README.md). The research (2026-10-31, from package recipes, PyPI and the pinned nixpkgs, nothing run on a
   phone) found Termux the route: from F-Droid or GitHub, its Python 3.14, Perl, SQLite with FTS5, clang and cmake;
   caracole by pip with deploy.md's constraints, rapidfuzz, selectolax and opencc built there from source (no
   Android wheels); ChordPro by cpanm (Object::Pad and its XS parsers, the rest pure Perl); the site indexes by
   `caracole index export` and `merge`, never built on the phone; `caracole serve --address 127.0.0.1` kept alive by
   termux-services, Termux:Boot and a wake lock, with Android 12+'s phantom process killer turned off. nix-on-droid
   is a fallback (old, slow under proot, and the flake builds for x86_64-linux alone today); Python embedded in the
   app (Chaquopy) can't run caracole's jobs, which start `python -m caracole` as child processes. The app then opens
   the phone's own server when it answers (`shouldInterceptRequest` passing `127.0.0.1:8737` through, its links
   followed, its downloads), else its offline copy.

## Not done, and why

- **No sync through Syncthing alone.** Syncthing would carry the library folder, but each side's database (versions,
  render records, tombstones) would disagree with it, and both sides rendering into one folder would overwrite each
  other's files with no way to choose.
- **No merge inside a song.** A song is taken whole from one side: its chords from one and its lyrics from the other
  would be a song neither side ever had.
- **No sign-in between servers.** caracole has none by the owner's choice; sync is for a network they trust, as caracole
  serve is.
