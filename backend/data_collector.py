import asyncio
import csv
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.database import get_latest_concurso, upsert_draws_bulk

logger = logging.getLogger(__name__)

CAIXA_URL = "https://servicebus2.caixa.gov.br/portaldeloterias/api/lotofacil/{concurso}"
SEED_CSV = Path("data/historical_seed.csv")
MAX_RETRIES = 3
SEMAPHORE_LIMIT = 5


def parse_draw(raw: dict) -> dict | None:
    try:
        concurso = int(raw.get("numero") or raw.get("concurso", 0))
        if not concurso:
            return None
        data_str = raw.get("dataApuracao", raw.get("data", ""))
        dezenas_raw = raw.get("listaDezenas", raw.get("dezenas", []))
        dezenas = [int(d) for d in dezenas_raw]
        if len(dezenas) != 15:
            return None

        premiacao = raw.get("premiacao", [])
        prizes = {}
        for tier in premiacao:
            acertos = tier.get("acertos", tier.get("faixa", ""))
            val = tier.get("valorPremio", tier.get("premio", 0)) or 0
            if str(acertos) in ("15", "Sena"):
                prizes["premio_15"] = float(val)
            elif str(acertos) in ("14", "Quina"):
                prizes["premio_14"] = float(val)
            elif str(acertos) in ("13", "Quadra"):
                prizes["premio_13"] = float(val)
            elif str(acertos) == "12":
                prizes["premio_12"] = float(val)
            elif str(acertos) == "11":
                prizes["premio_11"] = float(val)

        acumulado = int(bool(raw.get("acumulado", False) or raw.get("acumulated", False)))

        return {
            "concurso": concurso,
            "data": data_str,
            "dezenas": dezenas,
            "premio_15": prizes.get("premio_15"),
            "premio_14": prizes.get("premio_14"),
            "premio_13": prizes.get("premio_13"),
            "premio_12": prizes.get("premio_12"),
            "premio_11": prizes.get("premio_11"),
            "acumulado": acumulado,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to parse draw: {e} | raw={raw}")
        return None


async def fetch_draw(client: httpx.AsyncClient, concurso: int | str = "") -> dict | None:
    url = CAIXA_URL.format(concurso=concurso)
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, timeout=15)
            if resp.status_code == 404:
                return None
            if resp.status_code == 200:
                return parse_draw(resp.json())
            logger.warning(f"Concurso {concurso}: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Concurso {concurso} attempt {attempt+1}: {e}")
        await asyncio.sleep(2 ** attempt)
    return None


async def fetch_latest_draw(client: httpx.AsyncClient) -> dict | None:
    return await fetch_draw(client, "")


async def load_seed_csv() -> int:
    if not SEED_CSV.exists():
        return 0
    draws = []
    with open(SEED_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dezenas = [int(row[f"d{i}"]) for i in range(1, 16)]
                draws.append({
                    "concurso": int(row["concurso"]),
                    "data": row.get("data", ""),
                    "dezenas": dezenas,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                continue
    await upsert_draws_bulk(draws)
    logger.info(f"Loaded {len(draws)} draws from seed CSV")
    return len(draws)


async def sync_draws(client: httpx.AsyncClient) -> tuple[int, int]:
    """Returns (new_draws_count, total_latest_concurso)."""
    latest_in_db = await get_latest_concurso()

    # Load seed first if DB is empty
    if latest_in_db == 0:
        await load_seed_csv()
        latest_in_db = await get_latest_concurso()

    # Fetch the current latest from API
    latest_draw = await fetch_latest_draw(client)
    if not latest_draw:
        logger.warning("Could not fetch latest draw from Caixa API")
        return 0, latest_in_db

    latest_api = latest_draw["concurso"]
    if latest_api <= latest_in_db:
        return 0, latest_in_db

    # Fetch missing draws concurrently with semaphore
    missing = list(range(latest_in_db + 1, latest_api + 1))
    logger.info(f"Fetching {len(missing)} missing draws ({latest_in_db+1}..{latest_api})")

    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)

    async def fetch_one(concurso: int) -> dict | None:
        async with sem:
            return await fetch_draw(client, concurso)

    tasks = [fetch_one(c) for c in missing]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    draws = []
    for r in results:
        if isinstance(r, dict) and r:
            draws.append(r)

    await upsert_draws_bulk(draws)
    logger.info(f"Inserted {len(draws)} new draws")
    return len(draws), latest_api
