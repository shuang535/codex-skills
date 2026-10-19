from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import build_dashboard_state as builder
import render_dashboard as renderer
from dashboard_common import DashboardError, TIMEZONE_NAME


class ProgressParserTests(unittest.TestCase):
    def test_new_callout_supports_dynamic_categories_without_item_cap(self) -> None:
        lines = [
            "### 2026-09-23",
            "> [!summary]+ 2026-09-23",
            ">",
            "> **進度與成果**",
            ">",
            "> - **資料**：第一點。",
            "> - **策略**：第二點。",
            "> - **視覺化**：第三點。",
            ">",
            "> **方法／規格變更**",
            ">",
            "> - 更新資料口徑。",
            ">",
            "> **已確認重大決策**",
            ">",
            "> - ==採用方案 A。==",
            ">",
            "> **交付物**",
            ">",
            "> - 完成報告。",
            ">",
            "> **風險／限制**",
            ">",
            "> - ==樣本期間有限。==",
            ">",
            "> **詳細紀錄**",
            ">",
            "> - [[WORKLOG#2026-09-23|當日 Work Log]]",
        ]

        records = builder._parse_callout_history(lines, Path("PROGRESS.md"))

        categories = records[0]["categories"]
        self.assertEqual(len(categories["progress_results"]), 3)
        self.assertEqual(categories["method_changes"], ["更新資料口徑。"])
        self.assertEqual(categories["decisions"], ["==採用方案 A。=="])
        self.assertEqual(categories["deliverables"], ["完成報告。"])
        self.assertEqual(categories["risks"], ["==樣本期間有限。=="])

    def test_old_callout_headings_are_normalized(self) -> None:
        lines = [
            "### 2026-09-23",
            "> [!summary]+ 2026-09-23",
            "> **重點進度**",
            "> - 完成資料整理。",
            "> **研究結論／成果**",
            "> - 策略結果穩定。",
            "> **已確認決策**",
            "> - 採用方案 A。",
        ]

        records = builder._parse_callout_history(lines, Path("PROGRESS.md"))

        categories = records[0]["categories"]
        self.assertEqual(
            categories["progress_results"],
            ["完成資料整理。", "策略結果穩定。"],
        )
        self.assertEqual(categories["decisions"], ["採用方案 A。"])

    def test_unknown_callout_category_is_rejected(self) -> None:
        lines = [
            "### 2026-09-23",
            "> [!summary]+ 2026-09-23",
            "> **自訂分類**",
            "> - 不應接受。",
        ]

        with self.assertRaisesRegex(DashboardError, "unsupported callout subsection"):
            builder._parse_callout_history(lines, Path("PROGRESS.md"))


class RendererTests(unittest.TestCase):
    @staticmethod
    def _categories() -> dict[str, list[str]]:
        return {
            "progress_results": ["第一點。", "第二點。", "第三點。"],
            "method_changes": [],
            "decisions": ["==採用方案 A。=="],
            "deliverables": ["完成報告。"],
            "risks": [],
        }

    def test_dynamic_sections_render_in_fixed_order_and_hide_empty_sections(self) -> None:
        states = {
            "demo": {
                "status_label": "進行中",
                "research_stage": "策略建構",
                "milestone": "完成方案比較",
                "project_summary": "示範專案。",
                "latest_focus": "完成三項重要研究進度。",
                "updated_date": date(2026, 9, 23),
                "current_status": ["目前狀態。"],
                "recent_updates": [
                    {
                        "date": date(2026, 9, 23),
                        "source_link": "Demo/PROGRESS#2026-09-23",
                        "categories": self._categories(),
                    }
                ],
                "links": {
                    "progress": {"target": "Demo/PROGRESS", "label": "Progress"},
                    "log": {"target": "Demo/WORKLOG", "label": "工作紀錄"},
                    "method": {"target": "Demo/README", "label": "研究方法"},
                },
            }
        }

        content = renderer.render_dashboard(
            [("demo", "Demo")], states, date(2026, 9, 24)
        )

        self.assertIn("| 最新重點 |", content)
        self.assertIn("**目前狀態**", content)
        self.assertIn("**進度與成果**", content)
        self.assertIn("- 第三點。", content)
        self.assertIn("**已確認重大決策**", content)
        self.assertIn("**交付物**", content)
        self.assertNotIn("**方法／規格變更**", content)
        self.assertNotIn("**風險／限制**", content)

    def test_v3_and_v4_states_are_normalized(self) -> None:
        common = {
            "status_label": "進行中",
            "milestone": "里程碑",
            "project_summary": "示範專案。",
            "status_summary": "目前摘要。",
            "highlight_summary": "最新重點。",
            "updated_date": "2026-09-23",
            "current_status": ["目前狀態。"],
            "links": {
                "progress": {"target": "Demo/PROGRESS", "label": "Progress"},
                "log": {"target": "Demo/WORKLOG", "label": "工作紀錄"},
                "method": {"target": "Demo/README", "label": "研究方法"},
            },
        }

        state_v4 = {
            "schema_version": 4,
            "timezone": TIMEZONE_NAME,
            "projects": {
                "demo": {
                    **common,
                    "research_stage": "策略建構",
                    "recent_updates": [
                        {
                            "date": "2026-09-23",
                            "source_link": "Demo/PROGRESS#2026-09-23",
                            "progress": ["進度。"],
                            "conclusions": ["成果。"],
                            "decisions": ["決策。"],
                        }
                    ],
                }
            },
        }
        state_v3 = {
            "schema_version": 3,
            "timezone": TIMEZONE_NAME,
            "projects": {
                "demo": {
                    **common,
                    "recent_updates": [
                        {
                            "date": "2026-09-23",
                            "source_link": "Demo/PROGRESS#2026-09-23",
                            "status_changes": ["進度。"],
                            "results": [
                                {
                                    "text": "成果。",
                                    "link": "Demo/PROGRESS#2026-09-23",
                                }
                            ],
                            "decisions": [
                                {
                                    "text": "決策。",
                                    "link": "Demo/PROGRESS#2026-09-23",
                                }
                            ],
                        }
                    ],
                }
            },
        }

        def accept_link(_root: Path, target: str, _context: str) -> str:
            return target

        with patch.object(renderer, "validate_wikilink", side_effect=accept_link):
            normalized_v4 = renderer._validate_state(
                state_v4, [("demo", "Demo")], Path(".")
            )
            self.assertEqual(
                normalized_v4["demo"]["recent_updates"][0]["categories"][
                    "progress_results"
                ],
                ["進度。", "成果。"],
            )
            normalized_v3 = renderer._validate_state(
                state_v3, [("demo", "Demo")], Path(".")
            )
            self.assertEqual(normalized_v3["demo"]["research_stage"], "未標示")
            self.assertEqual(
                normalized_v3["demo"]["recent_updates"][0]["categories"]["decisions"],
                ["決策。"],
            )


if __name__ == "__main__":
    unittest.main()
