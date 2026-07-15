from __future__ import annotations

from dataclasses import replace

from .models import BuySellSignal, Center, KLine, Segment, Stroke


def detect_buy_sell_points(
    segments: list[Segment],
    centers: list[Center],
    divergences: list[object] | None = None,
    klines: list[KLine] | None = None,
    strokes: list[Stroke] | None = None,
) -> list[BuySellSignal]:
    """Identify the three Chan signal classes from completed structure."""
    segment_items = sorted(segments, key=lambda item: item.id)
    first = _first_points(segment_items, centers)
    second = _second_points(segment_items, first)
    third = _third_points(segment_items, centers)
    signals = _resolve_conflicts([*first, *second, *third])
    latest_index = (klines or [])[-1].index if klines else None
    return [_expire(signal, latest_index) for signal in sorted(signals, key=lambda item: item.index)]


def _first_points(segments: list[Segment], centers: list[Center]) -> list[BuySellSignal]:
    signals: list[BuySellSignal] = []
    positions = {segment.id: index for index, segment in enumerate(segments)}
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
        leave = _directional_leave(center, segments, positions, expected)
        if enter.direction != expected or leave is None:
            continue
        enter_power = _power(enter)
        leave_power = _power(leave)
        if enter_power <= 0:
            continue
        ratio = leave_power / enter_power
        if ratio >= 0.90:
            continue

        side = "buy" if expected == "down" else "sell"
        status = _confirmation_after(leave, segments, positions, "up" if side == "buy" else "down")
        signals.append(
            _segment_signal(
                side=side,
                signal_type=1,
                segment=leave,
                status=status,
                confidence=round(min(0.9, 0.68 + (0.9 - ratio) * 0.25), 3),
                reason=f"two-center {center.direction.lower()} trend divergence; leave/enter power ratio {ratio:.3f}",
                center_id=center.id,
                enter_segment_id=enter.id,
                leave_segment_id=leave.id,
                divergence_ratio=round(ratio, 3),
                strength=4 if ratio < 0.6 else 3,
            )
        )
    return signals


def _second_points(segments: list[Segment], first_points: list[BuySellSignal]) -> list[BuySellSignal]:
    positions = {segment.id: index for index, segment in enumerate(segments)}
    signals: list[BuySellSignal] = []
    for first in first_points:
        if first.status != "confirmed" or first.leave_segment_id is None:
            continue
        position = positions.get(first.leave_segment_id)
        if position is None or position + 2 >= len(segments):
            continue
        reaction = segments[position + 1]
        retest = segments[position + 2]
        expected_reaction = "up" if first.side == "buy" else "down"
        expected_retest = "down" if first.side == "buy" else "up"
        if reaction.direction != expected_reaction or retest.direction != expected_retest:
            continue
        qualifies = retest.low >= first.price if first.side == "buy" else retest.high <= first.price
        if not qualifies:
            continue
        status = _confirmation_after(retest, segments, positions, expected_reaction)
        signals.append(
            _segment_signal(
                side=first.side,
                signal_type=2,
                segment=retest,
                status=status,
                confidence=0.78 if status == "confirmed" else 0.64,
                reason=f"retest after {first.id} did not break the first-point extreme",
                center_id=first.center_id,
                enter_segment_id=reaction.id,
                leave_segment_id=retest.id,
                strength=4,
            )
        )
    return signals


def _third_points(segments: list[Segment], centers: list[Center]) -> list[BuySellSignal]:
    by_id = {segment.id: segment for segment in segments}
    positions = {segment.id: index for index, segment in enumerate(segments)}
    signals: list[BuySellSignal] = []
    for center in centers:
        if center.status != "ENDED" or not center.segment_ids or center.break_segment_id is None:
            continue
        leave = by_id.get(center.segment_ids[-1])
        retest = by_id.get(center.break_segment_id)
        if leave is None or retest is None or leave.status != "CONFIRMED":
            continue

        if (
            leave.direction == "up"
            and leave.end_price > center.zg
            and retest.direction == "down"
            and retest.low > center.zg
        ):
            status = "confirmed" if retest.status == "CONFIRMED" else "candidate"
            signals.append(
                _segment_signal(
                    "buy", 3, retest, status, 0.82 if status == "confirmed" else 0.68,
                    f"upward leave segment {leave.id + 1}; retest stayed above ZG {center.zg:.2f}",
                    center.id, leave_segment_id=leave.id, strength=5,
                )
            )
        elif (
            leave.direction == "down"
            and leave.end_price < center.zd
            and retest.direction == "up"
            and retest.high < center.zd
        ):
            status = "confirmed" if retest.status == "CONFIRMED" else "candidate"
            signals.append(
                _segment_signal(
                    "sell", 3, retest, status, 0.82 if status == "confirmed" else 0.68,
                    f"downward leave segment {leave.id + 1}; retest stayed below ZD {center.zd:.2f}",
                    center.id, leave_segment_id=leave.id, strength=5,
                )
            )
    return signals


