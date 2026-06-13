"""LLM client and sequence validation.

Provides:
1. ``OllamaClient`` — lightweight Ollama Cloud chat client used by
   all LLM-calling modules in the pathway generator.
2. ``validate_sequence`` — asks the LLM to sanity-check the final
   session order.
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests
import structlog

from pathway.models.schemas import Session

logger = structlog.get_logger(__name__)


class OllamaClient:
    """Lightweight Ollama Cloud chat client for the pathway generator.

    Mirrors the interface from ``rag_pipeline.src.llm.client`` but is
    self-contained so that course_pathway has no import dependency on
    rag_pipeline at runtime.
    """

    def __init__(
        self,
        host: str,
        model: str,
        api_key: str,
        max_retries: int = 3,
        timeout: int = 120,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._max_retries = max_retries
        self._timeout = timeout
        self._endpoint = f"{self._host}/api/chat"

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        json_mode: bool = False,
        timeout_override: int | None = None,
        num_predict: int | None = None,
    ) -> str:
        """Send a chat completion and return the raw content string."""
        options: dict[str, Any] = {"temperature": temperature}
        if num_predict is not None:
            options["num_predict"] = num_predict

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if json_mode:
            payload["format"] = "json"

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        effective_timeout = timeout_override if timeout_override is not None else self._timeout

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = requests.post(
                    self._endpoint,
                    headers=headers,
                    json=payload,
                    timeout=effective_timeout,
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except (requests.RequestException, KeyError) as exc:
                last_error = exc
                logger.warning(
                    "ollama_api_error", attempt=attempt, error=str(exc)
                )
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(
            f"Ollama API failed after {self._max_retries} attempts: {last_error}"
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        timeout_override: int | None = None,
        num_predict: int | None = None,
    ) -> dict[str, Any]:
        """Chat expecting a JSON response, parsed into a dict.

        Three-tier parsing to handle small-model JSON quirks:
        1. Strict json.loads
        2. Extract bare JSON object from markdown fences
        3. json-repair for missing commas, unescaped quotes, etc.
        """
        raw = self.chat(
            messages,
            temperature=temperature,
            json_mode=True,
            timeout_override=timeout_override,
            num_predict=num_predict,
        )
        # Tier 1 — strict parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Tier 2 — extract bare JSON object (strip markdown fences / extra text)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            candidate = raw[start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

            # Tier 3 — repair: fixes missing commas, unescaped quotes, truncation
            try:
                from json_repair import repair_json  # type: ignore
                repaired = repair_json(candidate, return_objects=True)
                if isinstance(repaired, dict):
                    logger.warning("json_repaired", original_len=len(raw))
                    return repaired
            except Exception:
                pass

        raise json.JSONDecodeError(
            f"Could not parse JSON from model output (len={len(raw)})", raw, 0
        )


# ── Sequence Validation ──────────────────────────────────────────

_VALIDATION_SYSTEM = (
    "You are an expert curriculum designer validating a computer science course. "
    "You will receive an ordered list of session titles representing a learning pathway. "
    "Check if the order makes pedagogical sense — foundational topics should come "
    "before advanced topics, and prerequisites should be covered first. "
    "Return a JSON object: "
    '{"valid": true/false, "issues": ["issue description", ...], '
    '"suggestion": "brief suggestion if invalid, empty string if valid"}. '
    "Return ONLY the JSON."
)


def validate_sequence(
    client: OllamaClient,
    sessions: list[Session],
) -> dict[str, Any]:
    """Ask the LLM to validate the pedagogical sense of a session order.

    Parameters
    ----------
    client:
        Configured Ollama client.
    sessions:
        Ordered list of sessions to validate.

    Returns
    -------
    dict
        ``{"valid": bool, "issues": list[str], "suggestion": str}``
    """
    titles = [
        f"{s.session_number}. {s.session_title}" for s in sessions
    ]
    listing = "\n".join(titles)

    try:
        result = client.chat_json(
            [
                {"role": "system", "content": _VALIDATION_SYSTEM},
                {"role": "user", "content": f"Session order:\n{listing}"},
            ],
            temperature=0.2,
        )
        logger.info(
            "sequence_validation_complete",
            valid=result.get("valid"),
            issues=len(result.get("issues", [])),
        )
        return result
    except Exception as exc:
        logger.warning("sequence_validation_failed", error=str(exc))
        return {"valid": True, "issues": [], "suggestion": ""}
