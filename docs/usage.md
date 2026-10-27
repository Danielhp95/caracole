# Using caracole

You list the songs you want to learn. Caracole builds a private library from
them: for each song a sing-along sheet (chords over the full lyrics), the
lyrics on their own, and guitar parts where they exist. A nightly
`caracole run` does the work within a small request budget, and
`Library/_todo.md` lists only what it can't decide without you.

This page covers using caracole on any machine. [deploy.md](deploy.md) sets it
up as a nightly service, on NixOS or on Ubuntu without Nix, with Syncthing and
backups.
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
- [Fonts in the PDFs](#fonts-in-the-pdfs)
- [Fonts for Chinese sheets](#fonts-for-chinese-sheets)
- [The library folder](#the-library-folder)
- [A worked example](#a-worked-example)
- [Running it on a server](#running-it-on-a-server)

## Configure

Caracole reads one TOML file: the one `--config` (`-c`) or `$CARACOLE_CONFIG`
names, or else `~/.config/caracole/caracole.toml` (under `$XDG_CONFIG_HOME` when
that is set). Without a file, the defaults apply. Every key is optional, and an
unknown key is an error, so a typo never falls back to a default unnoticed. So
is a value of the wrong type or out of range: write `true` and `false`, and
numbers, without quotes, and paths and names as quoted strings. The commands
then exit with status 2 and name the key. An older caracole's `[spotify]`,
`guitar_pro_mode`, `keep_guitar_pro` under `[rank]` and `token_file` under
`[ntfy]` are unknown keys now: delete them before you upgrade, or every
command, the nightly run and `caracole serve` among them, stops at its start.
`~` is your home folder, and a relative path is relative to the config file's
folder.

Here is every key with its default. The commented-out keys have none.

```toml
# data_dir = "..."                # one folder for the four below (see below)
library_dir = "~/Tabs"            # sheets, lyrics, _todo.md, index.html, wanted.txt
music_dir = "~/Music"             # tracks you bought; read only, used only for auto-chords
# state_dir = "..."               # the database and the lock (see below)
# cache_dir = "..."               # every raw response, kept forever (see below)
# overrides_file = "..."          # default: overrides.toml in library_dir
# wanted_file = "..."             # default: wanted.txt in library_dir
user_agent = "caracole/0.1 (personal tab library)"
chordpro_bin = "chordpro"         # the program that renders PDFs
ytdlp_bin = "yt-dlp"              # or $CARACOLE_YTDLP_BIN; see "Audio from YouTube"
# pdf_fonts = "/path/to/folder"   # or $CARACOLE_PDF_FONTS; see "Fonts in the PDFs"
# cjk_font = "/path/to/font.ttf"  # or $CARACOLE_CJK_FONT; see "Fonts for Chinese sheets"

[ntfy]                            # optional: a summary after each run, and alerts
# url = "https://ntfy.sh/a-long-private-topic"

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
[providers.harptabs]              # harmonica tabs, kept for your songs
enabled = true                    # false: caracole asks harptabs.com nothing
budget = 20
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

[rank]                            # which sheets and text tabs are kept
coverage_threshold = 0.8          # a sheet is complete when it covers 80% of the lyric lines (0-1)
line_match = 85                   # how close a lyric line must be to count as covered (0-100)
prior_votes = 10                  # m in the Bayesian rating (v·R + m·C) / (v + m)
scored_sheets = 3                 # sheets per song scored for coverage: the top 3 by rating
label_penalty = 0.5               # off the rating of an intro, solo, outro, riff or lesson
variant_bonus = 0.25              # onto an acoustic or live version, when your song is one

[autochords]                      # read only by `caracole autochords`
# btc_weights = "/path/to/weights.pt"         # or $CARACOLE_BTC_WEIGHTS
# beat_checkpoint = "/path/to/final0.ckpt"    # or $CARACOLE_BEAT_CHECKPOINT
device = "cpu"                    # where the models run
```

Caracole keeps one sheet and one text tab per song, and beside the sheet the
other Ultimate Guitar versions it scored (`scored_sheets`). Scores and
thresholds can't be negative, scores stop at 100, and `scored_sheets` is a
whole number.

**Folders.** With `data_dir`, everything is in one folder: `library_dir`,
`music_dir`, `state_dir` and `cache_dir` default to its `library`, `music`,
`state` and `cache` folders, and one you set yourself still wins. Without
it, `state_dir` is `$STATE_DIRECTORY` when systemd sets it, else
`$XDG_STATE_HOME/caracole`, else `~/.local/state/caracole`. `cache_dir` works the
same way from `$CACHE_DIRECTORY`, `$XDG_CACHE_HOME/caracole` or
`~/.cache/caracole`. The state folder holds `caracole.sqlite` and
`caracole.lock`: back it up, but don't sync it. The cache keeps every
response caracole has received, so it rarely asks for a page twice; deleting it
costs only requests. PDFs are made in it too, each in a private folder that
goes when the PDF is done, so caracole must be able to write there. Its
`icons` folder holds each site's icon, for `index.html` (see
[Where each file came from](#where-each-file-came-from)).

**The database.** Before a new caracole migrates `caracole.sqlite`, it copies it
to `caracole.sqlite.vN.bak`, N being the version it had. One caracole migrates
it at a time (a lock on `caracole.sqlite.migrating`, beside it): `caracole
serve`'s first requests after an upgrade, or the nightly run starting with
them, wait the few seconds it takes, then find it migrated. A database a newer
caracole migrated, after a rollback say, stops every command that uses it with
status 2: `database: … is at schema version 11, but this caracole knows up to 10:
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
pages caracole knows, with no request, even while Ultimate Guitar cools down. Schema 8
adds an index of the words of the UG index's artists' names, for finding an artist by
a word of their name and by a close spelling of it (see [caracole search](#caracole-search)):
the first command after the upgrade builds it from the index, in about a second, and it
adds about 10 MB to a full index. Schema 9 takes out what caracole no longer uses: Ultimate
Guitar's Guitar Pro and Power Tab tabs (the picks among them, and their rows in the UG index:
about 270,000 of a full index's 1.6 million, with the artists and names they alone had), and
what Spotify left (its ids among a song's sources, its state; an old `spotify_token.json` in
the state folder is yours to delete). A file you dropped into `_inbox/` that an older caracole
filed under a Guitar Pro pick on Ultimate Guitar stays, as the song's own inbox file. It takes
a few seconds more than the copy. Schema 10 adds harptabs.com's index, empty until the nightly
run, or `caracole harptabs`, reads its sitemap (see [caracole harptabs](#one-step-at-a-time)).
Schema 11 adds the tabs of harptabs.com's artist pages, empty until `caracole harptabs --index`,
or the nightly run, reads them.
The ukulele chords need no change of schema: an index built before reads Ultimate Guitar's
ukulele sitemaps at its next refresh (see [caracole index build](#caracole-index-build)). A state
folder caracole can't use ends a command with status
1 and `can't open the database …` (or `can't open …/caracole.lock: …`).
`caracole add` is the exception to both: it keeps its line and warns (see
below).

**No secrets.** caracole reads none. ntfy is a topic's `url` alone, posted to
with no token, so choose a long topic name nobody would guess. It is no secret
on the host either: on NixOS it is in the Nix store, which every user of the
machine can read. And `caracole serve` has no sign-in (see [caracole serve](#caracole-serve)). A `token_file`
under `[ntfy]`, which an older caracole read, is now an unknown key like any
other: delete it, and the token.

**Providers** are exactly `ug`, `lrclib`, `lacuerda`, `gtptabs`, `musescore`,
`harptabs` and `youtube`. Any other `[providers.…]` table is an error, like any other
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
scored and the text tab; LaCuerda's for a song with a sheet
already), stops once the hour's lookups have spent half of `lookup_per_hour`,
so an evening of songs looked up on the spot keeps getting sheets (about
twenty to thirty an hour with the defaults). What a lookup leaves undone waits
for the nightly run. Either
pace sends one request at a time to a site, never less than its robots.txt's
`Crawl-delay` apart (none of the sites caracole reads sets one for every
robot), and keeps everything else below: robots.txt, the cache, the blocks and
cooldowns. Only gtptabs.com, MuseScore, harptabs.com and YouTube can be turned
off: with `enabled = false` under `[providers.gtptabs]`, `[providers.musescore]`,
`[providers.harptabs]` or `[providers.youtube]`, caracole sends that site nothing, the nightly run skips
its step, and the to-do page's Provider health says it is off. The other three
are what caracole is built on, so `enabled` in their tables is an unknown key.
YouTube is on only where caracole can make chords of what it downloads (see
[Audio from YouTube](#audio-from-youtube)); its budget counts yt-dlp runs, not
requests.

**Guitar Pro files** come two ways. gtptabs.com's robots.txt leaves its
downloads open, so caracole downloads a file there for each song that has none
(`caracole gtptabs`, in [One step at a time](#one-step-at-a-time)); and one you
get anywhere yourself, dropped into `_inbox/` named as the song is, is filed
under its song (`caracole scan`). caracole takes none from Ultimate Guitar, whose
robots.txt closes its downloads to bots: from there it takes chords, text tabs
and ukulele chords alone.

**Harmonica tabs** come from harptabs.com, the one large free site of them
(about 27,000 tabs: hole numbers over the lyrics, "6" a blow, "-5" a draw). For
each song you want that has none, caracole matches its title against the
site's sitemap, reads the pages of the tabs titled so, and keeps the most
viewed one by your song's artist as `harmonica-1.txt` (`caracole harptabs`, in
[One step at a time](#one-step-at-a-time)), and the render gives it a page beside
it, `harmonica-1.html`, its holes over the words (see [The harmonica tab
page](#the-harmonica-tab-page)). Its site terms ask that nothing be
copied, and its API's that the tabs not be mirrored: caracole keeps the tabs of
your own songs alone, for you, never a tab of a song nobody asked for. So that
a search finds its tabs by artist as well as by title, as it finds Ultimate
Guitar's, caracole reads harptabs.com's artist pages into a local index (the
names of an artist's tabs, never the tabs themselves): `caracole harptabs
--index`, a budget at a time, and the nightly run with what its harptabs budget
leaves. It asks with caracole's own user agent, as it asks every site, and an
HTTP 403, a 429 or a challenge from harptabs.com is a block like any site's: a
cooldown and one alert, never a way around it (see [caracole run](#caracole-run)).

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
| `-vv` | debugging lines too, each with the name of its logger, and the logs of the libraries caracole uses (httpx, httpcore, and numba or torch under auto-chords), which otherwise show only their warnings and errors |

A warning starts with `warning:` and an error with `error:`, coloured on a
terminal unless `$NO_COLOR` is set; nothing is coloured when the output isn't
a terminal. Under systemd, each line starts with its priority for the journal
instead (see [deploy.md](deploy.md#logs)).

An unexpected error, a bug in caracole, ends the command with exit status 1:
one line that says so, then its traceback, on stderr.

## Say what you want to learn

### wanted.txt

`wanted.txt` sits in the library folder, so Syncthing carries it to your
laptop and phone and you can edit it anywhere. It is caracole's one source of
songs. One song per line:

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
- Edit the line's album or duration, and the next sync changes the song, and
  the duration the scan checks a purchase against; take one off the line, and
  it comes off the song.
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
- Deleting a line doesn't delete the song from caracole, and the song keeps
  the album and the duration the line gave it. To keep a song but stop all work on it, put it under
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
library knew, one whose line you deleted, say. `caracole -v add …` also prints the song's
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
    Ultimate Guitar: sheet 4170 · tab 4172 · kept beside it: tab 4169, tab 4171.
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
   the others scored are kept beside it, said as `kept beside it: tab 4169,
   tab 4171` (see [caracole versions](#caracole-versions)); then the text
   tab.
7. **LaCuerda**, for a Spanish song without a complete sheet,
   **gtptabs.com**, for a Guitar Pro file, and **harptabs.com**, for a
   harmonica tab, from the indexes the nightly run keeps: the harptabs.com tab
   you picked (`--harptabs URL`, its page's address, recorded under
   `[harptabs]`), else the most viewed by the song's artist. A tab you picked is
   kept beside the song's other harmonica tabs, never in place of one.
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
  sheet, chords or ukulele chords, or a text tab, by the offline index), and
  beside its pins of the other kind: a text tab picked after a chords sheet
  keeps the sheet you chose. A page of another type (a Guitar Pro file's, a
  bass tab's), when its address says so, is refused before anything is added
  or recorded: `tab 301 is not a chords, tabs or ukulele chords page`.
- `--lacuerda URL` is the LaCuerda song to keep the sheet of, its page's
  address (its best Letra y Acordes version) or a version's
  (`https://acordes.lacuerda.net/estopa/como_camaron-2.shtml`): it is recorded
  under `[lacuerda]`, and kept as the sheet whatever the song's language or
  its coverage of the lyrics; Ultimate Guitar's sheets never replace it, and
  the song gets Ultimate Guitar's text tab all the same. A `[pin]` of an
  Ultimate Guitar sheet wins over it.
- `--album ALBUM` and `--duration M:SS`, for a song new to the library, as in
  `caracole add`.
- `--progress` adds a JSON line per stage, which `caracole serve` reads.
- `--no-songbooks` leaves the songbooks that list the song as they are (by
  default the lookup makes them again). The page's Get the missing songs now
  uses it for each song and makes the songbook once, after them all; such a
  lookup's Try again runs alone, without it, and makes them again itself.

A song ignored in overrides.toml, or one wanted.txt can't hold, is not looked
up, and exits 1. A song the matcher isn't sure of gets everything but its
Ultimate Guitar sheet: pick its UG song with `--ug`, with Get it on the page
`caracole serve` serves, or with `caracole review`.

### caracole versions

Ultimate Guitar keeps several chords versions of a song (Wonderwall has 13),
and caracole keeps the three it scores against the lyrics: the best as
`sheet.txt`, the title's, and the other two beside it as `version-<tab>.txt`
(see [the library folder](#the-library-folder)). `caracole versions "ARTIST -
TITLE"` lists them all, in caracole's order (a song whose sheet is one of UG's
Ukulele Chords, as it has no chords there, lists those: "2 Ukulele Chords
versions on Ultimate Guitar"): the versions that cover the
lyrics first, then by the rating weighed by its votes; those never scored
after, by that rating; those Ultimate Guitar took down last. It only reads:
no request, and no wait for another caracole.

    $ caracole versions "Oasis - Wonderwall"
    Oasis - Wonderwall: 13 chords versions on Ultimate Guitar; the title opens tab 1064463, caracole's pick.
      Ver 3 of 13 · 4.86★ (408) · tab 1064463 · kept · the one · the version that oasis play on Wembley 2008
      Ver 1 of 13 · 4.85★ (12,629) · tab 39144 · kept
      Ver 5 of 13 · 4.91★ (95) · tab 1213325 · 40% of the lyrics · kept
      Ver 2 of 13 · 4.62★ (1,240) · tab 6624
      …
    Keep one beside the sheet: caracole versions "Oasis - Wonderwall" --keep TAB. Make one the sheet: caracole versions "Oasis - Wonderwall" --choose TAB.

A line says `the one` for the version the title opens; `kept` for one kept
in the song's folder; `kept: the sheet's very text` for a version whose text
is the sheet's, which the sheet stands for; the share of the lyrics a
version scored short of them covers; `gone from Ultimate Guitar` for one UG
took down (its files go at the song's next fetch); and the first lines of the
tabber's note. When the sheet is LaCuerda's or auto-chords', the first line
says so, and no version is the one.

- `--keep TAB` (the tab's id or its page's address) keeps one more version
  beside the sheet, now: its page is read at the lookup pace (one request,
  within a lookup's six and the hour's sixty, under caracole's lock as
  `caracole get` takes it), it is written as `version-<tab>.txt` and `.json`,
  and its viewer page is made. It stays kept whatever the ranking does, while
  Ultimate Guitar has it and you don't `[block]` it. A block, a spent budget
  or a site's error keeps nothing, says so and exits 0. A version kept
  already sends nothing, and stays kept from then on. A version whose text
  is the very text of the song's text tab (`tab.txt`) isn't kept: one text
  has one file in the folder.
- `--keep-more` keeps the versions not kept yet, as `--keep` would one by
  one, in caracole's order, as many as one lookup may: their pages are read at
  the lookup pace, until the lookup's six requests or the hour's sixty are
  spent; the rest stay for the next `--keep-more`. It passes over the sheet,
  the versions kept already, those Ultimate Guitar took down, those under
  `[block]`, and those a keep found it can't keep (a page with no sheet on
  it, or the very text of another file in the folder), which it never reads
  again. A block or a site's error stops it: what it kept before stays kept.
  Then the song's pages are made and the library page written, once, and it
  says how many it kept and how many are left:

      $ caracole versions "Oasis - Wonderwall" --keep-more
      …
      Kept 6 versions of Oasis - Wonderwall; 4 more not kept: ask again.

  With nothing left to keep it says so and sends nothing. It exits 0 in every
  one of those cases.
- `--choose TAB` makes a version the sheet: it is `caracole get --tab` for
  that version's page, so it is recorded under `[pin]` in overrides.toml, and
  the title, the PDF, the viewer and the songbooks use it. caracole's top
  versions stay kept beside it.
- `--clear` takes the song's chords pins out of `[pin]` (a text tab pin
  stays), comments and the rest of the file kept, then looks the
  song up again: caracole's pick is the sheet once more, and a version you
  had chosen outside the top three leaves the folder. Without a pin it says
  so and changes nothing.
- `--progress` adds a JSON line per stage, as `caracole get --progress` does,
  for `caracole serve`.

A tab that isn't one of the song's chords versions, or one Ultimate Guitar
took down, exits 1; so does a song not in the library. Two of `--keep`,
`--keep-more`, `--choose` and `--clear` at once exit 2.

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
    caracole won't bring it back, from wanted.txt or the nightly run, until you ask for it again: caracole add, the web page's request form, or a line in wanted.txt.
    Remove it? [y/N]: y
    Removed Radiohead - Creep: deleted 6 files, took 1 line out of wanted.txt.

`--yes` (`-y`) doesn't ask. Without it and without an answer (from a script,
say), nothing is removed and it exits 1.

- **What goes.** The song's lines in wanted.txt, every line that names it,
  the rest of the file kept byte for byte, comments included. The files
  caracole wrote in the song's folder: the sheets, tabs and Guitar Pro files
  it keeps (`sheet.txt`, `sheet.json`, `tab.txt`, `guitar-1.gp5`, the scores
  it filed from `_inbox/`…), the `.cho` files and PDFs it made from them (the
  `sheet (G Dorian, capo 0).pdf` exports of `caracole render --version` too),
  every file of a version kept beside the sheet (`version-<tab>.txt`,
  `.json`, and the viewer `version-<tab>.html` a render wrote, a version's
  page the last fetch let go too), each harmonica tab and the page a render
  wrote of it (`harmonica-1.txt`, `harmonica-1.html`), `lyrics.txt` and `lyrics.lrc` when they are LRCLIB's, and `info.json`.
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
  nightly run nor `caracole sync` brings it back: its line in wanted.txt is
  gone. `_todo.md`, `index.html` and `caracole search` no longer list it.
- **Until you ask again.** `caracole add`, the web page's request form, or a
  line for it that you write in wanted.txt brings it back as a new song, and
  the next run looks for it from scratch. A device that syncs back an old copy
  of wanted.txt with the line in it brings it back too.
- A wanted.txt caracole can't read (a symbolic link, say) stops the removal
  before anything goes: the line it couldn't take out would bring the song
  back.

`caracole remove --list` lists the songs removed, the latest first, and when.
`caracole remove` on a song removed already says when it was, and how to
bring it back. Like `caracole review`, it asks before it takes caracole's lock,
so the nightly run never waits for your answer; `--list` only reads. On the
web page, each song's **Remove**, under its line's chevron, does the same, right
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
a site named so, and a search of the artist pages caracole has read (斑马, Banma
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

`caracole sync` reads wanted.txt and prints a summary such as
`wanted.txt 3 songs, 1 new`, followed by each problem. Then it rewrites `_todo.md` and `index.html`. The nightly run starts
with the same sync.

`caracole sync`, `caracole add` and `caracole search --add` never fail because of
the pages: with an overrides.toml that can't be read, or a page that can't be
written, they still add and sync your songs and exit 0. They warn, and leave
the pages as they were.

## The first run

With some songs listed:

    caracole index build       # once: Ultimate Guitar's sitemaps into a local index
    caracole match --dry-run   # how every song matches, saving nothing
    caracole run               # one nightly run, now

### caracole index build

Caracole never searches Ultimate Guitar, whose robots.txt disallows its search
page. It reads the sitemaps UG publishes for crawlers instead, and keeps a
local index of every chords, text tabs and ukulele chords page, well over a
million. Tabs of the other types are counted and left out, Guitar Pro and
Power Tab files among them: caracole uses none of UG's, so a song UG has only
as one of those is not found there. UG's "Ukulele Chords" (about 150,000
pages, in their own sitemaps, `sitemap_ukulele1.xml` to `sitemap_ukulele4.xml`)
are the same chord-over-lyrics sheets with ukulele shapes beside them: a song
with no chords on UG takes its sheet from them (see [caracole
fetch](#one-step-at-a-time)). `caracole index build` reads the sitemap index
and its 45 tab sitemaps, one request at a time, 10–20 seconds apart: about 46
requests, 80 MB and 12 minutes. Its budget is 100 requests, more than a night's, so one build is
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
    [1/5] sitemap1.xml  2,000 tabs: 1,315 indexed, 221 bare ids, 454 of other types, 10 closed by robots.txt  4 left, about 1 min
    [2/5] sitemap2.xml  2,000 tabs: 1,329 indexed, 201 bare ids, 465 of other types, 5 closed by robots.txt  3 left, about 50 s
    [3/5] sitemap3.xml  2,000 tabs: 1,332 indexed, 204 bare ids, 462 of other types, 2 closed by robots.txt  2 left, about 30 s
    [4/5] sitemap4.xml  2,000 tabs: 1,318 indexed, 215 bare ids, 459 of other types, 8 closed by robots.txt  1 left, about 15 s
    [5/5] sitemap_last.xml  600 tabs: 414 indexed, 58 bare ids, 128 of other types
    Index built: 5 sitemaps read; 5,708 new tabs.
      Indexed     5,708 tabs: chords 3,225, tabs 2,483
      Artists     1,488
      Bare ids    899 of 8,600 tab URLs (10.5%): with no artist or title in the URL, only artist pages lead to them
      Left out    1,968 of other types (guitar-pro 772, bass 469, power 352, ukulele 224, drums 76, video 75)
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
files you already have: `sitemap1.xml` to `sitemap40.xml`,
`sitemap_ukulele1.xml` to `sitemap_ukulele4.xml` and `sitemap_last.xml`,
gzipped or not. It sends no requests. The 41 files of guitar tabs take
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
sitemap of each kind (`sitemap40.xml`, `sitemap_ukulele4.xml`) and any tab
sitemap not indexed yet, whether new, left by a stopped build, or one an older
caracole didn't read: an index built before caracole kept ukulele chords reads
the four ukulele sitemaps at its next refresh. These are conditional requests, which usually answer "unchanged". A
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
refreshed; then, once harptabs.com's sitemap is read, how far its artist index
has got: `harptabs.com: 1204 of 10428 artist pages read, 5130 tabs; caracole
harptabs --index reads the rest.`

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

1. **sync**: wanted.txt.
2. **icons**: fetch the icon of each site the library has something from, once
   (see [Where each file came from](#where-each-file-came-from)). It comes
   before the steps that can spend a site's budget.
3. **index**: refresh the index, and mark the songs that have new tabs.
4. **match**: match every song again, locally.
5. **lyrics**: ask LRCLIB for the songs that have no lyrics yet.
6. **fetch**: rank and keep Ultimate Guitar sheets and text tabs.
7. **lacuerda**: look on LaCuerda for Spanish songs without a complete sheet,
   then read LaCuerda's listings of every artist into a local index, for
   searches, with what the sheets left of its budget (once the library has a
   song: an empty one asks no site). The artist pages caracole's HTTP cache
   holds go into that index first, with no request. Once the listings are read
   whole, what is left of the budget reads the pages of LaCuerda's most popular
   artists (the most songs its listings count first) not read in 30 days, 10 a
   night at most, so that a search finds their songs; the summary says how many
   (`4 popular artist pages read, 0 errors`).
8. **scan**: link purchases in Music/, and file Guitar Pro downloads.
9. **gtptabs**: download a Guitar Pro file from gtptabs.com for each song that
   has none. It comes after the scan, so a file you dropped into `_inbox/` is
   filed first, and that song gets none from gtptabs.com. As for the other
   sites, the summary counts the songs an error left for the next run on the
   cause's line; sitemaps it couldn't read get a line of their own.
10. **harptabs**: keep a harmonica tab from harptabs.com for each song that has
    none and a tab there by its artist (see [caracole
    harptabs](#one-step-at-a-time)). What its budget leaves reads artist pages
    into harptabs.com's local index, for searches: your songs' artists first,
    then the others, each again after 30 days (`artist index: 18 pages read,
    1204 of 10428 artists`). Only once the library has a song.
11. **musescore**: read MuseScore's song sitemaps into a local index, for the
    to-do page's links to its pages. It downloads nothing.
12. **youtube**: take the audio of a few songs no human sheet was found for from
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
  overrides.toml or wanted.txt.
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
is left goes to text tabs, about a page a song. Before sheets came first, a
live run spent 8–12 requests a song.
A long list therefore fills in over a few nights, and a song the budget cut
off half-way resumes from the cache the next night.

gtptabs.com gets at most 20 requests a run, 10–20 seconds apart. The first
run spends seven on its sitemap index and six sitemaps, and reads them again
after 30 days, when each unchanged one costs a request. Then each song costs
its artist's page, which serves every song by that artist for 30 days, and a
download for its file.

harptabs.com gets at most 20 requests a run, 10–20 seconds apart. The first run
spends one on its sitemap, a single 6.4 MB file with no validators, read again
after 30 days. Then a song costs the pages of the tabs titled as it is (only
when the sitemap lists an artist by its artist's name), eight at most, each
read once and cached for good: most songs cost one or two, a common title a few
more. Its artist pages, for searches, cost one request each, and are read again
after 30 days: what the budget leaves reads about 15 a night, so the whole
index (about 10,400 artists) is `caracole harptabs --index`'s, which at 10–20
seconds a request takes some 44 hours of requests, a `--budget` at a time.

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
from when the command started, and sends one ntfy message too, titled as the
run's ("caracole: Ultimate Guitar blocked"), its text the line the command
prints: `caracole fetch`, `index`, `icons`, `lyrics`, `lacuerda`, `gtptabs`,
`harptabs`, `musescore` and `youtube` alike. So does a tab picked on caracole serve's review
page, which runs `caracole fetch --song`. A lookup (`caracole get`, `caracole
lacuerda --artist`, `caracole harptabs --artist`) sends none: it says so where you asked. A run, a command
or a lookup the site answers without a block starts the count again; one the
site answered with nothing but errors doesn't, and neither does a run that let
a lookup go first which was blocked meanwhile: that block's cooldown stands.
That block is the run's too: the run sends that site nothing more, and its
ntfy message says so, but it is one block, not two in a row.
Neither a block, nor a spent budget, nor any
other error from a site marks a song not found or its lyrics missing: the
song waits for the next run. An answer that won't read but was cached all the
same (a maintenance notice served as a page, say) is asked for once more,
past the cache, by the next run that needs it: from UG, LaCuerda,
gtptabs.com, harptabs.com and LRCLIB alike. Caracole never works around a block: no proxies,
no retries from elsewhere. A tab page UG keeps serving without its data is
asked for again after 7 days, then twice as long each time, up to 90 days;
meanwhile the song is filled from its other versions.

Nor does caracole ask for a page robots.txt closes to bots, or follow a
redirect to one: UG's search, download and print pages, and a few tab pages
(`/tab/track/…`); gtptabs.com's search, its Russian copy of every page
(`/ru/`) and each artist's "Download all" archive (`/storage/`); harptabs.com's
search, its API and its pages' data for scripts (`/*?*_rsc=`); MuseScore's
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
  text is the sheet's very text gets no files: the sheet stands for it. A
  version you keep with [`caracole versions --keep` or
  `--keep-more`](#caracole-versions) stays kept whatever the ranking.
  A song Ultimate Guitar has no chords for (none in the index, none on its
  artist's page) takes its sheet from UG's Ukulele Chords versions, rated and
  scored as chords are: the same chord-over-lyrics sheet with ukulele shapes,
  its files labelled "Ukulele Chords" on the library page, its versions those
  `caracole versions` lists. A song with chords keeps them, and its ukulele
  versions are never read (the sheet viewer draws ukulele shapes on any
  sheet); a chords version found later replaces a ukulele sheet. A chords
  page that can't be read is no reason to take the ukulele one: the song waits.
  A `[pin]` of a ukulele version makes it the sheet, as a chords pin does.
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
  `Artist - Title: sheet 101 · tab 402 (3 requests)`,
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
  runs it, and so does Ask LaCuerda (1 request) for a name its listings
  haven't reached yet, once LaCuerda's search for the query can't go by hand
  (that button sends the search first: see the library page below).

  **`caracole lacuerda --search QUERY`** asks LaCuerda's own search for the
  songs of QUERY now, one request at the lookup pace, and puts every song it
  answers into the index (as an artist page's would be, beside what the index
  holds), with each artist no listing read names yet: the songs of an artist
  whose page caracole hasn't read are then found locally. LaCuerda's search reads
  only the words of 4 letters or more, accents folded (`la flaca` is `flaca`,
  `19 días y 500 noches` is `dias noches`), and caracole asks it for songs alone
  (`busca.php?exp=…&canc=1`): the artists are its listings'. A query is asked at
  most once in 30 days (under any spelling LaCuerda reads the same, its words in
  any order); the HTTP cache keeps the answer. It first puts the artist pages the
  HTTP cache holds into the index, and asks nothing when your library or the index
  then answers the query well (`Found already: caracole has “…” already, in your
  library or its copy of LaCuerda's index; no request sent.`). Its last line starts
  with what LaCuerda answered, which caracole serve's request line shows:
  `Searched: LaCuerda has 2 songs for “corazon espinado”, in the index now.` (or,
  asked within 30 days, `Searched: LaCuerda was asked for “…” on 2026-10-22 03:30
  UTC: 2 songs, in the index.`), `Nothing found: LaCuerda has no song for “…”.`,
  or `Not searched: …` for a query with no word it reads, a cooldown, a block,
  the hour's lookups spent or an error (`Not searched: LaCuerda failed (…);
  nothing changed: try again later.`; a page its server cut short is such an
  error, never "no results"), all of which exit 0. Its requests count in the
  hour's lookups (`lookup_per_hour`); `--auto`, a search caracole serve's page
  sent by itself, keeps within 20 such searches an hour too (`Not searched: this
  hour's 20 searches of LaCuerda the page sends by itself are spent; …`), and
  isn't sent for an hour after its query's search failed, nor at all while three
  searches failed in the last hour (`Not searched: LaCuerda's search for “…”
  failed less than an hour ago (…), so the page won't send it by itself before
  …`); by hand (the page's Ask LaCuerda, or Enter in its search box), it asks.
  `--progress` prints a JSON line per event,
  for caracole serve's request page. It goes with neither `--index` nor
  `--artist` (exit 2).
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
- **`caracole harptabs`** keeps a harmonica tab from harptabs.com for each song
  that has none, newest songs first. It reads harptabs.com's one sitemap into a
  local index when it never has, or last did 30 days ago: its tabs by title
  (the address of a tab names its title alone, `/tab/25/piano-man`) and its
  artists by name. It never uses the site's search or its API. A song is looked
  up only when the sitemap lists a tab of its title and an artist of its
  artist's name; then the pages of the tabs of that title are read, lowest id
  first, eight at most, each for the artist it names, and of those by your
  song's artist the most viewed is kept, as the song's `harmonica-N.txt`, the
  page's tab as it is: hole numbers over the lyrics. A tab of no known artist
  ("by Unknown") is no one's, as a tab by another artist is. A song none of
  whose tabs is by its artist is asked about again after 30 days; a song with an
  error, next run. It prints `harptabs.com: 2 tried, 1 harmonica tab kept, 1 not on
  harptabs.com, 0 errors`, after `Index: 1 sitemap read.` when it read it. A
  song that has a harmonica tab gets no other, and no file is ever replaced.
  With harptabs.com turned off it asks nothing and says so. A cooldown, a block
  or a spent budget exits 0.

  **`caracole harptabs --index`** reads harptabs.com's artist pages into its
  local index instead, for searches, even for an empty library: the sitemap first, when it never was read or last
  was 30 days ago, then each artist page not read in 30 days, your songs'
  artists first, then the others in the sitemap's order. An artist page lists
  the artist's 30 most viewed tabs and says how many they have; the rest come
  from the site's API, which robots.txt closes, so caracole knows those 30. It
  asks at the bulk pace (10–20 s apart) with a budget of its own: `--budget N`
  requests, 100 by default, and goes on where the last one stopped. It prints
  `Index: harptabs.com's sitemap read.`, `harptabs.com: 99 artist pages read;
  99 of 10428 artists read, 412 tabs in the index.` and, with the budget spent,
  `The budget of 100 requests is spent: caracole harptabs --index reads the
  next 10329 artists, about 43 h of requests at this pace.`; or `harptabs.com's
  artist index is up to date: …` when nothing was due. A page that answers 404
  keeps no tab (`1 gone`); one that won't parse, or any other error, leaves what
  the index held of that artist, and is asked for again next time. It holds
  caracole's lock while it runs, as the nightly run does, letting a lookup go
  first in its pauses: a nightly run waits for it, so give it a budget that
  ends before night (2000 requests are about 8 hours). A cooldown, a block or a
  spent budget exits 0; `--budget` goes with `--index` alone (exit 2).

  **`caracole harptabs --artist NAME`** reads one artist's page into the index
  now: NAME is their name, or their page's address (`artist/1178/billy-joel`, as
  the sitemap lists it). It asks at the lookup pace, as `caracole get` does,
  within a lookup's budgets: one request, and none when caracole read the page
  within 30 days. Its last line starts as `caracole lacuerda --artist`'s does:
  `Read: harptabs.com's page of billy joel lists 30 of their 98 tabs, in the
  index now.`, `Not found: harptabs.com's sitemap lists no artist named NAME.`
  (no request), or `Not read: …` for the site turned off, its index still
  empty, a cooldown, a block, a spent budget or an error, all of which exit 0,
  nothing changed. It can't go with `--index` (exit 2). An artist's Read their
  page on the pages `caracole serve` serves runs it.
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
  Guitar Pro and Power Tab files you dropped into `_inbox/` (`.gp3`, `.gp4`,
  `.gp5`, `.gpx`, `.gp`, `.ptb`), wherever you got them, by their names, for
  any song you haven't ignored: one named `Soda Stereo - De Musica Ligera.gp5`,
  or `De Musica Ligera.gp5` when only one song has that title, becomes that
  song's `guitar-N.gp5`, N the lowest number no file of the song holds, so a
  file is never written over (a version number in the name, `(ver 2)`, is
  left out). It files scores too, such as MuseScore's downloads (`.mscz`,
  `.mxl`, `.musicxml`, `.pdf`, `.mid`, `.midi`): one named
  `Oasis - Wonderwall.mscz`, or `Wonderwall.mscz` when only one song has that
  title, becomes that song's `score-N.mscz`, N the lowest number no score of
  that format holds, so the formats of one score share it. A MusicXML file is
  also placed by the title and composer its header gives, when exactly one
  song has both. A score is never `sheet.pdf`, which caracole renders itself.
  A name a site writes in two scripts meets yours by any of its parts, the
  bracketed original included: the file of 周杰伦's 晴天 may be named
  `Jay Chou (周杰倫) - 晴天 Qing Tian Sunny Day (ver 1).gp5`. A file the library
  already has is removed from the inbox, and one it had and lost (deleted on a
  device, say), told by its bytes, is put back in its place; a file it can't
  place stays there, as does one whose place in the song's folder holds another
  file now, and so does a symbolic link, which is never read:
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
  ("Soda Stereo · Key Bm · half step down"): a capo they name for a sheet
  with none of its own, only where its chords are played where the sheet
  writes them (a version in another key or capo plays them elsewhere, and
  leaves it out); a tuning they name ("half step
  down", "Drop D", "Eb standard") or give after a "Tuning:" label ("Tuning:
  DADGAD"), never one they only talk about, and never standard tuning. Then the chord diagrams above
  the song, bold rust chords over the lyrics, and section names in small rust
  capitals (no band). The title is large, the page a clean two columns, and a
  songbook's songs are set the same way: in Adwaita Sans with the packages, the
  title, the chords and the section names bold, a repeat mark italic, a tab in
  Adwaita Mono (see [Fonts in the PDFs](#fonts-in-the-pdfs)). chordpro prints a text of the PDF's own, and `sheet.cho` stays as it
  is, for the viewer: the tab's notes before its first section stay out of the
  PDF (a tab after them stays in), the chord diagrams are the shapes the
  viewer shows first for the chords the sheet gives shapes for (its chord
  legend, "Cadd9 (x32033)", wherever it is), the section names are in
  capitals and the song is in two columns. When the two columns of its first
  page hold the song, they end level: the second starts at the section (in a
  song without headings, the stanza) that evens them out best, never inside
  one, a tab or a wrapped line, and only where each column keeps some room to
  spare (a numbered song's legend counts as part of it). A song one column holds
  stays in one; a song with no such place (one section longer than a column,
  say), a longer one than two hold, or one that sets its own columns flows
  from column to column and page to page as chordpro sets it, and its second
  column can then hold a line or two alone. So can, now and then, a Latin song
  in a songbook printed in a Chinese font, whose letters are wider than the
  estimate's. A song in another key, capo or
  mode, by its `[version]` or its `[transpose]`, has every chord written as
  its viewer shows it there (Bb, not chordpro's A#), each with the shape the
  viewer shows (or the one the version chose) as its diagram: chordpro moves
  nothing. A chord legend's lines stay as the tab writes them ("Am x02210"
  names that shape), as in the viewer. A songbook's songs are written the same
  way, each where the songbook plays it (see [Songbooks](#songbooks)).
  `sheet.html` is the sheet viewer, for the phone (see
  [The sheet viewer](#the-sheet-viewer)). A PDF is made again only when its
  sheet, its version, the fonts, caracole's PDF style or the text the
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
  song's own `t` (where its `[version]` puts the sheet, else its
  `[transpose]`), which the viewer leaves out of its address.
  `inst=` names the instrument the viewer was on (`ukulele`, `ukulele-low-g`,
  `baritone`, `piano`, `harmonica`, `flute`, `recorder`; `guitar` too): the
  PDF is made for it, and named after it, `sheet (G Major, capo 2,
  ukulele).pdf`, `sheet (A Major, piano).pdf`. A ukulele's has four-string
  diagrams of the viewer's shapes (low G and baritone alike); the piano's, a
  keyboard of three octaves for each chord, its keys in the chords' colour:
  the viewer's first position, the left hand's bass and the right hand's
  chord; the harmonica's, no diagram but, before the song, the harps for it
  ("Harmonica: C harp (2nd position) · G harp (1st)") and each chord's holes
  on the first (`G7: draw 2–5`, `F: not on this harp`); a flute's or a
  recorder's, the key's scale (`G major scale: G A B C D E F# G`). Under the
  title the instrument is named (`The Placeholders · Piano · Key A`), and one
  with no capo (the piano, the harmonica, the winds) plays the chords as they
  sound, the capo folded in: `Key A`, never `G shapes · capo 2`. Without
  `inst=`, the song's own version's instrument when the words name nothing of
  the version, else the guitar. An export with the same name replaces the last one. Exports are
  caracole's files: every render makes them again when the sheet, the style or
  the PDF's text changes (and says nothing when they are up to date), and
  `caracole remove` deletes them. One a new sheet names otherwise (a sheet in
  another key or capo took the old one's place, an auto sheet's key was heard
  again) is made under its new name, and the PDF under the old one goes, while
  it is still as caracole wrote it. The library page lists them under the
  song's line's chevron, as its PDF exports, each by its version (`G Dorian, capo
  0`), before its other files. An
  export is made from the song's human sheet, else its auto sheet; it needs one
  of them to be kept, and exits 1 with the reason when it can't be made.

  **`--song "ARTIST - TITLE" --version QUERY --mine`** makes that version
  the song's own instead: it writes it under `[version]` in overrides.toml
  (once it holds caracole's lock, keeping your comments) as the key it plays
  in (as the sheet reads its chords: `Gm` for an A minor sheet played two
  down), the mode you chose, if you chose one, and its capo, with the chords
  it plays instead and the shapes it chose by their names
  (`key=Gm&mode=dorian&capo=0&at=Gm.x-x-5-7-8-6`), and the instrument the
  viewer was on (`&inst=piano`, with the capo the guitar plays at), says so
  (`Your version of Soda Stereo - De Música Ligera: G Dorian, capo 0`), then
  renders the song as `--song` does: its `sheet.pdf` is in that version, its
  viewer starts there (on its instrument), its exports and its songbooks
  follow. `sheet.pdf` stays the guitar's: another instrument's PDF is an
  export's, or a songbook's. The key is a
  key, not a move: a sheet in another key or with another capo that takes
  the song's place later plays in G dorian with no capo too, and one that
  reads the same chords in the relative key (C major for A minor's), or
  names the parallel key for them (A for A minor's chords), plays the
  chords the version played (`[version]` in
  [overrides.toml](#overridestoml-your-decisions)). A sheet with no key has
  no key to keep: the version is written as the viewer's address writes it,
  a move from the sheet, its `t=` named even at 0 (`t=0&capo=1`). A version
  that plays the sheet where the song plays without one (its `[transpose]`,
  else as written) takes the song's `[version]` out instead, and the song
  follows its sheet again. `--mine` needs `--version` (exit 2).
  In the sheet viewer, ⋯ has **Export PDF**, with the version in words at its
  right ("D Dorian, capo 2"; from the folder, the row unfolds this command,
  with Copy), but for the auto sheet's viewer kept beside a human sheet: its chords are other ones, and an
  export would be the human sheet's (caracole serve refuses one from it, 409).
  caracole serve refuses one from a kept version's page (`version-<tab>.html`)
  too, for the same reason: make that version the one first, then export it
  from the song's own viewer.
  On `caracole serve` it opens `/export` in the same tab: the version in words ("G Dorian,
  capo 0"), Make PDF (this command, queued like any request), the job's line,
  then Open the PDF and Back to the sheet, which keeps the viewer's address.
  Below Make PDF, **Make this my version** queues the same command with
  `--mine` (caracole serve writes no overrides.toml itself); once it is done
  the page says so and links the song's own PDF. On the version the song
  plays in already (its `[version]`, else its `[transpose]`, else as written),
  the page says "It is your version" instead; for a `[version]` caracole
  wrote as a move from the sheet (`t=`, before it kept a key), it adds that a
  sheet in another key in its place would move it, and offers **Keep it in
  this key**, the same command, which writes it by its key.
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
  down and sends one ntfy message, as any block does, and the others are still
  asked. A block or an error exits 0.
- **`caracole review`** settles uncertain matches, one prompt per song (see
  [Review](#review)).
- **`caracole search [QUERY]... [--limit N] [--add N] [--key KEY] [--artist NAME]
  [--title TITLE] [--progression NUMERALS]`** searches your library and the offline UG index, by an
  artist, a title or both; `--key` finds your songs in one key, `--progression` those that play a
  progression (see [caracole search](#caracole-search)).
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
`harptabs`, `musescore` and `youtube` when they did something or were blocked, so that
Provider health shows the cooldown (`youtube` also when it let go of audio no
song needs any more, with nothing to download).
A page caracole can't write ends the command with status 1 and
`can't write …/_todo.md: Permission denied`, its own work saved first; for
`add`, `search --add` and `sync` that is only a warning.

**One caracole at a time.** The commands that ask the sites for pages or write
the library hold caracole's lock, `caracole.lock` in the state folder, while they
work, so no two budgets are ever spent side by side: `run` from start to end,
`get`, `index build` and `refresh`, `fetch`, `lyrics`, `lacuerda`, `gtptabs`,
`harptabs`, `musescore`, `youtube`, `render`, `match`, `scan`, `todo`, `sync`, `add`,
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
waits a whole pause again before its next request, to any site the lookup
asked: its next request to Ultimate Guitar waits UG's 10–20 seconds after the
lookup's last one, even when the lookup went first in a pause of LRCLIB's. The
run then reads each song again before its turn, and overrides.toml too, in that
step and in every step after it, so a song the lookup fetched isn't fetched
twice, and a tab it pinned, or a LaCuerda sheet it picked, is the one kept:
another LaCuerda sheet doesn't take its place, even when the run was asking
LaCuerda about that very song as the lookup went first (what LaCuerda answered
then waits in the cache, and the song stays as the lookup left it). Work that
sends no request lets a lookup go first between two songs:
`caracole autochords` (a song takes minutes, and the unit runs for hours), and
the PDF pass of the run and of `caracole render`, which reads each song and
overrides.toml again after it, and makes the songbooks and the pages from
overrides.toml as the lookup left it. `caracole fetch`, `lyrics`, `lacuerda`,
`gtptabs`, `harptabs`, `musescore`, `youtube` and `icons` let a lookup go first in their
pauses as the run does, and make the pages they write at their end from
overrides.toml as the lookup left it too. The waiting lookup announces itself with a file
in `caracole.lock.waiting/` in the state folder, which it touches every second
while it waits; one left by a lookup that was killed while it waited is no
longer waited for after five seconds. The run lets lookups alone go first: a
command that isn't one (`caracole fetch`, `remove`, `add`, …) still waits for
the whole run, even when it started before the lookup came, and the run holds
`caracole.lock.handoff` in the state folder while a lookup has the lock.
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
  yt-dlp get caracole's settings: it runs without any `CARACOLE_*` variable,
  with only the paths, language, proxy and certificate settings it needs.
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
  `# in place of the artist's line under [alias]`. An artist's line is given
  once on the page, since the same key twice under `[alias]` makes the file
  unreadable: a later song of theirs gets its `[match]` line alone, and says
  which item above has the artist's line (for another UG name, the line that
  holds both, to put in its place; for an item whose candidates give the
  artist several, of which one at most goes in, what to do with each), and
  its own line, should none of those go in. After the candidates
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
  `[artist_url]` table; once it has one, even with no entry left in it, the
  page gives the lines alone, to add under the table. The artist page lists all of the artist's tabs, bare ids
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
  version you want, drop the one you want into `_inbox/`, named as the song
  is (`Artist - Title.gp5`), and caracole files it beside this one.
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
- **Guitar parts not found.** Songs UG has no text tab for, and with no
  Guitar Pro or Power Tab file kept (from `_inbox/` or gtptabs.com), with
  Songsterr and YouTube links.
- **Inbox: files caracole couldn't place.** Rename such a file, a Guitar Pro
  file or a score, "Artist - Title.ext", the song as caracole names it, and
  the next run files it. Don't move it into the song's
  folder yourself: caracole wouldn't know it is there. A symbolic link in
  `_inbox/` is listed too: caracole files only regular files. A name that
  isn't UTF-8 (an old zip's, in Latin-1 or CP437) shows each byte it can't read
  as `\xNN`, and says so. If `_inbox` is a
  link itself, the page lists nothing from it, and says to make it a folder;
  until then the scan files nothing.
- **Missing lyrics.** LRCLIB has none for these yet; caracole asks again after
  30 days.
- **PDFs.** The last render of the library (the nightly run's, or `caracole
  render`'s): how many PDFs were made or failed, a font problem if there is
  one, with the sheets it keeps from a PDF, and the sheets that failed. A
  lookup (`caracole get`) and `caracole render --song` (the last step of a
  pick in `caracole serve`) render their own song alone and leave that record
  as it was, but for their song: they take it off the sheets that failed or
  wait for a font, or put it back on.
- **Sources.** How many songs wanted.txt has, with the lines it couldn't
  read; for a wanted.txt it couldn't read at all, the error, as
  `wanted.txt: error at <time>: …`; before it exists, how to create it.
- **Provider health.** For Ultimate Guitar, LRCLIB, LaCuerda, gtptabs.com,
  MuseScore, harptabs.com and YouTube: OK, errors (nothing has worked since the last error),
  cooling down until when, or off (`[providers.gtptabs] enabled = false`, and
  the same for `musescore`, `harptabs` and `youtube`; for YouTube also `off:` and why, as in
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
tabs, the search box, then the toolbar: **Filter**, **Sort** and, set apart
after a divider, **Select** (see below), at the right, one row on a phone too;
before them, the filters on, each a tag ("Wanted ×", "Harmonica ×", "A minor
×", "by Queen ×") that lets it go, then **Clear**, which lets them all go, never
the search (on a phone the tags go under the buttons).
The search box stays at the top as the page scrolls under it, with an edge to
show it.

It shows your songs as dense lines, grouped by artist: each artist's name over
their songs, artists A to Z ("The Beatles" under B, Chinese names by their
pinyin), with how many of their songs you have ("Soda Stereo · you have 2",
all of them, whatever the search or a filter leaves out), and their songs A to
Z under it. A line is a song, one line each on a laptop, 24 px tall with a
mouse (its buttons no smaller than a pointer needs): read down under the
search box, a laptop's screen holds twenty-odd lines with their artists'
names. On a phone a found song is one line too, its title, its key and its
button, and a song that needs something says so under its title. A line has the
song's title, which opens its sheet (the sheet viewer, see [The sheet
viewer](#the-sheet-viewer), else the PDF, else the text); its status when it
needs something, one word: Wanted, Needs review when caracole isn't sure of the
match, Not found when the offline index has no such song, or Ignored (a found
song, nearly every one, says nothing); what it holds, a small icon each, named
by its tooltip and for a screen reader: its chord sheet ("Auto sheet", in its
own colour, for one the audio model wrote; "Ukulele chords", a ukulele, for
Ultimate Guitar's Ukulele Chords), a Guitar Pro file (else a text tab, "Guitar tab"), a
harmonica tab, its lyrics and a score you filed (a phone leaves them out); its
key, in a small box ("Am"; a screen reader hears "Key A minor (from the tab)",
see [The song's key](#the-songs-key)); its one button, Open (Open PDF, Open
text), or, on the page `caracole serve` serves, Fetch now for a wanted song
(Pick the match for one that needs review first, and Removing… while caracole
removes it); and a chevron, which unfolds the song in place, turned while it is
open. An auto sheet says so by its icon, by its button's tooltip, "Auto sheet
PDF", and to a screen reader by the button's name, "Open PDF of Creep by
Radiohead, an auto sheet". Where each file came from, each site's own icon
says beside the file under the chevron (the lyrics LRCLIB's, a Guitar Pro file
gtptabs.com's: see [Where each file came from](#where-each-file-came-from)).

Its chevron opens the song in place, as a card over the list, which the
chevron closes again. At its top, its key in words and where it came from ("Key
A minor (from the tab)", "Key C major (estimated from the chords)", "(from the
audio)"), its transposition, its lyrics' state and when it was added. Then what
needs you: a review's candidates (below); where it stands on the YouTube route,
when caracole takes the audio of songs with no human sheet from YouTube ("No
human sheet yet: caracole takes the audio from YouTube next", "Audio from
YouTube: auto-chords works out the chords next", "Auto sheet from YouTube
audio"), with a link to the video once there is one, instead of offering to buy
it; and, served, Look in the index.

Then what you play from it, a tile each, in this order: its **Chord sheet**
(the accent's; **Auto sheet** in its own colour when that is its only sheet,
**Ukulele chords** for Ultimate Guitar's Ukulele Chords), its **Guitar Pro**
file (**Guitar tab** when it has a text tab and no Guitar Pro file), its
**Harmonica tab**, its **Lyrics** and a **Score** you filed. A tile's body opens
what it holds: the sheet's viewer (else its PDF, else its text); the first
Guitar Pro file, in the browser when `caracole serve` shows it there (see
[caracole serve](#caracole-serve)), else a download; the first harmonica tab,
the lyrics, the first score. Under it, a word of which it is (`Ver 3 · 4.86★ ·
in use`, `LaCuerda`, `from the recording`); its versions, a chip a source with
how many (`Versions [UG] 13 [LaCuerda] 2`, `Files [gtptabs] 1 [inbox] 1`), or,
one source with one version, `From` it; and its formats, downloads: the sheet's
PDF, Text and ChordPro, then its PDF exports, each by its version (`PDF · G
Dorian, capo 0`: see `caracole render --version` and Export PDF of this
version); a Guitar Pro file's, and the text tab; the lyrics' Text and Timed
(.lrc); each score's format. A tile with more than one version is drawn as a
small stack. A Guitar Pro or Power Tab file, and a score but its PDF, downloads
under its song's name (`Eagles - Hotel California (2).ptb`).

A chip opens that source's versions in a drawer under the row of tiles that
holds its tile (on a phone, under the tile); another chip, the chip again, its
✕ or Escape closes it, and opening one asks nothing of anyone. **Ultimate
Guitar**'s: how many versions the site has and how many caracole keeps (`13
versions on the site · 3 kept in your library`), then each kept version in rank
order, with UG's version number, its rating and votes, how much of the lyrics
it has (`Every line of the lyrics`, `80% of the lyrics`, in green when caracole
counts it whole), the tabber's note, and caracole's pick or your choice: **In
use** on the one the title opens, **Open** on each, its own viewer page,
`version-<tab>.html` (served by caracole serve as a sheet viewer is, while it
holds what caracole wrote), or its text, `version-<tab>.txt`, until render has
written the page; a version UG no longer has says so. The versions caracole
hasn't kept are counted, not listed (`10 more on Ultimate Guitar, not kept`).
On the page `caracole serve` serves, each version but the one has **Use this
one**, which makes it the sheet, as `caracole versions --choose` does (a
`[pin]`); while a `[pin]` chooses the sheet, **Back to caracole's pick**, as
`--clear` does; and the versions not kept have **Fetch them**, which keeps them
beside the sheet as `caracole versions --keep-more` does, within a lookup's
budget (**Fetch 6 more** when more are left than one lookup may keep: press it
again for the next). Each is a request of the song's, which its line shows as a
lookup's, and once it is over the card counts again. From the folder, the drawer
gives the command that keeps them, `caracole versions --keep-more 'Eagles -
Hotel California'`. **LaCuerda**'s: the sheets caracole met there, the most of
the lyrics first, each with its page (↗), In use on the one that is the sheet
and, served, Use this one on the others, which looks the song up keeping that
sheet, as Use LaCuerda's sheet does; while your choice on Ultimate Guitar is in
use, it says so, with Back to caracole's pick, as a `[pin]` outranks a LaCuerda
pick. The **auto sheet** beside a human one: its viewer, its PDF, text and
ChordPro. A Guitar Pro file's, a harmonica tab's or a score's source: a row a
file, Open where the page shows it, and Download. A harmonica tab with its page
beside it opens that page, from its tile and its row, its text a download.

Then its progressions, as it plays them ("vi–IV–I–V"), each a chip that shows
your songs with that progression (below); where else to find it, links that
leave caracole (↗): its MuseScore pages, each a possible match, as on the
to-do page, and for a song without a sheet, its search and buy links. At its
foot, served, **Fetch again** (below) and **Use LaCuerda's sheet**; **Add to a
songbook…** (see Songbooks, below), for a song the page had when it was loaded
(one that Get it or a request brought since has it once the page is loaded
again); and at the far end, info.json, a quiet download, and, served, **Remove**,
in red. When Fetch now has the line's button, the sheet's tile opens it all the
same, as its title does. A line drawn again (a request over) keeps its card
open, its drawer closed.

An artist's name, over their songs and marked with a funnel, shows only that
artist's songs ("Queen" leaves out ABBA's "Dancing Queen"), until you take its
tag ("by Queen ×") off. On the page `caracole serve` serves, the name searches for the artist
instead (see below), and the funnel is a button of its own beside it ("Only
Queen's songs"), which shows their songs alone as the name does from the
folder. Sorted by title, or by when the songs were added, the lines stand
alone, without the artists' names over them, each with its own (which does the
same). `#by=` in the address, an artist's name as a sheet viewer's artist line
links to it (`index.html#by=Soda%20Stereo`), does what pressing their name does:
from the folder, their songs alone (else the songs the name finds); served, the
search for them. A request's line (see [caracole serve](#caracole-serve)) shows under
the song's, a line of its own. The search, the filters, the sort and the
letters all work on the lines, and the address remembers
them, as it does the rest: a bookmark opens the page as you left it. (An
address from before, with `#view=rows` in it, opens the lines.)

**Songs by progression.** caracole reads each sheet's progressions as it
renders it: each section's chords as Roman numerals in the key the viewer
reads the sheet in, one cycle, with its name when it has one ("the pop
progression", "the Andalusian cadence"), and the named progressions it
plays within it (a verse ii–I–V–vi–IV–♭VII–I–V–vi–IV plays the pop
progression twice). A progression's button under a song's
chevron, or `#prog=` in the address (`index.html#prog=I%20V%20vi%20IV`, as a
sheet viewer's Harmony panel links to it; written by hand, `#prog=vi–IV–I–V` is
the same progression), shows only your songs that play it,
in any key and starting on any of its chords, under a line that says which,
with Show all: "Songs with I–V–vi–IV, the pop progression · Show all". A
progression with a name finds every reading of it: the pop progression is
I–V–vi–IV in C major and i–♭VI–♭III–♭VII in A minor, so a song whose key
caracole read as A minor rather than C major is there too, and so is a song
that plays it within a longer section. A section held on
one chord is no progression. A library rendered by an older caracole has its
progressions after its next render (the nightly run's).

A song that needs review lists its candidates under its chevron, under "3
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
as "am", also finds the names with "am" in them ("I Am the Walrus").
**Filter** opens the filters, as a panel under it on a computer (the list
behind it filters as you tap, with nothing to apply; a click outside it,
Escape or Filter again closes it) and as a sheet from the bottom of a phone's
screen (over the page dimmed, it ends in **Show 4 songs**, which closes it,
as Escape does). Its **Status** shows all songs, or only those found, wanted
or needing review (Review only while a song needs it), each with how many
songs it would show, the arrow keys moving between them; **Has something
for** shows the songs that have something for any of the instruments you
tap: a Chord sheet (a human or an auto sheet), a Guitar tab (a Guitar Pro
file or a text tab), Ukulele (Ultimate Guitar's Ukulele Chords), Harmonica
(a harmonica tab) or a Score you filed, each with how many songs have it
(one no song has, greyed, can't be tapped), and while one is on, each line's
icon of it is in the accent (the group shows once a song has something but a
chord sheet; the search's rows of the sites stay, whatever they are for); its
**Key**, there once a song has a key, is Any, Major or Minor, then the twelve
tonics in circle-of-fifths order (C G D A E B F♯ D♭ A♭ E♭ B♭ F, each named
as your songs spell the key: C♯ for a song in C# minor), a tonic no song is on
in the mode chosen dashed: a mode alone shows the songs in it, a tonic alone
the songs on it in either mode, and both one key, in whichever spelling ("F#
minor" and "Gb minor" alike); the tonic chosen, tapped again, goes. The
address keeps an exact key as before (`#key=A%20minor`), a mode alone as
`#mode=minor` and a tonic alone as `#tonic=E`.
**Clear all** lets them all go, and the panel says how many songs show
("4 songs"). Filter says how many of its filters are on (Filter 1), in the
accent. When the filters leave no song, the list says which ("No wanted songs
of Eagles with a harmonica tab in B minor match “hotel”."), with Show all
(Show all 1 match), which lets them all go. **Sort** sorts by artist, by title or by when songs were added.
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
it, and the names after `--` when one starts with "-" (the artist -M-), so that
caracole takes none for an option. `caracole serve` serves the same page, where typing searches what the
sites have too, under the same artist headers, with Get it, and a form to
request a song by name (see below).

On a touch screen every button, fold, chip, menu, letter, artist's name and funnel is
at least 44 pixels each way, for a thumb, and so are each line's button and
chevron (its title, beside them, is as tall): a phone shows about eleven songs to a
screen. With a mouse they keep their compact sizes. Fields, menus and the
Select boxes have an edge you can see against the page, in light and dark mode
(3:1 at least, as WCAG 1.4.11 asks), while the boxes the songs are in keep
their soft border, and so does the search box. The pages `caracole serve`
writes itself (Requests, Look up and its search box, a song's pick) do the
same.

**Select**, at the toolbar's end, puts a
box at the start of each song's line: tick songs in the order they go in the
songbook (each box shows its place, and a screen reader says it: "Pick Creep by
Radiohead, 2nd"). A tap anywhere on a line ticks it, or unticks it: while you
select, each line's button and chevron are put away, a request's line still says
how it goes but without its links (Details), and a tap on its title opens
nothing, so a tick never opens a file by mistake. A line's **Add to a
songbook…**, under its chevron, does the same with that song ticked, the bar's menu
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
in a name (and the names after `--` when one starts with "-": `caracole
songbook make -- 'Camp' '-M- - Je dis aime'`).
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
chip: "G Dorian" for a song with a setting of its own there, its own
version's key ("A Minor") for one without, or why it has no sheet ("No
sheet yet", "Not in the library"). A capo is named only when the song is
played with one ("E Minor, capo 2"), never as "capo 0". A song caracole
keeps a Guitar Pro file for has a small guitar after its title, so a set list tells
you which songs you can play along to as tabs too: drawn solid, a Guitar Pro or
Power Tab file the library keeps (filed from `_inbox/` or downloaded from
gtptabs.com), which on `caracole serve` opens its Guitar Pro page (see [Guitar
Pro files in the browser](#caracole-serve)), and otherwise (a Power Tab file, a
server without alphaTab, the file on disk) downloads the file under the song's
name ("Radiohead - Creep.gp5"). A song without one has none. The guitar is the
tab's alone: the songbook's PDF, phone page
and ChordPro file don't change. Its files come first: **PDF**, **Phone
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
screen each grip, chip, button, ×, title, guitar and menu is a thumb's target,
44 pixels at least.

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

- **The artist's name**, under the title, opens the library page on their
  songs, as their name there does: served by `caracole serve`, the search for
  them, your songs of theirs and every index's (Ultimate Guitar, LaCuerda,
  gtptabs.com, harptabs.com…) under their header, which asks no site; from the
  folder, or in caracole's Android app, your songs of theirs alone, with their
  chip on. It is a plain link (`index.html#by=Soda%20Stereo`), which the
  server's sandbox follows too, and the browser's Back returns to the sheet
  where you were. It reads as the line it was, muted,
  underlined under the pointer or the keyboard's focus; on a phone it is a
  thumb's target. A kept version's page and a songbook's songs have it too.

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
  1200 px the rail of necks (below) takes 345 px on the left, and the song is
  measured beside it: two columns then need a wider window (at 1280 px a song
  reads in one, at 1600 px two fit as they did at 1280 px without it). Hidden,
  the rail gives the song the whole width back. At 1200 px, with both the rail
  and the settings open, the song still has about 480 px, and wraps rather
  than scroll sideways.
- **Tap a chord** for its fingerings: up to four shapes from chords-db, after
  any the sheet gives, with the fingers, the barre and the fret they start on
  (swipe, or ‹ ›, for the next). Every place the chord is played lights up
  while its card is open. Under the shapes, the card lists the chord's notes,
  each with its interval (C7: C R, E 3, G 5, Bb ♭7), and the scale that fits
  over it for a solo, with its notes: the key's own mode on the chord's root
  for a chord in the key (Dm7 in C: D Dorian), the mode of the key a borrowed
  chord comes from, Mixolydian for a secondary dominant, and by its quality
  otherwise (Locrian for m7♭5); both follow the transposition, the capo and the
  mode, and a chord you try instead in the card. **Circle & keyboard**, at the
  card's head, closes it and opens the chord's tooltip (its notes on a circle
  or a keyboard, below), by the chord: its numeral where the sheet shows one,
  else its name, so the chords' names alone reach it too. It shows the chord
  played there now (one you chose instead, else the sheet's), and only where
  the tooltip has its notes to draw (the key known, the chord one caracole
  can read). The card leaves the song in
  view: on a phone it sits at the foot, above the bar, about 270 px tall, and
  the song scrolls
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
  chords-db's shapes, and so does a capo moved off the sheet's fret. The
  legend's own lines stay as written in any key, capo or mode: "Am x02210"
  names that shape, and Am stays Am there.
- **The key on the neck**: the rail's first neck (below) shows the key's
  scale across the frets, the tonic larger in rust, and Scale or the key's
  pentatonic box (Major pentatonic for a major key, Minor pentatonic for a
  minor one). It follows the key, the mode and the capo, in the key of the
  shapes you play: with a capo, its frets count from the capo, as the chords'
  necks do.
- **Hear it**: a tap on a chord, in the song or in the strip, also strums
  it, and so does a tap on the shape on its card (or Enter on it): the shape
  the card shows, with the capo where it is, low string to high, in standard
  tuning, or on the instrument chosen (below): a ukulele's strings from the
  4th to the 1st, shorter and softer, in its own tuning; a piano's notes
  struck together, the bass with them; a harmonica's holes for the chord
  blown or drawn together, on the harp chosen; a flute's or a recorder's
  notes of the chord one after another. The sound is made in the browser (a
  plucked string, a piano's string, a reed or a flute's breath, synthesized:
  no recording, nothing loaded), so it works from the synced folder and from `caracole serve` alike. Nothing sounds until you tap, one sound plays at a
  time, and the page falls silent when you switch away from it; the next tap
  plays again. The strum's loudness, four speakers beside the instrument in the
  settings, sets the volume: Off (crossed out), Soft, Medium (the default) or
  Loud (one, two and three waves). With it off, a tap opens the card alone. A
  phone set to silent may keep it silent.
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
  **Showing and hiding it**: the button at the rail's top (a sidebar, "Hide
  chord necks", which stays at the top as the rail scrolls) hides it, and the
  song takes the whole width; the same sidebar, first in the bar, hides it or
  brings it back (pressed while it shows), and so does the **Chord necks**
  switch in the settings: the three always agree. The choice is the
  screen's, not a song's: the browser keeps it once for every sheet and
  songbook, and the address keeps `necks=0` too, for a page served by
  `caracole serve`, where the browser keeps nothing: ‹ and › to another
  version keep it, and in a songbook so does every step to another song (the
  arrows, a swipe, ‹ ›, the contents). Served, a sheet opened afresh from the
  library page shows the rail again, as it starts at the usual text size: the
  library's links don't carry it. **Reset everything** shows the rail again. Hidden, the
  Harmony panel shows the key's neck, as on a narrower screen. Below 1200 px
  there is no rail and no button for it.
- **The key line** under the title says how the song is played. With a capo,
  it names the key of the shapes you play, the capo and the key the song
  sounds in: "Em shapes · capo 2 · sounds F#m". With none, the key alone:
  "Key Em". Each says where the key came from. On the piano, the harmonica,
  the flute and the recorder, which take no capo, it names the key the song
  sounds in ("Key F#m"), and the chords are named as they sound (F#m, not
  Em): the guitar's capo comes back with the guitar. On the harmonica a
  second line names the harps for the song, each in its position: "Harmonica:
  G harp (1st position) · C harp (2nd)" (below).
- **Instrument**, a menu in the settings: Guitar (the default), Ukulele (G C E A, the
  G string high), Ukulele, low G, Baritone ukulele (D G B E), Piano,
  Harmonica, Flute and Recorder. It
  changes how every chord is drawn and heard, never the song: the chord names
  stay, each drawn its own way. A ukulele's chords are four-string boxes, up to
  four shapes each, from chords-db's ukulele data (MIT, as the guitar's);
  low G plays the same shapes, the baritone the same shapes a fourth lower (a
  ukulele's C shape is its G). A chord it has no shape for shows the closest
  (C5 as C, G9 as G7), saying so, and a slash chord its plain chord ("Shown
  without its bass, E"). A ukulele keeps the capo, and offers **Easy keys**
  above it, the keys whose chords sit well under the fingers (on a ukulele
  C, F, G, Bb, Am and Dm; on the baritone G, C, D, F, Em and Am), nearest the
  key you play first: tap one to move the song there, as Transpose does (the
  guitar's capo suggestions are the guitar's alone). The piano draws each
  chord on a keyboard, its notes lit and its bass marked: root position, then
  the first and second inversions (‹ ›), the right hand around middle C and
  the bass, the root or a slash chord's, for the left hand below it. The rail
  of necks (below) draws a ukulele's four strings, and the piano has none.
  The **Harmonica** is a 10-hole diatonic harp in Richter tuning. The key line
  names the harps that play the song, two or three, best first, each with its
  position, numbered round the circle of fifths (1st: the harp in the song's
  key; 2nd, "cross harp": a harp a fourth above the song; 3rd, "slant harp": a
  whole tone below; and the mode the harp plays in from the 3rd on: "E harp
  (3rd position, dorian)"). A song in a major key lists the 1st position, then
  the 2nd; a song in another mode, the positions that suit it (the 3rd, 4th
  and 5th for a minor one), those that play the most of its chords first. Its
  row in the settings, under the menu, **Harp**, picks one of them, and lists each chord on it:
  the holes that play it on one breath ("draw 2–5"), the chord without its
  seventh or ninth where the harp has only that ("blow 1–3 (as C)"), the minor
  chord a harp plays for a major one it lacks ("draw 4–6 (as Dm, minor
  substitute)"), or "not on this harp"; and the song's harmonica tabs from
  harptabs.com, a link each to its page (see [The harmonica tab
  page](#the-harmonica-tab-page)) with its text beside it, and the key its
  harptabs.com page named, `key C (harptabs.com)`: the song's key on some tabs,
  the harp's on others, so never a harp. A chord's card and the strip draw the harp's ten holes, those it
  plays lit. The **Flute**
  (concert pitch) and the **Recorder** (soprano, sounding an octave above the
  notes it reads) show each chord's notes, each with its fingering: on the
  card, and in their row with the key's scale. That row switches the note
  names between A–G and Do–Si, and the recorder's fingering between baroque
  and German (they differ on F, F# and G#); the browser keeps both for every
  page. A flute's fingering shows the thumb's two keys at the top left, the
  left hand's three fingers and G# key, then the right hand's, with the trill
  keys, the E♭ key and the foot's C# and C; a recorder's, the thumb (half
  filled: pinched), the seven holes (the last two double) and the bell. None
  of the three takes a capo, and the harps follow Transpose.
  Like the rail of necks, the choice is the player's, not a song's: the
  browser keeps it once for every sheet and songbook, and the address keeps
  `inst=ukulele` (`ukulele-low-g`, `baritone`, `piano`, `harmonica`, `flute`,
  `recorder`) while it is another
  than the guitar, for a page served by `caracole serve`; ‹ and › to another
  version keep it, and so does every step to another song in a songbook.
  **Reset everything** leaves it as it is. **Export PDF** makes the PDF on
  the instrument shown, and **Make this my version** keeps it, so the song
  opens there (`caracole render --version`'s `inst=`); a songbook may play a
  song on its own (`caracole songbook set --instrument`).
- **The versions** of a song Ultimate Guitar has several of: under the key
  line, the sheet's viewer and each version kept beside it say which of UG's
  chords versions they are, with its rating and votes: "Ver 3 of 13 ·
  4.86★ (408) · the one", the one being the version the title opens. A song
  whose sheet is LaCuerda's says "13 versions on UG · the one: LaCuerda's
  sheet" there. ‹ and › open the version kept before or after this one, in
  rank order, in the same tab, at the same text size and scroll speed (the
  key, the capo and the rest are each sheet's own). Tap the line for the list
  of every version UG has, in rank order: rating, votes, which is the one,
  which are kept, which is this page, and the first lines of the tabber's
  note. It sits where the settings do (at the foot on a phone, a rail beside
  the song from 900 px wide, in their place). A kept version opens from it;
  one gone from UG is listed and opens nothing. Served by `caracole serve`,
  **Keep it** on a version not kept, **Make this the one** on a kept
  version's page, and **Back to caracole's pick** while a `[pin]` of yours
  chooses the sheet (the one `caracole versions --clear` takes out),
  open caracole serve's page that does it. Opened from a file, each shows the
  `caracole versions` command that does it, with Copy, and a version not kept
  links to its page on UG.
- **The bar** at the foot of the page holds what you reach for while
  playing: `− Em +`, a guitar, `Aa`, `▶` and `⋯`, and from 1200 px, first,
  the rail of necks' button (above). − and + move every
  chord, its shapes and the key a semitone at a time, with the key you play
  between them in short: "Em" over "shapes · capo 2" (or "key" with no
  capo), and "· +1" once transposed, or "capo 2 · +1" on a screen too
  narrow for all of it, and "capo 2" over "+1" on the narrowest; a key too
  long for its room ("Ab mixolydian") is a little smaller. A screen reader
  hears the whole line ("Em shapes · capo 2 · sounds F#m · +1"). **The
  guitar** shows the strip of every chord's shape (below), or hides it
  again, as All chord shapes in the settings does: it stays pressed while the strip
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
- **The settings** (⋯), headed by what is set ("D Dorian · capo 2 · Guitar":
  the key of the shapes you play in the mode played, the capo, the instrument;
  "As written" or "Transposed +2" for a song whose key caracole can't tell),
  leave the song in view, so
  you see its chords change as you transpose, move the capo or change the
  mode: on a phone they sit at the foot, above the bar, in at most 45 % of
  the screen, and the song scrolls under them; from 900 px wide they are a
  rail beside the song, which moves over for them. Nothing behind them is
  dimmed or out of reach. A chord's card opened with them covers them on a
  phone, and sits by its chord beside them on a wider screen; Escape closes
  the card first, then the settings, and gives the focus back to what opened
  each. Among them, side by side: **Transpose**, as − and + do, with the semitones counted; ↺ Reset, by it
  while it differs, goes back to the song's
  `[transpose]`, where the viewer starts, like the PDF. A song with a version
  of its own (`[version]`, Make this my version) starts in it, key, capo, mode,
  shapes and swaps (its key on whichever sheet the song has now), whenever its
  address names no other (an address with a
  `t=`, `mode=`, `capo=`, `alt=` or `at=` is that version instead); the address
  then always names its `t=`, and **Reset everything** goes back to it. What
  the browser kept for the page before the song had that version is left
  out. **Capo**, on every
  song, moves the capo a fret at a time, from none to
  the 11th; its ↺ Reset puts it back where the sheet has it. The song sounds the same
  wherever the capo is, and the chords show the shapes to play there: Em shapes
  with capo 2 become F#m shapes with no capo, or Dm shapes with capo 4. The
  capo stays on its fret when you transpose, as on a guitar, so the shapes
  move instead. In an awkward key it also suggests, under them, **Easier shapes**: frets
  where open shapes play it (Bb: capo 1 with A shapes, capo 3 with G shapes); tap one to play them.
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
  the key, such as the G major chord's B in C minor, stays where it is. The
  song's own mode has a thicker edge among the others, and the line over them
  says what the mode played sounds like ("minor, with a brighter sixth").
- **Chord names**, one of three: Chords, + Numerals (each chord's name and its
  numeral) or Numerals (the numeral in its place). A numeral says
  what the chord is in the key, as a Roman numeral counted up the key's scale
  from its tonic: in C major, C F G Am are I IV V vi; in A minor, Am G F E7
  are i ♭VII ♭VI V7 (numerals are written against the tonic's major scale, so
  a degree the key lowers gets a ♭). Upper case is a major chord, lower case a
  minor one; ° diminished, ø half-diminished, + augmented, then the chord's
  extension (V7, Imaj7, IVsus4); a number after a slash is the bass note's
  degree (C/E is I/3, C/D is I/2), a numeral after one the chord of the key a
  secondary chord leads to (D7 going to G in C is V7/V). With both, the
  numeral follows the chord's name, smaller, and the chord stays over its
  syllable; with numerals only it takes the name's place (a chord caracole
  can't read, N.C., stays as written). The mode re-labels them with the mapped
  chords; the key, the capo and the transposition leave them as they are (a I
  is a I in every key). Each is in the colour of its family: home (I, iii, vi;
  i, ♭III, ♭VI in minor) green, moving away (IV, ii) blue, pulling home (V,
  vii°, and a minor key's ♭VII) purple; a chord from outside the key
  (borrowed, as B♭ in C from C minor; a secondary dominant; or plainly
  outside) is underlined with dots. The **Role colours** switch turns the colours off.
  Hover over a numeral with the mouse, or tap it, for its tooltip: the chord,
  its numeral and its role (home, away, pull, or outside the key); its line,
  "vi: the 6th chord of C major, minor (lower case)", "♭VII: built on the
  lowered 7th degree of C major, major (upper case); borrowed from C minor",
  with the key it is read in and where that key came from (an estimated key
  read wrong gives every numeral another meaning); the chord's notes on a
  circle of the twelve notes, C at the top, the key's seven ringed and the
  chord's joined into a shape in its role's colour, the root filled, beside
  the notes listed with their intervals (D7: D root, F# 3, A 5, C ♭7), a note
  from outside the key dashed in red and named under them ("F isn't in G
  major (it has F#)."). **Keyboard ›** under the circle shows the notes as
  tiles over a keyboard instead, stacked up from the root (D7: D, then the F#,
  A and C above it), and **‹ Circle** goes back; ← and → do too while the
  focus is in the tooltip. The view you chose is kept for every sheet and
  songbook (the circle where the browser keeps nothing). ▶ Hear it, beside that
  button, strums the chord as its card plays it (none with the strum Off).
  Escape, a tap elsewhere or the mouse moving away closes it. With numerals
  only, a tap anywhere on the numeral shows its line; with both, a tap on the
  chord's name opens its card, which names the numeral too ("Bb · ♭VII"), and
  whose Circle & keyboard opens this tooltip, with the chords' names alone too.
  A song whose key caracole can't tell offers chords alone (the numerals
  greyed), and says so.
- **Harmony ›** (in the settings, with Guitar Pro tab and Export PDF after a
  rule, near their foot) opens a panel in their place, docked at the
  foot on a phone and a rail on the right from 900 px wide: the key the
  numerals are read in and where it came from, the key's neck on a phone (on
  a laptop it heads the rail of necks), and each section's progression in
  numerals, one cycle of it with the times it is played ("I–V–vi–IV ×4"; "×8,
  one variation" when a pass plays it otherwise, with a chord changed, or one
  added or left out, or, in a cycle of four chords or more, a chord changed
  and one added or left out as well, as Wonderwall's verse does; two chords
  changed are another line), its name when it has a common one, the named
  progressions it plays within it when it is longer ("contains the pop
  progression ×2"), and how the section ends (an authentic cadence, V–I;
  plagal, IV–I; half, on V; deceptive, V–vi). The names, each from Wikipedia
  or Open Music Theory: the pop progression (I–V–vi–IV), the '50s progression
  (I–vi–IV–V), the circle of fifths through every chord of the key
  (I–IV–vii°–iii–vi–ii–V–I, and in a minor key), Pachelbel's Canon, the
  double-plagal progression (♭VII–IV–I), the Creep progression (I–III–IV–iv)
  and the Aeolian shuttle (i–♭VII–♭VI–♭VII), which loop and so are named from
  any of their chords (within a longer section, from another than their
  first only when it plays it twice or more: a vi–IV–V–I played once there
  is a cadence); and the circle of fifths's vi–ii–V–I, the royal road
  (IV–V–iii–vi), ii–V–I, the minor ii–V–i, I–IV–V, the 12-bar blues, the
  8-bar blues (I–V–IV–I–V–I–V; an I–V–IV vamp is none), the Andalusian cadence
  (i–♭VII–♭VI–V), the lament (i–♭VII–♭VI–v), the ragtime progression
  (III7–VI7–II7–V7), the extended plagal progression (♭VI–♭III–♭VII–IV–I, the
  verse of "Hey Joe"), the backdoor progression (iv–♭VII–I), the Aeolian
  cadence (♭VI–♭VII–i), the minor plagal cadence (IV–iv–I), the puff
  progression (I–iii–IV) and the Montgomery-Ward bridge (I–IV–ii–V), from
  their first chord: I–vi–ii–V is no circle of fifths, nor iii–vi–IV–V the
  royal road. A section played round and round is read from where each pass
  starts, so a progression that goes somewhere is named within a pass, never
  across two (I–vi–ii–V ×4 plays no vi–ii–V–I). A chord's
  extensions and bass don't change its name (Cmaj7 and C/E are I), a chord
  with no third (Asus4, A5) is major or minor, and each is named in any key,
  and in a song whose key caracole read as the relative one (the pop
  progression in A minor, i–♭VI–♭III–♭VII), but the blues, the Aeolian
  cadence and the names that are numerals, and the Aeolian shuttle there from
  its first chord alone (vi–V–IV–V in C major: a major key's IV–V–vi–V is no
  shuttle). A section with no chord caracole can read isn't listed; a sheet with
  no headings has one section, "Section 1". Tap a progression to go to its
  section. **▶** plays it (strummed, as a tap on a chord is, above; not with
  the strum Off, or in a browser that can't make sound), a chord a bar at
  the tempo above the list (80 bpm to start; − and + change it as it plays),
  each chord with the shape and the capo the page shows, always in the
  progression's order (a busy page plays the rest later, never two chords at
  once), marking the chord playing. **■** stops it at once, as another ▶, a
  tap on a chord and switching away from the page do: nothing more of it
  sounds. Closing the panel stops every sound, a chord tapped too.
  **Songs with this progression** opens the library
  page with the songs that have it (`index.html#prog=I%20V%20vi%20IV`), and
  **Songs with the pop progression**, under a section that plays it within
  it, those that play that one. With numerals on, a section's heading on the
  sheet names its progression too ("Verse · the pop progression"), or those
  it plays within it ("Chorus · contains the '50s progression").
- Every chord's shape in a strip above the song (the guitar in the bar, or
  All chord shapes in the settings; kept for the page, as the text size is): the
  shapes alone, large enough to read at a glance; tap one for its card,
  with the fingers. Reset everything, alone at the foot of the settings, puts the
  transposition, the mode, the capo and the chords played instead back as
  the viewer starts them, shows the rail of necks again and hides the pinyin.
- **Pinyin**, a switch in the settings of a sheet with Chinese lyrics: on, it puts
  each Chinese character's reading over it, in pinyin with its tone marks
  (zhǐ), smaller and muted, between its chord and it; off, as the viewer starts,
  the readings go again. Each is read in context when the
  page is made (by pypinyin, word by word: 长 is cháng in 长城 and zhǎng in 成长,
  不要 is bú yào), and a sheet in Traditional characters is read as in
  Simplified ones, its 著 as 着 (睡著, shuì zháo) but in a word of its own (顯著,
  xiǎn zhù). Letters, digits and punctuation get none, and a sheet with
  Japanese kana has no Pinyin row: its kanji are no Mandarin. A character and
  its reading make one column, as wide as the wider of the two, so a chord
  stays over its character, and a long line wraps between columns, never
  between a chord, a reading and its character. Transposing, the capo, the
  mode and the chord names change the chords alone. The choice is the
  reader's, not a song's, as the rail of necks' is: the browser keeps it once
  for every sheet and songbook, and the address keeps `py=1` while it is on,
  for a page served by `caracole serve`, where the browser keeps nothing: ‹
  and › to another version keep it, and in a songbook so does every step to
  another song (served, a sheet opened afresh from the library page starts
  without it, as with the rail). Printed from the browser, the page prints
  what it shows, readings and all; the PDFs (the sheet's, an export's, a
  songbook's) have none. Copied, the lyrics leave the readings out. A sheet
  without chords has no settings, so no Pinyin row, but shows the readings
  when another page turned them on.
- **Guitar Pro tab ↗**, in the settings of a song with a Guitar Pro file (not a
  Power Tab one), a row a file: served by caracole serve, it opens the file
  drawn and played "in the browser" (see
  [Guitar Pro files in the browser](#caracole-serve)); from the folder, it is
  a "download", the file itself.
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
speed, the text size, the volume and the shape chosen for each chord among them: a chord
named otherwise when the page opens (an address with another key, mode or
capo), or on another instrument, starts at its first shape. It keeps the transposition, the mode, the
capo, the chord names (`nm=both`, `nm=numerals`), the text size, the scroll speed and the
volume in its address too (`sheet.html#t=2&mode=aeolian&fs=20&speed=8&vol=1`), the rail of necks hidden
(`necks=0`; the browser keeps that once for every page), the pinyin shown (`py=1`, kept so too), the instrument
(`inst=piano`, kept so too), and so the shape chosen for a
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
A key estimated from the chords, or heard in the audio, is the key of the
chords as the sheet writes them: always the shapes', whatever the capo ("Am
shapes · capo 5 · sounds Dm"), in the viewer, the PDFs, the exports and the
songbooks alike. Beside a human sheet, `sheet (auto).html` keeps to the
chords the model heard, which may be in another key than the tab (another
transposition, or a capo).

On Android, a file manager that opens the page through a `content://` address
can break its links to the songs' files. A browser, or an HTML viewer that
opens the file directly, works.

### The harmonica tab page

Each harmonica tab a song keeps, `harmonica-1.txt`, gets a page beside it at
render time, `harmonica-1.html`, in the sheet viewer's look: a file that opens
from the synced folder with no server and loads nothing, recorded as the
viewers are, so `caracole serve` sends it only while it is the page caracole
wrote (in a sandbox, as a viewer), and `caracole remove` deletes it with the
song. The Harmonica row of the sheet viewer's settings and the song's line on
the library page link it, the tab's text beside it.

- **The holes over the words**, each over the syllable it is blown on, as a
  chord sits over its syllable in the viewer: a blow in the sheet's rust
  ("4"), a draw in blue ("−4"), a bend's ′ in purple ("−3′"), holes together
  in their brackets ("(4 5)" a chord, "{−4 −5}" a shake, "[−2 −5]" a split). A
  phone wraps a line between its words, never parting a hole from its
  syllable. Rows played alone, later verses sung to the same tune and the
  tabber's notes come as the tab gives them. caracole reads what harptabs.com's
  tabbers write ("-4", "4D", "-3b", "b-3", "(5)" for a draw in a tab that
  writes no "-", "7,8B"…); a tab in a notation of its tabber's own, or for a
  chromatic harmonica, is its text as written, and the page says so.
- **The harp**, in the header and the bar. A tab's holes are the same on any
  harp, and sound in its key: caracole starts on the harp that plays with the
  record, the one that puts the most of the tab's sung notes on the chords the
  song's sheet plays under the same words ("D harp with the record (4th
  position, aeolian)", and how well it fits); else the harp the tab's words
  name ("I use an A harp": "A harp, as the tab says"); else the key
  harptabs.com's page names, which is the harp's on some tabs and the song's
  on others; else the first harp for the song's key, as the viewer's Harmonica
  row lists them; else a C harp. With a sheet that has a key, each harp says
  its position.
- **The bar**: − and + change the harp a semitone (the holes stay; the sound
  and the notes' names change); ♪, **Notes**, shows each hole's note on that
  harp in its place ("F#6"); **Aa** the text size, and ▶ scrolls by itself,
  as in the viewer.
- **A hole tapped** is heard, a harmonica's reed; **▶ at a line's end** plays
  the line hole by hole, a beat each, lighting each hole as it sounds, and
  stops when pressed again (no rhythm: the tab has none).
- **‹ Chord sheet** goes back to the song's sheet viewer (‹ Library for a song
  with none), and **The tab as text**, at the foot, opens `harmonica-1.txt`.

The page keeps the harp, Notes, the text size and the scroll speed in its
address too (`harmonica-1.html#harp=A&notes=1&fs=20`).

### Where each file came from

Each source has a mark: the site's own icon for Ultimate Guitar, LaCuerda,
LRCLIB (lyrics), gtptabs.com, MuseScore, harptabs.com and YouTube, a ♪ for a sheet the
audio model wrote (auto-chords) from audio you bought, YouTube's for one it
wrote from the audio caracole took from YouTube, and a ↓ for a file you filed
from `_inbox/`.
A site's mark is named for screen readers ("from Ultimate Guitar").

A site's icon is its favicon. The nightly run's icons step asks each site for
it once, from the first night the library has something from that site (a
sheet, a tab, a file, lyrics, MuseScore's pages), with that
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
[--title TITLE] [--progression NUMERALS]` looks in four places, and sends no request: your library, the
offline Ultimate Guitar index, LaCuerda's and harptabs.com's (see below):

    $ caracole search creep
    In your library
      Radiohead - Creep · wanted, no sheet yet · no folder yet

    On Ultimate Guitar (offline index)
      1. [UG] Radiohead - Creep · chords×2 tabs×1 (incl. acoustic)
         https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169
         in your library
      2. [UG] Stone Temple Pilots - Creep · chords×1
         https://tabs.ultimate-guitar.com/tab/stone-temple-pilots/creep-chords-5001
         caracole add "Stone Temple Pilots" "Creep"

    On LaCuerda (offline index)
      nothing matches

    On harptabs.com (offline index)
      [harptabs] radiohead - Creep · 2 tabs, key C
         https://www.harptabs.com/tab/3310/creep
         caracole get --harptabs https://www.harptabs.com/tab/3310/creep "radiohead" "Creep"

- **In your library**: every song, whatever its status, with its key when it
  has one (`Key G major (from the tab)`) and its folder. A song with a sheet
  is tagged with where the sheet came from, as `index.html` marks its files with the
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
  `[UG]`, with its tabs per type (chords, text tabs and ukulele chords, the
  types the index keeps), one of its pages, and the `caracole add` line to paste. The UG artist pages caracole has read (see
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
      1. [UG] Oasis - Dont Look Back In Anger · chords×10 tabs×12
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
Beagles.

A word of an artist's name finds them too: an artist whose name holds every
word of the query as words of its own, among others, is an artist line, after
an artist whose whole name the query is (`caracole search eagles` also lists
Eagles of Death Metal), the most songs first, weighed by how much of the name
the query is (`horse`: An Horse, 18 songs, before Horse the Band, 30, whose
longer name "horse" is less of). One with 50 songs or more and over four times
the songs of an artist whose whole name (or a name near it) the query is comes
before them: `dylan` lists Bob Dylan (638 songs) before Dylan (27), `swift`
Taylor Swift before Swift, `clapton` Eric Clapton before Claptone, while
`prince` keeps Prince before Prince Royce. Accents are folded (`sabina` finds LaCuerda's Joaquín Sabina) and
Chinese is read as pinyin, as whole words (伍佰 finds Wu Bai & China Blue);
never letters inside a word (`horse` finds no Seahorses), a word half typed
(`lynyr`), a word of fewer than three letters, or a word in more than 300
artists' names ("the", "band", "john": on a full index, about seventy such
words), which names only an artist whose whole name it is (`band`: The Band).
Such an artist leads when their songs are most of the songs the query
matches and they have five songs or more (one song of La Naranja Metalica's
leads nothing for `metalica`), or when they have 50 songs or more and one of
them is tabbed more than the first song titled like the query: `caracole
search skynyrd` leads with Lynyrd Skynyrd, and still lists Sam Grow's song
"Skynyrd" after their most tabbed songs; `zeppelin` leads with Led Zeppelin,
`young` with Neil Young, Hollywood Undead's "Young" listed after, while
`imagine` leads with John Lennon's Imagine, Imagine Dragons an artist line
after it. `--artist` still takes a whole name: `--artist lynyrd` names no one.

A query nothing matches well (no artist whose whole name it is, no song whose
whole title it is, here or on another site's index; a title that only begins
with it, The Who's "Eminence Front" for `eminen`, leaves room for Eminem) whose
words are spelled close to an artist's name ends with that artist, and the line
that lists their songs:

    $ caracole search lynrd
    …
    Did you mean Lynyrd Skynyrd?
      Lynyrd Skynyrd · Ultimate Guitar · 139 songs: caracole search --artist "Lynyrd Skynyrd"

Up to three, from Ultimate Guitar's index and LaCuerda's (`metalica` is
Metallica, `beatels` The Beatles, `sabinna` LaCuerda's Joaquín Sabina), the
most songs first, weighed by how much of the name the query is, both indexes'
together, and none with a tenth of the first one's weight (`metalika`:
Metallica, and no Malika Ayane): each word of the query is close to a word of the name (a
word of fewer than four letters must be the name's own), of the same first
letter, so a typo in a name's first letter suggests nothing, and Chinese never
does. An artist a word of the query names may be shown already (`metalica`:
La Naranja Metalica): an artist suggested then has more songs than any shown. The offline index knows no ratings (only the artist pages caracole
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
word of three letters or more is looked up in milliseconds, not by reading
every row: a song or an artist answers in 5–25 ms on a full index, and
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
table (one with no entry left in it counts). The line is keyed by the artist of a song of yours the query finds,
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
`ban-ma-ban-ma`. Only whole words, or a name's start as typed so far ("joaquin
sab"), match well: letters inside a word score below a strong hit (`maná` finds
David Chumaña and Esta mañana weakly), and a word in many artists' names ranks
them by their songs alone. A word of an artist's name at the query's start or
end, the rest a title, names them too, below an artist whose whole name is there
(`bunbury lady blue`: Enrique Bunbury). An artist the query names
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
"bunbury"; never a name that puts another word between the query's, `Silvio
Martinez Rodriguez` for "silvio rodriguez"), else an artist whose whole name
starts or ends the query and whose songs Ultimate Guitar's index reads it as
(`Estopa` for "estopa como camaron", while caracole hasn't read their page;
never `Fito` for "fito paez"), else the query less a title of two words or more
that Ultimate Guitar's index or LaCuerda's knows at its end or start (`mana` for
"mana rayando el sol"), else the query. A query LaCuerda's own index answers well
gets no such line: a song by its title ("como camaron" is Estopa's Como Camarón),
or by an artist it lists or holds the songs of ("estopa como camaron", once their
page is read), and neither does a name its listings give under another spelling
(Ultimate Guitar's `Los Enanitos Verdes` are its Enanitos Verdes) nor a query
Ultimate Guitar's index reads as a title ("creep"):

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
`caracole search` asks LaCuerda nothing: everything listed comes from the local
table, which also holds what LaCuerda's own search answered when it was asked
(`caracole lacuerda --search`, or the search bar of `caracole serve`).

**On harptabs.com** comes last, unnumbered, from its local index: the artists of
its sitemap, and the tabs of their pages caracole has read (`caracole harptabs
--index`, or the nightly run with what its budget leaves; see [caracole
harptabs](#one-step-at-a-time)). An artist the query names, whole or by a word of
their name, is a line with the tabs their page says they have and how many the
index holds, then their most viewed songs (`billy joel · harptabs.com · 98 tabs,
30 in the index. The most viewed:`), or, when caracole never read their page,
the line that reads it (`caracole harptabs --artist artist/1178/billy-joel`, one
request). A song is the tabs of one title by one artist, the title less what it
says in brackets ("Piano Man (C Harmonica)" and "Piano Man (Harp Intro)" are
Piano Man), the most viewed first: its line names how many there are and the
key the first's page names, its page, and the `caracole get --harptabs` line that
looks the song up now keeping that tab (`[harptabs]` in overrides.toml). A tab
whose artist no page read names yet is listed by its title alone, as a possible
match (`same title, maybe another song`). `--artist NAME` lists the songs the
index holds of the artist NAME names, the most viewed first, and `--title TITLE`
its songs of that title. While its artist pages aren't all read, the group ends
with how far it has got (`harptabs.com's artist pages are still being read: 1,204
of 10,428 artists so far; caracole harptabs --index reads the rest.`); turned
off, or before its sitemap is read, it says so. An artist page lists their 30
most viewed tabs: a prolific artist's others are found by their title alone.

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

`--progression NUMERALS` lists your songs that play a progression, in any key
and starting on any of its chords, as caracole read their sheets when it last
rendered them (see Songs by progression, under
[Library/index.html](#libraryindexhtml)): each with its status, the sections that play it,
the key its sheet was read in and its folder, up to `--limit` of them.
NUMERALS are Roman numerals, two chords or more, upper case for major and
lower case for minor, written against the tonic's major scale (`"vi IV I V"`,
`"vi–IV–I–V"`, `"i bVII bVI V"` with b or ♭ for a flat; a chord's quality and
extensions are left aside, so `"Imaj7 vi7 ii7 V7"` is I–vi–ii–V), or the name
of a progression or words of it (`andalusian`, `"the pop progression"`,
`blues`, `"royal road"`; words of fewer than five letters, `"the road"`, name
none unless "progression" or "cadence" is among them, nor do `minor` alone
and a song's title a name is after, `creep`, without "progression").
Numerals are named as a sheet's are: `"III7 VI7 II7 V7"` is the ragtime
progression, and `"iii vi IV V"` no royal road, which starts on its IV.
Written in a minor key's own way, against its natural minor scale (a minor
tonic, i, and no flat), a major III, VI or VII is its ♭III, ♭VI or ♭VII:
`"i VII VI V"` is i–♭VII–♭VI–V, the Andalusian cadence. A progression with a name finds every reading of
it, the pop progression in a major key and in the relative minor, and the
songs that play it within a longer section:

    $ caracole search --progression "vi IV I V"
    Your songs with I–V–vi–IV, the pop progression
      [UG] Another Band - Minor Song · found · untitled section · in A minor · /home/you/Tabs/Another Band/Minor Song
      [UG] Placeholder Band - Synthetic Song · found · Verse, Chorus · in C major · /home/you/Tabs/Placeholder Band/Synthetic Song

The offline indexes have no chords, so they aren't searched; `--progression`
goes with no QUERY, `--key`, `--artist`, `--title` or `--add`, and a text that
is no progression exits with status 2.

### caracole serve

`caracole serve [--address ADDRESS] [--port PORT] [--allow-host NAME]…`
serves the library page over HTTP, at `http://127.0.0.1:8737/` by default,
with what the file on disk can't do. It has no sign-in: anyone who can reach it
can read the library and request songs, so keep it on a network you trust (see
Who can reach it, below).

- **Search as you type.** The library page's search box filters your songs as
  you type, here as on the file, and from the third letter (the second with a
  Chinese character in it) it searches the sites too, a moment after you stop:
  no Enter, and no button. The list and its toolbar make way for the results,
  your songs among them still keeping to the filters and an artist's name you
  pressed, which the results' head says ("Your songs
  here: wanted · by Soda Stereo · in A minor"), with Show all of yours, which
  lets every song of yours show, there and in the list; the sites' songs are
  what the sites have, whatever the filters show. A progression typed as
  numerals ("vi IV I V", "i bVII bVI V") or named ("andalusian", "the pop
  progression", "blues"; words of fewer than five letters, "pop" or "the road",
  are words, as "minor" alone is, and "creep" the song) finds your songs
  that play it too, the first among the results, and the results' head says how
  many play it ("Your songs with I–V–vi–IV, the pop progression: 12"), with
  Show them, the list of those alone (`#prog=`, above). The results come under the
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
  lists the rest in their group, fifty at a time; an artist a word of the query
  names, "skynyrd", has their group too, first when they lead), **LaCuerda** (the artists
  the query names, each with their most popular songs with chords, and "+ N
  more by Estopa on LaCuerda" for the rest the index holds of theirs, then five
  songs: "estopa" finds Estopa; for an artist whose page caracole has never
  read, the group says how many songs LaCuerda lists and offers Read their
  page, which queues `caracole lacuerda --artist` (one request, at the lookup
  pace) and lists them in the group once it has run; and for a query it has no
  artist by, while the nightly run hasn't read the listing of its letter whole,
  the results offer Ask LaCuerda for “estopa” (1 request) under the groups
  (the button's tooltip says the letter its listings don't reach yet), which
  sends LaCuerda's own search for the query while it may go by hand (below), and
  otherwise queues `caracole lacuerda --artist estopa` (a request for
  each spelling of the name tried, usually one), then lists their songs in a
  group of their own, first, or says what LaCuerda answered: `Not found:
  LaCuerda has no artist page for estopa.`, or, for a cooldown, a block, a
  spent hour's budget or an error, `Not read: …`, with a link to the request's
  output. The name is chosen as `caracole search` chooses it: the artist the
  query names on Ultimate Guitar (never one whose name puts another word between
  the query's: Silvio Martinez Rodriguez is no answer for "silvio rodriguez"),
  else the one of theirs whose name starts or ends it, else the query less a
  title of two words or more an index knows at its end or start ("mana" for
  "mana rayando el sol", "héroes del silencio" for "héroes del silencio entre
  dos tierras"), else the query; a title there, "creep", or a song LaCuerda's
  index has, "como camaron", gets no offer, and neither does a name LaCuerda's
  listings already give under another spelling (Ultimate Guitar's Los Enanitos
  Verdes are its Enanitos Verdes, under E). Once a page is read, a search
  finds their songs at once. When LaCuerda alone has the artist the query names, and
  Ultimate Guitar's index nothing that matches well ("andres calamaro": only
  Javier Calamaro's songs; "antonio josé", beside Ultimate Guitar's José
  Antonio Méndez, one song, whose name holds those words), or LaCuerda's artist
  a word names has 50 songs or more and more than any artist the word names on
  Ultimate Guitar ("calamaro": Andrés Calamaro's 325 before Javier Calamaro's 25;
  "paez": Fito Paez), LaCuerda's artist comes first) and **gtptabs.com**
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
  forever" never a page titled Oasis or Forever), each a possible match.
  **harptabs.com**'s artists and songs share the artist groups and lines too,
  with its mark (`Harmonica 98` in an artist's header: the tabs their page says
  they have; `harmonica tab ×4` on a line): a song's harmonica tabs by an artist
  whose page caracole has read, the most viewed first under its "⋯", each a
  Get it that keeps that tab, and the line's own Get it, on a song the other
  sites don't have, keeps the most viewed (a lookup with `--harptabs`, recorded
  under `[harptabs]`). An artist's group ends with "+ 1 more by billy joel on
  harptabs.com" for the rest of the songs the index holds of theirs, or, when
  caracole never read their page, the offer to read it: one request to
  harptabs.com at a lookup's pace (`caracole harptabs --artist`, a request in
  the queue), then their songs in their group. A tab whose artist no page read
  names comes after MuseScore's pages, by its title alone, the same way (none
  while harptabs.com is turned off).
  **Instruments.** A row for one instrument says which, in an outlined badge
  beside its marks: **Ukulele** for an Ultimate Guitar song that has Ukulele
  Chords (its counts say "ukulele chords ×2"), **Harmonica** for a tab of
  harptabs.com, **Score** for a MuseScore page; and a song of yours says what it
  holds for one (a ukulele sheet, a harmonica tab, a score you filed): by its
  icons on the library page's line, as a badge on the lookup page's row. Nothing is left out for
  an instrument: every chord sheet is listed as always, with no badge, as a
  chord sheet is every instrument's. The results follow what you type; a search typed over stops at once, and only
  the newest query's answer is shown, the older one staying until then. Only
  your own typing stops a search: two people searching at the same moment (on
  two phones, or the library page and the lookup page) each wait their turn
  and get their answer (`/api/search`'s `box`, an id each search box makes). The
  line under the box says "Searching the sites…", then how many each site has.
  Under the results, one muted line says where caracole looked when a site
  wasn't searched whole, a chip a site: green searched whole (UG ✓,
  gtptabs.com ✓), amber in part (LaCuerda: up to C, while the nightly run
  still reads its listings: the letters read whole run up to C), red empty or
  blocked (MuseScore blocked, gtptabs.com: empty, before the nightly run read
  its index), grey turned off in caracole.toml (MuseScore: off); each chip's
  tooltip says why in one line ("LaCuerda's index is still being read: 2,957
  artists so far, with #, A–C read whole; the nightly run reads the rest.").

  When a query finds nothing, the results are one card instead. First, when
  its words are spelled close to artists' names (as [caracole
  search](#caracole-search) chooses them), "Did you mean": a line each
  ("Lynyrd Skynyrd · artist · 212 songs on UG"), whose Their songs opens that
  artist's songs in their group, first (fifty of Ultimate Guitar's, with "+ N
  more", or those LaCuerda's index holds, or the offer to read their page),
  with no request. Then the card, headed "Not it?" under them, else "No song or artist
  matches “lynrd”": Request “lynrd” by name, which opens the request form
  below, filled in from the query; Ask LaCuerda (1 request), only while
  LaCuerda's listings don't reach the name's letter (LaCuerda's search first,
  as under results); the chips of where
  caracole looked; and "Why can't caracole find it?", folded: Ultimate
  Guitar's sitemaps name some artists only by a number (Joaquín Sabina, Maná,
  宋冬野), so caracole can't see their tabs, with the `[artist_url]` lines to
  paste into overrides.toml for the query as that artist's name, and, for a
  title, `caracole add ARTIST "lynrd"`. Searching asks no site anything: it reads the indexes
  alone (5–25 ms a query on Ultimate Guitar's, up to about 0.15 s for very
  common words), takes no lock and spends no budget, and so does "+ N more".

  **LaCuerda's own search** is the one request a search may bring. LaCuerda's
  index holds every artist of its listings, but only the songs of the artist
  pages caracole has read; LaCuerda's search finds the rest. Once a query has
  settled, the box unchanged for 1.5 s, the page sends it by itself, one request
  at a lookup's pace (`caracole lacuerda --search`, a request of its own on the
  requests page), when the query has a word of 4 letters or more, LaCuerda's
  index has no song that matches it well (letters inside a word never do:
  "maná" is no "Mañana Clara"), nor the artist it names with their page read
  (all their songs are there already), nor has your library (a song of yours
  by its title or its artist: you are looking through your songs), LaCuerda
  wasn't asked for it in the last 30 days (its words in any order), LaCuerda
  isn't cooling down after a block, and the hour leaves room: at most 20 such
  searches an hour, within the hour's 60 lookup requests to LaCuerda. A line
  under the results says "Searching LaCuerda for “…”…", then what LaCuerda
  answered, and its songs arrive in their artists' groups as the search is
  asked again. Typing on sends nothing. **Enter** sends it at once, without
  waiting for the query to settle, as the button below does (by hand: past the
  hour's 20, within the hour's lookups), and still moves to the first result,
  where the focus stays as LaCuerda's songs arrive; Escape before the query's
  answer is in takes that Enter back. Enter sends nothing when no search would
  go: your library or LaCuerda's index already answers the query, it was asked
  in the last 30 days, the hour's lookups are spent, or LaCuerda cools down.
  Nor does it after a search failed lately: only the button below asks then.
  Once the hour's 20 are spent, the line offers **Ask
  LaCuerda for “…” (1 request)**, which asks by hand, within the hour's lookups;
  when those are spent, or LaCuerda cools down, it says LaCuerda's search waits.
  A search that failed (LaCuerda erred, or answered a page caracole can't read)
  isn't sent by itself again for an hour, and none is while three failed in the
  last hour: the line says so, with the button. A search refused or failed has
  the button under what it said. A query is sent once a page, and once in 30
  days. The Look up page does the same. **One LaCuerda button at a time**:
  where the results offer Ask LaCuerda for a name its listings don't reach yet
  (above), the line has no button of its own, and that one sends the search
  while the search may go by hand (before the query settles too, in its place),
  then, once it is asked, or after it failed lately, reads the name's page.
  **Enter never asks for a song**, however clear the best result (LaCuerda's
  search, above, is the one request it may send): it moves to
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
  its names, as `caracole get` does. Its chevron has what each site has: Ultimate
  Guitar's versions ("Chords 2 of 13", each with an "on UG" link to look at it
  there first), each looked up as `--tab …` (`[pin]`); LaCuerda's page and,
  beside Ultimate Guitar's song, Get it with this sheet, which keeps
  LaCuerda's; gtptabs.com's page. A MuseScore page is a link to open, as
  caracole never fetches from MuseScore. The line then says how it goes, on a
  line of its own ("Sending…", "Fetching from Ultimate Guitar… · 2 of 7
  done"), with the lookup's steps as chips under it, as on a song's line
  (below), and once the sheet is kept the line is the song's own line, yours,
  its sheet its button: the request line and its steps fold away. **A result's name does what its Get it does**: a click on
  "Wonderwall", or Enter or Space on it, looks the song up just as Get it would,
  and while that request is on its way the name, like the button, can't be
  pressed again. A removed song's name does what its Add again does (below). A
  song of yours whose title opens its sheet keeps opening it; and on the file,
  with no caracole serve, no name gets anything. **An artist's name searches
  for them**: a click on "C Tangana", over the results, over your songs in the
  list, or beside a line's title, puts their name in the search box and
  searches it as typing it would (their group first, with their songs, as a
  name typed whole leads), which asks no site, only the offline indexes; the
  focus goes to the box, Escape goes back to your songs, and the browser's Back
  to the list as it was before it (its search, artist, Show, sort and key, as
  its address had them). The funnel beside the name of an artist you have
  songs of shows those alone. A newer answer drawn while it goes (a search typed on)
  keeps the line where it has the song, with its request line; one it hasn't
  moves the request under the box as its line ("Just requested"), its request
  line going on there. A song your library has already, under its own names
  (UG's slugs write AC/DC as "Acdc" and 宋冬野 as "Song Dongye"), is your own
  line; one new to the library since the page loaded says In your library and
  Get it again, and is looked up as your song: no second song, and no line
  added to wanted.txt. A song your library hasn't, from Ultimate Guitar,
  LaCuerda or gtptabs.com, also has **Add for tonight's run** under its chevron: it
  goes into wanted.txt under the site's names, as Request does with Fetch it
  now unticked (a song only LaCuerda has as `caracole add --lacuerda …`, the
  pick recorded: its request says Added: tonight's run gets the sheet you
  picked on LaCuerda, as its line's chevron does, with a link to that sheet's
  page, and it waits for no Ultimate Guitar review of other artists' songs of
  its title), and the nightly run looks it up (not a song under one of UG's
  `misc-…` names, which are no one's: request it by name as you know it).
  Back to your songs, a song new to the library gets a line of its own under
  the box ("Just requested").

  **A song you removed** (`caracole remove`, or Remove on the page) that the
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
  nothing; they stay open as LaCuerda's search ends), or nothing when nothing
  stands out, and sends LaCuerda's search as the library page's Enter does. A query that finds nothing
  shows the same "Did you mean" and card, whose first button is Look “…” up by
  name (the form under the results, filled in), and whose Their songs lists
  that artist's songs, as their row's Songs does. A row's artist searches for
  them, as typing their name would. `/lookup?q=WORDS` opens it with
  that search, and a lookup posted without JavaScript lands there. Here your
  song keeps its own row, with Fetch again, and each site's row of it its own:
  Ultimate Guitar's Get it again, with a version of theirs to pick under "⋯",
  and LaCuerda's, which keeps that LaCuerda sheet.
- **Fetch again, and Use LaCuerda's sheet.** On the library page the index's
  rows of a song of yours are folded into your song's own line, so its chevron looks
  it up again, sending what the lookup page sends: **Fetch again**, on a song
  with its sheet (a wanted song has Fetch now), looks it up anew, one `caracole
  get` (`POST /lookup` with the song); **Use LaCuerda's sheet**, when LaCuerda has
  one of it, looks it up keeping that sheet, as `caracole get --lacuerda` does:
  the sheet you picked on LaCuerda (`[lacuerda]`), else the best LaCuerda sheet
  caracole met for the song and didn't keep, else the one the bar's search finds
  on LaCuerda (its LaCuerda row, with chords), and none once the sheet kept is
  LaCuerda's. The song's line then says how it goes, as for Get it. An ignored
  song has neither, and the file, which can ask nothing, never has them.
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
  is under the line's chevron, and the line's Pick the match opens it there, the
  focus on the first candidate.
- **Look in the index.** A wanted song the offline index didn't match (and
  whose sheet you didn't pick on LaCuerda: its line's chevron says Tonight's run
  gets the sheet you picked on LaCuerda instead) has a
  Look in the index link under its line's chevron: its
  page, `/review?song=ID`, runs
  `caracole search` for the song's artist and title, and offers the first five
  hits the same way, without None of these. A pick writes `[match]` alone (see
  [Review](#review)). The page runs the search when you open it, so the
  library page carries no hits of its own.
- **Remove a song.** Each song's Remove, under its line's chevron, removes the
  song where it is, and you stay on the library: one tap, and
  the song's line says "Removing in 5 s · Undo", the keyboard focus on Undo,
  and under it what goes, in one sentence, as
  [`caracole remove`](#caracole-remove) works it out: "Deletes caracole's 6
  files for it, its record and its wanted.txt line; leaves 1 other file;
  never touches Music/." Nothing is sent for those five seconds but that
  question, which changes nothing, and Undo stops it there: the line says
  "Not removed", and Remove is back. Then the page queues `caracole remove
  --yes "ARTIST - TITLE"`, and the line says how it goes: "Removing…",
  "Queued…", "Removing from caracole…", then "Removed", the song's line keeping
  only its name, its size and its request line where it was, so that nothing
  on the screen moves, until you load the page again. From
  then on the song counts nowhere: the numbers at the top, the buttons'
  counts and the count over the list leave it out. A page older than a
  change to the library (the song merged into another since, say) removes
  nothing, and the line says to reload the library. A song removed elsewhere
  while the page is open (in another tab, on another device, by `caracole
  remove`) stays on it as it was, until a request of the page's comes back
  with another song under its number in the library, which the next song
  added may get: then its line says "Removed" too, and the new song comes
  under the search box, as any song new to the library does. Without JavaScript,
  Remove opens a page that says what goes and what stays; Remove it queues
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
  then how it ended (a lookup that stopped says why, in its stage's words).
  While a song is looked up (Fetch now, Fetch again, a search result's Get it,
  Get the missing songs, the Songbooks tab's Add a song, Try again), the line
  counts the steps over ("Fetching the lyrics from LRCLIB… · 4 of 7 done"),
  and under it each step is a chip, as on the requests page: Song, Match UG
  (the offline index it matched in, Ultimate Guitar's), Sheet (then the site
  it asks, Sheet UG or Sheet LaCuerda, switching when it falls back to the
  other, and once done the site the sheet came from), PDF, Lyrics, Extras and
  Songbooks; those done ticked, the one that runs lit, those to come grey, a
  failed one red. A song Ultimate Guitar's index lacks reads **Match: not on
  UG**, drawn plain (dashed), never as a failure: the sheet may come from
  LaCuerda. A step that turns out not to apply drops out, and the count with
  it (no PDF without a sheet, no Songbooks when no songbook lists the song).
  A request that looks nothing up (an add for tonight, a removal, a songbook's
  change) keeps its one line. How it ended:
  - **Ready**: the steps fold away and nothing takes their place; the line is
    the song's, found, and its title or its Open opens the sheet, its files
    under its chevron (a screen reader still hears Ready, and the focus Fetch now
    gave the request line goes to that Open);
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

  Ended any way but Ready, a lookup's steps stay under its line, so that you
  see which one stopped (a failed one crossed and red, Match: not on UG
  plain).

  A song asked for again shows on the line it has there already, and a
  refused request's line goes at the next request. A request still on its
  way when you reload the page keeps its line. When the server stops
  answering, the lines say so after a few tries ("caracole serve can't be
  reached; trying again…"), until it answers again.

  Two requests or more also show in a corner, folded to one line on every
  width ("2 requests · 1 to go"), so that it covers no song; it opens upwards
  to a line per song, with no steps (the songs' lines have them), and closes;
  a request that ended Ready says just **Ready**, its song's name opening the
  sheet. Its one Details link opens the requests
  page. A songbook's change and a removal stay out of it: the songbook, in
  the Songbooks tab, or the song's line, where you asked says how each goes. A screen reader hears each song's request line as
  it changes, to the last one, and Fetch now hands the keyboard focus to that
  line as it goes. The page asks the server how its requests go every 1.5 seconds
  while one waits or runs (`/jobs.json`), less often in a background tab.
- **Requests**, the page at `/jobs`, shows what runs now, then what ended:
  - **Now**: the request that runs, as a card with its song, how long ago it
    started ("started 12 s ago"), its line ("Rendering the sheet…") and its
    steps, the one running highlighted and those done ticked: for a lookup,
    Song, Match UG (or Match: not on UG, plain), Sheet (Sheet UG or Sheet
    LaCuerda once it asks a site, then where the sheet came from), PDF,
    Lyrics, Extras (Ultimate Guitar's second pass, its sheets scored and its
    tab, LaCuerda's sheet, gtptabs.com's Guitar Pro file and harptabs.com's
    harmonica tab) and Songbooks,
    the same chips the library page draws under a song's line, leaving out a
    step it
    doesn't use (Songbooks when Get the missing songs makes the songbook
    after, a step that ended with nothing to do for the song, such as the PDF
    of a song with no sheet); for a request of other commands, its commands.
    Under it, the requests queued, in order ("Queued, next", "Queued, 2nd"),
    each with **Cancel**, which takes it out of the queue before it starts
    (`POST /jobs/cancel`; a request that runs is never stopped halfway, and
    one that is over stays). A cancelled request is over, never run: it stays
    in the history as **Cancelled**, and the pages that follow it (the library
    page on another device, the lookup, export and versions pages) say so, the
    song's line getting its Fetch now back. Cancelling a request leaves its wanted.txt line:
    the song is in your library's list from the moment you asked, and the
    nightly run looks for it; remove it from the library if you don't want it.
    A songbook's Add a song for a song you haven't got queues two requests,
    its lookup and the songbook's change, both or neither: cancelling either
    cancels the other too, while it waits.
  - **Today** and **Earlier** (by when each ended, in the server's time
    zone): the requests that are over, newest first, each with its outcome as
    a coloured word, the reason in a sentence when there is one, the time it
    ended and its next step:
    - **Ready** · **Open**, its sheet; a reason says what waits for tonight's
      run, in the site's own answer ("LRCLIB answered 503: the lyrics wait
      for tonight's run.");
    - **Needs review** · **Pick the match**, the picker's own page,
      `/review?song=ID` (without candidates to pick, **Open in the library**,
      the song's line);
    - **Not found**: "Ultimate Guitar has no chords for it" once caracole
      asked Ultimate Guitar for it (its song page, or its artist's page), and
      "Not in the offline Ultimate Guitar index under this name" for a song
      the index didn't match and whose artist's UG page isn't known, which
      nobody asked; then, when the local indexes have it elsewhere, what: a
      sheet LaCuerda's index holds, or a page gtptabs.com's index lists for a
      song with no Guitar Pro file, and **Get it from there**, the lookup a
      search's Get it runs (with that LaCuerda sheet picked), back on this
      page. A site a new lookup would skip again isn't offered: one cooling
      down after a block, one the lookup skipped for a block or a spent
      budget, LaCuerda once asked about the song this month and gtptabs.com
      once looked up for it this month. With nothing elsewhere, a song the
      index didn't match has **See what caracole search finds** (the
      picker's page, Look in the index, above), also beside Get it from
      there, and any other **Request by name**, the library page's request
      form filled in with the song (`/#q=Artist - Title`);
    - **Not fetched yet**, with why (a cooldown, a block, a spent budget or
      an error, in the stage's words), and **Failed**, with its error in one
      sentence: **Try again** queues the same commands again
      (`POST /jobs/again`), with no question asked, a songbook's Delete
      among them (a lookup of Get the missing songs, alone now, makes the
      songbooks its song is in again itself); a failed removal's Try again asks what goes first, as of
      now (Remove's own question, `POST /remove`);
    - a songbook's **Made** or **Added** · **Open songbook**; **Removed**,
      **Deleted**, **Added** (the nightly run looks for it), and a LaCuerda
      artist page's **Read**, **Not found** or **Not read** (Try again), each
      in a word and a sentence;
    - an export's **PDF made** · **Open the PDF** (or **Failed**, no PDF was
      found, with Try again), and Make this my version's **Your version now**
      · **Open sheet**: never its song's request, whose line on the library
      page stays its own.

  Every request keeps its **Output**, folded away: when it was asked for (in
  the server's time zone, named), the commands it ran and
  what each printed (they run at `-v`, so that is the whole story), and a
  lookup's stages with their states and why one was skipped. A song's Details
  link on the library page opens that request's output. The page refreshes
  itself every 10 seconds while one waits or runs; Stop refreshing keeps it
  still. The song's line on the library page still says it the short way
  (Not found · see the to-do page, above). A request that ended in a review
  (`caracole add` found only candidates) shows the song's picker under it
  while the page is still, so you pick at once; with Fetch it now ticked, its
  lookup has no UG song to fetch until then: it says Needs review, not a
  failure, and in its output the lookup's sheet stage Waits for a pick. While
  the page refreshes itself, which would undo a choice half made, its Pick the
  match opens the picker's own page instead. `/api/jobs` and
  `/api/jobs/N` give each request as JSON: its steps (a lookup's stages),
  each with its state, its song and the library files its sheet can be read
  in. These JSON addresses (`/api/…`) answer caracole's own pages, the address
  bar and programs such as curl; a browser fetching one for another site's
  page gets 403.
- **Without JavaScript**, the forms still work: a request sends you to its
  line on `/jobs`, its output open; a pick, to its line; a lookup, to the
  lookup page, which follows it (one from the requests page's Get it from
  there, back to `/jobs`).
- **A sheet's versions.** The sheet viewer's Make this the one and Keep it
  open `/versions?sheet=…&tab=…&do=choose|keep` in the same tab (the viewer
  runs in a sandbox, with no way to send a form), and `do=clear` is Back to
  caracole's pick:
  a page of the server's own naming the song and the version ("Ver 2 of 13 ·
  4.85★ (12,629)", with the tabber's note) and what the song's sheet is now
  ("The one now: Ver 3 · 4.86★ (408)", or LaCuerda's sheet, or the auto-chords
  sheet), with the one button that does it. **Make this the one** queues
  `caracole versions SONG --choose TAB`, which looks the song up with that tab,
  as `caracole get --tab` does with the tab's own page: it becomes `sheet.txt`,
  the page the title opens, its PDF and its songbooks', kept under `[pin]`.
  Asked from that version's own page, which goes once it is the one, the page
  still says how it went, and Back to the sheet opens `sheet.html`.
  **Keep it** queues `caracole versions SONG --keep TAB`: one tab page, at the
  lookup pace, kept beside the sheet with a viewer of its own. A runner-up
  caracole keeps by itself is kept already there (sent anyway: 409), and
  stays only while caracole's ranking keeps it among the runners-up; `caracole
  versions SONG --keep TAB` on it makes it yours, kept whatever the ranking. **Back to caracole's pick**, on a song with a
  `[pin]` that chooses its sheet (a tab pin stays, as `--clear` leaves it),
  queues `caracole versions SONG --clear`. Each is the song's
  request, as a lookup is: its card says how it goes, stage by stage, the same
  one asked twice is queued once, and Make this the one takes the place of the
  song's lookup still waiting. Keep it never looks the song up, so a lookup
  asked for meanwhile (Fetch now, the lookup page's) still runs: after it, in
  its job while it waits, as a job of its own once it runs. The page then says how it goes (it reloads
  itself while it waits or runs) and, once done, what it came to, read from the
  song and overrides.toml, not from how the command exited: the version is the
  one now (Open the sheet), or your choice is under `[pin]` but a block, a spent
  budget or the hour's cap kept the sheet as it was, so the nightly run (or a
  later lookup) makes it the one; the version kept (Open it) or not, and why;
  the pin gone, or still there. Back to the sheet goes back where you came
  from. On the one already, a version kept already, one Ultimate Guitar no
  longer has, one under `[block]`, or a song with no such pin, it says so and
  offers nothing (sent anyway: 409).
  The library page's song sends the same three by the song's id (`song`, in
  place of `sheet`), and one more: **Fetch them**, `POST /versions/keep-more`,
  queues `caracole versions SONG --keep-more`, the Ultimate Guitar versions
  not kept yet, as many as one lookup may, a request of the song's as Keep it
  is (refused, 409, for a song with none left to keep, or an ignored one).
  Each shows on the song's line as any request does, not on a page of its own.
- **Songbooks**, the page's second tab (see [The Songbooks tab](#the-songbooks-tab)
  for what it shows). Each change runs its `caracole songbook` command (see
  [Songbooks](#songbooks)) and leaves you where you are:
  - a song's **grip** (⠿) drags it to its place; on the keyboard, ↑ and ↓ on
    the grip move it, and the move is sent a moment after the last key, so
    ↑ ↑ ↑ is one `caracole songbook move`;
  - its **chip** ("A Minor", "A Minor, piano") opens its key, mode, capo and
    instrument there: **Play it here** runs `caracole songbook set NAME SONG
    --key K --mode M --capo N`, the capo always sent with the key and the mode,
    so a sheet that takes the song's place later still sounds in that key, and
    `--instrument I` once you choose another instrument; on one with no capo
    (the piano, the harmonica, the winds) the capo menu is off and the key is
    the key the song sounds in, which the key menu takes as you choose it;
    **Its own version** runs `--clear`;
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
  - **Rename or delete** renames the songbook (its new name over the set list
    at once) or, once you tick the box, deletes it and the files caracole made
    of it.

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
  the Songbooks tab on the songbook, its songs there at once, and its files'
  buttons too, to use once it is made ("Making the songbook…", then "Made ·
  Open songbook"). A change that can't be made, such
  as a name another songbook has, a song no longer in the library or a
  songbook deleted since the page was made, is refused at once, and nothing
  runs: the songbook's status line, or the Select bar, says why, and the bar
  keeps your ticks. A make that fails once it runs (songbooks.toml can't be
  written, say) leaves the songbook on the tab as it would have been, its line
  saying it couldn't be made and its status line why, with nothing in it to
  change, and gives the Select bar back its ticks, the name and why: making it
  again is one tap. Made again with those ticks under another name, the new
  songbook takes its line; its Forget it takes it off the tab.

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
and Guitar Pro, Power Tab and MuseScore's score files (`.mscz`, `.mxl`,
`.musicxml`, `.mid`, `.midi`) as downloads, never through a symbolic link, never a
hidden file, and never the database or the cache. A download is
named for its song, whatever it is called in the song's folder (where it stays
`guitar-N` or `score-N`): `Eagles - Hotel California.gp3`, its second file
`Eagles - Hotel California (2).gp5`, accents and Chinese as they are, and
nothing a system refuses in a file's name (`AC/DC` saves as `AC_DC - …`), a very
long name cut so that the title stays. That name comes from the server, so it
holds only for a file caracole serve sends. The page opened from the folder,
and a sheet viewer opened from the folder, put the same name in their links'
`download` attribute, but Chromium-based browsers (Chrome, Edge, Brave) ignore
it on a page opened as a file and save the file as `guitar-N` (or `score-N`),
its name in the folder. A songbook's page,
`_songbooks/<name>/songbook.html`, is sent only while it is the very page
caracole wrote there, as recorded when it wrote it (anyone with a synced device
could put a page of their own in the library), and in a sandbox: its scripts
run, but it can't reach the server, and keeps no
storage, so the song it shows is the one in its address (`#song-3`), where the
viewer keeps the song's transposition, mode, capo, text size and scroll speed
too (`#song-3=&t=2&fs=20&speed=8`). Edited
on a device, or replaced by a link, it gets a page saying so until the next
`caracole render` (or `caracole songbook render`) writes it again.

Of the HTML pages in the library, the server sends only the sheet viewers
(`sheet.html`, `sheet (auto).html` and each kept version's `version-<tab>.html`;
see [The sheet viewer](#the-sheet-viewer)),
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
afresh.

**Guitar Pro files in the browser.** Served, a song's Guitar Pro file
(`guitar-N.gp3`, `.gp4`, `.gp5`, `.gpx` or `.gp`, one caracole keeps: filed
from `_inbox/` or downloaded from gtptabs.com) has a group of its own under its
line's chevron, named as the file is (`Guitar Pro 1 · gtptabs.com`): **Open in the
browser**, and **Download** beside it. A sheet viewer the server sends offers
the same as **Guitar Pro tab**, in its ⋯ settings, for a song with such a file
(the viewer from the folder links the file itself), and so does the guitar after
the song's title in a songbook's set list (see [The Songbooks
tab](#the-songbooks-tab)). Open in the browser is
`/guitar?file=<the file's path in the library>`, a page the server makes for
each request, where [alphaTab](https://www.alphatab.net) draws and plays the
file: the song's title and artist, links back to the song in the library, to
its sheet viewer when it has one and to the file as a download, then a bar
that stays at the top while the score scrolls: **Play** (Pause while it plays)
and **Stop**, the **Tempo** (50 to 125 %) and **Tab only** or **Score and tab**
on one row, and under it the file's **tracks**, a button each with its name
(whole when you point at a name cut short) and its kind (6 strings, 4 strings,
drums, or no tab: a voice's or a piano's). The page starts on the first track a
guitarist would want: of those with notes and a tab, the first whose name says
guitar, before one whose name says nothing of it, and those before vocals, keys,
a synth or a bass (a Guitar Pro 3 file writes even the vocals as a tab). Tap a
track to show it instead, or hold Shift (or Ctrl, or ⌘) as you tap to show it
beside those shown, or take it away from them; on a touch screen, press and hold
it for that. The speaker on each track mutes it, and again unmutes it: at once,
while it plays too, whichever track is shown, until you close the page; a
muted track is struck through. On a screen under 600 px wide the bar is
compact (the switch reads **Tab** or **Score**, and the tracks scroll sideways
in their own row, which starts at the track shown) and the page starts with the tab alone, a little smaller,
three or four bars a line; a track with no tab (a piano's, the drums') is
shown as a score whatever the switch says. Playing, the page follows the
cursor. It is dark or light as your system is, the score too: its title,
artist and every text alphaTab draws in the page's text colour. A Power Tab
file (`.ptb`) stays a download: alphaTab can't read it.

Nothing is written into the library for it: the file is read when you open
the page (never through a symbolic link, and only a file the database records
as a song's Guitar Pro file; any other path answers 404), and its bytes are in
the page. The page runs in a sandbox, like a viewer, and loads one thing from
the server: alphaTab, its music font and its SoundFont, about 2.9 MB in one
script, `/assets/alphatab/alphatab-1.8.4-<hash>.js`, which the browser checks
against its hash and keeps for good. That script is the same for anyone, so the
server sends it to any origin, the page's sandbox among them. Only caracole serve does this: `index.html`
opened from the folder lists the file as before, and the server needs alphaTab
for it, which the Nix packages carry (`CARACOLE_ALPHATAB_DIR`; without Nix, see
[deploy.md](deploy.md#4-the-fonts-and-alphatab)). Without it the server runs all the same, the line's chevron
says Guitar Pro files are downloads until it has alphaTab, and `/guitar` says
why it can't show one.

**The Android app's copy.** caracole's Android app copies the library from the
server to read it offline: `GET /api/offline` lists what to copy, as JSON
(`format` 1; `start`, the page the app opens first; `files`, each with its
`path` in the library, the `url` that sends it, its `size`, `sha256`, `type`
and the `headers` the server sends it with, its Content-Security-Policy among
them). It lists `index.html` first, as caracole wrote it into the library (the
page that opens from the folder, with no forms), at `/offline/index.html`, then,
by path, every file that page links to that the server sends: the sheet
viewers, kept versions' pages, harmonica tabs' pages and songbook pages while
each is still as caracole wrote it, and the PDFs, sheets' text, ChordPro, lyrics, info.json,
Guitar Pro files and scores. Never Music/, `_inbox/`, a hidden name or a file
no page links. caracole records `index.html` each time it writes the pages; one
changed since, or written by a caracole older than that record, isn't sent, and
`/api/offline` answers 503 until `caracole todo` (or any command that writes the
pages) writes it again. It is a read and needs nothing on the server: no
option, no lock, no request to a site. Another site's page can't read it. In
the app the pages behave as they do opened from the folder: a viewer shows the
command to run for Export PDF or a version, and the Guitar Pro files themselves.

Who can reach it: there is no sign-in, no access token and no cookie, so
whoever can reach the server can read the library, request songs and change
songbooks. Keep it reachable only on a network you trust, your LAN or your
tailnet, never the internet.

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
- These keep other sites' pages, open in a browser on your network, from using
  the server; they keep out no person or program on the network itself.

It runs until Ctrl-C. On a server, `caracole-web.service` runs it
([deploy.md](deploy.md#5-the-library-page-on-your-network)).

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
  needs it. A song set on another instrument is printed for it, as an export
  is (`caracole render --version`, above): a ukulele's four strings, the
  piano's keyboards, the harmonica's harps and holes, the winds' scale. One
  chordpro run draws diagrams of one number of strings, so the PDF draws
  those most of its songs on a fretted instrument have (the guitar's six on a
  tie), and writes the others' shapes as frets above their song (`Ukulele: C
  0003 · Am 2000 · F 2010`). A song without a sheet keeps its place: the contents name it
  ("Hysteria · Muse · missing: no sheet yet"), and its page says so. Its
  document title, the name a PDF viewer or a phone shows, is the songbook's.
- **`songbook.html`**: one page for the phone, which opens from the synced
  folder and loads nothing. It opens on the contents, each song with its
  artist, key and capo on a line under its title ("Oasis · Em · capo 2", "Soda
  Stereo · G dorian": the key of the shapes the song opens in, and its capo,
  where the songbook plays it); tap
  a song to open it in the sheet viewer, with everything the viewer does
  (chord shapes, transposition, chords to play instead, modes, scrolling by
  itself, the artist's name that opens the library page on their songs), each
  song opening where the songbook plays it (on its instrument too) and keeping its
  own settings, its scroll
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
  `3. Soda Stereo - De Música Ligera (G Dorian)`, its capo only when it
  plays with one (`(E Minor, capo 2)`), or
  `(key unknown, as written)` for a key or a mode its sheet can't take, the
  key of its own version's too.
- **`caracole songbook add NAME "ARTIST - TITLE"...`** adds songs at the end;
  one it has already stays where it is.
- **`caracole songbook remove NAME "ARTIST - TITLE"...`** takes songs out. A
  song removed from the library goes by the name the songbook gives it.
- **`caracole songbook move NAME "ARTIST - TITLE" POSITION`** moves a song,
  1 being the first; past the end is last.
- **`caracole songbook set NAME "ARTIST - TITLE" [--key K] [--mode M] [--capo N] [--instrument I]`**
  gives a song its own setting in the songbook: the key it is played in
  (`G`, `F#`, `Bb`), its mode (`ionian`, `dorian`, ... `locrian`), its capo
  (0 to 11) and the instrument it is played on (`guitar`, `ukulele`,
  `ukulele-low-g`, `baritone`, `piano`, `harmonica`, `flute`, `recorder`): the
  songbook's PDF draws that instrument's chords (above, `songbook.pdf`), its
  phone page opens the song there, and it says so (`on the ukulele`,
  `In the songbook: A Minor, ukulele`). On an instrument with no capo the key
  is the key the song sounds in, with no capo taken from where it plays now
  (`--key B --instrument piano`: `B Minor, piano`); `--instrument guitar` plays
  it on the guitar even where its own version is on another. The parts you
  give change; the others stay. A key or a mode
  given with no capo keeps the capo the song plays at now, and the setting
  names it (`key G, dorian, no capo`). It says where the songbook plays the
  song now, as its set list does: `In the songbook: G Dorian`, or
  `In the songbook: G Dorian, capo 2` with a capo. `--clear` takes the
  whole setting off, and the song is in its own version again. In songbooks.toml a
  song with a setting is a table in place of the string, and one without stays
  a string: `songs = ["Oasis - Wonderwall", { song = "Soda Stereo - De Música
  Ligera", key = "G", mode = "dorian", capo = 0 }, { song = "Eagles - Hotel
  California", instrument = "ukulele" }]`. A key, mode, capo or instrument
  that is none of those is an error naming the songbook and the song, and
  stops the songbooks. The songbook's files play the song there: the key is the key of
  the shapes you play, as an export's name gives it (`G Dorian, capo 0`: G
  dorian shapes, no capo; with `--capo 2` they sound in A dorian), and what the
  setting leaves out is the song's own version's (`--capo 2` alone keeps its
  sound and plays it from other shapes; a key with no mode is that tonic in
  the mode the song's own version plays its sheet in, so on a sheet that reads
  the song's chords in the relative key, C major for A minor's, `--key B` is
  B major there). The key is a key, not a move:
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
order, their sheets, their transpositions, caracole's PDF style or the fonts,
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

[version]      # where you play a song, by its key, as Make this my version saves it: its PDF, viewer and songbooks follow
"Soda Stereo - De Música Ligera" = "key=Gm&mode=dorian&capo=0&at=Gm.x-x-5-7-8-6"

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

[harptabs]     # the harptabs.com tab a song's harmonica tab comes from
"Billy Joel - Piano Man" = "https://www.harptabs.com/tab/23862/piano-man-c-harmonica"
```

- **Song keys** are written `"Artist - Title"`. They match the way songs
  match, so these don't matter: case, accents, a leading "The", streaming
  services' version suffixes (" - Remastered 2011", " - 2019 Mix", " - En Vivo", "(Acústico)",
  " - Versión Acústica"), Traditional or Simplified Chinese, and number words
  or digits ("Té Para Tres" is "Té para 3"). In the artist, a leading Los,
  Las, El or La doesn't either, nor "y" for "&" ("Fito y Fitipaldis").
- **`[alias]`** takes one UG artist slug or a list of them. The slug is the
  artist part of a tab's address, as in `/tab/bob-marley/...`.
- **`[match]`** points one song at one UG song. Unlike a pin, it still picks
  up tabs added to that song later. Correct a `[match]` or a `[pin]`, and
  what the old one brought goes: the next fetch takes the song's sheet and tab
  from the new one. When the new one has no sheet, the
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
  candidates of their kind (sheet, tab), in the order given. A pin whose page
  is gone, is Official, or is closed to bots by robots.txt (UG's `/tab/track/`
  pages), or redirects to such a page, pins nothing, and the song's other
  versions compete for that kind. Nor does a pin of a page of a type caracole
  doesn't use (a Guitar Pro file's, a bass tab's). `caracole versions --clear`
  takes a song's chords pins out again.
- **`[transpose]`** shifts the chords and the key in the PDF. `sheet.txt`
  stays as the source wrote it.
- **`[version]`** is the song's own version: where you play it, as Make this
  my version saves it. It is the key it plays in, a mode you chose, and its
  capo (`key=Gm&mode=dorian&capo=0`: G dorian shapes, no capo). The key is
  the key of the shapes played, as a sheet names one, in the mode the sheet's
  chords were read in (`Gm` for an A minor sheet played two down, `D` for a
  C major one played two up, `A dorian`); a sheet in its place whose chords
  read in another mode on the same notes (C major's are A minor's) is read in
  those notes, so it plays the chords the version played. A sheet whose key
  names the right tonic in the other mode (A for an A minor sheet's chords,
  as a key read from audio can) is read from that tonic instead, when more
  of its chords are in that tonic's key in the entry's mode than in the key
  it names: it plays the chords the version played too, its label in the
  mode it names (`B Major, capo 0` for B minor's chords). A sheet whose key
  is off by another interval (a fifth) moves by the key it names. So when you
  write an entry by hand, its key names a key's notes, not a tonic alone:
  `key=G` on an A minor sheet is G major's notes from A, A dorian; write
  `key=Gm` for G minor. The mode, one of
  `ionian`, `dorian`, ... `locrian`, is there only when you chose one, and is
  then the mode those shapes play in (G dorian, whatever mode a new sheet
  names; on a sheet read in the relative key the viewer names it from that
  sheet's tonic, `Bb Lydian` for G dorian's notes on a C major sheet, and a
  chord outside the key there (a Bb among C major's chords) can come out
  a semitone off; with no mode chosen, every chord plays as it did). The
  capo is 0 to 11, the sheet's when left out. Then come `alt=` for chords
  played instead and `at=` for chosen shapes, each by the chord's name in that
  key (`alt=F.Fmaj7`: Fmaj7 for every F; `at=Gm.x-x-5-7-8-6`: Gm in that
  shape, its frets from the nut, low E first, `x` for a string not played,
  wherever the new sheet's card lists it; a `%`, `&`, `=`, `,` or `.` in a
  chord's name is written `%25`, `%26`, `%3D`, `%2C`, `%2E`; a ukulele's shape
  by its four strings, its G string first). Last, `inst=` names the instrument
  it is played on (`inst=piano`): its viewer opens there, and its songbooks
  play it there, but its `sheet.pdf` stays the guitar's; its capo is the one
  the guitar plays at. The song's `sheet.pdf` is
  made in it, its viewer starts in it, and its songbooks play it there, unless
  a songbook sets its own; it wins over the song's `[transpose]`, which stays
  in the file. The key is a key, not a move, as a songbook's setting is: a
  sheet in another key or with another capo that takes the song's place plays
  in that key at that capo, and a chord swapped or shaped there that the new
  sheet plays too keeps its swap or its shape; one it doesn't play takes
  nothing of them. An auto sheet rendered beside a human one takes its key,
  mode and capo alone. A sheet with no key (no chord caracole can read, none
  to estimate one from) can't take a key, so it plays as written, the log
  says so once its PDF is made (`sheet.pdf is as written, not in your
  version (G Dorian, capo 0): its sheet has no key caracole can read`), and
  its songbooks say so (`key unknown, as written`). An entry with `t=` in place
  of `key=`, as caracole wrote one before, is a move from the sheet, as the
  sheet viewer writes its address after `#` (`t=2` semitones, `mode=dorian`,
  `capo=0`, `alt=` and `at=` by the chords' places in the sheet; a `#` before
  it is dropped; without a `t`, it is at the song's `[transpose]`): it works
  as it did, and caracole never rewrites it. Take the entry out to go back to
  `[transpose]`, or the sheet as written. A value that is not text, holds a
  control character or is over 2000 characters, or whose key, mode or capo
  can't be one (a key as a sheet names one: `G`, `F#m`, `Bb dorian`), or with a
  `key=` and a `t=` both, is an error naming the entry.
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
- **`[harptabs]`** names the harptabs.com tab you picked for the song: its page
  (`https://www.harptabs.com/tab/23862/piano-man-c-harmonica`, or as your browser
  shows it). The nightly harptabs pass reads that page alone, in place of the
  song's candidates, and keeps its tab whoever the page names as its artist, as
  the song's next `harmonica-N.txt`, beside any it has: never in place of one. A
  tab you name is asked for at once; one gone from the site (404) is asked for
  again after 30 days. Get it on a harptabs.com row of caracole serve's search,
  and `caracole get --harptabs`, write it.

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

## Fonts in the PDFs

Every PDF caracole makes (a sheet's, an export's, a songbook's) is set in the
fonts of one folder, `pdf_fonts`, or `$CARACOLE_PDF_FONTS` (the key wins). It
holds four, each a `.ttf` or an `.otf`:

| File | What it sets |
|---|---|
| `regular` | the words, the line under the title, the page footer, the contents |
| `bold` | the title, the chords, the section names, the chord diagrams' names |
| `italic` | a repeat mark ("x2") beside the chords |
| `mono` | a tab |

The Nix packages' wrapper points `$CARACOLE_PDF_FONTS` at Adwaita Sans and
Adwaita Mono (nixpkgs' `adwaita-fonts`), GNOME's system fonts: what a Firefox
that sets no font of its own shows on GNOME, and what caracole's own pages
show there. Adwaita Sans comes as variable fonts, which ChordPro 6.050.7 draws
only in their default weight, so the package makes static Regular, Bold and
Italic instances of them (`nix/pdf-fonts.nix`), with their licence, the SIL
Open Font License 1.1, in `licenses/` beside them. A sheet's PDF embeds the
letters it uses of each, about 0.2 MB.

Each must be a font ChordPro draws right, as the Chinese font below must: a
single `.ttf` or `.otf`, no collection, no odd-length glyph records, and a
static font, not a variable one. A folder that lacks one, or holds one that
isn't, is logged once a render (`pdf_fonts is unusable (…): the PDFs keep
ChordPro's built-in fonts`), and the PDFs keep ChordPro's built-in Helvetica
and Courier, as they do with no folder set. Setting the folder, changing it or
taking it away makes every PDF again at the next render.

Adwaita Sans has the Latin, Greek and Cyrillic letters, the accents, and the
curly quotes and apostrophes (’ ʼ “ ”), so a sheet that has them is set in it
whole. Only letters it lacks, Chinese among them, bring in the Chinese font
below, for the words alone: the chords, their repeat marks and a tab stay in
Adwaita. A symbol it lacks (an emoji, say) prints as an empty box and brings
in no other font. A songbook is one PDF: with a Chinese song in it, all its
words are in the Chinese font.

## Fonts for Chinese sheets

Neither ChordPro's built-in PDF fonts nor Adwaita Sans have Chinese glyphs, so
a sheet with Chinese lyrics needs a font file. The Nix package sets one: its
wrapper points
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
Without Nix, [deploy.md](deploy.md#4-the-fonts-and-alphatab) installs
FusionKaiJ.

The font is used only for sheets that need it, by what the PDF prints: Chinese
only in the tab's notes before its first section, which stay out of the PDF,
needs none. Without `pdf_fonts`, ChordPro's built-in fonts lose any letter
outside Windows' Western set (a ʼ, Greek, Cyrillic), and such a sheet is set in
the Chinese font whole, as is one with a symbol they lack. Some transcribers type a
Cyrillic or Greek letter that looks Latin, such as the Cyrillic х in a repeat
mark "(х2)": when those are a sheet's only such letters, they are written as
the Latin ones, so the sheet keeps ChordPro's built-in fonts and needs no font
file.

## The library folder

```
Library/                    library_dir: ~/Tabs by default, /var/lib/caracole/library on a server
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
      version-39144.txt     another Ultimate Guitar version caracole scored for the sheet,
      version-39144.json    kept beside it (by its tab id), the runners-up: its text, the
      version-39144.html    version as UG gave it, and its viewer (no PDF of its own)
      lyrics.txt            the lyrics, from LRCLIB
      lyrics.lrc            the timed lyrics, when LRCLIB has them
      guitar-1.gp5          Guitar Pro or Power Tab files: filed from _inbox/, or from gtptabs.com
      score-1.mscz          scores you downloaded (MuseScore, MusicXML, PDF, MIDI), filed
      harmonica-1.txt       a harmonica tab from harptabs.com: hole numbers over the lyrics
      harmonica-1.html      its page, for the phone: each hole over its syllable, heard on a tap
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
separator or a character file systems reserve: `AC/DC` becomes `AC-DC`. An
artist has one folder: a new song by an artist the library has already,
written in another case alone (`oasis` beside `Oasis`), takes the library's
spelling, as a phone's file system may not tell two folders apart by case.
A folder's name keeps 120 bytes at most, so two songs whose titles agree that
far make one folder, and share it. A file one of them keeps there (a sheet, a
Guitar Pro file) is never written over by the other's: that song waits, and
the run's summary, `caracole fetch`, `caracole lacuerda` and a lookup say so
(`caracole autochords` in its log, before it runs the models), until the
folder is its own: remove one of the two (`caracole remove`), and ask for it
again under a shorter title.

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
back in the song's folder under its name, or drop it into `_inbox/` again:
the next scan puts it back in its place.

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
transcriber gives it, but for a letter alone (`A`, `F#`, `La`), which says no
mode: that is the minor key on that letter when the sheet's chords have its
notes (or those of the minor key a capo lower, for a tab that names the key the
song sounds in) and not the major key's, and the sheet never plays that
letter's major chord (A, A7, Amaj7). Ultimate Guitar names Hotel
California's key `A`, with capo 2 over Am E7 G D F C Dm E: caracole reads A
minor, A minor shapes that sound B minor. A key named with its mode (`Am`, `A
major`, `A minor`) is as named, and a letter whose chords fit its major key is
that major key. A sheet's own `{key: A}` with no key from the tab is read so
too. Either is the sheet's key before any `[transpose]`.

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
  rewrites every song's info.json once, with these fields (and once more
  after the upgrade that reads a tab's letter alone with its chords). caracole never
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
[deploy.md](deploy.md#4-auto-chords)). It links the new file to the song by
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

## Running it on a server

[deploy.md](deploy.md) sets caracole up as a nightly service, on NixOS with
the flake's module or on Ubuntu 24.04 without Nix: the timer, the hardened
units, Syncthing for the library and the music, restic backups, the offline
auto-chords unit, and caracole-web, which serves the library page with its
request form to your LAN or tailnet, with no sign-in. There, run any command
as the service does with `sudo caracole-admin COMMAND`, for example
`sudo caracole-admin index build`.
