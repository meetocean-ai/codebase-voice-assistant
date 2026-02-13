---
name: voice-join
description: "[Pro] Join a conference call as a voice AI assistant that can answer questions about the current codebase. Dials into Zoom, Meet, or Teams via phone."
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - mcp__codebase-voice__start_call_session
  - mcp__codebase-voice__poll_question
  - mcp__codebase-voice__provide_answer
  - mcp__codebase-voice__stop_session
  - mcp__codebase-voice__get_config
  - Read
  - Grep
  - Glob
---

# Voice Join — Join a Call as a Codebase AI Assistant [Pro]

Join a conference call via SIP dial-in. The assistant dials the conference number, joins as its own participant ("Claude - Codebase Assistant"), and answers codebase questions from anyone on the call.

Requires LiveKit + Twilio configuration. Run `/voice-config` first.

## Arguments

- `$1` — The dial-in phone number (e.g., `+15551234567`)
- `$2` — The meeting PIN/access code (optional, e.g., `12345#`)

If no arguments are provided, ask the user for the dial-in number.

## Steps

1. **Check configuration**: Call `mcp__codebase-voice__get_config` to verify Deepgram AND telephony keys (LiveKit + Twilio) are set. If telephony is not configured, tell the user this is a Pro feature, suggest `/voice-start` as the free alternative, and stop.

2. **Index the codebase**: Quickly scan the current project:
   - Use `Glob` with `**/*.{py,js,ts,go,rs,java,rb,cpp,c,h}` to get source files (limit to first 50)
   - Use `Read` to read: README.md, CLAUDE.md, package.json or pyproject.toml
   - Build a 2-3 sentence codebase summary

3. **Join the call**: Call `mcp__codebase-voice__start_call_session` with the project path, codebase summary, dial-in number, and optional PIN.

4. **Tell the user** the assistant has joined the call.

5. **Enter the question-answer loop**: Same as /voice-start:

   ```
   LOOP:
     a. Call mcp__codebase-voice__poll_question (timeout_ms: 2000)
     b. If result is "__NO_QUESTION__" → go to step a
     c. If result is "__LEAVE__" → call stop_session and exit
     d. If result is "__SESSION_ENDED__" → exit
     e. Otherwise, it's a codebase question:
        - Use Grep and Read to find relevant code
        - Formulate a concise answer (1-3 sentences, conversational)
        - Call mcp__codebase-voice__provide_answer with the answer
        - Go to step a
   ```

6. **On exit**: Call `mcp__codebase-voice__stop_session` and tell the user the session ended.
