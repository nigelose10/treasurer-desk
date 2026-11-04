"""@intake files a claim and hands it to @auditor."""

from __future__ import annotations

import logging

from desk.commands import strip_mention
from desk.documents import find_document, read_document, update_document
from desk.ledger import parse_records, render_records
from desk.llm import Wording, unreadable_reply
from desk.models import Claim, utc_now
from desk.policy import load_policy, packaged_policy_text
from desk.rules import extract
from desk.switch_client import SwitchClient

log = logging.getLogger("desk.intake")

DOC = "claims"


def format_card(claim: Claim) -> str:
    return "\n".join(
        [
            f"Claim {claim.id}",
            f"- payer: {claim.payer}",
            f"- amount: {claim.amount} {claim.currency}",
            f"- date: {claim.spent_on or 'missing'}",
            f"- category: {claim.category}",
            f"- event: {claim.event}",
            f"- receipt: {claim.receipt_ref or 'none'}",
        ]
    )


class Intake:
    def __init__(self, client: SwitchClient, room_id: str, wording: Wording, policy_path: str):
        self.client = client
        self.room_id = room_id
        self.wording = wording
        self.policy_path = policy_path

    async def handle(self, payload: dict) -> None:
        sender = str(payload.get("sender_name") or "")
        if sender.lower() == self.client.name:
            return
        text = strip_mention(str(payload.get("body") or ""), self.client.name)
        policy = await self._policy()
        categories = policy.get("categories") or None
        extraction = extract(text, categories=categories)
        amount, spent_on = extraction.amount, extraction.spent_on
        extraction = await self.wording.suggest_labels(extraction)
        extraction.amount = amount
        extraction.spent_on = spent_on
        if not extraction.ok:
            log.info("unreadable claim from %s ambiguous=%s", sender, extraction.ambiguous)
            await self.client.say(unreadable_reply())
            return
        claims = await self._claims()
        for existing in claims:
            if existing.get("payer", "").lower() == sender.lower() and existing.get("raw") == extraction.raw:
                await self.client.handoff(
                    f"Claim {existing['id']} is already on file for that message.\nPlease audit {existing['id']}.",
                    ["auditor"],
                )
                return
        number = 1 + max((int(item["id"].split("-")[1]) for item in claims if item.get("id")), default=0)
        claim = Claim(
            id=f"C-{number:03d}",
            payer=sender,
            amount=extraction.amount or "0.00",
            currency=extraction.currency,
            spent_on=extraction.spent_on,
            category=extraction.category,
            event=extraction.event,
            receipt_ref=extraction.receipt_ref,
            raw=extraction.raw,
            created_at=utc_now(),
        )
        claims.append(claim.to_dict())
        await self._save(claims)
        log.info("filed %s amount=%s mode=%s", claim.id, claim.amount, self.wording.config.label())
        card = format_card(claim)
        await self.client.handoff(
            f"{card}\nPlease audit {claim.id}. Wording: {self.wording.config.label()}.",
            ["auditor"],
        )

    async def _policy(self) -> dict:
        document = await find_document(self.client, self.room_id, "club-policy")
        text = await read_document(self.client, document["id"]) if document else packaged_policy_text(self.policy_path)
        try:
            return load_policy(text)
        except ValueError:
            log.warning("policy document unreadable; using the packaged file")
            return load_policy(packaged_policy_text(self.policy_path))

    async def _claims(self) -> list[dict]:
        document = await find_document(self.client, self.room_id, DOC)
        if not document:
            return []
        return parse_records(await read_document(self.client, document["id"]), "claims")

    async def _save(self, claims: list[dict]) -> None:
        document = await find_document(self.client, self.room_id, DOC)
        content = render_records("Claims", "claims", claims)
        if document is None:
            raise RuntimeError("claims document is missing")
        await update_document(self.client, document["id"], content)
