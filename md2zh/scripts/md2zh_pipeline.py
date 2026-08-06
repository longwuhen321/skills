#!/usr/bin/env python3
"""Losslessly extract, render, and verify visible Markdown translations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


CONFIG_VALUES = {"user", "ai"}
MINIMUM_PYTHON = (3, 8)
CONFIG_PY_TEMPLATE = (
    "# ============================================================\n"
    "# md2zh — 真实配置（本机路径，已被 .gitignore 排除，禁止提交）\n"
    "# 配置来源：/md2zh 配置向导（用户输入）。\n"
    "# ============================================================\n"
    "\n"
    "# ==================== md2zh 配置 ====================\n"
    "md2zh_config = {{\n"
    '    "python_path": {python_path!r},\n'
    '    "ambiguous_content_decider": {decider!r},\n'
    '    "output_dir": {output_dir!r},\n'
    '    "tree_translation": {tree_translation!r},\n'
    '    "max_block_chars": {max_block_chars!r},\n'
    "}}\n"
)
DEFAULT_MAX_BLOCK_CHARS = 16000
ARCHIVE_MAX_ENTRIES = 20
MAX_BLOCK_ATTEMPTS = 3
TOKEN_RE = re.compile(r"(?:@@MD2ZH:PROTECT:[A-Za-z0-9_-]+:[0-9]+@@|⟦MD2ZH:[^⟧]+⟧)")
SEGMENT_LINE_RE = re.compile(r"^@@MD2ZH:SEG:(block-[0-9]+):([0-9]+)@@$")
SEGMENT_ANY_RE = re.compile(r"@@MD2ZH:SEG:[^@\r\n]+@@")
RESERVED_NAMESPACE_RE = re.compile(r"(?:@@MD2ZH:|⟦MD2ZH:)")
MOJIBAKE_RE = re.compile(r"(?:\ufffd|Ã|Â|â€|ðŸ|锟斤拷)")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
TABLE_DELIMITER_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$"
)
SETEXT_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
REFERENCE_DEFINITION_RE = re.compile(r"^ {0,3}\[([^\]^][^\]]*)\]:[ \t]*(.+)$")
FOOTNOTE_DEFINITION_RE = re.compile(r"^( {0,3}\[\^[^\]]+\]:[ \t]*)(.*)$")
THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
DIRECTIVE_RE = re.compile(
    r"^(?P<prefix>\s*(?:(?:>[ \t]?)+)?)(?P<marker>:::\{?[A-Za-z0-9_-]+\}?|!!![A-Za-z0-9_-]*|\?\?\?[A-Za-z0-9_-]*|\[![A-Za-z0-9_-]+\])(?P<gap>[ \t]+)(?P<payload>.*?)(?P<trailing>[ \t]*)$"
)
HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*?)?/?>")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
ENTITY_RE = re.compile(r"&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
AUTOLINK_RE = re.compile(r"<(?:https?://[^<>\s]+|mailto:[^<>\s]+|[^<>\s@]+@[^<>\s@]+)>")
RAW_URL_RE = re.compile(r"https?://[^\s<>\"']+")
LATIN_RE = re.compile(r"[A-Za-z]")
DANGEROUS_TRANSLATION_RE = re.compile(r"[`*_\[\]<>|\\$]")


class PipelineError(Exception):
    """Base error for deterministic pipeline failures."""


class ConfigRequiredError(PipelineError):
    """Raised when the project has not completed its first-run choices."""


class PythonRuntimeError(PipelineError):
    """Raised when the configured Python runtime cannot safely run the pipeline."""


class TranslationValidationError(PipelineError):
    """Raised when a translation modifies or invents protected syntax."""


class DecisionValidationError(PipelineError):
    """Raised after rejected ambiguity decisions have been logged."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, str(path))
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, data: Any) -> None:
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_bytes_atomic(Path(path), payload)


def load_json(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def global_config_path() -> Path:
    """Path to the single skill-level config file (<skill>/scripts/config.py)."""
    return Path(__file__).resolve().parent / "config.py"


def probe_python(command: Sequence[str], runner=subprocess.run) -> Dict[str, Any]:
    command = [str(item) for item in command]
    probe = (
        "import json,sys; "
        "print(json.dumps({'version':list(sys.version_info[:3]),'executable':sys.executable}))"
    )
    try:
        result = runner(
            command + ["-c", probe],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PythonRuntimeError("cannot run {}: {}".format(" ".join(command), exc)) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        raise PythonRuntimeError("cannot run {}: {}".format(" ".join(command), detail))
    try:
        payload = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.strip()))
        version = [int(value) for value in payload["version"]]
        executable = str(payload["executable"])
    except (KeyError, TypeError, ValueError, StopIteration, json.JSONDecodeError) as exc:
        raise PythonRuntimeError("{} returned an invalid version probe".format(" ".join(command))) from exc
    if len(version) < 3 or tuple(version[:2]) < MINIMUM_PYTHON:
        raise PythonRuntimeError(
            "{} is Python {}; md2zh requires Python 3.8+".format(
                " ".join(command), ".".join(str(value) for value in version)
            )
        )
    return {"command": command, "version": version, "executable": executable}


def resolve_python(
    python_path: Optional[str] = None,
    runner=subprocess.run,
) -> Dict[str, Any]:
    if python_path:
        path = Path(python_path).expanduser()
        if not path.is_absolute():
            raise ValueError("python_path must be absolute")
        if not path.is_file():
            raise PythonRuntimeError("configured Python does not exist: {}".format(path))
        resolved = probe_python([str(path.resolve())], runner=runner)
        resolved["source"] = "explicit"
        return resolved

    # 缺省自动探测：只探测当前解释器（AI 正用它运行 pipeline，
    # 满足"全程同一个 Python"约束）；候选扫描是 AI 向导的工作，脚本不做。
    current = Path(sys.executable).resolve()
    resolved = probe_python([str(current)], runner=runner)
    resolved["source"] = "current-interpreter"
    return resolved


def same_executable(left: str, right: str) -> bool:
    try:
        return Path(left).samefile(Path(right))
    except OSError:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def ensure_current_python(config: Dict[str, Any]) -> Dict[str, Any]:
    python_path = config.get("python_path")
    if not isinstance(python_path, str) or not python_path:
        raise ConfigRequiredError(
            "md2zh_config has no python_path; run the /md2zh configuration wizard"
        )
    resolved = resolve_python(python_path)
    if not same_executable(sys.executable, resolved["executable"]):
        raise PythonRuntimeError(
            "md2zh must run with {}; current interpreter is {}".format(
                resolved["executable"], sys.executable
            )
        )
    return resolved


def _read_config_value(path: Path, key: str, default: Any = None) -> Any:
    """Leniently read one md2zh_config key from a config file (missing/broken → default)."""
    try:
        namespace: Dict[str, Any] = {}
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        config = namespace.get("md2zh_config")
        if isinstance(config, dict):
            return config.get(key, default)
    except (OSError, SyntaxError, ValueError):
        pass
    return default


def configure_project(
    decider: str,
    python_path: Optional[str] = None,
    config_path: Optional[Path] = None,
    output_dir: Optional[str] = None,
    tree_translation: Optional[bool] = None,
    max_block_chars: Optional[int] = None,
) -> Path:
    if decider not in CONFIG_VALUES:
        raise ValueError("ambiguous_content_decider must be 'user' or 'ai'")
    path = Path(config_path) if config_path else global_config_path()
    resolved = resolve_python(python_path)
    if not same_executable(sys.executable, resolved["executable"]):
        raise PythonRuntimeError(
            "configure md2zh with {}; current interpreter is {}".format(
                resolved["executable"], sys.executable
            )
        )
    if output_dir is None:
        output_dir = _read_config_value(path, "output_dir", "")
    if not isinstance(output_dir, str):
        output_dir = ""
    if tree_translation is None:
        tree_translation = _read_config_value(path, "tree_translation", True)
    if not isinstance(tree_translation, bool):
        tree_translation = True
    if max_block_chars is None:
        max_block_chars = _read_config_value(path, "max_block_chars", DEFAULT_MAX_BLOCK_CHARS)
    if not isinstance(max_block_chars, int) or isinstance(max_block_chars, bool):
        max_block_chars = DEFAULT_MAX_BLOCK_CHARS
    payload = CONFIG_PY_TEMPLATE.format(
        python_path=str(Path(resolved["executable"]).resolve()),
        decider=decider,
        output_dir=output_dir,
        tree_translation=tree_translation,
        max_block_chars=max_block_chars,
    )
    write_bytes_atomic(path, payload.encode("utf-8"))
    return path


def load_global_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else global_config_path()
    if not path.exists():
        raise ConfigRequiredError(
            "missing {}; run the /md2zh configuration wizard once".format(path)
        )
    namespace: Dict[str, Any] = {}
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    except (OSError, SyntaxError, ValueError) as exc:
        raise PipelineError("cannot load {}: {}".format(path, exc)) from exc
    config = namespace.get("md2zh_config")
    if not isinstance(config, dict):
        raise ConfigRequiredError("missing md2zh_config dict in {}".format(path))
    decider = config.get("ambiguous_content_decider")
    if decider not in CONFIG_VALUES:
        raise ConfigRequiredError(
            "missing ambiguous_content_decider in {}; run the /md2zh configuration wizard".format(path)
        )
    python_path = config.get("python_path")
    if not isinstance(python_path, str) or not python_path:
        raise ConfigRequiredError(
            "missing python_path in {}; run the /md2zh configuration wizard".format(path)
        )
    output_dir = config.get("output_dir")
    if not isinstance(output_dir, str):
        output_dir = ""
    tree_translation = config.get("tree_translation")
    if not isinstance(tree_translation, bool):
        tree_translation = True
    max_block_chars = config.get("max_block_chars")
    if not isinstance(max_block_chars, int) or isinstance(max_block_chars, bool):
        max_block_chars = DEFAULT_MAX_BLOCK_CHARS
    return {
        "ambiguous_content_decider": decider,
        "python_path": python_path,
        "output_dir": output_dir,
        "tree_translation": tree_translation,
        "max_block_chars": max_block_chars,
    }


