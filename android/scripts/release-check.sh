#!/usr/bin/env bash
# What the debug build carries for chords on the phone (:ml, ONNX Runtime, the models' graph and pins) and the release
# doesn't, until the owner chooses what ships (the chords-on-the-phone design's stage S):
#
#   android/scripts/release-check.sh
#
# It builds assembleRelease (unsigned without the release key, android/README.md's "Release": the same packaged
# output, its signature aside) and assembleDebug, then checks the release:
#
# - its runtime classpath names no onnxruntime and no project :ml;
# - its APK holds no lib/*/libonnxruntime*, no class under ai/onnxruntime/ in any classes*.dex (dexdump's
#   descriptors), no entry under caracole/autochords/, and its manifest (aapt2's dump) no TelemetryInitializer;
#
# and the debug APK as the control, so that no probe passes for nothing: it holds every one of them but the
# provider, which :ml's manifest removes from it too. It prints each check and exits non-zero on any failure.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
repo="$(dirname "$android")"

cd "$repo"
nix develop ./android -c gradle -p android :app:assembleRelease :app:assembleDebug --console=plain -q
release="$(ls "$android"/app/build/outputs/apk/release/app-release*.apk | head -1)"
debug="$android/app/build/outputs/apk/debug/app-debug.apk"
classpath="$(nix develop ./android -c gradle -p android :app:dependencies --configuration releaseRuntimeClasspath \
    --console=plain -q)"
probe="$(mktemp -d "${TMPDIR:-/tmp}/caracole-release-check-XXXXXX")"
trap 'rm -rf "$probe"' EXIT

# One APK's probes, a count each: "libs classes autochords provider providers" (the last, every provider the
# manifest declares: the dump read is a manifest's).
probes() {
    local apk="$1" dexes=0 classes=0 dex
    rm -rf "$probe/dex" && mkdir "$probe/dex"
    unzip -q -o "$apk" 'classes*.dex' -d "$probe/dex"
    for dex in "$probe"/dex/classes*.dex; do
        dexes=$((dexes + 1))
        classes=$((classes + $(nix develop ./android -c sh -c \
            '"$ANDROID_HOME"/build-tools/36.0.0/dexdump "$1"' sh "$dex" 2>/dev/null \
            | grep -c "Class descriptor *: 'Lai/onnxruntime/" || true)))
    done
    [ "$dexes" -gt 0 ] || { echo "release-check.sh: no classes*.dex in $apk" >&2; exit 2; }
    nix develop ./android -c sh -c '"$ANDROID_HOME"/build-tools/36.0.0/aapt2 dump xmltree --file AndroidManifest.xml \
        "$1"' sh "$apk" >"$probe/manifest"
    echo "$(unzip -Z1 "$apk" | grep -c '^lib/.*/libonnxruntime' || true)" \
        "$classes" \
        "$(unzip -Z1 "$apk" | grep -c '^caracole/autochords/' || true)" \
        "$(grep -c 'TelemetryInitializer' "$probe/manifest" || true)" \
        "$(grep -c 'E: provider' "$probe/manifest" || true)"
}

failed=0
check() {  # check WHAT OK: OK is 1 when it holds
    if [ "$2" = 1 ]; then echo "ok    $1"; else echo "FAIL  $1"; failed=1; fi
}

check "release classpath names no onnxruntime" "$([ "$(grep -ci onnxruntime <<<"$classpath" || true)" = 0 ] && echo 1)"
check "release classpath names no project :ml" "$([ "$(grep -c 'project :ml' <<<"$classpath" || true)" = 0 ] && echo 1)"

read -r libs classes autochords provider providers < <(probes "$release")
echo "release APK $release: $libs libonnxruntime*, $classes classes under ai/onnxruntime/," \
    "$autochords entries under caracole/autochords/," \
    "$provider TelemetryInitializer of its manifest's $providers providers"
check "release APK's manifest read (it declares providers)" "$([ "$providers" -gt 0 ] && echo 1)"
check "release APK holds no libonnxruntime*" "$([ "$libs" = 0 ] && echo 1)"
check "release APK holds no class under ai/onnxruntime/" "$([ "$classes" = 0 ] && echo 1)"
check "release APK holds nothing under caracole/autochords/" "$([ "$autochords" = 0 ] && echo 1)"
check "release APK's manifest declares no TelemetryInitializer" "$([ "$provider" = 0 ] && echo 1)"

read -r libs classes autochords provider providers < <(probes "$debug")
echo "debug APK (the control): $libs libonnxruntime*, $classes classes under ai/onnxruntime/," \
    "$autochords entries under caracole/autochords/," \
    "$provider TelemetryInitializer of its manifest's $providers providers"
check "the control: the debug APK holds libonnxruntime*" "$([ "$libs" -gt 0 ] && echo 1)"
check "the control: the debug APK holds classes under ai/onnxruntime/" "$([ "$classes" -gt 0 ] && echo 1)"
check "the control: the debug APK holds caracole/autochords/" "$([ "$autochords" -gt 0 ] && echo 1)"
check "the debug APK's manifest declares no TelemetryInitializer either" "$([ "$provider" = 0 ] && echo 1)"

exit "$failed"
