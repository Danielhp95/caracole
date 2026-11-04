#!/usr/bin/env bash
# The phone's device tests on the one emulator, one caller at a time (AGENTS.md, "How work is done here"):
#
#   android/scripts/device-test.sh [--computer DIR] [--sites SCENARIO] [--area NAME[,NAME...]] [--app] [CLASS[=DIR]]...
#
#   --area NAMES    CorpusOnDeviceTest's areas (core.testing.Replays, server.testing.ServerReplays); "all" or an empty
#                   list: every one
#   --app           the app's classes: EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against a
#                   computer of its own (tests.helpers.e2e_library in a fresh folder), as the M1-3 integration ran them
#   CLASS[=DIR]     a class of app/src/androidTest (NoSitesTest, LocalServerTest...), with DIR its computer's folder
#   --computer DIR  one computer for every class that names none
#   --sites S       the fake sites server for the classes (lane lookups-e2e fills this branch)
#
# It builds assembleDebug and assembleDebugAndroidTest first, outside the lock, then holds
# ${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock} while it installs and runs. It uses an
# emulator alone (a serial emulator-NNNN), never a phone adb also lists, starts one if none is up (without a display it
# stops and says so) and leaves it up, never holding the lock (nothing the script starts inherits it). Between classes the app's data is cleared, and the print spooler and any
# chooser closed. It prints each class's result and exits non-zero on any failure.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
repo="$(dirname "$android")"
app_id=io.github.danielhp95.caracole
runner="$app_id.test/$app_id.CaracoleTestRunner"
lock="${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}"
logs="${CARACOLE_DEVICE_LOGS:-${XDG_RUNTIME_DIR:-/tmp}/caracole-device-test}"

areas=""
want_areas=0
want_app=0
computer=""
sites=""
classes=()

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --area) want_areas=1; areas="${2-}"; [ $# -ge 2 ] || usage; shift 2 ;;
        --area=*) want_areas=1; areas="${1#--area=}"; shift ;;
        --app) want_app=1; shift ;;
        --computer) computer="${2-}"; [ -n "$computer" ] || usage; shift 2 ;;
        --sites) sites="${2-}"; [ -n "$sites" ] || usage; shift 2 ;;
        -h|--help) usage ;;
        -*) echo "device-test.sh: unknown option $1" >&2; usage ;;
        *) classes+=("$1"); shift ;;
    esac
