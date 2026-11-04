"""The conformance corpus's size, held to tests/conformance/budget.json (docs/superpowers/specs/2026-11-03-conformance-
corpus.md, "Budgets"): every area of ``vectors/`` (the sum of its files' sizes, in bytes) within its budget, the
vectors' total within ``vectors_total``, and the runtime data the APK ships (``data/``) within ``data_total``. An area
with no budget is refused: a lane that writes a new area names it in budget.json (the skeleton's), and a lane that
needs more says so in its report; it never raises a budget it doesn't own.
"""

import json
from pathlib import Path

from helpers.corpus import CONFORMANCE, VECTORS

BUDGET = CONFORMANCE / "budget.json"
MB = 1_000_000


def size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def budget() -> dict:
    return json.loads(BUDGET.read_text(encoding="utf-8"))


def test_every_area_of_the_vectors_is_within_its_budget():
    areas = budget()["areas"]
    over = {}
    for folder in sorted(p for p in VECTORS.iterdir() if p.is_dir()):
        assert folder.name in areas, f"vectors/{folder.name}/ has no budget in {BUDGET.name}"
        used = size(folder)
        if used > areas[folder.name]:
            over[folder.name] = f"{used / MB:.2f} MB of {areas[folder.name] / MB:.2f} MB"
    assert not over, f"over budget: {over}"


def test_the_vectors_and_the_runtime_data_are_within_their_totals():
    plan = budget()
    vectors = size(VECTORS)
    assert vectors <= plan["vectors_total"], f"vectors: {vectors / MB:.2f} MB of {plan['vectors_total'] / MB:.2f} MB"
    data = size(CONFORMANCE / "data")
    assert data <= plan["data_total"], f"data: {data / MB:.2f} MB of {plan['data_total'] / MB:.2f} MB"


def test_the_areas_budgets_fit_in_the_total():
    plan = budget()
    assert sum(plan["areas"].values()) <= plan["vectors_total"]
