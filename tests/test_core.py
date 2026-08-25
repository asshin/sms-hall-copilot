from app.engine import handle_mo
from app.matcher import match_rule
from app.policy import forbid_reason
from app.session import store
from app.sms import encoding_for, split_sms
from app.tools import reset_runtime


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


def test_en_zh_are_rule_commands():
    en = match_rule("EN", {"plan": "prepaid"})
    zh = match_rule("zh", {"plan": "postpaid"})
    assert en is not None and en.intent == "set_language" and en.slots.get("lang") == "en"
    assert zh is not None and zh.intent == "set_language" and zh.slots.get("lang") == "zh"
    assert en.confirm is False


def test_en_then_balance_replies_in_english():
    reset_runtime()
    store.reset()
    switched = handle_mo("85259990001", "EN")
    assert switched.trace.tools == ["set_language"]
    assert "Language set to English." in switched.replies[0]
    billed = handle_mo("85259990001", "BAL")
    assert "Balance" in billed.replies[0]


def test_voucher_code_is_rule_with_pin():
    plan = match_rule("V88888888", {"plan": "prepaid"})
    assert plan is not None
    assert plan.source == "rule"
    assert plan.intent == "voucher_topup"
    assert plan.slots.get("pin") == "88888888"
    assert plan.confirm is True


def test_voucher_redeem_then_balance():
    reset_runtime()
    store.reset()
    first = handle_mo("85259990001", "V88888888")
    assert first.trace.confirm_required is True
    assert first.trace.tools == []
    done = handle_mo("85259990001", "Y")
    assert done.trace.tools == ["redeem_voucher"]
    assert "50" in done.replies[0]
    bal = handle_mo("85259990001", "BAL")
    assert "238.5" in bal.replies[0]
