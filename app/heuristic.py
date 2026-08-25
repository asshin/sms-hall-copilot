from __future__ import annotations

import re

from app.models import IntentPlan
from app.policy import requires_confirm
from app.rag import search

_PAUSE = ("暂停", "停掉", "pause", "stop data", "停数据", "停流量")
_RULES: list[tuple[tuple[str, ...], str, dict]] = [
    (("余额", "话费", "balance", "credit"), "query_balance", {}),
    (("流量", "data remaining", "remaining data", "还剩多少流量", "剩余流量"), "query_data", {}),
    (("账单", "bill"), "query_bill", {}),
    (("套餐", "plan"), "query_plan", {}),
    (_PAUSE, "pause_data", {}),
    (("恢复", "resume", "重新开通数据"), "resume_data", {}),
    (("来电显示", "caller id", "callerid"), "subscribe_vas", {"vas_code": "caller_id"}),
    (("呼叫等待", "call waiting"), "subscribe_vas", {"vas_code": "call_waiting"}),
    (("退订来电", "关掉来电", "cidoff"), "unsubscribe_vas", {"vas_code": "caller_id"}),
]

_OOS = ("天气", "编一个", "随便编", "隔壁", "ignore previous", "忽略以上")


def plan(text: str) -> IntentPlan:
    low = text.strip().lower()
    if re.search(r"852\d{8}", text) and "8525999" in text:
        # asking about a specific demo number that may not be self
        others = set(re.findall(r"852\d{8}", text))
        if others:
            return IntentPlan(intent="out_of_scope", source="heuristic", confidence=0.9)

    if any(k in low for k in _PAUSE) or any(k in text for k in ("暂停", "停掉", "停数据", "停流量")):
        return IntentPlan(intent="pause_data", confirm=True, source="heuristic", confidence=0.8)

    if any(k in low for k in _OOS) or "编一个" in text or "隔壁" in text:
        return IntentPlan(intent="out_of_scope", source="heuristic", confidence=0.85, slots={"rag": search(text)[:1]})

    for keys, intent, slots in _RULES:
        if any(k in low or k in text for k in keys):
            return IntentPlan(
                intent=intent,
                slots=slots,
                confirm=requires_confirm(intent),
                source="heuristic",
                confidence=0.72,
            )
    return IntentPlan(intent="out_of_scope", source="heuristic", confidence=0.4)
