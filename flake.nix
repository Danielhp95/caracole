{
  description = "caracole: a nightly builder of sing-along chord sheets, lyrics and guitar parts";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/55bfb4d7437bd4e09ab7cba58a43bd68eb310044";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python3;
      runtimeDeps = ps: with ps; [ httpx selectolax rapidfuzz typer click mutagen tomlkit pypinyin opencc ];
      testDeps = ps: with ps; [ pytest pytest-xdist ];
      autochordsDeps = ps: with ps; [ torch torchaudio torchcodec beat-this librosa numpy scipy soundfile pyyaml openai-whisper ];
      # A second nixpkgs, whose python takes its torch from torch-bin (prebuilt CUDA; plain torch is
      # CPU-only), package-wide: one dependency on the CPU torch and buildEnv meets two torch builds.
      # triton-bin, too: nixpkgs' source triton cannot find libcuda for its JIT, which openai-whisper's
      # kernels need. torch-bin's CUDA libraries are unfree: only those it needs are admitted.
      cudaUnfree = [
        "cccl"
        "cuda_compat"
        "cuda_crt"
        "cuda_cudart"
        "cuda_cupti"
        "cuda_nvcc"
        "cuda_nvml_dev"
        "cuda_nvrtc"
        "cuda_nvtx"
        "cuda_profiler_api"
        "cudnn"
        "libcublas"
        "libcudla"
        "libcufft"
        "libcufile"
        "libcurand"
        "libcusolver"
        "libcusparse"
        "libcusparse_lt"
        "libnpp"
        "libnvfatbin"
        "libnvjitlink"
        "libnvjpeg"
        "libnvshmem"
        "libnvvm"
        "torch"
        "triton"
      ];
      pkgsCuda = import nixpkgs {
        inherit system;
        config.allowUnfreePredicate = pkg: builtins.elem (nixpkgs.lib.getName pkg) cudaUnfree;
        overlays = [
          (final: prev: {
            python3 = prev.python3.override {
              self = final.python3;
              packageOverrides = pyFinal: pyPrev: {
                torch = pyFinal.torch-bin;
                torchaudio = pyFinal.torchaudio-bin;
                torchvision = pyFinal.torchvision-bin;
                triton = pyFinal.triton-bin;
              };
            };
          })
        ];
      };
      pythonCuda = pkgsCuda.python3;
      devPython = python.withPackages (ps: runtimeDeps ps ++ testDeps ps);
      devPythonAutochords = python.withPackages (ps: runtimeDeps ps ++ testDeps ps ++ autochordsDeps ps);
      devPythonAutochordsCuda = pythonCuda.withPackages (ps: runtimeDeps ps ++ testDeps ps ++ autochordsDeps ps);
      # The chordpro the package's wrapper runs, without its GUI (about 130 MiB, not 1 GiB),
      # so the PDF tests here run the program the package does.
      devTools = [ caracole.chordpro pkgs.ruff pkgs.sqlite ];
      caracole = pkgs.callPackage ./nix/package.nix { };
      # The same program with the `autochords` extra (torch, beat-this, librosa),
      # its wrapper pointing at the model files from nix/autochords.nix.
      caracoleAutochords = caracole.override { withAutochords = true; };
      # The same on torch-bin: the GPU build, for transcribing lyrics with Whisper.
      caracoleAutochordsCuda = (pkgsCuda.callPackage ./nix/package.nix { python3Packages = pythonCuda.pkgs; }).override {
        withAutochords = true;
        cudaTorch = true;
      };
      # The fonts the packages set the PDFs in (Adwaita Sans and Mono, nix/pdf-fonts.nix) and render
      # Chinese sheets with, so the tests of both run here too.
      # And alphaTab, for caracole serve's Guitar Pro page and the browser tests of it.
      fontEnv.CARACOLE_CJK_FONT = caracole.cjkFont;
      fontEnv.CARACOLE_PDF_FONTS = "${caracole.pdfFonts}";
      fontEnv.CARACOLE_ALPHATAB_DIR = "${caracole.alphatab}";
      # `caracole` in a dev shell runs the checkout's src/ (the worktree the shell was
      # entered in), so an edit shows at once, with no rebuild.
      devCaracole = py: pkgs.writeShellScriptBin "caracole" ''
        exec ${py}/bin/python -m caracole "$@"
      '';
      # The auto-chords shells differ in their python alone (torch or torch-bin).
      autochordsShell = py: pkgs.mkShell ({
        packages = [ py (devCaracole py) pkgs.yt-dlp caracoleAutochords.demucs ] ++ devTools;
        shellHook = devShellHook;
        CARACOLE_BTC_WEIGHTS = caracoleAutochords.btcWeights;
        CARACOLE_BEAT_CHECKPOINT = caracoleAutochords.beatCheckpoint;
        CARACOLE_WHISPER_MODEL = caracoleAutochords.whisperModel;
        CARACOLE_DEMUCS_MODEL = caracoleAutochords.separatorModel;
      } // fontEnv);
      devShellHook = ''
        root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
        export PYTHONPATH="$root/src''${PYTHONPATH:+:$PYTHONPATH}"
        unset root
      '';
    in {
      packages.${system} = {
        default = caracole;
        autochords = caracoleAutochords;
        autochords-cuda = caracoleAutochordsCuda;
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
          cliPython = python.withPackages runtimeDeps;
        };
      };

      devShells.${system} = {
        default = pkgs.mkShell ({
          packages = [ devPython (devCaracole devPython) ] ++ devTools;
          shellHook = devShellHook;
        } // fontEnv);
        # `pytest -m autochords` here runs the model tests on the packaged model files,
        # and `caracole youtube` finds yt-dlp (and the transcriber demucs), as the auto-chords
        # package's wrapper does.
        autochords = autochordsShell devPythonAutochords;
        # `.#autochords` on torch-bin: the model tests against the GPU build of torch.
        autochords-cuda = autochordsShell devPythonAutochordsCuda;
      };
    };
}
