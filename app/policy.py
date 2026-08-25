from __future__ import annotations

from typing import Any

SENSITIVE = {"pause_data", "resume_data", "subscribe_vas", "unsubscribe_vas", "topup"}

PLAN_ONLY = {
    "pause_data": {"prepaid"},
    "resume_data": {"prepaid"},
    "topup": {"prepaid"},
    "query_bill": {"postpaid"},
}


def requires_confirm(intent: str, command: dict[str, Any] | None = None) -> bool:
    if command and command.get("confirm"):
        return True
    return intent in SENSITIVE


def forbid_reason(intent: str, user: dict[str, Any]) -> str | None:
    allowed = PLAN_ONLY.get(intent)
    if allowed and user.get("plan") not in allowed:
        if intent == "query_bill":
            return "prepaid_no_bill"
        if intent in {"pause_data", "resume_data"}:
            return "postpaid_no_pause"
        return "plan_mismatch"
    if intent == "pause_data" and user.get("data_paused"):
        return "already_paused"
    if intent == "resume_data" and not user.get("data_paused"):
        return "not_paused"
    if intent == "subscribe_vas":
        code = (user.get("_slots") or {}).get("vas_code") or "caller_id"
        if code in user.get("vas", []):
            return "vas_already_on"
    if intent == "unsubscribe_vas":
        code = (user.get("_slots") or {}).get("vas_code") or "caller_id"
        if code not in user.get("vas", []):
            return "vas_not_on"
    return None
