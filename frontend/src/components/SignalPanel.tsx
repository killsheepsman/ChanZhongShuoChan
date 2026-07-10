import type { AnalysisResponse, Signal } from "../types";

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
          <Metric label="理论" value={data.summary.theory_mark_count} />
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
