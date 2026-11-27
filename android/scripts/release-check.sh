#!/usr/bin/env bash
# What the release carries for chords on the phone and what it doesn't (the chords-on-the-phone design's §7, stage S):
#
#   android/scripts/release-check.sh
#
# It builds assembleRelease (unsigned without the release key, android/README.md's "Release": the same packaged
# output, its signature aside; its checkApkSize the 100 MiB cap) and assembleDebug in flake.nix's ml shell, the one with
# :ml (its CARACOLE_ONNXRUNTIME: the runtime's one-off build a machine; a release is never made without it), each APK
# read by the name its output-metadata.json gives (never a stale one beside it), then checks the release:
#
# - its runtime classpath names onnxruntime and project :ml (and project :core: the tree was read);
# - its APK holds ONNX Runtime's and libsoxr's libraries for arm64-v8a and for no other ABI (SQLite's for both), classes
#   under ai/onnxruntime/ and of :ml (dexdump's descriptors), caracole/autochords/ (BTC's graph and the pins), one model
#   file, BTC's graph (no weights' file: the phone fetches them), MlService in its ":ml" process, and none of the
#   Chords bench (no "ChordsBench", "BenchService" or Settings' row's words, "Chords bench", in its dex; no
#   assets/autochords/, the bench's clips; no ChordsBenchActivity, BenchService or BenchWorkerService, ":bench" or
#   ":benchrun" process or FOREGROUND_SERVICE_SPECIAL_USE in its manifest, aapt2's dump), no TelemetryInitializer;
# - its size: 100 MiB at most;
#
# and the controls, so that no probe passes for nothing:
#
# - the debug APK holds the bench and x86_64's libraries of the runtime;
# - the model files' names, those `nix build .#chord-models` makes ($CARACOLE_CHORD_MODELS, else the ./android#ml
#   shell's), are each one the model-file probe matches, and the weights' probe all but BTC's graph;
# - the runtime's AAR (ONNX Runtime built from its source, the ml shell's $CARACOLE_ONNXRUNTIME) declares no provider;
# - and ApkScanTest (`gradle :app:apkScan`, in the ml shell) finds none of what made Maven's AAR phone home
#   (mobile.events.data.microsoft.com, ai.onnxruntime.TelemetryInitializer, its ai/onnxruntime/telemetry/ client) in
#   either APK, nor in the runtime's AAR, its own control finding each where it would be;
# - and native-check.sh on both APKs: the runtime's and libsoxr's libraries (both ABIs in the debug APK, arm64-v8a's
#   alone in the release's) stored aligned, stripped and naming no path of the build.
#
# It prints each check and exits non-zero on any failure.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
repo="$(dirname "$android")"

cd "$repo"
nix develop ./android#ml -c gradle -p android :app:assembleRelease :app:assembleDebug --console=plain -q
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
    nix develop ./android#ml -c gradle -p android :app:dependencies --configuration "$1RuntimeClasspath" \
        --console=plain -q
}
classpath="$(classpath_of release)"
models="${CARACOLE_CHORD_MODELS:-$(nix develop ./android#ml -c printenv CARACOLE_CHORD_MODELS)}"
probe="$(mktemp -d "${TMPDIR:-/tmp}/caracole-release-check-XXXXXX")"
trap 'rm -rf "$probe"' EXIT

model_file='\.(onnx|pt)$'
weights_file='(^|/)(btc_model_large_voca\.pt|beat_this[^/]*\.onnx)$'

