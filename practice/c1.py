import sys
from pathlib import Path

# 练习脚本不在项目根目录时，必须把根目录加入查找路径，否则 from app.xxx 会失败
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.matcher import match_rule, normalize

print("normalize:", normalize("  bal  "))

plan = match_rule("BAL", {})
print("BAL intent:", None if plan is None else plan.intent)
print("BAL source:", None if plan is None else plan.source)

plan2 = match_rule("帮我查话费", {})
print("口语:", plan2)

from app.models import IntentPlan
IntentPlan(intent="pause_data", source="rule")
IntentPlan(intent="pause_data", source="xxx")   # 应报校验错误


def test_exact_command_is_rule():
    plan = match_rule("BAL", {"plan": "prepaid"})
    assert plan is not None
    assert plan.source == "rule"
    assert plan.intent == "query_balance"