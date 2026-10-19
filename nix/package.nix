# caracole as a Python application built from nixpkgs dependencies only. The
# wrapper puts `chordpro` on PATH for sheet PDFs, and points CARACOLE_CJK_FONT at
# a font with Chinese glyphs, so a song like 斑马斑马 renders. The `autochords`
# variant's wrapper also points at the model files the offline unit needs.
{
  lib,
  callPackage,
  python3Packages,
  perl5Packages,
  lxgw-fusionkai,

  # `chordpro`, without its wxWidgets GUI: the full package pulls GTK, WebKit
  # and GStreamer (about 1 GiB) into a closure that only ever runs headless.
  chordpro ? perl5Packages.AppMusicChordPro.overrideAttrs (old: {
    propagatedBuildInputs = lib.remove perl5Packages.Wx old.propagatedBuildInputs;
    postInstall = (old.postInstall or "") + ''
      rm $out/bin/wxchordpro
    '';
  }),

  # The CJK font for sheets, as one static .ttf or .otf file. ChordPro 6.050.7
  # opens only those as font files, so a .ttc collection (noto-fonts-cjk-sans,
  # source-han-sans) does not work. And its PDF library corrupts the glyph
  # subsets it embeds from TrueType fonts with odd-length glyph records, which
  # most CJK TTFs have (LXGW Neo XiHei and WenKai among them); src/caracole/render.py
  # refuses those. FusionKaiJ, a Kai (brush) face, has none, and renders with
  # normal subsetting: about 0.4 MB per Chinese sheet.
  cjkFont ? "${lxgw-fusionkai}/share/fonts/truetype/FusionKaiJ-Regular.ttf",

  # The `autochords` extra: torch, beat-this, librosa and friends.
  withAutochords ? false,
  # The model files the auto-chords variant's wrapper sets by default
  # (CARACOLE_BTC_WEIGHTS, CARACOLE_BEAT_CHECKPOINT): the fixed-output downloads in
  # ./autochords.nix, because the unit has no network. The NixOS module's
  # options, then settings.autochords, win over them. Null leaves one unset.
  models ? callPackage ./autochords.nix { },
  btcWeights ? models.btcWeights,
  beatCheckpoint ? models.beatThisCheckpoint,
}:

let
  inherit (lib.importTOML ../pyproject.toml) project;

  # Wrapper defaults only: a variable already set (by the NixOS unit, say) wins.
  modelFiles = lib.filterAttrs (_: file: file != null) {
    CARACOLE_BTC_WEIGHTS = btcWeights;
    CARACOLE_BEAT_CHECKPOINT = beatCheckpoint;
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
  pname = "caracole";
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
    # btc.py decodes .m4a (AAC) through it; beat-this pulls it in too.
    torchaudio
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
    "CARACOLE_CJK_FONT"
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
    export CARACOLE_CJK_FONT=${lib.escapeShellArg cjkFont}
  '';

  # After the tests, on the wrapped program: the font exists, and the wrapper
  # sets it and finds chordpro. The auto-chords variant finds its models and
  # their packages; the default one says where to get them.
  postCheck = ''
    if [ ! -f ${lib.escapeShellArg cjkFont} ]; then
      echo "CJK font not found: ${cjkFont}" >&2
      exit 1
    fi
    grep -qF -- ${lib.escapeShellArg cjkFont} $out/bin/caracole
    grep -qF -- ${lib.escapeShellArg "${chordpro}/bin"} $out/bin/caracole
    $out/bin/caracole --version | grep -qFx "caracole ${finalAttrs.version}"
  ''
  + (
    if withAutochords then
      lib.concatMapStrings (file: ''
        test -f ${lib.escapeShellArg file}
        grep -qF -- ${lib.escapeShellArg file} $out/bin/caracole
      '') (lib.attrValues modelFiles)
      + ''
        $out/bin/caracole autochords > autochords.out
        grep -qFx "auto-chords: 0 generated, 0 skipped, 0 failed" autochords.out
      ''
    else
      ''
        if $out/bin/caracole autochords 2> autochords.err; then
          echo "caracole autochords ran without torch, librosa and beat_this" >&2
          exit 1
        fi
        grep -qF "packages.autochords" autochords.err
      ''
  );

  pythonImportsCheck = [
    "caracole"
    "caracole.cli"
  ];

  passthru = {
    inherit
      chordpro
      cjkFont
      withAutochords
      btcWeights
      beatCheckpoint
      ;
  };

  meta = {
    inherit (project) description;
    homepage = "https://github.com/Danielhp95/caracole";
    license = lib.licenses.mit;
    mainProgram = "caracole";
    platforms = lib.platforms.linux;
  };
})
