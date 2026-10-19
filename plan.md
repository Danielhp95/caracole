# Tabarr, simplified

**Version 2.1 of the design, 18 October 2026.** This version is updated with your answers: you have Spotify Premium, you're learning guitar only, lyrics matter because you sing, and you can buy audio files.

This review replaces the first report's architecture with a much smaller one. The first report is still the reference for Spotify's 2026 rules, the provider terms of service, and the audio chord models. This version changes what you build and in what order.

## The short version

The first design was a general-purpose music identity engine, with a lot of machinery:

- an 11-step network search ladder;
- seven wanted states;
- eight format tiers;
- per-instrument profiles;
- four dedupe layers;
- a Node sidecar;
- a headless browser;
- a web UI.

For one person on one NUC, most of that costs more than it returns. Four ideas make a much smaller design possible.

1. **Ultimate Guitar publishes sitemaps of its tab pages, and its robots.txt disallows its search page.** So don't search UG song by song. Download the sitemaps once, build a local index of every tab URL (artist, song, type, id), and match your songs against it on the NUC.
   - Tabarr sends no search requests at all.
   - Re-searching a not-found song becomes a free local re-match.
   - New tabs show up in the newest sitemap, which works like the RSS feed Sonarr relies on.
2. **One tab page lists every version of that song with its type, rating and vote count.** So each matched song costs one page fetch to rank all its versions, plus one fetch per file you keep.
3. **Because you sing, every song gets two slots.**
   - **A sing-along sheet** (chords plus full lyrics). Tabarr insists on this one.
   - **An optional guitar part** (Guitar Pro or tab) for riffs, intros and solos.

   Lyrics come from LRCLIB for every song. They are saved on their own, and they are used to catch chord sheets with missing verses.
4. **Buying the audio unlocks the last tier.** A song nobody has charted can still get a sheet:
   - You buy the track, at about a dollar.
   - A local model generates timed chords and merges them with LRCLIB's synced lyrics.
   - Only songs with no human sheet need this, so the cost stays small.
   - Chordify stays a link you click, because its terms forbid automation.

The result is:

- a command-line tool that a systemd timer runs nightly;
- one SQLite file;
- one TOML file holding your decisions;
- a library folder of sheets, lyrics and guitar parts, with a to-do page.

That is roughly a third of the first design's moving parts.

## What your answers changed

| Your answer | What it changed |
|---|---|
| Spotify Premium | The Spotify source works as designed; no fallback is needed |
| Guitar only | Bass and ukulele are dropped; the guitar-part slot looks only at guitar formats |
| You sing | Two slots per song; lyrics fetched for every song; sheets ranked by how much of the lyrics they contain; ChordPro, PDF and per-song transposition moved earlier |
| You can buy audio | Local auto-chords now covers any song, through a buy list; Navidrome becomes optional |

One choice is still yours: **assisted or automatic Guitar Pro downloads** (section 3). The default is assisted.

## What changes from the first design, and why

