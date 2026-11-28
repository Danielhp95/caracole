"""nix/publish-models.sh, the owner's upload of beat_this's converted graphs and its licence to the GitHub release
`models` (the phone's models' job fetches them: core.models' ModelsSource), run against a fake ``gh`` (helpers/fake_gh.py): no test reaches
GitHub."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers.fake_gh import FakeGh

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "nix" / "publish-models.sh"
PINS = ROOT / "tests" / "conformance" / "data" / "caracole" / "autochords" / "models.json"

pytestmark = [
    pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="needs bash and jq"),
]

FP32 = "beat_this-final0.onnx"
FP16 = "beat_this-final0-fp16.onnx"
LICENCE = "beat_this-LICENSE.txt"
APK_LICENCE = ROOT / "android" / "ml" / "licenses" / LICENCE  # the one the APK carries, which the Nix wrapper names


class Rig:
    """A folder of the two graphs (small stand-ins) and the pins that name them, as models.json names the real ones."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.gh = FakeGh(tmp_path / "bin", tag="models")
        self.dir = tmp_path / "models"
        self.dir.mkdir()
        self.files = {FP32: b"the fp32 graph", FP16: b"the fp16 graph"}
        for name, data in self.files.items():
            (self.dir / name).write_bytes(data)
        (self.dir / "btc-graph.onnx").write_bytes(b"never uploaded")
        pins = json.loads(PINS.read_text(encoding="utf-8"))
        for key, name in (("fp32", FP32), ("fp16", FP16)):
            pins["beats"][key].update(bytes=len(self.files[name]), sha256=hashlib.sha256(self.files[name]).hexdigest())
        self.pins = tmp_path / "models.json"
        self.pins.write_text(json.dumps(pins), encoding="utf-8")
        # Under a name of its own, as a store path's: it is uploaded as beat_this-LICENSE.txt whatever its path.
        self.licence = tmp_path / "0123abcd-licence"
        self.licence_text = b"MIT License\n\nCopyright (c) 2024 a stand-in\n"
        self.licence.write_bytes(self.licence_text)

    def run(self, **env: str) -> subprocess.CompletedProcess:
        full = {**os.environ, "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}", "REPO": "o/r",
                "PINS": str(self.pins), "BEAT_THIS_LICENSE": str(self.licence), **env}
        full.pop("GH_TOKEN", None)
        return subprocess.run(["bash", str(SCRIPT), str(self.dir)], env=full, capture_output=True, text=True,
                              timeout=120)

    def uploads(self) -> list[str]:
        return [c["argv"][-1] for c in self.gh.calls() if c["argv"][:2] == ["release", "upload"]]


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_the_pins_name_the_two_assets_the_phone_fetches():
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    assert [pins["beats"][k]["asset"] for k in ("fp32", "fp16")] == [FP32, FP16]
    assert pins["release"] == "models"


def test_a_first_publish_makes_the_release_a_prerelease_and_uploads_each_graph_once(rig):
    done = rig.run()
    assert done.returncode == 0, done.stderr
    rig.gh.load()
    assert rig.gh.state["release"]["tag"] == "models" and rig.gh.state["release"]["prerelease"]
    assert rig.gh.names() == [LICENCE, FP16, FP32]
    assert [Path(p).name for p in rig.uploads()] == [FP32, FP16, LICENCE]
    assert rig.gh.content(FP16) == rig.files[FP16]
    assert rig.gh.content(LICENCE) == rig.licence_text
    assert done.stdout.splitlines() == [
        "publish-models: reading the release models of o/r...",
        "publish-models: creating the release models, a prerelease, so that it is never the repository's Latest...",
        f"publish-models: uploading {FP32} (14 bytes) to o/r, release models...",
        f"publish-models: {FP32} uploaded and checked",
        f"publish-models: uploading {FP16} (14 bytes) to o/r, release models...",
        f"publish-models: {FP16} uploaded and checked",
        f"publish-models: uploading {LICENCE} ({len(rig.licence_text)} bytes) to o/r, release models...",
        f"publish-models: {LICENCE} uploaded and checked",
        "publish-models: published 3 files",
    ]


def test_a_release_published_by_hand_already_holding_all_three_uploads_nothing(rig):
    rig.gh.asset(FP32, rig.files[FP32]).asset(FP16, rig.files[FP16]).asset(LICENCE, rig.licence_text)
    done = rig.run()
    assert done.returncode == 0, done.stderr
    assert rig.uploads() == []
    assert not [c for c in rig.gh.calls() if "DELETE" in c["argv"]]
    for name in (FP32, FP16, LICENCE):
        assert f"publish-models: {name} is already published" in done.stdout.splitlines()
    assert rig.gh.names() == [LICENCE, FP16, FP32]


