import { useCallback, useEffect, useMemo, useState } from "react";
import { ChartPanel } from "./components/ChartPanel";
import { ControlBar } from "./components/ControlBar";
import { LayerToggles } from "./components/LayerToggles";
import { SignalPanel } from "./components/SignalPanel";
import { SignalScanner } from "./components/SignalScanner";
import { Tdx2DbPanel } from "./components/Tdx2DbPanel";
import {
  AnalyzeParams,
  fetchAnalysis,
  configureTdx2Db,  fetchSignalScanStatus,
  fetchStocks,
  fetchTdx2DbStatus,  startSignalScan,
  startTdx2DbSync,
  startTdx2DbHistoryBackfill,
  stopTdx2DbSync,
} from "./lib/api";
import type { AnalysisResponse, Signal, SignalScanMatch, StockOption, Tdx2DbStatus } from "./types";

const today = new Date();
// Use the earliest requested 603703 five-minute history by default.
const start = new Date("2024-08-12T00:00:00");
const FALLBACK_STOCKS: StockOption[] = [
  { code: "603703", name: "盛洋科技" },
  { code: "000001", name: "平安银行" },
  { code: "000002", name: "万科A" },
  { code: "600000", name: "浦发银行" },
  { code: "600519", name: "贵州茅台" },
];

