param(
  [switch]$NoBrowser,
  [switch]$NoPause,
  [switch]$Restart
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogDir = Join-Path $Root "logs"
$BrowserProfileDir = Join-Path $Root ".browser-profile"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Node = Join-Path $env:ProgramFiles "nodejs\node.exe"

if (-not (Test-Path -LiteralPath $Python)) {
  $BundledPython = "C:\Users\77247\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path -LiteralPath $BundledPython) {
    $Python = $BundledPython
  } else {
    $Python = "python"
  }
}

function Test-PortListening {
  param([int]$Port)
  $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return [bool]$listener
}

function Stop-PortListener {
  param([int]$Port)
  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    if ($listener.OwningProcess) {
      Write-Host "Stopping process $($listener.OwningProcess) on port $Port..." -ForegroundColor Yellow
      Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
  }
}

function Wait-HttpOk {
  param(
    [string]$Url,
    [int]$Seconds = 30
  )
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $Url
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
        return $true
      }
    } catch {
      Start-Sleep -Milliseconds 700
    }
  }
  return $false
}

function Start-ServiceProcess {
  param(
    [string]$Title,
    [string]$WorkingDirectory,
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$OutLog,
    [string]$ErrLog
  )
  Write-Host "$Title starting in background..." -ForegroundColor Green
  return Start-Process     -FilePath $FilePath     -ArgumentList $ArgumentList     -WorkingDirectory $WorkingDirectory     -WindowStyle Hidden     -PassThru
}

function Find-Browser {
  $candidates = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe"
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
      return $candidate
    }
  }
  return $null
}

function Start-AppBrowser {
  param([string]$Url)
  $browser = Find-Browser
  if ($browser) {
    New-Item -ItemType Directory -Force -Path $BrowserProfileDir | Out-Null
    return Start-Process -FilePath $browser `
      -ArgumentList @("--app=$Url", "--user-data-dir=$BrowserProfileDir", "--no-first-run") `
      -PassThru
  }
  Start-Process $Url
  return $null
}

Write-Host ""
Write-Host "Starting Chanlun Stock Analyzer..." -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host ""
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if ($Restart) {
  Stop-PortListener 8000
  Stop-PortListener 5173
  Start-Sleep -Seconds 2
}

if (Test-PortListening 8000) {
  Write-Host "Backend already running on http://127.0.0.1:8000" -ForegroundColor Yellow
} else {
  Start-ServiceProcess `
    -Title "Backend" `
    -WorkingDirectory $BackendDir `
    -FilePath $Python `
    -ArgumentList @("-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -OutLog (Join-Path $LogDir "backend.out.log") `
    -ErrLog (Join-Path $LogDir "backend.err.log") | Out-Null
}

if (Test-PortListening 5173) {
  Write-Host "Frontend already running on http://127.0.0.1:5173" -ForegroundColor Yellow
} else {
  Start-ServiceProcess `
    -Title "Frontend" `
    -WorkingDirectory $FrontendDir `
    -FilePath $Node `
    -ArgumentList @((Join-Path $FrontendDir "node_modules\vite\bin\vite.js"), "--host", "127.0.0.1", "--port", "5173") `
    -OutLog (Join-Path $LogDir "frontend.out.log") `
    -ErrLog (Join-Path $LogDir "frontend.err.log") | Out-Null
}

Write-Host ""
Write-Host "Checking services..." -ForegroundColor Cyan
$backendOk = Wait-HttpOk "http://127.0.0.1:8000/api/health" 40
$frontendOk = Wait-HttpOk "http://127.0.0.1:5173" 40

if ($backendOk) {
  Write-Host "Backend OK:  http://127.0.0.1:8000" -ForegroundColor Green
} else {
  Write-Host "Backend not ready. Check the STOCK Backend 8000 window." -ForegroundColor Red
}

if ($frontendOk) {
  Write-Host "Frontend OK: http://127.0.0.1:5173" -ForegroundColor Green
} else {
  Write-Host "Frontend not ready. Check the STOCK Frontend 5173 window." -ForegroundColor Red
}

Write-Host ""
Write-Host "App URL: http://127.0.0.1:5173" -ForegroundColor Cyan
Write-Host "Logs: $LogDir" -ForegroundColor Cyan

if ($frontendOk -and -not $NoBrowser) {
  $browserProcess = Start-AppBrowser "http://127.0.0.1:5173"
  if ($browserProcess) {
    Write-Host "Close the app window to stop backend and frontend." -ForegroundColor Cyan
    Wait-Process -Id $browserProcess.Id -ErrorAction SilentlyContinue
    Stop-PortListener 8000
    Stop-PortListener 5173
    Write-Host "Services stopped." -ForegroundColor Green
  }
}

if (-not $NoPause) {
  Read-Host "Press Enter to close this launcher window"
}
