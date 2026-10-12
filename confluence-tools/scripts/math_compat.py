"""Known Confluence / MathJax 2.7.9 compatibility rules, not a TeX renderer.

Only formula payloads are rewritten. Source Markdown and surrounding storage
remain the caller's responsibility; see references/math-compatibility-rules.md.
"""

import html
import re
import xml.etree.ElementTree as ET


PROFILE = 'confluence-mathjax-2.7.9'
_TOKEN = re.compile(r'\\(?:[A-Za-z]+|[\s\S])|%[^\n]*(?:\n|$)')
_EXTENSIONS = {
    'AMSmath': frozenset('lVert rVert lvert rvert boxed substack xrightarrow '
                         'mathring dddot ddddot binom operatorname'.split()),
    'AMSsymbols': frozenset('leqslant geqslant triangleq square varnothing'.split()),
    'mediawiki-texvc': frozenset(('oiint', 'vline')),
    'cancel': frozenset(('cancel',)),
}
_CUSTOM = frozenset(('def', 'gdef', 'edef', 'xdef', 'let', 'newcommand',
                     'renewcommand', 'providecommand', 'DeclareMathOperator'))
_TAG = re.compile(
    r'<!\[CDATA\[.*?\]\]>|<!--.*?-->|'
    r'</?[\w:-]+\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*>', re.DOTALL)
_ATTR = re.compile(r'([\w:-]+)\s*=\s*(["\'])(.*?)\2', re.DOTALL)


class MathCompatibilityError(ValueError):
    """A formula needs manual review before a remote write."""


def _commands(tex):
    return (m for m in _TOKEN.finditer(tex) if m.group().startswith('\\'))


def _skip_space(tex, cursor, end):
    while cursor < end:
        if tex[cursor].isspace():
            cursor += 1
        elif tex[cursor] == '%':
            newline = tex.find('\n', cursor, end)
            cursor = end if newline < 0 else newline + 1
        else:
            break
    return cursor


def _argument(tex, cursor, end):
    """Return a TeX argument token/group span without expanding macros."""
    start = _skip_space(tex, cursor, end)
    if start == end or tex[start] == '}':
        raise ValueError('缺少公式命令参数')
    if tex[start] != '{':
        token = _TOKEN.match(tex, start, end)
        return start, token.end() if token else start + 1
    cursor = start + 1
    depth = 1
    while cursor < end:
        token = _TOKEN.match(tex, cursor, end)
        if token:
            cursor = token.end()
            continue
        if tex[cursor] == '{':
            depth += 1
        elif tex[cursor] == '}':
            depth -= 1
            if not depth:
                return start, cursor + 1
        cursor += 1
    raise ValueError('公式命令参数的花括号未闭合')


def _matrix_brace(tex, cursor, end):
    """Locate only a left brace enclosing matrix with an invisible right side."""
    brace = _skip_space(tex, cursor, end)
    if tex[brace:brace + 2] != r'\{':
        return None
    opening = _TOKEN.match(tex, _skip_space(tex, brace + 2, end), end)
    if not opening or opening.group() != r'\begin':
        return None
    a, b = _argument(tex, opening.end(), end)
    if tex[a:b] != '{matrix}':
        return None
    environments = ['{matrix}']
    for token in _TOKEN.finditer(tex, b, end):
        if token.group() not in (r'\begin', r'\end'):
            continue
        a, finish = _argument(tex, token.end(), end)
        environment = tex[a:finish]
        if token.group() == r'\begin':
            environments.append(environment)
        elif environments[-1] != environment:
            raise ValueError('左大括号内的矩阵环境未正确配对')
        else:
            environments.pop()
            if environments:
                continue
            right = _TOKEN.match(tex, _skip_space(tex, finish, end), end)
            if right and right.group() == r'\right':
                delimiter = _skip_space(tex, right.end(), end)
                if delimiter < end and tex[delimiter] == '.':
                    return brace
            return None
    raise ValueError('左大括号内的矩阵环境未闭合')


