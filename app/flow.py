from __future__ import annotations

from typing import Any

from app import boss, replies
from app.models import Trace, TurnResult
from app.select_match import match_select
from app.session import store


def start_offer_flow(user: dict[str, Any], started: float, source: str = "rule") -> TurnResult:
    """Declared 2way: QueryLanguage → QueryOfferableOffers → wait for a list choice."""
    msisdn = user["msisdn"]
    lang_res = boss.query_language(msisdn)
    offers_res = boss.query_offerable_offers(msisdn)
    lang = lang_res.get("lang") or user.get("lang") or "zh"
    items = list(offers_res.get("offers") or [])
    sess = store.get(msisdn)
    sess.state = "awaiting_select"
    sess.process_id = "subscribe_offer"
    sess.select_list = items
    sess.pending_intent = "subscribe_offer"
    sess.pending_slots = {"lang": lang}
    sess.touch()
    text = replies.offer_list_text(lang, items)
    trace = Trace(
        route=source,
        intent="browse_offers",
        tools=["query_language", "query_offerable_offers"],
    )
    from app.engine import _finish

    return _finish(msisdn, text, trace, started)


def handle_offer_select(user: dict[str, Any], text: str, started: float) -> TurnResult:
    from app.engine import _dispatch, _finish

    msisdn = user["msisdn"]
    sess = store.get(msisdn)
    lang = str(sess.pending_slots.get("lang") or user.get("lang") or "zh")
    items = list(sess.select_list or [])

    from app.matcher import is_no

    compact = text.strip()
    if compact in {"0", "０"} or is_no(text):
        sess.clear_pending()
        return _finish(msisdn, replies.cancelled(lang), Trace(route="rule", intent="cancel"), started)

    hit = match_select(text, items)
    cands = [c for c in (hit.get("candidates") or []) if c]
    if hit.get("reason") == "ambiguous" and len(cands) >= 2:
        sess.select_list = cands
        sess.state = "awaiting_select"
        sess.touch()
        trace = Trace(route="heuristic", intent="narrow_select", fallback_reason="ambiguous")
        return _finish(msisdn, replies.offer_list_text(lang, cands, narrowed=True), trace, started)
    if not hit.get("ok"):
        trace = Trace(route="rule", intent="need_select", fallback_reason=hit.get("reason"))
        return _finish(msisdn, replies.need_select_text(lang, items), trace, started)

    item = hit["item"]
    source = {"rule": "rule", "heuristic": "heuristic", "llm": "llm"}.get(hit.get("source"), "heuristic")
    slots = {
        "lang": lang,
        "offer_id": item["id"],
        "offer_name_zh": item["zh"],
        "offer_name_en": item["en"],
        "fee": item["fee"],
        "select_source": hit.get("source"),
    }
    sess.state = "awaiting_confirm"
    sess.pending_intent = "subscribe_offer"
    sess.pending_slots = slots
    sess.touch()
    from app.models import IntentPlan

    plan = IntentPlan(intent="subscribe_offer", slots=slots, confirm=True, source=source)
    return _dispatch(user, plan, lang, started, confirmed=False)
