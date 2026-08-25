from app.matcher import match_rule
from app.policy import forbid_reason
from app.sms import encoding_for, split_sms


def test_chinese_sms_uses_ucs2_and_70():
    parts = split_sms("将暂停本地及漫游数据，回复 Y 确认，N 取消。")
    assert encoding_for(parts[0]) == "ucs2"
    assert all(len(p) <= 70 for p in parts)


def test_exact_command_is_rule():
    plan = match_rule("BAL", {"plan": "prepaid"})
    assert plan is not None
    assert plan.source == "rule"
    assert plan.intent == "query_balance"


def test_postpaid_cannot_pause():
    reason = forbid_reason("pause_data", {"plan": "postpaid", "data_paused": False, "vas": []})
    assert reason == "postpaid_no_pause"
