"""Verify curated Progress selection and its rendered management summary."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_dashboard_state as builder
import render_dashboard as renderer
from dashboard_common import DashboardError, TIMEZONE_NAME


def make_record(day: str, items: list[str]) -> dict[str, object]:
    categories = {key: [] for key in builder.CATEGORY_KEYS}
    categories["progress_results"] = items
    return {"date": day, "categories": categories}


def make_state(updates: list[dict[str, object]], version: int = 6) -> dict[str, object]:
    return {
        "schema_version": version,
        "timezone": TIMEZONE_NAME,
        "projects": {
            "demo": {
                "status_label": "進行中",
                "research_stage": "策略建構",
                "milestone": "驗證原型",
                "project_summary": "研究與實作交接",
                "latest_focus": "原型待驗證",
                "updated_date": "2026-10-19",
                "current_status": ["研究已確認，實作中"],
                "recent_updates": updates,
                "links": {
                    key: {"target": f"Demo/{name}", "label": name}
                    for key, name in (
                        ("progress", "PROGRESS"), ("log", "WORKLOG"), ("method", "README")
                    )
                },
            }
        },
    }


class SelectionTests(unittest.TestCase):
    def test_selects_two_important_days_across_unselected_days(self) -> None:
        records = [
            make_record("2026-10-19", ["ordinary"]),
            make_record("2026-10-18", ["key <!-- dashboard:include -->", "private detail"]),
            make_record("2026-10-17", ["ordinary"]),
            make_record("2026-10-16", ["older <!-- dashboard:include -->"]),
            make_record("2026-10-15", ["oldest <!-- dashboard:include -->"]),
        ]
        updates = builder._build_recent_updates(records, "Demo/PROGRESS")
        self.assertEqual([entry["date"] for entry in updates], ["2026-10-18", "2026-10-16"])
        self.assertEqual(updates[0]["categories"]["progress_results"], ["key"])
        self.assertEqual(records[1]["categories"]["progress_results"][0],
                         "key <!-- dashboard:include -->")

    def test_explicit_zero_selection_does_not_fall_back(self) -> None:
        updates = builder._build_recent_updates(
            [make_record("2026-10-19", ["ordinary"])], "Demo/PROGRESS",
            explicit_selection=True,
        )
        self.assertEqual(updates, [])

    def test_legacy_without_markers_retains_two_latest_dates(self) -> None:
        records = [make_record(f"2026-10-{day}", [str(day)]) for day in (19, 18, 17)]
        updates = builder._build_recent_updates(records, "Demo/PROGRESS")
        self.assertEqual([entry["date"] for entry in updates], ["2026-10-19", "2026-10-18"])
        self.assertEqual(updates[0]["categories"]["progress_results"], ["19"])

    def test_no_item_cap_and_categories_preserved(self) -> None:
        record = make_record("2026-10-19", [f"item {i} <!-- dashboard:include -->" for i in range(5)])
        record["categories"]["risks"] = ["risk <!-- dashboard:include -->"]
        updates = builder._build_recent_updates([record], "Demo/PROGRESS")
        self.assertEqual(len(updates[0]["categories"]["progress_results"]), 5)
        self.assertEqual(updates[0]["categories"]["risks"], ["risk"])

    def test_marker_without_content_is_rejected(self) -> None:
        with self.assertRaisesRegex(DashboardError, "substantive text"):
            builder._build_recent_updates(
                [make_record("2026-10-19", ["<!-- dashboard:include -->"])], "Demo/PROGRESS"
            )


class CuratedRendererTests(unittest.TestCase):
    def validate(self, state: dict[str, object]) -> dict[str, object]:
        with patch.object(renderer, "validate_wikilink", side_effect=lambda root, target, context: target):
            return renderer._validate_state(state, [("demo", "Demo")], Path("."))

    def test_v6_older_selection_renders_its_actual_date(self) -> None:
        updates = builder._build_recent_updates(
            [make_record("2026-10-18", ["key <!-- dashboard:include -->"])], "Demo/PROGRESS"
        )
        states = self.validate(make_state(updates))
        text = renderer.render_dashboard([("demo", "Demo")], states, date(2026, 10, 19))
        self.assertIn("重點截至 2026-10-18", text)
        self.assertIn("最後更新 2026-10-19", text)
        self.assertNotIn("dashboard:include", text)
        self.assertIn("**進度與成果**", text)

    def test_v6_empty_selection_keeps_summary_and_links(self) -> None:
        states = self.validate(make_state([]))
        text = renderer.render_dashboard([("demo", "Demo")], states, date(2026, 10, 19))
        self.assertIn("尚無入選的管理重點", text)
        self.assertIn("研究已確認，實作中", text)
        self.assertIn("[[Demo/PROGRESS", text)
        self.assertNotIn("**進度與成果**", text)

    def test_future_selection_is_rejected(self) -> None:
        updates = builder._build_recent_updates(
            [make_record("2026-10-20", ["key"])], "Demo/PROGRESS"
        )
        with self.assertRaisesRegex(DashboardError, "cannot exceed"):
            self.validate(make_state(updates))

    def test_v5_keeps_previous_date_and_nonempty_requirements(self) -> None:
        updates = builder._build_recent_updates(
            [make_record("2026-10-19", ["key"])], "Demo/PROGRESS"
        )
        self.assertEqual(len(self.validate(make_state(updates, 5))["demo"]["recent_updates"]), 1)
        with self.assertRaises(DashboardError):
            self.validate(make_state([], 5))
        updates[0]["date"] = "2026-10-18"
        with self.assertRaisesRegex(DashboardError, "must equal"):
            self.validate(make_state(updates, 5))

    def test_document_declaration_reaches_builder_and_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("README", "WORKLOG"):
                (root / f"{name}.md").write_text("# Example\n", encoding="utf-8")
            (root / "PROGRESS.md").write_text(
                """## 專案摘要
- **專案定位**：示範交接
- **管理狀態**：進行中
- **研究階段**：策略建構
- **目前里程碑**：驗證原型
- **最新摘要**：原型待驗證
- **最後更新**：2026-10-19
## 作業流程與規劃
| 階段 | 目標產出 | 狀態 | 相依關係 |
|---|---|---|---|
| 研究 | 原型 | 進行中 | 無 |
## 目前狀態
- 研究與實作並行。
## 每日進度
<!-- dashboard:explicit -->
### 2026-10-19
> [!summary]+ 2026-10-19
> **進度與成果**
> - 一般檢查完成。
""", encoding="utf-8",
            )
            project = builder.Project(
                project_id="demo", project_summary="fallback", milestone="fallback",
                source_root=root,
                documents=(builder.Document(source="PROGRESS.md", destination="PROGRESS.md", role="progress"),),
                dashboard_links={
                    key: {"target": name, "label": name}
                    for key, name in (
                        ("progress", "PROGRESS"), ("log", "WORKLOG"), ("method", "README")
                    )
                },
            )
            project_state = builder._build_project_state(project, root)
            self.assertEqual(project_state["recent_updates"], [])
            state = {"schema_version": 6, "timezone": TIMEZONE_NAME, "projects": {"demo": project_state}}
            normalized = renderer._validate_state(state, [("demo", "Demo")], root)
            text = renderer.render_dashboard([("demo", "Demo")], normalized, date(2026, 10, 19))
            self.assertNotIn("一般檢查完成", text)
            self.assertIn("尚無入選的管理重點", text)


if __name__ == "__main__":
    unittest.main()
