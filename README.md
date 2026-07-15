# 缠论股票分析软件

一个基于 AKShare 数据源的缠论股票分析工具，流程为：

`K线 -> 分型 -> 笔 -> 线段 -> 中枢 -> 趋势/盘整 -> 背驰 -> 买卖点`

## 一键使用

在 Windows 电脑上：

1. 先双击 `安装依赖.bat` 或 `安装依赖.vbs`
2. 安装完成后双击 `打开股票软件.vbs`
3. 浏览器会打开 `http://127.0.0.1:5173`

依赖安装脚本会自动：

- 创建项目本地 Python 虚拟环境 `.venv`
- 安装后端依赖 `backend/requirements.txt`
- 安装前端依赖 `frontend/package.json`

## 手动启动

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-stock.ps1
```

## 技术栈

- 后端：Python + FastAPI + AKShare + pandas
- 前端：React + TypeScript + Vite + Lightweight Charts
- 缓存：SQLite，用于后台买卖点筛选结果

## 目录

```text
backend/
  app/
    chanlun/       # 缠论结构与买卖点算法
    services/      # AKShare 数据、信号缓存
frontend/
  src/
    components/    # 图表、控制栏、筛选面板
docs/
start-stock.ps1    # 启动前后端
install-deps.ps1   # 一键安装依赖
```

## 注意

- `data/`、`logs/`、`.venv/`、`frontend/node_modules/` 是本机生成目录，不提交到仓库。
- 首次筛选股票时会在本机 `data/` 下生成 SQLite 缓存。

## 通达信本地数据源

项目已接入 [xbfighting/tdx2db](https://github.com/xbfighting/tdx2db)，优先读取本机通达信安装目录中的原始行情文件。

1. 在软件工具栏点击“显示通达信本地库”。
2. 确认目录指向包含 `vipdoc` 文件夹的通达信安装目录，例如 `C:\new_tdx64`，然后点击“保存目录”。
3. 点击“增量同步”才会开始导入；软件不会自动下载全市场数据。同步可随时点击“停止”，下次继续同步时 `tdx2db` 会按已有本地数据库增量补齐。

本地数据库保存在 `data\chanlun_tdx.db`，当前支持日线、5 分钟、15 分钟、30 分钟和 60 分钟。通达信原始数据为不复权数据；1 分钟周期仍使用项目缓存或在线备用数据源。

## 连续增量分析缓存

每次完成股票分析后，程序会把笔、线段、中枢、买卖点、MACD 状态和原始 K 线摘要保存到 `data\analysis_cache.sqlite3`。

- 相同股票、周期、复权和起始日期且 K 线未变化时，直接返回结构快照。
- 只有尾部新增 K 线时，从最后确认笔之前的可变结构尾部连续续算；历史确认结构和编号不截断。
- 行情历史被修订、请求起点变化或分析引擎版本升级时，缓存自动失效并全量重建。
- 信号筛选索引记录分析引擎版本，旧规则生成的信号不会冒充当前结果。

API 响应中的 `analysis_cache.mode` 为 `rebuild`、`incremental` 或 `hit`，分别表示全量重建、连续增量续算和直接命中。
