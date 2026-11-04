"""Append-only ledger documents.

The JSON fence is what the code reads back. The table above it is there so a
person can read the same document in the room without a tool.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from desk.models import as_decimal

_FENCE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)


def render_entries(entries: list[dict]) -> str:
    lines = [
        "# Club ledger",
        "",
        "Append-only. The JSON block is the source of truth. This desk does not move money.",
        "",
        "| claim | payer | amount | event | category | decision | by | at | note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        row = dict(entry)
        row["note"] = (entry.get("note") or "").replace("|", "/")
        lines.append(
            "| {claim_id} | {payer} | {amount} | {event} | {category} | {decision} | {by} | {at} | {note} |".format(
                **row
            )
        )
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps({"entries": entries}, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def parse_entries(text: str) -> list[dict]:
    match = _FENCE.search(text or "")
    if not match:
        return []
    data = json.loads(match.group(1))
    entries = data.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError("ledger entries must be a list")
    return entries


def append_entry(entries: list[dict], entry: dict) -> tuple[list[dict], bool]:
    """Return the new list and whether a row was added.

    A second identical decision (same claim, decision, and amount) is a no-op.
    """
    for existing in entries:
        if (
            existing.get("claim_id") == entry["claim_id"]
            and existing.get("decision") == entry["decision"]
            and existing.get("amount") == entry["amount"]
        ):
            return entries, False
    return entries + [entry], True


def latest_by_claim(entries: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for entry in entries:
        latest[entry["claim_id"]] = entry
    return latest


def render_records(title: str, key: str, records: list[dict]) -> str:
    lines = [
        f"# {title}",
        "",
        "The JSON block is the source of truth.",
        "",
        "```json",
        json.dumps({key: records}, indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def parse_records(text: str, key: str) -> list[dict]:
    match = _FENCE.search(text or "")
    if not match:
        return []
    data = json.loads(match.group(1))
    records = data.get(key) or []
    if not isinstance(records, list):
        raise ValueError(f"{key} must be a list")
    return records


def format_summary(entries: list[dict], policy: dict, audits: list[dict]) -> str:
    latest = latest_by_claim(entries)
    approved = [entry for entry in latest.values() if entry.get("decision") == "approved"]
    rejected = [entry for entry in latest.values() if entry.get("decision") == "rejected"]
    total = sum((as_decimal(entry["amount"]) for entry in approved), Decimal("0.00"))
    decided = {entry["claim_id"] for entry in latest.values()}
    waiting = []
    seen: set[str] = set()
    for audit in audits:
        claim_id = audit.get("claim_id")
        if not claim_id or claim_id in decided or claim_id in seen:
            continue
        seen.add(claim_id)
        waiting.append(f"{claim_id} {audit.get('verdict')}")
    by_event: dict[str, Decimal] = {}
    for entry in approved:
        by_event[entry["event"]] = by_event.get(entry["event"], Decimal("0.00")) + as_decimal(entry["amount"])
    budgets = dict(policy.get("event_budgets") or {})
    lines = [
        "Month summary (ledger document, not a payment):",
        f"- approved: {len(approved)} claim(s), total {total}",
        f"- rejected: {len(rejected)}",
        f"- waiting on the treasurer: {', '.join(waiting) if waiting else 'none'}",
        "Budgets:",
    ]
    names = sorted(set(budgets) | set(by_event))
    if not names:
        lines.append("- no event activity yet")
    for name in names:
        spent = by_event.get(name, Decimal("0.00"))
        budget = budgets.get(name, policy.get("default_event_budget"))
        lines.append(f"- {name}: {spent} of {budget}")
    lines.append("No money has moved.")
    return "\n".join(lines)
