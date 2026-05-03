from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path("config") / "sources.json"


def load() -> list[dict]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Source registry missing at {CONFIG_PATH}")
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("sources", [])
