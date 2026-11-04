"""Plain data the rules engine and the ledger share.

Amounts are decimal strings with two places so a document round-trip cannot
drift. Dates are ISO dates or None.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


def money(value: Decimal | str | int) -> str:
    if isinstance(value, Decimal):
        amount = value
    else:
        amount = Decimal(str(value).replace(",", "").replace("$", ""))
    quantized = amount.quantize(Decimal("0.01"))
    return format(quantized, "f")


def as_decimal(value: str) -> Decimal:
    return Decimal(value)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Extraction:
    amount: str | None
    currency: str
    spent_on: str | None
    category: str
    event: str
    receipt_ref: str
    ambiguous: bool = False
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.amount is not None and not self.ambiguous


@dataclass
class Claim:
    id: str
    payer: str
    amount: str
    currency: str
    spent_on: str | None
    category: str
    event: str
    receipt_ref: str
    raw: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        return cls(
            id=data["id"],
            payer=data["payer"],
            amount=data["amount"],
            currency=data.get("currency") or "USD",
            spent_on=data.get("spent_on"),
            category=data.get("category") or "other",
            event=data.get("event") or "unspecified",
            receipt_ref=data.get("receipt_ref") or "",
            raw=data.get("raw") or "",
            created_at=data.get("created_at") or utc_now(),
        )

    def spent_on_date(self) -> date | None:
        if not self.spent_on:
            return None
        return date.fromisoformat(self.spent_on)


@dataclass
class Verdict:
    status: str  # PASS, FLAG, BLOCK
    reasons: list[str]
    explanation: str

    def line(self, claim_id: str) -> str:
        if self.reasons:
            detail = "; ".join(self.reasons)
            return f"{claim_id} {self.status}: {detail}"
        return f"{claim_id} {self.status}"


@dataclass
class Command:
    kind: str
    claim_id: str | None = None
    amount: str | None = None
    override: str | None = None
    reason: str | None = None
    policy_yaml: str | None = None
