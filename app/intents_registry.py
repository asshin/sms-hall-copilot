from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR

_PATH = DATA_DIR / "intents.json"


@lru_cache
def load_intents_file() -> dict[str, Any]:
    if not _PATH.exists():
        return {"intents": []}
    return json.loads(_PATH.read_text(encoding="utf-8"))


def reload_intents() -> None:
    load_intents_file.cache_clear()


def list_intents() -> list[dict[str, Any]]:
    return list(load_intents_file().get("intents") or [])


def get_intent(intent_id: str) -> dict[str, Any] | None:
    for spec in list_intents():
        if spec.get("id") == intent_id:
            return spec
    return None


def intent_ids() -> set[str]:
    return {str(s["id"]) for s in list_intents() if s.get("id")}


def save_intents_file(payload: dict[str, Any]) -> None:
    _PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reload_intents()


def append_intent(spec: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(_PATH.read_text(encoding="utf-8")) if _PATH.exists() else {"intents": []}
    existing = {str(s.get("id")) for s in data.get("intents") or []}
    if spec["id"] in existing:
        raise ValueError(f"{spec['id']} already exists")
    data.setdefault("intents", []).append(spec)
    save_intents_file(data)
    return spec


def remove_intent(intent_id: str) -> bool:
    if not _PATH.exists():
        return False
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    before = len(data.get("intents") or [])
    data["intents"] = [s for s in data.get("intents") or [] if s.get("id") != intent_id]
    if len(data["intents"]) == before:
        return False
    save_intents_file(data)
    return True
