---
name: web2md
description: Fetch webpage content and generate Typora-compatible Markdown files with local images and LaTeX formulas. Use only when the user explicitly invokes $web2md, /web2md, or @web2md and provides a URL; do not trigger when a URL merely appears in ordinary conversation.
---

# web2md — Webpage to Markdown

Given a URL, automatically generate a `.md` file that can be opened in Typora, download images to a local `.assets` folder, and convert mathematical formulas to LaTeX.

## Triggering

**Explicit invocation only.** Run only when the user uses `$web2md <URL>`, `/web2md <URL>`, or `@web2md <URL>`.

Do not trigger when the user casually provides a URL without explicitly invoking `$web2md`, `/web2md`, or `@web2md`.

## Workflow

Resolve `{项目根目录}` before selecting a Python environment. Store project-specific initialization state only under `{项目根目录}/.web2md_tools/`.

### Step 1: Initialize or reuse the project Python environment

**Read the project configuration first.** Use `{项目根目录}/.web2md_tools/config.json` as the persistent source of truth across Codex sessions.

The configuration format is:

```json
{
  "version": 1,
  "python_path": "E:\\work\\python_env\\python310\\python.exe"
}
```

When `config.json` exists:

1. Parse it as UTF-8 JSON and require `version` to equal `1` and `python_path` to be a non-empty absolute path to a Python executable.
2. Confirm that `python_path` exists as a file.
3. Launch it with `-c "import sys; print(sys.executable)"` and require a successful exit.
4. If these checks pass, reuse it immediately without asking the user—even in a new Codex session or when session memory is unavailable.

Ask for a Python environment again only when one of these conditions is true:

- `config.json` is missing, malformed, uses an unsupported version, or contains an invalid `python_path`.
- The recorded executable is missing or cannot be launched successfully.
- The user explicitly asks to change the Python environment.

When asking, use Chinese: “有想用的 Python 环境路径吗？直接回车我自动搜索。”

If the user specifies an environment directory, resolve it to its `python.exe`; if the user specifies an executable, use it directly. Normalize and validate the absolute executable path before continuing.

If the user skips the question, scan automatically:

- `where.exe python` / `where.exe python3`
- `$env:USERPROFILE\python_env\*\python.exe`、`E:\work\python_env\*\python.exe`
- the system `PATH`

After finding candidates, list them for the user to confirm. Prefer an environment that already has `requests`/`bs4`/`markdownify`/`lxml`.

Check the required dependencies after the interpreter itself passes validation. If dependencies are missing, keep the recorded interpreter and obtain the user's permission before running:

```powershell
& "<python路径>" -m pip install requests beautifulsoup4 markdownify lxml -q
```

Do not ask for a different Python path merely because dependencies are missing. Ask for another environment only if the current interpreter becomes unusable, dependency installation cannot make it usable, or the user requests a change.

After a newly selected interpreter launches successfully and its required dependencies are available, create `{项目根目录}/.web2md_tools/` if necessary and write or replace `config.json` with `version: 1` and the normalized absolute `python_path`. Never overwrite a valid saved path with a different environment without one of the conditions above.

Do not write the Python path to `.claude/settings.local.json` or modify Codex global configuration. Do not download dependencies in advance while creating or validating the skill.

### Step 2: Use the shared scripts

