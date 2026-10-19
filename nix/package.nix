# tabarr as a Python application built from nixpkgs dependencies only. The
# wrapper puts `chordpro` on PATH for sheet PDFs, and points TABARR_CJK_FONT at
# a font with Chinese glyphs, so a song like 斑马斑马 renders.
{
  lib,
  python3Packages,
  perl5Packages,
  lxgw-neoxihei,

  # `chordpro`, without its wxWidgets GUI: the full package pulls GTK, WebKit
  # and GStreamer (about 1 GiB) into a closure that only ever runs headless.
  chordpro ? perl5Packages.AppMusicChordPro.overrideAttrs (old: {
    propagatedBuildInputs = lib.remove perl5Packages.Wx old.propagatedBuildInputs;
    postInstall = (old.postInstall or "") + ''
      rm $out/bin/wxchordpro
    '';
  }),

  # The CJK font for sheets, as one static .ttf or .otf file. ChordPro's text
  # layer opens only those two as font files and takes any other name for a PDF
  # core font, so a .ttc collection (noto-fonts-cjk-sans-static, source-han-sans)
  # does not work. LXGW Neo XiHei is a single 7 MB sans TTF (simplified Chinese).
  cjkFont ? "${lxgw-neoxihei}/share/fonts/truetype/LXGWNeoXiHei.ttf",

  # The `autochords` extra: torch, beat-this, librosa and friends.
  withAutochords ? false,
  # Model files the auto-chords wrapper points at by default (the NixOS module's
  # options, and settings.autochords, still win). Null leaves them unset.
  btcWeights ? null,
  btcConfig ? null,
  beatCheckpoint ? null,
}:

let
  inherit (lib.importTOML ../pyproject.toml) project;

  # Wrapper defaults only: a variable already set (by the NixOS unit, say) wins.
  modelFiles = lib.filterAttrs (_: file: file != null) {
    TABARR_BTC_WEIGHTS = btcWeights;
    TABARR_BTC_CONFIG = btcConfig;
    TABARR_BEAT_CHECKPOINT = beatCheckpoint;
  };
  modelDefaults = lib.concatLists (
    lib.mapAttrsToList (name: file: [
      "--set-default"
      name
      "${file}"
    ]) modelFiles
  );
in
python3Packages.buildPythonApplication (finalAttrs: {
  pname = "tabarr";
  inherit (project) version;
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../README.md
      ../src
      ../tests
    ];
  };

  build-system = [ python3Packages.hatchling ];

  dependencies =
    with python3Packages;
    [
      httpx
      selectolax
      rapidfuzz
      spotipy
      typer
      mutagen
      tomlkit
      pypinyin
    ]
    ++ lib.optionals withAutochords finalAttrs.passthru.optional-dependencies.autochords;

  optional-dependencies.autochords = with python3Packages; [
    torch
    beat-this
    librosa
    numpy
    scipy
    soundfile
    pyyaml
  ];

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [ chordpro ])
    "--set-default"
    "TABARR_CJK_FONT"
    cjkFont
  ]
  ++ lib.optionals withAutochords modelDefaults;

  # `chordpro` on PATH lets the tests marked `chordpro` run. Those marked
  # `autochords` need the model weights; they run in `nix develop .#autochords`.
  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    chordpro
  ];
  disabledTestMarks = [ "autochords" ];

  preCheck = ''
    export HOME=$(mktemp -d)
    export TABARR_CJK_FONT=${lib.escapeShellArg cjkFont}
  '';

  # After the tests, on the wrapped program: the font exists, and the wrapper
  # sets it and finds chordpro.
  postCheck = ''
    if [ ! -f ${lib.escapeShellArg cjkFont} ]; then
      echo "CJK font not found: ${cjkFont}" >&2
      exit 1
    fi
    grep -qF -- ${lib.escapeShellArg cjkFont} $out/bin/tabarr
    grep -qF -- ${lib.escapeShellArg "${chordpro}/bin"} $out/bin/tabarr
    $out/bin/tabarr --version | grep -qFx "tabarr ${finalAttrs.version}"
  '';

  pythonImportsCheck = [
    "tabarr"
    "tabarr.cli"
  ];

  passthru = {
    inherit chordpro cjkFont withAutochords;
  };

  meta = {
    inherit (project) description;
    license = lib.licenses.mit;
    mainProgram = "tabarr";
    platforms = lib.platforms.linux;
  };
})
