import type { AnalysisResponse, SignalScanResponse, StockOption, Tdx2DbStatus, WatchDecision } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export interface AnalyzeParams {
  symbol: string;
  period: string;
  startDate: string;
  endDate: string;
  adjust: string;
  allowExternal: boolean;
}

export async function fetchAnalysis(params: AnalyzeParams): Promise<AnalysisResponse> {
  const query = new URLSearchParams({
    symbol: params.symbol,
    period: params.period,
    start_date: params.startDate,
    end_date: params.endDate,
    adjust: params.adjust,
    allow_external: String(params.allowExternal),
    _: String(Date.now()),
  });
  const response = await fetch(`${API_BASE}/api/analyze?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`分析接口返回 ${response.status}`);
  }
  return response.json();
}

export async function fetchWatchDecision(params: AnalyzeParams): Promise<WatchDecision> {
  const query = new URLSearchParams({
    symbol: params.symbol,
    start_date: params.startDate,
    end_date: params.endDate,
    adjust: params.adjust,
    allow_external: String(params.allowExternal),
    _: String(Date.now()),
  });
  const response = await fetch(`${API_BASE}/api/watch-assistant?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await apiErrorMessage(response, `走势研判接口返回 ${response.status}`));
  }
  return response.json();
}

export async function fetchStocks(): Promise<StockOption[]> {
  const response = await fetch(`${API_BASE}/api/stocks?_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`股票列表接口返回 ${response.status}`);
  }
  const payload = await response.json();
  return Array.isArray(payload.stocks) ? payload.stocks : [];
}

export interface SignalScanParams {
  startSignalDate: string;
  endSignalDate: string;
  period: string;
  side: "buy" | "sell";
  type: 1 | 2 | 3;
  adjust: string;
}

export async function fetchSignalScan(params: SignalScanParams): Promise<SignalScanResponse> {
  const query = new URLSearchParams({
    start_signal_date: params.startSignalDate,
    end_signal_date: params.endSignalDate,
    period: params.period,
    side: params.side,
    signal_type: String(params.type),
    adjust: params.adjust,
    _: String(Date.now()),
  });
  const response = await fetch(`${API_BASE}/api/signal-scan?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`买卖点筛选接口返回 ${response.status}`);
  }
  return response.json();
}

export async function startSignalScan(params: SignalScanParams): Promise<SignalScanResponse> {
  const query = new URLSearchParams({
    start_signal_date: params.startSignalDate,
    end_signal_date: params.endSignalDate,
    period: params.period,
    side: params.side,
    signal_type: String(params.type),
    adjust: params.adjust,
    _: String(Date.now()),
  });
  const response = await fetch(`${API_BASE}/api/signal-scan/start?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`买卖点筛选任务启动失败 ${response.status}`);
  }
  return response.json();
}

export async function fetchSignalScanStatus(jobId: string): Promise<SignalScanResponse> {
  const response = await fetch(`${API_BASE}/api/signal-scan/status/${jobId}?_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`买卖点筛选进度接口返回 ${response.status}`);
  }
  return response.json();
}

export async function fetchTdx2DbStatus(): Promise<Tdx2DbStatus> {
  const response = await fetch(`${API_BASE}/api/tdx2db?_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await apiErrorMessage(response, "Failed to read TongDaXin local database status"));
  return response.json();
}

export async function startTdx2DbHistoryBackfill(): Promise<Tdx2DbStatus> {
  const response = await fetch(`${API_BASE}/api/tdx2db/backfill/start?_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await apiErrorMessage(response, "导入通达信5分钟历史失败"));
  }
  return response.json();
}

export async function configureTdx2Db(tdxPath: string): Promise<Tdx2DbStatus> {
  const query = new URLSearchParams({ tdx_path: tdxPath, _: String(Date.now()) });
  const response = await fetch(`${API_BASE}/api/tdx2db/configure?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await apiErrorMessage(response, "Failed to save TongDaXin directory"));
  return response.json();
}

export async function startTdx2DbSync(): Promise<Tdx2DbStatus> {
  const response = await fetch(`${API_BASE}/api/tdx2db/sync/start?_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await apiErrorMessage(response, "Failed to start TongDaXin sync"));
  return response.json();
}

export async function stopTdx2DbSync(): Promise<Tdx2DbStatus> {
  const response = await fetch(`${API_BASE}/api/tdx2db/sync/stop?_=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await apiErrorMessage(response, "Failed to stop TongDaXin sync"));
  return response.json();
}

async function apiErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string" && payload.detail) return payload.detail;
  } catch {
    // Fall through to a stable HTTP error.
  }
  return `${fallback}: ${response.status}`;
}
