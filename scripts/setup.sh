#!/usr/bin/env bash
# Quick setup script for the codebase voice assistant plugin.
#
# Usage:
#   cd codebase-voice-assistant
#   ./scripts/setup.sh
#
# This will:
# 1. Create a Python virtual environment
# 2. Install dependencies
# 3. Install the audio driver
# 4. Verify the setup

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Setting up Codebase Voice Assistant"
echo "    Project: $PROJECT_DIR"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    echo "Error: Python 3.11+ required (found $PYTHON_VERSION)"
    exit 1
fi
echo "==> Python $PYTHON_VERSION found"

# Create venv
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv "$PROJECT_DIR/.venv"
fi

# Activate and install
echo "==> Installing dependencies..."
source "$PROJECT_DIR/.venv/bin/activate"
pip install -q --upgrade pip
pip install -q -e "$PROJECT_DIR"

# Install audio driver
echo ""
echo "==> Setting up audio driver..."
bash "$SCRIPT_DIR/install-audio-driver.sh"

# Verify
echo ""
echo "==> Verifying installation..."
python3 -c "
import src.server
import src.voice.pipeline
import src.call.manager
print('All modules imported successfully!')
"

echo ""
echo "============================================"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Load the plugin in Claude Code:"
echo "     claude --plugin-dir $PROJECT_DIR"
echo ""
echo "  2. Configure your API keys:"
echo "     /voice-config"
echo ""
echo "  3. Join a call:"
echo "     /voice-join +15551234567 12345#"
echo "============================================"
