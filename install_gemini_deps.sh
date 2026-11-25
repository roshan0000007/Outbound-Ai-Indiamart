#!/bin/bash
# Quick installation script for Gemini Live dependencies

set -e

echo "=================================="
echo "INSTALLING GEMINI LIVE DEPENDENCIES"
echo "=================================="
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Virtual environment not activated"
    echo "Please run: source venv/bin/activate"
    exit 1
fi

echo "✅ Using virtual environment: $VIRTUAL_ENV"
echo ""

echo "[1] Upgrading pip..."
python -m pip install --upgrade pip setuptools wheel -q

echo "[2] Installing google-generativeai..."
pip install "google-generativeai>=0.4.0" -q

echo "[3] Installing websockets..."
pip install "websockets>=11.0" -q

echo ""
echo "[4] Verifying installation..."
python -c "import google.generativeai; import websockets; print('✅ All packages installed successfully')"

echo ""
echo "=================================="
echo "✅ INSTALLATION COMPLETE"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. cd /opt/IndiaMart"
echo "2. python main.py"
echo ""
echo "You should see:"
echo "[Gemini Live] ✅ Client initialized successfully"
echo ""
