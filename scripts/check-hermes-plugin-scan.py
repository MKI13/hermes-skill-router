#!/usr/bin/env python3
"""Fail unless the pinned Hermes plugin scanner accepts this repository."""

from __future__ import annotations

from pathlib import Path

from tools.plugin_guard import PLUGIN_SCANNER_VERSION, format_scan_report, scan_plugin

_EXPECTED_SCANNER_VERSION = "plugin-guard-v1"


def main() -> int:
    if PLUGIN_SCANNER_VERSION != _EXPECTED_SCANNER_VERSION:
        print(
            "Unsupported Hermes plugin scanner version: "
            f"{PLUGIN_SCANNER_VERSION!r} (expected {_EXPECTED_SCANNER_VERSION!r})"
        )
        return 2
    repository = Path(__file__).resolve().parents[1]
    result = scan_plugin(repository, source="hermes-skill-router-ci")
    print(format_scan_report(result))
    return 0 if result.verdict == "safe" else 1


if __name__ == "__main__":
    raise SystemExit(main())
