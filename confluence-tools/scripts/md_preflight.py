"""Markdown 上传前只读预审与结构化审核报告。"""

import datetime
import hashlib
import json
import os
import re
import secrets
import shutil
from pathlib import Path
from urllib.parse import unquote

from common import (check_xhtml_balance, compile_inline_math_pattern,
                    inline_math_content)


CODE_RE = re.compile(
    r'```(?!latex\b).*?```|``[^\n]+?``|`[^`\n]+`',
    re.DOTALL | re.IGNORECASE)
LATEX_FENCE_RE = re.compile(r'```latex\b(.*?)```', re.DOTALL | re.IGNORECASE)
BLOCK_MATH_RE = re.compile(r'\$\$(.*?)\$\$', re.DOTALL)
INLINE_MATH_RE = compile_inline_math_pattern(allow_raw_angle_brackets=True)
ASYMMETRIC_INLINE_MATH_RE = re.compile(
    r'(?<!\\)(?<!\$)\$(?:'
    r'(?P<left>[ \t]+(?P<left_content>[^$\n]+?)(?<![ \t]))|'
    r'(?P<right>(?P<right_content>(?![ \t])[^$\n]+?)[ \t]+)'
    r')\$(?!\$)')
IMAGE_RE = re.compile(r'!\[[^\]]*\]\(([^)\n]+)\)')

REVIEW_CLEAN = 'CLEAN'
REVIEW_FIXABLE = 'FIXABLE'
REVIEW_BLOCKED = 'BLOCKED'


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _line_col(text, offset):
    return text.count('\n', 0, offset) + 1, offset - text.rfind('\n', 0, offset)


def _issue(rule_id, severity, text, offset, message):
    line, column = _line_col(text, offset)
    return {
        'rule_id': rule_id,
        'severity': severity,
        'line': line,
        'column': column,
        'message': message,
    }


def _atomic_write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + secrets.token_hex(4))
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _atomic_write_json(path, payload):
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    _atomic_write_bytes(path, data)


def _is_markdown_heading(source, offset):
    line_start = source.rfind('\n', 0, offset) + 1
    prefix = source[line_start:offset]
    return bool(re.match(r'^[ \t]{0,3}#{1,6}[ \t]+', prefix))


def _validate_formula(source, content, offset, kind, issues):
    stack = []
    index = 0
    while index < len(content):
        char = content[index]
        slash_count = 0
        cursor = index - 1
        while cursor >= 0 and content[cursor] == '\\':
            slash_count += 1
            cursor -= 1
        escaped = slash_count % 2 == 1
        if char == '{' and not escaped:
            stack.append(index)
        elif char == '}' and not escaped:
            if not stack:
                issues.append(_issue(
                    'LATEX_BRACE_UNEXPECTED_CLOSE', 'error', source,
                    offset + index, f'{kind} 公式含多余的右花括号'))
                break
            stack.pop()
        index += 1
    if stack:
        issues.append(_issue(
            'LATEX_BRACE_UNCLOSED', 'error', source, offset + stack[-1],
            f'{kind} 公式含未闭合的左花括号'))

    environments = []
    for match in re.finditer(r'\\(begin|end)\s*\{([^{}]+)\}', content):
        action, name = match.groups()
        if action == 'begin':
            environments.append(name)
        elif not environments or environments[-1] != name:
            issues.append(_issue(
                'LATEX_ENVIRONMENT_MISMATCH', 'error', source,
                offset + match.start(),
                f'LaTeX 环境结束不匹配: {name}'))
        else:
            environments.pop()
    if environments:
        issues.append(_issue(
            'LATEX_ENVIRONMENT_UNCLOSED', 'error', source, offset,
            f'LaTeX 环境未闭合: {environments[-1]}'))


def _sanitize_formula(content, fixes):
    repaired, emphasis_count = re.subn(r'</?em>', '_', content,
                                       flags=re.IGNORECASE)
    if emphasis_count:
        fixes.append({
            'rule_id': 'LATEX_MARKDOWN_EMPHASIS_REPAIRED',
            'count': emphasis_count,
            'message': '把公式内部的 em 标签恢复为 LaTeX 下划线',
        })
    repaired, star_count = re.subn(r'\\\*', '*', repaired)
    if star_count:
        fixes.append({
            'rule_id': 'LATEX_INVALID_STAR_REPAIRED',
            'count': star_count,
            'message': '把未定义控制序列 \\* 规范化为 *',
        })
    return repaired


