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
[providers.lrclib]                # lyrics
budget = 200
delay = [1, 2]
[providers.lacuerda]              # Spanish chord sheets
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

Caracole keeps one sheet and one text tab per song; only the number of Guitar
Pro picks is a setting. Scores and thresholds can't be negative, scores stop
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
goes when the PDF is done, so caracole must be able to write there.

**The database.** Before a new caracole migrates `caracole.sqlite`, it copies it
to `caracole.sqlite.vN.bak`, N being the version it had. A database a newer
caracole migrated, after a rollback say, stops every command that uses it with
status 2: `database: … is at schema version 4, but this caracole knows up to 3:
a newer caracole migrated it.` The message ends by naming that copy to restore,
when there is one. A state folder caracole can't use ends a command with status
1 and `can't open the database …` (or `can't open …/caracole.lock: …`).
`caracole add` is the exception to both: it keeps its line and warns (see
below).

**Secrets** stay out of the file. The Spotify client secret comes from
`$CREDENTIALS_DIRECTORY/spotify_client_secret` (systemd's `LoadCredential`),
else the file `client_secret_file` names, else
`$CARACOLE_SPOTIFY_CLIENT_SECRET`. The ntfy token comes from
`$CREDENTIALS_DIRECTORY/ntfy_token`, else `token_file`, else
`$CARACOLE_NTFY_TOKEN`.

**Providers** are exactly `ug`, `lrclib`, `lacuerda`, `gtptabs` and
`musescore`. Any other `[providers.…]` table is an error, like any other
unknown key. Only gtptabs.com and MuseScore can be turned off: with
`enabled = false` under `[providers.gtptabs]` or `[providers.musescore]`,
caracole sends that site nothing, the nightly run skips its step, and the to-do
page's Provider health says it is off. The other three are what caracole is
built on, so `enabled` in their tables is an unknown key.

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
  line gave it. To drop a song, put it under `[ignore]` in overrides.toml.
- The file must be a regular file. A symbolic link there is refused, not
  followed: the sync says `wanted.txt: not read: … is a symbolic link, which
  caracole doesn't follow; put the file itself there`, and the to-do page says
  that wanted.txt can't be read, under Setup problems and Sources.

Songs are handled newest first, so a song you add today is looked for
tonight. A line keeps its place when an upgrade changes how caracole keys
songs: the first command to open the database re-keys them, and two records
that turn out to be one song (斑馬斑馬 and 斑马斑马, say) become one.

### caracole add

`caracole add ARTIST TITLE [--album ALBUM] [--duration M:SS]` appends the line
for you, then syncs the file at once and rewrites `_todo.md` and
`index.html`:

    $ caracole add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    Added to /home/you/Tabs/wanted.txt, line 16:
      宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Song 宋冬野/斑马斑马: new; the next `caracole run` looks for it

A song that is already listed isn't added twice, and its line stays as it is:
edit the line to change its album or duration, and the next sync changes the
song. The file is the source of truth, so the line is written first, before
`caracole add` waits for any other caracole to finish. When the database can't be
updated, the line is kept all the same, a warning says why, and the next sync
adds the song. The first `caracole add` creates the file, with a header that
explains the format.

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
`daoko/uchiage-hanabi`), a purchase tagged that way, and a Guitar Pro download
UG named so.

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
- **review**: any other score of 75 or more, and any match on the title alone
  (usually a cover). You settle these on the to-do page or with
  `caracole review`.
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
4. The title alone, across all artists: always a review.

At steps 2 to 4, the matcher passes over the UG songs you rejected for the
song under `[reject]`, and so does the fetch on the artist's UG page, so they
are never offered again; other candidates still can be.

### caracole run

`caracole run` is what the nightly timer starts. Its steps, in order:

1. **sync**: wanted.txt, then Spotify.
2. **index**: refresh the index, and mark the songs that have new tabs.
3. **match**: match every song again, locally.
4. **lyrics**: ask LRCLIB for the songs that have no lyrics yet.
5. **fetch**: rank and keep Ultimate Guitar sheets and guitar parts.
6. **lacuerda**: look on LaCuerda for Spanish songs without a complete sheet.
7. **scan**: link purchases in Music/, and file Guitar Pro downloads.
8. **gtptabs**: download a Guitar Pro file from gtptabs.com for each song that
   has none. It comes after the scan, so a file you dropped into `_inbox/` is
   filed first, and that song gets none from gtptabs.com.
