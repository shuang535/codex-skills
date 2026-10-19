"""Validate dashboard state and render the K-drive Obsidian entry page."""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dashboard_common import (
    ALLOWED_STATUSES,
    DEFAULT_STATE_FILE,
    RESEARCH_STAGES,
    TIMEZONE_NAME,
    UPDATE_CATEGORIES,
    DashboardError,
    JsonObject,
    load_json,
    require_date,
    require_list,
    require_object,
    require_string,
    resolve_inside,
    validate_wikilink,
    wikilink,
    write_atomic,
)


MAX_CURRENT_ITEMS = 3
LEGACY_MAX_UPDATE_ITEMS = 2
RECENT_UPDATE_COUNT = 2
CATEGORY_KEYS = tuple(key for key, _ in UPDATE_CATEGORIES)


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render PROJECTS.md from the generated dashboard index."
    )
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument(
        "--as-of",
        type=_parse_iso_date,
        default=datetime.now(ZoneInfo(TIMEZONE_NAME)).date(),
        help="Dashboard date in YYYY-MM-DD; defaults to today in Asia/Taipei.",
    )
    parser.add_argument("--apply", action="store_true", help="Write dashboard atomically.")
    parser.add_argument("--show", action="store_true", help="Print rendered Markdown.")
    return parser.parse_args()


def _validate_registry(
    registry: JsonObject, registry_path: Path
) -> tuple[Path, Path, list[tuple[str, str]]]:
    if registry.get("schema_version") != 2:
        raise DashboardError("registry.schema_version must be 2")
    mirror_root = Path(require_string(registry, "mirror_root", "registry"))
    if not mirror_root.is_absolute():
        mirror_root = (registry_path.parent / mirror_root).resolve()
    dashboard_path = resolve_inside(
        mirror_root,
        require_string(registry, "dashboard", "registry"),
        "registry.dashboard",
    )
    projects: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, raw in enumerate(require_list(registry, "projects", "registry")):
        context = f"registry.projects[{index}]"
        if not isinstance(raw, dict):
            raise DashboardError(f"{context} must be an object")
        project_id = require_string(raw, "id", context)
        display_name = require_string(raw, "display_name", context)
        if project_id in seen_ids or display_name in seen_names:
            raise DashboardError(f"duplicate project id or display_name: {project_id}")
        seen_ids.add(project_id)
        seen_names.add(display_name)
        projects.append((project_id, display_name))
    return mirror_root, dashboard_path, projects


def _validate_text_list(
    data: JsonObject,
    key: str,
    context: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> list[str]:
    raw_items = require_list(data, key, context)
    if len(raw_items) < minimum or (maximum is not None and len(raw_items) > maximum):
        range_label = f"{minimum}+" if maximum is None else f"{minimum}-{maximum}"
        raise DashboardError(f"{context}.{key} must contain {range_label} items")
    items: list[str] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, str) or not raw.strip() or "\n" in raw or "\r" in raw:
            raise DashboardError(f"{context}.{key}[{index}] must be a non-empty single line")
        items.append(raw.strip())
    return items


def _validate_categorized_updates(
    data: JsonObject, context: str, mirror_root: Path, updated_date: date,
    *, curated: bool = False,
) -> list[JsonObject]:
    raw_updates = require_list(data, "recent_updates", context)
    minimum = 0 if curated else 1
    if not minimum <= len(raw_updates) <= RECENT_UPDATE_COUNT:
        raise DashboardError(
            f"{context}.recent_updates must contain {minimum}-{RECENT_UPDATE_COUNT} entries"
        )
    updates: list[JsonObject] = []
    previous_date: date | None = None
    for index, raw in enumerate(raw_updates):
        update_context = f"{context}.recent_updates[{index}]"
        if not isinstance(raw, dict):
            raise DashboardError(f"{update_context} must be an object")
        update_date = require_date(raw, "date", update_context)
        if update_date > updated_date:
            raise DashboardError(f"{update_context}.date cannot exceed updated_date")
        if previous_date is not None and update_date >= previous_date:
            raise DashboardError(f"{context}.recent_updates must be newest first")
        previous_date = update_date
        source_link = validate_wikilink(
            mirror_root,
            require_string(raw, "source_link", update_context),
            f"{update_context}.source_link",
        )
        raw_categories = require_object(raw, "categories", update_context)
        if set(raw_categories) != set(CATEGORY_KEYS):
            raise DashboardError(
                f"{update_context}.categories fields must be exactly {sorted(CATEGORY_KEYS)}"
            )
        categories = {
            key: _validate_text_list(
                raw_categories, key, f"{update_context}.categories", minimum=0
            )
            for key in CATEGORY_KEYS
        }
        if not any(categories.values()):
            raise DashboardError(f"{update_context} has no substantive content")
        updates.append(
            {
                "date": update_date,
                "source_link": source_link,
                "categories": categories,
            }
        )
    if not curated and updates[0]["date"] != updated_date:
        raise DashboardError(f"{context}.updated_date must equal the newest recent update")
    return updates


