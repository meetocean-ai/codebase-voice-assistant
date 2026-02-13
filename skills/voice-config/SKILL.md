---
name: voice-config
description: Configure API keys and settings for the codebase voice assistant
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - mcp__codebase-voice__get_config
  - mcp__codebase-voice__set_config
  - Bash
---

# Voice Config — Set Up the Codebase Voice Assistant

Help the user configure their API keys and preferences for the voice assistant.

## Required Configuration

1. **Deepgram API Key** (required for voice)
   - Sign up at https://console.deepgram.com (free tier: 12,000 minutes/month)
   - Ask the user for their API key
   - Save with `mcp__codebase-voice__set_config` key=`deepgram_api_key`

## Optional Configuration (for SIP dial-in mode)

2. **LiveKit Cloud** (optional — needed for bot to join calls as its own participant)
   - Sign up at https://cloud.livekit.io (free tier: 50GB/month)
   - Ask for: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
   - Save each with `mcp__codebase-voice__set_config`

3. **Twilio** (optional — needed for SIP dial-in)
   - Sign up at https://www.twilio.com (trial gives $15 credit)
   - Ask for: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
   - Save each with `mcp__codebase-voice__set_config`

## Preferences

4. **Wake word** (default: "Hey Claude")
   - Save with key=`wake_word`

5. **Voice** (default: "aura-2-en-US-luna")
   - Options: luna (female), orion (male), arcas (male), stella (female)
   - Save with key=`tts_voice`

6. **STT language** (default: "en-US")
   - Save with key=`stt_language`

## Verification

After configuration, use `mcp__codebase-voice__get_config` to show the user their current settings (mask API keys, show only last 4 chars).

Tell the user they can now use `/voice-join` to join a call.
