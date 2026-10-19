"""The Nix files set only environment variables tabarr reads."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NIX_FILES = [ROOT / "flake.nix", *sorted((ROOT / "nix").glob("*.nix"))]

# The package's own build runs these tests on a source tree without flake.nix or nix/.
pytestmark = pytest.mark.skipif(
    not (ROOT / "nix" / "package.nix").is_file(), reason="the Nix files are not in this tree"
)


def test_the_nix_files_set_only_variables_tabarr_reads():
    # An option whose variable nothing reads (btcConfig, for TABARR_BTC_CONFIG) is a dead end.
    named = {
        name
        for path in NIX_FILES
        for name in re.findall(r"\bTABARR_[A-Z0-9_]+\b", path.read_text(encoding="utf-8"))
    }
    source = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted((ROOT / "src" / "tabarr").rglob("*.py"))
    )
    assert "TABARR_CJK_FONT" in named
    assert sorted(name for name in named if f'"{name}"' not in source) == []
