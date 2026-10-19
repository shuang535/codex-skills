"""Synchronize allowlisted project Markdown into a read-only K-drive mirror.

The registry is the only source of project paths. The script never deletes files
from the mirror and defaults to a dry run unless ``--apply`` is provided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ALLOWED_SUFFIXES = {".md", ".mdx"}


@dataclass(frozen=True)
class DocumentConfig:
    source: str
    destination: str
    role: str


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    display_name: str
    source_root: Path
    mirror_dir: str
    documents: tuple[DocumentConfig, ...]


@dataclass(frozen=True)
class Registry:
    mirror_root: Path
    manifest_name: str
    projects: tuple[ProjectConfig, ...]


@dataclass(frozen=True)
class SyncPlanItem:
    project_id: str
    role: str
    source: Path
    destination: Path
    source_hash: str
    action: str


def _require_mapping(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{context} keys must be strings")
    return value


def _require_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
    return value


def _require_string(mapping: dict[str, object], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value


def _resolve_relative_path(root: Path, relative: str, context: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute():
        raise ValueError(f"{context} must be relative: {relative}")
    resolved_root = root.resolve(strict=False)
    resolved = (resolved_root / relative_path).resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{context} escapes its root: {relative}") from exc
    return resolved


def load_registry(path: Path) -> Registry:
    """Load and validate the project registry."""
    try:
        raw_value: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Registry is invalid JSON: {path}: {exc}") from exc

    raw = _require_mapping(raw_value, "registry")
    schema_version = raw.get("schema_version")
    if schema_version not in {1, 2}:
        raise ValueError(f"Unsupported schema_version: {schema_version!r}")

    mirror_root = Path(_require_string(raw, "mirror_root", "registry"))
    manifest_name = _require_string(raw, "manifest", "registry")
    manifest_path = Path(manifest_name)
    if manifest_path.is_absolute() or len(manifest_path.parts) != 1:
        raise ValueError("registry.manifest must be a filename inside mirror_root")

    projects: list[ProjectConfig] = []
    project_ids: set[str] = set()
    for project_index, project_value in enumerate(
        _require_list(raw.get("projects"), "registry.projects")
    ):
        context = f"registry.projects[{project_index}]"
        project = _require_mapping(project_value, context)
        project_id = _require_string(project, "id", context)
        if project_id in project_ids:
            raise ValueError(f"Duplicate project id: {project_id}")
        project_ids.add(project_id)

        documents: list[DocumentConfig] = []
        for document_index, document_value in enumerate(
            _require_list(project.get("documents"), f"{context}.documents")
        ):
            document_context = f"{context}.documents[{document_index}]"
            document = _require_mapping(document_value, document_context)
            documents.append(
                DocumentConfig(
                    source=_require_string(document, "source", document_context),
                    destination=_require_string(
                        document, "destination", document_context
                    ),
                    role=_require_string(document, "role", document_context),
                )
            )

        projects.append(
            ProjectConfig(
                project_id=project_id,
                display_name=_require_string(project, "display_name", context),
                source_root=Path(_require_string(project, "source_root", context)),
                mirror_dir=_require_string(project, "mirror_dir", context),
                documents=tuple(documents),
            )
        )

    return Registry(
        mirror_root=mirror_root,
        manifest_name=manifest_name,
        projects=tuple(projects),
    )


def calculate_sha256(path: Path) -> str:
    """Calculate a file SHA-256 without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_projects(
    registry: Registry, requested_ids: Sequence[str]
) -> tuple[ProjectConfig, ...]:
    """Select requested projects, or all projects when none are requested."""
    if not requested_ids:
        return registry.projects
    by_id = {project.project_id: project for project in registry.projects}
    unknown = sorted(set(requested_ids) - set(by_id))
    if unknown:
        raise ValueError(f"Unknown project id(s): {', '.join(unknown)}")
    return tuple(by_id[project_id] for project_id in requested_ids)


