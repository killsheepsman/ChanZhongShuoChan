import { useMemo } from "react";
import type { AnalyzeParams } from "../lib/api";
import type { StockOption } from "../types";

const MAX_STOCK_SUGGESTIONS = 80;

interface ControlBarProps {
  params: AnalyzeParams;
  loading: boolean;
  stockName?: string;
  stocks: StockOption[];
  stockNameInput: string;
  onStockNameInputChange: (value: string) => void;
  onChange: (params: AnalyzeParams) => void;
  onSelectStock: (stock: StockOption) => void;
  onPrevStock: () => void;
  onNextStock: () => void;
  onRun: () => void;
}

export function ControlBar({
  params,
  loading,
  stockName,
  stocks,
  stockNameInput,
  onStockNameInputChange,
  onChange,
  onSelectStock,
  onPrevStock,
  onNextStock,
  onRun,
}: ControlBarProps) {
  const codeOptions = useMemo(() => matchingStocks(stocks, params.symbol, params.symbol), [params.symbol, stocks]);
  const nameOptions = useMemo(() => matchingStocks(stocks, stockNameInput, params.symbol), [params.symbol, stockNameInput, stocks]);
  const selectOptions = useMemo(
    () => matchingStocks(stocks, stockNameInput || params.symbol, params.symbol),
    [params.symbol, stockNameInput, stocks]
  );

  function pickByCode(value: string) {
    const code = value.trim().padStart(value.trim().length >= 6 ? 6 : value.trim().length, "0");
    const stock = stocks.find((item) => item.code === code);
    if (stock) onSelectStock(stock);
  }

  function pickByName(value: string) {
    const keyword = value.trim();
    const stock = stocks.find((item) => item.name === keyword || `${item.code} ${item.name}` === keyword);
    if (stock) onSelectStock(stock);
  }

  return (
    <header className="control-bar">
      <div className="brand-block">
        <h1>缠论结构分析</h1>
        <span>{stockName ? `${params.symbol} ${stockName}` : "AKShare 实时导入 · 三买三卖标注"}</span>
      </div>

      <label>
        股票代码
        <input
          list="stock-code-list"
          value={params.symbol}
          onBlur={(event) => pickByCode(event.target.value)}
          onChange={(event) => onChange({ ...params, symbol: event.target.value.trim() })}
          onKeyDown={(event) => {
            if (event.key === "Enter") pickByCode(event.currentTarget.value);
          }}
        />
      </label>

      <label>
        公司名称
        <input
          list="stock-name-list"
          value={stockNameInput}
          onBlur={(event) => pickByName(event.target.value)}
          onChange={(event) => onStockNameInputChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") pickByName(event.currentTarget.value);
          }}
        />
      </label>

      <label>
        上市公司
        <select
          value={params.symbol}
          onChange={(event) => {
            const stock = stocks.find((item) => item.code === event.target.value);
            if (stock) onSelectStock(stock);
          }}
        >
          {selectOptions.map((stock) => (
            <option key={stock.code} value={stock.code}>
              {stock.code} {stock.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        周期
        <select value={params.period} onChange={(event) => onChange({ ...params, period: event.target.value })}>
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
        起始
        <input value={params.startDate} onChange={(event) => onChange({ ...params, startDate: event.target.value })} />
      </label>

      <label>
        结束
        <input value={params.endDate} onChange={(event) => onChange({ ...params, endDate: event.target.value })} />
      </label>

      <label>
        复权
        <select value={params.adjust} onChange={(event) => onChange({ ...params, adjust: event.target.value })}>
          <option value="qfq">前复权</option>
          <option value="">不复权</option>
          <option value="hfq">后复权</option>
        </select>
      </label>

      <label className="external-data-toggle" title="关闭时只读取通达信本地库和项目缓存；开启后才允许联网补齐本地缺失的最新数据。">
        <span>允许外部补数</span>
        <input
          type="checkbox"
          checked={params.allowExternal}
          onChange={(event) => onChange({ ...params, allowExternal: event.target.checked })}
        />
      </label>

      <div className="run-controls">
        <button className="nav-button" type="button" onClick={onPrevStock} disabled={loading || stocks.length === 0}>
          上一只
        </button>
        <button className="primary-button" type="button" onClick={onRun} disabled={loading}>
          {loading ? "分析中" : "分析"}
        </button>
        <button className="nav-button" type="button" onClick={onNextStock} disabled={loading || stocks.length === 0}>
          下一只
        </button>
      </div>

      <datalist id="stock-code-list">
        {codeOptions.map((stock) => (
          <option key={stock.code} value={stock.code}>
            {stock.name}
          </option>
        ))}
      </datalist>
      <datalist id="stock-name-list">
        {nameOptions.map((stock) => (
          <option key={stock.code} value={stock.name}>
            {stock.code}
          </option>
        ))}
      </datalist>
    </header>
  );
}

function matchingStocks(stocks: StockOption[], query: string, selectedCode: string) {
  const normalized = query.trim().toLocaleLowerCase();
  const selected = stocks.find((stock) => stock.code === selectedCode);
  const matches = normalized
    ? stocks.filter((stock) => stock.code.includes(normalized) || stock.name.toLocaleLowerCase().includes(normalized))
    : stocks;
  const ordered = selected ? [selected, ...matches.filter((stock) => stock.code !== selected.code)] : matches;
  return ordered.slice(0, MAX_STOCK_SUGGESTIONS);
}
