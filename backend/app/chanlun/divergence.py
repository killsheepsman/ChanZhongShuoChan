from __future__ import annotations

from .models import Center, Divergence, Segment


def detect_divergences(
    segments: list[Segment], centers: list[Center], macd: list[dict[str, float]] | None = None
) -> list[Divergence]:
    """Detect standard trend divergence with the same 0.90 rule as type-1 signals."""
    positions = {segment.id: index for index, segment in enumerate(segments)}
    divergences: list[Divergence] = []
    run_direction: str | None = None
    run_length = 0
    for center in centers:
        if center.direction not in ("UP", "DOWN"):
            run_direction = None
            run_length = 0
            continue
        if center.direction == run_direction:
            run_length += 1
        else:
            run_direction = center.direction
            run_length = 1
        if run_length < 2 or not center.segment_ids:
            continue

        expected = "down" if center.direction == "DOWN" else "up"
        first_position = positions.get(center.segment_ids[0])
        if first_position is None or first_position == 0:
            continue
        enter = segments[first_position - 1]
        leave = _leave(center, segments, expected)
        if leave is None or enter.direction != expected:
            continue
        enter_power = abs(enter.end_price - enter.start_price)
        leave_power = abs(leave.end_price - leave.start_price)
        if enter_power <= 0 or leave_power / enter_power >= 0.90:
            continue
        ratio = leave_power / enter_power
        divergences.append(
            Divergence(
                segment_id=leave.id,
                side="buy" if expected == "down" else "sell",
                kind="trend",
                strength=round(1 - ratio, 3),
                reason=f"连续同向中枢趋势背驰，离开段/进入段力度比 {ratio:.3f}",
            )
        )
    return divergences


def _leave(center: Center, segments: list[Segment], direction: str) -> Segment | None:
    member_ids = set(center.segment_ids)
    members = [segment for segment in segments if segment.id in member_ids]
    for segment in reversed(members[2:]):
        outside = segment.end_price < center.zd if direction == "down" else segment.end_price > center.zg
        if segment.direction == direction and outside:
            return segment
    return None
