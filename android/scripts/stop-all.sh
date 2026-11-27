#!/usr/bin/env bash
# Stops what device tests and builds leave running, for a human or an agent at a task's end (the owner's rule of
# 2026-11-27: "Ensure that emulators are properly killed when using them for testing or development. same thing for
# gradle biuld and adb servers."):
#
#   android/scripts/stop-all.sh [--gradle]
#
# - every emulator of device-test.sh's pool (CARACOLE_EMULATORS, 3 by default: emulator-5554, -5556, -5558) that is
#   up and whose lock is free: adb emu kill, its qemu waited for (CARACOLE_EMULATOR_STOP_WAIT seconds, 60 by default),
#   then killed; one whose lock another caller holds is in use, and left. This is how an emulator left by a
#   device-test.sh run that was SIGKILLed, or by a script older than the rule, is stopped: to device-test.sh it is
#   someone else's.
# - the Gradle daemons, only with --gradle: gradle --stop stops every daemon of that Gradle version for this user,
#   every checkout's and worktree's, a build running in one among them, so it refuses while any daemon of this user is
#   busy (gradle --status; one whose state it can't read counts as busy). Without --gradle it says how many run: each
#   stops by itself after two idle minutes (android/gradle.properties).
# - the adb server, only when adb lists no device at all, in any state (never while a phone is attached), and no
#   caller holds an emulator of the pool (one may be booting, not listed yet); never one it would start itself just to
#   look.
#
# It prints one line for each thing it stopped or left and why, does nothing twice, and exits 0 when nothing was
# running. Only this user's processes are looked at, each by its own program name and arguments.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
lock="${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}"
pool="${CARACOLE_EMULATORS:-3}"
wait="${CARACOLE_EMULATOR_STOP_WAIT:-60}"

gradle=0
case "${1-}" in
    "") ;;
    --gradle) gradle=1 ;;
    -h|--help) awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
    *) echo "stop-all.sh: unknown argument $1" >&2; exit 2 ;;
esac

say() { echo "stop-all.sh: $*"; }
lock_of() { if [ "$1" = 5554 ]; then echo "$lock"; else echo "${lock%.lock}-$1.lock"; fi; }
# This user's processes, "pid comm args" a line.
procs() { ps -u "$(id -u)" -o pid=,comm=,args= 2>/dev/null; }
# The qemu of emulator-$1: a process named qemu-system* whose arguments hold -port $1.
qemu_of() {
    procs | awk -v port="$1" '$2 ~ /^qemu-system/ { for (i = 3; i < NF; i++) if ($i == "-port" && $(i + 1) == port) {
        print $1; break } }'
}
# This user's Gradle daemons: a java whose arguments hold the GradleDaemon class.
gradle_daemons() {
    procs | awk '$2 == "java" { for (i = 3; i <= NF; i++) if ($i == "org.gradle.launcher.daemon.bootstrap.GradleDaemon") {
        print $1; break } }'
}

adb_bin="${ADB:-$(command -v adb || true)}"
[ -n "$adb_bin" ] || adb_bin="$(nix develop "$android#emulator" -c sh -c 'command -v adb')"
adb_cmd() { "$adb_bin" "$@" 8>&-; }  # an adb server it starts never holds a lock
look="$(adb_cmd devices 2>&1)"
adb_started=0
grep -q 'daemon started' <<<"$look" && adb_started=1
listed() { adb_cmd devices 2>/dev/null | awk '/^List of devices attached/ { on = 1; next } on && NF >= 2 { print $1 }'; }

# 1. The pool's emulators, each stopped while holding its lock, so no caller takes it as it dies.
mkdir -p "$(dirname "$lock")"
any=0
for ((i = 0; i < pool; i++)); do
    port=$((5554 + 2 * i))
    serial="emulator-$port"
    listed | grep -qx "$serial" || [ -n "$(qemu_of "$port")" ] || continue
    any=1
    exec 8>"$(lock_of "$port")"
    if ! flock -n 8; then
        say "left $serial: another caller holds its lock"
        exec 8>&-
        continue
    fi
    adb_cmd -s "$serial" emu kill >/dev/null 2>&1
    gone() { ! listed | grep -qx "$serial" && [ -z "$(qemu_of "$port")" ]; }
    for ((t = 0; t < wait * 10; t++)); do gone && break; sleep 0.1; done
    if gone; then
        say "stopped $serial"
    else
        # shellcheck disable=SC2046  # one pid a word
        kill $(qemu_of "$port") 2>/dev/null
        for ((t = 0; t < 100; t++)); do gone && break; sleep 0.1; done
        # shellcheck disable=SC2046
        gone || kill -KILL $(qemu_of "$port") 2>/dev/null
        for ((t = 0; t < 50; t++)); do gone && break; sleep 0.1; done
        if gone; then
            say "$serial didn't stop within $wait s of emu kill: killed it"
        else
            say "$serial didn't stop within $wait s of emu kill, nor when killed: it still runs"
        fi
    fi
    exec 8>&-
done
[ "$any" = 1 ] || say "no emulator of the pool is running"

# 2. The Gradle daemons: only with --gradle, and never while one is busy.
daemons="$(gradle_daemons)"
count="$(grep -c . <<<"$daemons")"
if [ "$count" = 0 ]; then
    say "no Gradle daemon is running"
elif [ "$gradle" = 0 ]; then
    say "left $count Gradle daemon(s): each stops by itself after two idle minutes (--gradle stops them now)"
else
    status="$(nix develop "$android" -c gradle -p "$android" --status 2>/dev/null)"
    idle="$(awk '$1 ~ /^[0-9]+$/ && $2 == "IDLE" { print $1 }' <<<"$status")"
    busy=0
    while read -r pid; do
        [ -n "$pid" ] && ! grep -qx "$pid" <<<"$idle" && busy=$((busy + 1))
    done <<<"$daemons"
    if [ "$busy" != 0 ]; then
        say "left $count Gradle daemon(s): $busy busy or of a state gradle --status doesn't say (a build may be running" \
            "in another checkout), and gradle --stop would stop every one"
    elif nix develop "$android" -c gradle -p "$android" --stop >/dev/null 2>&1; then
        say "stopped $count idle Gradle daemon(s) (gradle --stop)"
    else
        say "gradle --stop failed: a Gradle daemon may still run"
    fi
fi

# 3. The adb server: only with no device listed and no pool emulator held.
devices="$(listed)"
held=""
for ((i = 0; i < pool; i++)); do
    port=$((5554 + 2 * i))
    if ! flock -n "$(lock_of "$port")" true 2>/dev/null; then held="emulator-$port"; break; fi
done
if [ -n "$devices" ]; then
    say "left the adb server: $(paste -sd' ' <<<"$devices") is listed"
elif [ -n "$held" ]; then
    say "left the adb server: another caller holds $held"
elif [ "$adb_started" = 1 ]; then
    adb_cmd kill-server >/dev/null 2>&1
    say "no adb server was running"
else
    adb_cmd kill-server >/dev/null 2>&1
    say "stopped the adb server (no device listed)"
fi
exit 0
