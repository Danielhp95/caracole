#!/usr/bin/env bash
# The phone's device tests on a pool of emulators, one caller an emulator at a time (AGENTS.md, "How work is done
# here"):
#
#   android/scripts/device-test.sh [--computer DIR] [--sites SCENARIO] [--area NAME[,NAME...]] [--app] [CLASS[=DIR]]...
#
#   --area NAMES    CorpusOnDeviceTest's areas (core, server and viewer.testing's Replays); "all" or an empty
#                   list: every one
#   --app           the app's classes: EndToEndTest, PinchTest, SyncTabTest and PhoneEndToEndTest, each against a
#                   computer of its own (tests.helpers.e2e_library in a fresh folder), as the M1-3 integration ran them
#   CLASS[=DIR]     a class of app/src/androidTest (NoSitesTest, LocalServerTest..., or in full:
#                   io.github.danielhp95.caracole.NoSitesTest), with DIR its computer's folder
#   --computer DIR  one computer for every class that names none
#   --sites S       the fake sites server of scenario S (tests/helpers/fake_sites.py serve S PORT, on the host, a
#                   free port never 8737) for every class run, named to each as -e sites http://10.0.2.2:PORT
#
# It builds assembleDebug and assembleDebugAndroidTest first, outside the lock, then takes the first free emulator of
# the pool (CARACOLE_EMULATORS, 3 by default, the owner's choice of 2026-11-10: emulator-5554, -5556, -5558), holding its
# lock while it installs and runs: emulator-5554's is
# ${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}, as before, and each other's the same name
# with its port (caracole-emulator-5556.lock). It uses an emulator alone (a serial emulator-NNNN), never a phone adb also
# lists, starts the one it took if it isn't up (each read-only, so several run on the one AVD; without a display it
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

usage() { awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 2; }  # the header, whole

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

# 1. The build, outside the lock, so a lane that builds never holds the emulator.
(cd "$repo" && nix develop ./android -c gradle -p android assembleDebug assembleDebugAndroidTest --console=plain -q)
apk="$android/app/build/outputs/apk/debug/app-debug.apk"
test_apk="$android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"

# 2. A free emulator of the pool and its lock, held until the script ends.
mkdir -p "$(dirname "$lock")" "$logs"
pool="${CARACOLE_EMULATORS:-3}"
lock_of() { if [ "$1" = 5554 ]; then echo "$lock"; else echo "${lock%.lock}-$1.lock"; fi; }
port=""
said=0
while [ -z "$port" ]; do
    for i in $(seq 0 $((pool - 1))); do
        p=$((5554 + 2 * i))
        exec 9>"$(lock_of "$p")"
        if flock -n 9; then port="$p"; break; fi
        exec 9>&-
    done
    if [ -z "$port" ]; then
        [ "$said" = 1 ] || echo "device-test.sh: every emulator of the pool ($pool) is busy: waiting" >&2
        said=1
        sleep 3
    fi
done

# adb: the host's, else the emulator shell's (one adb server for every caller: a phone it also lists is never used).
adb_bin="${ADB:-$(command -v adb || true)}"
[ -n "$adb_bin" ] || adb_bin="$(cd "$repo" && nix develop ./android#emulator -c sh -c 'command -v adb')"
adb_cmd() { "$adb_bin" "$@"; }
emulator_serial() { adb_cmd devices 2>/dev/null | awk -v s="emulator-$port" '$1 == s && $2 == "device" { print $1; exit }'; }

serial="$(emulator_serial || true)"
if [ -z "$serial" ]; then
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        echo "device-test.sh: no emulator is up and there is no display to start one on" >&2
        exit 3
    fi
    echo "device-test.sh: starting emulator-$port (its log: $logs/emulator-$port.log)" >&2
    (cd "$repo" && setsid nohup nix develop ./android#emulator -c env \
        ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-/home/dani/.config/.android/avd}" QT_QPA_PLATFORM=xcb \
        LD_LIBRARY_PATH=/run/opengl-driver/lib \
        emulator -avd caracole -port "$port" -read-only -gpu host -no-snapshot-save >"$logs/emulator-$port.log" \
        2>&1 </dev/null &) 9>&-
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

# The fake sites server of scenario $sites, on a free port (never 8737), for every class: its address as the
# emulator reaches it, in each class's arguments.
site_args=()
if [ -n "$sites" ]; then
    sites_port="$(free_port)"
    while [ "$sites_port" = 8737 ]; do sites_port="$(free_port)"; done
    (exec 9>&-; cd "$repo" && exec nix develop -c python -m tests.helpers.fake_sites serve "$sites" "$sites_port" \
        --address 127.0.0.1) \
        >"$logs/sites-$sites_port.log" 2>&1 &
    servers+=($!)
    for _ in $(seq 1 600); do
        if python3 -c 'import sys, urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                "http://127.0.0.1:%s/" % sys.argv[1], timeout=2).close()' "$sites_port" 2>/dev/null; then
            site_args=(-e sites "http://10.0.2.2:$sites_port")
            break
        fi
        sleep 1
    done
    if [ ${#site_args[@]} -eq 0 ]; then
        echo "device-test.sh: the fake sites of $sites didn't answer (their log: $logs/sites-$sites_port.log)" >&2
        exit 3
    fi
    echo "device-test.sh: the fake sites of $sites at http://10.0.2.2:$sites_port (their log: $logs/sites-$sites_port.log)" >&2
fi

failed=0
results=()

# One class run: `am instrument -w`, its args; the app's data cleared, the print spooler and choosers closed after.
run_class() {
    local name="$1"; shift
    local out
    out="$(adb shell am instrument -w -e class "$app_id.$name" "$@" ${site_args[@]+"${site_args[@]}"} "$runner" 2>&1 \
        | tr -d '\r')" || true
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
    name="${name#"$app_id".}"  # a class named in full is the same class
    run_with_computer "$name" "$dir"
done

echo
printf '%s\n' "${results[@]}"
exit "$failed"
