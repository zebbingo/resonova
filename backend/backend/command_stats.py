"""
CommandStatsCollector — tracks command matching and forwarding stats from
the monitoring event pipeline.

Data is accumulated in memory and can be retrieved via the /api/commands/stats
endpoint. In a future iteration this could be persisted to a database or time-series store.

Architecture:
  monitoring WebSocket → _evaluate_and_transform_event()
    ↓
  kws_match / command_detected / command_forwarded events
    ↓
  CommandStatsCollector.record_event(event)  ← called from event transform
    ↓
  /api/commands/stats → collector.get_summary()
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

logger = logging.getLogger("command_stats")


class CommandStatsCollector:
    """In-memory collector for command usage statistics.

    Thread-safe: uses a Lock for all mutations.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # Per-rule hit counts
        self._rule_hits: dict[str, int] = defaultdict(int)

        # Per-rule forwarding counts (command was actually sent to device)
        self._rule_forwards: dict[str, int] = defaultdict(int)

        # Per-rule block counts (command was intercepted/filtered)
        self._rule_blocks: dict[str, int] = defaultdict(int)

        # Per-mode breakdown
        self._mode_hits: dict[str, int] = defaultdict(int)

        # Timestamp of first recorded event
        self._started_at: float = time.time()

        # Last event timestamp
        self._last_event_at: float = 0.0

        # Total events received
        self._total_events: int = 0

    # ── Recording ──────────────────────────────────────────────

    def record_event(self, event: dict) -> None:
        """Record a monitoring event for stats purposes.

        Recognized event types:
          - kws_match
          - command_detected
          - command_forwarded
          - command_filtered
        """
        event_type = event.get("type", "")
        if event_type not in ("kws_match", "command_detected", "command_forwarded", "command_filtered"):
            return

        with self._lock:
            self._total_events += 1
            self._last_event_at = time.time()

            keyword = event.get("keyword", "")
            command_name = event.get("command", "") or event.get("cmd", "")
            session_mode = event.get("session_mode", "") or event.get("mode", "")
            rule_id = event.get("rule_id", "") or keyword or command_name

            if event_type in ("kws_match", "command_detected"):
                self._rule_hits[rule_id] += 1
                if session_mode:
                    self._mode_hits[session_mode] += 1

            if event_type == "command_forwarded":
                self._rule_forwards[rule_id] += 1

            if event_type == "command_filtered" or event.get("is_blocked"):
                self._rule_blocks[rule_id] += 1

    def record_match(self, rule_id: str, command: str, mode: str = "") -> None:
        """Directly record a match (called from test-command or elsewhere)."""
        with self._lock:
            self._total_events += 1
            self._last_event_at = time.time()
            self._rule_hits[rule_id] += 1
            if mode:
                self._mode_hits[mode] += 1

    # ── Query ──────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Return a snapshot of current stats."""
        with self._lock:
            elapsed = time.time() - self._started_at
            return {
                "total_events": self._total_events,
                "uptime_seconds": round(elapsed, 1),
                "last_event_at": self._last_event_at,
                "last_event_ago_seconds": round(time.time() - self._last_event_at, 1) if self._last_event_at else None,
                "rules": dict(self._rule_hits),
                "forwards": dict(self._rule_forwards),
                "blocks": dict(self._rule_blocks),
                "by_mode": dict(self._mode_hits),
                "rule_ids": sorted(set(
                    list(self._rule_hits.keys())
                    + list(self._rule_forwards.keys())
                    + list(self._rule_blocks.keys())
                )),
            }

    def get_rule_stats(self, rule_id: str) -> dict | None:
        """Get stats for a single rule."""
        with self._lock:
            if rule_id not in self._rule_hits and rule_id not in self._rule_forwards:
                return None
            return {
                "rule_id": rule_id,
                "hits": self._rule_hits.get(rule_id, 0),
                "forwards": self._rule_forwards.get(rule_id, 0),
                "blocks": self._rule_blocks.get(rule_id, 0),
            }

    def reset(self) -> None:
        """Reset all stats."""
        with self._lock:
            self._rule_hits.clear()
            self._rule_forwards.clear()
            self._rule_blocks.clear()
            self._mode_hits.clear()
            self._total_events = 0
            self._started_at = time.time()
            self._last_event_at = 0.0

    @property
    def total_events(self) -> int:
        with self._lock:
            return self._total_events


# ── Module-level singleton ────────────────────────────────────

_collector: CommandStatsCollector | None = None


def get_collector() -> CommandStatsCollector:
    global _collector
    if _collector is None:
        _collector = CommandStatsCollector()
    return _collector
