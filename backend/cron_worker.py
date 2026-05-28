"""
Cron worker — executado uma vez por noite pelo Railway Cron Job.
Busca apenas os sorteios novos desde o último registrado no banco,
sem scraping agressivo. Tipicamente faz 1-3 requisições HTTP por execução
após a base histórica já estar populada.

Railway Cron schedule sugerido: 0 23 * * 1,3,5
(23h nos dias de sorteio: segunda, quarta e sexta)
"""
import asyncio
import logging
import os
import sys

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cron] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    os.makedirs("data", exist_ok=True)

    from backend.database import init_db, count_draws, get_latest_concurso
    from backend.data_collector import sync_draws

    await init_db()

    before = await count_draws()
    logger.info(f"DB has {before} draws before sync")

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; LotofacilBot/1.0)"},
        follow_redirects=True,
    ) as client:
        new, latest = await sync_draws(client)

    after = await count_draws()
    logger.info(f"Sync complete: +{new} draws | total={after} | latest concurso={latest}")

    if new == 0:
        logger.info("No new draws today — nothing to do.")
    else:
        logger.info(f"Inserted {new} new draw(s). Analysis cache will refresh on next API request.")


if __name__ == "__main__":
    asyncio.run(run())
    sys.exit(0)
