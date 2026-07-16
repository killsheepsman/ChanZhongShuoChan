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
  status: "candidate" | "confirmed" | "invalidated" | "expired";
  confidence: number;
  source: string;
  last_kline_time: string | null;
}

export interface SignalScanResponse {
  job_id?: string;
  status?: "running" | "done" | "failed";
  criteria: {
    start_signal_date: string;
    end_signal_date: string;
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

export interface SegmentEvidence {
  formation_stroke_ids: number[];
  formation_zd: number | null;
  formation_zg: number | null;
  candidate_stroke_ids: number[];
  candidate_zd: number | null;
  candidate_zg: number | null;
  characteristic_stroke_ids: number[];
  characteristic_pattern: string | null;
  guard_side: "high" | "low" | null;
  guard_price: number | null;
  candidate_extreme: number | null;
  break_stroke_id: number | null;
  break_time: string | null;
  break_reason: string | null;
}

export interface Segment extends Stroke {
  id: number;
  status: "IS_RUNNING" | "CONFIRMED";
  evidence: SegmentEvidence | null;
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
  segment_ids: number[];
  direction: "NONE" | "UP" | "DOWN" | "SIDEWAYS";
  extend_count: number;
  status: "RUNNING" | "ENDED";
  break_segment_id: number | null;
}

export interface CenterExpansion {
  id: string;
  center_ids: number[];
  overlap_low: number;
  overlap_high: number;
  gg: number;
  dd: number;
  status: "EXPANSION_CANDIDATE";
}

export interface Signal {
  id: string;
  side: "buy" | "sell";
  type: 1 | 2 | 3;
  index: number;
  time: string;
  price: number;
  status: "candidate" | "confirmed" | "invalidated" | "expired";
  confidence: number;
  reason: string;
  center_id: number | null;
  segment_id: number | null;
  divergence_ratio: number | null;
  enter_segment_id: number | null;
  leave_segment_id: number | null;
  strength: number;
  level: string;
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
    allow_external: boolean;
  };
  data_status?: {
    ok: boolean;
    source: "akshare" | "sample" | string;
    message: string;
    refreshed_at: string;
    first_kline_time: string | null;
    last_kline_time: string | null;
    source_first_kline_time?: string | null;
    source_last_kline_time?: string | null;
    kline_count: number;
    from_cache?: boolean;
    cache_updated?: boolean;
    failed_sources?: Array<{ source: string; label: string; error: string }>;
    external_allowed?: boolean;
  };
  engine?: {
    segment_engine: string;
    rule_profile: string;
  };
  klines: KLine[];
  raw_klines: KLine[];
  fractals: Fractal[];
  strokes: Stroke[];
  segments: Segment[];
  centers: Center[];
  center_expansions: CenterExpansion[];
  divergences: Divergence[];
  signals: Signal[];
  theory_marks: TheoryMark[];
  trend?: {
    type: "unclassified" | "consolidation" | "trend";
    direction: "up" | "down" | null;
    center_count: number;
    reason: string;
  };
  analysis_cache?: {
    mode: "hit" | "incremental" | "rebuild";
    hit: boolean;
    new_kline_count: number;
    recomputed_from_time: string | null;
    engine_version: string;
    updated_at: string;
  };
  summary: Record<string, number>;
}

export interface WatchLevelView {
  level: string;
  available: boolean;
  last_time: string | null;
  close: number | null;
  trend: string;
  segment_state: string;
  macd_state: string;
  volume_ratio: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
}

export interface WatchDecision {
  symbol: string;
  action: "BUY" | "SELL" | "WAIT" | "HOLD" | "NO_TRADE";
  order_allowed: boolean;
  priority: "P0" | "P1" | "P2" | "P3" | "P4";
  position_percent: number;
  market_coefficient: number;
  current_price: number | null;
  structure: string;
  latest_signal: { label: string; time: string; price: number; status: string; reason: string } | null;
  trigger_conditions: string[];
  stop_loss: number | null;
  targets: number[];
  risks: string[];
  conclusion: string;
  levels: { daily: WatchLevelView; minute30: WatchLevelView };
  generated_at: string;
  rule_profile: string;
  data_sources: Record<string, { ok: boolean; source: string; message: string; kline_count: number }>;
}




export interface Tdx2DbTableSummary {
  period: string;
  table: string;
  bar_count: number;
  stock_count: number;
  first_time: string | null;
  last_time: string | null;
}

export interface Tdx2DbStatus {
  configured_path: string;
  detected_path: string | null;
  path_valid: boolean;
  database_path: string;
  database_files?: Array<{ path: string; bytes: number }>;
  installed: boolean;
  executable: string;
  sync: {
    status: string;
    message: string;
    started_at: string | null;
    finished_at: string | null;
    exit_code: number | null;
    running: boolean;
    processed_stocks: number;
    total_stocks: number;
    daily_bars_imported: number;
    minute5_bars_imported: number;
    current_code: string | null;
    daily_failed: number;
  };
  tables: Tdx2DbTableSummary[];
}
