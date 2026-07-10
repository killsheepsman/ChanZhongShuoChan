import type { AnalysisResponse } from "../types";

type Props = {
  data: AnalysisResponse | null;
  error: string | null;
  loading: boolean;
};

const SOURCE_LABELS: Record<string, string> = {
  "akshare-eastmoney-hist": "AKShare / 东方财富历史行情",
  "akshare-eastmoney-minute": "AKShare / 东方财富分钟行情",
  "akshare-sina-daily": "AKShare / 新浪日线行情",
  "akshare-sina-minute": "AKShare / 新浪分钟行情",
  "akshare-tencent-daily": "AKShare / 腾讯日线行情",
  akshare: "AKShare",
  sample: "备用示例数据（非实时）",
};

function sourceLabel(source?: string) {
  if (!source) return "尚未请求";
  return SOURCE_LABELS[source] ?? source;
}

export function DataStatusFooter({ data, error, loading }: Props) {
  const status = data?.data_status;
  const state = error || status?.ok === false ? "warning" : status?.ok ? "ok" : "idle";
  const stateText = loading ? "正在连接外部数据" : error ? "连接或接口错误" : status?.ok ? "外部数据连接正常" : status ? "外部数据异常，已降级" : "等待分析";
  const detail = error ?? status?.message ?? "点击“分析”后显示本次数据请求结果。";

  return (
    <footer className={`data-status-footer ${state}`} aria-live="polite">
      <div className="data-status-summary">
        <strong>数据连接：{stateText}</strong>
        <span>来源：{sourceLabel(status?.source)}</span>
        {status && <span>K线：{status.kline_count} 根</span>}
        {status?.first_kline_time && <span>范围：{status.first_kline_time} 至 {status.last_kline_time ?? "-"}</span>}
        {status?.refreshed_at && <span>刷新：{status.refreshed_at}</span>}
      </div>
      <div className="data-status-detail">本次返回：{detail}</div>
      <div className="data-status-causes">
        常见原因：AKShare 依赖东方财富、新浪、腾讯等第三方接口，接口可能超时、限流、改版或返回空数据；本机网络、DNS、代理、防火墙或证书也可能阻断请求。分钟线比日线更容易不稳定；非交易日、停牌或所选日期无数据时，最新K线不会更新。若来源显示“备用示例数据（非实时）”，当前图表不能作为实时行情使用。
      </div>
    </footer>
  );
}
