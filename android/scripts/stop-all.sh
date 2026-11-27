#!/usr/bin/env bash
# Stops what device tests and builds leave running, for a human or an agent at a task's end (the owner's rule of
# 2026-11-27: "Ensure that emulators are properly killed when using them for testing or development. same thing for
# gradle biuld and adb servers."):
#
#   android/scripts/stop-all.sh
#
# - every emulator of device-test.sh's pool (CARACOLE_EMULATORS, 3 by default: emulator-5554, -5556, -5558) that is
#   up and whose lock is free: adb emu kill, its qemu waited for (CARACOLE_EMULATOR_STOP_WAIT seconds, 60 by default),
#   then killed; one whose lock another caller holds is in use, and left;
# - the Gradle daemons, gradle --stop through this checkout's android shell (it stops every daemon of that Gradle
#   version for this user), when one runs;
# - the adb server, only when adb lists no device at all (never while a phone is attached), and never one it would
#   start itself just to look.
#
# It prints one line for each thing it stopped or left and why, does nothing twice, and exits 0 when nothing was
# running.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
lock="${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}"
pool="${CARACOLE_EMULATORS:-3}"
wait="${CARACOLE_EMULATOR_STOP_WAIT:-60}"

case "${1-}" in
    "") ;;
    -h|--help) awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
    *) echo "stop-all.sh: unknown argument $1" >&2; exit 2 ;;
esac

say() { echo "stop-all.sh: $*"; }
lock_of() { if [ "$1" = 5554 ]; then echo "$lock"; else echo "${lock%.lock}-$1.lock"; fi; }
qemu_of() { pgrep -f "qemu-system.*-port $1( |$)" 2>/dev/null; }

adb_bin="${ADB:-$(command -v adb || true)}"
[ -n "$adb_bin" ] || adb_bin="$(nix develop "$android#emulator" -c sh -c 'command -v adb')"
look="$("$adb_bin" devices 2>&1)"
adb_started=0
grep -q 'daemon started' <<<"$look" && adb_started=1
listed() { "$adb_bin" devices 2>/dev/null | awk '/^List of devices attached/ { on = 1; next } on && NF >= 2 { print $1 }'; }

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
    "$adb_bin" -s "$serial" emu kill >/dev/null 2>&1
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
        say "$serial didn't stop within $wait s of emu kill: killed it"
    fi
    exec 8>&-
done
[ "$any" = 1 ] || say "no emulator of the pool is running"

# 2. The Gradle daemons.
if pgrep -f GradleDaemon >/dev/null 2>&1; then
    if nix develop "$android" -c gradle -p "$android" --stop >/dev/null 2>&1; then
        say "stopped the Gradle daemons (gradle --stop)"
    else
        say "gradle --stop failed: a Gradle daemon may still run"
    fi
else
    say "no Gradle daemon is running"
fi

# 3. The adb server: only with no device listed.
devices="$(listed)"
if [ -n "$devices" ]; then
    say "left the adb server: $(paste -sd' ' <<<"$devices") is listed"
elif [ "$adb_started" = 1 ]; then
    "$adb_bin" kill-server >/dev/null 2>&1
    say "no adb server was running"
else
    "$adb_bin" kill-server >/dev/null 2>&1
    say "stopped the adb server (no device listed)"
fi
exit 0
