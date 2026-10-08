import numpy as np
import pandas as pd
import pytest

from bot_arena import study
from bot_arena.engine import run_backtest
from bot_arena.risk import RiskLimits
from bot_arena.strategies import MeanReversion, full_roster

SYMBOLS = ["AAA", "LATE", "QQQ", "SPY"]


def market(n=420, seed=3):
    """Two years of prices; LATE only lists halfway through (NaN before)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2016-01-04", periods=n, freq="B", tz="UTC")
    closes = pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n))) for s in SYMBOLS}, index=idx
    )
    closes.loc[: idx[n // 2], "LATE"] = np.nan
    return closes, closes


UNIVERSE = study.Universe("test", "synthetic", study.data.BARS_FILE, SYMBOLS)
TRADE_FROM = "2016-07-01"


@pytest.fixture(scope="module")
def result(monkeypatch_module):
    opens, closes = market()
    return study.run_universe(UNIVERSE, opens, closes, trade_from=TRADE_FROM, fee=1.0)


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    mp.setattr(study, "MONKEY_SEEDS", 3)
    yield mp
    mp.undo()


def test_every_contestant_runs_including_qqq_hodler(result):
    assert set(result.results) == {b.name for b in full_roster()} | {"QQQ Hodler"}
    assert set(result.with_fee) == set(result.results) == set(result.with_breaker)
    assert len(result.monkeys) == 3


def test_main_results_run_without_the_breaker_and_the_breaker_table_shows_it():
    _, closes = market()
    crash = closes.copy()
    crash.iloc[300:320] *= 0.5  # everyone halves for a while, then recovers
    crash.iloc[320:] *= 2.0
    u = study.run_universe(UNIVERSE, crash, crash, trade_from=TRADE_FROM, fee=1.0)
    assert u.results["SPY Hodler"].status == "active"
    assert u.with_breaker["SPY Hodler"].status == "eliminated"
    row = next(r for r in study.breaker_table(u).splitlines() if "SPY Hodler" in r)
    assert "survived" not in row


def test_not_yet_listed_symbols_are_never_traded_early(result):
    listed = market()[1]["LATE"].first_valid_index()
    for r in result.results.values():
        assert all(f.date > listed for f in r.fills if f.symbol == "LATE"), r.strategy.name


def test_mean_reversion_copes_with_unlisted_symbols_with_or_without_the_wrapper():
    # It used to crash (IndexError) on a symbol with no prices yet; last_rsi now returns NaN.
    opens, closes = market()
    start = pd.Timestamp(TRADE_FROM, tz="UTC")
    run_backtest(MeanReversion(), opens, closes, 1000, trade_from=start, limits=RiskLimits())
    run_backtest(study.Listed(MeanReversion()), opens, closes, 1000, trade_from=start, limits=RiskLimits())


def test_spy_hodler_has_beta_one_against_spy(result):
    # Not exactly 1: it buys at the next open (not a close) and pays slippage, so the first days differ.
    beta, r2, alpha = study.versus(result.results["SPY Hodler"].equity, result.market)
    assert beta == pytest.approx(1.0, abs=0.03) and r2 == pytest.approx(1.0, abs=0.03)
    assert alpha == pytest.approx(0.0, abs=0.02)


def test_yearly_returns_chain_to_the_total():
    idx = pd.to_datetime(["2016-06-01", "2016-12-30", "2017-06-01", "2017-12-29"], utc=True)
    equity = pd.Series([1000.0, 1100.0, 990.0, 1210.0], index=idx)
    yearly = study.yearly_returns(equity)
    assert yearly.loc[2016] == pytest.approx(0.10) and yearly.loc[2017] == pytest.approx(0.10)
    assert (1 + yearly).prod() - 1 == pytest.approx(0.21)


def test_bear_window_slicing():
    idx = pd.date_range("2020-02-17", periods=8, freq="B", tz="UTC")
    equity = pd.Series([100, 110, 100, 90, 99, 80, 85, 120.0], index=idx)
    ret, dd = study.window(equity, "2020-02-18", "2020-02-25")  # 110 -> 85, with a low of 80 inside
    assert ret == pytest.approx(85 / 110 - 1) and dd == pytest.approx(80 / 110 - 1)
    assert study.window(equity, "2019-01-01", "2019-02-01") is None


def test_tables_have_one_row_per_bot(result):
    n = len(result.results)
    tables = (study.summary_table, study.yearly_table, study.bear_table, study.breaker_table)
    for table in (t(result) for t in tables):
        assert len(table.splitlines()) == n + 2  # header + separator + rows
    yearly_header = study.yearly_table(result).splitlines()[0]
    assert "2016" in yearly_header and "2017 YTD" in yearly_header and "Beat QQQ" in yearly_header
    assert len(study.monkey_table(result).splitlines()) == 4


def test_sharpe_standard_error_shrinks_with_time():
    assert study.sharpe_standard_error(1.0, 10) < study.sharpe_standard_error(1.0, 1)
    assert study.sharpe_standard_error(1.0, 10) == pytest.approx(((1 + 0.5) / 10) ** 0.5)


def test_universe_limits_allow_every_symbol_at_once():
    limits = study.UNIVERSES["sectors"].limits()
    assert limits.max_positions == 13 and limits.max_drawdown is None
    assert study.UNIVERSES["sectors"].limits(breaker=True).max_drawdown == 0.30
