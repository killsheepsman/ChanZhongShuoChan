import type { AnalysisResponse, SignalScanResponse, StockOption } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export interface AnalyzeParams {
  symbol: string;
  period: string;
  startDate: string;
  endDate: string;
  adjust: string;
}

export async function fetchAnalysis(params: AnalyzeParams): Promise<AnalysisResponse> {
  const query = new URLSearchParams({
    symbol: params.symbol,
    period: params.period,
    start_date: params.startDate,
    end_date: params.endDate,
    adjust: params.adjust,
    _: String(Date.now()),
  });
  const response = await fetch(`${API_BASE}/api/analyze?${query.toString()}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`分析接口返回 ${response.status}`);
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
  signalDate: string;
  period: string;
  side: "buy" | "sell";
  type: 1 | 2 | 3;
  adjust: string;
}

export async function fetchSignalScan(params: SignalScanParams): Promise<SignalScanResponse> {
  const query = new URLSearchParams({
    signal_date: params.signalDate,
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
    signal_date: params.signalDate,
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
