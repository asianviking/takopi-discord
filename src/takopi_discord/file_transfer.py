"""File transfer utilities for Discord transport."""

from __future__ import annotations

import io
import os
import shlex
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

__all__ = [
    "ZipTooLargeError",
    "default_upload_name",
    "deny_reason",
    "format_bytes",
    "normalize_relative_path",
    "parse_file_command",
    "resolve_path_within_root",
    "write_bytes_atomic",
    "zip_directory",
]

# Discord attachment size limit (25MB for non-nitro servers)
MAX_FILE_SIZE = 25 * 1024 * 1024

# Default deny patterns
DEFAULT_DENY_GLOBS = (".git/**", "*.env", ".env.*", "**/.env", "**/credentials*")


def split_command_args(text: str) -> tuple[str, ...]:
    """Split command arguments, handling quoted strings."""
    if not text.strip():
        return ()
    try:
        return tuple(shlex.split(text))
    except ValueError:
        return tuple(text.split())


def file_usage() -> str:
    """Return usage string for file command."""
    return "usage: `/file get <path>` or reply with attachment for `/file put <path>`"


def parse_file_command(args_text: str) -> tuple[str | None, str, str | None]:
    """Parse file command arguments.

    Returns: (command, path, error)
    """
    tokens = split_command_args(args_text)
    if not tokens:
        return None, "", file_usage()
    command = tokens[0].lower()
    rest = " ".join(tokens[1:]).strip()
    if command not in {"put", "get"}:
        return None, rest, file_usage()
    return command, rest, None


def normalize_relative_path(value: str) -> Path | None:
    """Normalize a relative path, rejecting unsafe paths."""
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.startswith("~"):
        return None
    path = Path(cleaned)
    if path.is_absolute():
        return None
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        return None
    if ".." in parts:
        return None
    if ".git" in parts:
        return None
    return Path(*parts)


def resolve_path_within_root(root: Path, rel_path: Path) -> Path | None:
    """Resolve a relative path within a root directory.

    Returns None if the resolved path escapes the root.
    """
    root_resolved = root.resolve(strict=False)
    target = (root / rel_path).resolve(strict=False)
    if not target.is_relative_to(root_resolved):
        return None
    return target


def deny_reason(rel_path: Path, deny_globs: Sequence[str]) -> str | None:
    """Check if a path is denied by any glob pattern.

    Returns the matching pattern if denied, None if allowed.
    """
    if ".git" in rel_path.parts:
        return ".git/**"
    posix = PurePosixPath(rel_path.as_posix())
    for pattern in deny_globs:
        if posix.match(pattern):
            return pattern
    return None


def format_bytes(value: int) -> str:
    """Format a byte count as a human-readable string."""
    size = max(0.0, float(value))
    units = ("b", "kb", "mb", "gb", "tb")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "b":
                return f"{int(size)} b"
            if size < 10:
                return f"{size:.1f} {unit}"
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{int(size)} B"


def default_upload_name(filename: str | None) -> str:
    """Generate a default upload filename."""
    name = Path(filename or "").name if filename else ""
    if not name:
        name = "upload.bin"
    return name


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    """Write bytes to a file atomically using a temp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=path.parent, prefix=".takopi-upload-"
    ) as handle:
        handle.write(payload)
        temp_name = handle.name
    Path(temp_name).replace(path)


class ZipTooLargeError(Exception):
    """Raised when a zip file exceeds the size limit."""

    pass


def zip_directory(
    root: Path,
    rel_path: Path,
    deny_globs: Sequence[str],
    *,
    max_bytes: int | None = None,
) -> bytes:
    """Zip a directory and return the bytes.

    Args:
        root: The root directory
        rel_path: Relative path to the directory to zip
        deny_globs: Glob patterns to exclude
        max_bytes: Maximum size of the zip file

    Raises:
        ZipTooLargeError: If the zip exceeds max_bytes
    """
    target = root / rel_path
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for dirpath, _, filenames in os.walk(target, followlinks=False):
            dir_path = Path(dirpath)
            for filename in filenames:
                item = dir_path / filename
                if item.is_symlink():
                    continue
                if not item.is_file():
                    continue
                rel_item = rel_path / item.relative_to(target)
                if deny_reason(rel_item, deny_globs) is not None:
                    continue
                archive.write(item, arcname=rel_item.as_posix())
                if max_bytes is not None and buffer.tell() > max_bytes:
                    raise ZipTooLargeError()
    payload = buffer.getvalue()
    if max_bytes is not None and len(payload) > max_bytes:
        raise ZipTooLargeError()
    return payload
