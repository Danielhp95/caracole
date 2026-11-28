#!/usr/bin/env bash
# ONNX Runtime for the phone, built from its source with no network and nothing that phones home (the chords-on-the-
# phone design's §3.5 and §7, Gate R): the CPU execution provider alone, telemetry off (1.27.1's is opt-in,
# onnxruntime_USE_TELEMETRY, never set; it has no Android telemetry at all), the kernels of the two graphs' ops alone
# (--ops, ml/onnxruntime-ops.config), and the Java bindings, in three steps:
#
#   android/scripts/build-onnxruntime.sh java --source DIR --out DIR
#   android/scripts/build-onnxruntime.sh native --source DIR --java DIR --mirror DIR --ndk DIR --protoc FILE \
#       --ops FILE --abi ABI --work DIR --out DIR [--jobs N]
#   android/scripts/build-onnxruntime.sh aar --source DIR --java DIR --out FILE NATIVE_OUT...
#
#   java      the Java bindings compiled once (javac): DIR/classes.jar and DIR/headers, the JNI headers
#   native    one ABI's libraries, DIR/jni/ABI/libonnxruntime.so and libonnxruntime4j_jni.so, stripped:
#             --source  ONNX Runtime's tree (read only; copied into --work, so its path is never the build's)
#             --java    java's output, whose headers the JNI library is compiled against
#             --mirror  its CMake dependencies, each at its deps.txt address less "https://"
#                       (onnxruntime_CMAKE_DEPS_MIRROR_DIR); CMake checks each against deps.txt's SHA-1
#             --ndk     the NDK (r28c), --protoc protoc 21.12 for this machine (deps.txt's protobuf)
#             --abi     arm64-v8a or x86_64
#             --jobs    the compile jobs: at most 8, $NIX_BUILD_CORES's when fewer (0, as Nix says "all", is 8)
#   aar       the AAR of java's classes and each NATIVE_OUT's jni/, no provider and no permission
#
# nix/onnxruntime-android.nix runs it in Nix's sandbox; run by hand from two folders it gives the same bytes: every
# path of the build is mapped (-ffile-prefix-map, the debug info stripped), no build id, the GNU hash alone, no
# .comment, no git commit (Git not looked for), every date EPOCH's (below), every zip's entries sorted. ORT's own Java
# path runs Gradle, which fetches: its Gradle commands become echoes, and javac makes the JNI headers instead.
set -euo pipefail

# The one date of every output, whatever the shell says (a Nix shell sets 1980-01-01T00:00:00Z, which jar refuses):
# 1980-01-01T00:00:02Z, a zip's earliest even second but one.
EPOCH=315532802
export SOURCE_DATE_EPOCH=$EPOCH LC_ALL=C TZ=UTC
api=26

step="${1-}"
shift || true
jobs="${NIX_BUILD_CORES:-8}"
source="" java="" mirror="" ndk="" protoc="" ops="" abi="" work="" out=""
natives=()
while [ $# -gt 0 ]; do
    case "$1" in
        --source) source="$2"; shift 2 ;;
        --java) java="$2"; shift 2 ;;
        --mirror) mirror="$2"; shift 2 ;;
        --ndk) ndk="$2"; shift 2 ;;
        --protoc) protoc="$2"; shift 2 ;;
        --ops) ops="$2"; shift 2 ;;
        --abi) abi="$2"; shift 2 ;;
        --work) work="$2"; shift 2 ;;
        --out) out="$2"; shift 2 ;;
        --jobs) jobs="$2"; shift 2 ;;
        --*) echo "build-onnxruntime.sh: unknown argument $1" >&2; exit 2 ;;
        *) natives+=("$1"); shift ;;
    esac
done
need() { for v in "$@"; do [ -n "${!v}" ] || { echo "build-onnxruntime.sh: --$v is required" >&2; exit 2; }; done; }
# Every zip this script writes (a jar, the AAR): its entries sorted, each dated EPOCH, mode 0644, .so files stored.
zip_folder() {
    python3 -B - "$1" "$2" "$EPOCH" <<'EOF'
import os, sys, time, zipfile
root, target, epoch = sys.argv[1], sys.argv[2], int(sys.argv[3])
date = time.gmtime(epoch)[:6]
names = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)
with zipfile.ZipFile(target, "w") as z:
    for name in names:
        info = zipfile.ZipInfo(name, date)
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_STORED if name.endswith(".so") else zipfile.ZIP_DEFLATED
        with open(os.path.join(root, name), "rb") as f:
            z.writestr(info, f.read())
EOF
}

java_step() {
    need source out
    mkdir -p "$out"
    out="$(realpath "$out")"
    local classes
    classes="$(mktemp -d)"
    rm -rf "$out/headers" && mkdir -p "$out/headers"
    find "$source/java/src/main/java" "$source/java/src/main/android" -name '*.java' | sort >"$classes.sources"
    javac --release 17 -encoding UTF-8 -nowarn -d "$classes" -h "$out/headers" @"$classes.sources"
    zip_folder "$classes" "$out/classes.jar"
    rm -rf "$classes" "$classes.sources"
}

