"""Switch agent protocol client: SSE down, HTTP up.

Speaks the 0.31.0 bridge directly. Registration, heartbeats, room operations,
and addressed messages are separate from claim logic so the rules can be tested
with plain strings.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

log = logging.getLogger("desk.switch")


class SwitchError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"switch {status}: {body}")
        self.status = status
        self.body = body


class SwitchClient:
    def __init__(self, base_url: str, api_key: str, agent_id: str, name: str, connection_id: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id
        self.name = name
        self.connection_id = connection_id
        self.room_id: str | None = None
        self.cursor = 0
        self.stream_open = False
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # A connection id with no stream makes Switch refuse the call.
        if self.stream_open:
            headers["X-Switch-Connection-Id"] = self.connection_id
        return headers

    async def op(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        response = await self._http.post(
            f"{self.base_url}/agents/{self.agent_id}/ops/{name}",
            headers=self._headers(),
            json=arguments or {},
        )
        if response.status_code >= 400:
            raise SwitchError(response.status_code, _body(response))
        payload = response.json()
        return payload.get("result", payload)

    async def beat(self) -> int:
        response = await self._http.post(
            f"{self.base_url}/agents/{self.agent_id}/connection/beat",
            headers=self._headers(),
            json={"connection_id": self.connection_id, "cursor": self.cursor},
        )
        return response.status_code

    async def connect_room(self, room_id: str) -> dict:
        self.room_id = room_id
        result = await self.op(
            "connect_to_room",
            {"room_id": room_id, "include_general_instructions": False},
        )
        return result

    async def say(self, body: str) -> Any:
        return await self.op("post_message", {"body": body})

    async def handoff(self, body: str, targets: list[str]) -> Any:
        return await self.op("send_targeted_message", {"body": body, "target_names": targets})

    async def events(self, room_id: str, *, replay: bool) -> AsyncIterator[tuple[str, dict]]:
        """Yield (event_name, data) frames.

        A fresh process asks for `start_from=head` so a restart does not re-run
        old mentions. A reconnect inside the process sends Last-Event-ID.
        """
        self.room_id = room_id
        params = {
            "connection_id": self.connection_id,
            "scope": "all",
            "filter": "addressed",
            "rooms": room_id,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
        }
        if replay and self.cursor:
            headers["Last-Event-ID"] = str(self.cursor)
        else:
            params["start_from"] = "head"
        timeout = httpx.Timeout(30.0, read=None)
        try:
            async for frame in self._read_events(params, headers, timeout):
                yield frame
        finally:
            self.stream_open = False

    async def _read_events(self, params: dict, headers: dict, timeout: httpx.Timeout):
        async with self._http.stream(
            "GET",
            f"{self.base_url}/agents/{self.agent_id}/events",
            params=params,
            headers=headers,
            timeout=timeout,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")
                raise SwitchError(response.status_code, body[:500])
            self.stream_open = True
            event_name = "message"
            data_lines: list[str] = []
            async for line in response.aiter_lines():
                if line == "":
                    if data_lines:
                        raw = "\n".join(data_lines)
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            payload = {"raw": raw}
                        if isinstance(payload, dict) and payload.get("sequence"):
                            self.cursor = int(payload["sequence"])
                        yield event_name, payload if isinstance(payload, dict) else {"raw": payload}
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text[:500]


async def register_agent(base_url: str, token: str, name: str, description: str, *, overwrite: bool) -> dict:
    body = {
        "name": name,
        "description": description,
        "connector_type": "custom-python",
        "integration_profile": {
            "connection_model": "always_on",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
        "overwrite": overwrite,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/agents",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise SwitchError(response.status_code, _body(response))
    return response.json()


async def clear_addressing_policy(base_url: str, email: str, password: str, agent_ids: list[str]) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        login = await client.post(
            f"{base_url.rstrip('/')}/gateway/auth/login",
            json={"email": email, "password": password},
        )
        if login.status_code >= 400:
            raise SwitchError(login.status_code, _body(login))
        for agent_id in agent_ids:
            response = await client.put(
                f"{base_url.rstrip('/')}/gateway/agents/{agent_id}/addressing-policy",
                json={"policy": None},
            )
            if response.status_code >= 400:
                raise SwitchError(response.status_code, _body(response))
            log.info("addressing policy cleared for %s", agent_id)


async def wait_until_healthy(base_url: str, attempts: int = 60) -> None:
    import asyncio

    last = "not tried"
    async with httpx.AsyncClient(timeout=5.0) as client:
        for _ in range(attempts):
            try:
                response = await client.get(f"{base_url.rstrip('/')}/health")
                if response.status_code == 200:
                    return
                last = f"{response.status_code} {response.text[:120]}"
            except httpx.HTTPError as exc:
                last = str(exc)
            await asyncio.sleep(2)
    raise RuntimeError(f"switch health check failed: {last}")
