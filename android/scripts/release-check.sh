#!/usr/bin/env bash
# What the release carries for chords on the phone and what it doesn't (the chords-on-the-phone design's §7, stage S),
# and what the debug build carries for YouTube on the phone (:youtube, Chaquopy's Python and yt-dlp) and the release
# doesn't, until the owner's gate (the phone-youtube design's stage Y5):
#
#   android/scripts/release-check.sh
#
# It builds assembleRelease (unsigned without the release key, android/README.md's "Release": the same packaged
# output, its signature aside; its checkApkSize the 100 MiB cap) and assembleDebug in flake.nix's ml shell, the one with
# :ml (its CARACOLE_ONNXRUNTIME: the runtime's one-off build a machine; a release is never made without it), each APK
# read by the name its output-metadata.json gives (never a stale one beside it), then checks the release:
#
# - its runtime classpath names onnxruntime and project :ml (and project :core: the tree was read), and no project
#   :youtube (Chaquopy's runtime is no dependency of it, its plugin packages it, so the APK's probes below hold it);
# - its APK holds ONNX Runtime's and libsoxr's libraries for arm64-v8a and for no other ABI (SQLite's for both), classes
#   under ai/onnxruntime/ and of :ml (dexdump's descriptors), caracole/autochords/ (BTC's graph and the pins), one model
#   file, BTC's graph (no weights' file: the phone fetches them), MlService in its ":ml" process, and none of the
#   Chords bench (no "ChordsBench", "BenchService" or Settings' row's words, "Chords bench", in its dex; no
#   assets/autochords/, the bench's clips; no ChordsBenchActivity, BenchService or BenchWorkerService, ":bench" or
#   ":benchrun" process or FOREGROUND_SERVICE_SPECIAL_USE in its manifest, aapt2's dump), no TelemetryInitializer;
# - and of Python: no lib/*/libpython*, no libchaquopy_java.so, none of the libraries Chaquopy's Python links
#   (lib<name>_python.so, lib<name>_chaquopy.so: OpenSSL's, SQLite's), no class under com/chaquo/ (Chaquopy's) in its
#   dex and no entry under assets/chaquopy/ (the standard library, yt-dlp, the glue);
# - and of :youtube's own: no class under io/github/danielhp95/caracole/youtube/ in its dex, and its manifest no
#   YtDlpService, GateService or ":youtube" process;
# - and of the YouTube bench: no "YouTubeBench" or Settings' row's words ("YouTube bench") in its dex, and its manifest
#   no YouTubeBenchActivity, YouTubeBenchLedger or ":ytbench" process;
# - and of QuickJS-NG: no lib/*/libqjs.so; and its native libraries packaged as before the debug build's
#   useLegacyPackaging (app/build.gradle.kts): every lib/*/*.so entry of the APK stored uncompressed and 16 KB aligned
#   (zipalign -c -P 16's "(OK)", counted against the APK's own lib/*/*.so entries, so one zipalign leaves unsaid
#   fails too), none compressed, and no android:extractNativeLibs="true" in its manifest;
# - the licences of what the chord models ship, under assets/chords/licenses/, each its source's bytes: ONNX Runtime's
#   LICENSE and ThirdPartyNotices.txt (from its AAR), libsoxr's LICENCE and COPYING.LGPL and PFFFT's (pffft.c's own,
#   verbatim), BTC's and beat_this's, and the README saying where the source is;
# - its size: 100 MiB at most;
#
# and the controls, so that no probe passes for nothing:
#
# - the debug classpath names project :youtube;
# - the debug APK holds the bench, x86_64's libraries of the runtime, the YouTube bench, each of Python's native-library
#   probes, Chaquopy's classes and assets/chaquopy/, :youtube's classes and services, libqjs.so, and its native
#   libraries compressed under android:extractNativeLibs="true";
# - the model files' names, those `nix build .#chord-models` makes ($CARACOLE_CHORD_MODELS, else the ./android#ml
#   shell's), are each one the model-file probe matches, and the weights' probe all but BTC's graph;
# - the runtime's AAR (ONNX Runtime built from its source, the ml shell's $CARACOLE_ONNXRUNTIME) declares no provider;
# - and ApkScanTest (`gradle :app:apkScan`, in the ml shell) finds none of what made Maven's AAR phone home
#   (mobile.events.data.microsoft.com, ai.onnxruntime.TelemetryInitializer, its ai/onnxruntime/telemetry/ client) in
#   either APK, nor in the runtime's AAR, its own control finding each where it would be;
# - and native-check.sh on both APKs: the runtime's, libsoxr's and libqjs.so (both ABIs in the debug APK, compressed and
#   extracted at install; the chord models' arm64-v8a's alone in the release's, stored aligned), stripped and naming no
#   path of the build.
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
debug_classpath="$(classpath_of debug)"
models="${CARACOLE_CHORD_MODELS:-$(nix develop ./android#ml -c printenv CARACOLE_CHORD_MODELS)}"
probe="$(mktemp -d "${TMPDIR:-/tmp}/caracole-release-check-XXXXXX")"
trap 'rm -rf "$probe"' EXIT

