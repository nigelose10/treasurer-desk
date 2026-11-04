#!/usr/bin/env python3
"""Create the fictional Mattermost members maya and sam.

The treasurer is the bundled user named `user`, seeded by Switch's setup
container. maya and sam are labelled demo people. This script never prints
passwords.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def request(method: str, url: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            payload = json.loads(raw) if raw else {}
            return response.status, payload, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:400]}
        return exc.code, payload, dict(exc.headers)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env = load_env(root / ".env")
    base = "http://127.0.0.1:8065"
    login = urllib.request.Request(
        f"{base}/api/v4/users/login",
        data=json.dumps(
            {"login_id": env["MATTERMOST_ADMIN_USER"], "password": env["MATTERMOST_ADMIN_PASSWORD"]}
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(login, timeout=30) as response:
        token = response.headers["Token"]
    status, team, _ = request("GET", f"{base}/api/v4/teams/name/{env['MATTERMOST_TEAM_NAME']}", token=token)
    if status != 200:
        sys.exit(f"team lookup failed: {status} {team}")
    people = (
        ("maya", "Maya", env["MAYA_PASSWORD"], "maya@example.test"),
        ("sam", "Sam", env["SAM_PASSWORD"], "sam@example.test"),
    )
    for username, first, password, email in people:
        status, existing, _ = request("GET", f"{base}/api/v4/users/username/{username}", token=token)
        if status == 200:
            user_id = existing["id"]
            print(f"{username} already exists")
        else:
            status, created, _ = request(
                "POST",
                f"{base}/api/v4/users",
                {
                    "email": email,
                    "username": username,
                    "password": password,
                    "first_name": first,
                    "last_name": "Demo",
                },
                token=token,
            )
            if status not in {200, 201}:
                sys.exit(f"could not create {username}: {status} {created}")
            user_id = created["id"]
            print(f"created fictional member {username}")
        status, membership, _ = request(
            "POST",
            f"{base}/api/v4/teams/{team['id']}/members",
            {"team_id": team["id"], "user_id": user_id},
            token=token,
        )
        if status not in {200, 201} and "already" not in json.dumps(membership).lower():
            # Mattermost returns 400 when the membership exists.
            if status != 400:
                sys.exit(f"could not add {username} to the team: {status} {membership}")
    print("seed complete (maya, sam, and the bundled treasurer user)")


if __name__ == "__main__":
    main()
