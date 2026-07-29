---
name: md2zh
description: Translate English Markdown files into natural Simplified Chinese with Codex while losslessly preserving code, LaTeX, links, citations, Markdown syntax, and every non-translated source byte. Use only when the user explicitly invokes $md2zh or asks to use the md2zh skill on a .md file.
---

# Markdown to Chinese

Translate the requested `.md` file into Simplified Chinese and write `<stem>_zh.md` beside it. Never overwrite the source. If the intended output already exists, stop and ask whether to overwrite it or use another name.

## Contract

Assume the source Markdown is correct. Do not validate, repair, normalize, reflow, or reserialize it.

Let the current Codex translate only protected, model-facing text blocks. Let `scripts/md2zh_pipeline.py` keep fine-grained byte ranges internally, restore protected source slices, and verify deterministic rendering. Never let a model edit the complete Markdown file directly.

Read [references/translation-rules.md](references/translation-rules.md) before translating.

## First-run configuration

1. Resolve the source path and project root. Use the workspace root when clear; otherwise use the source directory.
2. Inspect `{project-root}/.md2zh_tools/config.json` without invoking Python. On the first run, ask one combined question for:
   - whether `user` or `codex` decides content in unrecognized extension syntax; and
   - whether Python uses an explicit interpreter path or deterministic `auto` discovery. Recommend `auto`.
3. If an older config has `ambiguous_content_decider` but no `python` object, ask only for the Python choice and retain the decider.
4. Resolve one Python 3.8+ interpreter and use it for every pipeline command in this task:
   - `explicit`: probe only the supplied absolute path; stop if missing, unusable, or too old.
   - `auto`: try project `.venv`, project `venv`, `python`, `python3`, `py -3`, then the current known interpreter. Skip unusable or pre-3.8 candidates.
   - Probe by reporting both `sys.version_info` and `sys.executable`; use the reported absolute executable afterward.
5. Persist both choices with one applicable command:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" configure "<project-root>" --decider user --python-mode auto
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" configure "<project-root>" --decider codex --python-mode explicit --python-path "<absolute-python-path>"
   ```

The pipeline rejects later stages run with a different interpreter.

## Extract and plan

1. Keep the source read-only. Create one unique direct child such as `{project-root}/.md2zh_tools/intermediate/<task-id>/`. Store state, packet, decisions, glossary, merged translations, and candidate in that task directory; use its `run/` child as `<run-directory>`. Do not place unrelated files there.
2. Extract internal protected spans and a model-facing block packet:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" extract "<source.md>" --state "<state.json>" --blocks "<blocks.json>" --project-root "<project-root>"
   ```

   Internal spans are reconstruction metadata, not model tasks. The packet normally groups a long document into roughly 10–20 heading-aware blocks. Do not expose or translate the internal state file.
3. Review every `ambiguous_region` before translation:
   - `user`: present the grouped list once and collect translate/protect decisions.
   - `codex`: decide from the complete region, section, and neighboring visible context; select only exact suggested substrings and give a concise reason.
4. Record one structured decision batch:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" record-decisions "<state.json>" "<decisions.json>"
   ```

   Accepted, rejected, and retried Codex decisions are appended under `.md2zh_tools/decision_logs/*.jsonl`. Preserve those logs after completion.
5. Create or resume the block run:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" plan-blocks "<state.json>" "<run-directory>"
   ```

   The manifest records each block's input, output, accepted result, source hash, status, and attempt count. Re-running this command preserves accepted blocks when the extraction plan is unchanged.

## Translate with the current Codex

1. Read every `*.input.txt` once before writing translations. Build one task-local glossary for recurring or accuracy-critical terms, then retain it for every block.
2. Use the current Codex session as the translator. Do not launch nested Codex CLI jobs, child agents, or independent model sessions by default. They lose shared context and add startup, authorization, and duplicated-reasoning overhead.
3. Translate one complete block surface at a time:
   - keep every `@@MD2ZH:SEG:block-....:....@@` line unchanged and in order;
   - translate only the content line after each segment line;
   - keep every `@@MD2ZH:PROTECT:...@@` marker exactly once;
   - do not add commentary, JSON wrappers, code fences, or extra lines.
4. Write translation text directly as UTF-8 to the block's declared `*.output.txt`. Never transport translation text through PowerShell/Bash pipelines, `Add-Content`, heredocs, or here-strings. Pipeline commands may still be run from the shell.
5. Validate the first block immediately before translating the rest:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" validate-block "<state.json>" "<manifest.json>" block-0001
   ```

   This is an encoding and contract gate. Continue only after it passes.
6. Translate and validate the remaining blocks in source order. A failure changes only that block's manifest entry. Correct only the reported block; the initial attempt plus two correction rounds are allowed. Never restart accepted blocks or rerun the whole document for one failure.

## Merge, review, and publish

1. For ambiguity decisions marked `translate`, create a small extra translations map using `<region-id>:<zero-based-span-index>` keys. Do not add entries for protected regions.
2. Merge accepted blocks only after every block passes:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" merge-blocks "<state.json>" "<manifest.json>" "<translations.json>"
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" merge-blocks "<state.json>" "<manifest.json>" "<translations.json>" --extra-translations "<extra.json>"
   ```

   Run only the applicable form. The pipeline recreates the internal ID map; Codex does not produce the large JSON mapping.
3. Render and verify one task-local candidate:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" render "<state.json>" "<translations.json>" "<candidate.md>"
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" verify "<state.json>" "<translations.json>" "<candidate.md>"
   ```

   Use `--allow-overwrite` only when replacing this task's own candidate or after the user explicitly authorizes replacing an existing final output.
4. Review the complete visible translation for omissions, duplicated prose, altered meaning or certainty, terminology drift, untranslated English prose, and unnatural Chinese. Correct only affected block outputs, then revalidate each intentional revision with `validate-block ... --replace-accepted`. A rejected revision leaves the prior accepted result intact. Remerge, rerender, and reverify.
5. Render deterministically to the final path and verify it once. If the default output already exists, do not choose silently between it and a new file.
6. After final verification and semantic review pass, remove only this completed task directory:

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" cleanup-run "<manifest.json>"
   ```

   The command requires the exact `<task-id>/run/manifest.json` layout and all blocks accepted, then removes only `<task-id>/`. Preserve `.md2zh_tools/config.json`, all decision logs, unrelated data, the source, translations not owned by this task, and the final file.

## Translation engine

Use Codex for translation and ambiguity decisions. Do not send document content to an external machine-translation service unless the user explicitly requests it. Optional terminology research may use the network, but network failure must not block translation.

## Completion report

Report the final output path, block count, resumed/retired block counts, deterministic verification result, semantic review scope, ambiguity decider, Python mode/path/version, persistent decision-log path, external services used, and cleanup result.
