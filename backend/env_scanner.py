#!/usr/bin/env python3
"""
.env Scanner + Profile Switcher

Scans any .env file to detect "switch groups":
  Multiple lines with the SAME variable name,
  one active (uncommented), the rest commented.

Also extracts comments/descriptions from:
  1. Preceding comment blocks above each group
  2. Inline comments on each variable line
  
Supports switching which option is active by:
  commenting out the old active line,
  uncommenting the selected one.
"""

import re
import json
from pathlib import Path
from typing import Optional

LINE_PATTERN = re.compile(r"^(?P<comment>#\s*)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")
COMMENT_LINE = re.compile(r"^\s*#")
SECTION_HEADER = re.compile(r"^# [═=✧✻].*[═=✧✻]")  # decorative section headers
INLINE_COMMENT = re.compile(r"#(.+)$")


def _extract_inline_comment(text: str) -> str:
    """Extract inline comment from a line like `KEY=value # description`."""
    m = INLINE_COMMENT.search(text)
    return m.group(1).strip() if m else ""


def _clean_comment_line(line: str) -> str:
    """Clean a comment line: remove leading # and trim."""
    stripped = line.strip()
    if stripped.startswith("#"):
        stripped = stripped[1:].strip()
    return stripped


def _is_section_header(line: str) -> bool:
    """Check if line is a decorative section header."""
    return bool(SECTION_HEADER.match(line.strip()))


def scan_env_file(path: str | Path) -> dict:
    """
    Scan an .env file and return its full structure.
    
    Returns:
    {
      "file": "path/to/.env",
      "switch_groups": {
        "MQTT_HOST": {
          "description": ["comments above the group..."],
          "options": [
            {
              "value": "server-sg.zebbingo.com",
              "active": False,
              "line_index": 65,
              "comment": "inline comment after #",
              "raw_text": "# MQTT_HOST=server-sg.zebbingo.com"
            },
            ...
          ]
        }
      },
      "single_vars": [...],
      "total_lines": N
    }
    """
    path = Path(path)
    if not path.exists():
        return {"file": str(path), "error": "File not found"}
    
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Build index: key → list of line info
    key_index: dict[str, list[dict]] = {}
    # Track the group-level description comments (before the first occurrence)
    group_descriptions: dict[str, list[str]] = {}
    
    preceding_comment_block: list[str] = []
    section_header = ""
    
    for i, raw in enumerate(lines):
        stripped = raw.rstrip("\n").rstrip("\r")
        
        # Detect section headers
        if _is_section_header(stripped):
            section_header = _clean_comment_line(stripped)
            preceding_comment_block.append(stripped)
            continue
        
        m = LINE_PATTERN.match(stripped)
        if not m:
            # Track non-env-var lines as context
            if stripped.strip() == "":
                preceding_comment_block.append(stripped)
            elif COMMENT_LINE.match(stripped):
                preceding_comment_block.append(stripped)
            else:
                preceding_comment_block = []
            continue
        
        key = m.group("key")
        is_commented = bool(m.group("comment"))
        
        eq_pos = stripped.find("=")
        value = stripped[eq_pos + 1:].strip().strip("\"'") if eq_pos >= 0 else ""
        
        # Extract inline comment
        inline_comment = _extract_inline_comment(stripped)
        
        info = {
            "line_index": i,
            "key": key,
            "value": value,
            "active": not is_commented,
            "commented": is_commented,
            "comment": inline_comment,
            "raw_text": stripped,
        }
        
        if key not in key_index:
            key_index[key] = []
            # Store group-level description (non-comment, non-key lines before first occurrence)
            group_descriptions[key] = [
                _clean_comment_line(l) for l in preceding_comment_block
                if l.strip() and not _is_section_header(l)
            ]
        
        key_index[key].append(info)
        preceding_comment_block = []
    
    # Build groups
    groups = {}
    single_vars = []
    all_keys = []
    
    for key, entries in key_index.items():
        all_keys.append({"key": key, "count": len(entries)})
        if len(entries) > 1:
            # Determine if this group has an active option
            active_options = [e for e in entries if e["active"]]
            groups[key] = {
                "key": key,
                "description": group_descriptions.get(key, []),
                "options": entries,
                "active_count": len(active_options),
                "has_active": len(active_options) > 0,
            }
        else:
            single_vars.append(entries[0])
    
    return {
        "file": str(path),
        "file_name": path.name,
        "switch_groups": groups,
        "single_vars": single_vars,
        "total_lines": len(lines),
        "total_keys": len(all_keys),
    }


