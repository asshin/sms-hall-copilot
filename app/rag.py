from __future__ import annotations

import math
import re
from functools import lru_cache

from app.config import DATA_DIR

_TOKEN = re.compile(r"[a-zA-Z]+|[\u4e00-\u9fff]|[0-9]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


@lru_cache
def chunks() -> list[str]:
    raw = (DATA_DIR / "knowledge.md").read_text(encoding="utf-8")
    parts = [p.strip() for p in re.split(r"\n## ", raw) if p.strip()]
    return parts


def search(query: str, k: int = 3) -> list[str]:
    q = _tokens(query)
    if not q:
        return chunks()[:k]
    scored: list[tuple[float, str]] = []
    for ch in chunks():
        ct = _tokens(ch)
        if not ct:
            continue
        overlap = len(set(q) & set(ct))
        scored.append((overlap / math.sqrt(len(ct)), ch[:280]))
    scored.sort(reverse=True)
    return [c for s, c in scored[:k] if s > 0] or [chunks()[0][:280]]
