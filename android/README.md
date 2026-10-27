# caracole for Android

A small app that keeps a copy of your caracole library on the phone and shows it with no network: the library
page, every sheet in caracole's own viewer (key, capo, chord diagrams, harmony, pinyin, strum), the songbooks,
and the PDFs. It shows the pages caracole writes into the library as they are. When caracole is upgraded, the
pages change with it, and the app doesn't need an update.

It connects to `caracole serve` at the address you type, downloads what serve lists at `GET /api/offline`, and
keeps it in the app's own storage. Each file is stored once, under its SHA-256. A sync downloads only what
changed. It checks each file's size and hash, and it swaps the new list in whole, so a sync cut short leaves the
copy you had. The app is read-only: it never writes to the library.

## Build

From the repository's root, with Nix:

    nix develop ./android -c gradle -p android assembleDebug

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`. `android/flake.nix` provides JDK 17, Gradle and
the Android SDK (platform 36, build tools 36.0.0) from caracole's own nixpkgs. The build uses that pinned Gradle
rather than a Gradle wrapper, which would download a second copy. The flake also points the Android Gradle
plugin at the SDK's aapt2, because NixOS can't run the copy the plugin fetches from Maven. The first build
downloads the plugin and the libraries from Google's Maven and Maven Central.

The sync engine's tests run on the JVM, against a fake caracole serve:

    nix develop ./android -c gradle -p android :mirror:test

## Install

- With USB debugging on: `adb install android/app/build/outputs/apk/debug/app-debug.apk`.
- Or copy the APK to the phone and open it there. Android asks you to allow installs from that app (Files, say)
  once.

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
menu (⋮) has Sync now, Library and Settings.

## Offline

What works with no network:

- The library page: filters and search over your own songs.
- Each sheet viewer: transposition, capo, mode, diagrams, the harmony panel, pinyin and strumming.
- Kept versions' pages and songbook pages.

A PDF, a ChordPro file or a Guitar Pro file opens in another app on the phone. Android asks which app when more
than one can open it, and the app says so when none can. Links to Ultimate Guitar, MuseScore and other sites
open in the browser.

What doesn't work offline: anything that needs caracole serve. That means searching the sites, adding or fetching
songs, Export PDF, and choosing versions. Use caracole serve in a browser for those.

The viewers run sandboxed, with the same Content-Security-Policy and sandbox headers caracole serve sends.

## Try it on an emulator

`nix develop ./android#emulator` adds the emulator, `adb`, `avdmanager` and an Android 36 x86_64 image:

    avdmanager create avd -n caracole -k "system-images;android-36;google_apis;x86_64" -d pixel_6
    LD_LIBRARY_PATH=/run/opengl-driver/lib emulator -avd caracole -gpu host

Use `-gpu host`. With the software renderers (`swiftshader_indirect`, and the lavapipe fallback of `-gpu guest`),
emulators 37.1 and 37.2 crashed in their own render thread when the WebView went back a page. On the emulator,
the host's `127.0.0.1` is `10.0.2.2`. The instrumented test syncs from a running caracole serve, opens the
library page and a viewer, transposes, and hands off a PDF and a Guitar Pro file:

    nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest
    adb install -r -t android/app/build/outputs/apk/debug/app-debug.apk
    adb install -r -t android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
    adb shell am instrument -w -e server http://10.0.2.2:8737 \
        io.github.danielhp95.caracole.test/androidx.test.runner.AndroidJUnitRunner
