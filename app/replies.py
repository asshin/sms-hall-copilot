from __future__ import annotations

from typing import Any

from app.catalog import load_catalog
from app.sms import split_sms

VAS_NAME = lambda code, lang: load_catalog()["vas"][code]["zh" if lang == "zh" else "en"]


def t(lang: str, zh: str, en: str) -> str:
    return zh if lang == "zh" else en


def forbid_text(lang: str, reason: str) -> str:
    mapping = {
        "prepaid_no_bill": ("预付费无月结账单，请发 BAL 查余额。", "Prepaid has no bill. Send BAL for balance."),
        "postpaid_no_pause": ("后付费不支持短厅暂停数据。", "Postpaid cannot pause data via SMS hall."),
        "plan_mismatch": ("当前套餐不支持该业务。", "Not available on your plan."),
        "already_paused": ("数据服务已是暂停状态。", "Data is already paused."),
        "not_paused": ("数据服务目前是开通状态。", "Data is not paused."),
        "vas_already_on": ("该增值业务已开通。", "VAS already active."),
        "vas_not_on": ("该增值业务未开通。", "VAS is not active."),
    }
    zh, en = mapping.get(reason, ("暂不能办理。", "Not eligible."))
    return t(lang, zh, en)


def confirm_text(lang: str, intent: str, slots: dict[str, Any]) -> str:
    if intent == "pause_data":
        return t(lang, "将暂停本地及漫游数据，回复 Y 确认，N 取消。", "Pause local & roaming data. Reply Y to confirm, N to cancel.")
    if intent == "resume_data":
        return t(lang, "将恢复数据服务，回复 Y 确认，N 取消。", "Resume data. Reply Y to confirm, N to cancel.")
    if intent == "subscribe_vas":
        name = VAS_NAME(slots.get("vas_code", "caller_id"), lang)
        return t(lang, f"订购{name}将产生月费，回复 Y 确认，N 取消。", f"Subscribe {name} (monthly fee). Reply Y to confirm, N to cancel.")
    if intent == "unsubscribe_vas":
        name = VAS_NAME(slots.get("vas_code", "caller_id"), lang)
        return t(lang, f"退订{name}，回复 Y 确认，N 取消。", f"Unsubscribe {name}. Reply Y to confirm, N to cancel.")
    return t(lang, "回复 Y 确认，N 取消。", "Reply Y to confirm, N to cancel.")


def result_text(lang: str, intent: str, payload: dict[str, Any], slots: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return forbid_text(lang, payload.get("reason") or "plan_mismatch")
    if intent == "query_balance":
        return t(lang, f"当前余额 {payload['balance']} {payload['currency']}。", f"Balance {payload['balance']} {payload['currency']}.")
    if intent == "query_data":
        paused = t(lang, "已暂停", "paused") if payload.get("paused") else t(lang, "正常", "active")
        return t(lang, f"剩余流量 {payload['data_mb']}MB，状态{paused}。", f"{payload['data_mb']}MB left, {paused}.")
    if intent == "query_bill":
        return t(lang, f"本期账单 {payload['bill']} {payload['currency']}。", f"Bill {payload['bill']} {payload['currency']}.")
    if intent == "query_plan":
        name = payload["name_zh"] if lang == "zh" else payload["name_en"]
        return t(lang, f"当前套餐：{name}。", f"Plan: {name}.")
    if intent == "pause_data":
        return t(lang, "已暂停本地及漫游数据服务。", "Local and roaming data paused.")
    if intent == "resume_data":
        return t(lang, "数据服务已恢复。", "Data service resumed.")
    if intent == "subscribe_vas":
        name = VAS_NAME(slots.get("vas_code", "caller_id"), lang)
        return t(lang, f"已订购{name}，月费{payload['fee']}。", f"{name} subscribed, monthly {payload['fee']}.")
    if intent == "unsubscribe_vas":
        name = VAS_NAME(slots.get("vas_code", "caller_id"), lang)
        return t(lang, f"已退订{name}。", f"{name} unsubscribed.")
    if intent == "topup":
        return t(lang, f"充值成功，余额 {payload['balance']}。", f"Top up ok. Balance {payload['balance']}.")
    return t(lang, "办理完成。", "Done.")


def menu_text(lang: str, menu_code: str = "") -> str:
    cat = load_catalog()
    if not menu_code:
        return cat["root_menu"][lang]
    for m in cat["menus"]:
        if m["code"] == menu_code:
            return m[lang]
    return cat["root_menu"][lang]


def out_of_scope(lang: str) -> str:
    return t(
        lang,
        "暂无法处理该问题。请发 1880 查看菜单，或发 BAL/DATA 查询。",
        "Can't handle that. Send 1880 for menu, or BAL/DATA to query.",
    )


def cancelled(lang: str) -> str:
    return t(lang, "已取消。", "Cancelled.")


def need_yn(lang: str) -> str:
    return t(lang, "请回复 Y 确认或 N 取消。", "Please reply Y to confirm or N to cancel.")


def unknown_user(lang: str = "zh") -> str:
    return t(lang, "号码未登记。演示请用 85259990001/002/003。", "Unknown number. Demo: 85259990001/002/003.")


def as_sms(text: str) -> list[str]:
    return split_sms(text)
