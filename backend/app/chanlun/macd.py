from __future__ import annotations

import pandas as pd

from .models import KLine


def calculate_macd(klines: list[KLine]) -> list[dict[str, float]]:
    closes = pd.Series([kline.close for kline in klines], dtype="float64")
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = (dif - dea) * 2
    return [
        {"dif": float(dif.iloc[i]), "dea": float(dea.iloc[i]), "hist": float(hist.iloc[i])}
        for i in range(len(klines))
    ]


def macd_area(macd: list[dict[str, float]], start: int, end: int) -> float:
    left = max(0, start)
    right = min(len(macd) - 1, end)
    if right < left:
        return 0.0
    return sum(item["hist"] for item in macd[left : right + 1])
