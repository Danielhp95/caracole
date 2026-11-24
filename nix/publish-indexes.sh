#!/usr/bin/env bash
# publish-indexes: upload the site catalogues' file to the GitHub release `indexes`, check what
# GitHub holds, swap the manifest (optional) and prune.
#
#   publish-indexes [--manifest] DIR
#
# DIR is where `caracole index publish DIR` just wrote the file and published.json. Without
# --manifest the release's manifest (indexes.json) is left as it is. With it, the script builds
# the manifest itself from the release's own asset list, once the upload is checked and the
# pruning done: {"format": 1, "files": [{file, schema, made, bytes, sha256}, ...]}, every
# uploaded asset named indexes-s<N>-<yyyymmdd>T<hhmm>Z.sqlite.gz, newest first by the name's
# stamp (`made` from published.json for the new file, else the name's stamp). It is uploaded as
# indexes.json.next and swapped in by two renames. (Python's --manifest of caracole index
# publish is not used here.)
#
# Environment: REPO (default Danielhp95/caracole), TAG (default indexes), GH_TOKEN_FILE (a file
# holding the token: read into GH_TOKEN; else gh's own login or GH_TOKEN as set).
#
# Steps, each failing the script (exit 1) with a line saying which:
#   1 the release exists, else it is created (not "latest");
#   2 every asset whose state isn't "uploaded" is deleted (a half upload); with --manifest, a
#     manifest swap that died is mended first (indexes.json missing and .prev there: renamed
#     back), and a leftover indexes.json.next deleted;
#   3 the file DIR/published.json names: listed as uploaded with the same size and digest,
#     "already published", exit 0; listed otherwise, exit 1 (never replaced, no --clobber);
#   4 uploaded;
#   5 read back: size and digest must be published.json's, else it is deleted and exit 1;
#   6 `caracole index publish --kept <every asset name>` prints what the Keep rule drops; those
#     are deleted;
#   7 --manifest: the manifest built, uploaded as indexes.json.next, indexes.json renamed .prev,
#     .next renamed indexes.json, .prev deleted: two renames, so a run that dies between them is
#     mended by the next one's step 2.
#
# GitHub's REST asset shape is used throughout (`gh api repos/R/releases/tags/T`: numeric id,
# name, size, state, digest "sha256:<hex>"), since `gh release view --json assets` gives a
# GraphQL node id, which the renaming and deleting endpoints don't take. An asset is deleted by
# id with `gh api -X DELETE`, as `gh release delete-asset` takes names only and a half-uploaded
# asset may not be addressable by name.
set -euo pipefail

REPO=${REPO:-Danielhp95/caracole}
TAG=${TAG:-indexes}
mode=plain

usage() { echo "usage: publish-indexes [--manifest] DIR" >&2; exit 2; }
dir=
for arg in "$@"; do
  case $arg in
    --manifest) mode=manifest ;;
    -*) usage ;;
    *) [ -z "$dir" ] || usage; dir=$arg ;;
  esac
done
[ -n "$dir" ] || usage

if [ -n "${GH_TOKEN_FILE:-}" ]; then
  GH_TOKEN=$(cat "$GH_TOKEN_FILE")
  export GH_TOKEN
fi

die() { echo "publish-indexes: step $1: $2" >&2; exit 1; }

assets() { gh api "repos/$REPO/releases/tags/$TAG" | jq -c '.assets'; }
# the asset named $2 of the listing $1, or nothing
asset() { jq -c --arg n "$2" '[.[] | select(.name == $n)] | first // empty' <<<"$1"; }
delete_id() { gh api -X DELETE "repos/$REPO/releases/assets/$1" >/dev/null; }
rename_id() { gh api -X PATCH "repos/$REPO/releases/assets/$1" -f "name=$2" >/dev/null; }

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
if [ "$mode" = manifest ]; then
  if [ -z "$(asset "$list" indexes.json)" ] && [ -n "$(asset "$list" indexes.json.prev)" ]; then
    id=$(asset "$list" indexes.json.prev | jq -r .id)
    rename_id "$id" indexes.json || die 2 "indexes.json.prev can't be renamed back"
    list=$(assets) || die 2 "the release can't be read"
  fi
  leftover=$(asset "$list" indexes.json.next)
  if [ -n "$leftover" ]; then
    delete_id "$(jq -r .id <<<"$leftover")" || die 2 "a leftover indexes.json.next can't be deleted"
    list=$(assets) || die 2 "the release can't be read"
  fi
fi
for id in $(jq -r '.[] | select(.state != "uploaded") | .id' <<<"$list"); do
  delete_id "$id" || die 2 "the half-uploaded asset $id can't be deleted"
done
list=$(assets) || die 2 "the release can't be read"

# 3
there=$(asset "$list" "$file")
if [ -n "$there" ]; then
  if [ "$(jq -r .size <<<"$there")" = "$bytes" ] && [ "$(jq -r .digest <<<"$there")" = "$digest" ]; then
    echo "publish-indexes: $file is already published"
    exit 0
  fi
  die 3 "a different file of that name is there: $file"
fi

# 4
gh release upload "$TAG" --repo "$REPO" "$dir/$file" || die 4 "$file can't be uploaded"

# 5
list=$(assets) || die 5 "the release can't be read back"
there=$(asset "$list" "$file")
[ -n "$there" ] || die 5 "$file isn't listed after its upload"
if [ "$(jq -r .state <<<"$there")" != uploaded ] || [ "$(jq -r .size <<<"$there")" != "$bytes" ] \
  || [ "$(jq -r .digest <<<"$there")" != "$digest" ]; then
  delete_id "$(jq -r .id <<<"$there")" || true
  die 5 "GitHub holds $file with another size or digest than published.json's: deleted"
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
# 7
if [ "$mode" = manifest ]; then
  next=$dir/indexes.json.next
  list=$(assets) || die 7 "the release can't be read"
  jq --argjson new "$(cat "$published")" '
    {format: 1, files: ([.[] | select(.state == "uploaded")
      | (.name | capture("^indexes-s(?<s>[0-9]+)-(?<d>[0-9]{8})T(?<t>[0-9]{4})Z\\.sqlite\\.gz$")?) as $m
      | select($m) | {file: .name, schema: ($m.s | tonumber),
          stamp: "\($m.d[0:4])-\($m.d[4:6])-\($m.d[6:8])T\($m.t[0:2]):\($m.t[2:4]):00Z",
          bytes: .size, sha256: (.digest | sub("^sha256:"; ""))}
      | {file, schema, made: (if .file == $new.file then $new.made else .stamp end), bytes, sha256, stamp}]
      | sort_by(.stamp) | reverse | map(del(.stamp)))}' <<<"$list" >"$next" || die 7 "the manifest can't be built"
  gh release upload "$TAG" --repo "$REPO" "$next" || die 7 "indexes.json.next can't be uploaded"
  list=$(assets) || die 7 "the release can't be read"
  nextid=$(asset "$list" indexes.json.next | jq -r '.id // empty')
  [ -n "$nextid" ] || die 7 "indexes.json.next isn't listed after its upload"
  old=$(asset "$list" indexes.json)
  if [ -n "$old" ]; then
    rename_id "$(jq -r .id <<<"$old")" indexes.json.prev || die 7 "indexes.json can't be renamed to .prev"
  fi
  rename_id "$nextid" indexes.json || die 7 "indexes.json.next can't be renamed to indexes.json"
  if [ -n "$old" ]; then
    delete_id "$(jq -r .id <<<"$old")" || die 7 "indexes.json.prev can't be deleted"
  fi
fi

echo "publish-indexes: published $file"
