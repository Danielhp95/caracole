{
  description = "caracole: a nightly builder of sing-along chord sheets, lyrics and guitar parts";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/55bfb4d7437bd4e09ab7cba58a43bd68eb310044";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3;
      runtimeDeps = ps: with ps; [ httpx selectolax rapidfuzz spotipy typer mutagen tomlkit pypinyin ];
      testDeps = ps: with ps; [ pytest pytest-xdist ];
      autochordsDeps = ps: with ps; [ torch torchaudio beat-this librosa numpy scipy soundfile pyyaml ];
      devPython = python.withPackages (ps: runtimeDeps ps ++ testDeps ps);
      devPythonAutochords = python.withPackages (ps: runtimeDeps ps ++ testDeps ps ++ autochordsDeps ps);
      devTools = [ pkgs.perl5Packages.AppMusicChordPro pkgs.ruff pkgs.sqlite ];
      caracole = pkgs.callPackage ./nix/package.nix { };
      # The same program with the `autochords` extra (torch, beat-this, librosa),
      # its wrapper pointing at the model files from nix/autochords.nix.
      caracoleAutochords = caracole.override { withAutochords = true; };
      # The font the packages render Chinese sheets with, so the CJK test runs here too.
      fontEnv.CARACOLE_CJK_FONT = caracole.cjkFont;
    in {
      packages.${system} = {
        default = caracole;
        autochords = caracoleAutochords;
        dev-python = devPython;
        dev-python-autochords = devPythonAutochords;
      };

      # nix/module.nix, with the packages defaulting to this flake's builds
      # (the ones `nix build` tests) rather than rebuilds from the host's nixpkgs.
      nixosModules.default = { lib, pkgs, ... }:
        let
          packages = self.packages.${pkgs.stdenv.hostPlatform.system};
        in {
          _file = ./flake.nix;
          imports = [ ./nix/module.nix ];
          services.caracole.package = lib.mkDefault packages.default;
          services.caracole.autochords.package = lib.mkDefault packages.autochords;
        };

      checks.${system} = {
        package = self.packages.${system}.default;
        # The same tests with torch importable, and a `caracole autochords` run on
        # the wrapped program with its packaged model files.
        autochords = self.packages.${system}.autochords;
        module = pkgs.callPackage ./nix/module-check.nix {
          module = self.nixosModules.default;
          defaultPackage = self.packages.${system}.default;
          autochordsPackage = self.packages.${system}.autochords;
        };
      };

      devShells.${system} = {
        default = pkgs.mkShell ({ packages = [ devPython ] ++ devTools; } // fontEnv);
        # `pytest -m autochords` here runs the model tests on the packaged model files.
        autochords = pkgs.mkShell ({
          packages = [ devPythonAutochords ] ++ devTools;
          CARACOLE_BTC_WEIGHTS = caracoleAutochords.btcWeights;
          CARACOLE_BEAT_CHECKPOINT = caracoleAutochords.beatCheckpoint;
        } // fontEnv);
      };
    };
}
