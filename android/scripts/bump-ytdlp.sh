#!/usr/bin/env bash
# Moves the app's pinned yt-dlp to a new release (the phone-youtube design's §7), for the owner when YouTube changes
# what an older yt-dlp reads:
#
#   nix develop ./android -c android/scripts/bump-ytdlp.sh [--older] [VERSION]
#
# 1. It reads PyPI's JSON for yt-dlp: VERSION's (`/pypi/yt-dlp/VERSION/json`, a tag's `2026.01.05` read as PyPI's
#    `2026.1.5`), else the latest (`/pypi/yt-dlp/json`). A version not on PyPI, yanked, with no pure wheel
#    (`py3-none-any`), a wheel anywhere but `https://files.pythonhosted.org/…/<its file name>`, or older than the one
#    pinned is refused; `--older VERSION` takes an older one (a rollback after a yt-dlp regression), every check still
#    made. The one pinned already changes nothing.
# 2. It fetches the wheel into Nix's store (`nix-prefetch-url --print-path`, so the build's fixed-output fetch finds
#    it), checks its bytes are PyPI's SHA-256 and its METADATA names that version, and reads its `Requires-Dist` for
#    the yt-dlp-ejs of its default extra (`yt-dlp-ejs==X; extra == 'default'`, which yt-dlp refuses another of).
# 3. It does the same for that yt-dlp-ejs (`/pypi/yt-dlp-ejs/X/json`).
# 4. It rewrites android/youtube/pins.json's `ytdlp` and `ejs` (version, URL, SHA-256), the rest as it was, and prints
#    the steps left: android/README.md's "A release when YouTube changes".
#
# Nothing is written before every check passed; any refusal, or an answer of another shape, ends in "pins.json is as
# it was". CARACOLE_PYPI names another PyPI: the tests' fake, on loopback, whose own host alone may then serve the
# wheels. The script is the owner's, run by hand: no test runs it against the real PyPI.
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

exec python3 -I - "$pins" "${CARACOLE_PYPI:-https://pypi.org}" "$@" <<'PY'
import hashlib, json, os, re, subprocess, sys, tempfile, urllib.error, urllib.parse, urllib.request, zipfile

pins_path, pypi = sys.argv[1], sys.argv[2].rstrip("/")
VERSION = re.compile(r"\d+(\.\d+)*")
FILES = "files.pythonhosted.org"
# The tests' fake PyPI, on loopback: its own host may serve the wheels; any other PyPI's must be files.pythonhosted.org.
PYPI_HOST = urllib.parse.urlsplit(pypi)
LOOPBACK = PYPI_HOST.hostname in ("127.0.0.1", "::1")  # an address, never a name looked up


def refuse(words):
    print(f"bump-ytdlp.sh: {words}; android/youtube/pins.json is as it was", file=sys.stderr)
    sys.exit(1)


def usage(words):
    print(f"bump-ytdlp.sh: {words}\nusage: bump-ytdlp.sh [--older] [VERSION]", file=sys.stderr)
    sys.exit(2)


def normal(version):
    """A version as PyPI calls it: each part's leading zeros dropped (yt-dlp's tag 2026.01.05 is PyPI's 2026.1.5)."""
    return ".".join(str(int(part)) for part in version.split("."))


def key(version):
    return tuple(int(part) for part in version.split("."))


def checked_url(name, version, url, filename):
    """The wheel's URL, only https://files.pythonhosted.org/…/<filename> (or the loopback fake's own host), written
    canonically: no whitespace or control character, and the very text urlsplit and urlunsplit give back (no empty
    `?` or `#`), its host as written lower-case."""
    parts = urllib.parse.urlsplit(url)
    pythonhosted = parts.scheme == "https" and parts.netloc == FILES
    fake = LOOPBACK and parts.scheme in ("http", "https") and parts.netloc == PYPI_HOST.netloc
    if (not (pythonhosted or fake) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
            or url != urllib.parse.urlunsplit(parts) or parts.query or parts.fragment
            or not parts.path.endswith("/" + filename)):
        refuse(f"PyPI gives {name} {version}'s wheel at {url}, not https://{FILES}/…/{filename}")
    return url


