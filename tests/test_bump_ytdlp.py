"""android/scripts/bump-ytdlp.sh, the owner's one command to move the app's pinned yt-dlp (the phone-youtube design's
§7), run from a copy in a checkout of its own against a fake PyPI on loopback (``CARACOLE_PYPI``) and a stand-in for
``nix-prefetch-url`` that fetches from loopback alone: what it writes into pins.json, and what it refuses with
pins.json left as it was. No test reaches PyPI, files.pythonhosted.org or Nix's store."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "android" / "scripts" / "bump-ytdlp.sh"
PINS = ROOT / "android" / "youtube" / "pins.json"

if not SCRIPT.parent.exists():  # the package build's tree: pyproject.toml, README.md, LICENSE, src/ and tests/ alone
    pytest.skip("android/ is not in this tree", allow_module_level=True)

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")]

# nix-prefetch-url --print-path URL: the URL fetched (loopback alone, else it fails), kept under store/ beside it, then
# a hash line and the path, as Nix prints them; each call logged to calls.jsonl.
PREFETCH = r'''
import json, sys, urllib.parse, urllib.request
from pathlib import Path
here = Path(__file__).resolve().parent
argv = sys.argv[1:]
with open(here / "calls.jsonl", "a") as f:
    f.write(json.dumps(argv) + "\n")
url = argv[-1]
if urllib.parse.urlsplit(url).hostname != "127.0.0.1":
    sys.exit(f"stand-in nix-prefetch-url: {url} is not on loopback")
data = urllib.request.urlopen(url).read()
store = here / "store"
store.mkdir(exist_ok=True)
path = store / url.rsplit("/", 1)[1]
path.write_bytes(data)
print("0" * 52)
if "--print-path" in argv:
    print(path)
'''


def wheel(name: str, version: str, requires: list[str] = ()) -> bytes:
    """A pure wheel holding its METADATA alone, of fixed dates, so its bytes are the same each time."""
    folder = name.replace("-", "_")
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    lines += [f"Requires-Dist: {r}" for r in requires]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo(f"{folder}-{version}.dist-info/METADATA", (2026, 1, 1, 0, 0, 0)),
                   "\n".join(lines) + "\n\nThe description.\n")
    return out.getvalue()


class FakePyPI:
    """PyPI's JSON API (`/pypi/<name>/json`, `/pypi/<name>/<version>/json`) and its files, on 127.0.0.1."""

    def __init__(self) -> None:
        self.releases: dict[str, dict[str, dict]] = {}  # name -> version -> {"wheel": bytes, "sha256": str, …}
        self.asked: list[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                fake.asked.append(self.path)
                body = fake.answer(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def add(self, name: str, version: str, requires: list[str] = (), *, sha256: str | None = None,
            yanked: bool = False) -> None:
        data = wheel(name, version, requires)
        self.releases.setdefault(name, {})[version] = {
            "wheel": data, "sha256": sha256 or hashlib.sha256(data).hexdigest(), "yanked": yanked}

    def file_name(self, name: str, version: str) -> str:
        return f"{name.replace('-', '_')}-{version}-py3-none-any.whl"

    def answer(self, path: str) -> bytes | None:
        parts = path.strip("/").split("/")
        if parts[0] == "files" and len(parts) == 4:
            release = self.releases.get(parts[1], {}).get(parts[2])
            return release["wheel"] if release and parts[3] == self.file_name(parts[1], parts[2]) else None
        if parts[0] != "pypi" or parts[-1] != "json" or len(parts) not in (3, 4):
            return None
        name = parts[1]
        versions = self.releases.get(name)
        if not versions:
            return None
        version = parts[2] if len(parts) == 4 else max(versions, key=lambda v: tuple(map(int, v.split("."))))
        release = versions.get(version)
        if release is None:
            return None
        file = self.file_name(name, version)
        sdist = {"packagetype": "sdist", "filename": f"{name}-{version}.tar.gz",
                 "url": f"{self.base}/files/{name}/{version}/{name}-{version}.tar.gz",
                 "digests": {"sha256": "1" * 64}, "yanked": False}
        whl = {"packagetype": "bdist_wheel", "filename": file, "url": f"{self.base}/files/{name}/{version}/{file}",
               "digests": {"sha256": release["sha256"]}, "yanked": release["yanked"]}
        return json.dumps({"info": {"name": name, "version": version}, "urls": [sdist, whl]}).encode()


@pytest.fixture
def pypi():
    fake = FakePyPI()
    yield fake
    fake.close()


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A checkout of its own: the script and the real pins.json, nothing else."""
    (tmp_path / "android" / "scripts").mkdir(parents=True)
    (tmp_path / "android" / "youtube").mkdir(parents=True)
    shutil.copy2(SCRIPT, tmp_path / "android" / "scripts" / SCRIPT.name)
    shutil.copy2(PINS, tmp_path / "android" / "youtube" / "pins.json")
    tools = tmp_path / "tools"
    tools.mkdir()
    stub = tools / "nix-prefetch-url"
    stub.write_text(f"#!{sys.executable}\n{PREFETCH}")
    stub.chmod(0o755)
    return tmp_path


def run(checkout: Path, pypi: FakePyPI, *args: str) -> subprocess.CompletedProcess:
    # The stand-in first on PATH, so no real nix-prefetch-url is ever run.
    env = {"PATH": f"{checkout / 'tools'}:{os.environ['PATH']}", "CARACOLE_PYPI": pypi.base, "HOME": str(checkout)}
    return subprocess.run(["bash", str(checkout / "android" / "scripts" / SCRIPT.name), *args],
                          capture_output=True, text=True, env=env, cwd=checkout, timeout=60)


def pins(checkout: Path) -> dict:
    return json.loads((checkout / "android" / "youtube" / "pins.json").read_text())


def prefetched(checkout: Path) -> list[list[str]]:
    calls = checkout / "tools" / "calls.jsonl"
    return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


OLD = json.loads(PINS.read_text())
NEW = "2099.1.2"  # later than any pin, so the test holds whatever the real pin moves to


def release(pypi: FakePyPI, version: str = NEW, ejs: str = "9.1.0", **kwargs) -> None:
    pypi.add("yt-dlp", version, [f"yt-dlp-ejs=={ejs}; extra == 'default'", "requests>=2; extra == 'default'"],
             **kwargs)
    pypi.add("yt-dlp-ejs", ejs)


def test_with_no_version_it_pins_pypis_latest_yt_dlp_and_the_ejs_its_wheel_requires(checkout, pypi):
    release(pypi, "2099.1.1", "9.0.0")
    release(pypi)
    result = run(checkout, pypi)
    assert result.returncode == 0, result.stderr
    got = pins(checkout)
    ytdlp, ejs = pypi.releases["yt-dlp"][NEW], pypi.releases["yt-dlp-ejs"]["9.1.0"]
    assert got["ytdlp"] == {"version": NEW, "url": f"{pypi.base}/files/yt-dlp/{NEW}/yt_dlp-{NEW}-py3-none-any.whl",
                            "sha256": hashlib.sha256(ytdlp["wheel"]).hexdigest()}
    assert got["ejs"] == {"version": "9.1.0",
                          "url": f"{pypi.base}/files/yt-dlp-ejs/9.1.0/yt_dlp_ejs-9.1.0-py3-none-any.whl",
                          "sha256": hashlib.sha256(ejs["wheel"]).hexdigest()}
    assert {k: v for k, v in got.items() if k not in ("ytdlp", "ejs")} == \
        {k: v for k, v in OLD.items() if k not in ("ytdlp", "ejs")}
    assert list(got) == list(OLD)
    text = (checkout / "android" / "youtube" / "pins.json").read_text()
    assert text == json.dumps(got, indent=2) + "\n"
    assert pypi.asked[:1] == ["/pypi/yt-dlp/json"]
    assert "/pypi/yt-dlp-ejs/9.1.0/json" in pypi.asked
    assert [call[-1] for call in prefetched(checkout)] == [got["ytdlp"]["url"], got["ejs"]["url"]]
    for line in (f"yt-dlp {OLD['ytdlp']['version']} -> {NEW}", "git add android/youtube/pins.json",
                 "device-test.sh --youtube", "versionCode", ":app:assembleRelease"):
        assert line in result.stdout


def test_a_version_given_is_the_one_pinned(checkout, pypi):
    release(pypi, "2099.1.1", "9.0.0")
    release(pypi)
    result = run(checkout, pypi, "2099.1.1")
    assert result.returncode == 0, result.stderr
    assert pins(checkout)["ytdlp"]["version"] == "2099.1.1"
    assert pins(checkout)["ejs"]["version"] == "9.0.0"
    assert pypi.asked[:1] == ["/pypi/yt-dlp/2099.1.1/json"]


def refused(checkout: Path, pypi: FakePyPI, *args: str) -> str:
    before = (checkout / "android" / "youtube" / "pins.json").read_bytes()
    result = run(checkout, pypi, *args)
    assert result.returncode != 0, result.stdout
    assert (checkout / "android" / "youtube" / "pins.json").read_bytes() == before
    assert sorted(p.name for p in (checkout / "android" / "youtube").iterdir()) == ["pins.json"]
    return result.stderr


def test_a_version_pypi_hasnt_got_is_refused(checkout, pypi):
    release(pypi)
    assert "yt-dlp 2099.9.9 is not on PyPI" in refused(checkout, pypi, "2099.9.9")
    assert prefetched(checkout) == []


def test_a_version_that_isnt_one_is_refused_before_any_request(checkout, pypi):
    assert "not a yt-dlp version" in refused(checkout, pypi, "../../evil")
    assert pypi.asked == []


def test_a_wheel_whose_bytes_arent_pypis_sha256_is_refused(checkout, pypi):
    release(pypi, sha256="2" * 64)
    assert "SHA-256" in refused(checkout, pypi)


def test_an_ejs_wheel_whose_bytes_arent_pypis_sha256_is_refused(checkout, pypi):
    release(pypi)
    pypi.releases["yt-dlp-ejs"]["9.1.0"]["sha256"] = "3" * 64
    assert "SHA-256" in refused(checkout, pypi)


def test_a_yt_dlp_whose_wheel_requires_no_ejs_is_refused(checkout, pypi):
    pypi.add("yt-dlp", NEW, ["requests>=2; extra == 'default'"])
    assert "names no yt-dlp-ejs==" in refused(checkout, pypi)


def test_a_yanked_release_is_refused(checkout, pypi):
    release(pypi, yanked=True)
    assert "yanked" in refused(checkout, pypi)


def test_an_older_version_than_the_pin_is_refused(checkout, pypi):
    release(pypi, "2000.1.1", "0.0.1")
    assert "older than the pinned" in refused(checkout, pypi, "2000.1.1")
    assert prefetched(checkout) == []


def test_the_version_pinned_already_changes_nothing(checkout, pypi):
    current = OLD["ytdlp"]["version"]
    release(pypi, current)
    before = (checkout / "android" / "youtube" / "pins.json").read_bytes()
    result = run(checkout, pypi, current)
    assert result.returncode == 0, result.stderr
    assert f"yt-dlp {current} is pinned already" in result.stdout
    assert (checkout / "android" / "youtube" / "pins.json").read_bytes() == before
    assert prefetched(checkout) == []