def _validate_v4_updates(
    data: JsonObject, context: str, mirror_root: Path, updated_date: date
) -> list[JsonObject]:
    raw_updates = require_list(data, "recent_updates", context)
    if not 1 <= len(raw_updates) <= RECENT_UPDATE_COUNT:
        raise DashboardError(
            f"{context}.recent_updates must contain 1-{RECENT_UPDATE_COUNT} entries"
        )
    updates: list[JsonObject] = []
    previous_date: date | None = None
    for index, raw in enumerate(raw_updates):
        update_context = f"{context}.recent_updates[{index}]"
        if not isinstance(raw, dict):
            raise DashboardError(f"{update_context} must be an object")
        update_date = require_date(raw, "date", update_context)
        if previous_date is not None and update_date >= previous_date:
            raise DashboardError(f"{context}.recent_updates must be newest first")
        previous_date = update_date
        source_link = validate_wikilink(
            mirror_root,
            require_string(raw, "source_link", update_context),
            f"{update_context}.source_link",
        )
        progress = _validate_text_list(
            raw, "progress", update_context, minimum=0, maximum=LEGACY_MAX_UPDATE_ITEMS
        )
        conclusions = _validate_text_list(
            raw, "conclusions", update_context, minimum=0, maximum=LEGACY_MAX_UPDATE_ITEMS
        )
        decisions = _validate_text_list(
            raw, "decisions", update_context, minimum=0, maximum=LEGACY_MAX_UPDATE_ITEMS
        )
        if not progress and not conclusions and not decisions:
            raise DashboardError(f"{update_context} has no substantive content")
        updates.append(
            {
                "date": update_date,
                "source_link": source_link,
                "categories": {
                    "progress_results": [*progress, *conclusions],
                    "method_changes": [],
                    "decisions": decisions,
                    "deliverables": [],
                    "risks": [],
                },
            }
        )
    if updates[0]["date"] != updated_date:
        raise DashboardError(f"{context}.updated_date must equal the newest recent update")
    return updates


def _legacy_texts(raw_items: object, context: str, mirror_root: Path) -> list[str]:
    if not isinstance(raw_items, list) or len(raw_items) > LEGACY_MAX_UPDATE_ITEMS:
        raise DashboardError(
            f"{context} must contain 0-{LEGACY_MAX_UPDATE_ITEMS} items"
        )
    texts: list[str] = []
    for index, raw in enumerate(raw_items):
        item_context = f"{context}[{index}]"
        if not isinstance(raw, dict):
            raise DashboardError(f"{item_context} must be an object")
        texts.append(require_string(raw, "text", item_context))
        validate_wikilink(
            mirror_root,
            require_string(raw, "link", item_context),
            f"{item_context}.link",
        )
    return texts