native_step() {
    need source java mirror ndk protoc ops abi work out
    case "$abi" in
        arm64-v8a|x86_64) ;;
        *) echo "build-onnxruntime.sh: no ABI $abi (arm64-v8a, x86_64)" >&2; exit 2 ;;
    esac
    case "$jobs" in ''|*[!0-9]*|0) jobs=8 ;; esac
    [ "$jobs" -le 8 ] || jobs=8
    mkdir -p "$work" "$out"
    work="$(realpath "$work")"
    out="$(realpath "$out")"
    ops="$(realpath "$ops")"
    java="$(realpath "$java")"
    local src="$work/src" build="$work/build"
    rm -rf "$src" "$build"
    cp -r --no-preserve=mode "$source" "$src"
    chmod -R u+w "$src"
    mkdir -p "$build"

    # No Gradle: every command ORT's Java CMake runs Gradle with is an echo, and the headers and the jar it waits for
    # are the java step's.
    python3 -B - "$src/cmake/onnxruntime_java.cmake" <<'EOF'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
assert "COMMAND ${GRADLE_EXECUTABLE}" in text
open(path, "w", encoding="utf-8").write(
    text.replace("COMMAND ${GRADLE_EXECUTABLE}", "COMMAND ${CMAKE_COMMAND} -E echo skipped-gradle"))
EOF
    mkdir -p "$src/java/build/libs"
    cp -r "$java/headers" "$src/java/build/headers"
    cp "$java/classes.jar" "$src/java/build/libs/onnxruntime.jar"

    # The kernels of the ops the config names alone, rewritten into the build folder (op_reduction.generated).
    python3 -B "$src/tools/ci_build/reduce_op_kernels.py" "$ops" --cmake_build_dir "$build"

    local maps links
    maps="-ffile-prefix-map=$src=. -ffile-prefix-map=$build=. -ffile-prefix-map=$ndk=ndk"
    maps="$maps -ffile-prefix-map=$mirror=mirror"
    links="-Wl,--build-id=none -Wl,--hash-style=gnu -Wl,-z,max-page-size=16384"
    cmake -G Ninja -S "$src/cmake" -B "$build" --compile-no-warning-as-error \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
        -DANDROID_ABI="$abi" -DANDROID_PLATFORM="android-$api" -DANDROID_MIN_SDK="$api" -DANDROID_STL=c++_static \
        -DCMAKE_C_FLAGS="$maps" -DCMAKE_CXX_FLAGS="$maps" \
        -DCMAKE_SHARED_LINKER_FLAGS="$links" -DCMAKE_MODULE_LINKER_FLAGS="$links" \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_DISABLE_FIND_PACKAGE_Git=ON \
        -DPython3_EXECUTABLE="$(command -v python3)" -DPYTHON_EXECUTABLE="$(command -v python3)" \
        -DFETCHCONTENT_TRY_FIND_PACKAGE_MODE=NEVER -DFETCHCONTENT_QUIET=ON \
        -Donnxruntime_CMAKE_DEPS_MIRROR_DIR="$mirror" \
        -DONNX_CUSTOM_PROTOC_EXECUTABLE="$protoc" \
        -Donnxruntime_BUILD_SHARED_LIB=ON \
        -Donnxruntime_BUILD_JAVA=ON \
        -Donnxruntime_BUILD_UNIT_TESTS=OFF \
        -Donnxruntime_REDUCED_OPS_BUILD=ON \
        -Donnxruntime_USE_TELEMETRY=OFF \
        -Donnxruntime_DISABLE_RTTI=OFF \
        -Donnxruntime_USE_XNNPACK=OFF -Donnxruntime_USE_NNAPI_BUILTIN=OFF -Donnxruntime_USE_KLEIDIAI=OFF
    cmake --build "$build" --target onnxruntime onnxruntime4j_jni -j "$jobs"

    local strip="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip" lib found
    mkdir -p "$out/jni/$abi"
    for lib in libonnxruntime.so libonnxruntime4j_jni.so; do
        found="$(find "$build" -name "$lib" -type f | sort | head -1)"
        [ -n "$found" ] || { echo "build-onnxruntime.sh: no $lib in $build" >&2; exit 1; }
        "$strip" --strip-unneeded --remove-section=.comment -o "$out/jni/$abi/$lib" "$found"
    done
    echo "build-onnxruntime.sh: $abi (android-$api, $jobs jobs) in $out/jni/$abi"
}

aar_step() {
    need source java out
    [ ${#natives[@]} -gt 0 ] || { echo "build-onnxruntime.sh: aar needs a native step's output" >&2; exit 2; }
    local tree native
    tree="$(mktemp -d)"
    mkdir -p "$tree/jni" "$tree/META-INF/com/android/build/gradle"
    cp "$java/classes.jar" "$tree/classes.jar"
    for native in "${natives[@]}"; do cp -r "$native/jni/." "$tree/jni/"; done
    # No provider, no permission: this build sends nothing anywhere.
    cat >"$tree/AndroidManifest.xml" <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="ai.onnxruntime">
    <uses-sdk android:minSdkVersion="26" />
</manifest>
EOF
    # The JNI side makes and reads ai.onnxruntime's objects by name.
    echo '-keep class ai.onnxruntime.** { *; }' >"$tree/proguard.txt"
    : >"$tree/R.txt"
    printf 'aarFormatVersion=1.0\naarMetadataVersion=1.0\nminCompileSdk=1\n' \
        >"$tree/META-INF/com/android/build/gradle/aar-metadata.properties"
    cp "$source/LICENSE" "$source/ThirdPartyNotices.txt" "$tree/"
    chmod -R u+w "$tree"
    mkdir -p "$(dirname "$out")"
    zip_folder "$tree" "$out"
    rm -rf "$tree"
}

case "$step" in
    java) java_step ;;
    native) native_step ;;
    aar) aar_step ;;
    *) echo "build-onnxruntime.sh: java, native or aar first" >&2; exit 2 ;;
esac
