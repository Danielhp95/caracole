# BTC and beat_this as ONNX graphs, for chords and beats worked out on the phone (docs/autochords.md), made from
# ./autochords.nix's pins by src/caracole/autochords/export.py. Four files in one folder:
#
# - btc-graph.onnx, BTC's graph, which holds none of its weights: each is an external initializer at its offset in
#   btc_model_large_voca.pt beside it, the authors' file unchanged;
# - beat_this-final0.onnx, and beat_this-final0-fp16.onnx, its weights stored as float16.
#
# The export is deterministic: a second build (`nix build --rebuild`) gives the same bytes.
{
  lib,
  callPackage,
  runCommand,
  python3,
  models ? callPackage ./autochords.nix { },
}:

let
  python = python3.withPackages (
    ps: with ps; [
      torch
      onnx
      beat-this
      numpy
    ]
  );
  # The modules export.py imports, alone, so that a change elsewhere in src/ exports nothing again.
  src = lib.fileset.toSource {
    root = ../src;
    fileset = lib.fileset.unions [
      ../src/caracole/__init__.py
      ../src/caracole/autochords
    ];
  };
in
runCommand "caracole-chord-models" { nativeBuildInputs = [ python ]; } ''
  export HOME=$TMPDIR PYTHONPATH=${src}
  mkdir $out
  python - ${models.btcWeights} ${models.beatThisCheckpoint} $out <<'EOF'
  import sys
  from caracole.autochords.export import export_beats, export_btc
  btc, beats, out = sys.argv[1:]
  export_btc(btc, out)
  export_beats(beats, out, fp16=False)
  export_beats(beats, out, fp16=True)
  EOF
''
