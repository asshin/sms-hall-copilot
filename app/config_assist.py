from __future__ import annotations

import re
from typing import Any

from app.catalog import commands_by_code, load_catalog
from app.config import settings
from app.policy import PLAN_ONLY, SENSITIVE, requires_confirm
from app.rag import search

ALLOWED_INTENTS = {
    "query_balance",
    "query_data",
    "query_bill",
    "query_plan",
    "pause_data",
    "resume_data",
    "subscribe_vas",
    "unsubscribe_vas",
    "set_language",
    "voucher_topup",
    "topup",
    "unknown",
}

_INTENT_HINTS = [
    (("暂停", "pause", "停数据", "停流量"), "pause_data"),
    (("恢复", "resume"), "resume_data"),
    (("来电显示", "caller"), "subscribe_vas"),
    (("充值卡", "卡密", "voucher"), "voucher_topup"),
    (("语言", "英文", "中文", "english", "chinese"), "set_language"),
    (("余额", "balance"), "query_balance"),
    (("流量", "data"), "query_data"),
    (("账单", "bill"), "query_bill"),
]

PROPOSE_SYSTEM = """You draft HarborTel SMS-hall hidden-command configs.
Return ONLY JSON:
{"intent":"...","command_code":"ABCD","hidden":true,"plans":["prepaid"],"confirm":true,"slots":{}}
intent must be one of: query_balance, query_data, query_bill, query_plan, pause_data, resume_data,
subscribe_vas, unsubscribe_vas, set_language, voucher_topup, topup, unknown.
Do not invent CRM/BCOC endpoint names. If unsure, intent=unknown and omit command_code.
command_code: 2-8 letters or 2-4 digits. Prefer unused codes.
"""


def draft_config(requirement: str, force_heuristic: bool = False) -> dict[str, Any]:
    """Constrained harness: propose → retrieve → conflict → policy → verdict. Never writes catalog."""
    text = requirement.strip()
    steps: list[dict[str, Any]] = []

    hits = search(text)
    steps.append({"id": "retrieve_knowledge", "ok": True, "hits": len(hits)})

    proposal, source, usage = _propose(text, hits, force_heuristic=force_heuristic)
    steps.append({"id": "propose", "ok": True, "source": source, "intent": proposal.get("intent")})

    occupied = commands_by_code()
    requested = _normalize_code(proposal.get("command_code") or "")
    assigned, conflict = _allocate_code(requested, proposal.get("intent") or "unknown", occupied)
    steps.append(
        {
            "id": "check_conflict",
            "ok": conflict is None or assigned != requested,
            "requested": requested or None,
            "assigned": assigned,
            "conflict": conflict,
        }
    )

    intent = proposal.get("intent") if proposal.get("intent") in ALLOWED_INTENTS else "unknown"
    confirm = bool(proposal.get("confirm")) if "confirm" in proposal else requires_confirm(intent)
    if intent in SENSITIVE:
        confirm = True
    if intent == "unknown":
        confirm = True

    plans = _plans_for(intent, text, proposal.get("plans"))
    checks = _policy_checks(intent, confirm, plans, text)
    steps.append({"id": "apply_policy", "ok": all(c["ok"] for c in checks), "n": len(checks)})

    unknowns = _unknowns(text, intent)
    draft = {
        "command_code": assigned,
        "requested_code": requested or None,
        "intent": intent,
        "hidden": True,
        "confirm": confirm,
        "confirm_rounds": 1 if confirm else 0,
        "plans": plans,
        "slots": proposal.get("slots") if isinstance(proposal.get("slots"), dict) else {},
        "success_sms_zh": _template(intent, True),
        "success_sms_en": _template_en(intent),
        "fail_sms_zh": "办理失败，请稍后重试。",
        "fail_sms_en": "Failed. Please try later.",
        "catalog_shortcode": load_catalog()["shortcode"],
    }
    if conflict:
        draft["conflict"] = {
            **conflict,
            "resolved_to": assigned,
            "message": f"{conflict['code']} 已被 {conflict['existing_intent']} 占用，已改派 {assigned}。请人工确认后写入 catalog。",
        }
    else:
        draft["conflict"] = None

    verdict = _verdict(intent, unknowns, checks)
    steps.append({"id": "verdict", "ok": verdict != "blocked", "verdict": verdict})

    return {
        "apply": False,
        "verdict": verdict,
        "verdict_reason": _verdict_reason(verdict, unknowns, conflict),
        "draft": draft,
        "checks": checks,
        "unknowns": unknowns,
        "knowledge_hits": hits[:2],
        "steps": steps,
        "propose_source": source,
        "usage": usage,
    }


def _propose(text: str, hits: list[str], force_heuristic: bool = False) -> tuple[dict[str, Any], str, dict[str, int]]:
    heuristic = _heuristic_propose(text)
    if force_heuristic or not settings.llm_enabled:
        return heuristic, "heuristic", {"prompt": 0, "completion": 0}
    try:
        from app.llm import complete_json

        data, usage = complete_json(
            PROPOSE_SYSTEM,
            f"requirement: {text}\nknowledge: {hits[:2]}\noccupied_sample: {list(commands_by_code())[:12]}",
        )
        if data.get("intent") in ALLOWED_INTENTS:
            merged = {**heuristic, **{k: v for k, v in data.items() if v not in (None, "", [])}}
            return merged, "llm", usage
        return heuristic, "llm_invalid_fallback", usage
    except Exception as exc:  # noqa: BLE001
        heuristic["_fallback"] = type(exc).__name__
        return heuristic, "llm_error_fallback", {"prompt": 0, "completion": 0}


