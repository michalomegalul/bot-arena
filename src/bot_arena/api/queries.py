"""Database reads behind the API. Plain SQL in, contract models out."""

import pandas as pd
import psycopg

from bot_arena import metrics
from bot_arena.api.models import (
    BotDetail,
    BotSummary,
    EquityPoint,
    EquitySeries,
    JournalEntry,
    Leaderboard,
    Position,
    PricePoint,
    RiskEvent,
    Run,
    Trade,
)
from bot_arena.strategies import SpyHodler

BENCHMARK = SpyHodler.name
SPARKLINE_POINTS = 30


class NotFound(Exception):
    pass


def _day(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%d")


def _opt(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


# --- runs ---

_RUN_SQL = """
    SELECT r.id, r.kind, r.topic, r.start_date, r.end_date, r.started_at, count(b.id)
    FROM runs r LEFT JOIN bots b ON b.run_id = r.id
"""


def _run(row) -> Run:
    id_, kind, topic, start, end, started_at, bots = row
    return Run(
        id=id_,
        kind=kind,
        topic=topic,
        start_date=start.isoformat() if start else None,
        end_date=end.isoformat() if end else None,
        started_at=started_at.isoformat(),
        bots=bots,
    )


def runs(conn: psycopg.Connection) -> list[Run]:
    rows = conn.execute(_RUN_SQL + " GROUP BY r.id ORDER BY r.id DESC").fetchall()
    return [_run(r) for r in rows]


def run(conn: psycopg.Connection, run_id: int) -> Run:
    row = conn.execute(_RUN_SQL + " WHERE r.id = %s GROUP BY r.id", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"run {run_id} not found")
    return _run(row)


def default_run(conn: psycopg.Connection) -> Run:
    """The live paper run once it has any equity data, otherwise the newest backtest."""
    row = (
        conn.execute(
            """
        SELECT r.id FROM runs r
        WHERE r.kind IN ('paper', 'live')
          AND EXISTS (SELECT 1 FROM bots b JOIN equity_snapshots e ON e.bot_id = b.id WHERE b.run_id = r.id)
        ORDER BY r.id DESC LIMIT 1
        """
        ).fetchone()
        or conn.execute("SELECT id FROM runs ORDER BY (kind = 'backtest') DESC, id DESC LIMIT 1").fetchone()
    )
    if row is None:
        raise NotFound("no runs yet")
    return run(conn, row[0])


# --- bots and equity ---


def _bots(conn: psycopg.Connection, run_id: int) -> list[tuple]:
    return conn.execute(
        "SELECT id, name, emoji, status, starting_cash FROM bots WHERE run_id = %s ORDER BY id", (run_id,)
    ).fetchall()


def _equity_frames(conn: psycopg.Connection, bot_ids: list[int]) -> dict[int, pd.DataFrame]:
    rows = conn.execute(
        "SELECT bot_id, ts, equity, exposure FROM equity_snapshots WHERE bot_id = ANY(%s) ORDER BY ts",
        (bot_ids,),
    ).fetchall()
    frame = pd.DataFrame(rows, columns=["bot_id", "ts", "equity", "exposure"])
    return {bot_id: frame[frame.bot_id == bot_id].set_index("ts") for bot_id in bot_ids}


def _trade_counts(conn: psycopg.Connection, bot_ids: list[int]) -> dict[int, int]:
    rows = conn.execute(
        "SELECT bot_id, count(*) FROM trades WHERE bot_id = ANY(%s) GROUP BY bot_id", (bot_ids,)
    ).fetchall()
    return dict(rows)


def _summaries(conn: psycopg.Connection, run_id: int) -> list[BotSummary]:
    bots = _bots(conn, run_id)
    ids = [b[0] for b in bots]
    frames, counts = _equity_frames(conn, ids), _trade_counts(conn, ids)

    summaries = []
    for bot_id, name, emoji, status, cash in bots:
        frame = frames[bot_id]
        # Start every curve at the starting cash, so returns count from $1000, not from day one's close.
        equity = pd.concat([pd.Series([float(cash)]), frame["equity"].astype(float)], ignore_index=True)
        has_data = not frame.empty
        summaries.append(
            BotSummary(
                id=bot_id,
                name=name,
                emoji=emoji,
                status=status,
                is_benchmark=name == BENCHMARK,
                rank=0,
                starting_cash=float(cash),
                equity=float(equity.iloc[-1]) if has_data else None,
                total_return=metrics.total_return(equity) if has_data else None,
                max_drawdown=metrics.max_drawdown(equity) if has_data else None,
                sharpe=metrics.sharpe(equity) if len(frame) > 1 else None,
                sortino=metrics.sortino(equity) if len(frame) > 1 else None,
                exposure=_opt(frame["exposure"].iloc[-1]) if has_data else None,
                trades=counts.get(bot_id, 0),
                sparkline=[float(v) for v in frame["equity"].iloc[-SPARKLINE_POINTS:]],
            )
        )
    ranked = sorted(summaries, key=lambda s: (-(s.equity or s.starting_cash), s.name))
    for rank, summary in enumerate(ranked, start=1):
        summary.rank = rank
    return ranked


def leaderboard(conn: psycopg.Connection, run_id: int) -> Leaderboard:
    the_run = run(conn, run_id)
    as_of = conn.execute(
        "SELECT max(e.ts) FROM equity_snapshots e JOIN bots b ON b.id = e.bot_id WHERE b.run_id = %s",
        (run_id,),
    ).fetchone()[0]
    return Leaderboard(run=the_run, as_of=_day(as_of) if as_of else None, bots=_summaries(conn, run_id))


def equity(conn: psycopg.Connection, run_id: int, since: str | None = None) -> list[EquitySeries]:
    run(conn, run_id)
    bots = _bots(conn, run_id)
    frames = _equity_frames(conn, [b[0] for b in bots])
    out = []
    for bot_id, name, emoji, _, _ in bots:
        frame = frames[bot_id]
        points = [EquityPoint(t=_day(ts), v=float(v)) for ts, v in frame["equity"].items()]
        if since:
            points = [p for p in points if p.t > since]
        out.append(
            EquitySeries(bot_id=bot_id, name=name, emoji=emoji, is_benchmark=name == BENCHMARK, points=points)
        )
    return out


# --- trades and risk events ---


def trades(
    conn: psycopg.Connection, run_id: int, limit: int = 100, bot_id: int | None = None, after_id: int = 0
) -> list[Trade]:
    run(conn, run_id)
    rows = conn.execute(
        """
        SELECT t.id, t.bot_id, b.name, b.emoji, t.ts, t.symbol, t.side, t.shares, t.price, t.fee
        FROM trades t JOIN bots b ON b.id = t.bot_id
        WHERE b.run_id = %s AND (%s::bigint IS NULL OR t.bot_id = %s) AND t.id > %s
        ORDER BY t.ts DESC, t.id DESC LIMIT %s
        """,
        (run_id, bot_id, bot_id, after_id, limit),
    ).fetchall()
    return [
        Trade(
            id=id_,
            bot_id=b_id,
            bot=name,
            emoji=emoji,
            t=_day(ts),
            symbol=sym,
            side=side,
            shares=float(shares),
            price=float(price),
            value=float(shares) * float(price),
            fee=float(fee),
        )
        for id_, b_id, name, emoji, ts, sym, side, shares, price, fee in rows
    ]


def risk_events(
    conn: psycopg.Connection, run_id: int, limit: int = 100, bot_id: int | None = None, after_id: int = 0
) -> list[RiskEvent]:
    run(conn, run_id)
    rows = conn.execute(
        """
        SELECT r.id, r.bot_id, b.name, b.emoji, r.ts, r.kind, r.detail
        FROM risk_events r JOIN bots b ON b.id = r.bot_id
        WHERE b.run_id = %s AND (%s::bigint IS NULL OR r.bot_id = %s) AND r.id > %s
        ORDER BY r.ts DESC, r.id DESC LIMIT %s
        """,
        (run_id, bot_id, bot_id, after_id, limit),
    ).fetchall()
    return [
        RiskEvent(id=id_, bot_id=b_id, bot=name, emoji=emoji, t=_day(ts), kind=kind, detail=detail)
        for id_, b_id, name, emoji, ts, kind, detail in rows
    ]


# --- one bot ---


def bot_detail(conn: psycopg.Connection, run_id: int, bot_id: int) -> BotDetail:
    summary = next((s for s in _summaries(conn, run_id) if s.id == bot_id), None)
    if summary is None:
        raise NotFound(f"bot {bot_id} not found in run {run_id}")

    rows = conn.execute(
        """
        SELECT p.symbol, p.shares,
               (SELECT close FROM bars WHERE bars.symbol = p.symbol ORDER BY ts DESC LIMIT 1)
        FROM positions p WHERE p.bot_id = %s ORDER BY p.symbol
        """,
        (bot_id,),
    ).fetchall()
    positions = []
    for symbol, shares, price in rows:
        value = float(shares) * float(price) if price is not None else None
        weight = value / summary.equity if value is not None and summary.equity else None
        positions.append(
            Position(symbol=symbol, shares=float(shares), price=_opt(price), value=value, weight=weight)
        )

    return BotDetail(
        summary=summary,
        positions=positions,
        trades=trades(conn, run_id, limit=500, bot_id=bot_id),
        risk_events=risk_events(conn, run_id, limit=500, bot_id=bot_id),
    )


# --- AI journal ---


def journal(conn: psycopg.Connection, run_id: int, bot_id: int | None = None) -> list[JournalEntry]:
    """LLM decisions, newest first, each with the bot's and the benchmark's return until the
    bot's next decision (or the latest close, for the newest one)."""
    run(conn, run_id)
    rows = conn.execute(
        """
        SELECT j.id, j.bot_id, b.name, b.emoji, j.model, j.ts, j.targets, j.reasoning, j.confidence,
               j.notes, j.stats
        FROM journal j JOIN bots b ON b.id = j.bot_id
        WHERE b.run_id = %s AND (%s::bigint IS NULL OR j.bot_id = %s)
        ORDER BY j.ts DESC, j.id DESC
        """,
        (run_id, bot_id, bot_id),
    ).fetchall()
    if not rows:
        return []

    bots = _bots(conn, run_id)
    frames = _equity_frames(conn, [b[0] for b in bots])
    curves = {b_id: frames[b_id]["equity"].astype(float).rename(index=_day) for b_id, *_ in bots}
    benchmark = next((curves[b_id] for b_id, name, *_ in bots if name == BENCHMARK), None)

    def change(curve, start, end):
        if curve is None or start not in curve.index or end not in curve.index:
            return None
        return float(curve[end] / curve[start] - 1)

    next_decision: dict[int, str] = {}
    out = []
    for id_, b_id, name, emoji, model, ts, targets, reasoning, confidence, notes, stats in rows:
        t = _day(ts)
        curve = curves.get(b_id)
        until = next_decision.get(b_id) or (curve.index[-1] if curve is not None and len(curve) else None)
        next_decision[b_id] = t  # rows are newest first, so this is the next decision of the older row
        out.append(
            JournalEntry(
                id=id_,
                bot_id=b_id,
                bot=name,
                emoji=emoji,
                model=model,
                t=t,
                targets=targets,
                reasoning=reasoning,
                confidence=confidence,
                notes=notes,
                seconds=stats.get("seconds"),
                until=until if until and until > t else None,
                outcome=change(curve, t, until) if until and until > t else None,
                benchmark_outcome=change(benchmark, t, until) if until and until > t else None,
            )
        )
    return out


# --- prices ---


def prices(conn: psycopg.Connection, symbol: str, start: str | None, end: str | None) -> list[PricePoint]:
    rows = conn.execute(
        """
        SELECT DISTINCT ON ((ts AT TIME ZONE 'UTC')::date) ts, open, close FROM bars
        WHERE symbol = %s AND (%s::date IS NULL OR ts >= %s::date) AND (%s::date IS NULL OR ts < %s::date + 1)
        ORDER BY (ts AT TIME ZONE 'UTC')::date, ts DESC
        """,
        (symbol.upper(), start, start, end, end),
    ).fetchall()
    if not rows:
        raise NotFound(f"no prices for {symbol}")
    return [PricePoint(t=_day(ts), open=float(o), close=float(c)) for ts, o, c in rows]
