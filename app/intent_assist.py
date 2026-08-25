from __future__ import annotations

import json
import re
from typing import Any

from app.catalog import commands_by_code
from app.config import settings
from app.config_assist import _allocate_code, _normalize_code
from app.intents_registry import append_intent, get_intent, intent_ids, remove_intent
from app.tools import INTENT_TOOL

RESERVED = set(INTENT_TOOL) | {
    "show_menu",
    "out_of_scope",
    "unknown",
    "cancel",
    "unknown_user",
}

MUTATE_HINTS = ("开通", "关闭", "办理", "订购", "退订", "暂停", "恢复", "充值", "转账", "扣", "变更", "设置", "update", "set ", "write", "subscribe", "transfer")
QUERY_HINTS = ("查询", "query", "get", "余额", "状态", "剩余")

PROPOSE_SYSTEM = """You draft a HarborTel SMS-hall INTENT from an API contract.
Return ONLY JSON:
{
  "intent": "query_game_points",
  "kind": "query",
  "command_code": "GPNT",
  "confirm": false,
  "plans": ["prepaid","postpaid"],
  "keywords": ["游戏积分"],
  "success_sms_zh": "游戏积分 {points}。",
  "success_sms_en": "Game points {points}.",
  "fail_sms_zh": "查询失败，请稍后重试。",
  "fail_sms_en": "Failed. Please try later.",
  "mock_result": {"ok": true, "points": 1200},
  "api_name": "QueryGamePoints"
}
Rules:
- intent: snake_case, start with letter, 3-48 chars. query_* for reads, do_* / subscribe_* for writes.
- kind is query or mutate. mutate MUST confirm=true.
- Do not invent HTTP URLs. api_name is a contract id only.
- success templates may use response field placeholders like {points}.
- mock_result must include ok=true and sample values for response fields.
"""


