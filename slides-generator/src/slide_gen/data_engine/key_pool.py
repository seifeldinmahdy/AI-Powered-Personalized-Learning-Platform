"""
Multi-key Ollama Cloud pool loader.

The MCQ pipeline runs many parallel workers, one pinned per API key
(see mcq_service/.../data_generator.py::generate_synthetic_chunks). The
slides-generator data scripts reuse that idea for visual-classifier labeling
and targeted synthetic-chunk generation.

This collects the numbered Ollama Cloud keys (OLLAMA_API_KEY_1..N) primarily
from `mcq_service/.env` — that's where the 13-key fleet lives — and falls back
to the single keys in `slides-generator/.env`. Values are read without mutating
os.environ so each worker can be pinned to a distinct key.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import dotenv_values

# key_pool.py → data_engine → slide_gen → src → slides-generator → <repo root>
_HERE = Path(__file__).resolve()
_SLIDES_ROOT = _HERE.parents[3]
_REPO_ROOT = _HERE.parents[4]

# Searched in order; mcq_service first (the multi-key fleet), then slides-generator.
_DEFAULT_ENV_FILES = [
    _REPO_ROOT / "mcq_service" / ".env",
    _SLIDES_ROOT / ".env",
]


def load_ollama_keys(
    extra_env_files: list[str | Path] | None = None,
    max_keys: int | None = None,
) -> list[str]:
    """Return a de-duplicated, ordered list of Ollama Cloud API keys.

    Order: numbered keys (OLLAMA_API_KEY_1, _2, …) from each env file in search
    order, then the single OLLAMA_API_KEY / OLLAMA_API_KEY_FALLBACK fallbacks.

    Parameters
    ----------
    extra_env_files : optional list of .env paths to search BEFORE the defaults.
    max_keys : optional cap on how many keys to return.
    """
    candidates: list[Path] = []
    if extra_env_files:
        candidates += [Path(p) for p in extra_env_files]
    candidates += _DEFAULT_ENV_FILES

    keys: list[str] = []
    seen: set[str] = set()

    for env_path in candidates:
        if not env_path.exists():
            continue
        vals = dotenv_values(env_path)

        # Numbered keys, sorted numerically (OLLAMA_API_KEY_2 before _10).
        numbered: list[tuple[int, str]] = []
        for k, v in vals.items():
            if not v:
                continue
            if k.startswith("OLLAMA_API_KEY_"):
                suffix = k[len("OLLAMA_API_KEY_"):]
                if suffix.isdigit():
                    numbered.append((int(suffix), v))
        for _, v in sorted(numbered, key=lambda x: x[0]):
            if v not in seen:
                seen.add(v)
                keys.append(v)

        # Single-key fallbacks.
        for name in ("OLLAMA_API_KEY", "OLLAMA_API_KEY_FALLBACK"):
            v = vals.get(name)
            if v and v not in seen:
                seen.add(v)
                keys.append(v)

    if max_keys is not None:
        keys = keys[:max_keys]
    return keys


def probe_live_keys(
    keys: list[str],
    host: str | None = None,
    model: str = "gemma3:12b",
    timeout: int = 30,
) -> list[str]:
    """Return only keys that answer a 1-token probe with HTTP 200.

    Ollama Cloud's free plan enforces a per-account WEEKLY usage cap; exhausted
    keys return HTTP 429 and forbidden models return 403. A worker pinned to a
    dead key would fail every task, so callers should filter keys through this
    before spawning workers. ``model`` must be a free-plan model.
    """
    host = (host or os.getenv("OLLAMA_HOST", "https://ollama.com")).rstrip("/")
    live: list[str] = []
    for k in keys:
        if not k:
            continue
        try:
            r = requests.post(
                f"{host}/api/generate",
                headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
                json={"model": model, "prompt": "hi", "stream": False,
                      "options": {"num_predict": 1}},
                timeout=timeout,
            )
            if r.status_code == 200:
                live.append(k)
        except requests.RequestException:
            pass
    return live


def load_nvidia_keys(
    extra_env_files: list[str | Path] | None = None,
    max_keys: int | None = None,
) -> list[str]:
    """Return de-duplicated NVIDIA NIM API keys from the env files.

    Collects numbered keys (NVIDIA_API_KEY_1, _2, …) and the named role keys
    (NVIDIA_API_KEY_GEN / _JUDGE_B / _JUDGE_C / _JUDGE_D / _REFINE / _FALLBACK).
    All keys typically belong to ONE account whose RPM cap is pooled, so this is
    mostly for redundancy — throughput is governed by the rate limiter, not key
    count. ``nvapi-…`` is the expected prefix.
    """
    candidates: list[Path] = []
    if extra_env_files:
        candidates += [Path(p) for p in extra_env_files]
    candidates += _DEFAULT_ENV_FILES

    keys: list[str] = []
    seen: set[str] = set()
    named = ("NVIDIA_API_KEY_GEN", "NVIDIA_API_KEY_JUDGE_B", "NVIDIA_API_KEY_JUDGE_C",
             "NVIDIA_API_KEY_JUDGE_D", "NVIDIA_API_KEY_REFINE", "NVIDIA_API_KEY_FALLBACK",
             "NVIDIA_API_KEY")

    for env_path in candidates:
        if not env_path.exists():
            continue
        vals = dotenv_values(env_path)

        numbered: list[tuple[int, str]] = []
        for k, v in vals.items():
            if not v:
                continue
            if k.startswith("NVIDIA_API_KEY_"):
                suffix = k[len("NVIDIA_API_KEY_"):]
                if suffix.isdigit():
                    numbered.append((int(suffix), v))
        for _, v in sorted(numbered, key=lambda x: x[0]):
            if v not in seen:
                seen.add(v)
                keys.append(v)

        for name in named:
            v = vals.get(name)
            if v and v not in seen:
                seen.add(v)
                keys.append(v)

    if max_keys is not None:
        keys = keys[:max_keys]
    return keys


def get_nvidia_config(
    extra_env_files: list[str | Path] | None = None,
) -> dict:
    """Return {base_url, rpm} for NVIDIA NIM, read from the env files (with defaults)."""
    candidates: list[Path] = []
    if extra_env_files:
        candidates += [Path(p) for p in extra_env_files]
    candidates += _DEFAULT_ENV_FILES

    base_url = "https://integrate.api.nvidia.com/v1"
    rpm = 38
    for env_path in candidates:
        if not env_path.exists():
            continue
        vals = dotenv_values(env_path)
        if vals.get("NVIDIA_BASE_URL"):
            base_url = vals["NVIDIA_BASE_URL"]
        if vals.get("NVIDIA_RPM"):
            try:
                rpm = int(vals["NVIDIA_RPM"])
            except ValueError:
                pass
    return {"base_url": base_url, "rpm": rpm}


def describe_key_sources() -> str:
    """Human-readable summary of where keys were found (for logging)."""
    parts = []
    for env_path in _DEFAULT_ENV_FILES:
        if env_path.exists():
            vals = dotenv_values(env_path)
            n = sum(
                1 for k, v in vals.items()
                if v and k.startswith("OLLAMA_API_KEY_")
                and k[len("OLLAMA_API_KEY_"):].isdigit()
            )
            n += sum(1 for name in ("OLLAMA_API_KEY", "OLLAMA_API_KEY_FALLBACK")
                     if vals.get(name))
            parts.append(f"{env_path}: {n} key(s)")
    return "; ".join(parts) if parts else "no .env files found"
