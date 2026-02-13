#!/usr/bin/env bash
# Install virtual audio driver for system audio capture.
#
# macOS: Installs BlackHole (2-channel) via Homebrew
# Linux: Configures PulseAudio monitor source (usually built-in)
#
# This is needed for "local mode" where the bot listens to meeting audio
# through the system output and speaks back through a virtual microphone.

set -euo pipefail

OS="$(uname -s)"

case "$OS" in
    Darwin)
        echo "==> macOS detected"

        if ! command -v brew &>/dev/null; then
            echo "Error: Homebrew is required. Install from https://brew.sh"
            exit 1
        fi

        if brew list blackhole-2ch &>/dev/null; then
            echo "==> BlackHole 2ch already installed"
        else
            echo "==> Installing BlackHole 2ch virtual audio driver..."
            brew install blackhole-2ch
        fi

        echo ""
        echo "==> Setup instructions:"
        echo "1. Open 'Audio MIDI Setup' (search in Spotlight)"
        echo "2. Click '+' at bottom left -> 'Create Multi-Output Device'"
        echo "3. Check both your speakers/headphones AND BlackHole 2ch"
        echo "4. Set this Multi-Output Device as your system output"
        echo ""
        echo "This routes your meeting audio to both your ears AND the voice assistant."
        echo "The assistant will capture audio from the BlackHole device."
        ;;

    Linux)
        echo "==> Linux detected"

        if command -v pactl &>/dev/null; then
            echo "==> PulseAudio found"
            # List monitor sources
            echo "Available monitor sources:"
            pactl list short sources | grep monitor
            echo ""
            echo "The voice assistant will automatically detect the PulseAudio monitor source."
        elif command -v pipewire &>/dev/null; then
            echo "==> PipeWire found"
            echo "PipeWire provides PulseAudio compatibility. The voice assistant should work automatically."
        else
            echo "Error: PulseAudio or PipeWire is required for system audio capture on Linux."
            exit 1
        fi
        ;;

    *)
        echo "Error: Unsupported OS: $OS"
        echo "Currently supported: macOS (Darwin), Linux"
        exit 1
        ;;
esac

echo ""
echo "==> Audio driver setup complete!"
echo "Run '/voice-config' in Claude Code to configure your API keys."
