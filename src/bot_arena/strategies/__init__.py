from bot_arena.strategies.base import Strategy
from bot_arena.strategies.connors_rsi2 import ConnorsRSI2
from bot_arena.strategies.dual_momentum import DualMomentum
from bot_arena.strategies.equal_weight import EqualWeight
from bot_arena.strategies.faber_trend import FaberTrend
from bot_arena.strategies.hodler import SpyHodler
from bot_arena.strategies.mean_reversion import MeanReversion
from bot_arena.strategies.momentum import Momentum
from bot_arena.strategies.monkey import RandomMonkey
from bot_arena.strategies.vol_target import VolTarget
from bot_arena.strategies.winners import Winners12m1


def roster(seed: int = 42) -> list[Strategy]:
    """The bots in the live paper run."""
    return [SpyHodler(), Momentum(), MeanReversion(), RandomMonkey(seed)]


def full_roster(seed: int = 42) -> list[Strategy]:
    """Everyone, incl. strategies from published research (see docs/strategies.md)."""
    return [
        *roster(seed),
        FaberTrend(),
        DualMomentum(),
        EqualWeight(),
        VolTarget(),
        ConnorsRSI2(),
        Winners12m1(),
    ]


__all__ = [
    "ConnorsRSI2",
    "DualMomentum",
    "EqualWeight",
    "FaberTrend",
    "MeanReversion",
    "Momentum",
    "RandomMonkey",
    "SpyHodler",
    "Strategy",
    "VolTarget",
    "Winners12m1",
    "full_roster",
    "roster",
]
