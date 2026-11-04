"""@auditor applies the policy and hands the verdict to @bookkeeper.

The verdict is the return value of `policy.evaluate`. Wording from a model is
attached afterwards and cannot add or remove a reason.
"""

from __future__ import annotations

import logging
import re

from desk.commands import is_treasurer, parse_command, strip_mention
from desk.documents import find_document, participants, read_document, update_document
from desk.ledger import parse_entries, parse_records, render_records
from desk.llm import Wording
from desk.models import Claim, Verdict
from desk.policy import evaluate, load_policy, packaged_policy_text, render_policy_document
from desk.switch_client import SwitchClient

log = logging.getLogger("desk.auditor")
_CLAIM_ID = re.compile(r"\b(C-\d+)\b", re.IGNORECASE)


class Auditor:
    def __init__(self, client: SwitchClient, room_id: str, wording: Wording, treasurers: set[str], policy_path: str):
        self.client = client
        self.room_id = room_id
        self.wording = wording
        self.treasurers = treasurers
        self.policy_path = policy_path

    async def handle(self, payload: dict) -> None:
        sender = str(payload.get("sender_name") or "")
        if sender.lower() == self.client.name:
            return
        text = strip_mention(str(payload.get("body") or ""), self.client.name)
        command = parse_command(text)
        if command.kind == "apply-policy":
            await self._apply_policy(payload, command.policy_yaml or "")
            return
        if command.kind == "why":
            await self._why(command.claim_id or "")
            return
        match = _CLAIM_ID.search(text)
        if not match:
            await self.client.say("Tell me which claim, for example `@auditor why C-001`.")
            return
        await self._audit(match.group(1).upper())

    async def _audit(self, claim_id: str) -> None:
        claim = await self._claim(claim_id)
        if claim is None:
            await self.client.say(f"I cannot find {claim_id} in the claims document.")
            return
        try:
            policy = await self._policy()
        except ValueError as exc:
            await self.client.say(f"I could not load the policy document, so I did not issue a verdict. {exc}")
            return
        entries = await self._entries()
        others = await self._other_claims(claim_id)
        verdict = evaluate(claim, policy, others=others, entries=entries)
        status, reasons = verdict.status, list(verdict.reasons)
        explanation = await self.wording.polish_explanation(verdict, claim.raw)
        verdict = Verdict(status=status, reasons=reasons, explanation=explanation)
        audits = await self._audits()
        audits.append(
            {
                "claim_id": claim.id,
                "verdict": verdict.status,
                "reasons": verdict.reasons,
                "explanation": verdict.explanation,
                "amount": claim.amount,
                "wording": self.wording.config.label(),
            }
        )
        await self._save_audits(audits)
        log.info("verdict %s %s", claim.id, verdict.status)
        await self.client.handoff(
            f"{verdict.line(claim.id)}\n{verdict.explanation}",
            ["bookkeeper"],
        )

    async def _why(self, claim_id: str) -> None:
        claim = await self._claim(claim_id)
        if claim is None:
            await self.client.say(f"I cannot find {claim_id}.")
            return
        entries = await self._entries()
        latest = None
        for entry in entries:
            if entry.get("claim_id") == claim_id:
                latest = entry
        if latest and latest.get("decision") == "approved":
            claim.amount = latest["amount"]
        policy = await self._policy()
        verdict = evaluate(claim, policy, others=await self._other_claims(claim_id), entries=entries)
        history = [item for item in await self._audits() if item.get("claim_id") == claim_id]
        recorded = history[0] if history else None
        if recorded:
            reasons = "; ".join(recorded.get("reasons") or []) or "no reasons"
            opening = f"{claim_id} recorded {recorded.get('verdict')} on {recorded.get('amount')}: {reasons}."
        else:
            opening = verdict.line(claim_id)
        decision = ""
        if latest:
            decision = (
                f" Ledger: {latest.get('decision')} {latest.get('amount')} by {latest.get('by')}."
            )
        changed = ""
        if recorded and recorded.get("verdict") != verdict.status:
            changed = (
                f" Re-checked against the room as it is now, the rules would say {verdict.status}."
                " The ledger row was not changed."
            )
        await self.client.say(f"{opening}{decision}{changed}")

    async def _apply_policy(self, payload: dict, yaml_text: str) -> None:
        people = await participants(self.client)
        if not is_treasurer(payload.get("sender_name"), payload.get("sender"), people, self.treasurers):
            sender = payload.get("sender_name")
            await self.client.say(
                f"Refused: only the treasurer can replace the policy. Sender {sender!r} is not allowed."
            )
            return
        try:
            load_policy(yaml_text)
        except ValueError as exc:
            await self.client.say(f"I did not replace the policy. {exc}")
            return
        document = await find_document(self.client, self.room_id, "club-policy")
        if document is None or document.get("created_by_agent_id") != self.client.agent_id:
            await self.client.say("I do not own the club-policy document, so I cannot replace it.")
            return
        await update_document(self.client, document["id"], render_policy_document(yaml_text))
        await self.client.say("Policy document updated. The next claim uses it. The ledger was not changed.")

    async def _claim(self, claim_id: str) -> Claim | None:
        for record in await self._claim_records():
            if record.get("id") == claim_id:
                return Claim.from_dict(record)
        return None

    async def _other_claims(self, claim_id: str) -> list[Claim]:
        return [Claim.from_dict(record) for record in await self._claim_records() if record.get("id") != claim_id]

    async def _claim_records(self) -> list[dict]:
        document = await find_document(self.client, self.room_id, "claims")
        if not document:
            return []
        return parse_records(await read_document(self.client, document["id"]), "claims")

    async def _entries(self) -> list[dict]:
        document = await find_document(self.client, self.room_id, "ledger")
        if not document:
            return []
        return parse_entries(await read_document(self.client, document["id"]))

    async def _audits(self) -> list[dict]:
        document = await find_document(self.client, self.room_id, "audits")
        if not document:
            return []
        return parse_records(await read_document(self.client, document["id"]), "audits")

    async def _save_audits(self, audits: list[dict]) -> None:
        document = await find_document(self.client, self.room_id, "audits")
        if document is None:
            raise RuntimeError("audits document is missing")
        await update_document(self.client, document["id"], render_records("Audits", "audits", audits))

    async def _policy(self) -> dict:
        document = await find_document(self.client, self.room_id, "club-policy")
        text = await read_document(self.client, document["id"]) if document else packaged_policy_text(self.policy_path)
        return load_policy(text)
