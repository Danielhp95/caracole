# caracole for Android

A small app that keeps a copy of your caracole library on the phone and shows it with no network: the library
page, every sheet in caracole's own viewer (key, capo, chord diagrams, harmony, pinyin, strum), the songbooks,
and the PDFs. It shows the pages caracole writes into the library as they are. When caracole is upgraded, the
pages change with it, and the app doesn't need an update. With the computer's indexes imported, its search finds
songs on the sites with the computer off ([below](#search-with-the-computer-off)).

It connects to `caracole serve` at the address you type, downloads what serve lists at `GET /api/offline`, and
keeps it in the app's own storage. Each file is stored once, under its SHA-256. A sync downloads only what
changed. It checks each file's size and hash, and it swaps the new list in whole, so a sync cut short leaves the
copy you had. The copy writes nothing to the computer's library; the sync's two-way take and give does, as the computer's
own request ([Sync from the phone](#sync-from-the-phone)). The app shows the copy through a caracole of its own on
the phone, a small server on 127.0.0.1 that only the app can use.

## Build

From the repository's root, with Nix:

    nix develop ./android -c gradle -p android assembleDebug

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`. `android/flake.nix` provides JDK 17, Gradle and
the Android SDK (platform 36, build tools 36.0.0) from caracole's own nixpkgs. The build uses that pinned Gradle
rather than a Gradle wrapper, which would download a second copy. The flake also points the Android Gradle
plugin at the SDK's aapt2, because NixOS can't run the copy the plugin fetches from Maven. The first build
downloads the plugin and the libraries from Google's Maven and Maven Central.

The sync engine's tests run on the JVM, against a fake caracole serve, and so do the app's own (the text size, the
settings, a file read from the phone's server for another app, an index fetched or picked):

    nix develop ./android -c gradle -p android test

## Install

1. **Install the debug APK**, which [Build](#build) made:
   - with USB or wireless debugging on: `adb install -r android/app/build/outputs/apk/debug/app-debug.apk` (`-r`
     keeps the app's data when it is already there);
   - or copy the APK to the phone and open it there. Android asks you to allow installs from that app (Files, say)
     once.
2. **Open it**: caracole, in the launcher. The first start opens Settings: type the computer's address there, tap
   **Test**, then the bar's sync button ([below](#point-it-at-caracole-serve)). Until then the library page is empty, and its
   pages say caracole, with a Phone badge beside it; the sync brings the computer's settings, among them the
   library's name when its caracole.toml gives one (`name`), which the pages then show after caracole's.
3. **The indexes**, so that its search finds the sites' songs with the computer off, come with a sync (its Site
   indexes), or from a file: Settings › **Import a file**, one made on the computer with `caracole index export
   indexes.sqlite` and copied to the phone (`adb push indexes.sqlite /sdcard/Download/`, say) ([Search with the
   computer off](#search-with-the-computer-off)).

The debug APK is signed with your machine's debug key (`~/.android/debug.keystore`). An update must be signed
with the same key.

## Point it at caracole serve

1. Run `caracole serve` where the phone can reach it, on the LAN or the tailnet:
   `caracole serve --address 0.0.0.0` (see docs/usage.md). It answers to any IP address. To use a name, add it
   with `--allow-host`.
2. On the phone, open Settings (the first start opens it). Type the address, for example
   `http://192.168.1.20:8737`. Without a scheme, `http://` is assumed. An IPv6 address goes in brackets when it
   has a port (`[fd7a:115c::1]:8737`); typed without them, the app adds them.
3. Tap **Test**. It answers "studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26", or says what went
   wrong. Then tap the bar's sync button ([below](#sync-from-the-phone)).

**Sync on Wi-Fi by itself** syncs every 6 hours on an unmetered network, leaving what changed on both sides for you
to choose ([below](#sync-from-the-phone)). First it checks that caracole answers at the address. When nothing
answers there, or something else does (another network's device, a Wi-Fi login page), it does nothing and says
nothing. The library screen's bar has the sync
button, and its menu (⋮) Library and Settings.

The sync is two-way: what you add, remove or change on the phone goes to the computer too, and the computer's pages
come to the phone with what it changed.

## Offline

What works with no network:

- The library page: filters and search over your own songs.
- Each sheet viewer: transposition, capo, mode, diagrams, the harmony panel, pinyin and strumming.
- Kept versions' pages and songbook pages.

A PDF, a ChordPro file or a Guitar Pro file opens in another app on the phone. Android asks which app when more
than one can open it, and the app says so when none can. Links to Ultimate Guitar, MuseScore and other sites
open in the browser, and so does a link to caracole serve.

What doesn't work offline: fetching sheets from the sites, Export PDF, choosing versions, and the other pages that
need caracole serve. They say they aren't on the phone yet. Use caracole serve in a browser for those.

The pages come from the app's own server, with the same Content-Security-Policy and sandbox headers caracole serve
sends, so the viewers run sandboxed as they do there.

## Text size

Pinch any page to change its text size: fingers apart make the text larger, fingers together make it smaller. The
size goes from 50% to 250%, in steps of 5%, where 100% is the size Android's own font size setting gives the pages.
Only the text grows or shrinks. The page reflows to the screen's width, so it never zooms as a picture and never
scrolls sideways. The size holds for every page and across restarts. Settings shows it ("Text size: 120%"), and
**Reset** sets it back to 100%. A sheet's own **Aa** still works, and the two multiply.

While the fingers are down, a small label near the top of the page shows the size ("135%"). At a limit it shows
the limit ("250%", "50%"), so you can see why the text stopped growing. The label fades out about a second after the
fingers lift. With Android's "Remove animations" on, it disappears without fading. A screen reader announces the
final size once, at the end of the pinch.

A touch of one finger reaches the page as before: a scroll, a tap, a swipe. A second finger makes the touch a
pinch, and the page sees none of it.

The sheet viewer keeps each chord over its syllable at any text size. Pages written by an older caracole put the
chords over the lyrics when the text is much larger. Once caracole is upgraded, its next render writes the pages
again, and the next sync brings them to the phone.

## Search with the computer off

The app runs caracole's own rules (android/core and android/server) on the phone. Its server listens on
`http://127.0.0.1:8738`, or another free port when that one is taken. The WebView loads the library page from it:
caracole's own page, built from the same files caracole serve builds it from, each of your songs' cards made from
the phone's own library as caracole serve makes it. Sheets, PDFs and songbooks are the copy's files where the phone
holds the song as the computer did, else the pages the phone makes itself.

**Only the app can use that server.** At each launch the app makes a random secret and sets it as a cookie
(`caracole-launch`) in its WebView. The server refuses any request without it ("Not this app's caracole."), so
another app on the phone can't reach it. A cookie ignores the port, so the WebView loads that exact address and
nothing else: a link to another one, another port of 127.0.0.1 included (a Termux caracole serve on 8737), opens
in the browser, and nothing a page asks for elsewhere leaves the phone. A file another app opens (a PDF, a Guitar
Pro file) is read from the server inside the app, never downloaded by Android.

**Bring the computer's indexes** to search the sites. The computer builds them (the nightly run, `caracole index
build`); the phone never asks the sites for them. A sync brings each site whose index is newer on the computer (its
Site indexes, [below](#sync-from-the-phone)), and Settings' **Import a file** takes a file made on the computer with
`caracole index export indexes.sqlite` and copied to the phone, synced as a file of the indexes alone. The phone
merges them as `caracole index merge` does: each site's newer reads win, and nothing it holds goes back. A merge
waits for a sync that runs, and a sync waits for it; a file made by another caracole's schema is refused in the
merge's words ("the file was exported at schema version 14…": export it again with the computer's caracole).

Then the library page's search works with the computer off: your songs, and the songs of Ultimate Guitar,
LaCuerda, gtptabs.com, MuseScore, harptabs.com and gametabs.net as the indexes list them, "Did you mean", and an
artist's songs. LaCuerda's own search and YouTube's suggestions need the computer.

## Sync from the phone

The bar's **sync** button (two circular arrows, left of ⋮) opens the library page's sync sheet, from any page: the
phone and the computer at the address in Settings compared, and each takes what the other changed, as `caracole peer
sync` syncs two computers. It is the sheet caracole serve's Sync tab opens, written once in library_assets; the
phone's library page has no Sync tab.

1. **What to sync**: Library (your songs, their sheets and pages, both ways), Songbooks and Site indexes (for
   searching offline), all three ticked, each with what is waiting ("3 changed on the computer"). A song a songbook
   lists comes along with the songbooks, even with Library unticked. **Cancel** on the left, **Sync** on the right.
2. **A card for each conflict**, a song (or a songbook, a removal…) changed on both sides since the two last agreed:
   its name, "1 of N", the phone on the left and the computer on the right, a line for each way the two differ (its
   own key, its sheet, its versions, its kept files…). Under "Which version to keep", **Phone** or **Computer**, and
   **Same for the other N**. Above the card, what is to take (↓), to give (↑) and changed on both (⚠). There is no
   Skip: Cancel ends the sync with nothing taken or given.
3. **The sync** runs in the background, with a notification ("Syncing with <the computer's name>…") that keeps the
   app working while you leave it, gone once it ends:
   1. compared again, refused if either side changed since you compared (compare again then);
   2. a backup of the phone's library (`state/backups/`, the last three kept), then what the computer changed taken,
      each file checked by its SHA-256;
   3. what the phone changed given to the computer (`POST /peer/push`), which takes it as its own request and
      renders its pages;
   4. the computer's pages copied (skipped with Library unticked);
   5. what the two agree on recorded, so the next comparison lists only what changes after;
   6. the computer's newer indexes merged (skipped with Site indexes unticked, or when none is newer).
4. **The summary**: "Synced with: <name>" and when, then a section for each kind of change, each closed at first:
   the songs taken, the songs given (and why), the conflicts (which side was kept), the songbooks, the indexes (each
   site's tabs before → after). **Done** closes it.

A sync already on its way when the page loads (a reload, a notification's tap) is followed to its summary, never
started again.

**Export and Import a file**, in Settings, open the sheet at the export or the import.

- **Export**: "Export this library", its name, songs and date; Library and Songbooks ticked, Site indexes not, each
  with its size. The file, `<library name>-dd-mm-yy.caracole`, goes to Android's share sheet: send it, or save it
  to Files. The app reads it from its own server in its own process (the launch's cookie and all, never Android's
  DownloadManager) and shares a copy from its cache.
- **Import a file**: the sheet's Choose a file opens Android's file picker (a page can't open it without a tap of its
  own). A file another caracole exported, a phone's or a computer's, or an index from `caracole index export`, is
  synced as if its caracole were here: the same cards, **File** in the computer's place, a part the file doesn't
  hold greyed ("Not in this file"), and nothing goes back (a file takes nothing). Refused: this library's own
  export, and a file no newer than the last sync with its caracole ("Nothing in this file is newer than your sync
  with studio on 03/11/26").

**Sync on Wi-Fi by itself** (Settings) is this sync, unattended: every 6 hours on an unmetered network, the three
parts, every change made on one side taken or given, and each conflict left as it is on both sides, for the next
sync you start. First it reads the computer's state at the address in Settings; when nothing answers there, or
something else does (another network's device, a Wi-Fi login page), it does nothing and says nothing. While it runs,
the bar's line says so ("Syncing with the computer…"), and at its end what it did for a few seconds ("Up to date: 1
taken, 2 given"; "2 changed on both sides: tap Sync to choose"; or why it failed, a stage that failed among it, such
as the copy of the computer's pages). When it left conflicts, a notification on its own channel, Syncs, says so ("2
songs changed on both sides: tap to choose"), and its tap opens the sheet, whose cards ask; the next one that leaves
none takes it back. A sync with the computer already on its way (one from the sheet) is left to finish, and this one
does nothing.

The computer needs a caracole that syncs with the phone (sync format 3: `GET /api/peer/state` answers
`"format": 3`, with `POST /peer/push` and `GET /api/peer/index`). An older one is refused as the two are compared,
with the reason; upgrade caracole there.

**Your changes on the phone.** A song you add on the phone (a search row's Get it, or the request form) is in your
library at once, and the computer's next run fetches it after a sync gives it there: the phone asks no site. Its
line says "Added: the computer's next run fetches it." A song you remove on the phone leaves the library page at
once, and its pages answer "This song was removed on the phone." until a sync settles it: given to the computer,
which removes it too, or taken back from it. A song the phone holds otherwise than the computer did when it made its
pages answers "This song changed on the phone since the computer made its page.", with a link to the phone's own
sheet when it has one. A sync settles that too: the computer renders the song again as it takes the change, and the
same sync then copies its new pages.

## caracole itself on the phone (experimental)

The app above copies a computer's library. To search, add songs and fetch them with the computer off, the phone
runs caracole itself, in [Termux](https://termux.dev): the same caracole, its ChordPro and its fonts, with every
feature but auto-chords and YouTube (no torch on a phone) and the nightly run (the computer keeps that). Nobody has
run it on a phone yet: the steps below were worked out from the packages, and `android/termux/setup.sh` stops at the
first one that fails and says what to send.

1. **Install Termux and Termux:Boot**, both from F-Droid or both from their GitHub releases, never one of them from
   Google Play: the Play builds can't run each other's scripts. Open Termux once. In Android's settings, give it
   unrestricted battery use.
2. **Let it build.** pip compiles rapidfuzz, selectolax and opencc on the phone, and Android 12 and later kills a
   process tree of more than 32. On Android 14 and later: Developer options → **Disable child process
   restrictions**. On 12 and 13, from a computer with USB debugging:
   `adb shell device_config put activity_manager max_phantom_processes 2147483647`.
3. **Get the script and caracole.** Either from GitHub:

       pkg install -y curl
       curl -fsSLO https://raw.githubusercontent.com/Danielhp95/caracole/main/android/termux/setup.sh

   or copy `setup.sh` and a tarball of the repository (`git archive --prefix=caracole/ -o caracole.tar.gz HEAD`)
   to the phone's Downloads, then `termux-setup-storage` and `cp ~/storage/downloads/setup.sh
   ~/storage/downloads/caracole.tar.gz ~`.
4. **Run it**, with the phone charging, on Wi-Fi, with 2 GB free. It takes a while (the builds are the long part):

       termux-wake-lock
       sh setup.sh ~/caracole.tar.gz      # or no argument: caracole from GitHub's main

   Its steps: `tools` (Termux's packages), `python` (caracole and its dependencies, the versions of
   [deploy.md](../docs/deploy.md)'s constraints), `chordpro` (ChordPro 6.050.7 from CPAN), `fonts` (the PDFs'
   fonts and alphaTab), `wrapper` (`~/.caracole/bin/caracole`), `check` (a PDF, and `caracole serve` answering),
   `service`. Everything goes in `~/.caracole`, the log in `~/caracole-setup.log`. One that fails stops it: send
   the log, and once it is fixed, `sh setup.sh --step NAME ~/caracole.tar.gz` goes on from there.
5. **Start it.** Close Termux, open it again, then `sv-enable caracole`: `caracole serve` runs on
   `http://127.0.0.1:8737`, and again after every boot (Termux:Boot). Open that address in the phone's browser.
   `sv down caracole` stops it, `sv up caracole` starts it again.
6. **Bring the site indexes from the computer**, never `caracole index build` on the phone (days of requests): on
   the computer `caracole index export indexes.sqlite`, copy the file over, then on the phone `caracole index
   merge indexes.sqlite`.
7. **Sync with the computer**: `caracole peer sync http://COMPUTER:8737` on the phone (docs/usage.md, "Two
   caracoles"). For the computer to take the phone's changes too, the phone's server must listen where the computer
   reaches it: `echo 0.0.0.0 > ~/.caracole/address && sv restart caracole` (or the phone's tailnet address in
   place of 0.0.0.0) for the sync, and `rm ~/.caracole/address && sv restart caracole` after.

The library is at `~/Tabs`, in Termux's own storage: not in shared storage, which keeps no file modes. caracole
serve has no sign-in, so any app on the phone can use it on 127.0.0.1.

## Try it on an emulator

`nix develop ./android#emulator` adds the emulator, `adb`, `avdmanager` and an Android 36 x86_64 image:

    avdmanager create avd -n caracole -k "system-images;android-36;google_apis;x86_64" -d pixel_6
    ANDROID_AVD_HOME=~/.config/.android/avd QT_QPA_PLATFORM=xcb LD_LIBRARY_PATH=/run/opengl-driver/lib \
        emulator -avd caracole -gpu host -no-snapshot-save

`ANDROID_AVD_HOME` is where avdmanager made the AVD (the emulator looks in `~/.android/avd` otherwise);
`QT_QPA_PLATFORM=xcb` runs its window through XWayland on a Wayland desktop.

To try the app by hand there, install it as on a phone
(`adb install -r android/app/build/outputs/apk/debug/app-debug.apk`), start it
(`adb shell am start -n io.github.danielhp95.caracole/.MainActivity`, or from the emulator's launcher), and point it
at a computer of its own: `nix develop -c python -m tests.helpers.e2e_library serve DIR PORT --address 127.0.0.1`
builds a library of 20 songs in DIR with no request and serves it on the host's loopback alone (caracole serve has
no sign-in: never on the LAN for a test), which the emulator reaches at `http://10.0.2.2:PORT`. Its
bar's sync button then brings that computer's indexes with the rest, and Settings' Import a file a file pushed to the
emulator's Download folder (`adb push indexes.sqlite /sdcard/Download/`). `adb shell pm clear
io.github.danielhp95.caracole` starts it over, as new. Never PORT 8737 on a machine whose caracole-web listens there.

Use `-gpu host`. With the software renderers (`swiftshader_indirect`, and the lavapipe fallback of `-gpu guest`),
emulators 37.1 and 37.2 crashed in their own render thread when the WebView went back a page. On the emulator,
the host's `127.0.0.1` is `10.0.2.2`. The instrumented tests sync from a running caracole serve. EndToEndTest opens
the library page and a viewer, transposes, and hands off a PDF and a Guitar Pro file. PinchTest pinches the library
page and a sheet, larger and smaller, and checks the size label and that the chords stay over their syllables.
LocalServerTest needs no computer: the app's server answers its page only with the launch's cookie, the WebView
never loads another loopback port, and a first start's database is made whole. SyncSheetTest opens the sheet with
the bar's sync button and syncs a song changed on both sides, the computer's version kept, then finds nothing that
differs; and opens it from the notification of a Sync on Wi-Fi that left such a conflict. ExportImportTest exports
from Settings to the share sheet, and imports a file through the picker. They change the computer's library (one
song's own version), so give them a computer of their own, such as `nix develop -c python -m tests.helpers.e2e_library
serve DIR PORT --address 127.0.0.1`:

    nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest
    adb install -r -t android/app/build/outputs/apk/debug/app-debug.apk
    adb install -r -t android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
    adb shell am instrument -w -e server http://10.0.2.2:PORT \
        io.github.danielhp95.caracole.test/io.github.danielhp95.caracole.CaracoleTestRunner

Add `-e class io.github.danielhp95.caracole.PinchTest` to run one of them. The runner, `CaracoleTestRunner`, lets the
app send no request to a site: every test's sites refuse, unless the test names the fake sites server.

`android/scripts/device-test.sh` does all of it, one caller an emulator at a time (it builds first, then takes the
first free emulator of its pool, `CARACOLE_EMULATORS`, 3 by default: emulator-5554, -5556 and -5558, holding its lock,
`${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}` for the first and the same name with the
port for the others), starting that emulator if it isn't up (each read-only, so several run on the one AVD) and leaving it up:

    android/scripts/device-test.sh --area unicode,keys    # CorpusOnDeviceTest's areas (none named: every one)
    android/scripts/device-test.sh --app                  # EndToEndTest, PinchTest, SyncSheetTest, ExportImportTest,
                                                          # PhoneEndToEndTest, each against a computer of its own
    android/scripts/device-test.sh LocalServerTest NoSitesTest SyncSheetTest=/tmp/lib   # classes, one a computer

## Lookups on the phone

The library page's lookups ask the sites from the phone itself, as `caracole get` does on the computer, with the
computer off:

- **Get it** on a search's line, and **Fetch now** on the request form, look the song up now: the song you have, or a
  new one, which the lookup adds. A pick on the line (an Ultimate Guitar song or tab, a LaCuerda song, a harptabs.com
  or gametabs.net tab) is the one it asks for. **Add** with a LaCuerda song picked records the pick for the song, as
  `caracole add --lacuerda` does, for the next lookup or the computer's nightly run once synced.
- **Fetch now** on a song's card looks up a song you have, unless it is ignored or caracole isn't sure which Ultimate
  Guitar song it is (review it first).
- An artist's **Songs** reads their page on LaCuerda or harptabs.com, and **Fetch them** keeps more of a song's
  Ultimate Guitar versions.
- **LaCuerda's own search** goes as on the computer: once a query has settled, by the page itself while its gate
  allows, or with Ask LaCuerda, never twice for a query, at most 20 an hour by the page alone.

Each is a request of the Requests tab, one at a time behind any other, its line on the song's card saying how it goes
in caracole serve's words. A form posted without the page's script goes to that request's line in the Requests tab.
The phone keeps the computer's politeness, at the lookup pace (a few requests a song, 60 an hour to a site), with its
own counts, cooldowns and cache: two caracoles at one address may together send more than either one's limits. A
site that refuses or fails is never a miss: the song is added, its stage says what went wrong, its line says "Not
fetched yet", and the next lookup or the computer's nightly run, once synced, tries again. The sites' answers are kept for ever under the app's files
(`state/cache/http/`), never in a cache Android may clear.

While a lookup runs, the app stays in the foreground, with a notification naming the song and what the lookup does
now ("Estopa - Tu calorro: …"), gone once nothing waits or runs. Lookups use mobile data too.

On the emulator, LookupOfflineTest looks a song up with every site refusing, as with no network (the song added, its
stages failed, the notification while it runs), and NoNetworkTest checks that with no sites set a lookup opens no
socket: `android/scripts/device-test.sh --area lookup_routes LookupOfflineTest NoNetworkTest`.

## Picking an uncertain match

A song caracole isn't sure of (several Ultimate Guitar songs could be it) is settled on the phone as in caracole
serve: **Pick the match** on its card, on its line in the Requests tab, or a not-found song's **Look in the index**
(what the offline index finds for its artist and title) lists the candidates, each with why the matcher thought of it,
its score, its tabs and its Ultimate Guitar page. A pick goes into the phone's overrides under `[match]` (and
`[alias]` when the artist is spelled otherwise there), **None of these** under `[reject]`, and the song's match is
decided again at once, with its artist's other songs after an alias. **Fetch it now** (ticked) then looks the song up,
as Fetch now does. While a request of the song's waits or runs, a pick is refused until it ends. A sync takes the
answer to the computer, as it takes any of the phone's overrides.

## Performance notes

**The WAL after an import.** An import (a sync's newer indexes, or Settings' Import a file of them) merges the computer's
indexes in a few big transactions, and SQLite's WAL grows with them: on the owner's phone it was left at 387 MB, and
the first search after the import, or after a start, took more than 30 s while every search waited behind it. A WAL
SQLite has copied back stays on disk at its largest unless told otherwise, every read before the next checkpoint
goes through its index, and a start after Android stopped the app reads the whole file again to rebuild that index.
Now:

- every connection keeps `PRAGMA journal_size_limit` at 16 MiB (`Database.JOURNAL_SIZE_LIMIT`), so a WAL SQLite
  restarts is cut down to that;
- the import and the sync's index stage end with `Database.checkpoint()` on the writer: `PRAGMA
  wal_checkpoint(PASSIVE)` first, which copies the frames back while searches go on, then `TRUNCATE` with every
  reader taken, which has little left to copy and leaves no WAL at all;
- opening a database whose WAL is over the limit (a phone killed before its checkpoint) checkpoints it first;
- a merge that changed many of UG's rows (`Warmup.OPTIMIZE_AFTER`, 100,000 rows written, its triggers' included: an
  import, never a sync's nightly few, which FTS5's own merging keeps) makes each of UG's three full-text indexes one
  segment (`'optimize'`, a fraction of a second for 300,000 rows);
- the app's start runs one search in the background (`Database.warmUp`), so that the code, the data it loads lazily
  and the pages a search reads are ready before the owner's first search; a search that comes meanwhile runs beside
  it;
- the words of UG's keys a search kept are read again, whole, after an import added more than 1,000 of them
  (`Vocabulary.REREAD`), rather than added one at a time to lists of tens of thousands.

**Measured** (`ColdSearch`: a synthetic index of 300,000 ug_index rows, 70,687 words of their keys, imported, the
phone killed with it open, started again, its warm-up, then a misspelt query that looks for close spellings too).
"Before" is the same run over the same index with the fixes off (`ColdSearch(fixed = false)`: no journal size limit,
no checkpoint after the import or as the database opens, no optimize, no warm-up; Vocabulary's re-read, which it
can't turn off, is in both), each in a process of its own, as a start is:

| Emulator (Android 36, x86_64) | Before | After | What moved it |
|---|---|---|---|
| The WAL the import left | 72.7 MiB | 0 | the import's checkpoint (without it, the journal size limit: 16 MiB) |
| The import: merge, then checkpoint | 5.5 s | 5.5 s, the checkpoint 3 ms | nothing (the optimize is under 0.1 s of it) |
| A start: the database opened, and the WAL it finds | 3 ms, 72.7 MiB | 3 ms, none | the import's checkpoint (killed before it: the one at open) |
| The first search's steps in a new process, cold | 133 ms | 116 ms | nothing: the same steps (your songs 32 to 42 ms, MuseScore 44 ms, the close spellings 25 to 29 ms), which the warm-up now pays as the app starts |
| The first /api/search after a start, and a warm one | 21 ms, 14 ms | 20 ms after a 22 ms warm-up, 12 ms | nothing beyond the emulator's noise |
| The first search after an import while the app runs, and a warm one | 18 ms, 10 ms | 12 ms, 8 ms | a few ms, near the noise: the optimize's one segment each |

ColdSearch runs the cold steps first, so the start after them finds the code loaded: the first search after it, and
the warm-up's 22 ms, are the database's alone. On the JVM (`gradle bench`) the import's WAL is the same, 72.7 MiB
before and 0 after, and CheckpointBench's merge of 200,000 rows alone leaves 16 MiB (the limit), which its checkpoint
gives back (PASSIVE 10 ms, then TRUNCATE 2 ms); its search times are left out, within the noise of a machine other
builds share.

Neither the emulator nor the JVM shows the phone's 30 s: over an index in the page cache the first search's own steps
take about 0.13 s cold on the emulator (`ColdSearch.Result.steps`), which the warm-up now pays. What was cold on the
phone is what a big WAL costs on its storage: the rebuild of the WAL's index from a 387 MB file at a start, and reads
through it until a checkpoint, which the import's checkpoint now leaves none of. The owner's phone's numbers are the
M4 check's to take.

Run them with `nix develop ./android -c gradle -p android bench` (CheckpointBench, ColdSearchBench, its two runs each
in a JVM of its own, and MergeSpeedBench) and `android/scripts/device-test.sh
'ColdSearchTest#asThePhoneRanBeforeTheFixes' 'ColdSearchTest#theFirstSearchAfterAStartAnswersAsAWarmOneDoes'` (each in
a process of its own; `ColdSearchTest` alone runs both in one); `Timings` (core.db, behind `-Dcaracole.timings=1`,
never in a page) times each step.

## Pages built on the phone

The phone makes a song's pages itself, as the computer's render does them but with no PDF, whenever the computer's
pages in the copy aren't of the song as the phone holds it: a song added or looked up on the phone, or changed there
since the last sync. The song's sheet page (`sheet.html`, and an auto sheet's beside it), the page of each version kept
beside the sheet (`version-<tab>.html`) and of each harmonica tab (`harmonica-N.html`), with the sheet's `.cho` and its
`info.json`, go into the song's folder in the app's library, each written only when its bytes change; a version's or a
tab's page goes once the song keeps it no longer. An auto sheet made before its song had lyrics takes them first, as
the computer's render does. No page links a PDF: the phone makes none.

For every song, those the computer's pages serve too, the phone records what the library page finds it by: the
progressions its sheet plays and whether its words are Chinese.

A lookup makes its song's pages as it ends ("its pages made; this caracole makes no PDF"). After a sync that changed
songs, and when the app starts as a new build (any APK whose code or tables differ, whatever its version says), the
phone makes the pages it owes in the background, a request of the Requests tab ("Make the pages again"), which lets a
lookup asked for meanwhile go first, between two songs. A song whose pages can't be made says why on that request, and
costs the other songs nothing; it is tried again once the song changes or a new build is installed.

On the emulator: `android/scripts/device-test.sh --area render`.

## Songbooks, versions and printing

The Songbooks tab's forms and the Select bar's songbook are the phone's own, as `caracole songbook` is on the
computer: **Make** a songbook of the songs picked, **Add** to it (a song you have at once; one new to the library, from
the tab's search, looked up first, the two queued together or not at all), **Move** a song, **Take it out**,
**Rename** and **Delete** a songbook. Each is a request of the Requests tab, one at a time behind any other, its line
saying how it goes ("Making the songbook…", then "Made"); a form that can't be done (a name taken, a songbook or a
song that isn't there, a song of the computer the phone hasn't got) is refused at once, in caracole serve's words, and
queues nothing. The songbooks are the phone's (`phone_songbooks`), which a sync gives the computer.

- **A song's chip** sets where the songbook plays it, as on the computer: its key, mode, capo and instrument, or **Its
  own version**; a key or a mode alone keeps the capo it plays at now, and another instrument the pitch it plays at.
- **Get the missing songs** looks up each song of the songbook the phone has no sheet of (one a sync brought plays from
  the computer's sheet, and is never asked for), as many as the queue has room for, then makes the songbook again; a
  set list's **Get it**, that song alone.
- **Phone page**: the phone makes each songbook's page itself (`_songbooks/<name>/songbook.html`), from the sheets it
  plays, after every change; the PDF and the ChordPro file are the computer's (chordpro), so the phone links neither.
  A page that can't be made fails its request ("Making the songbook failed."), the change itself made.

**A sheet's versions.** A sheet the phone made lists its other Ultimate Guitar versions under its key line, as on the
computer. **Make this the one**, **Keep it** and **Back to caracole's pick** open a page of the phone's own that says
what the version is and what the song's sheet is now, with the one button that does it. Its request then shows on
that page until it is over (the page reloads every ten seconds), and in the Requests tab: Make this the one looks the
song up with that tab and keeps your choice in overrides; Keep it reads the version's page from Ultimate Guitar, at a
lookup's pace, and keeps it beside the sheet; Back to caracole's pick takes your choice out and looks the song up
again. A page the computer made and the phone copied names no version of the phone's: choose there on the computer.

**A harmonica tab's readings.** A harmonica tab's page links its Read as line (or, at its foot, **Change how it's
read**) to the readings caracole weighs, best first, each with its Q and a button that pins it (harptabs.com's own
notation among them), and Back to caracole's guess for a tab you pinned. The tab's page is made again with your
reading.

### Export PDF

**Export PDF** in a sheet's settings prints the sheet as the viewer shows it, in its version (key, capo, mode, the
shapes and swaps you chose, the instrument): Android's print dialog opens on an A4 page, for a printer or **Save as
PDF**, the file named as caracole serve names its download ("Soda Stereo - De Música Ligera (A Major, capo 0).pdf").
Nothing is written into the library. The phone makes no PDF of its own: the page you see is what prints, in the
viewer's print style (a light page, the margins).

- **Download and make it mine** (the viewer asks when the version's music isn't the song's own) prints it and makes
  it your version too, as on the computer: the song's `[version]`, kept by the key it plays in, so its viewer and its
  songbooks start there (a song whose pages were the computer's copy gets pages the phone makes, at once). The
  Requests tab shows it ("Your version now"). Like caracole serve's, it is a plain link with no form token, the one
  write the phone takes so.
- The phone names the version of a sheet of its own library: one it made the pages of, or one of the computer's
  pages whose song a sync brought (the Sync tab). A copy of the computer's pages with no song of its own (Sync now's
  pages alone) has no sheet to name, and says so. The auto-chords sheet kept beside a song's own sheet, and a kept
  version's page, offer no export of their own, as on the computer.

## Guitar Pro

A song's Guitar Pro file (filed from the inbox or downloaded from gtptabs.com) opens on a page of its own in the app,
as it does in caracole serve: the score drawn by alphaTab and played by its synthesizer (Play, Stop, Tempo), Tab only
or Score and tab, each track shown or muted. **Download** gives the file to another app. A Power Tab file is a
download alone.

alphaTab (MPL-2.0), its Bravura music font (SIL OFL 1.1) and the Sonivox SoundFont (Apache-2.0) are in the app, their
licences beside them in its assets (`alphatab/licenses/`): nothing is downloaded. A Guitar Pro file of a song only the
copy of the computer's pages has (not in the phone's own library yet) opens in another app instead, as before.

Building the app needs `CARACOLE_ALPHATAB_DIR` (alphaTab's files, nix/alphatab.nix), which `nix develop ./android`
sets; without it the build stops and says so.

## Sharing a song from a music app

In a music app, **Share** a song and pick **caracole** in Android's share sheet: caracole opens on a page of its own
for that song.

1. **What it read**: "caracole read Queen – Bohemian Rhapsody." It reads the artist and the title from the text the
   app shared, the way caracole reads what you type in a search box, with no request. "What Spotify sent" shows the
   text as it came. When the app shared a link alone, caracole asks its service once what the link names (below):
   "Read from Spotify's page: Queen – Bohemian Rhapsody."
2. **The best match**: the song the phone's search finds for those names, in your library or in the indexes, with
   what each site has of it ("Ultimate Guitar: chords ×12 · tabs ×3 · LaCuerda ×2"), and "In your library" when the
   song is yours. Up to three other songs the search found come under it, each with its own Get it.
3. **Your choice**:
   - **Get it** looks the song up now, like a search line's Get it, and the Requests tab shows how the lookup goes.
   - **Open** shows your song, when the library has it.
   - **Edit** takes the artist and the title as you type them, then searches again.
   - **Cancel** takes you back to the app you shared from.

Nothing is sent to a tab site until you tap Get it. With no index imported, the page says so, and Get it still looks
the song up by its names.

What each app shares (tests/fixtures/share/shares.jsonl lists them, each with where it was found):

- **Names in the text**, read as they come: Deezer ("I've found a song for you... Hotel California by Eagles 🔥
  Listen now on #Deezer"), Shazam ("I used Shazam to discover … by …"), SoundCloud ("Listen to … by … on
  #SoundCloud"), SoundHound, Musixmatch, YouTube (its subject, the video's title), Audile ("Hotel California -
  Eagles", title first), and Ultrasonic with Share on server off (its "Title:" and "Artist:" lines, in any of its
  languages).
- **A link alone**: Spotify, Apple Music, TIDAL and YouTube Music, as far as anyone has written down what they
  send; Navic, DSub and Ultrasonic's server shares send a link to your Navidrome or Subsonic server. Tempo copies its
  share's link instead of sharing it. Symfonium's text isn't known yet: share from it once and read the log (below).
- Any other app's text is read as you'd type it in the search box, less its links and the app's name at its end
  ("… | Spotify").

**A link alone** of Apple Music, Spotify, TIDAL, YouTube or YouTube Music is read by asking its service once, at a
lookup's pace, with caracole's own user agent:

| Link | Asked | Requests |
|---|---|---|
| Apple Music, a song (`music.apple.com/us/album/…?i=…`, `/song/…`) | Apple's catalogue, `itunes.apple.com/lookup` | 1 |
| Spotify, a track (`open.spotify.com/track/…`) | the track's page | 1 |
| Spotify's short link (`spotify.link/…`) | the link, then the track's page | 2 |
| TIDAL, a track (`tidal.com/track/…`, `/browse/track/…`) | the track's page, `tidal.com/track/…` | 1 |
| TIDAL's short link (`tidal.link/…`) | the link, then the track's page | 2 |
| YouTube, YouTube Music (`watch?v=`, `youtu.be`, `shorts`) | YouTube's oEmbed: the video's title and channel | 1 |

The page then says "Read from Spotify's page: Queen – Bohemian Rhapsody", and goes on as for a text that named the
song. A link to an album (Apple Music's with no `?i=`), a playlist, an artist or a channel names no song: the page says
which, with no request. When the service fails, blocks caracole or is turned off, the page says so in one line and
opens Edit. A link shared again is read from the cache, with no request. Each service is turned off on the computer,
`[providers.spotify] enabled = false` (or `itunes`, `tidal`, `youtube-oembed`) in caracole.toml, which the phone takes
at its next sync. Deezer's shares carry the song's names; a Navidrome or Subsonic link is never asked.

**To see what an app sends**, connect the phone with adb and run `adb logcat -s caracole-share` while you share.
Each share is one line: the sending app's package (when Android gives it), and the text, the subject and the title
as they came.

## Sharing files to caracole

A Guitar Pro file (`.gp3`, `.gp4`, `.gp5`, `.gpx`, `.gp`, or a Power Tab `.ptb`) or a score (`.mscz`, `.mxl`,
`.musicxml`, `.pdf`, `.mid`, `.midi`) you have on the phone, in a file manager, your browser's downloads or a chat:
**Share** it and pick **caracole**. Share several at once if you like.

caracole files each one as the computer files what you drop into `_inbox/`:

- **For the song its name is of**: "Oasis - Wonderwall.gp5", "Oasis - Wonderwall (ver 2).gp5", or "wonderwall.gp5"
  when one song of your library has that title. It is kept as the song's `guitar-1.gp5` (or the next number free) or
  `score-1.pdf`, never over a file the song keeps, and goes to the computer as the song's at the next sync.
- **A file caracole keeps already** (the same bytes, under any name) is nothing new: "Filed as guitar-1.gp5 of …".
  One the library lost (deleted on another device) is put back where it was.
- **A file no song fits waits**, up to 30 days, and is tried again after each sync and each lookup: share a Guitar
  Pro file first and look its song up after, and it is filed then. One that couldn't be filed (its song's folder is
  another song's too, the phone is full) waits too, tried again after the next sync, or a day later.
- **The bytes of a file caracole keeps whose copy you changed since** are not filed: "Not filed: … whose place holds
  other bytes now, and nothing is replaced". caracole replaces nothing of yours; the file is put back once that place
  is free.
- A score is placed by its name alone on the phone: a MusicXML file named "score.musicxml" waits, where the computer
  would read the title and composer inside it.

A toast says how each went, as its line on the Requests tab does: "Filed as guitar-1.gp5 of Oasis - Wonderwall",
"Waiting for a song that fits: Somebody - Unknown Song.gp5", or "Not filed: …" (a file of another kind, say: caracole keeps
Guitar Pro files and scores alone). A file shared with no extension takes the one its bytes or its type tell.

caracole is offered for files: never to open a PDF (Android's Open with), and never for a text (a music app's song,
above, is another share). A share of several kinds of file at once (a PDF with a photo, say) offers caracole too, as
Android offers it every app that takes any of them: a file caracole keeps nothing of is answered "Not filed". caracole
reads a file only from the app that shares it, never a `file:` address another app names.

## Alerts and backups

**Alerts** are notifications on their own channel, Alerts (Android's settings for the app list it beside "Work in the
background"; the app asks for the right to notify once, as the library screen opens):

- **a site that blocked a lookup**: "caracole: LRCLIB blocked", with when its cooldown ends. One a cooldown: a lookup
  that meets the same cooldown again says nothing more, and the lookups after it ask that site nothing until the
  cooldown is over. On the computer a lookup sends no alert (the nightly run does); the phone has no nightly run to
  tell, so its lookups do.
- **a request that failed while the app was in the background** (no screen of the app's open): its name and the line
  the Requests tab shows for it. One that fails while you are in the app says so there alone.

Tapping one opens the library.

**Backups** are in Settings, Open the backups: each backup is a copy of the phone's library, its songs, their versions,
the songbooks, the picks and overrides made on the phone, and the files it keeps (sheets, tabs, Guitar Pro files), each
file once however many backups hold it. The indexes aren't backed up: they come again from the computer.

- **Back up now** makes one by hand. One is also made every day while the phone is idle and its battery isn't low, and
  one before each sync takes anything from the computer. Three of each kind are kept, the oldest going as a new one is
  made; none is made without twice the room it needs (the Requests tab then says "Not backed up: there isn't room for
  it on the phone").
- **Export…** saves one as a single `.zip` (`caracole-by-hand-2026-11-10T081400Z.zip`: the copy, a SQLite database,
  and `blobs/<sha256>`, each file it keeps) wherever you pick, on the phone or in a cloud app's folder. It is a copy
  kept outside the phone: the phone can't restore from an exported file yet, only from the backups it lists.
- **Restore…** (asked first) puts the library back as that backup has it: the songs, versions, songbooks and files
  changed or added since are gone from the phone. What the phone has learnt of the sites since stays as it is now: each
  site's cooldown, the pace, which searches it asked and which songs it checked, the computer's settings, and what it
  agreed with the computer at the last sync. So the next sync gives the restored library to the computer as the
  phone's own change: whatever the restore changed of what the two agreed on at the last sync is given to the
  computer, and a song that sync agreed on that the backup doesn't hold is given as removed, so the computer removes
  it too (one the computer changed since is a conflict, yours to choose). The phone's pages are made again after it;
  until then its pages of what the restore changed aren't served.
- A backup that doesn't hold every file it names (one made before a sync by an older app, which kept the tables
  alone, or one made while a file was no longer its bytes) says how many in the list ("2 of its files not kept"). It
  restores only while the phone's files still hold those bytes, and can't be exported; otherwise its Restore says why
  and changes nothing.

A backup, its daily one and a restore are requests like a lookup, one at a time on the Requests tab ("Backed up
(by-hand)", "Restored the library of 2026-11-10 09:14"), never run beside a lookup.
