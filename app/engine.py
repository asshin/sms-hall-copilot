from __future__ import annotations

import re
import time
from typing import Any

from app.config import settings
from app import heuristic, llm, matcher, replies, tools
from app.tools import snapshot
from app.models import IntentPlan, Trace, TurnResult
from app.policy import forbid_reason, requires_confirm
from app.rag import search
from app.session import store
from app.sms import compose_meta

_AMOUNT = re.compile(r"^\d{1,4}$")


def handle_mo(msisdn: str, text: str) -> TurnResult:
    started = time.perf_counter()
    user = snapshot(msisdn)
    if not user:
        reply = replies.unknown_user()
        return _finish(msisdn, reply, Trace(route="rule", intent="unknown_user"), started)

    lang: str = user.get("lang") or "zh"
    sess = store.get(msisdn)
    expired = store.consume_expired(msisdn)
    if expired:
        return _finish(
            msisdn,
            replies.session_expired_text(lang, expired),
            Trace(route="rule", intent="session_expired", fallback_reason=expired.get("state")),
            started,
        )

    if sess.state == "awaiting_confirm":
        if matcher.is_yes(text):
            plan = IntentPlan(
                intent=sess.pending_intent or "out_of_scope",
                slots=dict(sess.pending_slots),
                source="confirm",
                confirm=False,
            )
            sess.clear_pending()
            return _dispatch(user, plan, lang, started, confirmed=True)
        if matcher.is_no(text):
            sess.clear_pending()
            return _finish(msisdn, replies.cancelled(lang), Trace(route="confirm", intent="cancel"), started)
        return _finish(msisdn, replies.need_yn(lang), Trace(route="confirm", intent=sess.pending_intent or "confirm"), started)

    if sess.state == "awaiting_select":
        from app.flow import handle_offer_select

        return handle_offer_select(user, text, started)

    if matcher.is_yes(text) and sess.last_receipt:
        receipt = sess.last_receipt
        intent = str(receipt.get("intent") or "already_done")
        return _finish(
            msisdn,
            replies.receipt_text(lang, intent),
            Trace(route="confirm", intent=intent, forbidden=True),
            started,
        )

    if sess.state == "in_menu" and sess.menu_code == "5":
        handled = _handle_topup_menu(user, text, lang, started)
        if handled is not None:
            return handled

    rule = matcher.match_rule(text, user)
    if rule:
        rule.slots["matched_code"] = matcher.normalize(text)
        return _dispatch(user, rule, lang, started, confirmed=False)

    rag_hits = search(text)
    fallback = None
    try:
        if settings.llm_enabled:
            plan = llm.classify(text, user)
            fallback = (plan.slots or {}).pop("_fallback", None)
        else:
            plan = heuristic.plan(text)
    except Exception as exc:  # noqa: BLE001 — demo must degrade
        plan = heuristic.plan(text)
        fallback = f"llm_error:{type(exc).__name__}"

    if rag_hits:
        plan.slots.setdefault("rag", rag_hits)
    return _dispatch(user, plan, lang, started, confirmed=False, fallback=fallback, rag_hits=rag_hits)


def _handle_topup_menu(user: dict[str, Any], text: str, lang: str, started: float) -> TurnResult | None:
    compact = matcher.normalize(text)
    if compact in {"0", "０"} or matcher.is_no(text):
        plan = IntentPlan(intent="show_menu", slots={"menu_code": ""}, source="rule")
        return _dispatch(user, plan, lang, started, confirmed=False)
    raw = text.strip()
    if _AMOUNT.fullmatch(raw):
        amount = int(raw)
        allowed = tools.topup_amounts()
        if amount not in allowed:
            return _finish(
                user["msisdn"],
                replies.forbid_text(lang, "need_amount"),
                Trace(route="rule", intent="need_amount"),
                started,
            )
        plan = IntentPlan(intent="topup", slots={"amount": amount}, confirm=True, source="rule")
        return _dispatch(user, plan, lang, started, confirmed=False)
    return None


