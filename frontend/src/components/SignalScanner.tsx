import type { SignalScanMatch } from "../types";

interface ScanProgress {
  scanned: number;
  total: number;
  percent: number;
  matched: number;
}

interface SignalScannerProps {
  startSignalDate: string;
  endSignalDate: string;
  period: string;
  side: "buy" | "sell";
  type: 1 | 2 | 3;
  loading: boolean;
  matches: SignalScanMatch[];
  message: string | null;
  progress: ScanProgress;
  selectedMatchKey: string;
  onChange: (next: { startSignalDate?: string; endSignalDate?: string; period?: string; side?: "buy" | "sell"; type?: 1 | 2 | 3 }) => void;
  onScan: () => void;
  onSelect: (match: SignalScanMatch) => void;
}

export function SignalScanner({
  startSignalDate,
  endSignalDate,
  period,
  side,
  type,
  loading,
  matches,
  message,
  progress,
  selectedMatchKey,
  onChange,
  onScan,
  onSelect,
}: SignalScannerProps) {
  return (
    <div className="signal-scanner">
      <strong>买卖点筛选</strong>
      <label>
        开始
        <input type="date" value={startSignalDate} onChange={(event) => onChange({ startSignalDate: event.target.value })} />
      </label>
      <label>
        结束
        <input type="date" value={endSignalDate} onChange={(event) => onChange({ endSignalDate: event.target.value })} />
      </label>
      <label>
        周期
        <select value={period} onChange={(event) => onChange({ period: event.target.value })}>
          <option value="daily">日线</option>
          <option value="weekly">周线</option>
          <option value="monthly">月线</option>
          <option value="1">1分钟</option>
          <option value="5">5分钟</option>
          <option value="15">15分钟</option>
          <option value="30">30分钟</option>
          <option value="60">60分钟</option>
        </select>
      </label>
      <label>
        信号
        <select
          value={`${side}-${type}`}
          onChange={(event) => {
            const [nextSide, nextType] = event.target.value.split("-");
            onChange({ side: nextSide as "buy" | "sell", type: Number(nextType) as 1 | 2 | 3 });
          }}
        >
          <option value="buy-1">买1</option>
          <option value="buy-2">买2</option>
          <option value="buy-3">买3</option>
          <option value="sell-1">卖1</option>
          <option value="sell-2">卖2</option>
          <option value="sell-3">卖3</option>
        </select>
      </label>
      <button type="button" onClick={onScan} disabled={loading}>
        {loading ? "筛选中" : "筛选"}
      </button>
      <label className="scan-results">
        命中股票
        <select
          value={selectedMatchKey}
          disabled={matches.length === 0}
          onChange={(event) => {
            const match = matches.find((item) => matchKey(item) === event.target.value);
            if (match) onSelect(match);
          }}
        >
          <option value="">{matches.length ? `共 ${matches.length} 条信号` : "暂无结果"}</option>
          {matches.map((match) => (
            <option key={matchKey(match)} value={matchKey(match)}>
              {match.time} {match.code} {match.name} {Math.round(match.confidence * 100)}%
            </option>
          ))}
        </select>
      </label>
      <div className="scan-progress-panel">
        <div className="scan-progress-text">
          <span>{message ?? "等待筛选"}</span>
          <span>{progress.scanned}/{progress.total || 0} · 命中 {progress.matched}</span>
        </div>
        <div className="scan-progress-track">
          <div className="scan-progress-fill" style={{ width: `${Math.max(0, Math.min(100, progress.percent))}%` }} />
        </div>
      </div>
    </div>
  );
}

function matchKey(match: SignalScanMatch) {
  return `${match.code}|${match.time}`;
}
