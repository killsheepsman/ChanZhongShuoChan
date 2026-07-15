from __future__ import annotations

import csv
from pathlib import Path

from app.chanlun.fractal import detect_fractals
from app.chanlun.kline import process_inclusion
from app.chanlun.segment import detect_segments
from app.chanlun.stroke import detect_strokes
from app.services.tdx2db_service import load_tdx2db_klines


SYMBOL = "603703"
PERIOD = "5"
START_DATE = "20240903"
END_DATE = "20260713"
OUTPUT_PATH = Path("analysis/603703_5分钟_20240903_20260713_线段划分.csv")


def main() -> None:
    raw_klines = load_tdx2db_klines(SYMBOL, PERIOD, START_DATE, END_DATE)
    processed = process_inclusion(raw_klines)
    fractals = detect_fractals(processed)
    strokes = detect_strokes(fractals)
    confirmed_strokes = [stroke for stroke in strokes if stroke.status == "CONFIRMED"]
    segments = detect_segments(confirmed_strokes)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "线段编号",
                "方向",
                "起点日期",
                "起点价格",
                "终点日期",
                "终点价格",
                "区间最高",
                "区间最低",
                "包含笔数",
                "笔序号",
                "状态",
                "形成三笔",
                "形成ZD",
                "形成ZG",
                "反向确认三笔",
                "反向ZD",
                "反向ZG",
                "特征序列笔",
                "特征序列破坏条件",
                "原线段防线",
                "反向极值",
                "终结触发笔",
                "终结时间",
                "终结依据",
            ],
        )
        writer.writeheader()
        for segment in segments:
            evidence = segment.evidence
            writer.writerow(
                {
                    "线段编号": segment.id + 1,
                    "方向": "向上" if segment.direction == "up" else "向下",
                    "起点日期": segment.start_time,
                    "起点价格": f"{segment.start_price:.2f}",
                    "终点日期": segment.end_time,
                    "终点价格": f"{segment.end_price:.2f}",
                    "区间最高": f"{segment.high:.2f}",
                    "区间最低": f"{segment.low:.2f}",
                    "包含笔数": len(segment.stroke_ids),
                    "笔序号": ",".join(str(stroke_id + 1) for stroke_id in segment.stroke_ids),
                    "状态": "已确认" if segment.status == "CONFIRMED" else "运行中",
                    "形成三笔": _ids(evidence.formation_stroke_ids if evidence else []),
                    "形成ZD": _price(evidence.formation_zd if evidence else None),
                    "形成ZG": _price(evidence.formation_zg if evidence else None),
                    "反向确认三笔": _ids(evidence.candidate_stroke_ids if evidence else []),
                    "反向ZD": _price(evidence.candidate_zd if evidence else None),
                    "反向ZG": _price(evidence.candidate_zg if evidence else None),
                    "特征序列笔": _ids(evidence.characteristic_stroke_ids if evidence else []),
                    "特征序列破坏条件": evidence.characteristic_pattern if evidence else "",
                    "原线段防线": _price(evidence.guard_price if evidence else None),
                    "反向极值": _price(evidence.candidate_extreme if evidence else None),
                    "终结触发笔": (evidence.break_stroke_id + 1)
                    if evidence and evidence.break_stroke_id is not None
                    else "",
                    "终结时间": evidence.break_time if evidence else "",
                    "终结依据": _reason(evidence),
                }
            )

    print(
        f"source=tdx2db-local raw={len(raw_klines)} processed={len(processed)} "
        f"fractals={len(fractals)} confirmed_strokes={len(confirmed_strokes)} "
        f"segments={len(segments)} output={OUTPUT_PATH}"
    )


def _ids(ids: list[int]) -> str:
    return ",".join(str(item + 1) for item in ids)


def _price(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else ""


def _reason(evidence: object) -> str:
    if evidence is None:
        return ""
    reason = getattr(evidence, "break_reason", None)
    if reason:
        return reason
    return "尚未出现穿越原线段防线的反向三笔重叠结构，线段保持运行。"


if __name__ == "__main__":
    main()
