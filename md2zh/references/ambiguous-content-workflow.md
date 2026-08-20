# 模糊内容决策工作流

## 强制读取条件

`extract` 生成的 state 含一个或多个 `ambiguous_region` 时，
**必须在记录任何决策前完整读取本文件**。没有模糊区域时不读取，也不创建空决策文件。

## 决策边界

- `ambiguous_content_decider=user`：一次性向用户展示分组列表，收集每项
  `translate` / `protect` 判决。
- `ambiguous_content_decider=ai`：依据完整 region、所属章节及相邻可见上下文判决，
  并写简短理由。
- `translate` 只授权翻译 pipeline 建议载荷中的精确源子串；不得借此重写未知结构。
- `protect` 保持整个候选载荷不变，不生成额外翻译键。

## 记录决策

`decisions.json` 必须恰好覆盖 state 中每个 region ID 一次，不得缺失、重复或包含未知 ID：

```json
{
  "decisions": [
    {
      "region_id": "unknown-0001",
      "decision": "protect",
      "reason": "保留未知指令载荷",
      "selected_spans": []
    },
    {
      "region_id": "unknown-0002",
      "decision": "translate",
      "reason": "该载荷是读者可见文字",
      "selected_spans": [
        {"source_start": 120, "source_end": 138, "text": "Exact source text"}
      ]
    }
  ]
}
```

执行：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" `
  record-decisions "<state.json>" "<decisions.json>"
```

命令会拒绝不完整或不精确的决策，并把 accepted / rejected 事件持久化到
`<skill-directory>/logs/decision_logs/*.jsonl`。

## 额外翻译

存在 accepted `translate` 决策时，命令输出的 `extra_translations_skeleton` 会列出
`unknown-xxxx:<span-index>` 键。将该对象保存为 UTF-8 `extra-translations.json`，
只把空字符串替换成对应中文：

```json
{
  "translations": {
    "unknown-0002:0": "精确源文字的中文译文"
  }
}
```

合并时追加：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" merge-blocks `
  "<state.json>" "<manifest.json>" "<translations.json>" `
  --extra-translations "<extra-translations.json>"
```

没有 accepted `translate` 决策时不得传空的额外翻译文件。pipeline 要求键集合与
accepted spans 完全一致、译文非空、无换行、无保护标记且不引入新的 Markdown 语法。

## 验收

- 每个 region 恰有一个 accepted 决策和理由。
- 每个 translate span 与 state 的精确偏移和源文本一致。
- 额外翻译键无缺失、无多余且译文非空。
- `merge-blocks`、`render` 与 `verify` 均使用同一份 accepted 决策结果。