export function App() {
  const [params, setParams] = useState<AnalyzeParams>({
    symbol: "603703",
    period: "5",
    startDate: formatDate(start),
    endDate: formatDate(today),
    adjust: "qfq",
    allowExternal: window.localStorage.getItem("chanlun.allowExternal") === "true",
  });
  const [stocks, setStocks] = useState<StockOption[]>(FALLBACK_STOCKS);
  const [stockNameInput, setStockNameInput] = useState("盛洋科技");
  const [layers, setLayers] = useState({
    fractals: true,
    strokes: true,
    segments: true,
    centers: true,
    divergences: true,
    theory: true,
    signals: true,
  });
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [focusedSignal, setFocusedSignal] = useState<Signal | null>(null);
  const [chartHeight, setChartHeight] = useState(760);
  const [loading, setLoading] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [scanParams, setScanParams] = useState({
    startSignalDate: formatInputDate(today),
    endSignalDate: formatInputDate(today),
    period: "5",
    side: "buy" as "buy" | "sell",
    type: 1 as 1 | 2 | 3,
  });
  const [scanMatches, setScanMatches] = useState<SignalScanMatch[]>([]);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [scanProgress, setScanProgress] = useState({ scanned: 0, total: 0, percent: 0, matched: 0 });
  const [selectedScanMatchKey, setSelectedScanMatchKey] = useState("");
  const [tdx2dbVisible, setTdx2dbVisible] = useState(false);
  const [tdx2dbStatus, setTdx2dbStatus] = useState<Tdx2DbStatus | null>(null);
  const [tdx2dbLoading, setTdx2dbLoading] = useState(false);
  const [tdx2dbError, setTdx2dbError] = useState<string | null>(null);
  const layerState = useMemo(() => layers, [layers]);

  const runAnalysis = useCallback(
    async (override?: AnalyzeParams) => {
      const requestParams = override ?? params;
      setLoading(true);
      setError(null);
      setRefreshMessage(null);
      try {
        const result = await fetchAnalysis(requestParams);
        setData(result);
        setFocusedSignal(null);
        setRefreshMessage(formatRefreshMessage(result));
        setStockNameInput(result.request.symbol_name);
      } catch (err) {
        setError(err instanceof Error ? err.message : "分析失败");
        setRefreshMessage("刷新失败");
      } finally {
        setLoading(false);
      }
    },
    [params]
  );

  function selectStock(stock: StockOption, autoRun = false) {
    const nextParams = { ...params, symbol: stock.code };
    setParams(nextParams);
    setStockNameInput(stock.name);
    if (autoRun) void runAnalysis(nextParams);
  }

  async function runSignalScan() {
    setScanLoading(true);
    setScanMessage("正在查询数据库并补充后台索引...");
    setScanProgress({ scanned: 0, total: 0, percent: 0, matched: 0 });
    setScanMatches([]);
    setSelectedScanMatchKey("");
    try {
      let status = await startSignalScan({
        ...scanParams,
        adjust: params.adjust,
      });
      while (status.job_id) {
        setScanMatches(status.matches ?? []);
        setScanProgress({
          scanned: status.scanned_count,
          total: status.total_count,
          percent: status.progress ?? 0,
          matched: status.matched_count,
        });
        setScanMessage(status.message ?? `已处理 ${status.scanned_count}/${status.total_count}`);
        if (status.status === "done" || status.status === "failed") break;
        await delay(1000);
        status = await fetchSignalScanStatus(status.job_id);
      }
    } catch (err) {
      setScanMessage(err instanceof Error ? err.message : "筛选失败");
    } finally {
      setScanLoading(false);
    }
  }

  async function saveTdx2DbPath(tdxPath: string) {
    setTdx2dbLoading(true);
    setTdx2dbError(null);
    try {
      setTdx2dbStatus(await configureTdx2Db(tdxPath));
      void fetchStocks().then((items) => items.length && setStocks(items));
    } catch (err) {
      setTdx2dbError(err instanceof Error ? err.message : "保存通达信目录失败");
    } finally {
      setTdx2dbLoading(false);
    }
  }

  async function startTdxSync() {
    setTdx2dbLoading(true);
    setTdx2dbError(null);
    try {
      setTdx2dbStatus(await startTdx2DbSync());
    } catch (err) {
      setTdx2dbError(err instanceof Error ? err.message : "启动通达信同步失败");
    } finally {
      setTdx2dbLoading(false);
    }
  }

  async function startTdxHistoryBackfill() {
    setTdx2dbLoading(true);
    setTdx2dbError(null);
    try {
      setTdx2dbStatus(await startTdx2DbHistoryBackfill());
    } catch (err) {
      setTdx2dbError(err instanceof Error ? err.message : "导入通达信5分钟历史失败");
    } finally {
      setTdx2dbLoading(false);
    }
  }

  async function stopTdxSync() {
    setTdx2dbLoading(true);
    setTdx2dbError(null);
    try {
      setTdx2dbStatus(await stopTdx2DbSync());
    } catch (err) {
      setTdx2dbError(err instanceof Error ? err.message : "停止通达信同步失败");
    } finally {
      setTdx2dbLoading(false);
    }
  }

  function selectScanMatch(match: SignalScanMatch) {
    const nextParams = { ...params, symbol: match.code, period: scanParams.period };
    setSelectedScanMatchKey(`${match.code}|${match.time}`);
    setParams(nextParams);
    setStockNameInput(match.name);
    void runAnalysis(nextParams);
  }

  const switchStock = useCallback(
    (step: -1 | 1) => {
      if (!stocks.length || loading) return;
      const currentIndex = Math.max(0, stocks.findIndex((stock) => stock.code === params.symbol));
      const nextIndex = (currentIndex + step + stocks.length) % stocks.length;
      const nextStock = stocks[nextIndex];
      const nextParams = { ...params, symbol: nextStock.code };
      setParams(nextParams);
      setStockNameInput(nextStock.name);
      void runAnalysis(nextParams);
    },
    [loading, params, runAnalysis, stocks]
  );

  function exportKlineCsv() {
    if (!data?.raw_klines.length) return;
    const symbol = data.request.symbol;
    const stockName = data.request.symbol_name || stockNameInput || "";
    const startDate = data.request.start_date || params.startDate;
    const endDate = data.request.end_date || params.endDate;
    const fileName = `${sanitizeFileName(symbol)}${sanitizeFileName(stockName)}${startDate}${endDate}.csv`;
    const rows = [
      ["日期", "股票代码", "股票名称", "高", "低", "开", "收"],
      ...data.raw_klines.map((kline) => [
        kline.time,
        symbol,
        stockName,
        formatCsvNumber(kline.high),
        formatCsvNumber(kline.low),
        formatCsvNumber(kline.open),
        formatCsvNumber(kline.close),
      ]),
    ];
    const csv = rows.map((row) => row.map(escapeCsvCell).join(",")).join("\r\n");
    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  useEffect(() => {
    if (!tdx2dbVisible) return;
    let cancelled = false;
    void fetchTdx2DbStatus()
      .then((status) => {
        if (!cancelled) setTdx2dbStatus(status);
      })
      .catch((err) => {
        if (!cancelled) setTdx2dbError(err instanceof Error ? err.message : "读取通达信本地库状态失败");
      });
    return () => {
      cancelled = true;
    };
  }, [tdx2dbVisible]);

  useEffect(() => {
    window.localStorage.setItem("chanlun.allowExternal", String(params.allowExternal));
  }, [params.allowExternal]);

  const tdxSyncActive =
    tdx2dbStatus?.sync.status === "running" ||
    tdx2dbStatus?.sync.status === "stopping";

  useEffect(() => {
    if (!tdx2dbVisible || !tdxSyncActive) return;
    const timer = window.setInterval(() => {
      void fetchTdx2DbStatus()
        .then(setTdx2dbStatus)
        .catch((err) => setTdx2dbError(err instanceof Error ? err.message : "刷新通达信同步状态失败"));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [tdx2dbVisible, tdxSyncActive]);

  useEffect(() => {
    void fetchStocks()
      .then((items) => {
        if (!items.length) return;
        setStocks(items);
        const current = items.find((stock) => stock.code === params.symbol);
        if (current) setStockNameInput(current.name);
      })
      .catch(() => {
        setStocks(FALLBACK_STOCKS);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      if (tagName === "input" || tagName === "select" || tagName === "textarea" || target?.isContentEditable) return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        switchStock(-1);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        switchStock(1);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [switchStock]);

  return (
    <main className="app-shell">
      <ControlBar
        params={params}
        loading={loading}
        stockName={data?.request.symbol_name}
        stocks={stocks}
        stockNameInput={stockNameInput}
        onStockNameInputChange={setStockNameInput}
        onChange={setParams}
        onSelectStock={(stock) => selectStock(stock)}
        onPrevStock={() => switchStock(-1)}
        onNextStock={() => switchStock(1)}
        onRun={() => void runAnalysis()}
      />
      <section className="workspace">
        <div className="chart-column">
          <div className="toolbar-row">
            <LayerToggles
              layers={layerState}
              onToggle={(key) => setLayers((current) => ({ ...current, [key]: !current[key as keyof typeof current] }))}
            />
            <div className="chart-height-control">
              <span>图高</span>
              <input
                type="range"
                min="420"
                max="1400"
                step="20"
                value={chartHeight}
                onChange={(event) => setChartHeight(Number(event.target.value))}
              />
              <input
                type="number"
                min="420"
                max="1400"
                step="20"
                value={chartHeight}
                onChange={(event) => setChartHeight(clampHeight(Number(event.target.value)))}
              />
            </div>
            <button className="small-button" type="button" disabled={!data?.klines.length} onClick={exportKlineCsv}>
              导出CSV
            </button>
            <button className="small-button" type="button" aria-pressed={tdx2dbVisible} onClick={() => setTdx2dbVisible((visible) => !visible)}>
              {tdx2dbVisible ? "隐藏通达信本地库" : "显示通达信本地库"}
            </button>
            {refreshMessage && (
              <div
                className={`refresh-banner ${data?.data_status?.ok === false ? "warning" : "success"}`}
                title={data?.data_status?.message ?? refreshMessage}
              >
                {refreshMessage}
              </div>
            )}
            {error && <div className="error-banner">{error}</div>}
          </div>
          <SignalScanner
            startSignalDate={scanParams.startSignalDate}
            endSignalDate={scanParams.endSignalDate}
            period={scanParams.period}
            side={scanParams.side}
            type={scanParams.type}
            loading={scanLoading}
            matches={scanMatches}
            message={scanMessage}
            progress={scanProgress}
            selectedMatchKey={selectedScanMatchKey}
            onChange={(next) => setScanParams((current) => ({ ...current, ...next }))}
            onScan={() => void runSignalScan()}
            onSelect={selectScanMatch}
          />
          {tdx2dbVisible && (
            <Tdx2DbPanel
              status={tdx2dbStatus}
              loading={tdx2dbLoading}
              error={tdx2dbError}
              onConfigure={(tdxPath) => void saveTdx2DbPath(tdxPath)}
              onStart={() => void startTdxSync()}
              onBackfill={() => void startTdxHistoryBackfill()}
              onStop={() => void stopTdxSync()}
            />
          )}
          <ChartPanel data={data} focusedSignal={focusedSignal} chartHeight={chartHeight} layers={layers} />
        </div>
        <SignalPanel data={data} selectedSignalId={focusedSignal?.id ?? null} onSignalClick={setFocusedSignal} assistantParams={params} />
      </section>
    </main>
  );
}

function formatDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

function formatInputDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function clampHeight(value: number) {
  if (!Number.isFinite(value)) return 760;
  return Math.min(1400, Math.max(420, value));
}

function sanitizeFileName(value: string) {
  return value.replace(/[\\/:*?"<>|\s]+/g, "");
}

function formatCsvNumber(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : "";
}

function escapeCsvCell(value: string | number) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function formatRefreshMessage(result: AnalysisResponse) {
  const status = result.data_status;
  if (!status) {
    const last = result.klines.at(-1)?.time ?? "-";
    return `刷新完成：${result.klines.length} 根K线，最新 ${last}`;
  }
  const source = formatDataSource(status.source);
  const last = status.last_kline_time ?? "-";
  const cache = result.analysis_cache;
  const cacheText = cache?.mode === "hit"
    ? "结构缓存命中"
    : cache?.mode === "incremental"
      ? `增量续算 ${cache.new_kline_count} 根`
      : "结构缓存已重建";
  return `${source}${status.ok ? "刷新成功" : "刷新异常"}：${status.kline_count} 根K线，${cacheText}，最新 ${last}`;
}

function formatDataSource(source: string) {
  const labels: Record<string, string> = {
    "akshare-eastmoney-hist": "AKShare-东方财富历史",
    "akshare-eastmoney-minute": "AKShare-东方财富分钟",
    "akshare-sina-daily": "AKShare-新浪日线",
    "akshare-sina-minute": "AKShare-新浪分钟",
    "akshare-tencent-daily": "AKShare-腾讯日线",
    akshare: "AKShare",
    sample: "备用数据",
  };
  if (source === "local-cache") return "本地缓存";
  if (source.startsWith("local-cache+")) return `本地缓存 + ${formatDataSource(source.slice("local-cache+".length))}`;
  return labels[source] ?? source;
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
