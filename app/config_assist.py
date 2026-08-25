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

_WRITE_HINTS = ("转账", "开通", "扣", "办理", "订购", "退订")


def _known_intents() -> set[str]:
    from app.intents_registry import intent_ids

    return (ALLOWED_INTENTS | intent_ids()) - {"unknown"}


def draft_config(requirement: str, force_heuristic: bool = False) -> dict[str, Any]:
    """Constrained harness: propose → retrieve → conflict → policy → verdict. Never writes catalog."""
    text = requirement.strip()
    steps: list[dict[str, Any]] = []

    hits = search(text)
    steps.append({"id": "retrieve_knowledge", "ok": True, "hits": len(hits)})

    proposal, source, usage = _propose(text, hits, force_heuristic=force_heuristic)
    steps.append({"id": "propose", "ok": True, "source": source, "intent": proposal.get("intent")})

    occupied = commands_by_code()
    requested = _normalize_code(proposal.get("command_code") or "") or _code_from_text(text)
    known = _known_intents()
    intent = proposal.get("intent") if proposal.get("intent") in known else "unknown"

    from app.intents_registry import get_intent

    spec = get_intent(intent) if intent != "unknown" else None
    if spec and not requested:
        requested = _normalize_code(str(spec.get("command_code") or ""))

    assigned, conflict = _allocate_code(requested, intent or "unknown", occupied)
    already = bool(
        spec is not None
        and requested
        and occupied.get(requested, {}).get("intent") == intent
        and intent != "unknown"
    )
    if already:
        assigned = requested
        conflict = None
    steps.append(
        {
            "id": "check_conflict",
            "ok": already or conflict is None or assigned != requested,
            "requested": requested or None,
            "assigned": assigned,
            "conflict": conflict,
            "already_configured": already,
        }
    )

    confirm = bool(proposal.get("confirm")) if "confirm" in proposal else requires_confirm(intent)
    if spec is not None:
        confirm = bool(spec.get("confirm"))
    if intent in SENSITIVE:
        confirm = True
    if intent == "unknown":
        confirm = True

    plans = list(spec.get("plans") or ["prepaid", "postpaid"]) if spec else _plans_for(intent, text, proposal.get("plans"))
    slots = dict(spec.get("default_slots") or {}) if spec else (
        proposal.get("slots") if isinstance(proposal.get("slots"), dict) else {}
    )
    checks = _policy_checks(intent, confirm, plans, text)
    if spec is not None:
        checks.append({"id": "registered_intent", "ok": True, "detail": f"命中已配置意图 {intent}"})
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
        "slots": slots,
        "success_sms_zh": (spec.get("success_sms_zh") if spec else None) or _template(intent, True),
        "success_sms_en": (spec.get("success_sms_en") if spec else None) or _template_en(intent),
        "fail_sms_zh": (spec.get("fail_sms_zh") if spec else None) or "办理失败，请稍后重试。",
        "fail_sms_en": (spec.get("fail_sms_en") if spec else None) or "Failed. Please try later.",
        "catalog_shortcode": load_catalog()["shortcode"],
    }
    if spec:
        draft["intent_kind"] = spec.get("kind")
        draft["api"] = spec.get("api")
        draft["description"] = spec.get("description")
    if already:
        draft["conflict"] = None
        draft["already_configured"] = {
            "code": requested,
            "intent": intent,
            "message": f"{requested} 已指向 {intent}。请到「用户短厅」发送 {requested} 测试，不必再写入。",
        }
    elif conflict:
        draft["conflict"] = {
            **conflict,
            "resolved_to": assigned,
            "message": f"{conflict['code']} 已被 {conflict['existing_intent']} 占用，已改派 {assigned}。请人工确认后写入 catalog。",
        }
    else:
        draft["conflict"] = None

    if already:
        verdict = "already_configured"
    else:
        verdict = _verdict(intent, unknowns, checks)
    steps.append({"id": "verdict", "ok": verdict != "blocked", "verdict": verdict})

    return {
        "apply": False,
        "can_apply": verdict not in {"blocked", "already_configured"},
        "verdict": verdict,
        "verdict_reason": _verdict_reason(verdict, unknowns, conflict, already=already, code=requested, intent=intent),
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
            _propose_system(),
            f"requirement: {text}\nknowledge: {hits[:2]}\noccupied_sample: {list(commands_by_code())[:12]}\nregistered_intents: {sorted(_known_intents())}",
        )
        if data.get("intent") in _known_intents():
            merged = {**heuristic, **{k: v for k, v in data.items() if v not in (None, "", [])}}
            from app.intents_registry import intent_ids

            if heuristic.get("intent") in intent_ids():
                merged["intent"] = heuristic["intent"]
                if heuristic.get("command_code"):
                    merged["command_code"] = heuristic["command_code"]
            return merged, "llm", usage
        return heuristic, "llm_invalid_fallback", usage
    except Exception as exc:  # noqa: BLE001
        heuristic["_fallback"] = type(exc).__name__
        return heuristic, "llm_error_fallback", {"prompt": 0, "completion": 0}