def build_sync_plan(
    registry: Registry, projects: Sequence[ProjectConfig]
) -> tuple[SyncPlanItem, ...]:
    """Validate all paths and build a complete plan before any write occurs."""
    plan: list[SyncPlanItem] = []
    destinations: set[Path] = set()

    for project in projects:
        project_destination = _resolve_relative_path(
            registry.mirror_root,
            project.mirror_dir,
            f"project {project.project_id} mirror_dir",
        )
        for document in project.documents:
            source = _resolve_relative_path(
                project.source_root,
                document.source,
                f"project {project.project_id} source",
            )
            destination = _resolve_relative_path(
                project_destination,
                document.destination,
                f"project {project.project_id} destination",
            )
            if source.suffix.lower() not in ALLOWED_SUFFIXES:
                raise ValueError(f"Source is not Markdown: {source}")
            if destination.suffix.lower() not in ALLOWED_SUFFIXES:
                raise ValueError(f"Destination is not Markdown: {destination}")
            if not source.is_file():
                raise ValueError(f"Source document not found: {source}")
            if destination in destinations:
                raise ValueError(f"Duplicate destination in sync plan: {destination}")
            destinations.add(destination)

            source_hash = calculate_sha256(source)
            if not destination.exists():
                action = "copy"
            elif not destination.is_file():
                raise ValueError(f"Destination is not a file: {destination}")
            elif calculate_sha256(destination) == source_hash:
                action = "unchanged"
            else:
                action = "update"
            plan.append(
                SyncPlanItem(
                    project_id=project.project_id,
                    role=document.role,
                    source=source,
                    destination=destination,
                    source_hash=source_hash,
                    action=action,
                )
            )
    return tuple(plan)


def _copy_and_verify(item: SyncPlanItem) -> None:
    item.destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = item.destination.with_name(f".{item.destination.name}.sync.tmp")
    try:
        shutil.copy2(item.source, temporary)
        if calculate_sha256(temporary) != item.source_hash:
            raise OSError(f"Temporary copy failed hash verification: {temporary}")
        os.replace(temporary, item.destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    if calculate_sha256(item.destination) != item.source_hash:
        raise OSError(f"Destination failed hash verification: {item.destination}")


def _load_existing_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "projects": {}}
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Existing manifest is invalid JSON: {path}") from exc
    manifest = _require_mapping(value, "manifest")
    if manifest.get("schema_version") != 1:
        raise ValueError("Existing manifest has an unsupported schema_version")
    _require_mapping(manifest.get("projects"), "manifest.projects")
    return manifest


def _write_manifest(
    registry: Registry,
    plan: Sequence[SyncPlanItem],
    selected_projects: Sequence[ProjectConfig],
) -> None:
    manifest_path = _resolve_relative_path(
        registry.mirror_root, registry.manifest_name, "registry manifest"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _load_existing_manifest(manifest_path)
    project_entries = _require_mapping(manifest.get("projects"), "manifest.projects")
    synced_at = datetime.now(timezone.utc).isoformat()

    for project in selected_projects:
        project_entries[project.project_id] = [
            {
                "source": str(item.source),
                "destination": str(item.destination),
                "role": item.role,
                "sha256": item.source_hash,
                "synced_at_utc": synced_at,
            }
            for item in plan
            if item.project_id == project.project_id
        ]
    manifest["updated_at_utc"] = synced_at

    temporary = manifest_path.with_name(f".{manifest_path.name}.sync.tmp")
    try:
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, manifest_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def execute_sync(
    registry: Registry,
    plan: Sequence[SyncPlanItem],
    projects: Sequence[ProjectConfig],
    apply_changes: bool,
) -> None:
    """Print the plan and optionally apply verified copies plus a manifest."""
    for item in plan:
        print(
            f"{item.project_id}\t{item.action}\t{item.role}\t"
            f"{item.source} -> {item.destination}"
        )
    if not apply_changes:
        print(f"DRY_RUN\tfiles={len(plan)}")
        return

    changed = 0
    for item in plan:
        if item.action != "unchanged":
            _copy_and_verify(item)
            changed += 1
        elif calculate_sha256(item.destination) != item.source_hash:
            raise OSError(f"Unchanged file failed verification: {item.destination}")
    _write_manifest(registry, plan, projects)
    print(f"SYNC_OK\tfiles={len(plan)}\tchanged={changed}\tverified={len(plan)}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize allowlisted project Markdown to the K-drive mirror."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        required=True,
        help="Device-specific registry JSON path.",
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Project id to sync; repeat for multiple projects. Omit for all.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply copies and update the manifest. Without this flag, dry-run only.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        registry = load_registry(args.registry)
        projects = select_projects(registry, args.project)
        plan = build_sync_plan(registry, projects)
        execute_sync(registry, plan, projects, args.apply)
    except (OSError, ValueError) as exc:
        print(f"ERROR\t{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
