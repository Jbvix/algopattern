import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import analyzer, database, data_collector, predictor, wolfram_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_analysis_cache: dict = {}
_prediction_cache: dict | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    await database.init_db()
    app.state.http_client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; LotofacilBot/1.0)"},
        follow_redirects=True,
    )
    asyncio.create_task(_background_sync(app.state.http_client))
    yield
    await app.state.http_client.aclose()


async def _background_sync(client: httpx.AsyncClient) -> None:
    try:
        new, latest = await data_collector.sync_draws(client)
        logger.info(f"Background sync: {new} new draws, latest={latest}")
        _analysis_cache.clear()
    except Exception as e:
        logger.warning(f"Background sync failed: {e}")


app = FastAPI(title="Lotofácil Predictor", lifespan=lifespan)

_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
frontend_path = Path("frontend")
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def root():
    index = Path("frontend/index.html")
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Lotofácil Predictor API", "docs": "/docs"}


@app.get("/api/health")
async def health():
    count = await database.count_draws()
    latest = await database.get_latest_concurso()
    return {"status": "ok", "db_draws": count, "latest_concurso": latest}


@app.post("/api/sync")
async def sync():
    try:
        new, latest = await data_collector.sync_draws(app.state.http_client)
        total = await database.count_draws()
        _analysis_cache.clear()
        global _prediction_cache
        _prediction_cache = None
        return {"new_draws": new, "total_draws": total, "latest_concurso": latest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _get_analysis() -> analyzer.AnalysisResult:
    if "result" in _analysis_cache:
        return _analysis_cache["result"]
    df = await database.get_all_draws()
    result = analyzer.compute_analysis(df)
    _analysis_cache["result"] = result
    return result


@app.get("/api/stats")
async def stats():
    analysis = await _get_analysis()
    if analysis.total_draws < 5:
        raise HTTPException(status_code=422, detail="Not enough data. Please sync first.")

    return {
        "total_draws": analysis.total_draws,
        "last_concurso": analysis.last_concurso,
        "last_data": analysis.last_data,
        "frequency": {str(k): v for k, v in analysis.frequency.items()},
        "frequency_pct": {str(k): v for k, v in analysis.frequency_pct.items()},
        "frequency_recent": {str(k): v for k, v in analysis.frequency_recent.items()},
        "recency": {str(k): v for k, v in analysis.recency.items()},
        "hot_numbers": analysis.hot_numbers,
        "cold_numbers": analysis.cold_numbers,
        "due_numbers": analysis.due_numbers,
        "even_odd_avg": analysis.even_odd_avg,
        "sum_stats": analysis.sum_stats,
        "sum_distribution": analysis.sum_distribution,
        "sum_buckets": analysis.sum_buckets,
        "decade_dist": analysis.decade_dist,
        "co_occurrence": analysis.co_occurrence,
        "top_pairs": analysis.top_pairs,
        "top_trios": analysis.top_trios,
        "last_draw": analysis.last_draw,
    }


async def _build_prediction(force: bool = False) -> dict:
    global _prediction_cache
    latest = await database.get_latest_concurso()

    if not force and _prediction_cache:
        if _prediction_cache.get("concurso_ref") == latest:
            return _prediction_cache

    cached_db = await database.get_latest_prediction()
    if not force and cached_db and cached_db.get("concurso_ref") == latest:
        _prediction_cache = cached_db
        return cached_db

    analysis = await _get_analysis()
    bets = predictor.generate_bets(analysis, n_bets=20)
    apostas = [combo for combo, _ in bets]
    scores = [round(float(score), 4) for _, score in bets]

    await database.save_prediction(latest, apostas, scores, method="composite_v1")

    result = {
        "apostas": apostas,
        "scores": scores,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "concurso_ref": latest,
        "method": "composite_v1",
    }
    _prediction_cache = result
    return result


@app.get("/api/predictions")
async def get_predictions():
    try:
        return await _build_prediction(force=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/predictions/generate")
async def generate_predictions():
    try:
        _analysis_cache.clear()
        return await _build_prediction(force=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/predictions/history")
async def prediction_history():
    return await database.get_recent_predictions(limit=5)


@app.get("/api/draws")
async def list_draws(limit: int = 50, offset: int = 0):
    df = await database.get_all_draws()
    total = len(df)
    df = df.sort_values("concurso", ascending=False).iloc[offset: offset + limit]
    def _clean(record: dict) -> dict:
        return {k: (int(v) if hasattr(v, 'item') and isinstance(v.item(), int) else
                    float(v) if hasattr(v, 'item') else v)
                for k, v in record.items()}

    draws = [_clean(r) for r in df.to_dict(orient="records")]
    return {"draws": draws, "total": int(total)}


@app.get("/api/draws/{concurso}")
async def get_draw(concurso: int):
    df = await database.get_all_draws()
    row = df[df["concurso"] == concurso]
    if row.empty:
        raise HTTPException(status_code=404, detail="Draw not found")
    raw = row.iloc[0].to_dict()
    return {k: (int(v) if hasattr(v, 'item') and isinstance(v.item(), int) else
                float(v) if hasattr(v, 'item') else v)
            for k, v in raw.items()}


@app.get("/api/wolfram/insight")
async def wolfram_insight():
    analysis = await _get_analysis()
    if analysis.total_draws < 5:
        return {"insight": None}
    insight = await wolfram_client.get_hot_numbers_insight(
        app.state.http_client, analysis.hot_numbers
    )
    sum_insight = await wolfram_client.get_sum_insight(
        app.state.http_client,
        analysis.sum_stats["mean"],
        analysis.sum_stats["std"],
    )
    return {
        "hot_insight": insight,
        "sum_insight": sum_insight,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)
