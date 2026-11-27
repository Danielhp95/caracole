#!/usr/bin/env bash
# publish-models: upload beat_this's two converted graphs to the GitHub release `models`, whence the phone's models'
# job fetches them (core.models' ModelsSource, the chords-on-the-phone design's §6). BTC's weights are never put there:
# the phone fetches its authors' own file.
#
#   publish-models DIR
#
# DIR is `nix build .#chord-models`' folder. The pins are models.json (PINS, which the Nix wrapper sets to the
# repository's tests/conformance/data/caracole/autochords/models.json): the release's name, each asset's name, size and
# SHA-256.
#
# Environment: REPO (default Danielhp95/caracole); GitHub's login is gh's own, or GH_TOKEN as set. Run by the owner by
# hand, never by caracole.
#
# Each step says what it does as it begins, on stdout. Steps, each failing the script (exit 1) with a line saying which:
#   1 the two files of DIR are the pinned ones (size and SHA-256), else nothing is uploaded;
#   2 the release exists, else it is created; either way a prerelease, so that it is never the repository's Latest;
#   3 every asset of the two names whose state isn't "uploaded" is deleted (a half upload);
#   4 each file: listed as uploaded with the pinned size and digest, "already published"; listed with no digest, which
#     can't be checked, deleted and uploaded again; listed otherwise, exit 1 (never replaced, no --clobber); else
#     uploaded, then read back: its size and digest must be the pins', else it is deleted and exit 1.
# No other asset of the release is touched.
#
# GitHub's REST asset shape is used throughout (`gh api repos/R/releases/tags/T`: numeric id, name, size, state, digest
# "sha256:<hex>"), as nix/publish-indexes.sh does.
set -euo pipefail

REPO=${REPO:-Danielhp95/caracole}
: "${PINS:?PINS: the path of models.json}"

[ $# -eq 1 ] && [ "${1#-}" = "$1" ] || { echo "usage: publish-models DIR" >&2; exit 2; }
dir=$1

die() { echo "publish-models: step $1: $2" >&2; exit 1; }
say() { echo "publish-models: $*"; }

TAG=$(jq -r .release "$PINS")
[ -n "$TAG" ] && [ "$TAG" != null ] || die 1 "$PINS names no release"

assets() {
  local id
  id=$(gh api "repos/$REPO/releases/tags/$TAG" | jq -r .id) || return 1
  gh api --paginate "repos/$REPO/releases/$id/assets?per_page=100" | jq -cs 'add // []'
}
asset() { jq -c --arg n "$2" '[.[] | select(.name == $n)] | first // empty' <<<"$1"; }
delete_id() { gh api -X DELETE "repos/$REPO/releases/assets/$1" >/dev/null; }

# 1: the pinned files, "name<TAB>bytes<TAB>sha256" a line.
pinned=$(jq -r '.beats.fp32, .beats.fp16 | "\(.asset)\t\(.bytes)\t\(.sha256)"' "$PINS")
names=() sizes=() shas=()
while IFS=$'\t' read -r name bytes sha; do
  names+=("$name") sizes+=("$bytes") shas+=("$sha")
done <<<"$pinned"
for i in "${!names[@]}"; do
  name=${names[$i]}
  [ -f "$dir/$name" ] || die 1 "$dir/$name is missing"
  [ "$(stat -c %s "$dir/$name")" = "${sizes[$i]}" ] \
    && [ "$(sha256sum "$dir/$name" | cut -d' ' -f1)" = "${shas[$i]}" ] \
    || die 1 "$dir/$name isn't the pinned file (${sizes[$i]} bytes, sha256 ${shas[$i]})"
done

# 2
say "reading the release $TAG of $REPO..."
if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  say "creating the release $TAG, a prerelease, so that it is never the repository's Latest..."
  gh release create "$TAG" --repo "$REPO" --prerelease --title "Chord models" \
    --notes "beat_this's converted graphs for caracole's chords on the phone: uploaded by nix/publish-models.sh." \
    >/dev/null || die 2 "the release $TAG can't be created"
else
  pre=$(gh api "repos/$REPO/releases/tags/$TAG" | jq -r .prerelease) || die 2 "the release $TAG can't be read"
  if [ "$pre" != true ]; then
    say "marking the release $TAG a prerelease, so that it is never the repository's Latest..."
    gh release edit "$TAG" --repo "$REPO" --prerelease >/dev/null || die 2 "the release $TAG can't be made a prerelease"
  fi
fi
list=$(assets) || die 2 "the release $TAG can't be read"

# 3
for name in "${names[@]}"; do
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    say "deleting $name, half uploaded..."
    delete_id "$id" || die 3 "the half-uploaded $name can't be deleted"
  done < <(jq -r --arg n "$name" '.[] | select(.name == $n and .state != "uploaded") | .id' <<<"$list")
done
list=$(assets) || die 3 "the release can't be read"

# 4
# (no gh reads from a loop's stdin: the files go by index)
for i in "${!names[@]}"; do
  name=${names[$i]} bytes=${sizes[$i]}
  digest="sha256:${shas[$i]}"
  there=$(asset "$list" "$name")
  if [ -n "$there" ] && [ -z "$(jq -r '.digest // empty' <<<"$there")" ]; then
    say "GitHub lists $name with no digest, so it can't be checked: deleting it to upload it again..."
    delete_id "$(jq -r .id <<<"$there")" || die 4 "$name, listed with no digest, can't be deleted"
    there=
  fi
  if [ -n "$there" ]; then
    if [ "$(jq -r .size <<<"$there")" = "$bytes" ] && [ "$(jq -r .digest <<<"$there")" = "$digest" ]; then
      say "$name is already published"
      continue
    fi
    die 4 "a different file of that name is there: $name"
  fi
  say "uploading $name ($bytes bytes) to $REPO, release $TAG..."
  gh release upload "$TAG" --repo "$REPO" "$dir/$name" || die 4 "$name can't be uploaded"
  list=$(assets) || die 4 "the release can't be read back"
  there=$(asset "$list" "$name")
  [ -n "$there" ] || die 4 "$name isn't listed after its upload"
  if [ "$(jq -r .state <<<"$there")" != uploaded ] || [ "$(jq -r .size <<<"$there")" != "$bytes" ] \
    || [ "$(jq -r '.digest // empty' <<<"$there")" != "$digest" ]; then
    delete_id "$(jq -r .id <<<"$there")" || true
    die 4 "GitHub holds $name with another size or digest than the pins': deleted"
  fi
  say "$name uploaded and checked"
done

say "published ${#names[@]} files"
