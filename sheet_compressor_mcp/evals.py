"""Eval harness — golden cases over the automotive hero file, run through the
real LLM provider so model behavior is measurable and regression-testable.

The unit suite (``tests/``) exercises ``extract_orders`` at Seam 2 with a fake
provider — deterministic, no network. This harness is the opposite half: it
fires ``extract_orders`` against the configured Bedrock/Anthropic adapter and
checks the live model output against expectations that encode what's actually
true of the source sheet (regions present, known make set, internal totals
consistent). Run on demand:

    python -m sheet_compressor_mcp.evals

The harness is intentionally framework-free — a list of cases, a list of
expectation callables, a runner that prints PASS/FAIL plus a summary count.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from .extract import extract_orders
from .llm import LLMProvider, build_provider_from_env


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
HERO_XLSX = EXAMPLES_DIR / "northstar-auto-q3-2025.xlsx"

# The four facts about the hero sheet we can assert without recomputing the
# generator's seeded random sequence: it stacks per-region / per-month blocks
# over the four regions below, using makes from the fixed LINEUP and statuses
# from the fixed STATUSES list. These mirror examples/build_hero_file.py.
KNOWN_REGIONS = frozenset({"Midwest", "Southeast", "West", "Northeast"})
KNOWN_MAKES = frozenset({"Ford", "Chevrolet", "Jeep", "Ram", "GMC", "Cadillac"})
REQUIRED_ORDER_FIELDS = frozenset({
    "order_id", "order_date", "dealership", "region", "make",
    "model", "qty", "unit_price", "total", "status",
})


@dataclass
class Outcome:
    """The result of a single expectation against an extract_orders payload."""

    name: str
    passed: bool
    detail: str


Expectation = Callable[[dict], Outcome]


@dataclass
class GoldenCase:
    """One sheet + the expectations its extraction result must satisfy."""

    name: str
    xlsx_path: Path
    expectations: list[Expectation]


# ---- Expectations ---------------------------------------------------------

def all_regions_present(result: dict) -> Outcome:
    """All four known regions appear among the extracted orders' region field."""
    seen = {(o.get("region") or "") for o in result.get("orders", [])}
    missing = KNOWN_REGIONS - seen
    if missing:
        return Outcome(
            "all four regions present",
            False,
            f"missing {sorted(missing)} (saw {sorted(seen)})",
        )
    return Outcome("all four regions present", True, f"saw {sorted(seen & KNOWN_REGIONS)}")


def every_order_region_is_known(result: dict) -> Outcome:
    """No extracted order names a region outside the four known regions."""
    bad = sorted({(o.get("region") or "") for o in result.get("orders", [])} - KNOWN_REGIONS)
    if bad:
        return Outcome(
            "every order's region is one of the known four",
            False,
            f"unknown regions: {bad}",
        )
    return Outcome("every order's region is one of the known four", True, "all known")


def every_order_make_is_known(result: dict) -> Outcome:
    """No extracted order names a make outside the source sheet's lineup."""
    bad = sorted({(o.get("make") or "") for o in result.get("orders", [])} - KNOWN_MAKES)
    if bad:
        return Outcome(
            "every order's make is one of the lineup makes",
            False,
            f"unknown makes: {bad}",
        )
    return Outcome("every order's make is one of the lineup makes", True, "all known")


def every_order_has_required_fields(result: dict) -> Outcome:
    """Each extracted order has every schema-required field populated (non-None)."""
    orders = result.get("orders", [])
    if not orders:
        return Outcome("every order has all required fields", False, "no orders")
    for i, order in enumerate(orders):
        missing = [f for f in REQUIRED_ORDER_FIELDS if order.get(f) is None]
        if missing:
            return Outcome(
                "every order has all required fields",
                False,
                f"order[{i}] missing {sorted(missing)}",
            )
    return Outcome(
        "every order has all required fields",
        True,
        f"{len(orders)} orders, all complete",
    )


def extracted_order_count_at_least(threshold: int) -> Expectation:
    """The hero sheet holds 4 regions × 3 months × 28-40 orders ≈ 336-480; a
    floor of e.g. 100 catches a model that extracted only a single region."""
    def check(result: dict) -> Outcome:
        got = len(result.get("orders", []))
        return Outcome(
            f">={threshold} orders extracted",
            got >= threshold,
            f"got {got} orders",
        )
    return check


def total_revenue_matches_sum_of_orders(result: dict, *, tolerance: float = 1.0) -> Outcome:
    """Schema invariant: ``total_revenue`` is the sum of the orders' ``total``s.
    Catches the model summing wrong or duplicating an order in its totals."""
    orders = result.get("orders", [])
    sum_totals = sum((o.get("total") or 0) for o in orders)
    declared = result.get("total_revenue") or 0
    diff = abs(sum_totals - declared)
    return Outcome(
        "total_revenue matches sum of orders' totals",
        diff <= tolerance,
        f"sum={sum_totals:.2f}, declared={declared:.2f}, diff={diff:.2f}",
    )


# ---- Golden suite ---------------------------------------------------------

GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase(
        name="hero/coverage",
        xlsx_path=HERO_XLSX,
        expectations=[
            all_regions_present,
            extracted_order_count_at_least(100),
        ],
    ),
    GoldenCase(
        name="hero/schema-fidelity",
        xlsx_path=HERO_XLSX,
        expectations=[
            every_order_has_required_fields,
            every_order_region_is_known,
            every_order_make_is_known,
        ],
    ),
    GoldenCase(
        name="hero/totals-consistent",
        xlsx_path=HERO_XLSX,
        expectations=[
            total_revenue_matches_sum_of_orders,
        ],
    ),
]


# ---- Runner ---------------------------------------------------------------

def run_cases(
    cases: list[GoldenCase] | None = None,
    provider: LLMProvider | None = None,
    out: TextIO = sys.stdout,
) -> int:
    """Run each case once through the provider; print PASS/FAIL per expectation.

    Returns 0 if every expectation passed, 1 otherwise — suitable for use as a
    process exit code so a CI script can gate on it.
    """
    cases = cases if cases is not None else GOLDEN_CASES
    provider = provider if provider is not None else build_provider_from_env()

    total = 0
    passed = 0
    for case in cases:
        result = extract_orders(str(case.xlsx_path), provider=provider)
        for expectation in case.expectations:
            outcome = expectation(result)
            total += 1
            if outcome.passed:
                passed += 1
            mark = "PASS" if outcome.passed else "FAIL"
            print(f"[{mark}] {case.name} :: {outcome.name} — {outcome.detail}", file=out)

    print(f"\n{passed}/{total} expectations passed", file=out)
    return 0 if passed == total else 1


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI entry
    sys.exit(run_cases())