# One APK's probes, a count each: "arm64 x86 soxr86 sqlite86 ortclasses mlclasses benchdex rowwords autochords assets
# models weights provider benchmanifest providers mlmanifest" (arm64 and x86: ONNX Runtime's libraries of each ABI;
# soxr86, x86_64's libsoxr; sqlite86, x86_64's SQLite; providers, every provider the manifest declares: the dump read is
# a manifest's; mlmanifest, the chord models' service, MlService, and its ":ml" process).
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
        # Settings' row's words as a string of their own in the dex (its length byte, the words, its end): never
        # "the Chords bench's" inside :ml's busy message, which the release says too.
        rowwords=$((rowwords + $({ grep -a -o -P '\x0cChords bench\x00' "$dex" || true; } | wc -l)))
    done
    [ "$dexes" -gt 0 ] || { echo "release-check.sh: no classes*.dex in $apk" >&2; exit 2; }
    nix develop ./android -c sh -c '"$ANDROID_HOME"/build-tools/36.0.0/aapt2 dump xmltree --file AndroidManifest.xml \
        "$1"' sh "$apk" >"$probe/manifest"
    unzip -Z1 "$apk" >"$probe/entries"
    echo "$(grep -c '^lib/arm64-v8a/libonnxruntime' "$probe/entries" || true)" \
        "$(grep -c '^lib/x86_64/libonnxruntime' "$probe/entries" || true)" \
        "$(grep -c '^lib/x86_64/libcaracole_soxr' "$probe/entries" || true)" \
        "$(grep -c '^lib/x86_64/libsqliteJni' "$probe/entries" || true)" \
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
check "release classpath names onnxruntime" "$(yes_if '[ "$(grep -ci onnxruntime <<<"$classpath" || true)" -gt 0 ]')"
check "release classpath names project :ml" "$(yes_if '[ "$(grep -c "project :ml" <<<"$classpath" || true)" -gt 0 ]')"

read -r arm64 x86 soxr86 sqlite86 ortclasses mlclasses benchdex rowwords autochords assets modelfiles weights provider \
    benchmanifest providers mlmanifest < <(probes "$release")
size="$(stat -c %s "$release")"
echo "release APK $release, $size bytes: $arm64 libonnxruntime* for arm64-v8a, $x86 and $soxr86 libsoxr for x86_64" \
    "($sqlite86 SQLite), $ortclasses classes under ai/onnxruntime/, $mlclasses of :ml, $benchdex bench names and" \
    "$rowwords of Settings' row's words in its dex, $autochords entries under caracole/autochords/, $assets under" \
    "assets/autochords/, $modelfiles model files ($weights the weights'), $provider TelemetryInitializer," \
    "$benchmanifest bench entries and $mlmanifest of the chord models' service of its manifest (of $providers providers)"
check "release APK's manifest read (it declares providers)" "$(yes_if '[ "$providers" -gt 0 ]')"
check "release APK holds ONNX Runtime's two libraries for arm64-v8a" "$(yes_if '[ "$arm64" = 2 ]')"
check "release APK holds no chord models' library for x86_64 (ONNX Runtime's, libsoxr)" \
    "$(yes_if '[ "$x86" = 0 ] && [ "$soxr86" = 0 ]')"
check "release APK still holds SQLite's library for x86_64" "$(yes_if '[ "$sqlite86" = 1 ]')"
check "release APK holds classes under ai/onnxruntime/" "$(yes_if '[ "$ortclasses" -gt 0 ]')"
check "release APK holds classes of :ml" "$(yes_if '[ "$mlclasses" -gt 0 ]')"
check "release APK holds caracole/autochords/ (BTC's graph, the pins)" "$(yes_if '[ "$autochords" -gt 0 ]')"
check "release APK holds one model file, BTC's graph, and no weights' file" \
    "$(yes_if '[ "$modelfiles" = 1 ] && [ "$weights" = 0 ]')"
check "release APK's manifest declares MlService in its :ml process" "$(yes_if '[ "$mlmanifest" -ge 2 ]')"
check "release APK's dex names no ChordsBench or BenchService" "$(yes_if '[ "$benchdex" = 0 ]')"
check "release APK's dex holds no \"Chords bench\" (Settings' row)" "$(yes_if '[ "$rowwords" = 0 ]')"
check "release APK holds nothing under assets/autochords/ (the bench's clips)" "$(yes_if '[ "$assets" = 0 ]')"
check "release APK's manifest has no trace of the bench" "$(yes_if '[ "$benchmanifest" = 0 ]')"
check "release APK's manifest declares no TelemetryInitializer" "$(yes_if '[ "$provider" = 0 ]')"
check "release APK is 100 MiB at most" "$(yes_if '[ "$size" -le $((100 * 1024 * 1024)) ]')"

