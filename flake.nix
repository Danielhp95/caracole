{
  description = "tabarr: a nightly builder of sing-along chord sheets, lyrics and guitar parts";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/55bfb4d7437bd4e09ab7cba58a43bd68eb310044";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3;
      runtimeDeps = ps: with ps; [ httpx selectolax rapidfuzz spotipy typer mutagen tomlkit pypinyin ];
      testDeps = ps: with ps; [ pytest ];
      autochordsDeps = ps: with ps; [ torch beat-this librosa numpy scipy soundfile pyyaml ];
      devPython = python.withPackages (ps: runtimeDeps ps ++ testDeps ps);
      devPythonAutochords = python.withPackages (ps: runtimeDeps ps ++ testDeps ps ++ autochordsDeps ps);
      devTools = [ pkgs.perl5Packages.AppMusicChordPro pkgs.ruff pkgs.sqlite ];
    in {
      packages.${system} = {
        dev-python = devPython;
        dev-python-autochords = devPythonAutochords;
      };

      devShells.${system} = {
        default = pkgs.mkShell { packages = [ devPython ] ++ devTools; };
        autochords = pkgs.mkShell { packages = [ devPythonAutochords ] ++ devTools; };
      };
    };
}
