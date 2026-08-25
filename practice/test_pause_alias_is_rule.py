
from app.matcher import match_rule, normalize
def test_pause_alias_is_rule():
    plan = match_rule("PAUSE", {"plan": "prepaid"})
    assert plan is not None
    assert plan.source == "rule"
    assert plan.intent == "pause_data"
    assert plan.confirm is True