from __future__ import annotations

import re
from typing import Any

from app.catalog import commands_by_code, load_catalog, menu_by_code
from app.models import IntentPlan
from app.policy import requires_confirm

YES = {"Y", "YES", "是", "确认", "確認", "OK"}
NO = {"N", "NO", "否", "取消"}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.strip()).upper()


def is_yes(text: str) -> bool:
    token = text.strip().upper()
    return token in YES or normalize(text) in {normalize(x) for x in YES}


def is_no(text: str) -> bool:
    token = text.strip().upper()
    return token in NO or normalize(text) in {normalize(x) for x in NO}


def match_rule(text: str, user: dict[str, Any]) -> IntentPlan | None:
    code = normalize(text)
    catalog = load_catalog()

    if code in {"1880", "MENU", "帮助", "HELP", "?", "？"} or code == catalog["shortcode"]:
        return IntentPlan(intent="show_menu", source="rule")

    cmd = commands_by_code().get(code)
    if cmd:
        return IntentPlan(
            intent=cmd["intent"],
            slots=dict(cmd.get("slots") or {}),
            confirm=requires_confirm(cmd["intent"], cmd),
            source="rule",
        )

    menus = menu_by_code()
    if code in menus or code == "0":
        return IntentPlan(
            intent="show_menu",
            slots={"menu_code": "" if code == "0" else code},
            source="rule",
        )
    return None
