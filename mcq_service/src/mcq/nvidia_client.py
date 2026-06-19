"""NVIDIA NIM client for in-session MCQ refinement.

A self-contained, production OpenAI-compatible REST client for NVIDIA's hosted
NIM endpoint (``POST /chat/completions``). Used by ``mcq.refine`` to run the
nemotron judge+repair pass at serve time — it has no dependency on the training
package.

The reasoning models (nemotron) emit a separate ``reasoning_content`` we ignore;
the usable answer is always ``choices[0].message.content``. Every request first
passes through an account-wide sliding-window rate limiter so the NVIDIA free
tier RPM cap is never exceeded (all keys on one account share the pool).
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any

import requests
import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNT-WIDE RATE LIMITER
# ═══════════════════════════════════════════════════════════════════════════════

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


# Singleton: every NvidiaClient shares one limiter because all keys belong to
# one NVIDIA account and the RPM cap is pooled across them.
_GLOBAL_LIMITER: _RateLimiter | None = None
_LIMITER_LOCK = threading.Lock()


def _limiter(max_per_min: int) -> _RateLimiter:
    global _GLOBAL_LIMITER
    with _LIMITER_LOCK:
        if _GLOBAL_LIMITER is None:
            _GLOBAL_LIMITER = _RateLimiter(max_per_min)
        return _GLOBAL_LIMITER


# ═══════════════════════════════════════════════════════════════════════════════
# CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class NvidiaClient:
    """Minimal NVIDIA NIM chat client with ``chat()`` and ``chat_json()``."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        rpm: int = 38,
        reasoning_budget: int = 1024,
        max_tokens: int = 2048,
        max_retries: int = 2,
        timeout: int = 120,
    ) -> None:
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._reasoning_budget = reasoning_budget
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._timeout = timeout
        self._limiter = _limiter(rpm)
        # nemotron is a reasoning model and takes a reasoning_budget; other
        # NIM models (e.g. openai/gpt-oss) reject the field.
        self._is_reasoning = "nemotron" in model.lower()

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_override: int | None = None,
    ) -> str:
        """Return ``choices[0].message.content`` for a chat completion."""
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

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            self._limiter.acquire()
            try:
                resp = requests.post(
                    self._endpoint, headers=headers, json=payload, timeout=eff_timeout
                )
                if resp.status_code == 429:
                    raise RuntimeError(f"429 rate limit: {resp.text[:160]}")
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"].get("content") or ""
                if not content.strip():
                    raise RuntimeError("empty content from model")
                return content
            except (requests.RequestException, KeyError, ValueError, RuntimeError) as exc:
                last_error = exc
                logger.warning(
                    "nvidia_api_error", attempt=attempt,
                    model=self._model, error=str(exc)[:160],
                )
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(
            f"NVIDIA API failed after {self._max_retries} attempts: {last_error}"
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout_override: int | None = None,
    ) -> dict[str, Any]:
        """Chat expecting a JSON object response, parsed tolerantly."""
        raw = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_override=timeout_override,
        )
        # Tier 1 — strict
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Tier 2 — extract the bare {...} object
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            candidate = raw[start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
            # Tier 3 — repair (missing commas, unescaped quotes, truncation)
            try:
                from json_repair import repair_json  # type: ignore
                repaired = repair_json(candidate, return_objects=True)
                if isinstance(repaired, dict):
                    logger.warning("nvidia_json_repaired", original_len=len(raw))
                    return repaired
            except Exception:
                pass
        raise json.JSONDecodeError(
            f"Could not parse JSON from NVIDIA output (len={len(raw)})", raw, 0
        )


# Lazy singleton so the refinement path reuses one client/limiter per process.
_client: NvidiaClient | None = None
_client_lock = threading.Lock()


def get_refine_client(settings) -> NvidiaClient | None:
    """Build (once) the NVIDIA judge client from settings, or None if unconfigured."""
    global _client
    if not getattr(settings, "NVIDIA_API_KEY_REFINE", ""):
        return None
    with _client_lock:
        if _client is None:
            _client = NvidiaClient(
                base_url=settings.NVIDIA_BASE_URL,
                model=settings.NVIDIA_REFINE_MODEL,
                api_key=settings.NVIDIA_API_KEY_REFINE,
                rpm=settings.NVIDIA_RPM,
                reasoning_budget=settings.NVIDIA_REASONING_BUDGET,
                max_tokens=settings.NVIDIA_MAX_TOKENS,
            )
        return _client
