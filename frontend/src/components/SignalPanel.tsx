import { useEffect, useState } from "react";
import { fetchWatchDecision, type AnalyzeParams } from "../lib/api";
import type { AnalysisResponse, Signal, WatchDecision } from "../types";

interface SignalPanelProps {
  data: AnalysisResponse | null;
  selectedSignalId: string | null;
  onSignalClick: (signal: Signal) => void;
  assistantParams: AnalyzeParams;
}

export function SignalPanel({ data, selectedSignalId, onSignalClick, assistantParams }: SignalPanelProps) {
  const [decision, setDecision] = useState<WatchDecision | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  useEffect(() => {
    setDecision(null);
    setDecisionError(null);
  }, [data?.request.symbol, data?.request.end_date, data?.request.adjust]);

  async function runDecision() {
    setDecisionLoading(true);
    setDecisionError(null);
    try {
      setDecision(await fetchWatchDecision(assistantParams));
    } catch (error) {
      setDecisionError(error instanceof Error ? error.message : "走势研判失败");
    } finally {
      setDecisionLoading(false);
    }
  }

  if (!data) {
    return (
      <aside className="side-panel">
        <h2>买卖点</h2>
        <p className="muted">运行分析后，买卖点会显示在右侧并可点击定位图表。</p>
      </aside>
    );
  }

  const signals = [...data.signals].sort((left, right) => right.index - left.index || right.type - left.type);

  return (
    <aside className="side-panel">
      <details className="side-section" open>
        <summary><span>结构统计</span></summary>
        <div className="side-section-body">
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
        </div>
      </details>

      <details className="side-section watch-section" open>
        <summary><span>走势研判</span></summary>
        <div className="side-section-body">
          <button className="watch-run-button" type="button" disabled={decisionLoading} onClick={() => void runDecision()}>
            {decisionLoading ? "正在研判..." : decision ? "重新研判" : "运行研判"}
          </button>
          {decisionError && <p className="watch-error">{decisionError}</p>}
          {!decision && !decisionError && <p className="muted watch-empty">按日线与30分钟结构判断当前是否满足下单条件。</p>}
          {decision && <DecisionResult decision={decision} />}
        </div>
      </details>

      <details className="side-section signal-section" open>
        <summary><span>买卖点</span><small>{signals.length} 条</small></summary>
        <div className="side-section-body">
          <p className="stock-name">{data.request.symbol} {data.request.symbol_name}</p>
          <div className="signal-list">
            {data.signals.length === 0 ? (
              <p className="muted">当前区间没有识别到候选买卖点。</p>
            ) : signals.map((signal) => (
              <button className={`signal-item ${signal.side} ${signal.status} ${selectedSignalId === signal.id ? "selected" : ""}`} key={signal.id} onClick={() => onSignalClick(signal)}>
                <div><strong>{signal.side === "buy" ? "买" : "卖"}{signal.type}</strong><span>{signal.time}</span></div>
                <div className="signal-meta"><span>{statusText(signal.status)}</span><span>置信 {Math.round(signal.confidence * 100)}%</span></div>
                <p>{signal.reason}</p>
                <footer><span>{signal.price.toFixed(2)}</span><span>{signal.status === "confirmed" ? "确认" : signal.status === "invalidated" ? "候选失效" : signal.status === "expired" ? "已过期" : "候选"}</span></footer>
              </button>
            ))}
          </div>
        </div>
      </details>
    </aside>
  );
}

function DecisionResult({ decision }: { decision: WatchDecision }) {
  const tone = decision.order_allowed ? (decision.action === "BUY" ? "buy" : "sell") : "wait";
  return (
    <div className={`watch-result ${tone}`}>
      <div className="watch-verdict">
        <strong>{actionText(decision.action)}</strong>
        <span>{decision.priority}</span>
      </div>
      <p className="watch-conclusion">{decision.conclusion}</p>
      <dl className="watch-facts">
        <div><dt>当前结构</dt><dd>{decision.structure}</dd></div>
        <div><dt>建议仓位</dt><dd>{decision.position_percent}%</dd></div>
        <div><dt>最新信号</dt><dd>{decision.latest_signal?.label ?? "无确认信号"}</dd></div>
        <div><dt>止损 / 目标</dt><dd>{decision.stop_loss?.toFixed(2) ?? "--"} / {decision.targets.length ? decision.targets.map((item) => item.toFixed(2)).join("、") : "--"}</dd></div>
      </dl>
      <div className="watch-levels">
        <LevelLine label="日线" level={decision.levels.daily} />
        <LevelLine label="30F" level={decision.levels.minute30} />
      </div>
      <div className="watch-notes"><strong>触发条件</strong>{decision.trigger_conditions.map((item) => <p key={item}>{item}</p>)}</div>
      <div className="watch-notes risk"><strong>风险</strong>{decision.risks.map((item) => <p key={item}>{item}</p>)}</div>
      <time>{decision.generated_at}</time>
    </div>
  );
}

function LevelLine({ label, level }: { label: string; level: WatchDecision["levels"]["daily"] }) {
  return <p><strong>{label}</strong><span>{level.trend} · {level.macd_state}</span><small>{level.close?.toFixed(2) ?? "--"}</small></p>;
}

function actionText(action: WatchDecision["action"]) {
  if (action === "BUY") return "允许条件买入";
  if (action === "SELL") return "卖出 / 减仓";
  if (action === "HOLD") return "继续持有";
  if (action === "WAIT") return "等待确认";
  return "禁止下单";
}

function statusText(status: Signal["status"]) {
  if (status === "confirmed") return "已确认";
  if (status === "invalidated") return "候选失效";
  if (status === "expired") return "已过期";
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
