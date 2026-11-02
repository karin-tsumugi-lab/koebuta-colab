"""Lossless, versioned source ledger for the new scenario path.

The legacy core.source_rows hash contract is deliberately not changed here.
Quoted text is a syntactic candidate, never proof of a speaker's identity.
"""
import re

from .core import digest, text
from .text_conversion import FORMATS, convert_with_map, protected_ranges
from .text_map import validate_map

PARSER_VERSION = 1
OPEN = {'「': '」', '『': '』', '“': '”', '"': '"'}
CLOSE = set(OPEN.values())


def parse_source(source, fmt='none', structure_mode='auto', known_labels=()):
    text(source, 'source', 100000)
    if fmt not in FORMATS or structure_mode not in ('auto', 'prose', 'script'):
        raise ValueError('原稿の構造・ルビ形式が不正です')
    labels = set(known_labels)
    if any(not isinstance(n, str) or not n.strip() or len(n) > 50 for n in labels):
        raise ValueError('人物ラベルが不正です')
    document = {'internal_schema': 1, 'parser_version': PARSER_VERSION,
                'revision': digest([source, fmt, structure_mode, sorted(labels), PARSER_VERSION]),
                'source': source, 'source_digest': digest(source),
                'parse_policy': {'format': fmt, 'structure_mode': structure_mode,
                                 'known_labels': sorted(labels)},
                'atoms': [], 'units': [], 'issues': []}

    def issue(code, start, end, message, severity='review', unit_id=None):
        document['issues'].append({'code': code, 'source_span': [start, end],
                                   'severity': severity, 'message': message,
                                   **({'unit_id': unit_id} if unit_id else {})})

    def structure(start, end, kind, rule):
        if start < end:
            document['atoms'].append({'source_span': [start, end], 'kind': kind,
                                      'disposition': 'structure', 'rule': rule,
                                      'unit_id': None})

    def unit(start, end, quote_path, explicit, paragraph, unresolved=False):
        if start == end:
            return
        body = source[start:end]
        if not body.strip():
            structure(start, end, 'layout', 'whitespace'); return
        value, warnings, mapping = convert_with_map(body, fmt)
        key = f'u{len(document["units"]) + 1:06d}'
        kind = ('unresolved' if unresolved else 'labelled' if explicit else
                'quoted' if quote_path else 'prose')
        row = {'id': key, 'source_span': [start, end], 'text': body,
               'baseline_tts': value, 'source_to_baseline': mapping,
               'syntactic_kind': kind, 'quote_path': list(quote_path),
               'paragraph_id': paragraph}
        if explicit:
            row['explicit_speaker'] = explicit
        document['units'].append(row)
        for p in mapping:
            a, b = p['source_span']
            omitted = not p['rendered'] and p['operation'] == 'layout'
            document['atoms'].append({'source_span': [start + a, start + b],
                                      'kind': 'literal' if p['operation'] == 'copy' else p['operation'],
                                      'disposition': 'structure' if omitted else 'spoken',
                                      'rule': p['operation'], 'unit_id': key})
        layout_only = not value.strip() and all(p['operation'] == 'layout' or
                      p['operation'] == 'copy' and not p['rendered'].strip() for p in mapping)
        for warning in ([] if layout_only else warnings):
            issue('conversion_review', start, end, warning, 'blocking', key)

    stack = []; offset = 0; quote_count = 0
    for paragraph_index, line in enumerate(source.splitlines(keepends=True), 1):
        # Keep line endings/indentation in the ledger; no strip/reconstruction.
        end = offset + len(line.rstrip('\r\n'))
        content_start = offset
        while content_start < end and source[content_start].isspace():
            content_start += 1
        structure(offset, content_start, 'layout', 'indentation')
        if content_start == end:
            structure(end, offset + len(line), 'layout', 'line_break')
            offset += len(line); continue
        explicit = None
        body = source[content_start:end]
        ranges = protected_ranges(body, fmt)
        match = re.match(r'^([^：:「\r\n]{1,25}?)([：:]\s*|(?=「))', body)
        if match and not stack and structure_mode != 'prose':
            name = match[1].strip()
            inside_notation = any(a <= match.end(1) < b for a, b in ranges)
            valid = (name and not re.search(r'[。！？!?［］《》\[\]]', name)
                     and not inside_notation)
            if valid and (structure_mode == 'script' or name in labels):
                label_end = content_start + match.end()
                structure(content_start, label_end, 'label', 'explicit_script_label')
                content_start = label_end; explicit = name
            elif valid:
                issue('ambiguous_label', content_start, content_start + match.end(),
                      '台本の人物名か本文かを確認してください。原文は保持しています。')
        # Protect ruby/annotation syntax before interpreting quotes and punctuation.
        ranges = protected_ranges(source[content_start:end], fmt)
        protected = {content_start + a: content_start + b for a, b in ranges}
        start = content_start; cursor = start
        path = [entry[1] for entry in stack]
        while cursor < end:
            if cursor in protected:
                cursor = protected[cursor]; continue
            ch = source[cursor]
            if ch in OPEN and not (ch == '"' and stack and stack[-1][0] == '"'):
                if not stack:
                    unit(start, cursor, path, explicit, paragraph_index)
                    start = cursor
                quote_count += 1
                stack.append((OPEN[ch], f'q{quote_count:06d}', cursor))
                if len(stack) == 1:
                    path = [stack[0][1]]
            elif ch in CLOSE:
                if not stack or ch != stack[-1][0]:
                    issue('unmatched_quote', cursor, cursor + 1, '引用符の対応を確認してください。')
                else:
                    stack.pop()
                    if not stack:
                        unit(start, cursor + 1, path, explicit, paragraph_index)
                        start = cursor + 1; path = []
            elif ch in '。！？!?' and (cursor + 1 == end or source[cursor + 1] not in CLOSE):
                unit(start, cursor + 1, path, explicit, paragraph_index)
                start = cursor + 1
            cursor += 1
        unit(start, end, path, explicit, paragraph_index)
        structure(end, offset + len(line), 'layout', 'line_break')
        offset += len(line)
    for _, _, start in stack:
        issue('unclosed_quote', start, len(source), '閉じていない引用符があります。本文は保持しています。')
    for index, atom in enumerate(document['atoms'], 1):
        atom['id'] = f'a{index:06d}'
    validate_document(document)
    return document


