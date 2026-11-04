# How Switch is used

Headless self-host, no Switch Console. Switch 0.31.0 is the room: identities, documents, and the bridge to Mattermost. This repo does not vendor Switch. `scripts/get-switch.sh` downloads the pinned compose file and the stack pulls `ghcr.io/sandbox-quantum/switch-core:0.31.0`.

| Switch feature | What Treasurer Desk does | Where |
|---|---|---|
| Self-host compose, profiles `collab` and `gateway` | `make up` starts Postgres, switch-core, Mattermost, the seeder, and the Gateway | `scripts/up.sh` |
| `POST /agents` with `connection_model: always_on` | Registers `@intake`, `@auditor`, and `@bookkeeper` | `desk/switch_client.py` `register_agent` |
| Addressing policy | Gateway login, then `PUT /gateway/agents/{id}/addressing-policy` with `{"policy": null}` so a human @mention is delivered | `desk/switch_client.py` line 191 |
| SSE `GET /agents/{id}/events` `filter=addressed` | Each agent keeps its own stream and ignores messages that do not mention it | `desk/switch_client.py` lines 85–105 |
| Heartbeat every 2 seconds | `POST /agents/{id}/connection/beat` while the stream is open | `desk/runner.py` `beat` |
| `create_room` | Creates `#club-finance` and the Mattermost channel, and invites the three agents plus `user`, `maya`, and `sam` | `desk/runner.py` line 109 |
| `send_targeted_message` | Intake hands a claim to `@auditor`. The auditor hands the verdict to `@bookkeeper` | `desk/agents/intake.py` line 83, `desk/agents/auditor.py` line 79 |
| Room documents | `claims`, `audits`, `club-policy`, and `ledger` are the state. They are re-read after a restart | `desk/documents.py` line 56 |
| Sender identity | The treasurer gate compares `sender_name` with `TREASURER_USERNAMES` and requires a human participant. An agent id is refused | `desk/commands.py` line 87, `desk/agents/bookkeeper.py` line 60 |
| Human in the room | Approve, reject, and adjust are typed in the same Mattermost channel. The desk never moves money | `desk/agents/bookkeeper.py` |

Agent tasks (`delegate_task` and the rest) are not used. Switch documents them as present but not ready. Handoff is an @mention.
