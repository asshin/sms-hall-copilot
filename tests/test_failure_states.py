from app.engine import handle_mo
from app.llm import parse_json
from app.policy import clamp_classify_intent
from app.session import store
from app.tools import reset_runtime, snapshot


def test_select_session_expiry_does_not_treat_digit_as_menu():
    reset_runtime()
    store.reset()
    listed = handle_mo("85259990001", "OFFER")
    assert listed.session_state == "awaiting_select"
    store.expire_now("85259990001")
    late = handle_mo("85259990001", "1")
    assert late.trace.intent == "session_expired"
    assert late.trace.tools == []
    assert "OFFER" in late.replies[0]
    assert late.session_state == "idle"
    user = snapshot("85259990001")
    assert "OFF_50G_LOCAL" not in (user.get("offers") or [])


def test_confirm_session_expiry_does_not_subscribe():
    reset_runtime()
    store.reset()
    handle_mo("85259990001", "OFFER")
    handle_mo("85259990001", "1")
    store.expire_now("85259990001")
    late = handle_mo("85259990001", "Y")
    assert late.trace.intent == "session_expired"
    assert late.trace.tools == []
    user = snapshot("85259990001")
    assert "OFF_50G_LOCAL" not in (user.get("offers") or [])
    assert user["balance"] == 188.5


def test_duplicate_yes_after_subscribe_does_not_call_tool_again():
    reset_runtime()
    store.reset()
    handle_mo("85259990001", "OFFER")
    handle_mo("85259990001", "1")
    first = handle_mo("85259990001", "Y")
    assert first.trace.tools == ["subscribe_offer"]
    user = snapshot("85259990001")
    assert user["offers"] == ["OFF_50G_LOCAL"]
    assert user["balance"] == 100.5
    second = handle_mo("85259990001", "Y")
    assert second.trace.tools == []
    assert second.trace.forbidden is True
    assert "已订购" in second.replies[0]
    assert snapshot("85259990001")["offers"] == ["OFF_50G_LOCAL"]
    assert snapshot("85259990001")["balance"] == 100.5


def test_menu_topup_amount_then_confirm():
    reset_runtime()
    store.reset()
    menu = handle_mo("85259990001", "5")
    assert menu.trace.intent == "show_menu"
    assert menu.session_state == "in_menu"
    ask = handle_mo("85259990001", "50")
    assert ask.trace.confirm_required is True
    assert ask.trace.tools == []
    done = handle_mo("85259990001", "Y")
    assert done.trace.tools == ["topup"]
    assert "238.5" in done.replies[0]
    assert snapshot("85259990001")["balance"] == 238.5


def test_menu_topup_rejects_unknown_amount_and_postpaid():
    reset_runtime()
    store.reset()
    handle_mo("85259990001", "5")
    bad = handle_mo("85259990001", "51")
    assert bad.trace.intent == "need_amount"
    assert bad.trace.tools == []
    assert snapshot("85259990001")["balance"] == 188.5

    reset_runtime()
    store.reset()
    handle_mo("85259990002", "5")
    refused = handle_mo("85259990002", "50")
    assert refused.trace.forbidden is True
    assert refused.trace.tools == []


def test_insufficient_balance_uses_boss_template_not_success():
    reset_runtime()
    store.reset()
    handle_mo("85259990003", "OFFER")
    handle_mo("85259990003", "1")
    failed = handle_mo("85259990003", "Y")
    assert failed.trace.tools == ["subscribe_offer"]
    assert failed.trace.fallback_reason == "insufficient_balance"
    assert "余额不足" in failed.replies[0]
    user = snapshot("85259990003")
    assert user.get("offers") in (None, [])
    assert user["balance"] == 3.2


def test_boss_timeout_does_not_subscribe():
    reset_runtime()
    store.reset()
    handle_mo("85259990004", "OFFER")
    handle_mo("85259990004", "1")
    failed = handle_mo("85259990004", "Y")
    assert failed.trace.tools == ["subscribe_offer"]
    assert failed.trace.fallback_reason == "boss_timeout"
    assert "系统繁忙" in failed.replies[0]
    user = snapshot("85259990004")
    assert user.get("offers") in (None, [])
    assert user["balance"] == 200


def test_query_offers_timeout_never_enters_select():
    reset_runtime()
    store.reset()
    from app.tools import _users

    _users()["85259990001"]["faults"] = {"query_offerable_offers": "boss_timeout"}
    out = handle_mo("85259990001", "OFFER")
    assert out.session_state == "idle"
    assert "query_offerable_offers" in out.trace.tools
    assert "系统繁忙" in out.replies[0]
    assert snapshot("85259990001").get("offers") in (None, [])


def test_classify_clamps_illegal_intent():
    intent, why = clamp_classify_intent("subscribe_offer")
    assert intent == "out_of_scope" and why == "illegal_intent"
    ok, why_ok = clamp_classify_intent("query_balance")
    assert ok == "query_balance" and why_ok is None
    custom, why_c = clamp_classify_intent("query_game_points")
    assert custom == "query_game_points" and why_c is None
    junk = parse_json('{"intent": "delete_subscriber", "slots": {}}')
    clamped, reason = clamp_classify_intent(junk["intent"])
    assert clamped == "out_of_scope" and reason == "illegal_intent"