def validate_document(document):
    source = document['source']
    policy = document['parse_policy']
    if (document.get('internal_schema') != 1 or document.get('parser_version') != PARSER_VERSION
            or document.get('revision') != digest([source, policy['format'], policy['structure_mode'],
                                                  policy['known_labels'], PARSER_VERSION])):
        raise ValueError('原文台帳の形式・版が一致しません')
    if document.get('source_digest') != digest(source):
        raise ValueError('原稿のハッシュが一致しません')
    units = {u['id']: u for u in document['units']}
    if len(units) != len(document['units']):
        raise ValueError('意味単位のIDが重複しています')
    cursor = 0; owned = {key: [] for key in units}; seen = set()
    for atom in document['atoms']:
        a, b = atom['source_span']
        if (type(a) is not int or type(b) is not int or a != cursor or not a < b <= len(source)
                or atom['id'] in seen or atom['disposition'] not in ('spoken', 'structure')):
            raise ValueError('原文台帳に欠落・重複・順序変更があります')
        seen.add(atom['id']); cursor = b
        key = atom['unit_id']
        if key is not None:
            if key not in units:
                raise ValueError('原文台帳の意味単位が存在しません')
            owned[key].append(atom)
        elif atom['disposition'] != 'structure':
            raise ValueError('読み上げる原文の所有先がありません')
        elif atom['rule'] not in ('whitespace', 'indentation', 'line_break', 'explicit_script_label'):
            raise ValueError('原文の省略規則が不正です')
        if atom['rule'] in ('whitespace', 'indentation', 'line_break') and source[a:b].strip():
            raise ValueError('本文を空白として省略できません')
    if cursor != len(source):
        raise ValueError('原文台帳に欠落があります')
    previous = 0
    for u in document['units']:
        a, b = u['source_span']
        if a < previous or not a < b <= len(source) or source[a:b] != u['text']:
            raise ValueError('意味単位の原文位置が一致しません')
        previous = b
        validate_map(u['text'], u['baseline_tts'], u['source_to_baseline'])
        expected = [{'source_span': [a + p['source_span'][0], a + p['source_span'][1]],
                     'kind': 'literal' if p['operation'] == 'copy' else p['operation'],
                     'disposition': 'structure' if not p['rendered'] and p['operation'] == 'layout' else 'spoken',
                     'rule': p['operation']} for p in u['source_to_baseline']]
        if [{k: atom[k] for k in expected[0]} for atom in owned[u['id']]] != expected:
            raise ValueError('意味単位と原文台帳の対応が一致しません')
    return True