def _normalize_legacy_updates(
    data: JsonObject, context: str, mirror_root: Path, updated_date: date
) -> list[JsonObject]:
    raw_updates = require_list(data, "recent_updates", context)
    if not 1 <= len(raw_updates) <= RECENT_UPDATE_COUNT:
        raise DashboardError(
            f"{context}.recent_updates must contain 1-{RECENT_UPDATE_COUNT} entries"
        )
    updates: list[JsonObject] = []
    previous_date: date | None = None
    for index, raw in enumerate(raw_updates):
        update_context = f"{context}.recent_updates[{index}]"
        if not isinstance(raw, dict):
            raise DashboardError(f"{update_context} must be an object")
        update_date = require_date(raw, "date", update_context)
        if previous_date is not None and update_date >= previous_date:
            raise DashboardError(f"{context}.recent_updates must be newest first")
        previous_date = update_date
        source_link = validate_wikilink(
            mirror_root,
            require_string(raw, "source_link", update_context),
            f"{update_context}.source_link",
        )
        progress = _validate_text_list(
            raw,
            "status_changes",
            update_context,
            minimum=0,
            maximum=LEGACY_MAX_UPDATE_ITEMS,
        )
        conclusions = _legacy_texts(
            raw.get("results"), f"{update_context}.results", mirror_root
        )
        decisions = _legacy_texts(
            raw.get("decisions"), f"{update_context}.decisions", mirror_root
        )
        if not progress and not conclusions and not decisions:
            raise DashboardError(f"{update_context} has no substantive content")
        updates.append(
            {
                "date": update_date,
                "source_link": source_link,
                "categories": {
                    "progress_results": [*progress, *conclusions],
                    "method_changes": [],
                    "decisions": decisions,
                    "deliverables": [],
                    "risks": [],
                },
            }
        )
    if updates[0]["date"] != updated_date:
        raise DashboardError(f"{context}.updated_date must equal the newest recent update")
    return updates


def _validate_links(raw: JsonObject, context: str, mirror_root: Path) -> dict[str, JsonObject]:
    raw_links = require_object(raw, "links", context)
    if set(raw_links) != {"progress", "log", "method"}:
        raise DashboardError(f"{context}.links fields must be progress, log, and method")
    links: dict[str, JsonObject] = {}
    for key in ("progress", "log", "method"):
        link_context = f"{context}.links.{key}"
        link = require_object(raw_links, key, f"{context}.links")
        target = validate_wikilink(
            mirror_root,
            require_string(link, "target", link_context),
            f"{link_context}.target",
        )
        label = require_string(link, "label", link_context)
        if any(token in label for token in ("|", "[[", "]]")):
            raise DashboardError(f"{link_context}.label contains invalid Markdown")
        links[key] = {"target": target, "label": label}
    return links


def _validate_state(
    state: JsonObject, projects: list[tuple[str, str]], mirror_root: Path
) -> dict[str, JsonObject]:
    state_version = state.get("schema_version")
    if state_version not in {3, 4, 5, 6}:
        raise DashboardError("state.schema_version must be 3, 4, 5, or 6")
    if state.get("timezone") != TIMEZONE_NAME:
        raise DashboardError(f"state.timezone must be {TIMEZONE_NAME}")
    raw_states = require_object(state, "projects", "state")
    registry_ids = {project_id for project_id, _ in projects}
    if set(raw_states) != registry_ids:
        missing = sorted(registry_ids - set(raw_states))
        extra = sorted(set(raw_states) - registry_ids)
        raise DashboardError(f"state project mismatch; missing={missing}, extra={extra}")
    states: dict[str, JsonObject] = {}
    for project_id, _ in projects:
        context = f"state.projects.{project_id}"
        raw = raw_states[project_id]
        if not isinstance(raw, dict):
            raise DashboardError(f"{context} must be an object")
        status_label = require_string(raw, "status_label", context)
        if status_label not in ALLOWED_STATUSES:
            raise DashboardError(f"{context}.status_label is not allowed: {status_label}")
        research_stage = (
            require_string(raw, "research_stage", context)
            if state_version in {4, 5, 6}
            else "未標示"
        )
        if research_stage not in RESEARCH_STAGES:
            raise DashboardError(f"{context}.research_stage is not allowed: {research_stage}")
        project_summary = require_string(raw, "project_summary", context)
        milestone = require_string(raw, "milestone", context)
        if state_version in {5, 6}:
            latest_focus = require_string(raw, "latest_focus", context)
        else:
            status_summary = require_string(raw, "status_summary", context)
            highlight_summary = require_string(raw, "highlight_summary", context)
            if len(status_summary) > 80 or "|" in status_summary:
                raise DashboardError(
                    f"{context}.status_summary must be at most 80 chars without pipe"
                )
            if len(highlight_summary) > 120:
                raise DashboardError(
                    f"{context}.highlight_summary must be at most 120 chars"
                )
            latest_focus = highlight_summary
        if len(project_summary) > 80 or "|" in project_summary:
            raise DashboardError(f"{context}.project_summary must be at most 80 chars without pipe")
        if len(milestone) > 40 or "|" in milestone:
            raise DashboardError(f"{context}.milestone must be at most 40 chars without pipe")
        if len(latest_focus) > 120 or "|" in latest_focus:
            raise DashboardError(
                f"{context}.latest_focus must be at most 120 chars without pipe"
            )
        updated_date = require_date(raw, "updated_date", context)
        current_status = _validate_text_list(
            raw, "current_status", context, minimum=1, maximum=MAX_CURRENT_ITEMS
        )
        if state_version in {5, 6}:
            updates = _validate_categorized_updates(
                raw, context, mirror_root, updated_date, curated=state_version == 6
            )
        elif state_version == 4:
            updates = _validate_v4_updates(raw, context, mirror_root, updated_date)
        else:
            updates = _normalize_legacy_updates(
                raw, context, mirror_root, updated_date
            )
        states[project_id] = {
            "status_label": status_label,
            "research_stage": research_stage,
            "milestone": milestone,
            "project_summary": project_summary,
            "latest_focus": latest_focus,
            "updated_date": updated_date,
            "current_status": current_status,
            "recent_updates": updates,
            "links": _validate_links(raw, context, mirror_root),
        }
    return states


