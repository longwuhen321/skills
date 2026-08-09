"""Locate Markdown fenced and inline code while preserving source offsets."""
import re


FENCE_OPEN = re.compile(
    r'^[ \t>]*(?P<marker>`{3,}|~{3,})(?P<rest>[^\r\n]*)$'
)


def _is_escaped(value, pos):
    backslashes = 0
    pos -= 1
    while pos >= 0 and value[pos] == '\\':
        backslashes += 1
        pos -= 1
    return backslashes % 2 == 1


def _scan_fenced_code(text):
    spans = []
    offset = 0
    fence_start = None
    fence_char = None
    fence_size = None

    for line in text.splitlines(keepends=True):
        content = line.rstrip('\r\n')
        if fence_start is None:
            match = FENCE_OPEN.match(content)
            if match:
                marker = match.group('marker')
                rest = match.group('rest')
                if marker[0] != '`' or '`' not in rest:
                    fence_start = offset
                    fence_char = marker[0]
                    fence_size = len(marker)
        else:
            close = re.fullmatch(
                rf'[ \t>]*{re.escape(fence_char)}{{{fence_size},}}[ \t]*',
                content,
            )
            if close:
                spans.append((fence_start, offset + len(line)))
                fence_start = None
                fence_char = None
                fence_size = None
        offset += len(line)

    unclosed_start = fence_start
    if unclosed_start is not None:
        spans.append((unclosed_start, len(text)))
    return spans, unclosed_start


def _fenced_code_spans(text):
    return _scan_fenced_code(text)[0]


def markdown_fenced_code_spans(text):
    """Return fenced-code spans, including an unclosed fence through EOF."""
    return _fenced_code_spans(text)


def unclosed_fence_start(text):
    """Return the source offset of an unclosed fence, or None."""
    return _scan_fenced_code(text)[1]


def _find_backtick_close(text, start, end, size):
    pos = start
    while pos < end:
        pos = text.find('`' * size, pos, end)
        if pos < 0:
            return -1
        before_is_tick = pos > start and text[pos - 1] == '`'
        after = pos + size
        after_is_tick = after < end and text[after] == '`'
        if not before_is_tick and not after_is_tick and not _is_escaped(text, pos):
            return pos
        pos = after
    return -1


def _inline_code_spans(text, fenced_spans):
    spans = []
    regions = []
    start = 0
    for fence_start, fence_end in fenced_spans:
        regions.append((start, fence_start))
        start = fence_end
    regions.append((start, len(text)))

    for region_start, region_end in regions:
        pos = region_start
        while pos < region_end:
            pos = text.find('`', pos, region_end)
            if pos < 0:
                break
            run_end = pos + 1
            while run_end < region_end and text[run_end] == '`':
                run_end += 1
            if _is_escaped(text, pos):
                pos = run_end
                continue
            close = _find_backtick_close(
                text, run_end, region_end, run_end - pos
            )
            if close < 0:
                pos = run_end
                continue
            close_end = close + (run_end - pos)
            spans.append((pos, close_end))
            pos = close_end
    return spans


def markdown_code_spans(text):
    """Return sorted, non-overlapping fenced and inline code spans."""
    fenced = markdown_fenced_code_spans(text)
    return sorted(fenced + _inline_code_spans(text, fenced))


def mask_markdown_code(text):
    """Replace code characters with spaces, preserving newlines and offsets."""
    masked = list(text)
    for start, end in markdown_code_spans(text):
        for pos in range(start, end):
            if masked[pos] not in '\r\n':
                masked[pos] = ' '
    return ''.join(masked)


def transform_outside_markdown_code(text, transform):
    """Apply transform only to text outside fenced and inline code."""
    pieces = []
    pos = 0
    for start, end in markdown_code_spans(text):
        pieces.append(transform(text[pos:start]))
        pieces.append(text[start:end])
        pos = end
    pieces.append(transform(text[pos:]))
    return ''.join(pieces)
