"""Shared validation and file helpers for dashboard publishing scripts."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path


ALLOWED_STATUSES = {"進行中", "待驗證", "待審核", "已交付", "暫停"}
RESEARCH_STAGES = {
    "假設形成",
    "資料確認",
    "策略建構",
    "回測驗證",
    "穩健性檢查",
    "正式交付",
    "持續監控",
    "未標示",
}
DEFAULT_STATE_FILE = "_dashboard_state.json"
TIMEZONE_NAME = "Asia/Taipei"
UPDATE_CATEGORIES = (
    ("progress_results", "進度與成果"),
    ("method_changes", "方法／規格變更"),
    ("decisions", "已確認重大決策"),
    ("deliverables", "交付物"),
    ("risks", "風險／限制"),
)
JsonObject = dict[str, object]


class DashboardError(ValueError):
    """Raised when dashboard inputs violate the publishing contract."""


def load_json(path: Path) -> JsonObject:
    """Load a UTF-8 JSON object."""
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DashboardError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DashboardError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise DashboardError(f"JSON root must be an object: {path}")
    return loaded


def require_object(data: JsonObject, key: str, context: str) -> JsonObject:
    """Return a required object field."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise DashboardError(f"{context}.{key} must be an object")
    return value


def require_list(data: JsonObject, key: str, context: str) -> list[object]:
    """Return a required list field."""
    value = data.get(key)
    if not isinstance(value, list):
        raise DashboardError(f"{context}.{key} must be a list")
    return value


def require_string(data: JsonObject, key: str, context: str) -> str:
    """Return a required, non-empty, single-line string field."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DashboardError(f"{context}.{key} must be a non-empty string")
    if "\n" in value or "\r" in value:
        raise DashboardError(f"{context}.{key} must be a single line")
    return value.strip()


def require_date(data: JsonObject, key: str, context: str) -> date:
    """Return a required ISO date field."""
    value = require_string(data, key, context)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DashboardError(f"{context}.{key} must use YYYY-MM-DD") from exc


def resolve_inside(root: Path, relative: str, context: str) -> Path:
    """Resolve a relative path and ensure it remains inside root."""
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise DashboardError(f"{context} must be relative: {relative}")
    root_resolved = root.resolve()
    resolved = (root_resolved / relative_path).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise DashboardError(f"{context} escapes its root: {relative}") from exc
    return resolved


def validate_wikilink(root: Path, target: str, context: str) -> str:
    """Validate a raw Obsidian target and its linked Markdown file."""
    if "[[" in target or "]]" in target or "|" in target:
        raise DashboardError(f"{context} must not contain brackets or an alias")
    file_target = target.split("#", maxsplit=1)[0].strip()
    if not file_target:
        raise DashboardError(f"{context} has no file target")
    if not file_target.casefold().endswith((".md", ".mdx")):
        file_target = f"{file_target}.md"
    linked_file = resolve_inside(root, file_target, context)
    if not linked_file.is_file():
        raise DashboardError(f"{context} points to a missing file: {linked_file}")
    return target


def write_atomic(path: Path, content: str) -> None:
    """Write UTF-8 text atomically and preserve the old file on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise DashboardError(f"failed to write {path}: {exc}") from exc


def without_markdown_suffix(path: str) -> str:
    """Return an Obsidian target without a Markdown suffix."""
    normalized = path.replace("\\", "/")
    for suffix in (".mdx", ".md"):
        if normalized.casefold().endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def wikilink(target: str, alias: str, *, in_table: bool = False) -> str:
    """Render an Obsidian wikilink, escaping its separator inside tables."""
    separator = r"\|" if in_table else "|"
    return f"[[{target}{separator}{alias}]]"
