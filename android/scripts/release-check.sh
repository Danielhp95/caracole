#!/usr/bin/env bash
# What the debug build carries for chords on the phone (:ml, ONNX Runtime, the models' graph and pins, the Chords
# bench and its clips) and the release doesn't, until the owner chooses what ships (the chords-on-the-phone design's
# stage S):
#
#   android/scripts/release-check.sh
#
# It builds assembleRelease (unsigned without the release key, android/README.md's "Release": the same packaged
# output, its signature aside) and assembleDebug, each APK read by the name its output-metadata.json gives (never a
# stale one beside it), then checks the release:
#
# - its runtime classpath names no onnxruntime and no project :ml (and names project :core: the tree was read);
# - its APK holds no lib/*/libonnxruntime*, no class under ai/onnxruntime/ or of :ml (io/github/danielhp95/caracole/ml/)
#   in any classes*.dex (dexdump's descriptors), no "ChordsBench" or "BenchService" or Settings' row's words
#   ("Chords bench") in its dex, no entry under caracole/autochords/ or assets/autochords/, no model file (an entry
#   ending .onnx or .pt), and its manifest (aapt2's dump) no TelemetryInitializer, no ChordsBenchActivity,
#   BenchService or BenchWorkerService, no ":bench" or ":benchrun" process and no FOREGROUND_SERVICE_SPECIAL_USE, and
#   no MlService (the chord models' service) and no ":ml" process;
#
# and the controls, so that no probe passes for nothing:
#
# - the debug classpath names onnxruntime;
# - the debug APK holds every one of them but the provider (which :ml's manifest removes from it too) and the model
#   files: it carries BTC's graph (an .onnx) and never the weights' files, btc_model_large_voca.pt and beat_this's,
#   which no APK holds (the owner's folder does: android/README.md, "The Chords bench");
# - the model files' names, those `nix build .#chord-models` makes ($CARACOLE_CHORD_MODELS, else the ./android#ml
#   shell's), are each one the model-file probe matches;
# - ONNX Runtime's AAR in Gradle's cache declares the TelemetryInitializer the manifest probe looks for.
#
# - and native-check.sh on both APKs: the debug one's libcaracole_soxr.so (both ABIs) stored aligned, stripped and
#   naming no path of the build; the release's libcaracole_*, none today, which passes saying so.
#
# It prints each check and exits non-zero on any failure.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
repo="$(dirname "$android")"
ort=1.32.0

