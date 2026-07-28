# Whole-document quality workflow

## Candidate generation

Treat the source Markdown as immutable. Assemble the complete translation in memory, then write one candidate file under `.md2zh_tools/intermediate/`. Preserve the source encoding, line endings, indentation, and existing structure. Do not use line-number maps or source-anchor replacement plans.

## Full validation pass

Run the validator once across the complete candidate:

```powershell
& "<python>" "<skill-directory>/scripts/markdown_qa.py" "<source.md>" "<candidate.md>" --report "<qa.json>"
```

The validator must complete every check before any correction begins. It compares formulas, link destinations, image paths, code blocks, heading levels, table structure, and other protected Markdown data. Its JSON report records:

- `failure_count`: total hard failures;
- `errors`: the complete grouped hard-failure list;
- `warning_count`: total warnings;
- `warnings`: the complete warning list.

Do not modify the candidate while validation is running. Do not stop after the first failure.

## Required user decision after failure

When `failure_count` is greater than zero:

1. Report the total failure count, failure categories, and available locations or first-difference positions.
2. Do not repair the candidate or change a script yet.
3. Ask the user to choose one strategy:
   - **Optimize and rerun:** improve the translation or validation script as appropriate, discard the current candidate, and regenerate it from the immutable source.
   - **Codex repairs:** allow Codex to repair the complete reported failure list individually in the candidate, followed by another full validation pass.
4. Proceed only after the user chooses. Never infer the choice from the failure type.

If the user chooses Codex repairs, use the already collected complete error list; do not alternate between discovering one error and repairing one error. After the approved repairs, rerun the entire validator and report the new complete count.

## Semantic review and publication

When there are no hard failures, review every warning. For a short document, compare every translated block with the source. For a long document, review at minimum the introduction, final section, one complete paragraph under every level-1 heading, every table, prose around formulas and figures, the reference section, and every warned passage.

Also scan for omissions, duplicated prose, inconsistent terminology, altered certainty, untranslated English prose, and unnatural Chinese. Publish `<stem>_zh.md` only after automated and semantic checks pass.