Treat the directory containing this `SKILL.md` as `<skill-directory>`. All projects must execute the canonical scripts directly from `<skill-directory>/scripts/`. In the current installation, this resolves to `C:\Users\root\.codex\skills\web2md\scripts\`.

Confirm that every script listed below exists in `<skill-directory>/scripts/` before continuing. If any required script is missing, stop and report the missing file. Never reconstruct scripts from memory, embed their source in this file, or modify a shared script while converting a webpage.

> **Shared-script rule:** Place every future reusable or shared script in `<skill-directory>/scripts/`; never copy shared scripts into individual projects.

Create only the project-specific working directories `{项目根目录}/.web2md_tools/intermediate/` and `{项目根目录}/.web2md_tools/_archive/` when they are needed. Ignore any legacy `.web2md_tools/*.py` copies already present in a project; do not execute, update, or delete them unless the user explicitly requests it.

| File | Purpose | Stage |
|------|------|------|
| `web2md.py` | Main fetching script | Step 3 |
| `markdown_code.py` | Shared code-span/fence masking helper | Steps 4-A–4-C and Finalization |
| `fix_escapes.py` | `\_` `\*` → `_` `*` | Step 4-A |
| `list_display_fixes.py` | Safely promote deterministic `$`→`$$` formulas and list remaining candidates | Step 4-B |
| `find_all_missed.py` | Scan for pseudo-formula patterns | Step 4-C |
| `final_verify.py` | Verify formulas, tables, and local image references | Finalization |

### Step 3: Fetch the page

```powershell
& "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}"
```

Automatically use the `HTTP_PROXY` / `HTTPS_PROXY` environment variables when present.

Before formula extraction, `web2md.py` performs narrowly scoped DOM normalization: it makes non-math relative links absolute, converts Sphinx fragment links to source-page links, removes Sphinx header-link glyphs while linking each heading to its original section, and wraps escaped prose placeholders such as `&lt;path&gt;` in `<code>`. This pass must skip Wikipedia `.mwe-math-element`, MathJax `<script type="math/tex...">`, `<math>`, `class="math"`, and all `<code>`, `<pre>`, `<script>`, and `<style>` subtrees. `process_math_formulas` runs only after this pass. Never post-process a formula payload to implement link, heading, or placeholder cleanup.

### Step 4: Review mathematical formulas

The `process_math_formulas` function recognizes only four kinds of markup—Wikipedia `.mwe-math-element`, MathJax `<script>`, `<math>`, and `class="math"`—and converts them to `$...$` / `$$...$$`.

After generating the `.md` file, complete the review in four stages:

#### Stage A: Automatic script repair (`fix_escapes.py`)

Fix incorrect `\_` and `\*` escaping introduced by markdownify (subscript `x_{k}` → `x\_{k}`, superscript `q^{*}` → `q^{\*}`).

```powershell
& "<python路径>" "<skill-directory>/scripts/fix_escapes.py" "{md文件路径}"
```

Internal logic: replace `\_` → `_` and `\*` → `*` inside `$$` and `$` blocks (limited to 2,000 characters to guard against a dangling `$`), then apply a global fallback.

> **Do not repair `\{` or `\}` at this stage**—they are valid LaTeX components of `\left\{` and `\right\}`.

#### Stage B: Promote deterministic `$` vs `$$` fixes (`list_display_fixes.py` + Codex verification)

```powershell
& "<python路径>" "<skill-directory>/scripts/list_display_fixes.py" "{md文件路径}" --apply
```

The script automatically promotes formulas containing `\begin{aligned/cases/array/bmatrix}` or genuine `\\` line breaks from `$...$` to `$$...$$`. It changes only the delimiters and preserves the formula payload byte-for-byte. Other candidates are listed for Codex verification; Codex must not manually rewrite deterministic candidates.

| Condition | Decision |
|------|------|
| `\begin{aligned/cases/array/bmatrix}` | → `$$` |
| Contains `\\` line breaks (multiline formula) | → `$$` |
| All other single-line formulas | Keep `$` (`$\displaystyle...$` is equivalent to `$$` in Typora) |

#### Stage C: LLM full-read loop (pseudo-formula identification)

Wikipedia renders simple formulas with `<b>`, `<i>`, and `<sup>`, which markdownify converts to `**i**` and `*i*`. A script cannot judge them—**Codex must read the entire `.md` file** and identify them from context.

1. **Read through** the `.md` file → identify missed pseudo-formulas (`**w***k*`, `*x*2`, `*a*1 + *b*2**i**`, etc.).
2. **Write a checklist** to `.web2md_tools/intermediate/fix_list_roundN.md` using the format `line number + original snippet → suggested fix`.
3. **Edit each item individually**, crossing it off after fixing it.
4. **Reread and review**.
5. If anything was missed → return to step 2, **until the document is clean**.

#### Fragmented inline-math sequences: Codex judgment

During every full read, inspect adjacent inline-math fragments separated only by punctuation, such as `$x$-$y'$-$z''$`. Treat them as **candidates**, not automatic replacements: a script may list their locations, but Codex must read the surrounding sentence and decide whether the fragments form one mathematical object.

Use these rules:

1. Merge fragments when they jointly denote one sequence, coordinate tuple, mapping, equation, or other single mathematical object.
2. Keep separate formulas when prose connectors such as `or` or `and` separate distinct mathematical objects.
3. Choose the connector from meaning:
   - For genuine subtraction, use a mathematical minus inside one formula: `$x-y$`.
   - For a named sequence whose hyphens are separators rather than subtraction, use `\text{-}` inside one formula.
4. Add every candidate and its contextual decision to the round checklist, including candidates deliberately left unchanged.
5. Never use a regular expression or automatic replacement to make this semantic decision. Apply only exact, individually reviewed edits.

Example—Tait–Bryan rotation-axis sequences:

| Original | Fix | Reason |
|------|------|------|
| `$x$-$y'$-$z''$` | `$x\text{-}y'\text{-}z''$` | One intrinsic axis sequence; the hyphens are separators |
| `$x$-$y'$-$z''$ ... or $z$-$y$-$x$` | `$x\text{-}y'\text{-}z''$ ... or $z\text{-}y\text{-}x$` | Keep the two sequences separate because `or` is prose |

In final verification, confirm that every fragmented-inline-math candidate was reviewed by Codex and that each completed sequence uses one `$...$` block.

Common missed patterns, grouped by type:

**A. Italic + number → subscript or superscript**

| Original | Fix | Explanation |
|------|------|------|
| `*a*1` | `$a_{1}$` | Italic letter + number → subscript |
| `*x*2` | `$x^{2}$` | Use context to decide whether it is a subscript or superscript |
| `*S*3` | `$S^{3}$` | Mathematical symbol + superscript |
| `*r*−1` | `$r^{-1}$` | Variable + exponent |

**B. Italic + operator → inline formula**

| Original | Fix | Explanation |
|------|------|------|
| `*x* = *y*` | `$x=y$` | Equation |
| `*a* + *b*` | `$a+b$` | Addition expression |
| `*p* − *q*` | `$p-q$` | Subtraction expression |
| `*c* = *d* = 0` | `$c=d=0$` | Chained equation |
| `*aq* = *qa*` | `$aq=qa$` | Product equation |

**C. Bold + number/operator → vector formula**

| Original | Fix | Explanation |
|------|------|------|
| `**i**2` | `$\mathbf{i}^{2}$` | Bold + superscript |
| `**i** ⋅ **j** = **k**` | `$\mathbf{i}\cdot\mathbf{j}=\mathbf{k}$` | Bold + operator |

**D. Bold letters used as mathematical symbols in prose**

| Original | Fix | Explanation |
|------|------|------|
| `{1, **i**, **j**, **k**}` | `$\{1,\mathbf{i},\mathbf{j},\mathbf{k}\}$` | Set |
| `±**i**, ±**j**, ±**k**` | `$\pm\mathbf{i},\pm\mathbf{j},\pm\mathbf{k}$` | With plus/minus signs |
| `**i**, **j**, and **k** will denote` | `$\mathbf{i},\mathbf{j},\mathbf{k}$ will denote` | Symbols within prose |
| `replacing 1 with a, **i** with b` | `replacing $1$ with $a$, $\mathbf{i}$ with $b$` | Mapping definition |

> ⚠️ In a multiplication table, `| **i** | **j** | **k** |` → **keep the bold formatting**; it is table formatting, not a formula.

**E. Function + italic argument**

| Original | Fix | Explanation |
|------|------|------|
| `cos(*φ*)` | `$\cos(\varphi)$` | Trigonometric function |
| `sin(*θ*)` | `$\sin(\theta)$` | Same as above |

**F. Mixed bold + italic expressions**

| Original | Fix | Explanation |
|------|------|------|
| `*a* + *b* **i** + *c* **j** + *d* **k**` | `$a+b\mathbf{i}+c\mathbf{j}+d\mathbf{k}$` | Quaternion expression |
| `*a*1 + *b*1**i** + *c*1**j**` | `$a_{1}+b_{1}\mathbf{i}+c_{1}\mathbf{j}$` | Expression with subscripts |
| `*p* = *b*1**i** + *c*1**j** + *d*1**k**` | `$p=b_{1}\mathbf{i}+c_{1}\mathbf{j}+d_{1}\mathbf{k}$` | Vector definition |

**G. Italic with special symbols (such as a superscript star)**

| Original | Fix | Explanation |
|------|------|------|
| `*pq*∗` | `$pq^{*}$` | Conjugate/dual marker |
| `*p*∗*q*` | `$p^{*}q$` | Same as above |
| `−*q*∗*p*∗` | `$-q^{*}p^{*}$` | Same as above |

**H. Mathematical symbols/notation**

| Original | Fix | Explanation |
|------|------|------|
| `*d*g(*p*, *q*)` | `$d_{g}(p,q)$` | Function + subscript + arguments |
| `*r a r*−1` | `$rar^{-1}$` | Conjugation expression |
| `*p*s, *q*s, *p*v, *q*v` | `$p_{s},q_{s},p_{v},q_{v}$` | Variable + subscript |

**I. Mathematical symbols and units**

Wikipedia renders some mathematical symbols with bold text or Unicode, which the script cannot recognize.

**I-1. Bold uppercase letters (number field/set notation)** — Wikipedia uses `**X**` in place of blackboard bold `\mathbb{X}`:

| Original | Field/set | Fix |
|------|------|------|
| `**R**` | Real numbers | `$\mathbf{R}$` |
| `**C**` | Complex numbers | `$\mathbf{C}$` |
| `**Z**` | Integers | `$\mathbf{Z}$` |
| `**Q**` | Rational numbers | `$\mathbf{Q}$` |
| `**N**` | Natural numbers | `$\mathbf{N}$` |
| `**F**` | Field | `$\mathbf{F}$` |
| `**H**` | Quaternions | `$\mathbf{H}$` |
| `**U**` | Unitary group/operator | `$\mathbf{U}$` |
| `**O**` | Orthogonal group | `$\mathbf{O}$` |
| `**S**` | Sphere/special group | `$\mathbf{S}$` |
| `M(2,**C**)` | Matrix ring | `$M(2,\mathbf{C})$` |

**I-2. Angles and units**

| Original | Fix | Explanation |
|------|------|------|
| `90°` `180°` `360°` | `$90^{\circ}$`, etc. | Angles in degrees |
| `45′` `30″` | `$45'$` `$30''$` | Minutes and seconds (rare) |

**I-3. Unicode operators**

| Original | Fix | Explanation |
|------|------|------|
| `±x` `±i` | `$\pm x$` | Plus/minus sign + variable |
| `a ⋅ b` | `$a \cdot b$` | Dot product |
| `a × b` | `$a \times b$` | Cross product (keep Unicode in dimensions such as `2 × 2`) |
| `a ∗ b` | `$a * b$` | Convolution/star product |
| `−x` | `$-x$` | Unicode minus sign |

**I-4. Inequalities and relation symbols**

| Original | Fix |
|------|------|
| `a ≤ b` | `$a \leq b$` |
| `a ≥ b` | `$a \geq b$` |
| `a ≠ b` | `$a \neq b$` |
| `a ≈ b` | `$a \approx b$` |
| `a ≡ b` | `$a \equiv b$` |
| `a ∼ b` | `$a \sim b$` |
| `a ∝ b` | `$a \propto b$` |

**I-5. Set and logical symbols**

| Original | Fix |
|------|------|
| `x ∈ S` | `$x \in S$` |
| `x ∉ S` | `$x \notin S$` |
| `A ⊂ B` | `$A \subset B$` |
| `A ⊆ B` | `$A \subseteq B$` |
| `A ∪ B` | `$A \cup B$` |
| `A ∩ B` | `$A \cap B$` |
| `∀x` | `$\forall x$` |
| `∃x` | `$\exists x$` |

**I-6. Arrows**

| Original | Fix | Explanation |
|------|------|------|
| `f: A → B` | `$f: A \to B$` | Function mapping |
| `x ↦ y` | `$x \mapsto y$` | Element mapping |
| `A ⇒ B` | `$A \Rightarrow B$` | Implication |
| `A ⇔ B` | `$A \Leftrightarrow B$` | Equivalence |
| Table header `→` | Keep Unicode | Table formatting |

**I-7. Other common symbols**

| Original | Fix |
|------|------|
| `∞` | `$\infty$` |
| `∂f/∂x` | `$\partial f / \partial x$` |
| `∇f` | `$\nabla f$` |
| `√x` | `$\sqrt{x}$` |

> **Decision boundary**: When adjacent to variables, numbers, or equals signs → convert to `$...$`; preserve dimensions such as `2 × 2` and table arrows. Preserve the table header `| **i** |`.

> **NBSP trap**: Wikipedia formulas often use `\xa0` (non-breaking space). Exact text matching may miss `**i\xa0⋅\xa0j**`, so check for it separately.

Optional auxiliary scan:

```powershell
& "<python路径>" "<skill-directory>/scripts/find_all_missed.py" "{md文件路径}"
```

#### Stage D: Review Markdown structure

During the same full-document read, inspect Markdown structure as well as formulas:

1. Check every table for a valid header separator, consistent column counts, and no leading `:   ` or four-space code-block indentation.
2. Reconstruct tables semantically when one mathematical tuple, sequence, or equation was split across several cells. Do not add a page-specific automatic rewrite.
3. Check that every local Markdown image target exists. Treat failed downloads that produced no Markdown image reference as harmless, but do not leave broken local references.
4. Check that fenced code blocks are closed and that prose placeholders such as `<path>` are code-formatted. Ignore placeholder-like text inside inline code, fenced code, and LaTeX.
5. For Sphinx pages, confirm that heading text links to the exact source section, the `` header-link glyph is absent, relative non-image links resolve to the source site, and legacy local command links such as `#cmdmount` do not remain.
6. Review a **Command Syntax** section that became a blockquote. Convert it to code only when the page semantics show that it is command syntax; do not make a global blockquote-to-code rewrite.
7. Do not invent table headers or rewrite blockquotes automatically when their semantics are unclear. Add each candidate and its contextual decision to the round checklist.
8. Rerun verification until no structural issue remains.

#### Final verification (`final_verify.py`)

```powershell
& "<python路径>" "<skill-directory>/scripts/final_verify.py" "{md文件路径}"
```

Require a zero exit code. Confirm that every math block has balanced LaTeX braces, `\_` and `\*` have been reduced to zero, `\\` line breaks are intact, `\left\{` has not been damaged, every `$$` occupies its own line, fenced code blocks are closed, tables are structurally valid, local image references exist, raw prose placeholders and Sphinx header glyphs are absent, relative non-image links are valid, legacy local command anchors are absent, and every item in the LLM checklist is checked off. The verifier masks fenced code, inline code, and LaTeX before applying prose-oriented checks.

### Step 5: Deliver the output

Tell the user the file path and that it can be opened with Typora.

If Codex discovered a new failure mode while fetching, converting, or reviewing the page, add a short post-task section that:

1. Summarizes the symptom, likely cause, and manual repair.
2. States `Recommend updating web2md Skill: yes` or `no`, with the specific Skill file or script that should change when the answer is yes.

Treat a failure mode as new only when the current scripts and instructions did not already detect or handle it. If no new failure mode appeared, omit this section entirely. Do not modify the shared Skill during a conversion unless the user explicitly asks for that update.

---

## Project-local working files

- `.web2md_tools/config.json` — persistent project Python environment (`version` + normalized `python_path`)
- `.web2md_tools/intermediate/` — LLM checklists named `fix_list_roundN.md`
- `.web2md_tools/_archive/` — one-off debugging and diagnostic files

### Directory structure rules

Keep all reusable scripts in the shared Skill directory:

```
<skill-directory>/
└── scripts/
    ├── web2md.py              ← main fetcher
    ├── markdown_code.py       ← shared fenced/inline code masking helper
    ├── fix_escapes.py          ← Stage A: repair \_ and \*
    ├── list_display_fixes.py   ← Stage B: safely apply deterministic $→$$ fixes
    ├── find_all_missed.py      ← Stage C: pseudo-formula scan
    └── final_verify.py         ← formula and Markdown structure verification
```

Keep only project-specific working data in `.web2md_tools/`:

```
.web2md_tools/
├── config.json             ← persistent Python environment for this project
├── intermediate/           ← LLM checklists named fix_list_roundN.md
└── _archive/               ← one-off files such as debugging scripts and temporary tests
```

- Do not scatter `.py` / `.txt` / `.json` files in the project root.
- Keep the confirmed Python executable only in `.web2md_tools/config.json`; validate and reuse it across Codex sessions.
- Put intermediate checklists generated by the LLM in `intermediate/`.
- Put non-reusable one-off scripts in `_archive/`.

---

## Key technical details of the scripts

### Defensive design

| Mechanism | Location | Explanation |
|------|------|------|
| `unquote()` for image filenames | `download_images` | Wikipedia URLs contain encodings such as `%28`, `%29`, and `%3D`; decode them before constructing filenames |
| Compare Wikipedia TeX sources | `wikipedia_latex` | Prefer a balanced, more complete image `alt` formula when MathML annotation text is truncated |
| Protected-subtree DOM normalization | `normalize_document_html` | Normalize links, Sphinx headings, and escaped prose placeholders before formula extraction while leaving math and code subtrees untouched |
| Sphinx source-section links | `link_sphinx_headings` / `normalize_document_links` | Remove header glyphs, link heading text to the exact source section, and resolve relative document links without changing formula contents |
| Text-node placeholder protection | `protect_angle_placeholders` | Wrap escaped prose placeholders in code without changing actual HTML tags or placeholder-like text inside math/code nodes |
| Markdown code masks | `markdown_code.py` | Make formula repair and verification ignore fenced and inline code while continuing to scan real LaTeX outside code |
| `is_wiki` domain check | `html_to_markdown` | Clean language bars/edit links and remove `[[edit]]` only for `wikipedia.org` / `wikimedia.org` |
| Unindent definition-list tables | `normalize_definition_list_tables` | Remove markdownify's `:   ` plus four-space nesting so Typora can parse the table before semantic review |
| Put `$$` on its own line | `html_to_markdown` | For `([^\n])\$\$`, insert `\n\n` before it; for `\$\$([^\n])`, insert `\n\n` after it, ensuring Typora recognizes the block |
| Truncate image names with `max_len=60` | `sanitize_filename` | Avoid excessively long filenames |
| Wikimedia rate-limit backoff | `download_images` | On HTTP 429, wait progressively for 2/4/6 seconds; add a 0.3-second interval between Wikimedia images |

### Explicitly prohibited actions

- **Do not treat `\{` or `\}` as Markdown escaping to repair**—they are valid LaTeX components of `\left\{` and `\right\}`.
- **Do not run link, heading, or placeholder normalization inside math or code subtrees**—formula payloads must remain byte-for-byte unchanged until `process_math_formulas` extracts them.
- **Do not use a global Markdown regular expression to wrap `<...>` placeholders**—operate on eligible DOM text nodes so actual HTML, code, and LaTeX remain untouched.
- **Do not automatically assign table headers or convert all blockquotes to code**—those are semantic decisions requiring full-document review.
- **Do not use regular expressions to distinguish whether `**i**` is a formula or bold text**—that is an LLM task and cannot be done by the script.
- **Do not apply Wikipedia-specific cleanup to non-Wikipedia pages**—use `is_wiki` as the guard.
- **Codex must make the judgment even when a script performs the replacement**—for conversions such as `**i**` → `$\mathbf{i}$`, a script may only use exact `str.replace` operations (with Codex manually writing each old→new pair), never regular expressions or automatic judgment. Distinguishing “bold text in a table” from “a bold mathematical symbol” requires contextual understanding and cannot be done by the script.
- **Scripts perform only mechanical operations; Codex reviews everything**—scripts handle mechanical changes such as `\_` → `_`, `\*` → `*`, and placing `$$` on its own line. These changes can still be wrong, incomplete, or damaging. Codex must read the entire document and verify every formula individually, including formulas that scripts changed and formulas they did not change. Never skip verification because “the script already handled it.” Prioritize quality and do not conserve tokens.
