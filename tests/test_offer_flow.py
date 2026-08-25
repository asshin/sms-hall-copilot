from app.boss import load_offers
from app.engine import handle_mo
from app.select_match import match_select
from app.session import store
from app.tools import reset_runtime, snapshot


def _items():
    return load_offers()


def test_select_digit_and_ordinal():
    items = _items()
    d = match_select("1", items, use_llm=False)
    assert d["ok"] and d["index"] == 1 and d["source"] == "rule"
    o = match_select("第一个", items, use_llm=False)
    assert o["ok"] and o["index"] == 1 and o["source"] == "heuristic"
    last = match_select("最后一个", items, use_llm=False)
    assert last["ok"] and last["index"] == 8


def test_select_name_and_typo_liucheng():
    items = _items()
    exact = match_select("50G本地流量", items, use_llm=False)
    assert exact["ok"] and exact["item"]["id"] == "OFF_50G_LOCAL"
    typo = match_select("50G本地流程", items, use_llm=False)
    assert typo["ok"] and typo["item"]["id"] == "OFF_50G_LOCAL"
    miss = match_select("天气怎么样", items, use_llm=False)
    assert miss["ok"] is False


def test_offer_flow_number_then_confirm():
    reset_runtime()
    store.reset()
    listed = handle_mo("85259990001", "OFFER")
    assert listed.trace.intent == "browse_offers"
    assert listed.trace.tools == ["query_language", "query_offerable_offers"]
    assert listed.session_state == "awaiting_select"
    assert "50G本地流量" in "".join(listed.replies)
    picked = handle_mo("85259990001", "1")
    assert picked.trace.confirm_required is True
    assert picked.trace.intent == "subscribe_offer"
    assert picked.trace.tools == []
    done = handle_mo("85259990001", "Y")
    assert done.trace.tools == ["subscribe_offer"]
    assert "50G" in done.replies[0]
    user = snapshot("85259990001")
    assert "OFF_50G_LOCAL" in (user.get("offers") or [])


def test_offer_flow_ordinal_and_typo_name():
    reset_runtime()
    store.reset()
    handle_mo("85259990001", "OFFER")
    first = handle_mo("85259990001", "第一个")
    assert first.trace.confirm_required is True
    handle_mo("85259990001", "N")

    handle_mo("85259990001", "OFFER")
    typo = handle_mo("85259990001", "50G本地流程")
    assert typo.trace.intent == "subscribe_offer"
    assert "50G" in "".join(typo.replies)
    done = handle_mo("85259990001", "Y")
    assert done.trace.tools == ["subscribe_offer"]


def test_offer_select_unknown_stays_in_session():
    reset_runtime()
    store.reset()
    handle_mo("85259990001", "OFFER")
    miss = handle_mo("85259990001", "天气")
    assert miss.trace.intent == "need_select"
    assert miss.session_state == "awaiting_select"
    assert miss.trace.tools == []
