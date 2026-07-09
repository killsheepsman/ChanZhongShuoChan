from __future__ import annotations

from .models import Center


def classify_trend(centers: list[Center]) -> dict[str, object]:
    if not centers:
        return {"type": "unclassified", "direction": None, "center_count": 0, "reason": "未形成中枢"}
    if len(centers) == 1:
        return {"type": "consolidation", "direction": None, "center_count": 1, "reason": "仅形成一个中枢，按盘整处理"}

    previous = centers[-2]
    current = centers[-1]
    if current.zd > previous.zg:
        return {"type": "trend", "direction": "up", "center_count": len(centers), "reason": "后中枢 ZD 高于前中枢 ZG"}
    if current.zg < previous.zd:
        return {"type": "trend", "direction": "down", "center_count": len(centers), "reason": "后中枢 ZG 低于前中枢 ZD"}
    return {"type": "consolidation", "direction": None, "center_count": len(centers), "reason": "后中枢与前中枢仍有重叠"}
