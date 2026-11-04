"""End-to-end flow through a real Switch server and the bundled Mattermost.

Offline rules mode. Every assertion is on a message the agents posted, or on
the ledger text the bookkeeper reads back from the room document.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLAIM_ID = re.compile(r"\b(C-\d+)\b")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


class Mattermost:
    def __init__(self, env: dict[str, str]):
        self.base = "http://127.0.0.1:8065"
        self.env = env
        self.tokens: dict[str, str] = {}
        self.channel_id = ""

    def login(self, username: str, password: str) -> str:
        request = urllib.request.Request(
            f"{self.base}/api/v4/users/login",
            data=json.dumps({"login_id": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            token = response.headers["Token"]
        self.tokens[username] = token
        return token

    def _get(self, path: str, token: str):
        request = urllib.request.Request(
            f"{self.base}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())

    def _post(self, path: str, token: str, body: dict):
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())

    def open_channel(self) -> None:
        token = self.tokens["maya"]
        teams = self._get("/api/v4/users/me/teams", token)
        team = next(item for item in teams if item["name"] == self.env["MATTERMOST_TEAM_NAME"])
        deadline = time.time() + 60
        while time.time() < deadline:
            channels = self._get(f"/api/v4/users/me/teams/{team['id']}/channels", token)
            for channel in channels:
                if channel.get("name") == "club-finance":
                    self.channel_id = channel["id"]
                    return
            time.sleep(2)
        raise AssertionError("club-finance channel was not created")

    def post(self, username: str, message: str) -> dict:
        return self._post(
            "/api/v4/posts",
            self.tokens[username],
            {"channel_id": self.channel_id, "message": message},
        )

    def messages(self) -> list[dict]:
        token = next(iter(self.tokens.values()))
        payload = self._get(f"/api/v4/channels/{self.channel_id}/posts?per_page=200", token)
        order = payload.get("order") or []
        posts = payload.get("posts") or {}
        rows = [posts[post_id] for post_id in order if post_id in posts]
        rows.sort(key=lambda row: row.get("create_at", 0))
        return rows

    def wait_for(self, pattern: str, since_ms: int, timeout: float = 50) -> dict:
        compiled = re.compile(pattern, re.IGNORECASE)
        deadline = time.time() + timeout
        while time.time() < deadline:
            for row in self.messages():
                if row.get("create_at", 0) < since_ms:
                    continue
                if compiled.search(row.get("message") or ""):
                    return row
            time.sleep(1)
        blob = "\n---\n".join((row.get("message") or "")[:400] for row in self.messages()[-12:])
        raise AssertionError(f"timed out waiting for {pattern!r}\nrecent:\n{blob}")


@pytest.fixture(scope="module")
def world():
    ready = ROOT / ".state" / "ready"
    if not ready.exists():
        pytest.fail("desk is not ready; run make up && make seed && make desk")
    env = load_env()
    chat = Mattermost(env)
    chat.login("maya", env["MAYA_PASSWORD"])
    chat.login("user", env["MATTERMOST_USER_PASSWORD"])
    chat.login("sam", env["SAM_PASSWORD"])
    chat.open_channel()
    return chat


def _since(chat: Mattermost) -> int:
    rows = chat.messages()
    if not rows:
        return 0
    return rows[-1]["create_at"] + 1


def test_reimbursement_flow(world: Mattermost):
    chat = world
    transcript: list[str] = [
        "# Transcript captured from Mattermost",
        "",
        "Fictional demo data. Rules mode. No money moved.",
        "",
    ]
    metrics: dict[str, float] = {}

    def say(username: str, message: str) -> int:
        since = _since(chat)
        chat.post(username, message)
        transcript.append(f"**{username}:** {message}")
        return since

    def expect(pattern: str, since: int, timeout: float = 50) -> str:
        row = chat.wait_for(pattern, since, timeout=timeout)
        text = row["message"]
        transcript.append(f"**agent:** {text}")
        transcript.append("")
        return text

    started = time.perf_counter()
    since = say(
        "maya",
        "@intake claim 42.30 pizza 2026-11-03 event:thursday-meetup receipt:inline",
    )
    card = expect(r"Claim C-\d+", since)
    passed = expect(r"C-\d+ PASS", since)
    metrics["claim_to_verdict_seconds"] = round(time.perf_counter() - started, 3)
    expect(r"Waiting for the treasurer", since)
    claim_id = CLAIM_ID.search(card).group(1)
    assert claim_id in passed

    since = say("user", f"@bookkeeper approve {claim_id}")
    approved = expect(r"Approved " + claim_id, since)
    assert "E-transfer" in approved
    assert "did not move money" in approved

    since = say(
        "maya",
        "@intake claim 90.00 pizza 2026-11-03 event:thursday-meetup receipt:over-cap",
    )
    flagged = expect(r"C-\d+ FLAG", since)
    over_id = CLAIM_ID.search(flagged).group(1)
    expect(r"Waiting for the treasurer", since)
    since = say("user", f"@bookkeeper approve {over_id}")
    refused = expect(r"Refused", since)
    assert "override" in refused.lower()
    since = say("user", f"@bookkeeper adjust {over_id} amount=38.00")
    adjusted = expect(r"Approved " + over_id, since)
    assert "38.00" in adjusted

    since = say("maya", "@intake beer $15.00 on 2026-11-03 event:social receipt:bar-tab")
    blocked = expect(r"C-\d+ BLOCK", since)
    assert "alcohol" in blocked.lower()

    since = say(
        "maya",
        "@intake claim 42.30 pizza 2026-11-03 event:thursday-meetup receipt:second-copy",
    )
    duplicate = expect(r"BLOCK", since)
    assert "duplicate" in duplicate.lower()

    since = say("maya", "@intake I think I paid something for snacks")
    unread = expect(r"could not read", since)
    assert "claim <amount>" in unread

    since = say("maya", "@intake claim 10.00 coffee 2026-11-04 event:office-hours receipt:cup")
    small = expect(r"C-\d+ PASS", since)
    small_id = CLAIM_ID.search(small).group(1)
    since = say("sam", f"@bookkeeper approve {small_id}")
    sam_refused = expect(r"Refused", since)
    assert "sam" in sam_refused.lower()
    since = say("user", f"@bookkeeper approve {small_id}")
    expect(r"Approved " + small_id, since)

    since = say("user", "@bookkeeper summary")
    summary = expect(r"Month summary", since)
    assert "No money has moved." in summary

    since = say("maya", f"@auditor why {claim_id}")
    why = expect(r"Ledger:", since)
    assert claim_id in why

    prior = subprocess.run(
        ["docker", "logs", "treasurer-desk-desk-1"],
        check=False,
        capture_output=True,
        text=True,
    )
    ready_count = (prior.stdout + prior.stderr).count("desk ready")
    subprocess.run(["docker", "restart", "treasurer-desk-desk-1"], check=True, timeout=90)
    deadline = time.time() + 120
    while time.time() < deadline:
        logs = subprocess.run(
            ["docker", "logs", "treasurer-desk-desk-1"],
            check=False,
            capture_output=True,
            text=True,
        )
        if (logs.stdout + logs.stderr).count("desk ready") > ready_count:
            time.sleep(2)
            break
        time.sleep(2)
    else:
        pytest.fail("desk did not log ready again after restart")
    since = say("user", "@bookkeeper ledger")
    ledger = expect(claim_id, since)
    assert "No money has moved." in ledger
    transcript.append("Restarted the desk container. The ledger document was still there.")

    (ROOT / "demo").mkdir(exist_ok=True)
    (ROOT / "demo" / "transcript.md").write_text("\n".join(transcript) + "\n")
    (ROOT / "demo" / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    assert metrics["claim_to_verdict_seconds"] < 40
