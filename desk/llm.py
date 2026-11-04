"""Optional OpenAI-compatible wording.

Rules mode never calls a network. Live mode may write the one-paragraph
explanation and may suggest a category, an event, or a receipt note. Amounts
and dates are discarded here even if the model returns them: the caller keeps
the values `desk.rules` already extracted.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx

from desk.models import Extraction, Verdict

log = logging.getLogger("desk.llm")

_UNREADABLE = "I could not read that, please use `claim <amount> <what> <date>`"


def unreadable_reply() -> str:
    return _UNREADABLE


@dataclass
class LLMConfig:
    mode: str
    base_url: str
    api_key: str
    model: str
    timeout: float = 20.0
    retries: int = 2

    @classmethod
    def from_env(cls) -> LLMConfig:
        mode = os.environ.get("LLM_MODE", "rules").strip().lower() or "rules"
        if mode not in {"rules", "live"}:
            raise ValueError("LLM_MODE must be rules or live")
        return cls(
            mode=mode,
            base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            api_key=os.environ.get("LLM_API_KEY", ""),
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            timeout=float(os.environ.get("LLM_TIMEOUT", "20")),
            retries=int(os.environ.get("LLM_RETRIES", "2")),
        )

    @property
    def live(self) -> bool:
        return self.mode == "live" and bool(self.api_key)

    def label(self) -> str:
        if self.live:
            return f"live:{self.model}"
        if self.mode == "live":
            return "rules (LLM_MODE=live but no LLM_API_KEY)"
        return "rules"


class Wording:
    def __init__(self, config: LLMConfig):
        self.config = config

    async def polish_explanation(self, verdict: Verdict, claim_text: str) -> str:
        """Return an explanation. The verdict status is never taken from the model."""
        if not self.config.live:
            return verdict.explanation
        prompt = (
            "Write one short paragraph explaining this reimbursement verdict to a club treasurer. "
            "Do not change the verdict and do not invent a different amount. "
            f"Verdict: {verdict.status}. Reasons: {'; '.join(verdict.reasons) or 'none'}. "
            f"Claim text: {claim_text}. "
            "Return JSON {\"explanation\": \"...\"} only."
        )
        try:
            payload = await self._complete(prompt)
        except Exception:
            log.exception("explanation model failed; keeping the templated paragraph")
            return verdict.explanation
        text = str(payload.get("explanation") or "").strip()
        if not text or verdict.status not in text and verdict.status.lower() not in text.lower():
            # Keep the template if the model dropped the verdict word.
            return verdict.explanation
        return text

    async def suggest_labels(self, extraction: Extraction) -> Extraction:
        """Fill category/event/receipt only when rules left them empty.

        Amount and spent_on on the returned extraction are always the code values.
        """
        if not self.config.live or not extraction.ok:
            return extraction
        if extraction.category != "other" and extraction.event != "unspecified" and extraction.receipt_ref:
            return extraction
        prompt = (
            "Classify this club reimbursement. Return JSON with keys "
            "category, event, receipt_ref, amount, spent_on. "
            "category is one of food, travel, supplies, venue, alcohol, other. "
            "event is a short slug or unspecified. "
            "The amount and date you return are ignored; code already extracted them. "
            f"Text: {extraction.raw}"
        )
        try:
            payload = await self._complete(prompt)
        except Exception:
            log.exception("label model failed; keeping regex labels")
            return extraction
        category = str(payload.get("category") or "").strip().lower()
        event = str(payload.get("event") or "").strip().lower().replace(" ", "-")
        receipt = str(payload.get("receipt_ref") or "").strip()
        if extraction.category == "other" and category in {"food", "travel", "supplies", "venue", "alcohol", "other"}:
            extraction.category = category
        if extraction.event == "unspecified" and event and event != "unspecified":
            extraction.event = event[:40]
        if not extraction.receipt_ref and receipt:
            extraction.receipt_ref = receipt[:80]
        if payload.get("amount") and str(payload.get("amount")) != extraction.amount:
            log.info(
                "model amount %s discarded; code amount %s stands",
                payload.get("amount"),
                extraction.amount,
            )
        return extraction

    async def _complete(self, prompt: str) -> dict:
        last_error: Exception | None = None
        attempts = self.config.retries + 1
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            for _ in range(attempts):
                try:
                    response = await client.post(
                        f"{self.config.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self.config.api_key}"},
                        json={
                            "model": self.config.model,
                            "temperature": 0,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": "You reply with one JSON object and nothing else.",
                                },
                                {"role": "user", "content": prompt},
                            ],
                        },
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    return _parse_json(content)
                except Exception as exc:
                    last_error = exc
                    log.warning("model call failed: %s", exc)
        assert last_error is not None
        raise last_error


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("model JSON was not an object")
    return data
