export interface KLine {
  index: number;
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

export interface StockOption {
  code: string;
  name: string;
}

export interface SignalScanMatch extends StockOption {
  time: string;
  price: number;
  status: "candidate" | "confirmed" | "invalidated";
  confidence: number;
  source: string;
  last_kline_time: string | null;
}

export interface SignalScanResponse {
  job_id?: string;
  status?: "running" | "done" | "failed";
  criteria: {
    signal_date: string;
    period: string;
    side: "buy" | "sell";
    type: 1 | 2 | 3;
    adjust: string;
  };
  scan_range: {
    start_date: string;
    end_date: string;
  };
  scanned_count: number;
  failed_count: number;
  total_count: number;
  matched_count: number;
  matches: SignalScanMatch[];
  message?: string;
  progress?: number;
  started_at?: string;
  refreshed_at: string;
}

export interface Fractal {
  index: number;
  time: string;
  kind: "top" | "bottom";
  price: number;
}

export interface Stroke {
  start_index: number;
  end_index: number;
  start_time: string;
  end_time: string;
  start_price: number;
  end_price: number;
  direction: "up" | "down";
  high: number;
  low: number;
}

export interface Segment extends Stroke {
  id: number;
  status: "IS_RUNNING" | "CONFIRMED";
}

export interface Center {
  id: number;
  start_index: number;
  end_index: number;
  start_time: string;
  end_time: string;
  zg: number;
  zd: number;
  gg: number;
  dd: number;
}

export interface Signal {
  id: string;
  side: "buy" | "sell";
  type: 1 | 2 | 3;
  index: number;
  time: string;
  price: number;
  status: "candidate" | "confirmed" | "invalidated";
  confidence: number;
  reason: string;
  center_id: number | null;
  segment_id: number | null;
}

export interface Divergence {
  segment_id: number;
  side: "buy" | "sell";
  kind: "trend" | "consolidation";
  strength: number;
  reason: string;
}

export interface TheoryMark {
  id: string;
  kind:
    | "segment_break"
    | "center_formed"
    | "center_extend"
    | "center_leave"
    | "center_retest"
    | "trend_state"
    | "macd_zero";
  index: number;
  time: string;
  price: number;
  label: string;
  reason: string;
  side: "buy" | "sell" | null;
  center_id: number | null;
  segment_id: number | null;
}

export interface AnalysisResponse {
  request: {
    symbol: string;
    symbol_name: string;
    period: string;
    start_date: string;
    end_date: string;
    adjust: string;
  };
  data_status?: {
    ok: boolean;
    source: "akshare" | "sample" | string;
    message: string;
    refreshed_at: string;
    first_kline_time: string | null;
    last_kline_time: string | null;
    kline_count: number;
  };
  klines: KLine[];
  fractals: Fractal[];
  strokes: Stroke[];
  segments: Segment[];
  centers: Center[];
  divergences: Divergence[];
  signals: Signal[];
  theory_marks: TheoryMark[];
  trend?: {
    type: "unclassified" | "consolidation" | "trend";
    direction: "up" | "down" | null;
    center_count: number;
    reason: string;
  };
  summary: Record<string, number>;
}
