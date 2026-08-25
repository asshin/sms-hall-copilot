from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

TTL_SEC = 120
PENDING_STATES = {"awaiting_select", "awaiting_confirm"}


@dataclass
class Session:
    msisdn: str
    state: str = "idle"  # idle | awaiting_confirm | in_menu | awaiting_select
    menu_code: str = ""
    pending_intent: str | None = None
    pending_slots: dict[str, Any] = field(default_factory=dict)
    select_list: list[dict[str, Any]] = field(default_factory=list)
    process_id: str | None = None
    last_receipt: dict[str, Any] | None = None
    updated_at: float = field(default_factory=time)

    def touch(self) -> None:
        self.updated_at = time()

    def expired(self) -> bool:
        return time() - self.updated_at > TTL_SEC

    def clear_pending(self) -> None:
        self.state = "idle"
        self.pending_intent = None
        self.pending_slots = {}
        self.select_list = []
        self.process_id = None
        self.touch()


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, Session] = {}
        self._expired_meta: dict[str, dict[str, Any]] = {}

    def get(self, msisdn: str) -> Session:
        sess = self._data.get(msisdn)
        if sess is None:
            sess = Session(msisdn=msisdn)
            self._data[msisdn] = sess
            return sess
        if sess.expired():
            if sess.state in PENDING_STATES:
                self._expired_meta[msisdn] = {
                    "state": sess.state,
                    "process_id": sess.process_id,
                    "pending_intent": sess.pending_intent,
                }
            sess = Session(msisdn=msisdn)
            self._data[msisdn] = sess
            return sess
        return sess

    def consume_expired(self, msisdn: str) -> dict[str, Any] | None:
        return self._expired_meta.pop(msisdn, None)

    def expire_now(self, msisdn: str) -> None:
        """Test helper: make the current session look TTL-expired."""
        sess = self._data.get(msisdn)
        if sess is not None:
            sess.updated_at = time() - TTL_SEC - 1

    def reset(self, msisdn: str | None = None) -> None:
        if msisdn:
            self._data.pop(msisdn, None)
            self._expired_meta.pop(msisdn, None)
        else:
            self._data.clear()
            self._expired_meta.clear()


store = SessionStore()
