from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.catalog import get_user, load_catalog, load_users

_RUNTIME: dict[str, dict[str, Any]] | None = None


def _users() -> dict[str, dict[str, Any]]:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = {k: deepcopy(v) for k, v in load_users().items()}
    return _RUNTIME


def reset_runtime() -> None:
    global _RUNTIME
    _RUNTIME = None


def snapshot(msisdn: str) -> dict[str, Any] | None:
    return _users().get(msisdn) or deepcopy(get_user(msisdn) or {})


def get_balance(msisdn: str) -> dict[str, Any]:
    u = _users()[msisdn]
    if u["plan"] != "prepaid":
        return {"ok": False, "reason": "postpaid_no_balance"}
    return {"ok": True, "balance": u["balance"], "currency": "HKD"}


def get_data_usage(msisdn: str) -> dict[str, Any]:
    u = _users()[msisdn]
    return {"ok": True, "data_mb": u["data_mb"], "paused": u["data_paused"]}


def get_bill(msisdn: str) -> dict[str, Any]:
    u = _users()[msisdn]
    if u["plan"] != "postpaid":
        return {"ok": False, "reason": "prepaid_no_bill"}
    return {"ok": True, "bill": u["bill"], "currency": "HKD"}


def get_plan(msisdn: str) -> dict[str, Any]:
    u = _users()[msisdn]
    return {
        "ok": True,
        "plan": u["plan"],
        "name_zh": u["plan_name_zh"],
        "name_en": u["plan_name_en"],
    }


def pause_data_service(msisdn: str) -> dict[str, Any]:
    u = _users()[msisdn]
    u["data_paused"] = True
    return {"ok": True, "data_paused": True}


def resume_data_service(msisdn: str) -> dict[str, Any]:
    u = _users()[msisdn]
    u["data_paused"] = False
    return {"ok": True, "data_paused": False}


def subscribe_vas(msisdn: str, vas_code: str = "caller_id") -> dict[str, Any]:
    u = _users()[msisdn]
    if vas_code not in u["vas"]:
        u["vas"].append(vas_code)
    vas = load_catalog()["vas"][vas_code]
    return {"ok": True, "vas_code": vas_code, "fee": vas["monthly_fee"]}


def unsubscribe_vas(msisdn: str, vas_code: str = "caller_id") -> dict[str, Any]:
    u = _users()[msisdn]
    u["vas"] = [v for v in u["vas"] if v != vas_code]
    return {"ok": True, "vas_code": vas_code}


def topup(msisdn: str, amount: float) -> dict[str, Any]:
    u = _users()[msisdn]
    u["balance"] = round(float(u.get("balance") or 0) + amount, 2)
    return {"ok": True, "balance": u["balance"]}


TOOL_MAP = {
    "get_balance": lambda msisdn, **_: get_balance(msisdn),
    "get_data_usage": lambda msisdn, **_: get_data_usage(msisdn),
    "get_bill": lambda msisdn, **_: get_bill(msisdn),
    "get_plan": lambda msisdn, **_: get_plan(msisdn),
    "pause_data_service": lambda msisdn, **_: pause_data_service(msisdn),
    "resume_data_service": lambda msisdn, **_: resume_data_service(msisdn),
    "subscribe_vas": lambda msisdn, **kw: subscribe_vas(msisdn, kw.get("vas_code", "caller_id")),
    "unsubscribe_vas": lambda msisdn, **kw: unsubscribe_vas(msisdn, kw.get("vas_code", "caller_id")),
    "topup": lambda msisdn, **kw: topup(msisdn, float(kw["amount"])),
}

INTENT_TOOL = {
    "query_balance": "get_balance",
    "query_data": "get_data_usage",
    "query_bill": "get_bill",
    "query_plan": "get_plan",
    "pause_data": "pause_data_service",
    "resume_data": "resume_data_service",
    "subscribe_vas": "subscribe_vas",
    "unsubscribe_vas": "unsubscribe_vas",
    "topup": "topup",
}


def run_tool(intent: str, msisdn: str, slots: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    name = INTENT_TOOL[intent]
    result = TOOL_MAP[name](msisdn, **(slots or {}))
    return name, result
