Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Autonoma Community Edition Launcher  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Component Check
if (-not (Test-Path "daemon")) {
    Write-Host "[ERROR] 'daemon' folder not found. Are you in the right directory?" -ForegroundColor Red
    exit 1
}

# 2. Python Detection
$pythonCmd = $null
try {
    $ver = py --version 2>&1
    $pythonCmd = "py"
    Write-Host "[OK] Python Detector: Found 'py' ($ver)" -ForegroundColor Green
} catch {
    try {
        $ver = python --version 2>&1
        $pythonCmd = "python"
        Write-Host "[OK] Python Detector: Found 'python' ($ver)" -ForegroundColor Green
    } catch {
        try {
            $ver = python3 --version 2>&1
            $pythonCmd = "python3"
            Write-Host "[OK] Python Detector: Found 'python3' ($ver)" -ForegroundColor Green
        } catch {
            Write-Host "[CRITICAL] No Python found! Please install Python 3.10+." -ForegroundColor Red
            exit 1
        }
    }
}

# 3. Environment Setup
$venvPath = "daemon\venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "[INFO] First time setup: Creating Virtual Environment..." -ForegroundColor Yellow
    & $pythonCmd -m venv $venvPath
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to create venv." -ForegroundColor Red
        exit 1
    }
    
    Write-Host "[INFO] Installing Dependencies (this may take a minute)..." -ForegroundColor Yellow
    & "$venvPath\Scripts\pip" install -r daemon\requirements.txt
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red
        exit 1
    }
}

# 4. Launch
Write-Host ""
Write-Host "[INFO] Starting Autonoma Daemon..." -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Gray

# Use the venv python to run the script
& "$venvPath\Scripts\python" daemon\start.py