def _has_strong_math_signal(content):
    """Only repair asymmetric spacing when the content is clearly mathematics."""
    return bool(
        re.search(r'\\[A-Za-z]+', content)
        or re.search(r'[_^]\s*(?:\{|[A-Za-z0-9])', content)
        or re.search(
            r'(?:[A-Za-z0-9}\]])\s+[+\-*/=]\s+(?:[A-Za-z0-9\\{[])',
            content))


def _find_asymmetric_formula(segment, cursor):
    for match in ASYMMETRIC_INLINE_MATH_RE.finditer(segment, cursor):
        content = (match.group('left_content')
                   if match.group('left') is not None
                   else match.group('right_content'))
        if _has_strong_math_signal(content):
            return match
    return None


def _formula_matches(segment):
    patterns = (
        ('latex', LATEX_FENCE_RE),
        ('block', BLOCK_MATH_RE),
        ('inline', INLINE_MATH_RE),
        ('inline_asymmetric', _find_asymmetric_formula),
    )
    cursor = 0
    while cursor < len(segment):
        candidates = []
        for kind, pattern in patterns:
            match = (pattern(segment, cursor)
                     if kind == 'inline_asymmetric'
                     else pattern.search(segment, cursor))
            if match:
                candidates.append((match.start(), -match.end(), kind, match))
        if not candidates:
            return
        _start, _end, kind, match = min(candidates)
        yield kind, match
        cursor = match.end()


def _process_text_segment(source, segment, base_offset, counts, fixes, issues):
    candidate = []
    residue = []
    cursor = 0
    for kind, match in _formula_matches(segment):
        candidate.append(segment[cursor:match.start()])
        residue.append(segment[cursor:match.start()])
        if kind in ('inline', 'inline_asymmetric'):
            if kind == 'inline':
                content = inline_math_content(
                    match, repair_markdown_emphasis=True)
            else:
                content = (match.group('left_content')
                           if match.group('left') is not None
                           else match.group('right_content'))
            content_offset = base_offset + match.start() + 1
            canonical = '$' + _sanitize_formula(content, fixes) + '$'
            counts['inline'] += 1
            if _is_markdown_heading(source, base_offset + match.start()):
                counts['heading_inline'] += 1
            if kind == 'inline' and match.group('spaced') is not None:
                fixes.append({
                    'rule_id': 'MATH_SPACING_NORMALIZED',
                    'count': 1,
                    'message': '把对称空格行内公式规范化为紧凑定界符',
                })
            if kind == 'inline_asymmetric':
                fixes.append({
                    'rule_id': 'MATH_ASYMMETRIC_SPACING_REPAIRED',
                    'count': 1,
                    'message': '仅在具有强数学特征时修复单边空格公式',
                })
        else:
            content = match.group(1)
            content_offset = base_offset + match.start(1)
            repaired = _sanitize_formula(content, fixes)
            if kind == 'block':
                canonical = '$$' + repaired + '$$'
                counts['block'] += 1
            else:
                canonical = match.group(0).replace(content, repaired, 1)
                counts['latex_fence'] += 1
        _validate_formula(source, content, content_offset, kind, issues)
        candidate.append(canonical)
        residue.append(''.join('\n' if c == '\n' else ' '
                               for c in match.group(0)))
        cursor = match.end()
    candidate.append(segment[cursor:])
    residue.append(segment[cursor:])
    return ''.join(candidate), ''.join(residue)


def _candidate_and_residue(source, counts, fixes, issues):
    candidate = []
    residue = []
    cursor = 0
    for code in CODE_RE.finditer(source):
        processed, remaining = _process_text_segment(
            source, source[cursor:code.start()], cursor, counts, fixes, issues)
        candidate.append(processed)
        residue.append(remaining)
        candidate.append(code.group(0))
        residue.append(''.join('\n' if c == '\n' else ' '
                               for c in code.group(0)))
        cursor = code.end()
    processed, remaining = _process_text_segment(
        source, source[cursor:], cursor, counts, fixes, issues)
    candidate.append(processed)
    residue.append(remaining)
    return ''.join(candidate), ''.join(residue)


def _check_residual_dollars(source, residue, issues):
    cleaned = re.sub(r'\\\$', '', residue)
    cleaned = re.sub(r'\$(?:[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?)', '', cleaned)
    block = cleaned.find('$$')
    if block >= 0:
        issues.append(_issue(
            'MATH_BLOCK_DELIMITER_UNMATCHED', 'error', source, block,
            '发现未配对的块公式定界符 $$'))
        cleaned = cleaned.replace('$$', '  ')
    dollar = cleaned.find('$')
    if dollar >= 0:
        issues.append(_issue(
            'MATH_INLINE_DELIMITER_UNMATCHED', 'error', source, dollar,
            '发现无法安全识别的行内公式定界符'))


