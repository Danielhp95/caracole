#!/usr/bin/env bash
# publish-indexes: upload the site catalogues' file to the GitHub release `indexes`, check what
# GitHub holds and prune.
#
#   publish-indexes DIR
#
# DIR is where `caracole index publish DIR` just wrote the file and published.json.
#
# Environment: REPO (default Danielhp95/caracole), TAG (default indexes); GitHub's login is gh's
# own, or GH_TOKEN as set. TICK (default 30): the seconds between two lines of the upload's
# progress.
#
# Each step says what it does as it begins, on stdout. Steps, each failing the script (exit 1)
# with a line saying which:
#   1 the release exists, else it is created; either way a prerelease, so that it is never the
#     repository's Latest (/releases/latest never answers a prerelease; the phone reads the tag);
#   2 every asset whose state isn't "uploaded" is deleted (a half upload);
#   3 the file DIR/published.json names: listed as uploaded with the same size and digest,
#     "already published" (steps 4 and 5 skipped, 6 still runs); listed with no digest, which
#     can't be checked, deleted and uploaded again; listed otherwise, exit 1 (never replaced, no
#     --clobber);
#   4 uploaded: every TICK seconds a line of how far gh has read the file (its file descriptor's
#     position, /proc/PID/fdinfo) against its size, else the time so far, until gh or this
#     script is gone;
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
TICK=${TICK:-30}

