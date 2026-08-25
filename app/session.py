from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

TTL_SEC = 120


@dataclass
class Session:
    msisdn: str
    state: str = "idle"  # idle | awaiting_confirm | in_menu
    menu_code: str = ""
    pending_intent: str | None = None
    pending_slots: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time)

    def touch(self) -> None:
        self.updated_at = time()

    def expired(self) -> bool:
        return time() - self.updated_at > TTL_SEC

    def clear_pending(self) -> None:
        self.state = "idle"
        self.pending_intent = None
        self.pending_slots = {}
        self.touch()


class SessionStore:
    def __init__(self) -> None:
        self._data: dict[str, Session] = {}

    def get(self, msisdn: str) -> Session:
        sess = self._data.get(msisdn)
        if sess is None or sess.expired():
            sess = Session(msisdn=msisdn)
            self._data[msisdn] = sess
        return sess

    def reset(self, msisdn: str | None = None) -> None:
        if msisdn:
            self._data.pop(msisdn, None)
        else:
            self._data.clear()


store = SessionStore()