done
[ "$want_areas" = 1 ] || [ "$want_app" = 1 ] || [ ${#classes[@]} -gt 0 ] || usage
[ "$areas" = all ] && areas=""
if [ -n "$sites" ]; then
    echo "device-test.sh: --sites is lane lookups-e2e's (the fake sites server): not built yet" >&2
    exit 2
fi

# 1. The build, outside the lock, so a lane that builds never holds the emulator.
(cd "$repo" && nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest --console=plain -q)
apk="$android/app/build/outputs/apk/debug/app-debug.apk"
test_apk="$android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"

# 2. The emulator's lock, held until the script ends.
mkdir -p "$(dirname "$lock")" "$logs"
exec 9>"$lock"
if ! flock -n 9; then
    echo "device-test.sh: the emulator is busy (another caller holds $lock): waiting" >&2
    flock 9
fi

# adb: the host's, else the emulator shell's (one adb server for every caller: a phone it also lists is never used).
adb_bin="${ADB:-$(command -v adb || true)}"
[ -n "$adb_bin" ] || adb_bin="$(cd "$repo" && nix develop ./android#emulator -c sh -c 'command -v adb')"
adb_cmd() { "$adb_bin" "$@"; }
emulator_serial() { adb_cmd devices 2>/dev/null | awk '$1 ~ /^emulator-[0-9]+$/ && $2 == "device" { print $1; exit }'; }

serial="$(emulator_serial || true)"
if [ -z "$serial" ]; then
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        echo "device-test.sh: no emulator is up and there is no display to start one on" >&2
        exit 3
    fi
    echo "device-test.sh: starting the emulator (its log: $logs/emulator.log)" >&2
    (cd "$repo" && setsid nohup nix develop ./android#emulator -c env \
        ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-/home/dani/.config/.android/avd}" QT_QPA_PLATFORM=xcb \
        LD_LIBRARY_PATH=/run/opengl-driver/lib \
        emulator -avd caracole -gpu host -no-snapshot-save >"$logs/emulator.log" 2>&1 </dev/null &) 9>&-
    for _ in $(seq 1 180); do
        serial="$(emulator_serial || true)"
        [ -n "$serial" ] && break
        sleep 2
    done
    [ -n "$serial" ] || { echo "device-test.sh: the emulator didn't come up" >&2; exit 3; }
fi
for _ in $(seq 1 180); do
    [ "$(adb_cmd -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && break
    sleep 2
done
echo "device-test.sh: on $serial" >&2
adb() { adb_cmd -s "$serial" "$@"; }

# 3. Both APKs.
adb install -r -t "$apk" >/dev/null
adb install -r -t "$test_apk" >/dev/null

# The computers this run started, stopped as it ends.
servers=()
cleanup() { for pid in "${servers[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT

free_port() { python3 -c 'import socket; s = socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()'; }

# A computer for DIR (made if it holds none) on a free port, never 8737 (the owner's caracole-web): its address as
# the emulator reaches it.
start_computer() {
    local dir="$1" port
    port="$(free_port)"
    while [ "$port" = 8737 ]; do port="$(free_port)"; done
    mkdir -p "$dir"
    (exec 9>&-; cd "$repo" && exec nix develop -c python -m tests.helpers.e2e_library serve "$dir" "$port") \
        >"$logs/computer-$port.log" 2>&1 &
    servers+=($!)
    for _ in $(seq 1 900); do
        if python3 -c 'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 1).close()' \
            "$port" 2>/dev/null; then
            echo "http://10.0.2.2:$port"
            return
        fi
        sleep 1
    done
    echo "device-test.sh: the computer in $dir didn't answer (its log: $logs/computer-$port.log)" >&2
    return 1
}

failed=0
results=()

# One class run: `am instrument -w`, its args; the app's data cleared, the print spooler and choosers closed after.
run_class() {
    local name="$1"; shift
    local out
    out="$(adb shell am instrument -w -e class "$app_id.$name" "$@" "$runner" 2>&1 | tr -d '\r')" || true
    echo "$out"
    if grep -q '^OK (' <<<"$out" && ! grep -qE 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed' <<<"$out"; then
        results+=("PASS $name")
    else
        results+=("FAIL $name")
        failed=1
    fi
    adb shell pm clear "$app_id" >/dev/null 2>&1 || true
    adb shell am force-stop com.android.printspooler >/dev/null 2>&1 || true
    adb shell input keyevent HOME >/dev/null 2>&1 || true
}

# 4. The corpus's areas.
if [ "$want_areas" = 1 ]; then
    if [ -n "$areas" ]; then run_class CorpusOnDeviceTest -e area "$areas"
    else run_class CorpusOnDeviceTest; fi
fi

# 5. The app's classes and those named, each with its computer.
run_with_computer() {
    local name="$1" dir="$2" url
    if [ -z "$dir" ]; then
        run_class "$name"
        return
    fi
    url="$(start_computer "$dir")" || { results+=("FAIL $name (no computer)"); failed=1; return; }
    run_class "$name" -e server "$url"
}

if [ "$want_app" = 1 ]; then
    base="$(mktemp -d "${TMPDIR:-/tmp}/caracole-device-XXXXXX")"
    for name in EndToEndTest PinchTest SyncTabTest PhoneEndToEndTest; do
        run_with_computer "$name" "${computer:-$base/$name}"
    done
fi
for spec in "${classes[@]:-}"; do
    [ -n "$spec" ] || continue
    name="${spec%%=*}"
    dir=""
    if [ "$spec" != "$name" ]; then dir="${spec#*=}"; else dir="$computer"; fi
    run_with_computer "$name" "$dir"
done

echo
printf '%s\n' "${results[@]}"
exit "$failed"