[ $# -eq 1 ] && [ "${1#-}" = "$1" ] || { echo "usage: publish-indexes DIR" >&2; exit 2; }
dir=$1

die() { echo "publish-indexes: step $1: $2" >&2; exit 1; }
say() { echo "publish-indexes: $*"; }

assets() {
  local id
  id=$(gh api "repos/$REPO/releases/tags/$TAG" | jq -r .id) || return 1
  gh api --paginate "repos/$REPO/releases/$id/assets?per_page=100" | jq -cs 'add // []'
}
# the asset named $2 of the listing $1, or nothing
asset() { jq -c --arg n "$2" '[.[] | select(.name == $n)] | first // empty' <<<"$1"; }
delete_id() { gh api -X DELETE "repos/$REPO/releases/assets/$1" >/dev/null; }

# Bytes as people read them, as caracole's backup.size_text: "79.6 MB", "64 KB", "17 bytes".
size_text() {
  local n=$1 unit scale tenths
  for unit in GB:1073741824 MB:1048576 KB:1024; do
    scale=${unit#*:}
    if [ "$n" -ge "$scale" ]; then
      tenths=$(((n * 10 + scale / 2) / scale))
      if [ $((tenths % 10)) -eq 0 ]; then
        echo "$((tenths / 10)) ${unit%:*}"
      else
        echo "$((tenths / 10)).$((tenths % 10)) ${unit%:*}"
      fi
      return
    fi
  done
  echo "$n bytes"
}
# "31 of 80 MB": both in the unit of the larger, as `caracole index publish` says its gzip.
amount() {
  local done=$1 total=$2 unit scale
  if [ "$total" -ge 1073741824 ]; then
    echo "$(size_text "$done" | sed 's/ GB$//') of $(size_text "$total")"
    return
  fi
  for unit in MB:1048576 KB:1024; do
    scale=${unit#*:}
    if [ "$total" -ge "$scale" ]; then
      echo "$(((done + scale / 2) / scale)) of $(((total + scale / 2) / scale)) ${unit%:*}"
      return
    fi
  done
  echo "$done of $total bytes"
}
# A time in words: "45 s", "8 min", "1 h 5 min".
span() {
  local s=$1
  if [ "$s" -lt 60 ]; then
    echo "$s s"
  elif [ "$s" -lt 3600 ]; then
    echo "$(((s + 30) / 60)) min"
  else
    echo "$((s / 3600)) h $(((s % 3600 + 30) / 60)) min"
  fi
}
# How far process $1 has read the file $2 (an absolute path): the position of its descriptor of
# it, or nothing (no such descriptor, or no /proc).
read_pos() {
  local fd pos
  for fd in /proc/"$1"/fd/*; do
    [ "$(readlink "$fd" 2>/dev/null)" = "$2" ] || continue
    pos=$(sed -n 's/^pos:[[:space:]]*//p' /proc/"$1"/fdinfo/"${fd##*/}" 2>/dev/null) || continue
    if [ -n "$pos" ]; then
      echo "$pos"
      return 0
    fi
  done
  return 1
}
# Whether process $1 still runs: there, and no zombie (one whose stopped parent hasn't reaped it).
running() {
  local stat
  kill -0 "$1" 2>/dev/null || return 1
  stat=$(cat /proc/"$1"/stat 2>/dev/null) || return 0 # no /proc: kill -0's word
  stat=${stat##*) }
  [ "${stat%% *}" != Z ]
}
# Every TICK seconds while gh ($1) uploads the file $2 of $3 bytes, begun at $4 (seconds since
# the epoch): how far it has got. Run in the background; killed (TERM), it ends its nap too. It
# ends by itself at its next tick once gh or this script is gone (the script killed mid-upload
# can't end it), saying nothing more.
ticker() {
  local now took pos nap
  trap 'kill "$nap" 2>/dev/null; exit 0' TERM
  while :; do
    sleep "$TICK" >/dev/null 2>&1 &
    nap=$!
    wait "$nap" || exit 0
    if ! running "$1" || ! running "$$"; then
      exit 0
    fi
    printf -v now '%(%s)T' -1
    took=$((now - $4))
    if pos=$(read_pos "$1" "$2") && [ "$pos" -gt 0 ]; then
      if [ "$pos" -ge "$3" ]; then
        say "uploading · all $(size_text "$3") read · $(span "$took") so far, waiting for GitHub"
      else
        say "uploading · $(amount "$pos" "$3") · $(span "$took") so far," \
          "about $(span $((took * ($3 - pos) / pos))) left"
      fi
    else
      say "uploading · $(span "$took") so far ($(size_text "$3"))"
    fi
  done
}
# gh's upload of the file $1 ($2 bytes), the ticker saying meanwhile how far it has got; gh's
# status.
upload() {
  local pid tick start code=0
  printf -v start '%(%s)T' -1
  gh release upload "$TAG" --repo "$REPO" "$1" &
  pid=$!
  ticker "$pid" "$(realpath "$1")" "$2" "$start" &
  tick=$!
  wait "$pid" || code=$?
  kill "$tick" 2>/dev/null || true
  wait "$tick" 2>/dev/null || true
  return "$code"
}

published=$dir/published.json
[ -f "$published" ] || die 3 "$published is missing: run caracole index publish first"
file=$(jq -r .file "$published")
bytes=$(jq -r .bytes "$published")
digest="sha256:$(jq -r .sha256 "$published")"
[ -f "$dir/$file" ] || die 3 "$dir/$file is missing"

# 1
say "reading the release $TAG of $REPO..."
if ! gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  say "creating the release $TAG, a prerelease, so that it is never the repository's Latest..."
  gh release create "$TAG" --repo "$REPO" --prerelease --title "Site catalogues" \
    --notes "The site catalogues' files: made weekly by caracole index publish." >/dev/null \
    || die 1 "the release $TAG can't be created"
else
  pre=$(gh api "repos/$REPO/releases/tags/$TAG" | jq -r .prerelease) || die 1 "the release $TAG can't be read"
  if [ "$pre" != true ]; then
    say "marking the release $TAG a prerelease, so that it is never the repository's Latest..."
    gh release edit "$TAG" --repo "$REPO" --prerelease >/dev/null \
      || die 1 "the release $TAG can't be made a prerelease"
  fi
fi
list=$(assets) || die 1 "the release $TAG can't be read"

# 2
while IFS=$'\t' read -r id name; do
  [ -n "$id" ] || continue
  say "deleting $name, half uploaded..."
  delete_id "$id" || die 2 "the half-uploaded asset $id can't be deleted"
done < <(jq -r '.[] | select(.state != "uploaded") | "\(.id)\t\(.name)"' <<<"$list")
list=$(assets) || die 2 "the release can't be read"

# 3
there=$(asset "$list" "$file")
if [ -n "$there" ] && [ -z "$(jq -r '.digest // empty' <<<"$there")" ]; then
  say "GitHub lists $file with no digest, so it can't be checked: deleting it to upload it again..."
  delete_id "$(jq -r .id <<<"$there")" || die 3 "$file, listed with no digest, can't be deleted"
  there=
fi
if [ -n "$there" ]; then
  if [ "$(jq -r .size <<<"$there")" = "$bytes" ] && [ "$(jq -r .digest <<<"$there")" = "$digest" ]; then
    say "$file is already published"
  else
    die 3 "a different file of that name is there: $file"
  fi
else
  # 4
  say "uploading $file ($(size_text "$bytes")) to $REPO, release $TAG..."
  upload "$dir/$file" "$bytes" || die 4 "$file can't be uploaded"

  # 5
  say "checking the upload against published.json..."
  list=$(assets) || die 5 "the release can't be read back"
  there=$(asset "$list" "$file")
  [ -n "$there" ] || die 5 "$file isn't listed after its upload"
  got=$(jq -r '.digest // empty' <<<"$there")
  [ -n "$got" ] || die 5 "GitHub gave no digest for $file: kept, not checked (the next run uploads it again)"
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
  count=$((${#args[@]} / 2))
  if [ "$count" -eq 1 ]; then noun=asset; else noun=assets; fi
  say "applying the Keep rule to $count $noun..."
  drop=$(caracole index publish "$dir" "${args[@]}") || die 6 "the Keep rule can't be applied"
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    id=$(asset "$list" "$name" | jq -r .id)
    delete_id "$id" || die 6 "$name can't be deleted"
    say "pruned $name"
  done <<<"$drop"
fi

say "published $file"