def _directional_leave(
    center: Center, segments: list[Segment], positions: dict[int, int], direction: str
) -> Segment | None:
    members = [segment for segment in segments if segment.id in set(center.segment_ids)]
    for segment in reversed(members[2:]):
        outside = segment.end_price < center.zd if direction == "down" else segment.end_price > center.zg
        if segment.direction == direction and outside:
            return segment
    if center.break_segment_id is not None:
        position = positions.get(center.break_segment_id)
        if position is not None:
            candidate = segments[position]
            outside = candidate.end_price < center.zd if direction == "down" else candidate.end_price > center.zg
            if candidate.direction == direction and outside:
                return candidate
    return None


def _confirmation_after(
    segment: Segment, segments: list[Segment], positions: dict[int, int], direction: str
) -> str:
    if segment.status != "CONFIRMED":
        return "candidate"
    position = positions.get(segment.id)
    if position is None or position + 1 >= len(segments):
        return "candidate"
    return "confirmed" if segments[position + 1].direction == direction else "candidate"


def _power(segment: Segment) -> float:
    return abs(segment.end_price - segment.start_price)


def _expire(signal: BuySellSignal, latest_index: int | None) -> BuySellSignal:
    if latest_index is not None and signal.status == "confirmed" and latest_index - signal.index > 10:
        return replace(signal, status="expired")
    return signal


def _resolve_conflicts(signals: list[BuySellSignal]) -> list[BuySellSignal]:
    kept: list[BuySellSignal] = []
    for signal in sorted(signals, key=lambda item: (item.index, -item.type)):
        conflict = next(
            (
                item
                for item in kept
                if item.side == signal.side and abs(item.index - signal.index) <= 3
            ),
            None,
        )
        if conflict is None:
            kept.append(signal)
        elif signal.type > conflict.type:
            kept[kept.index(conflict)] = signal
    return kept


def _segment_signal(
    side: str,
    signal_type: int,
    segment: Segment,
    status: str,
    confidence: float,
    reason: str,
    center_id: int | None,
    *,
    enter_segment_id: int | None = None,
    leave_segment_id: int | None = None,
    divergence_ratio: float | None = None,
    strength: int = 0,
) -> BuySellSignal:
    return BuySellSignal(
        id=f"{side.upper()[0]}{signal_type}_{segment.id + 1:03d}",
        side=side,  # type: ignore[arg-type]
        type=signal_type,  # type: ignore[arg-type]
        index=segment.end_index,
        time=segment.end_time,
        price=segment.low if side == "buy" else segment.high,
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        reason=reason,
        center_id=center_id,
        segment_id=segment.id,
        divergence_ratio=divergence_ratio,
        enter_segment_id=enter_segment_id,
        leave_segment_id=leave_segment_id,
        strength=strength,
    )


def _classify_third_point(signal: BuySellSignal, strokes: list[Stroke], center: Center) -> BuySellSignal:
    """Compatibility helper used by focused regression tests."""
    future = [stroke for stroke in strokes if stroke.start_index >= signal.index]
    for stroke in future:
        if signal.side == "buy":
            if stroke.low <= center.zg:
                return replace(signal, status="invalidated")
            if stroke.direction == "up":
                return replace(signal, status="confirmed")
        else:
            if stroke.high >= center.zd:
                return replace(signal, status="invalidated")
            if stroke.direction == "down":
                return replace(signal, status="confirmed")
    return replace(signal, status="candidate")