| First design | Simplified design | Why |
|---|---|---|
| Per-song UG search with an 11-step ladder | Local match against an index built from UG's sitemaps | `search.php` is disallowed in robots.txt; local matching is instant, unlimited and re-runnable |
| Exponential re-search backoff per song | Re-match locally after each sitemap refresh | New tabs arrive in the newest sitemap, so nothing needs scheduling per song |
| Weighted listening signals from many sources | Liked Songs plus playlists you choose, ideally one "Learn" playlist | Your intent is explicit, the wanted list stays small, and fewer requests are made |
| MusicBrainz canonicalization of every track | Manual aliases, plus MusicBrainz later and only if leftover misses need it | Your library is mostly Latin-script English and Spanish |
| 7 states multiplied by instrument profiles | 3 states (wanted, found, ignored), a review flag, no instrument profiles | You play guitar and sing; nothing else |
| 8 format tiers on one ladder | Two slots: a sing-along sheet (required) and a guitar part (optional) | A singer needs lyrics with chords; a Guitar Pro file doesn't replace that |
| Bayesian rating, file introspection, roles and upgrade hysteresis | Sheets: lyrics coverage, then Bayesian rating. Guitar parts: Bayesian rating. Keep the top N and replace when outranked | Introspection waits until ratings prove insufficient |
| 4-layer dedupe | Unique (provider, tab id) plus a SHA-256 of the file | Keeping 1–2 files per slot makes near-duplicate detection moot |
| ChordPro normalization in the core path | Sheets saved as plain text with the raw JSON beside them; ChordPro, PDF and transposition added in step 3 | Plain text first; transposition for your voice next |
| FastAPI, HTMX and an asyncio loop | Command line, systemd timer and a `_todo.md` page, with a review TUI later | No server to run, secure or keep alive |
| Playwright with Chromium | httpx with cookies from your own browser | This removes the hardest Nix packaging and hardening problems |
| uv2nix | `buildPythonApplication` on nixpkgs dependencies | Every dependency is already in nixpkgs |
| healthchecks.io, Prometheus, a NixOS VM test | An ntfy summary per run, plus ntfy from systemd `OnFailure` | That is enough for one machine |
| A 200–300 track labelled evaluation set in CI | Parser fixtures plus a dry-run diff of match decisions | Matching is local, so you can re-check your whole library in seconds |
| A Chordify MIDI import pipeline | A Chordify link on the to-do page | Chordify's terms forbid automation, and a link is zero code |
| 9+ providers | UG now; LRCLIB lyrics for every song; LaCuerda next; local auto-chords on audio you buy; MuseScore maybe | Effort goes where your songs are |

**Kept from the first design:**

- **Errors are not misses.** A 403, a 429, a challenge page or a parse failure is a provider error, never a "not found".
- **Never escalate after a block.** No proxies, no browser fingerprinting, no IP rotation.
- **Formats are ordered by quality.** Each slot has an ordered list of formats, and a song upgrades when a better one appears.
- **Ratings are shrunk by vote count** (a Bayesian average).
- **Artist aliases are learned from your corrections.**
- **Secrets and hardening:** the Spotify token lives in writable state, static secrets go through agenix or sops-nix, and the service uses Sonarr-style systemd hardening.
- **The legal map:** free content through its intended path, link-outs for services that forbid automation, and no paywall-circumvention tools.

## The design

### 1. Sources: tell it what you want to learn

**Spotify**

- **What to read:** Liked Songs (`GET /me/tracks`) plus the playlists you list in config. The best signal is a dedicated "Learn" playlist that you add to from your phone. Development Mode only returns the contents of playlists you own or collaborate on, so editorial playlists won't work ([migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)).
- **Top tracks:** optionally read `/me/top/tracks` to suggest songs. Have tabarr list these on the to-do page instead of fetching them automatically.
- **Library:** use spotipy 2.26.0, which is in nixpkgs unstable and already follows the 2026 playlist `/items` rename.
- **Auth:**
  - `tabarr auth spotify` prints the authorize URL, and you paste back the URL you were redirected to.
  - Register `http://127.0.0.1:8888/callback` as the redirect URI; `localhost` is rejected ([redirect URIs](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)).
  - The token lives in the state directory.
  - Refresh tokens expire six months after issue, so expect to re-authorise twice a year. Tabarr sends an ntfy alert when a refresh fails ([refreshing tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens)).
- **Premium:** a Development Mode app needs its owner to have Spotify Premium, which you have ([Spotify blog](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)).

**Your music folder**

- Tabarr reads a `Music/` folder of tracks you've bought. It uses this only as audio for auto-chords, never as a list of wanted songs.
- If you later run Navidrome, point it at the same folder. Tabarr doesn't need Navidrome.

**GDPR history export (optional)**

- A one-off import: `tabarr import spotify-history <zip> --top 200`.
- Count only plays of at least 30 seconds that weren't skipped.

**The song record**

- Fields: title, artists, album, duration, ISRC if known, source ids, and date added.
- Spotify's duration is what makes the lyrics lookup exact.
- Process the queue newest first, so a song you just added gets its sheet that night.

### 2. Discovery: a local index of Ultimate Guitar

**What UG publishes** (checked 2026-10-18):

