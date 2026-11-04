"""Club policy loaded from YAML, applied only by this module.

A language model may phrase the explanation. It does not choose PASS, FLAG,
or BLOCK, and it cannot drop a reason this function recorded.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from desk.models import Claim, Verdict, as_decimal

_REQUIRED = (
    "max_claim_amount",
    "preapproval_threshold",
    "receipt_max_age_days",
    "banned_categories",
    "default_event_budget",
)


def packaged_policy_text(path: str | None = None) -> str:
    policy_path = Path(path or Path(__file__).resolve().parent.parent / "policy" / "club-policy.yaml")
    return policy_path.read_text()


def load_policy(text: str) -> dict:
    """Accept a bare YAML document or a markdown file with one yaml fence."""
    fenced = _yaml_fence(text)
    data = yaml.safe_load(fenced)
    if not isinstance(data, dict):
        raise ValueError("policy must be a YAML mapping")
    missing = [key for key in _REQUIRED if key not in data]
    if missing:
        raise ValueError(f"policy is missing {', '.join(missing)}")
    data["max_claim_amount"] = str(data["max_claim_amount"])
    data["preapproval_threshold"] = str(data["preapproval_threshold"])
    data["default_event_budget"] = str(data["default_event_budget"])
    data["receipt_max_age_days"] = int(data["receipt_max_age_days"])
    data["banned_categories"] = [str(item).lower() for item in data.get("banned_categories") or []]
    budgets = {}
    for name, amount in (data.get("event_budgets") or {}).items():
        budgets[str(name)] = str(amount)
    data["event_budgets"] = budgets
    categories = []
    for name, words in (data.get("category_keywords") or {}).items():
        categories.append((str(name).lower(), tuple(str(word).lower() for word in words)))
    data["categories"] = categories
    return data


def _yaml_fence(text: str) -> str:
    if "```" not in text:
        return text
    lines = text.splitlines()
    collected: list[str] = []
    capturing = False
    for line in lines:
        if line.strip().startswith("```"):
            if capturing:
                break
            capturing = True
            continue
        if capturing:
            collected.append(line)
    return "\n".join(collected) if collected else text


def render_policy_document(yaml_text: str) -> str:
    body = yaml_text.strip() + "\n"
    return (
        "# Club policy\n\n"
        "The auditor re-reads this document on every claim. "
        "The fenced YAML is what the rules engine loads.\n\n"
        "```yaml\n"
        f"{body}"
        "```\n"
    )


def _event_budget(policy: dict, event: str) -> Decimal:
    raw = policy["event_budgets"].get(event, policy["default_event_budget"])
    return as_decimal(str(raw))


def _latest(entries: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for entry in entries:
        latest[entry["claim_id"]] = entry
    return latest


def approved_total(entries: list[dict], event: str, *, except_claim: str | None = None) -> Decimal:
    total = Decimal("0.00")
    for entry in _latest(entries).values():
        if except_claim and entry["claim_id"] == except_claim:
            continue
        if entry.get("decision") == "approved" and entry.get("event") == event:
            total += as_decimal(entry["amount"])
    return total


def is_duplicate(
    claim: Claim,
    others: list[Claim],
    entries: list[dict],
) -> bool:
    latest = _latest(entries)
    for other in others:
        if other.id == claim.id:
            continue
        if other.payer.lower() != claim.payer.lower():
            continue
        if other.amount != claim.amount or other.spent_on != claim.spent_on:
            continue
        if other.event != claim.event:
            continue
        decision = (latest.get(other.id) or {}).get("decision")
        if decision == "rejected":
            continue
        return True
    return False


def evaluate(
    claim: Claim,
    policy: dict,
    *,
    others: list[Claim],
    entries: list[dict],
    today: date | None = None,
) -> Verdict:
    today = today or date.today()
    reasons: list[str] = []
    blocked = False
    flagged = False
    amount = as_decimal(claim.amount)

    if amount <= 0:
        blocked = True
        reasons.append("amount must be greater than zero")

    if claim.category.lower() in set(policy["banned_categories"]):
        blocked = True
        reasons.append(f"category {claim.category} is not reimbursed")

    spent = claim.spent_on_date()
    if spent is None:
        flagged = True
        reasons.append("no receipt date, so the 14-day rule cannot be checked")
    elif spent > today:
        flagged = True
        reasons.append(f"receipt date {spent.isoformat()} is in the future")
    else:
        age = (today - spent).days
        if age > int(policy["receipt_max_age_days"]):
            blocked = True
            reasons.append(
                f"receipt is {age} days old, past the {policy['receipt_max_age_days']}-day limit"
            )

    cap = as_decimal(policy["max_claim_amount"])
    ceiling = as_decimal(policy["preapproval_threshold"])
    if amount > ceiling:
        blocked = True
        reasons.append(
            f"amount {claim.amount} exceeds the {policy['preapproval_threshold']} pre-approval line"
        )
    elif amount > cap:
        flagged = True
        reasons.append(f"amount {claim.amount} exceeds the {policy['max_claim_amount']} per-claim cap")

    if is_duplicate(claim, others, entries):
        blocked = True
        reasons.append("duplicate of an open or approved claim with the same payer, amount, date, and event")

    spent_so_far = approved_total(entries, claim.event, except_claim=claim.id)
    budget = _event_budget(policy, claim.event)
    if spent_so_far + amount > budget:
        flagged = True
        reasons.append(
            f"event {claim.event} would spend {spent_so_far + amount} of its {budget} budget"
        )

    if blocked:
        status = "BLOCK"
    elif flagged:
        status = "FLAG"
    else:
        status = "PASS"
    return Verdict(status=status, reasons=reasons, explanation=templated_explanation(claim, status, reasons, policy))


def templated_explanation(claim: Claim, status: str, reasons: list[str], policy: dict) -> str:
    if status == "PASS":
        detail = "It is inside the cap, the category is allowed, and the receipt date is in range."
    else:
        detail = " ".join(reasons) if reasons else "It needs the treasurer."
        if not detail.endswith("."):
            detail += "."
    follow = {
        "PASS": "The treasurer can `@bookkeeper approve " + claim.id + "`.",
        "FLAG": (
            "The treasurer can `@bookkeeper adjust "
            + claim.id
            + " amount=…` or approve it with override=\"reason\"."
        ),
        "BLOCK": (
            "The treasurer can `@bookkeeper reject "
            + claim.id
            + "`, or approve only with override=\"reason\"."
        ),
    }[status]
    return (
        f"{claim.id} is {status} for {claim.payer}: {claim.currency} {claim.amount} "
        f"on {claim.event} ({claim.category}). {detail} {follow} "
        f"Cap {policy['max_claim_amount']}, pre-approval {policy['preapproval_threshold']}."
    )


def approval_allowed(verdict: Verdict, override: str | None) -> tuple[bool, str]:
    if verdict.status == "PASS":
        return True, ""
    if override and override.strip():
        return True, ""
    return (
        False,
        f"Refused: {verdict.status} needs `override=\"reason\"` before it can be approved. "
        + ("; ".join(verdict.reasons) if verdict.reasons else ""),
    )
