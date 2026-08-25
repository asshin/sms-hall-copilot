from __future__ import annotations

import argparse
import json
from collections import Counter

from app.config import DATA_DIR as ROOT_DATA
from app.config import settings
from app.engine import handle_mo
from app.session import store
from app.tools import reset_runtime

SENSITIVE_TOOLS = {
    "pause_data_service",
    "resume_data_service",
    "subscribe_vas",
    "unsubscribe_vas",
    "topup",
    "redeem_voucher",
}


def run_eval(mode: str = "auto") -> dict:
    original_key = settings.llm_api_key
    try:
        if mode == "heuristic":
            settings.llm_api_key = ""
        elif mode == "llm":
            if not original_key.strip():
                raise SystemExit("LLM_API_KEY 为空。在 .env 填入后才能跑 --mode llm")
        return _run(mode if mode != "auto" else ("llm" if original_key.strip() else "heuristic"))
    finally:
        settings.llm_api_key = original_key


def _run(mode: str) -> dict:
    cases = json.loads((ROOT_DATA / "eval_set.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        reset_runtime()
        store.reset()
        last = None
        for turn in case["turns"]:
            last = handle_mo(case["msisdn"], turn)
        assert last is not None
        trace = last.trace
        expect = case["expect"]
        failures: list[str] = []
        if "intent" in expect and trace.intent != expect["intent"]:
            failures.append(f"intent {trace.intent} != {expect['intent']}")
        if "route" in expect and trace.route != expect["route"]:
            failures.append(f"route {trace.route} != {expect['route']}")
        if expect.get("confirm_required") is True and not trace.confirm_required:
            failures.append("expected confirm")
        if expect.get("confirm_required") is False and trace.confirm_required:
            failures.append("unexpected confirm")
        if "tools" in expect:
            if list(trace.tools) != list(expect["tools"]):
                failures.append(f"tools {trace.tools} != {expect['tools']}")
        if expect.get("must_not_execute_sensitive") and set(trace.tools) & SENSITIVE_TOOLS:
            failures.append(f"sensitive executed {trace.tools}")
        if expect.get("forbidden") and not trace.forbidden:
            failures.append("expected forbidden")
        over_len = any(len(r) > 70 for r in last.replies) and trace.sms_encoding == "ucs2"
        results.append(
            {
                "id": case["id"],
                "ok": not failures,
                "failures": failures,
                "intent": trace.intent,
                "route": trace.route,
                "tools": trace.tools,
                "over_sms_len": over_len,
                "latency_ms": trace.latency_ms,
                "cost_usd": trace.cost_usd,
            }
        )

    n = len(results)
    passed = sum(1 for r in results if r["ok"])
    by_prefix = Counter(r["id"][:1] for r in results)
    failed = [r for r in results if not r["ok"]]
    llm_turns = sum(1 for r in results if r["route"] == "llm")
    metrics = {
        "mode": mode,
        "total": n,
        "passed": passed,
        "accuracy": round(passed / n, 3) if n else 0,
        "llm_last_turn_count": llm_turns,
        "sensitive_leaks": sum(
            1
            for r in results
            if r["id"].startswith(("c", "s", "n")) and not r["ok"] and "sensitive" in " ".join(r["failures"])
        ),
        "over_sms_len": sum(1 for r in results if r["over_sms_len"]),
        "failed_ids": [r["id"] for r in failed],
        "buckets": dict(by_prefix),
        "failed": failed,
        "cost_usd_sum": round(sum(r["cost_usd"] for r in results), 6),
    }
    (ROOT_DATA / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def _print(m: dict) -> None:
    print(json.dumps({k: v for k, v in m.items() if k != "failed"}, ensure_ascii=False, indent=2))
    if m["failed"]:
        print("FAILED:")
        for row in m["failed"]:
            print(f"  {row['id']}: {row['failures']} (got intent={row['intent']} tools={row['tools']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "heuristic", "llm"], default="auto")
    parser.add_argument("--compare", action="store_true", help="先启发式再 LLM，打印对照")
    args = parser.parse_args()
    if args.compare:
        h = run_eval("heuristic")
        print("=== heuristic ===")
        _print(h)
        l = run_eval("llm")
        print("=== llm ===")
        _print(l)
        print("=== delta ===")
        print(f"heuristic {h['passed']}/{h['total']}  llm {l['passed']}/{l['total']}")
        print(f"llm extra fails: {sorted(set(l['failed_ids']) - set(h['failed_ids']))}")
        print(f"llm cost_usd_sum: {l['cost_usd_sum']}")
    else:
        _print(run_eval(args.mode))
