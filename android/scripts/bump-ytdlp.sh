#!/usr/bin/env bash
# Moves the app's pinned yt-dlp to a new release (the phone-youtube design's §7), for the owner when YouTube changes
# what an older yt-dlp reads:
#
#   nix develop ./android -c android/scripts/bump-ytdlp.sh [VERSION]
#
# 1. It reads PyPI's JSON for yt-dlp: VERSION's (`/pypi/yt-dlp/VERSION/json`), else the latest (`/pypi/yt-dlp/json`).
#    A version not on PyPI, yanked, with no pure wheel (`py3-none-any`), or older than the one pinned is refused; the
#    one pinned already changes nothing.
# 2. It fetches the wheel into Nix's store (`nix-prefetch-url --print-path`, so the build's fixed-output fetch finds
#    it), checks its bytes are PyPI's SHA-256 and its METADATA names that version, and reads its `Requires-Dist` for
#    the yt-dlp-ejs of its default extra (`yt-dlp-ejs==X; extra == 'default'`, which yt-dlp refuses another of).
# 3. It does the same for that yt-dlp-ejs (`/pypi/yt-dlp-ejs/X/json`).
# 4. It rewrites android/youtube/pins.json's `ytdlp` and `ejs` (version, URL, SHA-256), the rest as it was, and prints
#    the steps left: android/README.md's "A release when YouTube changes".
#
# Nothing is written before every check passed. CARACOLE_PYPI names another PyPI (the tests' fake, on loopback); the
# script is the owner's, run by hand: no test runs it against the real PyPI.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pins="$here/../youtube/pins.json"

for tool in python3 nix-prefetch-url; do
    command -v "$tool" >/dev/null || {
        echo "bump-ytdlp.sh: $tool is not on PATH: run it in android/flake.nix's shell" \
            "(nix develop ./android -c android/scripts/bump-ytdlp.sh)" >&2
        exit 2
    }
