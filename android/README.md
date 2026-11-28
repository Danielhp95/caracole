# caracole for Android

A small app that keeps a copy of your caracole library on the phone and shows it with no network: the library
page, every sheet in caracole's own viewer (key, capo, chord diagrams, harmony, pinyin, strum), the songbooks,
and the PDFs. It shows the pages caracole writes into the library as they are. When caracole is upgraded, the
pages change with it, and the app doesn't need an update. With the computer's indexes imported, its search finds
songs on the sites with the computer off ([below](#search-with-the-computer-off)), and caracole's own rules on the
phone look them up there, make their pages, songbooks and versions, file what you share to it and back it all up,
for the next sync to give the computer ([Lookups on the phone](#lookups-on-the-phone) and the sections after it).
It also makes a song's chord sheet from an audio file, heard on the phone, on an arm64 phone
([Chords from audio](#chords-from-audio-a-sheet-from-a-file)).

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
the Android SDK (platform 36, build tools 36.0.0, NDK r28c and CMake 3.31.6) from caracole's own nixpkgs, and the
host's CMake and gcc, which build libsoxr for the JVM's tests (below), and qemu's user-mode emulators. The NDK, about
2 GB, comes even for JVM-only work: `gradle test` builds libsoxr's static arm64 program with it (SoxrArm64Test), and
`:ml` and the app build and strip its native library with it. The build uses that pinned Gradle
rather than a Gradle wrapper, which would download a second copy. The flake also points the Android Gradle
plugin at the SDK's aapt2, because NixOS can't run the copy the plugin fetches from Maven. The first build
downloads the plugin and the libraries from Google's Maven and Maven Central.

The sync engine's tests run on the JVM, against a fake caracole serve, and so do the app's own (the text size, the
settings, a file read from the phone's server for another app, an index fetched or picked):

    nix develop ./android -c gradle -p android test

## Install

A phone with an old debug build under the release's package (`io.github.danielhp95.caracole`, signed with your debug
key) must lose it before F-Droid's caracole can install: sync its library to the computer first, since uninstalling
deletes its data, then `adb uninstall --user 0 io.github.danielhp95.caracole`. Debug builds made since are an app of
their own ([below](#your-phone-f-droid-and-a-debug-build-side-by-side)).

1. **Install the app**, from F-Droid or from a build of your own:
   - **From F-Droid** (signed releases, updated by F-Droid): in the F-Droid app, Settings › Repositories › **+**,
     then scan or paste
     `https://danielhp95.github.io/caracole/fdroid/repo?fingerprint=B34AD39AD80D6CE828F0885C68FD81816230BB3CB482C9E7BCC6DAD844500397`.
     Or open [the repository's page](https://danielhp95.github.io/caracole/fdroid/repo/) on the phone and tap its
     link. caracole then appears in F-Droid's list: install it from there. The fingerprint makes F-Droid check that
     the repository's index is the one signed with its key. The APKs are signed with caracole's release key, whose
     certificate's SHA-256 is `332c457ddadd0c7a2f2b7d880c827fec23cd2ab143f21a2f38c759d47b48a8f1`.
   - **Your own debug APK**, which [Build](#build) made, "Debug caracole", installed beside F-Droid's
     ([below](#your-phone-f-droid-and-a-debug-build-side-by-side)):
     - with USB or wireless debugging on: `android/scripts/phone-install.sh`, or
       `adb install -r android/app/build/outputs/apk/debug/app-debug.apk` (`-r` keeps the app's data when it is
       already there);
     - or copy the APK to the phone and open it there. Android asks you to allow installs from that app (Files,
       say) once.
2. **Open it**: caracole, in the launcher. The first start opens Settings: type the computer's address there, tap
   **Test**, then **Sync** beside it or the bar's sync button ([below](#point-it-at-caracole-serve)). Until then the library page is empty, and its
   pages say caracole, with a Phone badge beside it; the sync brings the computer's settings, among them the
   library's name when its caracole.toml gives one (`name`), which the pages then show after caracole's.
3. **The indexes**, so that its search finds the sites' songs with the computer off, come with a sync (its Site
   indexes), or from a file: Settings › **Import a file**, one made on the computer with `caracole index export
   indexes.sqlite` and copied to the phone (`adb push indexes.sqlite /sdcard/Download/`, say) ([Search with the
   computer off](#search-with-the-computer-off)).

The debug APK is signed with your machine's debug key (`~/.android/debug.keystore`), F-Droid's with the release
key, and they are two apps: `io.github.danielhp95.caracole.debug` and `io.github.danielhp95.caracole`.

## Your phone: F-Droid and a debug build side by side

F-Droid's caracole and a debug build of any checkout install at once, and neither replaces the other.

1. **Connect the phone** by wireless debugging: on the phone, Developer options › Wireless debugging, on. The first
   time, tap Pair device with pairing code and run `adb pair IP:PORT CODE` with what it shows. Then
   `adb connect IP:PORT`, with the address and port the Wireless debugging screen shows (the port changes each time
   you switch it on). USB debugging works too. `adb devices` lists the phone.
2. **Install a build** of the checkout you are in:

       android/scripts/phone-install.sh             # builds the debug APK and installs it
       android/scripts/phone-install.sh --launch    # and starts it
       android/scripts/phone-install.sh -s SERIAL   # when adb lists more than one phone

   It installs for the phone's own user alone (`adb install -r --user 0`), so the phone's other users keep what they
   have, and it never touches F-Droid's caracole. It ends by saying the version installed, `0.3.0-debug+abc1234`:
   a debug build's version names the commit it was built from (`git rev-parse --short HEAD`, `-debug` alone outside
   a git checkout), and Android's App info shows it too.

**Telling them apart**: the debug build is "Debug caracole" in the launcher, the share sheet and its notifications,
and its icon is amber, the logo smaller over a red DEBUG mark. Its server is on 127.0.0.1:8739, the release's on
8738, so both can run at once.

**Two libraries**: each app keeps its own. A new debug build starts empty: sync it with the computer (Settings, then
the bar's sync button), or import a file the computer or the other app exported (Settings › Import a file). Both can
sync with the same computer, as two phones would.

**An older checkout over a newer one**: a build's database moves forward with its schema, never back. Installing an
older checkout's debug build over the data a newer one left opens to "Couldn't start · …" (the database is too new
for it) until the debug app's data is cleared, its library with it:
`adb shell pm clear --user 0 io.github.danielhp95.caracole.debug`. If that library holds anything the computer
doesn't, sync it from the newer build before installing the older one.

**Removing it**: `adb uninstall --user 0 io.github.danielhp95.caracole.debug`, or uninstall "Debug caracole" on the
phone. Its library goes with it; F-Droid's caracole keeps its own.

## Release

A release is a signed APK in the F-Droid repository at `docs/fdroid/`, which GitHub Pages serves from `main`'s
`docs/` at https://danielhp95.github.io/caracole/fdroid/repo.

1. Raise `versionCode` (and `versionName`) in `app/build.gradle.kts`: F-Droid offers an APK as an update only when
   its `versionCode` is higher.
2. Build it signed. `~/.gradle/gradle.properties`, outside the repository, names the release key:

       caracole.release.storeFile=/path/to/caracole-release.jks
       caracole.release.storePassword=…

   (`caracole.release.keyAlias` is `caracole` and `caracole.release.keyPassword` the store's password unless
   given.) Then, in the `ml` shell, as the release carries the chord models (`:ml` and ONNX Runtime built from its
   source, below):

       nix develop ./android#ml -c gradle -p android :app:assembleRelease

   Without those properties the release APK is built unsigned. Outside the `ml` shell every packaging task of the
   release (assemble, bundle, package, install) refuses before anything runs, so no `app-release.apk` without the chord
   models is ever written (the app would say auto-chords isn't on the phone). Every release build ends with `checkApkSize`, which fails an APK
   over 100 MiB, the most the repository's Pages site takes (about 28.8 MB today). The chord models' libraries are
   arm64-v8a's alone in the release (`releaseMlAbis`): an x86_64 phone gets SQLite's and no chords, saying "no chord
   models for this phone's processor". The licences of what the chord models ship (ONNX Runtime's LICENSE and
   ThirdPartyNotices.txt, libsoxr's LICENCE and COPYING.LGPL, PFFFT's, which libsoxr is built with, BTC's and
   beat_this's) are its assets `chords/licenses/`, as alphaTab's are `alphatab/licenses/`, with a README saying that
   libsoxr is compiled into `libcaracole_soxr.so` and that caracole's, libsoxr's and the build's source is this
   repository, github.com/Danielhp95/caracole. It carries the app's yt-dlp too (`:youtube`: Chaquopy's Python, yt-dlp,
   `libqjs.so`), for arm64-v8a alone (`releaseYoutubeAbis`: Python's x86_64 libraries and Chaquopy's x86_64 assets left
   out, `DropPythonAbis`), with its notices under `licenses/youtube/`
   ([below](#youtube-on-the-phone-the-engine)), and extracts every native library at install
   (`useLegacyPackaging`, so Android runs qjs). That makes the release 28.8 MB, 9.3 MB more than chords alone (19.6 MB),
   and 55.6 MB installed on an arm64 phone (its 26.8 MB of libraries extracted beside the APK), 36.0 MB more (34.4 MiB).
   That installed figure leaves out what Chaquopy copies out of its assets into the app's files at Python's first start
   (its standard library, yt-dlp, the glue): about 14 MB more after the first YouTube run. Two builds of the same
   commit from checkouts at different paths give the same unsigned APK, byte for byte (`:youtube`'s assets and
   `libqjs.so` among it). `android/scripts/release-check.sh` checks all of it.

   F-Droid's own build server (an f-droid.org recipe, not this repository) would need, besides ONNX Runtime from its
   source: CPython for Android and Chaquopy's runtime built from source (both come prebuilt from Maven Central,
   `com.chaquo.python:target` and `com.chaquo.python.runtime`, which F-Droid's scanner refuses), python3.13 as
   Chaquopy's `buildPython`, the two wheels from `youtube/pins.json` by URL and SHA-256 into `CARACOLE_YTDLP_WHEELS`
   (pure Python, no build), QuickJS-NG's tree at pins.json's commit as `CARACOLE_QUICKJS_SRC`, NDK r28c and CMake
   3.31, and `AntiFeatures: NonFreeNet` (docs/fdroid/metadata/).
3. Before the first release that carries the chord models, and again whenever the runtime or `:ml` changes, install
   that signed release once on an arm64 phone (`adb install -r --user 0 …/app-release.apk`, over F-Droid's own: the
   same key), download the models in Settings › Chords from audio and make one song's sheet from an audio file. The
   release's R8 output and its arm64 libraries run nowhere else before it is published (the emulator takes debug
   builds alone, the Chords bench is a debug build's). Its yt-dlp likewise, before the first release that carries it
   and again whenever `youtube/pins.json` or `:youtube` changes: paste one video and take it to Ready on Wi-Fi, and the
   next day read in the Journal one sheet the phone made by itself (after a lookup found no sheet on the sites, or its
   daily pass). Both fit in the day's 50 runs.
4. Add it to the repository and sign the index (the repository's own key and its passwords are
   `docs/fdroid/keystore.p12` and `docs/fdroid/config.yml`, kept out of git):

       cp android/app/build/outputs/apk/release/app-release.apk docs/fdroid/repo/io.github.danielhp95.caracole_<versionCode>.apk
       cd docs/fdroid && nix develop ../../android -c nix shell nixpkgs#fdroidserver -c fdroid update

   `docs/fdroid/config.yml` keeps the last four APKs in the repository (`archive_older: 4`, the older ones moved to
   `archive/`, which isn't published), so that at about 20 MB an APK the Pages site stays far under its 1 GB.

5. After a schema bump (`SCHEMA_VERSION`), publish the site catalogues once before releasing the APK, so that the new
   app finds a file of its own schema: update the laptop's service, run `sudo caracole-admin index publish
   /var/lib/caracole/publish`, then `publish-indexes /var/lib/caracole/publish` (docs/deploy.md, "Publishing the site
   indexes"). Until then the app says the published catalogues are for an older version.
6. Commit `docs/fdroid/` whole and push `main`: `git add docs/fdroid` (its `.gitignore` keeps the keys and `tmp/`
   out). That includes what `fdroid update` writes besides the APK and the index: `repo/diff/` and the app's icon
   under `repo/io.github.danielhp95.caracole/`. The index names them, and F-Droid fails to update from the last
   index when they're missing. The app's page in F-Droid (its description, screenshots) is `docs/fdroid/metadata/`.

The chord models themselves are no part of the APK: the app downloads beat_this's two converted graphs from this
repository's GitHub prerelease `models`, and BTC's weights from its authors' repository, at a tap. The owner uploads the
first with `publish-models`, by hand, once a model changes (it checks the two files against `models.json`'s pins,
uploads each only once with beat_this's licence, `beat_this-LICENSE.txt`, and touches no other asset):

    nix run .#publish-models -- "$(nix build --print-out-paths .#chord-models)"

**For f-droid.org** (never done: the repository here is self-hosted), its build server would need, besides the Android
SDK and the NDK r28c: ONNX Runtime 1.27.1's source as a srclib, the tree nixpkgs pins
(`sha256-i2u/JnfbJ/srsZY3ATb2YsBBXEhTGhatsr3+9eHVV3M=`, 702,144,272 bytes as a NAR), hosted somewhere it can fetch,
since github.com/microsoft/onnxruntime answers 404; the 13 zips `cmake/deps.txt` names (each still on GitHub, pinned
in `nix/onnxruntime-android.nix`); protoc 21.12, built from protobuf's own source; and a prebuild that runs
`scripts/build-onnxruntime.sh` (java, native for arm64-v8a, aar) with no network and puts the AAR where
`CARACOLE_ONNXRUNTIME` names it. Its Anti-Features would be NonFreeNet (the models' downloads) and, while BTC's weights
have no licence, NonFreeAssets; no Tracking.

Losing either key ends the updates: the release key's APKs install over no other, and F-Droid refuses an index
signed with another key. Keep a copy of both outside the repository.

## A release when YouTube changes

YouTube breaks older yt-dlp often: the phone then says "YouTube changed what yt-dlp … reads". A fix is one pin moved
and the usual release, under an hour once yt-dlp has one:

1. Move the pin to PyPI's latest yt-dlp, or to a release you name (a tag's `2026.01.05` is PyPI's `2026.1.5`):

       nix develop ./android -c android/scripts/bump-ytdlp.sh [--older] [VERSION]

   It reads PyPI's JSON for yt-dlp and for the yt-dlp-ejs its wheel requires (`Requires-Dist: yt-dlp-ejs==…; extra
   == 'default'`), fetches both wheels into Nix's store (`nix-prefetch-url`), checks each is PyPI's SHA-256 and the
   version its `METADATA` says, and rewrites `youtube/pins.json`'s `ytdlp` and `ejs`. A version not on PyPI or
   yanked, a wheel anywhere but `https://files.pythonhosted.org/…/<its file name>` or of other bytes, and a version
   older than the pin are refused with `pins.json` as it was; `--older VERSION` goes back to an older one after a
   yt-dlp regression, every check still made. The version pinned already changes nothing. It prints the steps below.
2. `git add android/youtube/pins.json` (the flake reads only what git tracks), then
   `nix develop ./android -c gradle -p android :youtube:testDebugUnitTest`: `PinsTest` holds the wheels to the pins.
3. On the emulator, `android/scripts/device-test.sh --youtube`: `YtDlpVersionTest`, the app runs the pinned yt-dlp.
4. Raise `versionCode` and `versionName` in `app/build.gradle.kts`, build the release (`:app:assembleRelease`) and run
   `android/scripts/release-check.sh` ("Release", step 2).
5. One song by hand on the phone: a pasted video to Ready.
6. Publish: the APK into `docs/fdroid/repo`, `fdroid update`, commit `docs/fdroid/` and `android/youtube/pins.json`,
   push `main` ("Release", steps 3 and 5).

## Point it at caracole serve

1. Run `caracole serve` where the phone can reach it, on the LAN or the tailnet:
   `caracole serve --address 0.0.0.0` (see docs/usage.md). It answers to any IP address. To use a name, add it
   with `--allow-host`.
2. On the phone, open Settings (the first start opens it). Type the address, for example
   `http://192.168.1.20:8737`. Without a scheme, `http://` is assumed. An IPv6 address goes in brackets when it
   has a port (`[fd7a:115c::1]:8737`); typed without them, the app adds them.
3. Tap **Test**. It answers "studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26", or says what went
   wrong. Then tap **Sync**, right beside Test (it opens the same sheet as the bar's sync button; with no address it
   says so in place), or the bar's sync button ([below](#sync-from-the-phone)).

**Sync on Wi-Fi** syncs every 6 hours on an unmetered network, leaving what changed on both sides for you
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

What needs a network: looking songs up, which asks the sites from the phone itself ([Lookups on the
phone](#lookups-on-the-phone)) or a sheet's other version from Ultimate Guitar, and a sync with the computer. Making
a songbook, Export PDF (which prints) and Make this my version, a backup, and filing a shared file all work with
none. A sheet from a YouTube video needs a network too, and an arm64 phone ([A sheet from a YouTube
video](#a-sheet-from-a-youtube-video)), and so does YouTube's first video for a search with no sheet on the sites,
which an arm64 phone suggests as the computer's page does, on an unmetered network alone (`YouTubeSearchRunner`,
`POST /youtube/search`): its row fills the request form, and nothing downloads until you send it. What isn't on the
phone at all says so ("…: not on the phone yet."): caracole serve's lookup page (the library page's search does its
work). Use caracole serve in a browser for it.

The pages come from the app's own server, with the same Content-Security-Policy and sandbox headers caracole serve
sends, so the viewers run sandboxed as they do there.

## Text size

Pinch any page to change its text size: fingers apart make the text larger, fingers together make it smaller. The
size goes from 50% to 250%, in steps of 5%, where 100% is the size Android's own font size setting gives the pages.
The text grows or shrinks, and on the library page so do a song's buttons, its line's height, its card's tiles,
an artist's band and the search bar's buttons, until a song's line fills the screen's width (about 215% on a phone
412 dp wide): from there the text grows on, each title cut shorter, and the line stays one row with its key on the
screen. The page reflows to the screen's width, so it never zooms as a picture and never scrolls sideways. The size holds for every page and across restarts. Settings shows it ("Text size: 120%"), and
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
`http://127.0.0.1:8738` (a debug build on 8739), or another free port when that one is taken. The WebView loads the library page from it:
caracole's own page, built from the same files caracole serve builds it from, each of your songs' cards made from
the phone's own library as caracole serve makes it. Sheets, PDFs and songbooks are the copy's files where the phone
holds the song as the computer did, else the pages the phone makes itself.

**Only the app can use that server.** At each launch the app makes a random secret and sets it as a cookie
(`caracole-launch`) in its WebView. The server refuses any request without it ("Not this app's scribe."), so
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
artist's songs. LaCuerda's own search goes from the phone itself, as on the computer ([Lookups on the
phone](#lookups-on-the-phone)), and so does YouTube's first video for a search with no sheet on the sites, on an arm64
phone and an unmetered network (above). A link to an Ultimate Guitar tab or artist
page pasted into the box is no search: its panel reads that page from the phone itself, once, at a lookup's pace (the
tab's page, then its artist's lists), so the next search finds every song of that artist, and its Fetch this version
keeps the tab you pasted.

UG's artist directory comes with UG's index: every artist UG's letter listings name, which the computer reads (the
phone reads no listing). A search that names one whose page caracole hasn't read, an artist the sitemaps list only by
bare ids (宋冬野, Joaquín Sabina), shows them with the tabs UG counts of theirs and **Read their page on UG**. Pressed,
it reads that page from the phone itself, as a pasted link does, and their songs show in their group.

## Sync from the phone

The bar's **sync** button (two circular arrows, left of ⋮) opens the library page's sync sheet, from any page: the
phone and the computer at the address in Settings compared, and each takes what the other changed, as `caracole peer
sync` syncs two computers. It is the sheet caracole serve's Share tab opens, written once in library_assets; the
phone's library page has no Share tab.

1. **What to sync**: Library (your songs, their sheets and pages, both ways), Songbooks and Site indexes (for
   searching offline), all three ticked, each with what is waiting ("3 changed on the computer"). A song a songbook
   lists comes along with the songbooks, even with Library unticked. **Cancel** on the left, **Sync** on the right.
2. **A card for each conflict**, a song (or a songbook, a removal…) changed on both sides since the two last agreed:
   its name, "1 of N", the phone on the left and the computer on the right, a line for each way the two differ (its
   own key, its sheet, its versions, its kept files…). Under "Which version to keep", **Phone** or **Computer**, and
   **Same for the other N**. Above the card, what is to take (↓), to give (↑) and changed on both (⚠). There is no
   Skip: Cancel ends the sync with nothing taken or given.
3. **The sync** runs in the background, with a notification that keeps the app working while you leave it, gone
   once it ends. It names the computer, the stage the sync is at and what that stage says ("Sharing logs with studio
   · Copying the computer's pages · 120 of 640 pages"), its bar filled where the stage counts:
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

**Sync**, beside Test, and **Export and Import a file**, in Settings, open the sheet at the sync, the export or the import.

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

**Sync on Wi-Fi** (Settings) is this sync, unattended: every 6 hours on an unmetered network, the three
parts, every change made on one side taken or given, and each conflict left as it is on both sides, for the next
sync you start. First it reads the computer's state at the address in Settings; when nothing answers there, or
something else does (another network's device, a Wi-Fi login page), it does nothing and says nothing. While it runs,
the bar's line says so and names the stage it is at ("Syncing with the computer · Updating the indexes · …"), and at
its end what it did for a few seconds ("Up to date · 1
taken, 2 given"; "2 changed on both sides: tap Sync to choose"; or why it failed, a stage that failed among it, such
as the copy of the computer's pages). When it left conflicts, a notification on its own channel, Syncs, says so ("2
songs changed on both sides: tap to choose"), and its tap opens the sheet, whose cards ask; the next one that leaves
none takes it back. A sync with the computer already on its way (one from the sheet) is left to finish, and this one
does nothing.

The computer needs a caracole that syncs with the phone (sync format 3: `GET /api/peer/state` answers
`"format": 3`, with `POST /peer/push` and `GET /api/peer/index`). An older one is refused as the two are compared,
with the reason; upgrade caracole there.

**Your changes on the phone.** A song you add on the phone is in your library at once. A search row's Fetch, or
the request form with Fetch ticked, looks it up on the phone then ([Lookups on the phone](#lookups-on-the-phone)), and
the phone makes its pages; one asked for without Fetch asks no site, its line saying "Added · fetched tonight", and
the computer's next run fetches it once a sync gives it there. A song you remove on the phone
leaves the library page at once, and its pages answer "Removed from the phone's book." until a sync settles it:
given to the computer, which removes it too, or taken back from it. A song the phone holds otherwise than the
computer did when it made its pages is shown in the pages the phone makes of it ([Pages built on the
phone](#pages-built-on-the-phone)); until they are made, the computer's answers "Changed on the phone since the
computer wrote this page.", with a link to the phone's own sheet when it has one. A sync gives the change to the
computer, which renders the song again as it takes it, and a later sync copies its new pages.

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
7. **Share logs with the computer**: `caracole peer sync http://COMPUTER:8737` on the phone (docs/usage.md, "Two
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
(`adb shell am start -n io.github.danielhp95.caracole.debug/io.github.danielhp95.caracole.MainActivity`, or from the
emulator's launcher), and point it
at a computer of its own: `nix develop -c python -m tests.helpers.e2e_library serve DIR PORT --address 127.0.0.1`
builds a library of 20 songs in DIR with no request and serves it on the host's loopback alone (caracole serve has
no sign-in: never on the LAN for a test), which the emulator reaches at `http://10.0.2.2:PORT`. Its
bar's sync button then brings that computer's indexes with the rest, and Settings' Import a file a file pushed to the
emulator's Download folder (`adb push indexes.sqlite /sdcard/Download/`). `adb shell pm clear
io.github.danielhp95.caracole.debug` starts it over, as new. Never PORT 8737 on a machine whose caracole-web listens there.

Use `-gpu host`. With the software renderers (`swiftshader_indirect`, and the lavapipe fallback of `-gpu guest`),
emulators 37.1 and 37.2 crashed in their own render thread when the WebView went back a page. On the emulator,
the host's `127.0.0.1` is `10.0.2.2`. The instrumented tests sync from a running caracole serve. EndToEndTest opens
the library page and a viewer, transposes, and hands off a PDF and a Guitar Pro file. PinchTest pinches the library
page and a sheet, larger and smaller, and checks the size label, that a song's line on the library page grows with
the text (its buttons, its row and band as far as the screen's width lets them, every key on the screen), and that
the chords stay over their syllables.
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
        io.github.danielhp95.caracole.debug.test/io.github.danielhp95.caracole.CaracoleTestRunner

Add `-e class io.github.danielhp95.caracole.PinchTest` to run one of them (the debug build's package ends in `.debug`,
its classes' don't). The runner, `CaracoleTestRunner`, lets the
app send no request to a site: every test's sites refuse, unless the test names the fake sites server.

`android/scripts/device-test.sh` does all of it, one caller an emulator at a time (it builds first, then takes the
first free emulator of its pool, `CARACOLE_EMULATORS`, 3 by default: emulator-5554, -5556 and -5558, holding its lock,
`${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}` for the first and the same name with the
port for the others), starting that emulator if it isn't up (each read-only, so several run on the one AVD). As it
ends, on any path, it stops the emulator it started, while it still holds its lock, and leaves one that was up already;
`--keep-emulator` (or `CARACOLE_KEEP_EMULATOR=1`) keeps the one it started, to look at it. The computers and the other servers it starts are
stopped as it ends, every one (whatever each started under it too), and the folders it made for them removed. It stops the adb server it
started once adb lists no device and no other caller holds an emulator, never one with a phone attached. That is the
owner's rule of 2026-11-27: "Ensure that emulators are properly killed when using them for testing or development.
same thing for gradle biuld and adb servers." An emulator left by a run that was SIGKILLed, or by a script older than
this, reads as someone else's to every later caller and stays up until `android/scripts/stop-all.sh` runs, which stops
what is left at a task's end: every pool emulator no caller holds, and the adb server when no device is listed and no
caller holds an emulator. A Gradle daemon stops after two idle minutes (gradle.properties), and the Kotlin compile
daemon with it; `stop-all.sh --gradle` stops them at once, but `gradle --stop` stops every daemon of that version for
you, another worktree's running build among them, so it refuses while one is busy or `gradle --status` fails; the
check and the stop are not atomic, so a build that starts elsewhere between them can still be killed.

    android/scripts/device-test.sh --area unicode,keys    # CorpusOnDeviceTest's areas (none named: every one)
    android/scripts/device-test.sh --app                  # EndToEndTest, PinchTest, SyncSheetTest, ExportImportTest,
                                                          # PhoneEndToEndTest, each against a computer of its own
    android/scripts/device-test.sh LocalServerTest NoSitesTest SyncSheetTest=/tmp/lib   # classes, one a computer
    android/scripts/device-test.sh --ml --tcpdump /tmp/ml.pcap NoTelemetryTest   # the chord models (below), captured

## Lookups on the phone

The library page's lookups ask the sites from the phone itself, as `caracole get` does on the computer, with the
computer off:

- **Fetch** on a search's line, and **Request** with Fetch ticked on the request form, look the song up now: the
  song you have, or a new one, which the lookup adds. A pick on the line (an Ultimate Guitar song or tab, a LaCuerda
  song, a harptabs.com or gametabs.net tab) is the one it asks for. **Add** with a LaCuerda song picked records the pick for the song, as
  `caracole add --lacuerda` does, for the next lookup or the computer's nightly run once synced.
- **Fetch** on a song's card looks up a song you have, unless it is ignored or caracole isn't sure which Ultimate
  Guitar song it is (review it first).
- An artist's **Songs** reads their page on LaCuerda or harptabs.com, and **Fetch them** keeps more of a song's
  Ultimate Guitar versions.
- **LaCuerda's own search** goes as on the computer: once a query has settled, by the page itself while its gate
  allows, or with Ask LaCuerda, never twice for a query, at most 20 an hour by the page alone.

Each is a request of the Journal, one at a time behind any other, its line on the song's card saying how it goes
in caracole serve's words. A form posted without the page's script goes to that request's line in the Journal.
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
serve: **Pick the match** on its card, **Pick** on its line in the Journal, or a not-found song's **Look in index**
(**Search the index** in the Journal: what the offline index finds for its artist and title) lists the candidates, each with why the matcher thought of it,
its score, its tabs and its Ultimate Guitar page. A pick goes into the phone's overrides under `[match]` (and
`[alias]` when the artist is spelled otherwise there), **None of these** under `[reject]`, and the song's match is
decided again at once, with its artist's other songs after an alias. **Fetch** (ticked) then looks the song up,
as Fetch does. While a request of the song's waits or runs, a pick is refused until it ends. A sync takes the
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
through it until a checkpoint, which the import's checkpoint now leaves none of. On the owner's phone (Sony XQ-DQ72,
Android 15, the M4 check's ColdSearchTest): the 300,000 rows merged in 7.6 s, the first search after a start
118 ms, a warm one 24 ms.

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

A lookup makes its song's pages as it ends ("pages made; no PDFs on this scribe"). After a sync that changed
songs, and when the app starts as a new build (any APK whose code or tables differ, whatever its version says), the
phone makes the pages it owes in the background, a request of the Journal ("Remake the pages"), which lets a
lookup asked for meanwhile go first, between two songs. A song whose pages can't be made says why on that request, and
costs the other songs nothing; it is tried again once the song changes or a new build is installed.

On the emulator: `android/scripts/device-test.sh --area render`.

## Songbooks, versions and printing

The Songbooks tab's forms and the Select bar's songbook are the phone's own, as `caracole songbook` is on the
computer: **Make** a songbook of the songs picked, **Add** to it (a song you have at once; one new to the library, from
the tab's search, looked up first, the two queued together or not at all), **Move** a song, **Take it out**,
**Rename** and **Delete** a songbook. Each is a request of the Journal, one at a time behind any other, its line
saying how it goes ("Making the songbook…", then "Made"); a form that can't be done (a name taken, a songbook or a
song that isn't there, a song of the computer the phone hasn't got) is refused at once, in caracole serve's words, and
queues nothing. The songbooks are the phone's (`phone_songbooks`), which a sync gives the computer.

- **A song's chip** sets where the songbook plays it, as on the computer: its key, mode, capo and instrument, or **Its
  own version**; a key or a mode alone keeps the capo it plays at now, and another instrument the pitch it plays at.
- **Fetch the missing songs** looks up each song of the songbook the phone has no sheet of (one a sync brought plays from
  the computer's sheet, and is never asked for), as many as the queue has room for, then makes the songbook again; a
  set list's **Fetch**, that song alone.
- **Phone page**: the phone makes each songbook's page itself (`_songbooks/<name>/songbook.html`), from the sheets it
  plays, after every change; the PDF and the ChordPro file are the computer's (chordpro), so the phone links neither.
  A page that can't be made fails its request ("Making the songbook failed."), the change itself made.

**A sheet's versions.** A sheet the phone made lists its other Ultimate Guitar versions under its key line, as on the
computer. **Make this the one**, **Keep** and **Back to our pick** open a page of the phone's own that says
what the version is and what the song's sheet is now, with the one button that does it. Its request then shows on
that page until it is over (the page reloads every ten seconds), and in the Journal: Make this the one looks the
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
  Journal shows it ("Your version"). Like caracole serve's, it is a plain link with no form token, the one
  write the phone takes so.
- The phone names the version of a sheet of its own library: one it made the pages of, or one of the computer's
  pages whose song a sync brought (the Share tab). A copy of the computer's pages with no song of its own (Sync now's
  pages alone) has no sheet to name, and says so. The auto-chords sheet kept beside a song's own sheet, and a kept
  version's page, offer no export of their own, as on the computer.

## Guitar Pro

A song's Guitar Pro file (filed from the inbox or downloaded from gtptabs.com) opens on a page of its own in the app,
as it does in caracole serve: the score drawn by alphaTab and played by its synthesizer (Play, Stop, Tempo), Tab only
or Score and tab, each track shown or muted (on a phone, one button names the track shown and opens a sheet of the
tracks: a tick to show each and its speaker to mute it). **Download** gives the file to another app. A Power Tab file
is a download alone.

alphaTab (MPL-2.0), its Bravura music font (SIL OFL 1.1) and the Sonivox SoundFont (Apache-2.0) are in the app, their
licences beside them in its assets (`alphatab/licenses/`): nothing is downloaded. A Guitar Pro file of a song only the
copy of the computer's pages has (not in the phone's own library yet) opens in another app instead, as before.

Building the app needs `CARACOLE_ALPHATAB_DIR` (alphaTab's files, nix/alphatab.nix), which `nix develop ./android`
sets; without it the build stops and says so.

## Sharing a song from a music app

In a music app, **Share** a song and pick **caracole** in Android's share sheet: caracole opens on a page of its own
for that song.

1. **What it read**: "We read Queen – Bohemian Rhapsody." It reads the artist and the title from the text the
   app shared, the way caracole reads what you type in a search box, with no request. "What Spotify sent" shows the
   text as it came. When the app shared a link alone, caracole asks its service once what the link names (below):
   "Read from Spotify's page: Queen – Bohemian Rhapsody."
2. **Best match**: the song the phone's search finds for those names, in your library or in the indexes, with
   what each site has of it ("UG: chords ×12 · tabs ×3 · LaCuerda ×2"), and "In your logbook" when the
   song is yours. Up to three other songs the search found come under it, each with its own Fetch.
3. **Your choice**:
   - **Fetch** looks the song up now, like a search line's Fetch, and the Journal shows how the lookup goes.
   - **Open** shows your song, when the library has it.
   - **Edit** takes the artist and the title as you type them, then searches again.
   - **Cancel** takes you back to the app you shared from.

Nothing is sent to a tab site until you tap Fetch. With no index imported, the page says so, and Fetch still looks
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

A YouTube video shared to a phone that makes sheets from YouTube (an arm64 phone) also offers **Make its sheet from
this video** for the song it names ([A sheet from a YouTube video](#a-sheet-from-a-youtube-video)). Nothing downloads
before you press it.

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
- **A file caracole keeps already** (the same bytes, under any name) is nothing new: "Filed · guitar-1.gp5 of …".
  One the library lost (deleted on another device) is put back where it was.
- **A file no song fits waits**, up to 30 days, and is tried again after each sync and each lookup: share a Guitar
  Pro file first and look its song up after, and it is filed then. One that couldn't be filed (its song's folder is
  another song's too, the phone is full) waits too, tried again after the next sync, or a day later.
- **The bytes of a file caracole keeps whose copy you changed since** are not filed: "Not filed: … whose place holds
  other bytes now, and nothing is replaced". caracole replaces nothing of yours; the file is put back once that place
  is free.
- A score is placed by its name alone on the phone: a MusicXML file named "score.musicxml" waits, where the computer
  would read the title and composer inside it.

A toast says how each went, as its line in the Journal does: "Filed · guitar-1.gp5 of Oasis - Wonderwall",
"Waiting for its song: Somebody - Unknown Song.gp5", or "Not filed: …" (a file of another kind, say: caracole keeps
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
  the Journal shows for it. One that fails while you are in the app says so there alone.

Tapping one opens the library.

**Backups** are in Settings, Open the backups: each backup is a copy of the phone's library, its songs, their versions,
the songbooks, the picks and overrides made on the phone, and the files it keeps (sheets, tabs, Guitar Pro files), each
file once however many backups hold it. The indexes aren't backed up: they come again from the computer.

- **Back up now** makes one by hand. One is also made every day while the phone is idle and its battery isn't low, and
  one before each sync takes anything from the computer. Three of each kind are kept, the oldest going as a new one is
  made; none is made without twice the room it needs (the Journal then says "Not backed up: there isn't room for
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

A backup, its daily one and a restore are requests like a lookup, one at a time in the Journal ("Backed up
(by-hand)", "Restored the book of 2026-11-10 09:14"), never run beside a lookup.

## Chords from audio: the models

The chord model (BTC) and the beat model (beat_this) run on the phone in `:ml`, on ONNX Runtime 1.27.1 built from its
source (`OrtModels`; the owner's Gate R of 2026-11-27, "Build 1.27.1"). Both builds carry it (stage S; the release its
libraries for arm64-v8a alone, Release above), and only in the `./android#ml` shell: `../nix/onnxruntime-android.nix`
builds it with no network, for arm64-v8a and x86_64, and makes an AAR of the two in a Maven folder of its own, which
that shell names as `$CARACOLE_ONNXRUNTIME`. Without the variable `settings.gradle.kts` leaves `:ml` out, and the debug
build has no chord models and no Chords bench (`src/ml`, `src/debugMl`, `src/testDebugMl` and `src/androidTestMl` come
with `:ml`, `src/noMl` without it), so the other shells build and test the rest with no ONNX Runtime.

- The source is nixpkgs' pin of the tag v1.27.1 (`sha256-i2u/JnfbJ/srsZY3ATb2YsBBXEhTGhatsr3+9eHVV3M=`), which
  cache.nixos.org serves: github.com/microsoft/onnxruntime answers 404. Each CMake dependency is the zip `deps.txt`
  names, pinned by its SHA-256 in a local mirror (CMake checks `deps.txt`'s SHA-1 too).
- `scripts/build-onnxruntime.sh` compiles the Java bindings once (javac: ORT's own Java path runs Gradle, which
  fetches), builds each ABI with the NDK r28c, and zips the AAR. Each ABI gets the CPU execution provider alone, the
  kernels of the graphs' ops alone, and telemetry off (1.27.1's is opt-in, never set, and it has no Android telemetry
  at all). Every path of the build is mapped, there is no build id, one date (`EPOCH`) and every zip's entries sorted,
  so two folders give the same bytes. It runs at most 8 compile jobs, whatever Nix's `--cores` says.
- The ops are `ml/onnxruntime-ops.config`, made by `scripts/onnxruntime-ops.sh` from `nix build .#chord-models`'
  graphs, each as it is and as ONNX Runtime 1.27.1 optimizes it on x86_64 and on aarch64. The aarch64 run is
  cache.nixos.org's build of it under qemu-user (`./android#onnxruntime-ops-aarch64`), so arm64's own fusions are in
  the list. `onnxruntime-ops.sh --check` holds the committed list to the graphs. An op left out would fail loudly at
  session load, never silently; the owner's bench on the phone is the last check.
- It is built once a machine, about ten minutes an ABI, then kept in the store:
  `nix build ./android#onnxruntime-android` builds it alone. Entering the `ml` shell roots it against Nix's garbage
  collector (`$XDG_STATE_HOME/caracole/gcroots/onnxruntime-android`); `nix build ./android#onnxruntime-android -o PATH`
  roots it at PATH instead.

Its AAR declares no provider and no permission. `ApkScanTest` scans it in the `ml` shell's `gradle test` for what made
Maven's AAR phone home: `mobile.events.data.microsoft.com`, `ai.onnxruntime.TelemetryInitializer` and
`ai/onnxruntime/telemetry/`. Elsewhere that test is skipped, saying so. `gradle :app:apkScan` scans the release and
debug APKs the same way. `OrtModels` still sets `ORT_DISABLE_TELEMETRY=1` before the first environment and turns its
events off, and `NoTelemetryTest` checks that the installed app declares no provider of the runtime's.

The models are the computer's own, `nix build .#chord-models` (`CARACOLE_CHORD_MODELS` in the `./android#ml` shell);
the APK carries none of them. `ModelParityTest` runs them on the emulator over the computer's records
(`tests/conformance/vectors/autochords/models.jsonl`), every threshold read from the records' `gates`: BTC's chords
frame for frame, beat_this's fp32 logits, and the fp16-stored file's beats and downbeats by their F-measure:

    android/scripts/device-test.sh --ml --tcpdump /tmp/ml.pcap NoTelemetryTest

`--ml`, `--models`, `--data` and the corpus's `autochords` area build in the `ml` shell (the debug build with `:ml`);
every other run builds in the default one. `--ml` pushes the four files into the emulator's
`/data/local/tmp/caracole-models` (again only when one changed) and
runs `ModelParityTest` from `:ml`'s own test APK, which reports each model's load, each clip's time and its peak RSS,
`DecoderTest` and `PipelineTest` (below), then the app's `ChordsBenchTest` (the Chords bench, below) over the same
files.
`--tcpdump FILE` gates on what caracole's own uids send. Before the classes, on the rooted emulator (`su 0`), it puts a
chain of iptables and ip6tables rules at the head of OUTPUT that counts the packets of each of caracole's packages
installed (the debug app, its test APK, `:ml`'s test APK) by `-m owner --uid-owner`. Packets to 10.0.2.2 and to loopback
are counted apart; any other packet of theirs fails the run. A control proves the rules see the app's traffic: a
connection to a listener on the host's loopback, sent as the debug app (`run-as`) before and after the classes, must be
counted, each on its own: the counters are read just before each, and each must raise them by its own packets (the
classes' own packets to 10.0.2.2 are printed apart). `caracole_own` must also still be the first rule of OUTPUT in both
tables as the classes end. The rules come off however the run ends. What the gate proves: nothing caracole's own uids
sent left for a host other than 10.0.2.2 or loopback. What it doesn't: traffic another uid makes on caracole's behalf, a
name lookup among it (Android's resolver sends from its own process, and whether it charges the asking app wasn't shown
on this image: a lookup of an `.invalid` name as the app sent no packet at all). The capture lists such traffic but
can't attribute it: a lookup shows as a packet to or from the emulator's DNS (10.0.2.3), printed under a heading of its
own, listed, not attributed, and the reader's to judge; it never fails the run. The whole interface is captured too, as
evidence, with Wi-Fi off so that everything goes through the network the emulator's console captures. Its own control (a
ping of 10.0.2.2 and a connection to the listener) must be in FILE, and each packet to or from another host is listed
with the uid holding its socket as the classes end. It fails the run only when that uid is caracole's: the emulator's
own Google Play services talk to Google now and then, and are no failure of caracole's. A run killed with SIGKILL leaves
Wi-Fi off and the rules in: `adb -s emulator-NNNN shell svc wifi enable`, and `su 0 iptables -D OUTPUT -j caracole_own`
(and `ip6tables`) in `adb shell`. `:ml`'s test APK runs under AndroidJUnitRunner, not CaracoleTestRunner: it has no HTTP
code, so `caracole.network=loopback` isn't set for it.

BTC's graph and `models.json` (`tests/conformance/data/caracole/autochords/`) are `:ml`'s resources, so a build with
`:ml`'s alone; `:core`, whose resources are the rest of that folder, leaves them out. What the release carries, and
what it doesn't, is a check to run again:

    android/scripts/release-check.sh

It builds the release (unsigned without the release key: the same packaged output) and the debug build in the `ml`
shell, reads each APK by the name its `output-metadata.json` gives, and checks that the release's runtime classpath
names `onnxruntime` and `:ml`, and that its APK holds ONNX Runtime's and libsoxr's libraries for arm64-v8a alone,
classes under `ai/onnxruntime/` and of `:ml` (dexdump), `caracole/autochords/` with one model file (BTC's graph, no
weights), MlService in its `:ml` process, the licences under `assets/chords/licenses/` (each its source's bytes), and
nothing of the Chords bench (its classes, Settings' row, `assets/autochords/`, its manifest's entries) or of the
runtime's telemetry (aapt2), within 100 MiB. Every probe has a control that shows it can see what it looks for: the
debug build's APK (which holds the bench and x86_64's libraries, and none of the weights' files), the names of the
files `.#chord-models` makes, the runtime's own AAR, whose manifest declares no provider, the licences' probe telling
two licences apart, and `gradle :app:apkScan`, whose own control finds each string it looks for where it would be.

## Chords from audio: the decoder

The phone decodes a song's audio as the computer does (autochords/audio.py `load_mono`, at the file's own rate):
`:ml`'s `Decoder.decode(file, into)` writes interleaved float32 PCM to a file, a buffer at a time. A WAV or an AIFF is
read by `:autochords`' `Pcm`, with no codec, as libsndfile reads it; anything else goes through MediaExtractor and
Android's own software decoders (`c2.android.*`, never a vendor's). `Mixdown.mono` means the channels as numpy does.
`DecoderTest` holds it to the computer's decode of thirteen files (`tests/fixtures/autochords/encode.sh`: MP3 from
FFmpeg's LAME, from the lame program, and with no header; AAC at 22.05 and 11.025 kHz; AAC as yt-dlp leaves it on the
phone, as fragmented MP4, in two forms (one fragment, and a DASH-style file of six); Vorbis; Opus; FLAC of 16 and 24
bits; WAV; AIFF;
`tests/conformance/vectors/autochords/decode.jsonl`), on the emulator with `--ml`:

    android/scripts/device-test.sh --ml

On the emulator (2026-11-26) the lossless files come out sample for sample, but the 24-bit FLAC, which Android's
extractor gives as 16-bit (77 dB), the lossy ones at offset 0 and 72 to 83 dB of SNR (the gate is 60, whole and each
second), every file's frames the computer's to the frame, and the length it states (`durationS`, the one an auto sheet
is laid over) the computer's `read_audio`'s to the bit. What a plain MediaCodec loop gets wrong, and it doesn't:

- it trims as the computer does, never by the codec: where the format names the encoder's delay and padding, the
  framework's codecs may trim them themselves (this emulator's do, so they'd go twice), so it takes both keys out of
  the codec's format and trims itself: an MP4 to its edit list exactly (its last frame's padding is past 0.05 s at
  11.025 kHz), an Ogg to its last page's granule position (Opus's last packet runs 648 samples past it);
- it gives Android's MP3 decoder a frame of silence before a file with no LAME header, since that decoder always drops
  the first 529 samples it makes, where FFmpeg keeps them;
- it reads the length as mutagen does (an MP4's `mdhd`, a LAME tag's delay and padding taken off only where its
  version string is LAME's), never the extractor's;
- a fragmented MP4 (yt-dlp's m4a with no FFmpeg: an empty `mdhd`, no edit list) it decodes as the computer's remux of
  it does (yt-dlp's FixupM4a): its priming kept, as no box names it, and ended at its fragments' length, which is the
  length it states (2026-11-27: both forms to the frame, 82.7 and 78.1 dB; read whole and stated by its `mdhd`, the
  last frame's padding, 820 and 616 frames, was too many and the length 0); one whose fragments can't be read (a
  download cut short, trailing junk) it refuses in words, never stating a length of 0;
- it reads the decoder's output in the encoding it names, and refuses one it doesn't read;
- a decoder that stops, or changes its rate or channels partway, fails the decode in words.

Not covered by these files, and so not shown to match: an MPEG-1 MP3 at 44.1 kHz (the fixtures are MPEG-2, to keep
the corpus small), Ogg FLAC, HE-AAC (a decoder that doubles the rate, its SBR implicit, gets the edit list's samples
rescaled to its output's rate, exactly where they can be, else the format's stated delay and padding: shown on the
JVM through a fake codec alone), an MP4 with no edit list (iTunSMPB alone: trimmed by the extractor's stated delay and
padding), a non-AAC MP4 such as ALAC (its length the decoded seconds, not its `mdhd`), an AAC with perceptual noise substitution (each decoder fills those bands with noise of its own,
so no two agree; the fixtures are encoded without it), an AAC with loudness metadata (its normalization is asked off,
untested), a 24-bit FLAC to the bit (Android gives 16), an MP4 of several edits, a VBRI header mutagen refuses, an Ogg
stream that begins past granule 0, and any file of several audio tracks (the first is taken, where FFmpeg takes its
"best"). What only another Android image or a real phone shows: what MP3Extractor reports as `encoder-delay` there,
and whether taking the keys out of the format stops the platform's own trim on every version from the app's minSdk.

## Chords from audio: the resampler

The computer resamples audio for its models with python-soxr, librosa's resampler, which runs libsoxr 0.1.3; the phone
runs the same C. It is vendored in `autochords/native/soxr/` (LGPL-2.1+, its README names its source, its hash and its
two patches) and built with caracole's resample over it (`caracole_soxr.c`: python-soxr's `soxr.resample` of a
contiguous 1-D float32 array, the path that takes, `csoxr_split_ch`, one channel of split I/O) and the JNI to that
(`soxr_jni.c`) into one shared library, `libcaracole_soxr.so`, by `autochords/native/CMakeLists.txt`: by the NDK for
arm64-v8a and x86_64 in `:ml` (its `externalNativeBuild`; the release keeps arm64-v8a's alone), and by the host's gcc
for the JVM's tests (`:autochords`'s `hostSoxr` task, its folder on the tests' `java.library.path`). `:autochords`,
plain JVM, holds the front ends of the chords from audio (below); its resampler is `Soxr.resample(x, from, to)` (rates
finite and over 0: libsoxr never returns from an infinite one), which `SoxrTest` holds to python-soxr's answers
(`tests/conformance/vectors/autochords/soxr.jsonl`, made on x86_64 by libsoxr's SIMD engine, cr32s) within 1e-6:

    nix develop ./android -c gradle -p android :autochords:test

The phone's arm64 code is measured on this machine, never on a phone: `SoxrArm64Test` runs a static arm64 program of
the same sources and flags (`soxr_driver.c` over `caracole_soxr.c`, `arm64SoxrDriver`, by the NDK) under
`qemu-aarch64` over every record, and holds both of libsoxr's engines there to them within 1e-6: the SIMD one, cr32s
on NEON, which `soxr/aarch64.patch` turns on (upstream libsoxr, and so python-soxr, on aarch64 is scalar), the same
bits as x86_64's cr32s on every record (2026-11-26); and the scalar one, cr32 (`SOXR_USE_SIMD=0`), within 6e-7. So
the patch buys parity with the engine the vectors are made with, to the bit. It skips, saying why, without the NDK or
qemu.

What the APK carries of it is checked by a script, after `gradle -p android :app:assembleDebug`:

    nix develop ./android -c android/scripts/native-check.sh

`android/scripts/release-check.sh` runs it on the debug and the release APKs it builds (the release's
`libcaracole_soxr.so` and `libqjs.so` arm64-v8a's alone, `--release`), and fails with it: run it after any change to
the native code or the packaging. It checks each ABI's `libcaracole_soxr.so`, and `:youtube`'s `libqjs.so` (below), is
packaged as the APK installs it (stored uncompressed and 16 KB aligned, or compressed in an APK that extracts its
libraries at install, as every build does since Y5.1: release-check.sh asks both APKs' extracted, `--expect
extracted`), its segments 16 KB
aligned, stripped (no `.debug_*`, `.symtab`, `.comment` or build-id), and names no path of the build (`/home/`,
`/nix/store/`, `.cxx/`, `/tmp/`), and prints its SHA-256: two checkouts at different paths build the same bytes (the
library carries no debug information, `-g0`, its folders mapped away, `-ffile-prefix-map`). Every symbol but the JNI's
is hidden.

## Chords from audio: the hearing

The phone hears a song in a process of its own, `:ml` (`MlService`, in both builds), so the models' memory, a
crash or Android's low-memory killer never touch the app's server: `MlChordModels.hear(audio, onStep, waiting)` sends
the service the file's path and waits, saying run.py's steps ("setting up the models", "hearing the chords", "finding
the beats", and "waiting for the phone to cool"). The service's `Pipeline` decodes, mixes down and resamples to 22,050
Hz, runs BTC, then beat_this, one model at a time, and keeps each step's answer in
`files/state/cache/autochords/<sha16>-c1/`, so a hearing cut off goes on from its chords. A dead `:ml` is
`ChordsUnavailable`; the process ends after each hearing. The phone's heat and battery decide its threads, a wait or a
stop (`HeatRules`). `PipelineTest` holds the whole to the computer's hearing of the committed clips and of a 44.1 kHz
stereo MP3 and a 48 kHz stereo M4A (`models.jsonl`'s `gates.end_to_end`) and kills the process mid-hearing;
`device-test.sh --ml` runs it. On the emulator (2026-11-26) every file's WCSR and F are 1.0 (to the last bit but one),
each heard in 2-10 s, `:ml` at 300-410 MB at its peak.

`ParityRunTest` runs the same gate over songs that stay outside the repository (your own): a folder of audio files
with the computer's hearing of each beside it, made in the model shell from the repository's root,

    nix develop .#autochords -c python -m tests.helpers.autochords_reference --hearings ~/some-songs ~/hearings

(`meta.json`, the gates, and a few KB a song, `<name>.hearing.json`), then, with the songs and their hearings in one
folder (links will do),

    android/scripts/device-test.sh --data ~/songs-and-hearings

pushes it to the emulator, hears each song whole through `:ml`, prints each one's WCSR, F, the lengths each model read
against the computer's, where the chords part, its time stage by stage and `:ml`'s peak, then the whole over all, and
removes the folder from the emulator however the run ends. Without `--data` the class is skipped. On x86_64 the
emulator runs the phone's software decoders but not its CPU's kernels: only the phone's own bench says those.

What bounds a song's length is the models' own memory, not the song's: every stage reads the samples from files (the
pcm memory-mapped, the resampler streamed) in fixed blocks, and beat_this runs over 1500-frame chunks whatever the
length, so a 30-minute song costs its peak what a 3-minute one does (the beat session, about 756 MB on the owner's
phone), plus what grows with the song: BTC's features, 0.37 MB a minute (11 MB for 30 minutes), and the beat logits,
24 KB a minute. Its files take room while it is heard: the decode at the file's rate (30 minutes of 48 kHz stereo,
690 MB), its mixdown (345 MB) and the 22,050 Hz pcm (159 MB), each gone once the next is made, the pcm once the beats
are kept.

## Chords from audio: a sheet from a file

The phone's audio job (`caracole audio --upload=ID --song=…`) hears with the real `:ml` process (src/ml's
`PhoneChords`, both builds of the `ml` shell; a build without `:ml` has none, and says auto-chords isn't on the phone).
The models are those Settings' download installs in `files/state/models/c1/`. A hearing refuses under 15 % of battery
when not charging, holds a partial wake lock while it runs, goes one at a time (a job's and the Chords bench's never
together), and removes its checkpoints once the sheet's chords are heard; a hearing that failed keeps them for Try
again, and the app sweeps those a day old as it starts. It asks for Android 13, 6 GB of memory and an arm64 processor
(the release; a debug build x86_64 too, for the emulator).

`ChordsEndToEndTest` runs it whole on the emulator: the models `device-test.sh` pushes installed by the phone's own
models' job (nothing asked of GitHub), the committed 20 s clip `tests/fixtures/autochords/hearing.mp3` staged and its
job queued, LRCLIB the fake sites server's scenario `chords`, which times the clip's song:

    android/scripts/device-test.sh --models --sites chords ChordsEndToEndTest

It asserts the job Ready, "chords over the lyrics", the sheet's chords at B1's WCSR against the computer's hearing of
the clip, LRCLIB's requests alone, and that killing `:ml` mid-job fails it in words while the library page answers. On
the emulator (2026-11-27): queued to Ready in 4.9-8.2 s, WCSR 1.0 (majmin and tetrads), beats F 1.0.

**Settings › Chords from audio** (`ChordModelsRow`) says where the models stand: "Not downloaded · 55 MB",
"Downloading · 21 of 55 MB", "Ready · 55 MB on the phone", "Not downloaded: why" (a phone that can't make chords, a
download that failed), or "Waiting for your go-ahead (a metered network)". Download asks first (the size still to
fetch: a file a failed download kept is none of it), then, on a metered network, again; then it queues the `models`
job and follows its line. Remove asks, then deletes `files/state/models/` (refused while a sheet is being made from
them). The debug build's Chords bench is the section's last button. `SettingsChordsTest` downloads the real files from
a GitHub of its own on loopback (CaracoleTestRunner's `Caracole.modelsForTests`, port 8746), sees the library page's
"+", then removes them:

    android/scripts/device-test.sh --models SettingsChordsTest

An audio file shared to caracole (a music app's or a file manager's Share) opens its page on the library screen, its
guess in Artist and Title, Make sheet and Cancel; share one at a time (`ShareAudioTest`).

The phone hears no words. Its job's Words step is skipped ("not transcribed here: the phone hears no words" where every
lyrics site missed), the Journal's Ready then says "Chords only, no lyrics.", and the song's card says "No lyrics site
has its words. The computer hears them from its own audio of this song." Its card's lyrics panel (Look them up under
another name) searches the three lyrics sites under the name you type and takes the row you pick, as on the computer
(`caracole lyrics --song --as`, `--record`, `--clear` on the phone's queue, LyricsRoutes); a pick lays the auto sheet
out again from what was heard, with no model. The audio never leaves the phone (in `files/state/audio/`, never synced);
the sheet syncs, naming the file, and the computer keeps it, unless it hears the words itself where every lyrics site
missed ([docs/autochords.md](../docs/autochords.md#on-the-phone)).

### Gate B2 on your phone

The library page offers the "+" once the chord models are installed (the audio routes; `AudioRoutesOnDeviceTest`,
through `device-test.sh --models`, uploads a clip over the app's own server and queues its sheet). Install a debug build
(`android/scripts/phone-install.sh`), download the chord models in Settings › Chords from audio, charge the phone
above 15 %, then on the library page tap "+", pick a song of yours whose lyrics LRCLIB has timed, and Make sheet.
The gate: from the tap to Ready, with "chords over the lyrics", within 90 s. The Journal's entry gives the job's
times; say the song's length and the phone.


`:autochords` makes the models' inputs from 22,050 Hz samples as the computer does: `Cqt.logFeatures(y)`, BTC's
log-CQT (btc.py's `cqt_features`: librosa 1.0's CQT in 10 s chunks, `[frames, 144]`), and `Mel.logMel(y)`,
beat_this's log-mel (torchaudio's `MelSpectrogram`, `[frames, 128]`). What they apply comes from Python, never
recomputed: `tests/conformance/data/caracole/autochords/frontend.json` holds librosa's CQT as it ran over a chunk,
step by step (its resamples, by `Soxr`, and each octave's STFT and sparse basis) and beat_this's window and
filterbank. `CqtTest` and `MelTest` hold them to the computer's features of the committed clips
(`vectors/autochords/frontend.jsonl`) by the design's gate, a cosine per frame (median ≥ 0.9999, least ≥ 0.999), and
print how close each came; the area runs on the emulator too:

    nix develop ./android -c gradle -p android :autochords:test
    android/scripts/device-test.sh --area autochords

## The Chords bench (debug build)

Gate B0 asks how fast the two models run on your phone, how hot it gets, how much memory and battery they take, and
whether their answers are the computer's. The debug build has a screen that measures it, run by hand: no test ever
runs on your phone. It runs the models over the computer's own features of each song (its CQT and its mel), since the
phone can't yet decode audio or compute them itself (stage B1). So its speed is the models' alone: the whole hearing
will add the decoding and the features' time. And its parity is frame for frame against the computer's outputs;
chord-by-chord scores (WCSR) come with the labels, in B1.

It runs in sessions: one model on one thread count and memory setting, over every file. Each session runs in a fresh
process, so that its memory is its own; starting one costs a second or two. Each session in the report names its process
(`pid`) and says whether it was `fresh` (no earlier session's process still up). A session writes what it measured after
every run, so whatever ends it (Stop, a crash, Android killing it, a hang) loses only the run in flight. One that writes
nothing for longer than a run of its could take (four times the audio of the run in flight, 5 minutes at least), or
whose run in flight doesn't end within a minute of Stop, is given up, its finished runs kept. What you see for each
ending: A session loads its model first and times the load apart. Each run's `rss_peak_mb` is its true peak (the
process's peak memory, reset as the run begins), or null with `"reset": false` where the phone refused the reset.
`pss_peak_mb` is sampled once a second: a run of BTC lasts about a tenth of that, so its PSS is a reading taken around
the call.

- **Stop**: the session ends after its run in flight (given up after a minute, that run left out), with `stopped`
  "stopped by the owner (Stop)", and no other session starts.
- **Too hot**: when the phone's thermal status reaches critical, the session stops before its next run, with `stopped`
  "the phone's thermal status reached critical", and the bench stops after it: let the phone cool.
- **A hang**: a session given up for writing nothing has `failure` "no word from the session for N minutes: given
  up…", and the bench goes on to the next session.
- **A process that died**: `failure` "the session's process died before its end" (with ": Android killed it for
  memory" when Android's own record says so), and the bench goes on to the next session.

In each case the session's finished runs are kept, and it has no trusted hearing peak (`complete: false`), so its
setting's `memory_ok` is null, or false when it ran out of memory.

1. **Install the debug build**: `android/scripts/phone-install.sh` (above). The APK is about 98 MB, the runtime's
   libraries most of it; it holds no model file.
2. **Make a folder on the computer** with the model files and a few of your songs' references, from the repository's
   root:

       mkdir -p ~/caracole-bench
       cp "$(nix build .#chord-models --no-link --print-out-paths)"/*.{pt,onnx} ~/caracole-bench/
       nix develop .#autochords -c python -m tests.helpers.autochords_reference ~/some-songs ~/caracole-bench

   The second command writes one `.json` a song: what the computer's models made of it. Five songs are enough for
   B0; a reference keeps the decoded audio too, about 40 MB for four minutes. The model files are 138 MB. A
   reference whose decoded length, mel and duration disagree by more than 0.1 s is not written: the command names
   it and exits 1; the bench, given an older one whose duration its mel disagrees with, times it by the mel and says
   so in its log and the report's `length_flags`. A reference is named after its audio, with each character the phone's shared storage refuses (a colon, and
   `*?"<>|\`) made a hyphen: `adb push` can't copy a file whose name holds one ("remote couldn't create file"), so
   a file you rename yourself must keep them out too.
3. **Copy it to the phone**: `adb push ~/caracole-bench /sdcard/Download/` (add `-s SERIAL` as above).
4. **Open the bench**: Debug caracole › Settings › Chords bench. Pick the folder (Download › caracole-bench, then Use
   this folder and Allow). The first Start checks the model files against their pins and copies them into the app's
   own storage, which takes a minute.
5. **A short run first**: untick "then the same runs again with the screen off" and the folder's references, set the
   passes to 1, and press Start: a few minutes over the committed clips, to see parity on your phone.
6. **The gate's minimum next**: unplug the phone; tick beat_this fp16 alone, 4 threads alone, the arena off alone,
   the folder's references and the screen-off round, untick the clips; 5 passes. That is two sessions (screen on, then
   off), each 5 songs × 5 passes. For five songs of 4 minutes, a session is 100 minutes of audio × the RTF: about 10
   minutes at RTF 0.1, 25 at 0.25. So 20 to 50 minutes in all.
7. **The whole matrix, as time allows**: the defaults (BTC, both beat files, 2 and 4 threads, the arena off and on,
   5 passes, the screen-off round, clips and references). The screen stays on for the first round; when it says so,
   turn the screen off with the power button and leave the phone alone for the second round. It is 16 beat_this
   sessions (2 files × 2 thread counts × 2 arena settings × 2 rounds) of 100 minutes of audio each, BTC's a few
   seconds: about 160 minutes at RTF 0.1 and over 6 hours at 0.25, more if 2 threads are slower. Untick what you
   don't need. The notification and the screen say what runs, and Stop keeps what was done.
8. **Bring the report back**: it is `caracole-bench-<UTC time>.json` in the same folder, rewritten after each
   session: `adb pull /sdcard/Download/caracole-bench/caracole-bench-….json`. It says your phone's model, its
   SoC, its Android version, the app's version and the files' names, nothing else of yours.

What Gate B0 reads in it:

- `summary.references`: for each model, thread count, arena setting and screen state, your songs' warm runs'
  `rtf_median` and `rtf_max` (the model's seconds over the audio's), with `speed_ok` when `rtf_max` is 0.125 or less.
  `memory_ok` is true when `rss_hearing_mb` is 1 GB or less: the highest whole-life peak of that setting's sessions,
  each a fresh process holding the model's load, its first inference and every run after, as a hearing on the phone
  would (its clips included). It is null when no whole hearing was measured, and `memory_note` says why: a session that
  failed or was stopped before its planned runs were done (`sessions[].failure`, `sessions[].stopped`, and `complete:
  false`: an error, a dead process, the heat guard, your Stop, a hang), or one whose process wasn't fresh
  (`sessions[].fresh`). It is false when a session ran out of memory (`out_of_memory: true`): Java's OutOfMemoryError,
  ONNX Runtime's "Failed to allocate memory", or Android's own record that it killed the process for memory.
  `summary.gates` gives the limits it is held to. Beside it, `rss_steady_mb` is the warm runs' highest true peak, the
  load left out. A beat_this that can't reach RTF 0.25 stops stage B. `summary.clips` gives the same numbers for the
  committed clips, with no gate: they are parity's, and a short clip's chunk overhead is no measure of a song. Both
  leave each session's first run out (`cold`: its first inference warms the runtime), so a bench of 1 pass over a single
  file has an empty block, and a `references_note` or `clips_note` beside it says why.
- `parity.pass`: BTC's chords the computer's frame for frame but where the computer itself was within 0.001 of a tie,
  beat_this fp32's logits within 0.001, and the fp16 file's beats and downbeats at F ≥ 0.99.
- `runs`: each run with its `thermal` states, its `headroom_max` (read at most every 10 s) and its `battery_uah`
  change; `sessions`: each session's `load_seconds`, its process's peak, its battery change, and a `failure` or
  `stopped`; `battery`: the whole bench's. A negative battery change is drain. Together, how hot songs back to back
  make the phone, and what they cost.

Which beat file, how many threads and which memory setting ship are yours to choose from it (the design's §11). To
free the room afterwards, delete the folder; the app's own copy of the models goes with the debug app's data
(`adb shell pm clear --user 0 io.github.danielhp95.caracole.debug`, its library too).

### Gate B1: your songs heard whole

Gate B1 asks whether the phone's whole hearing (decode, mixdown, resample, the CQT and BTC, the mel and beat_this)
gives your songs the computer's chords and beats: WCSR ≥ 0.99 (majmin) and ≥ 0.98 (tetrads), beats and downbeats F ≥
0.99 within 0.07 s after the first 5 s, every threshold read from the hearings' `meta.json`. The bench's Hear the
songs (B1) button runs it.

1. **The computer's hearings**, from the repository's root, of the same songs you bring:

       nix develop .#autochords -c python -m tests.helpers.autochords_reference --hearings ~/some-songs \
           ~/caracole-bench/hearings

   It writes `meta.json` and one `<name>.hearing.json` a song, a few KB each; one whose lengths disagree is not
   written, and the command says which.
2. **The folder**: put the songs themselves in `~/caracole-bench` beside the model files (any name: a song is found
   by its bytes too), the `hearings` folder in it, and `adb push ~/caracole-bench /sdcard/Download/`.
3. **Run it**: Debug caracole › Settings › Chords bench, the folder as before (Download › caracole-bench), then
   **Hear the songs (B1)**. Each song is heard whole in a fresh `:ml` process, the screen kept on; a few minutes a
   song.
4. **The report**: `caracole-bench-<UTC time>.json` in the folder, its `hearings`: `gates`; `files`, a song each (its
   WCSR and F against each threshold, `failures`, `pass`, the samples and frames each model read beside the
   computer's, `frames_differ` and where, `seconds`, `rtf`, `stages_seconds`, `ml_peak_mb`); `over_all` (`pass`,
   each score's least and its mean by length, `rtf_max`, `ml_peak_mb_max`); `unmatched`; and `pass`.
## YouTube on the phone: the engine

A song's audio from YouTube on the phone runs yt-dlp itself, in Python, inside the app: `:youtube`, Chaquopy's Python
3.13 with yt-dlp and yt-dlp-ejs, linked into both builds (stage Y5.1), the release's for arm64-v8a alone: an x86_64
phone of the release gets no yt-dlp (`PhoneYouTube`, `BuildConfig.YOUTUBE_ABIS`) and says "this phone's caracole has
no yt-dlp".

Every piece is pinned in `youtube/pins.json`: Chaquopy's version (its Gradle plugin and its Python runtime, from Maven
Central), the Python minor version, the two pure wheels by URL and SHA-256, and QuickJS-NG's source for the JavaScript
challenges, by its tag's commit and the NAR hash of its tree (`fetchFromGitHub`'s; never GitHub's generated archive,
whose bytes have changed before). `flake.nix` reads it: it fetches the wheels into one folder, `CARACOLE_YTDLP_WHEELS`,
QuickJS-NG's tree into `CARACOLE_QUICKJS_SRC`, and puts `python3.13`, Chaquopy's `buildPython`, on PATH. pip installs
the two wheels from that folder alone, `--no-index --no-deps`: none of `yt-dlp[default]`'s native packages, no FFmpeg.
A build of `:youtube` without any of them fails, naming it (its `checkEngine` task); the other modules build without
them. The flake reads only
files git tracks: `git add` a changed `pins.json` before building. To move yt-dlp, run `bump-ytdlp.sh` ("A release
when YouTube changes"): it changes its pin and the yt-dlp-ejs version its wheel's `METADATA` requires (`PinsTest`
checks both).

`caracole_ytdlp.py` is the glue: `version()` says the Python, yt-dlp and yt-dlp-ejs it runs, and `run(argv, out, err)`
is one yt-dlp run, `yt_dlp.main` with `sys.stdout` and `sys.stderr` line-buffered into two files and its exit status
returned, never raised: anything that goes wrong under it is its traceback in the err file and status 1, as the
computer's yt-dlp process says it (`GlueTest` runs it with the shell's python3.13). One run a process: yt-dlp keeps
module state. Its own code ships as source, the wheels and the standard library compiled. Chaquopy already leaves out
the standard library's `tkinter`, `idlelib`, `test`, `ensurepip` and `pydoc_data` (3.13 has no `lib2to3`), and has no
setting to leave out more. On the emulator alone, with no network:

    android/scripts/device-test.sh --youtube

runs `YtDlpVersionTest` and `QjsTest` from `:youtube`'s own test APK (under `YoutubeTestRunner`,
`caracole.network=loopback`): Python starts, `version()` is `pins.json`'s, yt-dlp's own `--version` prints the pinned
one, and none of those modules is there; qjs is executable in the native library folder, says the pinned version and
runs a script, and yt-dlp, told of it alone (`--no-js-runtimes --js-runtimes quickjs:<path>`), names it among its
runtimes (its `-v` with no URL: the header, then its usage error, no request). `release-check.sh` checks the release
holds no `libpython*`, `libchaquopy_java.so`, `lib*_python.so` or `lib*_chaquopy.so`, no class under `com/chaquo/` and
nothing under `assets/chaquopy/`, with the debug build as the control. No route runs it yet.

Each yt-dlp run is a process of its own, `:youtube` (`YtDlpService`), as the computer runs a fresh `yt-dlp`:
`YtDlpClient` binds it, sends the argv, the main process's mode (`caracole.network`, as `LOOPBACK` or `NETWORK`; a
client of another process is given its gate's: that process has no test runner to set it, and refuses any other
value) and the run's own two folders (its cache and a download's, which the service checks are in the app's storage
with no link), follows yt-dlp's stderr line by line, and once it is answered the service kills its process; one
request a process, none run once its client let go, and one run at a time across the app's processes (a file lock, a
client that can't take it starting and killing nothing: "another run is going"). The environment is built from nothing (`Env`: `HOME` and `TMPDIR` of the app's own, `LANG`, `PATH`, no proxy
variable). The service runs an argv only as one of the phone's own templates (youtube.json's `phone_argv`) reads to
yt-dlp's own option parser: each option a template sets with its value, or a value its placeholder's check passes
(the gate's `--proxy` shape, the app's qjs, the run's own folders, a search of the phone's 8 results or a video on the network and
a 127.0.0.1 or 10.0.2.2 address under `LOOPBACK`), every other at its default; under `LOOPBACK` the tests' own forms
too (`--version`, `--no-check-certificates`, `-v`, KillTest's one `--exec`). So a test can't reach a real host through
it, and no argv runs a command, loads a plugin, reads cookies or writes outside the app. A timeout, a cancel or a close
kills the `:youtube` process (found by its name when its pid hasn't come yet), and Android kills what it started with
it (qjs among them: measured, nothing of the app's uid left 2 s after); one killed from outside is "yt-dlp stopped (the
phone may have run out of memory)". `GateService`, in the main process, gives another process of the app a gate there.

Two cautions for what builds on it. Never kill a process group: every process of the app's uid, the main one
included, shares one (zygote's). And yt-dlp's `-v` prints its proxy map, the gate's secret in it: `YtDlpClient` redacts
any gate-shaped address (however the argv spelled its `--proxy`: yt-dlp takes `--prox` too) from every line and the
output it gives back, but a bench or a debug run that adds `-v` must keep those `[debug]` lines out of every log,
report and screen but through it.

`YtDlpServiceTest`, `KillTest`, `GateServiceTest` and `AcrossProcessesTest` (`device-test.sh --youtube`) download a 6 s clip of the tests' own (made from
`tests/helpers/synth_music.py`, CC0) from a server of the test's on 127.0.0.1, by plain HTTP and by HTTPS, through the
gate: on the x86_64 emulator the process starts about 0.1 s after the bind, Python is ready with yt-dlp imported at
0.6–0.8 s, a `--version` run takes 0.7–0.8 s whole, and the clip's download 4.6–5.7 s (yt-dlp's own pause before a
download, 2.5–5 s, among it).

yt-dlp solves YouTube's player challenges in JavaScript, with QuickJS-NG's `qjs` (v0.18.0, MIT): no prebuilt Android
binary exists, so `youtube/native/CMakeLists.txt` builds it by the NDK for both ABIs (upstream's `qjs` command: the
engine, its libc and `qjs.c`, with the REPL's and standalone's bytecode upstream commits in `gen/`, so no host `qjsc`
step), with libsoxr's reproducibility flags and 16 KB pages, as a position-independent executable named `libqjs.so`.
Android runs no program an app writes, only one from its native library folder, where the package manager extracts the
APK's `lib*.so` when the build asks for it: `useLegacyPackaging`, every build's (`app/build.gradle.kts`, and
`:youtube`'s test APK). That applies to every native library, not qjs alone: ONNX Runtime's, SQLite's, Python's and
libsoxr are then compressed in the APK and extracted again at install, which costs the compressed copies, 21.0 MB on
arm64 (24.7 MB on x86_64). The two-ABI debug APK goes from 140.0 to 74.8 MB and installs smaller (126.0 MB on arm64,
134.8 MB on the x86_64 emulator, from 140.0), `libqjs.so` 1.2 MB of it an ABI. `Qjs.path(context)` is where it is;
yt-dlp runs it with `--script FILE` for each challenge and `--help` to read its version, each with its output piped
back, never onto the app's own descriptors. `release-check.sh` checks the release holds `lib/arm64-v8a/libqjs.so` and
no x86_64 one, and extracts its native libraries at install. QuickJS-NG's `LICENSE` (MIT, Fabrice Bellard, Charlie
Gordon, Ben Noordhuis, Saúl Ibarra Corretgé), which its `libregexp`, `libunicode` and `dtoa` sources repeat, is
`assets/licenses/youtube/quickjs-ng-LICENSE`.

It costs the debug APK 45.0 MB, both ABIs (26.3 MB of an arm64-only APK): Python's native libraries 12.3 MB an ABI, the
standard library and Chaquopy's bootstrap, the CA bundle and yt-dlp 10.8 MB for both. The licences of what ships with
it are the APK's assets `licenses/youtube/` (the design's §3.6; `youtube/licenses/README` says which is whose): CPython
3.13.16's LICENSE and Doc/license.rst (PSF-2.0, with what it incorporates), Chaquopy's (MIT), OpenSSL 3.5.9's
(Apache-2.0), libffi 3.4.4's, bzip2 1.0.8's and xz 5.4.6's, each that project's text at the version Chaquopy's Python
is built with (CPython's `Android/android.py`; SQLite is public domain, zlib Android's own), certifi's (MPL-2.0, its CA
bundle's), all kept in `youtube/licenses/`; and, copied at build time from the pinned wheels and source (`:youtube`'s
`copyLicences`), yt-dlp's and yt-dlp-ejs's (Unlicense), the notice yt-dlp-ejs's `lib.min.js` begins with (its bundled
meriyah, ISC, and astring, MIT) and QuickJS-NG's. Setuptools' (MIT) and pyelftools' (public domain) are in Chaquopy's
bootstrap beside their code. The app's `NoticesTest` holds each to its source, and (`gradle :app:apkScan`,
release-check.sh's) both APKs to that folder.

## A sheet from a YouTube video

Paste a video into the library page's request form (its YouTube field), or into a song card's From a YouTube video
and press Make sheet, or share a YouTube link to the app and press Make its sheet from this video: the phone takes the
video's audio with its yt-dlp, asks the lyrics sites for the words, hears the chords with its own models and keeps the
sheet, then lets the audio go. Nothing downloads before you press the button. A video pasted into the search box shows
its title and thumbnail first: one yt-dlp run of its metadata, one request for the picture. It works on Wi-Fi or
mobile data, on YouTube's terms as the computer keeps them (AGENTS.md, "The one exception is YouTube"): within
YouTube's budget of 50 runs, one run at a time, a pause between two, a block honoured with no retry, audio alone.

Settings' **YouTube audio** row says where it stands: "On · yt-dlp 2026.11.23 · 2 runs in the last 24 hours", "Off
(the computer's settings)", "Needs the chord models", "Cooling down until …" or "Out of date: …" (`YouTubeRow`); a
build without yt-dlp has no row. When it says out of date, see [A release when YouTube
changes](#a-release-when-youtube-changes).

`YouTubeEndToEndTest` runs it whole on the emulator, with the real models and a yt-dlp of the test's own
(`Caracole.youtubeForTests`: its one download the committed clip, `tests/fixtures/autochords/hearing.m4a`, nothing
sent to YouTube) and LRCLIB the fake sites':

    android/scripts/device-test.sh --models --sites chords YouTubeEndToEndTest

It asserts Ready, "chords over the lyrics", requests to LRCLIB and the test's yt-dlp alone, the audio gone after Ready,
and the Settings row's line.

## The YouTube bench (debug build)

Gate Y0 asks whether yt-dlp works on your phone: whether YouTube answers it, how long the player's challenge takes on
QuickJS, how much memory and how many bytes a song costs, which hosts it asks. The debug build has a screen that
measures it, run by hand, a few songs at a time. No test runs on your phone, and no test reaches YouTube: on the
emulator the bench reaches a loopback clip alone (`YouTubeBenchTest`, `device-test.sh --youtube`).

It keeps the owner's terms by itself, on the phone's own records. Every run of the phone's counted (kv `ytbench:runs`
and the `events` rows of provider `youtube` of the last 24 hours, the larger): each run reserves its slot in the main
process before its gate opens, so it counts whatever ends it, and only a run that never started gives its slot back; a
clock set back only counts more runs, never fewer. Its cap, YouTube's budget (50 runs in any 24 hours since
2026-11-27, 6 before), is lifted while the feature is
developed, the owner's word of 2026-11-27 ("ignore the run limits while developing this feature. as connection is
patchy"): no count refuses a session, the screen says the count and that there is no daily limit, and the report's
`budget` says `lifted`; `DbLedger.DAY_CAP_LIFTED = false` puts it back (a session that would pass the cap then refused,
saying how many runs are left). The computer's pause between runs (3.75–7.5 s, and after the phone's last run, kv
`http:last_request:youtube`). One run at a time (the client's lock, across the app's processes) and one session at a
time. A block honoured: recorded as the runner records one, the session stops, and none starts until the cooldown
ends. YouTube turned off, no session. Each song is a search (`ytsearch8:`), the computer's `choose`, and a download,
or a download alone for a video id; yt-dlp's cache is emptied as a session starts, so the first download solves the
player cold and the others warm, and each download is deleted once measured. Runs add `-v` (the service's leave for
the bench under the network): what the screen and the report keep came back from the client, the gate's secret taken
out, and no `[debug]` line.

The screen (`YouTubeBenchActivity`) runs in a process of its own, `:ytbench`, which never starts Python: its runs are
`:youtube`'s, its gates and its record of runs the main process's (`GateService`, `YouTubeBenchLedger`). On your phone
a session starts by a tap alone. Start enforces YouTube's hosts; Start, observing every host logs every host the run
asks but reaches no address that isn't public (`jnn-pa.googleapis.com` still refused), and is that button's alone. The
kill check runs at the end of every session, on your phone too, and never leaves it: a trickled download from a small
server inside the bench, through a gate that can reach 127.0.0.1 alone, stopped 2 s in, then no `:youtube` or qjs
process may be left and the next run must work. It spends none of the day's runs.

What three songs can't show: a success rate, how the timings spread across player versions, and what YouTube does
after days of a phone asking. `after_block_requests` is 0 by construction (a session stops at a block): it says the
bench sent nothing after one, not how YouTube treats the phone afterwards.

1. **Install the debug build**: `android/scripts/phone-install.sh` (above), and leave the app otherwise idle (no sync,
   no library page open: the report's `idle` says whether it was).
2. **Open the bench**: Debug caracole › Settings › YouTube bench. It says how many runs the last 24 hours held (no
   daily limit while the feature is developed).
3. **Type or paste up to three songs**, a line each: "Artist - Title", the artist first (AC/DC's slash is fine;
   quotes around a line are taken off), or a YouTube video id. Three songs are six runs. A search no video fits says
   the artist and the title it looked for, and the bench asks nothing more for that song. A session lost to the
   network (an error, no block) may be run again the same day: the cap is lifted; a block still ends the day's
   sessions until its cooldown ends.
4. **Tap Start** on mobile data (enforce), or **Start, observing every host** on Wi-Fi. Keep the screen open until it
   says `report:`; a session started again while one runs is refused.
5. **Bring the report back**: `caracole-ytbench-<UTC>.json` (§4.3 of the design: the device and the app, the pins as
   the running code reports them, the network's kind, `idle`, the day's runs before and after, each run's timings,
   challenge, sleeps and pause, clients, outcome, ERROR and WARNING lines, hosts and bytes, PSS, and a download's file
   and what MediaCodec decoded of it; the kill check; `summary`, each gate's numbers). The folder's files, into a
   folder outside the repository (nothing recorded of YouTube is committed). `…/ytbench/.` pulls its files, so a
   second day's pull into the same folder doesn't nest, and each report, kept on the phone, lands there once:

       mkdir -p ~/ytbench
       adb -s SERIAL pull /sdcard/Android/data/io.github.danielhp95.caracole.debug/files/ytbench/. ~/ytbench/

   It names your songs as typed, nothing else of yours.

### The sessions of Gate Y0

Sessions by hand, as many as you like, only when you say so: no one else starts one, and none starts by adb. What the
gate needs now (the controller's ruling of 2026-11-27, after the owner chose several short sessions a day):

- **On mobile data, Start** (enforce): at least three songs downloaded over any sessions, and at least one warm
  download, the second song's of a session: so run **two or three songs in one session**.
- An observed session (**Start, observing every host**, Wi-Fi alone) is wanted, not needed: an enforcing gate logs
  every host asked and every refusal. Enforcing on Wi-Fi is fine too. Two days aren't needed either: the days are
  reported, and what one day can't show is what YouTube does after days of a phone asking.
- A session the network lost (every run an error of a timeout's or a transport's, no block) counts for nothing: run it
  again. So does a song the network failed inside a session; the checker lists it by session and song, with its
  reason.
- A block, or a song failing for another reason, holds the gate until a later session, on a later day after any
  cooldown, on mobile data with Start, downloads its songs with no block and none failing: that clears it (the checker
  names it as cleared), and the three songs and the warm download are counted from the sessions after it. Blocked or
  failing on Wi-Fi on two days with no clean day after is §3.8's trigger, if the computer's yt-dlp worked on the same
  Wi-Fi the same hour (no report says: check it).
- The warm download must be one on mobile data with Start; each cold and warm limit is still checked wherever it was
  measured.
- Every run counted, any session's, and the optional Termux smoke test's (Y0.0, the design's §4.0) too, which the bench
  can't see. No daily cap while the feature is developed (the owner's word of 2026-11-27, above); a report written
  before it, which says no `lifted`, is still held to the cap it kept (its budget's `of`: six) in any 24 hours.
- Each session by a tap on Start, the app otherwise idle (no sync, no library page open).

Then pull the reports (step 5, the same folder) and, from the repository's root, give the checker all of them:

    nix develop -c python -m tests.helpers.ytbench_gate [--apk-growth-mb N] ~/ytbench/caracole-ytbench-*.json

It says the sessions and days given, each row of §4.4 (Y0-W works … Y0-C start; a run's error said with its reason, a
session lost to the network apart from a block) and the owner's terms (the cap a report kept, its `of`, in any 24
hours by the runs' own stamps for a report without `lifted`, the busiest 24 hours said where the cap was lifted,
nothing after a block, no
session observing every host but on Wi-Fi, a kill check that spent none, no host outside YouTube's reached, no proxy
secret in a report): PASS, FAIL or UNDECIDED, the numbers and what is missing or what to run next, then how often an
observed session asked `youtubei.googleapis.com` (the controller decides it), then the whole verdict. It exits 0 only
when every gate passed, 1 for a fail, 2 for undecided or a report that won't read. Y0-S is no report's:
`--apk-growth-mb` gives the release-equivalent arm64 APK's growth.

A run's `uid_bytes` are TrafficStats' bytes of the app's uid, loopback too (the report's `uid_counts`): yt-dlp's bytes
to the gate on 127.0.0.1 are counted sent and received, and the gate's on the network once, so a run counts about 3.1
times the gate's bytes (the phone's numbers; `YouTubeBenchTest` measures a loopback byte counted twice). Y0-H holds
them to three legs of the gate's bytes, 8 % more for headers and retransmits, and 64 KB a run: a bypass of the gate
would show as bytes the gate never saw, unless it stayed under about a sixth of the gate's bytes and 64 KB a run. The
bytes are judged over the idle sessions alone (at least one on mobile data with Start holding a download); a session
not idle is set aside from them, named, and counts everywhere else.

Three songs show no rate: what they can't decide is UNDECIDED, and the answer is more songs and, in time, more days.

## YouTube's gate

A song's audio from YouTube, on the phone, comes from yt-dlp run inside the app, reaching the network only through a
proxy of the app's own, `core.youtube.HostGate`: on 127.0.0.1 at a port of its own, with a user and a secret made for
each run (its `--proxy`). It tunnels a CONNECT on port 443 to `youtube.com`, `www.`, `m.`, `music.` and
`consent.youtube.com` and any `*.googlevideo.com`, and to nothing else: any other host gets 403, and
`jnn-pa.googleapis.com` (Google's attestation) is refused by name whatever the rule. It logs each host asked for, its
connects, its bytes each way and its refusals, `consent.youtube.com` and `redirector.googlevideo.com` apart. A listed
name that resolves to a loopback, private, link-local, shared or multicast address is refused too. A client that hasn't
sent its whole request 15 s after connecting is closed, and so is a tunnel in which nothing moves either way for two
minutes. Under `caracole.network=loopback` (tests and the emulator's) it allows `127.0.0.1` and `10.0.2.2` alone, and
looks nothing up. It is a check and a measurement: only yt-dlp's argv sends it through the gate.
