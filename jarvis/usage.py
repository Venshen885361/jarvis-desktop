"""Token 計量。每次 API 呼叫後累加，並即時推到 HUD，讓你看得到錢花在哪。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

# 每 MTok 美金定價。只放我們預設會用到的型號；找不到就以 0 計價（只顯示 token 數）。
# 來源：https://platform.claude.com/docs/en/about-claude/pricing
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-5": (3.0, 15.0),
}


@dataclass
class UsageTracker:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    api_calls: int = 0
    local_hits: int = 0  # 本機路由攔下、完全沒打 API 的次數
    cost_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
    ) -> None:
        with self._lock:
            self.api_calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.cache_read_tokens += cache_read
            self.cache_write_tokens += cache_write
            in_price, out_price = _PRICING.get(model, (0.0, 0.0))
            # cache read 以 0.1x 計、cache write 以 1.25x 計（Anthropic 標準倍率）
            self.cost_usd += (
                input_tokens * in_price
                + cache_read * in_price * 0.1
                + cache_write * in_price * 1.25
                + output_tokens * out_price
            ) / 1_000_000

    def add_local_hit(self) -> None:
        with self._lock:
            self.local_hits += 1

    def snapshot(self) -> dict:
        with self._lock:
            total = self.api_calls + self.local_hits
            return {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "cache_read": self.cache_read_tokens,
                "cache_write": self.cache_write_tokens,
                "api_calls": self.api_calls,
                "local_hits": self.local_hits,
                "local_ratio": round(self.local_hits / total * 100) if total else 0,
                "cost_usd": round(self.cost_usd, 4),
            }


tracker = UsageTracker()
