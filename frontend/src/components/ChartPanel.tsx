import { createChart, IChartApi, ISeriesApi, LineStyle, UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisResponse, Center, KLine, Segment, Signal, Stroke, TheoryMark } from "../types";

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
  const [hoveredKLine, setHoveredKLine] = useState<KLine | null>(null);

  const timeByIndex = useMemo(() => {
    const map = new Map<number, UTCTimestamp>();
    data?.klines.forEach((kline) => map.set(kline.index, toTimestamp(kline.time)));
    return map;
  }, [data]);

  useEffect(() => {
    dataRef.current = data;
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
      const kline = currentData.klines.find((item) => toTimestamp(item.time) === param.time);
      setHoveredKLine(kline ?? null);
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
      data.klines.map((kline) => ({
        time: toTimestamp(kline.time),
        open: kline.open,
        high: kline.high,
        low: kline.low,
        close: kline.close,
      }))
    );
    volumeRef.current.setData(
      data.klines.map((kline) => ({
        time: toTimestamp(kline.time),
        value: kline.volume,
        color: kline.close >= kline.open ? "rgba(239, 68, 68, 0.42)" : "rgba(34, 197, 94, 0.42)",
      }))
    );

    const markers = [];
    if (layers.fractals) {
      for (const fractal of data.fractals) {
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
        if (!segment) continue;
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
        const isCandidate = signal.status === "candidate";
        const isInvalidated = signal.status === "invalidated";
        markers.push({
          time: toTimestamp(signal.time),
          position: signal.side === "buy" ? "belowBar" : "aboveBar",
          color: signal.side === "buy" ? (isInvalidated ? "#64748b" : "#22c55e") : (isInvalidated ? "#64748b" : "#ef4444"),
          shape: signal.side === "buy" ? "arrowUp" : "arrowDown",
          text: `${signal.side === "buy" ? "B" : "S"}${signal.type}${isCandidate ? "?" : isInvalidated ? "x" : ""} ${Math.round(signal.confidence * 100)}%`,
        } as const);
      }
    }
    if (layers.segments) {
      for (const segment of data.segments) {
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

    fitFullRange();
  }, [data, layers, timeByIndex]);

  useEffect(() => {
    if (!data || !focusedSignal || !chartRef.current) return;
    const padding = 34;
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: Math.max(0, focusedSignal.index - padding),
      to: Math.min(data.klines.length - 1, focusedSignal.index + padding),
    });
    const kline = data.klines.find((item) => item.index === focusedSignal.index);
    setHoveredKLine(kline ?? null);
  }, [data, focusedSignal]);

  useEffect(() => {
    if (!data || !chartRef.current) return;
    window.requestAnimationFrame(() => fitFullRange());
  }, [chartHeight, data]);

  function drawLines(items: Array<Stroke | Segment>, color: string, lineWidth: 1 | 2 | 3, timeMap: Map<number, UTCTimestamp>) {
    for (const item of items) {
      const start = timeMap.get(item.start_index);
      const end = timeMap.get(item.end_index);
      if (!start || !end || !chartRef.current) continue;
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
      const color = signal.status === "invalidated" ? "#64748b" : signal.side === "buy" ? "#22c55e" : "#ef4444";
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

  function fitFullRange() {
    if (!chartRef.current || !data?.klines.length) return;
    chartRef.current.timeScale().fitContent();
    chartRef.current.timeScale().setVisibleLogicalRange({
      from: 0,
      to: data.klines.length - 1,
    });
  }

  return (
    <div className="chart-wrap" style={{ height: chartHeight }}>
      <div className="quote-strip">
        {hoveredKLine ? (
          <QuoteStrip kline={hoveredKLine} previous={data?.klines[hoveredKLine.index - 1]} />
        ) : (
          <span className="muted">鼠标移到K线上查看开高低收、涨跌幅、成交量和成交额</span>
        )}
        <button className="small-button" onClick={fitFullRange}>全貌</button>
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
