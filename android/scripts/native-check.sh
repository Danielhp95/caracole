#!/usr/bin/env bash
# What an APK's libcaracole_soxr.so (autochords/native/, packaged by :ml) must be, for each ABI (arm64-v8a, x86_64):
#
#   android/scripts/native-check.sh [APK]      # default: android/app/build/outputs/apk/debug/app-debug.apk
#
# run inside `nix develop ./android` after `gradle -p android :app:assembleDebug`:
#
# - stored uncompressed and 16 KB aligned (zipalign -c -P 16), its every LOAD segment aligned 0x4000;
# - stripped: no .debug_* or .symtab section, no .comment, no build-id note;
# - no path of the machine that built it: no "/home/", "/nix/store/", ".cxx/" or "/tmp/" among its strings.
#
# It prints each library's SHA-256 (two checkouts at different paths give the same: the design's §7) and exits
# non-zero on any failure.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
apk=${1:-$here/app/build/outputs/apk/debug/app-debug.apk}
: "${ANDROID_HOME:?run inside nix develop ./android}"
ndk=$ANDROID_HOME/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin
zipalign=$ANDROID_HOME/build-tools/36.0.0/zipalign
[ -f "$apk" ] || { echo "no APK at $apk: gradle -p android :app:assembleDebug" >&2; exit 2; }

failed=0
fail() { echo "FAIL: $*"; failed=1; }
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
aligned=$("$zipalign" -c -P 16 -v 4 "$apk")

for abi in arm64-v8a x86_64; do
  entry=lib/$abi/libcaracole_soxr.so
  so=$work/$abi.so
  if ! unzip -p "$apk" "$entry" > "$so" || [ ! -s "$so" ]; then
    fail "$entry: not in the APK"
    continue
  fi
  grep -qF "$entry (OK)" <<< "$aligned" || fail "$entry: not stored uncompressed and 16 KB aligned"
  if "$ndk/llvm-readelf" -lW "$so" | awk '$1 == "LOAD" && $NF != "0x4000"' | grep -q .; then
    fail "$entry: a LOAD segment not aligned 0x4000"
  fi
  sections=$("$ndk/llvm-readelf" -SW "$so")
  for s in .debug_ .symtab .comment .note.gnu.build-id; do
    grep -qF " $s" <<< "$sections" && fail "$entry: has a $s section"
  done
  paths=$("$ndk/llvm-strings" -a "$so" | grep -E '/home/|/nix/store/|\.cxx/|/tmp/' || true)
  [ -z "$paths" ] || fail "$entry: names a path of the build: $(head -3 <<< "$paths" | tr '\n' ' ')"
  echo "$(sha256sum "$so" | cut -d' ' -f1)  $entry ($(stat -c %s "$so") bytes)"
done

[ "$failed" = 0 ] && echo "OK: both libraries stored aligned, stripped, and naming no path of the build"
exit "$failed"
