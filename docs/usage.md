# Using tabarr

You list the songs you want to learn. Tabarr builds a private library from
them: for each song a sing-along sheet (chords over the full lyrics), the
lyrics on their own, and guitar parts where they exist. A nightly
`tabarr run` does the work within a small request budget, and
`Library/_todo.md` lists only what it can't decide without you.

This page covers using tabarr on any machine. [deploy.md](deploy.md) sets it
up as a nightly service on a NixOS host, with secrets, Syncthing and backups.
`tabarr --help` and `tabarr COMMAND --help` list every command and option.

- [Configure](#configure)
- [Say what you want to learn](#say-what-you-want-to-learn)
- [The first run](#the-first-run)
- [One step at a time](#one-step-at-a-time)
- [The to-do page](#the-to-do-page)
- [Browse and search](#browse-and-search)
- [overrides.toml: your decisions](#overridestoml-your-decisions)
- [Fonts for Chinese sheets](#fonts-for-chinese-sheets)
- [The library folder](#the-library-folder)
- [A worked example](#a-worked-example)
- [Running it on the NUC](#running-it-on-the-nuc)

## Configure

Tabarr reads one TOML file: the one `--config` (`-c`) or `$TABARR_CONFIG`
names, or else `~/.config/tabarr/tabarr.toml` (under `$XDG_CONFIG_HOME` when
that is set). Without a file, the defaults apply. Every key is optional, and an
unknown key is an error, so a typo never falls back to a default unnoticed. So
is a value of the wrong type or out of range: write `true` and `false`, and
numbers, without quotes, and paths and names as quoted strings. The commands
then exit with status 2 and name the key. `~` is your home folder, and a
relative path is relative to the config file's folder.

Here is every key with its default. The commented-out keys have none.

```toml
library_dir = "~/Tabs"            # sheets, lyrics, _todo.md, index.html, wanted.txt
music_dir = "~/Music"             # tracks you bought; read only, used only for auto-chords
# state_dir = "..."               # the database and the Spotify token (see below)
# cache_dir = "..."               # every raw response, kept forever (see below)
# overrides_file = "..."          # default: overrides.toml in library_dir
# wanted_file = "..."             # default: wanted.txt in library_dir
user_agent = "tabarr/0.1 (personal tab library)"
guitar_pro_mode = "assisted"      # the only mode: tabarr never downloads Guitar Pro files
chordpro_bin = "chordpro"         # the program that renders PDFs
# cjk_font = "/path/to/font.ttf"  # or $TABARR_CJK_FONT; see "Fonts for Chinese sheets"

[spotify]                         # optional: without a client_id, Spotify is skipped
# client_id = "your-app-client-id"
# client_secret_file = "/path/to/spotify_client_secret"
redirect_uri = "http://127.0.0.1:8888/callback"
liked_songs = true                # read your Liked Songs
playlists = []                    # names, ids or links of playlists you own or collaborate on
suggest_top_tracks = true         # list your top tracks on the to-do page; never added

[ntfy]                            # optional: a summary after each run, and alerts
# url = "https://ntfy.sh/a-long-private-topic"
# token_file = "/path/to/ntfy_token"

[providers.ug]                    # Ultimate Guitar
budget = 60                       # requests per run
delay = [10, 20]                  # seconds between two requests, chosen at random
[providers.lrclib]                # lyrics
budget = 200
delay = [1, 2]
[providers.lacuerda]              # Spanish chord sheets
budget = 30
delay = [10, 20]

[match]                           # how sure a match must be, on a 0-100 score
accept = 90                       # accept at this score or more...
margin = 8                        # ...when the next different title is this far behind
review = 75                       # from here up to an accept, ask you (at most accept)
artist_gate = 90                  # how close another artist's name must be to be tried

[rank]                            # which sheets and guitar parts are kept
coverage_threshold = 0.8          # a sheet is complete when it covers 80% of the lyric lines (0-1)
line_match = 85                   # how close a lyric line must be to count as covered (0-100)
prior_votes = 10                  # m in the Bayesian rating (v·R + m·C) / (v + m)
scored_sheets = 3                 # sheets per song scored for coverage: the top 3 by rating
label_penalty = 0.5               # off the rating of an intro, solo, outro, riff or lesson
variant_bonus = 0.25              # onto an acoustic or live version, when your song is one
keep_guitar_pro = 2               # Guitar Pro or Power Tab pages picked per song

[autochords]                      # read only by `tabarr autochords`
# btc_weights = "/path/to/weights.pt"         # or $TABARR_BTC_WEIGHTS
# beat_checkpoint = "/path/to/final0.ckpt"    # or $TABARR_BEAT_CHECKPOINT
device = "cpu"                    # where the models run
```

Tabarr keeps one sheet and one text tab per song; only the number of Guitar
Pro picks is a setting. Scores and thresholds can't be negative, scores stop
at 100, and `scored_sheets` and `keep_guitar_pro` are whole numbers.

**Folders.** `state_dir` is `$STATE_DIRECTORY` when systemd sets it, else
`$XDG_STATE_HOME/tabarr`, else `~/.local/state/tabarr`. `cache_dir` works the
same way from `$CACHE_DIRECTORY`, `$XDG_CACHE_HOME/tabarr` or
`~/.cache/tabarr`. The state folder holds `tabarr.sqlite` and the Spotify
token: back it up, but don't sync it. The cache keeps every response tabarr
has received, so it rarely asks for a page twice; deleting it costs only
requests.

**Secrets** stay out of the file. The Spotify client secret comes from
`$CREDENTIALS_DIRECTORY/spotify_client_secret` (systemd's `LoadCredential`),
else the file `client_secret_file` names, else
`$TABARR_SPOTIFY_CLIENT_SECRET`. The ntfy token comes from
`$CREDENTIALS_DIRECTORY/ntfy_token`, else `token_file`, else
`$TABARR_NTFY_TOKEN`.

**Providers** are exactly `ug`, `lrclib` and `lacuerda`. Any other
`[providers.…]` table is an error, like any other unknown key.

**Model files** for auto-chords come from `[autochords]`, else the
environment. The `autochords` package's wrapper sets the variables to the
files it ships, so you only set these to use other files.

## Say what you want to learn

### wanted.txt

`wanted.txt` sits in the library folder, so Syncthing carries it to your
laptop and phone and you can edit it anywhere. It always works, with or
without Spotify. One song per line:

    Artist - Title
    Artist - Title | Album
    Artist - Title | m:ss
    Artist - Title | Album | m:ss

For example:

    # the songs I'm learning
    宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Soda Stereo - De Música Ligera
    Radiohead - Creep | Pablo Honey | 3:58

- The album and the duration are optional. Either one makes the lyrics lookup
  exact. A duration is `m:ss`, `h:mm:ss` or whole seconds.
- The artist ends at the first " - " (an en or em dash works too), so a title
  may contain " - " but an artist can't.
- `#` starts a comment, at the start of a line or after a space. Write `\#`
  for a `#` that is part of a name (`John Lennon - \#9 Dream`) and `\|` for a
  `|`.
- An album named like a number needs an empty field after it:
  `Adele - Someone Like You | 21 |`.
- A line tabarr can't read is reported, and the other lines still count.
- Deleting a line doesn't delete the song from tabarr, just as unliking a
  track on Spotify doesn't. To drop a song, put it under `[ignore]` in
  overrides.toml.

Songs are handled newest first, so a song you add today is looked for
tonight.

### tabarr add

`tabarr add ARTIST TITLE [--album ALBUM] [--duration M:SS]` appends the line
for you, then syncs the file at once:

    $ tabarr add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    Added to /home/you/Tabs/wanted.txt, line 16:
      宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Song 宋冬野/斑马斑马: new; the next `tabarr run` looks for it

A song that is already listed isn't added twice, and its line stays as it is:
edit the line to change its album or duration. The file is the source of
truth, so when the database can't be updated, the line is kept all the same
and the next sync adds the song. The first `tabarr add` creates the file, with
a header that explains the format.

### tabarr sync

`tabarr sync` reads wanted.txt, then Spotify when it's set up, and prints a
summary such as `wanted.txt 3 songs, 1 new; Spotify off`, followed by each
problem. The nightly run starts with the same sync.

### Spotify (optional)

Your Liked Songs and the playlists you name join wanted.txt as sources. A
dedicated "Learn" playlist that you add to from your phone works best. A song
that comes from several sources, or a remaster next to the original, is one
song in the library.

1. Create an app at developer.spotify.com. In Development Mode the app's owner
   needs Spotify Premium. Add the redirect URI `http://127.0.0.1:8888/callback`
   exactly: `localhost` is rejected.
2. Put its `client_id` and your `playlists` under `[spotify]`, and the client
   secret where "Secrets" above says.
3. Run `tabarr auth spotify`. It prints an address: open it in a browser and
   allow access. The browser is then sent to `http://127.0.0.1:8888/callback?code=…`,
   which won't load; that's expected. Copy that whole address and paste it
   back. The token is saved in the state folder.
4. Run `tabarr sync`, or leave it to the nightly run.

Without a client id, Spotify is skipped silently, and `tabarr auth spotify`
prints these steps instead. Spotify never fails a sync or a run. When the
token is missing or has expired, the run carries on with wanted.txt, the to-do
page says that Spotify needs authorization, and ntfy tells you once. Spotify
expires the refresh token about six months after you authorize: run
`tabarr auth spotify` again then.

Development Mode reads only playlists you own or collaborate on, so
editorial playlists don't work. A playlist that can't be read is reported.

## The first run

With some songs listed:

    tabarr index build       # once: Ultimate Guitar's sitemaps into a local index
    tabarr match --dry-run   # how every song matches, saving nothing
    tabarr run               # one nightly run, now

### tabarr index build

Tabarr never searches Ultimate Guitar, whose robots.txt disallows its search
page. It reads the sitemaps UG publishes for crawlers instead, and keeps a
local index of every chords, tabs, Guitar Pro and Power Tab page: about 1.6
million. `tabarr index build` reads the sitemap index and its 41 tab sitemaps,
one request at a time, 10–20 seconds apart: about 42 requests, 70 MB and 10
minutes. Its budget is 100 requests, more than a night's, so one build is
enough. A block or a spent budget keeps the sitemaps read so far, and the next
refresh reads the rest.

**`tabarr index build --from DIR`** builds the index offline, from sitemap
files you already have: `sitemap1.xml` to `sitemap40.xml` and
`sitemap_last.xml`, gzipped or not. It sends no requests. The 41 files take
about 22 seconds and make a 303 MB database.

About a tenth of UG's tabs are listed by a bare id (`/tab/1234567`, with no
artist or song in the address), and the index can't see those. They include
every tab of an artist with an accented or non-Latin name, such as Joaquín
Sabina, Maná or 宋冬野. The to-do page asks you for those artists' pages once
(see [the to-do page](#the-to-do-page)).

**`tabarr index refresh`** re-reads `sitemap_last`, the highest-numbered
sitemap and any new numbered one. These are conditional requests, which
usually answer "unchanged". A new tab for a song you want marks that song to
be fetched again. The nightly run does this; the command does it by hand.

**`tabarr index stats`** prints the number of tabs of each type, of artists
and of sitemaps, the newest tab id, and when the index was built and last
refreshed.

### tabarr match --dry-run

Matching is local: no requests, and it takes seconds. `tabarr match` matches
every song against the index and prints one line per song, then the totals:

    accept     100.0  exact         Radiohead - Creep → radiohead/creep  CHANGED unmatched → accept
    review      88.9  fuzzy_title   Radio Head - Crep → radiohead/creep  CHANGED unmatched → review
    not_found      -  -             宋冬野 - 斑马斑马 → -  CHANGED unmatched → not_found
    3 songs: 1 accept, 1 review, 1 not_found; 3 changed. Dry run: nothing was saved.

The columns are the decision, the score, the step that decided it, and the
song with the UG song it matched. `CHANGED` marks a decision, or a UG song,
that differs from the saved one. `--dry-run` saves nothing, so you can try
other thresholds (`[match]` in tabarr.toml) or new overrides on your whole
library in seconds.

- **accept**: a score of 90 or more, with the next different title at least 8
  points behind.
- **review**: any other score of 75 or more, and any match on the title alone
  (usually a cover). You settle these on the to-do page or with
  `tabarr review`.
- **not_found**: below 75. A not-found song is matched again every night, so
  a new tab finds it.
- **pinned** and **ignored** come from overrides.toml.

How a song is matched, in order:

1. Your overrides: `[ignore]`, then `[pin]`, then `[match]`.
2. The title under each of the song's artists: as `[alias]` names them, then
   by their own names, also without hyphens (`AC/DC` meets `acdc`) and, for a
   Chinese name, in pinyin (宋冬野 meets `song-dongye`). An exact title wins,
   else the closest one.
3. The nearest other artist name, at 90 or more, then step 2 under it.
4. The title alone, across all artists: always a review.

### tabarr run

`tabarr run` is what the nightly timer starts. Its steps, in order:

1. **sync**: wanted.txt, then Spotify.
2. **index**: refresh the index, and mark the songs that have new tabs.
3. **match**: match every song again, locally.
4. **lyrics**: ask LRCLIB for the songs that have no lyrics yet.
5. **fetch**: rank and keep Ultimate Guitar sheets and guitar parts.
6. **lacuerda**: look on LaCuerda for Spanish songs without a complete sheet.
7. **scan**: link purchases in Music/, and file Guitar Pro downloads.
8. **render**: write ChordPro files and PDFs.
9. **todo**: rewrite `_todo.md` and `index.html`.

It prints one line per step and the requests made, and sends that summary to
ntfy. Every step runs even when an earlier one failed, so the to-do page is
always rewritten. Until the index is built, the index and match steps are
skipped.

**The budget.** A run sends Ultimate Guitar at most 60 requests, the index
refresh included, 10–20 seconds apart and one at a time. A matched song costs
about 3–6 requests. A long list therefore fills in over a few nights, newest
songs first, and a song the budget cut off half-way resumes from the cache the
next night.

**Errors are never misses.** A block (HTTP 403, 429 or a challenge page)
stops that site for the rest of the run, cools it down for 24 hours (twice as
long after each further block), and sends one ntfy message. Neither a block,
nor a spent budget, nor any other error from a site marks a song not found or
its lyrics missing: the song waits for the next run. Tabarr never works around
a block: no proxies, no retries from elsewhere.

The run exits 1 only for an unexpected error (a bug), after all the steps
have run, so that systemd's `OnFailure` can tell you. Blocks and a spent
budget exit 0. A broken overrides.toml stops the run before its first step
(exit 1, with an ntfy message), because every step reads it.

## One step at a time

Like `tabarr sync`, `tabarr index refresh` and `tabarr match` above, each
step of the run has a command of its own, with the run's budgets, cooldowns
and cache.

- **`tabarr lyrics`** asks LRCLIB for the lyrics of every song that has none
  yet, and again for misses older than 30 days. It writes `lyrics.txt`, plus
  `lyrics.lrc` when LRCLIB has timed lyrics. A song whose lookup failed stays
  pending. It exits 1 when LRCLIB is cooling down or blocks it.
- **`tabarr fetch [--song "ARTIST - TITLE"]`** fetches and ranks the UG
  versions of the songs that need it: new matches, songs with new tabs, songs
  a run left half-done, and not-found songs whose artist page is known (at most
  once in 30 days). Per song it prints what it kept, as
  `Artist - Title: sheet 101 · Guitar Pro 301, 303 · tab 402 (3 requests)`.
  `--song` fetches that one song now, even when nothing about it changed; the
  song must be in the library and matched, or not found with its artist page
  known. A cooldown, a block or a spent budget exits 0.
- **`tabarr lacuerda`** looks on LaCuerda for Spanish songs (judged by their
  lyrics, or by their title until there are lyrics) that have no complete
  sheet, at most once in 30 days per song. One artist page serves every song
  by that artist. LaCuerda's sheet is kept when there is no sheet yet, when it
  is complete and the kept one isn't, or when neither is complete and it
  covers more of the lyrics. An artist LaCuerda doesn't have gets an almost
  empty page, with HTTP 200; tabarr reads that as "not on LaCuerda". It exits 1
  when LaCuerda is cooling down or blocks it.
- **`tabarr scan`** links the audio files in Music/ to your songs, by their
  tags (or an "Artist - Title" file name) and their duration, give or take 3
  seconds. It never adds a song. A file named as the song wins over one whose
  name only comes close, so a whole album's "Pt. 1" doesn't take the place of
  its "Pt. 2". A close name must also be clearly closer than any other, and
  when your line gives no duration, the file must be as long as LRCLIB's
  lyrics say. Chinese names are compared as pinyin too, so 斑馬斑馬 meets
  斑马斑马. A Music/ folder that is missing or has no audio, such as a disk
  that isn't mounted, unlinks nothing. Then it files the Guitar Pro and Power
  Tab files you dropped into `_inbox/`, by their names: a file named
  `Soda Stereo - De Musica Ligera (ver 2).gp5` becomes that song's
  `guitar-N.gp5`, where N is the rank tabarr gave version 2. A file the
  library already has is removed from the inbox; a file it can't place stays
  there.
- **`tabarr render [--force]`** writes `sheet.cho` and `sheet.pdf` next to
  every kept sheet, transposed as `[transpose]` says, with the key, the artist
  and the capo under the title. A PDF is made again only when its sheet, its
  transposition or the font changes; `--force` makes them all again. It exits
  1 when a sheet couldn't be rendered, and the log says why.
- **`tabarr todo`** rewrites `_todo.md` and `index.html` from the database.
- **`tabarr review`** settles uncertain matches, one prompt per song (see
  [Review](#review)).
- **`tabarr search QUERY [--limit N] [--add N]`** searches your library and
  the offline UG index (see [tabarr search](#tabarr-search)).
- **`tabarr autochords`** writes `sheet (auto).txt` from audio you bought, for
  songs with no human sheet (see [the worked example](#a-worked-example)). It
  needs the flake's `packages.autochords`, with torch, librosa and beat_this;
  the default package says so and exits 1. It exits 1 too when a song failed,
  which is tried again next time.

## The to-do page

`Library/_todo.md` lists only what needs you, with the links to do it and the
exact lines to paste. Each run rewrites it, and so does `tabarr todo`. It
starts with a summary (songs found, wanted and ignored), a link to
`index.html`, and how many songs are waiting for the nightly fetch. Then each
of these sections, when it has something in it:

- **Review.** Matches tabarr wasn't sure about. Each candidate has its score,
  the UG song, the step that found it and links to its pages by type, then the
  lines to paste into overrides.toml (see [Review](#review)).
- **Partial sheets.** The best sheet covers less than 80% of the lyrics: the
  percentage, the sheet and its source page.
- **Artists to find on Ultimate Guitar.** UG lists artists with accented or
  non-Latin names only by bare ids (Joaquín Sabina, Maná, 宋冬野), so tabarr
  can't see their tabs. For each such artist with a song not found, the page
  links a UG search. Open the artist's page once, by hand, and paste its
  address under `[artist_url]`:

  ```toml
  [artist_url]
  "宋冬野" = "https://www.ultimate-guitar.com/artist/<name>_<id>"
  ```

  The artist page lists all of the artist's tabs, bare ids included. The next
  run reads it, finds your songs on it by title, and fetches them like any
  matched song. That's once per artist, not per song.
- **Buy list.** Songs still without a sheet once UG has been checked, or not
  found at all. Each has links to buy the track DRM-free (Bandcamp, Qobuz, the
  iTunes Store) and to check the song first (Chordify, Songsterr, a YouTube
  lesson search). Drop the purchase into Music/, and auto-chords writes a sheet
  from it. Songs whose audio you have are left off.
- **Guitar Pro pages to click.** The Guitar Pro and Power Tab versions tabarr
  picked for each song, best first, with version, rating and votes. Open each
  page, click its Download button, and drop the file into `_inbox/`; the next
  run, or `tabarr scan`, files it under its song. Tabarr never downloads these
  itself: UG's robots.txt closes its download endpoint to bots.
- **Guitar parts not found.** Songs UG has no guitar part for, with Songsterr
  and YouTube links.
- **Inbox: files tabarr couldn't place.** Rename such a file
  "Artist - Title.ext", or move it into the song's folder yourself.
- **Missing lyrics.** LRCLIB has none for these yet; tabarr asks again after
  30 days.
- **Suggestions from your Spotify top tracks**, with `suggest_top_tracks`.
  Add the ones you want to learn to your Learn playlist or to wanted.txt.
- **PDFs.** The last render: how many PDFs were made or failed, a font
  problem if there is one, and the sheets that failed.
- **Sources.** Whether Spotify is off, synced, or needs `tabarr auth spotify`,
  and how many songs wanted.txt has, with the lines it couldn't read.
- **Provider health.** For Ultimate Guitar, LRCLIB and LaCuerda: OK, or
  cooling down until when; the last success; the last error; the requests of
  the last run.

### Review

`tabarr review` asks about each song to review in turn:

    [1/1] Radio Head - Crep
      1) 89  radiohead/creep (fuzzy_title)  https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169
    Pick 1-1, (p)in a URL, (i)gnore, (s)kip, (q)uit:

- **A number** accepts that candidate. It writes
  `[match] "Radio Head - Crep" = "radiohead/creep"`, and
  `[alias] "Radio Head" = "radiohead"` when the artist's name differs, so
  every other song by that artist matches too. A candidate found by title alone
  gets no alias: it is usually a cover by someone else.
- **p** asks for a UG tab address, and writes it under `[pin]`.
- **i** ignores the song: it goes under `[ignore]`.
- **s**, or Enter, skips the song; **q** stops.

Each answer goes into overrides.toml, with your comments kept, so it survives
a lost database. When anything changed, tabarr matches again at the end. The
to-do page's Review section has the same `[match]` and `[alias]` lines, ready
to paste, if you'd rather edit the file.

## Browse and search

### Library/index.html

`index.html` sits next to `_todo.md`, and each run rewrites it. Open it from
the synced folder, in a browser on the laptop or the phone. It needs no server
and loads nothing from the network. It shows every song with its status, its
key or transposition, and links to its files, the PDF first. A song without a
sheet also gets buy and search links.

The search box filters as you type. It ignores case and accents, so "musica"
finds "De Música Ligera", and it matches Chinese titles by pinyin: "ban ma" or
"banma" finds 斑马斑马. The buttons show all songs, or only those found,
wanted or needing review, and you can sort by artist or by when songs were
added. When nothing in the library matches, the page shows the
`tabarr search` line to run.

On Android, a file manager that opens the page through a `content://` address
can break its links to the songs' files. A browser, or an HTML viewer that
opens the file directly, works.

### tabarr search

`tabarr search QUERY [--limit N] [--add N]` looks in two places, and sends no
request:

    $ tabarr search creep
    In your library
      Radiohead - Creep · wanted, no sheet yet · no folder yet

    On Ultimate Guitar (offline index)
      1. Radiohead - Creep · chords×2 tabs×1 guitar-pro×1 (incl. acoustic)
         https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169
         in your library
      2. Stone Temple Pilots - Creep · chords×1
         https://tabs.ultimate-guitar.com/tab/stone-temple-pilots/creep-chords-5001
         tabarr add "Stone Temple Pilots" "Creep"

- **In your library**: every song, whatever its status, with its folder.
- **On Ultimate Guitar**: numbered hits from the offline index, each with its
  tabs per type, one of its pages, and the `tabarr add` line to paste.

QUERY is words of the artist, the title or both. Matching ignores case,
accents and punctuation (`AC/DC`, `R.E.M.`), survives a typo, and also
compares Chinese as pinyin. `--limit N` (or `-n N`) shows up to N hits from
each place, 10 by default. `--add N` adds UG hit N to wanted.txt and syncs it,
the same way `tabarr add` does; a hit your library already has under another
name is left alone. When nothing matches well, or the query has accented or
non-Latin letters, the command also explains bare ids and prints the
`[artist_url]` line to paste.

## overrides.toml: your decisions

`overrides.toml` sits in the library folder (or where `overrides_file` says),
and can live in git. `tabarr review` writes `[match]`, `[alias]`, `[pin]` and
`[ignore]` for you; you write the rest by hand. These are all the tables:

```toml
[alias]        # source artist -> UG artist slug(s): fixes every song by that artist
"Bob Marley & The Wailers" = "bob-marley"

[match]        # song -> UG song, as "artist-slug/song-slug"; still picks up new tabs
"Soda - Persiana Americana" = "soda-stereo/persiana-americana"

[artist_url]   # artists UG lists only by bare ids -> their UG artist page
"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/<name>_<id>"

[pin]          # always use exactly these tab pages for a song
"Soda Stereo - De Música Ligera" = ["https://tabs.ultimate-guitar.com/tab/85053"]

[transpose]    # semitones, -11 to 11, applied when PDFs are rendered
"Soda Stereo - De Música Ligera" = -2

[ignore]       # songs tabarr leaves alone
songs = ["Some Artist - Some Interlude"]

[block]        # tabs never to use
tab_ids = [1601668]
```

- **Song keys** are written `"Artist - Title"`. They match the way songs
  match, so case, accents, a leading "The" and Spotify suffixes such as
  " - Remastered 2011" don't matter.
- **`[alias]`** takes one UG artist slug or a list of them. The slug is the
  artist part of a tab's address, as in `/tab/bob-marley/...`.
- **`[match]`** points one song at one UG song. Unlike a pin, it still picks
  up tabs added to that song later.
- **`[artist_url]`** is keyed by the artist's name as your songs write it. The
  value is the artist's page on UG, whose address ends in an underscore and a
  number (`https://www.ultimate-guitar.com/artist/soda_stereo_2946`, say).
- **`[pin]`** takes tab page addresses: paste them as your browser shows them.
  Pinned tabs replace the candidates of their kind (sheet, Guitar Pro, tab),
  in the order given.
- **`[transpose]`** shifts the chords and the key in the PDF. `sheet.txt`
  stays as the source wrote it.
- **`[ignore]`** stops all work on a song: no matching, fetching, rendering or
  to-do items. Take it out of the list, and the song comes back.
- **`[block]`** keeps tab ids out of every ranking.

An unknown table or a malformed entry is an error that names it. The
commands that read the file then exit with status 2, and the nightly run does
nothing until the file is fixed (ntfy tells you).

## Fonts for Chinese sheets

ChordPro's built-in PDF fonts have no Chinese glyphs, so a sheet with Chinese
lyrics needs a font file. The Nix package sets one: its wrapper points
`$TABARR_CJK_FONT` at `FusionKaiJ-Regular.ttf` from nixpkgs' `lxgw-fusionkai`,
a Kai (brush-style) face. To use another font, set `cjk_font`, which wins over
the variable.

Two kinds of font don't work with ChordPro 6.050.7, so tabarr refuses them
with an error instead of writing a PDF with blank text:

- font collections (`.ttc`), which is all nixpkgs ships of Noto CJK and
  Source Han Sans: ChordPro can't open them;
- TrueType fonts with odd-length glyph records, which most CJK `.ttf` files
  have (LXGW Neo XiHei and WenKai among them): their glyphs come out blank.

A CFF-based `.otf` works too; it is embedded whole, so its PDFs are larger.
Until a usable font is set, a Chinese sheet still gets its `.cho` file, and
the to-do page's PDFs section names the sheets waiting for a font. Section 7 of
[deploy.md](deploy.md#7-chinese-sheets-in-the-pdfs) has the details.

## The library folder

```
Library/                    library_dir: ~/Tabs by default, /srv/tabs on the NUC
  _todo.md                  what needs you
  index.html                browse and search the library
  wanted.txt                your songs
  overrides.toml            your decisions
  _inbox/                   Guitar Pro downloads waiting to be filed
  宋冬野/
    斑马斑马/
      sheet.txt             the chosen chord sheet, as plain text
      sheet.json            the same version as the source gave it
      sheet.cho  sheet.pdf  ChordPro, and a PDF in your key
      lyrics.txt            the lyrics, from LRCLIB
      lyrics.lrc            the timed lyrics, when LRCLIB has them
      guitar-1.gp5          Guitar Pro or Power Tab files you downloaded, best first
      tab.txt  tab.json     the best text tab
      sheet (auto).txt      made from audio you bought, when no human sheet exists
      sheet (auto).cho      its ChordPro and PDF
      sheet (auto).pdf
      info.json             where everything came from
Music/                      music_dir: the tracks you bought (tabarr only reads it)
```

Folder names keep their accents and scripts, but never contain a path
separator or a character file systems reserve: `AC/DC` becomes `AC-DC`.

Keep the library private. The sheets and lyrics are other people's work, and
a personal offline copy is the closest thing to the sites' personal-use terms.

## A worked example

The song is 斑马斑马 by 宋冬野 (Song Dongye), from the album 安和桥北. It
shows two hard cases: an artist Ultimate Guitar lists only by bare ids, and
lyrics without timings.

**1. Add it.**

    $ tabarr add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    Added to /home/you/Tabs/wanted.txt, line 16:
      宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Song 宋冬野/斑马斑马: new; the next `tabarr run` looks for it

The album and duration make the lyrics lookup exact. Written "斑马，斑马",
with a comma, it is the same song to tabarr.

**2. It isn't found on Ultimate Guitar.** UG's sitemaps list every tab of
宋冬野 by a bare id, so the local index has none of them:

    $ tabarr match --dry-run
    not_found      -  -             宋冬野 - 斑马斑马 → -  CHANGED unmatched → not_found

The to-do page then lists 宋冬野 under "Artists to find on Ultimate Guitar",
with a link to search UG, and puts the song on the buy list. Either way works:

- **Paste the artist's page.** Search UG in your browser, open 宋冬野's artist
  page, and paste its address into overrides.toml:

  ```toml
  [artist_url]
  "宋冬野" = "https://www.ultimate-guitar.com/artist/<name>_<id>"
  ```

  The next run reads that page, finds 斑马斑马 on it by its title (in either
  script, or in pinyin), and fetches its versions like any matched song;
  `tabarr fetch --song "宋冬野 - 斑马斑马"` does it now. A chords version
  becomes `sheet.txt`, and the song is found.
- **Buy the track**, from the buy list's links, for an auto sheet (step 4).

**3. The lyrics come from LRCLIB, plain.** LRCLIB has the song with plain
lyrics only, and no timings, so its folder gets `lyrics.txt` and no
`lyrics.lrc`. The lyrics are in Traditional characters (斑馬), while sheets
are usually in Simplified ones (斑马). Tabarr compares Chinese text as pinyin
when it checks how much of the lyrics a sheet covers, so a complete sheet
still counts as complete.

**4. Buy it, drop it into Music/, and run `tabarr autochords`.** The command
needs the flake's `packages.autochords` (`nix shell .#autochords` on the
laptop; on the NUC, the `tabarr-autochords` unit runs it after each nightly
run, see [deploy.md](deploy.md#6-auto-chords)). It links the new file to the
song by its tags and duration, finds the chords and the beats, and writes
`sheet (auto).txt`. With no timed lyrics to lay the chords over, the sheet is
a chord chart by bars followed by the plain lyrics. It starts with
"auto-generated, unverified", the song counts as found, and the next render
makes `sheet (auto).pdf` with the Chinese font. A complete human sheet found
later takes its place.

If the scan reports the file as unmatched, make the file's artist and title
tags match the song's line in wanted.txt.

## Running it on the NUC

[deploy.md](deploy.md) sets tabarr up as a nightly NixOS service: the timer,
the hardened units, agenix secrets, Syncthing for the library and the music,
restic backups, and the offline auto-chords unit. There, run any command as
the service does with `sudo tabarr-admin COMMAND`, for example
`sudo tabarr-admin index build`.