def draft_intent_from_api(
    description: str,
    request_schema: str,
    response_schema: str,
    command_code: str = "",
    force_heuristic: bool = False,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    desc = (description or "").strip()
    req, req_err = parse_schema(request_schema)
    resp, resp_err = parse_schema(response_schema)
    steps.append({"id": "parse_schema", "ok": not req_err and not resp_err, "request_error": req_err, "response_error": resp_err})

    checks = _schema_checks(desc, req, resp, req_err, resp_err)
    proposal, source, usage = _propose(desc, req, resp, command_code, force_heuristic=force_heuristic)
    steps.append({"id": "propose", "ok": True, "source": source, "intent": proposal.get("intent")})

    kind = proposal.get("kind") if proposal.get("kind") in {"query", "mutate"} else _kind_from(desc)
    proposed_id = str(proposal.get("intent") or "")
    if not _valid_new_intent(proposed_id):
        proposed_id = _intent_id(desc, kind, command_code)
    intent_id = _unique_intent_id(proposed_id)
    confirm = kind == "mutate" or bool(proposal.get("confirm"))
    if kind == "mutate":
        confirm = True
    if kind == "query" and any(k in desc for k in ("需要确认", "Y确认", "回复Y")):
        confirm = True
    if kind == "query" and any(k in desc for k in ("无需确认", "不用确认", "不需要确认")):
        confirm = False

    plans = _plans(desc, proposal.get("plans"))
    occupied = commands_by_code()
    requested = _normalize_code(command_code or proposal.get("command_code") or "")
    assigned, conflict = _allocate_code(requested, intent_id, occupied)

    default_slots = _default_slots(req)
    mock_result = proposal.get("mock_result") if isinstance(proposal.get("mock_result"), dict) else {}
    mock_result = {"ok": True, **_sample_from_schema(resp), **{k: v for k, v in mock_result.items() if k != "ok"}}
    mock_result["ok"] = True

    sms_zh = str(proposal.get("success_sms_zh") or _sms_zh(desc, resp, kind))
    sms_en = str(proposal.get("success_sms_en") or _sms_en(desc, resp, kind))
    keywords = proposal.get("keywords") if isinstance(proposal.get("keywords"), list) else _keywords(desc)

    checks.extend(_intent_checks(intent_id, kind, confirm, req, resp))
    steps.append({"id": "apply_policy", "ok": all(c["ok"] for c in checks), "n": len(checks)})

    unknowns: list[str] = []
    if re.search(r"(CRM|BCOC|接口|API)", desc, re.I):
        unknowns.append("external_api_mocked_only")
    if conflict:
        unknowns.append("command_reassigned")

    api_name = str(proposal.get("api_name") or _api_name(intent_id))
    draft = {
        "kind": "new_intent",
        "intent": intent_id,
        "intent_kind": kind,
        "command_code": assigned,
        "requested_code": requested or None,
        "hidden": True,
        "confirm": confirm,
        "confirm_rounds": 1 if confirm else 0,
        "plans": plans,
        "slots": default_slots,
        "keywords": [str(k) for k in keywords if k][:8],
        "api": {
            "name": api_name,
            "mock": True,
            "request": req,
            "response": resp,
        },
        "mock_result": mock_result,
        "success_sms_zh": sms_zh,
        "success_sms_en": sms_en,
        "fail_sms_zh": str(proposal.get("fail_sms_zh") or "办理失败，请稍后重试。"),
        "fail_sms_en": str(proposal.get("fail_sms_en") or "Failed. Please try later."),
        "description": desc[:120],
        "conflict": None,
    }
    if conflict:
        draft["conflict"] = {
            **conflict,
            "resolved_to": assigned,
            "message": f"{conflict['code']} 已被占用，已改派 {assigned}。",
        }

    verdict = "blocked" if any(not c["ok"] for c in checks) else ("needs_human_review" if unknowns else "ready_to_copy")
    steps.append({"id": "verdict", "ok": verdict != "blocked", "verdict": verdict})

    return {
        "kind": "new_intent",
        "apply": False,
        "can_apply": verdict != "blocked",
        "verdict": verdict,
        "verdict_reason": _reason(verdict, unknowns, conflict),
        "draft": draft,
        "checks": checks,
        "unknowns": unknowns,
        "steps": steps,
        "propose_source": source,
        "usage": usage,
    }


def apply_intent_draft(payload: dict[str, Any], *, acknowledged: bool) -> dict[str, Any]:
    from app.catalog import append_command, commands_by_code

    verdict = payload.get("verdict")
    draft = payload.get("draft") or {}
    if draft.get("kind") != "new_intent":
        return {"ok": False, "error": "not_intent_draft", "message": "这不是新增意图草案。"}
    if verdict == "blocked":
        return {"ok": False, "error": "blocked_or_unknown", "message": "策略未通过，不能写入。"}
    if not acknowledged:
        return {"ok": False, "error": "need_ack", "message": "请先勾选已人工检查，再确认写入。"}

    intent_id = str(draft.get("intent") or "")
    code = str(draft.get("command_code") or "").upper()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,47}", intent_id) or intent_id in RESERVED or get_intent(intent_id):
        return {"ok": False, "error": "bad_intent", "message": "意图名不合法或已存在。"}
    if not code or not re.fullmatch(r"[A-Z0-9]{2,10}", code):
        return {"ok": False, "error": "bad_code", "message": "指令码不合法。"}
    if code in commands_by_code():
        return {"ok": False, "error": "conflict", "message": f"{code} 已被占用。"}

    spec = {
        "id": intent_id,
        "kind": draft.get("intent_kind") or "query",
        "description": draft.get("description") or intent_id,
        "confirm": bool(draft.get("confirm")),
        "plans": list(draft.get("plans") or ["prepaid", "postpaid"]),
        "keywords": list(draft.get("keywords") or []),
        "default_slots": dict(draft.get("slots") or {}),
        "api": draft.get("api") or {"name": intent_id, "mock": True, "request": {}, "response": {}},
        "mock_result": dict(draft.get("mock_result") or {"ok": True}),
        "success_sms_zh": draft.get("success_sms_zh") or "办理完成。",
        "success_sms_en": draft.get("success_sms_en") or "Done.",
        "fail_sms_zh": draft.get("fail_sms_zh") or "办理失败，请稍后重试。",
        "fail_sms_en": draft.get("fail_sms_en") or "Failed. Please try later.",
        "command_code": code,
    }
    command = {
        "code": code,
        "intent": intent_id,
        "hidden": True,
        "confirm": bool(draft.get("confirm")),
        "plans": list(spec["plans"]),
    }
    if spec["default_slots"]:
        command["slots"] = spec["default_slots"]

    append_intent(spec)
    try:
        append_command(command)
    except Exception:
        remove_intent(intent_id)
        raise
    return {
        "ok": True,
        "applied": True,
        "command": command,
        "intent": spec,
        "message": f"已写入意图 {intent_id} 与指令 {code}。短厅页立刻可测。",
    }


def parse_schema(raw: str) -> tuple[dict[str, Any], str | None]:
    text = (raw or "").strip()
    if not text:
        return {}, "empty"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        parsed: dict[str, Any] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip().strip("\"'")
            if key:
                parsed[key] = val.strip().strip(",\"'")
        if parsed:
            return parsed, None
        return {}, "invalid_json"
    if isinstance(data, dict):
        return data, None
    if isinstance(data, list):
        out: dict[str, Any] = {}
        for item in data:
            if isinstance(item, dict) and item.get("name"):
                out[str(item["name"])] = item.get("type") or item.get("example") or "string"
        return out, None if out else "empty"
    return {}, "not_object"


