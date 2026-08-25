from app.config_assist import draft_config
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
