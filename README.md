# Codex Skills

可攜的 Codex 工作流程技能，目前包含 [work-progress-tracker](skills/work-progress-tracker/SKILL.md)。

## Work Progress Tracker

以三層 Markdown 記錄研究與實作進度，支援跨裝置交接、GitHub 工作分支同步，以及共享磁碟上的 Obsidian 儀表板。

- 第三層：完整 Work Log 與已確認方法規格。
- 第二層：PROGRESS 專案流程、目前狀態、每日 Callout 與交接。
- 第一層：PROJECTS 管理摘要，保留最近兩個有入選重點的日期。

## 安裝至另一台電腦

可直接要求 Codex：

> 從 https://github.com/shuang535/codex-skills 安裝 skills/work-progress-tracker。

也可 clone 後，將完整的 skills/work-progress-tracker 資料夾複製到該裝置的 Codex skills 目錄（通常為使用者目錄下的 .codex/skills）。不要只複製 SKILL.md；references、scripts、agents 與 tests 也需保留。已有同名 skill 時先備份並檢查本機設定，再更新。

安裝後開啟新對話並引用 $work-progress-tracker。兩台裝置應使用相同版本；clone repo 不會自動更新已安裝的 skill。

## 使用

1. 「接續專案」：檢查分支與地端變更，取得遠端更新並讀取交接。
2. 「紀錄今天進度」：整理研究與實作成果，預覽文件及 GitHub 提交範圍。
3. 「確認寫入」：更新文件、提交並推送工作分支，再發布共享磁碟。

研究與實作可並行；改變正式研究方法前仍需確認。收工不會自動合併主要分支。

## 裝置設定

公開版本不包含公司路徑、專案資料、個人認證或實際 registry。各裝置使用既有 Git 身分與認證；遠端 repo 必須具備存取權限。

共享磁碟發布需提供本機的 projects.json（registry schema v2），定義來源根目錄、文件 allowlist、鏡像根目錄與文件入口。格式規則見 [鏡像契約](skills/work-progress-tracker/references/mirror-contract.md)。此設定不要提交到公開 repo。

三個發布指令均明確傳入 --registry。未設定共享磁碟的裝置仍可透過 GitHub 接續；共享磁碟發布標示為待處理。

## 驗證

已以 Python 3.13 驗證。發布工具使用 Python 標準函式庫；Windows 若缺少 IANA 時區資料，安裝 tzdata。

```powershell
python -m unittest discover -s skills/work-progress-tracker/tests -v
```
