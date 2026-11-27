#!/usr/bin/env bash
# ONNX Runtime for the phone, built from its source with no network and nothing that phones home (the chords-on-the-
# phone design's §3.5 and §7, Gate R): the CPU execution provider alone, telemetry off (1.27.1's is opt-in,
# onnxruntime_USE_TELEMETRY, never set; it has no Android telemetry at all), the kernels of the two graphs' ops alone
# (--ops, ml/onnxruntime-ops.config), and the Java bindings' JNI library, for one ABI:
#
#   android/scripts/build-onnxruntime.sh --source DIR --mirror DIR --ndk DIR --protoc FILE --ops FILE --abi ABI \
#       --work DIR --out DIR [--jobs N]
#
#   --source  ONNX Runtime's tree (read only; copied into --work, so its path is never the build's)
#   --mirror  its CMake dependencies, each at its deps.txt address less "https://" (onnxruntime_CMAKE_DEPS_MIRROR_DIR);
#             CMake checks each against deps.txt's SHA-1, as it would a download
#   --ndk     the NDK (r28c), --protoc protoc 21.12 for this machine (deps.txt's protobuf)
#   --abi     arm64-v8a or x86_64; --jobs the compile jobs (default $NIX_BUILD_CORES, else 8)
#   --out     gets jni/ABI/libonnxruntime.so and libonnxruntime4j_jni.so, stripped
#
# nix/onnxruntime-android.nix runs it in Nix's sandbox; run by hand from two folders it gives the same bytes: every
# path of the build is mapped (-ffile-prefix-map, the debug info stripped), no build id, the GNU hash alone, no
# .comment, no git commit (Git not looked for), SOURCE_DATE_EPOCH fixed. ORT's own Java path runs Gradle, which
# fetches: its Gradle commands become echoes, and javac makes the JNI headers instead.
set -euo pipefail

jobs="${NIX_BUILD_CORES:-8}"
source="" mirror="" ndk="" protoc="" ops="" abi="" work="" out=""
while [ $# -gt 0 ]; do
    case "$1" in
        --source) source="$2" ;;
        --mirror) mirror="$2" ;;
        --ndk) ndk="$2" ;;
        --protoc) protoc="$2" ;;
        --ops) ops="$2" ;;
        --abi) abi="$2" ;;
        --work) work="$2" ;;
        --out) out="$2" ;;
        --jobs) jobs="$2" ;;
        *) echo "build-onnxruntime.sh: unknown argument $1" >&2; exit 2 ;;
    esac
    shift 2
done
for v in source mirror ndk protoc ops abi work out; do
    [ -n "${!v}" ] || { echo "build-onnxruntime.sh: --$v is required" >&2; exit 2; }
done
case "$abi" in
    arm64-v8a) target=aarch64-linux-android ;;
    x86_64) target=x86_64-linux-android ;;
    *) echo "build-onnxruntime.sh: no ABI $abi (arm64-v8a, x86_64)" >&2; exit 2 ;;
esac
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-315532802}"
export LC_ALL=C TZ=UTC
api=26

mkdir -p "$work" "$out"
work="$(realpath "$work")"
out="$(realpath "$out")"
ops="$(realpath "$ops")"
src="$work/src"
build="$work/build"
rm -rf "$src" "$build"
cp -r --no-preserve=mode "$source" "$src"
chmod -R u+w "$src"
mkdir -p "$build"

# No Gradle: every command ORT's Java CMake runs Gradle with is an echo, and the headers and the jar it waits for are
# javac's.
python3 -B - "$src/cmake/onnxruntime_java.cmake" <<'EOF'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
assert "COMMAND ${GRADLE_EXECUTABLE}" in text
open(path, "w", encoding="utf-8").write(
    text.replace("COMMAND ${GRADLE_EXECUTABLE}", "COMMAND ${CMAKE_COMMAND} -E echo skipped-gradle"))
EOF
classes="$work/classes"
rm -rf "$classes" && mkdir -p "$classes" "$src/java/build/headers" "$src/java/build/libs"
find "$src/java/src/main/java" "$src/java/src/main/android" -name '*.java' | sort >"$work/java-sources"
javac --release 17 -encoding UTF-8 -nowarn -d "$classes" -h "$src/java/build/headers" @"$work/java-sources"
jar --create --date="$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%dT%H:%M:%SZ)" \
    --file "$src/java/build/libs/onnxruntime.jar" -C "$classes" .

# The kernels of the ops the config names alone, rewritten into the build folder (op_reduction.generated).
python3 -B "$src/tools/ci_build/reduce_op_kernels.py" "$ops" --cmake_build_dir "$build"

maps="-ffile-prefix-map=$src=. -ffile-prefix-map=$build=. -ffile-prefix-map=$ndk=ndk -ffile-prefix-map=$mirror=mirror"
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

strip="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip"
mkdir -p "$out/jni/$abi"
for lib in libonnxruntime.so libonnxruntime4j_jni.so; do
    found="$(find "$build" -name "$lib" -type f | sort | head -1)"
    [ -n "$found" ] || { echo "build-onnxruntime.sh: no $lib in $build" >&2; exit 1; }
    "$strip" --strip-unneeded --remove-section=.comment -o "$out/jni/$abi/$lib" "$found"
done
echo "build-onnxruntime.sh: $abi ($target, android-$api) in $out/jni/$abi"
