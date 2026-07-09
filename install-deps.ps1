param(
  [switch]$NoPause
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$PythonVenv = Join-Path $Root ".venv"
$PythonExe = Join-Path $PythonVenv "Scripts\python.exe"

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
& $PythonExe -m pip install -r (Join-Path $BackendDir "requirements.txt")

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