def release(name, version):
    """PyPI's JSON of a release (the latest with no version), and its pure wheel's version, URL and SHA-256."""
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
    filename = f"{name.replace('-', '_')}-{got}-py3-none-any.whl"
    wheels = [f for f in data.get("urls", []) if f.get("packagetype") == "bdist_wheel" and f.get("filename") == filename]
    if len(wheels) != 1:
        refuse(f"{name} {got} has no pure wheel (py3-none-any) on PyPI")
    wheel = wheels[0]
    if wheel.get("yanked"):
        refuse(f"{name} {got} is yanked on PyPI")
    sha256 = str(wheel.get("digests", {}).get("sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        refuse(f"PyPI gives {name} {got}'s wheel no SHA-256")
    return got, checked_url(name, got, str(wheel.get("url", "")), filename), sha256


def fetched(name, version, url, sha256):
    """The wheel fetched into Nix's store, checked, and its METADATA's header fields."""
    try:
        out = subprocess.run(["nix-prefetch-url", "--type", "sha256", "--print-path", url],
                             capture_output=True, text=True, check=True).stdout.split()
    except subprocess.CalledProcessError as e:
        refuse(f"nix-prefetch-url couldn't fetch {url}: {e.stderr.strip()}")
    if len(out) != 2:
        refuse(f"nix-prefetch-url printed no hash and path for {url}")
    with open(out[1], "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        refuse(f"{url}'s bytes have SHA-256 {digest}, not PyPI's {sha256}")
    with zipfile.ZipFile(out[1]) as z:
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


def write(pins):
    """pins.json replaced whole: a temporary file in its folder, synced, then renamed over it."""
    folder = os.path.dirname(os.path.abspath(pins_path))
    fd, temporary = tempfile.mkstemp(prefix=".pins-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(pins, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, pins_path)
    except BaseException:
        os.unlink(temporary)
        raise
    try:  # the rename itself made lasting; pins.json is the new one already, so a failure here is no refusal
        folder_fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(folder_fd)
        finally:
            os.close(folder_fd)
    except OSError:
        pass


def main(args):
    older = args.count("--older")
    rest = [a for a in args if a != "--older"]
    if older > 1 or len(rest) > 1 or any(a.startswith("-") for a in rest):
        usage(f"unexpected arguments: {' '.join(args)}")
    if older and not rest:
        usage("--older needs the VERSION to go back to")
    asked = rest[0] if rest else None
    if asked is not None:
        if not VERSION.fullmatch(asked):
            refuse(f"{asked!r} is not a yt-dlp version (2026.11.23)")
        if normal(asked) != asked:
            print(f"yt-dlp {asked} is {normal(asked)} on PyPI.")
            asked = normal(asked)
    with open(pins_path) as f:
        pins = json.load(f)
    old = str(pins["ytdlp"]["version"])
    if asked == old:
        print(f"yt-dlp {old} is pinned already: nothing to do.")
        return
    if asked is not None and key(asked) < key(old) and not older:
        refuse(f"yt-dlp {asked} is older than the pinned {old} (--older {asked} goes back to it)")
    if asked is not None and key(asked) > key(old) and older:
        usage(f"yt-dlp {asked} is newer than the pinned {old}: no --older")

    version, url, sha256 = release("yt-dlp", asked)
    if version == old:
        print(f"yt-dlp {old}, PyPI's latest, is pinned already: nothing to do.")
        return
    if key(version) < key(old) and not older:
        refuse(f"PyPI's latest yt-dlp {version} is older than the pinned {old}")
    requires = fetched("yt-dlp", version, url, sha256).get("Requires-Dist", [])
    ejs = [m.group(1) for r in requires if (m := re.fullmatch(r"yt-dlp-ejs==([^;\s]+); extra == 'default'", r))]
    if len(ejs) != 1 or not VERSION.fullmatch(ejs[0]):
        refuse(f"yt-dlp {version}'s METADATA names no yt-dlp-ejs== of its default extra")
    ejs_version, ejs_url, ejs_sha256 = release("yt-dlp-ejs", ejs[0])
    fetched("yt-dlp-ejs", ejs_version, ejs_url, ejs_sha256)

    old_ejs = pins["ejs"]["version"]
    pins["ytdlp"] = {"version": version, "url": url, "sha256": sha256}
    pins["ejs"] = {"version": ejs_version, "url": ejs_url, "sha256": ejs_sha256}
    write(pins)
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


try:
    main(sys.argv[3:])
except (KeyError, IndexError, TypeError, AttributeError, ValueError, OSError, zipfile.BadZipFile) as e:
    refuse(f"an answer or a file of another shape than expected ({type(e).__name__}: {e})")
PY
