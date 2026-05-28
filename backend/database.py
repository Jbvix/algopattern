import json
import os
from datetime import datetime, timezone

import aiosqlite
import pandas as pd

DB_PATH = os.environ.get("DB_PATH", "data/lotofacil.db")


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS draws (
                concurso   INTEGER PRIMARY KEY,
                data       TEXT NOT NULL,
                dezenas    TEXT NOT NULL,
                premio_15  REAL,
                premio_14  REAL,
                premio_13  REAL,
                premio_12  REAL,
                premio_11  REAL,
                acumulado  INTEGER DEFAULT 0,
                fetched_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT NOT NULL,
                concurso_ref INTEGER,
                apostas      TEXT NOT NULL,
                scores       TEXT NOT NULL,
                method       TEXT NOT NULL
            )
        """)
        await db.commit()


async def upsert_draw(draw: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            INSERT OR REPLACE INTO draws
                (concurso, data, dezenas, premio_15, premio_14, premio_13, premio_12, premio_11, acumulado, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            draw["concurso"],
            draw["data"],
            json.dumps(sorted(draw["dezenas"])),
            draw.get("premio_15"),
            draw.get("premio_14"),
            draw.get("premio_13"),
            draw.get("premio_12"),
            draw.get("premio_11"),
            int(draw.get("acumulado", 0)),
            draw.get("fetched_at", datetime.now(timezone.utc).isoformat()),
        ))
        await db.commit()


async def upsert_draws_bulk(draws: list[dict]) -> None:
    if not draws:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        now = datetime.now(timezone.utc).isoformat()
        await db.executemany("""
            INSERT OR REPLACE INTO draws
                (concurso, data, dezenas, premio_15, premio_14, premio_13, premio_12, premio_11, acumulado, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                d["concurso"], d["data"], json.dumps(sorted(d["dezenas"])),
                d.get("premio_15"), d.get("premio_14"), d.get("premio_13"),
                d.get("premio_12"), d.get("premio_11"),
                int(d.get("acumulado", 0)),
                d.get("fetched_at", now),
            )
            for d in draws
        ])
        await db.commit()


async def get_all_draws() -> pd.DataFrame:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM draws ORDER BY concurso") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        return pd.DataFrame(columns=["concurso", "data", "dezenas", "premio_15",
                                      "premio_14", "premio_13", "premio_12", "premio_11",
                                      "acumulado", "fetched_at"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["dezenas"] = df["dezenas"].apply(json.loads)
    return df


async def get_latest_concurso() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(concurso) FROM draws") as cursor:
            row = await cursor.fetchone()
    return row[0] if row and row[0] else 0


async def count_draws() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM draws") as cursor:
            row = await cursor.fetchone()
    return row[0] if row else 0


async def save_prediction(concurso_ref: int, apostas: list, scores: list, method: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            INSERT INTO predictions (generated_at, concurso_ref, apostas, scores, method)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            concurso_ref,
            json.dumps(apostas),
            json.dumps(scores),
            method,
        ))
        await db.commit()


async def get_latest_prediction() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM predictions ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    r = dict(row)
    r["apostas"] = json.loads(r["apostas"])
    r["scores"] = json.loads(r["scores"])
    return r


async def get_recent_predictions(limit: int = 5) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM predictions ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
    result = []
    for row in rows:
        r = dict(row)
        r["apostas"] = json.loads(r["apostas"])
        r["scores"] = json.loads(r["scores"])
        result.append(r)
    return result
