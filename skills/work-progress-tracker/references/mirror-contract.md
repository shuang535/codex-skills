# K 槽 Obsidian 鏡像契約

## 角色

- 專案原始 Markdown 是編輯與證據來源；K 槽是最新成功發布的主要閱讀中心。
- K 槽只接受單向發布，不反向覆蓋來源。
- GitHub 保存已確認的可接續版本；K 槽無法連線不阻止地端記錄或 GitHub 提交。GitHub 與 K 槽分別回報結果，補同步見 [github-handoff.md](github-handoff.md)。
- `projects.json` 管理專案、文件 allowlist、路徑與 Dashboard 入口。
- `_dashboard_state.json` 與 `PROJECTS.md` 是可重建產物，不手動編輯。
- `_sync_manifest.json` 只記錄同步結果，不作研究規格。

## Registry

Schema v2 每個專案包含唯一 `id`、顯示名稱、舊版 fallback 用的 `project_summary`／`milestone`、`source_root`、`mirror_dir`、三個 `dashboard_links`（progress／log／method 的 target 與 label），以及 `documents` allowlist。

來源與目的地不可使用 glob 或未解析環境變數。相同來源映射到多個專案時，registry 必須明確揭露。

## 同步不變量

1. 只發布 allowlist 中的 `.md`／`.mdx`。
2. 目的地必須解析在 `mirror_root` 內。
3. 保留指定相對層級，避免連結失效。
4. SHA-256 相同不重複複製；不同才更新。
5. 複製後再次驗證 SHA-256。
6. 不刪除 registry 以外的 K 槽檔案。
7. Manifest 保存來源、目的地、角色、SHA-256 與 UTC 同步時間。

## 發布完成條件

只有同時滿足以下條件才算完成：

1. 使用者已確認的來源文件正確寫入；若是一般進度更新，已有有效預覽與明確「確認寫入」。
2. 該專案所有 allowlist 來源與 K 槽 SHA-256 一致，manifest 已更新。
3. 每個專案恰有一份 `role=progress`，且新版或相容舊版 schema 通過驗證。
4. `_dashboard_state.json` 由全部 Progress 重建並包含所有 registry 專案。
5. `PROJECTS.md` 每個專案恰有一列六欄摘要與一個 Callout，內容只來自 Progress。
6. Progress、工作紀錄、方法規格與更新來源連結都指向存在的 K 槽文件。
7. 發布後實際 state 與 dashboard SHA-256 分別等於 dry run 預期值。

任一條件失敗時保留已確認的地端更新，但狀態是「地端已記錄，K 槽發布未完成」。

## 執行順序

```powershell
python scripts/sync_project_docs.py --registry "<device-specific registry path>" --project <project-id> --apply
python scripts/build_dashboard_state.py --registry "<device-specific registry path>" --apply
python scripts/render_dashboard.py --registry "<device-specific registry path>" --apply
```

詢問狀態時只執行 dry run 或雜湊比較。若來源不同於 K 槽，分別說明已發布狀態與未發布變更。

入口缺失、K 槽無法連線或雜湊失敗時停止 K 槽發布，不猜路徑、不把部分成功描述為完整成功；保留地端與 GitHub 已完成結果。

## 跨裝置發布

- 本機 registry 是發布映射，repo 的相對文件入口才是跨裝置接續來源。另一裝置無 K 槽時回報待發布，不建立替代 K 路徑。
- 發布前核對 repo、分支、commit 與已確認來源文件；未合併的工作分支也可發布進度，但不能將原型寫成正式方法。
- 使用可連 K 槽的裝置補發布前先取得對應版本，排除來源中的未確認變更，並檢查現有鏡像差異以免用較舊或不同分支內容覆蓋較新成果。
- Dashboard 會重建所有 registry 專案。應先 dry run，檢查其他專案是否有未確認的來源變更或來源／鏡像差異；有則停止 Dashboard 發布，回報待處理，不能把其他專案的未確認狀態順帶發布。
- 回報來源版本及地端、GitHub、K 槽各自結果。重試 K 槽不用建立重複 commit；GitHub 重試也不代表 K 槽已同步。
