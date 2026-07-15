import { createChart, IChartApi, ISeriesApi, LineStyle, UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisResponse, Center, KLine, Segment, Signal, Stroke, TheoryMark } from "../types";

// The complete two-year five-minute history is roughly 21,000 bars. Render it
// in full and only enter explicit paging above this guardrail.
const MAX_FULL_HISTORY_KLINES = 25_000;
const WINDOW_KLINES = 3_000;
const INITIAL_FOCUS_KLINES = 360;

interface ChartPanelProps {
  data: AnalysisResponse | null;
  focusedSignal: Signal | null;
  chartHeight: number;
  layers: {
    fractals: boolean;
    strokes: boolean;
    segments: boolean;
    centers: boolean;
    divergences: boolean;
    theory: boolean;
    signals: boolean;
  };
}

export function ChartPanel({ data, focusedSignal, chartHeight, layers }: ChartPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlayRefs = useRef<ISeriesApi<"Line">[]>([]);
  const dataRef = useRef<AnalysisResponse | null>(null);
  const marketKlineByTimeRef = useRef<Map<UTCTimestamp, KLine>>(new Map());
  const [hoveredKLine, setHoveredKLine] = useState<KLine | null>(null);
  const [windowStart, setWindowStart] = useState(0);

  // Render requested history in full whenever practical. Windowing is only for
  // unusually large feeds and is disclosed by the chart controls.
  const marketKlines = useMemo(() => data?.raw_klines?.length ? data.raw_klines : data?.klines ?? [], [data]);
  const isWindowed = marketKlines.length > MAX_FULL_HISTORY_KLINES;
  const maximumWindowStart = Math.max(0, marketKlines.length - WINDOW_KLINES);
  const displayStart = isWindowed ? Math.min(Math.max(0, windowStart), maximumWindowStart) : 0;
  const displayKlines = useMemo(
    () => isWindowed ? marketKlines.slice(displayStart, displayStart + WINDOW_KLINES) : marketKlines,
    [displayStart, isWindowed, marketKlines]
  );
  const displayIndexByTime = useMemo(
    () => new Map(displayKlines.map((kline, index) => [kline.time, index])),
    [displayKlines]
  );
  const marketIndexByTime = useMemo(
    () => new Map(marketKlines.map((kline, index) => [kline.time, index])),
    [marketKlines]
  );
  const visibleStartTime = displayKlines[0] ? toTimestamp(displayKlines[0].time) : null;
  const visibleEndTime = displayKlines.at(-1) ? toTimestamp(displayKlines.at(-1)!.time) : null;
  const timeByIndex = useMemo(() => {
    const map = new Map<number, UTCTimestamp>();
    data?.klines.forEach((kline) => map.set(kline.index, toTimestamp(kline.time)));
    return map;
  }, [data]);

  useEffect(() => {
    dataRef.current = data;
    const currentMarketKlines = data?.raw_klines?.length ? data.raw_klines : data?.klines ?? [];
    marketKlineByTimeRef.current = new Map(
      currentMarketKlines.map((kline) => [toTimestamp(kline.time), kline])
    );
    setWindowStart(
      currentMarketKlines.length > MAX_FULL_HISTORY_KLINES
        ? Math.max(0, currentMarketKlines.length - WINDOW_KLINES)
        : 0
    );
  }, [data]);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { color: "#0f172a" },
        textColor: "#cbd5e1",
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      rightPriceScale: {
        borderColor: "#334155",
        scaleMargins: {
          top: 0.08,
          bottom: 0.24,
        },
      },
      timeScale: {
        borderColor: "#334155",
        timeVisible: true,
      },
      crosshair: {
        mode: 1,
      },
    });
    const candles = chart.addCandlestickSeries({
      upColor: "#ef4444",
      downColor: "#22c55e",
      borderUpColor: "#ef4444",
      borderDownColor: "#22c55e",
      wickUpColor: "#f87171",
      wickDownColor: "#4ade80",
    });
    const volumes = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: {
        top: 0.82,
        bottom: 0,
      },
    });
    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volumes;
    chart.subscribeCrosshairMove((param) => {
      const currentData = dataRef.current;
      if (!currentData || !param.time) {
        setHoveredKLine(null);
        return;
      }
      setHoveredKLine(marketKlineByTimeRef.current.get(param.time as UTCTimestamp) ?? null);
    });

    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      overlayRefs.current = [];
    };
  }, []);

  useEffect(() => {
    if (!data || !chartRef.current || !candleRef.current || !volumeRef.current) return;
    overlayRefs.current.forEach((series) => chartRef.current?.removeSeries(series));
    overlayRefs.current = [];

    candleRef.current.setData(
      displayKlines.map((kline) => ({
        time: toTimestamp(kline.time),
        open: kline.open,
        high: kline.high,
        low: kline.low,
        close: kline.close,
      }))
    );
    volumeRef.current.setData(
      displayKlines.map((kline) => ({
        time: toTimestamp(kline.time),
        value: kline.volume,
        color: kline.close >= kline.open ? "rgba(239, 68, 68, 0.42)" : "rgba(34, 197, 94, 0.42)",
      }))
    );

    const markers = [];
    const isVisibleTime = (time: string) => {
      const timestamp = toTimestamp(time);
      return visibleStartTime !== null && visibleEndTime !== null && timestamp >= visibleStartTime && timestamp <= visibleEndTime;
    };
    if (layers.fractals) {
      for (const fractal of data.fractals) {
        if (!isVisibleTime(fractal.time)) continue;
        markers.push({
          time: toTimestamp(fractal.time),
          position: fractal.kind === "top" ? "aboveBar" : "belowBar",
          color: fractal.kind === "top" ? "#f59e0b" : "#38bdf8",
          shape: fractal.kind === "top" ? "arrowDown" : "arrowUp",
          text: fractal.kind === "top" ? "顶" : "底",
        } as const);
      }
    }
    if (layers.divergences) {
      const segmentById = new Map(data.segments.map((segment) => [segment.id, segment]));
      for (const divergence of data.divergences) {
        const segment = segmentById.get(divergence.segment_id);
        if (!segment || !isVisibleTime(segment.end_time)) continue;
        markers.push({
          time: toTimestamp(segment.end_time),
          position: divergence.side === "buy" ? "belowBar" : "aboveBar",
          color: divergence.kind === "trend" ? "#e879f9" : "#c084fc",
          shape: "circle",
          text: divergence.kind === "trend" ? "背" : "盘背",
        } as const);
      }
    }
    if (layers.theory) {
      for (const mark of data.theory_marks ?? []) {
        if (!isVisibleTime(mark.time)) continue;
        markers.push({
          time: toTimestamp(mark.time),
          position: markerPosition(mark),
          color: theoryMarkColor(mark),
          shape: theoryMarkShape(mark),
          text: mark.label,
        } as const);
      }
    }
    if (layers.signals) {
      for (const signal of data.signals) {
        if (!isVisibleTime(signal.time)) continue;
        const isCandidate = signal.status === "candidate";
        const isInvalidated = signal.status === "invalidated" || signal.status === "expired";
        markers.push({
          time: toTimestamp(signal.time),
          position: signal.side === "buy" ? "belowBar" : "aboveBar",
          color: signal.side === "buy" ? (isInvalidated ? "#64748b" : "#22c55e") : (isInvalidated ? "#64748b" : "#ef4444"),
          shape: signal.side === "buy" ? "arrowUp" : "arrowDown",
          text: `${signal.side === "buy" ? "B" : "S"}${signal.type}${isCandidate ? "?" : signal.status === "expired" ? "旧" : isInvalidated ? "x" : ""} ${Math.round(signal.confidence * 100)}%`,
        } as const);
      }
    }
    if (layers.segments) {
      for (const segment of data.segments) {
        if (!isVisibleTime(segment.end_time)) continue;
        const isRunning = segment.status === "IS_RUNNING";
        markers.push({
          time: toTimestamp(segment.end_time),
          position: segment.direction === "up" ? "aboveBar" : "belowBar",
          color: isRunning ? "#38bdf8" : "#f59e0b",
          shape: "circle",
          text: `线${segment.id + 1} ${isRunning ? "运行" : "确认"}`,
        } as const);
      }
    }
    markers.sort((left, right) => Number(left.time) - Number(right.time));
    candleRef.current.setMarkers(markers);

    if (layers.strokes) drawLines(data.strokes, "#22d3ee", 1, timeByIndex);
    if (layers.segments) drawLines(data.segments, "#f59e0b", 3, timeByIndex);
    if (layers.centers) drawCenters(data.centers, timeByIndex);
    if (layers.signals) drawSignalLevels(data.signals, timeByIndex);

    showFullHistory();
  }, [data, displayKlines, layers, timeByIndex]);

  useEffect(() => {
    if (!data || !focusedSignal || !chartRef.current) return;
    const marketIndex = marketIndexByTime.get(focusedSignal.time);
    if (marketIndex === undefined) return;
    const displayEnd = displayStart + displayKlines.length;
    if (marketIndex < displayStart || marketIndex >= displayEnd) {
      setWindowStart(Math.min(maximumWindowStart, Math.max(0, marketIndex - Math.floor(WINDOW_KLINES / 2))));
      return;
    }
    const padding = 34;
    const focusedIndex = marketIndex - displayStart;
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: Math.max(0, focusedIndex - padding),
      to: Math.min(displayKlines.length - 1, focusedIndex + padding),
    });
    setHoveredKLine(displayKlines[focusedIndex] ?? null);
  }, [data, displayKlines, displayStart, focusedSignal, marketIndexByTime, maximumWindowStart]);

  function drawLines(items: Array<Stroke | Segment>, color: string, lineWidth: 1 | 2 | 3, timeMap: Map<number, UTCTimestamp>) {
    for (const item of items) {
      const start = timeMap.get(item.start_index);
      const end = timeMap.get(item.end_index);
      if (!start || !end || !chartRef.current) continue;
      if (visibleStartTime === null || visibleEndTime === null || start < visibleStartTime || end > visibleEndTime) continue;
      const isRunningSegment = "status" in item && item.status === "IS_RUNNING";
      const series = chartRef.current.addLineSeries({
        color,
        lineWidth: isRunningSegment ? 2 : lineWidth,
        lineStyle: isRunningSegment ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData([
        { time: start, value: item.start_price },
        { time: end, value: item.end_price },
      ]);
      overlayRefs.current.push(series);
    }
  }

  function drawCenters(centers: Center[], timeMap: Map<number, UTCTimestamp>) {
    for (const center of centers) {
      const start = timeMap.get(center.start_index);
      const end = timeMap.get(center.end_index);
      if (!start || !end || !chartRef.current) continue;
      if (visibleStartTime === null || visibleEndTime === null || start < visibleStartTime || end > visibleEndTime) continue;
      const label = center.id + 1;
      for (const [value, side] of [
        [center.zg, "ZG"],
        [center.zd, "ZD"],
      ] as const) {
        const series = chartRef.current.addLineSeries({
          color: "#14b8a6",
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        series.setData([
          { time: start, value },
          { time: end, value },
        ]);
        series.setMarkers([
          {
            time: end,
            position: side === "ZG" ? "aboveBar" : "belowBar",
            color: "#14b8a6",
            shape: "circle",
            text: `中枢${label} ${side} ${value.toFixed(2)}`,
          },
        ]);
        overlayRefs.current.push(series);
      }
    }
  }

  function drawSignalLevels(signals: Signal[], timeMap: Map<number, UTCTimestamp>) {
    if (!chartRef.current) return;
    for (const signal of signals) {
      const start = timeMap.get(signal.index);
      const end = timeMap.get(signal.index + 5) ?? timeMap.get(signal.index + 3) ?? timeMap.get(signal.index + 1);
      if (!start || !end) continue;
      if (visibleStartTime === null || visibleEndTime === null || start < visibleStartTime || start > visibleEndTime || end > visibleEndTime) continue;
      const color = signal.status === "invalidated" || signal.status === "expired" ? "#64748b" : signal.side === "buy" ? "#22c55e" : "#ef4444";
      const series = chartRef.current.addLineSeries({
        color,
        lineWidth: signal.status === "confirmed" ? 2 : 1,
        lineStyle: signal.status === "confirmed" ? LineStyle.Solid : LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData([
        { time: start, value: signal.price },
        { time: end, value: signal.price },
      ]);
      overlayRefs.current.push(series);
    }
  }

  function markerPosition(mark: TheoryMark) {
    if (mark.side === "buy") return "belowBar" as const;
    if (mark.side === "sell") return "aboveBar" as const;
    if (mark.kind === "center_formed" || mark.kind === "center_extend") return "inBar" as const;
    return "aboveBar" as const;
  }

  function theoryMarkColor(mark: TheoryMark) {
    const colors: Record<TheoryMark["kind"], string> = {
      segment_break: "#f97316",
      center_formed: "#14b8a6",
      center_extend: "#2dd4bf",
      center_leave: mark.side === "buy" ? "#22c55e" : "#ef4444",
      center_retest: mark.side === "buy" ? "#16a34a" : "#dc2626",
      trend_state: mark.side === "buy" ? "#38bdf8" : mark.side === "sell" ? "#fb7185" : "#94a3b8",
      macd_zero: mark.side === "buy" ? "#a3e635" : "#f472b6",
    };
    return colors[mark.kind];
  }

  function theoryMarkShape(mark: TheoryMark) {
    if (mark.kind === "center_formed" || mark.kind === "center_extend" || mark.kind === "trend_state") return "circle" as const;
    return mark.side === "buy" ? "arrowUp" as const : "arrowDown" as const;
  }

  function focusRecentBars() {
    if (!chartRef.current || !displayKlines.length) return;
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: Math.max(0, displayKlines.length - INITIAL_FOCUS_KLINES),
      to: displayKlines.length - 1,
    });
  }

  function showFullHistory() {
    if (!chartRef.current || !displayKlines.length) return;
    chartRef.current.timeScale().fitContent();
  }

  function showPreviousWindow() {
    setWindowStart((current) => Math.max(0, current - WINDOW_KLINES));
  }

  function showNextWindow() {
    setWindowStart((current) => Math.min(maximumWindowStart, current + WINDOW_KLINES));
  }

  const hoveredMarketIndex = hoveredKLine ? displayIndexByTime.get(hoveredKLine.time) ?? -1 : -1;

  return (
    <div className="chart-wrap" style={{ height: chartHeight }}>
      <div className="quote-strip">
        {hoveredKLine ? (
          <QuoteStrip kline={hoveredKLine} previous={hoveredMarketIndex > 0 ? displayKlines[hoveredMarketIndex - 1] : undefined} />
        ) : (
          <span className="muted">鼠标移到K线上查看开高低收、涨跌幅、成交量和成交额</span>
        )}
        {isWindowed && (
          <>
            <span className="muted">图表 {displayStart + 1}-{displayStart + displayKlines.length} / {marketKlines.length} 根</span>
            <button className="small-button" type="button" onClick={showPreviousWindow} disabled={displayStart === 0}>前一段</button>
            <button className="small-button" type="button" onClick={showNextWindow} disabled={displayStart >= maximumWindowStart}>后一段</button>
          </>
        )}
        <button className="small-button" type="button" onClick={focusRecentBars}>最新</button>
        {!isWindowed && marketKlines.length > 0 && (
          <span className="muted">{`\u56fe\u8868 1-${displayKlines.length} / ${marketKlines.length} \u6839`}</span>
        )}
        <button className="small-button" type="button" onClick={showFullHistory}>{"\u5168\u5386\u53f2"}</button>

      </div>
      <div className="chart-surface" ref={containerRef} />
    </div>
  );
}

function QuoteStrip({ kline, previous }: { kline: KLine; previous?: KLine }) {
  const diff = previous ? kline.close - previous.close : 0;
  const pct = previous?.close ? (diff / previous.close) * 100 : 0;
  const tone = diff >= 0 ? "quote-up" : "quote-down";
  return (
    <div className="quote-values">
      <strong>{kline.time}</strong>
      <span>开 {kline.open.toFixed(2)}</span>
      <span>高 {kline.high.toFixed(2)}</span>
      <span>低 {kline.low.toFixed(2)}</span>
      <span>收 {kline.close.toFixed(2)}</span>
      <span className={tone}>涨跌 {diff.toFixed(2)}</span>
      <span className={tone}>涨幅 {pct.toFixed(2)}%</span>
      <span>量 {formatVolume(kline.volume)}</span>
      {kline.amount ? <span>额 {formatAmount(kline.amount)}</span> : null}
    </div>
  );
}

function formatVolume(value: number) {
  if (value >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
  if (value >= 10000) return `${(value / 10000).toFixed(2)}万`;
  return value.toFixed(0);
}

function formatAmount(value: number) {
  if (value >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
  if (value >= 10000) return `${(value / 10000).toFixed(2)}万`;
  return value.toFixed(0);
}

function toTimestamp(value: string): UTCTimestamp {
  const normalized = value.includes(" ") ? value.replace(" ", "T") : `${value}T00:00:00`;
  return Math.floor(new Date(normalized).getTime() / 1000) as UTCTimestamp;
}
