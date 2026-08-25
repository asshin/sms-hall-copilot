from app.catalog import remove_command
from app.config_assist import apply_approved_draft, draft_config
from app.matcher import match_rule
from app.tools import reset_runtime


def test_stop_conflict_is_reassigned_not_applied():
    reset_runtime()
    out = draft_config(
        "预付费用户发送 STOP 暂停本地和漫游数据，需要 Y 确认。对接 CRM 暂停接口。",
        force_heuristic=True,
    )
    assert out["apply"] is False
    assert out["draft"]["intent"] == "pause_data"
    assert out["draft"]["confirm"] is True
    assert out["draft"]["requested_code"] == "STOP"
    assert out["draft"]["command_code"] != "STOP"
    assert out["draft"]["conflict"]["code"] == "STOP"
    assert "crm_endpoint_not_in_knowledge" in out["unknowns"]
    assert out["verdict"] == "needs_human_review"
    assert out["steps"][0]["id"] == "retrieve_knowledge"


def test_language_draft_no_confirm():
    out = draft_config("增加隐性指令 EN2 把短信切成英文", force_heuristic=True)
    assert out["draft"]["intent"] == "set_language"
    assert out["draft"]["confirm"] is False
    assert out["apply"] is False


def test_voucher_draft_is_prepaid_and_confirmed():
    out = draft_config("预付费充值卡业务，用户发卡密办理", force_heuristic=True)
    assert out["draft"]["intent"] == "voucher_topup"
    assert out["draft"]["confirm"] is True
    assert out["draft"]["plans"] == ["prepaid"]


def test_apply_blocked_unknown_is_rejected():
    out = draft_config("给用户开通游戏积分转账 YXZC 对接 CRM", force_heuristic=True)
    assert out["verdict"] == "blocked"
    res = apply_approved_draft(out, acknowledged=True)
    assert res["ok"] is False
    assert res["error"] == "blocked_or_unknown"


def test_crm_unknowns_require_ack_then_write():
    out = draft_config("预付费发送 PAUSZ 暂停数据并对接 CRM", force_heuristic=True)
    assert out["verdict"] == "needs_human_review"
    denied = apply_approved_draft(out, acknowledged=False)
    assert denied["ok"] is False
    assert denied["error"] == "need_ack"
    code = out["draft"]["command_code"]
    try:
        ok = apply_approved_draft(out, acknowledged=True)
        assert ok["ok"] is True
        assert match_rule(code, {"plan": "prepaid"}).intent == "pause_data"
    finally:
        remove_command(code)


def test_registered_game_points_is_not_unknown():
    out = draft_config("发送 GPNT查询用户游戏积分", force_heuristic=True)
    assert out["draft"]["intent"] == "query_game_points"
    assert out["draft"]["command_code"] == "GPNT"
    assert out["verdict"] == "already_configured"
    assert out["can_apply"] is False
    assert apply_approved_draft(out, acknowledged=True)["error"] == "already_configured"


def test_human_ack_writes_catalog_and_matcher_hits():
    out = draft_config("增加隐性指令 ZZLANG 把短信切成英文", force_heuristic=True)
    assert out["can_apply"] is True
    denied = apply_approved_draft(out, acknowledged=False)
    assert denied["error"] == "need_ack"
    code = out["draft"]["command_code"]
    try:
        res = apply_approved_draft(out, acknowledged=True)
        assert res["ok"] is True
        plan = match_rule(code, {"plan": "prepaid"})
        assert plan is not None
        assert plan.intent == "set_language"
    finally:
        remove_command(code)