def assess_formula(tex):
    """Return a candidate and located known-rule diagnostics; never write files.

    Offsets refer to the original formula. An unresolved formula is returned
    unchanged. Success covers only this rule set, not arbitrary TeX validity.
    """
    changes, issues = [], []

    def issue(offset, message):
        issues.append({'rule_id': 'MATH_COMPAT_REVIEW_REQUIRED',
                       'severity': 'error', 'offset': offset, 'message': message})

    def changed(rule_id, offset, message):
        changes.append({'rule_id': rule_id, 'offset': offset, 'message': message})

    for token in _commands(tex):
        name = token.group()[1:]
        if name in ('multicolumn', 'cline'):
            issue(token.start(), '\\' + name + ' 涉及矩阵结构，需人工复核，不能全局替换')
        elif name in _CUSTOM:
            issue(token.start(), '\\' + name + ' 含自定义宏，需人工确认命令语义')

    def rewrite(start, end):
        parts, cursor = [], start
        for token in _TOKEN.finditer(tex, start, end):
            if token.start() < cursor or not token.group().startswith('\\'):
                continue
            name = token.group()[1:]
            if name not in ('dfrac', 'operatorname', 'wideparen', 'iddots', 'left'):
                continue
            replacement, finish = token.group(), token.end()
            try:
                if name == 'left':
                    brace = _matrix_brace(tex, finish, end)
                    if brace is None:
                        continue
                    replacement = tex[token.start():brace] + r'\lbrace'
                    finish = brace + 2
                elif name == 'dfrac':
                    a, b = _argument(tex, finish, end)
                    c, d = _argument(tex, b, end)
                    replacement = (r'{\displaystyle\frac' + tex[finish:a]
                                   + rewrite(a, b) + tex[b:c] + rewrite(c, d) + '}')
                    finish = d
                elif name == 'operatorname':
                    arg_start = _skip_space(tex, finish, end)
                    starred = arg_start < end and tex[arg_start] == '*'
                    a, b = _argument(tex, arg_start + int(starred), end)
                    arg = tex[a:b]
                    label = arg[1:-1] if arg.startswith('{') else arg
                    following = _skip_space(tex, b, end)
                    explicit_limits = re.match(r'\\(?:no)?limits(?![A-Za-z])', tex[following:])
                    simple = (re.fullmatch(r'[A-Za-z0-9]+', label)
                              or label in (r'B\acute{e}zier', r'SB\acute{e}zier'))
                    if not simple or explicit_limits:
                        # Preserve AMS typography / SkipLimits semantics.
                        parts.append(tex[cursor:b])
                        cursor = b
                        continue
                    replacement = r'\mathop{\mathrm{' + label + '}}'
                    replacement += ' ' if starred else r'\nolimits '
                    finish = b
                elif name == 'wideparen':
                    a, b = _argument(tex, finish, end)
                    arg = tex[a:b]
                    label = arg[1:-1] if arg.startswith('{') else arg
                    if not re.fullmatch(r'[A-Z]+', label):
                        issue(token.start(), r'\wideparen 仅自动处理大写字母圆弧标签；此参数需人工复核')
                        continue
                    replacement = r'\overset{\mmlToken{mo}[stretchy=true]{⏜}}{' + label + '}'
                    finish = b
                else:
                    replacement = r'\mathinner{⋰}'
                changed('MATH_COMPAT_MATRIX_LBRACE' if name == 'left'
                        else 'MATH_COMPAT_' + name.upper(), token.start(),
                        '\\' + name + ' 转为已验证的兼容写法')
            except ValueError as exc:
                issue(token.start(), str(exc) + ': \\' + name)
                continue
            parts.extend((tex[cursor:token.start()], replacement))
            cursor = finish
        return ''.join(parts) + tex[cursor:end]

    candidate = tex if issues else rewrite(0, len(tex))
    present, commands = set(), set()
    for token in _commands(candidate):
        name = token.group()[1:]
        commands.add(name)
        if name == 'require':
            try:
                a, b = _argument(candidate, token.end(), len(candidate))
                present.add(candidate[a:b].strip('{}').strip())
            except ValueError:
                issue(token.start(), r'\require 的扩展名参数无效')
    required = [ext for ext, names in _EXTENSIONS.items() if names & commands]
    if 'vline' in commands and 'AMSmath' not in required:
        required.insert(0, 'AMSmath')
    missing = [ext for ext in required if ext not in present]
    if missing:
        candidate = ''.join(r'\require{' + ext + '} ' for ext in missing) + candidate
        changed('MATH_COMPAT_REQUIRE', 0, '显式加载扩展: ' + ', '.join(missing))
    return {'profile': PROFILE, 'text': tex if issues else candidate,
            'changes': [] if issues else changes, 'issues': issues,
            'renderer_validation': 'not_run'}


