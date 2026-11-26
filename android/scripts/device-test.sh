#!/usr/bin/env bash
# The phone's device tests on a pool of emulators, one caller an emulator at a time (AGENTS.md, "How work is done
# here"):
#
#   android/scripts/device-test.sh [--computer DIR] [--sites SCENARIO] [--area NAME[,NAME...]] [--app] [--ml]
#                                  [--tcpdump FILE] [CLASS[=DIR]]...
#
#   --area NAMES    CorpusOnDeviceTest's areas (core, server and viewer.testing's Replays); "all" or an empty
#                   list: every one
#   --app           the app's classes: EndToEndTest, PinchTest, SyncSheetTest, ExportImportTest and
#                   PhoneEndToEndTest, each against a computer of its own (tests.helpers.e2e_library in a fresh
#                   folder)
#   CLASS[=DIR]     a class of app/src/androidTest (NoSitesTest, LocalServerTest..., or in full:
#                   io.github.danielhp95.caracole.NoSitesTest), with DIR its computer's folder
#   --computer DIR  one computer for every class that names none
#   --sites S       the fake sites server of scenario S (tests/helpers/fake_sites.py serve S PORT, on the host, a
#                   free port never 8737) for every class run, named to each as -e sites http://10.0.2.2:PORT
#   --ml            :ml's ModelParityTest (its own test APK, io.github.danielhp95.caracole.ml.test), then the app's
#                   ChordsBenchTest (the debug build's Chords bench), over the chord and beat models in
#                   $CARACOLE_CHORD_MODELS (`nix build .#chord-models`; unset, the ./android#ml shell's), pushed into
#                   /data/local/tmp/caracole-models, a cache left there for the next run (a file pushed again only
#                   when its SHA-256 differs)
#   --tcpdump FILE  every packet the emulator sends or gets while the classes run, into FILE (pcap), with Wi-Fi off
#                   so that all of it goes through the one interface the emulator's console captures (its cellular
#                   network); any packet to or from a host but 10.0.2.2 fails the run (ARP between the emulator and
#                   10.0.2.2, and link-local multicast, which reaches no host, are listed and allowed). A control
#                   before and after the classes, a ping of 10.0.2.2 and a TCP connection to a listener of the
#                   script's on the host's loopback, must be in the capture, or it fails too: a capture that
#                   recorded nothing, or a network with no route out, proves nothing. The script turns Wi-Fi back on
#                   as it ends, an error too; killed with SIGKILL it can't: `adb -s emulator-NNNN shell svc wifi
#                   enable` then
#
# It builds assembleDebug and assembleDebugAndroidTest first (the debug build, io.github.danielhp95.caracole.debug, and
# its tests, io.github.danielhp95.caracole.debug.test), outside the lock, then takes the first free emulator of
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
ns=io.github.danielhp95.caracole        # the classes' package (the app's namespace)
app_id="$ns.debug"                      # the debug build's package, which the tests run: never the release's
runner="$app_id.test/$ns.CaracoleTestRunner"
lock="${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}"
logs="${CARACOLE_DEVICE_LOGS:-${XDG_RUNTIME_DIR:-/tmp}/caracole-device-test}"

areas=""
want_areas=0
want_app=0
want_ml=0
tcpdump=""
computer=""
sites=""
classes=()

usage() { awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 2; }  # the header, whole

while [ $# -gt 0 ]; do
    case "$1" in
        --area) want_areas=1; areas="${2-}"; [ $# -ge 2 ] || usage; shift 2 ;;
        --area=*) want_areas=1; areas="${1#--area=}"; shift ;;
        --app) want_app=1; shift ;;
        --ml) want_ml=1; shift ;;
        --tcpdump) tcpdump="${2-}"; [ -n "$tcpdump" ] || usage; shift 2 ;;
        --computer) computer="${2-}"; [ -n "$computer" ] || usage; shift 2 ;;
        --sites) sites="${2-}"; [ -n "$sites" ] || usage; shift 2 ;;
        -h|--help) usage ;;
        -*) echo "device-test.sh: unknown option $1" >&2; usage ;;
        *) classes+=("$1"); shift ;;
    esac
