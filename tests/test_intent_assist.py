from app.catalog import remove_command
from app.config_assist import apply_approved_draft
from app.engine import handle_mo
from app.intent_assist import draft_intent_from_api
from app.intents_registry import get_intent, remove_intent
from app.matcher import match_rule
from app.session import store
from app.tools import reset_runtime


def _cleanup(code: str, intent_id: str) -> None:
    remove_command(code)
    remove_intent(intent_id)


def test_blank_schema_is_blocked():
    out = draft_intent_from_api("查询积分", "", "", force_heuristic=True)
    assert out["verdict"] == "blocked"
    assert out["can_apply"] is False
    assert apply_approved_draft(out, acknowledged=True)["ok"] is False


def test_query_api_generates_intent_and_sms():
    out = draft_intent_from_api(
        "查询用户停车积分，预付费和后付费均可，无需确认。指令码 PARKX。",
        '{"msisdn":"string","lot_id":"P01"}',
        '{"ok":true,"points":80,"lot_id":"P01"}',
        "PARKX",
        force_heuristic=True,
    )
    assert out["kind"] == "new_intent"
    assert out["draft"]["intent"] == "query_parking_points"
    assert out["draft"]["confirm"] is False
    assert out["draft"]["command_code"] == "PARKX"
    assert "points" in out["draft"]["mock_result"]
    denied = apply_approved_draft(out, acknowledged=False)
    assert denied["error"] == "need_ack"
    code = out["draft"]["command_code"]
    intent_id = out["draft"]["intent"]
    try:
        ok = apply_approved_draft(out, acknowledged=True)
        assert ok["ok"] is True
        assert get_intent(intent_id) is not None
        plan = match_rule(code, {"plan": "prepaid"})
        assert plan is not None and plan.intent == intent_id
        reset_runtime()
        store.reset()
        turn = handle_mo("85259990001", code)
        assert turn.trace.intent == intent_id
        assert turn.trace.confirm_required is False
        assert "80" in turn.replies[0]
        spoken = handle_mo("85259990001", "查一下停车积分")
        assert spoken.trace.intent == intent_id
    finally:
        _cleanup(code, intent_id)


def test_mutate_api_requires_confirm():
    out = draft_intent_from_api(
        "开通来电名片，写接口，需要 Y 确认。指令码 NCRD。",
        '{"msisdn":"string"}',
        '{"ok":true,"status":"active"}',
        "NCRD",
        force_heuristic=True,
    )
    assert out["draft"]["intent_kind"] == "mutate"
    assert out["draft"]["confirm"] is True
    code = out["draft"]["command_code"]
    intent_id = out["draft"]["intent"]
    try:
        assert apply_approved_draft(out, acknowledged=True)["ok"] is True
        reset_runtime()
        store.reset()
        first = handle_mo("85259990001", code)
        assert first.trace.confirm_required is True
        done = handle_mo("85259990001", "Y")
        assert done.trace.intent == intent_id
        assert "active" in done.replies[0] or "办理" in done.replies[0] or "status" in done.replies[0]
    finally:
        _cleanup(code, intent_id)