def normalize_math_storage(storage):
    """Patch native math bodies in place, including math inside rich-text macros.

    A small XML token stack avoids scanning code, comments or CDATA as markup.
    Only changed payload slices are serialized; macro IDs and other bytes stay.
    """
    stack, replacements, changes, issues = [], [], [], []
    formulas = changed_formulas = 0
    for token in _TAG.finditer(storage):
        raw = token.group()
        if raw.startswith('<!'):
            continue
        tag = re.match(r'</?([\w:-]+)', raw).group(1).lower()
        if raw.startswith('</'):
            if not stack or stack[-1]['tag'] != tag:
                continue  # XHTML balance is checked separately by callers.
            frame = stack.pop()
            if 'body_start' not in frame:
                continue
            start, end = frame['body_start'], token.start()
            location = {'formula': frame['formula'], 'storage_offset': start}
            try:
                payload = ET.fromstring('<payload>' + storage[start:end] + '</payload>')
                if len(payload):
                    raise ValueError('数学宏正文含嵌套标签，需人工复核')
                tex = payload.text or ''
            except (ET.ParseError, ValueError) as exc:
                issues.append(dict(location, rule_id='MATH_COMPAT_REVIEW_REQUIRED',
                                   severity='error', offset=0, message=str(exc)))
                continue
            assessed = assess_formula(tex)
            changes.extend(dict(c, **location) for c in assessed['changes'])
            issues.extend(dict(i, **location) for i in assessed['issues'])
            if assessed['text'] == tex:
                continue
            if tag == 'ac:plain-text-body':
                encoded = '<![CDATA[' + assessed['text'].replace(']]>', ']]]]><![CDATA[>') + ']]>'
            else:
                encoded = html.escape(assessed['text'], quote=False)
            replacements.append((start, end, encoded))
            changed_formulas += 1
            continue
        attrs = {m.group(1).lower(): html.unescape(m.group(3)) for m in _ATTR.finditer(raw)}
        parent = stack[-1] if stack else {}
        macro = attrs.get('ac:name', '') if tag == 'ac:structured-macro' else ''
        protected = (parent.get('protected', False) or tag in ('code', 'pre')
                     or macro in ('code', 'noformat'))
        frame = {'tag': tag, 'macro': macro, 'protected': protected}
        if macro in ('mathinline', 'mathblock') and not protected:
            formulas += 1
            frame['formula'] = formulas
        body = (tag == 'ac:plain-text-body'
                or tag == 'ac:parameter' and attrs.get('ac:name') == 'body')
        if body and parent.get('macro') in ('mathinline', 'mathblock') and not protected:
            frame.update(body_start=token.end(), formula=parent['formula'])
        if not raw.endswith('/>'):
            stack.append(frame)
    result = storage
    for start, end, replacement in reversed(replacements):
        result = result[:start] + replacement + result[end:]
    return result, {'profile': PROFILE, 'formulas': formulas,
                    'changed_formulas': changed_formulas, 'changes': changes,
                    'issues': issues, 'passed': not issues,
                    'renderer_validation': 'not_run'}
