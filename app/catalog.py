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