def switch_env_option(path: str | Path, key: str, target_value: str) -> dict:
    """
    Switch which option is active for a given key in an .env file.
    
    Given a key like "MQTT_HOST" and a target value like "server-sg.zebbingo.com",
    this will:
      1. Find all lines with that key
      2. Comment out all except the one matching target_value
      3. Uncomment the one matching target_value
    
    Returns a summary of what changed.
    """
    path = Path(path)
    if not path.exists():
        return {"success": False, "error": "File not found"}
    
    with open(path, "r", encoding="utf-8") as f:
        lines = list(f)
    
    result = scan_env_file(path)
    group = result.get("switch_groups", {}).get(key)
    if not group:
        return {"success": False, "error": f"Key '{key}' is not a switch group in {path}"}
    
    target_lines = [e for e in group["options"] if e["value"] == target_value]
    if not target_lines:
        return {"success": False, "error": f"No option with value '{target_value}' for key '{key}'"}
    
    changes = []
    for entry in group["options"]:
        idx = entry["line_index"]
        raw = lines[idx].rstrip("\n").rstrip("\r")
        
        if entry["value"] == target_value:
            if entry["commented"]:
                new_line = raw.lstrip("#").lstrip(" ") + "\n"
                lines[idx] = new_line
                changes.append({"line": idx, "action": "uncommented", "value": target_value})
        else:
            if not entry["commented"]:
                new_line = "# " + raw.lstrip("#").lstrip(" ") + "\n"
                lines[idx] = new_line
                changes.append({"line": idx, "action": "commented_out", "value": entry["value"]})
    
    if not changes:
        return {"success": True, "message": "Already set", "changes": []}
    
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    
    return {
        "success": True,
        "file": str(path),
        "key": key,
        "active_value": target_value,
        "changes": changes,
    }


def format_scan_result(result: dict) -> str:
    """Pretty-print scan results."""
    lines = []
    groups = result.get("switch_groups", {})
    singles = result.get("single_vars", [])
    
    lines.append(f"File: {result['file']} ({result['total_lines']} lines)")
    lines.append(f"  {len(groups)} switch groups, {len(singles)} single vars")
    lines.append("")
    
    for key, group in sorted(groups.items()):
        desc = group.get("description", [])
        if desc:
            lines.append(f"  # {' | '.join(desc[:3])}")
        lines.append(f"  {key}:")
        for o in group["options"]:
            marker = ">" if o["active"] else " "
            comment = f"  # {o['comment']}" if o.get("comment") else ""
            lines.append(f"    {marker} {o['value']}{comment}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  uv run python env_scanner.py scan <path/to/.env>")
        print("  uv run python env_scanner.py switch <path/to/.env> <KEY> <value>")
        print("  uv run python env_scanner.py fmt <path/to/.env>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "scan":
        path = sys.argv[2]
        result = scan_env_file(path)
        print(format_scan_result(result))
        print("--- JSON ---")
        clean = _clean_for_json(result)
        print(json.dumps(clean, indent=2, ensure_ascii=False))
    
    elif cmd == "switch":
        if len(sys.argv) < 5:
            print("Usage: uv run python env_scanner.py switch <path> <KEY> <value>")
            sys.exit(1)
        path, key, value = sys.argv[2], sys.argv[3], sys.argv[4]
        result = switch_env_option(path, key, value)
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _clean_for_json(result: dict) -> dict:
    """Clean up result for JSON display."""
    return {
        "file": result["file"],
        "switch_groups": {
            k: {
                "key": v["key"],
                "description": v.get("description", []),
                "options": [
                    {
                        "value": o["value"],
                        "active": o["active"],
                        "line": o["line_index"],
                        "comment": o.get("comment", ""),
                    }
                    for o in v["options"]
                ],
                "has_active": v["has_active"],
            }
            for k, v in result["switch_groups"].items()
        },
        "single_var_count": len(result["single_vars"]),
    }


if __name__ == "__main__":
    main()
