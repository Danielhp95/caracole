# publish-models: nix/publish-models.sh, beat_this's two converted graphs uploaded to the GitHub release `models` (gh,
# jq and coreutils on its PATH, PINS the repository's models.json). See the script's header for its usage; the owner
# runs it, by hand: `nix run .#publish-models -- "$(nix build --print-out-paths .#chord-models)"`.
{
  writeShellApplication,
  gh,
  jq,
  coreutils,
}:
writeShellApplication {
  name = "publish-models";
  runtimeInputs = [
    gh
    jq
    coreutils
  ];
  runtimeEnv.PINS = "${../tests/conformance/data/caracole/autochords/models.json}";
  text = builtins.readFile ./publish-models.sh;
  meta.description = "Upload beat_this's converted graphs for caracole's chords on the phone to a GitHub release";
}
