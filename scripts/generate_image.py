#!/usr/bin/env python3
"""Generate one image through the configured OpenAI-compatible Images API."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
from typing import Any

try:
    from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, OpenAIError
except ImportError as exc:
    raise SystemExit(
        "The 'openai' package is required. Install it with: python -m pip install openai"
    ) from exc


DEFAULT_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_CONFIG = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "secrets" / "chickener-image.json"


def load_config(config_path: Path) -> tuple[str, str]:
    """Load and validate the configured API base URL and key."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Image API configuration was not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Image API configuration is not valid JSON: {config_path}") from exc

    base_url = os.environ.get("CHICKENER_IMAGE_API_BASE", str(config.get("api_base", ""))).strip().rstrip("/")
    api_key = os.environ.get("CHICKENER_IMAGE_API_KEY", str(config.get("api_key", ""))).strip()
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError("Image API base URL must start with http:// or https://")
    if not api_key:
        raise RuntimeError("Image API key is missing from the local configuration or environment")
    return base_url, api_key


def request_image(base_url: str, api_key: str, payload: dict[str, Any]) -> Any:
    """Request one image through the official OpenAI SDK compatibility layer."""

    try:
        with OpenAI(
            api_key=api_key,
            base_url=f"{base_url}/",
            timeout=DEFAULT_TIMEOUT_SECONDS,
            max_retries=0,
        ) as client:
            return client.images.generate(**payload)
    except APIStatusError as exc:
        body = exc.response.text[:2000].replace(api_key, "[REDACTED]")
        raise RuntimeError(f"Image API returned HTTP {exc.status_code}: {body}") from exc
    except APITimeoutError as exc:
        raise RuntimeError("Image API request timed out") from exc
    except APIConnectionError as exc:
        raise RuntimeError(f"Image API connection failed: {exc}") from exc
    except OpenAIError as exc:
        raise RuntimeError(f"Image API request failed: {exc}") from exc


def write_image(response: Any, output_path: Path, force: bool) -> None:
    """Decode the SDK response and write a PNG without accidental replacement."""

    data = getattr(response, "data", None)
    if not isinstance(data, list) or not data:
        raise RuntimeError("Image API response did not contain image data")
    encoded = getattr(data[0], "b64_json", None)
    if not isinstance(encoded, str) or not encoded:
        raise RuntimeError("Image API response did not contain b64_json output")
    if output_path.exists() and not force:
        raise RuntimeError(f"Output already exists: {output_path}. Use --force to overwrite it.")
    try:
        image = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError("Image API returned invalid base64 image data") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"), default="medium")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    output_path = Path(args.out)
    if output_path.suffix.lower() != ".png":
        raise SystemExit("--out must use a .png filename")
    if not args.prompt.strip():
        raise SystemExit("--prompt must not be empty")

    try:
        # Fail before a potentially billable request when replacement was not authorized.
        if output_path.exists() and not args.force:
            raise RuntimeError(f"Output already exists: {output_path}. Use --force to overwrite it.")
        base_url, api_key = load_config(args.config)
        response = request_image(
            base_url,
            api_key,
            {
                "model": args.model,
                "prompt": args.prompt.strip(),
                "n": 1,
                "size": args.size,
                "quality": args.quality,
                "output_format": "png",
            },
        )
        write_image(response, output_path, args.force)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