def _heuristic_propose(text: str) -> dict[str, Any]:
    intent = "unknown"
    for keys, name in _INTENT_HINTS:
        if any(k.lower() in text.lower() or k in text for k in keys):
            intent = name
            break
    code_match = re.search(r"\b([A-Z]{2,8}|\d{2,4})\b", text.upper())
    return {
        "intent": intent,
        "command_code": code_match.group(1) if code_match else "",
        "confirm": requires_confirm(intent) if intent != "unknown" else True,
        "plans": None,
        "slots": {},
    }


def _normalize_code(code: str) -> str:
    return re.sub(r"\s+", "", code.strip().upper())


def _allocate_code(requested: str, intent: str, occupied: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    if requested and requested not in occupied:
        return requested, None
    conflict = None
    if requested and requested in occupied:
        conflict = {"code": requested, "existing_intent": occupied[requested]["intent"]}
    base = requested if requested and re.fullmatch(r"[A-Z]{2,8}", requested) else _suggest_base(intent)
    if base not in occupied:
        return base, conflict
    for i in range(2, 30):
        cand = f"{base[:6]}{i}"
        if cand not in occupied:
            return cand, conflict
    return f"{base}X", conflict


def _suggest_base(intent: str) -> str:
    return {
        "pause_data": "STOPX",
        "resume_data": "RESUMX",
        "query_balance": "BALX",
        "query_data": "DATAX",
        "subscribe_vas": "VASX",
        "set_language": "LANGX",
        "voucher_topup": "CARDX",
        "topup": "TOPX",
    }.get(intent, "NEWX")


def _plans_for(intent: str, text: str, proposed: Any) -> list[str]:
    allowed = PLAN_ONLY.get(intent)
    if allowed:
        return sorted(allowed)
    if isinstance(proposed, list) and proposed:
        return [p for p in proposed if p in {"prepaid", "postpaid"}] or ["prepaid", "postpaid"]
    if "后付" in text:
        return ["postpaid"]
    if "预付" in text:
        return ["prepaid"]
    return ["prepaid", "postpaid"]


def _policy_checks(intent: str, confirm: bool, plans: list[str], text: str) -> list[dict[str, Any]]:
    checks = []
    sens_ok = not (intent in SENSITIVE and not confirm)
    checks.append(
        {
            "id": "sensitive_requires_confirm",
            "ok": sens_ok,
            "detail": "关停/订购/充值必须 confirm=true" if not sens_ok else "通过",
        }
    )
    plan_ok = True
    allowed = PLAN_ONLY.get(intent)
    if allowed and set(plans) - allowed:
        plan_ok = False
    checks.append(
        {
            "id": "plan_scope",
            "ok": plan_ok,
            "detail": f"plans={plans}" if plan_ok else f"{intent} 不允许 {plans}",
        }
    )
    crm = bool(re.search(r"(CRM|BCOC|接口|API)", text, re.I))
    checks.append(
        {
            "id": "no_invented_endpoint",
            "ok": True,
            "detail": "需求提到外部接口，草案不得填写具体 URL" if crm else "未声明外部接口",
        }
    )
    checks.append(
        {
            "id": "never_auto_apply",
            "ok": True,
            "detail": "harness 不写 catalog，须人工确认",
        }
    )
    return checks


def _unknowns(text: str, intent: str) -> list[str]:
    unknowns: list[str] = []
    if re.search(r"(CRM|BCOC|接口|API)", text, re.I):
        unknowns.append("crm_endpoint_not_in_knowledge")
    if intent == "unknown":
        unknowns.append("intent_not_recognized")
    return unknowns


def _verdict(intent: str, unknowns: list[str], checks: list[dict[str, Any]]) -> str:
    if intent == "unknown" or any(not c["ok"] for c in checks):
        return "blocked"
    if unknowns:
        return "needs_human_review"
    return "ready_to_copy"


def _verdict_reason(verdict: str, unknowns: list[str], conflict: dict | None) -> str:
    if verdict == "blocked":
        return "意图无法识别或策略检查未通过，禁止落地。"
    parts = ["仅生成草案，不会写入 catalog。"]
    if conflict:
        parts.append("指令码冲突已改派，请人工确认新码。")
    if unknowns:
        parts.append("存在未知项：" + ", ".join(unknowns))
    return " ".join(parts)


def _template(intent: str, ok: bool) -> str:
    if not ok:
        return "办理失败，请稍后重试。"
    return {
        "pause_data": "已暂停本地及漫游数据服务。",
        "resume_data": "数据服务已恢复。",
        "query_balance": "当前余额 {balance} HKD。",
        "subscribe_vas": "已订购{vas_name}。",
        "set_language": "已切换语言。",
        "voucher_topup": "充值卡已入账 {amount} HKD。",
    }.get(intent, "办理完成。")


def _template_en(intent: str) -> str:
    return {
        "pause_data": "Local and roaming data paused.",
        "resume_data": "Data service resumed.",
        "query_balance": "Balance {balance} HKD.",
        "subscribe_vas": "{vas_name} subscribed.",
        "set_language": "Language updated.",
        "voucher_topup": "Voucher {amount} HKD added.",
    }.get(intent, "Done.")
