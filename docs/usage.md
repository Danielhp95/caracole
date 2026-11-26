# Using caracole

You list the songs you want to learn. caracole builds a private library from them: for each song a
sheet with the chords over the lyrics, the lyrics on their own, and guitar parts where they exist.
A nightly `caracole run` does the work within a small request budget. `Library/_todo.md` lists
what it can't decide without you.

This page covers using caracole on any machine. [deploy.md](deploy.md) sets it up as a nightly
service, on NixOS or on Ubuntu without Nix, with Syncthing and backups. `caracole --help` and
`caracole COMMAND --help` list every command and option.

- [Configure](#configure)
- [What caracole prints](#what-caracole-prints)
- [Say what you want to learn](#say-what-you-want-to-learn)
- [The first run](#the-first-run)
- [One step at a time](#one-step-at-a-time)
- [UG's artist directory](#ugs-artist-directory)
- [Lyrics from LRCLIB, Megalobiz and AZLyrics](#lyrics-from-lrclib-megalobiz-and-azlyrics)
- [Audio from YouTube](#audio-from-youtube)
- [The to-do page](#the-to-do-page)
- [Browse and search](#browse-and-search)
- [Songbooks](#songbooks)
- [overrides.toml: your decisions](#overridestoml-your-decisions)
- [Fonts in the PDFs](#fonts-in-the-pdfs)
- [Fonts for Chinese sheets](#fonts-for-chinese-sheets)
- [The library folder](#the-library-folder)
- [A worked example](#a-worked-example)
- [Keeping the database](#keeping-the-database)
- [Two caracoles: the phone's and the computer's](#two-caracoles-the-phones-and-the-computers)
- [Running it on a server](#running-it-on-a-server)

## Configure

caracole reads one TOML file: the one `--config` (`-c`) or `$CARACOLE_CONFIG` names, else
`~/.config/caracole/caracole.toml` (under `$XDG_CONFIG_HOME` when that is set). Without a file, the
defaults apply.

Every key is optional. An unknown key, or a value of the wrong type or out of range, is an error:
the command exits with status 2 and names the key. Write `true`, `false` and numbers without
quotes, and paths and names as quoted strings. `~` is your home folder, and a relative path is
relative to the config file's folder.

Before you upgrade from an old caracole, delete `[spotify]`, `guitar_pro_mode`, `keep_guitar_pro`
under `[rank]` and `token_file` under `[ntfy]`. They are unknown keys now.

Here is every key with its default. The commented-out keys have none.

```toml
# name = "..."                    # what the pages call the library; default: library_dir's folder name
# data_dir = "..."                # one folder for the four below (see Folders)
library_dir = "~/Tabs"            # sheets, lyrics, _todo.md, index.html, wanted.txt
music_dir = "~/Music"             # tracks you bought; read only, used only for auto-chords
# state_dir = "..."               # the database and the lock (see Folders)
# cache_dir = "..."               # every raw response, kept forever (see Folders)
# overrides_file = "..."          # default: overrides.toml in library_dir
# wanted_file = "..."             # default: wanted.txt in library_dir
user_agent = "caracole/0.1 (personal tab library)"
chordpro_bin = "chordpro"         # the program that renders PDFs
ytdlp_bin = "yt-dlp"              # or $CARACOLE_YTDLP_BIN; see "Audio from YouTube"
demucs_bin = "demucs"             # or $CARACOLE_DEMUCS_BIN (demucs-rs)
# pdf_fonts = "/path/to/folder"   # or $CARACOLE_PDF_FONTS; see "Fonts in the PDFs"
# cjk_font = "/path/to/font.ttf"  # or $CARACOLE_CJK_FONT; see "Fonts for Chinese sheets"

[ntfy]                            # optional: a summary after each run, and alerts
# url = "https://ntfy.sh/a-long-private-topic"

[providers.ug]                    # Ultimate Guitar
budget = 60                       # requests per run
delay = [2.5, 5]                  # seconds between two requests, chosen at random
lookup_delay = [0.125, 0.375]     # the same, for a lookup (caracole get); [0, 0]: none
lookup_requests = 6               # requests to the site for one lookup, at most
lookup_per_hour = 60              # requests to the site for all lookups of an hour
[providers.lrclib]                # lyrics
budget = 200
delay = [0.25, 0.5]
[providers.megalobiz]             # timed lyrics, where LRCLIB has none, or none timed
enabled = true                    # false: caracole asks the site nothing
budget = 60                       # and never more than 900 a day (UTC)
delay = [0.5, 1]                  # can go past its API's 30 requests a minute
lookup_delay = [0.5, 0.75]
[providers.azlyrics]              # plain lyrics, where LRCLIB and Megalobiz have none
enabled = true
delay = [0, 0]                    # two requests per song, back to back; no budget by default
lookup_delay = [0, 0]
[providers.lacuerda]              # Spanish chord sheets, and its listings of every artist
budget = 30
delay = [2.5, 5]
[providers.gtptabs]               # Guitar Pro files, downloaded for you
enabled = true
budget = 20
delay = [2.5, 5]
[providers.musescore]             # MuseScore's song sitemaps, for links to its pages
enabled = true
budget = 10
delay = [2.5, 5]
[providers.harptabs]              # harmonica tabs, kept for your songs
enabled = true
budget = 20
delay = [2.5, 5]
[providers.gametabs]              # text tabs of game music, kept for your songs
enabled = true
budget = 20
delay = [0.25, 0.25]              # four requests a second
[providers.ireal]                 # iReal Pro's forum: chord charts of jazz standards
enabled = true
budget = 20
delay = [2.5, 5]
[providers.youtube]               # the audio of songs nobody has charted, for auto-chords
enabled = true                    # false: caracole runs no yt-dlp; on only with auto-chords
budget = 6                        # yt-dlp runs per run, each a search or a download
delay = [3.75, 7.5]               # seconds between two yt-dlp runs
[providers.ytimg]                 # YouTube's image host: a suggested video's thumbnail
enabled = true                    # false: suggestions come without thumbnails
budget = 20
delay = [0, 0]                    # no wait: right after the search
[providers.itunes]                # an Apple Music link shared to the phone
enabled = true                    # false: the phone asks Apple nothing
lookup_requests = 1               # requests for one shared link, at most
[providers.spotify]               # a Spotify link shared to the phone
enabled = true
lookup_requests = 2               # a spotify.link short link's hop, then the page
[providers.tidal]                 # a TIDAL link shared to the phone
enabled = true
lookup_requests = 2               # a tidal.link short link's hop, then the page
[providers.youtube-oembed]        # a YouTube or YouTube Music link shared to the phone; never yt-dlp
enabled = true
lookup_requests = 1

[ug_directory]                    # UG's artist directory: its listings, then every bare artist's page
concurrency = 6                   # requests in flight at once (1-32)
delay = [0, 0]                    # seconds before each request, chosen at random; [0, 0]: none
budget = 25000                    # requests per pass, separate from [providers.ug]'s budget

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

[autochords]                      # read by `caracole autochords`, `transcribe` and `youtube --sheet`
# btc_weights = "/path/to/weights.pt"         # or $CARACOLE_BTC_WEIGHTS
# beat_checkpoint = "/path/to/final0.ckpt"    # or $CARACOLE_BEAT_CHECKPOINT
device = "cpu"                    # where the models run
# whisper_model = "/path/to/large-v3.pt"      # or $CARACOLE_WHISPER_MODEL
# separator_model = "/path/to/htdemucs.safetensors"  # or $CARACOLE_DEMUCS_MODEL
transcribe_device = "auto"        # where Whisper runs: "auto" (the GPU when there is one), "cpu" or "cuda"
transcribe = true                 # a sheet from a video hears the words no lyrics site has; false: the card offers it
transcribe_per_run = 3            # songs whose words the nightly `caracole autochords` hears, newest first; 0: none
```

caracole keeps one sheet and one text tab per song, and beside the sheet the other Ultimate Guitar
versions it scored (`scored_sheets`). Scores and thresholds can't be negative, scores stop at 100,
and `scored_sheets` is a whole number.

**Folders.** With `data_dir`, `library_dir`, `music_dir`, `state_dir` and `cache_dir` default to
its `library`, `music`, `state` and `cache` folders. One you set yourself still wins. Without it:

| Folder | Default |
|---|---|
| `state_dir` | `$STATE_DIRECTORY` when systemd sets it, else `$XDG_STATE_HOME/caracole`, else `~/.local/state/caracole` |
| `cache_dir` | `$CACHE_DIRECTORY`, else `$XDG_CACHE_HOME/caracole`, else `~/.cache/caracole` |

The state folder holds `caracole.sqlite`, `caracole.lock`, the `requests.jsonl` of `caracole serve`,
in `backups/` the last three copies of the database (see
[Keeping the database](#keeping-the-database)), and in `audio/` the audio files you give caracole
(see [caracole audio](#caracole-audio)), which can't be fetched again. Back it up, but don't sync it.

The cache keeps every response caracole has received, so deleting it costs only requests. PDFs are
made there too, so caracole must be able to write to it. Its `icons` folder holds each site's icon
for `index.html` (see [Where each file came from](#where-each-file-came-from)).

**The database.** Before a new caracole migrates `caracole.sqlite`, it copies it to
`caracole.sqlite.vN.bak`, where N is the version it had. A new site's index starts empty, until
the nightly run or that site's command reads the site.

A database that a newer caracole migrated (after a rollback, say) stops every command that uses it
with status 2 and `database: … is at schema version 11, but this caracole knows up to 10 …`. The
message names the copy to restore, when there is one. A state folder caracole can't use ends a
command with status 1 and `can't open the database …` or `can't open …/caracole.lock: …`.
`caracole add` is the exception to both: it keeps its line and warns.

**No secrets.** caracole reads none. ntfy is a topic's `url`, posted to with no token, so choose a
long topic name nobody would guess. On NixOS it sits in the Nix store, which every user of the
machine can read. `caracole serve` has no sign-in (see [caracole serve](#caracole-serve)).

**Providers.** The tables above are the only ones, and any other `[providers.…]` table is an error.
Each also takes the three `lookup_` keys, with the defaults under `[providers.ug]` unless the block
gives others.

`ug`, `lrclib` and `lacuerda` can't be turned off: `enabled` there is an unknown key. With
`enabled = false` under any other, caracole sends that site nothing, the nightly run skips its
step, and the to-do page's Provider health says it is off. Some have rules of their own:

- `megalobiz` gets at most 900 requests a UTC day, runs and lookups together. After that its songs
  wait for the next day.
- `azlyrics` has no `budget` unless you set one. It is asked only about songs with no lyrics, each
  at most once in 30 days.
- `youtube` is on only where caracole can make chords of what it downloads (see
  [Audio from YouTube](#audio-from-youtube)). Its budget counts yt-dlp runs, and a lookup never
  runs yt-dlp.
- `itunes`, `spotify`, `tidal` and `youtube-oembed` are asked only by the phone, once, about a
  shared link that names no song (see [phone.md](phone.md#what-works-on-the-phone)). They have no
  `budget`, and the phone takes their settings at a sync.

**Two paces.** Bulk work keeps `budget` and `delay`. That is the nightly run, `caracole index
build` and most other commands. A lookup is one song you asked for now, with `caracole get` or from
`caracole serve`. It keeps `lookup_delay` instead and stops after `lookup_requests` requests to a
site. All the lookups of the last hour share `lookup_per_hour`, so a stuck button can't turn
lookups into a crawl.

Half of that hour is kept for sheets. Once lookups have spent half of it, a lookup leaves to the
nightly run what follows its sheet: Ultimate Guitar's other sheets and text tab, and LaCuerda for a
song that already has a sheet. With the defaults, an evening of lookups keeps getting twenty to
thirty sheets an hour.

Either pace sends a site one request at a time and keeps to robots.txt's closed paths, the cache,
the blocks and the cooldowns. caracole does not keep a robots.txt `Crawl-delay`: gametabs.net asks
for 5 seconds, and its default `delay` is a quarter of a second.

**Guitar Pro files** come two ways. caracole downloads one from gtptabs.com for each song that has
none (`caracole gtptabs`). A file you get yourself, dropped into `_inbox/` and named as the song
is, is filed under its song (`caracole scan`). None come from Ultimate Guitar, whose robots.txt
closes its downloads. From there caracole takes chords, text tabs and ukulele chords only.

**Harmonica tabs** come from harptabs.com, which has about 27,000. For each song that has none,
caracole looks the title up in the site's sitemap and keeps the most viewed tab by your song's
artist as `harmonica-1.txt` (`caracole harptabs`), with a page beside it (see
[The harmonica tab page](#the-harmonica-tab-page)). To find tabs by artist too, `caracole harptabs
--index` and the nightly run read the site's artist pages into a local index: the names of the
tabs, never the tabs. The site's terms ask that nothing be copied, yet caracole keeps tabs from
it, for your own songs only (see [sources.md](sources.md)).

**Tabs of game music** come from gametabs.net: about 8,500 guitar and bass tabs of some 1,600
games. The site files a tab under its game and its composers, never a performer. So write the game
or the composer as the artist:

    Hollow Knight - Resting Grounds
    Hollow Knight OST - Resting Grounds
    Yuzo Koshiro - Fillmore

caracole reads up to four tab pages with your title, the most viewed first, and keeps the most
viewed one whose page agrees on the title and the game or composer, as `gametab-1.txt` (`caracole
gametabs`). A song is found by its composer only once `caracole gametabs --index` or the nightly
run has read its game's page. A tab's Guitar Pro, MIDI and PDF files need a login there, so
caracole never has them. The site's terms forbid bots, so reading it is your choice
(see [sources.md](sources.md)).

**Chord charts of jazz standards** come from iReal Pro's forum (forums.irealpro.com), for the songs
Ultimate Guitar and LaCuerda left without a sheet. A chart with your song's title counts when its
composer is your line's artist, or when its thread is named for the title and your artist. In the
forum's curated "Jazz 1460 Standards" thread the title is enough, so `Bill Evans - Autumn Leaves`
gets Kosma's standard. Anywhere else it isn't: `Ren - Patience` gets no Guns N' Roses chart. A
chart you pick under `[ireal]` always counts.

A line can name several artists, split at " / ", " & ", ", ", " and ", " with ", " feat. " or
" ft. ", and each one counts: `Thad Jones & Mel Lewis - Groove Merchant` gets Thad Jones's chart. A
one-word name among them is matched as a surname, so `Simon & Garfunkel` meets Paul Simon's chart.

caracole reads at most three thread pages per song and keeps the chart as `sheet.txt` and
`sheet.json`. A chart has no words, so a sheet from Ultimate Guitar or LaCuerda that covers the
lyrics replaces it, unless you picked the chart. `caracole ireal --index` and the nightly run read
the forum's playlists into the local index, so a song can meet a chart whose thread isn't named for
it.

The commands for these sites are in [One step at a time](#one-step-at-a-time).

**Model files** for auto-chords come from `[autochords]`, else from the environment variables the
block names. The `autochords` package sets those variables to the files it ships, so set the keys
only to use other files.

## What caracole prints

Every command writes its report on stdout and its log on stderr, so `caracole run > night.txt`
keeps the report alone. The options that set how much the log says come before the command
(`caracole -v run`):

| Option | The log on stderr |
|---|---|
| none | warnings and errors |
| `-q`, `--quiet` | the same; `caracole run` also cuts its summary down to what needs you and what went wrong |
| `-v`, `--verbose` | also caracole's own information, such as a line per request: `LRCLIB GET https://lrclib.net/api/get?… → 503 Service Unavailable in 0.21 s (1 of 200 requests)` |
| `-vv` | also debugging lines, and the logs of the libraries caracole uses (httpx, httpcore, numba, torch) |

A warning starts with `warning:` and an error with `error:`, coloured on a terminal unless
`$NO_COLOR` is set. Under systemd, each line starts with its journal priority instead
(see [deploy.md](deploy.md#logs)).

While a long command works, it says how far it is, on stderr. On a terminal that is one line,
rewritten in place: the run's step, the requests sent against the site's budget, the pages or songs
done, and the time left. The budget is the most a step may spend, so its time is the most it may
take:

    [6/20] lyrics · LRCLIB · 37 of up to 200 requests  up to about 1 min left

In the journal the same line comes at most once a minute, and `caracole run` adds a line as each
step starts and ends. A step that doesn't run has its one line:

    [6/20] lyrics…
    [6/20] lyrics · LRCLIB · 120 of up to 200 requests  up to about 1 min left
    [6/20] lyrics: 12 found, 3 missing, 0 instrumental, 0 errors (1 min 32 s)
    [7/20] megalobiz: skipped: megalobiz is off ([providers.megalobiz] enabled = false)

An upgrade of the database by a newer caracole logs one line as it begins, and so does a caracole
that waits for another's to end: `Upgrading the database from schema 16 to 17 (a copy first:
caracole.sqlite.v16.bak)…`. The journal keeps it, and `-v` shows it on a terminal; at the default
verbosity a terminal shows no such line.

`-q` shows none of it. `-v` shows the minute lines and the step lines among its request lines,
and no live line. `caracole run`, `fetch`, `render`, `ug --directory`, `youtube` and the passes of
`lyrics`, `lacuerda`, `gtptabs`, `harptabs`, `gametabs`, `ireal` and `musescore` say how far they
are this way; so do `transcribe` and `youtube --sheet`, a long stage's line (`Vocals · 2 of ~12
min`). Their report on stdout is as it was. The progress only counts: it changes no pause.

Each build of the library page logs one line. `-v` shows it, and the journal keeps it by default
(`journalctl -u caracole-web | grep 'library page'`):

    library page served to lenovo:8737: 120 songs (100 found, 15 wanted, 5 ignored; 3 in review), 2 songbooks; database /var/lib/caracole/caracole.sqlite, 12,582,912 bytes, modified 2026-10-29T03:14:07Z; 0.84 s

A page with no songs, or a database that can't be opened or read, logs a warning instead. It says
what to check: the database's path, size, owner and schema version, the folders, and the user
caracole runs as. The page is still served.

A bug in caracole ends the command with exit status 1 and a traceback on stderr.

## Say what you want to learn

### wanted.txt

`wanted.txt` is caracole's one source of songs. It sits in the library folder, so Syncthing carries
it to your laptop and phone and you can edit it anywhere. One song per line:

    Artist - Title
    Artist - Title | Album
    Artist - Title | m:ss
    Artist - Title | Album | m:ss

For example:

    # the songs I'm learning
    宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Soda Stereo - De Música Ligera
    Radiohead - Creep | Pablo Honey | 3:58

- The album and the duration are optional. Either one makes the lyrics lookup exact. A duration is
  `m:ss`, `h:mm:ss` or whole seconds.
- The artist ends at the first " - " (an en or em dash works too), so a title may contain " - "
  but an artist can't.
- A version after the title asks for that version, as in `Radiohead - Creep - Acoustic` or
  `Soda Stereo - Té Para Tres (En Vivo)`. UG versions labelled the same way rank higher
  (`variant_bonus`).
- `#` starts a comment, at the start of a line or after a space. Write `\#` for a `#` in a name
  (`John Lennon - \#9 Dream`) and `\|` for a `|`.
- An album named like a number needs an empty field after it: `Adele - Someone Like You | 21 |`.
- If a song is on two lines, the first counts. A later line only fills in an album or a duration
  the first leaves out.

Edit a line and the next sync changes the song. An album or duration you take off the line comes
off the song. Deleting the line doesn't delete the song. To stop all work on a song, put it under
`[ignore]` in overrides.toml. To take it out of caracole, files and all, run
[`caracole remove`](#caracole-remove).

A line caracole can't read is reported, and the other lines still count. The file must be a regular
file: a symbolic link is refused (`wanted.txt: not read: … is a symbolic link …`), and the to-do
page says so too.

Songs are handled newest first, so a song you add today is looked for tonight.

### caracole add

    caracole add ARTIST TITLE [--album ALBUM] [--duration M:SS] [--lacuerda URL]
    caracole add "ARTIST - TITLE"

`caracole add` appends the line for you, syncs the file and rewrites `_todo.md` and `index.html`.
One text is read as [below](#one-text-read-as-a-songs-name).

    $ caracole add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    Added 宋冬野 - 斑马斑马 to wanted.txt; the next `caracole run` looks for it.
    Not in the offline Ultimate Guitar index under this name: `caracole search` with a few of its words looks wider.

The first line says what it did. A song already listed "is in wanted.txt already" and isn't added
twice: edit its line to change its album or duration. For a song the library knew, it says what
the library has ("with a sheet", "with no sheet yet", "ignored by overrides.toml"). A song you
[removed](#caracole-remove) comes back as new. `caracole -v add …` also prints the line's number
and the song's key in the library.

Then it matches the song against the offline index, as the nightly match step would
(see [caracole match](#caracole-match---dry-run)). It says what it matched (`On Ultimate Guitar:
radiohead/creep (exact)`), or that the index has nothing under that name, or it lists the
candidates it isn't sure of:

    Not sure which Ultimate Guitar song it is. Did you mean:
      1) 94  misc-musicals/epic-the-musical-not-sorry-for-loving-you (catch_all)  https://tabs.ultimate-guitar.com/tab/…
      2) 82  bill-fox/im-not-over-loving-you (title_only)  https://tabs.ultimate-guitar.com/tab/…
    Pick one with `caracole review`, or on _todo.md.

Nothing is matched while the index is empty (run `caracole index build`) or overrides.toml can't be
read. `caracole search --add` matches and reports the same way.

The line is written first, before `caracole add` waits for another caracole to finish. If the
database can't be updated, the line is kept, a warning says why, and the next sync adds the song.
The first `caracole add` creates the file, with a header that explains the format.

`--lacuerda URL` picks the song's sheet on LaCuerda. Give the song's page
(`https://acordes.lacuerda.net/estopa/como_camaron`) or one of its versions
(`…/como_camaron-2.shtml`), as `caracole search` prints them. The pick goes under `[lacuerda]` in
overrides.toml (see [overrides.toml](#overridestoml-your-decisions)), and the nightly run keeps
that sheet whatever the song's language. Any other address is a usage error (exit 2), with nothing
written. If caracole's lock file can't be opened, the command exits 1 with the line written and no
pick.

A song needs its artist. Given one text that doesn't say who the artist is (`caracole add
Wonderwall`), `caracole add` writes nothing and exits 2. It lists your songs with that title and
the first five hits of `caracole search Wonderwall`. Each hit scoring 90 or more comes with its
`caracole add "Oasis" "Wonderwall"` line, and `caracole search "Wonderwall" --add N` adds a hit by
its number. No site is asked who sang a title.

An artist such as "misc", "unknown" or "Various Artists" is nobody's name. `caracole add misc 斑马`
adds the line, but warns that caracole may never find the song.

### One text, read as a song's name

`caracole add TEXT`, `caracole get TEXT` and every form of `caracole serve` read one text the same
way, so the same text gives the same names everywhere. So do `POST /request` and `POST /lookup`
sent one text as `q`. Two arguments (`caracole add ARTIST TITLE`) are the names themselves and are
never read.

First, what a video's title adds is dropped: brackets such as "(Official Video)" or "(Letra)", a
last part such as "… | Official Video", format words such as "HD" or "4K", and quotes around the
text. "(feat. …)" and "(En Vivo)" stay. Lyric channels' brackets go too: their own words, as in
"【動態歌詞Lyrics】", "【中文字幕】" or "(官方完整版MV)", and a line of the lyrics quoted in 「」 or
『』: one that ends as a sentence, or a long one. A short quote is a title and stays:
"宋冬野「斑马，斑马」". So is one that ends as a sentence, or a long one of Latin words, right
after the channel's name or a known artist: "Aimer「どうして？」" and "Live「Lightning Crashes」"
from their channels, never "晴天「为什么？」" from 周杰倫's. A quote left alone once the video's
brackets go is the title: "「夜に駆ける。」(Official Video)". A bracket of a version's or a tag's
words alone, such as "【Live】", "【现场版】" or "【翻唱】", is never the title. After the song's name
it stays: "周深 大鱼【Live】" is "大鱼【Live】". At the start it is the upload's and goes: "【翻唱】大鱼"
is "大鱼". Then the first rule that fits names the song:

1. **Artist - Title.** The first dash with a space on each side splits them. An en or em dash, "|",
   "~", "//" and "_" work too. "Muse - Hysteria - Live" is "Hysteria - Live" by Muse. The two are
   swapped when only the second part is a known artist, as in a fan's upload. A part's brackets
   of 【】《》「」『』〈〉 are left out of it: "【翻唱】周深" is 周深. A part that is only brackets is
   the first one's words: "《消愁》" is 消愁, and so are "《消愁》 Live" and "《消愁》 by".
2. **A title in brackets.** With no mark, the first of those brackets is the title. The words
   before it are the artist, and what follows it is left out: "米津玄師 MV「Lemon」" is "Lemon" by
   米津玄師. When those words begin with the channel's name or a known artist and go on, they are
   the title: "陈奕迅 孤勇者《英雄联盟：双城之战》" from 陈奕迅's channel is "孤勇者". With no words
   before it, the words after it are the artist: "《孤勇者》陈奕迅", or "《孤勇者》 by 陈奕迅", unless
   they are only tags or a video's words: "《孤勇者》 Cover" names no artist, and "《孤勇者》 Piano
   Cover by Jane" names Jane. A band named "By …"
   before the bracket keeps it: "By Divine Right「Song」".
3. **A known artist first, or after "by".** "silvana estrada que problema" or "Que problema by
   Silvana Estrada", once caracole knows her. A known song title is left whole: "Love Me Tender" is
   not "Me Tender" by Love.
4. **A video's channel.** A pasted video's title that names no artist is its channel's song:
   "Creep" from "Radiohead - Topic" is Radiohead's.
5. **The video suggested for a search.** When YouTube's first video for a query is that very song,
   its artist is used: "creep" is Radiohead's "Creep".

If no rule fits, the text doesn't say who its artist is, and it is never cut at its first space. A
command lists the songs of that name and exits 2. A page fills the text in as the title for you to
finish. `/request` and `/lookup` refuse it.

A known artist is one from your library, from a video's channel, or from the local indexes of
Ultimate Guitar, LaCuerda, gtptabs.com and harptabs.com. No site is asked. A one-word name needs
more proof, such as five songs in an index or two in your library. So one mistaken line, "Silvana -
Estrada", doesn't make "Silvana" an artist.

The commands say how they read a text, unless that is the text as written:

    $ caracole add "Silvana Estrada – Que problema"
    Read “Silvana Estrada – Que problema” as Silvana Estrada - Que problema.

### caracole get

`caracole get "ARTIST - TITLE"` (or `caracole get ARTIST TITLE`) is for the song you want to play
now. It does the nightly run's work for that song alone, sheet first, and says where the sheet is
the moment it is kept:

    $ caracole get "Radiohead - Creep"
    Song: added to wanted.txt, line 16.
    Match: matched to radiohead/creep.
    Sheet: tab 4169 from UG: /home/you/Tabs/Radiohead/Creep/sheet.txt, readable after 2.1 s.
    PDF: /home/you/Tabs/Radiohead/Creep/sheet.pdf
    Lyrics: found.
    Ultimate Guitar: sheet 4170 · tab 4172 · kept beside it: tab 4169, tab 4171.
    gtptabs.com: Guitar Pro file downloaded.
    Done in 9.4 s: 8 asks (Ultimate Guitar 5, LRCLIB 1, gtptabs.com 2).

One text is read as [above](#one-text-read-as-a-songs-name). One that doesn't say who its artist is
(`caracole get Wonderwall`) looks nothing up and exits 2. Like `caracole add`, it lists the songs
with that title, each hit scoring 90 or more with its
`caracole get --ug oasis/wonderwall "Oasis - Wonderwall"` line.

The stages, in order:

1. **Song.** A song the library has is used as it is. Any other is added to wanted.txt as
   `caracole add` adds it, one you [removed](#caracole-remove) included.
2. **Match**, against the offline index.
3. **Sheet.** A sheet you picked comes first (`--lacuerda`, `--ireal`). Otherwise, or when your
   pick can't be had now, the best rated chords version on Ultimate Guitar is kept at once, in one
   or two requests, and the stage says why your pick isn't the sheet. Without a sheet from Ultimate
   Guitar, LaCuerda is asked, for a song it would be asked about tonight, then iReal Pro's forum,
   for a song its index has a chart of. From here on you can read the sheet.
4. **PDF**, as `caracole render` makes it.
5. **Lyrics**, from LRCLIB, then Megalobiz and AZLyrics for what it lacks.
6. **Ultimate Guitar again.** The top sheets are scored against the lyrics. A more complete one
   replaces the first, and the others are kept beside it
   (see [caracole versions](#caracole-versions)). Then the text tab.
7. **The other sites**, from their local indexes: LaCuerda for a Spanish song without a complete
   sheet, gtptabs.com for a Guitar Pro file, harptabs.com for a harmonica tab and gametabs.net for
   a tab of game music.
8. **Pages.** `_todo.md` and `index.html`, the PDF again if the sheet changed, a page for each
   harmonica tab, and MuseScore's pages matched from its local index.
9. **Songbooks.** Each songbook that lists the song is made again, as `caracole songbook render
   NAME` does. A songbooks.toml that can't be read is reported on that line and stops nothing.

The options that pick something record the pick in overrides.toml.

| Option | What it does |
|---|---|
| `--print` | Prints the sheet as soon as it is kept, and again when a better one replaces it. |
| `--ug ARTIST-KEY/SONG-KEY` | The Ultimate Guitar song to use, as `caracole search` shows it (`stone-temple-pilots/creep`). It is recorded under `[match]`, so the matcher never asks you about it. |
| `--tab URL` | The Ultimate Guitar tab to use, by its page's address or its id. It is recorded under `[pin]`, where it replaces the song's pin of the same kind (a chords or ukulele chords sheet, or a text tab) and leaves a pin of the other kind. A page of another type, such as a Guitar Pro file's, is refused before anything is written. |
| `--lacuerda URL` | The LaCuerda sheet to keep, by its song's page (its best Letra y Acordes version) or a version's page. It is recorded under `[lacuerda]` and stays the sheet whatever its language or its coverage of the lyrics, unless a `[pin]` names an Ultimate Guitar sheet. The song still gets Ultimate Guitar's text tab. |
| `--ireal URL` | The iReal Pro chart to use, by its thread's address, with `#post-N` for one post's. It is recorded under `[ireal]`. |
| `--harptabs URL` | The harptabs.com tab to keep, by its page's address. It is recorded under `[harptabs]` and kept beside the song's other harmonica tabs, never in place of one. |
| `--gametabs URL` | The gametabs.net tab to keep, by its page's address. It is recorded under `[gametabs]`. |
| `--album ALBUM`, `--duration M:SS` | For a song new to the library, as in `caracole add`. |
| `--no-songbooks` | Leaves the songbooks that list the song as they are. |
| `--progress` | Adds a JSON line per stage, which `caracole serve` reads. |

`caracole get` keeps the lookup pace (Two paces, under [Configure](#configure)): about a quarter
of a second between two requests to a site, six requests to a site at most, and sixty an hour for
all lookups together. A site cooling down after a block is left alone. A block, a spent budget or a
site's error leaves the song to the nightly run, never marks it not found, and exits 0.

A nightly run that holds caracole's lock lets the lookup go first at its next pause
([One caracole at a time](#one-step-at-a-time)). Two lookups at once take turns, so each site still
gets one request at a time.

A lookup exits 1 and fetches nothing for a song ignored in overrides.toml or one wanted.txt can't
hold. It also exits 1 when another caracole removes or merges the song meanwhile (`Nothing fetched:
Radiohead - Creep left the book during this fetch …`).

A song the matcher isn't sure of gets everything but its Ultimate Guitar sheet. Pick its UG song
with `--ug`, with Fetch on the page of `caracole serve`, or with `caracole review`.

### caracole versions

Ultimate Guitar keeps several chords versions of a song (Wonderwall has 13). caracole keeps the
three it scores against the lyrics: the best as `sheet.txt`, and the other two beside it as
`version-<tab>.txt` (see [the library folder](#the-library-folder)). `caracole versions "ARTIST -
TITLE"` lists them all. It only reads, so it sends no request and never waits for another caracole.

    $ caracole versions "Oasis - Wonderwall"
    Oasis - Wonderwall: 13 chords versions on Ultimate Guitar; the title opens tab 1064463, caracole's pick.
      Ver 3 of 13 · 4.86★ (408) · tab 1064463 · kept · the one · the version that oasis play on Wembley 2008
      Ver 5 of 13 · 4.91★ (95) · tab 1213325 · 40% of the lyrics · kept
      Ver 2 of 13 · 4.62★ (1,240) · tab 6624
      …

Versions that cover the lyrics come first, by the rating weighed by its votes. Those never scored
come next, and those Ultimate Guitar took down last. A song whose sheet is one of UG's Ukulele
Chords lists those versions instead. When the sheet is LaCuerda's or auto-chords', the first line
says so and no version is the one.

| On a line | Meaning |
|---|---|
| `the one` | the version the song's title opens |
| `kept` | kept in the song's folder |
| `kept: the sheet's very text` | its text is the sheet's, so the sheet stands for it |
| `40% of the lyrics` | the share of the lyrics it covers, when it falls short |
| `gone from Ultimate Guitar` | UG took it down; its files go at the song's next fetch |

| Option | What it does |
|---|---|
| `--keep TAB` | Keeps one more version beside the sheet, now, for one request at the lookup pace. TAB is the tab's id or its page's address. The version is written as `version-<tab>.txt` and `.json`, with its viewer page, and stays kept while Ultimate Guitar has it and you don't `[block]` it. A version whose text is the song's text tab (`tab.txt`) isn't kept. |
| `--keep-more` | Keeps the versions not kept yet, in the list's order, until the lookup's six requests or the hour's sixty are spent. It says how many are left, so run it again for the rest. It passes over versions under `[block]`, those Ultimate Guitar took down, and those it found it can't keep. |
| `--choose TAB` | Makes a version the sheet. It is `caracole get --tab` for that version, so it is recorded under `[pin]`, and the PDF, the viewer and the songbooks use it. caracole's top versions stay kept beside it. |
| `--clear` | Takes the song's chords pins out of `[pin]` (a text tab pin stays) and looks the song up again. caracole's pick is the sheet once more, and a version you had chosen outside the top three leaves the folder. |
| `--progress` | Adds a JSON line per stage, for `caracole serve`. |

A block, a spent budget or a site's error stops a keep, says so and exits 0. A tab that isn't one
of the song's chords versions, one Ultimate Guitar took down, or a song not in the library exits 1.
Two of `--keep`, `--keep-more`, `--choose` and `--clear` at once exit 2.

### caracole remove

`caracole remove "ARTIST - TITLE" [--yes]` takes a song out of caracole for good. Nothing brings it
back until you ask for it again. Name the song as the to-do page and `caracole search` do. It says
what goes and what stays, then asks:

    $ caracole remove "Radiohead - Creep"
    Remove Radiohead - Creep from caracole?
    It takes:
      - its line in wanted.txt (line 3)
      - 6 files caracole wrote in Radiohead/Creep/: info.json, lyrics.txt, sheet.cho, sheet.json, sheet.pdf, sheet.txt
      - its record in caracole's database: its match, its lyrics and 4 versions seen of it
    It leaves:
      - Radiohead/Creep/notes.md: caracole didn't write it
    Remove it? [y/N]: y

`--yes` (`-y`) doesn't ask. Without it and without an answer (from a script, say), nothing is
removed and it exits 1.

It takes every line in wanted.txt that names the song, the files caracole wrote in the song's
folder, the folder once empty, the song's record in the database, the audio caracole took from
YouTube for it, and the audio file you gave it (`caracole audio`). Syncthing then deletes the files
on every device. It leaves:

- Any file caracole didn't write, such as a `sheet.pdf` or `lyrics.txt` you put where caracole
  made none. The command names each one.
- The audio you bought, in Music/.
- The song's entries in overrides.toml, which apply again if you ask for the song again.
- Its place in a [songbook](#songbooks). The songbook lists it as "not in the logbook" until you
  take it out (`caracole songbook remove`, or × on `caracole serve`) or ask for the song again.

The song then stays out: the nightly run and `caracole sync` don't bring it back. To bring it back,
as a new song, use `caracole add`, the web page's request form, or write its line in wanted.txt. A
device that syncs back an old copy of wanted.txt with the line in it brings it back too.

If wanted.txt can't be read (a symbolic link, say), nothing is removed, because the line left in it
would bring the song back.

`caracole remove --list` lists the songs removed, the latest first, and when. The command asks
before it takes caracole's lock, so the nightly run never waits for your answer.

On the web page, **Remove** in a song's card does the same. It says in one line what goes, counts
down five seconds with Undo, then removes the song ([caracole serve](#caracole-serve)). As it is sent the
card closes and the song's line alone waits; it says Removed for a moment, then leaves the list.

### Names in other scripts

Write a song as you know it, in its own script or in Latin letters. `宋冬野 - 斑马斑马`,
`宋冬野 - 斑馬斑馬` and `Song Dongye - Banma Banma` all work: caracole also compares Chinese as
pinyin, and Traditional characters as Simplified ones.

Ultimate Guitar often writes a non-Latin name in several scripts at once: the original, a
romanization and a translation. It calls 宋冬野 "Song Dongye (宋冬野)" and his song "斑马 斑马 Banma
Banma Zebra Zebra". caracole takes each part as a name of its own, so `宋冬野 - 斑马斑马` finds
that song, and so would "Banma Banma" or "Zebra Zebra".

Japanese, Korean and Cyrillic names come in the same patterns: "打上花火 (Uchiage Hanabi)", "봄날
(Spring Day)", "Кино (Kino)". caracole doesn't romanize those. They meet on the part in their own
script, or on the Latin one.

The same goes wherever caracole meets a name it didn't write: the offline index, a purchase's tags,
a Guitar Pro download's name, and a search. UG's sitemaps write names in Latin letters only, so
`DAOKO - 打上花火 (Uchiage Hanabi)` meets `daoko/uchiage-hanabi`.

A few limits keep wrong songs out. A part that only names a version ("Live", "Acoustic", "Remix"),
a number or a single Latin letter never makes a match on its own. Latin words before the original,
or glued to it, are part of the title: "Baby 对不起" is not 对不起. A duet's name, such as "Joey
Yung (容祖儿) & Eason Chan (陈奕迅)", is neither singer. A featured artist is not the artist: "Ma
Di (feat. 宋冬野)" is Ma Di's.

### caracole sync

`caracole sync` reads wanted.txt and prints a summary such as `wanted.txt 3 songs, 1 new`, then
each problem. Then it rewrites `_todo.md` and `index.html`. The nightly run starts with the same
sync.

`caracole sync`, `caracole add` and `caracole search --add` never fail because of the pages. With
an overrides.toml that can't be read, or a page that can't be written, they still add and sync your
songs and exit 0. They warn, and leave the pages as they were.

## The first run

With some songs listed:

    caracole index build       # once: Ultimate Guitar's sitemaps into a local index
    caracole match --dry-run   # how every song matches, saving nothing
    caracole run               # one nightly run, now

### caracole index build

caracole never uses Ultimate Guitar's search, which robots.txt closes to bots. It reads the sitemaps
UG publishes for crawlers into a local index of every chords, text tab and ukulele chords page, well
over a million of them.

The build reads the sitemap index and its 45 tab sitemaps, one request at a time, 2.5–5 seconds
apart. That is about 46 requests, 80 MB and 4 minutes. Its budget is 100 requests, so one build is
enough. It prints a line per sitemap, then what the index holds:

    [1/5] sitemap1.xml  2,000 tabs: 1,315 indexed, 221 bare ids, 454 of other types, 10 closed by robots.txt  4 left, about 15 s
    ...
    Index built: 5 sitemaps read; 5,708 new tabs.
    The index is complete: `caracole match` can now match your songs against it, and the nightly run keeps it up to date.

Each line counts what the index leaves out:

- Tabs of other types, Guitar Pro and Power Tab files among them. caracole uses none of UG's, so a
  song UG has only as one of those is not found there.
- Tabs whose page robots.txt closes to bots (`/tab/track/…` and a few more).
- Bare ids. About a tenth of UG's tabs are listed as `/tab/1234567`, with no artist or song in the
  address. They include every tab of an artist with an accented or non-Latin name, such as Joaquín
  Sabina or 宋冬野. Only the artist's page leads to them. [The to-do page](#the-to-do-page) asks
  you once for that page, unless [UG's artist directory](#ugs-artist-directory) has found it.

UG's Ukulele Chords (about 150,000 pages, in `sitemap_ukulele1.xml` to `sitemap_ukulele4.xml`) are
indexed too. A song with no chords on UG takes its sheet from them (see
[caracole fetch](#one-step-at-a-time)).

If the build stops part-way, it keeps the sitemaps read so far and says how to resume. Until a
refresh has read the rest, the index is incomplete and no song is matched against it. The build
exits 130 on Ctrl-C, 0 on a block, a cooldown or a spent budget, and 1 on any other error.

    The index is partial: 12 of 41 tab sitemaps indexed, so no song is matched against it yet.
    To resume, run `caracole index refresh` after 2026-10-20 22:54 UTC: it reads the 29 sitemaps left, sitemap13.xml to sitemap40.xml and sitemap_last.xml (30 requests, about 2 min). The nightly run does the same.

#### caracole index build --from DIR

Builds the index offline, from sitemap files you already have: `sitemap1.xml` to `sitemap40.xml`,
`sitemap_ukulele1.xml` to `sitemap_ukulele4.xml` and `sitemap_last.xml`, gzipped or not. It sends no
request. The 41 files of guitar tabs take about 22 seconds and make a 303 MB database.

A file that isn't a sitemap stops it with exit status 1. The files before it are kept, and running
it again reads every file again.

#### caracole index refresh

Re-reads `sitemap_last`, the highest-numbered sitemap of each kind (`sitemap40.xml`,
`sitemap_ukulele4.xml`) and any tab sitemap not indexed yet, such as those a stopped build left.
These are conditional requests, which usually answer "unchanged". A new tab for a song you want
marks that song to be fetched again. The nightly run does this for you.

    Index refreshed: 1 of 2 sitemaps changed (sitemap_last.xml): +231 tabs, no song to refetch. 3 requests, 45 s.

Once it has read what a stopped build left, that line ends with "the index is now complete".

#### caracole index stats

Prints the number of tabs of each type, of artists and of sitemaps, the newest tab id, and when the
index was built and last refreshed. Then it says how far each other index has got, once that index
is started: UG's artist directory, harptabs.com, gametabs.net and iReal Pro's forum. Each line names
the command that reads the rest:

    harptabs.com: 1204 of 10428 artist pages read, 5130 tabs; caracole harptabs --index reads the rest.

To move an index into another database, see
[caracole index export and merge](#caracole-index-export-and-merge).

### caracole match --dry-run

Matching is local. It sends no request and takes seconds. `caracole match` matches every song
against the index and prints a line per song, then the totals:

    accept     100.0  exact         Radiohead - Creep → radiohead/creep  CHANGED unmatched → accept
    review      88.9  fuzzy_title   Radio Head - Crep → radiohead/creep  CHANGED unmatched → review
    not_found      -  -             宋冬野 - 斑马斑马 → -  CHANGED unmatched → not_found
    3 songs: 1 accept, 1 review, 1 not_found; 3 changed. Dry run: nothing was saved.

The columns are the decision, the score, the step that decided it, and your song with the UG song it
matched. `CHANGED` marks a decision, or a UG song, that differs from the saved one.

`--dry-run` saves nothing, so you can try other thresholds (`[match]` in caracole.toml) or new
overrides on your whole library. Without it, `caracole match` saves the decisions and rewrites
`_todo.md` and `index.html`. On an incomplete index it saves nothing, says why and exits 1.
`--dry-run` still shows what matches so far.

| Decision | When |
|---|---|
| `accept` | A score of 90 or more, with the next different title at least 8 points behind. |
| `review` | Any other score of 75 or more, any match on the title alone (usually a cover), and any match at step 4 below. You settle these on the to-do page or with `caracole review`. |
| `not_found` | Below 75. The song is matched again every night, so a new tab finds it. |
| `pinned`, `ignored` | Set in overrides.toml. |

A song is matched in this order:

1. Your overrides: `[ignore]`, then `[pin]`, then `[match]`.
2. The title under each of the song's artists. An artist is tried as `[alias]` names them, then
   under their own name, also without hyphens (`AC/DC` meets `acdc`), with or without a leading
   Spanish article (Enanitos Verdes meets `los-enanitos-verdes`) and, for a Chinese name, in pinyin
   (宋冬野 meets `song-dongye`). An exact title wins, else the closest one.
3. The nearest other artist name, at 90 or more, then step 2 under it.
4. Names that aren't quite UG's, when steps 2 and 3 accept nothing. These are always a review. The
   table below has the three kinds.
5. The title alone, across all artists. This is always a review too.

| Step 4 | What it matches | Example |
|---|---|---|
| `word_title` | A title by the song's artist that holds yours word for word, or that yours holds. It scores 80 to 90. | `Los Lobos - Canción del Mariachi` meets `los-lobos/cancion-del-mariachi-morena-de-mi-corazon` |
| `typo_artist` | An artist whose name is one letter away (for a name of four to seven letters) or two (from eight). Two swapped letters count as one. | `Coldplya - Yellow` meets `coldplay/yellow` |
| `catch_all` | A song of a musical, film, TV show, game or cartoon. UG files those under `misc-musicals`, `misc-soundtrack`, `misc-television`, `misc-computer-games` and `misc-cartoons`, with the show's name in the title. | `epic - I'm not sorry for loving you` meets `misc-musicals/epic-the-musical-not-sorry-for-loving-you` |

A review keeps its five best candidates. The best `catch_all` and the best `typo_artist` candidate
are always among them. UG songs you rejected for a song under `[reject]` are never offered again.

Matching never asks a search engine. A fallback through a search API with your own key is designed
but not built ([web-search.md](web-search.md)).

### caracole run

`caracole run` is what the nightly timer starts. Its steps, in order:

| Step | What it does |
|---|---|
| sync | Reads wanted.txt. |
| icons | Fetches the icon of each site the library has something from, once. See [Where each file came from](#where-each-file-came-from). |
| index | Refreshes the index and marks the songs that have new tabs. |
| ug-directory | Reads what is due of [UG's artist directory](#ugs-artist-directory). |
| match | Matches every song again, locally. |
| lyrics, megalobiz, azlyrics | Ask LRCLIB for missing lyrics, then Megalobiz for timed ones, then AZLyrics for the songs still without any. See [Lyrics from LRCLIB, Megalobiz and AZLyrics](#lyrics-from-lrclib-megalobiz-and-azlyrics). |
| fetch | Ranks and keeps Ultimate Guitar sheets and text tabs. |
| lacuerda | Looks on LaCuerda for Spanish songs without a complete sheet. What is left of its budget reads LaCuerda's listings of every artist into a local index, then the pages of its most popular artists not read in 30 days, 10 a night at most. |
| ireal | Keeps a chart from iReal Pro's forum as the sheet of each song the sheet sites left with none. |
| scan | Links purchases in Music/ and files what you dropped into `_inbox/`. |
| gtptabs | Downloads a Guitar Pro file from gtptabs.com for each song that has none. A file you dropped into `_inbox/` comes first. |
| harptabs | Keeps a harmonica tab from harptabs.com for each song that has none. What is left of its budget reads artist pages, for searches. |
| gametabs | Keeps a text tab of game music from gametabs.net for each song that has none. What is left of its budget reads game pages, for composers. |
| musescore | Reads MuseScore's song sitemaps, for the to-do page's links. It downloads nothing. |
| youtube | Takes the audio of a few songs with no human sheet, for auto-chords. Skipped in a caracole without auto-chords. See [Audio from YouTube](#audio-from-youtube). |
| render | Writes ChordPro files and PDFs. |
| todo | Rewrites `_todo.md` and `index.html`. |
| backup | Copies the database into the state folder's `backups/` and keeps the last three, but only after a run in which no step failed. See [caracole backup](#caracole-backup). |

Every step runs even when an earlier one failed, so the to-do page is always rewritten. A block, a
cooldown or a spent budget is no failure. A bug is.

Until the index is built, the index, ug-directory and match steps are skipped. After a build that
stopped part-way, match is skipped until the index step has read the rest. The ireal, harptabs and
gametabs steps, and LaCuerda's listings, ask nothing while the library is empty.

#### The summary

The run ends with a short summary and sends the same words to ntfy. On a first night, with one song
in wanted.txt, no index yet and LRCLIB overloaded, it reads:

    First, build the index once: caracole index build (about 4 minutes).
    Until then, no song is matched or looked for on Ultimate Guitar.

    Songs: 1 in wanted.txt, 1 new.
    LaCuerda: 30 pages of artists read.

    1 thing on your to-do page needs you: /home/you/Tabs/_todo.md
    LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.
    Requests: Ultimate Guitar 0 of 60, LRCLIB 2 of 200, LaCuerda 30 of 30 (used up: the rest waits for the next run).
    Took 3 s.

It leads with the one thing that unblocks the rest, when there is one: build or finish the index, or
fix overrides.toml or wanted.txt. Then comes a line for each step that did something. A step with
nothing to do has no line, and neither has a site you turned off. Last come how many things on the
to-do page need you, each site's problems with its cooldown, the requests against each budget, and
how long the run took.

The summary is all `caracole run` prints on stdout. Its log, on stderr, shows only the problems the
summary doesn't already say, and while the run goes, where it is: a live line on a terminal, the
step lines in the journal. For `-v` and `-q`, see [What caracole prints](#what-caracole-prints).

#### Budgets

Each site gets a fixed number of requests a run, one at a time, with a random pause between two.

| Site | At most, a run | Pause |
|---|---|---|
| Ultimate Guitar | 60, the index refresh included | 2.5–5 s |
| gtptabs.com | 20 | 2.5–5 s |
| harptabs.com | 20 | 2.5–5 s |
| gametabs.net | 20 | 0.25 s. Its robots.txt asks for 5 s, which caracole doesn't keep. |
| iReal Pro's forum | 20 | 2.5–5 s |
| MuseScore | 10 | 2.5–5 s |
| YouTube | 6 yt-dlp runs | 3.75–7.5 s |

The lyrics sites and LaCuerda have budgets too. You set them all under `[providers.…]` in
caracole.toml (see [Configure](#configure)). Here is where the requests go:

- Ultimate Guitar: the sheet of every waiting song first, newest songs first. A sheet takes a few
  requests: the song's versions pages, then up to three sheets scored against the lyrics. What is
  left goes to text tabs, about a page a song. A long list fills in over a few nights.
- gtptabs.com: per song, its artist's page and a download. The page serves every song by that
  artist for 30 days.
- harptabs.com, gametabs.net and iReal Pro's forum: a few pages a song, usually one or two. What is
  left reads about 15 artist pages a night on harptabs.com, about ten game pages on gametabs.net,
  and the forum's other playlists, about six pages.
- MuseScore: its song sitemaps only, an index and 18 files, read over two nights.
- YouTube: a search and a download per song, so three songs a night. Inside a run, yt-dlp waits half
  a second between its own requests and 2.5–5 seconds before a download.

A site's sitemaps cost a few requests on the first run, and again every 30 days: seven for
gtptabs.com and gametabs.net, nine for iReal Pro's forum with its Jazz 1460 Standards, one for
harptabs.com.

[UG's artist directory](#ugs-artist-directory) has a budget of its own (`[ug_directory]`), with
several requests in flight and no pause. Its first read takes about an hour.

#### Blocks and errors

A block is an HTTP 403 or 429, or a challenge page such as MuseScore's Cloudflare one. It stops that
site for the rest of the run and sends one ntfy message, which says until when caracole leaves the
site alone.

The cooldown counts from the start of the blocked run: 24 hours, doubled for each further block in
a row, plus 2 hours. That is 26 hours after a first block, 50 after a second and 98 after a third,
so the nightly runs skip the site for one night, then two, then four. An answer without a block ends
the streak. Nothing but errors doesn't.

A block in a command counts the same way and sends an ntfy message too. A lookup (`caracole get`,
`lacuerda --artist`, `harptabs --artist`, `ug --link`) sends none and tells you where you asked.
Only the first block of a streak sends a message. After three in a row, the Sites tab and the to-do
page's Provider health say so. For a site you can turn off, they add that
`[providers.<name>] enabled = false` in caracole.toml stops caracole asking it. caracole never works
around a block: no proxies, no retries from elsewhere.

Errors are never misses. No block, spent budget or other error from a site marks a song not found
or its lyrics missing. The song waits for the next run.

- A cached answer that won't read is asked for once more, past the cache.
- A tab page UG keeps serving without its data is asked for again after 7 days, then twice as long
  each time, up to 90 days. Meanwhile the song is filled from its other versions.
- caracole never asks for a page robots.txt closes to bots, and never follows a redirect to one. A
  tab at such a page is no candidate. [sources.md](sources.md) has the rules.

#### Exit status

| Status | When |
|---|---|
| 0 | The run did what it could. A block, a cooldown, a spent budget or a site's errors don't change that. |
| 1 | A bug, reported after all the steps have run so that systemd's `OnFailure` can tell you. The summary names the step and the log has its traceback. Also an overrides.toml caracole can't read, or a database it can't open. |
| 2 | A caracole.toml it can't read, or a database a newer caracole migrated. |

A broken overrides.toml stops the run before its first step, because every step reads it. The to-do
page is still rewritten, leading with the error. ntfy gets the same words, and index.html is left as
it was.

## One step at a time

Like `caracole sync`, `caracole index refresh` and `caracole match` above, each step of the run has
a command of its own, with the run's budgets, cooldowns and cache. Unless a command says otherwise:

- A cooldown, a block or a spent budget exits 0.
- A site you turned off is asked nothing, and the command says so.
- A site's sitemaps are read into a local index when they never were, and again after 30 days. A
  spent budget leaves the rest for the next run.
- A song the site doesn't have is asked about again after 30 days. A song that met an error is tried
  at the next run.
- caracole never uses a site's own search or API. `caracole lacuerda --search` is the one exception.
- A file caracole kept is never replaced by another download.
- `--progress`, where a command takes it, prints a JSON line per event for `caracole serve`.

Three commands take `--index [--budget N]`: `harptabs`, `gametabs` and `ireal`. With it they read
the site's pages into its local index instead, for searches, even for an empty library. They ask at
the bulk pace with a budget of their own, `--budget N` requests, 100 by default, and go on where the
last pass stopped. A page that answers 404 loses its entries (`1 gone`). A page that won't parse, or
any other error, leaves the index as it was. The command holds caracole's lock while it runs, so a
nightly run waits for it: give it a budget that ends before night. `--budget` goes with `--index`
alone (exit 2).

### caracole lyrics

Asks LRCLIB for the lyrics of every song that has none, and again for misses older than 30 days. It
writes `lyrics.txt`, plus `lyrics.lrc` when LRCLIB has timed lyrics. A song whose lookup failed
stays pending.

LRCLIB's 503 means it is busy, not that it has no lyrics. caracole asks once more after the wait its
`Retry-After` names, up to 30 seconds. A second 503 leaves the song pending.

Then it asks Megalobiz for the songs LRCLIB left, and AZLyrics for those still without any (see
[Lyrics from LRCLIB, Megalobiz and AZLyrics](#lyrics-from-lrclib-megalobiz-and-azlyrics)):

    Megalobiz: 1 found, 2 timed, 3 missing, 0 errors
    AZLyrics: 1 found, 2 missing, 0 errors

    caracole lyrics --song "ARTIST - TITLE" --as "ARTIST - TITLE"

Lists what the three sites have under a name you type, for a song whose own name finds nothing
there (a video's decorated title, a transliterated artist). caracole serve's library page does the
same from the song's card (see [Lyrics under another name, from a
card](#lyrics-under-another-name-from-a-card)). The song must be in the book and not
ignored. The name is noted first as the song's `[lyrics]` `as`, so later nights ask under it too;
typing the song's own name takes it out. Then each site is asked once, now, at a lookup's pace:
LRCLIB's search (and its exact match, with the audio's length, when nothing it lists fits),
Megalobiz's search, and AZLyrics' page of the artist you typed (never for a name with no Latin
letter). That is 2 to 4 requests. The same name again within 7 days answers from the cache with
none; after that the sites are asked again, so a record they added since is listed. Nothing of the
song's lyrics changes.

    Asked as 孟维来 - 野人 (its audio is 3:45); noted under [lyrics].
     1. LRCLIB     孟维来 - 野人 · 野人 · 3:46 · timed · best fit
     2. Megalobiz  (no artist) - 野人 · 3:45 · timed
    AZLyrics: no artist page for 孟维来.
    2 records marked instrumental aren't listed.
    Take one: caracole lyrics --song '孟维来 - 野人『…』' --pick 1
    Searched: LRCLIB and Megalobiz list 2 records for “孟维来 - 野人”.

The best fit is the record the nightly passes would keep, then the records that fit the name, then
the rest, 40 at most; a record more than 10 s off the audio says its gap ("4:31, audio 3:45").
Instrumental records are counted, never listed. A site cooling down, out of its asks, blocking or
failing is said and the others are listed; with no rows the last line is then `Not searched: …`,
never `Nothing found`. A site turned off is said and left out: the others answering none is
`Nothing found`. The list is kept for 7 days to pick from, until the song's next search. After
that only the name asked and the day are kept (the nightly run drops the rows), so the card says
`Asked as “…” on DD/MM/YY: over a week ago. Search again to pick one.`
`--song` and `--as` go together (exit 2); a song not in the book or ignored exits 1. A name that
changes the one kept is a new question for a song with no answer yet: a song pending or missing has
the sites' earlier misses forgotten and is pending again, so no transcription is offered until every
site has answered under the new name. Found lyrics and an instrumental verdict stay as they are; a
pick replaces them. A search changes no stored lyrics.

    caracole lyrics --song "ARTIST - TITLE" --pick N
    caracole lyrics --song "ARTIST - TITLE" --record SITE:ID

Makes row N of the song's last search (or the row that lists `SITE:ID`, such as `lrclib:28399373`)
its lyrics, now, in place of whatever it had. Only a record that search listed can be taken, and only
within its 7 days. LRCLIB's record comes from the search's own answer in the cache, with no request
(one when the cache lost it); Megalobiz's and AZLyrics' cost one request each, at a lookup's pace.
The record is noted under `[lyrics]` (its `as` kept) once the lyrics are written. A song with its
audio gets its auto sheet made, or made again, over the new words at once where auto-chords is
installed; otherwise tonight's run makes it (a chart already made takes the words as plain lyrics
meanwhile). A song with a human sheet gets its lyrics and its page, no chords. It says each stage:

    Lyrics: timed lyrics from LRCLIB: 孟维来 - 野人 (野人, 3:46); in place of AZLyrics' plain lyrics.
    Chords: chords over the lyrics.

A record with no lyrics now keeps nothing. A site cooling down, out of its asks, blocking or failing
keeps nothing and changes nothing: the song, its `[lyrics]` and its records stay as they were, and it
exits 0 (`No lyrics kept: …`). A refusal (the song not in the book or ignored, no search, one over a
week old, a record it didn't list) exits 1, and so does a failure here: overrides.toml that can't be
written or lyrics that can't be (nothing is then changed, though lyric files that couldn't be put
back are said to hold the new words), an info.json, a chords failure or a PDF that can't be made (the
lyrics stay kept: `Lyrics kept; the job failed after: …`). `--progress` adds a JSON line per stage, for
caracole serve. A pick cut off between noting the record and storing its lyrics (the machine stopped)
leaves the record noted and the old lyrics stored: pick it again.

    caracole lyrics --song "ARTIST - TITLE" --clear

Takes the record you picked out of `[lyrics]`, keeping its `as`, with no request. The lyrics that
record gave go with it (its auto sheet is made again at the next run), the sites' earlier misses are
forgotten and the song is pending, so tonight's run, or a lookup, asks every site again under the
name that holds. A song with no record picked exits 1 ("nothing to clear"). `--pick`, `--record`,
`--clear` and `--as` go one at a time (exit 2), and `--progress` only with `--pick` or `--record`.
Each takes caracole's lock as asked for now, so a nightly run lets it in at its next pause.

### caracole fetch

    caracole fetch [--song "ARTIST - TITLE"]

Fetches and ranks the UG versions of the songs that need it: new matches, songs with new tabs or a
changed `[block]`, songs a run left half-done, and songs whose kept sheet or tab the library lost.
First it scores, with no request, the sheets kept before their lyrics arrived. Per song it prints
what it kept, or `nothing kept`, then the totals:

    Artist - Title: sheet 101 · tab 402 (3 requests)

The other versions it scores are kept beside the sheet as `version-<tab>.txt` and
`version-<tab>.json` (see [the library folder](#the-library-folder)). They follow the ranking. A
version that leaves the top `scored_sheets`, that UG took down or that you `[block]` loses its files
at the song's next fetch. A version you keep with
[`caracole versions --keep` or `--keep-more`](#caracole-versions) stays. A pinned sheet keeps the
top versions by rating beside it. A song whose UG match was undone (by `[reject]`, say) loses the
sheet, the tab and the versions that match kept.

A song UG has no chords for takes its sheet from UG's Ukulele Chords versions. Its files are
labelled "Ukulele Chords" on the library page. A chords version found later replaces it. You can
`[pin]` a ukulele version as you pin a chords one.

Songs the index can't settle are looked up on their artist's UG page, when it is known, at most once
in 30 days. Those are songs not found, songs in review on their title alone or on names that aren't
quite UG's, and songs whose chords the index can't offer (bare ids, or pages robots.txt closes).
Every list read on an artist's page is kept for searches.

`--song` fetches that one song now, even when nothing about it changed. The song must be matched,
or be one of the songs above with its artist's page known. It prints that song's line alone, or why
nothing came: `not fetched (the error); it waits for the next run`, a spent budget, or UG's
cooldown. `-v` adds the requests, the count and the totals.

### caracole lacuerda

    caracole lacuerda [--index | --artist NAME | --search QUERY [--auto] [--progress]]

Looks on LaCuerda for Spanish songs that have no complete sheet, at most once in 30 days per song.
A song counts as Spanish by its lyrics, or by its title until it has lyrics. LaCuerda's sheet is
kept when there is no sheet yet, when it is complete and the kept one isn't, or when neither is
complete and it covers more of the lyrics. It never replaces a sheet you pinned.

The three options each do something else instead, and don't go together (exit 2).

`--index` reads LaCuerda's listings of every artist, about 200 pages, into a local index, as the
nightly step does with what is left of its budget. They are read again after 30 days, with
conditional requests. The index holds each artist's name, the slug of their page and their song
count, plus the songs of every artist page caracole has read. Searches suggest artists and songs
from it (see [caracole search](#caracole-search)).

    LaCuerda: 2950 artists and 140 songs in the index.

`--artist NAME` reads one artist's page into the index now, so that you can search their songs. NAME
is their name, or the slug of their page as `caracole search` prints it (`joaquin_sabina`). It asks
at the lookup pace, within a lookup's budgets, and not at all when the page is in the cache (30
days). On `caracole serve`, an artist's **Songs** runs it.

    Read: LaCuerda's page of Joaquín Sabina lists 241 songs.
    Not found: LaCuerda has no page for NAME.
    Not read: LaCuerda failed (…). Try again later.

`--search QUERY` asks LaCuerda's own search for songs, with one request at the lookup pace, and puts
what it answers into the index.

- LaCuerda reads only words of 4 letters or more, with accents folded: `19 días y 500 noches` is
  `dias noches`.
- A query is asked at most once in 30 days, and not at all when your library or the index already
  answers it well.
- Its request counts in the hour's lookups (`lookup_per_hour`).
- `--auto` marks a search the served page sends by itself. At most 20 of those go an hour. None goes
  for an hour after that query's search failed, or while three searches failed in the last hour. By
  hand (the page's **Ask LaCuerda**, or Enter in its search box) the search still goes.

Its last line is one of these:

    Searched: LaCuerda has 2 songs for “corazon espinado”, in the index now.
    Found already: caracole has “…” already, in your library or its copy of LaCuerda's index; no request sent.
    Nothing found: LaCuerda has no song for “…”.
    Not searched: LaCuerda failed (…); nothing changed: try again later.

`Not read` and `Not searched` cover a cooldown, a block, a spent budget or an error. They exit 0 and
change nothing.

### caracole gtptabs

Downloads a Guitar Pro file from gtptabs.com for each song that has no Guitar Pro or Power Tab
file, newest songs first.

It finds the song's artist in the site's sitemaps, under their name or the way the site files
people: last name first (`john-elton`) and "The" last (`beatles-the`). The artist's page, cached for
30 days, lists the song's uploads. Those with a guitar part (or no instrument listed), in a Guitar
Pro or Power Tab format and under 5 MB are tried, most stars first, at most three a song a run.

A download is kept only if its first bytes are those of a Guitar Pro (3 to 7) or Power Tab file. It
becomes the song's `guitar-N`, with the extension those bytes name and the lowest free N. Anything
else, such as a page served in its place, is thrown away, and that upload waits 30 days. Three
downloads in a row answered with a page end the pass as an error.

    gtptabs.com: 3 tried, 2 Guitar Pro files kept, 1 not on gtptabs.com, 0 errors

### caracole harptabs

    caracole harptabs [--index [--budget N] | --artist NAME]

Keeps a harmonica tab from harptabs.com for each song that has none, newest songs first.

A song is looked up only when the site's sitemap lists a tab with its title and an artist with its
artist's name. Then the pages of the tabs with that title are read, eight at most. Of those by your
song's artist, the most viewed is kept as `harmonica-N.txt`: hole numbers over the lyrics, as the
page has them. A tab "by Unknown" or by another artist is not kept. A song that has a harmonica tab
gets no other.

    harptabs.com: 2 tried, 1 harmonica tab kept, 1 not on harptabs.com, 0 errors

`--index` reads the artist pages, your songs' artists first, each again after 30 days. An artist
page lists the artist's 30 most viewed tabs, and caracole knows only those. The whole index is about
10,400 artists, some 11 hours of requests at 2.5–5 seconds each. 2000 requests take about 2 hours.

    The budget of 100 requests is spent: caracole harptabs --index reads the next 10329 artists, about 10 h 46 min of requests at this pace.

`--artist NAME` reads one artist's page into the index now. NAME is their name, or their page's
address as the sitemap lists it (`artist/1178/billy-joel`). It asks at the lookup pace: one request,
and none when caracole read the page within 30 days. It can't go with `--index` (exit 2). On
`caracole serve`, an artist's **Read their page** runs it.

    Read: harptabs' page of billy joel lists 30 of their 98 tabs.
    Not found: harptabs lists no artist named NAME.
    Not read: …

`Not read` covers the site turned off, its index still empty, a cooldown, a block, a spent budget or
an error. It exits 0 and changes nothing.

### caracole ug

    caracole ug --link URL [--progress]
    caracole ug --directory [--budget N]

The two options don't go together (exit 2).

`--link URL` reads an Ultimate Guitar page into caracole's index now. URL is a tab's page
(`https://tabs.ultimate-guitar.com/tab/4180894`, or a slugged one) or an artist's page
(`…/artist/634073`). For a tab it also reads the artist's page the tab links to. The artist's chords
and tabs lists are kept for searches, so a search finds every song of theirs, including those UG's
sitemaps list by a bare id.

It asks at the lookup pace, within a lookup's budgets, usually three requests. It sends no request
for a page caracole knows already, one UG answered 404 for, or a tab of a type caracole doesn't keep
(a Guitar Pro file, a bass tab…).

    Read: 斑马斑马 by 宋冬野, chords; their page lists 8 tabs.
    Not found: UG answers 404 for URL.
    Not read: …

`Not read` covers a cooldown, a block, a spent budget or an error. It exits 0. If the budget runs
out after the tab's page, the artist's page waits for the next lookup. A text that is no UG page
exits 2.

The library page runs this command when you paste a UG link into its search box (see
[Browse and search](#browse-and-search)).

`--directory` reads [UG's artist directory](#ugs-artist-directory): its letter listings, then the
page of every artist they name by a bare address. It goes on where the last pass stopped, with
`[ug_directory]`'s concurrency, pause and budget. `--budget N` sets its requests for this pass.
While it goes, it says how far it is, after each batch of requests:

    UG's listings · 312 of about 3,480 pages · letter m · 2,104 requests  about 48 min left
    UG's bare artists' pages · 1,200 of 9,431 · 14,210 requests  about 28 min left

Then what it read:

    The directory: 175,420 of about 175,600 artists, 27 of 27 listings read whole; 6,310 of 6,310 bare artists' pages read.

A block cools Ultimate Guitar down for every request of caracole's, the fetch and lookups too, and
sends one ntfy message. On a machine whose service uses another database the command is refused
(exit 2), because it builds an index. Run the service's instead:
`sudo caracole-admin ug --directory`.

### caracole gametabs

    caracole gametabs [--index [--budget N]]

Keeps a text tab of game music from gametabs.net for each song that has none, newest songs first.

A song is looked up only when a tab with its title belongs to a game your line names as its artist,
or to a composer it names. `OST` or `(Original Soundtrack)` after the game's name is fine. Composers
are known from the game pages caracole has read. The pages of those tabs are read, four at most,
most viewed first. Of those whose page agrees on the title and on the game or a composer, the most
viewed is kept as `gametab-N.txt`. A tab's attachments need a login, so caracole keeps the text
alone. A song that has a tab from there gets no other.

    gametabs.net: 2 tried, 1 tab kept, 1 not on gametabs.net, 0 errors

`--index` reads the game pages, your songs' games first, each again after 30 days. A game page lists
50 tabs with their composers, instruments, views and rating. That is how a song, or a search, finds
a tab by its composer. At a quarter of a second a request, the whole index, about 1,660 pages, is
some 7 minutes of pauses. `--budget 1700` reads it all.

    gametabs.net: 93 game pages read; 93 of 1658 game pages read, 512 tabs in the index.

### caracole ireal

    caracole ireal [--index [--budget N]]

Keeps a chord chart from iReal Pro's forum as the sheet of each song Ultimate Guitar and LaCuerda
left with none, newest songs first. A song with only an auto sheet counts as having none.

It reads the forum's sitemaps and the Jazz 1460 Standards when due. Then it tries each song that a
chart caracole has read belongs to, or that a thread is named for, by its title and artist or its
title alone (see [Chord charts of jazz standards](#configure)). It reads three thread pages a song
at most.

    Index: the Jazz 1460 Standards read.
    iReal Pro's forum: 2 tried, 1 chart kept, 1 not on iReal Pro's forum, 0 errors

`--index` reads the forum's playlists: the Jazz 1460 Standards, then the jazz forum's page and each
of its sticky threads (gypsy jazz, Dixieland, fusion, contemporary jazz…). Only a thread's first
page is read, each again after 30 days.

    iReal Pro's forum: 7 playlist pages read; 7 of 7 playlists read, 1,512 charts in the index.

### caracole musescore

Reads MuseScore's song sitemaps into the local index that the to-do page's MuseScore links come
from. It asks for nothing else and downloads nothing.

    Index: 2 sitemaps read.
    MuseScore: 80000 song pages in the index.

A Cloudflare challenge is a block. The command says `MuseScore blocked caracole: …`, sends one ntfy
message, and caracole leaves MuseScore alone until the cooldown ends.

### caracole scan

The scan does two things, and never adds a song.

First it links the audio files in Music/ to your songs, by their tags (or an "Artist - Title" file
name) and their duration, give or take 3 seconds. A file named as the song wins over one whose name
only comes close, and a close name must be clearly closer than any other. When your line gives no
duration, the file must be as long as LRCLIB's lyrics say. Chinese names are compared as pinyin too,
so 斑馬斑馬 meets 斑马斑马. If Music/ is missing or has no audio (a disk that isn't mounted, say),
nothing is unlinked: `Music: /srv/music is missing, so nothing was unlinked`.

Then it files what you dropped into `_inbox/`, by its name, for any song you haven't ignored.

| You drop | Extensions | It becomes |
|---|---|---|
| A Guitar Pro or Power Tab file | `.gp3`, `.gp4`, `.gp5`, `.gpx`, `.gp`, `.ptb` | `guitar-N.<ext>` |
| A score, such as a MuseScore download | `.mscz`, `.mxl`, `.musicxml`, `.pdf`, `.mid`, `.midi` | `score-N.<ext>` |

Name the file `Soda Stereo - De Musica Ligera.gp5`, or `De Musica Ligera.gp5` when only one song has
that title. A version number in the name, such as `(ver 2)`, is ignored. N is the lowest free
number, so no file is written over. The formats of one score share a number.

- A MusicXML file is also placed by the title and composer in its header, when exactly one song has
  both.
- A score never becomes `sheet.pdf`, which caracole renders itself.
- A name a site writes in two scripts, such as `Jay Chou (周杰倫)`, matches yours by any of its
  parts.

A file the library already has is removed from the inbox. One the library had and lost is put back
in its place. A file caracole can't place stays in the inbox, and so does one whose place in the
song's folder now holds another file.

A symbolic link is never read, and stays too:
`Inbox: 0 filed, 0 duplicates, 0 left, 1 symbolic link refused`. If `_inbox` is a link itself,
nothing in the folder it points at is read, filed or deleted.

### caracole render

    caracole render [--force] [--song "ARTIST - TITLE"]

Writes `sheet.cho`, `sheet.pdf` and `sheet.html` next to every kept sheet, or next to one song's
with `--song`. `sheet.html` is [the sheet viewer](#the-sheet-viewer). The song is rendered in its
own version: its `[version]`, else transposed as `[transpose]` says, else as written.

The PDF has the chord diagrams above the song, in two columns. Under the title it names the artist,
the key and the capo ("Soda Stereo · Bm shapes · capo 2 · sounds C#m"). For its fonts, see
[Fonts in the PDFs](#fonts-in-the-pdfs).

A PDF is made again only when its sheet, its version, the fonts, caracole's PDF style or the text it
prints changes, or when the file is no longer the one caracole wrote. So annotate a copy, not
`sheet.pdf`. `--force` makes them all again, or the one song's with `--song`. Meanwhile it says
which song it is on: `PDFs · 37 of 214 songs · Artist - Title  about 2 min left`.

Each UG version kept beside the sheet gets a viewer of its own, `version-<tab>.html`, in the
version's own key. It gets no `.cho`, no PDF and no Export PDF. To export one, make it the sheet
first. A song that no longer keeps its human sheet loses the `sheet.cho`, `sheet.pdf` and
`sheet.html` made from it.

When a sheet can't be rendered, the command exits 1 and the log says why, as
`no PDF for Artist - Title: …` or `no viewer for Artist - Title: …`. The last good PDF stays in
place. A symbolic link in the place of `sheet.json`, `sheet (auto).txt`, a `.cho` file or a viewer
fails that song alone, because caracole reads no sheet through a link. Remove it and render again.
The next `caracole run` writes `sheet.json` again.

After the sheets, it makes the [songbooks](#songbooks)' files that need it and prints
`Songbooks: 1 rendered, 2 up to date, 0 failed`. A songbook that couldn't be made, or a
songbooks.toml that can't be read, exits 1 too. With `--song` only that song's failure counts.

### caracole render --version

    caracole render --song "ARTIST - TITLE" --version QUERY

Exports that song's PDF in another version. QUERY is what the sheet viewer puts after the `#` in its
address, such as `t=2&mode=dorian&capo=0`.

| Word | Names |
|---|---|
| `t` | How far the sheet is transposed. Without it, the song's own `t`. |
| `mode`, `capo` | The mode and the capo. |
| `at` | Chord shapes you chose. |
| `alt` | "Play X for every Y". |
| `inst` | The instrument: `guitar`, `ukulele`, `ukulele-low-g`, `baritone`, `piano`, `harmonica`, `flute` or `recorder`. Without it, the guitar. |

A QUERY with none of `t`, `mode`, `capo`, `alt` or `at` is the song's own version, on that version's
instrument.

The PDF is written beside the sheet's own and named after the version: `sheet (G Dorian, capo
0).pdf`, `sheet (Transposed +2, capo 0).pdf` for a sheet with no key, or `sheet (G Major, capo 2,
ukulele).pdf`. An export with the same name replaces the last one.

The PDF is drawn for its instrument. A ukulele gets four-string diagrams and the piano a keyboard
for each chord. The harmonica gets the harps for the song and each chord's holes (`G7: draw 2–5`). A
flute or a recorder gets the key's scale. An instrument with no capo plays the chords as they
sound, so its PDF says `Key A`, never `G shapes · capo 2`.

Exports are caracole's files. Every render makes them again when the sheet or the style changes, and
`caracole remove` deletes them. The library page lists them in the song's card as its PDF exports.
An export is made from the song's human sheet, else its auto sheet. When it can't be made, the
command exits 1 and says why.

### caracole render --mine

    caracole render --song "ARTIST - TITLE" --version QUERY --mine

Makes that version the song's own instead of exporting it. The command writes it under `[version]`
in overrides.toml, keeping your comments, and says so:
`Your version of Soda Stereo - De Música Ligera: G Dorian, capo 0`. Then it renders the song. Its
`sheet.pdf` is in that version, its viewer starts there, and its exports and songbooks follow.
`--mine` needs `--version` (exit 2).

- The entry keeps a key, not a move: `key=Gm&mode=dorian&capo=0`, plus `&inst=piano` for another
  instrument. If a sheet in another key or capo takes the song's place later, it plays in G dorian
  with no capo too.
- A sheet with no key has no key to keep, so its entry is a move from the sheet (`t=0&capo=1`).
- A version that plays the sheet where the song plays without one removes the song's `[version]`.
- `sheet.pdf` stays the guitar's. Another instrument's PDF is an export or a songbook.

See `[version]` in [overrides.toml](#overridestoml-your-decisions).

In the sheet viewer, **Export PDF** under ⋯ does the export. On [`caracole serve`](#caracole-serve)
it downloads the PDF and writes nothing into the library. If you changed the key, mode, capo, a
chord or a shape, it asks first, and **Make mine** queues this command. Opened from a file, the
viewer shows the command to run instead.

### caracole todo, review and search

`caracole todo` rewrites `_todo.md` and `index.html` from the database.

`caracole review` settles uncertain matches, one prompt per song (see [Review](#review)).

`caracole search` searches your library and the offline UG index, by an artist, a title or both.
`--key` finds your songs in one key, and `--progression` those that play a progression (see
[caracole search](#caracole-search)).

    caracole search [QUERY]... [--limit N] [--add N] [--key KEY] [--artist NAME] [--title TITLE] [--progression NUMERALS]

### caracole icons

Fetches the icon of each site `index.html` has none for yet, then rewrites `_todo.md` and
`index.html`. It prints a line per site:

    Ultimate Guitar: icon fetched
    LaCuerda: kept already
    LRCLIB: no icon there; its badge stands in, and the site is asked again in a week

Unlike the run's icons step, the command also tries a site whose last try failed less than a week
ago. It tries YouTube too, with that provider's budget and pace (3.75–7.5 s), unless
`[providers.youtube] enabled = false`. What a site answered less than a week ago still comes from
the cache. A block cools that site down and sends one ntfy message, and the other sites are still
asked. A block or an error exits 0.

### caracole autochords

    caracole autochords [--song "ARTIST - TITLE"]

Writes `sheet (auto).txt` from audio, for the songs with no human sheet, or for one song with
`--song`. Then it rewrites `_todo.md` and `index.html`. The audio is one you bought (see
[the worked example](#a-worked-example)) or one the youtube step took.

It needs the flake's `packages.autochords`, with torch, librosa and beat_this. The default package
says so and exits 1.

| Exit status | When |
|---|---|
| 0 | A purchase it can't read fails that song alone. The to-do page lists the file, and the song is tried again once the file changes. |
| 1 | Auto-chords can't work at all: the model files are missing or unusable, or it can't write a sheet into the library. |

A song's sheet is made again when its audio changes, and when timed lyrics arrive after a sheet made
over plain lyrics or none, so that each chord can go over its word.

A song takes minutes, so it logs a line before each, `Working out the chords of Artist - Title
(3 of 12)…`, and one after: `Artist - Title: auto sheet written (synced lyrics)`.

Before the chords, it hears the words of up to `[autochords] transcribe_per_run` songs (3), newest
first, as `caracole transcribe` does (see [Lyrics transcribed from the
audio](#lyrics-transcribed-from-the-audio)): songs with audio that every lyrics site missed and that
weren't heard yet. A song past the cap gets its chords now and its words on a later run, its sheet
then made again over them. It lets a waiting lookup go first between a song's vocals and its
words too. Its last line says what it heard:

    auto-chords: 2 generated, 4 skipped, 0 failed; words heard for 1, nothing sung in 1

- `transcribe = false` or `transcribe_per_run = 0` hears nothing.
- Where this machine can't transcribe, it hears nothing and the to-do page says why, under
  **Lyrics that couldn't be transcribed**. That includes the GPU build's nightly unit,
  which doesn't see the GPU: the words then come from caracole serve's jobs.
- A setup that fails (the separator, the GPU, Whisper's model) stops the hearing for the rest of
  the run, and the to-do page says so; the chords go on, and it still exits 0. The song it failed
  on is noted, and the next nights pass over it for 30 days, or until its file changes, so that
  the others are heard; the to-do page lists it. Its card still offers Transcribe the lyrics.
- Audio Whisper can't load still gets its chords. Its words aren't heard, nor offered on its card,
  until the file changes; the to-do page lists it under **Lyrics that couldn't be transcribed**.
- A song you said isn't sung (`caracole transcribe --none`) is never heard again, until its audio
  changes: a new file is heard once more.
- A bug while hearing a song fails the run (exit 1), and the song's chords are made all the same.

### caracole youtube

    caracole youtube [--song "ARTIST - TITLE" [--url URL | --none] [--sheet [--progress]]] [--search QUERY | --video URL]

Takes the audio of the songs no human sheet was found for from YouTube, as the nightly youtube step
does (see [Audio from YouTube](#audio-from-youtube)). The chords come next, from
`caracole autochords`.

    Radiohead - Creep: downloaded Creep (Radiohead - Topic), https://www.youtube.com/watch?v=…
    YouTube: 1 downloaded, 0 not there, 0 unavailable, 0 errors (2 yt-dlp runs of 6).

| Option | What it does |
|---|---|
| `--song "ARTIST - TITLE"` | Takes that song's audio now, even when its search found nothing lately. It refuses a song that has a human sheet, is ignored or has audio of its own (a purchase, or a file you gave it). |
| `--url URL` | With `--song`. First writes the video under `[youtube]` in overrides.toml, so the song's audio comes from it. |
| `--none` | With `--song`. Writes `"none"` there and lets go of any audio the song had from YouTube. It asks nothing, so it works with YouTube off, and for a song not in the library yet. |
| `--sheet` | With `--song`. Does it all now: audio, chords and sheet. See "A sheet from a video, now" under [Audio from YouTube](#audio-from-youtube). |
| `--search QUERY` | Asks YouTube for the query's first video and its thumbnail, as the library page's suggestion does, within the same limits. It prints `Searched: …`, `Nothing found: …` or `Not searched: …` with the reason, and exits 0. |
| `--video URL` | Reads one video's title, channel, length and thumbnail, with no download, as a link pasted into the library page's search box does. |

It needs the flake's `packages.autochords`, which has auto-chords and yt-dlp. Without them, or
without the model files, it asks nothing and exits 1.

### caracole transcribe

    caracole transcribe --song "ARTIST - TITLE" [--force | --none] [--progress]

Transcribes, with Whisper, the lyrics of a song whose audio came from YouTube and that no lyrics
site has. It keeps them as the song's transcript and makes its auto sheet again with the chords over
them (see [Lyrics transcribed from the audio](#lyrics-transcribed-from-the-audio)). It needs the
flake's `packages.autochords`, with Whisper, its model files and demucs-rs. Without them it does
nothing and exits 1. It says each stage as it ends; while the vocals, the words and the chords run,
a live line on a terminal says what they are doing (`Words · 1:12 of 3:58`), and the journal gets
that line once a minute. `--progress` writes a JSON line per stage instead, for caracole serve.

| Option | What it does |
|---|---|
| `--force` | It is sung. Hears a song caracole heard nothing sung in, or that you said isn't sung, with no rule of nothing sung: Whisper runs whatever the singing found, over the whole song when none was. Also tries audio Whisper couldn't load again, after an ffmpeg or Whisper upgrade. A song offered a transcription anyway is simply transcribed. |
| `--none` | It isn't sung. For a song with a transcript: drops it, makes the sheet again with the chords alone (`Chords only: you said it isn't sung`), and never hears that audio again until `--force`. A new file is heard once more. |

### caracole audio

    caracole audio FILE [--song "ARTIST - TITLE"] [--progress]
    caracole audio --upload ID [--song "ARTIST - TITLE"] [--progress]

Makes a song's auto sheet from an audio file of yours (MP3, M4A, FLAC, WAV, Ogg or AIFF, 30
minutes at most), now:

    $ caracole audio "03 - Nick Cani - Vikingos veganos.flac"
    Read “03 - Nick Cani - Vikingos veganos.flac” as Nick Cani - Vikingos veganos.
    Song: added to wanted.txt, line 16.
    Audio: kept as its audio: FLAC, 3:18.
    Lyrics: found, timed.
    …

- The song is `--song`, else the file's artist and title tags, else its name, less its track number.
  A file that names no artist asks for `--song` and exits 2. A song the library doesn't have goes
  into wanted.txt with the file's album and length, so LRCLIB is asked with that length.
- A copy of the file is kept in the state folder's `audio/`, as `<song id>-<digest>.<ext>`, private
  to caracole and never synced. It becomes the song's audio, whatever the song had: a purchase stays
  in Music/ but is no longer its audio, YouTube's audio is let go of at the next youtube step, and a
  file given before is deleted. The scan never links a purchase over it. The same file again changes
  nothing (`Audio: has this file's audio already.`).
- Then it goes on as [a sheet from a video](#a-sheet-from-a-video-now) does: the lyrics sites first,
  the words heard from the file only when every one missed, the chords, the PDF, the viewer and the
  pages. A lookup waiting for the lock goes first before the vocals, the words and the chords.
- `--upload ID` takes a file caracole serve was sent, moved into place rather than copied. Without
  `--song`, the song is the one the file's tags or name say, as for a file (the page always names it).
  Once moved, the upload leaves a small marker beside the file for 30 days (the Journal's history),
  so the same request again (Try again after the Audio step, or one cut off on the way) goes on:
  `Audio: has this file's audio already.` while the song's audio is that file. An upload lost before
  its Audio step (a request interrupted, its file swept after an hour or replaced by another upload),
  or one a later file of yours has replaced since, says the upload is gone: choose it again.
  A request cut off while it kept the file and never asked again leaves the file in `audio/` for
  those 30 days; then it is deleted.
- No file of yours is deleted while another song's audio is that file too.
- Two songs merged into one (after an upgrade that spells a song's key anew) keep the file you gave
  either; of two such files, the one given last, and the next scan deletes the older.

It needs the flake's `packages.autochords` (auto-chords and its model files; no YouTube, no yt-dlp).
It exits 0 once the sheet is made, and when a site's block, cooldown, spent budget or error makes
the lyrics wait. It exits 1 for a song that is ignored or has a human sheet (`No sheet made: …
already has a sheet.`), for a file caracole doesn't read or auto-chords can't read, and, before it
reads anything, for a caracole that makes no chords. A removal deletes the song's file in `audio/`.

### When the pages are rewritten

A command that changes what `_todo.md` and `index.html` show rewrites both when it is done.

| Commands | Rewrite the pages |
|---|---|
| `match` (not `--dry-run`), `render`, `scan`, `todo`, `add`, `search --add`, `sync`, `autochords`, and every `songbook` command but `list` and `show` | Always. |
| `transcribe`, `audio` | Once it took the song. |
| `review` | When an answer changed something. |
| `fetch`, `lyrics`, `lacuerda`, `gtptabs`, `harptabs`, `gametabs`, `musescore`, `youtube` | When they did something or were blocked, so that Provider health shows the cooldown. |

A page caracole can't write ends the command with exit status 1 and
`can't write …/_todo.md: Permission denied`. The command's own work is saved first. For `add`,
`search --add` and `sync` it is only a warning.

### One caracole at a time

Every command that asks the sites or writes the library holds caracole's lock while it works, so no
two budgets are spent side by side. A second command waits for the first and says which it is:

    Another caracole is running (pid 4242: run); waiting for it to finish.

Once it has the lock, it reads the sites' cooldowns. If the first caracole was blocked, it sends
that site nothing and exits 0.

`search`, `match --dry-run`, `index stats`, `remove --list`, `songbook list` and `songbook show`
only read, so they never wait. `review` and `remove` take the lock only after your answers.

A lookup never waits behind a whole run. Lookups are `caracole get`, `ug --link`,
`lacuerda --search`, `lacuerda --artist` and `harptabs --artist`. A waiting one says:

    Another caracole is running (pid 4242: run); it lets a lookup go first at its next pause, or between two songs.

The run lets go of the lock in the pause it is in. Where it sends no request (auto-chords, the PDF
pass), it lets go between two songs. It takes the lock back when the lookup is done, waits a whole
pause before its next request to any site the lookup asked, and reads each song and overrides.toml
again. So a song the lookup fetched isn't fetched twice, and a tab it pinned or a LaCuerda sheet it
picked is the one kept. The commands for one site (`caracole fetch`, `lyrics`, `icons`…) let a
lookup go first in their pauses too.

Several lookups at once take turns with the lock, a request or a stage each, so each site still gets
one request at a time. While a lookup runs or waits, no other caracole takes the lock.

What you ask for now also waits as a lookup does, not behind the whole run:

- `add`, `remove`, `review`, `fetch --song`, `render --song`, `transcribe` and `audio`;
- `youtube --song` (with `--sheet` or `--none` too), `youtube --search` and `youtube --video`;
- `caracole songbook make`, `add`, `remove`, `move`, `set`, `rename`, `delete` and `render`.

Any other command, such as `caracole fetch`, `render` or `sync`, waits for the whole run.

A lookup still waits for a sync, an import, an index merge, a YouTube sheet's models or one stage of
a transcription. That is minutes at worst. The long one is a transcription's separator on a CPU,
about five times the song's length. On a GPU each stage takes a minute and a half at most.

The lock's files are in the state folder:

| File | What it is |
|---|---|
| `caracole.lock` | The lock. |
| `caracole.lock.waiting/` | A file per waiting lookup, which it touches every second. One left by a killed lookup stops counting after five seconds. |
| `caracole.lock.handoff` | Held by the run while a lookup has the lock. |
| `caracole.lock.lane` | Held by the lookups while any of them runs or waits. |

## UG's artist directory

UG's sitemaps list about a tenth of its tabs by a bare `/tab/{id}`, with no artist. That includes
every tab of an artist whose name has a letter outside ASCII (宋冬野, Joaquín Sabina, Кино). UG's
letter listings (`/bands/s.htm`, `/bands/s2.htm` …) name every artist: about 175,000 of them, on
about 3,500 pages. caracole reads them all, then the page of each artist listed by a bare
`/artist/{id}`.

- A search then finds such an artist by name, with **Read their page on UG** to read it now. Once
  their page is read, their songs show like any other artist's, and a search by title
  (斑马斑马) finds them.
- The nightly fetch finds their songs without an `[artist_url]` entry, and the to-do page stops
  asking you to find them.

Start the first read yourself, once, on the service:

    sudo caracole-admin ug --directory

It takes about an hour, 14,000 to 20,000 requests at about five a second. `[ug_directory]` in
caracole.toml sets that pace: six requests at once, no pause, a budget of 25,000. A lookup you
start meanwhile goes first. A pass that stops goes on from there the next time.

After that the nightly run's `ug-directory` step reads each listing again after 30 days. It reads
an artist's page again only when their row in the listing changed, and never within 30 days.

A block stops every request, cools Ultimate Guitar down for the fetch and lookups too, and sends
one ntfy message. A page that won't read never removes an artist. Only a 404 from their own page
does.

The directory travels with UG's index (about 25 MB) in `caracole index export` and `merge`, in a
`.caracole` file and in a sync's Site indexes. The phone reads no listing.

## Lyrics from LRCLIB, Megalobiz and AZLyrics

caracole asks three sites, in this order:

| Site | Asked about | Its lyrics |
|---|---|---|
| LRCLIB | every song | timed or plain |
| [Megalobiz](https://megalobiz.com/) | songs LRCLIB has no lyrics for, failed on, or has only plain lyrics for | timed, so they replace plain ones |
| [AZLyrics](https://www.azlyrics.com/) | songs that still have no lyrics | plain |

Megalobiz and AZLyrics are asked by the nightly run (its megalobiz and azlyrics steps), by
`caracole lyrics`, by a lookup, and when a sheet is made from a YouTube video.

- A song's lyrics are missing only once every site asked answered that it has none. caracole asks
  again after 30 days.
- An error is never a miss. The song goes back to pending and the next run asks again.
- A block cools the site down and sends one ntfy alert. A 429 is a block, and so is AZLyrics'
  page saying it has "detected unusual activity from your IP address".
- Lyrics from Megalobiz or AZLyrics link back to their page there: on the Lyrics tile of the
  song's card, and as `lyrics_from` in `info.json`.
- `[providers.megalobiz] enabled = false` and `[providers.azlyrics] enabled = false` turn them
  off.
- `[lyrics]` in overrides.toml (see [overrides.toml](#overridestoml-your-decisions)) is kept by every one of these:
  the sites are asked under its `as`, and a record you picked is asked of its own site alone. A
  lookup says so: `under “Eagles - Hotel California”: LRCLIB has none; …`, `the record you picked:
  megalobiz 24519`, `the record you picked is gone: lrclib 9`, `the record you picked isn't asked
  now: lrclib 9` (within its 30 days).
- A song whose record you picked and that has no lyrics is never transcribed, not even with
  Transcribe anyway: only that one record was asked, never the other sites. Pick another record,
  or clear the pick to have every site asked again, under the name you typed (`as`, which the clear
  keeps), else the song's own.
- A pick, a clear or a search the nightly run lets in at one of its pauses counts at once: the
  passes read `[lyrics]` again after it, and what a site answered about the song meanwhile is kept
  only if the song is still to be asked, as it was asked.

**Megalobiz** gets two requests per song at most. Its API allows 1,000 requests a day, and
caracole stops at 900 (see [Two paces](#configure)). It also allows 30 a minute, which caracole
doesn't keep to. It pauses 0.5–1 second between requests (0.5–0.75 in a lookup), so a busy night
may get a 429.

**AZLyrics** gets two requests per song: the artist's page, then the song's. Its robots.txt
closes its search, so caracole works out the artist's page from their name (`The Police` is
`/p/police.html`). That misses artists filed by surname (`Sean Paul`) or under another name
(`Plan B`). For those, name the lyrics page under `[azlyrics]` in overrides.toml. Each of its
pages says "Usage of azlyrics.com content by any third-party lyrics provider is prohibited by our
licensing agreement", so reading it is your choice.

Lyrics and [auto-chords](autochords.md):

- An auto sheet takes its words from a lyrics site when the song has any, else from the song's
  transcript (see [Lyrics transcribed from the audio](#lyrics-transcribed-from-the-audio)). With
  neither, or when a site calls the song instrumental, it is only a chord chart.
- Lyrics found later go under an auto sheet at once, without running the models. When they are
  timed, the next auto-chords run puts each chord over its word.

## Audio from YouTube

For a song nobody has charted, caracole can take the audio from YouTube and work out the chords
itself, with [auto-chords](autochords.md).

Taking audio from YouTube goes against its robots.txt, which closes the search and the API
yt-dlp uses (`/results`, `/youtubei/`) to crawlers. It also goes against YouTube's terms of
service, which allow no downloads but those YouTube offers. Doing it is your choice, for your own
library. To turn it off, set `[providers.youtube] enabled = false` in caracole.toml. This is the
one place where caracole asks for pages a site's robots.txt closes.

caracole keeps to these terms:

- It takes audio only for a song with no human sheet: those the buy list would list, or one you
  name with its video. A purchase in Music/ comes first, and a human sheet found later replaces
  the auto sheet.
- It runs yt-dlp only where auto-chords can make chords of the audio. A caracole without
  auto-chords (the default package) or its model files runs none, and the to-do page says why.
- A night's budget is 6 yt-dlp runs (a search or a download each), one at a time, 3.75–7.5
  seconds apart.
- It takes only the audio, as m4a, never a playlist, 100 MB at most. The file stays in the cache,
  outside the synced library (see [the library folder](#the-library-folder)).
- A block stops YouTube for the night: "Sign in to confirm you're not a bot", a 429 or 403, a
  rate limit or a captcha. The cooldown starts at 24 hours and doubles, with one ntfy message.
  caracole never works around a block: no cookies, login, proxy, PO tokens or plugins. yt-dlp
  ignores your own yt-dlp config too.
- On the library page, a video suggested for a search, or one whose link you paste, takes one
  yt-dlp run for its metadata. Both together are limited to 10 an hour, and a query or a video is
  asked once in 30 days.

`caracole autochords` then makes `sheet (auto).txt` from the audio. The sheet's third line names
the video, as in `Audio from YouTube: Creep (Radiohead - Topic)`, and the viewer links to it. The
to-do page and index.html say where each song stands.

### Which video

caracole asks yt-dlp's search for `ytsearch8:<artist> <title>`. It takes an upload whose title is
the song's, whose channel or title names the artist (宋冬野 meets "Song Dongye"), and whose
length is within 20 seconds of the song's. With no length known, 45 seconds to 15 minutes fits.

A cover or a live, karaoke, instrumental, lesson, slowed, sped-up or remixed version loses to
any other, unless the song itself is live or acoustic. After that an exact title wins, then the
closest length, then the artist's own or official uploads.

- If nothing fits, the song is a miss, asked about again after 30 days.
- For a wrong pick, or a song the search found nothing for, paste the right video under
  `[youtube]` in overrides.toml, or run `caracole youtube --song "Artist - Title" --url URL`.
- A network error, a timeout (2 minutes for a search, 15 for a download) or another yt-dlp
  failure is not a miss. The song waits for the next run.
- A video that needs a login (private, removed, age-restricted, members-only, DRM-protected) is
  passed over at the next search. So is one whose download failed 3 times for a reason other
  than the network. If you pasted the video, the song waits for another paste.

### A sheet from a video, now

For a song whose video you know, caracole makes the sheet at once. Use caracole serve's library
page, or run:

    caracole youtube --song "Nick Cani - Vikingos veganos" \
      --url "https://www.youtube.com/watch?v=lzN7Thn3FV4" --sheet

- A song the library doesn't have goes into wanted.txt, and the video goes under `[youtube]`.
  Without `--url`, caracole uses the video under `[youtube]`, else the one its search picks.
- It prints a line per stage: the audio (on the terms above), the lyrics, the vocals and the
  words, the chords (a few minutes on a CPU), then the PDF, the viewer `sheet (auto).html` and
  the pages. `--progress` adds a JSON line per stage, for caracole serve.
- The lyrics sites are always asked first. When every one has missed, the words are heard from
  the audio, as `caracole transcribe` hears them (see [Lyrics transcribed from the
  audio](#lyrics-transcribed-from-the-audio)), and the chords are made once, over them. That
  takes a couple of minutes more on a GPU, up to half an hour on a CPU. A song a site has
  lyrics for says `Vocals: skipped: not transcribed: its lyrics are found.` (or `instrumental`)
  wherever it runs. For a song no site has words for, it says `turned off` with `[autochords]
  transcribe = false`, or `not transcribed here: …` where this caracole can't transcribe.
- With timed lyrics, each chord goes over its word, as on Ultimate Guitar. With plain lyrics you
  get a chord chart, then the lyrics. With none, only the chart. When nothing sung was heard, the
  chart says `Instrumental: nothing sung was heard in the audio`.

It exits 0 when the sheet is made, and when a block, a cooldown, a spent budget or a network
error makes the song wait. A transcription that fails here (the separator, the GPU, Whisper's
model, or `Whisper can't read the audio`) fails its own stage alone and marks nothing against
the song: the sheet is made with the chords only, and the song's card still offers Transcribe
the lyrics. It exits 1 when:

- The song has a human sheet, is ignored, has audio of its own (bought or given), or has `"none"`
  under `[youtube]` and you gave no video. A human sheet kept, or the song ignored, while a lookup
  went first before the chords counts too.
- YouTube won't give the video, or auto-chords can't read the audio.
- This caracole can't make chords from audio. It says so before it asks anything.
- Another caracole removed the song meanwhile (`No sheet made: … left the book while its sheet
  was made`).

Its last line then says why (`No sheet made: can't download this video; try another.`).

### Timed lyrics of another length

LRCLIB times its lyrics against one release of a song. When your audio, a video or a purchase, is
within 2 seconds of that release's length, the chords go over the timed lyrics as they are.

When it isn't (a spoken intro, credits after the song, another cut), auto-chords works out how
far to shift the lyrics, up to 30 seconds either way, from the chords and beats it heard. It
shifts them only when one shift wins clearly. Otherwise the sheet is a chord chart, then the
plain lyrics.

The sheet says what was done, on the line after the video's:

    Audio from YouTube: Vikingos veganos (HyperFanes)
    Lyrics' timing shifted 12.0 s later to fit this audio

or `Lyrics' timing unshifted: LRCLIB's audio is 12.0 s shorter` when the lyrics fit as they are
timed. A wrong shift shows as chords that don't fit the words. Another video under `[youtube]`,
or a purchase, makes the sheet again.

### Lyrics transcribed from the audio

For a song with audio of its own (taken from YouTube, a purchase, or a file you gave it) that no
lyrics site has words for, caracole can hear the words itself, with Whisper large-v3, and make the
auto sheet again with the chords over them:

    caracole transcribe --song "Nick Cani - Vikingos veganos"

A sheet from a video does this by itself, before its chords (see [A sheet from a video,
now](#a-sheet-from-a-video-now)); this command is for a song whose sheet came without the words.
It never adds a song to wanted.txt, and it takes only a song that is offered a transcription.
That is a song with audio caracole can read, no human sheet, not ignored,
lyrics missing at every lyrics site you have switched on, and not transcribed yet.

- demucs-rs separates the vocals, to find where someone sings. Whisper then hears the whole song.
  It invents words over instrumental parts, so words more than 0.3 seconds from any singing are
  dropped.
- The sheet says `Lyrics transcribed from the audio (Whisper), unverified`.
- The words are kept as the song's transcript. Its lyrics stay missing, and lyrics a site has
  later win.
- When nothing sung was heard, the auto sheet says `Instrumental: nothing sung was heard in the audio`
  and is made again once to say so; lyrics a site has later replace it.
- It takes a couple of minutes on a GPU and up to half an hour on a CPU (`[autochords]
  transcribe_device`, `"auto"` by default). A lookup waiting for the lock goes first before each
  long stage.
- It prints a line per stage, and `--progress` adds a JSON line per stage, for caracole serve.
  Its library page offers the same on the song's card (see **Lyrics transcribed from the audio**
  under [caracole serve](#caracole-serve)).
- The transcript is kept before the chords. If they fail, or the server stops then, running it
  again (the Journal's Try again) goes straight to the chords over the kept transcript.

It exits 0 once the sheet is made, and 1 otherwise:

| It says | What happened | The song afterwards |
|---|---|---|
| `caracole transcribes nothing here: …` | This caracole can't transcribe: no Whisper, auto-chords, demucs-rs or model file, or a CUDA build on a machine that doesn't see the GPU. YouTube and yt-dlp aren't needed. | Unchanged. |
| `No transcript made: …` | The song isn't offered one or isn't in the book. Or, during the job, its lyrics were found, it got a human sheet or was ignored, its audio changed or it was removed. | Unchanged. |
| `Transcript kept; no sheet made: …` | The words were heard and kept, but before the chords the song got a human sheet, was ignored or found its lyrics, or the chords then failed. | Its transcript is kept, unused while it has a human sheet or lyrics; after a failure, Try again makes the sheet over it. |
| `Transcript and sheet kept: a bug in caracole …` | The sheet over the transcript was made, then caracole hit a bug. | Both are kept. |
| `Words: failed: no singing heard.` | Less than 10 seconds of singing, so Whisper didn't run, or too few words in it (under 8, or under 20 a minute). Nothing is kept. | Not offered until its audio changes. |
| `Whisper can't read the audio: …` | Whisper couldn't load the audio. The line says what to do. | Not offered until its audio changes, or `--force`. Its chords are still made. The to-do page lists it. |
| `… can't be said not sung: it has no transcript.` | `--none` for a song with no transcript of its audio. | Unchanged. |
| `can't measure the audio here`, `the separator can't run here`, `its vocals can't be read`, `its vocals are … shorter than the song`, `the GPU failed`, `Whisper's model won't load` | The setup failed, not the song. | Still offered. |

Anything else Whisper fails on is a bug in caracole. It says so, and the song stays offered.
Whatever stopped it, its last line says why (`No transcript made: the GPU failed: …`), never
`Done in …`.

## The to-do page

`Library/_todo.md` lists only what needs you, with the links to do it and the exact lines to
paste. Each run rewrites it, and so does every command that changes what it shows (see
[the pages](#one-step-at-a-time)). It starts with a summary (songs found, wanted and ignored), a
link to `index.html`, and how many songs are waiting for the nightly fetch. Then come these
sections, each only when it has something in it:

| Section | What it lists, and what to do |
|---|---|
| Setup problems | What stops caracole until you act: an overrides.toml it can't read (the nightly run then stops before its first step), a wanted.txt or lines of it that it can't read, a UG index that isn't built or is incomplete. |
| Review | Matches caracole wasn't sure about. See below. |
| Partial sheets | Sheets that cover less than 80% of the lyrics. A more complete one takes its place when one turns up. To use another UG version now, pin it under `[pin]`. |
| Artists to find on Ultimate Guitar | Artists whose tabs caracole can't see yet. See below. |
| Buy list | Songs with no human sheet, once caracole has nothing left to try, with links to buy the track DRM-free and to check the song first. Drop the purchase into Music/ and auto-chords writes a sheet from it. |
| No human sheet found yet | Takes the buy list's place when caracole takes audio from YouTube. Each song says where it stands: `queued`, `waiting` (YouTube is blocking caracole), `audio downloaded from` or `chords done, from` its video. Nothing here needs you. |
| Nothing on YouTube for these | Songs with no video that fits (asked again after 30 days), with a video that can't be downloaded, or with `"none"` under `[youtube]`. The lines to paste under `[youtube]` follow. |
| Auto-chords couldn't read these purchases | Each file, with the error. Download it again, or convert it (to FLAC, say). A changed file is tried again. For audio from YouTube, paste another video under `[youtube]`. |
| New Guitar Pro files from gtptabs.com | Files downloaded in the last 7 days. If one isn't the version you want, drop yours into `_inbox/` as `Artist - Title.gp5`. caracole files it beside this one. |
| Scores on MuseScore | Up to three MuseScore pages with the song's title, each only a possible match. Download a score yourself (most need a Pro account), save it under the name the line gives, such as `Oasis - Wonderwall.mscz`, and drop it into `_inbox/`. caracole never downloads these. If MuseScore is blocking caracole, the section says so. |
| Guitar parts not found | Songs with no UG text tab and no Guitar Pro or Power Tab file, with Songsterr and YouTube links. |
| Inbox: files caracole couldn't place | Rename the file `Artist - Title.ext`, as caracole names the song, and the next run files it. Don't move it into the song's folder yourself. A symbolic link is never filed, and `_inbox` itself has to be a folder. |
| Missing lyrics | Songs no lyrics site has words for yet. caracole asks again after 30 days. |
| PDFs | The last render: how many PDFs were made or failed, a font problem if there is one, and the sheets that failed. |
| Sources | How many songs wanted.txt has, and the lines caracole couldn't read. |
| Provider health | For each site: OK, errors (nothing has worked since the last error), cooling down until when, or off. Then its last success, its last error and the last run's requests. |

**Review** gives each candidate with its score, the UG song, the step that found it and links to
its pages, then its lines for overrides.toml. Each line ends with the table it goes under, as in
`# under [match]`. An artist's `[alias]` line is given once on the page, because the same key
twice under `[alias]` makes the file unreadable. The last line is the `[reject]` line that
dismisses all the candidates. `caracole review` asks the same in a terminal (see
[Review](#review)).

**Artists to find on Ultimate Guitar** lists artists UG's sitemaps show only by bare ids, usually
because of accents or non-Latin letters (Joaquín Sabina, Maná, 宋冬野). It goes away once
[UG's artist directory](#ugs-artist-directory) has read every listing. Until then, open the
artist's page on UG, or any of their tab pages, and paste its address into the block the page
gives:

```toml
[artist_url]
"宋冬野" = "https://www.ultimate-guitar.com/artist/634073"
```

- You do this once per artist, not per song. The next run reads the page, finds your songs on it
  by title and fetches them. `caracole search` then finds every tab the page lists.
- If the page you pasted leads nowhere (UG answers 404, robots.txt closes it, or it doesn't link
  to its artist's page), the artist stays on the list with what is wrong. Paste another page in
  its place.
- If UG's copy of the page can't be read, caracole asks again a week later, then after twice as
  long each time. Meanwhile the song isn't counted as missing.

### Review

`caracole review` asks about each song to review in turn. It lists up to five candidates, each
with its score, the UG song, the step that found it and a page of that song:

    [1/1] Radio Head - Crep
      1) 89  radiohead/creep (fuzzy_title)  https://tabs.ultimate-guitar.com/tab/radiohead/creep-tabs-4119
    Pick 1-1, (n)one of these, (p)in a URL, (i)gnore, (s)kip, (q)uit:

| Answer | What it does |
|---|---|
| a number | Accepts that candidate. Writes `[match] "Radio Head - Crep" = "radiohead/creep"`, and `[alias] "Radio Head" = "radiohead"` when the artist's name differs, so the artist's other songs match too. |
| `n` | None of them is the song. Writes them all under `[reject]`, and caracole goes on looking without them. Not offered for a song with no candidates. |
| `p` | Asks for a UG tab address and writes it under `[pin]`. Enter there skips the song. |
| `i` | Ignores the song: it goes under `[ignore]`. |
| `s` or Enter | Skips the song. |
| `q` | Stops. |

A number writes no `[alias]` for a candidate found by title alone, which is usually a cover, nor
for one under a catch-all artist such as `misc-musicals`.

Each answer goes into overrides.toml, with your comments kept. When an answer changed something,
caracole matches again at the end and rewrites `_todo.md` and `index.html`. A broken
overrides.toml stops it with status 2. It doesn't hold caracole's lock while it waits for you, so
the nightly run never waits for an answer.

To answer for one song without being asked:

    caracole review --song "Radio Head - Crep" --pick 1
    caracole review --song "Radio Head - Crep" --pick radiohead/creep
    caracole review --song "Radio Head - Crep" --none

- `--song "ARTIST - TITLE"` on its own asks about that song only.
- `--pick` takes a candidate's number or its UG song, as the list shows them.
- `--none` rejects every candidate listed. With `--seen ARTIST/SONG` for each one you saw, it
  rejects only those, in case the nightly run found others since.
- It then matches that song again, rewrites the pages and says where the song stands: matched
  (and how to fetch it now), still in review, or not found.
- It exits 1 and writes nothing for a song that doesn't need review, and for a number or a UG
  song that isn't in the list.

A song not found has no candidates. `caracole review --song "ARTIST - TITLE"` then lists the
first five songs `caracole search` finds for it, without those you rejected. `--pick` takes one
of them, by its number in that list or as ARTIST/SONG. Don't go by `caracole search`'s own
numbers, which count the songs you rejected too. Such a pick writes only `[match]`, no `[alias]`.

## Browse and search

### Library/index.html

`index.html` is your library on one page. It sits next to `_todo.md` and is rewritten with it. Open
it from the synced folder in any browser. It needs no server and loads nothing from the network.
While overrides.toml can't be read, caracole leaves the page as it was, so that it doesn't lose
your transpositions and ignored songs.

[`caracole serve`](#caracole-serve) serves the same page with more on it. There the search covers
the sites, and buttons do what the file can only give you a command for. Below, "served" means that
page and "from the folder" means the file.

The header shows the library's name. That is `name` in caracole.toml (one line of 80 characters at
most), or else the name of the library folder.

The tabs are **Library**, [**Songbooks**](#the-songbooks-tab) and [**Sites**](#the-sites-tab).
Served, there are also **Journal**, which lists your requests, and [**Share**](#the-share-tab).

#### The list of songs

Songs are grouped by artist, A to Z. "The Beatles" sorts under B, and Chinese names sort by their
pinyin.

A line has the song's title and a button for each thing you can play from: a chord sheet, a Guitar
Pro file, a guitar tab (Ultimate Guitar's text tab), a harmonica tab, a game music tab and a score
you filed. A button opens its file at once. The sheet opens in [the sheet
viewer](#the-sheet-viewer). A Guitar Pro file opens in the browser where `caracole serve` can show
it, and downloads otherwise. The small marks on a button say [which sites its versions came
from](#where-each-file-came-from).

The line also shows the song's [key](#the-songs-key) and, when the song needs something, a status:
Wanted, Needs review or Ignored. Needs review means caracole isn't sure of the match. Served, a
wanted song has **Fetch**, the download icon, which looks it up now, and a song that needs review
has **Pick**.

Click an artist's name to search for them, as if you had typed it.

#### A song's card

Click a song's name, or the blank space on its line, to open its card. Click again to close it. On
a window at least 1200 px wide the card opens in a pane beside the list. On a narrower one it opens
under the line.

From top to bottom, a card has:

1. The key and where it came from, your transposition, the state of the lyrics and the day the song
   was added.
2. What needs you: a review's candidates, or where the song stands when caracole takes its audio
   from YouTube.
3. A tile for each thing to play from, and one for the lyrics.
4. **Add to a songbook…** and **⋯**, which holds info.json and, served, **Remove**. Served, there
   are also **Fetch again** and **Use LaCuerda's sheet**.
5. Files: the song's other files.
6. On the sites: a mark for each site. It is in colour when the site has the song, grey when
   caracole asked and the site had nothing, and faint when caracole hasn't asked yet.
7. Elsewhere: links to MuseScore pages that may match and, for a song without a sheet, to where
   you can search for it or buy it.
8. Progressions: click one to see your songs that play it too.

Click a tile to open what it holds. The tile says which version that is (`Ver 3 · ★ 4.86 (408) ·
in use`, with the version's rating and votes). The arrow at its end opens a drawer. The downloads
come first: the sheet's PDF, Text, ChordPro and PDF exports, the lyrics' Text and Timed (.lrc), and
each format of a score.

The drawer then lists the versions by site. For Ultimate Guitar it says how many the site has and
how many caracole keeps (`13 on UG · 3 in your logbook`). Each kept version shows its rating, how
much of the lyrics it has, and `our pick` or `your choice`. **In use** marks the sheet, and
**Open** opens any of them. LaCuerda's sheets each link to their page there.

Served, the drawer's buttons do what [`caracole versions`](#caracole-versions) does:

| Button | What it does | Option |
|---|---|---|
| **Use this one** | Makes that version the sheet, with a `[pin]` | `--choose` |
| **Back to our pick** | Drops your pin | `--clear` |
| **Fetch them** | Keeps the versions not kept yet, as many as one lookup may | `--keep-more` |

When more versions are left than one lookup may keep, the button says **Fetch 6 more**. Press it
again for the next ones. On a LaCuerda sheet, **Use this one** looks the song up and keeps that
sheet. A `[pin]` on Ultimate Guitar outranks it, so the drawer asks you to press **Back to our
pick** first. From the folder, the drawer gives the `caracole versions --keep-more` command to
run.

A song that needs review lists its candidates, numbered as [`caracole review`](#review) numbers
them. Each has the reason the matcher thought of it and a link to its page on UG. Served, the list
is a picker. From the folder, the card gives the command to run, such as `caracole review --song
'Radio Head - Crep'`. A wanted song that the index didn't match gets the same command, or **Look
in index** when served.

#### Search, Filter and Sort

The search box filters your songs as you type and asks no site. [search.md](search.md) has the
tour.

- Case and accents don't matter, and Chinese titles match by their pinyin.
- A title's initials find it: "wywh" finds "Wish You Were Here".
- A key finds its songs, however the sheet spells it. "gb minor" also finds F# minor, and "minor"
  finds every minor key. A key typed as a chord, such as "am", also finds names with "am" in them.

From the folder, the page can't ask the sites. Press Enter and it shows the `caracole search`
command to run, quoted for your shell, with **Copy**. It shows the command at once when nothing in
your library matches. Served, typing searches the sites too. A key typed on its own filters your
songs only, because the sites' indexes know no keys.

While you search, the ← at the left of the box brings the list back as it was. Click in the empty
box and it lists up to five songs you opened recently in this browser.

**Filter** opens a panel with three groups, and the list filters as you tap.

| Group | What it keeps |
|---|---|
| Status | The songs that are Found, Wanted or in Review. |
| Matches | The songs with something for any instrument you tap: Chords (a human or an auto sheet), Guitar (a Guitar Pro file or a text tab), Ukulele, Harmonica or Score. |
| Key | Major or Minor, a tonic, or both. "F# minor" and "Gb minor" are one key. |

The filters that are on show as tags under the box. Click a tag to drop it. **Clear** drops them
all and keeps the search.

**Sort** orders the list by artist, by title or by when the songs were added. When more than 40
songs show, sorted by artist or title, a row of letters jumps to each letter.

#### Songs by progression

When caracole renders a sheet, it reads each section's chords as Roman numerals and names the
progressions it knows ("the pop progression", "the Andalusian cadence"). Songs rendered by an older
caracole get theirs at the next render.

Click a progression in a card to see only your songs that play it, in any key and starting on any
of its chords. **Show all** brings the others back. A named progression matches every way of
reading it. The pop progression is I–V–vi–IV in C major and i–♭VI–♭III–♭VII in A minor. A song that
plays it inside a longer section counts too.

#### Select songs for a songbook

Select picks the songs of a songbook. **+ New songbook** in the Songbooks tab turns it on, and so
does **Add to a songbook…** in a card.

Tick the songs in the order they go in the songbook. A tap anywhere on a line ticks it, and you
can search, filter and sort between ticks. Then name the songbook and press **Make songbook**, or
pick one you already have in the bar's menu to add the songs to it. The × leaves Select and keeps
your ticks.

Served, the button makes the songbook. From the folder, it gives the command to run:

```sh
caracole songbook make 'Beach nights' 'Muse - Hysteria' 'Radiohead - Creep'
```

#### Bookmarks and scripts

The address keeps the tab, the search, the filters and the sort, so a bookmark opens the page as
you left it. You can also write these by hand:

| Address | Opens |
|---|---|
| `#tab=songbooks`, `#tab=sites`, `#tab=requests` | A tab. `requests` is the Journal. |
| `#tab=songbooks&book=Campfire` | A songbook. |
| `#q=Soda+Stereo` | A search. |
| `#by=Soda%20Stereo` | A search for an artist. Older `#artist=` links still work. |
| `#prog=I%20V%20vi%20IV` | Your songs with that progression. `#prog=vi–IV–I–V` is the same one. |
| `#key=A%20minor`, `#mode=minor`, `#tonic=E` | Your songs in a key, in a mode or on a tonic. |

For scripts, the page's data is the `<script type="application/json" id="songs">` block. Each song
there has the `key` and `key_source` of its info.json, and a `source` for its sheet and for each
file (`ug`, `lacuerda`, `auto`…).

#### The Songbooks tab

The tab lists your [songbooks](#songbooks), each with its number of songs, how many have no sheet
and the day its files were last made (`3 songs · 1 without a sheet · changed 2026-10-20`).

Open one to see its files and its set list. The files are **PDF**, **Phone page**
(`songbook.html`) and **ChordPro**. In the set list, a song's title opens its sheet. Its chip says
the key the songbook plays it in. That is its setting there ("G Dorian", "E Minor, capo 2"), or
else the song's own key. A song with no sheet says why ("No sheet yet", "Not in the logbook"). A
small guitar after a title opens or downloads the song's Guitar Pro file.

From the folder, the tab changes nothing. It lists the commands that do (`caracole songbook add`,
`move`, `set … --key G --mode dorian --capo 0`, `remove`, `rename`, `delete`), or you can edit
songbooks.toml. Served, you can drag songs into place, change where each plays, take one out, fetch
the missing ones, **Add a song**, and rename or delete the songbook. See [caracole
serve](#caracole-serve).

#### The Sites tab

The tab says what caracole has from each [site it reads](sources.md), with the last nightly run's
times and requests over the list. It sends no request itself.

| Column | What it counts |
|---|---|
| Indexed | The songs in caracole's copy of the site's index, counted as songs, not versions. LaCuerda's count is the songs caracole knows so far, not the site's total. LRCLIB and YouTube have no index. |
| In your logbook | What caracole keeps from the site for your songs, and the share of your songs that is. |
| Last run | The requests the last nightly run sent, out of the site's budget (for YouTube, yt-dlp runs). Lookups and commands run by hand aren't counted. |
| Status | **OK**, **Indexing** (the index isn't read whole yet), **Waiting out** (blocked, with until when and why), **Errors** (nothing has worked since the last error) or **Off** (`enabled = false` in caracole.toml, or YouTube without auto-chords). |

Open a line for what the site's robots.txt closes, its terms where you chose to read it anyway
(harptabs.com, gametabs.net and YouTube), caracole's pace with it and its last request.

From the folder, the figures are as of the page's last write. The nightly run writes the page
before it ends, so the file may show a run with no end yet. Served, the figures are current.

### The sheet viewer

Each sheet has a page beside it: `sheet.html`, or `sheet (auto).html` for an auto sheet. It is one
file that opens from the synced folder with no server and loads nothing from the network. caracole
makes it from the song's `.cho` at render time. For a short tour, see [Reading a song](sheets.md).

Don't put the library folder as it is behind a web server. Anyone with a synced device could add a
page there that would run as your server's own. `caracole serve` sends only the pages caracole
wrote.

#### What the page shows

Under the title, the artist's name links to the library page's search for them
(`index.html#by=Soda%20Stereo`). Tuning, Capo and Key say how you are playing the song now. With
a capo, Key names the shapes and the sound ("Em shapes · sounds F#m"). Once you move the chords
it says how far ("F#m (+2)"). An auto sheet made from a YouTube video links the video.

The tab's notes before its first section are folded to two lines, and **More** opens the rest. In
a window 1100 px wide or more, a song that fits whole in two to five columns is shown that way.
The browser's Print gives one column in light colours with a 15 mm margin, without the controls.

The key comes from the tab, or is estimated from the chords, or for an auto sheet heard in the
audio (see [The song's key](#the-songs-key)). The Key line says which. When a tab with a capo
names the key the song sounds in, the viewer takes the chords as the shapes ("C shapes · capo 6 ·
sounds F#").

#### The bar

The bar is at the foot of the page. It slides away as you scroll down and comes back when you
scroll up or tap the page. From 1200 px wide it is a toolbar under the title instead.

| Control | What it does |
|---|---|
| **−** and **+** | Move every chord and the key a semitone. |
| The key | Tap it to pick one of the twelve keys in the song's mode. The capo stays where it is. A sheet whose key caracole can't tell has no list. Under the key, the bar says what differs from the sheet as written ("capo 2 · +1"). |
| **Shapes** | Opens the necks, the harps and Harmony (below). |
| **Text** (Aa) | The text size, and the theme: Auto (your system's), Light or Dark. |
| **Scroll** | Scrolls the song by itself (below). |
| **More** (⋯) | Opens the settings. |

×, Escape or the browser's Back closes the panel on top.

**Hide controls**, in the settings, or a double tap beside the song gives the song the whole
screen. Tap the handle at the foot to get the controls back. A phone on its side does this by
itself.

The pages take no keyboard shortcuts, so the browser's keys and a Bluetooth page turner scroll
them like any page. Focused controls still answer Space, Enter and Escape.

#### A chord's card

Tap a chord to hear it and open its card. The card has:

- Its shapes: any the sheet gives ("As the tab plays it"), then up to four from chords-db. Swipe
  or use ‹ › for the next.
- Its notes with their intervals (C7: C R, E 3, G 5, Bb ♭7) and a scale to solo over it (Dm7 in C:
  D Dorian).
- **Instead, in the key**: chords to play in its place, such as a seventh on the same root or a
  chord that shares most of its notes (Am or Em for C). Tap one to see its shapes, then play it
  for every such chord in the song. Changed chords are underlined.
- **Circle & keyboard**: its notes on a circle of the twelve notes, or on a keyboard.

A sheet gives a shape in the tab's chord legend (`Cadd9 (x32033)`) or in a ChordPro `{define}`.
It counts only for the chord as written. Once you transpose or move the capo, you get
chords-db's. The shapes are from [chords-db](https://github.com/tombatossals/chords-db) by David
Rubert (MIT licence).

The sound is made in the browser, so it works offline. The speakers in the settings set its
loudness: Off, Soft, Medium (the default) or Loud. With Off, a tap only opens the card. A phone
set to silent may stay silent.

#### The settings

| Setting | What it does |
|---|---|
| **Transpose** | The same as − and +. ↺ Reset goes back to the song's `[transpose]`. |
| **Capo** | From none to the 11th fret. The song sounds the same wherever the capo is, and the chords show the shapes to play there: Em shapes with capo 2 become F#m shapes with none. ↺ Reset puts it back where the sheet has it. |
| **Easier shapes** | In an awkward key, capo frets where open shapes work (Bb: capo 1 with A shapes). Tap one. |
| **Mode** | Another mode on the same tonic, such as C major or C Dorian for C minor. Each chord moves to the same degree of the new scale, so Ab becomes Am. |
| **Chord names** | Chords, + Numerals or Numerals. **Role colours** turns the numerals' colours off. |
| **Instrument** | How chords are drawn and heard (below). |
| **All chord shapes** | A strip of every chord's shape above the song. It is on by default below 1200 px. |
| **Simplified 简体 · Traditional 繁體**, **Pinyin** | For Chinese lyrics (below). |
| **Guitar Pro tab ↗** | One row for each of the song's Guitar Pro files (not Power Tab). With `caracole serve` the file opens in the browser (see [Guitar Pro files in the browser](#caracole-serve)). From the folder it downloads. |
| **Keep the screen on** | The screen stays on until 10 minutes after your last touch, and while the song scrolls by itself. Set the minutes from Off to 60, in steps of 5. |
| **Export PDF** | With `caracole serve`, downloads a PDF of the song as you play it now, on the instrument shown. **Make mine** also saves that as the song's own version (`[version]`), where the page then starts. From the folder you get the [`caracole render --version`](#one-step-at-a-time) command to copy. |
| **Reset all** | Puts the key, the mode, the capo and the swapped chords back where the page starts. It also shows the necks, hides the pinyin and returns to Simplified. It leaves the instrument and the screen minutes. |

**Numerals** say what each chord is in the key: in C major, C F G Am are I IV V vi. Their colour
is the chord's role: home (I, iii, vi) green, moving away (IV, ii) blue, pulling home (V, vii°)
purple. Dots under a chord mean it is from outside the key. Tap a numeral, or hover over it, for
what it means and the chord's notes on a circle or a keyboard. A sheet whose key caracole can't
tell has chord names only.

**Instrument** changes how chords are drawn and heard, never the song: Guitar (the default),
Ukulele (G C E A, high G), Ukulele low G, Baritone ukulele (D G B E), Piano, Harmonica, Flute or
Recorder. The ukuleles get four-string boxes from chords-db, keep the capo and offer **Easy
keys**. The piano shows a keyboard, in root position and two inversions. The flute (concert pitch)
and the soprano recorder show each note's fingering. Their row switches the note names between
A–G and Do–Si, and the recorder between baroque and German fingering.

The harmonica is a 10-hole diatonic harp in Richter tuning. The facts under the title name the
harps that play the song, best first, each with its position. The **Harp** row picks one and
lists the holes for each chord: "draw 2–5", "blow 1–3 (as C)" where the harp has only the plain
chord, or "not on this harp". It also links the song's harmonica tabs.

The piano, harmonica, flute and recorder take no capo, so their chords are named as they sound.

**Chinese lyrics** get two more rows. **Simplified 简体 · Traditional 繁體** picks the characters
for the whole page. Every sheet starts in Simplified, whichever it is written in. caracole
converts with OpenCC, which is not always right, so a sheet reads best in its own script.
**Pinyin** puts each character's reading over it, with tone marks. It is off at first.

`sheet.pdf` is in Simplified, and `sheet (Traditional).pdf` sits beside it (`sheet (auto,
Traditional).pdf` for an auto sheet, `songbook (Traditional).pdf` for a songbook with a Chinese
song). The page's PDF link and Export PDF follow the characters on screen. No PDF has pinyin, but
the browser's Print does. The `.cho` stays as written.

#### Necks, harps and Harmony

**Shapes** opens an overlay with up to three tabs. From 1200 px wide it is a rail left of the
song, which Shapes shows and hides. On a smaller screen it slides up over half the screen.

**Guitar** draws a neck for each chord of the song, with every shape of the chord in a colour of
its own. Click a shape to play that one from then on.

**Harmonica** puts the twelve harps on a circle of fifths and marks the ones that play the song's
chords with their position. Tap one to see what it plays ("Plays A, D and Em; E as Em."), the
key's scale on its ten holes and the holes for each chord. Transposing moves every harp, and a
capo doesn't. It opens on the harp of the song's harmonica tab, if the song has one.

**Harmony** is there when caracole can tell the song's key. It shows the key's scale on a neck,
then each section's progression in numerals with how often it is played ("I–V–vi–IV ×4"), how the
section ends (an authentic, plagal, half or deceptive cadence) and its name when it has a common
one. caracole knows more than twenty named progressions, among them the pop progression
(I–V–vi–IV), ii–V–I, the 12-bar blues and the Andalusian cadence. A longer progression says which
of them it holds ("contains the pop progression ×2").

Tap a progression to go to its section. **▶** plays it, one chord per bar, at the tempo above the
list (80 bpm at first), and **■** stops it. **Songs with this progression** opens the library
page on the songs that have it (`index.html#prog=I%20V%20vi%20IV`).

#### The version line

The line under the artist says what you are reading: "Chords · Ver 7 of 13 · acoustic · ★ 4.80
(1,204)", or "Chords · LaCuerda's sheet". Tap it for the list.

**Chords** has every version Ultimate Guitar lists, in rank order, each with its rating. It marks
the sheet, the kept versions and the one you are reading. The song's other files follow: a
harmonica tab opens its page, a text tab or a score's PDF opens the file, and a Guitar Pro file
downloads, or opens in the browser with `caracole serve`.

With `caracole serve`, the list has **Keep** on a version not kept, **Make this the one** on a
kept version's page, and **Back to our pick** while a `[pin]` of yours chooses the sheet. From the
folder, each shows the [`caracole versions`](#caracole-versions) command to copy instead, and a
version not kept links to its UG page.

#### Auto-scroll

**Scroll** counts down 3 seconds (press the count to start at once), then scrolls the song at a
steady pace. A pill steers it: − and + change the speed (1 to 30), ❚❚ pauses, ▶ goes on after
another countdown, and × ends it. Touching the page, the mouse wheel, a key that scrolls or a
chord's card pauses it, and so does the end of the song.

When the song has timed lyrics (LRCLIB's or Megalobiz's), the line being sung is lit while it
scrolls. Tap a line's words to set the lyrics' clock there. No recording plays, so the light
keeps the song's own times and doesn't follow your playing. There is no light in a songbook, or
when caracole can't match the timed lyrics to the sheet's lines.

#### What the page remembers

The browser remembers each song's key, mode, capo, chord names, swapped chords, chosen shapes,
text size, scroll speed and volume. Some choices are yours, not the song's, and are kept once for
every sheet, songbook and harmonica tab: the necks hidden, the instrument, the pinyin, the
Chinese characters, the theme and the minutes the screen stays on.

The page also writes all of this into its address, so you can bookmark or share it. Under
`caracole serve`, where the browser stores nothing, the address is what keeps your settings
through a reload.

    sheet.html#t=2&mode=aeolian&fs=20&speed=8&vol=1

| In the address | Meaning |
|---|---|
| `t=2` | Transposed two semitones up. |
| `mode=aeolian` | The mode. |
| `capo=3` | The capo's fret. |
| `nm=both`, `nm=numerals` | Chord names with numerals, or numerals only. |
| `at=3.2` | Chord 3 plays its third shape. |
| `alt=ionian.0.7.maj7.` | A chord played instead of another: mode, chord, root, suffix, bass. |
| `fs=20`, `speed=8`, `vol=1` | The text size, the scroll speed and the volume (0 is Off, 3 is Loud). |
| `inst=ukulele` | The instrument: `ukulele`, `ukulele-low-g`, `baritone`, `piano`, `harmonica`, `flute` or `recorder`. |
| `necks=0`, `py=1`, `trad=1` | The necks hidden, the pinyin shown, Traditional characters. |
| `theme=dark` | The theme, when it isn't Auto. |
| `awake=15` | The minutes the screen stays on, when they aren't 10. `awake=0` is Off. |

An address with `t=`, `mode=`, `capo=`, `alt=` or `at=` plays that version, not the song's own.
Under `caracole serve`, a sheet opened from the library page starts without the choices that are
yours, because the library's links don't carry them.

On Android, a file manager that opens the page through a `content://` address can break its links
to the song's files. A browser, or an HTML viewer that opens the file directly, works.

### The harmonica tab page

Each harmonica tab a song keeps, `harmonica-1.txt`, gets a page beside it at render time,
`harmonica-1.html`. It looks like the sheet viewer and opens from the synced folder with no
server. The Harmonica row of the sheet's settings and the song's line on the library page link to
it. `caracole remove` deletes it with the song.

Each hole sits over the syllable it is played on: a blow ("4"), a draw ("−4"), a bend ("−3′").
Brackets hold holes played together: "(4 5)" is a chord, "{−4 −5}" a shake, "[−2 −5]" a split.

The harp decides the key the holes sound in. The page starts on the harp that plays with the
record, the one that puts the most of the tab's sung notes on the chords of the song's sheet.
Failing that, it takes the harp the tab's words name ("I use an A harp"), then the key
harptabs.com's page names, then the first harp for the song's key, then a C harp.

| Control | What it does |
|---|---|
| **−** and **+** | Change the harp a semitone. The holes stay. The sound and the notes' names change. |
| **Shapes** | Opens the sheet viewer's overlay on its Harmonica tab. Its harp is the page's. |
| **Notes** (♪) | Shows each hole's note on that harp ("F#6"). |
| **Text**, **Scroll** | As in the sheet viewer. |
| A hole, **▶** | Tap a hole to hear it. ▶ at a line's end plays the line hole by hole, a beat each, since the tab has no rhythm. |
| **‹** by the title | Goes back to the song's sheet, or to the library for a song with none. |
| The version line | "Harmonica · Tab 1 of 2". Tap it for the same list as on the sheet. |
| **Tab as text**, at the foot | Opens `harmonica-1.txt`. |

The page has no settings. A double tap beside the tab hides the controls, as on a sheet, and the
screen stays on for the minutes you set there. The address keeps the harp, Notes, the text size
and the scroll speed (`harmonica-1.html#harp=A&notes=1&fs=20`), and `theme=` and `awake=` as a
sheet's does.

#### How a tab is read

No two tabbers write holes quite alike. caracole reads each tab in every notation it knows and
keeps the one that explains the most of its lines as notes a harmonica plays. When two are close,
the commoner one wins.

| Notation | How it writes holes |
|---|---|
| `signs` | harptabs.com's own: "4" is a blow, "-4" a draw, and bends are "-3b", "-3'", '-3"' (a whole step), "b-3" or "-b3". |
| `brackets` | A draw in brackets, as Spanish tabs write it: "(5)", "(3)b". |
| `letters` | "4B" and "5D", or "3b" blow and "3d" draw, with "*" for bends and "-" between notes run together. |
| `signs after` | The sign after the hole: "6+", "6-". |
| `barrett` | David Barrett's: a hole alone is drawn, "4+" is blown. |
| `legend` | The tab's own legend, two or more lines like "b= blow" or "(w) = Wah effect". It can add effects, such as "(w)" for a wah or "(h)" for a hold. |

The line under the harp says how the tab was read: "Read as: b blow · d draw · * bend · - joins,
from the tab's own legend", or "…, guessed (0.86)" with how sure caracole is, or "…, as you set
it". What the notation can't read stays in its place as written, muted. A line caracole isn't sure
of is shown as its text. So is a whole tab it isn't sure of, or one harptabs.com calls chromatic,
since caracole knows the ten-hole harp only.

If caracole read a tab wrong, pin a reading. With `caracole serve`, click the last words of the
Read as line ("guessed (0.86)"), or **Change how it's read** at the foot of the page. The server
lists the readings, best first, each with a button. **As harptabs writes it** is among them, and
**Back to caracole's guess** undoes your pin. From the folder, run `caracole harmonica` (below).
Either way the pin goes into `[harmonica]` in [overrides.toml](#overridestoml-your-decisions) and
the song's pages are made again.

#### caracole harmonica

`caracole harmonica "ARTIST - TITLE"` says how each of the song's harmonica tabs is read, then the
readings caracole weighed, best first, each under the name you would give `--as`. It only reads,
so it doesn't wait for another caracole.

    $ caracole harmonica "Cowboy Bebop - Spokey Dokey"
    harmonica-1.txt: read as b blow · d draw · * bend · - joins · (h) hold · (w) wah, from the tab's own legend (Q 0.96)
      legend       Q 0.96  b blow · d draw · * bend · - joins · (h) hold · (w) wah
      letters      Q 0.86  b blow · d draw · * bend · - joins
      …

| Option | What it does |
|---|---|
| `--as NOTATION` | Reads the tab so, whatever caracole guesses: `signs`, `brackets`, `letters`, `signs after`, `barrett` or `legend`. `legend` is refused for a tab that has none. |
| `--symbol SYMBOL=MEANING` | Reads one of the notation's symbols another way: `--as signs --symbol "*=bend"`. Repeatable. |
| `--clear` | Takes your pin out, and caracole guesses again. |
| `--tab harmonica-2.txt` | Names the tab, for a song that keeps more than one. |

A meaning is one of blow, draw, bend, double bend, triple bend, overblow, slide, joins, together,
hold, wah, vibrato, shake, trill, glissando, staccato or mark. A "4" in the symbol stands for the
hole, to say where the symbol is written: `"(4)=draw"`, `"4=blow"`.

`--as` and `--clear` write overrides.toml under caracole's lock, waiting for it as a lookup does,
then make the song's pages again. A tab the song hasn't got, a notation caracole doesn't know, or
`--as` with `--clear` exits 2 and writes nothing.

### Where each file came from

Each file on the pages has a mark for its source.

| Mark | Source |
|---|---|
| A site's own icon | That site. Lyrics have the icon of the one site that gave them. |
| YouTube's icon | An auto sheet made from audio caracole took from YouTube. |
| ♪ | An auto sheet made from audio you bought. |
| ↓ | A file you filed from `_inbox/`. |

A site's icon is its favicon. The nightly run's icons step asks each site for it once, from the
first night the library has something from that site. The icon is kept in the cache folder as
`icons/<site>.png`. caracole reads only a PNG or an ICO of up to 256 KB, never an SVG, and keeps
the image alone, at most 256 pixels a side and 16 KB. The pages inline it, so they still load
nothing from the network.

A site whose icon can't be had shows a small lettered badge instead, such as UG, LC or YT, and is
asked again a week later. The nightly run doesn't ask YouTube for its icon. `caracole icons` asks
now, YouTube included (see [One step at a time](#one-step-at-a-time)). If you delete `icons/` in
the cache folder, caracole makes the icons again from its cached answers, with no request.

### caracole search

    caracole search [QUERY]... [--limit N] [--add N] [--key KEY] [--artist NAME]
                    [--title TITLE] [--progression NUMERALS]

`caracole search` looks through your library and five offline indexes, the copies of the sites'
catalogues that caracole keeps on your computer. It sends no request.

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

    On gametabs.net (offline index)
      nothing matches

    On iReal Pro's forum (offline index)
      nothing matches

The groups always come in this order:

| Group | What it lists | Under each hit |
|---|---|---|
| In your library | Your songs that match, whatever their status | |
| Removed from your library | Songs you removed, only when one matches | `caracole add`, to bring it back |
| On Ultimate Guitar | Songs with chords, text tabs or ukulele chords, numbered | `caracole add` |
| On LaCuerda | Songs, numbered on from Ultimate Guitar's | `caracole add --lacuerda` |
| On harptabs.com | Harmonica tabs | `caracole get --harptabs` |
| On gametabs.net | Game music tabs | `caracole get --gametabs` |
| On iReal Pro's forum | Chord charts | `caracole get --ireal` |

A `caracole get` line looks the song up now, keeps that tab or chart, and records your pick in
overrides.toml (`[harptabs]`, `[gametabs]`, `[ireal]`).

A group says so when its site is turned off in caracole.toml or its index is still empty. While a
site is still being read, its group ends with how far it has got and what reads the rest.

#### Search options

| Option | What it does |
|---|---|
| `QUERY` | Words of the artist, the title, or both. |
| `--limit N`, `-n N` | Shows up to N hits from each place. The default is 10. |
| `--add N` | Adds hit N to wanted.txt. |
| `--artist NAME` | Lists one artist's songs. |
| `--title TITLE` | Lists the songs of one title, by any artist. |
| `--key KEY` | Lists only your songs in that key. |
| `--progression NUMERALS` | Lists only your songs that play that progression. |

These exit with status 2 and write nothing:

- `--title` with QUERY words
- `--key` with `--artist`, `--title` or `--add`
- `--progression` with QUERY, `--key`, `--artist`, `--title` or `--add`
- a KEY that is no key, or NUMERALS that are no progression
- `--add N` for a hit the search doesn't show, or for a hit under one of UG's catch-all artists

`--add N` takes the number the same search printed: Ultimate Guitar's hits first, then LaCuerda's.
It adds the song as [`caracole add`](#caracole-add) does and prints the same line. A LaCuerda hit
also becomes your pick there. N must be a hit the search shows, so raise `--limit` to reach a later
one. A hit your library already has under another name is left alone.

`--artist NAME` lists your songs by that artist, then theirs in each index. Ultimate Guitar's songs
come most tabbed first and are numbered for `--add`. When there are more than `--limit`, it says
how many (`… and 365 more: see them with --limit 368`). LaCuerda's songs come most popular first,
and harptabs.com's most viewed first.

NAME is the whole name, in any form. `--artist 宋冬野` and UG's "Song Dongye" are the same artist,
but `--artist lynyrd` names no one. QUERY words given with it search that artist's titles, as in
`caracole search --artist oasis live`. For an artist the Ultimate Guitar index lacks, it prints the
`[artist_url]` line to paste (see below).

`--title TITLE` lists the songs of that whole title by any artist, most tabbed first. With
`--artist` it searches that artist's titles. Neither option shows the removed songs.

#### What matches, and what comes first

A title alone or an artist's name alone is enough.

- Case, accents and punctuation don't matter (`AC/DC`, `R.E.M.`), and a typo still matches.
- Chinese is compared as pinyin, whole words only. 斑马 finds a title written `ban-ma` or `banma`,
  but not the letters inside `suburban-male`.
- The Ultimate Guitar index knows no ratings, so the song with the most tabs comes first:
  Radiohead's Creep before Stone Temple Pilots'.

When the query is an artist's name, and one of their songs has more tabs than any song titled like
the query, the artist leads. `caracole search oasis` starts with `Oasis, an artist: 195 songs
(1,193 tabs)` and their three most tabbed songs. The songs titled like "oasis" follow in the same
numbered list. Otherwise the songs lead, and the artist gets one line after them: `Also an artist:
Wonderwall, 9 songs (13 tabs)`.

One word of a name finds an artist too. `eagles` also lists Eagles of Death Metal, and `skynyrd`
leads with Lynyrd Skynyrd.

- The word must be whole and at least three letters long. `horse` finds no Seahorses, and `lynyr`
  finds no one.
- A word in more than 300 artists' names ("the", "band", "john") finds only the artist whose whole
  name it is, such as The Band.
- An artist whose whole name is the query comes first, unless one found by a word has 50 songs or
  more and over four times as many. `dylan` lists Bob Dylan (638 songs) before Dylan (27).

#### Did you mean

When nothing matches well, and your words are spelled close to an artist's name or a song's title,
the search ends with up to three suggestions. An artist comes with the command that lists their
songs (`lynrd` suggests Lynyrd Skynyrd), and a song with the command that adds it:

    $ caracole search hotl califronia
    …
    Did you mean Hotel California by Eagles?
      Eagles - Hotel California · Ultimate Guitar · 44 tabs: caracole add "Eagles" "Hotel California"

Suggestions come from Ultimate Guitar's, LaCuerda's and harptabs.com's indexes. Each word must
start with the right letter, and a word of fewer than four letters must be spelled right. Chinese
gets no suggestion, and a word in more than 5,000 tabs (`lovee`) suggests no title.

#### Artists the index can't see

Ultimate Guitar's sitemaps list some artists only by a bare id, usually those with accented or
non-Latin names such as Joaquín Sabina or 宋冬野. The index can't see their tabs. When nothing
matches well, or the query has such letters, the search says so and prints the `[artist_url]` line
to paste into [overrides.toml](#overridestoml-your-decisions), with the address of the artist's
page or of one of their tab pages.

The `[artist_url]` header is printed only while your file has no such table. If the file already
has that artist's page, the hint says so instead. If the query could be a title, the hint adds that
caracole needs the artist too (`caracole add ARTIST "斑马"`). No site is asked who sang it.

#### In your library

Each song shows its status, its key when it has one (`Key G major (from the tab)`) and its folder.
A song with a sheet is tagged with where the sheet came from, for example `[UG]`, `[LaCuerda]`,
`[auto]` for chords worked out from audio, or `[YouTube]` when that audio came from YouTube. A song
in review also lists its first three candidates, and [`caracole review`](#review) settles it.

Songs you took out with `caracole remove` follow in their own group when your words match one. Each
has the date it was removed and the `caracole add` line that brings it back. `--add` never acts on
a removed song.

#### On Ultimate Guitar

A hit you already have says `in your library` in place of its `caracole add` line.

The artist pages caracole has read (see [caracole fetch](#one-step-at-a-time)) are searched too,
including the tabs that the sitemaps list by bare id. Names are compared in each script UG writes
them in, so "Song Dongye (宋冬野)" matches both. A hit from such a page links to its best tab,
shows UG's rating (`rated 4.8 (120 votes)`), and names the artist the way your songs do.

Ultimate Guitar files some songs under catch-all artists such as `misc-musicals` (see
[caracole match](#caracole-match---dry-run)). A catch-all is never listed as an artist. Its songs
are also matched on the title alone, so `caracole search epic not sorry for loving you` finds
`misc-musicals/epic-the-musical-not-sorry-for-loving-you` first. That hit has no `caracole add`
line, because the song's artist would become "Misc Musicals". It tells you to add the song as you
know it, then pick the hit in `caracole review`.

#### On LaCuerda

LaCuerda's index holds every artist in the listings the nightly run has read so far, and the songs
of the artists whose page caracole has read (see [caracole lacuerda](#one-step-at-a-time)). It also
keeps the answers of LaCuerda's own search (`caracole lacuerda --search`, or the search bar of
`caracole serve`).

- A song's `caracole add --lacuerda` line makes that sheet your pick, so the nightly run keeps it.
  A song with no chords there (`1 version, no chords`) is added by its names alone.
- An artist the query names gets a line with their song count, then their most popular songs with
  chords. If caracole hasn't read their page, the line gives the command that does, in one request:
  `caracole lacuerda --artist joaquin_sabina`.
- Until the nightly run has read a letter's whole listing, the index can't tell whether LaCuerda
  has an artist under it. If the query finds none there, the group ends with `LaCuerda hasn't
  listed E yet` and the command that reads that name's page now: `caracole lacuerda --artist
  "estopa"`. It sends one request for each spelling it tries, usually one.

Names also match with their words run together ("rockstar" finds Los Rock Star) or as far as you
have typed ("joaquin sab").

#### On harptabs.com

Its index holds the artists of its sitemap and the tabs on the artist pages caracole has read.
`caracole harptabs --index` reads the rest (see [caracole harptabs](#one-step-at-a-time)).

- A song is the tabs of one title by one artist, and the key shown is the most viewed tab's.
  Words in brackets don't count: "Piano Man (C Harmonica)" is Piano Man.
- An artist the query names gets a line too, with their most viewed songs. For a page caracole
  never read, it gives the command that reads it in one request:
  `caracole harptabs --artist artist/1178/billy-joel`.
- An artist page lists only their 30 most viewed tabs. Their other tabs, and tabs whose artist
  caracole doesn't know yet, are found by their whole title alone and marked `same title, maybe
  another song`.

#### On gametabs.net

Its index holds its sitemaps and the game pages caracole has read. `caracole gametabs --index`
reads the rest (see [caracole gametabs](#one-step-at-a-time)).

A track is listed with its game as the artist. You find it by the game's name, the track's title,
or a composer:

    [gametabs] Hollow Knight - Resting Grounds · 2 tabs, Guitar, by Christopher Larkin

Only a game's page says who composed its tracks. A game whose page caracole hasn't read is named
from its address (`Final Fantasy Vii`), and so are its tracks. `--artist NAME` lists the tracks of
the game or the composer that NAME names.

#### On iReal Pro's forum

Its index holds the charts in the thread pages caracole has read: the forum's playlists
(`caracole ireal --index`, see [caracole ireal](#one-step-at-a-time)) and the threads read for your
songs. A chart is listed with its composer as the artist, first name first, and you find it by
title or by composer. Its line links to the best chart's post, and its `caracole get --ireal` line
keeps that chart as the song's sheet.

After the charts come up to eight threads that caracole hasn't read, whose name holds your words.
Each is a possible match. Names that begin with your words come first, then names that end with
them (a composer's threads, for two words or more), then the rest, the oldest first. Words of fewer
than three letters find no thread.

A thread's name doesn't say where its title ends. caracole takes its last words as the artist when
they name one it knows, so `misty-roses-tim-hardin` is Misty Roses by Tim Hardin. The line then
says `a thread not read yet, named from its name`, and its command reads the thread and keeps its
chart. When caracole can't tell the artist, the line says `a thread not read yet, its name alone`
and the command ends in `ARTIST TITLE`, for you to fill in.

`--artist` lists the threads whose name ends with it, and `--title` those whose name begins with
it. If the thread you fetch holds no chart of that title, nothing is kept and the lookup says so:
`iReal Pro's forum: no chart titled “Blue” in that thread`.

#### By key or by progression

`--key KEY` lists only your songs in that key (see [The song's key](#the-songs-key)), up to
`--limit` of them, with a count of the rest. With QUERY it filters the matches. Without it, you get
all your songs in the key, by name.

Write KEY the way tabs do, in either case: `"A minor"`, `Am`, `am`, `F#`, `"Bb major"`, `bbm`
(B flat minor), `"La menor"`. Any spelling of the same key matches, so `Gbm` finds F# minor. The
offline indexes have no keys, so `--key` leaves them out.

`--progression NUMERALS` lists your songs that play a progression, in any key and starting on any
of its chords, up to `--limit` of them. It reads what caracole found in each sheet when it last
rendered it (see Songs by progression, under [Library/index.html](#libraryindexhtml)). The offline
indexes have no chords, so they aren't searched. Each song comes with its status, the sections that
play the progression, the key its sheet was read in and its folder.

NUMERALS can be:

- Roman numerals, two chords or more, upper case for major and lower case for minor, counted on the
  tonic's major scale: `"vi IV I V"`, `"vi–IV–I–V"`, or `"i bVII bVI V"` with b or ♭ for a flat.
  Qualities and extensions are left aside, so `"Imaj7 vi7 ii7 V7"` is I–vi–ii–V.
- A minor key written its own way, with a minor tonic and no flat. A major III, VI or VII is then
  read as ♭III, ♭VI or ♭VII, so `"i VII VI V"` is the Andalusian cadence.
- A progression's name, or words of it: `andalusian`, `"the pop progression"`, `blues`,
  `"royal road"`.

A name finds every reading of its progression, such as the pop progression in a major key and in
the relative minor, and the songs that play it inside a longer section. Words of fewer than five
letters (`"the road"`) name nothing unless "progression" or "cadence" is among them. `minor` alone
names nothing, and neither does a song title such as `creep` without "progression".

### caracole serve

`caracole serve [--address ADDRESS] [--port PORT] [--allow-host NAME]… [--label TEXT]`
serves the library page over HTTP, at `http://127.0.0.1:8737/` by default, and adds what the file
on disk can't do. There is no sign-in. Anyone who can reach the server can read the library and
request songs, so keep it on a network you trust (see Who can reach it, below).

Every page it serves names the library after caracole's name, in the header and the tab's title.
When the library isn't your usual one, the pages caracole serve writes itself carry a badge
beside the name, and the server prints it when it starts:

- `--label TEXT` sets the badge (40 characters at most), for example `--label Demo`.
  `--label ""` shows none.
- Without `--label`, a library whose config file, library folder or state folder lies in a
  temporary folder (`/tmp`, `/var/tmp`, `/dev/shm`, `$TMPDIR`, `$TEMP`, `$TMP`) is badged
  **Scratch library**. The service's library in `/var/lib/caracole` and one you run from your
  home folder never are.

Sheet viewers and songbook pages are files from the library, sent as they are, so they have no
badge.

#### Searching

The search box filters your songs as you type. From the third letter (the second for Chinese) it
also searches the sites' offline indexes, a moment after you stop typing. No Enter is needed.

Results come under the same artist headers as the list. A header counts your songs by that
artist and, for an artist the query names, what the indexes list ("Estopa · you have 2 · UG 60 ·
LaCuerda 159 · Guitar Pro 12"). Under each artist you see:

- your matching songs (up to five, with All N of your songs when more match), and songs you
  removed;
- **Ultimate Guitar**: eight songs, plus each named artist's three most tabbed songs and
  "+ 57 more by Estopa", which lists the rest fifty at a time;
- **LaCuerda**: the named artist's most popular songs with chords and "+ N more", then five
  songs. For an artist whose page caracole hasn't read, the group offers **Read their page**,
  which queues `caracole lacuerda --artist` (one request at the lookup pace);
- **gtptabs.com**: five songs with a Guitar Pro file;
- **harptabs.com**, **gametabs.net** and **iReal Pro's forum**, under the artist, the game or
  the composer (below);
- **MuseScore** pages last, under their own header, matched by title only.

A song several sites have is one line, with each site's mark and counts ("chords ×9 · LaCuerda ×3
· Guitar Pro file"). The indexes hold no ratings, so lines show counts, not stars. A site's song
that you already have is your own line.

**Filter** works on the results too. Its Matches keep sites' songs by what the site has (UG's
chords, tabs or Ukulele Chords, LaCuerda's chords, an iReal Pro chart, a Guitar Pro file, a game
tab, a harmonica tab, a MuseScore score). With Harmonica on, "yoko kanno" shows her harmonica tabs
and nothing else. Status, Key and progressions apply to your songs only. The results' head says
what the filters keep, with **Show all**.

A progression typed as numerals ("vi IV I V") or named ("andalusian", "the pop progression",
"blues") finds your songs that play it, first in the results, with **Show them**. Short words such
as "pop" or "minor" are read as words.

A row for one instrument has a badge: **Ukulele** (UG's Ukulele Chords), **Harmonica**
(harptabs.com), **Score** (MuseScore), or **Guitar**, **Bass**, **Mandolin**, **Banjo** for a
gametabs.net track. Chord sheets have no badge, since they suit every instrument.

Searching asks no site. It reads the local indexes (5–25 ms a query, up to about 0.15 s for
common words), takes no lock and spends no budget. Two exceptions follow: LaCuerda's own search,
and a YouTube video suggested when the sites have no sheet. The address keeps the search
(`#q=wonderwall&all=1`).

##### More sites in the results

- **harptabs.com**: an artist's header shows `Harmonica 98` and a line `harmonica tab ×4`. Its tabs
  are under the line's "⋯", most viewed first, each with its own Fetch. The line's Fetch keeps the
  most viewed (a lookup with `--harptabs`, recorded under `[harptabs]`). A group ends with "+ 1
  more by billy joel on harptabs.com", or offers to read the artist's page (one request,
  `caracole harptabs --artist`). Tabs no artist page names come after MuseScore's, by title.
- **gametabs.net**: tracks appear under their game ("Hollow Knight"), `game tab ×2`, with
  instrument badges. Fetch works as for harptabs.com (`--gametabs`, `[gametabs]`).
- **iReal Pro's forum**: charts appear under their composer (`iReal Pro chart ×2`). Threads its
  sitemaps name but caracole hasn't read appear too, up to eight, under the by-line their name
  gives, marked `thread not read yet`. Fetch reads that thread and keeps its chart (`--ireal`,
  `[ireal]`). Nothing is asked of the forum before you press it. A thread with no by-line shows
  alone in an iReal Pro group, with no Fetch.

A site turned off in caracole.toml shows nothing.

##### The row of marks

Under the box, a row of marks says what each site found: your songs first, then each site with
results, by its icon (or UG, GT, LC, MS, HT, GM) and a count, then one quiet mark for the rest ("0
on 4 more"). Hover a mark for details. An amber mark with a pie cut means caracole has read only
part of that site's index so far ("7 on LaCuerda · index in part, up to C"). The rest mark's
tooltip lists every site at 0 and why ("index empty", "turned us back", "off"). On a wide screen
each site is named in full while the row fits. iReal Pro gets a mark once caracole has read its
sitemaps or a thread. When nothing is found anywhere, the row is gone.

##### When nothing is found

The list ends with a line for the query and a **Request** button, which opens the request form
filled in from the query. Tap the line's name to unfold more:

- **Ask LaCuerda · 1 request**, while LaCuerda's listings don't yet reach that letter;
- **Why isn't it found?**: UG's sitemaps name some artists only by a number (Joaquín Sabina,
  Maná, 宋冬野), so caracole can't see their tabs. It shows the `[artist_url]` lines to paste into
  overrides.toml, or `caracole add ARTIST "lynrd"` for a title.

When the words are spelled close to an artist's name or a song's title (as
[caracole search](#caracole-search) chooses them), the closest come first as "did you mean"
bands, such as "Stephen Foster · 7 songs on UG · you have 1". **Their 7 songs on UG ›** lists
their songs with no request.

##### LaCuerda's own search

LaCuerda's index holds every artist in its listings, but only the songs of artist pages caracole
has read. LaCuerda's own search finds the rest. Once the query has been unchanged for 1.5 s, the
page sends it by itself, one request at the lookup pace (`caracole lacuerda --search`, shown in
the Journal), when all of these hold:

- the query has a word of 4 letters or more;
- neither your library nor LaCuerda's index already matches it well;
- it wasn't asked in the last 30 days (words in any order);
- LaCuerda isn't cooling down after a block;
- fewer than 20 such searches went in the last hour, within the hour's 60 lookup requests.

A line under the results says "Searching LaCuerda for “…”…", then what came back, and the songs
join their artists' groups. **Enter** sends it at once, even past the hourly 20 (but within the
hour's lookups). Once the 20 are spent, the line offers **Ask LaCuerda for “…” (1 request)**. A
search that failed isn't sent by itself again for an hour, and none is while three failed in the
last hour. Only the button asks then. Only one LaCuerda button shows at a time. The Look up page
works the same way.

For a query that names no artist LaCuerda's index knows, while the nightly run hasn't finished
reading the listings for that letter, the results offer **Ask LaCuerda for “estopa” (1
request)**. It sends the search, or else queues `caracole lacuerda --artist estopa`, then lists
their songs or says `Not found: LaCuerda has no page for estopa.` or `Not read: …` with a link to
the output. A title ("creep") or a name LaCuerda lists under another spelling gets no offer.

##### Keys in the search box

Enter never fetches a song. It moves to the first result (and may send LaCuerda's search, above).
↓ goes to the first result's button. Escape returns to your songs with the search kept. Press it
again to clear the search, and once more in the empty box to leave it. The box's × clears it and
keeps you searching. The ← at the box's left, or Back, leaves the search.

#### Fetch

**Fetch**, the download icon at a result's end, looks the song up at once. Nothing is asked before
you press it:

- a song on Ultimate Guitar is looked up as `caracole get --ug …`, recording the pick under
  `[match]` so nothing waits for review. Its gtptabs.com stage downloads a Guitar Pro file if the
  song has none;
- otherwise a LaCuerda song is looked up as `caracole get --lacuerda …`, keeping that sheet
  (`[lacuerda]`);
- otherwise caracole looks it up by name, as `caracole get` does.

A song of yours with no line on the page has **Fetch again**, and a removed one **Add again**.

Tapping a result's name or blank space unfolds what each site has, and asks no site: UG's
versions ("Chords 2 of 13", each with an "on UG" link, fetched as `--tab …` and recorded as
`[pin]`), LaCuerda's page with **Fetch with this sheet**, and gtptabs.com's page. MuseScore pages
are links only, since caracole never fetches from MuseScore.

Tapping an artist's name anywhere searches for them, which asks no site.

A song your library already has, even under other names (UG writes AC/DC as "Acdc"), shows as
your own line. In the results, songs you have a sheet for stand out on a tinted background.

A song your library doesn't have, from UG, LaCuerda or gtptabs.com, also has **Add for tonight**
under its line. It goes into wanted.txt under the site's names, and the nightly run looks it up.
A LaCuerda-only song is added as `caracole add --lacuerda …`. UG's `misc-…` names belong to no
one, so request those by name.

A song you removed that the query matches shows as "Removed 2026-10-20" with **Add again**. That
writes its line back into wanted.txt (see [caracole remove](#caracole-remove)) and looks it up.

##### The lookup page

`/lookup` still works, though no header links to it. It runs the same search, and its Fetch shows
the sheet on the page as it arrives. Its Enter acts on the song you clearly meant (opens yours,
looks up a UG song), or opens the leading artist's songs, or does nothing. It shows "Did you mean"
rows and the same row of marks. `/lookup?q=WORDS` opens it with that search, and a lookup posted
without JavaScript lands there. Here your song keeps its own row with Fetch again, and each site's
row of it has its own Fetch again.

#### Fetch again, and Use LaCuerda's sheet

In a song's card, **Fetch again** looks the song up anew (one `caracole get`). **Use LaCuerda's
sheet**, when LaCuerda has one, looks it up keeping a LaCuerda sheet, as
`caracole get --lacuerda` does: the one you picked (`[lacuerda]`), else the best LaCuerda sheet
caracole saw and didn't keep, else the one the search finds. It goes once the kept sheet is
LaCuerda's. Ignored songs have neither, and the file on disk never does.

#### Request a song

Under the results, "Not in the list? Request it by name" opens a form with the artist, the title
and, optionally, the album and length. It is filled in from your search until you type into a
field, with the names read as [one text](#one-text-read-as-a-songs-name) is: "Muse - Hysteria",
"Qué problema by Silvana Estrada". `POST /request` and `POST /lookup` also take one text, `q`, and
refuse one whose artist isn't clear. The song goes into wanted.txt at once, as
`caracole add ARTIST TITLE` writes it, then `caracole add` runs.

With **Fetch** ticked (the default), the song is looked up at once instead, as `caracole get`
does: its sheet in seconds, then the PDF, the lyrics and the rest. Each wanted song's line has
Fetch too, except a song that needs review, which has **Pick** instead.

#### A sheet from a YouTube video

Where caracole can make chords from audio (`packages.autochords`, its model files and yt-dlp, and
YouTube not turned off), the request form has a **YouTube video** field. Search for "Nick Cani -
Vikingos veganos", press Request, paste `https://www.youtube.com/watch?v=lzN7Thn3FV4`, and
Request. caracole then makes the sheet from the video instead of a lookup:
`caracole youtube --sheet --progress` (see A sheet from a video, now, under
[Audio from YouTube](#audio-from-youtube)). A song you have with no human sheet, not ignored and
with no purchase linked has the same in its card, **From a YouTube video**, whose Make the sheet
replaces any YouTube audio it had.

The line shows a bar of steps: Song, Audio (YouTube), Lyrics, Words, Chords and PDF. Words is the lyrics
heard from the audio, only when no lyrics site has them. The audio and the
chords say what they are doing ("Chords · 4 of 5 · finding the beats"). When it is Ready,
the title opens `sheet (auto).html` and the Journal says what the sheet holds ("Chords over the
lyrics.", "Chords only, no lyrics."), or why the lyrics wait. If the words couldn't be heard here
it says why ("Chords only, no lyrics: the words couldn't be heard here (…).") and over a song with
nothing sung, "Chords only: nothing sung was heard." The nightly run asks LRCLIB again
and remakes the sheet with them.

- **Not made yet**: a block, a cooldown, a spent budget or a network error. Try again.
- **Failed**: YouTube won't give the video ("can't download this video; try another"), or
  auto-chords can't read the audio.
- Refused before anything is queued: a song with a human sheet ("… already has a sheet."), an
  ignored one, one with audio of its own (bought or given), or a link that isn't a YouTube
  video's.

One runs at a time per song. Where chords can't be made, the form has no video field and says why
("No sheets from YouTube here: auto-chords isn't installed.").

#### A sheet from an audio file

Where caracole can make chords from audio (`packages.autochords` and its model files; no YouTube, no
yt-dlp), the search bar has a **+** ("Make a sheet from an audio file"). Press it and choose a file,
or drop one on the Library. A song you have that isn't ignored and has no human sheet has **Sheet
from an audio file…** in its card too, beside From a YouTube video, even with a purchase linked.

The dialog shows the upload as it goes ("Uploading “song.mp3” · 3.1 of 8.4 MB"), then the file
("song.mp3 · MP3 · 3:18"), Artist and Title filled with the song it names, and "In your library: …"
for a song you have, with what the file will replace. Correct the names if they are wrong (a card's
song keeps its own) and press **Make sheet**: a line under the bar, or the song's own line, says how
it goes. **Cancel** or Escape deletes the file sent; a refusal says why, with **Choose another
file**, and a file dropped on the dialog is a new choice. Of several files only the first is used,
and the dialog says so. A file dropped anywhere else on the page is never opened in its place. The
file on disk and the phone have no +.

The file goes up in one
request, 128 MiB at most (`caracole audio FILE` takes any size), and waits in the state folder's
`audio/` until its sheet is asked for. caracole reads what it is from its bytes, never its name:
MP3, M4A, FLAC, WAV, Ogg or AIFF, 30 minutes at most. It answers the song the file's tags or its
name say, and whether you have it, with the audio the file would replace (bought, YouTube's, or a
file given before). A file sent and never used is deleted when the next one comes, or after an
hour.

Asking for the sheet queues `caracole audio --upload ID --song "ARTIST - TITLE" --progress`, a song
new to the library first going into wanted.txt with the file's album and length. The bar shows Song,
Audio, Lyrics, Words, Chords and PDF, Audio saying `kept as its audio: MP3, 3:18`, and Ready and
Not made yet read as for a sheet from a YouTube video. One runs at a time per song; asked again
meanwhile, the one queued is the answer and the second file is deleted.

- Refused before anything is queued: a song with a human sheet ("… already has a sheet.") or an
  ignored one. A purchase linked is no refusal: the file replaces it as the song's audio.
- Refused as it is sent: "Not an audio file caracole reads (MP3, M4A, FLAC, WAV, Ogg or AIFF).",
  "That file is too big: …", "That file is longer than 30 minutes.", "No room to keep it here.".
- Where chords can't be made: "No sheets from audio files here: auto-chords isn't installed.".

#### Lyrics under another name, from a card

When a song's own name finds no lyrics (a video's decorated title, a transliterated artist), its
card can look them up under a name you type. A song with no lyrics found has it open, above
Transcribe the lyrics: "No lyrics found. Look them up under another name". Any other song has
"Lyrics under another name…" folded under its foot, to replace the lyrics it has. Ignored songs have
none, and neither has a song while a request of it waits or runs.

- Artist and Title are filled in with the name you last asked under, else the song's own. Only
  Search, or Enter in a field, sends anything: opening the card or typing asks no site. Search
  queues `caracole lyrics --song … --as "ARTIST - TITLE"`; its line says "Asking LRCLIB, Megalobiz
  and AZLyrics under “孟维来 - 野人”…" and Search waits until it is over.
- Then the panel lists what the search kept: one row a record, with its site, "Artist - Title",
  album, length (and the audio's, when it is more than 10 s off), timed or plain. The best fit
  comes first, marked Best fit, and the record you picked says In use. Under the rows, what each
  site that listed nothing said, in `caracole lyrics --as`'s words, and how many instrumental
  records were left out. A long list makes the card longer; from 1200 px the card's pane scrolls. The search's own words head it: `Searched: …`, `Nothing found: …` (every
  site answered and none has any) or `Not searched: …; try again later.` (a site failed or
  waited: never "Nothing found").
- **Use these lyrics** on a row queues `caracole lyrics --song … --record SITE:ID --progress`. The
  song's line then follows the pick, and its card is drawn again once it is over, its Lyrics tile
  and its sheet as they are now. A search older than 7 days lists its rows with no button: search
  again to pick one.
- **Clear the pick** (`caracole lyrics --song … --clear`) is offered beside the row In use, and
  when the record you picked has given no lyrics, which the panel says ("The record you picked
  (megalobiz 8) has given no lyrics: pick another, or clear the pick."). The song is then pending:
  tonight's run asks every site again. Transcribe the lyrics is offered only once they have all
  answered.
- A refusal is said in the panel ("Search again: that record isn't among its last search's, …").
  The phone and the page opened as a file have no panel.

#### Transcribing the lyrics from a card

Where caracole can transcribe (as for `caracole transcribe`: auto-chords, Whisper, its two model
files and demucs-rs, and YouTube not turned off), a song offered a transcription has
**Transcribe the lyrics** in its card. That is a song with YouTube audio whose lyrics no site has
(see [Lyrics transcribed from the audio](#lyrics-transcribed-from-the-audio)). The button says how
long it takes: "a couple of minutes" with a GPU, "up to half an hour" without. Its newest Ready
request in the Journal offers it too, and a sheet from a video offers it as soon as it is Ready.

Pressing it queues `caracole transcribe --progress --song "Nick Cani - Vikingos veganos"`. The bar
shows Song, Vocals, Words, Chords and PDF, and how far the long steps are: the minutes the separator
has run against about how long it takes here, how far Whisper has heard the song ("Words · 3 of 5 ·
1:20 of 3:45"), and auto-chords' step. When it is Ready, the Journal says "Chords over the
transcribed lyrics.". If it fails, the Journal gives the reason ("no singing heard.", "the GPU
failed: …") with Try again. One runs at a time per song, and never beside another transcription
or a lookup. A song no longer offered one is refused ("… isn't offered a transcription: its lyrics
are found."). Where caracole can't transcribe, no card offers it. The phone never offers it.

Your word over caracole's goes on the card too. A song in which nothing sung was heard says so, with
**Transcribe anyway** (`caracole transcribe --force`). One whose sheet is over its transcript has
**Not sung: chords only** (`caracole transcribe --none`): its transcript is dropped, its sheet made
again with the chords alone, and that audio is never heard again (a new file is). Its card then
says "You said it isn't sung." with Transcribe anyway. Each is posted in place, as Transcribe the
lyrics is.

#### A YouTube video for a search

Where caracole can make a sheet from a video, a search with no sheet on the sites (no strong
match among your songs, UG's index or LaCuerda's chords, and no artist named in full) asks YouTube
for its first video. It does this once the query has been unchanged for 1.5 s, or at once on
Enter. That is one yt-dlp run (`caracole youtube --search`, in the Journal) for the title, channel
and length, never a download. Then comes one request for the thumbnail from `i.ytimg.com`
(provider `ytimg`), cached. A block there only pauses thumbnails.

The video shows as a row with **Make sheet**, which fills in the request form with the names and
the video for you to check. Nothing more is sent until you press Request. Limits: a query once in
30 days, 10 searches an hour, none while YouTube cools down, none for a query that failed in the
last hour, and none for an hour after three failures. A bot check, a 429 or a 403 is a block, with
one ntfy message. The file on disk never does this (see [Audio from YouTube](#audio-from-youtube)).

#### A pasted YouTube link

Paste a video's link into the search box (`youtube.com/watch?v=…`, `youtu.be/…`, `m.` or
`music.youtube.com`, `/shorts/…`) and it is treated as a song to add, not words to search. caracole
reads the video's title, channel and length (one yt-dlp run, no download, within the same limits
as a search's video), then shows the **Artist** and **Title** it guessed and **Add and make the
sheet**. The guess reads the title as [one text](#one-text-read-as-a-songs-name), with the channel
as the artist when nothing else names one: "Estopa - Como Camarón [Videoclip Oficial] HD" is
Estopa's "Como Camarón", and "Creep" from "Radiohead - Topic" is Radiohead's. On the file on disk,
run `caracole youtube --song 'Artist - Title' --url URL --sheet` instead.

#### A pasted Ultimate Guitar link

Paste a tab's page (`tabs.ultimate-guitar.com/tab/4180894`, or a slugged one) or an artist's page
(`ultimate-guitar.com/artist/634073`) and caracole reads it once, as `caracole ug --link` does:
the tab's page, then the artist's lists, at the lookup pace. None is read while UG cools down, or
for an hour after a failed read. You get UG's names for the tab, its type, version and rating, a
guessed **Artist** and **Title**, and **Fetch this version**, which keeps that version as the
sheet (a `[pin]`). From then on a search finds every song of that artist, including the bare-id
tabs UG's sitemaps don't name. A Guitar Pro file, a bass tab or a 404 is said and offers nothing.
An artist's link lists their songs, each with Fetch. On the file on disk a UG link is just words.

#### Pick

A song that needs review has **Pick**, which opens its candidates in the card. Choose one, or None
of these. It runs `caracole review --song "ARTIST - TITLE" --pick ARTIST/SONG`, which writes what
`caracole review` would (`[match]`, and `[alias]` where it would add one), matches the song again
(and, with an `[alias]`, that artist's other songs) and rewrites the pages. None of these runs
`--none` with the candidates you saw, which go under `[reject]`.

With Fetch ticked, a pick then runs `caracole fetch --song` and `caracole render --song` for that
song. None of these fetches nothing. If the matcher finds other candidates, the song is back in
review with those. The candidates must still be the ones the page showed. If the nightly run
matched the song again meanwhile, reload the page. A review without candidates keeps its Review
button, and `caracole review` offers it a pin or an ignore.

#### Look in index

A wanted song the offline index didn't match has **Look in index** in its card, unless you picked
its sheet on LaCuerda. It opens `/review?song=ID`, which runs `caracole search` for the song's
artist and title and offers the first five hits to pick. A pick writes `[match]` alone (see
[Review](#review)).

#### Remove a song

**Remove** in a song's card removes it where it is. The line says "Removing in 5 s · Undo" and
what goes, as [`caracole remove`](#caracole-remove) works it out: "Deletes caracole's 6 files for
it, its record and its wanted.txt line; leaves 1 other file; never touches Music/." Undo within
five seconds stops it. Then the page queues `caracole remove --yes "ARTIST - TITLE"` and the line
ends "Removed". The song then counts nowhere on the page. A page older than a change to the
library removes nothing and asks you to reload. Without JavaScript, Remove opens a page that says
what goes, with Remove it and Keep.

#### How it goes, on the page

A request leaves you where you are. The song's line says how it goes. A song new to the library
gets a "Just requested" line under the search box. You see "Queued…" (or "Queued · 2 requests
ahead…"), then what runs: "Adding to the book…" for a request without Fetch, or a lookup's stage
("Finding the song…", "Fetching from UG…", "Making the PDF…", "Fetching lyrics…"). "Waiting for
the book…" means a nightly run holds the lock until its next pause.

Once a lookup has run for a second, its line becomes a bar of steps: Song, Match (in UG's offline
index), Sheet (with the site it asks), PDF, Lyrics, Extras and Songbooks. Done steps are filled,
the running one pulses, a skipped one is an outline and a failed one is red with a "!". The text
names the step in hand ("Sheet · Ultimate Guitar · 3 of 7"). **Match: not on UG** is no failure,
since the sheet may come from LaCuerda. Steps that turn out not to apply stay in place, skipped.
A request that looks nothing up keeps one line.

How it ends:

| Line | Meaning |
|---|---|
| **Ready** | The bar goes and the song's title opens the sheet. |
| **Not on the sites · To-do page** | UG had no sheet, or its index has no such song (and the artist's UG page isn't known). |
| **Needs your pick · Pick** | caracole isn't sure which UG song it is. Without candidates: **Needs your pick · To-do page**. |
| **Not fetched yet · Details** | A cooldown, a block, a spent budget or an error stopped it. An error is never a miss: the song waits for the next run. |
| **Added · fetched tonight** | A request without Fetch. **Added · your LaCuerda pick comes tonight** when a LaCuerda pick waits. |
| **Read: …**, **Not found: …**, **Not read: …** | A LaCuerda artist page read, in the command's words, with Details. |
| an error | A command failed. **Details** links to its output. |

When it ends any other way than Ready, the bar stays, frozen, so you can see which step stopped.
An open card lists the steps one per line (✓ done, ◐ running, ○ to come, ! failed, – skipped)
with what each found. Skipped ones fold into "Skipped: PDF, Songbooks".

Lookups (Fetch, Fetch again, a pasted UG link, LaCuerda's search, an artist's page) start at once
beside the running request, up to three at a time, unless the song has a request in the queue.
Other requests wait for the one that runs and for the lookups. A waiting request shows its place
and **Cancel**. A running one is never stopped.

A request still on its way when you reload keeps its line. If the server stops answering, the
lines say "caracole serve can't be reached; trying again…". Two requests or more also show in a
folded corner panel ("2 requests · 1 to go") with a link to the Journal. The page asks
`/jobs.json` every 1.5 seconds while something waits or runs, less often in a background tab.

#### Journal

The library page's last tab, **Journal** (`#tab=requests`), shows what runs now and what ended,
from `/requests.json`. It refreshes every 1.5 seconds while something waits or runs, otherwise
every 10, and only while the tab shows. The tab counts the requests that wait or run.

**Now** lists running requests as cards (the queue's one and up to three lookups), with when each
started, its line and its steps. A lookup's steps are Song, Match, Sheet, PDF, Lyrics, Extras (UG's
second pass and its tab, LaCuerda's sheet, gtptabs.com's Guitar Pro file, harptabs.com's tab) and
Songbooks. Queued requests follow ("Queued · next", "Queued · 2nd", "Queued · next, after the
lookups"), each with **Cancel** (`POST /jobs/cancel`). A cancelled request stays in the history as
**Cancelled**. Cancelling leaves the song's wanted.txt line, so the nightly run still looks for it.
Remove the song if you don't want it. A songbook's Add a song for a song you haven't got queues
two requests, and cancelling either cancels both.

**Today** and **Earlier** (in the server's time zone) list finished requests, newest first, with
the outcome, the reason, a lookup's steps, the time and a next step:

- **Ready** · **Open**. A reason may say what waits for tonight ("LRCLIB answered 503: the lyrics
  wait for tonight's run.").
- **Needs your pick** · **Pick**, which opens `/review?song=ID`. Without candidates it says
  **Open in the library**.
- **Not on the sites**: "UG has no chords for it", or "Not in UG's index under this name". When a
  local index has the song elsewhere (a LaCuerda sheet, a gtptabs.com page), **Fetch from there**
  looks it up there. A site that is cooling down, or that was already asked this month, isn't
  offered. Otherwise it offers **Search the index** (for an unmatched song) or **Ask by name**,
  which fills in the request form (`/#q=Artist - Title`).
- **Not fetched yet** (with why) and **Failed** (with the error): **Try again** queues the same
  commands (`POST /jobs/again`). A removal's Try again asks what goes first.
- A songbook's **Made** or **Added** · **Open songbook**; **Removed**, **Deleted**, **Added**; a
  LaCuerda page's **Read**, **Not on the sites** or **Not read**.
- **Your version** · **Open**, from Export PDF's Make mine.
- **Interrupted**: caracole serve stopped while the request ran or waited. **Try again** queues it
  again. Its Output keeps what it printed, the step it was in marked Cut short.

Every request keeps its **Output**, folded: when it was asked, the commands it ran and what each
printed (at `-v`), and a lookup's stages. A Details link on the library page opens it
(`#tab=requests&job=N`). A request that ended in review (`caracole add` found only candidates)
says Needs your pick, which is not a failure.

The tab keeps the last 100 requests of the last 30 days, across restarts. caracole serve writes
them to `requests.jsonl` in the state folder, one JSON object per line, keeping each command's
last 200 lines of output at 1,000 characters each. It rewrites the file whole when it grows past
three lines per request or 4 MB. No command reads it and it takes no lock. Stop the server and
delete it to forget them all.

`/api/jobs` and `/api/jobs/N` give each request as JSON: its steps with their states, its song and
the library files its sheet can be read in. The `/api/…` addresses answer caracole's own pages,
the address bar and programs such as curl. A browser fetching one for another site's page gets
403.

#### Without JavaScript

The forms still post. A request or a pick sends you to the Journal (`/#tab=requests&job=N`),
and a lookup to the lookup page, which follows it.

#### A sheet's PDF

The sheet viewer's Export PDF links to `/export.pdf?sheet=<the viewer's path in the
library>&<its address after #>`. It makes that version's PDF now and sends it as a download named
for the song and the version (`Soda Stereo - De Música Ligera (A Major, capo 0).pdf`). This is the
PDF `caracole render --version` would write, made in a private folder in the cache. Nothing is
added to the library or the requests, and it takes no lock. A PDF that can't be made (chordpro
failing, a CJK font missing) is refused with the reason (500). A Chinese sheet's PDF uses the
characters the viewer shows, Traditional with `trad=1` (`… (A Major, capo 0, Traditional).pdf`).
With `&mine=1` (Make mine) it also queues `caracole render --song … --version … --mine`, which
makes that version yours ("Your version"). The auto sheet's viewer kept beside a human sheet and a
kept version's page get none (409).

#### How a harmonica tab is read

A harmonica tab's page links `/harmonica?page=<its path in the library>` (from its Read as line,
or "Change how it's read" at its foot). That page lists the readings caracole weighs for the tab,
best first, each with its Q and a button (`POST /harmonica/pin`), plus Back to our guess
(`POST /harmonica/clear`) once you set one. Each queues `caracole harmonica SONG --tab=… --as=…`
(or `--clear`), which writes `[harmonica]` and remakes the song's pages. The Journal shows it as
"Its harmonica tab read as you set it". A page that isn't a harmonica tab caracole wrote gets 404,
a reading that doesn't exist 400, and a tab already read that way, or no pin to remove, 409.

#### A sheet's versions

The sheet viewer runs in a sandbox and can't send forms, so its **Make this the one** and
**Keep** open `/versions?sheet=…&tab=…&do=choose|keep` in the same tab, and `do=clear` is **Back
to our pick**. The page names the version ("Ver 2 of 13 · 4.85★ (12,629)") and the song's current
sheet, with one button:

- **Make this the one** queues `caracole versions SONG --choose TAB`, which looks the song up with
  that tab as `caracole get --tab` does. It becomes `sheet.txt`, the PDF and its songbooks' sheet,
  kept under `[pin]`.
- **Keep** queues `caracole versions SONG --keep TAB`: one tab page at the lookup pace, kept beside
  the sheet with its own viewer. A runner-up caracole kept by itself stays only while the ranking
  keeps it. Keep it this way to make it yours for good.
- **Back to our pick**, on a song whose sheet a `[pin]` chooses, queues
  `caracole versions SONG --clear`. A tab pin stays.

Each is a request of the song, shown on its line like a lookup. The page reloads while it runs,
then says what came of it, read from the song and overrides.toml. If a block, a spent budget or
the hour's cap kept the old sheet, your pin is still recorded and the nightly run applies it. A
version that is already the one, already kept, gone from UG or under `[block]`, or a song with no
such pin, offers nothing (409).

The library page sends the same three by the song's id (`song` instead of `sheet`), and one more:
**Fetch them** (`POST /versions/keep-more`) queues `caracole versions SONG --keep-more`, keeping
the UG versions not kept yet, as many as one lookup may. A song with none left, or an ignored one,
gets 409.

#### Songbooks

The page's second tab (see [The Songbooks tab](#the-songbooks-tab)). Each change runs its
`caracole songbook` command (see [Songbooks](#songbooks)) and leaves you where you are:

- drag a song's grip (⠿) to move it (`caracole songbook move`). On the keyboard, ↑ and ↓ on the
  grip move it, sent once you stop;
- its chip ("A Minor, piano") opens key, mode, capo and instrument. **Play here** runs
  `caracole songbook set NAME SONG --key K --mode M --capo N`, and `--instrument I` when you
  change instrument. The capo is always sent, so a later sheet still sounds in that key. On an
  instrument with no capo (piano, harmonica, winds) the key is the key it sounds in. **Its own
  version** runs `--clear`;
- **×** takes the song out. **Fetch**, on a song with no sheet, looks it up and remakes the
  songbook;
- **Fetch the 2 missing songs** looks up each of your songs there without a sheet, in order, then
  runs `caracole songbook render NAME`. Songs not in the library, or ignored, are skipped. If the
  queue has less room than songs, it takes the first ones and offers the rest later;
- **Add a song** searches your songs and the offline indexes as you type, with no site asked. A
  song of yours is added at the end (`caracole songbook add`). One you don't have goes into
  wanted.txt, is looked up (`caracole get`), then added. Both are queued or neither;
- **Rename or delete** renames the songbook, or, once you tick the box, deletes it and the files
  caracole made of it.

The status line under the songbook's name says how each change goes ("Moving the song…",
"Moved"; once made, **Open songbook**). A lookup's line shows under its song. Select's Make
songbook (or Add to a songbook) runs `caracole songbook make NAME "ARTIST - TITLE"...` (or `add`)
in the order you ticked, and opens the tab on the songbook. A change that can't be made (a name
already taken, a song no longer in the library, a songbook deleted meanwhile) is refused at once
and nothing runs. A make that fails while running leaves the songbook on the tab with why, and
gives the Select bar back its ticks so you can try again with + New songbook. Its Forget takes it
off the tab.

#### How requests run

Every request runs a `caracole` command: one at a time in the queue, with up to three lookups
beside it that take turns with caracole's lock
([One caracole at a time](#one-caracole-at-a-time)). A request in the queue starts only once no
lookup runs or waits. So the server is never more aggressive than you at a terminal. Each command
takes the lock, keeps the pause after the last request any caracole sent, and keeps the budgets
and cooldowns. A lookup keeps the interactive pace (`lookup_delay`, 0.125–0.375 seconds between
two requests to a site, six for the song, sixty an hour), and a nightly run lets it go first at
its next pause.

The queue holds 20 requests, one per song. The lookups' lane runs three and holds ten waiting.
Asking again for a song returns its request, and Fetch on a song whose request only adds it
fetches it too. A request is in wanted.txt as soon as it's made, so a full queue or a restart
loses no song. The same songbook change sent twice is queued once. The server writes no songbook
itself.

#### Files the server sends

The page links each song's files, which the server sends from the library: PDFs, text, info.json,
and Guitar Pro, Power Tab and MuseScore files (`.mscz`, `.mxl`, `.musicxml`, `.mid`, `.midi`) as
downloads. It never follows a symbolic link and never sends a hidden file, the database or the
cache. A download is named for its song (`Eagles - Hotel California.gp3`, then
`Eagles - Hotel California (2).gp5`), with characters a system refuses replaced (`AC_DC - …`).
This only holds for files caracole serve sends. Chromium-based browsers ignore the name on a page
opened as a file and save it as `guitar-N` or `score-N`.

Of the library's HTML pages, the server sends only the sheet viewers (`sheet.html`,
`sheet (auto).html`, each `version-<tab>.html`; see [The sheet viewer](#the-sheet-viewer)), the
harmonica tab pages, and songbook pages (`_songbooks/<name>/songbook.html`). It sends each only
while it is still the page caracole last wrote: caracole records each page's SHA-256 and length.
Anything else gets 404, and so does a viewer edited on a synced device, replaced by a link, or in
a folder that is no song's. The page says the PDF is beside it. The next `caracole render` (or
`caracole songbook render`) writes it again.

These pages run in a sandbox. Their scripts run, but they can't reach the server and keep no
storage. A viewer keeps only the transposition, mode, capo, text size and scroll speed, in its
address (a songbook also keeps the song, `#song-3=&t=2&fs=20&speed=8`). Reload and Back keep
them, and opening it again from the library starts afresh. A viewer an older caracole wrote keeps
working after an upgrade.

#### Guitar Pro files in the browser

A Guitar Pro file caracole keeps (`guitar-N.gp3`, `.gp4`, `.gp5`, `.gpx` or `.gp`, from `_inbox/`
or gtptabs.com) has its own group in the song's card (`Guitar Pro 1 · gtptabs.com`), with **Open
in the browser** and **Download**. A served sheet viewer offers it as **Guitar Pro tab** in its ⋯
settings, and a songbook's set list has a guitar after the title.

Open in the browser goes to `/guitar?file=<the file's path in the library>`, where
[alphaTab](https://www.alphatab.net) draws and plays the file. A bar at the top has **Play**,
**Stop**, **Tempo** (50 to 125 %), **Tab only** or **Score and tab**, and the file's **tracks**.
It starts on the first guitar track with a tab. Tap a track to show it instead, or Shift-, Ctrl-
or ⌘-tap (press and hold on a touch screen) to add or remove it alongside others. Each track's
speaker mutes it, even while playing. On a narrow screen the tracks are one button that opens a
list with ticks. A track with no tab (piano, drums) shows as a score. A Power Tab file (`.ptb`)
stays a download, since alphaTab can't read it.

Nothing is written into the library. The file is read when you open the page, and only a file the
database records as a song's Guitar Pro file is shown (else 404). The page runs in a sandbox and
loads one script from the server, `/assets/alphatab/alphatab-1.8.4-<hash>.js` (about 2.9 MB,
alphaTab with its font and SoundFont), checked against its hash and cached. The server needs
alphaTab for this, which the Nix packages carry (`CARACOLE_ALPHATAB_DIR`; without Nix, see
[deploy.md](deploy.md#4-the-fonts-and-alphatab)). Without it the server still runs, the card says
Guitar Pro files are downloads, and `/guitar` says why. `index.html` opened from the folder lists
the file as a download.

#### Another caracole's sync

`GET /api/peer/state` answers what this library holds, unit by unit, for another caracole's
`caracole peer` (see [Two caracoles](#two-caracoles-the-phones-and-the-computers)). It includes
what the two last agreed on and each "keep mine" this library remembered from imports of that
caracole's files, and the schema of this database, so that a caracole of another asks for none of
its indexes. `GET /api/peer/unit` gives one unit whole, and `GET /api/peer/file` a song's
kept file while it is as kept. These reads take no lock and ask no site. `POST /peer/pull` queues
`caracole peer pull` of the units another caracole asks this one to take.

#### Export and Import a file

| Route | What it does |
|---|---|
| `GET /api/sync/sizes` | What an export would hold: name, songs, songbooks, the library's size in bytes, the indexes' size (null where SQLite can't count it) and the tabs they track. |
| `POST /sync/export` | JSON `{"parts": ["library", "songbooks"]}`, with `indexes` or not. Makes the file `caracole peer export` writes (see [Export and import](#export-and-import-peer-export-peer-import)) in `cache_dir/peer/`, one at a time (503 while another is made). Answers its id, download name (`horde_logbook-03-11-26.caracole`) and size. |
| `GET /api/sync/export?export=ID` | Sends it once and deletes it. An unsent one goes when the next is made, or after an hour. |
| `POST /sync/import/open` | JSON `{"size", "name"}`, 8 GiB at most, one at a time. Answers an id and the part size (8 MiB). |
| `POST /sync/import/part?import=ID&at=N` | Sends each part, in order, into `state_dir/peer/import-<id>/`. |
| `POST /sync/import/compare` | Form field `import`. Reads the file whole and compares it as `POST /sync/compare` does, or refuses it in `caracole peer import`'s words and deletes it: 400 for a file caracole didn't export, of another version or cut short; 409 for this library's own export, one with nothing new since your last sync with its caracole, or one whose caracole names songs by different rules. |
| `POST /sync/apply` | On that comparison, queues `caracole peer import` ("Sync with a file from <its library>"), which deletes the folder when done, unless it stopped where comparing again can settle it (the library changed since, a unit left). |
| `POST /sync/import/drop` | JSON `{"import"}`. Deletes it now, as Cancel does (409 while its import waits or runs). |

An import never taken is deleted an hour after its last part, or when the next file is opened if
no request names it and it is whole or its upload stopped two minutes before. The reads take no
lock and ask no site. The writes carry the form token, in a header or the form.

#### The Android app's copy

caracole's Android app copies the library from the server to read it offline. `GET /api/offline`
lists what to copy, as JSON: `format` 1, `start` (the page the app opens first) and `files`, each
with its `path`, `url`, `size`, `sha256`, `type` and the `headers` the server sends it with. It
lists `index.html` first, as caracole wrote it (at `/offline/index.html`), then every file it
links that the server sends: viewers, kept versions', harmonica tabs' and songbook pages while
unchanged, PDFs, text, ChordPro, lyrics, info.json, Guitar Pro files and scores. Never Music/,
`_inbox/` or a hidden file. If `index.html` changed since caracole wrote it, `/api/offline` answers
503 until `caracole todo` (or any command that writes the pages) writes it again. It needs no
option, takes no lock and asks no site. On the phone, the app's own caracole answers Export PDF
(it prints), versions, harmonica readings and the Guitar Pro page as caracole serve does
([android/README.md](../android/README.md)).

#### Who can reach it

There is no sign-in, no access token and no cookie. Whoever can reach the server can read the
library, request songs and change songbooks. Keep it on a network you trust, your LAN or your
tailnet, never the internet.

- `--address` is 127.0.0.1 by default, this machine alone. A LAN or tailnet address, or 0.0.0.0
  for every address, opens it to those networks. `--port` is 8737 by default.
- It answers to any of its IP addresses (`http://192.168.1.20:8737/`), and only to the names it
  knows: localhost, the machine's name, its `.local` name, and each `--allow-host NAME`, such as
  its full tailnet name. Any other name gets 421. This stops DNS rebinding.
- Every form carries a token the server makes when it starts, and a request from another site is
  refused (403). A form from a page older than the server's last start is refused too, so reload
  the page. `/jobs.json` and `/requests.json` need the same token in an `X-Caracole-Form-Token`
  header, and the page then says the server has restarted.
- One exception: Export PDF's Make mine is a plain link (`/export.pdf?…&mine=1`) with no token, so
  another site could change a song's saved version with a link. Nothing is lost: Reset, or making
  another version yours, undoes it.
- Only the served page's script may ask the server anything. `index.html` on disk asks nothing of
  anyone.

These checks keep other sites' pages, open in a browser on your network, from using the server.
They keep out no person or program on the network itself.

It runs until Ctrl-C. On a server, `caracole-web.service` runs it
([deploy.md](deploy.md#5-the-library-page-on-your-network)).
## Songbooks

A songbook is a name and some songs of your library, in order: a set list, the songs for a trip, a
book to print. caracole makes each one into three files in `Library/_songbooks/<name>/`:

| File | What it is |
|---|---|
| `songbook.pdf` | A title page, the contents, then every song's sheet. |
| `songbook.html` | One page for the phone: the contents, then each song in the [sheet viewer](#the-sheet-viewer). It loads nothing, so it opens from the synced folder. |
| `songbook.cho` | Every song's ChordPro with its `{key}` and `{capo}`, split by `{new_song}`, for an app such as SongbookPro or OnSong. |

All three show each song as the songbook plays it: in its setting there
(`caracole songbook set`, below), else in the song's own version (`[version]`, else `[transpose]`,
else as written).

- The PDF names chords as the viewer does (Bb, not A#). A song set on another instrument is
  printed for it. One PDF draws diagrams for one number of strings, so the other songs get their
  shapes as frets (`Ukulele: C 0003 · Am 2000 · F 2010`).
- A song without a sheet keeps its place, marked "missing: no sheet yet". The ChordPro file leaves
  it out.
- On the phone page, Previous, Next or a swipe changes song, and the page reopens where you left
  it.

The songbooks live in `songbooks.toml`, in the library, so the file syncs and you can edit it by
hand. caracole keeps your comments and layout. Each table is a songbook, named by its header, with
its songs in order as `"Artist - Title"`:

```toml
["Campfire"]
songs = [
  "Soda Stereo - De Música Ligera",
  "宋冬野 - 斑马，斑马",
  "Radiohead - Creep",
]
```

- A song must match the library's artist and title. Accents, case, Traditional or Simplified
  characters and a version suffix ("- Remastered 2007") don't count. A typo or a removed song is
  listed as missing, `not in the library`.
- A name can't be empty, start with a dot, hold a line break or be longer than 80 characters. Two
  names can't share a folder (`Camp/fire` and `Camp-fire`, or `Campfire` and `campfire`).
- If the file can't be read (bad TOML, or a symbolic link), the error names the file and the line.
  No songbook is made, and the files already there stay.

The library page lists them in its [Songbooks tab](#the-songbooks-tab). Opened as a file, it gives
you the commands below ready to copy. On `caracole serve` you change the songbooks on the page
(see [Library/index.html](#libraryindexhtml) and [caracole serve](#caracole-serve)).

### caracole songbook

| `caracole songbook …` | What it does |
|---|---|
| `make NAME "ARTIST - TITLE"...` | Makes a songbook of these songs, in this order. A name another songbook has is refused. |
| `list` | Shows every songbook: its songs, how many have no sheet, and its files. |
| `show NAME` | Lists its songs in order, where each plays, and where its files are. |
| `add NAME "ARTIST - TITLE"...` | Adds songs at the end. One it has already stays where it is. |
| `remove NAME "ARTIST - TITLE"...` | Takes songs out. |
| `move NAME "ARTIST - TITLE" POSITION` | Moves a song. 1 is first, and past the end is last. |
| `set NAME "ARTIST - TITLE" [options]` | Sets the song's key, mode, capo or instrument in this songbook ([below](#songbook-set)). |
| `rename NAME NEW` | Renames it. Its files move to the new folder. |
| `delete NAME` | Deletes it and the files caracole made. A file of yours in its folder stays. |
| `render [NAME] [--force]` | Makes the files that need it, for one songbook or all. `--force` makes them all again. |

A NAME is found in any case. `list` and `show` only read. Every other command writes
songbooks.toml, makes the songbook's files and rewrites `_todo.md` and `index.html`. It takes
caracole's lock, which a nightly run hands over at its next pause (see
[One caracole at a time](#one-step-at-a-time)).

`show` marks a song `(missing: no sheet yet)` or `(missing: not in the library)`, and says where
each one plays: `(G Dorian)`, `(E Minor, capo 2)`, or `(key unknown, as written)` when the sheet
can't take the key.

#### How a song is found

`make` and `add` take the artist and title written any way, or a search of your library that one
song answers well. They say which song they took:

    Took 宋冬野 - 斑马，斑马 for "ban ma ban ma"

An artist alone names no song: "Oasis" is refused with `did you mean "Oasis - Wonderwall"?`. A
song the library hasn't got is refused too, and nothing is written:

    No song "Radiohed - Karma" in the library: did you mean "Radiohead - Karma Police"?

A song named twice goes in once (`Muse - Hysteria is in it already`). `remove` and `move` look in
the songbook first, so `remove` also takes out a song you removed from the library.

#### songbook set

| Option | Values |
|---|---|
| `--key K` | The key the song is played in: `G`, `F#`, `Bb`. |
| `--mode M` | `ionian`, `dorian`, `phrygian`, `lydian`, `mixolydian`, `aeolian` or `locrian`. |
| `--capo N` | 0 to 11. |
| `--instrument I` | `guitar`, `ukulele`, `ukulele-low-g`, `baritone`, `piano`, `harmonica`, `flute` or `recorder`. |
| `--clear` | Takes the setting off. The song is in its own version again. |

The parts you give change and the others stay. The command answers with where the song plays now:
`In the songbook: G Dorian, capo 2`, or `In the songbook: A Minor, ukulele`.

- The key is the key of the shapes you play: `--key G --mode dorian --capo 2` sounds in A dorian.
- What you leave out comes from the song's own version: its mode for a key alone, and the capo the
  song plays at now. `--capo 2` alone keeps the sound and changes the shapes.
- The key is a key, not a move, so a new sheet in another key still plays in yours. A setting
  written by hand with no capo takes the capo of the song's own version, else the sheet's, so
  write `capo` too.
- On an instrument with no capo, such as the piano, the key is the key the song sounds in.
  `--instrument` alone keeps the pitch: `key G, capo 2` becomes `key A` on the piano.
- A sheet with no key caracole can read can't take a key or a mode. The song stays as written.

In songbooks.toml a song with a setting is a table in place of the string:

```toml
songs = [
  "Oasis - Wonderwall",
  { song = "Soda Stereo - De Música Ligera", key = "G", mode = "dorian", capo = 0 },
  { song = "Eagles - Hotel California", instrument = "ukulele" },
]
```

A value that is none of those above is an error. It names the songbook and the song, and stops the
songbooks.

#### When the files are made

`caracole render` and the nightly run make the songbooks' files after the sheets. A file is made
again only when what it is made from changed, or when it is no longer as caracole wrote it. A
songbook you take out of songbooks.toml by hand loses the files caracole made of it at the next
render. A songbook with a Chinese song gets its PDF once a
[CJK font](#fonts-for-chinese-sheets) is set.

`render` prints `1 rendered, 2 up to date, 0 failed`. A file that can't be made fails its songbook
alone, and the log says why (`songbook Campfire: no songbook.pdf: …`).

| Exit status | When |
|---|---|
| 1 | A file couldn't be made. After a change, the command says `Some of its files couldn't be made`. The change to songbooks.toml stays, and on `caracole serve` its request shows as failed. |
| 2 | songbooks.toml can't be read. |

## overrides.toml: your decisions

`overrides.toml` sits in the library folder (or where `overrides_file` says), and can live in git.
caracole writes most of it for you:

| Tables | Written by |
|---|---|
| `[match]`, `[alias]`, `[pin]`, `[ignore]`, `[reject]` | `caracole review` |
| `[youtube]` | `caracole youtube --song … --url` or `--none` |
| `[lacuerda]` | `caracole get --lacuerda`, `caracole add --lacuerda` (Fetch and Add for tonight on a LaCuerda song) |
| `[harptabs]`, `[gametabs]`, `[ireal]` | `caracole get --harptabs`, `--gametabs`, `--ireal` (Fetch on that site's row in caracole serve's search) |
| `[version]` | `caracole render --version … --mine` (Make this my version) |
| `[harmonica]` | `caracole harmonica --as`, or caracole serve's page of a harmonica tab's readings |

You write the rest by hand. These are all the tables:

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

[version]      # where you play a song, as Make this my version saves it
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

[azlyrics]     # the AZLyrics page of a song its artist's name doesn't lead to
"Misc Musicals - Hadestown Wait For Me" = "https://www.azlyrics.com/lyrics/hadestown/waitforme.html"

[lyrics]       # the name a song's lyrics are asked under, and the record you picked
"Plan B - Ill Manors" = { as = "Plan B - Ill Manors (Official)", record = "lrclib:28399373" }
"Pomme - Mononoké" = { record = "azlyrics:pomme/mononoke" }

[gametabs]     # the gametabs.net tab a song's tab of game music comes from
"Hollow Knight - Resting Grounds" = "https://gametabs.net/tabs/hollow-knight/resting-grounds-2"

[ireal]        # the iReal Pro forum's chart a song's sheet comes from
"Thad Jones - Groove Merchant" = "https://forums.irealpro.com/threads/groove-merchant-thad-jones.9518/post-38106"

[harmonica]    # how a song's harmonica tab is read, whatever caracole guesses
"Cowboy Bebop - Spokey Dokey" = {"harmonica-1.txt" = "letters"}
"Little Walter - Juke" = {"harmonica-1.txt" = {as = "signs", "*" = "bend"}}
```

Songs are written `"Artist - Title"` and match the way songs match everywhere. These don't matter:
case, accents, a leading "The", a version suffix (" - Remastered 2011", " - En Vivo",
"(Acústico)"), Traditional or Simplified Chinese, and number words or digits ("Té Para Tres" is
"Té para 3"). In the artist, neither does a leading Los, Las, El or La, nor "y" for "&".

Paste every address as your browser shows it. caracole copes with a query (`?filter=chords`), a
missing `https://` or `www.`, and UG's language editions (`es.ultimate-guitar.com`).

### Tables for Ultimate Guitar

`[alias]` takes one UG artist slug or a list. The slug is the artist part of a tab's address, as
in `/tab/bob-marley/...`.

`[match]` points one song at one UG song. Unlike a pin, it still picks up tabs added to that song
later. When you correct a `[match]` or a `[pin]`, the next fetch takes the sheet and tab from the
new one, and the old sheet goes even if the new one has none.

`[artist_url]` is keyed by the artist's name as your songs or UG write it: an entry for "Song
Dongye (宋冬野)" serves songs by 宋冬野 too (see [names in other scripts](#names-in-other-scripts)).
The value is the artist's page on UG. Its address must end in the artist's number, after the name
(`…/artist/soda_stereo_2946`) or alone (`…/artist/634073`). Any tab page of the artist works too:
the next fetch reads it once and remembers the artist page it links to. One that leads to no
artist page is listed on the to-do page.

`[pin]` takes a list of tab pages. They replace the candidates of their kind (sheet, tab), in the
order given. A pin does nothing when its page is gone, is Official, is closed to bots by
robots.txt (UG's `/tab/track/` pages), or is of a type caracole doesn't use (a Guitar Pro file, a
bass tab). `caracole versions --clear` takes a song's chords pins out again.

`[reject]` names the UG songs that are not this song, as one `"artist-slug/song-slug"` or a list.
They are never offered for it again. A `[match]` for the song still wins. Answering `n` in
`caracole review` writes this table. A match you reject is undone, and the next fetch takes away
the sheet and tab it kept.

`[block]` takes only `tab_ids = [...]`, and keeps those tabs out of every ranking from the next
fetch on. A kept sheet you block goes if nothing replaces it.

`[ignore]` takes only `songs = [...]`. It stops all work on a song: no matching, fetching,
rendering or to-do items.

### Tables for your key

`[transpose]` shifts the chords and the key in the PDF. `sheet.txt` stays as the source wrote it.

`[version]` is where you play the song. Its `sheet.pdf` is made there, its viewer starts there,
and its songbooks play it there unless a songbook sets its own. It wins over `[transpose]`. Take
the entry out to go back.

| Part | What it is |
|---|---|
| `key=Gm` | The key of the shapes you play, as a sheet names one: `G`, `F#m`, `Bb dorian`. |
| `mode=dorian` | `ionian`, `dorian`, ... `locrian`. Only there when you chose a mode. |
| `capo=0` | 0 to 11. The sheet's capo when left out. |
| `alt=F.Fmaj7` | A chord played instead of another: Fmaj7 for every F. |
| `at=Gm.x-x-5-7-8-6` | A chosen shape: frets from the nut, low E first, `x` for a string not played. A ukulele's has four strings, G first. |
| `inst=piano` | The instrument the viewer and the songbooks open on. `sheet.pdf` stays the guitar's. |

In a chord's name, write `%`, `&`, `=`, `,` and `.` as `%25`, `%26`, `%3D`, `%2C` and `%2E`. If
you write an entry by hand:

- The key names a key's notes, not a tonic alone. `key=G` on an A minor sheet is G major's notes
  from A, which is A dorian. Write `key=Gm` for G minor.
- The key is a key, not a move. A new sheet in another key or with another capo still plays in
  your key at your capo, and a chord you swapped or shaped keeps that if the new sheet plays it.
- An older entry with `t=` in place of `key=` is a move from the sheet in semitones. It still
  works, and caracole never rewrites it.
- A value over 2000 characters, a key, mode or capo that can't be one, or a `key=` with a `t=`, is
  an error naming the entry.

### Tables for the other sites

`[youtube]` names the video a song's audio comes from, in place of the one caracole's search
picks, or when it finds none. Any form of the address works (`watch?v=`, `youtu.be/`, `/shorts/`). A new video replaces
the song's audio at the next run, and its auto sheet is made again. `"none"` keeps the song off
YouTube for good: caracole deletes any audio it took, and the song goes back to the buy list.

`[lacuerda]` names the LaCuerda song whose sheet you want: its page, for its best Letra y Acordes
version, or one version's page (`…/como_camaron-2.shtml`). caracole keeps it in place of Ultimate
Guitar's sheet, LaCuerda's other versions and the auto sheet. Only a `[pin]` of a UG sheet wins
over it. An entry written by hand is asked for at the next nightly pass, unless LaCuerda
answered for the song in the last 30 days. `caracole get --lacuerda` asks at once.

`[harptabs]` and `[gametabs]` name the tab you picked, by its page. The nightly pass reads that
page alone and keeps its tab, whatever artist, game or composer the page names, as the song's next
`harmonica-N.txt` or `gametab-N.txt`. A page gone from the site (404) is asked for again after 30
days.

`[ireal]` names the chart you picked on iReal Pro's forum, by its thread's page. For one post's
chart, give the post's address (`…/post-38106`) or its anchor (`#post-38106`, on a later page
`…/page-3#post-38106`). A later page's address alone names no chart. The chart becomes the song's
sheet, in place of any but a tab you pinned on UG or a sheet you picked on LaCuerda.

`[azlyrics]` names a song's lyrics page on AZLyrics, for a song its artist's name doesn't lead to.
caracole asks for that page alone, while the song has no lyrics.

`[lyrics]` holds, for a song whose own name finds no lyrics, the name to ask under (`as`, an
"Artist - Title"), the record you picked (`record`), or both. A record is `lrclib:ID` or
`megalobiz:ID` (the record's number on that site) or `azlyrics:ARTIST/SONG` (the two parts of its
page's address, `azlyrics.com/lyrics/ARTIST/SONG.html`), and nothing else: no address, no other
path. LRCLIB, Megalobiz and AZLyrics are asked under `as`, with no album, in place of the song's own
name. A `[lyrics]` record wins over an `[azlyrics]` page, which wins over the `as` name. A record you
picked is final: while the song has its lyrics no site is asked about it, nor for timed lyrics in
place of plain ones. While it has none, only the record's own site is asked, for that record alone,
one request; a record gone leaves the song without lyrics (the log says so), and it is asked again
after 30 days. Until you pick another or clear the pick, a song whose record gave no lyrics, read or
not yet, is not transcribed ("the record you picked (lrclib 9) has given no lyrics: pick another, or
clear the pick"); one with a transcript kept may still be said not sung. The nightly run,
`caracole lyrics`, a lookup and a sheet made from a YouTube video all keep to `[lyrics]`. An entry you write by hand takes effect at the next run for a song still pending,
and at its next 30-day re-check for a song whose lyrics are missing. A `record` is never applied to a
song that already has lyrics. An `as` is: a song with plain lyrics is asked of Megalobiz under it for
timed ones, at the next run when Megalobiz hasn't been asked about it, else once its 30 days are
over; one typed through `caracole lyrics --as` is asked at the next run for a song pending or
missing, as the search forgets the sites' misses (`caracole lyrics --pick` and `--record` fetch at
once). Clear or change a pick with the
command (`caracole lyrics --song … --clear`, `--pick`, `--record`, `--as`): it forgets the sites'
misses at once, so every site is asked again under the name that holds before a transcription is
offered. A record you take out by hand leaves those misses for up to 30 days.

`[harmonica]` says how each of a song's harmonica tabs is read, by its file's name. The value is a
notation (`"signs"`, `"brackets"`, `"letters"`, `"signs after"` or `"barrett"`), `"legend"` for
the tab's own legend, or a table with a notation (`as`, signs by default) and what its symbols
mean (`{as = "signs", "*" = "bend"}`; see [caracole harmonica](#caracole-harmonica)). The tab's page
follows it at the next render, or at once with `caracole harmonica --as`.

### Errors in overrides.toml

Each table may appear only once: add lines under the table the file has already. An unknown table,
a key other than `songs` in `[ignore]` or `tab_ids` in `[block]`, or a malformed entry is an error
that names the table and the entry:

    error: overrides: /home/you/Tabs/overrides.toml: [reject] 'Creep': expected "Artist - Title", got 'Creep'

| The error says | What is wrong |
|---|---|
| `; merge the two [match] sections into one` | A table is declared twice. |
| `a symbolic link, which caracole doesn't follow; put the file itself there` | The file must be a regular file. |
| `can't read it: Permission denied` | caracole may not read the file. |
| `line 3 is not valid UTF-8 (save the file as UTF-8)` | The file is in another encoding. |

A missing file means no overrides. While the file can't be read:

- the commands that need it exit with status 2;
- the nightly run stops before its first step, and ntfy tells you;
- the run, `caracole todo` and `caracole scan` still rewrite `_todo.md`, which leads with the
  error, and leave `index.html` as it was;
- `caracole add`, `caracole search --add` and `caracole sync` still work, with a warning.

## Fonts in the PDFs

Every PDF caracole makes is set in the fonts of one folder: `pdf_fonts`, or `$CARACOLE_PDF_FONTS`
(the key wins). The Nix packages point it at Adwaita Sans and Adwaita Mono. The folder holds four
files, each a `.ttf` or an `.otf`:

| File | What it sets |
|---|---|
| `regular` | the words, the line under the title, the page footer, the contents |
| `bold` | the title, the chords, the section names, the chord diagrams' names |
| `italic` | a repeat mark ("x2") beside the chords |
| `mono` | a tab |

Each must be a single static font: no collection, no variable font, no odd-length glyph records.
With a file missing or unusable, the render logs
`pdf_fonts is unusable (…): the PDFs keep ChordPro's built-in fonts`, and the PDFs use ChordPro's
Helvetica and Courier, as they do with no folder set. Changing the folder makes every PDF again at
the next render.

Letters Adwaita Sans lacks, Chinese among them, bring in the Chinese font below for the words
alone. In a songbook with a Chinese song, all the words are in the Chinese font. A symbol
Adwaita lacks, such as an emoji, prints as an empty box.

## Fonts for Chinese sheets

A sheet with Chinese lyrics needs a font file for its PDF. The Nix package sets
`$CARACOLE_CJK_FONT` to `FusionKaiJ-Regular.ttf`, a brush-style face from nixpkgs'
`lxgw-fusionkai`. To use another font, set `cjk_font`, which wins over the variable. Without Nix,
[deploy.md](deploy.md#4-the-fonts-and-alphatab) installs FusionKaiJ.

caracole refuses two kinds of font with an error, as ChordPro 6.050.7 can't draw them:

- font collections (`.ttc`), which is all nixpkgs ships of Noto CJK and Source Han Sans;
- TrueType fonts with odd-length glyph records, which most CJK `.ttf` files have (LXGW Neo XiHei
  and WenKai among them).

A CFF-based `.otf` works, but its PDFs are larger.

Until a usable font is set, a Chinese sheet still gets its `.cho` file and its viewer. The to-do
page's PDFs section lists it with the first letter that needs the font, such as
`宋冬野 - 斑马斑马 (斑 U+6591)`.

Without `pdf_fonts`, a sheet with a ʼ, a Greek or a Cyrillic letter needs the Chinese font too, as
ChordPro's built-in fonts lack them. The exception is a letter that looks Latin, such as the
Cyrillic х in "(х2)": when those are the only ones, caracole writes them as Latin letters.

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
      songbook (Traditional).pdf  the same in Traditional characters, when a song is Chinese
      songbook.html         the songbook for the phone, in the sheet viewer
      songbook.cho          every sheet in ChordPro, for a songbook app
  _inbox/                   Guitar Pro and MuseScore downloads waiting to be filed
  宋冬野/
    斑马斑马/
      sheet.txt             the chosen chord sheet, as plain text
      sheet.json            the same version as the source gave it
      sheet.cho  sheet.pdf  ChordPro, and a PDF in your key (Chinese in Simplified characters)
      sheet (Traditional).pdf  a Chinese sheet's PDF in Traditional characters
      sheet.html            the sheet viewer, for the phone
      version-39144.txt     another Ultimate Guitar version kept beside the sheet, by its
      version-39144.json    tab id: its text, the version as UG gave it, and its viewer
      version-39144.html    (no PDF of its own)
      lyrics.txt            the lyrics, from LRCLIB (or Megalobiz, or AZLyrics)
      lyrics.lrc            the timed lyrics, when LRCLIB (or Megalobiz) has them
      guitar-1.gp5          Guitar Pro or Power Tab files: filed from _inbox/, or from gtptabs.com
      score-1.mscz          scores you downloaded (MuseScore, MusicXML, PDF, MIDI), filed
      harmonica-1.txt       a harmonica tab from harptabs.com: hole numbers over the lyrics
      harmonica-1.html      its page, for the phone
      tab.txt  tab.json     the best text tab
      gametab-1.txt         a text tab of game music from gametabs.net
      sheet (auto).txt      made from audio you bought, or caracole took from YouTube, when
      sheet (auto).cho      no human sheet exists; it stays, with its ChordPro, PDF and
      sheet (auto).pdf      viewer, beside a partial human sheet, until a complete one
      sheet (auto).html     replaces it
      info.json             where everything came from, and the song's key
Music/                      music_dir: the tracks you bought (caracole only reads it)
```

Keep the library private. The sheets and lyrics are other people's work.

The audio caracole takes from YouTube is not in the library. It is in the cache, as
`cache_dir/youtube/<song id>-<video id>.m4a`, a few MB a song. If you delete that folder, the next
run downloads it again for songs with no auto sheet yet.

Folder names keep their accents and scripts, but never a character file systems reserve: `AC/DC`
becomes `AC-DC`. An artist has one folder, so a new song by `oasis` goes into the `Oasis` folder
you have. A folder's name is 120 bytes at most, and two songs whose titles agree that far share
one folder. The second song then waits, and the run's summary or the lookup says so. To fix it,
`caracole remove` one of the two and add it again under a shorter title.

Syncthing, and every device it syncs with, can write to the library, so caracole never reads or
writes a file there through a symbolic link. A link in the place of wanted.txt, overrides.toml,
`_inbox` or a download in it is refused, and the command or the to-do page says so. A link in the
place of a sheet's file fails that song's render.

The files caracole keeps are its own. If one is deleted, cut short or edited, caracole writes it
again: the sheet, version and tab files (`.txt`, `.json`) at the next `caracole run` or
`caracole fetch`, and the `.cho` files, PDFs and viewers at the next render. Keep your own edits
in a copy under another name, which caracole leaves alone. The `.cho` files are the sheet in
ChordPro, for apps such as SongbookPro or OnSong.

Some files are not written again: `sheet (auto).txt`, `lyrics.txt`, `lyrics.lrc`, a Guitar Pro
file and a score. A song that has had a Guitar Pro file gets no other from gtptabs.com, even after
you delete it. Put a lost file back in the song's folder under its name, or drop it into `_inbox/`
again.

Deleting a song's folder doesn't remove the song: caracole writes its files again.
[`caracole remove`](#caracole-remove) removes it, and deletes only the files caracole wrote there.

### The song's key

caracole gives each song with a sheet a musical key, from the first of these that gives one:

1. **The tab**: the key Ultimate Guitar gives the kept version, or one the sheet states before its
   first chords, such as `{key: Am}`, `Key: G`, `Key of Bb` or LaCuerda's `Tono: La menor`.
2. **The chords** of the human sheet: the key whose notes they fit best. Chords that fit no key
   give none.
3. **The audio**, for a sheet auto-chords wrote: the key of the chords the model heard.

It is the key of the shapes you play, before any `[transpose]`. With a capo, the song sounds
higher.

A tab's key is as its transcriber gives it, except for a letter alone (`A`, `F#`, `La`), which
names no mode. caracole reads it as the minor key when the sheet's chords have that key's notes
and not the major key's, and the sheet never plays a major chord on its tonic (A, A7 or Amaj7 for
A minor). The letter may also name the key the song sounds in, a capo above its shapes, or a minor
key by its relative major:

| The tab says | Over the chords | caracole reads |
|---|---|---|
| `A`, capo 2 | Am E7 G D F C Dm E | A minor shapes, which sound in B minor |
| `B`, capo 2 | the same | B minor, the key it sounds in |
| `C` | Am F C G Am | A minor |
| `C` | C F G Am | C |

`info.json` holds the key in two fields, for anything that reads the library:

```json
"key": "A minor",
"key_source": "tab",
"identity_key": "soda-stereo/de-musica-ligera",
```

- `key` is the tonic, a capital letter with `#` or `b`, followed by ` minor` for a minor key:
  `"A minor"`, `"C"`, `"F#"`, `"Bb minor"`. It is `null` when no source gives one.
- `key_source` is `"tab"`, `"chords"` or `"audio"`, and `null` with no key.
- `identity_key` is caracole's own key for the song, which info.json called `key` before.

## A worked example

The song is 斑马斑马 by 宋冬野 (Song Dongye), from the album 安和桥北. It shows two hard cases: an
artist Ultimate Guitar lists only by bare ids, and lyrics without timings.

**1. Add it.** The album and duration make the lyrics lookup exact. Written "斑马，斑马" with a
comma, or 斑馬斑馬 in Traditional characters, it is the same song.

    $ caracole add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    Added 宋冬野 - 斑马斑马 to wanted.txt; the next `caracole run` looks for it.
    Not in the offline Ultimate Guitar index under this name: `caracole search` with a few of its words looks wider.

**2. It isn't found on Ultimate Guitar.** UG's sitemaps list every tab of 宋冬野 by a bare id, so
the local index has none of them, as `caracole add` said. The to-do page lists 宋冬野 under
"Artists to find on Ultimate Guitar", with a link to search UG and the line to paste. The song
goes on the buy list meanwhile.

**3. Tell caracole where 宋冬野 is on UG.** Once caracole has read
[UG's artist directory](#ugs-artist-directory), it finds his page by itself. Until then, search UG
in your browser and paste one of these into overrides.toml:

```toml
[artist_url]   # his artist page, which UG writes with his number alone
"宋冬野" = "https://www.ultimate-guitar.com/artist/634073"

[artist_url]   # or any of his tab pages: the next run reads it once for the artist page it links to
"宋冬野" = "https://tabs.ultimate-guitar.com/tab/4180894"

[pin]          # or a pin of the song's tab page, which takes that very version
"宋冬野 - 斑马斑马" = ["https://tabs.ultimate-guitar.com/tab/4180894"]
```

A pin teaches caracole his artist page too, so his other songs are found the next night.

**4. The next run finds it.** On his artist page UG names him "Song Dongye (宋冬野)", and the song
"斑马 斑马 Banma Banma Zebra Zebra", in two versions. Each part of such a name counts as a name of
its own (see [names in other scripts](#names-in-other-scripts)), so 斑马斑马 matches both. They are
scored against the lyrics, and the better one becomes `sheet.txt`. That takes four requests.
`caracole fetch --song "宋冬野 - 斑马斑马"` does it at once.

**5. The lyrics come from LRCLIB, plain.** LRCLIB has the song without timings, so its folder gets
`lyrics.txt` and no `lyrics.lrc`. Those lyrics are in Traditional characters (斑馬), and many
sheets are in Simplified ones (斑马). caracole compares Chinese text as pinyin, so a complete sheet
counts as complete either way.

**6. No human sheet anywhere? Buy it, drop it into Music/, and run `caracole autochords`.** The
buy list links the stores. The command needs the flake's `packages.autochords`
(`nix shell .#autochords`; on a server the `caracole-autochords` unit runs it after each nightly
run, see [deploy.md](deploy.md#4-auto-chords)). It links the new file to the song by its tags and
duration, and writes `sheet (auto).txt`, which starts with "auto-generated, unverified". If the
scan reports the file as unmatched, make its artist and title tags match the song's line in
wanted.txt.

With auto-chords, caracole doesn't wait for a purchase. The nightly run takes the song's audio
from YouTube itself (see [Audio from YouTube](#audio-from-youtube)). A purchase dropped into
Music/ later takes the video's place.

## Keeping the database

The database holds what took the longest to get: the indexes of every site, built from days of
polite requests, besides your songs' state. The cache can be lost, at the cost of requests. The
database is better kept.

### caracole backup

The nightly run's last step copies the whole database into `backups/` in the state folder, as
`caracole-2026-10-30T034512Z.sqlite` (the time in UTC), and keeps the last three. Each is about
430 MB for a library with every index. The copies a merge or a sync makes first
(`…-before-merge.sqlite`, `…-before-sync.sqlite`) keep their own three.

SQLite checks each copy. One that fails the check fails the run, so that you hear of it. With no
room for a copy (the database's size and 64 MB to spare), none is made and none is deleted, and
the summary says `No backup tonight: no room for a copy …`.

    caracole backup            # a copy now, under caracole's lock: it waits for a run
    caracole backup --list     # the copies there are, the newest last

`caracole backup` exits 1 when there is no room for a copy, or the copy fails its check. To put a
copy back, stop caracole, move the database's `-wal` and `-shm` files away with it, and copy the
backup into its place. [deploy.md](deploy.md#restoring-the-database) says how on a server.

### The service's library, and your home's

With no `--config` and no `CARACOLE_CONFIG`, caracole uses its home folders
(`~/.local/state/caracole`, `~/Tabs`; see [Configure](#configure)). On a machine that runs
caracole as a service, that is not the service's library. An index built from your shell would
land where the service never sees it.

So the service leaves a marker, `/etc/caracole/service`, that names its folders. The NixOS module
writes it, and so do [deploy.md](deploy.md)'s Ubuntu steps:

```toml
state_dir = "/var/lib/caracole/state"
library_dir = "/var/lib/caracole/library"
```

Where the marker is, caracole on its home folders does this:

| Command | What happens |
|---|---|
| One that builds an index: `run`, `index build`, `index refresh`, `gtptabs`, `musescore`, `harptabs --index`, `gametabs --index`, `ireal --index`, `lacuerda --index`, `ug --directory` | It exits 2 before it writes or asks anything, and names the two ways on: `sudo caracole-admin gametabs --index` for the service, `caracole --home gametabs --index` for your home. |
| Any other that writes or sends a request | It warns once, with the `sudo caracole-admin` line for the service, then goes on. `caracole serve` warns as it starts. |
| One that only reads: `search`, `index stats`, `versions`, `songbook list` and `show`, `backup --list`, `remove --list`, `match --dry-run` | Nothing. |

`--home` is a root option (`caracole --home COMMAND`). It says you mean the home folders: no
warning, no refusal. Naming a config does the same. An index already built in the home database
moves into the service's with the two commands below.

### caracole index export and merge

    caracole index export FILE [--site SITE]...   # the site indexes into a new SQLite file
    caracole index merge FILE [--site SITE]...    # what FILE read more recently, into this database

The sites are `ug`, `lacuerda`, `gtptabs`, `musescore`, `harptabs` and `gametabs`. With no
`--site`, both commands take every one.

`export` copies the sites' indexes and how far each has got, and nothing of your songs. It takes
no lock, so it runs beside a nightly run. It never writes over a file, so name a new one. On a
NixOS or Ubuntu service, `sudo caracole-admin` can write only the library, state and cache folders,
so name a file in the state folder (`/var/lib/caracole/state/indexes.sqlite`); anywhere else it
exits 2 with "can't write".

`merge` takes caracole's lock, so it waits for a run. The file must be an export of the same
schema version as this database, or it exits 2 and changes nothing. A site at a time, it takes the
pages and sitemaps the file read more recently, or the database never read. What the database has
and the file lacks stays, and how far an index has got never moves back.

- New Ultimate Guitar tabs mark their songs to be fetched again, as a refresh does.
- LaCuerda's artist pages and search answers carry no time, so only those the database lacks come
  in.
- A gtptabs.com, MuseScore, harptabs.com or gametabs.net sitemap, or a LaCuerda listing page, the
  file only checked again and found unchanged moves its record on, and none of its rows is written
  ("its progress (sitemaps found unchanged)"); a sync's report leaves such a site out.
- A file that holds only part of an index (the phone's download, `POST /peer/index/newer`) says
  which sitemaps it left out. Those are never read as gone.

Before it changes a row it backs the database up into `backups/` (`…-before-merge.sqlite`), and
without room for that copy it merges nothing. A merge that only moves records on makes no backup. While it works it says how far it has got on stderr:
the comparison, the backup, each site's sitemaps or pages, and Ultimate Guitar's tabs as they go in
(`Ultimate Guitar · 41 sitemaps · 600,000 of 1,367,059 tabs`, 50,000 at a time). In a terminal
that is one live line, taken off for a warning; in a journal or a pipe, or with `-v`, a line a step
and one each quarter of UG's tabs; with `-q`, none. Then it says what each site took, on stdout:

    Merged /var/lib/caracole/state/indexes.sqlite into /var/lib/caracole/state/caracole.sqlite:
      Ultimate Guitar: nothing read more recently.
      harptabs.com: 10,413 artist pages; harptabs_index 37,545 rows (unchanged), harptabs_artists 15 → 10,428, harptabs_artist_tabs 30 → 21,498.

Merging the same file again changes nothing and makes no backup (`Nothing to merge: …`). To move
your home database's indexes into a service's, see
[deploy.md](deploy.md#moving-an-index-into-the-service).

### caracole index publish

    caracole index publish DIR [--force]
    caracole index publish DIR --kept NAME [--kept NAME]...

Writes every site's index as one public file in `DIR`: `indexes-s17-20261124T0312Z.sqlite.gz` (the
schema and the minute), an export as above, gzipped, with nothing of your own in it (no LaCuerda
search answers, no path of yours). It also writes `published.json` (the file, its sizes, its sha256
and each site's rows) and deletes the older `indexes-*.sqlite.gz` in `DIR`. It takes no lock, and like
`index build` it is refused beside a service unless you name its config or pass `--home`.
On a NixOS or Ubuntu service, `sudo caracole-admin` writes the publish folder,
`/var/lib/caracole/publish`, beside the library, state and cache folders, once publishing is set up
there (deploy.md); it can write no other.

It says what it does as it goes (the export, each site's rows, the check, then `Compressing · 31 of 75
MB`): one live line in a terminal, plain lines in a journal. To watch the service's run, `sudo
systemctl start --no-block caracole-publish && journalctl -fu caracole-publish`; for the live line,
run it in a terminal with `sudo caracole-admin index publish /var/lib/caracole/publish`. A publish
by hand starts no upload, as the service's run does with `publish.uploadUser` (deploy.md): then run
`systemctl --user start caracole-upload`.

It exits 1, leaving nothing behind, when the name exists, when UG's index isn't built whole, or
when a site holds a tenth fewer rows than `published.json` says of the last file. `--force` publishes
that one anyway. It also refuses a file that holds a path of this machine, naming the table and
column: a text value with your folders, your home folder, the database or `/nix/store/` in it, or one
that begins with a machine's root (`/home/`, `/var/`, `/nix/`, `/tmp/`, `/data/`, `/sdcard/`,
`file:` and the like). A site's name that just begins with `/` is no path.

It also refuses to publish while the clock reads earlier than the minute in the last file's name
(`published.json`). A file named in the past would never reach the phones, which take the newest
name. `--force` doesn't pass this one. Either clock may be the wrong one:

- If the clock now is wrong (it went back), set it right, then publish.
- If the clock now is right, the last file was stamped ahead. Delete that file and `published.json`
  from `DIR`, delete its asset from the release on GitHub, then publish again.

`--kept NAME` (repeated, once for each name) exports nothing and reads no config, so it answers
beside a service too. It prints, one a line and each once,
the names the Keep rule would delete. The rule: the publishing schema keeps its two newest files
whatever their age; every other schema keeps its newest for 180 days. Each file's schema is in its
name, and the publishing schema is this caracole's or the newest among the names, whichever is
higher. So an upload script built before a schema change never prunes what a newer caracole
published. A name that isn't a catalogue file (`indexes.json`, say) is kept, so never printed.

If `published.json` is there but can't be read, `publish` refuses (exit 1) and tells you to remove it
or pass `--force`.

## Two caracoles: the phone's and the computer's

    caracole peer diff ADDRESS [--json]                        # what differs, and which side each would come from
    caracole peer sync ADDRESS [--here ADDRESS | --push] [--prefer here|there] [--choose SIDE:ID]...
                               [--compared HASH] [--parts PARTS] [--progress] [--yes]
    caracole peer export FILE [--parts PARTS]                  # this library in a .caracole file
    caracole peer import SOURCE [--prefer here|there] [--choose SIDE:ID]... [--compared HASH] [--parts PARTS]
                                [--progress] [--yes]           # a sync with such a file
    caracole peer pull ADDRESS --unit ID [--unit ID]...        # take these from there
    caracole peer take [--progress] DIR                        # a push caracole serve staged (it queues this)
    caracole peer new-id                                       # for a database copied from another caracole's

You can keep one caracole on the computer and another on the phone. Each has its own library and
works alone, and a sync brings the two together.

Every command talks to the `caracole serve` at ADDRESS, such as `http://192.168.1.20:8737`
(`http://` is assumed if you leave it out). Start that server with `--address 0.0.0.0` so that it
can be reached ([caracole serve](#caracole-serve)). [The Share tab](#the-share-tab) does the same
from a browser, and [phone.md](phone.md) is the short tour of the phone's side.

A sync compares units. Each unit is taken whole or not at all:

- a song: its wanted.txt line, its match and lyrics, the versions caracole keeps with their files,
  and every overrides.toml entry about it, such as your own version, pins, transpositions, picks
  and `[ignore]`;
- a removal, a songbook, and overrides.toml's `[alias]`, `[artist_url]` and `[block]` entries.

A sync never carries PDFs or pages. The side that takes a song makes them again. It never carries
cooldowns, request counts or the HTTP cache either. The site indexes are not units: they move as
the `indexes` part ([Syncing parts, and the indexes](#syncing-parts-and-the-indexes)).

After a first sync, each side remembers what the two agreed on. A unit changed on one side only
comes from that side, so a song added or removed on one side is added or removed on the other. A
unit changed on both sides, to different things, is a conflict, and you choose which to keep.
Before the first sync there is no history: a unit only one side has comes from that side, and a
unit both have that differs is a conflict. What a sync or an import takes counts as agreed once
it is taken, even if what follows then fails (giving the other side its share, making the pages)
and the sync fails with it: a later change there alone still comes here, with no conflict.

Both sides must use the same sync format, format 3 today. Another format is refused. After an
upgrade from an older format, the first sync compares with no history. A song one side removed in
the meantime then shows up as a song to take from the other side. To keep it removed, choose `here`
for it on the side that removed it.

Both sides must also name songs by the same rules. A caracole whose rules changed (a new version
can spell a song's key otherwise) would see each of the other's songs as one removed and one added.
So a comparison, a pull, a push and an import between two such caracoles are refused before
anything changes: "This caracole and the other name songs by different rules: update both to the
same version, then sync." The Share tab answers it with a 409, and the commands exit 1 (an import,
2). A caracole older than this check says nothing of its rules and is read as before, so update
both sides.

`caracole peer diff` asks the other library what it holds, in one request, and lists every
difference with the side it would come from:

    3 differences, 1 conflict:
      Songs:
        theirs comes here  Estopa - Tu Calorro  (only in theirs)
        CONFLICT           Oasis - Wonderwall  (in both books, different, never shared)
        ours goes there    Radiohead - Creep  (only in our book)

It changes nothing on either side and takes no lock. `--json` prints the comparison as data.

`caracole peer sync` compares, then asks about each conflict: here, there or skip. `--prefer here`
or `--prefer there` answers them all. It says how many units each side takes and asks once before
going on, unless you pass `--yes`. Then it takes here what comes from there. How the other side
gets its share is under
[Syncing by hand](#syncing-by-hand-peer-sync---push---choose---compared).

`caracole peer pull` takes the units you name, as `diff --json` names them (`song/<key>`,
`songbook/<name>`). Written as `--unit THERE:HERE:ID`, with each side's digest as compared (`-`
for none), a unit is left alone if either side changed it since. `peer pull` waits for the nightly
run as a lookup does and backs the database up first (`…-before-sync.sqlite` in
`state_dir/backups/`).

A song arrives whole, with each file checked by its SHA-256, and is rendered again. It takes the
other side's spelling and folder ("Radiohead - Creep" for your "radiohead - creep"). If only the
capitals of the artist's name differ, every song here by that artist takes the new spelling. A
unit the other side doesn't have is removed here, as `caracole remove` would, so name only units
that `diff` lists. A unit that changed since it was compared is left. `peer pull` then says why
and exits 1:

    Left as it was: Radiohead - Creep: changed there since compared

`peer sync` and `peer import` say each unit they left the same way, by its name. A conflict left
unanswered says `changed on both sides: choose a side with --choose or --prefer`.

Without `--progress`, `peer sync`, `pull`, `take` and `import` also say each unit they took and
gave, by its name: `Took Estopa - Tu Calorro`, `Took Radiohead - Creep (removed)` for a removal,
`Took Radiohead - Creep (asked for again)` for a removal undone there while the song itself was
left, `Gave Blur - Song 2: changed on both sides` for a conflict settled (Took: theirs came; Gave:
yours went). A song and its removal's tombstone are one line. The phone's Journal says the same
lines, the first 20 each way, then `Took … and 312 more`.

Two caracoles whose databases are copies of each other count as the same caracole, and a sync
says so. `caracole peer new-id` gives one of them its own id. It also forgets what that one agreed
on with every other caracole.

### The phone pushes its changes (POST /peer/push)

The phone starts every sync and serves nothing to the network, so the computer can't pull from it.
The phone pushes the computer's share to `caracole serve` instead. The server stages the push in
`state_dir/peer/push-<id>/` and queues `caracole peer take`, which the Journal shows as "Changes
from <its library>".

`caracole peer take [--progress] DIR` takes the push the way a pull takes units. It waits for the
nightly run, backs the database up, leaves any unit that changed here since the phone compared
("changed here since the comparison"), then deletes the folder. It exits 1 for a push it refuses
(one that is gone, or from a caracole that names songs by different rules), else 0 unless caracole
hits a bug. `--progress` prints JSON lines for the Journal; while it renders the songs taken, its render
step says which it is at ("12 of 20 songs").

Two pushes can be staged at once, one per caracole (a second gets a 409). A file can be 64 MiB and
a whole push 2 GiB. A push left for an hour is deleted. A push that fails before its document is
taken is deleted at once: its sender drops it (`POST /peer/push/drop`), and a caracole's next push
replaces its push never sent, so a failed sync never blocks the next one.

A big give (a first sync of a whole library) goes in several pushes, each within those limits (a
push document is 16 MiB at most), one after the other, each taken before the next is sent. If one
fails, or its take isn't seen to end within ten minutes, the pushes before it stay taken, the
next sync gives the rest, and the sync says how far it got. While it waits for a push to be taken,
a lookup asked for meanwhile goes first; a song that lookup changes is left for the next sync. A
song with a kept file over 64 MiB is left out with the reason, as an export leaves it; the phone
takes no such file either.

`GET /api/peer/index` serves the site indexes as `caracole index export` writes them
(`?sites=ug,lacuerda` for some). It serves one copy at a time and answers 503 meanwhile.

`POST /peer/index/newer` serves only the part the phone doesn't hold, which is what the phone
asks for. The phone sends its record of each sitemap it holds and the time of the last export it
merged from this computer (JSON, with the form token, 1 MiB at most). The answer holds each
sitemap whose record differs, with all of its rows, the pages read a page at a time since then
(less an hour, and earlier for pages a merge brought in meanwhile), and every progress record.
After a night's refresh that is a few sitemaps of Ultimate Guitar's instead of all of them. A
computer older than the route answers 404, and the phone downloads the whole index as before; so
does a document past the limit (413). The first part after such a whole download sends every
page read a page at a time, once.

### Syncing by hand: peer sync --push, --choose, --compared

`caracole peer sync` gives the other side its share in one of three ways:

| Option | What happens |
|---|---|
| `--push` | This side pushes it, as the phone does, so only this side needs to reach the other. The sync waits up to ten minutes for the other to take it. |
| `--here ADDRESS` | The other side is asked to pull from ADDRESS, this side's own `caracole serve` as the other reaches it. The request shows in its Journal ("Share with …"). |
| Neither | The sync prints the `caracole peer pull` line to run there. |

`--choose SIDE:ID` settles one unit, whatever was proposed: `here` (the other side takes yours),
`there` (you take theirs) or `skip` (both stay as they are). ID is the unit's id from
`diff --json`, as in `--choose=there:song/radiohead/creep`. Repeat the option for each unit. A
conflict settled by neither `--choose` nor `--prefer` is left, and the sync says so. A choice for
a unit that no longer differs is refused (exit 2).

`--compared HASH` names the comparison you chose on, the `"compared"` value of `diff --json`. If
the two libraries differ from it now, the sync refuses before changing anything (exit 1). Compare
and choose again.

A unit that changed on either side since the comparison is left, with the reason. That doesn't
fail the sync (exit 0). The sync then records what the two agree on and the other side's address,
which the Share tab lists. `--progress` prints the stages (compare, take, give, agree, index),
each unit and a final report as JSON lines for caracole serve; while the take renders the songs
taken, it says which it is at ("12 of 20 songs").

### Export and import: peer export, peer import

`caracole peer export FILE` writes this library to one `.caracole` file. Give it to another
caracole, keep it, or carry it where the two can't reach each other. If FILE is a folder, the file
is named for the library and the day: `horde_logbook-03-11-26.caracole`. Export takes no lock and
never writes over a file. `--parts` says what goes in, and its default is `library,songbooks`:

| Part | What the file holds |
|---|---|
| `library` | Every song, removal, alias, artist's UG page and blocked tab. Also the songs' pages and PDFs, so that a phone that takes a song can open its sheet. |
| `songbooks` | Every songbook and the songs they list, even without `library`. |
| `indexes` | The site indexes, as `caracole index export` writes them. Hundreds of MB. |

A song is left out, with the reason, when one of its kept files changed since caracole kept it or
is bigger than 64 MiB. If index.html is not as caracole last wrote it, the file holds no pages:
run `caracole todo` first. The file includes what harptabs.com, gametabs.net and AZLyrics gave.
caracole sends it nowhere, so who gets it is up to you. It is a zip (format 1) with a manifest,
`caracole.json`.

`caracole peer import SOURCE` syncs with such a file as if its caracole were here. It takes what
changed there and records what the two agree on, so the next file or network sync shows only later
changes. A file takes nothing back. To give your changes, export a file of your own.

Import refuses a file, before changing anything (exit 2), when the file:

- isn't a caracole export, or comes from another version of caracole;
- comes from a caracole that names songs by different rules ("That file's caracole and this one
  name songs by different rules: update both to the same version, then export it again.");
- is cut short or damaged ("That file can't be read whole (…): export it again.");
- is this library's own export (`caracole backup` keeps copies to go back to);
- holds nothing newer than your last sync with its caracole ("Nothing in this file is newer than
  your sync with horde_logbook on 03/11/26."). Importing the same whole file twice ends this way.

Otherwise it backs the database up (`…-before-sync.sqlite`) and takes each unit as `peer pull`
does. A conflict goes by `--choose`, else `--prefer`, else you are asked, else it is left. A song
removed there is removed here, but a part the file doesn't hold never removes anything. Nor is the
removal taken while the song stays here: if you keep your song, the removal is answered with it,
and if the song's conflict is left, so is the removal ("its song is here: its removal there is not
taken"). Then it
renders the songs taken, records the agreement and merges the file's indexes if `--parts` names
them. `--progress` names these steps check, take, render, agree and index, and the render step says
which of the songs taken it is at ("12 of 20 songs").

If you choose to keep your own version of a unit, caracole remembers. The next file from that
caracole doesn't ask again unless the unit changed, and the next `peer sync` with it gives it your
version. `peer diff` lists such a unit as "kept here".

After `--parts songbooks`, or an import that left a unit, you can import the same file again for
the rest. `--parts indexes` alone records no agreement.

SOURCE can also be an index export, whose indexes are merged and nothing else. Or it is the folder
of an upload that caracole serve staged (`state_dir/peer/import-<id>/`, one at a time, 8 GiB at
most). That folder is refused until every part has arrived ("That file isn't whole yet: send the
rest of it."), and deleted after the import or an hour after its last part. An import that stops
where comparing again can settle it (the library changed since the comparison, a unit left)
keeps the folder for an hour from its end, so the Sync tab's Compare again needs no new upload.

`--choose`, `--prefer`, `--compared`, `--progress` and `--yes` work as for `peer sync`. Import
exits 2 for a file refused or an option it can't take (a `--choose` that names no difference
now). It exits 1 when the library changed since the comparison, you answer no to "Go on?",
overrides.toml or songbooks.toml can't be read, it took nothing for want of a backup, its indexes
weren't merged, or for a bug. Otherwise it exits 0. A unit left is no failure, as for `peer sync`:
the Journal says "Shared · 1 change left as it was", as the phone's does, and its Output names the
unit and why.

### Syncing parts, and the indexes

`--parts`, of `peer sync` and `peer import`, takes `library`, `songbooks` and `indexes`, separated
by commas. The default is all three. A difference outside the parts is not taken, given or listed,
but a song that a songbook lists comes along with `songbooks`.

With `indexes`, the sync ends by bringing each site's index up to date on both sides (its `index`
stage). Whichever side read a site more recently gives that index to the other:

- An index taken here is downloaded and merged as `caracole index merge` does, after a backup
  (`…-before-merge.sqlite`), saying how far the merge has got as `index merge` does. With
  `--progress` that is the `index` stage's detail, which the Sync sheet shows. A `peer import` of a
  file's indexes says it the same way.
- An index given there is exported and uploaded to the other server, which merges it as a queued
  `caracole peer import`. The sync waits up to ten minutes for it. The other side must run this
  version of caracole or a later one.

If neither side is newer, nothing is sent ("no index is newer on either side"). If the other
side's database is of another schema, no index goes either way, since its merge would refuse the
file once downloaded: the stage says which side to update ("The indexes there are of a newer
caracole: update this one to take them"), and so do the Sync sheet's **Site indexes** line, its
summary once the sync is over, the Journal's outcome after what it shared, and the phone's Sync on
Wi-Fi line. The units still sync. If the stage fails, the sync says why and exits 1, and the units stay
synced.

The copies of an index being taken, given or merged live in `cache_dir/peer/` and are deleted once
done. A copy left by a sync or import that was killed is deleted an hour later, when the next
`peer sync` or `peer import` starts, or when caracole serve is next asked for its indexes.

### The Share tab

The library page from `caracole serve` has a **Share** tab, the last one, with three panels:
**Sync with a server**, **Export** and **Import a file**. Each opens the same sheet as the phone's
sync button.

To sync, type the other server's address. The last one you used is filled in. **Test** asks that
server what it holds and changes nothing ("✓ Studio answered: 96 songs, 3 songbooks, its indexes
read 02/11/26"). **Sync** opens the sheet:

1. It compares first, changing nothing, and shows three ticked parts: **Library**, **Songbooks**
   and **Site indexes**. Each says what waits in it. The top counts ↓ to take, ↑ to give and ⚠
   changed on both.
2. Changes made on one side only go through by themselves. A song or songbook changed on both
   sides gets a card that shows how the versions differ. Pick **This computer** or the other
   side's name. Tick **Same for the other N** first to answer the rest the same way. There is no
   skip: **Cancel** ends the sync with nothing taken or given.
3. A summary lists what was taken and given, whose version each conflict kept, and what each
   index brought: its new tabs ("+231 new tabs · 1,503,236 in all"), "up to date", or "all new
   here" for a site this side had none of.

The sync runs as a request in the Journal. Behind it is
`caracole peer sync ADDRESS --push --parts=… --compared HASH --choose=SIDE:ID …`. If it left
something or failed, the Journal offers **Compare again**, because your choices belonged to a
comparison that is past. Its Output names each unit left and why, as the phone's Journal does.
If the libraries changed after the comparison, Sync is refused and the sheet compares again,
keeping your choices.

**Export** shows each part's size. Library and Songbooks are ticked. Site indexes is not, because
it is big. The browser saves `<library name>-dd-mm-yy.caracole`
([Export and import](#export-and-import-peer-export-peer-import)). The server sends the file once,
so export again for another copy.

**Import a file** uploads the file you choose and opens the sheet as a sync with it. A part the
file doesn't hold is greyed ("Not in this file"), and a conflict's other side is the file. Nothing
is given back. The server holds one file at a time and drops it if you cancel.

The sheet also opens from the address: add `#sheet=sync`, `#sheet=export` or `#sheet=import` to
the library page's address.

The phone's Sync on Wi-Fi is the same sync, unattended. It syncs all three parts and leaves every
conflict as it is on both sides, for you to choose later.

The tab's routes, which the phone's own server answers the same way:

| Route | What it answers |
|---|---|
| `GET /api/sync` | This caracole's id, name and `device` (`computer` or `phone`), its counts, the addresses it synced with. |
| `POST /sync/test` | What the caracole at `address` holds. 400 for a bad address, 502 when nothing answers, 409 for this very caracole. |
| `POST /sync/compare` | The comparison, with `indexes_skipped` saying why no index goes when the other's database is of another schema. |
| `GET /api/sync/unit?comparison=&id=` | One unit as both sides hold it. |
| `GET /api/sync/indexes` | Each site's index: its newest read and the tabs it tracks. |
| `POST /sync/apply` | Queues the sync. `parts` works as `--parts`. |

### Each caracole's own politeness, and the computer's settings on the phone

Each caracole keeps its own request limits. The phone and the computer each count their own
requests to a site, keep their own pace and cooldowns, and keep their own record of what they
asked (LaCuerda's searches, Megalobiz's daily count, the 30-day checks). A sync carries none of
it, in either direction. A site that blocks the phone cools down the phone only.

So two caracoles at one address can together send a site more than one caracole's limits. Each
has its own `lookup_per_hour`, Megalobiz's 900 a day and LaCuerda's 20 searches an hour. The phone
only does lookups, so it adds little.

A sync does carry the computer's settings to the phone, as `settings` in `GET /api/peer/state`:

```json
{"name": "Canciones", "user_agent": "caracole/0.1 (personal tab library)",
 "providers": {"ug": {"enabled": true, "lookup_delay": [0.125, 0.375], "lookup_requests": 6, "lookup_per_hour": 60,
                      "per_day": null}, "…": {}},
 "match": {"accept": 90, "margin": 8, "review": 75, "artist_gate": 90},
 "rank": {"coverage_threshold": 0.8, "line_match": 85, "prior_votes": 10, "scored_sheets": 3,
          "label_penalty": 0.5, "variant_bonus": 0.25}}
```

They come from caracole.toml ([Configure](#configure)): its `name` (null if it sets none), its
`user_agent`, each provider's `enabled` and lookup settings, and `[match]` and `[rank]`, so that
the phone matches and ranks as the computer does. `per_day` is not a caracole.toml setting. It is
900 for Megalobiz and null for every other site. The computer never sends a run's `budget` or
`delay`, a folder, a program or your ntfy topic, and the phone sends no settings back.

The phone replaces its settings at each sync. A computer that gives none, or a sync that fails
early, leaves them as they were. The phone's pages show the library's `name`.

### The phone's reads go to the computer (POST /peer/index)

The pages the phone's lookups read are useful to the computer too: an artist's Ultimate Guitar
pages, LaCuerda's artist pages and search answers, harptabs.com's artist pages and gametabs.net's
game pages. At the end of every sync, the phone posts the ones it read since its last push to that
computer (`POST /peer/index`, 64 MiB at most). `caracole serve` stages the file as
`state_dir/peer/index-<16 hex>.sqlite` and queues its merge, "Index pages from another scribe" in
the Journal:

    caracole index merge --delete --progress -- FILE

This is the usual merge ([caracole index export and merge](#caracole-index-export-and-merge)),
with a backup of the database first. `--delete` deletes FILE once it is merged. It also deletes a
refused file that caracole serve staged, never one you named by hand. A file whose merge couldn't
start stays, so **Try again** works. `--progress` reports the merge as JSON lines for the
Journal, with how far it has got as the stage's detail.

If the computer refuses the file or doesn't answer, the phone keeps the pages for the next sync
and the sync says why. A 409 means the two run different versions of caracole, or two files
already wait to be merged. A 404 means the computer's caracole is too old for this route.

The phone waits for that merge, up to 10 minutes, and forgets the pages only once it is done. If
the merge fails, or is still going, the next sync sends them again; merging the same pages twice
changes nothing. Once merged, the computer's newest read of a site may be the phone's own page.
The phone notes that, so its next sync doesn't download the site's whole index for it.

### What the offline copy lists

`GET /api/offline` ([caracole serve](#caracole-serve)) lists every file the app copies. Each file
of a song or a songbook names its sync unit. `unit` is `song/<key>` or `songbook/<name key>` (the
name in lowercase, its spaces collapsed), and `digest` is that unit's digest when the list was
made. `index.html` carries no unit. Neither does a file that two songs sharing a folder could both
own, such as `info.json`.

The app shows a page it copied unless the phone changed or removed that song since. Then it shows
the phone's own pages of the song. Until those are made, it says the song changed on the phone and
links to the phone's sheet text. A song removed on the phone says so.

While overrides.toml or songbooks.toml can't be read, `/api/offline` answers 503 with what is
wrong, and the app keeps the copy it has. The list's `format` is still 1.

## Running it on a server

[deploy.md](deploy.md) sets caracole up as a nightly service, on NixOS with the flake's module or
on Ubuntu 24.04 without Nix. It covers the timer, the hardened units, Syncthing, restic backups,
the offline auto-chords unit, and caracole-web, which serves the library page to your LAN or
tailnet with no sign-in. On the server, run any command as the service does with
`sudo caracole-admin COMMAND`, for example `sudo caracole-admin index build`.