read -r arm64 x86 soxr86 sqlite86 ortclasses mlclasses benchdex rowwords autochords assets modelfiles weights provider \
    benchmanifest providers mlmanifest < <(probes "$debug")
echo "debug APK (the control) $debug, $(stat -c %s "$debug") bytes: $arm64 and $x86 libonnxruntime* (arm64-v8a," \
    "x86_64), $soxr86 libsoxr for x86_64, $benchdex bench names and $rowwords of Settings' row's words in its dex," \
    "$assets under assets/autochords/, $modelfiles model files ($weights the weights'), $provider" \
    "TelemetryInitializer, $benchmanifest bench entries and $mlmanifest of the chord models' service (of $providers" \
    "providers)"
check "the control: the debug APK holds ONNX Runtime's and libsoxr's libraries for x86_64" \
    "$(yes_if '[ "$x86" = 2 ] && [ "$soxr86" = 1 ]')"
check "the control: the debug APK's dex names the bench" "$(yes_if '[ "$benchdex" -gt 0 ]')"
check "the control: the debug APK's dex holds \"Chords bench\"" "$(yes_if '[ "$rowwords" -gt 0 ]')"
check "the control: the debug APK holds assets/autochords/ (the clips)" "$(yes_if '[ "$assets" -gt 0 ]')"
check "the control: the debug APK's manifest declares the bench" "$(yes_if '[ "$benchmanifest" -gt 0 ]')"
check "the debug APK holds none of the weights' files either" "$(yes_if '[ "$weights" = 0 ]')"
check "the debug APK's manifest declares no TelemetryInitializer either" "$(yes_if '[ "$provider" = 0 ]')"

# The model-file probe matches every file the models' build makes, and the weights' probe all but BTC's graph.
names="$(ls "$models")"
echo "the model files ($models): $(tr '\n' ' ' <<<"$names")"
check "the control: the model-file probe matches each of them" \
    "$(yes_if '[ "$(grep -c -v -E "$model_file" <<<"$names" || true)" = 0 ] && [ -n "$names" ]')"
check "the control: the weights' probe matches each but btc-graph.onnx" \
    "$(yes_if '[ "$(grep -v -E "$weights_file" <<<"$names" || true)" = btc-graph.onnx ]')"

# The runtime's AAR, built from its source, declares no provider (Maven's declared ai.onnxruntime.TelemetryInitializer).
ort_maven="$(nix develop ./android#ml -c printenv CARACOLE_ONNXRUNTIME)"
aar="$(find "$ort_maven" -name '*.aar' | head -1)"
providers_declared=1
[ -n "$aar" ] && providers_declared="$(unzip -p "$aar" AndroidManifest.xml | grep -c '<provider' || true)"
echo "ONNX Runtime's AAR: ${aar:-none in $ort_maven}"
check "the runtime's AAR (from source) declares no provider" "$(yes_if '[ -n "$aar" ] && [ "$providers_declared" = 0 ]')"
echo "ApkScanTest (gradle :app:apkScan):"
if nix develop ./android#ml -c gradle -p android :app:apkScan --console=plain -q; then scanned=1; else scanned=0; fi
check "ApkScanTest: no telemetry host, provider or client in the APKs or the runtime's AAR" "$scanned"

# The chord models' native libraries (native-check.sh): stored aligned, stripped and naming no path of the build, both
# ABIs' in the debug APK, arm64-v8a's alone in the release's.
echo "native-check.sh, the debug APK:"
if nix develop ./android -c "$here/native-check.sh" "$debug"; then native=1; else native=0; fi
check "the debug APK's runtime and libsoxr, both ABIs: aligned, stripped, no build path (native-check.sh)" "$native"
echo "native-check.sh, the release APK:"
if nix develop ./android -c "$here/native-check.sh" --release "$release"; then native=1; else native=0; fi
check "the release APK's runtime and libsoxr, arm64-v8a's alone: aligned, stripped, no build path" "$native"

exit "$failed"
