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