model_file='\.(onnx|pt)$'
weights_file='(^|/)(btc_model_large_voca\.pt|beat_this[^/]*\.onnx)$'

# One APK's probes, a count each: "arm64 x86 soxr86 sqlite86 ortclasses mlclasses benchdex rowwords autochords assets
# models weights provider benchmanifest providers pylibs chaquojni chaquolinked chaquoclasses chaquoassets ytclasses
# ytmanifest ytbenchdex ytbenchmanifest mlmanifest" (arm64 and x86: ONNX Runtime's libraries of each ABI; soxr86,
# x86_64's libsoxr; sqlite86, x86_64's SQLite; providers, every provider the manifest declares: the dump read is a
# manifest's; ytclasses, classes of :youtube, io/github/danielhp95/caracole/youtube/, in its dex; ytmanifest, the
# manifest's YtDlpService, GateService or ":youtube" process; ytbenchdex, "YouTubeBench" or Settings' "YouTube bench"
# row's words in its dex; ytbenchmanifest, the manifest's YouTubeBenchActivity, YouTubeBenchLedger or ":ytbench"
# process; mlmanifest, the chord models' service, MlService, and its ":ml" process).
probes() {
    local apk="$1" dexes=0 ortclasses=0 mlclasses=0 benchdex=0 rowwords=0 chaquoclasses=0 ytclasses=0 ytbenchdex=0 dex
    local dump
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
        ytbenchdex=$((ytbenchdex + $({ grep -a -o -E 'YouTubeBench|YouTube bench' "$dex" || true; } | wc -l)))
        chaquoclasses=$((chaquoclasses + $(grep -c "Class descriptor *: 'Lcom/chaquo/" <<<"$dump" || true)))
        ytclasses=$((ytclasses + $(grep -c "Class descriptor *: 'Lio/github/danielhp95/caracole/youtube/" <<<"$dump" \
            || true)))
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
        "$(grep -c '^lib/[^/]*/libpython' "$probe/entries" || true)" \
        "$(grep -c '^lib/[^/]*/libchaquopy_java\.so$' "$probe/entries" || true)" \
        "$(grep -c -E '^lib/[^/]*/lib[a-z0-9]+_(python|chaquopy)\.so$' "$probe/entries" || true)" \
        "$chaquoclasses" \
        "$(grep -c '^assets/chaquopy/' "$probe/entries" || true)" \
        "$ytclasses" \
        "$(grep -c -E 'YtDlpService|GateService|:youtube"' "$probe/manifest" || true)" \
        "$ytbenchdex" \
        "$(grep -c -E 'YouTubeBench(Activity|Ledger)|:ytbench"' "$probe/manifest" || true)" \
        "$(grep -c -E 'MlService|:ml"' "$probe/manifest" || true)"
}

