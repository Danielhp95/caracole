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

      sdkFor = emulator: pkgs.androidenv.composeAndroidPackages ({
        platformVersions = [ platformVersion ];
        buildToolsVersions = [ buildToolsVersion ];
        includeNDK = false;
        includeCmake = false;
        includeSources = false;
        includeEmulator = emulator;
        includeSystemImages = emulator;
      } // lib.optionalAttrs emulator {
        systemImageTypes = [ "google_apis" ];
        abiVersions = [ "x86_64" ];
      });

      jdk = pkgs.jdk17;
      # Gradle from nixpkgs, not a wrapper's download: pinned with the rest, run on the JDK above.
      gradle = pkgs.gradle_8.override { java = jdk; };

      shellFor = emulator:
        let
          sdk = (sdkFor emulator).androidsdk;
          home = "${sdk}/libexec/android-sdk";
        in pkgs.mkShell {
          packages = [ jdk gradle sdk ];
          JAVA_HOME = jdk.home;
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
      };
    };
}