- **robots.txt on www.ultimate-guitar.com:** disallows `/search.php` for all user agents. Artist pages are not disallowed, and there is no crawl delay ([robots.txt](https://www.ultimate-guitar.com/robots.txt)).
- **robots.txt on tabs.ultimate-guitar.com:** disallows `/tab/download`, `/tab/print?` and `/download/public/`. Ordinary tab pages are allowed ([robots.txt](https://tabs.ultimate-guitar.com/robots.txt)).
- **The sitemap index:** it lists 82 child sitemaps ([sitemap.xml](https://www.ultimate-guitar.com/sitemap.xml)).
  - `sitemap1`–`sitemap40` and `sitemap_last` list tab pages in the form `tabs.ultimate-guitar.com/tab/{artist}/{song}-{type}-{id}`.
  - The type tokens seen were `tabs`, `chords`, `bass`, `guitar-pro` and `ukulele`. Some entries are a bare `/tab/{id}` with no artist or song in the URL.
  - `sitemap_last` holds the newest ids, with modification dates into October 2026 ([sitemap1](https://www.ultimate-guitar.com/sitemap1.xml); [sitemap40](https://www.ultimate-guitar.com/sitemap40.xml); [sitemap_last](https://www.ultimate-guitar.com/sitemap_last.xml)).

**How tabarr uses it**

- **`tabarr index build`** fetches the child sitemaps once, slowly. It parses each URL into a row `ug_index(artist_slug, song_slug, type, tab_id)`.
  - Peel the trailing `-{id}` first, then the type suffix. Try `guitar-pro` before the single-word types.
  - Keep only `chords`, `tabs` and `guitar-pro`, and skip bare ids.
  - The sitemap protocol caps each file at 50,000 URLs, so the tab sitemaps hold at most about two million entries. Expect a few hundred MB of XML once; I haven't measured it.
- **`tabarr index refresh`** runs every night but re-fetches only `sitemap_last` and the highest-numbered sitemap. A new row matching a wanted song triggers a versions fetch for that song.
- **A full rebuild** can run monthly, or never.

**The local matching ladder**, all offline:

1. **Overrides** from `overrides.toml`: a pinned URL, an alias, or ignore.
2. **Exact match:** the artist's slug plus the cleaned title's slug.
3. **Fuzzy title within each of the song's artists:** rapidfuzz `ratio` on slugs.
4. **Fuzzy artist:** first the alias table, then the nearest artist slug above a gate of 90, then step 3 again.
5. **Title only, across all artists:** catches covers and misfiled tabs. These always go to review. rapidfuzz over the in-memory slug list is fast enough; add SQLite FTS5 trigram search only if it isn't.

**Normalization**, in order:

1. Unicode NFKD, then strip accents, then lowercase.
2. Replace "&" with "and" and drop a leading "the".
3. Drop Spotify's version suffixes: " - Remastered 2011", " - Live", "(feat. …)", "(Live at …)", " - Radio Edit".
4. Slugify with hyphens the way UG does.

Keep "acoustic" and "live" as a preference when ranking versions, not as a reason to treat songs as different.

**Decision rule**

- **Accept** when the best score is at least 90 and beats the next different title by at least 8 points.
- **Review** when it scores 75–90.
- **Not found** otherwise.

These thresholds are starting points. After the first run, `tabarr match --dry-run` prints every decision. Because matching is local, you can change the normalizer and re-check your whole library in seconds. Each review correction writes an alias, such as Spotify artist → UG artist slug, which fixes every song by that artist at once.

### 3. Fetch, rank and keep

**Two slots per song**

| Slot | Formats, best first | Required? | Keep |
|---|---|---|---|
| Sheet | Human chords over lyrics (UG Chords, LaCuerda acordes) → auto-chords with synced lyrics → lyrics only | Yes: a song is "found" only once it has a human or auto sheet | 1 |
| Guitar part | Guitar Pro (.gp3–5, .gpx, .gp) or Power Tab → ASCII tab | No; it never blocks "found" | 2 Guitar Pro, 1 tab |

**Lyrics for every song.** Before anything else, tabarr asks LRCLIB for the song's lyrics.

- **The lookup:** artist and title are required; album and duration are optional but make the match exact. LRCLIB's lookup accepts a duration within ±2 seconds ([LRCLIB source](https://github.com/tranxuanthang/lrclib)).
- **The files:** it saves `lyrics.txt` (plain) and `lyrics.lrc` (timed by line).
- **Why it matters:** this is one request per song, and it gives you lyrics even when no sheet exists. It is also the yardstick for checking sheets.
- **Spanish:** an earlier test returned "De Música Ligera" with synced lyrics for an unaccented query.

**Per matched song:**

1. **Fetch the matched tab page.** Its embedded JSON at `div.js-store[data-content]` → `store.page.data.tab_view.versions` lists the song's versions with type, version number, rating and votes. freetar, a maintained self-hosted UG front end, reads exactly this field to show "other versions" and filters out only `Official` ([freetar ug.py](https://github.com/kmille/freetar/blob/main/freetar/ug.py)).
2. **Rank sheets in two passes:**
   - **First, completeness:** whether the sheet's lyrics cover at least 80% of LRCLIB's lines. A line counts as covered when rapidfuzz `partial_ratio` against the sheet is 85 or more.
   - **Then, the Bayesian rating** `(v·R + m·C)/(v + m)`, where v is the version's vote count and R its rating. Start with m = 10 and C = the vote-weighted mean of that song's versions.

   A sheet with chords only for the first verse, or no lyrics at all, sinks below any complete one, but it is kept if nothing better exists. Coverage needs the sheet's text, so fetch only the top three sheets by rating and score those.
3. **Rank guitar parts** by the Bayesian rating alone. Give a small penalty when a version is labelled intro, solo or lesson, if the data carries such a label. Skip `Official`.
4. **Download the kept files.**
   - **Sheets and text tabs:** fetch the version's page and save `wiki_tab.content` as plain text, with the raw JSON beside it.
   - **Guitar Pro:** see below.

**Guitar Pro downloads**

UG's help centre says free user-submitted Guitar Pro files can be downloaded with the website's download button, and Official tabs can't ([UG Help](https://help.ultimate-guitar.com/en/articles/6749046-website-can-i-download-pro-tabs)). The endpoint behind that button, `/tab/download?id=`, is disallowed for bots in the tabs host's robots.txt. That leaves two modes, and the choice is yours:

- **Assisted (the compliant default):**
  1. The to-do page lists the Guitar Pro pages tabarr picked.
  2. You click Download on your laptop and drop the files into `Library/_inbox/`.
  3. Tabarr files each one under the right song by matching the file name.
- **Automatic:**
  - httpx sends the request with cookies exported from your logged-in browser.
  - It makes at most about 10 downloads a night, 10–20 seconds apart.
  - It is low volume and acts as you, but it does go against the robots rule.

**Upgrades and dedupe**

- **Upgrades:** when an index refresh adds a new tab id for a wanted song, tabarr re-fetches that song's versions and replaces a kept file only if the new version outranks it. An auto sheet is replaced as soon as a complete human sheet appears. Nothing else re-runs.
- **Dedupe:** unique (provider, tab id), plus a SHA-256 of each downloaded file.

**Later, only if ratings mislead:**

- Open Guitar Pro files and check them: estimated length against the recording, the share of empty bars.
- PyGuitarPro reads gp3–5. It is a small pure-Python package, not in nixpkgs.
- alphaTab reads every Guitar Pro version, from a small Node script.

### 4. When UG has no sheet

Work down this list:

1. **LaCuerda, for Spanish songs.**
   - URLs are predictable: `acordes.lacuerda.net/{artist}/{song}` in lowercase with underscores, accents stripped and ñ written as "ni".
   - The artist page lists every song, and each song page lists its versions best first. Its "acordes" versions are chords over lyrics.
   - One artist-page fetch serves every song by that artist.
   - Accept solfège chord names (Do, Re, Mi…).
   - Cifra Club can follow later.
2. **Buy the audio, then generate the sheet.**
   1. The to-do page keeps a buy list: songs with no human sheet, each with search links to DRM-free download stores such as Bandcamp, Qobuz and the iTunes Store.
   2. Drop each purchase into `Music/`.
   3. Tabarr matches the file to its song by tags and duration (mutagen).
   4. It runs auto-chords: BTC chord recognition, beat_this to snap chord changes to bars, then a merge with LRCLIB's timed lyrics into `sheet (auto).txt`.

   Expect a few seconds per song on CPU. The step runs as a separate unit with no network access, because the model weights ship with the package. The sheet is marked "auto-generated, unverified", and a human sheet replaces it as soon as one appears.
3. **Links, for songs you haven't bought:** Chordify, Songsterr, and a YouTube search for "{song} guitar lesson".
   - Chordify lets you check a song in its own player before you buy the track.
   - Its terms forbid automated access, including scripting your own paid account.
   - Premium ($3.50 a month, billed yearly) is worth it only if you'll use that player regularly.
4. **Lyrics only.** The LRCLIB lyrics are already in the folder, so even a song stuck at this step is singable while you work out the chords.

**Music.AI** ($0.04 a minute) can replace the model in step 2 if you'd rather not run one. It also needs the purchased file.

**MuseScore can wait.** It has no API, caps downloads at 20 a day, and most of its scores are standard notation without a TAB staff.

### 5. State and files

**SQLite**, five tables:

| Table | Holds |
|---|---|
| `songs` | id, title, artists, album, duration, ISRC, source ids, date added, status, review flag, lyrics status |
| `ug_index` | artist slug, song slug, type, tab id |
| `versions` | provider, tab id, song id, slot, rating, votes, version number, label, lyrics coverage, raw JSON, fetch time |
| `files` | version, path, SHA-256, kept rank |
| `events` | run, provider, URL, HTTP status, decision, message |

**`overrides.toml`** holds your decisions and can live in git:

```toml
[alias]                       # source artist -> UG artist slug
"Bob Marley & The Wailers" = "bob-marley"

[pin]                         # always use these pages for a song
"Soda Stereo - De Música Ligera" = ["https://tabs.ultimate-guitar.com/tab/85053"]

[transpose]                   # semitones, applied when sheets are rendered (step 3)
"Soda Stereo - De Música Ligera" = -2

[ignore]
songs = ["Some Artist - Some Interlude"]

[block]
tab_ids = [1601668]
```

**The library**, synced with Syncthing to your laptop (for TuxGuitar) and phone:

```
Music/                      tracks you bought (read-only for tabarr)
Library/
  _todo.md
  _inbox/                   Guitar Pro files you download in assisted mode
  Soda Stereo/
    De Música Ligera/
      sheet.txt             chords over lyrics, as the source shows it
      sheet.cho             ChordPro (step 3)
      sheet.pdf             rendered, in your key (step 3)
      lyrics.txt
      lyrics.lrc
      guitar-1.gp5
      guitar-2.gpx
      tab.txt
      info.json
```

**`_todo.md`** is the whole UI until you want more. It lists:

- **Review items:** each with candidate links and the override line to paste.
- **Partial sheets:** sheets under 80% lyric coverage.
- **The buy list:** songs with no human sheet, with store links.
- **Not-found guitar parts:** each with its Songsterr and YouTube links.
- **Guitar Pro pages to click**, in assisted mode.
- **Provider health.**

### 6. Running it on the NUC

**One nightly `tabarr run`:**

1. Sync Spotify.
2. Refresh the UG index from the newest sitemaps.
3. Match locally.
4. Fetch lyrics for new songs.
5. Fetch versions and files, within the budget.
6. Scan `Music/` for new purchases.
7. Render sheets (from step 3 of the build order).
8. Write `_todo.md` and send an ntfy summary.

A separate `tabarr-autochords` unit runs after it and only touches songs whose audio is new.

**Politeness**

- **Budget:** about 60 UG requests per run, 10–20 seconds apart at random, one at a time. LRCLIB gets one request per song, ever.
- **Cache:** keep every raw response forever.
- **On a block** (403, 429 or a challenge page):
  - stop using that provider for the rest of the run;
  - mark it cooling down for 24 hours, doubling on each repeat;
  - send one ntfy message;
  - never count the song as not found.
- **Why this matters:** UG has blocked heavier users. freetar's commit history shows a public instance hit with Cloudflare 403s in 2024, then caching added "to prevent 403s" in 2025, proxies in February 2026, and a direct mode again in September 2026. A home IP making a few dozen requests a night is a very different profile, but plan for 403s anyway.

**Packaging.** Use `python3Packages.buildPythonApplication`. Its dependencies are all in nixpkgs unstable:

- httpx 0.28.1
- selectolax 1.0.0
- rapidfuzz 3.14.5
- spotipy 2.26.0
- typer 0.25.1
- mutagen 1.48.1

The auto-chords unit adds beat-this 1.1.0 and torch. For sheets, nixpkgs ships the `chordpro` program as `perl5Packages.AppMusicChordPro` 6.050.7, which is older than upstream's 6.101 but renders PDFs and transposes.

**The NixOS module:**

```nix
{ config, lib, pkgs, ... }:
let
  cfg = config.services.tabarr;
  toml = pkgs.formats.toml { };
in {
  options.services.tabarr = {
    enable = lib.mkEnableOption "tabarr";
    package = lib.mkOption { type = lib.types.package; };
    libraryDir = lib.mkOption { type = lib.types.str; default = "/srv/tabs"; };   # str, so it is never copied to the store
    musicDir = lib.mkOption { type = lib.types.str; default = "/srv/music"; };
    schedule = lib.mkOption { type = lib.types.str; default = "*-*-* 03:30"; };
    settings = lib.mkOption { type = toml.type; default = { }; };
    credentials = lib.mkOption { type = lib.types.attrsOf lib.types.path; default = { }; };
  };

  config = lib.mkIf cfg.enable {
    users.users.tabarr = { isSystemUser = true; group = "tabarr"; };
    users.groups.tabarr = { };
    systemd.tmpfiles.rules = [ "d ${cfg.libraryDir} 2775 tabarr tabarr -" ];

    systemd.services.tabarr = {
      path = [ pkgs.perl5Packages.AppMusicChordPro ];   # `chordpro` for PDF sheets
      onFailure = [ "tabarr-notify-failure.service" ];  # a tiny curl-to-ntfy unit
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${lib.getExe cfg.package} run --config ${toml.generate "tabarr.toml" cfg.settings}";
        User = "tabarr"; Group = "tabarr";
        StateDirectory = "tabarr"; CacheDirectory = "tabarr";
        ReadWritePaths = [ cfg.libraryDir ];
        ReadOnlyPaths = [ "-${cfg.musicDir}" ];          # "-": don't fail if it doesn't exist yet
        LoadCredential = lib.mapAttrsToList (n: p: "${n}:${p}") cfg.credentials;
        NoNewPrivileges = true; ProtectSystem = "strict"; ProtectHome = true;
        PrivateTmp = true; PrivateDevices = true; ProtectProc = "invisible";
        ProtectKernelTunables = true; ProtectKernelModules = true; ProtectControlGroups = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        RestrictNamespaces = true; MemoryDenyWriteExecute = true; LockPersonality = true;
        SystemCallFilter = [ "@system-service" ]; CapabilityBoundingSet = ""; UMask = "0027";
      };
    };

    systemd.timers.tabarr = {
      wantedBy = [ "timers.target" ];
      timerConfig = { OnCalendar = cfg.schedule; Persistent = true; RandomizedDelaySec = "45m"; };
    };

    # tabarr-autochords: same user and paths, ordered after tabarr.service,
    # PrivateNetwork = true, and MemoryDenyWriteExecute left off (see below).
  };
}
```

**Hardening notes**

- With no Chromium in the process, `MemoryDenyWriteExecute` and `RestrictNamespaces` can be on. The first design had to leave both off.
- The auto-chords unit is the exception: PyTorch's CPU kernels can generate code at runtime, so leave `MemoryDenyWriteExecute` off there and set `PrivateNetwork = true` instead.

**Everything else**

- **Static secrets** (Spotify client secret, ntfy token) come from agenix or sops-nix through `LoadCredential`.
- **Mutable credentials** (the Spotify token, your UG cookies) live in the state directory, written by `tabarr auth spotify` and `tabarr auth ug --cookies cookies.txt`.
- **Backups:** restic covers `/var/lib/tabarr` (take a SQLite `.backup` first), the library and `Music/`.

## Build order

| Step | Scope | Done when |
|---|---|---|
| **0. Spike (an evening)** | (1) Your Spotify app reads Liked Songs and your Learn playlist; (2) fetch `sitemap_last` and one numbered sitemap, parse them, and find 20 of your songs locally; (3) one tab page still has `js-store` with a versions list carrying ratings and votes; (4) LRCLIB returns lyrics for 10 of your songs, half of them Spanish; (5) one Guitar Pro download with your cookies works, or you choose assisted mode | You know which parts of this plan are real |
| **1. MVP on the laptop** | Command line: `auth`, `index build` and `index refresh`, `sync`, `match --dry-run`, `run`; LRCLIB lyrics; UG sheets ranked by lyric coverage, then rating; Guitar Pro and tab parts; library and `_todo.md`; `overrides.toml`; SQLite | Every song in your Learn playlist has lyrics and a sheet with at least 80% lyric coverage, or a clear line on the to-do page |
| **2. Move to the NUC** | Flake, module, timer, agenix, ntfy, Syncthing, restic | A week of nightly runs with no intervention |
| **3. Sheets you can sing from** | ChordPro conversion (UG marks every chord with `[ch]`, so it's deterministic); PDF rendering with `chordpro`; per-song transposition from `overrides.toml`; LaCuerda for Spanish songs; a `tabarr review` TUI | Your phone shows a PDF of every sheet, in your key |
| **4. The floor** | Buy list; `Music/` scan; the auto-chords unit merging timed chords with synced lyrics | Every song you bought has at least an auto sheet |
| **Later, if needed** | Guitar Pro file introspection, MuseScore, Cifra Club, a web UI or player (It's MyTabs or TabVault), Navidrome as a source, GDPR import, Music.AI | — |

## Rules of the road

- **Discover through what UG publishes for crawlers:** the sitemaps and the pages robots.txt allows. Never call `search.php`.
- **Fetch only songs you asked for.** Cache forever, keep a small nightly budget, and make one request at a time.
- **Keep the library private.** Chord sheets and lyrics are other people's work. A personal offline copy is the closest thing to UG's personal-use terms, so keep it behind Syncthing or Tailscale and share it with no one.
- **Guitar Pro files:** downloading through the website is allowed for users, but the endpoint is disallowed for bots. Assisted mode stays inside both.
- **No paywalls:** skip Official and Pro tabs, and never use paywall tools such as dl-librescore, songsterr-downloader, TabGrabberr, or UG "Official" unlockers. Chordify and Songsterr are links only.
- **Audio for the local model comes from purchases**, not from streams.
- **On a block, back off.** Don't escalate.

None of this is legal advice.

## Sources

- Verified for this review (2026-10-18):
  - [UG robots.txt (www)](https://www.ultimate-guitar.com/robots.txt)
  - [UG robots.txt (tabs)](https://tabs.ultimate-guitar.com/robots.txt)
  - [UG sitemap index](https://www.ultimate-guitar.com/sitemap.xml)
  - [sitemap1](https://www.ultimate-guitar.com/sitemap1.xml), [sitemap40](https://www.ultimate-guitar.com/sitemap40.xml), [sitemap_last](https://www.ultimate-guitar.com/sitemap_last.xml)
  - [freetar source and commit history](https://github.com/kmille/freetar)
  - [UGDownloader source](https://github.com/jabbey1/UGDownloader) (artist pages list tabs by type, paginated)
  - [LRCLIB server source](https://github.com/tranxuanthang/lrclib) (album and duration are optional; ±2 s duration match)
  - nixpkgs unstable versions for spotipy, rapidfuzz, selectolax, httpx, typer, mutagen, beat-this and `perl5Packages.AppMusicChordPro`
- Carried over from the first report:
  - [Spotify Development Mode update](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)
  - [Spotify migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
  - [Spotify redirect URIs](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
  - [Spotify refreshing tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens)
  - [UG Help: downloading Guitar Pro files](https://help.ultimate-guitar.com/en/articles/6749046-website-can-i-download-pro-tabs)
  - [Chordify terms](https://chordify.net/pages/terms-and-conditions/)
  - [Chordify Premium](https://chordify.net/premium)
  - [Music.AI pricing](https://music.ai/pricing/)
  - [MuseScore download limits](https://intercom.help/musescore/en/articles/8535931)
  - [LaCuerda](https://acordes.lacuerda.net/joaquin_sabina/)
  - [ChordPro releases](https://github.com/ChordPro/chordpro/releases)
  - [BTC chord model](https://huggingface.co/puar-playground/btc-chord)
  - [beat_this in nixpkgs](https://github.com/NixOS/nixpkgs/blob/master/pkgs/development/python-modules/beat-this/default.nix)
