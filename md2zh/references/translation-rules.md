# Translation rules

Read the complete document before translating it.

## Preserve existing Markdown

Keep these items unchanged:

- fenced code blocks and inline code, including comments inside code;
- LaTeX formulas inside `$...$`, `$$...$$`, `\(...\)`, and `\[...\]`;
- link destinations, image paths, raw URLs, and autolinks;
- citation anchors, reference identifiers and definitions;
- HTML tags and attributes, entities, escape sequences, and `{{...}}` template syntax;
- heading levels, indentation, list nesting, blockquote depth, table delimiter rows, and source line endings.

Translate paragraph text, headings, list text, blockquotes, table-cell prose, link labels, and image alt text. Preserve each protected item exactly, but allow natural Chinese word order within the same prose block when all protected items remain present.

If the source contains `> 原文链接:`, preserve it and add one short translation note immediately below it.

## Translation quality

- Preserve meaning, scope, tone, logical relations, and certainty. Do not add, omit, summarize, or editorialize.
- Use established Chinese technical terms and keep recurring terminology consistent.
- Prefer natural Chinese over literal English word order.
- Keep personal names, product names, commands, identifiers, variables, bibliographic metadata, DOI, ISBN, URLs, and citation keys accurate.
- Preserve cited work titles in their source language in formal reference lists unless the document consistently uses an established Chinese title.
- For long documents, maintain a small task-local glossary rather than repeatedly revising already translated prose.

## Tables

Preserve the number and order of rows and cells, the outer-pipe style, alignment delimiters, and leading or trailing cell whitespace. Translate only cell prose. Do not split on pipes inside code, formulas, HTML attributes, or link/image targets.