def _dispatch(
    user: dict[str, Any],
    plan: IntentPlan,
    lang: str,
    started: float,
    confirmed: bool,
    fallback: str | None = None,
    rag_hits: list[str] | None = None,
) -> TurnResult:
    msisdn = user["msisdn"]
    sess = store.get(msisdn)
    usage = (plan.slots or {}).pop("_usage", None) or {}
    matched = plan.slots.pop("matched_code", None)
    rag_hits = rag_hits or plan.slots.pop("rag", None) or []

    if plan.intent == "show_menu":
        menu_code = str(plan.slots.get("menu_code") or "")
        if menu_code:
            sess.state = "in_menu"
            sess.menu_code = menu_code
        else:
            sess.state = "idle"
            sess.menu_code = ""
        text = replies.menu_text(lang, menu_code)
        trace = Trace(
            route=plan.source,
            intent="show_menu",
            matched_code=matched,
            rag_hits=list(rag_hits)[:2],
            fallback_reason=fallback,
        )
        return _finish(msisdn, text, trace, started, usage)

    if plan.intent == "browse_offers":
        from app.flow import start_offer_flow

        return start_offer_flow(user, started, plan.source)

    if plan.intent == "out_of_scope":
        trace = Trace(route=plan.source, intent="out_of_scope", rag_hits=list(rag_hits)[:2], fallback_reason=fallback)
        return _finish(msisdn, replies.out_of_scope(lang), trace, started, usage)

    user["_slots"] = plan.slots
    reason = forbid_reason(plan.intent, user)
    if reason:
        trace = Trace(
            route=plan.source,
            intent=plan.intent,
            matched_code=matched,
            forbidden=True,
            fallback_reason=fallback,
        )
        return _finish(msisdn, replies.forbid_text(lang, reason), trace, started, usage)

    if (plan.confirm or requires_confirm(plan.intent)) and not confirmed:
        sess.state = "awaiting_confirm"
        sess.pending_intent = plan.intent
        sess.pending_slots = dict(plan.slots)
        sess.touch()
        trace = Trace(
            route=plan.source,
            intent=plan.intent,
            matched_code=matched,
            confirm_required=True,
            fallback_reason=fallback,
        )
        return _finish(msisdn, replies.confirm_text(lang, plan.intent, plan.slots), trace, started, usage)

    if not tools.has_tool(plan.intent):
        trace = Trace(route=plan.source, intent=plan.intent, fallback_reason=fallback)
        return _finish(msisdn, replies.out_of_scope(lang), trace, started, usage)

    tool_name, payload = tools.run_tool(plan.intent, msisdn, plan.slots)
    text = replies.result_text(lang, plan.intent, payload, plan.slots)
    if payload.get("ok") and requires_confirm(plan.intent):
        sess.last_receipt = {"intent": plan.intent, "slots": dict(plan.slots)}
        sess.touch()
    trace = Trace(
        route=plan.source,
        intent=plan.intent,
        matched_code=matched,
        tools=[tool_name],
        rag_hits=list(rag_hits)[:2],
        fallback_reason=fallback if payload.get("ok") else (payload.get("reason") or fallback),
    )
    return _finish(msisdn, text, trace, started, usage)


def _finish(
    msisdn: str,
    text: str,
    trace: Trace,
    started: float,
    usage: dict[str, int] | None = None,
) -> TurnResult:
    parts = replies.as_sms(text)
    meta = compose_meta(text)
    trace.latency_ms = int((time.perf_counter() - started) * 1000)
    trace.sms_encoding = str(meta["encoding"])
    trace.sms_parts = int(meta["parts"])
    if usage:
        trace.prompt_tokens = int(usage.get("prompt") or 0)
        trace.completion_tokens = int(usage.get("completion") or 0)
        trace.cost_usd = round(
            trace.prompt_tokens / 1_000_000 * settings.llm_input_price_per_1m
            + trace.completion_tokens / 1_000_000 * settings.llm_output_price_per_1m,
            6,
        )
    return TurnResult(replies=parts, trace=trace, session_state=store.get(msisdn).state)
