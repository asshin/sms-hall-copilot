from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR


@lru_cache
def load_catalog() -> dict[str, Any]:
    return json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))


@lru_cache
def load_users() -> dict[str, dict[str, Any]]:
    return json.loads((DATA_DIR / "users.json").read_text(encoding="utf-8"))


def get_user(msisdn: str) -> dict[str, Any] | None:
    return load_users().get(msisdn)


def commands_by_code() -> dict[str, dict[str, Any]]:
    return {c["code"].upper(): c for c in load_catalog()["commands"]}


def menu_by_code() -> dict[str, dict[str, Any]]:
    return {m["code"]: m for m in load_catalog()["menus"]}


def reload_catalog() -> None:
    load_catalog.cache_clear()


def save_catalog(catalog: dict[str, Any]) -> None:
    path = DATA_DIR / "catalog.json"
    path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reload_catalog()


def append_command(command: dict[str, Any]) -> dict[str, Any]:
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    code = str(command["code"]).upper()
    existing = {c["code"].upper() for c in catalog["commands"]}
    if code in existing:
        raise ValueError(f"{code} already exists")
    catalog["commands"].append(command)
    save_catalog(catalog)
    return command


def remove_command(code: str) -> bool:
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    before = len(catalog["commands"])
    catalog["commands"] = [c for c in catalog["commands"] if str(c["code"]).upper() != code.upper()]
    if len(catalog["commands"]) == before:
        return False
    save_catalog(catalog)
    return True
