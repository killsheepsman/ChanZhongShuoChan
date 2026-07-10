from __future__ import annotations

from .models import BuySellSignal, Center, Divergence, KLine, Segment, TheoryMark


def detect_theory_marks(
    klines: list[KLine],
    segments: list[Segment],
    centers: list[Center],
    divergences: list[Divergence],
    signals: list[BuySellSignal],
    macd: list[dict[str, float]],
) -> list[TheoryMark]:
    marks: list[TheoryMark] = []
    marks.extend(_segment_break_marks(segments))
    marks.extend(_center_marks(centers, segments))
    marks.extend(_center_leave_and_retest_marks(centers, segments))
    marks.extend(_trend_state_marks(centers))
    marks.extend(_macd_zero_marks(klines, macd))
    return _dedupe_marks(marks)


def _segment_break_marks(segments: list[Segment]) -> list[TheoryMark]:
    marks: list[TheoryMark] = []
    for previous, current in zip(segments, segments[1:]):
        if previous.status != "CONFIRMED":
            continue
        side = "sell" if previous.direction == "up" else "buy"
        marks.append(
            TheoryMark(
                id=f"segment-break-{previous.id}",
                kind="segment_break",
                index=previous.end_index,
                time=previous.end_time,
                price=previous.end_price,
                label=f"线{previous.id + 1}破坏",
                reason="反向线段形成，旧线段确认结束，新线段从该点开始",
                side=side,
                segment_id=previous.id,
            )
        )
    return marks


def _center_marks(centers: list[Center], segments: list[Segment]) -> list[TheoryMark]:
    by_id = {segment.id: segment for segment in segments}
    marks: list[TheoryMark] = []
    for center in centers:
        formation_id = center.segment_ids[2] if len(center.segment_ids) >= 3 else center.segment_ids[-1]
        formation = by_id.get(formation_id)
        if formation:
            marks.append(
                TheoryMark(
                    id=f"center-formed-{center.id}",
                    kind="center_formed",
                    index=formation.end_index,
                    time=formation.end_time,
                    price=(center.zg + center.zd) / 2,
                    label=f"中枢{center.id + 1}形成",
                    reason=f"连续三线段重叠区间 [ZD={center.zd:.2f}, ZG={center.zg:.2f}]",
                    center_id=center.id,
                    segment_id=formation.id,
                )
            )
        for segment_id in center.segment_ids[3:]:
            segment = by_id.get(segment_id)
            if not segment:
                continue
            marks.append(
                TheoryMark(
                    id=f"center-extend-{center.id}-{segment.id}",
                    kind="center_extend",
                    index=segment.end_index,
                    time=segment.end_time,
                    price=(center.zg + center.zd) / 2,
                    label=f"中枢{center.id + 1}延伸",
                    reason="后续线段与中枢 [ZD, ZG] 仍有重叠，走势继续围绕该中枢震荡",
                    center_id=center.id,
                    segment_id=segment.id,
                )
            )
    return marks


