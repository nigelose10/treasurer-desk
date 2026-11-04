"""One process, three Switch connections.

The agents hand work to each other with addressed messages. Restart safety is
the room documents, which are re-read on boot. A fresh process listens from
the head of the stream so a restart does not file the same claim twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from pathlib import Path

import httpx

from desk.agents.auditor import Auditor
from desk.agents.bookkeeper import Bookkeeper
from desk.agents.intake import Intake
from desk.documents import ensure_document
from desk.ledger import render_entries, render_records
from desk.llm import LLMConfig, Wording
from desk.policy import packaged_policy_text, render_policy_document
from desk.switch_client import (
    SwitchClient,
    SwitchError,
    clear_addressing_policy,
    register_agent,
    wait_until_healthy,
)

log = logging.getLogger("desk")

AGENTS = (
    ("intake", "Files club reimbursement claims and hands them to the auditor."),
    ("auditor", "Applies the club policy. The verdict is code, not a model."),
    ("bookkeeper", "Records the human treasurer's decision on the shared ledger."),
)


class StateDir:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def load_keys(self) -> dict:
        file = self.path / "agents.json"
        if not file.exists():
            return {}
        return json.loads(file.read_text())

    def save_keys(self, keys: dict) -> None:
        (self.path / "agents.json").write_text(json.dumps(keys, indent=2))

    def load_seen(self) -> set[str]:
        file = self.path / "seen.json"
        if not file.exists():
            return set()
        return set(json.loads(file.read_text()))

    def save_seen(self, seen: set[str]) -> None:
        (self.path / "seen.json").write_text(json.dumps(sorted(seen)))

    def mark_ready(self, room_id: str, mode: str) -> None:
        (self.path / "ready").write_text(json.dumps({"room_id": room_id, "mode": mode}))


def _env_set(name: str, default: str) -> set[str]:
    raw = os.environ.get(name, default)
    return {item.strip() for item in raw.split(",") if item.strip()}


async def ensure_keys(state: StateDir, base_url: str) -> dict:
    keys = state.load_keys()
    token = os.environ.get("AGENT_REGISTRATION_TOKEN", "")
    if not token:
        raise RuntimeError("AGENT_REGISTRATION_TOKEN is required to register the desk agents")
    overwrite = os.environ.get("DESK_OVERWRITE_AGENTS") == "1"
    for name, description in AGENTS:
        if name in keys and not overwrite:
            continue
        try:
            created = await register_agent(base_url, token, name, description, overwrite=overwrite)
        except SwitchError as exc:
            if exc.status == 409 and name in keys:
                continue
            raise RuntimeError(
                f"could not register @{name}: {exc}. "
                "If the name already exists, set DESK_OVERWRITE_AGENTS=1 once or restore state/agents.json."
            ) from exc
        keys[name] = {"id": created["id"], "api_key": created["api_key"]}
        state.save_keys(keys)
        log.info("registered @%s id=%s", name, created["id"])
    return keys


async def ensure_room(client: SwitchClient, room_name: str, users: list[str]) -> str:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            rooms = await client.op("list_rooms", {"include_archived": False})
            for room in rooms or []:
                if room.get("name") == room_name:
                    return room.get("room_id") or room["id"]
            created = await client.op(
                "create_room",
                {
                    "name": room_name,
                    "description": "Club reimbursements. Fictional demo data. No money moves.",
                    "agent_names": [name for name, _ in AGENTS],
                    "user_names": users,
                    "channel_type": "channel_public",
                    "instructions": (
                        "Treasurer Desk. @intake files a claim, @auditor applies the written policy, "
                        "and @bookkeeper records only a human treasurer's decision. "
                        "The model cannot change a verdict. No money moves."
                    ),
                },
            )
            failed = created.get("failed_attachments") or []
            if failed:
                log.info("room created; some people are not on the bridge yet: %s", failed)
            return created["id"]
        except (SwitchError, httpx.HTTPError) as exc:
            last_error = exc
            log.info("waiting for the bridge before creating the room: %s", exc)
            await asyncio.sleep(2)
    raise RuntimeError(f"could not create room {room_name}: {last_error}")


async def invite_missing(client: SwitchClient, room_id: str, users: list[str]) -> None:
    wanted_users = set(users)
    wanted_agents = {name for name, _ in AGENTS}
    for _ in range(30):
        context = await client.connect_room(room_id)
        present = {participant.get("name") for participant in context.get("participants") or []}
        for agent in sorted(wanted_agents - present):
            await client.op("invite_agent_to_room", {"room_id": room_id, "agent_name": agent})
        missing_users = sorted(wanted_users - present)
        if not missing_users:
            return
        try:
            await client.op("add_users_to_room", {"room_id": room_id, "user_names": missing_users})
        except SwitchError as exc:
            log.info("still waiting for %s: %s", missing_users, exc)
        await asyncio.sleep(2)
        context = await client.connect_room(room_id)
        present = {participant.get("name") for participant in context.get("participants") or []}
        if wanted_users <= present:
            return
    log.warning("proceeding without every human in the room; seed.py may still be creating them")


async def seed_documents(clients: dict[str, SwitchClient], room_id: str, policy_path: str, sync_policy: bool) -> None:
    empty_claims = render_records("Claims", "claims", [])
    empty_audits = render_records("Audits", "audits", [])
    empty_ledger = render_entries([])
    policy_body = render_policy_document(packaged_policy_text(policy_path))
    await ensure_document(
        clients["intake"],
        room_id,
        "claims",
        "Structured reimbursement claims",
        "Intake writes one record per claim. Other agents only read it.",
        empty_claims,
    )
    await ensure_document(
        clients["auditor"],
        room_id,
        "audits",
        "Policy verdicts",
        "The auditor appends the code verdict for each claim.",
        empty_audits,
    )
    await ensure_document(
        clients["auditor"],
        room_id,
        "club-policy",
        "Club reimbursement policy",
        "Re-read on every claim. The YAML fence is the rules engine input.",
        policy_body,
        overwrite=sync_policy,
    )
    await ensure_document(
        clients["bookkeeper"],
        room_id,
        "ledger",
        "Append-only reimbursement ledger",
        "The bookkeeper appends the treasurer's decision. Do not rewrite history.",
        empty_ledger,
    )


async def listen(
    client: SwitchClient,
    room_id: str,
    queue: asyncio.Queue,
    connected: asyncio.Event,
    stop: asyncio.Event,
) -> None:
    first = True
    while not stop.is_set():
        try:
            async for event_name, frame in client.events(room_id, replay=not first):
                first = False
                if event_name == "connection_state":
                    if frame.get("cursor"):
                        client.cursor = int(frame["cursor"])
                    await client.connect_room(room_id)
                    if not connected.is_set():
                        connected.set()
                        log.info("@%s connected to %s", client.name, room_id)
                    continue
                if event_name == "evicted":
                    log.info("@%s evicted; reopening", client.name)
                    break
                if event_name != "message":
                    continue
                payload = dict(frame.get("payload") or {})
                payload["_sequence"] = frame.get("sequence")
                await queue.put(payload)
        except Exception:
            if stop.is_set():
                break
            log.exception("@%s stream dropped; reopening", client.name)
            await asyncio.sleep(1)


async def consume(
    name: str,
    handler,
    queue: asyncio.Queue,
    seen: set[str],
    state: StateDir,
    started: asyncio.Event,
    stop: asyncio.Event,
) -> None:
    lock = asyncio.Lock()
    while not stop.is_set():
        payload = await queue.get()
        if not started.is_set():
            await started.wait()
        message_id = str(payload.get("message_id") or payload.get("_sequence") or "")
        seen_key = f"{name}:{message_id}" if message_id else ""
        async with lock:
            if seen_key and seen_key in seen:
                continue
            try:
                await handler.handle(payload)
            except Exception:
                log.exception("@%s failed on a message", name)
                try:
                    await handler.client.say(
                        "I hit an error handling that message and did not guess an amount or a verdict."
                    )
                except Exception:
                    log.exception("@%s could not post the error", name)
            if seen_key:
                seen.add(seen_key)
                state.save_seen(seen)


async def beat(client: SwitchClient, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            status = await client.beat()
            if status in {404, 409}:
                log.info("@%s heartbeat %s; the stream loop will reopen", client.name, status)
        except Exception:
            log.info("@%s heartbeat failed", client.name)
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            continue


async def run() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    base_url = os.environ.get("SWITCH_URL", "http://127.0.0.1:8000")
    room_name = os.environ.get("ROOM_NAME", "club-finance")
    users = [item.strip() for item in os.environ.get("ROOM_USERS", "user,maya,sam").split(",") if item.strip()]
    treasurers = _env_set("TREASURER_USERNAMES", "user")
    default_policy = Path(__file__).resolve().parent.parent / "policy" / "club-policy.yaml"
    policy_path = os.environ.get("POLICY_PATH", str(default_policy))
    sync_policy = os.environ.get("DESK_SYNC_POLICY", "seed").lower() == "always"
    wording = Wording(LLMConfig.from_env())
    state = StateDir(os.environ.get("STATE_DIR", ".state"))
    log.info("desk starting mode=%s switch=%s", wording.config.label(), base_url)
    await wait_until_healthy(base_url)
    keys = await ensure_keys(state, base_url)
    await clear_addressing_policy(
        base_url,
        os.environ.get("GATEWAY_ADMIN_EMAIL", "admin@switch.local"),
        os.environ["GATEWAY_ADMIN_PASSWORD"],
        [keys[name]["id"] for name, _ in AGENTS],
    )
    clients = {
        name: SwitchClient(base_url, keys[name]["api_key"], keys[name]["id"], name, str(uuid.uuid4()))
        for name, _ in AGENTS
    }
    room_id = await ensure_room(clients["intake"], room_name, users)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    queues = {name: asyncio.Queue() for name, _ in AGENTS}
    connected = {name: asyncio.Event() for name, _ in AGENTS}
    started = asyncio.Event()
    seen = state.load_seen()
    handlers = {
        "intake": Intake(clients["intake"], room_id, wording, policy_path),
        "auditor": Auditor(clients["auditor"], room_id, wording, treasurers, policy_path),
        "bookkeeper": Bookkeeper(clients["bookkeeper"], room_id, treasurers, policy_path),
    }
    tasks = []
    for name, _ in AGENTS:
        tasks.append(asyncio.create_task(listen(clients[name], room_id, queues[name], connected[name], stop)))
        tasks.append(asyncio.create_task(consume(name, handlers[name], queues[name], seen, state, started, stop)))
        tasks.append(asyncio.create_task(beat(clients[name], stop)))
    await asyncio.gather(*(event.wait() for event in connected.values()))
    await invite_missing(clients["intake"], room_id, users)
    await seed_documents(clients, room_id, policy_path, sync_policy)
    state.mark_ready(room_id, wording.config.label())
    started.set()
    log.info("desk ready room=%s mode=%s", room_id, wording.config.label())
    await stop.wait()
    for task in tasks:
        task.cancel()
    for client in clients.values():
        await client.aclose()


def main() -> None:
    asyncio.run(run())