def ensure_state_runtime(state: Dict[str, Any]) -> None:
    runtime = state.get("runtime")
    executable = runtime.get("executable") if isinstance(runtime, dict) else None
    if not isinstance(executable, str) or not executable:
        raise PythonRuntimeError("translation state does not contain its Python runtime")
    if not same_executable(sys.executable, executable):
        raise PythonRuntimeError(
            "continue this translation with {}; current interpreter is {}".format(
                executable, sys.executable
            )
        )


def default_tools_root() -> Path:
    """日志产物根目录：skill 根目录下的 debug/（skill 根 = scripts 的父目录）。

    旧版为 {项目根}/.md2zh_tools/，2026-08-06 起迁移到 <skill>/debug/。
    """
    return Path(__file__).resolve().parent.parent / "debug"


def state_tools_root(state: Dict[str, Any]) -> Path:
    """state 中记录的日志根目录；旧 state 无 tools_root 时回退 project_root/.md2zh_tools。"""
    root = state.get("tools_root")
    if isinstance(root, str) and root:
        return Path(root).resolve()
    return (Path(state["project_root"]) / ".md2zh_tools").resolve()


def source_relative_path(source: Path, project_root: Path) -> str:
    try:
        return str(source.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(source.resolve())


def split_lines(text: str) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    position = 0
    number = 1
    for match in re.finditer(r"\r\n|\n|\r", text):
        lines.append(
            {
                "number": number,
                "start": position,
                "content_end": match.start(),
                "end": match.end(),
                "content": text[position : match.start()],
                "newline": match.group(0),
            }
        )
        position = match.end()
        number += 1
    if position < len(text) or not lines:
        lines.append(
            {
                "number": number,
                "start": position,
                "content_end": len(text),
                "end": len(text),
                "content": text[position:],
                "newline": "",
            }
        )
    return lines


def is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def find_run_close(text: str, start: int, marker: str) -> int:
    position = text.find(marker, start)
    while position >= 0:
        if not is_escaped(text, position):
            return position
        position = text.find(marker, position + 1)
    return -1


def find_matching_bracket(text: str, opener: int) -> int:
    depth = 1
    index = opener + 1
    while index < len(text):
        if text[index] == "`" and not is_escaped(text, index):
            length = 1
            while index + length < len(text) and text[index + length] == "`":
                length += 1
            marker = "`" * length
            close = find_run_close(text, index + length, marker)
            if close >= 0:
                index = close + length
                continue
        if not is_escaped(text, index):
            if text[index] == "[":
                depth += 1
            elif text[index] == "]":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return -1


def find_balanced_paren(text: str, opener: int) -> int:
    depth = 1
    quote = ""
    index = opener + 1
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote and not is_escaped(text, index):
                quote = ""
        elif char in "\"'" and not is_escaped(text, index):
            quote = char
        elif not is_escaped(text, index):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return -1


def normalize_reference_id(value: str) -> str:
    return " ".join(value.strip().lower().split())


def collect_reference_ids(lines: Sequence[Dict[str, Any]]) -> set:
    result = set()
    for line in lines:
        match = REFERENCE_DEFINITION_RE.match(line["content"])
        if match:
            result.add(normalize_reference_id(match.group(1)))
    return result


def strip_container_prefix(content: str) -> str:
    cursor = min(len(content) - len(content.lstrip(" ")), 3)
    if cursor >= len(content) or content[cursor] != ">":
        return content
    while cursor < len(content) and content[cursor] == ">":
        cursor += 1
        if cursor < len(content) and content[cursor] in " \t":
            cursor += 1
        spaces = 0
        while cursor < len(content) and content[cursor] == " " and spaces < 3:
            cursor += 1
            spaces += 1
    return content[cursor:]


def fence_match(content: str) -> Optional[re.Match[str]]:
    return FENCE_RE.match(strip_container_prefix(content))


def protected_line_indexes(lines: Sequence[Dict[str, Any]]) -> set:
    protected = set()
    if lines and lines[0]["content"].strip() == "---":
        for index in range(len(lines)):
            protected.add(index)
            if index > 0 and lines[index]["content"].strip() in {"---", "..."}:
                break

    fence_char = ""
    fence_length = 0
    display_marker = ""
    html_end = ""
    for index, line in enumerate(lines):
        if index in protected:
            continue
        content = line["content"]
        container_content = strip_container_prefix(content)
        stripped = container_content.strip()
        if fence_char:
            protected.add(index)
            match = fence_match(content)
            if match and match.group(1)[0] == fence_char and len(match.group(1)) >= fence_length and not match.group(2).strip():
                fence_char = ""
                fence_length = 0
            continue
        if display_marker:
            protected.add(index)
            if display_marker in content and not is_escaped(content, content.find(display_marker)):
                display_marker = ""
            continue
        if html_end:
            protected.add(index)
            if html_end in content.lower():
                html_end = ""
            continue

        fence = fence_match(content)
        if fence:
            protected.add(index)
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            continue
        if re.match(r"^( {4}|\t)", container_content):
            protected.add(index)
            continue
        if stripped.startswith("$$") and stripped.count("$$") == 1:
            protected.add(index)
            display_marker = "$$"
            continue
        if stripped.startswith(r"\[") and r"\]" not in stripped[2:]:
            protected.add(index)
            display_marker = r"\]"
            continue
        lowered = container_content.lower()
        for tag in ("script", "style", "pre", "code"):
            if re.search(r"<{}(?:\s|>)".format(tag), lowered):
                protected.add(index)
                if "</{}>".format(tag) not in lowered:
                    html_end = "</{}>".format(tag)
                break
        if index in protected:
            continue
        if "<!--" in container_content:
            protected.add(index)
            if "-->" not in container_content[container_content.find("<!--") + 4 :]:
                html_end = "-->"
            continue
        if THEMATIC_BREAK_RE.match(content) or TABLE_DELIMITER_RE.match(content) or SETEXT_RE.match(content):
            protected.add(index)
            continue
        if REFERENCE_DEFINITION_RE.match(content):
            protected.add(index)
    return protected


def table_row_indexes(lines: Sequence[Dict[str, Any]]) -> set:
    result = set()
    for index, line in enumerate(lines):
        if not TABLE_DELIMITER_RE.match(line["content"]):
            continue
        if index > 0 and "|" in lines[index - 1]["content"]:
            result.add(index - 1)
        cursor = index + 1
        while cursor < len(lines):
            content = lines[cursor]["content"]
            if not content.strip() or "|" not in content:
                break
            result.add(cursor)
            cursor += 1
    return result


def setext_heading_indexes(lines: Sequence[Dict[str, Any]]) -> set:
    return {
        index - 1
        for index, line in enumerate(lines)
        if index > 0 and SETEXT_RE.match(line["content"]) and lines[index - 1]["content"].strip()
    }


def footnote_continuation_indexes(lines: Sequence[Dict[str, Any]]) -> set:
    result = set()
    active = False
    for index, line in enumerate(lines):
        content = line["content"]
        if FOOTNOTE_DEFINITION_RE.match(content):
            active = True
            continue
        if not active:
            continue
        if not content.strip():
            continue
        if re.match(r"^( {4}|\t)", content):
            result.add(index)
            continue
        active = False
    return result


def top_level_pipes(text: str) -> List[int]:
    result: List[int] = []
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "`":
            length = 1
            while index + length < len(text) and text[index + length] == "`":
                length += 1
            marker = "`" * length
            close = find_run_close(text, index + length, marker)
            if close >= 0:
                index = close + length
                continue
        if text.startswith("$$", index):
            close = find_run_close(text, index + 2, "$$")
            if close >= 0:
                index = close + 2
                continue
        matched_math = False
        for opener, closer in ((r"\(", r"\)"), (r"\[", r"\]")):
            if text.startswith(opener, index) and not is_escaped(text, index):
                close = find_run_close(text, index + len(opener), closer)
                if close >= 0:
                    index = close + len(closer)
                    matched_math = True
                    break
        if matched_math:
            continue
        if text[index] == "$" and not is_escaped(text, index):
            close = find_run_close(text, index + 1, "$")
            if close >= 0:
                index = close + 1
                continue
        image = text.startswith("![", index) and not is_escaped(text, index)
        if image or (text[index] == "[" and not is_escaped(text, index)):
            opener = index + 1 if image else index
            close = find_matching_bracket(text, opener)
            if close >= 0:
                after = close + 1
                if after < len(text) and text[after] == "(":
                    target_end = find_balanced_paren(text, after)
                    if target_end >= 0:
                        index = target_end + 1
                        continue
                if after < len(text) and text[after] == "[":
                    ref_end = text.find("]", after + 1)
                    if ref_end >= 0:
                        index = ref_end + 1
                        continue
        if text[index] == "|" and not is_escaped(text, index):
            result.append(index)
        index += 1
    return result


def table_cell_spans(content: str) -> List[Tuple[int, int]]:
    pipes = top_level_pipes(content)
    if not pipes:
        return []
    raw_spans: List[Tuple[int, int]] = []
    start = 0
    for pipe in pipes:
        if pipe == 0 and start == 0:
            start = 1
            continue
        raw_spans.append((start, pipe))
        start = pipe + 1
    if start < len(content):
        raw_spans.append((start, len(content)))
    spans: List[Tuple[int, int]] = []
    for start, end in raw_spans:
        while start < end and content[start] in " \t":
            start += 1
        while end > start and content[end - 1] in " \t":
            end -= 1
        if start < end:
            spans.append((start, end))
    return spans


def line_payload_span(content: str) -> Optional[Tuple[int, int, str, bool]]:
    start = len(content) - len(content.lstrip(" \t"))
    cursor = start
    while True:
        match = re.match(r">[ \t]?", content[cursor:])
        if not match:
            break
        cursor += match.end()
    list_match = re.match(r"(?:[-+*]|\d+[.)])[ \t]+", content[cursor:])
    if list_match:
        cursor += list_match.end()
        task = re.match(r"\[[ xX]\][ \t]+", content[cursor:])
        if task:
            cursor += task.end()
    heading = re.match(r"#{1,6}[ \t]+", content[cursor:])
    is_heading = bool(heading)
    if heading:
        cursor += heading.end()

    end = len(content)
    while end > cursor and content[end - 1] in " \t":
        end -= 1
    if is_heading:
        close = re.search(r"[ \t]+#+$", content[cursor:end])
        if close:
            end = cursor + close.start()
    if end > cursor and content[end - 1] == "\\" and not is_escaped(content, end - 1):
        end -= 1
    if end <= cursor:
        return None
    return cursor, end, "heading" if is_heading else "text", is_heading


def trim_raw_url(value: str) -> str:
    while value and value[-1] in ".,;:!?":
        value = value[:-1]
    while value.endswith(")") and value.count("(") < value.count(")"):
        value = value[:-1]
    return value


def inline_template(
    source_text: str, unit_id: str, reference_ids: set
) -> Tuple[str, List[Dict[str, str]]]:
    tokens: List[Dict[str, str]] = []

    def add_token(value: str, kind: str) -> str:
        short_unit_id = unit_id.rsplit("-", 1)[-1]
        marker = "@@MD2ZH:PROTECT:{}:{}@@".format(short_unit_id, len(tokens) + 1)
        tokens.append({"marker": marker, "value": value, "kind": kind})
        return marker

    def scan(text: str) -> str:
        output: List[str] = []
        index = 0
        while index < len(text):
            if text.startswith("{{", index) and not is_escaped(text, index):
                close = text.find("}}", index + 2)
                if close >= 0:
                    output.append(add_token(text[index : close + 2], "template"))
                    index = close + 2
                    continue
            if text[index] == "`" and not is_escaped(text, index):
                length = 1
                while index + length < len(text) and text[index + length] == "`":
                    length += 1
                marker = "`" * length
                close = find_run_close(text, index + length, marker)
                if close >= 0:
                    output.append(add_token(text[index : close + length], "inline_code"))
                    index = close + length
                    continue
            math_pairs = (("$$", "$$"), (r"\(", r"\)"), (r"\[", r"\]"))
            matched_math = False
            for opener, closer in math_pairs:
                if text.startswith(opener, index) and not is_escaped(text, index):
                    close = find_run_close(text, index + len(opener), closer)
                    if close >= 0:
                        output.append(add_token(text[index : close + len(closer)], "math"))
                        index = close + len(closer)
                        matched_math = True
                        break
            if matched_math:
                continue
            if text[index] == "$" and not is_escaped(text, index):
                close = find_run_close(text, index + 1, "$")
                if close >= 0:
                    output.append(add_token(text[index : close + 1], "math"))
                    index = close + 1
                    continue
            if text[index] == "\\" and index + 1 < len(text):
                output.append(add_token(text[index : index + 2], "escape"))
                index += 2
                continue
            autolink = AUTOLINK_RE.match(text, index)
            if autolink:
                output.append(add_token(autolink.group(0), "autolink"))
                index = autolink.end()
                continue
            comment = HTML_COMMENT_RE.match(text, index)
            if comment:
                output.append(add_token(comment.group(0), "html_comment"))
                index = comment.end()
                continue
            tag = HTML_TAG_RE.match(text, index)
            if tag:
                output.append(add_token(tag.group(0), "html_tag"))
                index = tag.end()
                continue
            entity = ENTITY_RE.match(text, index)
            if entity:
                output.append(add_token(entity.group(0), "entity"))
                index = entity.end()
                continue
            raw_url = RAW_URL_RE.match(text, index)
            if raw_url:
                value = trim_raw_url(raw_url.group(0))
                output.append(add_token(value, "raw_url"))
                index += len(value)
                continue
            image = text.startswith("![", index) and not is_escaped(text, index)
            if image or (text[index] == "[" and not is_escaped(text, index)):
                opener = index + 1 if image else index
                close = find_matching_bracket(text, opener)
                if close >= 0:
                    label_start = opener + 1
                    label = text[label_start:close]
                    after = close + 1
                    if not image and (label.startswith("^") or label.startswith("@")):
                        output.append(add_token(text[index:after], "reference"))
                        index = after
                        continue
                    if after < len(text) and text[after] == "(":
                        target_end = find_balanced_paren(text, after)
                        if target_end >= 0:
                            output.append(add_token(text[index:label_start], "image_open" if image else "link_open"))
                            output.append(scan(label))
                            output.append(add_token(text[close : target_end + 1], "link_target"))
                            index = target_end + 1
                            continue
                    if after < len(text) and text[after] == "[":
                        ref_end = text.find("]", after + 1)
                        if ref_end >= 0:
                            output.append(add_token(text[index:label_start], "image_open" if image else "link_open"))
                            output.append(scan(label))
                            output.append(add_token(text[close : ref_end + 1], "reference_target"))
                            index = ref_end + 1
                            continue
                    if not image and normalize_reference_id(label) in reference_ids:
                        output.append(add_token(text[index:after], "shortcut_reference"))
                        index = after
                        continue
                    output.append(add_token(text[index:label_start], "image_open" if image else "bracket_open"))
                    output.append(scan(label))
                    output.append(add_token(text[close:after], "bracket_close"))
                    index = after
                    continue
            emphasis = None
            for marker in ("***", "___", "**", "__", "~~", "*", "_"):
                if text.startswith(marker, index) and not is_escaped(text, index):
                    emphasis = marker
                    break
            if emphasis:
                output.append(add_token(emphasis, "format"))
                index += len(emphasis)
                continue
            output.append(text[index])
            index += 1
        return "".join(output)

    template = scan(source_text)
    pair_number = 0
    format_stacks: Dict[str, List[Dict[str, str]]] = {}
    structure_stack: List[Dict[str, str]] = []
    for token in tokens:
        if token["kind"] == "format":
            stack = format_stacks.setdefault(token["value"], [])
            if stack:
                opener = stack.pop()
                pair_number += 1
                pair_id = "pair-{}".format(pair_number)
                opener["pair_id"] = pair_id
                opener["pair_role"] = "open"
                token["pair_id"] = pair_id
                token["pair_role"] = "close"
            else:
                stack.append(token)
        elif token["kind"] in {"link_open", "image_open", "bracket_open"}:
            structure_stack.append(token)
        elif token["kind"] in {"link_target", "reference_target", "bracket_close"} and structure_stack:
            opener = structure_stack.pop()
            pair_number += 1
            pair_id = "pair-{}".format(pair_number)
            opener["pair_id"] = pair_id
            opener["pair_role"] = "open"
            token["pair_id"] = pair_id
            token["pair_role"] = "close"
    return template, tokens


def visible_template_text(template: str) -> str:
    return TOKEN_RE.sub("", template)


def make_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def append_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def segment_marker(block_id: str, number: int) -> str:
    return "@@MD2ZH:SEG:{}:{:04d}@@".format(block_id, number)


def translation_block_surface(units: Sequence[Dict[str, Any]], block_id: str) -> str:
    lines: List[str] = []
    for number, unit in enumerate(units, 1):
        lines.append(segment_marker(block_id, number))
        lines.extend(unit["template"].split("\n"))   # 段落 unit 可含多行
    return "\n".join(lines) + ("\n" if lines else "")


def translatable_chars(unit: Dict[str, Any]) -> int:
    """可译字符数 = 模板去除保护标记后的可见文本长度（等待翻译的字符）。"""
    return len(visible_template_text(unit["template"]))


def build_translation_blocks(
    units: Sequence[Dict[str, Any]],
    max_chars: int = DEFAULT_MAX_BLOCK_CHARS,
) -> List[Dict[str, Any]]:
    """Group units into blocks with heading sections as the natural boundary.

    Each heading section (a heading unit plus everything until the next
    heading) becomes its own block when it fits within `max_chars`;
    an over-sized section is split at unit boundaries (paragraph/line
    edges), never inside a unit. The pre-heading file head is its own
    section. Units keep source order.
    """
    if max_chars <= 0:
        raise ValueError("block char budget must be positive")

    # 1) section boundaries: every heading unit starts a new section
    sections: List[Tuple[int, int]] = []
    start = 0
    for index, unit in enumerate(units):
        if unit["kind"] == "heading" and index > start:
            sections.append((start, index))
            start = index
    sections.append((start, len(units)))

    # 2) each section is one group; split only when it exceeds max_chars
    groups: List[List[Dict[str, Any]]] = []
    for section_start, section_end in sections:
        current: List[Dict[str, Any]] = []
        current_chars = 0
        for unit in units[section_start:section_end]:
            unit_chars = translatable_chars(unit)
            if current and current_chars + unit_chars > max_chars:
                groups.append(current)
                current = []
                current_chars = 0
            current.append(unit)
            current_chars += unit_chars
        if current:
            groups.append(current)

    blocks: List[Dict[str, Any]] = []
    for number, group in enumerate(groups, 1):
        block_id = "block-{:04d}".format(number)
        surface = translation_block_surface(group, block_id)
        sections_seen = [unit["section"] for unit in group if unit["section"]]
        blocks.append(
            {
                "id": block_id,
                "unit_ids": [unit["id"] for unit in group],
                "unit_count": len(group),
                "line_start": group[0]["line_start"],
                "line_end": group[-1]["line_end"],
                "section_start": sections_seen[0] if sections_seen else "",
                "section_end": sections_seen[-1] if sections_seen else "",
                "translatable_chars": sum(translatable_chars(unit) for unit in group),
                "surface_bytes": len(surface.encode("utf-8")),
                "surface_sha256": sha256_bytes(surface.encode("utf-8")),
            }
        )
    return blocks


def packet_translation_blocks(
    state_units: Sequence[Dict[str, Any]], blocks: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    units_by_id = {unit["id"]: unit for unit in state_units}
    result: List[Dict[str, Any]] = []
    for block in blocks:
        surface = translation_block_surface(
            [units_by_id[unit_id] for unit_id in block["unit_ids"]], block["id"]
        )
        result.append(
            {
                "id": block["id"],
                "line_start": block["line_start"],
                "line_end": block["line_end"],
                "section_start": block["section_start"],
                "section_end": block["section_end"],
                "unit_count": block["unit_count"],
                "surface_sha256": block["surface_sha256"],
                "surface": surface,
            }
        )
    return result


def extract_files(
    source_path: Path,
    state_path: Path,
    units_path: Path,
    project_root: Path,
    config_path: Optional[Path] = None,
    tools_root: Optional[Path] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    source_path = Path(source_path).resolve(strict=True)
    state_path = Path(state_path)
    units_path = Path(units_path)
    project_root = Path(project_root).resolve(strict=True)
    tools_root = Path(tools_root).resolve() if tools_root else default_tools_root()
    config = load_global_config(config_path)
    runtime = ensure_current_python(config)
    raw = source_path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PipelineError("source must be UTF-8 or UTF-8 with BOM: {}".format(exc)) from exc

    lines = split_lines(text)
    reference_ids = collect_reference_ids(lines)
    protected_lines = protected_line_indexes(lines)
    table_lines = table_row_indexes(lines)
    setext_headings = setext_heading_indexes(lines)
    footnote_continuations = footnote_continuation_indexes(lines)
    protected_lines.difference_update(footnote_continuations)
    units: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    section = ""
    unit_number = 0
    region_number = 0

    def add_unit(start: int, end: int, kind: str, line_number: int, current_section: str) -> Optional[Dict[str, Any]]:
        nonlocal unit_number
        original = text[start:end]
        tentative_id = "unit-{:04d}".format(unit_number + 1)
        template, tokens = inline_template(original, tentative_id, reference_ids)
        if not LATIN_RE.search(visible_template_text(template)):
            return None
        # 裸可见文本中的保留标记字样（非受保护 token 内）必须拒绝；
        # 行内代码/公式等 token 内的标记字样会被整体保护，天然安全。
        unprotected = template
        for token in tokens:
            unprotected = unprotected.replace(token["marker"], "", 1)
        if RESERVED_NAMESPACE_RE.search(unprotected):
            raise PipelineError(
                "source contains the reserved MD2ZH marker namespace in translatable text"
            )
        unit_number += 1
        item = {
            "id": tentative_id,
            "kind": kind,
            "start": start,
            "end": end,
            "line_start": line_number,
            "line_end": line_number,
            "source_text": original,
            "template": template,
            "tokens": tokens,
            "section": current_section,
            "context_before": "",
            "context_after": "",
        }
        units.append(item)
        return item

    paragraph_buffer: Optional[Dict[str, int]] = None

    def flush_paragraph() -> None:
        nonlocal paragraph_buffer
        if paragraph_buffer is not None:
            item = add_unit(
                paragraph_buffer["start"],
                paragraph_buffer["end"],
                "text",
                paragraph_buffer["line_start"],
                section,
            )
            if item:
                item["line_end"] = paragraph_buffer["line_end"]
            paragraph_buffer = None

    for index, line in enumerate(lines):
        content = line["content"]
        if index in protected_lines:
            flush_paragraph()
            continue
        if index in footnote_continuations:
            flush_paragraph()
            leading = len(content) - len(content.lstrip(" \t"))
            end = len(content.rstrip(" \t"))
            if leading < end:
                add_unit(
                    line["start"] + leading,
                    line["start"] + end,
                    "footnote",
                    line["number"],
                    section,
                )
            continue
        footnote = FOOTNOTE_DEFINITION_RE.match(content)
        if footnote:
            flush_paragraph()
            start = line["start"] + len(footnote.group(1))
            end = line["start"] + len(content.rstrip(" \t"))
            if start < end:
                add_unit(start, end, "footnote", line["number"], section)
            continue
        directive = DIRECTIVE_RE.match(content)
        if directive and LATIN_RE.search(directive.group("payload")):
            flush_paragraph()
            region_number += 1
            payload_start = line["start"] + directive.start("payload")
            payload_end = line["start"] + directive.end("payload")
            ambiguous.append(
                {
                    "id": "unknown-{:04d}".format(region_number),
                    "line_start": line["number"],
                    "line_end": line["number"],
                    "source_start": line["start"],
                    "source_end": line["content_end"],
                    "raw_fragment": content,
                    "section": section,
                    "context_before": "",
                    "context_after": "",
                    "suggested_spans": [
                        {
                            "source_start": payload_start,
                            "source_end": payload_end,
                            "text": text[payload_start:payload_end],
                        }
                    ],
                }
            )
            continue
        if index in table_lines:
            flush_paragraph()
            for cell_start, cell_end in table_cell_spans(content):
                add_unit(
                    line["start"] + cell_start,
                    line["start"] + cell_end,
                    "table_cell",
                    line["number"],
                    section,
                )
            continue
        span = line_payload_span(content)
        if not span:
            flush_paragraph()   # 空行/纯结构行 = 段落边界
            continue
        relative_start, relative_end, kind, is_heading = span
        if index in setext_headings:
            kind = "heading"
            is_heading = True
        if kind == "heading":
            flush_paragraph()
            item = add_unit(
                line["start"] + relative_start,
                line["start"] + relative_end,
                kind,
                line["number"],
                section,
            )
            heading_text = content[relative_start:relative_end]
            heading_template, _ = inline_template(heading_text, "section", reference_ids)
            section = visible_template_text(heading_template).strip() or section
            if item:
                item["section"] = section
            continue
        # 普通文本：段落合并——连续文本行组成一个多行 unit
        abs_start = line["start"] + relative_start
        abs_end = line["start"] + relative_end
        if paragraph_buffer is not None and line["start"] == paragraph_buffer["prev_line_end"]:
            paragraph_buffer["end"] = abs_end
            paragraph_buffer["line_end"] = line["number"]
            paragraph_buffer["prev_line_end"] = line["end"]
        else:
            flush_paragraph()
            paragraph_buffer = {
                "start": abs_start,
                "end": abs_end,
                "line_start": line["number"],
                "line_end": line["number"],
                "prev_line_end": line["end"],
            }
    flush_paragraph()

    ordered_context = sorted(
        [(item["start"], item["template"]) for item in units]
        + [(item["source_start"], item["raw_fragment"]) for item in ambiguous],
        key=lambda pair: pair[0],
    )

    def context_at(position: int) -> Tuple[str, str]:
        before = ""
        after = ""
        for item_position, value in ordered_context:
            if item_position < position:
                before = value
            elif item_position > position:
                after = value
                break
        return before, after

    for item in units:
        item["context_before"], item["context_after"] = context_at(item["start"])
    for item in ambiguous:
        item["context_before"], item["context_after"] = context_at(item["source_start"])

    timestamp = timestamp or make_timestamp()
    source_hash = sha256_bytes(raw)
    log_directory = Path("decision_logs")
    log_name = "{}.{}.{}.jsonl".format(source_path.stem, source_hash[:8], timestamp)
    log_relative = log_directory / log_name
    log_path = tools_root / log_relative
    suffix = 2
    while log_path.exists():
        log_name = "{}.{}.{}.{}.jsonl".format(source_path.stem, source_hash[:8], timestamp, suffix)
        log_relative = log_directory / log_name
        log_path = tools_root / log_relative
        suffix += 1
    append_jsonl(
        log_path,
        [
            {
                "schema_version": 1,
                "event": "run_started",
                "timestamp": timestamp,
                "source_path": source_relative_path(source_path, project_root),
                "source_sha256": source_hash,
                "decision_source": config["ambiguous_content_decider"],
                "ambiguous_count": len(ambiguous),
            }
        ],
    )

    state_units = sorted(units, key=lambda item: item["start"])
    translation_blocks = build_translation_blocks(
        state_units, max_chars=config["max_block_chars"]
    )
    state = {
        "schema_version": 4,
        "project_root": str(project_root),
        "tools_root": str(tools_root),
        "source": {
            "path": str(source_path),
            "relative_path": source_relative_path(source_path, project_root),
            "sha256": source_hash,
            "bom": bom,
        },
        "config": config,
        "runtime": {
            "executable": runtime["executable"],
            "version": runtime["version"],
        },
        "decision_log": log_relative.as_posix(),
        "units": state_units,
        "translation_blocks": translation_blocks,
        "ambiguous_regions": ambiguous,
    }
    packet = {
        "schema_version": 3,
        "source": {
            "relative_path": state["source"]["relative_path"],
            "sha256": source_hash,
        },
        "ambiguous_content_decider": config["ambiguous_content_decider"],
        "blocks_are_in_source_order": True,
        "translation_blocks": packet_translation_blocks(state_units, translation_blocks),
        "ambiguous_regions": ambiguous,
        "translation_contract": {
            "translate_one_complete_block_surface_at_a_time": True,
            "preserve_each_segment_line_in_order": True,
            "preserve_each_md2zh_marker_once": True,
            "do_not_add_markdown_syntax": True,
        },
    }
    write_json_atomic(state_path, state)
    write_json_atomic(units_path, packet)
    return {
        "state": str(state_path),
        "units": str(units_path),
        "unit_count": len(units),
        "block_count": len(translation_blocks),
        "ambiguous_count": len(ambiguous),
        "max_block_chars": config["max_block_chars"],
        "decision_log": str(log_path),
    }


def decision_log_path(state: Dict[str, Any]) -> Path:
    return state_tools_root(state) / Path(state["decision_log"])


def validate_decision(
    state: Dict[str, Any], region: Dict[str, Any], decision: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    choice = decision.get("decision")
    spans = decision.get("selected_spans", [])
    if choice not in {"translate", "protect"}:
        errors.append("decision must be 'translate' or 'protect'")
        return errors
    if not isinstance(spans, list):
        errors.append("selected_spans must be a list")
        return errors
    if choice == "protect" and spans:
        errors.append("protect decisions must not select translation spans")
    if choice == "translate" and not spans:
        errors.append("translate decisions must select at least one span")

    source_raw = Path(state["source"]["path"]).read_bytes()
    text = source_raw.decode("utf-8-sig")
    allowed = region["suggested_spans"]
    previous_end = -1
    for index, span in enumerate(sorted(spans, key=lambda item: item.get("source_start", -1))):
        try:
            start = int(span["source_start"])
            end = int(span["source_end"])
            value = span["text"]
        except (KeyError, TypeError, ValueError):
            errors.append("selected span {} is malformed".format(index + 1))
            continue
        if start < previous_end:
            errors.append("selected spans overlap")
        previous_end = end
        if start >= end or text[start:end] != value:
            errors.append("selected span {} does not match the immutable source".format(index + 1))
            continue
        if not any(start >= item["source_start"] and end <= item["source_end"] for item in allowed):
            errors.append("selected span {} crosses protected directive syntax".format(index + 1))
    return errors


def record_decisions(state_path: Path, decisions_path: Path) -> Dict[str, int]:
    state = load_json(Path(state_path))
    ensure_state_runtime(state)
    raw = Path(state["source"]["path"]).read_bytes()
    if sha256_bytes(raw) != state["source"]["sha256"]:
        raise PipelineError("source changed after extraction")
    payload = load_json(Path(decisions_path))
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list):
        raise DecisionValidationError("decisions file must contain a decisions list")
    regions = {item["id"]: item for item in state["ambiguous_regions"]}
    log_path = decision_log_path(state)
    attempt_counts: Dict[str, int] = {}
    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("event") == "ambiguity_decision" and event.get("region_id"):
                    region_id = event["region_id"]
                    attempt_counts[region_id] = max(
                        attempt_counts.get(region_id, 0), int(event.get("attempt", 0))
                    )
    records: List[Dict[str, Any]] = []
    rejected = 0
    passed = 0
    for decision in decisions:
        region_id = decision.get("region_id") if isinstance(decision, dict) else None
        attempt = attempt_counts.get(region_id, 0) + 1
        if region_id:
            attempt_counts[region_id] = attempt
        region = regions.get(region_id)
        errors = ["unknown region_id"] if not region else validate_decision(state, region, decision)
        status = "rejected" if errors else "passed"
        if errors:
            rejected += 1
        else:
            passed += 1
        record: Dict[str, Any] = {
            "schema_version": 1,
            "event": "ambiguity_decision",
            "attempt": attempt,
            "source_path": state["source"]["relative_path"],
            "source_sha256": state["source"]["sha256"],
            "region_id": region_id,
            "decision_source": state["config"]["ambiguous_content_decider"],
            "decision": decision.get("decision") if isinstance(decision, dict) else None,
            "reason": decision.get("reason", "") if isinstance(decision, dict) else "",
            "selected_spans": decision.get("selected_spans", []) if isinstance(decision, dict) else [],
            "validation_status": status,
            "validation_errors": errors,
            "applied": not errors,
        }
        if region:
            record.update(
                {
                    "line_start": region["line_start"],
                    "line_end": region["line_end"],
                    "section": region["section"],
                    "raw_fragment": region["raw_fragment"],
                    "context_before": region["context_before"],
                    "context_after": region["context_after"],
                }
            )
        records.append(record)
    append_jsonl(log_path, records)
    if rejected:
        raise DecisionValidationError("{} ambiguity decision(s) rejected; details were logged".format(rejected))
    return {"passed": passed, "rejected": rejected}


def load_translation_map(path: Path) -> Dict[str, str]:
    payload = load_json(Path(path))
    translations = payload.get("translations") if isinstance(payload, dict) else None
    if not isinstance(translations, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in translations.items()):
        raise TranslationValidationError("translations file must contain a string-to-string translations object")
    return translations


def path_is_within(path: Path, parent: Path) -> bool:
    path = Path(path).resolve()
    parent = Path(parent).resolve()
    try:
        return os.path.commonpath((str(path), str(parent))) == str(parent)
    except ValueError:
        return False


def state_block_surface(state: Dict[str, Any], block: Dict[str, Any]) -> str:
    units_by_id = {unit["id"]: unit for unit in state["units"]}
    try:
        units = [units_by_id[unit_id] for unit_id in block["unit_ids"]]
    except KeyError as exc:
        raise PipelineError("translation block references an unknown unit: {}".format(exc)) from exc
    surface = translation_block_surface(units, block["id"])
    if sha256_bytes(surface.encode("utf-8")) != block["surface_sha256"]:
        raise PipelineError("translation block surface hash mismatch for {}".format(block["id"]))
    return surface


def block_plan_fingerprint(state: Dict[str, Any]) -> str:
    payload = {
        "source_sha256": state["source"]["sha256"],
        "blocks": [
            {
                "id": block["id"],
                "unit_ids": block["unit_ids"],
                "surface_sha256": block["surface_sha256"],
            }
            for block in state.get("translation_blocks", [])
        ],
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))


def plan_blocks(state_path: Path, run_dir: Path) -> Path:
    state_path = Path(state_path).resolve(strict=True)
    state = load_json(state_path)
    ensure_state_runtime(state)
    run_dir = Path(run_dir).resolve()
    intermediate_root = (state_tools_root(state) / "intermediate").resolve()
    if run_dir == intermediate_root or not path_is_within(run_dir, intermediate_root):
        raise PipelineError("block run directory must be a child of the tools intermediate directory")

    plan_sha256 = block_plan_fingerprint(state)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        if (
            manifest.get("source_sha256") != state["source"]["sha256"]
            or manifest.get("plan_sha256") != plan_sha256
            or Path(manifest.get("state_path", "")).resolve() != state_path
        ):
            raise PipelineError("existing block run belongs to a different extraction plan")
    else:
        if run_dir.exists() and any(run_dir.iterdir()):
            raise PipelineError("block run directory is not empty and has no manifest")
        blocks = []
        for block in state.get("translation_blocks", []):
            block_id = block["id"]
            blocks.append(
                {
                    "id": block_id,
                    "unit_count": block["unit_count"],
                    "line_start": block["line_start"],
                    "line_end": block["line_end"],
                    "surface_sha256": block["surface_sha256"],
                    "input_file": "blocks/{}.input.txt".format(block_id),
                    "output_file": "blocks/{}.output.txt".format(block_id),
                    "accepted_file": "blocks/{}.accepted.json".format(block_id),
                    "status": "pending",
                    "attempts": 0,
                    "revisions": 0,
                    "last_error": "",
                }
            )
        manifest = {
            "schema_version": 1,
            "source_sha256": state["source"]["sha256"],
            "state_path": str(state_path),
            "plan_sha256": plan_sha256,
            "max_attempts_per_block": MAX_BLOCK_ATTEMPTS,
            "blocks": blocks,
        }

    state_blocks = {block["id"]: block for block in state.get("translation_blocks", [])}
    for block in manifest["blocks"]:
        expected = state_block_surface(state, state_blocks[block["id"]]).encode("utf-8")
        input_path = run_dir / block["input_file"]
        if not input_path.exists() or input_path.read_bytes() != expected:
            write_bytes_atomic(input_path, expected)
        if block["status"] == "accepted" and not (run_dir / block["accepted_file"]).exists():
            raise PipelineError("accepted result is missing for {}".format(block["id"]))
    write_json_atomic(manifest_path, manifest)
    return manifest_path


def manifest_block(manifest: Dict[str, Any], block_id: str) -> Dict[str, Any]:
    matches = [block for block in manifest.get("blocks", []) if block.get("id") == block_id]
    if len(matches) != 1:
        raise PipelineError("unknown or duplicated block id: {}".format(block_id))
    return matches[0]


def parse_block_surface(
    state: Dict[str, Any], block: Dict[str, Any], translated_surface: str
) -> Dict[str, str]:
    if MOJIBAKE_RE.search(translated_surface):
        raise TranslationValidationError("{} contains likely mojibake".format(block["id"]))
    lines = translated_surface.splitlines()
    units_by_id = {unit["id"]: unit for unit in state["units"]}
    translations: Dict[str, str] = {}
    position = 0
    for index, unit_id in enumerate(block["unit_ids"]):
        marker = segment_marker(block["id"], index + 1)
        if position >= len(lines) or lines[position] != marker:
            raise TranslationValidationError(
                "{} must preserve segment lines in source order".format(block["id"])
            )
        position += 1
        content_lines: List[str] = []
        while position < len(lines) and not SEGMENT_LINE_RE.match(lines[position]):
            content_lines.append(lines[position])
            position += 1
        translated = "\n".join(content_lines)
        if not translated.strip():
            raise TranslationValidationError("{} has an empty translation".format(unit_id))
        if SEGMENT_ANY_RE.search(translated):
            raise TranslationValidationError("{} contains a misplaced segment marker".format(unit_id))
        if "\n\n" in translated or translated.startswith("\n") or translated.endswith("\n"):
            raise TranslationValidationError(
                "{} must not change paragraph boundaries (no blank lines)".format(unit_id)
            )
        validate_translated_template(units_by_id[unit_id], translated)
        translations[unit_id] = translated
    if position < len(lines) and any(lines[j].strip() for j in range(position, len(lines))):
        raise TranslationValidationError(
            "{} has extra content after the last segment".format(block["id"])
        )
    return translations


def validate_block(
    state_path: Path,
    manifest_path: Path,
    block_id: str,
    output_path: Optional[Path] = None,
    replace_accepted: bool = False,
) -> Dict[str, Any]:
    state = load_json(Path(state_path))
    ensure_state_runtime(state)
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = load_json(manifest_path)
    if manifest.get("source_sha256") != state["source"]["sha256"]:
        raise PipelineError("manifest source does not match state")
    block = manifest_block(manifest, block_id)
    run_dir = manifest_path.parent
    accepted_path = run_dir / block["accepted_file"]
    was_accepted = block["status"] == "accepted"
    if was_accepted and not replace_accepted:
        if not accepted_path.exists():
            raise PipelineError("accepted result is missing for {}".format(block_id))
        return {"block": block_id, "status": "accepted", "attempts": block["attempts"]}
    if not was_accepted and block["attempts"] >= manifest["max_attempts_per_block"]:
        raise TranslationValidationError("{} exhausted its two correction rounds".format(block_id))

    output_path = Path(output_path) if output_path else run_dir / block["output_file"]
    try:
        raw = output_path.read_bytes()
        translated_surface = raw.decode("utf-8-sig")
        state_blocks = {item["id"]: item for item in state["translation_blocks"]}
        translations = parse_block_surface(state, state_blocks[block_id], translated_surface)
    except (OSError, UnicodeDecodeError, KeyError, PipelineError) as exc:
        if not was_accepted:
            block["attempts"] += 1
            block["status"] = "failed"
        block["last_error"] = str(exc)
        write_json_atomic(manifest_path, manifest)
        if isinstance(exc, TranslationValidationError):
            raise
        raise TranslationValidationError("{} output is invalid: {}".format(block_id, exc)) from exc

    if was_accepted:
        block["revisions"] = block.get("revisions", 0) + 1
    else:
        block["attempts"] += 1
    block["status"] = "accepted"
    block["last_error"] = ""
    accepted = {
        "schema_version": 1,
        "block_id": block_id,
        "source_sha256": state["source"]["sha256"],
        "surface_sha256": block["surface_sha256"],
        "output_sha256": sha256_bytes(raw),
        "translations": translations,
    }
    write_json_atomic(accepted_path, accepted)
    expected_output_path = run_dir / block["output_file"]
    if output_path.resolve() != expected_output_path.resolve():
        write_bytes_atomic(expected_output_path, raw)
    write_json_atomic(manifest_path, manifest)
    return {
        "block": block_id,
        "status": "accepted",
        "attempts": block["attempts"],
        "revisions": block.get("revisions", 0),
    }


def merge_blocks(
    state_path: Path,
    manifest_path: Path,
    translations_path: Path,
    extra_translations_path: Optional[Path] = None,
) -> Dict[str, Any]:
    state = load_json(Path(state_path))
    ensure_state_runtime(state)
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = load_json(manifest_path)
    if manifest.get("source_sha256") != state["source"]["sha256"]:
        raise PipelineError("manifest source does not match state")
    run_dir = manifest_path.parent
    translations: Dict[str, str] = {}
    units_by_id = {unit["id"]: unit for unit in state["units"]}
    for block in manifest["blocks"]:
        if block["status"] != "accepted":
            raise TranslationValidationError("{} has not been accepted".format(block["id"]))
        accepted = load_json(run_dir / block["accepted_file"])
        if (
            accepted.get("block_id") != block["id"]
            or accepted.get("source_sha256") != state["source"]["sha256"]
            or accepted.get("surface_sha256") != block["surface_sha256"]
        ):
            raise PipelineError("accepted result does not match {}".format(block["id"]))
        for unit_id, value in accepted.get("translations", {}).items():
            if unit_id in translations or unit_id not in units_by_id:
                raise TranslationValidationError("unexpected or duplicated translation id: {}".format(unit_id))
            validate_translated_template(units_by_id[unit_id], value)
            translations[unit_id] = value
    expected_units = set(units_by_id)
    if set(translations) != expected_units:
        missing = sorted(expected_units - set(translations))
        raise TranslationValidationError("merged blocks are missing units: {}".format(missing[:10]))
    if extra_translations_path:
        extras = load_translation_map(Path(extra_translations_path))
        overlap = sorted(set(extras) & set(translations))
        if overlap:
            raise TranslationValidationError("extra translations duplicate unit ids: {}".format(overlap[:10]))
        translations.update(extras)
    write_json_atomic(Path(translations_path), {"translations": translations})
    return {
        "translations": str(Path(translations_path)),
        "translation_count": len(translations),
        "block_count": len(manifest["blocks"]),
    }


def cleanup_run(manifest_path: Path) -> Dict[str, Any]:
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = load_json(manifest_path)
    state_path = Path(manifest.get("state_path", "")).resolve(strict=True)
    state = load_json(state_path)
    run_dir = manifest_path.parent
    task_dir = run_dir.parent
    intermediate_root = (state_tools_root(state) / "intermediate").resolve()
    if (
        manifest_path.name != "manifest.json"
        or run_dir.name != "run"
        or task_dir.parent != intermediate_root
        or not path_is_within(state_path, task_dir)
    ):
        raise PipelineError("refusing to clean an invalid block run path")
    if not path_is_within(run_dir, task_dir):
        raise PipelineError("refusing to clean a block run outside the tools intermediate directory")
    unfinished = [block["id"] for block in manifest.get("blocks", []) if block["status"] != "accepted"]
    if unfinished:
        raise PipelineError("refusing to clean an unfinished block run: {}".format(unfinished[:10]))
    # 归档而不是删除（web2md 风格，便于排查）：移入 .md2zh_tools/_archive/
    archive_root = intermediate_root.parent / "_archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / task_dir.name
    if target.exists():
        shutil.rmtree(str(target))
    shutil.move(str(task_dir), str(target))
    # 只保留最近 20 个归档条目，超出删最旧
    entries = sorted(archive_root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in entries[ARCHIVE_MAX_ENTRIES:]:
        shutil.rmtree(str(old))
    return {"archived": str(target), "exists_after": task_dir.exists()}


def accepted_decisions(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    log_path = decision_log_path(state)
    if not log_path.exists():
        return result
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event") == "ambiguity_decision" and event.get("validation_status") == "passed":
                result[event["region_id"]] = event
    return result


def validate_translated_template(unit: Dict[str, Any], translated: str) -> str:
    expected = [token["marker"] for token in unit["tokens"]]
    actual = TOKEN_RE.findall(translated)
    if Counter(actual) != Counter(expected):
        raise TranslationValidationError("{} must preserve every protection marker exactly once".format(unit["id"]))
    marker_positions = {marker: index for index, marker in enumerate(actual)}
    pairs: Dict[str, Dict[str, int]] = {}
    for token in unit["tokens"]:
        pair_id = token.get("pair_id")
        pair_role = token.get("pair_role")
        if pair_id and pair_role:
            pairs.setdefault(pair_id, {})[pair_role] = marker_positions[token["marker"]]
    intervals: List[Tuple[int, int]] = []
    for pair_id, positions in pairs.items():
        if set(positions) != {"open", "close"} or positions["open"] >= positions["close"]:
            raise TranslationValidationError("{} broke protected marker pair {}".format(unit["id"], pair_id))
        intervals.append((positions["open"], positions["close"]))
    for first_index, (left_open, left_close) in enumerate(intervals):
        for right_open, right_close in intervals[first_index + 1 :]:
            if left_open < right_open < left_close < right_close or right_open < left_open < right_close < left_close:
                raise TranslationValidationError("{} crossed protected marker pairs".format(unit["id"]))
    visible = TOKEN_RE.sub("", translated)
    original_visible = TOKEN_RE.sub("", unit["template"])
    validate_no_introduced_syntax(original_visible, visible, unit["id"], unit["kind"])
    rendered = translated
    for token in unit["tokens"]:
        rendered = rendered.replace(token["marker"], token["value"])
    if TOKEN_RE.search(rendered):
        raise TranslationValidationError("{} contains an unknown protection marker".format(unit["id"]))
    return rendered


def validate_no_introduced_syntax(original: str, translated: str, label: str, kind: str = "text") -> None:
    original_counts = Counter(DANGEROUS_TRANSLATION_RE.findall(original))
    translated_counts = Counter(DANGEROUS_TRANSLATION_RE.findall(translated))
    if any(count > original_counts[marker] for marker, count in translated_counts.items()):
        raise TranslationValidationError("{} introduced Markdown syntax outside protected markers".format(label))
    for marker in ("{{", "}}", "~~"):
        if translated.count(marker) > original.count(marker):
            raise TranslationValidationError("{} introduced Markdown syntax outside protected markers".format(label))
    block_pattern = re.compile(r"^(?:#{1,6}[ \t]+|[-+][ \t]+|>[ \t]?|\d+[.)][ \t]+)")
    if kind == "text":
        translated_lines = translated.split("\n")
        original_lines = original.split("\n")
        if any(block_pattern.match(tline) for tline in translated_lines) and not any(
            block_pattern.match(oline) for oline in original_lines
        ):
            raise TranslationValidationError("{} introduced a block-level Markdown marker".format(label))


def line_ending_style(text: str) -> str:
    """行尾风格：源区间使用 \\r\\n 还是 \\n（取第一个出现的换行）。"""
    crlf = text.find("\r\n")
    lf = text.find("\n")
    if crlf >= 0 and (lf < 0 or crlf <= lf):
        return "\r\n"
    return "\n"


def deterministic_render(state: Dict[str, Any], translations: Dict[str, str]) -> bytes:
    source_path = Path(state["source"]["path"])
    raw = source_path.read_bytes()
    if sha256_bytes(raw) != state["source"]["sha256"]:
        raise PipelineError("source changed after extraction")
    text = raw.decode("utf-8-sig")
    replacements: List[Tuple[int, int, str, str]] = []
    expected_translation_ids = set()
    for unit in state["units"]:
        unit_id = unit["id"]
        expected_translation_ids.add(unit_id)
        if unit_id not in translations:
            raise TranslationValidationError("missing translation for {}".format(unit_id))
        value = validate_translated_template(unit, translations[unit_id])
        if "\n" in value:
            style = line_ending_style(text[unit["start"] : unit["end"]])
            if style != "\n":
                value = value.replace("\n", style)
        replacements.append((unit["start"], unit["end"], value, unit_id))

    decisions = accepted_decisions(state)
    for region in state["ambiguous_regions"]:
        decision = decisions.get(region["id"])
        if not decision:
            raise TranslationValidationError("missing accepted decision for {}".format(region["id"]))
        if decision["decision"] == "protect":
            continue
        for index, span in enumerate(decision["selected_spans"]):
            translation_id = "{}:{}".format(region["id"], index)
            expected_translation_ids.add(translation_id)
            if translation_id not in translations:
                raise TranslationValidationError("missing translation for {}".format(translation_id))
            value = translations[translation_id]
            if "\r" in value or "\n" in value or TOKEN_RE.search(value):
                raise TranslationValidationError("{} contains forbidden structure".format(translation_id))
            validate_no_introduced_syntax(span["text"], value, translation_id)
            replacements.append((span["source_start"], span["source_end"], value, translation_id))

    unexpected = sorted(set(translations) - expected_translation_ids)
    if unexpected:
        raise TranslationValidationError("unexpected translation ids: {}".format(unexpected[:10]))

    replacements.sort(key=lambda item: (item[0], item[1]))
    previous_end = -1
    for start, end, _value, label in replacements:
        if start < previous_end:
            raise PipelineError("translation ranges overlap at {}".format(label))
        if start < 0 or end < start or end > len(text):
            raise PipelineError("translation range is outside source at {}".format(label))
        previous_end = end
    rendered = text
    for start, end, value, _label in reversed(replacements):
        rendered = rendered[:start] + value + rendered[end:]
    if TOKEN_RE.search(rendered):
        raise TranslationValidationError("rendered candidate contains a protection marker")
    result = rendered.encode("utf-8")
    if state["source"]["bom"]:
        result = b"\xef\xbb\xbf" + result
    return result


def render_file(
    state_path: Path,
    translations_path: Path,
    output_path: Path,
    allow_overwrite: bool = False,
) -> Dict[str, Any]:
    state = load_json(Path(state_path))
    ensure_state_runtime(state)
    output_path = Path(output_path)
    if output_path.resolve() == Path(state["source"]["path"]).resolve():
        raise PipelineError("render output must not be the source file")
    if output_path.exists() and not allow_overwrite:
        raise PipelineError("render output already exists; explicit overwrite permission is required")
    translations = load_translation_map(Path(translations_path))
    rendered = deterministic_render(state, translations)
    write_bytes_atomic(output_path, rendered)
    return {
        "output": str(output_path),
        "sha256": sha256_bytes(rendered),
        "bytes": len(rendered),
    }


def verify_file(state_path: Path, translations_path: Path, output_path: Path) -> Dict[str, Any]:
    errors: List[str] = []
    try:
        state = load_json(Path(state_path))
        ensure_state_runtime(state)
        translations = load_translation_map(Path(translations_path))
        expected = deterministic_render(state, translations)
        actual = Path(output_path).read_bytes()
        if actual != expected:
            errors.append("candidate does not match deterministic render")
        if TOKEN_RE.search(actual.decode("utf-8-sig")):
            errors.append("candidate contains a protection marker")
    except (OSError, ValueError, PipelineError) as exc:
        errors.append(str(exc))
    return {"pass": not errors, "errors": errors, "failure_count": len(errors)}


def copy_assets(source_path: Path, output_path: Path) -> Dict[str, Any]:
    """Copy the source's sibling `<stem>.assets` folder next to an output file.

    Markdown image references stay relative to the source file name
    (e.g. `![](Guide.assets/x.png)`), so the copied folder keeps the
    source stem. A missing assets folder is not an error.
    """
    source_path = Path(source_path).resolve()
    assets_dir = source_path.parent / (source_path.stem + ".assets")
    if not assets_dir.is_dir():
        return {"source": str(assets_dir), "target": None, "copied": False, "files": 0}
    target_dir = Path(output_path).resolve().parent / (source_path.stem + ".assets")
    shutil.copytree(str(assets_dir), str(target_dir), dirs_exist_ok=True)
    file_count = sum(1 for item in assets_dir.rglob("*") if item.is_file())
    return {
        "source": str(assets_dir),
        "target": str(target_dir),
        "copied": True,
        "files": file_count,
    }


def summarize_document(state_path: Path, summary_path: Path) -> Dict[str, Any]:
    """Write a structure summary md: heading tree, per-section translatable
    char counts, code/math block positions, and the default block plan.

    The summary is the AI planner's input: it confirms the default plan or
    gives adjustment instructions before `plan-blocks`.
    """
    state = load_json(Path(state_path))
    ensure_state_runtime(state)
    source_path = Path(state["source"]["path"])
    raw = source_path.read_bytes()
    if sha256_bytes(raw) != state["source"]["sha256"]:
        raise PipelineError("source changed after extraction")
    text = raw.decode("utf-8-sig")
    max_chars = state["config"].get("max_block_chars", DEFAULT_MAX_BLOCK_CHARS)

    # 1) 扫描标题（ATX + setext）与代码围栏区间
    lines = split_lines(text)
    setext_indexes = setext_heading_indexes(lines)
    headings: List[Dict[str, Any]] = []
    fences: List[Tuple[int, int]] = []
    in_fence: Optional[str] = None
    fence_start = 0
    for index, line in enumerate(lines):
        content = line["content"]
        fence = FENCE_RE.match(content)
        if in_fence is not None:
            if fence and fence.group(1)[0] == in_fence[0] and len(fence.group(1)) >= len(in_fence):
                fences.append((fence_start, line["end"]))
                in_fence = None
            continue
        if fence:
            in_fence = fence.group(1)
            fence_start = line["start"]
            continue
        if index in setext_indexes:
            title = content.strip()
            next_content = lines[index + 1]["content"] if index + 1 < len(lines) else ""
            setext_match = SETEXT_RE.match(next_content)
            level = 1 if setext_match and setext_match.group(1).startswith("=") else 2
            if title:
                headings.append(
                    {
                        "level": level,
                        "text": title,
                        "start": line["start"],
                        "line": line["number"],
                    }
                )
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.*)$", content)
        if heading:
            level = len(heading.group(1))
            title = re.sub(r"[ \t]+#+$", "", heading.group(2).rstrip())
            headings.append(
                {
                    "level": level,
                    "text": title,
                    "start": line["start"],
                    "line": line["number"],
                }
            )
            continue
    if in_fence is not None:
        fences.append((fence_start, len(text)))

    # 公式块（$$...$$ 配对区间，近似统计）
    math_blocks: List[Tuple[int, int]] = []
    positions = [match.start() for match in re.finditer(r"\$\$", text)]
    for index in range(0, len(positions) - 1, 2):
        math_blocks.append((positions[index], positions[index + 1] + 2))

    # 2) 每个 unit 归属最近的标题节点（无标题 → 文件头节点）
    nodes: List[Dict[str, Any]] = [
        {"level": 0, "text": "(无标题头部)", "start": 0}
    ] + headings
    node_chars = [0] * len(nodes)
    for unit in state["units"]:
        owner = 0
        for index, node in enumerate(nodes):
            if node["start"] <= unit["start"]:
                owner = index
            else:
                break
        node_chars[owner] += translatable_chars(unit)

    # 3) 汇总统计
    total_chars = sum(node_chars)
    heading_counts = {1: 0, 2: 0, 3: 0}
    for heading in headings:
        if heading["level"] in heading_counts:
            heading_counts[heading["level"]] += 1
    fence_chars = sum(end - start for start, end in fences)
    math_chars = sum(end - start for start, end in math_blocks)
    blocks = state.get("translation_blocks", [])

    # 4) 章节行（≤3 级显示；4+ 级字符并入最近的 ≤3 级父节点）
    section_chars: Dict[int, int] = {}
    last_l3 = 0
    for index, node in enumerate(nodes):
        if node["level"] <= 3:
            last_l3 = index
            section_chars[index] = node_chars[index]
        else:
            section_chars[last_l3] = section_chars.get(last_l3, 0) + node_chars[index]
    section_lines: List[str] = []
    numbering = {1: 0, 2: 0, 3: 0}
    for index, node in enumerate(nodes):
        level = node["level"]
        if level > 3:
            continue
        chars = section_chars.get(index, 0)
        status = "✅ 整块" if chars <= max_chars else "⚠️ 超限需拆"
        prefix = ""
        if level >= 1:
            numbering[level] += 1
            numbering = {key: (numbering[key] if key <= level else 0) for key in numbering}
            prefix = ".".join(str(numbering[key]) for key in range(1, level + 1))
            line = "### {}{}. {}（{} 级，{} 字符）{}".format(
                "  " * (level - 1), prefix, node["text"], level, chars, status
            )
        else:
            line = "### {}（{} 字符）{}".format(node["text"], chars, status)
        section_lines.append(line)

    # 5) 默认分块方案表
    plan_lines = [
        "| 块 | 章节范围 | 可译字符 | 状态 |",
        "|---|---|---|---|",
    ]
    for block in blocks:
        section = block.get("section_start") or "(无标题)"
        if len(section) > 40:
            section = section[:37] + "..."
        chars = block.get("translatable_chars", 0)
        status = "✅ ≤ 上限" if chars <= max_chars else "⚠️ 超限"
        plan_lines.append(
            "| {} | {} | {} | {} |".format(block["id"], section, chars, status)
        )

    summary = "\n".join(
        [
            "# 分块结构摘要 — {}（共 {} 可译字符）".format(source_path.name, total_chars),
            "",
            "## 总体",
            "- 标题：{} 个一级 / {} 个二级 / {} 个三级（四级及以下计入最近父级）".format(
                heading_counts[1], heading_counts[2], heading_counts[3]
            ),
            "- 总可译字符：{}（等待翻译的字符，不含代码/公式/链接目标等保护内容）".format(total_chars),
            "- 代码块：{} 个（共 {} 字符）｜公式块：{} 个（共 {} 字符）——保护区间，不参与翻译".format(
                len(fences), fence_chars, len(math_blocks), math_chars
            ),
            "- 分块上限 max_block_chars：{} 字符".format(max_chars),
            "- 分块数：{} 块".format(len(blocks)),
            "",
            "## 章节统计",
        ]
        + section_lines
        + [
            "",
            "## 默认分块方案",
            "",
        ]
        + plan_lines
        + [
            "",
            "> AI 审阅：确认默认方案直接进入 plan-blocks；如需调整（如大章节拆点、紧邻小章节合并），给出调整指令。",
        ]
    ) + "\n"
    write_bytes_atomic(Path(summary_path), summary.encode("utf-8"))
    return {
        "summary": str(Path(summary_path)),
        "headings": len(headings),
        "blocks": len(blocks),
        "total_chars": total_chars,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        help="path to the md2zh config file (default: <skill>/scripts/config.py)",
    )

    configure = subparsers.add_parser(
        "configure",
        parents=[common],
        help="store the ambiguity decider, Python runtime and output dir in the skill-level config",
    )
    configure.add_argument("--decider", choices=sorted(CONFIG_VALUES), required=True)
    configure.add_argument(
        "--python-path",
        help="absolute path to the Python interpreter; omitted = auto-detect",
    )
    configure.add_argument(
        "--output-dir",
        help="output directory for translated files; empty = same directory as the source",
    )
    configure.add_argument(
        "--tree-translation",
        choices=["true", "false"],
        help="enable tree translation for multi-file directories (default: true)",
    )
    configure.add_argument(
        "--max-block-chars",
        type=int,
        help="max translatable characters per block (default: 16000, suggested 10000-24000)",
    )

    extract = subparsers.add_parser(
        "extract",
        parents=[common],
        help="extract translator-facing translation blocks",
    )
    extract.add_argument("source")
    extract.add_argument("--state", required=True)
    extract.add_argument("--blocks", "--units", dest="units", required=True)
    extract.add_argument("--project-root", required=True)
    extract.add_argument(
        "--tools-root",
        help="tools/log root directory (default: <skill>/debug); internal override for tests",
    )

    summarize = subparsers.add_parser(
        "summarize",
        help="write a structure summary md for the AI block planner",
    )
    summarize.add_argument("state")
    summarize.add_argument("output")

    decisions = subparsers.add_parser("record-decisions", help="validate and persist ambiguity decisions")
    decisions.add_argument("state")
    decisions.add_argument("decisions")

    plan = subparsers.add_parser("plan-blocks", help="create or resume a block translation run")
    plan.add_argument("state")
    plan.add_argument("run_dir")

    validate = subparsers.add_parser("validate-block", help="validate and accept one translated block")
    validate.add_argument("state")
    validate.add_argument("manifest")
    validate.add_argument("block_id")
    validate.add_argument("--output")
    validate.add_argument("--replace-accepted", action="store_true")

    merge = subparsers.add_parser("merge-blocks", help="merge all accepted block translations")
    merge.add_argument("state")
    merge.add_argument("manifest")
    merge.add_argument("translations")
    merge.add_argument("--extra-translations")

    cleanup = subparsers.add_parser("cleanup-run", help="remove one completed translation task safely")
    cleanup.add_argument("manifest")

    render = subparsers.add_parser("render", help="losslessly render translated units")
    render.add_argument("state")
    render.add_argument("translations")
    render.add_argument("output")
    render.add_argument("--allow-overwrite", action="store_true")

    copy_assets_cmd = subparsers.add_parser(
        "copy-assets",
        help="copy the source's sibling <stem>.assets folder next to an output file",
    )
    copy_assets_cmd.add_argument("source")
    copy_assets_cmd.add_argument("output")

    verify = subparsers.add_parser("verify", help="verify a candidate against deterministic rendering")
    verify.add_argument("state")
    verify.add_argument("translations")
    verify.add_argument("output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "configure":
            result: Any = {
                "config": str(
                    configure_project(
                        args.decider,
                        args.python_path,
                        Path(args.config) if args.config else None,
                        args.output_dir,
                        args.tree_translation == "true"
                        if args.tree_translation is not None
                        else None,
                        args.max_block_chars,
                    )
                )
            }
        elif args.command == "extract":
            result = extract_files(
                Path(args.source),
                Path(args.state),
                Path(args.units),
                Path(args.project_root),
                config_path=Path(args.config) if args.config else None,
                tools_root=Path(args.tools_root) if args.tools_root else None,
            )
        elif args.command == "summarize":
            result = summarize_document(Path(args.state), Path(args.output))
        elif args.command == "record-decisions":
            result = record_decisions(Path(args.state), Path(args.decisions))
        elif args.command == "plan-blocks":
            result = {"manifest": str(plan_blocks(Path(args.state), Path(args.run_dir)))}
        elif args.command == "validate-block":
            result = validate_block(
                Path(args.state),
                Path(args.manifest),
                args.block_id,
                Path(args.output) if args.output else None,
                replace_accepted=args.replace_accepted,
            )
        elif args.command == "merge-blocks":
            result = merge_blocks(
                Path(args.state),
                Path(args.manifest),
                Path(args.translations),
                Path(args.extra_translations) if args.extra_translations else None,
            )
        elif args.command == "cleanup-run":
            result = cleanup_run(Path(args.manifest))
        elif args.command == "render":
            result = render_file(
                Path(args.state),
                Path(args.translations),
                Path(args.output),
                allow_overwrite=args.allow_overwrite,
            )
        elif args.command == "copy-assets":
            result = copy_assets(Path(args.source), Path(args.output))
        else:
            result = verify_file(Path(args.state), Path(args.translations), Path(args.output))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["pass"] else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ConfigRequiredError as exc:
        print(json.dumps({"config_required": True, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3
    except (OSError, ValueError, PipelineError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