def _check_attachments(source_path, candidate, issues):
    base = Path(source_path).resolve().parent
    attachments = []
    for match in IMAGE_RE.finditer(candidate):
        raw = match.group(1).strip()
        if raw.startswith('<') and raw.endswith('>'):
            raw = raw[1:-1]
        raw = re.sub(r'\{[^{}]*\}\s*$', '', raw).strip()
        if raw.startswith(('http://', 'https://', '//', 'data:', '#')):
            continue
        path = (base / unquote(raw)).resolve()
        if not path.is_file():
            issues.append(_issue(
                'ATTACHMENT_NOT_FOUND', 'error', candidate, match.start(1),
                f'本地附件不存在: {raw}'))
        else:
            attachments.append(str(path))
    return attachments


def review_markdown(source_path, artifact_dir):
    source_path = Path(source_path).resolve()
    raw = source_path.read_bytes()
    issues = []
    fixes = []
    try:
        source = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        source = raw.decode('utf-8', errors='replace')
        issues.append(_issue(
            'ENCODING_NOT_UTF8', 'error', source, 0,
            f'Markdown 不是有效 UTF-8: {exc}'))
    if '\x00' in source:
        issues.append(_issue(
            'NUL_BYTE', 'error', source, source.index('\x00'),
            'Markdown 含 NUL 字符'))

    counts = {'inline': 0, 'heading_inline': 0, 'block': 0,
              'latex_fence': 0}
    candidate, residue = _candidate_and_residue(
        source, counts, fixes, issues)
    _check_residual_dollars(source, residue, issues)
    attachments = _check_attachments(source_path, candidate, issues)

    artifact_dir = Path(artifact_dir)
    review_path = artifact_dir / 'review.json'
    candidate_bytes = candidate.encode('utf-8')
    has_errors = any(item['severity'] == 'error' for item in issues)
    if has_errors:
        status = REVIEW_BLOCKED
    elif fixes or candidate_bytes != raw:
        status = REVIEW_FIXABLE
    else:
        status = REVIEW_CLEAN
    report = {
        'schema_version': 2,
        'source_path': str(source_path),
        'source_sha256': _sha256_bytes(raw),
        'candidate_sha256': _sha256_bytes(candidate_bytes),
        'status': status,
        'passed': not has_errors,
        'formula_counts': counts,
        'fixes': fixes,
        'issues': issues,
        'attachments': attachments,
        'storage_validation': None,
    }
    _atomic_write_json(review_path, report)
    return {
        'passed': report['passed'],
        'status': status,
        'source_path': source_path,
        'review_path': review_path.resolve(),
        'candidate_text': candidate,
        'candidate_bytes': candidate_bytes,
        'report': report,
    }


