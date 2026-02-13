---
name: voice-start
description: Start a voice conversation with Claude about your codebase. Talk through your mic, get answers through your speakers. Free, no telephony needed.
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - mcp__codebase-voice__start_local_session
  - mcp__codebase-voice__poll_question
  - mcp__codebase-voice__provide_answer
  - mcp__codebase-voice__stop_session
  - mcp__codebase-voice__get_config
  - Read
  - Grep
  - Glob
---

# Voice Start — Talk to Claude About Your Code

Start a local voice session. Ask questions about your codebase through your microphone and hear answers through your speakers. No telephony setup needed.

## Requirements

- Deepgram API key (free tier: 12,000 min/month)
- A microphone

## Steps

1. **Check configuration**: Call `mcp__codebase-voice__get_config` to verify Deepgram API key is set. If not configured, tell the user to run `/voice-config` first and stop.

2. **Index the codebase**: Quickly scan the current project to build context:
   - Use `Glob` with `**/*.{py,js,ts,go,rs,java,rb,cpp,c,h}` to get source files (limit to first 50)
   - Use `Read` to read: README.md, CLAUDE.md, package.json or pyproject.toml (whichever exists)
   - Build a 2-3 sentence codebase summary including: language, framework, purpose, key directories

3. **Start the session**: Call `mcp__codebase-voice__start_local_session` with the project path and codebase summary.

4. **Enter the question-answer loop**: Continuously poll for voice questions and answer them:

   ```
   LOOP:
     a. Call mcp__codebase-voice__poll_question (timeout_ms: 2000)
     b. If result is "__NO_QUESTION__" → go to step a (keep polling)
     c. If result is "__LEAVE__" → call stop_session and exit
     d. If result is "__SESSION_ENDED__" → exit
     e. Otherwise, the result is a question about the codebase:
        - Use Grep and Read to search the codebase for relevant code
        - Formulate a concise answer (1-3 sentences, conversational tone)
        - Call mcp__codebase-voice__provide_answer with the answer
        - Go to step a
   ```

   IMPORTANT: Keep answers concise and conversational. The user is listening, not reading.
   Say things like "The auth module is in src/auth.py, it uses JWT tokens for session management"
   not long code blocks or technical documentation.

5. **On exit**: Call `mcp__codebase-voice__stop_session` and tell the user the session ended.
