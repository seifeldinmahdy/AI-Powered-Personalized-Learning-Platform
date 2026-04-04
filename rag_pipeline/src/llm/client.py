"""Injectable Ollama Cloud LLM client with retry logic and structured logging."""

from __future__ import annotations

import json
import time
from typing import Any

import requests
import structlog

logger = structlog.get_logger(__name__)


class OllamaCloudClient:
    """HTTP client for the Ollama Cloud chat API.

    Designed to be injectable: pass a mock in tests, a real instance in
    production.  All calls are logged with structlog.
    """

    def __init__(
        self,
        host: str,
        model: str,
        api_key: str,
        max_retries: int = 3,
        timeout: int = 120,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout
        self.chat_endpoint = f"{self.host}/api/chat"

    # ── Internal helpers ──────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ── Public API ────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request and return the raw content string.

        Retries with exponential back-off on transient failures.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"

        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "llm_api_call",
                    endpoint=self.chat_endpoint,
                    model=self.model,
                    attempt=attempt,
                    json_mode=json_mode,
                )
                response = requests.post(
                    self.chat_endpoint,
                    headers=self._headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()

                data = response.json()
                content: str = data["message"]["content"]

                logger.info(
                    "llm_api_success",
                    attempt=attempt,
                    response_length=len(content),
                )
                return content

            except (
                requests.RequestException,
                KeyError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                logger.warning(
                    "llm_api_error",
                    attempt=attempt,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                if attempt < self.max_retries:
                    time.sleep(2**attempt)

        raise RuntimeError(
            f"LLM API call failed after {self.max_retries} attempts: "
            f"{last_error}"
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """Send a chat request expecting a JSON response.

        Parses the raw content string into a Python dict.
        """
        raw = self.chat(
            messages, json_mode=True, temperature=temperature
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "llm_json_parse_error",
                raw_response=raw[:500],
                error=str(exc),
            )
            raise


def build_client_from_settings(
    settings: Any,
) -> OllamaCloudClient:
    """Factory that creates an OllamaCloudClient from a Settings object."""
    return OllamaCloudClient(
        host=settings.ollama_host,
        model=settings.ollama_model,
        api_key=settings.ollama_api_key,
        max_retries=settings.max_retries,
    )
