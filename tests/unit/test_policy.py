from datetime import date
from pathlib import Path

from desk.models import Claim
from desk.policy import approval_allowed, evaluate, load_policy, packaged_policy_text

TODAY = date(2026, 11, 4)
POLICY = load_policy(packaged_policy_text(str(Path(__file__).resolve().parents[2] / "policy" / "club-policy.yaml")))


def claim(**kwargs) -> Claim:
    data = {
        "id": "C-001",
        "payer": "maya",
        "amount": "42.30",
        "currency": "USD",
        "spent_on": "2026-11-03",
        "category": "food",
        "event": "thursday-meetup",
        "receipt_ref": "inline",
        "raw": "pizza",
    }
    data.update(kwargs)
    return Claim.from_dict(data)


def test_clean_claim_passes():
    verdict = evaluate(claim(), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "PASS"
    assert verdict.reasons == []


def test_over_cap_is_a_flag_not_a_block():
    verdict = evaluate(claim(amount="90.00"), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "FLAG"
    assert any("cap" in reason for reason in verdict.reasons)


def test_preapproval_line_blocks():
    verdict = evaluate(claim(amount="250.00"), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "BLOCK"
    assert any("pre-approval" in reason for reason in verdict.reasons)


def test_alcohol_is_blocked():
    verdict = evaluate(claim(category="alcohol", amount="15.00"), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "BLOCK"
    assert any("alcohol" in reason for reason in verdict.reasons)


def test_old_receipt_is_blocked():
    verdict = evaluate(claim(spent_on="2026-10-01"), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "BLOCK"
    assert any("days old" in reason for reason in verdict.reasons)


def test_missing_date_is_a_flag():
    verdict = evaluate(claim(spent_on=None), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "FLAG"
    assert any("receipt date" in reason for reason in verdict.reasons)


def test_duplicate_is_blocked():
    other = claim(id="C-009")
    verdict = evaluate(claim(), POLICY, others=[other], entries=[], today=TODAY)
    assert verdict.status == "BLOCK"
    assert any("duplicate" in reason for reason in verdict.reasons)


def test_rejected_duplicate_can_be_filed_again():
    other = claim(id="C-009")
    entries = [{"claim_id": "C-009", "decision": "rejected", "amount": "42.30", "event": "thursday-meetup"}]
    verdict = evaluate(claim(), POLICY, others=[other], entries=entries, today=TODAY)
    assert verdict.status == "PASS"


def test_event_budget_flags_when_the_new_claim_would_exceed_it():
    entries = [
        {
            "claim_id": "C-002",
            "decision": "approved",
            "amount": "180.00",
            "event": "thursday-meetup",
        }
    ]
    verdict = evaluate(claim(id="C-003", amount="30.00"), POLICY, others=[], entries=entries, today=TODAY)
    assert verdict.status == "FLAG"
    assert any("budget" in reason for reason in verdict.reasons)


def test_override_does_not_change_the_verdict():
    verdict = evaluate(claim(amount="90.00"), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "FLAG"
    allowed, _ = approval_allowed(verdict, "board already agreed")
    assert allowed
    still_flag = evaluate(claim(amount="90.00"), POLICY, others=[], entries=[], today=TODAY)
    assert still_flag.status == "FLAG"


def test_pass_does_not_need_an_override_and_a_flag_does():
    passed = evaluate(claim(), POLICY, others=[], entries=[], today=TODAY)
    assert approval_allowed(passed, None)[0]
    flagged = evaluate(claim(amount="90.00"), POLICY, others=[], entries=[], today=TODAY)
    assert not approval_allowed(flagged, None)[0]
    assert not approval_allowed(flagged, "  ")[0]


def test_zero_amount_is_blocked():
    verdict = evaluate(claim(amount="0.00"), POLICY, others=[], entries=[], today=TODAY)
    assert verdict.status == "BLOCK"
