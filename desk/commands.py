"""Treasurer commands and the human gate.

Approval is allowed only when the Switch sender is one of TREASURER_USERNAMES
and that name is a human participant. An agent cannot pass by using the same
display name.
"""

from __future__ import annotations

import re

from desk.models import Command, money

_CLAIM = r"(C-\d+)"
_APPROVE = re.compile(rf"\bapprove\s+{_CLAIM}\b", re.IGNORECASE)
_REJECT = re.compile(rf"\breject\s+{_CLAIM}\b", re.IGNORECASE)
_ADJUST = re.compile(
    r"\badjust\s+(C-\d+)\s+amount\s*=\s*\$?\s*"
    r"(\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.(\d{1,2}))?",
    re.IGNORECASE,
)
_WHY = re.compile(rf"\bwhy\s+{_CLAIM}\b", re.IGNORECASE)
_SUMMARY = re.compile(r"\bsummary\b", re.IGNORECASE)
_LEDGER = re.compile(r"\bledger\b", re.IGNORECASE)
_APPLY = re.compile(r"\bapply-policy\b", re.IGNORECASE)
_OVERRIDE = re.compile(
    r"""override\s*=\s*(?:"([^"]+)"|'([^']+)'|(\S+))""",
    re.IGNORECASE,
)
_FENCE = re.compile(r"```(?:yaml|yml)?\n(.*?)```", re.DOTALL | re.IGNORECASE)
_VERDICT_LINE = re.compile(r"\bC-\d+\s+(PASS|FLAG|BLOCK)\b")


def is_verdict_handoff(text: str) -> bool:
    """An auditor verdict quotes the approve command. That quote is not an order."""
    return _VERDICT_LINE.search(text or "") is not None


def strip_mention(body: str, name: str) -> str:
    return re.sub(rf"@{re.escape(name)}\b", "", body or "", flags=re.IGNORECASE).strip()


def parse_command(text: str) -> Command:
    override_match = _OVERRIDE.search(text)
    override = None
    if override_match:
        override = next(group for group in override_match.groups() if group)

    if _APPLY.search(text):
        fenced = _FENCE.search(text)
        return Command(kind="apply-policy", override=override, policy_yaml=fenced.group(1) if fenced else text)

    why = _WHY.search(text)
    if why:
        return Command(kind="why", claim_id=why.group(1).upper(), override=override)

    adjust = _ADJUST.search(text)
    if adjust:
        frac = adjust.group(3)
        amount = money(f"{adjust.group(2).replace(',', '')}.{frac}" if frac else adjust.group(2))
        return Command(kind="adjust", claim_id=adjust.group(1).upper(), amount=amount, override=override)

    approve = _APPROVE.search(text)
    if approve:
        return Command(kind="approve", claim_id=approve.group(1).upper(), override=override)

    reject = _REJECT.search(text)
    if reject:
        remainder = text[reject.end() :].strip(" .:-")
        if override_match:
            remainder = _OVERRIDE.sub("", remainder).strip(" .:-")
        return Command(
            kind="reject",
            claim_id=reject.group(1).upper(),
            reason=remainder or None,
            override=override,
        )

    if _SUMMARY.search(text):
        return Command(kind="summary")
    if _LEDGER.search(text):
        return Command(kind="ledger")
    return Command(kind="unknown")


def is_treasurer(
    sender_name: str | None,
    sender_id: str | None,
    participants: list[dict],
    allowed: set[str],
) -> bool:
    name = (sender_name or "").strip().lower()
    if not name or name not in {item.lower() for item in allowed}:
        return False
    sender = sender_id or ""
    if "@switch-agent-" in sender or ":agent" in sender:
        return False
    for participant in participants:
        if str(participant.get("name", "")).lower() != name:
            continue
        return participant.get("type") == "user"
    return False
