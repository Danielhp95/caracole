# publish-models: nix/publish-models.sh, beat_this's two converted graphs and its licence uploaded to the GitHub release
# `models` (gh, jq and coreutils on its PATH, PINS the repository's models.json, BEAT_THIS_LICENSE the APK's copy of
# the licence). See the script's header for its usage; the owner runs it, by hand:
# `nix run .#publish-models -- "$(nix build --print-out-paths .#chord-models)"`.
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
  runtimeEnv.BEAT_THIS_LICENSE = "${../android/ml/licenses/beat_this-LICENSE.txt}";
  text = builtins.readFile ./publish-models.sh;
  meta.description =
    "Upload beat_this's converted graphs and licence for caracole's chords on the phone to a GitHub release";
}
