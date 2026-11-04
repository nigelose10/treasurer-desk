#!/usr/bin/env python3
"""Record the Mattermost room while the real agents answer.

Playwright drives two browser contexts (member maya, treasurer user). Replies
are not scripted: the script waits until the posted text shows up in the page.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TAKES = ROOT / "demo" / "takes"
CLAIM = re.compile(r"Claim (C-\d+)")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env


def login(page, username: str, password: str) -> None:
    page.goto("http://127.0.0.1:8065/login", wait_until="domcontentloaded")
    choice = page.locator("a.btn-tertiary")
    login_box = page.locator("#input_loginId")
    page.locator("a.btn-tertiary, #input_loginId").first.wait_for(timeout=30000)
    if choice.count() and not login_box.count():
        choice.first.click()
    login_box.wait_for(timeout=30000)
    login_box.fill(username)
    page.locator("#input_password-input").fill(password)
    page.locator("button:has-text('Log in'), button[type='submit']").first.click()
    page.wait_for_url(re.compile(r".*/channels/.*"), timeout=30000)
    page.goto("http://127.0.0.1:8065/switch/channels/club-finance", wait_until="domcontentloaded")
    # Mattermost sometimes opens a product tour over the post box.
    for label in ("Skip tour", "Skip", "Got it", "Close"):
        button = page.get_by_role("button", name=label)
        if button.count():
            button.first.click()
            page.wait_for_timeout(300)
    page.locator("#post_textbox").wait_for(timeout=30000)


def _visible(page, text: str):
    return page.locator(".post-message__text", has_text=text).first


def speak(page, message: str, wait_for: str, pause_ms: int = 5000) -> None:
    box = page.locator("#post_textbox").first
    box.click()
    box.fill("")
    box.type(message, delay=25)
    page.wait_for_timeout(300)
    box.press("Enter")
    # The reply is produced live. Headless Mattermost sometimes does not paint
    # the websocket update, so once the text is in the channel we reload it.
    try:
        _visible(page, wait_for).wait_for(state="visible", timeout=8000)
    except Exception:
        page.reload(wait_until="domcontentloaded")
        page.locator("#post_textbox").wait_for(timeout=30000)
        _visible(page, wait_for).wait_for(state="visible", timeout=20000)
    _visible(page, wait_for).scroll_into_view_if_needed()
    page.wait_for_timeout(pause_ms)


def main() -> None:
    env = load_env()
    script = yaml.safe_load((ROOT / "demo" / "script.yaml").read_text())
    TAKES.mkdir(parents=True, exist_ok=True)
    for old in TAKES.glob("*.webm"):
        old.unlink()
    timing = []
    claim_id = None
    passwords = {"maya": "MAYA_PASSWORD", "user": "MATTERMOST_USER_PASSWORD"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        contexts = {}
        pages = {}

        def open_person(who: str):
            if who in pages:
                return pages[who]
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(TAKES),
                record_video_size={"width": 1280, "height": 720},
            )
            context.add_init_script("window.localStorage.setItem('__landingPageSeen__', 'true');")
            page = context.new_page()
            started = time.perf_counter()
            login(page, who, env[passwords[who]])
            contexts[who] = context
            pages[who] = page
            timing.append({"who": who, "phase": "login", "seconds": round(time.perf_counter() - started, 2)})
            return page

        try:
            for step in script["steps"]:
                who = step["who"]
                page = open_person(who)
                message = step["say"]
                if "{claim}" in message:
                    if not claim_id:
                        sys.exit("the recorder never saw a claim id")
                    message = message.replace("{claim}", claim_id)
                started = time.perf_counter()
                speak(page, message, step["wait"])
                if claim_id is None:
                    body = page.inner_text("body")
                    found = CLAIM.search(body)
                    if found:
                        claim_id = found.group(1)
                timing.append(
                    {
                        "who": who,
                        "say": message,
                        "wait": step["wait"],
                        "caption": step.get("caption", ""),
                        "seconds": round(time.perf_counter() - started, 2),
                    }
                )
            pages["user"].wait_for_timeout(4000)
        finally:
            videos = {}
            for who, context in contexts.items():
                video = pages[who].video
                path = TAKES / f"{who}.webm"
                context.close()
                if video:
                    video.save_as(str(path))
                    videos[who] = str(path)
            browser.close()
    (TAKES / "timing.json").write_text(json.dumps({"claim_id": claim_id, "steps": timing, "videos": videos}, indent=2))
    print(json.dumps({"claim_id": claim_id, "videos": videos}, indent=2))


if __name__ == "__main__":
    main()
