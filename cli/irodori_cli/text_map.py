"""Source-owned transformations. Offsets are Unicode code points, end exclusive.

Copies can be cut at any character. A replacement, including an omission, owns
its complete source interval; no length-ratio or repeated-text matching is used.
"""
import copy
import re


class TextMap:
    def __init__(self, source):
        self.source = source
        self.pieces = ([{'source_span': [0, len(source)], 'rendered': source,
                         'operation': 'copy'}] if source else [])

    @property
    def rendered(self):
        return ''.join(p['rendered'] for p in self.pieces)

    def replace(self, start, end, value, operation):
        """Replace a nonempty rendered interval, preserving atomic provenance."""
        if not 0 <= start < end <= len(self.rendered):
            raise ValueError('変換対象の位置が不正です')
        spans = []; cursor = 0
        for piece in self.pieces:
            following = cursor + len(piece['rendered'])
            spans.append((cursor, following)); cursor = following
        first = next(i for i, (a, b) in enumerate(spans) if b > start)
        last = max(i for i, (a, b) in enumerate(spans) if a < end and b > a)
        left, right = self.pieces[first], self.pieces[last]
        a, b = left['source_span'][0], right['source_span'][1]
        prefix = left['rendered'][:start - spans[first][0]]
        suffix = right['rendered'][end - spans[last][0]:]
        before, after = [], []
        if left['operation'] == 'copy' and prefix:
            before = [{'source_span': [a, a + len(prefix)], 'rendered': prefix,
                       'operation': 'copy'}]
            a += len(prefix); prefix = ''
        if right['operation'] == 'copy' and suffix:
            after = [{'source_span': [b - len(suffix), b], 'rendered': suffix,
                      'operation': 'copy'}]
            b -= len(suffix); suffix = ''
        self.pieces[first:last + 1] = [*before, {
            'source_span': [a, b], 'rendered': prefix + value + suffix,
            'operation': operation}, *after]

    def sub(self, pattern, replacement, operation):
        body = self.rendered
        for match in reversed(list(re.finditer(pattern, body))):
            value = replacement(match) if callable(replacement) else match.expand(replacement)
            if value != match[0]:
                self.replace(match.start(), match.end(), value, operation)

    def export(self):
        result = []; cursor = 0
        for piece in self.pieces:
            item = copy.deepcopy(piece)
            item['tts_span'] = [cursor, cursor + len(item['rendered'])]
            item['indivisible'] = item['operation'] != 'copy'
            result.append(item); cursor = item['tts_span'][1]
        validate_map(self.source, self.rendered, result)
        return result


def validate_map(source, rendered, pieces):
    """Reject gaps, overlap, forged copies and stale offsets in either space."""
    a = b = 0
    for p in pieces:
        span, target = p.get('source_span'), p.get('tts_span')
        if (not isinstance(span, list) or not isinstance(target, list)
                or len(span) != 2 or len(target) != 2
                or any(type(v) is not int for v in [*span, *target])
                or span[0] != a or not a < span[1] <= len(source)
                or target[0] != b or not b <= target[1] <= len(rendered)
                or p.get('rendered') != rendered[b:target[1]]
                or p.get('operation') not in ('copy', 'ruby', 'layout', 'escape', 'emphasis', 'ai_reading', 'normalize')
                or p.get('indivisible') is not (p['operation'] != 'copy')):
            raise ValueError('原文と読みの変換マップが一致しません')
        if p['operation'] == 'copy' and source[a:span[1]] != p['rendered']:
            raise ValueError('原文のコピー範囲が変わっています')
        a, b = span[1], target[1]
    if a != len(source) or b != len(rendered):
        raise ValueError('変換マップに欠落があります')


def mapped_boundary(pieces, source_offset):
    """Map a source cut to reading. Return None inside an atomic operation."""
    for p in pieces:
        a, b = p['source_span']; x, y = p['tts_span']
        if source_offset == a:
            return x
        if source_offset == b:
            return y
        if a < source_offset < b:
            return x + source_offset - a if p['operation'] == 'copy' else None
    if not pieces and source_offset == 0:
        return 0
    return None
