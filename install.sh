#!/bin/bash

echo "========================================"
echo "Hybrid Local AI Code Reviewer Installer"
echo "========================================"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1)
    echo "✓ Python found: $PYTHON_VERSION"
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_VERSION=$(python --version 2>&1)
    echo "✓ Python found: $PYTHON_VERSION"
    PYTHON_CMD=python
else
    echo "✗ Python not found. Please install Python 3.10+ from python.org"
    exit 1
fi

# Check Node.js
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version 2>&1)
    echo "✓ Node.js found: $NODE_VERSION"
else
    echo "✗ Node.js not found. Please install Node.js 18+ from nodejs.org"
    exit 1
fi

# Check VS Code
if command -v code &> /dev/null; then
    CODE_VERSION=$(code --version 2>&1 | head -n 1)
    echo "✓ VS Code found: $CODE_VERSION"
    VSCODE_AVAILABLE=true
else
    echo "⚠ VS Code CLI not found. Extension will be packaged but not auto-installed."
    echo "  You can install it manually: code --install-extension autonoma-ai-reviewer-1.0.0.vsix"
    VSCODE_AVAILABLE=false
fi

echo ""


# Bootstrap: Check if running standalone (no daemon folder)
if [ ! -d "daemon" ]; then
    echo "⚠ Core components not found locally."
    echo "⬇ Downloading Autonoma Pilot Edition (Latest)..."
    
    ZIP_URL="https://github.com/vihaaninnovations/autonoma-ai.github.io/releases/latest/download/Autonoma_Pilot_Edition.zip"
    ZIP_PATH="Autonoma_Pilot_Edition.zip"
    
    if command -v curl &> /dev/null; then
        curl -L -o "$ZIP_PATH" "$ZIP_URL"
    elif command -v wget &> /dev/null; then
        wget -O "$ZIP_PATH" "$ZIP_URL"
    else
        echo "✗ Neither curl nor wget found. Please download $ZIP_URL manually."
        exit 1
    fi

    if [ $? -eq 0 ]; then
        echo "✓ Download complete."
        echo "📦 Extracting..."
        unzip -o "$ZIP_PATH"
        rm "$ZIP_PATH"
        
        # Move up if nested
        if [ -d "Autonoma_Pilot_Edition" ]; then
            mv Autonoma_Pilot_Edition/* .
            rm -rf Autonoma_Pilot_Edition
        fi
    else
        echo "✗ Failed to download installer content."
        exit 1
    fi
fi

# Step 1: Install Python dependencies
echo "Step 1: Installing Python dependencies..."
cd daemon || exit 1

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing Python packages..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "✗ Failed to install Python dependencies"
    exit 1
fi

echo "✓ Python dependencies installed"
echo ""

# Step 2: Initialize database
echo "Step 2: Initializing database..."
$PYTHON_CMD -c "from db.db import init_db; init_db()"

if [ $? -ne 0 ]; then
    echo "✗ Failed to initialize database"
    exit 1
fi

echo "✓ Database initialized"
echo ""

# Step 3: Install VS Code extension
echo "Step 3: Installing VS Code extension..."
cd ../vscode-extension || exit 1

# Install Node.js dependencies
echo "Installing Node.js dependencies..."
npm install

if [ $? -ne 0 ]; then
    echo "✗ Failed to install Node.js dependencies"
    exit 1
fi

# Install vsce if not present
echo "Checking for vsce (VS Code Extension Manager)..."
if ! npm list -g @vscode/vsce &> /dev/null; then
    echo "Installing vsce..."
    npm install --save-dev @vscode/vsce
fi

# Compile extension
echo "Compiling extension..."
npm run compile

if [ $? -ne 0 ]; then
    echo "✗ Failed to compile extension"
    exit 1
fi

# Package extension
echo "Packaging extension..."
npm run package

if [ $? -ne 0 ]; then
    echo "✗ Failed to package extension"
    exit 1
fi

echo "✓ Extension packaged successfully"

# Install extension if VS Code CLI is available
if [ "$VSCODE_AVAILABLE" = true ]; then
    echo "Installing extension to VS Code..."
    code --install-extension autonoma-ai-reviewer-1.0.0.vsix
    
    if [ $? -eq 0 ]; then
        echo "✓ Extension installed successfully"
        echo "  Please reload VS Code (Ctrl+Shift+P > 'Developer: Reload Window')"
    else
        echo "⚠ Extension packaged but not installed. Install manually:"
        echo "  code --install-extension autonoma-ai-reviewer-1.0.0.vsix"
    fi
else
    echo "⚠ VS Code CLI not found. Extension packaged but not installed."
    echo "  Install manually: code --install-extension autonoma-ai-reviewer-1.0.0.vsix"
fi

echo ""

# Summary
echo "========================================"
echo "Installation Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Start the daemon:"
echo "   cd daemon"
echo "   source venv/bin/activate"
echo "   python start.py"
echo ""
echo "2. Reload VS Code (if extension was installed):"
echo "   Press Ctrl+Shift+P, then type: 'Developer: Reload Window'"
echo ""
echo "3. Verify installation:"
echo "   - Open Command Palette (Ctrl+Shift+P)"
echo "   - Search for 'Hybrid Reviewer'"
echo "   - You should see all commands available"
echo ""
echo "4. Check daemon health:"
echo "   Open browser: http://127.0.0.1:8000/health"
echo ""
