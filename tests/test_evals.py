"""Tests for the eval harness — runner + expectations against a fake provider.

The harness itself is network-dependent (it calls the real LLM provider in the
field) — the *deterministic* part is its expectation logic and pass/fail
reporting. Those we exercise here by feeding the runner a fake provider that
returns canned extract_orders payloads, just like the Seam 2 unit tests do.
"""

from __future__ import annotations

import io
from pathlib import Path

from sheet_compressor_mcp.evals import (
    GOLDEN_CASES,
    DEALER_REGIONS,
    GoldenCase,
    all_regions_present,
    extracted_order_count_at_least,
    every_order_has_required_fields,
    every_order_make_is_known,
    every_order_region_is_known,
    run_cases,
    total_revenue_matches_sum_of_orders,
)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
HERO_XLSX = EXAMPLES / "northstar-auto-q3-2025.xlsx"


class FakeProvider:
    """Returns the same canned response for every call."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = 0

    def extract_structured(self, *, system, user, schema, max_tokens=4096):
        self.calls += 1
        return self.response


GOOD_RESPONSE = {
    "orders": [
        {"order_id": "NS-1", "order_date": "2025-07-08", "dealership": "X",
         "region": "Midwest", "make": "Ford", "model": "F-150",
         "qty": 1, "unit_price": 100.0, "total": 100.0, "status": "delivered"},
        {"order_id": "NS-2", "order_date": "2025-08-01", "dealership": "Y",
         "region": "Southeast", "make": "Chevrolet", "model": "Tahoe",
         "qty": 1, "unit_price": 200.0, "total": 200.0, "status": "Pending"},
        {"order_id": "NS-3", "order_date": "2025-09-04", "dealership": "Z",
         "region": "West", "make": "Jeep", "model": "Wrangler",
         "qty": 1, "unit_price": 150.0, "total": 150.0, "status": "Invoiced"},
        {"order_id": "NS-4", "order_date": "2025-07-15", "dealership": "W",
         "region": "Northeast", "make": "Ram", "model": "1500",
         "qty": 1, "unit_price": 50.0, "total": 50.0, "status": "delivered"},
    ],
    "total_revenue": 500.0,
}


def test_all_regions_present_passes_when_all_four_appear():
    outcome = all_regions_present(GOOD_RESPONSE)
    assert outcome.passed
    assert "all four regions present" in outcome.name


def test_all_regions_present_fails_when_one_missing():
    partial = {"orders": GOOD_RESPONSE["orders"][:3], "total_revenue": 450.0}
    outcome = all_regions_present(partial)
    assert not outcome.passed
    assert "Northeast" in outcome.detail or "northeast" in outcome.detail


def test_every_order_region_is_known_flags_typos():
    bad = {"orders": [{**GOOD_RESPONSE["orders"][0], "region": "Pacifika"}],
           "total_revenue": 0}
    outcome = every_order_region_is_known(bad)
    assert not outcome.passed
    assert "Pacifika" in outcome.detail


def test_every_order_make_is_known_flags_unknown_make():
    bad = {"orders": [{**GOOD_RESPONSE["orders"][0], "make": "Toyota"}],
           "total_revenue": 0}
    outcome = every_order_make_is_known(bad)
    assert not outcome.passed


def test_every_order_has_required_fields_flags_missing_field():
    incomplete = dict(GOOD_RESPONSE["orders"][0])
    incomplete.pop("status")
    outcome = every_order_has_required_fields({"orders": [incomplete],
                                                "total_revenue": 0})
    assert not outcome.passed
    assert "status" in outcome.detail


def test_extracted_order_count_at_least_threshold():
    check = extracted_order_count_at_least(10)
    assert not check(GOOD_RESPONSE).passed
    assert check({"orders": [{}] * 10, "total_revenue": 0}).passed


def test_total_revenue_matches_sum_of_orders_within_rounding():
    # Declared 500.0, sum is 500.0 → pass.
    assert total_revenue_matches_sum_of_orders(GOOD_RESPONSE).passed

    drifted = {"orders": GOOD_RESPONSE["orders"], "total_revenue": 999.0}
    assert not total_revenue_matches_sum_of_orders(drifted).passed


def test_run_cases_returns_zero_when_all_pass():
    case = GoldenCase(
        name="all-pass",
        xlsx_path=HERO_XLSX,
        expectations=[all_regions_present],
    )
    buf = io.StringIO()
    fake = FakeProvider(GOOD_RESPONSE)
    rc = run_cases(cases=[case], provider=fake, out=buf)
    assert rc == 0
    assert fake.calls == len(DEALER_REGIONS)
    out = buf.getvalue()
    assert "[PASS]" in out
    assert "1/1 expectations passed" in out


def test_run_cases_returns_one_when_any_fails():
    bad_case = GoldenCase(
        name="fail-case",
        xlsx_path=HERO_XLSX,
        expectations=[extracted_order_count_at_least(9999)],
    )
    buf = io.StringIO()
    rc = run_cases(cases=[bad_case], provider=FakeProvider(GOOD_RESPONSE), out=buf)
    assert rc == 1
    out = buf.getvalue()
    assert "[FAIL]" in out
    assert "0/1 expectations passed" in out


def test_run_cases_runs_each_expectation_under_its_case_name():
    case = GoldenCase(
        name="multi-expect",
        xlsx_path=HERO_XLSX,
        expectations=[all_regions_present, every_order_make_is_known],
    )
    buf = io.StringIO()
    run_cases(cases=[case], provider=FakeProvider(GOOD_RESPONSE), out=buf)
    out = buf.getvalue()
    assert out.count("multi-expect") == 2
    assert "2/2 expectations passed" in out


def test_run_cases_calls_provider_once_per_case_not_per_expectation():
    # Important: golden cases run extract_orders ONCE per case and reuse the
    # result across expectations. extract_orders itself fans out one call per
    # region, so the bill scales with regions-per-case — NOT with the number of
    # assertions (here, 3 expectations still cost just one region-fan-out).
    case = GoldenCase(
        name="reused",
        xlsx_path=HERO_XLSX,
        expectations=[all_regions_present, all_regions_present, all_regions_present],
    )
    fake = FakeProvider(GOOD_RESPONSE)
    run_cases(cases=[case], provider=fake, out=io.StringIO())
    assert fake.calls == len(DEALER_REGIONS)


def test_golden_cases_target_the_hero_file():
    # The shipped golden suite must point at the automotive hero file (per the
    # PRD: extract_orders' demo target).
    assert GOLDEN_CASES, "shipped golden suite is empty"
    for case in GOLDEN_CASES:
        assert case.xlsx_path == HERO_XLSX, (
            f"case {case.name!r} targets {case.xlsx_path}, not the hero file"
        )
        assert case.expectations, f"case {case.name!r} has no expectations"
