"""NVIDIA NIM client (OpenAI-compatible) with an account-wide rate limiter.

Ported from mcq_service so the slides-generator data scripts can use NVIDIA's
hosted NIM endpoint as a second generation backend alongside Ollama Cloud.

All NVIDIA keys here belong to ONE account, so the free-tier RPM cap is POOLED
across every key. A single process-wide sliding-window limiter enforces it —
adding more keys does NOT raise throughput; it only adds redundancy. Saturating
the quota is done with multiple worker threads that all share this one limiter.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

import requests


class _RateLimiter:
    """Thread-safe sliding-window limiter: at most ``max_per_min`` calls / 60s."""

    def __init__(self, max_per_min: int) -> None:
        self._max = max(1, max_per_min)
        self._window = 60.0
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self._window:
                    self._calls.popleft()
                if len(self._calls) < self._max:
                    self._calls.append(now)
                    return
                sleep_for = self._window - (now - self._calls[0]) + 0.02
            time.sleep(min(max(sleep_for, 0.01), 5.0))


# Singleton: every NvidiaClient shares one limiter because all keys belong to one
# NVIDIA account and the RPM cap is pooled across them.
_GLOBAL_LIMITER: _RateLimiter | None = None
_LIMITER_LOCK = threading.Lock()


def _limiter(max_per_min: int) -> _RateLimiter:
    global _GLOBAL_LIMITER
    with _LIMITER_LOCK:
        if _GLOBAL_LIMITER is None:
            _GLOBAL_LIMITER = _RateLimiter(max_per_min)
        return _GLOBAL_LIMITER


class NvidiaRateLimitError(RuntimeError):
    """Raised on HTTP 429 from the NIM endpoint (quota / RPM exceeded)."""


class NvidiaAuthError(RuntimeError):
    """Raised on HTTP 401/403 from the NIM endpoint (bad/disabled key)."""


class NvidiaClient:
    """Minimal NVIDIA NIM chat client. ``chat()`` returns message content text.

    Distinguishes rate-limit / auth / transport failures via typed exceptions so
    callers can retire a dead backend vs. retry a transient blip.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        rpm: int = 38,
        max_tokens: int = 4096,
        timeout: int = 120,
        reasoning_budget: int = 1024,
    ) -> None:
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._reasoning_budget = reasoning_budget
        self._limiter = _limiter(rpm)
        # nemotron is a reasoning model and takes a reasoning_budget; other NIM
        # models (e.g. openai/gpt-oss) reject the field. The usable answer is
        # always choices[0].message.content (reasoning_content is separate).
        self._is_reasoning = "nemotron" in model.lower()

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_override: int | None = None,
    ) -> str:
        """Return ``choices[0].message.content``. Raises typed errors on failure."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "top_p": 1,
            "max_tokens": max_tokens or self._max_tokens,
            "stream": False,
        }
        if self._is_reasoning:
            payload["reasoning_budget"] = self._reasoning_budget
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        eff_timeout = timeout_override if timeout_override is not None else self._timeout

        self._limiter.acquire()
        try:
            resp = requests.post(
                self._endpoint, headers=headers, json=payload, timeout=eff_timeout
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"transport error: {exc}") from exc

        if resp.status_code == 429:
            raise NvidiaRateLimitError(resp.text[:160])
        if resp.status_code in (401, 403):
            raise NvidiaAuthError(f"{resp.status_code}: {resp.text[:160]}")
        if resp.status_code >= 500:
            raise RuntimeError(f"server error {resp.status_code}: {resp.text[:160]}")
        resp.raise_for_status()

        content = resp.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise RuntimeError("empty content from model")
        return content
