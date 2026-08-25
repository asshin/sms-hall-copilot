from __future__ import annotations

from typing import Any

SENSITIVE = {"pause_data", "resume_data", "subscribe_vas", "unsubscribe_vas", "topup", "voucher_topup"}

PLAN_ONLY = {
    "pause_data": {"prepaid"},
    "resume_data": {"prepaid"},
    "topup": {"prepaid"},
    "voucher_topup": {"prepaid"},
    "query_bill": {"postpaid"},
}


def requires_confirm(intent: str, command: dict[str, Any] | None = None) -> bool:
    if command and command.get("confirm"):
        return True
    from app.intents_registry import get_intent

    spec = get_intent(intent)
    if spec is not None:
        return bool(spec.get("confirm"))
    return intent in SENSITIVE


def forbid_reason(intent: str, user: dict[str, Any]) -> str | None:
    from app.intents_registry import get_intent

    spec = get_intent(intent)
    if spec is not None:
        allowed = set(spec.get("plans") or [])
        if allowed and user.get("plan") not in allowed:
            return "plan_mismatch"
        return None
    allowed = PLAN_ONLY.get(intent)
    if allowed and user.get("plan") not in allowed:
        if intent == "query_bill":
            return "prepaid_no_bill"
        if intent in {"pause_data", "resume_data"}:
            return "postpaid_no_pause"
        if intent == "voucher_topup":
            return "voucher_prepaid_only"
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
    if intent == "set_language":
        lang = (user.get("_slots") or {}).get("lang")
        if lang and user.get("lang") == lang:
            return "already_lang"
    if intent == "voucher_topup":
        pin = str((user.get("_slots") or {}).get("pin") or "")
        if not pin:
            return "need_pin"
        from app.tools import inspect_voucher

        card = inspect_voucher(pin)
        if card is None:
            return "invalid_pin"
        if card.get("used"):
            return "voucher_used"
    return None