cd "$repo"
nix develop ./android -c gradle -p android :app:assembleRelease :app:assembleDebug --console=plain -q
# The APK of a variant, by the name the build wrote it under (output-metadata.json's outputFile).
apk_of() {
    local out="$android/app/build/outputs/apk/$1" name
    name="$(sed -n 's/.*"outputFile": *"\([^"]*\)".*/\1/p' "$out/output-metadata.json" | head -1)"
    [ -n "$name" ] && [ -f "$out/$name" ] || { echo "release-check.sh: no $1 APK in $out" >&2; exit 2; }
    echo "$out/$name"
}
release="$(apk_of release)"
debug="$(apk_of debug)"
classpath_of() {
    nix develop ./android -c gradle -p android :app:dependencies --configuration "$1RuntimeClasspath" \
        --console=plain -q
}
classpath="$(classpath_of release)"
debug_classpath="$(classpath_of debug)"
models="${CARACOLE_CHORD_MODELS:-$(nix develop ./android#ml -c printenv CARACOLE_CHORD_MODELS)}"
probe="$(mktemp -d "${TMPDIR:-/tmp}/caracole-release-check-XXXXXX")"
trap 'rm -rf "$probe"' EXIT

model_file='\.(onnx|pt)$'
weights_file='(^|/)(btc_model_large_voca\.pt|beat_this[^/]*\.onnx)$'

# One APK's probes, a count each: "libs ortclasses mlclasses benchdex rowwords autochords assets models weights
# provider benchmanifest providers mlmanifest" (providers, every provider the manifest declares: the dump read is a
# manifest's; mlmanifest, the chord models' service, MlService, and its ":ml" process).
probes() {
    local apk="$1" dexes=0 ortclasses=0 mlclasses=0 benchdex=0 rowwords=0 dex dump
    rm -rf "$probe/dex" && mkdir "$probe/dex"
    unzip -q -o "$apk" 'classes*.dex' -d "$probe/dex"
    for dex in "$probe"/dex/classes*.dex; do
        dexes=$((dexes + 1))
        dump="$(nix develop ./android -c sh -c '"$ANDROID_HOME"/build-tools/36.0.0/dexdump "$1"' sh "$dex" 2>/dev/null)"
        ortclasses=$((ortclasses + $(grep -c "Class descriptor *: 'Lai/onnxruntime/" <<<"$dump" || true)))
        mlclasses=$((mlclasses + $(grep -c "Class descriptor *: 'Lio/github/danielhp95/caracole/ml/" <<<"$dump" \
            || true)))
        benchdex=$((benchdex + $({ grep -a -o -E 'ChordsBench|BenchService' "$dex" || true; } | wc -l)))
        rowwords=$((rowwords + $({ grep -a -o 'Chords bench' "$dex" || true; } | wc -l)))
    done
    [ "$dexes" -gt 0 ] || { echo "release-check.sh: no classes*.dex in $apk" >&2; exit 2; }
    nix develop ./android -c sh -c '"$ANDROID_HOME"/build-tools/36.0.0/aapt2 dump xmltree --file AndroidManifest.xml \
        "$1"' sh "$apk" >"$probe/manifest"
    unzip -Z1 "$apk" >"$probe/entries"
    echo "$(grep -c '^lib/.*/libonnxruntime' "$probe/entries" || true)" \
        "$ortclasses" "$mlclasses" "$benchdex" "$rowwords" \
        "$(grep -c '^caracole/autochords/' "$probe/entries" || true)" \
        "$(grep -c '^assets/autochords/' "$probe/entries" || true)" \
        "$(grep -c -E "$model_file" "$probe/entries" || true)" \
        "$(grep -c -E "$weights_file" "$probe/entries" || true)" \
        "$(grep -c 'TelemetryInitializer' "$probe/manifest" || true)" \
        "$(grep -c -E 'ChordsBenchActivity|Bench(Worker)?Service|:bench(run)?"|FOREGROUND_SERVICE_SPECIAL_USE' \
            "$probe/manifest" || true)" \
        "$(grep -c 'E: provider' "$probe/manifest" || true)" \
        "$(grep -c -E 'MlService|:ml"' "$probe/manifest" || true)"
}

failed=0
check() {  # check WHAT OK: OK is 1 when it holds
    if [ "$2" = 1 ]; then echo "ok    $1"; else echo "FAIL  $1"; failed=1; fi
}
yes_if() { if eval "$1"; then echo 1; else echo 0; fi; }

check "release classpath read (it names project :core)" \
    "$(yes_if '[ "$(grep -c "project :core" <<<"$classpath" || true)" -gt 0 ]')"
check "release classpath names no onnxruntime" "$(yes_if '[ "$(grep -ci onnxruntime <<<"$classpath" || true)" = 0 ]')"
check "release classpath names no project :ml" "$(yes_if '[ "$(grep -c "project :ml" <<<"$classpath" || true)" = 0 ]')"
check "the control: the debug classpath names onnxruntime" \
    "$(yes_if '[ "$(grep -ci onnxruntime <<<"$debug_classpath" || true)" -gt 0 ]')"

read -r libs ortclasses mlclasses benchdex rowwords autochords assets modelfiles weights provider benchmanifest \
    providers mlmanifest \
    < <(probes "$release")
echo "release APK $release: $libs libonnxruntime*, $ortclasses classes under ai/onnxruntime/, $mlclasses of :ml," \
    "$benchdex bench names and $rowwords of Settings' row's words in its dex, $autochords entries under" \
    "caracole/autochords/, $assets under" \
    "assets/autochords/, $modelfiles model files, $provider TelemetryInitializer, $benchmanifest bench entries" \
    "and $mlmanifest of the chord models' service of its manifest (of $providers providers)"
check "release APK's manifest read (it declares providers)" "$(yes_if '[ "$providers" -gt 0 ]')"
check "release APK holds no libonnxruntime*" "$(yes_if '[ "$libs" = 0 ]')"
check "release APK holds no class under ai/onnxruntime/" "$(yes_if '[ "$ortclasses" = 0 ]')"
check "release APK holds no class of :ml" "$(yes_if '[ "$mlclasses" = 0 ]')"
check "release APK's dex names no ChordsBench or BenchService" "$(yes_if '[ "$benchdex" = 0 ]')"
check "release APK's dex holds no \"Chords bench\" (Settings' row)" "$(yes_if '[ "$rowwords" = 0 ]')"
check "release APK holds nothing under caracole/autochords/" "$(yes_if '[ "$autochords" = 0 ]')"
check "release APK holds nothing under assets/autochords/" "$(yes_if '[ "$assets" = 0 ]')"
check "release APK holds no model file (.onnx, .pt)" "$(yes_if '[ "$modelfiles" = 0 ]')"
check "release APK's manifest declares no TelemetryInitializer" "$(yes_if '[ "$provider" = 0 ]')"
check "release APK's manifest has no trace of the bench" "$(yes_if '[ "$benchmanifest" = 0 ]')"
check "release APK's manifest has no MlService and no :ml process" "$(yes_if '[ "$mlmanifest" = 0 ]')"

read -r libs ortclasses mlclasses benchdex rowwords autochords assets modelfiles weights provider benchmanifest \
    providers mlmanifest \
    < <(probes "$debug")
echo "debug APK (the control) $debug, $(stat -c %s "$debug") bytes: $libs libonnxruntime*, $ortclasses classes" \
    "under ai/onnxruntime/, $mlclasses of :ml, $benchdex bench names and $rowwords of Settings' row's words in its" \
    "dex, $autochords entries under" \
    "caracole/autochords/, $assets under assets/autochords/, $modelfiles model files ($weights the weights')," \
    "$provider TelemetryInitializer, $benchmanifest bench entries and $mlmanifest of the chord models' service of" \
    "its manifest (of $providers providers)"
check "the control: the debug APK holds libonnxruntime*" "$(yes_if '[ "$libs" -gt 0 ]')"
check "the control: the debug APK holds classes under ai/onnxruntime/" "$(yes_if '[ "$ortclasses" -gt 0 ]')"
check "the control: the debug APK holds classes of :ml" "$(yes_if '[ "$mlclasses" -gt 0 ]')"
check "the control: the debug APK's dex names the bench" "$(yes_if '[ "$benchdex" -gt 0 ]')"
check "the control: the debug APK's dex holds \"Chords bench\"" "$(yes_if '[ "$rowwords" -gt 0 ]')"
check "the control: the debug APK holds caracole/autochords/" "$(yes_if '[ "$autochords" -gt 0 ]')"
check "the control: the debug APK holds assets/autochords/ (the clips)" "$(yes_if '[ "$assets" -gt 0 ]')"
check "the control: the debug APK holds a model file (BTC's graph)" "$(yes_if '[ "$modelfiles" -gt 0 ]')"
check "the debug APK holds none of the weights' files either" "$(yes_if '[ "$weights" = 0 ]')"
check "the control: the debug APK's manifest declares the bench" "$(yes_if '[ "$benchmanifest" -gt 0 ]')"
check "the control: the debug APK's manifest declares MlService in its :ml process" \
    "$(yes_if '[ "$mlmanifest" -ge 2 ]')"
check "the debug APK's manifest declares no TelemetryInitializer either" "$(yes_if '[ "$provider" = 0 ]')"

# The model-file probe matches every file the models' build makes, and the weights' probe all but BTC's graph.
names="$(ls "$models")"
echo "the model files ($models): $(tr '\n' ' ' <<<"$names")"
check "the control: the model-file probe matches each of them" \
    "$(yes_if '[ "$(grep -c -v -E "$model_file" <<<"$names" || true)" = 0 ] && [ -n "$names" ]')"
check "the control: the weights' probe matches each but btc-graph.onnx" \
    "$(yes_if '[ "$(grep -v -E "$weights_file" <<<"$names" || true)" = btc-graph.onnx ]')"

# The string the manifest probe looks for is the one the runtime's AAR declares.
aar="$(find "${GRADLE_USER_HOME:-$HOME/.gradle}/caches/modules-2" -name "onnxruntime-android-$ort.aar" 2>/dev/null \
    | head -1)"
declared=0
[ -n "$aar" ] && declared="$(unzip -p "$aar" AndroidManifest.xml | grep -c 'ai.onnxruntime.TelemetryInitializer' \
    || true)"
echo "ONNX Runtime's AAR: ${aar:-none in the Gradle cache}"
check "the control: the AAR's own manifest declares ai.onnxruntime.TelemetryInitializer" \
    "$(yes_if '[ "$declared" -gt 0 ]')"

# Our own native libraries (native-check.sh): the debug APK's libcaracole_soxr.so, both ABIs, stored aligned,
# stripped and naming no path of the build; the release's, none today, held to the same if one ever comes.
echo "native-check.sh, the debug APK:"
if nix develop ./android -c "$here/native-check.sh" "$debug"; then native=1; else native=0; fi
check "the debug APK's libcaracole_soxr.so: aligned, stripped, no build path (native-check.sh)" "$native"
echo "native-check.sh, the release APK:"
if nix develop ./android -c "$here/native-check.sh" --release "$release"; then native=1; else native=0; fi
check "the release APK's libcaracole_*, if any: aligned, stripped, no build path (native-check.sh)" "$native"

exit "$failed"
