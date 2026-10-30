"""AI token-usage accounting for the AI-link function.

Google's Generative Language API does NOT expose the account's remaining
credit / balance through the API key (that lives in Google Cloud Billing,
reachable only via OAuth + the Cloud Billing API — out of scope here). What
IS available and exact is the per-call ``usageMetadata`` Gemini returns
(prompt / output / total tokens). We accumulate those into the persistent
platform-settings store so the Product-Owner console can show cumulative
usage + an (operator-rate-based) cost ESTIMATE.

Cost is an estimate: token prices change and differ per model, so the
per-million-token input/output rates are operator-configurable
(``ai_price_in_per_m`` / ``ai_price_out_per_m``); the defaults are a
Gemini-Flash ballpark and clearly labelled as an estimate in the UI.
"""
from __future__ import annotations

import json
import logging

import httpx

from app.config import settings

log = logging.getLogger("osint.ai_usage")

_KEY = "ai_usage"                 # platform-settings blob (JSON string)
_RATE_IN = "ai_price_in_per_m"    # USD per 1M input tokens
_RATE_OUT = "ai_price_out_per_m"  # USD per 1M output tokens
_DEFAULT_IN = 0.075               # Gemini-Flash ballpark (estimate)
_DEFAULT_OUT = 0.30

_EMPTY = {"runs": 0, "prompt_tokens": 0, "output_tokens": 0,
          "total_tokens": 0, "since": None, "last_run": None, "last_model": None}


async def _get_settings() -> dict:
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
        r.raise_for_status()
        return r.json() or {}


async def _put_settings(values: dict) -> None:
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.put(url, headers={"X-Internal-Key": settings.internal_secret},
                        json={"values": values})
        r.raise_for_status()


def _parse_blob(raw) -> dict:
    if not raw:
        return dict(_EMPTY)
    try:
        d = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (ValueError, TypeError):
        return dict(_EMPTY)
    return {**_EMPTY, **d}


async def record(prompt_tokens: int, output_tokens: int, total_tokens: int,
                 model: str, when_iso: str) -> None:
    """Add one AI run to the cumulative counters. Best-effort — a usage
    write must never break the AI feature itself."""
    try:
        allset = await _get_settings()
        blob = _parse_blob(allset.get(_KEY))
        blob["runs"] += 1
        blob["prompt_tokens"] += int(prompt_tokens or 0)
        blob["output_tokens"] += int(output_tokens or 0)
        blob["total_tokens"] += int(total_tokens or (prompt_tokens + output_tokens) or 0)
        blob["since"] = blob["since"] or when_iso
        blob["last_run"] = when_iso
        blob["last_model"] = model
        await _put_settings({_KEY: json.dumps(blob)})
    except Exception:  # noqa: BLE001
        log.warning("ai_usage.record failed (non-fatal)", exc_info=True)


async def get_usage() -> dict:
    """Cumulative usage + estimated cost from the operator-configured rates."""
    try:
        allset = await _get_settings()
    except Exception:  # noqa: BLE001
        allset = {}
    blob = _parse_blob(allset.get(_KEY))

    def _rate(key: str, default: float) -> float:
        try:
            v = str(allset.get(key, "")).strip()
            return float(v) if v else default
        except (ValueError, TypeError):
            return default

    rate_in = _rate(_RATE_IN, _DEFAULT_IN)
    rate_out = _rate(_RATE_OUT, _DEFAULT_OUT)
    # Gemini bills prompt tokens at the input rate and EVERYTHING else at the
    # output rate — including the "thinking" tokens a reasoning model spends,
    # which land in total but not in candidatesTokenCount. So bill
    # (total - prompt) at the output rate, not just the visible output.
    prompt = blob["prompt_tokens"]
    billable_out = max(blob["output_tokens"], blob["total_tokens"] - prompt)
    cost = (prompt / 1_000_000) * rate_in + (billable_out / 1_000_000) * rate_out
    return {
        **blob,
        "billable_output_tokens": billable_out,
        "rate_in_per_m": rate_in,
        "rate_out_per_m": rate_out,
        "estimated_cost_usd": round(cost, 4),
        # Google's API can't report the account balance via the API key.
        "balance_available": False,
    }


async def reset() -> None:
    await _put_settings({_KEY: json.dumps(dict(_EMPTY))})


async def set_rates(rate_in: float | None, rate_out: float | None) -> None:
    values: dict = {}
    if rate_in is not None:
        values[_RATE_IN] = str(max(0.0, float(rate_in)))
    if rate_out is not None:
        values[_RATE_OUT] = str(max(0.0, float(rate_out)))
    if values:
        await _put_settings(values)
