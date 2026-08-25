from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.config import DATA_DIR
from app.tools import _users

_OFFERS: list[dict[str, Any]] | None = None


def load_offers() -> list[dict[str, Any]]:
    global _OFFERS
    if _OFFERS is None:
        raw = json.loads((DATA_DIR / "offers.json").read_text(encoding="utf-8"))
        _OFFERS = list(raw.get("offers") or [])
    return _OFFERS


def reset_offers_cache() -> None:
    global _OFFERS
    _OFFERS = None


def _fault(msisdn: str, op: str) -> str | None:
    user = _users().get(msisdn) or {}
    faults = user.get("faults") or {}
    reason = faults.get(op)
    return str(reason) if reason else None


def query_language(msisdn: str) -> dict[str, Any]:
    """Mock BOSS: query subscriber language. Hall config does not own this field."""
    fault = _fault(msisdn, "query_language")
    if fault:
        return {"ok": False, "reason": fault, "msisdn": msisdn}
    user = _users()[msisdn]
    return {"ok": True, "lang": user.get("lang") or "zh", "msisdn": msisdn}


def query_offerable_offers(msisdn: str) -> dict[str, Any]:
    """Mock BOSS: tariffs the subscriber may order. List is not from SMS menu config."""
    fault = _fault(msisdn, "query_offerable_offers")
    if fault:
        return {"ok": False, "reason": fault, "msisdn": msisdn}
    user = _users()[msisdn]
    owned = set(user.get("offers") or [])
    items = []
    for row in load_offers():
        item = deepcopy(row)
        item["owned"] = item["id"] in owned
        items.append(item)
    return {"ok": True, "msisdn": msisdn, "plan": user.get("plan"), "offers": items}


def subscribe_offer(msisdn: str, offer_id: str | None = None, **_: Any) -> dict[str, Any]:
    """Mock BOSS: order by msisdn + offer_id. Failures come from BOSS, not the model."""
    fault = _fault(msisdn, "subscribe_offer")
    if fault:
        return {"ok": False, "reason": fault}
    if not offer_id:
        return {"ok": False, "reason": "need_offer"}
    catalog = {o["id"]: o for o in load_offers()}
    offer = catalog.get(offer_id)
    if not offer:
        return {"ok": False, "reason": "unknown_offer"}
    user = _users()[msisdn]
    owned = list(user.get("offers") or [])
    if offer_id in owned:
        return {"ok": False, "reason": "offer_already_on"}
    fee = float(offer.get("fee") or 0)
    if user.get("plan") == "prepaid":
        bal = float(user.get("balance") or 0)
        if bal < fee:
            return {"ok": False, "reason": "insufficient_balance"}
        user["balance"] = round(bal - fee, 2)
    owned.append(offer_id)
    user["offers"] = owned
    return {
        "ok": True,
        "offer_id": offer_id,
        "name_zh": offer["zh"],
        "name_en": offer["en"],
        "fee": offer["fee"],
        "balance": user.get("balance"),
    }
