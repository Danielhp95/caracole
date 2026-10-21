"""The Nix files set only environment variables caracole reads, and list the dependencies
pyproject.toml lists: every third-party module the source imports."""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NIX_FILES = [ROOT / "flake.nix", *sorted((ROOT / "nix").glob("*.nix"))]
SRC = ROOT / "src" / "caracole"

# The package's own build runs these tests on a source tree without flake.nix or nix/.
pytestmark = pytest.mark.skipif(
    not (ROOT / "nix" / "package.nix").is_file(), reason="the Nix files are not in this tree"
)


def test_the_nix_files_set_only_variables_caracole_reads():
    # An option whose variable nothing reads (btcConfig, for CARACOLE_BTC_CONFIG) is a dead end.
    named = {
        name
        for path in NIX_FILES
        for name in re.findall(r"\bCARACOLE_[A-Z0-9_]+\b", path.read_text(encoding="utf-8"))
    }
    source = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted((ROOT / "src" / "caracole").rglob("*.py"))
    )
    assert "CARACOLE_CJK_FONT" in named
    assert sorted(name for name in named if f'"{name}"' not in source) == []


def _name(requirement: str) -> str:
    """A distribution's name as PEP 503 compares it: "beat_this", "Beat-This" and "beat-this" alike."""
    match = re.match(r"[A-Za-z0-9._-]+", requirement.strip())
    assert match, requirement
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _nix_list(path: Path, pattern: str) -> set[str]:
    """The attribute names of the Nix list ``pattern`` opens (its comments left out)."""
    text = "\n".join(line.split("#", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())
    match = re.search(pattern + r"\s*\[([^\]]*)\]", text)
    assert match, f"{path.name}: no list after {pattern!r}"
    return {_name(word) for word in match.group(1).split()}


def _listed() -> dict[str, dict[str, set[str]]]:
    """The runtime and auto-chords dependencies as pyproject.toml, flake.nix and nix/package.nix list them."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    flake, package = ROOT / "flake.nix", ROOT / "nix" / "package.nix"
    return {
        "pyproject.toml": {
            "runtime": {_name(r) for r in project["dependencies"]},
            "autochords": {_name(r) for r in project["optional-dependencies"]["autochords"]},
        },
        "flake.nix": {
            "runtime": _nix_list(flake, r"runtimeDeps = ps: with ps;"),
            "autochords": _nix_list(flake, r"autochordsDeps = ps: with ps;"),
        },
        "nix/package.nix": {
            "runtime": _nix_list(package, r"\bdependencies =\s*with python3Packages;"),
            "autochords": _nix_list(package, r"optional-dependencies\.autochords = with python3Packages;"),
        },
    }


def _imported(path: Path) -> set[str]:
    """The top-level modules a source file imports that are neither the standard library's nor caracole's."""
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules - set(sys.stdlib_module_names) - {"__future__", "caracole"}


def test_pyproject_the_flake_and_the_package_list_the_same_dependencies():
    # A dependency is listed three times (AGENTS.md); one missing from flake.nix leaves it out of
    # `nix develop`, one missing from package.nix out of the package.
    listed = _listed()
    assert listed["flake.nix"] == listed["pyproject.toml"]
    assert listed["nix/package.nix"] == listed["pyproject.toml"]


def test_every_module_the_source_imports_comes_from_a_listed_dependency():
    # A module that arrives with another dependency (click with typer, requests with spotipy) is
    # still listed: the package that brings it may stop bringing it, or change it under caracole.
    listed = _listed()["pyproject.toml"]
    from_distribution = packages_distributions()  # "yaml" → ["PyYAML"], for what is installed here
    missing = []
    for path in sorted(SRC.rglob("*.py")):
        allowed = set(listed["runtime"])
        if path.relative_to(SRC).parts[0] == "autochords":  # btc.py, beats.py: run with the extra installed
            allowed |= listed["autochords"]
        for module in sorted(_imported(path)):
            names = {_name(n) for n in from_distribution.get(module, [module])}
            if not names & allowed:
                missing.append(f"{path.relative_to(ROOT)}: {module}")
    assert missing == []
