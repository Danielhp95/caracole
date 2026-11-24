# publish-indexes: nix/publish-indexes.sh, the site catalogues' upload to the GitHub release
# `indexes` (gh, jq, coreutils, sed and caracole on its PATH). See the script's header for its usage.
{
  writeShellApplication,
  gh,
  jq,
  coreutils,
  gnused,
  caracole,
}:
writeShellApplication {
  name = "publish-indexes";
  runtimeInputs = [
    gh
    jq
    coreutils
    gnused
    caracole
  ];
  text = builtins.readFile ./publish-indexes.sh;
  meta.description = "Upload caracole's site catalogues to a GitHub release, check and prune them";
}
