# Resonova Turn-First Monitoring Design

## Why this exists

Resonova is not a generic session tracker.
The product is built around **turns**:

- a session is the lifecycle shell
- a turn is the unit users care about
- monitoring, logs, and feedback should default to the current turn

If the UI only says “session is alive”, users still cannot tell whether the current turn was sent, transcribed, replied to, or completed.

## Design rule

Show the following in this order:

1. Current turn state
2. Current turn progress
3. Turn-level STT / LLM / TTS result
4. Session state as a secondary summary
5. Connection / heartbeat / intro state as supporting context

## What should be turn-first

- The main feedback card should start with the current turn number and turn status
- The flow summary should describe the latest turn before the session summary
- The log view should display `turn_id` explicitly when an event belongs to a turn
- E2E scripts should assert on `turn_completed`, STT text, reply text, and command output
- `session_status` is useful, but it is not the primary user-facing answer

## What should remain session-level

- device online/offline
- intro playback lifecycle
- session start / end
- heartbeat
- pipeline health

These still matter, but they should support the turn view rather than replace it.

## Practical implementation notes

- Prefer `turn_id` in logs and UI cards whenever the event has one
- Keep `session_status` as the lifecycle summary string
- For manual send actions, show “turn requested” immediately and keep the UI in a waiting state until turn completion arrives
- When debugging, group events by `turn_id` first, then inspect the surrounding session context

## Current Resonova direction

The frontend is being updated to:

- surface the current turn in the device feedback card
- add turn-aware labels to the log view
- keep the session summary visible, but secondary
- make `turn_completed` the visible end state for send-turn interactions

This design matches the actual runtime model and the way the chatbot pipeline works today.
