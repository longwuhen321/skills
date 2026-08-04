# Translation rules

## Content boundary

Translate reader-visible natural language in:

- ATX and Setext heading text;
- paragraphs, list-item prose, blockquotes, and table-cell prose;
- text inside emphasis and ordinary inline HTML elements;
- inline-link labels and image alt text;
- footnote prose and prose surrounding citations.

Keep these source items unchanged:

- fenced and indented code blocks, inline code, and code-like HTML elements;
- LaTeX inside `$...$`, `$$...$$`, `\(...\)`, and `\[...\]`;
- link destinations, image paths, raw URLs, autolinks, reference identifiers, citation keys, and footnote identifiers;
- Markdown markers, indentation, hard-break whitespace, blank lines, and line endings;
- YAML frontmatter, HTML tags and attributes, comments, entities, escapes, and template syntax;
- formal bibliography titles and metadata.

Reference-style shortcut labels are also identifiers, so keep them unchanged. Translate full/collapsed reference-link labels only when their identifiers remain separately protected.

The pipeline represents protected source with ASCII `@@MD2ZH:PROTECT:...@@` markers. Keep every supplied marker exactly once. Markers may move with natural Chinese word order when doing so does not split formatting pairs. Never invent, edit, duplicate, or omit a marker.

The model-facing input is a small set of complete translation blocks, not hundreds of JSON mapping entries. Each `@@MD2ZH:SEG:block-....:....@@` line identifies the position of the following single-line text segment. Preserve every segment line exactly and in order. Translate the content lines only; do not add wrappers, commentary, blank lines, or physical line breaks.

## Ambiguous content

Read `.md2zh_tools/config.json` to determine whether the user or the AI assistant decides ambiguous content. A translate decision must select exact source substrings inside the pipeline's suggested payload; it never authorizes rewriting an entire unknown construct.

For AI-assistant decisions, use the complete supplied section and neighboring context. Record a concise reason. Let the pipeline persist all accepted, rejected, and retried decisions in `.md2zh_tools/decision_logs/*.jsonl` for later diagnosis and rule improvement.

## Translation quality

- Preserve meaning, scope, tone, logical relations, and certainty. Do not add, omit, summarize, or editorialize.
- Prefer natural Simplified Chinese over literal English word order.
- Use established Chinese technical terms and keep recurring terminology consistent across sections.
- Preserve personal names, product names, commands, identifiers, variables, bibliographic metadata, DOI, ISBN, URLs, and citation keys accurately.
- Read all blocks once, establish the document context and shared glossary, then translate blocks in source order. Never treat a content line as context-free just because the safety pipeline stores it separately.
- Keep formal cited-work titles in their source language unless the document consistently uses an established Chinese title.
- Translate table cells independently without changing their surrounding pipes or whitespace.

## Semantic review

Review all translated blocks for omissions, duplication, mistranslation, altered certainty, terminology drift, untranslated English prose, and unnatural Chinese. For long documents, review every heading, every table, every ambiguity decision, prose around formulas and figures, the introduction, the final section, and at least one complete paragraph under every level-1 heading.
