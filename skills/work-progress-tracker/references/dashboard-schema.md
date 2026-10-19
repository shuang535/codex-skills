# Dashboard 發布索引

`_dashboard_state.json` 是 `build_dashboard_state.py` 從所有 Progress 產生的可重建索引，不手動修改。

## Schema v6

```json
{
  "schema_version": 6,
  "timezone": "Asia/Taipei",
  "projects": {
    "project-id": {
      "status_label": "進行中",
      "research_stage": "策略建構",
      "milestone": "目前里程碑",
      "project_summary": "專案定位",
      "latest_focus": "最多80字的最新重點",
      "updated_date": "2026-09-23",
      "current_status": [],
      "recent_updates": [
        {
          "date": "2026-09-23",
          "source_link": "Project/PROGRESS#2026-09-23",
          "categories": {
            "progress_results": [],
            "method_changes": [],
            "decisions": [],
            "deliverables": [],
            "risks": []
          }
        }
      ],
      "links": {
        "progress": {"target": "Project/PROGRESS", "label": "Progress"},
        "log": {"target": "Project/WORKLOG", "label": "工作紀錄"},
        "method": {"target": "Project/README", "label": "研究方法"}
      }
    }
  }
}
```

分類 key 與顯示名稱固定為：

| Key | PROJECTS 標題 |
|---|---|
| `progress_results` | 進度與成果 |
| `method_changes` | 方法／規格變更 |
| `decisions` | 已確認重大決策 |
| `deliverables` | 交付物 |
| `risks` | 風險／限制 |

五個 key 固定存在，內容可以為空；Renderer 只顯示非空分類。分類內不設固定點數上限，但每項必須是非空單行文字。

`recent_updates` 保存最近零至兩個有入選重點的日期。無入選項目時為空陣列，每個存在的日期仍須有非空分類。`updated_date` 是 Progress 最後更新日，各重點日期不得晚於它，但不必等於它。`current_status` 保存一至三點目前狀態。程式碼測試證據不是 Dashboard 必要欄位。

新版 Progress 的專案定位、里程碑、研究階段與最新摘要是發布內容來源；`latest_focus` 直接使用最新摘要。Registry 的 `project_summary` 與 `milestone` 只作舊版 Progress 的相容 fallback。入口 target／label 仍由 registry 提供。

產生器驗證管理狀態、研究階段、摘要長度、日期順序、分類名稱、專案完整性、K 槽入口與表格六欄。Renderer 可讀既有 schema v3、v4、v5 state，舊版仍要求最新重點日期等於最後更新；新 builder 輸出 schema v6。舊 Progress 的選取 fallback 見 progress-schema。
