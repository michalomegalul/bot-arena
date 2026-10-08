"""FastAPI app: the read-only arena API, plus the built web UI at /.

Run with `arena api`. There are deliberately no write endpoints; the kill switch and other
admin actions stay on the command line, off the web.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

from bot_arena.api import queries
from bot_arena.api.models import (
    BotDetail,
    EquitySeries,
    FeedMessage,
    Leaderboard,
    PricePoint,
    RiskEvent,
    Run,
    Trade,
)

FEED_POLL_SECONDS = 5.0


def create_app(database_url: str | None = None, web_dir: Path | None = None) -> FastAPI:
    load_dotenv()
    url = database_url or os.environ["DATABASE_URL"]
    pool = ConnectionPool(url, min_size=1, max_size=8, open=False, kwargs={"autocommit": True})

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool.open()
        yield
        pool.close()

    app = FastAPI(title="Bot Arena", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)

    @app.exception_handler(queries.NotFound)
    async def not_found(request: Request, exc: queries.NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    def db(fn, *args, **kwargs):
        with pool.connection() as conn:
            return fn(conn, *args, **kwargs)

    @app.get("/api/health")
    def health() -> dict:
        db(lambda conn: conn.execute("SELECT 1"))
        return {"ok": True}

    @app.get("/api/runs")
    def list_runs() -> list[Run]:
        return db(queries.runs)

    @app.get("/api/runs/default")
    def default_run() -> Run:
        return db(queries.default_run)

    @app.get("/api/runs/{run_id}/leaderboard")
    def leaderboard(run_id: int) -> Leaderboard:
        return db(queries.leaderboard, run_id)

    @app.get("/api/runs/{run_id}/equity")
    def equity(run_id: int) -> list[EquitySeries]:
        return db(queries.equity, run_id)

    @app.get("/api/runs/{run_id}/trades")
    def trades(run_id: int, limit: int = Query(100, ge=1, le=1000), bot_id: int | None = None) -> list[Trade]:
        return db(queries.trades, run_id, limit, bot_id)

    @app.get("/api/runs/{run_id}/risk-events")
    def risk_events(
        run_id: int, limit: int = Query(100, ge=1, le=1000), bot_id: int | None = None
    ) -> list[RiskEvent]:
        return db(queries.risk_events, run_id, limit, bot_id)

    @app.get("/api/runs/{run_id}/bots/{bot_id}")
    def bot(run_id: int, bot_id: int) -> BotDetail:
        return db(queries.bot_detail, run_id, bot_id)

    @app.get("/api/prices/{symbol}")
    def prices(symbol: str, start: str | None = None, end: str | None = None) -> list[PricePoint]:
        return db(queries.prices, symbol, start, end)

    @app.websocket("/api/runs/{run_id}/feed")
    async def feed(websocket: WebSocket, run_id: int):
        """Push new trades, risk events and equity points as the recorder writes them."""
        await websocket.accept()
        try:
            await asyncio.to_thread(db, queries.run, run_id)
        except queries.NotFound:
            await websocket.close(code=4404)
            return

        def latest():
            with pool.connection() as conn:
                t = queries.trades(conn, run_id, limit=1)
                r = queries.risk_events(conn, run_id, limit=1)
                board = queries.leaderboard(conn, run_id)
            return (t[0].id if t else 0), (r[0].id if r else 0), board.as_of

        def news(trade_id, risk_id, as_of):
            with pool.connection() as conn:
                return (
                    queries.trades(conn, run_id, limit=500, after_id=trade_id),
                    queries.risk_events(conn, run_id, limit=500, after_id=risk_id),
                    queries.equity(conn, run_id, since=as_of) if as_of else queries.equity(conn, run_id),
                )

        trade_id, risk_id, as_of = await asyncio.to_thread(latest)

        async def push_news():
            nonlocal trade_id, risk_id, as_of
            while True:
                await asyncio.sleep(FEED_POLL_SECONDS)
                new_trades, new_risks, new_equity = await asyncio.to_thread(news, trade_id, risk_id, as_of)
                for t in reversed(new_trades):  # oldest first
                    await websocket.send_json(FeedMessage(type="trade", trade=t).model_dump())
                    trade_id = max(trade_id, t.id)
                for r in reversed(new_risks):
                    await websocket.send_json(FeedMessage(type="risk", risk=r).model_dump())
                    risk_id = max(risk_id, r.id)
                for series in new_equity:
                    if series.points:
                        await websocket.send_json(FeedMessage(type="equity", equity=series).model_dump())
                        as_of = max(as_of or "", series.points[-1].t)

        async def until_disconnected():
            # With daily data there is usually nothing to send, so a closed tab would never be
            # noticed by push_news alone. Listening for the disconnect ends the task right away.
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass

        tasks = [asyncio.create_task(push_news()), asyncio.create_task(until_disconnected())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    _serve_web(app, web_dir or Path(os.getenv("ARENA_WEB_DIR", "web/dist")))
    return app


def _serve_web(app: FastAPI, web_dir: Path) -> None:
    """Serve the built React app, sending unknown paths to index.html (client-side routing)."""
    index = web_dir / "index.html"
    if not index.exists():
        return
    app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (web_dir / path).resolve()
        if path and file.is_file() and file.is_relative_to(web_dir.resolve()):
            return FileResponse(file)
        return FileResponse(index)