def validate_storage(result, storage_html, heading_math_mode):
    checks = []
    errors = []
    balanced, description = check_xhtml_balance(storage_html)
    checks.append({'check': 'xhtml_balance', 'passed': balanced,
                   'detail': description})
    if not balanced:
        errors.append(description)

    bare_void = bool(re.search(
        r'<(?:br|hr)(?:\s[^<>]*?)?\s*(?<!/)>', storage_html,
        flags=re.IGNORECASE))
    checks.append({'check': 'confluence_void_elements',
                   'passed': not bare_void})
    if bare_void:
        errors.append('Confluence storage 含未自闭合的 br/hr 标签')

    inline_macros = len(re.findall(
        r'<ac:structured-macro\b[^>]*ac:name=["\']mathinline["\']',
        storage_html))
    block_macros = len(re.findall(
        r'<ac:structured-macro\b[^>]*ac:name=["\']mathblock["\']',
        storage_html))
    counts = result['report']['formula_counts']
    expected_inline = counts['inline']
    if heading_math_mode == 'literal':
        expected_inline -= counts['heading_inline']
    expected_block = counts['block'] + counts['latex_fence']
    macro_ok = inline_macros == expected_inline and block_macros == expected_block
    checks.append({
        'check': 'math_macro_counts',
        'passed': macro_ok,
        'detail': {
            'mathinline': [inline_macros, expected_inline],
            'mathblock': [block_macros, expected_block],
        },
    })
    if not macro_ok:
        errors.append('公式数量与生成的 Confluence 数学宏数量不一致')

    protected = re.sub(
        r'<ac:structured-macro\b[^>]*/>|'
        r'<ac:structured-macro\b.*?</ac:structured-macro>|'
        r'<code[^>]*>.*?</code>|<pre[^>]*>.*?</pre>',
        '', storage_html, flags=re.DOTALL)
    if heading_math_mode == 'literal':
        protected = re.sub(r'<h[1-6]\b[^>]*>.*?</h[1-6]>', '', protected,
                           flags=re.DOTALL)
    residual = bool(BLOCK_MATH_RE.search(protected)
                    or INLINE_MATH_RE.search(protected)
                    or LATEX_FENCE_RE.search(protected))
    checks.append({'check': 'math_residuals', 'passed': not residual})
    if residual:
        errors.append('转换后的正文仍有公式定界符残留')

    placeholder = bool(re.search(
        r'<!--\s*(?:MATH|LATEX|CODE|TOC)_[A-Z_]*\d+_', storage_html))
    checks.append({'check': 'placeholder_residuals',
                   'passed': not placeholder})
    if placeholder:
        errors.append('转换后的 storage 仍有内部占位符残留')

    math_macros = re.findall(
        r'<ac:structured-macro\b'
        r'(?=[^>]*ac:name=["\']math(?:inline|block)["\'])'
        r'[^>]*>.*?</ac:structured-macro>',
        storage_html, flags=re.DOTALL | re.IGNORECASE)
    macro_with_emphasis = any(
        re.search(r'<em\b', macro, flags=re.IGNORECASE)
        for macro in math_macros)
    checks.append({'check': 'markdown_emphasis_in_math',
                   'passed': not macro_with_emphasis})
    if macro_with_emphasis:
        errors.append('数学宏内部仍含 Markdown emphasis 标签')

    result['report']['storage_validation'] = {
        'passed': not errors,
        'checks': checks,
        'errors': errors,
    }
    result['report']['passed'] = result['report']['passed'] and not errors
    result['passed'] = result['report']['passed']
    if errors:
        result['status'] = REVIEW_BLOCKED
        result['report']['status'] = REVIEW_BLOCKED
    _atomic_write_json(result['review_path'], result['report'])
    return not errors, errors


def apply_review_fixes(result, target_path):
    """把确定性候选内容写入明确的修复副本，不修改预审源文件。"""
    if result['status'] != REVIEW_FIXABLE:
        return False
    _atomic_write_bytes(Path(target_path), result['candidate_bytes'])
    return True


def block_review(result, rule_id, message):
    """把正文转换阶段的异常写回结构化报告并阻断上传。"""
    result['report']['issues'].append({
        'rule_id': rule_id,
        'severity': 'error',
        'line': 1,
        'column': 1,
        'message': message,
    })
    result['report']['status'] = REVIEW_BLOCKED
    result['report']['passed'] = False
    result['status'] = REVIEW_BLOCKED
    result['passed'] = False
    _atomic_write_json(result['review_path'], result['report'])


class PreflightRun:
    """管理一次单页或树导入的预审产物。"""

    def __init__(self, logs_root):
        self.logs_root = Path(logs_root)
        self.timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        self.run_token = secrets.token_hex(6)
        self.run_dir = (self.logs_root / 'intermediate' / self.timestamp
                        / self.run_token)
        self.entries = []
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._write_manifest('running')

    def _write_manifest(self, status):
        payload = {
            'schema_version': 1,
            'status': status,
            'created_at': self.timestamp,
            'entries': self.entries,
        }
        _atomic_write_json(self.run_dir / 'manifest.json', payload)

    def review(self, source_path, phase='full'):
        page_dir = self.run_dir / 'pages' / f'{len(self.entries) + 1:04d}'
        result = review_markdown(source_path, page_dir)
        self.entries.append({
            'source_path': str(result['source_path']),
            'review_path': str(result['review_path']),
            'phase': phase,
            'status': result['status'],
            'passed': result['passed'],
        })
        self._write_manifest('running')
        return result

    def refresh(self, result):
        for entry in self.entries:
            if entry['review_path'] == str(result['review_path']):
                entry['passed'] = result['passed']
                entry['status'] = result['status']
                break
        self._write_manifest('running')

    def finish(self, success):
        self._write_manifest('completed' if success else 'failed')
        if not success:
            return self.run_dir
        archive = self.logs_root / '_archive' / self.timestamp / self.run_token
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.run_dir), str(archive))
        intermediate_timestamp = self.run_dir.parent
        try:
            intermediate_timestamp.rmdir()
        except OSError:
            pass
        return archive
