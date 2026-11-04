#!/usr/bin/env python3
"""Show the desk agent ids.

Registration happens inside the desk process on startup, because the API key
is returned once and has to live next to the process that opens the stream.
This script prints ids only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> None:
    state = Path(os.environ.get("STATE_DIR", Path(__file__).resolve().parents[1] / ".state"))
    path = state / "agents.json"
    if not path.exists():
        print("No agents registered yet. Start the desk (`make desk`); it registers on boot.")
        return
    data = json.loads(path.read_text())
    for name, info in data.items():
        print(f"@{name} {info.get('id')}")


if __name__ == "__main__":
    main()
