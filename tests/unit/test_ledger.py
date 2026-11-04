from decimal import Decimal

from desk.ledger import append_entry, format_summary, parse_entries, render_entries
from desk.policy import approved_total


def entry(claim_id="C-001", decision="approved", amount="42.30"):
    return {
        "claim_id": claim_id,
        "payer": "maya",
        "amount": amount,
        "event": "thursday-meetup",
        "category": "food",
        "decision": decision,
        "by": "user",
        "at": "2026-11-04T15:00:00+00:00",
        "note": "",
        "override": "",
    }


def test_append_is_idempotent_for_the_same_decision():
    first, added = append_entry([], entry())
    assert added
    second, added_again = append_entry(first, entry())
    assert not added_again
    assert second == first


def test_round_trip_preserves_rows():
    rows, _ = append_entry([], entry())
    rows, _ = append_entry(rows, entry("C-002", "rejected", "15.00"))
    assert parse_entries(render_entries(rows)) == rows


def test_approved_total_uses_the_latest_row_only():
    rows = [entry("C-001", "approved", "80.00"), entry("C-001", "approved", "38.00")]
    # identical decision+amount would not append; different amounts are a correction trail
    assert approved_total(rows, "thursday-meetup") == Decimal("38.00")


def test_summary_counts_waiting_audits():
    text = format_summary(
        [entry()],
        {"event_budgets": {"thursday-meetup": "200.00"}, "default_event_budget": "150.00"},
        [{"claim_id": "C-009", "verdict": "FLAG"}, {"claim_id": "C-001", "verdict": "PASS"}],
    )
    assert "total 42.30" in text
    assert "C-009 FLAG" in text
    assert "C-001" not in text.split("waiting", 1)[1].split("Budgets", 1)[0]
    assert "No money has moved." in text
