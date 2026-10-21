# Using caracole

You list the songs you want to learn. Caracole builds a private library from
them: for each song a sing-along sheet (chords over the full lyrics), the
lyrics on their own, and guitar parts where they exist. A nightly
`caracole run` does the work within a small request budget, and
`Library/_todo.md` lists only what it can't decide without you.

This page covers using caracole on any machine. [deploy.md](deploy.md) sets it
up as a nightly service on a NixOS host, with secrets, Syncthing and backups.
`caracole --help` and `caracole COMMAND --help` list every command and option.

- [Configure](#configure)
- [What caracole prints](#what-caracole-prints)
- [Say what you want to learn](#say-what-you-want-to-learn)
- [The first run](#the-first-run)
- [One step at a time](#one-step-at-a-time)
- [Audio from YouTube](#audio-from-youtube)
- [The to-do page](#the-to-do-page)
- [Browse and search](#browse-and-search)
- [Songbooks](#songbooks)
- [overrides.toml: your decisions](#overridestoml-your-decisions)
- [Fonts for Chinese sheets](#fonts-for-chinese-sheets)
- [The library folder](#the-library-folder)
- [A worked example](#a-worked-example)
- [Running it on the NUC](#running-it-on-the-nuc)

## Configure

Caracole reads one TOML file: the one `--config` (`-c`) or `$CARACOLE_CONFIG`
names, or else `~/.config/caracole/caracole.toml` (under `$XDG_CONFIG_HOME` when
that is set). Without a file, the defaults apply. Every key is optional, and an
unknown key is an error, so a typo never falls back to a default unnoticed. So
is a value of the wrong type or out of range: write `true` and `false`, and
numbers, without quotes, and paths and names as quoted strings. The commands
then exit with status 2 and name the key. `~` is your home folder, and a
relative path is relative to the config file's folder.

Here is every key with its default. The commented-out keys have none.

```toml
# data_dir = "..."                # one folder for the four below (see below)
library_dir = "~/Tabs"            # sheets, lyrics, _todo.md, index.html, wanted.txt
music_dir = "~/Music"             # tracks you bought; read only, used only for auto-chords
# state_dir = "..."               # the database, the Spotify token and the lock (see below)
# cache_dir = "..."               # every raw response, kept forever (see below)
# overrides_file = "..."          # default: overrides.toml in library_dir
# wanted_file = "..."             # default: wanted.txt in library_dir
user_agent = "caracole/0.1 (personal tab library)"
guitar_pro_mode = "assisted"      # UG's mode, the only one: you click its Guitar Pro pages
chordpro_bin = "chordpro"         # the program that renders PDFs
ytdlp_bin = "yt-dlp"              # or $CARACOLE_YTDLP_BIN; see "Audio from YouTube"
# cjk_font = "/path/to/font.ttf"  # or $CARACOLE_CJK_FONT; see "Fonts for Chinese sheets"

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
lookup_delay = [0.5, 1.5]         # the same, for a song you look up now (caracole get); [0, 0]: none
lookup_requests = 6               # requests to the site for that one song, at most
lookup_per_hour = 60              # requests to the site for every lookup of an hour, together
[providers.lrclib]                # lyrics
budget = 200
delay = [1, 2]
[providers.lacuerda]              # Spanish chord sheets, and its listings of every artist
budget = 30
delay = [10, 20]
[providers.gtptabs]               # Guitar Pro files, downloaded for you
enabled = true                    # false: caracole asks gtptabs.com nothing
budget = 20
delay = [10, 20]
[providers.musescore]             # MuseScore's song sitemaps, for links to its pages
enabled = true                    # false: caracole asks MuseScore nothing
budget = 10
delay = [10, 20]
[providers.youtube]               # the audio of songs nobody has charted, with auto-chords
enabled = true                    # false: caracole runs no yt-dlp; on only with auto-chords
budget = 6                        # yt-dlp runs per run, each a search or a download
delay = [15, 30]                  # seconds between two yt-dlp runs

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

[autochords]                      # read only by `caracole autochords`
# btc_weights = "/path/to/weights.pt"         # or $CARACOLE_BTC_WEIGHTS
# beat_checkpoint = "/path/to/final0.ckpt"    # or $CARACOLE_BEAT_CHECKPOINT
device = "cpu"                    # where the models run
```

Caracole keeps one sheet and one text tab per song, and beside the sheet the
other Ultimate Guitar versions it scored (`scored_sheets`); only the number of
Guitar Pro picks is a setting of its own. Scores and thresholds can't be negative, scores stop
at 100, and `scored_sheets` and `keep_guitar_pro` are whole numbers.

**Folders.** With `data_dir`, everything is in one folder: `library_dir`,
`music_dir`, `state_dir` and `cache_dir` default to its `library`, `music`,
`state` and `cache` folders, and one you set yourself still wins. Without
it, `state_dir` is `$STATE_DIRECTORY` when systemd sets it, else
`$XDG_STATE_HOME/caracole`, else `~/.local/state/caracole`. `cache_dir` works the
same way from `$CACHE_DIRECTORY`, `$XDG_CACHE_HOME/caracole` or
`~/.cache/caracole`. The state folder holds `caracole.sqlite`, the Spotify token
and `caracole.lock`: back it up, but don't sync it. The cache keeps every
response caracole has received, so it rarely asks for a page twice; deleting it
costs only requests. PDFs are made in it too, each in a private folder that
goes when the PDF is done, so caracole must be able to write there. Its
`icons` folder holds each site's icon, for `index.html` (see
[Where each file came from](#where-each-file-came-from)).

**The database.** Before a new caracole migrates `caracole.sqlite`, it copies it
to `caracole.sqlite.vN.bak`, N being the version it had. A database a newer
caracole migrated, after a rollback say, stops every command that uses it with
status 2: `database: … is at schema version 8, but this caracole knows up to 7:
a newer caracole migrated it.` The message ends by naming that copy to restore,
when there is one. Schema 4 keeps the songs you removed. Schema 5 adds an index of the UG index's names, for
searching as you type: the first command after the upgrade builds it from the
index, in a few seconds, and it adds about a quarter to the database's size
(about 75 MB to a full index's 315). Schema 6 adds LaCuerda's artist index, empty
until the nightly run, or `caracole lacuerda --index`, reads LaCuerda's listings
of every artist (see [`caracole lacuerda`](#one-step-at-a-time)). Schema 7 keeps
the tabs of the Ultimate Guitar artist pages caracole reads, for searches (see
[caracole search](#caracole-search)): the first nightly run or `caracole get`
after the upgrade fills it, once, from what the HTTP cache holds of the artist
pages caracole knows, with no request, even while Ultimate Guitar cools down. A state
folder caracole can't use ends a command with status
1 and `can't open the database …` (or `can't open …/caracole.lock: …`).
`caracole add` is the exception to both: it keeps its line and warns (see
below).

**Secrets** stay out of the file. The Spotify client secret comes from
`$CREDENTIALS_DIRECTORY/spotify_client_secret` (systemd's `LoadCredential`),
else the file `client_secret_file` names, else
`$CARACOLE_SPOTIFY_CLIENT_SECRET`. The ntfy token comes from
`$CREDENTIALS_DIRECTORY/ntfy_token`, else `token_file`, else
`$CARACOLE_NTFY_TOKEN`.

**Providers** are exactly `ug`, `lrclib`, `lacuerda`, `gtptabs`, `musescore`
and `youtube`. Any other `[providers.…]` table is an error, like any other
unknown key. Each has the three `lookup_` keys too, with the defaults above
(YouTube's go unused: a lookup runs no yt-dlp).

**Two paces.** Bulk work, the nightly run, `caracole index build` and every
command but `caracole get`, keeps `budget` and `delay`: 10–20 seconds between
two requests to Ultimate Guitar, whichever caracole sends them. A lookup
(`caracole get`, and the lookups of `caracole serve`) is one song you asked
for just now, so it keeps `lookup_delay` instead, about a second, and stops
after `lookup_requests` requests to a site; every lookup of the last hour
shares `lookup_per_hour`, so a script or a stuck button can't turn lookups
into a crawl. Half of that hour is kept for sheets: what follows a lookup's
sheet, which the nightly run would do anyway (Ultimate Guitar's other sheets
scored, guitar parts and the text tab; LaCuerda's for a song with a sheet
already), stops once the hour's lookups have spent half of `lookup_per_hour`,
so an evening of songs looked up on the spot keeps getting sheets (about
twenty to thirty an hour with the defaults). What a lookup leaves undone waits
for the nightly run. Either
pace sends one request at a time to a site, never less than its robots.txt's
`Crawl-delay` apart (none of the sites caracole reads sets one for every
robot), and keeps everything else below: robots.txt, the cache, the blocks and
cooldowns. Only gtptabs.com, MuseScore and YouTube can be turned off: with
`enabled = false` under `[providers.gtptabs]`, `[providers.musescore]` or
`[providers.youtube]`, caracole sends that site nothing, the nightly run skips
its step, and the to-do page's Provider health says it is off. The other three
are what caracole is built on, so `enabled` in their tables is an unknown key.
YouTube is on only where caracole can make chords of what it downloads (see
[Audio from YouTube](#audio-from-youtube)); its budget counts yt-dlp runs, not
requests.

**Guitar Pro files** come two ways. Ultimate Guitar's robots.txt closes its
download endpoint to bots, so its Guitar Pro pages are yours to click:
`guitar_pro_mode` is Ultimate Guitar's, and takes only `"assisted"` (any other
value is an error). gtptabs.com's robots.txt leaves its downloads open, so
caracole downloads a file there for each song that has none (`caracole gtptabs`,
in [One step at a time](#one-step-at-a-time)).

**Model files** for auto-chords come from `[autochords]`, else the
environment. The `autochords` package's wrapper sets the variables to the
files it ships, so you only set these to use other files.

## What caracole prints

Every command writes its report, what it did and what needs you, on stdout,
and its log, the diagnostics, on stderr, so `caracole run > night.txt` keeps
the report alone. Like `--config`, the options that set how much the log
says come before the command (`caracole -v run`):

| Option | The log on stderr |
|---|---|
| none | the problems: warnings and errors |
| `-q`, `--quiet` | the problems too; `caracole run` also cuts its summary down to what needs you and what went wrong |
| `-v`, `--verbose` | caracole's own information too, such as a line per request: `LRCLIB GET https://lrclib.net/api/get?… → 503 Service Unavailable in 0.21 s (1 of 200 requests)`, or `→ 200 OK from the cache` for an answer it sent no request for |
| `-vv` | debugging lines too, each with the name of its logger, and the logs of the libraries caracole uses (httpx, httpcore, urllib3, spotipy, and numba or torch under auto-chords), which otherwise show only their warnings and errors |

A warning starts with `warning:` and an error with `error:`, coloured on a
terminal unless `$NO_COLOR` is set; nothing is coloured when the output isn't
a terminal. Under systemd, each line starts with its priority for the journal
instead (see [deploy.md](deploy.md#logs)). No secret reaches the log, at any
level: not the Spotify client secret, the ntfy token, an Authorization header
or an OAuth token.

An unexpected error, a bug in caracole, ends the command with exit status 1:
one line that says so, then its traceback, on stderr.

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
- The line's album and duration win over Spotify's. Edit them, and the next
  sync changes the song, and the duration the scan checks a purchase
  against; take one off the line, and Spotify's takes its place, if Spotify
  has the song.
- The artist ends at the first " - " (an en or em dash works too), so a title
  may contain " - " but an artist can't.
- A version after the title, as in `Radiohead - Creep - Acoustic` or
  `Soda Stereo - Té Para Tres (En Vivo)`, is still the same song, and asks
  for that version: UG versions labelled the same way rank higher
  (`variant_bonus`). Change it or take it off, and the next sync changes the
  song.
- A song on two lines is the first line's: a later line only fills in an
  album or a duration the first leaves out.
- `#` starts a comment, at the start of a line or after a space. Write `\#`
  for a `#` that is part of a name (`John Lennon - \#9 Dream`) and `\|` for a
  `|`.
- An album named like a number needs an empty field after it:
  `Adele - Someone Like You | 21 |`.
- A line caracole can't read is reported, and the other lines still count.
- Deleting a line doesn't delete the song from caracole, just as unliking a
  track on Spotify doesn't, and the song keeps the album and the duration the
  line gave it. To keep a song but stop all work on it, put it under
  `[ignore]` in overrides.toml; to take it out of caracole, files and all,
  run [`caracole remove`](#caracole-remove).
- The file must be a regular file. A symbolic link there is refused, not
  followed: the sync says `wanted.txt: not read: … is a symbolic link, which
  caracole doesn't follow; put the file itself there`, and the to-do page says
  that wanted.txt can't be read, under Setup problems and Sources.

Songs are handled newest first, so a song you add today is looked for
tonight. A line keeps its place when an upgrade changes how caracole keys
songs: the first command to open the database re-keys them, and two records
that turn out to be one song (斑馬斑馬 and 斑马斑马, say) become one.

### caracole add

`caracole add ARTIST TITLE [--album ALBUM] [--duration M:SS] [--lacuerda URL]` (or
`caracole add "ARTIST - TITLE"`) appends the line
for you, then syncs the file at once and rewrites `_todo.md` and
`index.html`:

    $ caracole add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    Added 宋冬野 - 斑马斑马 to wanted.txt; the next `caracole run` looks for it.
    Not in the offline Ultimate Guitar index under this name: `caracole search` with a few of its words looks wider.

It says in one line what it did and what the library has of the song: "is in
wanted.txt already" for a song listed before, and "the library has it, with a
sheet" (or "with no sheet yet", or "ignored by overrides.toml") for a song the
library knew, from Spotify, say. `caracole -v add …` also prints the song's
line in wanted.txt, with its number and the file's path, and the song's key in
the library:

    $ caracole -v add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    wanted.txt line 16 (/home/you/Tabs/wanted.txt): 宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Added 宋冬野 - 斑马斑马 to wanted.txt; the next `caracole run` looks for it.
    Song 宋冬野/斑马斑马: new
    Not in the offline Ultimate Guitar index under this name: `caracole search` with a few of its words looks wider.

Then it matches the song against the offline index, as the nightly match
step would (see [caracole match](#caracole-match---dry-run)), saves the match
and says what it found, on the lines after that one: the UG song it matched
(`On Ultimate Guitar: radiohead/creep (exact)`), that the index has nothing
under that name, or, when it isn't sure, the candidates, each with its score,
the step that found it and a page, as `caracole review` lists them:

    $ caracole add epic "I'm not sorry for loving you"
    Added epic - I'm not sorry for loving you to wanted.txt; the next `caracole run` looks for it.
    Not sure which Ultimate Guitar song it is. Did you mean:
      1) 94  misc-musicals/epic-the-musical-not-sorry-for-loving-you (catch_all)  https://tabs.ultimate-guitar.com/tab/misc-musicals/epic-the-musical-not-sorry-for-loving-you-chords-4742072
      2) 82  bill-fox/im-not-over-loving-you (title_only)  https://tabs.ultimate-guitar.com/tab/bill-fox/im-not-over-loving-you-chords-1066803
    Pick one with `caracole review`, or on _todo.md.

The review is saved, so `caracole review` can settle it at once. Nothing is
matched while the index is empty (it says to run `caracole index build`) or
overrides.toml can't be read, and an incomplete index records no miss: the
song may be in a sitemap not read yet. `caracole search --add` matches the song
it adds the same way, and says what it did in the same words.

A song that is already listed isn't added twice, and its line stays as it is
(a second line says so when you gave another album or duration): edit the line
to change its album or duration, and the next sync changes the
song. The file is the source of truth, so the line is written first, before
`caracole add` waits for any other caracole to finish. When the database can't be
updated, the line is kept all the same, a warning says why, and the next sync
adds the song. The first `caracole add` creates the file, with a header that
explains the format.

`--lacuerda URL` is the LaCuerda song you picked for it, its page's address
(`https://acordes.lacuerda.net/estopa/como_camaron`) or one of its versions'
(`…/como_camaron-2.shtml`), as `caracole search` prints it with the song: it
goes under `[lacuerda]` in overrides.toml (see
[overrides.toml](#overridestoml-your-decisions)), and the nightly run keeps
that sheet, whatever the song's language, asking LaCuerda for it at its next
pass however lately it answered for the song: `LaCuerda: the nightly run keeps
the sheet you picked there (https://acordes.lacuerda.net/estopa/como_camaron),
recorded under [lacuerda] in overrides.toml.` Any other address is a usage
error (exit 2), with nothing written. overrides.toml is in the library, so the
pick is written once `caracole add` holds caracole's lock, as every writer of
that file does; a lock file that can't be opened exits 1, the line in
wanted.txt and no pick written. A song you picked on LaCuerda is no Ultimate
Guitar review of other artists' songs of its title (covers, mostly): the sheet
is the one you picked, so with nothing of its artist's by that name in the
offline index it is not found there, and says so: `Ultimate Guitar's offline
index has no song of theirs by this name; the sheet is the one you picked on
LaCuerda.`

A song you [removed](#caracole-remove) comes back with `caracole add`, as new:
`Added Radiohead - Creep to wanted.txt; back from its removal on 2026-10-19, as
new; the next caracole run looks for it.`

A song needs its artist: caracole looks it up by artist and title. Given one
name with no " - " (`caracole add Wonderwall`), `caracole add` writes nothing
and exits 2. It lists your songs of that title, then what
`caracole search Wonderwall` lists first, five hits numbered as the search
numbers them, each with its `caracole add "Oasis" "Wonderwall"` line (a hit
scoring under 90 has none: it may well be another song), and
`caracole search "Wonderwall" --add N` to add one by its number; the last line
says what it takes, with `caracole add ARTIST "Wonderwall"` (or, for an
artist's name alone, `caracole add "Oasis" TITLE`). Nothing asks a site who
sang a title: the offline index answers, or you do.

An artist such as "misc", "unknown" or "Various Artists" is no one's name, so
nothing can be found by it: `caracole add misc 斑马` adds the line, and warns
that caracole may never find the song, and that `caracole search "斑马"` lists
the songs of that title with their artists.

### caracole get

`caracole get "ARTIST - TITLE"` (or `caracole get ARTIST TITLE`) is for the
song you want to play now. One name alone (`caracole get Wonderwall`) looks
nothing up and exits 2: like `caracole add`, it lists your songs of that
title and the offline index's songs, each scoring 90 or more with its
`caracole get --ug oasis/wonderwall "Oasis - Wonderwall"` line. It does the nightly run's work for that song alone,
at once, sheet first, and says where the sheet is the moment it is kept:

    $ caracole get "Radiohead - Creep"
    Song: added to wanted.txt, line 16.
    Match: matched to radiohead/creep.
    Sheet: tab 4169 from Ultimate Guitar: /home/you/Tabs/Radiohead/Creep/sheet.txt, readable after 2.1 s.
    PDF: made.
    PDF: /home/you/Tabs/Radiohead/Creep/sheet.pdf
    Lyrics: found.
    Ultimate Guitar: sheet 4170 · Guitar Pro 4174 · tab 4172.
    Sheet: a better one replaced it, in /home/you/Tabs/Radiohead/Creep/sheet.txt.
    LaCuerda: skipped: not a song for LaCuerda: not Spanish, a complete sheet already, or asked this month.
    gtptabs.com: Guitar Pro file downloaded.
    Pages: _todo.md and index.html rewritten.
    Done in 9.4 s: 8 requests (Ultimate Guitar 5, LRCLIB 1, gtptabs.com 2).

In order:

1. **The song.** One the library has is used as it is; any other is added to
   wanted.txt, as `caracole add` adds it, and synced: a song you
   [removed](#caracole-remove) comes back that way, as new.
2. **Match**, against the offline index, for this song alone.
3. **The sheet.** The LaCuerda sheet you picked (`--lacuerda`), first: its
   version's page, one request (and the artist's page when LaCuerda's index
   doesn't name the song's best version). Else, or when LaCuerda can't give it
   now, one Ultimate Guitar page lists every version of the song's chords with
   its rating, and the best rated is kept at once: one or two requests. The
   stage then says first why your pick isn't the sheet (`LaCuerda failed (…)`,
   a cooldown, `the Ultimate Guitar tab you pinned is kept over your LaCuerda
   pick`), then what Ultimate Guitar gave.
   Without one there, LaCuerda's, for a song LaCuerda would be asked about
   tonight. From here on the sheet is readable.
4. **The PDF**, as `caracole render` makes it, for this song alone: another
   song's failed PDF, or one waiting for a CJK font, isn't this one's.
5. **The lyrics**, from LRCLIB.
6. **Ultimate Guitar again**, as the nightly run would: the top sheets are
   scored against the lyrics, and a more complete one replaces the first;
   then the guitar parts and the text tab.
7. **LaCuerda**, for a Spanish song without a complete sheet, and
   **gtptabs.com**, for a Guitar Pro file, from the index the nightly run
   keeps.
8. **The pages**: `_todo.md` and `index.html`, with the PDF made again if the
   sheet changed, and MuseScore's pages matched from its local index.
9. **The songbooks it is in**: each songbook of songbooks.toml that lists the
   song is made again, as `caracole songbook render NAME` does (one whose
   songs and settings did not change is left as it is: "up to date"), then
   `_todo.md` and `index.html` once more, so the library page's Songbooks tab
   has the songbook's files as they are now. A songbook that does not list the
   song is left alone. On `caracole serve`, once the lookup is over (Fetch now,
   Fetch it now, a set list's Get it), the Songbooks tab is drawn again: the
   song shows there with its sheet, and no Get it. A songbooks.toml that cannot
   be read is said on that line and stops nothing: the lookup still exits 0.

It keeps the interactive pace ([Two paces](#configure)): about a second
between two requests to a site, six requests to a site at most, and sixty an
hour for every lookup together. What it leaves undone, the nightly run does.
A site cooling down after a block is left alone; a block, a spent budget or a
site's error leaves the song to the nightly run, never not found, and exits 0.
When that cuts Ultimate Guitar short, a matched song is marked to fetch, as
`caracole fetch --song` marks it, so the nightly run fetches it even if it was
fetched before.
A nightly run that holds caracole's lock lets the lookup go first at its next
pause ([One caracole at a time](#one-step-at-a-time)).

Options:

- `--print` prints the sheet itself as soon as it is kept, and again when a
  better one replaces it.
- `--ug ARTIST-KEY/SONG-KEY` is the Ultimate Guitar song to use, as
  `caracole search` shows it (`stone-temple-pilots/creep`): it is recorded
  under `[match]` in overrides.toml, so the matcher never asks you about it.
- `--tab URL` is the tab to use, its page's address or its id: it is
  recorded under `[pin]`, in place of the song's pin of the same kind (a
  chords sheet, a text tab, a Guitar Pro or Power Tab file, by the offline
  index), and beside its pins of the other kinds: a Guitar Pro version picked
  after a chords sheet keeps the sheet you chose.
- `--lacuerda URL` is the LaCuerda song to keep the sheet of, its page's
  address (its best Letra y Acordes version) or a version's
  (`https://acordes.lacuerda.net/estopa/como_camaron-2.shtml`): it is recorded
  under `[lacuerda]`, and kept as the sheet whatever the song's language or
  its coverage of the lyrics; Ultimate Guitar's sheets never replace it, and
  the song gets Ultimate Guitar's guitar parts all the same. A `[pin]` of an
  Ultimate Guitar sheet wins over it.
- `--album ALBUM` and `--duration M:SS`, for a song new to the library, as in
  `caracole add`.
- `--progress` adds a JSON line per stage, which `caracole serve` reads.
- `--no-songbooks` leaves the songbooks that list the song as they are (by
  default the lookup makes them again). The page's Get the missing songs now
  uses it for each song and makes the songbook once, after them all.

A song ignored in overrides.toml, or one wanted.txt can't hold, is not looked
up, and exits 1. A song the matcher isn't sure of gets everything but its
Ultimate Guitar sheet: pick its UG song with `--ug`, with Get it on the page
`caracole serve` serves, or with `caracole review`.

### caracole remove

`caracole remove "ARTIST - TITLE" [--yes]` takes a song out of caracole for
good: nothing brings it back until you ask for it again. Name the song as the
to-do page and `caracole search` do. It says what goes and what stays, and asks:

    $ caracole remove "Radiohead - Creep"
    Remove Radiohead - Creep from caracole?
    It takes:
      - its line in wanted.txt (line 3)
      - 6 files caracole wrote in Radiohead/Creep/: info.json, lyrics.txt, sheet.cho, sheet.json, sheet.pdf, sheet.txt
      - its record in caracole's database: its match, its lyrics and 4 versions seen of it
    It leaves:
      - Radiohead/Creep/notes.md: caracole didn't write it
    Spotify still lists it: caracole leaves it out from now on, unless you like it or add it to a playlist again.
    caracole won't bring it back, from wanted.txt, Spotify or the nightly run, until you ask for it again: caracole add, the web page's request form, or a line in wanted.txt.
    Remove it? [y/N]: y
    Removed Radiohead - Creep: deleted 6 files, took 1 line out of wanted.txt.

`--yes` (`-y`) doesn't ask. Without it and without an answer (from a script,
say), nothing is removed and it exits 1.

- **What goes.** The song's lines in wanted.txt, every line that names it,
  the rest of the file kept byte for byte, comments included. The files
  caracole wrote in the song's folder: the sheets, tabs and Guitar Pro files
  it keeps (`sheet.txt`, `sheet.json`, `version-<tab>.txt`, `tab.txt`, `guitar-1.gp5`, the scores
  it filed from `_inbox/`…), the `.cho` files and PDFs it made from them (the
  `sheet (G Dorian, capo 0).pdf` exports of `caracole render --version` too),
  every file of a version kept beside the sheet (`version-<tab>.txt`,
  `.json`, and the viewer `version-<tab>.html` a render wrote, a version's
  page the last fetch let go too), `lyrics.txt` and `lyrics.lrc` when they are LRCLIB's, and `info.json`.
  Then the folder, and the artist's folder, once empty. Syncthing then
  deletes them on every device. And the song's record: its match, its
  versions, its lyrics and what caracole remembered about it, and the audio
  caracole took from YouTube for it (see [Audio from YouTube](#audio-from-youtube)),
  from caracole's cache.
- **What stays.** Any other file in the folder, a file of yours, a folder, a
  symbolic link (never followed), stays where it is, and the command names
  it; so does a `sheet.pdf` or `lyrics.txt` you put in a folder where caracole
  made none. Nothing outside the song's folder is deleted. The audio you
  bought, in Music/, is never touched: the song lets go of it. overrides.toml
  keeps its entries for the song, which apply again if you ask for it again.
  So does songbooks.toml: a [songbook](#songbooks) with the song lists it as
  missing, "not in the library", until you take it out (`caracole songbook
  remove`, or × on `caracole serve`) or ask for the song again; its files
  keep the song's sheet until the next render makes them again.
- **It stays out.** caracole remembers the song as removed, so neither the
  nightly run nor `caracole sync` brings it back: not from wanted.txt (its
  line is gone), not from your Liked Songs or a playlist that still lists it
  (the sync says `Spotify 120 songs, 0 new, 1 removed song left out`), and the
  to-do page no longer suggests it from your top tracks. `_todo.md`,
  `index.html` and `caracole search` no longer list it.
- **Until you ask again.** `caracole add`, the web page's request form, or a
  line for it that you write in wanted.txt brings it back as a new song, and
  the next run looks for it from scratch. So does a Spotify track you like, or
  add to a playlist, after the removal. A device that syncs back an old copy
  of wanted.txt with the line in it brings it back too.
- A wanted.txt caracole can't read (a symbolic link, say) stops the removal
  before anything goes: the line it couldn't take out would bring the song
  back.

`caracole remove --list` lists the songs removed, the latest first, and when.
`caracole remove` on a song removed already says when it was, and how to
bring it back. Like `caracole review`, it asks before it takes caracole's lock,
so the nightly run never waits for your answer; `--list` only reads. On the
web page, each song's **Remove…**, under its line's "⋯", does the same, right
there on its line: it says in one line what goes, counts down five seconds with Undo, then
removes the song ([caracole serve](#caracole-serve)).

### Names in other scripts

Write a song as you know it, in its own script or in Latin letters:
`宋冬野 - 斑马斑马`, `宋冬野 - 斑馬斑馬` and `Song Dongye - Banma Banma` all
work. Caracole compares Chinese as pinyin too, and Traditional characters as
Simplified ones.

Ultimate Guitar often writes a non-Latin name in two scripts at once: the
original, a romanization and a translation, in any order in brackets or after
" / " or " - ", or, with nothing between them, the original first and the rest
after a space. 宋冬野's artist page calls him "Song Dongye (宋冬野)", and the song
"斑马 斑马 Banma Banma Zebra Zebra". Each part counts as a name of its own when
caracole compares UG's names with yours, so `宋冬野 - 斑马斑马` finds that song
there, and so would "Banma Banma", "Ban Ma Ban Ma" or "Zebra Zebra".

Japanese, Korean and Cyrillic names come in the same patterns ("打上花火 (Uchiage
Hanabi)", "봄날 (Spring Day)", "Кино (Kino)"). Caracole doesn't romanize those
to compare them: they meet on the part in their own script, or on the Latin
one. It reads Hangul and kana only to tell where a romanization ends and a
translation starts, as it does for Chinese with pinyin in any reading of a
character: "봄날 Bomnal Spring Day" is "Bomnal" and "Spring Day", "夜に駆ける Yoru ni
Kakeru Racing Into The Night" is "Yoru ni Kakeru" and "Racing Into The Night",
and "重来 Chong Lai Start Over" is "Chong Lai" and "Start Over".

The same goes wherever caracole meets a name it didn't write: a song you
wrote in two scripts against the index (UG's sitemaps write names in Latin
letters only, so `DAOKO - 打上花火 (Uchiage Hanabi)` meets
`daoko/uchiage-hanabi`), a purchase tagged that way, a Guitar Pro download
UG named so, and a search of the artist pages caracole has read (斑马, Banma
and 宋冬野 all find "斑马 斑马 Banma Banma Zebra Zebra").

UG also lists some of these titles in Latin letters alone, the romanization
with its translation in brackets ("Hong Dou (Red Bean)" for 王菲's 红豆): on an
artist page, a title in Latin letters counts by what is outside its brackets
too, so 红豆 finds it there.

A part that only names a version or a part, such as "Live", "Acoustic",
"Remix" or "Intro", or that is a number or a single Latin letter, never makes
a match on its own. Two Latin letters do ("IU (아이유)" is IU), and so does an
original in any script, however short ("Ты (Ty)" is Ты). Another song of the
artist never stands in for yours either: 董小姐 is no 斑马斑马, in any script, and
Latin before the original, or glued to it, is part of the title: "Baby 对不起"
and "我的Baby" are neither 对不起 nor "Baby". A name with two non-Latin parts, as a
duet's "Joey Yung (容祖儿) & Eason Chan (陈奕迅)", is taken whole: it is neither
singer. Nor is an artist a name features part of it, bracketed in any width or
not: "Ma Di (feat. 宋冬野)" is Ma Di's, never 宋冬野's, and "南山南（feat. 宋冬野）" is 南山南.
A tab page of such a pair teaches caracole no artist page for either of them,
as UG may give the pair a page of its own.

### caracole sync

`caracole sync` reads wanted.txt, then Spotify when it's set up, and prints a
summary such as `wanted.txt 3 songs, 1 new; Spotify off`, followed by each
problem. Then it rewrites `_todo.md` and `index.html`. The nightly run starts
with the same sync.

`caracole sync`, `caracole add` and `caracole search --add` never fail because of
the pages: with an overrides.toml that can't be read, or a page that can't be
written, they still add and sync your songs and exit 0. They warn, and leave
the pages as they were.

### Spotify (optional)

Your Liked Songs and the playlists you name join wanted.txt as sources. A
dedicated "Learn" playlist that you add to from your phone works best. A song
that comes from several sources, or a remaster next to the original, is one
song in the library. Where they disagree, the album and the duration come
from your wanted.txt line, and Spotify fills in what the line leaves out.
Each sync takes what the sources say that night, so a change Spotify makes
to a track's album or duration reaches the song, unless your line says
otherwise.

1. Create an app at developer.spotify.com. In Development Mode the app's owner
   needs Spotify Premium. Add the redirect URI `http://127.0.0.1:8888/callback`
   exactly: `localhost` is rejected.
2. Put its `client_id` and your `playlists` under `[spotify]`, and the client
   secret where "Secrets" above says.
3. Run `caracole auth spotify`. It prints an address: open it in a browser and
   allow access. The browser is then sent to `http://127.0.0.1:8888/callback?code=…`,
   which won't load; that's expected. Copy that whole address and paste it
   back. The token is saved in the state folder.
4. Run `caracole sync`, or leave it to the nightly run.

Without a client id, Spotify is skipped silently, and `caracole auth spotify`
prints these steps instead. Spotify never fails a sync or a run. With a client
id but no client secret, the sync says that Spotify isn't fully set up and
where the secret goes; authorizing can't help until it is there. When the
token is missing or has expired, the run carries on with wanted.txt, the to-do
page says that Spotify needs authorization, and ntfy tells you once. Spotify
expires the refresh token about six months after you authorize: run
`caracole auth spotify` again then.

Development Mode reads only playlists you own or collaborate on, so
editorial playlists don't work. A playlist that can't be read is reported.

A song you removed with `caracole remove` stays out while Spotify still lists
it, and the summary counts it (`1 removed song left out`). Like it, or add it
to a playlist, again after the removal, and it comes back.

When Spotify says caracole is asking too often (HTTP 429), a wait of up to 30
seconds is waited out a few times; a longer one isn't. The sync then stops
asking, keeps the songs it has read, and doesn't ask Spotify again until the
wait is over, so an app over its limits isn't kept there.

## The first run

With some songs listed:

    caracole index build       # once: Ultimate Guitar's sitemaps into a local index
    caracole match --dry-run   # how every song matches, saving nothing
    caracole run               # one nightly run, now

### caracole index build

Caracole never searches Ultimate Guitar, whose robots.txt disallows its search
page. It reads the sitemaps UG publishes for crawlers instead, and keeps a
local index of every chords, tabs, Guitar Pro and Power Tab page: about 1.6
million. `caracole index build` reads the sitemap index and its 41 tab sitemaps,
one request at a time, 10–20 seconds apart: about 42 requests, 70 MB and 10
minutes. Its budget is 100 requests, more than a night's, so one build is
enough. A block or a spent budget keeps the sitemaps read so far, and the next
refresh reads the rest. Until then the index is incomplete, and no song is
matched against it: a song in a sitemap not read yet isn't missing from UG.

The index leaves out the tabs whose page robots.txt closes to bots (UG files
the band Track's tabs under `/tab/track/`, which it closes, and there are a
few more), so no song is matched to a page caracole may not read. A build or a
refresh also drops any such tab indexed earlier.

**What it prints.** Before the first tab sitemap, the build says what it
indexes, how many tab sitemaps the sitemap index lists, how many it must
download and how many it has already (in the HTTP cache, or indexed: those are
asked for again with a conditional request and skipped when unchanged), about
how many tab URLs that is, and how long the pacing makes it. Then a line per
sitemap: its URLs, the rows indexed (and how many are new, when not all), the
bare ids, the tabs of types the index doesn't keep, those robots.txt closes,
and how many sitemaps are left with the time they should take. That estimate
starts from the pacing and moves to the pace measured. Last, what the index
holds and the state it is in. A small example, five sitemaps where UG lists 41:

    Indexing Ultimate Guitar's tab pages as rows of artist, title and type, to match your songs offline.
    Only the sitemaps UG publishes for search engines are read: no tab itself is downloaded.
    Reading the sitemap index...
    The sitemap index lists 5 tab sitemaps (sitemap1.xml to sitemap4.xml and sitemap_last.xml): 5 to download.
    About 250,000 tab URLs (up to 50,000 a sitemap). 5 requests, 10-20 s apart: about 1 min.
    [1/5] sitemap1.xml  2,000 tabs: 1,574 indexed, 221 bare ids, 195 of other types, 10 closed by robots.txt  4 left, about 1 min
    [2/5] sitemap2.xml  2,000 tabs: 1,591 indexed, 201 bare ids, 203 of other types, 5 closed by robots.txt  3 left, about 50 s
    [3/5] sitemap3.xml  2,000 tabs: 1,595 indexed, 204 bare ids, 199 of other types, 2 closed by robots.txt  2 left, about 30 s
    [4/5] sitemap4.xml  2,000 tabs: 1,577 indexed, 215 bare ids, 200 of other types, 8 closed by robots.txt  1 left, about 15 s
    [5/5] sitemap_last.xml  600 tabs: 495 indexed, 58 bare ids, 47 of other types
    Index built: 5 sitemaps read; 6,832 new tabs.
      Indexed     6,832 tabs: chords 3,225, tabs 2,483, guitar-pro 772, power 352
      Artists     1,488
      Bare ids    899 of 8,600 tab URLs (10.5%): with no artist or title in the URL, only artist pages lead to them
      Left out    844 of other types (bass 469, ukulele 224, drums 76, video 75)
      robots.txt  25 tabs left out: robots.txt closes their pages
      Requests    6 of a budget of 100
      Duration    1 min 17 s
    The index is complete: `caracole match` can now match your songs against it, and the nightly run keeps it up to date.

On a terminal the sitemap lines share one line, rewritten in place, and the
index's state is in color. In the journal, or piped, each sitemap is a line of
its own, with no carriage return and no color; `NO_COLOR` turns color off on a
terminal too. The bare-id, left-out and robots.txt counts cover the sitemaps
indexed since caracole counts them, so after an upgrade they appear once a
build has read the sitemaps again.

**When it stops part-way**, on Ctrl-C (which exits 130), a block, a cooldown
or a spent budget (which exit 0), or another error (which exits 1), it says
why, sums up what it read, and says how to resume and where. Blocked at the
13th of 41 sitemaps (small ones, in this example):

    [12/41] sitemap12.xml  200 tabs: 159 indexed, 21 bare ids, 20 of other types  29 left, about 8 min
    Ultimate Guitar blocked caracole (ug: 403: https://www.ultimate-guitar.com/sitemap13.xml: HTTP 403). No more requests to it until 2026-10-20 22:54 UTC (block #1); the sitemaps read so far are kept.
    Index build stopped after 12 of 41 sitemaps; 1,891 new tabs.
      ...
      Requests    14 of a budget of 100
      Duration    3 min 26 s
    The index is partial: 12 of 41 tab sitemaps indexed, so no song is matched against it yet.
    To resume, run `caracole index refresh` after 2026-10-20 22:54 UTC: it reads the 29 sitemaps left, sitemap13.xml to sitemap40.xml and sitemap_last.xml (30 requests, about 7 min). The nightly run does the same.

**`caracole index build --from DIR`** builds the index offline, from sitemap
files you already have: `sitemap1.xml` to `sitemap40.xml` and
`sitemap_last.xml`, gzipped or not. It sends no requests. The 41 files take
about 22 seconds and make a 303 MB database. It prints the same, with the
files it found in place of the sitemap index. A file that isn't a sitemap
stops it, exiting 1: the files before it are kept, and running it again reads
every file again.

About a tenth of UG's tabs are listed by a bare id (`/tab/1234567`, with no
artist or song in the address), and the index can't see those. They include
every tab of an artist with an accented or non-Latin name, such as Joaquín
Sabina, Maná or 宋冬野. The to-do page asks you for those artists' pages once,
or for any of their tab pages (see [the to-do page](#the-to-do-page)).

**`caracole index refresh`** re-reads `sitemap_last`, the highest-numbered
sitemap and any numbered one not indexed yet, whether new or left by a stopped
build. These are conditional requests, which usually answer "unchanged". A
new tab for a song you want marks that song to be fetched again. The nightly
run does this; the command does it by hand. In the journal or piped, it
prints a line for each sitemap that changed, then one line for it all (on a
terminal, each sitemap shows on the live line while it is read, and only that
last line stays):

    Checking the sitemap index for new tabs...
    [2/2] sitemap_last.xml  900 tabs: 726 indexed (231 new), 88 bare ids, 85 of other types, 1 closed by robots.txt
    Index refreshed: 1 of 2 sitemaps changed (sitemap_last.xml): +231 tabs, no song to refetch. 3 requests, 45 s.

When it reads sitemaps a stopped build left, it first says which, and how long
they should take; once it has read them all, its last line ends with "the index
is now complete". Stopped part-way, it says so as the build does, with how to
resume.

**`caracole index stats`** prints the number of tabs of each type, of artists
and of sitemaps, the newest tab id, and when the index was built and last
refreshed.

### caracole match --dry-run

Matching is local: no requests, and it takes seconds. `caracole match` matches
every song against the index and prints one line per song, then the totals:

    accept     100.0  exact         Radiohead - Creep → radiohead/creep  CHANGED unmatched → accept
    review      88.9  fuzzy_title   Radio Head - Crep → radiohead/creep  CHANGED unmatched → review
    not_found      -  -             宋冬野 - 斑马斑马 → -  CHANGED unmatched → not_found
    3 songs: 1 accept, 1 review, 1 not_found; 3 changed. Dry run: nothing was saved.

The columns are the decision, the score, the step that decided it, and the
song with the UG song it matched. `CHANGED` marks a decision, or a UG song,
that differs from the saved one. `--dry-run` saves nothing, so you can try
other thresholds (`[match]` in caracole.toml) or new overrides on your whole
library in seconds. Without it, `caracole match` saves the decisions and
rewrites `_todo.md` and `index.html`. On an incomplete index it saves nothing,
exits 1 and says why; `--dry-run` still shows what matches so far.

- **accept**: a score of 90 or more, with the next different title at least 8
  points behind.
- **review**: any other score of 75 or more, any match on the title alone
  (usually a cover), and any match on a name that isn't quite UG's (step 4
  below). You settle these on the to-do page or with `caracole review`.
- **not_found**: below 75. A not-found song is matched again every night, so
  a new tab finds it.
- **pinned** and **ignored** come from overrides.toml.

How a song is matched, in order:

1. Your overrides: `[ignore]`, then `[pin]`, then `[match]`.
2. The title under each of the song's artists: as `[alias]` names them, then
   by their own names, also without hyphens (`AC/DC` meets `acdc`), with or
   without a leading Spanish article (Enanitos Verdes meets
   `los-enanitos-verdes`) and, for a Chinese name, in pinyin (宋冬野 meets
   `song-dongye`). An exact title wins, else the closest one.
3. The nearest other artist name, at 90 or more, then step 2 under it.
4. Names that aren't quite UG's, when steps 2 and 3 accept nothing. Each is
   always a review, never an accept, and joins a review's candidates; the
   step names them:
   - `word_title`: a title of the song's artist that holds yours word for
     word, or that yours holds: `Los Lobos - Canción del Mariachi` meets
     `los-lobos/cancion-del-mariachi-morena-de-mi-corazon`. It scores 80 to
     90, by how much of the longer title the shorter one covers. A word that
     names nothing on its own, such as "Live", never counts.
   - `typo_artist`: for an artist the index knows by none of their names, the
     artists whose names are a letter or two away, then step 2 under them:
     `Coldplya - Yellow` meets `coldplay/yellow`. One letter for a name of
     four to seven letters, two from eight, none for a shorter name; two
     letters swapped count as one. Of those, the five nearest, then those
     with the most tabs, come first: `Tolo` meets `tool` before `colo`,
     `lolo`, `molo`, `polo` and `solo`.
   - `catch_all`: UG files the songs of musicals, films, TV shows, games and
     cartoons under catch-all artists (`misc-musicals`, `misc-soundtrack`,
     `misc-television`, `misc-computer-games`, `misc-cartoons`), with the
     show's name inside the title. `epic - I'm not sorry for loving you`
     meets `misc-musicals/epic-the-musical-not-sorry-for-loving-you`, scored
     94: a catch-all title that holds the artist's name is scored on what is
     left of it, less words such as "the musical" next to the name. One that
     doesn't hold it but ends in your title of two words or more scores 90,
     for a show's song your source credits to its composer. `misc-originals`
     and `misc-unsigned-bands` file a song as "performer - title"
     (`misc-originals/ray-porter-red-sarah`): there the artist's name must
     start the title, and no ending counts. The other `misc-…` artists
     (`misc-praise-songs`, `misc-traditional`, `misc-christmas`,
     `misc-children`) file the bare title, which step 5 finds;
     `misc-mashups` titles hold two songs, neither the one you want.
5. The title alone, across all artists: always a review.

A review keeps its five best candidates, but the best `catch_all` and the
best `typo_artist` candidate are always among them, in place of the last of
the others: `Idina Menzel - Let It Go` lists covers of "Let It Go" at 100,
and `misc-cartoons/frozen-let-it-go` (90) too.

At steps 2 to 5, the matcher passes over the UG songs you rejected for the
song under `[reject]`, and so does the fetch on the artist's UG page, so they
are never offered again; other candidates still can be.

Matching never asks a search engine. A fallback through an official search
API with your own key (Brave Search API, or a SearXNG of your own) is
designed, and not built: [web-search.md](web-search.md) has the
configuration it would take, and why it waits.

### caracole run

`caracole run` is what the nightly timer starts. Its steps, in order:

1. **sync**: wanted.txt, then Spotify.
2. **icons**: fetch the icon of each site the library has something from, once
   (see [Where each file came from](#where-each-file-came-from)). It comes
   before the steps that can spend a site's budget.
3. **index**: refresh the index, and mark the songs that have new tabs.
4. **match**: match every song again, locally.
5. **lyrics**: ask LRCLIB for the songs that have no lyrics yet.
6. **fetch**: rank and keep Ultimate Guitar sheets and guitar parts.
7. **lacuerda**: look on LaCuerda for Spanish songs without a complete sheet,
   then read LaCuerda's listings of every artist into a local index, for
   searches, with what the sheets left of its budget (once the library has a
   song: an empty one asks no site).
8. **scan**: link purchases in Music/, and file Guitar Pro downloads.
9. **gtptabs**: download a Guitar Pro file from gtptabs.com for each song that
   has none. It comes after the scan, so a file you dropped into `_inbox/` is
   filed first, and that song gets none from gtptabs.com. As for the other
   sites, the summary counts the songs an error left for the next run on the
   cause's line; sitemaps it couldn't read get a line of their own.
10. **musescore**: read MuseScore's song sitemaps into a local index, for the
    to-do page's links to its pages. It downloads nothing.
11. **youtube**: take the audio of a few songs no human sheet was found for from
    YouTube, for auto-chords (see [Audio from YouTube](#audio-from-youtube)).
    Skipped in a caracole without auto-chords.
12. **render**: write ChordPro files and PDFs.
13. **todo**: rewrite `_todo.md` and `index.html`.

Every step runs even when an earlier one failed, so the to-do page is always
rewritten. Until the index is built, the index and match steps are skipped;
after a build that stopped part-way, the match step is skipped until the index
step's refresh has read the rest.

The run ends with a short summary, and sends the same words to ntfy. On a first
night, with one song in wanted.txt, the index not built yet and LRCLIB
overloaded, it reads:

    First, build the index once: caracole index build (about 10 minutes).
    Until then, no song is matched or looked for on Ultimate Guitar.

    Songs: 1 in wanted.txt, 1 new.
    LaCuerda: 30 pages of artists read.

    1 thing on your to-do page needs you: /home/you/Tabs/_todo.md
    LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.
    Requests: Ultimate Guitar 0 of 60, LRCLIB 2 of 200, LaCuerda 30 of 30 (used up: the rest waits for the next run).
    Took 3 s.

(gtptabs.com and MuseScore were turned off that night; when they're on, as
they are by default, the Requests line lists them too. LaCuerda's requests are
its listings of every artist, about 200 pages: the first nights read them 30
a night, each going on where the last stopped.)

- **First** comes the one thing that unblocks the rest, when there is one, said
  once however many steps wait for it: build or finish the index, fix
  overrides.toml or wanted.txt, authorize Spotify again.
- **Then a line for each step that did something**, its counts without the
  zeros ("Lyrics: 3 found, 1 missing."). A step with nothing to do has none.
- **Last**: how many things on the to-do page need you, and where it is; the
  problems, a site at a time, with its cooldown and until when, and the songs
  one cause left for the next run counted on one line; the requests against
  each site's budget; and how long the run took.

A block's ntfy message is that block's line of the summary. The summary is
all `caracole run` prints on stdout; on a terminal, what needs you and what
went wrong are coloured. Its log, on stderr, shows only the problems the
summary doesn't already say: nothing, that night above. `caracole -v run`
adds a line per step and per request there, and `caracole -q run` prints only
the lines that need you or went wrong. A site turned off
(`[providers.gtptabs] enabled = false`, say) has no line; `caracole -v run`
shows its step as skipped.

**The budget.** A run sends Ultimate Guitar at most 60 requests, the index
refresh included, 10–20 seconds apart and one at a time. It settles the sheet
of every waiting song first, newest songs first: a few requests a song, for
its versions pages and then up to three sheets scored against the lyrics. What
is left goes to guitar parts, about a page per type (Guitar Pro, Power Tab,
tabs) a song. Before sheets came first, a live run spent 8–12 requests a song.
A long list therefore fills in over a few nights, and a song the budget cut
off half-way resumes from the cache the next night.

gtptabs.com gets at most 20 requests a run, 10–20 seconds apart. The first
run spends seven on its sitemap index and six sitemaps, and reads them again
after 30 days, when each unchanged one costs a request. Then each song costs
its artist's page, which serves every song by that artist for 30 days, and a
download for its file.

MuseScore gets at most 10 requests a run, 10–20 seconds apart, all for its song
sitemaps: an index and 18 files of about 40,000 song pages each, read over two
nights, the second going on where the first stopped, then again each month with
conditional requests. They name each song's title, never its artist. When
caracole first asked for them, on 19 October 2026, MuseScore's Cloudflare
protection answered with a challenge: caracole takes that as a block, like a
403, and lists what it read before, if anything (see
[the to-do page](#the-to-do-page)).

YouTube gets at most 6 yt-dlp runs a night, 15–30 seconds apart: a search and a
download a song, so three songs. Inside each run yt-dlp waits 2 seconds between
its own requests, and 10–20 seconds before a download.

**Errors are never misses.** A block (HTTP 403, 429 or a challenge page)
stops that site for the rest of the run and sends one ntfy message, which
says until when caracole leaves the site alone. That cooldown counts from the
start of the blocked run: 24 hours, doubled for each further block in a row,
plus 2 hours, so 26 hours after a first block, 50 after a second and 98 after
a third. However late the timer starts them, the nightly runs then leave that
site out for the next night after a first block, the next two after a second,
and the next four after a third. A block in a command counts the same way,
from when the command started. A run or a command the site answers without a
block starts the count again. Neither a block, nor a spent budget, nor any
other error from a site marks a song not found or its lyrics missing: the
song waits for the next run. An answer that won't read but was cached all the
same (a maintenance notice served as a page, say) is asked for once more,
past the cache, by the next run that needs it: from UG, LaCuerda,
gtptabs.com and LRCLIB alike. Caracole never works around a block: no proxies,
no retries from elsewhere. A tab page UG keeps serving without its data is
asked for again after 7 days, then twice as long each time, up to 90 days;
meanwhile the song is filled from its other versions.

Nor does caracole ask for a page robots.txt closes to bots, or follow a
redirect to one: UG's search, download and print pages, and a few tab pages
(`/tab/track/…`); gtptabs.com's search, its Russian copy of every page
(`/ru/`) and each artist's "Download all" archive (`/storage/`); MuseScore's
search, downloads, oEmbed endpoint and `/api/jmuse`, which serves a score's
pages, audio and MIDI. A tab at such a page, or at a page UG redirects to one, is
no candidate, and neither is a link in UG's data that isn't a valid address:
the song is filled from its other versions.

**Exit status.**

| Status | When |
|---|---|
| 0 | the run did what it could: a block, a cooldown, a spent budget or a site's errors included, as the songs wait for the next run |
| 1 | a bug, after all the steps have run, so that systemd's `OnFailure` can tell you: the summary says which step failed, and the log has its traceback behind a one-line summary; or an overrides.toml caracole can't read; or a database it can't open |
| 2 | a caracole.toml it can't read, or a database a newer caracole migrated |

A broken overrides.toml stops the run before its first step (with an ntfy
message, which is the summary leading with the error), because every step
reads it. The to-do page is still rewritten, leading with the error, and
index.html is left as it was.

## One step at a time

Like `caracole sync`, `caracole index refresh` and `caracole match` above, each
step of the run has a command of its own, with the run's budgets, cooldowns
and cache.

- **`caracole lyrics`** asks LRCLIB for the lyrics of every song that has none
  yet, and again for misses older than 30 days. It writes `lyrics.txt`, plus
  `lyrics.lrc` when LRCLIB has timed lyrics. A song whose lookup failed stays
  pending. A cooldown, a block or a spent budget exits 0.
- **`caracole fetch [--song "ARTIST - TITLE"]`** first scores the sheets kept
  before their lyrics arrived, with no request, as the nightly run does. Then
  it fetches and ranks the UG versions of the songs that need it: new
  matches, songs with new tabs or a changed `[block]`, songs a run left
  half-done, and songs whose kept sheet or tab the library lost (see
  [the library folder](#the-library-folder)). A song whose UG match was
  undone (by `[reject]`, say) loses the sheet, the tab and the versions that
  match kept. The other versions a fetch scores for the sheet are kept beside
  it, with no request more: `version-<tab>.txt` and `version-<tab>.json` (see
  [the library folder](#the-library-folder)). They follow the ranking: a
  version that leaves the top `scored_sheets` loses its files at the song's
  next fetch, as does one UG took down or one you `[block]`, and one that
  enters is written from the page that fetch scored. A version whose page
  can't be read keeps its files until it can. A pinned sheet keeps the top
  versions by rating beside it, read from the cache alone. A version whose
  text is the sheet's very text gets no files: the sheet stands for it.
  Songs the index can't settle are looked up on their artist's UG page, when
  it is known, at most once in 30 days: songs not found, songs reviewed on
  their title alone (only other artists' songs of it) or on names that
  aren't quite UG's (steps 4 and 5 of the matcher, above), songs found on that
  page before, and songs whose chords the index can't offer (bare ids, or
  pages robots.txt closes). Every list of an artist page it reads, from UG or
  from the cache, is kept for searches, bare ids with their names: a list read
  to its end replaces what that kind's list gave before (a tab UG took down
  goes), a list the page cap cut short only adds, and an artist page UG answers
  404 for loses its tabs. Per song it prints what it kept, as
  `Artist - Title: sheet 101 · Guitar Pro 301, 303 · tab 402 (3 requests)`,
  or `nothing kept`, then the totals. `--song` fetches that one song now, even
  when nothing about it changed; the song must be in the library and matched,
  or not found or reviewed on its title alone or on names that aren't quite
  UG's, with its artist page known. It
  prints that song's line alone, without the count (`Artist - Title: sheet
  101`), or why nothing came: `not fetched (the error); it waits for the next
  run`, or that the budget was spent first, or UG's cooldown. A `--song` cut
  short that way marks a matched song to fetch, so the next run fetches it
  even if it was fetched before and nothing changed; a song looked up on its
  artist's page lately waits for that page's next reading instead, and the
  line says to ask for it again later. `-v` adds the requests, the count and
  the totals. A cooldown, a block or a spent budget exits 0.
- **`caracole lacuerda`** looks on LaCuerda for Spanish songs (judged by their
  lyrics, or by their title until there are lyrics) that have no complete
  sheet, at most once in 30 days per song. Like `caracole fetch`, it first
  scores the sheets kept before their lyrics arrived. One artist page serves
  every song by that artist. LaCuerda's sheet is kept when there is no sheet
  yet, when it is complete and the kept one isn't, or when neither is
  complete and it covers more of the lyrics, but never in place of a sheet you
  pinned. A LaCuerda sheet the library lost is written again at the next
  pass, whatever the date, usually from the cache. An artist LaCuerda doesn't
  have gets an almost empty page, with HTTP 200; caracole reads that as "not on
  LaCuerda". The artist's page is asked for first under the slug LaCuerda's
  own listings give the name, when its artist index has it (Enanitos Verdes
  are `enanitos` there), then under slugs made from the name; the songs of
  every artist page caracole reads go into that index. A cooldown, a block or
  a spent budget exits 0.

  **`caracole lacuerda --index`** reads LaCuerda's listings of every artist
  into that local index instead, as the nightly lacuerda step does with what
  its sheets left of the budget. LaCuerda has no sitemap: `/tabs/e/` and the
  other initials show only their 50 most popular artists, and every artist is
  on `/tabs/e/index0.html`, `index100.html`…, 100 a page (E has 7 pages and 639
  artists; the whole index is about 200 pages). Each initial's first page says
  which pages it has. The index holds each artist's name as LaCuerda writes
  it, the slug of their page and the songs it counts, and the songs of the
  artist pages caracole has read, from its cache, with no request of their
  own. The listings are read when they never all were, and again after 30 days
  with conditional requests (a page unchanged since costs a request, answered
  304); a spent budget leaves the rest for the next run, which goes on where
  this one stopped. It prints `Index: 30 pages of artists read.` and
  `LaCuerda: 2950 artists and 140 songs in the index.`, or
  `LaCuerda's artist index is up to date: 19500 artists and 140 songs.` when
  nothing was due. A page that won't parse, or any other error, leaves the
  index as it was and counts as an error: an error never empties an initial.
  A cooldown, a block or a spent budget exits 0. The lacuerda step reads the
  artists' slugs from it, and `caracole search`, the served library page's
  search and the Look up page suggest its artists and songs (see [caracole search](#caracole-search)).

  **`caracole lacuerda --artist NAME`** reads one artist's page into the index
  now, so that their songs are there to search: NAME is their name, or the
  slug of their page as `caracole search` prints it (`joaquin_sabina`), tried
  first when it is written as one. It asks at the lookup pace, as
  `caracole get` does, within a lookup's budgets: a request for each slug
  tried until one answers (one for a slug the listings give; a name they don't
  list may take one per spelling, "the" or "y" kept or not), and none when the
  page is in the cache (30 days). Its last line starts with what LaCuerda
  answered, which caracole serve's request line shows: `Read: LaCuerda's page
  of Joaquín Sabina lists 241 songs, in the index now.`, `Not found: LaCuerda
  has no artist page for NAME.`, or `Not read: …` for a cooldown, a block, a
  spent budget or an error (`Not read: LaCuerda failed (…); nothing changed:
  try again later.`), all of which exit 0, nothing changed. It can't go with
  `--index` (exit 2). An artist's Songs on the page `caracole serve` serves
  runs it, and so does Read LaCuerda's page for a name its listings haven't
  reached yet.
- **`caracole gtptabs`** downloads a Guitar Pro file from gtptabs.com for each
  song that has no Guitar Pro or Power Tab file, newest songs first. It reads
  gtptabs.com's sitemaps into a local index when it never has, or last did 30
  days ago, and finds each song's artist there: under the artist's name, or
  as the site files people, last name first (`john-elton`) and "The" last
  (`beatles-the`). It never uses the site's search. The artist's page, cached
  for 30 days, lists the song's uploads, newer ones than the 2015 sitemaps
  included. Those with a guitar part (or no instrument listed), in a Guitar
  Pro or Power Tab format and under 5 MB are tried, most stars first, at most
  three a song a run. A download is kept only if its first bytes are a Guitar
  Pro (3 to 7) or Power Tab file's: as the song's `guitar-N`, with the
  extension those bytes say, N the lowest number no file of the song holds.
  Anything else, such as a page served in its place, is thrown away, and that
  upload waits 30 days. A song its artist's page doesn't list is asked about
  again after 30 days; a song with an error, next run. It prints
  `gtptabs.com: 3 tried, 2 Guitar Pro files kept, 1 not on gtptabs.com, 0 errors`,
  after `Index: 6 sitemaps read.` when it read them. Three downloads in a row
  answered with a page instead of a file end the pass as an error, so a site
  that started asking for a login costs three requests. With gtptabs.com
  turned off it asks nothing and says so. A cooldown, a block or a spent
  budget exits 0.
- **`caracole musescore`** reads MuseScore's song sitemaps into the local index
  the to-do page's MuseScore links come from, when it never has, or last did 30
  days ago; it asks for nothing else, and downloads nothing. It prints
  `Index: 2 sitemaps read.` and `MuseScore: 80000 song pages in the index.`, or
  `MuseScore's index is up to date: 720000 song pages.` when nothing was due. A
  spent budget leaves the rest of the sitemaps for the next run, which goes on
  where this one stopped. A Cloudflare challenge is a block: the command says
  `MuseScore blocked caracole: …`, sends one ntfy message, and caracole leaves
  MuseScore alone until the cooldown ends. With MuseScore turned off it asks
  nothing and says so. A cooldown, a block or a spent budget exits 0.
- **`caracole scan`** links the audio files in Music/ to your songs, by their
  tags (or an "Artist - Title" file name) and their duration, give or take 3
  seconds. It never adds a song. A file named as the song wins over one whose
  name only comes close, so a whole album's "Pt. 1" doesn't take the place of
  its "Pt. 2". A close name must also be clearly closer than any other, and
  when your line gives no duration, the file must be as long as LRCLIB's
  lyrics say. Chinese names are compared as pinyin too, so 斑馬斑馬 meets
  斑马斑马. A Music/ folder that is missing or has no audio, such as a disk
  that isn't mounted, unlinks nothing, and the scan says so
  (`Music: /srv/music is missing, so nothing was unlinked`). Then it files the
  Guitar Pro and Power Tab files you dropped into `_inbox/`, by their names: a
  file named `Soda Stereo - De Musica Ligera (ver 2).gp5` becomes that song's
  `guitar-N.gp5`, where N is the rank caracole gave version 2, or the lowest
  free number when another file already holds guitar-N. It files scores too,
  such as MuseScore's downloads (`.mscz`, `.mxl`, `.musicxml`, `.pdf`, `.mid`,
  `.midi`): one named `Oasis - Wonderwall.mscz`, or `Wonderwall.mscz` when only
  one song has that title, becomes that song's `score-N.mscz`, N the lowest
  number no score of that format holds, so the formats of one score share it.
  A MusicXML file is also placed by the title and composer its header gives,
  when exactly one song has both. A score is never `sheet.pdf`, which caracole
  renders itself. A name UG writes in two scripts meets yours by any of its
  parts, the bracketed original included: the file of 周杰伦's 晴天 may be
  named `Jay Chou (周杰倫) - 晴天 Qing Tian Sunny Day (ver 1).gp5`. A file the library
  already has is removed from the inbox; a file it can't place stays there,
  and so does a symbolic link, which is never read:
  `Inbox: 0 filed, 0 duplicates, 0 left, 1 symbolic link refused`. If
  `_inbox` is a link itself, it is refused the same way, and nothing in the
  folder it points at is read, filed or deleted. The nightly run's scan line
  ends with the same count (`, 1 symbolic link refused`).
- **`caracole render [--force] [--song "ARTIST - TITLE"]`** (and
  **`caracole render --song "ARTIST - TITLE" --version QUERY`**, below) writes
  `sheet.cho`, `sheet.pdf` and `sheet.html` next to every kept sheet, or the
  one song's with `--song`, in the song's own version: its `[version]` (Make
  this my version, below), else transposed as `[transpose]` says, else as written.
  The PDF has one line under the title: the artist and the viewer's key line
  ("Soda Stereo · Bm shapes · capo 2 · sounds C#m", or "Soda Stereo · Key Bm"
  without a capo), then a capo or a tuning the tab's notes name
  ("Soda Stereo · Key Bm · half step down"): a tuning they name ("half step
  down", "Drop D", "Eb standard") or give after a "Tuning:" label ("Tuning:
  DADGAD"), never one they only talk about, and never standard tuning. Then the chord diagrams above
  the song, bold rust chords over the lyrics, and section names in small rust
  capitals (no band). The title is large, the page a clean two columns, and a
  songbook's songs are set the same way. chordpro prints a text of the PDF's own, and `sheet.cho` stays as it
  is, for the viewer: the tab's notes before its first section stay out of the
  PDF (a tab after them stays in), the chord diagrams are the shapes the
  viewer shows first for the chords the sheet gives shapes for (its chord
  legend, "Cadd9 (x32033)", wherever it is), the section names are in
  capitals and the song is in two columns. A song in another key, capo or
  mode, by its `[version]` or its `[transpose]`, has every chord written as
  its viewer shows it there (Bb, not chordpro's A#), each with the shape the
  viewer shows (or the one the version chose) as its diagram: chordpro moves
  nothing. A songbook's songs are written the same way, each where the
  songbook plays it (see [Songbooks](#songbooks)).
  `sheet.html` is the sheet viewer, for the phone (see
  [The sheet viewer](#the-sheet-viewer)). A PDF is made again only when its
  sheet, its version, the font, caracole's PDF style or the text the
  PDF prints changes (the key it names, as when an auto sheet's key is heard
  again, or a newer caracole's way of writing it), or when
  it is no longer the PDF caracole wrote: deleted, cut short, edited, or a
  link in its place. So annotate a copy, not `sheet.pdf`. `--force` makes them
  all again (the song's alone, with `--song`). With `--song`, as after a pick
  in `caracole serve`, only that song's failure counts: another sheet that
  fails, or waits for a font, is not its own, nor is a songbook, and the to-do
  page keeps telling of the last render of the library. After an upgrade from
  a caracole that didn't record what it wrote, or that drew its PDFs another
  way, the first render makes every PDF once more. The viewer is written
  again whenever it would change, at every render. Each version of UG's
  kept beside the sheet (`version-<tab>.txt` and `.json`) gets a viewer of
  its own, `version-<tab>.html`, and no `.cho` or PDF; its viewer offers no
  Export PDF either (an export is made from `sheet.html`'s sheet, so
  `caracole render --version` makes the one's PDF). It opens in the
  version's own key, as the version is written, since the song's own version (`[version]`,
  `[transpose]`) is its sheet's. Every viewer of the song (`sheet.html`, an
  auto sheet's standing alone, each `version-<tab>.html`) lists the song's UG
  chords versions, in the order caracole ranks them, and which one it is. A
  version no longer kept loses its `version-<tab>.html` at the next render,
  while it is still as caracole wrote it. A song that no longer
  keeps its human sheet (its UG match was undone, say) loses the `sheet.cho`,
  `sheet.pdf` and `sheet.html` made from it; one you put where caracole never
  rendered one stays. A sheet that never
  got a PDF (waiting for a font, or chordpro failed on it) loses its
  `sheet.cho` and `sheet.html` while they are still as caracole wrote them.

  **`--song "ARTIST - TITLE" --version QUERY`** exports that song's PDF in
  another version: the viewer's address for it (`t=2&mode=dorian&capo=0`, with
  `at=` for chosen chord shapes and `alt=` for "play X for every Y"; the same
  words the sheet viewer puts after its `#`). It writes the PDF beside the
  sheet's own, named after the version: `sheet (G Dorian, capo 0).pdf`,
  `sheet (A Minor, capo 0).pdf`, or `sheet (Transposed +2, capo 0).pdf` for a
  sheet with no key. Every chord is written as the viewer shows it (moved,
  in the mode, swapped), with its chosen shape, and no `{transpose}` is left.
  The words are read as the viewer reads its own address: naming nothing of
  the version (no `t`, `mode`, `capo`, `alt` or `at`), they are the song's
  own version, where the viewer starts; without a `t`, the version is at the
  song's own `t` (its `[version]`'s, else its `[transpose]`), which the viewer
  leaves out of its address. An export with the same name replaces the last one. Exports are
  caracole's files: every render makes them again when the sheet, the style or
  the PDF's text changes (and says nothing when they are up to date), and
  `caracole remove` deletes them. One a new sheet names otherwise (a sheet in
  another key or capo took the old one's place, an auto sheet's key was heard
  again) is made under its new name, and the PDF under the old one goes, while
  it is still as caracole wrote it. The library page lists them under the
  song's line's "⋯", as its Versions, each by its version (`G Dorian, capo
  0`), before its other files. An
  export is made from the song's human sheet, else its auto sheet; it needs one
  of them to be kept, and exits 1 with the reason when it can't be made.

  **`--song "ARTIST - TITLE" --version QUERY --mine`** makes that version
  the song's own instead: it writes it under `[version]` in overrides.toml
  (once it holds caracole's lock, keeping your comments), says so
  (`Your version of Soda Stereo - De Música Ligera: G Dorian, capo 0`), then
  renders the song as `--song` does: its `sheet.pdf` is in that version, its
  viewer starts there, its exports and its songbooks follow. A version that is
  where the song plays without one (its `[transpose]`, else as written) takes
  the song's `[version]` out instead. `--mine` needs `--version` (exit 2).
  In the sheet viewer, ⋯ has **Export PDF of this version**, but for the auto
  sheet's viewer kept beside a human sheet: its chords are other ones, and an
  export would be the human sheet's (caracole serve refuses one from it, 409).
  On `caracole serve` it opens `/export` in the same tab: the version in words ("G Dorian,
  capo 0"), Make PDF (this command, queued like any request), the job's line,
  then Open the PDF and Back to the sheet, which keeps the viewer's address.
  Below Make PDF, **Make this my version** queues the same command with
  `--mine` (caracole serve writes no overrides.toml itself); once it is done
  the page says so and links the song's own PDF. On the version the song
  plays in already (its `[version]`, else its `[transpose]`, else as written),
  the page says "It is your version" instead.
  Opened from a file, the viewer shows the command to run instead, with Copy,
  and says that `--mine` makes it your version.
  chordpro works on a copy, in a private folder in the cache, and the new PDF
  replaces the old one in one rename, so a failed render leaves the last good
  PDF in place. It exits 1 when a sheet couldn't be rendered, and the log
  says why, as `no PDF for Artist - Title: …` (chordpro's own messages name
  the copy in the cache); a PDF text caracole couldn't make (a bug) fails
  that sheet's PDF alone the same way, with its traceback in the log, and its
  viewer is still written. A viewer that couldn't be made or written is logged
  as `no viewer for Artist - Title: …` and counts the song as failed too, but
  never costs it its PDFs. A symbolic link, a FIFO or a folder in the place of
  `sheet.json`, `sheet (auto).txt`, a `.cho` file or a viewer fails that song
  alone: caracole reads no sheet through a link. Remove the link, and the next
  render writes the `.cho` and the viewer again; the next `caracole run` writes
  `sheet.json` again before it renders. Then it makes the
  [songbooks](#songbooks)' files that need it, and says how that went on a
  line of its own, `Songbooks: 1 rendered, 2 up to date, 0 failed`, when there
  are songbooks; a songbook that couldn't be made, or a songbooks.toml that
  can't be read, exits 1 too, but not with `--song`: that line still says so.
- **`caracole todo`** rewrites `_todo.md` and `index.html` from the database.
- **`caracole icons`** fetches the icon of each site `index.html` has none for
  yet, now, then rewrites `_todo.md` and `index.html`. It prints a line a site:
  `Ultimate Guitar: icon fetched`, `LaCuerda: kept already`, `LRCLIB: no icon
  there; its badge stands in, and the site is asked again in a week`, or why it
  asked nothing (turned off, cooling down). Unlike the run's icons step, it
  also tries a site whose last try failed less than a week ago, and YouTube,
  with its provider's budget and pace (15–30 s), unless `[providers.youtube]
  enabled = false` turned it off. What a site answered less than a week ago
  still comes from the cache, so running it again sooner asks that site nothing. A block cools that site
  down, as any block does, and the others are still asked. A block or an error
  exits 0.
- **`caracole review`** settles uncertain matches, one prompt per song (see
  [Review](#review)).
- **`caracole search [QUERY]... [--limit N] [--add N] [--key KEY] [--artist NAME]
  [--title TITLE]`** searches your library and the offline UG index, by an
  artist, a title or both; `--key` finds your songs in one key (see
  [caracole search](#caracole-search)).
- **`caracole autochords`** writes `sheet (auto).txt` from audio you bought, for
  songs with no human sheet (see [the worked example](#a-worked-example)), then
  rewrites `_todo.md` and `index.html`. It needs the flake's
  `packages.autochords`, with torch, librosa and beat_this; the default package
  says so and exits 1. A purchase it can't read fails that song alone: it
  exits 0, the to-do page lists the file, and the song is tried again once the
  file changes. It exits 1 when auto-chords can't work at all: the model files
  missing or unusable, or a sheet it can't write into the library. It also
  works out the chords of the audio the youtube step took, as of a purchase.
- **`caracole youtube [--song "ARTIST - TITLE" [--url URL | --none]]`** takes
  the audio of the songs no human sheet was found for from YouTube, as the
  nightly run's youtube step does (see [Audio from YouTube](#audio-from-youtube)),
  printing a line per song, such as
  `Radiohead - Creep: downloaded Creep (Radiohead - Topic), https://www.youtube.com/watch?v=…`,
  then `YouTube: 1 downloaded, 0 not there, 0 unavailable, 0 errors (2 yt-dlp runs of 6).`
  `--song` takes that song's audio now, even when its search found nothing
  lately; it refuses a song that has a human sheet, is ignored or has a
  purchase linked, and says so when the song has that video's audio already. `--url` first writes the video
  under `[youtube]` in overrides.toml, so the song's audio comes from it; `--none`
  writes `"none"` there, lets go of any audio the song had from YouTube, and asks
  nothing, so it works with YouTube off too, and for a song not in the library
  yet. It needs the flake's `packages.autochords`, which has auto-chords and
  yt-dlp: without them, or without the model files, it asks nothing and exits 1.
  Turned off, it asks nothing and says so. A cooldown, a block or a spent budget
  exits 0. The chords come next, from `caracole autochords`.

**The pages.** A command that changes what `_todo.md` and `index.html` show
rewrites both when it is done: `match` (not `--dry-run`), `render`, `scan`,
`todo`, `add`, `search --add`, `sync`, `autochords` and every `songbook`
command but `list` and `show`; `review` when an
answer changed something; and `fetch`, `lyrics`, `lacuerda`, `gtptabs`,
`musescore` and `youtube` when they did something or were blocked, so that
Provider health shows the cooldown (`youtube` also when it let go of audio no
song needs any more, with nothing to download).
A page caracole can't write ends the command with status 1 and
`can't write …/_todo.md: Permission denied`, its own work saved first; for
`add`, `search --add` and `sync` that is only a warning.

**One caracole at a time.** The commands that ask the sites for pages or write
the library hold caracole's lock, `caracole.lock` in the state folder, while they
work, so no two budgets are ever spent side by side: `run` from start to end,
`get`, `index build` and `refresh`, `fetch`, `lyrics`, `lacuerda`, `gtptabs`,
`musescore`, `youtube`, `render`, `match`, `scan`, `todo`, `sync`, `add`,
`search --add`, `autochords` and the `songbook` commands that change a songbook
or render one. A
second one waits for the first, and says which it is:
`Another caracole is running (pid 4242: run); waiting for it to finish.`
`caracole review` and `caracole remove` take the lock only after your answers,
never while they wait for one, and `search`, `match --dry-run`, `index stats`,
`remove --list`, `songbook list` and `songbook show` only read, so they never
wait. A command that waited reads the sites' cooldowns once it has the
lock: if the caracole it waited for was blocked, it sends that site nothing and
exits 0. Its first request to a site also waits out the pause after the last
request any caracole sent there, so the pauses hold whichever caracole sends.

A lookup (`caracole get`) never waits behind a whole run: it says
`Another caracole is running (pid 4242: run); it lets a lookup go first at its
next pause, or between two songs.`, and the run, which spends most of its time in its 10–20 second
pauses (its youtube step, in its 15–30 seconds between two yt-dlp runs), lets go
of the lock in the pause it is in, takes it back once the lookup is done, and
waits a whole pause again before its next request. The
run then reads each song again before its turn, and overrides.toml too, so a
song the lookup fetched isn't fetched twice, and a tab it pinned is the one
kept. Work that sends no request lets a lookup go first between two songs:
`caracole autochords` (a song takes minutes, and the unit runs for hours), and
the PDF pass of the run and of `caracole render`, which reads each song and
overrides.toml again after it. The waiting lookup announces itself with a file
in `caracole.lock.waiting/` in the state folder, which it touches every second
while it waits; one left by a lookup that was killed while it waited is no
longer waited for after five seconds.
A songbook change, asked for now as a lookup is, waits the same way and says
the same: `caracole songbook make`, `add`, `remove`, `move`, `set`, `rename`,
`delete` and `render`, so a songbook you make (from a terminal, or on
`caracole serve`) while the nightly run works is made in the run's next pause,
in seconds, rather than after the whole run.

## Audio from YouTube

For a song nobody has charted, caracole can take the audio from YouTube and
work out the chords itself, with auto-chords. This is your choice for your own
library, and it goes against YouTube's robots.txt (which closes `/results` and
`/youtubei/`, the search and the API yt-dlp uses, to crawlers) and against
YouTube's terms of service, which allow no downloads but those YouTube offers.
It is the one place caracole goes against a site's robots.txt; everywhere else
it honours it. It does so on these terms:

- **Only for a song with no human sheet**, and nothing caracole will still do may
  find one: the songs the buy list would list. A purchase in Music/ comes
  first, and a human sheet found later still takes the auto sheet's place.
- **Only with auto-chords.** The download is no use without the chords, so a
  caracole without auto-chords (the default package), or without its model
  files, runs no yt-dlp at all, and the to-do page says why. It is on by
  default in `packages.autochords`, which has yt-dlp; `[providers.youtube]
  enabled = false` turns it off.
- **A few songs a night**: a budget of 6 yt-dlp runs (a search or a download
  each), 15–30 seconds apart, one at a time; yt-dlp's own pauses space out its
  requests inside a run (`--sleep-requests 2`, and 10–20 seconds before a
  download).
- **Blocks honoured**: "Sign in to confirm you're not a bot", an HTTP 429 or 403,
  a rate limit or a captcha stops YouTube for the night and starts its
  cooldown, 24 hours and doubling, as for any site, with one ntfy message.
  Nothing is retried, and caracole never works around a block: no cookies, no
  login, no proxy, no PO tokens or plugins (yt-dlp gets `--ignore-config`,
  `--no-cookies`, `--no-cookies-from-browser`, `--no-plugin-dirs`). Nor does
  yt-dlp get any of caracole's secrets: it runs without the unit's credentials
  or any `CARACOLE_*` variable, with only the paths, language, proxy and
  certificate settings it needs.
- **Audio alone**, as m4a, never a playlist, at most 100 MB, kept outside the
  synced library, in the cache (see [the library folder](#the-library-folder)).

**Which video.** caracole asks yt-dlp's search for `ytsearch8:<artist> <title>`
and picks the upload whose title is the song's and whose channel or title names
the artist, names in two scripts included (宋冬野 meets "Song Dongye"), and
whose length is within 20 seconds of the song's (its own, else LRCLIB's; with
neither, from 45 seconds to 15 minutes). A title in Chinese, Japanese or Korean,
written with no spaces, is the song's when nothing but the artist and words such
as 官方, 歌词 or MV are left around it, or when it stands as a word of its own
among others; never when it only starts a longer one (雨 isn't 雨下一整晚, nor
晴天 晴天娃娃). A cover, a live, karaoke, instrumental, lesson, slowed, sped-up
or remixed version loses to any other, unless the song itself is live or
acoustic: by its title (karaoke "in the style of" the artist included) or by
its channel's name (KaraFun, Sing King, any "Karaoke" or "Nightcore" channel). Then a title that is exactly the song's beats one that only stands
among other words; then the closest length wins (within 2 seconds, LRCLIB's
timed lyrics fit the audio), then the artist's "Topic" channel
(YouTube's own upload of the release), official audio, the artist's own
channel or an official video, then the search's order. Nothing that fits makes
the song a miss, asked about again after 30 days. A wrong pick, or a song the
search found nothing for: paste the right video under `[youtube]` in
overrides.toml, or run `caracole youtube --song "Artist - Title" --url URL`.

**Then the chords.** The youtube step links the audio to the song as the scan
links a purchase, and `caracole autochords` (its unit, after each nightly run)
makes `sheet (auto).txt` from it. Its third line says where the audio came from,
`Audio from YouTube: Creep (Radiohead - Topic), https://www.youtube.com/watch?v=…`,
and so does the PDF's first line; info.json gives the video's address as the
auto sheet's source. The to-do page and index.html say where each song stands.

**Errors are never misses** here either: a network error, a timeout (2 minutes
for a search, 15 for a download) or anything else yt-dlp fails on leaves the
song for the next run, after the songs whose last try didn't fail. A video
YouTube won't give without a login (private, removed, age-restricted,
members-only, DRM-protected) is passed over for the next pick; one you pasted
waits for another paste, and is never asked for again meanwhile. A song with
audio from another video keeps it until then. So is a video whose download
failed 3 times for any reason but the network (a format YouTube no longer
offers, say): the next run searches again, without that one, and the song is no
miss.

## The to-do page

`Library/_todo.md` lists only what needs you, with the links to do it and the
exact lines to paste. Each run rewrites it, and so does every command that
changes what it shows (see [the pages](#one-step-at-a-time)). It starts with a
summary (songs found, wanted and ignored), a link to `index.html`, and how
many songs are waiting for the nightly fetch. Then each of these sections,
when it has something in it:

- **Setup problems.** What stops caracole until you act: an overrides.toml it
  can't read (the nightly run then stops before its first step, and the page,
  built without your overrides, leads with the error), a UG index that isn't
  built or is incomplete, a wanted.txt it can't read at all (the songs it
  read before are still looked for), and lines of wanted.txt it can't read.
- **Review.** Matches caracole wasn't sure about. Each candidate has its score,
  the UG song, the step that found it and links to its pages by type, then its
  lines for overrides.toml. They come without table headers: each line ends
  with the table it goes under, as in `# under [match]`. A candidate under
  another UG name for the artist also gets an `[alias]` line, unless
  overrides.toml has that alias already; for an artist with aliases, the
  line is the artist's whole list with the new one, marked
  `# in place of the artist's line under [alias]`. After the candidates
  comes the `[reject]` line that dismisses them all; for a song with a
  `[reject]` line already, the whole line to put in its place (see
  [Review](#review)). When the candidates come only from the steps that never
  accept (other artists' songs of the title, probably covers, and names that
  aren't quite UG's), the item says what they are, and whether caracole has
  looked on the artist's own UG page yet:

  ```
  Only songs UG files under a catch-all artist (`misc-musicals`) with the
  show's name in the title and other artists' songs with this title
  (probably covers). If none is the song you want, dismiss them all (below):
  UG may list epic only by bare ids, and the to-do page then lists them under
  Artists to find.
  ```

  For a candidate under `misc-originals` or `misc-unsigned-bands`, it says
  instead that the performer's name starts the title. A candidate under a
  catch-all artist gets no `[alias]` line. When some
  candidates come from names that aren't quite UG's, the section's
  introduction says what each of their steps (`catch_all`, `typo_artist`,
  `word_title`) means.
- **Partial sheets.** The best sheet covers less than 80% of the lyrics: the
  percentage, the sheet and its source page. A more complete sheet takes its
  place when one turns up; to use another UG version now, pin it under
  `[pin]`.
- **Artists to find on Ultimate Guitar.** UG lists artists with accented or
  non-Latin names only by bare ids (Joaquín Sabina, Maná, 宋冬野), so caracole
  can't see their tabs. For each such artist with a song not found, or
  reviewed on its title alone or on names that aren't quite UG's, the page
  links a UG search. A song with a candidate under the right spelling of a
  misspelt name (`typo_artist`) or under a catch-all artist (`catch_all`)
  isn't counted while that candidate stands: it is likelier the song than a
  page of bare ids, and `Coldplya` is no artist to look for. Dismissed in
  `caracole review`, it gives way. Open the artist's
  page once, by hand, or any of their tab pages, and paste its address, as
  your browser shows it, into the one block the page gives for all of them,
  in place of `https://www.ultimate-guitar.com/artist/…`:

  ```toml
  [artist_url]
  "宋冬野" = "https://www.ultimate-guitar.com/artist/634073"
  ```

  The block has the `[artist_url]` header only while overrides.toml has no
  `[artist_url]` entries; after that the page gives the lines alone, to add
  under the table. The artist page lists all of the artist's tabs, bare ids
  included. The next run reads it, finds your songs on it by title, and
  fetches them like any matched song. That's once per artist, not per song.
  From then on `caracole search` finds every tab the page lists, with UG's
  ratings, and the `caracole add` line for each of their songs.
  A tab page you pasted is read first, once, for the artist page it links to.
  When it leads to none (UG answers 404 for it, robots.txt closes it, or it
  doesn't link to its artist's page), the artist stays on the list, with the
  page you pasted and what is wrong with it, and no new line: put the
  artist's page, or another of their tab pages, in its place. The song isn't
  taken for missing meanwhile. The same goes when UG's copy of the page can't
  be read, even fetched again: an error on UG's side rather than a page that
  leads nowhere. caracole asks for it again a week later, then after twice as
  long each time it still can't, whichever of the artist's songs asks, and
  the list says when; another page in its place is read at the next run.
- **Buy list.** No human sheet found yet, and nothing caracole will still do may
  find one: the song's UG fetch is done (or UG doesn't have it), no fetch,
  artist page or LaCuerda check is due for it, and, for a song not found, the
  index is complete. Songs still waiting for one of those are counted at the
  top instead. Each has links to buy the track DRM-free (Bandcamp, Qobuz, the
  iTunes Store) and to check the song first (Chordify, Songsterr, a YouTube
  lesson search). Drop the purchase into Music/, and auto-chords writes a
  sheet from it. Songs whose audio you have are left off. This is the list of a
  caracole that takes no audio from YouTube; unless you turned YouTube off, it
  says why it takes none (`… only when it can work out the chords from it, and
  here it can't: this caracole was built without auto-chords …`).
- **No human sheet found yet**, in place of the buy list when caracole takes the
  audio from YouTube (see [Audio from YouTube](#audio-from-youtube)). The same
  songs, and those whose audio came from YouTube, until a human sheet turns up,
  each with where it stands: `queued` (the next run looks for it, or downloads
  the video it picked, linked), `waiting` while YouTube is blocking caracole,
  `audio downloaded from` the video, or `chords done, from` the video, with a
  link to the auto sheet; with the "check first" links (Chordify, Songsterr, a
  YouTube lesson search), and no buy links. A song whose last try failed says
  so, and is tried again. caracole does all of this itself, so the section
  doesn't count among the things that need you.
- **Nothing on YouTube for these.** The songs YouTube's search found no video
  that fits (asked again after 30 days), whose video under `[youtube]` can't be
  downloaded (private, removed, age-restricted: caracole never logs in; a song
  with audio from an earlier video says so, and keeps it), or that
  you turned YouTube down for (`"none"`, with buy links). The lines to paste
  under `[youtube]` follow, one per song, each in place of
  `https://www.youtube.com/watch?v=…`; for a song with an entry already, the
  line says to put it in place of that entry.
- **Auto-chords couldn't read these purchases.** Each file auto-chords failed
  on, with the error. Re-download it, or convert it (to FLAC, say) and replace
  the original: a changed file is tried again on the next run. Audio from
  YouTube is named by its video: paste another video under `[youtube]`.
- **New Guitar Pro files from gtptabs.com.** The files caracole downloaded in
  the last 7 days, one for each song that had none, each with a link to its
  page on gtptabs.com. Open each in Guitar Pro or TuxGuitar: if it isn't the
  version you want, any Ultimate Guitar page below is still there to click.
- **Guitar Pro pages to click.** The Guitar Pro and Power Tab versions caracole
  picked for each song, best first, with version, rating and votes. Each is
  labelled with its rank, as `guitar-1`: the name its file gets, unless a file
  you downloaded earlier holds that number (then it gets the lowest free one).
  Open each page, click its Download button, and drop the file into
  `_inbox/`; the next run, or `caracole scan`, files it under its song. Caracole
  never downloads these itself: UG's robots.txt closes its download endpoint
  to bots. A song with a file from gtptabs.com says so, as
  `(guitar-1.gpx came from gtptabs.com)`: its UG pages stay in case you want
  another version.
- **Scores on MuseScore.** For each song with no score filed, up to three
  MuseScore song pages with its title, oldest first, each a possible match:
  MuseScore's sitemaps give titles only, never the artist. Open one, pick a
  score, and click its Download button (MuseScore asks you to log in, and most
  scores need a Pro account). Save the file under the name the line gives, such
  as `Oasis - Wonderwall.mscz`, with its own extension, and drop it into
  `_inbox/`: the next run files it as the song's `score-N`. Caracole never
  downloads these itself. When MuseScore is blocking caracole (its Cloudflare
  protection answered with a challenge, as it did in October 2026), the section
  says so first, with the last answer and until when caracole leaves MuseScore
  alone, even when it has nothing to list: the pages listed then come from the
  sitemaps read before, and with none read, you can still find a score on
  musescore.com yourself and drop it into `_inbox/` named the same way.
- **Guitar parts not found.** Songs UG has no guitar part for, and with no
  Guitar Pro or Power Tab file kept (from `_inbox/` or gtptabs.com), with
  Songsterr and YouTube links.
- **Inbox: files caracole couldn't place.** Rename such a file
  "Artist - Title (ver N).ext", as Guitar Pro pages to click names the song
  and the version, or a score "Artist - Title.ext", the song as caracole names
  it, and the next run files it. Don't move it into the song's
  folder yourself: caracole wouldn't know it is there. A symbolic link in
  `_inbox/` is listed too: caracole files only regular files. If `_inbox` is a
  link itself, the page lists nothing from it, and says to make it a folder;
  until then the scan files nothing.
- **Missing lyrics.** LRCLIB has none for these yet; caracole asks again after
  30 days.
- **Suggestions from your Spotify top tracks**, with `suggest_top_tracks`.
  Add the ones you want to learn to your Learn playlist or to wanted.txt.
  Songs you have, and songs you removed, aren't suggested.
- **PDFs.** The last render of the library (the nightly run's, or `caracole
  render`'s): how many PDFs were made or failed, a font problem if there is
  one, with the sheets it keeps from a PDF, and the sheets that failed. A
  lookup (`caracole get`) and `caracole render --song` (the last step of a
  pick in `caracole serve`) render their own song alone and leave that record
  as it was, but for their song: they take it off the sheets that failed or
  wait for a font, or put it back on.
- **Sources.** Whether Spotify is off, synced, not fully set up (the client
  secret missing, say), or needs `caracole auth spotify`, and how many songs
  wanted.txt has, with the lines it couldn't read; for a wanted.txt it
  couldn't read at all, the error, as `wanted.txt: error at <time>: …`.
- **Provider health.** For Ultimate Guitar, LRCLIB, LaCuerda, gtptabs.com,
  MuseScore and YouTube: OK, errors (nothing has worked since the last error),
  cooling down until when, or off (`[providers.gtptabs] enabled = false`, and
  the same for `musescore` and `youtube`; for YouTube also `off:` and why, as in
  a caracole without auto-chords); the last success; the last error; the
  requests of the last run (for YouTube, its yt-dlp runs).

### Review

`caracole review` asks about each song to review in turn. It lists up to five
candidates, each with its score, the UG song, the step that found it and the
page of that song's oldest tab, whatever its type:

    [1/1] Radio Head - Crep
      1) 89  radiohead/creep (fuzzy_title)  https://tabs.ultimate-guitar.com/tab/radiohead/creep-tabs-4119
    Pick 1-1, (n)one of these, (p)in a URL, (i)gnore, (s)kip, (q)uit:

- **A number** accepts that candidate. It writes
  `[match] "Radio Head - Crep" = "radiohead/creep"`, and
  `[alias] "Radio Head" = "radiohead"` when the artist's name differs, so
  every other song by that artist matches too; an artist with aliases already
  keeps them, and gets this one added. A candidate found by title alone gets
  no alias: it is usually a cover by someone else. Nor does one under a
  catch-all artist (`catch_all`): `misc-musicals` is no other name of
  EPIC's. One under the right spelling of a misspelt artist (`typo_artist`)
  does, so the artist's other songs match too.
- **n** says none of them is the song. It writes them all under `[reject]`,
  as `"Radio Head - Crep" = ["radiohead/creep"]`, and clears the review
  without ignoring the song: the rematch leaves those candidates out for good,
  and caracole goes on looking for the song, on its artist's UG page too, where
  it passes over them as well. A song without candidates isn't offered `n`:
  its prompt starts at `(p)in a URL`.
- **p** asks for a UG tab address, and writes it under `[pin]`; Enter there
  skips the song.
- **i** ignores the song: it goes under `[ignore]`.
- **s**, or Enter, skips the song; **q** stops.

Each answer goes into overrides.toml, with your comments kept, so it survives
a lost database. When an answer changed something, caracole matches again at
the end and rewrites `_todo.md` and `index.html`. It ends with the count, as
`accepted 1, pinned 0, ignored 0, rejected 0, skipped 0`. A broken
overrides.toml stops it with status 2: before its first question, or, if the
file breaks while it waits for you, at the answer it can't write, which
leaves the file untouched. It never holds caracole's lock while it waits for
you, so the nightly run never waits for an answer. The to-do page's Review
section has the same `[match]`, `[alias]` and `[reject]` lines, ready to
paste, if you'd rather edit the file.

`caracole review --song "ARTIST - TITLE"` asks about that song alone. Given an
answer too, it asks nothing, and writes what that answer writes:

    caracole review --song "Radio Head - Crep" --pick 1
    caracole review --song "Radio Head - Crep" --pick radiohead/creep
    caracole review --song "Radio Head - Crep" --none

`--pick` takes a candidate's number, as the list numbers it, or its UG song as
the list shows it; `--none` rejects every candidate listed, or, with one
`--seen ARTIST/SONG` for each, only those: the ones you saw, should the
nightly run have found others since. It holds caracole's lock while it
answers, matches that song again (and, when it writes an `[alias]`, the
artist's other songs) and rewrites the pages, then says where the song
stands: matched (and how to fetch it now), still in review, or not found,
which caracole goes on looking for. Other songs keep their match: an edit
you made by hand to another song's entry in overrides.toml waits for the next
`caracole match` or nightly run. A song that doesn't need review, a number or
a UG song the list hasn't, exits 1 and writes nothing. This is what the picker
of `caracole serve` runs (see [caracole serve](#caracole-serve)).

A song not found has no candidates, but `--pick` also takes one of the first
five songs `caracole search` finds for its artist and title, leaving out
those you rejected for it. `caracole review --song "ARTIST - TITLE"` with no
answer lists them, numbered as `--pick` takes them, and writes nothing:

    Radio Head - Crep: not found under this name. What caracole search "Radio Head Crep" finds for it, without the songs you rejected for it:
      1) 88  radiohead/creep  https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-1
    Pick one with caracole review --song "Radio Head - Crep" --pick N, or ARTIST/SONG: that writes [match] alone, no [alias].

Go by these numbers, or by ARTIST/SONG, never by `caracole search`'s own:
it numbers the songs you rejected too. A pick writes `[match]` alone: no
`[alias]`, since a song under another artist's name may as well be a cover
as another spelling.

## Browse and search

### Library/index.html

`index.html` sits next to `_todo.md`, and is rewritten with it, except while
overrides.toml can't be read: built without it, the page would lose your
transpositions and ignored songs, so it stays as it was. Open it from the
synced folder, in a browser on the laptop or the phone. It needs no server and
loads nothing from the network. Its browser tab shows caracole's mark, an
inverted question mark (¿) on its rust-red square, drawn inside the page itself,
as every page caracole writes or serves shows it (the sheet viewers and the
songbooks from their next render); caracole serve answers a browser's own
`/favicon.ico` with it too. It has two tabs under its header: **Library**,
your songs, and **Songbooks** (see [The Songbooks tab](#the-songbooks-tab));
the address remembers which (`#tab=songbooks`). Its header is short, so that on
a phone the first song starts well within the first screen: the library's
numbers beside its title (served, the Requests link on the line above), the
tabs, the search box, then one row of
buttons and menus (the status buttons, then Select, Key and Sort), which
scrolls sideways on a phone, fading at an end where more of it is out of
sight. The search box stays at the top as the page scrolls under it, with an
edge to show it.

It shows your songs as dense lines, grouped by artist: each artist's name over
their songs, artists A to Z ("The Beatles" under B, Chinese names by their
pinyin), with how many of their songs you have ("Soda Stereo · you have 2",
all of them, whatever the search or a filter leaves out), and their songs A to
Z under it. A line is a song, one line each on a laptop, 24 px tall with a
mouse (its buttons no smaller than a pointer needs): read down under the
search box, a laptop's screen holds twenty-odd lines with their artists'
names. On a phone two lines a song, the title and its button, then the rest
under the title. A line has the song's title, which
opens its sheet (the sheet viewer, see [The sheet viewer](#the-sheet-viewer),
else the PDF, else the text); its status, one word: Found, Wanted, Needs review
when caracole isn't sure of the match, or Not found when the offline index has
no such song; its key ("Am"; a screen reader hears "Key A minor (from the
tab)", see [The song's key](#the-songs-key)); the marks of where its sheet and
its files came from, the sheet's first, by each site's own icon (the lyrics
LRCLIB's, a Guitar Pro file gtptabs.com's: see [Where each file came
from](#where-each-file-came-from)); and its one button, Open (Open PDF, Open
text), or, on the page `caracole serve` serves, Fetch now for a wanted song
(Pick the match for one that needs review first, and Removing… while caracole
removes it). An auto sheet says so by its ♪ mark (YouTube's, when its audio came
from there), by its button's tooltip, "Auto sheet PDF", and to a screen reader
by the button's name, "Open PDF of Creep by Radiohead, an auto sheet".

Everything else a song has waits under its line's "⋯": its key in words and
where it came from ("Key A minor (from the tab)", "Key C major (estimated from
the chords)", "(from the audio)"), its transposition, its lyrics' state and
when it was added; a review's candidates (below); where it stands on the
YouTube route, when caracole takes the audio of songs with no human sheet from
YouTube ("No human sheet yet: caracole takes the audio from YouTube next",
"Audio from YouTube: auto-chords works out the chords next", "Auto sheet from
YouTube audio"), with a link to the video once there is one, instead of
offering to buy it; its versions, the sheet's PDFs in other versions, each
by its version (`G Dorian, capo 0`: see `caracole render --version` and Export
PDF of this version); its other files (the PDF, the text, the ChordPro file,
the lyrics, the timed lyrics, the tab, info.json, the Guitar Pro files) and the
Guitar Pro versions to download from Ultimate Guitar; its MuseScore pages,
each a possible match, as on the to-do page; for a song without a sheet, its
search and buy links; **Add to a songbook…** (see Songbooks, below), for a
song the page had when it was loaded (one that Get it or a request brought
since has it once the page is loaded again); and, served, Look in the index
and Remove…. When Fetch now has the line's button,
the sheet is the first of its files there, and its title opens it all the same.
A Guitar Pro file caracole downloaded names its site, as `Guitar Pro 1 ·
gtptabs.com`, and a score its format, as `Score 1 (MuseScore)`; a score's PDF
is never what a line opens, which is the sheet.

An artist's name, over their songs and marked with a funnel, shows only that
artist's songs ("Queen" leaves out ABBA's "Dancing Queen"), until you take its
chip off. Sorted by title, or by when the songs were added, the lines stand
alone, without the artists' names over them, each with its own (which filters
the same). A request's line (see [caracole serve](#caracole-serve)) shows under
the song's, a line of its own. The search, the status buttons, the Key menu,
the sort and the letters all work on the lines, and the address remembers
them, as it does the rest: a bookmark opens the page as you left it. (An
address from before, with `#view=rows` in it, opens the lines.)

A song that needs review lists its candidates under its "⋯", under "3
candidates", numbered as `caracole review` numbers them. Each is the UG song as UG names it
("Radiohead – Creep"), why the matcher thought of it ("artist spelled
differently", "title only: another artist's song, probably a cover", "under
UG's catch-all misc-musicals"), its score, its tabs per type ("Chords ×2 ·
Tabs ×1") and a link to its page on UG. The file can't write overrides.toml,
so it ends with the line to run, as `caracole review --song 'Radio Head -
Crep'`; `caracole serve` makes the list a picker (see below). A wanted song
the offline index didn't match says so, with the same line: for it, that
lists what `caracole search` finds, numbered as `--pick` takes them (see
[Review](#review)); `caracole serve` links to them instead.

The search box filters your songs as you type, asking nothing of anyone. It
ignores case and accents, so "musica" finds "De Música Ligera", and it matches
Chinese titles by pinyin: "ban ma" or "banma" finds 斑马斑马. A title's
initials, typed whole, find it too: "wywh" finds "Wish You Were Here", "bmbm"
斑马斑马. It finds keys too, however a sheet spells them: "a
minor", "F# major", "bbm", and "gb minor", which also finds the songs in F#
minor; or "minor" for every song in a minor key. A key written as a chord, such
as "am", also finds the names with "am" in them ("I Am the Walrus"). The
buttons show all songs, or only those found, wanted or needing review (that
button only while a song needs review); the Key
menu, there once a song has a key, shows only the songs in one key, with how
many each key has, and puts the spellings of one key together ("F# / Gb
minor"); and you can sort by artist, by title or by when songs were added.
Sorted by artist or title, with more than 40 songs shown, a row of letters
jumps to the first artist under each (by title, the first song). A line under the box says what typing and Enter do.
On the file on disk, which can ask nothing of anyone, **Enter** searches the
sites the only way it can (the Enter that ends a word typed with an input
method, pinyin say, only ends the word): it shows under the box the `caracole
search` line to run where caracole runs, with Copy, and leaves your songs as
they are; Escape takes it away. When nothing in the library matches, the page
shows that line at once. A key typed as a key ("a minor", "F# major") filters
your songs alone: the sites' indexes know no keys, so the line under the box
says so, and Enter waits for a search without one. The page puts each word of a line to run in single quotes
(`'Guns N'\'' Roses'`), so that no shell changes a `!`, a `$` or a quote in
it. `caracole serve` serves the same page, where typing searches what the
sites have too, under the same artist headers, with Get it, and a form to
request a song by name (see below).

On a touch screen every button, fold, chip, menu, letter and artist's name is
at least 44 pixels each way, for a thumb, and so are each line's button and
"⋯" (its title, beside them, is as tall): a phone shows about eleven songs to a
screen. With a mouse they keep their compact sizes. Fields, menus and the
Select boxes have an edge you can see against the page, in light and dark mode
(3:1 at least, as WCAG 1.4.11 asks), while the boxes the songs are in keep
their soft border, and so does the search box. The pages `caracole serve`
writes itself (Requests, Look up and its search box, a song's pick) do the
same.

**Select**, beside the Key menu, puts a
box at the start of each song's line: tick songs in the order they go in the
songbook (each box shows its place, and a screen reader says it: "Pick Creep by
Radiohead, 2nd"). A tap anywhere on a line ticks it, or unticks it: while you
select, each line's button and "⋯" are put away, a request's line still says
how it goes but without its links (Details), and a tap on its title opens
nothing, so a tick never opens a file by mistake. A line's **Add to a
songbook…**, under its "⋯", does the same with that song ticked, the bar's menu
or name field ready. Search, filter and sort between ticks; the bar at the
bottom counts them, `3 selected`. Give the songbook a name and tap Make
songbook, or pick a songbook there is in the menu (instead of New songbook)
to Add to it; Clear unticks them all. The × at the start of the bar, or
Select pressed again, leaves the mode, and the ticks wait, unseen, for when
you come back. On a phone the bar is one line,
`× 3 selected · Make songbook…`, and its button unfolds the menu and the name
field (its ▾, or Escape, folds them away again). On the file on disk, which
can't write anything, Make songbook gives the command to run where caracole
runs, folded under "The command to run", with Copy beside it:
`caracole songbook make 'Beach nights' 'Muse - Hysteria' 'Radiohead - Creep'`,
each word in single quotes, so that no shell changes a `!`, a `$` or a quote
in a name.
On `caracole serve`, the button makes the songbook, and the page opens the
Songbooks tab on it (see below).

#### The Songbooks tab

The page's second tab lists your songbooks (see [Songbooks](#songbooks)) as
lines: each one's name, how many songs, how many still have no sheet in it,
and the day caracole last made its files (`3 songs · 1 without a sheet ·
changed 2026-10-20`). Open one and it shows as a set list, beside the list
from 900 pixels wide, in its place on a phone (**‹ Songbooks** goes back):
each song a line, as dense as the library's with a mouse, with its place, its
title (which opens its sheet), its artist and where the songbook plays it, its
chip: "G Dorian, capo 0" for a song with a setting of its own there, its own
version's key ("A Minor, capo 0") for one without, or why it has no sheet ("No
sheet yet", "Not in the library"). Its files come first: **PDF**, **Phone
page** (`songbook.html`) and **ChordPro**, each opened in the same tab. The
address remembers the songbook open (`#tab=songbooks&book=Campfire`).
**+ New songbook** turns Select on, in the library, its bar ready for the name:
tick its songs and make it.

On the file on disk the tab changes nothing: under the set list it gives the
commands that do, where caracole runs (`caracole songbook add`, `move`, `set
… --key G --mode dorian --capo 0`, `remove`, `rename`, `delete`), or edit
songbooks.toml. On `caracole serve` each song can be dragged to its place, set
to play elsewhere, taken out or got now, and the songbook gets its missing
songs, a song from your library or the indexes (**Add a song**), another name,
or deleted (see [caracole serve](#caracole-serve) below). On a touch
screen each grip, chip, button, ×, title and menu is a thumb's target, 44
pixels at least.

Each song's entry in the page's data (the `<script type="application/json"
id="songs">` block) has the same `key` and `key_source` as its info.json, and
`source`, where its sheet came from (`ug`, `lacuerda`, `auto`…); each of its
files has its own `source`.

### The sheet viewer

Each sheet's `sheet.html` (`sheet (auto).html` for an auto sheet) is the sheet
as a page for the phone. Like `index.html` it is one file that opens from the
synced folder with no server, and loads nothing from the network. Don't serve
the library folder as it is to other browsers: anyone with a synced device
could put a page of their own there, which would run as your server's own.
caracole records each viewer it writes, so that a server can tell its pages
from anyone else's. It is made at render time from the song's own
`.cho`, and stays in the song's folder: nothing of the sheet is copied
anywhere else. It links back to `index.html` and to the PDF beside it.

- **Chords over the lyrics**, in bold rust. A long line wraps between words,
  never between a chord and its syllable, and a chord reaches over the words
  after it, so the lyrics read without gaps. A chord never reaches past the
  edge of the screen: at the end of a row with less room left than the chord
  is wide, it goes on to the next row with its words.
- **The tab's notes**: what a tab says before its first section or its first
  riff (the tabber's comments, a link, a chord legend) is shown small and
  muted, two lines of it; **More** opens the rest, and works without
  JavaScript too. Printed, all of it prints. Chords or a verse before the
  first section are the song, and nothing is folded then.
- **On a wide screen** (1100 px or more: a laptop), the song reads down one
  column, centred, in slightly larger text. A song short enough for the
  window to show it whole in two columns is shown in two, side by side; a
  longer one stays in one, as it would otherwise run down the first column
  and back up the second. The viewer measures again when the window or the
  text size changes, and when the settings' rail opens beside the song. From
  1200 px the rail of necks (below) takes 300 px on the left, and the song is
  measured beside it: two columns then need a wider window (at 1280 px a song
  reads in one, at 1600 px two fit as they did at 1280 px without it).
- **Tap a chord** for its fingerings: up to four shapes from chords-db, after
  any the sheet gives, with the fingers, the barre and the fret they start on
  (swipe, or ‹ ›, for the next). Every place the chord is played lights up
  while its card is open. The card leaves the song in view: on a phone it
  sits at the foot, above the bar, about 200 px tall, and the song scrolls
  under it (a chord tapped where the card comes up moves above it, with its
  words); from 900 px wide it opens next to the chord, and goes with it as
  the page scrolls. It keeps its size from one shape to the next. Tap another
  chord and the card shows that one; × or Escape closes it. The shapes come
  from [chords-db](https://github.com/tombatossals/chords-db) by David Rubert
  (MIT licence, whose notice is at the foot of every page); a chord it has no
  shape for shows the closest one, saying so. A shape the sheet gives comes
  first, on the card ("As the tab plays it") and in the strip: a tab's chord
  legend (`Cadd9 (x32033)`, `Dsus4/F# 2x0233`), which gives no fingers (they
  show where chords-db has the same shape), or a ChordPro `{define}` in a
  sheet of yours. It counts only for the very chord it was given for, and only
  where it plays that chord: transposed, Cadd9 becomes a Dadd9, with
  chords-db's shapes, and so does a capo moved off the sheet's fret.
- **A neck per chord**, on a laptop (1200 px wide or more): a rail on the
  left lists each chord of the song once, in the order it first comes, with a
  guitar neck (frets 0 to 15, the high e on top) showing every shape of it in
  a colour of its own, the tab's own ringed (a note several shapes play is a
  smaller dot for each, side by side in the fret, the first shape leftmost,
  and an open string several play a ring for each left of the nut, so none
  hides another and a click on one plays its shape), and a legend under it that
  numbers them as the card counts them ("2 of 5") and names them: "1 · the
  tab's", "2 · open", "3 · fret 3", so two shapes at one fret ("1 · fret 1",
  "2 · fret 1") have names of their own. Click a shape, on the neck or in the
  legend, to play it: the strip and the chord's card show it, and the address
  keeps it, as the card's ‹ › do (and the rail follows the card's). In a
  legend the arrow keys go from shape to shape; Tab stops once a chord. The
  necks follow the key, the capo and the mode, and two chords shown by one
  name (A# and Bb, transposed to B) share one neck. The rail scrolls on its
  own, the song and the bar move over for it, and it isn't printed; on a
  narrower screen or a phone, the chord's card is where the shapes are.
- **The key line** under the title says how the song is played. With a capo,
  it names the key of the shapes you play, the capo and the key the song
  sounds in: "Em shapes · capo 2 · sounds F#m". With none, the key alone:
  "Key Em". Each says where the key came from.
- **The bar** at the foot of the page holds what you reach for while
  playing: `− Em +`, a guitar, `Aa`, `▶` and `⋯`. − and + move every
  chord, its shapes and the key a semitone at a time, with the key you play
  between them in short: "Em" over "shapes · capo 2" (or "key" with no
  capo), and "· +1" once transposed, or "capo 2 · +1" on a screen too
  narrow for all of it, and "capo 2" over "+1" on the narrowest; a key too
  long for its room ("Ab mixolydian") is a little smaller. A screen reader
  hears the whole line ("Em shapes · capo 2 · sounds F#m · +1"). **The
  guitar** shows the strip of every chord's shape (below), or hides it
  again, as Show all in the settings does: it stays pressed while the strip
  shows, and the two always agree. Pressed further down the song, it takes
  the page up to the strip, so the shapes are in view; a sheet without
  chords has none. **Aa** opens a small box over the bar with the text
  size and A− and A+, nothing dimmed behind it; a tap anywhere else, or
  Escape, closes it. **▶** scrolls the song by itself (below). **⋯** opens the
  settings. The bar slides away as you scroll down the song, and comes back
  when you scroll up, tap the page or reach the end, where the song's last
  lines and the footer end above it. It stays while the browser puts you
  back where you were in the song, and while the keyboard's focus is on one
  of its buttons; Tab reaches each of them from the end of the page, and
  brings the bar back.
- **The settings** (⋯), headed by the key line, leave the song in view, so
  you see its chords change as you transpose, move the capo or change the
  mode: on a phone they sit at the foot, above the bar, in at most 45 % of
  the screen, and the song scrolls under them; from 900 px wide they are a
  rail beside the song, which moves over for them. Nothing behind them is
  dimmed or out of reach. A chord's card opened with them covers them on a
  phone, and sits by its chord beside them on a wider screen; Escape closes
  the card first, then the settings, and gives the focus back to what opened
  each. Among them: **Transpose**, as − and + do, with the semitones counted; Reset goes back to the song's
  `[transpose]`, where the viewer starts, like the PDF. A song with a version
  of its own (`[version]`, Make this my version) starts in it, key, capo, mode,
  shapes and swaps, whenever its address names no other (an address with a
  `t=`, `mode=`, `capo=`, `alt=` or `at=` is that version instead); the address
  then always names its `t=`, and **Reset everything** goes back to it. What
  the browser kept for the page before the song had that version is left
  out. **Capo**, on every
  song, moves the capo a fret at a time, from none to
  the 11th; Reset puts it back where the sheet has it. The song sounds the same
  wherever the capo is, and the chords show the shapes to play there: Em shapes
  with capo 2 become F#m shapes with no capo, or Dm shapes with capo 4. The
  capo stays on its fret when you transpose, as on a guitar, so the shapes
  move instead. In an awkward key it also suggests frets where open shapes play
  it (Bb: capo 1 with A shapes, capo 3 with G shapes); tap one to play them.
  The fret suggested is where the capo goes, and it may be lower than the
  sheet's, or no capo at all (a sheet in G shapes with capo 2, transposed down
  two: no capo, G shapes).
- **Instead, in the key**: the chord's card also lists chords to play in its
  place that keep to the key: colours on the same root (a seventh, add9, sus2,
  a sixth), an inversion, and chords that share most of its notes (Am or Em
  for C in C major). Tap one to see its shapes, then play it for every one of
  those chords in the song; changed chords are underlined.
- **Mode**: with C minor, switch to C major, or to any mode on C (Dorian,
  Phrygian, Lydian, Mixolydian, Locrian). Each chord's notes move to the same
  degree of the new scale, so Ab becomes Am and Bb7 a Bm7b5; a note outside
  the key, such as the G major chord's B in C minor, stays where it is.
- Every chord's shape in a strip above the song (the guitar in the bar, or
  Show all in the settings; kept for the page, as the text size is): the
  shapes alone, large enough to read at a glance; tap one for its card,
  with the fingers. Reset everything, at the foot of the settings, puts the
  transposition, the mode, the capo and the chords played instead back as
  the viewer starts them.
- **Scrolling by itself**: ▶ in the bar counts down 3 seconds to give you
  time to get your hands on the guitar (press the count to start at once),
  then scrolls the song at a steady pace, with the screen kept on where the
  browser allows it. While it is on, a pill steers it, just above the bar's
  place: − and + change the speed (1 to 30) as it scrolls, ❚❚ pauses and ▶
  goes on after another countdown, and × ends it. The bar is out of the way
  while the song scrolls, and back under the pill while it is paused, so you
  can transpose or change the text size before going on; the pill stays
  where it is, so a second tap lands on it again. A finger on the
  page, the mouse wheel, a key that scrolls, a
  scroll by hand or a chord's card pauses it, so the page is yours to read
  until you press ▶, which stays within reach (above the card, on a phone,
  with the bar kept under the card while the song scrolls on);
  it pauses at the end of the song too. A bigger text
  scrolls as much faster, so a speed keeps its pace through the song. With
  reduced motion asked for in your system's settings, the countdown shows the
  seconds alone, with no ring.

The viewer remembers its settings for each song in the browser, the scroll
speed, the text size and the shape chosen for each chord among them: a chord
named otherwise when the page opens (an address with another key, mode or
capo) starts at its first shape. It keeps the transposition, the mode, the
capo, the text size and the scroll speed in its address too
(`sheet.html#t=2&mode=aeolian&fs=20&speed=8`), and so the shape chosen for a
chord, on its card or its neck (`at=3.2`: chord 3, its third shape), and the
chords played instead of others (`alt=ionian.0.7.maj7.`: mode, chord, root,
suffix, bass), so a reload or
Back keeps them where the browser keeps nothing, as when `caracole serve` sends it (see
[caracole serve](#caracole-serve)). Its key is its sheet's, found as for
info.json (see [The song's key](#the-songs-key)): the human sheet's from the
tab, or estimated from its chords, and the auto sheet's heard in the audio;
the page says which. With a capo, a tab may name the key the song sounds in
rather than the shapes' (F# for a song played in C shapes with capo 6): when
the chords are in the named key lowered by the capo, the viewer takes them as
the shapes and the named key as the sound ("C shapes · capo 6 · sounds F#").
Beside a human sheet, `sheet (auto).html` keeps to the
chords the model heard, which may be in another key than the tab (another
transposition, or a capo).

On Android, a file manager that opens the page through a `content://` address
can break its links to the songs' files. A browser, or an HTML viewer that
opens the file directly, works.

### Where each file came from

Each source has a mark: the site's own icon for Ultimate Guitar, LaCuerda,
LRCLIB (lyrics), gtptabs.com, MuseScore and YouTube, a ♪ for a sheet the
audio model wrote (auto-chords) from audio you bought, YouTube's for one it
wrote from the audio caracole took from YouTube, and a ↓ for a file you filed
from `_inbox/`.
A site's mark is named for screen readers ("from Ultimate Guitar").

A site's icon is its favicon. The nightly run's icons step asks each site for
it once, from the first night the library has something from that site (a
sheet, a Guitar Pro page to click, lyrics, MuseScore's pages), with that
site's own polite client: its robots.txt, budget, pauses and cooldown, and
every answer cached forever. It asks for `/favicon.ico`
first; when that gives no icon, the home page, for an `<link rel="icon">` or
`apple-touch-icon` on the same site (two at most, never an SVG). The icon is
kept in the cache folder, as `icons/<site>.png`, small and cleaned:

- only a PNG or an ICO is read, by its bytes, up to 256 KB;
- a PNG keeps its image chunks alone, with no text, metadata or animation,
  once each chunk and its pixels check out;
- an ICO gives its image nearest 32 pixels, turned into a PNG;
- anything else, an SVG too, is refused;
- a kept icon is at most 256 pixels a side and 16 KB.

The page inlines each icon (a `data:` URI), so it still loads nothing from the
network. A site whose icon can't be had (it blocked caracole, robots.txt closes
it, it has none, or it wasn't asked yet) shows a small lettered badge instead:
UG, LC, LR, GT, MS, YT. A site that gave no icon, or failed, is asked again a
week later, its answers older than a week asked for once more, so a site that
puts an icon up later gets it then; a spent budget or a cooldown leaves it for
the next run. The nightly run doesn't ask YouTube: its youtube step runs
yt-dlp, which fetches no icon. `caracole icons` asks now (see
[One step at a time](#one-step-at-a-time)), and deleting `icons/` in the cache
folder makes caracole read them again from its cache of the answers, however
old, with no request.

### caracole search

`caracole search [QUERY]... [--limit N] [--add N] [--key KEY] [--artist NAME]
[--title TITLE]` looks in three places, and sends no request: your library, the
offline Ultimate Guitar index and LaCuerda's (see below):

    $ caracole search creep
    In your library
      Radiohead - Creep · wanted, no sheet yet · no folder yet

    On Ultimate Guitar (offline index)
      1. [UG] Radiohead - Creep · chords×2 tabs×1 guitar-pro×1 (incl. acoustic)
         https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169
         in your library
      2. [UG] Stone Temple Pilots - Creep · chords×1
         https://tabs.ultimate-guitar.com/tab/stone-temple-pilots/creep-chords-5001
         caracole add "Stone Temple Pilots" "Creep"

    On LaCuerda (offline index)
      nothing matches

- **In your library**: every song, whatever its status, with its key when it
  has one (`Key G major (from the tab)`) and its folder. A song with a sheet
  is tagged with where the sheet came from, as `index.html` marks it with the
  site's icon: `[UG]`, `[LaCuerda]`, `[auto]` (the audio model), `[YouTube]`
  (the audio model, from the audio caracole took from YouTube), as in
  `[LaCuerda] Soda Stereo - De Música Ligera · found · …`. A song in review
  also shows its first three candidates, as the matcher found them:

      epic - I'm not sorry for loving you · wanted, needs review · no folder yet
         Did you mean (`caracole review` settles it):
           94  misc-musicals/epic-the-musical-not-sorry-for-loving-you (catch_all)
           82  bill-fox/im-not-over-loving-you (title_only)

- **Removed from your library**: right after your library, the songs
  `caracole remove` took out that the words match (Chinese as pinyin, whole
  words only), each with the date it was removed and the line that asks for it
  again, which is a wanted.txt line:

      Removed from your library
        宋冬野 - 斑马斑马 · removed 2026-10-20
           bring it back: caracole add "宋冬野" "斑马斑马"

  The group is absent when no removed song matches (and for `--artist` and
  `--title`). A removed song is never what Enter or `--add` acts on; once
  `caracole add` brings it back, it is in your library and not in this group.

- **On Ultimate Guitar**: numbered hits from the offline index, each tagged
  `[UG]`, with its tabs per type, one of its pages, and the `caracole add`
  line to paste. The UG artist pages caracole has read (see
  [caracole fetch](#one-step-at-a-time)) are searched too: every tab each one
  listed, bare ids included, which UG's sitemaps list without names. Their
  names are compared in each script UG writes them in ("Song Dongye (宋冬野)"
  is 宋冬野 and Song Dongye, "斑马 斑马 Banma Banma Zebra Zebra" is 斑马斑马 and
  Banma Banma), Chinese as pinyin, whole words only. A song such a page lists
  is one hit with the index's tabs of it, its tabs counted once; its page is
  the page's best tab, of the best type, then the best rated, each rating
  weighed by its votes as `caracole fetch` weighs them (pulled toward the
  average of those tabs, the more the fewer votes it has, so a 5.0 from one
  vote rarely beats a 4.8 from 300), with UG's rating (`rated 4.8 (120
  votes)`, nothing for a tab nobody rated); and its artist is named as your
  songs name them (your 宋冬野, or else the original of UG's two names), so
  its line adds the song under that name:

      $ caracole search 斑马
      …
      On Ultimate Guitar (offline index)
        1. [UG] 宋冬野 - 斑马斑马 · chords×2 · rated 4.8 (120 votes)
           https://tabs.ultimate-guitar.com/tab/4180894
           caracole add "宋冬野" "斑马斑马"

  Their artist is an artist line too (`caracole search 宋冬野`, `caracole search
  --artist 宋冬野`). Looked up with `caracole get`, or added for the nightly run,
  the song is looked for on that artist page, whose address caracole knows
  already. A song of one of UG's catch-all artists (`misc-musicals`, `misc-soundtrack`…,
  see [caracole match](#caracole-match---dry-run)) is also scored on its title
  alone, with and without words such as "the musical", so
  `caracole search epic not sorry for loving you` finds
  `misc-musicals/epic-the-musical-not-sorry-for-loving-you` first. Its hit has
  no `caracole add` line: added with UG's names, the song's artist would be
  "Misc Musicals". It says instead that its artist is a catch-all, to add the
  song as you know it and pick that hit in `caracole review`:

      1. [UG] Misc Musicals - Epic The Musical Not Sorry For Loving You · chords×1
         https://tabs.ultimate-guitar.com/tab/misc-musicals/epic-the-musical-not-sorry-for-loving-you-chords-4742072
         misc-musicals is UG's catch-all artist, no one's name: add the song as you know it,
         then pick this hit in `caracole review`:
           caracole add "<the show or singer>" "<the song>"

QUERY is words of the artist, the title or both, so a song whose artist you
don't know is found by its title alone, and an artist by their name alone.
When the query is an artist's name, and that artist has a song with more tabs
than any song titled like it, the artist leads: the number of their songs and
tabs, their three most tabbed songs, then the songs titled like it, all
numbered in one list:

    $ caracole search oasis
    …
    On Ultimate Guitar (offline index)
      Oasis, an artist: 195 songs (1,193 tabs). The most tabbed:
      1. [UG] Oasis - Dont Look Back In Anger · chords×10 tabs×12 guitar-pro×9 power×1
         https://tabs.ultimate-guitar.com/tab/oasis/dont-look-back-in-anger-chords-6097
         caracole add "Oasis" "Dont Look Back In Anger"
      …
         All 195: caracole search --artist "Oasis"

      Songs titled like oasis:
      4. [UG] A Great Big World - Oasis · chords×4
      …

When a song leads, the songs come first, and an artist of that name is a
line of its own: `caracole search wonderwall` lists Oasis's, Ryan Adams's and
Cartel's Wonderwall, then `Also an artist: Wonderwall, 9 songs (13 tabs)`
with its `caracole search --artist "Wonderwall"` line; the band's songs are
left out of the list. Beside an artist whose name is the query, one whose name
is only near it is left out, with its songs: `caracole search eagles` lists no
Beagles. The offline index knows no ratings (only the artist pages caracole
read do), so the number of
tabs is what puts the song you probably mean first (Radiohead's Creep before
Stone Temple Pilots'). A catch-all such as `misc-musicals` is never an
artist.

Matching ignores case,
accents and punctuation (`AC/DC`, `R.E.M.`), survives a typo, and also
compares Chinese as pinyin, as whole words only, as the matcher does: 斑马
finds a title written `ban-ma` or `banma`, never the letters inside
`suburban-male` or `band-maid`, and pinyin matching only part of a name is
never a strong hit. It reads an index of the UG index's names, so a
word of three letters or more is looked up in milliseconds, not by reading all
1.6 million rows: a song or an artist answers in 5–25 ms on a full index, and
a query made only of very common words in 50–160 ms ("the" about 0.1 s, "i
love you" about 0.15 s): such a word is in tens of thousands of names, so it
brings in only the thousand shortest of them, which hold its exact titles and
artists, and the names every word of the query is in; the first hits are the
same as when every name was ranked. `--limit N` (or `-n N`) shows up to N hits from
each place, 10 by default. `--add N` adds UG hit N, numbered as the same
search printed it, to wanted.txt and syncs it,
the same way `caracole add` does, and says so in the same one line (`-v` adds
its line in wanted.txt and the song's key). N can be at most `--limit`, so only a hit the
search shows can be added, and a hit your library already has under another
name is left alone. A hit under a catch-all artist is refused (exit 2, nothing
written), with the same advice as its hit. When nothing matches well, or the query has accented or
non-Latin letters, the command also explains bare ids, unless a strong hit comes from an artist page
caracole has read (caracole sees that artist's tabs), and prints the
`[artist_url]` line to paste, for the artist's page or one of their tab pages,
with the table's header only while overrides.toml has no `[artist_url]`
entries. The line is keyed by the artist of a song of yours the query finds,
never by a placeholder such as "misc" (a line `misc - 斑马` in wanted.txt),
else by the query itself; a query may be a title, so the hint then adds that
caracole needs the song's artist too (`caracole add ARTIST "斑马"`): nothing
asks a site who sang it. For an artist whose page overrides.toml has already, under any form
of their name, it gives no line and says so. The search reads
overrides.toml for this hint alone, and still works when the file can't be
read.

`--artist NAME` lists one artist's songs: yours by them first (their name
in any form, so `--artist 宋冬野` finds your 宋冬野 songs, and UG's "Song
Dongye" is the same artist), then all of theirs in the offline index, most
tabbed first, numbered for `--add`, `--limit` of them, with how many more
there are (`… and 365 more: see them with --limit 368`). QUERY words given
with it search their titles: `caracole search --artist oasis live`. For an
artist the index lacks (UG lists 宋冬野 only by a bare id), it prints the
`[artist_url]` line to paste, keyed by NAME. `--title TITLE` lists songs of
that title by any artist, by tabs, never an artist's songs: it takes the
whole title, so it can't go with QUERY words (exit 2); with `--artist`, it
searches that artist's titles. Neither goes with `--key` (exit 2).

**On LaCuerda** comes after Ultimate Guitar's hits, numbered on, from
LaCuerda's local index (see [caracole lacuerda](#one-step-at-a-time)), which
holds every artist of LaCuerda's listings the nightly run has read, and the
songs of the artists whose page caracole has read. Its names are compared as
Ultimate Guitar's are, also with their words run together: "rockstar" finds
Los Rock Star, and "banma" a song LaCuerda writes 斑马斑马, whose pinyin is
`ban-ma-ban-ma`. An artist the query names
is a line of their own, with the songs LaCuerda's listing counts, then their
most popular songs with chords the index holds; or, when caracole has never
read their page, the line that reads it, one request:

    $ caracole search estopa
    …
    On LaCuerda (offline index)
      Estopa · LaCuerda · 159 songs. The most popular with chords:
      1. [LaCuerda] Estopa - Como Camarón · 3 versions, with chords
         https://acordes.lacuerda.net/estopa/como_camaron
         caracole add --lacuerda https://acordes.lacuerda.net/estopa/como_camaron "Estopa" "Como Camarón"
      …
         All 12 the index holds: caracole search --artist "Estopa"

    $ caracole search joaquin sabina
    …
    On LaCuerda (offline index)
      Joaquín Sabina · LaCuerda · 241 songs
         caracole hasn't read their page: caracole lacuerda --artist joaquin_sabina reads it (one request)

While the nightly run hasn't read the listing of a name's letter whole, the
index can't tell whether LaCuerda has an artist it doesn't list: for a query
it has no artist by, under such a letter, the group ends with the line that
reads the page of that name now. The name is the artist the query names on
Ultimate Guitar, by their whole name or by part of it (`Enrique Bunbury` for
"bunbury"), else an artist whose whole name starts or ends the query and whose
songs Ultimate Guitar's index reads it as (`Estopa` for "estopa como camaron",
while caracole hasn't read their page; never `Fito` for "fito paez"), else the
query. A query LaCuerda's own index answers well gets no such line: a song by
its title ("como camaron" is Estopa's Como Camarón), or by an artist it lists or
holds the songs of ("estopa como camaron", once their page is read), and
neither does a query Ultimate Guitar's index reads as a title ("creep"):

    $ caracole search estopa
    …
    On LaCuerda (offline index)
      nothing matches

      LaCuerda's index is still being read: 2,957 artists so far, with #, A, B read
      whole; the nightly run reads the rest.

      LaCuerda hasn't listed E yet: caracole lacuerda --artist "estopa" reads the
      page of “estopa” now (a request for each spelling of the name tried, usually one).

A song's line adds it as your pick there (`caracole add --lacuerda`), so the
nightly run keeps that sheet; a song LaCuerda has no chords for ("1 version,
no chords") is added by its names alone. `--add N` takes LaCuerda's hits too,
numbered as printed, and records the pick the same way. `--artist NAME` lists
the songs the index holds of the LaCuerda artist NAME names, LaCuerda's most
popular first (`Estopa · LaCuerda · 12 of their 159 songs in the index, the
most popular first:`), after Ultimate Guitar's, and `--title TITLE` its songs
of that title. Names are compared as Ultimate Guitar's are: as words, accents
folded, a leading "Los" and an artist's "y" aside, Chinese as pinyin, as whole words only (斑马
finds 宋冬野's 斑马斑马 and a title written `banma`, never the letters inside `Bohemia Suburbana` or
`El Bananero`; pinyin matching only part of a name is never a strong hit). While the
index is empty the group says so (`Nothing yet: LaCuerda's index is empty: the
nightly run reads its listings of every artist`), and while the nightly run
still reads its listings it ends with what it has: `LaCuerda's index is still
being read: 2,957 artists so far, with #, A–C read whole; the nightly run reads
the rest.` (the artists counted include those of a letter read in part).
LaCuerda has no search caracole uses: everything listed comes from the local
table, and nothing asks LaCuerda anything.

`--key KEY` keeps only your songs in that key (see
[The song's key](#the-songs-key)), with or without QUERY; without it, your
songs in the key, by name. It lists up to `--limit` of them, and says how many
more there are:

    $ caracole search --key Am
    In your library, in A minor
      [LaCuerda] Soda Stereo - De Música Ligera · found · Key A minor (estimated from the chords) · /home/you/Tabs/Soda Stereo/De Música Ligera

    The offline Ultimate Guitar and LaCuerda indexes have no keys: search them without --key.

KEY is written the way tabs write keys, in either case: `"A minor"`, `Am`,
`am`, `F#`, `"Bb major"`, `bbm` (B flat minor), `"La menor"`; any spelling of
the same key matches (`Gbm` finds F# minor). The
offline indexes know no keys, so `--key` leaves them out, and `--add` can't go
with it. A KEY that is no key exits with status 2.

### caracole serve

`caracole serve [--address ADDRESS] [--port PORT] [--allow-host NAME]…
[--token-file FILE]` serves the library page over HTTP, at
`http://127.0.0.1:8737/` by default, with what the file on disk can't do:

- **Search as you type.** The library page's search box filters your songs as
  you type, here as on the file, and from the third letter (the second with a
  Chinese character in it) it searches the sites too, a moment after you stop:
  no Enter, and no button. The list and its buttons make way for the results,
  your songs among them still keeping to the status buttons, the Key menu and
  an artist's name you pressed, which the results' head says ("Your songs
  here: wanted · by Soda Stereo · in A minor"), with Show all of yours, which
  lets every song of yours show, there and in the list; the sites' songs are
  what the sites have, whatever the buttons show. The results come under the
  same artist headers as the list's, each header counting the songs
  of theirs you have and, for an artist the query names, the songs Ultimate
  Guitar's, LaCuerda's and gtptabs.com's indexes list of theirs ("Estopa · you
  have 2 · UG 60 · LaCuerda 159 · Guitar Pro 12": Guitar Pro is gtptabs.com's
  songs with a file there, a title uploaded twice one song; none while
  gtptabs.com is turned off). Under an artist come your songs that match (up to five in
  all, as their lines, with all they offer, a title opening its sheet, and All
  N of your songs above the groups when more match; a close match the filter
  missed, a typo say, too), the songs you removed that match (below), then what
  caracole's offline indexes hold of theirs: **Ultimate Guitar** (eight songs,
  and the artists the query names, as in [caracole search](#caracole-search),
  each with their three most tabbed songs, then "+ 57 more by Estopa", which
  lists the rest in their group, fifty at a time), **LaCuerda** (the artists
  the query names, each with their most popular songs with chords, and "+ N
  more by Estopa on LaCuerda" for the rest the index holds of theirs, then five
  songs: "estopa" finds Estopa; for an artist whose page caracole has never
  read, the group says how many songs LaCuerda lists and offers Read their
  page, which queues `caracole lacuerda --artist` (one request, at the lookup
  pace) and lists them in the group once it has run; and for a query it has no
  artist by, while the nightly run hasn't read the listing of its letter whole,
  the results say so under the groups and offer Read LaCuerda's page for
  “estopa”, which queues `caracole lacuerda --artist estopa` (a request for
  each spelling of the name tried, usually one), then lists their songs in a
  group of their own, first, or says what LaCuerda answered: `Not found:
  LaCuerda has no artist page for estopa.`, or, for a cooldown, a block, a
  spent hour's budget or an error, `Not read: …`, with a link to the request's
  output. The name is chosen as `caracole search` chooses it: the artist the
  query names on Ultimate Guitar, else the one of theirs whose name starts or
  ends it, else the query; a title there, "creep", or a song LaCuerda's index
  has, "como camaron", gets no offer. Once a page is read, a search finds their
  songs at once. When LaCuerda alone has the artist the query names, and
  Ultimate Guitar's index nothing that matches well ("andres calamaro": only
  Javier Calamaro's songs), LaCuerda's artist comes first) and **gtptabs.com**
  (five songs with a Guitar Pro file there). A song the sites have under the
  same artist and title is one line, with each site's mark and what each has
  of it ("chords ×9 · LaCuerda ×3 · Guitar Pro file": Ultimate Guitar's tabs
  per type, LaCuerda's versions, gtptabs.com's file): they share the song's
  identity key, made from its artist and title as caracole makes your songs'.
  The indexes hold no ratings (only the sheets caracole fetched have them), so
  a line shows counts, never stars. A site's row of a song of yours is your
  song's own line, and puts that artist's other rows under your artist's
  header (Ultimate Guitar's "Song Dongye (宋冬野)" under your 宋冬野).
  **MuseScore**'s pages come last, under a header of their own, as its
  sitemaps name no artist: five pages whose title is what you typed, or what
  you typed less an artist's name before or after it, when that artist has a
  song of that title in the Ultimate Guitar index, gtptabs.com's or your
  library ("oasis wonderwall" finds the Wonderwall pages, and "oasis live
  forever" never a page titled Oasis or Forever), each a possible match. The
  results follow what you type; a search typed over stops at once, and only
  the newest query's answer is shown, the older one staying until then. The
  line under the box says "Searching the sites…", then how many each site has,
  and the results end with the sites left out and why: one turned off in
  caracole.toml, or one whose index the nightly run hasn't read yet
  (MuseScore's while it blocks caracole, LaCuerda's before its first
  listings); and those searched in part: LaCuerda's, while the nightly run
  still reads its listings ("Searched in part: LaCuerda (its index is still
  being read: 2,957 artists so far, with #, A–C read whole; the nightly run
  reads the rest)."). Searching asks no site anything: it reads the indexes
  alone (5–25 ms a query on Ultimate Guitar's, up to about 0.15 s for very
  common words), takes no lock and spends no budget, and so does "+ N more".
  **Enter never spends a request**, however clear the best result: it moves to
  the first result's line (once the query's answer is in), from which Tab goes
  on to its name and its button; Get it, or a click or a key on the name,
  does. Escape, or Back to your songs, goes back to
  the list with your search and buttons as they were (Escape again clears the
  search; Enter, or typing on, brings the results back), and the box's × back
  to all your songs; either way a song asked for there has its line (see
  below); ↓ goes from the box to the first result's button. The address keeps
  it (`#q=wonderwall&all=1`).

  **Get it** on a line looks the song up at once: as Ultimate Guitar's song
  when the line has one, as `caracole get --ug …` does, recording the pick in
  overrides.toml (`[match]`), so nothing waits for a review, and its
  gtptabs.com stage downloads the Guitar Pro file for a song that has none;
  else as LaCuerda's, as `caracole get --lacuerda …` does, keeping that
  LaCuerda sheet (`[lacuerda]`), whatever Ultimate Guitar has (one with no
  chords there, "LaCuerda ×1, no chords", is looked up by its names); else by
  its names, as `caracole get` does. Its "⋯" has what each site has: Ultimate
  Guitar's versions ("Chords 2 of 13", each with an "on UG" link to look at it
  there first), each looked up as `--tab …` (`[pin]`); LaCuerda's page and,
  beside Ultimate Guitar's song, Get it with this sheet, which keeps
  LaCuerda's; gtptabs.com's page. A MuseScore page is a link to open, as
  caracole never fetches from MuseScore. The line then says how it goes, on a
  line of its own ("Sending…", "Fetching from Ultimate Guitar…", "Ready · Open
  sheet"), and once the sheet is kept the line is the song's own line, its
  sheet its button. **A result's name does what its Get it does**: a click on
  "Wonderwall", or Enter or Space on it, looks the song up just as Get it would,
  and while that request is on its way the name, like the button, can't be
  pressed again. A removed song's name does what its Add again does (below). A
  song of yours whose title opens its sheet keeps opening it; an artist's name
  still shows that artist's songs; and on the file, with no caracole serve, no
  name gets anything. A newer answer drawn while it goes (a search typed on)
  keeps the line where it has the song, with its request line; one it hasn't
  moves the request under the box as its line ("Just requested"), its request
  line going on there. A song your library has already, under its own names
  (UG's slugs write AC/DC as "Acdc" and 宋冬野 as "Song Dongye"), is your own
  line; one new to the library since the page loaded says In your library and
  Get it again, and is looked up as your song: no second song, and no line
  added to wanted.txt. A song your library hasn't, from Ultimate Guitar,
  LaCuerda or gtptabs.com, also has **Add for tonight's run** under "⋯": it
  goes into wanted.txt under the site's names, as Request does with Fetch it
  now unticked (a song only LaCuerda has as `caracole add --lacuerda …`, the
  pick recorded: its request says Added: tonight's run gets the sheet you
  picked on LaCuerda, as its line's "⋯" does, with a link to that sheet's
  page, and it waits for no Ultimate Guitar review of other artists' songs of
  its title), and the nightly run looks it up (not a song under one of UG's
  `misc-…` names, which are no one's: request it by name as you know it).
  Back to your songs, a song new to the library gets a line of its own under
  the box ("Just requested").

  **A song you removed** (`caracole remove`, or Remove… on the page) that the
  query matches shows in its artist's group as "Removed 2026-10-20", with
  **Add again**, which asks for it again as the request form does with Fetch
  it now ticked: a line in wanted.txt, which brings a removed song back (see
  [caracole remove](#caracole-remove)), then its lookup. It is never what
  Enter acts on.

  `/lookup`, the lookup page, still answers, though no page's header links to
  it any more (the requests page's has Library alone): the same search of your library
  and the Ultimate Guitar and LaCuerda indexes, whose Get it (or a song's name,
  which does the same) reads the sheet on the page as it arrives, stage by
  stage. Its Enter acts on the song you clearly meant (one of
  yours opens; an Ultimate Guitar song is looked up), the leading artist's
  songs (LaCuerda's artist when LaCuerda's group leads, which asks LaCuerda
  nothing), or nothing when nothing stands out. `/lookup?q=WORDS` opens it with
  that search, and a lookup posted without JavaScript lands there. It alone
  looks a song you already have up again: on the library page the index's
  rows of a song of yours are folded into your song's own line, which has
  neither Get it again nor a version to pick, while here your song keeps its
  own row, with Fetch again, and each site's row of it its own: Ultimate
  Guitar's Get it again, with a version of theirs to pick under "⋯", and
  LaCuerda's, which keeps that LaCuerda sheet.
- **Request a song.** Under the results, "Not in the list? Request it by
  name" takes an artist, a title and, optionally, the album and the length,
  filled in from what you searched ("Muse - Hysteria"; an artist's name alone
  when an artist leads, else a title) until you type into a field yourself. The song goes into wanted.txt at once,
  as `caracole add ARTIST TITLE` writes it (a song listed already is left as
  it is), then `caracole add` runs to put it in the library.
- **Fetch it now.** Ticked, as it is by default, the request is looked up at
  once instead, as `caracole get` does it: its sheet in seconds, then its PDF,
  lyrics and the rest. Each wanted song's line has Fetch now for its button,
  which does the same, except on a song that needs review, which has no UG song
  to fetch until you say which it is (`caracole review`, or a `[match]`, `[pin]`
  or `[reject]` entry in overrides.toml): its line has Pick the match instead
  (below), and Get it on an
  Ultimate Guitar song of the page's search picks one too.
- **Pick the match.** On a song that needs review, Pick the match opens its
  candidates, as on the file (see above), as a list to choose from: pick one,
  or None of these, and Pick. It runs `caracole review --song "ARTIST - TITLE"
  --pick ARTIST/SONG`, which writes what answering that number in `caracole
  review` writes (`[match]`, and `[alias]` where the number would add one),
  matches that song again (with an `[alias]`, the artist's other songs too)
  and rewrites the pages; or, for None of these, `--none` with the
  candidates you saw, which go under `[reject]`. As a request does, the
  pick leaves you where you are: the picker gives way to the song's line,
  which says "Writing the answer to overrides.toml…", then how the rest goes
  (below). With Fetch it now ticked,
  as it is by default, a pick then runs `caracole fetch --song` and
  `caracole render --song`, for that song alone, at the nightly pace; None of
  these fetches nothing, and caracole goes on
  looking for the song: if the matcher finds others, the song is back in
  review with those, and its line offers them to pick from, with no Fetch now
  until one is picked. The candidates must still be the ones the page showed
  (the nightly run may have matched the song again: reload the page then),
  and a song whose own request waits or runs gets its pick once that ends:
  until then its line lists the candidates without a form. A
  review without candidates keeps its Review first button: `caracole review`
  offers it a pin or an ignore. With the keyboard, Enter opens the picker and
  takes the focus to the first candidate, the arrow keys choose, and Tab
  goes on through the candidates' UG links to Fetch it now and Pick. The picker
  is under the line's "⋯", and the line's Pick the match opens it there, the
  focus on the first candidate.
- **Look in the index.** A wanted song the offline index didn't match (and
  whose sheet you didn't pick on LaCuerda: its line's "⋯" says Tonight's run
  gets the sheet you picked on LaCuerda instead) has a
  Look in the index link under its line's "⋯": its
  page, `/review?song=ID`, runs
  `caracole search` for the song's artist and title, and offers the first five
  hits the same way, without None of these. A pick writes `[match]` alone (see
  [Review](#review)). The page runs the search when you open it, so the
  library page carries no hits of its own.
- **Remove a song.** Each song's Remove…, under its line's "⋯", removes the
  song where it is, and you stay on the library: one tap, and
  the song's line says "Removing in 5 s · Undo", the keyboard focus on Undo,
  and under it what goes, in one sentence, as
  [`caracole remove`](#caracole-remove) works it out: "Deletes caracole's 6
  files for it, its record and its wanted.txt line; leaves 1 other file;
  never touches Music/." Nothing is sent for those five seconds but that
  question, which changes nothing, and Undo stops it there: the line says
  "Not removed", and Remove… is back. Then the page queues `caracole remove
  --yes "ARTIST - TITLE"`, and the line says how it goes: "Removing…",
  "Queued…", "Removing from caracole…", then "Removed", the song's line keeping
  only its name, its size and its request line where it was, so that nothing
  on the screen moves, until you load the page again. From
  then on the song counts nowhere: the numbers at the top, the buttons'
  counts and the count over the list leave it out. A page older than a
  change to the library (the song merged into another since, say) removes
  nothing, and the line says to reload the library. Without JavaScript,
  Remove… opens a page that says what goes and what stays; Remove it queues
  the removal and goes back to the library as you left it (its search,
  filters and sort), the song's line in view, and Keep it goes back there
  too.
- **How it goes, on the page.** A request leaves you where you are. The
  song's line, on a line of its own under it, or for a song new to the
  library a line of its own under the search box ("Just requested"), says
  how its request goes: "Queued…"
  (or "Queued behind 2 requests…"), then what runs: for a request without
  Fetch it now, "Adding to the library…"; for one looked up now, its stage
  ("Finding the song…", "Looking it up…", "Fetching from Ultimate Guitar…",
  or "Fetching from LaCuerda…" while the sheet comes from LaCuerda, the one
  you picked there or LaCuerda's when Ultimate Guitar has none, "Rendering the
  sheet…", "Fetching the lyrics from LRCLIB…", "Fetching from LaCuerda…",
  "Fetching from gtptabs.com…", "Writing the library page…"), or "Waiting for
  another caracole…" while a nightly run holds the lock until its next pause;
  then how it ended (a lookup that stopped says why, in its stage's words):
  - **Ready · Open sheet**, and the song's line opens its sheet, its files under its "⋯";
  - **Not found · see the to-do page**, when Ultimate Guitar had no sheet:
    the fetch looked the song up during the request and found none, or the
    index has no such song (and its artist's UG page isn't known);
  - **Needs review · Pick the match**, when caracole isn't sure which UG
    song it is and has candidates for it: the link opens the line's picker
    (from the corner's list of requests, the picker's own page); without
    candidates, **Needs review · see the to-do page**;
  - **Not fetched yet · Details**, when a cooldown, a block, a spent budget
    or an error stopped the fetch before it looked the song up: an error is
    never a miss, and the song waits for the next run (Details says if it
    doesn't);
  - **Added: the nightly run looks for it**, for a request without Fetch it
    now; **Added: tonight's run gets the sheet you picked on LaCuerda** for
    one with a LaCuerda pick still to ask for;
  - for a read of a LaCuerda artist's page (Read their page, Read LaCuerda's
    page for a name), what LaCuerda answered, in the command's words up to its
    first ";": **Read: LaCuerda's page of Caifanes lists 88 songs, in the index
    now.**, **Not found: LaCuerda has no artist page for caifanes.**, or **Not
    read: LaCuerda failed.**, **Not read: LaCuerda is cooling down after a
    block until …**, **Not read: this hour's 60 lookup requests to LaCuerda are
    spent.**, each with **Details**;
  - or, when a command failed, its error in one sentence, with a **Details**
    link to what it printed.

  A song asked for again shows on the line it has there already, and a
  refused request's line goes at the next request. A request still on its
  way when you reload the page keeps its line. When the server stops
  answering, the lines say so after a few tries ("caracole serve can't be
  reached; trying again…"), until it answers again.

  Two requests or more also show in a corner, folded to one line on every
  width ("2 requests · 1 to go"), so that it covers no song; it opens upwards
  to a line per song, and closes. Its one Details link opens the requests
  page. A songbook's change and a removal stay out of it: the songbook, in
  the Songbooks tab, or the song's line, where you asked says how each goes. A screen reader hears each song's request line as
  it changes, to the last one, and Fetch now hands the keyboard focus to that
  line as it goes. The page asks the server how its requests go every 1.5 seconds
  while one waits or runs (`/jobs.json`), less often in a background tab.
- **Requests**, the page at `/jobs`, has one line per request, the same as
  its song's, with the commands it ran and what each printed folded away
  under it (they run at `-v`, so that is the whole story), and a lookup's
  stages with their states and why one was skipped. A song's Details
  link opens that request's output. It refreshes itself every 10 seconds while
  one waits or runs; Stop refreshing keeps it still. A request that ended in a
  review (`caracole add` found only candidates) shows the song's picker under
  its line, so you pick at once; with Fetch it now ticked, its lookup has no
  UG song to fetch until then: its line says Needs review · Pick the match,
  not a failure, and in its output the lookup's sheet stage Waits for a pick.
  While
  the page refreshes itself, which would undo a choice half made, it shows a
  Pick the match link to the picker's own page, `/review?song=ID`, instead of
  the picker. One whose song the index didn't match links to what `caracole
  search` finds for it (Look in the index, above). `/api/jobs` and
  `/api/jobs/N` give each request as JSON: its steps (a lookup's stages),
  each with its state, its song and the library files its sheet can be read
  in. These JSON addresses (`/api/…`) answer caracole's own pages, the address
  bar and programs such as curl; a browser fetching one for another site's
  page gets 403.
- **Without JavaScript**, the forms still work: a request sends you to its
  line on `/jobs`, its output open; a pick, to its line; a lookup, to the
  lookup page, which follows it.
- **Songbooks**, the page's second tab (see [The Songbooks tab](#the-songbooks-tab)
  for what it shows). Each change runs its `caracole songbook` command (see
  [Songbooks](#songbooks)) and leaves you where you are:
  - a song's **grip** (⠿) drags it to its place; on the keyboard, ↑ and ↓ on
    the grip move it, and the move is sent a moment after the last key, so
    ↑ ↑ ↑ is one `caracole songbook move`;
  - its **chip** ("A Minor, capo 0") opens its key, mode and capo there:
    **Play it here** runs `caracole songbook set NAME SONG --key K --mode M
    --capo N`, the capo always sent with the key and the mode, so a sheet that
    takes the song's place later still sounds in that key; **Its own version**
    runs `--clear`;
  - **×** takes it out; **Get it**, on a song with no sheet yet, looks it up
    now (one `caracole get`), then makes the songbook again with its sheet;
  - **Get the 2 missing songs now** looks up each song of yours there without
    a sheet, one `caracole get` after the other in the songbook's order, then
    runs `caracole songbook render NAME`: its line says "Queued behind 2
    requests…" while they run, then "Making the songbook…" and "Made · Open
    songbook". A song "not in the library", or one overrides.toml ignores,
    isn't looked up. With less room in the queue than songs, it gets the first
    ones, and the button offers the rest once they are done;
  - **Add a song** searches your songs and the offline indexes as you type
    (as the library's bar does: no site is asked), each result with **Add**
    (**In it** for a song the songbook has): a song of yours is put at the
    songbook's end at once (`caracole songbook add`); one you don't have goes
    into wanted.txt, is looked up now as Get it does (`caracole get`), then
    added. Nothing is queued unless both fit in the queue (a lookup that joins
    one already queued needs no room of its own);
  - **Rename or delete** renames the songbook or, once you tick the box,
    deletes it and the files caracole made of it.

  The songbook's status line, under its name, says how its change goes
  ("Queued…", "Moving the song…", then "Moved"; "Changed", "Renamed", "Taken
  out", "Deleted"; once done, Made and Added link the songbook's phone page,
  Open songbook, as their lines on `/jobs` do), and a lookup's line goes under
  its song in the set list (and on the song's own line in the library); the
  lookups stay out of the list of requests in the corner. While a rename or a
  deletion runs, the songbook's controls wait. Once a change is over the set
  list is drawn again as songbooks.toml has it (and so it is once any song's
  lookup or removal is over, wherever you asked for it: a song Fetch now got
  shows there with its sheet), each line where it was: a song
  taken out says "Taken out", and a deleted songbook "Deleted", where it was
  until your next click or key, so that nothing on the screen moves seconds
  after your tap. Select's Make songbook (or Add to a songbook there is) runs
  `caracole songbook make NAME "ARTIST - TITLE"...` (or `add`) with the songs
  in the order you ticked them, ends Select once the server has it, and opens
  the Songbooks tab on the songbook, its songs there at once ("Making the
  songbook…", then "Made · Open songbook"). A change that can't be made, such
  as a name another songbook has, a song no longer in the library or a
  songbook deleted since the page was made, is refused at once, and nothing
  runs: the songbook's status line, or the Select bar, says why, and the bar
  keeps your ticks.

Every request runs the `caracole` command line, one command at a time, so the
server is never more aggressive than you at a terminal: each command takes
caracole's lock, keeps the pause after the last request any caracole sent, and
keeps the budgets and cooldowns. A lookup keeps the interactive pace (about a
second between two requests to a site, six for the song, sixty an hour), and
a nightly run holding the lock lets it go first at its next pause. The
queue holds 20 requests and one per song: asking again for a song gives its
request, and Fetch it now on a song whose request only adds it fetches it too.
A request is in wanted.txt as soon as it's made, so a full queue or a restart
loses no song. A songbook change waits in the queue like a request; the same
change sent twice is queued once. The server writes no songbook itself: the
command does, under caracole's lock. The page links each
song's files, which the server sends from the library: PDFs, text, info.json,
and Guitar Pro files as downloads, never through a symbolic link, never a
hidden file, and never the database, the token or the cache. A songbook's page,
`_songbooks/<name>/songbook.html`, is sent only while it is the very page
caracole wrote there, as recorded when it wrote it (anyone with a synced device
could put a page of their own in the library), and in a sandbox: its scripts
run, but it can reach neither the server nor your sign-in, and keeps no
storage, so the song it shows is the one in its address (`#song-3`), where the
viewer keeps the song's transposition, mode, capo, text size and scroll speed
too (`#song-3=&t=2&fs=20&speed=8`). Edited
on a device, or replaced by a link, it gets a page saying so until the next
`caracole render` (or `caracole songbook render`) writes it again.

Of the HTML pages in the library, the server sends only the sheet viewers
(`sheet.html`, `sheet (auto).html`; see [The sheet viewer](#the-sheet-viewer)),
and each only while it is still the page caracole last wrote for that song:
caracole records each viewer's SHA-256 and length when it writes it. Any other
page answers 404 Not found, and so does a viewer edited on a synced device, a
symbolic link in a viewer's place, and a viewer in a folder that is no song's
in the database: the page says the viewer isn't the one caracole wrote, and
that the PDF is beside it. The next `caracole render` writes an edited viewer
again. The server sends a viewer in a sandbox (its Content-Security-Policy
header): the page runs its own script and style and nothing else, in an origin
of its own, with no cookie and no way to ask the server for anything. The
header allows the script and style the page itself was written with, so a
viewer an older caracole wrote keeps working after an upgrade until the next
render writes it again. It works as it does from the folder, but keeps only
the transposition, the mode, the capo, the text size and the scroll speed, in
its address: a reload or Back keeps them, and opening it again from the library starts
afresh. Its links to
the PDF and back to the library work with an access token too: the sign-in
cookie goes with a link followed from another page, but not with a form
another site posts or anything it loads from the server.

Who can reach it:

- `--address` is 127.0.0.1 by default: this machine alone. A LAN or tailnet
  address, or 0.0.0.0 for every address, opens it to those networks. `--port`
  is 8737 by default.
- It answers to any of its IP addresses (`http://192.168.1.20:8737/`), and
  only to the names it knows: localhost, the machine's name and its `.local`
  name, and each `--allow-host NAME`, such as its full tailnet name. A
  browser that names it otherwise gets 421; this keeps other sites from
  reaching it under a name of their own (DNS rebinding), which an address
  can't be.
- Every form must come from the server's own page: it carries a token the
  server makes when it starts, and a request from another site is refused
  (403). A form posted from a page older than the server's last start is
  refused too; reload the page. `/jobs.json`, which the page's script reads,
  is refused the same way, and needs the same token in an
  `X-Caracole-Form-Token` header: a song's line then says the server has restarted.
  Only the served page may ask the server anything from its script (its
  Content-Security-Policy has `connect-src 'self'`); `index.html` on disk asks
  nothing of anyone.
- `--token-file FILE` asks each browser once for the access token in FILE (16
  characters or more, such as `openssl rand -base64 24`), then remembers it in
  a cookie. Without the option, a `web_token` credential from systemd
  (`$CREDENTIALS_DIRECTORY/web_token`) does the same. Listening beyond this
  machine without a token, it warns.

It runs until Ctrl-C. On the NUC, `services.caracole.web` runs it as a unit
([deploy.md](deploy.md), section 8).

## Songbooks

A songbook is a name and some songs of your library, in an order: a set list,
the songs for a trip, a book to print. caracole makes each one into three files
in `Library/_songbooks/<name>/`:

- **`songbook.pdf`**: a title page (the name, how many songs), the contents,
  then every song's sheet in order, in caracole's look and each where the
  songbook plays it: in its setting there (`caracole songbook set`, below),
  else in the song's own version (its `[version]`, else its `[transpose]`, else
  as written), every chord written as its viewer shows it there (Bb, not
  chordpro's A#) with the viewer's shape as its diagram, all from one chordpro run, with the Chinese font when a song
  needs it. A song without a sheet keeps its place: the contents name it
  ("Hysteria · Muse · missing: no sheet yet"), and its page says so. Its
  document title, the name a PDF viewer or a phone shows, is the songbook's.
- **`songbook.html`**: one page for the phone, which opens from the synced
  folder and loads nothing. It opens on the contents, each song with its
  artist, key and capo on a line under its title ("Oasis · Em · capo 2", "Soda
  Stereo · G dorian": the key of the shapes the song opens in, and its capo,
  where the songbook plays it); tap
  a song to open it in the sheet viewer, with everything the viewer does
  (chord shapes, transposition, chords to play instead, modes, scrolling by
  itself), each song opening where the songbook plays it and keeping its own settings, its scroll
  speed, text size and chosen shapes among them. Previous and Next name the
  songs they go to ("‹ Hotel California", "Next: little wolf ›", a title too long for the phone
  cut short with "…"), above each song and again at its end, where on a phone
  Next has a row of its own, with room for the title. They, a swipe across the
  sheet or the arrow keys go from song to song, skipping the missing ones, and
  Contents goes back. Opened again, the page takes you back
  to the song you had open, where you were in it, and its address names it
  (`#song-3`); the contents mark it as
  "last opened". Without JavaScript, or printed, it is every song one after
  the other. Served by `caracole serve`, it runs in a sandbox without the
  browser's storage: each song keeps its address (`#song-3`), and the
  viewer keeps the song's transposition, mode, capo, text size and scroll
  speed there (`#song-3=&t=2&fs=20&speed=8`), so a reload or Back keeps them, but not your place
  or its other settings; the next song opens where the songbook plays it.
- **`songbook.cho`**: every song's ChordPro, in its key, split by
  `{new_song}`, to import into a songbook app such as SongbookPro or OnSong.
  Each song is where the songbook plays it, every chord already written there
  as the viewer names it, with its `{key}` and `{capo}` and no chord
  definitions an app may not read; songs without a sheet aren't in it.

The songbooks are in `songbooks.toml`, in the library, so the file syncs and
you can edit it by hand. Each table is a songbook, its header the name and
`songs` its songs in order, written as `"Artist - Title"` as overrides.toml
writes them:

```toml
["Campfire"]
songs = [
  "Soda Stereo - De Música Ligera",
  "宋冬野 - 斑马，斑马",
  "Radiohead - Creep",
]
```

caracole keeps your comments and layout when it changes the file. A song of
the file is its song of the library by its artist and title: accents, case,
Traditional or Simplified characters and a version suffix ("- Remastered 2007")
don't count, but nothing else does, as no search is made for it. A song the
library hasn't got (removed since, or written with a typo) is listed missing,
`not in the library`, and never taken for another with a title like it
("Karma Police Live" for "Karma Police").
A name can't be empty, start with a dot, hold a line break or be longer than
80 characters, and two songbooks can't have names that would share a folder
(`Camp/fire` and `Camp-fire`; `Campfire` and `campfire`). A songbooks.toml that
can't be read (not TOML, or a symbolic link, which caracole never reads
through) makes no songbook: the error names the file and the line, every
songbook's files stay as they are, and everything else goes on.

The library page shows them in its [Songbooks tab](#the-songbooks-tab), where
`caracole serve` changes them too: Select makes one of the songs you tick, and a
song's chip sets where it plays.

### caracole songbook

- **`caracole songbook make NAME "ARTIST - TITLE"...`** makes a songbook of
  these songs, in this order, and its files. A song is found by its artist and
  title written any way, or by a search of your library that one song answers
  well ("ban ma ban ma" for 宋冬野 - 斑马，斑马, or a typo), and it says which
  song it took: `Took 宋冬野 - 斑马，斑马 for "ban ma ban ma"`. An artist's
  name alone names no song, even when you have only one of theirs: "Oasis"
  is refused with `did you mean "Oasis - Wonderwall"?`. The songbook keeps
  each song as the library names it, and a song named twice once, where it is
  first (`Muse - Hysteria is in it already`). A song the library hasn't got is refused,
  with what you may have meant, and nothing is written:
  `No song "Radiohed - Karma" in the library: did you mean "Radiohead - Karma Police"?`
  A name another songbook has is refused too.
- **`caracole songbook list`** shows every songbook, how many songs it has and
  how many have no sheet, and its files.
- **`caracole songbook show NAME`** lists its songs in order, the missing ones
  marked (`(missing: no sheet yet)`, `(missing: not in the library)`), and
  where its files are. A song with a setting in the songbook, or a version of
  its own, says where the songbook plays it, as its set list does:
  `3. Soda Stereo - De Música Ligera (G Dorian, capo 0)`, or
  `(key unknown, as written)` for a key or a mode its sheet can't take.
- **`caracole songbook add NAME "ARTIST - TITLE"...`** adds songs at the end;
  one it has already stays where it is.
- **`caracole songbook remove NAME "ARTIST - TITLE"...`** takes songs out. A
  song removed from the library goes by the name the songbook gives it.
- **`caracole songbook move NAME "ARTIST - TITLE" POSITION`** moves a song,
  1 being the first; past the end is last.
- **`caracole songbook set NAME "ARTIST - TITLE" [--key K] [--mode M] [--capo N]`**
  gives a song its own setting in the songbook: the key it is played in
  (`G`, `F#`, `Bb`), its mode (`ionian`, `dorian`, ... `locrian`) and its capo
  (0 to 11). The parts you give change; the others stay. A key or a mode
  given with no capo keeps the capo the song plays at now, and the setting
  names it. It says where the songbook plays the song now:
  `In the songbook: G Dorian, capo 0`. `--clear` takes the
  whole setting off, and the song is in its own version again. In songbooks.toml a
  song with a setting is a table in place of the string, and one without stays
  a string: `songs = ["Oasis - Wonderwall", { song = "Soda Stereo - De Música
  Ligera", key = "G", mode = "dorian", capo = 0 }]`. A key, mode or capo that
  is none of those is an error naming the songbook and the song, and stops the
  songbooks. The songbook's files play the song there: the key is the key of
  the shapes you play, as an export's name gives it (`G Dorian, capo 0`: G
  dorian shapes, no capo; with `--capo 2` they sound in A dorian), and what the
  setting leaves out is the song's own version's (`--capo 2` alone keeps its
  sound and plays it from other shapes). The key is a key, not a move:
  replacing the song's sheet with one in another key keeps it, and with the
  setting's capo, the key it sounds in too. A setting with no capo (a song
  that had no sheet yet when you set it, or one written by hand) takes the
  capo of the song's own version, else its sheet's: a sheet in its place with
  another capo then sounds in another key, so give `--capo` too. A song whose
  sheet has no key (no chord caracole can read, none to estimate one from)
  can't take a key or a mode, so it stays as written.
- **`caracole songbook rename NAME NEW`** renames it; its files move to the
  folder of the new name.
- **`caracole songbook delete NAME`** deletes it, and the files caracole made
  of it. A file of yours in its folder stays, and so does the folder.
- **`caracole songbook render [NAME] [--force]`** makes the files of one
  songbook, or of all, that need it, and prints
  `1 rendered, 2 up to date, 0 failed`. It exits 1 when a file couldn't be
  made, and the log says why, as `songbook Campfire: no songbook.pdf: …`. A
  file that can't be made or written (chordpro failed, a folder in its place,
  a full disk) fails its songbook alone: its other files and the other
  songbooks are still made.

A NAME is found in any case. `remove` and `move` take the songbook's own song
of that artist and title first, and only when it has none, the song a search of
your library finds ("oasis wonderwal"), as `make` does. Each change writes
songbooks.toml, makes the songbook's files and rewrites `_todo.md` and
`index.html`, holding caracole's lock, which a nightly run lets it have at its
next pause, as it does a lookup (see [One caracole at a time](#one-step-at-a-time));
`list` and `show` only read, and never wait. A change whose files couldn't all be made exits 1, as `render` does,
after saying `Some of its files couldn't be made`: the change to songbooks.toml
stays made, and on `caracole serve` its request shows as failed. A
songbooks.toml that can't be read exits 2.

`index.html` lists the songbooks and makes the commands to change them, and
`caracole serve` runs them from the page (see
[Library/index.html](#libraryindexhtml) and [caracole serve](#caracole-serve)).

`caracole render` and the nightly run make the songbooks' files after the
sheets, and a file only when what it is made from changed: its songs, their
order, their sheets, their transpositions, caracole's PDF style or the font,
for `songbook.pdf` the text each song's PDF prints too (the key it names, as
when an auto sheet's key is heard again, or a newer caracole's way of writing
it), and for `songbook.html` the sheet viewer too, so an upgrade that changes the
viewer makes every songbook's page again, as it does every `sheet.html`; or
when it is no longer as caracole wrote it (deleted, edited, a link in its
place). A songbook gone from songbooks.toml (deleted or renamed by hand) loses
the files caracole made of it at the next render, each only while it is still
as caracole wrote it, and never through a symbolic link. Like the sheets' PDFs, a songbook with a Chinese song
gets its PDF once a CJK font is set, by what the PDF prints: Chinese only in a tab's notes before its first
section needs none. Its page and its ChordPro file need none. A song whose PDF text can't be made (a bug in
caracole) fails the songbooks it is in, as a chordpro failure does: their PDF stays as it was, and their
other files and the other songbooks are still made.

## overrides.toml: your decisions

`overrides.toml` sits in the library folder (or where `overrides_file` says),
and can live in git. `caracole review` writes `[match]`, `[alias]`, `[pin]`,
`[ignore]` and `[reject]` for you, `caracole youtube --song … --url` or
`--none` writes `[youtube]`, `caracole get --lacuerda` and `caracole add
--lacuerda` (Get it and Add for tonight's run on a LaCuerda song) write
`[lacuerda]`, and `caracole render --version … --mine` (Make this my version)
writes `[version]`; you write the rest by hand. These are all the tables:

```toml
[alias]        # source artist -> UG artist slug(s): fixes every song by that artist
"Bob Marley & The Wailers" = "bob-marley"

[match]        # song -> UG song, as "artist-slug/song-slug"; still picks up new tabs
"Soda - Persiana Americana" = "soda-stereo/persiana-americana"

[artist_url]   # artists UG lists only by bare ids -> their UG artist page
"宋冬野" = "https://www.ultimate-guitar.com/artist/634073"

[pin]          # always use exactly these tab pages for a song
"Soda Stereo - De Música Ligera" = ["https://tabs.ultimate-guitar.com/tab/85053"]

[transpose]    # semitones, -11 to 11, applied when PDFs are rendered
"Soda Stereo - De Música Ligera" = -2

[version]      # where you play a song, as its viewer's address says it: its PDF, viewer and songbooks follow
"Soda Stereo - De Música Ligera" = "t=2&mode=dorian&capo=0&at=3.1"

[ignore]       # songs caracole leaves alone
songs = ["Some Artist - Some Interlude"]

[block]        # tabs never to use
tab_ids = [1601668]

[reject]       # UG songs that are not the song: never offered for it again
"Maná - Rayando el Sol" = ["ana-gabriel/rayando-el-sol"]

[youtube]      # the video a song's audio comes from, or "none" for no audio from YouTube
"Radiohead - Creep" = "https://www.youtube.com/watch?v=XFkzRNyygfk"
"Some Artist - Some Interlude" = "none"

[lacuerda]     # the LaCuerda song (or version) a song's sheet comes from
"Estopa - Como Camarón" = "https://acordes.lacuerda.net/estopa/como_camaron"
```

- **Song keys** are written `"Artist - Title"`. They match the way songs
  match, so these don't matter: case, accents, a leading "The", Spotify's
  suffixes (" - Remastered 2011", " - 2019 Mix", " - En Vivo", "(Acústico)",
  " - Versión Acústica"), Traditional or Simplified Chinese, and number words
  or digits ("Té Para Tres" is "Té para 3"). In the artist, a leading Los,
  Las, El or La doesn't either, nor "y" for "&" ("Fito y Fitipaldis").
- **`[alias]`** takes one UG artist slug or a list of them. The slug is the
  artist part of a tab's address, as in `/tab/bob-marley/...`.
- **`[match]`** points one song at one UG song. Unlike a pin, it still picks
  up tabs added to that song later. Correct a `[match]` or a `[pin]`, and
  what the old one brought goes: the next fetch takes the song's sheet, tab
  and Guitar Pro picks from the new one. When the new one has no sheet, the
  old sheet goes all the same, and the next render takes its `sheet.cho` and
  `sheet.pdf` along.
- **`[artist_url]`** is keyed by the artist's name as your songs write it, or
  as UG writes it: an entry for "Song Dongye (宋冬野)" or "Song Dongye" serves
  songs by 宋冬野 too (see [names in other scripts](#names-in-other-scripts)).
  The value is the artist's page on UG, whose address ends in the artist's
  number: UG writes some with the name before it
  (`https://www.ultimate-guitar.com/artist/soda_stereo_2946`) and some with
  the number alone (宋冬野's is `https://www.ultimate-guitar.com/artist/634073`).
  Paste it as your browser shows it, even after you clicked a filter or
  another page (`?filter=chords`, `?page=2`, `?sort=date`): caracole drops the
  query. It may come without `https://` or `www.`, as an address bar shortens
  it, with capitals, or from one of UG's language editions
  (`es.ultimate-guitar.com`, the Spanish one): caracole asks for the page at
  UG's own address. An address without the number (`/artist/joaquin_sabina`)
  is an error: UG answers it with "page not found". Any tab page of the artist
  works too, bare or slugged (`https://tabs.ultimate-guitar.com/tab/4180894`):
  the next fetch reads it once, a request like any other within the night's
  budget, and remembers the artist page it links to, for every song by the
  artist. A tab page that leads to no artist page is listed on the to-do page,
  and its songs wait for another address.
- **`[pin]`** takes tab page addresses: paste them as your browser shows them,
  a query or a fragment included, without `https://` too, and from a language
  edition (`https://es.ultimate-guitar.com/tab/4180894` is
  `https://tabs.ultimate-guitar.com/tab/4180894`). Pinned tabs replace the
  candidates of their kind (sheet, Guitar Pro, tab), in the order given. A pin
  whose page is gone, is Official, or is closed to bots by robots.txt (UG's
  `/tab/track/` pages), or redirects to such a page, pins nothing, and the
  song's other versions compete for that kind.
- **`[transpose]`** shifts the chords and the key in the PDF. `sheet.txt`
  stays as the source wrote it.
- **`[version]`** is the song's own version: where you play it, written as the
  sheet viewer writes it in its address after `#` (`t=2` semitones,
  `mode=dorian`, `capo=0`, `alt=` for chords played instead, `at=` for chosen
  shapes; a `#` before it is dropped), as Make this my version saves it. The
  song's `sheet.pdf` is made in it, its viewer starts in it, and its songbooks
  take its transposition; it wins over the song's `[transpose]`, which stays in
  the file, and a version without a `t` is at that `[transpose]`. Its shapes and
  swaps are the chords' of the sheet it was made on, by their places: an auto
  sheet rendered beside a human one takes the rest of it alone, and a new sheet
  plays the chords it still offers. Take the entry out to go back to
  `[transpose]`, or the sheet as written. A value that is not text, holds a
  control character or is over 2000 characters is an error naming the entry.
- **`[ignore]`** takes only `songs = [...]`. It stops all work on a song: no
  matching, fetching, rendering or to-do items. Take it out of the list, and
  the song comes back.
- **`[block]`** takes only `tab_ids = [...]`, and keeps those tabs out of
  every ranking. A tab you block, or take out of `[block]`, reaches the songs
  fetched already at the next fetch. A kept sheet you block that nothing
  replaces goes, and the next render takes its `sheet.cho` and `sheet.pdf`
  along.
- **`[reject]`** names, for a song, the UG songs that are not it, as
  `"artist-slug/song-slug"` like `[match]`: one string, or a list. The
  matcher passes over them at every step, and so does the fetch on the
  artist's UG page, so they are never offered again, while other candidates
  still can be; a `[match]` for the song still wins. A match caracole made on
  the artist's UG page is undone at the next match when `[reject]` names it.
  A song whose match `[reject]` undoes loses the sheet and the tab that match
  kept at the next fetch, unless its artist's page finds the song again, and
  their `sheet.cho` and `sheet.pdf` at the next render; it stays found only
  if a LaCuerda or auto sheet is left. Guitar Pro files you filed, and files
  caracole doesn't track, stay. `n` in `caracole review` writes this table.
- **`[youtube]`** names the YouTube video a song's audio comes from, in place of
  the one caracole's search picks, also for a song its search found nothing
  for: paste the address as your browser shows it (`watch?v=`, `youtu.be/`,
  `music.youtube.com`, `/shorts/`, a playlist or a time in it included; caracole
  takes the video alone). A new video for a song whose audio came from another
  replaces it at the next run, and its auto sheet is made again. `"none"` keeps
  the song's audio off YouTube for good: caracole lets go of any it took, and the
  song goes back to buying. An auto sheet made already stays until a human
  sheet, or one from other audio, takes its place.
- **`[lacuerda]`** names the LaCuerda song whose sheet is the song's: its page
  (`https://acordes.lacuerda.net/estopa/como_camaron`: its best Letra y Acordes
  version) or one version's (`…/como_camaron-2.shtml`), as your browser shows
  it (without `https://`, on `lacuerda.net`, with a query). The nightly
  LaCuerda pass asks for it whatever the song's language or its sheet, until it
  is the sheet kept, and keeps it whatever its coverage of the lyrics, in place
  of Ultimate Guitar's, LaCuerda's other versions and the auto sheet;
  Ultimate Guitar's fetch never replaces it. A `[pin]` of an Ultimate Guitar
  sheet wins over it. An entry you write by hand is asked for at the next pass
  unless LaCuerda answered for the song in the last 30 days;
  `caracole get --lacuerda` asks at once.

Each table may appear only once in the file: add lines under a table it has
already, as the to-do page's lines say. An unknown table, a key other than
`songs` in `[ignore]` or `tab_ids` in `[block]`, or a malformed entry is an
error that names the table and the entry:

    error: overrides: /home/you/Tabs/overrides.toml: [reject] 'Creep': expected "Artist - Title", got 'Creep'

A table declared twice ends with `; merge the two [match] sections into one`.
The file must be a regular file: a symbolic link or a folder there is refused
unread (`a symbolic link, which caracole doesn't follow; put the file itself
there`), while a missing file means no overrides. A file caracole may not read,
or one saved in an encoding other than UTF-8, is an error too:
`can't read it: Permission denied`, or
`line 3 is not valid UTF-8 (save the file as UTF-8)`, naming the first such
line.

While the file can't be read, the commands that need it exit with status 2,
and the nightly run stops before its first step (ntfy tells you). The run,
`caracole todo` and `caracole scan` still rewrite `_todo.md`, which then leads
with the error, and leave `index.html` as it was. `caracole add`,
`caracole search --add` and `caracole sync` still add and sync your songs, with
a warning.

## Fonts for Chinese sheets

ChordPro's built-in PDF fonts have no Chinese glyphs, so a sheet with Chinese
lyrics needs a font file. The Nix package sets one: its wrapper points
`$CARACOLE_CJK_FONT` at `FusionKaiJ-Regular.ttf` from nixpkgs' `lxgw-fusionkai`,
a Kai (brush-style) face. To use another font, set `cjk_font`, which wins over
the variable.

Two kinds of font don't work with ChordPro 6.050.7, so caracole refuses them
with an error instead of writing a PDF with blank text:

- font collections (`.ttc`), which is all nixpkgs ships of Noto CJK and
  Source Han Sans: ChordPro can't open them;
- TrueType fonts with odd-length glyph records, which most CJK `.ttf` files
  have (LXGW Neo XiHei and WenKai among them): their glyphs come out blank.

A CFF-based `.otf` works too; it is embedded whole, so its PDFs are larger.
Until a usable font is set, a Chinese sheet still gets its `.cho` file and its
viewer (`sheet.html`, which the browser draws with its own fonts), and the
to-do page's PDFs section names the sheets waiting for a font, each with
the first letter it needs the font for, such as `宋冬野 - 斑马斑马 (斑 U+6591)`.
Section 7 of [deploy.md](deploy.md#7-chinese-sheets-in-the-pdfs) has the
details.

The font is used only for sheets that need it, by what the PDF prints: Chinese
only in the tab's notes before its first section, which stay out of the PDF,
needs none. Some transcribers type a
Cyrillic or Greek letter that looks Latin, such as the Cyrillic х in a repeat
mark "(х2)": when those are a sheet's only such letters, they are written as
the Latin ones, so the sheet keeps ChordPro's built-in fonts and needs no font
file.

## The library folder

```
Library/                    library_dir: ~/Tabs by default, /var/lib/caracole/library on the NUC
  _todo.md                  what needs you
  index.html                browse and search the library
  wanted.txt                your songs
  overrides.toml            your decisions
  songbooks.toml            your songbooks (see Songbooks)
  _songbooks/
    Campfire/
      songbook.pdf          every sheet of the songbook, after a title page and the contents
      songbook.html         the songbook for the phone, in the sheet viewer
      songbook.cho          every sheet in ChordPro, for a songbook app
  _inbox/                   Guitar Pro and MuseScore downloads waiting to be filed
  宋冬野/
    斑马斑马/
      sheet.txt             the chosen chord sheet, as plain text
      sheet.json            the same version as the source gave it
      version-39144.txt     another Ultimate Guitar version caracole scored for the sheet,
      version-39144.json    kept beside it (by its tab id): the runners-up
      sheet.cho  sheet.pdf  ChordPro, and a PDF in your key
      sheet.html            the sheet viewer, for the phone
      version-39144.txt     another version of the sheet, kept beside it: its text,
      version-39144.json    the version as UG gave it, and its viewer (no PDF of
      version-39144.html    its own)
      lyrics.txt            the lyrics, from LRCLIB
      lyrics.lrc            the timed lyrics, when LRCLIB has them
      guitar-1.gp5          Guitar Pro or Power Tab files: filed by rank, or from gtptabs.com
      score-1.mscz          scores you downloaded (MuseScore, MusicXML, PDF, MIDI), filed
      tab.txt  tab.json     the best text tab
      sheet (auto).txt      made from audio you bought, or caracole took from YouTube,
      sheet (auto).cho      when no human sheet exists; it stays, with its ChordPro,
      sheet (auto).pdf      PDF and viewer, beside a partial human sheet, until a
      sheet (auto).html     complete one replaces it
      info.json             where everything came from, and the song's key
Music/                      music_dir: the tracks you bought (caracole only reads it)
```

The audio caracole takes from YouTube is not in the library: it stays in the
cache folder, `cache_dir/youtube/<song id>-<video id>.m4a`, private and out of
Syncthing's way, a few MB a song. caracole deletes a song's file there once a
purchase or a human sheet takes its place, or `"none"` under `[youtube]` turns
YouTube down for it, and any file there no song names; deleting the folder
yourself costs only downloads, and only for songs that have no auto sheet yet:
the next run, or `caracole youtube`, downloads their videos again.

Folder names keep their accents and scripts, but never contain a path
separator or a character file systems reserve: `AC/DC` becomes `AC-DC`.

**The `.cho` files** are the sheet in ChordPro, a plain-text format that puts
each chord in brackets before the syllable it falls on (`[Am]Yesterday`).
caracole makes `sheet.cho` from `sheet.txt`, as the sheet is written, and
renders the PDF from it in your key (`[version]`, else `[transpose]`). You don't need to open it: it is there for songbook
apps that read ChordPro, such as SongbookPro (Android, iOS, Windows) or OnSong
(iOS), which scroll, transpose and draw chord diagrams on a phone or tablet,
and any text editor opens it. Don't edit it in place, as the next render
writes it again; copy it under another name for a version of your own.

Others can write to the library: Syncthing, and every device it syncs with. A
symbolic link planted there could point at caracole's private files, so caracole
never reads or writes a file there through a link. A link in the place of
wanted.txt, overrides.toml, `_inbox` or a download in it is refused, and the
command or the to-do page says so; one in the place of `sheet.json`,
`sheet (auto).txt`, a `.cho` file or a viewer fails that song's render, and
`info.json` is not read through one. A file caracole
replaces there arrives through a temporary file beside it, named
`.<name>.<8 hex digits>.tmp`, and reaches the disk before it is renamed into
place, so a power cut during the nightly run leaves the old file or the new
one, never an empty one.

**The files caracole keeps are its own.** One that is no longer as caracole wrote
it, deleted (on the laptop, say), cut short or edited, is written again, and
only it: `sheet.txt`, `sheet.json`, `version-<tab>.txt`, `version-<tab>.json`,
`tab.txt` and `tab.json` at the next
`caracole run` or `caracole fetch` (a LaCuerda sheet at the next LaCuerda pass),
from the cache, usually with no request; the `.cho` files, the PDFs and the
viewers at the next render. So is a link in the place of one of them, except a
`.cho` or a viewer. A
file still as caracole wrote it is never written again, so Syncthing has
nothing to sync. Keep your own edits and annotations in a copy under another
name: caracole leaves alone the files it doesn't track. A lost
`sheet (auto).txt`, `lyrics.txt` or `lyrics.lrc` isn't written again, nor is
a Guitar Pro file: a song that has had one, filed from `_inbox/` or
downloaded from gtptabs.com, gets no other from gtptabs.com, even after you
delete it. Nor is a score, which caracole never downloads. Put one you lost
back in the song's folder under its name.

Deleting a song's folder yourself doesn't remove the song: caracole writes its
files again. [`caracole remove`](#caracole-remove) does, and deletes only the
files caracole wrote there (an edited one included, since it is caracole's), by
name in the song's folder, never through a symbolic link; it names what it
leaves.

Keep the library private. The sheets and lyrics are other people's work, and
a personal offline copy is the closest thing to the sites' personal-use terms.

### The song's key

caracole gives each song with a sheet a musical key, and says where it came
from. It takes the first of these that gives one:

1. **From the tab**: the key Ultimate Guitar gives the kept version, or a key
   the sheet states before its first chords: a ChordPro `{key: Am}`, or a note
   such as `Key: G`, `Key of Bb`, or LaCuerda's `Tono: La menor`.
2. **Estimated from the chords** of the human sheet: which key's notes its
   chords fit best, and whether it starts and ends on that key's home chord.
   Chords that fit no key give no estimate.
3. **From the audio**, for a sheet auto-chords wrote: the key of the chords
   the model heard, each weighed by how long it sounds. Auto-chords records
   it with the sheet; for a sheet made before it did, the key is estimated
   from the chords the sheet shows.

An estimate is the key of the chords as the sheet writes them, the shapes you
play: with a capo, the song sounds higher. A key from the tab is as its
transcriber gives it. Either is the sheet's key before any `[transpose]`.

`info.json` holds it in two fields, for anything that reads the library:

```json
"key": "A minor",
"key_source": "tab",
"identity_key": "soda-stereo/de-musica-ligera",
```

- `key` is the tonic, a capital letter with `#` or `b` as the source spells
  it, followed by ` minor` for a minor key: `"A minor"`, `"C"`, `"F#"`,
  `"Bb minor"`. A major key is the tonic alone. `null` when no source gives one.
- `key_source` is `"tab"`, `"chords"` or `"audio"`, as in the list above, and
  `null` with no key.
- `identity_key` is caracole's own key for the song, which info.json called
  `key` before. The first command that rewrites the pages after an upgrade
  rewrites every song's info.json once, with these fields. caracole never
  rewrites an info.json that holds the same text already, so Syncthing has
  nothing to sync for it.

## A worked example

The song is 斑马斑马 by 宋冬野 (Song Dongye), from the album 安和桥北. It
shows two hard cases: an artist Ultimate Guitar lists only by bare ids, and
lyrics without timings.

**1. Add it.**

    $ caracole add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    Added 宋冬野 - 斑马斑马 to wanted.txt; the next `caracole run` looks for it.
    Not in the offline Ultimate Guitar index under this name: `caracole search` with a few of its words looks wider.

The album and duration make the lyrics lookup exact. Written "斑马，斑马",
with a comma, it is the same song to caracole, and so is 斑馬斑馬, in
Traditional characters, as some releases write it.

**2. It isn't found on Ultimate Guitar.** UG's sitemaps list every tab of
宋冬野 by a bare id, so the local index has none of them, as `caracole add`
said, and `caracole match` says too:

    $ caracole match --dry-run
    not_found      -  -             宋冬野 - 斑马斑马 → -

`--dry-run` saves nothing; `caracole add` saved that match already, so the
to-do page it rewrote lists 宋冬野 under "Artists to find on Ultimate
Guitar", with a link to search UG and the line to paste, and puts the song on
the buy list meanwhile:

```toml
[artist_url]
"宋冬野" = "https://www.ultimate-guitar.com/artist/…"
```

**3. Tell caracole where 宋冬野 is on UG.** Search UG in your browser, and
paste what you find into overrides.toml, as your browser shows it. Any one of
these does:

- **His artist page.** UG writes it with his number alone, and no name:

  ```toml
  [artist_url]
  "宋冬野" = "https://www.ultimate-guitar.com/artist/634073"
  ```

  A click on a filter adds `?filter=chords` to the address; caracole drops it.
- **Any of his tab pages**, such as the one UG's search finds for the song:

  ```toml
  [artist_url]
  "宋冬野" = "https://tabs.ultimate-guitar.com/tab/4180894"
  ```

  The next run reads that page once, within the night's budget, for the
  artist page it links to (`/artist/634073`), and remembers it. A tab page
  that leads to no artist page stays on the to-do page, with what is wrong
  with it, until you paste another one.
- **A pin of the song's tab page**, which takes that very version:

  ```toml
  [pin]
  "宋冬野 - 斑马斑马" = ["https://tabs.ultimate-guitar.com/tab/4180894"]
  ```

  Reading it teaches caracole 宋冬野's artist page too, so his other songs
  in wanted.txt (`宋冬野 - 董小姐`, say) are found there the next night with
  nothing more to paste.

**4. The next run finds it.** With his artist page known, the run reads its
chords list, then its tabs list. UG names him "Song Dongye (宋冬野)" there,
and the song "斑马 斑马 Banma Banma Zebra Zebra", in two versions: the
original, its pinyin and a translation, run together. Each part counts as a
name of its own (see [names in other scripts](#names-in-other-scripts)), so
斑马斑马 matches both versions, and none of his other songs (与我交谈 Speak
With Me, 莉莉安 Lilian, 董小姐, 郭源潮). Both versions are scored against the
lyrics, the better one becomes `sheet.txt`, and the song is found; 宋冬野
leaves the to-do page. That takes four requests: the two lists and the two
versions (or the tab page you pasted, the lists and the other version).
`caracole fetch --song "宋冬野 - 斑马斑马"` does it at once.

**5. The lyrics come from LRCLIB, plain.** LRCLIB has the song with plain
lyrics only, and no timings, so its folder gets `lyrics.txt` and no
`lyrics.lrc`. Its lyrics are in Traditional characters (斑馬), as UG's sheet
of the song is; many sheets are in Simplified ones (斑马). Caracole compares
Chinese text as pinyin when it checks how much of the lyrics a sheet covers,
so a complete sheet counts as complete either way.

**6. No human sheet anywhere? Buy it, drop it into Music/, and run
`caracole autochords`.** The buy list links the stores. The command needs the
flake's `packages.autochords` (`nix shell .#autochords` on the laptop; on the
NUC, the `caracole-autochords` unit runs it after each nightly run, see
[deploy.md](deploy.md#6-auto-chords)). It links the new file to the song by
its tags and duration (tags in two scripts, such as "Song Dongye (宋冬野)",
work too), finds the chords and the beats, and writes
`sheet (auto).txt`. With no timed lyrics to lay the chords over, the sheet is
a chord chart by bars followed by the plain lyrics. It starts with
"auto-generated, unverified", the song counts as found, and the next render
makes `sheet (auto).pdf` with the Chinese font. A complete human sheet found
later takes its place; a partial one is rendered beside it, and the auto
sheet's PDF stays until a complete one arrives.

If the scan reports the file as unmatched, make the file's artist and title
tags match the song's line in wanted.txt.

With auto-chords, caracole doesn't wait for a purchase: the nightly run takes
the song's audio from YouTube itself (see [Audio from YouTube](#audio-from-youtube)),
picking an upload named "斑马，斑马" or "Banma Banma" by 宋冬野 or "Song
Dongye", and the to-do page lists the song as "No human sheet found yet",
queued, then downloaded, then with its chords done. The auto sheet says which
video its audio came from, on its third line. A purchase dropped into Music/
later takes the video's place.

## Running it on the NUC

[deploy.md](deploy.md) sets caracole up as a nightly NixOS service: the timer,
the hardened units, agenix secrets, Syncthing for the library and the music,
restic backups, the offline auto-chords unit, and caracole-web, which serves
the library page with its request form. There, run any command as the service
does with `sudo caracole-admin COMMAND`, for example
`sudo caracole-admin index build`.