def _center_leave_and_retest_marks(centers: list[Center], segments: list[Segment]) -> list[TheoryMark]:
    marks: list[TheoryMark] = []
    for center in centers:
        if not center.segment_ids:
            continue
        after = [segment for segment in segments if segment.id > center.segment_ids[-1]]
        for leave, retest in zip(after, after[1:]):
            if leave.high > center.zg and leave.direction == "up":
                marks.append(
                    TheoryMark(
                        id=f"center-leave-up-{center.id}-{leave.id}",
                        kind="center_leave",
                        index=leave.end_index,
                        time=leave.end_time,
                        price=leave.high,
                        label=f"离开中枢{center.id + 1}上",
                        reason="次级别走势向上离开中枢，为三买观察前提",
                        side="buy",
                        center_id=center.id,
                        segment_id=leave.id,
                    )
                )
                if retest.direction == "down" and retest.low > center.zg:
                    marks.append(
                        TheoryMark(
                            id=f"center-retest-b3-{center.id}-{retest.id}",
                            kind="center_retest",
                            index=retest.end_index,
                            time=retest.end_time,
                            price=retest.low,
                            label=f"三买前提",
                            reason=f"向上离开中枢后回试低点 {retest.low:.2f} 未跌破 ZG={center.zg:.2f}",
                            side="buy",
                            center_id=center.id,
                            segment_id=retest.id,
                        )
                    )
                break
            if leave.low < center.zd and leave.direction == "down":
                marks.append(
                    TheoryMark(
                        id=f"center-leave-down-{center.id}-{leave.id}",
                        kind="center_leave",
                        index=leave.end_index,
                        time=leave.end_time,
                        price=leave.low,
                        label=f"离开中枢{center.id + 1}下",
                        reason="次级别走势向下离开中枢，为三卖观察前提",
                        side="sell",
                        center_id=center.id,
                        segment_id=leave.id,
                    )
                )
                if retest.direction == "up" and retest.high < center.zd:
                    marks.append(
                        TheoryMark(
                            id=f"center-retest-s3-{center.id}-{retest.id}",
                            kind="center_retest",
                            index=retest.end_index,
                            time=retest.end_time,
                            price=retest.high,
                            label=f"三卖前提",
                            reason=f"向下离开中枢后回抽高点 {retest.high:.2f} 未升破 ZD={center.zd:.2f}",
                            side="sell",
                            center_id=center.id,
                            segment_id=retest.id,
                        )
                    )
                break
    return marks


def _trend_state_marks(centers: list[Center]) -> list[TheoryMark]:
    marks: list[TheoryMark] = []
    for previous, current in zip(centers, centers[1:]):
        if current.zd > previous.zg:
            marks.append(
                TheoryMark(
                    id=f"trend-up-{current.id}",
                    kind="trend_state",
                    index=current.start_index,
                    time=current.start_time,
                    price=current.zd,
                    label="上涨趋势",
                    reason="后中枢 ZD 高于前中枢 ZG，两个同级别中枢无重叠",
                    side="buy",
                    center_id=current.id,
                )
            )
        elif current.zg < previous.zd:
            marks.append(
                TheoryMark(
                    id=f"trend-down-{current.id}",
                    kind="trend_state",
                    index=current.start_index,
                    time=current.start_time,
                    price=current.zg,
                    label="下跌趋势",
                    reason="后中枢 ZG 低于前中枢 ZD，两个同级别中枢无重叠",
                    side="sell",
                    center_id=current.id,
                )
            )
        else:
            marks.append(
                TheoryMark(
                    id=f"consolidation-{current.id}",
                    kind="trend_state",
                    index=current.start_index,
                    time=current.start_time,
                    price=(current.zg + current.zd) / 2,
                    label="盘整延续",
                    reason="相邻同级别中枢仍有重叠，尚未形成趋势",
                    center_id=current.id,
                )
            )
    return marks


def _macd_zero_marks(klines: list[KLine], macd: list[dict[str, float]]) -> list[TheoryMark]:
    marks: list[TheoryMark] = []
    for index in range(1, min(len(klines), len(macd))):
        previous = macd[index - 1]["dif"]
        current = macd[index]["dif"]
        if previous <= 0 < current:
            kline = klines[index]
            marks.append(
                TheoryMark(
                    id=f"macd-up-zero-{index}",
                    kind="macd_zero",
                    index=kline.index,
                    time=kline.time,
                    price=kline.low,
                    label="DIF上0轴",
                    reason="MACD DIF 从零轴下方进入零轴上方，二买/上涨延续观察条件",
                    side="buy",
                )
            )
        elif previous >= 0 > current:
            kline = klines[index]
            marks.append(
                TheoryMark(
                    id=f"macd-down-zero-{index}",
                    kind="macd_zero",
                    index=kline.index,
                    time=kline.time,
                    price=kline.high,
                    label="DIF下0轴",
                    reason="MACD DIF 从零轴上方进入零轴下方，二卖/下跌延续观察条件",
                    side="sell",
                )
            )
    return marks


def _dedupe_marks(marks: list[TheoryMark]) -> list[TheoryMark]:
    kept: dict[str, TheoryMark] = {}
    for mark in marks:
        kept[mark.id] = mark
    return sorted(kept.values(), key=lambda item: (item.index, item.kind, item.id))
