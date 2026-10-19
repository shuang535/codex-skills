"""Build the K-drive dashboard index from legacy or callout PROGRESS files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dashboard_common import (
    ALLOWED_STATUSES,
    DEFAULT_STATE_FILE,
    RESEARCH_STAGES,
    TIMEZONE_NAME,
    UPDATE_CATEGORIES,
    DashboardError,
    JsonObject,
    load_json,
    require_list,
    require_string,
    resolve_inside,
    validate_wikilink,
    write_atomic,
)


METADATA_PATTERN = re.compile(
    r"^- \*\*(專案定位|管理狀態|研究階段|目前里程碑|最新摘要|最後更新|狀態|證據|摘要)\*\*[：:]\s*(.+)$"
)
DATE_HEADING_PATTERN = re.compile(r"^### (\d{4}-\d{2}-\d{2})$")
CALLOUT_PATTERN = re.compile(r"^> \[!summary\]([+-]) (\d{4}-\d{2}-\d{2})$")
CALLOUT_ANY_SECTION_PATTERN = re.compile(r"^> \*\*(.+)\*\*$")
CALLOUT_BULLET_PATTERN = re.compile(r"^> - (.+)$")
LEGACY_RESULT_PATTERN = re.compile(r"^- `([^`]+)`[：:]\s*(.+)$")
MAX_CURRENT_ITEMS = 3
RECENT_UPDATE_COUNT = 2
CATEGORY_KEYS = tuple(key for key, _ in UPDATE_CATEGORIES)
DASHBOARD_INCLUDE = "<!-- dashboard:include -->"
DASHBOARD_EXPLICIT = "<!-- dashboard:explicit -->"


@dataclass(frozen=True)
class Document:
    """One registry document mapping."""

    source: str
    destination: str
    role: str


@dataclass(frozen=True)
class Project:
    """Registry data needed to build one dashboard entry."""

    project_id: str
    project_summary: str
    milestone: str
    source_root: Path
    documents: tuple[Document, ...]
    dashboard_links: dict[str, dict[str, str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build _dashboard_state.json from project PROGRESS files."
    )
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write state atomically.")
    parser.add_argument("--show", action="store_true", help="Print generated JSON.")
    return parser.parse_args()


def _parse_document(raw: object, context: str) -> Document:
    if not isinstance(raw, dict):
        raise DashboardError(f"{context} must be an object")
    return Document(
        source=require_string(raw, "source", context),
        destination=require_string(raw, "destination", context),
        role=require_string(raw, "role", context),
    )


def _parse_dashboard_links(raw: object, context: str) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        raise DashboardError(f"{context} must be an object")
    required = {"progress", "log", "method"}
    if set(raw) != required:
        raise DashboardError(f"{context} fields must be exactly {sorted(required)}")
    links: dict[str, dict[str, str]] = {}
    for key in required:
        entry = raw[key]
        entry_context = f"{context}.{key}"
        if not isinstance(entry, dict):
            raise DashboardError(f"{entry_context} must be an object")
        target = require_string(entry, "target", entry_context)
        label = require_string(entry, "label", entry_context)
        if any(token in label for token in ("|", "[[", "]]")):
            raise DashboardError(f"{entry_context}.label contains invalid Markdown")
        links[key] = {"target": target, "label": label}
    return links


def _parse_projects(registry: JsonObject) -> tuple[Path, list[Project]]:
    if registry.get("schema_version") != 2:
        raise DashboardError("registry.schema_version must be 2")
    mirror_root = Path(require_string(registry, "mirror_root", "registry"))
    projects: list[Project] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(require_list(registry, "projects", "registry")):
        context = f"registry.projects[{index}]"
        if not isinstance(raw, dict):
            raise DashboardError(f"{context} must be an object")
        project_id = require_string(raw, "id", context)
        if project_id in seen_ids:
            raise DashboardError(f"duplicate project id: {project_id}")
        seen_ids.add(project_id)
        project_summary = require_string(raw, "project_summary", context)
        milestone = require_string(raw, "milestone", context)
        if len(project_summary) > 80 or "|" in project_summary:
            raise DashboardError(f"{context}.project_summary must be at most 80 chars without pipe")
        if len(milestone) > 40 or "|" in milestone:
            raise DashboardError(f"{context}.milestone must be at most 40 chars without pipe")
        documents = tuple(
            _parse_document(item, f"{context}.documents[{item_index}]")
            for item_index, item in enumerate(require_list(raw, "documents", context))
        )
        projects.append(
            Project(
                project_id=project_id,
                project_summary=project_summary,
                milestone=milestone,
                source_root=Path(require_string(raw, "source_root", context)),
                documents=documents,
                dashboard_links=_parse_dashboard_links(
                    raw.get("dashboard_links"), f"{context}.dashboard_links"
                ),
            )
        )
    return mirror_root, projects


def _find_section(lines: list[str], heading: str, path: Path) -> list[str]:
    matches = [index for index, line in enumerate(lines) if line.strip() == heading]
    if len(matches) != 1:
        raise DashboardError(f"{path} must contain exactly one {heading!r} section")
    start = matches[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def _has_section(lines: list[str], heading: str) -> bool:
    return sum(line.strip() == heading for line in lines) == 1


def _parse_metadata(lines: list[str], path: Path, *, modern: bool) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in lines:
        match = METADATA_PATTERN.fullmatch(line.strip())
        if match:
            metadata[match.group(1)] = match.group(2).strip()
    required = (
        {"專案定位", "管理狀態", "研究階段", "目前里程碑", "最新摘要", "最後更新"}
        if modern
        else {"狀態", "證據", "摘要", "最後更新"}
    )
    if set(metadata) != required:
        raise DashboardError(f"{path} project summary fields must be exactly {sorted(required)}")
    status_key = "管理狀態" if modern else "狀態"
    if metadata[status_key] not in ALLOWED_STATUSES:
        raise DashboardError(f"{path} has unsupported status: {metadata[status_key]}")
    if modern:
        if metadata["研究階段"] not in RESEARCH_STAGES - {"未標示"}:
            raise DashboardError(f"{path} has unsupported research stage: {metadata['研究階段']}")
        limits = {"專案定位": 80, "目前里程碑": 40, "最新摘要": 80}
    else:
        limits = {"摘要": 40}
    for key, maximum in limits.items():
        if len(metadata[key]) > maximum or "|" in metadata[key]:
            raise DashboardError(f"{path} {key} must be at most {maximum} chars without pipe")
    try:
        date.fromisoformat(metadata["最後更新"])
    except ValueError as exc:
        raise DashboardError(f"{path} last update must use YYYY-MM-DD") from exc
    return metadata


def _parse_bullets(lines: list[str], context: str, maximum: int) -> list[str]:
    items = [line.strip()[2:].strip() for line in lines if line.strip().startswith("- ")]
    if not 1 <= len(items) <= maximum:
        raise DashboardError(f"{context} must contain 1-{maximum} bullets")
    if any(not item for item in items):
        raise DashboardError(f"{context} contains an empty bullet")
    return items


def _validate_workflow(lines: list[str], path: Path) -> None:
    table_rows = [line for line in lines if line.strip().startswith("|")]
    if len(table_rows) < 3:
        raise DashboardError(f"{path} workflow section must contain a non-empty Markdown table")


def _validate_dates(records: list[dict[str, object]], path: Path) -> None:
    if not records:
        raise DashboardError(f"{path} must contain at least one dated progress entry")
    raw_dates = [str(record["date"]) for record in records]
    if len(raw_dates) != len(set(raw_dates)):
        raise DashboardError(f"{path} contains duplicate progress dates")
    if raw_dates != sorted(raw_dates, reverse=True):
        raise DashboardError(f"{path} progress dates must be newest first")
    for raw_date in raw_dates:
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise DashboardError(f"invalid progress date in {path}: {raw_date}") from exc


def _parse_callout_history(lines: list[str], path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    subsection: str | None = None
    mapping = {
        "重點進度": "progress_results",
        "研究結論／成果": "progress_results",
        "已確認決策": "decisions",
        "進度與成果": "progress_results",
        "方法／規格變更": "method_changes",
        "已確認重大決策": "decisions",
        "交付物": "deliverables",
        "風險／限制": "risks",
        "詳細紀錄": "details",
    }
    for raw_line in lines:
        line = raw_line.strip()
        date_match = DATE_HEADING_PATTERN.fullmatch(line)
        if date_match:
            if current is not None:
                records.append(current)
            current = {
                "date": date_match.group(1),
                "marker": None,
                "categories": {key: [] for key in CATEGORY_KEYS},
                "details": [],
            }
            subsection = None
            continue
        callout_match = CALLOUT_PATTERN.fullmatch(line)
        if callout_match:
            if current is None or callout_match.group(2) != current["date"]:
                raise DashboardError(f"{path} callout date must match its date heading")
            if current["marker"] is not None:
                raise DashboardError(f"{path} has duplicate callout for {current['date']}")
            current["marker"] = callout_match.group(1)
            subsection = None
            continue
        section_match = CALLOUT_ANY_SECTION_PATTERN.fullmatch(line)
        if section_match:
            if current is None or current["marker"] is None:
                raise DashboardError(f"{path} has a callout section outside a dated callout")
            label = section_match.group(1)
            if label not in mapping:
                raise DashboardError(f"{path} has unsupported callout subsection: {label}")
            subsection = mapping[label]
            continue
        bullet_match = CALLOUT_BULLET_PATTERN.fullmatch(line)
        if bullet_match:
            if current is None or subsection is None:
                raise DashboardError(f"{path} has a bullet outside a callout subsection")
            if subsection == "details":
                items = current["details"]
            else:
                categories = current["categories"]
                if not isinstance(categories, dict):
                    raise DashboardError(f"invalid callout parser state for {path}")
                items = categories[subsection]
            if not isinstance(items, list):
                raise DashboardError(f"invalid callout parser state for {path}")
            item = bullet_match.group(1).strip()
            if not item:
                raise DashboardError(f"{path} contains an empty callout bullet")
            items.append(item)
    if current is not None:
        records.append(current)
    _validate_dates(records, path)
    for index, record in enumerate(records):
        expected_marker = "+" if index == 0 else "-"
        if record["marker"] != expected_marker:
            raise DashboardError(
                f"{path} {record['date']} must use [!summary]{expected_marker}"
            )
        categories = record["categories"]
        if not isinstance(categories, dict) or set(categories) != set(CATEGORY_KEYS):
            raise DashboardError(f"{path} {record['date']} has invalid categories")
        if any(
            not isinstance(categories[key], list)
            or any(not isinstance(item, str) or not item for item in categories[key])
            for key in CATEGORY_KEYS
        ):
            raise DashboardError(f"{path} {record['date']} has invalid category items")
        details = record["details"]
        if not isinstance(details, list):
            raise DashboardError(f"{path} {record['date']} has invalid detail links")
        if not any(categories[key] for key in CATEGORY_KEYS):
            raise DashboardError(f"{path} {record['date']} has no substantive progress")
    return records


def _parse_legacy_history(lines: list[str], path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    subsection: str | None = None
    subsection_label: str | None = None
    mapping = {
        "狀態變化": "progress_results",
        "重大決策": "decisions",
        "成果": "progress_results",
    }
    for raw_line in lines:
        line = raw_line.strip()
        date_match = DATE_HEADING_PATTERN.fullmatch(line)
        if date_match:
            if current is not None:
                records.append(current)
            current = {
                "date": date_match.group(1),
                "categories": {key: [] for key in CATEGORY_KEYS},
            }
            subsection = None
            subsection_label = None
            continue
        if line.startswith("#### "):
            label = line[5:].strip()
            if label not in mapping:
                raise DashboardError(f"{path} has unsupported history subsection: {label}")
            subsection = mapping[label]
            subsection_label = label
            continue
        if not line.startswith("- "):
            continue
        if current is None or subsection is None:
            raise DashboardError(f"{path} has a history bullet outside a dated subsection")
        text = line[2:].strip()
        if subsection_label == "成果":
            result_match = LEGACY_RESULT_PATTERN.fullmatch(line)
            if not result_match:
                raise DashboardError(f"{path} legacy results must use '- `Evidence`: text'")
            text = result_match.group(2).strip()
        categories = current["categories"]
        if not isinstance(categories, dict):
            raise DashboardError(f"invalid legacy parser state for {path}")
        items = categories[subsection]
        if not isinstance(items, list):
            raise DashboardError(f"invalid legacy parser state for {path}")
        items.append(text)
    if current is not None:
        records.append(current)
    _validate_dates(records, path)
    for record in records:
        categories = record["categories"]
        if not isinstance(categories, dict) or set(categories) != set(CATEGORY_KEYS):
            raise DashboardError(f"{path} {record['date']} has invalid legacy categories")
        if not any(categories[key] for key in CATEGORY_KEYS):
            raise DashboardError(f"{path} {record['date']} has no recorded progress")
    return records


def _find_document(project: Project, role: str) -> Document:
    matches = [document for document in project.documents if document.role == role]
    if len(matches) != 1:
        raise DashboardError(
            f"project {project.project_id} must have exactly one document with role={role}"
        )
    return matches[0]


def _build_recent_updates(
    records: list[dict[str, object]], progress_link: str, *, explicit_selection: bool = False
) -> list[JsonObject]:
    updates: list[JsonObject] = []
    # A document-level declaration distinguishes intentional zero selections from legacy input.
    explicit_selection = explicit_selection or any(
        DASHBOARD_INCLUDE in item
        for record in records
        for key in CATEGORY_KEYS
        for item in record["categories"][key]
    )
    for record in records:
        categories = {
            key: [
                item.replace(DASHBOARD_INCLUDE, "").strip()
                for item in record["categories"][key]
                if not explicit_selection or DASHBOARD_INCLUDE in item
            ]
            for key in CATEGORY_KEYS
        }
        if any(not item for items in categories.values() for item in items):
            raise DashboardError("dashboard selection must contain substantive text")
        if not any(categories.values()):
            continue
        record_date = str(record["date"])
        updates.append(
            {
                "date": record_date,
                "source_link": f"{progress_link}#{record_date}",
                "categories": categories,
            }
        )
        if len(updates) == RECENT_UPDATE_COUNT:
            break
    return updates


def _build_project_state(project: Project, mirror_root: Path) -> JsonObject:
    progress_document = _find_document(project, "progress")
    progress_path = resolve_inside(
        project.source_root, progress_document.source, f"{project.project_id}.progress"
    )
    try:
        lines = progress_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise DashboardError(f"progress file not found: {progress_path}") from exc

    modern = _has_section(lines, "## 每日進度")
    legacy = _has_section(lines, "## 重大進度歷史")
    if modern == legacy:
        raise DashboardError(
            f"{progress_path} must use exactly one of '每日進度' or '重大進度歷史'"
        )
    metadata = _parse_metadata(
        _find_section(lines, "## 專案摘要", progress_path), progress_path, modern=modern
    )
    current_status = _parse_bullets(
        _find_section(lines, "## 目前狀態", progress_path),
        f"{progress_path} current status",
        MAX_CURRENT_ITEMS,
    )
    if modern:
        _validate_workflow(_find_section(lines, "## 作業流程與規劃", progress_path), progress_path)
        records = _parse_callout_history(
            _find_section(lines, "## 每日進度", progress_path), progress_path
        )
        status_label = metadata["管理狀態"]
        research_stage = metadata["研究階段"]
        project_summary = metadata["專案定位"]
        milestone = metadata["目前里程碑"]
        status_summary = metadata["最新摘要"]
    else:
        records = _parse_legacy_history(
            _find_section(lines, "## 重大進度歷史", progress_path), progress_path
        )
        status_label = metadata["狀態"]
        research_stage = "未標示"
        project_summary = project.project_summary
        milestone = project.milestone
        status_summary = metadata["摘要"]
    if records[0]["date"] != metadata["最後更新"]:
        raise DashboardError(f"{progress_path} latest progress date must equal last update")

    links = {key: project.dashboard_links[key] for key in ("progress", "log", "method")}
    for key, entry in links.items():
        validate_wikilink(
            mirror_root, entry["target"], f"{project.project_id}.links.{key}.target"
        )
    explicit_selection = any(line.strip() == DASHBOARD_EXPLICIT for line in lines)
    recent_updates = _build_recent_updates(
        records, links["progress"]["target"], explicit_selection=explicit_selection
    )
    return {
        "status_label": status_label,
        "research_stage": research_stage,
        "milestone": milestone,
        "project_summary": project_summary,
        "latest_focus": status_summary,
        "updated_date": metadata["最後更新"],
        "current_status": current_status,
        "recent_updates": recent_updates,
        "links": links,
    }


def main() -> int:
    args = parse_args()
    try:
        registry_path = args.registry.resolve()
        registry = load_json(registry_path)
        mirror_root, projects = _parse_projects(registry)
        state_file = registry.get("dashboard_state", DEFAULT_STATE_FILE)
        if not isinstance(state_file, str) or not state_file.strip():
            raise DashboardError("registry.dashboard_state must be a non-empty string")
        output_path = args.output or resolve_inside(
            mirror_root, state_file, "registry.dashboard_state"
        )
        state: JsonObject = {
            "schema_version": 6,
            "timezone": TIMEZONE_NAME,
            "projects": {
                project.project_id: _build_project_state(project, mirror_root)
                for project in projects
            },
        }
        content = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        action = "write" if args.apply else "dry-run"
        print(f"{action}: projects={len(projects)} state={output_path} sha256={digest}")
        if args.show:
            print(content, end="")
        if args.apply:
            write_atomic(output_path, content)
            if output_path.read_text(encoding="utf-8") != content:
                raise DashboardError(f"post-write verification failed: {output_path}")
            print(f"verified: {output_path}")
        return 0
    except (DashboardError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
