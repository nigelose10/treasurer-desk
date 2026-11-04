from datetime import date
from pathlib import Path

import yaml

from desk.rules import extract

TODAY = date(2026, 11, 4)
CASES = yaml.safe_load((Path(__file__).resolve().parents[1] / "fixtures" / "claims.yaml").read_text())["cases"]


def test_fixture_has_more_than_twenty_claims():
    assert len(CASES) >= 20


def test_each_fixture_case():
    for case in CASES:
        found = extract(case["text"], today=TODAY)
        assert found.amount == case.get("amount"), case["text"]
        assert found.ambiguous is case.get("ambiguous", False), case["text"]
        if "currency" in case and found.amount:
            assert found.currency == case["currency"], case["text"]
        if "category" in case:
            assert found.category == case["category"], case["text"]
        if "event" in case:
            assert found.event == case["event"], case["text"]
        if "date" in case:
            assert found.spent_on == case["date"], case["text"]
        if "receipt_contains" in case:
            assert case["receipt_contains"] in found.receipt_ref, case["text"]