9. **musescore**: read MuseScore's song sitemaps into a local index, for the
   to-do page's links to its pages. It downloads nothing.
10. **render**: write ChordPro files and PDFs.
11. **todo**: rewrite `_todo.md` and `index.html`.

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

    1 thing on your to-do page needs you: /home/you/Tabs/_todo.md
    LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.
    Requests: Ultimate Guitar 0 of 60, LRCLIB 2 of 200, LaCuerda 0 of 30.
    Took 3 s.

(gtptabs.com and MuseScore were turned off that night; when they're on, as
they are by default, the Requests line lists them too.)

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
song waits for the next run. Caracole never works around a block: no proxies,
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
  undone (by `[reject]`, say) loses the sheet and the tab that match kept.
  Songs the index can't settle are looked up on their artist's UG page, when
  it is known, at most once in 30 days: songs not found, songs reviewed on
  their title alone (only other artists' songs of it), songs found on that
  page before, and songs whose chords the index can't offer (bare ids, or
  pages robots.txt closes). Per song it prints what it kept, as
  `Artist - Title: sheet 101 · Guitar Pro 301, 303 · tab 402 (3 requests)`,
  or `nothing kept`. `--song` fetches that one song now, even when nothing
  about it changed; the song must be in the library and matched, or not found
  or reviewed on its title alone with its artist page known. A cooldown, a
  block or a spent budget exits 0.
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
  LaCuerda". A cooldown, a block or a spent budget exits 0.
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
- **`caracole render [--force]`** writes `sheet.cho`, `sheet.pdf` and
  `sheet.html` next to every kept sheet, transposed as `[transpose]` says.
  The PDF has the artist, the key and the capo on one line under the title
  ("Soda Stereo · Key Bm · Capo 2"), the chord diagrams above the song, bold
  chords in rust over the lyrics, and section names on a light band.
  `sheet.html` is the sheet viewer, for the phone (see
  [The sheet viewer](#the-sheet-viewer)). A PDF is made again only when its
  sheet, its transposition, the font or caracole's PDF style changes, or when
  it is no longer the PDF caracole wrote: deleted, cut short, edited, or a
  link in its place. So annotate a copy, not `sheet.pdf`. `--force` makes them
  all again. After an upgrade from a caracole that didn't record what it
  wrote, or that drew its PDFs another way, the first render makes every PDF
  once more. The viewer is written again whenever it would change, at every
  render. A song that no longer keeps its human sheet (its UG match was
  undone, say) loses the `sheet.cho`, `sheet.pdf` and `sheet.html` made from
  it; one you put where caracole never rendered one stays. A sheet that never
  got a PDF (waiting for a font, or chordpro failed on it) loses its
  `sheet.cho` and `sheet.html` while they are still as caracole wrote them.
  chordpro works on a copy, in a private folder in the cache, and the new PDF
  replaces the old one in one rename, so a failed render leaves the last good
  PDF in place. It exits 1 when a sheet couldn't be rendered, and the log
  says why, as `no PDF for Artist - Title: …` (chordpro's own messages name
  the copy in the cache). A viewer that couldn't be made or written is logged
  as `no viewer for Artist - Title: …` and counts the song as failed too, but
  never costs it its PDFs. A symbolic link, a FIFO or a folder in the place of
  `sheet.json`, `sheet (auto).txt`, a `.cho` file or a viewer fails that song
  alone: caracole reads no sheet through a link. Remove the link, and the next
  render writes the `.cho` and the viewer again; the next `caracole run` writes
  `sheet.json` again before it renders. Then it makes the
  [songbooks](#songbooks)' files that need it, and says how that went on a
  line of its own, `Songbooks: 1 rendered, 2 up to date, 0 failed`, when there
  are songbooks; a songbook that couldn't be made, or a songbooks.toml that
  can't be read, exits 1 too.
- **`caracole todo`** rewrites `_todo.md` and `index.html` from the database.
- **`caracole review`** settles uncertain matches, one prompt per song (see
  [Review](#review)).
- **`caracole search [QUERY]... [--limit N] [--add N] [--key KEY]`** searches
  your library and the offline UG index; `--key` finds your songs in one key
  (see [caracole search](#caracole-search)).
- **`caracole autochords`** writes `sheet (auto).txt` from audio you bought, for
  songs with no human sheet (see [the worked example](#a-worked-example)), then
  rewrites `_todo.md` and `index.html`. It needs the flake's
  `packages.autochords`, with torch, librosa and beat_this; the default package
  says so and exits 1. A purchase it can't read fails that song alone: it
  exits 0, the to-do page lists the file, and the song is tried again once the
  file changes. It exits 1 when auto-chords can't work at all: the model files
  missing or unusable, or a sheet it can't write into the library.

**The pages.** A command that changes what `_todo.md` and `index.html` show
rewrites both when it is done: `match` (not `--dry-run`), `render`, `scan`,
`todo`, `add`, `search --add`, `sync`, `autochords` and every `songbook`
command but `list` and `show`; `review` when an
answer changed something; and `fetch`, `lyrics`, `lacuerda`, `gtptabs` and
`musescore` when they did something or were blocked, so that Provider health
shows the cooldown.
A page caracole can't write ends the command with status 1 and
`can't write …/_todo.md: Permission denied`, its own work saved first; for
`add`, `search --add` and `sync` that is only a warning.

**One caracole at a time.** The commands that ask the sites for pages or write
the library hold caracole's lock, `caracole.lock` in the state folder, while they
work, so no two budgets are ever spent side by side: `run` from start to end,
`index build` and `refresh`, `fetch`, `lyrics`, `lacuerda`, `gtptabs`,
`musescore`, `render`, `match`, `scan`, `todo`, `sync`, `add`, `search --add`,
`autochords` and the `songbook` commands that change a songbook or render one. A
second one waits for the first, and says which it is:
`Another caracole is running (pid 4242: run); waiting for it to finish.`
`caracole review` takes the lock only after your answers, never while it waits
for one, and `search`, `match --dry-run`, `index stats`, `songbook list` and
`songbook show` only read, so they never wait. A command that waited reads the sites' cooldowns once it has the
lock: if the caracole it waited for was blocked, it sends that site nothing and
exits 0. Its first request to a site also waits out the pause after the last
request any caracole sent there, so the pauses hold whichever caracole sends.

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
  [Review](#review)). When the candidates are only other artists' songs of
  the title, probably covers, the item says so, and whether caracole has looked
  on the artist's own UG page yet.
- **Partial sheets.** The best sheet covers less than 80% of the lyrics: the
  percentage, the sheet and its source page. A more complete sheet takes its
  place when one turns up; to use another UG version now, pin it under
  `[pin]`.
- **Artists to find on Ultimate Guitar.** UG lists artists with accented or
  non-Latin names only by bare ids (Joaquín Sabina, Maná, 宋冬野), so caracole
  can't see their tabs. For each such artist with a song not found, or
  reviewed on its title alone, the page links a UG search. Open the artist's
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
  sheet from it. Songs whose audio you have are left off.
- **Auto-chords couldn't read these purchases.** Each file auto-chords failed
  on, with the error. Re-download it, or convert it (to FLAC, say) and replace
  the original: a changed file is tried again on the next run.
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
- **PDFs.** The last render: how many PDFs were made or failed, a font
  problem if there is one, and the sheets that failed.
- **Sources.** Whether Spotify is off, synced, not fully set up (the client
  secret missing, say), or needs `caracole auth spotify`, and how many songs
  wanted.txt has, with the lines it couldn't read; for a wanted.txt it
  couldn't read at all, the error, as `wanted.txt: error at <time>: …`.
- **Provider health.** For Ultimate Guitar, LRCLIB, LaCuerda, gtptabs.com and
  MuseScore: OK, errors (nothing has worked since the last error), cooling down
  until when, or off (`[providers.gtptabs] enabled = false`, and the same for
  `musescore`); the last success; the last error; the requests of the last run.

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
  no alias: it is usually a cover by someone else.
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

## Browse and search

### Library/index.html

`index.html` sits next to `_todo.md`, and is rewritten with it, except while
overrides.toml can't be read: built without it, the page would lose your
transpositions and ignored songs, so it stays as it was. Open it from the
synced folder, in a browser on the laptop or the phone. It needs no server and
loads nothing from the network. It shows every song as a card, in a grid as
wide as the screen: one column on a phone, three or four on a laptop. A card
has its status, its key and where the key came from ("Key A minor (from the
tab)", "Key C major (estimated from the chords)", "(from the audio)": see
[The song's key](#the-songs-key)), its transposition, and links to its files:
the sheet viewer first (see [The sheet viewer](#the-sheet-viewer)), then the
PDF. A Guitar Pro file caracole downloaded names its site, as
`Guitar Pro 1 · gtptabs.com`, and a score its format, as `Score 1 (MuseScore)`;
a score's PDF is never the card's main link, which is the sheet's. Each
artist's cards share a coloured monogram, and the artist's name under a title
shows only that artist's songs ("Queen" leaves out ABBA's "Dancing Queen"),
until you take its chip off. "Find it elsewhere" opens a song's MuseScore
pages, each a possible match, as on the to-do page, and, for a song without a
sheet, its search and buy links.

The search box filters as you type. It ignores case and accents, so "musica"
finds "De Música Ligera", and it matches Chinese titles by pinyin: "ban ma" or
"banma" finds 斑马斑马. It finds keys too, however a sheet spells them: "a
minor", "F# major", "bbm", and "gb minor", which also finds the songs in F#
minor; or "minor" for every song in a minor key. A key written as a chord, such
as "am", also finds the names with "am" in them ("I Am the Walrus"). The
buttons show all songs, or only those found, wanted or needing review; the Key
menu, there once a song has a key, shows only the songs in one key, with how
many each key has, and puts the spellings of one key together ("F# / Gb
minor"); and you can sort by artist, by title or by when songs were added.
Sorted by artist or title, a row of letters jumps to the first song under
each. When nothing in the library matches, the page shows the
`caracole search` line to run, unless you searched for a key, which the
offline index doesn't know. `caracole serve` serves the same page with a form
to request songs (see below).

**Songbooks** (see [Songbooks](#songbooks)), above the search box once there is
one, lists each songbook: its songs in order, those without a sheet marked
missing, and its files, the phone page first, then the PDF and the ChordPro
file. On the file on disk it names the `caracole songbook` commands that change
it; `caracole serve` adds buttons. **Select**, beside the Sort menu, puts a
box on each card: tick songs in the order they go in the songbook (each box
shows its place), search and filter between ticks, and the bar at the bottom
counts them, `3 selected`. Give the songbook a name and tap Make songbook, or
pick a songbook there is in the menu to Add to it; Clear unticks them all, and
Done leaves the mode. On the file on disk, which can't write anything, the bar
shows the command to run where caracole runs, with Copy:
`caracole songbook make "Beach nights" "Muse - Hysteria" "Radiohead - Creep"`.
On `caracole serve`, the button makes the songbook (see below).

Each song's entry in the page's data (the `<script type="application/json"
id="songs">` block) has the same `key` and `key_source` as its info.json.

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
  after it, so the lyrics read without gaps.
- **Tap a chord** for its fingerings: up to four shapes, with the fingers, the
  barre and the fret they start on (swipe, or ‹ ›, for the next). Every place
  the chord is played lights up while its card is open. The shapes come from
  [chords-db](https://github.com/tombatossals/chords-db) by David Rubert (MIT
  licence, whose notice is at the foot of every page); a chord it has no
  shape for shows the closest one, saying so.
- **The key button** (bottom right) opens the settings. **Transpose** moves
  every chord, its shapes and the key by semitones; Reset goes back to the
  song's `[transpose]`, where the viewer starts, like the PDF. In an awkward
  key, **Capo** offers frets where open shapes play it (Bb: capo 1 with A
  shapes, capo 3 with G shapes); tap one, and the chords show the shapes to
  play with the capo on. The sheet's own capo counts: the fret shown is where
  the capo goes, and it may be lower than the sheet's, or no capo at all (a
  sheet in G shapes with capo 2, transposed down two: no capo, G shapes).
- **Instead, in the key**: the chord's card also lists chords to play in its
  place that keep to the key: colours on the same root (a seventh, add9, sus2,
  a sixth), an inversion, and chords that share most of its notes (Am or Em
  for C in C major). Tap one to see its shapes, then play it for every one of
  those chords in the song; changed chords are underlined.
- **Mode**: with C minor, switch to C major, or to any mode on C (Dorian,
  Phrygian, Lydian, Mixolydian, Locrian). Each chord's notes move to the same
  degree of the new scale, so Ab becomes Am and Bb7 a Bm7b5; a note outside
  the key, such as the G major chord's B in C minor, stays where it is.
- Text size, every chord's shape in a strip above the song, and scrolling by
  itself (with the screen kept on, where the browser allows it).

The viewer remembers its settings for each song in the browser. Its key is
its sheet's, found as for info.json (see [The song's key](#the-songs-key)):
the human sheet's from the tab, or estimated from its chords, and the auto
sheet's heard in the audio; the page says which. Beside a human sheet,
`sheet (auto).html` keeps to the chords the model heard, which may be in
another key than the tab (another transposition, or a capo).

On Android, a file manager that opens the page through a `content://` address
can break its links to the songs' files. A browser, or an HTML viewer that
opens the file directly, works.

### caracole search

`caracole search [QUERY]... [--limit N] [--add N] [--key KEY]` looks in
two places, and sends no request:

    $ caracole search creep
    In your library
      Radiohead - Creep · wanted, no sheet yet · no folder yet

    On Ultimate Guitar (offline index)
      1. Radiohead - Creep · chords×2 tabs×1 guitar-pro×1 (incl. acoustic)
         https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169
         in your library
      2. Stone Temple Pilots - Creep · chords×1
         https://tabs.ultimate-guitar.com/tab/stone-temple-pilots/creep-chords-5001
         caracole add "Stone Temple Pilots" "Creep"

- **In your library**: every song, whatever its status, with its key when it
  has one (`Key G major (from the tab)`) and its folder.
- **On Ultimate Guitar**: numbered hits from the offline index, each with its
  tabs per type, one of its pages, and the `caracole add` line to paste.

QUERY is words of the artist, the title or both. Matching ignores case,
accents and punctuation (`AC/DC`, `R.E.M.`), survives a typo, and also
compares Chinese as pinyin. `--limit N` (or `-n N`) shows up to N hits from
each place, 10 by default. `--add N` adds UG hit N to wanted.txt and syncs it,
the same way `caracole add` does. N can be at most `--limit`, so only a hit the
search shows can be added, and a hit your library already has under another
name is left alone. When nothing matches well, or the query has accented or
non-Latin letters, the command also explains bare ids and prints the
`[artist_url]` line to paste, for the artist's page or one of their tab pages,
with the table's header only while overrides.toml has no `[artist_url]`
entries. For an artist whose page overrides.toml has already, under any form
of their name, it gives no line and says so. The search reads
overrides.toml for this hint alone, and still works when the file can't be
read.

`--key KEY` keeps only your songs in that key (see
[The song's key](#the-songs-key)), with or without QUERY; without it, your
songs in the key, by name. It lists up to `--limit` of them, and says how many
more there are:

    $ caracole search --key Am
    In your library, in A minor
      Soda Stereo - De Música Ligera · found · Key A minor (estimated from the chords) · /home/you/Tabs/Soda Stereo/De Música Ligera

    The offline Ultimate Guitar index has no keys: search it without --key.

KEY is written the way tabs write keys, in either case: `"A minor"`, `Am`,
`am`, `F#`, `"Bb major"`, `bbm` (B flat minor), `"La menor"`; any spelling of
the same key matches (`Gbm` finds F# minor). The
offline index knows no keys, so `--key` leaves it out, and `--add` can't go
with it. A KEY that is no key exits with status 2.

### caracole serve

`caracole serve [--address ADDRESS] [--port PORT] [--allow-host NAME]…
[--token-file FILE]` serves the library page over HTTP, at
`http://127.0.0.1:8737/` by default, with three things the file on disk can't
do:

- **Request a song.** The form at the top takes an artist, a title and,
  optionally, the album and the length. The song goes into wanted.txt at once,
  as `caracole add ARTIST TITLE` writes it (a song listed already is left as
  it is), then `caracole add` runs to put it in the library.
- **Fetch it now.** Ticked, as it is by default, the request also runs
  `caracole match` (offline), `caracole fetch --song "ARTIST - TITLE"` and
  `caracole render` (offline), so a sheet can be there in a minute or two.
  Each wanted song's card has a Fetch now button that does the same, except
  on a song that needs review: it says Review first, since `caracole fetch`
  waits for `caracole review` (or a `[match]`, `[pin]` or `[reject]` entry in
  overrides.toml) to settle the match. Lyrics, LaCuerda and the rest wait for
  the nightly run.
- **Requests**, the page at `/jobs`, lists each request, the commands it
  runs and what each printed (the newest request's output open), and
  refreshes itself every 10 seconds while one waits or runs. Stop refreshing
  keeps it still, so an output stays open to read.

Every request runs the `caracole` command line, one command at a time, so the
server is never more aggressive than you at a terminal: each command takes
caracole's lock (behind a nightly run, it waits), keeps the pause after the
last request any caracole sent, and keeps the budgets and cooldowns. The
queue holds 20 requests and one per song: asking again for a song gives its
request, and Fetch it now on a song whose request only adds it fetches it too.
A request is in wanted.txt as soon as it's made, so a full queue or a restart
loses no song. The page links each
song's files, which the server sends from the library: PDFs, text, info.json,
and Guitar Pro files as downloads, never through a symbolic link, never a
hidden file, and never the database, the token or the cache.

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
  refused too; reload the page.
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
  then every song's sheet in order, in caracole's look and each in its own key
  (`[transpose]`), all from one chordpro run, with the Chinese font when a song
  needs it. A song without a sheet keeps its place: the contents name it
  ("Hysteria · Muse · missing: no sheet yet"), and its page says so.
- **`songbook.html`**: one page for the phone, which opens from the synced
  folder and loads nothing. It opens on the contents; tap a song to open it in
  the sheet viewer, with everything the viewer does (chord shapes,
  transposition, chords to play instead, modes, scrolling by itself), each
  song in its own key and keeping its own settings. Next and Previous, a swipe
  across the sheet or the arrow keys go from song to song, skipping the
  missing ones, and Contents goes back. Opened again, the page takes you back
  to the song you had open, where you were in it; the contents mark it as
  "last opened". Without JavaScript, or printed, it is every song one after
  the other.
- **`songbook.cho`**: every song's ChordPro, in its key, split by
  `{new_song}`, to import into a songbook app such as SongbookPro or OnSong.
  chordpro writes it, so the chords are already transposed; songs without a
  sheet aren't in it.

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

caracole keeps your comments and layout when it changes the file. A song is
found the way other commands find one: accents, case, Traditional or
Simplified characters and a version suffix ("- Remastered 2007") don't count.
A name can't be empty, start with a dot, hold a line break or be longer than
80 characters, and two songbooks can't have names that would share a folder
(`Camp/fire` and `Camp-fire`; `Campfire` and `campfire`). A songbooks.toml that
can't be read (not TOML, or a symbolic link, which caracole never reads
through) makes no songbook: the error names the file and the line, every
songbook's files stay as they are, and everything else goes on.

### caracole songbook

- **`caracole songbook make NAME "ARTIST - TITLE"...`** makes a songbook of
  these songs, in this order, and its files. A song is found by its artist and
  title written any way, or by a search of your library that one song answers
  well ("ban ma ban ma" for 宋冬野 - 斑马，斑马, or a typo), and it says which
  song it took: `Took 宋冬野 - 斑马，斑马 for "ban ma ban ma"`. The songbook keeps
  each song as the library names it. A song the library hasn't got is refused,
  with what you may have meant, and nothing is written:
  `No song "Radiohed - Karma" in the library: did you mean "Radiohead - Karma Police"?`
  A name another songbook has is refused too.
- **`caracole songbook list`** shows every songbook, how many songs it has and
  how many have no sheet, and its files.
- **`caracole songbook show NAME`** lists its songs in order, each one's
  transposition, the missing ones marked (`(missing: no sheet yet)`,
  `(missing: not in the library)`), and where its files are.
- **`caracole songbook add NAME "ARTIST - TITLE"...`** adds songs at the end;
  one it has already stays where it is.
- **`caracole songbook remove NAME "ARTIST - TITLE"...`** takes songs out. A
  song removed from the library goes by the name the songbook gives it.
- **`caracole songbook move NAME "ARTIST - TITLE" POSITION`** moves a song,
  1 being the first; past the end is last.
- **`caracole songbook rename NAME NEW`** renames it; its files move to the
  folder of the new name.
- **`caracole songbook delete NAME`** deletes it, and the files caracole made
  of it. A file of yours in its folder stays, and so does the folder.
- **`caracole songbook render [NAME] [--force]`** makes the files of one
  songbook, or of all, that need it, and prints
  `1 rendered, 2 up to date, 0 failed`. It exits 1 when a file couldn't be
  made, and the log says why, as `songbook Campfire: no songbook.pdf: …`.

A NAME is found in any case. Each change writes songbooks.toml, makes the
songbook's files and rewrites `_todo.md` and `index.html`, holding caracole's
lock; `list` and `show` only read, and never wait. A songbooks.toml that can't
be read exits 2.

`caracole render` and the nightly run make the songbooks' files after the
sheets, and a file only when what it is made from changed: its songs, their
order, their sheets, their transpositions, caracole's PDF style or the font;
or when it is no longer as caracole wrote it (deleted, edited, a link in its
place). A songbook gone from songbooks.toml (deleted or renamed by hand) loses
the files caracole made of it at the next render, each only while it is still
as caracole wrote it. Like the sheets' PDFs, a songbook with a Chinese song
gets its PDF once a CJK font is set; its page and its ChordPro file need none.

## overrides.toml: your decisions

`overrides.toml` sits in the library folder (or where `overrides_file` says),
and can live in git. `caracole review` writes `[match]`, `[alias]`, `[pin]`,
`[ignore]` and `[reject]` for you; you write the rest by hand. These are all
the tables:

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

[ignore]       # songs caracole leaves alone
songs = ["Some Artist - Some Interlude"]

[block]        # tabs never to use
tab_ids = [1601668]

[reject]       # UG songs that are not the song: never offered for it again
"Maná - Rayando el Sol" = ["ana-gabriel/rayando-el-sol"]
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

The font is used only for sheets that need it. Some transcribers type a
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
      sheet.cho  sheet.pdf  ChordPro, and a PDF in your key
      sheet.html            the sheet viewer, for the phone
      lyrics.txt            the lyrics, from LRCLIB
      lyrics.lrc            the timed lyrics, when LRCLIB has them
      guitar-1.gp5          Guitar Pro or Power Tab files: filed by rank, or from gtptabs.com
      score-1.mscz          scores you downloaded (MuseScore, MusicXML, PDF, MIDI), filed
      tab.txt  tab.json     the best text tab
      sheet (auto).txt      made from audio you bought, when no human sheet exists;
      sheet (auto).cho      it stays, with its ChordPro, PDF and viewer, beside a
      sheet (auto).pdf      partial human sheet, until a complete one replaces it
      sheet (auto).html
      info.json             where everything came from, and the song's key
Music/                      music_dir: the tracks you bought (caracole only reads it)
```

Folder names keep their accents and scripts, but never contain a path
separator or a character file systems reserve: `AC/DC` becomes `AC-DC`.

**The `.cho` files** are the sheet in ChordPro, a plain-text format that puts
each chord in brackets before the syllable it falls on (`[Am]Yesterday`).
caracole makes `sheet.cho` from `sheet.txt`, in your key (`[transpose]`), and
renders the PDF from it. You don't need to open it: it is there for songbook
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
only it: `sheet.txt`, `sheet.json`, `tab.txt` and `tab.json` at the next
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
    Added to /home/you/Tabs/wanted.txt, line 16:
      宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Song 宋冬野/斑马斑马: new; the next `caracole run` looks for it

The album and duration make the lyrics lookup exact. Written "斑马，斑马",
with a comma, it is the same song to caracole, and so is 斑馬斑馬, in
Traditional characters, as some releases write it.

**2. It isn't found on Ultimate Guitar.** UG's sitemaps list every tab of
宋冬野 by a bare id, so the local index has none of them:

    $ caracole match --dry-run
    not_found      -  -             宋冬野 - 斑马斑马 → -  CHANGED unmatched → not_found

`--dry-run` saves nothing. After the next `caracole run` (or `caracole match`),
the to-do page lists 宋冬野 under "Artists to find on Ultimate Guitar", with a
link to search UG and the line to paste, and puts the song on the buy list
meanwhile:

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

## Running it on the NUC

[deploy.md](deploy.md) sets caracole up as a nightly NixOS service: the timer,
the hardened units, agenix secrets, Syncthing for the library and the music,
restic backups, the offline auto-chords unit, and caracole-web, which serves
the library page with its request form. There, run any command as the service
does with `sudo caracole-admin COMMAND`, for example
`sudo caracole-admin index build`.