def _callout_line(text: str = "") -> str:
    return f"> {text}" if text else ">"


def _render_update_items(lines: list[str], label: str, items: object) -> None:
    if not isinstance(items, list) or not items:
        return
    lines.extend([_callout_line(), _callout_line(f"**{label}**"), _callout_line()])
    lines.extend(_callout_line(f"- {item}") for item in items)


def _render_project_callout(display_name: str, state: JsonObject, as_of: date) -> list[str]:
    updated_date = state["updated_date"]
    if not isinstance(updated_date, date):
        raise DashboardError(f"invalid rendered date for {display_name}")
    marker = "+" if updated_date == as_of else "-"
    lines = [
        _callout_line(
            f"[!abstract]{marker} {display_name}｜{state['status_label']}／"
            f"{state['research_stage']}｜{state['milestone']}｜最後更新 {updated_date.isoformat()}"
        ),
        _callout_line(),
        _callout_line(f"**專案定位**：{state['project_summary']}"),
        _callout_line(),
        _callout_line("**目前狀態**"),
        _callout_line(),
    ]
    current_status = state["current_status"]
    if not isinstance(current_status, list):
        raise DashboardError(f"invalid current status for {display_name}")
    lines.extend(_callout_line(f"- {item}") for item in current_status)
    updates = state["recent_updates"]
    if not isinstance(updates, list):
        raise DashboardError(f"invalid recent updates for {display_name}")
    if updated_date != as_of:
        lines.extend(
            [
                _callout_line(),
                _callout_line(
                    f"**更新狀態**：截至 {updated_date.isoformat()}；"
                    f"以下保留最近 {len(updates)} 個重要更新日。"
                ),
            ]
        )
    if not updates:
        lines.extend([_callout_line(), _callout_line("尚無入選的管理重點；詳細進度請見 Progress。")])
    elif updates[0]["date"] != as_of:
        lines.extend([
            _callout_line(),
            _callout_line(f"**重點截至 {updates[0]['date'].isoformat()}**"),
        ])
    for raw_update in updates:
        if not isinstance(raw_update, dict):
            raise DashboardError(f"invalid update for {display_name}")
        update_date = raw_update["date"]
        if not isinstance(update_date, date):
            raise DashboardError(f"invalid update date for {display_name}")
        lines.extend(
            [
                _callout_line(),
                _callout_line(
                    f"**{update_date.isoformat()}**｜"
                    f"{wikilink(str(raw_update['source_link']), 'Progress 紀錄')}"
                ),
            ]
        )
        categories = raw_update.get("categories")
        if not isinstance(categories, dict):
            raise DashboardError(f"invalid update categories for {display_name}")
        for key, label in UPDATE_CATEGORIES:
            _render_update_items(lines, label, categories[key])
    links = state["links"]
    if not isinstance(links, dict):
        raise DashboardError(f"invalid document links for {display_name}")
    lines.extend(
        [
            _callout_line(),
            _callout_line("**文件入口**"),
            _callout_line(),
            _callout_line(
                "- "
                + "・".join(
                    wikilink(str(links[key]["target"]), str(links[key]["label"]))
                    for key in ("progress", "log", "method")
                )
            ),
        ]
    )
    return lines


