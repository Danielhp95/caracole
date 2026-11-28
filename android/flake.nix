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
      # BTC's authors' weights (../nix/autochords.nix, the computer's own fixed-output fetch of their file), for
      # core.models' ModelFilesTest: its SHA-256 and the ranges BTC's graph reads in it.
      autochordsFiles = pkgs.callPackage ../nix/autochords.nix { };
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
      # QuickJS-NG, yt-dlp's JavaScript runtime on the phone, pins.json's tag by its commit and the NAR hash of its tree
      # (never GitHub's generated archive's bytes): CARACOLE_QUICKJS_SRC, which youtube/native/CMakeLists.txt builds by
      # the NDK into `libqjs.so`.
      quickjsSrc = pkgs.fetchFromGitHub { inherit (pins.quickjs) owner repo rev hash; };
      # Chaquopy's buildPython (:youtube's pyc and pip) must be the app's Python's minor version, pins.json's.
      python = pkgs."python${lib.replaceStrings [ "." ] [ "" ] pins.python}";
      # ONNX Runtime 1.27.1 built from its source for arm64-v8a and x86_64 (../nix/onnxruntime-android.nix), an AAR in
      # a Maven folder of its own, which settings.gradle.kts reads as $CARACOLE_ONNXRUNTIME for :ml in Maven Central's
      # place: in the ml shell alone, so the other shells build and test everything but :ml with no ONNX Runtime. Built
      # once a machine (about 20 min, at most 8 compile jobs), then the store's, kept by the ml shell's GC root.
      onnxruntime = pkgs.callPackage ../nix/onnxruntime-android.nix {
        ndk = "${(sdkFor false).androidsdk}/libexec/android-sdk/ndk/${ndkVersion}";
      };

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
          # unzip, for the scripts that read an APK (scripts/native-check.sh, release-check.sh).
          packages = [ jdk gradle sdk pkgs.cmake pkgs.gcc pkgs.qemu-user python pkgs.unzip ];
          JAVA_HOME = jdk.home;
          CARACOLE_ALPHATAB_DIR = "${alphatab}";
          CARACOLE_YTDLP_WHEELS = "${ytdlpAndroid}";
          CARACOLE_QUICKJS_SRC = "${quickjsSrc}";
          CARACOLE_BTC_WEIGHTS = "${autochordsFiles.btcWeights}";
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
      # `nix build ./android#onnxruntime-android` (and `.natives.arm64-v8a`, `.natives.x86_64`, `.java`, `.mirror`).
      packages.${system} = {
        onnxruntime-android = onnxruntime;
        # ONNX Runtime 1.27.1's own Python (nixpkgs' python3Packages.onnxruntime, the same release as the phone's) and
        # onnx, for scripts/onnxruntime-ops.sh, which derives ml/onnxruntime-ops.config from the graphs.
        onnxruntime-ops-python = pkgs.python3.withPackages (ps: [ ps.onnx ps.onnxruntime ps.flatbuffers ]);
        # The same Python and onnxruntime 1.27.1 built for aarch64 (cache.nixos.org's), run here under qemu-user, so
        # that the optimizer fuses as it does on the phone's CPU: `onnxruntime-ops-aarch64 script.py …`.
        onnxruntime-ops-aarch64 =
          let
            arm = nixpkgs.legacyPackages.aarch64-linux;
            ps = arm.python3Packages;
            modules = ps.requiredPythonModules [ ps.onnx ps.onnxruntime ];
          in pkgs.writeShellScriptBin "onnxruntime-ops-aarch64" ''
            export PYTHONPATH=${lib.concatMapStringsSep ":" (m: "${m}/${arm.python3.sitePackages}") modules}
            exec ${pkgs.qemu-user}/bin/qemu-aarch64 ${arm.python3}/bin/python3 -B "$@"
          '';
      };

      devShells.${system} = {
        # Builds and tests the app: `nix develop ./android -c gradle -p android assembleDebug`.
        default = shellFor false;
        # The same, with the emulator and an Android ${platformVersion} system image (x86_64, Google APIs).
        emulator = shellFor true;
        # The emulator's, with CARACOLE_CHORD_MODELS (the models' folder) and CARACOLE_ONNXRUNTIME (the runtime built
        # from source, so :ml and the debug build's chord models): `scripts/device-test.sh --ml`, `--models`,
        # release-check.sh. Entering it roots the runtime's build against Nix's garbage collector, in
        # $XDG_STATE_HOME/caracole/gcroots (an indirect root: delete the link to let it go).
        ml = (shellFor true).overrideAttrs (old: {
          CARACOLE_CHORD_MODELS = "${chordModels}";
          CARACOLE_ONNXRUNTIME = "${onnxruntime}/maven";
          shellHook = old.shellHook + ''
            root="''${XDG_STATE_HOME:-$HOME/.local/state}/caracole/gcroots/onnxruntime-android"
            if command -v nix-store >/dev/null && [ "$(readlink "$root" 2>/dev/null)" != "${onnxruntime}" ]; then
              mkdir -p "$(dirname "$root")"
              nix-store --add-root "$root" --indirect --realise ${onnxruntime} >/dev/null 2>&1 || true
            fi
          '';
        });
      };
    };
}