done
[[ $# -le 1 ]] || { echo "usage: bump-ytdlp.sh [VERSION]" >&2; exit 2; }

exec python3 -I - "$pins" "${CARACOLE_PYPI:-https://pypi.org}" "$@" <<'PY'
import hashlib, json, os, re, subprocess, sys, tempfile, urllib.error, urllib.request, zipfile

pins_path, pypi = sys.argv[1], sys.argv[2].rstrip("/")
asked = sys.argv[3] if len(sys.argv) > 3 else None
VERSION = re.compile(r"\d+(\.\d+)*")


def refuse(words):
    print(f"bump-ytdlp.sh: {words}; android/youtube/pins.json is as it was", file=sys.stderr)
    sys.exit(1)


def key(version):
    return tuple(int(part) for part in version.split("."))


def release(name, version):
    """PyPI's JSON of a release (the latest with no version), and its pure wheel's entry."""
    url = f"{pypi}/pypi/{name}/{version}/json" if version else f"{pypi}/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=60) as answer:
            data = json.load(answer)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            refuse(f"{name} {version} is not on PyPI" if version else f"{name} is not on PyPI")
        refuse(f"PyPI answered {e.code} for {url}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        refuse(f"couldn't read PyPI's {url}: {e}")
    got = str(data.get("info", {}).get("version", ""))
    if not VERSION.fullmatch(got) or (version and got != version):
        refuse(f"PyPI's {url} names version {got!r}")
    wheels = [f for f in data.get("urls", []) if f.get("packagetype") == "bdist_wheel"
              and f.get("filename") == f"{name.replace('-', '_')}-{got}-py3-none-any.whl"]
    if len(wheels) != 1:
        refuse(f"{name} {got} has no pure wheel (py3-none-any) on PyPI")
    wheel = wheels[0]
    if wheel.get("yanked"):
        refuse(f"{name} {got} is yanked on PyPI")
    sha256 = str(wheel.get("digests", {}).get("sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        refuse(f"PyPI gives {name} {got}'s wheel no SHA-256")
    return got, str(wheel["url"]), sha256


def fetched(name, version, url, sha256):
    """The wheel fetched into Nix's store, checked, and its METADATA's header fields."""
    try:
        out = subprocess.run(["nix-prefetch-url", "--type", "sha256", "--print-path", url],
                             capture_output=True, text=True, check=True).stdout.split()
    except subprocess.CalledProcessError as e:
        refuse(f"nix-prefetch-url couldn't fetch {url}: {e.stderr.strip()}")
    path = out[-1]
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        refuse(f"{url}'s bytes have SHA-256 {digest}, not PyPI's {sha256}")
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"[^/]+\.dist-info/METADATA", n)]
        if len(names) != 1:
            refuse(f"{url} holds no one METADATA")
        header = z.read(names[0]).decode().split("\n\n", 1)[0].splitlines()
    fields = {}
    for line in header:
        field, _, value = line.partition(": ")
        fields.setdefault(field, []).append(value)
    if fields.get("Name") != [name] or fields.get("Version") != [version]:
        refuse(f"{url}'s METADATA is of {fields.get('Name')} {fields.get('Version')}, not {name} {version}")
    return fields


if asked is not None and not VERSION.fullmatch(asked):
    refuse(f"{asked!r} is not a yt-dlp version (2026.11.23)")
with open(pins_path) as f:
    pins = json.load(f)
old = pins["ytdlp"]["version"]
if asked is not None and asked == old:
    print(f"yt-dlp {old} is pinned already: nothing to do.")
    sys.exit(0)
if asked is not None and key(asked) < key(old):
    refuse(f"yt-dlp {asked} is older than the pinned {old}")

version, url, sha256 = release("yt-dlp", asked)
if version == old:
    print(f"yt-dlp {old}, PyPI's latest, is pinned already: nothing to do.")
    sys.exit(0)
if key(version) < key(old):
    refuse(f"yt-dlp {version} is older than the pinned {old}")
requires = fetched("yt-dlp", version, url, sha256).get("Requires-Dist", [])
ejs = [m.group(1) for r in requires if (m := re.fullmatch(r"yt-dlp-ejs==([^;\s]+); extra == 'default'", r))]
if len(ejs) != 1 or not VERSION.fullmatch(ejs[0]):
    refuse(f"yt-dlp {version}'s METADATA names no yt-dlp-ejs== of its default extra")
ejs_version, ejs_url, ejs_sha256 = release("yt-dlp-ejs", ejs[0])
fetched("yt-dlp-ejs", ejs_version, ejs_url, ejs_sha256)

old_ejs = pins["ejs"]["version"]
pins["ytdlp"] = {"version": version, "url": url, "sha256": sha256}
pins["ejs"] = {"version": ejs_version, "url": ejs_url, "sha256": ejs_sha256}
folder = os.path.dirname(os.path.abspath(pins_path))
fd, temporary = tempfile.mkstemp(prefix=".pins-", suffix=".json", dir=folder)
try:
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(pins, indent=2) + "\n")
    os.chmod(temporary, 0o644)
    os.replace(temporary, pins_path)
except BaseException:
    os.unlink(temporary)
    raise

print(f"""Pinned yt-dlp {old} -> {version} and yt-dlp-ejs {old_ejs} -> {ejs_version} in android/youtube/pins.json.
Left to do (android/README.md, "A release when YouTube changes"):
  1. git add android/youtube/pins.json   (the flake reads only what git tracks)
  2. nix develop ./android -c gradle -p android :youtube:testDebugUnitTest   (PinsTest: the wheels are the pins)
  3. android/scripts/device-test.sh --youtube   (YtDlpVersionTest: the app runs the pinned yt-dlp)
  4. raise versionCode and versionName in android/app/build.gradle.kts
  5. nix develop ./android -c gradle -p android :app:assembleRelease, then android/scripts/release-check.sh
  6. one song by hand on the phone: a pasted video to Ready
  7. publish: the APK into docs/fdroid/repo, fdroid update, commit docs/fdroid and push main (android/README.md,
     "Release")""")
PY