def _table_cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", r"\|")


def _ordered_projects(
    projects: list[tuple[str, str]], states: dict[str, JsonObject]
) -> list[tuple[str, str]]:
    registry_order = {project_id: index for index, (project_id, _) in enumerate(projects)}
    return sorted(
        projects,
        key=lambda item: (
            0 if states[item[0]]["status_label"] == "進行中" else 1,
            -states[item[0]]["updated_date"].toordinal(),
            registry_order[item[0]],
        ),
    )


def _validate_table_rows(rows: list[str], expected_columns: int) -> None:
    for row in rows:
        delimiters = sum(
            1
            for index, char in enumerate(row)
            if char == "|" and (index == 0 or row[index - 1] != "\\")
        )
        if delimiters != expected_columns + 1:
            raise DashboardError(
                f"summary table row has {delimiters - 1} columns, "
                f"expected {expected_columns}: {row}"
            )


def render_dashboard(
    projects: list[tuple[str, str]], states: dict[str, JsonObject], as_of: date
) -> str:
    ordered_projects = _ordered_projects(projects, states)
    summary_rows = [
        "| 專案 | 管理狀態／研究階段 | 目前里程碑 | 最新重點 | 更新日 | 入口 |",
        "|---|---|---|---|---|---|",
    ]
    for project_id, display_name in ordered_projects:
        state = states[project_id]
        updated_date = state["updated_date"]
        links = state["links"]
        if not isinstance(updated_date, date) or not isinstance(links, dict):
            raise DashboardError(f"invalid summary state for {display_name}")
        progress = links["progress"]
        if not isinstance(progress, dict):
            raise DashboardError(f"invalid progress link for {display_name}")
        updated_label = (
            updated_date.isoformat()
            if updated_date == as_of
            else f"截至 {updated_date.isoformat()}"
        )
        summary_rows.append(
            f"| {_table_cell(display_name)} | "
            f"**{_table_cell(state['status_label'])}**／{_table_cell(state['research_stage'])} | "
            f"{_table_cell(state['milestone'])} | "
            f"{_table_cell(state['latest_focus'])} | "
            f"{updated_label} | "
            f"{wikilink(str(progress['target']), str(progress['label']), in_table=True)} |"
        )
    _validate_table_rows(summary_rows, expected_columns=6)
    lines = [
        "<!-- Generated by work-progress-tracker/scripts/render_dashboard.py. -->",
        "<!-- PROGRESS.md is the project content source; do not edit this file directly. -->",
        "",
        "# 專案進度總覽",
        "",
        f"> 最後彙整：{as_of.isoformat()}（Asia/Taipei）  ",
        "> K 槽是最新成功發布的 Obsidian 閱讀中心；專案原始 Markdown 仍是編輯來源。",
        "",
        "## 專案摘要",
        "",
        *summary_rows,
        "",
        "## 專案區塊",
        "",
    ]
    for project_id, display_name in ordered_projects:
        lines.extend(_render_project_callout(display_name, states[project_id], as_of))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    try:
        registry_path = args.registry.resolve()
        registry = load_json(registry_path)
        mirror_root, dashboard_path, projects = _validate_registry(registry, registry_path)
        state_path = args.state
        if state_path is None:
            state_file = registry.get("dashboard_state", DEFAULT_STATE_FILE)
            if not isinstance(state_file, str) or not state_file.strip():
                raise DashboardError("registry.dashboard_state must be a non-empty string")
            state_path = resolve_inside(mirror_root, state_file, "registry.dashboard_state")
        states = _validate_state(load_json(state_path.resolve()), projects, mirror_root)
        content = render_dashboard(projects, states, args.as_of)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        action = "write" if args.apply else "dry-run"
        print(f"{action}: projects={len(projects)} dashboard={dashboard_path} sha256={digest}")
        if args.show:
            print(content, end="")
        if args.apply:
            write_atomic(dashboard_path, content)
            if dashboard_path.read_text(encoding="utf-8") != content:
                raise DashboardError(f"post-write verification failed: {dashboard_path}")
            print(f"verified: {dashboard_path}")
        return 0
    except (DashboardError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
