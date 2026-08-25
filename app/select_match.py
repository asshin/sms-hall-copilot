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
    ordinal = _ordinal(raw, by_index)
    if ordinal:
        return ordinal
    named = _named(raw, items)
    if named:
        return named

    if use_llm is False or (use_llm is None and not settings.llm_enabled):
        return _miss("no_rule_match")
    return _llm_select(raw, items)


def _miss(reason: str) -> dict[str, Any]:
    return {"ok": False, "index": None, "item": None, "source": "none", "reason": reason, "confidence": 0.0}


def _hit(item: dict[str, Any], source: str, confidence: float) -> dict[str, Any]:
    return {"ok": True, "index": int(item["index"]), "item": item, "source": source, "reason": None, "confidence": confidence}


def _digit(raw: str, by_index: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    token = re.sub(r"\s+", "", raw)
    m = re.fullmatch(r"(?:编号)?(\d{1,2})(?:号|项|\.|．)?", token)
    if not m:
        return None
    idx = int(m.group(1))
    item = by_index.get(idx)
    return _hit(item, "rule", 1.0) if item else _miss("index_out_of_range")


def _ordinal(raw: str, by_index: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    compact = re.sub(r"\s+", "", raw)
    if compact in {"最后", "最后一个", "last"}:
        if not by_index:
            return None
        item = by_index[max(by_index)]
        return _hit(item, "heuristic", 0.92)
    # longest ordinal first
    for key in sorted(_ORDINAL, key=len, reverse=True):
        if key in compact:
            item = by_index.get(_ORDINAL[key])
            return _hit(item, "heuristic", 0.9) if item else _miss("index_out_of_range")
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
    exact: list[dict[str, Any]] = []
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        names = [_normalize(str(item.get("zh") or "")), _normalize(str(item.get("en") or "")), _normalize(str(item.get("id") or ""))]
        names.extend(_normalize(a) for a in item.get("aliases") or [])
        if needle in names or any(needle == n for n in names):
            exact.append(item)
            continue
        score = 0
        for n in names:
            if not n:
                continue
            if needle in n or n in needle:
                score = max(score, 80 if min(len(needle), len(n)) >= 4 else 60)
            overlap = _char_overlap(needle, n)
            score = max(score, overlap)
        if score:
            scored.append((score, item))
    if len(exact) == 1:
        return _hit(exact[0], "heuristic", 0.95)
    if len(exact) > 1:
        return _miss("ambiguous")
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None
    best, item = scored[0]
    tied = [s for s in scored if s[0] == best]
    if len(tied) > 1:
        return _miss("ambiguous")
    if best >= 70:
        return _hit(item, "heuristic", min(0.9, best / 100))
    return None


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