# One APK's native libraries: "qjs stored compressed extracted total" (libqjs.so entries; lib/*/*.so stored
# uncompressed and 16 KB aligned, and compressed; 1 when its manifest says android:extractNativeLibs="true"; every
# lib/*/*.so entry of the APK, whatever zipalign said of it), after probes of the same APK, whose entries and manifest
# it reads.
natives() {
    local aligned
    aligned="$(nix develop ./android -c sh -c '"$ANDROID_HOME"/build-tools/36.0.0/zipalign -c -P 16 -v 4 "$1"' sh "$1")"
    echo "$(grep -c '^lib/[^/]*/libqjs\.so$' "$probe/entries" || true)" \
        "$(grep -c -E '^ *[0-9]+ lib/[^/]+/[^/]+\.so \(OK\)$' <<<"$aligned" || true)" \
        "$(grep -c -E '^ *[0-9]+ lib/[^/]+/[^/]+\.so \(OK - compressed\)$' <<<"$aligned" || true)" \
        "$(grep -c -F 'android:extractNativeLibs(0x010104ea)=true' "$probe/manifest" || true)" \
        "$(grep -c -E '^lib/[^/]+/[^/]+\.so$' "$probe/entries" || true)"
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
check "release classpath names no project :youtube" \
    "$(yes_if '[ "$(grep -c "project :youtube" <<<"$classpath" || true)" = 0 ]')"
check "the control: the debug classpath names project :youtube" \
    "$(yes_if '[ "$(grep -c "project :youtube" <<<"$debug_classpath" || true)" -gt 0 ]')"

read -r arm64 x86 soxr86 sqlite86 ortclasses mlclasses benchdex rowwords autochords assets modelfiles weights provider \
    benchmanifest providers pylibs chaquojni chaquolinked chaquoclasses chaquoassets ytclasses ytmanifest ytbenchdex \
    ytbenchmanifest mlmanifest < <(probes "$release")
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
echo "release APK: $ytbenchdex YouTube bench names or Settings' row's words in its dex, $ytbenchmanifest YouTube" \
    "bench entries of its manifest"
check "release APK's dex names no YouTubeBench and holds no \"YouTube bench\" (Settings' row)" \
    "$(yes_if '[ "$ytbenchdex" = 0 ]')"
check "release APK's manifest has no YouTubeBenchActivity, YouTubeBenchLedger or :ytbench" \
    "$(yes_if '[ "$ytbenchmanifest" = 0 ]')"
echo "release APK: $pylibs libpython*, $chaquojni libchaquopy_java.so, $chaquolinked lib*_python.so or" \
    "lib*_chaquopy.so, $chaquoclasses classes under com/chaquo/, $chaquoassets entries under" \
    "assets/chaquopy/"
check "release APK holds no libpython*" "$(yes_if '[ "$pylibs" = 0 ]')"
check "release APK holds no libchaquopy_java.so" "$(yes_if '[ "$chaquojni" = 0 ]')"
check "release APK holds no lib*_python.so or lib*_chaquopy.so" "$(yes_if '[ "$chaquolinked" = 0 ]')"
check "release APK holds no class under com/chaquo/" "$(yes_if '[ "$chaquoclasses" = 0 ]')"
check "release APK holds nothing under assets/chaquopy/" "$(yes_if '[ "$chaquoassets" = 0 ]')"
echo "release APK: $ytclasses classes of :youtube in its dex, $ytmanifest YtDlpService, GateService or :youtube" \
    "entries in its manifest"
check "release APK holds no class of :youtube (io/github/danielhp95/caracole/youtube/)" \
    "$(yes_if '[ "$ytclasses" = 0 ]')"
check "release APK's manifest names no YtDlpService, GateService or :youtube process" \
    "$(yes_if '[ "$ytmanifest" = 0 ]')"
read -r qjs stored compressed extracted total < <(natives "$release")
echo "release APK: $qjs libqjs.so, native libraries $stored stored and aligned, $compressed compressed, of $total" \
    "lib/*/*.so entries, extractNativeLibs=true $extracted"
check "release APK holds no libqjs.so" "$(yes_if '[ "$qjs" = 0 ]')"
check "release APK holds native libraries (lib/*/*.so)" "$(yes_if '[ "$total" -gt 0 ]')"
if [ "$total" -gt 0 ] && [ "$stored" != "$total" ]; then
    echo "      $((total - stored)) of the release's $total lib/*/*.so entries aren't stored uncompressed and 16 KB" \
        "aligned (zipalign's (OK)): compressed, misaligned, or not read by zipalign"
fi
check "release APK's native libraries are every one stored uncompressed and 16 KB aligned" \
    "$(yes_if '[ "$total" -gt 0 ] && [ "$stored" = "$total" ] && [ "$compressed" = 0 ]')"
check "release APK's manifest says no extractNativeLibs=true" "$(yes_if '[ "$extracted" = 0 ]')"

check "release APK's manifest declares no TelemetryInitializer" "$(yes_if '[ "$provider" = 0 ]')"
check "release APK is 100 MiB at most" "$(yes_if '[ "$size" -le $((100 * 1024 * 1024)) ]')"

read -r arm64 x86 soxr86 sqlite86 ortclasses mlclasses benchdex rowwords autochords assets modelfiles weights provider \
    benchmanifest providers pylibs chaquojni chaquolinked chaquoclasses chaquoassets ytclasses ytmanifest ytbenchdex \
    ytbenchmanifest mlmanifest < <(probes "$debug")
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
echo "debug APK (the control): $ytbenchdex YouTube bench names or Settings' row's words in its dex," \
    "$ytbenchmanifest YouTube bench entries of its manifest"
check "the control: the debug APK's dex names the YouTube bench and holds its row's words" \
    "$(yes_if '[ "$ytbenchdex" -gt 0 ]')"
check "the control: the debug APK's manifest declares the YouTube bench (its activity, its ledger, :ytbench)" \
    "$(yes_if '[ "$ytbenchmanifest" -ge 3 ]')"
check "the debug APK holds none of the weights' files either" "$(yes_if '[ "$weights" = 0 ]')"
check "the debug APK's manifest declares no TelemetryInitializer either" "$(yes_if '[ "$provider" = 0 ]')"
echo "debug APK (the control): $pylibs libpython*, $chaquojni libchaquopy_java.so, $chaquolinked lib*_python.so" \
    "or lib*_chaquopy.so, $chaquoclasses classes under com/chaquo/, $chaquoassets entries" \
    "under assets/chaquopy/"
check "the control: the debug APK holds libpython*" "$(yes_if '[ "$pylibs" -gt 0 ]')"
check "the control: the debug APK holds libchaquopy_java.so" "$(yes_if '[ "$chaquojni" -gt 0 ]')"
check "the control: the debug APK holds lib*_python.so and lib*_chaquopy.so" \
    "$(yes_if '[ "$chaquolinked" -gt 0 ]')"
check "the control: the debug APK holds classes under com/chaquo/" "$(yes_if '[ "$chaquoclasses" -gt 0 ]')"
check "the control: the debug APK holds assets/chaquopy/" "$(yes_if '[ "$chaquoassets" -gt 0 ]')"
echo "debug APK (the control): $ytclasses classes of :youtube, $ytmanifest YtDlpService, GateService or :youtube" \
    "entries in its manifest"
check "the control: the debug APK holds classes of :youtube" "$(yes_if '[ "$ytclasses" -gt 0 ]')"
check "the control: the debug APK's manifest names YtDlpService, GateService and :youtube" \
    "$(yes_if '[ "$ytmanifest" -ge 3 ]')"
read -r qjs stored compressed extracted total < <(natives "$debug")
echo "debug APK (the control): $qjs libqjs.so, native libraries $stored stored and aligned, $compressed compressed," \
    "of $total lib/*/*.so entries, extractNativeLibs=true $extracted"
check "the control: the debug APK holds libqjs.so" "$(yes_if '[ "$qjs" -gt 0 ]')"
check "the control: the debug APK's native libraries are compressed, extracted at install" \
    "$(yes_if '[ "$compressed" -gt 0 ] && [ "$extracted" = 1 ]')"

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
# The licences of what the chord models ship (ml/build.gradle.kts's copyLicences), in the release APK byte for byte
# as their sources hold them: ONNX Runtime's from its AAR, libsoxr's beside its source, BTC's and beat_this's.
licence_dir="$probe/licences"
mkdir -p "$licence_dir"
[ -n "$aar" ] && unzip -q -o "$aar" LICENSE ThirdPartyNotices.txt -d "$licence_dir/ort" 2>/dev/null
licence_pairs=(
    "onnxruntime-LICENSE=$licence_dir/ort/LICENSE"
    "onnxruntime-ThirdPartyNotices.txt=$licence_dir/ort/ThirdPartyNotices.txt"
    "libsoxr-LICENCE=android/autochords/native/soxr/LICENCE"
    "libsoxr-COPYING.LGPL=android/autochords/native/soxr/COPYING.LGPL"
    "BTC-LICENSE=src/caracole/autochords/LICENSE-BTC"
    "beat_this-LICENSE.txt=android/ml/licenses/beat_this-LICENSE.txt"
    "libsoxr-pffft-LICENSE=android/ml/licenses/libsoxr-pffft-LICENSE"
    "README=android/ml/licenses/README"
)
same_licence() {  # same_licence APK NAME SOURCE: the APK's assets/chords/licenses/NAME is SOURCE's bytes
    [ -s "$3" ] && unzip -p "$1" "assets/chords/licenses/$2" 2>/dev/null | cmp -s - "$3"
}
for pair in "${licence_pairs[@]}"; do
    name="${pair%%=*}"
    check "release APK holds $name (assets/chords/licenses/), its source's bytes" \
        "$(yes_if 'same_licence "$release" "$name" "${pair#*=}"')"
done
# PFFFT's licence, which libsoxr is built with (autochords/native/CMakeLists.txt's pffft32s.c), is pffft.c's own
# comment, verbatim: the file the APK carries is found whole in that source.
within() {  # within PART WHOLE: PART's text (its last newlines aside) is in WHOLE's, verbatim
    local part whole
    part="$(cat "$1")" && whole="$(cat "$2")" && [ -n "$part" ] && [[ "$whole" == *"$part"* ]]
}
check "libsoxr-pffft-LICENSE is pffft.c's licence, verbatim" \
    "$(yes_if 'within android/ml/licenses/libsoxr-pffft-LICENSE android/autochords/native/soxr/src/pffft.c')"
check "the control: the verbatim probe finds no other licence in pffft.c" \
    "$(yes_if '! within android/autochords/native/soxr/LICENCE android/autochords/native/soxr/src/pffft.c')"
check "the control: the licences' probe tells two licences apart (onnxruntime-LICENSE is not libsoxr's LICENCE)" \
    "$(yes_if '! same_licence "$release" onnxruntime-LICENSE android/autochords/native/soxr/LICENCE')"
check "the control: the licences' probe finds no licence the APK lacks" \
    "$(yes_if '! same_licence "$release" no-such-LICENSE src/caracole/autochords/LICENSE-BTC')"

echo "ApkScanTest (gradle :app:apkScan):"
if nix develop ./android#ml -c gradle -p android :app:apkScan --console=plain -q; then scanned=1; else scanned=0; fi
check "ApkScanTest: no telemetry host, provider or client in the APKs or the runtime's AAR" "$scanned"

# Our native libraries (native-check.sh): the debug APK's runtime, libsoxr and libqjs.so, both ABIs, extracted at
# install; the release's runtime and libsoxr, arm64-v8a's alone, stored aligned; each stripped and naming no path of the
# build.
echo "native-check.sh, the debug APK:"
if nix develop ./android -c "$here/native-check.sh" --expect extracted "$debug"; then native=1; else native=0; fi
check "the debug APK's runtime, libsoxr and libqjs.so, both ABIs: extracted, stripped, no build path" \
    "$native"
echo "native-check.sh, the release APK:"
if nix develop ./android -c "$here/native-check.sh" --release "$release"; then native=1; else native=0; fi
check "the release APK's runtime and libsoxr, arm64-v8a's alone: aligned, stripped, no build path" "$native"

exit "$failed"
