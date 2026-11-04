"""Room-document helpers shared by the three agents.

Switch lets the creating agent update a document and lets every room member
read it. Each agent therefore owns the documents it writes and only reads the
others.
"""

from __future__ import annotations

import logging
from typing import Any

from desk.switch_client import SwitchClient, SwitchError

log = logging.getLogger("desk.docs")


async def list_documents(client: SwitchClient, room_id: str) -> list[dict]:
    context = await client.connect_room(room_id)
    documents = context.get("documents") or []
    return documents


async def read_document(client: SwitchClient, document_id: str) -> str:
    rows = await client.op("load_internal_documents", {"ids": [document_id]})
    if not rows:
        raise SwitchError(404, f"document {document_id} missing")
    return rows[0].get("content") or ""


async def find_document(client: SwitchClient, room_id: str, name: str) -> dict | None:
    for document in await list_documents(client, room_id):
        if document.get("name") == name:
            return document
    return None


async def ensure_document(
    client: SwitchClient,
    room_id: str,
    name: str,
    description: str,
    instructions: str,
    content: str,
    *,
    overwrite: bool = False,
) -> tuple[str, str]:
    existing = await find_document(client, room_id, name)
    if existing:
        current = await read_document(client, existing["id"])
        if overwrite and existing.get("created_by_agent_id") == client.agent_id:
            await client.op("update_room_document", {"document_id": existing["id"], "content": content})
            return existing["id"], content
        return existing["id"], current
    created = await client.op(
        "create_room_document",
        {
            "name": name,
            "description": description,
            "instructions": instructions,
            "content": content,
        },
    )
    return created["document_id"], content


async def update_document(client: SwitchClient, document_id: str, content: str) -> None:
    await client.op("update_room_document", {"document_id": document_id, "content": content})


async def participants(client: SwitchClient) -> list[dict[str, Any]]:
    rows = await client.op("list_participants", {})
    return rows or []
