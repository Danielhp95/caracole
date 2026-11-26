{
  description = "caracole's Android app: the shells that build it, and one that runs it on an emulator";

  # The nixpkgs of caracole's own flake (../flake.nix), so one copy serves both.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/55bfb4d7437bd4e09ab7cba58a43bd68eb310044";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        # The Android SDK is unfree, under Google's licence, accepted here.
        config = { allowUnfree = true; android_sdk.accept_license = true; };
      };
      inherit (pkgs) lib;

      # What app/build.gradle.kts compiles against: they change together.
      platformVersion = "36";
      buildToolsVersion = "36.0.0";
      # What ml/build.gradle.kts's externalNativeBuild names: they change together.
      ndkVersion = "28.2.13676358";
      cmakeVersion = "3.31.6";

      sdkFor = emulator: pkgs.androidenv.composeAndroidPackages ({
        platformVersions = [ platformVersion ];
        buildToolsVersions = [ buildToolsVersion ];
        # The NDK and CMake build libsoxr for the phone's ABIs (autochords/native/, ml/build.gradle.kts's
        # externalNativeBuild): r28c, which ml/build.gradle.kts's ndkVersion names too.
        includeNDK = true;
        ndkVersions = [ ndkVersion ];
        includeCmake = true;
        cmakeVersions = [ cmakeVersion ];
        includeSources = false;
        includeEmulator = emulator;
        includeSystemImages = emulator;
      } // lib.optionalAttrs emulator {
        # The emulator the end-to-end test passed on, with -gpu host: its software renderers, and 37.1.11's
        # (the repo's "latest"), crashed in the emulator's render thread (README.md).
        emulatorVersion = "37.2.4";
        systemImageTypes = [ "google_apis" ];
        abiVersions = [ "x86_64" ];
      });

      # alphaTab's three files (../nix/alphatab.nix, the computer's own fixed-output fetch), for the Guitar Pro
      # page's assets and the tests that read them (lane guitar-alphatab).
      alphatab = pkgs.callPackage ../nix/alphatab.nix { };
      # BTC's graph and weights and beat_this's two graphs (../nix/autochords-onnx.nix, the computer's
      # `.#chord-models`), which :ml's ModelParityTest runs on the emulator (scripts/device-test.sh --ml): in the ml
      # shell alone, so the other shells never build them (torch exports them).
      chordModels = pkgs.callPackage ../nix/autochords-onnx.nix { };
      # yt-dlp and yt-dlp-ejs, the two pure wheels of youtube/pins.json (the one place they are pinned), each fetched
      # by its URL and SHA-256 (fixed-output) into one folder, CARACOLE_YTDLP_WHEELS, from which :youtube's pip
      # installs them, `--no-index --no-deps` (youtube/build.gradle.kts).
      pins = builtins.fromJSON (builtins.readFile ./youtube/pins.json);
      ytdlpAndroid = pkgs.linkFarm "caracole-ytdlp-wheels" (map (pin: {
        name = baseNameOf pin.url;
        path = pkgs.fetchurl { inherit (pin) url sha256; };
      }) [ pins.ytdlp pins.ejs ]);
      # Chaquopy's buildPython (:youtube's pyc and pip) must be the app's Python's minor version, pins.json's.
      python = pkgs."python${lib.replaceStrings [ "." ] [ "" ] pins.python}";

      # Headless: the full jdk17 links gtk3, which brings nixpkgs' libsqlite3, whose sqlite3_* symbols then
      # silently take the place of the bundled SQLite's (core's DatabaseTest asserts sqlite_source_id()).
      jdk = pkgs.jdk17_headless;
      # Gradle from nixpkgs, not a wrapper's download: pinned with the rest, run on the JDK above.
      gradle = pkgs.gradle_8.override { java = jdk; };

      shellFor = emulator:
        let
          sdk = (sdkFor emulator).androidsdk;
          home = "${sdk}/libexec/android-sdk";
        in pkgs.mkShell {
          # The host's CMake and gcc build the same libsoxr for the JVM's tests (autochords/build.gradle.kts's
          # hostSoxr task); qemu's user-mode emulators run the NDK's static arm64 build of it there
          # (SoxrArm64Test), so the phone's engine is measured on this machine, never on a phone.
          packages = [ jdk gradle sdk pkgs.cmake pkgs.gcc pkgs.qemu-user python ];
          JAVA_HOME = jdk.home;
          CARACOLE_ALPHATAB_DIR = "${alphatab}";
          CARACOLE_YTDLP_WHEELS = "${ytdlpAndroid}";
          ANDROID_HOME = home;
          ANDROID_SDK_ROOT = home;
          # The Android Gradle plugin fetches aapt2 from Maven, a binary NixOS can't run:
          # build-tools' copy, patched for Nix, instead.
          GRADLE_OPTS = "-Dorg.gradle.project.android.aapt2FromMavenOverride=${home}/build-tools/${buildToolsVersion}/aapt2";
          shellHook = lib.optionalString emulator ''
            export PATH="${home}/emulator:${home}/platform-tools:$PATH"
          '';
        };
    in {
      devShells.${system} = {
        # Builds and tests the app: `nix develop ./android -c gradle -p android assembleDebug`.
        default = shellFor false;
        # The same, with the emulator and an Android ${platformVersion} system image (x86_64, Google APIs).
        emulator = shellFor true;
        # The emulator's, with CARACOLE_CHORD_MODELS: the models' folder, for `scripts/device-test.sh --ml`.
        ml = (shellFor true).overrideAttrs { CARACOLE_CHORD_MODELS = "${chordModels}"; };
      };
    };
}
