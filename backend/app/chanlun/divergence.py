from __future__ import annotations

from .macd import macd_area
from .models import Center, Divergence, Segment


def detect_divergences(segments: list[Segment], centers: list[Center], macd: list[dict[str, float]]) -> list[Divergence]:
    divergences: list[Divergence] = []
    segment_by_id = {segment.id: segment for segment in segments}

    for center in centers:
        enter = _enter_segment(center, segments, segment_by_id)
        leave = _leave_segment(center, segments)
        if not enter or not leave:
            continue

        enter_power = _segment_power(enter, macd)
        leave_power = _segment_power(leave, macd)
        if enter_power <= 0:
            continue

        strength = max(0.0, min(1.0, 1 - leave_power / enter_power))
        if strength < 0.12:
            continue

        trend_kind = _trend_kind(center, centers)
        if leave.direction == "down" and leave.low < center.zd:
            divergences.append(
                Divergence(
                    segment_id=leave.id,
                    side="buy",
                    kind="trend" if trend_kind == "trend_down" else "consolidation",
                    strength=round(strength, 3),
                    reason=f"离开中枢下跌段力度弱于进入段，力度比 {leave_power / enter_power:.2f}",
                )
            )
        elif leave.direction == "up" and leave.high > center.zg:
            divergences.append(
                Divergence(
                    segment_id=leave.id,
                    side="sell",
                    kind="trend" if trend_kind == "trend_up" else "consolidation",
                    strength=round(strength, 3),
                    reason=f"离开中枢上涨段力度弱于进入段，力度比 {leave_power / enter_power:.2f}",
                )
            )
    return divergences


def _enter_segment(center: Center, segments: list[Segment], segment_by_id: dict[int, Segment]) -> Segment | None:
    first_id = center.segment_ids[0] if center.segment_ids else None
    before = [segment for segment in segments if first_id is not None and segment.id < first_id]
    if before:
        return before[-1]
    return segment_by_id.get(center.segment_ids[0]) if center.segment_ids else None


def _leave_segment(center: Center, segments: list[Segment]) -> Segment | None:
    last_center_id = center.segment_ids[-1] if center.segment_ids else None
    after = [segment for segment in segments if last_center_id is not None and segment.id > last_center_id]
    return after[0] if after else None


def _segment_power(segment: Segment, macd: list[dict[str, float]]) -> float:
    area = abs(macd_area(macd, segment.start_index, segment.end_index))
    amplitude = max(segment.high - segment.low, 0.0)
    return area + amplitude


def _trend_kind(center: Center, centers: list[Center]) -> str:
    previous = [item for item in centers if item.end_index < center.start_index]
    if not previous:
        return "consolidation"
    last = previous[-1]
    if center.zd > last.zg:
        return "trend_up"
    if center.zg < last.zd:
        return "trend_down"
    return "consolidation"