done
[ "$want_areas" = 1 ] || [ "$want_app" = 1 ] || [ "$want_ml" = 1 ] || [ ${#classes[@]} -gt 0 ] || usage
[ "$areas" = all ] && areas=""
[ -z "$tcpdump" ] || tcpdump="$(realpath -m "$tcpdump")"

# 1. The build, outside the lock, so a lane that builds never holds the emulator.
tasks=(assembleDebug assembleDebugAndroidTest)
[ "$want_ml" = 1 ] && tasks+=(:ml:assembleDebugAndroidTest)
(cd "$repo" && nix develop ./android -c gradle -p android "${tasks[@]}" --console=plain -q)
apk="$android/app/build/outputs/apk/debug/app-debug.apk"
test_apk="$android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
ml_apk="$android/ml/build/outputs/apk/androidTest/debug/ml-debug-androidTest.apk"
ml_models=/data/local/tmp/caracole-models
if [ "$want_ml" = 1 ]; then
    models="${CARACOLE_CHORD_MODELS:-$(cd "$repo" && nix develop ./android#ml -c printenv CARACOLE_CHORD_MODELS)}"
    [ -f "$models/btc-graph.onnx" ] || { echo "device-test.sh: no chord models in '$models'" >&2; exit 2; }
fi

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
if [ "$want_ml" = 1 ]; then
    adb install -r -t "$ml_apk" >/dev/null
    adb shell mkdir -p "$ml_models"
    for file in "$models"/*; do
        name="$(basename "$file")"
        there="$(adb shell sha256sum "$ml_models/$name" 2>/dev/null | awk '{ print $1 }' || true)"
        [ "$there" = "$(sha256sum "$file" | awk '{ print $1 }')" ] || adb push "$file" "$ml_models/$name" >/dev/null
    done
fi

# The computers this run started, stopped as it ends.
servers=()
capturing=0
cleanup() {
    for pid in "${servers[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
    # A run cut short while it captured leaves the emulator as it found it: capturing nothing, its Wi-Fi on.
    if [ "$capturing" = 1 ]; then
        adb emu network capture stop >/dev/null 2>&1 || true
        adb shell svc wifi enable || true
    fi
}
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

# The capture, with Wi-Fi off (the console captures the cellular network alone), once the network has settled. Its
# control: a listener on the host's loopback (10.0.2.2 to the emulator, nothing that leaves the machine), and
# `control`, a ping of 10.0.2.2 and one connection to the listener, sent before and after the classes.
capture=""
if [ -n "$tcpdump" ]; then
    probe_port="$(free_port)"
    while [ "$probe_port" = 8737 ]; do probe_port="$(free_port)"; done
    (exec 9>&-; exec python3 -c 'import socket, sys
s = socket.create_server(("127.0.0.1", int(sys.argv[1])))
while True:
    c, _ = s.accept(); c.recv(64); c.sendall(b"ok\n"); c.close()' "$probe_port") &
    servers+=($!)
    capturing=1
    adb shell svc wifi disable
    sleep 15
    capture="$(adb emu network capture start "caracole-$$.pcap" | tr -d '\r' | sed -n 's/^OK: capturing to //p')"
    [ -n "$capture" ] || { echo "device-test.sh: the emulator wouldn't capture" >&2; exit 3; }
    echo "device-test.sh: capturing into $tcpdump" >&2
fi
control() {
    [ -n "$capture" ] || return 0
    adb shell ping -c 1 -W 2 10.0.2.2 >/dev/null 2>&1 || true
    adb shell "echo caracole-probe | nc -w 2 10.0.2.2 $probe_port" >/dev/null 2>&1 || true
}
control

# One class run: `am instrument -w`, its args; the app's data cleared, the print spooler and choosers closed after.
run_class() {
    local name="$1"; shift
    local out
    out="$(adb shell am instrument -w -e class "$ns.$name" "$@" ${site_args[@]+"${site_args[@]}"} "$runner" 2>&1 \
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

if [ "$want_ml" = 1 ]; then
    out="$(adb shell am instrument -w -e class "$ns.ml.ModelParityTest" -e models "$ml_models" \
        "$ns.ml.test/androidx.test.runner.AndroidJUnitRunner" 2>&1 | tr -d '\r')" || true
    echo "$out"
    if grep -q '^OK (' <<<"$out" && ! grep -qE 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed' <<<"$out"; then
        results+=("PASS ModelParityTest")
    else
        results+=("FAIL ModelParityTest")
        failed=1
    fi
    # The debug build's Chords bench over the committed clips, on the same pushed models.
    run_class ChordsBenchTest -e models "$ml_models"
fi

if [ "$want_app" = 1 ]; then
    base="$(mktemp -d "${TMPDIR:-/tmp}/caracole-device-XXXXXX")"
    for name in EndToEndTest PinchTest SyncSheetTest ExportImportTest PhoneEndToEndTest; do
        run_with_computer "$name" "${computer:-$base/$name}"
    done
fi
for spec in "${classes[@]:-}"; do
    [ -n "$spec" ] || continue
    name="${spec%%=*}"
    dir=""
    if [ "$spec" != "$name" ]; then dir="${spec#*=}"; else dir="$computer"; fi
    name="${name#"$ns".}"  # a class named in full is the same class
    run_with_computer "$name" "$dir"
done

# The capture read: a packet to or from a host but 10.0.2.2 fails the run, and so does a control missing from it.
if [ -n "$capture" ]; then
    control
    adb emu network capture stop >/dev/null
    adb shell svc wifi enable
    capturing=0
    mv "$capture" "$tcpdump"
    read_ok=0
    python3 - "$tcpdump" "$probe_port" <<'EOF' || read_ok=$?
import ipaddress, struct, sys

data = open(sys.argv[1], "rb").read()
assert data[:4] == bytes.fromhex("d4c3b2a1") and struct.unpack("<I", data[20:24])[0] == 1, "not an Ethernet pcap"
guest, host = ipaddress.ip_address("10.0.2.15"), ipaddress.ip_address("10.0.2.2")
probe = int(sys.argv[2])
packets, others, allowed = 0, [], []
# The control's packets: ICMP echo requests and replies, the listener's SYN and SYN-ACK, each way.
seen = {"ping": 0, "pong": 0, "syn": 0, "syn-ack": 0}
at = 24
while at < len(data):
    length = struct.unpack("<I", data[at + 8:at + 12])[0]
    frame = data[at + 16:at + 16 + length]
    at += 16 + length
    packets += 1
    kind = frame[12:14].hex()
    if kind == "0806":
        src, dst = ipaddress.ip_address(frame[28:32]), ipaddress.ip_address(frame[38:42])
        (allowed if {src, dst} <= {guest, host} else others).append(f"ARP {src} -> {dst}")
        continue
    if kind == "0800":
        src, dst = ipaddress.ip_address(frame[26:30]), ipaddress.ip_address(frame[30:34])
    elif kind == "86dd":
        src, dst = ipaddress.ip_address(frame[22:38]), ipaddress.ip_address(frame[38:54])
    else:
        others.append(f"ethertype {kind}")
        continue
    if {src, dst} == {guest, host}:
        if kind == "0800":
            body = frame[14 + 4 * (frame[14] & 15):]
            if frame[23] == 1 and body[0] == 8 and dst == host:
                seen["ping"] += 1
            elif frame[23] == 1 and body[0] == 0 and dst == guest:
                seen["pong"] += 1
            elif frame[23] == 6:
                ports, flags = struct.unpack(">HH", body[:4]), body[13]
                if dst == host and ports[1] == probe and flags & 0x12 == 0x02:
                    seen["syn"] += 1
                elif dst == guest and ports[0] == probe and flags & 0x12 == 0x12:
                    seen["syn-ack"] += 1
        continue
    if any(dst in ipaddress.ip_network(net) for net in ("224.0.0.0/24", "ff02::/16")):
        allowed.append(f"link-local multicast {src} -> {dst}")
        continue
    others.append(f"{src} -> {dst}")
print(f"tcpdump: {packets} packets, {len(others)} to or from a host but 10.0.2.2")
missing = [name for name, n in seen.items() if n < 2]
print("  control (before and after the classes): " + ", ".join(f"{name} {n}" for name, n in seen.items())
      + (f"; missing: {', '.join(missing)}: the capture proves nothing" if missing else ""))
for line in sorted(set(allowed)):
    print(f"  allowed: {line}")
for line in others:
    print(f"  {line}")
sys.exit(1 if others or missing else 0)
EOF
    if [ "$read_ok" = 0 ]; then results+=("PASS tcpdump"); else results+=("FAIL tcpdump"); failed=1; fi
fi

echo
printf '%s\n' "${results[@]}"
exit "$failed"
