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
PYTHON_MODES = {"auto", "explicit"}
MINIMUM_PYTHON = (3, 8)
DEFAULT_TARGET_BLOCK_BYTES = 8000
DEFAULT_MAX_BLOCK_BYTES = 10000
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


def project_config_path(project_root: Path) -> Path:
    return Path(project_root) / ".md2zh_tools" / "config.json"


def python_candidates(
    project_root: Path,
    which=shutil.which,
    platform_name: Optional[str] = None,
    current_executable: Optional[str] = sys.executable,
) -> List[Dict[str, Any]]:
    project_root = Path(project_root)
    platform_name = platform_name or os.name
    suffix = Path("Scripts") / "python.exe" if platform_name == "nt" else Path("bin") / "python"
    candidates: List[Dict[str, Any]] = []
    seen = set()

    def add(command: Sequence[str], source: str) -> None:
        command = [str(item) for item in command]
        key = (os.path.normcase(os.path.abspath(command[0])),) + tuple(command[1:])
        if key not in seen:
            seen.add(key)
            candidates.append({"command": command, "source": source})

    for directory in (".venv", "venv"):
        executable = project_root / directory / suffix
        if executable.is_file():
            add([str(executable)], "project:{}".format(directory))
    for name in ("python", "python3"):
        executable = which(name)
        if executable:
            add([str(executable)], "path:{}".format(name))
    launcher = which("py")
    if launcher:
        add([str(launcher), "-3"], "path:py -3")
    if current_executable and Path(current_executable).is_file():
        add([str(Path(current_executable).resolve())], "current-interpreter")
    return candidates


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
    project_root: Path,
    mode: str,
    python_path: Optional[str] = None,
    runner=subprocess.run,
) -> Dict[str, Any]:
    if mode not in PYTHON_MODES:
        raise ValueError("python mode must be 'auto' or 'explicit'")
    if mode == "explicit":
        if not python_path:
            raise ValueError("python_path is required in explicit mode")
        path = Path(python_path).expanduser()
        if not path.is_absolute():
            raise ValueError("python_path must be absolute")
        if not path.is_file():
            raise PythonRuntimeError("configured Python does not exist: {}".format(path))
        resolved = probe_python([str(path.resolve())], runner=runner)
        resolved["source"] = "explicit"
        return resolved
    if python_path:
        raise ValueError("python_path is not allowed in auto mode")

    errors = []
    for candidate in python_candidates(project_root):
        try:
            resolved = probe_python(candidate["command"], runner=runner)
            resolved["source"] = candidate["source"]
            return resolved
        except PythonRuntimeError as exc:
            errors.append("{}: {}".format(candidate["source"], exc))
    if not errors:
        raise PythonRuntimeError("no Python candidates were found; md2zh requires Python 3.8+")
    raise PythonRuntimeError("no compatible Python 3.8+ runtime was found: {}".format("; ".join(errors)))


def same_executable(left: str, right: str) -> bool:
    try:
        return Path(left).samefile(Path(right))
    except OSError:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def ensure_current_python(project_root: Path, config: Dict[str, Any]) -> Dict[str, Any]:
    python_config = config["python"]
    resolved = resolve_python(
        project_root,
        python_config["mode"],
        python_config.get("path"),
    )
    if not same_executable(sys.executable, resolved["executable"]):
        raise PythonRuntimeError(
            "md2zh must run with {}; current interpreter is {}".format(
                resolved["executable"], sys.executable
            )
        )
    return resolved


def configure_project(
    project_root: Path,
    decider: str,
    python_mode: str,
    python_path: Optional[str] = None,
) -> Path:
    if decider not in CONFIG_VALUES:
        raise ValueError("ambiguous_content_decider must be 'user' or 'ai'")
    path = project_config_path(Path(project_root))
    resolved = resolve_python(project_root, python_mode, python_path)
    if not same_executable(sys.executable, resolved["executable"]):
        raise PythonRuntimeError(
            "configure md2zh with {}; current interpreter is {}".format(
                resolved["executable"], sys.executable
            )
        )
    data: Dict[str, Any] = {}
    if path.exists():
        existing = load_json(path)
        if isinstance(existing, dict):
            data.update(existing)
    data["ambiguous_content_decider"] = decider
    data["python"] = {"mode": python_mode}
    if python_mode == "explicit":
        data["python"]["path"] = str(Path(resolved["executable"]).resolve())
    write_json_atomic(path, data)
    return path


