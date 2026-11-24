# publish-indexes: nix/publish-indexes.sh, the site catalogues' upload to the GitHub release
# `indexes` (gh, jq and caracole on its PATH). See the script's header for its usage.
{
  writeShellApplication,
  gh,
  jq,
  coreutils,
  caracole,
}:
writeShellApplication {
  name = "publish-indexes";
  runtimeInputs = [
    gh
    jq
    coreutils
    caracole
  ];
  text = builtins.readFile ./publish-indexes.sh;
  meta.description = "Upload caracole's site catalogues to a GitHub release, check and prune them";
}