def _propose_system() -> str:
    extra = ", ".join(sorted(_known_intents()))
    return f"""You draft HarborTel SMS-hall hidden-command configs.
Return ONLY JSON:
{{"intent":"...","command_code":"ABCD","hidden":true,"plans":["prepaid"],"confirm":true,"slots":{{}}}}
intent must be one of: {extra}.
If the requirement matches an already-configured custom intent, use that id (never unknown).
Do not invent new intent names here. Do not invent CRM/BCOC URLs.
command_code: 2-8 letters or 2-4 digits. Prefer unused codes unless the user names an existing one.
"""


def _heuristic_propose(text: str) -> dict[str, Any]:
    spec = _match_registered_intent(text)
    if spec:
        return {
            "intent": spec["id"],
            "command_code": _code_from_text(text) or str(spec.get("command_code") or ""),
            "confirm": bool(spec.get("confirm")),
            "plans": list(spec.get("plans") or []),
            "slots": dict(spec.get("default_slots") or {}),
        }
    intent = "unknown"
    for keys, name in _INTENT_HINTS:
        if any(k.lower() in text.lower() or k in text for k in keys):
            intent = name
            break
    return {
        "intent": intent,
        "command_code": _code_from_text(text),
        "confirm": requires_confirm(intent) if intent != "unknown" else True,
        "plans": None,
        "slots": {},
    }


def _match_registered_intent(text: str) -> dict[str, Any] | None:
    from app.intents_registry import list_intents

    low = text.lower()
    upper = text.upper()
    writing = any(k in text for k in _WRITE_HINTS) and "查询" not in text
    best: dict[str, Any] | None = None
    best_score = 0
    for spec in list_intents():
        score = 0
        iid = str(spec.get("id") or "")
        if iid and (iid in text or iid in low):
            score += 6
        code = str(spec.get("command_code") or "").upper()
        if code and code in upper:
            score += 5
        for kw in spec.get("keywords") or []:
            token = str(kw)
            if len(token) >= 3 and (token in text or token.lower() in low):
                score += min(len(token), 8)
        if spec.get("kind") == "query" and writing:
            score -= 12
        if spec.get("kind") == "query" and "查询" in text:
            score += 3
        if score > best_score:
            best, best_score = spec, score
    return best if best_score >= 4 else None


def _code_from_text(text: str) -> str:
    match = re.search(r"([A-Z]{2,8}|\d{2,4})", text.upper())
    return match.group(1) if match else ""


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
            "detail": "生成草案后须人工勾选并点「审核通过」才写入 catalog",
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


def _verdict_reason(
    verdict: str,
    unknowns: list[str],
    conflict: dict | None,
    already: bool = False,
    code: str = "",
    intent: str = "",
) -> str:
    if verdict == "already_configured":
        return f"{code} 已配置为 {intent}。到用户短厅发送该指令即可，无需再写入。"
    if verdict == "blocked":
        return "意图无法识别或策略检查未通过，禁止落地。若是新业务，请用「新增意图」填写接口描述和出入参。"
    parts = ["仅生成草案。人工勾选确认后才会写入 catalog。"]
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


def apply_approved_draft(payload: dict[str, Any], *, acknowledged: bool) -> dict[str, Any]:
    """Human-in-the-loop write. Blocked or unknown intents never land."""
    from app.catalog import append_command, commands_by_code

    verdict = payload.get("verdict")
    draft = payload.get("draft") or {}
    intent = draft.get("intent")
    code = str(draft.get("command_code") or "").upper()

    if (payload.get("draft") or {}).get("kind") == "new_intent":
        from app.intent_assist import apply_intent_draft

        return apply_intent_draft(payload, acknowledged=acknowledged)
    if verdict == "blocked" or intent in (None, "unknown") or intent not in _known_intents():
        return {"ok": False, "error": "blocked_or_unknown", "message": "意图未识别或策略未通过，不能写入。"}
    if verdict == "already_configured":
        return {"ok": False, "error": "already_configured", "message": f"{code} 已指向 {intent}，不必重复写入。"}
    if not code or not re.fullmatch(r"[A-Z0-9]{2,10}", code):
        return {"ok": False, "error": "bad_code", "message": "指令码不合法。"}
    if not acknowledged:
        return {"ok": False, "error": "need_ack", "message": "请先勾选已人工检查，再确认写入 catalog。"}
    if code in commands_by_code():
        return {"ok": False, "error": "conflict", "message": f"{code} 已被占用。"}

    command = {
        "code": code,
        "intent": intent,
        "hidden": True,
        "confirm": bool(draft.get("confirm")),
        "plans": list(draft.get("plans") or ["prepaid", "postpaid"]),
    }
    slots = draft.get("slots") if isinstance(draft.get("slots"), dict) else {}
    if slots:
        command["slots"] = slots
    append_command(command)
    return {
        "ok": True,
        "applied": True,
        "command": command,
        "message": f"已写入 catalog：{code} → {intent}。短厅页立刻可测。",
    }