def load_project_config(project_root: Path) -> Dict[str, Any]:
    path = project_config_path(Path(project_root))
    if not path.exists():
        raise ConfigRequiredError(
            "missing {}; ask once for the ambiguity decider and Python runtime mode".format(path)
        )
    data = load_json(path)
    decider = data.get("ambiguous_content_decider") if isinstance(data, dict) else None
    if decider not in CONFIG_VALUES:
        raise PipelineError("invalid ambiguous_content_decider in {}".format(path))
    python_config = data.get("python")
    if not isinstance(python_config, dict):
        raise ConfigRequiredError(
            "missing Python runtime selection in {}; ask only for explicit or auto mode".format(path)
        )
    mode = python_config.get("mode")
    if mode not in PYTHON_MODES:
        raise PipelineError("invalid Python runtime mode in {}".format(path))
    if mode == "explicit":
        configured_path = python_config.get("path")
        if not isinstance(configured_path, str) or not configured_path:
            raise PipelineError("missing explicit Python path in {}".format(path))
        python_config = {"mode": mode, "path": configured_path}
    else:
        if "path" in python_config:
            raise PipelineError("auto Python mode must not contain a path in {}".format(path))
        python_config = {"mode": mode}
    return {"ambiguous_content_decider": decider, "python": python_config}


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
        lines.extend((segment_marker(block_id, number), unit["template"]))
    return "\n".join(lines) + ("\n" if lines else "")


def build_translation_blocks(
    units: Sequence[Dict[str, Any]],
    target_bytes: int = DEFAULT_TARGET_BLOCK_BYTES,
    max_bytes: int = DEFAULT_MAX_BLOCK_BYTES,
) -> List[Dict[str, Any]]:
    if target_bytes <= 0 or max_bytes < target_bytes:
        raise ValueError("block byte budgets must satisfy 0 < target <= max")

    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_bytes = 0
    for unit in units:
        estimated_marker = "@@MD2ZH:SEG:block-0000:0000@@"
        entry_bytes = len((estimated_marker + "\n" + unit["template"] + "\n").encode("utf-8"))
        starts_new_line = not current or unit["line_start"] != current[-1]["line_start"]
        natural_boundary = unit["kind"] == "heading" and current_bytes >= target_bytes
        hard_boundary = current_bytes + entry_bytes > max_bytes
        if current and starts_new_line and (natural_boundary or hard_boundary):
            groups.append(current)
            current = []
            current_bytes = 0
        current.append(unit)
        current_bytes += entry_bytes
    if current:
        groups.append(current)

    blocks: List[Dict[str, Any]] = []
    for number, group in enumerate(groups, 1):
        block_id = "block-{:04d}".format(number)
        surface = translation_block_surface(group, block_id)
        sections = [unit["section"] for unit in group if unit["section"]]
        blocks.append(
            {
                "id": block_id,
                "unit_ids": [unit["id"] for unit in group],
                "unit_count": len(group),
                "line_start": group[0]["line_start"],
                "line_end": group[-1]["line_end"],
                "section_start": sections[0] if sections else "",
                "section_end": sections[-1] if sections else "",
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
    timestamp: Optional[str] = None,
    target_block_bytes: int = DEFAULT_TARGET_BLOCK_BYTES,
    max_block_bytes: int = DEFAULT_MAX_BLOCK_BYTES,
) -> Dict[str, Any]:
    source_path = Path(source_path).resolve(strict=True)
    state_path = Path(state_path)
    units_path = Path(units_path)
    project_root = Path(project_root).resolve(strict=True)
    config = load_project_config(project_root)
    runtime = ensure_current_python(project_root, config)
    raw = source_path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PipelineError("source must be UTF-8 or UTF-8 with BOM: {}".format(exc)) from exc
    if RESERVED_NAMESPACE_RE.search(text):
        raise PipelineError("source contains the reserved MD2ZH marker namespace")

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

    for index, line in enumerate(lines):
        content = line["content"]
        if index in protected_lines:
            continue
        if index in footnote_continuations:
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
            start = line["start"] + len(footnote.group(1))
            end = line["start"] + len(content.rstrip(" \t"))
            if start < end:
                add_unit(start, end, "footnote", line["number"], section)
            continue
        directive = DIRECTIVE_RE.match(content)
        if directive and LATIN_RE.search(directive.group("payload")):
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
            continue
        relative_start, relative_end, kind, is_heading = span
        if index in setext_headings:
            kind = "heading"
            is_heading = True
        item = add_unit(
            line["start"] + relative_start,
            line["start"] + relative_end,
            kind,
            line["number"],
            section,
        )
        if is_heading:
            heading_text = content[relative_start:relative_end]
            heading_template, _ = inline_template(heading_text, "section", reference_ids)
            section = visible_template_text(heading_template).strip() or section
            if item:
                item["section"] = section

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
    log_directory = Path(".md2zh_tools") / "decision_logs"
    log_name = "{}.{}.{}.jsonl".format(source_path.stem, source_hash[:8], timestamp)
    log_relative = log_directory / log_name
    log_path = project_root / log_relative
    suffix = 2
    while log_path.exists():
        log_name = "{}.{}.{}.{}.jsonl".format(source_path.stem, source_hash[:8], timestamp, suffix)
        log_relative = log_directory / log_name
        log_path = project_root / log_relative
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
        state_units, target_bytes=target_block_bytes, max_bytes=max_block_bytes
    )
    state = {
        "schema_version": 3,
        "project_root": str(project_root),
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
        "schema_version": 2,
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
        "decision_log": str(log_path),
    }


