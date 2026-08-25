from __future__ import annotations

import json
import re
from typing import Any

from app.config import settings

_TYPOS = (
    ("流程", "流量"),
    ("流星", "流量"),
    ("本地流", "本地流"),
)

_ORDINAL = {
    "第一": 1,
    "第一个": 1,
    "第一项": 1,
    "第二": 2,
    "第二个": 2,
    "第三": 3,
    "第三个": 3,
    "第四": 4,
    "第四个": 4,
    "第五": 5,
    "第五个": 5,
    "第六": 6,
    "第六个": 6,
    "第七": 7,
    "第七个": 7,
    "第八": 8,
    "第八个": 8,
}

SELECT_SYSTEM = """You map one HarborTel SMS to ONE item in the current offer list.
Return ONLY JSON: {"index": 1, "confidence": 0.0}
index must be one of the provided indexes, or null if unrelated/ambiguous.
The user may type a number, 第一个, a tariff name, or a typo (流程→流量).
Never invent an offer that is not in the list. Never return an index outside the list.
"""


def match_select(text: str, items: list[dict[str, Any]], *, use_llm: bool | None = None) -> dict[str, Any]:
    """Constrained list alignment. Digit/ordinal/name first; LLM only as a fallback."""
    raw = (text or "").strip()
    if not items or not raw:
        return _miss("empty")
    by_index = {int(i["index"]): i for i in items}

    digit = _digit(raw, by_index)
    if digit:
        return digit
    ordinal = _ordinal(raw, items)
    if ordinal:
        return ordinal
    named = _named(raw, items)
    if named:
        return named

    if use_llm is False or (use_llm is None and not settings.llm_enabled):
        return _miss("no_rule_match")
    return _llm_select(raw, items)


def _miss(reason: str, candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "index": None,
        "item": None,
        "source": "none",
        "reason": reason,
        "confidence": 0.0,
        "candidates": list(candidates or []),
    }


def _hit(item: dict[str, Any], source: str, confidence: float) -> dict[str, Any]:
    return {
        "ok": True,
        "index": int(item["index"]),
        "item": item,
        "source": source,
        "reason": None,
        "confidence": confidence,
        "candidates": [],
    }


def _digit(raw: str, by_index: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    token = re.sub(r"\s+", "", raw)
    m = re.fullmatch(r"(?:编号)?(\d{1,2})(?:号|项|\.|．)?", token)
    if not m:
        return None
    idx = int(m.group(1))
    item = by_index.get(idx)
    return _hit(item, "rule", 1.0) if item else _miss("index_out_of_range")


def _ordinal(raw: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """第N个 / 最后 = current visible list order, not the original full catalog."""
    ordered = sorted(items, key=lambda i: int(i["index"]))
    if not ordered:
        return None
    compact = re.sub(r"\s+", "", raw)
    if compact in {"最后", "最后一个", "last"}:
        return _hit(ordered[-1], "heuristic", 0.92)
    for key in sorted(_ORDINAL, key=len, reverse=True):
        if key in compact:
            pos = _ORDINAL[key]
            if 1 <= pos <= len(ordered):
                return _hit(ordered[pos - 1], "heuristic", 0.9)
            return _miss("index_out_of_range")
    return None


def _normalize(text: str) -> str:
    out = re.sub(r"\s+", "", text).casefold()
    for src, dst in _TYPOS:
        out = out.replace(src, dst)
    return out


def _named(raw: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = _normalize(raw)
    if len(needle) < 2:
        return None
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        score = _name_score(needle, item)
        if score >= 70:
            scored.append((score, item))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], int(x[1]["index"])))
    exact = [it for s, it in scored if s >= 100]
    if len(scored) == 1:
        src_score = scored[0][0]
        return _hit(scored[0][1], "heuristic", 0.95 if src_score >= 100 else min(0.9, src_score / 100))
    if len(exact) > 1 or len(scored) > 1:
        return _miss("ambiguous", _sort_items([it for _, it in scored]))
    return None


def _name_score(needle: str, item: dict[str, Any]) -> int:
    names = [_normalize(str(item.get("zh") or "")), _normalize(str(item.get("en") or "")), _normalize(str(item.get("id") or ""))]
    names.extend(_normalize(a) for a in item.get("aliases") or [])
    score = 0
    for n in names:
        if not n:
            continue
        if needle == n:
            score = max(score, 100)
        elif needle in n or n in needle:
            score = max(score, 80 if min(len(needle), len(n)) >= 4 else 60)
        score = max(score, _char_overlap(needle, n))
    return score


def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda i: int(i["index"]))


def _char_overlap(a: str, b: str) -> int:
    if not a or not b:
        return 0
    shared = sum(1 for ch in set(a) if ch in b and not ch.isdigit())
    digits = "".join(ch for ch in a if ch.isdigit())
    if digits and digits in b:
        shared += 4
    ratio = shared / max(len(set(a)), 1)
    return int(ratio * 70)


def _llm_select(raw: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from app.llm import complete_json

        payload = {
            "sms": raw,
            "offers": [{"index": i["index"], "zh": i["zh"], "en": i["en"], "id": i["id"]} for i in items],
        }
        data, _usage = complete_json(SELECT_SYSTEM, json.dumps(payload, ensure_ascii=False))
        idx = data.get("index")
        if idx is None:
            return _miss("llm_null")
        item = next((i for i in items if int(i["index"]) == int(idx)), None)
        if not item:
            return _miss("llm_out_of_list")
        return _hit(item, "llm", float(data.get("confidence") or 0.7))
    except Exception:  # noqa: BLE001
        return _miss("llm_error")
