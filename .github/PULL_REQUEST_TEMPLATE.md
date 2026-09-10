## 這個 PR 改了什麼 / What this changes

<!-- 一兩句話就好。有對應的 issue 請附上連結。 -->
<!-- One or two sentences. Link an issue if there is one. -->

## 怎麼測的 / How it was tested

<!-- 例：在測試伺服器跑過機器人，/points top 翻頁正常 -->
<!-- e.g. "ran the bot on a scratch server, /points top paginates correctly" -->

## 檢查清單 / Checklist

- [ ] `python -m compileall -q -x '(^|/)venv/' .` 通過 / passes
- [ ] `ruff check .` 通過 / passes
- [ ] 沒有提交機密或執行期狀態 / no secrets or runtime state committed
      (`config.yaml`, `api_key/`, `private/`, `json/points.json`,
      `json/queues.json`, `json/fb_watch.json`, `logs/`, `cogs_local/`)
- [ ] 沒有硬編頻道 / 身分組 / guild ID 或主機名稱，新設定已加進 `config.example.yaml`
      / no hardcoded IDs or hostnames; new settings added to `config.example.yaml`
- [ ] 指令或安裝步驟有變的話，兩份 README 都更新了
      / both READMEs updated if commands or setup steps changed
