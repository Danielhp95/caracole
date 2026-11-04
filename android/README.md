# caracole for Android

A small app that keeps a copy of your caracole library on the phone and shows it with no network: the library
page, every sheet in caracole's own viewer (key, capo, chord diagrams, harmony, pinyin, strum), the songbooks,
and the PDFs. It shows the pages caracole writes into the library as they are. When caracole is upgraded, the
pages change with it, and the app doesn't need an update. With the computer's indexes imported, its search finds
songs on the sites with the computer off ([below](#search-with-the-computer-off)).

It connects to `caracole serve` at the address you type, downloads what serve lists at `GET /api/offline`, and
keeps it in the app's own storage. Each file is stored once, under its SHA-256. A sync downloads only what
changed. It checks each file's size and hash, and it swaps the new list in whole, so a sync cut short leaves the
copy you had. The copy writes nothing to the computer's library; the Sync tab's two-way sync does, as the computer's
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
   **Test**, then **Sync now** ([below](#point-it-at-caracole-serve)). Until then the library page is empty, and its
   pages say caracole, with a Phone badge beside it; the sync brings the computer's settings, among them the
   library's name when its caracole.toml gives one (`name`), which the pages then show after caracole's.
3. **Import the indexes**, so that its search finds the sites' songs with the computer off: Settings › Import
   indexes › **From the computer** (caracole serve at that address), or **From a file**, one made on the computer
   with `caracole index export indexes.sqlite` and copied to the phone (`adb push indexes.sqlite /sdcard/Download/`,
   say). It runs in the background and Settings says how it ended ([Search with the computer
   off](#search-with-the-computer-off)).

The debug APK is signed with your machine's debug key (`~/.android/debug.keystore`). An update must be signed
with the same key.

## Point it at caracole serve

1. Run `caracole serve` where the phone can reach it, on the LAN or the tailnet:
   `caracole serve --address 0.0.0.0` (see docs/usage.md). It answers to any IP address. To use a name, add it
   with `--allow-host`.
2. On the phone, open Settings (the first start opens it). Type the address, for example
   `http://192.168.1.20:8737`. Without a scheme, `http://` is assumed. An IPv6 address goes in brackets when it
   has a port (`[fd7a:115c::1]:8737`); typed without them, the app adds them.
3. Tap **Test**. It answers "caracole answered: 312 files, 41 MB", or says what went wrong. Then tap **Sync now**.

**Sync on Wi-Fi by itself** syncs every 6 hours on an unmetered network. First it checks that caracole answers
at the address. When nothing answers there, or something else does (another network's device, a Wi-Fi login
page), it does nothing and keeps the last sync's outcome; **Sync now** says what answered. The library screen's
menu (⋮) has Sync now, Sync with the computer ([below](#sync-from-the-phone)), Library and Settings.

Sync now copies the computer's pages, one way. Sync with the computer, the library page's Sync tab, is the two-way
sync: what you add, remove or change on the phone goes to the computer too.

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
caracole's own page, built from the same files caracole serve builds it from, with your songs' cards taken from the
copy. Sheets, PDFs and songbooks are the copy's files.

**Only the app can use that server.** At each launch the app makes a random secret and sets it as a cookie
(`caracole-launch`) in its WebView. The server refuses any request without it ("Not this app's caracole."), so
another app on the phone can't reach it. A cookie ignores the port, so the WebView loads that exact address and
nothing else: a link to another one, another port of 127.0.0.1 included (a Termux caracole serve on 8737), opens
in the browser, and nothing a page asks for elsewhere leaves the phone. A file another app opens (a PDF, a Guitar
Pro file) is read from the server inside the app, never downloaded by Android.

**Import the computer's indexes** to search the sites. The computer builds them (the nightly run, `caracole index
build`); the phone never asks the sites for them. In Settings, under Import indexes:

- **From the computer** fetches them from caracole serve at the address above (`GET /api/peer/index`, which a
  recent caracole gives).
- **From a file** takes a file made on the computer with `caracole index export indexes.sqlite` and copied to the
  phone.

The import runs in the background, with a notification while it lasts, one import at a time: asked for while one
runs, Settings says so. The phone merges the file as `caracole index merge` does: each site's newer reads win, and
nothing it holds goes back. It waits for a sync that runs, and a sync waits for it. Settings shows how the last
import ended, or why it failed, in the computer's words or the merge's ("the file was exported at schema version
14…": export it again with the computer's caracole). Import again now and then to bring the sites' new songs; a
sync from the phone brings the newer ones too ([below](#sync-from-the-phone)).

Then the library page's search works with the computer off: your songs, and the songs of Ultimate Guitar,
LaCuerda, gtptabs.com, MuseScore, harptabs.com and gametabs.net as the indexes list them, "Did you mean", and an
artist's songs. LaCuerda's own search and YouTube's suggestions need the computer.

## Sync from the phone

The library page's **Sync** tab syncs the phone and the computer both ways, as `caracole peer sync` syncs two
computers. Open it from the menu (⋮ › Sync with the computer) or from the library page's tabs. The field offers the
address in Settings; the address you compare with becomes the one Settings keeps, for Sync now too.

**Compare** asks the computer for its state and lists what differs, a line per unit: a song (its names, versions,
choices and kept files), a removal, a songbook, an artist's alias or UG page, a blocked tab. Each line says what the
sync proposes:

- **keep here's**: changed on the phone since the two last agreed;
- **take there's**: changed on the computer;
- **CONFLICT**: changed on both, differently.

Each has Here, There and Skip, the proposal chosen at first. A conflict has none until you choose, one at a time or
all at once (Keep here's for every conflict, Take there's for every conflict), and **Sync** waits until each has
one. Skip leaves a unit as it is on both sides, until the next comparison.

**Sync** runs it in the background, with a notification ("Syncing with <the computer's name>…") that keeps the app
working while you leave it, gone once it ends. Its stages show on the tab:

1. compared again, refused if either side changed since you compared (compare again then);
2. a backup of the phone's library (`state/backups/`, the last three kept), then what the computer changed taken,
   each file checked by its SHA-256;
3. what the phone changed given to the computer (`POST /peer/push`), which takes it as its own request and renders
   its pages;
4. the computer's pages copied, as Sync now copies them;
5. what the two agree on recorded, so the next comparison lists only what changes after;
6. the computer's newer indexes merged, skipped when none is newer.

At the end the tab lists what was taken here, given there and left as it was, with why ("changed here since the
comparison"), and Reload shows the library page with the songs as they are now.

The computer needs a caracole that syncs with the phone (sync format 3: `GET /api/peer/state` answers
`"format": 3`, with `POST /peer/push` and `GET /api/peer/index`). An older one is refused at Compare, with the
reason; upgrade caracole there.

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
Settings then imports that computer's indexes (From the computer), or a file pushed to the emulator's Download
folder (`adb push indexes.sqlite /sdcard/Download/`, then From a file). `adb shell pm clear
io.github.danielhp95.caracole` starts it over, as new. Never PORT 8737 on a machine whose caracole-web listens there.

Use `-gpu host`. With the software renderers (`swiftshader_indirect`, and the lavapipe fallback of `-gpu guest`),
emulators 37.1 and 37.2 crashed in their own render thread when the WebView went back a page. On the emulator,
the host's `127.0.0.1` is `10.0.2.2`. The instrumented tests sync from a running caracole serve. EndToEndTest opens
the library page and a viewer, transposes, and hands off a PDF and a Guitar Pro file. PinchTest pinches the library
page and a sheet, larger and smaller, and checks the size label and that the chords stay over their syllables.
LocalServerTest needs no computer: the app's server answers its page only with the launch's cookie, the WebView
never loads another loopback port, and a first start's database is made whole. SyncTabTest opens the Sync tab from
the menu, compares with the computer and syncs, then compares again and finds nothing that differs (it changes the
phone's library, so give it a computer of its own, such as `nix develop -c python -m tests.helpers.e2e_library serve
DIR PORT --address 127.0.0.1`):

    nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest
    adb install -r -t android/app/build/outputs/apk/debug/app-debug.apk
    adb install -r -t android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
    adb shell am instrument -w -e server http://10.0.2.2:PORT \
        io.github.danielhp95.caracole.test/io.github.danielhp95.caracole.CaracoleTestRunner

Add `-e class io.github.danielhp95.caracole.PinchTest` to run one of them. The runner, `CaracoleTestRunner`, lets the
app send no request to a site: every test's sites refuse, unless the test names the fake sites server.

`android/scripts/device-test.sh` does all of it, one caller at a time (it builds first, then holds the emulator's
lock, `${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}`), starting the emulator if none is
up and leaving it up:

    android/scripts/device-test.sh --area unicode,keys    # CorpusOnDeviceTest's areas (none named: every one)
    android/scripts/device-test.sh --app                  # EndToEndTest, PinchTest, SyncTabTest, PhoneEndToEndTest,
                                                          # each against a computer of its own
    android/scripts/device-test.sh LocalServerTest NoSitesTest SyncTabTest=/tmp/lib   # classes, one a computer

## Lookups on the phone

Not built yet.

## Performance notes

**The WAL after an import.** An import (Settings' Import indexes, or a sync's newer indexes) merges the computer's
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

Not built yet.

## Songbooks, versions and printing

Not built yet.

## Guitar Pro

Not built yet.

## Sharing files to caracole

Not built yet.

## Alerts and backups

Not built yet.
