from __future__ import annotations

import re
from typing import Any

from app.catalog import commands_by_code, load_catalog
from app.policy import SENSITIVE, requires_confirm
from app.rag import search

_INTENT_HINTS = [
    (("暂停", "pause", "停数据"), "pause_data"),
    (("恢复", "resume"), "resume_data"),
    (("来电显示", "caller"), "subscribe_vas"),
    (("余额", "balance"), "query_balance"),
    (("流量", "data"), "query_data"),
    (("账单", "bill"), "query_bill"),
]


def draft_config(requirement: str) -> dict[str, Any]:
    text = requirement.strip()
    hits = search(text)
    intent = "unknown"
    for keys, name in _INTENT_HINTS:
        if any(k.lower() in text.lower() or k in text for k in keys):
            intent = name
            break

    code_match = re.search(r"\b([A-Z]{2,8}|\d{2,4})\b", text.upper())
    proposed_code = code_match.group(1) if code_match else _suggest_code(intent)
    occupied = commands_by_code()
    conflict = occupied.get(proposed_code.upper())

    confirm = requires_confirm(intent) if intent != "unknown" else True
    if intent == "unknown":
        confirm = True  # fail-safe: never emit unconfirmed write ops

    prepaid_only = intent in {"pause_data", "resume_data"}
    draft = {
        "command_code": proposed_code.upper(),
        "intent": intent,
        "hidden": True,
        "confirm": confirm,
        "plans": ["prepaid"] if prepaid_only else ["prepaid", "postpaid"],
        "confirm_rounds": 1 if confirm else 0,
        "success_sms_zh": _template(intent, True),
        "fail_sms_zh": "办理失败，请稍后重试。",
        "conflict": None
        if not conflict
        else {
            "code": proposed_code.upper(),
            "existing_intent": conflict["intent"],
            "message": f"{proposed_code.upper()} 已被 {conflict['intent']} 占用，请换码。",
        },
        "unknowns": _unknowns(text, intent),
        "knowledge_hits": hits[:2],
        "catalog_shortcode": load_catalog()["shortcode"],
    }
    if intent in SENSITIVE and not draft["confirm"]:
        draft["unknowns"].append("sensitive_intent_missing_confirm")
    return draft


def _suggest_code(intent: str) -> str:
    return {
        "pause_data": "STOP2",
        "resume_data": "RES2",
        "query_balance": "BAL2",
        "query_data": "DAT2",
        "subscribe_vas": "VAS2",
    }.get(intent, "NEW1")


def _template(intent: str, ok: bool) -> str:
    if not ok:
        return "办理失败，请稍后重试。"
    return {
        "pause_data": "已暂停本地及漫游数据服务。",
        "resume_data": "数据服务已恢复。",
        "query_balance": "当前余额 {balance} HKD。",
        "subscribe_vas": "已订购{vas_name}。",
    }.get(intent, "办理完成。")


def _unknowns(text: str, intent: str) -> list[str]:
    unknowns: list[str] = []
    if re.search(r"(CRM|BCOC|接口|API)", text, re.I) and "HarborTel" not in text:
        unknowns.append("crm_endpoint_not_in_knowledge")
    if intent == "unknown":
        unknowns.append("intent_not_recognized")
    return unknowns
