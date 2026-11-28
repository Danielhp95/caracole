#!/usr/bin/env bash
# A debug build of this checkout on your phone, beside F-Droid's caracole (android/README.md, "Your phone: F-Droid and
# a debug build side by side"):
#
#   android/scripts/phone-install.sh [-s SERIAL] [--launch]
#
#   -s SERIAL   the device to install on, as `adb devices` names it; else the one phone connected (an emulator-NNNN
#               never counts), and an error that lists the devices when there is none or more than one
#   --launch    start the app once it is installed
#
# It builds the debug APK of the checkout it is in, in the ml shell so the chord models' :ml is in it (nix develop
# <checkout>/android#ml -c gradle -p <checkout>/android :app:assembleDebug --max-workers=2), checks that it is the
# debug build, io.github.danielhp95.caracole.debug, then installs it for the phone's own user alone (adb install -r --user 0: another user of the phone is left alone) and
# says the package and the versionName the phone now has. It never touches F-Droid's io.github.danielhp95.caracole.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android="$(dirname "$here")"
package=io.github.danielhp95.caracole.debug
activity=io.github.danielhp95.caracole.MainActivity

serial=""
launch=0

usage() { awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 2; }  # the header, whole
fail() { echo "phone-install.sh: $*" >&2; exit "${code:-1}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        -s) serial="${2-}"; [ -n "$serial" ] || usage; shift 2 ;;
        -s*) serial="${1#-s}"; shift ;;
        --launch) launch=1; shift ;;
        -h|--help) usage ;;
        *) echo "phone-install.sh: unknown argument $1" >&2; usage ;;
    esac
done

# adb: $ADB, the host's, else the emulator shell's.
adb_bin="${ADB:-$(command -v adb || true)}"
[ -n "$adb_bin" ] || adb_bin="$(nix develop "$android#emulator" -c sh -c 'command -v adb')"

# 1. The device, before the build: its serial and state, one a line, read after adb's header alone (an adb server
# that starts says so first: "* daemon not running; starting now", "* daemon started successfully").
devices="$("$adb_bin" devices | awk '/^List of devices attached/ { listing = 1; next } listing && NF >= 2 { print $1, $2 }')"
listed() {
    if [ -z "$devices" ]; then
        echo "  (none: connect one, android/README.md says how)"
        return
    fi
    # shellcheck disable=SC2001  # every line indented: a parameter expansion has no anchor at a line's start
    sed 's/^/  /' <<<"$devices"
}
if [ -n "$serial" ]; then
    state="$(awk -v s="$serial" '$1 == s { print $2; exit }' <<<"$devices")"
    [ -n "$state" ] || code=3 fail "$serial isn't connected. adb lists:
$(listed)"
    [ "$state" = device ] || code=3 fail "$serial is $state, not ready (unauthorized: accept the prompt on the phone)."
else
    phones="$(awk '$2 == "device" && $1 !~ /^emulator-/ { print $1 }' <<<"$devices")"
    count="$(grep -c . <<<"$phones" || true)"
    if [ "$count" = 0 ]; then
        code=3 fail "no phone is connected and ready. adb lists:
$(listed)"
    elif [ "$count" != 1 ]; then
        code=3 fail "more than one phone is connected: name one with -s SERIAL. adb lists:
$(listed)"
    fi
    serial="$phones"
fi
echo "phone-install.sh: installing on $serial" >&2

# 2. The debug APK of this checkout.
nix develop "$android#ml" -c gradle -p "$android" :app:assembleDebug --max-workers=2
out="$android/app/build/outputs/apk/debug"
apk="$out/app-debug.apk"
[ -f "$apk" ] || fail "the build made no $apk"
meta_of() { sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$out/output-metadata.json" 2>/dev/null | head -n 1; }
built="$(meta_of applicationId)"
[ "$built" = "$package" ] || code=4 fail "the APK built is ${built:-of no package}, not $package: nothing installed."

# 3. Installed for the phone's own user alone.
if ! said="$("$adb_bin" -s "$serial" install -r --user 0 "$apk" 2>&1)"; then
    fail "not installed. adb said:
$(sed 's/\r$//; s/^/  /' <<<"$said")
Often a debug build signed with another machine's key is installed already, and none installs over it: then remove
it with
  adb -s $serial uninstall --user 0 $package
(its library goes with it) and run this again."
fi
echo "${said//$'\r'/}" >&2
version="$("$adb_bin" -s "$serial" shell dumpsys package "$package" | tr -d '\r' \
    | sed -n 's/^ *versionName=\(.*\)$/\1/p' | head -n 1)"
echo "Installed $package ${version:-$(meta_of versionName)} on $serial."

if [ "$launch" = 1 ]; then
    "$adb_bin" -s "$serial" shell am start --user 0 -n "$package/$activity" >/dev/null
    echo "Started it."
fi
