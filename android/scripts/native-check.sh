#!/usr/bin/env bash
# What an APK's own native code must be: the chord models' (autochords/native/'s libcaracole_soxr.so, packaged by :ml,
# and ONNX Runtime's libonnxruntime.so and libonnxruntime4j_jni.so, built from its source) and libqjs.so (QuickJS-NG's
# qjs, youtube/native/, packaged by :youtube), run inside `nix develop ./android` after a build in the ml shell:
#
#   android/scripts/native-check.sh [--expect extracted|stored] [APK]
#                                  # default: android/app/build/outputs/apk/debug/app-debug.apk
#   android/scripts/native-check.sh [--expect …] --release APK   # the release's: arm64-v8a's alone, no other ABI's
#
# release-check.sh runs it on both APKs it builds. Each library (the four, for arm64-v8a and x86_64 in the debug APK,
# for arm64-v8a alone in the release, all required) must be:
#
# - either stored uncompressed and 16 KB aligned (zipalign -c -P 16), or compressed in an APK whose manifest says
#   android:extractNativeLibs="true" (the debug build's useLegacyPackaging, app/build.gradle.kts: the package manager
#   extracts it at install, and the zip's alignment is nothing to it); with --expect, the one of the two named
#   (extracted: compressed under extractNativeLibs="true", every build's since Y5.1; stored: uncompressed and
#   aligned, the releases' before it), the other a failure; and its every LOAD segment aligned 0x4000;
# - stripped: no .debug_* or .symtab section, no .comment, no build-id note;
# - no path of the machine that built it: no "/home/", "/nix/store/", ".cxx/" or "/tmp/" among its strings;
# - libqjs.so a position-independent executable (ELF type DYN with an interpreter, /system/bin/linker64), which
#   Android runs from the app's native library folder.
#
# It prints each library's SHA-256 (two checkouts at different paths give the same: the design's §7) and exits
# non-zero on any failure.
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
expect=""
release=0
while [ $# -gt 0 ]; do
  case "$1" in
    --expect) expect="${2-}"; shift 2 || shift ;;
    --expect=*) expect="${1#--expect=}"; shift ;;
    --release) release=1; shift ;;
    *) break ;;
  esac
done
case "$expect" in
  ""|extracted|stored) ;;
  *) echo "native-check.sh: --expect takes extracted or stored, not '$expect'" >&2; exit 2 ;;
esac
apk=${1:-$here/app/build/outputs/apk/debug/app-debug.apk}
: "${ANDROID_HOME:?run inside nix develop ./android}"
ndk=$ANDROID_HOME/ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin
zipalign=$ANDROID_HOME/build-tools/36.0.0/zipalign
[ -f "$apk" ] || { echo "no APK at $apk: gradle -p android :app:assembleDebug" >&2; exit 2; }

failed=0
fail() { echo "FAIL: $*"; failed=1; }
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
# zipalign's own verdict is the whole APK's: each entry's line decides below, saying which and why.
aligned=$("$zipalign" -c -P 16 -v 4 "$apk" || true)
manifest=$("$ANDROID_HOME/build-tools/36.0.0/aapt2" dump xmltree --file AndroidManifest.xml "$apk")
extracted=0
grep -qF 'android:extractNativeLibs(0x010104ea)=true' <<< "$manifest" && extracted=1
ours=$(unzip -Z1 "$apk" | grep -E '^lib/[^/]+/(libcaracole_[^/]*|libonnxruntime|libonnxruntime4j_jni|libqjs)\.so$' \
  || true)
libs="libcaracole_soxr.so libonnxruntime.so libonnxruntime4j_jni.so libqjs.so"
if [ "$release" = 1 ]; then
  abis="arm64-v8a"
  # The release's chord models' libraries and its libqjs.so are arm64-v8a's alone (app/build.gradle.kts's
  # releaseMlAbis and releaseYoutubeAbis).
  others=$(grep -v '^lib/arm64-v8a/' <<< "$ours" || true)
  [ -z "$others" ] || fail "the release carries another ABI's: $(tr '\n' ' ' <<< "$others")"
else
  abis="arm64-v8a x86_64"
fi
entries=$(for abi in $abis; do for lib in $libs; do echo "lib/$abi/$lib"; done; done)

for entry in $entries; do
  so=$work/$(tr / _ <<< "$entry")
  if ! grep -qxF "$entry" <<< "$ours" || ! unzip -p "$apk" "$entry" > "$so" || [ ! -s "$so" ]; then
    fail "$entry: not in the APK"
    continue
  fi
  if grep -qF "$entry (OK - compressed)" <<< "$aligned"; then
    [ "$extracted" = 1 ] || fail "$entry: compressed in an APK whose native libraries aren't extracted"
    [ "$expect" != stored ] || fail "$entry: compressed and extracted at install, where --expect stored"
  else
    grep -qF "$entry (OK)" <<< "$aligned" || fail "$entry: not stored uncompressed and 16 KB aligned"
    [ "$expect" != extracted ] || fail "$entry: stored in the APK, where --expect extracted"
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

[ "$failed" = 0 ] && echo "OK: $(wc -w <<< "$entries") libraries packaged as its APK extracts them, aligned, stripped," \
  "naming no path of the build"
exit "$failed"
