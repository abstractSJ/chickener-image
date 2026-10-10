#!/usr/bin/env python3
"""Generate or edit images through the configured OpenAI-compatible Images API."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Sequence
from urllib.parse import urlparse
from urllib.request import urlopen

try:
    from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, OpenAIError
except ImportError as exc:
    raise SystemExit(
        "The 'openai' package is required. Install it with: python -m pip install openai"
    ) from exc


DEFAULT_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_OUTPUT_DIR = Path("output") / "imagegen"
MAX_IMAGES = 4
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_DOWNLOADED_IMAGE_BYTES = 20 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUPPORTED_INPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
OPERATIONS = ("generate", "edit", "batch", "reference")
DEFAULT_CONFIG = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "secrets" / "chickener-image.json"
# Skill-local config enables one-file deployment: drop config.json next to
# SKILL.md and no per-user secrets directory is needed.
SKILL_LOCAL_CONFIG = Path(__file__).resolve().parent.parent / "config.json"


@dataclass(frozen=True)
class JobResult:
    """The result for one input or one multi-image operation."""

    input_path: Path | None
    output_paths: tuple[Path, ...]
    error: str | None = None


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def load_config(config_path: Path) -> tuple[str, str]:
    """Load and validate the configured API base URL and key."""
    candidates = [SKILL_LOCAL_CONFIG]
    if config_path != SKILL_LOCAL_CONFIG:
        candidates.append(config_path)
    config: Any = None
    chosen_path = candidates[-1]
    for candidate in candidates:
        if candidate.exists():
            chosen_path = candidate
            break
    try:
        config = json.loads(chosen_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        searched = " or ".join(str(path) for path in candidates)
        raise RuntimeError(f"Image API configuration was not found: {searched}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Image API configuration is not valid JSON: {chosen_path}") from exc

    if not isinstance(config, dict):
        raise RuntimeError(f"Image API configuration must be a JSON object: {chosen_path}")
    base_url = os.environ.get("CHICKENER_IMAGE_API_BASE", str(config.get("api_base", ""))).strip().rstrip("/")
    api_key = os.environ.get("CHICKENER_IMAGE_API_KEY", str(config.get("api_key", ""))).strip()
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError("Image API base URL must start with http:// or https://")
    if not api_key:
        raise RuntimeError("Image API key is missing from the local configuration or environment")
    return base_url, api_key


def resolve_operation(inputs: Sequence[Path], operation: str | None) -> str:
    """Resolve only unambiguous legacy defaults and validate explicit operations."""
    if operation is None:
        if not inputs:
            return "generate"
        if len(inputs) == 1:
            return "edit"
        raise ValueError("multiple input images require an explicit operation: batch or reference")
    if operation not in OPERATIONS:
        raise ValueError(f"unsupported operation: {operation}")
    if operation == "generate" and inputs:
        raise ValueError("generate operation does not accept input images")
    if operation == "edit" and len(inputs) != 1:
        raise ValueError("edit operation requires exactly one input image")
    if operation in ("batch", "reference") and not inputs:
        raise ValueError(f"{operation} operation requires at least one input image")
    return operation


def _image_signature(data: bytes) -> bool:
    return (
        data.startswith(PNG_SIGNATURE)
        or data.startswith(b"\xff\xd8\xff")
        or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def validate_inputs(inputs: Sequence[Path]) -> None:
    """Validate input count, type, size, and basic image signatures before requests."""
    if len(inputs) > MAX_IMAGES:
        raise ValueError(f"at most {MAX_IMAGES} input images are supported")
    seen: set[Path] = set()
    for path in inputs:
        path = Path(path)
        if path in seen:
            raise ValueError(f"duplicate input image: {path}")
        seen.add(path)
        if not path.exists():
            raise ValueError(f"input image was not found: {path}")
        if not path.is_file():
            raise ValueError(f"input path is not a file: {path}")
        if path.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
            raise ValueError(f"unsupported input image format: {path}")
        size = path.stat().st_size
        if size == 0:
            raise ValueError(f"input image is empty: {path}")
        if size > MAX_INPUT_BYTES:
            raise ValueError(f"input image is too large: {path}")
        with path.open("rb") as handle:
            if not _image_signature(handle.read(12)):
                raise ValueError(f"input image has an unsupported or invalid format: {path}")


def _with_cwd(path: Path, cwd: Path) -> Path:
    return path if path.is_absolute() else cwd / path


def _next_available(path: Path, reserved: set[Path]) -> Path:
    candidate = path
    index = 2
    while candidate.exists() or candidate in reserved:
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        index += 1
    return candidate


def _default_name(operation: str, input_path: Path | None = None) -> str:
    if operation == "batch" and input_path is not None:
        return f"{input_path.stem}-edited.png"
    if operation == "edit" and input_path is not None:
        return f"{input_path.stem}-edited.png"
    return "imagegen.png"


def build_output_paths(
    operation: str,
    inputs: Sequence[Path],
    out_paths: Sequence[Path],
    out_dir: Path | None,
    *,
    cwd: Path | None = None,
) -> list[Path]:
    """Plan output paths without creating or overwriting any files."""
    cwd = Path.cwd() if cwd is None else Path(cwd)
    if out_paths and out_dir is not None:
        raise ValueError("--out and --out-dir are mutually exclusive")
    if len(out_paths) > MAX_IMAGES:
        raise ValueError(f"at most {MAX_IMAGES} output images are supported")

    if out_paths:
        planned = [_with_cwd(Path(path), cwd) for path in out_paths]
        if any(path.suffix.lower() != ".png" for path in planned):
            raise ValueError("all output files must use the .png extension")
    else:
        directory = _with_cwd(Path(out_dir), cwd) if out_dir is not None else cwd / DEFAULT_OUTPUT_DIR
        count = len(inputs) if operation == "batch" else 1
        reserved: set[Path] = set()
        planned = []
        for index in range(count):
            source = inputs[index] if operation == "batch" else None
            candidate = directory / _default_name(operation, source)
            if index and operation != "batch":
                candidate = directory / f"imagegen-{index + 1}.png"
            candidate = _next_available(candidate, reserved)
            planned.append(candidate)
            reserved.add(candidate)

    if operation == "generate" and inputs:
        raise ValueError("generate operation does not accept input images")
    if operation == "edit" and len(planned) != 1:
        raise ValueError("edit operation requires exactly one output")
    if operation == "batch" and len(planned) != len(inputs):
        raise ValueError("batch input and output counts must be the same")
    if len(planned) > MAX_IMAGES:
        raise ValueError(f"at most {MAX_IMAGES} output images are supported")
    return planned


def validate_outputs(outputs: Sequence[Path], force: bool) -> None:
    """Reject duplicate or explicitly conflicting output paths before requests."""
    normalized = [Path(path).absolute() for path in outputs]
    if len(set(normalized)) != len(normalized):
        raise ValueError("output paths must not contain duplicates")
    for path in normalized:
        if path.is_dir():
            raise ValueError(f"output path is a directory: {path}")
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"output directory is not usable: {path.parent}")
    if not force:
        existing = next((path for path in normalized if path.exists()), None)
        if existing is not None:
            raise ValueError(f"output already exists: {existing}. Use --force to overwrite it.")


def _redact(message: str, api_key: str) -> str:
    return message.replace(api_key, "[REDACTED]") if api_key else message


def request_image(
    base_url: str,
    api_key: str,
    operation: str,
    prompt: str,
    input_paths: Sequence[Path],
    output_count: int,
    size: str,
    quality: str,
    model: str,
) -> Any:
    """Send one explicitly selected generation, edit, or reference request."""
    payload = {
        "model": model,
        "prompt": prompt,
        "n": output_count,
        "size": size,
        "quality": quality,
        "output_format": "png",
        "background": "opaque",
    }
    try:
        with OpenAI(
            api_key=api_key,
            base_url=f"{base_url}/",
            timeout=DEFAULT_TIMEOUT_SECONDS,
            max_retries=0,
        ) as client:
            if operation == "generate":
                return client.images.generate(**payload)
            if operation not in ("edit", "reference"):
                raise ValueError(f"unsupported request operation: {operation}")
            with ExitStack() as stack:
                handles = [stack.enter_context(path.open("rb")) for path in input_paths]
                payload["image"] = handles[0] if operation == "edit" else handles
                return client.images.edit(**payload)
    except APIStatusError as exc:
        body = str(getattr(getattr(exc, "response", None), "text", ""))[:2000]
        message = body or str(exc)
        status_code = getattr(exc, "status_code", None)
        raise RuntimeError(
            _redact(f"Image API returned HTTP {status_code or 'error'}: {message}", api_key)
        ) from exc
    except APITimeoutError as exc:
        raise RuntimeError("Image API request timed out") from exc
    except APIConnectionError as exc:
        raise RuntimeError(
            f"Image API connection failed: {_redact(str(exc), api_key)}"
        ) from exc
    except OpenAIError as exc:
        raise RuntimeError(
            f"Image API request failed: {_redact(str(exc), api_key)}"
        ) from exc


def _download_image(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Image API returned an invalid image URL")
    chunks: list[bytes] = []
    total = 0
    try:
        with urlopen(url, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOADED_IMAGE_BYTES:
                    raise ValueError("Image API image URL response is too large")
                chunks.append(chunk)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Image API image URL could not be downloaded") from exc
    return b"".join(chunks)


def _validate_output_image(image: bytes) -> bytes:
    if not image:
        raise ValueError("Image API returned an empty image")
    if not image.startswith(PNG_SIGNATURE):
        raise ValueError("Image API returned invalid PNG image data")
    return image


def extract_image_bytes(response: Any, index: int = 0) -> bytes:
    """Extract one PNG image from a Base64 or URL response."""
    data = _value(response, "data")
    if not isinstance(data, list) or index < 0 or index >= len(data):
        raise ValueError("Image API response did not contain image data")
    item = data[index]
    encoded = _value(item, "b64_json")
    if isinstance(encoded, str) and encoded:
        try:
            image = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("Image API returned invalid base64 image data") from exc
        return _validate_output_image(image)
    url = _value(item, "url")
    if isinstance(url, str) and url:
        return _validate_output_image(_download_image(url))
    raise ValueError("Image API response did not contain b64_json or url output")


def request_image_output(
    base_url: str,
    api_key: str,
    operation: str,
    prompt: str,
    input_paths: Sequence[Path],
    size: str,
    quality: str,
    model: str,
) -> bytes:
    """Request and validate one image without automatic retries."""
    response = request_image(
        base_url, api_key, operation, prompt, input_paths, 1, size, quality, model
    )
    return extract_image_bytes(response)


def _write_temporary_image(image: bytes, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}-", suffix=".tmp", dir=output_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        handle = os.fdopen(descriptor, "wb")
    except Exception:
        os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise
    try:
        handle.write(image)
        handle.flush()
        os.fsync(handle.fileno())
    except Exception:
        try:
            handle.close()
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise
    handle.close()
    return temporary_path


def write_images_atomically(
    images: Sequence[bytes], output_paths: Sequence[Path], force: bool
) -> None:
    """Stage and commit a set of images, rolling back on a commit failure."""
    if len(images) != len(output_paths):
        raise ValueError("image and output counts must be the same")
    validated_images = [_validate_output_image(image) for image in images]
    paths = [Path(path) for path in output_paths]
    for path in paths:
        if path.exists() and path.is_dir():
            raise ValueError(f"output path is a directory: {path}")
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"output directory is not usable: {path.parent}")

    if not force:
        existing = next((path for path in paths if path.exists()), None)
        if existing is not None:
            raise ValueError(f"output already exists: {existing}. Use --force to overwrite it.")

    temporary_paths: list[Path] = []
    backup_paths: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for image, output_path in zip(validated_images, paths):
            temporary_paths.append(_write_temporary_image(image, output_path))
        if force:
            for output_path in paths:
                if output_path.exists():
                    descriptor, backup_name = tempfile.mkstemp(
                        prefix=f".{output_path.stem}-", suffix=".bak", dir=output_path.parent
                    )
                    os.close(descriptor)
                    backup_path = Path(backup_name)
                    backup_paths[output_path] = backup_path
                    shutil.copyfile(output_path, backup_path)
        for temporary_path, output_path in zip(temporary_paths, paths):
            if output_path.exists() and not force:
                raise ValueError(f"output already exists: {output_path}. Use --force to overwrite it.")
            os.replace(temporary_path, output_path)
            committed.append(output_path)
    except Exception:
        for output_path in reversed(committed):
            backup_path = backup_paths.get(output_path)
            try:
                if backup_path is not None and backup_path.exists():
                    os.replace(backup_path, output_path)
                    backup_paths.pop(output_path, None)
                else:
                    output_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)
        for backup_path in backup_paths.values():
            backup_path.unlink(missing_ok=True)


def write_image(image: bytes, output_path: Path, force: bool) -> None:
    """Write one image through the atomic multi-image path."""
    write_images_atomically([image], [Path(output_path)], force)


def _execution_error(exc: Exception) -> str:
    """Explain that a failed provider request may already have been charged."""
    return (
        f"{exc}; the provider may have processed and charged this request, "
        "so it was not retried automatically"
    )


def execute_plan(
    operation: str,
    prompt: str,
    inputs: Sequence[Path],
    outputs: Sequence[Path],
    base_url: str,
    api_key: str,
    model: str,
    size: str,
    quality: str,
    force: bool,
) -> list[JobResult]:
    """Execute an already validated plan serially without automatic retries."""
    results: list[JobResult] = []
    if operation == "batch":
        jobs = zip(inputs, outputs)
        for input_path, output_path in jobs:
            try:
                image = request_image_output(
                    base_url,
                    api_key,
                    "edit",
                    prompt,
                    [input_path],
                    size,
                    quality,
                    model,
                )
                write_image(image, output_path, force)
                results.append(JobResult(input_path, (output_path,)))
            except (OSError, RuntimeError, ValueError) as exc:
                results.append(JobResult(input_path, (output_path,), _execution_error(exc)))
        return results

    for output_path in outputs:
        try:
            image = request_image_output(
                base_url,
                api_key,
                operation,
                prompt,
                inputs,
                size,
                quality,
                model,
            )
            write_image(image, output_path, force)
            results.append(JobResult(None, (output_path,)))
        except (OSError, RuntimeError, ValueError) as exc:
            results.append(JobResult(None, (output_path,), _execution_error(exc)))
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--out", action="append", type=Path, default=[])
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--operation", choices=OPERATIONS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"), default="medium")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.prompt.strip():
        print("Error: --prompt must not be empty", file=sys.stderr)
        return 1

    cwd = Path.cwd()
    inputs = [_with_cwd(path, cwd) for path in args.input]
    try:
        operation = resolve_operation(inputs, args.operation)
        validate_inputs(inputs)
        outputs = build_output_paths(operation, inputs, args.out, args.out_dir, cwd=cwd)
        validate_outputs(outputs, args.force)
        base_url, api_key = load_config(args.config)
        results = execute_plan(
            operation,
            args.prompt.strip(),
            inputs,
            outputs,
            base_url,
            api_key,
            args.model,
            args.size,
            args.quality,
            args.force,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    failed = False
    for result in results:
        if result.error:
            failed = True
            label = f"{result.input_path}: " if result.input_path else ""
            print(f"Error: {label}{result.error}", file=sys.stderr)
            continue
        for output_path in result.output_paths:
            print(f"Wrote {output_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