def decision_log_path(state: Dict[str, Any]) -> Path:
    return Path(state["project_root"]) / Path(state["decision_log"])


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
    intermediate_root = (
        Path(state["project_root"]) / ".md2zh_tools" / "intermediate"
    ).resolve()
    if run_dir == intermediate_root or not path_is_within(run_dir, intermediate_root):
        raise PipelineError("block run directory must be a child of .md2zh_tools/intermediate")

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
    expected_line_count = len(block["unit_ids"]) * 2
    if len(lines) != expected_line_count:
        raise TranslationValidationError(
            "{} changed segment or physical-line boundaries".format(block["id"])
        )
    units_by_id = {unit["id"]: unit for unit in state["units"]}
    translations: Dict[str, str] = {}
    for index, unit_id in enumerate(block["unit_ids"]):
        marker = lines[index * 2]
        translated = lines[index * 2 + 1]
        if marker != segment_marker(block["id"], index + 1):
            raise TranslationValidationError(
                "{} must preserve segment lines in source order".format(block["id"])
            )
        if not translated.strip():
            raise TranslationValidationError("{} has an empty translation".format(unit_id))
        if SEGMENT_ANY_RE.search(translated):
            raise TranslationValidationError("{} contains a misplaced segment marker".format(unit_id))
        validate_translated_template(units_by_id[unit_id], translated)
        translations[unit_id] = translated
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
    intermediate_root = (
        Path(state["project_root"]) / ".md2zh_tools" / "intermediate"
    ).resolve()
    if (
        manifest_path.name != "manifest.json"
        or run_dir.name != "run"
        or task_dir.parent != intermediate_root
        or not path_is_within(state_path, task_dir)
    ):
        raise PipelineError("refusing to clean an invalid block run path")
    if not path_is_within(run_dir, task_dir):
        raise PipelineError("refusing to clean a block run outside .md2zh_tools/intermediate")
    unfinished = [block["id"] for block in manifest.get("blocks", []) if block["status"] != "accepted"]
    if unfinished:
        raise PipelineError("refusing to clean an unfinished block run: {}".format(unfinished[:10]))
    shutil.rmtree(str(task_dir))
    return {"removed": str(task_dir), "exists_after": task_dir.exists()}


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
    if "\n" in translated or "\r" in translated:
        raise TranslationValidationError("{} translation must not change physical line boundaries".format(unit["id"]))
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
    if kind == "text" and block_pattern.match(translated) and not block_pattern.match(original):
        raise TranslationValidationError("{} introduced a block-level Markdown marker".format(label))


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser(
        "configure", help="store the project ambiguity decider and Python runtime"
    )
    configure.add_argument("project_root")
    configure.add_argument("--decider", choices=sorted(CONFIG_VALUES), required=True)
    configure.add_argument("--python-mode", choices=sorted(PYTHON_MODES), required=True)
    configure.add_argument("--python-path")

    extract = subparsers.add_parser("extract", help="extract translator-facing translation blocks")
    extract.add_argument("source")
    extract.add_argument("--state", required=True)
    extract.add_argument("--blocks", "--units", dest="units", required=True)
    extract.add_argument("--project-root", required=True)

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
                        Path(args.project_root),
                        args.decider,
                        args.python_mode,
                        args.python_path,
                    )
                )
            }
        elif args.command == "extract":
            result = extract_files(
                Path(args.source),
                Path(args.state),
                Path(args.units),
                Path(args.project_root),
            )
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
