"""Deterministic claim reading.

Amounts and dates come from this module only. A model is never asked to invent
them, and a live model is not allowed to replace a value this module found.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from desk.models import Extraction, money

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTH = re.compile(
    r"\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r")\s+(\d{1,2})(?:,?\s*(\d{4}))?\b",
    re.IGNORECASE,
)
_RELATIVE = re.compile(r"\b(today|yesterday)\b", re.IGNORECASE)

_DOLLAR = re.compile(
    r"(?P<sym>[$€£])\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d{1,2}))?"
)
_CODE_FIRST = re.compile(
    r"\b(?P<word>USD|EUR|GBP)\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d{1,2}))?\b",
    re.IGNORECASE,
)
_WORD_AFTER = re.compile(
    r"\b(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d{1,2}))?\s*"
    r"(?P<word>USD|EUR|GBP|dollars|euros|pounds)\b",
    re.IGNORECASE,
)
_PLAIN_CENTS = re.compile(r"\b(?P<num>\d{1,3}(?:,\d{3})+|\d+)\.(?P<frac>\d{2})\b")
_CLAIM_INT = re.compile(r"\b(?P<num>\d{1,6})\b")

_EVENT = re.compile(r"\bevent\s*[:=]\s*([a-z0-9][a-z0-9-]*)", re.IGNORECASE)
_MEETUP = re.compile(r"\b([A-Za-z]+)['’]s\s+meetup\b")
_RECEIPT = re.compile(r"\breceipt\s*[:\-]?\s*([^\n]{1,80})", re.IGNORECASE)

# Longer phrases first so "room rental" wins over a stray keyword.
_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("alcohol", ("alcohol", "cocktail", "whiskey", "vodka", "soju", "beer", "wine")),
    ("venue", ("room rental", "venue", "booking fee")),
    ("travel", ("uber", "lyft", "taxi", "transit", "metro", "train")),
    ("supplies", ("markers", "paper", "supplies", "plates", "napkins", "cups")),
    ("food", ("pizza", "snacks", "coffee", "lunch", "dinner", "catering", "bagels", "bagel", "food")),
]

_CURRENCY = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "usd": "USD",
    "eur": "EUR",
    "gbp": "GBP",
    "dollars": "USD",
    "euros": "EUR",
    "pounds": "GBP",
}


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _not_future(found: date, today: date) -> date:
    if found > today:
        try:
            return found.replace(year=found.year - 1)
        except ValueError:
            return found
    return found


def _mask_span(text: str, start: int, end: int) -> str:
    return text[:start] + (" " * (end - start)) + text[end:]


def find_date(text: str, today: date) -> tuple[str, date | None]:
    """Return the text with the first date blanked out, plus that date."""
    match = _ISO.search(text)
    if match:
        found = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found:
            return _mask_span(text, match.start(), match.end()), found
    match = _SLASH.search(text)
    if match:
        found = _safe_date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        if found:
            return _mask_span(text, match.start(), match.end()), found
    match = _MONTH.search(text)
    if match:
        month = _MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        found = _safe_date(year, month, day)
        if found:
            if match.group(3) is None:
                found = _not_future(found, today)
            return _mask_span(text, match.start(), match.end()), found
    match = _RELATIVE.search(text)
    if match:
        word = match.group(1).lower()
        found = today if word == "today" else today - timedelta(days=1)
        return _mask_span(text, match.start(), match.end()), found
    return text, None


def _number(num: str, frac: str | None) -> str:
    digits = num.replace(",", "")
    if frac is None:
        return money(digits)
    padded = (frac + "00")[:2]
    return money(f"{digits}.{padded}")


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(not (end <= other_start or start >= other_end) for other_start, other_end in spans)


def _collect_amounts(masked: str, claim_syntax: bool) -> list[tuple[str, str]]:
    found: list[tuple[int, int, str, str]] = []
    patterns = (
        (_DOLLAR, "sym"),
        (_CODE_FIRST, "word"),
        (_WORD_AFTER, "word"),
        (_PLAIN_CENTS, None),
    )
    for pattern, currency_group in patterns:
        for match in pattern.finditer(masked):
            span = (match.start(), match.end())
            if _overlaps(span, [(item[0], item[1]) for item in found]):
                continue
            currency = "USD"
            if currency_group:
                currency = _CURRENCY[match.group(currency_group).lower()]
            found.append((span[0], span[1], _number(match.group("num"), match.group("frac")), currency))
    if claim_syntax and not found:
        for match in _CLAIM_INT.finditer(masked):
            span = (match.start(), match.end())
            if _overlaps(span, [(item[0], item[1]) for item in found]):
                continue
            found.append((span[0], span[1], _number(match.group("num"), None), "USD"))
    found.sort(key=lambda item: item[0])
    return [(amount, currency) for _, _, amount, currency in found]


def _category(text: str, categories: list[tuple[str, tuple[str, ...]]] | None = None) -> str:
    lowered = text.lower()
    for name, words in categories or _CATEGORIES:
        if any(word in lowered for word in words):
            return name
    return "other"


def _event(text: str) -> str:
    explicit = _EVENT.search(text)
    if explicit:
        return explicit.group(1).lower()
    meetup = _MEETUP.search(text)
    if meetup:
        return f"{meetup.group(1).lower()}-meetup"
    return "unspecified"


def _receipt(text: str) -> str:
    match = _RECEIPT.search(text)
    if not match:
        return ""
    snippet = match.group(1).strip(" .")
    return snippet[:80]


def extract(
    text: str,
    today: date | None = None,
    categories: list[tuple[str, tuple[str, ...]]] | None = None,
) -> Extraction:
    today = today or date.today()
    raw = " ".join(text.split())
    claim_syntax = bool(re.match(r"claim\b", raw, re.IGNORECASE))
    masked, spent = find_date(raw, today)
    amounts = _collect_amounts(masked, claim_syntax)
    ambiguous = len(amounts) > 1
    amount = None if ambiguous or not amounts else amounts[0][0]
    currency = "USD" if not amounts else amounts[0][1]
    return Extraction(
        amount=amount,
        currency=currency,
        spent_on=spent.isoformat() if spent else None,
        category=_category(raw, categories),
        event=_event(raw),
        receipt_ref=_receipt(raw),
        ambiguous=ambiguous,
        raw=raw,
    )
