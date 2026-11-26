#!/usr/bin/env bash
# What the debug APK's own native code must be, for each ABI (arm64-v8a, x86_64): libcaracole_soxr.so
# (autochords/native/, packaged by :ml) and libqjs.so (QuickJS-NG's qjs, youtube/native/, packaged by :youtube):
#
#   android/scripts/native-check.sh [APK]      # default: android/app/build/outputs/apk/debug/app-debug.apk
#
# run inside `nix develop ./android` after `gradle -p android :app:assembleDebug`:
#
# - either stored uncompressed and 16 KB aligned (zipalign -c -P 16), or compressed in an APK whose manifest says
#   android:extractNativeLibs="true" (the debug build's useLegacyPackaging, app/build.gradle.kts: the package manager
#   extracts it at install, and the zip's alignment is nothing to it); and its every LOAD segment aligned 0x4000;
# - stripped: no .debug_* or .symtab section, no .comment, no build-id note;
# - no path of the machine that built it: no "/home/", "/nix/store/", ".cxx/" or "/tmp/" among its strings;
# - libqjs.so a position-independent executable (ELF type DYN with an interpreter, /system/bin/linker64), which
#   Android runs from the app's native library folder.
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
manifest=$("$ANDROID_HOME/build-tools/36.0.0/aapt2" dump xmltree --file AndroidManifest.xml "$apk")
extracted=0
grep -qF 'android:extractNativeLibs(0x010104ea)=true' <<< "$manifest" && extracted=1

for entry in lib/{arm64-v8a,x86_64}/{libcaracole_soxr,libqjs}.so; do
  so=$work/$(tr / _ <<< "$entry")
  if ! unzip -p "$apk" "$entry" > "$so" || [ ! -s "$so" ]; then
    fail "$entry: not in the APK"
    continue
  fi
  if grep -qF "$entry (OK - compressed)" <<< "$aligned"; then
    [ "$extracted" = 1 ] || fail "$entry: compressed in an APK whose native libraries aren't extracted"
  else
    grep -qF "$entry (OK)" <<< "$aligned" || fail "$entry: not stored uncompressed and 16 KB aligned"
  fi
  if "$ndk/llvm-readelf" -lW "$so" | awk '$1 == "LOAD" && $NF != "0x4000"' | grep -q .; then
    fail "$entry: a LOAD segment not aligned 0x4000"
  fi
  sections=$("$ndk/llvm-readelf" -SW "$so")
  for s in .debug_ .symtab .comment .note.gnu.build-id; do
    grep -qF " $s" <<< "$sections" && fail "$entry: has a $s section"
  done
  paths=$("$ndk/llvm-strings" -a "$so" | grep -E '/home/|/nix/store/|\.cxx/|/tmp/' || true)
  [ -z "$paths" ] || fail "$entry: names a path of the build: $(head -3 <<< "$paths" | tr '\n' ' ')"
  if [ "${entry##*/}" = libqjs.so ]; then
    header=$("$ndk/llvm-readelf" -hlW "$so")
    { grep -qE 'Type: +DYN' <<< "$header" && grep -qF '[Requesting program interpreter: /system/bin/linker64]' \
      <<< "$header"; } || fail "$entry: not a position-independent executable for Android's linker64"
  fi
  echo "$(sha256sum "$so" | cut -d' ' -f1)  $entry ($(stat -c %s "$so") bytes)"
done

[ "$failed" = 0 ] && echo "OK: each library packaged as its APK extracts it, aligned, stripped, and naming no path" \
  "of the build"
exit "$failed"
