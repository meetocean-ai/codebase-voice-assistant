# Codebase Voice Assistant

Claude Code plugin — talk to Claude about your codebase using voice. Ask questions through your mic and hear answers through your speakers, or join a conference call as an AI participant.

## Two Modes

### Local Voice (Free)

Talk to Claude through your microphone. Only needs a Deepgram API key (free tier: 12,000 min/month).

```
/voice-config    # set your Deepgram API key
/voice-start     # start talking
```

Say **"Hey Claude"** followed by your question. Claude searches the codebase and answers via voice.

### Conference Call (Pro)

Dial into Zoom, Meet, or Teams as an AI participant. Everyone on the call can ask codebase questions. Requires LiveKit + Twilio.

```
/voice-config                         # set all API keys
/voice-join +15551234567 12345#       # join with dial-in + PIN
```

## Quick Start

```bash
# Clone and install
git clone https://github.com/artemustimenko/codebase-voice-assistant.git
cd codebase-voice-assistant
./scripts/setup.sh

# Use as a Claude Code plugin
claude --plugin-dir /path/to/codebase-voice-assistant
```

## How It Works

1. You run `/voice-start` (local) or `/voice-join` (conference call)
2. Say **"Hey Claude"** followed by a question about your codebase
3. Claude searches the code using its built-in tools (Read, Grep, Glob)
4. The answer is spoken aloud via text-to-speech
5. Say **"Claude, leave"** to disconnect

## Architecture

```
Mic / Conference Call
       |
   Audio Capture
       |
   Deepgram STT (streaming)
       |
   Wake Word Detector ("Hey Claude")
       |
   Question Queue ──> Claude Code (searches codebase)
       |                      |
   Filler audio          Codebase answer
       |                      |
   Deepgram TTS <────────────┘
       |
   Speakers / Conference Call
```

## Requirements

- Python 3.11+
- Deepgram API key (free tier available)
- For Pro mode: LiveKit Cloud + Twilio accounts

## Commands

| Command | Description |
|---------|-------------|
| `/voice-start` | Start local voice session (free) |
| `/voice-join <number> [pin]` | Join conference call (pro) |
| `/voice-config` | Configure API keys |
| `/voice-status` | Check session status |
