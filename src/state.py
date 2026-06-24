import json
from pathlib import Path

from . import config


def load() -> dict:
    path = Path(config.STATE_PATH)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(state: dict) -> None:
    path = Path(config.STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