def test_a_release_with_the_graphs_and_no_licence_gets_the_licence_alone(rig):
    rig.gh.asset(FP32, rig.files[FP32]).asset(FP16, rig.files[FP16])
    done = rig.run()
    assert done.returncode == 0, done.stderr
    assert [Path(p).name for p in rig.uploads()] == [LICENCE]
    assert rig.gh.content(LICENCE) == rig.licence_text


def test_another_licence_of_that_name_is_never_replaced(rig):
    rig.gh.asset(FP32, rig.files[FP32]).asset(FP16, rig.files[FP16]).asset(LICENCE, b"another text")
    done = rig.run()
    assert done.returncode == 1
    assert f"a different file of that name is there: {LICENCE}" in done.stderr
    assert rig.gh.content(LICENCE) == b"another text" and rig.uploads() == []


def test_no_licence_uploads_nothing(rig):
    done = rig.run(BEAT_THIS_LICENSE=str(rig.tmp / "none"))
    assert done.returncode == 1
    assert "beat_this's licence, is missing" in done.stderr
    assert rig.uploads() == [] and rig.gh.names() == []


def test_the_licence_the_wrapper_names_is_the_apks_beat_this_licence():
    wrapper = (ROOT / "nix" / "publish-models.nix").read_text(encoding="utf-8")
    assert 'BEAT_THIS_LICENSE = "${../android/ml/licenses/beat_this-LICENSE.txt}"' in wrapper
    assert APK_LICENCE.read_text(encoding="utf-8").startswith("MIT License")


def test_a_release_that_isnt_a_prerelease_is_made_one(rig):
    rig.gh.release(prerelease=False)
    done = rig.run()
    assert done.returncode == 0, done.stderr
    rig.gh.load()
    assert rig.gh.state["release"]["prerelease"]


def test_a_folder_that_isnt_the_pinned_build_uploads_nothing(rig):
    (rig.dir / FP16).write_bytes(b"another graph!")
    done = rig.run()
    assert done.returncode == 1
    assert f"{FP16} isn't the pinned file" in done.stderr
    assert rig.uploads() == [] and rig.gh.names() == []


def test_another_file_of_the_same_name_is_never_replaced(rig):
    rig.gh.asset(FP32, b"someone else's")
    done = rig.run()
    assert done.returncode == 1
    assert f"a different file of that name is there: {FP32}" in done.stderr
    assert rig.gh.content(FP32) == b"someone else's"
    assert rig.uploads() == []


def test_an_asset_listed_with_no_digest_is_uploaded_again(rig):
    rig.gh.asset(FP32, rig.files[FP32], no_digest=True).asset(FP16, rig.files[FP16]).asset(LICENCE, rig.licence_text)
    done = rig.run()
    assert done.returncode == 0, done.stderr
    assert [Path(p).name for p in rig.uploads()] == [FP32]
    rig.gh.load()
    assert all(a["digest"] for a in rig.gh.state["assets"])


def test_a_half_upload_is_deleted_first(rig):
    rig.gh.asset(FP16, b"half", state="starter")
    done = rig.run()
    assert done.returncode == 0, done.stderr
    assert rig.gh.names() == [LICENCE, FP16, FP32]
    assert rig.gh.content(FP16) == rig.files[FP16]


def test_an_upload_github_holds_otherwise_is_deleted_and_fails(rig):
    rig.gh.load()
    rig.gh.state["corrupt_upload"] = True
    rig.gh.save()
    done = rig.run()
    assert done.returncode == 1
    assert f"GitHub holds {FP32} with another size or digest than the pins'" in done.stderr
    assert rig.gh.names() == []


def test_another_repository_or_release_is_never_asked(rig):
    done = rig.run(REPO="someone/else")
    assert done.returncode == 1
    assert rig.gh.names() == [] and rig.uploads() == []


def test_nothing_but_the_two_graphs_and_the_licence_is_touched(rig):
    rig.gh.asset("notes.txt", b"the owner's")
    done = rig.run()
    assert done.returncode == 0, done.stderr
    assert rig.gh.names() == [LICENCE, FP16, FP32, "notes.txt"]
    assert "btc-graph.onnx" not in " ".join(rig.uploads())
