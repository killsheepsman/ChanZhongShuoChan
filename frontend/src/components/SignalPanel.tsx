import type { AnalysisResponse, Segment, Signal } from "../types";

interface SignalPanelProps {
  data: AnalysisResponse | null;
  selectedSignalId: string | null;
  onSignalClick: (signal: Signal) => void;
}

export function SignalPanel({ data, selectedSignalId, onSignalClick }: SignalPanelProps) {
  if (!data) {
    return (
      <aside className="side-panel">
        <h2>结构状态</h2>
        <p className="muted">运行分析后，这里会显示分型、笔、线段、中枢和买卖点。</p>
      </aside>
    );
  }

  const signals = [...data.signals].sort((left, right) => right.index - left.index || right.type - left.type);
  const segments = [...data.segments].sort((left, right) => right.id - left.id);

  return (
    <aside className="side-panel">
      <section>
        <h2>结构状态</h2>
        <p className="stock-name">
          {data.request.symbol} {data.request.symbol_name}
        </p>
        <div className="summary-grid">
          <Metric label="K线" value={data.summary.kline_count} />
          <Metric label="分型" value={data.summary.fractal_count} />
          <Metric label="笔" value={data.summary.stroke_count} />
          <Metric label="线段" value={data.summary.segment_count} />
          <Metric label="中枢" value={data.summary.center_count} />
          <Metric label="背驰" value={data.summary.divergence_count} />
          <Metric label="信号" value={data.summary.signal_count} />
          <Metric label="理论标记" value={data.summary.theory_mark_count} />
        </div>
      </section>
      <section className="data-range-section">
        <h2>数据与引擎</h2>
        <div className="data-range-list">
          <span>请求区间：{data.request.start_date} - {data.request.end_date}</span>
          <span>图表/分析区间：{data.data_status?.first_kline_time ?? "-"} - {data.data_status?.last_kline_time ?? "-"}</span>
          <span>数据源覆盖：{data.data_status?.source_first_kline_time ?? data.data_status?.first_kline_time ?? "-"} - {data.data_status?.source_last_kline_time ?? data.data_status?.last_kline_time ?? "-"}</span>
          <span>原始K线：{data.data_status?.kline_count ?? data.raw_klines.length} 根；处理后：{data.klines.length} 根</span>
          <span>结构引擎：{data.engine?.segment_engine ?? "-"}</span>
          <span className="muted">{data.data_status?.message ?? data.engine?.rule_profile}</span>
          <span className="muted">{data.engine?.rule_profile}</span>
        </div>
      </section>
      <section className="segment-evidence-section">
        <h2>线段证据</h2>
        <div className="segment-evidence-list">
          {segments.length === 0 ? (
            <p className="muted">尚未出现满足连续三笔共同重叠条件的线段。</p>
          ) : (
            segments.map((segment) => <SegmentEvidenceCard key={segment.id} segment={segment} />)
          )}
        </div>
      </section>
      <section>
        <h2>买卖点</h2>
        <div className="signal-list">
          {data.signals.length === 0 ? (
            <p className="muted">当前区间没有识别到候选买卖点。</p>
          ) : (
            signals.map((signal) => (
              <button
                className={`signal-item ${signal.side} ${signal.status} ${selectedSignalId === signal.id ? "selected" : ""}`}
                key={signal.id}
                onClick={() => onSignalClick(signal)}
              >
                <div>
                  <strong>
                    {signal.side === "buy" ? "买" : "卖"}
                    {signal.type}
                  </strong>
                  <span>{signal.time}</span>
                </div>
                <div className="signal-meta">
                  <span>{statusText(signal.status)}</span>
                  <span>置信 {Math.round(signal.confidence * 100)}%</span>
                </div>
                <p>{signal.reason}</p>
                <footer>
                  <span>{signal.price.toFixed(2)}</span>
                  <span>{signal.status === "confirmed" ? "确认" : signal.status === "invalidated" ? "候选失效" : "候选"}</span>
                </footer>
              </button>
            ))
          )}
        </div>
      </section>
    </aside>
  );
}

function SegmentEvidenceCard({ segment }: { segment: Segment }) {
  const evidence = segment.evidence;
  const state = segment.status === "CONFIRMED" ? "已确认" : "运行中";
  return (
    <article className={`segment-evidence-card ${segment.status === "CONFIRMED" ? "confirmed" : "running"}`}>
      <header>
        <strong>线段{segment.id + 1} {segment.direction === "up" ? "向上" : "向下"}</strong>
        <span>{state}</span>
      </header>
      <p>{segment.start_time} 至 {segment.end_time}</p>
      <p>起止：{segment.start_price.toFixed(2)} → {segment.end_price.toFixed(2)}；区间：{segment.low.toFixed(2)} - {segment.high.toFixed(2)}</p>
      {evidence ? (
        <>
          <p>形成：{formatStrokeIds(evidence.formation_stroke_ids)}；共同重叠 [{formatPrice(evidence.formation_zd)}, {formatPrice(evidence.formation_zg)}]</p>
          {evidence.candidate_stroke_ids.length > 0 ? (
            <p>反向候选：{formatStrokeIds(evidence.candidate_stroke_ids)}；重叠 [{formatPrice(evidence.candidate_zd)}, {formatPrice(evidence.candidate_zg)}]</p>
          ) : null}
          <p>守卫：{evidence.guard_side === "low" ? "低点" : evidence.guard_side === "high" ? "高点" : "-"} {formatPrice(evidence.guard_price)}；候选极值 {formatPrice(evidence.candidate_extreme)}</p>
          {evidence.break_stroke_id !== null ? (
            <p className="break-evidence">确认：笔{evidence.break_stroke_id + 1}，{evidence.break_time}。{evidence.break_reason}</p>
          ) : (
            <p className="muted">尚无完整反向线段突破守卫，当前线段继续运行。</p>
          )}
        </>
      ) : (
        <p className="muted">旧版数据未提供结构证据。</p>
      )}
    </article>
  );
}

function formatStrokeIds(ids: number[]) {
  return ids.length ? ids.map((id) => `笔${id + 1}`).join("、") : "-";
}

function formatPrice(value: number | null) {
  return value === null || !Number.isFinite(value) ? "-" : value.toFixed(2);
}

function statusText(status: Signal["status"]) {
  if (status === "confirmed") return "已确认";
  if (status === "invalidated") return "候选失效";
  return "当下候选";
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </div>
  );
}
