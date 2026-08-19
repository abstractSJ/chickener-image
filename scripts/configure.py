#!/usr/bin/env python3
"""Configure Chickener Image credentials in the current user's Codex home."""

from __future__ import annotations

import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import sys
from typing import Any


DEFAULT_CONFIG = (
    Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    / "secrets"
    / "chickener-image.json"
)


def read_config(config_path: Path) -> dict[str, Any]:
    """Read an existing configuration without exposing its values."""

    if not config_path.exists():
        return {}
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Existing configuration is unreadable: {config_path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Existing configuration must be a JSON object: {config_path}")
    return value


def effective_settings(config: dict[str, Any]) -> tuple[str, str]:
    """Resolve environment overrides and stored configuration values."""

    base_url = os.environ.get(
        "CHICKENER_IMAGE_API_BASE", str(config.get("api_base", ""))
    ).strip().rstrip("/")
    api_key = os.environ.get(
        "CHICKENER_IMAGE_API_KEY", str(config.get("api_key", ""))
    ).strip()
    return base_url, api_key


def validate_settings(base_url: str, api_key: str) -> None:
    """Validate required settings without making a network request."""

    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError("API base URL must start with http:// or https://")
    if not api_key:
        raise RuntimeError("API key is missing")


def write_config(config_path: Path, base_url: str, api_key: str) -> None:
    """Write credentials outside the skill directory with restrictive permissions."""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_base": base_url, "api_key": api_key}
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        # POSIX permissions prevent other local users from reading the API key.
        config_path.chmod(0o600)


def configure(config_path: Path) -> None:
    """Prompt locally for settings while keeping API key input hidden."""

    existing = read_config(config_path)
    old_base_url = str(existing.get("api_base", "")).strip().rstrip("/")
    old_api_key = str(existing.get("api_key", "")).strip()

    base_prompt = "API base URL"
    if old_base_url:
        base_prompt += " (leave blank to keep the existing value)"
    entered_base_url = input(f"{base_prompt}: ").strip().rstrip("/")
    base_url = entered_base_url or old_base_url

    key_prompt = "API key (input hidden)"
    if old_api_key:
        key_prompt += " (leave blank to keep the existing value)"
    entered_api_key = getpass(f"{key_prompt}: ").strip()
    api_key = entered_api_key or old_api_key

    validate_settings(base_url, api_key)
    write_config(config_path, base_url, api_key)
    print(f"Configuration saved to {config_path}")
    print("Credential values were not displayed.")


def check(config_path: Path) -> None:
    """Check effective configuration without printing sensitive values."""

    config = read_config(config_path)
    base_url, api_key = effective_settings(config)
    validate_settings(base_url, api_key)
    print(f"Configuration is valid: {config_path}")
    print("Credential values were not displayed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Override the configuration path (primarily for testing or advanced setups).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate effective configuration without displaying credential values.",
    )
    args = parser.parse_args()

    try:
        if args.check:
            check(args.config)
        else:
            configure(args.config)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
