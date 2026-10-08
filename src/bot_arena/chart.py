"""Plot equity curves."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # render to a file, no window needed
import matplotlib.pyplot as plt
import pandas as pd


def plot_equity(curves: dict[str, pd.Series], benchmark: str, cash: float, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, equity in curves.items():
        style = {"linestyle": "--", "color": "black", "linewidth": 2} if name == benchmark else {}
        ax.plot(equity.index, equity.values, label=f"{name}  ${equity.iloc[-1]:,.0f}", **style)
    ax.axhline(cash, color="grey", linewidth=0.8)
    ax.set_title(f"${cash:,.0f} invested on day one, buy and hold")
    ax.set_ylabel("Portfolio value ($)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
