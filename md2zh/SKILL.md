---
name: md2zh
description: Translate English Markdown files into accurate, natural Simplified Chinese while preserving the existing Markdown format, code, LaTeX, link and image targets, citations, headings, and tables. Use only when the user explicitly invokes $md2zh or asks to use the md2zh skill on a .md file.
---

# Markdown to Chinese

Translate the requested English Markdown file into Simplified Chinese. Write the final result beside the source as `<stem>_zh.md`; never overwrite the source unless the user explicitly requests it.

## Core rule

Treat the source Markdown as already correctly formatted. Translate content only. Do not reformat, normalize, restructure, or "repair" the source Markdown.

## Workflow

1. Resolve the input `.md` path. Ask only when the path is missing or ambiguous.
2. Read the complete document before translating. Understand its organization, context, recurring terminology, and reference policy.
3. Read [references/translation-rules.md](references/translation-rules.md). Establish consistent translations for recurring or accuracy-critical terms.
4. Keep the source read-only. Prepare the complete translation in memory while retaining the source's Markdown structure, whitespace, indentation, and line endings.
5. After the complete translation is assembled, write one task-owned candidate under `.md2zh_tools/intermediate/`. Do not incrementally patch the source or final `_zh.md` file.
6. Follow [references/quality-workflow.md](references/quality-workflow.md) and run `scripts/markdown_qa.py` once across the entire candidate. Let every check finish before changing anything.
7. If validation finds failures, report the complete failure count and grouped failure list, then stop and ask the user to choose:
   - optimize the translation or validation script, discard the candidate, and rerun from the source; or
   - allow Codex to repair the reported failures individually.
8. Do not choose a repair strategy or modify the candidate before the user answers.
9. If there are no hard failures, review all warnings and perform the required semantic review. Publish the candidate as `<stem>_zh.md` only after the checks pass.
10. Remove only current-task temporary files after successful delivery; preserve unrelated working data.

## Translation engine

Translate with Codex itself. Do not send document text to an external machine-translation service unless the user explicitly requests it. Optional terminology research may use the network, but network failure must not block translation.

## Working files

Keep task-owned temporary data under `{project-root}/.md2zh_tools/intermediate/`, such as:

```text
<stem>.<short-source-hash>.candidate.md
<stem>.<short-source-hash>.qa.json
<stem>.<short-source-hash>.glossary.tsv
```

Do not create line-number replacement maps, source-anchor replacement plans, or incrementally repaired stage files.

## Completion report

State the final output path, automated validation result, warnings reviewed, semantic review scope, use of external services or terminology research, and whether temporary files were cleaned.
