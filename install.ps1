Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Hybrid Local AI Code Reviewer Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Python not found. Please install Python 3.10+ from python.org" -ForegroundColor Red
    exit 1
}

# Check Node.js
try {
    $nodeVersion = node --version 2>&1
    Write-Host "✓ Node.js found: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Node.js not found. Please install Node.js 18+ from nodejs.org" -ForegroundColor Red
    exit 1
}

# Check VS Code
try {
    $codeVersion = code --version 2>&1 | Select-Object -First 1
    Write-Host "✓ VS Code found: $codeVersion" -ForegroundColor Green
} catch {
    Write-Host "⚠ VS Code CLI not found. Extension will be packaged but not auto-installed." -ForegroundColor Yellow
    Write-Host "  You can install it manually: code --install-extension autonoma-ai-reviewer-1.0.0.vsix" -ForegroundColor Yellow
}

Write-Host ""

# Bootstrap: Check if running standalone (no daemon folder)
if (-not (Test-Path "daemon")) {
    Write-Host "⚠ Core components not found locally." -ForegroundColor Yellow
    Write-Host "⬇ Downloading Autonoma Pilot Edition (Latest)..." -ForegroundColor Cyan
    
    $zipUrl = "https://github.com/vihaaninnovations/autonoma-ai.github.io/releases/latest/download/Autonoma_Pilot_Edition.zip"
    $zipPath = "Autonoma_Pilot_Edition.zip"
    
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
        Write-Host "✓ Download complete." -ForegroundColor Green
        
        Write-Host "📦 Extracting..." -ForegroundColor Cyan
        Expand-Archive -Path $zipPath -DestinationPath . -Force
        Remove-Item $zipPath
        
        # Move inner content up if nested
        if (Test-Path "Autonoma_Pilot_Edition") {
            Move-Item -Path "Autonoma_Pilot_Edition\*" -Destination . -Force
            Remove-Item "Autonoma_Pilot_Edition" -Force
        }
        
    } catch {
        Write-Host "✗ Failed to download/extract installer content." -ForegroundColor Red
        Write-Host "  Error: $_" -ForegroundColor Red
        Write-Host "  Please download the Zip manually from GitHub Releases." -ForegroundColor Yellow
        exit 1
    }
}

# Step 1: Install Python dependencies
Write-Host "Step 1: Installing Python dependencies..." -ForegroundColor Yellow
cd daemon

# Create virtual environment if it doesn't exist
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv venv
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& ".\venv\Scripts\Activate.ps1"

# Install dependencies
Write-Host "Installing Python packages..." -ForegroundColor Cyan
pip install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to install Python dependencies" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Python dependencies installed" -ForegroundColor Green
Write-Host ""

# Step 2: Initialize database
Write-Host "Step 2: Initializing database..." -ForegroundColor Yellow
python -c "from db.db import init_db; init_db()"

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to initialize database" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Database initialized" -ForegroundColor Green
Write-Host ""

# Step 3: Install VS Code extension
Write-Host "Step 3: Installing VS Code extension..." -ForegroundColor Yellow
cd ../vscode-extension

# Install Node.js dependencies
Write-Host "Installing Node.js dependencies..." -ForegroundColor Cyan
npm install

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to install Node.js dependencies" -ForegroundColor Red
    exit 1
}

# Install vsce if not present
Write-Host "Checking for vsce (VS Code Extension Manager)..." -ForegroundColor Cyan
$vsceInstalled = npm list -g @vscode/vsce 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing vsce..." -ForegroundColor Cyan
    npm install --save-dev @vscode/vsce
}

# Compile extension
Write-Host "Compiling extension..." -ForegroundColor Cyan
npm run compile

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to compile extension" -ForegroundColor Red
    exit 1
}

# Package extension
Write-Host "Packaging extension..." -ForegroundColor Cyan
npm run package

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Failed to package extension" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Extension packaged successfully" -ForegroundColor Green

# Install extension if VS Code CLI is available
if (Get-Command code -ErrorAction SilentlyContinue) {
    Write-Host "Installing extension to VS Code..." -ForegroundColor Cyan
    code --install-extension autonoma-ai-reviewer-1.0.0.vsix
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Extension installed successfully" -ForegroundColor Green
        Write-Host "  Please reload VS Code (Ctrl+Shift+P > 'Developer: Reload Window')" -ForegroundColor Cyan
    } else {
        Write-Host "⚠ Extension packaged but not installed. Install manually:" -ForegroundColor Yellow
        Write-Host "  code --install-extension autonoma-ai-reviewer-1.0.0.vsix" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠ VS Code CLI not found. Extension packaged but not installed." -ForegroundColor Yellow
    Write-Host "  Install manually: code --install-extension autonoma-ai-reviewer-1.0.0.vsix" -ForegroundColor Yellow
}

Write-Host ""

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Start the daemon:" -ForegroundColor White
Write-Host "   cd daemon" -ForegroundColor Gray
Write-Host "   .\venv\Scripts\Activate.ps1" -ForegroundColor Gray
Write-Host "   python start.py" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Reload VS Code (if extension was installed):" -ForegroundColor White
Write-Host "   Press Ctrl+Shift+P, then type: 'Developer: Reload Window'" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Verify installation:" -ForegroundColor White
Write-Host "   - Open Command Palette (Ctrl+Shift+P)" -ForegroundColor Gray
Write-Host "   - Search for 'Hybrid Reviewer'" -ForegroundColor Gray
Write-Host "   - You should see all commands available" -ForegroundColor Gray
Write-Host ""
Write-Host "4. Check daemon health:" -ForegroundColor White
Write-Host "   Open browser: http://127.0.0.1:8000/health" -ForegroundColor Gray
Write-Host ""
