# Paste-ready submission text

Track: 01 Best Business Workflow

Do not submit this yourself. Nigel registers and clicks Submit. This file is the text.

## Short description

Treasurer Desk is a club reimbursement room on a self-hosted Switch 0.31.0 server. A member posts a claim in Mattermost. Three agents in one process hand it along: intake files it, the auditor applies a written policy in code, and the bookkeeper records only the human treasurer's decision on a shared room document. The desk never moves money. Rules mode runs the whole flow with no LLM key. A live OpenAI-compatible model can phrase explanations and cannot change a verdict.

## Links Nigel fills in

- Repo: https://github.com/nigelose10/treasurer-desk
- README: that repo's README
- Video: upload `docs/demo.mp4` (or the GitHub file) to an unlisted YouTube video on Nigel's channel, then paste that URL. The file in the repo is the recording. It is about 1:46, rules mode, fictional data.
- Track: 01 Best Business Workflow

## What is real

- Switch 0.31.0, Mattermost, and the three agents ran on one machine. `GET /health` returned `{"status":"ok"}`.
- A Mattermost message `@echo hi` was delivered to a custom agent with `sender_name` `user` during the protocol spike, and agent-to-agent @mentions were delivered both with `send_targeted_message` and with a plain `@mention`.
- The committed transcript in `demo/transcript.md` was captured from Mattermost during `pytest tests/e2e`, not written by hand. Claim-to-verdict time in that run was 1.022 seconds.
- 24 unit tests passed. The e2e test passed against the real server, including a desk-container restart that kept the ledger.
- The demo video was recorded with Playwright and ffmpeg. Replies were produced by the running agents in rules mode. No model key was used for the recording.

## What is not true

- No money moved.
- maya, sam, and the claims are fictional.
- Receipt photos are not read. There is no OCR.
- Slack, Teams, and Discord were not bridged. The run used the bundled Mattermost.
- This agent did not register on Luma, did not open the WeMakeDevs form, and did not click Submit.
