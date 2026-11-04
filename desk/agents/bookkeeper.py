"""@bookkeeper writes the treasurer's decision onto the ledger.

Anyone may ask for the ledger or a summary. approve, reject, and adjust are
refused unless the Switch sender is a human treasurer.
"""

from __future__ import annotations

import logging
import re

from desk.commands import is_treasurer, is_verdict_handoff, parse_command, strip_mention
from desk.documents import find_document, participants, read_document, update_document
from desk.ledger import append_entry, format_summary, parse_entries, parse_records, render_entries
from desk.models import Claim, utc_now
from desk.policy import approval_allowed, evaluate, load_policy, packaged_policy_text
from desk.switch_client import SwitchClient

log = logging.getLogger("desk.bookkeeper")
_CLAIM_ID = re.compile(r"\b(C-\d+)\b", re.IGNORECASE)


class Bookkeeper:
    def __init__(self, client: SwitchClient, room_id: str, treasurers: set[str], policy_path: str):
        self.client = client
        self.room_id = room_id
        self.treasurers = treasurers
        self.policy_path = policy_path

    async def handle(self, payload: dict) -> None:
        sender = str(payload.get("sender_name") or "")
        if sender.lower() == self.client.name:
            return
        text = strip_mention(str(payload.get("body") or ""), self.client.name)
        if is_verdict_handoff(text):
            match = _CLAIM_ID.search(text)
            claim_id = match.group(1).upper() if match else "that claim"
            await self.client.say(
                f"Noted {claim_id}. Waiting for the treasurer to approve, reject, or adjust it."
            )
            return
        command = parse_command(text)
        if command.kind == "summary":
            await self.client.say(await self._summary())
            return
        if command.kind == "ledger":
            await self.client.say(await self._ledger_text())
            return
        if command.kind in {"approve", "reject", "adjust"}:
            await self._decide(payload, command)
            return
        await self.client.say(
            "I record decisions. Try `@bookkeeper approve C-001`, `reject C-001 <reason>`, "
            "`adjust C-001 amount=38.00`, `summary`, or `ledger`."
        )

    async def _decide(self, payload: dict, command) -> None:
        people = await participants(self.client)
        sender_name = str(payload.get("sender_name") or "")
        if not is_treasurer(sender_name, payload.get("sender"), people, self.treasurers):
            await self.client.say(
                f"Refused: only the treasurer can {command.kind} {command.claim_id}. "
                f"Sender {sender_name!r} is not a treasurer."
            )
            return
        claim = await self._claim(command.claim_id or "")
        if claim is None:
            await self.client.say(f"I cannot find {command.claim_id} in the claims document.")
            return
        entries = await self._entries()
        latest = None
        for entry in entries:
            if entry.get("claim_id") == claim.id:
                latest = entry
        if latest and latest.get("decision") in {"approved", "rejected"}:
            await self.client.say(
                f"{claim.id} is already {latest['decision']} on the ledger "
                f"({latest['amount']} by {latest.get('by')}). I did not add another row."
            )
            return
        working = claim
        note = ""
        if command.kind == "adjust":
            working = Claim.from_dict({**claim.to_dict(), "amount": command.amount})
            note = f"adjusted from {claim.amount} to {command.amount}"
        policy = await self._policy()
        others = await self._others(claim.id)
        verdict = evaluate(working, policy, others=others, entries=entries)
        if command.kind == "reject":
            await self._append(
                working,
                decision="rejected",
                by=sender_name,
                note=command.reason or "",
                override="",
            )
            await self.client.say(
                f"Rejected {claim.id}. Reason: {command.reason or 'none given'}. "
                "The ledger has the row. No money has moved."
            )
            return
        allowed, refusal = approval_allowed(verdict, command.override)
        if not allowed:
            await self.client.say(f"{verdict.line(claim.id)}\n{refusal}")
            return
        await self._append(
            working,
            decision="approved",
            by=sender_name,
            note=note,
            override=command.override or "",
        )
        log.info("approved %s amount=%s by=%s", claim.id, working.amount, sender_name)
        await self.client.say(
            f"Approved {claim.id} for {working.amount} {working.currency} "
            f"({working.category}, {working.event}). Rules verdict on the booked amount: {verdict.status}. "
            f"E-transfer, for the treasurer to send by hand: pay {working.payer} "
            f"{working.amount} {working.currency} for {claim.id}. "
            f"Decided by {sender_name} at {utc_now()}. This desk did not move money."
        )

    async def _append(self, claim: Claim, *, decision: str, by: str, note: str, override: str) -> None:
        entries = await self._entries()
        entry = {
            "claim_id": claim.id,
            "payer": claim.payer,
            "amount": claim.amount,
            "event": claim.event,
            "category": claim.category,
            "decision": decision,
            "by": by,
            "at": utc_now(),
            "note": note,
            "override": override,
        }
        updated, _added = append_entry(entries, entry)
        document = await find_document(self.client, self.room_id, "ledger")
        if document is None:
            raise RuntimeError("ledger document is missing")
        await update_document(self.client, document["id"], render_entries(updated))

    async def _summary(self) -> str:
        return format_summary(await self._entries(), await self._policy(), await self._audits())

    async def _ledger_text(self) -> str:
        entries = await self._entries()
        if not entries:
            return "The ledger is empty. No money has moved."
        lines = ["Ledger (authoritative copy is the room document):"]
        for entry in entries:
            lines.append(
                f"- {entry['claim_id']} {entry['decision']} {entry['amount']} {entry['event']} "
                f"by {entry.get('by')} at {entry.get('at')} {entry.get('note') or ''}".rstrip()
            )
        lines.append("No money has moved.")
        return "\n".join(lines)

    async def _claim(self, claim_id: str) -> Claim | None:
        for record in await self._claim_records():
            if record.get("id") == claim_id:
                return Claim.from_dict(record)
        return None

    async def _others(self, claim_id: str) -> list[Claim]:
        return [Claim.from_dict(record) for record in await self._claim_records() if record.get("id") != claim_id]

    async def _claim_records(self) -> list[dict]:
        return await self._records("claims", "claims")

    async def _audits(self) -> list[dict]:
        return await self._records("audits", "audits")

    async def _records(self, name: str, key: str) -> list[dict]:
        document = await find_document(self.client, self.room_id, name)
        if not document:
            return []
        return parse_records(await read_document(self.client, document["id"]), key)

    async def _entries(self) -> list[dict]:
        document = await find_document(self.client, self.room_id, "ledger")
        if not document:
            return []
        return parse_entries(await read_document(self.client, document["id"]))

    async def _policy(self) -> dict:
        document = await find_document(self.client, self.room_id, "club-policy")
        text = (
            await read_document(self.client, document["id"])
            if document
            else packaged_policy_text(self.policy_path)
        )
        return load_policy(text)
