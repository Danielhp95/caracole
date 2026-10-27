# caracole as a Python application built from nixpkgs dependencies only. The
# wrapper puts `chordpro` on PATH for sheet PDFs, points CARACOLE_PDF_FONTS at the
# fonts they are set in (./pdf-fonts.nix: Adwaita Sans and Mono, GNOME's), and
# CARACOLE_CJK_FONT at a font with Chinese glyphs, so a song like 斑马斑马 renders. The `autochords`
# variant's wrapper also points at the model files the offline unit needs, and
# puts `yt-dlp` on PATH, for the audio of songs nobody has charted. Both point
# CARACOLE_ALPHATAB_DIR at alphaTab (./alphatab.nix), which caracole serve's Guitar
# Pro page draws and plays a song's Guitar Pro file with.
{
  lib,
  callPackage,
  python3Packages,
  perl5Packages,
  lxgw-fusionkai,

  # yt-dlp, which the nightly run's YouTube step runs (src/caracole/youtube.py),
  # in the auto-chords variant alone: without auto-chords caracole takes no audio
  # from YouTube. nixpkgs' wrapper brings what it needs: ffmpeg and ffprobe for
  # `-x`, and deno, the JavaScript runtime YouTube's player needs, patched in.
  yt-dlp,

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

  # The fonts every PDF is set in (./pdf-fonts.nix): Adwaita Sans, static Regular, Bold and
  # Italic instances of GNOME's variable fonts, and Adwaita Mono for tabs, in one folder
  # (src/caracole/pdf_fonts.py). The CJK font above takes the words only where they need
  # letters Adwaita lacks (Chinese). Null leaves CARACOLE_PDF_FONTS unset: the PDFs then
  # keep ChordPro's built-in Helvetica and Courier.
  pdfFonts ? callPackage ./pdf-fonts.nix { },

  # alphaTab's browser build, its music font and its SoundFont (./alphatab.nix), which
  # caracole serve sends to its Guitar Pro page (src/caracole/web/alphatab.py). Null
  # leaves CARACOLE_ALPHATAB_DIR unset: Guitar Pro files are then downloads alone.
  alphatab ? callPackage ./alphatab.nix { },

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
      # hatchling puts it in the wheel's dist-info, as pip's install from the repository has it.
      ../LICENSE
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
      typer
      click
      mutagen
      tomlkit
      pypinyin
      opencc
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
    (lib.makeBinPath ([ chordpro ] ++ lib.optional withAutochords yt-dlp))
    "--set-default"
    "CARACOLE_CJK_FONT"
    cjkFont
  ]
  ++ lib.optionals (pdfFonts != null) [
    "--set-default"
    "CARACOLE_PDF_FONTS"
    "${pdfFonts}"
  ]
  ++ lib.optionals (alphatab != null) [
    "--set-default"
    "CARACOLE_ALPHATAB_DIR"
    "${alphatab}"
  ]
  ++ lib.optionals withAutochords modelDefaults;

  # `chordpro` on PATH lets the tests marked `chordpro` run. Those marked
  # `autochords` need the model weights; they run in `nix develop .#autochords`.
  # pytest-xdist's setup hook runs them on $NIX_BUILD_CORES workers.
  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    python3Packages.pytest-xdist
    chordpro
  ];
  disabledTestMarks = [ "autochords" ];

  preCheck = ''
    export HOME=$(mktemp -d)
    export CARACOLE_CJK_FONT=${lib.escapeShellArg cjkFont}
  ''
  + lib.optionalString (pdfFonts != null) ''
    export CARACOLE_PDF_FONTS=${pdfFonts}
  ''
  + lib.optionalString (alphatab != null) ''
    export CARACOLE_ALPHATAB_DIR=${alphatab}
  '';

  # After the tests, on the installed package: it is src/, file for file. The
  # tests import caracole from src/ (pyproject's pythonpath), so they would pass
  # with a stylesheet, script, template or data file the code reads at run time
  # (library_assets/, viewer/, chordpro-style.json) left out of the wheel, or
  # with a folder beside src/caracole that the wheel never takes.
  # Then on the wrapped program: the font exists, and the wrapper
  # sets it and finds chordpro, and points at the PDF fonts' four files and at
  # alphaTab's three. The auto-chords variant finds its models, their
  # packages and yt-dlp, so its YouTube route is on (with no song to ask about,
  # it asks nothing); the default one says where to get them, and takes no audio
  # from YouTube.
  postCheck = ''
    if ! diff -r --exclude=__pycache__ --exclude='caracole-*.dist-info' \
      src $out/${python3Packages.python.sitePackages}; then
      echo "the installed package is not src/ file for file: see the lines above" >&2
      exit 1
    fi
    if [ ! -f ${lib.escapeShellArg cjkFont} ]; then
      echo "CJK font not found: ${cjkFont}" >&2
      exit 1
    fi
    grep -qF -- ${lib.escapeShellArg cjkFont} $out/bin/caracole
    grep -qF -- ${lib.escapeShellArg "${chordpro}/bin"} $out/bin/caracole
  ''
  + lib.optionalString (pdfFonts != null) ''
    for role in regular bold italic mono; do
      test -f ${pdfFonts}/$role.ttf
    done
    grep -qF -- "CARACOLE_PDF_FONTS" $out/bin/caracole
    grep -qF -- ${pdfFonts} $out/bin/caracole
  ''
  + lib.optionalString (alphatab != null) ''
    for file in alphaTab.min.js Bravura.woff2 sonivox.sf3; do
      test -f ${alphatab}/$file
    done
    grep -qF -- "CARACOLE_ALPHATAB_DIR" $out/bin/caracole
    grep -qF -- ${alphatab} $out/bin/caracole
  ''
  + ''
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
        grep -qF -- ${lib.escapeShellArg "${yt-dlp}/bin"} $out/bin/caracole
        $out/bin/caracole youtube > youtube.out
        grep -qFx "No song is waiting for audio from YouTube." youtube.out
      ''
    else
      ''
        if $out/bin/caracole autochords 2> autochords.err; then
          echo "caracole autochords ran without torch, librosa and beat_this" >&2
          exit 1
        fi
        grep -qF "packages.autochords" autochords.err
        if $out/bin/caracole youtube 2> youtube.err; then
          echo "caracole youtube ran without auto-chords" >&2
          exit 1
        fi
        grep -qF "packages.autochords" youtube.err
        if grep -qF -- ${lib.escapeShellArg "${yt-dlp}/bin"} $out/bin/caracole; then
          echo "the default package puts yt-dlp on PATH" >&2
          exit 1
        fi
      ''
  );

  # library_page reads index.html's stylesheets and scripts (library_assets/) at import:
  # importing it from $out checks the package holds them.
  pythonImportsCheck = [
    "caracole"
    "caracole.cli"
    "caracole.library_page"
  ];

  passthru = {
    inherit
      chordpro
      yt-dlp
      cjkFont
      pdfFonts
      withAutochords
      alphatab
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
