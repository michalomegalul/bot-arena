import pandas as pd
import pytest

from bot_arena.broker import SimBroker

DAY = pd.Timestamp("2026-01-02")


def px(**prices):
    return pd.Series(prices, dtype=float)


def test_buy_applies_slippage_and_fee():
    broker = SimBroker(1000, slippage_bps=100, fee_per_trade=1.0)  # 1% slippage
    broker.rebalance({"AAA": 0.5}, px(AAA=100), DAY)
    (fill,) = broker.fills
    assert fill.side == "buy" and fill.price == pytest.approx(101.0)
    assert broker.positions["AAA"] == pytest.approx(500 / 101)
    assert broker.cash == pytest.approx(1000 - 500 - 1)


def test_all_in_never_makes_cash_negative():
    broker = SimBroker(1000, slippage_bps=50, fee_per_trade=2.0)
    broker.rebalance({"AAA": 0.6, "BBB": 0.4}, px(AAA=10, BBB=20), DAY)
    assert broker.cash >= 0
    assert broker.equity(px(AAA=10, BBB=20)) == pytest.approx(1000 - 2 * 2 - 1000 * 0.005, rel=1e-3)


def test_unlisted_holdings_are_sold_and_sells_fund_buys():
    broker = SimBroker(1000, slippage_bps=0)
    broker.rebalance({"AAA": 1.0}, px(AAA=10, BBB=10), DAY)
    broker.rebalance({"BBB": 1.0}, px(AAA=20, BBB=10), DAY)  # AAA doubled, now switch to BBB
    assert "AAA" not in broker.positions
    assert broker.positions["BBB"] == pytest.approx(200)
    assert [f.side for f in broker.fills] == ["buy", "sell", "buy"]


def test_symbols_without_a_price_are_left_alone():
    broker = SimBroker(1000, slippage_bps=0)
    broker.rebalance({"AAA": 0.5}, px(AAA=10), DAY)
    broker.rebalance({}, px(AAA=float("nan")), DAY)  # "sell everything", but AAA has no price today
    assert broker.positions["AAA"] == pytest.approx(50)


def test_tiny_trades_are_skipped():
    broker = SimBroker(1000, slippage_bps=0)
    broker.rebalance({"AAA": 1.0}, px(AAA=10), DAY)
    broker.rebalance({"AAA": 1.0}, px(AAA=10.001), DAY)  # drift of a few cents
    assert len(broker.fills) == 1


@pytest.mark.parametrize("targets", [{"AAA": -0.1}, {"AAA": 0.7, "BBB": 0.4}, {"AAA": float("nan")}])
def test_shorting_margin_and_nan_are_rejected(targets):
    with pytest.raises(ValueError):
        SimBroker(1000).rebalance(targets, px(AAA=10, BBB=10), DAY)


# --- regressions found in review ---


def test_a_sell_never_costs_more_in_fees_than_it_brings_in():
    # Review repro: a $1.50 sell with a $2 fee used to push cash to -0.50.
    broker = SimBroker(1000, slippage_bps=0, fee_per_trade=2.0)
    broker.rebalance({"A": 1.0}, px(A=10), DAY)
    broker.rebalance({"A": 0.9985}, px(A=10), DAY)
    assert broker.cash >= 0
    assert len(broker.fills) == 1  # the tiny sell was skipped


def test_tiny_trades_are_skipped_when_the_fee_would_eat_them():
    broker = SimBroker(1000, slippage_bps=0, fee_per_trade=5.0)
    broker.rebalance({"A": 0.5}, px(A=10, B=10), DAY)
    broker.rebalance({"A": 0.5, "B": 0.003}, px(A=10, B=10), DAY)  # a $3 buy that costs $5
    assert "B" not in broker.positions


def test_buy_order_does_not_depend_on_set_iteration_order():
    broker = SimBroker(1000, slippage_bps=10)
    broker.rebalance({"ZZZ": 0.5, "AAA": 0.5, "MMM": 0.0}, px(AAA=10, MMM=10, ZZZ=10), DAY)
    assert [f.symbol for f in broker.fills] == ["AAA", "ZZZ"]


def test_holdings_without_a_price_still_count_towards_equity():
    # Review repro: with B unpriced, A used to be sized against $500 instead of $1000.
    broker = SimBroker(1000, slippage_bps=0)
    broker.rebalance({"A": 0.5, "B": 0.5}, px(A=10, B=10), DAY)
    broker.rebalance({"A": 0.5, "C": 0.5}, px(A=10, B=float("nan"), C=10), DAY, last_known=px(B=10))
    assert broker.positions["A"] == pytest.approx(50)  # untouched: still $500 = 50%
    assert broker.positions["B"] == pytest.approx(50)  # can't be sold without a price
    assert "C" not in broker.positions  # no cash left until B can be sold


def test_small_drift_of_an_existing_position_is_left_alone():
    broker = SimBroker(1000, slippage_bps=0)
    broker.rebalance({"A": 0.5, "B": 0.5}, px(A=10, B=10), DAY)
    broker.rebalance({"A": 0.5, "B": 0.5}, px(A=10.3, B=10), DAY)  # A drifted to ~50.7%
    assert len(broker.fills) == 2


def test_selling_out_completely_ignores_the_drift_tolerance():
    broker = SimBroker(1000, slippage_bps=0)
    broker.rebalance({"A": 0.99, "B": 0.01}, px(A=10, B=10), DAY)
    broker.rebalance({"A": 0.99}, px(A=10, B=10), DAY)
    assert "B" not in broker.positions