def _propose(
    desc: str,
    req: dict[str, Any],
    resp: dict[str, Any],
    command_code: str,
    force_heuristic: bool,
) -> tuple[dict[str, Any], str, dict[str, int]]:
    heuristic = _heuristic_propose(desc, req, resp, command_code)
    if force_heuristic or not settings.llm_enabled:
        return heuristic, "heuristic", {"prompt": 0, "completion": 0}
    try:
        from app.llm import complete_json

        data, usage = complete_json(
            PROPOSE_SYSTEM,
            json.dumps(
                {"description": desc, "request": req, "response": resp, "command_code": command_code},
                ensure_ascii=False,
            ),
        )
        if isinstance(data, dict) and _valid_new_intent(str(data.get("intent") or "")):
            merged = {**heuristic, **{k: v for k, v in data.items() if v not in (None, "", [])}}
            if str(merged.get("kind") or "") not in {"query", "mutate"}:
                merged["kind"] = heuristic["kind"]
            return merged, "llm", usage
        return heuristic, "llm_invalid_fallback", usage
    except Exception as exc:  # noqa: BLE001
        heuristic["_fallback"] = type(exc).__name__
        return heuristic, "llm_error_fallback", {"prompt": 0, "completion": 0}


def _heuristic_propose(desc: str, req: dict[str, Any], resp: dict[str, Any], command_code: str) -> dict[str, Any]:
    kind = _kind_from(desc)
    code_match = re.search(r"\b([A-Z]{2,8})\b", (command_code or desc).upper())
    code = command_code.upper() if command_code else (code_match.group(1) if code_match else "")
    intent = _intent_id(desc, kind, code)
    return {
        "intent": intent,
        "kind": kind,
        "command_code": code,
        "confirm": kind == "mutate",
        "plans": _plans(desc, None),
        "keywords": _keywords(desc),
        "success_sms_zh": _sms_zh(desc, resp, kind),
        "success_sms_en": _sms_en(desc, resp, kind),
        "mock_result": {"ok": True, **_sample_from_schema(resp)},
        "api_name": _api_name(intent),
    }


def _kind_from(desc: str) -> str:
    low = desc.lower()
    if any(k in desc or k in low for k in QUERY_HINTS) and not any(k in desc for k in ("转账", "扣")):
        return "query"
    if any(k in desc or k in low for k in MUTATE_HINTS):
        return "mutate"
    return "query"


def _intent_id(desc: str, kind: str, code: str) -> str:
    prefix = "query_" if kind == "query" else "do_"
    stem = ""
    mapping = (
        ("游戏积分", "game_points"),
        ("停车积分", "parking_points"),
        ("积分", "points"),
        ("来电名片", "namecard"),
        ("名片", "namecard"),
        ("停机", "suspend"),
        ("复机", "restore"),
    )
    for cn, en in mapping:
        if cn in desc:
            stem = en
            break
    if not stem:
        words = re.findall(r"[a-zA-Z]{3,}", desc)
        stem = "_".join(w.lower() for w in words[:3])
    if not stem:
        stem = (code or "api").lower()
    raw = re.sub(r"[^a-z0-9_]+", "_", prefix + stem).strip("_")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,47}", raw):
        raw = prefix + (code or "api").lower()
    return raw[:48]


def _valid_new_intent(name: str) -> bool:
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,47}", name or ""):
        return False
    if name in RESERVED:
        return False
    banned = ("out_of_scope", "unknown", "show_menu", "cancel", "unknown_user")
    return not any(name == p or name.startswith(p + "_") for p in banned)


def _unique_intent_id(base: str) -> str:
    taken = RESERVED | intent_ids()
    if base not in taken:
        return base
    for i in range(2, 30):
        cand = f"{base}_{i}"[:48]
        if cand not in taken:
            return cand
    return f"{base}_x"


def _plans(desc: str, proposed: Any) -> list[str]:
    if isinstance(proposed, list) and proposed:
        got = [p for p in proposed if p in {"prepaid", "postpaid"}]
        if got:
            return got
    if "后付" in desc and "预付" not in desc:
        return ["postpaid"]
    if "预付" in desc and "后付" not in desc:
        return ["prepaid"]
    return ["prepaid", "postpaid"]


def _keywords(desc: str) -> list[str]:
    found = re.findall(r"[\u4e00-\u9fff]{3,8}", desc)
    en = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", desc)]
    extra = [w for w in ("游戏积分", "来电名片", "停车积分") if w in desc]
    out: list[str] = []
    for item in extra + found + en:
        if item not in out and item not in {"用户发送", "需要确认", "无需确认"}:
            out.append(item)
    return out[:8]


