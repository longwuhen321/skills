#!/usr/bin/env python3
"""Fail-closed structural checks and heuristic warnings for md2zh output."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*?)(?:\r?\n)?$")
ATX_RE = re.compile(r"^( {0,3})(#{1,6})(?:[ \t]+|$)")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
LIST_RE = re.compile(r"^(\s*)([-+*]|\d+[.)])([ \t]+)")
BLOCKQUOTE_RE = re.compile(r"^(\s*(?:>[ \t]?)+)")
TABLE_DELIMITER_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
REFERENCE_DEFINITION_RE = re.compile(r"^ {0,3}\[([^\]\r\n]+)\]:[ \t]*(.+)$")
REFERENCE_USE_RE = re.compile(r"(?<!\\)\]\[([^\]\r\n]*)\]")
URL_START_RE = re.compile(r"(?<![\w])https?://")
URL_CHAR_RE = re.compile(r"[A-Za-z0-9._~:/?#\[\]@!$&'*+,;=%-]")
ENTITY_RE = re.compile(r"&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
ESCAPE_RE = re.compile(r"\\[`*{}\[\]()#+\-.!_|>]")
HTML_TAG_RE = re.compile(
    r"<!--.*?-->|</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*?)?/?>", re.DOTALL
)
PLACEHOLDER_RE = re.compile(
    r"(?i)(?:__|@@|⟦|<)\s*(?:MD2ZH|PLACEHOLDER|PROTECTED|PH)"
    r"[A-Z0-9_:\-]*\s*(?:__|@@|⟧|>)|\bXPH\d+X\b"
)
TRANSLATION_NOTE_RE = re.compile(
    r"^[ \t]*>[ \t]*(?:翻译说明|译注)[:：][^\r\n]*(?:\r\n|\n|\r|$)",
    re.MULTILINE,
)
TRANSLATIONESE = ("进行一个", "被由", "这意味着说", "关于于", "取决于于")


@dataclass
class Document:
    path: Path
    text: str
    newline_style: str
    dominant_newline_style: str
    bom: bool
    visible_text: str
    fenced_blocks: List[str]
    unclosed_fence: bool


def newline_styles(data: bytes) -> Tuple[str, str]:
    crlf = data.count(b"\r\n")
    lone_lf = data.count(b"\n") - crlf
    lone_cr = data.count(b"\r") - crlf
    kinds = sum(value > 0 for value in (crlf, lone_lf, lone_cr))
    if kinds > 1:
        counts = {"crlf": crlf, "lf": lone_lf, "cr": lone_cr}
        return "mixed", max(counts, key=counts.get)
    if crlf:
        return "crlf", "crlf"
    if lone_lf:
        return "lf", "lf"
    if lone_cr:
        return "cr", "cr"
    return "none", "none"


def newline_sequence(text: str) -> List[str]:
    return re.findall(r"\r\n|\n|\r", text)


def remove_added_translation_note(source: str, output: str) -> str:
    source_notes = len(TRANSLATION_NOTE_RE.findall(source))
    output_notes = list(TRANSLATION_NOTE_RE.finditer(output))
    if len(output_notes) != source_notes + 1:
        return output
    match = output_notes[0]
    return output[: match.start()] + output[match.end() :]


def line_ending_only(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def hide_fenced_blocks(text: str) -> Tuple[str, List[str], bool]:
    visible: List[str] = []
    blocks: List[str] = []
    current: List[str] = []
    fence_char = ""
    fence_length = 0

    for line in text.splitlines(keepends=True):
        match = FENCE_RE.match(line)
        if not current:
            if match:
                marker = match.group(2)
                fence_char = marker[0]
                fence_length = len(marker)
                current = [line]
                visible.append(line_ending_only(line))
            else:
                visible.append(line)
            continue

        current.append(line)
        visible.append(line_ending_only(line))
        if match:
            marker = match.group(2)
            if marker[0] == fence_char and len(marker) >= fence_length and not match.group(3).strip():
                blocks.append("".join(current))
                current = []
                fence_char = ""
                fence_length = 0

    if current:
        blocks.append("".join(current))
    return "".join(visible), blocks, bool(current)


def read_document(path: Path) -> Document:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("{} is not valid UTF-8: {}".format(path, exc)) from exc
    visible, blocks, unclosed = hide_fenced_blocks(text)
    style, dominant_style = newline_styles(raw)
    return Document(path, text, style, dominant_style, bom, visible, blocks, unclosed)


def mask_match(text: str, match: re.Match[str]) -> str:
    return text[: match.start()] + "".join(
        char if char in "\r\n" else " " for char in match.group(0)
    ) + text[match.end() :]


def extract_and_mask(text: str, pattern: re.Pattern[str]) -> Tuple[List[str], str]:
    matches = list(pattern.finditer(text))
    tokens = [match.group(0) for match in matches]
    for match in reversed(matches):
        text = mask_match(text, match)
    return tokens, text


def extract_inline_code(text: str) -> Tuple[List[str], str]:
    pattern = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
    return extract_and_mask(text, pattern)


def extract_math(text: str) -> Tuple[Dict[str, List[str]], str]:
    patterns = (
        ("display_dollar", re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL)),
        ("display_bracket", re.compile(r"(?<!\\)\\\[.*?(?<!\\)\\\]", re.DOTALL)),
        ("inline_paren", re.compile(r"(?<!\\)\\\(.*?(?<!\\)\\\)", re.DOTALL)),
        (
            "inline_dollar",
            re.compile(r"(?<![\\$])\$(?!\$)(?:\\.|[^$\r\n])+?(?<!\\)\$(?!\$)"),
        ),
    )
    found: Dict[str, List[str]] = {}
    for name, pattern in patterns:
        found[name], text = extract_and_mask(text, pattern)
    return found, text


def atomic_order(text: str) -> List[Tuple[str, str]]:
    inline_code_re = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
    math_patterns = (
        ("display_dollar", re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL)),
        ("display_bracket", re.compile(r"(?<!\\)\\\[.*?(?<!\\)\\\]", re.DOTALL)),
        ("inline_paren", re.compile(r"(?<!\\)\\\(.*?(?<!\\)\\\)", re.DOTALL)),
        (
            "inline_dollar",
            re.compile(r"(?<![\\$])\$(?!\$)(?:\\.|[^$\r\n])+?(?<!\\)\$(?!\$)"),
        ),
    )
    result: List[Tuple[str, str]] = []
    index = 0
    while index < len(text):
        code = inline_code_re.match(text, index)
        if code:
            result.append(("inline_code", code.group(0)))
            index = code.end()
            continue

        matched_math = False
        for kind, pattern in math_patterns:
            match = pattern.match(text, index)
            if match:
                result.append((kind, match.group(0)))
                index = match.end()
                matched_math = True
                break
        if matched_math:
            continue

        if text.startswith("](", index) and not is_escaped(text, index):
            depth = 1
            cursor = index + 2
            while cursor < len(text) and depth:
                if not is_escaped(text, cursor):
                    if text[cursor] == "(":
                        depth += 1
                    elif text[cursor] == ")":
                        depth -= 1
                cursor += 1
            if depth == 0:
                result.append(("link_target", text[index + 2 : cursor - 1]))
                index = cursor
                continue

        if text.startswith("{{", index) and not is_escaped(text, index):
            depth = 1
            cursor = index + 2
            while cursor < len(text) - 1 and depth:
                pair = text[cursor : cursor + 2]
                if pair == "{{" and not is_escaped(text, cursor):
                    depth += 1
                    cursor += 2
                    continue
                if pair == "}}" and not is_escaped(text, cursor):
                    depth -= 1
                    cursor += 2
                    continue
                cursor += 1
            if depth == 0:
                result.append(("template", text[index:cursor]))
                index = cursor
                continue

        html = HTML_TAG_RE.match(text, index)
        if html:
            result.append(("html", html.group(0)))
            index = html.end()
            continue

        url = URL_START_RE.match(text, index)
        if url:
            cursor = url.end()
            paren_depth = 0
            while cursor < len(text):
                char = text[cursor]
                if char == "(":
                    paren_depth += 1
                elif char == ")":
                    if paren_depth == 0:
                        break
                    paren_depth -= 1
                elif not URL_CHAR_RE.fullmatch(char):
                    break
                cursor += 1
            result.append(("raw_url", text[index:cursor]))
            index = cursor
            continue

        entity = ENTITY_RE.match(text, index)
        if entity:
            result.append(("entity", entity.group(0)))
            index = entity.end()
            continue
        escape = ESCAPE_RE.match(text, index)
        if escape:
            result.append(("escape", escape.group(0)))
            index = escape.end()
            continue
        index += 1
    return result


def is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def scan_links(text: str) -> Tuple[List[Tuple[str, str]], int]:
    stack: List[int] = []
    links: List[Tuple[str, str]] = []
    malformed = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "[" and not is_escaped(text, index):
            stack.append(index)
        elif char == "]" and not is_escaped(text, index):
            opener = stack.pop() if stack else None
            if index + 1 < len(text) and text[index + 1] == "(":
                if opener is None:
                    malformed += 1
                    index += 1
                    continue
                depth = 1
                cursor = index + 2
                while cursor < len(text) and depth:
                    if not is_escaped(text, cursor):
                        if text[cursor] == "(":
                            depth += 1
                        elif text[cursor] == ")":
                            depth -= 1
                    cursor += 1
                if depth:
                    malformed += 1
                    index += 1
                    continue
                kind = "image" if opener > 0 and text[opener - 1] == "!" else "link"
                links.append((kind, text[index + 2 : cursor - 1]))
                index = cursor - 1
        index += 1
    return links, malformed


def extract_urls(text: str) -> List[str]:
    urls: List[str] = []
    for match in URL_START_RE.finditer(text):
        cursor = match.end()
        paren_depth = 0
        while cursor < len(text):
            char = text[cursor]
            if char == "(":
                paren_depth += 1
            elif char == ")":
                if paren_depth == 0:
                    break
                paren_depth -= 1
            elif not URL_CHAR_RE.fullmatch(char):
                break
            cursor += 1
        urls.append(text[match.start() : cursor])
    return urls


def extract_balanced_templates(text: str) -> Tuple[List[str], int]:
    tokens: List[str] = []
    stack: List[int] = []
    index = 0
    malformed = 0
    while index < len(text) - 1:
        pair = text[index : index + 2]
        if pair == "{{" and not is_escaped(text, index):
            stack.append(index)
            index += 2
            continue
        if pair == "}}" and not is_escaped(text, index):
            if not stack:
                malformed += 1
            else:
                start = stack.pop()
                if not stack:
                    tokens.append(text[start : index + 2])
            index += 2
            continue
        index += 1
    malformed += len(stack)
    return tokens, malformed


def heading_signatures(text: str) -> List[str]:
    signatures: List[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        atx = ATX_RE.match(line)
        if atx:
            signatures.append("atx:{}".format(len(atx.group(2))))
        elif index > 0 and lines[index - 1].strip() and SETEXT_RE.match(line):
            signatures.append("setext:{}".format(line.lstrip()[0]))
    return signatures


def list_signatures(text: str) -> List[Tuple[int, str]]:
    result = []
    for line in text.splitlines():
        match = LIST_RE.match(line)
        if match:
            marker = match.group(2)
            kind = marker if not marker[0].isdigit() else marker[-1]
            result.append((len(match.group(1).expandtabs(4)), kind))
    return result


def blockquote_signatures(text: str) -> List[str]:
    result = []
    for line in text.splitlines():
        if re.match(r"^\s*>\s*(?:翻译说明|译注)[:：]", line):
            continue
        match = BLOCKQUOTE_RE.match(line)
        if match:
            result.append(re.sub(r"[^>]", "", match.group(1)))
    return result


def pipe_count(line: str) -> int:
    return sum(char == "|" and not is_escaped(line, index) for index, char in enumerate(line))


def table_signatures(text: str) -> List[Tuple[int, bool, bool]]:
    result = []
    for line in text.splitlines():
        count = pipe_count(line)
        if not count:
            continue
        stripped = line.strip()
        leading = stripped.startswith("|")
        trailing = stripped.endswith("|") and not is_escaped(stripped, len(stripped) - 1)
        result.append((count, leading, trailing))
    return result


def table_delimiters(text: str) -> List[str]:
    return [line for line in text.splitlines() if TABLE_DELIMITER_RE.match(line)]


def reference_definitions(text: str) -> List[str]:
    return [line for line in text.splitlines() if REFERENCE_DEFINITION_RE.match(line)]


def original_link_lines(text: str) -> List[str]:
    return [line for line in text.splitlines() if re.match(r"^\s*>\s*原文链接:", line)]


def block_count(text: str) -> int:
    return len(
        [part for part in re.split(r"(?:(?:\r\n|\n|\r)){2,}", text) if part.strip()]
    )


def first_difference(left: Sequence[Any], right: Sequence[Any]) -> int:
    for index, (left_item, right_item) in enumerate(zip(left, right)):
        if left_item != right_item:
            return index
    return min(len(left), len(right))


def compare_sequence(
    label: str, source: Sequence[Any], output: Sequence[Any], errors: List[str]
) -> None:
    if source != output:
        index = first_difference(source, output)
        errors.append(
            "{} changed (source {}, output {}, first difference at item {})".format(
                label, len(source), len(output), index + 1
            )
        )


def compare_collection(
    label: str, source: Sequence[Any], output: Sequence[Any], errors: List[str]
) -> None:
    if Counter(source) != Counter(output):
        missing = list((Counter(source) - Counter(output)).elements())
        added = list((Counter(output) - Counter(source)).elements())
        errors.append(
            "{} changed (source {}, output {}, missing {}, added {})".format(
                label, len(source), len(output), missing[:3], added[:3]
            )
        )


def protected_view(document: Document) -> Dict[str, Any]:
    inline_code, visible = extract_inline_code(document.visible_text)
    math, visible = extract_math(visible)
    links, malformed_links = scan_links(visible)
    templates, malformed_templates = extract_balanced_templates(visible)
    return {
        "visible": visible,
        "fenced_code": document.fenced_blocks,
        "inline_code": inline_code,
        "math": math,
        "links": links,
        "reference_uses": REFERENCE_USE_RE.findall(visible),
        "reference_definitions": reference_definitions(visible),
        "urls": extract_urls(visible),
        "html_tags": HTML_TAG_RE.findall(visible),
        "entities": ENTITY_RE.findall(visible),
        "escapes": ESCAPE_RE.findall(visible),
        "templates": templates,
        "atomic_order": atomic_order(document.visible_text),
        "malformed_links": malformed_links,
        "malformed_templates": malformed_templates,
        "headings": heading_signatures(visible),
        "lists": list_signatures(visible),
        "blockquotes": blockquote_signatures(visible),
        "tables": table_signatures(visible),
        "table_delimiters": table_delimiters(visible),
        "original_link_lines": original_link_lines(visible),
        "blocks": block_count(visible),
    }


def warning_lines(source: str, output: str) -> List[str]:
    warnings: List[str] = []
    source_lines = {line.strip() for line in source.splitlines() if line.strip()}
    english_heavy: List[int] = []
    unchanged: List[int] = []
    mixed_punctuation: List[int] = []
    translationese: List[Tuple[int, str]] = []

    for number, line in enumerate(output.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or REFERENCE_DEFINITION_RE.match(line):
            continue
        latin = len(re.findall(r"[A-Za-z]", stripped))
        han = len(re.findall(r"[\u3400-\u9fff]", stripped))
        if latin >= 24 and han == 0 and not stripped.startswith(("http://", "https://")):
            english_heavy.append(number)
        if stripped in source_lines and latin >= 24 and han == 0:
            unchanged.append(number)
        if re.search(r"[\u3400-\u9fff][,;!?]|[,;!?][\u3400-\u9fff]", stripped):
            mixed_punctuation.append(number)
        for phrase in TRANSLATIONESE:
            if phrase in stripped:
                translationese.append((number, phrase))

    if english_heavy:
        warnings.append("possible untranslated English prose at output lines {}".format(english_heavy[:30]))
    if unchanged:
        warnings.append("English-heavy lines unchanged from source at output lines {}".format(unchanged[:30]))
    if mixed_punctuation:
        warnings.append("ASCII punctuation adjacent to Chinese text at output lines {}".format(mixed_punctuation[:30]))
    if translationese:
        warnings.append("possible translationese occurrences: {}".format(translationese[:30]))
    return warnings


def build_report(source: Document, output: Document) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    source_view = protected_view(source)
    output_view = protected_view(output)

    comparable_output = remove_added_translation_note(source.text, output.text)
    if newline_sequence(source.text) != newline_sequence(comparable_output):
        errors.append("source newline sequence changed")
    if source.unclosed_fence:
        errors.append("source contains an unclosed fenced code block")
    if output.unclosed_fence:
        errors.append("output contains an unclosed fenced code block")
    if output_view["malformed_links"]:
        errors.append("output contains {} malformed inline link(s)".format(output_view["malformed_links"]))
    if output_view["malformed_templates"]:
        errors.append("output contains {} unbalanced template marker(s)".format(output_view["malformed_templates"]))

    compare_sequence("fenced code", source_view["fenced_code"], output_view["fenced_code"], errors)
    compare_collection("inline code", source_view["inline_code"], output_view["inline_code"], errors)
    for math_kind in source_view["math"]:
        compare_collection(
            "{} math".format(math_kind),
            source_view["math"][math_kind],
            output_view["math"][math_kind],
            errors,
        )
    for key, label in (
        ("links", "link and image targets"),
        ("reference_uses", "reference-use identifiers"),
        ("reference_definitions", "reference definitions"),
        ("urls", "raw URLs"),
        ("html_tags", "HTML tags and attributes"),
        ("entities", "HTML entities"),
        ("escapes", "Markdown escape sequences"),
        ("templates", "template syntax"),
    ):
        compare_collection(label, source_view[key], output_view[key], errors)
    for key, label in (
        ("headings", "heading structure"),
        ("lists", "list structure"),
        ("blockquotes", "blockquote structure"),
        ("tables", "pipe/table structure"),
        ("table_delimiters", "table delimiter rows"),
        ("original_link_lines", "original-link metadata lines"),
    ):
        compare_sequence(label, source_view[key], output_view[key], errors)

    placeholders = [match.group(0) for match in PLACEHOLDER_RE.finditer(output.text)]
    if placeholders:
        errors.append("placeholder remnants found: {}".format(placeholders[:10]))

    if source_view["blocks"] != output_view["blocks"]:
        warnings.append(
            "blank-line block count changed (source {}, output {})".format(
                source_view["blocks"], output_view["blocks"]
            )
        )
    warnings.extend(warning_lines(source_view["visible"], output_view["visible"]))

    failure_count = len(errors)
    warning_count = len(warnings)
    stats = {
        "source": str(source.path),
        "output": str(output.path),
        "newline_style": output.newline_style,
        "headings": len(output_view["headings"]),
        "fenced_code_blocks": len(output_view["fenced_code"]),
        "inline_code_spans": len(output_view["inline_code"]),
        "links_and_images": len(output_view["links"]),
        "reference_definitions": len(output_view["reference_definitions"]),
        "pipe_lines": len(output_view["tables"]),
        "hard_errors": failure_count,
        "warnings": warning_count,
    }
    return {
        "pass": not errors,
        "failure_count": failure_count,
        "errors": errors,
        "warning_count": warning_count,
        "warnings": warnings,
        "stats": stats,
    }


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="source Markdown file")
    parser.add_argument("output", help="staged Chinese Markdown file")
    parser.add_argument("--report", help="optional JSON report path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        source = read_document(Path(args.source).resolve(strict=True))
        output = read_document(Path(args.output).resolve(strict=True))
        report = build_report(source, output)
        if args.report:
            write_json_atomic(Path(args.report).resolve(strict=False), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["pass"] else 1
    except (OSError, ValueError) as exc:
        print("markdown QA error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
