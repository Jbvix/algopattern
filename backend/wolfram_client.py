import hashlib
import logging
import os
import time
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

WOLFRAM_API_URL = "https://api.wolframalpha.com/v2/query"
_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 3600  # 1 hour


def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()


def _get_cached(query: str) -> str | None:
    key = _cache_key(query)
    if key in _cache:
        value, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return value
        del _cache[key]
    return None


def _set_cached(query: str, value: str) -> None:
    key = _cache_key(query)
    _cache[key] = (value, time.time())


async def query_wolfram(client: httpx.AsyncClient, query: str) -> str | None:
    api_key = os.environ.get("WOLFRAM_API_KEY")
    if not api_key:
        return None

    cached = _get_cached(query)
    if cached:
        return cached

    try:
        resp = await client.get(
            WOLFRAM_API_URL,
            params={
                "appid": api_key,
                "input": query,
                "output": "json",
                "format": "plaintext",
                "podstate": "Step-by-step solution",
            },
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning(f"Wolfram API status {resp.status_code}")
            return None

        data = resp.json()
        query_result = data.get("queryresult", {})
        if not query_result.get("success"):
            return None

        pods = query_result.get("pods", [])
        texts = []
        for pod in pods[:4]:
            title = pod.get("title", "")
            for sub in pod.get("subpods", []):
                text = sub.get("plaintext", "").strip()
                if text and len(text) < 500:
                    texts.append(f"{title}: {text}")
        result = " | ".join(texts) if texts else None
        if result:
            _set_cached(query, result)
        return result

    except Exception as e:
        logger.warning(f"Wolfram query failed: {e}")
        return None


async def get_frequency_insight(client: httpx.AsyncClient, freq_dict: dict[int, int]) -> str | None:
    sorted_freq = sorted(freq_dict.items(), key=lambda x: x[1], reverse=True)
    top5 = [str(n) for n, _ in sorted_freq[:5]]
    query = f"statistical analysis of the integer sequence {{{','.join(top5)}}}"
    return await query_wolfram(client, query)


async def get_hot_numbers_insight(client: httpx.AsyncClient, hot_numbers: list[int]) -> str | None:
    nums = ",".join(str(n) for n in sorted(hot_numbers[:8]))
    query = f"prime factorization and number theory properties of {{{nums}}}"
    return await query_wolfram(client, query)


async def get_sum_insight(client: httpx.AsyncClient, mean: float, std: float) -> str | None:
    query = f"normal distribution with mean {mean:.1f} and standard deviation {std:.1f}"
    return await query_wolfram(client, query)