def _default_slots(req: dict[str, Any]) -> dict[str, Any]:
    skip = {"msisdn", "msisdn_no", "servicenumber", "lang", "channel", "shortcode"}
    slots: dict[str, Any] = {}
    for key, spec in req.items():
        if key.lower() in skip:
            continue
        val = _sample_value(key, spec)
        if val not in ("string", "str", "int", "integer", "number", "bool", "boolean", ""):
            slots[key] = val
        elif isinstance(spec, (int, float, bool)):
            slots[key] = spec
    return slots


def _sample_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, spec in schema.items():
        if key == "ok":
            continue
        out[key] = _sample_value(key, spec)
    return out


def _sample_value(key: str, spec: Any) -> Any:
    if isinstance(spec, bool):
        return spec
    if isinstance(spec, (int, float)):
        return spec
    if isinstance(spec, dict):
        if "example" in spec:
            return spec["example"]
        if spec.get("type") in {"object", "dict"} or (spec and all(isinstance(v, dict) for v in spec.values())):
            return {k: _sample_value(k, v) for k, v in spec.items() if k not in {"type", "example"}}
        typ = str(spec.get("type") or "")
        return _sample_value(key, typ or "string")
    text = str(spec).strip()
    low = text.lower()
    if low in {"int", "integer", "number", "long"}:
        return 1200 if "point" in key.lower() or "积分" in key else 1
    if low in {"bool", "boolean"}:
        return True
    if low in {"string", "str", "varchar"}:
        return key
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return float(text) if "." in text else int(text)
    return text


def _sms_zh(desc: str, resp: dict[str, Any], kind: str) -> str:
    fields = [k for k in resp.keys() if k != "ok"]
    if "积分" in desc and "points" in resp:
        return "游戏积分 {points}。"
    label = "查询结果" if kind == "query" else "办理完成"
    if fields:
        parts = "，".join(f"{k} {{{k}}}" for k in fields[:4])
        return f"{label}：{parts}。"
    return f"{label}。"


def _sms_en(desc: str, resp: dict[str, Any], kind: str) -> str:
    fields = [k for k in resp.keys() if k != "ok"]
    if ("point" in desc.lower() or "积分" in desc) and "points" in resp:
        return "Game points {points}."
    label = "Result" if kind == "query" else "Done"
    if fields:
        parts = ", ".join(f"{k}={{{k}}}" for k in fields[:4])
        return f"{label}: {parts}."
    return f"{label}."


def _api_name(intent_id: str) -> str:
    return "".join(p.title() for p in intent_id.split("_") if p) or "HallApi"


def _schema_checks(desc: str, req: dict, resp: dict, req_err: str | None, resp_err: str | None) -> list[dict[str, Any]]:
    checks = [
        {"id": "has_description", "ok": bool(desc), "detail": "已填写接口描述" if desc else "缺少接口描述"},
        {"id": "request_schema", "ok": req_err is None and bool(req), "detail": req_err or f"入参 {list(req)[:8]}"},
        {"id": "response_schema", "ok": resp_err is None and bool(resp), "detail": resp_err or f"出参 {list(resp)[:8]}"},
    ]
    blob = json.dumps({"d": desc, "q": req, "s": resp}, ensure_ascii=False)
    has_url = bool(re.search(r"https?://", blob, re.I))
    checks.append(
        {
            "id": "no_live_endpoint",
            "ok": True,
            "detail": "检测到 URL，仅保存合同名与 Mock，不会对真实接口发请求" if has_url else "不保存真实 URL",
        }
    )
    return checks


def _intent_checks(intent_id: str, kind: str, confirm: bool, req: dict, resp: dict) -> list[dict[str, Any]]:
    name_ok = bool(re.fullmatch(r"[a-z][a-z0-9_]{2,47}", intent_id)) and intent_id not in RESERVED
    mutate_ok = not (kind == "mutate" and not confirm)
    return [
        {"id": "intent_id", "ok": name_ok, "detail": intent_id if name_ok else "意图名不合法或与内置冲突"},
        {"id": "mutate_requires_confirm", "ok": mutate_ok, "detail": "写操作必须 confirm=true" if not mutate_ok else "通过"},
        {
            "id": "never_auto_apply",
            "ok": True,
            "detail": "生成意图后须人工勾选并写入 intents.json + catalog",
        },
    ]


def _reason(verdict: str, unknowns: list[str], conflict: dict | None) -> str:
    if verdict == "blocked":
        return "出入参无法解析或策略未通过，禁止落地。"
    parts = ["根据接口合同生成新意图（Mock 执行，不调真实 CRM）。人工确认后写入。"]
    if conflict:
        parts.append("指令码已改派。")
    if unknowns:
        parts.append("请核对：" + ", ".join(unknowns))
    return " ".join(parts)
