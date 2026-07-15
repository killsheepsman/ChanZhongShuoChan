param(
  [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$PythonVenv = Join-Path $Root ".venv"
$PythonExe = Join-Path $PythonVenv "Scripts\python.exe"
$Tdx2DbPackageDir = Join-Path $Root "third_party\tdx2db-package"

function Find-Python {
  $commands = @("py", "python")
  foreach ($command in $commands) {
    $resolved = Get-Command $command -ErrorAction SilentlyContinue
    if ($resolved) {
      return $command
    }
  }
  return $null
}

function Require-Command {
  param(
    [string]$Command,
    [string]$Message
  )
  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    throw $Message
  }
}

Write-Host ""
Write-Host "Installing Chanlun Stock Analyzer dependencies..." -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host ""

$pythonCommand = Find-Python
if (-not $pythonCommand) {
  throw "Python was not found. Please install Python 3.10+ from https://www.python.org/downloads/ and check 'Add python.exe to PATH'."
}

Require-Command "npm.cmd" "Node.js/npm was not found. Please install Node.js LTS from https://nodejs.org/."

if (-not (Test-Path -LiteralPath $PythonExe)) {
  Write-Host "Creating Python virtual environment..." -ForegroundColor Green
  if ($pythonCommand -eq "py") {
    & py -3 -m venv $PythonVenv
  } else {
    & python -m venv $PythonVenv
  }
}

Write-Host "Installing backend Python packages..." -ForegroundColor Green
& $PythonExe -m pip install --upgrade pip

$pipInstallArgs = @("install", "--retries", "5", "--timeout", "60")
if (Test-Path -LiteralPath $Tdx2DbPackageDir) {
  Write-Host "Using bundled tdx2db package..." -ForegroundColor Green
  $pipInstallArgs += @("--find-links", $Tdx2DbPackageDir)
}
$pipInstallArgs += @("-r", (Join-Path $BackendDir "requirements.txt"))
& $PythonExe -m pip @pipInstallArgs

if ($LASTEXITCODE -ne 0) {
  Write-Host "Primary Python package source failed; retrying with the mirror..." -ForegroundColor Yellow
  $mirrorArgs = @("install", "--retries", "5", "--timeout", "60", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple") + $pipInstallArgs[1..($pipInstallArgs.Length - 1)]
  & $PythonExe -m pip @mirrorArgs
}
if ($LASTEXITCODE -ne 0) {
  throw "Python dependency installation failed. Check the network connection and run the installer again."
}

Write-Host "Installing frontend Node packages..." -ForegroundColor Green
Push-Location $FrontendDir
try {
  npm.cmd install
} finally {
  Pop-Location
}

Write-Host ""
Write-Host "Dependencies installed successfully." -ForegroundColor Green
Write-Host "Next step: double-click 打开股票软件.vbs" -ForegroundColor Cyan

if (-not $NoPause) {
  Read-Host "Press Enter to close"
}
