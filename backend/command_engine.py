"""
CommandRuleEngine — YAML-driven command matching engine.

Replaces the hardcoded _DIAGNOSTIC_RULES list in server.py with rules
loaded from commands.yaml. Supports hot-reload so changes made via the
CommandManager frontend take effect immediately without restart.

Architecture:
  CommandRuleEngine.load()          ← called at startup and after each save
    ↓
  compile regex patterns per rule  ← cached in _rules list
    ↓
  match(text, mode) → [Match]      ← used by /api/device/test-command
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import yaml

logger = logging.getLogger("command_engine")

# ── 默认 YAML 路径 ────────────────────────────────────────────────
DEFAULT_COMMANDS_YAML = Path(__file__).resolve().parent / "commands.yaml"


@dataclass
class RuleMatch:
    """A single matched rule result."""
    rule_id: str
    intent: str
    command: str
    pattern: str
    description: str = ""


@dataclass
class CompiledRule:
    """A rule with its compiled regex pattern."""
    rule_id: str
    patterns: list[re.Pattern]
    intent: str
    command: str
    modes: frozenset[str]
    enabled: bool
    description: str


class CommandRuleEngine:
    """Singleton engine that loads and matches command rules from YAML."""

    _instance: ClassVar[CommandRuleEngine | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self):
        self._rules: list[CompiledRule] = []
        self._yaml_path: Path = DEFAULT_COMMANDS_YAML
        self._load_count: int = 0
        self._load_lock = threading.Lock()

    # ── Singleton ────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> CommandRuleEngine:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Load / Reload ────────────────────────────────────────────

    def load(self, yaml_path: str | Path | None = None) -> int:
        """Load rules from YAML. Returns number of rules compiled.

        If yaml_path is None, uses the previously set path (or default).
        Thread-safe: call from any thread (e.g. hot-reload).
        """
        with self._load_lock:
            if yaml_path is not None:
                self._yaml_path = Path(yaml_path)

            if not self._yaml_path.exists():
                logger.warning("Commands YAML not found: %s", self._yaml_path)
                self._rules = []
                return 0

            try:
                with open(self._yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception as exc:
                logger.error("Failed to load commands YAML: %s", exc)
                return len(self._rules)  # keep existing rules on error

            raw_rules = data.get("command_rules", []) if data else []
            compiled: list[CompiledRule] = []

            for raw in raw_rules:
                if not isinstance(raw, dict):
                    continue
                rule_id = str(raw.get("id", ""))
                if not rule_id:
                    continue

                raw_patterns = raw.get("patterns", [])
                if isinstance(raw_patterns, str):
                    raw_patterns = [raw_patterns]

                try:
                    patterns = [re.compile(p, re.IGNORECASE) for p in raw_patterns]
                except re.error as exc:
                    logger.warning("Bad regex in rule '%s': %s", rule_id, exc)
                    continue

                compiled.append(CompiledRule(
                    rule_id=rule_id,
                    patterns=patterns,
                    intent=str(raw.get("intent", "")),
                    command=str(raw.get("command", "")),
                    modes=frozenset(raw.get("modes", [])),
                    enabled=bool(raw.get("enabled", True)),
                    description=str(raw.get("description", "")),
                ))

            self._rules = compiled
            self._load_count += 1
            logger.info("Loaded %d command rules (total loads: %d)", len(compiled), self._load_count)
            return len(compiled)

    def reload(self, yaml_path: str | Path | None = None) -> int:
        """Convenience alias for load() — triggers full reload."""
        return self.load(yaml_path=yaml_path)

    # ── Matching ────────────────────────────────────────────────

    def match(self, text: str, mode: str) -> list[RuleMatch]:
        """Match text against all enabled rules for the given session mode.

        Returns a list of RuleMatch objects, ordered by rule position in YAML.
        (Multiple rules may match the same text; the caller should take the
        first match, or accumulate them as appropriate.)
        """
        if not text or not self._rules:
            return []

        results: list[RuleMatch] = []
        pass_through_modes = frozenset({"story", "spark", "song"})

        for rule in self._rules:
            if not rule.enabled:
                continue

            # In pass-through modes, only match rules that include the current mode
            if mode in pass_through_modes:
                if mode not in rule.modes:
                    continue
            else:
                if mode not in rule.modes and "unknown" not in rule.modes and "dialogue" not in rule.modes:
                    # If the rule has explicit modes and neither the current mode nor
                    # dialogue/unknown is included, skip
                    if rule.modes and mode not in rule.modes:
                        continue

            for pattern in rule.patterns:
                if pattern.search(text):
                    results.append(RuleMatch(
                        rule_id=rule.rule_id,
                        intent=rule.intent,
                        command=rule.command,
                        pattern=pattern.pattern,
                        description=rule.description,
                    ))
                    break  # one match per rule

        return results

    def match_first(self, text: str, mode: str) -> RuleMatch | None:
        """Match text and return only the first matching rule, if any."""
        matches = self.match(text, mode)
        return matches[0] if matches else None

    # ── Introspection ────────────────────────────────────────────

    @property
    def rules(self) -> list[CompiledRule]:
        return list(self._rules)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    @property
    def load_count(self) -> int:
        return self._load_count

    def get_enabled_rules(self) -> list[CompiledRule]:
        return [r for r in self._rules if r.enabled]

    def get_rule_ids(self) -> list[str]:
        return [r.rule_id for r in self._rules]


# ── Module-level convenience ────────────────────────────────────

_engine: CommandRuleEngine | None = None


def get_engine() -> CommandRuleEngine:
    """Get or create the global CommandRuleEngine instance."""
    global _engine
    if _engine is None:
        _engine = CommandRuleEngine.get_instance()
        _engine.load()
    return _engine


def reload_engine(yaml_path: str | Path | None = None) -> int:
    """Reload the global engine and return rule count."""
    eng = get_engine()
    return eng.reload(yaml_path=yaml_path)
