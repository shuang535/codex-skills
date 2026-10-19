---
name: work-progress-tracker
description: 以三層 Markdown 記錄研究與實作進度，支援跨裝置接續、預覽確認、GitHub 工作分支同步與 K 槽 Obsidian 儀表板發布。詢問狀態時唯讀；紀錄進度先預覽，確認寫入後提交已確認範圍並同步。
---

# 工作進度追蹤

把詳細研究與實作紀錄提煉成專案作業中心，再產生跨專案摘要。GitHub 保存可接續的版本，K 槽保存最新成功發布的閱讀版本。

## 三層文件

詳見 [references/document-model.md](references/document-model.md)，沿用既有文件，不建立第四層或重複 README。

1. **第三層 Work Log／方法規格**：問題、假設、方法、結果、解讀、原型與交接依據。Work Log 可保存明確標示的待確認方案；正式規格只保存已確認方法。格式見 [references/work-log-schema.md](references/work-log-schema.md)。
2. **第二層 PROGRESS**：專案摘要、流程規劃、目前研究／實作狀態、交接事項及每日 Callout。格式見 [references/progress-schema.md](references/progress-schema.md)。
3. **第一層 PROJECTS**：只從 Progress 取得管理摘要、目前狀態與已選取的分類重點。不得直接讀取日誌補寫結論。

## 操作模式

- **詢問進度／狀態**：唯讀本機、遠端已知狀態與必要文件；不 fetch、pull、寫入或發布。
- **接續專案**：依 [references/github-handoff.md](references/github-handoff.md) 檢查 repo、分支、身分與地端變更，fetch；地端乾淨且能快轉時更新目前工作分支。讀取 Progress 與必要 Log，說明研究／實作狀態、待確認事項及可接續工作。接續不授權開始新的研究或實作任務。
- **紀錄今天進度／收工**：蒐集實際證據、形成草稿與提交清單，先預覽。
- **確認寫入**：依有效預覽更新文件，commit、push 已確認的工作分支，再發布 K 槽；不逐步重問。使用者明確指定的其他授權表達依當次指示處理。
- **只要求重新同步**：只重試指定目標；不新增研究內容、建立新 commit 或擴張先前提交範圍。
- **沒有實質進度**：不新增空白日期；有相關成果待同步時可預覽提交範圍，不虛構研究成果。

## 蒐集、確認與預覽

讀 [references/preview-workflow.md](references/preview-workflow.md)。

1. 對照本次 thread、實際修改、notebook 結果、圖表、產出物及既有第三層文件，不只依賴對話聲稱完成。
2. 先整理第三層草稿。研究與實作可並行，暫定方法可用於原型，但不得被寫成正式採用。
3. 對改變資料口徑、訊號、回測假設、權重、交易規則或正式規格的決策，列出原因與影響並先由使用者確認。一般實作細節直接處理。
4. 一般紀錄使用精簡預覽；重大決策／方法變更提供完整受影響內容與驗收方式。兩種預覽都列出文件變動、PROJECTS 呈現、GitHub repo／分支／檔案／既有未推送提交與 K 槽範圍。
5. 確認寫入後執行；若來源、研究結果、提交範圍或遠端基準已改變，重新檢查受影響預覽。

## 寫入與交接

1. 更新第三層：同一天合併日誌，保存研究問題、證據、差異、待確認事項及接手方式；正式方法變更才更新規格。
2. 更新第二層：調整目前狀態與必要流程規劃，合併當日 Callout；以研究／實作／交接前綴呈現有內容的項目。細部 Todo 與執行步驟留在第三層。
3. 只把影響研究解讀、里程碑、可重現性或交付的實作成果向上提煉，不以測試數量或重構數量作研究成果。
4. 在 Progress 標示管理重點，由程式重建第一層；不手動修改 PROJECTS 或 state。

## Dashboard 選取

- 摘要表固定六欄：專案、管理狀態／研究階段、目前里程碑、最新重點、更新日、入口。最新重點直接取 Progress 的最新摘要。
- Progress 在每日進度段落加入 `<!-- dashboard:explicit -->` 啟用明確選取；入選項目末尾加 `<!-- dashboard:include -->`。標記由 agent 隨預覽提出，不要求使用者手工維護。
- 只帶入入選項目，保留最近兩個有入選內容的日期；無入選項目仍顯示摘要、目前狀態與入口。無今日重點時標示實際重點日期。
- 五種分類依序為進度與成果、方法／規格變更、已確認重大決策、交付物、風險／限制。只顯示非空分類、不限制分類點數，同一事項不重複。
- 目前狀態最多三點；今天有更新的專案 Callout 展開，其餘收合。進行中專案優先，再按最後更新日排序。
- 舊文件仍可讀取，遷移與篩選細節見 progress-schema；索引相容性見 [references/dashboard-schema.md](references/dashboard-schema.md)。

## GitHub 與 K 槽發布

GitHub 操作與跨裝置規則見 [references/github-handoff.md](references/github-handoff.md)。提交本次確認的文件、程式碼、notebook 與必要成果，推送工作分支；收工不自動合併主要分支。各裝置使用既有 Git 身分與權限，不寫死帳號。

K 槽或共享磁碟發布見 [references/mirror-contract.md](references/mirror-contract.md)。由各發布裝置提供 registry 路徑，使用其中的 mirror_root、dashboard 與文件映射：

```text
Registry: <device-specific path>/projects.json
Dashboard: <registry mirror_root>/<registry dashboard>
```

K 槽 registry 用於發布，不是跨裝置接續的必要條件。repo 內保留相對文件入口；本機絕對路徑與 K 槽映射由發布裝置管理。找不到發布設定時不猜路徑，回報 K 槽待發布。

分別回報地端、GitHub 與 K 槽結果。GitHub 成功須核對遠端分支 commit；K 槽成功須通過來源／鏡像雜湊、state schema、六欄摘要、入口與產出雜湊驗證。任一目標失敗保留已確認成果，列出重試目標，不宣稱全部完成。

## 邊界

- 不因紀錄進度重構、搬移或刪除專案文件。
- 不從 K 槽反向覆蓋來源，不刪除 K 槽額外檔案。
- 不發布憑證、大型原始資料、非必要敏感輸出；notebook 輸出亦需檢查。
- 不寫入名稱含「暫存」「交換區」「自動清除」的專案發布路徑。
