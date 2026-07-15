import { useEffect, useState } from "react";
import type { Tdx2DbStatus } from "../types";

interface Tdx2DbPanelProps {
  status: Tdx2DbStatus | null;
  loading: boolean;
  error: string | null;
  onConfigure: (path: string) => void;
  onStart: () => void;
  onBackfill: () => void;
  onStop: () => void;
}

const PERIOD_LABELS: Record<string, string> = {
  daily: "日线",
  "5": "5分钟",
  "15": "15分钟",
  "30": "30分钟",
  "60": "60分钟",
};

export function Tdx2DbPanel({ status, loading, error, onConfigure, onStart, onBackfill, onStop }: Tdx2DbPanelProps) {
  const [tdxPath, setTdxPath] = useState("");
  const sync = status?.sync;
  const syncStatus = sync?.status ?? "idle";
  const syncActive = Boolean(sync?.running || syncStatus === "running" || syncStatus === "stopping");
  const canStart = Boolean(status?.installed && status?.path_valid && !syncActive);
  const syncStatusLabel: Record<string, string> = {
    idle: "等待启动",
    running: "同步中",
    stopping: "正在停止",
    completed: "已完成",
    stopped: "已停止",
    failed: "同步失败",
  };

  useEffect(() => {
    setTdxPath(status?.configured_path || status?.detected_path || "");
  }, [status?.configured_path, status?.detected_path]);

  return (
    <section className="tdx2db-panel" aria-label="通达信本地库">
      <strong>通达信本地库</strong>
      <label className="tdx2db-path-input">
        数据目录
        <input
          value={tdxPath}
          placeholder="选择含 vipdoc 的通达信目录"
          onChange={(event) => setTdxPath(event.target.value)}
          title={tdxPath}
        />
      </label>
      <button className="small-button" type="button" disabled={loading || !tdxPath.trim()} onClick={() => onConfigure(tdxPath.trim())}>
        保存目录
      </button>
      <button type="button" disabled={loading || !canStart} onClick={onStart}>
        增量同步
      </button>
      <button className="small-button" type="button" disabled={loading || !canStart} onClick={onBackfill} title="把通达信本地 lc5 文件中早于数据库的历史5分钟线补入项目数据库。">
        补全5分历史
      </button>
      <button className="small-button" type="button" disabled={loading || !syncActive || syncStatus === "stopping"} onClick={onStop}>
        停止
      </button>
      <div className="tdx2db-summary">
        <span className={status?.installed ? "tdx2db-ready" : "tdx2db-warning"}>
          {status?.installed ? "tdx2db 已安装" : "缺少 tdx2db，先点击一键安装依赖"}
        </span>
        <span className={status?.path_valid ? "tdx2db-ready" : "tdx2db-warning"}>
          {status?.path_valid ? "通达信目录有效" : "未配置有效通达信目录"}
        </span>
        <span className={`tdx2db-sync-state tdx2db-sync-${syncStatus}`}>同步状态：{syncStatusLabel[syncStatus] ?? syncStatus}</span>
        <span>详情：{sync?.message ?? "等待手动启动"}</span>
        {status?.database_path && <span className="tdx2db-path" title={status.database_path}>数据库：{status.database_path}</span>}
      </div>
      {status?.tables?.length ? (
        <div className="tdx2db-tables" aria-label="本地行情表统计">
          {status.tables.map((table) => (
            <span key={table.table} title={`${table.first_time ?? "-"} 至 ${table.last_time ?? "-"}`}>
              {PERIOD_LABELS[table.period] ?? table.period}：{table.stock_count} 股 / {table.bar_count} 根
            </span>
          ))}
        </div>
      ) : (
        <span className="tdx2db-empty">尚未生成本地行情库；同步只在点击“增量同步”后开始。</span>
      )}
      {error && <div className="tdx2db-error" role="alert">{error}</div>}
    </section>
  );
}
