from __future__ import annotations

from .models import KLine


EMA12_ALPHA = 2 / 13
EMA26_ALPHA = 2 / 27
DEA_ALPHA = 2 / 10


def calculate_macd(klines: list[KLine]) -> list[dict[str, float]]:
    return continue_macd([], klines)


def continue_macd(
    previous: list[dict[str, float]], klines: list[KLine]
) -> list[dict[str, float]]:
    """Advance recursive EMA state without replaying prior closes."""
    result = list(previous)
    if previous:
        ema12 = previous[-1]["ema12"]
        ema26 = previous[-1]["ema26"]
        dea = previous[-1]["dea"]
    else:
        ema12 = ema26 = dea = 0.0

    for kline in klines:
        if not result:
            ema12 = ema26 = kline.close
            dif = 0.0
            dea = 0.0
        else:
            ema12 = EMA12_ALPHA * kline.close + (1 - EMA12_ALPHA) * ema12
            ema26 = EMA26_ALPHA * kline.close + (1 - EMA26_ALPHA) * ema26
            dif = ema12 - ema26
            dea = DEA_ALPHA * dif + (1 - DEA_ALPHA) * dea
        result.append(
            {
                "dif": float(dif),
                "dea": float(dea),
                "hist": float((dif - dea) * 2),
                "ema12": float(ema12),
                "ema26": float(ema26),
            }
        )
    return result


def macd_area(macd: list[dict[str, float]], start: int, end: int) -> float:
    left = max(0, start)
    right = min(len(macd) - 1, end)
    if right < left:
        return 0.0
    return sum(item["hist"] for item in macd[left : right + 1])
