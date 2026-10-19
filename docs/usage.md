# Using tabarr

You list the songs you want to learn. Tabarr builds a private library: a
sing-along sheet (chords over full lyrics) for each song, plus guitar parts
where they exist. It runs nightly, and it asks you only for what it can't
decide itself, on `Library/_todo.md`.

## 1. Configure

Tabarr reads `~/.config/tabarr/tabarr.toml`, or the file given with
`--config` or `$TABARR_CONFIG`. Every key is optional, and an unknown key is
an error.

```toml
library_dir = "~/Tabs"            # sheets, lyrics, guitar parts, _todo.md, wanted.txt, overrides.toml
music_dir = "~/Music"             # tracks you bought (read-only; used only for auto-chords)
# state_dir, cache_dir default to $STATE_DIRECTORY/$CACHE_DIRECTORY, then XDG
# cjk_font = "/path/to/NotoSansCJK.otf"   # PDFs with Chinese/Japanese/Korean lyrics

[spotify]                         # optional: without a client_id Spotify is skipped
client_id = "your-app-client-id"
playlists = ["Learn"]             # names, ids or URLs of playlists you own
liked_songs = true
suggest_top_tracks = true         # listed on the to-do page, never added automatically
# client_secret: $CREDENTIALS_DIRECTORY/spotify_client_secret, client_secret_file, or
# $TABARR_SPOTIFY_CLIENT_SECRET

[ntfy]                            # optional
url = "https://ntfy.sh/your-private-topic"
# token: $CREDENTIALS_DIRECTORY/ntfy_token, token_file, or $TABARR_NTFY_TOKEN

[providers.ug]                    # the defaults, shown for reference
budget = 60                       # requests per run
delay = [10, 20]                  # seconds between requests, chosen at random

[match]                           # the defaults
accept = 90
margin = 8
review = 75

[rank]                            # the defaults
coverage_threshold = 0.8          # a sheet is complete when it covers 80% of the lyric lines
line_match = 85
prior_votes = 10
```

## 2. Say what you want to learn

**`wanted.txt`** sits in the library folder and always works, with or
without Spotify. Edit it anywhere, including on your phone through
Syncthing. Each line is one song:

    # Artist - Title | Album | m:ss   (album and duration are optional)
    宋冬野 - 斑马斑马 | 安和桥北 | 4:13
    Soda Stereo - De Música Ligera
    Radiohead - Creep | Pablo Honey | 3:58

`tabarr add "宋冬野" "斑马斑马" --album 安和桥北 --duration 4:13` appends a
line for you.

**Spotify (optional):**

1. Create an app at developer.spotify.com, with redirect URI
   `http://127.0.0.1:8888/callback`.
2. Put its `client_id` in the config and the secret where the config section
   above says.
3. Run `tabarr auth spotify`. It prints a URL; open it, approve, and paste back
   the address you're redirected to (the page itself won't load).

The token is refreshed automatically. Spotify expires it after about six
months, and tabarr alerts you then. If Spotify fails, the run carries on with
`wanted.txt`.

## 3. First run

    tabarr index build      # once: about 41 UG sitemaps, 10–20 s apart (about 10 minutes)
    tabarr match --dry-run  # how every song matched, without saving anything
    tabarr run              # what the nightly timer runs

**What a run does:**

1. Syncs your songs.
2. Refreshes the newest UG sitemaps.
3. Matches songs locally.
4. Fetches lyrics from LRCLIB.
5. Fetches and ranks sheets within the request budget (60 UG requests per
   run, so a big backlog fills in over a few nights, newest songs first).
6. Tries LaCuerda for Spanish songs.
7. Files purchases and inbox downloads.
8. Renders PDFs.
9. Rewrites `_todo.md`.

Individual steps have their own commands: `tabarr sync`, `tabarr lyrics`,
`tabarr fetch`, `tabarr scan`, `tabarr render`, `tabarr todo`,
`tabarr review`, `tabarr autochords`.

## 4. The to-do page

`Library/_todo.md` lists only what needs you:

- **Review.** Matches tabarr wasn't sure about, each with links and the exact
  `overrides.toml` lines to paste. `tabarr review` asks you one question per song
  instead.
- **Partial sheets.** The best sheet available covers less than 80% of the
  lyrics.
- **Artists to find on Ultimate Guitar.** UG's sitemaps list some artists only
  by bare ids, usually because of accents or non-Latin letters (Joaquín Sabina,
  Maná, 宋冬野), so tabarr can't see their tabs. Find the artist page once, by
  hand, and paste its address under `[artist_url]`.
- **Buy list.** No human sheet exists. Buy the track (DRM-free) and drop it
  into `Music/`, and tabarr generates an auto sheet. Links to check the song on
  Chordify, Songsterr or YouTube first.
- **Guitar Pro pages to click.** Download each file with the page's Download
  button and drop it into `_inbox/`. Tabarr never downloads these itself,
  because UG's download endpoint is closed to bots.
- **Guitar parts not found**, **missing lyrics**, **suggestions** from your
  Spotify top tracks, **sources**, and **provider health** (blocks and
  cooldowns).

## 5. overrides.toml: your decisions

The file sits in the library folder by default. Tabarr writes to it when you
use `tabarr review`, and keeps your comments.

```toml
[alias]          # source artist -> UG artist slug: fixes every song by that artist
"Bob Marley & The Wailers" = "bob-marley"

[match]          # song -> UG song ("artist-slug/song-slug"); still picks up new tabs
"Soda - Persiana Americana" = "soda-stereo/persiana-americana"

[artist_url]     # artists UG lists only by bare ids
"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/joaquin_sabina_12345"

[pin]            # always use exactly these tab pages
"Soda Stereo - De Música Ligera" = ["https://tabs.ultimate-guitar.com/tab/85053"]

[transpose]      # semitones, applied when PDFs are rendered
"Soda Stereo - De Música Ligera" = -2

[ignore]
songs = ["Some Artist - Some Interlude"]

[block]          # tabs never to use
tab_ids = [1601668]
```

Song keys are written `"Artist - Title"`. They match the way songs match, so
case, accents, a leading "The" and Spotify suffixes such as "- Remastered
2011" don't matter.

## 6. The library

```
Library/
  _todo.md  wanted.txt  overrides.toml
  _inbox/                     Guitar Pro downloads waiting to be filed
  宋冬野/
    斑马，斑马/
      sheet.txt  sheet.json   the chosen chord sheet, plain text and as the source gave it
      sheet.cho  sheet.pdf    ChordPro, and a PDF in your key
      lyrics.txt lyrics.lrc   from LRCLIB (.lrc only when timed lyrics exist)
      guitar-1.gp5            assisted Guitar Pro downloads, best first
      tab.txt                 the best text tab
      sheet (auto).txt        generated from audio you bought, when no human sheet exists
      info.json               where everything came from
```

Keep the library private. Sheets and lyrics are other people's work, and a
personal offline copy is the closest thing to the sites' personal-use terms.
