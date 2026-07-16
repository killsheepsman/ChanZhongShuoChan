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
  onOptimize: () => void;
}

const PERIOD_LABELS: Record<string, string> = {
  daily: "日线",
  "5": "5分钟",
  "15": "15分钟",
  "30": "30分钟",
  "60": "60分钟",
};

export function Tdx2DbPanel({ status, loading, error, onConfigure, onStart, onBackfill, onStop, onOptimize }: Tdx2DbPanelProps) {
  const [tdxPath, setTdxPath] = useState("");
  const sync = status?.sync;
  const syncStatus = sync?.status ?? "idle";
  const syncActive = Boolean(sync?.running || syncStatus === "running" || syncStatus === "stopping");
  // The project-owned importer reads vipdoc directly; the optional tdx2db CLI
  // is no longer required to start daily/5-minute synchronization.
  const canStart = Boolean(status?.path_valid && !syncActive);
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
      <button className="small-button" type="button" disabled={loading || syncActive} onClick={onOptimize} title="删除15/30/60分钟冗余表并压缩SQLite数据库，必须先停止同步。">
        清理冗余并压缩
      </button>
      <div className="tdx2db-summary">
        <span className="tdx2db-ready">项目本地导入器已就绪</span>
        <span className={status?.path_valid ? "tdx2db-ready" : "tdx2db-warning"}>
          {status?.path_valid ? "通达信目录有效" : "未配置有效通达信目录"}
        </span>
        <span className={`tdx2db-sync-state tdx2db-sync-${syncStatus}`}>同步状态：{syncStatusLabel[syncStatus] ?? syncStatus}</span>
        {sync && sync.total_stocks > 0 ? (
          <span>日线：{sync.processed_stocks}/{sync.total_stocks}只，累计{sync.daily_bars_imported.toLocaleString()}根，当前{sync.current_code ?? "-"}；5分钟K线：{sync.processed_stocks}/{sync.total_stocks}只，累计{sync.minute5_bars_imported.toLocaleString()}根，当前{sync.current_code ?? "-"}</span>
        ) : (
          <span>详情：{sync?.message ?? "等待手动启动"}</span>
        )}
        {status?.database_path && <span className="tdx2db-path" title={status.database_path}>数据库：{status.database_path}</span>}
      </div>
      <span className="tdx2db-empty">日线和5分钟均按数据库最新时间增量同步，已有K线不会重复写入。</span>
      {error && <div className="tdx2db-error" role="alert">{error}</div>}
    </section>
  );
}
