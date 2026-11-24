#!/usr/bin/env bash
# publish-indexes: upload the site catalogues' file to the GitHub release `indexes`, check what
# GitHub holds and prune.
#
#   publish-indexes DIR
#
# DIR is where `caracole index publish DIR` just wrote the file and published.json.
#
# Environment: REPO (default Danielhp95/caracole), TAG (default indexes); GitHub's login is gh's
# own, or GH_TOKEN as set.
#
# Steps, each failing the script (exit 1) with a line saying which:
#   1 the release exists, else it is created (not "latest");
#   2 every asset whose state isn't "uploaded" is deleted (a half upload);
#   3 the file DIR/published.json names: listed as uploaded with the same size and digest,
#     "already published" (steps 4 and 5 skipped, 6 still runs); listed otherwise, exit 1 (never
#     replaced, no --clobber);
#   4 uploaded;
#   5 read back: size and digest must be published.json's, else it is deleted and exit 1;
#   6 `caracole index publish --kept <every asset name>` prints what the Keep rule drops; those
#     are deleted.
#
# GitHub's REST asset shape is used throughout (`gh api repos/R/releases/tags/T`: numeric id,
# name, size, state, digest "sha256:<hex>"), since `gh release view --json assets` gives a
# GraphQL node id, which the deleting endpoint doesn't take. An asset is deleted by id with
# `gh api -X DELETE`, as `gh release delete-asset` takes names only and a half-uploaded asset may
# not be addressable by name.
set -euo pipefail

REPO=${REPO:-Danielhp95/caracole}
TAG=${TAG:-indexes}

[ $# -eq 1 ] && [ "${1#-}" = "$1" ] || { echo "usage: publish-indexes DIR" >&2; exit 2; }
dir=$1

die() { echo "publish-indexes: step $1: $2" >&2; exit 1; }

assets() {
  local id
  id=$(gh api "repos/$REPO/releases/tags/$TAG" | jq -r .id) || return 1
  gh api --paginate "repos/$REPO/releases/$id/assets?per_page=100" | jq -cs 'add // []'
}
# the asset named $2 of the listing $1, or nothing
asset() { jq -c --arg n "$2" '[.[] | select(.name == $n)] | first // empty' <<<"$1"; }
delete_id() { gh api -X DELETE "repos/$REPO/releases/assets/$1" >/dev/null; }

published=$dir/published.json
[ -f "$published" ] || die 3 "$published is missing: run caracole index publish first"
file=$(jq -r .file "$published")
bytes=$(jq -r .bytes "$published")
digest="sha256:$(jq -r .sha256 "$published")"
[ -f "$dir/$file" ] || die 3 "$dir/$file is missing"

# 1
if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release create "$TAG" --repo "$REPO" --latest=false --title "Site catalogues" \
    --notes "The site catalogues' files: made weekly by caracole index publish." \
    || die 1 "the release $TAG can't be created"
fi
list=$(assets) || die 1 "the release $TAG can't be read"

# 2
for id in $(jq -r '.[] | select(.state != "uploaded") | .id' <<<"$list"); do
  delete_id "$id" || die 2 "the half-uploaded asset $id can't be deleted"
done
list=$(assets) || die 2 "the release can't be read"

# 3
there=$(asset "$list" "$file")
if [ -n "$there" ]; then
  if [ "$(jq -r .size <<<"$there")" = "$bytes" ] && [ "$(jq -r .digest <<<"$there")" = "$digest" ]; then
    echo "publish-indexes: $file is already published"
  else
    die 3 "a different file of that name is there: $file"
  fi
else
  # 4
  gh release upload "$TAG" --repo "$REPO" "$dir/$file" || die 4 "$file can't be uploaded"

  # 5
  list=$(assets) || die 5 "the release can't be read back"
  there=$(asset "$list" "$file")
  [ -n "$there" ] || die 5 "$file isn't listed after its upload"
  got=$(jq -r '.digest // empty' <<<"$there")
  [ -n "$got" ] || die 5 "GitHub gave no digest for $file: kept, not checked"
  if [ "$(jq -r .state <<<"$there")" != uploaded ] || [ "$(jq -r .size <<<"$there")" != "$bytes" ] \
    || [ "$got" != "$digest" ]; then
    delete_id "$(jq -r .id <<<"$there")" || true
    die 5 "GitHub holds $file with another size or digest than published.json's: deleted"
  fi
fi

# 6
list=$(assets) || die 6 "the release can't be read"
args=()
while IFS= read -r name; do args+=(--kept "$name"); done < <(jq -r '.[].name' <<<"$list")
if [ ${#args[@]} -gt 0 ]; then
  drop=$(caracole index publish "$dir" "${args[@]}") || die 6 "the Keep rule can't be applied"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    id=$(asset "$list" "$name" | jq -r .id)
    delete_id "$id" || die 6 "$name can't be deleted"
    echo "publish-indexes: pruned $name"
  done <<<"$drop"
fi

echo "publish-indexes: published $file"
