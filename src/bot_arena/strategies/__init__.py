from bot_arena.strategies.base import Strategy
from bot_arena.strategies.hodler import SpyHodler
from bot_arena.strategies.mean_reversion import MeanReversion
from bot_arena.strategies.momentum import Momentum
from bot_arena.strategies.monkey import RandomMonkey


def roster(seed: int = 42) -> list[Strategy]:
    """The bots that compete in the arena."""
    return [SpyHodler(), Momentum(), MeanReversion(), RandomMonkey(seed)]


__all__ = ["MeanReversion", "Momentum", "RandomMonkey", "SpyHodler", "Strategy", "roster"]
